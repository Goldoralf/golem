#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sonde vivante du lot 8 (docs/diagnostics.md §6) : fabrique un paquet sur le rack QUI TOURNE, puis
le juge — manifeste, sha256 par fichier, taille, vocabulaire de la chronologie, liste blanche — et
grep-e les PII que le rack connaît DE LUI-MÊME (prénoms de son .band.json, noms de ses presets,
$USER, hostname, jeton golem.fm, adresses LAN). Verdict en dernier.

    ./tools/check-report.py [--kind boot|session|event] [--keep] [--url http://localhost:8770]

Le paquet fabriqué est retiré de l'index à la fin (sauf --keep) : la sonde ne laisse pas de trace
qui partirait au prochain boot. Rien n'est envoyé : POST /api/diag/build ne pousse jamais.
"""
import argparse
import getpass
import hashlib
import io
import json
import os
import re
import socket
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def api(url, path, body=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def pii_known():
    """Ce que CE rack ne doit pas laisser sortir — lu dans ses propres fichiers."""
    out = {}
    try:
        d = json.load(open(os.path.join(ROOT, "config", ".band.json")))
        for p in d.get("people") or []:
            if p.get("name"):
                out[f"prénom {p['name']!r}"] = p["name"]
        for b in [d.get("band")] + list(d.get("bands") or []):
            if isinstance(b, dict) and b.get("name"):
                out[f"groupe {b['name']!r}"] = b["name"]
    except Exception:
        pass
    try:
        t = (json.load(open(os.path.join(ROOT, "config", "integrations.json"))).get("golemfm") or {}).get("token")
        if t and len(t) > 8:
            out["jeton golem.fm"] = t
    except Exception:
        pass
    try:
        import glob
        for f in glob.glob(os.path.join(ROOT, "presets", "*.json")):
            if os.path.basename(f).startswith("."):
                continue
            n = json.load(open(f)).get("name")
            if n and len(n) >= 4:
                out[f"preset {n!r}"] = n
    except Exception:
        pass
    out["$USER"] = getpass.getuser()
    out["hostname"] = socket.gethostname()
    out["home"] = os.path.expanduser("~")
    return {k: v for k, v in out.items() if v and len(v) >= 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="event", choices=("boot", "session", "event"))
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--url", default="http://localhost:8770")
    a = ap.parse_args()
    fails = []

    r = api(a.url, "/api/diag/build", {"kind": a.kind, "detail": "check-report probe"})
    if not r.get("ok"):
        print(f"✗ build : {r}")
        return 2
    path = os.path.join(ROOT, "diag", r["file"])
    data = open(path, "rb").read()
    print(f"paquet   {r['file']}  {len(data)} o  kind={r['kind']}  missing={r.get('missing')}")
    if hashlib.sha256(data).hexdigest() != r["sha256"]:
        fails.append("sha256 de l'index ≠ fichier")
    if len(data) > 4 * 1024 * 1024:
        fails.append("paquet > 4 Mo")

    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    man = json.loads(z.read("golem-report.json"))
    for n, sha in man["files"].items():
        if n not in names:
            fails.append(f"manifeste cite {n} absent du zip")
        elif hashlib.sha256(z.read(n)).hexdigest() != sha:
            fails.append(f"sha256 de {n} ≠ manifeste")
    rep = json.loads(z.read("report.json"))
    from bridge import diag
    bad = diag.violations(rep)
    if bad:
        fails.append(f"liste blanche violée : {bad}")
    tl = [json.loads(x) for x in z.read("timeline.ndjson").decode().splitlines() if x.strip()]
    unknown = sorted({t.get("type") for t in tl if t.get("type") not in diag.EVENTS})
    if unknown:
        fails.append(f"types hors vocabulaire dans la chronologie : {unknown}")
    print(f"contenu  {len(names)} fichiers · sections {[k for k in rep if not k.startswith('_')]}")
    print(f"timeline {len(tl)} événements · logs {[n for n in names if n.startswith('logs/')]}")
    if rep.get("_missing"):
        print(f"sondes absentes : {rep['_missing']}")

    blob = b"".join(z.read(n) for n in names).decode("utf-8", "replace")
    known = pii_known()
    for label, val in known.items():
        if re.search(re.escape(val), blob, re.IGNORECASE):
            fails.append(f"PII : {label} présent dans le paquet")
    for rx, label in ((r"gmt_[A-Za-z0-9_\-]{6,}", "jeton gmt_"), (r"\b192\.168\.\d+\.\d+\b", "IP LAN"),
                      (r"/home/[a-z]", "chemin /home")):
        if re.search(rx, blob):
            fails.append(f"PII : {label} présent dans le paquet")
    print(f"PII      {len(known)} chaînes connues du rack cherchées, {len([f for f in fails if f.startswith('PII')])} trouvées")

    if not a.keep:
        idx_path = os.path.join(ROOT, "diag", "index.json")
        try:
            idx = [x for x in json.load(open(idx_path)) if x.get("report_id") != r["report_id"]]
            json.dump(idx, open(idx_path, "w"), indent=1)
            os.remove(path)
            print("nettoyé  paquet de sonde retiré de l'index (--keep pour le garder)")
        except Exception as e:
            print(f"(nettoyage impossible : {e})")

    if fails:
        print("\n✗ VERDICT : " + " ; ".join(fails))
        return 1
    print("\n✓ VERDICT : paquet propre — manifeste, hachages, liste blanche, vocabulaire, aucune PII connue du rack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
