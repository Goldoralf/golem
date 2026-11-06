# SPDX-License-Identifier: GPL-3.0-or-later
"""Un banc est isolé du matériel de la machine (2026-10-27) — GOLEM_NO_HW_MIDI=1 : le bridge d'un banc tourne sur la machine du rack,
et son filet amidi retombait sur le port « volt » — la vraie Whammy changeait de programme."""
from bridge import foot, midi_out


def test_sans_materiel_rien_ne_part_ni_ne_s_ouvre(monkeypatch):
    monkeypatch.setenv("GOLEM_NO_HW_MIDI", "1")
    forked = []
    monkeypatch.setattr(midi_out, "_send_amidi", lambda b: forked.append(b) or True)
    monkeypatch.setattr(midi_out, "_RT", {"out": None, "name": None})
    assert midi_out._rt_open() is None and midi_out.find_port() is None
    assert midi_out.program_change(3) is False and midi_out.control_change(11, 64) is False
    assert not forked


def test_le_pied_ne_demarre_pas(monkeypatch):
    monkeypatch.setenv("GOLEM_NO_HW_MIDI", "1")
    cls = next(c for c in vars(foot).values() if isinstance(c, type) and hasattr(c, "_find_port") and hasattr(c, "start"))
    assert cls.start(cls.__new__(cls)) is False


def test_un_banc_ne_voit_que_sa_carte_virtuelle(monkeypatch):
    """GOLEM_BENCH_CARD : le banc ne voit que sa carte, branchée — jamais la Volt du rack d'à côté comme candidate."""
    from bridge import cards
    monkeypatch.setenv("GOLEM_BENCH_CARD", "golem-bench")
    assert [c["id"] for c in cards.connected()] == ["golem-bench"]
