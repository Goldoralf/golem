#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Les RÉFÉRENCES MIDI des démos (docs/preset-preview.md §1 et §7, 2026-11-03) : l'équivalent des DI de guitare
pour les claviers et la batterie. Une DI se re-ampe à travers la chaîne d'un patch ; une référence MIDI se JOUE
par l'instrument du patch (Vital, piano, orgue, kit), puis traverse sa chaîne. Composées ICI, à nous — aucune
phrase reconnaissable, comme les grooves d'usine (tools/make-factory-grooves.py) : le script EST la partition,
il se relit, se corrige et se régénère à l'identique.

Règles des références : courtes, en MI (comme les DI, pour comparer les patchs entre eux), la dernière note ou le
dernier coup LAISSÉ SONNER (la fin de piste tombe une mesure après : les queues de reverb et de delay s'entendent).
Pas de tempo imposé au patch : la référence garde le sien.

Claviers (canal 1) : piano · epiano · organ · pad · lead · bass (une basse de synthé, mi1–mi2) — la pédale de sustain (CC64) sur les pianos, la molette
(CC1) qui monte sur le pad et sur la note tenue du lead, un bend d'un ton sur le lead.
Batterie (canal 10) : rock · funk · jazz · metal — General MIDI, et seulement les notes qui ont le même sens sur les
kits du rack (même liste que les grooves) : deux mesures de groove, une variation, un break, puis le crash final.

    ./tools/make-midi-refs.py       # écrit library/di-refs/{keys,drums}/<bucket>.mid et met à jour index.json

Les fichiers vont avec les DI (library/di-refs/, hors dépôt, livrés dans la release di-refs) ; ce script, lui, est
commité : la partition reste lisible et régénérable.
"""
import json
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "library", "di-refs")
PPQ = 480

# ── l'écriture SMF (format 0) : notes, contrôleurs, bend ───────────────────────────────────────────────────────


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def smf(notes, bars, tempo, ch=0, cc=(), bend=(), beats_per_bar=4):
    """notes = [(début en noires, durée en noires, note, vélocité)] ; cc = [(temps, n° CC, valeur)] ;
    bend = [(temps, valeur −8192..8191)]. La fin de piste tombe pile sur la barre `bars`."""
    length = int(round(bars * beats_per_bar * PPQ))
    tick = lambda t: int(round(t * PPQ))
    ev = []
    for t, d, n, v in notes:
        a, b = tick(t), min(tick(t + d), length)
        assert 0 <= a < b <= length, (t, d, n)
        ev.append((a, 2, bytes([0x90 | ch, n, max(1, min(127, v))])))
        ev.append((b, 0, bytes([0x80 | ch, n, 0])))
    for t, num, val in cc:
        ev.append((tick(t), 1, bytes([0xB0 | ch, num, max(0, min(127, val))])))
    for t, val in bend:
        v = max(0, min(16383, val + 8192))
        ev.append((tick(t), 1, bytes([0xE0 | ch, v & 0x7F, v >> 7])))
    ev.sort(key=lambda e: (e[0], e[1]))
    trk = bytearray()
    trk += _vlq(0) + b"\xff\x58\x04" + bytes([beats_per_bar, 2, 24, 8])
    trk += _vlq(0) + b"\xff\x51\x03" + struct.pack(">I", int(60_000_000 / tempo))[1:]
    last = 0
    for t, _, msg in ev:
        trk += _vlq(t - last) + msg
        last = t
    trk += _vlq(length - last) + b"\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ) + b"MTrk" + struct.pack(">I", len(trk)) + bytes(trk)


def chord(t, d, pitches, v, spread=0.0):
    """Un accord ; `spread` > 0 égrène légèrement (en noires) du grave vers l'aigu, comme une main."""
    return [(t + i * spread, d - i * spread, p, v) for i, p in enumerate(pitches)]


def pedal(bars, per_bar=1, tail=True):
    """Pédale de sustain relevée puis reposée à chaque changement d'accord (juste après l'attaque)."""
    out = []
    for b in range(bars):
        for k in range(per_bar):
            t = b * 4 + k * 4 / per_bar
            out += [(t, 64, 0), (t + 0.05, 64, 127)]
    if not tail:
        out.append((bars * 4 - 0.01, 64, 0))
    return out

# ── CLAVIERS (MI majeur) ────────────────────────────────────────────────────────────────────────────────────


def k_piano():
    """Ballade : main gauche fondamentale + quinte, accord, mélodie au-dessus ; la nuance monte puis retombe."""
    n = []
    prog = [((40, 47), (64, 68, 71)), ((37, 44), (61, 64, 68)), ((33, 40), (61, 64, 69)), ((35, 42), (63, 66, 71))]
    mel = [[(1, 73), (2, 76), (2.5, 75), (3, 71)], [(1, 73), (2, 68), (2.5, 71), (3, 73)],
           [(1, 76), (2, 73), (2.5, 69), (3, 71)], [(1, 75), (2, 78), (2.5, 76), (3, 75)]]
    for b, ((r, f), ch) in enumerate(prog):
        t, v = b * 4, (58, 68, 78, 70)[b]
        n += [(t, 2, r, v + 6), (t + 1.5, 2.5, f, v - 6)]
        n += chord(t, 3.9, ch, v - 10, spread=0.02)
        n += [(t + o, 0.9, p, v + 8) for o, p in mel[b]]
    n += [(16, 4, 28, 70), (16, 4, 40, 64)] + chord(16, 4, (59, 64, 68, 71, 76), 66, spread=0.03)
    return smf(n, 6, 80, cc=pedal(5))


def e_piano():
    """Comping soul : neuvièmes sans fondamentale à la main droite, la basse à gauche, des anticipations."""
    n = []
    prog = [(40, (63, 66, 68, 71)), (37, (59, 63, 64, 68)), (45, (56, 59, 61, 64)), (35, (57, 61, 64, 68))]
    for b, (bass, vo) in enumerate(prog):
        t = b * 4
        n += [(t, 1.4, bass, 84), (t + 2.5, 1.4, bass + 12, 70)]
        n += chord(t, 1.25, vo, 82) + chord(t + 1.5, 0.45, vo, 58) + chord(t + 2.5, 1.0, vo, 74)
        n += chord(t + 3.5, 0.4, vo, 50)
    n += [(16, 4, 40, 80)] + chord(16, 4, (63, 66, 68, 71, 75), 78, spread=0.015)
    return smf(n, 6, 88, cc=pedal(5, per_bar=2))


def organ():
    """Gospel sur pédale de mi : accords tenus et liés (l'orgue ne connaît pas la vélocité), un trait à la fin."""
    n = [(0, 16, 28, 100)]                                                      # pédale de basse, mi grave
    prog = [(52, 56, 59, 64), (52, 57, 61, 64), (52, 56, 59, 64), (51, 54, 59, 63)]
    for b, ch in enumerate(prog):
        n += chord(b * 4, 4 if b < 3 else 2.5, ch, 100)
    n += [(14.5, 0.5, 71, 100), (15, 0.5, 73, 100), (15.5, 0.5, 75, 100)]       # si, do#, ré# vers le mi
    n += chord(12 + 2.5, 1.5, (51, 54, 59), 100)
    n += [(16, 4, 28, 100)] + chord(16, 4, (52, 56, 59, 64, 76), 100)
    return smf(n, 6, 100)


def pad():
    """Nappe lente : quatre accords legato qui se chevauchent un peu ; la molette ouvre le son peu à peu."""
    n = []
    prog = [(52, 59, 63, 66, 68), (49, 56, 59, 64, 66), (45, 52, 59, 61, 64)]
    for b, ch in enumerate(prog):
        n += chord(b * 4, 4.3, ch, 72)
    n += chord(12, 8, (40, 52, 59, 64, 68, 71), 70)
    mod = [(i * 0.5, 1, int(i * 0.5 * 90 / 20)) for i in range(41)]           # 0 → 90 sur vingt temps
    return smf(n, 6, 70, cc=mod)


def lead():
    """Lead monophonique (mi mixolydien) : phrasé lié, un bend d'un ton, une note tenue qui vibre à la molette."""
    n = [(0, 1.5, 76, 96), (1.5, 0.5, 74, 84), (2, 0.5, 71, 88), (2.5, 0.5, 69, 80), (3, 1, 71, 92),
         (4, 0.5, 74, 90), (4.5, 0.5, 76, 94), (5, 1, 79, 104), (6, 0.5, 81, 96), (6.5, 0.5, 79, 88), (7, 1, 76, 92),
         (8, 2, 81, 108), (10, 0.5, 79, 92), (10.5, 0.5, 76, 88), (11, 1, 74, 90),
         (12, 6, 76, 104)]
    bend = [(8.25 + i * 0.05, int(8191 * min(1, i / 5))) for i in range(6)]     # la → si, en un quart de temps
    bend += [(9.6 + i * 0.05, int(8191 * (1 - min(1, i / 4)))) for i in range(5)] + [(10, 0)]
    vib = [(13 + i * 0.25, 1, min(110, i * 8)) for i in range(17)]
    return smf(n, 6, 100, cc=vib + [(17.9, 1, 0)], bend=bend)

def bass():
    """Basse de synthé (2026-11-14, pour un preset Vital « Bass » écouté seul) : une ligne monophonique en mi, grave
    (mi1–mi2), croches liées et notes piquées, des sauts d'octave, une glissade, puis la fondamentale tenue."""
    n = []
    riff = [(0, 0.75, 28, 104), (0.75, 0.25, 28, 72), (1, 0.5, 40, 96), (1.5, 0.5, 28, 80), (2, 0.75, 31, 98),
            (2.75, 0.25, 33, 76), (3, 1, 35, 100)]
    for b, shift in enumerate((0, 0, -4, -2)):                                 # mi, mi, do, ré
        n += [(b * 4 + t, d, p + shift, v) for t, d, p, v in riff]
    n += [(16, 4, 28, 108)]
    bend = [(15.5 + i * 0.05, int(-4096 * (1 - min(1, i / 6)))) for i in range(7)]   # glisse d'un ton vers le mi
    return smf(n, 6, 100, cc=[(0, 1, 0)], bend=bend)

# ── BATTERIE (canal 10) ─────────────────────────────────────────────────────────────────────────────────────


K, X, S, TL, TM, CH, PH, OH, CR, RD, BL = 36, 37, 38, 41, 45, 42, 44, 46, 49, 51, 53
TRIP = 2 / 3


def hits(lst, length=0.2):
    return [(t, length, n, v) for t, n, v in lst]


def ending(bar):
    """Le coup final : crash + grosse caisse sur le premier temps, puis on laisse sonner une mesure."""
    t = bar * 4
    return [(t, CR, 118), (t, K, 112)]


def d_rock():
    h = []
    for b in range(3):
        t = b * 4
        h += [(t + i / 2, CH, 92 if i % 2 == 0 else 70) for i in range(8)]
        h += [(t + 1, S, 112), (t + 3, S, 114)]
        h += [(t + x, K, 110) for x in ((0, 2, 2.5) if b != 1 else (0, 1.5, 2, 3.5))]
    h[0] = (0, CR, 108)
    t = 12                                                                              # le break
    h += [(t, CH, 92), (t + 0.5, CH, 70), (t + 1, S, 112), (t, K, 110), (t + 1.5, K, 104)]
    h += [(t + 2 + i / 4, n, 96 + i * 3) for i, n in enumerate((S, S, S, S, TM, TM, TL, TL))]
    return smf(hits(h + ending(4)), 6, 110, ch=9)


def d_funk():
    h = []
    for b in range(3):
        t = b * 4
        h += [(t + i / 4, CH, 88 if i % 2 == 0 else 54) for i in range(16) if not (i == 14)]
        h += [(t + 3.5, OH, 86), (t + 1, S, 114), (t + 3, S, 114)]
        h += [(t + x, S, 34) for x in (0.75, 1.75, 2.25, 3.75)]                         # notes fantômes
        h += [(t + x, K, 108) for x in ((0, 0.75, 2.5) if b != 1 else (0, 0.75, 1.5, 2.75, 3.25))]
    t = 12
    h += [(t + i / 4, CH, 80) for i in range(8)] + [(t + 1, S, 114), (t, K, 108), (t + 0.75, K, 100)]
    h += [(t + 2 + i / 4, n, v) for i, (n, v) in enumerate(((S, 80), (S, 50), (S, 96), (TM, 100),
                                                            (S, 60), (TM, 104), (TL, 108), (TL, 112)))]
    return smf(hits(h + ending(4)), 6, 96, ch=9)


def d_jazz():
    h = []
    for b in range(3):
        t = b * 4
        h += [(t, RD, 92), (t + 1, RD, 96), (t + 1 + TRIP, RD, 70), (t + 2, RD, 92), (t + 3, RD, 96),
              (t + 3 + TRIP, RD, 70)]
        h += [(t + 1, PH, 74), (t + 3, PH, 74)]
        h += [(t + x, K, 34) for x in range(4)]                                         # grosse caisse « plume »
        if b == 1:
            h += [(t + 2 + TRIP, S, 58), (t + 3 + TRIP, X, 70)]                         # comping
        else:
            h += [(t + 3, X, 76)]
    t = 12
    h += [(t, RD, 92), (t + 1, RD, 96), (t + 1, PH, 74)]
    h += [(t + 2 + i * TRIP / 2, n, 70 + i * 5) for i, n in enumerate((S, S, S, TM, TM, TL))]
    return smf(hits(h + [(16, RD, 100), (16, BL, 96), (16, CR, 104), (16, K, 96)]), 6, 140, ch=9)


def d_metal():
    h = []
    for b in range(3):
        t = b * 4
        h += [(t + i / 4, K, 104 if i % 4 == 0 else 96) for i in range(16)]           # double pédale en doubles croches
        h += [(t + q, CR if q == 0 else RD, 108 if q == 0 else 96) for q in range(4)]
        h += [(t + 1, S, 120), (t + 3, S, 120)]
    t = 12
    h += [(t, CR, 112), (t, K, 106), (t + 1, S, 120), (t + 0.5, K, 100)]
    h += [(t + 2 + i / 4, n, 108 + (i % 2) * 6) for i, n in enumerate((S, S, TM, TM, TM, TL, TL, TL))]
    h += [(t + 2 + i / 4, K, 98) for i in range(8)]
    return smf(hits(h + ending(4)), 6, 160, ch=9)

# ── l'index ─────────────────────────────────────────────────────────────────────────────────────────────────


REFS = {
    "keys/piano":  (k_piano, "Piano ballad", "velocity, sustain pedal, the body and the room of a piano"),
    "keys/epiano": (e_piano, "Electric piano comping", "velocity bark, tremolo and chorus, ninth chords"),
    "keys/organ":  (organ, "Gospel organ", "held legato chords, drawbars, rotary speaker"),
    "keys/pad":    (pad, "Slow pad", "overlapping chords, filter opened by the mod wheel, long release"),
    "keys/lead":   (lead, "Synth lead", "legato, pitch bend, vibrato on the mod wheel, delay tails"),
    "keys/bass":   (bass, "Synth bass", "low end, octave jumps, staccato and legato, glide into the root"),
    "drums/rock":  (d_rock, "Rock beat", "kick and snare body, hi-hat, toms, crash"),
    "drums/funk":  (d_funk, "Funk beat", "ghost notes, open hi-hat, tight snare"),
    "drums/jazz":  (d_jazz, "Jazz swing", "ride, feathered kick, cross-stick, brushes or sticks"),
    "drums/metal": (d_metal, "Metal double kick", "kick definition at speed, crash and ride, tom fill"),
}


def main():
    idx_path = os.path.join(OUT, "index.json")
    try:
        index = json.load(open(idx_path, encoding="utf-8"))
    except (OSError, ValueError):
        index = {"refs": {}}
    refs = index.setdefault("refs", {})
    for key, (fn, name, shows) in REFS.items():
        rel = key + ".mid"
        os.makedirs(os.path.join(OUT, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(OUT, rel), "wb") as f:
            f.write(fn())
        refs[key] = {**(refs.get(key) or {}), "file": rel, "kind": "midi", "name": name, "key": "E",
                     "showcases": shows}
        if key.startswith("drums/"):
            refs[key].pop("key", None)
        print(f"  ✓ {rel}")
    tmp = idx_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    os.replace(tmp, idx_path)
    print(f"✓ {len(REFS)} références MIDI, index : {idx_path}")


if __name__ == "__main__":
    main()
