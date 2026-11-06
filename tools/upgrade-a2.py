#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Backfill A2 de la librairie — Phase 2 de docs/archive/nam-a2-migration.md.

Pour chaque tone TONE3000 du catalogue (format nam), récupère les re-entraînements
A2 (?architecture=2 — mêmes noms de modèles, ids distincts), matche PAR NOM les
modèles installés et télécharge les jumeaux A2 CÔTE À CÔTE (suffixe -a2.nam, même
dossier). Les A2 sont AJOUTÉS en fin de entry.models : models[0] (le défaut
historique que résolvent les presets existants) ne bouge pas — la bascule d'un
preset reste un choix explicite (b["model"]).

Idempotent : re-run = skip des fichiers présents et des modèles déjà au catalogue.
  ./tools/upgrade-a2.py [--dry-run]
"""
import json, os, sys, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import t3k
import importlib.util
spec = importlib.util.spec_from_file_location("blib", os.path.join(HERE, "build-library.py"))
blib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blib)

INDEX = os.path.join(ROOT, "library", "catalog", "tones-index.json")


def _norm(name):
    return " ".join((name or "").split()).casefold()


def _save(cat):
    tmp = INDEX + ".tmp"
    json.dump(cat, open(tmp, "w"), indent=1)
    os.replace(tmp, INDEX)


def main():
    dry = "--dry-run" in sys.argv
    cat = json.load(open(INDEX))
    tones = cat.get("tones", [])
    n_dl = n_skip = 0
    no_a2, mismatches, errors = [], [], []

    for ti, t in enumerate(tones):
        if t.get("format") == "ir":
            continue
        models = t.get("models") or []
        base = [m for m in models if str(m.get("arch")) != "2"]
        if not base:
            continue
        have_ids = {str(m.get("id")) for m in models}
        have_names_a2 = {_norm(m.get("name")) for m in models if str(m.get("arch")) == "2"}
        want = [m for m in base if _norm(m.get("name")) not in have_names_a2]
        if not want:
            continue

        label = f"[{ti + 1}/{len(tones)}] {t.get('amp') or t.get('title')} (#{t['id']})"
        st, res = t3k.api_get(f"/api/v1/models?tone_id={t['id']}&architecture=2")
        if st != 200:
            errors.append(f"{label}: models A2 -> {st}")
            print(f"✗ {label}: API {st}", flush=True)
            continue
        a2 = [m for m in (res.get("data", res if isinstance(res, list) else []) or []) if m.get("model_url")]
        if not a2:
            no_a2.append(label)
            print(f"— {label}: pas de version A2", flush=True)
            continue
        by_name = {_norm(m.get("name")): m for m in a2}

        added = []
        for m in want:
            hit = by_name.get(_norm(m.get("name")))
            if not hit:
                mismatches.append(f"{label}: « {m.get('name')} » sans jumeau A2")
                continue
            if str(hit.get("id")) in have_ids:
                continue
            ext = os.path.splitext(urllib.parse.urlparse(hit["model_url"]).path)[1] or ".nam"
            rel = os.path.join(os.path.dirname(m.get("file") or ""),
                               blib.slugify(hit.get("name") or "model") + "-a2" + ext)
            if dry:
                print(f"  DRY {rel}", flush=True)
                continue
            r = blib.download(hit["model_url"], os.path.join(ROOT, rel))
            if str(r).startswith("err"):
                errors.append(f"{label}: download {os.path.basename(rel)} -> {r}")
                continue
            n_dl += 1 if r == "ok" else 0
            n_skip += 1 if r == "skip" else 0
            added.append({"id": hit.get("id"), "name": hit.get("name"), "file": rel,
                          "size": hit.get("size"), "arch": "2"})
            have_ids.add(str(hit.get("id")))
        if added:
            models.extend(added)           # EN FIN de liste : models[0] inchangé
            _save(cat)                     # reprise gratuite si interruption
            print(f"✓ {label}: +{len(added)} A2", flush=True)

    print("\n=== RÉSUMÉ ===")
    print(f"téléchargés: {n_dl} · déjà sur disque: {n_skip}")
    print(f"tones sans A2 ({len(no_a2)}):")
    for x in no_a2:
        print("  ", x)
    if mismatches:
        print(f"modèles sans jumeau A2 ({len(mismatches)}):")
        for x in mismatches:
            print("  ", x)
    if errors:
        print(f"ERREURS ({len(errors)}):")
        for x in errors:
            print("  ", x)


if __name__ == "__main__":
    main()
