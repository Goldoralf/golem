# SPDX-License-Identifier: GPL-3.0-or-later
"""`mode.band` — un mode déclare l'espace de destination des prises (docs/identity.md,
message-golem-modes-espaces.md §1.1). Même contrat que `mode.card`.

Ce qui est vérifié ici est ce qui ferait mal : une synchro ou un boot qui rebascule l'espace
tout seul, une bascule silencieuse pendant un enregistrement, et un id inconnu qui créerait
un espace. Lancer : .venv/bin/python -m pytest tests/test_mode_band.py -q
"""
import json

import pytest

from bridge import modes as modes_mod
from bridge import roster
from bridge.state import state


BANDS = [{"id": "b_perso", "name": "Earth is my Spaceship", "kind": "personal"},
         {"id": "b_night", "name": "Night Shift", "kind": "band"}]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    f = tmp_path / ".band.json"
    f.write_text(json.dumps({"band": {"id": "b_perso", "name": "Earth is my Spaceship",
                                      "source": "cache"}, "bands": BANDS}))
    monkeypatch.setattr(roster, "FILE", str(f))
    return f


def test_band_of_est_le_miroir_de_card_of():
    assert modes_mod.band_of({"band": "b_night"}) == "b_night"
    assert modes_mod.band_of({"band": "  "}) is None
    assert modes_mod.band_of({}) is None                  # absent = garde l'espace courant
    # ⚠ sur les définitions d'USINE, pas sur list_modes() : celui-ci fusionne la surcouche
    # LOCALE (config/modes.local/), donc un mode auquel l'utilisateur a donné un espace
    # faisait échouer ce test — il mesurait l'état de la machine, pas le contrat.
    for mid in ("pedalboard", "studio", "rehearsal", "gig", "show"):
        assert modes_mod.band_of(modes_mod.factory_def(mid)) is None, mid


def test_selectionner_un_espace_connu(cache):
    ok, res = roster.set_current("b_night")
    assert ok and res["id"] == "b_night" and res["source"] == "cache"
    assert json.load(open(cache))["band"]["id"] == "b_night"


def test_le_rack_ne_cree_jamais_un_espace(cache):
    ok, why = roster.set_current("b_inconnu")
    assert not ok and "inconnu" in why
    assert json.load(open(cache))["band"]["id"] == "b_perso"     # rien n'a bougé


def test_aucun_espace_est_un_choix_et_la_liste_survit(cache):
    """« Aucun » = les prises attendent sur le rack. La liste est un CACHE, pas une dérivée
    du courant : l'effacer ferait un aller sans retour."""
    ok, res = roster.set_current(None)
    assert ok and res is None
    d = json.load(open(cache))
    assert d["band"] is None and [b["id"] for b in d["bands"]] == ["b_perso", "b_night"]
    assert roster.set_current("b_night")[0]                       # le retour est possible


def test_une_synchro_ne_rebascule_pas_lespace(cache):
    """La règle qui compte : le catalogue vient du serveur, le CHOIX de la salle reste."""
    roster.set_current("b_night")
    payload = {"synced": "2026-09-07T10:00:00Z", "default": "b_perso",
               "bands": BANDS, "band": BANDS[0], "people": []}   # champs de transition servis
    d, rep = roster.reconcile(payload, roster.read())
    assert rep["current"] == "b_night" and d["band"]["id"] == "b_night"


def test_deux_taps_quand_une_prise_tourne(monkeypatch):
    """La prise en cours ne bouge pas — son tag est gelé au départ — mais ça se dit AVANT."""
    from bridge import routes_modes
    monkeypatch.setattr(state, "perf", {"recording": True}, raising=False)
    monkeypatch.setattr(state, "mode", {"id": "studio", "ui": {}}, raising=False)
    monkeypatch.setattr(modes_mod, "list_modes", lambda: [{"id": "rehearsal", "name": "Rehearsal",
                                                           "band": "b_night"}])
    monkeypatch.setattr(roster, "read", lambda: {"band": {"id": "b_perso"}, "bands": BANDS})
    import asyncio
    res = asyncio.run(routes_modes.set_mode({"id": "rehearsal"}))
    assert res.status_code == 409
    assert json.loads(bytes(res.body))["needs_confirm"] is True


def test_la_porte_de_sortie_du_kiosk_ne_demande_JAMAIS_confirmation(monkeypatch):
    """⚠ LE TEST QUI COMPTE LE PLUS DE CE FICHIER.

    Quitter un mode VERROUILLÉ, c'est l'appui long sur le logo — la seule porte de sortie du
    kiosk, et elle envoie `{id: "studio"}` SANS `confirm`. Le 2026-09-07, un mode Home qui
    déclarait un espace suffisait à la transformer en 409 : Gig verrouille l'UI, la porte
    répondait « confirm required », et l'utilisateur restait enfermé. Mesuré sur le rack, sur
    le scénario exact — et le dépôt est catégorique : on ne livre jamais un mode sans sa
    sortie testée, c'est déjà arrivé, il a fallu Alt+F4.
    """
    from bridge import routes_modes
    monkeypatch.setattr(state, "perf", {"recording": False}, raising=False)
    monkeypatch.setattr(state, "mode", {"id": "gig", "ui": {"locked": True}}, raising=False)
    monkeypatch.setattr(modes_mod, "list_modes",
                        lambda: [{"id": "studio", "name": "Home", "band": "b_perso", "ui": {}}])
    monkeypatch.setattr(modes_mod, "set_current", lambda mid: {"id": mid, "name": "Home", "ui": {}})
    monkeypatch.setattr(roster, "read", lambda: {"band": {"id": "b_night"}, "bands": BANDS})
    monkeypatch.setattr(roster, "set_current", lambda bid: (True, {"id": bid, "name": "x"}))
    import asyncio
    res = asyncio.run(routes_modes.set_mode({"id": "studio"}))
    assert res.get("ok") is True, "la porte de sortie doit s'ouvrir sans confirmation"


# ── LA RÈGLE : le groupe vient de golem.fm, sinon il n'existe pas (décision 2026-09-07) ──
def test_un_rack_jamais_connecte_ne_connait_aucun_groupe(tmp_path, monkeypatch):
    """Un GoleM qui ne s'est jamais appairé ne prononce pas le mot « groupe ».

    Ce n'est pas un cas dégradé : c'est le comportement NATIF. Le seed écrit à la main en
    août (`source: local-temporary`) était l'exception — et il a coûté cher : 30 prises
    taguées avec un id que le serveur ne connaissait pas, donc bloquées des mois avec pour
    seul symptôme un 404 que personne ne lit.

    Ce test verrouille les trois portes par lesquelles la notion pourrait revenir.
    """
    from bridge import routes_patches, takes
    monkeypatch.setattr(roster, "FILE", str(tmp_path / "absent.json"))

    # 1. le cache est vide, et l'API le dit sans inventer
    assert roster.read() == {}
    assert routes_patches.api_band() == {"band": None, "people": [], "bands": []}

    # 2. aucun id ne se résout — le rack ne fabrique JAMAIS un tag
    monkeypatch.setattr(takes, "_read_band", roster.read)
    assert takes.resolve_band("b_haw6vqzh5u") is None
    assert takes.resolve_band("night-shift") is None

    # 3. une prise se fait quand même : elle part sans tag et attend sur le disque
    monkeypatch.setattr(takes, "RECORDINGS", str(tmp_path))
    d = tmp_path / "perf-20260907-220000"
    d.mkdir()
    (d / "Mix.wav").write_bytes(b"RIFF")
    json.dump({"kind": "take", "band": None, "files": ["Mix.wav"]},
              open(d / "take.json", "w"))
    row = takes.index()[0]
    assert row["band"] is None and row["band_name"] is None

    # 4. et le web ne peut pas la taguer à distance tant que le roster n'est pas là
    out = takes.tag([{"uid": row["uid"], "band": "b_haw6vqzh5u"}])
    assert out["tagged"] == [] and out["skipped"][0]["reason"] == "band_unknown_on_rack"


def test_des_que_le_roster_arrive_la_notion_existe(cache, monkeypatch):
    """Le premier appairage est le moment où le groupe apparaît — pas avant."""
    from bridge import routes_patches, takes
    monkeypatch.setattr(takes, "_read_band", roster.read)
    assert len(routes_patches.api_band()["bands"]) == 2
    assert takes.resolve_band("b_night") == {"id": "b_night", "name": "Night Shift",
                                            "source": "cache"}
