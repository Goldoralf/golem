# SPDX-License-Identifier: GPL-3.0-or-later
"""À l'arrêt de golem, plus rien ne prend le moteur (2026-11-19) : le banc CPU au repos rendait encore un bloc après
l'enregistrement du set, et REAPER ouvrait « Save project golem-set.rpp before closing? » derrière la fenêtre fermée."""
import threading
import time

from bridge import cpu_bench, reamp


def test_golem_qui_s_arrete_est_une_raison_de_ne_pas_prendre_le_moteur(monkeypatch):
    monkeypatch.setitem(reamp._CLOSING, "at", None)
    reamp.set_closing()
    assert reamp.busy_reason() == "golem is stopping"
    assert reamp.busy_reason(idle=False) == "golem is stopping"
    assert cpu_bench.busy(manual=True) == "golem is stopping"


def test_le_banc_s_arrete_au_bloc_en_cours_et_rend_le_moteur(monkeypatch):
    monkeypatch.setitem(reamp._CLOSING, "at", None)
    monkeypatch.setattr(cpu_bench, "targets", lambda fresh=False: [])
    started, restored = threading.Event(), []
    t = [{"key": cpu_bench.SYSTEM_KEY, "hash": "h", "label": "empty lane"}, {"key": "chorus|stereo", "hash": "h2", "label": "chorus"}]
    monkeypatch.setattr(cpu_bench, "pending", lambda *a, **k: list(t))
    monkeypatch.setattr(cpu_bench, "load_profile", lambda: {"blocks": {cpu_bench.SYSTEM_KEY: {}}})
    monkeypatch.setattr(cpu_bench, "save_profile", lambda p: None)
    monkeypatch.setattr(cpu_bench, "_record", lambda *a: None)
    monkeypatch.setattr(cpu_bench, "machine_now", lambda: {})

    def measure(target, machine, seq):
        started.set()
        time.sleep(0.3)                                  # le bloc en cours finit
        raise cpu_bench.BenchError("measured")
    closing = lambda: "golem is stopping" if reamp._CLOSING["at"] else None   # noqa: E731 — la seule règle testée ici
    th = threading.Thread(target=cpu_bench.run, kwargs={"measure": measure, "busy_fn": closing,
                                                        "restore": lambda: restored.append(1)})
    cpu_bench._ST["running"] = True
    th.start()
    assert started.wait(5)
    reamp.set_closing()
    assert cpu_bench.stop(timeout=5) is True
    th.join(5)
    assert restored == [1], "la sandbox est reposée AVANT que le set ne s'enregistre"
    assert cpu_bench.status()["waiting_for"] == "golem is stopping"
