# SPDX-License-Identifier: GPL-3.0-or-later
"""AUDIT 2026-09-13, m4 : un id de preset garde ses lettres."""
from bridge.store import _safe_id


def test_les_accents_tombent_sans_emporter_la_lettre():
    assert _safe_id("Été") == "ete"
    assert _safe_id("Rêve à Paris") == "reve-a-paris"
    assert _safe_id("Paper Kite") == "paper-kite"                   # inchangé pour l'existant


def test_deux_noms_non_latins_ne_partagent_pas_un_fichier():
    a, b = _safe_id("日本"), _safe_id("中国")
    assert a != b and a.startswith("untitled-") and b.startswith("untitled-")
    assert _safe_id("") == "untitled" and _safe_id(None) == "untitled"


def test_un_id_deja_sur_reste_identique():
    for pid in ("velvetine", "1983", "polaris-ii", "sandbox-try"):
        assert _safe_id(pid) == pid
