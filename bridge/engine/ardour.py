# SPDX-License-Identifier: GPL-3.0-or-later
"""Le Golem Engine (construit depuis Ardour) derrière le contrat (docs/ardour-plan.md §2, lot A1.4).

Même forme que REAPER, mesurée au spike A1.4 :
  - commandes : le MÊME slot presets/.command.json + accusé (commands.enqueue), lu par le veilleur Lua du moteur
    (golem-engine/golem/engine/golem_watch.lua) ;
  - chemin rapide : la surface OSC d'Ardour (port 3819). Elle écrit la valeur BRUTE d'un paramètre de plugin : la
    valeur normalisée du bridge est convertie avec la plage publiée par le moteur (`load_ranges`) ; sans plage
    connue, on refuse plutôt que d'écrire n'importe quoi ;
  - télémétrie : le retour OSC d'Ardour est TRADUIT dans le vocabulaire que le bridge lit déjà (/track/N/vu,
    /track/N/mute) : app.on_osc ne sait pas quel moteur parle ;
  - process : `luasession` lancé par golem/engine/run.sh, qui écrit son PID dans presets/.engine.pid.
Ce lot ne sait que ping et status : le reste du vocabulaire arrive avec A2/A3.
"""
import json
import logging
import math
import os
import signal
import subprocess
import time

from .. import config as C
from .base import EngineAdapter

log = logging.getLogger("golem.engine")

ENGINE_DIR = os.environ.get("GOLEM_ENGINE_DIR", os.path.expanduser("~/golem-engine"))
OSC_PORT = int(os.environ.get("GOLEM_ENGINE_OSC", "3819"))
def card_device():
    """Le nom de la carte ACTIVE de golem (config/cards/<carte>.json, la même que REAPER ouvre) — le veilleur la retrouve
    parmi les périphériques ALSA d'Ardour par un nom contenu dans l'autre. None si aucune carte n'est connue."""
    try:
        with open(os.path.join(C.ROOT, "config", "cards", f"{C.alsa_card()}.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("name") or None
    except (OSError, ValueError, AttributeError):
        return None


# la carte de golem en ALSA par défaut ; sans carte connue (un banc, une machine neuve) : le pilote factice, sans son
DEVICE = os.environ.get("GOLEM_ENGINE_DEVICE", card_device() or "")
BACKEND = os.environ.get("GOLEM_ENGINE_BACKEND", "ALSA" if DEVICE else "None (Dummy)")
# la session vit DANS golem (sets/, état local comme sets/golem-set.rpp) : rien hors de l'install
SESSION_DIR = os.environ.get("GOLEM_ENGINE_SESSION", os.path.join(C.ROOT, "sets", "golem-engine"))
RUN_LOG = os.environ.get("GOLEM_ENGINE_LOG", "/tmp/golem-engine.log")

# retour demandé à la surface : boutons (mute) + niveaux + vumètre en dB (bits 0, 1, 7 de /set_surface/feedback)
FEEDBACK = 1 | 2 | 128
STRIP_TYPES = 1 | 2 | 4          # pistes audio, pistes MIDI, bus audio : l'ordre des strips = celui du livemap
_TRANSPORT = {"play": "/transport_play", "pause": "/transport_stop", "stop": "/transport_stop", "start": "/goto_start"}


def pid_file():
    return os.path.join(C.PRESETS_DIR, ".engine.pid")


def db_to_vu(db):
    """Vumètre d'Ardour (dB, -193 = silence) -> l'échelle du bridge, 1,0 = 0 dBFS (contrôle d'écrêtage d'app.on_osc)."""
    return 0.0 if db <= -120 else 10 ** (db / 20.0)


def _bpm(cmd):
    """Le TEMPO du morceau, comme golem_rig.lua le pose sur REAPER (SetCurrentBPM) : celui de la ligne de setlist
    (`cmd.bpm`), sinon celui du preset (presets/<id>.json) — les delays et trémolos synchronisés suivent l'hôte."""
    try:
        b = float(cmd.get("bpm"))
        if 20 <= b <= 400:
            return b
    except (TypeError, ValueError):
        pass
    try:                                       # le nom tel que golem_rig le lit : l'id brut de la commande
        with open(os.path.join(C.PRESETS_DIR, f"{cmd.get('preset')}.json"), encoding="utf-8") as f:
            b = float((json.load(f) or {}).get("bpm"))
        return b if 20 <= b <= 400 else None
    except (OSError, ValueError, TypeError):
        return None


class ArdourEngine(EngineAdapter):
    id = "ardour"
    actions = frozenset({"ping", "status", "rig_recall", "scene_apply", "stomp", "rig_verify", "dump", "audio_set",
                         "plugins", "snapshot", "gapmeter"})
    PROC_NAMES = ("luasession",)

    def __init__(self, link=None):
        self._link = link
        self._on_message = None
        self._ranges = {}            # (track, fx, param) -> (lower, upper, logarithmic)
        self._said_range = set()

    # ── commandes : le slot de toujours ──────────────────────────────────────────────────
    def _send(self, cmd):
        """Un rappel ou une scène emporte son plan MOTEUR dans la commande (bridge/engine/ardour_plan.py) : une scène
        en file ne peut pas écraser le plan d'un rappel pas encore lu, et l'écriture reste celle, atomique, du slot."""
        from .. import commands
        if cmd.get("action") in ("rig_recall", "scene_apply"):
            from . import ardour_plan
            try:
                with open(ardour_plan.rig_path(cmd.get("preset")), encoding="utf-8") as f:
                    plan = ardour_plan.build(json.load(f))
            except (OSError, ValueError) as e:
                log.error(f"ardour : plan compilé illisible pour {cmd.get('preset')} ({e}) — commande non envoyée")
                return None
            for s in plan["skipped"]:
                log.info(f"ardour : {s.get('id') or s.get('path')} {s.get('type') or ''} {s.get('param') or ''} — {s['why']}")
            plan["bpm"] = _bpm(cmd)
            cmd = {**cmd, "plan": plan}
        return commands.enqueue(cmd)

    # ── lien OSC ─────────────────────────────────────────────────────────────────────────
    @property
    def link(self):
        if self._link is None:
            from ..reaper_osc import ReaperLink       # un lien UDP générique : envoi + écoute locale
            self._link = ReaperLink("127.0.0.1", OSC_PORT, C.BRIDGE_OSC_RECV_PORT, self._dispatch)
        return self._link

    def _dispatch(self, address, args):
        """Traduit le retour d'Ardour dans le vocabulaire du bridge."""
        if not self._on_message:
            return
        try:
            if address == "/strip/meter" and len(args) >= 2:
                return self._on_message(f"/track/{int(args[0])}/vu", (db_to_vu(float(args[1])),))
            if address == "/strip/mute" and len(args) >= 2:
                return self._on_message(f"/track/{int(args[0])}/mute", (float(args[1]),))
        except (TypeError, ValueError):
            return
        self._on_message(address, args)

    def start_feedback(self, on_message):
        self._on_message = on_message
        self.link.start()
        self.register_surface()

    def register_surface(self):
        """Dit à la surface où renvoyer son retour (port d'écoute du bridge) et quoi renvoyer. À refaire après chaque
        démarrage du moteur : la surface oublie ses clients."""
        lk = self.link
        lk.send("/set_surface/port", C.BRIDGE_OSC_RECV_PORT)
        lk.send("/set_surface/strip_types", STRIP_TYPES)
        lk.send("/set_surface/feedback", FEEDBACK)
        return True

    def stop_feedback(self):
        if self._link:
            self._link.stop()

    def talking(self):
        """La surface d'Ardour ne parle qu'à un changement : le battement du veilleur (presets/.engine-status.json,
        réécrit toutes les 2 s) dit qu'il lit ses commandes."""
        if self.pid() is None:
            return False
        try:
            return time.time() - os.stat(os.path.join(C.PRESETS_DIR, ".engine-status.json")).st_mtime < 6.0
        except OSError:
            return False

    def engine_started(self):
        if self._on_message:                         # le bridge écoute déjà : se réabonner auprès de la nouvelle surface
            self.register_surface()
        self.request_inventory()

    def request_inventory(self):
        """Demande au moteur lesquels des plugins de sa table sont installés (presets/.engine-plugins.json)."""
        from . import ardour_plan
        try:
            table = ardour_plan.load_table()
        except (OSError, ValueError):
            return None
        want = [{"type": t, **ardour_plan.plugin_of(e)} for t, e in table.items()]
        return self.send({"action": "plugins", "want": want})

    def inventory(self):
        """{at, found: {type: bool}, n, total} — None tant que le moteur n'a pas répondu."""
        try:
            with open(os.path.join(C.PRESETS_DIR, ".engine-plugins.json"), encoding="utf-8") as f:
                return json.load(f) or None
        except (OSError, ValueError):
            return None

    def missing_plugin(self, block_type):
        """Le type est dans la table mais son plugin n'est pas installé ici (inventaire du moteur)."""
        inv = self.inventory()
        return bool(inv) and (inv.get("found") or {}).get(block_type) is False

    # ── chemin rapide ────────────────────────────────────────────────────────────────────
    def load_ranges(self, ranges):
        """[{track, fx, param, lower, upper, log?}] — publiées par le moteur avec le livemap."""
        self._ranges = {(r["track"], r["fx"], r["param"]): (float(r["lower"]), float(r["upper"]), bool(r.get("log")))
                        for r in ranges or [] if {"track", "fx", "param", "lower", "upper"} <= set(r)}

    _lm = {"mtime": None, "ranges": {}}

    def _livemap_ranges(self):
        """(track, fx, p) -> (pmin, pmax, False), relu quand le livemap change (le moteur le réécrit à chaque rebuild)."""
        path = os.path.join(C.PRESETS_DIR, ".livemap.json")
        try:
            m = os.stat(path).st_mtime_ns
        except OSError:
            return {}
        if m != self._lm["mtime"]:
            rng = {}
            try:
                with open(path, encoding="utf-8") as f:
                    lm = json.load(f) or {}
                for b in (lm.get("blocks") or {}).values():
                    for pm in (b.get("params") or {}).values():
                        rng[(b.get("track"), b.get("fx"), pm.get("p"))] = (float(pm["pmin"]), float(pm["pmax"]), False)
            except (OSError, ValueError, KeyError, TypeError):
                rng = {}
            self._lm = {"mtime": m, "ranges": rng}
        return self._lm["ranges"]

    def raw_value(self, track, fx, param, norm):
        rng = self._ranges.get((track, fx, param)) or self._livemap_ranges().get((track, fx, param))
        if rng is None:
            return None
        lo, hi, logarithmic = rng
        n = max(0.0, min(1.0, float(norm)))
        if logarithmic and lo > 0 and hi > 0:
            return lo * math.pow(hi / lo, n)
        return lo + n * (hi - lo)

    def set_fx_param(self, track, fx, param, norm):
        raw = self.raw_value(track, fx, param, norm)
        if raw is None:
            key = (track, fx, param)
            if key not in self._said_range:
                self._said_range.add(key)
                log.warning(f"ardour : plage inconnue pour piste {track} fx {fx} param {param} — écriture refusée")
            return False
        # surface d'Ardour : strip (1-based, = piste du livemap), plugin et paramètre 1-based, valeur brute
        return self.link.send("/strip/plugin/parameter", [int(track), int(fx) + 1, int(param) + 1, float(raw)])

    def set_track_volume(self, track, value):
        return self.link.send("/strip/fader", [int(track), max(0.0, min(1.0, float(value)))])

    def set_track_mute(self, track, muted):
        return self.link.send("/strip/mute", [int(track), 1 if muted else 0])

    def transport(self, op):
        return self.link.send(_TRANSPORT[op], [])

    def refresh(self):
        self.register_surface()
        return self.link.send("/refresh", [])

    # ── cycle de vie ─────────────────────────────────────────────────────────────────────
    def pid(self):
        try:
            pid = int(open(pid_file()).read().strip())
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")
            with open(f"/proc/{pid}/stat") as f:
                if f.read().rsplit(")", 1)[-1].split()[0] == "Z":
                    return None
        except (OSError, ValueError):
            return None
        names = [os.path.basename(c.decode("utf-8", "replace")) for c in cmd if c]
        return pid if any(n in self.PROC_NAMES for n in names[:2]) else None

    def ready_since(self, t0):
        from .. import monitors
        return monitors._watch_started_since(t0)        # golem_watch.lua écrit la même ligne « démarré. surveille »

    def stop(self, timeout=10.0):
        pid = self.pid()
        if pid is None:
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return True
        end = time.time() + timeout
        while time.time() < end:
            if self.pid() is None:
                return True
            time.sleep(0.2)
        return False

    def run_script(self):
        return os.path.join(ENGINE_DIR, "golem", "engine", "run.sh")

    def restart(self, why="requested"):
        script = self.run_script()
        if not os.path.isfile(script):
            raise RuntimeError(f"Golem Engine not found ({script})")
        dead = self.stop()
        logf = open(RUN_LOG, "a")
        logf.write(time.strftime("\n── %Y-%m-%d %H:%M:%S ") + f"restart ({why}) — ancien arrêté : {dead}\n")
        logf.flush()
        subprocess.Popen(["bash", script, C.ROOT, SESSION_DIR, BACKEND, DEVICE], start_new_session=True,
                         stdout=logf, stderr=subprocess.STDOUT)
        return {"ok": True, "restarting": True}

    _table = {"mtime": None, "types": frozenset()}

    def plays(self, block_type):
        """Un type joue ici s'il est dans library/catalog/effects-golem-engine.json (relue quand elle change)."""
        from . import ardour_plan
        try:
            m = os.stat(ardour_plan.TABLE).st_mtime_ns
            if m != self._table["mtime"]:
                self._table = {"mtime": m, "types": frozenset(ardour_plan.load_table())}
        except (OSError, ValueError):
            return False
        return block_type in self._table["types"]

    # ── carte son (lot A2.2) ─────────────────────────────────────────────────────────────
    BUFFERS = (32, 64, 96, 128, 192, 256, 384, 512, 1024)

    def _status(self):
        try:
            with open(os.path.join(C.PRESETS_DIR, ".engine-status.json"), encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def audio(self):
        st = self._status() if self.pid() is not None else {}
        out = {}
        if st.get("buffer"):
            out["buffer"] = int(st["buffer"])
        if st.get("sample_rate"):
            out["rate"] = int(st["sample_rate"])
        if st.get("backend"):
            out["backend"] = st["backend"]
        if st.get("dsp_load") is not None:
            out["dsp_load"] = round(float(st["dsp_load"]), 1)
        return out

    def xruns(self):
        st = self._status() if self.pid() is not None else {}
        return int(st["xruns"]) if st.get("xruns") is not None else None

    def adopt_audio(self, audio):
        """Pas encore de buffer à soi : prendre celui du moteur d'avant (REAPER à 192 -> le Golem Engine à 192, pas 1024),
        ou le plus proche au-dessus dans notre liste."""
        path = os.path.join(C.ROOT, "config", "golem-engine.json")
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except (OSError, ValueError):
            cfg = {}
        if cfg.get("buffer") or not audio.get("buffer"):
            return
        b = int(audio["buffer"])
        size = b if b in self.BUFFERS else next((x for x in self.BUFFERS if x >= b), self.BUFFERS[-1])
        cfg["buffer"] = size
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        os.replace(tmp, path)
        log.info(f"ardour : buffer {size} repris du moteur d'avant ({b})")

    def set_buffer(self, size):
        """À chaud : le veilleur arrête puis relance le moteur avec le nouveau buffer (~26 ms), la session reste. Le
        choix est gardé dans config/golem-engine.json (état local), relu à chaque démarrage du moteur."""
        if size not in self.BUFFERS:
            raise ValueError(f"size must be one of {list(self.BUFFERS)}")
        path = os.path.join(C.ROOT, "config", "golem-engine.json")
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except (OSError, ValueError):
            cfg = {}
        cfg["buffer"] = size
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        os.replace(tmp, path)
        seq = self.send({"action": "audio_set", "buffer": size}) if self.pid() is not None else None
        return {"ok": True, "size": size, "restarting": False, "applied_live": seq is not None,
                "theoretical_ms": round(2 * size / 48000 * 1000, 1)}

    _version = None

    def version(self):
        if self._version is None:
            try:
                out = subprocess.run(["git", "-C", ENGINE_DIR, "describe", "--tags", "--always"],
                                     capture_output=True, text=True, timeout=3).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                out = ""
            self._version = out or None
        return self._version
