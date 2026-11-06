# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bridge qui ne répondait plus (PC Windows neuf, 2026-11-03) : chaque snapshot rechargeait et migrait le preset
d'accueil (startup_home._missing), et chaque broadcast_threadsafe planifiait SA tâche de diffusion — sans écran, rien
ne les fondait. La boucle asyncio ne rendait plus la main. `.venv/bin/python -m pytest tests/test_bridge_saturation.py -q`"""
import asyncio
import os
import threading

import pytest

from bridge import app as A
from bridge import startup_home as SH


# ── le snapshot ne recharge pas l'accueil ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def home(monkeypatch, tmp_path):
    presets, setlists, patches = tmp_path / "presets", tmp_path / "setlists", tmp_path / "patches"
    for d in (presets, setlists, patches):
        d.mkdir()
    monkeypatch.setattr(SH, "PATH", str(tmp_path / ".startup.json"))
    monkeypatch.setattr(SH, "_cache", {"mtime": None, "doc": None})
    monkeypatch.setattr(SH, "_missing_cache", {"key": None, "val": None})
    monkeypatch.setattr("bridge.config.PRESETS_DIR", str(presets))
    monkeypatch.setattr("bridge.config.SETLISTS_DIR", str(setlists))
    monkeypatch.setattr("bridge.patches.PATCHES_DIR", str(patches))
    from bridge import store
    loads = []

    def load(pid):
        loads.append(pid)
        return {"id": pid} if (presets / f"{pid}.json").exists() else None
    monkeypatch.setattr(store, "load_preset", load)
    (presets / "chill.json").write_text("{}")
    SH.set_home({"kind": "preset", "id": "chill", "name": "Chill"})
    return {"loads": loads, "presets": presets}


def test_cent_snapshots_ne_rechargent_l_accueil_qu_une_fois(home):
    for _ in range(100):
        assert SH.describe()["home"]["missing"] is None
    assert home["loads"] == ["chill"], "describe() est appelé par CHAQUE snapshot : il ne recharge rien"


def test_l_accueil_change_ou_son_preset_disparait_et_la_reponse_suit(home):
    SH.describe()
    SH.set_home({"kind": "preset", "id": "other", "name": "Other"})
    assert SH.describe()["home"]["missing"] == "not found"                # nouvel accueil : recalculé
    (home["presets"] / "other.json").write_text("{}")
    os.utime(home["presets"], (1_000_000, 1_000_000))                    # la date du dossier bouge (création)
    assert SH.describe()["home"]["missing"] is None                      # il est apparu : on le voit
    (home["presets"] / "other.json").unlink()
    os.utime(home["presets"], (2_000_000, 2_000_000))
    assert SH.describe()["home"]["missing"] == "not found"               # supprimé : on le voit aussi


def test_une_ecriture_en_place_du_preset_d_accueil_est_vue(home, monkeypatch):
    """Le dossier ne bouge pas quand on réécrit un fichier en place (open(..., "w")) : la date du FICHIER compte."""
    from bridge import store
    state = {"ok": False}
    monkeypatch.setattr(store, "load_preset", lambda pid: {"id": pid} if state["ok"] else None)
    f = home["presets"] / "chill.json"
    os.utime(f, (3_000_000, 3_000_000))
    assert SH.describe()["home"]["missing"] == "not found"              # illisible : « not found »
    before = os.stat(home["presets"]).st_mtime_ns
    state["ok"] = True
    with open(f, "w") as fh:                                             # réparé EN PLACE
        fh.write('{"id": "chill"}')
    os.utime(f, (4_000_000, 4_000_000))
    os.utime(home["presets"], ns=(before, before))                       # le dossier, lui, n'a pas bougé
    assert SH.describe()["home"]["missing"] is None


# ── la diffusion : une seule en file, rien sans écran ────────────────────────────────────────────────────────────
class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, payload):
        self.sent.append(payload)


def test_sans_ecran_aucun_snapshot(monkeypatch):
    monkeypatch.setattr(A, "_bcast", {"lock": None, "pending": False, "queued": False})
    monkeypatch.setattr(A, "_clients", set())
    n = []
    monkeypatch.setattr(A.state, "snapshot", lambda: n.append(1) or {})
    asyncio.new_event_loop().run_until_complete(A._broadcast())
    assert n == [], "personne ne lit l'état : il ne se calcule pas"


def test_les_demandes_des_fils_se_fondent_en_une_seule_diffusion(monkeypatch):
    """Des dizaines de broadcast_threadsafe (OSC, moniteurs, téléchargements) avant que la boucle reprenne la main :
    une seule tâche planifiée, donc un seul snapshot — avant, autant de snapshots que de demandes."""
    monkeypatch.setattr(A, "_bcast", {"lock": None, "pending": False, "queued": False})
    ws = FakeWS()
    monkeypatch.setattr(A, "_clients", {ws})
    n = []
    monkeypatch.setattr(A.state, "snapshot", lambda: n.append(1) or {"n": len(n)})
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(A, "_loop", loop)

    def storm():
        for _ in range(50):
            A.broadcast_threadsafe()
    t = threading.Thread(target=storm)
    t.start()
    t.join()
    loop.run_until_complete(asyncio.sleep(0.05))
    assert len(n) == 1 and ws.sent == ['{"n":1}']
    A.broadcast_threadsafe()                                              # la suivante repart normalement
    loop.run_until_complete(asyncio.sleep(0.05))
    assert len(n) == 2 and ws.sent[-1] == '{"n":2}'
    loop.close()
