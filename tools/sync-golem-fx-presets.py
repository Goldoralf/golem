#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Seeds golem-fx's factory presets into library/block-presets/<type>/<id>.json (docs/golem-fx-sheet.md §5).

golem-fx researches and annotates a factory preset set per pedal (golem-fx/presets/<crate>.json, exported COMPLETE in
visuals/data/descriptors.json: every parameter of the plugin). Each becomes one block preset file, keyed by the rack's
block type and the preset's stable id — golem.fm's AI refers to it as "<type>/<id>", and golem.fm's sync reads these
files from this repository. The fields are golem-fx's (id, type, name, desc, inst, genres, subgenres, gain, use, refs,
level_db, sync, tags, default, params, notes), plus `factory: true` and `golem_fx: true`.

Params are rewritten in the block's vocabulary (bridge/golem_fx.preset_params): the id the sheet shows (a catalogue id
where the setting is a catalogue knob), a list by its RANK. A type's IDENTITY setting (reverb-plate = algo Plate…) is
never written; a preset that says otherwise is refused. A type the catalogue does not have (gapmeter, a probe) is skipped.

An id the rack already had keeps its file name: golem-fx's version replaces it (golem-fx kept those ids on purpose, so
saved patches resolve) and it is NOT flagged `golem_fx` (it stays offered everywhere; settings only golem-fx has are
dropped by the compiler where golem-fx does not play the block). Presets of a previous seed that golem-fx removed are
deleted; a hand-made or rack preset (no `golem_fx_seed`) is never touched.

  ./tools/sync-golem-fx-presets.py                  # from ~/code/golem-fx (or --from)
  ./tools/sync-golem-fx-presets.py --check          # exit 1 if the files are not up to date
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "library" / "block-presets"
FIELDS = ("id", "type", "name", "desc", "inst", "genres", "subgenres", "gain", "use", "refs", "level_db", "sync", "tags",
          "default", "params", "notes")


def build(src):
    from bridge import golem_fx
    cat = {e["type"]: e for e in json.load(open(ROOT / "library" / "catalog" / "effects.json", encoding="utf-8"))["effects"]}
    desc = json.load(open(Path(src) / "visuals" / "data" / "descriptors.json", encoding="utf-8"))["descriptors"]
    files, problems, skipped = {}, [], set()
    taken = {}                                            # (type, inst) -> id du défaut retenu
    for crate in sorted(desc):
        for pr in desc[crate].get("presets") or []:
            t, pid = pr.get("type"), pr.get("id")
            if t not in cat:
                skipped.add(t)
                continue
            params, bad = golem_fx.preset_params(t, pr.get("params") or {}, cat[t].get("params"))
            if bad:
                problems.append(f"{t}/{pid}: " + "; ".join(bad))
                continue
            o = {k: pr.get(k) for k in FIELDS if k in pr}
            o["params"] = params
            o["factory"] = True
            o["golem_fx_seed"] = crate                    # la marque du semis : ce que ce script possède
            key = (t, pr.get("inst") or "any")
            if o.get("default"):
                if key in taken:                          # un seul défaut par (type, instrument) : le premier
                    problems.append(f"{t}/{pid}: second default for {key[1]} (kept {taken[key]})")
                    o["default"] = False
                else:
                    taken[key] = pid
            files[(t, pid)] = o
    return files, problems, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="src", default=os.path.expanduser("~/code/golem-fx"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    files, problems, skipped = build(a.src)
    for p in problems:
        print("  ⚠ " + p)
    written, changed, removed = 0, [], []
    seeded_before = {}
    for d in OUT.iterdir() if OUT.is_dir() else []:
        if d.is_dir():
            for f in d.glob("*.json"):
                try:
                    o = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if isinstance(o, dict) and o.get("golem_fx_seed"):
                    seeded_before[(d.name, f.stem)] = f
    for (t, pid), o in sorted(files.items()):
        f = OUT / t / (pid + ".json")
        prev = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
        rack_had = isinstance(prev, dict) and not prev.get("golem_fx_seed")
        if not rack_had and not (isinstance(prev, dict) and prev.get("golem_fx") is False):
            o["golem_fx"] = True                         # nouveau : proposé là où golem-fx joue le bloc
        else:
            o["golem_fx"] = False                        # un id que le rack avait : proposé partout
        text = json.dumps(o, indent=1, ensure_ascii=False) + "\n"
        if not f.is_file() or f.read_text(encoding="utf-8") != text:
            changed.append(f"{t}/{pid}")
            if not a.check:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8")
        written += 1
    for key, f in seeded_before.items():
        if key not in files:
            removed.append("/".join(key))
            if not a.check:
                f.unlink()
    commit = subprocess.run(["git", "-C", a.src, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"{written} golem-fx presets from golem-fx {commit} -> library/block-presets "
          f"({len(changed)} changed, {len(removed)} removed, {len(problems)} problem(s); skipped types: {sorted(skipped)})")
    if a.check and (changed or removed):
        print("not up to date: " + ", ".join((changed + removed)[:10]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
