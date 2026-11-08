#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Les PARTITIONS des DI de basse (docs/preset-preview.md §1) : trois lignes à faire jouer par une basse virtuelle
(EZbass…) puis à exporter en WAV sec — ce WAV est la DI que les patchs de basse re-ampent. Le MIDI n'est qu'un
moyen : la référence livrée reste `bass/<bucket>.wav`. Composées ICI, à nous — aucune ligne reconnaissable.

Règles communes des DI (docs/archive/di-refs-recording.md) : en MI, quatre mesures, la dernière note LAISSÉE
SONNER (la fin du fichier tombe deux mesures après le début de la tenue : les queues de reverb et de delay
s'entendent). Basse 4 cordes : mi grave = 28 (E1), sol à vide = 43. Monophonique : aucune note ne chevauche la
suivante (une basse virtuelle lirait un chevauchement comme un legato ou un slide).

    finger  100 bpm  doigts : fondamentale-quinte-octave, notes fantômes, approches chromatiques, mi grave tenu
    pick    120 bpm  médiator : croches franches accentuées, montée chromatique, mi tenu
    slap    100 bpm  slap : pouce sur les fondamentales graves, pop sur les octaves (≥ 38), notes mortes, mi tenu

Le jeu (doigts, médiator, slap) se choisit DANS l'instrument : ces fichiers ne portent aucun keyswitch.

    ./tools/make-bass-di-midi.py [--out DOSSIER]    # défaut : library/di-refs/bass/sources/<bucket>.mid
"""
import argparse
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# l'écriture SMF est celle des références MIDI (même format, même PPQ)
_spec = importlib.util.spec_from_file_location("make_midi_refs", os.path.join(HERE, "make-midi-refs.py"))
_refs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_refs)
smf = _refs.smf

E1, F1, Fs1, G1, Gs1, A1, B1 = 28, 29, 30, 31, 32, 33, 35
C2, Cs2, D2, Ds2, E2, Fs2, G2, Gs2, A2, B2 = 36, 37, 38, 39, 40, 42, 43, 44, 45, 47
Cs3 = 49

# la tenue finale : du temps 16 jusqu'à un souffle avant la fin des six mesures
HOLD = 7.9


def finger():
    """Groove aux doigts sur I-vi-IV-V (mi, do#m, la, si) : chaque mesure pose sa fondamentale, monte quinte et
    octave, glisse une note fantôme, et rejoint la suivante par une approche ; la quatrième mesure descend en
    doubles croches vers le mi grave tenu."""
    g = 30                                                                   # vélocité d'une note fantôme
    n = [
        # mi
        (0, 0.7, E1, 100), (0.75, 0.2, E1, g), (1, 0.45, B1, 88), (1.5, 0.45, E2, 92),
        (2, 0.7, E1, 98), (2.75, 0.2, E2, g), (3, 0.45, B1, 86), (3.5, 0.45, C2, 80),
        # do# mineur
        (4, 0.7, Cs2, 100), (4.75, 0.2, Cs2, g), (5, 0.45, Gs2, 86), (5.5, 0.45, Cs3, 90),
        (6, 0.7, Cs2, 96), (6.75, 0.2, Gs2, g), (7, 0.45, B1, 84), (7.5, 0.45, 34, 80),          # si, sib → la
        # la
        (8, 0.7, A1, 100), (8.75, 0.2, A1, g), (9, 0.45, E2, 88), (9.5, 0.45, A2, 92),
        (10, 0.45, Gs2, 84), (10.5, 0.45, E2, 82), (11, 0.45, Cs2, 86), (11.5, 0.45, 34, 82),    # sib → si
        # si, puis la descente
        (12, 0.7, B1, 100), (12.75, 0.2, B1, g), (13, 0.45, Fs2, 88), (13.5, 0.45, B2, 92),
        (14, 0.45, A2, 86), (14.5, 0.22, Gs2, 84), (14.75, 0.22, Fs2, 80),
        (15, 0.22, E2, 86), (15.25, 0.22, Ds2, 82), (15.5, 0.22, Cs2, 84), (15.75, 0.22, B1, 88),
        (16, HOLD, E1, 104),
    ]
    return smf(n, 6, 100)


def pick():
    """Rock au médiator : croches régulières, temps accentués, contretemps un peu moins forts ; mi, sol-la, mi
    avec un trait quinte-septième-octave, do-ré, puis une montée chromatique en doubles croches vers le mi tenu."""
    bars = [
        [E1, E1, E1, E1, E1, E1, E2, D2],
        [G1, G1, G1, G1, A1, A1, A1, A1],
        [E1, E1, E1, E1, B1, B1, D2, E2],
        [C2, C2, C2, C2, D2, D2],
    ]
    n = []
    for b, notes in enumerate(bars):
        for i, p in enumerate(notes):
            t = b * 4 + i * 0.5
            v = 110 if i % 2 == 0 else 92
            if i == 0:
                v = 118                                                      # le premier temps de la mesure
            n.append((t, 0.42, p, v))
    n += [(15 + i * 0.25, 0.22, p, 100 + i * 4) for i, p in enumerate((B1, Cs2, D2, Ds2))]
    n.append((16, HOLD, E2, 116))
    return smf(n, 6, 120)


def slap():
    """Funk en slap (mi pentatonique) : pouce (T) sur les fondamentales graves, pop (P) sur les octaves et les
    cordes aiguës, notes mortes (G) entre les deux ; mi, mi avec un trait montant, la, si qui redescend
    chromatiquement vers le mi grave tenu au pouce."""
    T, P, G = (0.22, 108), (0.2, 115), (0.12, 28)                            # durée, vélocité par geste

    def bar(t0, seq):
        return [(t0 + t, d, p, v) for t, p, (d, v) in seq]

    n = []
    n += bar(0, [(0, E1, T), (0.5, E1, G), (0.75, E2, P), (1, E1, G), (1.25, E1, T), (1.5, E2, P),
                 (2, G1, T), (2.25, A1, T), (2.5, G2, P), (3, E1, T), (3.5, D2, P), (3.75, E2, P)])
    n += bar(4, [(0, E1, T), (0.5, E1, G), (0.75, E2, P), (1, E1, G), (1.25, E1, T), (1.5, E2, P),
                 (2, G1, T), (2.5, E2, P), (2.75, E1, G), (3, B1, T), (3.25, D2, P), (3.5, E2, P), (3.75, G2, P)])
    n += bar(8, [(0, A1, T), (0.5, A1, G), (0.75, A2, P), (1, A1, G), (1.25, A1, T), (1.5, A2, P),
                 (2, C2, T), (2.5, D2, T), (2.75, A2, P), (3, A1, T), (3.5, G2, P), (3.75, A2, P)])
    n += bar(12, [(0, B1, T), (0.5, B1, G), (0.75, B2, P), (1, B1, G), (1.25, B1, T), (1.5, B2, P),
                  (2, D2, T), (2.5, E2, P), (2.75, D2, T), (3, B1, T), (3.25, A1, T), (3.5, G1, T), (3.75, F1, T)])
    n.append((16, HOLD, E1, 112))
    return smf(n, 6, 100)


PARTS = {"finger": finger, "pick": pick, "slap": slap}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "library", "di-refs", "bass", "sources"))
    out = ap.parse_args().out
    os.makedirs(out, exist_ok=True)
    for name, fn in PARTS.items():
        path = os.path.join(out, name + ".mid")
        with open(path, "wb") as f:
            f.write(fn())
        print(f"  ✓ {path}")


if __name__ == "__main__":
    main()
