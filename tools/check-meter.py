#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie que les TROIS implémentations de la durée de mesure disent la même chose.

    ./tools/check-meter.py            # Python + JS (rapide, hors-ligne pour le JSFX)
    ./tools/check-meter.py --rig      # + le JSFX, MESURÉ dans Reaper (bridge et rig requis)

POURQUOI CE SCRIPT EXISTE
La formule `duree_mesure = num × (4/den) × 60/bpm` vit à trois endroits, et ils ne peuvent pas
partager de code : EEL2 dans le thread audio, JS dans le navigateur, Python dans le bridge. Ils
peuvent partager une TABLE — tools/meter-cases.json. Le jour où l'un dérive, on l'apprend ici
plutôt qu'en concert, où le batteur entendrait la mesure 33 pendant que le rig tire la 34.

CE QU'IL VÉRIFIE, ET COMMENT
  · Python : appel direct de bridge.arrangement.section_seconds.
  · JS     : le VRAI module servi (app/designer-arrangement.js), importé dans Chrome headless.
             Pas une copie de la formule — celle qui part sur le rack.
  · JSFX   : le seul qu'on ne peut pas interroger. On le MESURE : on pose (beats, den) sur le
             métronome, on compte ses pulsations pendant N secondes, et on compare le débit à
             la théorie. C'est moins précis (± un tick) mais c'est la vérité du terrain.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "tools", "meter-cases.json")
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
TOL = 1e-9


def load_cases():
    return json.load(open(CASES))["cases"]


def check_python(cases):
    sys.path.insert(0, ROOT)
    from bridge import arrangement as A
    bad = []
    for c in cases:
        got = A.section_seconds({"bars": c["bars"], "sig": {"num": c["num"], "den": c["den"]}},
                                None, c["bpm"])
        if abs(got - c["seconds"]) > TOL:
            bad.append((c, got))
    return bad


def check_js(cases):
    """Importe le module RÉELLEMENT servi et lui pose les mêmes questions."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = b.new_page()
        pg.goto(BRIDGE + "/app/", wait_until="domcontentloaded")
        got = pg.evaluate(
            """async (cases) => {
                 const m = await import('/app/designer-arrangement.js');
                 return cases.map(c => m.secSeconds(
                   { bars: c.bars, sig: { num: c.num, den: c.den } }, null, c.bpm));
               }""", cases)
        b.close()
    return [(c, g) for c, g in zip(cases, got) if abs(g - c["seconds"]) > TOL]


def _post(path, body):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r))


def _ticks(timeout=3.0):
    """(compteur, instant de sa publication). Le Lua ne publie `.click.json` qu'UNE FOIS PAR SECONDE : lu à un instant
    quelconque, le compteur avait jusqu'à 1 s de retard à chaque bout — plus d'une pulsation d'erreur à 5,8 puls/s
    sur 8 s, un faux désaccord sur 32/16 (2026-10-08). On attend donc l'écriture SUIVANTE et on date le compteur par
    elle : la durée mesurée est celle qui sépare deux publications, pas celle de nos sommeils."""
    p = os.path.join(ROOT, "presets", ".click.json")
    m0, t0 = os.stat(p).st_mtime, time.time()
    while time.time() - t0 < timeout:
        m = os.stat(p).st_mtime
        if m != m0:
            time.sleep(0.02)                            # l'écriture Lua n'est pas atomique
            try:
                return json.load(open(p))["ticks"], m
            except (OSError, ValueError, KeyError):
                m0 = m
        time.sleep(0.005)
    return json.load(open(p))["ticks"], os.stat(p).st_mtime


def check_jsfx(cases, window=8.0):
    """MESURE le métronome. Le JSFX ne rend pas une durée de mesure : il émet des pulsations.
    On compare donc le DÉBIT de pulsations à la théorie — mesure_attendue/num pulsations par
    mesure, soit num/duree_mesure pulsations par seconde."""
    bad, saved = [], None
    try:
        saved = json.load(open(os.path.join(ROOT, "config", "click.json")))
    except Exception:
        pass
    # une seule mesure de tempo par cas : on ne peut pas changer le BPM du preset ici, donc on
    # teste les cas au BPM du rig et on saute les autres (le rapport num/den est ce qui compte).
    st = json.load(urllib.request.urlopen(BRIDGE + "/api/state"))
    # le tempo DU CLICK (celui qu'il joue : le preset, le backing ou le réglage) — pas 120 par défaut. Le 2026-10-08,
    # sans backing chargé, l'outil supposait 120 alors que le click battait à 87 : neuf « désaccords » qui étaient
    # tous exacts à 87 (rapport 87/120 partout).
    bpm = float((st.get("click") or {}).get("bpm") or (st.get("backing") or {}).get("bpm") or 0) or 120.0
    try:                                                # et au NIVEAU réglé : sans `level`, le JSFX jouait à 0 dB
        level = float(json.load(open(os.path.join(ROOT, "config", "click.json"))).get("level", -12))
    except (OSError, ValueError):
        level = -12.0
    for c in cases:
        if c["bars"] != 1:
            continue                                    # le débit ne dépend pas du nombre de mesures
        expected_rate = c["num"] / (c["num"] * (4.0 / c["den"]) * (60.0 / bpm))
        _post("/api/metronome", {"on": False})
        time.sleep(0.4)
        from bridge.commands import write_command       # noqa: E402  (import tardif : ROOT en tête)
        write_command({"action": "click", "op": "set", "on": True, "level": level, "beats": c["num"],
                       "den": c["den"], "groups": [], "div": 1})
        time.sleep(2.0)
        (k0, m0) = _ticks(); time.sleep(window - 1.0); (k1, m1) = _ticks()
        rate = (k1 - k0) / max(0.5, m1 - m0)
        # tolérance : ± 1 tick sur la fenêtre (on échantillonne un compteur, pas une horloge)
        if abs(rate - expected_rate) > (1.0 / window) + 0.02:
            bad.append((c, rate, expected_rate))
        else:
            print(f"    {c['num']}/{c['den']} @{bpm:.0f} : {rate:.2f} puls/s "
                  f"(théorie {expected_rate:.2f})")
    _post("/api/metronome", {"on": False})
    if saved:                                           # on rend le métronome comme on l'a trouvé
        json.dump(saved, open(os.path.join(ROOT, "config", "click.json"), "w"), indent=1)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", action="store_true", help="mesure AUSSI le JSFX (bridge + Reaper requis)")
    ap.add_argument("--window", type=float, default=8.0, help="fenêtre de mesure du JSFX (s)")
    ap.add_argument("--skip-js", action="store_true",
                    help="saute l'étage JS EXPLICITEMENT (sans ça, un étage invérifiable = ÉCHEC)")
    a = ap.parse_args()
    cases = load_cases()
    fail = 0

    print(f"Table d'or : {len(cases)} cas\n")

    print("  Python  — bridge/arrangement.py")
    bad = check_python(cases)
    for c, got in bad:
        print(f"    ✗ {c['name']} : {got} au lieu de {c['seconds']}")
    print(f"    {'✓ ' + str(len(cases)) + ' cas' if not bad else '✗ ' + str(len(bad)) + ' ÉCART(S)'}\n")
    fail += len(bad)

    if a.skip_js:
        print("  JS      — SAUTÉ (--skip-js, assumé)\n")
    else:
        print("  JS      — app/designer-arrangement.js (module servi, dans Chrome)")
        try:
            bad = check_js(cases)
            for c, got in bad:
                print(f"    ✗ {c['name']} : {got} au lieu de {c['seconds']}")
            print(f"    {'✓ ' + str(len(cases)) + ' cas' if not bad else '✗ ' + str(len(bad)) + ' ÉCART(S)'}\n")
            fail += len(bad)
        except Exception as e:
            # ⚠ un étage qu'on NE PEUT PAS vérifier est un ÉCHEC, pas un avertissement : ce
            # script a rendu vert pendant des semaines en sautant sa moitié JS en silence
            # (playwright absent du venv — audit 2026-08-12). Sauter se dit avec --skip-js.
            print(f"    ✗ NON VÉRIFIÉ ({e})")
            print("      → il faut playwright (pip install playwright) ET le bridge lancé ;"
                  " ou --skip-js pour l'assumer\n")
            fail += 1

    if a.rig:
        print("  JSFX    — reaper/Effects/golem_click.jsfx (MESURÉ, pas interrogé)")
        try:
            bad = check_jsfx(cases, a.window)
            for c, rate, exp in bad:
                print(f"    ✗ {c['name']} : {rate:.2f} puls/s au lieu de {exp:.2f}")
            print(f"    {'✓ conforme' if not bad else '✗ ' + str(len(bad)) + ' ÉCART(S)'}\n")
            fail += len(bad)
        except Exception as e:
            # --rig a été DEMANDÉ : ne pas pouvoir mesurer est un échec, pas une excuse.
            print(f"    ✗ NON MESURÉ ({e})\n")
            fail += 1
    else:
        print("  JSFX    — non mesuré (relancer avec --rig, bridge + Reaper allumés)\n")

    print("RÉSULTAT :", "les implémentations sont d'accord" if fail == 0 else f"{fail} DÉSACCORD(S)")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
