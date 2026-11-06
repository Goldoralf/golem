# SPDX-License-Identifier: GPL-3.0-or-later
"""Calibration ▸ Drums, côté bridge (docs/calibration.md, addendum 2026-09-23) — lot D1.

Ce que ces tests gardent : la piste d'écoute ne se demande qu'avec le nom EXACT que Reaper donne au
device (« hw:Nitro », lu dans /proc/asound/cards), jamais par heuristique ; un module débranché est
un 409 qui le dit ; le flux `live` ne ment pas quand rien n'a encore été publié.
Les handlers sont appelés directement (pas de TestClient : httpx n'est pas une dépendance du rack).
"""
import asyncio
import json

from bridge import routes_dev as R


def _body(resp):
    """Un handler rend un dict (200) ou une JSONResponse : on lit les deux pareil."""
    if isinstance(resp, dict):
        return 200, resp
    return resp.status_code, json.loads(resp.body)


def test_start_resout_le_port_lie_vers_le_nom_reaper_du_device(monkeypatch):
    from bridge import inputmap, vital
    sent = []
    monkeypatch.setattr(inputmap, "usb_ports", lambda: [{"port": 1, "device": "Alesis Nitro", "role": "drums"}])
    monkeypatch.setattr(vital, "_hw_of", lambda name: "hw:Nitro" if name == "Alesis Nitro" else None)
    monkeypatch.setattr(R, "write_command", lambda cmd: (sent.append(cmd), 7)[1])
    code, d = _body(asyncio.run(R.drumlearn_start({"port": 1})))
    assert code == 200 and d == {"ok": True, "device": "Alesis Nitro", "dev": "hw:Nitro", "seq": 7}
    assert sent == [{"action": "drumlearn", "on": True, "dev": "hw:Nitro"}]


def test_un_module_debranche_est_un_409_qui_le_dit_et_rien_ne_part(monkeypatch):
    from bridge import vital
    sent = []
    monkeypatch.setattr(vital, "_hw_of", lambda name: None)
    monkeypatch.setattr(R, "write_command", lambda cmd: (sent.append(cmd), 1)[1])
    code, d = _body(asyncio.run(R.drumlearn_start({"device": "Alesis Nitro"})))
    assert code == 409 and "not plugged in" in d["error"] and sent == []
    assert _body(asyncio.run(R.drumlearn_start({})))[0] == 400


def test_stop_et_live(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(R, "write_command", lambda cmd: (sent.append(cmd), 2)[1])
    assert asyncio.run(R.drumlearn_stop())["ok"] is True
    assert sent == [{"action": "drumlearn", "on": False}]
    monkeypatch.setattr(R, "DRUMLEARN_LIVE", str(tmp_path / "none.json"))
    assert R.drumlearn_live() == {"on": False, "dev": None, "seq": 0, "clock": 0, "events": [], "err": None}
    (tmp_path / "live.json").write_text(json.dumps({"on": True, "dev": "hw:Nitro", "seq": 3, "clock": 900,
                                                    "events": [{"k": 1, "n": 42, "v": 102, "c": 9, "t": 1.0}]}))
    monkeypatch.setattr(R, "DRUMLEARN_LIVE", str(tmp_path / "live.json"))
    d = R.drumlearn_live()
    assert d["on"] is True and d["events"][0]["n"] == 42
