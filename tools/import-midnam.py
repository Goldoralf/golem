#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Importe des fichiers MIDNAM dans le catalogue de pédales (docs/pedal-registry.md §6).

MIDNAM est le standard MMA « quel programme porte quel nom » — donc le SENS QUI NOUS INTÉRESSE :
ce que le rack envoie à l'appareil. (À ne pas confondre avec les `midi_maps` d'Ardour, qui vont
dans l'autre sens : ce qu'un contrôleur envoie au logiciel. Elles ne servent pas ici.)

    ./tools/import-midnam.py --list                 # ce que le manifeste prévoit d'importer
    ./tools/import-midnam.py --all                  # importe tout le manifeste
    ./tools/import-midnam.py Line_6_EchoPro         # un seul

CE QUE L'IMPORT NE FAIT PAS, et c'est volontaire :
  · il ne pose JAMAIS `verified` — un descripteur importé vaut « quelqu'un l'a écrit quelque
    part » ; seul un rack qui passe la vérification au pied peut le confirmer (contrat §6) ;
  · il n'invente ni familles, ni procédure d'installation, ni contrôles de vérification :
    ces tiers demandent la pédale sous la main. Un fichier importé est une TABLE, pas une recette.
  · il n'écrase jamais un descripteur existant (--force pour forcer) : notre Whammy est calibrée
    au matériel, un import ne doit pas pouvoir la remplacer par une version anonyme.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "library", "pedals")
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midnam-sources.json")
API = "https://api.github.com/repos/Ardour/ardour/contents/share/patchfiles/%s.midnam"

# Un nom de patch qui n'est qu'un numéro n'apprend rien. Attention au piège où je suis tombé :
# l'Eventide Eclipse commence par 89 slots UTILISATEUR (« 00 », « 01 »…) puis liste 347 presets
# d'usine correctement nommés. Juger sur les premières lignes fait rejeter un bon fichier — on
# regarde donc la PROPORTION, et on retire les slots numériques au lieu de tout jeter.
NUMERIC_NAME = re.compile(r"^\s*\d+\s*$")


def fetch(name):
    """Le contenu d'un .midnam : fichier local si le chemin existe, sinon dépôt Ardour (GPL-2)."""
    if os.path.isfile(name):
        return open(name, encoding="utf-8", errors="replace").read()
    with urllib.request.urlopen(API % name, timeout=30) as r:
        return base64.b64decode(json.load(r)["content"]).decode("utf-8", "replace")


def parse(xml):
    """(meta, patches) d'un MIDNAM. `patches` = [(nom, program change)] dans l'ordre du fichier."""
    meta = {
        "manufacturer": (re.search(r"<Manufacturer>([^<]*)", xml) or [None, ""])[1].strip(),
        "model": (re.search(r"<Model>([^<]*)", xml) or [None, ""])[1].strip(),
        "author": (re.search(r"<Author>([^<]*)", xml) or [None, ""])[1].strip(),
    }
    pats = re.findall(r'<Patch\s+[^>]*Name="([^"]*)"[^>]*ProgramChange="(\d+)"', xml)
    if not pats:      # l'ordre des attributs n'est pas garanti par le DTD
        pats = [(n, pc) for pc, n in
                re.findall(r'<Patch\s+[^>]*ProgramChange="(\d+)"[^>]*Name="([^"]*)"', xml)]
    return meta, [(n.strip(), int(pc)) for n, pc in pats]


def pair_bypass(patches):
    """Apparie « X Active » / « X Bypass » quand le fichier encode les deux (cas Whammy DT).

    MIDNAM n'a AUCUNE notion de bypass : c'est une simple liste de programmes. Certains auteurs
    la font quand même apparaître dans les noms — quand c'est le cas on la récupère, sinon les
    modes n'ont pas de PC de bypass et l'UI n'affiche pas le bouton correspondant.
    """
    act, byp = {}, {}
    for name, pc in patches:
        m = re.match(r"^(.*)\s+(Active|Bypass)$", name, re.I)
        if not m:
            return None
        (act if m.group(2).lower() == "active" else byp)[m.group(1).strip()] = pc
    if not act or set(act) != set(byp):
        return None
    return [{"name": k, "family": "custom", "active_pc": act[k], "bypass_pc": byp[k]} for k in act]


def convert(name, xml, note=""):
    meta, patches = parse(xml)
    if not patches:
        raise ValueError("aucun <Patch> — ce MIDNAM ne décrit pas de programmes")
    numeric = [1 for n, _ in patches if NUMERIC_NAME.match(n)]
    named = [(n, pc) for n, pc in patches if not NUMERIC_NAME.match(n)]
    if len(named) < 4:
        raise ValueError(f"{len(numeric)}/{len(patches)} patches n'ont qu'un numéro pour nom — "
                         "rien à importer (les noms d'usine ne sont pas dans le fichier)")
    dropped = len(patches) - len(named)
    modes = pair_bypass(patches) or [
        {"name": n, "family": "custom", "active_pc": pc} for n, pc in named]
    model = meta["model"] or name.replace("_", " ")
    brand = meta["manufacturer"] or ""
    # l'id porte la MARQUE : « echopro » ne dit pas de qui, et deux fabricants peuvent partager
    # un nom de modèle. On évite le doublon quand le modèle la répète déjà.
    full = model if brand and model.lower().startswith(brand.lower()) else f"{brand} {model}".strip()
    slug = re.sub(r"[^a-z0-9]+", "-", full.lower()).strip("-")
    return {
        "id": slug,
        "name": model,
        "kind": "pedal",
        "schema": 1,
        "identity": {
            "brand": meta["manufacturer"] or None,
            "model": model,
            "firmware": None,
            "connection": "din",
            "note": "Importé d'un MIDNAM : la table vient d'un tiers, pas d'une mesure sur "
                    "l'appareil. Vérifie-la au pied avant de t'y fier en concert.",
        },
        "channel": 1,
        "modes": modes,
        "provenance": {
            "source": "imported",
            # JAMAIS `verified` : personne n'a branché cette pédale ici (contrat §6)
            "confidence": "unconfirmed",
            "note": (f"MIDNAM {name}.midnam du dépôt Ardour (GPL-2)"
                     + (f", auteur : {meta['author']}" if meta["author"] else "")
                     + (f", {dropped} slot(s) utilisateur sans nom écartés" if dropped else "")
                     + (f". {note}" if note else "")),
            "upstream": f"Ardour/share/patchfiles/{name}.midnam",
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="noms de MIDNAM (sans .midnam) ou chemins locaux")
    ap.add_argument("--all", action="store_true", help="importe tout le manifeste")
    ap.add_argument("--list", action="store_true", help="affiche le manifeste et sort")
    ap.add_argument("--force", action="store_true", help="écrase un descripteur existant")
    ap.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    a = ap.parse_args()

    man = json.load(open(MANIFEST, encoding="utf-8"))
    if a.list:
        print(f"{man['why']}\n")
        for e in man["import"]:
            print(f"  {e['midnam']:<28} {e['why']}")
        print(f"\nÉCARTÉS ({len(man['rejected'])}) :")
        for e in man["rejected"]:
            print(f"  {e['midnam']:<28} {e['why']}")
        return 0

    names = a.names or ([e["midnam"] for e in man["import"]] if a.all else [])
    if not names:
        ap.error("donne un nom, ou --all, ou --list")
    whys = {e["midnam"]: e.get("why", "") for e in man["import"]}

    os.makedirs(CATALOG, exist_ok=True)
    ok = ko = 0
    for n in names:
        base = os.path.basename(n).replace(".midnam", "")
        try:
            d = convert(base, fetch(n), whys.get(base, ""))
        except Exception as e:
            print(f"  ✗ {base} : {e}")
            ko += 1
            continue
        dst = os.path.join(CATALOG, d["id"] + ".json")
        if os.path.exists(dst) and not a.force:
            print(f"  — {base} : {d['id']}.json existe déjà (--force pour écraser)")
            continue
        if not a.dry_run:
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1, ensure_ascii=False)
        print(f"  ✓ {base} → {d['id']}.json · {len(d['modes'])} modes"
              + (" (avec bypass)" if d["modes"][0].get("bypass_pc") is not None else ""))
        ok += 1
    print(f"\n{ok} importé(s), {ko} refusé(s)" + (" — DRY RUN, rien écrit" if a.dry_run else ""))
    return 0 if not ko else 1


if __name__ == "__main__":
    sys.exit(main())
