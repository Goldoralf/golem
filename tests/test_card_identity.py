# SPDX-License-Identifier: GPL-3.0-or-later
"""La même carte sous deux noms (docs/returns.md, « l'identité d'une carte reste par système ») : `hw:V276` sous Linux,
`asio:Universal Audio Volt` sous Windows. La clé USB est la passerelle. Né du 2026-10-10 : le mode « studio » déclarait
`hw:V276`, et le Designer préparait un patch guitare neuf pour la carte Linux (guitare sur 1) alors que le moteur résout
sur la carte branchée (guitare sur 2)."""
import json

from bridge import cards


def _registry(monkeypatch, tmp_path):
    (tmp_path / "V276.json").write_text(json.dumps({"id": "V276", "usb": "2B5A:0023", "name": "Volt 276"}))
    (tmp_path / "XR18.json").write_text(json.dumps({"id": "XR18", "usb": "1397:00d4", "name": "XR18"}))
    monkeypatch.setattr(cards, "CARDS_DIR", str(tmp_path))


def test_la_cle_usb_relie_le_nom_linux_et_le_pilote_windows(monkeypatch, tmp_path):
    _registry(monkeypatch, tmp_path)
    assert cards.usb_of("hw:V276") == "2b5a:0023"
    assert cards.usb_of("asio:Universal Audio Volt") == "2b5a:0023"
    assert cards.same_card("hw:V276", "asio:Universal Audio Volt")


def test_un_pilote_generique_ou_une_autre_carte_ne_correspond_pas(monkeypatch, tmp_path):
    _registry(monkeypatch, tmp_path)
    assert cards.usb_of("asio:ASIO4ALL v2") is None                    # un emballage n'est l'identité de rien
    assert not cards.same_card("hw:V276", "asio:ASIO4ALL v2")
    assert not cards.same_card("hw:XR18", "asio:Universal Audio Volt")
    assert not cards.same_card("hw:inconnue", "asio:Universal Audio Volt")
    assert cards.same_card("hw:V276", "hw:V276") and not cards.same_card("", "hw:V276")


def test_la_route_dit_que_la_carte_du_mode_est_la_carte_branchee(monkeypatch, tmp_path):
    from bridge import inputmap, routes_inputmap
    _registry(monkeypatch, tmp_path)
    live = {"card": "asio:Universal Audio Volt", "inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar"}]}
    monkeypatch.setattr(inputmap, "_card_device", lambda: "asio:Universal Audio Volt")
    monkeypatch.setattr(inputmap, "current", lambda dev=None: live if dev in (None, live["card"]) else {"card": dev, "inputs": [{"ch": "1", "role": "guitar"}]})
    r = routes_inputmap.get_inputmap("V276")
    assert r["same_as_live"] is True and r["card"] == "asio:Universal Audio Volt"
    assert [(i["ch"], i["role"]) for i in r["inputs"]] == [("1", "voice"), ("2", "guitar")]
    r = routes_inputmap.get_inputmap("XR18")                          # une autre carte : son propre patch, comme avant
    assert "same_as_live" not in r and r["card"] == "hw:XR18"


# ── macOS (NON VÉRIFIÉ sur un Mac : sorties de system_profiler FABRIQUÉES, deux formes possibles) ──────────────
OLD_SP = {"SPUSBDataType": [{"_name": "USB 3.1 Bus", "_items": [
    {"_name": "Volt 276", "vendor_id": "0x2b5a  (Universal Audio)", "product_id": "0x0023", "serial_num": "x"},
    {"_name": "MPK Mini Mk II", "vendor_id": "0x09e8", "product_id": "0x0045"}]}]}
NEW_SP = {"SPUSBHostDataType": [{"_name": "USB31Bus", "_items": [
    {"_name": "Volt 276", "USBDeviceKeyVendorID": 11098, "USBDeviceKeyProductID": 35}]}]}


def _mac(monkeypatch, tmp_path, outputs):
    import subprocess
    _registry(monkeypatch, tmp_path)
    monkeypatch.setattr(cards.sys, "platform", "darwin")
    monkeypatch.setattr(cards, "_MAC_USB_CACHE", {"at": 0.0, "val": None})

    class R:
        def __init__(self, out): self.stdout = out
    monkeypatch.setattr(subprocess, "run", lambda args, **k: R(json.dumps(outputs.get(args[1], {}))))


def test_mac_la_volt_en_core_audio_est_la_meme_carte(monkeypatch, tmp_path):
    _mac(monkeypatch, tmp_path, {"SPUSBDataType": OLD_SP})
    assert cards.usb_of("coreaudio:Volt 276") == "2b5a:0023"
    assert cards.same_card("hw:V276", "coreaudio:Volt 276")
    assert not cards.same_card("hw:XR18", "coreaudio:Volt 276")


def test_mac_la_forme_recente_de_system_profiler_aussi(monkeypatch, tmp_path):
    _mac(monkeypatch, tmp_path, {"SPUSBHostDataType": NEW_SP})          # identifiants en ENTIERS décimaux
    assert cards.usb_of("coreaudio:Volt 276") == "2b5a:0023"


def test_mac_un_nom_ambigu_ou_inconnu_ne_devine_rien(monkeypatch, tmp_path):
    two = {"SPUSBDataType": [{"_items": [{"_name": "Volt 276", "vendor_id": "0x2b5a", "product_id": "0x0023"},
                                          {"_name": "Volt 476", "vendor_id": "0x2b5a", "product_id": "0x0025"}]}]}
    _mac(monkeypatch, tmp_path, two)
    assert cards.usb_of("coreaudio:Volt") is None                        # deux appareils : on ne choisit pas
    assert cards.usb_of("coreaudio:MacBook Pro Microphone") is None
    assert cards._hexid("2b5a") is None and cards._hexid(11098) == "2b5a" and cards._hexid("0x0023") == "0023"
