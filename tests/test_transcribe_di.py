# SPDX-License-Identifier: GPL-3.0-or-later
"""La DI d'une prise armée (stratégie TX de golem.fm, bridge/transcribe_di.py) : le calage d'une phrase sur la grille
du click, les hauteurs d'une attaque, la durée notée, le doigté qui écoute la corde, et l'écriture des valeurs
pointées et des silences. Tout ici est PUR : ni audio, ni modèle, ni venv — le banc audio vit chez golem.fm
(`tools/tx_bench`, run_cases.py)."""
import math
import xml.etree.ElementTree as ET

from bridge import fingering as FG
from bridge import transcribe as T
from bridge import transcribe_di as D

GRID = {"bpm": 100.0, "beats": 4, "beat_type": 4, "downbeat_s": 2.4, "count_in": 1, "end_s": 12.0}
Q = 0.6                                                        # une noire à 100 bpm


def test_un_musicien_qui_presse_reste_sur_ses_noires():
    # TX02 : en avance de 80 à 200 ms à partir de la 7e note — progressivement. Des noires, pas des doubles inventées.
    lead = [0, 0, 0, 0, 0, 0, 0.08, 0.11, 0.14, 0.17, 0.2, 0.2, 0.2]
    got = D.quantize_phrase([4 + i - d / Q for i, d in enumerate(lead)])
    assert got == [4.0 + i for i in range(13)]


def test_deux_attaques_ne_prennent_jamais_la_meme_place():
    got = D.quantize_phrase([4.0, 4.04, 4.5])
    assert len(set(got)) == 3 and got == sorted(got)


def test_la_grille_est_lue_sur_la_prise_et_sans_elle_rien():
    man = {"bpm": 100, "downbeat_s": 2.4, "count_in": 1, "bars": 4, "passes": 1, "sig": {"num": 4, "den": 4}}
    assert D.grid_of(man) == {**GRID, "end_s": 2.4 + 16 * Q}
    assert D.grid_of({**man, "passes": 0})["end_s"] is None    # en boucle : la prise finit avec le fichier
    assert D.grid_of({"bpm": 100}) is None                     # capture libre : les cinq règles
    assert D.grid_of({**man, "downbeat_s": "x"}) is None


def test_le_decompte_est_ecrit_et_le_riff_commence_a_la_mesure_suivante():
    figs, keep = D.figures_of([(2.4, 3.0, [40]), (3.0, 3.6, [41])], GRID, end_s=3.6)
    assert [f.onset_ql for f in figs] == [4.0, 5.0] and keep == [0, 1]


def test_une_note_etouffee_laisse_un_silence_cale_a_la_croche():
    # sonne 0,35 s sur une blanche (1,2 s) : une croche notée (0,58 noire -> 0,5), puis le silence
    figs, _ = D.figures_of([(2.4, 2.75, [40]), (3.6, 4.8, [40])], GRID, end_s=4.8)
    assert (figs[0].dur_ql, figs[0].rest_after_ql) == (0.5, 1.5)
    assert (figs[1].dur_ql, figs[1].rest_after_ql) == (2.0, 0.0)


def test_une_attaque_avant_le_temps_zero_est_ecartee_apres_le_calage():
    figs, keep = D.figures_of([(0.05, 0.3, [40]), (2.4, 3.0, [40])], {**GRID, "count_in": 0}, end_s=3.0)
    assert keep == [1] and figs[0].onset_ql == 0.0


def test_toute_la_serie_harmonique_est_la_corde_qui_sonne():
    assert {12, 19, 24, 28, 31, 34, 36} <= D.HARMONIC_SERIES
    # le partiel +28 (mi grave -> sol dièse aigu), deux fois moins sûr : la corde qui sonne, pas un doigt
    assert D.pick_pitches([(40, 0.9, 1.0), (68, 0.4, 1.0)], None, 40, 88) == ([40], "model")
    # une octave vraiment jouée est aussi sûre que sa fondamentale : elle reste
    assert D.pick_pitches([(40, 0.9, 1.0), (52, 0.8, 1.0)], None, 40, 88) == ([40, 52], "model")


def test_une_note_seule_est_lue_par_pyin():
    assert D.pick_pitches([(52, 0.7, 1.0)], 40, 40, 88) == ([40], "pyin 40 (model 52)")
    assert D.pick_pitches([], 45, 40, 88) == ([45], "pyin")
    assert D.pick_pitches([], 30, 40, 88) == ([], "nothing")    # hors tessiture : rien, plutôt qu'une note fausse


def test_une_corde_qui_sonne_encore_n_est_pas_rejouee():
    # prise 260 : le si attaqué réveille le mi et le la laissés sonner — deux éclats brefs, pYIN tient le si
    cand = [(59, 0.69, 0.26), (45, 0.40, 0.09), (40, 0.39, 0.08)]
    assert D.pick_pitches(cand, 59, 40, 88, ringing={40, 45, 50, 55}, sure=True) == ([59], "pyin")
    # sans pYIN sûr, ou pour des notes longues (un accord gratté), rien n'est retiré
    assert D.pick_pitches(cand, 59, 40, 88, ringing={40, 45}, sure=False)[0] == [40, 45, 59]
    assert D.pick_pitches([(59, 0.7, 0.5), (45, 0.6, 0.5)], 59, 40, 88, ringing={45}, sure=True)[0] == [45, 59]


def test_un_partiel_partage_n_est_pas_une_seconde_note():
    # prise 266 : une ronde de si, le modèle entend aussi un ré à mi-confiance pendant toute la note
    assert D.pick_pitches([(59, 0.85, 2.08), (50, 0.50, 1.93)], 59, 40, 88, sure=True) == ([59], "pyin")
    # une double corde jouée : deux confiances voisines, les deux restent
    assert D.pick_pitches([(59, 0.85, 2.0), (50, 0.70, 2.0)], 59, 40, 88, sure=True)[0] == [50, 59]


def test_une_hauteur_sans_fondamentale_n_est_pas_jouee():
    # prise 286 : la ronde de mi aigu lue [sol, si, mi], pYIN à 0,62 — le si n'a pas de fondamentale (27 dB sous le mi)
    cand = [(59, 0.55, 2.15), (55, 0.45, 0.1), (64, 0.75, 2.23)]
    assert D.pick_pitches(cand, 64, 28, 88, fund={55: 0.2, 59: -5.0, 64: 22.7}) == ([64], "pyin")
    # un accord gratté : des fondamentales voisines, tout reste ; sans lecture, rien ne change
    assert D.pick_pitches([(40, 0.8, 1.0), (47, 0.7, 1.0)], 40, 28, 88, fund={40: 30.0, 47: 26.0})[0] == [40, 47]
    assert D.pick_pitches(cand, 64, 28, 88)[0] == [55, 59, 64]
    # prise 281 : le mi grave (41 Hz), lu sur son 3e partiel, sonne autant que ses octaves — il reste, elles s'en vont
    low = [(28, 0.8, 2.0), (40, 0.45, 2.0), (52, 0.4, 2.0), (62, 0.35, 2.0)]
    assert D.pick_pitches(low, 28, 28, 88, fund={28: 31.0, 40: 30.0, 52: 28.0, 62: 26.0})[0] == [28]
    # prise 292 : le la à vide fait vibrer le la grave (son octave basse) — rien à 165 Hz, il s'en va
    assert D.pick_pitches([(33, 0.6, 2.0), (45, 0.7, 2.0)], None, 28, 88, fund={33: 16.7, 45: 34.9})[0] == [45]
    # prise 288 : le mi aigu fait vibrer le la à vide (le mi en est le 3e partiel) — 27 dB sous lui, il s'en va
    cand = [(76, 0.4, 0.52), (64, 0.74, 2.25), (45, 0.59, 1.93)]
    assert D.pick_pitches(cand, 64, 28, 88, sure=True, fund={45: -3.0, 64: 23.6, 76: 19.7}) == ([64], "pyin")


def test_l_octave_d_une_corde_grave_est_son_partiel():
    # prise 288 : le mi grave lu [mi, mi] et le la [la, la] ; une octave aussi sûre que la grave reste
    assert D.pick_pitches([(52, 0.35, 0.13), (40, 0.47, 2.11), (28, 0.74, 2.2)], 28, 28, 88)[0] == [28]
    assert D.pick_pitches([(33, 0.83, 1.95), (45, 0.58, 1.99)], 33, 28, 88)[0] == [33]
    assert D.pick_pitches([(33, 0.8, 1.95), (45, 0.75, 1.99)], 33, 28, 88)[0] == [33, 45]
    # au-dessus du mi de la 6 cordes, rien ne change (la règle des harmoniques à 0,6)
    assert D.pick_pitches([(40, 0.8, 2.0), (52, 0.55, 2.0)], 40, 28, 88)[0] == [40, 52]


def test_la_regle_2_du_rack_connait_aussi_la_serie():
    notes = [T.RawNote(1.0, 2.0, 40, 0.9), T.RawNote(1.01, 2.0, 68, 0.4)]
    keep, dropped = T.rule2_harmonics(notes)
    assert [n.pitch for n in keep] == [40] and [n.pitch for n in dropped] == [68]


def test_la_corde_entendue_departage_deux_formes_de_la_meme_note():
    # un la (45) : corde 6 case 5 ou corde 5 à vide. Sans oreille, la main reste sur la corde 6 ; les deux cordes
    # étalonnées, un B de corde 5 à vide la fait changer
    b_open = {6: 2.0e-4, 5: 1.0e-4}
    assert FG.fingering([(45,)])[0] == [(45, 6, 5)]
    assert FG.fingering([(45,)], heard=[1.0e-4], b_open=b_open)[0] == [(45, 5, 0)]
    assert FG.evidence_cost(((45, 5, 0),), 1.0e-4, b_open) < 1e-9
    assert FG.fingering([(45,)], heard=[2.0e-4 * 2 ** (5 / 6)], b_open=b_open)[0] == [(45, 6, 5)]
    # une corde candidate non étalonnée : on ne juge pas (comparer du connu à de l'inconnu, c'est déclarer)
    assert FG.fingering([(45,)], heard=[1.0e-4], b_open={6: 2.0e-4})[0] == [(45, 6, 5)]
    # une mesure aberrante coûte au moins le plafond à chaque forme, et ne les départage qu'à peine (0,75 par octave)
    far = [FG.evidence_cost(c, 1.0, b_open) for c in (((45, 5, 0),), ((45, 6, 5),))]
    assert min(far) >= FG.EVIDENCE_CAP and abs(far[0] - far[1]) < 2.0
    # …mais entre deux formes qu'elle contredit, la plus proche gagne (prise 290 : le la grave lu 1,3e-4)
    b8 = {8: 4.0e-4, 7: 2.7e-4, 6: 2.35e-4}
    assert FG.evidence_cost(((33, 7, 0),), 1.31e-4, b8) < FG.evidence_cost(((33, 8, 5),), 1.31e-4, b8)


def test_quand_l_oreille_ne_tranche_pas_la_corde_a_vide():
    # 8 cordes de Alex : sol à vide (corde 3) et ré case 5 (corde 4) prévoient le même B — la ronde de sol est à vide
    eight = (28, 33, 40, 45, 50, 55, 59, 64)
    b8 = {8: 4.0e-4, 7: 2.7e-4, 6: 2.35e-4, 5: 0.9e-4, 4: 0.485e-4, 3: 0.87e-4, 2: 0.295e-4, 1: 0.10e-4}
    assert FG.fingering([(55,)], eight, heard=[0.87e-4], b_open=b8)[0] == [(55, 3, 0)]
    # la 6 cordes de Alex, où les deux B s'écartent de 0,15 octave : l'oreille décide seule, et elle dit case 5
    b6 = {6: 1.87e-4, 5: 1.117e-4, 4: 0.777e-4, 3: 1.247e-4, 2: 0.471e-4, 1: 0.167e-4}
    assert FG.fingering([(55,)], heard=[0.777e-4 * 2 ** (5 / 6)], b_open=b6)[0] == [(55, 4, 5)]
    assert FG.fingering([(55,)], heard=[1.247e-4], b_open=b6)[0] == [(55, 3, 0)]
    # une mesure qui ne dit rien (B nul ou absente) sur une guitare étalonnée : la corde à vide aussi
    assert FG.fingering([(40,)], eight, heard=[0.0], b_open=b8)[0] == [(40, 6, 0)]
    # …mais une note qu'on n'a pas pu lire (`None`, trop brève) ne tire rien vers la corde à vide : la main décide
    assert FG.fingering([(40,)], eight, heard=[None], b_open=b8)[0] == FG.fingering([(40,)], eight)[0]
    # sans étalonnage, rien ne change
    assert FG.fingering([(40,)], eight)[0] == [(40, 7, 7)]


def test_la_main_reste_ou_l_oreille_l_a_vue():
    # riff de Alex (prise 307) : le la de départ lu corde 7 case 12 sans doute possible ; les notes suivantes, trop
    # brèves pour être lues, restent en haut du manche au lieu de redescendre case 3
    eight = (28, 33, 40, 45, 50, 55, 59, 64)
    b8 = {8: 4.0e-4, 7: 2.7e-4, 6: 1.75e-4, 5: 0.9e-4, 4: 0.485e-4, 3: 0.87e-4, 2: 0.295e-4, 1: 0.10e-4}
    line = [(45,), (47,), (48,), (55,), (57,)]
    heard = [2.7e-4 * 4, None, None, None, None]
    blind = FG.fingering(line, eight, heard=[None] * 5, b_open=b8)
    seen = FG.fingering(line, eight, heard=heard, b_open=b8)
    assert seen[0] == [(45, 7, 12)]
    assert min(x[0][2] for x in seen[1:]) > max(x[0][2] for x in blind[1:])
    # sans oreille, aucun point d'appui : le doigté est celui d'avant
    assert FG.fingering(line, eight) == FG.fingering(line, eight, heard=[None] * 5, b_open=b8)


def _notes(xml):
    root = ET.fromstring(xml.split("\n", 2)[2])
    return [(n.find("rest") is not None, int(n.findtext("duration")), n.findtext("type"), n.find("dot") is not None)
            for n in root.iter("note")]


def test_une_noire_pointee_est_ecrite_pointee():
    xml = T.to_musicxml([T.Figure(0.0, 1.5, (52,)), T.Figure(1.5, 2.5, (52,))], bpm=100)
    assert _notes(xml)[0] == (False, 6, "quarter", True)


def test_un_silence_de_trois_temps_est_une_blanche_pointee():
    xml = T.to_musicxml([T.Figure(0.0, 1.0, (52,), rest_after_ql=3.0)], bpm=100)
    assert _notes(xml)[1] == (True, 12, "half", True)


def test_un_silence_qui_n_a_pas_de_valeur_se_decoupe_sans_perdre_un_tick():
    # 1,25 temps de silence : une noire + une double, la mesure fait toujours 16 ticks
    xml = T.to_musicxml([T.Figure(0.0, 2.75, (52,), rest_after_ql=1.25)], bpm=100)
    rests = [n for n in _notes(xml) if n[0]]
    assert [(d, t) for _, d, t, _ in rests] == [(4, "quarter"), (1, "16th")]
    assert sum(d for _, d, _, _ in _notes(xml)) == 16
    assert T._split_ql(3.0) == [3.0] and T._split_ql(1.25) == [1.0, 0.25] and math.isclose(sum(T._split_ql(0.1)), 0.1)


EIGHT = [30, 35, 40, 45, 50, 55, 59, 64]


def test_une_huit_cordes_a_sa_tab_a_huit_lignes_et_son_fa_diese_grave():
    # fa# et sol graves : une seule place, sur la corde 8 — qu'une 6 cordes n'a pas
    xml = T.to_musicxml([T.Figure(0.0, 4.0, (30,)), T.Figure(4.0, 4.0, (31,))], bpm=100, tuning=EIGHT, frets=24)
    root = ET.fromstring(xml.split("\n", 2)[2])
    assert root.findtext(".//staff-lines") == "8"
    low = root.find(".//staff-tuning[@line='1']")
    assert (low.findtext("tuning-step"), low.findtext("tuning-alter"), low.findtext("tuning-octave")) == ("F", "1", "1")
    placed = [(n.findtext("notations/technical/string"), n.findtext("notations/technical/fret"))
              for n in root.iter("note") if n.find("rest") is None]
    assert placed == [("8", "0"), ("8", "1")]


def test_le_profil_d_une_guitare(tmp_path):
    from bridge import inharm
    p = tmp_path / "g.json"
    p.write_text('{"active": "eight", "eight": {"tuning": [64, 30, 35, 40, 45, 50, 55, 59], "frets": 24,'
                 ' "b_open": {"8": 3e-4, "9": 1e-4, "1": -1}}, "default": {"b_open": {"6": 2e-4}}}')
    g = inharm.guitar(str(p))
    assert g["id"] == "eight" and g["tuning"] == EIGHT and g["frets"] == 24 and g["b_open"] == {8: 3e-4}
    assert inharm.guitar(str(p), "default")["tuning"] == [40, 45, 50, 55, 59, 64]     # sans accordage : une 6 standard
    assert inharm.guitar(str(tmp_path / "absent.json"))["id"] == "default"


def test_une_guitare_porte_sa_main(tmp_path):
    # la 8 cordes de Alex, en position haute (prise 305) : sa main couvre 5 cases ; la 6 cordes garde celle du corpus
    from bridge import inharm
    p = tmp_path / "g.json"
    p.write_text('{"eight": {"tuning": [28, 33, 40, 45, 50, 55, 59, 64], "hand": {"reach": 5, "height": 0,'
                 ' "shape_power": 9, "string": "x", "move": -1}}}')
    assert inharm.guitar(str(p), "eight")["hand"] == {"reach": 5.0, "height": 0.0}
    assert inharm.guitar(str(p), "default")["hand"] == {}
    line = [(45,), (47,), (48,), (55,), (57,)]
    low = T.to_musicxml([T.Figure(i, 1.0, ps) for i, ps in enumerate(line)], tuning=list(EIGHT), frets=24)
    high = T.to_musicxml([T.Figure(i, 1.0, ps) for i, ps in enumerate(line)], tuning=list(EIGHT), frets=24,
                         hand={"reach": 5.0, "height": 0.0, "string": 1.0})
    assert low != high


def test_la_tessiture_suit_la_guitare():
    notes = [T.RawNote(0.0, 1.0, 30), T.RawNote(1.0, 2.0, 40)]
    assert [n.pitch for n in T.rule1_range(notes, "guitar")] == [40]                  # une 6 cordes : le fa# est un fantôme
    assert [n.pitch for n in T.rule1_range(notes, "guitar", (30, 88))] == [30, 40]


def test_la_guitare_se_lit_sur_l_accordage_du_riff(tmp_path):
    from bridge import inharm
    p = tmp_path / "g.json"
    p.write_text('{"active": "strat", "lp": {"tuning": [40,45,50,55,59,64]}, "strat": {"tuning": [40,45,50,55,59,64]},'
                 ' "eight": {"tuning": [30,35,40,45,50,55,59,64]}}')
    assert inharm.guitar_for([64, 59, 55, 50, 45, 40], str(p)) == "strat"       # deux 6 standard : celle qu'on joue
    assert inharm.guitar_for([30, 35, 40, 45, 50, 55, 59, 64], str(p)) == "eight"
    assert inharm.guitar_for([38, 45, 50, 55, 59, 64], str(p)) is None           # un drop D que le rack n'a pas


def test_l_accordage_arrive_avec_l_armement():
    from bridge import compo
    base = {"bpm": 100, "bars": 4}
    assert compo.take_params({**base, "tuning": [64, 59, 55, 50, 45, 40]})[0]["tuning"] == [40, 45, 50, 55, 59, 64]
    assert "tuning" not in compo.take_params(base)[0]
    assert compo.take_params({**base, "tuning": [40, 45]}) == (None, "bad take: tuning is 4 to 9 MIDI notes")
    assert compo.take_params({**base, "tuning": "8-std"})[1] == "bad take: tuning is 4 to 9 MIDI notes"


def test_un_accordage_inconnu_s_ecrit_sans_etalonnage(monkeypatch, tmp_path):
    from bridge import inharm, transcribe_cli
    monkeypatch.setattr(inharm, "CALIB", str(tmp_path / "absent.json"))
    g, rng = transcribe_cli._guitar_of({"guitar": None, "tuning": [38, 45, 50, 55, 59, 64]}, "guitar")
    assert g["id"] is None and g["b_open"] == {} and rng == (38, 64 + 22)
    assert transcribe_cli._guitar_of({}, "bass") == (None, None)


def test_la_carte_du_manche_choisit_la_case_qui_sonne_comme_elle():
    # 8 cordes de Alex (2026-11-01, riff 307) : le si et le do graves joués corde 6 cases 7-8 ; sans la carte, le
    # doigté du corpus les descend corde 5 cases 2-3
    eight = (28, 33, 40, 45, 50, 55, 59, 64)
    line = [(45,), (47,), (48,)]
    blind = FG.fingering(line, eight)
    neck = [None, {(6, 7): 0.0, (5, 2): 3.0, (7, 14): 3.0, (8, 19): 5.0},
            {(6, 8): 0.0, (5, 3): 3.0, (7, 15): 3.0, (8, 20): 5.0}]
    seen = FG.fingering(line, eight, neck=neck)
    assert blind[1] != [(47, 6, 7)]
    assert seen[1:] == [[(47, 6, 7)], [(48, 6, 8)]]
    # sans carte, rien ne change ; un écart énorme pèse comme le plafond
    assert FG.fingering(line, eight, neck=[None] * 3) == blind
    huge = [None, {k: (0.0 if v == 0 else 99.0) for k, v in neck[1].items()},
            {k: (0.0 if v == 0 else 99.0) for k, v in neck[2].items()}]
    assert FG.fingering(line, eight, neck=huge) == seen


def test_un_profil_designe_sa_carte_du_manche(tmp_path, monkeypatch):
    from bridge import inharm, neckmap
    p = tmp_path / "g.json"
    p.write_text('{"eight": {"tuning": [28, 33, 40, 45, 50, 55, 59, 64], "neckmap": "eight"}, "six": {}}')
    assert inharm.guitar(str(p), "eight")["neckmap"] == "eight"
    assert inharm.guitar(str(p), "six")["neckmap"] is None
    monkeypatch.setattr(neckmap, "DIR", str(tmp_path))
    (tmp_path / "eight.json").write_text('{"partials": 12, "cells": {}}')
    (tmp_path / "old.json").write_text('{"partials": 8, "cells": {}}')
    assert neckmap.load("eight") == {"partials": 12, "cells": {}}
    assert neckmap.load("old") is None                       # un autre format ne dit rien
    assert neckmap.load("../eight") is None and neckmap.load(None) is None


def test_l_empreinte_d_une_note_ne_depend_pas_de_sa_force():
    np = __import__("pytest").importorskip("numpy")
    from bridge import neckmap
    sr = 48000
    t = np.arange(int(0.5 * sr)) / sr
    f0 = neckmap._hz(45)
    note = sum((0.8 ** k) * np.sin(2 * np.pi * k * f0 * t) for k in range(1, 13))
    soft = neckmap.fingerprint(0.05 * note, sr, 0.02, 0.22, 45)
    loud = neckmap.fingerprint(0.9 * note, sr, 0.02, 0.22, 45)
    assert len(soft) == neckmap.N_PARTIALS and max(abs(a - b) for a, b in zip(soft, loud)) < 0.1
    # deux positions dont l'une a l'empreinte de la note : elle seule ne coûte rien
    other = neckmap.fingerprint(sum((0.5 ** k) * np.sin(2 * np.pi * k * f0 * t) * (1 + (k % 2)) for k in range(1, 13)),
                                sr, 0.02, 0.22, 45)
    nmap = {"cells": {"5:0": {str(w): soft for w in neckmap.WINDOWS_S}, "6:5": {str(w): other for w in neckmap.WINDOWS_S}}}
    c = neckmap.costs(note, sr, [(0.005, 0.25, (45,)), (0.0, 0.3, (45, 52))], nmap, [28, 33, 40, 45, 50, 55, 59, 64])
    assert c[0][(5, 0)] == 0.0 and c[0][(6, 5)] > 1.0 and c[1] is None


def test_deux_doigts_qui_tapent_sont_deux_notes():
    # riff de Alex tout en tapping (prise 392, 120 bpm) : des doubles à 0,10 s, la hauteur change à chaque note
    notes = [(2.252, 47.0), (2.473, 48.0), (2.577, 55.0), (2.694, 57.0)]
    def heard(t0, t1):
        on = [p for t, p in notes if t <= t0 + 1e-6]
        return on[-1] if on else None
    flat = lambda t: 0.0
    assert D.merge_onsets([t for t, _ in notes], flat, heard) == [2.252, 2.473, 2.577, 2.694]
    # le médiator puis la corde : deux pics, UNE hauteur -> une attaque, celle où l'énergie monte le plus
    rise = {9.265: 1.0, 9.404: 6.0}.get
    assert D.merge_onsets([9.265, 9.404], rise, lambda a, b: 52.0) == [9.404]
    # une hauteur qu'on ne lit pas (moins de trois trames sûres) ne sépare rien
    assert D.merge_onsets([9.265, 9.404], rise, lambda a, b: None) == [9.404]
    # le médiator pendant que la note d'avant sonne encore (gammes de Guitar-TECHS, 2026-11-02) : entre ses deux
    # pics, on entend l'ANCIENNE note — ce n'est pas une note nouvelle au premier pic, c'est une seule attaque
    ringing = lambda t0, t1: 52.0 if t1 <= 1.10 else 53.0
    assert D.merge_onsets([1.00, 1.10], {1.00: 1.0, 1.10: 6.0}.get, ringing) == [1.10]
