# SPDX-License-Identifier: GPL-3.0-or-later
"""reaper.ini : automute=0 forcé partout (Linux et desktop) ; licence REAPER posée dans le dossier de
ressources que REAPER lit (pas ~/.config/REAPER sous Windows/macOS) ; erreurs de routes_system en anglais."""
import asyncio
import importlib.util
import re
from pathlib import Path

from bridge import routes_system
from provision import desktop

ROOT = Path(__file__).resolve().parents[1]


def _ini_setup():
    spec = importlib.util.spec_from_file_location("reaper_ini_setup", ROOT / "provision/reaper-ini-setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_linux_provisioning_forces_automute_off(tmp_path, monkeypatch):
    m = _ini_setup()
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\nautomute=1\nnorunmute=1\ncsurf_cnt=0\n\n[other]\nx=1\n", encoding="latin-1")
    monkeypatch.setattr(m, "INI", str(ini))
    monkeypatch.setattr(m, "reaper_running", lambda: False)
    monkeypatch.setattr(m, "_read_keys_sources", lambda: (None, None))
    monkeypatch.setattr(m, "keys_name_patterns", lambda *a: ([], ""))
    monkeypatch.setattr(m, "write_keys_sidecar", lambda *a: None)
    monkeypatch.setattr(m, "midi_enable_keys", lambda: ({}, ""))
    monkeypatch.setattr(m, "midi_enable_out", lambda: ({}, ""))
    m.main()
    text = ini.read_text(encoding="latin-1")
    assert "\nautomute=0\n" in text and "automute=1" not in text
    assert "\nnorunmute=0\n" in text
    assert text.index("automute=0") < text.index("[other]")


def test_linux_provisioning_inserts_automute_when_absent(tmp_path, monkeypatch):
    m = _ini_setup()
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\ncsurf_cnt=0\n", encoding="latin-1")
    for name, val in (("INI", str(ini)), ("reaper_running", lambda: False),
                      ("_read_keys_sources", lambda: (None, None)), ("keys_name_patterns", lambda *a: ([], "")),
                      ("write_keys_sidecar", lambda *a: None), ("midi_enable_keys", lambda: ({}, "")),
                      ("midi_enable_out", lambda: ({}, ""))):
        monkeypatch.setattr(m, name, val)
    m.main()
    assert re.search(r"^automute=0$", ini.read_text(encoding="latin-1"), re.M)


def test_desktop_ini_forces_automute_off(tmp_path):
    ini = tmp_path / "reaper.ini"
    ini.write_bytes(b"[reaper]\r\nautomute=1\r\naudio=ASIO\r\n\r\n[other]\r\nx=1\r\n")
    assert desktop.configure_ini(ini)
    text = ini.read_bytes().decode("latin-1")
    assert "automute=0\r\n" in text and "automute=1" not in text
    assert text.index("automute=0") < text.index("[other]")
    assert not desktop.configure_ini(ini)                     # rejouable


def test_desktop_ini_inserts_automute_when_absent(tmp_path):
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\n", encoding="ascii")
    assert desktop.configure_ini(ini)
    assert re.search(r"^automute=0$", ini.read_text(encoding="latin-1"), re.M)


def test_license_goes_to_the_reaper_resource_dir(tmp_path, monkeypatch):
    res = tmp_path / "AppData" / "Roaming" / "REAPER"
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(routes_system.C, "reaper_resource_dir", lambda: str(res))
    from bridge import desktop_reaper
    monkeypatch.setattr(desktop_reaper, "license_state", lambda: "evaluation")
    assert routes_system.reaper_license_status()["present"] is False
    out = asyncio.run(routes_system.reaper_license_set({"license": "SECRET-KEY"}))
    assert out["ok"]
    lic = res / "reaper-license.rk"
    assert lic.read_text() == "SECRET-KEY\n"
    assert routes_system.reaper_license_status()["present"] is True


def test_empty_license_is_refused_in_english():
    out = asyncio.run(routes_system.reaper_license_set({"license": "  "}))
    assert out.status_code == 400 and b"empty license" in out.body


def test_learn_save_without_bindings_is_refused_in_english():
    out = asyncio.run(routes_system.learn_save({"bindings": []}))
    assert out.status_code == 400 and b"no binding learned" in out.body


def test_cards_adopt_unknown_card_is_refused_in_english(monkeypatch):
    from bridge import cards
    monkeypatch.setattr(routes_system.sys, "platform", "linux")
    monkeypatch.setattr(cards, "remember", lambda cid: None)
    out = asyncio.run(routes_system.cards_adopt({"id": "Nope"}))
    assert out.status_code == 404 and b"not connected" in out.body


def test_no_french_error_strings_in_routes_system():
    src = (ROOT / "bridge/routes_system.py").read_text(encoding="utf-8")
    french = [line.strip() for line in src.splitlines()
              if '"error"' in line and re.search(r"[àâçéèêëîïôûùüœ«]", line.split("#", 1)[0])]
    assert french == []


def test_le_peripherique_audio_par_defaut_n_est_plus_la_carte_du_rack_de_dev(monkeypatch):
    # 2026-11-03 : « hw:V276 » était écrit dans le reaper.ini de toute machine neuve (et aucun linux_audio_mode : JACK)
    m = _ini_setup()
    monkeypatch.setattr(m, "card_present", lambda dev: dev == "hw:iTwo")
    monkeypatch.setattr(m, "active_card", lambda: "")
    insert, _ = m.audio_keys({})
    assert insert["alsa_indev"] == "null" and insert["linux_audio_mode"] == "1"   # rien : ALSA muet, jamais V276
    monkeypatch.setattr(m, "active_card", lambda: "iTwo")    # la carte active du bridge (io.json d'abord, puis branchée)
    insert, _ = m.audio_keys({})
    assert insert["alsa_indev"] == insert["alsa_outdev"] == "hw:iTwo"
