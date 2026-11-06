#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesure la MAIN de la transcription — le choix de la corde et de la case — sur des partitions Guitar Pro.

    ./tools/check-fingering.py                       # corpus de golem.fm, guitares, jeu de TEST
    ./tools/check-fingering.py --split all           # tout le corpus
    ./tools/check-fingering.py --instrument bass     # les basses 4 cordes
    ./tools/check-fingering.py --algo naive          # la ligne de base (bridge/transcribe.naive_fingering)
    ./tools/check-fingering.py --set move=1.5 --set open_high=3   # essayer un réglage sans toucher au code
    ./tools/check-fingering.py --tune                # cherche les poids sur le jeu d'ENTRAÎNEMENT
    ./tools/check-fingering.py --worst 5             # les morceaux les plus mal doigtés

POURQUOI SANS AUDIO (docs/tablature-fingering.md §7, corpus A)
Une partition Guitar Pro donne, pour chaque note, la corde ET la case jouées : c'est la vérité du doigté. On
donne à l'algorithme les HAUTEURS seules, on compare son choix. Ça mesure la main, sans l'oreille ni la grille.

CE QU'IL COMPTE — trois nombres, jamais fusionnés
  · notes exactes   : même corde, même case ;
  · accords exacts  : tout le groupe d'attaques simultanées juste ;
  · position ±2     : la main au bon endroit (case moyenne des notes fretées à 2 cases près) — un doigté
                      « faux » mais jouable au même endroit n'est pas la même erreur qu'un saut de 7 cases.
Plus le PIRE morceau : une moyenne cache le morceau qu'un guitariste trouverait injouable.

LE CORPUS
Les .gp (Guitar Pro 7/8, un zip) sous ~/code/maestrium (GOLEMFM_CODE pour un autre endroit), dédoublonnés par
contenu. Pistes de guitare à 6 cordes (ou de basse à 4 cordes), dans leur PROPRE accordage et capo. Les .gp5
demandent une bibliothèque que le poste n'a pas : ils sont ignorés, et l'outil le dit. Découpe déterministe PAR
MORCEAU (empreinte) : un réglage s'apprend sur certains morceaux et se vérifie sur d'autres.
"""
import argparse
import glob
import hashlib
import itertools
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge import fingering as FG          # noqa: E402
from bridge.transcribe import naive_fingering   # noqa: E402

CODE = os.environ.get("GOLEMFM_CODE", os.path.expanduser("~/code/maestrium"))
CACHE = os.path.join(os.environ.get("TMPDIR", "/tmp"), "golem-fingering-corpus.json")


def _prop(el, name):
    for p in el.iter("Property"):
        if p.get("name") == name:
            return p
    return None


def read_gp(path, instrument):
    """Un .gp -> [piste] ; piste = {name, tuning (grave→aigu), groups: [[(pitch, corde, case), …], …]}.
    Corde au format MusicXML : 1 = la plus AIGUË. Les notes liées (suites) et mortes (x) sont écartées ; une
    note d'ornement compte comme un groupe à part."""
    with zipfile.ZipFile(path) as z:
        r = ET.fromstring(z.read("Content/score.gpif"))
    bars = {b.get("id"): b for b in r.find("Bars")}
    voices = {v.get("id"): v for v in r.find("Voices")}
    beats = {b.get("id"): b for b in r.find("Beats")}
    notes = {n.get("id"): n for n in r.find("Notes")}
    masterbars = list(r.find("MasterBars"))
    order = r.find("MasterTrack").findtext("Tracks").split()
    nstr = 6 if instrument == "guitar" else 4
    out = []
    for ti, t in enumerate(r.find("Tracks")):
        typ = ((t.findtext("InstrumentSet/Type") or "") + " " + (t.findtext("Name") or "")).lower()
        is_bass = "bass" in typ
        if (instrument == "bass") != is_bass or (instrument == "guitar" and "guitar" not in typ):
            continue
        tp = _prop(t, "Tuning")
        tun = [int(x) for x in (tp.findtext("Pitches") or "").split()] if tp is not None else []
        if len(tun) != nstr:
            continue
        cp = _prop(t, "CapoFret")
        capo = int((cp.findtext("Fret") if cp is not None else 0) or 0)
        pos_in_master = order.index(t.get("id")) if t.get("id") in order else ti
        groups = []
        for mb in masterbars:
            bar = bars.get(mb.findtext("Bars").split()[pos_in_master])
            if bar is None:
                continue
            for vid in (bar.findtext("Voices") or "").split():
                if vid == "-1":
                    continue
                for bid in (voices[vid].findtext("Beats") or "").split():
                    g = []
                    for nid in (beats[bid].findtext("Notes") or "").split():
                        n = notes[nid]
                        tie = n.find("Tie")
                        if (tie is not None and tie.get("destination") == "true") or _prop(n, "Muted") is not None:
                            continue
                        s, f = _prop(n, "String"), _prop(n, "Fret")
                        if s is None or f is None:
                            continue
                        si, fr = int(s.findtext("String")), int(f.findtext("Fret"))
                        if not 0 <= si < nstr:
                            continue
                        # la hauteur JOUÉE (capo compris) ; la case notée est relative au capo, comme la vérité
                        g.append((tun[si] + capo + fr, nstr - si, fr))
                    if g:
                        groups.append(sorted(g, key=lambda x: -x[0]))
            # (une voix après l'autre : pour un doigté, l'ordre des groupes d'une même voix est ce qui compte)
        if groups:
            out.append({"name": " ".join((t.findtext("Name") or "").split()), "tuning": [p + capo for p in tun],
                        "capo": capo, "groups": groups})
    return out


def _title(path):
    """Le titre + l'artiste d'un .gp, normalisés — la clé d'un MORCEAU."""
    import re
    with zipfile.ZipFile(path) as z:
        sc = ET.fromstring(z.read("Content/score.gpif")).find("Score")
    t = " ".join((sc.findtext(k) or "") for k in ("Title", "Artist")) if sc is not None else ""
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def corpus(instrument, refresh=False):
    """Toutes les pistes du corpus, en cache (le parcours des zips prend une minute)."""
    cache = CACHE.replace(".json", f"-{instrument}.json")
    if not refresh and os.path.isfile(cache):
        return json.load(open(cache))
    seen = {}
    for p in glob.glob(os.path.join(CODE, "**", "*.gp"), recursive=True):
        if "node_modules" in p:
            continue
        try:
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        except OSError:
            continue
        seen.setdefault(h, p)
    # UN MORCEAU = UNE ENTRÉE : le même titre existe en plusieurs fichiers (catalogue, sauvegarde, synced.gp /
    # source.gp) au contenu à peine différent. Sans ce tri, un morceau tombait à la fois en entraînement et en test
    # — et comptait double. On garde la version la plus fournie.
    by_title = {}
    for h, p in sorted(seen.items()):
        try:
            tracks = read_gp(p, instrument)
            title = _title(p)
        except Exception as e:                      # un fichier illisible n'arrête pas la mesure
            print(f"  ⚠ {os.path.basename(p)} : {type(e).__name__}", file=sys.stderr)
            continue
        if not tracks:
            continue
        n = sum(len(g) for t in tracks for g in t["groups"])
        key = title or h
        if key not in by_title or n > by_title[key][0]:
            by_title[key] = (n, {"id": hashlib.sha256(key.encode()).hexdigest()[:12],
                                 "file": os.path.relpath(p, CODE), "title": title, "tracks": tracks})
    songs = [v for _, v in sorted(by_title.values(), key=lambda x: x[1]["file"])]
    json.dump(songs, open(cache, "w"))
    return songs


def split_of(song):
    """Découpe déterministe par MORCEAU : 1 sur 3 en test."""
    return "test" if int(song["id"], 16) % 3 == 0 else "train"


def score(songs, finger):
    """-> {notes, notes_ok, chords, chords_ok, pos_ok, groups, per_song:[(file, %)]}."""
    tot = {"notes": 0, "notes_ok": 0, "chords": 0, "chords_ok": 0, "pos": 0, "pos_ok": 0, "open": 0, "open_ref": 0}
    per = []
    for s in songs:
        n0, ok0 = tot["notes"], tot["notes_ok"]
        for tr in s["tracks"]:
            truth = tr["groups"]
            guess = finger([[p for p, _, _ in g] for g in truth], tr["tuning"])
            for g, est in zip(truth, guess):
                ref = {p: (st, fr) for p, st, fr in g}
                got = {p: (st, fr) for p, st, fr in est}
                tot["notes"] += len(g)
                tot["notes_ok"] += sum(1 for p in ref if got.get(p) == ref[p])
                tot["open"] += sum(1 for p in got if got[p][1] == 0)
                tot["open_ref"] += sum(1 for p in ref if ref[p][1] == 0)
                if len(g) > 1:
                    tot["chords"] += 1
                    tot["chords_ok"] += int(all(got.get(p) == ref[p] for p in ref))
                fr_ref = [fr for _, fr in ref.values() if fr > 0]
                fr_got = [v[1] for v in got.values() if v[1] and v[1] > 0]
                if fr_ref and fr_got:
                    tot["pos"] += 1
                    tot["pos_ok"] += int(abs(sum(fr_ref) / len(fr_ref) - sum(fr_got) / len(fr_got)) <= 2)
        if tot["notes"] > n0:
            per.append((s["file"], (tot["notes_ok"] - ok0) / (tot["notes"] - n0), tot["notes"] - n0))
    return tot, per


def naive(groups, tuning):
    tun = [(None, None, p) for p in sorted(tuning, reverse=True)]
    return [naive_fingering(g, max_fret=24, tuning=tun) for g in groups]


def shapes(weights):
    def run(groups, tuning):
        return FG.fingering(groups, tuning=tuning, weights=weights)
    return run


def pct(a, b):
    return f"{100 * a / b:5.1f} %" if b else "  —  "


def line(label, tot, per):
    worst = min(per, key=lambda x: x[1]) if per else ("—", 0, 0)
    return (f"{label:<10} notes {pct(tot['notes_ok'], tot['notes'])} · accords {pct(tot['chords_ok'], tot['chords'])}"
            f" · position ±2 {pct(tot['pos_ok'], tot['pos'])} · cordes à vide {pct(tot['open'], tot['notes'])}"
            f" (vérité {pct(tot['open_ref'], tot['notes'])}) · pire morceau {100 * worst[1]:.1f} %")


def octave_case():
    """LE cas du contrat : l'octave que le mainteneur joue 0 7 x 9 x x (mi grave à vide, la case 7, sol case 9)."""
    got = FG.fingering([[40, 52, 64]], tuning=FG.STANDARD["guitar"])[0]
    want = [(64, 3, 9), (52, 5, 7), (40, 6, 0)]
    return got == want, got


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--instrument", choices=("guitar", "bass"), default="guitar")
    ap.add_argument("--split", choices=("test", "train", "all"), default="test")
    ap.add_argument("--algo", choices=("shapes", "naive", "both"), default="both")
    ap.add_argument("--set", action="append", default=[], help="poids=valeur, pour essayer un réglage")
    ap.add_argument("--tune", action="store_true", help="recherche des poids sur le jeu d'entraînement")
    ap.add_argument("--worst", type=int, default=0)
    ap.add_argument("--refresh", action="store_true", help="relire les .gp (sinon le cache)")
    a = ap.parse_args()

    songs = corpus(a.instrument, a.refresh)
    pick = [s for s in songs if a.split == "all" or split_of(s) == a.split]
    n_notes = sum(len(g) for s in pick for t in s["tracks"] for g in t["groups"])
    print(f"corpus {a.instrument} : {len(songs)} morceaux · jeu « {a.split} » : {len(pick)} morceaux, "
          f"{sum(len(s['tracks']) for s in pick)} pistes, {n_notes} notes   (FINGERING_VERSION {FG.FINGERING_VERSION})")
    w = dict(FG.WEIGHTS[a.instrument])
    for kv in a.set:
        k, v = kv.split("=")
        if k not in w:
            sys.exit(f"✗ poids inconnu : {k} (connus : {', '.join(w)})")
        w[k] = float(v)

    if a.tune:
        train = [s for s in songs if split_of(s) == "train"]
        test = [s for s in songs if split_of(s) == "test"]
        best = score(train, shapes(w))[0]
        best_v = best["notes_ok"] / best["notes"]
        print(f"départ (entraînement) : {100 * best_v:.2f} %")
        for _round in range(3):
            for k in list(w):
                for f in (0.0, 0.5, 0.75, 1.5, 2.0):
                    trial = dict(w, **{k: w[k] * f if w[k] else f})
                    t = score(train, shapes(trial))[0]
                    v = t["notes_ok"] / t["notes"]
                    if v > best_v + 1e-4:
                        best_v, w = v, trial
                        print(f"  {k} -> {w[k]:.3g} : {100 * v:.2f} %")
        print("poids retenus :", json.dumps({k: round(v, 3) for k, v in w.items()}))
        pick = test
        print("sur le jeu de TEST :")

    if a.algo in ("naive", "both"):
        tot, per = score(pick, naive)
        print(line("naïf", tot, per))
    if a.algo in ("shapes", "both"):
        tot, per = score(pick, shapes(w))
        print(line("formes", tot, per))
        for f, v, n in sorted(per, key=lambda x: x[1])[:a.worst]:
            print(f"   {100 * v:5.1f} %  ({n} notes)  {f}")
    if a.instrument == "guitar":
        ok, got = octave_case()
        print(("✓" if ok else "✗") + f" l'octave 0 7 x 9 : {got}")


if __name__ == "__main__":
    main()
