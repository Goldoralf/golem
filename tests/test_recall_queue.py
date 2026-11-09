# SPDX-License-Identifier: GPL-3.0-or-later
"""La porte du pied vers le moteur (bridge/recall.py `submit`, `schedule`, `schedule_slot`) : un seul worker, dans
l'ordre, et une erreur DITE sans tuer la file. Audit des tests du 2026-11-09 : ce chemin (PC de bank, scène au pied,
cues) n'avait aucun test. Aucun REAPER : les rappels sont remplacés par des enregistreurs."""
import threading
import time

from bridge import recall


def _drain():
    """Attend que la file du worker soit vide (un marqueur passe après tout ce qui a été soumis)."""
    done = threading.Event()
    recall.submit(done.set)
    assert done.wait(5)


def test_la_file_est_servie_dans_l_ordre_meme_si_un_rappel_est_lent():
    seen = []
    recall.submit(lambda: (time.sleep(0.15), seen.append("bank 3")))
    recall.submit(lambda: seen.append("scene B"))
    recall.submit(lambda: seen.append("scene C"))
    _drain()
    assert seen == ["bank 3", "scene B", "scene C"]                 # un seul worker : jamais doublé


def test_une_erreur_est_dite_et_la_file_continue(monkeypatch):
    errors, seen = [], []
    monkeypatch.setattr(recall.log_recall, "error", lambda msg: errors.append(msg))

    def boom():
        raise RuntimeError("REAPER ne répond pas")
    recall.submit(boom)
    recall.submit(lambda: seen.append("ensuite"))
    _drain()
    assert seen == ["ensuite"]
    assert len(errors) == 1 and "REAPER ne répond pas" in errors[0]


def test_le_pied_passe_par_les_bons_rappels(monkeypatch):
    calls = []
    monkeypatch.setattr(recall, "do_recall", lambda pid, scene: calls.append(("recall", pid, scene)))
    monkeypatch.setattr(recall, "do_recall_slot", lambda slot, source=None: calls.append(("slot", slot, source)))
    recall.schedule_slot(4, "foot")                                  # PC de bank
    recall.schedule(None, "C")                                       # scène au pied, preset courant
    _drain()
    assert calls == [("slot", 4, "foot"), ("recall", None, "C")]


def test_sans_boucle_attachee_un_rappel_differe_part_tout_de_suite(monkeypatch):
    """_later sans boucle (tests, avant le démarrage) : appel direct, rien ne se perd."""
    monkeypatch.setattr(recall, "_loop", None)
    got = []
    recall._later(5, got.append, "x")
    assert got == ["x"]
