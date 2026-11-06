# SPDX-License-Identifier: GPL-3.0-or-later
"""Le job `upload-di` (« Request DI » du web) : monter les DI d'une prise DÉJÀ montée. Le serveur vérifie chaque piste
re-déclarée par (idx, sha) — redéclarer la prise entière avec les DI décalait les idx et finissait en 409 ; et
`take-upload` avec `kinds:["di"]` ne pouvait rien, une prise montée sortant de la file du monteur."""
import json

import pytest

from bridge import tones_jobs, uploader
from tests.test_uploader import FakeServer, _wire, rig  # noqa: F401  (fixture réutilisée)

TAKE = "perf-20260907-120000"


class StrictServer(FakeServer):
    """Comme le vrai : une piste FINIE redéclarée avec un autre sha (ou le même idx pour un autre fichier) = 409."""

    def req(self, path, body=None, token=None, **kw):
        if path == "/api/ext/recordings":
            rec = self.recs.get(body["uid"])
            for d in body["tracks"]:
                cur = rec and rec["tracks"].get(d["idx"])
                if cur and cur["done"] and (cur["sha256"] != d["sha256"] or cur["size_bytes"] != d["size_bytes"]):
                    return 409, f"Track {d['idx']} already uploaded with a different sha256"
        return super().req(path, body, token, **kw)


def test_les_di_d_une_prise_deja_montee_montent_sous_des_idx_libres(rig, monkeypatch):
    srv = StrictServer()
    _wire(monkeypatch, srv)
    assert uploader.upload_take(TAKE)["ok"]                         # mix + lane + take.json, comme d'habitude
    before = {i: dict(t) for i, t in srv.recs[TAKE]["tracks"].items()}
    rep = uploader.upload_di(TAKE)
    assert rep["ok"] and rep["di"] == 1, rep
    tracks = srv.recs[TAKE]["tracks"]
    di = [t for t in tracks.values() if t["kind"] == "di"]
    assert len(di) == 1 and di[0]["done"] and di[0]["idx"] == max(before) + 1
    assert all(tracks[i]["sha256"] == t["sha256"] for i, t in before.items())   # rien de redéclaré autrement
    assert srv.completed.count(TAKE) == 2
    man = json.load(open(f"{rig}/take.json"))
    assert man["upload_di"]["state"] == "done" and man["upload"]["state"] == "done"   # deux états séparés


def test_une_di_deja_declaree_reprend_a_son_idx(rig, monkeypatch):
    srv = StrictServer(fail_put_after=None)
    _wire(monkeypatch, srv)
    uploader.upload_take(TAKE)
    srv.fail_put_after = len(srv.puts) + 1                          # coupe après une tranche de la DI
    assert not uploader.upload_di(TAKE)["ok"]
    srv.fail_put_after = None
    rep = uploader.upload_di(TAKE)
    assert rep["ok"], rep
    di = [t for t in srv.recs[TAKE]["tracks"].values() if t["kind"] == "di"]
    assert len(di) == 1 and di[0]["done"]                           # une seule DI : reprise, pas doublon


def test_une_prise_sans_di_le_dit(rig, monkeypatch):
    import os
    os.remove(f"{rig}/DI-Sandbox-Input-1.wav")
    _wire(monkeypatch, StrictServer())
    rep = uploader.upload_di(TAKE)
    assert not rep["ok"] and rep["reason"] == "no_di"


def test_le_job_refuse_une_prise_inconnue_et_sans_uid(rig, monkeypatch):
    with pytest.raises(RuntimeError, match="missing uid"):
        tones_jobs._upload_di({"action": "upload-di"})
    with pytest.raises(RuntimeError, match="unknown take"):
        tones_jobs._upload_di({"action": "upload-di", "uid": "nope"})


def test_jamais_pendant_qu_on_joue(rig, monkeypatch):
    _wire(monkeypatch, StrictServer())
    monkeypatch.setattr(uploader, "can_run", lambda: (False, "rec"))
    assert uploader.upload_di(TAKE) == {"ok": False, "uid": TAKE, "reason": "rec"}
