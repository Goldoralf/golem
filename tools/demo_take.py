#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LA PRISE DE DÉMO de la coquille (docs/private/launch-plan.md §4, 2026-11-04) : une vraie prise du rack, déposée dans
Library ▸ Tracks ▸ Recordings de la démo publique — le groupe généré par le bloc Standard et le solo du mainteneur,
sur un patch d'usine, une minute.

Une prise sort de chez quelqu'un : son take.json nomme son groupe, ses membres, sa session, la guitare qu'il joue,
le mode de sa machine. On ne garde que ce qui décrit la MUSIQUE — le patch, la scène, le tempo, les repères, les
sources et les rôles des entrées —, plus un titre. Les .wav sont copiés tels quels (l'instantané les convertit).

    ./tools/demo_take.py recordings/perf-20261104-000346 OUT_RECORDINGS [--title "Rooftop Prowl — solo"] [--drop-role Voice]

`--drop-role` retire les pistes d'une entrée de ce rôle (Input-N, Input-Nmerge, DI-…-Input-N) et son rôle — une voix
restée muette ; le reste de la prise n'est pas touché.

`tools/shell_snapshot.py --factory --take <dossier de prise>` l'appelle pour la poser dans son banc.
"""
import argparse
import json
import os
import re
import shutil

# ce que la démo montre d'une prise : la musique, jamais les gens ni la machine
KEEP = ("kind", "mode", "sources", "started_at", "ended_at", "started_at_utc", "started_epoch_ms", "sample_rate",
        "preset", "preset_name", "scene", "bpm", "flags", "roles", "standard", "backing", "looper", "drums", "files",
        "bwf_time_reference", "bwf_timestamp", "title")
MARK_KINDS = ("preset", "scene", "click", "standard", "backing", "section", "tempo")


def dropped_inputs(m, drop_roles):
    """Les numéros d'entrée dont le rôle est à retirer."""
    want = {r.lower() for r in drop_roles or []}
    return {n for n, r in (m.get("roles") or {}).items() if str(r).lower() in want}


def _of_input(f, inputs):
    mt = re.match(r"^(?:.+-)?Input-(\d+)(?:merge)?\.wav$", f, re.I)
    return bool(mt) and mt.group(1) in inputs


def clean_manifest(m, title=None, drop_roles=None):
    out = {k: m[k] for k in KEEP if k in m}
    gone = dropped_inputs(m, drop_roles)
    if gone:
        out["roles"] = {n: r for n, r in (m.get("roles") or {}).items() if n not in gone}
        if isinstance(out.get("sources"), dict):
            out["sources"] = {k: (False if k in {"in" + n for n in gone} else v) for k, v in out["sources"].items()}
        if isinstance(out.get("files"), list):
            out["files"] = [f for f in out["files"] if not _of_input(f, gone)]
    out["marks"] = [{k: v for k, v in mk.items() if k in ("sec", "at", "kind", "value", "name", "bpm")}
                    for mk in m.get("marks") or [] if isinstance(mk, dict) and mk.get("kind") in MARK_KINDS]
    if title:
        out["title"] = title
    return out


def demo_take(src, dest_recordings, title=None, drop_roles=None):
    """Copie la prise `src` dans `dest_recordings/<même nom>`, take.json nettoyé. Rend le chemin posé."""
    src = os.path.abspath(src)
    name = os.path.basename(src.rstrip("/"))
    dst = os.path.join(dest_recordings, name)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    with open(os.path.join(src, "take.json"), encoding="utf-8") as f:
        m = json.load(f)
    gone = dropped_inputs(m, drop_roles)
    for f in sorted(os.listdir(src)):
        if f.lower().endswith((".wav", ".flac", ".mid", ".seq")) and not _of_input(f, gone):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
    with open(os.path.join(dst, "take.json"), "w", encoding="utf-8") as f:
        json.dump(clean_manifest(m, title, drop_roles), f, ensure_ascii=False, indent=1)
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("take", help="the take folder (recordings/perf-…)")
    ap.add_argument("out", help="the recordings folder to put it in")
    ap.add_argument("--title", help="a title shown with the take")
    ap.add_argument("--drop-role", action="append", default=[], help="leave out the tracks of the input with this role")
    a = ap.parse_args()
    print(demo_take(a.take, a.out, a.title, a.drop_role))


if __name__ == "__main__":
    main()
