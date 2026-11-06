# SPDX-License-Identifier: GPL-3.0-or-later
"""Les switches EMPRUNTÉS suivent l'édition (2026-09-15) : le Click posé sur SW4 de « Paper Kite »
était dans le fichier, absent de /live, et le pied rappelait la scène D. `state.scene_claims` (rangée des
scènes de /live, `_on_foot_scene`) et `recall.backing_sw` (fronts du backing) n'étaient calculés qu'au
recall. `.venv/bin/python -m pytest tests/test_foot_claims_follow_edit.py -q`"""
import asyncio
import json
import re
import sys
import types
from pathlib import Path

from bridge import recall, store
from bridge.state import state

ROOT = Path(__file__).resolve().parents[1]

# chaque service qui peut prendre un slot de scène (foot_scene_claim) — posé sur un switch 1-5
SERVICES = ["click", "tuner", "rec", "compo", "backing-track", "sample", "drums", "standard", "whammy-dt", "clean-boost", "midi-pedal"]


def _doc(foot):
    """Un preset v2 : une lane guitare (whammy, boost, tuner, pédale MIDI) + les services de ⚙."""
    lane = [{"id": "wh", "type": "whammy-dt"}, {"id": "bo", "type": "clean-boost"},
            {"id": "tu", "type": "tuner"}, {"id": "mp", "type": "midi-pedal", "ref": "hx-stomp", "label": "HX"}]
    gen = [{"id": "bk", "type": "backing-track"}, {"id": "sm", "type": "sample"},
           {"id": "dr", "type": "drums"}, {"id": "st", "type": "standard"}]
    rec = [{"id": "rec-global", "type": "rec"}, {"id": "click-global", "type": "click", "bypass": True},
           {"id": "compo-global", "type": "compo"}]
    for b in lane + gen + rec:
        if b["type"] in foot:
            b["foot"] = foot[b["type"]]
    return {"id": "paper-kite", "name": "Paper Kite", "lanes_v": 2,
            "lanes": [{"id": "guitar-1", "role": "guitar", "chain": {"pre": lane, "split": None, "post": []}}],
            "config": {"gen": {"blocks": gen}, "rec": {"blocks": rec}},
            "scenes": [{"id": "A", "name": "Intro", "blocks": {}}]}


def test_chaque_service_pose_sur_la_rangee_des_scenes_est_un_claim():
    for t in SERVICES:
        claims = store._scene_claims(_doc({t: 4}))
        assert [c["type"] for c in claims.get(4, [])] == [t], t
    roles = {t: store._scene_claims(_doc({t: 3}))[3][0]["role"] for t in ("click", "tuner", "backing-track", "whammy-dt")}
    assert roles == {"click": "service", "tuner": "guitar", "backing-track": "service", "whammy-dt": "guitar"}   # l'étiquette de la pile
    mp = store._scene_claims(_doc({"midi-pedal": 2}))[2][0]
    assert (mp["ref"], mp["label"]) == ("hx-stomp", "HX")        # la tuile nomme la pédale


def test_bind_foot_claims_suit_le_document(monkeypatch):
    monkeypatch.setattr(state, "scene_claims", {5: [{"id": "old", "type": "rec"}]})
    monkeypatch.setattr(recall, "backing_sw", 5)
    recall.bind_foot_claims(_doc({"click": 4, "backing-track": 8, "rec": 5}))
    assert {k: [c["type"] for c in v] for k, v in state.scene_claims.items()} == {4: ["click"], 5: ["rec"]}
    assert recall.backing_sw == 8
    recall.bind_foot_claims(None)
    assert state.scene_claims == {} and recall.backing_sw is None


def test_sauver_le_preset_courant_rebranche_le_pied(tmp_path, monkeypatch):
    """La route de sauvegarde appelle `_bind_foot_services` sur le preset courant — et c'est cette
    fonction (non importable en test : bridge.app ouvre un port) qui appelle `bind_foot_claims`."""
    from bridge import config as C, routes_content, tones_sync, golemfm
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(store, "save_recorder_cfg_from", lambda p, prev=None: None)     # n'écrit pas config/recorder.json
    monkeypatch.setattr(tones_sync, "publish_soon", lambda *a, **k: None)
    monkeypatch.setattr(golemfm, "push_song_links", lambda: None)
    monkeypatch.setattr(state, "preset_id", "paper-kite")
    monkeypatch.setattr(state, "song", {}, raising=False)
    bound = []

    async def _noop():
        return None
    fake = types.ModuleType("bridge.app")
    fake._bind_foot_services = lambda p: (bound.append(p), recall.bind_foot_claims(p))
    fake._broadcast = _noop
    monkeypatch.setitem(sys.modules, "bridge.app", fake)
    import bridge
    monkeypatch.setattr(bridge, "app", fake, raising=False)
    monkeypatch.setattr(state, "scene_claims", {})

    r = asyncio.run(routes_content.save_preset(_doc({"click": 4, "rec": 5, "backing-track": 5})))
    assert r == {"ok": True, "id": "paper-kite"}
    assert bound, "la sauvegarde du preset courant n'a pas rebranché le pied"
    assert [c["type"] for c in state.scene_claims[4]] == ["click"]
    assert sorted(c["type"] for c in state.scene_claims[5]) == ["backing-track", "rec"]
    assert json.load(open(tmp_path / "presets" / "paper-kite.json"))["config"]["rec"]["blocks"][1]["foot"] == 4


def test_bind_foot_services_appelle_bind_foot_claims():
    src = (ROOT / "bridge" / "app.py").read_text()
    body = re.search(r"def _bind_foot_services\(cur\):(.*?)\ndef ", src, re.S).group(1)
    assert "recall_mod.bind_foot_claims(cur)" in body
