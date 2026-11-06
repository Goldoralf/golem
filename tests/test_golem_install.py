# SPDX-License-Identifier: GPL-3.0-or-later
"""Installer un .golem venu d'ailleurs (plan-song-sharing lot 1.4, et le job song-install de golem.fm) :
vérifié en entier, puis FUSIONNÉ — le fichier apporte médias et identité, le rack garde sa fiche, sa
synchro et mine/. Et le dossier surveillé qui s'en sert."""
import json
import os
import zipfile

import pytest

from bridge import golemfile as G, inbox as I, songs as S

SID = "us:" + "a" * 32
_REAL_INBOX_DIR = I.inbox_dir          # pris au chargement, avant la garde de conftest


def _incoming(path, title="Paper Kite", sheet=None, mine=None, rep=None, **files):
    members = {"audio/original.mp3": b"ID3" + b"\0" * 400, "sync/bars.json": b'{"v":1,"bars":[]}', **files}
    if sheet is not None:
        members["sheet.json"] = json.dumps(sheet).encode()
    if mine:
        members.update(mine)
    man = {"type": "song", "id": SID, "title": title, "kind": "cover", "golemfm": {"slug": "un_slug_du_fichier"}}
    if rep:
        man["repertoire"] = rep
    G.write(str(path), man, members)
    return str(path)


def test_une_chanson_inconnue_est_creee_sans_la_synchro_d_un_autre_rack(tmp_path):
    src = _incoming(tmp_path / "in.golem", sheet={"bpm": 87}, rep={"rev": 99, "band": "b_autre"})
    r = S.install_golem(src, slug="glass_lanterns_paper_kite")
    assert r["created"] and r["id"] == SID
    d = S.load(SID)
    assert d["title"] == "Paper Kite" and d["sheet"] == {"bpm": 87}
    assert d["rev"] == 1 and "band" not in d                    # la synchro d'un autre rack est écartée
    assert d["song_slug"] == "glass_lanterns_paper_kite"    # le slug du TRANSPORT, pas celui du fichier (§2.8)


def test_un_golem_pose_a_la_main_ne_prend_jamais_le_slug_du_fichier(tmp_path):
    """song-sharing.md §2.8 : un .golem ne mène à personne. Le `golemfm.slug` d'un fichier (un ancien, ou un faux)
    est ignoré ; sans transport, la chanson se relie par la carte du catalogue de CE compte qui porte son id."""
    r = S.install_golem(_incoming(tmp_path / "in.golem"))
    assert r["created"] and "song_slug" not in S.load(SID)
    os.unlink(S._path(SID))
    S.remember_cards([{"slug": "glass_lanterns_paper_kite", "golem_id": SID}])
    S.install_golem(_incoming(tmp_path / "in2.golem"))
    assert S.load(SID)["song_slug"] == "glass_lanterns_paper_kite"


def test_une_chanson_connue_garde_sa_fiche_sa_synchro_et_mine(tmp_path):
    S.save({"id": SID, "rev": 5, "band": "b_night", "title": "Paper Kite", "kind": "cover",
            "sheet": {"preset": "paper-kite", "bpm": 87}}, bump=False)
    G.replace(S._path(SID), None, {"mine/take1.wav": b"RIFF" + b"\1" * 100})
    src = _incoming(tmp_path / "in.golem", title="Paper Kite (remaster)", sheet={"bpm": 120},
                    mine={"mine/theirs.wav": b"RIFF"}, **{"stems/drums.mp3": b"ID3" + b"\2" * 200})
    r = S.install_golem(src)
    assert not r["created"]
    d = S.load(SID)
    assert d["title"] == "Paper Kite (remaster)"                # l'identité vient du fichier
    assert d["sheet"] == {"preset": "paper-kite", "bpm": 87}    # la FICHE reste celle du rack
    assert d["rev"] == 5 and d["band"] == "b_night"               # la synchro aussi
    p = S._path(SID)
    rep = G.verify(p)
    assert "stems/drums.mp3" in rep["present"]                   # les médias arrivent
    assert G.read_member(p, "mine/take1.wav") == b"RIFF" + b"\1" * 100
    with zipfile.ZipFile(p) as zf:
        assert "mine/theirs.wav" not in zf.namelist()            # le mine/ d'un autre ne remplace pas le nôtre


def test_un_fichier_refuse_ne_touche_pas_la_bibliotheque(tmp_path):
    bad = tmp_path / "bad.golem"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("golem.json", json.dumps({"format": "golem/1", "type": "song", "id": "paper-kite", "files": {}}))
    with pytest.raises(S.InstallError, match="not a song id"):
        S.install_golem(str(bad))
    assert S.list_all() == []
    assert not [f for f in os.listdir(S.C.SONGS_DIR) if f.startswith(".install-")]   # pas de reste


def test_le_dossier_surveille(tmp_path, monkeypatch):
    box = tmp_path / "inbox"
    monkeypatch.setattr(I, "CFG", str(tmp_path / "inbox.json"))
    monkeypatch.setattr(I, "inbox_dir", _REAL_INBOX_DIR)      # la vraie lecture du réglage (la garde la remplace)
    I.set_dir(str(box))
    I._seen.clear()
    src = _incoming(box / "song.golem")
    (box / "bad.golem").write_bytes(b"not a zip")
    (box / "track.mp3").write_bytes(b"ID3")
    assert I.scan_once() == []                                   # premier relevé : on attend la stabilité
    evs = {e["file"]: e for e in I.scan_once()}
    assert evs["song.golem"]["ok"] and evs["song.golem"]["id"] == SID
    assert not evs["bad.golem"]["ok"] and "zip" in evs["bad.golem"]["why"]
    assert os.path.exists(box / ".imported" / "song.golem")      # jamais effacé
    assert (box / ".refused" / "bad.golem.why.txt").read_text().strip()
    assert (box / "track.mp3").exists()                          # pas un .golem : laissé tel quel
    assert S.load(SID)["title"] == "Paper Kite"
    assert I.recent()["recent"][0]["file"] in ("song.golem", "bad.golem")


def test_une_chanson_ct_qui_circule_s_installe(tmp_path):
    """song-sharing.md §2.8 : l'id d'un fichier qui circule est `ct:…` (dérivé de la chanson, pas du compte)."""
    p = str(tmp_path / "ct.golem")
    G.write(p, {"type": "song", "id": "ct:0123abcd", "title": "Paper Kite", "kind": "cover"}, {"lyrics/song.lrc": b"x"})
    r = S.install_golem(p)
    assert r["created"] and r["id"] == "ct:0123abcd" and S.load("ct:0123abcd")["title"] == "Paper Kite"


def test_un_ct_pose_a_la_main_se_rattache_par_le_ct_id_de_la_carte(tmp_path):
    p = str(tmp_path / "ct.golem")
    G.write(p, {"type": "song", "id": "ct:" + "0" * 32, "title": "Paper Kite", "kind": "cover"}, {"lyrics/song.lrc": b"x"})
    S.remember_cards([{"slug": "glass_lanterns_paper_kite", "golem_id": "rs:1", "ct_id": "ct:" + "0" * 32}])
    S.install_golem(p)
    assert S.load("ct:" + "0" * 32)["song_slug"] == "glass_lanterns_paper_kite"
