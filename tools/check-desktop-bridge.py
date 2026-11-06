#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie le démarrage réel du bridge et la réponse de l'interface locale."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def _get(port, path, timeout=15):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"{path} : HTTP {r.status}")
        return json.load(r)


def check_system_pages(port):
    """Les écrans System d'un poste ne doivent jamais retomber sur le chemin LINUX (/proc, ~/opt, dpkg) —
    l'état des lieux macOS du 2026-10-04 (docs/platforms.md, M0) en a trouvé un par écran.
    Sans carte son ni REAPER (CI) : on juge la FORME et la provenance, pas le matériel."""
    if sys.platform not in ("win32", "darwin"):
        return
    health = _get(port, "/api/system/health")
    ram = health.get("ram") or {}
    if not ram.get("total_mb") or health.get("cpu_pct") is None:
        raise RuntimeError(f"Dashboard : RAM/CPU illisibles sur {sys.platform} : {health}")
    libs = {c["id"]: c for c in _get(port, "/api/system/libraries", timeout=60)["components"]}
    for cid in ("reaper", "nam-core", "fastapi"):
        if libs.get(cid, {}).get("only") == "linux":
            raise RuntimeError(f"Libraries : « {cid} » dit Linux only sur {sys.platform}")
    net = _get(port, "/api/network", timeout=30)
    for key in ("ap", "station", "reachable", "golem"):
        if key not in net:
            raise RuntimeError(f"Network : clé « {key} » absente — la page planterait : {net}")
    _get(port, "/api/cards")
    _get(port, "/api/desktop/audio")
    upd = _get(port, "/api/system/reaper-update?check=0")
    if sys.platform == "darwin" and upd.get("can_update") is not False:
        raise RuntimeError(f"Licenses ▸ Reaper offre une mise à jour que macOS n'a pas : {upd}")
    print(f"Écrans System sur {sys.platform} : Dashboard, Libraries, Network, Soundcard, Licenses OK")


def main():
    with tempfile.TemporaryDirectory(prefix="golem-bridge-smoke-") as tmp:
        runtime = Path(tmp) / "runtime"
        runtime.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        log_path = Path(tmp) / "bridge.log"
        resource = Path(tmp) / "REAPER"
        resource.mkdir()
        python = (ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
                  if sys.platform in ("win32", "darwin") else Path(sys.executable))
        if not python.is_file():
            raise RuntimeError(f"environnement desktop absent : {python}")
        env = {**os.environ, "GOLEM_RUNTIME_DIR": str(runtime),
               "GOLEM_REAPER_RESOURCE_DIR": str(resource), "GOLEM_PORT": str(port),
               "PYTHONUTF8": "1"}
        with log_path.open("w", encoding="utf-8") as log:
            bridge = subprocess.Popen(
                [str(python), "-m", "uvicorn", "bridge.app:app", "--host", "127.0.0.1",
                 "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if bridge.poll() is not None:
                        break
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/app/", timeout=0.5) as response:
                            body = response.read()
                            if response.status != 200 or b"GoleM" not in body:
                                raise RuntimeError("interface absente ou réponse inattendue")
                            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as api:
                                if api.status != 200 or json.load(api).get("ok") is not True:
                                    raise RuntimeError("API de santé indisponible")
                            print(f"Bridge prêt sur {sys.platform} : HTTP 200, {len(body)} octets")
                            check_system_pages(port)
                            return
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                if bridge.poll() is not None:
                    raise RuntimeError(f"bridge arrêté avec le code {bridge.returncode}")
                raise RuntimeError("interface indisponible après 20 secondes")
            finally:
                if bridge.poll() is None:
                    if sys.platform == "win32":
                        # The venv launcher can leave a child holding bridge.log.
                        try:
                            subprocess.run(["taskkill", "/PID", str(bridge.pid), "/T", "/F"],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           check=False, timeout=5)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                    if bridge.poll() is None:
                        bridge.terminate()
                    try:
                        bridge.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        bridge.kill()
                        bridge.wait()
                if sys.exc_info()[0] is not None:
                    log.flush()
                    print(log_path.read_text(encoding="utf-8", errors="replace")[-4000:], file=sys.stderr)


if __name__ == "__main__":
    main()
