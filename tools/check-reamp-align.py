#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le reamp est-il ALIGNÉ à l'échantillon sur la DI ? (docs/reamp.md §5, lot 3)

Fabrique une DI de test (silence + trois impulsions espacées), la fait rendre par le rack à travers
une lane d'un preset (POST /api/reamp/try — le vrai chemin du job, sans rien monter), puis mesure
où la sortie démarre à chaque impulsion. Un ampli déforme, une IR étale, mais l'ATTAQUE reste où
elle est : un décalage constant entre DI et rendu = de la latence de chaîne non compensée.

  ./tools/check-reamp-align.py                       # preset courant, première lane instrumentale
  ./tools/check-reamp-align.py --preset paper-kite --scene B --lane guitar-1
  ./tools/check-reamp-align.py --di recordings/perf-…/DI-Sandbox-Input-1.wav   # une vraie DI : longueur + écoute

⚠ Prend le moteur live pendant le rendu (quelques secondes) puis le remet : à lancer quand
personne ne joue. N'enregistre rien, ne monte rien.
"""
import argparse
import array
import contextlib
import json
import os
import sys
import urllib.request
import wave

BRIDGE = os.environ.get("GOLEM_BRIDGE", "http://localhost:8770")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000
MARKS = (1.0, 2.5, 4.0)            # secondes : trois impulsions, le silence entre elles laisse retomber
TOL_MS = 1.0                       # budget : au-delà, la piste « bave » à côté des autres lanes


def make_di(path):
    n = int(SR * 5.5)
    a = array.array("h", [0] * n)
    for t in MARKS:
        i = int(t * SR)
        for k in range(48):         # 1 ms de créneau : assez d'énergie pour traverser un gate
            a[i + k] = 20000 if k < 24 else -20000
    with contextlib.closing(wave.open(path, "wb")) as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(a.tobytes())


def read_mono(path):
    with contextlib.closing(wave.open(path, "rb")) as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        a = array.array("h", raw); scale = 32768.0
    elif width == 3:
        a = [int.from_bytes(raw[i:i + 3], "little", signed=True) for i in range(0, len(raw), 3)]; scale = 8388608.0
    elif width == 4:
        a = array.array("i", raw); scale = 2147483648.0
    else:
        sys.exit(f"sample width {width} not handled")
    return sr, [max(abs(a[i + c]) for c in range(ch)) / scale for i in range(0, len(a), ch)]


def onset(sig, start, stop, floor):
    for i in range(start, min(stop, len(sig))):
        if sig[i] >= floor:
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset"); ap.add_argument("--scene"); ap.add_argument("--lane"); ap.add_argument("--di")
    a = ap.parse_args()
    di = os.path.abspath(a.di) if a.di else os.path.join(ROOT, "recordings", ".reamp", "align-di.wav")
    if not a.di:
        os.makedirs(os.path.dirname(di), exist_ok=True)
        make_di(di)
    body = {k: v for k, v in {"preset": a.preset, "scene": a.scene, "lane": a.lane, "di": di}.items() if v}
    req = urllib.request.Request(BRIDGE + "/api/reamp/try", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"✗ render refused: {e.read().decode()[:300]}")
    print(f"rendered {res['preset']} · {res['scene']} · lane {res['lane']} -> {res['wav']}")
    with contextlib.closing(wave.open(di, "rb")) as w:
        di_sr, di_n = w.getframerate(), w.getnframes()
    ok = True
    if (res["sample_rate"], res["frames"]) != (di_sr, di_n):
        print(f"✗ length/rate: render {res['frames']} @ {res['sample_rate']} Hz, DI {di_n} @ {di_sr} Hz"); ok = False
    else:
        print(f"✓ same rate and length as the DI ({di_n} samples @ {di_sr} Hz)")
    if a.di:
        print("  (real DI: listen to the file — alignment is measured on the synthetic DI only)")
        return 0 if ok else 1
    sr, out = read_mono(res["wav"])
    peak = max(out) or 0
    if peak < 1e-4:
        print("✗ the render is SILENT — the lane did not pass the DI (NAM without model? lane muted in this scene?)")
        return 1
    offs = []
    for t in MARKS:
        i0 = int(t * sr)
        # l'attaque : le premier échantillon à 20 % de la crête locale, cherché de −5 ms à +50 ms
        win = out[max(0, i0 - sr // 200): i0 + sr // 20]
        loc = max(win) if win else 0
        at = onset(out, max(0, i0 - sr // 200), i0 + sr // 20, 0.2 * loc) if loc > 1e-4 else None
        offs.append(None if at is None else at - i0)
    print("impulse offsets (samples):", offs)
    real = [o for o in offs if o is not None]
    if not real:
        print("✗ no attack found near the impulses"); return 1
    worst_ms = max(abs(o) for o in real) * 1000.0 / sr
    spread = max(real) - min(real)
    verdict = "✓" if worst_ms <= TOL_MS and spread <= sr // 1000 else "✗"
    print(f"{verdict} worst offset {worst_ms:.2f} ms (budget {TOL_MS} ms), spread {spread} samples")
    return 0 if (ok and verdict == "✓") else 1


if __name__ == "__main__":
    sys.exit(main())
