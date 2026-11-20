#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prépare le lecteur LV2 compilé (native/capture-lv2), sa provenance et ses empreintes, vérifiées à l'installation.

    ./tools/build-capture-lv2.sh /tmp/out/golem-capture.lv2
    python tools/package-capture-lv2.py linux-x86_64 /tmp/out/golem-capture.lv2
    # Windows (MSYS2 UCRT64) : cmake -S native/capture-lv2/windows -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
    python tools/package-capture-lv2.py windows-x86_64 build/golem-capture.lv2

Comme tools/package-capture-player.py pour le CLAP : une archive par plateforme dans native/capture-lv2/bin, avec les
notices, et un manifeste (sha256 de l'archive, du binaire, des sources — celles du LV2 ET le cœur partagé de
native/capture)."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def binary_name(platform):
    """Le binaire du bundle : golem-capture.dll sous Windows, .so ailleurs (le manifeste LV2 le nomme)."""
    return "golem-capture.dll" if platform.startswith("windows") else "golem-capture.so"


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
        binary = binary_name(args.platform)
        for name in (binary, "manifest.ttl", "golem-capture.ttl"):
            info = zipfile.ZipInfo("golem-capture.lv2/" + name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name == binary else 0o644) << 16
            z.writestr(info, (args.bundle / name).read_bytes())
        for license in sorted((ROOT / "native/capture/licenses").glob("*.txt")):
            entry = zipfile.ZipInfo("licenses/" + license.name, date_time=stamp)
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, license.read_bytes())
        z.writestr(zipfile.ZipInfo("LICENSE-golem.txt", date_time=stamp), (ROOT / "LICENSE").read_bytes())
    sources = sorted((ROOT / "native/capture-lv2").glob("*.cpp")) + sorted((ROOT / "native/capture-lv2").glob("*.ttl")) \
        + [ROOT / "native/capture-lv2/CMakeLists.txt", ROOT / "native/capture/engine.cpp", ROOT / "native/capture/engine.h"]
    if args.platform.startswith("windows"):                 # son propre CMakeLists (les mêmes sources, sans les toucher)
        sources.append(ROOT / "native/capture-lv2/windows/CMakeLists.txt")
    lv2 = ROOT / "native/capture-lv2"
    file = folder / "manifest.json"
    data = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    data[args.platform] = {"file": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                           "binary_sha256": hashlib.sha256((args.bundle / binary).read_bytes()).hexdigest(),
                           "sources": {(p.relative_to(lv2).as_posix() if p.is_relative_to(lv2 / "windows") else p.name):
                                       hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")   # LF partout (.gitattributes)
    print(archive, archive.stat().st_size)


if __name__ == "__main__":
    main()
