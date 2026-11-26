# SPDX-License-Identifier: GPL-3.0-or-later
"""Le job golem.fm `song-load` (Follow Golem « preset + arrangement », 2026-11-26) : la chanson avec SON preset,
arrangement armé à l'arrêt ; refus en phrases (golem.fm les affiche tels quels et ne réessaie jamais)."""
import pytest

from bridge import blockstatus, recall, tones_jobs as TJ
from bridge.state import state

SID = "us:" + "c" * 32
DOC = {"id": SID, "title": "Paper Kite", "song_slug": "paper-kite", "sheet": {"preset": "rig"}}
RIG = {"id": "rig", "scenes": [{"id": "A"}], "config": {}}


@pytest.fixture
def rack(monkeypatch):
    calls = []
    songs = {SID: DOC}
    monkeypatch.setattr("bridge.songs.load", lambda sid: songs.get(sid))
    monkeypatch.setattr("bridge.songs.list_all", lambda: list(songs.values()))
    monkeypatch.setattr("bridge.store.load_preset", lambda pid: RIG if pid == "rig" else None)
    monkeypatch.setattr(recall, "load_preset", lambda pid: RIG if pid == "rig" else None)
    monkeypatch.setattr(recall, "do_recall", lambda pid, sc: calls.append(("recall", pid)) or True)
    monkeypatch.setattr(recall, "arm_song", lambda: calls.append(("arm", state.song.get("band_song"))))
    monkeypatch.setattr(recall, "_bind_foot_services", lambda p: calls.append(("foot",)))
    monkeypatch.setattr(recall, "_notify", None)
    for k, v in (("preset_id", "other"), ("song", None), ("mode", {}), ("perf", {}), ("backing", {}),
                 ("arrangement", {}), ("rig_loading", None)):
        monkeypatch.setattr(state, k, v, raising=False)
    return songs, calls


def test_annonce_dans_les_caps():
    assert "song-load" in blockstatus.JOB_CAPS and "song-load" in TJ._HANDLERS
    assert TJ.lane_of("song-load") == "rig"


def test_charge_par_id_avec_le_preset_de_la_chanson(rack):
    _songs, calls = rack
    ack = TJ._song_load({"id": SID, "slug": "paper-kite", "category": "song", "preset": "rig"})
    assert ack["song"] == SID and ack["preset"] == "rig"
    assert calls == [("recall", "rig"), ("arm", SID)]                # rappel puis armement, jamais de start
    assert state.rig_loading is None


def test_meme_preset_sans_rappel(rack, monkeypatch):
    _songs, calls = rack
    monkeypatch.setattr(state, "preset_id", "rig")
    TJ._song_load({"id": None, "slug": "paper-kite", "category": "song"})
    assert ("recall", "rig") not in calls and ("foot",) in calls and ("arm", SID) in calls


@pytest.mark.parametrize("job, why", [
    ({"id": "us:" + "d" * 32, "slug": "x"}, "not on your golem"),
    ({"id": None, "slug": "absent"}, "not on your golem"),
    ({"id": SID, "slug": "paper-kite", "preset": "autre"}, "plays its own preset"),
])
def test_refus(rack, job, why):
    with pytest.raises(RuntimeError, match=why):
        TJ._song_load(job)


def test_slug_porte_par_deux_chansons_refuse(rack):
    songs, _calls = rack
    songs["rs:" + "e" * 32] = {**DOC, "id": "rs:" + "e" * 32}
    with pytest.raises(RuntimeError, match="2 songs"):
        TJ._song_load({"id": None, "slug": "paper-kite"})


@pytest.mark.parametrize("k, v, why", [
    ("mode", {"ui": {"locked": True}}, "locked"),
    ("perf", {"recording": True}, "take is recording"),
    ("arrangement", {"running": True}, "song is playing"),
    ("rig_loading", {"song": "x"}, "still loading"),
])
def test_refus_d_etat(rack, monkeypatch, k, v, why):
    _songs, calls = rack
    monkeypatch.setattr(state, k, v)
    with pytest.raises(RuntimeError, match=why):
        TJ._song_load({"id": SID, "slug": "paper-kite"})
    assert calls == []
