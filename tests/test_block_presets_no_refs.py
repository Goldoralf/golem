# SPDX-License-Identifier: GPL-3.0-or-later
"""Aucun preset de bloc ne nomme un artiste (2026-11-22).

Les presets d'usine de golem-fx portent des références (artiste, morceau, source) pour ses prompts d'IA. Elles restent
chez lui : ce dépôt est public. Le semis (tools/sync-golem-fx-presets.py) les a recopiées du 2026-11-13 au 2026-11-22
dans 166 fichiers ; ce test échoue si le champ revient, par le semis ou à la main."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = ("refs", "artist", "song")


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def test_aucun_preset_de_bloc_ne_porte_de_reference():
    bad = []
    for f in sorted((ROOT / "library" / "block-presets").glob("*/*.json")):
        keys = set(_keys(json.loads(f.read_text(encoding="utf-8"))))
        if keys & set(FORBIDDEN):
            bad.append(f"{f.parent.name}/{f.name}: {sorted(keys & set(FORBIDDEN))}")
    assert not bad, f"{len(bad)} block preset(s) carry a reference: {bad[:5]}"


def test_le_semis_ne_recopie_pas_les_references():
    spec = importlib.util.spec_from_file_location("sync_golem_fx_presets", ROOT / "tools" / "sync-golem-fx-presets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not set(FORBIDDEN) & set(mod.FIELDS)
