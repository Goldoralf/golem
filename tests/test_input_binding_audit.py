# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit des entrées 2026-10-10 (docs/audit-2026-10-10-entrees.md) : de la carte au preset, une lane s'assied sur
l'entrée de SON RÔLE, son titre et son rôle suivent l'entrée, deux lanes d'un rôle se numérotent, et une carte
d'entrées n'hérite que d'une carte réglée. Carte de référence : IN 1 voix, IN 2 guitare (le mainteneur, micro 48 V en 1)."""
import copy
import json
import os

import pytest

from bridge import inputmap, patches, preset_view, store

CARD = {"card": "asio:Universal Audio Volt", "inputs": inputmap.with_nth([
    {"ch": "1", "role": "voice", "name": "Voice 1"}, {"ch": "2", "role": "guitar", "name": "Guitar 1"}])}


@pytest.fixture
def card(monkeypatch):
    monkeypatch.setattr(inputmap, "current", lambda *a, **k: copy.deepcopy(CARD))
    return CARD


def _lanes(p):
    return {L["id"]: L for L in store.lanes_of(copy.deepcopy(p))}


def test_une_lane_sans_entree_ni_liaison_prend_l_entree_de_son_role(card):
    p = {"lanes_v": 2, "lanes": [{"id": "guitar", "role": "guitar", "chain": {"pre": [], "split": None, "post": []}},
                                  {"id": "voice", "role": "voice", "chain": {"pre": [], "split": None, "post": []}}], "scenes": []}
    L = _lanes(p)
    assert (L["guitar"]["in_sel"], L["guitar"]["input"]) == ("2", 2)          # pas '1' parce qu'elle s'appelle guitar
    assert (L["voice"]["in_sel"], L["voice"]["input"]) == ("1", 1)


def test_un_preset_legacy_met_sa_chaine_guitare_sur_la_prise_guitare(card):
    p = {"guitar": {"chain": [{"type": "amp", "id": "a"}]}, "voice": {"chain": []}, "scenes": []}
    L = _lanes(p)
    assert L["guitar"]["input"] == 2 and L["guitar"]["role"] == "guitar"
    assert L["voice"]["input"] == 1 and L["voice"]["role"] == "voice"
    p["in"] = {"1": "1"}                                                         # un choix explicite reste respecté
    assert _lanes(p)["guitar"]["input"] == 1


def test_le_titre_et_le_role_d_une_lane_liee_sont_ceux_de_l_entree(card):
    p = {"lanes_v": 2, "lanes": [{"id": "g", "role": "guitar", "in_sel": "2", "in_role": "voice", "in_nth": 1,
                                  "chain": {"pre": [], "split": None, "post": []}}], "scenes": []}
    L = _lanes(p)["g"]
    assert (L["in_sel"], L["input"], L["in_name"], L["role"]) == ("1", 1, "Voice 1", "voice")   # « Voice 1 », pas « voice 1 »
    p["lanes"][0].update(in_role="guitar")
    L = _lanes(p)["g"]
    assert (L["in_sel"], L["in_name"], L["role"]) == ("2", "Guitar 1", "guitar")


def test_deux_lanes_d_un_meme_role_se_lient_a_guitar_1_et_guitar_2(card):
    two = {"card": "hw:XR18", "inputs": inputmap.with_nth([{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "guitar"}, {"ch": "3", "role": "voice"}])}
    doc = {"id": "duo", "name": "Duo", "role": "guitar", "lanes_v": 2, "scenes": [],
           "lanes": [{"id": "g1", "role": "guitar", "chain": {"pre": [], "split": None, "post": []}},
                     {"id": "g2", "role": "guitar", "chain": {"pre": [], "split": None, "post": []}}]}
    p = patches.as_preset(doc, two)
    assert [(L["in_sel"], L["in_nth"]) for L in p["lanes"]] == [("1", 1), ("2", 2)]
    p = patches.as_preset(doc, CARD)                                             # une seule guitare : la 2e attend, et le dit
    assert p["lanes"][0]["in_sel"] == "2" and p["lanes"][1]["in_sel"] == "NONE" and "#2" in p["lanes"][1]["bind_error"]


def test_une_carte_d_entrees_n_herite_que_d_une_carte_reglee_de_la_meme_identite(tmp_path, monkeypatch):
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    monkeypatch.setattr(inputmap, "_card_channels", lambda device: (2, 2))
    from bridge import cards
    monkeypatch.setattr(cards, "usb_of", lambda d: {"asio:UMC ASIO Driver": "1397:0509", "asio:Universal Audio Volt": "2b5a:0023"}.get(d))
    # 1. une autre carte connue (UMC) ne lègue pas ses rôles à la Volt
    json.dump({"card": "asio:UMC ASIO Driver", "inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar"}]},
              open(os.path.join(tmp_path, inputmap._slug("asio:UMC ASIO Driver") + ".json"), "w"))
    assert inputmap.inherit("asio:UMC ASIO Driver", "asio:Universal Audio Volt") is False
    # 2. une carte restée à ses défauts d'usine (pilote non configuré) ne lègue rien : la Volt prend SON semis
    json.dump(inputmap._seed("asio:unconfigured"), open(os.path.join(tmp_path, inputmap._slug("asio:unconfigured") + ".json"), "w"))
    assert inputmap.inherit("asio:unconfigured", "asio:Universal Audio Volt") is False
    # 3. un emballage générique RÉGLÉ par le musicien (ASIO4ALL, voix en 1) lègue toujours au pilote natif
    json.dump({"card": "asio:ASIO4ALL v2", "inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar"}]},
              open(os.path.join(tmp_path, inputmap._slug("asio:ASIO4ALL v2") + ".json"), "w"))
    assert inputmap.inherit("asio:ASIO4ALL v2", "asio:Universal Audio Volt") is True


def test_mac_la_carte_d_entrees_se_cle_sur_le_peripherique_ouvert_pas_sur_le_defaut(monkeypatch):
    from bridge import desktop_audio, cards
    monkeypatch.setattr(inputmap.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_audio, "configured_coreaudio_input", lambda: desktop_audio.DEFAULT_DEVICE)
    monkeypatch.setattr(cards, "mac_opened_input", lambda: "Volt 276")
    assert inputmap._card_device() == "coreaudio:Volt 276"
    monkeypatch.setattr(cards, "mac_opened_input", lambda: None)                 # REAPER pas encore là : le défaut, dit tel quel
    assert inputmap._card_device() == "coreaudio:" + desktop_audio.DEFAULT_DEVICE
