#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le rack est-il LIBRE pour un auto-test ? (docs/quality-automation.md, lot 5 — la règle des sondes : jamais pendant
qu'on joue, jamais une prise.)

Lit le bridge vivant (GET /api/state, GET /api/reamp) et applique la règle « libre » du reamp (docs/reamp.md §2) :
pas de mode Gig ni verrou, pas de prise ni de décompte, pas de chanson ni d'arrangement en cours, pas de chargement,
et personne n'a touché le rack (écran, pied, signal) depuis `--idle` secondes (défaut 600, celui du reamp).

Codes de sortie : 0 libre · 3 occupé (la raison sur stdout) · 4 bridge injoignable. Un workflow s'arrête proprement
sur 3 et 4 : « rien fait cette nuit, voici pourquoi » n'est pas un échec."""
import argparse
import json
import sys
from urllib.request import urlopen


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8770")
    ap.add_argument("--idle", type=float, default=600.0, help="secondes sans geste exigées (défaut 600)")
    a = ap.parse_args()
    try:
        with urlopen(a.base + "/api/state", timeout=5) as r:
            st = json.load(r)
        with urlopen(a.base + "/api/reamp", timeout=5) as r:
            rp = json.load(r)
    except Exception as e:
        print(f"bridge unreachable at {a.base}: {e}")
        return 4
    mode = st.get("mode") or {}
    perf = st.get("perf") or {}
    why = None
    if mode.get("id") == "gig":
        why = "gig mode"
    elif (mode.get("ui") or {}).get("locked"):
        why = "mode locked"
    elif perf.get("recording") or st.get("perf_countin"):
        why = "a take is recording"
    elif (st.get("backing") or {}).get("playing"):
        why = "a song is playing"
    elif (st.get("arrangement") or {}).get("running"):
        why = "an arrangement is running"
    elif st.get("rig_loading"):
        why = "the rig is loading"
    elif rp.get("waiting_for"):
        why = rp["waiting_for"]
    else:
        act = rp.get("activity") or {}
        idle = act.get("idle_s")
        if idle is not None and idle < a.idle:
            why = f"someone used the rack {int(idle)} s ago ({act.get('src')}); waiting for {int(a.idle)} s of quiet"
    if why:
        print(f"busy: {why}")
        return 3
    print(f"free: preset {st.get('preset_id')}, REAPER {'connected' if st.get('reaper_connected') else 'absent'}, "
          f"idle {int((rp.get('activity') or {}).get('idle_s') or 0)} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
