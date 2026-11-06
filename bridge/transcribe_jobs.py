# SPDX-License-Identifier: GPL-3.0-or-later
"""File de transcription — un seul travail à la fois, en tâche de fond, à basse priorité.

Contrat : `docs/archive/tablature-study.md` §12.

Trois exigences non négociables, et elles dictent la forme :
  1. **Jamais pendant qu'on joue.** Le travail part APRÈS la prise, et il tourne en `nice -19`
     dans un PROCESSUS séparé — pas un thread : le modèle pèse, et le processus du bridge tient
     le lien OSC. Zéro xrun est un critère d'acceptation, pas un souhait.
  2. **Un seul à la fois.** Une répète produit des prises en rafale ; lancer dix modèles en
     parallèle sur le rack, c'est exactement la façon de hacher le son de la prise suivante.
  3. **Ça se voit.** Un travail muet qui prend trente secondes est indiscernable d'un bouton
     cassé. L'état vit dans `state.transcribe` et part au WebSocket.
"""
import json
import os
import subprocess
import threading
import time

from . import config as C
from .golog import swallowed as _swallowed

RECORDINGS = os.path.join(C.ROOT, "recordings")

VENV_PY = os.path.join(C.ROOT, ".venv-transcribe", "bin", "python")
NICE = "19"                     # la plus basse priorité ordonnançable

_lock = threading.Lock()
_queue = []                     # noms de dossiers de prise en attente
_cur = None                     # {dir, status, progress, source, error, started}
_last = {}                      # dir -> dernier résultat, pour l'écran après coup
_on_change = None               # callback posé par app.py (broadcast WS)
_worker = None


def available():
    """Le venv est-il installé ? Un rack sans lui doit le DIRE, pas échouer en silence."""
    return os.path.isfile(VENV_PY)


def _notify():
    if _on_change:
        try:
            _on_change()
        except Exception as _e:
            _swallowed(_e)


def set_on_change(fn):
    global _on_change
    _on_change = fn


def snapshot():
    """Ce que l'écran lit : le travail en cours, la file, et le dernier résultat par prise."""
    with _lock:
        return {"available": available(), "current": dict(_cur) if _cur else None,
                "queue": list(_queue), "last": dict(_last)}


def score_of(take_dir_abs):
    """L'index d'une prise déjà transcrite (`scores/index.json`), ou None. Lu par /api/loops :
    c'est ce qui fait que le bouton sait s'il dit « Transcribe » ou « Score »."""
    try:
        with open(os.path.join(take_dir_abs, "scores", "index.json")) as f:
            idx = json.load(f)
    except Exception:
        return None
    srcs = idx.get("sources") or []
    oks = [s for s in srcs if s.get("file")]
    return {"at": idx.get("at"), "seconds": idx.get("seconds"), "engine": idx.get("engine"),
            "bars": sum(s.get("bars") or 0 for s in oks), "sources": len(oks),
            "exact": sum(1 for s in oks if s.get("quality") == "exact"),
            "draft": sum(1 for s in oks if s.get("quality") == "draft"),
            "failed": [s.get("src") for s in srcs if s.get("error")]}


def eligible(take_dir_abs):
    """Une prise est transcriptible si elle porte une DI ou une capture MIDI.

    C'est la précondition que l'écran montre déjà, sans le savoir : la puce `+DI` de l'en-tête.
    Sans source propre, on ne grise pas seulement le bouton — on dit pourquoi (§12)."""
    try:
        files = os.listdir(take_dir_abs)
    except Exception:
        return (False, "take not found")
    if any(f.lower().endswith(".mid") for f in files):
        return (True, "")
    if any(f.startswith("DI-") and f.lower().endswith(".wav") for f in files):
        return (True, "")
    if "standard.seq" in files:                     # les parties du Standard joué : exactes (lot 3 des partitions)
        return (True, "")
    return (False, "no DI in this take — set Rec to Multi + DI")


def enqueue(take_dir):
    """Met une prise dans la file. Idempotent : re-demander une prise déjà en file ou en cours
    ne fait rien (le bouton peut être tapé deux fois, c'est un écran tactile)."""
    if not available():
        return {"ok": False, "error": "transcription engine not installed (.venv-transcribe)"}
    path = os.path.join(RECORDINGS, take_dir)
    ok, why = eligible(path)
    if not ok:
        return {"ok": False, "error": why}
    with _lock:
        if (_cur and _cur["dir"] == take_dir) or take_dir in _queue:
            return {"ok": True, "already": True}
        _queue.append(take_dir)
    _ensure_worker()
    _notify()
    return {"ok": True}


def _ensure_worker():
    global _worker
    with _lock:
        if _worker and _worker.is_alive():
            return
        _worker = threading.Thread(target=_run_loop, name="transcribe", daemon=True)
        _worker.start()


def _run_loop():
    global _cur
    while True:
        with _lock:
            if not _queue:
                _cur = None
                return
            take = _queue.pop(0)
            _cur = {"dir": take, "status": "running", "progress": 0.0, "source": "",
                    "error": "", "started": time.time()}
        _notify()
        _run_one(take)
        _notify()


def _run_one(take):
    """Lance le worker dans le venv et SUIT sa sortie ligne à ligne (une ligne = un événement
    JSON). Le suivi n'est pas cosmétique : sans lui l'écran ne peut pas distinguer « ça
    travaille » de « c'est bloqué »."""
    global _cur
    path = os.path.join(RECORDINGS, take)
    cmd = ["nice", "-n", NICE, VENV_PY, "-m", "bridge.transcribe_cli", path]
    try:
        p = subprocess.Popen(cmd, cwd=C.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, bufsize=1)
    except Exception as e:
        with _lock:
            _last[take] = {"ok": False, "error": "lancement impossible : %s" % e}
        return
    total, seen = 1, 0
    for line in p.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue                                    # les avertissements du venv, ignorés
        try:
            ev = json.loads(line)
        except Exception:
            continue
        with _lock:
            if not _cur:
                break
            if ev.get("ev") == "start":
                total = max(1, int(ev.get("total") or 1))
            elif ev.get("ev") == "source":
                seen = int(ev.get("i") or 0)
                _cur["source"] = ev.get("name") or ""
                _cur["progress"] = round(seen / total, 3)
            elif ev.get("ev") in ("ok", "fail"):
                seen += 1
                _cur["progress"] = round(min(1.0, seen / total), 3)
        _notify()
    err = (p.stderr.read() or "").strip()
    code = p.wait()
    idx = score_of(path)
    with _lock:
        _last[take] = ({"ok": True, **idx} if idx and code == 0
                       else {"ok": False, "error": (err.splitlines()[-1] if err else
                                                    "the worker stopped (code %s)" % code)})
        _cur = None
