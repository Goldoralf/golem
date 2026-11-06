# SPDX-License-Identifier: GPL-3.0-or-later
"""Le REC et le morceau (docs/devices-people.md, lot F — décision) : « Record with the song » en
répète lance la prise avec le morceau et l'arrête avec lui ; en show la prise part avec la PREMIÈRE
chanson et ne s'arrête pas ; l'arrangement publie ses parties et qui l'a lancé.
`.venv/bin/python -m pytest tests/test_song_rec.py -q`"""
import asyncio

from bridge import arrangement as A


def _preset():
    return {"id": "p1", "bpm": 120, "scenes": [{"id": "A"}, {"id": "B"}],
            "config": {"arr": {"blocks": [{"type": "arrangement", "id": "arr", "params": {
                "advance": "foot", "sig": {"num": 4, "den": 4},
                "sections": [{"name": "intro", "bars": 4, "scene": "A"}, {"name": "verse", "bars": 8, "scene": "B"}]}}]}}}


def test_le_controleur_dit_qui_lance_et_publie_ses_parties_et_signale_debut_et_fin():
    events = []

    async def run():
        ctl = A.ArrangementCtl(apply_cue=lambda sec: None, on_song=lambda ev, info: events.append((ev, info)))
        r = ctl.start(_preset(), by="Sam")
        assert r["ok"]
        await asyncio.sleep(0.01)
        snap = ctl.snapshot()
        assert snap["by"] == "Sam" and [p["name"] for p in snap["parts"]] == ["intro", "verse"]
        # depuis le 2026-10-15 (docs/live-pages.md) une partie dit aussi où elle commence et sa métrique
        assert snap["parts"][1] == {"name": "verse", "bars": 8, "scene": "B", "dur": 16.0, "at": 8.0, "num": 4, "den": 4}
        ctl.stop()
    asyncio.run(run())
    assert [e[0] for e in events] == ["start", "end"] and events[0][1]["by"] == "Sam"


def test_un_stop_sans_morceau_ne_signale_rien():
    events = []
    ctl = A.ArrangementCtl(apply_cue=lambda sec: None, on_song=lambda ev, info: events.append(ev))
    ctl.stop()
    assert events == []


def test_la_regle_du_rec():
    from bridge.song_rec import decide
    # rec_scope "song" (répète) : la case lance, la fin arrête
    assert decide("start", asked=True, set_scope=False, first_line=False, recording=False, with_song=False) == ("start", True)
    assert decide("end", asked=False, set_scope=False, first_line=False, recording=True, with_song=True) == ("stop", False)
    assert decide("start", asked=False, set_scope=False, first_line=False, recording=False, with_song=False) == (None, False)
    # rec_scope "set" (Gig) : la première chanson lance et la prise ne s'arrête pas ; déjà lancée : rien
    assert decide("start", asked=False, set_scope=True, first_line=True, recording=False, with_song=False) == ("start", False)
    assert decide("end", asked=False, set_scope=True, first_line=False, recording=True, with_song=False) == (None, False)
    assert decide("start", asked=False, set_scope=True, first_line=True, recording=True, with_song=False) == (None, False)
    # set, chanson 4, REC arrêté exprès : il ne repart pas ; et la case ne vaut pas en « set »
    assert decide("start", asked=True, set_scope=True, first_line=False, recording=False, with_song=False) == (None, False)
