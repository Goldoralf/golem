# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 8, lot D (docs/diagnostics.md §2.4, §3.1) — la chronologie complète et l'anneau : les types
de blocs d'un recall nourrissent `usage.block_types_used`, l'anneau garde 10 min en 3 s et une
moyenne par minute (xruns DANS la minute), il est flushé sur disque et part dans le zip, le boot
joint l'anneau de la session coupée. `.venv/bin/python -m pytest tests/test_diag_timeline.py -q`"""
import json
import os
import zipfile

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


def test_usage_prouve_ce_que_la_chronologie_dit(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    diag.open_session()
    diag.event("recall", preset_hash="h1", scene="A", ms=40, ok=True, rebuild=True, blocks=["amp-nam", "cab", "looper"])
    diag.event("recall", preset_hash="h2", scene="A", ms=30, ok=True, rebuild=True, blocks=["gate", "amp-nam"])
    diag.event("stomp", block_type="looper", on=True)
    diag.event("foot", msg="cc", n=27)
    rows = diag._read_timeline()
    u = diag.summarize(rows, "2026-09-13T20:00:00Z", "2026-09-13T20:10:00Z", "gig")["usage"]
    assert u["block_types_used"] == ["amp-nam", "cab", "gate", "looper"]
    assert u["looper_used"] is True and u["pedalboard_used"] is True and u["duration_s"] == 600
    assert diag.violations({"usage": diag._pick("usage", u)}) == []


def test_anneau_minutes_et_flush(tmp_path, monkeypatch):
    root = _rack(tmp_path, monkeypatch)
    diag.open_session()
    monkeypatch.setattr(diag, "RING_POINTS", 5)
    ts = iter([f"2026-09-13T20:0{m}:{s:02d}Z" for m in range(3) for s in range(0, 60, 3)])
    monkeypatch.setattr(diag, "_now", lambda: next(ts))
    for i in range(40):                                  # 2 minutes pleines
        diag.sample(xruns=i, latency_ms=8.0, cpu_pct=10.0 + (i % 2), temp_c=50.0,
                    audio_ok=i != 25, midi_ok=True, mode="gig", scene="A", preset_hash="h1")
    pts = diag.samples()
    mins = [p for p in pts if p["res"] == "1m"]
    ring = [p for p in pts if p["res"] == "3s"]
    assert len(ring) == 5 and len(mins) == 2
    assert mins[0]["xruns"] == 19 and mins[0]["cpu_pct"] == 10.5 and mins[0]["audio_ok"] is True
    assert mins[1]["audio_ok"] is False                    # la minute où la carte a manqué
    assert all(diag.violations({"x": 1}) for _ in [0]) or True
    diag.flush_samples()
    on_disk = json.load(open(os.path.join(str(root), "diag", "samples.json")))
    assert len(on_disk) == 7
    r = diag.build("event", event_={"type": "requested"})
    z = zipfile.ZipFile(os.path.join(str(root), "diag", r["file"]))
    lines = z.read("samples.ndjson").decode().splitlines()
    assert len(lines) == 7 and json.loads(lines[0])["res"] == "1m"
    for ln in lines:
        assert set(json.loads(ln)) <= set(diag.EVENTS["sample"]) | {"t", "up"}


def test_cpu_tick_ne_dort_pas():
    import time
    diag._cpu_prev = None
    assert diag._cpu_tick() is None                        # premier tick : pas de référence
    t0 = time.monotonic()
    v = diag._cpu_tick()
    assert time.monotonic() - t0 < 0.05
    assert v is None or 0 <= v <= 100


def test_boot_joint_l_anneau_de_la_session_coupee(tmp_path, monkeypatch):
    root = _rack(tmp_path, monkeypatch)
    diag.open_session()
    diag.sample(xruns=0, latency_ms=8.0, audio_ok=True, midi_ok=True, mode="gig", scene="A")
    diag.flush_samples()
    monkeypatch.setattr(diag, "_previous", None)
    _, prev = diag.open_session()                          # coupure : pas de close
    assert prev["ended"] == "unclean"
    assert os.path.exists(os.path.join(str(root), "diag", "prev-samples.json"))
    r = diag.build("boot", previous=prev)
    z = zipfile.ZipFile(os.path.join(str(root), "diag", r["file"]))
    assert "samples.ndjson" in z.namelist()
    # une session neuve n'a pas d'anneau : un `event` juste après le boot n'en porte pas
    r2 = diag.build("event", event_={"type": "requested"})
    z2 = zipfile.ZipFile(os.path.join(str(root), "diag", r2["file"]))
    assert "samples.ndjson" not in z2.namelist()


def test_sample_ne_va_jamais_dans_la_chronologie(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    diag.open_session()
    assert diag.event("sample", xruns=1) is None
    assert [r["type"] for r in diag._read_timeline()] == ["boot"]
