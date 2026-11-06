# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 10 (golem-format.md §6 bis / §6 ter) : la grille d'une chanson (`chart/song.gsx` de son .golem) devient un
standard que le bloc Standard joue ; un stem ENREGISTRÉ sur une version (`take_of`) est coupé — et c'est dit —
quand la fiche n'est plus dans cette version."""
import json

import pytest

from bridge import golemfile as G, golemfm as M, songs as S, standards as STD

SID = "us:" + "5e" * 16
GSX = {"v": 1, "title": "Our Blues", "composer": "The Band", "key": "Gm", "meter": "4/4", "tempo": 132,
       "feel": "swing", "form": ["A", "A", "B"],
       "sections": {"A": {"bars": "Gm7 | C7 | Gm7 | Gm7"}, "B": {"bars": "Cm7 | F7 | Bb | D7"}}}


@pytest.fixture
def std(tmp_path, monkeypatch):
    monkeypatch.setattr(STD, "SYNCED_DIR", str(tmp_path / "synced"))
    monkeypatch.setattr(STD, "LOCAL_DIR", str(tmp_path / "local"))
    STD._cache.update(sig=None)
    src = str(tmp_path / "s.golem")
    G.write(src, {"type": "song", "id": SID, "title": "Our Blues", "kind": "original",
                  "files": {"stems/guitar-1.flac": {"part": "guitar-1", "origin": "recorded",
                                                    "take_of": {"key": "Gm", "tempo": 132}},
                            "stems/voice-1.flac": {"part": "voice-1", "origin": "recorded",
                                                   "take_of": {"key": "Am", "tempo": 132}}}},
            {"chart/song.gsx": json.dumps(GSX).encode(), "stems/guitar-1.flac": b"fLaC1", "stems/voice-1.flac": b"fLaC2",
             "sheet.json": b'{"bpm": 132}'})
    S.install_golem(src)
    yield
    STD._cache.update(sig=None)


def test_la_grille_d_une_chanson_est_un_standard_jouable(std):
    slug = STD.song_slug(SID)
    assert slug == "song-us-" + "5e" * 16 and ":" not in slug
    meta = next(m for m in STD.list_standards() if m["slug"] == slug)
    assert meta["title"] == "Our Blues" and meta["key"] == "Gm" and meta["song"] == SID and meta["synced"] is False
    g = STD.get_grid(slug)
    assert g and g["sections"] and STD.render(g, key="Gm")["events"]               # le bloc Standard peut la jouer


def test_un_stem_d_une_autre_version_est_coupe_et_c_est_dit(std):
    v = S.version_now(SID)
    assert v["key"] == "Gm" and v["tempo"] == 132
    verdict = {t["stem"]: t for t in S.stem_takes(SID)}
    assert verdict["stems/guitar-1.flac"]["ok"]
    assert not verdict["stems/voice-1.flac"]["ok"] and "recorded in Am, the song is now in Gm" in verdict["stems/voice-1.flac"]["why"]
    M._STEMS_CACHE.clear()
    assert set(M.local_files(SID)) == {"guitar-1"}                                  # la voix ne joue pas faux : coupée
    items = {i["key"]: i for i in S.files_summary(SID)["items"]}
    assert items["take:voice-1"]["state"] == "missing" and "Am" in items["take:voice-1"]["info"]
    S.update(SID, bpm=150)                                                          # la fiche change de tempo
    M._STEMS_CACHE.clear()
    assert M.local_files(SID) is None                                               # plus aucun stem dans la version
    assert "recorded at 132, the song is now at 150" in S.stem_takes(SID)[0]["why"]
    S.update(SID, bpm=132)                                                          # retour à la version : il revient
    M._STEMS_CACHE.clear()
    assert set(M.local_files(SID)) == {"guitar-1"}


def test_changer_la_tonalite_dans_le_preset_coupe_le_stem_sans_que_le_golem_bouge(std, tmp_path, monkeypatch):
    """La tonalité vit dans le bloc Standard du PRESET : la changer ne réécrit pas le .golem, et le stem doit quand
    même se taire (le cache des stems est lié au fichier, la coupure se recalcule à chaque appel)."""
    from bridge import config as C, store
    pdir = tmp_path / "presets"
    pdir.mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(pdir))
    preset = {"id": "blues", "name": "Blues", "bpm": 132, "lanes_v": 2, "lanes": [], "scenes": [{"id": "A"}],
              "config": {"gen": {"blocks": [{"id": "std1", "type": "standard", "params": {"standard": STD.song_slug(SID), "key": "Original"}}]}}}
    store._write_json_atomic(str(pdir / "blues.json"), preset)
    S.update(SID, preset="blues")
    assert set(M.local_files(SID)) == {"guitar-1"}
    preset["config"]["gen"]["blocks"][0]["params"]["key"] = "Am"                    # le bloc passe en La mineur
    store._write_json_atomic(str(pdir / "blues.json"), preset)
    assert S.version_now(SID)["key"] == "Am"
    assert set(M.local_files(SID)) == {"voice-1"}                                   # la guitare (Gm) se tait, la voix (Am) joue
