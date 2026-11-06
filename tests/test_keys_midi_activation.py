# SPDX-License-Identifier: GPL-3.0-or-later
"""L'activation MIDI Reaper ne doit plus être en dur sur l'AKAI (audit 2026-08-12 §3, chantier ②).

Le verrou d'origine : `KEYS_NAME_RE = mpk|akai` dans provision/reaper-ini-setup.py — un
contrôleur calibré au wizard (Arturia, Novation…) n'était JAMAIS ouvert par Reaper : silence
total, aucune erreur nulle part, la version MIDI de « la piste qui sort du graphe vivant ».
Ces tests prouvent la résolution PURE (aucun matériel, aucun fichier) :
  (a) un binding/profil déclaré -> son nom devient le motif de résolution ;
  (b) aucune donnée -> repli sur l'ancien motif mpk|akai (rack jamais calibré) ;
  (c) le rack AKAI actuel (soundcard.json + profil 09e8-0045) matche toujours — zéro régression.
"""

from __future__ import annotations

import importlib.util
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Le script porte un tiret dans son nom : chargement par chemin, pas par import.
_spec = importlib.util.spec_from_file_location(
    "reaper_ini_setup", os.path.join(_ROOT, "provision", "reaper-ini-setup.py"))
ris = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ris)

# Nom ENRICHI tel que le construit alsa_card_names() + rich() : « hw:<id> » + les DEUX lignes
# de /proc/asound/cards (la 2e porte le nom constructeur, celui des profils de calibration).
AKAI_RICH = "hw:II USB-Audio - MPK Mini Mk II AKAI MPK Mini Mk II"
VOLT_RICH = "hw:V276 USB-Audio - Volt 276 Universal Audio Volt 276"


def test_binding_declare_donne_le_motif():
    """(a) Un Arturia lié dans soundcard.json est résolu par son nom — plus de verrou AKAI."""
    sc = {"usb1": {"enabled": True, "device": "Arturia KeyLab 49",
                   "kind": "midi", "roles": ["keys"]}}
    pats, src = ris.keys_name_patterns(sc, [])
    assert pats == ["arturia keylab 49"]
    assert "config" in src
    assert ris.keys_match("hw:KeyLab49 USB-Audio - KeyLab 49 Arturia KeyLab 49", pats)
    assert not ris.keys_match(AKAI_RICH, pats)      # l'AKAI débranché du binding ne matche plus
    assert not ris.keys_match(VOLT_RICH, pats)      # la carte son, jamais


def test_profil_calibre_seul_suffit():
    """(a bis) Un profil du wizard (config/controllers/) résout même sans binding actif."""
    pats, src = ris.keys_name_patterns({}, [{"usb": "1c75:0288", "name": "Novation Launchkey 25"}])
    assert pats == ["novation launchkey 25"]
    assert "config" in src
    assert ris.keys_match("hw:Launchkey USB-Audio - Launchkey 25 Novation Launchkey 25", pats)


def test_aucune_donnee_repli_mpk_akai():
    """(b) Rack jamais calibré : le repli reste l'ancien motif mpk|akai — l'AKAI d'origine
    doit être ouvert exactement comme avant le chantier."""
    pats, src = ris.keys_name_patterns(None, None)
    assert pats == ["mpk", "akai"]
    assert "repli" in src
    assert ris.keys_match(AKAI_RICH, pats)
    assert ris.keys_match("hw:II USB-Audio - MPK Mini Mk II", pats)   # même sans la 2e ligne
    assert not ris.keys_match(VOLT_RICH, pats)


def test_cas_akai_actuel_inchange():
    """(c) L'état réel du rack (binding « MPK Mini Mk II » + profil « AKAI MPK Mini Mk II ») :
    la résolution data-driven matche le même device qu'avant. Un binding désactivé est ignoré,
    les doublons sont fusionnés, l'ordre reste stable (binding d'abord)."""
    sc = {"usb1": {"enabled": True, "device": "MPK Mini Mk II",
                   "kind": "midi", "roles": ["keys", "pads"]},
          "usb2": {"enabled": False, "device": "Fantôme Débranché"}}
    profs = [{"usb": "09e8:0045", "name": "AKAI MPK Mini Mk II"},
             {"usb": "09e8:0045", "name": "MPK Mini Mk II"}]      # doublon du binding
    pats, _src = ris.keys_name_patterns(sc, profs)
    assert pats == ["mpk mini mk ii", "akai mpk mini mk ii"]
    assert ris.keys_match(AKAI_RICH, pats)
    assert not ris.keys_match(VOLT_RICH, pats)
    assert not ris.keys_match("hw:Fantome USB-Audio - Fantôme Débranché", pats)


# ── (d) Le contrôleur DÉBRANCHÉ — la panne du 2026-09-11 ────────────────────────────────────
# « À chaque reboot le MIDI est en erreur » : un clavier débranché n'est plus NOMMABLE (Reaper
# l'appelle « hw:II », /proc/asound/cards ne l'enrichit plus), la résolution par nom échouait, et
# le script écrasait midiins/midiouts à 0 — mesuré sur le rack : reaper.ini.bak=4, reaper.ini=0.
# Rebrancher le clavier ne rendait rien : le masque restait à 0. La MÉMOIRE du device résolu
# (son index de cache Reaper est immuable) garde le bit.
ORDER = ["virtual", "hw:V276", "hw:II", "hw:iTwo"]   # [mididevcache] du rack, ordre immuable
PATS = ["mpk mini mk ii", "akai mpk mini mk ii"]


def _rich_branche(name):
    """/proc/asound/cards enrichit les cartes PRÉSENTES — l'AKAI en fait partie."""
    return {"hw:V276": VOLT_RICH, "hw:II": AKAI_RICH}.get(name, name)


def _rich_debranche(name):
    """AKAI débranché : sa carte a disparu de /proc/asound/cards, il ne reste que « hw:II »."""
    return {"hw:V276": VOLT_RICH}.get(name, name)


def test_branche_resolu_par_nom():
    assert ris.resolve_keys_index(ORDER, _rich_branche, PATS, "hw:V276") == (2, "hw:II", "name")


def test_debranche_sans_memoire_reste_introuvable():
    """L'ancien comportement — c'est LUI qui écrasait le masque à 0."""
    assert ris.resolve_keys_index(ORDER, _rich_debranche, PATS, "hw:V276") == (None, None, None)


def test_debranche_mais_memorise_garde_son_index():
    assert ris.resolve_keys_index(ORDER, _rich_debranche, PATS, "hw:V276",
                                  remembered="hw:II") == (2, "hw:II", "memory")


def test_la_memoire_ne_peut_jamais_designer_la_carte_son():
    """Garde-fou de la doctrine : le MIDI de la carte son appartient au bridge (FCB + Whammy).
    Une mémoire corrompue/héritée ne doit pas faire ouvrir hw:V276 par Reaper."""
    assert ris.resolve_keys_index(ORDER, _rich_debranche, PATS, "hw:V276",
                                  remembered="hw:V276") == (None, None, None)


def test_memoire_ignoree_si_le_device_a_quitte_le_cache():
    assert ris.resolve_keys_index(ORDER, _rich_debranche, PATS, "hw:V276",
                                  remembered="hw:Disparu") == (None, None, None)


def test_masque_conserve_quand_le_clavier_est_debranche(monkeypatch):
    """La régression qui compte : index 2 (par mémoire) -> midiins=4, PAS 0."""
    monkeypatch.setattr(ris, "reaper_midi_index",
                        lambda d: (2, "hw:II", "cache · MÉMOIRE (contrôleur débranché)"))
    ov, note = ris.midi_enable_keys()
    assert ov["midiins"] == "4" and ov["midiins_nowarn"] == "4"   # nowarn : aucune modale au boot
    assert ov["midiins_cs"] == "0"                                # un clavier ne pilote pas Reaper
    assert ov["midiins_h"] == "0"
    ov_out, _ = ris.midi_enable_out()
    assert ov_out["midiouts"] == "4" and ov_out["midiouts_nowarn"] == "4"


def test_masque_a_zero_si_le_controleur_na_JAMAIS_ete_vu(monkeypatch):
    """Machine vierge / clavier inconnu : 0 reste le bon défaut (carte son protégée)."""
    monkeypatch.setattr(ris, "reaper_midi_index", lambda d: (None, None, "src"))
    assert ris.midi_enable_keys()[0]["midiins"] == "0"
    assert ris.midi_enable_out()[0]["midiouts"] == "0"


def test_le_sidecar_preserve_la_memoire_quand_on_republie_les_motifs(tmp_path, monkeypatch):
    """start.sh republie les motifs à chaque démarrage : ça ne doit pas effacer la mémoire."""
    monkeypatch.setattr(ris, "KEYS_SIDECAR", str(tmp_path / ".keys-midi.json"))
    ris.write_keys_sidecar(PATS, "config")
    ris.remember_keys_device("in", "hw:II")
    ris.remember_keys_device("out", "hw:II")
    assert ris.keys_memory() == {"in": "hw:II", "out": "hw:II"}
    ris.write_keys_sidecar(PATS, "config")                 # republication : mémoire conservée
    assert ris.keys_memory() == {"in": "hw:II", "out": "hw:II"}
    assert ris.read_keys_sidecar()["patterns"] == PATS     # et les motifs restent lisibles par le Lua
