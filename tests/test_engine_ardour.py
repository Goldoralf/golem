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

_REAL_PLATFORM = sys.platform        # lu à l'import, avant tout monkeypatch


@pytest.fixture
def surface():
    s = FakeSurface()
    yield s
    s.close()


@pytest.fixture
def eng(surface, monkeypatch, tmp_path):
    # jamais le fichier du RACK : quand il tourne sur le Golem Engine, son presets/.looper.json donnait une plage à un
    # potard que ce test croit inconnu (2026-11-17)
    monkeypatch.setattr(A.C, "LOOPER_FILE", str(tmp_path / "no-looper.json"))
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
                       ("/transport_stop",), ("/locate", 0, 0)]


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
    # un process dont le nom est sûr : `sleep` peut être un binaire multi-appel (coreutils) dont /proc/…/cmdline ne
    # commence pas par « sleep » — le test échouait en CI (2026-11-17)
    import sys
    # LE VRAI SYSTÈME pour ce test (2026-11-22) : `slot` pose sys.platform = « linux » pour la file de commandes, et
    # c'est le MÊME module sys partout — sous Windows, _proc_names prenait alors la voie `ps` au lieu de `tasklist` et
    # ne rendait jamais rien (« ([], []) » au diagnostic). Un défaut du test, pas du moteur.
    monkeypatch.setattr(sys, "platform", _REAL_PLATFORM)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (slot / ".engine.pid").write_text(str(p.pid))
        e = A.ArdourEngine(link=object())
        assert e.pid() is None                       # un process qui n'est pas luasession : pas le moteur
        # le nom que CE système donne à ce process, pas basename(sys.executable) : Windows rend l'image sans « .exe »
        # (tasklist), macOS le binaire du framework (« Python », pas « python3.12 ») — rouge sur les deux (2026-11-22)
        # … lu quand il ne bouge plus : un process tout juste lancé n'a pas encore son nom définitif (le python du
        # framework macOS se ré-exécute en « Python »), et le premier `tasklist` d'un runner Windows peut dépasser
        # son délai et ne rien rendre — la première lecture seule laissait le test rouge sur les deux
        import time
        names, same = [], 0
        for _ in range(50):
            now = A._proc_names(p.pid)[:1]
            same = same + 1 if now and now == names else 0
            names = now
            if same >= 2:
                break
            time.sleep(0.2)
        monkeypatch.setattr(A.ArdourEngine, "PROC_NAMES", tuple(names))
        assert e.pid() == p.pid and e.running(), (names, A._proc_names(p.pid))
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


def test_le_looper_est_pilote_a_l_adresse_que_le_veilleur_publie(eng, surface, tmp_path, monkeypatch):
    """bridge/looper.py écrit ses commandes en normalisé, par décalage depuis « GoleM Cmd » : l'adaptateur connaît les
    plages du looper (celles des sliders de golem_super8) là où presets/.looper.json dit qu'il est."""
    f = tmp_path / ".looper.json"
    f.write_text(json.dumps({"present": True, "track": 19, "fx": 0, "cmd_param": 0}))
    monkeypatch.setattr(A.C, "LOOPER_FILE", str(f))
    eng.set_fx_param(19, 0, 0, (5 * 128 + 36) / 16383.0)       # la commande : seq 5, note 36 — exacte à l'arrivée
    eng.set_fx_param(19, 0, 1, 120 / 400.0)                    # le tempo
    eng.set_fx_param(19, 0, 3, 0.5)                            # « GoleM Loop 1 dB » : -30
    got = surface.wait(3)
    assert got[0] == ("/strip/plugin/parameter", 19, 1, 1, pytest.approx(676.0, abs=1e-3))
    assert got[1] == ("/strip/plugin/parameter", 19, 1, 2, pytest.approx(120.0))
    assert got[2] == ("/strip/plugin/parameter", 19, 1, 4, pytest.approx(-30.0))
    assert eng.set_fx_param(19, 0, 8, 0.5) is False            # au-delà de ses paramètres : inconnu
    assert eng.set_fx_param(18, 0, 0, 0.5) is False            # une autre piste : inconnue
