# SPDX-License-Identifier: GPL-3.0-or-later
"""La backing appartient à la CHANSON (docs/song-backing.md) : le preset est le lecteur et porte la règle des stems."""
import pytest

from bridge import backing_owner as BO
from bridge import recall, store
from bridge.state import state


def _preset(block=True, params=None, lanes=None):
    p = {"id": "rig", "lanes_v": 2, "lanes": lanes or [], "scenes": [{"id": "A"}],
         "config": {"gen": {"blocks": [{"id": "bk", "type": "backing-track", "params": params or {}}] if block else []}},
         "backing": {"songs": [{"slug": "legacy_song"}]}}
    return p


@pytest.fixture
def own(monkeypatch):
    monkeypatch.setattr(BO, "own_parts", lambda p, imap=None: {"guitar": "Guitar 1", "vocals": "Voice 1"})


def test_la_regle_coupe_ce_que_le_preset_joue_et_ses_exceptions(own):
    assert set(BO.rule(_preset())) == {"guitar", "vocals"}
    assert set(BO.rule(_preset(params={"mute_own": False}))) == set()
    r = BO.rule(_preset(params={"stems": {"guitar": "play", "piano": "mute", "nope": "mute"}}))
    assert set(r) == {"vocals", "piano"} and r["piano"] == "muted by this preset"
    assert BO.rule(_preset(block=False)) == {}                     # pas de lecteur : pas de règle


def test_le_mix_joue_est_la_chanson_puis_la_regle():
    song_mix = {"piano": {"mute": 1}, "drums": {"mute": 0, "vol": 0.8}}
    got = BO.apply(song_mix, ["guitar"], ["vocals", "drums", "piano", "guitar"])
    assert got["piano"]["mute"] == 1 and got["guitar"]["mute"] == 1 and got["drums"] == {"mute": 0, "vol": 0.8}
    assert song_mix == {"piano": {"mute": 1}, "drums": {"mute": 0, "vol": 0.8}}   # la chanson n'est pas touchée


def test_un_preset_joue_seul_ne_joue_aucune_backing(monkeypatch, own):
    monkeypatch.setattr(state, "song", None)
    eff = recall.effective_preset(_preset())
    assert eff["backing"]["songs"] == [] and set(eff["backing"]["mute"]) == {"guitar", "vocals"}


def test_la_backing_est_celle_de_la_chanson(monkeypatch, own):
    from bridge import golemfm, songs
    monkeypatch.setattr(state, "song", {"band_song": "rs:" + "a" * 32, "preset": "rig"})
    monkeypatch.setattr(songs, "load", lambda sid: {"id": sid, "title": "Mine", "artist": "Us",
                                                     "sheet": {"preset": "rig"}})
    monkeypatch.setattr(golemfm, "_golem_stems", lambda sid: ["vocals", "guitar"])
    eff = recall.effective_preset(_preset())
    assert [s["slug"] for s in eff["backing"]["songs"]] == ["rs:" + "a" * 32]       # ses stems, pas « legacy_song »
    # sans stems dans le .golem : la backing de SA fiche
    monkeypatch.setattr(golemfm, "_golem_stems", lambda sid: [])
    monkeypatch.setattr(songs, "load", lambda sid: {"id": sid, "sheet": {"preset": "rig", "backing": "fm_slug"}})
    monkeypatch.setattr(golemfm, "backing_key", lambda slug, band_song=None: slug)
    assert [s["slug"] for s in recall.effective_preset(_preset())["backing"]["songs"]] == ["fm_slug"]
    # sans bloc Backing Track : la chanson joue QUAND MÊME sa backing (une ligne la jouait déjà sans lui), sans règle
    eff = recall.effective_preset(_preset(block=False))
    assert [s["slug"] for s in eff["backing"]["songs"]] == ["fm_slug"] and eff["backing"]["mute"] == {}


def test_le_karaoke_garde_sa_liste(monkeypatch):
    monkeypatch.setattr(state, "song", None)
    p = {**_preset(), "id": store.KARAOKE_ID}
    assert recall.effective_preset(p)["backing"]["songs"] == [{"slug": "legacy_song"}]


def test_la_migration_recopie_sans_rien_effacer(monkeypatch):
    from bridge import golemfm, setlists as SL, songs as SG
    import bridge.store as ST
    presets = [{"id": "rig", "backing": ["legacy_song"]}, {"id": "other", "backing": {"songs": [{"slug": "x"}]}}]
    monkeypatch.setattr(ST, "load_presets", lambda: presets)
    docs = [{"id": "rs:" + "1" * 32, "title": "A", "sheet": {"preset": "rig"}},
            {"id": "rs:" + "2" * 32, "title": "B", "sheet": {"preset": "rig", "backing": "already"}},
            {"id": "rs:" + "3" * 32, "title": "C", "sheet": {"preset": "rig"}}]
    monkeypatch.setattr(SG, "list_all", lambda: docs)
    monkeypatch.setattr(golemfm, "_golem_stems", lambda sid: ["vocals"] if sid.endswith("3" * 32) else [])
    updated = []
    monkeypatch.setattr(SG, "update", lambda sid, **kw: updated.append((sid, kw)) or {})
    sl = {"id": "s1", "name": "S1", "lines": [{"id": "l1", "preset": "rig"}, {"id": "l2", "preset": "rig", "band_song": "x"},
                                               {"id": "l3", "preset": "rig", "backing": "mine"}]}
    monkeypatch.setattr(SL, "list_all", lambda: [{"id": "s1"}])
    monkeypatch.setattr(SL, "load", lambda sid: sl)
    monkeypatch.setattr(SL, "pid_of", lambda ln: ln.get("preset"))
    saved = []
    monkeypatch.setattr(SL, "save", lambda d: saved.append(d))
    assert BO.migrate() == 2
    assert updated == [("rs:" + "1" * 32, {"backing": "legacy_song"})]           # B a déjà sa backing, C a ses stems
    assert [ln.get("backing") for ln in sl["lines"]] == ["legacy_song", None, "mine"]
    assert presets[0]["backing"] == ["legacy_song"]                              # rien d'effacé dans le preset
