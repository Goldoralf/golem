#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie le ROUTAGE des sends Reaper — MIDI coupé, modes, sorties hardware.

    ./tools/check-routing.py              # sur le rack (bridge + Reaper allumés), ~15 s
    ./tools/check-routing.py --dry-run    # hors rig : autotest des parseurs (chunk local + échantillons)

POURQUOI CE SCRIPT EXISTE
Deux pannes de la même famille, longues à trouver, faciles à re-créer :
· UN SEND REAPER TRANSPORTE LE MIDI PAR DÉFAUT, tous canaux. golem_super8 (le looper) est
  piloté nativement par des NOTES — pile la plage des pads d'un MPK Mini. Les notes du clavier
  descendaient dans le looper par le send de la lane Keys : le pad 3 faisait alterner une boucle
  play/stop sans fin. Le piège a DORMI six semaines, réveillé le jour où l'AKAI est revenu.
  Règle posée depuis (golem_rig/golem_perfrec) : I_MIDIFLAGS=31 (« no MIDI ») sur tout send qui
  ne doit porter que du son. Ce script vérifie que la règle TIENT — dans le chunk, pas au log.
· L'INDEX DE SEND FAUX = ÉCRITURE NO-OP SILENCIEUSE : le « quirk cat 0 » qui n'existait pas a
  laissé le send DI du perf-rec en post-fader — DI et mix identiques OCTET POUR OCTET sur
  24 prises. Le mode du send (PRE-FX = 1) ne se prouve qu'en le RELISANT du chunk.

CE QU'IL VÉRIFIE (au chunk, la seule autorité)
1. Les receives de « Recording » (perf-rec) : post-fader (mode 0) et MIDI coupé (31).
2. Les receives de « Looper » : MIDI coupé (31) — LE piège super8.
3. Balayage des pistes Sandbox/services : tout send qui porte de l'AUDIO a le MIDI coupé ;
   un send MIDI-seul VOULU (root → enfant-instrument) se reconnaît à srcchan = -1 et est listé,
   pas condamné.
4. Le send DI (« Recording:DI … ») est en PRE-FX (mode 1) — vérifiable SEULEMENT pendant une
   prise multi+DI : ces pistes sont éphémères. Hors prise, le script le dit et n'invente rien.
5. Les sorties hardware : chaque piste que mixer_dump connaît a bien un HWOUT, sur un canal
   qui EXISTE sur la carte (outputs_count de config/io.json).

FORMAT DU CHUNK (mesuré sur le rack, presets/.chunk.log du 2026-08)
    AUXRECV <src> <mode> <vol> <pan> <mute> <mono> <phase> <srcchan> <dstchan> <panlaw:U> <midi> <auto> ''
    HWOUT   <dst> <?> <vol> …
Le jeton panlaw (« -1:U ») sert d'ANCRE : le MIDI est le jeton SUIVANT (31 = coupé, confirmé
sur les receives du Looper posés par golem_rig). Une ligne qui ne porte pas l'ancre est déclarée
« format inattendu » — verdict suspendu, jamais inventé (mieux vaut un check étroit et sûr).

LIMITES ASSUMÉES
· Lecture seule (chunkdump/peaks/mixer_dump sont des sondes read-only) — rien à restaurer.
· On ne prouve pas que le SON arrive aux baffles (ça, c'est volume/MONITOR — cf. mémoire
  « baffles muets = volume d'abord »), ni la correspondance rôle-par-rôle du patch d'entrées.
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS = os.path.join(ROOT, "presets")
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
CHUNK_LOG = os.path.join(PRESETS, ".chunk.log")
PEAKS_JSON = os.path.join(PRESETS, ".peaks.json")
MIXER_JSON = os.path.join(PRESETS, ".mixerdump.json")
OK, KO, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m⚠\033[0m"
MIDI_NONE = 31          # I_MIDIFLAGS : 5 bits bas = canal source, 31 = « none » (pas de MIDI)
fails = []

# pistes balayées à l'étape 3 (en plus des Sandbox*) : les destinations sensibles et les
# services qui reçoivent de l'audio.
SWEEP_EXTRA = ["Looper", "Recording", "Backing Track", "Click", "Drums", "Sample"]


def check(cond, label, detail=""):
    print(f"  {OK if cond else KO} {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(label)
    return cond


def _acked(seq):
    from bridge.commands import _ack_path
    try:
        return int(json.load(open(_ack_path(seq))).get("seq") or 0) >= seq
    except (OSError, ValueError):
        return None


def send_cmd(cmd, outfile, timeout=8.0):
    """write_command (rend le `seq`, n'écrase jamais un slot pas encore lu) → attend que le
    fichier de sortie change. L'ACK de golem_watch (.command-ack.json) dit si la commande a
    seulement été lue quand rien ne sort."""
    sys.path.insert(0, ROOT)
    from bridge.commands import write_command
    try:
        before = os.stat(outfile).st_mtime_ns
    except OSError:
        before = None
    seq = write_command(cmd)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if os.stat(outfile).st_mtime_ns != before:
                time.sleep(0.08)              # l'écriture Lua n'est pas atomique : petite grâce
                return open(outfile, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
        time.sleep(0.1)
    if _acked(seq) is False:
        print(f"    (commande « {cmd.get('action')} » jamais consommée — golem_watch/Reaper "
              "éteint ? gel SETTLE post-rebuild ?)")
    return None


def chunkdump(track):
    """Chunk texte de la piste, None si pas de réponse, "" si piste introuvable."""
    txt = send_cmd({"action": "chunkdump", "track": track}, CHUNK_LOG)
    if txt is None:
        return None
    if txt.startswith("piste introuvable") or txt.startswith("aucune piste"):
        return ""
    return txt


def parse_auxrecv(line):
    """Une ligne AUXRECV → dict, ou {"error": …} si le format surprend (verdict suspendu).
    L'ancre est le jeton panlaw (contient ':') ; le MIDI est le jeton SUIVANT — position
    CONFIRMÉE sur le rack : les receives du Looper posés par golem_rig y lisent bien 31."""
    t = line.split()
    if not t or t[0] != "AUXRECV" or len(t) < 4:
        return {"error": f"pas une ligne AUXRECV : {line!r}"}
    anchor = next((i for i, x in enumerate(t) if ":" in x and i > 3), None)
    if anchor is None or anchor + 1 >= len(t) or anchor < 5:
        return {"error": f"ancre panlaw introuvable : {line!r}"}
    try:
        return {"src": int(t[1]), "mode": int(t[2]),
                "srcchan": int(t[anchor - 2]), "dstchan": int(t[anchor - 1]),
                "midi": int(t[anchor + 1]), "raw": line.strip()}
    except ValueError:
        return {"error": f"jetons non numériques : {line!r}"}


def parse_hwout(line):
    """Une ligne HWOUT → {dst, mono, base}. dst ≥ 1024 = send MONO (base = dst - 1024)."""
    t = line.split()
    if not t or t[0] != "HWOUT" or len(t) < 2:
        return {"error": f"pas une ligne HWOUT : {line!r}"}
    try:
        dst = int(t[1])
    except ValueError:
        return {"error": f"canal illisible : {line!r}"}
    mono = dst >= 1024
    return {"dst": dst, "mono": mono, "base": dst - 1024 if mono else dst, "raw": line.strip()}


def chunk_lines(chunk, keyword):
    """Les lignes `keyword …` du NIVEAU PISTE (avant le premier <FXCHAIN — les données FX
    peuvent contenir n'importe quoi, on ne les lit pas)."""
    out = []
    for line in chunk.splitlines():
        s = line.strip()
        if s.startswith("<FXCHAIN"):
            break
        if s.startswith(keyword + " "):
            out.append(s)
    return out


def midi_verdict(rcv):
    """(ok, libellé) pour un receive : audio → MIDI doit être coupé ; MIDI-seul voulu → listé."""
    if "error" in rcv:
        return None, rcv["error"]
    if rcv["srcchan"] == -1:                  # send MIDI-SEUL voulu (root → enfant-instrument)
        return True, f"MIDI-seul VOULU (srcchan -1, flags {rcv['midi']}) — routage instrument"
    if rcv["midi"] == MIDI_NONE:
        return True, "MIDI coupé (31)"
    return False, (f"MIDI OUVERT (flags {rcv['midi']}) sur un send audio — le piège super8 : "
                   f"poser I_MIDIFLAGS=31 · {rcv['raw']}")


def names_map():
    """{numéro 1-based: nom} + {nom: hw_sends} via la sonde peaks (read-only)."""
    txt = send_cmd({"action": "peaks", "clear": False}, PEAKS_JSON)
    if txt is None:
        return None, None
    idx, hw = {}, {}
    try:
        for row in json.loads(txt):
            m = re.match(r"^(\d+) (.*)$", row.get("track") or "")
            if m:
                idx[int(m.group(1))] = m.group(2)
                hw[m.group(2)] = row.get("hw_sends")
    except ValueError:
        return None, None
    return idx, hw


def check_receives(track, tmap, want_mode=None, context=""):
    """Toutes les lignes AUXRECV d'une piste : MIDI coupé (+ mode si exigé)."""
    chunk = chunkdump(track)
    if chunk is None:
        check(False, f"« {track} » : chunkdump répond", "Reaper/golem_watch muet ?")
        return
    if chunk == "":
        print(f"  ·   « {track} » absente — rien à vérifier ici"
              + (f" ({context})" if context else ""))
        return
    rcvs = [parse_auxrecv(l) for l in chunk_lines(chunk, "AUXRECV")]
    if not rcvs:
        print(f"  ·   « {track} » : aucun receive" + (f" ({context})" if context else ""))
        return
    for r in rcvs:
        src = tmap.get(r.get("src", -1) + 1, f"piste #{r.get('src')}") if "error" not in r else "?"
        okm, why = midi_verdict(r)
        if okm is None:
            check(False, f"« {track} » ← {src} : ligne AUXRECV lisible", why)
            continue
        check(okm, f"« {track} » ← {src} : pas de MIDI clandestin", why if not okm else why)
        if want_mode is not None and "error" not in r and r["srcchan"] != -1:
            check(r["mode"] == want_mode,
                  f"« {track} » ← {src} : mode {want_mode} "
                  + ("(post-fader)" if want_mode == 0 else "(PRE-FX)"),
                  f"mode relu {r['mode']}" + ("" if r["mode"] == want_mode else f" · {r['raw']}"))


def check_hwouts(track, outputs_count, hw_counts):
    chunk = chunkdump(track)
    if chunk is None:
        check(False, f"« {track} » : chunkdump répond", "Reaper/golem_watch muet ?")
        return
    if chunk == "":
        check(False, f"« {track} » : la piste du mixer existe encore",
              "mixer_dump la connaît mais le chunk ne la trouve plus")
        return
    hws = [parse_hwout(l) for l in chunk_lines(chunk, "HWOUT")]
    if not check(len(hws) > 0, f"« {track} » : au moins une sortie hardware (HWOUT)",
                 "aucune — la piste est muette aux baffles (route_monitor pas passé ?)"):
        return
    for h in hws:
        if "error" in h:
            check(False, f"« {track} » : ligne HWOUT lisible", h["error"])
            continue
        width = 1 if h["mono"] else 2
        check(h["base"] + width <= outputs_count,
              f"« {track} » : HWOUT sur un canal qui EXISTE "
              f"({'mono' if h['mono'] else 'stéréo'} base {h['base'] + 1})",
              f"carte : {outputs_count} sortie(s)" if h["base"] + width <= outputs_count else
              f"base {h['base']} + {width} > {outputs_count} sorties — send dans le vide · {h['raw']}")
    want = hw_counts.get(track)
    if want is not None and want != len(hws):
        print(f"  {WARN} « {track} » : {len(hws)} HWOUT au chunk mais peaks en compte {want} "
              "(les deux sondes divergent — relancer)")


# ── autotest hors rig ───────────────────────────────────────────────────────────────────────
SAMPLES = [
    # (ligne, midi attendu, mode, srcchan) — la 1re vient du VRAI chunk du rack (Looper)
    ("AUXRECV 3 0 1 0 0 0 0 0 4 -1:U 31 -1 ''", 31, 0, 0),
    ("AUXRECV 4 0 1 0 0 0 0 0 0 -1:U 0 -1 ''", 0, 0, 0),      # MIDI ouvert → doit être flaggé
    ("AUXRECV 2 1 1 0 0 0 0 -1 0 -1:U 0 -1 ''", 0, 1, -1),    # MIDI-seul voulu (srcchan -1)
]


def dry_run():
    print("── dry-run : autotest des parseurs (ne prouve RIEN sur le rack) ──")
    for line, midi, mode, srcchan in SAMPLES:
        r = parse_auxrecv(line)
        good = ("error" not in r and r["midi"] == midi and r["mode"] == mode
                and r["srcchan"] == srcchan)
        check(good, f"parse AUXRECV : …{line[8:40]}…",
              f"midi={r.get('midi')} mode={r.get('mode')} srcchan={r.get('srcchan')}")
    r = parse_hwout("HWOUT 0 0 1 0 0 0 0 -1:U -1")
    check(r.get("base") == 0 and not r.get("mono"), "parse HWOUT stéréo base 0", str(r))
    r = parse_hwout("HWOUT 1025 0 1 0 0 0 0 -1:U -1")
    check(r.get("base") == 1 and r.get("mono"), "parse HWOUT mono canal 2", str(r))
    ok_v, why = midi_verdict(parse_auxrecv(SAMPLES[1][0]))
    check(ok_v is False, "un send audio à MIDI ouvert est bien CONDAMNÉ", why[:60])
    ok_v, why = midi_verdict(parse_auxrecv(SAMPLES[2][0]))
    check(ok_v is True, "un send MIDI-seul voulu est bien TOLÉRÉ", why[:60])
    if os.path.exists(CHUNK_LOG):
        chunk = open(CHUNK_LOG, encoding="utf-8", errors="replace").read()
        lines = chunk_lines(chunk, "AUXRECV")
        parsed = [parse_auxrecv(l) for l in lines]
        bad = [p for p in parsed if "error" in p]
        check(not bad, f"presets/.chunk.log (vrai chunk) : {len(lines)} AUXRECV parsées",
              "; ".join(p["error"] for p in bad[:2]) if bad else
              " · ".join(f"midi={p['midi']}" for p in parsed) or "aucune ligne AUXRECV")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description="Sends : MIDI coupé, modes, sorties hardware.")
    ap.add_argument("--dry-run", action="store_true",
                    help="autotest local des parseurs, sans toucher au rig")
    a = ap.parse_args()
    if a.dry_run:
        return dry_run()

    try:
        io = json.load(open(os.path.join(ROOT, "config", "io.json")))
    except (OSError, ValueError):
        io = {}
    outputs_count = int(io.get("outputs_count") or 2)
    print(f"carte « {io.get('device', '?')} » · {outputs_count} sortie(s) physique(s)")

    tmap, hw_counts = names_map()
    if tmap is None:
        sys.exit(f"{KO} la sonde peaks ne répond pas — Reaper/golem_watch tourne ?")

    print("\n── 1. Receives du perf-rec (« Recording ») : post-fader, MIDI coupé ──")
    check_receives("Recording", tmap, want_mode=0,
                   context="golem_perfrec pas monté, ou aucune source cochée")

    print("\n── 2. Receives du looper (« Looper ») : MIDI coupé — LE piège super8 ──")
    check_receives("Looper", tmap, context="preset sans looper : normal")

    print("\n── 3. Balayage : aucun send audio ne transporte de MIDI ──")
    sweep = sorted(n for n in tmap.values() if n.startswith("Sandbox ")) \
        + [n for n in SWEEP_EXTRA if n in tmap.values()
           and n not in ("Looper", "Recording")]        # 1 et 2 déjà faits
    for name in sweep:
        check_receives(name, tmap)
    if not sweep:
        print(f"  {WARN} aucune piste Sandbox — pas de preset monté ? (recall d'abord)")

    print("\n── 4. Le send DI du perf-rec est un VRAI DI (PRE-FX, mode 1) ──")
    di_tracks = sorted(n for n in tmap.values() if n.startswith("Recording:DI "))
    if not di_tracks:
        print(f"  ·   aucune piste « Recording:DI … » : elles n'existent QUE pendant une prise "
              "multi+DI\n      (pistes éphémères) — relancer ce script PENDANT une prise pour "
              "prouver ce point.\n      Hors prise, le garde-fou vivant est le RELIRE de "
              "add_receive (golem_perfrec.lua).")
    for name in di_tracks:
        check_receives(name, tmap, want_mode=1)

    print("\n── 5. Sorties hardware ↔ patch (mixer_dump + chunk) ──")
    txt = send_cmd({"action": "mixer_dump"}, MIXER_JSON)
    if txt is None:
        check(False, "mixer_dump répond", "Reaper/golem_watch muet ?")
    else:
        try:
            rows = json.loads(txt).get("sends") or []
        except ValueError:
            rows = []
        check(len(rows) > 0, f"mixer_dump voit des pistes sorties ({len(rows)})",
              ", ".join(f"{r['src']}→{r['hw_db']:g} dB" + (" MUTE" if r.get("hw_mute") else "")
                        for r in rows))
        for r in rows:
            check_hwouts(r["track"], outputs_count, hw_counts or {})

    print("\n" + "=" * 64)
    if fails:
        print(f"{KO} {len(fails)} échec(s) : " + " · ".join(fails[:6]))
    else:
        print(f"{OK} les sends portent ce qu'ils doivent — et rien d'autre.")
    print(f"\n{WARN} Non vérifié ici : que le son ARRIVE aux baffles (bouton MONITOR/volume "
          "ALSA — chassé 3×\nà tort côté Reaper), et le point 4 hors prise (pistes DI "
          "éphémères).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
