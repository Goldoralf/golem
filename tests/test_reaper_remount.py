# SPDX-License-Identifier: GPL-3.0-or-later
"""REAPER tombe ou redémarre en plein concert : le bridge le voit et remonte le rig tout seul (bridge/monitors.py,
`_monitor_reaper` et `_remount_after_restart`). Audit des tests du 2026-11-09 : le chemin qui rend le son après un
plantage n'avait aucun test. Aucun processus réel : le PID de REAPER, le veilleur Lua et le rappel sont simulés."""
import asyncio
import os
import time

import pytest

from bridge import monitors as M
from bridge import recall


@pytest.fixture
def fast(monkeypatch):
    """Les attentes du moniteur (0,5 s, 2 s) deviennent immédiates."""
    real = asyncio.sleep
    monkeypatch.setattr(M.asyncio, "sleep", lambda s: real(0))


def _remount(monkeypatch, pid_seq, watch_ready=True, live=False, preset="p1", scene="B"):
    calls = []
    seq = iter(pid_seq)
    last = [pid_seq[0]]

    def pid():
        last[0] = next(seq, last[0])
        return last[0]
    monkeypatch.setattr(M, "_reaper_pid", pid)
    monkeypatch.setattr(M, "_watch_started_since", lambda t0: watch_ready)
    monkeypatch.setattr(recall, "rig_is_live", lambda p: live)
    monkeypatch.setattr(recall, "do_recall", lambda p, s, *a: calls.append((p, s)) or True)
    monkeypatch.setattr(M.state, "preset_id", preset, raising=False)
    monkeypatch.setattr(M.state, "scene_id", scene, raising=False)
    asyncio.run(M._remount_after_restart(pid_seq[0]))
    return calls


def test_le_rig_est_remonte_avec_le_preset_et_la_scene_en_cours(monkeypatch, fast):
    assert _remount(monkeypatch, [222]) == [("p1", "B")]


def test_pas_de_remontee_si_quelqu_un_a_rappele_entre_temps(monkeypatch, fast):
    assert _remount(monkeypatch, [222], live=True) == []


def test_pas_de_remontee_si_reaper_a_encore_redemarre(monkeypatch, fast):
    """Un autre process a pris la place pendant l'attente du veilleur : c'est la tâche suivante qui remontera."""
    assert _remount(monkeypatch, [222, 333], watch_ready=False) == []


def test_pas_de_remontee_tant_que_le_veilleur_lua_n_a_pas_demarre(monkeypatch, fast):
    """Le veilleur consomme sans l'exécuter toute commande posée avant lui : rappeler trop tôt ne servirait à rien."""
    assert _remount(monkeypatch, [222], watch_ready=False) == []


def test_sans_preset_en_cours_rien_a_remonter(monkeypatch, fast):
    assert _remount(monkeypatch, [222], preset=None) == []


def test_le_veilleur_se_reconnait_a_sa_ligne_de_demarrage(monkeypatch, tmp_path):
    log = tmp_path / ".watch.log"
    monkeypatch.setattr(M, "_WATCH_LOG", str(log))
    t0 = time.time() - 5
    assert M._watch_started_since(t0) is False                       # pas de journal
    log.write_text("autre chose\n", encoding="utf-8")
    assert M._watch_started_since(t0) is False
    log.write_text("golem_watch démarré. surveille presets/.command.json\n", encoding="utf-8")
    assert M._watch_started_since(t0) is True
    os.utime(log, (t0 - 60, t0 - 60))                                # une ligne d'un process d'AVANT ne compte pas
    assert M._watch_started_since(t0) is False


class _Stop(Exception):
    pass


def test_le_moniteur_voit_la_chute_puis_la_relance_et_ne_remonte_que_les_reaper_d_apres(monkeypatch):
    """Premier REAPER vu = l'affaire de boot_recall ; il tombe (lien OSC mort, état diffusé) ; le suivant est remonté."""
    pids = iter([111, 111, None, 222, 222])
    remounts, diag, bcast = [], [], []
    monkeypatch.setattr(M, "_reaper_pid", lambda: next(pids))
    monkeypatch.setattr(M, "_seen_reaper", False)
    monkeypatch.setattr(M, "_last_reaper_pid", None)

    async def remount(pid):
        remounts.append(pid)
    monkeypatch.setattr(M, "_remount_after_restart", remount)
    monkeypatch.setattr(M, "_diag_trigger", lambda t, **f: diag.append(f.get("state")))
    monkeypatch.setattr(M, "_reaper_why", lambda consume=False: {})

    async def broadcast():
        bcast.append(M.state.reaper_running)
    monkeypatch.setattr(M, "_broadcast", broadcast)
    monkeypatch.setattr(M.state, "reaper_running", False, raising=False)
    monkeypatch.setattr(M.state, "reaper_connected", True, raising=False)
    gen0 = M.state.reaper_gen
    n = [0]
    real = asyncio.sleep

    async def tick(_s):
        n[0] += 1
        if n[0] >= 5:
            raise _Stop
        await real(0)
    monkeypatch.setattr(M.asyncio, "sleep", tick)

    async def run():
        with pytest.raises(_Stop):
            await M._monitor_reaper()
        await real(0)                                               # laisse partir la tâche de remontée
    asyncio.run(run())
    assert remounts == [222]
    assert diag == ["up", "down", "up"]
    assert bcast == [True, False, True]
    assert M.state.reaper_gen - gen0 == 3                           # 111, None, 222 : trois changements
    assert M.state.reaper_running is True
