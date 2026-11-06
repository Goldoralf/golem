# SPDX-License-Identifier: GPL-3.0-or-later
"""HEALTH ▸ FIX — LE REGISTRE D'ACTIONS (docs/assistant.md §3, maquette mockups/health-fix.html validée le 2026-10-20).

Une action n'existe que si elle est ICI : le bouton « Fix… » de Health, `golem doctor` et, plus tard, l'assistant
(golem.fm propose, la machine décide) appellent LA MÊME. Chaque action déclare ce qu'un modèle lira (`description`),
son risque (read · modify · system), ses pages d'aide (les ids de golem.fm, `<section>/<page>` : ce qu'un modèle
peut citer), ses paramètres BORNÉS (un schéma JSON, construit pour cette plateforme), si elle
est permise pendant qu'on joue (`live_allowed` — jamais pour ce qui n'est pas `read`), et sa VÉRIFICATION : une
réparation n'est finie que quand la sonde repasse au vert.

Le cycle : `plan()` valide et décrit (avant → après, ce que ça coûte, comment on vérifie, comment on revient) — c'est
la feuille de l'écran ; `apply()` exécute (une seule réparation à la fois), puis un fil vérifie et range le résultat
dans l'incident (bridge/incidents.py) et la chronologie de diagnostic (événement `fix`). Le registre reste COURT :
seulement des chemins de code qui existaient déjà (routes du Dashboard, commandes du veilleur).

Pas de « snapshot » global (le P5 du brouillon) : la seule action qui change un réglage persistant est le buffer, et
elle porte son propre retour arrière (`undo` : la taille d'avant). Les autres ne changent rien qu'on puisse défaire."""
import asyncio
import contextlib
import sys
import threading
import time
import uuid

from .golog import get
from .golog import swallowed as _swallowed

log = get("fixes")
VERIFY_POLL_S = 1.0
DROPOUTS_WATCH_S = 120            # la vérification d'un buffer : deux minutes de jeu sans rafale
DROPOUTS_OK_MAX = 2               # au plus 2 décrochages pendant la fenêtre (le seuil d'une rafale est 10)
ENGINE_BACK_S = 90                # le temps qu'un REAPER relancé réponde de nouveau (buffer, redémarrage)

_lock = threading.Lock()
_run = {"cur": None, "last": None}   # la réparation en cours, et la dernière finie


def _st():
    from .state import state
    return state


def _buffer_sizes():
    if sys.platform in ("win32", "darwin"):
        from .desktop_audio import BUFFER_SIZES
        return list(BUFFER_SIZES)
    from .routes_system import AUDIO_BSIZES
    return list(AUDIO_BSIZES)


def _bsize():
    with contextlib.suppress(Exception):
        from .routes_system import _read_bsize
        v = _read_bsize()
        return int(v) if v else None
    return None


def _rt_ms(size, rate=48000):
    return round(2 * size / rate * 1000, 1)


def _rate():
    with contextlib.suppress(Exception):
        from .rigstatus import engine_doc
        r = (engine_doc() or {}).get("samplerate")
        if r:
            return int(r)
    return 48000


# ── l'exécution de chaque action : le chemin de code qui existait déjà ─────────────────────────────────────────────
async def _run_buffer(p):
    from .routes_system import audio_buffer
    return await audio_buffer({"size": p["size"]})


async def _run_osc(p):
    from .routes_system import osc_refresh
    return await osc_refresh()


async def _run_restart(p):
    from . import diag
    diag.intent("reaper", "requested")                    # un redémarrage voulu n'est pas un crash (diag §2.3)
    from .routes_system import reaper_restart
    return await reaper_restart()


async def _run_command(action):
    from .commands import write_command
    write_command({"action": action, "why": "health fix"})
    return {"ok": True}


async def _run_audio_reset(p):
    return await _run_command("audio_reset")


async def _run_midi_reinit(p):
    return await _run_command("midi_reinit")


async def _run_repose(p):
    from . import recall
    recall._LAST_EMIT["shape"] = None                     # forme oubliée → rig_recall : un vrai rebuild, pas une bascule
    err = await asyncio.to_thread(recall.reapply_sandbox)
    return {"ok": not err, "error": err} if err else {"ok": True}


async def _run_silence(p):
    from . import silence
    r = silence.start(p.get("seconds") or 4.0)
    return r if r.get("ok") else {"ok": False, "error": r.get("why") or "cannot start"}


async def _run_facts(p):
    from . import health
    health.facts(fresh=True)
    return {"ok": True}


# ── la vérification : la sonde relue jusqu'au vert, ou jusqu'au délai ──────────────────────────────────────────────
def _engine_ok():
    st = _st()
    return bool(getattr(st, "reaper_running", False) and getattr(st, "reaper_connected", False))


def _audio_ok():
    return (getattr(_st(), "audio", None) or {}).get("ok") is True


def _verify_engine(ctx, now):
    if _engine_ok():
        return "ok", "REAPER answers the bridge"
    return ("ko", "REAPER still does not answer") if now - ctx["t0"] > ctx["timeout"] else ("wait", "waiting for REAPER to answer…")


def _verify_audio(ctx, now):
    if _audio_ok():
        return "ok", "the audio thread is running"
    return ("ko", "the audio thread did not come back") if now - ctx["t0"] > 20 else ("wait", "waiting for the audio thread…")


def _verify_midi(ctx, now):
    midi = getattr(_st(), "midi", None) or {}
    if midi.get("ok") is not False:
        return "ok", "MIDI devices reopened"
    return ("ko", "MIDI still reports a problem") if now - ctx["t0"] > 20 else ("wait", "reopening MIDI devices…")


def _verify_rig(ctx, now):
    rc = getattr(_st(), "rig_check", None) or {}
    if rc.get("ok") is True and float(rc.get("t") or 0) >= ctx["t0"] - 1:
        return "ok", f"every file loaded ({rc.get('checked', 0)} checked)"
    if rc.get("ok") is False and float(rc.get("t") or 0) >= ctx["t0"] - 1:
        return "ko", "files still not loaded after the rebuild"
    return ("ko", "the rebuild was not verified in time") if now - ctx["t0"] > 60 else ("wait", "rebuilding the preset…")


def _verify_dropouts(ctx, now):
    """Deux temps : attendre que REAPER revienne avec le nouveau buffer, puis compter les décrochages pendant
    DROPOUTS_WATCH_S de jeu. Rien de joué = rien de prouvé, mais rien de cassé non plus : le verdict le dit."""
    st = _st()
    if ctx.get("watch_from") is None:
        if _engine_ok() and _audio_ok() and now - ctx["t0"] > 3:
            ctx["watch_from"], ctx["xr0"] = now, int(getattr(st, "xruns", 0) or 0)
            return "wait", "REAPER is back — keep playing, golem counts dropouts"
        if now - ctx["t0"] > ENGINE_BACK_S:
            return "ko", "REAPER did not come back with the new buffer"
        return "wait", "REAPER restarts its audio with the new buffer…"
    n = max(0, int(getattr(st, "xruns", 0) or 0) - ctx["xr0"])
    left = DROPOUTS_WATCH_S - (now - ctx["watch_from"])
    if n > DROPOUTS_OK_MAX:
        return "ko", f"{n} dropouts in {int(now - ctx['watch_from'])} s — the buffer is too small"
    if left <= 0:
        return "ok", f"{n} dropout{'s' if n != 1 else ''} in {DROPOUTS_WATCH_S // 60} min"
    return "wait", f"checking: {n} dropout{'s' if n != 1 else ''} · {int(left)} s left — keep playing"


def _verify_none(ctx, now):
    return "ok", "done"


# ── le registre ────────────────────────────────────────────────────────────────────────────────────────────────────
def _buffer_label(p):
    """Le sens du changement : un buffer qui MONTE répare des dropouts, un buffer qui DESCEND baisse la latence (constaté
    2026-10-20 : golem.fm proposait 192 → 128 pour « baisser la latence », affiché « Raise the buffer »)."""
    cur = _bsize()
    return "Lower the buffer" if cur and p.get("size") and p["size"] < cur else "Raise the buffer"


def _plan_buffer(p):
    cur, new, rate = _bsize(), p["size"], _rate()
    if cur and new < cur:
        return {"title": "Lower the latency",
                "why": "A smaller buffer answers faster under your fingers. It gives the computer less time per buffer: "
                       "with heavy presets, dropouts (crackles) can come back.",
                "before": {"value": f"{cur} samples", "sub": f"{_rt_ms(cur, rate)} ms round trip"},
                "after": {"value": f"{new} samples", "sub": f"{_rt_ms(new, rate)} ms round trip"},
                "costs": ["REAPER restarts its audio — about 10 s of silence. Not during a take or a song."],
                "verify": f"Then golem watches dropouts for {DROPOUTS_WATCH_S // 60} minutes while you play. If they "
                          "come back, the change has failed and Undo puts the buffer back.",
                "undo": f"Undo puts the buffer back to {cur} samples.",
                "apply_label": f"Apply — {new} samples"}
    return {"title": "Fix: audio dropouts",
            "why": "Dropouts come in bursts when the computer gets less time than it needs per buffer. A larger "
                   "buffer gives it more, for a little more latency.",
            "before": {"value": f"{cur} samples" if cur else "unknown", "sub": f"{_rt_ms(cur, rate)} ms round trip" if cur else ""},
            "after": {"value": f"{new} samples", "sub": f"{_rt_ms(new, rate)} ms round trip"},
            "costs": ["REAPER restarts its audio — about 10 s of silence. Not during a take or a song."],
            "verify": f"Then golem watches dropouts for {DROPOUTS_WATCH_S // 60} minutes while you play. The fix counts only if it stays clean.",
            "undo": f"Undo puts the buffer back to {cur} samples." if cur else "Undo: Settings ▸ System ▸ Dashboard ▸ Audio buffer.",
            "apply_label": f"Apply — {new} samples"}


ACTIONS = {
    "set_buffer": {
        "label": "Change the buffer",
        "label_for": _buffer_label,
        "description": "Change the audio buffer size. A larger buffer stops dropouts (crackles) at the cost of a "
                       "little latency; REAPER restarts its audio (~10 s of silence).",
        "risk": "modify", "live_allowed": False, "help": ["golem/health", "golem/soundcard"],
        "params": lambda: {"type": "object", "required": ["size"],
                           "properties": {"size": {"type": "integer", "enum": _buffer_sizes()}}},
        "run": _run_buffer, "verify": _verify_dropouts, "plan": _plan_buffer,
        "undo": lambda p, before: {"action": "set_buffer", "params": {"size": before}} if before else None,
    },
    "osc_refresh": {
        "label": "Resync REAPER",
        "description": "Ask REAPER to resend its whole state to the bridge, without restarting. For an engine that "
                       "runs but does not answer.",
        "risk": "modify", "live_allowed": False, "help": ["golem/health"],
        "params": lambda: {"type": "object", "properties": {}},
        "run": _run_osc, "verify": _verify_engine, "timeout": 15,
        "plan": lambda p: {"title": "Fix: REAPER does not answer", "why": "REAPER runs but the bridge hears nothing from it. "
                           "A resync asks it to resend everything — nothing restarts.",
                           "before": {"value": "answering" if _engine_ok() else "not answering"}, "after": {"value": "answering"},
                           "costs": ["No silence, nothing restarts."],
                           "verify": "golem checks that REAPER answers within 15 s.", "undo": "",
                           "apply_label": "Resync"},
    },
    "reaper_restart": {
        "label": "Restart REAPER",
        "description": "Restart the audio engine. The current preset is posed again. Silence for 10 to 30 s.",
        "risk": "modify", "live_allowed": False, "help": ["help/no-sound", "golem/health"],
        "params": lambda: {"type": "object", "properties": {}},
        "run": _run_restart, "verify": _verify_engine, "timeout": ENGINE_BACK_S,
        "plan": lambda p: {"title": "Fix: restart the engine", "why": "REAPER is not running, or not answering even "
                           "after a resync. Restarting it reloads its scripts and poses the preset again.",
                           "before": {"value": "down" if not getattr(_st(), "reaper_running", False)
                                      else "running" if _engine_ok() else "not answering"},
                           "after": {"value": "running"},
                           "costs": ["Silence for 10 to 30 s while REAPER starts. Not during a take or a song."],
                           "verify": "golem checks that REAPER answers again.", "undo": "",
                           "apply_label": "Restart REAPER"},
    },
    "audio_reset": {
        "label": "Reopen the sound card",
        "description": "Ask REAPER to close and reopen the sound card. For an audio thread that stopped while the "
                       "card is still plugged in.",
        "risk": "modify", "live_allowed": False, "help": ["help/no-sound", "golem/soundcard"],
        "params": lambda: {"type": "object", "properties": {}},
        "run": _run_audio_reset, "verify": _verify_audio,
        "plan": lambda p: {"title": "Fix: the sound card stopped", "why": "The card is plugged in but REAPER's audio "
                           "thread is not running. Reopening the card usually brings it back.",
                           "before": {"value": "running" if _audio_ok() else "stopped"}, "after": {"value": "running"},
                           "costs": ["A second of silence."],
                           "verify": "golem checks that the audio thread runs again within 20 s.", "undo": "",
                           "apply_label": "Reopen the card"},
    },
    "midi_reinit": {
        "label": "Reopen MIDI devices",
        "description": "Ask REAPER to reopen its MIDI devices. For a pedalboard or keyboard plugged after REAPER "
                       "started, or that stopped answering.",
        "risk": "modify", "live_allowed": False, "help": ["golem/hardware"],
        "params": lambda: {"type": "object", "properties": {}},
        "run": _run_midi_reinit, "verify": _verify_midi,
        "plan": lambda p: {"title": "Fix: MIDI devices", "why": "REAPER opens MIDI devices only when it starts; a "
                           "device plugged later, or one that dropped, needs them reopened.",
                           "before": {"value": "MIDI problem"}, "after": {"value": "reopened"},
                           "costs": ["No sound change."],
                           "verify": "golem checks the MIDI report within 20 s.", "undo": "",
                           "apply_label": "Reopen MIDI"},
    },
    "repose_preset": {
        "label": "Pose the preset again",
        "description": "Rebuild the current preset from scratch in REAPER. For a NAM model or IR that did not load.",
        "risk": "modify", "live_allowed": False, "help": ["help/no-sound", "sound/captures"],
        "params": lambda: {"type": "object", "properties": {}},
        "run": _run_repose, "verify": _verify_rig,
        "plan": lambda p: {"title": "Fix: files not loaded", "why": "A model or IR of the current preset did not load. "
                           "Posing the preset again rebuilds every block and reloads its files.",
                           "before": {"value": "files missing"}, "after": {"value": "rebuilt"},
                           "costs": ["Half a second to a few seconds of silence while the preset is rebuilt."],
                           "verify": "golem checks that every file loaded.", "undo": "",
                           "apply_label": "Pose it again"},
    },
    "silence_hunt": {
        "label": "Why no sound?",
        "description": "Read the levels along the chain while the musician plays for four seconds, and name the "
                       "first silent stage. Read-only.",
        "risk": "read", "live_allowed": True, "help": ["help/no-sound"],
        "params": lambda: {"type": "object", "properties": {"seconds": {"type": "integer", "minimum": 1, "maximum": 10}}},
        "run": _run_silence, "verify": _verify_none,
        "plan": lambda p: {"title": "Why no sound?", "why": "Reads levels along the chain while you play.",
                           "costs": ["Read-only. You play for four seconds."], "verify": "", "undo": "",
                           "apply_label": "Run"},
    },
    "health_facts": {
        "label": "Read the facts",
        "description": "Read every Health fact again now (engine, card, dropouts, pedalboard, files, disk). Read-only.",
        "risk": "read", "live_allowed": True, "help": ["golem/health"],
        "params": lambda: {"type": "object", "properties": {}},
        "run": _run_facts, "verify": _verify_none,
        "plan": lambda p: {"title": "Read the facts", "why": "", "costs": ["Read-only."], "verify": "", "undo": "",
                           "apply_label": "Read"},
    },
}


def label_for(name, params=None):
    """Le libellé d'une action AVEC ses paramètres (le buffer monte ou descend) — celui du registre sinon."""
    a = ACTIONS.get(name) or {}
    with contextlib.suppress(Exception):
        if a.get("label_for"):
            return a["label_for"](params or {})
    return a.get("label") or name


def registry():
    """Ce que la machine sait faire, tel qu'un appelant (l'écran, doctor, un modèle) peut le lire — sans le code."""
    out = []
    for name, a in ACTIONS.items():
        out.append({"name": name, "label": a["label"], "description": a["description"], "risk": a["risk"],
                    "params": a["params"](), "live_allowed": a["live_allowed"], "help": a["help"]})
    return out


def validate(name, params=None):
    """(params normalisés, None) ou (None, raison en anglais). Le schéma est la seule porte : action inconnue, champ
    en trop, type, énumération, bornes."""
    a = ACTIONS.get(name)
    if not a:
        return None, f"unknown action '{name}'"
    params = dict(params or {})
    schema = a["params"]()
    props = schema.get("properties") or {}
    for k in params:
        if k not in props:
            return None, f"'{name}' takes no parameter '{k}'"
    for k in schema.get("required") or []:
        if k not in params:
            return None, f"'{name}' needs '{k}'"
    for k, v in params.items():
        spec = props[k]
        if spec.get("type") == "integer" and (type(v) is not int):
            return None, f"'{k}' must be an integer"
        if "enum" in spec and v not in spec["enum"]:
            return None, f"'{k}' must be one of {spec['enum']}"
        if "minimum" in spec and v < spec["minimum"] or "maximum" in spec and v > spec["maximum"]:
            return None, f"'{k}' is out of range"
    return params, None


def blocked(name):
    """Pourquoi on ne peut pas lancer cette action maintenant — ou None. La garde est LOCALE : ni l'écran ni un
    modèle ne la lèvent (P4)."""
    a = ACTIONS.get(name) or {}
    if a.get("live_allowed"):
        return None
    with contextlib.suppress(Exception):
        from . import reamp
        why = reamp.busy_reason(idle=False)
        if why:
            return {"gig mode": "not in gig mode", "mode locked": "not while the mode is locked"}.get(why, f"not while {why}")
    with _lock:
        if _run["cur"] and _run["cur"]["phase"] in ("running", "verifying"):
            return "another fix is running"
    return None


def suggest(fact):
    """L'action du registre qui répond à un fait orange ou rouge de Health — ou None (la ligne garde alors son lien
    vers l'écran qui règle). Rend {action, params, label}."""
    fid, lvl = fact.get("id"), fact.get("level")
    if lvl not in ("warn", "bad"):
        return None
    st = _st()
    if fid == "dropouts":
        cur, sizes = _bsize(), _buffer_sizes()
        nxt = next((s for s in sizes if cur and s > cur), None)
        return {"action": "set_buffer", "params": {"size": nxt}} if nxt else None
    if fid == "engine":
        return {"action": "osc_refresh" if getattr(st, "reaper_running", False) else "reaper_restart", "params": {}}
    if fid == "audio":
        a = getattr(st, "audio", None) or {}
        if a.get("card") or "not connected" in str(a.get("why") or ""):
            return None                                   # une carte débranchée se rebranche, elle ne se « répare » pas
        return {"action": "audio_reset", "params": {}}
    if fid == "pedalboard" and (getattr(st, "midi", None) or {}).get("ok") is False:
        return {"action": "midi_reinit", "params": {}}
    if fid == "playing" and not getattr(st, "rig_error", None) and (getattr(st, "rig_check", None) or {}).get("ok") is False:
        return {"action": "repose_preset", "params": {}}
    if fid == "scripts":
        return {"action": "reaper_restart", "params": {}}
    return None


def repair_for(fact):
    """Pour `health.compute()` : le geste « Fix… » d'un fait, avec sa garde dite d'avance."""
    s = suggest(fact)
    if not s:
        return None
    a = ACTIONS[s["action"]]
    return {"action": s["action"], "params": s["params"], "label": "Fix…", "title": label_for(s["action"], s["params"]),
            "blocked": blocked(s["action"])}


def plan(name, params=None):
    """La feuille : validée, décrite, avec la garde du moment. Rien n'est exécuté."""
    p, err = validate(name, params)
    if err:
        return {"ok": False, "error": err}
    a = ACTIONS[name]
    doc = a["plan"](p)
    return {"ok": True, "action": name, "params": p, "risk": a["risk"], "blocked": blocked(name), **doc}


def status():
    with _lock:
        cur, last = _run["cur"], _run["last"]
        return {"current": dict(cur) if cur else None, "last": dict(last) if last else None}


def _event(rec):
    with contextlib.suppress(Exception):
        from . import diag
        diag.event("fix", id=rec.get("incident"), action=rec["action"], params=rec["params"], by=rec["by"],
                   verify="ok" if rec["phase"] == "done" else "ko", ms=int((rec.get("ended_at", time.time()) - rec["started_at"]) * 1000))


def _finish(rec, ok, text):
    rec.update(phase="done" if ok else "failed", text=text, ended_at=round(time.time(), 3))
    with _lock:
        _run["last"], _run["cur"] = dict(rec), None
    _event(rec)
    log.info(f"réparation {rec['action']} {rec['params']} ({rec['by']}) → {'ok' if ok else 'ko'} : {text}")
    with contextlib.suppress(Exception):
        from . import incidents
        incidents.fix_done(rec.get("incident"), rec, ok)


def _verify_loop(rec, verify, timeout):
    ctx = {"t0": time.time(), "timeout": timeout}
    while True:
        now = time.time()
        try:
            verdict, text = verify(ctx, now)
        except Exception as e:
            _swallowed(e)
            verdict, text = "ko", "the check failed"
        with _lock:
            if _run["cur"] is rec:
                rec["text"] = text
        if verdict != "wait":
            _finish(rec, verdict == "ok", text)
            return
        time.sleep(VERIFY_POLL_S)


async def apply(name, params=None, by="button", incident=None):
    """Exécute, puis vérifie en arrière-plan. Rend tout de suite {ok, fix} ou {ok: False, error} — la garde, le
    schéma et « une réparation à la fois » sont revérifiés ici, quoi qu'ait dit la feuille."""
    p, err = validate(name, params)
    if err:
        return {"ok": False, "error": err, "status": 400}
    why = blocked(name)
    if why:
        return {"ok": False, "error": why, "status": 409}
    a = ACTIONS[name]
    by = by if by in ("button", "assistant", "doctor", "undo") else "button"
    before = _bsize() if name == "set_buffer" else None
    rec = {"id": uuid.uuid4().hex[:8], "action": name, "params": p, "by": by, "incident": incident,
           "label": label_for(name, p), "phase": "running", "text": "starting…", "started_at": round(time.time(), 3)}
    if a.get("undo"):
        rec["undo"] = a["undo"](p, before)
    with _lock:
        if _run["cur"] and _run["cur"]["phase"] in ("running", "verifying"):
            return {"ok": False, "error": "another fix is running", "status": 409}
        _run["cur"] = rec
    if incident:
        with contextlib.suppress(Exception):
            from . import incidents
            incidents.fix_started(incident, rec)
    try:
        r = await a["run"](p)
    except Exception as e:
        _swallowed(e)
        r = {"ok": False, "error": str(e)}
    body = r
    if hasattr(r, "body"):                                # une JSONResponse d'une route existante : son erreur
        import json
        with contextlib.suppress(Exception):
            body = json.loads(r.body)
        body = {"ok": False, **(body if isinstance(body, dict) else {})}
    if not (isinstance(body, dict) and body.get("ok", True) is not False):
        _finish(rec, False, str((body or {}).get("error") or "the action was refused"))
        return {"ok": False, "error": rec["text"], "status": 409, "fix": dict(rec)}
    with _lock:
        rec["phase"] = "verifying"
    threading.Thread(target=_verify_loop, args=(rec, a["verify"], a.get("timeout", ENGINE_BACK_S)),
                     name="golem-fix-verify", daemon=True).start()
    return {"ok": True, "fix": dict(rec)}
