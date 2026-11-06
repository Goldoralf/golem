# SPDX-License-Identifier: GPL-3.0-or-later
"""L'auto-save d'un patch accepte l'id d'une LANE v2, pas seulement un royaume (le mainteneur, patch 1983,
2026-09-14) : un patch essayé depuis golem.fm vit sur la lane `guitar-try` — le guard de la route ne
connaissait que guitar/voice/keys, chaque enregistrement rendait 400 en silence, et une scène
supprimée à l'écran n'atteignait jamais le fichier. `.venv/bin/python -m pytest tests/test_patch_save_lane.py -q`"""
import asyncio

from bridge import patches as P, routes_patches as R


def _doc(lane_id="guitar-try"):
    return {"id": "sandbox-try", "name": "1983", "lanes_v": 2,
            "lanes": [{"id": lane_id, "role": "guitar", "name": "1983", "midi": False, "out_sel": "1-2",
                       "chain": {"pre": [{"id": "amp-1", "type": "amp-nam"}], "split": None, "post": []}}],
            "scenes": [{"id": "A"}, {"id": "B"}],
            "__patch": {"realm": lane_id, "id": "1983", "role": "guitar"}}


def test_la_lane_v2_du_banc_est_acceptee(monkeypatch):
    got = {}
    monkeypatch.setattr(P, "save_patch", lambda pid, preset, lane: got.update(pid=pid, lane=lane) or {"id": pid})
    monkeypatch.setattr(R, "_pushed", lambda r: r)
    r = asyncio.run(R.api_save("1983", {"preset": _doc(), "lane": "guitar-try"}))
    assert isinstance(r, dict) and r["ok"] is True and got == {"pid": "1983", "lane": "guitar-try"}


def test_un_royaume_passe_toujours_et_un_inconnu_est_refuse(monkeypatch):
    monkeypatch.setattr(P, "save_patch", lambda pid, preset, lane: {"id": pid})
    monkeypatch.setattr(R, "_pushed", lambda r: r)
    assert asyncio.run(R.api_save("x", {"preset": _doc(), "lane": "guitar"}))["ok"] is True
    r = asyncio.run(R.api_save("x", {"preset": _doc(), "lane": "nope"}))
    assert r.status_code == 400
    r = asyncio.run(R.api_save("x", {"lane": "guitar-try"}))
    assert r.status_code == 400
