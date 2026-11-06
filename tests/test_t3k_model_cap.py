# SPDX-License-Identifier: GPL-3.0-or-later
"""Plafond de modèles à l'installation TONE3000 : 8 par pack (anti-bloat), 16 pour un pack
OUTBOARD — un balayage de gain tronqué dans l'ordre du pack perdait ses prises les plus propres
(BAE 1073MP, 2026-09-14 : les A 40-60 dB tombaient, le défaut « le plus propre » devenait 70 dB)."""

import pytest

from bridge import rig
from bridge import routes_t3k as R

# les deux pages de chaque liste : 12 A2, puis 12 A1 jumeaux + un custom sans jumeau
PAGES = {
    "/api/v1/models?tone_id=1&architecture=2&page=1": {"data": [{"id": 10 + i, "name": f"m{i}"} for i in range(10)],
                                                      "page": 1, "total_pages": 2},
    "/api/v1/models?tone_id=1&architecture=2&page=2": {"data": [{"id": 20, "name": "m10"}, {"id": 21, "name": "m11"}],
                                                      "page": 2, "total_pages": 2},
    "/api/v1/models?tone_id=1&page=1": {"data": [{"id": 100 + i, "name": f"m{i}"} for i in range(10)], "page": 1, "total_pages": 2},
    "/api/v1/models?tone_id=1&page=2": {"data": [{"id": 110, "name": "m10"}, {"id": 111, "name": "m11"}, {"id": 112, "name": "custom"}],
                                        "page": 2, "total_pages": 2},
}


def test_plafond_par_nature():
    assert R.model_cap("amp") == 8 == R.model_cap(None) == R.model_cap("pedal")
    assert R.model_cap("outboard") == 16
    assert R.MAX_MODELS_OUTBOARD * 300_000 < 6_000_000    # ~300 Ko par modèle : 16 tiennent en 5 Mo


@pytest.fixture
def api(monkeypatch):
    calls = []
    monkeypatch.setattr(R._t3k, "api_get", lambda p: (calls.append(p), (200, PAGES[p]))[1])
    return calls


def test_fetch_models_lit_toutes_les_pages_et_ecarte_le_jumeau_a1(monkeypatch, api):
    """L'API pagine par 10 : un pack de 12 perdait ses deux derniers modèles. Et un A1 qui porte
    le nom d'un A2 est la même capture ré-entraînée : un seul cran au Capture dial.
    ⚠ La règle dépend de l'OS (rig.nam_unreadable) : le test l'épingle, sinon il échoue sous Windows."""
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    got = R._fetch_models(1)
    assert [m["id"] for m in got] == list(range(10, 20)) + [20, 21, 112]   # 12 A2 + le custom sans jumeau
    assert len(api) == 4                                                    # 2 pages × 2 listes, pas plus


@pytest.mark.parametrize("plat", ["win32", "darwin"])
def test_fetch_models_hors_linux_met_l_a1_en_tete_et_garde_l_a2(monkeypatch, api, plat):
    """Le NAM de Windows/macOS ne lit pas l'A2 : l'A1 passe en tête (défaut d'un bloc sans épingle),
    l'A2 jumeau reste derrière pour les patches faits sous Linux qui l'épinglent par son id."""
    monkeypatch.setattr(rig, "_platform", lambda: plat)
    got = R._fetch_models(1)
    assert [m["id"] for m in got] == list(range(100, 110)) + [110, 111, 112] + list(range(10, 20)) + [20, 21]
    assert len(api) == 4
