# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests à froid du lecteur pédalier (bridge/foot.py) : parsing aseqdump + dispatch.

Aucun MIDI réel : on rejoue des lignes aseqdump SYNTHÉTIQUES via `feed()` — exactement le
chemin de /api/foot/inject — et on capture les handlers. L'état module (_DEVICE, _BOUND,
_HEARD) est remplacé par monkeypatch et restauré ; `inputmap.din_role` est neutralisé pour
ne pas lire la vraie input map du dépôt.

Régressions visées : le filtre de canal qui rend SOURD (UnO2 canal 2 vs 1.0.4 canal 1), le
quirk note_edges=paired de la 1.0.4 (press ET release affichés « Note off »), la synthèse de
release des switches qui ne relâchent jamais (le hold-clear fantôme du 2026-08-07), la table
de bindings apprise (ENGL Z9 & co), et le témoin foot_heard qu'une injection ne doit PAS armer.

Non testé à froid (dépendances dures, assumé) : la boucle _supervise (subprocess aseqdump),
_find_port (énumération ALSA) et la machine appui-long/saisie 2 chiffres (threading.Timer à
1,5 s / 8 s — du temps réel, couvert sur rack par tools/check-foot.py).
"""
import pytest

from bridge import foot
from bridge import inputmap


WIRE_CH = 1        # canal SUR LE FIL (0-15) = canal 2 du contrat (UnO2)


# ── fabriques de lignes aseqdump ─────────────────────────────────────────────────────────────
def _cc(ch, cc, val):
    return f" 20:0   Control change          {ch}, controller {cc}, value {val}"


def _pc(ch, prog):
    return f" 20:0   Program change          {ch}, program {prog}"


def _non(ch, note, vel=127):
    return f" 20:0   Note on                 {ch}, note {note}, velocity {vel}"


def _noff(ch, note, vel=None):
    s = f" 20:0   Note off                {ch}, note {note}"
    return s + (f", velocity {vel}" if vel is not None else "")


@pytest.fixture
def rig(monkeypatch):
    """Lecteur avec handlers espions + état module hermétique (rien du dépôt n'est lu)."""
    calls = {"scene": [], "stomp": [], "recall": [], "treadle": [], "volume": [], "edge": []}
    r = foot.FootReader(
        on_scene=lambda s: calls["scene"].append(s),
        on_stomp=lambda sw, want=None: calls["stomp"].append((sw, want)),
        on_recall=lambda slot, source=None: calls["recall"].append((slot, source)),
        on_treadle=lambda v: calls["treadle"].append(v),
        on_volume=lambda v: calls["volume"].append(v),
        on_stomp_edge=lambda sw, on: calls["edge"].append((sw, on)),
    )
    monkeypatch.setattr(foot, "_DEVICE",
                        {"device_id": "test", "wire_channel": WIRE_CH, "note_edges": "clean",
                         "note_base": 0, "edge_switches": None})
    monkeypatch.setattr(foot, "_BOUND", {})
    monkeypatch.setattr(foot, "_HEARD", {"t": None})
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "fcb")   # kill-switch OFF par défaut
    return r, calls


# ── parsing + dispatch de base (contrat v2, chemin codé) ─────────────────────────────────────
def test_pc_declenche_recall_source_pc(rig):
    """PC n -> recall slot n, source « pc » (le pédalier ANNONCE sa bank : pas de réalignement)."""
    r, calls = rig
    r.feed(_pc(WIRE_CH, 7))
    assert calls["recall"] == [(7, "pc")]


def test_cc_scenes_20_a_24(rig):
    r, calls = rig
    for cc, scene in sorted(foot.SCENE_CC.items()):
        r.feed(_cc(WIRE_CH, cc, 127))
    assert calls["scene"] == ["A", "B", "C", "D", "E"]


def test_cc_scene_rejouee_au_front_0(rig):
    """Caractérisation : le chemin codé ne filtre PAS la valeur des CC scènes — la puce UnO en
    toggling alterne 127/0, et les DEUX fronts reposent la scène (idempotent côté rack)."""
    r, calls = rig
    r.feed(_cc(WIRE_CH, 20, 127))
    r.feed(_cc(WIRE_CH, 20, 0))
    assert calls["scene"] == ["A", "A"]


def test_cc_stomps_fronts_absolus(rig):
    """CC30-34 alternés 127/0 (état de la LED) -> ordre ABSOLU (sw, True/False), jamais un
    toggle relatif : LED et son ne peuvent plus s'inverser."""
    r, calls = rig
    r.feed(_cc(WIRE_CH, 30, 127))
    r.feed(_cc(WIRE_CH, 30, 0))
    assert calls["stomp"] == [(6, True), (6, False)]
    calls["stomp"].clear()
    for cc, sw in sorted(foot.STOMP_CC.items()):
        r.feed(_cc(WIRE_CH, cc, 127))
    assert calls["stomp"] == [(6, True), (7, True), (8, True), (9, True), (10, True)]


def test_expression_treadle_dedupliquee_volume_toujours_transmis(rig):
    """EXP2 (CC11) est dédupliquée (anti-flood) : deux valeurs identiques -> UN callback.
    Caractérisation EXP1 (CC7) : seule la TRACE est dédupliquée, on_volume part à chaque CC
    (symétrie de trace 2026-08-04 — les deux pédales se logent, mais le volume suit toujours)."""
    r, calls = rig
    r.feed(_cc(WIRE_CH, 11, 64))
    r.feed(_cc(WIRE_CH, 11, 64))
    r.feed(_cc(WIRE_CH, 11, 65))
    assert calls["treadle"] == [64, 65]
    r.feed(_cc(WIRE_CH, 7, 100))
    r.feed(_cc(WIRE_CH, 7, 100))
    assert calls["volume"] == [100, 100]


# ── filtre de canal (l'écho THRU de la UnO2) ─────────────────────────────────────────────────
def test_autre_canal_ignore_en_silence(rig):
    """Un message sur un AUTRE canal est un écho THRU (Whammy, remote…), pas le pied : PC, CC
    et Note doivent être jetés SANS effet — et sans armer le témoin foot_heard."""
    r, calls = rig
    other = WIRE_CH + 4
    r.feed(_pc(other, 3))
    r.feed(_cc(other, 20, 127))
    r.feed(_non(other, 5))
    assert all(v == [] for v in calls.values())
    assert foot.last_heard() is None


# ── fronts des Notes (identité/durée des switches) ───────────────────────────────────────────
def test_note_fronts_francs_uno2(rig):
    """UnO2 (note_edges=clean) : NoteOn vel>0 = press, tout le reste = release. La puce envoie
    note 0-9 pour SW1-10 -> note 5 = switch 6, et les fronts partent vers on_stomp_edge."""
    r, calls = rig
    r.feed(_non(WIRE_CH, 5, 127))       # SW6 press
    r.feed(_noff(WIRE_CH, 5, 0))        # SW6 release
    assert calls["edge"] == [(6, True), (6, False)]


def test_note_rangee_des_scenes_passe_aussi(rig):
    """Corrigé 2026-08-07 : les fronts des switches 1-5 doivent passer AUSSI (un bloc Standard
    en switch 5 n'était déclenché par personne). app.py tranche, le lecteur transmet."""
    r, calls = rig
    r.feed(_non(WIRE_CH, 2, 127))       # SW3 press (pas SW1 : on n'arme pas l'appui long)
    r.feed(_noff(WIRE_CH, 2, 0))
    assert calls["edge"] == [(3, True), (3, False)]


def test_note_edges_paired_quirk_104(rig):
    """Puce 1.0.4 : press ET release s'affichent « Note off » SANS vélocité. Les fronts sont
    reconstruits par APPARIEMENT : 1er événement = press, 2e = release."""
    r, calls = rig
    foot._DEVICE["note_edges"] = "paired"
    r.feed(_noff(WIRE_CH, 5))           # 1er = press
    r.feed(_noff(WIRE_CH, 5))           # 2e = release
    assert calls["edge"] == [(6, True), (6, False)]


def test_switch_sans_release_devient_un_tap(rig):
    """2026-08-07 : un switch ABSENT de edge_switches ne relâche jamais -> on synthétise le
    release tout de suite (un geste à durée serait INCONTRÔLABLE, pas inopérant : le hold-clear
    du looper partait tout seul 0,6 s après l'appui). Un switch qui relâche n'est pas touché."""
    r, calls = rig
    foot._DEVICE["edge_switches"] = {6}
    r.feed(_non(WIRE_CH, 6, 127))       # SW7 : ne relâche jamais -> release synthétisé
    assert calls["edge"] == [(7, True), (7, False)]
    calls["edge"].clear()
    r.feed(_non(WIRE_CH, 5, 127))       # SW6 : relâche vraiment -> on attend SON release
    assert calls["edge"] == [(6, True)]


# ── table de bindings apprise (pédalier non-FCB) ─────────────────────────────────────────────
def test_bindings_dispatchent_vers_les_intentions(rig):
    """Un pédalier APPRIS envoie ce qu'il envoie ; la table (type, canal, numéro) -> intention
    fait le pont : slot, scène (release avalé), stomp absolu, expression."""
    r, calls = rig
    foot.set_device({"device_id": "z9", "wire_channel": 4, "note_edges": "clean", "note_base": 0,
                     "bindings": [
                         {"event": {"type": "pc", "channel": 3, "number": 5},
                          "intent": {"kind": "slot", "slot": 12}},
                         {"event": {"type": "cc", "channel": 3, "number": 80},
                          "intent": {"kind": "scene", "name": "B"}},
                         {"event": {"type": "cc", "channel": 3, "number": 81},
                          "intent": {"kind": "stomp", "switch": 7, "absolute": True}},
                         {"event": {"type": "cc", "channel": 3, "number": 1},
                          "intent": {"kind": "expression", "pedal": 2}},
                     ]})
    r.feed(_pc(3, 5))
    assert calls["recall"] == [(12, "pc")]
    r.feed(_cc(3, 80, 127))
    r.feed(_cc(3, 80, 0))               # relâchement : la scène est déjà posée -> avalé
    assert calls["scene"] == ["B"]
    r.feed(_cc(3, 81, 127))
    r.feed(_cc(3, 81, 0))
    assert calls["stomp"] == [(7, True), (7, False)]
    r.feed(_cc(3, 1, 42))
    assert calls["treadle"] == [42]     # pedal 2 -> treadle (pedal 1 irait au volume)


def test_evenement_non_lie_retombe_sur_le_filtre_de_canal(rig):
    """Un événement hors table n'est pas une erreur : le chemin codé prend le relais — et ici
    le canal 3 n'est pas le canal du fil (4), donc il finit ignoré, sans effet."""
    r, calls = rig
    foot.set_device({"device_id": "z9", "wire_channel": 4, "note_edges": "clean", "note_base": 0,
                     "bindings": [{"event": {"type": "pc", "channel": 3, "number": 5},
                                   "intent": {"kind": "slot", "slot": 12}}]})
    r.feed(_cc(3, 99, 127))             # CC jamais déclaré, canal ≠ fil
    assert all(v == [] for v in calls.values())


# ── témoins & kill-switch ────────────────────────────────────────────────────────────────────
def test_feed_narme_pas_le_temoin_foot_heard(rig):
    """Vu le 2026-08-07 : une injection vient du RACK, pas du pied. check-foot.py ne doit pas
    rendre `foot_heard` frais — sinon le diagnostic ment à celui dont le câble est débranché."""
    r, calls = rig
    r.feed(_cc(WIRE_CH, 20, 127))
    assert calls["scene"] == ["A"]      # l'événement est bien traité…
    assert foot.last_heard() is None    # …mais le témoin reste muet


def test_killswitch_midi_in_none_ignore_tout(rig, monkeypatch):
    """Input map : MIDI IN = none -> un câble parasite ne pilote plus rien, tout est jeté."""
    r, calls = rig
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "none")
    r.feed(_pc(WIRE_CH, 3))
    r.feed(_cc(WIRE_CH, 20, 127))
    r.feed(_non(WIRE_CH, 5, 127))
    assert all(v == [] for v in calls.values())
