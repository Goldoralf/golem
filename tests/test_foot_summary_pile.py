# SPDX-License-Identifier: GPL-3.0-or-later
"""La pile d'un switch sur /live (maquette A, 2026-09-15) : chaque bloc d'un switch porte son RÔLE de
lane et son libellé dans le résumé pédalier — « Phaser · GTR », « PEQ · VOX », « Rec · SVC »."""

from bridge import store


def test_les_blocs_d_un_switch_portent_leur_role_et_leur_libelle():
    p = {"lanes_v": 2, "id": "x", "scenes": [{"id": "A", "blocks": {"peq-1": False}}],
         "lanes": [{"id": "guitar-1", "key": "1", "role": "guitar", "chain": {"pre": [{"type": "phaser", "id": "ph-1", "foot": 7}], "post": []}},
                   {"id": "voice-1", "key": "2", "role": "voice", "chain": {"pre": [{"type": "eq-para", "id": "peq-1", "foot": 7, "label": "Air"}], "post": []}}],
         "config": {"gen": {"blocks": [{"type": "backing-track", "id": "bk", "foot": 5}]},
                    "rec": {"blocks": [{"type": "rec", "id": "rec-global", "foot": 5}]}}}
    fs = store._foot_summary(p)
    sw7 = next(s for s in fs["switches"] if s["sw"] == 7)
    assert [(b["type"], b["role"], b["label"], b["variant"]) for b in sw7["blocks"]] == [("phaser", "guitar", None, None), ("eq-para", "voice", "Air", None)]
    assert "peq-1" in fs["scenes"][0]["off"]          # la ligne PEQ s'éteint dans la scène A
    # le switch 5 est revendiqué par deux services : ils ne sont pas dans les switchs 6-10, mais dans _foot_blocks
    assert {b.get("id") for b, k in store._foot_blocks(p) if b.get("foot") == 5} == {"bk", "rec-global"}
