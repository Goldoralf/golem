#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesure la GIGUE du chemin de commande bridge → Reaper (docs/arrangement.md).

    ./tools/check-jitter.py            # 20 tirs, ~25 s ⚠ ÇA FAIT DU BRUIT sur les moniteurs
    ./tools/check-jitter.py -n 40      # plus d'échantillons
    ./tools/check-jitter.py --silent   # sans son : mesure le chemin CLICK au lieu du sample

POURQUOI CE SCRIPT EXISTE
Déclencher un sample à la mesure 21 n'a de sens que si le sample tombe VRAIMENT à la mesure 21.
Or le chemin est : bridge (Python) → presets/.command.json → boucle `defer` de golem_watch →
paramètre JSFX → note-on. `defer` tourne à la cadence d'affichage de Reaper (~30 Hz) : la
granularité théorique est donc ~33 ms. À 120 BPM une double-croche fait 125 ms — 33 ms, c'est
le quart d'une double-croche. Inaudible sur un riser, franchement audible sur un impact.

CE QU'ON MESURE, ET CE QU'ON NE MESURE PAS
On mesure l'aller-retour COMMANDE → ACCUSÉ : l'instant où le bridge écrit la commande, et
l'instant où le Lua publie son état (même tick `defer` que le déclenchement). C'est le terme
DOMINANT et celui qu'on peut instrumenter sans micro.
On ne mesure PAS la latence audio de la carte (8 ms fixes, connus, et communs à tout le rig) :
elle ajoute un retard CONSTANT, pas de la gigue — et un retard constant se compense, une gigue
non. C'est bien la gigue qui décide si l'on peut poser un sample « pixel perfect ».
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")


def _post(path, body):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r))


def _state():
    return json.load(urllib.request.urlopen(BRIDGE + "/api/state"))


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def measure(path, fire, n, gap):
    """Tire `n` fois avec un écart aléatoire-ish : on veut échantillonner TOUTES les phases
    du tick `defer`, sinon on mesure un alias et on croit le rig plus précis qu'il n'est."""
    out = []
    for i in range(n):
        before = _mtime(path)
        t0 = time.perf_counter()
        fire(i)
        deadline = t0 + 1.0
        while time.perf_counter() < deadline:
            m = _mtime(path)
            if m is not None and m != before:
                out.append((time.perf_counter() - t0) * 1000.0)
                break
            time.sleep(0.001)
        else:
            out.append(None)                       # pas d'accusé en 1 s
        # écart VOLONTAIREMENT non multiple du tick (~33 ms) : balaie les phases
        time.sleep(gap + (i % 7) * 0.0041)
    return out


def report(name, vals, theo_tick=33.3):
    ok = [v for v in vals if v is not None]
    lost = len(vals) - len(ok)
    if not ok:
        print(f"  {name} : AUCUN accusé — le Lua ne répond pas (Reaper arrêté ?)")
        return None
    ok.sort()
    med = statistics.median(ok)
    p95 = ok[min(len(ok) - 1, int(len(ok) * 0.95))]
    spread = ok[-1] - ok[0]
    print(f"  {name} · {len(ok)} tirs" + (f" ({lost} perdus)" if lost else ""))
    print(f"    min {ok[0]:6.1f} ms | médiane {med:6.1f} | p95 {p95:6.1f} | max {ok[-1]:6.1f}")
    print(f"    GIGUE (max−min) = {spread:.1f} ms   [tick defer théorique ≈ {theo_tick:.0f} ms]")
    return {"n": len(ok), "min": ok[0], "med": med, "p95": p95, "max": ok[-1], "spread": spread}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=20, help="nombre de tirs")
    ap.add_argument("--gap", type=float, default=0.9, help="écart entre tirs (s)")
    ap.add_argument("--silent", action="store_true",
                    help="mesure le chemin CLICK (horloge silencieuse) — aucun son émis")
    a = ap.parse_args()

    st = _state()
    if not st.get("reaper_connected"):
        sys.exit("Reaper n'est pas connecté — rien à mesurer.")
    print(f"machine : Reaper connecté · latence carte {st.get('latency_ms')} ms · "
          f"preset « {st.get('preset_id')} »\n")

    if a.silent:
        # l'horloge SILENCIEUSE du click : même relais golem_watch, zéro son.
        path = os.path.join(ROOT, "presets", ".click.json")
        cfg = json.load(open(os.path.join(ROOT, "config", "click.json")))
        # ⚠ ON BASCULE `beats`, PAS `clock` : la signature de publication de golem_click.lua
        # OMET `clock` (et `den`) — basculer l'horloge silencieuse ne déclenche AUCUNE
        # publication, et on mesurerait alors le battement de cœur à 1 Hz au lieu de la
        # commande. Premier jet du script : 425 ms « de latence », pur artefact.
        # `beats` EST dans la signature, et avec on:false le click reste muet.
        state0 = [False]

        def fire(i):
            state0[0] = not state0[0]
            from bridge.commands import write_command
            write_command({"action": "click", "op": "set", "on": False, "clock": False,
                           "level": cfg.get("level", -12),
                           "beats": 5 if state0[0] else 4,
                           "den": cfg.get("den", 4), "groups": [], "div": 1})
        sys.path.insert(0, ROOT)
        print("Chemin CLICK (horloge silencieuse) — aucun son émis")
        res = report("click", measure(path, fire, a.n, a.gap))
        from bridge.commands import write_command
        write_command({"action": "click", "op": "set", "on": False, "clock": False,
                       "level": cfg.get("level", -12), "beats": cfg.get("beats", 4),
                       "den": cfg.get("den", 4), "groups": [], "div": 1})
    else:
        sw = next(iter((st.get("sample_switches") or {})), None)
        if sw is None:
            sys.exit("Aucun bloc sample assigné à un switch : assigner un pied au bloc sample,\n"
                     "ou lancer avec --silent (chemin click, sans son).")
        path = os.path.join(ROOT, "presets", ".sample.json")
        print(f"⚠ CHEMIN SAMPLE — {a.n} tirs vont S'ENTENDRE sur les moniteurs (switch {sw})\n")
        res = report("sample", measure(path, lambda i: _post("/api/sample", {"sw": int(sw)}), a.n, a.gap))
        _post("/api/sample", {"sw": int(sw), "op": "stop"})

    if res:
        print()
        if res["spread"] <= 12:
            print("  → gigue faible : poser un sample à la mesure tient sans pré-armement.")
        elif res["spread"] <= 40:
            print("  → gigue de l'ordre du tick `defer` : suffisant pour un riser, PAS pour un\n"
                  "    impact sur le temps. Le pré-armement (« joue dans N échantillons »,\n"
                  "    décompté par le JSFX dans le thread audio) est nécessaire.")
        else:
            print("  → gigue élevée : le pré-armement est indispensable, et il faut regarder\n"
                  "    ce qui charge la boucle defer (un autre script long au même tick ?).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
