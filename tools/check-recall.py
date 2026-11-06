#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie le MOTEUR DE RECALL (bridge/recall.py) : sérialisation et boucle libre.

    ./tools/check-recall.py                    # bridge local (http://localhost:8770)
    ./tools/check-recall.py --url http://rack:8770

⚠ SUR UN RACK VIVANT, C'EST AUDIBLE : le test rappelle réellement des presets (le rig change
de son pendant ~10 s). Le preset et la scène de départ sont restaurés à la fin.

POURQUOI CE SCRIPT EXISTE
Le recall est le chemin le plus critique du rack, et l'extraction de bridge/recall.py
(audit 2026-08-12, P2) a changé son régime d'exécution : le cœur (bake + compile + écritures)
tourne désormais dans un exécuteur à un worker, sérialisé par un verrou, HORS de la boucle
asyncio. Deux propriétés en découlent, et ce script les mesure au lieu de les croire :

1. **La boucle reste libre pendant un recall.** Avant, chaque recall gelait WebSocket, polls
   et API le temps du compile — plus l'attente polie du protocole ACK (≤0,9 s par commande).
   On bombarde /api/recall et on chronomètre /api/health EN MÊME TEMPS : si la médiane dépasse
   quelques ms, la boucle est retombée dans le chemin bloquant.
2. **Les recalls concurrents se sérialisent sans se mélanger.** 8 recalls simultanés alternant
   deux presets doivent tous aboutir, et l'état final (state.preset_id) doit être d'accord
   avec la dernière commande émise (presets/.command.json côté rack) — pas un hybride.

Vérifié à froid le 2026-08-13 (PC sans Reaper) : 8 recalls en ~7,5 s, médiane /api/health
4 ms pendant la tempête. Sur le rack, Reaper consomme les commandes : la tempête va plus
vite (pas de timeout ACK) et le test entend en plus la cohérence du rig monté.
"""
import argparse
import json
import sys
import threading
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://localhost:8770")
ap.add_argument("--max-health-ms", type=float, default=150.0,
                help="latence max tolérée de /api/health pendant la tempête (défaut 150 ms)")
args = ap.parse_args()
B = args.url.rstrip("/")


def post(path, body, timeout=30):
    r = urllib.request.urlopen(urllib.request.Request(
        B + path, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=timeout)
    return json.loads(r.read())


def get(path, timeout=5):
    return json.loads(urllib.request.urlopen(B + path, timeout=timeout).read())


def fail(msg):
    print(f"✗ {msg}")
    sys.exit(1)


try:
    st0 = get("/api/state")
except Exception as e:
    fail(f"bridge injoignable sur {B} : {e}")
init_pid, init_scene = st0.get("preset_id"), st0.get("scene_id")

# deux presets de travail : ceux de la setlist active d'abord (ce que le pied jouerait),
# sinon les deux premiers du magasin.
pids = [b["preset"] for b in (get("/api/fcb-banks").get("banks") or []) if b.get("preset") and not b.get("missing")]   # une case sans preset (vide, chanson seule) ne se rappelle pas
if len(pids) < 2:
    pids = [p.get("id") for p in (get("/api/presets") if isinstance(get("/api/presets"), list)
                                  else get("/api/presets").get("presets", [])) if p.get("id")]
if len(pids) < 2:
    fail("il faut au moins 2 presets pour tester la sérialisation")
pa, pb = pids[0], pids[1]
print(f"presets de test : {pa} / {pb} (départ : {init_pid or '—'})")

# 1. recall simple : l'état suit
r = post("/api/recall", {"preset": pa})
if r["state"]["preset_id"] != pa:
    fail(f"recall simple : state.preset_id = {r['state']['preset_id']!r}, attendu {pa!r}")
print("✓ recall simple — l'état suit")

# 2. tempête : 8 recalls concurrents + latence /api/health pendant
lat, errs, res = [], [], []
stop = threading.Event()


def prober():
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            get("/api/health", timeout=5)
            lat.append(time.monotonic() - t0)
        except Exception as e:
            errs.append(repr(e))
        time.sleep(0.05)


def storm(i):
    try:
        res.append(post("/api/recall", {"preset": pb if i % 2 else pa}, timeout=60)["state"]["preset_id"])
    except Exception as e:
        res.append(repr(e))


pr = threading.Thread(target=prober)
pr.start()
ths = [threading.Thread(target=storm, args=(i,)) for i in range(8)]
t0 = time.monotonic()
[t.start() for t in ths]
[t.join() for t in ths]
dur = time.monotonic() - t0
stop.set()
pr.join()

if errs:
    fail(f"/api/health en erreur pendant la tempête : {errs[:3]}")
bad = [x for x in res if x not in (pa, pb)]
if bad:
    fail(f"recalls en erreur : {bad[:3]}")
med = sorted(lat)[len(lat) // 2] * 1000
mx = max(lat) * 1000
print(f"✓ tempête — 8 recalls en {dur:.1f}s ; /api/health pendant : médiane {med:.0f} ms, max {mx:.0f} ms")
if mx > args.max_health_ms:
    fail(f"la boucle a bloqué : max {mx:.0f} ms > {args.max_health_ms:.0f} ms — le recall est-il "
         "retombé SUR la boucle asyncio ?")

# 3. cohérence : l'état final est un des deux presets, pas un hybride
st = get("/api/state")
if st["preset_id"] not in (pa, pb):
    fail(f"état final incohérent : {st['preset_id']!r}")
print(f"✓ cohérence — état final : {st['preset_id']} (scène {st['scene_id']})")

# 4. restauration du point de départ (sur un rack vivant, on rend le son qu'on a pris)
if init_pid:
    post("/api/recall", {"preset": init_pid, **({"scene": init_scene} if init_scene else {})})
    print(f"✓ restauré : {init_pid}" + (f" scène {init_scene}" if init_scene else ""))

print("TOUT VERT")
