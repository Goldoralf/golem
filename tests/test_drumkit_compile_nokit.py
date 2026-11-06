# SPDX-License-Identifier: GPL-3.0-or-later
"""Un bloc batterie SANS kit compile (bloc sans moteur) — 2026-10-08 : une ligne de journal égarée lisait des
variables de la boucle des kits, absente quand aucun kit n'est choisi, et le brouillon entier était refusé."""
import os


def test_la_branche_sans_kit_ne_lit_pas_les_variables_de_la_boucle():
    src = open(os.path.join(os.path.dirname(__file__), "..", "bridge", "compile_rig.py"), encoding="utf8").read()
    i = src.index("introuvable — bloc sans moteur")
    branch = src[src.rindex("else:", 0, i):src.index("\n", i)]
    assert "{k.get(" not in branch and "tr[" not in branch
