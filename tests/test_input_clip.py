# SPDX-License-Identifier: GPL-3.0-or-later
"""ÉCRÊTAGE D'ENTRÉE (2026-09-14) : trois lectures du vumètre collées au plafond posent
`state.clip[in<n>]` (un plateau, pas une crête) ; une crête isolée ne pose rien ; un nouvel
épisode se signale une fois ; l'écran lit un âge, jamais deux horloges.
`.venv/bin/python -m pytest tests/test_input_clip.py -q`"""
from bridge import inputclip
from bridge.state import RigState


def test_plateau_oui_crete_non_episode_une_fois():
    st = RigState(); inputclip._run.clear()
    t = 1000.0
    assert not inputclip.note_level(st, 1, 1.0, t) and not inputclip.note_level(st, 1, 0.5, t) and not inputclip.note_level(st, 1, 1.0, t)
    assert st.clip == {}                                        # crêtes isolées : rien
    inputclip.note_level(st, 1, 0.2, t)                          # retour sous le plafond : la série repart de zéro
    assert [inputclip.note_level(st, 1, 0.999, t + i * 0.05) for i in range(3)] == [False, False, True]
    assert st.clip["in1"] == {"at": t + 0.1, "count": 1}
    assert [inputclip.note_level(st, 1, 1.0, t + 0.5 + i * 0.05) for i in range(3)][-1] is False   # même épisode
    assert st.clip["in1"]["count"] == 2 and "in2" not in st.clip
    assert [inputclip.note_level(st, 1, 1.0, t + 10 + i * 0.05) for i in range(3)][-1] is True     # nouvel épisode
    snap = st.snapshot()["clip"]["in1"]
    assert snap["count"] == 3 and isinstance(snap["age"], float)
