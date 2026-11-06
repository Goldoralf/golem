# SPDX-License-Identifier: GPL-3.0-or-later
"""Le CLICK D'UNE PRISE ARMÉE (docs/compo.md §12, lot B) — un fichier audio, pas le métronome.

Pourquoi un fichier : le Click du rack est un JSFX qui tourne librement, et la prise démarre par
une commande (la gigue d'un tick `defer`, ~30 ms). Rien ne relie donc le « 1 » que l'on entend au
premier échantillon du fichier enregistré — et golem.fm doit poser la prise SUR le riff. Un
fichier joué par la piste Backing, lui, est sur la TIMELINE de Reaper, que la prise démarre à 0 :
le premier temps tombe exactement à `downbeat_s` dans le fichier, par construction.

WAV mono 16 bits, 48 kHz, sans dépendance (le bridge n'a pas numpy). Le décompte est plus fort que
le click de la prise ; le « 1 » de chaque mesure est accentué.
"""
import math
import os
import struct

SR = 48000


LOOP_MAX_S = 600.0             # une prise EN BOUCLE (passes 0) s'arrête seule au plus tard ici — disque et fichier


def bar_seconds(bpm, num, den):
    return num * (4.0 / den) * 60.0 / bpm


def timing(take):
    """(beat_s, bar_s, downbeat_s, total_s) d'une prise armée `take = {bpm, sig, count_in, bars, passes}`.
    `passes: 0` = EN BOUCLE jusqu'au Stop : `total_s` est alors le plafond LOOP_MAX_S."""
    num, den = take["sig"]["num"], take["sig"]["den"]
    beat = (4.0 / den) * 60.0 / take["bpm"]
    bar = beat * num
    down = take["count_in"] * bar
    if not take.get("passes"):
        return beat, bar, down, max(LOOP_MAX_S, down + take["bars"] * bar)
    return beat, bar, down, down + take["bars"] * take["passes"] * bar


def _blip(freq, gain, dur=0.035):
    n = int(SR * dur)
    return [min(1.0, gain) * math.sin(2 * math.pi * freq * i / SR) * (1 - i / n) ** 2 for i in range(n)]


def _pcm(samples):
    return b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767)))) for v in samples)


def gains(level_db):
    """Les amplitudes du click, CALÉES SUR golem_click.jsfx : `gain = 10^(level/20)`, accent ×1, autres
    temps ×0,708 (−3 dB). Le décompte +6 dB au-dessus (plafonné) : on doit entendre le « 1 » qui arrive.
    Un seul réglage pour tous les clicks — le Level du bloc Click (2026-09-30 : « on ne l'entend pas
    assez » ; le click des riffs avait ses propres amplitudes, figées, que rien ne réglait)."""
    g = 10 ** (float(level_db) / 20.0)
    rec = (g, g * 0.708)
    cnt = (min(0.95, g * 2.0), min(0.95, g * 2.0 * 0.708))
    return {(True, True): cnt[0], (True, False): cnt[1], (False, True): rec[0], (False, False): rec[1]}


def render(take, path, level_db=-12.0):
    """Écrit le click de la prise dans `path` : décompte puis (si `click == "always"`) la prise entière,
    plus une mesure de silence, au NIVEAU du bloc Click (`level_db`). Rend la durée écrite, en secondes.
    Assemblé TEMPS PAR TEMPS en octets (blip + silence jusqu'au temps suivant, positions arrondies à
    l'échantillon depuis l'origine — aucune dérive) : une boucle de 10 min se rend en un instant."""
    beat, bar, down, total = timing(take)
    num = take["sig"]["num"]
    amp = gains(level_db)
    blips = {(c, a): _pcm(_blip(1760 if a else 1320, amp[(c, a)])) for c in (True, False) for a in (True, False)}
    n_total = int(round((total + bar) * SR))
    beats_total = int(round(total / beat)) if take.get("click", "always") == "always" else int(round(down / beat))
    out, pos = [], 0
    for k in range(beats_total):
        start = int(round(k * beat * SR))
        nxt = min(int(round((k + 1) * beat * SR)), n_total)
        if start >= n_total:
            break
        if start > pos:
            out.append(b"\x00\x00" * (start - pos))
        blip = blips[(k * beat < down - 1e-6, k % num == 0)][: 2 * (nxt - start)]
        out.append(blip)
        pos = start + len(blip) // 2
    if n_total > pos:
        out.append(b"\x00\x00" * (n_total - pos))
    data = b"".join(out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16))
        f.write(b"data" + struct.pack("<I", len(data)) + data)
    os.replace(tmp, path)
    return n_total / SR
