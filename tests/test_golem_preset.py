# SPDX-License-Identifier: GPL-3.0-or-later
"""Le preset dans le .golem (golem-format.md §9, 2026-10-08) : une copie rangée dans sheet.json, tenue à jour
en tâche de fond, gardée quand on retouche la fiche ; à l'arrivée, créé s'il manque, jamais d'écrasement."""
import json
import os

import pytest

from bridge import golemfile as G, preset_export as PE, songs as S

SID = "rs:" + "a1" * 16
PRESET = {"id": "paper-kite", "name": "Paper Kite", "bpm": 87, "lanes_v": 2, "lanes": [], "scenes": [{"id": "A"}]}


@pytest.fixture
def presets(tmp_path, monkeypatch):
    d = tmp_path / "presets"
    d.mkdir()
    monkeypatch.setattr(S.C, "PRESETS_DIR", str(d))
    # build_export résout les dépendances en hachant la bibliothèque : simulé (son rôle ici = rendre le doc)
    monkeypatch.setattr(PE, "build_export", lambda pid: (
        {"schema_version": 1, "catalog_version": 28, "deps": [{"sha256": "ab" * 32, "kind": "nam"}], "unresolved": [],
         "preset": json.load(open(d / f"{pid}.json"))}, {}) if (d / f"{pid}.json").exists() else (None, {}))
    return d


def _write_preset(d, doc, age_s=120):
    p = d / f"{doc['id']}.json"
    p.write_text(json.dumps(doc))
    t = os.path.getmtime(p) - age_s
    os.utime(p, (t, t))
    return p


def test_la_copie_est_rangee_puis_gardee_quand_on_retouche_la_fiche(presets):
    _write_preset(presets, PRESET)
    S.save({"id": SID, "rev": 1, "title": "Paper Kite", "kind": "cover", "sheet": {"preset": "paper-kite"}}, bump=False)
    assert S.preset_snapshot_stale(SID)
    assert S.snapshot_preset(SID) == "written"
    raw = json.loads(G.read_member(S._path(SID), "sheet.json"))
    assert raw["preset"] == "paper-kite" and raw[S.PRESET_KEY]["preset"]["bpm"] == 87
    assert raw[S.PRESET_KEY]["deps"][0]["kind"] == "nam"                        # désignée par sha256, pas embarquée
    assert S.load(SID)["sheet"] == {"preset": "paper-kite"}                    # la fiche lue reste la fiche
    assert not S.preset_snapshot_stale(SID)
    S.update(SID, capo=2)                                                       # retouche de FICHE
    raw = json.loads(G.read_member(S._path(SID), "sheet.json"))
    assert raw["capo"] == 2 and S.PRESET_KEY in raw                             # la copie n'est pas perdue


def test_un_preset_reenregistre_sans_changer_de_son_ne_reecrit_pas_le_golem(presets):
    _write_preset(presets, PRESET)
    S.save({"id": SID, "rev": 1, "title": "C", "kind": "cover", "sheet": {"preset": "paper-kite"}}, bump=False)
    S.snapshot_preset(SID)
    before = os.stat(S._path(SID)).st_mtime_ns
    _write_preset(presets, dict(PRESET, colors={"A": "#fff"}), age_s=90)        # couleur seulement : même son
    assert S.preset_snapshot_stale(SID)
    assert S.snapshot_preset(SID) == "unchanged"
    assert os.stat(S._path(SID)).st_mtime_ns == before and not S.preset_snapshot_stale(SID)
    _write_preset(presets, dict(PRESET, bpm=90), age_s=10)                      # trop récent : on attend
    assert not S.preset_snapshot_stale(SID)


def _arriving(tmp_path, preset):
    src = str(tmp_path / "in.golem")
    doc = {"id": preset["id"], "fingerprint": PE.fingerprint(preset), "preset": preset, "deps": [],
           "unresolved": [{"what": "asset", "type": "amp-nam", "ref": "t3k:246", "reason": "missing"}]}
    G.write(src, {"type": "song", "id": SID, "title": "Paper Kite", "kind": "cover"},
            {"sheet.json": json.dumps({"preset": preset["id"], S.PRESET_KEY: doc}).encode()})
    return src


def test_a_l_arrivee_le_preset_absent_est_cree(tmp_path, presets):
    r = S.install_golem(_arriving(tmp_path, PRESET))
    assert r["preset"]["action"] == "created" and r["preset"]["unresolved"][0]["ref"] == "t3k:246"
    assert json.load(open(presets / "paper-kite.json"))["bpm"] == 87


def test_a_l_arrivee_le_preset_local_n_est_jamais_ecrase(tmp_path, presets):
    _write_preset(presets, dict(PRESET, bpm=120))
    r = S.install_golem(_arriving(tmp_path, PRESET))
    assert r["preset"]["action"] == "kept_local"
    assert json.load(open(presets / "paper-kite.json"))["bpm"] == 120         # le sien, intact
    _write_preset(presets, PRESET)
    S.delete(SID)
    assert S.install_golem(_arriving(tmp_path, PRESET))["preset"]["action"] == "same"


def test_une_chanson_d_usine_ne_recoit_jamais_la_copie(presets, monkeypatch):
    # sinon le .golem d'usine change d'empreinte et factory.edited() le dit retouché : l'usine ne le met plus à jour
    _write_preset(presets, PRESET)
    S.save({"id": SID, "rev": 1, "title": "Golem Rising", "kind": "original", "sheet": {"preset": "paper-kite"}}, bump=False)
    monkeypatch.setattr(S, "is_factory", lambda sid: sid == SID)
    before = os.stat(S._path(SID)).st_mtime_ns
    assert not S.preset_snapshot_stale(SID)
    assert os.stat(S._path(SID)).st_mtime_ns == before
