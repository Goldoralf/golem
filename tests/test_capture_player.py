# SPDX-License-Identifier: GPL-3.0-or-later
"""Les binaires livrés correspondent aux sources, voyagent avec leurs licences et s'installent sans compilateur."""
import hashlib
import json
from pathlib import Path
import zipfile

from provision import capture_player as P


def test_bundled_players_have_pinned_bytes_sources_and_notices():
    manifest = json.loads((P.SOURCE / "bin/manifest.json").read_text(encoding="utf-8"))
    assert {"windows-x86_64", "linux-x86_64"} <= set(manifest)
    for key, entry in manifest.items():
        archive = P.SOURCE / "bin" / entry["file"]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry["sha256"], key
        with zipfile.ZipFile(archive) as z:
            binary = z.read("golem-capture.clap")
            assert hashlib.sha256(binary).hexdigest() == entry["binary_sha256"]
            assert {"licenses/NAMCore.txt", "licenses/CLAP.txt", "licenses/Eigen-MPL2.txt", "LICENSE-golem.txt"} <= set(z.namelist())
        for file, sha in entry["sources"].items():
            assert hashlib.sha256((P.SOURCE / file).read_bytes()).hexdigest() == sha, (key, file)


def test_install_uses_the_bundled_reader_without_a_trainer_or_compiler(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "platform_key", lambda: "windows-x86_64")
    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a compiler was started")))
    binary = P.install(tmp_path)
    assert binary == tmp_path / "golem-capture.clap" and binary.stat().st_size > 100000
    before = binary.stat().st_mtime_ns
    assert P.install(tmp_path).stat().st_mtime_ns == before


def test_linux_reader_exports_only_its_clap_entry(tmp_path):
    """Le cœur NAM exporté partageait son registre (symbole GNU unique) avec le plugin NAM du même REAPER : la seconde
    inscription de SlimmableContainer tuait REAPER (2026-10-25, docs/pitfalls/plugins.md)."""
    import shutil
    import subprocess
    import pytest
    if not shutil.which("nm"):
        pytest.skip("nm absent")
    with zipfile.ZipFile(P.SOURCE / "bin/linux-x86_64.zip") as z:
        (tmp_path / "golem-capture.clap").write_bytes(z.read("golem-capture.clap"))
    out = subprocess.run(["nm", "-D", "--defined-only", str(tmp_path / "golem-capture.clap")],
                         capture_output=True, text=True, check=True).stdout
    assert [line.split()[-1] for line in out.splitlines() if line.strip()] == ["clap_entry"]
