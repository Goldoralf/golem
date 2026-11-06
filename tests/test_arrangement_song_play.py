# SPDX-License-Identifier: GPL-3.0-or-later
"""▶ Play depuis la page Songs (2026-09-24) : l'arrangement joué est celui de la CHANSON, sans ligne de
setlist. `recall.effective_preset` relit la fiche quand l'état porte `band_song` sans `line`."""
import json

from bridge import recall, songs as S
from bridge.state import state


def test_la_fiche_d_une_chanson_sans_ligne_est_jouee(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "SONGS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(S, "DIR", str(tmp_path), raising=False)
    doc = {"id": "rs:test", "rev": 1, "title": "T", "kind": "cover", "born": "rack",
           "sheet": {"preset": "p1", "bpm": 91, "arrangement": {"type": "arrangement", "id": "arr-song",
                     "params": {"advance": "bars", "count_in": 1, "sections": [{"name": "intro", "bars": 2, "scene": "A"}]}}}}
    monkeypatch.setattr(S, "load", lambda sid: doc if sid == "rs:test" else None)
    p = {"id": "p1", "name": "P", "bpm": 120, "config": {"gen": {"blocks": []}, "rec": {"blocks": []}}, "lanes": [], "scenes": [{"id": "A"}]}
    monkeypatch.setattr(state, "song", recall.song_of_song(doc, "p1"), raising=False)
    eff = recall.effective_preset(p)
    blocks = ((eff.get("config") or {}).get("arr") or {}).get("blocks") or []
    assert blocks and blocks[0]["params"]["sections"][0]["scene"] == "A" and blocks[0]["params"]["count_in"] == 1
    assert eff["bpm"] == 91                                        # le tempo de la fiche, pas celui du preset (120)
    assert state.song["band_song"] == "rs:test" and state.song["line"] is None and state.song["bpm"] == 91
    # un autre preset chargé : la chanson ne s'applique pas à lui
    eff2 = recall.effective_preset({**p, "id": "p2"})
    assert ((eff2.get("config") or {}).get("arr") or {}).get("blocks") == []


def test_le_decompte_publie_ses_bornes_et_live_view_n_a_pas_de_defaut_cache():
    """§22 bis : le HUD compte les temps sur count_from/count_to ; /live décide du défaut (None), la chanson dit
    Timeline ou Pedalboard."""
    from bridge import arrangement as A
    import time as _t
    ctl = A.ArrangementCtl(apply_cue=lambda s: None)
    snap = ctl.snapshot()
    assert snap["live_view"] is None and snap["count_from"] is None and snap["count_to"] is None
    ctl._counting, ctl._c0, ctl._count_s = True, 100.0, 2.5
    snap = ctl.snapshot()
    assert snap["counting"] is True and snap["count_from"] == 100.0 and snap["count_to"] == 102.5
    p = {"id": "p", "bpm": 120, "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a", "params": {"live_view": "Pedalboard", "sections": [{"name": "x", "bars": 1}]}}]}}}
    ctl.load(p)
    assert ctl.snapshot()["live_view"] == "Pedalboard"


def test_la_backing_part_apres_le_decompte_et_s_arrete_au_stop():
    """§8 « Départ = lancer le morceau » + §13.3 : la backing part au premier temps de la section 1 (APRÈS
    le décompte) et le ■ Stop l'arrête — seulement si c'est le morceau qui l'a lancée."""
    import asyncio
    from bridge import arrangement as A
    calls = []
    p = {"id": "p", "bpm": 120, "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a",
         "params": {"count_in": 1, "sections": [{"name": "x", "bars": 4}]}}]}}}

    async def run(loaded):
        calls.clear()
        ctl = A.ArrangementCtl(apply_cue=lambda s: None, backing=lambda on: (calls.append(on), loaded)[1])
        assert ctl.start(p)["ok"]
        await asyncio.sleep(0.2)
        assert calls == [] and ctl.snapshot()["counting"]            # pendant le décompte : rien
        await asyncio.sleep(2.1)                                     # 1 mesure de 4/4 à 120 = 2 s
        assert calls == [True] and ctl.snapshot()["backing"] is loaded
        ctl.stop()
        return list(calls), ctl.snapshot()["backing"]

    assert asyncio.run(run(True)) == ([True, False], False)
    assert asyncio.run(run(False)) == ([True], False)                # pas de backing lancée : on n'arrête rien


def _ctl_avec_transport(tr):
    from bridge import arrangement as A
    fired = []
    ctl = A.ArrangementCtl(apply_cue=lambda s: fired.append(s["name"]), backing=lambda on: True,
                           transport=lambda: dict(tr))
    p = {"id": "p", "bpm": 240, "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a",
         "params": {"count_in": 0, "sections": [{"name": n, "bars": 1} for n in ("a", "b", "c")]}}]}}}
    return ctl, p, fired                                             # 1 mesure de 4/4 à 240 = 1 s


def test_l_horloge_est_le_transport_et_une_pause_retient_l_arrangement():
    """§5 lot 2 : avec une backing, les frontières suivent SA position, pas l'horloge du serveur."""
    import asyncio, time
    tr = {"present": True, "playing": False, "paused": False, "pos": 0.0, "at": 0.0}

    async def run():
        ctl, p, fired = _ctl_avec_transport(tr)
        ctl.start(p)
        await asyncio.sleep(0.05)
        assert fired == ["a"] and ctl.snapshot()["clock"] == "server"   # pas encore d'état frais
        # le transport publie : il n'est qu'à 0,2 s alors que le serveur compte déjà plus (démarrage lent)
        tr.update(playing=True, pos=0.2, at=time.time() + 0.0)
        await asyncio.sleep(0.6)                                         # transport ≈ 0,8 s : toujours « a »
        assert fired == ["a"] and ctl.snapshot()["clock"] == "transport"
        await asyncio.sleep(0.4)                                         # ≈ 1,2 s : « b »
        assert fired == ["a", "b"]
        # PAUSE à 1,5 s : on attend bien au-delà de la frontière de « c » (2 s) — rien ne part
        await asyncio.sleep(0.3)
        tr.update(playing=False, paused=True, pos=1.5, at=time.time())
        await asyncio.sleep(1.0)
        assert fired == ["a", "b"]
        tr.update(playing=True, paused=False, pos=1.5, at=time.time())  # reprise
        await asyncio.sleep(0.7)
        assert fired == ["a", "b", "c"]
        ctl.stop()

    asyncio.run(run())


def test_un_retour_en_arriere_du_transport_recale_la_partie():
    import asyncio, time
    tr = {"present": True, "playing": True, "paused": False, "pos": 0.0, "at": 0.0}

    async def run():
        ctl, p, fired = _ctl_avec_transport(tr)
        ctl.start(p)
        await asyncio.sleep(0.02)
        tr.update(pos=1.3, at=time.time())                              # on est dans « b »
        await asyncio.sleep(0.15)
        assert fired[-1] == "b"
        tr.update(pos=0.1, at=time.time())                              # double-tap restart : retour au début
        await asyncio.sleep(0.15)
        assert fired[-1] == "a" and ctl.snapshot()["index"] == 0
        await asyncio.sleep(1.0)                                        # puis ça repart normalement
        assert fired[-1] == "b"
        ctl.stop()

    asyncio.run(run())


def test_le_click_part_avec_le_morceau_et_la_fin_tombe_a_la_fin_de_la_derniere_partie():
    """§8 : le click part au premier temps (après le décompte) et se tait à la fin du morceau. La fin = la fin
    de la DERNIÈRE partie, plus son début : une prise « with the song » s'arrêtait au début de l'outro."""
    import asyncio
    from bridge import arrangement as A
    ev, songs = [], []
    p = {"id": "p", "bpm": 240, "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a",
         "params": {"count_in": 1, "sections": [{"name": "a", "bars": 1}, {"name": "b", "bars": 1}]}}]}}}

    async def run():
        ctl = A.ArrangementCtl(apply_cue=lambda s: None, click_song=lambda *a: ev.append(a[0]),
                               on_song=lambda e, info: songs.append(e))
        ctl.start(p)
        assert ev == ["start"]
        await asyncio.sleep(1.1)                                 # décompte : 1 mesure à 240 = 1 s
        assert ev == ["start", "go"]
        await asyncio.sleep(1.2)                                 # « b » a commencé (t = 1 s) : pas fini
        assert ctl.snapshot()["name"] == "b" and not ctl.snapshot()["done"] and songs == ["start"]
        await asyncio.sleep(1.0)                                 # fin de « b » (t = 2 s)
        assert ctl.snapshot()["done"] and songs == ["start", "end"] and ev == ["start", "go", "stop"]

    asyncio.run(run())


def test_un_arret_pendant_le_decompte_rend_le_click():
    import asyncio
    from bridge import arrangement as A
    ev = []
    p = {"id": "p", "bpm": 120, "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a",
         "params": {"count_in": 2, "sections": [{"name": "a", "bars": 1}]}}]}}}

    async def run():
        ctl = A.ArrangementCtl(apply_cue=lambda s: None, click_song=lambda *a: ev.append(a[0]))
        ctl.start(p)
        await asyncio.sleep(0.2)
        ctl.stop()
        assert ev == ["start", "cancel"]

    asyncio.run(run())


def test_les_cases_de_la_chanson_decident_ce_qui_part():
    """docs/arrangement.md : `params.starts` — False coupe, True force, absent = comportement d'avant."""
    import asyncio
    from bridge import arrangement as A

    def preset(starts):
        prm = {"count_in": 0, "sections": [{"name": "a", "bars": 1}]}
        if starts is not None:
            prm["starts"] = starts
        return {"id": "p", "bpm": 240, "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a", "params": prm}]}}}

    assert A.starts_of(preset(None)) == {"backing": None, "click": None, "rec": None, "sample": None, "drums": None}
    assert A.starts_of(preset({"backing": False, "click": True}))["backing"] is False

    async def run(starts):
        bk, clk, songs = [], [], []
        ctl = A.ArrangementCtl(apply_cue=lambda s: None, backing=lambda on: (bk.append(on), True)[1],
                               click_song=lambda ev, *a: clk.append((ev, *a)),
                               on_song=lambda e, info: songs.append((e, info.get("record"))))
        ctl.start(preset(starts))
        await asyncio.sleep(0.1)
        ctl.stop()
        return bk, clk, songs

    bk, clk, songs = asyncio.run(run({"backing": False, "click": False, "rec": True}))
    assert bk == [] and ("go", False) in clk and songs[0] == ("start", True)
    bk, clk, songs = asyncio.run(run(None))                       # rien de coché : comme avant
    assert bk == [True, False] and ("go", None) in clk and songs[0] == ("start", None)
