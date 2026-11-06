# SPDX-License-Identifier: GPL-3.0-or-later
"""La mémoire de position du pédalier ne doit jamais enregistrer une supposition.

Régression du 2026-08-10. `goto_bank` écrivait `_BELIEVED` dès que `control_change()` rendait
True — or True ne dit que « les octets ont quitté le port ». Sur un rig à une seule sortie DIN,
le câble vit sur la Whammy pendant le jeu : l'ordre partait dans le vide, le rack notait quand
même la position, et l'alignement suivant se croyait « déjà bon » et ne partait plus. Le rack
cessait d'essayer sans avoir jamais réussi une seule fois.

Ces tests ne touchent NI le MIDI NI le disque : `active` et `control_change` sont remplacés.
"""

from __future__ import annotations

import pytest

from bridge import pedalboard


DEVICE = {
    "name": "FCB1010 — puce UnO2",
    "capabilities": {"goto_bank": {"supported": True, "channel": 16,
                                   "controller": 0, "index_base": 1}},
}


@pytest.fixture
def rig(monkeypatch):
    """Neutralise le matériel et rend l'état de la sonde pilotable par le test."""
    sent: list[tuple] = []

    def _fake_active(stale):
        return lambda: {"id": "fcb1010-uno2", "name": DEVICE["name"], "device": DEVICE,
                        "source": "measured", "stale": stale}

    class _FakeMidiOut:
        @staticmethod
        def control_change(cc, val, channel=1):
            sent.append((cc, val, channel))
            return True          # les octets sortent : c'est TOUT ce que le MIDI garantit

    monkeypatch.setitem(__import__("sys").modules, "bridge.midi_out", _FakeMidiOut)
    # ⚠ Patcher sys.modules ne suffit PAS si un AUTRE test a déjà importé bridge.midi_out :
    # l'import pose l'attribut sur le paquet `bridge`, et `from . import midi_out` le préfère
    # au sys.modules patché. Constaté quand test_midi_pedal.py est arrivé (2026-08-13) : les
    # trois tests d'ici échouaient EN SUITE et passaient SEULS. On patche donc l'attribut aussi.
    import bridge as _pkg
    monkeypatch.setattr(_pkg, "midi_out", _FakeMidiOut, raising=False)
    monkeypatch.setattr(pedalboard, "_BELIEVED", {"slot": None})
    return {"sent": sent, "set_stale": lambda s: monkeypatch.setattr(
        pedalboard, "active", _fake_active(s))}


def test_lien_non_prouve_nenregistre_rien(rig):
    """Sonde muette = on ne sait pas si l'ordre arrive. On l'envoie, on ne le NOTE pas."""
    rig["set_stale"](True)
    assert pedalboard.goto_bank(3) is True          # l'ordre est bien parti
    assert rig["sent"] == [(0, 4, 16)]              # CC0 = slot+index_base, canal 16
    assert pedalboard.believed_slot() is None       # ...mais rien n'est enregistré


def test_le_rack_continue_dessayer(rig):
    """Le vrai dégât du bug : après un envoi non prouvé, l'alignement suivant doit REPARTIR.
    C'est ce que le court-circuit `believed_slot() == slot` supprimait définitivement."""
    rig["set_stale"](True)
    pedalboard.goto_bank(3)
    pedalboard.goto_bank(3)
    assert len(rig["sent"]) == 2


def test_lien_prouve_enregistre(rig):
    """Sonde fraîche = le rack atteint le pédalier, l'ordre arrive : là on peut noter."""
    rig["set_stale"](False)
    assert pedalboard.goto_bank(5) is True
    assert pedalboard.believed_slot() == 5


def test_le_pedalier_fait_toujours_autorite(rig):
    """Un PC entrant est un fait, pas une supposition : il écrase la mémoire quoi qu'il arrive."""
    rig["set_stale"](False)
    pedalboard.goto_bank(5)
    pedalboard.note_foot_bank(2)                    # le pied annonce SA bank
    assert pedalboard.believed_slot() == 2


def test_capacite_absente_nenvoie_rien(rig):
    """Une puce qui ne sait pas recevoir (la 1.0.4) ne doit produire aucun octet."""
    rig["set_stale"](False)
    DEVICE["capabilities"]["goto_bank"]["supported"] = False
    try:
        assert pedalboard.goto_bank(1) is False
        assert rig["sent"] == []
        assert pedalboard.believed_slot() is None
    finally:
        DEVICE["capabilities"]["goto_bank"]["supported"] = True
