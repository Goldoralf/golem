# SPDX-License-Identifier: GPL-3.0-or-later
"""Un appui de SCÈNE au pied ne rappelle pas le PRESET (panne du 2026-09-20, répète du mainteneur).

La puce envoie, à CHAQUE appui de scène, un PC (« je suis sur la bank n ») puis le CC de scène.
Deux défauts se combinaient :
  1. `_on_foot_scene` appelait `schedule(state.preset_id, sc)` : un rappel de PRESET sans ligne,
     qui posait `state.song = None` ;
  2. au PC suivant, `do_recall_slot` ne reconnaissait donc plus « déjà chargé, même ligne » et
     rappelait le preset avec `scene=None` -> `scenes[0]` : la scène A.
Tracé sur le canal de commandes : chaque appui écrivait `scene_apply A` PUIS la scène demandée.
Aller de C à B traversait A — l'autre branche d'ampli, donc un blanc — et selon l'ordre des deux
fils, la scène demandée pouvait perdre. ⚠ « À l'écran, rien : lui passait déjà par do_recall(None, sc) » — c'était
FAUX (trouvé le 2026-10-09) : les tuiles de scène de /live envoyaient {preset, scene}, et chaque tap effaçait la
chanson (« no song · sounds only — load it »). Corrigé à l'écran, et le moteur garde désormais le morceau sur un
rappel du MÊME preset sans ligne.
"""
import re
from pathlib import Path

from bridge import recall
from bridge.state import state

ROOT = Path(__file__).resolve().parents[1]


def test_le_pied_demande_une_scene_pas_un_preset():
    """Lu dans la source : app.py importe Reaper, OSC et MIDI, on ne le monte pas pour ça."""
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    body = src[src.index("def _on_foot_scene"):src.index("# types SERVICE")]
    assert "recall_mod.schedule(None, sc)" in body
    assert not re.search(r"recall_mod\.schedule\(state\.preset_id", body)


def test_un_PC_du_preset_courant_garde_la_scene(monkeypatch):
    calls = []
    monkeypatch.setattr(recall, "do_recall", lambda pid, scene, line=None: calls.append((pid, scene)) or True)
    monkeypatch.setattr(recall, "_fcb_slot_pid", lambda slot: "paper-kite")
    monkeypatch.setattr(recall, "_fcb_slot_line", lambda slot: {"id": "r:covers:1", "preset": "paper-kite"})
    monkeypatch.setattr(state, "preset_id", "paper-kite", raising=False)
    monkeypatch.setattr(state, "scene_id", "C", raising=False)
    monkeypatch.setattr(state, "song", None, raising=False)      # rappel précédent venu de l'écran
    recall.do_recall_slot(0, "pc")
    assert calls == [("paper-kite", "C")], "scene=None retombait sur scenes[0] : la scène A"


def test_un_AUTRE_preset_demarre_sur_sa_premiere_scene(monkeypatch):
    calls = []
    monkeypatch.setattr(recall, "do_recall", lambda pid, scene, line=None: calls.append((pid, scene)) or True)
    monkeypatch.setattr(recall, "_fcb_slot_pid", lambda slot: "autre")
    monkeypatch.setattr(recall, "_fcb_slot_line", lambda slot: {"id": "r:covers:2", "preset": "autre"})
    monkeypatch.setattr(state, "preset_id", "paper-kite", raising=False)
    monkeypatch.setattr(state, "scene_id", "C", raising=False)
    recall.do_recall_slot(1, "pc")
    assert calls == [("autre", None)]


def test_meme_preset_meme_ligne_reste_un_no_op(monkeypatch):
    calls = []
    monkeypatch.setattr(recall, "do_recall", lambda *a, **k: calls.append(a) or True)
    monkeypatch.setattr(recall, "_fcb_slot_pid", lambda slot: "paper-kite")
    monkeypatch.setattr(recall, "_fcb_slot_line", lambda slot: {"id": "r:covers:1", "preset": "paper-kite"})
    monkeypatch.setattr(state, "preset_id", "paper-kite", raising=False)
    monkeypatch.setattr(state, "song", {"line": "r:covers:1"}, raising=False)
    recall.do_recall_slot(0, "pc")
    assert calls == []


# ── UN ESSAI TIENT TANT QUE LE PIED NE CHANGE PAS DE BANK (patches.md §19, 2026-09-30) ─────────
def _trial(monkeypatch, believed):
    from bridge import pedalboard
    calls = []
    monkeypatch.setattr(recall, "do_recall", lambda pid, scene, line=None: calls.append((pid, scene)) or True)
    monkeypatch.setattr(recall, "_fcb_slot_pid", lambda slot: "paper-kite" if slot == 2 else "autre")
    monkeypatch.setattr(recall, "_fcb_slot_line", lambda slot: {"id": f"r:covers:{slot}"})
    monkeypatch.setattr(state, "preset_id", "patch:the-wall", raising=False)
    monkeypatch.setattr(state, "scene_id", "B", raising=False)
    monkeypatch.setitem(pedalboard._BELIEVED, "slot", believed)
    return calls, pedalboard


def test_le_PC_de_la_bank_du_pied_garde_le_patch_ouvert(monkeypatch):
    calls, pb = _trial(monkeypatch, 2)
    assert recall.do_recall_slot(2, "pc") is True
    assert calls == [] and state.preset_id == "patch:the-wall"          # seule la scène (le CC) suivra


def test_bank_inconnue_au_demarrage_le_patch_ouvert_garde_la_main(monkeypatch):
    calls, pb = _trial(monkeypatch, None)
    recall.do_recall_slot(2, "pc")
    assert calls == [] and pb.believed_slot() == 2                    # et la bank est apprise


def test_changer_de_bank_au_pied_quitte_lessai(monkeypatch):
    calls, pb = _trial(monkeypatch, 2)
    recall.do_recall_slot(3, "pc")
    assert calls == [("autre", None)]                                  # UP/DOWN puis un switch = un vrai choix


# ── L'ÉCRAN, LUI AUSSI (2026-10-09) ────────────────────────────────────────────────────────────

def test_une_tuile_de_scene_de_live_demande_une_scene_pas_un_preset():
    src = (ROOT / "app/page-live.js").read_text(encoding="utf8")
    assert "recall(current.id, s.id)" not in src, "un tap de scène envoyait le preset : la chanson était effacée"
    assert src.count("recall(null, s.id)") >= 2
    assert "preset ? { preset, scene } : { scene }" in src


def test_le_moteur_garde_le_morceau_sur_un_rappel_du_meme_preset_sans_ligne():
    """Lu dans la source : do_recall pilote Reaper. La règle : seul un AUTRE preset ou une vraie ligne change le morceau."""
    src = (ROOT / "bridge/recall.py").read_text(encoding="utf8")
    body = src[src.index("def do_recall(pid, scene, line=None)"):src.index("def do_recall_slot")]
    assert "if line is not None or _preset_changed or not state.song:" in body


# ── UN REDÉMARRAGE DU BRIDGE GARDE LE MORCEAU (2026-10-09) ──────────────────────────────────────

def _setlist(monkeypatch, lines, sid="covers"):
    monkeypatch.setattr(recall, "fcb_setlist", lambda: {"id": sid, "lines": lines})
    monkeypatch.setattr("bridge.songs.line_title", lambda ln: ln.get("title"))
    monkeypatch.setattr("bridge.songs.line_sheet", lambda ln: {})


def test_la_ligne_notee_revient_au_demarrage(monkeypatch):
    _setlist(monkeypatch, [{"id": "r:covers:1", "preset": "paper-kite", "title": "Paper Kite"}])
    s = recall._song_from_live({"preset": "paper-kite", "line": "r:covers:1", "setlist": "covers"}, "paper-kite")
    assert s and s["line"] == "r:covers:1" and s["title"] == "Paper Kite"


def test_une_ligne_partie_ou_une_autre_setlist_ne_revient_pas(monkeypatch):
    _setlist(monkeypatch, [{"id": "r:covers:1", "preset": "autre"}])
    assert recall._song_from_live({"line": "r:covers:1", "setlist": "covers"}, "paper-kite") is None   # autre preset
    assert recall._song_from_live({"line": "r:covers:9", "setlist": "covers"}, "paper-kite") is None   # ligne partie
    _setlist(monkeypatch, [{"id": "r:covers:1", "preset": "paper-kite"}], sid="originals")
    assert recall._song_from_live({"line": "r:covers:1", "setlist": "covers"}, "paper-kite") is None   # autre setlist active
    assert recall._song_from_live({}, "paper-kite") is None                                             # ancien .live.json
