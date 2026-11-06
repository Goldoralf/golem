# SPDX-License-Identifier: GPL-3.0-or-later
"""Le pilote ASIO d'une carte est le SIEN, pas un emballage générique (2026-10-10 : guitare sur IN 2, « le patch
ne sonne qu'en IN 1 » — ASIO4ALL perdait la prise IN 2 de la Volt 276 ; le pilote natif rend les deux)."""
import json
import os

from provision import desktop
from bridge import desktop_audio, inputmap

DRIVERS = ["Ableton Move", "ASIO4ALL v2", "Realtek ASIO", "UMC ASIO Driver", "Universal Audio Volt"]
VOLT = {"FriendlyName": "Volt 276", "InstanceId": "TUSBAUDIO_ENUM\\VID_2B5A&PID_0023&KS\\22332039048326"}
UMC = {"FriendlyName": "BEHRINGER UMC 404HD 192k", "InstanceId": "TUSBAUDIO_ENUM\\VID_1397&PID_0509&KS"}


def test_la_volt_est_reconnue_par_son_identite_usb_et_son_pilote_natif_choisi():
    assert desktop.select_asio_driver(DRIVERS, [VOLT]) == ("Universal Audio Volt", 4)
    assert desktop.native_asio_driver(DRIVERS, [VOLT, UMC]) is None           # deux cartes connues : on ne devine pas
    assert desktop.native_asio_driver(DRIVERS, []) is None
    assert desktop.native_asio_driver(["ASIO4ALL v2"], [VOLT]) is None        # natif pas installé : rien à préférer


def test_un_pilote_generique_se_reconnait():
    assert desktop.is_generic_asio("ASIO4ALL v2") and desktop.is_generic_asio("FlexASIO")
    assert not desktop.is_generic_asio("Universal Audio Volt") and not desktop.is_generic_asio("UMC ASIO Driver")


def test_l_alerte_ne_vise_que_le_generique_quand_le_natif_existe(monkeypatch):
    monkeypatch.setattr(desktop_audio.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "present_media", lambda: [VOLT])
    monkeypatch.setattr(desktop_audio, "_NATIVE_CACHE", {"at": 0.0, "val": None})
    cur = {"driver": "ASIO4ALL v2", "drivers": DRIVERS}
    assert desktop_audio.native_driver_advice(cur) == {"native": "Universal Audio Volt", "generic": "ASIO4ALL v2"}
    assert desktop_audio.native_driver_advice({"driver": "Universal Audio Volt", "drivers": DRIVERS}) is None
    monkeypatch.setattr(desktop_audio, "_NATIVE_CACHE", {"at": 0.0, "val": None})
    monkeypatch.setattr(desktop, "present_media", lambda: [])
    assert desktop_audio.native_driver_advice(cur) is None                   # carte débranchée : pas d'alerte


def test_le_pilote_change_les_roles_suivent(tmp_path, monkeypatch):
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    old = {"card": "asio:ASIO4ALL v2", "inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar", "person": "alex"}],
           "outputs": [{"ch": "1-2", "role": "monitors"}], "midi_in": "fcb", "midi_out": "whammy-dt"}
    json.dump(old, open(os.path.join(tmp_path, "asio-ASIO4ALL-v2.json"), "w"))
    assert inputmap.inherit("asio:ASIO4ALL v2", "asio:Universal Audio Volt") is True
    new = json.load(open(os.path.join(tmp_path, "asio-Universal-Audio-Volt.json")))
    assert new["inputs"] == old["inputs"] and new["card"] == "asio:Universal Audio Volt"
    assert new["inherited_from"] == "asio:ASIO4ALL v2"
    assert inputmap.inherit("asio:ASIO4ALL v2", "asio:Universal Audio Volt") is False   # déjà là : jamais écrasée
    assert inputmap.inherit("asio:nope", "asio:other") is False


def test_une_volt_neuve_sous_windows_est_semee_comme_sous_linux(monkeypatch):
    monkeypatch.setattr(inputmap, "_card_channels", lambda device: (2, 2))
    seeded = inputmap._seed("asio:Universal Audio Volt")
    assert [(i["ch"], i["role"]) for i in seeded["inputs"]] == [("1", "guitar"), ("2", "voice")]
