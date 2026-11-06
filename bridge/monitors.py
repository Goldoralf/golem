# SPDX-License-Identifier: GPL-3.0-or-later
"""Moniteurs d'arrière-plan (process Reaper, latence/xruns ALSA, accordeur) — extrait d'app.py (P3).
Appeler init(broadcast) au startup, puis create_task sur chaque _monitor_*/_poll_*."""
import os, re, json, glob, time, asyncio, contextlib, subprocess, sys, csv

from . import config as C
from .state import state
from .golog import get
from . import modes as _modes
from .golog import swallowed as _swallowed

# un logger par tag historique (audio/pedalboard/midi/perf/transcribe/take)
log_audio = get("audio")
log_pedalboard = get("pedalboard")
log_midi = get("midi")
log_perf = get("perf")
log_transcribe = get("transcribe")
log_take = get("take")
log_reaper = get("reaper")

_broadcast = None          # coroutine de diffusion WS, injectée par app.init au startup


def init(broadcast):
    global _broadcast
    _broadcast = broadcast


_PID_MEMO = {"t": 0.0, "pid": None, "fn": None}


def reaper_pid_recent(max_age=1.5):
    """Le PID de REAPER, relu au plus toutes les `max_age` s (audit 2026-11-04, P2) : sous Windows `_reaper_pid` lance
    `tasklist`, un process par scène sur le chemin du pied. Un PID mémorisé d'un REAPER qui vient de mourir fait
    échouer `_process_started` — rig_is_live retombe alors sur reaper_gen, comme avant."""
    now = time.monotonic()
    if now - _PID_MEMO["t"] > max_age or _PID_MEMO.get("fn") is not _reaper_pid:   # remplacée (tests) : relue
        _PID_MEMO.update(t=now, pid=_reaper_pid(), fn=_reaper_pid)
    return _PID_MEMO["pid"]


def _reaper_pid():
    """PID du process Reaper (None si éteint). Le PID — pas un booléen — car un RESTART rapide
    (< période de poll) doit être détecté : le PID change même si le down n'a jamais été observé."""
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe", "/FO", "CSV", "/NH"],
                                 capture_output=True, timeout=3)
            # tasklist emits UTF-16 with no console and ANSI with a console.
            raw = out.stdout or b""
            decoded = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "ascii",
                                 errors="replace")
            for row in csv.reader(decoded.splitlines()):
                if len(row) >= 2 and row[0].casefold() == "reaper.exe" and row[1].isdigit():
                    return int(row[1])
        except (OSError, subprocess.SubprocessError):
            pass
        return None
    if sys.platform == "darwin":
        for name in ("REAPER", "reaper"):
            try:
                out = subprocess.run(["pgrep", "-x", "-o", name], capture_output=True, text=True, timeout=3)
                if out.returncode == 0 and out.stdout.strip().isdigit():
                    return int(out.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                pass
        return None
    try:
        out = subprocess.run(["pgrep", "-x", "-o", "reaper"], capture_output=True, text=True, timeout=3)
        if out.returncode == 0 and out.stdout.strip():
            return int(out.stdout.split()[0])
    except Exception as _e:
        _swallowed(_e)
    try:
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                with contextlib.suppress(Exception):
                    # ⚠ ÉGALITÉ STRICTE, pas une sous-chaîne. Le noyau a un thread « oom_reaper »
                    # qui CONTIENT « reaper » : ce repli renvoyait donc son PID sur toute machine
                    # Linux, et le rack annonçait « Reaper allumé » alors qu'il était mort — y
                    # compris quand il venait de planter, c'est-à-dire au pire moment. Trouvé sur
                    # une VM nue le 2026-08-02. Même leçon que le routage de golem_watch : sur un
                    # nom de processus ou d'action, on compare, on ne cherche pas dedans.
                    if open(f"/proc/{pid}/comm").read().strip() == "reaper":
                        return int(pid)
    except Exception as _e:
        _swallowed(_e)
    return None


def _process_started(pid):
    """Heure de démarrage (epoch) d'un process. Linux : /proc/<pid>. Windows : GetProcessTimes —
    sans lui, rig_is_live tombait dans son repli « portabilité » et ADOPTAIT un rig mort avec le
    Reaper précédent (2026-10-02). macOS : `ps -o etime` (bridge/desktop_macos.py) — le même bug y
    attendait (docs/platforms.md, M1). Lève si l'heure n'est pas lisible (repli de l'appelant)."""
    if sys.platform == "darwin":
        from . import desktop_macos
        return desktop_macos.process_started(pid)
    if sys.platform != "win32":
        return os.stat(f"/proc/{pid}").st_mtime
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise OSError(ctypes.get_last_error(), f"OpenProcess({pid})")
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise OSError(ctypes.get_last_error(), f"GetProcessTimes({pid})")
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return created / 1e7 - 11644473600                     # FILETIME (100 ns depuis 1601) -> epoch
    finally:
        k32.CloseHandle(handle)


def _reaper_running():
    """Détecte le process Reaper (indépendant de l'OSC)."""
    return _reaper_pid() is not None


_last_reaper_pid = None      # PID observé au poll précédent (change = restart, même sans down visible)


async def _monitor_reaper():
    global _last_reaper_pid
    prev_pid = None
    while True:
        pid = await asyncio.get_running_loop().run_in_executor(None, _reaper_pid)
        running = pid is not None
        if pid != _last_reaper_pid:
            _last_reaper_pid = pid
            state.reaper_gen += 1        # start/stop/RESTART de Reaper -> invalide les caches de forme (_LAST_EMIT)
        if running != state.reaper_running:
            state.reaper_running = running
            if not running:
                state.reaper_connected = False   # process éteint -> lien OSC mort
            state.touch()
            await _broadcast()
            # lot 8 : Reaper tombé = un paquet `event` tout de suite (un abort de plugin ne laisse
            # rien dans le journal noyau — c'est apport.log, joint au paquet, qui le dit) — SAUF si
            # l'arrêt était voulu (`why` posé par diag.intent : restart, réglages, mise à jour)
            _diag_trigger("reaper", state="up" if running else "down", **_reaper_why(consume=running))
        elif running and pid != prev_pid and prev_pid is not None:
            _diag_trigger("reaper", state="restart", **_reaper_why(consume=True))
        # UN NOUVEAU REAPER, APRÈS UN AUTRE (relance, crash) : le son doit revenir tout seul (2026-10-13).
        # Le premier process vu par ce bridge est l'affaire de boot_recall ; ceux d'après rouvrent un projet qui
        # ne porte plus le rig (mesuré : une piste et son volume système), et rien ne le remontait tant que
        # personne ne rappelait un preset — « Restart REAPER » rendait le rack muet.
        global _seen_reaper
        if running and pid != prev_pid:
            if _seen_reaper:
                asyncio.create_task(_remount_after_restart(pid))
            _seen_reaper = True
        prev_pid = pid
        await asyncio.sleep(2)


_seen_reaper = False         # un process Reaper a déjà été vu par CE bridge (le premier = boot_recall)
_WATCH_LOG = os.path.join(C.PRESETS_DIR, ".watch.log")


def _watch_started_since(t0):
    """Le veilleur Lua du NOUVEAU process a-t-il démarré ? Il écrit « démarré. surveille … » dans .watch.log
    à son lancement — seule preuve qu'une commande sera lue : il CONSOMME sans l'exécuter toute commande
    posée avant lui (golem_watch.lua, anti-segfault au chargement du projet)."""
    try:
        if os.path.getmtime(_WATCH_LOG) < t0:
            return False
        with open(_WATCH_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(_WATCH_LOG) - 4096))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return False
    return any("démarré. surveille" in line for line in tail)


async def _remount_after_restart(pid):
    """Rejoue le preset et la scène en cours sur le Reaper qui vient de (re)démarrer, une fois son veilleur
    prêt — sauf si quelqu'un a rappelé entre-temps (le rig est alors déjà celui du nouveau process)."""
    t0 = time.time() - 5                                    # le veilleur peut précéder notre détection (poll 2 s)
    for _ in range(90):                                     # ~45 s : projet, audio, scripts de démarrage
        if _reaper_pid() != pid:
            return                                          # encore relancé entre-temps : la tâche suivante s'en charge
        if _watch_started_since(t0):
            break
        await asyncio.sleep(0.5)
    else:
        log_reaper.warning("Reaper relancé : veilleur Lua jamais démarré — rig non remonté (rappeler un preset)")
        return
    await asyncio.sleep(2.0)                                # le SETTLE du chargement du projet
    from . import recall as recall_mod
    pid_preset, scene = state.preset_id, state.scene_id
    if not pid_preset or recall_mod.rig_is_live(pid_preset):
        return
    ok = await asyncio.get_running_loop().run_in_executor(None, recall_mod.do_recall, pid_preset, scene)
    log_reaper.info(f"Reaper relancé : rig remonté ({pid_preset}, scène {scene}) -> {'ok' if ok else 'ÉCHEC'}")


def _reaper_why(consume=False):
    """{why: …} si un arrêt de Reaper était annoncé, sinon {} — consommé à la remontée (`up`)."""
    try:
        from . import diag
        why = diag.peek_intent("reaper", clear=consume)
        return {"why": why} if why else {}
    except Exception:
        return {}


def _diag_trigger(type_, **fields):
    """Pont vers la chronologie du lot 8 — jamais fatal pour un moniteur."""
    try:
        from . import diag
        diag.trigger(type_, **fields)
    except Exception as _e:
        _swallowed(_e, "diag")


def _diag_event(type_, **fields):
    try:
        from . import diag
        diag.event(type_, **fields)
    except Exception as _e:
        _swallowed(_e, "diag")


def _diag_take_stop(cur):
    """Fin de prise dans la chronologie : nature, durée, nombre de pistes — lus dans le manifeste
    que `_write_take_manifest` vient d'écrire (la vérité de la prise), jamais son nom ni ses gens."""
    try:
        d = os.path.join(C.ROOT, cur.get("file") or "")
        man = json.load(open(os.path.join(d, "take.json"))) if os.path.isdir(d) else {}
        dur = None
        try:
            t0, t1 = man.get("started_at"), man.get("ended_at")
            if t0 and t1:
                import datetime as _dt
                dur = int((_dt.datetime.fromisoformat(t1) - _dt.datetime.fromisoformat(t0)).total_seconds())
        except Exception:
            dur = None
        _diag_event("take", state="stop", kind=man.get("kind"), duration_s=dur,
                    tracks=len(man.get("files") or []) or None)
    except Exception as _e:
        _swallowed(_e, "diag take")


# ── moniteur audio : latence (hw_params ALSA du Volt) + xruns (journal noyau) ──
# Reaper tient le Volt en ALSA BRUT (hw:V276, cf. reaper.ini) — PAS PipeWire/JACK. La source
# fiable de latence est donc /proc/asound/<carte>/pcm0{p,c}/sub0/hw_params (world-readable),
# valide uniquement tant que Reaper tient la carte (sinon 'closed' -> None). Si un jour Reaper
# passe sur PipeWire/JACK, cette source change (pw-top ERR + quantum/rate deviennent la vérité).
_AUDIO_START = time.strftime("%Y-%m-%d %H:%M:%S")   # baseline xruns = démarrage du bridge
_DESKTOP_XRUN = {"stamp": None, "clock": 0, "count": 0}


def _read_latency_ms():
    """Latence round-trip (ms) = (period_p + period_c)/rate — une lame in + une lame out, = ce
    qu'affiche Reaper (~10 ms pour block 256 @48k). Valeur de CONFIG (statique, ne fluctue pas ;
    c'est xruns l'indicateur temps réel). period_size, PAS buffer_size (le ring complet = 3 périodes
    sur-compte ×3). None si Reaper ne tient pas la carte ('closed')."""
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        return desktop_audio.latency_ms()[0]
    try:
        total_period, rate = 0, 0
        for path in glob.glob(f"/proc/asound/{C.alsa_card()}/pcm0[pc]/sub0/hw_params"):
            txt = open(path).read()
            mp = re.search(r"period_size:\s*(\d+)", txt)
            mr = re.search(r"rate:\s*(\d+)", txt)
            if not (mp and mr):
                return None                      # 'closed' -> Reaper ne tient pas la carte
            total_period += int(mp.group(1)); rate = int(mr.group(1))
        if rate and total_period:
            return round(total_period / rate * 1000, 1)
    except Exception as _e:
        _swallowed(_e)
    return None


def _read_xruns():
    """Nb de dropouts (xrun/overrun USB) loggués par le noyau depuis le démarrage du bridge (None si indispo)."""
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        actual = desktop_audio._public_actual() or {}
        try:
            stamp = int(actual["AUDIO_XRUN_TIME"])
            clock = int(actual["XRUN_CLOCK"])
        except (KeyError, TypeError, ValueError):
            return None
        if clock < _DESKTOP_XRUN["clock"]:
            _DESKTOP_XRUN.update(stamp=0, count=0)
        if stamp > 0 and stamp != _DESKTOP_XRUN["stamp"] and _DESKTOP_XRUN["stamp"] is not None:
            _DESKTOP_XRUN["count"] += 1
        _DESKTOP_XRUN.update(stamp=stamp, clock=clock)
        return _DESKTOP_XRUN["count"]
    try:
        out = subprocess.run(
            ["journalctl", "-kq", "-g", "xrun|overrun|underrun|overflow|underflow",
             "-S", _AUDIO_START, "-o", "cat"],
            capture_output=True, text=True, timeout=5).stdout
        return sum(1 for ln in out.splitlines() if ln.strip())
    except Exception:
        return None


# ── « LE THREAD AUDIO AVANCE-T-IL ? » — la question que personne ne posait ────────────────
# Le 2026-08-08, la carte son a été ré-énumérée (débranchement/hub). Reaper a gardé un
# descripteur mort : PLUS RIEN ne sortait pendant treize heures — crêtes figées au bit près sur
# toutes les pistes, standard muet, horloge MIDI arrêtée — et le rack annonçait
# `reaper_running: true`, `reaper_connected: true`, `xruns: 0`. Aucun signal.
#
# ⚠ LES DEUX TÉMOINS ÉVIDENTS MENTENT. `Audio_IsRunning()` a rendu 1 pendant la panne, et
# `GetAudioDeviceInfo` rend la chaîne CONFIGURÉE (« ALSA V276 »), pas l'état réel. Mesurés.
#
# Le seul fait honnête est qu'un compteur du thread audio n'avance plus. On lit celui de la
# piste « MIDI Clock » — permanente, son JSFX tourne en @block sans rien attendre de personne,
# et golem_clock publie {ticks, t} une fois par seconde.
#   `t` avance et `ticks` avance  -> tout va bien
#   `t` avance et `ticks` FIGE    -> la boucle Lua vit, le THREAD AUDIO est mort  <- la panne
#   `t` fige                      -> c'est Reaper ou la boucle : un autre problème, pas celui-ci
_CLOCK_W = {"ticks": None, "t": None}


def _read_clock_witness():
    try:
        with open(os.path.join(C.PRESETS_DIR, ".clock.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _audio_alive():
    """(ok, raison). None = on ne sait pas encore — on n'alarme JAMAIS sur une ignorance."""
    w = _read_clock_witness()
    if not w:
        return None, "pas de témoin"
    prev, _CLOCK_W["ticks"], _CLOCK_W["t"] = dict(_CLOCK_W), w.get("ticks"), w.get("t")
    if prev["t"] is None:
        return None, "première lecture"
    if w.get("t") == prev["t"]:
        return None, "témoin non rafraîchi (boucle Lua ou Reaper)"   # autre panne, pas la nôtre
    if w.get("ticks") == prev["ticks"]:
        # ⚠ chaîne AFFICHÉE (title de la puce « NO AUDIO » sur /live) -> ANGLAIS, règle 4
        return False, "audio thread stalled — sound card lost?"
    return True, ""


# ── RÉCUPÉRATION AUTOMATIQUE, avec trois garde-fous ──────────────────────────────────────
# La panne est un SILENCE TOTAL et la récupération est prouvée (Audio_Quit + Audio_Init rouvre
# le périphérique — vérifié sur un vrai débranchement le 2026-08-08). Personne n'ouvre un
# terminal entre deux morceaux : le rack doit se rattraper seul. Mais une action automatique
# sur le périphérique audio se borne, sinon elle devient la panne suivante.
#
#   1. JAMAIS PENDANT UNE PRISE. golem_apply refuse déjà si le transport tourne ; on n'essaie
#      même pas, et surtout on NE BRÛLE PAS la tentative — elle attend la fin de la prise.
#   2. UNE SEULE TENTATIVE par épisode. Si la carte est physiquement absente, réessayer en rond
#      n'ajoute que du bruit dans les journaux et de la latence à chaque cycle.
#   3. ON LE DIT. Journal à l'envoi, journal au retour, et la puce reste rouge tant que ce n'est
#      pas revenu — une réparation silencieuse cache la panne au lieu de la traiter.
_AUDIO_FIX = {"tried": False}


def _active_card_missing():
    """Nom de la carte ACTIVE si elle n'est pas branchée, sinon None (lu dans state.cards)."""
    if sys.platform != "linux":
        return None
    c = state.cards or {}
    if c.get("active") and c.get("active_present") is False:
        return c.get("active_name") or c.get("active")
    return None


def _audio_recover(alive, why):
    """Rend le nouvel état `state.audio` et déclenche au plus UNE récupération par épisode."""
    if alive:
        if _AUDIO_FIX["tried"]:
            log_audio.info("✓ le thread audio est reparti")
        _AUDIO_FIX["tried"] = False
        return {"ok": True, "why": ""}
    # garde-fou 4 (2026-09-21) : la carte active n'est PAS BRANCHÉE. On dit laquelle, et on ne
    # brûle PAS l'unique tentative : Audio_Init échouerait, et au rebranchement il ne resterait
    # plus rien pour rouvrir le périphérique. La tentative part au premier tick où elle revient.
    missing = _active_card_missing()
    if missing:
        return {"ok": False, "why": f"{missing} is not connected", "card": missing,
                "fix": "plug it in, or switch to another card"}
    recording = bool((state.perf or {}).get("recording"))
    if recording:                                    # garde-fou 1 : la prise passe avant tout
        return {"ok": False, "why": why, "fix": "waiting — a take is recording"}
    if not _AUDIO_FIX["tried"]:                      # garde-fou 2 : une seule fois
        _AUDIO_FIX["tried"] = True
        log_audio.warning(f"⚠ {why} — récupération AUTOMATIQUE : audio_reset (une seule tentative)")
        with contextlib.suppress(Exception):
            from .commands import write_command
            write_command({"action": "audio_reset"})
        return {"ok": False, "why": why, "fix": "recovering…"}
    return {"ok": False, "why": why, "fix": "recovery had no effect — check the cable"}


# ── LE CONTRAT MIDI : le rack savait, et se taisait ──────────────────────────────────────
# `golem_midi.lua` publie presets/.midi.json en continu — qui ouvre l'entrée de l'AKAI, qui
# ouvre sa sortie, et ce qui cloche. Le 2026-08-08 il portait le diagnostic COMPLET (« entrée
# AKAI ouverte par PERSONNE -> lane Keys morte (masque midiins périmé) ») et sa réparation…
# sans que rien ne le montre nulle part : le mainteneur a cherché un son que le rack savait absent.
# Même motif que la carte son le matin même — on détecte, on ne dit pas.
# On ne publie que l'essentiel : l'état, ce qui cloche, et comment réparer. Fichier absent =
# sentinelle non chargée -> on n'alarme PAS (une ignorance n'est pas une panne).
def _read_governor():
    """Gouverneur CPU du cœur 0 (sysfs, lecture gratuite) — None sans cpufreq (VM).
    Windows : le plan d'alimentation lu comme un gouverneur (bridge/desktop_power.py)."""
    if sys.platform == "win32":
        from . import desktop_power
        return desktop_power.governor()
    try:
        return open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read().strip()
    except OSError:
        return None


def _read_rig_check():
    """presets/.rig-check.json — écrit par golem_rig (passe rig_verify de golem_watch, ~2 s après
    un recall) : les fichiers (modèle NAM, IR) que chaque plugin a RÉELLEMENT chargés, lus en clair
    sur le paramètre du plugin. {t, ok, checked, issues[]}. None = pas encore de témoin."""
    try:
        with open(os.path.join(C.PRESETS_DIR, ".rig-check.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


RIG_CHECK_HIST = os.path.join(C.PRESETS_DIR, ".rig-check.history.json")
RIG_CHECK_KEEP = 20


def _archive_rig_check(rc):
    """Empile une passe de vérification ANORMALE dans un journal borné.

    ⚠ Pourquoi (question de golem.fm, 2026-09-12) : `.rig-check.json` ne garde que la DERNIÈRE
    passe. Or sa valeur est dans les passes qui NE sont PAS vides — et celles-là s'effacent à la
    compilation suivante. Les quatre anomalies « expected %MODEL% » du 2026-09-11 avaient déjà
    disparu quand on est venu les lire : l'artefact le plus précieux du rack était aussi le plus
    fugace. On garde donc les 20 dernières passes à anomalies, horodatées.

    Seulement les anormales : une passe verte ne dit rien qu'on ne sache déjà (l'état courant le
    dit), et elle chasserait du journal les seules entrées qui méritent d'y être."""
    if not rc or rc.get("ok"):
        return
    try:
        with open(RIG_CHECK_HIST, encoding="utf-8") as f:
            hist = json.load(f)
        hist = hist if isinstance(hist, list) else []
    except (OSError, ValueError):
        hist = []
    if hist and hist[-1].get("t") == rc.get("t"):        # même passe relue : on n'empile pas deux fois
        return
    hist.append({"t": rc.get("t"), "checked": rc.get("checked"),
                 "issues": rc.get("issues") or [], "preset": state.preset_id})
    hist = hist[-RIG_CHECK_KEEP:]
    tmp = RIG_CHECK_HIST + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
        os.replace(tmp, RIG_CHECK_HIST)
    except OSError:
        pass


def _read_midi_health():
    try:
        with open(os.path.join(C.PRESETS_DIR, ".midi.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return {"ok": bool(d.get("ok")), "issues": list(d.get("issues") or []),
            "fix": d.get("fix") or "", "ts": d.get("ts")}


def _pedalboard_brief():
    """{id, name, source, stale} — de quoi dire à l'écran « quelle puce, et sur quelle base ».
    Une sonde qui échoue ne bascule plus sur un autre appareil (cf. pedalboard.probe) ; elle
    marque la mesure NON CONFIRMÉE, et ça doit se voir : un pédalier muet s'est cherché une
    heure faute de cette ligne (2026-08-08)."""
    try:
        from . import pedalboard as _pb
        a = _pb.active()
        return {"id": a.get("id"), "name": a.get("name"), "source": a.get("source"),
                "stale": bool(a.get("stale"))}
    except Exception:
        return None


# ── « en erreur » s'éteint tout seul : seuls les dropouts RÉCENTS font la tuile rouge ──────
# 10 min sans un xrun -> retour au vert (« N earlier »). Effacement manuel : xruns_clear(),
# appelé par le bouton de la tuile ET par un changement de buffer (les xruns d'avant
# parlaient de l'ancien réglage). state.xruns, le cumul, n'est jamais remis à zéro : le
# diagnostic calcule ses deltas dessus.
XRUN_RECENT_S = 600
_XRUN_EVENTS = []                                # [(epoch, nb)] des dropouts vus, purgé à la fenêtre


def _xruns_decay():
    """Recalcule state.xruns_recent (fenêtre glissante). Rend True si l'état a changé."""
    cut = time.time() - XRUN_RECENT_S
    _XRUN_EVENTS[:] = [e for e in _XRUN_EVENTS if e[0] >= cut]
    recent = sum(n for _, n in _XRUN_EVENTS)
    last = _XRUN_EVENTS[-1][0] if _XRUN_EVENTS else state.xruns_last
    if (recent, last) == (state.xruns_recent, state.xruns_last):
        return False
    state.xruns_recent, state.xruns_last = recent, last
    return True


def xruns_clear():
    """Acquitte les dropouts : la tuile repasse au vert, le cumul (diag) n'est pas touché."""
    _XRUN_EVENTS.clear()
    _xruns_decay()
    state.touch()


async def _monitor_audio():
    loop = asyncio.get_running_loop()
    while True:
        lat = await loop.run_in_executor(None, _read_latency_ms)
        xr = await loop.run_in_executor(None, _read_xruns)
        alive, why = await loop.run_in_executor(None, _audio_alive)
        # LA PREMIÈRE LECTURE NE CONCLUT PAS (il faut deux témoins pour voir les ticks avancer) — et le cycle suivant
        # est à 3 s : l'écran de chargement restait sur « opening sound card… » ~3,4 s après le lien OSC, pour un
        # démarrage de 7 s (2026-10-20 : « c'est trop long »). golem_clock réécrit le témoin chaque seconde :
        # on relit 1,2 s plus tard, et la carte est dite vivante au premier cycle.
        if alive is None and why == "première lecture":
            await asyncio.sleep(1.2)
            alive, why = await loop.run_in_executor(None, _audio_alive)
        mh = await loop.run_in_executor(None, _read_midi_health)
        pb = await loop.run_in_executor(None, _pedalboard_brief)
        changed = False
        # ⚠ `changed = False` était placé APRÈS ce bloc : un changement du PÉDALIER SEUL était
        # donc écrasé, et rien n'était diffusé. Sur un rack au repos — latence, xruns et audio
        # stables — la puce « ⚠ PEDAL? » de /live restait donc affichée indéfiniment, même une
        # fois le pédalier re-sondé avec succès. Le témoin ne partait plus, et il n'y avait
        # rien à réparer : c'est l'écran qui ne l'apprenait jamais.
        if pb is not None and pb != (state.pedalboard or None):
            if pb.get("stale") and not (state.pedalboard or {}).get("stale"):
                log_pedalboard.warning(f"⚠ « {pb.get('id')} » NON CONFIRMÉ (la sonde n'a pas répondu) "
                                       "— on garde la puce mesurée, son canal est le bon")
            if bool(pb.get("stale")) != bool((state.pedalboard or {}).get("stale")):
                _diag_event("chip", chip="PEDAL?", on=bool(pb.get("stale")))
            state.pedalboard = pb
            changed = True
        gov = await loop.run_in_executor(None, _read_governor)
        boost = None if gov is None else (gov == "performance")
        if boost != state.cpu_boost:
            state.cpu_boost = boost
            changed = True
        rc = await loop.run_in_executor(None, _read_rig_check)
        if rc is not None and rc != (state.rig_check or None):
            if not rc.get("ok") and rc.get("t") != (state.rig_check or {}).get("t"):
                _archive_rig_check(rc)                   # la passe anormale survit à la suivante
                for i in rc.get("issues") or []:
                    log_midi.warning(f"⚠ FX FILE {i.get('track')} FX#{i.get('fx')} ({i.get('kind')}) « {i.get('expected')} » "
                                     + ("réinjecté, rechargement" if i.get("repaired") else "NON chargé"))
                _diag_trigger("rig_check", ok=False, issues=len(rc.get("issues") or []),
                              kinds=sorted({str(i.get("kind")) for i in rc.get("issues") or [] if isinstance(i, dict)}))
            if bool(rc.get("ok")) != bool((state.rig_check or {}).get("ok", True)):
                _diag_event("chip", chip="FX FILE", on=not rc.get("ok"))
            state.rig_check = rc
            changed = True
        if mh is not None and mh != (state.midi or None):
            if not mh["ok"] and (state.midi or {}).get("ok") is not False:
                for i in mh["issues"]:
                    log_midi.warning(f"⚠ {i}")
            if bool(mh.get("ok")) != bool((state.midi or {}).get("ok", True)):
                _diag_event("chip", chip="NO MIDI", on=not mh.get("ok"))
                _diag_event("midi", state="plugged" if mh.get("ok") else "unplugged")
            state.midi = mh
            changed = True
        if alive is not None:
            new = _audio_recover(bool(alive), why)
            if new != (state.audio or {}):
                was_ok = (state.audio or {}).get("ok", True)
                if bool(new.get("ok")) != bool(was_ok):
                    _diag_event("chip", chip="NO AUDIO", on=not new.get("ok"))
                    # lot 8 : la carte qui disparaît est LE paquet `event` qui compte (13 h de
                    # silence sans un signal, 2026-08-08) ; sa récupération entre dans la chronologie
                    _diag_trigger("audio", state="recovered" if new.get("ok") else "lost", why=str(new.get("why") or ""))
                state.audio = new
                changed = True
        # fin d'un épisode d'écrêtage : 3 s sans plateau -> la puce s'éteint, la chronologie le note
        for key, c in list((state.clip or {}).items()):
            if not c.get("off") and time.time() - c["at"] > 3.0:
                c["off"] = True; changed = True
                _diag_event("chip", chip=f"IN {key[2:]} CLIP", on=False)
        if lat != state.latency_ms:
            state.latency_ms = lat; changed = True
        if sys.platform in ("win32", "darwin"):
            from . import desktop_audio
            actual = await loop.run_in_executor(None, desktop_audio._public_actual)
            _, source = desktop_audio.latency_ms(actual) if actual else (None, None)
            metrics = {"platform": sys.platform}
            if actual and str(actual.get("SRATE", "")).isdigit() and str(actual.get("BSIZE", "")).isdigit():
                metrics = {"platform": sys.platform, "source": source, "sample_rate": int(actual["SRATE"]),
                           "buffer_size": int(actual["BSIZE"]),
                           "driver": actual.get("IDENT_IN") or actual.get("IDENT_OUT"),
                           "xruns_available": "AUDIO_XRUN_TIME" in actual}
            if metrics != state.audio_metrics:
                state.audio_metrics = metrics; changed = True
        if xr is not None and xr != state.xruns:
            if xr > (state.xruns or 0):                  # lot 8 : le delta par tick, fenêtré par l'anneau
                _diag_trigger("xrun", delta=xr - (state.xruns or 0), window_s=3)
                _XRUN_EVENTS.append((time.time(), xr - (state.xruns or 0)))
            state.xruns = xr; changed = True
        changed = _xruns_decay() or changed
        if changed:
            state.touch(); await _broadcast()
        # lot 8 (§3.1) : un point de l'anneau par tick — hors boucle, rien ne bloque l'audio
        await loop.run_in_executor(None, _diag_sample, lat, xr)
        # PENDANT LE DÉMARRAGE, tant que la carte n'a pas de verdict, on repasse toutes les 0,5 s : le témoin apparaît
        # quand golem_clock se lance, et un cycle de 3 s le laissait attendre jusqu'à 3 s de plus sur l'écran de
        # chargement. Ensuite, le rythme de croisière (2026-10-20).
        await asyncio.sleep(0.5 if alive is None and not _boot_done() else 3)


def _boot_done():
    try:
        from . import boot_progress
        return bool(boot_progress.doc().get("done"))
    except Exception:
        return True


def _diag_sample(lat, xr):
    try:
        from . import diag, rigstatus
        diag.sample(xruns=xr, latency_ms=lat, cpu_pct=diag._cpu_tick(), temp_c=rigstatus.temp_c(),
                    audio_ok=(state.audio or {}).get("ok"), midi_ok=(state.midi or {}).get("ok"),
                    mode=(_modes.take_kind(state.mode) if (_modes and state.mode) else None),
                    scene=state.scene_id, preset_hash=diag.preset_hash_of(state.preset_id))
    except Exception as _e:
        _swallowed(_e, "diag sample")


# ── accordeur : golem_tuner.lua écrit presets/.tuner.json (note/cents), le bridge le suit ──
def _read_tuner_file():
    try:
        return json.load(open(C.TUNER_FILE))
    except Exception:
        return None


async def _poll_tuner():
    """Suit .tuner.json à ~20 Hz TANT QUE l'accordeur est armé (idle sinon). active=False si le signal fige."""
    loop = asyncio.get_running_loop()
    last_seq, last_change = -1, 0.0
    while True:
        if not state.tuner.get("on"):
            last_seq = -1
            await asyncio.sleep(0.3)
            continue
        data = await loop.run_in_executor(None, _read_tuner_file)
        now = time.time()
        if data and data.get("seq") != last_seq:
            last_seq = data.get("seq"); last_change = now
            state.tuner = {**state.tuner, **data, "on": True,
                           "active": bool(data.get("active")) and data.get("conf", 0) > 0}
            state.touch(); await _broadcast()
        elif state.tuner.get("active") and now - last_change > 0.4:   # signal figé -> "listening…"
            state.tuner = {**state.tuner, "active": False}
            state.touch(); await _broadcast()
        await asyncio.sleep(0.05)


# ── sample : golem_sample.lua écrit presets/.sample.json, le bridge réconcilie la fin des one-shots ──
_sample_ctl = None


def init_sample(ctl):
    global _sample_ctl
    _sample_ctl = ctl


async def _poll_sample():
    """Suit .sample.json quand des lanceurs de samples sont montés : réconcilie l'état optimiste
    (un one-shot qui se termine seul -> playing:false) et pousse state.samples -> WS."""
    loop = asyncio.get_running_loop()
    last = None
    while True:
        if not state.sample_switches:
            if last is not None:
                last = None
                state.samples = {}
                state.touch(); await _broadcast()
            await asyncio.sleep(0.4)
            continue
        def _read():
            try:
                return json.load(open(C.SAMPLE_FILE))
            except Exception:
                return None
        data = await loop.run_in_executor(None, _read)
        blocks = (data or {}).get("blocks") or {}
        if _sample_ctl:
            _sample_ctl.apply_feedback(blocks)
        sig = json.dumps(blocks, sort_keys=True)
        if sig != last:
            last = sig
            state.samples = _sample_ctl.snapshot() if _sample_ctl else {}
            state.touch(); await _broadcast()
        await asyncio.sleep(0.12)


# ── perf rec : golem_perfrec écrit presets/.perf.json — miroir dans state.perf (badge REC Live) ──
# Flags Companion : taps « mark that » pendant la prise, vidés au départ d'un enregistrement,
# écrits dans take.json au stop (le riff de 23h14 ressort dans golem.fm au découpage).
PERF_FLAGS = []
# Contexte observé PENDANT la prise et gravé dans take.json au stop. Aujourd'hui : la chanson
# de backing jouée par-dessus (lien vers golem.fm). C'est de la donnée IRRÉCUPÉRABLE après
# coup — le preset peut être réédité, la chanson sélectionnée changée — d'où la capture à chaud.
PERF_CTX = {}


def _bk_ctx(key, title, played):
    """Le backing d'une prise, tel que take.json le porte. `slug` = le slug golem.fm (c'est par lui que
    golem.fm range la prise, docs ranger-prises) ; la clé jouée, si c'est l'id d'une chanson .golem (lot 1.5),
    part à côté en `song_id` — jamais à la place."""
    from . import golemfm
    gs = golemfm.golemfm_slug(key)
    out = {"slug": gs or key, "title": title or gs or key, "played": played}
    if golemfm.is_song_key(key):
        out["song_id"] = key
    return out

# suit la croissance du dossier de la prise en cours -> débit réel + plancher (bridge/disk.py)
from .disk import Watch as _Watch
_watch = _Watch()
_DISK_EVERY_S = 30.0                    # au repos : la place disque est relue à ce rythme (une suppression doit se voir)
_DISK_AT = {"t": 0.0}

# ── MARQUES AUTOMATIQUES (roadmap 0.b) ─────────────────────────────────────────────────────
# Ce que la MACHINE a observé pendant la prise, en secondes depuis son début. `flags`, à côté,
# reste ce qu'un HUMAIN a marqué : deux natures de vérité, deux listes. Un consommateur qui veut
# la chronologie complète fusionne les deux sur `sec`.
#
# POURQUOI ON OBSERVE L'ÉTAT PLUTÔT QUE D'INSTRUMENTER LES APPELANTS
# Un recall arrive par l'API, par le pied, par un slot de setlist, par un changement de mode —
# et par ce qu'on ajoutera demain. Instrumenter chaque chemin, c'est en oublier un et ne le
# découvrir qu'au dépouillement d'une répète. La boucle de poll voit DÉJÀ l'état à 2 Hz : on
# compare, et tout nouveau chemin est journalisé gratuitement. Résolution 0,5 s, largement
# assez pour une frontière de morceau — et ce n'est PAS de l'édition à l'échantillon.
#
# ⚠ `sec` se calcule depuis `started_at`, publié par le Lua à la seconde : les marques sont
# justes à ±1 s. C'est bon pour découper des morceaux, ça ne l'est pas pour caler une coupe.
PERF_MARKS = []
_mark_prev = None


def _mark_state():
    """L'instantané comparé d'un tick à l'autre. Ajouter une clé ici suffit à la journaliser."""
    arr = state.arrangement or {}
    clk = state.click or {}
    return {
        "preset": state.preset_id,
        "scene": state.scene_id,
        # section de l'arrangement quand il tourne : la structure interne du morceau, offerte
        "section": arr.get("name"),
        "click": bool(clk.get("on")),
        "bpm": round(float(clk.get("bpm") or 0), 2) or None,
    }


def _mark_sec(started_at):
    import time as _t
    with contextlib.suppress(Exception):
        t0 = _t.mktime(_t.strptime(started_at, "%Y-%m-%dT%H:%M:%S"))
        return max(0.0, round(_t.time() - t0, 1))
    return None


def _mark_scan(started_at, first=False):
    """Compare l'état au précédent et journalise ce qui a bougé. `first` = début de prise :
    on pose l'état INITIAL à sec 0 — sans lui, un morceau joué d'un bout à l'autre sans changer
    de preset n'aurait aucune marque, et on ne saurait même pas ce qui a été joué."""
    global _mark_prev
    cur = _mark_state()
    prev = None if first else _mark_prev
    sec = 0.0 if first else _mark_sec(started_at)
    at = time.strftime("%Y-%m-%dT%H:%M:%S")
    for k, v in cur.items():
        if k == "bpm":
            continue                                  # le tempo voyage AVEC la marque click
        if prev is not None and prev.get(k) == v:
            continue
        if v in (None, ""):
            continue                                  # ni une valeur absente, ni une qui disparaît :
                                                      # « section = None » n'est pas un repère (False, si)
        m = {"sec": sec, "at": at, "kind": k, "value": v}
        if k == "preset":
            m["name"] = state.preset_name              # le NOM du morceau, pas seulement son id
            song = getattr(state, "song", None)
            if song and (song.get("slug") or song.get("title")):
                # la LIGNE de setlist (setlists.md §9) : slug opaque + titre, recopiés — la découpe
                # nomme le morceau sans passer par le backing du preset
                m["song"] = {k2: song.get(k2) for k2 in ("slug", "title", "line") if song.get(k2)}
        if k == "click":
            m["bpm"] = cur["bpm"]                      # un tempo daté : tempo-map et mesures
        PERF_MARKS.append(m)
    _mark_prev = cur


def _standard_title(slug):
    """Le titre lisible d'un standard, depuis le miroir local (library/standards/synced).
    Le slug à défaut : un manifeste ne doit jamais échouer pour un libellé manquant."""
    with contextlib.suppress(Exception):
        p = os.path.join(C.ROOT, "library", "standards", "synced", f"{slug}.json")
        return (json.load(open(p)) or {}).get("title") or slug
    return slug


def _band_tag():
    """Le groupe du rack, tel qu'il est AU MOMENT DE LA PRISE. `source` voyage avec : le serveur
    doit savoir si le tag vient d'un roster synchronisé ou du roster local temporaire — un tag
    posé sur un écran tactile sans login est une DÉCLARATION, pas une preuve (identity.md)."""
    with contextlib.suppress(Exception):
        b = (json.load(open(os.path.join(C.CONFIG_DIR, ".band.json"))) or {}).get("band") or {}
        if b.get("id"):
            return {"id": b["id"], "name": b.get("name") or b["id"],
                    "source": b.get("source") or "cache"}
    return None                                   # pas de groupe : la prise attend ici


# ── SESSION : une répète, plusieurs prises ─────────────────────────────────────────────────
# Rien à maintenir en mémoire (une session doit survivre à un redémarrage du bridge) : on la
# DÉDUIT au stop, en regardant si la prise précédente s'est terminée il y a peu.
SESSION_GAP_H = 6.0


def _session_id(started_at):
    """Reprend la session de la prise précédente si l'écart est court, en ouvre une sinon."""
    import time as _t
    ts = lambda x: _t.mktime(_t.strptime(x, "%Y-%m-%dT%H:%M:%S"))
    with contextlib.suppress(Exception):
        t0 = ts(started_at)
        best = None
        root = os.path.join(C.ROOT, "recordings")
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            man = os.path.join(p, "take.json") if os.path.isdir(p) else (p + ".json")
            if not os.path.isfile(man):
                continue
            with contextlib.suppress(Exception):
                d = json.load(open(man))
                e = ts(d.get("ended_at") or "")
                if e <= t0 and (best is None or e > best[0]):
                    best = (e, d.get("session"))
        if best and best[1] and (t0 - best[0]) < SESSION_GAP_H * 3600:
            return best[1]
        return "sess-" + started_at.replace("-", "").replace(":", "").replace("T", "-")[:13]
    return None

async def _poll_click():
    """Suit .click.json (écrit par golem_click.lua) à 2 Hz : état du métronome -> state.click
    (tuile claim /live, témoin). Léger : le fichier ne bouge qu'au toggle/config."""
    loop = asyncio.get_running_loop()
    path = os.path.join(C.PRESETS_DIR, ".click.json")
    last = None
    while True:
        def _read():
            try:
                return json.load(open(path))
            except Exception:
                return None
        data = await loop.run_in_executor(None, _read)
        cur = {"on": bool((data or {}).get("on")), "present": bool((data or {}).get("present")),
               "bpm": (data or {}).get("tempo")}
        if cur != last:
            last = cur
            state.click = cur
            state.touch(); await _broadcast()
        await asyncio.sleep(0.5)


async def _poll_cards():
    """Détection des cartes son (gear-registry É2) à 3 s : publie l'active + les CANDIDATES au
    switch (connectées, non actives, non ignorées) -> bannière de la page Soundcard."""
    if sys.platform != "linux":
        from . import desktop_audio
        last = None
        # LA TÉLÉMÉTRIE QUI SE TAIT N'EST PAS UNE CARTE ABSENTE (2026-10-05). L'état ouvert par REAPER
        # vient de golem_desktop_audio.lua, une boucle defer réécrite toutes les 2 s. Quand les boucles
        # GoleM de REAPER s'arrêtent (une erreur Lua les emportait toutes), le fichier vieillit, `actual`
        # devient vide, et l'écran disait « No sound card » alors que le son passait. Silence ≠ absence :
        # on ne conclut rien de la carte, on dit que les scripts se sont arrêtés — avec la dernière
        # erreur écrite par la garde de __startup.lua, si elle existe.
        fresh_seen = False
        quiet = unheard = 0
        errlog = os.path.join(C.PRESETS_DIR, ".lua-errors.log")
        while True:
            # une erreur ponctuelle (fichier tenu par REAPER…) ne doit pas TUER la boucle : sans elle,
            # plus aucun état de carte ni « REAPER stopped listening » jusqu'au redémarrage (2026-10-05)
            try:
                settings = await asyncio.get_running_loop().run_in_executor(None, desktop_audio.settings)
            except Exception as e:
                log_audio.warning(f"cartes : lecture des réglages audio impossible ({e}) — nouvel essai dans 3 s")
                await asyncio.sleep(3)
                continue
            driver = settings.get("driver") if sys.platform == "win32" else settings.get("input_device")
            actual = settings.get("actual") or {}
            present = bool(actual.get("MODE") and driver)
            if sys.platform == "darwin" and actual:
                # l'entrée CONFIGURÉE est-elle celle que REAPER a ouverte ? Débranchée, REAPER retombe sur le
                # micro intégré et la carte restait « présente » (audit macOS, 2026-11-04)
                from . import cards as cards_mod
                present = bool(cards_mod.mac_opened_input())
            if sys.platform == "win32":
                opened = actual.get("IDENT_IN", "") + " " + actual.get("IDENT_OUT", "")
                present = bool(driver and actual.get("MODE", "").upper() == "ASIO" and
                               driver.casefold() in opened.casefold())
            stalled, lua_error, never = False, None, False
            if actual:
                fresh_seen, quiet, unheard = True, 0, 0
            elif state.reaper_connected and fresh_seen:
                quiet += 1
                stalled = quiet >= 3                       # ~9 s sans un mot d'une boucle qui parle toutes les 2 s
            elif state.reaper_connected:
                # JAMAIS ENTENDUES (2026-11-04, premier Mac réel) : REAPER répondait par OSC mais une boîte modale
                # (« REAPER Preferences » d'un profil neuf, cachée par open -j) empêchait __startup.lua de tourner —
                # ni veilleur ni télémétrie, et rien à l'écran : `fresh_seen` n'étant jamais vrai, ce cas passait
                # sous le radar. 60 s : le premier lancement balaie les plugins avant de lancer nos scripts.
                unheard += 1
                stalled = never = unheard >= 20
            else:
                fresh_seen, quiet, unheard = False, 0, 0   # REAPER relancé : on attend qu'il reparle
            if stalled:
                present = None                             # inconnu, pas « débranchée »
                try:
                    with open(errlog, encoding="utf-8", errors="replace") as f:
                        lines = [ln for ln in f.read().splitlines() if ln[:2] == "20"]
                    lua_error = lines[-1][:300] if lines else None
                except OSError:
                    pass
            cands = []
            if sys.platform == "darwin":
                # les interfaces branchées autres que la carte active (cards.connected) : la bannière « Switch to »,
                # comme sous Linux — une Volt branchée n'était jamais proposée (2026-11-04)
                try:
                    from . import cards as cards_mod
                    ignored = {d["id"] for d in cards_mod.registry() if d.get("ignored")}
                    known_ids = {d["id"] for d in cards_mod.registry()}
                    cands = [{"id": c["id"], "name": c["name"], "known": c["id"] in known_ids}
                             for c in cards_mod.connected() if c["id"] != driver and c["id"] not in ignored]
                except Exception as e:
                    log_audio.warning(f"cartes : interfaces Core Audio illisibles ({e})")
            cur = {"active": driver or "", "active_present": present,
                   "active_name": driver or "", "candidates": cands, "known": [],
                   "scripts_stalled": stalled, "scripts_never_started": never, "lua_error": lua_error}
            if cur != last:
                last = cur
                state.cards = cur
                state.touch(); await _broadcast()
            await asyncio.sleep(3)
    loop = asyncio.get_running_loop()
    last = None
    while True:
        def _scan():
            try:
                from . import cards as cards_mod
                dev = (json.load(open(os.path.join(C.CONFIG_DIR, "io.json"))) or {}).get("device", "")
                active = dev.split(":", 1)[1] if ":" in dev else dev
                reg = {d["id"]: d for d in cards_mod.registry()}
                here = {c["id"] for c in cards_mod.connected()}
                cands = [{"id": c["id"], "name": c["name"], "known": c["id"] in reg}
                         for c in cards_mod.connected()
                         if c["id"] != active and not reg.get(c["id"], {}).get("ignored")]
                # les cartes CONNUES, branchées ou non (gear-registry É3) : préparer une 8×8 avant
                # qu'elle arrive était un travail invisible — l'écran ne montrait que le branché.
                # Charge utile volontairement maigre : ce paquet part dans CHAQUE tick du WS.
                known = [{"id": d["id"], "name": d.get("name") or d["id"],
                          "inputs": d.get("inputs"), "outputs": d.get("outputs"),
                          "connected": d["id"] in here, "active": d["id"] == active,
                          "prepared": os.path.exists(os.path.join(C.CONFIG_DIR, "inputmaps", f"hw-{d['id']}.json"))}
                         for d in reg.values() if not d.get("ignored")]
                known.sort(key=lambda k: (not k["active"], not k["connected"], k["id"].lower()))
                # LA CARTE ACTIVE EST-ELLE LÀ ? (2026-09-21) Débranchée, Reaper démarrait sur un
                # « ALSA: error opening input device » à lui, et l'écran du rack ne disait rien. Le
                # bandeau global de l'app (main.js CardMissing) et la puce de /live lisent ces deux champs.
                return {"active": active, "candidates": cands, "known": known,
                        "active_present": active in here,
                        "active_name": (reg.get(active) or {}).get("name") or active}
            except Exception:
                return None
        cur = await loop.run_in_executor(None, _scan)
        if cur is not None and cur != last:
            last = cur
            state.cards = cur
            state.touch(); await _broadcast()
        await asyncio.sleep(3)


async def _poll_hotplug():
    """Veille hotplug UNIFIÉE (audit 2026-08-12 §3, chantier ⑤) à 3 s, sur le patron de
    _poll_cards : scan /proc/asound (bridge/hotplug.py), débounce d'insertion (l'USB
    s'énumère en plusieurs temps), identification PURE (profil calibré / descripteur de
    pédalier USB / inconnu), publication state.hotplug -> WS (bannière Soundcard).

    Un pédalier USB qui apparaît relance la sonde SysEx d'identité — généralisation de
    detect_async, qui ne tournait qu'au démarrage : un pédalier branché après le boot
    n'était JAMAIS sondé. C'est la SEULE action automatique, et elle ne fait que poser une
    question à l'appareil : on détecte et on PROPOSE, jamais de restart sans geste.

    Anti-bruit : un appareil stable ne redéclenche rien (il faut un vrai départ puis un
    retour), et quand rien ne change il n'y a NI log NI broadcast."""
    loop = asyncio.get_running_loop()
    from . import hotplug
    watch = hotplug.new_watch()
    events, last = [], None
    booted_at = time.time()
    reinit_at = 0.0
    while True:
        def _scan():
            try:
                return hotplug.scan(), hotplug.context()
            except Exception:
                return None
        got = await loop.run_in_executor(None, _scan)
        if got is not None:
            seen, ctx = got
            watch, arrivals, departures = hotplug.step(watch, seen, time.time())
            for d in arrivals + departures:
                v = hotplug.identify(d, ctx)
                if v["kind"] == "soundcard":
                    continue                 # l'étage carte son a déjà sa bannière (state.cards)
                ev = "plug" if d in arrivals else "unplug"
                log_midi.info("hotplug : « %s » %s — %s"
                              % (d.get("name"), "branché" if ev == "plug" else "débranché",
                                 v.get("label")))
                events.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": ev,
                               "name": d.get("name"), "kind": v["kind"], "label": v["label"]})
                if ev == "plug" and v["kind"] == "pedalboard":
                    with contextlib.suppress(Exception):
                        from . import pedalboard as _pb
                        _pb.detect_async()   # non réentrante : une sonde en cours n'empile pas
            # ── WINDOWS : RÉPARATION MIDI AUTO (2026-10-03) ──
            # REAPER n'ouvre ses appareils MIDI qu'à son démarrage : un appareil rebranché (ou ré-énuméré par
            # Windows) pendant qu'il tourne reste une prise MORTE — le Nitro sonnait dans son casque, rien
            # n'arrivait. Sous Linux, golem_midi.lua le voit dans /proc/asound et lance midi_reinit ; sous
            # Windows ce constat n'existe pas, mais le MOMENT de la panne se voit : un appareil que REAPER
            # doit tenir qui (ré)apparaît. On demande alors à REAPER de rouvrir ses appareils — midi_reinit
            # SEUL, aucun masque touché (ceux-là ne changent qu'au démarrage). Jamais à l'amorçage (REAPER
            # vient de tout ouvrir), et au plus une fois par 10 s (un hub qui ré-énumère tout d'un coup).
            # macOS (2026-10-04, M5) : REAPER n'y ouvre lui aussi ses appareils qu'au démarrage — même remède.
            if sys.platform in ("win32", "darwin") and arrivals and time.time() - booted_at > 15 and time.time() - reinit_at > 10:
                with contextlib.suppress(Exception):
                    from . import desktop_midi
                    held = [d.get("name") for d in arrivals
                            if any(desktop_midi.same(d.get("name"), n) for n in desktop_midi.keys_device_names())]
                    if held:
                        from .commands import write_command
                        write_command({"action": "midi_reinit", "why": "replugged: " + ", ".join(held)})
                        reinit_at = time.time()
                        log_midi.info("réparation MIDI auto : %s rebranché — midi_reinit demandé à REAPER" % ", ".join(held))
                        events.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": "reinit",
                                       "name": ", ".join(held), "kind": "midi",
                                       "label": "REAPER reopened its MIDI devices"})
            del events[:-hotplug.EVENTS_MAX]
            cur = hotplug.snapshot(watch["present"], events, ctx)
            if cur != last:
                last = cur
                state.hotplug = cur
                state.touch(); await _broadcast()
        await asyncio.sleep(3)


async def _poll_perf():
    loop = asyncio.get_running_loop()
    path = os.path.join(C.PRESETS_DIR, ".perf.json")
    last = None
    while True:
        def _read():
            try:
                return json.load(open(path))
            except Exception:
                return None
        data = await loop.run_in_executor(None, _read)
        cur = {"recording": bool((data or {}).get("recording")),
               "file": (data or {}).get("file") or "",
               "started_at": (data or {}).get("started_at") or ""}
        # CONTEXTE de la prise, observé PENDANT qu'elle tourne (0,5 s de résolution suffit) :
        # le backing peut être lancé APRÈS le Record, donc le lire une seule fois au démarrage
        # raterait le cas courant. On retient la chanson dès qu'elle joue, et on ne l'oublie plus.
        if cur["recording"]:
            bk = state.backing or {}
            if bk.get("playing") and bk.get("slug"):
                title = next((s.get("title") for s in (bk.get("songs") or [])
                              if s.get("slug") == bk["slug"]), None)
                PERF_CTX["backing"] = _bk_ctx(bk["slug"], title, True)
            elif "backing" not in PERF_CTX and bk.get("present") and bk.get("slug"):
                title = next((s.get("title") for s in (bk.get("songs") or [])
                              if s.get("slug") == bk["slug"]), None)
                PERF_CTX["backing"] = _bk_ctx(bk["slug"], title, False)
            # LE STANDARD, miroir exact de `backing` (message-golem-enregistrements.md §2) :
            # « je m'enregistre par-dessus Summertime » n'était pas lisible dans la prise, qui
            # tombait en `source: free` — vrai, mais pauvre. Même sémantique de `played` :
            # présent (la grille est chargée) vs joué (elle a tourné pendant la prise).
            sd = state.standard or {}
            if sd.get("standard"):
                played = bool(sd.get("playing"))
                if played or "standard" not in PERF_CTX:
                    PERF_CTX["standard"] = {"id": sd["standard"],
                                            "title": _standard_title(sd["standard"]),
                                            "played": played or (PERF_CTX.get("standard") or {}).get("played", False),
                                            "bars": sd.get("bars") or 0}
            # LE LOOPER, lecture minimale (décision 2026-09-07, §3a du même message) : en
            # mode `mix` le résultat des boucles est DÉJÀ dans le fichier ; le flag dit juste
            # qu'il y en avait, et lesquelles. On accumule l'UNION des boucles vues actives —
            # une boucle lancée puis arrêtée avant le stop compte, elle s'entend dans la prise.
            for i, sl in enumerate((state.looper or {}).get("slots") or []):
                if sl.get("state") in ("play", "rec", "overdub"):
                    lp = PERF_CTX.setdefault("looper", {"active": True, "loops": []})
                    lab = sl.get("label") or f"Loop {i + 1}"
                    if lab not in lp["loops"]:
                        lp["loops"].append(lab)
        # ── PLACE DISQUE (roadmap 0.a) : on mesure ce qui s'écrit VRAIMENT, et on arrête au
        # plancher plutôt que de laisser l'écriture échouer au milieu d'un morceau.
        from . import disk as _disk
        if cur["recording"]:
            _mark_scan(cur.get("started_at") or "")     # journalise ce qui a bougé (roadmap 0.b)
            why = _watch.tick(cur.get("file") or "")
            state.disk = _disk.status(_watch.rate)
            if why:
                from .commands import write_command
                write_command({"action": "perf_rec", "on": False})
                state.perf_error = why
                log_perf.warning(f"{why}")
                state.touch(); await _broadcast()
        elif not last or last.get("recording") or time.time() - _DISK_AT["t"] > _DISK_EVERY_S:
            # au repos : l'estimation prudente suffit — mais RELUE toutes les 30 s. Elle ne l'était qu'au
            # démarrage et à la fin d'une prise : 23 Go de prises effacés le 2026-09-29, et la barre
            # affichait toujours « 13.8 GB free » pour un disque qui en avait 35.
            state.disk = _disk.status()
            _DISK_AT["t"] = time.time()
        if cur != last:
            if cur["recording"] and not (last or {}).get("recording"):
                PERF_FLAGS.clear()                       # nouvelle prise -> flags remis à zéro
                PERF_CTX.clear()
                PERF_MARKS.clear()
                # LE GROUPE EST GELÉ AU DÉPART, pas au stop : une prise appartient à qui jouait
                # quand elle a commencé. Les deux coïncident presque toujours (on change de
                # groupe ENTRE les morceaux), mais quand ils diffèrent, c'est le départ qui a
                # raison. Même raison que `backing`, capturé pendant : c'est irrécupérable après.
                PERF_CTX["band"] = _band_tag()
                _mark_scan(cur.get("started_at") or "", first=True)   # l'état INITIAL, à sec 0
                _watch.reset()                           # nouvelle prise -> nouveau débit mesuré
                state.perf_error = ""                    # un départ réussi efface le refus précédent
                with contextlib.suppress(Exception):     # une capture de riff attendait ce départ (compo.md §11)
                    from . import compo as _compo
                    _compo.on_perf_start()
                _diag_event("take", state="start", kind=_modes.take_kind() if _modes else None)
            # fin de prise (true -> false avec un fichier) : écrit le MANIFESTE take.json —
            # le « dossier prêt à partir » (2026-07-24) : contexte musical + params du REC.
            if last and last.get("recording") and not cur["recording"] and cur["file"]:
                await loop.run_in_executor(None, _write_take_manifest, cur)
                await loop.run_in_executor(None, _diag_take_stop, cur)
                # la prise apparaît dans l'index « À ranger » de golem.fm sans attendre le tick
                # de 5 min du heartbeat (docs/private/exchanges/message-maestrium-ranger-prises.md §1)
                with contextlib.suppress(Exception):
                    from . import rigstatus as _rs
                    _rs.push_soon()
                # AUTO (docs/archive/tablature-study.md §12) : la prise part en transcription dès qu'elle
                # est fermée — donc APRÈS le manifeste, qui porte le BPM dont le moteur a besoin.
                # Jamais pendant le jeu : on est ici précisément parce que l'enregistrement vient
                # de s'arrêter, et le worker tourne en `nice -19` dans un autre processus.
                with contextlib.suppress(Exception):
                    from . import store as _store, transcribe_jobs as _tj
                    if (_store.load_recorder_cfg() or {}).get("transcribe") == "auto":
                        # cur["file"] EST le dossier de la prise (relatif à ROOT) en multipiste,
                        # et un .wav plat en mode mix — qui n'a ni DI ni MIDI, donc rien à
                        # transcrire. On ne tente que sur un vrai dossier.
                        d = os.path.basename(cur["file"] or "")
                        if d.startswith("perf-") and os.path.isdir(os.path.join(C.ROOT, cur["file"])):
                            r = _tj.enqueue(d)
                            log_transcribe.info("auto %s -> %s" % (d, r))
            last = cur
            state.perf = cur
            state.touch(); await _broadcast()
        await asyncio.sleep(0.5)


# ── horodatage BWF (chunk « bext ») : caler une vidéo sur une prise sans rien mesurer ───────
# Reaper écrit déjà un chunk bext, mais son TimeReference vaut la position PROJET (= 0 chez nous).
# On y inscrit l'HEURE DU JOUR de début de prise (en échantillons depuis minuit) + la date/heure
# lisibles : Resolve / Premiere / Reaper calent alors la vidéo automatiquement.
# Coût : 8 octets réécrits dans l'en-tête APRÈS la prise — zéro impact sur l'audio temps réel.
_BEXT_TIMEREF = 256 + 32 + 32 + 10 + 8      # Description+Originator+Reference+Date+Time
_BEXT_DATE, _BEXT_TIME = 256 + 32 + 32, 256 + 32 + 32 + 10


def _riff_chunk(f, fourcc):
    """Offset des DONNÉES d'un chunk RIFF (parcours réel, pas une recherche d'octets) + sa taille."""
    f.seek(0)
    if f.read(4) != b"RIFF":
        return None, 0
    f.seek(12)
    while True:
        head = f.read(8)
        if len(head) < 8:
            return None, 0
        cid, size = head[:4], int.from_bytes(head[4:8], "little")
        if cid == fourcc:
            return f.tell(), size
        f.seek(size + (size & 1), 1)          # les chunks sont alignés sur 2 octets


def stamp_bwf(path, started_at, srate=48000):
    """Écrit l'heure de début (ISO « YYYY-MM-DDTHH:MM:SS ») dans le bext du WAV. True si posé."""
    try:
        d, t = started_at.split("T")[0], started_at.split("T")[1][:8]
        h, m, s = (int(x) for x in t.split(":"))
    except Exception:
        return False
    samples = (h * 3600 + m * 60 + s) * int(srate)
    try:
        with open(path, "r+b") as f:
            off, size = _riff_chunk(f, b"bext")
            if off is None or size < _BEXT_TIMEREF + 8:
                return False                   # pas de bext (ou tronqué) : on ne fabrique rien
            f.seek(off + _BEXT_DATE)
            f.write(d.encode("ascii")[:10].ljust(10, b" "))
            f.write(t.encode("ascii")[:8].ljust(8, b" "))
            f.seek(off + _BEXT_TIMEREF)
            f.write((samples & 0xFFFFFFFF).to_bytes(4, "little"))     # TimeReferenceLow
            f.write(((samples >> 32) & 0xFFFFFFFF).to_bytes(4, "little"))  # …High
        return True
    except Exception as e:
        log_take.warning(f"horodatage BWF impossible sur {os.path.basename(path)} : {e}")
        return False


def _active_guitar():
    try:
        from . import inharm
        return inharm.active_guitar()
    except Exception as _e:
        _swallowed(_e, "guitar")
        return None


def _write_take_manifest(cur):
    """recordings/perf-<ts>/take.json (multi) ou perf-<ts>.wav.json (mix) : timestamp, mode,
    sources cochées, preset/scène/bpm au moment du stop, fichiers. Base de l'envoi golem.fm
    (docs/private/exchanges/maestrium-exchange.md §3.4). Jamais fatal."""
    import time as _t
    try:
        _take_manifest(cur)
    except Exception as e:                    # jamais fatal — mais jamais MUET non plus
        log_perf.error(f"take.json NON écrit : {type(e).__name__}: {e}")


def _drums_ctx():
    """Ce qu'il faut pour RELIRE le .mid d'une prise : par port USB lié au rôle `drums`, le module tel
    que le rack l'a vu et le descripteur en service. Liste vide s'il n'y a pas de batterie MIDI."""
    try:
        from . import inputmap as _im
        return [{"slot": f"USB {u.get('port')}", "device": u.get("device"),
                 "descriptor": (u.get("kit") or {}).get("id"),
                 "descriptor_auto": bool((u.get("kit") or {}).get("auto")),
                 "fallback": bool((u.get("kit") or {}).get("fallback"))}
                for u in _im.usb_ports() if u.get("bound") and u.get("role") == "drums"]
    except Exception as _e:
        _swallowed(_e)
        return []


def _take_manifest(cur):
    import time as _t
    # ⚠ `_store` n'était importé que LOCALEMENT dans une autre fonction (celle de la transcription
    # auto) : ici il n'existait pas, et le rôle de l'entrée MIDI faisait tomber tout le manifeste
    # — « take.json NON écrit : NameError » à chaque prise du 2026-09-09 au 2026-09-21.
    from . import store as _store
    if True:
        target = os.path.join(C.ROOT, cur["file"])
        src = {}
        with contextlib.suppress(Exception):
            src = json.load(open(os.path.join(C.PRESETS_DIR, ".perfsrc.json")))
        from .store import load_preset
        preset = load_preset(state.preset_id) if state.preset_id else None
        man = {
            "kind": "take",
            "mode": src.get("mode") or "mix",
            "sources": {k: v for k, v in src.items() if k == "usb" or (k.startswith("in") and k[2:].isdigit())},   # lot 4 : in<N>
            "started_at": cur.get("started_at") or "",
            "ended_at": _t.strftime("%Y-%m-%dT%H:%M:%S"),
            "preset": state.preset_id, "preset_name": state.preset_name,
            "scene": state.scene_id,
            "bpm": (preset or {}).get("bpm"),
            "flags": list(PERF_FLAGS),
            # ce que la MACHINE a vu (roadmap 0.b) — `flags` reste ce qu'un HUMAIN a marqué.
            # Un consommateur qui veut la chronologie complète fusionne les deux sur `sec`.
            "marks": list(PERF_MARKS),
            # la répète à laquelle cette prise appartient : déduite de l'écart avec la prise
            # précédente (docs/private/repete-vers-demo.md §3 — une Session groupe des Takes).
            "session": _session_id(cur.get("started_at") or ""),
            # LE GROUPE, GELÉ ICI (roadmap 0.c, docs/identity.md). C'est le TAG QUI DÉCIDE DE LA
            # DESTINATION : une prise sans groupe ne monte pas, elle attend sur le rack. Le
            # groupe réglé sur le rack n'est qu'un DÉFAUT — la caisse se prête, et c'est la
            # PRISE qui porte le groupe, pas la machine. Gelé comme `roles` et `backing` :
            # changer le groupe du rack demain ne doit pas réattribuer les prises d'hier.
            # posé AU DÉPART (PERF_CTX), pas relu ici : entre-temps quelqu'un a pu changer le
            # groupe courant du rack pour la prise SUIVANTE.
            "band": PERF_CTX.get("band"),
            # RÔLE de chaque entrée AU MOMENT DE LA PRISE (patch de la carte) : c'est ce qui
            # permet d'afficher « Guitar DI » plutôt que « DI-Sandbox-Input-1 ». Figé ici et pas
            # relu à l'affichage, sinon rebrancher la guitare sur l'entrée 2 renommerait
            # rétroactivement toutes les prises passées.
            # ⚠ inclure AUSSI le rôle de l'entrée MIDI : la lane clavier est « Sandbox #Input 3 »
            # côté Reaper, mais son rôle vit dans patch.midi (pas dans patch.inputs, qui ne décrit
            # que les entrées AUDIO de la carte). Sans ça, sa capture s'appelait « Input 3 MIDI ».
            # ⚠ `state.inputmap`, PAS `state.patch` : cet attribut n'a jamais existé. Le
            # manifeste échouait donc en entier — et `contextlib.suppress` (« jamais fatal »)
            # l'avalait sans un mot. Aucune prise n'a eu de take.json entre le 2026-07-26 et le
            # 2026-08-02. Leçon : un filet qui protège une écriture NON critique doit quand même
            # DIRE ce qu'il a rattrapé, sinon il transforme une panne en absence.
            # LA GUITARE jouée (config/string-calib.json `active`, bridge/inharm.py) : la transcription lit son
            # accordage, ses cases et son étalonnage — une 8 cordes a sa tab à 8 lignes (2026-10-29)
            "guitar": _active_guitar(),
            "roles": {**{str(i.get("ch")): i.get("label") or i.get("role")
                         for i in ((state.inputmap or {}).get("inputs") or []) if i.get("ch")},
                      **({str(_store.midi_input_base(len((state.inputmap or {}).get("inputs") or []))): ((state.inputmap or {}).get("midi") or {}).get("label")
                                or ((state.inputmap or {}).get("midi") or {}).get("role")}
                         if ((state.inputmap or {}).get("midi") or {}).get("role") not in (None, "none")
                         else {})},
            # CONTEXTE de la prise (badge de la carte Recordings) : le mode machine dit OÙ elle a
            # été faite (compo à la maison, concert, répétition…). Donnée automatique, jamais saisie.
            # ⚠ l'ID seulement : state.mode est le DICT complet du mode. Y graver la définition
            # entière gonflerait chaque take.json et la figerait (un mode réédité rendrait le
            # manifeste menteur) — l'UI résout l'id via /api/modes, source unique de vérité.
            "machine_mode": (lambda m: (m or {}).get("id") if isinstance(m, dict) else m)(
                getattr(state, "mode", None)),
            # CE QUE LA PRISE EST pour golem.fm (décision 2026-09-08) : « show » (concert),
            # « gig » (répète en conditions) ou « rehearsal » (Pedalboard, Home, Rehearsal,
            # Accompaniment). Gelé au REC comme le groupe : golem.fm trie ses traitements dessus
            # (découpe, mastering, partage) sans que l'utilisateur ait à requalifier après coup.
            "kind": _modes.take_kind(getattr(state, "mode", None)),
            # chanson de backing jouée par-dessus, si elle l'a été (lien vers l'onglet Backings
            # et, à terme, vers golem.fm) — cf. PERF_CTX, observé pendant la prise.
            "backing": PERF_CTX.get("backing"),
            # par-dessus QUOI on a joué, suite : la grille de standard et les boucles du looper
            # (message-golem-enregistrements.md §2 et §3a). Absents = la prise n'en avait pas ;
            # golem.fm en dérive `source` (standard / looper) au lieu de tomber en `free`.
            "standard": PERF_CTX.get("standard"),
            "looper": PERF_CTX.get("looper"),
            # QUI jouait sur quelle entrée, gelé comme les rôles. Dict PARALLÈLE à `roles` et
            # non un objet dans `roles` : 89 prises portent déjà des libellés en CHAÎNES, que
            # `routes_content._labels` lit telles quelles — changer la forme les aurait rendues
            # illisibles pour un champ de confort. golem.fm accepte les deux (message du 09-05
            # §5) ; le rack garde celle qui ne casse rien.
            "people": {str(i.get("ch")): i["person"]
                       for i in ((state.inputmap or {}).get("inputs") or [])
                       if i.get("ch") and i.get("person")} or None,
            # ── UN .mid SANS SON ALPHABET NE SE RELIT PAS (docs/drums-kit.md lot 3, 2026-09-18) ──
            # Le MIDI capté est le flux BRUT du module : ses notes ne veulent dire « caisse claire »
            # ou « charleston » qu'à travers le DESCRIPTEUR en service ce jour-là (config/drumkits/).
            # Un module se remplace, un descripteur se corrige : sans cette ligne, la prise d'hier se
            # relirait avec la table d'aujourd'hui. On grave l'ID du descripteur et le nom du module,
            # jamais la table — elle est versionnée, et la recopier la figerait.
            "drums": _drums_ctx() or None,
            "files": [],
        }
        if os.path.isdir(target):
            man["files"] = sorted(f for f in os.listdir(target)
                                  if f.lower().endswith((".wav", ".mid")))   # .mid = captures MIDI
            out = os.path.join(target, "take.json")
            # ⚠ .wav SEULEMENT : stamp_bwf réécrit un chunk d'en-tête RIFF — l'appliquer à un
            # .mid corromprait le fichier MIDI (en-tête MThd, rien à voir avec RIFF).
            wavs = [os.path.join(target, f) for f in man["files"] if f.lower().endswith(".wav")]
        elif os.path.isfile(target):
            man["files"] = [os.path.basename(target)]
            out = target + ".json"
            wavs = [target]
        else:
            return
        # horodatage BWF de chaque fichier de la prise (multipiste : toutes les pistes partagent
        # la même heure de début, donc restent alignées entre elles ET avec la vidéo)
        sr = int((state.audio or {}).get("srate") or 48000) if hasattr(state, "audio") else 48000
        man["bwf_timestamp"] = bool(man["started_at"]) and all(
            stamp_bwf(w, man["started_at"], sr) for w in wavs)
        # ── L'HORLOGE MURALE (message-golem-modes-espaces.md §1.5) ──────────────────────────
        # `started_at` est une ISO NAÏVE : l'heure de la salle, sans décalage. On ne la touche
        # pas — c'est elle qu'on affiche, et la convertir serait mentir sur ce qui a été lu à
        # l'horloge du mur. On AJOUTE à côté un instant absolu, pour que golem.fm puisse poser
        # une vidéo de téléphone sur sa timeline sans qu'on cale quoi que ce soit à la main.
        with contextlib.suppress(Exception):
            epoch = _t.mktime(_t.strptime(man["started_at"], "%Y-%m-%dT%H:%M:%S"))
            man["started_epoch_ms"] = int(epoch * 1000)
            man["started_at_utc"] = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(epoch))
        # ⚠ APRÈS `stamp_bwf`, jamais avant : c'est lui qui écrit le chunk `bext` qu'on relit.
        # `time_reference` est l'horodatage d'ÉCHANTILLON — l'ancre qui aligne les lanes entre
        # elles ; mesuré identique sur les 9 lanes d'une prise, et il survit au FLAC monté.
        if wavs:
            from . import takes as _takes
            info = _takes.wav_info(wavs[0])
            if info.get("time_reference") is not None:
                man["bwf_time_reference"] = info["time_reference"]
            man["sample_rate"] = info.get("sample_rate") or sr
        # UNE CAPTURE DE RIFF (docs/compo.md §11) : le même dossier, déclaré riff — auteur, cible, SES lanes,
        # fenêtre de drop. Seul un vrai dossier (multipiste) déclare des lanes ; la capture l'a exigé au départ.
        riff = None
        if os.path.isdir(target):
            from . import compo as _compo
            riff = _compo.claim_riff()
            if riff:
                _compo.stamp_manifest(man, riff)
        # LE STANDARD JOUÉ PENDANT LA PRISE (lot 3 des partitions, 2026-10-17) : on garde la séquence que le moteur
        # a jouée — la prochaine grille l'écraserait. Ses parties s'écrivent ensuite en partitions EXACTES.
        if os.path.isdir(target) and (man.get("standard") or {}).get("played"):
            with contextlib.suppress(OSError):
                import shutil as _sh
                _sh.copyfile(os.path.join(C.PRESETS_DIR, ".standard.seq"), os.path.join(target, "standard.seq"))
                man["standard"] = {**man["standard"], "seq": "standard.seq"}
        json.dump(man, open(out, "w"), indent=1, ensure_ascii=False)
        if riff:
            _compo.after_written(os.path.basename(target), riff)


# ── drums : golem_drums.lua écrit presets/.drums.json, le bridge réconcilie l'état des grooves ──
_drums_ctl = None


def init_drums(ctl):
    global _drums_ctl
    _drums_ctl = ctl


async def _poll_drums():
    """Suit .drums.json quand des boîtes à rythmes sont montées : réconcilie l'état optimiste
    (stop naturel / changement de partie côté Lua) et pousse state.drums -> WS."""
    loop = asyncio.get_running_loop()
    last = None
    while True:
        if not state.drum_switches:
            if last is not None:
                last = None
                state.drums = {}
                state.touch(); await _broadcast()
            await asyncio.sleep(0.4)
            continue
        def _read():
            try:
                return json.load(open(C.DRUMS_FILE))
            except Exception:
                return None
        data = await loop.run_in_executor(None, _read)
        blocks = (data or {}).get("blocks") or {}
        if _drums_ctl:
            _drums_ctl.apply_feedback(blocks, authoritative=bool((data or {}).get("present")))
        sig = json.dumps(blocks, sort_keys=True)
        if sig != last:
            last = sig
            state.drums = _drums_ctl.snapshot() if _drums_ctl else {}
            state.touch(); await _broadcast()
        await asyncio.sleep(0.15)


# ── standard : golem_chordseq.lua écrit presets/.standard.json — le JSFX FAIT FOI ──────────
# Le contrôleur de pied est optimiste (le tap bascule tout de suite, pour que la LED réponde) ;
# ce poll rattrape ce que le Lua sait et que le bridge ignore : fin de grille en mode « once »,
# arrêt déclenché depuis l'écran, ou lecteur mort après un rechargement de Reaper. Sans lui, un
# tap au pied démarrerait une grille déjà arrêtée — ou l'inverse.
_std_ctl = None


def init_standard(ctl):
    global _std_ctl
    _std_ctl = ctl


async def _poll_standard():
    loop = asyncio.get_running_loop()
    path = os.path.join(C.PRESETS_DIR, ".standard.json")
    last = None
    while True:
        if not state.standard_switches:
            if last is not None:
                last = None
                state.standard = {}
                state.touch(); await _broadcast()
            await asyncio.sleep(0.5)
            continue

        def _read():
            try:
                with open(path) as f:
                    return json.load(f)
            except (OSError, ValueError):
                return None
        data = await loop.run_in_executor(None, _read)
        playing = bool((data or {}).get("playing"))
        if _std_ctl:
            _std_ctl.apply_feedback(playing)
        sig = (playing, (data or {}).get("standard"), (data or {}).get("bar"))
        if sig != last:
            last = sig
            state.standard = {"playing": playing, "standard": (data or {}).get("standard"),
                              "bar": (data or {}).get("bar", -1), "bars": (data or {}).get("bars", 0)}
            state.touch(); await _broadcast()
        await asyncio.sleep(0.2)


# ── looper : golem_looper.lua écrit presets/.looper.json (états gmem), le bridge le suit ──
_looper_ctl = None       # LooperControl, injecté par app.py (reçoit l'adresse OSC + le feedback)


def init_looper(ctl):
    global _looper_ctl
    _looper_ctl = ctl


def _read_looper_file():
    try:
        with open(C.LOOPER_FILE) as f:
            d = json.load(f)
        d["_mtime"] = os.path.getmtime(C.LOOPER_FILE)       # l'adresse ne vaut que publiée après le dernier rappel
        return d
    except Exception:
        return None


async def _poll_looper():
    """Suit .looper.json à ~20 Hz quand le preset a un looper (idle 0.3 s sinon). Pousse l'adresse
    de commande (track/fx/param) et le feedback dans LooperControl, et l'état symbolique dans
    state.looper -> WS. La position (pos/len) est extrapolée côté client entre deux frames."""
    loop = asyncio.get_running_loop()
    last_sig = None
    while True:
        if not state.looper.get("enabled"):
            if last_sig is not None:      # préset sans looper : on fige un état neutre une fois
                last_sig = None
                state.looper = {**state.looper, "present": False, "slots": [], "len": 0.0, "pos": 0.0}
                state.touch(); await _broadcast()
            await asyncio.sleep(0.3)
            continue
        data = await loop.run_in_executor(None, _read_looper_file)
        if data and data.get("present"):
            if _looper_ctl:
                _looper_ctl.set_addr({"track": data.get("track"), "fx": data.get("fx"),
                                      "cmd_param": data.get("cmd_param")}, data.get("_mtime"))
                _looper_ctl.set_feedback(data.get("slots") or [], data.get("firstrec") or 0)
            # Autant de slots que la TABLE du preset en déclare (docs/looper.md §1) — plus « 3 »
            # en dur : un preset peut n'avoir que deux boucles, ou quatre. L'index d'un slot EST
            # la ligne de la table, donc la paire stéréo du JSFX.
            rows = _looper_ctl.loops() if _looper_ctl else []
            raws = data.get("slots") or []
            slots = []
            for i, row in enumerate(rows):
                st = _looper_ctl.slot_state(i) if _looper_ctl else "empty"
                raw = raws[i] if i < len(raws) else {}
                # MASTER = la paire qui a fixé la longueur (firstrec, canal 1-based) ; PEAK = la crête de la boucle
                # qui joue — deux faits que golem_looper publiait et que /live n'affichait pas (2026-10-13,
                # mockups/live-looper.html)
                fr = int(data.get("firstrec") or 0)
                slots.append({"state": st, "has": bool(raw.get("has")),
                              "sw": row.get("sw"), "src": row.get("src"),
                              "label": row.get("label") or "",
                              "master": bool(fr) and (fr - 1) // 2 == i,
                              "peak": round(float(raw.get("peak") or 0), 2)})
            # ⚠ le LIBELLÉ est dans la signature : sans lui, renommer une boucle dans le Designer
            # ne rafraîchissait pas /live (le moniteur ne republie que sur changement de signature)
            # et la tuile gardait l'ancien nom jusqu'au prochain coup de pied.
            sig = (True, tuple((s["state"], s["has"], s["sw"], s["label"], s["master"], round(s["peak"], 1)) for s in slots),
                   round(data.get("len") or 0, 2), round(data.get("pos") or 0, 1),
                   int(data.get("countin") or 0), int(data.get("countin_slot") or 0))
            if sig != last_sig:
                last_sig = sig
                ci = int(data.get("countin") or 0)
                state.looper = {**state.looper, "present": True, "slots": slots,
                                "len": data.get("len") or 0.0, "pos": data.get("pos") or 0.0,
                                # le décompte de la 1re boucle (docs/looper.md) : la paire (= slot) et les temps restants
                                "countin": {"slot": int(data.get("countin_slot") or 0) - 1, "beats": ci} if ci > 0 else None,
                                "t": time.time()}
                state.touch(); await _broadcast()
        else:
            if _looper_ctl:
                _looper_ctl.set_addr(None)
            sig = (False,)
            if sig != last_sig:
                last_sig = sig
                state.looper = {**state.looper, "present": False, "slots": [], "len": 0.0, "pos": 0.0}
                state.touch(); await _broadcast()
        await asyncio.sleep(0.05)


# ── backing : golem_backing.lua écrit presets/.backing.json (transport/position) ──
_backing_ctl = None      # BackingControl, injecté par app.py (reçoit le feedback transport)


def init_backing(ctl):
    global _backing_ctl
    _backing_ctl = ctl


def _read_backing_file():
    """+ `_at` = l'heure où Reaper a ÉCRIT le fichier (mtime : golem_backing écrit un tmp puis le renomme,
    juste après avoir lu la position). C'est ce qui fait de `pos` une HORLOGE : « à tel instant, le
    transport était là » — l'arrangement s'y cale (docs/arrangement.md §5). L'heure de NOTRE lecture
    ajouterait jusqu'à un tour de poll (0,1 s) d'erreur."""
    try:
        at = os.stat(C.BACKING_FILE).st_mtime
        d = json.load(open(C.BACKING_FILE))
        if isinstance(d, dict):
            d["_at"] = at
        return d
    except Exception:
        return None


async def _poll_backing():
    """Suit .backing.json à ~10 Hz quand le preset lie des chansons (idle 0.3 s sinon).
    Pousse le feedback dans BackingControl et l'état dans state.backing -> WS ; la
    position est extrapolée côté client entre deux frames (pattern LoopProgress)."""
    loop = asyncio.get_running_loop()
    last_sig = None
    while True:
        # ⚠ UNE PRISE ARMÉE (docs/compo.md §12) charge son click dans le backing MÊME si le preset n'en a pas :
        # sans ce garde, on ne lisait pas .backing.json — Reaper avait chargé « riff-take » et le bridge,
        # qui ne regardait pas, abandonnait au bout de 8 s (test réel du 2026-09-30, preset le groupe)
        riff_needs = False
        with contextlib.suppress(Exception):
            from . import compo as _compo
            riff_needs = _compo.backing_needed()
        if not state.backing.get("enabled") and not riff_needs:
            if last_sig is not None:      # preset sans backing : fige un état neutre une fois
                last_sig = None
                state.backing = {**state.backing, "present": False, "slug": None,
                                 "playing": False, "paused": False, "pos": 0.0, "len": 0.0}
                state.touch(); await _broadcast()
            await asyncio.sleep(0.3)
            continue
        data = await loop.run_in_executor(None, _read_backing_file)
        with contextlib.suppress(Exception):          # la FIN d'un karaoké (docs/karaoke.md §2.3)
            from . import karaoke as _karaoke
            _karaoke.on_backing(data)
        extra = _backing_ctl.snapshot_extra() if _backing_ctl else {"songs": [], "slug": None}
        if data and data.get("present"):
            if _backing_ctl:
                _backing_ctl.set_feedback({"present": True, "playing": bool(data.get("playing")),
                                           "paused": bool(data.get("paused")),
                                           "pos": data.get("pos") or 0.0, "len": data.get("len") or 0.0,
                                           "slug": data.get("slug"), "at": data.get("_at")})
            playing = _backing_ctl.playing() if _backing_ctl else bool(data.get("playing"))
            sig = (True, data.get("slug"), playing, bool(data.get("paused")),
                   round(data.get("pos") or 0, 1), round(data.get("len") or 0, 1),
                   json.dumps(data.get("stems") or {}, sort_keys=True),
                   json.dumps(data.get("loop") or {}, sort_keys=True), len(extra["songs"]),
                   int(data.get("songclick") or 0))
            if sig != last_sig:
                last_sig = sig
                state.backing = {**state.backing, "present": True, "slug": data.get("slug"),
                                 "songs": extra["songs"], "playing": playing,
                                 "paused": bool(data.get("paused")),
                                 "pos": data.get("pos") or 0.0, "len": data.get("len") or 0.0,
                                 "stems": data.get("stems") or {},
                                 "loop": data.get("loop") or {"on": False, "a": 0.0, "b": 0.0},
                                 # temps du click du morceau RÉELLEMENT posés sur la piste Click (docs/bars-format.md)
                                 "songclick": int(data.get("songclick") or 0),
                                 "t": time.time()}
                state.touch(); await _broadcast()
        else:
            if _backing_ctl:
                _backing_ctl.set_feedback({"present": False, "playing": False, "paused": False,
                                           "pos": 0.0, "len": 0.0, "slug": None})
            sig = (False, len(extra["songs"]))
            if sig != last_sig:
                last_sig = sig
                state.backing = {**state.backing, "present": False, "slug": None, "songs": extra["songs"],
                                 "playing": False, "paused": False, "pos": 0.0, "len": 0.0, "stems": {}}
                state.touch(); await _broadcast()
        await asyncio.sleep(0.1)
