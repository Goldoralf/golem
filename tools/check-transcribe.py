#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie les CINQ RÈGLES de transcription (docs/archive/tablature-study.md §9), sans le modèle.

Pourquoi sans le modèle : les règles sont des fonctions pures sur des événements. Les tester à
travers Basic Pitch mélangerait deux choses — « le modèle a mal entendu » et « la règle a mal
décidé » — et c'est exactement l'ambiguïté qui a coûté une soirée au POC. Ici chaque règle est
mise devant le cas qui l'a fait naître, avec une entrée fabriquée dont on connaît la réponse.

    ./tools/check-transcribe.py              # les règles, ~0 s, aucune dépendance
    ./tools/check-transcribe.py --audio W    # + la chaîne réelle sur un WAV (exige le venv)
    ./tools/check-transcribe.py --xml OUT    # écrit une tablature MusicXML de démonstration
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.transcribe import (RawNote, apply_rules, rule1_range, rule2_harmonics,  # noqa: E402
                               rule3_grid, rule4_group_onsets, rule5_figures, to_musicxml)

OK = FAIL = 0


def ok(label, cond, detail=""):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if cond else "  \033[31m✗\033[0m ") + label
          + (" — " + detail if detail else ""))
    if cond:
        OK += 1
    else:
        FAIL += 1


def N(onset, dur, pitch, conf=1.0):
    return RawNote(onset=onset, offset=onset + dur, pitch=pitch, conf=conf)


# ── Règle 1 ───────────────────────────────────────────────────────────────────────────────────
def r1():
    print("\nRègle 1 — tessiture (les fantômes d'octave)")
    notes = [N(0, .5, 40), N(.5, .5, 91), N(1, .5, 55), N(1.5, .5, 20)]
    kept = rule1_range(notes, "guitar")
    ok("G6 (91) et le grave impossible (20) écartés d'une guitare",
       [n.pitch for n in kept] == [40, 55], f"gardé {[n.pitch for n in kept]}")
    ok("la même note passe sur une BASSE quand elle est dans SA tessiture",
       [n.pitch for n in rule1_range([N(0, .5, 30)], "bass")] == [30])
    ok("le mi grave à vide (40) n'est jamais écarté — c'est la borne, pas au-delà",
       len(rule1_range([N(0, .5, 40)], "guitar")) == 1)


# ── Règle 2 ───────────────────────────────────────────────────────────────────────────────────
def r2():
    print("\nRègle 2 — harmoniques (« le G2 produisait toujours un G3 »)")
    fond = N(0, 1.0, 43, conf=0.9)
    harm = N(0.01, 0.8, 55, conf=0.5)                      # +12, simultané, moins sûr
    kept, dropped = rule2_harmonics([fond, harm])
    ok("l'octave simultanée et moins sûre est écartée",
       [n.pitch for n in kept] == [43] and [n.pitch for n in dropped] == [55])

    # le contre-exemple qui compte : une octave VRAIMENT jouée doit survivre
    joue = N(0.01, 0.8, 55, conf=0.88)                     # aussi sûre que la fondamentale
    kept, _ = rule2_harmonics([fond, joue])
    ok("une octave JOUÉE (aussi sûre) survit — la confiance est le discriminant",
       sorted(n.pitch for n in kept) == [43, 55])

    tard = N(0.30, 0.8, 55, conf=0.4)                      # +12 mais 300 ms plus tard
    kept, _ = rule2_harmonics([fond, tard])
    ok("une note à +12 attaquée 300 ms plus tard n'est pas une harmonique",
       sorted(n.pitch for n in kept) == [43, 55])

    q = N(0.01, 0.8, 62, conf=0.4)                         # +19
    kept, dropped = rule2_harmonics([fond, q])
    ok("la quinte de l'octave (+19) est traitée comme l'octave",
       [n.pitch for n in dropped] == [62])


# ── Règle 3 ───────────────────────────────────────────────────────────────────────────────────
def r3():
    print("\nRègle 3 — grille ADAPTATIVE (la trouvaille du POC)")
    bpm = 120                                              # une noire = 0,5 s
    posee = [N(i * 0.5, 0.4, 45) for i in range(8)]
    ok("prise posée (attaques à la noire) -> grille = noire",
       abs(rule3_grid(posee, bpm) - 1.0) < 1e-6, f"lu {rule3_grid(posee, bpm):.3f}")
    rapide = [N(i * 0.125, 0.1, 45) for i in range(16)]
    ok("riff en doubles -> grille = double",
       abs(rule3_grid(rapide, bpm) - 0.25) < 1e-6, f"lu {rule3_grid(rapide, bpm):.3f}")
    croches = [N(i * 0.25, 0.2, 45) for i in range(12)]
    ok("croches -> grille = croche",
       abs(rule3_grid(croches, bpm) - 0.5) < 1e-6, f"lu {rule3_grid(croches, bpm):.3f}")
    ok("la grille est DÉDUITE, pas réglée : les deux cas coexistent sans rien toucher",
       rule3_grid(posee, bpm) != rule3_grid(rapide, bpm))


# ── Règle 4 ───────────────────────────────────────────────────────────────────────────────────
def r4():
    print("\nRègle 4 — fusion sur les ATTAQUES, jamais sur les fins")
    bpm, grid = 120, 1.0
    # une tenue de 2 s, et trois notes jouées PENDANT qu'elle sonne
    tenue = N(0.0, 2.0, 40)
    dessus = [N(0.5, 0.2, 55), N(1.0, 0.2, 57), N(1.5, 0.2, 59)]
    groups = rule4_group_onsets([tenue] + dessus, bpm, grid)
    ok("une note tenue n'AVALE pas celles qui sonnent pendant qu'elle dure",
       len(groups) == 4, f"{len(groups)} groupes (attendu 4)")
    acc = [N(0.0, 1.0, 40), N(0.008, 1.0, 47), N(0.015, 1.0, 52)]
    ok("trois attaques à 15 ms = UN accord",
       len(rule4_group_onsets(acc, bpm, grid)) == 1)
    ok("sur une grille de doubles, 60 ms ne sont plus simultanés (2 notes, pas un accord)",
       len(rule4_group_onsets([N(0, .1, 40), N(0.060, .1, 47)], bpm, 0.25)) == 2)
    ok("et 60 ms ne le sont pas non plus sur une grille de NOIRES — la main plafonne à 45 ms",
       len(rule4_group_onsets([N(0, .1, 40), N(0.060, .1, 47)], bpm, 1.0)) == 2)
    # non-régression : Basic Pitch ne rend PAS ses événements par temps croissant. Une version
    # antérieure prenait sa référence dans l'ordre d'arrivée -> toute la prise fondait en un
    # accord (mesuré : 101 notes -> 1 figure sur une vraie DI).
    desordre = [N(2.0, .2, 52), N(0.0, .2, 40), N(1.0, .2, 47), N(3.0, .2, 45)]
    ok("une entrée NON TRIÉE donne le même découpage qu'une entrée triée",
       len(rule4_group_onsets(desordre, bpm, grid)) == 4,
       f"{len(rule4_group_onsets(desordre, bpm, grid))} groupes (attendu 4)")


# ── Règle 5 ───────────────────────────────────────────────────────────────────────────────────
def r5():
    print("\nRègle 5 — durée NOTÉE ≠ durée SONORE")
    bpm, grid = 120, 1.0                                   # noire = 0,5 s
    # deux noires, mais la corde résonne 3x trop longtemps : la figure vient de l'espacement
    laisse = [N(0.0, 1.5, 45), N(0.5, 1.5, 47), N(1.0, 1.5, 49)]
    figs = rule5_figures(rule4_group_onsets(laisse, bpm, grid), bpm, grid, total_s=1.5)
    ok("corde qui résonne 1,5 s, attaques à la noire -> NOIRES écrites",
       all(abs(f.dur_ql - 1.0) < 1e-6 for f in figs[:2]),
       f"durées {[round(f.dur_ql, 2) for f in figs]}")
    ok("aucun silence là où le musicien n'a pas étouffé",
       all(f.rest_after_ql == 0 for f in figs[:2]))
    # étouffée : le son s'arrête au quart de l'espacement
    mute = [N(0.0, 0.12, 45), N(1.0, 0.4, 47)]
    figs = rule5_figures(rule4_group_onsets(mute, bpm, grid), bpm, grid, total_s=1.4)
    ok("note étouffée -> un silence est écrit après elle",
       figs[0].rest_after_ql > 0, f"figure {figs[0].dur_ql} + silence {figs[0].rest_after_ql}")


# ── La chaîne, sur la vérité terrain décrite au §9 ────────────────────────────────────────────
def chain():
    print("\nLa chaîne — les 7 sections annoncées (§9 du contrat)")
    bpm = 120
    spq = 60.0 / bpm
    notes, t, plan = [], 0.0, []
    # noires / blanches / noires / blanches / rapide / tenues / blanches
    for figure, count in [(1.0, 4), (2.0, 2), (1.0, 4), (2.0, 2), (0.25, 8), (4.0, 1), (2.0, 2)]:
        for _ in range(count):
            # la corde résonne au-delà de la figure : c'est tout le piège de la règle 5
            notes.append(N(t, min(figure * spq * 1.6, 2.2), 45 + len(notes) % 5, conf=0.9))
            plan.append(figure)
            t += figure * spq
    figs, rep = apply_rules(notes, bpm, "guitar", total_s=t)
    ok("chaque attaque donne UNE figure (rien n'est avalé)",
       len(figs) == len(plan), f"{len(figs)} figures pour {len(plan)} attaques")
    justes = sum(1 for f, want in zip(figs, plan) if abs(f.dur_ql - want) < 0.26)
    ok("chaque figure retrouve sa valeur (noire / blanche / double / ronde)",
       justes >= len(plan) - 1, f"{justes}/{len(plan)} exactes")
    print(f"     rapport : grille « {rep['grille_nom']} » · {rep['gardees']} notes gardées · "
          f"{rep['harmoniques']} harmonique(s) écartée(s) · {rep['silences']} silence(s)")


# ── Le MusicXML produit est bien une TABLATURE (format prouvé §10) ────────────────────────────
def xml(path=None):
    print("\nSortie — MusicXML tablature")
    bpm = 120
    notes = [N(0.0, 0.4, 40), N(0.0, 0.4, 47), N(1.0, 0.4, 43), N(1.0, 0.4, 50),
             N(2.0, 1.8, 52), N(4.0, 0.4, 45)]
    figs, _ = apply_rules(notes, bpm, "guitar", total_s=4.5)
    x = to_musicxml(figs, bpm=bpm, title="GoleM — check-transcribe")
    ok("la portée est déclarée TAB à 6 cordes", "<sign>TAB</sign>" in x and "<staff-lines>6</staff-lines>" in x)
    ok("chaque note porte corde ET case", x.count("<technical>") == x.count("<pitch>"),
       f"{x.count('<technical>')} technical / {x.count('<pitch>')} pitch")
    ok("l'accordage est déclaré", x.count("<staff-tuning") == 6)
    ok("le tempo voyage avec la partition", "<per-minute>120</per-minute>" in x)
    if path:
        open(path, "w").write(x)
        print(f"     écrit : {path}")


def audio(wav, bpm, instrument):
    print(f"\nChaîne réelle — {wav}")
    try:
        from bridge.transcribe import transcribe
        figs, rep = transcribe(wav, bpm, instrument=instrument)
    except Exception as e:
        print(f"  \033[33m·\033[0m modèle indisponible ({type(e).__name__}: {e}) — "
              f"les règles restent vérifiées sans lui")
        return
    print(f"     {rep['entrees']} notes entendues -> {rep['gardees']} gardées "
          f"({rep['hors_tessiture']} hors tessiture, {rep['harmoniques']} harmoniques)")
    print(f"     grille « {rep['grille_nom']} » · {rep['groupes']} figures dont "
          f"{rep['accords']} accords · {rep['silences']} silences")
    ok("le modèle a entendu quelque chose", rep["entrees"] > 0)
    ok("les règles n'ont pas tout jeté", rep["gardees"] > 0)
    ok("des figures sortent", len(figs) > 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", help="WAV de DI à transcrire pour de vrai (exige .venv-transcribe)")
    ap.add_argument("--bpm", type=float, default=120)
    ap.add_argument("--instrument", default="guitar")
    ap.add_argument("--xml", help="écrit une tablature MusicXML de démonstration")
    a = ap.parse_args()
    print("Les cinq règles de transcription — docs/archive/tablature-study.md §9")
    r1(); r2(); r3(); r4(); r5(); chain(); xml(a.xml)
    if a.audio:
        audio(a.audio, a.bpm, a.instrument)
    print(f"\n{OK} ✓   {FAIL} ✗")
    sys.exit(1 if FAIL else 0)
