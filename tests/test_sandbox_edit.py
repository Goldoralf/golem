# SPDX-License-Identifier: GPL-3.0-or-later
"""Deux écrans n'éditent pas le même brouillon en silence (docs/devices-people.md, lot D).
`.venv/bin/python -m pytest tests/test_sandbox_edit.py -q`"""
from bridge import sandbox_edit as E


def test_le_meme_editeur_ecrit_toujours():
    m = {"edit_rev": 7, "editor": "kiosk"}
    assert E.conflict(m, "kiosk", None) is None and E.conflict(m, "kiosk", 2) is None


def test_un_autre_ecran_parti_d_une_revision_depassee_est_refuse():
    m = {"edit_rev": 7, "editor": "kiosk", "editor_name": "the rack screen"}
    assert E.conflict(m, "window", 6) == {"rev": 7, "by": "the rack screen"}
    assert E.conflict(m, "window", None) == {"rev": 7, "by": "the rack screen"}   # base inconnue : prudence
    assert E.conflict(m, "window", 7) is None                                       # il a vu la dernière
    assert E.conflict(m, "window", 3, force=True) is None                           # « Keep mine », ouvrir un preset


def test_un_brouillon_sans_meta_ne_bloque_personne():
    assert E.conflict({}, "window", None) is None
    assert E.conflict({"edit_rev": 3}, "window", 0) is None          # écrit par un ancien client ou par golem.fm


def test_apres_ecriture_la_revision_avance_et_nomme_l_editeur():
    m = E.after_write({"edit_rev": 7, "editor": "kiosk"}, "tablet", "Rack screen")
    assert m == {"edit_rev": 8, "editor": "tablet", "editor_name": "Rack screen"}
    assert E.after_write(m, None, None) == {"edit_rev": 9, "editor": "tablet", "editor_name": "Rack screen"}
