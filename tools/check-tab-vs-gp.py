#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare une transcription faite par le rack à la partition Guitar Pro de référence.

    ./tools/check-tab-vs-gp.py recordings/perf-20260921-…          # la prise (scores/index.json)
    ./tools/check-tab-vs-gp.py recordings/perf-…/scores/Input-1.musicxml
    ./tools/check-tab-vs-gp.py perf-20260921-… --gp X.gp --sync manual_sync.json
    ./tools/check-tab-vs-gp.py --self-test                          # l'outil contre lui-même

POURQUOI CET OUTIL EXISTE
La transcription du rack (bridge/transcribe.py : Basic Pitch puis cinq règles) était jugée à
l'oreille et à l'œil, sur une vérité terrain de quelques mesures (POC du 2026-07-26, « ~80 % »).
Pour Paper Kite on a mieux : golem.fm tient la partition .gp ET une carte de synchro posée à la
main sur le même fichier audio que le backing du rack (stems identiques octet pour octet). Une
prise lancée au switch 5 démarre avec le backing à 0 : chaque note transcrite a donc une date
dans l'audio, et chaque note de la partition aussi. On peut COMPTER au lieu d'estimer.

CE QU'IL MESURE, ET CE QU'IL NE MESURE PAS
Appariement note à note sur l'ATTAQUE (±50 ms, hauteur exacte — la convention MIR), puis à
l'octave près : précision, rappel, F1, par piste de guitare de la partition. Il mesure ce que la
partition MusicXML ÉCRIT, donc le modèle ET les règles ensemble — y compris la quantification :
une note juste posée sur la mauvaise double croche compte fausse à ±50 ms. D'où la seconde ligne,
à ± un demi-pas de la grille de la transcription, et le « plafond » de --self-test : la partition
passée elle-même par les règles, ce qu'un auditeur PARFAIT obtiendrait à ce tempo.
Il ne mesure PAS le doigté (corde/case) : la hauteur seule. Ni les durées.

L'ALIGNEMENT
Référence : la carte de synchro de golem.fm (`manual_sync.json`, sinon `songsterr_sync.json`,
même forme), c.-à-d. la date audio du début de chaque mesure + `introOffsetSec` ; entre deux
points, le temps est linéaire dans la mesure (sémantique alphaTab). Sans carte : le tempo de la
partition, et il DÉRIVE (Paper Kite va de 79 à 94 BPM). Puis un balayage du décalage résiduel
(±5 s, histogramme des écarts d'attaque à hauteur égale) ET de la transposition (±3 demi-tons —
guitare accordée en mi♭ ou Whammy engagée). Les deux valeurs retenues sont DITES en tête.
"""
import argparse
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from bisect import bisect_right
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = os.environ.get("GOLEMFM_DATA", os.path.expanduser("~/code/maestrium/data/songs"))
RECORDINGS = os.path.join(ROOT, "recordings")
DEFAULT_SLUG = "glass_lanterns_paper_kite"


class Note:
    __slots__ = ("t", "pitch", "track", "chord")

    def __init__(self, t, pitch, track=None, chord=1):
        self.t, self.pitch, self.track, self.chord = t, pitch, track, chord


# ══ LA RÉFÉRENCE : Guitar Pro 7/8 (.gp = zip, Content/score.gpif) ══════════════════════════════
NOTE_QL = {"Whole": 4.0, "Half": 2.0, "Quarter": 1.0, "Eighth": 0.5, "16th": 0.25,
           "32nd": 0.125, "64th": 0.0625, "128th": 0.03125}


def _gpif_root(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return ET.fromstring(z.read("Content/score.gpif"))
    if path.lower().endswith(".gpif"):
        return ET.parse(path).getroot()
    sys.exit(f"✗ {path} n'est pas un Guitar Pro 7/8 (.gp = zip). Le .gp5 demande pyguitarpro, "
             "absent ici : donne le .gp.")


def _prop(el, name):
    for p in el.iter("Property"):
        if p.get("name") == name:
            return p
    return None


def _play_order(masterbars, warn):
    """Ordre de LECTURE des mesures (reprises + fins alternatives) -> [(index, occurrence)].
    Les sauts D.S./Coda ne sont pas suivis : on le dit."""
    out, occ, i, start, passes = [], Counter(), 0, 0, Counter()
    if any(mb.find("Directions") is not None for mb in masterbars):
        warn.append("la partition porte des sauts (D.S./Coda) non suivis : lecture linéaire")
    while i < len(masterbars):
        mb = masterbars[i]
        rep = mb.find("Repeat")
        if rep is not None and rep.get("start") == "true" and passes[i] == 0 and i != start:
            start = i
        alt = (mb.findtext("AlternateEndings") or "").split()
        cur_pass = passes[start] + 1
        if not alt or str(cur_pass) in alt:
            out.append((i, occ[i]))
            occ[i] += 1
        if rep is not None and rep.get("end") == "true":
            count = int(rep.get("count") or 2)
            if passes[start] + 1 < count:
                passes[start] += 1
                i = start
                continue
            passes[start] = 0
            start = i + 1
        i += 1
    return out


def read_reference(path, warn):
    """-> ({track_id: {name, notes:[(ql_abs, pitch, chord_size)]}}, bars:[(idx, occ, ql0, ql_len)],
    tempo_qpm, n_dead)."""
    r = _gpif_root(path)
    tracks = {t.get("id"): t for t in r.find("Tracks")}
    masterbars = list(r.find("MasterBars"))
    bars = {b.get("id"): b for b in r.find("Bars")}
    voices = {v.get("id"): v for v in r.find("Voices")}
    beats = {b.get("id"): b for b in r.find("Beats")}
    notes = {n.get("id"): n for n in r.find("Notes")}
    rhythms = {x.get("id"): x for x in r.find("Rhythms")}

    tempos = []
    for a in r.find("MasterTrack").iter("Automation"):
        if a.findtext("Type") == "Tempo":
            val = (a.findtext("Value") or "120 2").split()
            if len(val) > 1 and val[1] != "2":
                warn.append(f"tempo en unité {val[1]} (pas la noire) lu comme noires")
            tempos.append((int(a.findtext("Bar") or 0), float(val[0])))
    tempos.sort()
    if len(tempos) > 1:
        warn.append(f"{len(tempos)} changements de tempo : seul le premier sert hors carte de synchro")
    qpm = tempos[0][1] if tempos else 120.0

    def ql_of(rh):
        d = NOTE_QL.get(rh.findtext("NoteValue") or "Quarter", 1.0)
        dot = rh.find("AugmentationDot")
        if dot is not None:
            n = int(dot.get("count") or 1)
            d *= 2 - 0.5 ** n
        tup = rh.find("PrimaryTuplet")
        if tup is not None:
            d *= int(tup.get("den") or 1) / int(tup.get("num") or 1)
        return d

    def bar_len(mb):
        num, den = (mb.findtext("Time") or "4/4").split("/")
        return int(num) * 4.0 / int(den)

    guitars = {tid: t for tid, t in tracks.items()
               if "guitar" in ((t.findtext("InstrumentSet/Type") or "") + (t.findtext("Name") or "")).lower()
               and "bass" not in (t.findtext("InstrumentSet/Type") or "").lower()}
    out = {tid: {"name": " ".join((t.findtext("Name") or "").split()), "notes": []} for tid, t in guitars.items()}
    order = _play_order(masterbars, warn)
    track_pos = {tid: i for i, tid in enumerate(r.find("MasterTrack").findtext("Tracks").split())}
    dead, mism, bar_list, cursor = 0, 0, [], 0.0
    for idx, occ in order:
        mb = masterbars[idx]
        blen = bar_len(mb)
        bar_list.append((idx, occ, cursor, blen))
        bar_ids = mb.findtext("Bars").split()
        for tid, t in guitars.items():
            tun = [int(x) for x in (_prop(t, "Tuning").findtext("Pitches") or "").split()] if _prop(t, "Tuning") is not None else []
            capo = int((_prop(t, "CapoFret").findtext("Fret") if _prop(t, "CapoFret") is not None else 0) or 0)
            bar = bars[bar_ids[track_pos[tid]]]
            for vid in (bar.findtext("Voices") or "").split():
                if vid == "-1":
                    continue
                pos = cursor
                for bid in (voices[vid].findtext("Beats") or "").split():
                    be = beats[bid]
                    d = ql_of(rhythms[be.find("Rhythm").get("ref")])
                    grace = be.find("GraceNotes") is not None
                    ids = (be.findtext("Notes") or "").split()
                    sounding = []
                    for nid in ids:
                        n = notes[nid]
                        tie = n.find("Tie")
                        if tie is not None and tie.get("destination") == "true":
                            continue                          # suite liée : pas une attaque
                        if _prop(n, "Muted") is not None:
                            dead += 1                         # note morte (x) : pas de hauteur
                            continue
                        s, f = _prop(n, "String"), _prop(n, "Fret")
                        calc = None
                        if s is not None and f is not None and tun:
                            calc = tun[int(s.findtext("String"))] + int(f.findtext("Fret")) + capo
                        m = _prop(n, "Midi")
                        pitch = int(m.findtext("Number")) if m is not None else calc
                        if calc is not None and pitch != calc:
                            mism += 1
                        if pitch is not None:
                            sounding.append(pitch)
                    for p in sounding:
                        out[tid]["notes"].append((pos, p, len(sounding)))
                    if not grace:
                        pos += d
        cursor += blen
    if mism:
        warn.append(f"{mism} note(s) dont la propriété Midi contredit corde+case : Midi retenu")
    return out, bar_list, qpm, dead


# ══ LA CARTE DE SYNCHRO : partition (noires) -> audio (s) ═══════════════════════════════════════
def read_sync(path):
    d = json.load(open(path))
    pts = d.get("sync_points") or []
    return {(int(p["barIndex"]), int(p.get("barOccurence") or 0)): (float(p.get("barPosition") or 0),
             float(p["millisecondOffset"]) / 1000.0) for p in pts}, float(d.get("introOffsetSec") or 0), d


def time_map(bar_list, qpm, sync=None, intro=0.0):
    """Fonction ql_abs -> secondes audio. Ancres = points de synchro (début de mesure + position
    dans la mesure) ; linéaire entre deux ; au-delà, le tempo de la partition."""
    spq = 60.0 / qpm
    anchors = []
    if sync:
        for idx, occ, ql0, blen in bar_list:
            p = sync.get((idx, occ))
            if p:
                anchors.append((ql0 + p[0] * blen, intro + p[1]))
    anchors.sort()
    if len(anchors) < 2:
        return (lambda q: intro + q * spq), anchors
    xs = [a[0] for a in anchors]

    def f(q):
        i = bisect_right(xs, q) - 1
        if i < 0:
            return anchors[0][1] + (q - xs[0]) * spq
        if i >= len(anchors) - 1:
            return anchors[-1][1] + (q - xs[-1]) * spq
        (q0, t0), (q1, t1) = anchors[i], anchors[i + 1]
        return t0 + (q - q0) * (t1 - t0) / (q1 - q0)
    return f, anchors


# ══ LA TRANSCRIPTION : le MusicXML que le rack écrit (bridge/transcribe_cli.py) ═════════════════
_STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def read_musicxml(path, bpm=None):
    """-> ([Note], bpm, grille_s). Lecture SÉQUENTIELLE (sémantique MusicXML : c'est ce qu'un
    lecteur voit), accords par <chord/>, suites liées ignorées, backup/forward suivis."""
    r = ET.parse(path).getroot()
    part = r.find("part")
    div, tempo, cur, last_on = 1, None, 0, 0
    beats, beat_type, m_start = 4, 4, 0
    events = []
    for m in part.findall("measure"):
        # ⚠ CHAQUE MESURE REPART DE SA POSITION NOMINALE. Le writer du rack produit des mesures
        # TROP PLEINES quand deux figures arrondies se chevauchent ; un curseur qui court d'une
        # mesure à l'autre reportait l'excédent et dérivait de 2 s sur Paper Kite (mesuré :
        # plafond 0,22 au lieu de 0,67). Un lecteur de partition pose chaque mesure à sa place.
        cur = m_start
        for el in m:
            if el.tag == "attributes" and el.find("time") is not None:
                beats = int(el.findtext("time/beats") or beats)
                beat_type = int(el.findtext("time/beat-type") or beat_type)
            if el.tag == "attributes" and el.findtext("divisions"):
                div = int(el.findtext("divisions"))
            elif el.tag == "direction":
                s = el.find("sound")
                if s is not None and s.get("tempo") and tempo is None:
                    tempo = float(s.get("tempo"))
            elif el.tag == "sound" and el.get("tempo") and tempo is None:
                tempo = float(el.get("tempo"))
            elif el.tag == "backup":
                cur -= int(el.findtext("duration") or 0)
            elif el.tag == "forward":
                cur += int(el.findtext("duration") or 0)
            elif el.tag == "note":
                dur = int(el.findtext("duration") or 0)
                chord = el.find("chord") is not None
                on = last_on if chord else cur
                if not chord:
                    last_on = cur
                    cur += dur
                if el.find("rest") is not None:
                    continue
                if any(t.get("type") == "stop" for t in el.findall("tie")):
                    continue                                  # suite liée
                p = el.find("pitch")
                if p is None:
                    continue
                midi = (int(p.findtext("octave")) + 1) * 12 + _STEP[p.findtext("step")] + int(float(p.findtext("alter") or 0))
                events.append((on / div, midi))
        m_start += int(round(beats * 4.0 / beat_type * div))
    q = bpm or tempo or 120.0
    spq = 60.0 / q
    cnt = Counter(e[0] for e in events)
    out = [Note(ql * spq, p, chord=cnt[ql]) for ql, p in events]
    # grille : le plus petit écart entre attaques distinctes, en noires (ce que la règle 3 a choisi)
    ons = sorted(set(e[0] for e in events))
    gaps = [b - a for a, b in zip(ons, ons[1:]) if b - a > 1e-6]
    grid_ql = min(gaps) if gaps else 0.25
    return out, q, grid_ql * spq


def resolve_input(arg, source=None):
    """.musicxml | dossier de prise | nom ou uid de prise -> (musicxml, take_dir|None, manifeste)."""
    if arg.endswith(".musicxml") and os.path.isfile(arg):
        td = os.path.dirname(os.path.dirname(os.path.abspath(arg)))
        return arg, td, _manifest(td)
    cand = arg if os.path.isdir(arg) else os.path.join(RECORDINGS, arg)
    if not os.path.isdir(cand):
        try:
            from bridge.takes import uid_of
        except Exception:
            uid_of = str.lower
        hits = [d for d in os.listdir(RECORDINGS) if uid_of(d) == arg.lower()] if os.path.isdir(RECORDINGS) else []
        if not hits:
            sys.exit(f"✗ ni fichier, ni prise : {arg}")
        cand = os.path.join(RECORDINGS, hits[0])
    idx_p = os.path.join(cand, "scores", "index.json")
    if not os.path.isfile(idx_p):
        sys.exit(f"✗ {cand} n'est pas transcrite (pas de scores/index.json) — Recordings ▸ Transcribe")
    idx = json.load(open(idx_p))
    srcs = [s for s in idx.get("sources", []) if s.get("file")]
    if source:
        srcs = [s for s in srcs if s.get("src") == source]
    else:
        srcs = [s for s in srcs if s.get("instrument", "guitar") == "guitar"] or srcs
        srcs.sort(key=lambda s: (s.get("kind") != "audio", -(s.get("figures") or 0)))
    if not srcs:
        sys.exit(f"✗ aucune source transcrite{(' nommée ' + source) if source else ''} dans {cand}")
    return os.path.join(cand, srcs[0]["file"]), cand, _manifest(cand)


def _manifest(td):
    try:
        return json.load(open(os.path.join(td, "take.json")))
    except Exception:
        return {}


# ══ L'APPARIEMENT ═══════════════════════════════════════════════════════════════════════════════
def match(ref, est, tol, key=lambda p: p):
    """Appariement 1-1 à hauteur égale (selon `key`) et |Δt| ≤ tol. Par hauteur, deux listes
    triées : le glouton « au plus tôt » est optimal pour des fenêtres de même largeur.
    -> liste de (i_ref, i_est, dt)."""
    by_r, by_e = defaultdict(list), defaultdict(list)
    for i, n in enumerate(ref):
        by_r[key(n.pitch)].append(i)
    for j, n in enumerate(est):
        by_e[key(n.pitch)].append(j)
    pairs = []
    for k, ri in by_r.items():
        ej = by_e.get(k)
        if not ej:
            continue
        ri = sorted(ri, key=lambda i: ref[i].t)
        ej = sorted(ej, key=lambda j: est[j].t)
        a = b = 0
        while a < len(ri) and b < len(ej):
            dt = est[ej[b]].t - ref[ri[a]].t
            if dt < -tol:
                b += 1
            elif dt > tol:
                a += 1
            else:
                pairs.append((ri[a], ej[b], dt))
                a += 1
                b += 1
    return pairs


def prf(n_match, n_ref, n_est):
    p = n_match / n_est if n_est else 0.0
    r = n_match / n_ref if n_ref else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def best_alignment(ref, est, sweep, tol, transpositions):
    """Décalage global (s) et transposition (demi-tons) qui maximisent les appariements :
    histogramme des écarts d'attaque à hauteur égale, fenêtre glissante de ±tol."""
    best = (-1, 0.0, 0)
    by_r = defaultdict(list)
    for n in ref:
        by_r[n.pitch].append(n.t)
    for v in by_r.values():
        v.sort()
    step = 0.005
    for tr in transpositions:
        hist = Counter()
        for n in est:
            ts = by_r.get(n.pitch + tr)
            if not ts:
                continue
            lo, hi = bisect_right(ts, n.t - sweep - tol), bisect_right(ts, n.t + sweep + tol)
            for t in ts[lo:hi]:
                hist[round((t - n.t) / step)] += 1       # décalage à AJOUTER à la transcription
        if not hist:
            continue
        w = int(round(tol / step))
        keys = sorted(hist)
        for k in keys:
            if abs(k * step) > sweep:
                continue
            s = sum(hist.get(k + d, 0) for d in range(-w, w + 1))
            if s > best[0] or (s == best[0] and abs(k) < abs(round(best[1] / step))):
                best = (s, k * step, tr)
    return best[1], best[2]


def report(ref_tracks, est, tol, grid_s, head, bpm=None):
    """Le tableau par piste + la meilleure + les erreurs typiques."""
    print(head)
    rows, best = [], None
    combos = [(tid, v["name"], v["notes"]) for tid, v in ref_tracks.items()]
    if len(ref_tracks) > 1:
        allnotes = [n for v in ref_tracks.values() for n in v["notes"]]
        combos.append(("+".join(ref_tracks), "toutes les guitares", allnotes))
    print(f"\n  {'piste de référence':44} {'notes':>6} {'justes':>6} {'préc.':>6} {'rappel':>6} {'F1':>5} │ {'F1 octave près':>14}")
    for tid, name, notes in combos:
        m = match(notes, est, tol)
        mo = match(notes, est, tol, key=lambda p: p % 12)
        p, r, f = prf(len(m), len(notes), len(est))
        _, _, fo = prf(len(mo), len(notes), len(est))
        rows.append((tid, name, notes, m, f))
        label = f"{tid} {name}"[:44]
        print(f"  {label:44} {len(notes):6d} {len(m):6d} {p:6.0%} {r:6.0%} {f:5.2f} │ {fo:14.2f}")
        if len(tid.split("+")) == 1 and (best is None or f > best[4]):
            best = rows[-1]
    tid, name, notes, m, f = best
    print(f"\n→ la piste qui colle le mieux : {tid} « {name} » (F1 {f:.2f})")
    if grid_s and grid_s / 2 > tol:
        mg = match(notes, est, grid_s / 2)
        pg, rg, fg = prf(len(mg), len(notes), len(est))
        print(f"  à ± un demi-pas de grille ({grid_s / 2 * 1000:.0f} ms, la quantification de la "
              f"transcription) : préc. {pg:.0%} · rappel {rg:.0%} · F1 {fg:.2f}")
    if bpm:
        try:
            cf, cfg, cgrid, gname = ceiling(notes, bpm, tol)
            print(f"  plafond des règles sur cette piste à {bpm:g} BPM (grille « {gname} ») : F1 {cf:.2f} à "
                  f"±{tol * 1000:.0f} ms, {cfg:.2f} à ± un demi-pas — l'écart AU-DESSUS revient au modèle")
        except Exception as e:
            print(f"  plafond des règles non calculé : {type(e).__name__}: {e}")

    # erreurs typiques, sur la meilleure piste
    mr = {i for i, _, _ in m}
    me = {j for _, j, _ in m}
    oct_ = match([notes[i] for i in range(len(notes)) if i not in mr],
                 [est[j] for j in range(len(est)) if j not in me], tol, key=lambda p: p % 12)
    near = match([notes[i] for i in range(len(notes)) if i not in mr],
                 [est[j] for j in range(len(est)) if j not in me], 0.150)
    single = [i for i, n in enumerate(notes) if n.chord == 1]
    chordal = [i for i, n in enumerate(notes) if n.chord > 1]
    dts = sorted(dt for _, _, dt in m)
    print("\nErreurs typiques (meilleure piste) :")
    if dts:
        med = dts[len(dts) // 2] * 1000
        print(f"  · décalage des notes justes : médiane {med:+.0f} ms "
              f"({'la transcription tarde' if med > 10 else 'la transcription devance' if med < -10 else 'centré'})")
    print(f"  · {len(near)} note(s) à la bonne hauteur mais entre ±{tol * 1000:.0f} et ±150 ms "
          f"(attaque mal placée — souvent la grille)")
    print(f"  · {len(oct_)} note(s) justes à l'OCTAVE près seulement (fantômes d'octave, règle 1-2)")
    if chordal:
        rs = sum(1 for i in single if i in mr) / len(single) if single else 0
        rc = sum(1 for i in chordal if i in mr) / len(chordal)
        verdict = "les accords perdent des notes" if rc < rs - 0.1 else "pas d'écart net"
        print(f"  · rappel : notes isolées {rs:.0%} · notes d'accord {rc:.0%} ({verdict})")
    extra = len(est) - len(me) - len(oct_) - len(near)
    print(f"  · {max(0, extra)} note(s) transcrite(s) sans rien d'approchant dans la partition "
          f"(fantômes, autre partie, ou jeu libre)")
    return best


def reference_notes(gp, sync_path, warn):
    tracks, bar_list, qpm, dead = read_reference(gp, warn)
    sync, intro, sdoc = (read_sync(sync_path) if sync_path else (None, 0.0, {}))
    tm, anchors = time_map(bar_list, qpm, sync, intro)
    ref = {tid: {"name": v["name"], "notes": [Note(tm(q), p, tid, c) for q, p, c in v["notes"]]}
           for tid, v in tracks.items()}
    return ref, qpm, dead, anchors, intro, sdoc


def _default_paths(man):
    slug = ((man or {}).get("backing") or {}).get("slug") or DEFAULT_SLUG
    d = os.path.join(DATA, slug)
    gp = next((os.path.join(d, f) for f in ("source.gp", "synced.gp") if os.path.isfile(os.path.join(d, f))), None)
    sync = next((os.path.join(d, f) for f in ("manual_sync.json", "songsterr_sync.json")
                 if os.path.isfile(os.path.join(d, f))), None)
    return slug, gp, sync


def ceiling(notes, bpm, tol):
    """Le PLAFOND des règles : la partition elle-même passée par les cinq règles puis écrite en
    MusicXML, au tempo de la prise. C'est ce qu'un auditeur PARFAIT obtiendrait — la part de
    l'écart qui revient à la quantification, pas au modèle. -> (F1 ±tol, F1 ±½ grille, grille)."""
    import tempfile
    from bridge.transcribe import RawNote, apply_rules, to_musicxml
    raw = [RawNote(onset=n.t, offset=n.t + 0.2, pitch=n.pitch) for n in notes if n.t >= 0]
    figs, rep = apply_rules(raw, bpm, instrument="guitar")
    with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as fh:
        fh.write(to_musicxml(figs, bpm=bpm))
    try:
        est, _, grid_s = read_musicxml(fh.name)
    finally:
        os.unlink(fh.name)
    f = prf(len(match(notes, est, tol)), len(notes), len(est))[2]
    fg = prf(len(match(notes, est, grid_s / 2)), len(notes), len(est))[2]
    return f, fg, grid_s, rep["grille_nom"]


# ══ L'AUTO-VÉRIFICATION ═════════════════════════════════════════════════════════════════════════
def self_test(gp, sync_path, tol):
    warn, ok = [], True
    ref, qpm, dead, anchors, intro, _ = reference_notes(gp, sync_path, warn)
    allref = [n for v in ref.values() for n in v["notes"]]
    tid = max(ref, key=lambda k: len(ref[k]["notes"]))
    notes = ref[tid]["notes"]
    print(f"référence : {len(allref)} notes de guitare, {len(anchors)} ancres de synchro, piste de test {tid}")

    m = match(notes, [Note(n.t, n.pitch) for n in notes], tol)
    f = prf(len(m), len(notes), len(notes))[2]
    ok &= f == 1.0
    print(f"  {'✓' if f == 1.0 else '✗'} la référence contre elle-même : F1 = {f:.3f}")

    shifted = [Note(n.t - 1.3, n.pitch) for n in notes]          # transcription EN AVANCE de 1,3 s
    off, tr = best_alignment(notes, shifted, 5.0, tol, range(-3, 4))
    good = abs(off - 1.3) <= 0.01 and tr == 0
    ok &= good
    print(f"  {'✓' if good else '✗'} décalage de 1,3 s retrouvé : {off:+.3f} s, transposition {tr:+d}")

    up = [Note(n.t + 0.4, n.pitch + 1) for n in notes]           # un demi-ton au-dessus, en retard
    off, tr = best_alignment(notes, up, 5.0, tol, range(-3, 4))
    good = abs(off + 0.4) <= 0.01 and tr == -1
    ok &= good
    print(f"  {'✓' if good else '✗'} demi-ton au-dessus + 0,4 s de retard retrouvés : {off:+.3f} s, transposition {tr:+d}")

    try:
        bpm = 88.0
        f, fg, grid_s, gname = ceiling(notes, bpm, tol)
        print(f"  · plafond des règles à {bpm:g} BPM (grille « {gname} ») : un auditeur PARFAIT "
              f"obtiendrait F1 {f:.2f} à ±{tol * 1000:.0f} ms, {fg:.2f} à ± un demi-pas ({grid_s / 2 * 1000:.0f} ms)")
    except Exception as e:
        print(f"  · plafond des règles non calculé : {type(e).__name__}: {e}")
    for w in warn:
        print("  ⚠ " + w)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("take", nargs="?", help="prise (dossier, nom, uid) ou fichier .musicxml")
    ap.add_argument("--gp", help="partition de référence .gp (défaut : données golem.fm du backing de la prise)")
    ap.add_argument("--sync", help="carte de synchro (défaut : manual_sync.json, sinon songsterr_sync.json)")
    ap.add_argument("--no-sync", action="store_true", help="ignorer la carte : tempo de la partition seul")
    ap.add_argument("--source", help="source transcrite à prendre (ex. Input-1), défaut : la guitare")
    ap.add_argument("--tol", type=float, default=50, help="tolérance d'attaque en ms (défaut 50)")
    ap.add_argument("--sweep", type=float, default=5.0, help="balayage du décalage résiduel, ±s (défaut 5)")
    ap.add_argument("--no-transpose", action="store_true", help="ne pas chercher de transposition")
    ap.add_argument("--self-test", action="store_true", help="vérifier l'outil sur la partition seule")
    a = ap.parse_args()
    tol = a.tol / 1000.0

    if a.self_test:
        slug, gp, sync = _default_paths({})
        gp, sync = a.gp or gp, (None if a.no_sync else (a.sync or sync))
        if not gp:
            sys.exit("✗ pas de partition : --gp")
        sys.exit(0 if self_test(gp, sync, tol) else 1)
    if not a.take:
        ap.error("donne une prise ou un .musicxml (ou --self-test)")

    xml, take_dir, man = resolve_input(a.take, a.source)
    slug, gp, sync = _default_paths(man)
    gp, sync = a.gp or gp, (None if a.no_sync else (a.sync or sync))
    if not gp:
        sys.exit(f"✗ pas de partition pour « {slug} » dans {DATA} : --gp")
    warn = []
    ref, qpm, dead, anchors, intro, sdoc = reference_notes(gp, sync, warn)
    est, bpm, grid_s = read_musicxml(xml)
    if not est:
        sys.exit(f"✗ {xml} ne contient aucune note")
    allref = [n for v in ref.values() for n in v["notes"]]
    off, tr = best_alignment(allref, est, a.sweep, tol, [0] if a.no_transpose else range(-3, 4))
    est = [Note(n.t + off, n.pitch + tr, chord=n.chord) for n in est]

    src = (sdoc.get("_source") or {})
    head = [f"Référence   : ~/{os.path.relpath(gp, os.path.expanduser('~'))} — {len(allref)} notes de guitare "
            f"({', '.join(ref)}), {qpm:g} BPM écrit" + (f", {dead} notes mortes ignorées" if dead else ""),
            ("Synchro     : " + (f"{os.path.basename(sync)} — {len(anchors)} ancres, intro {intro:.2f} s"
                                  + (f" ({src.get('method')}, « {src.get('notes')} »)" if src else "")
                                  if sync and anchors else "AUCUNE carte — tempo de la partition, il dérive")),
            f"Transcription : {os.path.relpath(xml, ROOT)} — {len(est)} notes, {bpm:g} BPM, grille {grid_s * 1000:.0f} ms",
            f"Alignement  : prise = backing depuis 0, décalage résiduel {off:+.2f} s"
            + (" (balayé ±%g s)" % a.sweep)
            + (f", TRANSPOSITION {tr:+d} demi-ton(s) — accordage ou Whammy ?" if tr else ", transposition 0")]
    if abs(off) > a.sweep - 0.05:
        head.append("  ⚠ décalage en BUTÉE du balayage : la prise n'a peut-être pas démarré avec le backing (--sweep)")
    # ⚠ LA FENÊTRE JOUÉE (2026-09-21) : une prise de 2 min 28 comparée aux 5 min de la partition
    # comptait comme « manquées » toutes les notes d'après la fin de la prise — le rappel et le F1
    # étaient sous-estimés de moitié. On ne garde que les notes de référence qui tombent pendant
    # la prise (du début à la dernière note transcrite + 1 s, après alignement).
    t_end = max(n.t for n in est) + 1.0
    n_all = sum(len(v["notes"]) for v in ref.values())
    for v in ref.values():
        v["notes"] = [n for n in v["notes"] if n.t <= t_end]
    n_win = sum(len(v["notes"]) for v in ref.values())
    head.append(f"Fenêtre     : les {t_end:.0f} premières secondes jouées — {n_win} notes de référence sur {n_all}")
    report(ref, est, tol, grid_s, "\n".join(head), bpm=bpm)
    for w in warn:
        print("  ⚠ " + w)


if __name__ == "__main__":
    main()
