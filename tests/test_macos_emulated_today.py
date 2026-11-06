# SPDX-License-Identifier: GPL-3.0-or-later
"""Passe macOS ÉMULÉE (2026-10-10) sur ce qui est arrivé aujourd'hui : recettes de capture, capture « trop chaude »,
identité de carte, patch neuf, relance pendant l'arrêt. Aucun Mac ici : `sys.platform = "darwin"` et des sorties
FABRIQUÉES. Ces tests disent que le CODE prend les branches macOS sans casser — pas que le matériel répond.
Ce qui reste à voir sur une vraie machine est listé dans docs/platforms.md."""
import json
import plistlib
import sys

import pytest

from bridge import cards, desktop_audio, inputmap, plugin_capture as PC, plugin_recipes as R, routes_inputmap
from provision import desktop


@pytest.fixture
def mac(monkeypatch):
    for mod in (sys, PC.sys, R.sys, cards.sys, desktop_audio.sys, inputmap.sys, desktop.sys):
        monkeypatch.setattr(mod, "platform", "darwin")
    import platform
    monkeypatch.setattr(platform, "system", lambda: "Darwin")


def test_la_version_d_un_plugin_se_lit_dans_son_bundle(mac, tmp_path):
    vst3 = tmp_path / "Example Lead Suite.vst3" / "Contents"
    vst3.mkdir(parents=True)
    (vst3 / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "1.1.0", "CFBundleVersion": "110"}))
    assert R.plugin_version(tmp_path / "Example Lead Suite.vst3") == "1.1.0"
    au = tmp_path / "Fortin.component" / "Contents"
    au.mkdir(parents=True)
    (au / "Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": "3.0.1"}))
    assert R.plugin_version(tmp_path / "Fortin.component") == "3.0.1"
    assert R.plugin_version(tmp_path / "absent.vst3") is None


def test_l_os_envoye_a_golem_fm_est_darwin(mac):
    assert R.rack_os() == "darwin"                                     # jamais « macos » (contrat §3)


def test_les_outils_de_capture_sont_cherches_au_bon_endroit(mac, monkeypatch, tmp_path):
    monkeypatch.delenv("GOLEM_NAM_TRAIN", raising=False)
    monkeypatch.setattr(PC.Path, "home", classmethod(lambda cls: tmp_path))
    assert PC.train_home() == tmp_path / "Library" / "Application Support" / "GoleM" / "nam-train"
    assert PC._venv_python(tmp_path / "venv").as_posix().endswith("venv/bin/python")
    env = PC.environment()                                             # rien d'installé : il le DIT
    assert env["ready"] is False and "NAM trainer" in env["missing"][0]


def test_aucune_alerte_de_pilote_asio_sur_mac(mac):
    assert desktop_audio.native_driver_advice({"driver": "ASIO4ALL v2", "drivers": ["ASIO4ALL v2"]}) is None


def test_la_carte_branchee_est_la_carte_du_mode_par_la_cle_usb(mac, monkeypatch, tmp_path):
    (tmp_path / "V276.json").write_text(json.dumps({"id": "V276", "usb": "2b5a:0023", "name": "Universal Audio Volt 276"}))
    monkeypatch.setattr(cards, "CARDS_DIR", str(tmp_path))
    monkeypatch.setattr(cards, "_MAC_USB_CACHE", {"at": 0.0, "val": [("Volt 276", "2b5a:0023")]})
    monkeypatch.setattr(cards, "_mac_usb_devices", lambda: [("Volt 276", "2b5a:0023")])
    monkeypatch.setattr(desktop_audio, "configured_coreaudio_input", lambda: "Volt 276")
    assert inputmap._card_device() == "coreaudio:Volt 276"
    live = {"card": "coreaudio:Volt 276", "inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar"}]}
    monkeypatch.setattr(inputmap, "current", lambda dev=None: live if dev in (None, live["card"]) else {"card": dev, "inputs": []})
    r = routes_inputmap.get_inputmap("V276")
    assert r["same_as_live"] is True and [(i["ch"], i["role"]) for i in r["inputs"]] == [("1", "voice"), ("2", "guitar")]


def test_par_defaut_le_nom_vient_de_ce_que_reaper_a_ouvert(mac, monkeypatch):
    monkeypatch.setattr(cards, "_mac_usb_devices", lambda: [("Volt 276", "2b5a:0023"), ("MPK Mini Mk II", "09e8:0045")])
    monkeypatch.setattr(desktop_audio, "_public_actual", lambda: {"MODE": "CoreAudio", "IDENT_IN": "Volt 276"})
    monkeypatch.setattr(desktop_audio, "configured_coreaudio_input", lambda: desktop_audio.DEFAULT_DEVICE)
    assert cards.usb_of("coreaudio:" + desktop_audio.DEFAULT_DEVICE) == "2b5a:0023"


def test_relancer_pendant_l_arret_attend_aussi_sur_mac(mac, monkeypatch):
    seq = iter([{"stopping": True}, None])
    monkeypatch.setattr(desktop, "bridge_health", lambda port: next(seq, None))
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    assert desktop.wait_stopped(8770) is True


def test_le_banc_de_rendu_ne_copie_que_ce_qui_existe(mac, monkeypatch, tmp_path):
    """Le REAPER séparé reprend licence et caches de plugins de la machine : sur Mac, ceux qui existent."""
    res = tmp_path / "REAPER"
    res.mkdir()
    (res / "reaper-license.rk").write_text("lic")
    (res / "reaper-vstplugins_arm64.ini").write_text("[vstcache]")
    monkeypatch.setattr("provision.desktop.resource_dir", lambda: res)
    bench = PC._bench_dir(tmp_path / "work")
    assert (bench / "reaper-license.rk").is_file() and (bench / "reaper-vstplugins_arm64.ini").is_file()
    # ⚠ PAS d'assertion sur la config audio : le banc écrit `[audioconfig] mode=4` (Windows : pas de carte), que
    # macOS ignore — tools/check-native-nam.py écrit Core Audio dans [REAPER] et ferme un choix de carte modal.
    # Défaut connu (passe macOS du 2026-10-10, docs/platforms.md), pas à figer dans un test.


# ── les corrections de la passe macOS (points 1, 2, 3, 4, 7 de docs/platforms.md §5) ─────────────────
def test_1_le_reaper_des_captures_a_sa_config_core_audio_et_ses_caches(mac, monkeypatch, tmp_path):
    res = tmp_path / "REAPER"
    res.mkdir()
    for f in ("reaper-license.rk", "reaper-vstplugins_arm64.ini", "reaper-auplugins_arm64-bc.ini", "reaper-clap-macos-arm64.ini"):
        (res / f).write_text("x")
    monkeypatch.setattr("provision.desktop.resource_dir", lambda: res)
    bench = PC._bench_dir(tmp_path / "work")
    ini = (bench / "reaper.ini").read_text()
    assert "coreaudioindevnew=<default system devices>" in ini and "coreaudiooutdevnew=<default system devices>" in ini
    assert "[audioconfig]" not in ini                                   # le réglage WINDOWS n'est plus écrit
    for f in ("reaper-auplugins_arm64-bc.ini", "reaper-clap-macos-arm64.ini", "reaper-vstplugins_arm64.ini"):
        assert (bench / f).is_file(), f                                 # aucun rescan des plugins à chaque capture


def test_1_windows_garde_son_banc_sans_carte(monkeypatch, tmp_path):
    monkeypatch.setattr(PC.sys, "platform", "win32")
    res = tmp_path / "REAPER"
    res.mkdir()
    monkeypatch.setattr("provision.desktop.resource_dir", lambda: res)
    assert "[audioconfig]\nmode=4" in (PC._bench_dir(tmp_path / "w") / "reaper.ini").read_text()


def test_1_la_boite_audio_est_fermee_par_son_pid(mac, monkeypatch):
    import subprocess
    seen = []

    class Out:
        stdout = "dismissed"
    monkeypatch.setattr(subprocess, "run", lambda args, **k: seen.append(args) or Out())
    assert PC._mac_dismiss_audio_dialog(4242) is True
    assert seen[0][0] == "osascript" and "unix id is 4242" in seen[0][2] and 'click button "No"' in seen[0][2]


def test_2_le_bouton_stop_ferme_reaper_par_l_apple_event(mac, monkeypatch):
    import threading
    from bridge import routes_dev
    import provision.desktop_window as DW
    calls = []
    monkeypatch.setattr(desktop, "close_app_windows", lambda: 1)
    monkeypatch.setattr(desktop, "_backend_pids", lambda: set())
    running = iter([True, True, False])
    monkeypatch.setattr(desktop, "reaper_running", lambda: next(running, False))
    monkeypatch.setattr(desktop, "reaper_binary", lambda: (_ for _ in ()).throw(AssertionError("le binaire ne doit plus servir")))
    monkeypatch.setattr(DW, "request_reaper_close", lambda pids: calls.append("apple-event") or 1)
    monkeypatch.setattr(PC, "stop_benches", lambda: calls.append("benches") or 1)
    monkeypatch.setattr("bridge.desktop_audio.save_project_in_place", lambda: None)
    monkeypatch.setattr(routes_dev.time, "sleep", lambda s: None)
    monkeypatch.setattr(routes_dev.os, "_exit", lambda code: calls.append(("exit", code)))
    monkeypatch.setattr("bridge.diag.shutdown_report", lambda reason: None)

    class Now(threading.Thread):                                        # le fil d'arrêt, exécuté sur place
        def start(self): self.run()
    monkeypatch.setattr(threading, "Thread", Now)
    routes_dev._ui_quit_desktop(True)
    assert calls == ["benches", "apple-event", ("exit", 0)]             # bancs d'abord, REAPER poliment, puis le bridge


def test_3_un_mac_par_defaut_qui_joue_est_branche(mac, monkeypatch, tmp_path):
    from bridge import rigstatus, modes
    monkeypatch.setattr(modes, "list_modes", lambda: [])
    monkeypatch.setattr(inputmap, "_card_device", lambda: "coreaudio:" + desktop_audio.DEFAULT_DEVICE)
    monkeypatch.setattr(cards, "connected", lambda: [{"index": 0, "id": "Volt 276", "name": "Volt 276"}])
    monkeypatch.setattr(cards, "present_usb_ids", lambda: set())
    monkeypatch.setattr(cards, "registry", lambda: [])
    monkeypatch.setattr(inputmap, "current", lambda dev=None: {"card": dev, "inputs": [], "outputs": []})
    doc = rigstatus.cards_doc()
    active = next(c for c in doc if c.get("active"))
    assert active["connected"] is True


def test_4_les_cartes_du_registre_sont_presentes_par_leur_cle_usb(mac, monkeypatch):
    monkeypatch.setattr(cards, "_mac_usb_devices", lambda: [("Volt 276", "2b5a:0023"), ("MPK Mini Mk II", "09e8:0045")])
    assert cards.present_usb_ids() == {"2b5a:0023", "09e8:0045"}


def test_7_la_version_se_lit_meme_si_reaper_nomme_le_binaire_interieur(mac, tmp_path):
    b = tmp_path / "Example Lead Suite.vst3" / "Contents"
    (b / "MacOS").mkdir(parents=True)
    (b / "MacOS" / "Example Lead Suite").write_text("bin")
    (b / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "1.1.0"}))
    assert R.plugin_version(b / "MacOS" / "Example Lead Suite") == "1.1.0"


# ── point 5 : un REAPER de banc (capture, recette) n'est pas le REAPER principal — Windows comme Mac ────────────
@pytest.mark.parametrize("os_name", ["darwin", "win32"])
def test_5_un_reaper_de_banc_ne_compte_pas(monkeypatch, tmp_path, os_name):
    monkeypatch.setattr(desktop.sys, "platform", os_name)
    monkeypatch.setattr(PC, "bench_pids_file", lambda: tmp_path / "bench.json")
    monkeypatch.setattr(desktop, "reaper_pids", lambda: {100, 200})
    PC._bench_register(200, True)
    assert desktop.bench_reaper_pids() == {200}
    assert desktop.reaper_running() is True                            # le principal (100) tourne
    monkeypatch.setattr(desktop, "reaper_pids", lambda: {200})
    assert desktop.reaper_running() is False                           # seul le banc : « REAPER fermé »
    PC._bench_register(200, False)
    assert desktop.bench_reaper_pids() == set()


def test_5_tasklist_est_lu_par_pid(monkeypatch):
    import subprocess
    monkeypatch.setattr(desktop.sys, "platform", "win32")

    class R:
        stdout = ('"reaper.exe","44744","Console","1","812 000 Ko"\r\n'
                  '"reaper.exe","48940","Console","1","300 000 Ko"\r\n').encode("ascii")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert desktop.reaper_pids() == {44744, 48940}


def test_5_arreter_les_bancs_annule_la_capture_et_desinscrit(monkeypatch, tmp_path):
    monkeypatch.setattr(PC, "bench_pids_file", lambda: tmp_path / "bench.json")

    class P:
        pid = 4242
        def poll(self): return None
        def terminate(self): self.done = True
        def wait(self, timeout=None): return 0
    p = P()
    PC._bench_register(p.pid, True)
    monkeypatch.setattr(PC, "_procs", {p})
    monkeypatch.setattr(PC, "_job", {"state": "train"})
    assert PC.stop_benches() == 1
    assert p.done and PC.status()["state"] == "cancelling"
    assert desktop.bench_reaper_pids() == set()
    PC._cancel.clear()
