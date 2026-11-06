# SPDX-License-Identifier: GPL-3.0-or-later
"""Le switch de l'ARRANGEMENT est recensé au pied (trouvé le 2026-09-30) : sa lane `config.arr` est à part
depuis le 16/09 et `_foot_blocks` ne parcourait que gen/rec — /live, les conflits de switches, la réservation
de la rangée 1-5 et la puce ne voyaient pas le départ de la chanson."""
from pathlib import Path

from bridge import store

ROOT = Path(__file__).resolve().parents[1]

PRESET = {"id": "p", "lanes_v": 2, "scenes": [{"id": "A"}],
          "lanes": [{"id": "guitar-1", "key": "guitar-1", "role": "guitar", "chain": {"pre": [{"id": "dly", "type": "delay-tape", "foot": 8}], "split": None, "post": []}}],
          "config": {"gen": {"blocks": []}, "rec": {"blocks": []},
                     "arr": {"blocks": [{"id": "arr-1", "type": "arrangement", "foot": 8, "params": {"advance": "bars"}}]}}}


def test_larrangement_est_sur_son_switch():
    sw8 = next(s for s in store._foot_summary(PRESET)["switches"] if s["sw"] == 8)
    assert {b["type"] for b in sw8["blocks"]} == {"delay-tape", "arrangement"}      # le conflit se VOIT


def test_sur_la_rangee_des_scenes_il_reserve_son_switch_comme_un_geste():
    p = {**PRESET, "config": {**PRESET["config"], "arr": {"blocks": [{"id": "arr-1", "type": "arrangement", "foot": 3}]}}}
    claims = store._scene_claims(p)
    assert [c["type"] for c in claims[3]] == ["arrangement"]
    assert store.claim_species(claims[3]) == "gesture"


def test_ce_nest_jamais_un_fx_a_basculer():
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    line = next(l for l in src.splitlines() if l.startswith("SERVICE_TYPES"))
    assert '"arrangement"' in line



def _fn(name):
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    start = src.index("def " + name + "(")
    end = src.index("\ndef ", start + 1)
    return src[start:end]


def test_le_switch_de_l_arrangement_passe_avant_la_backing():
    """2026-10-07 : l'arrangement LANCE la backing — une backing posée sur son switch ne lui vole plus le geste
    (bridge.app ne s'importe pas ici : il ouvre le port OSC du bridge qui tourne)."""
    body = _fn("_on_stomp_edge")
    assert body.index("sw == state.arr_switch") < body.index("sw == recall_mod.backing_sw")
    assert "effective_preset(load_preset(state.preset_id))" in body        # la chanson, pas le preset brut


def test_la_prise_avec_le_morceau_vient_de_la_case_record_et_d_elle_seule():
    """Lot 3 (arrangement-controls §7) : plus d'empilement de Rec sur le switch — la case de la chanson décide."""
    body = _fn("_on_song")
    assert '.get("record") is True' in body and "_rec_on_arr_switch" not in body


def test_la_prise_du_morceau_annonce_la_backing_et_part_au_premier_temps():
    """2026-10-07, test au pied de Paper Kite (« pas de backing ») : la prise lancée par le morceau démarrait le
    transport sans annoncer la backing — golem_perfrec coupait son bus. Elle l'annonce, et part après le décompte."""
    body = _fn("_on_song")
    assert "with_backing=bk" in body and 'delay=(info or {}).get("count_in")' in body
    bk = _fn("_arr_backing")
    assert 'return "free"' in bk and "rec_with_song" in bk          # la prise joue la backing ; son arrêt l'arrête
