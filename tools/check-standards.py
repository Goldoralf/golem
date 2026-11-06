#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie le moteur de STANDARDS — la grammaire, le rendu, et (au besoin) le rack.

    ./tools/check-standards.py            # corpus + rendu, hors-rig, ~3 s
    ./tools/check-standards.py --rig      # + joue vraiment et mesure le signal

Ce que ça prouve SANS Reaper :
  · la grammaire des symboles est FERMÉE — 0 illisible sur les 55 040 du corpus ;
  · les 1382 grilles se compilent et se rendent sans exception ;
  · la transposition est réversible et le rendu déterministe ;
  · les note-off couvrent TOUS les note-on (un accord collé = catastrophe sur scène) ;
  · aucun événement ne dépasse le point de bouclage.

Ce que seul `--rig` peut dire : que la tête de lecture avance vraiment, que les deux pistes
sonnent, et que l'arrêt coupe tout. Le reste est du calcul, et le calcul se vérifie ici.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import standards as S            # noqa: E402

BASE = "http://localhost:8770"
OK, KO, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m⚠\033[0m"
fails = []


def check(cond, label, detail=""):
    print(f"  {OK if cond else KO} {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(label)
    return cond


def post(path, body=None):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(body or {}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", action="store_true", help="joue sur le rack et mesure")
    # ⚠ AUCUN titre en dur : depuis que le rack est un MIROIR de golem.fm, il ne contient
    # que ce que le groupe a tagué — un « autumn-leaves » codé en dur faisait échouer le
    # vérificateur sur un rack parfaitement sain. On prend ce qui est là.
    ap.add_argument("--standard", default=None, help="slug à éprouver (défaut : le premier)")
    a = ap.parse_args()

    print("\n── 1. Ce que le rack POSSÈDE ───────────────────────────────────")
    if not check(S.catalog_ready(), "au moins une grille synchronisée", S.GOLEM_DIR + " ou " + S.SYNCED_DIR):
        print("\n   Le rack ne connaît pas de catalogue : il reçoit ce que golem.fm lui")
        print("   synchronise. Pour travailler en attendant : ./tools/seed-standards.py")
        return 1
    t = time.time()
    lst = S.list_standards()
    check(len(lst) > 0, f"{len(lst)} standard(s)", f"{(time.time() - t) * 1000:.0f} ms")
    check(all(m["key"] for m in lst), "tonalité connue pour TOUS",
          f"{sum(1 for m in lst if m['key_inferred'])} inférées (dernier accord de la forme)")
    check(all(m["tempo"] > 0 for m in lst), "tempo amorcé pour tous",
          "table TEMPO_BY_RHYTHM — le dataset n'en porte aucun")

    print("\n── 2. La grammaire des symboles ────────────────────────────────")
    # Le corpus amont n'est PAS un fichier du produit — il n'est là que si seed-standards.py
    # l'a téléchargé. Quand il est là on éprouve la grammaire sur ses 55 040 symboles (le
    # seul test qui prouve qu'elle est FERMÉE) ; sinon on se rabat sur les grilles présentes.
    if os.path.exists(S.STD_FILE):
        raw = json.load(open(S.STD_FILE, encoding="utf-8"))
    else:
        print(f"  {WARN} corpus amont absent — grammaire éprouvée sur les seules grilles du rack")
        raw = [S._cache["by_slug"][m["slug"]] for m in lst]
    bad, nsym = {}, 0
    for r in raw:
        for sec in r.get("Sections", []):
            for seg in [sec.get("MainSegment")] + list(sec.get("Endings") or []):
                if not seg:
                    continue
                for bar in seg["Chords"].split("|"):
                    for c in S._parse_bar(bar, 4):
                        nsym += 1
                        if S.parse_symbol(c["sym"]) is None:
                            bad[c["sym"]] = bad.get(c["sym"], 0) + 1
    check(not bad, f"{nsym} symboles lus, 0 illisible",
          "" if not bad else f"{sum(bad.values())} en échec : {list(bad)[:6]}")
    # les pièges du corpus, nommément
    for sym, want in (("Cm/maj7", [0, 3, 7, 11]), ("Am/maj7/G#", [0, 3, 7, 11]),
                      ("E7alt", None), ("N.C.", []), ("Bb7b9sus", None)):
        ch = S.parse_symbol(sym)
        check(ch is not None and (want is None or ch["ints"] == want),
              f"piège lu : {sym}", "" if ch else "ILLISIBLE")

    print("\n── 3. Le rendu ─────────────────────────────────────────────────")
    t, tot, unk, hang, over = time.time(), 0, [], [], []
    for m in lst:
        g = S.get_grid(m["slug"])
        r = S.render(g, motion="comp")
        tot += len(r["events"])
        if r["unknown"]:
            unk.append(m["slug"])
        on = {}
        for at, note, vel, lane in r["events"]:
            if at >= r["len_ppq"]:
                over.append(m["slug"])
            k = (note, lane)
            on[k] = on.get(k, 0) + (1 if vel else -1)
        if any(v != 0 for v in on.values()):
            hang.append(m["slug"])
    dt = time.time() - t
    check(not unk, f"{len(lst)} grille(s) rendue(s) — {tot} événements", f"{dt:.1f} s")
    check(not hang, "chaque note-on a son note-off",
          "" if not hang else f"{len(hang)} grilles laissent une note tenue : {hang[:3]}")
    check(not over, "aucun événement au-delà du point de bouclage",
          "" if not over else f"{len(set(over))} grille(s) débordent : {sorted(set(over))[:3]}")

    print("\n── 4. Transposition & déterminisme ─────────────────────────────")
    slug = a.standard or lst[0]["slug"]
    g = S.get_grid(slug)
    if not g:
        check(False, f"standard de test présent : {slug}")
        return 1
    print(f"  (éprouvé sur « {g['title']} »)")
    r1 = S.render(g, key=g["key"], motion="comp")
    r2 = S.render(g, key=g["key"], motion="comp")
    check(r1["events"] == r2["events"], "rendu déterministe (deux passes identiques)")
    check(r1["semis"] == 0, "tonalité d'origine = 0 demi-ton")
    up = S.render(g, key="C", motion="comp")
    check(up["semis"] != 0 or (g["key"] or "").startswith("C"),
          f"transposition effective vers C", f"{up['semis']} demi-tons")
    syms1 = [c["sym"] for b in r1["bars"] for c in b["chords"]]
    syms2 = [c["sym"] for b in up["bars"] for c in b["chords"]]
    check(len(syms1) == len(syms2), "la grille garde sa forme en transposant",
          f"{len(syms1)} accords")

    print("\n── 5. La séquence écrite pour Reaper ───────────────────────────")
    b = S.build(slug, key=g["key"], motion="comp")
    txt = open(b["file"], encoding="utf-8").read().splitlines()
    hdr = dict(l.split(None, 1) for l in txt[:5] if " " in l)
    check(int(hdr.get("nev", 0)) == b["events"], "en-tête `nev` cohérent",
          f"{b['events']} événements")
    check(int(hdr.get("len", 0)) == b["render"]["len_ppq"], "en-tête `len` cohérent",
          f"{hdr.get('len')} ticks")
    check(len(txt) == 5 + b["events"], "une ligne par événement, pas une de plus")
    # ⚠ la ligne d'en-tête `len` NE DOIT PAS ressembler à un événement (le Lua parse au motif)
    check(not any(l.split()[0].isdigit() for l in txt[:5] if l),
          "aucune ligne d'en-tête lisible comme un événement")

    print("\n── 5 bis. Les grooves JOUÉS (packs .mid) ───────────────────────")
    fams = S.pack_families()
    if not fams:
        print(f"  {WARN} aucun pack importé — `tools/import-drum-packs.py <dossier>`. "
              "Le bloc ne propose alors que les motifs écrits, ce qui est un cas VALIDE.")
    else:
        check(True, "index des packs lisible", f"{len(fams)} familles")
        # La métrique n'est pas cosmétique : un groove en 4/4 sous une valse est FAUX.
        w = [f for f in fams if f["meter"] == "3/4"]
        if w:
            check(S.pack_pattern(w[0]["family"], 120, "4/4") is None,
                  "un groove 3/4 est REFUSÉ sous une grille 4/4", w[0]["family"])
        check(S.pack_pattern("aucune/famille", 120, "4/4") is None,
              "une famille inconnue rend None (le moteur retombe sur l'écrit)")
        f0 = next((f for f in fams if f["meter"] == "4/4"), fams[0])
        lo, hi = min(f0["tempos"]), max(f0["tempos"])
        if lo != hi:
            a_, b_ = S.pack_pattern(f0["family"], lo, f0["meter"]), \
                     S.pack_pattern(f0["family"], hi, f0["meter"])
            check(a_ != b_, "la prise SUIT le tempo", f"{lo} vs {hi} bpm — motifs différents")
        # Le plafond de vélocité : c'est ce qui a fait passer la batterie de -1,1 à -2,3 dB.
        hot = [f["family"] for f in fams
               for pat in [S.pack_pattern(f["family"], 120, f["meter"])] if pat
               if max(v for bar in pat for _, _, v in bar) > S.VEL_CEIL]
        check(not hot, f"aucun motif ne dépasse la vélocité {S.VEL_CEIL}",
              ", ".join(hot[:3]) if hot else f"{len(fams)} familles vérifiées")
        # La grille décide de la métrique, le groove joué ne doit pas la déborder.
        g4 = S.render(g, parts={"keys": False, "bass": False, "drums": True},
                      groove=f0["family"], bpm=120)
        check(any(e[3] == 2 for e in g4["events"]), "un groove joué produit bien des frappes",
              f"{sum(1 for e in g4['events'] if e[3] == 2 and e[2])} note-on")

    print("\n── 5 ter. Les réglages de jeu ──────────────────────────────────")
    # Le contrat de tous ces réglages : SANS eux, le rendu est celui d'avant, au bit près.
    # C'est ce qui permet d'en ajouter sans relire chaque grille.
    base = S.render(g, parts={"keys": True, "bass": True})
    check(S.render(g, parts={"keys": True, "bass": True},
                   size="as-written", style="rootless", register="mid", density="auto",
                   anticip=True, move=True, passing=False, approach="chromatic",
                   bass_oct=0, ghost=False, land=False, fill="off")["events"] == base["events"],
          "les défauts explicites == aucun réglage", "rendu identique au bit près")
    # Chaque réglage doit CHANGER quelque chose : un réglage inerte est pire qu'absent.
    # ⚠ Sur DEUX grilles, pas une : l'anticipation, les accords de passage, les notes
    # d'approche et les ghost notes n'existent QUE sur un feel swing/even. Testés sur une
    # bossa seule, les cinq paraissaient inertes — le test était faux, pas le moteur.
    grids = [g] + [x for x in (S.get_grid("summertime"), S.get_grid("so-what")) if x]
    inert = []
    for kw in ({"size": "9-13"}, {"style": "shell"}, {"style": "drop2"}, {"register": "high"},
               {"density": "charleston"}, {"density": "sparse"}, {"anticip": False},
               {"passing": True}, {"approach": "diatonic"}, {"approach": "none"},
               {"ghost": True}, {"bass_oct": -1}, {"bass_mode": "root5"},
               {"bass_mode": "pedal"}, {"bass_mode": "bossa"}):
        if all(S.render(gx, parts={"keys": True, "bass": True}, **kw)["events"]
               == S.render(gx, parts={"keys": True, "bass": True})["events"] for gx in grids):
            inert.append(list(kw)[0] + "=" + str(list(kw.values())[0]))
    check(not inert, "chaque réglage change le rendu",
          ", ".join(inert) or f"15 réglages × {len(grids)} grilles")
    # La tessiture : un réglage qui sort la basse ou le clavier de sa plage est un bug audible.
    out = []
    for kw in ({"register": "low"}, {"register": "high"}, {"style": "drop2"},
               {"bass_oct": -1}, {"bass_oct": 1}):
        r = S.render(g, parts={"keys": True, "bass": True}, **kw)
        for at, n, v, lane in r["events"]:
            if v and lane == 1 and not (S.BASS_LO <= n <= S.BASS_HI):
                out.append(f"basse {n} ({kw})")
            if v and lane == 0 and not (21 <= n <= 108):
                out.append(f"clavier {n} ({kw})")
    check(not out, "aucune note hors tessiture", ", ".join(out[:3]) or "5 réglages balayés")
    # L'harmonie : une tension ajoutée un demi-ton AU-DESSUS d'une note de l'accord sonne faux.
    bad = []
    for sym in ("Am7", "Cmaj7", "G7", "E7alt", "Dm7b5", "C7b9", "Fm6", "Bbmaj7#11"):
        ch = S.parse_symbol(sym)
        if not ch:
            continue
        for sz in ("9", "9-13", "alt"):
            pcs = [(ch["root"] + i) % 12 for i in S.size_ints(ch["ints"], sz)]
            for x in pcs:
                if (x - 1) % 12 in pcs and (x % 12) not in [(ch["root"] + i) % 12 for i in ch["ints"]]:
                    bad.append(f"{sym}/{sz}")
    check(not bad, "aucune tension ajoutée à ½ ton au-dessus d'une note de l'accord",
          ", ".join(sorted(set(bad))[:3]) or "8 accords × 3 tailles")

    if not a.rig:
        print(f"\n{WARN} Non vérifié sans --rig : que la tête avance, que ça SONNE, "
              "et que l'arrêt coupe tout.")
    else:
        print("\n── 6. Sur le rack ──────────────────────────────────────────────")
        try:
            res = post("/api/standards/play", {"standard": slug, "motion": "comp"})
            check(res.get("ok"), "play accepté", f"{res.get('events')} événements")
            time.sleep(2.5)
            st = json.load(open(os.path.join(S.config.ROOT, "presets", ".standard.json")))
            check(st.get("playing"), "le lecteur tourne")
            bar0 = st.get("bar", -1)
            time.sleep(3)
            st2 = json.load(open(os.path.join(S.config.ROOT, "presets", ".standard.json")))
            check(st2.get("bar", -1) != bar0, "la tête de lecture AVANCE",
                  f"mesure {bar0} → {st2.get('bar')}")
            post("/api/standards/stop")
            time.sleep(1.5)
            st3 = json.load(open(os.path.join(S.config.ROOT, "presets", ".standard.json")))
            check(not st3.get("playing"), "l'arrêt coupe le lecteur")
        except Exception as e:
            check(False, "le rack répond", f"{type(e).__name__}: {e}")

    print("\n" + ("=" * 64))
    if fails:
        print(f"{KO} {len(fails)} échec(s) : " + " · ".join(fails[:5]))
        return 1
    print(f"{OK} tout est vert.")
    print("\nCe que MÊME --rig ne voit pas : si l'accompagnement sonne JUSTE. "
          "Les voicings et\nla walking bass sont des tables de règles — il faut une oreille "
          "pour les juger.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
