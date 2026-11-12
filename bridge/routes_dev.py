# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes DEV (rig_recall de test + outils fxprobe/namtest/loadtest/chunkdump/fxdump/projreload)
— extrait d'app.py (P3). Exécutées par golem_watch -> golem_apply/golem_rig."""
import os, json, contextlib, subprocess, sys, time, asyncio

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from . import config as C
from .commands import write_command
from .golog import get

log = get("ui")
from .store import _safe_id

router = APIRouter()


@router.post("/api/rig_recall")
async def rig_recall(request: Request):
    """TEST du nouveau modèle (paths+splits) : compile le preset -> <id>.rig.json puis déclenche golem_rig.
    Accepte ?preset= OU un body json {preset}. Charge depuis presets/ ou docs/examples/."""
    pid = request.query_params.get("preset")
    if not pid:
        with contextlib.suppress(Exception):
            pid = (await request.json() or {}).get("preset")
    if not pid:
        return JSONResponse({"error": "preset requis (?preset=… ou body json {preset})"}, status_code=400)
    pid = _safe_id(pid)                      # S-P2-2 : anti path-traversal
    src = os.path.join(C.PRESETS_DIR, f"{pid}.json")
    if not os.path.exists(src):
        src = os.path.join(C.ROOT, "docs", "examples", f"{pid}.json")
    if not os.path.exists(src):
        return JSONResponse({"error": f"preset {pid} introuvable"}, status_code=404)
    try:
        preset = json.load(open(src))
    except Exception as e:
        return JSONResponse({"error": f"{pid}.json illisible : {e}"}, status_code=400)
    try:
        from . import compile_rig
        compile_rig.compile_preset(preset)
    except Exception as e:
        return JSONResponse({"error": f"compile: {e}"}, status_code=400)
    write_command({"action": "rig_recall", "preset": pid})
    return {"ok": True, "preset": pid}


@router.post("/api/loadtest")
async def loadtest(body: dict):
    write_command({"action": "loadtest", "file": body.get("file"), "template": body.get("template"), "ir": body.get("ir")})
    return {"ok": True}


@router.post("/api/chunkdump")
async def chunkdump(body: dict):
    write_command({"action": "chunkdump", "track": body.get("track"), "find": body.get("find")})
    return {"ok": True}


@router.post("/api/namtest")
async def namtest(body: dict):
    """TEST (dev) : charge un .nam in-session dans un plugin -> presets/.fxprobe.log. Aucun reload."""
    write_command({"action": "namtest", "plugin": body.get("plugin"),
                   "file": body.get("file"), "uri": body.get("uri")})
    return {"ok": True}


@router.post("/api/projreload")
async def projreload():
    """Sauve + rouvre le projet Reaper -> recharge les fichiers NAM/IR (project-open). Prend qq secondes."""
    write_command({"action": "projreload"})
    return {"ok": True}


@router.post("/api/fxprobe")
async def fxprobe(body: dict):
    """SONDE (dev) : teste le chargement d'un fichier dans un plugin -> presets/.fxprobe.log.
    body: {plugin, file, keys:[...]}. Passe par golem_apply (dofile à chaud, pas de restart Reaper)."""
    write_command({"action": "fxprobe", "plugin": body.get("plugin"),
                   "file": body.get("file"), "keys": body.get("keys") or []})
    return {"ok": True}


@router.post("/api/peaks")
async def peaks(body: dict = None):
    """PEAKS (dev, bug volume) : peak-hold dB de chaque piste + Master -> presets/.peaks.json.
    body {clear: true} = remise à zéro des peak-holds (protocole clear -> jouer -> relire)."""
    write_command({"action": "peaks", "clear": bool((body or {}).get("clear"))})
    return {"ok": True, "file": "presets/.peaks.json"}


@router.post("/api/fxdump")
async def fxdump():
    """Outil de calibration : demande à golem_apply de relever tous les params réels des FX
    (noms + index + valeurs/min/max) dans presets/.fxdump.json. Recall d'abord un preset."""
    write_command({"action": "dumpfx"})
    return {"ok": True, "file": "presets/.fxdump.json"}


# (l'ancien /api/io/profile — bascule de profil de lieu — est supprimé : le routage vit dans le Designer)


# ── Meters temps réel (tiroirs P3 — feuilles gate/comp/limiter) ──
# POST {block:id} : résout piste+fx via la livemap et ARME la boucle golem_apply (auto-désarmée
# 10 s après le dernier arm ; le navigateur ré-arme toutes les 4 s tant que la feuille est ouverte).
# GET /read : relit /dev/shm/golem-meters.json (tmpfs, écrit ~30 Hz par Reaper).
@router.post("/api/meters")
async def meters_arm(req: Request):
    body = await req.json()
    bid = str(body.get("block") or "")
    try:
        lm = json.load(open(os.path.join(C.PRESETS_DIR, ".livemap.json")))
    except Exception:
        return JSONResponse({"ok": False, "error": "no livemap"}, status_code=404)
    ent = (lm.get("blocks") or {}).get(bid)
    if not ent:
        return JSONResponse({"ok": False, "error": "block not live"}, status_code=404)
    write_command({"action": "meters", "track": ent.get("track"), "fx": ent.get("fx")})
    return {"ok": True, "track": ent.get("track"), "fx": ent.get("fx")}


@router.get("/api/meters/read")
def meters_read():
    # Un remplacement de fichier de télémétrie Windows peut créer un trou bref.
    try:
        return json.load(open(C.runtime_file("golem-meters.json")))
    except Exception:
        return {}


# ── SONDE DE TROUS (tools/check-scene-gap.py) : un ton continu en queue de la piste `tone`, un
# détecteur golem_gapmeter en queue de chaque piste de `tracks`. {on:false} retire tout.
# GET /read relit /dev/shm/golem-gaps.json (recopié à chaque tick defer par golem_apply).
@router.post("/api/gapmeter")
async def gapmeter(body: dict = Body(...)):
    cmd = {"action": "gapmeter", "on": bool(body.get("on"))}
    for k in ("tone", "tone_head", "db", "hz", "tracks", "thr", "thrs", "min_ms", "hold", "port"):
        if body.get(k) is not None:
            cmd[k] = body[k]
    write_command(cmd)
    return {"ok": True}


@router.post("/api/lcbench")
async def lcbench(body: dict = Body(...)):
    """Banc d'essai SWS LiveConfigs (tools/bench-liveconfigs.py) : relais vers golem_apply."""
    cmd = {"action": "lcbench"}
    for k in ("op", "path", "tracks", "prep"):
        if body.get(k) is not None:
            cmd[k] = body[k]
    write_command(cmd)
    return {"ok": True}


@router.get("/api/gapmeter/read")
def gapmeter_read():
    try:
        return json.load(open(C.runtime_file("golem-gaps.json")))
    except Exception:
        return {}


# ── écho live des potards AKAI (feuilles keys) : golem_knobs publie les CC appliqués dans
# /dev/shm/golem-knobs-live.json (entrées expirées à 2 s côté Lua). La feuille poll et fait
# suivre ses dials — affichage seul.
@router.get("/api/knobs/live")
def knobs_live():
    try:
        rows = json.load(open(C.runtime_file("golem-knobs-live.json")))
    except Exception:
        rows = []
    return {"knobs": rows}


@router.get("/api/knobs/config")
def knobs_config():
    """config/knobs.json (CC des banques + plage du clavier physique) — pour la feuille keys
    (KeyZone v2 : la bande = LES touches du contrôleur, pas un piano 128 notes)."""
    from . import controllers                      # la calibration locale, sinon la graine (2026-10-03)
    return controllers.knobs_config() or {"kb_range": [48, 72]}


# ── CALIBRATION (docs/calibration.md) : MIDI-learn + profils de contrôleurs ──────────────────

@router.get("/api/calibrate/live")
def calibrate_live():
    """Flux learn : dernière note / dernier CC / pitch bend vus par knob-tap (via golem_knobs
    -> /dev/shm/golem-learn.json). Le stepper poll et compare les seq pour détecter le geste."""
    try:
        return json.load(open(C.runtime_file("golem-learn.json")))
    except Exception:
        return {"note": {"seq": 0}, "cc": {"seq": 0}, "pb": {"seq": 0}}


@router.get("/api/drumkits")
def drumkits_list():
    """Les descripteurs de kit de batterie (docs/drums-kit.md §3) + le kit résolu de chaque port USB drums."""
    from . import drumkits, inputmap
    ports = [{"ch": u["ch"], "port": u["port"], "device": u.get("device"), "kit": u.get("kit")}
             for u in inputmap.usb_ports() if u.get("role") == "drums"]
    return {"kits": drumkits.listing(), "ports": ports, "elements": list(drumkits.ELEMENTS)}


@router.get("/api/controllers")
def controllers_list():
    """Contrôleurs MIDI USB branchés + leur profil de calibration (None = jamais calibré)."""
    from . import controllers as ctl
    return {"controllers": ctl.listing()}


@router.post("/api/controllers/profile")
async def controllers_save(body: dict):
    """Sauve un profil de calibration et propage aux consommateurs actifs (config/knobs.json).
    golem_knobs est rechargé à chaud pour relire la map (liste blanche reload)."""
    from . import controllers as ctl
    if not (body or {}).get("usb") and not (body or {}).get("name"):
        return JSONResponse({"error": "usb ou name requis"}, status_code=400)
    prof = ctl.save(body)
    write_command({"action": "reload", "script": "golem_knobs"})   # relit knobs.json/knobmap
    return {"ok": True, "profile": prof}


@router.post("/api/calibrate/midi")
async def calibrate_midi(body: dict):
    """Émission MIDI brute vers la pédale (vérification/wizard de mapping) : {pc} ou {cc,val}
    ou {sweep_cc} (balayage 0->127, test de treadle). channel 1 par défaut."""
    from . import midi_out
    body = body or {}
    ch = max(1, min(16, int(body.get("channel") or 1)))
    if body.get("pc") is not None:
        ok = midi_out.program_change(int(body["pc"]) & 0x7F, ch)
    elif body.get("sweep_cc") is not None:
        cc = int(body["sweep_cc"]) & 0x7F
        ok = True
        for v in list(range(0, 128, 4)) + [127, 64, 0]:
            ok = bool(midi_out.control_change(cc, v, ch)) and ok
    elif body.get("cc") is not None:
        ok = midi_out.control_change(int(body["cc"]) & 0x7F, int(body.get("val") or 0) & 0x7F, ch)
    else:
        return JSONResponse({"error": "pc | cc | sweep_cc requis"}, status_code=400)
    return {"ok": bool(ok)}


# ── coquille d'appareil du poste de travail (app/device.html) ────────────────
@router.post("/api/ui/quit")
async def ui_quit(body: dict = Body(default=None)):
    """Ferme la fenêtre de la coquille SANS arrêter golem — « Continue on a tablet » (app/tablet-sheet.js).

    Avec `{"stop": true}` (bouton ⏻) : ferme la fenêtre **ET** arrête le rig — Reaper, le
    lecteur MIDI, puis ce bridge. L'équivalent exact de `golem stop`, sans quitter l'écran.

    ⚠ LA CROIX SYSTÈME, ELLE, ARRÊTE GOLEM DESKTOP (2026-11-08, Windows/macOS : app.stop_if_window_closed) —
    sous Windows, fermer un logiciel par sa croix le ferme. Cette route sans `stop` marque donc la fermeture comme
    VOULUE (machine.window_detached) : la fenêtre part, golem continue pour la tablette. Échap ne ferme plus rien.

    ⚠ POURQUOI DEUX BOUTONS ET PAS UN. Fermer une fenêtre et arrêter le moteur audio sont
    deux intentions différentes. Un ✕ qui couperait le son parce qu'on écarte la coquille
    pendant qu'on joue serait un piège — c'est la même famille d'erreur que le kiosk sans
    échappatoire, à l'envers. Le ✕ ferme, le ⏻ arrête, et le ⏻ demande confirmation.

    Même chemin pour « 📱 Continue on tablet » (sans stop) et pour le « ⏻ Stop GoleM » de System ▸
    Dashboard (avec stop), qui sert l'appareil principal d'un GoleM SERVER, sans fenêtre (docs/installer.md
    §4) : la route est au palier admin (bridge/auth.py), l'ordinateur lui-même passe toujours.

    Pourquoi passer par le bridge : `window.close()` est REFUSÉ par Chrome pour une fenêtre
    qu'un script n'a pas ouverte (constaté le 2026-07-29 — la croix ne faisait rien). Et en
    plein écran, il n'y a plus de bouton système : sans ce chemin, on est enfermé.

    Périmètre volontairement étroit : on ne tue QUE les processus dont la ligne de commande
    porte le profil de navigateur dédié du lanceur (`.../golem/browser`, posé par
    provision/golem). Jamais le navigateur personnel de l'utilisateur.
    """
    import signal
    import subprocess
    if (body or {}).get("stop"):                     # /api/health cesse de dire « ok » : un lanceur attendra la fin
        from .state import state
        state.stopping = True
    else:                                            # fermée EXPRÈS : la croix-arrêt ne s'applique pas
        from . import machine
        machine.window_detached()
    if sys.platform in ("win32", "darwin"):
        return await asyncio.to_thread(_ui_quit_desktop, bool((body or {}).get("stop")))
    profile = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                           "golem", "browser")
    killed = []
    try:
        out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=5).stdout
    except Exception as e:
        return JSONResponse({"error": f"ps: {e}"}, status_code=500)
    for line in out.splitlines():
        line = line.strip()
        pid, _, args = line.partition(" ")
        # le profil doit apparaître TEL QUEL dans --user-data-dir : pas de correspondance floue
        if f"--user-data-dir={profile}" not in args:
            continue
        with contextlib.suppress(Exception):
            os.kill(int(pid), signal.SIGTERM)
            killed.append(int(pid))
    full = bool((body or {}).get("stop"))
    if not killed and not full:
        return JSONResponse({"error": "aucune fenêtre de coquille trouvée"}, status_code=404)
    log.info(f"coquille fermée ({len(killed)} process)")
    if not full:
        return {"ok": True, "killed": len(killed)}

    # ── arrêt complet : mêmes cibles que `golem stop`, dans le même ordre ──────────────
    # Dans un fil : la réponse doit partir avant que ce bridge meure, sinon l'appelant ne sait pas si l'arrêt a eu
    # lieu (même patron que bridge-restart) — et l'écran virtuel attend la mort de REAPER.
    import threading
    threading.Thread(target=_linux_full_stop, name="golem-stop", daemon=True).start()
    log.info("arrêt complet demandé (Reaper + bridge) — le PC redevient un PC normal")
    return {"ok": True, "killed": len(killed), "stopped": True}


def _linux_full_stop(grace=0.6):
    """Linux : le REAPER de ce rack fermé, le lecteur MIDI, l'écran virtuel, ce bridge en DERNIER.

    LE SET N'EST PAS ENREGISTRÉ SOUS LINUX, ET C'EST VOULU (essayé puis retiré le 2026-11-08). Windows/macOS
    l'enregistrent parce qu'ils ferment REAPER POLIMENT (WM_CLOSE, Apple Event) et que « Save project? » bloquerait
    l'arrêt ; ici REAPER reçoit SIGTERM, pas de boîte. Le rig est reconstruit au rappel de chaque démarrage :
    sets/golem-set.rpp reste une coquille (inchangée depuis juillet sur le rack) — un rig entier enregistré dedans
    ferait charger tous ses plugins par REAPER avant le premier rappel (démarrage plus lent, plugin qui fige au
    chargement). Et « Save project » (40026) par OSC n'avait de toute façon rien réécrit au premier essai.

    Deux écarts corrigés le 2026-11-08 (premier essai de la croix sous Linux) :
    - L'XVFB SURVIVAIT : l'écran virtuel de REAPER (provision/start.sh) restait après chaque arrêt ; `golem stop`
      le fermait, pas cette route. On le ferme APRÈS la mort de REAPER, qui dessine dessus.
    - `pkill -f "uvicorn bridge.app"` TUAIT PAR MOTIF : toute ligne de commande qui le contient (le shell qui le
      cite, les bridges jetables des sondes sur un autre port — le piège corrigé dans reload.sh le 2026-10-25).
      Ce bridge s'arrête par SON PID ; REAPER par les PID du rack, jamais le REAPER d'un banc (-cfgfile)."""
    import signal
    from . import routes_system
    pids = routes_system._rack_reaper_pids()
    if pids:
        for p in pids:
            with contextlib.suppress(OSError):
                os.kill(p, signal.SIGTERM)
        if not routes_system._wait_reaper_dead(timeout=15.0):
            log.warning("REAPER toujours là 15 s après l'arrêt demandé")
    with contextlib.suppress(Exception):
        subprocess.run(["pkill", "-x", "aseqdump"], timeout=5)   # -x : le nom exact, pas la ligne de commande
    _stop_xvfb()
    time.sleep(grace)
    os.kill(os.getpid(), signal.SIGTERM)             # uvicorn s'arrête proprement (rapport de session compris)


def _stop_xvfb():
    """L'écran virtuel de REAPER, celui que provision/start.sh lance : un process `Xvfb` dont le PREMIER argument est
    exactement l'écran du rack (GOLEM_XVFB_DISPLAY, :99) — jamais un autre Xvfb. Rend le nombre de process arrêtés."""
    import signal
    display = os.environ.get("GOLEM_XVFB_DISPLAY", ":99")
    n = 0
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if len(argv) > 1 and os.path.basename(argv[0]) == b"Xvfb" and argv[1] == display.encode():
            with contextlib.suppress(OSError):
                os.kill(int(d), signal.SIGTERM)
                n += 1
    if n:
        log.info(f"écran virtuel de REAPER fermé ({display})")
    return n


def _ui_quit_desktop(full):
    """Windows/macOS : mêmes gestes que la branche Linux, par les outils du lanceur (provision/desktop.py)
    — `ps`, `pkill` et `bash` n'existent pas ici, la route répondait 500 et le ⏻ ne faisait rien.
    REAPER est fermé par WM_CLOSE, pas tué : s'il demande d'enregistrer, sa boîte reste à l'écran
    (le garde ne masque que sa fenêtre principale). Le bridge s'en va en DERNIER, une fois REAPER
    parti, et le lanceur qui l'attend (bridge.wait) s'arrête avec lui."""
    import threading
    from provision import desktop
    killed = desktop.close_app_windows()
    if not killed and not full:
        return JSONResponse({"error": "no golem window found"}, status_code=404)
    log.info(f"coquille fermée ({killed} process)")
    if not full:
        return {"ok": True, "killed": killed}

    def finish():
        # LE PROJET DE GOLEM ENREGISTRÉ D'ABORD (2026-10-03). Chaque rebuild du rig le marque modifié, et
        # WM_CLOSE ouvrait « Save project golem-set.rpp before closing? » derrière la coquille : le bridge
        # partait au bout de 20 s, le lanceur disait « stopped », et le relancement échouait sur un REAPER
        # encore ouvert. Le projet est celui de GoleM (sets/, réécrit en jouant — CLAUDE.md règle 2).
        # Par l'action NATIVE « File: Save project » (40026) sur le lien OSC, pas par un script Lua : le
        # même jour la boucle de golem_desktop_audio.lua était morte dans le REAPER qui tournait, et
        # l'instantané ne répondait plus — l'OSC, lui, est servi par REAPER même sans nos scripts.
        # Un projet sans chemin ouvrirait une boîte « Enregistrer sous » : on ne l'envoie qu'avec un nom.
        # UN REAPER FIGÉ NE SE FERME PAS POLIMENT (2026-10-05) : son thread principal ne lit plus rien,
        # ni la sauvegarde OSC ni WM_CLOSE — le ⏻ attendait 20 s pour rien et le laissait ouvert. Figé
        # (aucun message traité pendant 15 s) = on le termine ; vivant = le chemin poli, inchangé.
        # les REAPER de banc d'abord (capture, recette) : il n'en reste qu'un, celui qu'on ferme
        try:
            from . import plugin_capture
            if plugin_capture.stop_benches():
                log.info("REAPER de banc arrêtés avant l'arrêt complet")
        except Exception as e:
            log.warning(f"REAPER de banc non arrêtés : {e}")
        pids = desktop._backend_pids()
        hung = False
        if sys.platform == "win32" and desktop.reaper_running():
            from provision.desktop_window import reaper_hung, force_close_reaper
            hung = reaper_hung(pids)
            if hung:
                log.warning(f"REAPER ne répond plus (thread principal figé) : fermeture forcée "
                            f"({force_close_reaper(pids)} process)")
        if not hung and desktop.reaper_running():
            try:
                from . import desktop_audio
                project = desktop_audio.save_project_in_place()
                if project:
                    log.info(f"projet enregistré avant l'arrêt : {project}")
            except Exception as e:
                log.warning(f"projet non enregistré avant l'arrêt : {e}")
        # macOS : « quit » par Apple Event, le chemin de la page Audio — pas le binaire (`-nonewinst -closeall:exit`,
        # 15 s HORS try : un délai dépassé tuait ce fil avant os._exit, le bridge restait « stopping » ; et lancer le
        # binaire d'une app déjà ouverte n'est pas sûr de lui parvenir). Passe macOS du 2026-10-10.
        try:
            from provision.desktop_window import request_reaper_close
            request_reaper_close(pids)
        except Exception as e:
            log.warning(f"fermeture de REAPER non demandée : {e}")
        for _ in range(40):                          # 20 s : le temps d'une boîte « enregistrer ? »
            if not desktop.reaper_running():
                break
            time.sleep(0.5)
        else:
            # toujours là : une boîte « enregistrer ? » (la fenêtre RÉPOND — on la laisse), ou un
            # REAPER figé entre-temps. 5 s de sonde de plus : le lanceur attend le bridge 30 s en tout.
            if sys.platform == "win32":
                from provision.desktop_window import reaper_hung, force_close_reaper
                if reaper_hung(pids, seconds=5):
                    log.warning(f"REAPER figé à la fermeture : fermeture forcée ({force_close_reaper(pids)} process)")
                    for _ in range(10):
                        if not desktop.reaper_running():
                            break
                        time.sleep(0.5)
        log.info("arrêt complet (Reaper + bridge) — le PC redevient un PC normal")
        # LA SESSION SE CLÔT AVANT LE os._exit (2026-10-05) : os._exit saute l'arrêt de l'app, donc
        # diag.shutdown_report — chaque fermeture NORMALE sous Windows/macOS partait « unclean », et
        # golem.fm comptait 15 incidents par jour (pastille rouge). Écrire d'abord, envoyer court.
        try:
            from . import diag
            diag.shutdown_report("quit")
        except Exception as e:
            log.warning(f"clôture de session non écrite : {e}")
        os._exit(0)

    threading.Thread(target=finish, name="golem-quit", daemon=True).start()
    return {"ok": True, "killed": killed, "stopped": True}


# ── MÉMOIRE DE FENÊTRE du poste de travail ──────────────────────────────────
# La fenêtre ouverte par `provision/golem` retrouve sa taille et son zoom. État PUREMENT LOCAL
# (il décrit l'écran de cette machine, pas le rig) : config/.desktop.json, hors dépôt — même
# règle que .mode.json ou .band.json. Un GoleM server n'a pas de fenêtre : rien à mémoriser.
# Contrat + mesures : docs/ui-architecture.md § « la fenêtre du poste de travail ».
GEOM_FILE = os.path.join(C.CONFIG_DIR, ".desktop.json")
GEOM_SHELLS = ("ui", "device", "phone")


def _geom_read():
    try:
        d = json.load(open(GEOM_FILE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@router.get("/api/ui/geometry")
async def ui_geometry_get():
    """Ce dont la page a besoin pour se RATTRAPER quand Chrome a recyclé son processus."""
    return _geom_read()


@router.post("/api/ui/geometry")
async def ui_geometry_set(request: Request):
    """La page rapporte sa géométrie — elle seule la connaît (session Wayland, pas d'outil de
    fenêtrage). Corps : {shell, w, h, dpr, first}.

    `base` = l'échelle NATURELLE de l'écran, et le seul instant où on peut la lire est le
    CHARGEMENT : avant que l'utilisateur n'ait touché à Ctrl+/-. C'est `first` qui le dit. Sans
    cette distinction, le premier rapport suivant un zoom écrasait `base` avec le zoom lui-même :
    l'écart disparaissait, et on ne rejouait plus rien (mesuré — le test 4 sortait 0 au lieu de
    1.25). Un écran HiDPI, lui, doit garder son dpr 2 comme naturel : on ne fige jamais l'échelle
    de bureau de quelqu'un qui n'a rien demandé.
    """
    body = await request.json()
    shell = str((body or {}).get("shell") or "")
    if shell not in GEOM_SHELLS:
        return JSONResponse({"error": f"shell inconnue (attendu : {'|'.join(GEOM_SHELLS)})"}, status_code=400)
    try:
        w, h = int(body["w"]), int(body["h"])
        dpr = round(float(body.get("dpr") or 1), 4)
    except Exception:
        return JSONResponse({"error": "w/h/dpr numériques requis"}, status_code=400)
    # garde-fou : une fenêtre minimisée rapporte parfois 0, un bug rapporterait l'absurde — et
    # une taille absurde MÉMORISÉE ouvre une fenêtre inatteignable au prochain lancement.
    if not (320 <= w <= 16000 and 200 <= h <= 16000 and 0.2 <= dpr <= 8):
        return JSONResponse({"error": f"géométrie hors bornes ({w}×{h} @{dpr})"}, status_code=400)

    d = _geom_read()
    cur = d.get(shell) if isinstance(d.get(shell), dict) else {}
    forced = float(cur.get("forced") or 0)          # ce que le lanceur a posé AVANT d'ouvrir
    base = float(cur.get("base") or 0) or dpr
    if body.get("first"):
        if not forced:
            base = dpr                              # rien de forcé : ce qu'on voit EST l'écran
        elif abs(dpr - forced) > 0.01:
            # Le lanceur a forcé X et la page voit autre chose : le navigateur ajoute sa propre
            # échelle (zoom par site restauré, écran changé…). Empiler les deux donnerait un
            # zoom au carré — on renonce à forcer et on repart de ce qu'on voit. Ça se répare
            # tout seul au lancement suivant plutôt que de dériver.
            base, forced = dpr, 0.0
    d[shell] = {"w": w, "h": h, "dpr": dpr, "base": round(base, 4), "forced": forced}
    os.makedirs(C.CONFIG_DIR, exist_ok=True)
    tmp = GEOM_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, GEOM_FILE)
    return {"ok": True, shell: d[shell]}


# ── Calibration ▸ Drums (docs/calibration.md, addendum 2026-09-23) ────────────────────────────
# Tant que Reaper détient le port rawmidi d'un module, personne d'autre ne peut l'écouter : la
# mesure passe par une piste d'écoute DANS Reaper (golem_drumlearn.lua + drum-tap.jsfx), créée à la
# demande. Le bridge résout le nom Reaper du device ("hw:Nitro") depuis /proc/asound/cards — jamais
# d'heuristique : un module absent = 409 qui le dit.
DRUMLEARN_LIVE = C.runtime_file("golem-drumlearn.json")


@router.post("/api/calibrate/drums/start")
async def drumlearn_start(body: dict):
    """{port: n} (prise USB liée) ou {device: "Alesis Nitro"} -> piste d'écoute sur ce module."""
    from . import inputmap, vital
    body = body or {}
    device = body.get("device")
    if not device and body.get("port") is not None:
        for u in inputmap.usb_ports():
            if u.get("port") == int(body["port"]):
                device = u.get("device")
    if not device:
        return JSONResponse({"error": "port or device required"}, status_code=400)
    hw = vital._hw_of(device)
    if not hw:
        return JSONResponse({"error": f"« {device} » is not plugged in (not in /proc/asound/cards)"}, status_code=409)
    seq = write_command({"action": "drumlearn", "on": True, "dev": hw})
    return {"ok": True, "device": device, "dev": hw, "seq": seq}


def _reaper_midi_input(device):
    """Le nom EXACT que REAPER donne à l'entrée MIDI de ce device, ou None s'il n'est pas branché.
    Linux : « hw:II » depuis /proc/asound/cards ; Windows : le nom WinMM, que REAPER reprend tel quel."""
    if sys.platform == "win32":
        from . import desktop_midi
        names = desktop_midi.ports().get("in") or []
        want = (device or "").strip().casefold()
        return next((n for n in names if n.casefold() == want), None)
    from . import vital
    return vital._hw_of(device)


@router.post("/api/calibrate/keys/start")
async def keylearn_start(body: dict):
    """Calibration ▸ Controllers (2026-10-03) : une piste d'écoute « KeysLearn » sur ce clavier, avec
    knob-tap — le stepper ne dépend plus d'une lane Keys dans le preset chargé (un patch guitare n'en a
    pas : « Play the LOWEST key » ne voyait rien)."""
    device = ((body or {}).get("device") or "").strip()
    if not device:
        return JSONResponse({"error": "device required"}, status_code=400)
    dev = _reaper_midi_input(device)
    if not dev:
        return JSONResponse({"error": f"« {device} » is not plugged in"}, status_code=409)
    seq = write_command({"action": "drumlearn", "on": True, "dev": dev, "tap": "knob"})
    return {"ok": True, "device": device, "dev": dev, "seq": seq}


@router.post("/api/controllers/pads-channel")
async def controllers_pads_channel(body: dict = None):
    """DONNER AUX PADS LEUR PROPRE CANAL (bridge/controller_program.py) : pads sur le canal 10, notes 36.., écrit DANS
    le contrôleur — lu, original gardé, écrit, RELU, puis sa mémoire de travail. Le modèle vient de son descripteur
    (config/controller-models/) ; sans descripteur : 409 qui le dit (régler dans l'éditeur du fabricant, puis
    calibrer). Succès -> les canaux vont dans le profil (bridge/controllers.py) et le moteur trie la lane Keys."""
    import asyncio
    from . import controller_program as cp, controllers as ctl, devices
    body = body or {}
    want = {"usb": body.get("usb") or "", "name": body.get("name") or ""}
    dev = next((d for d in devices.detected() if d.get("kind") == "midi" and devices._match(want, d)), None)
    if not dev:
        return JSONResponse({"error": "this controller is not plugged in"}, status_code=409)
    model = cp.model_for(dev.get("usb"), dev.get("name"))
    if not cp.can_program(model):
        return JSONResponse({"error": "golem does not know how to program this controller — set its pads to their own "
                                      "MIDI channel in the maker's editor, then calibrate again"}, status_code=409)
    hw = _reaper_midi_input(dev.get("name")) or dev.get("hw")
    if not hw:
        return JSONResponse({"error": "the audio engine does not see this controller"}, status_code=409)
    try:
        r = await asyncio.get_running_loop().run_in_executor(None, lambda: cp.setup(model, hw))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    if r["ok"]:
        ctl.set_channels(dev.get("usb") or "", model.get("name") or dev.get("name") or "", r["key_ch"], r["pad_ch"], r["notes"])
    return {"ok": r["ok"], "model": model["id"], "pad_ch": r["pad_ch"], "key_ch": r["key_ch"], "notes": r["notes"]}


@router.post("/api/calibrate/keys/stop")
async def keylearn_stop():
    seq = write_command({"action": "drumlearn", "on": False})
    return {"ok": True, "seq": seq}


@router.post("/api/calibrate/drums/stop")
async def drumlearn_stop():
    seq = write_command({"action": "drumlearn", "on": False})
    return {"ok": True, "seq": seq}


@router.get("/api/calibrate/drums/live")
def drumlearn_live():
    """Le tampon des 32 derniers événements du module (k 1 note-on · 2 CC · 3 aftertouch poly), publié
    par golem_drumlearn.lua. `on: false` = aucune piste d'écoute ; `err` dit pourquoi si elle a échoué."""
    try:
        return json.load(open(DRUMLEARN_LIVE))
    except Exception:
        return {"on": False, "dev": None, "seq": 0, "clock": 0, "events": [], "err": None}


@router.post("/api/drumkits/measure")
async def drumkits_measure(body: dict):
    """« Save as measured » : {measure, kit?} -> analyse + comparaison + descripteur écrit (verified).
    `dry: true` = tout sauf l'écriture (l'écran de revue). Refus 409 quand la mesure se contredit
    (deux éléments de base sur une note) ou que le descripteur qui en sort est invalide."""
    from . import drumlearn, drumkits
    body = body or {}
    measure, kit = body.get("measure") or {}, body.get("kit")
    if not (measure.get("steps") or {}):
        return JSONResponse({"error": "measure.steps required"}, status_code=400)
    base = drumkits.get(kit) if kit else None
    if kit and not base:
        return JSONResponse({"error": f"unknown drum kit descriptor: {kit}"}, status_code=400)
    rep = drumlearn.analyse(measure)
    cmp_ = drumlearn.compare(rep, base) if base else None
    try:
        desc = drumlearn.descriptor(rep, measure, base)
        if body.get("dry"):
            return {"ok": True, "dry": True, "report": rep, "compare": cmp_, "descriptor": desc,
                    "problems": drumkits.validate(desc, desc.get("id"))}
        path = drumlearn.write(desc)
    except ValueError as e:
        return JSONResponse({"error": str(e), "report": rep, "compare": cmp_}, status_code=409)
    return {"ok": True, "report": rep, "compare": cmp_, "descriptor": desc, "path": C.rel(path)}
