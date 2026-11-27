# SPDX-License-Identifier: GPL-3.0-or-later
"""LES ÉPINGLES SE TIENNENT (2026-11-27, docs/release-checklist.md A1). Chaque composant que golem installe a UNE copie de
son numéro de version, et tout le reste s'en déduit ou la répète sous contrôle. Sans ce test, un changement de version
qui oublie un fichier ne se voyait qu'à l'installation : `install-golem-fx.sh` portait sa propre copie de la version de
golem-fx, l'essai à blanc de l'installateur disait encore « Golem Engine 9.9-g1 » sous une épingle à 9.9-g8."""
import json
import os
import re

import pytest

from provision import golem_engine as GE
from provision import golem_fx as GF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def _pins(system):
    return json.loads(_read("provision", system, "pins.json"))


def _code(text):
    """Le texte sans ses lignes de commentaire (shell, Python) : un commentaire peut raconter l'histoire d'une version."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


# ── golem-fx : provision/golem_fx.py VERSION ─────────────────────────────────────────────────────────────────────────
def test_le_script_linux_de_golem_fx_n_a_pas_sa_copie_du_numero():
    sh = _code(_read("provision", "install-golem-fx.sh"))
    assert "golem_fx as G; print(G.VERSION)" in sh
    assert not re.search(r"\b\d+\.\d+(\.\d+)?\b", sh.split("GFX_ASSET=")[0].split("GFX_VERSION=")[1]), \
        "install-golem-fx.sh : la version se lit dans provision/golem_fx.py, pas ici"


@pytest.mark.parametrize("system", ["windows", "macos"])
def test_pins_json_de_golem_fx_dit_la_meme_version_que_le_module(system):
    p = _pins(system)["golem_fx"]
    assert p["version"] == GF.VERSION
    assert f"/golem-fx-{GF.VERSION}/" in p["url"] and re.fullmatch(r"[0-9a-f]{64}", p["sha256"])
    assert f"golem-fx-{GF.VERSION} " in p["_comment"], "le commentaire de l'épingle cite une autre release"


def test_le_manifeste_des_composants_dit_la_version_de_golem_fx():
    comp = next(c for c in json.loads(_read("provision", "components.json"))["components"] if c["id"] == "golem-fx")
    assert comp["version"] == GF.VERSION and comp["url"].endswith(f"/golem-fx-{GF.VERSION}")


def test_downloads_sha256_n_epingle_qu_une_release_de_golem_fx_et_du_moteur():
    urls = [ln.split()[1] for ln in _read("provision", "downloads.sha256").splitlines()
            if ln and not ln.startswith("#") and len(ln.split()) == 2]
    fx = {m.group(1) for u in urls if (m := re.search(r"/golem-fx-([^/]+)/", u))}
    eng = {m.group(1) for u in urls if (m := re.search(r"/golem-engine-([^/]+)/", u))}
    assert fx == {GF.VERSION} and eng == {GE.VERSION}


# ── Golem Engine : provision/golem_engine.py VERSION (Linux), pins.json (Windows) ────────────────────────────────────
def test_le_script_linux_du_moteur_lit_la_version_du_module():
    sh = _code(_read("provision", "install-golem-engine.sh"))
    assert "import golem_engine as G" in sh and not re.search(r"9\.\d+-g\d+", sh)


def test_pins_json_du_moteur_tient_sa_version_dans_son_adresse():
    p = _pins("windows")["golem_engine"]
    assert f"/golem-engine-{p['version']}/" in p["url"] and re.fullmatch(r"[0-9a-f]{64}", p["sha256"])
    assert GE.pinned_version("win32") == p["version"] and GE.pinned_version("linux") == GE.VERSION


# ── ce qui AFFICHE une version la lit, sans la recopier ──────────────────────────────────────────────────────────────
def test_l_essai_a_blanc_de_l_installateur_lit_les_versions():
    dry = _read("installer", "dry_step.py")
    assert "_pinned('golem_engine')" in dry and "_pinned('golem_fx')" in dry
    assert not re.search(r"Golem Engine 9\.\d", dry) and not re.search(r"golem-fx \d+\.\d", dry)


def test_le_manifeste_des_parametres_vient_du_commit_de_la_release_epinglee():
    """library/catalog/golem-fx-plugins.json est régénéré depuis golem-fx (tools/sync-golem-fx-manifest.py) : son commit
    doit être celui que la release épinglée a construit. Les commentaires des épingles le citent (7 chiffres) — c'est le
    seul recoupement possible sans le dépôt golem-fx (la CI ne l'a pas)."""
    commit = json.loads(_read("library", "catalog", "golem-fx-plugins.json"))["golem_fx_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    for where in (_pins("windows")["golem_fx"]["_comment"], _pins("macos")["golem_fx"]["_comment"],
                  _read("provision", "downloads.sha256")):
        assert f"golem-fx {commit[:7]}" in where, "une épingle cite un autre commit de golem-fx que le manifeste"


# ── la doc qui cite l'épingle (docs/installer.md, la table des épingles) ─────────────────────────────────────────────
def test_la_doc_de_l_installateur_cite_la_release_epinglee():
    assert f"golem-fx-{GF.VERSION}" in _read("docs", "installer.md")
