# SPDX-License-Identifier: GPL-3.0-or-later
"""Le contrat moteur (docs/ardour-plan.md §2, étape A1) : le bridge parle à un EngineAdapter, REAPER en est un,
sans changement de comportement — les mêmes commandes, les mêmes numéros d'action, les mêmes adresses OSC."""
import logging

import pytest

from bridge import engine, engines
from bridge.engine.fake import FakeEngine
from bridge.engine.reaper import ReaperEngine


@pytest.fixture
def fake():
    eng = FakeEngine()
    prev = engine.use(eng)
    yield eng
    engine.use(prev)


class _Link:
    """Un faux ReaperLink : ce qui partirait en OSC."""
    def __init__(self):
        self.out = []

    def trigger_action(self, cid):
        self.out.append(("action", cid))
        return True

    def set_fx_param(self, *a):
        self.out.append(("fx", *a))
        return True

    def set_track_volume(self, *a):
        self.out.append(("vol", *a))
        return True

    def set_track_mute(self, *a):
        self.out.append(("mute", *a))
        return True


def test_le_moteur_par_defaut_est_reaper(monkeypatch):
    monkeypatch.setattr(engine, "_active", None)
    monkeypatch.setattr(engines, "current", lambda *a, **k: "reaper")
    assert isinstance(engine.get(), ReaperEngine)
    assert engine.get() is engine.get()                          # un seul adaptateur par process


def test_un_moteur_sans_adaptateur_retombe_sur_reaper(monkeypatch, caplog):
    monkeypatch.setattr(engine, "_active", None)
    monkeypatch.delenv("GOLEM_ENGINE", raising=False)              # le choix lu, pas celui que la suite force
    monkeypatch.setattr(engines, "current", lambda *a, **k: "nope")
    with caplog.at_level(logging.WARNING, logger="golem.engine"):
        assert engine.get().id == "reaper"
    assert "nope" in caplog.text


def test_write_command_passe_par_le_moteur_actif(fake):
    from bridge import commands
    seq = commands.write_command({"action": "stomp", "ids": ["drive"], "on": True})
    assert seq == 1 and fake.sent == [{"action": "stomp", "ids": ["drive"], "on": True, "seq": 1}]


def test_une_action_inconnue_du_moteur_rend_none_et_se_dit_une_fois(caplog):
    eng = FakeEngine(actions={"rig_recall", "scene_apply"})
    with caplog.at_level(logging.WARNING, logger="golem.engine"):
        assert eng.send({"action": "looper"}) is None
        assert eng.send({"action": "looper"}) is None
        assert eng.send({"action": "scene_apply", "scene": "B"}) == 1
    assert caplog.text.count("looper") == 1
    assert [c["action"] for c in eng.sent] == ["scene_apply"]


def test_reaper_pose_dans_la_file_de_toujours(monkeypatch):
    from bridge import commands
    got = []
    monkeypatch.setattr(commands, "enqueue", lambda c: (got.append(c), 42)[1])
    assert ReaperEngine(link=_Link()).send({"action": "rig_recall", "preset": "p"}) == 42
    assert got == [{"action": "rig_recall", "preset": "p"}]


def test_reaper_garde_ses_numeros_d_action_et_ses_adresses():
    link = _Link()
    eng = ReaperEngine(link=link)
    for op in ("play", "pause", "stop", "start"):
        eng.transport(op)
    eng.refresh()
    eng.set_fx_param(3, 0, 11, 0.5)
    eng.set_track_volume(1, 0.7)
    eng.set_track_mute(2, True)
    assert link.out == [("action", 1007), ("action", 1008), ("action", 1016), ("action", 40042),
                        ("action", 41743), ("fx", 3, 0, 11, 0.5), ("vol", 1, 0.7), ("mute", 2, True)]


def test_le_backing_joue_par_le_transport_du_moteur(fake, monkeypatch):
    from bridge import backing
    monkeypatch.setattr(backing, "write_command", lambda c: None)
    ctl = backing.BackingControl(osc=fake)
    ctl._osc.transport("play")
    src = open(backing.__file__, encoding="utf-8").read()
    assert "trigger_action" not in src                           # plus aucun numéro d'action REAPER dans le backing
    assert ("transport", "play") in fake.fast


def test_les_caps_du_battement_disent_le_moteur_actif(fake):
    from bridge import blockstatus
    c = blockstatus.caps()
    assert c["engine"] == "fake" and c["engine_version"] == "fake-1"


def test_les_capacites_viennent_du_descripteur():
    caps = ReaperEngine(link=_Link()).capabilities()
    assert caps.get("lanes") == "yes"
    feats = {f for f, _ in engines.features()}
    assert feats and feats <= set(caps)                          # une entrée par fonction, rien d'oublié


# ── A1.2 : le cycle de vie ───────────────────────────────────────────────────────────────────
def test_le_redemarrage_passe_par_le_moteur_actif(fake):
    import asyncio
    from bridge import routes_system
    assert asyncio.run(routes_system.reaper_restart()) == {"ok": True, "restarting": True}
    assert fake.fast == [("restart", "requested")]


def test_un_moteur_qui_ne_sait_pas_se_relancer_rend_409():
    import asyncio
    from bridge import routes_system
    from bridge.engine.base import EngineAdapter
    prev = engine.use(EngineAdapter())
    try:
        r = asyncio.run(routes_system.reaper_restart())
    finally:
        engine.use(prev)
    assert r.status_code == 409


def test_le_moniteur_lit_le_pid_du_moteur_actif(fake):
    from bridge import monitors
    assert monitors._engine_pid() == 4242 and monitors._engine_ready_since(0)
    fake.up = False
    assert monitors._engine_pid() is None and not fake.running()


def test_reaper_lit_son_pid_et_son_veilleur(monkeypatch):
    from bridge import monitors
    monkeypatch.setattr(monitors, "_reaper_pid", lambda: 77)
    monkeypatch.setattr(monitors, "_watch_started_since", lambda t0: t0 == 5)
    eng = ReaperEngine(link=_Link())
    assert eng.pid() == 77 and eng.running() and eng.ready_since(5) and not eng.ready_since(6)


# ── A1.3 : un bloc que le moteur ne sait pas jouer ──────────────────────────────────────────
class _Planned(FakeEngine):
    def descriptor(self):
        return {"name": "Golem Engine", "capabilities": {"looper": "planned", "kill_switch": "no", "lanes": "yes"}}


def test_un_bloc_hors_capacites_du_moteur_est_indisponible_raison_engine():
    from bridge import blockstatus
    prev = engine.use(_Planned())
    try:
        lp = blockstatus.block_state({"type": "looper"})
        ks = blockstatus.block_state({"type": "killswitch"})
    finally:
        engine.use(prev)
    assert lp == {"state": "unavailable", "reason": "engine", "engine_cap": "planned",
                  "why": "not available on Golem Engine yet"}
    assert ks["reason"] == "engine" and ks["why"] == "Golem Engine can't play this block"


def test_reaper_ne_bloque_aucun_type():
    from bridge import blockstatus
    prev = engine.use(ReaperEngine(link=_Link()))
    try:
        assert blockstatus.engine_gate() == {}
    finally:
        engine.use(prev)


def test_chaque_type_porte_par_une_fonction_existe_au_catalogue():
    import json
    from bridge import config as C
    import os
    cat = json.load(open(os.path.join(C.ROOT, "library", "catalog", "effects.json"), encoding="utf-8"))
    types = {e.get("type") for e in cat["effects"]}
    fob = engines.feature_of_block()
    feats = {f for f, _ in engines.features()}
    assert fob and set(fob) <= types and set(fob.values()) <= feats


def test_reaper_au_repos_repond_par_le_battement_de_golem_clock(monkeypatch, tmp_path):
    """Sans signal, REAPER n'émet aucun OSC : le battement de golem_clock dit qu'il répond ; sans battement, on ne sait
    pas (None : le trafic OSC décide, comme avant)."""
    import os
    import time
    from bridge import config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    eng = ReaperEngine(link=_Link())
    assert eng.talking() is None
    clock = tmp_path / ".clock.json"
    clock.write_text('{"ticks": 1}')
    assert eng.talking() is True
    old = time.time() - 30
    os.utime(clock, (old, old))
    assert eng.talking() is None
