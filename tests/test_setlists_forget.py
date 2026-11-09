# SPDX-License-Identifier: GPL-3.0-or-later
"""Un preset supprimé quitte les setlists : son emplacement devient libre, les banks suivantes ne
bougent pas (2026-09-08). Un preset simplement absent (pas encore synchronisé) n'est PAS touché."""
import json
import os

from bridge import setlists, store


def test_forget_libere_sans_decaler(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path))
    json.dump({"id": "fcb-banks", "name": "Repertoire", "presets": ["a", "b", "c", "b"]}, open(tmp_path / "fcb-banks.json", "w"))
    assert setlists.forget_preset("b") == 2
    d = json.load(open(tmp_path / "fcb-banks.json"))
    assert d["presets"] == ["a", "", "c", ""]                       # liste DÉRIVÉE : "" = libre
    assert [ln.get("preset") for ln in d["lines"]] == ["a", None, "c", None]
    assert setlists.forget_preset("zz") == 0


def test_load_preset_none_est_un_emplacement_libre():
    assert store.load_preset(None) is None
    assert store.load_preset("") is None


# ── store.delete_preset (audit des tests du 2026-11-09 : la suppression d'un preset n'avait aucun test) ────────────
def _rack(tmp_path, monkeypatch):
    from bridge import config as C, golemfm
    pre, sl = tmp_path / "presets", tmp_path / "setlists"
    pre.mkdir(); sl.mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(pre))
    monkeypatch.setattr(C, "SETLISTS_DIR", str(sl))
    pushed = []
    monkeypatch.setattr(golemfm, "push_song_links", lambda: pushed.append(1))    # rien ne part vers golem.fm
    for pid in ("a", "b"):
        json.dump({"id": pid, "name": pid.upper()}, open(pre / f"{pid}.json", "w"))
    json.dump({"id": "fcb-banks", "name": "Repertoire", "presets": ["a", "b", "a"]}, open(sl / "fcb-banks.json", "w"))
    return pre, sl, pushed


def test_supprimer_un_preset_libere_ses_banks_sans_decaler_les_autres(tmp_path, monkeypatch):
    from bridge.state import state
    pre, sl, pushed = _rack(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "preset_id", "b", raising=False)
    assert store.delete_preset("a") == {"deleted": True, "banks_freed": 2}
    assert not (pre / "a.json").exists() and (pre / "b.json").exists()
    assert json.load(open(sl / "fcb-banks.json"))["presets"] == ["", "b", ""]
    assert state.preset_id == "b"                                                 # le preset joué n'est pas touché


def test_supprimer_le_preset_joue_l_oublie_pour_le_prochain_demarrage(tmp_path, monkeypatch):
    """Sinon boot_recall échouait en silence au démarrage suivant (audit 2026-09-13, m5)."""
    from bridge.state import state
    pre, _sl, _ = _rack(tmp_path, monkeypatch)
    (pre / ".live.json").write_text('{"preset": "b"}')
    monkeypatch.setattr(state, "preset_id", "b", raising=False)
    monkeypatch.setattr(state, "preset_name", "B", raising=False)
    store.delete_preset("b")
    assert state.preset_id is None and state.preset_name is None and not (pre / ".live.json").exists()


def test_un_preset_absent_n_est_pas_une_erreur_et_un_chemin_ne_sort_pas_du_dossier(tmp_path, monkeypatch):
    pre, _sl, _ = _rack(tmp_path, monkeypatch)
    victim = tmp_path / "victim.json"
    victim.write_text("{}")
    assert store.delete_preset("zz") == {"deleted": False, "banks_freed": 0}
    assert store.delete_preset("../victim")["deleted"] is False                  # _safe_id : jamais hors de presets/
    assert victim.exists() and (pre / "a.json").exists()
