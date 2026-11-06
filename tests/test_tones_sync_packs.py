# SPDX-License-Identifier: GPL-3.0-or-later
"""Le doc de pack poussé au miroir golem.fm (tones_sync.build_packs) — retour golem.fm 2026-09-14,
Library restructurée par rôle : `family` sur les captures (la règle du sélecteur, override compris),
la NATURE lue dans les fichiers (deux packs d'IR dormaient en `experimental`), `extra.engine` sur
les kits (pads contre batteries), et le pack `sample` qui reste poussé (les one-shots du bloc)."""

import json
import os

from bridge import config as C, kits, tones_sync as S


def _lib(tmp_path, monkeypatch, tones, kit=None, samples=()):
    root = tmp_path
    for t in tones:
        for m in t["models"]:
            p = root / m["file"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x" * 16)
    (root / "library" / "catalog").mkdir(parents=True, exist_ok=True)
    json.dump({"tones": tones}, open(root / "library" / "catalog" / "tones-index.json", "w"))
    kdir = root / "library" / "kits"; kdir.mkdir(parents=True)
    if kit:
        json.dump(kit, open(kdir / f"{kit['id']}.json", "w"))
    sdir = root / "assets" / "samples"; sdir.mkdir(parents=True)
    for fn in samples:
        (sdir / fn).write_bytes(b"RIFF")
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "CATALOG", str(root / "library" / "catalog" / "tones-index.json"))
    monkeypatch.setattr(kits, "KITS_DIR", str(kdir))
    monkeypatch.setattr(kits, "SAMPLES_DIR", str(sdir))
    monkeypatch.setattr(S, "VITAL_DIRS", ())
    packs, _ = S.build_packs({})
    return {p["uid"]: p for p in packs}


def test_family_lue_comme_le_selecteur_override_compris(tmp_path, monkeypatch):
    tones = [
        {"id": 1, "gear": "amp-cab", "format": "nam", "title": "Marshall", "url": "https://www.tone3000.com/x", "models": [{"file": "a/m.nam"}]},
        {"id": 2, "gear": "amp", "format": "nam", "title": "Ampeg", "tags": ["bass", "svt"], "url": "https://www.tone3000.com/x", "models": [{"file": "a/b.nam"}]},
        {"id": 3, "gear": "pedal", "format": "nam", "title": "Darkglass", "style": "bass", "family": "guitar", "url": "https://www.tone3000.com/x", "models": [{"file": "a/p.nam"}]},
        {"id": 4, "gear": "outboard", "format": "nam", "title": "Neve", "url": "https://www.tone3000.com/x", "models": [{"file": "a/n.nam"}]},
        {"id": 5, "gear": "amp", "format": "nam", "title": "Behringer Bass V-Amp Pro", "url": "https://www.tone3000.com/x", "models": [{"file": "a/v.nam"}]},
        {"id": 6, "gear": "amp", "format": "nam", "title": "Fender Bassman 59", "url": "https://www.tone3000.com/x", "models": [{"file": "a/f.nam"}]},
    ]
    packs = _lib(tmp_path, monkeypatch, tones)
    assert packs["t3k:5"]["family"] == "bass"            # « Bass » en mot entier dans le nom
    assert packs["t3k:6"]["family"] == "guitar"          # Bassman n'est pas une basse
    assert packs["t3k:1"]["family"] == "guitar"
    assert packs["t3k:2"]["family"] == "bass"            # heuristique tag
    assert packs["t3k:3"]["family"] == "guitar"          # l'override manuel bat le style
    assert "family" not in packs["t3k:4"]                # l'outboard n'a pas de famille : le rôle la choisit


def test_la_nature_se_lit_dans_les_fichiers(tmp_path, monkeypatch):
    tones = [
        {"id": 64815, "gear": "experimental", "format": "ir", "title": "GK IRs", "url": "https://www.tone3000.com/x", "models": [{"file": "a/1.wav"}, {"file": "a/2.wav"}]},
        {"id": 7, "gear": "cab", "format": "nam", "title": "déclaré cab, fichiers nam", "url": "https://www.tone3000.com/x", "models": [{"file": "a/c.nam"}]},
        {"id": 8, "gear": "amp", "format": "nam", "title": "tête", "url": "https://www.tone3000.com/x", "models": [{"file": "a/h.nam"}]},
        {"id": 9, "gear": "weird", "format": "?", "title": "illisible", "url": "https://www.tone3000.com/x", "models": [{"file": "a/z.bin"}]},
    ]
    packs = _lib(tmp_path, monkeypatch, tones)
    assert packs["t3k:64815"]["kind"] == "cab" and packs["t3k:64815"]["family"] == "guitar"
    assert packs["t3k:7"]["kind"] == "amp-cab"
    assert packs["t3k:8"]["kind"] == "amp"               # amp seul vs amp-cab : deux .nam, la déclaration reste
    assert packs["t3k:9"]["kind"] == "experimental"      # seulement quand les fichiers ne disent rien
    assert S.kind_of("cab", ["/x/ir.WAV", "/x/ir2.flac"]) == "cab"


def test_kit_engine_et_pack_sample(tmp_path, monkeypatch):
    kit = {"id": "k1", "name": "Pads", "engine": "avldrums", "pads": []}
    packs = _lib(tmp_path, monkeypatch, [], kit=kit, samples=("kick.wav", "count-in.wav"))
    assert packs["local:kit-k1"]["extra"] == {"kit_id": "k1", "engine": "avldrums", "factory": True}   # une batterie est d'usine par nature
    assert "drums" in packs["local:kit-k1"]["tags"]
    smp = packs["local:samples"]
    assert smp["kind"] == "sample" and len(smp["assets"]) == 2
    assert smp["assets"][0]["extra"]["rel"] == "assets/samples/count-in.wav"
    kit2 = {"id": "k2", "name": "Pads", "pads": []}                       # sans engine = rs5k (pads)
    packs2 = _lib(tmp_path / "b", monkeypatch, [], kit=kit2)
    assert packs2["local:kit-k2"]["extra"] == {"kit_id": "k2", "engine": "rs5k", "factory": False} and "pads" in packs2["local:kit-k2"]["tags"]
