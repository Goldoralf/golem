# SPDX-License-Identifier: GPL-3.0-or-later
"""Le setup desktop préserve la configuration REAPER existante."""
from provision import desktop


def test_configure_ini_preserves_audio_and_existing_surfaces(tmp_path):
    ini = tmp_path / "reaper.ini"
    ini.write_bytes(b"[reaper]\r\naudio=ASIO\r\ncsurf_0=Other\r\ncsurf_cnt=1\r\n\r\n[other]\r\nx=1\r\n")
    assert desktop.configure_ini(ini)
    text = ini.read_bytes().decode("latin-1")
    assert "audio=ASIO\r\n" in text
    assert "csurf_0=Other\r\n" in text
    assert 'csurf_1=OSC "golem"' in text
    assert "csurf_cnt=2\r\n" in text
    assert "norunmute=0\r\n" in text
    assert "[other]\r\nx=1" in text
    assert ini.with_suffix(".ini.bak").exists()
    assert not desktop.configure_ini(ini)


def test_copy_resources_keeps_a_user_startup_backup(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "RUNTIME_DIR", str(tmp_path / "runtime"))
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "__startup.lua").write_text("-- user script\n", encoding="utf-8")
    desktop.copy_resources(tmp_path)
    assert (scripts / "__startup.golem-user.lua").read_text(encoding="utf-8") == "-- user script\n"
    assert "__startup.golem-user.lua" in (scripts / "__startup.lua").read_text(encoding="utf-8")
    assert (scripts / "golem/__startup.lua").is_file()
    assert (tmp_path / "Effects/golem").is_dir()
    assert (tmp_path / "OSC/golem.ReaperOSC").is_file()
    assert (tmp_path / "golem-root.txt").read_text(encoding="utf-8").strip() == str(desktop.ROOT)
    assert (tmp_path / "golem-runtime.txt").read_text(encoding="utf-8").strip() == str(tmp_path / "runtime")


def test_first_run_seeds_asio_but_preserves_existing_audio(tmp_path):
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\n", encoding="ascii")
    assert desktop.configure_ini(ini, ("UMC ASIO Driver", 4))
    content = ini.read_text(encoding="latin-1")
    assert "[audioconfig]\nmode=3\nasio_driver=4\n" in content
    assert 'asio_driver_name="UMC ASIO Driver"' in content
    assert not desktop.configure_ini(ini, ("UMC ASIO Driver", 4))
    ini.write_text("[reaper]\n\n[audioconfig]\nmode=4\nwasapi_mode=0\n", encoding="ascii")
    desktop.configure_ini(ini, ("UMC ASIO Driver", 4))
    assert "mode=4\nwasapi_mode=0" in ini.read_text(encoding="latin-1")
    assert "asio_driver_name" not in ini.read_text(encoding="latin-1")


def test_known_usb_asio_is_selected_without_guessing_other_hardware():
    drivers = ["Ableton Move", "Ableton Push", "ASIO4ALL v2", "Realtek ASIO", "UMC ASIO Driver"]
    media = [{"FriendlyName": "BEHRINGER UMC 404HD 192k", "InstanceId": "TUSBAUDIO_ENUM\\VID_1397"},
             {"FriendlyName": "Realtek(R) Audio", "InstanceId": "HDAUDIO\\FUNC_01"}]
    media[0]["InstanceId"] += "&PID_0509&KS"
    assert desktop.select_asio_driver(drivers, media) == ("UMC ASIO Driver", 4)
    assert desktop.select_asio_driver(drivers, [
        {"FriendlyName": "BEHRINGER UMC 404HD 192k", "InstanceId": "USB\\VID_1397&PID_0001"}]) is None
    assert desktop.select_asio_driver(["Acme Interface A ASIO"], [
        {"FriendlyName": "Acme Interface B", "InstanceId": "USB\\VID_9999"}]) is None
    assert desktop.select_asio_driver(drivers, [], "UMC ASIO Driver") == ("UMC ASIO Driver", 4)


def test_desktop_launcher_resumes_auto_saved_session(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(C, "reaper_resource_dir", lambda: str(tmp_path / "resources"))
    project = tmp_path / "sets" / "golem-session-1.rpp"
    project.parent.mkdir()
    project.write_text("<REAPER_PROJECT", encoding="ascii")
    desktop.remember_project(project)
    assert desktop.desktop_project() == project
    outside = tmp_path / "outside.rpp"
    outside.write_text("<REAPER_PROJECT", encoding="ascii")
    import pytest
    with pytest.raises(ValueError, match="outside the sets folder"):
        desktop.remember_project(outside)


def test_sans_carte_reconnue_le_setup_pose_un_reglage_neutre_et_rien_de_plus(tmp_path):
    """Windows vierge (2026-10-01) : sans AUCUN réglage audio, REAPER ouvre une boîte modale à
    chaque lancement et __startup.lua attend qu'on y réponde — GoleM démarre inerte. Un `mode=`
    suffit ; Dummy Audio n'ouvre aucune entrée. Un réglage existant appartient à l'utilisateur."""
    ini = tmp_path / "reaper.ini"
    ini.write_bytes(b"[reaper]\r\ncsurf_cnt=0\r\n")
    assert desktop.configure_ini(ini, None, dummy_audio=True)
    text = ini.read_bytes().decode("latin-1")
    assert "[audioconfig]\r\nmode=4\r\n" in text
    assert not desktop.configure_ini(ini, None, dummy_audio=True)           # rejouable
    # une carte choisie par l'utilisateur n'est JAMAIS remplacée par le réglage neutre
    ini.write_bytes(b"[reaper]\r\n[audioconfig]\r\nmode=3\r\nasio_driver=1\r\n")
    desktop.configure_ini(ini, None, dummy_audio=True)
    text = ini.read_bytes().decode("latin-1")
    assert "mode=3" in text and "mode=4" not in text
    # ni par une carte reconnue : le pilote connu ne sert qu'à un REAPER sans réglage
    desktop.configure_ini(ini, ("UMC ASIO Driver", 4), dummy_audio=True)
    assert "asio_driver=1" in ini.read_bytes().decode("latin-1")


def test_la_verification_de_version_au_demarrage_est_coupee_sauf_choix_de_l_utilisateur(tmp_path):
    """Sur un Windows vierge, un REAPER épinglé qui n'est plus le dernier ouvrait au premier lancement
    une boîte MODALE « New Version Notification » : __startup.lua bloqué, GoleM sans moteur (VM,
    2026-10-02). Le setup coupe la vérification — mais une clé déjà posée appartient à l'utilisateur."""
    fresh = tmp_path / "fresh.ini"
    fresh.write_text("[reaper]\nfoo=1\n")
    desktop.configure_ini(fresh)
    assert "verchk=0" in fresh.read_text().splitlines()
    chosen = tmp_path / "chosen.ini"
    chosen.write_text("[reaper]\nverchk=1\n")
    desktop.configure_ini(chosen)
    assert "verchk=1" in chosen.read_text().splitlines() and "verchk=0" not in chosen.read_text()


def test_configure_ini_seeds_the_system_coreaudio_devices_on_macos(tmp_path):
    # profil REAPER neuf sous macOS : sans périphérique, « REAPER Preferences » bloque __startup.lua (2026-11-04)
    ini = tmp_path / "reaper.ini"
    ini.write_bytes(b"[reaper]\n")
    assert desktop.configure_ini(ini, coreaudio=("Microphone MacBook Air", "Haut-parleurs MacBook Air"))
    text = ini.read_text(encoding="latin-1")
    for line in ("coreaudioindevnew=Microphone MacBook Air", "coreaudiooutdevnew=Haut-parleurs MacBook Air",
                 "coreaudiosrate=48000", "coreaudiosrateuse=1", "coreaudiobs=256", "coreaudiobsuse=1"):
        assert line + "\n" in text
    assert "[audioconfig]" not in text
    assert not desktop.configure_ini(ini, coreaudio=("Volt 276", "Volt 276"))     # rejouable


def test_configure_ini_keeps_a_coreaudio_device_the_user_chose(tmp_path):
    ini = tmp_path / "reaper.ini"
    ini.write_bytes(b"[reaper]\ncoreaudioindevnew=Volt 276\ncoreaudiobs=128\n")
    desktop.configure_ini(ini, coreaudio=("Microphone MacBook Air", "Haut-parleurs MacBook Air"))
    text = ini.read_text(encoding="latin-1")
    assert "coreaudioindevnew=Volt 276\n" in text and "coreaudiobs=128\n" in text
    assert "coreaudiooutdevnew" not in text


def test_the_seeded_coreaudio_devices_are_the_system_defaults_by_name(monkeypatch):
    # « <default system devices> » ferait rapporter « CoreAudio Default » : la carte perdrait son rôle d'entrée
    from subprocess import CompletedProcess
    report = {"SPAudioDataType": [{"_name": "coreaudio_device", "_items": [
        {"_name": "Microphone de «\u00a0iPhone\u00a0»", "coreaudio_device_input": 1},
        {"_name": "Microphone MacBook Air", "coreaudio_default_audio_input_device": "spaudio_yes"},
        {"_name": "Haut-parleurs MacBook Air", "coreaudio_default_audio_output_device": "spaudio_yes"}]}]}
    import json
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda *a, **k: CompletedProcess(a, 0, stdout=json.dumps(report), stderr=""))
    assert desktop.coreaudio_default_devices() == ("Microphone MacBook Air", "Haut-parleurs MacBook Air")

    def broken(*a, **k):
        raise OSError("no system_profiler")
    monkeypatch.setattr(desktop.subprocess, "run", broken)
    assert desktop.coreaudio_default_devices() == (desktop.COREAUDIO_DEFAULT,) * 2
