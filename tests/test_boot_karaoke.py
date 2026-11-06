# SPDX-License-Identifier: GPL-3.0-or-later
"""Au démarrage, le preset ÉPHÉMÈRE du karaoké ne s'adopte pas (2026-10-18) : laissé dans REAPER par une soirée
Vocals, il n'appartient à aucune bank — /live s'ouvrait sur « bank #00 » vide et l'accueil choisi était ignoré."""
import asyncio
import json

from bridge import recall, startup_home, store
from bridge.state import state


def _boot(monkeypatch, tmp_path, live_pid, plan=None):
    monkeypatch.setattr("bridge.config.PRESETS_DIR", str(tmp_path))
    json.dump({"preset": live_pid, "scene": "A"}, open(tmp_path / ".live.json", "w"))
    monkeypatch.setattr(state, "reaper_running", True)
    monkeypatch.setattr(state, "preset_id", None)
    monkeypatch.setattr(recall, "load_preset", lambda pid: {"id": pid, "name": pid, "scenes": [{"id": "A"}]})
    monkeypatch.setattr(recall, "rig_is_live", lambda pid: True)
    monkeypatch.setattr(startup_home, "plan", lambda: plan)
    monkeypatch.setattr(startup_home, "first_slot", lambda sl=None: 1)
    done, adopted = [], []
    monkeypatch.setattr(startup_home, "apply", lambda steps: done.append(("home", steps)) or True)

    async def slot_async(n, *a, **k):
        done.append(("slot", n))
        return True
    monkeypatch.setattr(recall, "slot_async", slot_async)
    monkeypatch.setattr(recall, "stomp_states", lambda p, s: adopted.append(p["id"]) or {})

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(recall.asyncio, "sleep", no_sleep)
    asyncio.run(recall.boot_recall())
    return done, adopted


def test_le_karaoke_ne_s_adopte_pas_l_accueil_joue(monkeypatch, tmp_path):
    done, adopted = _boot(monkeypatch, tmp_path, store.KARAOKE_ID, plan=[("recall", "velvetine", "A")])
    assert adopted == [] and done == [("home", [("recall", "velvetine", "A")])]


def test_sans_accueil_la_premiere_bank_non_vide(monkeypatch, tmp_path):
    done, adopted = _boot(monkeypatch, tmp_path, store.KARAOKE_ID, plan=None)
    assert adopted == [] and done == [("slot", 1)]
