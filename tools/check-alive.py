#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie que les SERVICES du rack sont VIVANTS — pas « configurés », pas « présents » : VIVANTS.

    ./tools/check-alive.py                # sur le rack (bridge + Reaper allumés), ~20 s
    ./tools/check-alive.py --window 8     # fenêtre d'observation plus large (services lents)
    ./tools/check-alive.py --dry-run      # hors rig : autotest des parseurs sur les fichiers locaux

POURQUOI CE SCRIPT EXISTE
C'est LA classe de régression n°1 du dépôt : une piste de service sans entrée, sans item et non
armée SORT du graphe temps réel de Reaper dès qu'elle se tait — son @block s'arrête, et comme
l'ordre de départ arrive par gmem (un canal que Reaper ne voit pas), plus rien ne peut la
réveiller. Cinq victimes recensées : le standard (verrou `latch`), le click (muet dès la
création de sa piste), la boîte à rythmes, le sample, et la piste « MIDI Clock » — dont l'arrêt
a privé l'AKAI d'horloge EN SILENCE alors que l'en-tête du script jurait le contraire.
Et par-dessus : Reaper ne sait pas dire que sa carte son a disparu (13 h de silence le
2026-08-08 avec `reaper_running: true · 0 xrun`). Le SEUL fait honnête est un compteur du
thread audio qui n'avance plus.

CE QU'IL VÉRIFIE
1. Les témoins de vivacité, lus DEUX FOIS à `--window` secondes d'écart :
   · .clock.json  {ticks,t}  — `t` avance = la boucle Lua vit ; `ticks` avance = le THREAD
     AUDIO vit. `t` qui avance avec `ticks` figé = carte perdue (le discriminant du CLAUDE.md).
   · .click.json — réécrit ≤1 s (mtime = pouls du Lua) ; si le click est actif (`on` ou
     `clock`), son compteur `ticks` doit avancer (JSFX @sample vivant).
   · .standard.json — `hb` est incrémenté par le JSFX golem_chordseq à chaque @block, et une
     instance PERMANENTE vit sur la piste Click : `hb` figé = piste hors du graphe vivant.
   · .midi.json — `ts` avance (~5 s de période) = la sentinelle mesure ; `ok`/`issues` = le
     contrat MIDI est tenu (qui possède l'AKAI, qui possède la carte son).
2. L'ARMEMENT des pistes de service (chunkdump) : RECARM=1 et I_RECMODE=2 (« aucun ») dans le
   chunk — le vaccin posé après les cinq pannes. Une piste dés-armée est une rechute CERTAINE.

CE QU'IL NE PEUT PAS VOIR (limites assumées)
· .drums.json et .sample.json ne sont écrits QUE sur changement de signature : aucune double
  lecture ne peut prouver leur vivacité — on vérifie leur présence/parse et l'armement des
  pistes, c'est tout ce que les fichiers permettent.
· Que ça SONNE. Un @block qui tourne n'est pas une preuve que le haut-parleur vibre.

Lecture seule : aucun état modifié (chunkdump est une sonde read-only).
Les commandes passent par bridge.commands.write_command (slot presets/.command.json) ; la
consommation est PROUVÉE par l'ACK {seq,t} que golem_watch écrit dans .command-ack.json —
l'ack dit « lu », le fichier de sortie qui change dit « fait » : on attend les deux.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS = os.path.join(ROOT, "presets")
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
CHUNK_LOG = os.path.join(PRESETS, ".chunk.log")
OK, KO, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m⚠\033[0m"
fails = []

# Les pistes de service et le Lua qui les possède. `permanent` : créée au boot par __startup —
# son absence est une panne. Les pistes Standard, Drums et Sample, elles, naissent au PREMIER PLAY de leur bloc
# (`op_play` → `ensure_track`, qui les ARME à chaque appel). ⚠ Corrigé le 2026-10-08 : Drums et Sample étaient
# déclarées permanentes — après une relance de Reaper sans preset qui les joue, le script criait à la panne
# sur deux pistes simplement pas encore nées (le code, lui, les arme à la création : le vaccin tient).
SERVICE_TRACKS = [
    ("Click",          "golem_click.lua",    True),
    ("Drums",          "golem_drums.lua",    False),
    ("Sample",         "golem_sample.lua",   False),
    ("MIDI Clock",     "golem_clock.lua",    True),
    ("Standard Keys",  "golem_chordseq.lua", False),
    ("Standard Bass",  "golem_chordseq.lua", False),
    ("Standard Drums", "golem_chordseq.lua", False),
    ("Standard Guitar", "golem_chordseq.lua", False),
]


def check(cond, label, detail=""):
    print(f"  {OK if cond else KO} {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(label)
    return cond


def read_json(name):
    """(données, mtime_ns) du témoin — (None, None) si absent/illisible (jamais fatal)."""
    p = os.path.join(PRESETS, name)
    try:
        st = os.stat(p)
        with open(p, encoding="utf-8") as f:
            return json.load(f), st.st_mtime_ns
    except (OSError, ValueError):
        return None, None


def _acked(seq):
    """golem_watch a-t-il CONSOMMÉ notre commande ? (.command-ack.json {seq,t}, audit 2026-08-12).
    L'ack est posé AVANT l'exécution : il prouve « lu », pas « fait »."""
    from bridge.commands import _ack_path
    try:
        return int(json.load(open(_ack_path(seq))).get("seq") or 0) >= seq
    except (OSError, ValueError):
        return None                                   # pas d'ack (golem_watch d'avant l'audit ?)


def send_cmd(cmd, outfile, timeout=8.0):
    """Écrit la commande via bridge.commands.write_command (qui rend le `seq` et n'écrase
    jamais un slot pas encore lu), attend l'ACK de consommation, PUIS que le fichier de
    sortie change. Rend le texte du fichier, ou None — en DISANT à quel étage ça a échoué."""
    sys.path.insert(0, ROOT)
    from bridge.commands import write_command
    try:
        before = os.stat(outfile).st_mtime_ns
    except OSError:
        before = None
    seq = write_command(cmd)
    t0, seen_ack = time.time(), False
    while time.time() - t0 < timeout:
        if not seen_ack:
            got = _acked(seq)
            if got:
                seen_ack = True
            elif got is None:
                seen_ack = True                       # pas d'ack sur ce rack : repli mtime seul
        try:
            if os.stat(outfile).st_mtime_ns != before:
                time.sleep(0.08)                      # petite grâce : l'écriture Lua n'est pas atomique
                return open(outfile, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
        time.sleep(0.12)
    if _acked(seq) is False:
        print(f"    (commande « {cmd.get('action')} » JAMAIS consommée — golem_watch/Reaper "
              "éteint ? gel SETTLE post-rebuild ?)")
    return None


def parse_rec_line(chunk):
    """(arm, recmode, ligne brute) depuis la PREMIÈRE ligne `REC …` du chunk (niveau piste —
    elle précède toujours le bloc <FXCHAIN). Format observé sur le rack :
        REC <arm> <input> <monitor> <recmode> …    ex. armé/mode-aucun : REC 1 -1 1 2 …
    Rend (None, None, None) si la ligne manque ou surprend — on le DIT, on n'invente pas."""
    for line in chunk.splitlines():
        line = line.strip()
        if line.startswith("REC "):
            toks = line.split()
            if len(toks) >= 5:
                try:
                    return int(toks[1]), int(toks[4]), line
                except ValueError:
                    return None, None, line
            return None, None, line
    return None, None, None


def snapshot():
    """Une lecture de TOUS les témoins, d'un coup (les deux passes doivent être comparables)."""
    out = {}
    for key, fn in (("clock", ".clock.json"), ("click", ".click.json"),
                    ("standard", ".standard.json"), ("midi", ".midi.json"),
                    ("drums", ".drums.json"), ("sample", ".sample.json")):
        out[key] = read_json(fn)
    return out


def verdict_clock(s1, s2):
    c1, _ = s1["clock"]
    c2, _ = s2["clock"]
    if c1 is None or c2 is None:
        check(False, ".clock.json présent", "absent/illisible — golem_clock.lua ne publie pas "
              "(Reaper lancé ? __startup passé ?)")
        return
    t_moves = c2.get("t") != c1.get("t")
    check(t_moves, "clock : la boucle Lua publie (`t` avance)",
          f"t {c1.get('t')} → {c2.get('t')}")
    if not t_moves:
        return                       # `t` figé = Reaper/boucle : ce n'est pas la panne carte-son
    # LE discriminant honnête : `t` avance + `ticks` figé = thread audio mort (carte perdue).
    check(c2.get("ticks") != c1.get("ticks"),
          "clock : LE THREAD AUDIO AVANCE (`ticks`)",
          f"ticks {c1.get('ticks')} → {c2.get('ticks')}" if c2.get("ticks") != c1.get("ticks")
          else f"ticks figé à {c1.get('ticks')} pendant que t avance — carte son perdue ? "
               "(récupération : commande audio_reset)")


def verdict_click(s1, s2):
    d1, m1 = s1["click"]
    d2, m2 = s2["click"]
    if d1 is None or d2 is None:
        check(False, ".click.json présent", "absent/illisible — golem_click.lua ne publie pas")
        return
    # golem_click.lua réécrit le fichier au moins toutes les ~1 s : le mtime est son pouls.
    check(m2 != m1, "click : la boucle Lua publie (mtime avance)")
    check(bool(d2.get("present")), "click : piste + JSFX présents (`present`)",
          "" if d2.get("present") else "le Lua ne voit ni sa piste ni son FX")
    active = bool(d2.get("on")) or bool(d2.get("clock"))
    if active:
        moved = d2.get("ticks") != d1.get("ticks")
        check(moved, "click ACTIF : le compteur `ticks` avance (@sample vivant)",
              f"{d1.get('ticks')} → {d2.get('ticks')}" if moved else
              f"figé à {d1.get('ticks')} — piste Click hors du graphe vivant "
              "(la panne du 2026-08-07 : armer, I_RECMODE 2)")
        check((d2.get("tempo") or 0) > 0, "click ACTIF : `tempo` non nul",
              f"{d2.get('tempo')} BPM")
    else:
        print("  ·   click OFF — compteur à l'arrêt : attendu (run=0), rien à prouver ici")


def verdict_standard(s1, s2):
    d1, m1 = s1["standard"]
    d2, m2 = s2["standard"]
    if d1 is None or d2 is None:
        check(False, ".standard.json présent",
              "absent/illisible — golem_chordseq.lua ne s'est jamais lancé (__startup ?)")
        return
    # `hb` est incrémenté par le JSFX à chaque @block ; l'instance PERMANENTE de la piste Click
    # suffit à le faire avancer même sans grille chargée. hb figé = le verrou du 2026-08-08.
    moved = d2.get("hb") != d1.get("hb")
    check(moved, "standard : le heartbeat `hb` du JSFX avance",
          f"hb {d1.get('hb')} → {d2.get('hb')}" if moved else
          f"hb figé à {d1.get('hb')}" + (" (fichier non réécrit non plus)" if m1 == m2 else "")
          + " — piste Click/Standard hors du graphe vivant, OU gmem écrasé (piège re-attach), "
            "OU boucle golem_chordseq.lua morte")
    if bool(d2.get("playing")):
        pos1, pos2 = (d1.get("bar"), d1.get("beat")), (d2.get("bar"), d2.get("beat"))
        check(pos1 != pos2, "standard EN LECTURE : la tête avance (bar/beat)",
              f"{pos1} → {pos2}")


def verdict_midi(s1, window):
    d1, _ = s1["midi"]
    if d1 is None:
        check(False, ".midi.json présent",
              "absent/illisible — la sentinelle golem_midi.lua ne tourne pas")
        return
    # La sentinelle publie toutes les ~5 s : une fenêtre de 4 s peut légitimement tomber entre
    # deux écritures. On attend donc jusqu'à (période + marge) APRÈS la fenêtre avant de conclure.
    ts1, deadline = d1.get("ts"), time.time() + max(0.0, 7.0 - window)
    d2 = d1
    while time.time() < deadline:
        d2, _ = read_json(".midi.json")
        if d2 and d2.get("ts") != ts1:
            break
        time.sleep(0.5)
    d2 = d2 or {}
    check(d2.get("ts") != ts1, "midi : la sentinelle mesure encore (`ts` avance)",
          f"{ts1} → {d2.get('ts')}")
    issues = list(d2.get("issues") or [])
    check(bool(d2.get("ok")) and not issues, "midi : le contrat des ports est tenu (`ok`)",
          "" if d2.get("ok") else " · ".join(issues) +
          (f"  →  {d2.get('fix')}" if d2.get("fix") else ""))


def verdict_presence_only(s2, key, lua):
    d, _ = s2[key]
    if d is None:
        check(False, f".{key}.json présent",
              f"absent/illisible — {lua} ne s'est jamais lancé (__startup ?)")
        return
    check(bool(d.get("present")), f"{key} : témoin lisible (`present`)",
          f"{len(d.get('blocks') or {})} bloc(s) suivi(s)")
    print(f"  ·   {key} : vivacité NON mesurable par le témoin (écrit sur changement "
          "seulement) — l'armement de la piste, plus bas, est la vraie garde")


def check_arming():
    print("\n── 2. Armement des pistes de service (le vaccin des 5 pannes) ──")
    for name, lua, permanent in SERVICE_TRACKS:
        chunk = send_cmd({"action": "chunkdump", "track": name}, CHUNK_LOG)
        if chunk is None:
            check(False, f"« {name} » : chunkdump répond",
                  "Reaper/golem_watch muet ? (ou slot .command.json écrasé — relancer)")
            continue
        if chunk.startswith("piste introuvable") or chunk.startswith("aucune piste"):
            if permanent:
                check(False, f"« {name} » : la piste existe",
                      f"introuvable — {lua} ne l'a pas créée (service jamais lancé ?)")
            else:
                print(f"  ·   « {name} » pas encore créée (naît au premier play) — rien à vérifier")
            continue
        arm, recmode, raw = parse_rec_line(chunk)
        if arm is None:
            check(False, f"« {name} » : ligne REC lisible",
                  f"format inattendu : {raw!r} — vérifier le parseur, pas le rack")
            continue
        check(arm == 1, f"« {name} » : ARMÉE (RECARM 1)",
              "" if arm == 1 else f"dés-armée — elle sortira du graphe vivant dès qu'elle se "
                                  f"tait (rechute certaine, {lua}) · {raw}")
        check(recmode == 2, f"« {name} » : I_RECMODE 2 (« aucun » — n'écrit jamais de fichier)",
              "" if recmode == 2 else f"recmode {recmode} — armée pour VIVRE, pas pour "
                                      f"enregistrer · {raw}")


# ── autotest hors rig : les parseurs, sur les fichiers présents + échantillons figés ────────
REC_SAMPLES = [("REC 1 -1 1 2 0 0 0 0", 1, 2), ("REC 0 -1 0 0 0 0 0 0", 0, 0)]


def dry_run():
    print("── dry-run : autotest des parseurs (ne prouve RIEN sur le rack) ──")
    for raw, want_arm, want_mode in REC_SAMPLES:
        arm, mode, _ = parse_rec_line(raw)
        check((arm, mode) == (want_arm, want_mode), f"parse REC : {raw!r}",
              f"arm={arm} recmode={mode}")
    if os.path.exists(CHUNK_LOG):
        arm, mode, raw = parse_rec_line(open(CHUNK_LOG, encoding="utf-8", errors="replace").read())
        check(raw is not None, "parse REC sur presets/.chunk.log (vrai chunk)",
              f"{raw!r} → arm={arm} recmode={mode}")
    s = snapshot()
    for key in ("clock", "click", "standard", "midi", "drums", "sample"):
        d, _ = s[key]
        if d is None:
            print(f"  ·   .{key}.json absent ici (normal hors rack)")
        else:
            check(isinstance(d, dict), f".{key}.json parse", json.dumps(d)[:70])
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description="Vivacité des services (témoins + armement).")
    ap.add_argument("--window", type=float, default=4.0,
                    help="secondes entre les deux lectures des témoins (défaut 4)")
    ap.add_argument("--dry-run", action="store_true",
                    help="autotest local des parseurs, sans toucher au rig")
    a = ap.parse_args()
    if a.dry_run:
        return dry_run()
    window = max(2.0, a.window)          # sous 2 s, les témoins à 1 Hz ne peuvent pas répondre
    if window != a.window:
        print(f"{WARN} fenêtre relevée à {window:.0f} s (les témoins publient à ~1 Hz)")

    try:
        st = json.load(urllib.request.urlopen(BRIDGE + "/api/state", timeout=5))
        if not st.get("reaper_running"):
            print(f"{WARN} le bridge dit Reaper ÉTEINT — tout ce qui suit devrait être rouge")
    except Exception:
        print(f"{WARN} bridge injoignable ({BRIDGE}) — on continue sur les fichiers/commandes "
              "locaux (les témoins n'ont pas besoin de lui)")

    print(f"\n── 1. Témoins de vivacité (deux lectures à {window:.0f} s d'écart) ──")
    s1 = snapshot()
    time.sleep(window)
    s2 = snapshot()
    verdict_clock(s1, s2)
    verdict_click(s1, s2)
    verdict_standard(s1, s2)
    verdict_midi(s1, window)
    verdict_presence_only(s2, "drums", "golem_drums.lua")
    verdict_presence_only(s2, "sample", "golem_sample.lua")

    check_arming()

    print("\n" + "=" * 64)
    if fails:
        print(f"{KO} {len(fails)} échec(s) : " + " · ".join(fails[:6]))
    else:
        print(f"{OK} tout est vert — les services sont dans le graphe vivant.")
    print(f"\n{WARN} Ce que ce script ne voit pas : que ça SONNE (un @block qui tourne n'est "
          "pas un haut-parleur\nqui vibre), la vivacité fine de drums/sample (témoins écrits "
          "sur changement seulement), et\nl'arrivée réelle de l'horloge MIDI dans l'AKAI "
          "(là, c'est l'arpégiateur du clavier qui répond).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
