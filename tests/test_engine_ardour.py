# SPDX-License-Identifier: GPL-3.0-or-later
"""L'adaptateur du Golem Engine (docs/ardour-plan.md §2, lot A1.4) contre un faux Ardour (tests/fakeardour.py) :
les adresses OSC de la surface d'Ardour, la conversion normalisé -> brut, la traduction du retour dans le
vocabulaire du bridge, le slot de commandes et le PID du process."""
import json
import os
import subprocess
import sys

import pytest

from bridge import commands
from bridge import config as C
from bridge.engine import ardour as A
from bridge.reaper_osc import ReaperLink

sys.path.insert(0, os.path.dirname(__file__))
from fakeardour import FakeSurface, FakeWatcher, free_udp_port  # noqa: E402


@pytest.fixture
def surface():
    s = FakeSurface()
    yield s
    s.close()


@pytest.fixture
def eng(surface):
    e = A.ArdourEngine()
    e.recv_port = free_udp_port()
    e._link = ReaperLink("127.0.0.1", surface.port, e.recv_port, e._dispatch)
    yield e
    e.stop_feedback()


def test_le_retour_est_demande_au_port_du_bridge(eng, surface):
    eng.start_feedback(lambda a, args: None)
    got = surface.wait(3)
    assert ("/set_surface/port", C.BRIDGE_OSC_RECV_PORT) in got
    assert ("/set_surface/feedback", A.FEEDBACK) in got and ("/set_surface/strip_types", A.STRIP_TYPES) in got


def test_mute_volume_transport_refresh_aux_adresses_d_ardour(eng, surface):
    eng.set_track_mute(2, True)
    eng.set_track_volume(1, 0.8)
    eng.transport("play")
    eng.transport("pause")
    eng.transport("start")
    got = surface.wait(5)
    assert got[:5] == [("/strip/mute", 2, 1), ("/strip/fader", 1, pytest.approx(0.8)), ("/transport_play",),
                       ("/transport_stop",), ("/goto_start",)]


def test_un_potard_sans_plage_connue_est_refuse(eng, surface):
    assert eng.set_fx_param(1, 0, 0, 0.5) is False
    assert surface.wait(1, timeout=0.3) == []


def test_un_potard_est_converti_en_valeur_brute(eng, surface):
    eng.load_ranges([{"track": 1, "fx": 0, "param": 0, "lower": -20, "upper": 20},
                     {"track": 1, "fx": 1, "param": 2, "lower": 20, "upper": 20000, "log": True}])
    eng.set_fx_param(1, 0, 0, 0.75)                   # linéaire : -20 + 0,75 × 40 = 10
    eng.set_fx_param(1, 1, 2, 0.5)                    # logarithmique : 20 × 1000^0,5 ≈ 632
    got = surface.wait(2)
    assert got[0] == ("/strip/plugin/parameter", 1, 1, 1, pytest.approx(10.0))
    assert got[1][:4] == ("/strip/plugin/parameter", 1, 2, 3) and got[1][4] == pytest.approx(632.46, rel=1e-3)


def test_le_retour_d_ardour_est_traduit_pour_le_bridge(eng, surface):
    seen = []
    eng.start_feedback(lambda a, args: seen.append((a, tuple(args))))
    surface.wait(3)
    surface.feedback(eng.recv_port, "/strip/meter", 1, -6.0)
    surface.feedback(eng.recv_port, "/strip/meter", 2, -193.0)
    surface.feedback(eng.recv_port, "/strip/mute", 3, 1.0)
    surface.feedback(eng.recv_port, "/transport_play", 1.0)
    import time
    end = time.time() + 2
    while len(seen) < 4 and time.time() < end:
        time.sleep(0.02)
    assert seen[0][0] == "/track/1/vu" and seen[0][1][0] == pytest.approx(0.501, abs=1e-3)
    assert seen[1] == ("/track/2/vu", (0.0,))
    assert seen[2] == ("/track/3/mute", (1.0,))
    assert seen[3][0] == "/transport_play"                  # le reste passe tel quel


@pytest.fixture
def slot(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "COMMAND_FILE", str(tmp_path / ".command.json"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(commands, "ACK_FILE", str(tmp_path / ".command-ack.json"))
    monkeypatch.setattr(commands.sys, "platform", "linux")
    monkeypatch.setattr(commands, "_reaper_up", lambda: True)
    monkeypatch.setattr(commands, "_queue", [])
    monkeypatch.setattr(commands, "_drainer", None)
    return tmp_path


def test_les_commandes_passent_par_le_slot_et_sont_accusees(slot):
    (slot / ".command.json").write_text(json.dumps({"action": "status", "seq": 1}))
    w = FakeWatcher(str(slot / ".command.json"), str(slot / ".command-ack.json"))
    try:
        e = A.ArdourEngine(link=object())
        assert e.send({"action": "looper", "op": "rec"}) is None           # pas encore dans son vocabulaire
        s1 = e.send({"action": "ping"})
        ran = w.wait_ran(1)
        s2 = e.send({"action": "status"})
        ran = w.wait_ran(2)
        assert commands.flush(2)
    finally:
        w.stop()
    assert [c["action"] for c in ran] == ["ping", "status"]                 # la commande d'avant n'a pas joué
    assert [c["seq"] for c in ran] == [s1, s2]
    assert json.loads((slot / ".command-ack.json").read_text())["seq"] == s2


def test_le_pid_est_celui_du_process_moteur(slot, monkeypatch):
    p = subprocess.Popen(["sleep", "30"])
    try:
        (slot / ".engine.pid").write_text(str(p.pid))
        e = A.ArdourEngine(link=object())
        assert e.pid() is None                       # un process qui n'est pas luasession : pas le moteur
        monkeypatch.setattr(A.ArdourEngine, "PROC_NAMES", ("sleep",))
        assert e.pid() == p.pid and e.running()
        assert e.stop(timeout=3) and e.pid() is None
    finally:
        p.kill()
        p.wait()
    (slot / ".engine.pid").write_text("999999999")
    assert A.ArdourEngine(link=object()).pid() is None


def test_relancer_sans_moteur_installe_est_une_erreur(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ENGINE_DIR", str(tmp_path / "absent"))
    with pytest.raises(RuntimeError):
        A.ArdourEngine(link=object()).restart()


def test_golem_engine_force_le_moteur_en_dev(monkeypatch):
    from bridge import engine
    monkeypatch.setattr(engine, "_active", None)
    monkeypatch.setenv("GOLEM_ENGINE", "ardour")
    assert engine.get().id == "ardour"
    monkeypatch.setattr(engine, "_active", None)
