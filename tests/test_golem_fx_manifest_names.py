# SPDX-License-Identifier: GPL-3.0-or-later
"""Chaque nom de paramètre que golem cherche dans un plugin golem-fx existe TEL QUEL dans le manifeste
(library/catalog/golem-fx-plugins.json). golem_rig.lua (REAPER) ne cherche plus que le nom exact (2026-11-20) : son
ancien repli « contient ce nom, sans casse » parcourait pairs(), dont l'ordre n'est pas défini — un nom ambigu
pouvait viser un autre potard. Un nom changé côté golem-fx casse ce test au lieu de régler le mauvais paramètre."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "library" / "catalog"


def _load(name):
    return json.loads((CAT / name).read_text(encoding="utf-8"))


def test_chaque_parametre_golem_fx_se_trouve_par_son_nom_exact():
    engine = _load("effects-golem-engine.json")["effects"]
    plugins = _load("golem-fx-plugins.json")["plugins"]
    by_type = {e.get("type"): e for e in _load("effects.json")["effects"] if isinstance(e, dict)}
    missing, n = [], 0
    for btype, spec in engine.items():
        if not (isinstance(spec, dict) and spec.get("golem_fx") and spec.get("vst3")):
            continue
        plugin = plugins.get(spec["vst3"])
        assert plugin, f"{btype}: {spec['vst3']} not in the manifest"
        ranges = plugin.get("params") or {}
        absent = spec.get("absent") or {}
        for d in by_type.get(btype, {}).get("params") or []:      # le catalogue, comme apply_golem_fx
            if absent.get(d.get("id")):
                continue
            label = (spec.get("params") or {}).get(d.get("id")) or d.get("name")
            n += 1
            if label not in ranges:
                missing.append((btype, "param", label))
        for label in spec.get("init") or {}:                      # l'init écrit sous REAPER
            n += 1
            if label not in ranges:
                missing.append((btype, "init", label))
        for dp in ((plugin.get("descriptor") or {}).get("params") or {}).values():   # la fiche du bloc
            if isinstance(dp, dict) and dp.get("name"):
                n += 1
                if dp["name"] not in ranges:
                    missing.append((btype, "descriptor", dp["name"]))
    assert n > 1000 and not missing, missing[:20]
