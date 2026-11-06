# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 8 (docs/diagnostics.md §6) — LA RÈGLE INVERSÉE : rien ne part sauf ce qui est listé.
Un champ inconnu posé dans une sonde n'apparaît pas ; une clé hors table est une violation ;
le vocabulaire de la chronologie est fermé. `.venv/bin/python -m pytest tests/test_diag_whitelist.py -q`"""
import json
import os

from bridge import config as C, diag


def _rack(tmp_path, monkeypatch):
    root = tmp_path
    (root / "config").mkdir()
    (root / "presets").mkdir()
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "CONFIG_DIR", str(root / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(root / "presets"))
    monkeypatch.setattr(diag, "_scrubber", None)
    return root


def test_pick_ne_garde_que_la_table():
    d = {"os": "ubuntu 24.04", "kernel": "7.0", "zzz_new": "fuite", "hostname": "rack-de-lea"}
    out = diag._pick("platform", d)
    assert out == {"os": "ubuntu 24.04", "kernel": "7.0"}


def test_pick_descend_dans_les_listes_et_sous_dicts():
    d = {"hash": "abc", "blocks": [{"type": "amp-nam", "name": "Set Léa", "ref": "t3k:1"}],
         "lanes": {"count": 2, "roles": ["guitar"], "names": ["Léa vox"]}}
    out = diag._pick("preset", d)
    assert out["blocks"] == [{"type": "amp-nam"}]
    assert out["lanes"] == {"count": 2, "roles": ["guitar"]}


def test_violations_voit_une_cle_hors_table():
    rep = {"platform": {"os": "x", "zzz": 1}, "preset": {"blocks": [{"type": "cab", "name": "n"}]},
           "inconnu": {"a": 1}}
    bad = diag.violations(rep)
    assert "platform.zzz" in bad and "preset.blocks[].name" in bad and "inconnu" in bad


def test_violations_accepte_previous_session_comme_usage():
    rep = {"previous_session": {"session_id": "s", "usage": {"duration_s": 3, "modes": [{"kind": "gig", "duration_s": 3}],
                                                          "takes": {"count": 0, "kinds": {"gig": 0}}},
                                "anomalies": [{"chip": "NO AUDIO", "total_s": 4}]}}
    assert diag.violations(rep) == []
    rep["previous_session"]["usage"]["zzz"] = 1
    assert diag.violations(rep) == ["previous_session.usage.zzz"]


def test_le_rapport_construit_passe_la_table(tmp_path, monkeypatch):
    """Sur ce poste, les sondes réelles tournent : le rapport doit sortir sans violation, et chaque
    section porte son `_doc` (le lecteur est une IA sans notre code)."""
    _rack(tmp_path, monkeypatch)
    diag.open_session()
    rep = diag.build_report("boot")
    assert diag.violations(rep) == []
    assert rep["report"]["schema"] == diag.SCHEMA
    for sec in ("platform", "golem", "health"):
        assert sec in rep and rep[sec]["_doc"]
    assert "hostname" not in json.dumps(rep)


def test_un_champ_hors_vocabulaire_est_retire_de_la_chronologie(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    row = diag.event("recall", preset_hash="abc123", ms=31, ok=True, preset_name="Set Léa")
    assert row["preset_hash"] == "abc123" and "preset_name" not in row
    assert diag.event("bidule", x=1) is None
    lines = open(os.path.join(str(tmp_path), "diag", "timeline.ndjson")).read().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["type"] == "recall"


def test_chaque_type_de_la_table_est_documente():
    """§2.4 : le vocabulaire du code et celui du contrat se lisent pareil."""
    doc = open(os.path.join(os.path.dirname(__file__), "..", "docs", "diagnostics.md"), encoding="utf-8").read()
    for t in diag.EVENTS:
        assert f"`{t}`" in doc, f"type `{t}` absent du contrat"
    for sec in diag.WHITELIST:
        base = sec.split(".")[0].rstrip("[]")
        assert f"`{base}`" in doc, f"section `{base}` absente du contrat"
