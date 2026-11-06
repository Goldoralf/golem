# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 8 (docs/diagnostics.md §3.2, §6) — la session SUR DISQUE : ouverte au boot, chronologie en
append, « coupure » (pas de close) → au boot suivant la précédente est clôturée `unclean`, son
bilan reconstruit et rendu pour le `boot`. Et la fenêtre d'xruns est une différence de points.
`.venv/bin/python -m pytest tests/test_diag_session.py -q`"""
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
    monkeypatch.setattr(diag, "collect_logs", lambda w, sc=None: ({}, []))
    return root


def test_session_propre(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    sess, prev = diag.open_session()
    assert prev is None and sess["session_id"] and sess["ended_at"] is None
    diag.event("mode", **{"from": "rehearsal", "to": "gig", "locked": True})
    diag.event("recall", preset_hash="a1", scene="B", ms=31, ok=True, rebuild=False)
    diag.event("recall", preset_hash="a2", scene="A", ms=120, ok=False, rebuild=True)
    diag.event("scene", to="C", ms=4)
    diag.event("chip", chip="NO AUDIO", on=True)
    diag.event("chip", chip="NO AUDIO", on=False)
    diag.event("take", state="stop", kind="gig", duration_s=180, tracks=4)
    closed = diag.close_session("sigterm")
    assert closed["ended"] == "clean"
    r = diag.build("session")
    u = r["report"]["usage"]
    assert u["ended"] == "clean" and u["recalls"] == {"count": 2, "ms_median": 76, "ms_max": 120, "failed": 1}
    assert u["scene_switches"] == 1 and u["presets_distinct"] == 2 and u["takes"]["kinds"] == {"gig": 1}
    kinds = [m["kind"] for m in u["modes"]]
    assert kinds[-1] == "gig" and all(m["duration_s"] >= 0 for m in u["modes"])   # le kind initial vient du rack
    assert r["report"]["anomalies"][0]["chip"] == "NO AUDIO" and r["report"]["anomalies"][0]["count"] == 1
    assert diag.violations(r["report"]) == []


def test_coupure_puis_reboot_raconte_la_session_precedente(tmp_path, monkeypatch):
    root = _rack(tmp_path, monkeypatch)
    s1, _ = diag.open_session()
    diag.event("chip", chip="NO AUDIO", on=True)          # la carte disparaît…
    diag.event("xrun", delta=47, window_s=90)
    # …et le rack est débranché : PAS de close_session. Boot suivant :
    s2, prev = diag.open_session()
    assert s2["session_id"] != s1["session_id"]
    assert prev["session_id"] == s1["session_id"] and prev["ended"] == "unclean"
    assert prev["anomalies"][0]["chip"] == "NO AUDIO" and prev["usage"]["events"]["xrun"] == 1
    assert os.path.exists(os.path.join(str(root), "diag", "prev-timeline.ndjson"))
    r = diag.build("boot", previous=prev)
    rep = r["report"]
    assert rep["previous_session"]["ended"] == "unclean"
    assert rep["previous_session"]["anomalies"][0]["chip"] == "NO AUDIO"
    assert diag.violations(rep) == []
    # la chronologie du paquet boot contient les événements de la session coupée
    import zipfile
    z = zipfile.ZipFile(os.path.join(str(root), "diag", r["file"]))
    tl = [json.loads(x) for x in z.read("timeline.ndjson").decode().splitlines() if x.strip()]
    assert any(t["type"] == "xrun" and t["delta"] == 47 for t in tl)
    assert any(t["type"] == "boot" for t in tl)


def test_fenetre_xruns_est_une_difference_de_points(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    diag.open_session()
    diag.event("xrun", delta=3, window_s=3)
    diag.event("xrun", delta=44, window_s=3)
    rows = [r for r in diag._read_timeline(since_s=90) if r["type"] == "xrun"]
    assert sum(r["delta"] for r in rows) == 47


def test_rotation_garde_les_non_envoyes(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    monkeypatch.setattr(diag, "KEEP_REPORTS", 2)
    diag.open_session()
    ids = []
    for i in range(4):
        r = diag.build("event", event_={"type": "requested"})
        ids.append(r["report_id"])
        if i < 2:
            diag.mark_sent(r["report_id"])        # les deux premiers sont partis
    idx = diag.index()
    # 4 fabriqués, 2 gardés par KEEP + les non-envoyés jamais purgés : les 2 derniers (non envoyés)
    # restent, le 2e (envoyé, hors quota) est purgé, le 1er aussi
    assert [r["report_id"] for r in idx] == ids[2:]
    assert all(diag.report_path(i) for i in ids[2:])
    assert diag.report_path(ids[0]) is None
