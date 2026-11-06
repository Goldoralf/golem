# SPDX-License-Identifier: GPL-3.0-or-later
"""Sous Windows, os.replace échoue tant qu'un autre thread lit la cible (2026-10-03 : devices.json perdu, un
.tmp orphelin dans config/, la veille des branchements tuée). L'écriture atomique réessaie, et ne laisse
jamais de fichier temporaire derrière elle."""
import json

import pytest

from bridge import store


def test_reessaie_tant_que_la_cible_est_ouverte(tmp_path, monkeypatch):
    real, calls = store.os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "Permission denied")
        return real(src, dst)
    monkeypatch.setattr(store.os, "name", "nt")
    monkeypatch.setattr(store.os, "replace", flaky)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    target = tmp_path / "devices.json"
    store._write_json_atomic(str(target), {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1} and len(calls) == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_la_fente_de_commande_reessaie_aussi(tmp_path, monkeypatch):
    """2026-10-03 : `fxadd` partait en PermissionError pendant que golem_watch lisait .command.json."""
    from bridge import commands
    real, calls = store.os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 2:
            raise PermissionError(13, "Access denied")
        return real(src, dst)
    monkeypatch.setattr(commands.C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(commands.C, "COMMAND_FILE", str(tmp_path / ".command.json"))
    monkeypatch.setattr(store.os, "name", "nt")
    monkeypatch.setattr(store.os, "replace", flaky)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    seq = commands.write_command({"action": "ping"})
    assert json.loads((tmp_path / ".command.json").read_text())["seq"] == seq and len(calls) == 2


def test_echec_final_sans_fichier_temporaire(tmp_path, monkeypatch):
    def locked(src, dst):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(store.os, "name", "nt")
    monkeypatch.setattr(store.os, "replace", locked)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        store._write_json_atomic(str(tmp_path / "devices.json"), {"a": 1})
    assert not list(tmp_path.glob("*.tmp"))
