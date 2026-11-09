# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests à froid du bloc pédale MIDI générique (chantier ① audit 2026-08-12 §3).

La cible est la RÉSOLUTION descripteur -> messages dans bridge/midi_out.py : PC de réglage,
PC de bypass PAR réglage (sémantique Whammy, le cas général quand la table le décrit), canal,
CC de treadle — sur DEUX descripteurs RÉELS du dépôt :

- mappings/whammy-dt.json   : table CALIBRÉE matériel, avec bypass par réglage + treadle ;
- library/pedals/lexicon-mx200.json : import MIDNAM, SANS bypass ni treadle ni default_mode
  (le cas des 7 descripteurs importés — exactement ce que la glue Whammy-only ne savait pas jouer).

Le chemin d'émission est testé avec `_send`/`_send_named` espionnés (aucun MIDI réel) et
`pedal_cfg`/`_din_out_off` monkeypatchés : rien du matériel, rien de l'input map du dépôt.

Non testé à froid (matériel requis, assumé) : le son qui sort de la pédale — c'est le rôle de
`verify.checks` du registre (docs/pedal-registry.md §2), au pied, sur le rack.
"""
import json
import os

import pytest

from bridge import midi_out

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(*parts):
    """⚠ CES DEUX DESCRIPTEURS SONT DU CONTENU LOCAL, PAS DU DÉPÔT (gitignorés : `mappings/*.json`
    et `library/pedals/`). Un clone frais — ou un rack qu'on vient de remettre à zéro — n'en a
    aucun, et ces tests tombaient alors en ERREUR : 16 faux négatifs qui masquent les vraies
    régressions. On SAUTE explicitement, ce qui est la vérité : « rien à tester ici, ce rack
    n'a pas encore de descripteur » (constaté au reset du 2026-09-07)."""
    path = os.path.join(ROOT, *parts)
    if not os.path.isfile(path):
        pytest.skip(f"descripteur local absent ({os.path.join(*parts)}) — un rack neuf n'en a pas")
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def whammy():
    # le descripteur VERSIONNÉ (library/pedals) : mappings/ est l'état local d'un rack (ignoré par git) — le test était
    # sauté en CI, donc nulle part ailleurs que sur un rack déjà installé (audit 2026-11-09)
    return _load("library", "pedals", "whammy-dt.json")


@pytest.fixture(scope="module")
def mx200():
    return _load("library", "pedals", "lexicon-mx200.json")


# ── résolution pure (aucun I/O) ──────────────────────────────────────────────────────────────
def test_whammy_active_pc(whammy):
    r = midi_out.resolve_setting(whammy, "↑1 Oct", active=True)
    assert r == {"pc": 1, "channel": 1, "name": "↑1 Oct"}


def test_whammy_bypass_pc_par_reglage(whammy):
    # chaque réglage a SON PC de bypass (actif+21 pour la famille whammy) — le cas général
    r = midi_out.resolve_setting(whammy, "↑1 Oct", active=False)
    assert r["pc"] == 22
    # famille drop : décalage +18, et l'ordre du fil est inversé (calibré matériel)
    assert midi_out.resolve_setting(whammy, "Drop −3 semitones", active=True)["pc"] == 57
    assert midi_out.resolve_setting(whammy, "Drop −3 semitones", active=False)["pc"] == 75


def test_whammy_default_mode(whammy):
    # sans nom -> default_mode du descripteur (↑1 Oct)
    r = midi_out.resolve_setting(whammy, None, active=True)
    assert (r["name"], r["pc"]) == ("↑1 Oct", 1)


def test_reglage_inconnu(whammy):
    assert midi_out.resolve_setting(whammy, "n'existe pas", active=True) is None


def test_whammy_treadle_cc(whammy):
    assert midi_out.pedal_treadle_cc(whammy) == 11


def test_mx200_active_pc(mx200):
    r = midi_out.resolve_setting(mx200, "3 RetroVerb", active=True)
    assert r == {"pc": 2, "channel": 1, "name": "3 RetroVerb"}


def test_mx200_sans_default_mode(mx200):
    # import MIDNAM sans default_mode -> le PREMIER réglage de la table
    r = midi_out.resolve_setting(mx200, None, active=True)
    assert (r["name"], r["pc"]) == ("1 Big Pop Vocal", 0)


def test_mx200_sans_bypass_ni_treadle(mx200):
    # table MIDNAM : pas de PC de bypass -> None (rien d'honnête à envoyer), pas de treadle
    assert midi_out.resolve_setting(mx200, "3 RetroVerb", active=False) is None
    assert midi_out.pedal_treadle_cc(mx200) is None


# ── chemin d'émission (espionné) ─────────────────────────────────────────────────────────────
@pytest.fixture
def wire(monkeypatch, whammy, mx200):
    """_send espionné + descripteurs servis depuis les fixtures (pas de mappings/ réels),
    kill-switch input map neutralisé (le test ne lit pas la config du dépôt)."""
    sent = []
    monkeypatch.setattr(midi_out, "_send", lambda msg: (sent.append(list(msg)), True)[1])
    monkeypatch.setattr(midi_out, "_din_out_off", lambda: False)
    table = {"whammy-dt": whammy, "lexicon-mx200": mx200}
    monkeypatch.setattr(midi_out, "pedal_cfg", lambda pid: table.get(pid, {}))
    return sent


def test_pedal_mode_actif(wire):
    name = midi_out.pedal_mode("whammy-dt", "↑1 Oct", active=True)
    assert name == "↑1 Oct"
    assert wire == [[0xC0, 1]]          # PC 1, canal 1 -> statut 0xC0


def test_pedal_mode_bypass(wire):
    midi_out.pedal_mode("whammy-dt", "↑1 Oct", active=False)
    assert wire == [[0xC0, 22]]


def test_pedal_treadle(wire):
    assert midi_out.pedal_treadle("whammy-dt", 100) is True
    assert wire == [[0xB0, 11, 100]]    # CC 11, canal 1


def test_pedal_mode_midnam(wire):
    assert midi_out.pedal_mode("lexicon-mx200", "3 RetroVerb", active=True) == "3 RetroVerb"
    assert wire == [[0xC0, 2]]


def test_pedal_bypass_midnam_silencieux(wire):
    # pas de PC de bypass dans la table -> rien sur le fil, None (l'appelant garde l'état)
    assert midi_out.pedal_mode("lexicon-mx200", "3 RetroVerb", active=False) is None
    assert wire == []


def test_treadle_midnam_silencieux(wire):
    assert midi_out.pedal_treadle("lexicon-mx200", 64) is False
    assert wire == []


def test_canal_du_descripteur(wire, monkeypatch, whammy):
    # le canal vient du DESCRIPTEUR : canal 3 -> statut 0xC2
    w3 = dict(whammy, channel=3)
    monkeypatch.setattr(midi_out, "pedal_cfg", lambda pid: w3)
    midi_out.pedal_mode("whammy-dt", "↑1 Oct", active=True)
    assert wire == [[0xC2, 1]]


def test_port_dedie_du_descripteur(wire, monkeypatch, whammy):
    # champ midi_port -> l'envoi passe par le port DÉDIÉ, jamais par la ligne par défaut
    named = []
    monkeypatch.setattr(midi_out, "_send_named",
                        lambda port, msg: (named.append((port, list(msg))), True)[1])
    wp = dict(whammy, midi_port="hw:2,0,0")
    monkeypatch.setattr(midi_out, "pedal_cfg", lambda pid: wp)
    midi_out.pedal_mode("whammy-dt", "↑1 Oct", active=True)
    assert wire == [] and named == [("hw:2,0,0", [0xC0, 1])]
