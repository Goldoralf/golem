# SPDX-License-Identifier: GPL-3.0-or-later
"""Les instruments clavier d'usine (piano SFZ, e-piano DX7, orgue) voyagent dans l'ÉTAT poussé à
golem.fm, pas en packs (demande golem.fm 2026-09-15) : Library ▸ Keys ▸ Instruments des deux côtés."""

from bridge import rigstatus


def test_keys_instruments_dans_l_etat():
    ki = rigstatus.keys_instruments()
    assert [i["type"] for i in ki] == ["piano", "ep", "organ"]
    for i in ki:
        assert i["factory"] is True and i["engine"] in ("sfizz", "dexed", "b3") and isinstance(i["items"], list)
    ep = ki[1]
    assert ep["sounds"] == 32 * ep["count"]
