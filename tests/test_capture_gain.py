# SPDX-License-Identifier: GPL-3.0-or-later
"""Lire le gain dans le nom d'une capture (spec capture-gain v0.1, golem.fm 2026-09-14 —
canonique dans docs/blocks-doctrine.md « Addendum outboard »).

Le parseur vit dans app/capture-gain.js (Capture dial + modèle par défaut à la pose) : il est
joué par NODE contre la table de cas partagée avec golem.fm — tests/capture-gain-cases.json,
copie de maestrium/conception/capture-gain-cases.json (34 noms, 15 packs, tous RÉELS, API
TONE3000). La même table est jouée là-bas : deux implémentations, une vérité.
Exigé : 34/34 noms, 15/15 ordres, 30/30 défauts (voice + other par pack)."""

import json
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


def _run():
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent : le parseur JS ne peut pas être joué ici")
    r = subprocess.run([node, os.path.join(HERE, "capture_gain_check.mjs")], capture_output=True, text=True)
    assert r.stdout.strip(), r.stderr
    return json.loads(r.stdout), r.returncode


def test_table_partagee_jouee_en_entier():
    out, rc = _run()
    assert out["names"]["total"] == 34 and out["order"]["total"] == 15 and out["defaults"]["total"] == 30, out
    assert out["names"]["fails"] == [], json.dumps(out["names"]["fails"], ensure_ascii=False, indent=1)
    assert out["order"]["fails"] == [], json.dumps(out["order"]["fails"], ensure_ascii=False, indent=1)
    assert out["defaults"]["fails"] == [], json.dumps(out["defaults"]["fails"], ensure_ascii=False, indent=1)
    assert rc == 0


def test_la_table_est_celle_de_la_spec():
    t = json.load(open(os.path.join(HERE, "capture-gain-cases.json")))
    assert t["spec"].startswith("capture-gain v0.1")
    assert {"name", "gain"} <= set(t["names"][0]) and {"models", "order", "defaults"} <= set(t["packs"][0])
