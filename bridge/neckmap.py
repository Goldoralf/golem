# SPDX-License-Identifier: GPL-3.0-or-later
"""LA CARTE DU MANCHE d'une guitare : l'empreinte de chaque case, une preuve de plus pour le doigté (2026-11-01).

Deux positions d'une même note ne sonnent pas pareil : une corde plus grosse raccourcie n'a pas les partiels d'une
corde plus fine plus longue. On enregistre la guitare case par case (une ronde par case, corde par corde : la
« phase 1 » de la séance du 30/10), et chaque case garde son empreinte — l'amplitude de ses 12 premiers partiels,
en dB sous le plus fort, PENTE RETIRÉE (jouer fort rend la note plus brillante partout, pas à une case donnée).
Une note transcrite dont la hauteur a plusieurs positions est comparée à l'empreinte de chacune ; l'écart à la plus
proche devient un coût du doigté (`fingering.fingering`, `fp`).

L'empreinte d'une note dépend de la longueur qu'on en lit : une double croche n'a pas le spectre d'une ronde. La
carte garde donc chaque case lue sur plusieurs fenêtres (`WINDOWS_S`) et compare une note à la fenêtre la plus
proche de la sienne.

Mesuré sur la 8 cordes du mainteneur (banc ~/golem-doc-work/neck, 2026-11-01) : apprise sur la phase 1, la carte place
170/190 notes de la phase 2 (une autre séance, attaques douces et fortes) sur la bonne corde (hasard : 51) ; ses
erreurs sont toujours la corde voisine. Dans le doigté : riffs 305/307/308 47/66 -> 53/66 corde et case, rondes
47/48 inchangées.

La carte est un fichier LOCAL à la machine (`config/neckmap/<guitare>.json`, jamais commité) que le profil de la
guitare désigne (`config/string-calib.json`, clé `neckmap`). Sans carte, rien ne change. numpy et soundfile,
importés à l'appel : ce module tourne dans `.venv-transcribe`.
"""
from __future__ import annotations

import json
import os

#: Partiels lus.
N_PARTIALS = 12
#: Fenêtres de lecture (s) : la note comparée à la fenêtre la plus proche de sa durée.
WINDOWS_S = (0.06, 0.08, 0.10, 0.13, 0.16, 0.20, 0.25, 0.30, 0.40)
#: On saute le tout début de l'attaque (le médiator, pas la corde).
SKIP_S = 0.015
#: Plancher d'un partiel absent, sous le plus fort (dB).
FLOOR_DB = -60.0
NFFT = 1 << 15
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "neckmap")


def _hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def fingerprint(y, sr, t0, t1, midi):
    """L'empreinte d'une note jouée entre t0 et t1 (s) : N_PARTIALS valeurs (dB, pente retirée), ou None trop court."""
    import numpy as np
    seg = y[int(t0 * sr):int(t1 * sr)]
    if len(seg) < 512:
        return None
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), NFFT))
    freqs = np.fft.rfftfreq(NFFT, 1 / sr)
    ls = np.log(spec + 1e-9)
    f0 = _hz(midi)
    # f1 affinée à ±60 cents par la somme des 6 premiers partiels : la guitare n'est jamais au cent près
    bf = max((f0 * 2 ** (c / 1200) for c in np.linspace(-60, 60, 61)),
             key=lambda f: sum(ls[int(round(n * f * NFFT / sr))] for n in range(1, 7) if n * f < sr / 2))
    a = []
    for n in range(1, N_PARTIALS + 1):
        # vers le haut, la fenêtre s'élargit avec n² : l'inharmonicité pousse les partiels aigus
        i0, i1 = np.searchsorted(freqs, [n * bf * 0.985, n * bf * (1.015 + 0.0006 * n * n)])
        a.append(20 * np.log10(spec[i0:i1].max() + 1e-12) if i0 < i1 < len(freqs) else np.nan)
    a = np.array(a)
    a = np.maximum(a - np.nanmax(a), FLOOR_DB)
    x = np.log2(np.arange(1, N_PARTIALS + 1))
    m = ~np.isnan(a)
    k, b = np.polyfit(x[m], a[m], 1)
    return [None if np.isnan(v) else round(float(v), 2) for v in a - (k * x + b)]


def _window(dur):
    return min(WINDOWS_S, key=lambda w: abs(w - max(WINDOWS_S[0], min(WINDOWS_S[-1], dur))))


def build(takes, tuning, out):
    """La carte d'une guitare à partir de ses prises de rondes : `takes` = {corde: dossier de prise}, une ronde par
    mesure de la case 0 à la dernière (take.json : downbeat_s, bpm, sig, bars). `tuning` grave -> aigu, cordes
    numérotées comme en MusicXML (1 = la plus aiguë)."""
    import numpy as np
    import soundfile as sf
    n = len(tuning)
    cells = {}
    for s, d in takes.items():
        man = json.load(open(os.path.join(d, "take.json"), encoding="utf-8"))
        di = [ln["files"]["di"] for ln in man.get("lanes") or [] if (ln.get("files") or {}).get("di")][0]
        y, sr = sf.read(os.path.join(d, di), always_2d=True)
        y = y[:, 0]
        bar = 60.0 / man["bpm"] * man["sig"]["num"]
        for f in range(man["bars"]):
            a = int((man["downbeat_s"] + f * bar - 0.05) * sr)
            env = np.convolve(np.abs(y[a:a + sr // 2]), np.ones(256) / 256, mode="same")
            on = (a + int(np.argmax(env))) / sr                  # l'attaque, dans la première demi-seconde
            midi = tuning[n - int(s)] + f
            cells[f"{s}:{f}"] = {str(w): fingerprint(y, sr, on + SKIP_S, on + SKIP_S + w, midi) for w in WINDOWS_S}
    doc = {"_doc": "Carte du manche (bridge/neckmap.py) : empreinte de chaque case « corde:case » par fenêtre (s).",
           "tuning": list(tuning), "partials": N_PARTIALS, "windows": list(WINDOWS_S),
           "from": {str(s): os.path.basename(os.path.normpath(d)) for s, d in takes.items()}, "cells": cells}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, out)
    return doc


def load(name):
    """La carte nommée par un profil de guitare (`neckmap`), ou None (absente, illisible, d'un autre format)."""
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        return None
    try:
        doc = json.load(open(os.path.join(DIR, name + ".json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if doc.get("partials") == N_PARTIALS and isinstance(doc.get("cells"), dict) else None


def costs(y, sr, events, nmap, tuning):
    """Pour chaque note SEULE à plusieurs positions : {(corde, case): écart à la plus proche (0 pour elle)} ; None
    pour un accord, une note trop courte ou une seule position. `events` = [(t0, t1, hauteurs)]."""
    import numpy as np
    n = len(tuning)
    out = []
    for t0, t1, ps in events:
        if len(ps) != 1:
            out.append(None)
            continue
        w = _window(t1 - t0 - 0.02)
        u = fingerprint(y, sr, t0 + SKIP_S, t0 + SKIP_S + w, ps[0])
        d = {}
        for i, o in enumerate(tuning):
            s, f = n - i, ps[0] - o
            ref = ((nmap["cells"].get(f"{s}:{f}") or {}).get(str(w))) if f >= 0 else None
            if u is None or ref is None:
                continue
            a = np.array([np.nan if v is None else v for v in u], float)
            b = np.array([np.nan if v is None else v for v in ref], float)
            m = ~(np.isnan(a) | np.isnan(b))
            if m.any():
                d[(s, f)] = float(np.sqrt(np.mean((a[m] - b[m]) ** 2)))
        if len(d) < 2:
            out.append(None)
            continue
        lo = min(d.values())
        out.append({k: v - lo for k, v in d.items()})
    return out


if __name__ == "__main__":
    # python -m bridge.neckmap <guitare> <prise corde 1> … <prise corde N>  (dans .venv-transcribe)
    import sys
    from bridge import inharm
    gid, dirs = sys.argv[1], sys.argv[2:]
    g = inharm.guitar(inharm.CALIB, gid)
    if len(dirs) != len(g["tuning"]):
        sys.exit(f"{gid} a {len(g['tuning'])} cordes : une prise par corde, de la corde 1 (aiguë) à la plus grave")
    doc = build({i + 1: d for i, d in enumerate(dirs)}, g["tuning"], os.path.join(DIR, gid + ".json"))
    print(f"{len(doc['cells'])} cases -> {os.path.join(DIR, gid + '.json')}")
