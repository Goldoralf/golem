#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Photographie le rig AU MOMENT où le son disparaît — AVANT de relancer Reaper.

    ./tools/check-silence.py              # sur le rack : joue 4 s quand il le demande, ~12 s
    ./tools/check-silence.py --no-wait    # sans musicien (CI, à blanc) : échantillonne sans attendre

POURQUOI CE SCRIPT EXISTE
Le 2026-09-07, « je n'ai plus de son régulièrement, ça crash tout le temps » : cinq relances de
Reaper en trois minutes… et AUCUN segfault dans le journal du noyau. Relancer efface la scène
du crime : après, plus rien ne dit si l'entrée n'arrivait plus, si un plugin avalait le signal,
si une branche était muette, ou si Reaper avait perdu la carte. Ce script relève tout ça en
lecture seule, en 12 s, et dit OÙ le signal s'arrête.

DEPUIS LE 2026-10-20 la logique vit dans le bridge (bridge/silence.py — le bouton « Why no sound? »
de Settings ▸ Health, docs/health.md §4.1) : ce script lance la chasse par la route
POST /api/health/silence, attend, et imprime le rapport — le même que l'écran, gardé dans
presets/.silence-<hhmmss>.json. Un seul verdict, une seule liste de seuils.

LIMITES ASSUMÉES
· Il ne répare rien. Il ne relance rien. Il dit.
· Sans signal joué, il ne peut conclure que « pas d'entrée » — il le dit, il n'invente pas.
· Refusé (409, avec la raison) pendant une prise, une chanson, un chargement, ou en mode scène.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

import os

BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
OK, KO, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m⚠\033[0m"


def get(path):
    with urllib.request.urlopen(BRIDGE + path, timeout=5) as r:
        return json.load(r)


def post(path, body=None):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body or {}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-wait", action="store_true", help="n'attend pas le musicien (le verdict le dit)")
    ap.add_argument("--seconds", type=float, default=4.0, help="durée d'écoute des crêtes (défaut 4 s, 1–10)")
    args = ap.parse_args()
    try:
        st = get("/api/state")
    except Exception as e:
        print(f"{KO} bridge injoignable ({e}) — rien à photographier")
        return 2
    print("── 1. moteur")
    print(f"  {OK if st.get('reaper_running') else KO} Reaper : {'tourne' if st.get('reaper_running') else 'ÉTEINT'}"
          f" · lien OSC {'ok' if st.get('reaper_connected') else 'MORT'}")
    au = st.get("audio") or {}
    print(f"  {KO if au.get('ok') is False else OK} thread audio {'FIGÉ : ' + str(au.get('why')) if au.get('ok') is False else 'vivant'}"
          f" · RT {st.get('latency_ms')} ms · xruns {st.get('xruns')}")
    for i in (st.get("rig_check") or {}).get("issues") or []:
        print(f"  {WARN} FX FILE : {i.get('track')} FX#{i.get('fx')} ({i.get('kind')}) « {i.get('expected')} » non chargé")
    print(f"  preset {st.get('preset_id')} · scène {st.get('scene_id')} · mode {(st.get('mode') or {}).get('id')}")

    print("\n── 2. la chasse (bridge/silence.py)")
    try:
        post("/api/health/silence", {"seconds": args.seconds, "waited": not args.no_wait})
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.load(e)
        except Exception:
            pass
        print(f"  {KO} refusée : {body.get('error') or e}")
        return 1
    if not args.no_wait:
        print(f"  ▶ JOUE MAINTENANT pendant {args.seconds:.0f} s…")
    t0 = time.time()
    rep = None
    while time.time() - t0 < args.seconds + 40:
        s = get("/api/health/silence")
        if s.get("phase") == "done":
            rep = s.get("report")
            break
        if s.get("phase") == "error":
            print(f"  {KO} la chasse a échoué : {s.get('error')}")
            return 1
        time.sleep(0.5)
    if not rep:
        print(f"  {KO} pas de rapport en {args.seconds + 40:.0f} s")
        return 1
    for t in rep.get("tracks") or []:
        flag = OK if t["peak_db"] > -60 else (WARN if t.get("mute") else KO)
        print(f"  {flag} {t['name']:<32} crête {t['peak_db']:6.1f} dBFS · vol {t.get('vol_db')} dB · mute {int(bool(t.get('mute')))}"
              f" · hw {t.get('hw_sends')} · sends {t.get('sends')}")
    for n, f in (rep.get("chunk") or {}).items():
        print(f"  {n}: {(f or {}).get('rec') or 'REC ?'} · {(f or {}).get('mute') or ''} · {len((f or {}).get('hwout') or [])} HWOUT · {(f or {}).get('mainsend') or ''}")
    for m in rep.get("missing") or []:
        print(f"  {KO} {m['track']} FX#{m['fx']} {m['plugin']} : {m['param']} VIDE")

    v = rep.get("verdict") or {}
    print("\n── VERDICT")
    print(f"  {OK if v.get('level') == 'ok' else KO} {v.get('title')}  [{v.get('stage')}]")
    print(f"  → {v.get('text')}")
    if rep.get("file"):
        print(f"\n  rapport : {rep['file']}  (à me montrer, ou à garder)")
    return 0 if v.get("level") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
