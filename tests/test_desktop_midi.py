# SPDX-License-Identifier: GPL-3.0-or-later
"""Le MIDI du poste Windows/macOS (bridge/desktop_midi.py) : les prises DIN choisies, les prises USB, et
les masques de REAPER — sous Windows un port ne s'ouvre qu'une fois, REAPER OU le bridge."""
import pytest

from bridge import desktop_midi as M


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(M.C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("GOLEM_FCB_PORT", raising=False)
    monkeypatch.delenv("GOLEM_MIDI_PORT", raising=False)
    monkeypatch.setattr(M, "ports", lambda: {"in": ["Volt 276", "MPK Mini Mk II", "loopMIDI Port"],
                                              "out": ["Microsoft GS Wavetable Synth", "Volt 276", "MPK Mini Mk II"]})
    return tmp_path


def test_nom_propre_comme_reaper(monkeypatch):
    monkeypatch.setattr(M.sys, "platform", "win32")
    assert M._rtmidi_name("Volt 276 1", 1) == "Volt 276"   # l'index de rtmidi/WinMM, et lui seul
    assert M._rtmidi_name("Volt 276", 0) == "Volt 276"     # « 276 » n'est pas un index
    assert M.clean("2- Volt 276") == "Volt 276"            # le doublon de Windows, gardé par REAPER
    assert M.same("2- Volt 276", "Volt 276")


def test_prises_usb_hors_din_et_ports_logiciels(cfg):
    assert [d["name"] for d in M.usb_devices()] == ["Volt 276", "MPK Mini Mk II"]
    M.set_din_port("in", "Volt 276")
    assert [d["name"] for d in M.usb_devices()] == ["MPK Mini Mk II"]


def test_la_variable_d_environnement_gagne(cfg, monkeypatch):
    M.set_din_port("in", "Volt 276")
    monkeypatch.setenv("GOLEM_FCB_PORT", "UMC404HD")
    assert M.din_port("in") == "UMC404HD" and M.din_source("in") == "env"


def test_masques_din_fermee_clavier_ouvert(cfg):
    res = cfg / "reaper"
    res.mkdir()
    (res / "reaper-midihw.ini").write_text(
        "[mididevcache]\nin0=MPK Mini Mk II\nin1=2- Volt 276\nin2=Volt 276\n"
        "on0=MPK Mini Mk II\non1=Volt 276\non2=2- Volt 276\n[mididevignore]\n", encoding="latin-1")
    (res / "reaper.ini").write_text("[REAPER]\nmidiins=6\nmidiouts=6\n", encoding="latin-1")
    M.set_din_port("in", "Volt 276")
    M.set_din_port("out", "Volt 276")
    # in : MPK (0) ouvert, les deux Volt (1, 2) fermés ; out : MPK (0) ouvert, Volt (1, 2) fermés
    assert M.wanted_masks(str(res), 6, 6, ["AKAI MPK Mini Mk II", "MPK Mini Mk II"]) == (1, 1)
    assert M.masks_pending.__name__


def test_une_batterie_est_ouverte_en_entree_seulement(cfg):
    """2026-10-03 : la SORTIE de l'Alesis Nitro ouverte par REAPER figeait l'envoi USB du module (plus un
    message, même lu en direct). Une batterie n'a pas l'usage d'une sortie : entrée ouverte, sortie fermée."""
    res = cfg / "reaper"
    res.mkdir()
    (res / "reaper-midihw.ini").write_text(
        "[mididevcache]\nin0=MPK Mini Mk II\nin3=Alesis Nitro\non0=MPK Mini Mk II\non3=Alesis Nitro\n[mididevignore]\n",
        encoding="latin-1")
    ins, outs = M.wanted_masks(str(res), 0, 9, ["MPK Mini Mk II", "Alesis Nitro"], ["MPK Mini Mk II"])
    assert ins == 9 and outs == 1                      # Nitro (bit 3) : entrée oui, sortie refermée
