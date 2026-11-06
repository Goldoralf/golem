# SPDX-License-Identifier: GPL-3.0-or-later
"""Surge XT Effects (Surge Synth Team, GPL-3) sous Windows — les blocs « surge-spring », « surge-freqshift » et
« surge-treemonster ».

2026-10-22 : effects-windows.json disait Surge XT « installé » ; l'inventaire REAPER du poste de dev ne le portait
pas. L'archive officielle « pluginsonly » win64 est épinglée à son empreinte ; on n'en tire que le bundle VST3
« Surge XT Effects » (le synthé Surge XT lui-même n'est pas un bloc).

Pas de droits d'administrateur : comme provision/dragonfly.py, le bundle va dans le dossier VST3 par utilisateur
que REAPER parcourt déjà (%LOCALAPPDATA%\\Programs\\Common\\VST3\\GoleM).

    python provision/surge.py            # pose Surge XT Effects là où REAPER le trouve
    python provision/surge.py --check    # dit s'il est là, sans rien télécharger
"""
import hashlib
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.3.4"
PIN = {"url": f"https://github.com/surge-synthesizer/releases-xt/releases/download/{VERSION}/surge-xt-win64-{VERSION}-pluginsonly.zip",
       "sha256": "564e162c560af07ad4ed47fe1bfcd827cf97a575de30d06c48249aad2e7c35e6"}
BUNDLE = "Surge XT Effects.vst3"


def dest_dir():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "Common" / "VST3" / "GoleM"


def installed(dest=None):
    dest = dest or dest_dir()
    return sys.platform == "win32" and (dest / BUNDLE / "Contents").is_dir()


def _record(path, existed):
    """Reçu d'install (docs/uninstall.md §9.2), dans un reçu qui EXISTE seulement ; jamais d'exception."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", Path(__file__).with_name("receipt.py"))
        R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(R)
        if not R.exists():
            return
        R.add(str(path), "dir", "provision/surge.py", "plugins", existed=existed)
    except Exception as e:
        print(f"  ⚠ install receipt not updated ({e})", file=sys.stderr)


def install(fetch=None, log=print, dest=None):
    """Pose le VST3 Surge XT Effects vérifié. Rend le dossier. `fetch(url) -> bytes` remplaçable par les tests."""
    if sys.platform != "win32" and dest is None:
        raise RuntimeError("Surge XT: this installer is for Windows (Linux: apt surge-xt ; macOS: manual pin)")
    dest = Path(dest or dest_dir())
    if (dest / BUNDLE / "Contents").is_dir():
        log(f"✓ Surge XT Effects already in {dest}")
        _record(dest / BUNDLE, True)
        return dest
    if fetch is None:
        def fetch(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (golem install)"})
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.read()
    log(f"→ downloading {PIN['url'].rsplit('/', 1)[-1]} (Surge XT {VERSION}, GPL-3, 46 MB)")
    data = fetch(PIN["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != PIN["sha256"]:
        raise RuntimeError(f"Surge XT archive changed upstream (sha256 {got[:12]}…, pinned {PIN['sha256'][:12]}…) — not installed")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        prefix = BUNDLE + "/"
        members = [n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if not members:
            raise RuntimeError(f"Surge XT: {BUNDLE} not in the archive")
        tmp = dest / (BUNDLE + ".part")                      # posé à côté puis renommé : jamais un bundle à moitié copié
        shutil.rmtree(tmp, ignore_errors=True)
        for n in members:
            rel = n[len(prefix):]
            if ".." in Path(rel).parts:
                raise RuntimeError(f"Surge XT: unsafe path {n}")
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))
        final = dest / BUNDLE
        if final.exists():
            shutil.rmtree(final)
        os.replace(tmp, final)
    _record(dest / BUNDLE, False)
    log(f"✓ Surge XT Effects → {dest} (REAPER sees it at its next start)")
    return dest


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("installed" if installed() else "missing")
        sys.exit(0 if installed() else 1)
    install()
