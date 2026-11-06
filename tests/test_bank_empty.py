# SPDX-License-Identifier: GPL-3.0-or-later
"""Vider une bank (sélecteur de bank, 2026-10-08) : la ligne quitte la setlist mais son RANG reste — les banks
suivantes ne bougent pas. Le preset et la chanson ne sont pas touchés."""
import os

from bridge import config as C, setlists as SL


def test_vider_une_bank_ne_decale_pas_les_suivantes(tmp_path, monkeypatch):
    sdir = tmp_path / "setlists"; sdir.mkdir()
    monkeypatch.setattr(C, "SETLISTS_DIR", str(sdir))
    sl = SL.normalize({"id": "t", "name": "T", "presets": ["a", "b", "c"]})
    sl["lines"][1]["band_song"] = "rs:x"                 # une ligne qui porte une chanson
    SL.save(sl)
    lid = SL.load("t")["lines"][1]["id"]
    out = SL.remove_line("t", lid, keep_slot=True)
    assert out["presets"] == ["a", "", "c"]               # c reste la bank 3
    assert not any(ln.get("band_song") for ln in out["lines"])
    assert SL.remove_line("t", "inconnue", keep_slot=True) is None


def test_echanger_deux_banks(tmp_path, monkeypatch):
    sdir = tmp_path / "setlists"; sdir.mkdir()
    monkeypatch.setattr(C, "SETLISTS_DIR", str(sdir))
    sl = SL.normalize({"id": "t", "name": "T", "presets": ["a", "b", "c"]})
    sl["lines"][0]["band_song"] = "rs:x"
    SL.save(sl)
    out = SL.swap_lines("t", 0, 2)
    assert out["presets"] == ["c", "b", "a"] and out["lines"][2].get("band_song") == "rs:x"   # la chanson suit
    out = SL.swap_lines("t", 1, 5)                                    # vers une bank libre au-delà de la fin
    assert out["presets"] == ["c", "", "a", "", "", "b"]


def test_ranger_une_chanson_dans_une_bank(tmp_path, monkeypatch):
    """La bank reçoit la CHANSON (pas son seul preset) : l'ancienne ligne de la chanson et les lignes « preset seul »
    du même preset deviennent vides ; aucune autre bank ne bouge."""
    from bridge import songs as S
    sdir, so = tmp_path / "setlists", tmp_path / "songs"; sdir.mkdir(); so.mkdir()
    monkeypatch.setattr(C, "SETLISTS_DIR", str(sdir))
    monkeypatch.setattr(C, "SONGS_DIR", str(so)); monkeypatch.setattr(S, "DIR", str(so), raising=False)
    S.save({"id": "rs:cr", "rev": 1, "title": "Paper Kite", "kind": "cover", "born": "rack",
            "sheet": {"preset": "paper-kite"}}, bump=False)
    SL.save(SL.normalize({"id": "t", "name": "T", "presets": ["a", "paper-kite", "b"]}))
    out = SL.place_song("t", "rs:cr", 3)
    assert [ln.get("band_song") for ln in out["lines"]] == [None, None, None, "rs:cr"]
    assert [ln.get("preset") for ln in out["lines"]][:3] == ["a", None, "b"]          # la ligne « preset seul » vidée
    out = SL.place_song("t", "rs:cr", 1)                                              # déplacée : l'ancien rang se vide
    assert [bool(ln.get("band_song")) for ln in out["lines"]] == [False, True, False, False]
