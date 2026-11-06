# SPDX-License-Identifier: GPL-3.0-or-later
"""Le MusicXML de la transcription : chaque mesure fait EXACTEMENT sa longueur.

Trouvé le 2026-09-21 par tools/check-tab-vs-gp.py sur Paper Kite : chaque durée était arrondie
seule, un tick était forcé, et deux figures arrondies qui se chevauchaient étaient écrites toutes
les deux en entier. Des mesures trop pleines, qu'un lecteur (alphaTab, le comparateur) ne cale
plus : 2 s de dérive sur le morceau."""
import xml.etree.ElementTree as ET

from bridge.transcribe import Figure, to_musicxml


def _bar_lengths(xml):
    root = ET.fromstring(xml.split("\n", 2)[2])          # sans la déclaration ni le DOCTYPE
    out = []
    for m in root.iter("measure"):
        tot = 0
        for n in m.iter("note"):
            if n.find("chord") is None:
                tot += int(n.find("duration").text)
        out.append(tot)
    return out


def test_deux_figures_qui_se_chevauchent_ne_s_empilent_pas():
    figs = [Figure(0.0, 1.0, (52,)), Figure(0.75, 1.0, (55, 59))]
    assert _bar_lengths(to_musicxml(figs, bpm=88)) == [16]


def test_un_triolet_ne_laisse_pas_la_mesure_courte():
    figs = [Figure(0.0, 0.33, (57,)), Figure(0.33, 0.33, (57,)), Figure(0.66, 0.34, (57,))]
    assert _bar_lengths(to_musicxml(figs, bpm=88)) == [16]


def test_un_silence_ne_sort_pas_de_sa_mesure():
    figs = [Figure(3.0, 0.5, (60,), rest_after_ql=1.5), Figure(6.0, 3.0, (40,))]
    assert set(_bar_lengths(to_musicxml(figs, bpm=88))) == {16}


def test_toutes_les_attaques_restent():
    figs = [Figure(i * 0.25, 0.25, (50 + i % 5,)) for i in range(16)]
    xml = to_musicxml(figs, bpm=88)
    assert xml.count("<pitch>") == 16 and _bar_lengths(xml) == [16]
