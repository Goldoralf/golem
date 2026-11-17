#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prépare le lecteur LV2 compilé (native/capture-lv2), sa provenance et ses empreintes, vérifiées à l'installation.

    ./tools/build-capture-lv2.sh /tmp/out/golem-capture.lv2
    python tools/package-capture-lv2.py linux-x86_64 /tmp/out/golem-capture.lv2

Comme tools/package-capture-player.py pour le CLAP : une archive par plateforme dans native/capture-lv2/bin, avec les
notices, et un manifeste (sha256 de l'archive, du binaire, des sources — celles du LV2 ET le cœur partagé de
native/capture)."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ("golem-capture.so", "manifest.ttl", "golem-capture.ttl")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("platform")
    parser.add_argument("bundle", type=Path, help="le dossier golem-capture.lv2 compilé")
    args = parser.parse_args()
    folder = ROOT / "native/capture-lv2/bin"
    folder.mkdir(exist_ok=True)
    archive = folder / (args.platform + ".zip")
    stamp = (2026, 11, 17, 0, 0, 0)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in FILES:
            info = zipfile.ZipInfo("golem-capture.lv2/" + name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".so") else 0o644) << 16
            z.writestr(info, (args.bundle / name).read_bytes())
        for license in sorted((ROOT / "native/capture/licenses").glob("*.txt")):
            entry = zipfile.ZipInfo("licenses/" + license.name, date_time=stamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, license.read_bytes())
        z.writestr(zipfile.ZipInfo("LICENSE-golem.txt", date_time=stamp), (ROOT / "LICENSE").read_bytes())
    sources = sorted((ROOT / "native/capture-lv2").glob("*.cpp")) + sorted((ROOT / "native/capture-lv2").glob("*.ttl")) \
        + [ROOT / "native/capture-lv2/CMakeLists.txt", ROOT / "native/capture/engine.cpp", ROOT / "native/capture/engine.h"]
    file = folder / "manifest.json"
    data = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    data[args.platform] = {"file": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                           "binary_sha256": hashlib.sha256((args.bundle / "golem-capture.so").read_bytes()).hexdigest(),
                           "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(archive, archive.stat().st_size)


if __name__ == "__main__":
    main()
