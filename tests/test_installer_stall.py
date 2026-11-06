# SPDX-License-Identifier: GPL-3.0-or-later
"""2026-10-24, un testeur Windows : 16 min figé sur « golem itself », relancé — et plus rien ne disait où. La trace de
l'installateur va aussi sur le disque ; une étape muette se voit (`quiet`) et s'arrête (■ Stop this step), Retry la
reprend ; une étape élevée (UAC) ne s'arrête pas d'ici."""
import importlib.util
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server():
    spec = importlib.util.spec_from_file_location("golem_installer_stall", os.path.join(ROOT, "installer", "server.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_trace_va_aussi_sur_le_disque(tmp_path, monkeypatch):
    srv = _server()
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    srv.open_log_file("install")
    srv.log("→ golem's Python packages (pip)", "bridge")
    srv.log("@@progress 1 2", "sounds")                  # un marqueur sans phase : il entre dans la trace
    srv.LOGFILE["f"].close()
    text = open(srv.S["log_file"], encoding="utf-8").read()
    assert os.path.dirname(srv.S["log_file"]) == str(tmp_path)
    assert "[bridge] → golem's Python packages (pip)" in text


def test_une_etape_muette_se_voit_et_s_arrete():
    srv = _server()
    srv.S["running"] = True
    out = {}
    cmd = [sys.executable, "-c", "import time; print('start', flush=True); time.sleep(60)"]
    t = threading.Thread(target=lambda: out.update(rc=srv.run(cmd, "bridge")))
    t.start()
    for _ in range(100):
        if srv.CUR["proc"] is not None and any(e["line"] == "start" for e in srv.S["log"]):
            break
        time.sleep(0.05)
    assert srv.CUR["proc"] is not None and not srv.CUR["elevated"]
    srv.CUR["last"] = time.time() - 200                   # trois minutes et plus sans une ligne
    assert srv.stop_step()["ok"] is True
    t.join(timeout=15)
    assert out["rc"] != 0                                 # l'étape échoue : Retry la reprendra
    assert any("stopped by you after 3 min" in e["line"] for e in srv.S["log"])
    assert srv.CUR["proc"] is None and srv.stop_step()["ok"] is False


def test_une_etape_elevee_ne_s_arrete_pas_d_ici():
    srv = _server()
    srv.S["running"] = True
    cmd = [sys.executable, "-c", "import time; time.sleep(30)", "-Verb RunAs"]   # la marque d'installer/elevate_win.py
    t = threading.Thread(target=lambda: srv.run(cmd, "system"), daemon=True)
    t.start()
    for _ in range(100):
        if srv.CUR["proc"] is not None:
            break
        time.sleep(0.05)
    r = srv.stop_step()
    assert r["ok"] is False and "Windows' permission" in r["error"]
    srv.CUR["proc"].kill()
    t.join(timeout=15)
