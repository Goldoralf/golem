# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiroir Pads v2 (2026-10-14) : la famille d'un son de pad se lit dans son nom (le navigateur range par famille) ;
l'écoute n'accepte qu'un sample sous assets/samples."""
from bridge import kits


def test_la_famille_d_un_sample_se_lit_dans_son_nom():
    cases = {"01_kick": "kick", "02_kick_sub": "kick", "03_snare": "snare", "04_clap": "clap", "05_rim": "perc",
             "06_hat_closed": "hat", "07_hat_pedal": "hat", "09_tom_low": "tom", "12_ride": "cym", "14_crash": "cym",
             "16_cowbell": "perc", "Big BD 808": "kick", "Shaker loop": "perc", "mystery": "perc"}
    for name, cat in cases.items():
        assert kits.sample_cat(name) == cat, name


def test_on_n_ecoute_qu_un_sample_du_rack():
    assert not kits.sample_ok("../config/integrations.json")
    assert not kits.sample_ok("/etc/passwd")
    assert not kits.sample_ok("assets/samples/nope.wav")
