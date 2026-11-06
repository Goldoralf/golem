#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prépare les lecteurs compilés, leur provenance et leurs empreintes vérifiées par l'installateur."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("platform")
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    folder = ROOT / "native/capture/bin"
    folder.mkdir(exist_ok=True)
    archive = folder / (args.platform + ".zip")
    info = zipfile.ZipInfo("golem-capture.clap", date_time=(2026, 10, 16, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(info, args.binary.read_bytes())
        for license in sorted((ROOT / "native/capture/licenses").glob("*.txt")):
            entry = zipfile.ZipInfo("licenses/" + license.name, date_time=(2026, 10, 16, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, license.read_bytes())
        z.writestr("LICENSE-golem.txt", (ROOT / "LICENSE").read_bytes())
    file = folder / "manifest.json"
    data = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    sources = sorted((ROOT / "native/capture").glob("*.cpp")) + sorted((ROOT / "native/capture").glob("*.h")) + [ROOT / "native/capture/CMakeLists.txt"]
    data[args.platform] = {"file": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                           "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                           "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(archive, archive.stat().st_size)


if __name__ == "__main__":
    main()
