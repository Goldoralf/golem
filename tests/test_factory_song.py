# SPDX-License-Identifier: GPL-3.0-or-later
"""La chanson d'usine « Golem Rising » (docs/factory.md §5, 2026-10-20) : un `.golem` sain, qui joue un preset d'usine,
dont chaque bascule de partie touche un bloc qui EXISTE, et que la ligne de setlist d'usine joue par `band_song`.
`.venv/bin/python -m pytest tests/test_factory_song.py -q`"""
import json
import os

from bridge import golemfile as GF
from bridge import songs as SG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "library", "factory")


def _songs():
    d = os.path.join(F, "songs")
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".golem")]


def _lane_list(ln):
    ch = ln.get("chain") or {}
    return (ch.get("pre") or []) + (ch.get("post") or []) + \
        [x for br in ((ch.get("split") or {}).get("branches") or []) for x in br.get("blocks") or []]


def _blocks(p):
    out = set()
    for ln in p["lanes"]:
        ch = ln.get("chain") or {}
        for b in (ch.get("pre") or []) + (ch.get("post") or []) + \
                [x for br in ((ch.get("split") or {}).get("branches") or []) for x in br.get("blocks") or []]:
            out.add(b["id"])
    return out


def test_chaque_chanson_d_usine_est_un_golem_complet_qui_joue_un_preset_d_usine():
    assert _songs(), "l'usine livre au moins une chanson"
    for path in _songs():
        GF.verify(path)
        m = GF.read_manifest(path)
        assert m["type"] == "song" and SG.BS.match(m["id"]) and os.path.basename(path) == SG._safe(m["id"]) + ".golem"
        assert m["kind"] == "original" and m["rights"]["work"] == "own"
        assert {"art/cover.jpg", "art/band.jpg"} <= set(m["files"]), "pochette et photo du groupe"
        sheet = json.loads(GF.read_member(path, "sheet.json"))
        with open(os.path.join(F, "presets", sheet["preset"] + ".json"), encoding="utf-8") as f:
            p = json.load(f)
        scenes, known = {s["id"] for s in p["scenes"]}, _blocks(p)
        secs = sheet["arrangement"]["params"]["sections"]
        assert secs and SG.clean_sheet(sheet)["arrangement"]["params"]["sections"] == secs
        for s in secs:
            assert s.get("scene") is None or s["scene"] in scenes, s
            assert set(s.get("blocks") or {}) <= known, (s["name"], set(s["blocks"]) - known)
        # les bascules touchent TOUS les instruments qui ont une PÉDALE (pas un ampli, un baffle, un gate, un compresseur
        # ou un égaliseur : ça, c'est la scène) — une basse dont les états ouvrent la Darkglass suit les scènes
        not_pedal = {"amp", "amp-nam", "cab", "gate", "comp", "eq", "eq-para", "deesser", "piano"}
        with_pedals = {ln["id"] for ln in p["lanes"] for b in _lane_list(ln) if b["type"] not in not_pedal}
        lanes_hit = {ln["id"] for ln in p["lanes"] for s in secs for b in (s.get("blocks") or {}) if b in _blocks({"lanes": [ln]})}
        assert with_pedals and lanes_hit == with_pedals, (lanes_hit, with_pedals)


def test_la_ligne_d_usine_joue_la_chanson_et_la_chanson_ne_monte_pas_vers_golemfm():
    with open(os.path.join(F, "setlists", "factory.json"), encoding="utf-8") as f:
        lines = json.load(f)["lines"]
    ids = {GF.read_manifest(p)["id"] for p in _songs()}
    played = [ln for ln in lines if ln.get("band_song") in ids]
    assert played, "une ligne de la setlist d'usine joue la chanson"
    for ln in played:
        assert ln.get("preset") and ln.get("arrangement"), "la ligne garde une copie de la fiche"
        assert SG.is_factory(ln["band_song"])
        assert SG.sync_of({"id": ln["band_song"], "rev": 1}) == {"state": "factory"}
