# SPDX-License-Identifier: GPL-3.0-or-later
"""Les diodes des stomps suivent le rack (bridge/foot_leds.py, docs/pedalboards.md § Diodes). La puce simulée
reproduit la MESURE du 2026-10-08 : un appui à distance bascule la diode et renvoie CC + Note, comme le pied."""
import time

import pytest

from bridge import foot_leds as L


class Chip:
    """La UnO2 : une diode par stomp, l'appui à distance la bascule et l'écho repart vers le rack."""
    def __init__(self, leds):
        self.leds, self.presses, self.to_rack = dict(leds), [], []

    def press(self, sw):
        self.presses.append(sw)
        self.leds[sw] = not self.leds.get(sw, False)
        swallowed_cc = L.on_stomp_cc(sw, self.leds[sw])
        swallowed_note = L.on_stomp_note(sw)
        if not swallowed_cc:
            self.to_rack.append(("cc", sw, self.leds[sw]))
        if not swallowed_note:
            self.to_rack.append(("note", sw))
        return True


@pytest.fixture
def rig():
    L.forget()
    want = {}
    chip = Chip({})
    L.configure(lambda: dict(want), chip.press)
    yield want, chip
    L.configure(None, None)
    L.forget()


def test_la_scene_eteint_les_diodes_allumees_au_pied(rig):
    want, chip = rig
    for sw in (6, 7, 8):                      # Paper Kite : trois stomps allumés au pied pendant les essais
        chip.leds[sw] = True
        assert not L.on_stomp_cc(sw, True)    # un vrai coup de pied passe au rack
    want.update({6: True, 7: False, 8: False, 9: False})     # « Big Muff wall » : seul SW6
    assert L.align() == [7, 8, 9]             # SW9 inconnue : appuyée, l'écho la remet (clignotement)
    assert chip.leds == {6: True, 7: False, 8: False, 9: False}
    assert chip.to_rack == []                 # l'écho n'atteint jamais le rack : aucun bloc rebasculé


def test_l_echo_corrige_une_croyance_fausse(rig):
    want, chip = rig
    chip.leds[7] = True                       # allumée, mais le rack la croit éteinte (relancé entre-temps)
    L.on_stomp_cc(7, False)                   # croyance fausse
    chip.leds[7] = True
    want.update({7: True})
    L.align()                                 # 1er appui : la diode s'éteint, l'écho dit OFF -> second appui
    assert chip.presses == [7, 7] and chip.leds[7] is True
    assert chip.to_rack == []


def test_une_diode_inconnue_est_appuyee_et_l_echo_la_remet(rig):
    want, chip = rig
    chip.leds.update({6: False, 7: True})     # rack rechargé : il ne sait rien des diodes
    want.update({6: False, 7: False})
    L.align()
    assert chip.leds == {6: False, 7: False}  # SW7 éteinte ; SW6 a clignoté (deux appuis) et reste éteinte
    assert sorted(chip.presses) == [6, 6, 7]
    assert chip.to_rack == []                 # et le son n'a jamais bougé


def test_un_coup_de_pied_apres_la_fenetre_passe_au_rack(rig, monkeypatch):
    want, chip = rig
    want.update({8: True})
    calls = []
    L.configure(lambda: dict(want), lambda sw: calls.append(sw) or True)    # la puce ne répond pas
    L.align()
    monkeypatch.setattr(L, "ECHO_WINDOW_S", 0.0)
    L._PENDING[8]["until"] = time.monotonic() - 1                            # fenêtre d'écho passée
    assert not L.on_stomp_cc(8, False)        # c'est le pied : le rack doit l'entendre
