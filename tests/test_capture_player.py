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


# ── le même lecteur en LV2, pour le Golem Engine (native/capture-lv2) ───────────────────────────────────────────────
def test_the_lv2_reader_is_pinned_like_the_clap_one():
    manifest = json.loads((P.LV2_SOURCE / "bin/manifest.json").read_text(encoding="utf-8"))
    assert "linux-x86_64" in manifest
    for key, entry in manifest.items():
        archive = P.LV2_SOURCE / "bin" / entry["file"]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry["sha256"], key
        with zipfile.ZipFile(archive) as z:
            binary = "golem-capture.dll" if key.startswith("windows") else "golem-capture.so"
            assert hashlib.sha256(z.read("golem-capture.lv2/" + binary)).hexdigest() == entry["binary_sha256"]
            manifest_ttl = z.read("golem-capture.lv2/manifest.ttl").decode()
            assert f"<{binary}>" in manifest_ttl, key                      # le manifeste nomme le binaire livré
            assert {"golem-capture.lv2/manifest.ttl", "golem-capture.lv2/golem-capture.ttl", "licenses/NAMCore.txt",
                    "licenses/Eigen-MPL2.txt", "LICENSE-golem.txt"} <= set(z.namelist())
        for file, sha in entry["sources"].items():                       # ses sources ET le cœur partagé avec le CLAP
            src = P.LV2_SOURCE / file if (P.LV2_SOURCE / file).is_file() else P.SOURCE / file
            assert hashlib.sha256(src.read_bytes()).hexdigest() == sha, (key, file)


def test_the_lv2_reader_installs_only_where_the_golem_engine_is(tmp_path, monkeypatch):
    monkeypatch.setattr(P.sys, "platform", "linux")
    monkeypatch.setattr(P, "platform_key", lambda: "linux-x86_64")
    monkeypatch.setenv("GOLEM_ENGINE_DIR", str(tmp_path / "no-engine"))
    assert P.install_lv2_bundled(tmp_path / "out") is None               # REAPER seul : rien n'est posé
    run = tmp_path / "engine" / "golem" / "engine" / "run.sh"
    run.parent.mkdir(parents=True)
    run.write_text("#!/bin/sh\n")
    monkeypatch.setenv("GOLEM_ENGINE_DIR", str(tmp_path / "engine"))
    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a compiler was started")))
    out = P.install_lv2_bundled(tmp_path / "out")
    assert out == tmp_path / "out" and sorted(f.name for f in out.iterdir()) == ["golem-capture.so", "golem-capture.ttl", "manifest.ttl"]
    monkeypatch.setattr(P, "platform_key", lambda: "linux-aarch64")
    assert P.install_lv2_bundled(tmp_path / "arm") is None               # plateforme non livrée : pas de build au démarrage


def test_the_lv2_reader_installs_on_windows_in_the_lilv_default_path(tmp_path, monkeypatch):
    """Windows (2026-11-20) : le Golem Engine y joue les captures pilotables avec le MÊME lecteur, une .dll posée sans
    droits d'admin dans %APPDATA%\\LV2 (le chemin LV2 par défaut de lilv)."""
    manifest = json.loads((P.LV2_SOURCE / "bin/manifest.json").read_text(encoding="utf-8"))
    assert "windows-x86_64" in manifest
    monkeypatch.setattr(P.sys, "platform", "win32")
    monkeypatch.setattr(P, "platform_key", lambda: "windows-x86_64")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert P.lv2_dir() == tmp_path / "Roaming" / "LV2" / "golem-capture.lv2"
    out = P.install_lv2_bundled(tmp_path / "out", force=True)
    assert sorted(f.name for f in out.iterdir()) == ["golem-capture.dll", "golem-capture.ttl", "manifest.ttl"]


def test_the_lv2_reader_exports_only_its_descriptor(tmp_path):
    import shutil
    import subprocess
    import pytest
    if not shutil.which("nm"):
        pytest.skip("nm absent")
    with zipfile.ZipFile(P.LV2_SOURCE / "bin/linux-x86_64.zip") as z:
        (tmp_path / "golem-capture.so").write_bytes(z.read("golem-capture.lv2/golem-capture.so"))
    out = subprocess.run(["nm", "-D", "--defined-only", str(tmp_path / "golem-capture.so")], capture_output=True, text=True, check=True).stdout
    assert [ln.split()[-1] for ln in out.splitlines() if ln.strip()] == ["lv2_descriptor"]
