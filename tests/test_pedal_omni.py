# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce qu'une pédale MIDI écoute (Omni ou son canal), déclaré depuis System ▸ Gear ▸ Pedals (2026-11-24), et la
procédure d'une pédale installée qui suit le catalogue."""
import json

import pytest

from bridge import config as C
from bridge import routes_content


@pytest.fixture
def rack(tmp_path, monkeypatch):
    maps, cat = tmp_path / "mappings", tmp_path / "catalog"
    maps.mkdir()
    cat.mkdir()
    monkeypatch.setattr(C, "MAPPINGS_DIR", str(maps))
    monkeypatch.setattr(routes_content, "PEDALS_CATALOG", str(cat))
    return maps, cat


def _write(p, d):
    p.write_text(json.dumps(d), encoding="utf-8")


def test_omni_se_declare_et_s_efface(rack):
    maps, _ = rack
    _write(maps / "whammy-dt.json", {"id": "whammy-dt", "channel": 1, "modes": []})
    assert routes_content.pedals_omni("whammy-dt", {"omni": False})["omni"] is False
    assert json.loads((maps / "whammy-dt.json").read_text(encoding="utf-8"))["omni"] is False
    assert routes_content.pedals_omni("whammy-dt", {"omni": None})["omni"] is None
    assert "omni" not in json.loads((maps / "whammy-dt.json").read_text(encoding="utf-8"))


def test_omni_refuse_une_valeur_floue_ou_une_pedale_absente(rack):
    maps, _ = rack
    _write(maps / "whammy-dt.json", {"id": "whammy-dt", "modes": []})
    assert routes_content.pedals_omni("whammy-dt", {"omni": "yes"}).status_code == 400
    assert routes_content.pedals_omni("h9", {"omni": False}).status_code == 404


def test_la_procedure_suit_le_catalogue_les_reglages_restent_locaux(rack):
    maps, cat = rack
    new = {"phases": [{"name": "Wire it up", "steps": [{"title": "MIDI channel 1, not Omni", "action": "midi_channel"}]}]}
    _write(cat / "whammy-dt.json", {"id": "whammy-dt", "channel": 1, "install": new})
    _write(maps / "whammy-dt.json", {"id": "whammy-dt", "channel": 3, "omni": False, "installed_from": "catalog",
                                     "install": {"phases": [{"steps": [{"title": "MIDI channel"}]}]}})
    got = routes_content.get_mapping("whammy-dt")
    assert got["install"] == new
    assert got["channel"] == 3 and got["omni"] is False


def test_une_pedale_du_wizard_garde_sa_procedure(rack):
    maps, cat = rack
    _write(cat / "custom.json", {"id": "custom", "install": {"phases": []}})
    mine = {"phases": [{"steps": [{"title": "mine"}]}]}
    _write(maps / "custom.json", {"id": "custom", "install": mine})
    assert routes_content.get_mapping("custom")["install"] == mine
