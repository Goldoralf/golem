# SPDX-License-Identifier: GPL-3.0-or-later
"""SETTINGS ▸ HEALTH, la couche « Now » (docs/health.md §1.1, maquette mockups/health.html, 2026-10-20) : des FAITS
datés, lus sans rien toucher, chacun avec sa SOURCE et, quand il est orange ou rouge, le GESTE qui répare. Jamais une
estimation : ce que le bridge n'a pas mesuré est dit « wait », pas inventé (CLAUDE.md : vérifier avant d'affirmer).

Un fil rafraîchit les faits toutes les 5 s (`start`) ; `brief()` — niveau, titre, compte — est O(1) et part dans
`state.snapshot()` pour le point de santé de la barre du haut ; `facts()` rend la liste entière à la page
(`GET /api/health/facts`). Les faits chers (l'état des blocs de la setlist active) sont mis en cache 60 s.

La DÉRIVE DE L'ENVIRONNEMENT (docs/health.md §4.2) vit ici aussi : à chaque passage, ce qui ne devrait pas changer
tout seul — versions de golem et de REAPER, OS, carte, fréquence, buffer, nombre de plugins, gouverneur — est comparé
au dernier instantané (`config/.env-snapshot.json`, local) ; un changement est daté et dit sur la ligne
« Since last boot ». La moitié des « ça marchait hier » tiennent là."""
import contextlib
import json
import os
import platform
import sys
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("health")
START = time.time()                      # le départ du bridge : « since start » se compte d'ici
REFRESH_S = 5.0                          # les faits se relisent toutes les 5 s (le fil, ou à la demande)
SETLIST_CACHE_S = 60.0                   # l'état des blocs de la setlist active : le seul fait cher
FM_GRACE_S = 15.0                        # le lien golem.fm met quelques secondes à s'ouvrir après le démarrage
XRUN_BURST = 10                          # ≥ 10 décrochages en 10 min : rouge (le seuil du paquet `event` de diag)
DISK_WARN_GB, DISK_BAD_GB = 20.0, 5.0
ENV_PATH = lambda: os.path.join(C.CONFIG_DIR, ".env-snapshot.json")   # noqa: E731 — le dossier de config du MOMENT
ENV_CHANGES_KEPT = 30
ENV_SOFT = ("golem",)                    # change à chaque mise à jour voulue : dit, jamais une alerte
# ce qui se compare entre deux passages, et comment on le nomme à l'écran
ENV_LABELS = {"golem": "golem", "reaper": "REAPER", "os": "OS", "card": "sound card", "samplerate": "sample rate",
              "bsize": "buffer", "plugins": "plugins", "governor": "CPU governor", "kernel": "kernel"}

# ok < wait < warn < bad : « wait » n'alarme jamais (pas encore mesuré, ou sans objet ici)
_RANK = {"ok": 0, "wait": 1, "warn": 2, "bad": 3}
_lock = threading.Lock()
_cache = {"at": 0.0, "doc": None}
_setlist_cache = {"key": None, "at": 0.0, "value": None}
_thread = {"on": False}


def _fact(fid, name, level, text, source, fix=None, detail=None):
    d = {"id": fid, "name": name, "level": level if level in _RANK else "wait", "text": str(text), "source": source}
    if fix:
        d["fix"] = fix                   # {"label": "Download →", "go": "songs/setlists"} — une navigation ; l'ACTION, quand le
                                         # registre en a une, est `repair` (posé par compute, bridge/fixes.py)
    if detail:
        d["detail"] = detail
    return d


def _hhmm(t):
    try:
        return time.strftime("%H:%M", time.localtime(float(t)))
    except (TypeError, ValueError, OverflowError):
        return "?"


def _ago(t, now=None):
    """« 3 min ago » / « 2 h ago » — le bridge compare SES horloges, jamais celle de l'écran."""
    if not t:
        return ""
    s = max(0, (now or time.time()) - float(t))
    if s < 90:
        return f"{int(s)} s ago"
    if s < 5400:
        return f"{int(round(s / 60))} min ago"
    return f"{s / 3600:.0f} h ago"


# ── les faits, un par un (chacun tolérant : une sonde qui casse rend « wait », jamais une exception) ────────────────
def _f_engine(st):
    running, connected = bool(getattr(st, "reaper_running", False)), bool(getattr(st, "reaper_connected", False))
    ver = None
    with contextlib.suppress(Exception):
        from .rigstatus import reaper_version
        ver = reaper_version()
    name = "REAPER" + (f" {ver}" if ver else "")
    src = "reaper_running · reaper_connected"
    if running and connected:
        return _fact("engine", "Engine", "ok", f"{name} · running · talking to the bridge", src)
    if running:
        return _fact("engine", "Engine", "warn", f"{name} started but is not answering the bridge", src,
                     fix={"label": "Dashboard →", "go": "system/sys"})
    if getattr(st, "rig_loading", None) or (time.time() - START) < 60:
        return _fact("engine", "Engine", "wait", f"{name} is starting…", src)
    return _fact("engine", "Engine", "bad", f"{name} is not running — no sound until it is", src,
                 fix={"label": "Dashboard →", "go": "system/sys"})


def _f_audio(st):
    a = getattr(st, "audio", None) or {}
    eng = None
    with contextlib.suppress(Exception):
        from .rigstatus import engine_doc
        eng = engine_doc()
    eng = eng or {}
    device = eng.get("device") or a.get("card") or (getattr(st, "audio_metrics", None) or {}).get("driver") or "sound card"
    bits = [str(device)]
    if eng.get("samplerate"):
        bits.append(f"{eng['samplerate'] / 1000:g} kHz")
    if eng.get("bsize"):
        bits.append(f"{eng['bsize']} samples")
    lat = getattr(st, "latency_ms", None) if getattr(st, "latency_ms", None) is not None else eng.get("latency_ms")
    if lat is not None:
        bits.append(f"{float(lat):.1f} ms")
    src = "audio_metrics · .clock.json"
    if a.get("ok") is True:
        return _fact("audio", "Sound card", "ok", " · ".join(bits), src)
    if a.get("ok") is False:
        why = a.get("why") or "the audio thread is not running"
        return _fact("audio", "Sound card", "bad", f"{device} — {why}" + (f" · {a['fix']}" if a.get("fix") else ""), src,
                     fix={"label": "Soundcard →", "go": "system/gear/sound"})
    return _fact("audio", "Sound card", "wait", f"{device} — waits for the engine", src)


def _f_dropouts(st):
    total = int(getattr(st, "xruns", 0) or 0)
    recent = int(getattr(st, "xruns_recent", 0) or 0)
    last = getattr(st, "xruns_last", None)
    src = "xruns"
    if recent <= 0:
        return _fact("dropouts", "Dropouts", "ok", f"0 in the last 10 min · {total} since start"
                     + (f" · last {_ago(last)}" if last else ""), src)
    lvl = "bad" if recent >= XRUN_BURST else "warn"
    return _fact("dropouts", "Dropouts", lvl, f"{recent} in the last 10 min · {total} since start · last {_ago(last)}", src,
                 fix={"label": "Buffer →", "go": "system/sys"})


def _f_pedalboard(st):
    pb = None
    with contextlib.suppress(Exception):
        from . import pedalboard
        pb = pedalboard.active()
    pb = pb or (getattr(st, "pedalboard", None) or {})
    midi = getattr(st, "midi", None) or {}
    src = "pedalboard · .midi.json"
    name = pb.get("name") or pb.get("id") or "pedalboard"
    if midi.get("ok") is False and midi.get("issues"):
        issue = midi["issues"][0]
        issue = issue.get("text") or issue.get("msg") if isinstance(issue, dict) else str(issue)
        return _fact("pedalboard", "Pedalboard & MIDI", "warn", str(issue)[:140], src,
                     fix={"label": "Pedalboard →", "go": "system/gear/board"})
    if pb.get("source") == "measured" and not pb.get("stale"):
        return _fact("pedalboard", "Pedalboard & MIDI", "ok", f"{name} · confirmed by the chip"
                     + (f" · firmware {pb['firmware']}" if pb.get("firmware") else ""), src)
    if pb.get("source") == "measured":
        return _fact("pedalboard", "Pedalboard & MIDI", "warn", f"{name} · measured earlier, the last probe got no answer — still usable",
                     src, fix={"label": "Pedalboard →", "go": "system/gear/board"})
    if pb.get("source") == "declared":
        return _fact("pedalboard", "Pedalboard & MIDI", "wait", f"{name} · declared, not confirmed — press a switch", src)
    return _fact("pedalboard", "Pedalboard & MIDI", "wait", "no pedalboard declared", src)


def _f_playing(st):
    name = getattr(st, "preset_name", None) or getattr(st, "preset_id", None)
    rc = getattr(st, "rig_check", None) or {}
    err = getattr(st, "rig_error", None)
    src = ".rig-check.json" + (f" {_hhmm(rc['t'])}" if rc.get("t") else "") + " · .livemap.json"
    if err:
        txt = err.get("error") or err.get("why") or str(err) if isinstance(err, dict) else str(err)
        return _fact("playing", "Playing", "bad", f"the last recall was refused — {str(txt)[:120]}", src,
                     fix={"label": "Presets →", "go": "songs/presets"})
    if not name:
        return _fact("playing", "Playing", "wait", "nothing loaded yet", src)
    label = f"“{str(name).replace('⛓', '', 1).strip()}”"
    if rc.get("ok") is True:
        n = rc.get("checked") or 0
        return _fact("playing", "Playing", "ok", f"{label} · {n} file{'s' if n != 1 else ''} loaded and checked", src)
    if rc.get("ok") is False:
        issues = [i for i in rc.get("issues") or [] if isinstance(i, dict)]
        kinds = sorted({str(i.get("kind") or "file") for i in issues})
        unrepaired = [i for i in issues if not i.get("repaired")]
        lvl = "bad" if unrepaired else "warn"
        what = f"{len(unrepaired)} file{'s' if len(unrepaired) != 1 else ''} not loaded" if unrepaired \
            else f"{len(issues)} file{'s' if len(issues) != 1 else ''} repaired after the build"
        return _fact("playing", "Playing", lvl, f"{label} · {what} ({', '.join(kinds)})", src,
                     fix={"label": "Blocks →", "go": "designer"} if unrepaired else None)
    return _fact("playing", "Playing", "wait", f"{label} · not verified yet", src)


def _setlist_status():
    """Les blocs de CHAQUE preset de la setlist active, résumé — cher (manifeste, inventaire) : cache 60 s, clé
    (setlist, mtime de son fichier, date de l'inventaire)."""
    from . import setlists as SL
    from . import blockstatus as BS
    from . import store
    sid = SL.active_id()
    sl = SL.load(sid)
    if not sl:
        return None
    try:
        mtime = os.path.getmtime(SL._path(sid))
    except OSError:
        mtime = 0
    inv_at = None
    with contextlib.suppress(Exception):
        inv_at = (BS.inventory() or {}).get("at")
    key = (sid, mtime, inv_at)
    now = time.time()
    with _lock:
        if _setlist_cache["key"] == key and now - _setlist_cache["at"] < SETLIST_CACHE_S:
            return _setlist_cache["value"]
    pids = [p for p in (sl.get("presets") or []) if p]
    seen, out = set(), {"id": sid, "name": sl.get("name") or sid, "presets": 0, "not_ready": [], "missing_blocks": 0,
                        "download_bytes": 0, "inventory": True,
                        # POURQUOI ça ne jouera pas (2026-10-20 : « je ne comprends pas… toutes les setlists sont là ») :
                        # un plugin absent de cette machine, un format de capture que ce moteur ne lit pas, une capture à
                        # télécharger — les raisons de blockstatus, comptées, pour une phrase qui explique
                        "reasons": {"plugin": 0, "format": 0, "capture": 0, "other": 0}}
    for pid in pids:
        if pid in seen:
            continue
        seen.add(pid)
        try:
            p = store.load_preset(pid)
        except Exception as e:
            _swallowed(e)
            p = None
        if not p:
            continue
        out["presets"] += 1
        try:
            s = BS.preset_status(p)
        except Exception as e:
            _swallowed(e)
            continue
        out["inventory"] = out["inventory"] and bool((s.get("caps") or {}).get("inventory"))
        sm = s.get("summary") or {}
        for b in s.get("blocks") or []:
            if b.get("state") != "ready":
                r = b.get("reason") if b.get("reason") in ("plugin", "format", "capture") else ("capture" if b.get("state") == "download" else "other")
                out["reasons"][r] += 1
        if sm.get("missing"):
            out["not_ready"].append({"preset": p.get("name") or pid, "missing": sm["missing"],
                                     "download": (sm.get("download") or {}).get("n", 0),
                                     "unavailable": sm.get("unavailable", 0)})
            out["missing_blocks"] += int(sm["missing"])
            out["download_bytes"] += int((sm.get("download") or {}).get("bytes") or 0)
    with _lock:
        _setlist_cache.update(key=key, at=now, value=out)
    return out


def _f_setlist():
    src = "blocks/status · setlist"
    try:
        s = _setlist_status()
    except Exception as e:
        _swallowed(e)
        s = None
    if not s:
        return _fact("setlist", "Setlist on the foot", "wait", "no setlist", src)
    label = f"“{s['name']}”"
    if not s["presets"]:
        return _fact("setlist", "Setlist on the foot", "wait", f"{label} · empty", src)
    if not s["not_ready"]:
        return _fact("setlist", "Setlist on the foot", "ok",
                     f"{label} · {s['presets']} preset{'s' if s['presets'] != 1 else ''} · every block ready", src)
    nr = s["not_ready"]
    dl = sum(x["download"] for x in nr)
    n = s["missing_blocks"]
    where = f"on “{nr[0]['preset']}”" if len(nr) == 1 else f"across {len(nr)} of {s['presets']} presets"
    rs = s.get("reasons") or {}
    osname = {"win32": "Windows", "darwin": "macOS"}.get(sys.platform, "Linux")
    why = []
    if rs.get("plugin"):
        why.append(f"{rs['plugin']} need a plugin not installed on this {osname} machine")
    if rs.get("format"):
        why.append(f"{rs['format']} are captures this engine cannot play ({osname})")
    if rs.get("capture"):
        why.append(f"{rs['capture']} to download" + (f" ({s['download_bytes'] / 1e6:.0f} MB)" if s["download_bytes"] else ""))
    if rs.get("other"):
        why.append(f"{rs['other']} other")
    what = f"{n} block{'s' if n != 1 else ''} will not play here {where}" + (": " + ", ".join(why) if why else "")
    # le geste : la page Patches — chaque patch s'ouvre dans le Designer, qui télécharge les captures manquantes
    # (POST /api/blocks/fetch) ou pose la jumelle jouable d'une A2 (blocks/playable). Health ne télécharge rien lui-même :
    # un téléchargement repose le preset, donc change ce qui joue (2026-10-20 : « le bouton download, il fait quoi ? »)
    return _fact("setlist", "Setlist on the foot", "warn", f"{label} · {what}", src,
                 fix={"label": "Patches →", "go": "songs/patches"}, detail=nr[:8])


def _f_plugins():
    src = ".fx-inventory.json"
    caps, n = None, None
    with contextlib.suppress(Exception):
        from . import blockstatus as BS
        caps = BS.caps()
        n = (BS.inventory() or {}).get("n")
    if not caps or not caps.get("inventory"):
        return _fact("plugins", "Plugins", "wait", "REAPER has not listed its plugins yet", src)
    q, un = caps.get("quarantine") or [], caps.get("unavailable") or []
    bits = [f"{n} found by REAPER" if n is not None else "listed" + (f" {caps['inventory_at'][:10]}" if caps.get("inventory_at") else "")]
    bits.append(f"{len(un)} block type{'s' if len(un) != 1 else ''} not installable here" if un else "every block type available")
    if q:
        bits.append(f"{len(q)} quarantined ({', '.join(q[:3])}{'…' if len(q) > 3 else ''})")
    return _fact("plugins", "Plugins", "ok", " · ".join(bits), src)


def _f_disk():
    src = "disk"
    d = None
    with contextlib.suppress(Exception):
        from .rigstatus import disk
        d = disk()
    if not d:
        return _fact("disk", "Disk", "wait", "not measured", src)
    free = float(d.get("free_gb") or 0)
    txt = f"{free:.0f} GB free of {d.get('total_gb', 0):.0f} GB"
    if free < DISK_BAD_GB:
        return _fact("disk", "Disk", "bad", txt + " — recordings will fail", src, fix={"label": "Storage →", "go": "system/content/storage"})
    if free < DISK_WARN_GB:
        return _fact("disk", "Disk", "warn", txt + " — getting tight", src, fix={"label": "Storage →", "go": "system/content/storage"})
    return _fact("disk", "Disk", "ok", txt, src)


def _f_golemfm(boot):
    src = "golemfm · uplink"
    fm = ((boot or {}).get("services") or {}).get("fm") or {}
    linked_t = None
    with contextlib.suppress(Exception):
        from . import follow_uplink
        linked_t = (follow_uplink.LINKED or {}).get("t")
    if fm.get("configured") is False:
        return _fact("golemfm", "golem.fm", "wait", "optional — not paired · shared songs, stems and your band", src,
                     fix={"label": "Pair →", "go": "system/connect/golemfm"})
    if fm.get("ok"):
        return _fact("golemfm", "golem.fm", "ok", "linked" + (f" · since {_hhmm(linked_t)}" if linked_t else ""), src)
    if fm.get("configured") and (time.time() - START) > FM_GRACE_S:
        return _fact("golemfm", "golem.fm", "warn", "paired but not reachable — check the network or golem.fm", src,
                     fix={"label": "golem.fm →", "go": "system/connect/golemfm"})
    return _fact("golemfm", "golem.fm", "wait", "connecting…" if fm.get("configured") else "not checked yet", src)


def _f_scripts():
    """presets/.lua-errors.log — écrit par le garde-fou xpcall de __startup.lua. Une erreur DEPUIS LE DÉPART du bridge
    (mtime) est dite avec sa dernière ligne ; un vieux journal n'alarme pas."""
    src = ".lua-errors.log"
    with contextlib.suppress(Exception):
        from .state import state as _st
        if (_st.cards or {}).get("scripts_never_started"):
            # OSC vivant, télémétrie jamais vue (bridge/monitors.py) : une boîte de REAPER bloque __startup.lua
            return _fact("scripts", "Scripts", "bad", "golem's scripts never started in REAPER — a REAPER window "
                         "(Preferences, licence, save) is probably waiting: bring REAPER to the front and close it",
                         "monitors.scripts_never_started")
    p = os.path.join(C.PRESETS_DIR, ".lua-errors.log")
    try:
        stt = os.stat(p)
    except OSError:
        return _fact("scripts", "Scripts", "ok", "no Lua error since start", src)
    if stt.st_size == 0 or stt.st_mtime < START:
        return _fact("scripts", "Scripts", "ok", "no Lua error since start", src)
    last = ""
    with contextlib.suppress(OSError, UnicodeDecodeError):
        with open(p, "rb") as f:
            f.seek(max(0, stt.st_size - 4000))
            lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
            last = lines[-1] if lines else ""
    return _fact("scripts", "Scripts", "warn", f"a Lua error at {_hhmm(stt.st_mtime)} — {last[:120]}", src,
                 fix={"label": "Dashboard →", "go": "system/sys"})


# ── la dérive de l'environnement ───────────────────────────────────────────────────────────────────────────────────
def env_current():
    """Ce qui ne devrait pas changer tout seul. Une sonde absente rend None — et None ne compte jamais comme un
    changement (le moteur pas encore levé n'est pas une carte qui a disparu)."""
    out = {k: None for k in ENV_LABELS}
    with contextlib.suppress(Exception):
        from . import rigstatus
        out["golem"] = rigstatus.golem_version()
        out["reaper"] = rigstatus.reaper_version()
        eng = rigstatus.engine_doc() or {}
        out["card"] = eng.get("device")
        out["samplerate"] = eng.get("samplerate")
        out["bsize"] = eng.get("bsize")
    # macOS : platform.release() est le noyau Darwin (« 24.5.0 » pour macOS 15.5) — la version de macOS est mac_ver()
    release = (platform.mac_ver()[0] or platform.release()) if sys.platform == "darwin" else platform.release()
    out["os"] = f"{ {'win32': 'Windows', 'linux': 'Linux', 'darwin': 'macOS'}.get(sys.platform, sys.platform) } {release}".strip()
    out["kernel"] = platform.version()[:60] or None
    with contextlib.suppress(Exception):
        from . import blockstatus as BS
        out["plugins"] = (BS.inventory() or {}).get("n")
    if sys.platform.startswith("linux"):
        with contextlib.suppress(Exception):
            from .routes_system import _cpu_governor
            out["governor"] = _cpu_governor()
    return out


def _env_read():
    try:
        with open(ENV_PATH(), encoding="utf-8") as f:
            d = json.load(f) or {}
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def env_update(current=None, now=None):
    """Compare l'instantané courant au dernier gardé ; date chaque changement ; n'écrit que s'il y a du neuf.
    Rend {first, changes} — `first` : premier passage (rien à comparer), `changes` : la liste gardée."""
    now = now or time.time()
    cur = current if current is not None else env_current()
    doc = _env_read()
    values = doc.get("values") if isinstance(doc.get("values"), dict) else {}
    changes = [c for c in (doc.get("changes") or []) if isinstance(c, dict)]
    first = not values
    dirty = False
    for k, v in cur.items():
        if v is None:
            continue
        old = (values.get(k) or {}).get("value") if isinstance(values.get(k), dict) else None
        if k not in values:
            values[k] = {"value": v, "at": now}
            dirty = True
        elif old != v:
            changes.append({"key": k, "from": old, "to": v, "at": now})
            values[k] = {"value": v, "at": now}
            dirty = True
            log.info(f"environnement : {ENV_LABELS.get(k, k)} {old!r} → {v!r}")
    changes = changes[-ENV_CHANGES_KEPT:]
    if dirty:
        try:
            from .store import _write_json_atomic
            os.makedirs(os.path.dirname(ENV_PATH()), exist_ok=True)
            _write_json_atomic(ENV_PATH(), {"values": values, "changes": changes, "at": now})
        except Exception as e:
            _swallowed(e)
    return {"first": first, "changes": changes}


def _f_environment():
    src = "environment snapshot"
    try:
        r = env_update()
    except Exception as e:
        _swallowed(e)
        return _fact("environment", "Since last boot", "wait", "not compared", src)
    recent = [c for c in r["changes"] if float(c.get("at") or 0) >= START]
    if r["first"]:
        return _fact("environment", "Since last boot", "wait", "first measurement — nothing to compare yet", src)
    if not recent:
        return _fact("environment", "Since last boot", "ok", "nothing changed: same REAPER, plugins, card, rate, buffer", src)
    # LA VERSION DE GOLEM EST UNE INFORMATION (2026-10-20) : elle change à chaque mise à jour voulue — et sur un poste
    # de dev à chaque commit. Dite en vert ; l'orange reste pour ce qui bouge tout seul (REAPER, carte, fréquence, buffer…)
    hard = [c for c in recent if c.get("key") not in ENV_SOFT]
    said = [f"{ENV_LABELS.get(c['key'], c['key'])} {c.get('from')} → {c.get('to')}" for c in (hard or recent)[-4:]]
    if not hard:
        return _fact("environment", "Since last boot", "ok", "golem updated: " + " · ".join(c for c in said) + " · nothing else changed",
                     src, detail=recent[-10:])
    return _fact("environment", "Since last boot", "warn", "changed: " + " · ".join(said), src, detail=recent[-10:])


# ── la liste, le verdict, le cache ─────────────────────────────────────────────────────────────────────────────────
def _guard():
    """La garde « rack libre » d'un contrôle à la demande — celle du banc de reamp (docs/reamp.md §2)."""
    try:
        from . import reamp, activity
        why = reamp.busy_reason()
        act = activity.last()
        return {"free": why is None, "why": why, "idle_s": act.get("idle_s"), "src": act.get("src")}
    except Exception as e:
        _swallowed(e)
        return {"free": None, "why": "unknown", "idle_s": None, "src": None}


def _verdict(facts):
    levels = [f["level"] for f in facts]
    bad = [f for f in facts if f["level"] == "bad"]
    warn = [f for f in facts if f["level"] == "warn"]
    wait = [f for f in facts if f["level"] == "wait"]
    ok = [f for f in facts if f["level"] == "ok"]
    counts = {"ok": len(ok), "warn": len(warn), "bad": len(bad), "wait": len(wait), "total": len(facts)}
    worst = max(levels, key=lambda lv: _RANK[lv]) if levels else "wait"
    if bad:
        title = "Something is wrong: " + ", ".join(f["name"].lower() for f in bad) + "."
        text = bad[0]["text"]
    elif warn:
        title = "Playing is safe. One thing to look at." if len(warn) == 1 else f"Playing is safe. {len(warn)} things to look at."
        text = " · ".join(f"{f['name']}: {f['text']}" for f in warn[:2])
    elif ok and not any(f["id"] in ("engine", "audio") and f["level"] == "wait" for f in facts):
        worst = "ok"                                      # des « wait » à côté de verts : tout ce qui est mesuré va bien
        title = "Everything checks out."
        text = f"{len(ok)} facts measured, nothing to look at" + (f" · {len(wait)} not measured yet" if wait else "") + "."
    else:
        worst = "wait"
        title = "Still starting."
        text = "facts arrive as the engine comes up."
    return {"level": worst, "title": title, "text": text, "counts": counts}


def compute():
    from .state import state as st
    boot = None
    with contextlib.suppress(Exception):
        from . import boot_progress
        boot = boot_progress.doc()
    probes = (lambda: _f_engine(st), lambda: _f_audio(st), lambda: _f_dropouts(st), lambda: _f_pedalboard(st),
              lambda: _f_playing(st), _f_setlist, _f_plugins, _f_disk, lambda: _f_golemfm(boot), _f_scripts,
              _f_environment)
    facts = []
    for fn in probes:
        try:
            facts.append(fn())
        except Exception as e:                            # une sonde qui casse n'emporte pas la page
            _swallowed(e)
    # HEALTH ▸ FIX (docs/assistant.md §3) : un fait orange ou rouge auquel le registre sait répondre porte son
    # geste « Fix… » (avec la garde du moment) ; les faits surveillés ouvrent et ferment les incidents (§3.1)
    with contextlib.suppress(Exception):
        from . import fixes, incidents
        incidents.observe(facts)
        for f in facts:
            r = fixes.repair_for(f)
            if r:
                f["repair"] = r
                inc = incidents.by_fact(f["id"])
                if inc:
                    f["incident"] = inc["id"]
    now = time.time()
    fc = None
    with contextlib.suppress(Exception):
        from . import first_check
        fc = first_check.brief()
    return {"at": round(now, 3), "since_start_s": round(now - START, 1), "verdict": _verdict(facts), "facts": facts,
            "guard": _guard(), "first_check": fc}


def facts(fresh=False):
    """La liste entière, du cache si elle a moins de REFRESH_S — `fresh` force la relecture."""
    now = time.time()
    with _lock:
        doc = _cache["doc"]
        if doc and not fresh and now - _cache["at"] < REFRESH_S:
            return doc
    doc = compute()
    with _lock:
        _cache.update(at=time.time(), doc=doc)
    return doc


def brief():
    """Le point de santé de la barre du haut : O(1), jamais de sonde ici (appelé à chaque snapshot)."""
    with _lock:
        doc = _cache["doc"]
    if not doc:
        return None
    v = doc["verdict"]
    return {"level": v["level"], "title": v["title"], "bad": v["counts"]["bad"], "warn": v["counts"]["warn"], "at": doc["at"]}


def start(every_s=REFRESH_S):
    """Le fil des faits — démarré par app.py avec les autres moniteurs. Idempotent."""
    if _thread["on"]:
        return
    _thread["on"] = True

    def loop():
        time.sleep(3.0)                                   # le temps que l'état existe
        while True:
            try:
                facts(fresh=True)
            except Exception as e:
                _swallowed(e)
            time.sleep(every_s)

    threading.Thread(target=loop, name="golem-health", daemon=True).start()
