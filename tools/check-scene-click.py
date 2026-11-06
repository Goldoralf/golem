#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesure le CLIC d'une bascule de scène : ce que la sortie fait pendant les quelques millisecondes
où une branche cède la place à l'autre.

    ./tools/check-scene-click.py              # 12 bascules A<->B ⚠ TON DE TEST + une prise courte (supprimée)
    ./tools/check-scene-click.py -n 20 --keep

POURQUOI (2026-09-21) : on hésitait à couper une branche par son VOLUME (un saut sec, 0 dB -> -inf)
ou par un MUTE de piste (Reaper y applique un court fondu, d'après la source de SWS). Les deux ne font
ni trou ni gel (check-scene-gap.py) ; ce qui les distingue, c'est ce qui s'entend À la bascule. On le
mesure au lieu de le supposer.

COMMENT : un ton continu entre dans la lane ; le rack ENREGISTRE la sortie de la piste de fusion (la
prise normale du bloc Rec, mode multipiste) pendant n bascules A<->B ; puis, sur le fichier, à
l'échantillon près :
  · la DURÉE de la transition — le temps que met le niveau (RMS 0,5 ms) pour passer de 10 % à 90 %
    du chemin entre le niveau d'avant et celui d'après. ~0 ms = un saut ; quelques ms = un fondu ;
  · le PIC de « cassure » — la dérivée seconde du signal (x[n] - 2x[n-1] + x[n-2]) pendant ±3 ms
    autour de la bascule, comparée à ce qu'elle vaut en régime établi dans les DEUX scènes. Une
    discontinuité (un clic) fait un pic ; une transition douce reste dans le régime établi.
Le détecteur ne sait pas qui a basculé : il trouve les bascules sur le niveau (les scènes A et B de
Paper Kite diffèrent de ~7 dB). La prise de mesure est supprimée à la fin, sauf --keep.
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")


def post(path, body=None):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body or {}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=30))


def state():
    return json.load(urllib.request.urlopen(BRIDGE + "/api/state", timeout=10))


def load(path):
    w = wave.open(path)
    n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    raw = w.readframes(n)
    w.close()
    if sw == 3:
        a = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
        x = np.where(x & 0x800000, x - (1 << 24), x) / float(1 << 23)
    elif sw == 2:
        x = np.frombuffer(raw, dtype=np.int16) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype=np.int32) / float(1 << 31)
    else:
        sys.exit("format WAV non géré (%d octets)" % sw)
    return x.reshape(-1, ch)[:, 0].astype(np.float64), sr


def analyse(x, sr):
    """Trouve les bascules sur le niveau, et mesure pour chacune transition et cassure."""
    h = max(1, int(sr * 0.0005))                                  # RMS sur 0,5 ms
    n = len(x) // h
    rms = np.sqrt(np.mean(x[:n * h].reshape(n, h) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    sm = np.convolve(db, np.ones(20) / 20, mode="same")          # niveau lissé sur 10 ms
    lo, hi = np.percentile(sm[sm > -60], 10), np.percentile(sm[sm > -60], 90)
    mid = (lo + hi) / 2
    if hi - lo < 3:
        return None, (lo, hi)
    state_hi = sm > mid
    edges = np.nonzero(np.diff(state_hi.astype(int)))[0]
    d2 = np.abs(x[2:] - 2 * x[1:-1] + x[:-2])
    guard = int(0.15 / 0.0005)                                    # régime établi = à >150 ms d'une bascule
    steady = np.ones(n, dtype=bool)
    for e in edges:
        steady[max(0, e - guard):e + guard] = False
    steady_samples = np.repeat(steady, h)[:len(d2)]
    ref = np.percentile(d2[steady_samples], 99.99) if steady_samples.any() else np.max(d2)
    out = []
    for e in edges:
        a, b = e - 60, e + 60                                     # ±30 ms autour
        if a < 0 or b >= n:
            continue
        before, after = np.median(db[a:e - 10]), np.median(db[e + 10:b])
        seg = db[e - 20:e + 20]
        lo10 = before + 0.1 * (after - before)
        hi90 = before + 0.9 * (after - before)
        up = after > before
        i10 = next((i for i, v in enumerate(seg) if (v >= lo10 if up else v <= lo10)), None)
        i90 = next((i for i, v in enumerate(seg) if (v >= hi90 if up else v <= hi90)), None)
        trans = (i90 - i10) * 0.5 if (i10 is not None and i90 is not None and i90 >= i10) else None
        s0, s1 = max(0, e * h - int(sr * 0.003)), min(len(d2), e * h + int(sr * 0.003))
        spike = 20 * np.log10(max(np.max(d2[s0:s1]), 1e-9) / max(ref, 1e-9))
        out.append({"t": e * h / sr, "up": bool(up), "from_db": before, "to_db": after,
                    "trans_ms": trans, "spike_db": spike})
    return out, (lo, hi)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-n", type=int, default=12, help="nombre de bascules")
    ap.add_argument("--interval", type=float, default=0.9)
    ap.add_argument("--keep", action="store_true", help="garder la prise de mesure")
    a = ap.parse_args()
    st = state()
    if st["perf"].get("recording") or (st.get("backing") or {}).get("playing"):
        sys.exit("✗ une prise ou un backing tourne")
    head = "Sandbox #Input 1"
    post("/api/recall", {"scene": "A"})
    time.sleep(1.2)
    post("/api/gapmeter", {"on": True, "tone": head, "db": -24, "tracks": [head + "#merge"], "thrs": [-70], "hold": 120})
    time.sleep(1.5)
    post("/api/perf/start")
    time.sleep(1.8)
    for i in range(a.n):
        post("/api/recall", {"scene": "B" if i % 2 == 0 else "A"})
        time.sleep(a.interval)
    time.sleep(0.6)
    post("/api/perf/stop")
    take = None
    for _ in range(80):
        time.sleep(0.25)
        s = state()
        if not s["perf"].get("recording") and s["perf"].get("file"):
            take = os.path.join(ROOT, s["perf"]["file"])
            if os.path.exists(os.path.join(take, "take.json")):
                break
    post("/api/gapmeter", {"on": False})
    post("/api/recall", {"scene": "A"})
    if not take or not os.path.isdir(take):
        sys.exit("✗ prise introuvable : %s" % take)
    wav = next((os.path.join(take, f) for f in sorted(os.listdir(take)) if "merge" in f and f.endswith(".wav")), None)
    if not wav:
        sys.exit("✗ pas de piste de fusion dans %s : %s" % (take, os.listdir(take)))
    x, sr = load(wav)
    res, (lo, hi) = analyse(x, sr)
    print("prise %s · %s · %.1f s à %d Hz · niveaux des deux scènes : %.1f / %.1f dB" % (
        os.path.basename(take), os.path.basename(wav), len(x) / sr, sr, lo, hi))
    if not res:
        print("✗ bascules non détectées (les deux scènes ont le même niveau ?)")
    else:
        for r in res:
            print("  %6.2f s  %s  %5.1f -> %5.1f dB   transition %s   cassure %+5.1f dB" % (
                r["t"], "vers la forte " if r["up"] else "vers la douce ", r["from_db"], r["to_db"],
                ("%4.1f ms" % r["trans_ms"]) if r["trans_ms"] is not None else "   ?   ", r["spike_db"]))
        tr = [r["trans_ms"] for r in res if r["trans_ms"] is not None]
        sp = [r["spike_db"] for r in res]
        print("\n── bilan : %d bascules · transition médiane %.1f ms (max %.1f) · cassure médiane %+.1f dB (max %+.1f) ──" % (
            len(res), float(np.median(tr)) if tr else -1, max(tr) if tr else -1, float(np.median(sp)), max(sp)))
        print("   cassure > +6 dB = un pic plus fort que tout ce que le signal fait en régime établi : un CLIC")
    if a.keep:
        print("prise gardée : %s" % take)
    else:
        shutil.rmtree(take)
        print("prise de mesure supprimée")


if __name__ == "__main__":
    main()
