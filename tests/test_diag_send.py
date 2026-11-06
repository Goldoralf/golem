# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 8, lot C (docs/diagnostics.md §4, §6) — l'envoi et ses trois déclencheurs : golem.fm
injoignable → le paquet ATTEND et part une seule fois au passage suivant ; à l'arrêt on ÉCRIT
avant d'envoyer ; un incident déclenche UN paquet par nature toutes les 10 min ; le job
`diagnostic-report` refuse quand la case est décochée ; le boot joint la session coupée.
`.venv/bin/python -m pytest tests/test_diag_send.py -q`"""
import json
import os

from bridge import config as C, diag


def _rack(tmp_path, monkeypatch, paired=True):
    root = tmp_path
    (root / "config").mkdir()
    (root / "presets").mkdir()
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "CONFIG_DIR", str(root / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(root / "presets"))
    monkeypatch.setattr(diag, "_scrubber", None)
    monkeypatch.setattr(diag, "collect_logs", lambda w, sc=None: ({}, []))
    monkeypatch.setattr(diag, "_rate", {})
    from bridge import golemfm
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://golem.test", "gmt_x") if paired else ("", ""))
    return root


class _Net:
    """Faux golem.fm : `down` = refuse tout, sinon accepte et note les sha reçus."""
    def __init__(self, down=False):
        self.down, self.got = down, []

    def install(self, monkeypatch):
        import urllib.request

        net = self

        class _Resp:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.body).encode()

        def urlopen(req, timeout=None):
            if net.down:
                raise OSError("connection refused")
            sha = req.full_url.split("sha256=")[1]
            dedup = sha in net.got
            net.got.append(sha)
            return _Resp({"id": len(net.got), "deduplicated": dedup})

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        return self


def test_injoignable_puis_envoye_une_seule_fois(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    net = _Net(down=True).install(monkeypatch)
    diag.open_session()
    r = diag.build("event", event_={"type": "requested"})
    ok, err = diag.send(r["report_id"])
    assert ok is False and "refused" in err
    row = diag.index()[0]
    assert row["sent_at"] is None and row["error"] and os.path.exists(os.path.join(str(tmp_path), "diag", row["file"]))
    # le réseau revient : le battement suivant l'envoie, le suivant ne renvoie rien
    net.down = False
    assert diag.flush_pending() == 1
    assert diag.index()[0]["sent_at"] and diag.index()[0]["error"] is None
    assert diag.flush_pending() == 0 and len(net.got) == 1


def test_non_appaire_reste_en_attente(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch, paired=False)
    diag.open_session()
    r = diag.build("event", event_={"type": "requested"})
    ok, err = diag.send(r["report_id"])
    assert ok is False and err == "not paired" and diag.index()[0]["sent_at"] is None


def test_arret_ecrit_avant_d_envoyer(tmp_path, monkeypatch):
    root = _rack(tmp_path, monkeypatch)
    _Net(down=True).install(monkeypatch)
    diag.open_session()
    diag.event("recall", preset_hash="a", scene="A", ms=20, ok=True, rebuild=False)
    r = diag.shutdown_report("sigterm")
    assert r["kind"] == "session" and os.path.exists(os.path.join(str(root), "diag", r["file"]))
    assert diag.session()["ended"] == "clean"
    assert diag.index()[0]["sent_at"] is None            # pas envoyé, mais ÉCRIT
    assert r["report"]["usage"]["recalls"]["count"] == 1


def test_boot_joint_la_session_coupee_et_vide_l_attente(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    net = _Net(down=True).install(monkeypatch)
    diag.boot()
    diag.event("chip", chip="NO AUDIO", on=True)
    ev = diag.build("event", event_={"type": "audio", "detail": "lost"})
    diag.send(ev["report_id"])                            # reste en attente (réseau coupé)
    # « il a tout éteint » : pas de shutdown_report. Reboot, réseau revenu :
    net.down = False
    monkeypatch.setattr(diag, "_previous", None)
    diag.boot()
    r = diag.boot_report()
    assert r["report"]["previous_session"]["ended"] == "unclean"
    assert r["report"]["previous_session"]["anomalies"][0]["chip"] == "NO AUDIO"
    sent = [x for x in diag.index() if x["sent_at"]]
    assert {x["kind"] for x in sent} == {"event", "boot"} and len(net.got) == 2


def test_trigger_un_paquet_par_nature_par_10_min(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    _Net().install(monkeypatch)
    diag.open_session()
    built = []
    monkeypatch.setattr(diag, "build", lambda kind, **kw: built.append((kind, kw)) or None)
    import threading
    # exécution synchrone du thread pour le test
    monkeypatch.setattr(threading, "Thread", lambda target=None, **kw: type("T", (), {"start": lambda s: target()})())
    diag.trigger("audio", state="lost", why="clock frozen")
    diag.trigger("audio", state="lost", why="clock frozen")     # même nature, < 10 min : pas de 2e paquet
    diag.trigger("reaper", state="down")                          # autre nature : oui
    diag.trigger("reaper", state="up")                            # `up` n'est pas déclencheur
    diag.trigger("xrun", delta=3, window_s=3)                     # sous le seuil
    diag.trigger("xrun", delta=47, window_s=3)                    # rafale
    assert [b[1]["event_"]["type"] for b in built] == ["audio", "reaper", "xrun"]
    assert built[0][1]["event_"]["detail"] == "clock frozen"
    rows = diag._read_timeline()
    assert [r["type"] for r in rows if r["type"] != "boot"] == ["audio", "audio", "reaper", "reaper", "xrun", "xrun"]


def test_trigger_case_decochee_ecrit_mais_n_envoie_pas(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    diag.set_auto(False)
    diag.open_session()
    built = []
    monkeypatch.setattr(diag, "build", lambda kind, **kw: built.append(kind) or None)
    diag.trigger("audio", state="lost", why="x")
    assert built == [] and [r["type"] for r in diag._read_timeline()] == ["boot", "audio"]
    assert diag.boot_report() is None and diag.shutdown_report() is None


def test_job_diagnostic_report(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    net = _Net().install(monkeypatch)
    diag.open_session()
    from bridge import tones_jobs
    out = tones_jobs._diagnostic_report({"detail": "from the web"})
    assert out["report_id"] and len(net.got) == 1
    diag.set_auto(False)
    import pytest
    with pytest.raises(RuntimeError, match="reports disabled on this rack"):
        tones_jobs._diagnostic_report({})


def test_une_exception_du_bridge_devient_un_evenement(tmp_path, monkeypatch):
    _rack(tmp_path, monkeypatch)
    diag.open_session()
    built = []
    monkeypatch.setattr(diag, "build", lambda kind, **kw: built.append(kw["event_"]) or None)
    import threading
    monkeypatch.setattr(threading, "Thread", lambda target=None, **kw: type("T", (), {"start": lambda s: target()})())
    from bridge.golog import get
    log = get("recall")
    log.error("recall refused for Set Léa")                 # sans trace : chronologie seule
    try:
        raise ValueError("gmem[0] frozen")
    except ValueError:
        log.exception("golem_click stuck")                  # avec trace : paquet event
    rows = [r for r in diag._read_timeline() if r["type"] == "error"]
    assert len(rows) == 2 and rows[0]["logger"] == "recall" and "ValueError" in rows[1]["msg"]
    assert len(built) == 1 and built[0]["type"] == "error"


def test_un_arret_de_reaper_annonce_n_est_pas_un_abort(tmp_path, monkeypatch):
    """Retour golem.fm 2026-09-14 : `reaper down` sans intention se lisait comme un crash. Le site qui
    décide l'arrêt pose `diag.intent` ; le moniteur joint `why` ; pas de paquet `event`."""
    _rack(tmp_path, monkeypatch)
    _Net().install(monkeypatch)
    diag.open_session()
    built = []
    monkeypatch.setattr(diag, "build", lambda kind, **kw: built.append(kw["event_"]) or None)
    import threading
    monkeypatch.setattr(threading, "Thread", lambda target=None, **kw: type("T", (), {"start": lambda s: target()})())
    diag.intent("reaper", "requested")
    assert diag.peek_intent("reaper") == "requested"
    diag.trigger("reaper", state="down", why=diag.peek_intent("reaper"))
    diag.trigger("reaper", state="up", why=diag.peek_intent("reaper", clear=True))
    assert diag.peek_intent("reaper") is None
    assert built == []                                     # annoncé : pas de paquet
    rows = [r for r in diag._read_timeline() if r["type"] == "reaper"]
    assert [(r["state"], r["why"]) for r in rows] == [("down", "requested"), ("up", "requested")]
    diag.trigger("reaper", state="down")                   # NON annoncé : paquet
    assert len(built) == 1 and built[0]["type"] == "reaper"
    # une intention périmée ne compte plus
    diag.intent("reaper", "settings")
    monkeypatch.setattr(diag, "INTENT_TTL_S", 0)
    assert diag.peek_intent("reaper") is None
