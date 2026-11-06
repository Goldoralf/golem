# SPDX-License-Identifier: GPL-3.0-or-later
"""La boîte à rythmes pilotée par l'arrangement (docs/arrangement.md §6, 2026-10-20) : elle part au premier temps sur
le groove de sa section, chaque section choisit le sien — envoyé pendant la DERNIÈRE PULSATION pour que le JSFX (qui
quantifie à la mesure) bascule pile sur la frontière —, « stop » la coupe, et elle s'arrête avec le morceau. Une seule
forme : celle de l'arrangement. `.venv/bin/python -m pytest tests/test_arrangement_drums.py -q`"""
import asyncio
import time

from bridge import arrangement as A


def _preset(drums=(None, 1, None, "stop", 0), bpm=240, starts=None, with_block=True):
    secs = [{"name": "s%d" % i, "bars": 1, "scene": "A", **({"drums": d} if d is not None else {})} for i, d in enumerate(drums)]
    pm = {"sections": secs, **({"starts": starts} if starts else {})}
    blocks = [{"type": "arrangement", "id": "a", "params": pm}]
    if with_block:
        blocks.append({"type": "drums", "id": "dm", "params": {"patterns": ["a.mid", "b.mid"]}})
    return {"id": "p", "bpm": bpm, "scenes": [{"id": "A"}], "config": {"arr": {"blocks": blocks}}}


def _ctl(present=True):
    ev = []

    def drums(op, idx=None):
        ev.append((op, idx, time.time()))
        return present
    ctl = A.ArrangementCtl(apply_cue=lambda s: ev.append(("cue", s["name"], time.time())), drums=drums)
    return ctl, ev


def test_le_plan_porte_le_groove_de_chaque_section():
    pl = A.plan(_preset())
    assert [s["drums"] for s in pl] == [None, 1, None, "stop", 0]
    # une section sans consigne garde le groove d'avant ; sans aucune consigne avant, le premier motif
    assert [A.drums_at(pl, k) for k in range(5)] == [0, 1, 1, "stop", 0]
    assert A.starts_of(_preset(starts={"drums": False}))["drums"] is False
    assert A.starts_of(_preset())["drums"] is None


def test_la_batterie_part_au_premier_temps_change_avant_la_frontiere_et_s_arrete_avec_le_morceau():
    """240 BPM, 4/4 : sections de 1 s, pulsation 0,25 s. s0 groove 0 ; s1 groove 1 envoyé entre 0,75 et 1 s ; s3 « stop »
    à la frontière (3 s) ; s4 relance le groove 0 ; la fin du morceau (5 s) l'arrête."""
    async def run():
        ctl, ev = _ctl()
        t0 = time.time()
        ctl.start(_preset())
        await asyncio.sleep(5.4)
        ops = [(e[0], e[1]) for e in ev if e[0] != "cue"]
        assert ops == [("play", 0), ("pattern", 1), ("stop", None), ("play", 0), ("stop", None)], ops
        play0, pat1 = ev[0], next(e for e in ev if e[0] == "pattern")
        assert play0[2] - t0 < 0.15                                  # au premier temps (pas de décompte)
        assert 0.70 < pat1[2] - t0 < 1.0, pat1[2] - t0               # ~0,875 s : frontière − ½ pulsation
        cue1 = next(e for e in ev if e[0] == "cue" and e[1] == "s1")
        assert pat1[2] < cue1[2], "le groove part AVANT la frontière, pas après"

    asyncio.run(run())


def test_stop_coupe_la_batterie_qu_il_a_lancee():
    async def run():
        ctl, ev = _ctl()
        ctl.start(_preset())
        await asyncio.sleep(0.3)
        ctl.stop()
        assert [(e[0], e[1]) for e in ev if e[0] != "cue"] == [("play", 0), ("stop", None)]

    asyncio.run(run())


def test_case_decochee_ou_preset_sans_boite_a_rythmes_rien_ne_part():
    async def run():
        ctl, ev = _ctl()
        ctl.start(_preset(starts={"drums": False}))
        await asyncio.sleep(1.3)
        ctl.stop()
        assert not [e for e in ev if e[0] != "cue"], "case Drums décochée : la batterie ne part pas"
        ctl2, ev2 = _ctl(present=False)
        ctl2.start(_preset())
        await asyncio.sleep(1.3)
        ctl2.stop()
        assert [(e[0], e[1]) for e in ev2 if e[0] != "cue"] == [("play", 0)], "sans boîte à rythmes : un essai, puis plus rien"

    asyncio.run(run())


def test_le_bridge_branche_la_batterie_sur_l_arrangement():
    import inspect
    from bridge import app
    assert "drums=_arr_drums" in inspect.getsource(app)
