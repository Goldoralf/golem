# SPDX-License-Identifier: GPL-3.0-or-later
"""Le mixer de /live et le bloc STANDARD (2026-10-20) : une tranche par partie qu'il JOUE — Piano et Bass par défaut,
Drums et Guitar quand le bloc les demande. Avant, le Standard n'avait aucune tranche (« il joue à travers les lanes »,
faux depuis qu'il a ses pistes). `.venv/bin/python -m pytest tests/test_mixer_standard.py -q`"""
from bridge import inputmap, mixer, store


def _summary(monkeypatch, params):
    pre = {"id": "p", "config": {"gen": {"blocks": [{"type": "standard", "id": "standard", "params": params}]}}}
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [], "outputs": []})
    monkeypatch.setattr(store, "load_preset", lambda pid: pre)
    monkeypatch.setattr(mixer.state, "preset_id", "p", raising=False)
    monkeypatch.setattr(mixer, "levels", lambda: {})
    return {s["id"]: s for s in mixer.summary()["sources"]}


def test_une_tranche_par_partie_jouee(monkeypatch):
    src = _summary(monkeypatch, {"standard": "x", "keys": True, "bass": True, "drums": True})
    assert [src[k]["label"] for k in ("std-keys", "std-bass", "std-drums")] == ["Piano", "Bass", "Drums"]
    assert "std-guitar" not in src
    assert all(src[k]["sub"] == "standard" and src[k]["present"] for k in ("std-keys", "std-bass", "std-drums"))


def test_les_parties_par_defaut_sont_celles_du_moteur(monkeypatch):
    src = _summary(monkeypatch, {"standard": "x", "keys": False, "guitar": True})
    assert "std-keys" not in src and "std-drums" not in src
    assert {"std-bass", "std-guitar"} <= set(src)


def test_sans_standard_aucune_tranche(monkeypatch):
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [], "outputs": []})
    monkeypatch.setattr(store, "load_preset", lambda pid: {"id": "p", "config": {}})
    monkeypatch.setattr(mixer.state, "preset_id", "p", raising=False)
    assert not [s for s in mixer.summary()["sources"] if s["id"].startswith("std-")]
