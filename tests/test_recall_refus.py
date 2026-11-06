# SPDX-License-Identifier: GPL-3.0-or-later
"""AUDIT 2026-09-13, B2 : un recall qui ne compile pas ÉCHOUE — et le dit.

Avant : `emit_sandbox` jetait le retour de `emit_sandbox_preset` (le texte du refus de compile),
`.live.json` était écrit AVANT l'émission, `do_recall` rendait True. /live et le pied affichaient un
preset que Reaper n'avait jamais monté, et boot_recall le ré-adoptait au démarrage suivant.
"""
from bridge import recall


def test_emit_sandbox_rend_le_refus_de_compile(monkeypatch):
    monkeypatch.setattr(recall, "load_preset", lambda pid: {"id": pid, "lanes_v": 2, "lanes": [], "scenes": []})
    monkeypatch.setattr(recall, "emit_sandbox_preset", lambda p, s, action="rig_recall": "bloc gx-detune en quarantaine")
    assert recall.emit_sandbox("x", "A") == "bloc gx-detune en quarantaine"


def test_emit_sandbox_rend_none_quand_ca_passe(monkeypatch):
    monkeypatch.setattr(recall, "load_preset", lambda pid: {"id": pid})
    monkeypatch.setattr(recall, "emit_sandbox_preset", lambda p, s, action="rig_recall": None)
    assert recall.emit_sandbox("x", "A") is None
    assert recall.emit_sandbox(None, "A") is None                    # pas de preset -> rien à émettre, pas d'erreur


def test_emit_sandbox_nomme_un_preset_inconnu(monkeypatch):
    monkeypatch.setattr(recall, "load_preset", lambda pid: None)
    assert "unknown preset" in recall.emit_sandbox("fantome", "A")


def test_letat_porte_le_refus():
    from bridge.state import state
    assert "rig_error" in state.snapshot()
