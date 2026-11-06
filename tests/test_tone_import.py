# SPDX-License-Identifier: GPL-3.0-or-later
"""Import files (docs/tone-import.md) : un .nam, un .gcap, un IR ou un paquet .zip entrent au catalogue ; ce qui ne peut
pas jouer est écarté AVEC sa raison, jamais en silence."""
import io
import json
import struct
import wave
import zipfile

import pytest

from bridge import capture_module as M, config as C, irlib, resolver, rig, tone_import as T


def _nam(arch="WaveNet", gear=None):
    d = {"version": "0.7.0", "architecture": arch, "config": {}, "weights": [0.1, 0.2], "sample_rate": 48000}
    if gear:
        d["metadata"] = {"gear_type": gear}
    return json.dumps(d).encode()


def _wav(seconds):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack("<h", 1000) + b"\0\0" * (int(48000 * seconds) - 1))
    return buf.getvalue()


def _gcap():
    model = {"architecture": "HyperWaveNet", "sample_rate": 48000, "weights": [.1], "version": "1.0.0",
             "config": {"params": [{"name": "Drive", "min": .2, "max": .8, "default": .5}]}}
    return json.dumps(M.build("Test capture", [{"id": "od", "name": "Overdrive", "model": model}])).encode()


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "ASSET_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(C, "CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setattr(irlib, "IR_DIR", str(tmp_path / "assets" / "irs" / "user"))
    monkeypatch.setattr(irlib, "_REL_ROOT", str(tmp_path))
    monkeypatch.setattr(resolver, "_TONES", {"mtime": None, "idx": None})
    monkeypatch.setattr(rig, "nam_unreadable", lambda: [])
    return tmp_path


def _tones(lib):
    return {t["id"]: t for t in json.loads((lib / "catalog.json").read_text(encoding="utf-8"))["tones"]}


def test_un_nam_seul_entre_au_catalogue_et_se_resout(lib):
    r = T.import_file("My Pedal-Capture.nam", _nam(gear="pedal"))
    assert r["ok"] and r["skipped"] == []
    t = _tones(lib)["imp-my-pedal-capture"]
    assert t["gear"] == "pedal" and t["models"][0]["arch"] == "1" and t["private"] is True
    assert resolver._resolve("imp-my-pedal-capture", {}).endswith("my-pedal-capture.nam")


def test_ce_qui_ne_joue_pas_est_ecarte_avec_sa_raison(lib, monkeypatch):
    assert "parametric" in T.import_file("p.nam", _nam("HyperWaveNet"))["skipped"][0]["reason"]
    assert T.import_file("notes.txt", b"hello")["skipped"][0]["reason"].startswith("unsupported")
    monkeypatch.setattr(rig, "nam_unreadable", lambda: ["SlimmableContainer"])
    r = T.import_file("a2.nam", _nam("SlimmableContainer"))
    assert r["ok"] and "cannot play" in r["warnings"][0]                    # inscrite, mais dite
    assert _tones(lib)["imp-a2"]["models"][0]["arch"] == "2"


def test_un_paquet_zip_de_golem_entre_en_entier(lib):
    """Le format des paquets de captures : un fragment library/catalog/*.json (noms de modèles, nature), les .nam sous
    assets/, un module .gcap, des .nam de plus dans un dossier, des A/B d'écoute et un vrai IR."""
    frag = {"tones": [{"id": "cap-test-amp", "title": "Test amp", "gear": "amp-cab", "format": "nam", "models": [
        {"id": "cap-test-amp-1", "name": "Gain 30%", "file": "assets/models/captures/test-amp/test-amp.nam", "arch": "1"},
        {"id": "cap-test-amp-p", "name": "parametric", "file": "assets/models/captures/test-amp/parametric.nam"},
        {"id": "cap-test-amp-x", "name": "escape", "file": "../../evil.nam"}]}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pack/library/catalog/captures.json", json.dumps(frag))
        z.writestr("pack/assets/models/captures/test-amp/test-amp.nam", _nam())
        z.writestr("pack/assets/models/captures/test-amp/parametric.nam", _nam("HyperWaveNet"))
        z.writestr("pack/modules/Test.gcap", _gcap())
        z.writestr("pack/models/clean-amp.nam", _nam(gear="amp_cab"))
        z.writestr("pack/models/dirty-amp.nam", _nam(gear="amp_cab"))
        z.writestr("pack/audio/AB-preset.wav", _wav(3))
        z.writestr("pack/irs/v30.wav", _wav(0.2))
        z.writestr("pack/README.txt", "hi")
    r = T.import_file("Pack.zip", buf.getvalue())
    kinds = sorted((i["kind"], i["models"]) for i in r["installed"])
    assert kinds == [("ir", 1), ("module", 1), ("tone", 1), ("tone", 2)]
    tones = _tones(lib)
    assert [m["name"] for m in tones["cap-test-amp"]["models"]] == ["Gain 30%"]      # le paramétrique et l'évasion restent dehors
    assert (lib / "assets/models/captures/test-amp/test-amp.nam").is_file() and not (lib.parent / "evil.nam").exists()
    assert [m["name"] for m in tones["imp-pack-models"]["models"]] == ["Clean amp", "Dirty amp"]
    assert tones["imp-pack-models"]["gear"] == "amp-cab"
    reasons = {s["file"]: s["reason"] for s in r["skipped"]}
    assert list(reasons) == ["pack/assets/models/captures/test-amp/parametric.nam"] and "parametric" in reasons[list(reasons)[0]]
    assert r["ignored"] == 2                                                         # le README et l'A/B d'écoute
    assert "not an impulse response" in T.import_file("long.wav", _wav(3))["skipped"][0]["reason"]   # seul, il est dit
    again = T.import_file("Pack.zip", buf.getvalue())                                # réimporter ne double rien
    assert again["ok"] and len([t for t in _tones(lib) if t.startswith(("cap-test", "imp-pack"))]) == 2


def test_la_route_n_est_pas_ouverte_au_reseau(monkeypatch):
    """Comme /api/ir/upload : l'écran du rack et un appareil appairé importent ; le réseau local, non."""
    from bridge import auth
    from tests.test_audit_2026_10_15_security import DEVS, Req
    monkeypatch.setattr(auth, "_device_by_token", lambda t: DEVS.get(t))
    assert auth.allowed_http(Req("POST", "/api/tones/import")) is False
    assert auth.allowed_http(Req("POST", "/api/tones/import", "musician")) is True
    assert auth.allowed_http(Req("POST", "/api/tones/import", client="127.0.0.1")) is True
