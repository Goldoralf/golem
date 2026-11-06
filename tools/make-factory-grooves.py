#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Les GROOVES D'USINE du golem (2026-10-13, + six pour « Golem Rising » le 2026-10-20) : des rythmes composés ICI, à nous — aucun pack tiers.

Pourquoi un script et pas des .mid posés à la main : un groove se relit (la grille ci-dessous EST la partition), se
corrige et se régénère. Sortie : library/factory/grooves/<id>.mid + meta.json (pack, genre, tempo), déposés au
démarrage par bridge/factory.py comme le reste de l'usine.

Convention : General MIDI, et SEULEMENT les notes qui ont le même sens sur les kits du rack (AVL Black Pearl, Red
Zeppelin, Blonde Bop — leur 48 est le charleston OUVERT, pas un tom) : 36 kick · 37 cross-stick · 38 snare · 41 tom
basse · 45 tom · 42 charleston fermé · 44 pédale · 46 charleston entrouvert · 49 crash · 51 ride · 53 cloche de ride.
Deux mesures par groove, la fin de piste tombe PILE sur la barre (golem_drums arrondit la boucle à la mesure).

    ./tools/make-factory-grooves.py          # écrit library/factory/grooves/
"""
import json
import os
import random
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "library", "factory", "grooves")
PPQ = 480
K, X, S, TL, TM, CH, PH, OH, CR, RD, BL = 36, 37, 38, 41, 45, 42, 44, 46, 49, 51, 53
# les sons des kits de PADS (pads-house / lofi / trap, en GM depuis le 2026-10-13) que les batteries AVL n'ont pas
SUB, CLAP, COW = 35, 39, 56


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def smf(hits, bars, beats_per_bar=4, den=4, tempo=120):
    """hits = [(temps_en_noires, note, vélocité)] -> Standard MIDI File format 0, canal 10, PPQ 480."""
    length = int(round(bars * beats_per_bar * (4 / den) * PPQ))
    ev = []
    for t, n, v in hits:
        tick = int(round(t * PPQ))
        assert 0 <= tick < length, (t, n)
        ev.append((tick, 1, bytes([0x99, n, max(1, min(127, v))])))
        ev.append((min(tick + PPQ // 8, length), 0, bytes([0x89, n, 0])))
    ev.sort(key=lambda e: (e[0], e[1]))
    trk = bytearray()
    trk += _vlq(0) + b"\xff\x58\x04" + bytes([beats_per_bar, {4: 2, 8: 3}[den], 24, 8])
    trk += _vlq(0) + b"\xff\x51\x03" + struct.pack(">I", int(60_000_000 / tempo))[1:]
    last = 0
    for tick, _, msg in ev:
        trk += _vlq(tick - last) + msg
        last = tick
    trk += _vlq(length - last) + b"\xff\x2f\x00"        # fin de piste = la barre, pile
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ) + b"MTrk" + struct.pack(">I", len(trk)) + bytes(trk)


def human(hits, seed, spread=6):
    """Vélocités un peu vivantes (déterministe : le même fichier à chaque génération)."""
    r = random.Random(seed)
    return [(t, n, v + r.randint(-spread, spread)) for t, n, v in hits]


def grid(steps, per_beat, note, pattern, vel_on=90, vel_acc=None, bars=2, beats=4):
    """pattern = chaîne de pas ('x' frappe, 'X' accent, '.' rien), répétée sur `bars` mesures."""
    out, n = [], per_beat * beats
    for b in range(bars):
        for i, c in enumerate(pattern[b * n:(b + 1) * n] if len(pattern) >= n * bars else pattern):
            if c in "xX":
                out.append((b * beats + i / per_beat, note, (vel_acc or vel_on + 20) if c == "X" else vel_on))
    return out


TRIP = (0, 2 / 3)                 # swing ternaire : la croche « en retard » tombe au 3e tiers du temps


def g_funk16():
    h = grid(4, 4, CH, "XxXx" * 8, 52, 90)                                          # doubles croches, accents sur les croches
    h = [x for x in h if not (x[0] == 7.5)] + [(7.5, OH, 88)]                      # ouverte sur le « et » du 4
    h += [(1, S, 112), (3, S, 112), (5, S, 112), (7, S, 112)]
    h += [(t, S, 34) for t in (0.75, 1.75, 2.5, 3.75, 4.75, 5.25, 6.75)]          # notes fantômes
    h += [(t, K, 108) for t in (0, 0.75, 2.5, 4, 4.5, 6.25, 6.75)]
    return h


def g_rock8():
    h = grid(2, 2, CH, "Xx" * 8, 72, 96)
    h = [x for x in h if x[0] != 0] + [(0, CR, 104)]
    h += [(t, S, 112) for t in (1, 3, 5, 7)]
    h += [(t, K, 110) for t in (0, 2, 2.5, 4, 5.5, 6)]
    return h


def g_shuffle():
    h = []
    for beat in range(8):
        h += [(beat + TRIP[0], RD, 90 if beat % 2 == 0 else 80), (beat + TRIP[1], RD, 62)]
    h += [(t, S, 108) for t in (1, 3, 5, 7)]
    h += [(t, K, 104) for t in (0, 2, 4, 6, 6 + 2 / 3 + 1)]                     # la reprise avant la boucle
    h += [(t, PH, 70) for t in (1, 3, 5, 7)]
    return h


def g_halftime():
    h = grid(2, 2, CH, "Xx" * 8, 70, 92)
    h = [x for x in h if x[0] != 0] + [(0, CR, 108)]
    h += [(2, S, 118), (6, S, 118), (7.75, S, 40)]
    h += [(t, K, 112) for t in (0, 0.5, 1.5, 3.5, 4, 4.75, 5.5)]
    return h


def g_fourfloor():
    h = [(b, K, 112) for b in range(8)]
    h += [(b + 0.5, OH, 84) for b in range(8)]
    h += [(b, CH, 66) for b in range(8)]
    h += [(t, S, 104) for t in (1, 3, 5, 7)]
    return h


def g_boombap():
    sw = 0.58                                                                       # swing léger des croches
    h = [(b + o, CH, 78 if o == 0 else 58) for b in range(8) for o in (0, sw)]
    h += [(t, S, 116) for t in (1, 3, 5, 7)]
    h += [(t, K, 112) for t in (0, 1.75, 2.5, 4, 4.5, 6.5, 7.75)]
    return h


def g_onedrop():
    h = []
    for b in range(8):
        h += [(b + TRIP[0], CH, 64), (b + TRIP[1], CH, 46)]
    h += [(2, X, 104), (2, K, 106), (6, X, 104), (6, K, 106)]                       # tout sur le 3
    h += [(7 + TRIP[1], X, 50)]
    return h


def g_bossa():
    h = [(b + o, CH, 54 if o else 64) for b in range(8) for o in (0, 0.5)]
    clave = (0, 1.5, 3, 5, 6.5)                                                     # clave bossa sur deux mesures
    h += [(t, X, 92) for t in clave]
    h += [(t, K, 84 if t % 2 == 0 else 66) for t in (0, 1.5, 2, 3.5, 4, 5.5, 6, 7.5)]
    return h


def g_swing():
    h = []
    for b in range(8):
        h.append((b, RD, 92 if b % 2 else 78))
        if b % 2 == 1:
            h.append((b + TRIP[1], RD, 64))                                         # « spang-a-lang »
    h += [(t, PH, 74) for t in (1, 3, 5, 7)]
    h += [(t, K, 30) for t in range(8)]                                             # grosse caisse « plume »
    h += [(3 + TRIP[1], S, 46), (6 + TRIP[1], S, 40)]                               # un peu de comping
    return h


def g_sixeight():
    # 6/8 : 6 croches par mesure = 3 noires ; deux mesures = 6 noires
    h = [(i * 0.5, CH, 76 if i % 3 == 0 else 56) for i in range(12)]
    h = [x for x in h if x[0] != 0] + [(0, CR, 90)]
    h += [(1.5, S, 104), (4.5, S, 104)]
    h += [(t, K, 104) for t in (0, 2.5, 3, 5.5)]
    return h


def g_house():
    h = [(b, K, 116) for b in range(8)]
    h += [(t, CLAP, 108) for t in (1, 3, 5, 7)]
    h += [(b + 0.5, OH, 86) for b in range(8)]
    h += [(b + o, CH, 50) for b in range(8) for o in (0.25, 0.75)]                 # doubles croches légères
    h += [(t, X, 70) for t in (1.75, 3.25, 5.75, 6.5)]                              # rims syncopés
    return h


def g_lofi():
    sw = 0.6                                                                        # swing paresseux
    late = 0.04                                                                     # la caisse un peu en retard
    h = [(b + o, CH, 64 if o == 0 else 44) for b in range(8) for o in (0, sw) if not (b == 3 and o)]
    h += [(t + late, S, 100) for t in (1, 3, 5, 7)]
    h += [(t, SUB, 104) for t in (0, 2 + sw, 4, 5 + sw, 6.5)]
    h += [(t, X, 40) for t in (2.75, 6.75)]                                         # rim fantôme
    return h


def g_trap():
    # demi-tempo : la caisse (clap) sur le 3 ; 808 clairsemé ; charleston en croches avec des roulements en triolets
    h = [(b * 0.5, CH, 70 if b % 2 == 0 else 54) for b in range(16)]
    h = [x for x in h if not (3 <= x[0] < 4 or 7 <= x[0] < 8)]
    h += [(3 + i / 6, CH, 50 + i * 5) for i in range(6)]                            # roulement fin de mesure 1
    h += [(7 + i / 8, CH, 46 + i * 6) for i in range(8)]                            # roulement plus serré
    h += [(2, CLAP, 116), (6, CLAP, 116), (2, S, 70), (6, S, 70)]
    h += [(t, SUB, 112) for t in (0, 0.75, 2.5, 4, 5.5, 5.75)]
    h += [(4, OH, 72)]
    return h


# ── LA CHANSON D'USINE « Golem Rising » (2026-10-20) : un groove par partie, que l'ARRANGEMENT choisit section par
# section (docs/arrangement.md §6) — intro, couplet, refrain, solo, un break d'une mesure, le coup final. Ajoutés EN FIN
# de liste : les grooves d'avant gardent leur graine, donc leurs fichiers à l'octet près.
def g_rock_intro():
    """Toms et charleston au pied : ça monte sans encore taper."""
    h = [(b, PH, 70) for b in range(8)]
    h += [(t, TL, 96) for t in (0, 1, 2, 3, 4, 5, 6, 7)] + [(t + 0.5, TL, 70) for t in (1, 3, 5)]
    h += [(t, K, 104) for t in (0, 2, 4, 6)]
    h += [(0, CR, 96), (7.5, S, 88), (7.75, S, 100)]
    return h


def g_rock_verse():
    """Serré : charleston fermé, grosse caisse qui pousse, caisse sur 2 et 4."""
    h = grid(2, 2, CH, "Xx" * 8, 66, 88)
    h += [(t, S, 108) for t in (1, 3, 5, 7)]
    h += [(t, K, 106) for t in (0, 1.5, 2, 4, 5.5, 6, 6.5)]
    return h


def g_rock_chorus():
    """Ouvert : charleston entrouvert, crash sur le 1, la caisse qui claque."""
    h = [(b + o, OH, 84 if o == 0 else 66) for b in range(8) for o in (0, 0.5)]
    h = [x for x in h if x[0] != 0] + [(0, CR, 118), (4, CR, 100)]
    h += [(t, S, 120) for t in (1, 3, 5, 7)]
    h += [(t, K, 114) for t in (0, 0.5, 2, 2.5, 4, 4.5, 6, 6.5)]
    return h


def g_rock_solo():
    """Sous le solo : la ride et sa cloche, la grosse caisse en croches — ça porte sans couvrir la guitare."""
    h = [(b + o, RD, 88 if o == 0 else 64) for b in range(8) for o in (0, 0.5)]
    h = [x for x in h if x[0] != 0] + [(0, CR, 116)] + [(t, BL, 92) for t in (2, 6)]
    h += [(t, S, 116) for t in (1, 3, 5, 7)]
    h += [(t, K, 108) for t in (0, 1, 2, 2.5, 4, 5, 6, 6.5)]
    return h


def g_rock_fill():
    """Le break d'UNE mesure avant le refrain et le solo (la section ne dure qu'une mesure : seule la 1re joue)."""
    h = [(0, K, 110), (0, CH, 80), (0.5, CH, 70)]
    h += [(1 + i / 4, S, 70 + i * 6) for i in range(4)]
    h += [(2 + i / 4, TM, 96) for i in range(4)] + [(3 + i / 4, TL, 104) for i in range(4)]
    h += [(t, K, 104) for t in (2, 3)]
    return h + [(4, K, 90), (4, CH, 60)]             # la 2e mesure : un temps, pour que la boucle ait sa longueur


def g_rock_end():
    """Le coup final : crash et grosse caisse sur le 1, puis on laisse sonner."""
    return [(0, CR, 124), (0, K, 120), (0, S, 100)]


# ── LE PRESET METAL D'USINE (2026-10-20) : des grooves nettement DIFFÉRENTS d'une partie à l'autre, pour que
# l'arrangement les enchaîne et qu'on l'entende — intro aux toms, couplet djent en demi-temps, refrain en double
# pédale, breakdown, solo sur la cloche de ride, un break d'une mesure. Ajoutés EN FIN de liste (graines stables).
def g_metal_intro():
    """Tom basse en croches, grosse caisse sur chaque temps, crash sur chaque 1 : ça gronde avant d'entrer."""
    h = [(i / 2, TL, 100 if i % 2 == 0 else 76) for i in range(15)]
    h += [(t, K, 112) for t in range(8)] + [(0, CR, 112), (4, CR, 104)]
    h += [(7 + i / 4, S, 84 + i * 10) for i in range(4)]
    return h


def g_metal_verse():
    """Djent en DEMI-TEMPS : la caisse sur le 3, la grosse caisse calée sur un riff syncopé en doubles."""
    h = grid(2, 2, CH, "Xx" * 8, 70, 90)
    h += [(t, S, 118) for t in (2, 6)]
    h += grid(16, 4, K, "X..x..x.X..x..x." + "X..x..x.X.xx.x.x", 104, 116)
    return h


def g_metal_chorus():
    """Plein : double pédale en doubles croches, caisse sur 2 et 4, crash sur chaque temps."""
    h = [(t / 4, K, 104 if t % 2 == 0 else 92) for t in range(32)]
    h += [(t, S, 124) for t in (1, 3, 5, 7)]
    h += [(t, CR if t in (0, 4) else RD, 112 if t in (0, 4) else 96) for t in range(8)]
    return h


def g_metal_breakdown():
    """Le breakdown : demi-temps lourd, crash sur chaque temps, la grosse caisse épouse les chugs — et laisse des trous."""
    h = [(t, S, 126) for t in (2, 6)]
    h += [(t, CR, 104) for t in range(8)]
    h += grid(16, 4, K, "X.x...x.xx..x..." + "X.x...x.xx.x.xxx", 108, 120)
    return h


def g_metal_solo():
    """Sous le solo : double pédale continue, la cloche de ride en croches, caisse sur 2 et 4."""
    h = [(t / 4, K, 98 if t % 2 == 0 else 88) for t in range(32)]
    h += [(i / 2, BL, 96 if i % 2 == 0 else 78) for i in range(16) if i not in (0, 8)] + [(0, CR, 118), (4, CR, 106)]
    h += [(t, S, 120) for t in (1, 3, 5, 7)]
    return h


def g_metal_fill():
    """Le break d'UNE mesure : caisse, tom, tom basse en doubles, puis caisse et grosse caisse à l'unisson."""
    h = [(i / 4, S, 92 + i * 4) for i in range(4)] + [(1 + i / 4, TM, 104) for i in range(4)]
    h += [(2 + i / 4, TL, 110) for i in range(4)] + [(3 + i / 4, S, 120) for i in range(4)]
    h += [(3 + i / 4, K, 116) for i in range(4)]
    return h + [(4, K, 90), (4, CR, 110)]            # la 2e mesure : un temps, pour que la boucle ait sa longueur


def g_metal_end():
    """Le coup final : crash, grosse caisse et caisse à l'unisson sur le 1, puis on laisse sonner (Golem Rising)."""
    return [(0, CR, 126), (0, K, 124), (0, S, 112), (0, TL, 104)]


# id, nom, genre (docs/genres.md), tempo conseillé, fabrique, (temps, unité) par mesure
GROOVES = [
    ("golem-funk-16", "Funk 16", "funk", 100, g_funk16, (4, 4)),
    ("golem-rock-8", "Rock 8", "classic-rock", 120, g_rock8, (4, 4)),
    ("golem-shuffle", "Shuffle", "texas-blues", 92, g_shuffle, (4, 4)),
    ("golem-half-time", "Half-time", "hard-rock", 140, g_halftime, (4, 4)),
    ("golem-four-on-the-floor", "Four on the floor", "disco", 118, g_fourfloor, (4, 4)),
    ("golem-boom-bap", "Boom bap", "boom-bap", 90, g_boombap, (4, 4)),
    ("golem-one-drop", "One drop", "roots-reggae", 76, g_onedrop, (4, 4)),
    ("golem-bossa", "Bossa", "bossa-nova", 130, g_bossa, (4, 4)),
    ("golem-swing", "Swing", "swing", 140, g_swing, (4, 4)),
    ("golem-six-eight", "6/8 ballad", "ballad", 60, g_sixeight, (6, 8)),
    # pour les kits de PADS (le kit conseillé est le leur ; ils jouent aussi sur une batterie, sans clap ni cowbell)
    ("golem-house", "House", "house", 124, g_house, (4, 4), "pads-house"),
    ("golem-lofi", "Lo-fi", "lo-fi-hip-hop", 80, g_lofi, (4, 4), "pads-lofi"),
    ("golem-trap", "Trap", "trap", 140, g_trap, (4, 4), "pads-trap"),
    # « Golem Rising » (en fin de liste : voir plus haut)
    ("golem-rock-intro", "Rock intro", "classic-rock", 120, g_rock_intro, (4, 4)),
    ("golem-rock-verse", "Rock verse", "classic-rock", 120, g_rock_verse, (4, 4)),
    ("golem-rock-chorus", "Rock chorus", "classic-rock", 120, g_rock_chorus, (4, 4)),
    ("golem-rock-solo", "Rock solo", "classic-rock", 120, g_rock_solo, (4, 4)),
    ("golem-rock-fill", "Rock fill", "classic-rock", 120, g_rock_fill, (4, 4)),
    ("golem-rock-end", "Rock ending", "classic-rock", 120, g_rock_end, (4, 4)),
    # le preset metal (en fin de liste : voir plus haut)
    ("golem-metal-intro", "Metal intro", "progressive-metal", 120, g_metal_intro, (4, 4)),
    ("golem-metal-verse", "Metal verse", "progressive-metal", 120, g_metal_verse, (4, 4)),
    ("golem-metal-chorus", "Metal chorus", "progressive-metal", 120, g_metal_chorus, (4, 4)),
    ("golem-metal-breakdown", "Metal breakdown", "progressive-metal", 120, g_metal_breakdown, (4, 4)),
    ("golem-metal-solo", "Metal solo", "progressive-metal", 120, g_metal_solo, (4, 4)),
    ("golem-metal-fill", "Metal fill", "progressive-metal", 120, g_metal_fill, (4, 4)),
    ("golem-metal-end", "Metal ending", "progressive-metal", 120, g_metal_end, (4, 4)),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = {}
    for i, (gid, name, genre, tempo, fn, (num, den), *kit) in enumerate(GROOVES):
        data = smf(human(fn(), seed=i), bars=2, beats_per_bar=num, den=den, tempo=tempo)
        with open(os.path.join(OUT, gid + ".mid"), "wb") as f:
            f.write(data)
        meta[gid] = {"name": name, "genre": genre, "tempo": tempo, "bars": 2, "pack": "golem",
                     "kit": kit[0] if kit else "drums-black-pearl", "factory": True}
        print(f"{gid:26} {len(data):5} octets · {name} · {genre} · {tempo} BPM")
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
