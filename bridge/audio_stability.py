# SPDX-License-Identifier: GPL-3.0-or-later
"""LE BUFFER QUI TIENT SUR CETTE MACHINE (docs/health.md §2 bis, 2026-11-25) — la quatrième étape du first check,
sans geste : le bridge essaie les buffers du plus petit au plus grand sur le preset posé, compte les cycles EN RETARD
du moteur (patch 16 du Golem Engine : `late_cycles` dans .engine-status.json — sous ASIO le pilote ne signale aucun
xrun) et garde le plus petit qui n'en fait aucun. Le buffer retenu reste posé (config/golem-engine.json) ; le
musicien peut en choisir un plus petit en connaissance de cause (Settings ▸ Audio Engine).

Pourquoi : sur le portable de dev, 128 claquait 1 à 4 fois par 10 s à cause du pilote NVIDIA (LatencyMon), 64
plusieurs centaines ; un buffer choisi « au hasard » se découvre en jouant. La mesure dit aussi ce qu'ont fait les
plus petits (« 128 a claqué 4 fois en 10 s »), et Health ▸ Dropouts dit d'où viennent les clics.

Sans compteur (REAPER, un moteur d'avant le patch, un backend ALSA qui a ses vrais xruns) : « not measured », jamais
une invention, et l'étape ne fait pas échouer la vérification."""
import contextlib
import threading
import time

from .golog import get

log = get("audio-stability")

CANDIDATES = (64, 128, 256, 512, 1024)
SETTLE_S = 3.0                 # un flux rouvert : ses premiers cycles ne sont pas ceux du jeu
LISTEN_S = 10.0                # par buffer : assez pour qu'un pilote qui bloque tous les quelques secondes se montre

_run = {"thread": None, "cancel": False, "doc": None}
_lock = threading.Lock()


def _engine():
    from . import engine
    return engine.get()


def _late(eng):
    st = eng._status() if hasattr(eng, "_status") else {}
    v = st.get("late_cycles")
    return int(v) if isinstance(v, (int, float)) else None


def _latency_ms(eng):
    st = eng._status() if hasattr(eng, "_status") else {}
    li, lo, sr = st.get("latency_in"), st.get("latency_out"), st.get("sample_rate") or 48000
    if li and lo:
        return round((li + lo) / sr * 1000, 1)
    b = st.get("buffer")
    return round(2 * b / sr * 1000, 1) if b else None


def measurable(eng=None):
    """Le moteur compte-t-il ses cycles en retard ? (le Golem Engine g8+ sous PortAudio)"""
    eng = eng or _engine()
    return getattr(eng, "id", None) != "reaper" and hasattr(eng, "set_buffer") and _late(eng) is not None


def plan(eng):
    sizes = [n for n in CANDIDATES if n in tuple(getattr(eng, "BUFFERS", CANDIDATES))]
    return sizes or list(CANDIDATES)


def measure(eng, sizes, sleep=time.sleep, on_step=None, cancelled=lambda: False):
    """Essaie chaque taille dans l'ordre ; s'arrête à la première sans cycle en retard. Rend
    {buffer, tried: [(taille, cycles en retard)], ok, latency_ms} — `ok` faux quand même la plus grande claque."""
    tried = []
    chosen = None
    for i, n in enumerate(sizes):
        if cancelled():
            break
        if on_step:
            on_step(n, i, len(sizes))
        eng.set_buffer(n)
        sleep(SETTLE_S)
        a = _late(eng)
        sleep(LISTEN_S)
        b = _late(eng)
        if a is None or b is None:
            return {"measured": False}
        late = b - a if b >= a else b                     # le compteur repart de zéro à chaque ouverture du flux
        tried.append((n, late))
        if late == 0:
            chosen = n
            break
    if not tried:
        return {"measured": False}
    ok = chosen is not None
    if not ok:
        chosen = tried[-1][0]                            # même la plus grande claque : on la garde, et on le dit
        if eng.audio().get("buffer") != chosen:
            eng.set_buffer(chosen)
    return {"measured": True, "ok": ok, "buffer": chosen, "tried": tried, "latency_ms": _latency_ms(eng)}


def status():
    with _lock:
        d = dict(_run["doc"] or {})
    d["running"] = bool(_run["thread"] and _run["thread"].is_alive())
    return d


def start():
    """Lance la mesure dans un fil (≈ 15 s par taille essayée) ; à la fin, l'étape `stability` du first check est
    écrite par le bridge lui-même. Une mesure déjà en cours n'est pas relancée."""
    from . import first_check
    if _run["thread"] and _run["thread"].is_alive():
        return status()
    eng = _engine()
    if not measurable(eng):
        first_check.record("stability", True, {"measured": False})
        return {"running": False, "measured": False}
    sizes = plan(eng)
    _run["cancel"] = False
    with _lock:
        _run["doc"] = {"sizes": sizes, "at": None, "index": 0}

    def step(n, i, total):
        with _lock:
            _run["doc"] = {"sizes": sizes, "at": n, "index": i, "total": total}

    def work():
        r = {"measured": False}
        try:
            r = measure(eng, sizes, on_step=step, cancelled=lambda: _run["cancel"])
        except Exception as e:                            # une mesure qui casse ne bloque pas la vérification
            log.warning(f"mesure de stabilité interrompue : {e}")
        if _run["cancel"]:
            return
        with contextlib.suppress(Exception):
            from . import monitors
            monitors.xruns_clear()                        # les claquements de la mesure ne sont pas ceux du jeu
        first_check.record("stability", r.get("ok", True) if r.get("measured") else True, r)
        log.info(f"buffer qui tient ici : {r}")

    _run["thread"] = threading.Thread(target=work, daemon=True, name="audio-stability")
    _run["thread"].start()
    return status()


def cancel():
    """« Skip » : la mesure s'arrête à la fin de la taille en cours ; l'étape est notée passée."""
    _run["cancel"] = True
