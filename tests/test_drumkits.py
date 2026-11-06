# SPDX-License-Identifier: GPL-3.0-or-later
"""Descripteurs de kit de batterie (docs/drums-kit.md §3, lot 1) : tous valides, identification par le
nom USB avec repli GM DIT, traduction note -> élément et CC -> trois positions de charleston."""
import json, os

import pytest

from bridge import drumkits


def test_tous_les_descripteurs_du_depot_sont_valides():
    kits = drumkits.load_all(strict=True)
    assert {"alesis-nitro", "roland-td", "general-midi", "millenium-mps1000", "yamaha-dtx402"} <= set(kits)
    for kid, d in kits.items():
        assert drumkits.validate(d, kid) == []
    assert drumkits.get("general-midi")["provenance"]["confidence"] == "unconfirmed"      # un repli ne prétend rien


def test_identification_par_le_nom_usb_le_motif_le_plus_long_gagne():
    assert drumkits.identify("Nitro Drum Module") == ("alesis-nitro", True, False)
    assert drumkits.identify("Roland TD-17")[0] == "roland-td"
    assert drumkits.identify("MPS-1000")[0] == "millenium-mps1000" and drumkits.identify("MPS-850")[0] == "millenium-mps850"
    assert drumkits.identify("DTX402") == ("yamaha-dtx402", True, False)
    assert drumkits.identify("MPK Mini Mk II") == ("general-midi", True, True)             # inconnu : repli, et c'est dit
    assert drumkits.identify(None)[2] is True


def test_resolve_prefere_le_kit_choisi_puis_l_usb():
    r = drumkits.resolve({"device": "Nitro Drum Module"})
    # `verified` depuis le 2026-09-23 : ce module-là a été mesuré pad par pad (check-drums.py)
    assert r["id"] == "alesis-nitro" and r["auto"] is True and r["fallback"] is False and r["confidence"] == "verified"
    r = drumkits.resolve({"device": "Nitro Drum Module", "kit": "roland-td"})
    assert r["id"] == "roland-td" and r["auto"] is False
    r = drumkits.resolve({"device": "Nitro Drum Module", "kit": "gone-kit"})               # un kit disparu -> l'USB
    assert r["id"] == "alesis-nitro" and r["auto"] is True


def test_note_vers_element_et_charleston_trois_positions():
    nitro, roland, crimson = drumkits.get("alesis-nitro"), drumkits.get("roland-td"), drumkits.get("alesis-crimson2")
    assert drumkits.element_of(nitro, 36) == "kick" and drumkits.element_of(nitro, 42) == "hh-closed"
    assert drumkits.element_of(nitro, 23) is None      # MESURÉ le 23/09 : ce module n'émet jamais 23
    assert drumkits.element_of(roland, 26) == "hh-open-edge" and drumkits.element_of(roland, 99) is None   # inconnue : rien
    assert drumkits.element_of(crimson, 8) == "hh-open"                                   # une seule note + CC
    # Roland : 0 ouvert -> 90 fermé ; Medeli/Yamaha : 0 -> 127
    assert [drumkits.hihat_position(roland, v) for v in (0, 20, 45, 89)] == ["open", "open", "half", "closed"]
    # Le MÉCANISME des trois bandes, sur un descripteur synthétique : il ne doit pas dépendre d'une
    # table de terrain, sinon une mesure qui corrige un fichier casse le test du mécanisme (vécu le
    # 2026-09-23 : la Nitro n'a PAS de CC de charleston, et ce test l'affirmait par elle).
    synth = {"hihat": {"cc": 4, "open_value": 0, "closed_value": 127, "positions": 3, "bands": [33, 66]}}
    assert [drumkits.hihat_position(synth, v) for v in (0, 60, 127)] == ["open", "half", "closed"]
    assert drumkits.hihat_position(nitro, 64) is None                                    # pédale = interrupteur
    assert drumkits.hihat_position(drumkits.get("alesis-turbo"), 64) is None


def test_un_descripteur_casse_est_refuse_et_ignore(tmp_path, monkeypatch):
    monkeypatch.setattr(drumkits, "DIR", str(tmp_path))
    monkeypatch.setattr(drumkits, "LOCAL_DIR", str(tmp_path))   # les mesures aussi : jamais config/ réel
    good = json.load(open(os.path.join(os.path.dirname(drumkits.DIR) if False else "config/drumkits", "general-midi.json")))
    bad = json.loads(json.dumps(good)); bad["id"] = "bad-kit"; bad["map"]["36"] = "gong"; bad["provenance"]["confidence"] = "verified"
    (tmp_path / "bad-kit.json").write_text(json.dumps(bad))
    (tmp_path / "general-midi.json").write_text(json.dumps(good))
    probs = drumkits.validate(bad, "bad-kit")
    assert any("not a kit element" in p for p in probs) and any("`verified` needs `source: measured`" in p for p in probs)
    assert set(drumkits.load_all()) == {"general-midi"}                                  # le cassé est ignoré, pas fatal
    with pytest.raises(ValueError):
        drumkits.load_all(strict=True)


def test_le_port_usb_drums_porte_son_kit(tmp_path, monkeypatch):
    from bridge import inputmap, config as C, devices
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    (tmp_path / "soundcard.json").write_text(json.dumps({"usb2": {"enabled": True, "device": "Nitro Drum Module", "kind": "midi", "roles": ["drums"]}}))
    # connu ≠ branché (2026-09-23) : le rang usb2 n'existe que si l'appareil est DÉTECTÉ en 2e
    monkeypatch.setattr(devices, "_usb_list", lambda: [{"name": "MPK", "kind": "midi"}, {"name": "Nitro Drum Module", "kind": "midi"}])
    u2 = inputmap.usb_ports()[1]
    assert u2["role"] == "drums" and u2["kit"]["id"] == "alesis-nitro" and u2["kit"]["auto"] is True
