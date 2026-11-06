# SPDX-License-Identifier: GPL-3.0-or-later
"""Ports USB = entrées du RACK (2026-09-09, docs/input-map.md §3.3) : quatre ports fixes,
numérotés AVEC les entrées audio, une personne par port ; jamais dans le patch d'une carte.
Depuis le 2026-09-23 (« connu ≠ branché », bridge/devices.py) le binding vit dans le REGISTRE des
appareils connus (config/devices.json) ; `usbN` est le rang de l'appareil détecté, dérivé. Le vieux
soundcard.json est migré au premier chargement — c'est ce que la fixture exerce."""

import json, os
import pytest

from bridge import config as C, inputmap, modes, recall


@pytest.fixture
def rack(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path / "maps"))
    monkeypatch.setattr(inputmap, "_card_device", lambda: "hw:V276")
    from bridge import devices
    monkeypatch.setattr(devices, "_usb_list", lambda: [{"name": "MPK Mini Mk II", "kind": "midi"}])   # rien sur USB 2..4
    json.dump({"usb1": {"enabled": True, "device": "MPK Mini Mk II", "kind": "midi", "roles": ["keys", "pads"]}},
              open(tmp_path / "soundcard.json", "w"))
    json.dump({"people": [{"id": "p_sala", "name": "SaLA"}]}, open(tmp_path / ".band.json", "w"))
    inputmap.set_role("input", "1", "guitar", "hw:V276")
    return tmp_path


def known(rack):
    """Le registre migré : {key: entry} — et la preuve que soundcard.json a été gardé en .migrated."""
    assert not os.path.exists(rack / "soundcard.json") and os.path.exists(rack / "soundcard.json.migrated")
    return json.load(open(rack / "devices.json"))["devices"]


def akai(rack):
    return next(e for e in known(rack).values() if e["name"] == "MPK Mini Mk II")


def test_quatre_ports_toujours_la_lie_ou_non(rack):
    cur = inputmap.current("hw:V276")
    assert [u["ch"] for u in cur["usb"]] == ["usb1", "usb2", "usb3", "usb4"]
    u1 = cur["usb"][0]
    assert u1["bound"] and u1["role"] == "keys-pads" and u1["nth"] == 1 and u1["name"] == "Keys + Pads 1" and u1["device"] == "MPK Mini Mk II"
    assert all(not u["bound"] and u["role"] == "none" and u.get("nth") is None for u in cur["usb"][1:])
    assert cur["midi"]["role"] == "keys-pads"                    # compat : l'ancien champ reste


def test_le_numero_est_partage_entre_audio_et_usb(rack):
    inputmap.set_role("input", "5", "keys-pads", "hw:V276")     # un clavier AUDIO en IN 5
    cur = inputmap.current("hw:V276")
    assert next(e for e in cur["inputs"] if e["ch"] == "5")["nth"] == 1
    assert cur["usb"][0]["nth"] == 2 and cur["usb"][0]["name"] == "Keys + Pads 2"
    with pytest.raises(ValueError):                             # 1 est pris par l'audio
        inputmap.set_nth("usb1", 1, "hw:V276")
    inputmap.set_nth("usb1", 3, "hw:V276")
    assert akai(rack)["nth"] == 3
    with pytest.raises(ValueError):                             # et 3 est pris par l'USB
        inputmap.set_nth("5", 3, "hw:V276")


def test_personne_et_role_d_un_port_vont_dans_le_binding(rack):
    cur = inputmap.set_person("usb1", "p_sala", "hw:V276")
    assert cur["usb"][0]["person"] == "p_sala" and cur["usb"][0]["person_name"] == "SaLA"
    assert akai(rack)["person"] == "p_sala"
    assert not os.path.exists(rack / "maps" / "hw-V276.json") or "usb1" not in open(rack / "maps" / "hw-V276.json").read()
    cur = inputmap.set_role("input", "usb1", "keys", "hw:V276")
    assert cur["usb"][0]["role"] == "keys" and akai(rack)["roles"] == ["keys"]
    with pytest.raises(ValueError):
        inputmap.set_role("input", "usb1", "guitar", "hw:V276")
    with pytest.raises(ValueError):                             # rien de branché sur USB 3
        inputmap.set_role("input", "usb3", "keys", "hw:V276")
    inputmap.set_role("input", "usb1", "none", "hw:V276")       # « none » = oublier, explicitement
    assert not any(e["name"] == "MPK Mini Mk II" for e in known(rack).values())


def test_le_mode_coupe_un_port_usb_comme_une_entree(rack, monkeypatch):
    from bridge.state import state
    cur = inputmap.current("hw:V276")
    monkeypatch.setattr(state, "inputmap", cur, raising=False)
    monkeypatch.setattr(state, "mode", {"id": "gig", "services": {}, "inputs_off": ["keys-pads#1"]}, raising=False)
    p = {"id": "p", "lanes_v": 2, "lanes": [
        {"id": "guitar", "role": "guitar", "in_sel": "1", "chain": {"pre": [], "split": None, "post": []}},
        {"id": "keys-pads-1", "role": "keys-pads", "midi": True, "in_sel": "usb", "chain": {"pre": [], "split": None, "post": []}}],
         "scenes": [{"id": "A"}]}
    assert recall.input_veto(p) == {"keys-pads-1"}
    monkeypatch.setattr(state, "mode", {"id": "gig", "services": {}, "inputs_off": []}, raising=False)
    assert recall.input_veto(p) == set()


def test_un_module_de_batterie_sur_un_port_usb(rack):
    """docs/drums-kit.md lot 0 : `drums` est un rôle de port USB, EXCLUSIF ; il ne devient pas la lane
    Keys legacy (cur["midi"]) et il est numéroté et nommé comme les autres."""
    cur = inputmap.set_role("input", "usb1", "drums", "hw:V276")
    u1 = cur["usb"][0]
    assert u1["role"] == "drums" and u1["name"] == "Drums 1" and u1["nth"] == 1
    assert akai(rack)["roles"] == ["drums"]
    assert (cur.get("midi") or {}).get("role") != "drums"        # la lane Keys legacy ne devient pas une batterie (absente ici : seul port = batterie)
    with pytest.raises(ValueError):
        inputmap.set_role("input", "usb1", "guitar", "hw:V276")


def test_un_appareil_debranche_reste_connu_et_revient_tout_seul(rack, monkeypatch):
    """2026-09-23 : « ils ont été connectés au golem, ils ne disparaissent pas ». Débranché : plus
    de rang usbN, mais toujours connu (rôles, personne, numéro). Rebranché à N'IMPORTE quel rang : actif
    sans geste. Et un autre appareil qui prend le rang n'efface rien."""
    from bridge import devices
    inputmap.set_person("usb1", "p_sala", "hw:V276")
    monkeypatch.setattr(devices, "_usb_list", lambda: [])            # débranché
    assert not inputmap.current("hw:V276")["usb"][0]["bound"]
    assert akai(rack)["person"] == "p_sala" and akai(rack)["roles"] == ["keys", "pads"]
    lst = devices.listing()
    assert [(d["name"], d["connected"], d["port"]) for d in lst] == [("MPK Mini Mk II", False, None)]
    # un AUTRE appareil prend le rang 1 : il est détecté, pas connu — et l'AKAI n'a pas bougé
    monkeypatch.setattr(devices, "_usb_list", lambda: [{"name": "Alesis Nitro", "kind": "midi"}])
    assert not inputmap.current("hw:V276")["usb"][0]["bound"]
    assert [(d["name"], d["known"], d["connected"]) for d in devices.listing()] == [("Alesis Nitro", False, True), ("MPK Mini Mk II", True, False)]
    inputmap.set_role("input", "usb1", "drums", "hw:V276")                           # on la lie : deux connus
    assert sorted(e["name"] for e in known(rack).values()) == ["Alesis Nitro", "MPK Mini Mk II"]
    # les deux branchés : chacun à son rang, sans aucun geste
    monkeypatch.setattr(devices, "_usb_list", lambda: [{"name": "Alesis Nitro", "kind": "midi"}, {"name": "AKAI MPK Mini Mk II", "kind": "midi"}])
    cur = inputmap.current("hw:V276")
    assert cur["usb"][0]["role"] == "drums" and cur["usb"][1]["role"] == "keys-pads" and cur["usb"][1]["person"] == "p_sala"
