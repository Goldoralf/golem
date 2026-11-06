# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes système (dashboard /api/system + perf-mode + buffer audio Reaper) — extrait d'app.py (P3)."""
import os, re, json, shutil, signal, subprocess, threading, time, asyncio, contextlib, sys

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse

from . import config as C
from . import backup as _backup
from . import serial as _serial
from . import reaper_license
from .golog import get

log = get("system")

log_audio = get("audio")
log_cards = get("cards")
from .state import state
from .store import load_presets, _read_json
from . import store
from .golog import swallowed as _swallowed

router = APIRouter()

# ── buffer audio Reaper (linux_audio_bsize de reaper.ini) ────────────────────
REAPER_INI = os.path.expanduser("~/.config/REAPER/reaper.ini")
AUDIO_BSIZES = [64, 96, 128, 192, 256, 384, 512]


def _ini_set(text, key, value):
    """`key=value` dans la section [reaper] de reaper.ini : remplacée si elle existe, AJOUTÉE sinon.
    Une install neuve n'a ni linux_audio_bsize ni (avant reaper-ini-setup) alsa_indev/outdev : REAPER n'écrit une clé
    que si elle diffère de son défaut. Refuser « missing from reaper.ini » bloquait le buffer de Settings sur tout
    golem neuf (2026-11-03, portable Ubuntu 26.04)."""
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=", text, re.M):
        return re.sub(rf"^{re.escape(key)}=.*$", lambda _m: line, text, count=1, flags=re.M)
    if re.search(r"^\[reaper\]\s*$", text, re.M):
        return re.sub(r"^\[reaper\]\s*$", lambda m: m.group(0) + "\n" + line, text, count=1, flags=re.M)
    return "[reaper]\n" + line + "\n" + text


def _read_bsize():
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        actual = desktop_audio._public_actual() or {}
        try:
            return int(actual.get("BSIZE") or desktop_audio.settings()["buffer_size"])
        except (OSError, ValueError, TypeError):
            return None
    try:
        m = re.search(r"^linux_audio_bsize=(\d+)", open(REAPER_INI).read(), re.M)
        return int(m.group(1)) if m else None
    except Exception:
        return None



RESTART_LOG = "/tmp/golem-reaper-restart.log"


def _rack_reaper_pids():
    """Les PID du REAPER DE CE RACK : un processus « reaper » qui n'est ni un zombie ni le REAPER d'un banc (les bancs
    check-rig-materialize / shell_snapshot lancent le leur avec -cfgfile) — même règle que provision/start.sh. Avant
    (2026-11-06), `pgrep -x reaper` voyait le zombie d'un banc : le redémarrage attendait une mort qui ne venait pas,
    start.sh croyait REAPER ouvert et ne le relançait pas ; et `pkill -x reaper` tuait aussi le REAPER du banc."""
    try:
        out = subprocess.run(["pgrep", "-x", "reaper"], capture_output=True, text=True, timeout=3).stdout.split()
    except Exception as _e:
        _swallowed(_e)
        return []
    pids = []
    for p in out:
        try:
            with open(f"/proc/{p}/stat") as f:
                if f.read().rsplit(")", 1)[-1].split()[0] == "Z":
                    continue
            with open(f"/proc/{p}/cmdline", "rb") as f:
                if b"-cfgfile" in f.read().split(b"\0"):
                    continue
        except OSError:
            continue
        pids.append(int(p))
    return pids


def _wait_reaper_dead(timeout=12.0):
    """Attend la mort RÉELLE du process après le SIGTERM (asynchrone : Reaper sauve d'abord sa config et peut mettre
    >2 s). True si mort, False si toujours là au timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _rack_reaper_pids():
            return True
        time.sleep(0.3)
    return False


def _restart_reaper_async(after_dead=None, why="requested"):
    """Redémarre Reaper (le Set + golem_watch repartent via __startup ; le bridge reste up).
    En thread : la requête HTTP rend la main tout de suite, l'UI suit reaper_running/latency_ms.
    On ATTEND la mort réelle du process avant de relancer, pour deux raisons vécues :
      1. Reaper RÉÉCRIT reaper.ini en quittant -> toute édition de l'ini doit se faire APRÈS
         sa mort (callback after_dead), sinon il écrase le changement (bug buffer resté à 128) ;
      2. start.sh no-op si pgrep voit encore l'ancien process -> Reaper ne repartait pas du
         tout (carte ALSA fermée, latence disparue du dashboard)."""
    def run():
        # lot 8 : l'INTENTION avant le pkill — sinon la chronologie montre un abort (golem.fm, 2026-09-14)
        with __import__("contextlib").suppress(Exception):
            from . import diag
            diag.intent("reaper", why)
        # Reaper repart -> le rig matérialisé n'est plus garanti : on invalide le cache de forme
        # (recall._LAST_EMIT) pour que la prochaine émission fasse un REBUILD (jamais un
        # scene_apply sur un projet fraîchement rechargé).
        with __import__("contextlib").suppress(Exception):
            from . import recall
            recall.invalidate_shape()
        for pid in _rack_reaper_pids():                    # le REAPER de CE rack seulement, jamais celui d'un banc
            with __import__("contextlib").suppress(OSError):
                os.kill(pid, signal.SIGTERM)
        dead = _wait_reaper_dead()
        if after_dead:
            after_dead()
        # la sortie de start.sh dans un JOURNAL (2026-11-06) : jetée, un REAPER qui ne repartait pas ne disait pas pourquoi
        logf = open(RESTART_LOG, "a")
        logf.write(time.strftime("\n── %Y-%m-%d %H:%M:%S ") + f"restart ({why}) — reaper mort : {dead}\n")
        logf.flush()
        subprocess.Popen(["bash", os.path.join(C.ROOT, "provision", "start.sh")],
                         start_new_session=True, stdout=logf, stderr=subprocess.STDOUT)
    threading.Thread(target=run, daemon=True).start()


def _cpu_governor():
    if sys.platform == "win32":                          # le plan d'alimentation (bridge/desktop_power.py)
        from . import desktop_power
        return desktop_power.governor()
    return _read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")


def _read_text(path):
    try:
        return open(path).read().strip()
    except Exception:
        return None


def _git(*args):
    try:
        return subprocess.run(["git", "-C", C.ROOT, *args], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception as e:
        return f"(git indisponible: {e})"


# L'ÉTAT DE LA MACHINE n'est pas un changement de code (CLAUDE.md, règle 2) : Reaper réécrit sets/, le
# musicien presets/ et ses mappings, la page Soundcard config/inputmaps/. « local changes » les comptait
# — un rack qui tourne n'était donc JAMAIS « clean », et le bouton de release restait grisé pour un
# fichier que personne n'a édité à la main (vu sur le PC de le 2026-10-03 : 1 modifié, 4 non suivis,
# tous dans config/). Ne comptent que les fichiers SUIVIS hors de ces dossiers ; un état suivi modifié
# qu'une release toucherait fait échouer `git checkout`, qui le dit.
STATE_PATHS = ("config/", "presets/", "sets/", "mappings/", "setlists/")


def _code_changes():
    try:
        out = subprocess.run(["git", "-C", C.ROOT, "status", "--porcelain", "--untracked-files=no"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    paths = [ln[3:].split(" -> ")[-1].strip('"') for ln in out.splitlines() if len(ln) > 3]
    return [p for p in paths if not p.startswith(STATE_PATHS)]


@router.get("/api/reamp")
def reamp_status():
    """La file des reamps (docs/reamp.md §3) : ce qui attend, et POURQUOI le rack n'est pas libre."""
    from . import reamp, activity
    return {**reamp.status(), "activity": activity.last()}


@router.post("/api/reamp/try")
def reamp_try(body: dict):
    """BANC du reamp (tools/check-reamp-align.py) : rend une DI locale à travers une lane, SANS rien
    monter. Prend le moteur comme le vrai job et le remet après ; refuse ce que le job refuse — sauf
    la clause d'inactivité (c'est quelqu'un devant le rack qui le lance)."""
    from . import reamp
    from .store import load_preset, lanes_of
    why = reamp.busy_reason()
    if why and not why.startswith("in use"):
        return JSONResponse({"error": why}, status_code=409)
    pid, di = body.get("preset") or state.preset_id, body.get("di")
    preset = load_preset(pid) if pid else None
    if not preset or not di or not os.path.isfile(di):
        return JSONResponse({"error": "preset and an existing di path are required"}, status_code=400)
    scene = body.get("scene") or ((preset.get("scenes") or [{}])[0].get("id"))
    lane, err = reamp.pick_lane(lanes_of(preset), body.get("lane"), body.get("role"))
    err = err or reamp.check_lane(lane)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    out = body.get("out") or os.path.join(reamp.CACHE, "try", os.path.basename(di).rsplit(".", 1)[0] + ".try.wav")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        wav = reamp.render(pid, scene, lane, di, out, key=f"reamp-try-{int(time.time())}")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    sr, frames, ch = reamp.wav_info(wav)
    return {"ok": True, "wav": wav, "preset": pid, "scene": scene, "lane": lane["id"],
            "sample_rate": sr, "frames": frames, "channels": ch}


@router.get("/api/system")
def system():
    from . import desktop_audio
    desktop = sys.platform in ("win32", "darwin")
    actual = desktop_audio._public_actual() if desktop else None
    return {
        "platform": sys.platform,
        "reaper_connected": state.reaper_connected,
        "reaper_running": state.reaper_running,
        "bridge": "ok",
        "cpu_governor": _cpu_governor(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_clean": not _code_changes(),
        "presets": len(load_presets()),
        "tones": len((_read_json(C.CATALOG, {}) or {}).get("tones", [])),
        "audio_bsize": _read_bsize(),
        # sous Windows, ce que le PILOTE ASIO accepte (desktop_audio.buffer_choices) : le reste se grise
        **_bsize_choices(desktop),
        "audio_srate": int(actual["SRATE"]) if actual and str(actual.get("SRATE", "")).isdigit() else None,
        "audio_latency_ms": desktop_audio.latency_ms(actual)[0] if desktop else None,
        "audio_latency_source": desktop_audio.latency_ms(actual)[1] if desktop else None,
        # le pilote garde la main sur le buffer (sa latence ne suit pas la taille demandée) : à dire, avec le geste
        "audio_driver_override": desktop_audio.driver_override(actual) if desktop else None,
        "serial": _serial.plate(),                       # le numéro à vie (docs/connect.md §4.5)
    }


@router.post("/api/system/serial/recover")
def system_serial_recover():
    """Relire son numéro à vie chez golem.fm (fichier perdu, vérification). Jamais une réécriture : un
    numéro différent de celui gardé est une anomalie, montrée sur la plaque."""
    r = _serial.fetch()
    return {**r, "plate": _serial.plate()}


def _reaper_license_path():
    """La licence vit dans le dossier de ressources de REAPER — celui qu'il LIT : ~/.config/REAPER sous
    Linux, mais %APPDATA%\\REAPER (Windows) ou ~/Library/Application Support/REAPER (macOS). Calculé à
    l'appel (bridge/reaper_license.py, partagé avec l'installateur) : un chemin figé à l'import poserait la clé
    là où REAPER ne regarde jamais."""
    return reaper_license.path(C.reaper_resource_dir())


@router.get("/api/system/reaper-license")
def reaper_license_status():
    """Présence d'une licence Reaper posée — JAMAIS son contenu (secret).

    `state` (Windows, 2026-10-03) : ce que REAPER AFFICHE — « registered » ou « evaluation » — lu dans le
    titre de sa fenêtre. Un fichier présent ne dit pas qu'il est ACCEPTÉ : REAPER 7.79 a refusé une clé que
    7.27 acceptait, et la carte affichait « ✓ installed » pendant que le moteur tournait en évaluation."""
    out = {"present": os.path.isfile(_reaper_license_path())}
    if sys.platform == "win32":
        from . import desktop_reaper
        out["state"] = desktop_reaper.license_state()
    return out


@router.post("/api/system/reaper-license")
async def reaper_license_set(body: dict):
    """Écrit la licence dans <resource>/reaper-license.rk : Reaper l'importe au prochain
    démarrage (fin du nag d'éval). Le contenu est un SECRET — hors repo (dossier de ressources de
    REAPER), jamais renvoyé ni logué. Nécessite un restart du moteur pour prendre effet.
    L'écriture est celle de l'installateur (écran 3) : bridge/reaper_license.write."""
    # reçu d'install (docs/uninstall.md §2) : y avait-il une licence AVANT golem ? (jamais son contenu)
    from . import install_receipt
    try:
        reaper_license.write(body.get("license"), os.path.dirname(_reaper_license_path()), prior=install_receipt.prior)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    # l'écran de chargement relit la présence (ligne REAPER) sans attendre sa vérification périodique
    from . import boot_progress
    boot_progress.refresh_reaper_license()
    return {"ok": True, "restart_needed": True}


def _bsize_choices(desktop):
    from . import desktop_audio
    if not desktop:
        return {"audio_bsizes": AUDIO_BSIZES, "audio_bsizes_ok": None, "audio_driver": None}
    try:
        shown, allowed = desktop_audio.buffer_choices()
        driver = desktop_audio.settings().get("driver") if sys.platform == "win32" else None
    except (OSError, ValueError, KeyError):
        shown, allowed, driver = list(desktop_audio.BUFFER_SIZES), None, None
    return {"audio_bsizes": shown, "audio_bsizes_ok": allowed, "audio_driver": driver}


@router.post("/api/audio-buffer")
async def audio_buffer(body: dict):
    """Change le buffer audio de Reaper (linux_audio_bsize) et REDÉMARRE le moteur (~10 s).
    reaper.ini n'est relu qu'au démarrage ET RÉÉCRIT par Reaper quand il quitte -> l'édition
    doit se faire APRÈS la mort du process (after_dead), sinon Reaper écrase le changement en
    sauvant sa config à la sortie. L'UI suit la relance sur reaper_running puis lit latency_ms
    (mesurée sur les hw_params ALSA réels) et surveille les xruns."""
    size = body.get("size")
    from . import desktop_audio, monitors
    sizes = (await asyncio.to_thread(desktop_audio.buffer_choices))[0] if sys.platform in ("win32", "darwin") else AUDIO_BSIZES
    if type(size) is not int or size not in sizes:
        return JSONResponse({"error": f"size must be one of {sizes}"}, status_code=400)
    if sys.platform in ("win32", "darwin"):
        try:
            current = await asyncio.to_thread(desktop_audio.settings)
            request = {key: current[key] for key in ("sample_rate", "sample_rate_use", "buffer_size",
                                                      "buffer_size_use")}
            request.update(buffer_size=size, buffer_size_use=True)
            if sys.platform == "win32":
                request.update({key: current[key] for key in ("driver", "input_first", "input_last",
                                                                "output_first", "output_last")})
            else:
                request.update({key: current[key] for key in ("input_device", "output_device")})
            apply = await asyncio.to_thread(desktop_audio.start_apply, request)
            monitors.xruns_clear()                            # les xruns d'avant jugeaient l'ancien buffer
            return {"ok": True, "size": size, "restarting": True, "apply": apply}
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except (OSError, RuntimeError) as e:
            return JSONResponse({"error": str(e)}, status_code=409)
    try:                                                      # validations AVANT de tuer Reaper
        open(REAPER_INI).read()                               # lisible ? (absente : la clé est AJOUTÉE à l'écriture)
        if not os.path.exists(REAPER_INI + ".golem.bak"):     # filet : sauvegarde une fois
            shutil.copy2(REAPER_INI, REAPER_INI + ".golem.bak")
    except Exception as e:
        return JSONResponse({"error": f"reaper.ini : {e}"}, status_code=500)
    from . import install_receipt                             # reçu : la valeur d'avant golem (le premier gagne)
    install_receipt.prior("reaper_ini.keys.linux_audio_bsize", install_receipt.ini_value(REAPER_INI, "linux_audio_bsize"))

    def write_ini():   # exécuté par le thread de restart, une fois Reaper réellement mort
        try:
            cur = open(REAPER_INI).read()
            # tmp + replace : réécrire l'ini de Reaper EN PLACE laissait un fichier tronqué
            # possible sur coupure — le pire candidat du dépôt (audit 2026-08-12)
            tmp = REAPER_INI + ".golem.tmp"
            open(tmp, "w").write(_ini_set(cur, "linux_audio_bsize", size))
            os.replace(tmp, REAPER_INI)
        except Exception as e:
            # Reaper repart avec l'ancien buffer ; l'UI retombe sur ses pieds au timeout —
            # mais un échec AVALÉ a déjà fait chercher le bug ailleurs : on le dit.
            log_audio.error(f"⚠ reaper.ini non réécrit ({e}) — buffer inchangé")

    _restart_reaper_async(after_dead=write_ini, why="settings")
    monitors.xruns_clear()                                    # les xruns d'avant jugeaient l'ancien buffer
    return {"ok": True, "size": size, "restarting": True,
            "theoretical_ms": round(2 * size / 48000 * 1000, 1)}


# ── moteur audio (Settings ▸ Engines ▸ Audio) — COQUILLE, docs/audio-engine-choice.md ────────────
# Les deux routes de la page. Elles disent ce qui est choisi et ce qui serait possible ; aucune
# ne bascule de moteur (lot E3). Le choix est un fichier LOCAL (config/engine.json, gitignoré).

@router.get("/api/engines")
def engines_list():
    """Les moteurs connus (descripteurs config/engines/), le moteur choisi, et les fonctions."""
    from . import engines
    return {"current": engines.current(), "platform": sys.platform,
            "features": [{"id": i, "label": l} for i, l in engines.features()],
            "engines": engines.descriptors()}


@router.post("/api/engine")
async def engine_select(body: dict):
    """Choisir le moteur. Aujourd'hui seul le moteur courant est sélectionnable : la route valide
    et répond, elle ne bascule rien. Un moteur indisponible est refusé avec sa raison (409)."""
    from . import engines
    eid = str(body.get("id") or "")
    cur = engines.current()
    try:
        engines.write_choice(eid, set_by="app")
    except ValueError as e:
        return JSONResponse({"error": str(e), "current": cur}, status_code=409)
    # eid != cur ne peut pas arriver tant qu'un seul moteur est disponible ; le jour où ce sera
    # possible, la bascule (lot E3) se branche ICI — l'écran lit `switch_pending`.
    return {"ok": True, "current": eid, "switch_pending": eid != cur}


@router.post("/api/system/xruns-clear")
async def xruns_clear():
    """Acquitte les dropouts audio (bouton de la tuile) : l'écran repasse au vert, le cumul du
    diagnostic reste. Sans ce geste, la tuile se rallume verte seule après monitors.XRUN_RECENT_S."""
    from . import monitors
    from .app import _broadcast
    monitors.xruns_clear()
    await _broadcast()
    return {"ok": True}


# ── registre de cartes + adoption (docs/gear-registry.md É1-É3, 2026-07-26) ──────────────

@router.get("/api/cards")
def cards_list():
    """Cartes USB connectées + registre. `candidate` = connectée, non active, non ignorée —
    la bannière « switch » de la page Soundcard s'appuie dessus."""
    from . import cards as cards_mod
    if sys.platform == "win32":
        from . import desktop_audio
        active = desktop_audio.settings()["driver"]
    elif sys.platform == "darwin":
        active = cards_mod.mac_opened_input() or ""
    else:
        dev = (_read_json(os.path.join(C.CONFIG_DIR, "io.json"), {}) or {}).get("device", "")
        active = dev.split(":", 1)[1] if ":" in dev else dev
    conn = cards_mod.connected()
    reg = {d["id"]: d for d in cards_mod.registry()}
    for c in conn:
        c["known"] = c["id"] in reg
        c["ignored"] = bool(reg.get(c["id"], {}).get("ignored"))
        c["active"] = c["id"] == active
        c["candidate"] = not c["active"] and not c["ignored"]
    # ── É3 : une carte CONNUE mais absente existe pour l'utilisateur ────────────────────────
    # Elle est au registre (déclarée à la main, ou vue un jour), son patch d'entrées l'attend
    # peut-être déjà — et rien à l'écran ne le disait : on ne voyait que les cartes BRANCHÉES.
    # Préparer une 8×8 avant qu'elle arrive était donc un travail invisible (docs/gear-registry §É3).
    here = {c["id"] for c in conn}
    for d in reg.values():
        d["connected"] = d["id"] in here
        d["active"] = d["id"] == active
        from . import inputmap
        d["prepared"] = os.path.exists(os.path.join(C.CONFIG_DIR, "inputmaps",
                                                   inputmap._slug(inputmap.device_of(d["id"])) + ".json"))
    return {"active": active, "connected": conn, "registry": list(reg.values())}


@router.post("/api/cards/declare")
async def cards_declare(body: dict):
    """Déclare une carte À LA MAIN (jamais branchée) : {id, name, inputs, outputs}. Elle entre au
    registre, un mode peut la déclarer et nommer ses entrées (patch semé depuis ce descripteur)."""
    from . import cards as cards_mod
    try:
        d = cards_mod.declare((body or {}).get("id"), (body or {}).get("name"), (body or {}).get("inputs"), (body or {}).get("outputs"))
    except (ValueError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "card": d}


@router.post("/api/cards/ignore")
async def cards_ignore(body: dict):
    """Marque une carte « jamais proposée » (ex. l'audio du dock USB) — descriptor conservé."""
    from . import cards as cards_mod
    d = cards_mod.remember(body.get("id") or "")
    if d is None:
        return JSONResponse({"error": "card not connected"}, status_code=404)
    d["ignored"] = True
    store._write_json_atomic(cards_mod._path(d["id"]), d, indent=1)
    return {"ok": True}


@router.post("/api/cards/adopt")
async def cards_adopt(body: dict):
    """ADOPTE une carte connectée : probe -> registre, io.json (device + midi_out + nb sorties),
    reaper.ini (alsa_indev/outdev, écrit APRÈS la mort du process — même règle que le buffer),
    restart du moteur. Le patch des rôles se seed tout seul au prochain accès (inputmap._load) ;
    celui de la carte REMPLACÉE reste intact dans config/inputmaps/ (retour sans reconfiguration)."""
    from . import cards as cards_mod
    cid = (body.get("id") or "").strip()
    if sys.platform == "win32":
        from . import desktop_audio
        current = desktop_audio.settings()
        if cid not in current["drivers"]:
            return JSONResponse({"error": "Choose an installed ASIO driver"}, status_code=400)
        request = {key: current[key] for key in ("sample_rate", "sample_rate_use", "buffer_size",
                                                  "buffer_size_use")}
        request.update(driver=cid, input_first=0, input_last=1,
                       output_first=0, output_last=1)
        try:
            apply = desktop_audio.start_apply(request)
            return {"ok": True, "card": cid, "apply": apply}
        except (OSError, ValueError, RuntimeError) as e:
            return JSONResponse({"error": str(e)}, status_code=409)
    if sys.platform == "darwin":
        # macOS : la carte = un périphérique Core Audio ; sa sortie suit quand elle en a une (une
        # interface USB), sinon la sortie actuelle reste (micro USB seul, casque sur le Mac)
        from . import desktop_audio
        current = desktop_audio.settings()
        if cid not in current["inputs"]:
            return JSONResponse({"error": "Choose a connected CoreAudio input"}, status_code=400)
        request = {key: current[key] for key in ("sample_rate", "sample_rate_use", "buffer_size",
                                                  "buffer_size_use", "output_device")}
        request["input_device"] = cid
        if cid in current["outputs"]:
            request["output_device"] = cid
        try:
            apply = desktop_audio.start_apply(request)
            return {"ok": True, "card": cid, "apply": apply}
        except (OSError, ValueError, RuntimeError) as e:
            return JSONResponse({"error": str(e)}, status_code=409)
    d = cards_mod.remember(cid)                              # probe + registre (descriptor sauvé)
    if d is None:
        return JSONResponse({"error": f"card {cid!r} not connected"}, status_code=404)
    if not (d.get("inputs") or d.get("outputs")):            # ceinture : jamais adopter un device sans PCM
        return JSONResponse({"error": f"{d.get('name')} has no audio (a MIDI controller?)"}, status_code=400)
    try:                                                     # validations AVANT de tuer Reaper
        open(REAPER_INI).read()                              # lisible ? (clés absentes : AJOUTÉES à l'écriture)
        if not os.path.exists(REAPER_INI + ".golem.bak"):
            shutil.copy2(REAPER_INI, REAPER_INI + ".golem.bak")
    except Exception as e:
        return JSONResponse({"error": f"reaper.ini : {e}"}, status_code=500)
    from . import install_receipt                            # reçu : la carte d'avant golem (le premier gagne)
    for key in ("alsa_indev", "alsa_outdev"):
        install_receipt.prior(f"reaper_ini.keys.{key}", install_receipt.ini_value(REAPER_INI, key))
    # io.json : device + port MIDI OUT de la carte (la Whammy suit), nb de sorties physiques
    io_path = os.path.join(C.CONFIG_DIR, "io.json")
    io = _read_json(io_path, {}) or {}
    io["device"] = f"hw:{cid}"
    io["outputs_count"] = int(d.get("outputs") or 2)
    port = cards_mod.midi_out_port(cid)
    if port:
        io["midi_out"] = port
    store._write_json_atomic(io_path, io)     # l'identité de la carte son : jamais tronquée
    # les ports MIDI suivent la carte : on oublie les caches (Whammy) et on rebranche le pied
    with contextlib.suppress(Exception):
        from . import midi_out
        midi_out.reset_ports()
    with contextlib.suppress(Exception):
        from . import app as _app
        if _app._foot:
            _app._foot.rebind()

    def write_ini():   # exécuté une fois Reaper réellement mort (il réécrit l'ini en quittant)
        try:
            cur = open(REAPER_INI).read()
            cur = _ini_set(cur, "alsa_indev", f"hw:{cid}")
            cur = _ini_set(cur, "alsa_outdev", f"hw:{cid}")
            # les masques MIDI (midiins/midiouts) ne sont PAS touchés ici : c'est le domaine de
            # provision/reaper-ini-setup.py (lancé par start.sh AVANT chaque relance du moteur),
            # qui les recalcule depuis le [mididevcache] de Reaper — AKAI seul, jamais la carte
            # son. La sentinelle golem_midi.lua vérifie le contrat en continu (presets/.midi.json).
            tmp = REAPER_INI + ".golem.tmp"     # tmp + replace : jamais d'ini tronqué (audit 2026-08-12)
            open(tmp, "w").write(cur)
            os.replace(tmp, REAPER_INI)
        except Exception as e:
            log_cards.error(f"⚠ reaper.ini non réécrit ({e}) — la carte adoptée n'est pas posée")

    # RECALL DU MODE À LA CARTE (docs/modes.md §4) : le mode courant déclarait-il une AUTRE
    # carte ? Alors il n'est plus jouable — on prend celui qui déclare la nouvelle. Silencieux
    # si le mode courant vaut pour n'importe quelle carte, et jamais depuis un mode verrouillé.
    switched = None
    try:
        from . import modes as modes_mod
        from .routes_modes import _re_veto
        tgt = modes_mod.for_card(f"hw:{cid}")
        if tgt is not None:
            state.mode = modes_mod.set_current(tgt["id"])
            _re_veto()
            from .routes_modes import clear_practice
            clear_practice()
            switched = tgt["id"]
            with contextlib.suppress(Exception):             # sa liste au pied par défaut (patch-as-preset §7)
                _ok, _why = modes_mod.apply_foot_list(state.mode)
                if _why:
                    log_cards.warning(_why)
            log_cards.info(f"carte {cid} adoptée → mode « {tgt['name']} » (déclaré pour cette carte)")
            # push WS : le badge de mode de la topbar suit la bascule sans recharger la page
            with contextlib.suppress(Exception):
                from . import app as _app
                await _app._broadcast()
    except Exception as e:
        log_cards.warning(f"recall du mode à la carte non appliqué : {e}")

    _restart_reaper_async(after_dead=write_ini, why="settings")
    return {"ok": True, "card": d, "restarting": True, "mode": switched}


# ── Soundcard : vue I/O de la carte (onglet Settings ▸ Gear ▸ Soundcard) ─────────────
def _card_index(alsa_id):
    """Index numérique de la carte ALSA (V276 -> 1) via le lien /proc/asound/<id> -> cardN."""
    try:
        return int(os.path.basename(os.path.realpath(f"/proc/asound/{alsa_id}")).replace("card", ""))
    except Exception:
        return None


def _pcm_open(alsa_id, direction):
    """True si un process (Reaper) tient le flux ALSA ('p'=playback, 'c'=capture)."""
    try:
        return open(f"/proc/asound/{alsa_id}/pcm0{direction}/sub0/hw_params").read().strip() != "closed"
    except Exception:
        return False


def _seq_clients():
    """Clients ALSA seq (`aconnect -l`, forcé LANG=C : les libellés sont localisés sinon).
    to = quelqu'un LIT le port (source branchée, ex. foot.py sur le DIN IN) ;
    frm = quelqu'un ÉCRIT dessus (ex. whammy du bridge vers le DIN OUT)."""
    try:
        out = subprocess.run(["aconnect", "-l"], capture_output=True, text=True, timeout=5,
                             env={**os.environ, "LANG": "C", "LC_ALL": "C"}).stdout
    except Exception:
        return []
    clients, cur = [], None
    for ln in out.splitlines():
        m = re.match(r"client (\d+): '(.*)' \[(.*)\]", ln)
        if m:
            attrs = dict(kv.split("=", 1) for kv in m.group(3).split(",") if "=" in kv)
            cur = {"id": int(m.group(1)), "name": m.group(2).strip(),
                   "kernel": attrs.get("type") == "kernel",
                   "card": int(attrs["card"]) if attrs.get("card", "").isdigit() else None,
                   "to": False, "frm": False}
            clients.append(cur)
        elif cur and "Connecting To" in ln:
            cur["to"] = True
        elif cur and "Connected From" in ln:
            cur["frm"] = True
    return clients


SOUNDCARD_CFG = os.path.join(C.CONFIG_DIR, "soundcard.json")


def _soundcard_cfg():
    """La vue usbN, dérivée du registre des appareils connus (bridge/devices.py, 2026-09-23)."""
    from . import devices
    return devices.bindings()


@router.post("/api/soundcard/midi-port")
async def soundcard_midi_port(body: dict):
    """Windows/macOS : la prise DIN `in` (pédalier) ou `out` (Whammy) = ce port MIDI de l'OS, ou aucun
    (`port: null`). Le bridge s'y rebranche tout de suite ; REAPER, lui, ne lâche (ou ne prend) un
    port qu'en redémarrant — `restart_needed` le dit (bridge/desktop_midi.py)."""
    if sys.platform not in ("win32", "darwin"):
        return JSONResponse({"error": "on the rack the DIN jacks are the sound card's own MIDI"}, status_code=400)
    from . import desktop_midi, foot as _foot, midi_out as _mout
    kind, port = body.get("kind"), body.get("port")
    if kind not in ("in", "out") or (port is not None and not isinstance(port, str)):
        return JSONResponse({"error": "kind must be in|out, port a port name or null"}, status_code=400)
    if desktop_midi.din_source(kind) == "env":
        return JSONResponse({"error": f"{desktop_midi._ENV[kind]} is set on this computer and wins — remove it first"},
                            status_code=409)
    desktop_midi.set_din_port(kind, port)
    desktop_midi._CACHE["at"] = 0.0
    if kind == "in" and _foot._READER is not None:
        _foot._READER.rebind()
    if kind == "out":
        _mout.reset_ports()
    return {"ok": True, "restart_needed": desktop_midi.masks_pending(C.reaper_resource_dir())}


@router.post("/api/soundcard/usb")
async def soundcard_usb(body: dict):
    """Binding d'une prise GoleM USB : {port: 1|2, enabled: bool, roles?: ["keys","pads"], kit?}.
    Depuis le 2026-09-23 (« connu ≠ branché », docs/gear-registry.md) : lier = rendre CONNU l'appareil
    détecté à ce rang (bridge/devices.py) ; un appareil connu qui réapparaît à n'importe quel rang y est
    actif tout seul. `enabled: false` = l'OUBLIER — le seul geste qui retire un appareil, explicite.
    `roles` (P0 claviers, docs/archive/keys-rig-plan.md) : "keys" / "pads" se combinent ; ["drums"] est exclusif."""
    from . import inputmap, devices
    port = body.get("port")
    if port not in range(1, inputmap.USB_PORTS + 1):
        return JSONResponse({"error": f"port must be 1..{inputmap.USB_PORTS}"}, status_code=400)
    key = devices.key_at(port)
    if body.get("enabled"):
        roles = body.get("roles")
        if roles is not None and (not isinstance(roles, list) or not roles
                                  or (roles != ["drums"] and any(r not in ("keys", "pads") for r in roles))):
            return JSONResponse({"error": 'roles must be a list of "keys"/"pads", or exactly ["drums"]'}, status_code=400)
        extra = {}
        if "kit" in body:                                    # docs/drums-kit.md lot 1 : le descripteur (null = auto par USB)
            from . import drumkits
            kid = body.get("kit")
            if kid and not drumkits.get(kid):
                return JSONResponse({"error": f"unknown drum kit descriptor: {kid}"}, status_code=400)
            extra["kit"] = kid or None
        try:
            if key:
                devices.update(key, roles=roles, **extra)
            else:
                devices.bind(port, roles=roles, **extra)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
    elif key:
        devices.forget(key)
    out = {"ok": True, "binding": devices.bindings()}
    if sys.platform in ("win32", "darwin"):           # REAPER n'ouvre un clavier qu'en démarrant
        from . import desktop_midi
        out["restart_needed"] = desktop_midi.masks_pending(C.reaper_resource_dir())
    return out


# ── les appareils connus (docs/gear-registry.md addendum 2026-09-23) ─────────────────────────
@router.get("/api/devices")
def devices_list():
    """Connus ∪ détectés, chacun avec son état (connected, port, last_seen), son profil de calibration
    (contrôleur) et son descripteur de kit (module de batterie)."""
    from . import devices, controllers, drumkits
    out = []
    for d in devices.listing():
        prof = controllers.load(d.get("usb") or "", d.get("name") or "")
        row = {**d, "calibrated": (prof or {}).get("calibrated")}
        if "drums" in (d.get("roles") or []):
            row["kit"] = drumkits.resolve({"device": d.get("name"), "kit": d.get("kit")})
        out.append(row)
    return {"devices": out}


@router.post("/api/devices/{key}")
async def devices_update(key: str, body: dict):
    """Modifier un appareil CONNU, branché ou non : {roles?, person?, kit?}."""
    from . import devices, drumkits
    body = body or {}
    roles = body.get("roles")
    if roles is not None and (not isinstance(roles, list) or not roles
                              or (roles != ["drums"] and any(r not in ("keys", "pads") for r in roles))):
        return JSONResponse({"error": 'roles must be a list of "keys"/"pads", or exactly ["drums"]'}, status_code=400)
    extra = {}
    if "person" in body:
        extra["person"] = body.get("person") or None
    if "kit" in body:
        kid = body.get("kit")
        if kid and not drumkits.get(kid):
            return JSONResponse({"error": f"unknown drum kit descriptor: {kid}"}, status_code=400)
        extra["kit"] = kid or None
    try:
        k, e = devices.update(key, roles=roles, **extra)
    except KeyError:
        return JSONResponse({"error": f"unknown device: {key}"}, status_code=404)
    return {"ok": True, "key": k, "device": e}


@router.delete("/api/devices/{key}")
async def devices_forget(key: str):
    """Oublier un appareil — la seule sortie du registre, et elle est explicite."""
    from . import devices
    e = devices.forget(key)
    if e is None:
        return JSONResponse({"error": f"unknown device: {key}"}, status_code=404)
    return {"ok": True, "forgotten": e}


@router.get("/api/soundcard")
def soundcard():
    """Vue I/O temps réel de la carte : la carte est-elle là, Reaper tient-il les flux (entrées/
    sorties/casque « actives »), le MIDI DIN est-il exploité (subscriptions seq), et quels
    périphériques USB sont branchés (contrôleurs MIDI type MPK mini, cartes audio USB) -> les
    2 prises USB host de la version rack. L'UI poll ce endpoint toutes les ~3 s."""
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        settings = desktop_audio.settings()
        actual = settings.get("actual") or {}
        driver = settings.get("driver") if sys.platform == "win32" else settings.get("input_device")
        backend = "ASIO" if sys.platform == "win32" else "CoreAudio"
        opened = actual.get("MODE", "").replace(" ", "").casefold() == backend.casefold()
        if sys.platform == "win32":
            opened = bool(opened and driver and driver.casefold() in
                          (actual.get("IDENT_IN", "") + " " + actual.get("IDENT_OUT", "")).casefold())
            present = bool(opened and driver in settings["drivers"])
        else:
            present = bool(opened and driver in settings["inputs"])
        try:
            inputs = int(actual["INPUT_COUNT"]) if opened else None
            outputs = int(actual["OUTPUT_COUNT"]) if opened else None
        except (KeyError, TypeError, ValueError):
            inputs = outputs = None
        latency, source = desktop_audio.latency_ms(actual)
        # la rangée RACK de l'écran (USB 1-4 + MIDI IN/OUT) : bridge/desktop_midi.py
        from . import desktop_midi, devices, foot as _foot, midi_out as _mout
        mports = desktop_midi.ports()
        din_in, din_out = desktop_midi.din_port("in"), desktop_midi.din_port("out")
        reader = _foot._READER
        midi = {"present": bool(mports["in"] or mports["out"]),
                "in_active": bool(reader is not None and getattr(reader, "_native_connected", None)
                                  and reader._native_connected.is_set()),
                "out_active": bool(_mout._RT.get("name")),
                "in_port": din_in, "out_port": din_out,
                "in_source": desktop_midi.din_source("in"), "out_source": desktop_midi.din_source("out"),
                "in_present": any(desktop_midi.same(p, din_in) for p in mports["in"]) if din_in else False,
                "out_present": any(desktop_midi.same(p, din_out) for p in mports["out"]) if din_out else False,
                "ports": mports,
                "restart_needed": desktop_midi.masks_pending(C.reaper_resource_dir())}
        bound = devices.bindings()
        usb = [{"name": d["name"], "kind": d.get("kind") or "midi", "active": f"usb{d['port']}" in bound}
               for d in devices.detected()]
        return {"card": {"alsa": driver or "", "name": driver or "", "present": present,
                         "backend": backend, "inputs": inputs, "outputs": outputs,
                         "input_names": actual.get("INPUT_NAMES") if opened else None,
                         "output_names": actual.get("OUTPUT_NAMES") if opened else None},
                "platform": sys.platform, "drivers": settings.get("drivers", []),
                "sample_rate": actual.get("SRATE") if opened else None,
                "latency_ms": latency, "latency_source": source,
                "playback_open": bool(opened and actual.get("IDENT_OUT")),
                "capture_open": bool(opened and actual.get("IDENT_IN")),
                "bsize": _read_bsize(), "midi": midi, "usb": usb, "binding": bound}
    alsa, idx = C.alsa_card(), _card_index(C.alsa_card())
    name, present = None, False
    try:                                     # "/proc/asound/cards :  1 [V276 ]: USB-Audio - Volt 276"
        for ln in open("/proc/asound/cards"):
            m = re.match(r"\s*\d+\s+\[(\S+)\s*\]:\s*\S+ - (.*)", ln)
            if m and m.group(1) == alsa:
                present, name = True, m.group(2).strip()
    except Exception as _e:
        _swallowed(_e)
    clients = _seq_clients()
    own = [c for c in clients if c["card"] is not None and c["card"] == idx]
    # prises USB host : clients MIDI noyau d'AUTRES cartes (contrôleurs) + cartes audio USB en plus
    midi_cards = set()
    usb = []
    for c in clients:
        if c["kernel"] and c["card"] is not None and c["card"] != idx and c["name"] not in ("System", "Midi Through"):
            midi_cards.add(c["card"])
            usb.append({"name": c["name"], "kind": "midi", "active": c["to"] or c["frm"]})
    try:                                     # cartes audio USB supplémentaires (sans port MIDI)
        for ln in open("/proc/asound/cards"):
            m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]:\s*USB-Audio - (.*)", ln)
            if m and m.group(2) != alsa and int(m.group(1)) not in midi_cards:
                usb.append({"name": m.group(3).strip(), "kind": "audio", "active": False})
    except Exception as _e:
        _swallowed(_e)
    return {
        "card": {"alsa": alsa, "name": name, "present": present},
        "playback_open": _pcm_open(alsa, "p"),
        "capture_open": _pcm_open(alsa, "c"),
        "bsize": _read_bsize(),
        "midi": {"present": bool(own), "in_active": any(c["to"] for c in own),
                 "out_active": any(c["frm"] for c in own)},
        "usb": usb[:2],
        "binding": _soundcard_cfg(),
    }


# ── actions de réparation (dashboard System : agir depuis la tuile en défaut) ─
@router.post("/api/system/reaper-restart")
async def reaper_restart():
    """(Re)lance Reaper : pkill (no-op s'il est down) puis provision/start.sh (Set + OSC + veilleur
    repartent via __startup). L'UI suit reaper_running/reaper_connected en WebSocket."""
    from . import boot_progress
    boot_progress.reset("restart")                         # l'écran de chargement revient (mockups/loading.html)
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        current = await asyncio.to_thread(desktop_audio.settings)
        keys = ("sample_rate", "sample_rate_use", "buffer_size", "buffer_size_use")
        keys += (("driver", "input_first", "input_last", "output_first", "output_last")
                 if sys.platform == "win32" else ("input_device", "output_device"))
        try:
            apply = await asyncio.to_thread(desktop_audio.start_apply,
                                            {key: current[key] for key in keys}, ensure_running=True)
            return {"ok": True, "restarting": True, "apply": apply}
        except (ValueError, RuntimeError, OSError) as e:
            return JSONResponse({"error": str(e)}, status_code=409)
    _restart_reaper_async()
    return {"ok": True, "restarting": True}


@router.post("/api/system/osc-refresh")
async def osc_refresh():
    """Resynchronise le lien OSC SANS redémarrer : action Reaper native 41743 (« Control surface:
    refresh all surfaces ») -> Reaper renvoie tout son état OSC ; si le device est vivant, le
    monitor voit le trafic et reaper_connected repasse à vrai. Sinon -> restart Reaper."""
    from . import app as _app
    sent = _app.reaper.trigger_action(41743)
    return {"ok": bool(sent)}


@router.post("/api/system/bridge-restart")
async def bridge_restart():
    """Redémarre le bridge lui-même via provision/reload.sh, détaché (le script tue cet uvicorn
    puis en relance un). La réponse part AVANT la mort du process (sleep 0.5) ; l'UI voit le
    WebSocket tomber puis revenir (reconnexion auto)."""
    if sys.platform in ("win32", "darwin"):
        return JSONResponse({"error": "Restart the desktop launcher to restart the bridge"}, status_code=409)
    subprocess.Popen(["bash", "-c", "sleep 0.5; exec ./provision/reload.sh"],
                     cwd=C.ROOT, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "restarting": True}


# ── stats de contenu (sous-onglet Content du dashboard) ──────────────────────
@router.get("/api/system/content")
def system_content():
    presets = load_presets()
    tones = (_read_json(C.CATALOG, {}) or {}).get("tones", [])
    gears = [str(t.get("gear")) for t in tones]
    effects = (_read_json(os.path.join(C.ROOT, "library", "catalog", "effects.json"), {}) or {}).get("effects", [])
    from . import setlists as _sl                     # la liste AU PIED, pas fcb-banks.json (2026-09-30)
    banks = _sl.load(_sl.active_id()) or {}
    taken = len([x for x in (banks.get("presets") or []) if x])
    try:
        templates = len([f for f in os.listdir(os.path.join(C.ROOT, "templates")) if f.endswith(".json")])
    except Exception:
        templates = 0
    return {
        "presets": len(presets),
        "scenes": sum(len(p.get("scenes") or []) for p in presets),
        "amps": gears.count("amp") + gears.count("amp-cab"),
        "cabs": gears.count("cab"),
        "pedals": gears.count("pedal"),
        "tones": len(tones),
        "effects": len(effects),
        "templates": templates,
        "fcb": {"taken": taken, "capacity": 19, "free": max(0, 19 - taken)},
        "sizes": _backup.counts(),          # volumétrie par catégorie de backup (nb + octets)
    }


# ── sauvegardes .zip (backups/) : créer / lister / télécharger / supprimer ────
@router.post("/api/backup")
async def make_backup(body: dict):
    """Construit UNE sauvegarde dans backups/ : `{kind}` (une catégorie, ou `all`) ou `{kinds: [...]}` (une sélection,
    un seul fichier — modal I/O refondu, 2026-10-09). `vault: true` = en garder aussi une copie chez golem.fm (« Also keep
    a copy on golem.fm »), SI le vault accepte ce type — sinon c'est dit (`vault.why`), la sauvegarde locale reste.
    Rangé en tâche exécutrice (une sauvegarde complète = des centaines de Mo, ne bloque pas la boucle)."""
    b = body or {}
    kinds = b.get("kinds")
    what = kinds if isinstance(kinds, list) and kinds else b.get("kind")
    if not what or (isinstance(what, str) and (what not in _backup.KINDS or what == "custom")):
        return JSONResponse({"error": "unknown category: %s" % what}, status_code=400)
    try:
        r = await asyncio.get_running_loop().run_in_executor(None, _backup.build, what)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    # le VAULT : demandé ici, ou l'envoi automatique (Settings ▸ Connect ▸ golem.fm) — jamais pour un type que golem.fm refuse
    from . import golemfm
    from .routes_content import _load_integrations
    want = bool(b.get("vault")) or bool((_load_integrations().get("golemfm") or {}).get("auto_push"))
    if want:
        why = _backup.vault_refusal(r["file"])
        if why:
            r["vault"] = {"ok": False, "why": why}
        else:
            pr = golemfm.push_backup(r["file"])
            r["vault"] = {"ok": bool(pr.get("ok")), **({"why": pr.get("error")} if not pr.get("ok") else {})}
        r["auto_push"] = bool((r.get("vault") or {}).get("ok"))
    return r


@router.get("/api/backups/overview")
async def backups_overview():
    """L'écran Export : chaque catégorie, sa taille, sa dernière sauvegarde (rack ou vault) ; la dernière complète ; ce
    qui n'est pas sauvegardé. Le vault est lu chez golem.fm (réseau -> executor) ; injoignable, on montre le rack."""
    from . import golemfm
    loop = asyncio.get_running_loop()
    remote = await loop.run_in_executor(None, golemfm.list_remote)
    o = await loop.run_in_executor(None, _backup.overview, (remote or {}).get("backups") or [])
    return {**o, "vault": {"online": bool((remote or {}).get("online")),
                           **{k: remote.get(k) for k in ("bytes", "max_bytes") if isinstance(remote, dict) and k in remote}}}


@router.get("/api/backups")
def get_backups():
    return {"backups": _backup.list_backups()}


@router.get("/api/backup/remote")
async def list_remote_backups():
    """Backups présents dans le vault golem.fm (réseau -> executor). DÉCLARÉE AVANT
    /api/backup/{name} sinon 'remote' serait matché comme un nom de fichier."""
    from . import golemfm
    return await asyncio.get_running_loop().run_in_executor(None, golemfm.list_remote)


@router.get("/api/backup/{name}")
def download_backup(name: str):
    p = _backup.backup_path(name)
    if not p:
        return JSONResponse({"error": "backup not found"}, status_code=404)
    return FileResponse(p, media_type="application/zip", filename=name)


@router.post("/api/backup/{name}/save-local")
def save_backup_local(name: str, request: Request):
    """La sauvegarde copiée dans les Téléchargements de CETTE machine (bridge/downloads.py) : la fenêtre golem desktop
    n'affiche plus la bulle de téléchargement de Chrome. Réservé à l'écran local."""
    from . import auth as auth_mod, downloads
    if not auth_mod._is_local(request.client.host if request.client else ""):
        return JSONResponse({"error": "only on this machine's own screen"}, status_code=403)
    p = _backup.backup_path(name)
    if not p:
        return JSONResponse({"error": "backup not found"}, status_code=404)
    return {"ok": True, **downloads.save_copy(p, name)}


@router.post("/api/system/save-local")
async def system_save_local(request: Request, name: str = ""):
    """Un petit fichier produit par l'app (fichier de moteur…) écrit dans les Téléchargements de CETTE machine.
    Corps BRUT = le contenu (1 Mo au plus). Réservé à l'écran local : un appareil distant télécharge chez lui."""
    from . import auth as auth_mod, downloads
    if not auth_mod._is_local(request.client.host if request.client else ""):
        return JSONResponse({"error": "only on this machine's own screen"}, status_code=403)
    blob = await request.body()
    if len(blob) > 1 << 20:
        return JSONResponse({"error": "file too large"}, status_code=413)
    return {"ok": True, **downloads.save_bytes(name, blob)}


@router.post("/api/system/save-local-url")
def system_save_local_url(request: Request, body: dict):
    """N'IMPORTE QUEL fichier que le rack sert (une prise, un sample, un groove, un kit…) écrit dans les Téléchargements
    de CETTE machine, sans passer par le navigateur (2026-10-15 : « appliquer partout la solution du 12/10 » — la
    bulle de téléchargement de Chrome surgissait HORS de golem). Le bridge se demande le fichier à lui-même : une seule
    route, et chaque téléchargement garde la sienne (ses noms, ses gardes). Réservé à l'écran local ; seule une adresse
    `/api/…` de ce rack est acceptée, jamais une URL externe."""
    import urllib.request
    from urllib.parse import urlsplit
    from . import auth as auth_mod, downloads
    if not auth_mod._is_local(request.client.host if request.client else ""):
        return JSONResponse({"error": "only on this machine's own screen"}, status_code=403)
    url = str(body.get("url") or "")
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path.startswith("/api/") or ".." in parts.path:
        return JSONResponse({"error": "invalid address"}, status_code=400)
    # le bridge se lit lui-même par la boucle locale — jamais par le Host qu'envoie le client
    # (scope["server"] = l'adresse locale de la socket, que le client ne choisit pas)
    host, port = request.scope.get("server") or ("127.0.0.1", 8770)
    base = "http://%s:%d" % (("[%s]" % host) if ":" in str(host) else host, port)
    try:
        with urllib.request.urlopen(base + url, timeout=60) as r:
            name = str(body.get("name") or "") or downloads.filename_of(r.headers.get("Content-Disposition"), url)
            return {"ok": True, **downloads.save_stream(name, r)}
    except urllib.error.HTTPError as e:
        return JSONResponse({"error": "the rack refused this file (%s)" % e.code}, status_code=502)
    except OSError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/api/backup/{name}")
def remove_backup(name: str):
    return {"ok": True} if _backup.delete_backup(name) else JSONResponse({"error": "not found"}, status_code=404)


# ── vault golem.fm : pousser/tirer les backups vers le serveur ───────────────
@router.post("/api/backup/push/{name}")
def push_backup_remote(name: str):
    """Pousse backups/<name> vers le vault golem.fm (thread démon + polling status)."""
    from . import golemfm
    if not _backup.backup_path(name):
        return JSONResponse({"error": "backup not found"}, status_code=404)
    r = golemfm.push_backup(name)
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.get("/api/backup/push/status")
def push_backup_status():
    from . import golemfm
    return golemfm.push_status()


@router.delete("/api/backup/remote/{backup_id}")
async def delete_remote_backup(backup_id: int):
    """Retire une sauvegarde du vault. Déclarée AVANT toute route à segment libre, même
    raison que /api/backup/remote (sinon « remote » serait pris pour un nom de fichier)."""
    from . import golemfm
    r = await asyncio.get_running_loop().run_in_executor(None, golemfm.delete_remote, backup_id)
    return r if r.get("ok") else JSONResponse(r, status_code=502)


@router.post("/api/backup/pull")
async def pull_remote_backup(body: dict):
    """Télécharge un backup du vault dans backups/ (sha vérifié). Le fichier entre
    dans la liste locale — restauration via le pipeline d'import existant."""
    from . import golemfm
    bid = (body or {}).get("id")
    if not isinstance(bid, int):
        return JSONResponse({"error": "id required"}, status_code=400)
    r = await asyncio.get_running_loop().run_in_executor(None, golemfm.pull_backup, bid)
    return r if r.get("ok") else JSONResponse(r, status_code=502)


# ── tone library golem.fm : miroir de la lib (packs + blobs) ─────────────────
@router.get("/api/tones-sync")
def tones_sync_status():
    """Statut du push de la tone library (poll pendant un sync) + dernier résultat."""
    from . import tones_sync
    base, token = tones_sync._cfg()
    return {"paired": bool(base and token), **tones_sync.status()}


@router.post("/api/tones-sync")
def tones_sync_start():
    """Déclenche un sync manuel de la tone library vers golem.fm (thread démon)."""
    from . import tones_sync
    r = tones_sync.start_sync()
    return r if r.get("ok") else JSONResponse(r, status_code=409)


# ── prêts de Library au groupe (docs/library-loans.md) ───────────────────────
@router.get("/api/library/lent")
def library_lent():
    """Le registre des prêts : disponible, installé (et par qui), retiré, incomplet — ce que la Library montre."""
    from . import loans
    return loans.status()


@router.post("/api/library/lent/pull-all")
def library_lent_pull_all():
    """« Download all lent » : le geste humain qui tire tout ce qui est prêté et pas encore là (tâche de fond)."""
    from . import loans
    return loans.pull_all()


# ── jobs golem.fm (module /golem) : install/remove/recall en pull ────────────
@router.get("/api/tones-jobs")
def tones_jobs_status():
    """Dernier passage de la file de jobs golem.fm (compteurs + log court)."""
    from . import tones_jobs
    return tones_jobs.status()


@router.post("/api/tones-jobs/run")
async def tones_jobs_run():
    """Tire et traite la file MAINTENANT (les installs peuvent être longues —
    exécuté hors event-loop)."""
    from . import tones_jobs
    r = await asyncio.get_running_loop().run_in_executor(None, tones_jobs.process)
    return r if r.get("ok") else JSONResponse(r, status_code=409)


# ── import d'un backup .zip : analyse (dry-run) puis application confirmée ────
@router.post("/api/import/inspect-local")
async def import_inspect_local(body: dict):
    """Comme /api/import/inspect mais pour un zip DÉJÀ dans backups/ (ex. tiré du
    vault) : staging disque-à-disque, pas de round-trip navigateur de 500 Mo."""
    from . import importer
    name = (body or {}).get("file")
    p = _backup.backup_path(name)
    if not p:
        return JSONResponse({"ok": False, "error": "backup not found"}, status_code=404)
    loop = asyncio.get_running_loop()
    try:
        token, path = await loop.run_in_executor(None, importer.stage_path, p)
        plan = await loop.run_in_executor(None, importer.inspect, path)
        plan["token"] = token
        return plan
    except importer.ImportError_ as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/import/inspect")
async def import_inspect(request: Request):
    """Corps BRUT = octets du .zip. Valide TOUT (manifeste, hash, chemins) et renvoie le PLAN + un token.
    Aucune écriture. Un zip douteux est refusé ici (400)."""
    from . import importer
    from .http_body import body_to_file, TooLarge
    # audit 2026-11-04 (M9) : jusqu'à 2 Go — écrits sur le disque au fil de l'eau, jamais gardés en mémoire
    os.makedirs(importer.STAGING, exist_ok=True)
    tmp = os.path.join(importer.STAGING, f".upload-{os.getpid()}-{id(request)}.part")
    try:
        await body_to_file(request, tmp, importer.MAX_ZIP)
    except TooLarge:
        return JSONResponse({"ok": False, "error": "file too large (> 2 GB)"}, status_code=413)
    loop = asyncio.get_running_loop()
    try:
        if not os.path.getsize(tmp):
            raise importer.ImportError_("empty body")
        token, path = await loop.run_in_executor(None, importer.stage_path, tmp)
        plan = await loop.run_in_executor(None, importer.inspect, path)
        plan["token"] = token
        return plan
    except importer.ImportError_ as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


@router.post("/api/import/apply")
async def import_apply(body: dict):
    """Applique le backup stagé (token) avec la stratégie de doublons choisie. Re-valide + pré-backup."""
    from . import importer
    token = (body or {}).get("token")
    strategy = (body or {}).get("strategy", "skip")
    path = importer._staged_path(token)
    if not path:
        return JSONResponse({"error": "import expired or not found — load the file again"}, status_code=404)
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, importer.apply, path, strategy)
        importer.discard(token)
        return res
    except importer.ImportError_ as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── mise à jour git — RELEASES UNIQUEMENT (tags) ─────────────────────────────
def _git_rc(*args, timeout=30):
    try:
        r = subprocess.run(["git", "-C", C.ROOT, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _has_git_repo():
    return bool(shutil.which("git")) and _git_rc("rev-parse", "--git-dir")[0] == 0


@router.get("/api/system/update")
def system_update(fetch: int = 0):
    """État de mise à jour, borné aux TAGS (releases). fetch=1 : git fetch --tags d'abord (réseau).
    status : no-release | up-to-date | update-available | ahead (dev local devant la release)."""
    # SANS GIT, PAS DE MISE À JOUR D'ICI (2026-11-06) : une install Windows/macOS est une COPIE sans .git (le bootstrap
    # télécharge l'archive), et sans git `_git` rend son message d'erreur — l'écran le prenait pour un nom de release.
    # Une telle install se met à jour PAR ARCHIVE (bridge/release_update.py, docs/update.md §3) : la release de GitHub.
    if not _has_git_repo():
        from . import release_update
        return release_update.status(fetch=bool(fetch))
    fetch_err = None
    if fetch:
        rc, _, err = _git_rc("fetch", "--tags", "--quiet", "origin", timeout=60)
        if rc != 0:
            fetch_err = err.splitlines()[-1] if err else "git fetch failed"
    head = _git("rev-parse", "HEAD")
    tags = [t for t in _git("tag", "--sort=-v:refname").splitlines() if t]
    latest = tags[0] if tags else None
    status, log = "no-release", []
    if latest:
        tag_commit = _git("rev-parse", latest + "^{}")
        if tag_commit == head:
            status = "up-to-date"
        elif _git_rc("merge-base", "--is-ancestor", latest + "^{}", "HEAD")[0] == 0:
            status = "ahead"
        else:
            status = "update-available"
            log = _git("log", "--oneline", "--no-decorate", "HEAD.." + latest).splitlines()[:20]
    # LES NOTES DE LA RELEASE (2026-11-06) : le message du tag annoté, écrit en anglais pour l'écran — les sujets de
    # commit sont en français (CLAUDE.md, règle 4) et ne s'affichent plus. Arrivé avec le même `git fetch --tags`.
    notes = _tag_notes(latest) if status == "update-available" else ""
    return {"current": _git("describe", "--tags", "--always"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "clean": not (changes := _code_changes()), "changes": changes[:20],
            # POSTE : la bascule relance TOUT (fenêtre, REAPER, bridge), pas seulement le bridge
            "full_restart": sys.platform in ("win32", "darwin"),
            "latest": latest, "status": status, "log": log, "notes": notes, "fetch_error": fetch_err,
            # True signée · False refusée à l'installation · None aucune clé déclarée (docs/release-signing.md)
            "signed": _release_signed(latest)}


def _tag_notes(tag):
    """Le message d'un tag ANNOTÉ, sans sa signature ; « » pour un tag léger (son message serait celui du commit)."""
    if not tag or _git("cat-file", "-t", tag) != "tag":
        return ""
    body = _git("tag", "-l", "--format=%(contents)", tag)
    return body.split("-----BEGIN ", 1)[0].strip()[:4000]


def _release_signed(tag):
    if not tag:
        return None
    from . import release_sig
    try:
        return release_sig.verify(tag)[0]
    except Exception:
        return False


@router.post("/api/system/update")
async def system_update_apply(body: dict):
    """Bascule sur une RELEASE (git checkout <tag>) puis redémarre le bridge pour charger le
    nouveau code. Refus si l'arbre n'est pas propre (aucun stash/reset automatique)."""
    tag = (body or {}).get("tag")
    if not _has_git_repo():
        return await _update_by_archive(tag)
    if not tag or _git_rc("rev-parse", "--verify", tag + "^{}")[0] != 0:
        return JSONResponse({"error": f"unknown release: {tag}"}, status_code=400)
    if _code_changes():
        return JSONResponse({"error": "the golem code has local changes — commit or stash first"},
                            status_code=409)
    # la SIGNATURE du tag (docs/release-signing.md) : vérifiée avec les clés de la version INSTALLÉE
    from . import release_sig
    signed, why = release_sig.verify(tag)
    if signed is False:
        return JSONResponse({"error": why}, status_code=409)
    # l'état local SORTI du dépôt le 2026-10-15 (bridge/local_state.py) : mis de côté, sinon la bascule le supprime
    from . import local_state
    restore = local_state.preserve()
    rc, _, err = _git_rc("checkout", tag)
    restore()                                             # même en échec : la machine retrouve ses réglages
    if rc != 0:
        return JSONResponse({"error": err or "git checkout failed"}, status_code=500)
    return _restart_after_update(tag, signed)


async def _update_by_archive(tag):
    """La release `tag` posée par archive (install sans git), puis le même redémarrage que la voie git."""
    from . import release_update, release_sig
    if not release_update.vkey(tag):
        return JSONResponse({"error": f"unknown release: {tag}"}, status_code=400)
    # une release SIGNÉE ne se vérifie qu'avec git (git verify-tag) : déclarer une clé ferme la voie archive
    if release_sig._keys(os.path.join(C.ROOT, release_sig.SIGNERS)):
        return JSONResponse({"error": "releases are signed: updating needs git — run the install line again"},
                            status_code=409)
    try:
        await asyncio.get_running_loop().run_in_executor(None, release_update.apply, tag)
    except Exception as e:
        log.error(f"mise à jour par archive vers {tag} : {e}")
        return JSONResponse({"error": f"update failed: {e}"}, status_code=500)
    return _restart_after_update(tag, None, with_reaper=True)


def _restart_after_update(tag, signed, with_reaper=False):
    """Relance ce qu'il faut pour charger la release : TOUT sur un poste (Windows, macOS), le bridge sous Linux — et
    REAPER quand ses scripts ont changé (reload.sh le voit par git ; sans git, `with_reaper` le demande)."""
    if sys.platform in ("win32", "darwin"):
        # POSTE : pas de reload.sh ni de systemd. Le lanceur relance TOUT (fenêtre, REAPER, bridge) —
        # il faut de toute façon que REAPER relise les scripts Lua de la release (copy_resources au
        # démarrage). Un processus DÉTACHÉ : il survit à l'arrêt du bridge qui l'a lancé.
        from provision.desktop import venv_python
        py = venv_python()
        if sys.platform == "win32" and py.with_name("pythonw.exe").is_file():
            py = py.with_name("pythonw.exe")
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
        subprocess.Popen([str(py), "-m", "provision.desktop", "restart"], cwd=C.ROOT,
                         creationflags=flags, start_new_session=sys.platform != "win32",
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "tag": tag, "restarting": True, "full_restart": True, "signed": signed}
    subprocess.Popen(["bash", "-c", "sleep 0.5; exec ./provision/reload.sh" + (" --with-reaper" if with_reaper else "")],
                     cwd=C.ROOT, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "tag": tag, "restarting": True, "signed": signed}


# ── mise à jour du MOTEUR AUDIO (Reaper) — bornée au pin de la release ───────
@router.get("/api/system/reaper-update")
def system_reaper_update(check: bool = True, force: bool = False):
    """État moteur : version installée vs version VALIDÉE avec la release GoleM installée
    (pin REAPER_VERSION du provisioning). L'UI poll ce endpoint pendant une update (busy).

    Rend AUSSI la dernière version publiée par Cockos (`upstream`), lue au plus une fois par jour,
    en fond : une INFORMATION, jamais une cible — le bouton d'update reste borné au pin.
    `?check=0` n'en déclenche jamais la lecture (poll d'une update en cours, diagnostics)."""
    from . import reaper_update
    if force:
        reaper_update.upstream_check(force=True)
    return reaper_update.status(check=check and not force)


@router.post("/api/system/reaper-update")
async def system_reaper_update_apply(body: dict = None):
    """Déclenche l'update moteur : download + install côte à côte, bascule symlink, restart,
    smoke test (running + OSC), rollback automatique en échec. Coupe l'audio ~1 min.

    `{"version": "7.80"}` : installer la version PUBLIÉE par Cockos que le rack a lue, sans qu'une
    release GoleM l'ait validée (décision 2026-09-22 : l'utilisateur final doit pouvoir le faire
    seul). Le moteur refuse toute autre cible. Sans `version` : le pin, le chemin validé."""
    from . import reaper_update
    ok, err = reaper_update.start_update((body or {}).get("version"))
    if not ok:
        return JSONResponse({"error": err}, status_code=409)
    return {"ok": True, "started": True}


@router.post("/api/system/reaper-switch")
async def system_reaper_switch(body: dict):
    """Revient à une version DÉJÀ installée côte à côte (« Use 7.79 ») : aucun réseau, même séquence
    (arrêt, bascule, redémarrage, smoke test, rollback). C'est le filet d'une install non validée."""
    from . import reaper_update
    ok, err = reaper_update.start_switch((body or {}).get("version"))
    if not ok:
        return JSONResponse({"error": err}, status_code=409)
    return {"ok": True, "started": True}


# ── mixer de sorties (contrat docs/mixer.md) ─────────────────────────────────
@router.get("/api/mixer")
async def mixer_get():
    """Sources déduites (patch + preset courant + clic), niveaux du rig, destinations."""
    from . import mixer
    return mixer.summary()


@router.post("/api/mixer")
async def mixer_set(body: dict):
    """Pose un ou plusieurs trims. Persiste (config/mixer.json, état du rig — un recall n'y
    touche pas) et applique À CHAUD via mixer_apply (aucun rebuild).

      {source, db?, mute?}                     une tranche
      {levels: {src: {db?, mute?}, ...}}       un groupe lié — UNE commande pour tout le geste
    """
    from . import mixer
    try:
        if isinstance(body.get("levels"), dict):
            out = mixer.set_levels(body["levels"])
            return {"ok": True, "levels": out}
        src = str(body.get("source") or "")
        if not src:
            return JSONResponse({"error": "source missing"}, status_code=400)
        cur = mixer.set_level(src, body.get("db"), body.get("mute"))
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "source": src, **cur}


# ── pédalier : quel appareil, et comment on le charge ────────────────────────
# Contrat docs/pedalboards.md. L'écran ne connaît AUCUN modèle : il lit ce que le descripteur
# de l'appareil actif déclare, et déclenche « charge » sans savoir quelle recette tourne.
# le Python du venv : `.venv/bin/python` n'existe pas sous Windows (`.venv\Scripts\python.exe`) — les
# recettes partaient en FileNotFoundError (2026-10-03)
_PY = os.path.join(C.ROOT, ".venv", "Scripts", "python.exe") if sys.platform == "win32" \
    else os.path.join(C.ROOT, ".venv", "bin", "python")


@router.get("/api/pedalboard")
async def pedalboard_get():
    """L'appareil actif, l'intention, les capacités, et les appareils connus.

    `active.source` vaut `measured` (la puce s'est identifiée, avec firmware et série) ou
    `declared` (personne n'a répondu, on retient ce qui est coché). L'écran DOIT montrer la
    différence : confondre une mesure et une déclaration fait chercher la panne au mauvais étage.
    """
    from . import pedalboard, foot
    out = pedalboard.summary()
    # COMMENT la puce se charge SUR CETTE MACHINE (décision 2026-10-02) : sous Linux le rack
    # compile et envoie lui-même ; sous Windows et macOS l'utilisateur colle le setup texte dans le
    # logiciel officiel (Control Center), qui le compile et l'envoie — GoleM rend alors le port.
    # 2026-10-03 : Windows envoie lui aussi par le fil (_flash_uno2_native) ; Control Center reste le
    # secours à l'écran. macOS garde l'éditeur tant que le chemin natif n'y a pas été joué — l'écran offre
    # l'envoi direct en un geste (même _flash_uno2_native, par CoreMIDI), pour que la recette le joue.
    out["load_mode"] = "editor" if sys.platform == "darwin" else "wire"
    out["ports_held"] = foot.ports_held()
    out["os"] = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    return out


# ── Windows / macOS : le setup UnO2 en TEXTE, pour le logiciel officiel ─────────────────────────
def _uno2_text():
    sys.path.insert(0, os.path.join(C.ROOT, "tools", "fcb"))
    import uno2_text
    return uno2_text


@router.get("/api/pedalboard/setup-text")
async def pedalboard_setup_text():
    """Le texte à coller dans FCB UnO Control Center — décompilé du MÊME setup que le binaire du flash
    Linux, et vérifié avant d'être servi (relu, il doit redonner ce binaire au bit près ; ASCII seul).
    Un texte qui échoue à cette vérification n'est PAS servi : coller un setup faux, c'est un pédalier
    qui ment au rack (tools/fcb/uno2_text.py)."""
    try:
        ut = _uno2_text()
        text, binary, setup, device = await asyncio.get_running_loop().run_in_executor(
            None, lambda: ut.current(time.strftime("%Y-%m-%d %H:%M")))
        problems = ut.check(text, binary)
    except Exception as e:
        return JSONResponse({"error": f"cannot build the setup: {e}"}, status_code=500)
    if problems:
        return JSONResponse({"error": "the setup text failed its own check: " + "; ".join(problems)}, status_code=500)
    import uno2
    return {"text": text, "device": device["id"], "bytes": len(binary),
            "used": uno2.setup_length(setup), "budget": uno2.BUDGET,
            "banks": [b.name for b in setup.banks]}


@router.post("/api/pedalboard/hold")
async def pedalboard_hold(body: dict):
    """{on: true|false} — rendre ou reprendre les ports MIDI du pédalier (entrée ET sortie). Sous
    Windows un port ne s'ouvre qu'une fois : sans ça, Control Center ne peut pas parler à la puce
    tant que GoleM tourne. Se lève tout seul au bout de 15 min (foot.HOLD_MAX_S)."""
    from . import foot, midi_out
    on = bool(body.get("on"))
    midi_out.hold(on)
    held = foot.hold_ports(on)
    return {"ok": True, "ports_held": held, "auto_release_s": foot.HOLD_MAX_S if held else None}


@router.post("/api/pedalboard/flashed")
async def pedalboard_flashed():
    """« I flashed it » — l'utilisateur a envoyé le setup par Control Center. On écrit ce que le flash
    Linux écrit après l'accusé de la puce (presets/.uno2-flashed.json, par LA MÊME fonction) : le rack
    y lit quels switches de la rangée des scènes envoient un état. ⚠ C'est une DÉCLARATION de
    l'utilisateur, pas un accusé de la puce : l'écran le dit, et propose le test au pied."""
    try:
        sys.path.insert(0, os.path.join(C.ROOT, "tools", "fcb"))
        import flash_uno2
        import gen_uno2_syx as gen
        import uno2
        contract, device = gen.load()
        loops = gen.looper_slots_from_setlist()
        claims = gen.claim_slots_from_setlist(contract)
        syx = uno2.to_sysex(uno2.build_binary(gen.build(contract, device, looper_slots=loops, claim_slots=claims)))
        flash_uno2._remember_flash(syx, loops, claims)
        doc = _read_json(os.path.join(C.PRESETS_DIR, ".uno2-flashed.json"), {}) or {}
        doc["source"] = "editor"
        store._write_json_atomic(os.path.join(C.PRESETS_DIR, ".uno2-flashed.json"), doc, indent=1)
    except Exception as e:
        return JSONResponse({"error": f"cannot record the flash: {e}"}, status_code=500)
    # le flash est fini : on reprend le pédalier ICI, pas dans l'écran (un onglet fermé entre les deux
    # laisserait le rack sourd jusqu'au délai de 15 min)
    from . import foot, midi_out
    midi_out.hold(False)
    foot.hold_ports(False)
    return {"ok": True, "recorded": doc, "ports_held": False}


@router.post("/api/pedalboard/detect")
async def pedalboard_detect():
    """Rejoue la sonde d'identité. Rend le résumé — `active.source` dit ce qu'elle a donné.

    ⚠ Un échec n'est PAS une erreur : la 1.0.4 ne répond à rien. Le silence élimine la UnO2,
    il n'identifie personne."""
    from . import pedalboard
    hit = await asyncio.get_running_loop().run_in_executor(None, pedalboard.probe)
    out = pedalboard.summary()
    out["probed"] = bool(hit)
    return out


@router.post("/api/pedalboard/select")
async def pedalboard_select(body: dict):
    """Déclare l'appareil branché à la main (efface la sonde : une déclaration explicite prime)."""
    from . import pedalboard
    try:
        pedalboard.select(str(body.get("id") or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return pedalboard.summary()


# ── écoute : apprendre un pédalier qu'on ne programme pas ────────────────────
# Le cas GÉNÉRAL, contrairement aux deux FCB. Les docs constructeur (contrat §8 bis) sont
# formelles : un ENGL Z9 ou un Diezel Columbus n'émettent QUE des Program Change — ni Note
# d'identité, ni front de relâchement, ni CC. On ne les configurera jamais ; on apprend ce
# qu'ils envoient et on leur donne un rôle.
@router.post("/api/pedalboard/learn/start")
async def learn_start():
    """Ouvre l'écoute. ⚠ Le pédalier CESSE de piloter le rig pendant ce temps — sans ça,
    appuyer sur un switch pour le déclarer changerait le morceau sous les doigts."""
    from . import foot
    foot.learn_start()
    return {"ok": True, "learning": True}


@router.get("/api/pedalboard/learn/live")
async def learn_live():
    """Le dernier événement vu, et le résumé de tout ce qui est passé.

    Le résumé porte l'information qui évite une question à l'utilisateur : un switch envoie
    deux valeurs (127 puis 0), une pédale d'expression en balaie trente. On peut donc deviner
    le rôle au lieu de le demander.
    """
    from . import foot
    return foot.learn_state()


@router.post("/api/pedalboard/learn/stop")
async def learn_stop():
    from . import foot
    foot.learn_stop()
    return {"ok": True, "learning": False}


@router.post("/api/pedalboard/learn/save")
async def learn_save(body: dict):
    """Écrit le descripteur appris et l'active — à partir de là, le pédalier pilote le rack.

    body = {name, channel, bindings:[{event:{type,channel,number}, intent:{...}}], edges?}
    """
    from . import pedalboard, foot
    bindings = body.get("bindings") or []
    if not bindings:
        return JSONResponse({"error": "no binding learned — nothing to save"}, status_code=400)
    try:
        slug = pedalboard.save_learned(
            name=str(body.get("name") or "").strip(),
            bindings=bindings,
            channel=int(body.get("channel", 1)),
            edges=bool(body.get("edges", True)),
            notes=body.get("note"))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    foot.learn_stop()                                # l'écoute se ferme : l'appareil reprend la main
    return {"ok": True, "id": slug, **pedalboard.summary()}


@router.post("/api/pedalboard/goto")
async def pedalboard_goto(body: dict):
    """Envoie le pédalier sur une bank — banc de mesure, et secours si le rack et le pied ont
    divergé.

    Sert surtout à trancher `goto_bank.index_base` du descripteur : l'afficheur de la UnO2 compte
    depuis 1 alors que le contrat rack compte depuis 0, et rien ne dit lequel des deux la puce
    attend. Demander la bank 3 puis LIRE l'afficheur répond en une seconde ; c'est le genre de
    question qu'aucun manuel ne tranche et qu'on ne devine pas.
    """
    from . import pedalboard
    try:
        slot = int(body.get("slot"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "slot missing or not an integer"}, status_code=400)
    caps = ((pedalboard.active()["device"].get("capabilities") or {}).get("goto_bank") or {})
    if not caps.get("supported"):
        return JSONResponse({"error": "this device cannot receive a bank change"},
                            status_code=400)
    sent = pedalboard.goto_bank(slot)
    return {"ok": sent, "slot": slot,
            "sent_value": slot + int(caps.get("index_base", 0)),
            "controller": int(caps.get("controller", 0)), "channel": caps.get("channel")}


# ── recettes de charge (contrat docs/pedalboards.md §2 et §10) ──────────────────────────────
# Le descripteur DÉCLARE sa recette (`load.recipe`), cette table la RÉSOUT : un appareil neuf =
# un descripteur + une entrée ici — plus jamais un `if` par appareil dans la route.
# ⚠ Une recette est du CODE DE CONFIANCE : le descripteur ne choisit qu'un NOM de cette table.
# Lui laisser porter une commande, c'est laisser un fichier importé faire exécuter n'importe
# quoi au rack. Le vocabulaire est répliqué dans tools/check-descriptors.py (RECIPES).

def _flash_uno2_native(device_id):
    """Windows / macOS (2026-10-03, « code le flash UNO2 ») : le MÊME dialogue que
    tools/fcb/flash_uno2.py — identification, refus si ce n'est pas une UnO2, dump, accusés 7C/7F,
    mémoire du flash — mais DANS le bridge. Un second processus ne pourrait pas ouvrir les prises :
    sous WinMM une prise MIDI n'a qu'un seul propriétaire, et c'est déjà le bridge (sortie : midi_out,
    entrée : le lecteur du pied, auquel on s'abonne pour les SysEx comme la sonde d'identité).
    Rend (ok, journal, http)."""
    import contextlib as _cl
    import io
    from . import foot, midi_out
    sys.path.insert(0, os.path.join(C.ROOT, "tools", "fcb"))
    import flash_uno2 as F
    import gen_uno2_syx as gen
    import uno2

    contract, dev = gen.load(gen.CONTRACT, device_id)
    loops = gen.looper_slots_from_setlist()
    claims = gen.claim_slots_from_setlist(contract)
    setup = gen.build(contract, dev, looper_slots=loops, claim_slots=claims)
    used = uno2.setup_length(setup)
    syx = uno2.to_sysex(uno2.build_binary(setup))
    if used > uno2.BUDGET:
        return False, f"setup too large for the chip ({used} / {uno2.BUDGET} bytes) — nothing sent", 409
    if midi_out.held():
        return False, "the pedalboard ports are lent to another program (Control Center) — take them back first", 409
    stream = foot.native_sysex_stream()
    if stream is None:
        return False, ("the pedalboard MIDI input is not connected — choose it in Settings ▸ Gear ▸ Soundcard ▸ MIDI "
                       "(and restart REAPER if it still holds the port)"), 409

    class _BridgeMidi(F.Midi):
        """Les prises du bridge derrière l'interface de flash_uno2.Midi (send / await_reply / close)."""
        def __init__(self):                      # noqa — pas d'ouverture : les prises sont déjà là
            self.inp, self.out = stream, None
            self.out_name = midi_out.find_port() or "?"

        def send(self, data):
            if not midi_out.send_sysex(bytes(data)):
                raise RuntimeError("MIDI OUT unavailable — nothing reached the pedalboard")

        def close(self):
            stream.close_port()

    out = io.StringIO()
    ok = False
    midi = _BridgeMidi()
    try:
        with _cl.redirect_stdout(out):
            print("MIDI ports: output %s · input (pedalboard reader)" % midi.out_name)
            info = F.identify(midi)
            if info is None:
                return False, out.getvalue().strip() or "no answer from the pedalboard", 502
            if info["device"] != F.DEVICE_UNO2:
                print("  Not a UnO2 chip — nothing written.")
                return False, out.getvalue().strip(), 409
            print("Writing: %d bytes" % len(syx))
            ok = F.flash(midi, syx)
            if ok:
                F._remember_flash(syx, loops, claims)
    except Exception as e:
        return False, (out.getvalue() + "\n✗ " + str(e)).strip(), 500
    finally:
        midi.close()
    return ok, out.getvalue().strip(), (200 if ok else 502)


async def _load_recipe_uno2(act):
    """Compile l'intention et l'envoie par le fil, avec identification préalable et accusés
    lus (tools/fcb/flash_uno2.py — contrat docs/fcb/uno2/README.md)."""
    if sys.platform in ("win32", "darwin"):
        ok, log_text, status = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _flash_uno2_native(act["id"]))
        if not ok:
            return JSONResponse({"error": log_text[-600:] or "flash failed"}, status_code=status)
        return {"ok": True, "device": act["id"], "confirmed": True, "log": log_text}
    tool = os.path.join(C.ROOT, "tools", "fcb", "flash_uno2.py")
    try:
        r = await asyncio.get_running_loop().run_in_executor(
            None, lambda: subprocess.run([_PY, tool, "--write", "--device", act["id"]],
                                         capture_output=True, text=True, timeout=60))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return JSONResponse({"error": out.strip()[-400:] or "flash failed"}, status_code=500)
    return {"ok": True, "device": act["id"], "confirmed": True, "log": out.strip()}


async def _load_recipe_uno104(act):
    """Régénère le dump figé (2352 o) et l'envoie — la puce ne confirme rien, et les réglages
    globaux restent À FAIRE AU PIED (elle ignore les octets globaux du fil)."""
    from . import midi_out
    gen = os.path.join(C.ROOT, "tools", "fcb", "gen_golem_syx.py")
    syx = os.path.join(C.ROOT, "mappings", "fcb1010-golem.syx")
    try:
        r = await asyncio.get_running_loop().run_in_executor(
            None, lambda: subprocess.run([_PY, gen], capture_output=True, text=True, timeout=15))
        if r.returncode != 0:
            return JSONResponse({"error": ".syx generation failed: " + (r.stderr or r.stdout).strip()[:300]},
                                status_code=500)
        data = open(syx, "rb").read()
        if not midi_out.send_sysex(data):
            return JSONResponse({"error": "MIDI send failed (Volt port missing?)"}, status_code=500)
        # Cette puce n'accuse RIEN : « envoyé » n'est pas « reçu ». C'est l'écran du FCB qui
        # tranche, et la procédure le dit — d'où confirmed=false, qui n'est pas un échec.
        return {"ok": True, "device": act["id"], "confirmed": False,
                "bytes": len(data), "port": midi_out.find_port()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


_LOAD_RECIPES = {"uno2": _load_recipe_uno2, "uno104": _load_recipe_uno104}


@router.post("/api/pedalboard/load")
async def pedalboard_load():
    """Charge l'intention GoleM dans le pédalier actif, par SA recette (load.recipe du
    descripteur, résolue dans _LOAD_RECIPES).

    Une recette inconnue — ou absente : un appareil appris déclare `load: none` — est refusée
    plutôt que devinée : envoyer le mauvais dump à une puce est exactement le genre d'erreur
    qui ne se voit qu'en jouant.
    """
    from . import pedalboard
    act = pedalboard.active()
    recipe = (act["device"].get("load") or {}).get("recipe")
    run = _LOAD_RECIPES.get(recipe)
    if run is None:
        return JSONResponse({"error": "device \"%s\" declares no known load recipe "
                                      "(got: %r; known: %s)"
                             % (act["id"], recipe, ", ".join(sorted(_LOAD_RECIPES)))},
                            status_code=400)
    return await run(act)


@router.post("/api/fcb/flash")
async def fcb_flash():
    """Alias historique de /api/pedalboard/load — gardé le temps que les appelants migrent."""
    return await pedalboard_load()


PERF_HINT = "passwordless sudo not set up — run ./provision/setup-perf-sudo.sh once"


def apply_perf(on):
    """Bascule le gouverneur CPU (performance/powersave) via provision/perf-mode.sh, en sudo -n.
    Synchrone (≤ 15 s) : appelé par la route ET par la bascule de mode (modes.perf_boost).
    Rend (ok, sortie). Nécessite la règle sudoers NOPASSWD (provision/golem-perf.sudoers)."""
    if sys.platform == "win32":                       # Windows : le plan « Performance », sans droits
        from . import desktop_power
        return desktop_power.set_boost(on)
    if sys.platform != "linux":
        return False, "CPU boost is not available on this computer yet"
    script = "/usr/local/sbin/golem-perf-mode"        # copie root-owned (S-P1-4)
    if not os.path.exists(script):
        script = os.path.join(C.ROOT, "provision", "perf-mode.sh")   # repli dev (setup non joué)
    try:
        r = subprocess.run(["sudo", "-n", script, "on" if on else "off"],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return False, str(e)


def apply_perf_for_mode(mode, why=""):
    """Le boost SUIT LE MODE (2026-09-08) : Gig et Show l'allument, les autres l'éteignent.
    Jamais fatal — sans règle sudo, on le DIT une fois par bascule, et le bouton ⚡ reste là."""
    if sys.platform not in ("linux", "win32"):
        return None
    from . import modes as _modes
    want = _modes.perf_boost(mode)
    gov = _cpu_governor()
    if gov is None:
        return None                                    # pas de cpufreq (VM) : rien à faire
    if (gov == "performance") == want:
        return True                                    # déjà dans l'état voulu : pas de sudo pour rien
    ok, out = apply_perf(want)
    if ok:
        log.info(f"boost CPU {'ON' if want else 'OFF'} — mode « {(mode or {}).get('name')} »{why}")
    else:
        log.warning(f"boost CPU {'ON' if want else 'OFF'} NON appliqué (mode « {(mode or {}).get('name')} ») : {out or PERF_HINT}")
    return ok


@router.get("/api/app-build")
def app_build():
    """La « version » de l'app servie = la date (s) du fichier le plus récent de app/. La page la
    compare à celle qu'elle a chargée : si elle change, bandeau « New version — tap to reload ».
    POURQUOI (2026-09-08) : la fenêtre du rack (golem desktop) ne recharge JAMAIS ; trois fois
    dans la journée un correctif livré a été déclaré « ça ne marche toujours pas » depuis une page
    qui tournait avec le JS d'avant. Scandir léger, appelé toutes les 20 s par page ouverte."""
    root = os.path.join(C.ROOT, "app")
    newest = 0
    try:
        for e in os.scandir(root):
            if e.is_file() and e.name.endswith((".js", ".css", ".html")):
                newest = max(newest, int(e.stat().st_mtime))
    except OSError:
        pass
    return {"build": newest}


@router.post("/api/perf-mode")
async def perf_mode(body: dict):
    """Bascule manuelle du gouverneur CPU (bouton ⚡ du dashboard) — sinon ok=False + hint."""
    if sys.platform not in ("linux", "win32"):
        return JSONResponse({"error": "CPU boost is not available on this computer yet"}, status_code=501)
    on = bool(body.get("on"))
    ok, out = await asyncio.get_running_loop().run_in_executor(None, apply_perf, on)
    return {"ok": ok, "governor": _cpu_governor(), "output": out,
            "hint": None if ok or sys.platform == "win32" else PERF_HINT}   # Windows : pas de sudo, le message dit tout


# ── santé machine pour le Dashboard (3e rangée de cards — 2026-07-24) ──
@router.get("/api/system/health")
def system_health():
    """Golem CPU / RAM / état du process Reaper — pollé par le Dashboard (léger, sans psutil).
    cpu_pct réutilise la sonde /proc/stat de rigstatus (2 échantillons, ~250 ms)."""
    from . import rigstatus
    out = {"cpu_pct": rigstatus.cpu_pct(), "temp_c": rigstatus.temp_c(), "ram": rigstatus.ram()}
    reap = {"running": False}
    if sys.platform == "win32":
        import csv
        try:
            raw = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe", "/FO", "CSV", "/NH"],
                                 capture_output=True, check=True, timeout=3).stdout
            decoded = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "ascii",
                                 errors="replace")
            row = next((r for r in csv.reader(decoded.splitlines()) if len(r) >= 5 and
                        r[0].lower() == "reaper.exe"), None)
            if row:
                memory_kb = int("".join(c for c in row[4] if c.isdigit()) or "0")
                reap = {"running": True, "pid": int(row[1]),
                        "rss_mb": round(memory_kb / 1024), "uptime_s": None}
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            _swallowed(e)
        out["reaper"] = reap
        return out
    if sys.platform == "darwin":
        # le process s'appelle « REAPER » sur un Mac, et /proc n'existe pas : le chemin Linux ci-dessous
        # aurait affiché « not running » devant un moteur qui joue (docs/platforms.md, M1)
        from . import desktop_macos, monitors
        pid = monitors._reaper_pid()
        if pid is not None:
            reap = {"running": True, "pid": pid, **(desktop_macos.process_info(pid) or {})}
        out["reaper"] = reap
        return out
    try:
        pid = subprocess.run(["pgrep", "-x", "-o", "reaper"], capture_output=True, text=True,
                             timeout=3).stdout.split()
        if pid:
            pid = int(pid[0])
            reap["running"] = True
            reap["pid"] = pid
            with open(f"/proc/{pid}/statm") as f:                 # RSS en pages -> Mo
                reap["rss_mb"] = round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6)
            up = float(open("/proc/uptime").read().split()[0])    # uptime process via starttime (ticks)
            start_ticks = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19])
            hz = os.sysconf("SC_CLK_TCK")
            reap["uptime_s"] = int(up - start_ticks / hz)
            reap["threads"] = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[17])
    except Exception as _e:
        _swallowed(_e)
    out["reaper"] = reap
    return out


# ── accès distant (Sprints 3.1+3.5 — SECURITY.md) : appareils nommés + invitations ──
@router.get("/api/auth/devices")
def auth_devices():
    """Appareils autorisés + invitations en attente (SANS tokens). GET SENSIBLE."""
    from . import auth as auth_mod
    return auth_mod.list_devices()


@router.post("/api/auth/devices")
async def auth_device_create(body: dict):
    """Crée une INVITATION taguée (rôle × type) -> son QR l'échange au 1er scan."""
    from . import auth as auth_mod
    r = auth_mod.create_invite(body.get("role"), body.get("kind"), person=body.get("person"),
                               guest=body.get("guest"), days=body.get("days"))
    if r.get("error"):
        return JSONResponse(r, status_code=400)
    return r


@router.delete("/api/auth/devices/{did}")
def auth_device_remove(did: str):
    """Révoque UN appareil (ou annule une invitation) — les autres ne bougent pas."""
    from . import auth as auth_mod
    if not auth_mod.remove(did):
        return JSONResponse({"error": "unknown device"}, status_code=404)
    return {"ok": True}


@router.post("/api/auth/promote")
def auth_promote(body: dict):
    """Promeut (ou rétrograde) un appareil ADMIN — audit 2026-08-12, M-1. Le middleware
    réserve déjà cette route aux admins : depuis l'écran du rack (localhost), ou depuis un
    appareil déjà promu. Un rack neuf n'a AUCUN admin : la première promotion se fait
    debout devant la machine, comme l'appairage."""
    from . import auth as auth_mod
    if not auth_mod.set_admin(body.get("id"), bool(body.get("admin", True))):
        return JSONResponse({"error": "unknown device"}, status_code=404)
    return auth_mod.list_devices()


@router.get("/api/auth/whoami")
def auth_whoami(request: Request):
    """Qui me parle ? — l'appareil ne voit que SA fiche (routage Golem Companion :
    kind=Phone -> /app/m.html). GET libre : sans token valide, device=None."""
    from . import auth as auth_mod
    client = request.client.host if request.client else ""
    # `token` (docs/devices-people.md, lot B) : « unknown » = un jeton présenté que le rack ne reconnaît
    # plus — l'app affiche « this device is no longer paired » au lieu de s'ouvrir figée
    return {"local": auth_mod._is_local(client), "device": auth_mod.device_of(request),
            "token": auth_mod.token_state(request)}


@router.post("/api/auth/devices/{did}/person")
def auth_device_person(did: str, body: dict):
    """QUI utilise cet appareil (docs/devices-people.md, lot A) — sans rescanner. Réservé au rack et aux admins."""
    from . import auth as auth_mod
    r = auth_mod.set_person(did, person=body.get("person"), guest=body.get("guest"), days=body.get("days"))
    if r.get("error"):
        return JSONResponse(r, status_code=404 if r["error"] == "unknown device" else 400)
    return auth_mod.list_devices()


@router.post("/api/auth/conductor")
def auth_conductor(body: dict):
    """Accorde (ou retire) le droit CONDUCTOR à un appareil : charger, lancer, arrêter les morceaux et la
    prise depuis un téléphone (docs/devices-people.md, lot F). Réservé à l'écran du rack et aux admins."""
    from . import auth as auth_mod
    if not auth_mod.set_conductor(body.get("id"), bool(body.get("conductor", True))):
        return JSONResponse({"error": "unknown device"}, status_code=404)
    return auth_mod.list_devices()


@router.post("/api/auth/extend")
def auth_extend(body: dict):
    """Prolonge l'accès d'un invité : `days` (1, 7, 30 — le geste de l'écran) ou `hours`.
    Réservé à l'écran du rack et aux admins."""
    from . import auth as auth_mod
    if not auth_mod.extend(body.get("id"), body.get("hours") or 24, days=body.get("days")):
        return JSONResponse({"error": "unknown device"}, status_code=404)
    return auth_mod.list_devices()


# ── le premier écran d'un rack sans écran (docs/devices-people.md, lot C) ─────────────────────────
@router.post("/api/auth/pair-code")
def auth_pair_code():
    """Un code à six chiffres, 10 min, usage unique (local ou admin : `golem pair`, Remote devices)."""
    from . import auth as auth_mod
    return auth_mod.create_pair_code()


@router.get("/api/auth/pair")
def auth_pair_status():
    """La page d'appairage demande seulement si un code attend — jamais le code."""
    from . import auth as auth_mod
    return {"pending": auth_mod.pair_code_pending() is not None}


@router.post("/api/auth/pair")
async def auth_pair(request: Request):
    """Échange le code d'appairage contre un appareil « Rack screen » (tablette, admin). Ouverte sans
    token comme /api/auth/claim : le code est le secret, à usage unique, 10 essais au plus."""
    from . import auth as auth_mod
    try:
        body = await request.json() or {}
    except Exception:
        body = {}
    got = auth_mod.claim_pair(body.get("code"), ua=request.headers.get("user-agent", ""),
                              ip=request.client.host if request.client else "")
    if not got:
        return JSONResponse({"error": "wrong or expired code — run `golem pair` on the rack for a new one"}, status_code=410)
    return got


@router.post("/api/take/flag")
async def perf_flag(request: Request):
    """« Mark that » (Companion ▸ Rec) : marqueur horodaté dans le take EN COURS.
    (/api/take/* — PAS /api/perf/* : ce chemin est capturé par /api/perf/{action} de routes_content.)
    Refusé hors enregistrement (409) — le bouton n'a de sens que pendant la prise."""
    from . import auth as auth_mod, monitors
    perf = getattr(state, "perf", None) or {}
    if not perf.get("recording"):
        return JSONResponse({"error": "not recording"}, status_code=409)
    dev = auth_mod.device_of(request)
    sec = None
    with contextlib.suppress(Exception):
        t0 = time.mktime(time.strptime(perf.get("started_at", ""), "%Y-%m-%dT%H:%M:%S"))
        sec = round(time.time() - t0, 1)
    monitors.PERF_FLAGS.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sec": sec,
                                "by": (dev or {}).get("role") or "local",
                                # la PERSONNE (id du groupe, docs/devices-people.md lot A) : « le mainteneur · solo » sur golem.fm
                                **({"person": dev["person"]} if (dev or {}).get("person") else {}),
                                # …et OÙ dans le set : le morceau et la partie qui jouaient (lot F)
                                "song": ((getattr(state, "song", None) or {}).get("title")) or getattr(state, "preset_name", None),
                                "part": ((getattr(state, "arrangement", None) or {}).get("name"))})
    return {"ok": True, "count": len(monitors.PERF_FLAGS)}


@router.get("/api/take/flags")
def perf_flags_list(request: Request):
    """Les marques de la prise EN COURS (Companion ▸ Rec). `mine` = celles de l'appareil qui demande."""
    from . import auth as auth_mod, monitors
    dev = auth_mod.device_of(request) or {}
    rows = list(monitors.PERF_FLAGS)
    return {"flags": rows, "mine": [f for f in rows if dev.get("person") and f.get("person") == dev.get("person")]}


@router.post("/api/auth/claim")
async def auth_claim(request: Request):
    """Échange invitation -> token d'appareil (appelé par le bootstrap de l'app au 1er scan).
    SEULE route auth ouverte sans token : l'invitation elle-même est le secret, à usage unique.
    Capture la fiche appareil au passage (User-Agent -> modèle, IP -> MAC)."""
    from . import auth as auth_mod
    try:
        body = await request.json() or {}
    except Exception:
        body = {}
    got = auth_mod.claim(body.get("invite"),
                         ua=request.headers.get("user-agent", ""),
                         ip=request.client.host if request.client else "")
    if not got:
        return JSONResponse({"error": "invite unknown or already used — ask for a new QR"}, status_code=410)
    return got


@router.get("/api/auth/qr")
def auth_qr(invite: str = ""):
    """QR d'UNE invitation : encode http://<ip>:8770/app/?auth=<token-invitation>.
    GET SENSIBLE (dans auth.SENSITIVE_GET) : local ou appareil déjà autorisé seulement."""
    from . import auth as auth_mod
    tok = auth_mod.invite_token(invite)
    if not tok:
        return JSONResponse({"error": "unknown or already claimed invite"}, status_code=404)
    # l'adresse de la ROUTE PAR DÉFAUT, jamais un pont Docker/libvirt (docs/connect.md §0 : `hostname -I`
    # rendait sa première adresse, la bonne par chance). Point d'accès levé : le NOM du rack, que son DNS
    # sert (R2) — le jeton se range sous l'origine qui suivra le téléphone de la scène à la répète.
    from . import connect as connect_mod, reach as reach_mod
    addr = connect_mod.addresses()
    # golem.local d'abord (2026-10-03, bridge/reach.py) : le JETON se range sous l'ORIGINE de l'URL — un
    # téléphone appairé sur 192.168.0.22 ne l'était plus sur golem.local, ni sur l'IP du point d'accès. Un
    # seul nom, la maison et la scène, et le raccourci de l'écran d'accueil reste appairé partout.
    rs = reach_mod.status()
    host = rs["host"] if rs.get("mdns") else (connect_mod.mdns_host() if addr["ap"] else None)
    ip = host or addr["primary"]
    if not ip:
        return JSONResponse({"error": "no LAN address"}, status_code=404)
    url = f"http://{ip}:{connect_mod.PORT}/app/?auth={tok}"
    try:
        import qrcode
        import qrcode.image.svg
        import io
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
        buf = io.BytesIO()
        img.save(buf)
        from fastapi.responses import Response
        return Response(content=buf.getvalue(), media_type="image/svg+xml")
    except ImportError:
        return JSONResponse({"error": "qrcode module missing (run bridge-setup.sh)"}, status_code=501)


@router.post("/api/auth/revoke")
def auth_revoke():
    """Panique : révoque TOUS les appareils + invitations — les kiosks locaux ne bougent pas."""
    from . import auth as auth_mod
    auth_mod.revoke()
    return {"ok": True}


# ── bibliothèques embarquées : le manifeste + ce qui est vraiment installé ───────────────
@router.get("/api/system/libraries")
def system_libraries():
    """System ▸ Licences ▸ Libraries (docs/installer.md §5) : provision/components.json confronté à
    la machine (dpkg, venv, fichiers) — dire ce qu'on embarque ET s'il est là."""
    from . import libraries
    rep = libraries.report()
    # les moteurs de séparation installés DEPUIS LA LISTE de golem.fm : leur attribution est une obligation de
    # licence (docs/separation.md §2.1) — jamais un moteur ajouté à la main (on ne nomme aucun moteur tiers, §1)
    try:
        from . import separation
        extra = separation.attributions()
    except Exception:
        extra = []
    if extra:
        rep = {**rep, "components": list(rep.get("components") or []) + extra}
    return rep
