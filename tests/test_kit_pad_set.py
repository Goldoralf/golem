# SPDX-License-Identifier: GPL-3.0-or-later
"""Le son d'UN pad remplacé en place (bridge/kits.py set_pad, job golem.fm `kit-pad-set`, décision du mainteneur
2026-11-18) : même id, pas de copie implicite ; un kit d'usine ne se modifie pas, ni par ce job ni par l'écran."""
import json
import os

import pytest

from bridge import config as C, kits


@pytest.fixture
def box(tmp_path, monkeypatch):
    """Un dossier de kits et un dossier de samples à soi ; aucun miroir programmé, aucune écriture dans le rack."""
    root = tmp_path / "root"
    (root / "assets" / "samples").mkdir(parents=True)
    k = tmp_path / "kits"
    k.mkdir()
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(kits, "KITS_DIR", str(k))
    monkeypatch.setattr(kits, "SAMPLES_DIR", str(root / "assets" / "samples"))
    monkeypatch.setattr(kits, "_set_kind", lambda rel, kind, loud=None: None)
    synced = []
    monkeypatch.setattr(kits, "_sync_soon", lambda: synced.append(1))
    (root / "assets" / "samples" / "kick.wav").write_bytes(b"RIFFold")
    json.dump({"id": "pads-mine", "name": "Mine", "role": "pad", "engine": "rs5k",
               "pads": [{"note": 36, "sample": "assets/samples/kick.wav", "mode": "oneshot", "level": 0.0}]},
              open(k / "pads-mine.json", "w"))
    json.dump({"id": "pads-house", "name": "House", "role": "pad", "engine": "rs5k", "factory": True,
               "pads": [{"note": 36, "sample": "assets/samples/kick.wav", "mode": "oneshot", "level": 0.0}]},
              open(k / "pads-house.json", "w"))
    return {"root": root, "kits": k, "synced": synced}


def test_le_pad_change_de_son_dans_le_meme_kit_et_le_miroir_suit(box):
    r = kits.set_pad("pads-mine", 36, b"RIFFnew", "whatever.wav", label="Big kick", mode="gate", level=-3)
    assert r["ok"] and r["kit"]["id"] == "pads-mine"                              # en place : le même id
    assert r["pad"] == {"note": 36, "sample": "assets/samples/big-kick.wav", "mode": "gate", "level": -3.0}
    assert (box["root"] / "assets" / "samples" / "big-kick.wav").read_bytes() == b"RIFFnew"
    assert (box["root"] / "assets" / "samples" / "kick.wav").read_bytes() == b"RIFFold"   # l'ancien son n'est pas écrasé
    assert json.load(open(box["kits"] / "pads-mine.json"))["pads"][0]["sample"] == "assets/samples/big-kick.wav"
    assert box["synced"]                                                           # golem.fm reçoit le kit sans redémarrage
    r = kits.set_pad("pads-mine", 38, b"RIFFsn", "snare.wav")                      # une note libre : le pad est ajouté
    assert r["ok"] and [p["note"] for p in r["kit"]["pads"]] == [36, 38] and r["pad"]["mode"] == "gate"


def test_les_refus_se_disent(box):
    assert "not found" in kits.set_pad("nope", 36, b"x", "a.wav")["error"]
    f = kits.set_pad("pads-house", 36, b"x", "a.wav")
    assert f["ok"] is False and f["factory"] is True and "make a copy" in f["error"]
    assert json.load(open(box["kits"] / "pads-house.json"))["pads"][0]["sample"] == "assets/samples/kick.wav"
    assert "bad note" in kits.set_pad("pads-mine", 200, b"x", "a.wav")["error"]
    assert "expected one of" in kits.set_pad("pads-mine", 36, b"x", "a.txt")["error"]
    # l'écran non plus ne réécrit pas un kit d'usine (il perdait son drapeau, et la graine l'écrasait au démarrage)
    s = kits.save_kit({"id": "pads-house", "name": "House", "pads": []})
    assert s["ok"] is False and s["factory"] is True
    assert json.load(open(box["kits"] / "pads-house.json")).get("factory") is True


def test_le_job_rend_le_kit_relu_et_leve_sur_un_refus(box, monkeypatch):
    from bridge import tones_jobs as J
    monkeypatch.setattr(J, "_blob_bytes", lambda job, tmp: b"RIFFjob")
    r = J._kit_pad_set({"action": "kit-pad-set", "kit": "pads-mine", "note": 36, "sha": "s", "filename": "clap.wav"})
    assert r["kit"]["id"] == "pads-mine" and r["pad"]["sample"] == "assets/samples/clap.wav" and "kit-pad-set" in J._HANDLERS
    with pytest.raises(RuntimeError, match="factory kit"):
        J._kit_pad_set({"action": "kit-pad-set", "kit": "pads-house", "note": 36, "sha": "s", "filename": "c.wav"})
    with pytest.raises(RuntimeError, match="kit and note required"):
        J._kit_pad_set({"action": "kit-pad-set", "kit": "pads-mine", "sha": "s"})
