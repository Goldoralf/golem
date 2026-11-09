# SPDX-License-Identifier: GPL-3.0-or-later
"""Le banc du premier usage d'un plugin VST Host sous Linux (bridge/plugin_trial.py, docs/platforms.md §6.1 lot 3).
Aucun REAPER n'est lancé : le verdict se lit sur une trace simulée, et l'essai lui-même est remplacé. Le banc a été
calibré à la main le 2026-11-09 sur le vrai REAPER 7.82 (bruit 12 ms ; un JSFX qui bloque 67 / 83 ms est lu 67 / 83)."""
import threading
from pathlib import Path

import pytest

from bridge import blockstatus as BS, plugin_trial as T, rig

PLUGIN = "CLAP: Fake Synth (Vendor)"


@pytest.fixture
def bench(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "TRIALS", str(tmp_path / "vst-trials.json"))
    monkeypatch.setattr(T.sys, "platform", "linux")
    monkeypatch.setenv("GOLEM_VST_TRIAL", "1")
    return tmp_path


class Proc:
    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 1


def _trace(tmp, text):
    p = Path(tmp) / "t.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_verdicts_lus_sur_la_trace(bench):
    assert T._watch(Proc(), _trace(bench, "start\nloaded\nstall_ms=12\ndone\n"), 5) == (True, None, {"stall_ms": 12})
    ok, why, extra = T._watch(Proc(), _trace(bench, "start\nloaded\nstall_ms=430\ndone\n"), 5)
    assert not ok and "430 ms" in why and extra == {"stall_ms": 430}
    assert T._watch(Proc(alive=False), _trace(bench, "start\nloaded\n"), 5)[:2] == (False, "crashed REAPER")


def test_un_plugin_introuvable_n_est_pas_juge(bench):
    """Un nom périmé ou un plugin désinstallé : pas de verdict gardé (on réessaiera), blockstatus dit « not installed »."""
    with pytest.raises(RuntimeError, match="did not load"):
        T._watch(Proc(), _trace(bench, "start\nerror=the plugin did not load\n"), 5)


def test_fige_pendant_le_chargement_ou_apres(bench, monkeypatch):
    monkeypatch.setattr(T, "FROZEN_S", 0.3)
    assert T._watch(Proc(), _trace(bench, "start\nloaded\nbeat\n"), 5)[:2] == (False, "froze REAPER")
    assert T._watch(Proc(), _trace(bench, "start\n"), 0.3)[0] is False
    with pytest.raises(RuntimeError):                                  # REAPER n'a même pas démarré : pas un verdict
        T._watch(Proc(), Path(bench) / "absent.txt", 0.3)


def test_le_rig_retient_un_plugin_jamais_essaye_puis_le_laisse_jouer(bench, monkeypatch):
    started = []
    monkeypatch.setattr(T, "start", lambda plugin, on_done=None: started.append(plugin) or True)
    block = {"id": "host", "type": "vst-host", "plugin": PLUGIN}
    assert rig._drop_quarantined([block]) == [] and started == [PLUGIN]
    T._record(PLUGIN, True, stall_ms=12)
    assert rig._drop_quarantined([block]) == [block]
    T._record(PLUGIN, False, "crashed REAPER")
    assert rig._drop_quarantined([block]) == []


def test_ailleurs_que_sous_linux_rien_ne_change(bench, monkeypatch):
    monkeypatch.setattr(T.sys, "platform", "win32")
    block = {"id": "host", "type": "vst-host", "plugin": PLUGIN}
    assert rig._drop_quarantined([block]) == [block]
    monkeypatch.setattr(T.sys, "platform", "linux")
    monkeypatch.setenv("GOLEM_VST_TRIAL", "0")                          # le banc coupé (dépannage, suite de tests)
    assert rig._drop_quarantined([block]) == [block]


def test_l_etat_du_bloc_dit_l_essai_puis_le_refus(bench, monkeypatch):
    monkeypatch.setattr(BS, "inventory", lambda: {"qualified_names": {PLUGIN.casefold()}})
    st = BS.block_state({"type": "vst-host", "plugin": PLUGIN})
    assert st["state"] == "unavailable" and st["reason"] == "trial" and "tested" in st["why"]
    T._record(PLUGIN, False, "stopped the audio engine for 430 ms when switched on or off")
    st = BS.block_state({"type": "vst-host", "plugin": PLUGIN})
    assert st["reason"] == "quarantine" and "430 ms" in st["detail"]
    T._record(PLUGIN, True, stall_ms=12)
    assert BS.block_state({"type": "vst-host", "plugin": PLUGIN})["state"] == "ready"


def test_un_seul_essai_a_la_fois_et_la_suite_est_appelee(bench, monkeypatch):
    gate, done = threading.Event(), []
    monkeypatch.setattr(T, "trial", lambda p: (gate.wait(5), (True, None, {"stall_ms": 12}))[1])
    assert T.start(PLUGIN, on_done=lambda p, ok: done.append((p, ok))) is True
    assert T.start(PLUGIN) is False and T.running(PLUGIN)
    gate.set()
    for _ in range(100):
        if done:
            break
        threading.Event().wait(0.02)
    assert done == [(PLUGIN, True)] and T.verdict(PLUGIN)["ok"] is True
    assert T.start(PLUGIN) is False                                     # un verdict : plus jamais essayé


def test_le_script_du_banc_arme_la_piste_et_pose_le_metre_avant_le_plugin():
    lua = T.script(PLUGIN, "/tmp/x.txt")
    assert lua.index("golem_trial_meter") < lua.index("TrackFX_AddByName(tr, PLUGIN")
    assert '"I_RECMODE", 2' in lua and '"I_RECARM", 1' in lua
    assert "options:gmem=golem_trial" in T.METER and "@init" in T.METER.split("@block")[0]


def test_le_verdict_du_banc_change_la_forme_du_plan_donc_le_bloc_est_pose(bench):
    """Vu au rack le 2026-11-09 : le brouillon rejoué après un verdict « ok » avait la même forme qu'avant (le bloc VST
    y figurait déjà, le rig l'avait retiré) -> scene_apply -> le plugin jamais posé, sa fenêtre en 404. Le verdict, et
    le plugin choisi, font partie de la forme : ils exigent un rebuild."""
    from bridge import recall
    p = {"id": "t", "name": "t", "kind": "patch", "patch_v": 2, "lanes_v": 2,
         "lanes": [{"id": "g", "role": "guitar", "chain": {"pre": [{"id": "host", "type": "vst-host", "plugin": PLUGIN}]}}],
         "scenes": [{"id": "A", "name": "A"}]}
    pending = recall.scene_shape(p, "A")
    T._record(PLUGIN, True, stall_ms=12)
    ok = recall.scene_shape(p, "A")
    assert ok != pending
    T._record(PLUGIN, False, "crashed REAPER")
    assert recall.scene_shape(p, "A") not in (pending, ok)
    p["lanes"][0]["chain"]["pre"][0]["plugin"] = "CLAP: Other (Vendor)"
    assert recall.scene_shape(p, "A") != ok
