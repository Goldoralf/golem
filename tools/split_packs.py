#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Éclate les packs MULTI-AMPLIS du catalogue en entrées à part entière (une par ampli).

Table CURATÉE À LA MAIN (le mapping modèle→ampli passe par les noms de capture : « Messy Double
Recto » = Mesa Dual Rectifier…) — on n'éclate QUE quand le mapping est sans ambiguïté. Le pack
parent RESTE dans le catalogue (badge PACK) ; les entrées dérivées portent `parent` et un id
"<parent>-<slug>" (résolu normalement par bridge/resolver : mêmes fichiers .nam).

IDEMPOTENT : purge les dérivées existantes puis les recrée. À lancer APRÈS tools/classify.py
(pipeline : build-library → classify → split_packs). 67139 (Headbangers Ball) N'EST PAS éclaté :
surnoms (« CHUG NORRIS »…) impossibles à mapper sûrement sur un ampli.

Usage : .venv/bin/python tools/split_packs.py
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "library", "catalog", "tones-index.json")

# parent id -> [ (suffixe, nom d'ampli, marque, préfixe(s) de nom de modèle) ]
SPLITS = {
    1868: [   # Extreme Metal Pack
        ("recto",   "Mesa Boogie Dual Rectifier",          "Mesa/Boogie", ("Messy Double Recto",)),
        ("vh4",     "Diezel VH4",                          "Diezel",      ("VH4_",)),
        ("orange",  "Orange Rockerverb",                   "Orange",      ("Orange Julius",)),
        ("jcm800",  "Marshall JCM800",                     "Marshall",    ("Marsh 800",)),
    ],
    28241: [  # Metal Guitar (MIX READY) — 1 modèle = 1 ampli, nommés par la capture
        ("herbert", "Diezel Herbert",                      "Diezel",      ("HELLBERT",)),
        ("savage",  "ENGL Savage",                         "ENGL",        ("ENGL SAVAGE",)),
        ("xxx",     "Peavey Triple XXX",                   "Peavey",      ("TRIPLE XXX",)),
        ("satan",   "Randall Satan",                       "Randall",     ("SLAUGHTER",)),
        ("stealth", "EVH 5150 III Stealth",                "EVH",         ("STEALTH",)),
        ("vh4",     "Diezel VH4",                          "Diezel",      ("FAT VH4",)),
        ("revf",    "Mesa Boogie Dual Rectifier Rev F",    "Mesa/Boogie", ("REV F",)),
        ("hm2",     "Boss HM-2 (chainsaw)",                "Boss",        ("CHAINSAW",)),
    ],
}


def main():
    d = json.load(open(INDEX))
    tones = [t for t in d["tones"] if not t.get("parent")]        # purge des dérivées (idempotent)
    by_id = {t["id"]: t for t in tones}
    added = 0
    for pid, parts in SPLITS.items():
        parent = by_id.get(pid)
        if not parent:
            print(f"⚠ parent {pid} absent du catalogue — ignoré"); continue
        for suffix, amp, brand, prefixes in parts:
            models = [m for m in parent.get("models", [])
                      if any((m.get("name") or "").strip().upper().startswith(p.upper()) for p in prefixes)]
            if not models:
                print(f"⚠ {pid}-{suffix} : aucun modèle ne matche {prefixes} — ignoré"); continue
            tones.append({
                "id": f"{pid}-{suffix}", "parent": pid,
                "title": f"{parent.get('title', '')} — {amp}",
                "amp": amp, "brand": brand, "gear": parent.get("gear", "amp"),
                "style": parent.get("style"), "tags": parent.get("tags", []),
                "models": models, "url": parent.get("url"),
                "downloads": parent.get("downloads", 0), "favorites": parent.get("favorites", 0),
                "pack": False,
            })
            added += 1
            print(f"  ✓ {pid}-{suffix:8s} {amp:38s} {len(models)} modèle(s)")
    d["tones"] = tones
    json.dump(d, open(INDEX, "w"), ensure_ascii=False, indent=2)
    print(f"écrit : {added} entrées dérivées ({len(tones)} tones au total)")


if __name__ == "__main__":
    main()
