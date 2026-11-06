# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests à froid du contrôleur looper (bridge/looper.py) : normalize_loops + machine de gestes.

Aucun Reaper : le dispatch OSC est un FAUX (set_fx_param enregistre la valeur normalisée du
slider « GoleM Cmd », qu'on décode en seq/note) et le fallback fichier est détourné vers
tmp_path — presets/.looper-cmd.json du dépôt n'est jamais touché. L'état des slots vient soit
de l'override optimiste (posé par le dispatch), soit d'un set_feedback synthétique.

Les gestes à DURÉE (hold=clear, stop différé, kill all) passent par threading.Timer : on
raccourcit les seuils (monkeypatch LONG_S/CONFIRM_S/DOUBLE_S, relus à chaque appel) pour que
les tests attendent ~0,2 s au lieu de secondes — le timing RÉEL (0,4/0,6/1,2 s) reste une
affaire de pied, validée sur rack.

Contrat testé (docs/looper.md) : table {sw, src, label} max 4 lignes, 2 boucles peuvent
partager une source ; SW5 = play/stop all, SW10 hold = clear all ; tap = rec/close,
double-tap = overdub, hold = wipe du slot.
"""
import json
import time

import pytest

from bridge import looper
from bridge import config as C


class _FakeOSC:
    """Enregistre les écritures FX_PARAM du chemin primaire (jamais de vrai OSC)."""
    def __init__(self):
        self.sent = []

    def set_fx_param(self, track, fx, param, v):
        if param == 5:                  # le slider « GoleM Cmd » de _lp() ; le reste (calage, volumes) n'est pas une commande
            self.sent.append(v)
        return True


def _notes(osc):
    """Décode les notes de commande depuis les valeurs normalisées (v = (seq*128+note)/16383)."""
    return [round(v * 16383) % 128 for v in osc.sent]


def _seqs(osc):
    return [round(v * 16383) // 128 for v in osc.sent]


def _lp():
    osc = _FakeOSC()
    lp = looper.LooperControl(osc)
    lp.set_addr({"track": 1, "fx": 0, "cmd_param": 5})
    return lp, osc


# ── normalize_loops (docs/looper.md §1-2) ────────────────────────────────────────────────────
def test_table_absente_rend_le_defaut():
    """Table vide/absente -> le défaut 1/2/3 -> lanes 1/2/k (la rangée PROCHE, amendement du 2026-10-14),
    jamais écrit au preset."""
    assert looper.normalize_loops(None) == [{"sw": 1, "src": "1"}, {"sw": 2, "src": "2"},
                                            {"sw": 3, "src": "k"}]
    assert looper.normalize_loops([]) == looper.normalize_loops(None)


def test_normalize_rejette_les_lignes_invalides():
    """Switch hors LOOP_SWITCHES (5 et 10 = gestes globaux), doublon de switch (premier arrivé
    gagne), src vide, ligne non-dict : tout est jeté sans casser le reste."""
    rows = looper.normalize_loops([
        {"sw": 5, "src": "1"},          # SW5 = play all, jamais une boucle
        {"sw": 6, "src": "1", "label": "GTR"},
        {"sw": 6, "src": "2"},          # doublon de switch -> premier gagne
        {"sw": 10, "src": "2"},         # SW10 = kill all
        {"sw": "x", "src": "2"},        # sw non entier
        {"sw": 7, "src": ""},           # source vide
        "n'importe quoi",               # ligne non-dict
        {"sw": 9, "src": "k"},
    ])
    # une table d'AVANT l'amendement (6-9) se lit sur la rangée proche (1-4), dans le même ordre
    assert rows == [{"sw": 1, "src": "1", "label": "GTR"}, {"sw": 4, "src": "k"}]
    assert looper.normalize_loops([{"sw": 1, "src": "1"}, {"sw": 6, "src": "2"}]) == [{"sw": 1, "src": "1"}]   # 6 -> 1 : doublon


def test_normalize_max_4_et_source_partagee():
    """Au plus MAX_LOOPS (4) lignes ; deux boucles PEUVENT partager une source (docs/looper.md)."""
    rows = looper.normalize_loops([{"sw": 6, "src": "1"}, {"sw": 7, "src": "1"},
                                   {"sw": 8, "src": "k"}, {"sw": 9, "src": "k"}])
    assert [r["src"] for r in rows] == ["1", "1", "k", "k"]
    assert len(looper.normalize_loops([{"sw": sw, "src": "1"} for sw in (6, 7, 8, 9, 6)])) == 4


def test_set_loops_lordre_fait_le_slot_et_les_stomps_restent_libres():
    """La ligne n de la table = slot n (paire stéréo n du JSFX). Une 4e boucle prend SW4 ; SW 6-9 ne sont JAMAIS
    au looper (amendement du 2026-10-14) : switches() est LA source, pas la constante SWITCHES."""
    lp, _ = _lp()
    assert 4 not in lp.switches() and not ({6, 7, 8, 9} & lp.switches())
    lp.set_loops([{"sw": 4, "src": "k"}, {"sw": 1, "src": "1"}])
    assert lp._slot(4) == 0 and lp._slot(1) == 1        # l'ordre fait le slot
    assert lp.switches() == frozenset({1, 4, 5, 10})    # + les deux gestes globaux


# ── retour d'état gmem (set_feedback) ────────────────────────────────────────────────────────
def test_feedback_rec_vs_dub_et_etats():
    """st=2 = enregistre : REC si c'est la paire maîtresse (firstrec), DUB sinon ;
    st=1 = play ; st=0 = stop si la loop existe, empty sinon."""
    lp, _ = _lp()
    lp.set_feedback([{"st": 2, "has": 1}, {"st": 2, "has": 1},
                     {"st": 1, "has": 1}, {"st": 0, "has": 1}], firstrec=1)
    assert [lp.slot_state(i) for i in range(4)] == ["rec", "dub", "play", "stop"]
    lp.set_feedback([{"st": 0, "has": 0}], firstrec=0)
    assert lp.slot_state(0) == "empty"


# ── machine de gestes : tap = rec / close, double-tap = overdub ──────────────────────────────
def test_tap_rec_puis_close_puis_double_tap_overdub():
    """Slot vide : le press EST la loop (REC immédiat, note rec). Press suivant ferme la loop
    (PLAY, définit la longueur maîtresse). Puis deux releases dans la fenêtre = OVERDUB."""
    lp, osc = _lp()
    lp.on_edge(1, True)                                 # vide -> REC au press
    lp.on_edge(1, False)                                # press consommé : release muet
    assert lp.slot_state(0) == "rec"
    lp.on_edge(1, True)                                 # rec -> close = PLAY au press
    lp.on_edge(1, False)
    assert lp.slot_state(0) == "play"
    lp.on_edge(1, True)                                 # play : l'action attend le release
    lp.on_edge(1, False)                                # 1er release (arme le stop différé)
    lp.on_edge(1, True)                                 # 2e press annule le stop différé
    lp.on_edge(1, False)                                # 2e release < DOUBLE_S -> overdub
    rec, play, _clear = looper.NOTES[0]
    assert _notes(osc) == [rec, play, rec]
    assert lp.slot_state(0) == "dub"


def test_release_sur_stop_resume():
    """Slot arrêté : le release rejoue (Super8 ré-entre à la position globale) — pas le press,
    qui arme l'appui long (clear)."""
    lp, osc = _lp()
    lp.set_feedback([{"st": 0, "has": 1}], firstrec=0)  # slot 0 : loop existante, stoppée
    lp.on_edge(1, True)
    assert osc.sent == []                               # le press seul ne fait rien
    lp.on_edge(1, False)
    assert _notes(osc) == [looper.NOTES[0][1]]          # note play
    assert lp.slot_state(0) == "play"


def test_tap_simple_sur_play_stoppe_apres_la_fenetre(monkeypatch):
    """Tap simple sur une loop qui joue : STOP, mais DIFFÉRÉ de la fenêtre du double-tap
    (sinon le 1er tap d'un double-tap arrêterait la loop)."""
    monkeypatch.setattr(looper, "DOUBLE_S", 0.05)
    lp, osc = _lp()
    lp.set_feedback([{"st": 1, "has": 1}], firstrec=0)
    lp.on_edge(1, True)
    lp.on_edge(1, False)
    assert osc.sent == []                               # rien dans la fenêtre…
    time.sleep(0.2)
    assert _notes(osc) == [looper.NOTES[0][1]]          # …puis le stop part
    assert lp.slot_state(0) == "stop"


def test_hold_efface_le_slot(monkeypatch):
    """Appui long sur une loop posée = CLEAR du slot ; le release qui suit ne fait rien
    (press consommé par le seuil)."""
    monkeypatch.setattr(looper, "LONG_S", 0.05)
    lp, osc = _lp()
    lp.set_feedback([{"st": 1, "has": 1}], firstrec=0)
    lp.on_edge(1, True)
    time.sleep(0.2)                                     # le seuil d'appui long tombe
    assert _notes(osc) == [looper.NOTES[0][2]]          # note clear
    assert lp.slot_state(0) == "empty"
    lp.on_edge(1, False)
    assert len(osc.sent) == 1                           # release muet


def test_sw5_play_stop_all_et_sw10_kill_all(monkeypatch):
    """SW5 press = play/stop all (note 21). SW10 : le tap court ne fait RIEN (sécurité), seul
    le hold >= CONFIRM_S envoie le kill all (note 20) et vide tous les slots."""
    monkeypatch.setattr(looper, "CONFIRM_S", 0.05)
    lp, osc = _lp()
    lp.on_edge(5, True)
    assert _notes(osc) == [looper.PLAYALL_NOTE]
    lp.on_edge(10, True)
    lp.on_edge(10, False)                               # tap court : timer annulé
    assert _notes(osc) == [looper.PLAYALL_NOTE]
    lp.on_edge(10, True)
    time.sleep(0.2)
    assert _notes(osc) == [looper.PLAYALL_NOTE, looper.KILL_NOTE]
    assert all(lp.slot_state(s) == "empty" for s in looper.NOTES)


# ── dispatch : chemin primaire OSC + fallback fichier ────────────────────────────────────────
def test_dispatch_seq_cycle_1_a_127_jamais_0():
    """La seq encode le retrigger : 1..127 puis re-1 — jamais 0 (le fork ignore v < 128)."""
    lp, osc = _lp()
    for _ in range(128):
        lp.dispatch(36)
    seqs = _seqs(osc)
    assert seqs[0] == 1 and seqs[126] == 127 and seqs[127] == 1
    assert 0 not in seqs
    assert set(_notes(osc)) == {36}


def test_dispatch_fallback_fichier_sans_adresse(tmp_path, monkeypatch):
    """Tant que l'adresse OSC du slider est inconnue (.looper.json pas encore publié), le
    dispatch retombe sur le fichier de commande — détourné ici vers tmp_path."""
    cmd = tmp_path / ".looper-cmd.json"
    monkeypatch.setattr(C, "LOOPER_CMD_FILE", str(cmd))
    lp = looper.LooperControl(None)                     # ni OSC ni adresse
    assert lp.dispatch(36) is True
    assert json.load(open(cmd)) == {"seq": 1, "notes": [36]}


def test_rec_dub_enchaine_une_couche_a_la_fermeture_d_une_1re_prise():
    """Amendement 2026-10-14 (soir), façon Boss RC « REC → DUB » : la fermeture d'une 1re prise enchaîne aussitôt
    une couche (note play PUIS note rec) ; une fermeture d'overdub non. Sur la 1re boucle CALÉE, c'est le JSFX qui
    enchaîne à la barre (drapeau 4) : le bridge n'envoie que la note play."""
    lp, osc = _lp()
    lp.timing = lambda: {"bpm": 0, "beats": 4, "snap": False, "count_in": False, "rec_dub": True}
    rec, play, _ = looper.NOTES[0]
    lp.slot_tap(0)                                       # vide -> rec (1re boucle, libre)
    lp.set_feedback([{"st": 2, "has": 1}], firstrec=1); lp._opt.clear()
    lp.slot_tap(0)                                       # ferme -> play + rec (une couche)
    assert _notes(osc)[-2:] == [play, rec] and lp.slot_state(0) == "dub"
    lp.set_feedback([{"st": 2, "has": 1}], firstrec=0); lp._opt.clear()
    lp.slot_tap(0)                                       # ferme la couche -> play seul
    assert _notes(osc)[-1] == play and lp.slot_state(0) == "play"
    # la 1re boucle calée : le JSFX enchaîne
    lp2, osc2 = _lp()
    lp2.timing = lambda: {"bpm": 100, "beats": 4, "snap": False, "count_in": True, "rec_dub": True}
    lp2.slot_tap(0)
    lp2.set_feedback([{"st": 2, "has": 1}], firstrec=1); lp2._opt.clear()
    lp2.slot_tap(0)
    cmds = [n for n in _notes(osc2)]
    assert cmds[-1] == play and rec not in cmds[cmds.index(rec) + 1:]   # pas de note rec après la fermeture


def test_le_volume_de_chaque_boucle_vit_dans_la_table_et_part_au_jsfx():
    """Mixer des boucles (2026-10-14) : `level` (dB −60..0) et `mute` survivent à normalize_loops ; la table posée
    au rappel part sur les sliders « GoleM Loop N dB » (cmd+3..+6) et « GoleM Loops level » (cmd+7)."""
    rows = looper.normalize_loops([{"sw": 1, "src": "1", "level": -12.04}, {"sw": 2, "src": "2", "level": 9, "mute": 1}])
    assert rows == [{"sw": 1, "src": "1", "level": -12.0}, {"sw": 2, "src": "2", "level": 0.0, "mute": True}]
    sent = []

    class Osc:
        def set_fx_param(self, track, fx, param, v):
            sent.append((param, round(v, 4)))
            return True
    lp = looper.LooperControl(Osc())
    lp.set_addr({"track": 1, "fx": 0, "cmd_param": 2})
    sent.clear()
    lp.set_loops(rows)
    assert sent == [(5, round(48 / 60, 4)), (6, 0.0), (7, 1.0), (8, 1.0), (9, 1.0)]   # −12 dB, muette, 0, 0, tout = 1
    sent.clear()
    assert lp.set_slot_level(1, mute=False)["level"] == 0.0
    assert (6, 1.0) in sent
    sent.clear()
    lp.set_all_level(0.5)
    assert sent == [(9, 0.5)]
