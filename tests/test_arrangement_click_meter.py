# SPDX-License-Identifier: GPL-3.0-or-later
"""Le click suit la mesure de la section (docs/arrangement.md §3, §9) : la feuille de section promet « le click accente
le premier temps de chaque groupe » — le moteur ne s'en servait que pour calculer des durées, le click jouait la mesure
de config/click.json. Une section en 7/8 a maintenant son click en 7/8, le décompte compte dans la mesure de la section
de départ, et le stop rend au click SA mesure."""
import asyncio
import time
from pathlib import Path

from bridge import arrangement as A

ROOT = Path(__file__).resolve().parent.parent
M44 = {"beats": 4, "den": 4, "groups": []}
M78 = {"beats": 7, "den": 8, "groups": [3, 2, 2]}


def _preset(bpm=240, count_in=0, sigs=(None, {"num": 7, "den": 8, "groups": [3, 2, 2]}, None), base=None):
    secs = []
    for i, sg in enumerate(sigs):
        s = {"name": "s%d" % i, "bars": 1, "scene": "ABC"[i % 3]}
        if sg:
            s["sig"] = sg
        secs.append(s)
    pm = {"count_in": count_in, "sections": secs}
    if base is not None:
        pm["sig"] = base
    return {"id": "p", "bpm": bpm, "scenes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a", "params": pm}]}}}


def _ctl():
    ev, t = [], {}
    ctl = A.ArrangementCtl(
        apply_cue=lambda s: ev.append(("cue", s["name"], time.time())),
        click_hold=lambda on: ev.append(("hold", on, time.time())),
        click_meter=lambda m, push=True: ev.append(("meter", m, push, time.time())))
    return ctl, ev, t


def _strip(m):
    """La mesure sans l'ancre de phase (vérifiée à part, _anchors) — None reste None."""
    if m is None:
        return None
    m = {k: v for k, v in m.items() if k != "anchor"}
    return m or None


def _meters(ev):
    return [(_strip(e[1]), e[2]) for e in ev if e[0] == "meter"]


def _anchors(ev):
    return [(e[1] or {}).get("anchor") for e in ev if e[0] == "meter"]


def test_le_plan_porte_la_mesure_du_click():
    p = _preset(base={"num": 4, "den": 4})
    pl = A.plan(p)
    assert [s["click"] for s in pl] == [M44, M78, M44]
    # rien de déclaré (ni section, ni morceau) : le click garde SA mesure (ligne, config)
    pl = A.plan(_preset())
    assert pl[0]["click"] is None and pl[1]["click"] == M78 and pl[2]["click"] is None
    # un groupement qui ne fait pas le numérateur n'est pas transmis (accent sur le 1 seul)
    pl = A.plan(_preset(sigs=({"num": 7, "den": 8, "groups": [3, 3]},)))
    assert pl[0]["click"] == {"beats": 7, "den": 8, "groups": []}


def test_la_mesure_part_une_demi_pulsation_avant_la_frontiere_et_revient_au_stop():
    """240 BPM, 4/4 : section de 1 s, pulsation 0,25 s. La mesure 7/8 doit partir APRÈS le dernier temps de s0
    (0,75 s) et AVANT la frontière (1 s) : le compteur du JSFX est alors sur le « 1 » à venir."""
    async def run():
        ctl, ev, _ = _ctl()
        t0 = time.time()
        ctl.start(_preset(base={"num": 4, "den": 4}))
        assert _meters(ev) == [(M44, False)]                       # retenue au départ, sans commande à part
        assert _anchors(ev) == [0.0]                               # la mesure 1 de s0 est à 0 s du transport
        await asyncio.sleep(1.4)
        pushed = [e for e in ev if e[0] == "meter" and e[2]]
        assert pushed and _strip(pushed[0][1]) == M78
        assert pushed[0][1]["anchor"] == 1.0                       # s1 commence à 1 s (4/4 à 240)
        dt = pushed[0][3] - t0
        assert 0.80 < dt < 1.0, dt                                  # ~0,875 s (frontière − ½ pulsation)
        cue1 = next(e for e in ev if e[0] == "cue" and e[1] == "s1")
        assert pushed[0][3] < cue1[2]
        ctl.stop()
        assert _meters(ev)[-1] == (None, True)                     # le click retrouve sa mesure

    asyncio.run(run())


def test_le_decompte_compte_dans_la_mesure_de_la_section_de_depart():
    async def run():
        ctl, ev, _ = _ctl()
        ctl.start(_preset(count_in=1, sigs=({"num": 7, "den": 8, "groups": [3, 2, 2]}, None)))
        await asyncio.sleep(0.05)
        kinds = [e[0] for e in ev]
        assert kinds.index("meter") < kinds.index("hold")          # la mesure est posée AVANT le décompte
        assert _meters(ev)[0] == (M78, False)
        assert _anchors(ev)[0] == 0.0
        ctl.stop()
        assert _meters(ev)[-1] == (None, True)

    asyncio.run(run())


def test_partir_d_une_section_prend_sa_mesure():
    async def run():
        ctl, ev, _ = _ctl()
        ctl.start(_preset(base={"num": 4, "den": 4}), from_idx=1)
        assert _meters(ev)[0] == (M78, False)
        assert _anchors(ev)[0] == 1.0                              # l'ancre de la section de DÉPART, pas 0
        await asyncio.sleep(0.05)
        ctl.stop()
        assert _meters(ev)[-1] == (None, True)

    asyncio.run(run())


def test_un_saut_de_repete_envoie_la_mesure_de_la_cible_avant_la_frontiere():
    async def run():
        ctl, ev, _ = _ctl()
        t0 = time.time()
        ctl.start(_preset(base={"num": 4, "den": 4}, sigs=(None, None, {"num": 5, "den": 4})))
        await asyncio.sleep(0.2)
        assert ctl.cue(2)["ok"]                                    # s0 -> s2 (5/4) à la frontière de 1 s
        await asyncio.sleep(1.0)
        pushed = [e for e in ev if e[0] == "meter" and e[2]]
        assert _strip(pushed[0][1]) == {"beats": 5, "den": 4, "groups": []}
        assert pushed[0][1]["anchor"] == 2.0                       # la cible du saut, partie avec sa mesure
        assert 0.80 < pushed[0][3] - t0 < 1.0
        ctl.stop()

    asyncio.run(run())


def test_la_fin_du_morceau_rend_sa_mesure_au_click():
    async def run():
        ctl, ev, _ = _ctl()
        ctl.start(_preset(sigs=({"num": 3, "den": 4},)))            # une section de 0,75 s
        await asyncio.sleep(1.0)
        assert ctl.snapshot()["done"]
        assert _meters(ev)[-1] == (None, True)

    asyncio.run(run())


def test_le_bridge_branche_la_mesure_sur_le_click():
    """bridge.app ne s'importe pas ici (il ouvre le port OSC du bridge qui tourne) : on lit la source."""
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    assert "click_meter=_arr_click_meter" in src
    cfg = src[src.index("def _click_cfg"):src.index("def _click_set")]
    assert '_ARR_CLICK["meter"]' in cfg                           # toute commande click porte la mesure en cours
