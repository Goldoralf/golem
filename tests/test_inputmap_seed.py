# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests du seed d'inputmap depuis le probe (audit 2026-08-12 §3 chantier ④).

Le seed est une fonction pure (bridge/inputmap._seed) : on la teste sans toucher au
filesystem du dépôt ; les canaux de la carte sont fournis en monkeypatchant bridge.cards
(known/probe). La persistance (_load qui n'écrase JAMAIS une map existante) se teste en
redirigeant INPUTMAPS_DIR vers tmp_path — config/inputmaps/ du dépôt n'est jamais touché.
"""
import json

import pytest

from bridge import cards, config as C, first_run, inputmap


@pytest.fixture(autouse=True)
def _instrument(monkeypatch):
    """L'instrument noté à l'installation (config/instrument.json) est celui de LA MACHINE : sur le Mac du premier test
    réel (2026-11-04), une basse — et ces tests attendaient une guitare. Guitare ici, sauf test qui le dit."""
    monkeypatch.setattr(first_run, "instrument", lambda: None)


@pytest.fixture
def card(monkeypatch):
    """Déclare la carte vue par le registre : card({'Test8': (8, 8)})."""
    def _set(table):
        def _known(cid):
            if cid in table:
                n_in, n_out = table[cid]
                return {"id": cid, "inputs": n_in, "outputs": n_out}
            return None
        monkeypatch.setattr(cards, "known", _known)
        monkeypatch.setattr(cards, "probe", lambda cid: None)   # carte pas branchée ici
    return _set


# ── le seed lui-même ─────────────────────────────────────────────────────────

def test_seed_v276_identique_octet_pour_octet(card):
    """La Volt garde EXACTEMENT sa forme historique — la référence est le littéral
    de l'ancien code (avant le chantier ④), sérialisé pour comparer l'ordre des clés."""
    card({"V276": (2, 2)})
    attendu = {"card": "hw:V276",
               "inputs": [{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "voice"}],
               "outputs": [{"ch": "1-2", "role": "monitors"}],
               "midi_in": "fcb", "midi_out": "whammy-dt"}
    assert json.dumps(inputmap._seed("hw:V276")) == json.dumps(attendu)


def test_seed_carte_inconnue_2ch_comme_avant(card):
    """Carte inconnue 2 canaux : IN1 guitare, IN2 unassigned — l'existant, préservé."""
    card({"iTwo": (2, 2)})
    attendu = {"card": "hw:iTwo",
               "inputs": [{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "none"}],
               "outputs": [{"ch": "1-2", "role": "monitors"}],
               "midi_in": "fcb", "midi_out": "whammy-dt"}
    assert json.dumps(inputmap._seed("hw:iTwo")) == json.dumps(attendu)


def test_seed_8x8_compte_les_canaux(card):
    """Probe 8 entrées / 8 sorties : 8 entrées semées (rôles none au-delà de IN1),
    4 paires de sorties (la première monitors, les autres other)."""
    card({"Test8": (8, 8)})
    m = inputmap._seed("hw:Test8")
    assert [e["ch"] for e in m["inputs"]] == [str(i) for i in range(1, 9)]
    assert m["inputs"][0]["role"] == "guitar"
    assert all(e["role"] == "none" for e in m["inputs"][1:])
    assert [o["ch"] for o in m["outputs"]] == ["1-2", "3-4", "5-6", "7-8"]
    assert m["outputs"][0]["role"] == "monitors"
    assert all(o["role"] == "other" for o in m["outputs"][1:])


def test_seed_sorties_impaires(card):
    """3 sorties : paire 1-2 monitors + canal 3 mono en queue."""
    card({"T": (4, 3)})
    m = inputmap._seed("hw:T")
    assert [o["ch"] for o in m["outputs"]] == ["1-2", "3"]
    assert [o["role"] for o in m["outputs"]] == ["monitors", "other"]


def test_seed_carte_hors_registre_repli_2ch(card):
    """Rien ne sait compter (ni registre ni probe) : repli sur la supposition
    historique — 2 entrées, une paire de sorties."""
    card({})
    m = inputmap._seed("hw:Mystery")
    assert len(m["inputs"]) == 2 and m["outputs"] == [{"ch": "1-2", "role": "monitors"}]


# ── la persistance : une map existante n'est JAMAIS re-semée ─────────────────

def test_map_existante_intacte(card, monkeypatch, tmp_path):
    """Une inputmap déjà écrite (2 entrées personnalisées) reste intacte même si la
    carte annonce maintenant 8 canaux — le seed ne joue qu'en l'absence de fichier."""
    card({"Test8": (8, 8)})
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    existante = {"card": "hw:Test8",
                 "inputs": [{"ch": "1", "role": "bass", "person": "alex"},
                            {"ch": "2", "role": "voice"}],
                 "outputs": [{"ch": "1-2", "role": "pa"}],
                 "midi_in": "none", "midi_out": "none"}
    (tmp_path / "hw-Test8.json").write_text(json.dumps(existante))
    assert inputmap._load("hw:Test8") == existante


def test_seed_ecrit_au_premier_acces(card, monkeypatch, tmp_path):
    """Pas de fichier -> _load sème (dimensionné par la carte) et persiste."""
    card({"Test8": (8, 8)})
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    m = inputmap._load("hw:Test8")
    assert len(m["inputs"]) == 8
    assert json.loads((tmp_path / "hw-Test8.json").read_text()) == m


# ── replis config.alsa_card : io.json > registre > carte branchée > rien ───────

@pytest.fixture
def sans_io(monkeypatch, tmp_path):
    """alsa_card sans env ni io.json (ROOT redirigé vers un dossier vide)."""
    monkeypatch.delenv("GOLEM_ALSA_CARD", raising=False)
    monkeypatch.setattr(C, "ROOT", str(tmp_path))


def test_alsa_card_registre_carte_branchee(sans_io, monkeypatch):
    monkeypatch.setattr(cards, "registry", lambda: [{"id": "A"}, {"id": "B"}])
    monkeypatch.setattr(cards, "connected", lambda: [{"id": "B"}])
    assert C.alsa_card() == "B"


def test_alsa_card_registre_unique_non_ignoree(sans_io, monkeypatch):
    monkeypatch.setattr(cards, "registry", lambda: [{"id": "A", "ignored": True}, {"id": "B"}])
    monkeypatch.setattr(cards, "connected", lambda: [])
    assert C.alsa_card() == "B"


def test_alsa_card_sans_carte_rien_pas_la_carte_du_rack_de_dev(sans_io, monkeypatch):
    monkeypatch.setattr(cards, "registry", lambda: [])
    monkeypatch.setattr(cards, "connected", lambda: [])
    assert C.alsa_card() == ""                     # plus « V276 » (2026-11-03)
    monkeypatch.setattr(cards, "connected", lambda: [{"id": "iTwo"}])
    assert C.alsa_card() == "iTwo"                 # jamais adoptée, mais branchée


def test_alsa_card_branchee_mais_ignoree(sans_io, monkeypatch):
    monkeypatch.setattr(cards, "registry", lambda: [{"id": "X", "ignored": True}, {"id": "Y", "ignored": True}])
    monkeypatch.setattr(cards, "connected", lambda: [{"id": "X"}, {"id": "iTwo"}])
    assert C.alsa_card() == "iTwo"


@pytest.mark.parametrize("inst, in1, in2", [("bass", "bass", "voice"), ("voice", "voice", "none"), ("keys", "guitar", "voice")])
def test_seed_suit_l_instrument_de_l_installation(card, monkeypatch, inst, in1, in2):
    """Une carte NEUVE prend en IN1 le rôle de l'instrument choisi à l'installation (first_run.input_role) — une
    basse, pas « guitar » (vu sur le Mac du 2026-11-04 : ses cartes dataient d'avant ce choix) ; la Volt garde sa voix
    en IN2, libérée quand la voix est en IN1."""
    monkeypatch.setattr(first_run, "instrument", lambda: inst)
    card({"V276": (2, 2)})
    m = inputmap._seed("hw:V276")
    assert [e["role"] for e in m["inputs"]] == [in1, in2]
