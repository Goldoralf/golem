# SPDX-License-Identifier: GPL-3.0-or-later
"""Un clavier, UN profil (2026-10-03) : le MPK avait 09e8-0045.json (Linux, VID:PID) et MPK_Mini_Mk_II.json
(Windows, faute de VID:PID). Le plus récent l'emporte, rangé sous le VID:PID, et le doublon disparaît."""
import json

from bridge import controllers as K, desktop_midi


def _write(d, name, prof):
    (d / name).write_text(json.dumps(prof), encoding="utf-8")


def test_le_plus_recent_gagne_sous_le_vid_pid_et_le_doublon_disparait(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "DIR", str(tmp_path))
    _write(tmp_path, "09e8-0045.json", {"usb": "09e8:0045", "name": "AKAI MPK Mini Mk II",
                                        "keys": {"lo": 48}, "calibrated": "2026-07-26 15:56"})
    _write(tmp_path, "MPK_Mini_Mk_II.json", {"usb": "", "name": "MPK Mini Mk II",
                                             "keys": {"lo": 48, "hi": 72}, "calibrated": "2026-10-03 21:05"})
    prof = K.consolidate("09e8:0045", "MPK Mini Mk II")
    assert prof["keys"]["hi"] == 72 and prof["usb"] == "09e8:0045"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["09e8-0045.json"]
    assert K.load("09e8:0045", "AKAI MPK Mini Mk II")["calibrated"] == "2026-10-03 21:05"   # vu depuis Linux


def test_un_autre_appareil_n_est_jamais_fusionne(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "DIR", str(tmp_path))
    _write(tmp_path, "09e8-0045.json", {"usb": "09e8:0045", "name": "MPK Mini Mk II", "calibrated": "1"})
    _write(tmp_path, "1235-0032.json", {"usb": "1235:0032", "name": "Launchkey Mini", "calibrated": "2"})
    K.consolidate("09e8:0045", "MPK Mini Mk II")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["09e8-0045.json", "1235-0032.json"]


def test_windows_lit_le_vid_pid_par_le_nom_du_peripherique(monkeypatch):
    import subprocess
    monkeypatch.setattr(desktop_midi.sys, "platform", "win32")
    monkeypatch.setattr(desktop_midi, "_USB_IDS", {"key": None, "val": {}})
    out = ("Volt 276\tUSB\\VID_2B5A&PID_0023\\22332039048326\r\n"
           "MPK Mini Mk II\tUSB\\VID_09E8&PID_0045&MI_01\\6&12FA9B86&3&0001\r\n").encode("utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": out})())
    ids = desktop_midi._REAL_USB_IDS(["MPK Mini Mk II"])          # la vraie fonction, sortie simulée
    assert ids["mpk mini mk ii"] == "09e8:0045" and ids["volt 276"] == "2b5a:0023"
