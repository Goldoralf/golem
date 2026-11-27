# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/doc-impact.py et les sections de la coquille (docs/release-tool-plan.md §3 bis, étape 3) : la relecture de la
doc se fait par section du menu, et le bruit (disque, CPU) n'en demande pas."""
import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shell_snapshot as S     # noqa: E402

_spec = importlib.util.spec_from_file_location("doc_impact", os.path.join(ROOT, "tools", "doc-impact.py"))
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


@pytest.mark.parametrize("route,section", [
    ("#/live", "live"), ("#/designer/keys-1", "designer"), ("#/songs/setlists/factory/r:factory:12", "songs"),
    ("#/library/tracks/recordings", "library/tracks"), ("#/system/gear/drums", "settings/gear"), ("#/system/mode", "settings/mode"),
    ("/app/m.html?tab=live&mode=now", "companion"), ("?boot=firstcheck&at=input", "first-check"),
    ("/app/?boot=firstcheck#/live", "first-check")])
def test_chaque_route_a_sa_section(route, section):
    assert S.section_of(route) == section


def test_chaque_page_et_chaque_exemple_est_range():
    cu = S._check_ui()
    secs = S.sections_of(cu.RACK_PAGES + cu.PHONE_PAGES, S.EXAMPLES)
    assert sum(len(v["examples"]) for v in secs.values()) == len(S.EXAMPLES)
    assert {"live", "designer", "songs", "companion", "first-check", "settings/gear", "library/tracks"} <= set(secs)
    assert all(k == "live" or "/" in k or k in ("designer", "songs", "companion", "first-check") for k in secs), sorted(secs)


def test_le_bruit_ne_demande_pas_de_relecture():
    assert D.to_review({"reads": ["/api/storage", "/api/system"]}) is False
    assert D.to_review({"reads": ["/api/storage"], "pixels": 0.1}) is True              # un pixel a bougé : on regarde
    assert D.to_review({"reads": ["/api/controllers", "/api/devices"]}) is True         # le matériel déclaré est du contenu
    assert D.to_review({"reads": ["/api/sandbox"]}) is True and D.to_review({"anchors_gone": ["x"]}) is True
    assert D.to_review({"reads": ["POST /api/blocks/status"]}) is True


def test_le_rapport_range_par_section():
    rep = {"added": ["new-one"], "removed": [], "old_routes": {},
           "changed": {"golem-rising-live": {"pixels": 0.2}, "factory-storage": {"reads": ["/api/storage"]},
                       "factory-health": {"anchors_gone": ["health.guard"]}}}
    ex = {"golem-rising-live": {"route": "#/live"}, "factory-storage": {"route": "#/system/content/storage"},
          "factory-health": {"route": "#/system/sys/health"}, "new-one": {"route": "#/songs"},
          "library-amps": {"route": "#/library/tones/amps"}}
    secs = D.by_section(rep, ex)
    assert secs["live"]["status"] == "changed" and secs["live"]["review"] == ["golem-rising-live"]
    assert secs["settings/content"]["status"] == "noise only" and secs["settings/content"]["noise"] == ["factory-storage"]
    assert secs["settings/sys"]["gone"] == ["health.guard"] and secs["songs"]["added"] == ["new-one"]
    assert secs["library/tones"]["status"] == "unchanged"                                # une section sans changement se dit


def _snap(d, commit, examples, failed=(), partial=None):
    (d / "examples").mkdir(parents=True)
    for n in examples:
        (d / "examples" / (n + ".json")).write_text(json.dumps({"name": n, "v": commit + str(d)}))
    man = {"kind": "factory", "commit": commit, "examples": list(examples), "anchors": {"examples": {n: ["a:" + n] for n in examples}},
           "examples_failed": [{"name": n, "route": "#/live", "why": "boom"} for n in failed]}
    if partial:
        man["partial"] = partial
    (d / "SNAPSHOT.json").write_text(json.dumps(man))
    return d


def test_une_section_refaite_s_integre_a_la_coquille_du_meme_commit(tmp_path):
    full = _snap(tmp_path / "full", "c1", ["golem-rising-live", "companion-now"], failed=["companion-rec"])
    part = _snap(tmp_path / "part", "c1", ["companion-rec", "companion-now"], partial={"sections": ["companion"]})
    done = S.merge_into(str(part), str(full), log=lambda *_: None)
    man = json.loads((full / "SNAPSHOT.json").read_text())
    assert done == ["companion-rec", "companion-now"] and man["examples_failed"] == []          # l'échec réparé s'en va
    assert man["examples"] == ["golem-rising-live", "companion-now", "companion-rec"]           # l'ordre d'EXAMPLES
    assert "part" in json.loads((full / "examples" / "companion-now.json").read_text())["v"]    # remplacé par le neuf
    assert man["anchors"]["examples"]["companion-rec"] == ["a:companion-rec"]


def test_deux_commits_ne_se_melangent_pas(tmp_path):
    full = _snap(tmp_path / "full", "c1", ["golem-rising-live"])
    part = _snap(tmp_path / "part", "c2", ["companion-now"], partial={"sections": ["companion"]})
    with pytest.raises(SystemExit, match="same commit"):
        S.merge_into(str(part), str(full), log=lambda *_: None)
    with pytest.raises(SystemExit, match="not a full factory snapshot"):
        S.merge_into(str(_snap(tmp_path / "p2", "c2", ["companion-now"])), str(part), log=lambda *_: None)


def test_une_page_n_est_citee_que_pour_un_exemple_a_relire(tmp_path):
    (tmp_path / "a.en.md").write_text('::golem{example="factory-storage"}\n::golem{example="golem-rising-live" halo="live.tile"}\n')
    (tmp_path / "b.en.md").write_text('::golem{example="factory-storage"}\n')
    rep = {"removed": [], "changed": {"factory-storage": {"reads": ["/api/storage"]}, "golem-rising-live": {"pixels": 0.2}}}
    assert D.pages_citing(str(tmp_path), rep) == {"a.en.md": ["example golem-rising-live"]}     # b ne cite que du bruit


def test_les_horodatages_ne_font_pas_un_changement():
    a = {"boot": {"done": 1.0, "now": 2.0}, "now": 5, "hb": 88079, "scene_id": "B",
         "idle": {"waiting_for": "in use (screen, 3 s ago)"}, "takes": [{"dir": "perf-1", "now": 1}]}
    b = {"boot": {"done": 9.0, "now": 9.5}, "now": 6, "hb": 86459, "scene_id": "B",
         "idle": {"waiting_for": "in use (screen, 1 s ago)"}, "takes": [{"dir": "perf-1", "now": 2}]}
    assert D.stable(a) == D.stable(b)
    assert D.stable(dict(a, scene_id="C")) != D.stable(b)                 # un vrai changement reste un changement
    assert D.stable({"x": "3 songs"}) == {"x": "3 songs"} and D.stable({"x": "2 min ago"}) == {"x": "N ago"}


def test_une_date_unix_et_le_disque_du_poste_sont_du_bruit():
    a = {"health": {"level": "warn", "at": 1795789803.992}, "updated": 1795789803, "disk": {"free": 5}, "bpm": 120, "rate": 1440000}
    b = {"health": {"level": "warn", "at": 1795787737.67}, "updated": 1795787740, "disk": {"free": 9}, "bpm": 120, "rate": 1440000}
    assert D.stable(a) == D.stable(b) and D.stable(a)["bpm"] == 120 and D.stable(a)["rate"] == 1440000     # un nombre ordinaire reste
    assert D.stable({"ok": True}) == {"ok": True}
