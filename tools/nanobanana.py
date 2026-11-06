#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Génère des images via Nano Banana (Gemini 2.5 Flash Image) — REST, sans SDK.

Usage :
    python3 tools/nanobanana.py "un ampli Marshall stack, icône plate" out.png
    python3 tools/nanobanana.py --batch jobs.json     # jobs.json = [{"prompt":..,"out":..}, ...]

Clé : GOOGLE_API_KEY dans .env. Modèle : gemini-2.5-flash-image (100 img/jour).
"""
import os, sys, json, base64, time, urllib.request, urllib.error

MODEL = os.environ.get("NB_MODEL", "gemini-2.5-flash-image")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={k}"


def _load_key():
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    env = os.path.join(os.path.dirname(__file__), "..", ".env")
    for line in open(env, encoding="utf-8"):
        line = line.strip()
        if line.startswith("GOOGLE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("GOOGLE_API_KEY introuvable (.env)")


def generate(prompt, out_path, key=None, retries=3):
    key = key or _load_key()
    url = ENDPOINT.format(m=MODEL, k=key)
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            for part in data["candidates"][0]["content"]["parts"]:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline:
                    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                    open(out_path, "wb").write(base64.b64decode(inline["data"]))
                    return out_path
            raise RuntimeError("réponse sans image : " + json.dumps(data)[:400])
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            if e.code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1)); continue
            raise SystemExit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1)); continue
            raise SystemExit(f"réseau: {e}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--batch":
        jobs = json.load(open(args[1]))
        key = _load_key()
        for i, job in enumerate(jobs, 1):
            out = generate(job["prompt"], job["out"], key=key)
            print(f"[{i}/{len(jobs)}] {out}")
        return
    if len(args) < 2:
        raise SystemExit(__doc__)
    print(generate(args[0], args[1]))


if __name__ == "__main__":
    main()
