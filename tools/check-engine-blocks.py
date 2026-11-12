#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Les blocs du Golem Engine, un par un, sur un moteur à pilote factice (docs/ardour-plan.md §5 A3, étape 1).

Pour chaque type de library/catalog/effects-golem-engine.json : le plugin s'instancie (temps mesuré : un ajout long
fige le moteur), chaque paramètre du catalogue se résout par son nom (règle de golem_rig : exact, puis sous-chaîne),
une valeur s'écrit et se relit, le bloc se coupe et se rallume deux fois sans xrun. Aucune carte, aucun son, aucun
fichier du rack touché : une session jetable dans un dossier temporaire. Sans danger pendant que le rack joue.

  ./tools/check-engine-blocks.py [types…] [--engine-dir ~/golem-engine] [--json rapport.json]
Code 1 au premier manquement.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ADD_MS_MAX = 500           # au-delà, l'ajout fige le moteur assez longtemps pour s'entendre (check-block-stall)
SPECIAL = {"drumkit"}      # deux blocs moteur (traducteur + kit) : couvert par tests/test_engine_ardour_plan.py et le banc


def probe_input(types=None):
    from bridge.engine import ardour_plan as P
    table, catalog = P.load_table(), P.load_catalog()
    out = []
    for t, spec in sorted(table.items()):
        if t in SPECIAL or (types and t not in types):
            continue
        labels = []
        defs = {p["id"]: p for p in (catalog.get(t) or {}).get("params") or [] if p.get("id")}
        names = spec.get("params") or {}
        for pid, d in defs.items():
            if pid in (spec.get("absent") or {}):
                continue                                   # dit absent par la table, avec sa raison
            e, why = P.param_entry(dict(d, name=names.get(pid) or d.get("name")), d.get("default"))
            if e is None:
                continue                                   # refusé par le plan (contenu, courbe) : rien à sonder
            # un interrupteur s'écrit 1 (pas le milieu de sa plage : un bool relu 1 pour 0.37 n'est pas une faute)
            value = e.get("value") if "value" in e else (1.0 if d.get("type") == "bool" else None)
            labels.append({"pid": pid, "label": e["label"], "value": value})
        for k, v in (spec.get("init") or {}).items():
            labels.append({"pid": f"init:{k}", "label": k, "value": v})
        out.append({"type": t, **P.plugin_of(spec), "labels": labels})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("types", nargs="*")
    ap.add_argument("--engine-dir", default=os.environ.get("GOLEM_ENGINE_DIR") or os.path.expanduser("~/golem-engine"))
    ap.add_argument("--json", help="écrire le rapport ici")
    a = ap.parse_args()
    lua = os.path.join(a.engine_dir, "build", "luasession", "luasession")
    if not os.path.exists(lua):
        print(f"Golem Engine introuvable : {lua}")
        return 2
    work = tempfile.mkdtemp(prefix="golem-engine-blocks-")
    try:
        inp, out = os.path.join(work, "in.json"), os.path.join(work, "out.json")
        with open(inp, "w", encoding="utf-8") as f:
            json.dump(probe_input(set(a.types) or None), f)
        env_sh = os.path.join(a.engine_dir, "golem", "dev", "env.sh")
        cmd = (f'source "{env_sh}" >/dev/null 2>&1 && exec "{lua}" "{ROOT}/tools/engine-probe-blocks.lua" '
               f'"{work}/session" "{inp}" "{out}"')
        env = dict(os.environ, LANG="C.UTF-8", LC_ALL="C.UTF-8")
        p = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=600)
        if not os.path.exists(out):
            print(p.stdout[-2000:], p.stderr[-2000:])
            print("ÉCHEC : la sonde n'a rien rendu")
            return 1
        res = json.load(open(out, encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    fails = []
    for r in res:
        bad = [f"{x['pid']} écrit {x['wrote']:.4g} relu {x['read']:.4g}" for x in r.get("params") or [] if not x["ok"]]
        loose = [f"{x['pid']}→« {x['port_label']} »" for x in r.get("params") or [] if x["how"] == "substring"]
        problems = []
        if r.get("error"):
            problems.append(r["error"])
        problems += [f"absent : {m}" for m in r.get("missing") or []]
        problems += bad
        if (r.get("add_ms") or 0) > ADD_MS_MAX:
            problems.append(f"ajout {r['add_ms']} ms")
        if r.get("xruns"):
            problems.append(f"{r['xruns']} xrun(s) aux bascules")
        n = len(r.get("params") or [])
        io = f"{r.get('audio_in', '?')}→{r.get('audio_out', '?')}"
        head = (f"  {'ok ' if not problems else 'FAIL'}  {r['type']:<18} {n:>2} param(s), audio {io}, "
                f"ajout {r.get('add_ms', '?')} ms")
        print(head + (f" — {'; '.join(problems)}" if problems else ""))
        if loose:
            print(f"        par sous-chaîne : {', '.join(loose)}")
        if problems:
            fails.append(r["type"])
            if r.get("missing"):
                print(f"        labels du plugin : {', '.join(r.get('labels') or [])}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    print("OK" if not fails else f"{len(fails)} bloc(s) en échec : {', '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
