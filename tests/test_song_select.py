# SPDX-License-Identifier: GPL-3.0-or-later
"""Charger une chanson SANS la lancer (POST /api/arrangement {op: select, song}) — le tiroir Backing du Designer
(docs/song-backing.md §6) : l'état dit la chanson, sa backing s'arme, l'arrangement reste à l'arrêt."""
import asyncio

from bridge import app as A
from bridge.state import state


class _Req:
    headers, client, query_params, cookies = {}, None, {}, {}


def test_select_charge_la_chanson_sans_rien_lancer(monkeypatch):
    calls = []
    doc = {"id": "rs:" + "a" * 32, "title": "Paper Kite", "sheet": {"preset": "rig"}}
    rig = {"id": "rig", "scenes": [{"id": "A"}], "config": {}}
    monkeypatch.setattr("bridge.songs.load", lambda sid: doc if sid == doc["id"] else None)
    monkeypatch.setattr(A, "load_preset", lambda pid: rig if pid == "rig" else None)
    monkeypatch.setattr(A.auth_mod, "device_of", lambda req: None)
    monkeypatch.setattr(state, "preset_id", "rig")
    monkeypatch.setattr(state, "song", None)                               # restaurée après le test
    monkeypatch.setattr(A, "_bind_foot_services", lambda p: None)
    monkeypatch.setattr(A.recall_mod, "effective_preset",
                        lambda p: {**p, "backing": {"songs": [{"slug": doc["id"]}], "mute": {}}})
    monkeypatch.setattr(A._backing_ctl, "on_recall", lambda p, allowed=True: calls.append(("backing", p["backing"]["songs"])))
    monkeypatch.setattr(A._arr_ctl, "load", lambda p: calls.append(("arr-load",)))
    monkeypatch.setattr(A._arr_ctl, "start", lambda *a, **k: calls.append(("START",)) or {"ok": True})

    monkeypatch.setattr(A.recall_mod, "remember_live", lambda: calls.append(("remember",)))

    async def nothing():
        return None
    monkeypatch.setattr(A, "_broadcast", nothing)
    r = asyncio.run(A.arrangement_action(_Req(), {"op": "select", "song": doc["id"]}))
    assert r["ok"] and state.song.get("band_song") == doc["id"]
    assert ("backing", [{"slug": doc["id"]}]) in calls and ("arr-load",) in calls
    assert ("START",) not in calls                                           # chargée, pas lancée
    assert ("remember",) in calls                                            # retenu au redémarrage
    calls.clear()
    monkeypatch.setattr(A._arr_ctl, "stop", lambda: calls.append(("stop",)))
    monkeypatch.setattr(A.recall_mod, "effective_preset", lambda p: {**p, "backing": {"songs": [], "mute": {}}})
    r = asyncio.run(A.arrangement_action(_Req(), {"op": "unselect"}))
    assert r["ok"] and state.song is None                                      # le preset reste, seul
    assert ("backing", []) in calls and ("remember",) in calls and ("START",) not in calls


def test_la_mesure_d_une_chanson_chargee_depuis_songs_joue(monkeypatch):
    # docs/designer-song.md §6 : avant, song_click() ne lisait que la mesure d'une LIGNE de setlist — une chanson
    # chargée depuis Songs (ou par « Load » dans le Designer) gardait la mesure globale
    from bridge import recall
    p = {"id": "rig", "config": {"rec": {"blocks": [{"type": "click", "id": "clk", "params": {"beats": 4}}]}}}
    monkeypatch.setattr(recall, "load_preset", lambda pid: p if pid == "rig" else None)
    monkeypatch.setattr("bridge.songs.load", lambda sid: {"id": sid, "sheet": {"preset": "rig",
                                                          "blocks": {"clk": {"params": {"beats": 7, "den": 8}}}}})
    monkeypatch.setattr(state, "song", {"band_song": "rs:" + "b" * 32, "preset": "rig", "line": None})
    assert recall.song_click() == {"beats": 7, "den": 8}
    monkeypatch.setattr(state, "song", None)
    assert recall.song_click() == {}
