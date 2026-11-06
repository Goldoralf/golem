# SPDX-License-Identifier: GPL-3.0-or-later
"""Rattacher un .golem venu d'ailleurs par l'EMPREINTE (golem-format.md §12.5, règle validée le 2026-10-08) :
un id inconnu qui est le même enregistrement qu'une de nos chansons — refusé si elle a ses médias, la complète si
elle n'en a pas (empreinte de sa carte), sinon chanson nouvelle. Vraies empreintes : tests/data/fingerprints.json."""
import json
import os

import pytest

from bridge import golemfile as G, songs as S

D = json.load(open(os.path.join(os.path.dirname(__file__), "data", "fingerprints.json")))
MINE = "rs:" + "b2" * 16
THEIRS = "us:" + "c3" * 16


def _file(path, sid, fp, dur=297893, title="Paper Kite"):
    G.write(str(path), {"type": "song", "id": sid, "title": title, "kind": "cover",
                        "recording": {"duration_ms": dur, "fingerprint": {"algo": "chromaprint", "value": fp}}},
            {"stems/drums.mp3": b"ID3" + b"\1" * 100, "sheet.json": b'{"bpm": 120}'})
    return str(path)


def test_meme_enregistrement_qu_une_chanson_complete_refuse(tmp_path):
    S.install_golem(_file(tmp_path / "a.golem", MINE, D["kite"]))
    with pytest.raises(S.InstallError, match="same recording as your song « Paper Kite » — already complete"):
        S.install_golem(_file(tmp_path / "b.golem", THEIRS, D["reencode96k"]))
    assert [d["id"] for d in S.list_all()] == [MINE]


def test_meme_enregistrement_que_la_carte_d_une_chanson_sans_medias_la_complete(tmp_path):
    S.save({"id": MINE, "rev": 7, "band": "b_night", "title": "Paper Kite", "kind": "cover",
            "song_slug": "glass_lanterns_paper_kite", "sheet": {"bpm": 87}}, bump=False)
    assert S.remember_cards([{"slug": "glass_lanterns_paper_kite", "fingerprint": D["kite"], "duration_sec": 297.9}]) == 1
    r = S.install_golem(_file(tmp_path / "b.golem", THEIRS, D["delay70ms"]))
    assert r["id"] == MINE and r["created"] is False
    d = S.load(MINE)
    assert d["rev"] == 7 and d["band"] == "b_night" and d["sheet"] == {"bpm": 87}      # notre fiche, notre id
    assert "stems/drums.mp3" in G.verify(S._path(MINE))["present"]                      # leurs médias
    assert [x["id"] for x in S.list_all()] == [MINE]


def test_un_autre_enregistrement_devient_une_chanson_nouvelle(tmp_path):
    S.install_golem(_file(tmp_path / "a.golem", MINE, D["kite"]))
    r = S.install_golem(_file(tmp_path / "b.golem", THEIRS, D["other_song"], title="Warm Light"))
    assert r["created"] and r["id"] == THEIRS
    assert sorted(d["id"] for d in S.list_all()) == sorted([MINE, THEIRS])


def test_une_chanson_complete_sans_empreinte_dans_son_manifeste_est_reconnue_par_sa_carte(tmp_path):
    """Vécu : Paper Kite tirée AVANT que golem.fm ne calcule les empreintes — médias présents, manifeste sans
    empreinte. Sa carte en a une : une copie d'ami doit être refusée, pas devenir un doublon."""
    G.write(str(tmp_path / "mine.golem"),
            {"type": "song", "id": MINE, "title": "Paper Kite", "kind": "cover"},
            {"stems/drums.mp3": b"ID3" + b"\1" * 100})
    S.install_golem(str(tmp_path / "mine.golem"), slug="glass_lanterns_paper_kite")
    S.remember_cards([{"slug": "glass_lanterns_paper_kite", "fingerprint": D["kite"], "duration_ms": 297893}])
    with pytest.raises(S.InstallError, match="already complete"):
        S.install_golem(_file(tmp_path / "b.golem", THEIRS, D["reencode96k"]))
    assert [d["id"] for d in S.list_all()] == [MINE]
