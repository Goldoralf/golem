# SPDX-License-Identifier: GPL-3.0-or-later
"""Clé `bench` du catalogue (v26) : un bloc pas encore passé au banc de gel (tools/check-block-stall.py).

golem.fm la lit pour que son IA ne propose pas ces blocs ; le Designer du rack les offre quand même.
Une seule valeur, « pending », retirée quand le banc conclut proprement — un bloc qui échoue part en
`quarantine`. Ce test empêche les deux dérives : une valeur inventée, et un bloc à la fois en attente et en
quarantaine (deux natures contradictoires que les lecteurs ne savent pas départager)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _catalog():
    return json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json")))


def test_bench_value_is_only_pending():
    cat = _catalog()
    assert cat["catalog_version"] >= 26
    for e in cat["effects"]:
        if "bench" in e:
            assert e["bench"] == "pending", e["type"]


def test_bench_and_quarantine_are_exclusive():
    for e in _catalog()["effects"]:
        assert not ("bench" in e and "quarantine" in e), e["type"]


def test_bench_comment_documents_the_key():
    assert "check-block-stall" in _catalog()["_bench_comment"]
