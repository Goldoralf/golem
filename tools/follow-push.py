#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pousse des frames `pos` vers golem.fm SANS backing, sans Reaper, sans audio.

    ./tools/follow-push.py ray_stone_warm_light
    ./tools/follow-push.py ray_stone_warm_light --start 30 --pause-at 10 --secs 45

Le pendant, côté rack, de `backend/tools/simulate_rack_follow.py` de golem.fm (demandé par
leur agent le 2026-08-03). Ensemble, les deux simulateurs isolent les quatre pièces :

    ce script + leur page   → notre UPLINK seul est en cause, ou pas
    leur simulateur + page  → le WEB seul est en cause, ou pas
    rack réel + leur page   → si les deux premiers marchent, c'est la jonction

Il parle le MÊME protocole que `bridge/follow_uplink.py` — même URL, même Bearer, même
forme de frame, même cadence — mais il fabrique la position au lieu de la lire du rig.
C'est le seul intérêt : ne rien mobiliser d'autre que le socket.

⚠ Ne lance PAS ceci pendant que le bridge tourne avec un backing en lecture : deux uplinks
pousseraient deux positions contradictoires. L'outil le dit et refuse (--force pour passer).
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# `websockets` vit dans le venv du bridge, pas dans le python du système : on se relance
# dedans plutôt que d'exiger une activation manuelle (l'outil doit marcher tapé tel quel).
# ⚠ On teste sys.prefix, PAS le chemin de l'exécutable : `.venv/bin/python3` est un lien
# vers le python du système, donc realpath() rend la MÊME valeur des deux côtés et la
# ré-exécution était sautée en silence (« ModuleNotFoundError: websockets » alors que le
# paquet est bien installé). sys.prefix, lui, distingue vraiment les deux environnements.
_VENV = os.path.join(ROOT, ".venv")
if os.path.isdir(_VENV) and os.path.realpath(sys.prefix) != os.path.realpath(_VENV):
    os.execv(os.path.join(_VENV, "bin", "python3"),
             [os.path.join(_VENV, "bin", "python3")] + sys.argv)
from bridge import golemfm                       # noqa: E402
from bridge.follow_uplink import _ws_url           # noqa: E402  (même dérivation d'URL)

PUSH_EVERY_S = 0.22                                # ~4,5 Hz — la cadence du vrai uplink


async def main(a):
    base, token = golemfm._cfg()
    if not base or not token:
        print("✗ pas appairé — Settings ▸ API ▸ golem.fm")
        return 1
    url = _ws_url(base)
    print(f"  base   : {base}")
    print(f"  socket : {url}")
    print(f"  jeton  : {token[:12]}… ({len(token)} car.)")

    import websockets
    try:
        async with websockets.connect(
                url, additional_headers={"Authorization": "Bearer " + token},
                open_timeout=8, ping_interval=20, ping_timeout=10) as ws:
            print(f"  ✓ connecté — pousse « {a.slug} » à {1 / PUSH_EVERY_S:.1f} Hz\n")
            t0, seq, pos = time.time(), 0, float(a.start)
            playing = True
            while time.time() - t0 < a.secs:
                el = time.time() - t0
                if a.pause_at and playing and el >= a.pause_at:
                    playing = False
                    print(f"  ⏸  pause à {pos:.1f} s (le curseur doit se figer)")
                if playing:
                    pos = a.start + el
                seq += 1
                await ws.send(json.dumps({"type": "pos", "slug": a.slug, "playing": playing,
                                          "posMs": round(pos * 1000, 1), "seq": seq}))
                if seq % 23 == 0:
                    print(f"  → seq {seq:4d}  pos {pos:7.2f} s  playing={playing}")
                await asyncio.sleep(PUSH_EVERY_S)
            print(f"\n  {seq} frames envoyées. Déconnexion → la page doit dire « rack offline ».")
    except Exception as e:
        code = getattr(getattr(e, "rcvd", None), "code", None) or getattr(e, "code", None)
        if code == 4401:
            print("  ✗ 4401 — jeton invalide ou révoqué : ré-appairer")
        elif code == 4403:
            print("  ✗ 4403 — le jeton n'a pas le scope `follow:push` : ré-appairer suffit")
        else:
            print(f"  ✗ {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", help="slug golem.fm (ex. ray_stone_warm_light)")
    ap.add_argument("--start", type=float, default=0, help="position de départ, en secondes")
    ap.add_argument("--pause-at", type=float, default=0, help="fige le curseur après N s")
    ap.add_argument("--secs", type=float, default=30, help="durée du test")
    ap.add_argument("--force", action="store_true", help="pousser même si le bridge tourne")
    a = ap.parse_args()
    if not a.force:
        up = subprocess.run(["pgrep", "-f", "uvicorn bridge.app"],
                            capture_output=True).returncode == 0
        if up:
            print("✗ le bridge tourne : son uplink pousse déjà. Deux sources = deux positions")
            print("  contradictoires. Arrête-le (golem stop) ou passe --force en connaissance.")
            sys.exit(2)
    sys.exit(asyncio.run(main(a)))
