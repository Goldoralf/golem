# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests à froid du chantier « une seule source d'intention + transport découplé »
(audit 2026-08-12 §3 · docs/pedalboards.md §10).

Trois résolutions, chacune sans matériel :
  · l'INTENTION : foot.py compile ses tables (CC=scène, CC=stomp, pédales, appui long) depuis
    le contrat (config/pedalboard/contract.json, arrivé par wire_contract().intent) — les
    valeurs en dur d'avant sont devenues DEFAULT_INTENT, le REPLI, même schéma ;
  · le TRANSPORT : resolve_port() choisit le port aseqdump selon le descripteur —
    din-soundcard (défaut, comportement historique) ou usb (port_match), port absent = None
    (la boucle _supervise réessaie, comme pour un DIN manquant) ;
  · la RECETTE de charge : le descripteur déclare un NOM, routes_system._LOAD_RECIPES résout —
    plus de `if` par appareil, recette inconnue refusée (400).

L'état module de foot (tables globales) est restauré par fixture : test_foot_feed.py compte
sur les valeurs par défaut.
"""
import asyncio

import pytest

from bridge import foot, inputmap, pedalboard


# ── fabriques de lignes aseqdump (mêmes gabarits que test_foot_feed) ─────────────────────────
def _cc(ch, cc, val):
    return f" 20:0   Control change          {ch}, controller {cc}, value {val}"


@pytest.fixture
def intent_reset():
    """Rend les tables par défaut après le test — les autres modules de test y comptent."""
    yield
    foot.apply_intent(None)


# ── l'intention : compilation + repli ────────────────────────────────────────────────────────
def test_repli_egal_aux_tables_historiques():
    """DEFAULT_INTENT compilé = exactement les tables qui étaient en dur (contrat gelé). Si ce
    test casse, le repli a divergé du contrat — précisément ce que le chantier interdit."""
    foot.apply_intent(None)
    assert foot.SCENE_CC == {20: "A", 21: "B", 22: "C", 23: "D", 24: "E"}
    assert foot.STOMP_CC == {30: 6, 31: 7, 32: 8, 33: 9, 34: 10}
    assert (foot.VOLUME_CC, foot.TREADLE_CC) == (7, 11)
    assert foot.DIGIT_OF_SWITCH == {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 0}
    assert foot.SELECT_SWITCH == 1
    # 1,5 s depuis le 2026-09-21 (0,5 s : un retour appuyé en scène A entrait en sélection sans le
    # dire, et la scène suivante devenait un chiffre — tests/test_foot_select_visible.py)
    assert (foot.LONGPRESS_S, foot.SELECT_TIMEOUT_S) == (1.5, 8.0)


def test_repli_identique_au_contrat_du_depot():
    """Le fichier config/pedalboard/contract.json et DEFAULT_INTENT doivent compiler les MÊMES
    tables : le repli est la même vérité dans le même schéma, pas une deuxième."""
    assert foot._compile_intent(pedalboard.contract()) == foot._compile_intent(None)


def test_intention_compilee_depuis_un_contrat(intent_reset):
    foot.apply_intent({
        "scenes": [{"switch": 1, "name": "A", "cc": 40}, {"switch": 2, "name": "B", "cc": 41}],
        "stomps": [{"switch": 6, "cc": 50}],
        "expression": [{"pedal": 1, "cc": 9}, {"pedal": 2, "cc": 12}],
        "select": {"switch": 2, "long_press_s": 1.0, "timeout_s": 3.0},
    })
    assert foot.SCENE_CC == {40: "A", 41: "B"}
    assert foot.STOMP_CC == {50: 6}
    assert (foot.VOLUME_CC, foot.TREADLE_CC) == (9, 12)
    assert foot.DIGIT_OF_SWITCH == {1: 1, 2: 2, 6: 6}
    assert foot.SELECT_SWITCH == 2
    assert (foot.LONGPRESS_S, foot.SELECT_TIMEOUT_S) == (1.0, 3.0)


def test_contrat_partiel_retombe_section_par_section(intent_reset):
    """Une section absente prend le repli SANS emporter les autres : un contrat qui ne parle
    que des scènes garde les stomps et l'appui long d'origine."""
    foot.apply_intent({"scenes": [{"switch": 1, "name": "A", "cc": 60}]})
    assert foot.SCENE_CC == {60: "A"}
    assert foot.STOMP_CC == {30: 6, 31: 7, 32: 8, 33: 9, 34: 10}
    assert foot.SELECT_SWITCH == 1


def test_contrat_malforme_ne_casse_jamais_les_tables(intent_reset):
    """Blindage : un cc non numérique fait retomber sur le REPLI complet — un pied qui obéit à
    l'ancienne table vaut mieux qu'un pied mort."""
    foot.apply_intent({"scenes": [{"switch": 1, "name": "A", "cc": "quarante"}]})
    assert foot.SCENE_CC == {20: "A", 21: "B", 22: "C", 23: "D", 24: "E"}


def test_intention_arrive_par_set_device_et_dispatche(intent_reset, monkeypatch):
    """Chemin complet : wire_contract() porte `intent`, set_device() l'applique, et un CC du
    NOUVEAU contrat déclenche la scène — la table en dur n'est plus consultée."""
    calls = []
    r = foot.FootReader(on_scene=calls.append, on_stomp=lambda sw, want=None: None)
    monkeypatch.setattr(foot, "_DEVICE", dict(foot._DEVICE, device_id="t", wire_channel=1))
    monkeypatch.setattr(foot, "_BOUND", {})
    monkeypatch.setattr(foot, "_HEARD", {"t": None})
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "fcb")
    foot.set_device({"device_id": "t", "wire_channel": 1, "note_edges": "clean", "note_base": 0,
                     "intent": {"scenes": [{"switch": 1, "name": "Z", "cc": 99}]}})
    r.feed(_cc(1, 99, 127))          # le CC du nouveau contrat…
    r.feed(_cc(1, 20, 127))          # …et l'ancien CC 20, qui ne doit plus rien faire
    assert calls == ["Z"]


# ── le transport : din par défaut, usb déclaré, port absent ──────────────────────────────────
LISTING = (" Port    Client name                      Port name\n"
           "  0:0    System                           Timer\n"
           " 20:0    Volt 276                         Volt 276 MIDI 1\n"
           " 24:0    HX Stomp                         HX Stomp MIDI 1\n")


def test_transport_din_par_defaut():
    """Sans transport (ou din-soundcard), le pied suit la carte son active — comportement
    historique, y compris le repli « volt » quand la carte n'a pas de nom."""
    assert foot.resolve_port(LISTING, None, "Volt 276") == "20:0"
    assert foot.resolve_port(LISTING, {"kind": "din-soundcard"}, "Volt 276") == "20:0"
    assert foot.resolve_port(LISTING, {}, None) == "20:0"        # repli « volt »


def test_transport_usb_ecoute_son_propre_port():
    """Un pédalier USB déclaré est écouté sur SON port ALSA — pas sur le DIN de la carte, même
    si elle est là."""
    assert foot.resolve_port(LISTING, {"kind": "usb", "port_match": "hx stomp"}, "Volt 276") == "24:0"


def test_transport_usb_port_absent_rend_none_sans_crash():
    """USB débranché (ou motif vide) = None, comme le DIN manquant : la boucle _supervise
    réessaie, rien n'explose."""
    assert foot.resolve_port(LISTING, {"kind": "usb", "port_match": "morningstar"}, "Volt 276") is None
    assert foot.resolve_port(LISTING, {"kind": "usb"}, "Volt 276") is None
    assert foot.resolve_port("", {"kind": "usb", "port_match": "hx"}, None) is None


def test_find_port_usb_ne_depend_pas_de_la_carte_son(monkeypatch):
    """_find_port en transport usb ne consulte JAMAIS midi_out._active_card_midi : le pédalier
    USB doit être entendu même quand la carte son a disparu.

    ⚠ On n'importe PAS le vrai bridge.midi_out : test_pedalboard_believed le remplace par
    sys.modules, et l'attribut de package posé par un vrai import rendrait ce remplacement
    inopérant (leçon du 2026-08-13). Même technique ici : un faux module qui EXPLOSE s'il
    est consulté."""
    import sys

    class _FakeMidiOut:
        @staticmethod
        def _active_card_midi():
            raise AssertionError("la carte son a été consultée — le transport usb n'en dépend pas")

    monkeypatch.setitem(sys.modules, "bridge.midi_out", _FakeMidiOut)
    monkeypatch.setattr(foot, "_DEVICE",
                        dict(foot._DEVICE, transport={"kind": "usb", "port_match": "hx stomp"}))
    monkeypatch.setattr(foot.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(foot.subprocess, "check_output", lambda *a, **k: LISTING)
    monkeypatch.delenv("GOLEM_FCB_PORT", raising=False)
    r = foot.FootReader(on_scene=lambda s: None, on_stomp=lambda sw, want=None: None)
    assert r._find_port() == "24:0"


def test_set_device_transport_change_rebranche_le_lecteur(monkeypatch):
    """Changer de transport doit tuer l'aseqdump courant (rebind) : il écoute l'ancien port et
    personne d'autre ne le sait. Transport inchangé -> pas de rebind inutile."""
    rebinds = []

    class _Reader:
        def rebind(self):
            rebinds.append(1)

    monkeypatch.setattr(foot, "_READER", _Reader())
    monkeypatch.setattr(foot, "_BOUND", {})
    monkeypatch.setattr(foot, "_DEVICE",
                        {"device_id": "t", "wire_channel": 1, "note_edges": "clean",
                         "note_base": 0, "transport": {"kind": "din-soundcard"},
                         "edge_switches": None})
    wire = {"device_id": "t", "wire_channel": 1, "note_edges": "clean", "note_base": 0,
            "transport": {"kind": "usb", "port_match": "hx"}}
    foot.set_device(wire)
    assert rebinds == [1]
    foot.set_device(dict(wire))          # même transport : rien à rebrancher
    assert rebinds == [1]


def test_wire_contract_porte_transport_et_intention(monkeypatch):
    """wire_contract() est LE canal : transport du descripteur (défaut din-soundcard quand il
    ne dit rien) + intention du dépôt, pour une application unique par set_device()."""
    dev = {"channel": 5, "quirks": {}, "capabilities": {}}
    monkeypatch.setattr(pedalboard, "active",
                        lambda: {"id": "x", "name": "x", "device": dev, "source": "declared"})
    w = pedalboard.wire_contract()
    assert w["transport"] == {"kind": "din-soundcard"}
    assert w["intent"].get("scenes"), "l'intention du dépôt doit voyager avec le contrat de fil"
    dev["transport"] = {"kind": "usb", "port_match": "hx stomp"}
    assert pedalboard.wire_contract()["transport"] == {"kind": "usb", "port_match": "hx stomp"}


# ── la recette de charge : déclarée par le descripteur, résolue par le bridge ────────────────
def test_recettes_des_descripteurs_du_depot_sont_connues_du_bridge():
    """Chaque descripteur livré qui déclare une recette doit la trouver dans _LOAD_RECIPES —
    c'est l'anti-dérive : ajouter un descripteur sans sa recette casse ICI, pas au flash."""
    from bridge import routes_system
    devs = pedalboard.devices()
    assert "fcb1010-uno2" in devs and "fcb1010-uno104" in devs
    declared = {(d.get("load") or {}).get("recipe") for d in devs.values()}
    declared.discard(None)
    assert declared, "au moins une recette déclarée dans le dépôt"
    assert declared <= set(routes_system._LOAD_RECIPES), \
        "recette déclarée par un descripteur mais inconnue du bridge : %r" % (
            declared - set(routes_system._LOAD_RECIPES))


def test_recette_inconnue_refusee_400(monkeypatch):
    """Un appareil sans recette connue (appris, `load: none`, faute de frappe) est REFUSÉ —
    envoyer le mauvais dump à une puce ne se voit qu'en jouant."""
    from bridge import routes_system
    monkeypatch.setattr(pedalboard, "active",
                        lambda: {"id": "learned-x", "device": {"load": {}}})
    resp = asyncio.run(routes_system.pedalboard_load())
    assert resp.status_code == 400
