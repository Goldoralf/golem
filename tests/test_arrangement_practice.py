# SPDX-License-Identifier: GPL-3.0-or-later
"""Les gestes de répète du moteur d'arrangement (docs/live-pages.md §6, 2026-10-15) : partir d'une section, mettre une
section en attente pour la frontière, boucler la section en cours — sans backing (horloge du serveur) et avec (transport
de Reaper, saut audio fait par golem_backing.lua)."""
import asyncio
import time

from bridge import arrangement as A


def _preset(bpm=240, n=3, count_in=0, bars=1):
    return {"id": "p", "bpm": bpm, "scenes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a", "params": {
                "count_in": count_in, "sections": [{"name": "s%d" % i, "bars": bars, "scene": "ABC"[i % 3]} for i in range(n)]}}]}}}


def _ctl(**kw):
    fired, ops = [], []
    ctl = A.ArrangementCtl(apply_cue=lambda s: fired.append((s["name"], bool(s.get("_lap")))),
                           backing_ctl=lambda op, **k: ops.append((op, k)), **kw)
    return ctl, fired, ops


def test_partir_d_une_section_decompte_et_backing_positionnee_avant():
    """§6.1 : la backing est positionnée AVANT le décompte ; à 240 BPM une mesure dure 1 s < 2 s : 2 mesures de
    décompte ; la section de départ part la première, celles d'avant jamais."""
    calls = []

    async def run():
        ctl, fired, ops = _ctl(backing=lambda on, at=0.0: (calls.append((on, at)), True)[1])
        r = ctl.start(_preset(), from_idx=2)
        assert r["ok"] and abs(r["count_in"] - 2.0) < 1e-6
        assert ops == [("pause", {}), ("seek", {"pos": 2.0})] and calls == []   # mise en pause, positionnée, pas lancée
        await asyncio.sleep(0.05)
        assert ctl.snapshot()["counting"] and ctl.snapshot()["from"] == 2
        await asyncio.sleep(2.1)
        assert calls == [(True, 2.0)] and [f[0] for f in fired] == ["s2"]
        ctl.stop()

    asyncio.run(run())


def test_un_morceau_lent_garde_une_mesure_et_le_decompte_du_morceau_l_emporte():
    ctl, _f, _o = _ctl()

    async def run():
        r = ctl.start(_preset(bpm=60), from_idx=0)                          # 1 mesure = 4 s : une seule
        assert abs(r["count_in"] - 4.0) < 1e-6
        ctl.stop()
        r = ctl.start(_preset(bpm=60, count_in=2), from_idx=1)             # le morceau en demande 2
        assert abs(r["count_in"] - 8.0) < 1e-6
        ctl.stop()
        assert ctl.start(_preset(), from_idx=9)["ok"] is False

    asyncio.run(run())


def test_la_boucle_rejoue_la_section_et_ne_laisse_pas_passer_la_suivante():
    async def run():
        ctl, fired, _ops = _ctl()
        ctl.start(_preset())                                               # pas de décompte, 1 s par section
        await asyncio.sleep(0.2)
        assert ctl.set_loop(True)["ok"]
        await asyncio.sleep(2.1)                                           # deux tours de s0
        names = [f[0] for f in fired]
        assert names == ["s0", "s0", "s0"] and ctl.snapshot()["loops"] == 2
        assert all(lap for _n, lap in fired[1:])                           # un tour = une réapplication « _lap »
        ctl.set_loop(False)
        await asyncio.sleep(1.0)
        assert [f[0] for f in fired][-1] == "s1"
        ctl.stop()

    asyncio.run(run())


def test_une_section_en_attente_part_a_la_frontiere_puis_le_morceau_reprend_son_cours():
    async def run():
        ctl, fired, _ops = _ctl()
        ctl.start(_preset(n=4))
        await asyncio.sleep(1.2)                                           # dans s1
        assert ctl.cue(0)["ok"] and ctl.snapshot()["cue"] == 0
        await asyncio.sleep(0.9)                                           # frontière de s1 -> s0 (pas s2)
        assert [f[0] for f in fired] == ["s0", "s1", "s0"] and ctl.snapshot()["cue"] is None
        await asyncio.sleep(1.0)
        assert [f[0] for f in fired][-1] == "s1"                           # puis le cours normal
        ctl.stop()

    asyncio.run(run())


def test_la_mise_en_attente_est_verrouillee_un_temps_avant_la_frontiere():
    async def run():
        ctl, _fired, _ops = _ctl()
        ctl.start(_preset())
        await asyncio.sleep(0.85)                                          # 0,15 s < un temps (0,25 s)
        r = ctl.cue(2)
        assert r["ok"] is False and r.get("locked")
        ctl.stop()
        assert ctl.cue(1)["ok"] is False                                   # à l'arrêt : c'est `from` qui sert

    asyncio.run(run())


def test_avec_la_backing_le_saut_est_arme_dans_reaper_et_le_moteur_n_attend_pas_le_transport():
    """§6.2 : la mise en attente arme le saut dans Reaper (boucle native vers l'arrière) ; à la frontière le moteur
    applique la cible LUI-MÊME, même si le transport publie encore une position d'avant le saut."""
    tr = {"present": True, "playing": True, "paused": False, "pos": 0.0, "at": 0.0}

    async def run():
        ctl, fired, ops = _ctl(backing=lambda on, at=0.0: True, transport=lambda: dict(tr))
        ctl.start(_preset(n=4))
        t0 = time.time()
        await asyncio.sleep(0.05)
        tr.update(pos=1.2, at=time.time())                                 # dans s1
        await asyncio.sleep(0.1)
        assert ctl.cue(0)["ok"]
        assert ("jump", {"at": 2.0, "to": 0.0}) in ops
        # le transport « oublie » de publier le saut : il dit encore 1,9 s quand la frontière passe
        while time.time() - t0 < 2.0:
            tr.update(pos=1.9, at=time.time() - 0.05)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.15)
        names = [f[0] for f in fired]
        assert names[-1] == "s0" and "s2" not in names                     # jamais la section d'après
        tr.update(pos=0.3, at=time.time())                                 # le saut est confirmé
        await asyncio.sleep(0.5)
        assert [f[0] for f in fired][-1] == "s0"
        ctl.stop()
        assert ops[-1][0] == "loop_off" or ("loop_off", {}) not in ops     # rien d'armé : rien à lever

    asyncio.run(run())


def test_un_saut_rate_se_recale_sur_le_transport():
    tr = {"present": True, "playing": True, "paused": False, "pos": 0.0, "at": 0.0}

    async def run():
        ctl, fired, _ops = _ctl(backing=lambda on, at=0.0: True, transport=lambda: dict(tr))
        ctl.start(_preset(n=4))
        await asyncio.sleep(0.05)
        tr.update(pos=1.2, at=time.time())
        await asyncio.sleep(0.1)
        ctl.cue(0)
        await asyncio.sleep(0.8)                                           # la frontière passe : le moteur saute
        assert [f[0] for f in fired][-1] == "s0"
        tr.update(pos=2.6, at=time.time())                                 # mais Reaper a continué : il est dans s2
        # bornée, pas fixe : le moteur relit le transport toutes les 50 ms, mais un runner CI chargé (windows-2025,
        # 2026-10-19) a mis plus de 0,3 s à le voir — ce que le test garde, c'est le recalage, pas sa vitesse
        for _ in range(60):
            if [f[0] for f in fired][-1] == "s2":
                break
            await asyncio.sleep(0.05)
        assert [f[0] for f in fired][-1] == "s2"
        ctl.stop()

    asyncio.run(run())


def test_le_stop_leve_la_boucle_et_remet_tout_a_zero():
    async def run():
        ctl, _fired, ops = _ctl(backing=lambda on, at=0.0: True, transport=lambda: None)
        ctl.start(_preset())
        await asyncio.sleep(0.1)
        ctl._follow = True                                                 # la backing est suivie
        assert ctl.set_loop(True)["ok"] and ("loop", {"a": 0.0, "b": 1.0}) in ops
        ctl.stop()
        snap = ctl.snapshot()
        assert ("loop_off", {}) in ops and snap["loop"] is False and snap["cue"] is None and snap["loops"] == 0

    asyncio.run(run())


def test_reaper_publie_le_saut_avant_la_frontiere_du_moteur_un_seul_saut():
    """Relecture de l'ingénieur du son : le Lua publie le rebouclage tout de suite ; le moteur peut le voir AVANT
    d'atteindre lui-même la frontière. C'est le saut armé : il est appliqué une fois, le cue est consommé, et la
    section cible n'est pas re-sautée à sa fin."""
    tr = {"present": True, "playing": True, "paused": False, "pos": 0.0, "at": 0.0}

    async def run():
        ctl, fired, ops = _ctl(backing=lambda on, at=0.0: True, transport=lambda: dict(tr))
        ctl.start(_preset(n=4))
        await asyncio.sleep(0.05)
        tr.update(pos=1.2, at=time.time())
        await asyncio.sleep(0.1)
        assert ctl.cue(0)["ok"]
        tr.update(pos=1.85, at=time.time())                             # le moteur est encore dans s1
        await asyncio.sleep(0.06)
        tr.update(pos=0.02, at=time.time())                             # Reaper a déjà rebouclé
        await asyncio.sleep(0.3)
        names = [f[0] for f in fired]
        assert names[-1] == "s0" and names.count("s0") == 2 and ctl.snapshot()["cue"] is None
        await asyncio.sleep(1.0)                                        # fin de s0 : on continue, pas de nouveau saut
        assert [f[0] for f in fired][-1] == "s1" and [f[0] for f in fired].count("s0") == 2
        ctl.stop()

    asyncio.run(run())


def test_un_seek_dans_la_section_rearme_le_saut():
    """golem_backing lève le saut armé à tout seek (audit 2026-10-15) : un seek qui reste dans la section le fait
    réarmer par le moteur, sinon la scène sauterait seule à la frontière."""
    tr = {"present": True, "playing": True, "paused": False, "pos": 0.0, "at": 0.0}

    async def run():
        ctl, fired, ops = _ctl(backing=lambda on, at=0.0: True, transport=lambda: dict(tr))
        ctl.start(_preset(bpm=60, n=4))                                    # 4 s la section
        await asyncio.sleep(0.05)
        tr.update(pos=4.5, at=time.time())                                 # dans s1
        await asyncio.sleep(0.15)
        assert ctl.cue(0)["ok"]
        n = sum(1 for o in ops if o[0] == "jump")
        tr.update(pos=5.5, at=time.time())                                 # seek EN AVANT, toujours dans s1
        await asyncio.sleep(0.2)
        assert sum(1 for o in ops if o[0] == "jump") == n + 1
        assert ops[-1] == ("jump", {"at": 8.0, "to": 0.0})
        assert ctl._cue == 0
        ctl.stop()

    asyncio.run(run())
