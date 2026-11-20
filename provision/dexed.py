# SPDX-License-Identifier: GPL-3.0-or-later
"""Dexed (Digital Suburban, GPL-3) sous Windows — le synthé FM DX7 du bloc « ep » (piano électrique).

2026-11-20 : Dexed existait pour Windows, mais rien ne l'installait — le bloc ep restait « untested » dans
effects-windows.json et le Golem Engine ne pouvait pas le jouer (banc check-engine-ardour : 3 échecs). Posé à la
main sur le poste de dev, le banc passe : la voix SysEx est lue, le piano sonne. L'archive officielle win64 (VST3,
CLAP, standalone) est épinglée à son empreinte (celle que GitHub publie pour la release) ; on n'en tire que le bundle
VST3 que la table nomme.

Pas de droits d'administrateur : comme provision/dragonfly.py, le bundle va dans le dossier VST3 par utilisateur
que REAPER et le Golem Engine parcourent (%LOCALAPPDATA%\\Programs\\Common\\VST3\\GoleM). Linux :
provision/plugins.sh (~/.vst3).

    python provision/dexed.py            # pose Dexed là où REAPER et le moteur le trouvent
    python provision/dexed.py --check    # dit s'il est là, sans rien télécharger
"""
import hashlib
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.0.1"                                        # la même que provision/plugins.sh (Linux)
PIN = {"url": f"https://github.com/asb2m10/dexed/releases/download/v{VERSION}/Dexed-{VERSION}-win.zip",
       "sha256": "1f118445f2c5c411636bb41ddf8b456db09af74cd38f9ede8a93a01020505f05"}
BUNDLE = "Dexed.vst3"                                    # à la racine de l'archive


def dest_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "Common" / "VST3" / "GoleM"


def _found(dest=None):
    return ((dest or dest_dir()) / BUNDLE / "Contents").is_dir()


def installed():
    """Dexed est là pour golem : dans son dossier, ou déjà installé dans Common Files (l'installeur officiel)."""
    if sys.platform != "win32":
        return False
    common = Path(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")) / "VST3" / BUNDLE
    return _found() or (common / "Contents").is_dir()


def _record(paths, existed):
    """Reçu d'install (docs/uninstall.md §9.2) : le bundle posé, dans un reçu qui EXISTE seulement (comme
    dragonfly). Jamais d'exception — un reçu raté ne casse pas l'installation."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", Path(__file__).with_name("receipt.py"))
        R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(R)
        if not R.exists():
            return
        for p in paths:
            R.add(str(p), "dir", "provision/dexed.py", "plugins", existed=existed)
    except Exception as e:
        print(f"  ⚠ install receipt not updated ({e})", file=sys.stderr)


def install(fetch=None, log=print, dest=None):
    """Pose le VST3 Dexed vérifié. Rend le dossier. `fetch(url) -> bytes` remplaçable par les tests."""
    if sys.platform != "win32" and dest is None:
        raise RuntimeError("Dexed: this installer is for Windows (Linux: provision/plugins.sh)")
    dest = Path(dest or dest_dir())
    if _found(dest):
        log(f"✓ Dexed already in {dest}")
        _record([dest / BUNDLE], False)
        return dest
    if fetch is None:
        def fetch(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (golem install)"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
    log(f"→ downloading {PIN['url'].rsplit('/', 1)[-1]} (Dexed {VERSION}, GPL-3)")
    data = fetch(PIN["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != PIN["sha256"]:
        raise RuntimeError(f"Dexed archive changed upstream (sha256 {got[:12]}…, pinned {PIN['sha256'][:12]}…) "
                           "— not installed")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        prefix = BUNDLE + "/"
        members = [n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if not members:
            raise RuntimeError(f"Dexed: {BUNDLE} not in the archive")
        # posé à côté puis renommé : un REAPER qui scanne ne voit jamais un bundle à moitié copié
        tmp = dest / (BUNDLE + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        for n in members:
            rel = n[len(prefix):]
            if ".." in Path(rel).parts:                     # une archive ne sort jamais de son dossier
                shutil.rmtree(tmp, ignore_errors=True)
                raise RuntimeError(f"Dexed: unsafe path {n}")
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))
        final = dest / BUNDLE
        if final.exists():
            shutil.rmtree(final)
        os.replace(tmp, final)
    _record([final], False)
    log(f"✓ Dexed → {dest} (REAPER and the Golem Engine see it at their next start)")
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
