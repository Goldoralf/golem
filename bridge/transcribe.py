# SPDX-License-Identifier: GPL-3.0-or-later
"""DI → notes → figures : les cinq règles de transcription de GoleM.

Contrat : `docs/archive/tablature-study.md` (§9 le POC, §10 le format prouvé).

⚠ POURQUOI CE FICHIER EXISTE
Le POC du 2026-07-26 a établi ces règles sur vérité terrain — et son code n'a JAMAIS été
versionné. Il n'en restait que la prose du contrat, un `.mid` de sortie et un venv de 835 Mo.
Ce module est la reconstruction, cette fois dans le dépôt et sous test.

── CE QUE FAIT L'IA, ET CE QU'ELLE NE FAIT PAS ──
L'IA (Basic Pitch, ONNX 220 Ko, zéro réseau) ÉCOUTE : elle rend des hauteurs avec un début, une
fin et une confiance. Tout ce qui suit — quoi garder, comment grouper, quelle figure écrire —
est PROCÉDURAL. Aucune de ces cinq règles n'est apprise, et c'est délibéré : ce sont elles qui
portent la valeur, elles doivent être lisibles, discutables et corrigibles à la main.

Le module est séparé en deux étages :
  · les règles, fonctions PURES sur des `RawNote` — testables sans modèle, sans audio, sans venv ;
  · le runner, qui appelle Basic Pitch dans `.venv-transcribe` (import paresseux, jamais au
    chargement du bridge : le modèle et ses dépendances pèsent, et le rack doit démarrer sans).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ── Tessitures (règle 1). Bornes en note MIDI, cordes à vide incluses. ────────────────────────
# Guitare standard : mi grave E2 = 40. Une 24e case sur la chanterelle = E6 = 88. Au-delà, ce
# n'est pas un doigt : c'est une harmonique ou un fantôme d'octave du modèle.
RANGES = {
    "drums":  (0, 127),      # une note de batterie n'a pas de tessiture : c'est un élément du kit
    "guitar": (40, 88),
    "bass":   (28, 67),      # si grave d'une 5 cordes B0 = 23 ; on reste sur la 4 cordes E1 = 28
    "voice":  (36, 84),
    "keys":   (21, 108),
}

# Règle 2 — intervalles harmoniques d'une corde qui sonne : la SÉRIE (partiels 2 à 10 : +12, +19, +24, +28, +31,
# +34, +36, +38, +40). L'octave et sa quinte venaient des prises de « le G2 produisait toujours un G3 » ; le banc TX de
# golem.fm (2026-10-29) a vu passer les partiels suivants comme des notes.
HARMONIC_INTERVALS = tuple(sorted({round(12 * math.log2(k)) for k in range(2, 11)}))
HARMONIC_WINDOW_S = 0.040      # attaque « simultanée » : 40 ms
HARMONIC_CONF_RATIO = 0.85     # et moins sûre que sa fondamentale

# Règle 3 — subdivisions candidates, en fraction de noire. Une prise posée tombe sur 1.0
# (noires), un riff rapide sur 0.25 (doubles).
GRID_CANDIDATES = (1.0, 0.5, 1 / 3, 0.25, 1 / 6, 0.125)

# Règle 4 — deux attaques ne font UN accord que si elles tiennent dans la largeur d'un coup de
# médiator. C'est une contrainte PHYSIQUE (la main), pas musicale : un arpège rapide reste deux
# événements même sur une grille grossière. La grille ne fait que la borner par le haut.
STRUM_MAX_S = 0.045

# Règle 5 — une note dont le SON s'arrête bien avant l'attaque suivante a été ÉTOUFFÉE : c'est
# là, et seulement là, qu'un silence s'écrit.
MUTE_RATIO = 0.55              # son < 55 % de l'espacement -> silence sur le reste


@dataclass(frozen=True)
class RawNote:
    """Ce que rend l'IA : une hauteur, un début, une fin, une confiance. Rien d'autre."""
    onset: float               # secondes
    offset: float              # secondes
    pitch: int                 # note MIDI
    conf: float = 1.0          # 0..1

    @property
    def dur(self) -> float:
        return max(0.0, self.offset - self.onset)


@dataclass
class Figure:
    """Ce qu'on écrit : un groupe d'attaques simultanées, à une position, pour une durée."""
    onset_ql: float            # position en noires depuis le début
    dur_ql: float              # figure NOTÉE (règle 5 : l'espacement, pas le son)
    pitches: tuple             # notes MIDI simultanées
    rest_after_ql: float = 0.0 # silence écrit après (étouffement détecté)
    tied: bool = False         # la figure dépasse la mesure -> liée
    src: tuple = field(default_factory=tuple, repr=False)   # les RawNote d'origine


# ── RÈGLE 1 — TESSITURE ───────────────────────────────────────────────────────────────────────
def rule1_range(notes, instrument="guitar", rng=None):
    """Tue les fantômes d'octave hors de portée de l'instrument (G6, A5… sur une guitare).

    La règle la plus bête des cinq, et celle qui enlève le plus de bruit : un modèle
    polyphonique générique n'a aucune idée de ce qu'est une guitare."""
    lo, hi = rng or RANGES.get(instrument, RANGES["guitar"])
    return [n for n in notes if lo <= n.pitch <= hi]


# ── RÈGLE 2 — HARMONIQUES ─────────────────────────────────────────────────────────────────────
def rule2_harmonics(notes, window=HARMONIC_WINDOW_S, ratio=HARMONIC_CONF_RATIO,
                    intervals=HARMONIC_INTERVALS):
    """Écarte la note qui est la CORDE QUI SONNE, pas un doigt.

    Trois conditions ensemble, jamais une seule : à un intervalle de la série harmonique d'une autre note,
    attaquée en même temps (< 40 ms), et MOINS SÛRE qu'elle. La confiance est ce qui empêche de
    tuer une vraie octave jouée — un guitariste en joue tout le temps."""
    keep, dropped = [], []
    for n in notes:
        harmonic_of = None
        for f in notes:
            if f is n or f.pitch >= n.pitch:
                continue
            if (n.pitch - f.pitch) in intervals and abs(n.onset - f.onset) < window \
               and n.conf < f.conf * ratio:
                harmonic_of = f
                break
        (dropped if harmonic_of else keep).append(n)
    return keep, dropped


# ── RÈGLE 3 — GRILLE ADAPTATIVE ───────────────────────────────────────────────────────────────
def rule3_grid(notes, bpm, candidates=GRID_CANDIDATES):
    """DÉDUIT la subdivision des intervalles réels — la trouvaille du POC.

    Une subdivision fixe force un choix perdant : trop grossière, elle écrase les répétitions
    rapides ; trop fine, elle laisse passer les re-déclenchements du modèle comme des notes.
    Ici on regarde les écarts entre attaques et on prend la plus grosse subdivision qui les
    explique — celle dont l'erreur d'alignement est la plus faible. Une prise posée tombe donc
    sur la noire, Paper Kite sur la double, sans rien régler à la main."""
    if len(notes) < 2 or bpm <= 0:
        return 0.25
    spq = 60.0 / bpm                                    # secondes par noire
    onsets = sorted({round(n.onset, 4) for n in notes})
    gaps = [b - a for a, b in zip(onsets, onsets[1:]) if b - a > 0.02]
    if not gaps:
        return 0.25
    best, best_err = 0.25, None
    for g in candidates:
        step = g * spq
        if step <= 0:
            continue
        # erreur RELATIVE au pas : sinon une grille très fine gagne toujours (tout y tombe)
        err = sum(min(x % step, step - (x % step)) / step for x in gaps) / len(gaps)
        # on ne garde une grille plus fine que si elle explique NETTEMENT mieux
        if best_err is None or err < best_err - 0.02:
            best, best_err = g, err
    return best


# ── RÈGLE 4 — FUSION SUR LES ATTAQUES ─────────────────────────────────────────────────────────
def rule4_group_onsets(notes, bpm, grid):
    """Groupe en accords ce qui est attaqué ENSEMBLE — et jamais sur les fins.

    L'erreur du POC, mesurée : prolonger une note tenue jusqu'à l'attaque suivante lui faisait
    avaler tout ce qui venait après (155 notes -> 39, structure détruite). Une note tenue et une
    note jouée par-dessus sont DEUX événements ; seules deux ATTAQUES au même instant n'en font
    qu'un.

    La fenêtre a DEUX bornes, et il faut les deux. Un plafond PHYSIQUE — la largeur d'un coup de
    médiator (45 ms) : au-delà, la main a joué deux fois, quel que soit le tempo. Et la grille,
    qui la resserre encore sur un passage rapide : à 120 BPM une double fait 125 ms, deux
    attaques séparées de 60 ms y sont deux notes, pas un accord. Ma première version n'avait que
    la borne musicale (½ subdivision = 62 ms) et fusionnait ces 60 ms — attrapé par le test."""
    if not notes:
        return []
    spq = 60.0 / bpm if bpm > 0 else 0.5
    win = min(STRUM_MAX_S, grid * spq * 0.5)
    # ⚠ ON TRIE D'ABORD, ET LA RÉFÉRENCE VIENT DU TRI. Première version : `cur` partait de
    # `notes[0]` (l'ordre d'ARRIVÉE) pendant que la boucle parcourait la liste triée. Basic Pitch
    # ne rend pas ses événements par temps croissant : si le premier arrivé était tardif, tous les
    # écarts devenaient négatifs, donc « simultanés », et TOUTE la prise fondait en un seul accord.
    # Mesuré sur une vraie DI : 101 notes -> 1 figure. Aucun de mes tests ne l'attrapait, ils
    # passaient tous des listes déjà triées — c'est l'audio réel qui l'a sorti.
    ordered = sorted(notes, key=lambda x: x.onset)
    groups, cur = [], [ordered[0]]
    for n in ordered[1:]:
        if n.onset - cur[0].onset <= win:
            cur.append(n)
        else:
            groups.append(cur)
            cur = [n]
    groups.append(cur)
    return groups


# ── RÈGLE 5 — DURÉE NOTÉE ≠ DURÉE SONORE ──────────────────────────────────────────────────────
def rule5_figures(groups, bpm, grid, total_s=None, mute_ratio=MUTE_RATIO):
    """La figure vient de l'ESPACEMENT entre attaques ; le son ne sert qu'à voir les silences.

    Sur une guitare la corde résonne librement : la durée sonore d'une note ne dit rien de la
    figure que le musicien a jouée — elle dit seulement jusqu'où ça sonnait. On écrit donc
    l'espacement jusqu'à l'attaque suivante. Le son ne sert qu'à UNE chose : s'il s'arrête bien
    avant (étouffement), c'est un silence, et on l'écrit."""
    if not groups:
        return []
    spq = 60.0 / bpm if bpm > 0 else 0.5
    q = lambda s: round(s / spq / grid) * grid          # secondes -> noires, sur la grille
    out = []
    for i, g in enumerate(groups):
        onset = min(n.onset for n in g)
        if i + 1 < len(groups):
            nxt = min(n.onset for n in groups[i + 1])
        elif total_s is not None:
            nxt = max(total_s, max(n.offset for n in g))
        else:
            nxt = max(n.offset for n in g)
        span = max(nxt - onset, 0.0)
        sound = max(n.offset for n in g) - onset
        span_ql = max(grid, q(span))
        if span > 0 and sound < span * mute_ratio:      # étouffé -> une partie est du silence
            dur_ql = max(grid, q(sound))
            rest_ql = max(0.0, span_ql - dur_ql)
        else:
            dur_ql, rest_ql = span_ql, 0.0
        out.append(Figure(onset_ql=q(onset), dur_ql=dur_ql, rest_after_ql=rest_ql,
                          pitches=tuple(sorted(n.pitch for n in g)), src=tuple(g)))
    return out


# ── LA CHAÎNE ─────────────────────────────────────────────────────────────────────────────────
def apply_rules(notes, bpm, instrument="guitar", total_s=None, rng=None):
    """Les cinq règles dans l'ordre. Rend (figures, rapport) — le rapport dit ce qui a été
    écarté et pourquoi : une transcription qui jette des notes en silence est indéfendable."""
    n0 = len(notes)
    kept = rule1_range(notes, instrument, rng)
    n1 = len(kept)
    kept, harm = rule2_harmonics(kept)
    grid = rule3_grid(kept, bpm)
    groups = rule4_group_onsets(kept, bpm, grid)
    figs = rule5_figures(groups, bpm, grid, total_s=total_s)
    report = {
        "entrees": n0,
        "hors_tessiture": n0 - n1,
        "harmoniques": len(harm),
        "gardees": len(kept),
        "grille_ql": grid,
        "grille_nom": {1.0: "noire", 0.5: "croche", 1 / 3: "triolet de croches",
                       0.25: "double", 1 / 6: "triolet de doubles",
                       0.125: "triple"}.get(grid, str(grid)),
        "groupes": len(groups),
        "accords": sum(1 for g in groups if len(g) > 1),
        "silences": sum(1 for f in figs if f.rest_after_ql > 0),
    }
    return figs, report


# ── RUNNER : l'audio jusqu'aux figures (import paresseux du venv) ─────────────────────────────
def notes_from_audio(wav, onset_threshold=0.5, frame_threshold=0.3, min_note_len_ms=58):
    """Basic Pitch -> [RawNote]. Importé À L'APPEL : le bridge ne doit pas payer le modèle au
    démarrage, et le rack doit pouvoir tourner sans le venv installé."""
    from basic_pitch.inference import predict          # noqa: PLC0415 — volontaire, cf. docstring
    from basic_pitch import ICASSP_2022_MODEL_PATH
    _, _, events = predict(str(wav), ICASSP_2022_MODEL_PATH,
                           onset_threshold=onset_threshold, frame_threshold=frame_threshold,
                           minimum_note_length=min_note_len_ms)
    # events = [(start_s, end_s, pitch_midi, amplitude, [bends])]
    return [RawNote(onset=float(e[0]), offset=float(e[1]), pitch=int(e[2]),
                    conf=float(e[3])) for e in events]


# ── SORTIE : MusicXML tablature (format prouvé §10) ───────────────────────────────────────────
# Accordage standard, corde 1 = mi AIGU (convention MusicXML, et convention guitariste).
TUNING = [("E", 4, 64), ("B", 3, 59), ("G", 3, 55), ("D", 3, 50), ("A", 2, 45), ("E", 2, 40)]
# La BASSE a SA tablature (2026-10-17) : elle était écrite sur les six cordes de la guitare, et tout ce qui
# descend sous le mi grave de la guitare (E1 à D♯2 — l'essentiel d'une ligne de basse) sortait sans corde ni case.
TUNINGS = {
    "guitar": TUNING,
    "bass": [("G", 2, 43), ("D", 2, 38), ("A", 1, 33), ("E", 1, 28)],
}
MAX_FRET = {"guitar": 17, "bass": 24}
# l'instrument General MIDI de la partie (numérotation MusicXML, 1 à 128)
MIDI_PROGRAM = {"guitar": 28, "bass": 34, "keys": 1, "voice": 54}
_STEPS = {0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("E", -1), 4: ("E", 0), 5: ("F", 0),
          6: ("F", 1), 7: ("G", 0), 8: ("A", -1), 9: ("A", 0), 10: ("B", -1), 11: ("B", 0)}


def naive_fingering(pitches, max_fret=17, tuning=TUNING):
    """Corde/case par la position la plus basse possible.

    ⚠ CE N'EST PAS le « vocabulaire guitaristique » du contrat, et ça se voit : sur l'octave que
    le mainteneur joue A:7 + G:9, cette fonction choisit les cordes à vide — mathématiquement optimal,
    musicalement faux. C'est exactement l'écueil que le §9 décrit. Elle est ici pour que la
    chaîne produise une tablature VISIBLE de bout en bout ; le doigté par formes est le chantier
    suivant, et il remplacera cette fonction sans toucher aux cinq règles."""
    used, out = set(), []
    for p in sorted(pitches, reverse=True):             # de l'aigu au grave
        best = None
        for si, t in enumerate(tuning, start=1):
            open_p = t[2]
            fret = p - open_p
            if 0 <= fret <= max_fret and si not in used:
                if best is None or fret < best[1]:
                    best = (si, fret)
        if best:
            used.add(best[0])
            out.append((p, best[0], best[1]))
        else:
            out.append((p, None, None))
    return sorted(out, key=lambda x: -x[0])


_VALUES = [(4.0, "whole"), (2.0, "half"), (1.0, "quarter"), (0.5, "eighth"), (0.25, "16th"), (0.125, "32nd")]


def _type_of(ql):
    """Figure MusicXML la plus proche d'une durée en noires."""
    return min(_VALUES, key=lambda t: abs(math.log(max(ql, 1e-6) / t[0])))[1]


def _typed(ql):
    """`<type>` d'une durée en noires, et `<dot/>` si elle est pointée (une noire pointée n'est pas une noire : le
    rack n'écrivait jamais de point, 2026-10-29) ; sinon la valeur la plus proche."""
    for base, name in _VALUES:
        if abs(ql - 1.5 * base) < 1e-6:
            return f"<type>{name}</type><dot/>"
    return f"<type>{_type_of(ql)}</type>"


def _split_ql(ql):
    """Une durée -> des valeurs écrivables, en noires : simple ou pointée, sinon une somme de valeurs décroissantes
    (un silence de 3 temps est une blanche pointée, pas « une ronde »)."""
    out, left = [], ql
    while left > 1e-6:
        for base, _name in _VALUES:
            if abs(left - 1.5 * base) < 1e-6:
                out.append(1.5 * base)
                left = 0.0
                break
            if base <= left + 1e-6:
                out.append(base)
                left -= base
                break
        else:
            out.append(left)                       # plus fin qu'une triple : la valeur la plus proche
            break
    return out


def _bar_bodies(figures, bar_ql, divisions, nbars, notes_of, pre="", post=""):
    """Le corps de chaque mesure, d'une seule portée : `notes_of(fig, d, dur, first, cont)` écrit les notes d'une
    figure (déjà coupée à la barre), `pre`/`post` sont glissés dans chaque silence (voix, portée). Rend
    (corps par mesure, nombre de mesures réellement remplies)."""
    # répartition en mesures : une figure qui déborde est COUPÉE et liée (cas « > 4 temps » du §9)
    bars, cursor = {}, 0.0
    for f in figures:
        pos, left, first = f.onset_ql, f.dur_ql, True
        while left > 1e-6:
            b = int(pos // bar_ql)
            room = (b + 1) * bar_ql - pos
            take = min(left, room)
            bars.setdefault(b, []).append((pos - b * bar_ql, take, f, first, left - take > 1e-6))
            pos += take
            left -= take
            first = False
        if f.rest_after_ql > 1e-6:
            b = int(pos // bar_ql)
            bars.setdefault(b, []).append((pos - b * bar_ql, f.rest_after_ql, None, True, False))
        cursor = max(cursor, pos)

    def rest(d):
        # un silence s'écrit en valeurs JUSTES, quitte à en poser plusieurs : les ticks se partagent sans reste
        parts, out, at = _split_ql(d / divisions), [], 0
        for k, q in enumerate(parts):
            t = d - at if k == len(parts) - 1 else int(round(q * divisions))
            if t <= 0:
                continue
            out.append(f'<note><rest/><duration>{t}</duration>{pre}{_typed(t / divisions)}{post}</note>')
            at += t
        return "".join(out)

    # ⚠ UNE MESURE FAIT EXACTEMENT SA LONGUEUR, en ticks ENTIERS (2026-09-21, trouvé par
    # tools/check-tab-vs-gp.py). Avant : chaque durée était arrondie SEULE, `max(1, …)` forçait
    # un tick, et deux figures dont les positions arrondies se chevauchaient étaient écrites
    # toutes les deux en entier — des mesures trop pleines, qu'un lecteur ne cale plus : sur
    # Paper Kite, 2 s de dérive sur le morceau. Ici on arrondit les BORNES (début et fin), pas
    # les durées, donc la somme tombe juste ; un chevauchement est ROGNÉ, jamais empilé ; et un
    # silence posé après une figure ne sort pas de sa mesure.
    bar_t = int(round(bar_ql * divisions))
    used = int(math.ceil(max(cursor, bar_ql) / bar_ql))
    out = []
    for b in range(max(nbars or 0, used)):
        body, at_t = [], 0
        for start, dur, fig, first, cont in sorted(bars.get(b, []), key=lambda x: x[0]):
            s_t = max(int(round(start * divisions)), at_t)
            e_t = min(int(round((start + dur) * divisions)), bar_t)
            if e_t <= s_t:
                if fig is None or s_t >= bar_t:
                    continue                            # silence absorbé, ou plus de place
                e_t = s_t + 1                           # une attaque ne disparaît pas à l'arrondi
            if s_t > at_t:                              # trou -> silence explicite
                body.append(rest(s_t - at_t))
            d = e_t - s_t
            body.extend([rest(d)] if fig is None else notes_of(fig, d, d / divisions, first, cont))
            at_t = e_t
        if bar_t > at_t:
            body.append(rest(bar_t - at_t))
        out.append("".join(body))
    return out, used


def _note(k, head, d, dur, first, cont, pre="", post="", notations=""):
    """UNE note, dans l'ordre du schéma MusicXML : chord, hauteur, durée, liaison, (instrument, voix), figure,
    (tête, portée), notations."""
    tie = ('<tie type="start"/>' if cont else '') + ('<tie type="stop"/>' if not first else '')
    tied = ('<tied type="start"/>' if cont else '') + ('<tied type="stop"/>' if not first else '')
    nota = tied + notations
    return (f'<note>{"<chord/>" if k else ""}{head}<duration>{d}</duration>{tie}{pre}'
            f'{_typed(dur)}{post}{f"<notations>{nota}</notations>" if nota else ""}</note>')


def _pitch(p):
    step, alter = _STEPS[p % 12]
    a = f"<alter>{alter}</alter>" if alter else ""
    return f'<pitch><step>{step}</step>{a}<octave>{p // 12 - 1}</octave></pitch>'


def _tempo_dir(bpm):
    return (f'<direction placement="above"><direction-type><metronome>'
            f'<beat-unit>quarter</beat-unit><per-minute>{int(round(bpm))}</per-minute>'
            f'</metronome></direction-type><sound tempo="{int(round(bpm))}"/></direction>')


def _doc(title, part_list, measures):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">\n'
            '<score-partwise version="4.0">\n'
            f'  <work><work-title>{title}</work-title></work>\n'
            f'  <part-list>{part_list}</part-list>\n'
            '  <part id="P1">\n' + "\n".join(
                f'    <measure number="{b + 1}">{m}</measure>' for b, m in enumerate(measures))
            + '\n  </part>\n</score-partwise>\n')


def _part(part_name, program, channel=1, extra=""):
    return (f'<score-part id="P1"><part-name>{part_name}</part-name>{extra}'
            f'<midi-instrument id="P1-I1"><midi-channel>{channel}</midi-channel>'
            f'<midi-program>{program}</midi-program></midi-instrument></score-part>')


def tuning_of(midis):
    """Un accordage en notes MIDI (n'importe quel ordre) -> [(step, octave, midi, alter)] de l'AIGU au grave, la
    forme de `TUNINGS` (une 8 cordes en fa# grave a une corde altérée : `<tuning-alter>`)."""
    out = []
    for p in sorted(midis, reverse=True):
        step, alter = _STEPS[p % 12]
        out.append((step, p // 12 - 1, p, alter))
    return out


def to_musicxml(figures, bpm=120, beats=4, beat_type=4, title="GoleM transcription",
                part_name="Guitar", divisions=4, fingering=None, instrument="guitar", heard=None, b_open=None,
                tuning=None, frets=None, hand=None, neck=None):
    """Figures -> MusicXML. Le format est celui PROUVÉ le 2026-08-09 (§10) : pour un instrument à
    cordes, portée TAB (6 lignes guitare, 4 basse), accordage déclaré, et `<technical><string>/<fret>`
    sur chaque note — sans quoi alphaTab rend une portée standard et la tablature n'existe pas.
    Un instrument SANS frettes (voix) reçoit une portée de notes : clé de sol, ou de fa si la partie
    vit sous le do central. Le clavier a sa partition à deux portées (`to_musicxml_piano`), la
    batterie sa portée de percussion (`to_musicxml_drums`). `heard`/`b_open` : le B mesuré de chaque figure et
    l'étalonnage de la guitare, la preuve du doigté (`fingering.py` §4) ; `neck` : ce que la carte du manche dit de
    chaque figure (`neckmap.costs`). `tuning` (notes MIDI) et `frets` : la
    guitare de la prise (`inharm.guitar`) — une 8 cordes a sa tab à 8 lignes."""
    bar_ql = beats * (4.0 / beat_type)
    tuning = tuning_of(tuning) if tuning else TUNINGS.get(instrument)
    max_fret = int(frets) if frets else MAX_FRET.get(instrument, 17)
    if fingering is None and tuning:
        # LA MAIN PAR FORMES (bridge/fingering.py, lot 4) : le morceau ENTIER est doigté d'un coup — la meilleure
        # suite de positions — avant d'écrire la moindre mesure ; une figure coupée à la barre garde son doigté
        from .fingering import fingering as _shapes
        placed_all = _shapes([f.pitches for f in figures], tuning=[t[2] for t in reversed(tuning)],
                             instrument=instrument, heard=heard, b_open=b_open, neck=neck,
                             weights=dict(hand or {}, **({"max_fret": float(frets)} if frets else {})) or None)
        by_fig = {id(f): pl for f, pl in zip(figures, placed_all)}

        def fingering(ps, _fig=None):
            return by_fig.get(id(_fig)) or naive_fingering(ps, max_fret=max_fret, tuning=tuning)
        fingering.by_figure = True
    if tuning:
        tun = "".join(
            f'<staff-tuning line="{i + 1}"><tuning-step>{t[0]}</tuning-step>'
            + (f'<tuning-alter>{t[3]}</tuning-alter>' if len(t) > 3 and t[3] else '')
            + f'<tuning-octave>{t[1]}</tuning-octave></staff-tuning>'
            for i, t in enumerate(reversed(tuning)))
        clef = (f'<clef><sign>TAB</sign><line>5</line></clef>'
                f'<staff-details><staff-lines>{len(tuning)}</staff-lines>{tun}</staff-details>')
    else:
        allp = sorted(p for f in figures for p in f.pitches)
        low = bool(allp) and allp[len(allp) // 2] < 60
        clef = '<clef><sign>F</sign><line>4</line></clef>' if low else '<clef><sign>G</sign><line>2</line></clef>'
    attrs = (f'<attributes><divisions>{divisions}</divisions><key><fifths>0</fifths></key>'
             f'<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>'
             f'{clef}</attributes>')

    def notes_of(fig, d, dur, first, cont):
        placed = ((fingering(fig.pitches, fig) if getattr(fingering, "by_figure", False) else fingering(fig.pitches))
                  if fingering else [(p, None, None) for p in sorted(fig.pitches, reverse=True)])
        return [_note(k, _pitch(p), d, dur, first, cont,
                      notations=(f"<technical><string>{s}</string><fret>{fr}</fret></technical>"
                                 if s is not None else ""))
                for k, (p, s, fr) in enumerate(placed)]

    bodies, _ = _bar_bodies(figures, bar_ql, divisions, 0, notes_of)
    measures = [(attrs + _tempo_dir(bpm) if b == 0 else "") + body for b, body in enumerate(bodies)]
    return _doc(title, _part(part_name, MIDI_PROGRAM.get(instrument, 28)), measures)


# ── LE CLAVIER : deux portées (lot 1 des partitions, 2026-10-17) ─────────────────────────────────
# Une capture MIDI de clavier est EXACTE : pas d'oreille, juste l'écriture. Main droite en clé de sol, main
# gauche en clé de fa, partagées au do central (le partage le plus simple qui ne ment pas : on ne devine pas
# quelle main joue quoi). La pédale de sustain (CC64) s'écrit sous la portée de fa.
PIANO_SPLIT = 60


def piano_hands(notes, bpm, split=PIANO_SPLIT):
    """Notes EXACTES (capture MIDI) -> (figures main droite, figures main gauche, grille).

    ⚠ PAS la règle 5. Elle déduit la durée écrite de l'ESPACEMENT des attaques, ce qui est juste pour une corde
    qui sonne et faux au clavier : la ronde de la main gauche devenait une noire parce que la main droite
    attaquait à chaque temps. Ici le début ET la fin de chaque note sont quantifiés sur la grille (règle 3),
    main par main ; une figure dure jusqu'à la fin de ses notes, rognée à l'attaque suivante de la MÊME main
    (une voix par portée) ; le reste devient silence."""
    grid = rule3_grid(notes, bpm)
    q = bpm / 60.0

    def snap(x):
        return round(x * q / grid) * grid

    def hand(ns):
        groups = {}
        for n in ns:
            groups.setdefault(snap(n.onset), []).append(n)
        starts = sorted(groups)
        out = []
        for i, a in enumerate(starts):
            end = max(max(snap(n.offset), a + grid) for n in groups[a])
            if i + 1 < len(starts):
                end = min(end, starts[i + 1])
            out.append(Figure(a, max(grid, end - a), tuple(sorted({n.pitch for n in groups[a]}))))
        return out
    return (hand([n for n in notes if n.pitch >= split]), hand([n for n in notes if n.pitch < split]), grid)


def to_musicxml_piano(figures, bpm=120, beats=4, beat_type=4, title="GoleM transcription",
                      part_name="Keys", divisions=4, pedals=(), split=PIANO_SPLIT, hands=None):
    """Figures -> MusicXML piano : UNE partie, DEUX portées (`<staves>2</staves>`), voix 1 sur chacune
    (`<backup>` entre les deux). `hands` = (main droite, main gauche) de `piano_hands` — sinon les
    `figures` sont partagées au do central. `pedals` = [(début_ql, fin_ql)] des appuis de sustain."""
    bar_ql = beats * (4.0 / beat_type)
    bar_t = int(round(bar_ql * divisions))
    if hands:
        hi, lo = hands
        figures = list(hi) + list(lo)
    else:
        hi = [Figure(f.onset_ql, f.dur_ql, tuple(p for p in f.pitches if p >= split), f.rest_after_ql)
              for f in figures if any(p >= split for p in f.pitches)]
        lo = [Figure(f.onset_ql, f.dur_ql, tuple(p for p in f.pitches if p < split), f.rest_after_ql)
              for f in figures if any(p < split for p in f.pitches)]

    def staff(figs, voice, st):
        pre, post = f"<voice>{voice}</voice>", f"<staff>{st}</staff>"

        def notes_of(fig, d, dur, first, cont):
            return [_note(k, _pitch(p), d, dur, first, cont, pre=pre, post=post)
                    for k, p in enumerate(sorted(fig.pitches))]
        return notes_of, pre, post

    last = max([f.onset_ql + f.dur_ql + f.rest_after_ql for f in figures] + [bar_ql])
    nbars = int(math.ceil(last / bar_ql - 1e-9))
    nh, ph, qh = staff(hi, 1, 1)
    # voix 1 sur les DEUX portées : la voix 5 (convention de MuseScore pour la seconde portée) est dessinée
    # GRISÉE par alphaTab, qui la prend pour une voix secondaire (vu au rendu, 2026-10-17)
    nl, pl, ql_ = staff(lo, 1, 2)
    top, _ = _bar_bodies(hi, bar_ql, divisions, nbars, nh, ph, qh)
    bot, _ = _bar_bodies(lo, bar_ql, divisions, nbars, nl, pl, ql_)
    n = max(len(top), len(bot))
    top += [f'<note><rest measure="yes"/><duration>{bar_t}</duration>{ph}{qh}</note>'] * (n - len(top))
    bot += [f'<note><rest measure="yes"/><duration>{bar_t}</duration>{pl}{ql_}</note>'] * (n - len(bot))

    # la pédale : une indication par appui et par relâché, placée par <offset> depuis le début de la mesure
    ped = {}
    for a, z in pedals or ():
        for at, kind in ((a, "start"), (z, "stop")):
            if at is None or at < 0:
                continue
            b = min(int(at // bar_ql), n - 1)
            off = int(round((at - b * bar_ql) * divisions))
            ped.setdefault(b, []).append(
                f'<direction placement="below"><direction-type><pedal type="{kind}" line="yes"/></direction-type>'
                f'<offset>{off}</offset><staff>2</staff></direction>')
    attrs = (f'<attributes><divisions>{divisions}</divisions><key><fifths>0</fifths></key>'
             f'<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time><staves>2</staves>'
             f'<clef number="1"><sign>G</sign><line>2</line></clef>'
             f'<clef number="2"><sign>F</sign><line>4</line></clef></attributes>')
    measures = []
    for b in range(n):
        head = attrs + _tempo_dir(bpm) if b == 0 else ""
        measures.append(head + top[b] + f'<backup><duration>{bar_t}</duration></backup>'
                        + "".join(ped.get(b, [])) + bot[b])
    return _doc(title, _part(part_name, MIDI_PROGRAM["keys"]), measures)


# ── LA BATTERIE : une portée de percussion (lot 2 des partitions, 2026-10-17) ─────────────────────
# Une capture MIDI de batterie électronique est EXACTE, mais ses notes n'ont de sens qu'à travers le
# DESCRIPTEUR du module (config/drumkits/, gravé dans take.json `drums`) : la note 40 est une caisse claire
# ici, un tom là. On lit donc ÉLÉMENT par élément, puis on écrit chaque élément à sa place conventionnelle
# (grosse caisse sous la portée, charleston au-dessus, cymbales en croix). Le canal 10 et la note General MIDI
# de chaque élément ne servent qu'à la LECTURE sonore de la partition.
#   élément -> (ligne affichée, octave, tête de note, note General MIDI)
DRUM_NOTATION = {
    "kick": ("F", 4, None, 36),
    "snare": ("C", 5, None, 38), "snare-rim": ("C", 5, "circle-x", 40), "snare-xstick": ("C", 5, "x", 37),
    "tom1": ("E", 5, None, 50), "tom1-rim": ("E", 5, None, 50),
    "tom2": ("D", 5, None, 47), "tom2-rim": ("D", 5, None, 47),
    "tom3": ("A", 4, None, 43), "tom3-rim": ("A", 4, None, 43),
    "tom4": ("G", 4, None, 41), "tom4-rim": ("G", 4, None, 41),
    "hh-closed": ("G", 5, "x", 42), "hh-closed-edge": ("G", 5, "x", 42), "hh-half": ("G", 5, "x", 42),
    "hh-open": ("G", 5, "circle-x", 46), "hh-open-edge": ("G", 5, "circle-x", 46),
    "hh-pedal": ("D", 4, "x", 44), "hh-splash": ("D", 4, "circle-x", 44),
    "crash1": ("A", 5, "x", 49), "crash1-edge": ("A", 5, "x", 49),
    "crash2": ("B", 5, "x", 57), "crash2-edge": ("B", 5, "x", 57),
    "ride": ("F", 5, "x", 51), "ride-edge": ("F", 5, "x", 59), "ride-bell": ("F", 5, "diamond", 53),
    "splash": ("A", 5, "x", 55), "china": ("B", 5, "circle-x", 52),
}
# la note General MIDI de référence d'un élément : ce qu'on fait passer par les règles (une hauteur par élément)
DRUM_GM = {el: v[3] for el, v in DRUM_NOTATION.items()}
_GM_DRUM = {}
for _el, _v in DRUM_NOTATION.items():
    _GM_DRUM.setdefault(_v[3], _el)


def to_musicxml_drums(figures, bpm=120, beats=4, beat_type=4, title="GoleM transcription",
                      part_name="Drums", divisions=4):
    """Figures (hauteurs = note General MIDI d'un élément, cf. DRUM_GM) -> MusicXML de percussion : clé de
    percussion, `<unpitched>` à la ligne conventionnelle, têtes en croix pour les cymbales, et un
    `<score-instrument>` par élément joué (canal 10) pour que le lecteur sache le faire sonner."""
    bar_ql = beats * (4.0 / beat_type)
    used = sorted({p for f in figures for p in f.pitches if p in _GM_DRUM})
    figures = [Figure(f.onset_ql, f.dur_ql, tuple(p for p in f.pitches if p in _GM_DRUM), f.rest_after_ql)
               for f in figures if any(p in _GM_DRUM for p in f.pitches)]

    def notes_of(fig, d, dur, first, cont):
        out = []
        for k, gm in enumerate(sorted(fig.pitches)):
            step, octv, head, _ = DRUM_NOTATION[_GM_DRUM[gm]]
            out.append(_note(k, f'<unpitched><display-step>{step}</display-step>'
                                f'<display-octave>{octv}</display-octave></unpitched>',
                             d, dur, first, cont, pre=f'<instrument id="P1-X{gm}"/>',
                             # ⚠ TOUJOURS une tête : sans <notehead>, alphaTab dessine la hampe d'une grosse caisse
                             # ou d'une caisse claire SANS tête (vu au rendu, 2026-10-17)
                             post=f"<notehead>{head or 'normal'}</notehead>"))
        return out

    attrs = (f'<attributes><divisions>{divisions}</divisions><key><fifths>0</fifths></key>'
             f'<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>'
             f'<clef><sign>percussion</sign></clef></attributes>')
    bodies, _ = _bar_bodies(figures, bar_ql, divisions, 0, notes_of)
    measures = [(attrs + _tempo_dir(bpm) if b == 0 else "") + body for b, body in enumerate(bodies)]
    insts = "".join(f'<score-instrument id="P1-X{gm}"><instrument-name>{_GM_DRUM[gm]}</instrument-name>'
                    f'</score-instrument>' for gm in used)
    mids = "".join(f'<midi-instrument id="P1-X{gm}"><midi-channel>10</midi-channel>'
                   f'<midi-unpitched>{gm + 1}</midi-unpitched></midi-instrument>' for gm in used)
    part = f'<score-part id="P1"><part-name>{part_name}</part-name>{insts}{mids}</score-part>'
    return _doc(title, part, measures)


def transcribe(wav, bpm, instrument="guitar", total_s=None, **kw):
    """Chaîne complète : audio -> figures + rapport. Le point d'entrée du futur moteur É1."""
    notes = notes_from_audio(wav, **kw)
    return apply_rules(notes, bpm, instrument=instrument, total_s=total_s)


# ── LES PARTIES DU BLOC STANDARD : des partitions EXACTES (lot 3 des partitions, 2026-10-17) ──────
# Une prise jouée par-dessus un Standard emporte la séquence que le moteur a jouée (`standard.seq`, copiée
# à la fin de la prise — docs/standards.md §1). Ce sont des notes que golem a ÉCRITES : rien à écouter,
# seulement à mettre en page. Le swing est noté comme on le lit (croches droites, le « 2/3 » est sous-entendu).
# Les mesures partent du 1er temps de la grille (le décompte est retiré) : l'alignement sur le temps de la
# prise est l'affaire de la grille (lot 5).
STD_PPQ = 960                      # standards.PPQ — recopié : ce module ne dépend pas du bridge
STD_LANES = (                      # lane de la séquence -> (nom de la partie, instrument)
    (0, "Piano", "keys"), (1, "Bass", "bass"), (2, "Drums", "drums"), (4, "Rhythm guitar", "guitar"),
)


def read_seq(path):
    """Le fichier `.standard.seq` -> {len, bar, cin, events: [(ppq, note, vel, lane)]}."""
    head, ev = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            bits = line.split()
            if len(bits) == 2 and bits[0] in ("v", "len", "bar", "cin", "nev"):
                head[bits[0]] = int(bits[1])
            elif len(bits) == 4:
                ev.append(tuple(int(b) for b in bits))
    return {"len": head.get("len", 0), "bar": head.get("bar", 4 * STD_PPQ), "cin": head.get("cin", 0),
            "events": ev}


def _straight(ql):
    """Une position en noires, notée comme on la lit : la croche swinguée (2/3 du temps) s'écrit croche
    droite ; le reste tombe à la double la plus proche."""
    base = math.floor(ql)
    frac = ql - base
    if abs(frac - 2 / 3) < 0.06:
        return base + 0.5
    return base + round(frac * 4) / 4


def _lane_notes(seq, lane):
    """Les notes d'une lane, en NOIRES depuis le 1er temps de la grille : [(début, fin, hauteur)]."""
    cin, out, held = seq["cin"], [], {}
    for at, note, vel, ln in sorted(seq["events"], key=lambda e: (e[0], e[2])):
        if ln != lane:
            continue
        if vel > 0:
            held.setdefault(note, []).append(at)
        elif held.get(note):
            a = held[note].pop(0)
            if a >= cin:
                out.append(((a - cin) / STD_PPQ, (at - cin) / STD_PPQ, note))
    return out


def _spacing_figures(notes, cap=1.0):
    """Coups groupés par attaque, chacun noté jusqu'à l'attaque suivante (plafonné à `cap` noire) : la
    batterie et la pompe, dont le son est court mais la lecture se fait en temps."""
    groups = {}
    for a, _z, p in notes:
        groups.setdefault(_straight(a), set()).add(p)
    starts = sorted(groups)
    out = []
    for i, a in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else a + cap
        out.append(Figure(a, max(0.25, min(cap, nxt - a)), tuple(sorted(groups[a]))))
    return out


def standard_scores(seq, bpm, title="Standard"):
    """La séquence d'un Standard -> [{name, instrument, xml, figures}] — une partition par partie JOUÉE
    (le clic, lane 3, n'en est pas une)."""
    beats = max(1, int(round(seq["bar"] / STD_PPQ)))
    total = max(0.0, (seq["len"] - seq["cin"]) / STD_PPQ)

    def clip(figs):
        # la grille fait N mesures, pas une de plus : l'anticipation du dernier accord ou le dernier coup
        # débordaient d'une mesure vide
        return [Figure(f.onset_ql, min(f.dur_ql, total - f.onset_ql), f.pitches) for f in figs
                if f.onset_ql < total - 1e-6] if total else figs
    out = []
    for lane, name, inst in STD_LANES:
        notes = _lane_notes(seq, lane)
        if not notes:
            continue
        ttl = f"{title} — {name}"
        if inst in ("keys", "bass"):
            # les vraies durées, main par main : la même mise en page que le clavier capté en MIDI (une seconde
            # par noire, puis bpm 60 : piano_hands raisonne en secondes)
            raw = [RawNote(_straight(a), max(_straight(a) + 0.25, _straight(z)), p) for a, z, p in notes]
            hi, lo, _grid = piano_hands(raw, 60, split=PIANO_SPLIT if inst == "keys" else 0)
            hi, lo = clip(hi), clip(lo)
            if inst == "keys":
                xml, nfig = to_musicxml_piano(None, bpm=bpm, beats=beats, title=ttl, part_name=name,
                                              hands=(hi, lo)), len(hi) + len(lo)
            else:
                xml, nfig = to_musicxml(hi, bpm=bpm, beats=beats, title=ttl, part_name=name,
                                        instrument="bass"), len(hi)
        else:
            figs = clip(_spacing_figures(notes))
            if inst == "drums":
                figs = [f for f in figs if any(p in _GM_DRUM for p in f.pitches)]
                xml = to_musicxml_drums(figs, bpm=bpm, beats=beats, title=ttl, part_name=name)
            else:
                xml = to_musicxml(figs, bpm=bpm, beats=beats, title=ttl, part_name=name, instrument="guitar")
            nfig = len(figs)
        out.append({"name": name, "instrument": inst, "xml": xml, "figures": nfig})
    return out
