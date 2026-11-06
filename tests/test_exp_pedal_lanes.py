# SPDX-License-Identifier: GPL-3.0-or-later
"""La pédale d'EXPRESSION doit voir les blocs d'un preset v2 (lanes).

Panne réelle du 2026-09-20, trouvée une heure avant une répète : « la pédale EXP 2
volume ne marche pas » sur Paper Kite. `_iter_ui_blocks` ne lisait que les miroirs legacy
(`preset.guitar`, `preset.voice`), qui ne sont régénérés QUE pour les lanes d'id `guitar`,
`voice`, `keys` (store.LEGACY_KEY). Une lane moderne s'appelle `guitar-1` depuis que l'id dérive
de l'entrée (2026-09-09) : le miroir était donc ABSENT, la fonction ne voyait aucun bloc, et la
cible de la pédale restait vide — sans une erreur, sans une ligne de log, avec « EXP2 Volume »
affiché à l'écran. Tout était vrai sauf la cible.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _iter_ui_blocks():
    """La fonction seule, sans monter tout le bridge (app.py importe Reaper, OSC, MIDI…)."""
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    i = src.index("def _iter_ui_blocks")
    j = src.index("def _set_exp_blk_from")
    ns = {}
    exec(compile(src[i:j], "app.py", "exec"), ns)
    return ns["_iter_ui_blocks"]


def _v2(blocks):
    return {"id": "p", "lanes_v": 2, "lanes": [
        {"id": "guitar-1", "role": "guitar", "in_sel": "1",
         "chain": {"pre": blocks, "split": None, "post": []}}]}


def test_les_blocs_d_une_lane_v2_sont_vus():
    blocks = [{"id": "volume-sys", "type": "volume"}, {"id": "b1", "type": "gate"}]
    out = list(_iter_ui_blocks()(_v2(blocks)))
    assert [b["id"] for b in out] == ["volume-sys", "b1"]


def test_une_lane_au_nom_MODERNE_compte():
    """C'est tout le bug : `guitar-1` n'a pas de miroir legacy, et c'est le cas par défaut."""
    p = _v2([{"id": "volume-sys", "type": "volume"}])
    assert "guitar" not in p, "un preset v2 n'a pas forcément de miroir legacy"
    assert any(b["type"] == "volume" for b in _iter_ui_blocks()(p))


def test_les_branches_d_un_split_comptent_aussi():
    p = _v2([])
    p["lanes"][0]["chain"]["split"] = {"branches": [
        {"id": "a", "blocks": [{"id": "wah-1", "type": "wah"}]},
        {"id": "b", "blocks": [{"id": "amp-1", "type": "amp"}]}]}
    assert {b["id"] for b in _iter_ui_blocks()(p)} == {"wah-1", "amp-1"}


def test_le_chemin_LEGACY_marche_encore():
    """Un preset d'avant les lanes garde son comportement — sinon on répare en cassant."""
    old = {"id": "p", "guitar": {"pre": [{"id": "v", "type": "volume"}], "split": None, "post": []},
           "voice": {"chain": [{"id": "r", "type": "reverb"}]}}
    assert {b["id"] for b in _iter_ui_blocks()(old)} == {"v", "r"}


def test_un_preset_vide_ne_leve_pas():
    assert list(_iter_ui_blocks()({"id": "p"})) == []
