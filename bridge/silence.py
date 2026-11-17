# SPDX-License-Identifier: GPL-3.0-or-later
"""« WHY NO SOUND? » (docs/health.md §4.1) — la chasse au silence, depuis l'écran. Photographie le rig AU MOMENT où le
son manque, AVANT qu'on relance quoi que ce soit (relancer efface la scène du crime : CLAUDE.md), en lecture seule,
et dit OÙ le signal s'arrête, du plus amont au plus aval : carte perdue → pas d'entrée → pas de sortie matérielle →
le signal sort de REAPER (le silence est en aval) → il s'arrête dans la chaîne (NAM/IR sans fichier, branche muette)
→ il est dans les branches mais pas sur la piste de sortie (merge).

C'est la logique de tools/check-silence.py (2026-09-07), portée ici pour que le musicien l'ait sous le doigt ; l'outil
appelle désormais cette route. Sondes : les probes read-only de golem_apply (peaks, chunkdump, dumpfx), chacune par le
SLOT UNIQUE .command.json — on échantillonne donc peu (4 fois en 4 s), jamais pendant une prise ou une chanson
(reamp.busy_reason sans la règle d'inactivité : le musicien JOUE pendant la mesure, c'est le but). Le rapport est
gardé dans presets/.silence-<hhmmss>.json, comme avant, pour la relecture à froid."""
import contextlib
import json
import os
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("silence")
SILENT_DB = -60.0                 # en dessous : pas de signal
SAMPLES = 4                       # relevés de crêtes pendant l'écoute — chacun prend le slot de commande
_lock = threading.Lock()
_S = {"phase": "idle", "started": None, "seconds": 4.0, "play_until": None, "report": None, "error": None, "at": None}

PEAKS = lambda: os.path.join(C.PRESETS_DIR, ".peaks.json")        # noqa: E731
CHUNK = lambda: os.path.join(C.PRESETS_DIR, ".chunk.log")         # noqa: E731
FXDUMP = lambda: os.path.join(C.PRESETS_DIR, ".fxdump.json")      # noqa: E731


def status():
    with _lock:
        d = dict(_S)
    d["now"] = round(time.time(), 3)
    return d


def _set(**kw):
    with _lock:
        _S.update(kw)


def _probe(cmd, out, timeout=6.0):
    """Vide `out`, pose la commande, attend que REAPER l'ait réécrit. None si muet (moteur gelé ou absent)."""
    from .commands import write_command
    with contextlib.suppress(OSError):
        open(out, "w").close()
    write_command(cmd)
    t0 = time.time()
    while time.time() - t0 < timeout:
        with contextlib.suppress(OSError):
            if os.path.getsize(out) > 0:
                time.sleep(0.15)
                with open(out, encoding="utf-8", errors="replace") as f:
                    return f.read()
        time.sleep(0.1)
    return None


def _peaks_max(seconds, samples=SAMPLES):
    best = {}
    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds and n < samples:
        txt = _probe({"action": "peaks", "clear": False}, PEAKS(), timeout=3)
        n += 1
        if not txt:
            break
        try:
            rows = json.loads(txt)
        except ValueError:
            break
        for r in rows:
            name = r["track"].split(" ", 1)[1] if " " in str(r.get("track", "")) else str(r.get("track", ""))
            cur = best.setdefault(name, {"inst": -150.0})
            cur.update({k: r.get(k) for k in ("vol_db", "mute", "hw_sends", "sends")})
            cur.update({k: r[k] for k in ("root", "rig") if k in r})    # les marques d'un moteur qui ne nomme pas comme REAPER
            cur["inst"] = max(cur["inst"], float(r.get("instL", -150)), float(r.get("instR", -150)))
        time.sleep(max(0.0, seconds / samples))
    return best


def _engine_name(eng):
    """Le nom du moteur qui joue, pour l'écran (« REAPER », « Golem Engine »)."""
    with contextlib.suppress(Exception):
        return (eng.descriptor() or {}).get("name") or "REAPER"
    return "REAPER"


def _chunk_facts(track):
    txt = _probe({"action": "chunkdump", "track": track, "find": None}, CHUNK())
    if not txt or txt.startswith("piste introuvable") or txt.startswith("aucune piste"):
        return None
    facts = {"rec": None, "mute": None, "hwout": [], "mainsend": None}
    for line in txt.splitlines():
        t = line.strip()
        if t.startswith("REC "):
            facts["rec"] = t
        elif t.startswith("MUTESOLO "):
            facts["mute"] = t
        elif t.startswith("HWOUT "):
            facts["hwout"].append(t)
        elif t.startswith("MAINSEND "):
            facts["mainsend"] = t
    return facts


def _fx_facts():
    txt = _probe({"action": "dumpfx"}, FXDUMP(), timeout=8)
    if not txt:
        return None
    try:
        data = json.loads(txt)
    except ValueError:
        return None
    out = {}
    for t in data:
        rows = []
        for fx in t.get("fx") or []:
            files = {p["name"]: p.get("disp") for p in fx.get("params") or []
                     if p.get("name") in ("Neural Model", "Impulse Response")}
            rows.append({"i": fx.get("fx"), "plugin": fx.get("plugin"), "files": files})
        out[t.get("track")] = rows
    return out


def is_rig(name, row):
    """Une piste DU RIG ? REAPER : son nom (« Sandbox #… ») ; un moteur qui nomme autrement le dit dans la sonde (`rig`)."""
    return bool(row["rig"]) if "rig" in row else str(name).startswith("Sandbox #")


def is_root(name, row):
    """L'ENTRÉE d'une lane ? REAPER : la piste racine « Sandbox #Input N » ; ailleurs la marque `root` de la sonde (le
    Golem Engine : ses pistes golem:inN, vumètre à l'entrée de la carte)."""
    if "root" in row:
        return bool(row["root"])
    return str(name).startswith("Sandbox #Input ") and "/" not in name and "#merge" not in name


def _roots(peaks):
    return sorted(n for n in peaks if is_root(n, peaks[n]))


def verdict(st, peaks, chunk, fx, waited=True):
    """Le verdict, du plus amont au plus aval — en anglais, pour l'écran. `level` : bad = le rig ou la carte ;
    ok = le signal sort du moteur, le rig n'y est pour rien. `st["engine_name"]` : le moteur qui joue (REAPER par
    défaut) ; `fx` : les fichiers lus sur les plugins (REAPER, dumpfx) ou `st["missing"]`, déjà établi (rig-check)."""
    au = (st.get("audio") or {}) if isinstance(st, dict) else {}
    eng = (st.get("engine_name") if isinstance(st, dict) else None) or "REAPER"
    roots = _roots(peaks)
    root_sig = any(peaks[n]["inst"] > SILENT_DB for n in roots)
    outs = [n for n in peaks if is_rig(n, peaks[n]) and (peaks[n].get("hw_sends") or 0) > 0 and not peaks[n].get("mute")]
    out_sig = any(peaks[n]["inst"] > SILENT_DB for n in outs)
    down_sig = any(peaks[n]["inst"] > SILENT_DB for n in peaks if is_rig(n, peaks[n]) and n not in roots)
    missing = list((st.get("missing") if isinstance(st, dict) else None) or [])
    for tname, rows in (fx or {}).items():
        if not str(tname).startswith("Sandbox #"):
            continue
        for r in rows:
            for pname, disp in (r.get("files") or {}).items():
                if not disp:
                    missing.append({"track": tname, "fx": r.get("i"), "plugin": (r.get("plugin") or "")[:34], "param": pname})
    if au.get("ok") is False:
        return {"code": "card", "level": "bad", "stage": "sound card",
                "title": "The sound card is lost — not the rig.",
                "text": f"The audio thread stopped ({au.get('why') or 'no witness'}). Reset the audio device or restart {eng} from the Dashboard."}
    if not peaks:
        return {"code": "probe", "level": "bad", "stage": "engine",
                "title": f"{eng} did not answer the probe.",
                "text": f"The engine may be frozen: a plugin that stalls on load (quarantine it), or restart {eng} from the Dashboard."}
    if not root_sig:
        rec = " · ".join(f"{n}: {((chunk or {}).get(n) or {}).get('rec') or 'REC ?'}" for n in roots) or "no input track"
        # l'armement d'une piste est une affaire de REAPER : un moteur qui n'a pas cette sonde (chunk None) n'en parle pas
        armed = f", and that the track is armed ({rec})" if chunk is not None else ""
        return {"code": "input", "level": "bad", "stage": "input",
                "title": "No signal reaches the input tracks.",
                "text": (f"Nothing above {int(SILENT_DB)} dBFS on the inputs while you played: check the cable, the card's input and its gain"
                         f"{armed}.") + ("" if waited else " Measured without anyone playing — normal when idle.")}
    if not outs:
        return {"code": "routing", "level": "bad", "stage": "output routing",
                "title": "No live track has a hardware output.",
                "text": "The signal has nowhere to go: the output routing — the mixer, the card's output patch, or a lane without an OUT."}
    if out_sig:
        return {"code": "downstream", "level": "ok", "stage": f"after {eng}",
                "title": "The signal leaves the golem — the silence is after it.",
                "text": "A track with a hardware output carries level. Look at the card's MONITOR knob, the system volume, the cables and the monitors — the rig is fine."}
    if not down_sig:
        if missing:
            m = missing[0]
            return {"code": "chain", "level": "bad", "stage": "FX chain",
                    "title": "The signal enters, then stops inside the chain.",
                    "text": f"{m['track']} FX #{m['fx']} ({m['plugin']}): {m['param']} is empty — the model or IR did not load. Download it again or pick another one."
                            + (f" {len(missing) - 1} more empty." if len(missing) > 1 else ""), "missing": missing}
        return {"code": "chain", "level": "bad", "stage": "FX chain",
                "title": "The signal enters, then stops inside the chain.",
                "text": "No level after the input track: a branch is muted or an effect swallows the signal — see the tracks below."}
    return {"code": "merge", "level": "bad", "stage": "merge",
            "title": "Signal in the branches, none on the output track.",
            "text": "The merge send or its level (mixer), or the active branch is muted."}


def hunt(seconds=4.0, waited=True):
    """La chasse, synchrone (appelée dans un fil par `start`) : état, crêtes pendant `seconds`, chunk des pistes
    d'entrée, fichiers des NAM/IR, verdict ; rapport écrit dans presets/.silence-<hhmmss>.json."""
    from .state import state
    from . import engine
    eng = engine.active()
    name = _engine_name(eng)
    st = {"reaper_running": state.reaper_running, "reaper_connected": state.reaper_connected, "audio": state.audio,
          "latency_ms": state.latency_ms, "xruns": state.xruns, "rig_check": state.rig_check,
          "preset_id": state.preset_id, "preset_name": state.preset_name, "scene_id": state.scene_id,
          "engine": eng.id, "engine_name": name}
    report = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "state": st, "seconds": seconds}
    if not state.reaper_running:
        report["verdict"] = {"code": "engine", "level": "bad", "stage": "engine", "title": f"{name} is not running.",
                             "text": "The only case where restarting is the answer: start it from the Dashboard."}
        report["tracks"] = []
        return report
    _set(phase="listening", play_until=round(time.time() + seconds, 3))
    peaks = _peaks_max(seconds)
    _set(phase="reading", play_until=None)
    roots = _roots(peaks)
    # les sondes de REAPER (chunk d'une piste, valeurs lues sur les plugins) n'existent que là où le moteur les a ; un
    # autre moteur dit ses fichiers manquants par sa vérification du rig (.rig-check.json, lue sur les plugins aussi)
    chunk = ({n: _chunk_facts(n) for n in roots} if peaks else {}) if eng.supports("chunkdump") else None
    fx = _fx_facts() if peaks and eng.supports("dumpfx") else None
    if not eng.supports("dumpfx"):
        st["missing"] = [{"track": i.get("track"), "fx": i.get("fx"), "plugin": i.get("kind") or "file",
                          "param": "its file", "expected": i.get("expected")}
                         for i in ((state.rig_check or {}).get("issues") or []) if isinstance(i, dict)]
    report["verdict"] = verdict(st, peaks, chunk, fx, waited=waited)
    report["tracks"] = [{"name": n, "peak_db": round(p["inst"], 1), "vol_db": p.get("vol_db"), "mute": bool(p.get("mute")),
                         "hw_sends": p.get("hw_sends"), "sends": p.get("sends")}
                        for n, p in sorted(peaks.items()) if is_rig(n, p) or is_root(n, p)]
    report["chunk"] = chunk or {}
    report["missing"] = report["verdict"].get("missing") or []
    try:
        path = os.path.join(C.PRESETS_DIR, time.strftime(".silence-%H%M%S.json"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({**report, "peaks": peaks, "fx": fx}, f, ensure_ascii=False, indent=1)
        report["file"] = os.path.relpath(path, C.ROOT)
    except OSError as e:
        _swallowed(e)
    log.info(f"chasse au silence : {report['verdict']['code']} — {report['verdict']['title']}")
    return report


def start(seconds=4.0, waited=True):
    """Lance la chasse dans un fil. Refuse si une chasse tourne, si REAPER est absent, ou si le rack n'est pas libre
    (prise, chanson, chargement, mode scène) — rend {ok, why}."""
    from .state import state
    with _lock:
        if _S["phase"] in ("listening", "reading"):
            return {"ok": False, "why": "a hunt is already running"}
    if not state.reaper_running:
        from . import engine
        return {"ok": False, "why": f"{_engine_name(engine.active())} is not running — start it from the Dashboard, there is nothing to measure"}
    why = None
    with contextlib.suppress(Exception):
        from . import reamp
        why = reamp.busy_reason(idle=False)
    if why:
        return {"ok": False, "why": f"not now: {why}"}
    seconds = min(max(float(seconds or 4.0), 1.0), 10.0)
    _set(phase="listening", started=round(time.time(), 3), seconds=seconds, report=None, error=None, at=None)

    def run():
        try:
            rep = hunt(seconds, waited=waited)
            _set(phase="done", report=rep, at=round(time.time(), 3), play_until=None)
            # un verdict rouge ouvre un incident, un vert ferme celui qui l'était (docs/assistant.md §3.1) — seulement
            # quand le musicien a joué : une mesure à blanc ne prouve rien
            v = rep.get("verdict") or {}
            if waited and v.get("level") in ("bad", "ok"):
                with contextlib.suppress(Exception):
                    from . import incidents
                    incidents.probe("silence", v.get("code"), v.get("level") == "bad", "No sound: " + str(v.get("stage") or ""),
                                    v.get("title"))
        except Exception as e:
            _swallowed(e)
            _set(phase="error", error=str(e)[:200], at=round(time.time(), 3), play_until=None)

    threading.Thread(target=run, name="golem-silence", daemon=True).start()
    return {"ok": True, "seconds": seconds}


def clear():
    _set(phase="idle", started=None, report=None, error=None, play_until=None, at=None)
    return {"ok": True}
