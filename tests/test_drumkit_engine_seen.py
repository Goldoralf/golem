# SPDX-License-Identifier: GPL-3.0-or-later
"""Un moteur à part (drumkit…) n'a pas de nom de plugin à prédire, mais golem_rig dit s'il a pu le poser —
2026-10-03 : un kit sans AVL Drumkits (Windows) s'affichait « ready », les notes arrivaient, rien ne sonnait."""
from bridge import blockstatus as BS


def test_le_constat_du_moteur_barre_un_kit_sans_moteur():
    assert BS.plugin_state("drumkit", inv=None, obs={}) is None                       # rien su : on ne barre pas
    assert BS.plugin_state("drumkit", inv=None, obs={"drumkit": {"ok": False}}) is False
    assert BS.plugin_state("drumkit", inv=None, obs={"drumkit": {"ok": True, "name": "LV2i:Black Pearl"}}) is True
