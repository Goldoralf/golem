# SPDX-License-Identifier: GPL-3.0-or-later
"""La destination d'un push = le serveur ET le compte (2026-11-19, golem.fm de dev) : un rack ré-appairé sur un autre
compte du même serveur croyait tout déjà poussé — 0 pack, 0 blob, 0 bank chez le nouveau compte."""
from bridge import tones_sync as TS

BASE = "http://192.168.0.12:7300"


def _paired(monkeypatch, token):
    monkeypatch.setattr(TS, "_cfg", lambda: (BASE + "/", token))


def test_un_nouveau_jeton_est_une_nouvelle_destination(monkeypatch):
    _paired(monkeypatch, "gmt_compte1")
    state = {}
    TS._pushed_for(state)["t3k:246"] = "h1"
    _paired(monkeypatch, "gmt_compte2")
    assert TS._pushed_for(state) == {}, "le compte 2 n'a rien reçu : tout repart"
    _paired(monkeypatch, "gmt_compte1")
    assert TS._pushed_for(state) == {"t3k:246": "h1"}, "chaque destination garde le sien"


def test_la_cle_ne_porte_jamais_le_jeton(monkeypatch):
    _paired(monkeypatch, "gmt_secret_token")
    key = TS._dest_key()
    assert key.startswith(BASE + "#") and "secret" not in key
    _paired(monkeypatch, None)
    assert TS._dest_key() == BASE


def test_les_presets_publies_suivent_la_destination(monkeypatch, tmp_path):
    monkeypatch.setattr(TS, "_PUBLISHED", str(tmp_path / ".published.json"))
    _paired(monkeypatch, "gmt_compte1")
    TS._mark_published("factory-x", "fp1")
    assert TS._published_map() == {"factory-x": "fp1"}
    _paired(monkeypatch, "gmt_compte2")
    assert TS._published_map() == {}
