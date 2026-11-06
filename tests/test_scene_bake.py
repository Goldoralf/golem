# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests du bake de scène (bridge/scene_bake.py) : bypass par scène + potards par scène
(scene-first + héritage — cf. mémoire per-scene-knob-params)."""
from bridge import scene_bake
import pytest


@pytest.fixture(autouse=True)
def _carte_classique(monkeypatch):
    """Ces presets LEGACY s'assoient désormais sur l'entrée de leur rôle (audit 2026-10-10) : la carte de test
    est la classique (IN 1 guitare, IN 2 voix) — pas celle de la machine qui lance les tests."""
    from bridge import inputmap
    card = {"card": "hw:test", "inputs": inputmap.with_nth([{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "voice"}])}
    monkeypatch.setattr(inputmap, "current", lambda *a, **k: card)


def _preset(scenes=None, pre=None):
    return {
        "id": "t", "name": "T",
        "guitar": {"pre": pre or [{"type": "boost", "id": "boost-1", "params": {"gain": 4}}],
                   "split": None, "post": []},
        "voice": {"chain": []},
        "scenes": scenes or [{"id": "A", "name": "base", "blocks": {}, "voice": False}],
    }


def _guitar_blocks(out):
    gp = next(p for p in out["paths"] if p["input"] == 1)
    return [n for n in gp["chain"] if "split" not in n]


def test_bake_bypass_par_scene():
    p = _preset(scenes=[{"id": "A", "blocks": {"boost-1": False}, "voice": False}])
    blocks = _guitar_blocks(scene_bake.to_paths_preset(p, "A"))
    assert blocks[0]["bypass"] is True          # scène OFF -> bloc posé mais bypassé


def test_bake_scene_on_force():
    p = _preset(scenes=[{"id": "A", "blocks": {"boost-1": True}, "voice": False}])
    blocks = _guitar_blocks(scene_bake.to_paths_preset(p, "A"))
    assert blocks[0].get("bypass") is False


def test_params_scene_first_heritage():
    """scene.params[bloc][pid] écrase la base ; les params non-override héritent."""
    p = _preset(scenes=[{"id": "A", "blocks": {}, "voice": False,
                         "params": {"boost-1": {"gain": 9}}},
                        {"id": "B", "blocks": {}, "voice": False}])
    a = _guitar_blocks(scene_bake.to_paths_preset(p, "A"))[0]
    b = _guitar_blocks(scene_bake.to_paths_preset(p, "B"))[0]
    assert a["params"]["gain"] == 9             # override de la scène A
    assert b["params"]["gain"] == 4             # scène B hérite de la base


def test_voice_path_absent_si_scene_voice_off():
    out = scene_bake.to_paths_preset(_preset(), "A")
    assert all(p["input"] == 1 for p in out["paths"])


def test_un_potard_touche_dans_une_scene_est_ecrit_dans_toutes(tmp_path, monkeypatch):
    """Mesuré le 2026-09-14 : un clean-boost réglé à 2,6 dB en scène C restait à 2,6 en scène A,
    parce qu'A ne disait rien et que le moteur n'écrit que ce qu'on lui donne. Une scène sans
    réglage doit RAMENER le potard (base, sinon défaut du catalogue) ; un potard jamais touché
    n'est pas écrit."""
    import json
    from bridge import config as C
    cat = tmp_path / "effects.json"
    json.dump({"effects": [{"type": "clean-boost", "params": [{"id": "gain", "default": 6}]},
                           {"type": "delay", "params": [{"id": "mix", "default": 30}, {"id": "time", "default": 400}]}]}, open(cat, "w"))
    monkeypatch.setattr(C, "EFFECTS", str(cat))
    p = _preset(pre=[{"id": "cb", "type": "clean-boost"}, {"id": "dl", "type": "delay", "params": {"time": 500}}],
                scenes=[{"id": "A", "blocks": {}}, {"id": "C", "blocks": {}, "params": {"cb": {"gain": 2.58}, "dl": {"time": 250}}}])
    a = {b["id"]: b for b in _guitar_blocks(scene_bake.to_paths_preset(p, "A"))}
    c = {b["id"]: b for b in _guitar_blocks(scene_bake.to_paths_preset(p, "C"))}
    assert c["cb"]["params"] == {"gain": 2.58} and c["dl"]["params"] == {"time": 250}
    assert a["cb"]["params"] == {"gain": 6}                 # ramené au DÉFAUT du catalogue
    assert a["dl"]["params"] == {"time": 500}               # ramené à la BASE du bloc ; `mix` jamais touché : absent


# ── `None` dans scene.blocks = « pas de clé » : le moteur ET l'écran/les diodes (2026-10-15) ──
@pytest.mark.parametrize("sblk, base_bypass, on", [
    ({"d1": None}, False, True),                       # id None -> base allumée
    ({"d1": None}, True, False),                       # id None -> base coupée
    ({"d1": None, "drive": False}, False, False),      # id None -> la clé de TYPE décide
    ({"d1": None, "drive": True}, True, True),
    ({"drive": None}, True, False),                    # type None -> base
    ({"drive": None}, False, True),
    ({"d1": True, "drive": None}, True, True),         # l'id gagne toujours
    ({"d1": False, "drive": True}, False, False),
])
def test_none_dans_scene_blocks_meme_lecture_moteur_et_ecran(sblk, base_bypass, on):
    from bridge import preset_view
    b = {"id": "d1", "type": "drive", "bypass": base_bypass}
    baked = scene_bake._bake_block(b, sblk)
    assert (not baked["bypass"]) is on
    assert preset_view._block_on_in_scene({"id": "d1", "type": "drive", "bypass": base_bypass}, sblk) is on
