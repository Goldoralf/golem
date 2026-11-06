# SPDX-License-Identifier: GPL-3.0-or-later
"""La position des pédales EXP suit d'un preset à l'autre (2026-11-06) : écrite dans la copie émise avant la compilation,
volume à 100 % tant que rien n'est reçu, rôle bloc seulement une fois la pédale bougée."""
import copy

import pytest

from bridge import app as A
from bridge.state import state


def _preset():
    return {"id": "p", "lanes": [{"id": "guitar-1", "chain": {"pre": [
        {"id": "wah-1", "type": "wah", "params": {"wah": 0.5}},
        {"id": "vol-1", "type": "volume", "params": {"gain": 0}}]}}],
        "scenes": [{"id": "A", "params": {"vol-1": {"gain": -12}, "wah-1": {"wah": 0.8}}}, {"id": "B"}]}


def _p(work, bid, pid):
    return next(b for L in work["lanes"] for b in L["chain"]["pre"] if b["id"] == bid)["params"][pid]


@pytest.fixture(autouse=True)
def pedals(monkeypatch):
    monkeypatch.setattr(state, "pedals", {"volume": "exp1", "block": "exp2"})
    monkeypatch.setattr(state, "exp1", 127)
    monkeypatch.setattr(state, "exp2", 0)
    monkeypatch.setattr(state, "exp_known", {"exp1": False, "exp2": False})


def test_rien_recu_le_volume_a_100_et_le_bloc_garde_son_reglage():
    w = _preset()
    A._exp_bake(w)
    assert _p(w, "vol-1", "gain") == 0.0                    # 100 % = 0 dB, le gain unité
    assert _p(w, "wah-1", "wah") == 0.5                      # pédale jamais bougée : le réglage du preset reste
    assert "gain" not in w["scenes"][0]["params"]["vol-1"]   # la scène ne reprend pas la main sur la pédale
    assert w["scenes"][0]["params"]["wah-1"] == {"wah": 0.8}


def test_une_position_connue_est_ecrite_sur_les_deux_cibles(monkeypatch):
    monkeypatch.setattr(state, "exp1", 0)
    monkeypatch.setattr(state, "exp2", 127)
    monkeypatch.setattr(state, "exp_known", {"exp1": True, "exp2": True})
    w = _preset()
    A._exp_bake(w)
    assert _p(w, "vol-1", "gain") == -60.0                   # talon = -60 dB
    assert _p(w, "wah-1", "wah") == 1.0
    assert "wah" not in w["scenes"][0]["params"]["wah-1"]


def test_les_roles_permutes_suivent_la_bonne_pedale(monkeypatch):
    monkeypatch.setattr(state, "pedals", {"volume": "exp2", "block": "exp1"})
    monkeypatch.setattr(state, "exp1", 64)
    monkeypatch.setattr(state, "exp2", 127)
    monkeypatch.setattr(state, "exp_known", {"exp1": True, "exp2": False})
    w = _preset()
    A._exp_bake(w)
    assert _p(w, "vol-1", "gain") == 0.0                     # le volume lit EXP 2
    assert _p(w, "wah-1", "wah") == pytest.approx(64 / 127, abs=1e-4)


def test_un_mouvement_rend_la_position_connue(monkeypatch):
    monkeypatch.setattr(A, "_apply_exp", lambda a, v: True)
    A._on_pedal("exp2", 90)
    assert state.exp_known["exp2"] is True and state.exp2 == 90


def test_le_preset_recu_n_est_jamais_touche():
    p = _preset()
    before = copy.deepcopy(p)
    A._exp_bake(copy.deepcopy(p))
    assert p == before


def test_l_emission_ecrit_la_position_avant_de_compiler(monkeypatch):
    from bridge import recall, scene_bake, compile_rig, store
    seen = {}

    def bake(work, scene, union=True, veto=None):
        seen["gain"] = _p(work, "vol-1", "gain")
        raise RuntimeError("stop")                           # on n'a besoin que de voir la copie compilée
    monkeypatch.setattr(scene_bake, "to_paths_preset", bake)
    monkeypatch.setattr(compile_rig, "compile_preset", lambda b: None)
    monkeypatch.setattr(store, "ensure_volume", lambda w: w)
    monkeypatch.setattr(recall, "_exp_bake", A._exp_bake)
    monkeypatch.setattr(state, "exp1", 0)
    monkeypatch.setattr(state, "exp_known", {"exp1": True, "exp2": False})
    recall.emit_sandbox_preset(_preset(), "A")
    assert seen["gain"] == -60.0


def test_une_demo_sonne_au_reglage_du_preset_pas_a_la_pedale(monkeypatch):
    from bridge import preview
    monkeypatch.setattr(state, "exp1", 0)
    monkeypatch.setattr(state, "exp_known", {"exp1": True, "exp2": False})
    w = _preset()
    assert preview._gen_lock.acquire(blocking=False)
    try:
        A._exp_bake(w)
    finally:
        preview._gen_lock.release()
    assert _p(w, "vol-1", "gain") == 0                       # le réglage du preset, pas le talon de la pédale
