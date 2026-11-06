# SPDX-License-Identifier: GPL-3.0-or-later
"""Les catégories offertes à chaque RÔLE de lane vivent en donnée (effects.json `role_categories`,
v11) : le Designer du rack, le tiroir de golem.fm et le vocabulaire de son IA lisent la même table
(demande 2026-09-14). Ce test garde la table cohérente avec le catalogue et la doctrine."""

import json
import os

from bridge import rigstatus

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _fx():
    return json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json")))


def test_la_table_ne_nomme_que_des_categories_du_catalogue():
    fx = _fx()
    rc = {k: v for k, v in fx["role_categories"].items() if not k.startswith("_")}
    known = set(fx["categories"]) | {"keys", "pads"}
    assert set(rc) == {"guitar", "line", "bass", "voice", "keys", "keys-pads", "pads", "drums"}
    for role, cats in rc.items():
        assert cats and set(cats) <= known, (role, set(cats) - known)
        assert len(cats) == len(set(cats))
    assert rc["keys"] == rc["pads"] == rc["keys-pads"]


def test_la_doctrine_voix_est_dans_la_donnee():
    rc = _fx()["role_categories"]
    voice = set(rc["voice"])
    assert {"drive", "amp", "cab", "filter"}.isdisjoint(voice)      # ni ampli, ni cab, ni disto (patches.md §12)
    assert {"lofi", "preamp", "dynamics", "eq", "pitch"} <= voice    # la seule saturation ouverte : Grit
    assert "amp" not in rc["keys"] and "pitch" not in rc["keys"]     # claviers : aucun ampli, pas de Whammy


def test_le_catalogue_pousse_porte_la_table_sans_le_commentaire():
    cat = rigstatus.catalog()
    assert cat["catalog_version"] >= 11
    assert set(cat["role_categories"]) == {"guitar", "line", "bass", "voice", "keys", "keys-pads", "pads", "drums"}
    assert not any(k.startswith("_") for k in cat["role_categories"])


def test_le_tamis_fin_role_blocks_est_coherent_et_pousse():
    """v15 (docs/drums-kit.md) : chaque bloc de role_blocks.<role> existe, n'est pas en quarantaine et vit dans
    une catégorie que role_categories.<role> autorise ; la table part dans le catalogue poussé."""
    import json, os
    from bridge import config as C, rigstatus
    fx = json.load(open(os.path.join(C.ROOT, "library", "catalog", "effects.json")))
    types = {e["type"]: e for e in fx["effects"]}
    rb = {k: v for k, v in fx["role_blocks"].items() if not k.startswith("_")}
    assert "drums" in rb and "drumkit" in rb["drums"] and "amp-nam" not in rb["drums"] and "tuner" not in rb["drums"]
    for role, blocks in rb.items():
        cats = set(fx["role_categories"][role])
        for t in blocks:
            assert t in types and not types[t].get("quarantine"), (role, t)
            assert types[t]["category"] in cats, (role, t, types[t]["category"])
    assert rigstatus.catalog()["role_blocks"]["drums"] == rb["drums"]


def test_une_guitare_ne_voit_pas_la_batterie():
    """2026-10-25 : une lane guitare proposait la catégorie Drums (le Drum Kit, grisé). guitar et line voient tout le
    catalogue SAUF la batterie — sans la table, un rôle absent voit tout, et golem.fm aussi."""
    fx = _fx()
    for role in ("guitar", "line"):
        assert set(fx["role_categories"][role]) == set(fx["categories"]) - {"drums"}, role
