# SPDX-License-Identifier: GPL-3.0-or-later
"""Les erreurs de l'app et les signatures (docs/diagnostics.md §7.2–§7.3, lots D4+D5) : `ui_error` dans la chronologie,
plafonné, jamais un déclencheur ; une signature calculée par le rack sur la forme scrubbée, la même d'une machine à
l'autre ; une exception signée par son type et sa frame du bridge, pas par son message."""
import hashlib
import logging
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge import config as C, diag, golog, routes_diag, scrub


def _rack(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(diag, "_scrubber", diag.Scrubber(names=["Léa"], presets=[], songs=[]))
    monkeypatch.setattr(diag, "_scrubber_at", time.time())        # sinon diag.scrubber() le reconstruit sans Léa
    monkeypatch.setattr(diag, "collect_logs", lambda w, sc=None: ({}, []))
    diag.open_session()


def _client():
    app = FastAPI()
    app.include_router(routes_diag.router)
    return TestClient(app)


def test_la_signature_est_celle_de_la_forme_qui_part(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    row = diag.event("error", logger="recall", msg="preset of Léa not found in /home/lea/golem/presets/x.json",
                     sig_src="recall: preset of Léa not found in /home/lea/golem/presets/x.json")
    assert "Léa" not in row["sig_src"] and "/home/" not in row["sig_src"]
    assert row["sig"] == hashlib.sha256(row["sig_src"].encode()).hexdigest()[:12]
    # une autre machine, d'autres valeurs : la même signature
    other = diag.event("error", logger="recall", msg="x", sig_src="recall: preset of Léa not found in /home/bob/g/presets/x.json")
    assert other["sig"] == row["sig"]
    # une signature fournie par l'appelant est ignorée
    forged = diag.event("error", logger="recall", msg="m", sig="000000000000", sig_src="recall: m")
    assert forged["sig"] == scrub.sig(scrub.normalize("recall: m"))


def test_une_exception_est_signee_par_son_type_et_sa_frame(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(diag, "trigger", lambda t, **f: seen.append(f))
    lg = logging.getLogger("golem.recall")
    h = golog._DiagHandler()
    for n in (3, 4711):
        try:
            {}["slot%d" % n]
        except KeyError:
            rec = lg.makeRecord(lg.name, logging.ERROR, __file__, 1, "recall %d failed", (n,), sys_exc_info())
            h.emit(rec)
    assert seen[0]["sig_src"] == seen[1]["sig_src"] == "recall|KeyError|?"   # pas de frame bridge/ dans ce test
    assert "3" in seen[0]["msg"] and "4711" in seen[1]["msg"]


def sys_exc_info():
    import sys
    return sys.exc_info()


def test_ui_error_entre_dans_la_chronologie_signe_et_plafonne(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    trig = []
    monkeypatch.setattr(diag, "trigger", lambda *a, **k: trig.append(a))
    c = _client()
    body = {"page": "/designer?x=1", "msg": "x is undefined", "src": "http://192.168.1.4:8770/app/page-designer.js",
            "line": 120, "frames": ["page-designer.js:120", "lib.js:33"], "client": "companion", "extra": "dropped"}
    r = c.post("/api/diag/ui-error", json=body).json()
    assert r["ok"] and len(r["sig"]) == 12
    row = [x for x in diag._read_timeline() if x["type"] == "ui_error"][-1]
    assert row["page"] == "/designer" and row["where"] == "page-designer.js:120" and row["client"] == "companion"
    assert "extra" not in row and "192.168" not in str(row) and not trig
    # même erreur, une autre ligne (une autre version) : même signature
    body2 = dict(body, line=131, frames=["page-designer.js:131", "lib.js:40"])
    assert c.post("/api/diag/ui-error", json=body2).json()["sig"] == r["sig"]
    for _ in range(routes_diag.UI_ERRORS_MAX):
        c.post("/api/diag/ui-error", json=body)
    assert c.post("/api/diag/ui-error", json=body).json() == {"ok": False, "dropped": True}
    assert body["client"] in routes_diag.UI_CLIENTS
    assert diag.violations({}) == []
