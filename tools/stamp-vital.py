#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Appose la signature golem.fm sur des presets Vital, en préservant leur provenance.

    ./tools/stamp-vital.py library/synth/vital/user            # aperçu (défaut)
    ./tools/stamp-vital.py library/synth/vital/user --apply    # écrit
    ./tools/stamp-vital.py un.vital deux.vital --apply --author "golem.fm"

Écrit `author` et `comments` dans le `.vital`, et un index `provenance.json` à côté.

── DRY PAR DÉFAUT, CONTRAIREMENT AU RESTE DU RACK ──────────────────────────────────────
Les autres outils de `tools/` écrivent et prennent `--dry` pour s'en abstenir. Celui-ci
RÉÉCRIT DES FICHIERS EN PLACE : l'inverse est plus sûr. Il faut `--apply` pour qu'il touche
quoi que ce soit.

── DEUX PASSES, PAS UNE ────────────────────────────────────────────────────────────────
Vital ne met JAMAIS `author` à jour tout seul : vérifié dans le binaire, `SynthBase::
getAuthor()` n'est lu que par le navigateur de presets et par `LoadSave::stateToJson()`,
qui écrit le fichier. La valeur qui part sur le disque est donc celle du champ Author du
dialogue Save — celle du preset chargé, sauf si tu la retapes.

D'où deux passes :

    ./tools/stamp-vital.py ~/Téléchargements --index-only --apply   # AVANT Vital
    …modding à la main, sauvegardes depuis Vital…
    ./tools/stamp-vital.py library/synth/vital/user --apply         # APRÈS

La première relève l'auteur d'origine dans `provenance.json` sans toucher aux fichiers.
Elle n'est facultative que si tu ne touches pas au champ Author dans Vital : dès l'instant
où tu y tapes « golem.fm » toi-même, l'auteur d'origine n'existe plus nulle part et RIEN ne
peut le reconstruire. Le plus simple reste de laisser ce champ tranquille et de laisser
l'outil faire l'échange — mais si tu l'as retapé, la passe finale va rechercher le crédit
dans l'index.

── ON RÉÉCRIT 187 OCTETS, PAS 405 Ko ───────────────────────────────────────────────────
Un `.vital` est du JSON compact à clés triées : les métadonnées forment une tête d'environ
187 octets, tout le reste est `settings` + `synth_version`. On coupe à `,"settings":{`, on
re-sérialise la tête (que des chaînes) et on recolle la queue OCTET POUR OCTET.

Pourquoi pas un simple json.load/dump ? Parce que Vital écrit ses flottants avec un autre
formateur que Python : sur BS_Cyberpunk_Spoiler, un aller-retour naïf réécrit
`13.800003051757813` en `...812`. La VALEUR est identique (même double, vérifié), mais le
texte change — et avec lui le hash des `settings`, qui est notre clé d'identité de patch.
Un caractère sur 405 081 suffit à la faire bouger. On ne touche donc pas à la queue.

── LA PROVENANCE, ON LA GARDE ──────────────────────────────────────────────────────────
Même ligne que le bloc `source` des grilles (docs/standards-format.md §6) : on n'efface pas
l'auteur d'origine, on le déplace dans `comments`. Un preset qu'on a modifié reste un
dérivé, et l'écrire coûte zéro.

`comments` devient  ->  "D'après <auteur d'origine>. https://golem.fm"
                        "https://golem.fm"            (si le preset n'avait pas d'auteur,
                                                       ou s'il était déjà à nous)

L'index `provenance.json` écrit à côté est la trace DURABLE : lui survit aux re-sauvegardes
depuis Vital, qui écrasent les champs du fichier. C'est là qu'on retrouve d'où vient quoi le
jour où quelqu'un le demande.

⚠ CE QU'IL NE TOUCHE PAS : les `author` des wavetables, à l'intérieur de `settings`. Ils
créditent Matt Tytel ou unfa pour des tables qu'on n'a pas faites ; les réécrire serait faux,
et ce champ est par ailleurs le seul signal fiable pour vérifier qu'une table est bien du
contenu factory. Si un jour tu dessines tes propres tables, ça se rediscutera — pas avant.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

DEFAULT_AUTHOR = "golem.fm"
DEFAULT_URL = "https://golem.fm"
SPLIT = ',"settings":{'


def split_head(raw):
    """Coupe le fichier en (métadonnées: dict, queue: str intouchée).

    On cherche la PREMIÈRE occurrence de `,"settings":{` qui donne une tête valide — un
    champ `comments` contenant littéralement cette chaîne ne nous piégerait pas.
    """
    start = 0
    while True:
        i = raw.find(SPLIT, start)
        if i < 0:
            raise ValueError("pas de clé `settings` de premier niveau")
        try:
            head = json.loads(raw[:i] + "}")
        except json.JSONDecodeError:
            start = i + 1
            continue
        if "settings" in head:          # on a coupé trop loin
            start = i + 1
            continue
        return head, raw[i:]


CREDIT = re.compile(r"^(D'après .+?\.)\s*")


def stamp(path, author, url, credit=True, force=False, origins=None):
    """Retourne (nouveau texte, avant, après, meta) sans rien écrire.

    meta vaut None quand il n'y a rien à faire.

    `origins` est le {fichier: auteur d'origine} lu dans provenance.json. Il sert quand le
    fichier porte DÉJÀ notre nom — typiquement parce qu'on a tapé « golem.fm » dans le champ
    Author de Vital : l'auteur d'origine n'est plus dans le fichier, mais l'index l'a gardé,
    et on peut encore reconstruire la ligne de crédit à partir de lui.
    """
    raw = open(path, encoding="utf-8").read()
    head, tail = split_head(raw)
    before = (head.get("author") or "").strip()
    old_comments = (head.get("comments") or "").strip()
    ours = before == author

    # « Rien à faire » = notre nom ET notre URL déjà en place. Un fichier à notre nom mais
    # sans URL (Vital est passé par là) doit encore être complété.
    if ours and url in old_comments and not force:
        return None, before, author, None

    if ours:
        # On ne reconstruit JAMAIS le crédit depuis `before` : il vaut déjà « golem.fm ».
        # Ordre : le crédit encore présent dans comments, sinon celui gardé par l'index.
        m = CREDIT.match(old_comments)
        origin = m.group(1)[len("D'après "):-1] if m else (origins or {}).get(
            os.path.basename(path))
        comments = f"D'après {origin}. {url}" if (credit and origin) else url
    elif credit and before:
        comments = f"D'après {before}. {url}"
    else:
        comments = url

    if ours and old_comments == comments:
        return None, before, author, None

    head["author"] = author
    head["comments"] = comments
    new = json.dumps(head, separators=(",", ":"), sort_keys=True,
                     ensure_ascii=False)[:-1] + tail   # [:-1] retire l'accolade fermante

    # garde-fou : la queue doit être rigoureusement intacte
    assert new.endswith(tail), "la queue a bougé — on n'écrit pas"

    meta = {
        "file": os.path.basename(path),
        "preset_name": head.get("preset_name"),
        "author_before": before or None,
        "author_after": author,
        "settings_md5": hashlib.md5(tail.encode()).hexdigest(),
        "stamped": datetime.date.today().isoformat(),
    }
    return new, before, author, meta


def probe(path, author):
    """Relève la provenance du fichier TEL QU'IL EST, sans rien réécrire.

    C'est le mode à passer sur le dossier de téléchargement, avant toute session Vital :
    une fois que tu as tapé « golem.fm » dans le champ Author du dialogue Save, l'auteur
    d'origine n'existe plus nulle part et rien ne peut le reconstruire.
    """
    raw = open(path, encoding="utf-8").read()
    head, tail = split_head(raw)
    before = (head.get("author") or "").strip()
    return {
        "file": os.path.basename(path),
        "preset_name": head.get("preset_name"),
        "author_before": before or None,
        "author_after": author,
        "settings_md5": hashlib.md5(tail.encode()).hexdigest(),
        "stamped": datetime.date.today().isoformat(),
    }


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                out += [os.path.join(root, f) for f in sorted(files)
                        if f.lower().endswith(".vital")]
        elif p.lower().endswith(".vital"):
            out.append(p)
        else:
            print(f"  ignoré (pas un .vital) : {p}", file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="fichiers .vital ou dossiers à parcourir")
    ap.add_argument("--author", default=DEFAULT_AUTHOR)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--no-credit", action="store_true",
                    help="n'inscrit pas « D'après <auteur> » dans comments")
    ap.add_argument("--index-only", action="store_true",
                    help="relève la provenance dans provenance.json SANS toucher aux .vital "
                         "(à passer sur le dossier de téléchargement, avant Vital)")
    ap.add_argument("--force", action="store_true",
                    help="re-signe un preset déjà signé (met l'URL à jour, garde le crédit)")
    ap.add_argument("--apply", action="store_true", help="écrit (sinon : aperçu seul)")
    a = ap.parse_args()

    files = collect(a.paths)
    if not files:
        print("aucun .vital trouvé")
        return 1

    # L'index existant sert de mémoire : il porte l'auteur d'origine des fichiers dont
    # Vital a depuis écrasé le champ `author`.
    root = a.paths[0] if os.path.isdir(a.paths[0]) else os.path.dirname(files[0]) or "."
    idx_path = os.path.join(root, "provenance.json")
    doc = {"v": 1, "presets": []}
    if os.path.exists(idx_path):
        try:
            doc = json.load(open(idx_path, encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    origins = {p["file"]: p["author_before"] for p in doc.get("presets", [])
               if p.get("author_before") and p["author_before"] != a.author}

    index, written, skipped = [], 0, 0
    print(f"{'fichier':38}{'auteur avant':22}→ après")
    print("-" * 78)
    for f in files:
        try:
            if a.index_only:
                meta = probe(f, a.author)
                new, before, after = None, meta["author_before"] or "", "(relevé)"
            else:
                new, before, after, meta = stamp(f, a.author, a.url,
                                                 credit=not a.no_credit, force=a.force,
                                                 origins=origins)
        except Exception as e:                       # un .vital illisible ne stoppe pas le lot
            print(f"{os.path.basename(f)[:36]:38}⚠ {e}")
            skipped += 1
            continue
        if meta is None:
            print(f"{os.path.basename(f)[:36]:38}{before[:20]:22}— déjà signé")
            skipped += 1
            continue
        print(f"{os.path.basename(f)[:36]:38}{(before or '—')[:20]:22}→ {after}")
        index.append(meta)
        if a.apply and new is not None:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
            written += 1

    if not a.apply:
        verbe = "à relever" if a.index_only else "à signer"
        print(f"\n  {len(index)} {verbe}, {skipped} ignoré(s) — (aperçu, rien écrit ; "
              f"ajoute --apply)")
        return 0

    # l'index vit à côté des presets et se cumule d'une passe à l'autre
    known = {p["file"]: i for i, p in enumerate(doc.get("presets", []))}
    for m in index:
        if m["file"] in known:
            prev = doc["presets"][known[m["file"]]]
            # Une re-signature (--force) relit `golem.fm` comme auteur « avant », puisque le
            # fichier porte déjà notre nom. On ne laisse pas ça écraser l'auteur d'origine
            # déjà consigné : l'index est la trace durable, il ne se dégrade pas.
            if m["author_before"] in (None, a.author) and prev.get("author_before"):
                m["author_before"] = prev["author_before"]
            doc["presets"][known[m["file"]]] = m
        else:
            doc["presets"].append(m)
    doc["presets"].sort(key=lambda p: p["file"])
    doc["_note"] = ("Provenance des presets Vital republiés sur golem.fm. Écrit par "
                    "tools/stamp-vital.py. Les champs du .vital sont écrasés à chaque "
                    "sauvegarde depuis Vital — cet index, lui, reste.")
    with open(idx_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)

    if a.index_only:
        print(f"\n  {len(index)} relevé(s) — aucun .vital modifié")
    else:
        print(f"\n  {written} signé(s), {skipped} ignoré(s)")
    print(f"  index -> {idx_path} ({len(doc['presets'])} presets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
