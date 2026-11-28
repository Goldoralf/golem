# SPDX-License-Identifier: GPL-3.0-or-later
"""L'accordeur coupe tout (2026-11-28, le mainteneur : « comme en concert, on ne veut pas entendre le musicien s'accorder »).
Il passe par le mixer de sorties : tant qu'il est armé, chaque source part « mute » vers le moteur, sans toucher
config/mixer.json ; désarmé, les niveaux enregistrés reviennent. Aucun moteur, aucun fichier de la machine."""
import pytest

from bridge import mixer
from bridge.state import state


@pytest.fixture
def sent(monkeypatch, tmp_path):
    monkeypatch.setattr(mixer, "MIXER_FILE", str(tmp_path / "mixer.json"))
    monkeypatch.setitem(mixer._cache, "mtime", None)
    monkeypatch.setattr(state, "tuner", {"on": False})
    out = []
    monkeypatch.setattr(mixer.commands, "write_command", lambda cmd: out.append(cmd))
    return out


def test_armé_tout_part_coupé_sans_toucher_les_niveaux_enregistrés(sent, tmp_path):
    mixer.set_levels({"click": {"db": -6}, "in1": {"mute": True}})
    state.tuner = {"on": True}
    lv = mixer.applied_levels()
    assert all(v["mute"] is True for v in lv.values())
    assert {"in1", "in2", "in101", "click", "backing", "drums", "looper", "sample", "std-keys"} <= set(lv)
    assert lv["click"]["db"] == -6                                    # le niveau voyage, seul le mute change
    assert mixer.levels()["click"] == {"db": -6.0} and "mute" not in mixer.levels()["click"]


def test_désarmé_le_mute_est_explicite_partout(sent):
    """golem_rig ne touche pas une source sans « mute » : une source jamais réglée resterait coupée."""
    mixer.set_levels({"in1": {"mute": True}})
    lv = sent[-1]["levels"]
    assert sent[-1]["action"] == "mixer_apply"
    assert lv["in1"]["mute"] is True and lv["in2"]["mute"] is False and lv["click"]["mute"] is False


def test_l_accordeur_coupe_avant_d_armer_et_rend_le_son_apres(monkeypatch, sent):
    from bridge import app as A
    from bridge import store
    monkeypatch.setattr(store, "tuner_source", lambda preset: (1, "guitar", None))
    monkeypatch.setattr(A, "write_command", lambda cmd: sent.append(cmd))
    monkeypatch.setattr(A, "_tuner_in_sent", {"n": 1})
    monkeypatch.setattr(state, "preset_id", None)
    A._do_tuner(True)
    assert [c["action"] for c in sent] == ["mixer_apply", "tuner"]
    assert all(v["mute"] for v in sent[0]["levels"].values())
    sent.clear()
    A._do_tuner(False)
    assert [c["action"] for c in sent] == ["tuner", "mixer_apply"]
    assert not any(v["mute"] for v in sent[1]["levels"].values())
