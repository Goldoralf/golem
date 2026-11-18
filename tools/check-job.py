#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Essaie UN job de golem.fm sur le rack qui tourne, SANS golem.fm (POST /api/tones-jobs/try).

    tools/check-job.py '{"action": "generate-preview", "preset": "patch:my-patch", "ref": "guitar/crunch"}'
    tools/check-job.py job.json
    tools/check-job.py --list

Le job tourne VRAIMENT, par le même gestionnaire qu'un job venu de golem.fm : un rendu prend le moteur quelques
dizaines de secondes (et le rend), `di-record` enregistre une courte prise. Seuls ses ENVOIS vers golem.fm (clips,
avancement) sont notés au lieu de partir — la sortie les liste. À ne pas lancer pendant que quelqu'un joue
(docs/dev-setup.md). Un job qui télécharge un fichier de golem.fm (`di: {sha}`) demande un rack appairé.

Code de sortie : 0 = le job a rendu son accusé ; 1 = refusé ou en échec (la phrase est affichée)."""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("GOLEM_BASE", "http://localhost:8770")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if argv[0] == "--list":
        raw = '{"action": ""}'
    else:
        raw = open(argv[0], encoding="utf-8").read() if os.path.isfile(argv[0]) else argv[0]
    try:
        job = json.loads(raw)
    except ValueError as e:
        print(f"not JSON: {e}", file=sys.stderr)
        return 2
    req = urllib.request.Request(BASE + "/api/tones-jobs/try", data=json.dumps({"job": job}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        out = json.loads(e.read() or b"{}")
    except OSError as e:
        print(f"bridge unreachable at {BASE}: {e}", file=sys.stderr)
        return 1
    if not out.get("ok"):
        print("REFUSED / FAILED:", out.get("error"))
    else:
        print("ACK:", json.dumps(out.get("ack"), indent=1, ensure_ascii=False))
    for s in out.get("sent") or []:
        print("  would send →", s.get("path"), f"({s['bytes']} bytes)" if s.get("bytes") else json.dumps(s.get("body"), ensure_ascii=False)[:160])
    if out.get("seconds") is not None:
        print(f"{out['seconds']} s")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
