# SPDX-License-Identifier: GPL-3.0-or-later
"""Le registre des appareils MIDI connus — « connu ≠ branché » (bridge/devices.py, docs/gear-registry.md
addendum 2026-09-23). Ce que ces tests gardent : la migration ne perd rien (un binding par prise devient
un appareil ; un profil calibré est un appareil) ; le rang usbN est DÉRIVÉ de la présence ; un appareil
connu se ré-identifie par VID:PID quand on le revoit ; seul `forget` retire une entrée."""
import json
import os

import pytest

from bridge import config as C, devices as D


@pytest.fixture
def rack(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(D, "_usb_list", lambda: [])
    monkeypatch.setattr(D, "_cards", lambda: [])
    return tmp_path


def _present(monkeypatch, *names, cards=None):
    monkeypatch.setattr(D, "_usb_list", lambda: [{"name": n, "kind": "midi"} for n in names])
    monkeypatch.setattr(D, "_cards", lambda: cards or [])


def test_la_migration_garde_le_binding_et_les_profils_sans_rien_effacer(rack, monkeypatch):
    json.dump({"usb1": {"enabled": True, "device": "MPK Mini Mk II", "kind": "midi", "roles": ["keys", "pads"],
                        "person": "alex", "nth": 2}}, open(rack / "soundcard.json", "w"))
    os.makedirs(rack / "controllers")
    json.dump({"usb": "1c75:0288", "name": "Arturia KeyStep", "calibrated": "2026-08-01 10:00"},
              open(rack / "controllers" / "1c75-0288.json", "w"))
    devs = D.known()
    assert set(e["name"] for e in devs.values()) == {"MPK Mini Mk II", "Arturia KeyStep"}
    akai = next(e for e in devs.values() if e["name"] == "MPK Mini Mk II")
    assert akai["roles"] == ["keys", "pads"] and akai["person"] == "alex" and akai["nth"] == 2
    assert devs["1c75:0288"]["roles"] == ["keys", "pads"] and devs["1c75:0288"]["first_seen"] == "2026-08-01 10:00"
    assert os.path.exists(rack / "soundcard.json.migrated") and not os.path.exists(rack / "soundcard.json")
    assert D.known() == devs                                  # idempotent : la 2e lecture ne migre pas


def test_le_rang_usb_est_derive_de_la_presence(rack, monkeypatch):
    json.dump({"usb1": {"enabled": True, "device": "MPK Mini Mk II", "kind": "midi", "roles": ["keys", "pads"]}},
              open(rack / "soundcard.json", "w"))
    assert D.bindings() == {}                                 # connu, mais rien de branché
    _present(monkeypatch, "Alesis Nitro", "AKAI MPK Mini Mk II")
    b = D.bindings()
    assert list(b) == ["usb2"] and b["usb2"]["device"] == "MPK Mini Mk II" and b["usb2"]["roles"] == ["keys", "pads"]
    lst = D.listing()
    assert [(d["name"], d["known"], d["connected"], d["port"]) for d in lst] == \
        [("Alesis Nitro", False, True, 1), ("MPK Mini Mk II", True, True, 2)]


def test_un_connu_par_nom_apprend_son_vid_pid_quand_on_le_revoit(rack, monkeypatch):
    json.dump({"usb1": {"enabled": True, "device": "MPK Mini Mk II", "kind": "midi", "roles": ["keys"]}},
              open(rack / "soundcard.json", "w"))
    assert list(D.known()) == ["name:mpk-mini-mk-ii"]
    _present(monkeypatch, "AKAI MPK Mini Mk II",
             cards=[{"index": 3, "id": "II", "usb": "09e8:0045", "name": "AKAI MPK Mini Mk II", "short": "MPK Mini Mk II", "pcm": False}])
    D.mark_seen(force=True)
    devs = D.known()
    assert list(devs) == ["09e8:0045"] and devs["09e8:0045"]["roles"] == ["keys"] and devs["09e8:0045"]["last_seen"]
    assert D.bindings()["usb1"]["key"] == "09e8:0045"


def test_lier_un_inconnu_puis_l_oublier(rack, monkeypatch):
    with pytest.raises(ValueError):
        D.bind(1, roles=["drums"])                            # rien de branché
    _present(monkeypatch, "Alesis Nitro", cards=[{"index": 4, "id": "Nitro", "usb": "13b2:009c", "name": "Alesis Nitro", "short": "Alesis Nitro", "pcm": False}])
    k, e = D.bind(1, roles=["drums"], kit="alesis-nitro", person="alex")
    assert k == "13b2:009c" and e["kit"] == "alesis-nitro" and e["person"] == "alex"
    assert D.bindings()["usb1"]["kit"] == "alesis-nitro"
    # les rôles changent : le kit d'un module ne survit pas à un rôle clavier, le numéro non plus
    D.update(k, roles=["keys"])
    assert "kit" not in D.known()[k]
    _present(monkeypatch)                                      # débranché : toujours connu
    assert D.bindings() == {} and D.known()[k]["name"] == "Alesis Nitro"
    assert D.forget(k)["name"] == "Alesis Nitro" and D.known() == {} and D.forget(k) is None
