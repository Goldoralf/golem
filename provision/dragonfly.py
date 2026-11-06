# SPDX-License-Identifier: GPL-3.0-or-later
"""Dragonfly Reverb (Michael Willis, GPL-3) sous Windows — les blocs « Reverb » (Hall), « Plate » et « Room ».

2026-10-22 : effects-windows.json nommait les VST3 Dragonfly, mais rien ne les installait — mesuré sur le poste de
dev : les trois réverbes manquaient, et avec elles 45 objets d'usine sur 47 jouaient sans réverbe. L'archive
officielle win64 (VST2, VST3, LV2, CLAP, standalone) est épinglée à son empreinte ; on n'en tire que les trois
bundles VST3 que la table nomme.

Pas de droits d'administrateur : comme provision/airwindows.py, les bundles vont dans le dossier VST3 par
utilisateur que REAPER parcourt déjà (%LOCALAPPDATA%\\Programs\\Common\\VST3\\GoleM).

    python provision/dragonfly.py            # pose les trois réverbes là où REAPER les trouve
    python provision/dragonfly.py --check    # dit si elles sont là, sans rien télécharger
"""
import hashlib
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.2.10"
PIN = {"url": f"https://github.com/michaelwillis/dragonfly-reverb/releases/download/{VERSION}/"
              f"dragonfly-reverb-{VERSION}-win64.zip",
       "sha256": "ca5f35f9dcd9a33f06490d3c92f04061a1a798cb81257d5ca5851bdda0824c66"}
# les bundles que effects-windows.json nomme (reverb, reverb-plate, reverb-room)
BUNDLES = ("DragonflyHallReverb.vst3", "DragonflyPlateReverb.vst3", "DragonflyRoomReverb.vst3")
ROOT_IN_ZIP = f"dragonfly-reverb-{VERSION}/"


def dest_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "Common" / "VST3" / "GoleM"


def _found(dest=None):
    dest = dest or dest_dir()
    return [b for b in BUNDLES if (dest / b / "Contents").is_dir()]


def installed():
    return sys.platform == "win32" and len(_found()) == len(BUNDLES)


def _record(paths, existed):
    """Reçu d'install (docs/uninstall.md §9.2) : chaque bundle posé, dans un reçu qui EXISTE seulement (comme
    airwindows). Jamais d'exception — un reçu raté ne casse pas l'installation."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", Path(__file__).with_name("receipt.py"))
        R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(R)
        if not R.exists():
            return
        for p in paths:
            R.add(str(p), "dir", "provision/dragonfly.py", "plugins", existed=existed)
    except Exception as e:
        print(f"  ⚠ install receipt not updated ({e})", file=sys.stderr)


def install(fetch=None, log=print, dest=None):
    """Pose les trois VST3 Dragonfly vérifiés. Rend le dossier. `fetch(url) -> bytes` remplaçable par les tests."""
    if sys.platform != "win32" and dest is None:
        raise RuntimeError("Dragonfly Reverb: this installer is for Windows (Linux: provision/plugins.sh)")
    dest = Path(dest or dest_dir())
    if len(_found(dest)) == len(BUNDLES):
        log(f"✓ Dragonfly Reverb already in {dest}")
        _record([dest / b for b in BUNDLES], False)
        return dest
    if fetch is None:
        def fetch(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (golem install)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
    log(f"→ downloading {PIN['url'].rsplit('/', 1)[-1]} (Dragonfly Reverb {VERSION}, GPL-3)")
    data = fetch(PIN["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != PIN["sha256"]:
        raise RuntimeError(f"Dragonfly Reverb archive changed upstream (sha256 {got[:12]}…, pinned "
                           f"{PIN['sha256'][:12]}…) — not installed")
    dest.mkdir(parents=True, exist_ok=True)
    posed = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        for b in BUNDLES:
            prefix = ROOT_IN_ZIP + b + "/"
            members = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
            if not members:
                raise RuntimeError(f"Dragonfly Reverb: {b} not in the archive")
            # posé à côté puis renommé : un REAPER qui scanne ne voit jamais un bundle à moitié copié
            tmp = dest / (b + ".part")
            shutil.rmtree(tmp, ignore_errors=True)
            for n in members:
                rel = n[len(prefix):]
                if ".." in Path(rel).parts:                 # une archive ne sort jamais de son dossier
                    raise RuntimeError(f"Dragonfly Reverb: unsafe path {n}")
                out = tmp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(n))
            final = dest / b
            if final.exists():
                shutil.rmtree(final)
            os.replace(tmp, final)
            posed.append(final)
    _record(posed, False)
    log(f"✓ Dragonfly Reverb → {dest} (REAPER sees it at its next start)")
    return dest


if __name__ == "__main__":
    if "--check" in sys.argv:
        ok = installed()
        print(("✓ installed in " if ok else "✗ missing from ") + str(dest_dir()))
        sys.exit(0 if ok else 1)
    try:
        install()
    except Exception as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
