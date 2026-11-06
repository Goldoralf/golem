# SPDX-License-Identifier: GPL-3.0-or-later
"""Le backing par ID de chanson (plan-song-sharing lot 1.5) : une chanson dont le .golem porte des stems
joue ses stems ; sinon le slug et l'ancien cache, comme avant. Ce qui part vers golem.fm reste le slug."""
import json
import os

from bridge import golemfile as G, golemfm as M, songs as S

SID = "us:" + "b" * 32
BARS = {"version": 1, "slug": "glass_lanterns_paper_kite", "bars": [
    {"bar": 1, "ms": 290, "num": 4, "den": 4}, {"bar": 2, "ms": 3017, "num": 4, "den": 4}], "end_ms": 5800}


def _song_with_stems(tmp_path):
    src = str(tmp_path / "in.golem")
    G.write(src, {"type": "song", "id": SID, "title": "Paper Kite", "kind": "cover",
                  "files": {"stems/drums.mp3": {"part": "drums", "origin": "separated"},
                            "stems/guitar-1.flac": {"part": "guitar-1", "origin": "recorded"}}},
            {"stems/drums.mp3": b"ID3" + b"\1" * 300, "stems/guitar-1.flac": b"fLaC" + b"\2" * 300,
             "sync/bars.json": json.dumps(BARS).encode(), "sheet.json": b'{"bpm": 87}'})
    S.install_golem(src, slug="glass_lanterns_paper_kite")   # le slug vient du transport (song-sharing.md §2.8)


def test_la_cle_devient_l_id_quand_le_golem_porte_des_stems(tmp_path):
    assert M.backing_key("glass_lanterns_paper_kite") == "glass_lanterns_paper_kite"   # rien : le slug
    _song_with_stems(tmp_path)
    assert M.backing_key("glass_lanterns_paper_kite") == SID                # par le slug golem.fm
    assert M.backing_key("autre-slug", band_song=SID) == SID                     # par la chanson de la ligne
    out = M.resolve_backing_songs([{"slug": "glass_lanterns_paper_kite"}])
    assert out == [{"slug": SID, "from_slug": "glass_lanterns_paper_kite", "title": "Paper Kite"}]
    assert M.golemfm_slug(SID) == "glass_lanterns_paper_kite" and M.golemfm_slug("x") == "x"


def test_les_stems_les_emplacements_le_mix_et_la_carte(tmp_path):
    _song_with_stems(tmp_path)
    assert M.is_cached(SID)
    files = M.local_files(SID)
    assert set(files) == {"drums", "guitar-1"}                                   # lot 1.6 : chaque stem garde son nom
    assert open(files["guitar-1"], "rb").read().startswith(b"fLaC")
    assert M.stems_of(SID) == ["drums", "guitar-1"]                              # les six d'abord, puis les autres
    M.save_mix(SID, {"guitar-1": {"mute": 1, "vol": 1.0}})
    assert M.read_meta(SID)["mix"] == {"guitar-1": {"mute": 1, "vol": 1.0}}
    assert G.verify(S._path(SID))                                                # le mix n'a PAS réécrit le .golem
    from bridge import bars
    assert bars.load(SID)["bars"][1]["ms"] == 3017                               # la carte du .golem, slug golem.fm


def test_la_commande_de_chargement_passe_des_fichiers_explicites(tmp_path, monkeypatch):
    _song_with_stems(tmp_path)
    from bridge import backing
    sent = []
    monkeypatch.setattr(backing, "write_command", lambda c: sent.append(c))
    ctl = backing.BackingControl(osc=None, on_change=lambda: None)
    assert ctl.load(SID)["ok"]
    cmd = sent[-1]
    assert cmd["slug"] == SID and set(cmd["files"]) == {"drums", "guitar-1"} and "ticks" in cmd


def test_deux_guitares_deux_pistes(tmp_path):
    """Le cas qui motive le lot 1.6 : un original enregistré, deux guitares. Avant, la seconde tombait dans
    l'emplacement de la première et se taisait sans erreur."""
    src = str(tmp_path / "orig.golem")
    G.write(src, {"type": "song", "id": SID, "title": "Original", "kind": "original",
                  "files": {"stems/guitar-1.flac": {"part": "guitar-1", "origin": "recorded"},
                            "stems/guitar-2.flac": {"part": "guitar-2", "origin": "recorded"},
                            "stems/voice-1.flac": {"part": "voice-1", "origin": "recorded"}}},
            {"stems/guitar-1.flac": b"fLaC1", "stems/guitar-2.flac": b"fLaC2", "stems/voice-1.flac": b"fLaC3"})
    S.install_golem(src)
    assert M.stems_of(SID) == ["guitar-1", "guitar-2", "voice-1"]
    files = M.local_files(SID)
    assert open(files["guitar-2"], "rb").read() == b"fLaC2"


def test_le_mix_du_tiroir_regle_la_cle_jouee(tmp_path):
    """Le tiroir Backing parle en slug ; si la chanson joue depuis son .golem, c'est SON mix qu'on règle."""
    _song_with_stems(tmp_path)
    from bridge import routes_backing as R
    got = R.backing_mix_get("glass_lanterns_paper_kite")
    assert got["key"] == SID and got["stems"] == ["drums", "guitar-1"] and got["mix"] == {}
