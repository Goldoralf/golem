# SPDX-License-Identifier: GPL-3.0-or-later
"""« Pack à écho » (2026-09-14) : le verdict se LIT dans les fichiers, se garde par pack, ne relit pas
un pack inchangé, sort du verdict quand le pack part, et remonte dans /api/catalog et captures().
`.venv/bin/python -m pytest tests/test_ir_quality.py -q`"""
import json
import math
import os
import struct

from bridge import config as C, ir_quality, rigstatus


def _wav(path, echo_ms=None, sr=48000, ms=600):
    n = int(sr * ms / 1000); x = [0.0] * n
    for i in range(int(sr * 0.04)): x[i] = 0.9 * math.exp(-i / (sr * 0.006))
    if echo_ms is not None:
        j = int(sr * echo_ms / 1000)
        for i in range(int(sr * 0.02)): x[j + i] = 0.07 * math.exp(-i / (sr * 0.004))
    body = b"".join(struct.pack("<i", int(round(v * 8388608)))[:3] for v in x)
    open(path, "wb").write(b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 3, 3, 24) + b"data" + struct.pack("<I", len(body)) + body)


def _rack(tmp_path, monkeypatch):
    root = tmp_path; (root / "library" / "catalog").mkdir(parents=True); (root / "assets" / "irs").mkdir(parents=True)
    _wav(str(root / "assets" / "irs" / "bad1.wav"), echo_ms=480); _wav(str(root / "assets" / "irs" / "bad2.wav"), echo_ms=300)
    _wav(str(root / "assets" / "irs" / "ok.wav"))
    idx = {"tones": [{"id": 5004, "title": "Palmer", "gear": "cab", "models": [{"id": 1, "file": "assets/irs/bad1.wav"}, {"id": 2, "file": "assets/irs/bad2.wav"}]},
                     {"id": 45022, "title": "Marshall", "gear": "cab", "models": [{"id": 3, "file": "assets/irs/ok.wav"}]},
                     {"id": 246, "title": "Twin", "gear": "amp", "models": [{"id": 4, "file": "assets/irs/ok.wav"}]}]}
    json.dump(idx, open(root / "library" / "catalog" / "tones-index.json", "w"))
    monkeypatch.setattr(C, "ROOT", str(root)); monkeypatch.setattr(C, "CONFIG_DIR", str(root / "config"))
    monkeypatch.setattr(C, "CATALOG", str(root / "library" / "catalog" / "tones-index.json"))
    return root


def test_le_verdict_se_lit_et_se_garde(tmp_path, monkeypatch):
    root = _rack(tmp_path, monkeypatch)
    v = ir_quality.scan()
    assert v["5004"]["bad"] == 2 and v["5004"]["files"] == 2 and 290 <= v["5004"]["worst_ms"] <= 490
    assert v["45022"]["bad"] == 0 and "246" not in v                      # un ampli n'est pas jugé
    assert ir_quality.echo_of(5004)["bad"] == 2 and ir_quality.echo_of(45022) is None
    assert os.path.exists(root / "library" / "catalog" / ".ir-quality.json")
    # un pack inchangé n'est pas relu : la signature tient
    at = v["5004"]["at"]; v2 = ir_quality.scan(); assert v2["5004"]["at"] == at
    # le pack désinstallé sort du verdict
    idx = json.load(open(C.CATALOG)); idx["tones"] = [t for t in idx["tones"] if t["id"] != 5004]
    json.dump(idx, open(C.CATALOG, "w"))
    assert "5004" not in ir_quality.scan()


def test_captures_et_catalogue_portent_le_verdict(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch); ir_quality.scan()
    caps = {c["ref"]: c for c in rigstatus.captures()}
    assert caps["5004"].get("echo") is True and "echo" not in caps["45022"] and "echo" not in caps["246"]
    from bridge import routes_content
    monkeypatch.setattr(routes_content, "_model_weights", lambda: {})
    cat = {str(t["id"]): t for t in routes_content.get_catalog()["tones"]}
    assert cat["5004"]["echo"]["bad"] == 2 and "echo" not in cat["45022"]
