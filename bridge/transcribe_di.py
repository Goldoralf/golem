# SPDX-License-Identifier: GPL-3.0-or-later
"""LA DI D'UNE PRISE ARMÉE → figures : les attaques du DI, les hauteurs de l'oreille, la grille du click
(stratégie TX v1 de golem.fm, banc `maestrium/backend/tools/tx_bench`, validée le 2026-10-29 sur TX01 et TX02 :
13/13 hauteurs, 12/13 rythmes — portée ici, docs/compo.md §5).

Ce qui change par rapport aux cinq règles (`transcribe.apply_rules`), qui restent celles d'une prise SANS grille :
  1. une note n'existe que si le DI montre une ATTAQUE (flux spectral) : un redéclenchement du modèle au milieu
     d'une note qui sonne n'est plus une note, et la main qui étouffe non plus (le niveau ne monte pas) — sauf une
     note LIÉE, dont la hauteur change nettement et qui continue de sonner ;
  2. dans une attaque, une hauteur nettement moins sûre qu'une plus grave à un intervalle de la SÉRIE HARMONIQUE
     (partiels 2 à 10) est la corde qui sonne, pas un doigt ; une attaque seule est lue par pYIN, plus juste que
     le modèle polyphonique sur un DI propre ;
  3. la grille est celle du CLICK, lue sur la prise (`bpm`, `downbeat_s`, `count_in`) : rien n'est deviné, et la
     phrase ENTIÈRE est calée d'un coup (Viterbi) — un musicien qui presse de 80 à 200 ms presse doucement, une
     double inventée fait sauter l'écart d'un coup ;
  4. la durée notée va jusqu'à l'attaque suivante, sauf si le son s'éteint avant (30 dB sous le pic) : la fin se
     cale alors à la croche, le reste est un silence.

Deux étages, comme `transcribe.py` : le calage et l'écriture, PURS (testés sans audio ni venv) ; l'écoute
(librosa, Basic Pitch), importée à l'appel, dans `.venv-transcribe` seulement.
"""
from __future__ import annotations

import math

from .transcribe import RANGES, Figure

SR = 22050
HOP = 256
#: Deux attaques à moins de ça sont UNE attaque (le pic de flux est souvent double : le médiator, puis la corde).
MERGE_S = 0.150
#: …sauf si la hauteur change entre elles d'au moins ça (2026-11-01, riff du mainteneur TOUT EN TAPPING, 120 bpm : des
#: doubles à 0,125 s, six notes sur quinze fusionnées avec la précédente). Le médiator puis la corde, c'est UNE
#: hauteur ; deux doigts qui tapent, deux. None : la fusion d'avant, au temps seul.
MERGE_KEEP_SEMITONES = 0.7
MERGE_STRICT = True
#: Fenêtre où une note du modèle « appartient » à une attaque du DI.
ATTACK_BEFORE_S, ATTACK_AFTER_S = 0.060, 0.110
#: Intervalles de la série harmonique (partiels 2 à 10), en demi-tons arrondis : 12, 19, 24, 28, 31, 34, 36, 38, 40.
HARMONIC_SERIES = frozenset(round(12 * math.log2(k)) for k in range(2, 11))
#: Une harmonique est nettement MOINS sûre que sa fondamentale ; un doigt, non.
HARMONIC_RATIO = 0.6
#: Sous cette fraction de la plus sûre de l'attaque, ce n'est pas une note jouée.
WEAK_RATIO = 0.4
#: Le son est « éteint » quand il passe à ce nombre de dB sous le pic de l'attaque.
MUTE_DB = 30.0
MUTE_RATIO = 0.55
#: Une attaque JOUÉE fait monter le niveau (35-45 dB depuis le silence, quelques dB sur une corde qui sonne) ;
#: la main qui étouffe, non. Et elle n'est pas un murmure à côté des autres attaques de la prise.
MIN_RISE_DB = 3.0
MAX_BELOW_DB = 24.0
#: Une note LIÉE (hammer-on, glissé) : la hauteur change d'au moins ça, et le niveau tient encore 200 ms plus loin
#: (une corde qui MEURT sous la main fait dériver pYIN d'un ou deux demi-tons, mais elle s'éteint).
LEGATO_SEMITONES = 0.7
LEGATO_HOLD_S = 0.20
LEGATO_DROP_DB = 8.0
PYIN_MIN_PROB = 0.3
#: UNE CORDE QUI SONNE ENCORE n'est pas jouée à nouveau (2026-10-29, prise 260 : « mi la ré sol si mi » laissés sonner,
#: le si lu [mi, la, si]) : quand pYIN tient UNE hauteur nette, une note brève du modèle à une hauteur jouée dans les
#: RING_S précédentes est la corde d'avant que l'attaque réveille, pas un doigt.
RING_S = 4.0                           # un mi grave à vide sonne encore 2,5 s plus tard
GHOST_MAX_S = 0.20
PYIN_SURE = 0.8                        # médiane de la probabilité pYIN sur SURE_S après l'attaque
SURE_S = 0.20
#: UNE HAUTEUR SANS FONDAMENTALE n'est pas jouée (2026-10-30, prise 286 : le mi aigu lu [sol, si, mi] — le 4e partiel
#: du si est le 3e du mi, et pYIN, à 0,62, n'était pas « sûr ») : une corde jouée sonne d'abord sur sa fondamentale. Le
#: modèle en propose une à FUND_GAP_DB sous la fondamentale la plus forte de l'attaque : c'est le partiel d'une autre.
#: Mesuré sur la prise : 27 dB pour le si fantôme, 22 pour le sol ; une note d'accord grattée est à quelques dB.
FUND_GAP_DB = 20.0
FUND_S = (0.04, 0.30)                  # la fenêtre lue après l'attaque
FUND_N_FFT = 8192                      # 2,7 Hz par case à 22 050 Hz : le mi grave d'une 8 cordes (41 Hz) se lit
#: SOUS LE MI DE LA 6 CORDES, la fondamentale est plus faible que ses partiels (le mi grave d'une 8 cordes à 41 Hz,
#: 16 dB sous son 3e partiel — le micro la coupe) : c'est le 3e partiel qui dit si la corde sonne. Il n'est le partiel
#: d'aucune de ses octaves : le la grave qu'un la à vide fait vibrer par sympathie (prise 292, l'un est l'octave de
#: l'autre) n'a presque rien à 3 fois sa fondamentale.
FUND_LOW = 40
#: …et l'écart y est plus serré : le la grave fantôme de la prise 292 est 18 dB sous le la à vide ; joués, le la grave
#: et le mi grave sont à 2 et 3 dB de leur octave.
FUND_GAP_LOW_DB = 12.0
OCTAVE_LOW_RATIO = 0.85

#: LE CALAGE D'UNE PHRASE (Viterbi) : chaque attaque choisit une position de la grille (le douzième de noire
#: couvre doubles et triolets). Trois coûts :
#:   · la COMPLEXITÉ de la position (le temps < la croche < la double < le triolet) ;
#:   · l'avance/retard du musicien sur le click, |d| (il ne joue pas une noire à côté) ;
#:   · le CHANGEMENT de cette avance d'une note à l'autre : presser est progressif.
LATTICE = 12
POS_COST = {0: 0.0, 6: 0.8, 3: 1.5, 9: 1.5, 4: 1.8, 8: 1.8, 2: 2.5, 10: 2.5}
SEARCH_QL = 0.6
W_ABS, ABS_SCALE = 1.0, 0.5
W_JUMP, JUMP_SCALE = 1.0, 0.25


# ── LE CALAGE (pur) ───────────────────────────────────────────────────────────────────────────────
def quantize_phrase(qls):
    """Positions entendues (en noires depuis le temps 0 de la partition) -> positions sur la grille, la phrase
    entière d'un coup. Deux attaques ne tombent jamais sur la même position, ni à rebours."""
    if not qls:
        return []
    cands = []
    for x in qls:
        lo, hi = math.ceil((x - SEARCH_QL) * LATTICE), math.floor((x + SEARCH_QL) * LATTICE)
        row = []
        for k in range(lo, hi + 1):
            c = POS_COST.get(k % LATTICE)
            if c is None:
                continue
            p = k / LATTICE
            d = x - p
            row.append((p, d, c + W_ABS * (d / ABS_SCALE) ** 2))
        cands.append(row or [(round(x * 4) / 4, 0.0, 0.0)])
    back = [[(c, None) for _, _, c in cands[0]]]
    for i in range(1, len(cands)):
        cur = []
        for p, d, c in cands[i]:
            opt = (math.inf, None)
            for j, (pp, dp, _) in enumerate(cands[i - 1]):
                if pp >= p - 1e-9 or back[-1][j][0] == math.inf:
                    continue
                v = back[-1][j][0] + c + W_JUMP * ((d - dp) / JUMP_SCALE) ** 2
                if v < opt[0]:
                    opt = (v, j)
            cur.append(opt)
        back.append(cur)
    j = min(range(len(back[-1])), key=lambda k: back[-1][k][0])
    out = []
    for i in range(len(cands) - 1, -1, -1):
        out.append(cands[i][j][0])
        j = back[i][j][1]
    return out[::-1]


def grid_of(man):
    """La grille du click lue sur la prise : {bpm, beats, beat_type, downbeat_s, count_in, end_s|None} — ou None
    pour une prise sans grille (capture libre, prise de set : les cinq règles s'en chargent)."""
    try:
        bpm = float(man.get("bpm") or 0)
        down = man.get("downbeat_s")
        if bpm <= 0 or down is None:
            return None
        down = float(down)
    except (TypeError, ValueError):
        return None
    sig = man.get("sig") or {}
    beats, beat_type = int(sig.get("num") or 4), int(sig.get("den") or 4)
    bar_ql = beats * 4.0 / beat_type
    q = 60.0 / bpm
    bars, passes = int(man.get("bars") or 0), int(man.get("passes") or 0)
    # EN BOUCLE (`passes: 0`) la prise s'arrête au Stop : elle finit avec le fichier
    end = down + bars * passes * bar_ql * q if bars and passes else None
    return {"bpm": bpm, "beats": beats, "beat_type": beat_type, "downbeat_s": down,
            "count_in": int(man.get("count_in") or 0), "end_s": end}


def figures_of(events, grid, end_s):
    """Les notes ENTENDUES [(attaque s, fin du son s, hauteurs)] -> figures sur la grille. Le temps 0 de la
    partition est le début de la mesure de décompte (convention du rack : le décompte est écrit, le riff commence
    à la mesure suivante). Rend (figures, indices des notes gardées)."""
    q = 60.0 / grid["bpm"]
    bar_ql = grid["beats"] * 4.0 / grid["beat_type"]
    t_zero = grid["downbeat_s"] - grid["count_in"] * bar_ql * q
    qls = quantize_phrase([(t - t_zero) / q for t, _, _ in events])
    # une attaque un peu en avance sur le premier temps s'y cale ; ce qui reste AVANT le temps 0 est écarté APRÈS
    # le calage, jamais sur l'instant brut (une attaque lente est datée trop tôt)
    keep = [i for i, x in enumerate(qls) if x >= 0]
    end_ql = (end_s - t_zero) / q
    figs = []
    for n, i in enumerate(keep):
        t0, sound_end, ps = events[i]
        on_ql = qls[i]
        next_ql = qls[keep[n + 1]] if n + 1 < len(keep) else end_ql
        span = max(next_ql - on_ql, 0.0)
        dur, rest = span, 0.0
        sound_ql = (sound_end - t0) / q
        if span > 0 and sound_ql < MUTE_RATIO * span:
            # une extinction est floue (la main se pose, la corde meurt) : elle se cale à la croche, jamais plus
            # fin qu'une double
            dur = min(span, max(round(sound_ql / 0.5) * 0.5, 0.25))
            rest = span - dur
        figs.append(Figure(onset_ql=on_ql, dur_ql=dur, pitches=tuple(sorted(ps)), rest_after_ql=rest))
    return figs, keep


def pick_pitches(cand, mono, lo, hi, ringing=(), sure=False, fund=None):
    """Les hauteurs JOUÉES à une attaque : `cand` = [(hauteur, confiance, durée s)] du modèle autour de l'attaque,
    `mono` = la hauteur pYIN (ou None), `sure` = pYIN la tient nettement, `ringing` = les hauteurs jouées juste avant,
    `fund` = {hauteur: niveau dB de sa fondamentale après l'attaque} (None : pas lu). Rend (hauteurs, d'où elles
    viennent)."""
    cand = [(p, c, d) for p, c, d in cand if lo <= p <= hi]
    if fund and cand:
        # (sous FUND_LOW, `fund` est le niveau du 3e partiel : voir `listen`) — prise 288 : le la à vide qu'un mi aigu
        # fait vibrer par sympathie, 27 dB sous lui, en est le 3e partiel
        def louder(p):
            return max((fund.get(q, -120.0) for q, _c, _d in cand if q != p), default=-120.0)
        cand = [(p, c, d) for p, c, d in cand
                if p not in fund or fund[p] >= louder(p) - (FUND_GAP_LOW_DB if p < FUND_LOW else FUND_GAP_DB)]
    # …et L'OCTAVE D'UNE CORDE GRAVE (prise 288 : le mi grave lu [mi, mi], le la [la, la] — 0,64 et 0,70 de la
    # confiance de la grave) : sous FUND_LOW, l'octave est le partiel le plus fort de la corde, pas une seconde corde
    # tant que le modèle ne l'entend pas presque autant qu'elle
    for low, lc, _d in [x for x in cand if x[0] < FUND_LOW]:
        cand = [(p, c, d) for p, c, d in cand if (p - low) not in (12, 24) or c >= OCTAVE_LOW_RATIO * lc]
    if sure and mono is not None:
        cand = [(p, c, d) for p, c, d in cand if p == mono or not (p in ringing and d < GHOST_MAX_S)]
        # …et le FANTÔME d'un partiel partagé (prise 266 : la ronde de si lue [ré, si] — le 3e partiel du si est le 5e
        # du ré) : pYIN tient une seule hauteur, le modèle en ajoute une nettement moins sûre que celle-là
        top = max((c for p, c, _d in cand if p == mono), default=None)
        if top is not None:
            cand = [(p, c, d) for p, c, d in cand if p == mono or c >= HARMONIC_RATIO * top]
    cand = [(p, c) for p, c, _d in cand]
    best = max((c for _, c in cand), default=0.0)
    kept = []
    for p, c in sorted(cand):
        if c < WEAK_RATIO * best:
            continue
        harm = any(fp < p and (p - fp) in HARMONIC_SERIES and c < HARMONIC_RATIO * fc for fp, fc in cand)
        if not harm and p not in kept:
            kept.append(p)
    if mono is not None and not (lo <= mono <= hi):
        mono = None
    if len(kept) <= 1 and mono is not None:
        return [mono], ("pyin" if not kept or kept[0] == mono else f"pyin {mono} (model {kept[0]})")
    if not kept:
        return [], "nothing"
    return kept, "model"


# ── L'ÉCOUTE (venv) ───────────────────────────────────────────────────────────────────────────────
def _frames(t0, t1):
    a = int(t0 * SR / HOP)
    return a, max(a + 1, int(t1 * SR / HOP))


def merge_onsets(found, rise, heard):
    """Les pics de flux -> les attaques. Deux pics à moins de MERGE_S sont UNE attaque (le médiator, puis la corde),
    celle après laquelle l'énergie monte le plus (`rise(t)`, dB) — sauf si la hauteur change entre eux d'au moins
    MERGE_KEEP_SEMITONES : deux doigts qui tapent, deux notes. La hauteur est lue sur le CORPS de chaque note,
    jusqu'au pic suivant (`heard(t0, t1)` : demi-tons MIDI, ou None) : dans les 70 ms qui suivent une note tapée,
    pYIN n'a qu'une trame sûre sur six (prise 392)."""
    def differ(a, b):
        return a is not None and b is not None and abs(a - b) >= MERGE_KEEP_SEMITONES

    def new_pitch(t_prev, t, t_next):
        if MERGE_KEEP_SEMITONES is None:
            return False
        between, after = heard(t_prev + 0.02, t - 0.005), heard(t + 0.02, min(t_next, t + 0.30) - 0.005)
        if MERGE_STRICT:
            # au médiator, le 1er pic tombe pendant que la note d'AVANT sonne encore : entre les deux pics, c'est elle
            # qu'on entend (gammes de Guitar-TECHS, 2026-11-02 : la règle seule doublait les notes inventées) — deux
            # notes seulement si une hauteur NOUVELLE commence au premier pic
            return differ(heard(t_prev - 0.15, t_prev - 0.005), between) and differ(between, after)
        return differ(between, after)

    onsets = []
    for i, t in enumerate(found):
        t_next = found[i + 1] if i + 1 < len(found) else t + 0.30
        if onsets and t - onsets[-1] < MERGE_S and not new_pitch(onsets[-1], t, t_next):
            if rise(t) > rise(onsets[-1]):
                onsets[-1] = t
            continue
        onsets.append(t)
    return onsets


def listen(wav, grid, instrument="guitar", rng=None):
    """Le DI -> les notes entendues [(attaque, fin du son, hauteurs)], la fin de la prise (s) et le journal de ce
    qui a été écarté. Importe librosa et Basic Pitch : à n'appeler que dans `.venv-transcribe`."""
    import librosa
    import numpy as np
    from .transcribe import notes_from_audio

    y, _ = librosa.load(str(wav), sr=SR, mono=True)
    lo, hi = rng or RANGES.get(instrument, RANGES["guitar"])
    raw = notes_from_audio(wav)
    f0, _voiced, prob = librosa.pyin(y, fmin=librosa.midi_to_hz(lo - 1), fmax=librosa.midi_to_hz(hi + 1),
                                     sr=SR, hop_length=HOP)
    f0 = librosa.hz_to_midi(f0)
    db = 20 * np.log10(librosa.feature.rms(y=y, hop_length=HOP)[0] + 1e-9)
    power = np.abs(librosa.stft(y, n_fft=FUND_N_FFT, hop_length=HOP)) ** 2
    bins = librosa.fft_frequencies(sr=SR, n_fft=FUND_N_FFT)
    q = 60.0 / grid["bpm"]
    down = grid["downbeat_s"]
    end_s = grid["end_s"] or len(y) / SR

    # LES ATTAQUES : deux pics de flux trop proches sont UNE attaque, celle après laquelle l'énergie monte le plus
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    found = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, backtrack=True, units="time")

    def rise(t):
        a, b = _frames(t, t + 0.10)
        return float(db[a:b].max()) - float(db[max(0, int((t - 0.03) * SR / HOP))])

    def heard(t0, t1):
        a, b = _frames(t0, t1)
        seg, pr = f0[a:b], prob[a:b]
        ok = ~np.isnan(seg) & (pr > PYIN_MIN_PROB)
        # trois trames sûres au moins, comme `pitch_med` : à deux, un faux départ (la main qui touche la corde avant
        # l'attaque, TX02 à 9,27 s) se lisait un ton à côté et gardait deux attaques pour une note
        return float(np.median(seg[ok])) if ok.sum() >= 3 else None

    onsets = merge_onsets([float(t) for t in found], rise, heard)
    onsets = [t for t in onsets if down - 0.5 * q <= t < end_s - 0.05]

    def level(t):
        a = int(t * SR / HOP)
        return float(db[a:a + int(0.14 * SR / HOP)].max()), float(db[max(0, a - 3)])

    def fundamental(p, t0):
        """Le niveau (dB) de la fondamentale de `p` juste après l'attaque (son 3e partiel sous FUND_LOW) : la case la
        plus forte à ±3 % (une au moins)."""
        a, b = _frames(t0 + FUND_S[0], t0 + FUND_S[1])
        f = float(librosa.midi_to_hz(p)) * (3 if p < FUND_LOW else 1)
        k = int(np.argmin(np.abs(bins - f)))
        w = max(1, int(round(0.03 * f / (bins[1] - bins[0]))))
        seg = power[max(0, k - w):k + w + 1, a:b]
        return float(10 * np.log10(seg.max(axis=0).mean() + 1e-12)) if seg.size else -120.0

    def pitch_med(t0, t1):
        a, b = _frames(t0, t1)
        seg, pr = f0[a:b], prob[a:b]
        ok = ~np.isnan(seg) & (pr > PYIN_MIN_PROB)
        return float(np.median(seg[ok])) if ok.sum() >= 3 else None

    def legato(t):
        before, after = pitch_med(t - 0.15, t - 0.02), pitch_med(t + 0.04, t + 0.25)
        if before is None or after is None or abs(after - before) < LEGATO_SEMITONES:
            return False
        a, later = int(t * SR / HOP), int((t + LEGATO_HOLD_S) * SR / HOP)
        return later < len(db) and db[later] >= db[a] - LEGATO_DROP_DB

    lv = {t: level(t) for t in onsets}
    loudest = max((p for p, _ in lv.values()), default=0.0)
    dropped = {t for t in onsets
               if (lv[t][0] - lv[t][1] < MIN_RISE_DB and not legato(t)) or lv[t][0] < loudest - MAX_BELOW_DB}
    log = [f"noise {t:.3f}s (rise {lv[t][0] - lv[t][1]:+.1f} dB, peak {lv[t][0]:.1f} dB)" for t in sorted(dropped)]
    onsets = [t for t in onsets if t not in dropped]

    events = []
    for i, t0 in enumerate(onsets):
        nxt = onsets[i + 1] if i + 1 < len(onsets) else end_s
        # une note du modèle qui commence après l'attaque SUIVANTE est à elle, pas à celle-ci (des doubles tapées à
        # 0,08 s : le ré de la prise 392 daté 3,148 s tombait aussi dans la fenêtre du do d'avant -> un accord)
        cand = [(n.pitch, n.conf, n.dur) for n in raw
                if t0 - ATTACK_BEFORE_S <= n.onset <= min(t0 + ATTACK_AFTER_S, nxt)]
        m = pitch_med(t0 + 0.04, min(nxt, t0 + 0.40))
        a, b = _frames(t0 + 0.04, min(nxt, t0 + 0.04 + SURE_S))
        sure = bool(len(prob[a:b])) and float(np.median(prob[a:b])) >= PYIN_SURE
        ringing = {p for t, _e, ps_ in events if t0 - t < RING_S for p in ps_}
        fund = {p: fundamental(p, t0) for p in {c[0] for c in cand}} if len(cand) > 1 else None
        ps, why = pick_pitches(cand, int(round(m)) if m is not None else None, lo, hi, ringing=ringing, sure=sure,
                               fund=fund)
        # la fin du son : MUTE_DB sous le pic, cherchée APRÈS le pic (l'attaque est ramenée au creux qui la précède)
        a, b = _frames(t0, nxt)
        seg = db[a:b]
        head = seg[: max(1, int(0.15 * SR / HOP))]
        pk = int(head.argmax()) if len(seg) else 0
        peak = float(head[pk]) if len(seg) else -120.0
        below = np.where(seg[pk:] < peak - MUTE_DB)[0]
        sound_end = t0 + (pk + below[0]) * HOP / SR if len(below) else nxt
        log.append(f"attack {t0:.3f}s -> {ps} ({why}), sounds until {sound_end:.3f}s")
        if ps:
            events.append((t0, min(sound_end, nxt), ps))
    return events, end_s, log, len(raw), len(dropped)


def transcribe_take(wav, man, instrument="guitar", rng=None):
    """Une DI d'une prise À GRILLE -> (figures, rapport, notes gardées [(attaque, fin du son, hauteurs)] une par
    figure, grille) — ou None si la prise n'a pas de grille."""
    grid = grid_of(man)
    if not grid:
        return None
    events, end_s, log, n_raw, n_noise = listen(wav, grid, instrument, rng)
    figs, keep = figures_of(events, grid, end_s)
    report = {"engine": "tx1", "entrees": n_raw, "attaques": len(events), "bruits": n_noise, "gardees": len(figs),
              "accords": sum(1 for f in figs if len(f.pitches) > 1),
              "silences": sum(1 for f in figs if f.rest_after_ql > 0), "journal": log[-60:]}
    return figs, report, [events[i] for i in keep], grid
