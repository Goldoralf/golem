#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Les images de la chanson d'usine « Golem Rising » (docs/factory.md §5) : pochette et photo du groupe, faites par
Nano Banana Pro (Gemini, même appel que les outils de golem.fm). À NOUS : générées pour golem, aucun visage réel, aucun
texte dans l'image (l'écran écrit le titre). Une seule fois — le résultat est rangé dans le .golem d'usine par
tools/make-factory-song.py --art <dossier>, qui garde ensuite celles du fichier.

Usage : set -a; . ./.env; set +a; .venv/bin/python tools/gen-factory-song-art.py <dossier> [cover] [band]"""
import base64
import io
import json
import os
import sys
import urllib.request

from PIL import Image

KEY = os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"]
MODEL = "gemini-3-pro-image"
RULES = ("Absolutely NO text anywhere: no letters, no words, no logos, no band name, no watermark, no numbers. "
         "Square 1:1 composition, full bleed, no border, no frame.")
IMAGES = {
    "cover": "Album cover art for a short, punchy hard-rock single called Golem Rising. A colossal stone golem made "
    "of dark cracked granite rises out of the ground in a storm at night, glowing molten-orange light pouring out of "
    "the cracks in its chest and eyes, one huge fist raised to the sky, lightning behind it, dust and sparks flying. "
    "Low camera angle, heroic and powerful. Painted in the style of a classic 1980s rock album cover: dramatic "
    "airbrushed illustration, deep blacks, electric blue sky, hot orange highlights. " + RULES,
    "band": "Band photo of a fictional rock band made only of five stone golems of cracked granite with glowing "
    "molten-orange cracks, on a small club stage under warm spotlights and haze: two golems playing electric guitars, "
    "one playing a bass, one at a drum kit, one at an upright piano, and one singing into a vintage microphone in front. "
    "No human beings, no human faces. Shot like a live concert photograph, slightly from below, shallow depth of field, "
    "warm amber and blue stage lights, energetic and good-humoured. " + RULES,
}


def gen(name, out):
    body = {"contents": [{"parts": [{"text": IMAGES[name]}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=240))
    parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    img = next((p["inlineData"]["data"] for p in parts if "inlineData" in p), None)
    if not img:
        raise SystemExit(f"{name} : pas d'image ({json.dumps(d)[:600]})")
    im = Image.open(io.BytesIO(base64.b64decode(img))).convert("RGB").resize((1000, 1000), Image.LANCZOS)
    path = os.path.join(out, f"{name}.jpg")
    im.save(path, "JPEG", quality=86, optimize=True, progressive=True)
    print(path, os.path.getsize(path))


if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for n in sys.argv[2:] or list(IMAGES):
        gen(n, out)
