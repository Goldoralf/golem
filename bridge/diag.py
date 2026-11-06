# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que le rack nous dit — le paquet de diagnostic (docs/diagnostics.md, lot 8, FIGÉ 2026-09-13).

Ce module FABRIQUE le paquet ; il n'envoie rien (lot C) et ne pose pas encore d'événements sur
les sites du bridge (lot D). Trois idées, dans l'ordre où elles protègent :

1. **Liste blanche à règle inversée** (`WHITELIST`). Le rapport n'est jamais la copie d'un dict
   existant (`state.snapshot()`, `rigstatus.full()`) : chaque section est PIOCHÉE champ par champ
   par `_pick`, et `violations()` parcourt le résultat pour dire ce qui n'est pas dans la table.
   Un champ ajouté demain à `/api/state` n'est pas dans le rapport, par construction.
2. **Le rack ne connaît pas les personnes** (docs/identity.md) : ni nom de preset, de lane, de
   capture, ni prénom, ni espace. Des TYPES et des HACHAGES (courts : un hexa ≥ 32 est traité
   comme un jeton par le scrubber, donc jamais de sha complet dans le rapport).
3. **Le scrubber** (`scrub`) est la seconde couche, pas la première : il rattrape ce qu'un log a pu
   écrire (`log.info("recall Set Léa")` existe forcément quelque part). Aveugle (regex : home,
   user, host, IP, MAC, jetons) ET informé (le rack sait quels prénoms, quels noms de presets et
   de morceaux il doit effacer — il les lit au moment du scrub).

Le lecteur final est une IA sur golem.fm qui ne connaît pas notre code : la pièce maîtresse est
`timeline.ndjson` (un événement par ligne, VOCABULAIRE FERMÉ `EVENTS`), `report.json` porte un
`_doc` par section, tout est en UTC ISO-8601 plus `up` (secondes depuis le boot du bridge).

Résiste à l'extinction : la session est sur disque (`diag/session.json`, chronologie en append),
un rack débranché raconte sa session au boot suivant (`open_session()` rend la précédente si elle
n'a pas été clôturée). Case décochée (`config/diag.json` `auto:false`) : la chronologie locale
s'écrit toujours (elle sert à se dépanner), aucun zip n'est fabriqué, rien ne sort.
"""
import contextlib
import hashlib
import io
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from . import config as C
from . import scrub as _scrub
from .golog import get
from .golog import swallowed as _swallowed

log = get("diag")

SCHEMA = "golem-report/2"
MANIFEST_VERSION = 2
KINDS = ("boot", "session", "event")
KEEP_REPORTS = 20                 # paquets gardés localement (jamais un non-envoyé)
MAX_ZIP_BYTES = 4 * 1024 * 1024   # plafond du paquet
LOG_BUDGET_BYTES = 3 * 1024 * 1024  # part des logs dans ce plafond (tronqués par la fin)
LOG_WINDOW_S = 30 * 60            # fenêtre des logs d'un `event` / `boot`
LOG_WINDOW_SET_S = 2 * 3600       # borne d'une `session`
HASH_LEN = 12                     # hachages COURTS (un hexa ≥ 32 = jeton pour le scrubber)

_UP0 = time.monotonic()
_lock = threading.Lock()


# ── chemins (dynamiques : les tests déplacent C.ROOT) ────────────────────────────────────────
def _dir():
    d = os.path.join(C.ROOT, "diag")
    os.makedirs(d, exist_ok=True)
    return d


def _settings_path():
    return os.path.join(C.CONFIG_DIR, "diag.json")


def _session_path():
    return os.path.join(_dir(), "session.json")


def _timeline_path():
    return os.path.join(_dir(), "timeline.ndjson")


def _index_path():
    return os.path.join(_dir(), "index.json")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _up():
    return round(time.monotonic() - _UP0, 1)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ── la case ──────────────────────────────────────────────────────────────────────────────────
def auto():
    """Case « Allow this GoleM to send usage and bug reports » — absente = cochée."""
    d = _read_json(_settings_path(), {}) or {}
    return bool(d.get("auto", True))


def set_auto(on):
    d = _read_json(_settings_path(), {}) or {}
    d["auto"] = bool(on)
    os.makedirs(C.CONFIG_DIR, exist_ok=True)
    _write_json_atomic(_settings_path(), d)
    return d["auto"]


# ── LA LISTE BLANCHE ─────────────────────────────────────────────────────────────────────────
# Une clé par section, la liste EXACTE des champs autorisés. `[]` en suffixe = liste de dicts.
# docs/diagnostics.md §2.3 est la traduction en prose de cette table ; les deux doivent se lire pareil.
WHITELIST = {
    "report": ("schema", "kind", "session_id", "report_id", "created_at", "up", "truncated"),
    "platform": ("os", "kernel", "rt", "arch", "cpu_model", "cpu_count", "ram_total_mb"),
    "golem": ("version", "branch", "dirty", "profile", "installed_at", "installer", "catalog_version"),
    "reaper": ("installed", "pinned", "running", "uptime_s", "rss_mb", "restarts"),
    "audio": ("card", "bsize", "rate", "latency_ms", "governor", "boost", "alive", "xruns_total", "xruns_window"),
    "audio.card": ("usb", "inputs", "outputs", "midi"),
    "audio.card.midi": ("in", "out"),
    "midi": ("devices", "ok", "issues"),
    "midi.devices[]": ("usb", "kernel"),
    "pedalboard": ("id", "source", "stale"),
    "mode": ("id", "kind", "locked", "services"),
    "preset": ("hash", "scene", "blocks", "lanes"),
    "preset.blocks[]": ("type", "category", "quarantine", "bypass", "wrong_kind"),
    "preset.lanes": ("count", "roles"),
    "libraries": ("components", "missing"),
    "libraries.components[]": ("id", "installed", "version"),
    "catalog": ("quarantined", "captures"),
    "catalog.captures": ("nam", "ir"),
    "rig_check": ("ok", "checked", "issues"),
    "rig_check.issues[]": ("kind", "expected", "repaired"),
    "health": ("cpu_pct", "temp_c", "ram_used_pct", "disk"),
    "first_check": ("done_at", "skipped", "took_s", "verdict", "steps"),
    "first_check.steps": ("input", "output", "foot"),
    "first_check.steps.input": ("ok", "took_s", "peak_db", "input", "role", "gain"),
    "first_check.steps.output": ("ok", "took_s", "click_ticks", "heard"),
    "first_check.steps.foot": ("ok", "took_s", "answered"),
    "health.disk": ("free_gb", "used_pct"),
    "usage": ("started_at", "ended_at", "ended", "duration_s", "modes", "recalls", "scene_switches",
              "presets_distinct", "block_types_used", "takes", "standards_played", "looper_used",
              "keys_used", "pedalboard_used", "foot_messages", "jobs", "events"),
    "usage.modes[]": ("kind", "duration_s"),
    "usage.recalls": ("count", "ms_median", "ms_max", "failed"),
    "usage.takes": ("count", "duration_s", "kinds"),
    "usage.jobs": ("done", "error"),
    "anomalies[]": ("chip", "first_at", "total_s", "count"),
    "previous_session": ("session_id", "started_at", "ended_at", "ended", "usage", "anomalies"),
    "event": ("type", "at", "chips", "detail"),
    "incidents": ("opened", "resolved", "hints", "open"),
    "incidents.open[]": ("kind", "code", "age_s"),
}
# Sections dont les sous-clés sont LIBRES (dicts de comptes : {kind: n}, {service: bool}) — le
# contenu reste des nombres/booléens, la clé est un type ou un identifiant de service, jamais un nom.
FREE_MAPS = {"mode.services", "usage.takes.kinds", "usage.events", "previous_session.usage.takes.kinds",
             "previous_session.usage.events", "incidents.resolved", "incidents.hints"}

_DOC = {
    "platform": "the machine: OS, kernel (rt = PREEMPT_RT), CPU, RAM",
    "golem": "golem version (git describe) and install profile",
    "reaper": "the audio engine: versions, process, restarts during this session",
    "audio": "sound card by USB VID:PID (never by name), buffer, latency, CPU governor; alive = the audio "
             "thread counter still advances; xruns_window = dropouts in the last 90 s",
    "midi": "MIDI devices by USB id, and the MIDI sentinel verdict",
    "pedalboard": "the active foot controller descriptor (id), and whether its probe is stale",
    "mode": "current usage mode; kind = show | gig | rehearsal",
    "preset": "the loaded rig: short file hash, active scene, block TYPES (never names)",
    "libraries": "components from the public manifest: installed or missing",
    "catalog": "block types quarantined (known to crash Reaper) and how many captures are installed",
    "rig_check": "what each plugin REALLY loaded (NAM model / IR), read from the plugin after recall",
    "health": "CPU, temperature, RAM, disk at report time",
    "first_check": "the first-start check (docs/health.md §2): verdicts and durations of the three gestures — signal "
                   "seen on an input, the click heard, the pedalboard answering — never a name",
    "usage": "what happened during this session, computed from timeline.ndjson",
    "anomalies": "warning chips that lit up during the session, with durations",
    "previous_session": "present in a boot report when the previous session did not close cleanly",
    "event": "the incident that triggered this report",
    "incidents": "failures of this session and how each one ended (docs/assistant.md §3.1): opened = how many; "
                 "resolved = by action (a golem fix, verified) · restart · outside (came back with nothing from "
                 "golem: a cable, a knob — hints = what the musician said) ; open = still failing at the end",
}


def _pick(path, d):
    """Ne garde de `d` que les champs listés pour `path` — c'est la seule façon d'entrer dans le rapport."""
    if not isinstance(d, dict):
        return d
    allowed = WHITELIST.get(path)
    if allowed is None:
        return d
    out = {}
    for k in allowed:
        if k in d and d[k] is not None:
            v = d[k]
            sub = f"{path}.{k}"
            if isinstance(v, dict) and sub in WHITELIST:
                v = _pick(sub, v)
            elif isinstance(v, list) and f"{sub}[]" in WHITELIST:
                v = [_pick(f"{sub}[]", x) for x in v if isinstance(x, dict)]
            out[k] = v
    return out


def violations(report):
    """Chemins du rapport qui ne sont PAS dans la liste blanche — vide si tout va bien.
    C'est le test de recette (tests/test_diag_whitelist.py) ; en production on l'appelle aussi,
    et une violation fait ÉCHOUER la fabrication : mieux vaut pas de rapport qu'une fuite."""
    bad = []

    def spec(path):
        # `previous_session.usage` se lit comme `usage` : même table, même règle
        if path.startswith("previous_session."):
            return WHITELIST.get(path[len("previous_session."):])
        return WHITELIST.get(path)

    def walk(path, v):
        if isinstance(v, dict):
            if path in FREE_MAPS:
                return
            allowed = spec(path)
            for k, x in v.items():
                if k.startswith("_"):
                    continue                        # _doc
                if allowed is None or k not in allowed:
                    if path == "" and k in WHITELIST:  # section de premier niveau
                        walk(k, x)
                        continue
                    bad.append(f"{path}.{k}" if path else k)
                    continue
                walk(f"{path}.{k}", x)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, (dict, list)):
                    walk(f"{path}[]", x)

    for section, v in report.items():
        if section.startswith("_"):
            continue
        if section not in WHITELIST and f"{section}[]" not in WHITELIST:
            bad.append(section)
            continue
        walk(section, v)
    return bad


# ── le scrubber ──────────────────────────────────────────────────────────────────────────────
# Le moteur vit dans bridge/scrub.py (bibliothèque standard, partagé avec l'installateur, docs/diagnostics.md §7.1) ;
# ici, ce que le RACK sait devoir effacer : personnes, presets, chansons.


class Scrubber(_scrub.Scrubber):
    """Construit UNE fois les listes de ce que le rack sait devoir effacer, puis scrubbe des chaînes.
    Une liste qui échoue à se lire ne fait pas tomber le scrub : elle est vide (et le test PII
    vérifie les autres couches)."""

    def __init__(self, names=None, presets=None, songs=None):
        self.root = C.ROOT
        self.names = _scrub.norm(names if names is not None else self._roster_names())
        self.presets = _scrub.norm(presets if presets is not None else self._preset_names())
        self.songs = _scrub.norm(songs if songs is not None else self._song_names())
        super().__init__(known=((self.presets, "<preset>"), (self.songs, "<song>"), (self.names, "<name>")),
                         roots=(C.ROOT,))

    @staticmethod
    def _roster_names():
        out = []
        try:
            from . import roster
            d = roster.read() or {}
            for p in d.get("people") or []:
                if isinstance(p, dict):
                    out += [p.get("name"), p.get("id")]
            for b in [d.get("band")] + list(d.get("bands") or []):
                if isinstance(b, dict):
                    out.append(b.get("name"))       # le NOM du groupe ; pas son slug (« test », « dev »
                                                    # — des mots de log, pas des personnes)
        except Exception as e:
            _swallowed(e, "roster")
        try:
            from . import inputmap
            for e in (inputmap.current() or {}).get("inputs") or []:
                if isinstance(e, dict):
                    out += [e.get("person"), e.get("person_name")]
        except Exception as e:
            _swallowed(e, "inputmap")
        return [x for x in out if x]

    @staticmethod
    def _preset_names():
        out = []
        try:
            from . import store
            for p in store.load_presets():
                out += [p.get("name"), p.get("artist")]
                for L in p.get("lanes") or []:
                    if isinstance(L, dict):
                        out.append(L.get("name"))
        except Exception as e:
            _swallowed(e, "presets")
        try:
            from . import patches
            for p in patches.list_patches():
                out.append(p.get("name") if isinstance(p, dict) else None)
        except Exception as e:
            _swallowed(e, "patches")
        return [x for x in out if x]

    @staticmethod
    def _song_names():
        out = []
        # la bibliothèque : titres et SLUGS golem.fm (le slug mène à la ligne de la chanson, donc à son compte)
        try:
            from . import songs, golem_pull
            for d in songs.list_all() or []:
                if isinstance(d, dict):
                    out += [d.get("title"), d.get("song_slug")]
            out += list(golem_pull.etags().keys()) + list(songs._cards().keys())
        except Exception as e:
            _swallowed(e, "songs")
        try:
            from . import setlists
            for s in setlists.list_all() or []:
                if isinstance(s, dict):
                    out.append(s.get("name"))
                    for ln in s.get("lines") or s.get("items") or []:
                        if isinstance(ln, dict):
                            out += [ln.get("title"), ln.get("name")]
        except Exception as e:
            _swallowed(e, "setlists")
        return [x for x in out if x]


_scrubber = None
_scrubber_at = 0.0


def scrubber(fresh=False):
    """Le scrubber courant, reconstruit au plus toutes les 60 s (les listes de noms bougent)."""
    global _scrubber, _scrubber_at
    if fresh or _scrubber is None or time.time() - _scrubber_at > 60:
        _scrubber = Scrubber()
        _scrubber_at = time.time()
    return _scrubber


def scrub(s):
    return scrubber()(s)


def short_hash(data):
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    return hashlib.sha1(data).hexdigest()[:HASH_LEN]


# ── la chronologie ───────────────────────────────────────────────────────────────────────────
# Vocabulaire FERMÉ (docs/diagnostics.md §2.4) : type -> champs autorisés. Un champ inconnu est
# retiré (et tracé en debug) ; un type inconnu est refusé. Le lot D pose diag.event() sur les sites.
EVENTS = {
    "boot": ("reason",),
    "shutdown": ("reason",),
    "reaper": ("state", "pid_uptime_s", "why"),     # why = requested | settings | update ; absent = pas demandé
    "mode": ("from", "to", "locked"),
    "recall": ("preset_hash", "scene", "ms", "ok", "rebuild", "blocks"),
    "scene": ("to", "ms"),
    "stomp": ("block_type", "on"),
    "foot": ("msg", "n"),
    "xrun": ("delta", "window_s"),
    "chip": ("chip", "on"),
    "audio": ("state", "why"),
    "midi": ("state",),
    "rig_check": ("ok", "issues", "kinds"),
    "take": ("state", "kind", "duration_s", "tracks"),
    "job": ("action", "ok", "ms"),
    "error": ("logger", "msg", "sig", "sig_src"),
    # une erreur de l'app (docs/diagnostics.md §7.2) : jamais un déclencheur — elle part avec la session
    "ui_error": ("page", "msg", "where", "sig", "sig_src", "client"),
    "requested": (),
    # HEALTH ▸ FIX (docs/assistant.md §3.1) : une panne, la réparation tentée, comment elle a fini — types et codes,
    # jamais un titre (le titre lisible reste sur la machine, config/.incidents.json)
    "incident": ("id", "state", "kind", "code", "stage"),
    "fix": ("id", "action", "params", "by", "verify", "ms"),
    "resolution": ("id", "resolved_by", "after_s", "hint"),
    # « Ask golem » (docs/assistant.md §5) : qu'une question a été posée et comment elle a fini — jamais son texte
    "assist": ("ok", "error", "cites", "proposed", "dropped", "ms"),
    # `sample` ne va JAMAIS dans timeline.ndjson : c'est la ligne de samples.ndjson (anneau §3.1)
    "sample": ("res", "xruns", "latency_ms", "cpu_pct", "temp_c", "audio_ok", "midi_ok", "mode", "scene", "preset_hash"),
}
SIGNED = ("error", "ui_error")      # les natures qui portent une signature (docs/diagnostics.md §7.3)
# natures d'événements qui méritent un paquet `event` immédiat (lot C les branche sur send)
EVENT_TRIGGERS = {"reaper": lambda f: f.get("state") in ("down", "restart") and not f.get("why"),
                  "audio": lambda f: f.get("state") == "lost",
                  "rig_check": lambda f: f.get("ok") is False,
                  "xrun": lambda f: (f.get("delta") or 0) >= 10,
                  "error": lambda f: True}


def event(type_, **fields):
    """Le seul point d'entrée de la chronologie : valide, scrubbe, horodate, écrit (append, une
    ligne par événement — rien à perdre à la coupure). Rend la ligne écrite, ou None si refusée."""
    if type_ not in EVENTS or type_ == "sample":
        log.warning(f"événement hors vocabulaire refusé : {type_!r}")
        return None
    allowed = EVENTS[type_]
    row = {"t": _now(), "up": _up(), "type": type_}
    sc = scrubber()
    for k, v in fields.items():
        if k not in allowed:
            log.debug(f"champ hors vocabulaire retiré : {type_}.{k}")
            continue
        if isinstance(v, str):
            v = sc(v)[:200]
        elif isinstance(v, list):
            v = [sc(x)[:80] if isinstance(x, str) else x for x in v][:20]
        row[k] = v
    if type_ in SIGNED:
        # la signature (§7.3) : calculée ICI sur la forme SCRUBBÉE puis normalisée — celle qui part, que golem.fm
        # recalcule ; jamais une valeur fournie par l'appelant
        src = _scrub.normalize(row.get("sig_src") or row.get("msg") or "")
        row["sig_src"], row["sig"] = src, _scrub.sig(src)
    line = json.dumps(row, ensure_ascii=False)
    try:
        with _lock:
            with open(_timeline_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as e:
        _swallowed(e, "timeline")
    return row


def _read_timeline(path=None, since_s=None):
    """Les lignes de la chronologie (dicts), optionnellement bornées aux `since_s` dernières secondes."""
    rows = []
    try:
        with open(path or _timeline_path(), encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        return rows
    if since_s is not None and rows:
        cut = _up() - since_s
        rows = [r for r in rows if (r.get("up") or 0) >= cut]
    return rows


# ── la session ───────────────────────────────────────────────────────────────────────────────
def open_session(reason="boot"):
    """Ouvre la session du boot. Si la précédente n'a pas été clôturée (rack débranché, bridge tué),
    elle est clôturée `unclean` ici, sa chronologie archivée dans `diag/prev-timeline.ndjson`, et
    son bilan est RENDU pour partir dans le `boot` (previous_session) — c'est le concert qui finit
    par « il a tout éteint », raconté le lendemain."""
    prev = _read_json(_session_path())
    previous = None
    if isinstance(prev, dict) and prev.get("session_id") and not prev.get("ended_at"):
        rows = _read_timeline()
        prev["ended_at"] = _last_t(rows) or prev.get("started_at")
        prev["ended"] = "unclean"
        previous = {"session_id": prev["session_id"], "started_at": prev.get("started_at"),
                    "ended_at": prev["ended_at"], "ended": "unclean",
                    **summarize(rows, prev.get("started_at"), prev["ended_at"], prev.get("mode_kind"))}
        try:
            os.replace(_timeline_path(), os.path.join(_dir(), "prev-timeline.ndjson"))
        except OSError:
            pass
        _write_json_atomic(os.path.join(_dir(), "prev-session.json"), prev)
    elif isinstance(prev, dict) and prev.get("ended_at"):
        try:
            os.replace(_timeline_path(), os.path.join(_dir(), "prev-timeline.ndjson"))
        except OSError:
            pass
    reset_samples()
    mode_kind = None
    try:
        from . import modes
        mode_kind = modes.take_kind()
    except Exception as e:
        _swallowed(e, "mode")
    sess = {"session_id": str(uuid.uuid4()), "started_at": _now(), "mode_kind": mode_kind,
            "ended_at": None, "ended": None}
    _write_json_atomic(_session_path(), sess)
    event("boot", reason=reason)
    return sess, previous


def close_session(reason="sigterm"):
    """Clôt proprement : événement `shutdown`, `ended: clean`. Rend la session (ou None)."""
    sess = _read_json(_session_path())
    if not isinstance(sess, dict) or not sess.get("session_id"):
        return None
    event("shutdown", reason=reason)
    sess["ended_at"] = _now()
    sess["ended"] = "clean"
    _write_json_atomic(_session_path(), sess)
    return sess


def session():
    return _read_json(_session_path())


def _last_t(rows):
    for r in reversed(rows):
        if r.get("t"):
            return r["t"]
    return None


def _parse_t(s):
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except Exception:
        return None


def summarize(rows, started_at=None, ended_at=None, mode_kind=None):
    """`usage` + `anomalies` calculés de la chronologie — ce que le rack sait pré-calculer pour que
    l'IA n'ait pas à reconstituer qu'un `NO AUDIO` a duré 13 h à partir de 4 000 échantillons."""
    t0 = _parse_t(started_at) if started_at else None
    t1 = _parse_t(ended_at) if ended_at else None
    dur = int(t1 - t0) if (t0 is not None and t1 is not None and t1 >= t0) else None
    ups = [r.get("up") for r in rows if isinstance(r.get("up"), (int, float))]
    up_end = max(ups) if ups else 0
    # modes : durée par kind, depuis les événements `mode` (le kind initial vient de la session)
    modes = {}
    cur, cur_up = mode_kind, (min(ups) if ups else 0)
    for r in rows:
        if r.get("type") == "mode":
            if cur:
                modes[cur] = modes.get(cur, 0) + max(0, (r.get("up") or 0) - cur_up)
            cur, cur_up = r.get("to"), r.get("up") or 0
    if cur:
        modes[cur] = modes.get(cur, 0) + max(0, up_end - cur_up)
    recalls = [r for r in rows if r.get("type") == "recall"]
    ms = [r["ms"] for r in recalls if isinstance(r.get("ms"), (int, float))]
    takes = [r for r in rows if r.get("type") == "take" and r.get("state") == "stop"]
    kinds = {}
    for r in takes:
        kinds[r.get("kind") or "?"] = kinds.get(r.get("kind") or "?", 0) + 1
    jobs = [r for r in rows if r.get("type") == "job"]
    counts = {}
    for r in rows:
        counts[r.get("type") or "?"] = counts.get(r.get("type") or "?", 0) + 1
    block_types = sorted({b for r in recalls for b in (r.get("blocks") or []) if isinstance(b, str)})
    stomps = [r for r in rows if r.get("type") == "stomp"]
    usage = {
        "started_at": started_at, "ended_at": ended_at, "duration_s": dur,
        "block_types_used": block_types or None,
        "looper_used": any((r.get("block_type") or "").startswith("looper") for r in stomps) or None,
        "pedalboard_used": any(r.get("type") == "foot" for r in rows) or None,
        "modes": [{"kind": k, "duration_s": int(v)} for k, v in modes.items()],
        "recalls": {"count": len(recalls),
                    "ms_median": round(statistics.median(ms)) if ms else None,
                    "ms_max": max(ms) if ms else None,
                    "failed": sum(1 for r in recalls if r.get("ok") is False)},
        "scene_switches": sum(1 for r in rows if r.get("type") == "scene"),
        "presets_distinct": len({r.get("preset_hash") for r in recalls if r.get("preset_hash")}),
        "takes": {"count": len(takes), "duration_s": int(sum(r.get("duration_s") or 0 for r in takes)),
                  "kinds": kinds},
        "foot_messages": sum(1 for r in rows if r.get("type") == "foot"),
        "jobs": {"done": sum(1 for r in jobs if r.get("ok")), "error": sum(1 for r in jobs if r.get("ok") is False)},
        "events": counts,
    }
    # anomalies : chaque puce, de son allumage à son extinction (ou la fin)
    anomalies, open_ = {}, {}
    for r in rows:
        if r.get("type") != "chip":
            continue
        c = r.get("chip")
        if r.get("on"):
            open_.setdefault(c, r.get("up") or 0)
            a = anomalies.setdefault(c, {"chip": c, "first_at": r.get("t"), "total_s": 0, "count": 0})
            a["count"] += 1
        elif c in open_:
            anomalies[c]["total_s"] += max(0, (r.get("up") or 0) - open_.pop(c))
    for c, since in open_.items():
        anomalies[c]["total_s"] += max(0, up_end - since)
    for a in anomalies.values():
        a["total_s"] = int(a["total_s"])
    return {"usage": usage, "anomalies": list(anomalies.values())}


# ── les sondes ───────────────────────────────────────────────────────────────────────────────
def _read_text(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read().strip()
    except OSError:
        return None


def platform_info():
    """La sonde qui MANQUAIT (docs/diagnostics.md §0.1) : OS, noyau, RT, CPU, RAM."""
    out = {"arch": platform.machine() or None, "cpu_count": os.cpu_count()}
    osr = _read_text("/etc/os-release") or ""
    kv = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', osr, re.M))
    if kv.get("ID"):
        out["os"] = f"{kv.get('ID')} {kv.get('VERSION_ID') or ''}".strip()
    out["kernel"] = platform.release() or None
    rt = _read_text("/sys/kernel/realtime")
    out["rt"] = (rt == "1") or ("PREEMPT_RT" in (platform.version() or ""))
    cpuinfo = _read_text("/proc/cpuinfo") or ""
    m = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)
    if m:
        out["cpu_model"] = m.group(1).strip()
    try:
        from . import rigstatus
        r = rigstatus.ram()
        if r:
            out["ram_total_mb"] = r.get("total_mb")
    except Exception as e:
        _swallowed(e, "ram")
    return out


def _usbid(card_idx):
    if card_idx is None:
        return None
    return _read_text(f"/proc/asound/card{card_idx}/usbid")


def _section_golem():
    from . import rigstatus
    d = dict(rigstatus.rack_identity())
    try:
        from .routes_system import _git
        d["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD") or None
        d["dirty"] = bool(_git("status", "--porcelain"))
    except Exception as e:
        _swallowed(e, "git")
    return d


def _section_reaper(rows):
    from . import reaper_update
    st = reaper_update.status()
    d = {"installed": st.get("installed"), "pinned": st.get("pinned")}
    try:
        from .routes_system import system_health
        h = system_health().get("reaper") or {}
        d.update({"running": h.get("running"), "uptime_s": h.get("uptime_s"), "rss_mb": h.get("rss_mb")})
    except Exception as e:
        _swallowed(e, "health")
    d["restarts"] = sum(1 for r in rows if r.get("type") == "reaper" and r.get("state") == "restart")
    return d


def _section_audio(st, rows):
    from . import cards
    from .routes_system import _read_bsize, _cpu_governor
    card = None
    try:
        # l'état porte `hw:V276` (nom ALSA de périphérique), cards.probe veut l'id de carte `V276`
        cid = str((st.inputmap or {}).get("card") or "").removeprefix("hw:") or C.alsa_card()
        p = cards.probe(cid) if cid else None
        if p:
            card = {"usb": p.get("usb") or None, "inputs": p.get("inputs"), "outputs": p.get("outputs"),
                    "midi": p.get("midi")}
    except Exception as e:
        _swallowed(e, "card")
    window = None
    xr = [r for r in _read_timeline(since_s=90) if r.get("type") == "xrun"]
    if xr:
        window = sum(r.get("delta") or 0 for r in xr)
    return {"card": card, "bsize": _read_bsize(), "latency_ms": st.latency_ms, "governor": _cpu_governor(),
            "boost": bool(getattr(st, "cpu_boost", False)), "alive": (st.audio or {}).get("ok"),
            "xruns_total": st.xruns, "xruns_window": window}


def _section_midi(st):
    devs = []
    try:
        from .routes_system import _seq_clients
        for c in _seq_clients():
            if c.get("card") is None:
                continue                                    # clients logiciels : pas un appareil
            devs.append({"usb": _usbid(c.get("card")), "kernel": bool(c.get("kernel"))})
    except Exception as e:
        _swallowed(e, "seq")
    m = st.midi or {}
    return {"devices": devs, "ok": m.get("ok"), "issues": [scrub(str(x))[:120] for x in (m.get("issues") or [])]}


def _section_mode():
    from . import modes
    m = modes.current() or {}
    return {"id": m.get("id"), "kind": modes.take_kind(m), "locked": bool((m.get("ui") or {}).get("locked")),
            "services": {k: bool(v) for k, v in (m.get("services") or {}).items()}}


def _categories():
    try:
        data = json.load(open(C.EFFECTS))
        return {e.get("type"): e.get("category") for e in data.get("effects", []) if e.get("type")}
    except Exception:
        return {}


def _section_preset(st):
    from . import store, rig
    pid = st.preset_id
    p = store.load_preset(pid) if pid else None
    if not p:
        return None
    h = None
    try:
        path = os.path.join(C.PRESETS_DIR, f"{store._safe_id(pid)}.json")
        h = short_hash(open(path, "rb").read()) if os.path.exists(path) else short_hash(json.dumps(p, sort_keys=True))
    except Exception as e:
        _swallowed(e, "hash")
    cats, q = _categories(), rig.quarantined_types()
    blocks, roles, n = [], [], 0
    for b, lane in store.all_blocks(p):
        if not isinstance(b, dict) or not b.get("type"):
            continue
        t = b["type"]
        row = {"type": t, "category": cats.get(t)}
        if t in q:
            row["quarantine"] = True
        if b.get("bypass"):
            row["bypass"] = True
        blocks.append(row)
    try:
        lanes = store.lanes_of(p)
        n = len(lanes)
        roles = [L.get("role") or L.get("kind") or "?" for L in lanes if isinstance(L, dict)]
    except Exception as e:
        _swallowed(e, "lanes")
    return {"hash": h, "scene": st.scene_id, "blocks": blocks, "lanes": {"count": n, "roles": roles}}


def _section_libraries():
    from . import libraries
    rep = libraries.report()
    comps = [{"id": c.get("id"), "installed": c.get("installed"), "version": c.get("version")}
             for c in rep.get("components") or []]
    return {"components": comps, "missing": [c["id"] for c in comps if c["installed"] is False]}


def _section_catalog():
    from . import rig, rigstatus
    caps = rigstatus.captures()
    return {"quarantined": sorted(rig.quarantined_types().keys()),
            "captures": {"nam": sum(1 for c in caps if c.get("type") == "nam"),
                         "ir": sum(1 for c in caps if c.get("type") == "ir")}}


def _section_rig_check():
    from .monitors import _read_rig_check
    rc = _read_rig_check()
    if not rc:
        return None
    issues = [{"kind": i.get("kind"), "expected": scrub(os.path.basename(str(i.get("expected") or "")))[:80],
               "repaired": bool(i.get("repaired"))} for i in rc.get("issues") or [] if isinstance(i, dict)]
    return {"ok": rc.get("ok"), "checked": rc.get("checked"), "issues": issues}


def _section_health():
    from . import rigstatus
    d = rigstatus.disk() or {}
    r = rigstatus.ram() or {}
    return {"cpu_pct": rigstatus.cpu_pct(), "temp_c": rigstatus.temp_c(), "ram_used_pct": r.get("used_pct"),
            "disk": {"free_gb": d.get("free_gb"), "used_pct": d.get("used_pct")}}


def _section_first_check():
    from . import first_check
    return first_check.section()


def build_report(kind, event_=None, previous=None):
    """`report.json` : chaque section PIOCHÉE (`_pick`) puis vérifiée (`violations`). Une sonde qui
    échoue rend une section absente, jamais une exception : un rapport partiel dit `_missing`."""
    if kind not in KINDS:
        raise ValueError(f"kind inconnu : {kind}")
    from .state import state as st
    sess = session() or {}
    rows = _read_timeline()
    rep = {"report": {"schema": SCHEMA, "kind": kind, "session_id": sess.get("session_id"),
                      "report_id": str(uuid.uuid4()), "created_at": _now(), "up": _up(), "truncated": False}}
    missing = []
    probes = [("platform", platform_info), ("golem", _section_golem), ("reaper", lambda: _section_reaper(rows)),
              ("audio", lambda: _section_audio(st, rows)), ("midi", lambda: _section_midi(st)),
              ("pedalboard", lambda: _pick_pedalboard()), ("mode", _section_mode),
              ("preset", lambda: _section_preset(st)), ("libraries", _section_libraries),
              ("catalog", _section_catalog), ("rig_check", _section_rig_check), ("health", _section_health),
              ("first_check", _section_first_check)]
    for name, fn in probes:
        try:
            v = fn()
        except Exception as e:
            _swallowed(e, name)
            v = None
        if v is None:
            missing.append(name)
            continue
        rep[name] = _pick(name, v)
        if name in _DOC:
            rep[name]["_doc"] = _DOC[name]
    if kind == "session":
        s = summarize(rows, sess.get("started_at"), sess.get("ended_at") or _now(), sess.get("mode_kind"))
        u = _pick("usage", s["usage"])
        u["ended"] = sess.get("ended") or "unknown"
        rep["usage"] = {**u, "_doc": _DOC["usage"]}
        rep["anomalies"] = [_pick("anomalies[]", a) for a in s["anomalies"]]
        try:
            from . import incidents as _inc
            inc = _inc.summary(rows)
        except Exception as e:
            _swallowed(e, "incidents")
            inc = None
        if inc:
            rep["incidents"] = {**_pick("incidents", inc), "_doc": _DOC["incidents"]}
    if kind == "boot" and previous:
        pv = _pick("previous_session", previous)
        if "usage" in pv:
            pv["usage"] = _pick("usage", pv["usage"])
        if "anomalies" in pv:
            pv["anomalies"] = [_pick("anomalies[]", a) for a in pv["anomalies"]]
        rep["previous_session"] = {**pv, "_doc": _DOC["previous_session"]}
    if kind == "event":
        ev = dict(event_ or {})
        ev.setdefault("at", _now())
        ev["chips"] = _chips(st)
        if "detail" in ev:
            ev["detail"] = scrub(str(ev["detail"]))[:500]
        rep["event"] = {**_pick("event", ev), "_doc": _DOC["event"]}
    rep = scrubber().deep(rep)
    if missing:
        rep["_missing"] = missing
    bad = violations(rep)
    if bad:
        raise RuntimeError(f"liste blanche violée : {bad}")
    return rep


def _pick_pedalboard():
    from .monitors import _pedalboard_brief
    return _pedalboard_brief()


def _chips(st):
    """Les puces /live allumées à l'instant (miroir de app/page-live.js, barre d'info)."""
    chips = []
    if (st.audio or {}).get("ok") is False:
        chips.append("NO AUDIO")
    m = st.midi or {}
    if m.get("ok") is False:
        chips.append("NO MIDI")
    if (st.rig_check or {}).get("ok") is False:
        chips.append("FX FILE")
    if getattr(st, "rig_error", None):
        chips.append("RIG")
    if getattr(st, "rig_unmounted", None):
        chips.append("LANES OFF")
    if (st.pedalboard or {}).get("stale"):
        chips.append("PEDAL?")
    if st.xruns:
        chips.append("XRUNS")
    return chips


# ── les logs ─────────────────────────────────────────────────────────────────────────────────
_KERNEL_RX = re.compile(r"xrun|snd_|usb |audio|ALSA", re.IGNORECASE)


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return -1, ""


def collect_logs(window_s, sc=None):
    """{nom: texte scrubbé} + la liste des sources ABSENTES. On ne devine pas : un journal qui
    n'existe pas est dit tel quel (`missing[]`)."""
    sc = sc or scrubber()
    if sys.platform in ("win32", "darwin"):
        return _collect_desktop_logs(window_s, sc)
    since = f"-{int(window_s)}s"
    out, missing = {}, []
    rc, txt = _run(["journalctl", "--user", "-u", "golem-bridge", "-u", "golem-reaper", "-u", "golem-midi",
                    "-u", "golem-kiosk", "-u", "golem-server", "--since", since, "-o", "short-iso", "--no-pager"])
    if rc == 0 and txt.strip() and "No entries" not in txt:
        out["bridge.log"] = txt
    else:
        missing.append("journald:user")
    rc, txt = _run(["journalctl", "-k", "--since", since, "-o", "short-iso", "--no-pager"])
    if rc == 0:
        lines = [ln for ln in txt.splitlines() if _KERNEL_RX.search(ln)]
        out["kernel.log"] = "\n".join(lines)
    else:
        missing.append("journald:kernel")
    rl = os.environ.get("GOLEM_REAPER_LOG", "/tmp/golem-reaper.log")
    if os.path.exists(rl):
        out["reaper.log"] = _tail(rl, LOG_BUDGET_BYTES // 3)
    else:
        missing.append("reaper.log")
    ap = "/var/log/apport.log"
    if os.path.exists(ap):
        try:
            with open(ap, encoding="utf-8", errors="replace") as f:
                out["apport.log"] = "\n".join(ln.rstrip() for ln in f if "reaper" in ln.lower())
        except OSError:
            missing.append("apport.log")
    else:
        missing.append("apport.log")
    try:
        from .monitors import _read_rig_check, RIG_CHECK_HIST
        rc_ = _read_rig_check()
        hist = _read_json(RIG_CHECK_HIST, [])
        if rc_ or hist:
            out["rig-check.json"] = json.dumps({"last": rc_, "history": hist}, ensure_ascii=False, indent=1)
    except Exception as e:
        _swallowed(e, "rig-check")
    return {k: "\n".join(sc(ln) for ln in v.splitlines()) for k, v in out.items()}, missing


def _collect_desktop_logs(window_s, sc):
    """Windows / macOS : ni journald ni apport — le paquet partait sans un journal (« absents: journald:user,
    journald:kernel, reaper.log, apport.log », premier Mac réel 2026-11-04). Les journaux que golem y écrit
    lui-même : bridge.log (dossier GoleM des ressources REAPER), le lanceur, et sous macOS le dernier rapport
    de plantage de REAPER s'il date de la fenêtre."""
    out, missing = {}, []
    with contextlib.suppress(Exception):
        bl = os.path.join(C.reaper_resource_dir(), "GoleM", "logs", "bridge.log")
        if os.path.exists(bl):
            out["bridge.log"] = _tail(bl, LOG_BUDGET_BYTES // 2)
    if "bridge.log" not in out:
        missing.append("bridge.log")
    if sys.platform == "darwin":
        home = os.path.expanduser("~")
        ll = os.path.join(home, "Library", "Logs", "GoleM-launcher.log")
        if os.path.exists(ll):
            out["launcher.log"] = _tail(ll, LOG_BUDGET_BYTES // 6)
        else:
            missing.append("launcher.log")
        reports = os.path.join(home, "Library", "Logs", "DiagnosticReports")
        with contextlib.suppress(OSError):
            recent = sorted((e for e in os.scandir(reports) if e.name.lower().startswith("reaper")
                             and time.time() - e.stat().st_mtime <= window_s), key=lambda e: e.stat().st_mtime)
            if recent:
                out["reaper-crash.ips"] = _tail(recent[-1].path, LOG_BUDGET_BYTES // 3)
    with contextlib.suppress(Exception):
        from .monitors import _read_rig_check, RIG_CHECK_HIST
        rc_ = _read_rig_check()
        hist = _read_json(RIG_CHECK_HIST, [])
        if rc_ or hist:
            out["rig-check.json"] = json.dumps({"last": rc_, "history": hist}, ensure_ascii=False, indent=1)
    return {k: "\n".join(sc(ln) for ln in v.splitlines()) for k, v in out.items()}, missing


def _tail(path, max_bytes):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - max_bytes))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _fit_logs(logs, budget):
    """Tronque PAR LE DÉBUT (les lignes récentes gagnent) pour tenir dans le budget. Rend (logs, tronqué)."""
    total = sum(len(v.encode("utf-8")) for v in logs.values())
    if total <= budget:
        return logs, False
    out, share = {}, budget // max(1, len(logs))
    for k, v in logs.items():
        b = v.encode("utf-8")
        if len(b) > share:
            b = b[-share:]
            i = b.find(b"\n")
            b = b[i + 1:] if i >= 0 else b
        out[k] = b.decode("utf-8", "replace")
    return out, True


# ── le zip ───────────────────────────────────────────────────────────────────────────────────
def index():
    d = _read_json(_index_path(), [])
    return d if isinstance(d, list) else []


def _save_index(rows):
    _write_json_atomic(_index_path(), rows)


def build(kind, event_=None, previous=None, force=False):
    """Fabrique le paquet `kind` dans diag/, l'indexe, applique la rotation. Rend l'entrée d'index
    (+ `report` en clair pour les outils). Case décochée → None, sauf `force` (check-report.py :
    fabriquer sans envoyer reste permis, c'est du local)."""
    if not auto() and not force:
        return None
    rep = build_report(kind, event_=event_, previous=previous)
    sc = scrubber()
    window = LOG_WINDOW_SET_S if kind == "session" else LOG_WINDOW_S
    logs, missing = collect_logs(window, sc)
    logs, truncated = _fit_logs(logs, LOG_BUDGET_BYTES)
    rep["report"]["truncated"] = truncated
    rows = _read_timeline(since_s=None if kind == "session" else window)
    if kind == "boot" and previous:
        rows = _read_timeline(os.path.join(_dir(), "prev-timeline.ndjson")) + rows
    files = {"report.json": json.dumps(rep, ensure_ascii=False, indent=1),
             "timeline.ndjson": "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)}
    flush_samples()
    pts = samples() if kind != "boot" else []
    if kind == "boot" and previous:
        pts = _read_json(os.path.join(_dir(), "prev-samples.json"), []) or []
    if pts:
        files["samples.ndjson"] = "\n".join(json.dumps(s, ensure_ascii=False) for s in pts)
    for k, v in logs.items():
        files[f"logs/{k}"] = v
    manifest = {"golem_report": MANIFEST_VERSION, "kind": kind, "session_id": rep["report"]["session_id"],
                "report_id": rep["report"]["report_id"], "created_at": rep["report"]["created_at"],
                "files": {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in files.items()},
                "truncated": truncated, "missing": missing}
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    name = f"golem-{kind}-{ts}-{rep['report']['report_id'][:8]}.zip"
    path = os.path.join(_dir(), name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("golem-report.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        for k, v in files.items():
            z.writestr(k, v)
    data = buf.getvalue()
    if len(data) > MAX_ZIP_BYTES:
        raise RuntimeError(f"paquet trop gros : {len(data)} o > {MAX_ZIP_BYTES}")
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    entry = {"report_id": rep["report"]["report_id"], "kind": kind, "created_at": rep["report"]["created_at"],
             "file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
             "sent_at": None, "error": None}
    with _lock:
        rows_ = index()
        rows_.append(entry)
        rows_ = _rotate(rows_)
        _save_index(rows_)
    log.info(f"paquet {kind} fabriqué : {name} ({len(data)} o, {len(files)} fichiers"
             f"{', tronqué' if truncated else ''}{', absents: ' + ','.join(missing) if missing else ''})")
    return {**entry, "report": rep, "missing": missing}


def _rotate(rows):
    """Garde KEEP_REPORTS paquets ; un paquet NON envoyé n'est jamais purgé par la rotation."""
    keep, dropped = [], 0
    for r in reversed(rows):
        if len(keep) < KEEP_REPORTS or not r.get("sent_at"):
            keep.append(r)
        else:
            dropped += 1
            try:
                os.remove(os.path.join(_dir(), r.get("file") or ""))
            except OSError:
                pass
    return list(reversed(keep))


def report_path(report_id):
    for r in index():
        if r.get("report_id") == report_id:
            p = os.path.join(_dir(), r.get("file") or "")
            return p if os.path.exists(p) else None
    return None


def mark_sent(report_id, error=None):
    with _lock:
        rows = index()
        for r in rows:
            if r.get("report_id") == report_id:
                r["sent_at"] = None if error else _now()
                r["error"] = error
        _save_index(rows)


def status():
    """Pour GET /api/diag et les outils : la case, la session, l'index."""
    return {"auto": auto(), "session": session(), "reports": index(),
            "timeline_lines": sum(1 for _ in open(_timeline_path(), encoding="utf-8")) if os.path.exists(_timeline_path()) else 0}


# ── L'INTENTION (retour golem.fm, 2026-09-14) ────────────────────────────────────────────────
# Un `reaper down` sans intention se lit comme un abort — et le rack tuait Reaper sur trois
# chemins sans rien écrire (restart du Dashboard, changement de buffer/carte, mise à jour). Le
# site qui DÉCIDE l'arrêt pose l'intention AVANT le pkill ; le moniteur, qui VOIT l'arrêt, la
# joint à l'événement (`why`), et une chute annoncée ne fabrique pas de paquet `event`.
INTENT_TTL_S = 120
_intents = {}


def intent(kind, why):
    """« Je vais arrêter <kind>, parce que <why> » — posé par celui qui le décide."""
    _intents[kind] = (str(why), time.monotonic())
    return why


def peek_intent(kind, clear=False):
    """L'intention fraîche (< INTENT_TTL_S) pour <kind>, ou None. `clear` la consomme."""
    it = _intents.get(kind)
    if not it:
        return None
    why, t0 = it
    # `>=` et pas `>` : l'horloge monotone de Windows avance par pas de ~16 ms, deux lectures
    # voisines rendent la MÊME valeur — avec `>`, une durée de vie nulle ne périmait jamais
    # (tests/test_diag_send.py, mesuré sur la VM le 2026-10-01).
    if time.monotonic() - t0 >= INTENT_TTL_S:
        _intents.pop(kind, None)
        return None
    if clear:
        _intents.pop(kind, None)
    return why


# ── L'ENVOI (lot C) ──────────────────────────────────────────────────────────────────────────
SEND_TIMEOUT_S = 60           # envoi normal
SHUTDOWN_SEND_TIMEOUT_S = 5   # à l'arrêt : le réseau peut déjà tomber, on n'attend pas
EVENT_RATE_S = 600            # au plus un paquet `event` par nature toutes les 10 min
BOOT_WAIT_REAPER_S = 90       # le `boot` attend Reaper connecté, 90 s max
_rate = {}                    # nature -> horloge monotone du dernier paquet event
_previous = None              # bilan de la session précédente (open_session), pour le `boot`
_send_lock = threading.Lock()


def send(report_id, timeout=SEND_TIMEOUT_S):
    """POST du zip vers golem.fm (`/api/ext/diagnostics`, corps brut, sha256 dans l'URL — le contrat
    du vault). Rend (ok, détail). Jamais d'exception ; un échec laisse le paquet EN ATTENTE
    (`sent_at: null`, `error`), repris par `flush_pending()` au battement suivant ou au boot."""
    from .golemfm import _cfg
    row = next((r for r in index() if r.get("report_id") == report_id), None)
    if row is None:
        return False, "unknown report"
    if row.get("sent_at"):
        return True, "already sent"
    path = os.path.join(_dir(), row.get("file") or "")
    if not os.path.exists(path):
        mark_sent(report_id, error="file missing")
        return False, "file missing"
    base, token = _cfg()
    if not base or not token:
        mark_sent(report_id, error="not paired")
        return False, "not paired"
    url = (base + "/api/ext/diagnostics?filename=" + urllib.parse.quote(row["file"])
           + "&kind=" + row["kind"] + "&sha256=" + row["sha256"])
    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/zip")
    req.add_header("Content-Length", str(os.path.getsize(path)))
    try:
        with open(path, "rb") as f:
            req.data = f
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read() or b"null") or {}
        mark_sent(report_id)
        log.info(f"paquet {row['kind']} envoyé : {row['file']}"
                 f"{' (déjà connu de golem.fm)' if body.get('deduplicated') else ''}")
        return True, body
    except urllib.error.HTTPError as e:
        from .golemfm import http_error_text           # `detail` peut être une chaîne, un objet ou une liste (422)
        err = f"HTTP {e.code}: {http_error_text(e)}"
    except Exception as e:
        err = str(e)
    mark_sent(report_id, error=err[:200])
    log.warning(f"paquet {row['kind']} non envoyé ({err}) — en attente")
    return False, err


def flush_pending(timeout=SEND_TIMEOUT_S):
    """Envoie ce qui attend, dans l'ordre, un seul passage à la fois. Rend le nombre envoyé.
    Appelé par le pousseur de `rigstatus` (5 min) et au boot. Silencieux si non appairé."""
    if not auto():
        return 0
    if not _send_lock.acquire(blocking=False):
        return 0
    try:
        n = 0
        for r in list(index()):
            if r.get("sent_at"):
                continue
            ok, _ = send(r["report_id"], timeout=timeout)
            if not ok:
                break                     # golem.fm injoignable : inutile d'insister sur les suivants
            n += 1
        return n
    finally:
        _send_lock.release()


def trigger(type_, **fields):
    """Un événement qui peut MÉRITER un paquet `event` immédiat (§4.3) : on l'écrit toujours dans la
    chronologie ; si sa nature est déclencheuse, que la case est cochée et que la limite (une par
    nature / 10 min) le permet, un paquet part dans un thread — jamais sur la boucle."""
    row = event(type_, **fields)
    if row is None:
        return None
    rule = EVENT_TRIGGERS.get(type_)
    if rule is None or not rule(fields) or not auto():
        return row
    now = time.monotonic()
    if now - _rate.get(type_, -1e9) < EVENT_RATE_S:
        return row
    _rate[type_] = now
    detail = fields.get("why") or fields.get("msg") or fields.get("state") or ""

    def work():
        try:
            r = build("event", event_={"type": type_, "detail": str(detail)})
            if r:
                send(r["report_id"])
        except Exception as e:
            log.warning(f"paquet event ({type_}) non fabriqué : {e}")

    threading.Thread(target=work, daemon=True, name=f"diag-event-{type_}").start()
    return row


def boot(reason="boot"):
    """Au démarrage du bridge (synchrone, léger) : ouvre la session, garde le bilan de la précédente."""
    global _previous
    sess, _previous = open_session(reason)
    if _previous:
        log.info(f"session précédente non clôturée ({_previous.get('started_at')}) : "
                 "bilan reconstruit, partira avec le boot")
    return sess


def boot_report():
    """Le paquet `boot` (dans un thread) : d'abord ce qui attend, puis la machine + le bilan de la
    session précédente. Case décochée : rien."""
    if not auto():
        return None
    try:
        flush_pending()
        r = build("boot", previous=_previous)
        if r:
            send(r["report_id"])
        return r
    except Exception as e:
        log.warning(f"paquet boot non fabriqué : {e}")
        return None


def shutdown_report(reason="sigterm"):
    """À l'arrêt : ÉCRIRE D'ABORD (clôture + zip sur disque, < 1 s), ENVOYER ENSUITE, court.
    Un envoi qui traîne ne doit jamais empêcher l'écriture — s'il échoue, le paquet part au boot."""
    sess = close_session(reason)
    if sess is None or not auto():
        return None
    try:
        r = build("session")
    except Exception as e:
        log.warning(f"paquet session non fabriqué : {e}")
        return None
    if r:
        send(r["report_id"], timeout=SHUTDOWN_SEND_TIMEOUT_S)
    return r


async def boot_task():
    """Tâche asyncio du démarrage : attend Reaper connecté (90 s max) pour que le `boot` décrive un
    rig réel, puis fabrique et envoie hors boucle."""
    import asyncio
    from .state import state as st
    t0 = time.monotonic()
    while not st.reaper_connected and time.monotonic() - t0 < BOOT_WAIT_REAPER_S:
        await asyncio.sleep(2)
    await asyncio.get_running_loop().run_in_executor(None, boot_report)


# ── LE HASH D'UN PRESET, en cache (lot D) ────────────────────────────────────────────────────
_hash_cache = {}


def preset_hash_of(pid):
    """Hachage COURT du fichier du preset courant — jamais son id ni son nom. Cache par
    (id, mtime) : appelé à chaque tick de l'anneau et à chaque recall."""
    if not pid:
        return None
    try:
        from . import store
        # l'ESSAI d'un patch (sandbox-try) n'a pas de fichier à lui : c'est le document de la sandbox
        name = ".sandbox" if pid == getattr(store, "SANDBOX_TRY_ID", "sandbox-try") else store._safe_id(pid)
        path = os.path.join(C.PRESETS_DIR, f"{name}.json")
        mt = os.path.getmtime(path)
    except Exception:
        return None
    key = (pid, mt)
    h = _hash_cache.get(key)
    if h is None:
        try:
            h = short_hash(open(path, "rb").read())
        except OSError:
            return None
        _hash_cache.clear()
        _hash_cache[key] = h
    return h


# ── L'ANNEAU DE MESURES (lot D, §3.1) ────────────────────────────────────────────────────────
RING_POINTS = 200            # 10 min à 3 s
FLUSH_EVERY_S = 15           # écriture disque de l'anneau (le rack est un appareil qu'on débranche)
_ring = []                   # les RING_POINTS derniers échantillons (résolution 3 s)
_minutes = []                # une moyenne par minute, toute la session
_cur_min = None              # {"key": "YYYY-MM-DDTHH:MM", "n", sommes…}
_last_flush = 0.0
_cpu_prev = None


def _samples_path():
    return os.path.join(_dir(), "samples.json")


def _cpu_tick():
    """% CPU depuis le tick PRÉCÉDENT, sans dormir (rigstatus.cpu_pct dort 250 ms) : deux lectures
    de /proc/stat à 3 s d'écart. None au premier tick."""
    global _cpu_prev
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = [int(x) for x in parts[1:9]]
    except Exception:
        return None
    idle, total = vals[3] + vals[4], sum(vals)
    prev, _cpu_prev = _cpu_prev, (idle, total)
    if prev is None or total == prev[1]:
        return None
    return round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)


def sample(**fields):
    """Un point de l'anneau (chaque tick du moniteur audio). Garde 10 min en 3 s et une moyenne par
    minute pour la session ; flush disque toutes les 15 s. Rend la ligne (ou None si vocabulaire)."""
    global _cur_min, _last_flush
    row = {"t": _now(), "up": _up(), "res": "3s"}
    for k, v in fields.items():
        if k in EVENTS["sample"] and v is not None:
            row[k] = v
    with _lock:
        _ring.append(row)
        del _ring[:-RING_POINTS]
        key = row["t"][:16]
        if _cur_min is None or _cur_min["key"] != key:
            if _cur_min is not None:
                _minutes.append(_close_minute(_cur_min))
            _cur_min = {"key": key, "t": row["t"], "up": row["up"], "n": 0, "sum": {}, "last": {},
                        "xruns0": row.get("xruns"), "audio_bad": 0, "midi_bad": 0}
        m = _cur_min
        m["n"] += 1
        for k in ("latency_ms", "cpu_pct", "temp_c"):
            if isinstance(row.get(k), (int, float)):
                m["sum"][k] = m["sum"].get(k, 0.0) + row[k]
                m["last"][k] = m["last"].get(k, 0) + 1
        for k in ("mode", "scene", "preset_hash", "xruns"):
            if k in row:
                m["last"][k] = row[k]
        if row.get("audio_ok") is False:
            m["audio_bad"] += 1
        if row.get("midi_ok") is False:
            m["midi_bad"] += 1
    now = time.monotonic()
    if now - _last_flush >= FLUSH_EVERY_S:
        _last_flush = now
        flush_samples()
    return row


def _close_minute(m):
    out = {"t": m["t"], "up": m["up"], "res": "1m"}
    for k in ("latency_ms", "cpu_pct", "temp_c"):
        if m["last"].get(k):
            out[k] = round(m["sum"][k] / m["last"][k], 1)
    for k in ("mode", "scene", "preset_hash"):
        if k in m["last"]:
            out[k] = m["last"][k]
    if isinstance(m["last"].get("xruns"), int) and isinstance(m.get("xruns0"), int):
        out["xruns"] = m["last"]["xruns"] - m["xruns0"]      # xruns DANS la minute, pas le cumul
    out["audio_ok"] = m["audio_bad"] == 0
    out["midi_ok"] = m["midi_bad"] == 0
    return out


def samples():
    """Les minutes de la session + l'anneau des 10 dernières minutes (ce qui part dans le zip)."""
    with _lock:
        mins = list(_minutes) + ([_close_minute(_cur_min)] if _cur_min else [])
        return mins + list(_ring)


def flush_samples():
    try:
        _write_json_atomic(_samples_path(), samples())
    except OSError as e:
        _swallowed(e, "samples")


def reset_samples():
    """Nouvelle session : l'anneau repart ; le fichier de la précédente est archivé pour le `boot`."""
    global _cur_min, _cpu_prev
    with _lock:
        _ring.clear(); _minutes.clear(); _cur_min = None; _cpu_prev = None
    try:
        os.replace(_samples_path(), os.path.join(_dir(), "prev-samples.json"))
    except OSError:
        pass
