# SPDX-License-Identifier: GPL-3.0-or-later
"""CINQ modes d'usine depuis la fusion Show → Gig (docs/modes.md §7 bis, 2026-09-18), et ce que
chacun fait dire aux prises (§4)."""
from bridge import modes


def test_cinq_modes_dusine_et_leur_kind():
    by = {m["id"]: m for m in modes.list_modes() if m.get("_factory")}
    assert set(by) == {"pedalboard", "studio", "accompaniment", "rehearsal", "gig"}      # plus de `show`
    assert {mid: modes.take_kind(m) for mid, m in by.items()} == {
        "pedalboard": "rehearsal", "studio": "rehearsal", "accompaniment": "rehearsal",
        "rehearsal": "rehearsal", "gig": "gig"}
    # le rack n'ÉMET plus « show » — il l'accepte encore à la lecture, et une carte locale qui le
    # déclare continue de marcher : la donnée décide (docs/modes.md §7 bis.3)
    assert "show" in modes.TAKE_KINDS
    assert modes.take_kind({"id": "mon-show", "take_kind": "show"}) == "show"


def test_repli_par_lid_pour_un_mode_local_dun_autre_age():
    assert modes.take_kind({"id": "gig"}) == "gig"
    assert modes.take_kind({"id": "mon-mode-perso"}) == "rehearsal"
    assert modes.take_kind_of_id(None) == "rehearsal"
