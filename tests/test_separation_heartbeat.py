# SPDX-License-Identifier: GPL-3.0-or-later
"""`separation_job` du battement (docs/separation.md §10) : absent sans job tenu, la raison d'attente en CODE (jamais
le texte de busy_reason), le compte à rebours de la règle des 10 min, la progression en cours ; et un refus de
golem.fm au code inconnu dit son `message`."""
import pytest

from bridge import inventory, separation as S


@pytest.fixture
def job(monkeypatch):
    monkeypatch.setitem(S._JOB, "cur", {"id": 131, "kind": "vocals"})
    monkeypatch.setitem(S._JOB, "phase", "waiting")
    monkeypatch.setitem(S._JOB, "waiting", None)
    monkeypatch.setitem(S._JOB, "progress", None)
    return S._JOB


def test_sans_job_tenu_pas_de_cle(monkeypatch):
    monkeypatch.setitem(S._JOB, "cur", None)
    assert S.heartbeat_job() is None


@pytest.mark.parametrize("why,code", [
    ("gig mode", "gig"), ("mode locked", "locked"), ("a take is recording", "recording"),
    ("a song is playing", "playing"), ("a song is loading", "loading"), ("a preview is rendering", "preview")])
def test_la_raison_part_en_code(job, why, code):
    job["waiting"] = why
    assert S.heartbeat_job() == {"job": 131, "phase": "waiting", "why": code}


def test_in_use_dit_quand_il_commencera_sans_la_source_du_geste(job, monkeypatch):
    from bridge import activity
    monkeypatch.setattr(activity, "idle_s", lambda: 400.0)
    job["waiting"] = "in use (screen, 400 s ago)"
    out = S.heartbeat_job()
    assert out == {"job": 131, "phase": "waiting", "why": "in_use", "starts_in_s": 200}
    assert "screen" not in repr(out)


def test_une_raison_inconnue_ne_part_pas(job):
    job["waiting"] = "something new"
    assert S.heartbeat_job() == {"job": 131, "phase": "waiting"}


@pytest.mark.parametrize("phase", ["download", "separate", "upload"])
def test_en_cours_running_avec_progression(job, phase):
    job.update(phase=phase, progress=0.4237)
    assert S.heartbeat_job() == {"job": 131, "phase": "running", "progress": 0.424}


def test_en_cours_sans_progression(job):
    job["phase"] = "download"
    assert S.heartbeat_job() == {"job": 131, "phase": "running"}


def test_le_battement_porte_la_cle(job, monkeypatch):
    from bridge import rigstatus
    job["waiting"] = "a song is playing"
    assert rigstatus.light()["separation_job"] == {"job": 131, "phase": "waiting", "why": "playing"}
    job["cur"] = None
    assert "separation_job" not in rigstatus.light()


def test_un_refus_inconnu_dit_le_message_de_golem_fm():
    det = {"error": "import_failed", "message": "This album has no cover yet."}
    assert inventory._why(422, "import_failed", det) == "This album has no cover yet."
    assert inventory._why(422, "import_failed", {"error": "import_failed"}) == "golem.fm refused (422 import_failed)"
    assert inventory._why(422, "bad_golem", det) == "golem.fm refused the file"   # un code connu garde notre phrase


class _StopWorker(BaseException):
    pass


def test_un_lot_qui_tient_le_moteur_laisse_le_job_en_attente_et_annulable(monkeypatch):
    """Revue 2026-10-25 : le job annonçait `running` puis restait bloqué sur RUN_LOCK, tenu par le lot d'un dossier —
    golem.fm disait « separating », et une annulation n'était vue qu'après le morceau du lot. Il attend désormais DANS
    la boucle de la règle « libre » : waiting, sans code, annulable ; le verrou du lot n'est jamais relâché par lui."""
    import threading
    seen, acks = [], []

    class Cond(type(S._jcond)):
        def wait(self, timeout=None):
            seen.append(dict(phase=S._JOB["phase"], waiting=S._JOB["waiting"]))
            if len(seen) == 2:
                S._JOB["cancel"].add(131)           # l'utilisateur annule pendant l'attente
            if len(seen) > 4:
                raise _StopWorker()                 # la file est vide : on arrête le fil du test
            return True
    monkeypatch.setattr(S, "_jcond", Cond(threading.Lock()))
    monkeypatch.setattr(S, "_JOBS", [{"id": 131, "kind": "vocals"}])
    monkeypatch.setattr(S, "_busy", lambda idle=True: None)
    monkeypatch.setattr(S, "active_engine", lambda: (None, None))
    monkeypatch.setattr(S, "_publish", lambda: None)
    monkeypatch.setattr(S, "_cleanup", lambda jid: None)
    monkeypatch.setattr(S, "_run_job", lambda job: pytest.fail("ran while the batch held the engine"))
    monkeypatch.setattr(S, "_ack", lambda job, body: acks.append(body))
    monkeypatch.setitem(S._JOB, "cancel", set())
    lock = threading.Lock()
    monkeypatch.setattr(S, "RUN_LOCK", lock)
    lock.acquire()                                   # le lot d'un dossier sépare
    t = threading.Thread(target=lambda: pytest.raises(_StopWorker, S._work), daemon=True)
    t.start(); t.join(5)
    assert not t.is_alive()
    assert seen[0] == {"phase": "waiting", "waiting": "a folder is being separated"}
    assert acks == [{"ok": False, "error": "cancelled"}]
    assert lock.locked()                             # toujours au lot
    lock.release()


def test_un_fichier_de_moteur_combine_mal_forme_est_refuse_sans_500():
    with pytest.raises(S.SeparationError, match="not a golem engine file"):
        S.read_engine_file({"format": S.ENGINE_FILE_FORMAT, "kind": "combined", "first": "x", "second": {}})


def test_ffmpeg_absent_est_une_erreur_dite(monkeypatch):
    import subprocess
    def missing(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(S.SeparationError, match="needs ffmpeg"):
        S.decode("in.wav", "out.f32")


def test_on_ne_retire_pas_le_moteur_qui_separe(monkeypatch):
    import threading
    d = {"engines": [{"id": "e1", "kind": "onnx", "origin": "listed"}], "active": "e1", "rtf": {}}
    monkeypatch.setattr(S, "load", lambda: d)
    monkeypatch.setattr(S, "_save", lambda x: pytest.fail("saved while separating"))
    lock = threading.Lock()
    monkeypatch.setattr(S, "RUN_LOCK", lock)
    with lock:
        with pytest.raises(S.SeparationError, match="separating a song right now"):
            S.remove("e1")
    assert d["active"] == "e1" and d["engines"]
