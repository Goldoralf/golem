#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Empaquette les DÉMOS D'USINE pour les publier une fois (docs/preset-preview.md §10, 2026-11-15).

Chaque golem rendait lui-même toutes les démos d'usine — une demi-heure de moteur pris, 67 Mo refaits partout. Elles
sont rendues UNE fois (sur le rack du mainteneur), empaquetées ici, publiées en asset de release (golem-binaries,
`factory-demos-vN`) ; un golem les télécharge (bridge/factory_demos.py) et ne rend que ce qui manque ou a changé. golem.fm
prend la même archive : une seule source.

Ce qui part : les démos des patchs d'usine (patch-factory-*), des lanes des presets d'usine (preset-factory-*), des
blocs drums/standard (block-factory-*, block-patch-factory-*), des sons claviers d'usine (sound-* de
sound_preview.factory_sounds) et des kits d'usine (kit-<id> de drum_preview.factory_kits). Jamais une démo de
l'utilisateur (ses presets Vital, ses kits importés, ses écoutes).

    ./tools/pack-factory-demos.py                 # -> assets/.cache/factory-demos/golem-factory-demos.tar + .json (index, sha256)
    ./tools/pack-factory-demos.py --publish factory-demos-v1   # + gh release create sur Goldoralf/golem-binaries
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REPO = "Goldoralf/golem-binaries"
NAME = "golem-factory-demos"


def factory_dirs():
    from bridge import config as C, sound_preview as SP, drum_preview as DP
    root = C.PREVIEWS_DIR
    prefixes = ("patch-factory-", "preset-factory-", "block-factory-", "block-patch-factory-")
    keep = {os.path.basename(SP.sound_dir(s)) for s in SP.factory_sounds()}
    keep |= {os.path.basename(DP.kit_dir(k)) for k in DP.factory_kits()}
    out = []
    for d in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if os.path.isdir(os.path.join(root, d)) and (d.startswith(prefixes) or d in keep):
            out.append(d)
    return root, out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", ".cache", "factory-demos"))
    ap.add_argument("--publish", metavar="TAG", help="publish to the golem-binaries release TAG (gh, not marked latest)")
    a = ap.parse_args()
    root, dirs = factory_dirs()
    os.makedirs(a.out, exist_ok=True)
    tar_path = os.path.join(a.out, NAME + ".tar")
    index = {"name": NAME, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "items": {}}
    with tarfile.open(tar_path, "w") as tf:                 # .opus déjà compressé : un tar simple
        for d in dirs:
            # les lanes d'un preset (preset-x/<lane>/) et les blocs (block-x/<switch>/) sont un niveau plus bas
            for sub, _ds, fs in sorted(os.walk(os.path.join(root, d))):
                rel = os.path.relpath(sub, root).replace(os.sep, "/")
                files = {}
                for f in sorted(fs):
                    p = os.path.join(sub, f)
                    if not f.endswith((".wav", ".tmp", ".midi.txt")):
                        files[f] = hashlib.sha256(open(p, "rb").read()).hexdigest()
                        tf.add(p, arcname=f"{rel}/{f}")
                if files:
                    index["items"][rel] = files
    index["sha256"] = hashlib.sha256(open(tar_path, "rb").read()).hexdigest()
    index["bytes"] = os.path.getsize(tar_path)
    idx_path = os.path.join(a.out, NAME + ".json")
    json.dump(index, open(idx_path, "w"), indent=1)
    print(f"{len(index['items'])} demo folders, {index['bytes'] / 1e6:.1f} MB -> {tar_path}")
    if a.publish:
        notes = (f"Factory sound demos of golem, rendered once and shared ({len(index['items'])} folders). "
                 "Downloaded by bridge/factory_demos.py; golem.fm reads the same archive.")
        subprocess.run(["gh", "release", "create", a.publish, "--repo", REPO, "--title", f"Factory demos ({a.publish})",
                        "--notes", notes, "--latest=false", tar_path, idx_path], check=True)
        print(f"published: https://github.com/{REPO}/releases/tag/{a.publish}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
