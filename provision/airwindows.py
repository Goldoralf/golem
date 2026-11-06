# SPDX-License-Identifier: GPL-3.0-or-later
"""Airwindows TapeDelay2 — le bloc « Tape Delay (Airwindows) », le même sous Linux et sous Windows.

2026-10-03 : un phaser et un tape delay qui existent sur les DEUX systèmes, à côté des blocs Calf
(Linux seulement). Airwindows (Chris Johnson, licence MIT) ne publie que des archives de TOUS ses
plugins, à une adresse qui ne change jamais — leur contenu, si. On n'épingle donc pas l'archive mais le
FICHIER qu'on en tire : TapeDelay2 n'a plus été recompilé depuis 2018 (Linux) et 2022 (Windows). Le
jour où il l'est, l'empreinte ne correspond plus et l'installation le DIT au lieu de poser un binaire
que personne n'a écouté ici.

Pas de droits d'administrateur : le plugin va dans un dossier de l'utilisateur que REAPER parcourt
déjà (Windows : le dossier VST3 par utilisateur, REAPER y lit aussi les VST2 ; Linux : ~/.vst).

    python provision/airwindows.py            # pose TapeDelay2 là où REAPER le trouve
    python provision/airwindows.py --check    # dit s'il est là, sans rien télécharger
"""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

PINS = {
    "win32": {"url": "https://www.airwindows.com/wp-content/uploads/WinVST64s.zip",
              "member": "WinVST64s/TapeDelay264.dll", "file": "TapeDelay264.dll",
              "sha256": "8c98815faab171c768fb1d5c572e13a4f75eae52e93ef18a83af1f30bfbcbc99"},
    "linux": {"url": "https://www.airwindows.com/wp-content/uploads/LinuxVSTs.zip",
              "member": "LinuxVSTs/TapeDelay2.so", "file": "TapeDelay2.so",
              "sha256": "10a4c43bd383bdfd38e9b2e23a35d1d47b7037dd62abb40f3ed6b626563b3b99"},
}


def _os():
    return "win32" if sys.platform == "win32" else "linux" if sys.platform.startswith("linux") else None


def dest_dir(platform=None):
    platform = platform or _os()
    if platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "Common" / "VST3" / "GoleM"
    return Path.home() / ".vst" / "airwindows"


def installed(platform=None):
    platform = platform or _os()
    pin = PINS.get(platform)
    return bool(pin) and (dest_dir(platform) / pin["file"]).is_file()


def _record(dest, existed, platform=None):
    """Reçu d'install (docs/uninstall.md §2 ; Windows §9.2) : le plugin posé. Jamais d'exception — un reçu raté ne
    casse pas l'installation. Sous Windows, seulement dans un reçu qui EXISTE (l'installateur le crée à l'étape
    « source » ; le setup lancé à la main sur une install d'avant le reçu n'en crée pas — provision/desktop.py)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", Path(__file__).with_name("receipt.py"))
        R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(R)
        if (platform or _os()) == "win32" and not R.exists():
            return
        R.add(str(dest), "file", "provision/airwindows.py", "plugins", existed=existed)
    except Exception as e:
        print(f"  ⚠ install receipt not updated ({e})", file=sys.stderr)


def install(platform=None, fetch=None, log=print):
    """Pose TapeDelay2 vérifié. Rend le chemin. `fetch(url) -> bytes` remplaçable par les tests."""
    platform = platform or _os()
    pin = PINS.get(platform)
    if not pin:
        raise RuntimeError(f"Airwindows TapeDelay2: no build pinned for {sys.platform}")
    dest = dest_dir(platform) / pin["file"]
    if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == pin["sha256"]:
        log(f"✓ Airwindows TapeDelay2 already in {dest.parent}")
        if platform == "win32":
            # dans le dossier « GoleM » : c'est le nôtre, même posé avant le reçu (sous Linux ~/.vst peut être à toi)
            _record(dest, False, platform)
        return dest
    if fetch is None:
        def fetch(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (golem install)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
    log(f"→ downloading {pin['url'].rsplit('/', 1)[-1]} (Airwindows, MIT)")
    with zipfile.ZipFile(io.BytesIO(fetch(pin["url"]))) as z:
        data = z.read(pin["member"])
    got = hashlib.sha256(data).hexdigest()
    if got != pin["sha256"]:
        raise RuntimeError(f"Airwindows TapeDelay2 changed upstream (sha256 {got[:12]}…, pinned "
                           f"{pin['sha256'][:12]}…) — not installed; re-validate it, then bump the pin")
    existed = dest.exists()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    _record(dest, existed, platform)
    log(f"✓ Airwindows TapeDelay2 → {dest} (REAPER sees it at its next start)")
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
