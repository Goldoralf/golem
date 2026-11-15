#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Où en est le passage des blocs de golem à golem-fx ? — le tableau de docs/golem-fx-migration.md, tiré des données.

Chaque bloc visible du catalogue (library/catalog/effects.json) tombe dans une colonne :
  - JOUÉ par golem-fx : `golem_fx: true` dans la table du moteur (effects-golem-engine.json) ;
  - PRÊT chez golem-fx, pas encore branché : un plugin de golem-fx déclare ce bloc (golem-fx-plugins.json, `blocks`) ;
  - SANS golem-fx : un effet open source qu'aucun plugin de golem-fx ne remplace encore ;
  - HORS PÉRIMÈTRE : ce que golem-fx ne remplacera pas (captures NAM, instruments, blocs fonction, matériel MIDI).

  ./tools/golem-fx-progress.py            # réécrit le tableau entre les marqueurs du document
  ./tools/golem-fx-progress.py --check    # code 1 si le document n'est pas à jour (la suite de tests l'appelle)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "golem-fx-migration.md"
BEGIN, END = "<!-- golem-fx-progress:begin -->", "<!-- golem-fx-progress:end -->"
# ce que golem-fx ne remplacera pas : une capture (le son EST le fichier), un instrument, un bloc fonction de golem, du
# matériel piloté en MIDI
OUT_OF_SCOPE = {"nam": ("Captures (the sound is the file)", {"pedal-nam", "preamp-nam", "comp-nam", "amp", "amp-nam", "boost"}),
                "inst": ("Instruments", {"vital", "pads", "drumkit", "organ", "piano", "ep"}),
                "feature": ("golem features", {"rec", "tuner", "click", "backing-track", "looper", "compo", "drums",
                                               "standard", "arrangement", "sample"}),
                "hw": ("Hardware (MIDI)", {"whammy-dt", "midi-pedal"})}


def table():
    cat = json.loads((ROOT / "library/catalog/effects.json").read_text(encoding="utf-8"))["effects"]
    eng = json.loads((ROOT / "library/catalog/effects-golem-engine.json").read_text(encoding="utf-8"))["effects"]
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    crate_of = {b: p["crate"] for p in plugins.values() for b in ((p.get("descriptor") or {}).get("blocks") or [])}
    played, ready, without, out = [], [], [], {k: [] for k in OUT_OF_SCOPE}
    for e in cat:
        t = e["type"]
        if e.get("hidden"):
            continue
        spec = eng.get(t) if isinstance(eng.get(t), dict) else {}
        scope = next((k for k, (_l, ts) in OUT_OF_SCOPE.items() if t in ts), None)
        if spec.get("golem_fx"):
            played.append((t, crate_of.get(t, "?"), e.get("quarantine", "").startswith("golem-fx only"), bool(e.get("bench"))))
        elif scope:
            out[scope].append(t)
        elif t in crate_of:
            ready.append((t, crate_of[t], str(e.get("plugin") or e.get("engine") or "")))
        else:
            without.append((t, str(e.get("plugin") or e.get("engine") or "")))
    eff = len(played) + len(ready) + len(without)
    L = [f"**{len(played)} of {eff} effect blocks** are played by golem-fx; {len(ready)} are ready in golem-fx and not "
         f"wired yet; {len(without)} have no golem-fx counterpart yet.", "",
         "| Status | Blocks |", "|---|---|"]
    rep = [f"`{t}`" for t, _c, only, _b in played if not only]
    new = [f"`{t}`" for t, _c, only, _b in played if only]
    bench = [f"`{t}`" for t, _c, _o, b in played if b]
    L.append(f"| Played by golem-fx, replacing an open-source plugin ({len(rep)}) | {', '.join(rep)} |")
    L.append(f"| Played by golem-fx, new blocks with no open-source original ({len(new)}) | {', '.join(new)} |")
    L.append(f"| … of which the engine-stall bench is still pending ({len(bench)}) | {', '.join(bench) or '—'} |")
    L.append(f"| Ready in golem-fx, not wired yet ({len(ready)}) | "
             + ", ".join(f"`{t}` ({c}, today {p.split(':')[-1].strip()[:28] or '—'})" for t, c, p in ready) + " |")
    L.append(f"| No golem-fx counterpart yet ({len(without)}) | "
             + ", ".join(f"`{t}` ({p.split(':')[-1].strip()[:28]})" for t, p in without) + " |")
    for k, (label, _ts) in OUT_OF_SCOPE.items():
        L.append(f"| Out of scope — {label} ({len(out[k])}) | {', '.join(f'`{t}`' for t in out[k])} |")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    doc = DOC.read_text(encoding="utf-8")
    i, j = doc.index(BEGIN) + len(BEGIN), doc.index(END)
    new = doc[:i] + "\n" + table() + "\n" + doc[j:]
    if a.check:
        if new != doc:
            print("docs/golem-fx-migration.md is not up to date: run ./tools/golem-fx-progress.py")
            return 1
        return 0
    DOC.write_text(new, encoding="utf-8")
    print(table().splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
