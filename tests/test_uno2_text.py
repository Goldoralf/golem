# SPDX-License-Identifier: GPL-3.0-or-later
"""Le setup UnO2 en texte (Windows / macOS : collé dans Control Center) dit EXACTEMENT ce que le rack
flasherait sous Linux. Le texte est décompilé du même Setup que le binaire ; relu, il doit redonner ce
binaire au bit près — sur la configuration nue (le témoin), avec des banks looper, avec des switches
réservés, et les deux à la fois. Et il ne contient que de l'ASCII (Control Center refuse le non-Latin-1 :
les setups d'août ne compilaient pas à cause des traits de cadre)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "fcb"))
import gen_uno2_syx as gen  # noqa: E402
import uno2  # noqa: E402
import uno2_text  # noqa: E402


def _roundtrip(looper=(), claims=None):
    contract, device = gen.load()
    setup = gen.build(contract, device, looper_slots=looper, claim_slots=claims or {})
    binary = uno2.build_binary(setup)
    text = uno2_text.render(setup, device["channel"])
    assert uno2_text.check(text, binary) == []
    back, channel = uno2_text.parse(text)
    assert channel == device["channel"]
    assert uno2.build_binary(back) == binary
    assert uno2.setup_length(back) == uno2.setup_length(setup)
    return text


def test_bare_contract_roundtrips_bit_for_bit():
    text = _roundtrip()
    assert text.isascii()
    assert "REMOTE_CONTROL_CHANNEL = 16" in text and "CHANNEL Golem = 2" in text


def test_looper_and_claimed_banks_roundtrip():
    text = _roundtrip(looper=(3, 7), claims={1: [5], 4: [2, 3]})
    assert "Slot03L" in text and "Slot01C" in text and "Claim2" in text


def test_sections_come_in_the_order_control_center_imposes():
    text = _roundtrip(looper=(2,), claims={0: [4]})
    order = ["PRESETS =", "EFFECTS =", "TRIGGERS =", "SWEEPS =", "BANKS =", "REMOTE_CONTROL_CHANNEL",
             "CHANNEL Golem", "VAR $slot", "INIT_FCB =", "INIT_BANK", "PRESET SceneA", "EFFECT_ON", "TRIGGER_CLICK", "SWEEP Exp1"]
    pos = [text.index(k) for k in order]
    assert pos == sorted(pos)


def test_a_tampered_text_is_refused():
    contract, device = gen.load()
    setup = gen.build(contract, device)
    binary = uno2.build_binary(setup)
    text = uno2_text.render(setup, device["channel"])
    assert uno2_text.check(text.replace("CtrlChange 20 127", "CtrlChange 21 127", 1), binary)
    assert uno2_text.check(text.replace("Golem", "Golem ─", 1), binary)


def test_released_ports_send_nothing():
    """Port rendu (flash par Control Center) : aucun envoi ne doit rouvrir le port — sous Windows
    l'éditeur perdrait la puce au premier changement de scène."""
    sys.path.insert(0, ROOT)
    from bridge import midi_out
    opened = []
    real = midi_out._rt_open
    midi_out._rt_open = lambda: opened.append(1)
    try:
        midi_out.hold(True)
        assert midi_out.control_change(20, 127, channel=2) is False
        assert midi_out.send_sysex([0xF0, 0x00, 0xF7]) is False
        assert opened == []
    finally:
        midi_out.hold(False)
        midi_out._rt_open = real
