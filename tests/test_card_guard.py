# SPDX-License-Identifier: GPL-3.0-or-later
"""La carte de golem hors du son du bureau (bridge/card_guard.py) : qui la tient, la règle WirePlumber, et ce que
Health en dit. Rack Linux 2026-11-26 : Firefox jouait sur l'iTwo à travers PipeWire, REAPER a démarré sans carte,
l'écran restait sur « Still starting. »."""
import os

import pytest

from bridge import card_guard as G
from bridge import commands, fixes, monitors
from bridge.state import state

DUMP = [
    {"id": 78, "type": "PipeWire:Interface:Device", "info": {"props": {"alsa.id": "iTwo"}}},
    {"id": 44, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink", "alsa.card": 1}}},
    {"id": 46, "type": "PipeWire:Interface:Node", "info": {"props": {"media.class": "Audio/Sink", "alsa.card": 0}}},
    {"id": 85, "type": "PipeWire:Interface:Node", "info": {"props": {"application.name": "Firefox"}}},
    {"id": 90, "type": "PipeWire:Interface:Link", "info": {"output-node-id": 85, "input-node-id": 44}},
]


def fake_proc(tmp_path, procs):
    """Un faux /proc : {pid: (comm, [cibles des fd])}."""
    for pid, (comm, targets) in procs.items():
        d = tmp_path / str(pid)
        (d / "fd").mkdir(parents=True)
        (d / "comm").write_text(comm + "\n")
        for i, t in enumerate(targets):
            os.symlink(t, d / "fd" / str(i))
    return str(tmp_path)


def test_qui_tient_la_carte(tmp_path):
    proc = fake_proc(tmp_path, {1867: ("pipewire", ["/dev/snd/pcmC1D0p", "/dev/snd/seq"]),
                                500: ("reaper", ["/dev/snd/pcmC0D0c"]), 7: ("bash", ["/dev/null"])})
    assert G.holders(1, proc) == [{"pid": 1867, "name": "pipewire"}]
    assert G.holders(0, proc) == [{"pid": 500, "name": "reaper"}]


def test_les_applications_derriere_pipewire():
    assert G.desktop_apps(1, DUMP) == ["Firefox"]
    assert G.desktop_apps(0, DUMP) == []


def test_held_ignore_les_moteurs_de_golem(monkeypatch):
    monkeypatch.setattr(G.sys, "platform", "linux")
    monkeypatch.setattr(G, "card_number", lambda cid: 1)
    monkeypatch.setattr(G, "_pw_dump", lambda: DUMP)
    monkeypatch.setattr(G, "holders", lambda n: [{"pid": 2, "name": "reaper"}])
    assert G.held("iTwo") is None
    monkeypatch.setattr(G, "holders", lambda n: [{"pid": 3, "name": "pipewire"}])
    h = G.held("iTwo")
    assert h["desktop"] is True and h["apps"] == ["Firefox"] and h["number"] == 1


def test_la_regle_wireplumber(tmp_path):
    rule = tmp_path / "wp" / "90-golem-card.conf"
    assert G.write_rule("iTwo", str(rule)) is True
    text = rule.read_text()
    assert 'alsa.id = "iTwo"' in text and "device.disabled = true" in text
    assert G.write_rule("iTwo", str(rule)) is False                 # déjà là : rien ne change
    assert G.write_rule('x" } ] evil', str(rule)) is False          # un id étrange n'entre jamais dans la règle


def test_release_passe_le_profil_a_off(monkeypatch):
    calls = []
    monkeypatch.setattr(G.subprocess, "run", lambda argv, **k: calls.append(argv) or type("R", (), {"returncode": 0})())
    assert G.release("iTwo", DUMP) is True and calls == [["wpctl", "set-profile", "78", "0"]]
    assert G.release("V276", DUMP) is False                          # PipeWire ne la voit pas : rien à faire


def test_coupable(monkeypatch):
    monkeypatch.setattr(G.sys, "platform", "linux")
    monkeypatch.setenv("GOLEM_CARD_GUARD", "0")
    assert G.held("iTwo") is None and G.guard("iTwo", force=True) is None


@pytest.fixture
def rig(monkeypatch):
    sent = []
    monkeypatch.setattr(commands, "write_command", lambda cmd: sent.append(cmd))
    monkeypatch.setattr(state, "perf", {})
    monkeypatch.setitem(monitors._AUDIO_FIX, "tried", False)
    guarded = []
    monkeypatch.setattr(G, "guard", lambda cid=None, force=False: guarded.append(force))
    return sent, guarded


def test_health_dit_qui_tient_la_carte_et_la_reprend_une_fois(rig, monkeypatch):
    sent, guarded = rig
    h = {"card": "iTwo", "number": 1, "holders": [{"pid": 3, "name": "pipewire"}], "apps": ["Firefox"], "desktop": True}
    a = monitors._held_state(h)
    assert a["ok"] is False and a["held"] is True
    assert a["why"] == "iTwo is in use by Firefox through the desktop sound — the engine could not open it"
    assert guarded == [True] and sent == [{"action": "audio_reset"}]
    a = monitors._held_state(h)                                      # une seule tentative par épisode
    assert guarded == [True] and a["fix"] == "free the card, then restart the engine"
    monkeypatch.setattr(state, "audio", a)
    assert fixes.suggest({"id": "audio", "level": "bad"})["action"] == "free_card"


def test_un_autre_programme_en_alsa_direct_on_le_nomme(rig, monkeypatch):
    sent, guarded = rig
    a = monitors._held_state({"card": "iTwo", "number": 1, "holders": [{"pid": 9, "name": "audacity"}], "apps": [],
                              "desktop": False})
    assert "in use by audacity —" in a["why"] and a["fix"] == "close audacity, then restart the engine"
    assert sent == [] and guarded == []
    monkeypatch.setattr(state, "audio", a)
    assert fixes.suggest({"id": "audio", "level": "bad"}) is None    # rien que golem puisse fermer à sa place
