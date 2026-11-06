# SPDX-License-Identifier: GPL-3.0-or-later
"""La file de commandes (audit 2026-10-15) : une commande pas encore lue par golem_watch n'est plus écrasée."""
import json
import time

import pytest

from bridge import commands
from bridge import config as C


@pytest.fixture
def slot(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "COMMAND_FILE", str(tmp_path / ".command.json"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(commands, "ACK_FILE", str(tmp_path / ".command-ack.json"))
    monkeypatch.setattr(commands.sys, "platform", "linux")
    monkeypatch.setattr(commands, "_reaper_up", lambda: True)
    monkeypatch.setattr(commands, "_queue", [])
    monkeypatch.setattr(commands, "_drainer", None)

    def ack():                                  # golem_watch consomme ce qui est dans le slot
        seq = json.loads((tmp_path / ".command.json").read_text())["seq"]
        (tmp_path / ".command-ack.json").write_text(json.dumps({"seq": seq}))

    def current():
        return json.loads((tmp_path / ".command.json").read_text())
    return ack, current


def _wait(cond, t=2.0):
    end = time.time() + t
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_slot_libre_ecriture_immediate(slot):
    ack, current = slot
    commands.write_command({"action": "stomp", "block": "a"})
    assert current()["action"] == "stomp" and commands.queued() == []


def test_slot_occupe_la_commande_attend_dans_l_ordre(slot):
    ack, current = slot
    commands.write_command({"action": "rig_recall", "preset": "p1"})
    commands.write_command({"action": "stomp", "block": "a"})
    commands.write_command({"action": "stomp", "block": "b"})
    assert current()["action"] == "rig_recall"                 # rien n'a écrasé le rappel non lu
    assert [q["action"] for q in commands.queued()] == ["stomp", "stomp"]
    ack()
    assert _wait(lambda: current().get("block") == "a")
    ack()
    assert _wait(lambda: current().get("block") == "b")
    ack()
    assert _wait(lambda: commands._drainer is None)


def test_un_rappel_remplace_rappels_et_scenes_en_attente_jamais_un_stomp(slot):
    ack, current = slot
    commands.write_command({"action": "mixer_dump"})           # occupe le slot
    commands.write_command({"action": "rig_recall", "preset": "p1"})
    commands.write_command({"action": "scene_apply", "preset": "p1", "scene": "B"})
    commands.write_command({"action": "stomp", "block": "a"})
    commands.write_command({"action": "rig_recall", "preset": "p2"})
    commands.write_command({"action": "scene_apply", "preset": "p2", "scene": "C"})
    commands.write_command({"action": "scene_apply", "preset": "p2", "scene": "D"})
    assert [(q["action"], q.get("preset"), q.get("scene")) for q in commands._queue] == [
        ("stomp", None, None), ("rig_recall", "p2", None), ("scene_apply", "p2", "D")]
    commands._queue.clear()


def test_reaper_eteint_on_ecrase_comme_avant(slot, monkeypatch):
    ack, current = slot
    commands.write_command({"action": "stomp", "block": "a"})
    import os
    old = time.time() - 10
    os.utime(C.COMMAND_FILE, (old, old))
    monkeypatch.setattr(commands, "_reaper_up", lambda: False)
    commands.write_command({"action": "stomp", "block": "b"})
    assert current()["block"] == "b" and commands.queued() == []
