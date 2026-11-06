# SPDX-License-Identifier: GPL-3.0-or-later
"""Le lecteur fait partie de golem ; aucun trainer ni VST commercial à installer."""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native" / "capture"


def platform_key():
    arch = platform.machine().lower()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(arch, arch)
    return {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform, sys.platform) + "-" + arch


def plugin_dir():
    import os
    if sys.platform == "win32":
        # le chemin CLAP standard PAR UTILISATEUR (spec CLAP ; pas de droits d'admin). Mesuré le 2026-10-19 :
        # REAPER ne balaie PAS %APPDATA%\CLAP (le lecteur y était posé, absent de reaper-clap-win64.ini) ;
        # posé ici, il apparaît au redémarrage sous « golem Capture (golem) », le nom attendu par effects.json.
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs" / "Common" / "CLAP"
    if sys.platform == "darwin":
        return Path.home() / "Library/Audio/Plug-Ins/CLAP"
    return Path.home() / ".clap"


def install_bundled():
    """Le démarrage desktop ne déclenche jamais un build réseau pour une plateforme non livrée."""
    manifest_file = SOURCE / "bin" / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.is_file() else {}
    return install() if platform_key() in manifest else None


def install(destination=None):
    """Copie vérifiée d'un lecteur livré ; sur une autre architecture, build du même code épinglé."""
    target = Path(destination) if destination else plugin_dir()
    manifest_file = SOURCE / "bin" / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.is_file() else {}
    entry = manifest.get(platform_key())
    target.mkdir(parents=True, exist_ok=True)
    def record(path, existed):
        if destination is None and sys.platform == "linux":
            # Le reçu (provision/receipt.py, `add`) rend le lecteur désinstallable comme les autres plugins du
            # rack. Écrit DANS le processus :
            # un sous-processus Python à chaque `start` est inutile, et le lanceur ne doit lancer que le bridge
            # (tests/test_launcher_single_instance.py). Un reçu absent ou en échec n'empêche jamais le démarrage.
            # receipt.py chargé par son CHEMIN, comme surge.py : lancé en script (install-capture.sh), `provision`
            # n'est pas importable — le reçu ne notait pas le lecteur (VM 2026-10-23), le désinstalleur l'oubliait
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("golem_receipt", Path(__file__).with_name("receipt.py"))
                receipt = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(receipt)
                if receipt.exists():
                    receipt.add(str(path), "file", "capture_player.py", "capture-player", existed=existed)
            except Exception as exc:
                print(f"⚠ install receipt not updated ({exc})", file=sys.stderr)
    if entry:
        archive = SOURCE / "bin" / entry["file"]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Bundled capture player checksum mismatch")
        with zipfile.ZipFile(archive) as z:
            # Une liste exacte évite d'extraire du code ou un chemin fourni par une capture.
            data = z.read("golem-capture.clap")
        path = target / "golem-capture.clap"
        existed = path.exists()
        if not path.is_file() or path.read_bytes() != data:
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data); tmp.replace(path)
        record(path, existed)
        return path
    build = ROOT / "assets" / ".cache" / "capture-player-build"
    subprocess.run(["cmake", "-S", str(SOURCE), "-B", str(build), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"], check=True)
    subprocess.run(["cmake", "--build", str(build), "--parallel", "2"], check=True)
    path = target / "golem-capture.clap"
    existed = path.exists()
    if (build / "golem-capture.clap").is_dir():
        shutil.copytree(build / "golem-capture.clap", path, dirs_exist_ok=True)
    else:
        shutil.copy2(build / "golem-capture.clap", path)
    record(path, existed)
    return path


if __name__ == "__main__":
    print(install())
