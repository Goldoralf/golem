#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Importe une SÉLECTION d'un pack de grooves MIDI (Toontrack & compatibles) vers le rack.

    ./tools/import-drum-packs.py ~/code/maestrium/data/drum-midi-files
    ./tools/import-drum-packs.py <dossier> --dry     # montre sans écrire

Écrit `library/grooves/packs/<pack>/<kit>/<feel>/<bpm>.mid` + un index `packs.json` que le
bloc Standard interroge par FAMILLE et par TEMPO (`groove: "jazz/walk/sticks"`).

── POURQUOI UNE SÉLECTION ET PAS TOUT ──────────────────────────────────────────────────
Le pack fait 6779 fichiers. En importer 6779 referait l'erreur des 1382 grilles : une
bibliothèque que personne ne parcourt. On garde UN fichier par (kit, feel, tempo) — le pack
jazz en offre 9 tempos de 70 à 220, ce qui permet au groove de SUIVRE le tempo du preset
au lieu d'être étiré. C'est ce que fait un batteur.

Le fichier retenu est celui dont la densité est MÉDIANE : ni la variation la plus creuse,
ni la plus chargée.

── LE REMAP SE DÉRIVE, IL NE S'INVENTE PAS ─────────────────────────────────────────────
Les packs déclarent leur mapping dans un fichier `kitpieces` (famille -> notes). Mesuré sur
400 fichiers : 87,4 % des frappes sont déjà dans la plage General MIDI 35-59, et les 12,6 %
restants sont presque tous des ARTICULATIONS DE CHARLEY (notes 21, 22, 23, 25, 26, 60, 62).
On lit donc `kitpieces` et on ramène chaque note hors-GM sur la note GM de sa famille.

⚠ DROITS : ces packs sont des produits COMMERCIAUX. Sur le rack, c'est l'usage prévu. Ils ne
se redistribuent pas — `library/grooves/` est gitignoré, et rien ici ne remonte vers
golem.fm. Même ligne que pour les grilles (docs/standards-format.md §6).
"""
import argparse
import json
import os
import re
import shutil
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import config as C          # noqa: E402
from bridge import grooves as G         # noqa: E402

DEST = os.path.join(C.ROOT, "library", "grooves", "packs")
INDEX = os.path.join(C.ROOT, "library", "grooves", "packs.json")

# note GM de destination, par famille déclarée dans `kitpieces`
GM_OF_FAMILY = {"Kick": 36, "Snare": 38, "Hi-Hat": 42, "Ride Cymbals": 51,
                "Crash Cymbals": 49, "Toms": 45, "Percussion": 54}
GM_KEEP = set(range(35, 60))            # le cœur GM : on n'y touche pas

# Nos noms de feel <- dossiers du pack, APRÈS normalisation (§norm_feel). Ce qui n'est pas
# listé passe sous son nom normalisé — on n'invente pas de vocabulaire.
FEEL_ALIAS = {"walk": "walk", "2 beat": "two", "shuffle": "shuffle",
              "3 four": "waltz", "3 four walk": "waltz",   # les deux sont du 3/4 jazz
              "5 four": "five", "ballad": "ballad", "bop": "bop"}
# Le jazz garde le temps SUR LA RIDE. Sans ça, la sélection « densité médiane » tombe une
# fois sur deux sur une variation au charleston : mesuré sur « Walk Sticks @140 », les 34
# fichiers du dossier portent 145 frappes de ride, et le fichier retenu n'en avait AUCUNE.
# Ce n'est pas un goût, c'est l'idiome — donc une règle par pack, pas un réglage.
PREFER_NOTE = {"jazz": 51}                # 51 = ride GM

# sections des packs blues : celles qui BOUCLENT sous une grille sont le groove…
BLUES_SECTIONS = ("VERSE", "CHORUS")
# …et celles-ci sont des FINS DE PHRASE — une mesure qui remplace la dernière d'une section.
# Elles ne bouclent pas, donc elles vivent dans un index séparé (`fills`) et ne peuvent pas
# être choisies comme groove par erreur.
FILL_SECTIONS = ("FILL_VARIATIONS", "BREAK", "DRUM_BREAK", "TURNAROUND", "TWO_FOUR_FILL")


def norm_feel(name):
    """« 3 Four Sticks 2 » -> « 3 four ». Le kit et le numéro de variante sortent du NOM.

    Le premier jet ne retirait « Sticks » qu'en FIN de chaîne : on obtenait des familles
    « 3-four-sticks-2 » et « 3-four-walk », donc des alias qui ne matchaient jamais.
    """
    n = re.sub(r"\[.*?\]", " ", name)               # « 3 Four Sticks [2] » : variante entre crochets
    n = re.sub(r"\b(sticks?|brushes)\b", " ", n, flags=re.I)
    n = re.sub(r"\s+\d+\s*$", " ", n)             # numéro de variante en fin
    return re.sub(r"\s+", " ", n).strip().lower()


def read_kitpieces(path):
    """{note: note_GM} dérivé du fichier livré avec le pack. {} s'il est absent."""
    try:
        s = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    remap, fam = {}, None
    for line in s.splitlines():
        m = re.match(r'\s*name "(.+)"', line)
        if m:
            fam = m.group(1)
            continue
        m2 = re.match(r"\s*note (\d+)", line)
        if m2 and fam:
            n = int(m2.group(1))
            gm = GM_OF_FAMILY.get(fam)
            if gm and n not in GM_KEEP:          # hors GM -> la note GM de sa famille
                remap[n] = gm
    return remap


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="dossier du pack (contient <PACK>/<kit>/<bpm>/<feel>/*.mid)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    packs = [d for d in sorted(os.listdir(a.src)) if os.path.isdir(os.path.join(a.src, d))]
    index, kept, skipped, remaps, pool, fpool = {}, 0, [], {}, {}, {}
    fidx = {}

    for pack in packs:
        proot = os.path.join(a.src, pack)
        pname = slug(pack.split("@")[-1].replace("REAL_", ""))
        remap = read_kitpieces(os.path.join(proot, "kitpieces"))
        remaps[pname] = {str(k): v for k, v in remap.items()}
        print(f"\n── {pack}  ->  {pname}   ({len(remap)} note(s) à remapper)")

        for kit in sorted(os.listdir(proot)):
            kdir = os.path.join(proot, kit)
            if not os.path.isdir(kdir):
                continue
            # arborescence attendue : <kit>/<NNN BPM>/<feel>/*.mid
            bpms = [d for d in sorted(os.listdir(kdir)) if re.match(r"^\d+\s*BPM$", d)]
            if not bpms:
                # Arborescence « style » (packs blues) : <style>/<bpm>-Sxxx@SECTION/*.mid.
                # On ne garde que les sections qui BOUCLENT (couplet/refrain) : un INTRO ou
                # un SOLO sous une grille de 32 mesures n'a pas de sens.
                style = slug(kit.split("@")[-1])
                best, fills = {}, {}
                for sub in sorted(os.listdir(kdir)):
                    m = re.match(r"^(\d+)-\S*@(\w+)$", sub)
                    if not m:
                        continue
                    sect = m.group(2).upper()
                    is_fill = sect in FILL_SECTIONS
                    if not is_fill and sect not in BLUES_SECTIONS:
                        continue
                    sbpm = int(m.group(1))
                    for f in sorted(os.listdir(os.path.join(kdir, sub))):
                        if not f.lower().endswith(".mid"):
                            continue
                        d = G.read_smf(os.path.join(kdir, sub, f))
                        if not d:
                            continue
                        # Un fill remplace UNE mesure (deux au plus). Les dossiers marqués
                        # TURNAROUND contiennent parfois un chorus entier de 12 mesures :
                        # ce n'est pas un fill, ça écraserait la moitié d'une section.
                        if is_fill and (d["bars"] or 1) > 2:
                            continue
                        (fills if is_fill else best).setdefault(sbpm, []).append(
                            (len(d["events"]), os.path.join(kdir, sub, f), d))
                # ⚠ le fill se collecte MÊME si le dossier n'a pas de couplet : les deux
                # index sont indépendants. Sortir ici jetait 60 des 65 dossiers de fills.
                if not best and not fills:
                    skipped.append(f"{pname}/{style}")
                    continue
                for sbpm, cand in sorted(best.items()):
                    pool.setdefault((f"{pname}/{style}", pname, style, None, sbpm),
                                    []).extend(cand)
                for sbpm, cand in sorted(fills.items()):
                    fpool.setdefault((f"{pname}/{style}", pname, style, sbpm),
                                     []).extend(cand)
                continue
            for bd in bpms:
                bpm = int(bd.split()[0])
                for feel in sorted(os.listdir(os.path.join(kdir, bd))):
                    fdir = os.path.join(kdir, bd, feel)
                    if not os.path.isdir(fdir):
                        continue
                    mids = [os.path.join(fdir, f) for f in sorted(os.listdir(fdir))
                            if f.lower().endswith(".mid")]
                    cand = []
                    for m in mids:
                        d = G.read_smf(m)
                        if d:
                            cand.append((len(d["events"]), m, d))
                    if not cand:
                        continue
                    key = norm_feel(feel)
                    fk = FEEL_ALIAS.get(key, slug(key))
                    pool.setdefault((f"{pname}/{fk}/{slug(kit)}",
                                     pname, slug(kit), fk, bpm), []).extend(cand)

    # ── sélection : UN fichier par (famille, tempo), densité médiane ──
    for (fam, pname, kit, fk, bpm), cand in sorted(pool.items()):
        want = PREFER_NOTE.get(pname)
        if want:
            ride = [c for c in cand if any(n == want for _, n, _ in c[2]["events"])]
            if ride:
                cand = ride
        cand.sort()
        _, src, d = cand[len(cand) // 2]
        out = (os.path.join(DEST, pname, kit, fk, f"{bpm}.mid") if fk
               else os.path.join(DEST, pname, kit, f"{bpm}.mid"))
        if not a.dry:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
        index.setdefault(fam, []).append({
            "bpm": bpm, "file": os.path.relpath(out, C.ROOT), "bars": d["bars"],
            "meter": f"{d['num']}/{d['den']}", "hits": len(d["events"]),
            "of": len(cand)})
        kept += 1
    # ── les fills : même sélection, index séparé ──
    for (fam, pname, style, bpm), cand in sorted(fpool.items()):
        cand.sort()
        _, src, d = cand[len(cand) // 2]
        out = os.path.join(DEST, pname, style, "fills", f"{bpm}.mid")
        if not a.dry:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
        fidx.setdefault(fam, []).append({
            "bpm": bpm, "file": os.path.relpath(out, C.ROOT), "bars": d["bars"],
            "meter": f"{d['num']}/{d['den']}", "hits": len(d["events"]), "of": len(cand)})
    for fam in fidx:
        fidx[fam].sort(key=lambda x: x["bpm"])
    for fam in index:
        index[fam].sort(key=lambda x: x["bpm"])
    doc = {"v": 2, "remap": remaps,
           "families": index, "fills": fidx,
           "_note": "Sélection importée par tools/import-drum-packs.py — packs COMMERCIAUX, "
                    "usage local seulement, jamais redistribués (library/grooves/ est gitignoré)."}
    print(f"\n  {kept} motif(s) retenus · {len(index)} familles · "
          f"{sum(len(v) for v in fidx.values())} fill(s) dans {len(fidx)} familles")
    for fam, lst in sorted(index.items()):
        print(f"   {fam:26} {len(lst):2} tempos : {[x['bpm'] for x in lst]}")
    if skipped:   # on NOMME ce qu'on laisse : un compteur laisse croire que tout est couvert
        print(f"\n  ignorés ({len(skipped)}, aucune section VERSE/CHORUS) : {', '.join(skipped)}")
    if a.dry:
        print("\n  (--dry : rien écrit)")
        return 0
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"\n  index -> {os.path.relpath(INDEX, C.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
