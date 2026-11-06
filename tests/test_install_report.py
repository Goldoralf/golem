# SPDX-License-Identifier: GPL-3.0-or-later
"""Le rapport d'échec de l'installateur (installer/report.py, docs/diagnostics.md §7.1, lot D2) : rien ne part sans le
clic, rien de personnel dans le paquet, une signature qui ne dépend pas de la machine."""
import getpass
import hashlib
import importlib.util
import json
import os
import socket
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _report():
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    try:
        spec = importlib.util.spec_from_file_location("golem_install_report", os.path.join(ROOT, "installer", "report.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path.pop(0)


R = _report()
S = R._scrub_module(ROOT)
HOME = os.path.expanduser("~")
LAN = "192.168.1.42"
KEY = "gmt_typed_key_0123"
PW = "hunter2-pass"


def _state(tmp_path, lines):
    log = tmp_path / "golem-install.log"
    log.write_text("\n".join(f"10:00:00 [{s}] {t}" for s, t in lines), encoding="utf-8")
    return {"src": ROOT, "dir": str(tmp_path / "golem"), "running": False, "dry": False, "log_file": str(log),
            "packs": ["di", "piano"], "engine": "reaper", "instrument": "bass", "platform_name": "linux",
            "privilege": "sudo",
            "steps": [{"id": "source", "state": "ok", "secs": 4, "rc": 0}, {"id": "system", "state": "fail", "secs": 80, "rc": 100}],
            "log": [{"step": s, "line": t} for s, t in lines], "install": {"phases": []}}


def _unzip(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_le_paquet_n_emporte_rien_de_personnel(tmp_path):
    user, host = getpass.getuser(), socket.gethostname()
    lines = [("system", f"$ apt-get install in {HOME}/golem by {user}@{host}"),
             ("system", f"golem.fm key {KEY} from {LAN}"),
             ("system", f"✗ E: Unable to locate package libsfizz1 ({tmp_path}/golem/provision)"),
             ("system", "✗ step « system » failed (exit 100) — fix the cause and tap Retry")]
    b = R.build(_state(tmp_path, lines), "install", str(tmp_path / "out"), secrets=[PW, KEY],
                checks=[{"id": "ram", "ok": True, "blocking": False, "detail": f"{user} has 8 GB"}])
    files = _unzip(b["path"])
    assert set(files) == {"golem-report.json", "report.json", "logs/install.log"}
    blob = b"".join(files.values()).decode("utf-8")
    for leak in (KEY, PW, LAN, HOME, str(tmp_path)) + ((user,) if len(user) >= 3 else ()) + ((host,) if len(host) >= 3 else ()):
        assert leak not in blob, leak
    man = json.loads(files["golem-report.json"])
    assert man["golem_report"] == 2 and man["kind"] == "install"
    assert all(hashlib.sha256(files[n]).hexdigest() == h for n, h in man["files"].items())
    rep = json.loads(files["report.json"])
    assert rep["checks"] == [{"id": "ram", "ok": True, "blocking": False}]          # le détail ne part pas
    ins = rep["install"]
    assert ins["failed_step"] == "system" and ins["rc"] == 100 and ins["instrument"] == "bass"
    # la VRAIE erreur, pas le résumé de l'installateur ; golem.fm recalcule la signature à partir de sig_src
    assert ins["sig_src"].startswith("✗ E: Unable to locate package libsfizz#")
    assert ins["sig"] == hashlib.sha256(ins["sig_src"].encode()).hexdigest()[:12]


def test_la_signature_ne_depend_pas_de_la_machine():
    a = S.normalize(r"12:00:01 [system] ✗ C:\Users\Ann\AppData\x.exe returned 0x80070005 after 31 s")
    b = S.normalize(r"09:13:55 [system] ✗ C:\Users\Bob\Temp\x.exe returned 0x80004005 after 2 s")
    assert a == b == "✗ x.exe returned * after # s"
    assert S.sig(a) != S.sig(S.normalize("✗ y.exe returned 0x1 after 2 s"))


def test_rien_ne_part_sans_echec_et_le_dry_ne_part_jamais(monkeypatch, tmp_path):
    if sys.platform != "linux":
        pytest.skip("installateur apt réservé à Linux")
    spec = importlib.util.spec_from_file_location("golem_installer", os.path.join(ROOT, "installer", "server.py"))
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    sent = []
    monkeypatch.setattr(srv.RP, "send", lambda *a, **k: sent.append(a) or {"ok": True, "code": "R7K2Q"})
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    srv.S.update(dry=True, error="system failed (exit 3)", src=ROOT, dir=str(tmp_path / "g"))
    srv.send_report("install")
    assert srv.S["report"]["state"] == "dry" and not sent and os.path.isfile(srv.S["report"]["path"])
    srv.S.update(dry=False)
    srv.send_report("install")
    assert srv.S["report"] == {"state": "sent", "code": "R7K2Q", "path": srv.S["report"]["path"], "error": None}
    assert len(sent) == 1


def test_l_adresse_de_production_est_celle_du_bridge():
    src = open(os.path.join(ROOT, "bridge", "routes_content.py"), encoding="utf-8").read()
    assert f'DEFAULT_SERVER = "{R.PROD_URL}"' in src
