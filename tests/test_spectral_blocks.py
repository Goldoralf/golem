# SPDX-License-Identifier: GPL-3.0-or-later
"""Les blocs spectraux (docs/spectral.md, lot 0 — 2026-09-25) : Spectral Comp et Stretch sont au catalogue avec
des potards écrits en NORMALISÉ par taper connu (`map.mode: pow`, jamais la dichotomie d'affichage — ces plugins
relisent en retard), leurs défauts s'écrivent à la compile (`defaults: compile` : le défaut du plugin est un
piège — 1:1, direct coupé), et les interrupteurs de module de Stretch suivent leurs potards."""
import json
import os

from bridge import compile_rig as CR, config as C


def _catalog():
    return json.load(open(os.path.join(C.ROOT, "library", "catalog", "effects.json")))


def _block(t):
    return next(e for e in _catalog()["effects"] if e.get("type") == t)


def test_les_deux_blocs_sont_au_catalogue_avec_des_tapers_connus():
    cat = _catalog()
    assert cat["catalog_version"] >= 23
    sc, px, fz = _block("spectral-comp"), _block("stretch"), _block("freeze")
    assert sc["plugin"].startswith("CLAP: Spectral Compressor") and px["plugin"].startswith("CLAP: PaulXStretch")
    assert sc["category"] == "dynamics" and px["category"] == "reverb"
    assert sc.get("defaults") == "compile" and px.get("defaults") == "compile" and fz.get("defaults") == "compile"
    assert fz["plugin"] == "CLAP: GoleM Freeze (GoleM)" and fz["category"] == "reverb"
    assert next(p for p in fz["params"] if p["id"] == "freeze")["type"] == "bool"      # le geste = un paramètre
    assert next(p for p in fz["params"] if p["id"] == "mix").get("exp") is True         # le gel entre à la pédale EXP
    for b in (sc, px, fz):
        for p in b["params"]:
            m = p.get("map") or {}
            assert m.get("mode") in ("pow", "raw"), (b["type"], p["id"])          # jamais « norm » (dichotomie)
            if m.get("mode") == "pow":
                assert {"min", "max", "exp"} <= set(m), (b["type"], p["id"])
            if p.get("type") == "bool":
                assert m.get("mode") == "raw"
        assert all(p.get("default") is not None for p in b["params"]), b["type"]
    thru = next(p for p in px["params"] if p["id"] == "thru")
    assert thru["default"] is True                          # un insert qui avale le direct est un silence
    win = next(p for p in sc["params"] if p["id"] == "window")
    assert win["values"] == [4, 5, 6] and win["map"] == {"mode": "raw"}   # ordre brut - 6 : 1024/2048/4096


def test_les_defauts_du_catalogue_s_ecrivent_a_la_compile_pour_ces_blocs_seulement():
    CR._FX_DEFS = None
    blocks = [{"id": "b1", "type": "spectral-comp", "params": {"thresh": -30}},
              {"id": "b2", "type": "stretch"},
              {"id": "b3", "type": "gate", "params": {}}]
    CR._fill_compile_defaults(blocks)
    sc, px, gate = blocks
    assert sc["params"]["thresh"] == -30 and sc["params"]["down"] == 4 and sc["params"]["window"] == "2048"
    assert px["params"]["thru"] is True and px["params"]["capture"] is False and px["params"]["amount"] == 4
    assert gate["params"] == {}                             # les autres blocs gardent les défauts du plugin


def test_les_interrupteurs_de_module_de_stretch_suivent_leurs_potards():
    blocks = [{"id": "b2", "type": "stretch", "params": {"spread": 30}},
              {"id": "b4", "type": "stretch", "params": {"spread": 0, "compress": 10, "spread_on": True}}]
    CR._expand_stretch(blocks)
    assert blocks[0]["params"]["spread_on"] is True and blocks[0]["params"]["comp_on"] is False
    assert blocks[1]["params"]["spread_on"] is True and blocks[1]["params"]["comp_on"] is True   # explicite : gardé
