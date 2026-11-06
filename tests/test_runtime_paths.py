# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrats de chemin et d'ACK partagés par le bridge et le veilleur Reaper."""
import json
import os
import pytest

from bridge import commands, config as C


def test_reaper_resource_override_is_absolute_and_leaves_defaults_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLEM_REAPER_RESOURCE_DIR", raising=False)
    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert C.reaper_resource_dir() == os.path.join(str(tmp_path), "Roaming", "REAPER")

    monkeypatch.setenv("GOLEM_REAPER_RESOURCE_DIR", str(tmp_path / "isolated"))
    assert C.reaper_resource_dir() == str(tmp_path / "isolated")
    monkeypatch.setenv("GOLEM_REAPER_RESOURCE_DIR", "relative/path")
    with pytest.raises(ValueError, match="chemin absolu"):
        C.reaper_resource_dir()


def test_runtime_dir_conserve_tmpfs_linux_et_utilise_un_dossier_utilisateur(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLEM_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(C.sys, "platform", "linux")
    assert C.runtime_dir() == "/dev/shm"

    monkeypatch.setattr(C.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert C.runtime_dir() == os.path.join(str(tmp_path), "Local", "GoleM", "runtime")

    monkeypatch.setattr(C.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert C.runtime_dir() == os.path.join(str(tmp_path), "Library", "Caches", "GoleM", "runtime")


def test_ack_windows_par_sequence_libere_le_slot_sans_remplacer_le_fichier(monkeypatch, tmp_path):
    monkeypatch.setattr(commands.sys, "platform", "win32")
    command_file = tmp_path / ".command.json"
    ack_file = tmp_path / ".command-ack.json"
    monkeypatch.setattr(C, "COMMAND_FILE", str(command_file))
    monkeypatch.setattr(commands, "ACK_FILE", str(ack_file))
    command_file.write_text(json.dumps({"seq": 42}), encoding="utf-8")
    (tmp_path / ".command-ack.json.42").write_text(json.dumps({"seq": 42}), encoding="utf-8")

    commands._wait_slot_free()

    assert (tmp_path / ".command-ack.json.42").exists()
