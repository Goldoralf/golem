# SPDX-License-Identifier: GPL-3.0-or-later
"""Genres (docs/genres.md, validé le 2026-10-06) : 17 familles ; un preset porte des FAMILLES (0 à 2)."""
import json
import os
import re

from bridge import genres as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_les_familles_de_l_app_sont_celles_des_donnees():
    """app/lib.js garde une COPIE des familles (rendu synchrone) : elle ne doit jamais diverger de
    config/genres.json — trois copies à la main avaient déjà divergé (brazilian, country)."""
    js = open(os.path.join(ROOT, "app", "lib.js"), encoding="utf-8").read()
    block = js[js.index("export const GENRE_FAMILIES"):]
    block = block[:block.index("];")]
    app = re.findall(r"\['([^']+)', '([^']+)'\]", block)
    assert app == G.families() and len(app) == 17


def test_chaque_ancien_style_a_une_famille_qui_existe():
    ids = {f for f, _ in G.families()}
    assert set(G.LEGACY.values()) <= ids
    old = ["djent", "metal", "punk", "math rock", "rock", "pop", "funk", "soul", "blues", "jazz", "manouche",
           "rap", "electronic", "ambient", "reggae", "latin", "folk", "world", "traditionnal", "classical"]
    assert all(G.family_of(s) in ids for s in old)


def test_la_migration_garde_l_ordre_sans_doublon_et_deux_au_plus():
    p = {"styles": ["djent", "math rock", "metal", "jazz"]}
    assert G.migrate_styles(p) and p == {"styles": ["metal", "rock"], "style": "metal"}
    assert not G.migrate_styles(p)                             # idempotent
    p = {"style": "manouche"}
    G.migrate_styles(p)
    assert p["styles"] == ["jazz"] and p["style"] == "jazz"
    p = {"styles": ["nope", "metalcore"]}                       # inconnu abandonné, sous-genre -> sa famille
    G.migrate_styles(p)
    assert p["styles"] == ["metal"]
    p = {"styles": []}
    G.migrate_styles(p)
    assert p == {"styles": [], "style": None}


def test_un_preset_charge_porte_des_familles():
    from bridge.store import migrate_config
    p = migrate_config({"id": "t", "name": "T", "styles": ["rap", "soul"], "lanes_v": 2, "lanes": [], "scenes": [{"id": "A"}]})
    assert p["styles"] == ["hip-hop", "rnb"] and p["style"] == "hip-hop"


def test_l_apercu_choisit_sa_di_par_famille():
    from bridge.preview import _bucket
    assert _bucket("guitar", "metal") == "guitar/high-gain"
    assert _bucket("guitar", "rock") == "guitar/crunch"
    assert _bucket("guitar", "jazz") == "guitar/clean"
    assert _bucket("bass", "metal") == "bass/pick"


def test_la_liste_de_golem_fm_passe_devant_la_copie(tmp_path, monkeypatch):
    """golem.fm est propriétaire : sa liste (reçue au battement) l'emporte dès qu'elle est au moins aussi récente ;
    une réponse invalide ne remplace rien ; sa table des anciens styles est lue avant la nôtre."""
    from bridge import golemfm
    local = json.load(open(os.path.join(ROOT, "config", "genres.json"), encoding="utf-8"))
    monkeypatch.setattr(G, "GENRES_FILE", str(tmp_path / "genres.json"))
    monkeypatch.setattr(G, "REMOTE_FILE", str(tmp_path / "genres.remote.json"))
    json.dump(local, open(G.GENRES_FILE, "w"))
    G._cache.update(key=None, data=None)
    served = json.loads(json.dumps(local))
    served["version"] = 2
    served["families"][0]["label"] = "Heavy Metal"
    served["legacy"] = {"djent": ["metal", "djent"], "chiptune": ["electronic", "chiptune"]}
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(golemfm, "_req", lambda path, **kw: (200, served) if path == "/api/ext/genres" and kw.get("token") == "tok" else (401, None))
    assert G.sync(2) and G.version() == 2 and G.families()[0] == ("metal", "Heavy Metal")
    assert not G.sync(2)                                          # déjà à jour : pas de nouvel appel utile
    assert G.family_of("djent") == "metal"
    assert G.label_of("bossa-nova") == "Bossa nova" and G.label_of("metal") == "Heavy Metal"
    monkeypatch.setattr(golemfm, "_req", lambda path, **kw: (200, {"families": [{"id": "x"}]}))
    assert not G.sync(3) and G.version() == 2                     # invalide : on garde ce qu'on a
