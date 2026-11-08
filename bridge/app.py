# SPDX-License-Identifier: GPL-3.0-or-later
"""Bridge GoleM — FastAPI.

Sert l'app (statique), expose l'API REST (presets, recall) + un WebSocket qui pousse
l'état live du RIG, et relaie les commandes vers Reaper en OSC.

Lancer :  ./provision/serve-rig.sh   (ou  uvicorn bridge.app:app --host 0.0.0.0 --port 8770)
"""
import os, json, glob, asyncio, tempfile, contextlib, subprocess, re, time, itertools, threading, logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as C
from . import midi_out
from . import inputclip
from . import foot
from . import foot_leds
from . import modes as modes_mod
from . import scene_bake
from . import monitors
from . import auth as auth_mod
from . import activity as activity_mod
from . import looper as looper_mod
from . import transcribe_jobs as transcribe_mod
from . import backing as backing_mod
from . import sample as sample_mod
from . import drums as drums_mod
from . import standards as standards_mod
from . import arrangement as arrangement_mod
from . import machine as machine_mod
from . import routes_content, routes_dev, routes_system, routes_t3k, routes_backing, routes_network, routes_modes, routes_inputmap, routes_patches, routes_blocks, routes_kit_import, routes_standards, routes_diag, routes_connect, routes_desktop_audio, routes_separation, routes_health
from . import mcp
from . import recall as recall_mod   # le moteur de recall (extrait d'ici — audit 2026-08-12 P2)
from .state import state
from . import store
from .store import load_presets, load_preset, _read_json, _write_json_atomic, _safe_id
from .commands import write_command
from .reaper_osc import ReaperLink
from .golog import get

# un logger par tag historique : les préfixes [boot]/[bank]/… sont cités dans la doc
# et les habitudes de grep — le nom du logger les reprend, le message ne les double pas
log_boot = get("boot")
log_bank = get("bank")
log_sandbox = get("sandbox")
log_standard = get("standard")
log_click = get("click")
log_perf = get("perf")

app = FastAPI(title="GoleM bridge")


# audit 2026-11-04 (H2) : uvicorn journalise le chemin du WebSocket AVEC sa query — le `?token=` d'un appareil finissait
# en clair dans le journal du bridge, que les paquets de diagnostic embarquent. Effacé à la source.
class _TokenFilter(logging.Filter):
    _rx = re.compile(r"(token=)[^&\s\"']+")

    def filter(self, record):
        if record.args:
            record.args = tuple(self._rx.sub(r"\1<token>", a) if isinstance(a, str) else a
                                for a in (record.args if isinstance(record.args, tuple) else (record.args,)))
        if isinstance(record.msg, str) and "token=" in record.msg:
            record.msg = self._rx.sub(r"\1<token>", record.msg)
        return True


for _n in ("uvicorn.error", "uvicorn.access"):
    logging.getLogger(_n).addFilter(_TokenFilter())


# ── AUTH transverse (Sprint 3.1 — SECURITY.md) : UN middleware protège toutes les
# mutations + GET sensibles. Local (kiosk) auto-authentifié ; distant = token du QR. ──
@app.middleware("http")
async def _auth_guard(request, call_next):
    # audit 2026-10-15 (S3) : /library est servi à tous ; ses dossiers CACHÉS (.import = les téléchargements d'URL,
    # avant lecture) n'en font pas partie
    # audit 2026-11-04 (M2) : sous Windows, `\` sépare aussi — `/library/a\..\catalog\.x.json` passait le test
    if request.url.path.startswith("/library/") and any(
            seg.startswith(".") for seg in request.url.path.replace("\\", "/").split("/")):
        from fastapi.responses import JSONResponse as _JR
        return _JR({"error": "not found"}, status_code=404)
    if not auth_mod.allowed_http(request):
        from fastapi.responses import JSONResponse as _JR
        return _JR({"error": "unauthorized — scan the QR on the rack (Settings ▸ Connect ▸ Devices)"},
                   status_code=403)
    # ACTIVITÉ (docs/reamp.md §2) : une requête qui MODIFIE = quelqu'un s'en sert. La géométrie de
    # fenêtre n'est pas un geste (la coquille la pousse seule au chargement et au redimensionnement).
    if request.method != "GET" and request.url.path != "/api/ui/geometry":
        activity_mod.touch("screen")
    response = await call_next(request)
    # Sprint 4.3 (D-P1-4) : /app en no-cache -> le navigateur REVALIDE chaque module (ETag déjà
    # émis par StaticFiles => 304 quasi gratuits sur le LAN). Fini le code JS périmé après un
    # déploiement : un F5 normal suffit, plus jamais de Ctrl+Shift+R (piège vécu x4 le 2026-07-24).
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache"
    # audit 2026-11-04 (L8) : une page ouverte sur la machine du rack ne doit pas encadrer l'app (le client local est
    # admin : clic détourné) ni faire interpréter une réponse comme un autre type
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response
app.include_router(routes_content.router)
app.include_router(routes_dev.router)
app.include_router(routes_system.router)
app.include_router(routes_desktop_audio.router)
app.include_router(routes_t3k.router)
app.include_router(mcp.router)          # /mcp : la vue LECTURE du rack (docs/rack-mcp.md)
app.include_router(routes_backing.router)
app.include_router(routes_network.router)
app.include_router(routes_modes.router)
app.include_router(routes_inputmap.router)
from . import routes_card_setups                 # les configurations de carte entre racks (docs/card-setups-exchange.md)
app.include_router(routes_card_setups.router)
from . import routes_startup                     # l'accueil au démarrage (mockups/startup-home.html)
app.include_router(routes_startup.router)
app.include_router(routes_patches.router)
app.include_router(routes_blocks.router)     # état des blocs (docs/block-status.md)
app.include_router(routes_kit_import.router) # « + Add » d'une batterie par le rack (docs/drums-kit.md §8)
app.include_router(routes_standards.router)
app.include_router(routes_diag.router)      # lot 8 : paquets de diagnostic (docs/diagnostics.md)
app.include_router(routes_connect.router)   # se connecter sans taper d'adresse (docs/connect.md)
app.include_router(routes_separation.router)  # séparation de sources sur le golem (docs/separation.md)
app.include_router(routes_health.router)      # Settings ▸ Health : des faits datés (docs/health.md)
from . import routes_machine                     # cet ordinateur : fenêtre, démarrage, durcissement (docs/installer.md §4)
app.include_router(routes_machine.router)
state.mode = modes_mod.current()      # mode machine restauré au boot (docs/modes.md)
from . import inputmap as inputmap_mod
state.inputmap = inputmap_mod.current()   # input map de la carte active (docs/input-map.md)
from . import preview as preview_mod   # génération de démo : applicateur de scène live + restaurateur
from .golog import swallowed as _swallowed
preview_mod.set_scene_applier(recall_mod.emit_sandbox)
# restaure le rig d'avant après une génération (elle PREND le moteur) : ré-applique le .sandbox.json
preview_mod.set_restore(recall_mod.reapply_sandbox)
midi_out.warm()                       # ligne Whammy armée au boot (LED MIDI OUT honnête)
_loop = None            # boucle asyncio principale (pour planifier depuis le thread OSC)
_clients = set()        # WebSockets connectés
_foot = None            # lecteur FCB1010 (bridge/foot.py)


# ── WebSocket : diffusion de l'état ──────────────────────────────────────────
# UN ENVOI À LA FOIS, ET UNE PRISE QUI ÉCHOUE SE FERME (2026-10-20 — « je suis coincé »). Trouvé sur le rack : la fenêtre
# golem affichait l'écran de chargement figé à 7 s, le bridge ne comptait plus aucun écran, et son WebSocket était
# toujours « open » dans le journal. La diffusion était planifiée depuis plusieurs fils (OSC à 20 Hz pendant le rappel
# de la bank 00, moniteurs, rappel) : deux `send` se chevauchaient sur la même prise, l'un levait, et le client était
# écarté EN SILENCE sans que la prise soit fermée — la page gardait un WebSocket vivant mais muet, donc jamais de
# reconnexion. Désormais : un verrou (les diffusions concurrentes se fondent en une seule, avec l'état le plus frais),
# une sérialisation pour tous les écrans, l'erreur journalisée, et la prise FERMÉE pour que la page se reconnecte.
# UNE SEULE DIFFUSION EN FILE, ET RIEN SANS ÉCRAN (PC Windows neuf, 2026-11-03) : le verrou ne fond que les demandes
# arrivées PENDANT un envoi (un await). Sans écran, il n'y a aucun await : chaque broadcast_threadsafe (OSC, moniteurs,
# téléchargements — plusieurs fils, des dizaines par seconde) planifiait SA tâche, et chacune refaisait un snapshot
# complet. Dès qu'un snapshot coûtait plus que l'écart entre deux demandes, la file ne se vidait plus : la boucle
# asyncio ne rendait plus la main, /api/health ne répondait plus, l'installateur disait « did not start within 90 s ».
# `queued` : au plus une tâche planifiée depuis les fils ; sans écran, pas de snapshot du tout (personne ne le lit).
_bcast = {"lock": None, "pending": False, "queued": False}
log_ws = get("ws")


def _bcast_lock():
    if _bcast["lock"] is None:
        _bcast["lock"] = asyncio.Lock()
    return _bcast["lock"]


def _snapshot_text():
    return json.dumps(state.snapshot(), ensure_ascii=False, separators=(",", ":"))


async def _drop(ws, e):
    _clients.discard(ws)
    log_ws.warning(f"écran écarté sur une erreur d'envoi ({type(e).__name__}: {str(e)[:120]}) — prise fermée, il se reconnectera")
    with contextlib.suppress(Exception):
        await ws.close(code=1011)


async def _broadcast():
    if not _clients:                     # aucun écran : rien à envoyer, donc rien à calculer
        return
    lock = _bcast_lock()
    if lock.locked():
        _bcast["pending"] = True         # la diffusion en cours repartira une fois, avec l'état le plus frais
        return
    async with lock:
        while True:
            _bcast["pending"] = False
            try:
                payload = _snapshot_text()
            except Exception as e:       # un état non sérialisable est un bug à voir, pas des écrans perdus en silence
                log_ws.warning(f"état non sérialisable : {type(e).__name__}: {str(e)[:160]}")
                return
            dead = []
            for ws in list(_clients):
                try:
                    await ws.send_text(payload)
                except Exception as e:
                    dead.append((ws, e))
            for ws, e in dead:
                await _drop(ws, e)
            if not _bcast["pending"]:
                return


def broadcast_threadsafe():
    """Planifie une diffusion depuis n'importe quel thread (ex. callback OSC). Une demande arrivée alors qu'une
    diffusion est DÉJÀ en file s'y fond : celle-ci lira l'état le plus frais (le drapeau tombe quand elle démarre)."""
    if _loop and not _bcast.get("queued"):
        _bcast["queued"] = True
        try:
            _loop.call_soon_threadsafe(_start_queued_broadcast)
        except RuntimeError:             # boucle fermée (arrêt) : rien à diffuser
            _bcast["queued"] = False


def _start_queued_broadcast():
    _bcast["queued"] = False
    asyncio.ensure_future(_broadcast())


# ── OSC : feedback Reaper -> état ────────────────────────────────────────────
_last_vu_bcast = 0.0


def on_osc(address, args):
    state.set_reaper(True)               # tout message = Reaper est là
    if address.startswith("/track/") and address.endswith("/vu"):
        # /track/<n>/vu -> meter (glow réactif Live). Débit métrique élevé -> broadcast throttlé ~20 Hz.
        try:
            n = int(address.split("/")[2]); val = float(args[0]) if args else 0.0
        except (ValueError, IndexError):
            return
        # /track/<n> est l'INDEX de piste Reaper : les trois roots « Sandbox #Input 1/2/3 » ouvrent le
        # projet, au-delà ce sont des sous-pistes et des services. Par ENTRÉE (lot 4 cosmétique) — deux
        # guitares = deux vumètres. Sur une carte à N entrées, ce lien passera par le livemap.
        if 1 <= n <= 3:
            state.levels[f"in{n}"] = val
            activity_mod.note_level(val)              # quelqu'un joue (docs/reamp.md §2)
            # ÉCRÊTAGE : le vumètre OSC est normalisé, 1,0 = 0 dBFS. Trois lectures collées au plafond
            # = un plateau, pas une crête. Une puce sur /live et Soundcard, un événement de chronologie
            # par épisode (docs/diagnostics.md) — et le conseil : le gain de la carte.
            if inputclip.note_level(state, n, val):
                with contextlib.suppress(Exception):
                    from . import diag
                    diag.event("chip", chip=f"IN {n} CLIP", on=True)
        if n == 1: state.levels["guitar"] = val          # compat : les clés par rôle restent
        elif n == 2: state.levels["voice"] = val
        state.touch()
        global _last_vu_bcast
        now = time.time()
        if now - _last_vu_bcast >= 0.05:
            _last_vu_bcast = now
            broadcast_threadsafe()
        return
    elif address == "/tempo/raw" and args:
        with contextlib.suppress(Exception):
            state.tempo = int(float(args[0])); state.touch()
    broadcast_threadsafe()


reaper = ReaperLink(C.REAPER_OSC_HOST, C.REAPER_OSC_SEND_PORT, C.BRIDGE_OSC_RECV_PORT, on_osc)

# contrôleur du looper : dispatch OSC (slider GoleM Cmd) + moteur de gestes du pied.
# L'adresse (track/fx/param) et le feedback lui sont poussés par monitors._poll_looper.
_looper_ctl = looper_mod.LooperControl(reaper, on_change=lambda: broadcast_threadsafe())


def _looper_timing():
    """Le calage de la 1re boucle (docs/looper.md, addendum 2026-10-14) : le tempo du preset, la mesure du click,
    et le réglage du bloc looper — `length` « auto » (défaut) cale la fermeture sur la mesure QUAND une grille joue
    (click, boîte à rythmes, backing), « free » jamais ; `count_in` (défaut oui, en « auto » seulement) lance une
    mesure de click avant la 1re boucle quand RIEN ne joue. Le décompte implique le calage : son click est la grille."""
    cur = load_preset(state.preset_id) if state.preset_id else None
    p = recall_mod.effective_preset(cur) or {} if cur else {}
    blk = next((b for b in ((p.get("config") or {}).get("gen") or {}).get("blocks") or [] if b.get("type") == "looper"), None)
    prm = (blk or {}).get("params") or {}
    if prm.get("length", "auto") == "free":
        return {"bpm": 0, "beats": 4, "snap": False, "count_in": False, "rec_dub": bool(prm.get("rec_dub", False))}
    bpm = float(p.get("bpm") or 0)
    grid = _click_on() or bool(_backing_ctl.playing()) or any(
        st.get("playing") for st in (_drums_ctl.snapshot() or {}).values())
    return {"bpm": bpm, "beats": int(_click_cfg().get("beats") or 4), "snap": bool(grid and bpm),
            "count_in": bool(prm.get("count_in", True) and not grid and bpm),
            "rec_dub": bool(prm.get("rec_dub", False))}


_looper_ctl.timing = _looper_timing

# contrôleur des backing tracks : transport OSC /action + commandes items via .command.json.
# Le feedback (.backing.json) lui est poussé par monitors._poll_backing.
_backing_ctl = backing_mod.BackingControl(reaper, on_change=lambda: broadcast_threadsafe())


def _bars_changed(slug):
    """Une carte des mesures arrive (ou change) pour la backing CHARGÉE : on la recharge pour que golem_backing repose
    les temps du click — jamais pendant qu'elle joue (on ne coupe pas ce qu'on écoute ; elle repartira au rappel)."""
    if (state.backing or {}).get("slug") == slug and not _backing_ctl.playing():
        _backing_ctl.load(slug)


from . import bars as _bars_mod                                       # noqa: E402
_bars_mod.listeners.append(_bars_changed)
# le switch du bloc backing-track du preset courant vit avec le moteur : recall_mod.backing_sw

# contrôleur des blocs SAMPLE (lanceurs de one-shots) : moteur de gestes tap/appui-long ->
# commandes {action:"sample"} relayées à golem_sample.lua. state.sample_switches posé au recall.
_sample_ctl = sample_mod.SampleControl(
    emit=lambda c: write_command({**c, "_route": "sample"}),
    on_change=lambda: (setattr(state, "samples", _sample_ctl.snapshot()), broadcast_threadsafe()))

# contrôleur des blocs DRUMS (boîte à rythmes MIDI) : gestuelle 3-seuils (fill/variation/stop)
# -> commandes {action:"drums"} relayées à golem_drums.lua. state.drum_switches posé au recall.
_drums_ctl = drums_mod.DrumControl(
    emit=lambda c: write_command({**c, "_route": "drums"}),
    on_change=lambda: (setattr(state, "drums", _drums_ctl.snapshot()), broadcast_threadsafe()))


# ── CHEF D'ORCHESTRE (docs/arrangement.md §8) : les sections d'un preset jouées dans le temps.
# Il n'ajoute AUCUNE ligne côté Reaper — il actionne des chemins déjà livrés : rappel de scène
# sans rebuild (gapless) et `_do_stomp(sw, want)`, dont l'état ABSOLU attendait les cues.
def _arr_cue(sec):
    """Applique une cue de section.

    ORDRE (contrat §3 bis) : LA SCÈNE D'ABORD, LES BASCULES EXPLICITES ENSUITE. Une section peut
    donc dire « scène B, mais delay coupé » — c'est le cas « la scène plus une chose », et c'est
    le seul ordre qui ne surprend personne.

    Les bascules portent des ID DE BLOCS, pas des numéros de switch : réorganiser le pédalier ne
    doit pas changer le sens d'un morceau. Une scène absente du preset ne fait RIEN (règle 4) —
    le plan l'a déjà neutralisée.

    ⚠ UN SEUL message pour les deux sens : le canal bridge->Reaper n'a qu'un slot, deux commandes
    successives se perdraient l'une l'autre — et les espacer ferait arriver le boost avant que le
    delay ne se coupe, audible à une frontière de section.

    Le corps tourne dans l'exécuteur du recall (UN worker, FIFO) : l'ordre « scène puis
    bascules » est préservé, et la boucle asyncio reste libre pendant le bake/compile —
    une cue ne gèle plus le WebSocket ni le tick de l'arrangement.
    """
    recall_mod.submit(_arr_cue_core, sec)


def _arr_cue_core(sec):
    # un TOUR DE BOUCLE ou un SAUT de répète (`_lap`, docs/live-pages.md §6.3) ne rappelle la scène que si elle
    # CHANGE : un rappel de la même scène re-bascule des blocs (le convolveur, la Whammy) pour rien, à chaque tour
    if sec.get("scene") and not (sec.get("_lap") and sec["scene"] == getattr(state, "scene_id", None)):
        recall_mod.do_recall(None, sec["scene"])
    blocks = sec.get("blocks") or {}
    if blocks:
        on_ids = [k for k, v in blocks.items() if v]
        off_ids = [k for k, v in blocks.items() if not v]
        write_command({"action": "stomp", "preset": state.preset_id,
                       "on_ids": on_ids, "off_ids": off_ids, "_route": "rig_recall"})


def _arr_click_hold(on):
    """Décompte : le click DOIT s'entendre, même en `click_mode: off` (§13 — c'est sa seule raison
    d'être). On court-circuite donc `_click_set` et son veto de mode, délibérément."""
    ck = _click_cfg()
    _click_cmd({"action": "click", "op": "set", "on": bool(on), "level": ck["level"],
                   "beats": ck["beats"], "den": ck.get("den", 4),
                   "groups": ck.get("groups") or [], "div": 1, "out": store.click_out()})


_ARR_CLICK = {"was": False, "ours": False, "song": False, "meter": None}


def _arr_click_meter(meter, push=True):
    """LA MESURE DE LA SECTION (docs/arrangement.md §3) : tant qu'un morceau tourne, `_click_cfg` la pose par-dessus
    la config et la ligne — toute commande click (décompte, premier temps, geste manuel) la porte. `push` : le moteur
    de cues l'envoie lui-même à l'instant qu'il a choisi (une demi-pulsation avant la frontière, _premeter) ; une
    commande SANS `on` — golem_click.lua garde l'état allumé/éteint, donc aucun front, aucun « 1 » en trop.
    `meter` porte aussi l'ANCRE de phase (`anchor`, arrangement.click_anchor) : _click_cmd la transmet.
    Poussée AUSSI en click du MORCEAU (2026-10-15) : les temps y viennent des notes, mais le GROUPEMENT (3+2+2) vit
    dans la section — le JSFX accentue le temps des notes dont le bit du masque est à 1 (docs/bars-format.md §5)."""
    meter = dict(meter) if meter else None
    if meter == _ARR_CLICK.get("meter"):
        return
    _ARR_CLICK["meter"] = meter
    if not push:
        return
    ck = _click_cfg()
    _click_cmd({"action": "click", "op": "set", "beats": ck["beats"], "den": ck.get("den", 4),
                "groups": ck.get("groups") or [], "div": 1})


def _click_cmd(cmd):
    """TOUTE commande `click` passe ici : elle porte l'état « click du morceau » (`song`, docs/bars-format.md).
    golem_click.lua garde la valeur d'un champ absent — une commande annexe (niveau, décompte, horloge) qui
    l'oublierait laisserait le click asservi à des notes qui n'existent plus : muet. On le dit donc à chaque fois.
    Même loi pour l'ANCRE de phase (`anchor`, s sur le transport, -1 = aucune — docs/arrangement.md §4) : une ancre
    restée d'un morceau fini recalerait le click libre sur une section qui n'existe plus."""
    cmd["song"] = bool(_ARR_CLICK.get("song"))
    a = (_ARR_CLICK.get("meter") or {}).get("anchor")
    cmd["anchor"] = round(float(a), 4) if isinstance(a, (int, float)) and a >= 0 else -1
    write_command(cmd)


def _arr_click_song(ev, want=None):
    """Le click PART avec le morceau et se tait avec lui (docs/arrangement.md §8) — si la chanson le veut (bloc
    Click actif dans le preset tel qu'il se joue) et si le mode le permet (`_click_set` porte le veto). On ne
    rend que ce qu'on a pris : un click qui jouait déjà avant ▶ Play continue après ■ Stop."""
    if ev == "start":
        _ARR_CLICK.update(was=_click_on(), ours=False)
        # le mode « click du morceau » part DÈS LE DÉCOMPTE (transport arrêté, il ne change rien : le décompte reste
        # libre) — posé seulement au premier temps, il arrivait par le fichier de commande 30 à 100 ms APRÈS le
        # transport (OSC), et les premières notes de l'item partaient sans être jouées (relecture reascript, 2026-10-07)
        _ARR_CLICK["song"] = bool(_arr_click_want(want) and _song_click_ready())
        if _ARR_CLICK["was"]:
            # le JSFX ne repart sur le « 1 » qu'à un FRONT 0->1 (même geste que _countin_begin) : sans lui, un
            # click qui tournait déjà décomptait hors de la mesure du morceau
            ck = _click_cfg()
            _click_cmd({"action": "click", "op": "set", "on": False, "level": ck["level"],
                           "beats": ck["beats"], "den": ck.get("den", 4), "groups": ck.get("groups") or [],
                           "div": 1, "out": store.click_out()})
        return
    if ev == "go":
        want = _arr_click_want(want)
        # LE CLICK DU MORCEAU (docs/bars-format.md) : la backing part avec une carte des mesures -> le click joue
        # ses VRAIS temps (notes posées sur la piste Click par golem_backing, mode `song` du JSFX), plus un
        # tempo fixe qui décroche d'un groupe joué sans click. Sans carte : le click d'avant, au tempo de la fiche.
        _ARR_CLICK["song"] = bool(want and _song_click_ready())
        if want and _click_set(True):
            _ARR_CLICK["ours"] = not _ARR_CLICK["was"]
        elif not _ARR_CLICK["was"]:
            _arr_click_hold(False)                  # le décompte l'avait forcé : il rend la main
        else:
            _click_set(True)                        # il jouait avant (coupé au départ pour la phase) : il reprend
        return
    if ev == "cancel":                              # arrêt pendant le décompte : on rend l'état d'avant
        if not _ARR_CLICK["was"]:
            _arr_click_hold(False)
        return
    if ev == "stop":
        song, _ARR_CLICK["song"] = _ARR_CLICK.get("song"), False
        if _ARR_CLICK["ours"]:
            _ARR_CLICK["ours"] = False
            _click_set(False)
        elif song:
            _click_set(_click_on())                 # il jouait avant : il reste, mais hors mode « morceau »


def _arr_click_want(want):
    """La case Click de la chanson décide ; sans case, le bloc Click du preset (actif = il part) — §6."""
    if want is not None:
        return bool(want)
    cur = load_preset(state.preset_id) if state.preset_id else None
    eff = recall_mod.effective_preset(cur) if cur else None
    blocks = (((eff or {}).get("config") or {}).get("rec") or {}).get("blocks") or []
    cb = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "click"), None)
    return bool(cb) and not cb.get("bypass")


def _song_click_ready():
    """Le click peut-il suivre les vrais temps ? La carte des mesures du morceau lancé (prise par
    l'arrangement, donc la backing part avec lui), et la backing chargée est bien la sienne."""
    if not getattr(_arr_ctl, "_bars", None):
        return False
    # ⚠ des temps RÉELLEMENT posés sur la piste Click (golem_backing le publie) : sans eux le JSFX en mode
    # « morceau » attend des notes qui n'existent pas, et le click se tait (test au rig du 2026-10-08 : la piste
    # Click n'existait pas encore quand la backing s'est chargée). Mieux vaut le click à tempo fixe que rien.
    if not int((state.backing or {}).get("songclick") or 0):
        return False
    from . import bars as _bars
    return _arr_song_backing_wanted({}) and (state.backing or {}).get("slug") == _bars.slug_of(
        recall_mod.effective_preset(load_preset(state.preset_id)) if state.preset_id else None)


def _arr_backing(on, at=0.0):
    """La backing suit le ▶ Play / ■ Stop de l'arrangement (docs/arrangement.md §8). AUTOMATIQUE dès
    qu'une backing est CHARGÉE (le bloc backing du preset l'a posée au rappel) et que le mode l'autorise :
    il n'y a rien à cocher. Repart de 0 même si elle jouait déjà — « lancer le morceau », c'est du début."""
    if not on:
        if _ARR_TAKE.get("bk"):
            _ARR_TAKE["bk"] = False
            # la backing tourne sur le transport de la PRISE du morceau : c'est l'arrêt de la prise (qui suit, par
            # on_song « end ») qui arrête le transport. La couper ici posait B_MUTE sur le bus — et rien ne le
            # rouvrait après la prise (stop + mute pendant une prise = muet pour la suite)
            if getattr(state, "rec_with_song", False):
                return False
        _backing_ctl.stop()
        return False
    if _ARR_TAKE.get("bk"):
        return "free"                               # lancée par la prise, depuis 0 : rien à faire, ne pas la suivre
    if not (state.backing or {}).get("present") or not modes_mod.allows("backing", state.mode):
        return False
    # ⚠ LA BONNE backing : celle que le preset COURANT déclare. Une backing restée chargée d'un autre
    # morceau (ou d'une pré-écoute) n'a rien à faire sous cet arrangement.
    want = _arr_backing_slugs()
    if want and (state.backing or {}).get("slug") not in want:
        return False
    # ⚠ PENDANT UNE PRISE perf-rec, `restart` ne remet PAS la backing à 0 (il la démute : le transport
    # appartient à la prise) — sa position n'est alors pas le temps du morceau. Elle part, mais on ne la
    # SUIT pas : « free » = lancée, horloge du serveur.
    free = backing_mod._perf_recording()
    if at and not free:
        _backing_ctl.play_from_cursor()            # partie d'une section : déjà positionnée avant le décompte (§6.1)
    else:
        _backing_ctl.restart()
    return "free" if free else True


def _arr_backing_ctl(op, **kw):
    """Les gestes de répète côté backing (docs/live-pages.md §6) — le saut audio est fait par golem_backing.lua."""
    if op == "seek":
        # le DÉMUTE part avec la position, AVANT le décompte : au premier temps il ne reste que l'ordre de lecture (budget
        # de 15 ms — relecture de l'ingénieur du son)
        write_command({"action": "backing", "op": "mute", "on": False})
        _backing_ctl.seek(kw.get("pos") or 0.0)
    elif op == "pause":
        if (state.backing or {}).get("playing"):
            _backing_ctl.pause()
    elif op == "jump":
        _backing_ctl.jump(kw.get("at") or 0.0, kw.get("to") or 0.0)
    elif op == "loop":
        _backing_ctl.loop(kw.get("a") or 0.0, kw.get("b") or 0.0)
    elif op in ("loop_off", "jump_off"):
        _backing_ctl.loop_off()


def _arr_backing_slugs():
    """Les backings que le preset courant déclare (bloc backing, ligne/chanson comprises)."""
    p = load_preset(state.preset_id) if state.preset_id else None
    eff = recall_mod.effective_preset(p) if p else None
    return [x.get("slug") for x in (((eff or {}).get("backing") or {}).get("songs") or []) if x.get("slug")]


def _arr_sample(cue):
    """Un marqueur de la lane de samples (docs/arrangement.md §14).

    PRÉ-ARMÉ : `in_ms` dit dans combien de temps le son doit sortir — Reaper décompte lui-même
    plutôt que de jouer « à la réception », ce qui absorbe la gigue de ~30 ms du chemin de
    commande (§15, mesurée par tools/check-jitter.py).

    `ring` : on ne coupe PAS ce qui sonne déjà (§18) — la monophonie est la loi du PIED, pas
    celle de la lane, où un riser doit continuer pendant que l'impact tombe.

    ⚠ VETO DE MODE : un mode qui coupe « sample » coupe AUSSI l'automation (décision 
    2026-07-31) — sinon le veto mentirait exactement là où il compte, en Gig.
    """
    if not modes_mod.allows("sample", state.mode):
        return
    write_command({"action": "sample", "op": "play", "block": cue["block"], "idx": cue["idx"],
                   "samples": cue["samples"], "in_ms": cue.get("in_ms", 0),
                   "ring": bool(cue.get("ring"))})


def _arr_drums(op, idx=None):
    """LA BATTERIE DU MORCEAU (docs/arrangement.md §6, 2026-10-20) : le premier bloc `drums` du preset joué — au pied
    ou non. play = au premier temps, sur le groove de la section ; pattern = le groove suivant (le JSFX le cale sur la
    mesure) ; stop. Rend False sans boîte à rythmes, ou quand le mode la coupe (même veto que le pied) : l'arrangement
    n'insiste plus."""
    if not modes_mod.allows("drummachine", state.mode):
        return False
    p = load_preset(state.preset_id) if state.preset_id else None
    eff = recall_mod.effective_preset(p) if p else None
    blocks = drums_mod.blocks(eff or p)
    if not blocks:
        return False
    d = blocks[0]
    if op == "play":
        n = len(d.get("patterns") or [])
        if not n:
            return False
        _drums_ctl.song_play(d, min(int(idx or 0), n - 1))
    elif op == "pattern":
        n = len(d.get("patterns") or [])
        if n:
            _drums_ctl.song_pattern(d["block"], min(int(idx or 0), n - 1))
    elif op == "stop":
        _drums_ctl.stop(d["block"])
    return True


_arr_ctl = arrangement_mod.ArrangementCtl(
    apply_cue=_arr_cue,
    apply_sample=_arr_sample,
    on_change=lambda: (setattr(state, "arrangement", _arr_ctl.snapshot()), broadcast_threadsafe()),
    click_hold=_arr_click_hold,
    allowed=lambda: modes_mod.allows("arrangement", state.mode),
    on_song=lambda ev, info: _on_song(ev, info),
    backing=_arr_backing,
    transport=lambda: _backing_ctl.transport(),
    click_song=_arr_click_song,
    click_meter=_arr_click_meter,
    backing_ctl=_arr_backing_ctl,
    drums=_arr_drums)


# ── LE REC ET LE MORCEAU (docs/devices-people.md, lot F — décision 2026-09-15) ────────────────
# En RÉPÈTE : le conductor coche « Record with the song » -> la prise part avec le morceau et s'arrête
# avec lui. En SHOW : le REC part avec la PREMIÈRE chanson de la setlist, sauf s'il tourne déjà (lancé
# en coulisse depuis la tablette ou un téléphone). Jamais ailleurs : un REC arrêté exprès au milieu
# d'un show ne repart pas tout seul à la chanson suivante.
def _recording():
    return bool((_read_json(os.path.join(C.PRESETS_DIR, ".perf.json"), {}) or {}).get("recording"))


def _first_line_playing():
    song = state.song or {}
    try:
        from . import setlists as _sl
        sl = _sl.load(song.get("setlist") or _sl.active_id()) or {}
        lines = [ln for ln in sl.get("lines") or [] if _sl.pid_of(ln)]
        return bool(lines) and song.get("line") == lines[0].get("id")
    except Exception:
        return False


_ARR_TAKE = {"bk": False, "go": 0.0}    # la prise lancée par le morceau : backing annoncée ? départ différé à…


def _arr_song_backing_wanted(info):
    """Le morceau qui démarre lancera-t-il la backing ? (même règle que _arr_backing)"""
    if (info or {}).get("backing") is False:
        return False
    if not (state.backing or {}).get("present") or not modes_mod.allows("backing", state.mode):
        return False
    want = _arr_backing_slugs()
    return not want or (state.backing or {}).get("slug") in want


def _on_song(ev, info):
    from . import song_rec
    if ev == "start":
        _ARR_TAKE.update(bk=False, go=0.0)      # un morceau neuf : rien d'hérité du précédent
    asked = bool(getattr(state, "rec_with_song_asked", False))
    # LA CASE « Record » de la chanson (docs/arrangement.md) décide, d'où que vienne le départ. L'ancien
    # geste (Rec empilé sur le switch de l'arrangement) n'existe plus : la migration du lot 3 l'a changé en case
    # à chaque démarrage, et le tiroir MIDI assign dit qu'un bloc posé là ne part pas.
    if ev == "start" and (info or {}).get("record") is True:
        asked = True
    state.rec_with_song_asked = False
    # la CARTE décide jusqu'où va la prise (docs/modes.md §7 bis) — plus l'identifiant du mode
    set_scope = modes_mod.rec_scope(state.mode) == "set"
    action, state.rec_with_song = song_rec.decide(
        ev, asked=asked, set_scope=set_scope, first_line=set_scope and _first_line_playing(),
        recording=_recording(), with_song=bool(getattr(state, "rec_with_song", False)))
    if action == "start":
        # ⚠ LA PRISE ET LA BACKING DU MORCEAU (2026-10-07, test au pied de Paper Kite : « pas de backing ») :
        # une prise démarre le TRANSPORT ; non prévenu, golem_perfrec coupait le bus de la backing (« lecture non
        # voulue ») et rien ne le rouvrait — la backing jouait, muette. Même piège que Rec + Backing sur SW5 le
        # 2026-09-21, même remède : on ANNONCE la backing (`with_backing`), et c'est le transport de la prise qui
        # la joue depuis 0. La prise part au PREMIER TEMPS (après le décompte de l'arrangement, `delay`) — partie
        # au tap, elle aurait lancé les stems en avance d'autant. Un seul décompte (arrangement-controls §10.4).
        bk = _arr_song_backing_wanted(info)
        started = _foot_perf_toggle(with_backing=bk, countin=False, delay=(info or {}).get("count_in")) is True
        # prise REFUSÉE (disque, mode) : la backing ne viendra pas du transport de la prise — l'arrangement la
        # lancera lui-même (_arr_backing), comme sans prise
        _ARR_TAKE.update(bk=bk and started,
                         go=(time.time() + float((info or {}).get("count_in") or 0)) if started else 0.0)
        log_perf.info("prise lancée avec le morceau" + (" (première chanson du set)" if set_scope else ""))
    elif action == "stop":
        write_command({"action": "perf_rec", "on": False})
    elif ev == "end" and _ARR_TAKE.get("go", 0) > time.time():
        # arrêté PENDANT le décompte : la prise différée n'a pas encore démarré (`recording` faux) — on
        # l'annule, sinon elle partirait seule dans le silence (golem_perfrec lâche son départ différé)
        write_command({"action": "perf_rec", "on": False})
    if ev == "end":
        _ARR_TAKE.update(go=0.0)


# bloc STANDARD (grille d'accords jouée par le rack) : un switch, tap = play/stop,
# maintenu = relance. La FORME reste à l'arrangement (docs/standards.md §3).
_std_ctl = standards_mod.StandardControl(
    emit=lambda op, pm: _standard_cmd(op, pm),
    on_change=lambda: (setattr(state, "standard", _std_ctl.snapshot()), broadcast_threadsafe()))


def _preset_bpm():
    """Le tempo du preset courant — celui que le rack pose dans Reaper au rappel.

    C'est LUI qui choisit la prise d'un groove joué (voir standards.pack_pattern) : la grille
    dit à quel tempo le morceau se joue d'habitude, le preset dit à quel tempo il se joue CE
    SOIR. Prendre celui de la grille ferait tourner un groove à 80 sous un morceau à 120.
    """
    if not state.preset_id:
        return None
    p = load_preset(state.preset_id) or {}
    return p.get("bpm")


def _standard_cmd(op, pm):
    """Rend la grille et lance/arrête le lecteur. Le rendu vit ICI (pas dans le contrôleur) :
    c'est un calcul lourd qu'on ne veut pas dans le thread du lecteur MIDI."""
    if op != "play":
        write_command({"action": "standard", "op": "stop"})
        return
    if not modes_mod.allows("standard", state.mode):           # veto de mode : on ne lance pas, on le dit
        log_standard.warning("standard : lecture refusée — service coupé par le mode courant")
        return
    pm = pm or {}
    # les réglages de jeu vivent dans les params DU BLOC : le pied joue donc exactement ce que le tiroir montre — et
    # le rendu d'un bloc (preview.render_block) lit les mêmes, par la même fonction
    b = standards_mod.build(pm.get("standard"), **standards_mod.block_kwargs(pm, _preset_bpm()))
    if not b:
        log_standard.warning(f"grille introuvable : {pm.get('standard')!r}")
        return
    write_command({"action": "standard", "op": "play", "standard": pm.get("standard"),
                   "file": b["file"], "loop": True, "arp": pm.get("arp") or "",
                   "kit": pm.get("kit") or "black-pearl",
                   "keys": b["parts"].get("keys", True),
                   "bass": b["parts"].get("bass", True),
                   "drums": bool(b["parts"].get("drums")),
                   "guitar": bool(b["parts"].get("guitar"))})


def _on_stomp_edge(sw, on):
    """Fronts Note du FCB (thread lecteur, latence critique — pas de _off_thread : le press
    d'un REC/PLAY/sample EST le timing musical). Précédence : backing-track > sample > looper.
    Les blocs sample sont pilotés par les fronts (tap = lance/avance, appui-long = stop) ; le
    chemin CC (_do_stomp) leur cède (comme le looper) pour éviter le double-déclenchement."""
    # LE SWITCH DE L'ARRANGEMENT LANCE LE MORCEAU (2026-10-07) : il passe AVANT la backing — c'est lui qui
    # la lance (§8). Une backing posée sur le même switch ne doit pas lui voler le geste : avant, elle
    # gagnait, et l'arrangement posé à côté ne partait jamais du pied.
    # chef d'orchestre : tap = lance / section suivante / resync · appui long = arrêt (§8). Le MORCEAU tel
    # qu'il se joue (ligne / chanson), pas le preset brut : ses parties vivent sur la chanson (§4 bis) — le
    # pied démarrait « no arrangement in this preset », toujours (trouvé le 2026-10-07)
    if state.arr_switch is not None and sw == state.arr_switch:
        _arr_ctl.on_edge(sw, on, recall_mod.effective_preset(load_preset(state.preset_id)) if state.preset_id else None)
        return
    if recall_mod.backing_sw is not None and sw == recall_mod.backing_sw:
        if _rec_with_backing(sw):
            return          # le CC de ce switch a déjà lancé prise + backing : un seul geste, pas deux
        _backing_ctl.on_edge(sw, on)
        return
    smp = (state.sample_switches or {}).get(sw)
    if smp:
        _sample_ctl.on_edge(sw, on, smp.get("block"), smp.get("samples"), smp.get("foot_idx"))
        return
    drm = (state.drum_switches or {}).get(sw)
    if drm:
        _drums_ctl.on_edge(sw, on, drm.get("block"), drm.get("patterns"), drm.get("fills"), drm.get("kit"),
                           sequence=drm.get("sequence"), seq_mode=drm.get("seq_mode"))
        return
    std = (state.standard_switches or {}).get(sw)
    if std:
        _std_ctl.on_edge(sw, on, std.get("params"))
        return
    # ⚠ REPLI LOOPER BORNÉ À LA RANGÉE HAUTE. Depuis que les fronts des switches 1-5 remontent
    # aussi (foot.py, 2026-08-07), un appui de SCÈNE non revendiqué arriverait ici et piloterait
    # le looper — un switch de scène qui lance une boucle, c'est la panne qu'on ne comprend pas.
    # Les revendications explicites ci-dessus (backing/sample/drums/standard/arrangement) valent,
    # elles, pour les dix switches : elles nomment leur switch.
    if sw in _looper_ctl.switches() and state.looper.get("enabled"):
        _looper_ctl.on_edge(sw, on)


def _off_thread(fn):
    """Décale un callback pied vers la boucle asyncio : le thread lecteur MIDI ne doit JAMAIS
    compiler un rig ni faire de gros I/O (il bloquerait le parsing des events suivants — treadle),
    et une exception n'y tuerait plus la session aseqdump (audit 2026-07-07 P1)."""
    def wrap(*a):
        if _loop:
            _loop.call_soon_threadsafe(lambda: fn(*a))
        else:
            fn(*a)
    return wrap


@app.on_event("startup")
async def _startup():
    global _loop, _foot
    _loop = asyncio.get_running_loop()
    from . import reach as reach_mod                 # http://golem.local : mDNS + renvoi du port 80
    reach_mod.start()
    # LA BACKING APPARTIENT À LA CHANSON (docs/song-backing.md §5) : l'ancien `backing.songs` des presets recopié sur
    # leurs chansons et leurs lignes — idempotent, rien d'effacé, hors de la boucle (il lit toutes les setlists)
    def _migrate_backing():
        try:
            from . import backing_owner
            n = backing_owner.migrate()
            if n:
                log_boot.info(f"backing : {n} chanson(s)/ligne(s) reçoivent la backing de leur preset")
        except Exception as e:
            log_boot.warning(f"backing : migration non faite : {e}")
    threading.Thread(target=_migrate_backing, name="backing-migrate", daemon=True).start()
    try:                                             # un lot « Separate a folder » interrompu reprend (separation-batch.md)
        from . import separation_batch
        separation_batch.resume()
    except Exception as e:
        log_boot.warning(f"separation batch : reprise non faite : {e}")
    if os.environ.get("GOLEM_DESKTOP_BACKEND") == "1":
        from provision.desktop import start_reaper_window_guard
        start_reaper_window_guard()
    try:
        from . import boot_progress
        boot_progress.check_services_async()           # golem.fm appairé ? TONE3000 connecté ? (écran de chargement)
        boot_progress.start_periodic()                  # … puis toutes les 5 min (pastilles de Settings)
        from . import health
        health.start()                                  # Settings ▸ Health : les faits toutes les 5 s (docs/health.md)
    except Exception as _e:
        _swallowed(_e)
        routes_network.start_win_fallback()     # pas de réseau en 30 s -> point d'accès (scène, Windows)
    os.makedirs(C.RUNTIME_DIR, exist_ok=True)
    # L'USINE (docs/factory.md) : pose ce qui manque de library/factory/ AVANT le rappel de démarrage — l'accueil peut
    # être un preset d'usine. Jamais d'écrasement, jamais de résurrection d'un objet supprimé (bridge/factory.py).
    try:
        from . import factory as factory_mod
        factory_mod.seed()
    except Exception as _e:
        _swallowed(_e)
    # l'instrument choisi à l'installation (bridge/first_run.py) : une fois, après l'usine — sa banque et son accueil
    # sont des objets d'usine — et avant le rappel de démarrage qui lit l'accueil
    try:
        from . import first_run
        first_run.apply()
    except Exception as _e:
        _swallowed(_e)
    # ReaScript n'hérite pas toujours de l'environnement du bridge (.env, lancement
    # autonome). Ces deux pointeurs sont écrits AVANT les autres tâches de démarrage.
    with contextlib.suppress(Exception):
        os.makedirs(C.REAPER_RESOURCE_DIR, exist_ok=True)
        for name, value in (("golem-root.txt", C.ROOT), ("golem-runtime.txt", C.RUNTIME_DIR)):
            fd, tmp = tempfile.mkstemp(dir=C.REAPER_RESOURCE_DIR, prefix=f".{name}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as ptr:
                    ptr.write(value)
                os.replace(tmp, os.path.join(C.REAPER_RESOURCE_DIR, name))
            finally:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
    # lot 8 (docs/diagnostics.md §4.1) : la session de diagnostic s'ouvre AVANT tout le reste — si
    # la précédente n'a pas été clôturée (rack débranché), son bilan partira avec le paquet `boot`
    from . import diag
    diag.boot()
    # les batteries d'usine reviennent au démarrage si elles manquent (docs/drums-kit.md §2, 2026-09-15)
    try:
        from . import kits as _kits
        if (seeded := _kits.seed_factory()):
            log_boot.info(f"batteries d'usine ressemées : {', '.join(seeded)}")
    except Exception as _e:
        log_boot.warning(f"graines de batteries : {_e}")
    # LE PREMIER ÉCRAN D'UN GOLEM SANS FENÊTRE (docs/devices-people.md, lot C) : lancé en server
    # (GOLEM_LAUNCH, posé par le lanceur — docs/installer.md §4) et aucun appareil admin -> un code
    # d'appairage est publié dans le journal (et `golem server` l'affiche)
    try:
        if os.environ.get("GOLEM_LAUNCH") == "server" and not auth_mod.admin_exists():
            pc = auth_mod.create_pair_code()
            log_boot.warning(f"rack sans écran et sans appareil admin — code d'appairage {pc['code']} "
                             f"(10 min) : ouvrir http://<ip>:8770/app/pair.html sur la tablette")
    except Exception as _e:
        log_boot.warning(f"code d'appairage : {_e}")
    recall_mod.attach_loop(_loop)        # le moteur planifie ses différés (+0,8 s) sur CETTE boucle
    _arr_ctl.attach_loop(_loop)          # le pied crée sa tâche DANS la boucle, pas dans le thread MIDI
    reaper.start()
    # Lecteur FCB : le pied passe désormais par le bridge (scène/stomp/treadle Whammy).
    # scène/stomp/recall (lourds : load+compile+write) -> boucle asyncio ; treadle/volume
    # (légers, latence critique) restent dans le thread lecteur.
    # Quel pédalier est branché : on applique d'abord le contrat de l'appareil DÉCLARÉ (le
    # lecteur doit être juste dès la première note), puis la sonde tourne en tâche de fond et
    # corrige si une puce s'identifie. Bloquer le démarrage sur un pédalier éteint serait pire
    # que de commencer sur une déclaration.
    from . import pedalboard

    def _apply_pedalboard(_act=None):
        wire = pedalboard.wire_contract()
        foot.set_device(wire)
        # L'écran doit montrer ce que montre le PÉDALIER : son décalage d'affichage suit donc
        # l'appareil, et voyage jusqu'à l'UI par l'état. Le contrat sur le fil, lui, ne bouge pas.
        # La sonde tourne dans son propre thread : si le décalage change, il faut pousser l'état,
        # sinon l'écran garde l'ancienne numérotation jusqu'au prochain événement.
        if state.bank_base != wire["display_base"]:
            state.bank_base = wire["display_base"]
            state.touch()
            with contextlib.suppress(Exception):
                broadcast_threadsafe()

    _apply_pedalboard()
    pedalboard.on_change(_apply_pedalboard)
    _foot = foot.FootReader(
        on_scene=_off_thread(lambda sc, val=None: (_on_foot_scene(sc, val), broadcast_threadsafe())),
        on_stomp=_off_thread(lambda b, want=None: (_do_stomp(b, want), broadcast_threadsafe())),
        # recall = soumission directe au worker du moteur (FIFO) : le thread lecteur ne fait
        # que déposer, le moteur notifie les WebSockets à la fin — plus de compile sur la boucle
        on_recall=lambda slot, source=None: recall_mod.schedule_slot(slot, source),
        on_treadle=lambda v: (_on_pedal("exp2", v), broadcast_threadsafe()),
        on_volume=lambda v: (_on_pedal("exp1", v), broadcast_threadsafe()),
        on_stomp_edge=_on_stomp_edge,   # direct (pas _off_thread) : le press d'un REC = timing musical
        on_select=_on_foot_select,
    )
    _foot.select_blocked = lambda sw: bool(state.looper.get("enabled")) and sw in _looper_ctl.switches()
    _foot.start()
    pedalboard.detect_async()
    monitors.init(_broadcast)
    # transcription : son avancement doit ARRIVER à l'écran, sinon un travail de 30 s est
    # indiscernable d'un bouton cassé (docs/archive/tablature-study.md §12).
    def _tr_changed():
        state.transcribe = transcribe_mod.snapshot()
        state.touch()
        broadcast_threadsafe()
    transcribe_mod.set_on_change(_tr_changed)
    state.transcribe = transcribe_mod.snapshot()
    monitors.init_looper(_looper_ctl)
    monitors.init_backing(_backing_ctl)
    monitors.init_sample(_sample_ctl)
    monitors.init_drums(_drums_ctl)
    monitors.init_standard(_std_ctl)
    asyncio.create_task(monitors._monitor_reaper())
    asyncio.create_task(monitors._monitor_audio())
    asyncio.create_task(monitors._poll_tuner())
    asyncio.create_task(monitors._poll_looper())
    asyncio.create_task(monitors._poll_backing())
    asyncio.create_task(monitors._poll_perf())
    asyncio.create_task(monitors._poll_click())
    asyncio.create_task(monitors._poll_cards())
    asyncio.create_task(monitors._poll_hotplug())   # « quelque chose vient d'apparaître » (chantier ⑤)
    asyncio.create_task(monitors._poll_sample())
    asyncio.create_task(monitors._poll_drums())
    asyncio.create_task(monitors._poll_standard())
    # le DOSSIER SURVEILLÉ (plan-song-sharing lot 1.4) : tout .golem déposé dans ~/golem-inbox est installé
    from . import inbox as _inbox
    from . import inventory as _inventory
    asyncio.create_task(_inbox.watch(on_change=lambda evs: (_inventory.request_publish(), broadcast_threadsafe())))
    # les .golem de golem.fm (lot 2) : un tirage 20 s après le démarrage — un rack éteint se rattrape seul
    async def _golem_boot_pull():
        await asyncio.sleep(20)
        from . import golem_pull as _gp
        with contextlib.suppress(Exception):
            await asyncio.to_thread(_gp.refresh_all)
    asyncio.create_task(_golem_boot_pull())
    # la COPIE DU PRESET dans chaque .golem (golem-format.md §9, 2026-10-08) : rafraîchie en tâche de fond,
    # une chanson par passage, quand son preset est stable depuis 60 s — et JAMAIS pendant que ça joue (le zip
    # entier est réécrit : des dizaines de Mo de disque au milieu d'une prise, non)
    async def _golem_preset_snapshots():
        from . import songs as _songs
        while True:
            await asyncio.sleep(30)
            with contextlib.suppress(Exception):
                busy = ((state.backing or {}).get("playing") or backing_mod._perf_recording()
                        or bool(getattr(_arr_ctl, "_live", False)))
                if busy:
                    continue
                todo = [d["id"] for d in _songs.list_all() if _songs.preset_snapshot_stale(d["id"])]
                if todo:
                    await asyncio.to_thread(_songs.snapshot_preset, todo[0])
    asyncio.create_task(_golem_preset_snapshots())
    # la PHOTO DE L'ARTISTE dans les .golem qui n'en ont pas (artist_photos.py) : une chanson par passage, demandée
    # à golem.fm, jamais pendant que ça joue ; après un échec (injoignable, erreur), on attend 10 min
    async def _golem_artist_photos():
        from . import artist_photos as _ap
        await asyncio.sleep(90)
        while True:
            pause = 30
            with contextlib.suppress(Exception):
                busy = ((state.backing or {}).get("playing") or backing_mod._perf_recording()
                        or bool(getattr(_arr_ctl, "_live", False)))
                if not busy and await asyncio.to_thread(_ap.step) == "error":
                    pause = 600
            await asyncio.sleep(pause)
    asyncio.create_task(_golem_artist_photos())
    # L'INVENTAIRE sur golem.fm (song-sharing.md §2.7) : 40 s après le démarrage, puis toutes les 10 min — un diff vide
    # ne coûte qu'une lecture des manifestes. Les dépôts et les tirages publient aussi d'eux-mêmes (request_publish).
    async def _golem_inventory():
        await asyncio.sleep(40)
        while True:
            with contextlib.suppress(Exception):
                if not backing_mod._perf_recording():
                    await asyncio.to_thread(_inventory.publish)
            await asyncio.sleep(600)
    asyncio.create_task(_golem_inventory())
    # les DOSSIERS DE CHANSONS (song-folders.md §2.5) : un passage 20 s après le démarrage, puis toutes les 10 min.
    # Un passage ne fait que des `stat` ; seuls les fichiers changés sont relus.
    async def _song_folders_start():
        await asyncio.sleep(20)
        from . import song_folders
        if song_folders.folders():
            song_folders.request_scan()
    asyncio.create_task(_song_folders_start())
    # uplink tab-follow : pousse la position backing vers golem.fm (dort si pas appairé)
    # + reçoit les commandes du laptop (v2.1 : seek/play/pause/boucle A/B)
    from . import compo, follow_uplink
    compo.init(on_change=broadcast_threadsafe)          # cibles « Follow Golem » -> /live + Companion
    compo.bind(armed_start=_riff_armed_start, restore=_riff_restore,   # la prise armée (docs/compo.md §12)
               standard_start=_std_take_start, standard_restore=_std_take_restore,   # la prise de standard (docs/compo.md §11)
               tap=_compo_tap)                                          # le départ depuis golem.fm (§13)
    follow_uplink.init(_backing_ctl)
    from . import karaoke as _karaoke                # docs/karaoke.md : commandes du WS de follow
    _karaoke.init(_backing_ctl)
    asyncio.create_task(follow_uplink.run())
    # jobs golem.fm (install/remove/recall) : filet périodique, silencieux si pas appairé
    from . import tones_jobs
    tones_jobs.start_poller()
    # status rig -> golem.fm (Addendum 13) : push léger ~5 min (versions + disque), silencieux sinon
    from . import rigstatus
    rigstatus.start_pusher()
    # golem.fm/connect : le rack dit où le trouver (case « Let golem.fm find this rack », silencieux sinon)
    with contextlib.suppress(Exception):
        from . import connect as _connect
        _connect.start()
    # lot 8 : le paquet `boot` part une fois Reaper connecté (90 s max), après ce qui attendait
    asyncio.create_task(diag.boot_task())
    # « pack à écho » : le verdict des IR se relit au démarrage (fichiers changés seulement)
    with contextlib.suppress(Exception):
        from . import ir_quality
        ir_quality.scan_async()
    # lot 2 setlists : les arrangements que les presets portaient (config.arr) passent sur les LIGNES,
    # une fois — le preset garde une donnée morte, le Designer ne la montre plus (arrangement.md §4)
    try:
        from . import setlists as _sl
        moved = _sl.migrate_legacy_arrangements()
        if moved:
            log_boot.info(f"arrangements migrés vers les lignes de setlist : {moved}")
    except Exception as e:
        log_boot.warning(f"migration des arrangements : {e}")
    # 2026-09-16 (docs/arrangement.md §4 bis) : la PÉDALE de l'arrangement remonte de la chanson au RIG.
    # Une pédale appartient au pédalier ; rangée dans la ligne, elle pouvait différer d'un morceau à
    # l'autre sur le même rig. Idempotente : ne touche pas un bloc qui a déjà sa pédale.
    try:
        from . import arrangement as _arrmod
        if (_mg := modes_mod.migrate_show_to_gig()):
            log_boot.info("mode « show » fusionné dans « gig » (docs/modes.md §7 bis) — "
                          + ("carte locale archivée en show.json.merged" if _mg["archived"] else "rien à archiver")
                          + (f" (elle déclarait band={_mg['band']} card={_mg['card']} — Gig garde les siens)" if _mg["band"] or _mg["card"] else "")
                          + (" · le rack était EN Show : remis sur Gig" if _mg["switched"] else ""))
        feet = _arrmod.migrate_foot_to_rig()
        if feet:
            log_boot.info(f"pédale d'arrangement posée sur le rig : {feet}")
        # 2026-10-07 (docs/arrangement.md §7, lot 3) : les blocs EMPILÉS sur le switch de l'arrangement
        # deviennent des cases « When the song starts » de leurs chansons, et quittent le switch
        stacks = _arrmod.migrate_stacks_to_starts()
        for x in stacks:
            log_boot.info(f"« {x['name']} » : {', '.join(x['moved'])} retiré(s) du switch {x['switch']} de l'arrangement "
                          f"— case(s) posée(s) sur {x['songs']} chanson(s) et {x['lines']} ligne(s) libre(s)")
    except Exception as e:
        log_boot.warning(f"migration de la pédale d'arrangement : {e}")
    # boost CPU du mode courant (Gig/Show = on) : un bridge relancé en plein set ne doit pas le perdre
    import threading as _th
    from . import routes_system as _sys
    _th.Thread(target=lambda: _sys.apply_perf_for_mode(state.mode, " (démarrage)"), daemon=True).start()
    # roster multi-espaces : le cache local rattrape golem.fm au boot (lot B §4). Silencieux
    # si non appairé ; en thread, parce qu'un serveur injoignable ne doit pas retarder le
    # démarrage du rig — le cache fait foi entre deux synchros, c'est tout son intérêt.
    import threading as _th
    with contextlib.suppress(Exception):
        from . import roster
        _th.Thread(target=roster.sync, daemon=True).start()
    # le monteur : les prises taguées montent hors temps de jeu (lot B). Il se tait pendant
    # un REC et en mode Gig, et ne fait rien tant que rien n'est tagué.
    with contextlib.suppress(Exception):
        from . import uploader
        uploader.start_worker()
    asyncio.create_task(recall_mod.boot_recall())


@app.on_event("shutdown")
async def _shutdown():
    """lot 8 (docs/diagnostics.md §4.2) : à l'arrêt (SIGTERM systemd, reload.sh), clôturer la
    session et fabriquer le paquet `session` — ÉCRIRE d'abord, envoyer ensuite (5 s max). Hors
    boucle : la boucle est en train de mourir, et un envoi qui traîne ne doit rien bloquer."""
    from . import diag
    try:
        await asyncio.get_running_loop().run_in_executor(None, diag.shutdown_report)
    except Exception as e:
        log_boot.warning(f"paquet session à l'arrêt : {e}")


# _boot_recall vit désormais dans bridge/recall.py (boot_recall) — extrait avec le moteur.


# ── API REST ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    # PENDANT UN ARRÊT, le bridge répond encore jusqu'à ~20 s (projet enregistré, REAPER fermé) : il ne doit plus
    # dire « ok ». Sinon le lanceur, relancé dans cet intervalle, croyait golem en marche, ouvrait une fenêtre sur
    # ce bridge mourant et n'en démarrait pas d'autre — « Bridge link lost » jusqu'à une seconde relance (2026-10-10)
    if getattr(state, "stopping", False):
        return {"ok": False, "stopping": True}
    # `screens` : les pages de l'app connectées (WebSocket) — le lanceur attend la PREMIÈRE avant de lancer REAPER,
    # pour que l'écran de chargement se voie (2026-10-11 : « la fenêtre du golem s'ouvre en premier »)
    return {"ok": True, "reaper_connected": state.reaper_connected, "screens": len(_clients)}


@app.get("/api/state")
def get_state():
    return state.snapshot()


# ── verrou live (armé depuis la page Live, gèle le Designer sur tous les écrans) ─
@app.post("/api/live-lock")
async def live_lock(body: dict):
    state.live_lock = bool(body.get("on"))
    await _broadcast()
    return {"ok": True, "live_lock": state.live_lock}


# ── une pédale EXP bougée À L'ÉCRAN (page Live, doigt ou souris) ──────
@app.post("/api/exp")
async def exp_set(body: dict):
    """{pedal: 'exp1'|'exp2', value: 0..127} — exactement le chemin de la pédale physique
    (`_on_pedal`) : la valeur va au RÔLE du moment (volume, bloc assigné, sinon treadle Whammy),
    pas à un potard choisi ici. Sans pédalier branché, l'écran remplace le pied ; avec, le
    dernier qui bouge gagne, comme deux mains sur un même potard."""
    phys = body.get("pedal")
    if phys not in ("exp1", "exp2"):
        return JSONResponse({"error": "pedal must be 'exp1' or 'exp2'"}, status_code=400)
    try:
        v = max(0, min(127, int(round(float(body.get("value"))))))
    except (TypeError, ValueError):
        return JSONResponse({"error": "value must be a number 0-127"}, status_code=400)
    _on_pedal(phys, v)
    await _broadcast()
    return {"ok": True, "pedal": phys, "value": v}


# ── rôles des pédales d'expression (volume / bloc contextuel, exclusifs) ──────
@app.get("/api/pedals")
def get_pedals():
    return state.pedals


@app.post("/api/pedals")
async def set_pedals(body: dict):
    """Assigne le rôle volume à 'exp1' ou 'exp2' (le rôle bloc prend l'autre, toujours exclusifs).
    Accepte {volume: ...} ou {block: ...}. Persisté dans config/pedals.json + broadcast immédiat."""
    v = body.get("volume")
    if v is None and body.get("block") in ("exp1", "exp2"):
        v = "exp2" if body["block"] == "exp1" else "exp1"
    if v not in ("exp1", "exp2"):
        return JSONResponse({"error": "volume|block doit valoir 'exp1' ou 'exp2'"}, status_code=400)
    state.pedals = {"volume": v, "block": "exp2" if v == "exp1" else "exp1"}
    with contextlib.suppress(Exception):
        store._write_json_atomic(_PEDALS_PATH, state.pedals, indent=1)
    await _broadcast()
    return state.pedals


# Le moteur de recall vit dans bridge/recall.py : _rig_is_live, _scene_shape, _do_recall,
# _stomp_states, les banks FCB (slot->preset) et _emit_sandbox y sont devenus rig_is_live,
# scene_shape, do_recall, do_recall_slot, fcb_setlist, emit_sandbox… (audit 2026-08-12 P2).


# ── pédales EXP : deux RÔLES (volume / bloc contextuel), deux pédales physiques ─
# Les pédales physiques sont figées par le flash FCB (EXP1 = ExpA = CC7, EXP2 = ExpB = CC11) ;
# quel rôle chacune joue est une CONFIG GLOBALE (config/pedals.json, page Système ▸ Pedalboard).
# Les presets ne référencent QUE les rôles (clé historique `exp2` = assignation du rôle bloc) —
# ils survivent donc à un échange volume<->bloc sans migration.
# Cibles résolues au moment de l'émission du rig. Rôle volume : preset.exp1 explicite > 1er bloc
# volume (sinon affichage seul). Rôle bloc : preset.exp2 explicite > bloc wah présent > Whammy.
# Au CC : lookup pur en mémoire + un envoi OSC normalisé (ou rtmidi pour la Whammy) — zéro I/O disque.
_EXP_VOL = {"assign": None}                  # {block, param, min, max} | None = rien (Live seulement)
_EXP_BLK = {"assign": None, "label": None}   # {block, param, min, max} | None = Whammy (compat)
_PEDALS_PATH = os.path.join(C.ROOT, "config", "pedals.json")


def _load_pedals():
    """Rôles -> pédale physique, depuis config/pedals.json. Toujours exclusifs (bloc = l'autre)."""
    try:
        v = json.load(open(_PEDALS_PATH)).get("volume")
    except Exception:
        v = None
    v = v if v in ("exp1", "exp2") else "exp1"
    return {"volume": v, "block": "exp2" if v == "exp1" else "exp1"}


state.pedals = _load_pedals()
# rien reçu encore : le rôle VOLUME part à 100 % (0 dB, ce que joue le bloc volume du preset), l'autre à 0 (_exp_bake)
setattr(state, state.pedals.get("volume", "exp1"), 127)
_LIVEMAP = {"mtime": None, "map": None}
_FXDEFS = {"mtime": None, "map": None}
_LIVEMAP_PATH = os.path.join(C.PRESETS_DIR, ".livemap.json")
_EFFECTS_PATH = os.path.join(C.ROOT, "library", "catalog", "effects.json")


def _cached_json(cache, path, transform):
    try:
        mt = os.path.getmtime(path)
        if cache["mtime"] != mt:
            cache["map"] = transform(json.load(open(path)))
            cache["mtime"] = mt
    except Exception:
        cache["map"] = None
    return cache["map"]


def _fxdefs():
    return _cached_json(_FXDEFS, _EFFECTS_PATH,
                        lambda d: {e["type"]: e for e in d.get("effects", [])})


def _iter_ui_blocks(preset):
    """TOUS les blocs d'un preset, v2 (lanes) comme legacy (guitar/voice).

    ⚠ CETTE FONCTION NE LISAIT QUE LE LEGACY, et c'est ce qui a tué les deux pédales
    d'expression sur tout preset moderne (2026-09-20 : « la pédale EXP 2 volume ne marche
    pas », sur Paper Kite, avant une répète).

    La chaîne est ici : les MIROIRS legacy (`preset.guitar`, `preset.voice`) ne sont régénérés que
    pour les lanes dont l'id est `guitar`, `voice` ou `keys` — c'est `store.LEGACY_KEY`, et c'est
    volontaire. Mais une lane moderne s'appelle `guitar-1` (l'id DÉRIVE de l'entrée depuis le
    2026-09-09), donc `preset.guitar` est ABSENT, donc cette fonction ne voyait AUCUN bloc, donc
    `_set_exp_vol_from` ne trouvait jamais le bloc `volume` qui était pourtant là, dans la lane.

    Une panne muette exemplaire : rien ne casse, rien n'est journalisé, la pédale envoie bien son
    CC (`state.exp2` = 127) et l'écran affichait même « EXP2 Volume ». Tout était vrai sauf la
    cible. C'est la classe « une couche ne voit pas l'autre » de CLAUDE.md — le code qui pose la
    garde ne ment pas, la couche du dessous ne lui répond simplement plus.

    On lit `preset["lanes"]` EN DIRECT, sans passer par `store.lanes_of` : lister des blocs ne
    demande pas de résoudre les entrées, et cette fonction est appelée à chaque émission du rig.
    """
    lanes = preset.get("lanes")
    if isinstance(lanes, list) and lanes:
        for L in lanes:
            c = (L or {}).get("chain") or {}
            for b in (c.get("pre") or c.get("chain") or []):
                if isinstance(b, dict):
                    yield b
            for br in ((c.get("split") or {}).get("branches") or []):
                for b in (br.get("blocks") or []):
                    if isinstance(b, dict):
                        yield b
            for b in (c.get("post") or []):
                if isinstance(b, dict):
                    yield b
        return
    g = preset.get("guitar") or {}
    for b in g.get("pre") or g.get("chain") or []:
        yield b
    for br in ((g.get("split") or {}).get("branches") or []):
        for b in br.get("blocks") or []:
            yield b
    for b in g.get("post") or []:
        yield b
    for b in (preset.get("voice") or {}).get("chain") or []:
        if isinstance(b, dict):                       # rétro-compat : anciens types nus ignorés
            yield b


def _exp_blk_assign(preset):
    """La cible du rôle BLOC, calculée sans rien poser : explicite (preset.exp2) > 1er bloc wah* > None."""
    a = preset.get("exp2")
    # assignation ORPHELINE (le bloc a été supprimé mais exp2 a survécu — presets d'avant le
    # fix rmBlock 2026-07-23) : ignorée -> repli auto wah*/Whammy, plus de « Wah » fantôme
    if a and not any(b.get("id") == a.get("block") for b in _iter_ui_blocks(preset)):
        a = None
    if not a:
        for b in _iter_ui_blocks(preset):
            if str(b.get("type", "")).startswith("wah") or b.get("type") == "autowah":
                a = {"block": b.get("id"), "param": "wah", "min": 0, "max": 1}
                break
    return a


def _set_exp_blk_from(preset):
    """Cible du rôle BLOC pour le rig émis : explicite (preset.exp2) > 1er bloc wah* > None (Whammy)."""
    a = _exp_blk_assign(preset)
    _EXP_BLK["assign"] = a
    if a:
        # label depuis le PRESET (pas la livemap : elle est écrite par golem_rig APRÈS l'émission)
        blk = next((b for b in _iter_ui_blocks(preset) if b.get("id") == a.get("block")), {})
        btype = blk.get("type")
        _EXP_BLK["type"] = btype
        # midi-pedal : le RELAIS treadle (patron whammy-dt) a besoin du descripteur -> on garde le ref,
        # et le label est le NOM de la pédale (posé à l'ajout), pas le générique « MIDI Pedal »
        _EXP_BLK["ref"] = str(blk.get("ref")) if btype == "midi-pedal" and blk.get("ref") else None
        _EXP_BLK["label"] = ((btype == "midi-pedal" and blk.get("label")) or
                             ((_fxdefs() or {}).get(btype) or {}).get("name") or a.get("param") or "FX")
    else:
        # sémantique 2026-07-23  : EXP1 = pédale « bloc » LIBRE ; la Whammy DT a sa PROPRE
        # pédale physique. Sans assignation -> EXP1 ne pilote RIEN (fini le relais implicite).
        _EXP_BLK["type"] = None
        _EXP_BLK["ref"] = None
        # un preset LOOPER : la pédale libre dose toutes les boucles (2026-10-14) — l'écran le dit
        from . import rig as _rig                           # (import manquant : NameError avalé — ruff F821, 2026-10-15)
        _EXP_BLK["label"] = "Loop level" if _rig.looper_enabled(preset) else "—"
    state.exp2_target = _EXP_BLK["label"]


def _apply_exp(a, v):
    """Pousse une pédale EXP (0-127) sur le param assigné via la livemap. Retourne False si la cible
    est absente/introuvable. Appelé des THREADS lecteurs : rester léger (lookup mémoire + un UDP)."""
    if not a:
        return False
    lm = _cached_json(_LIVEMAP, _LIVEMAP_PATH, lambda d: d)
    blk = ((lm or {}).get("blocks") or {}).get(a.get("block"))
    pm = (blk or {}).get("params", {}).get(a.get("param"))
    if not (blk and pm):
        return False
    amin, amax = float(a.get("min", 0)), float(a.get("max", 1))
    raw = amin + (v / 127.0) * (amax - amin)              # unités du potard (déf. effects.json)
    d = ((_fxdefs() or {}).get(blk.get("type")) or {})
    pdef = next((p for p in d.get("params", []) if p.get("id") == a.get("param")), {})
    scale = (pdef.get("map") or {}).get("scale")
    if scale:
        raw = raw * scale                                  # ex. % -> port 0..1 (boost)
    pmin, pmax = pm.get("pmin", 0), pm.get("pmax", 1)
    norm = (raw - pmin) / (pmax - pmin) if pmax != pmin else 0
    reaper.set_fx_param(blk["track"], blk["fx"], pm["p"], norm)
    return True


def _exp_vol_assign(preset):
    """La cible du rôle VOLUME, calculée sans rien poser : explicite (preset.exp1) > 1er bloc volume.
    Balaye -60 dB (talon ≈ silence) -> 0 dB (pointe = unité) ; le +6 du potard reste à la main."""
    a = preset.get("exp1")
    if not a:
        for b in _iter_ui_blocks(preset):
            if b.get("type") == "volume":
                a = {"block": b.get("id"), "param": "gain", "min": -60, "max": 0}
                break
    return a


def _set_exp_vol_from(preset):
    """Cible du rôle VOLUME pour le rig émis (voir _exp_vol_assign)."""
    _EXP_VOL["assign"] = _exp_vol_assign(preset)


# ── LA POSITION DES PÉDALES SUIT D'UN PRESET À L'AUTRE (2026-11-06, décision du mainteneur) ───────────────────────────
# Le pédalier ne dit sa position que quand on BOUGE la pédale (la UnO2 n'a rien à interroger). Avant, un rappel posait la
# cible de chaque pédale sans lui donner la valeur connue : le bloc volume jouait au gain du preset (0 dB) pendant que
# /live affichait 0 %, et chaque changement de scène remettait le gain du preset (reapply_scene pose l'état complet).
# Maintenant la valeur est ÉCRITE DANS LA COPIE ÉMISE, juste avant la compilation : rebuild ou bascule de scène, REAPER
# reçoit le bon niveau, sans saut ni course avec le moteur.
#  · le rôle VOLUME a toujours une valeur : la dernière position reçue (pédale ou curseur de l'écran), sinon 100 % au
#    démarrage (0 dB — le son d'avant, jamais un départ muet) ;
#  · le rôle BLOC n'est écrit qu'une fois la pédale bougée : sinon le réglage enregistré du preset (un mix, une position
#    de wah posée à la main) reste.
def _exp_bake(work):
    """Écrit la position connue des pédales sur leurs cibles dans `work` (la copie émise), base ET scènes."""
    # ⚠ PAS PENDANT UNE DÉMO (2026-11-06) : rendre la démo d'un son applique ses scènes par ce même chemin, et la
    # position de la pédale du musicien finissait dans le clip — une pédale volume laissée au talon a rendu trois scènes
    # de Modern Metal muettes. Une démo sonne au réglage du preset.
    from . import preview as _pv
    if _pv.rendering():
        return
    vol = state.pedals.get("volume", "exp1")
    blk = "exp2" if vol == "exp1" else "exp1"
    for a, phys in ((_exp_vol_assign(work), vol), (_exp_blk_assign(work), blk)):
        if not a or not a.get("block") or not a.get("param"):
            continue
        if phys == blk and not state.exp_known.get(phys):
            continue
        lo, hi = float(a.get("min", 0)), float(a.get("max", 1))
        raw = round(lo + (getattr(state, phys) / 127.0) * (hi - lo), 4)
        for b in _iter_ui_blocks(work):
            if b.get("id") == a["block"]:
                b.setdefault("params", {})[a["param"]] = raw
        # une scène qui fixerait ce potard ne doit pas reprendre la main sur la pédale
        for sc in work.get("scenes") or []:
            per = (sc.get("params") or {}).get(a["block"]) if isinstance(sc, dict) else None
            if isinstance(per, dict):
                per.pop(a["param"], None)


def _on_pedal(phys, v):
    """CC d'une pédale PHYSIQUE ('exp1' = ExpA/CC7, 'exp2' = ExpB/CC11) -> son RÔLE du moment.
    Appelé des THREADS lecteurs : rester léger. Rôle volume : bloc volume (sinon affichage seul).
    Rôle bloc : param assigné, sinon défaut/compat = relais treadle Whammy DT."""
    setattr(state, phys, v)
    state.exp_known[phys] = True                    # la position est connue : elle suivra les rappels (_exp_bake)
    if state.pedals.get("volume") == phys:
        _apply_exp(_EXP_VOL["assign"], v)
    elif not _EXP_BLK["assign"] and state.looper.get("enabled"):
        # un preset LOOPER : la pédale qui n'est ni le volume ni assignée dose TOUTES les boucles (2026-10-14)
        _looper_ctl.set_all_level(v / 127.0)
    elif not _apply_exp(_EXP_BLK["assign"], v):
        # le relais treadle ne joue QUE si EXP1 est EXPLICITEMENT assignée au bloc matériel
        # (bloc midi absent de la livemap -> _apply_exp rend False) ; non assignée = inerte.
        # whammy-dt = chemin nominatif prouvé ; midi-pedal = même relais, par descripteur
        # (pedal_treadle no-op si le descripteur ne déclare pas de CC de treadle).
        if _EXP_BLK.get("type") == "whammy-dt":
            midi_out.whammy_treadle(v)
        elif _EXP_BLK.get("type") == "midi-pedal" and _EXP_BLK.get("ref"):
            midi_out.pedal_treadle(_EXP_BLK["ref"], v)


def _scene_arms_whammy():
    """Chemin HÉRITÉ scene["whammy"] (plus aucun preset ne l'utilise, mais il est encore câblé
    dans _do_recall) : la glu des blocs ne doit pas le contredire."""
    cur = load_preset(state.preset_id) if state.preset_id else None
    sc = next((s for s in (cur or {}).get("scenes", []) if s.get("id") == state.scene_id), None)
    return bool(sc and sc.get("whammy"))


def _whammy_off():
    """Ramène la Whammy DT au bypass MATÉRIEL et oublie l'état — n'émet QUE si on croit
    quelque chose d'engagé (pas de PC inutile sur le bus, pas de blip de pitch)."""
    if state.whammy_on or state.whammy_mode:
        midi_out.whammy_mode(state.whammy_mode, False)
    if state.whammy_drop and state.whammy_drop != state.whammy_mode:   # 2e moteur, PC distinct
        midi_out.whammy_mode(state.whammy_drop, False)
    state.whammy_on = False
    state.whammy_mode = None
    state.whammy_drop = None
    state.whammy_pedal = None       # pedale eteinte : la prochaine position se renvoie


def _whammy_dt_glue(baked, force=False):
    """Bloc whammy-dt -> MIDI matériel. La DT a DEUX MOTEURS INDÉPENDANTS et combinables :
    Whammy/Harmony/Detune (params mode + won, treadle) ET Drop/Raise Tune (params drop + don).
    Chacun reçoit SON PC actif/bypass. Bloc bypassé par la scène = les deux moteurs en bypass.

    ⚠ CETTE FONCTION EST L'AUTORITÉ sur l'état de la pédale : elle tourne à CHAQUE émission
    (recall de preset ET changement de scène). Sans bloc whammy-dt, elle DOIT donc éteindre.
    Bug 2026-07-26 (retour terrain « je change de preset et elle est toujours allumée ») : le
    `return` était DANS la boucle -> un preset sans bloc whammy-dt ne produisait aucun MIDI et
    la pédale restait physiquement enclenchée."""
    from . import rig
    for b in rig.iter_blocks(baked):
        if b.get("type") == "whammy-dt":
            prm = b.get("params") or {}
            active = not b.get("bypass")
            won = active and prm.get("won", True)
            don = active and prm.get("don", False)
            # ⚠ Pour ÉTEINDRE un moteur il faut le NOM du réglage encore engagé : sur la DT chaque
            # réglage a SON PC de bypass (Drop −3 = 57 pour armer, 75 pour éteindre). Un preset ou
            # une scène qui ne nomme plus le réglage n'avait donc aucun PC à envoyer et laissait le
            # moteur allumé — bug 2026-07-26 : « Polaris scène A me met en drop −3 ; je passe sur
            # une scène d'un AUTRE preset et le drop ne part pas ». Les autres presets ONT un bloc
            # whammy-dt (sans drop) : on entrait ici, pas dans le repli sans-bloc. On retombe donc
            # sur le dernier réglage connu, mais UNIQUEMENT pour éteindre (armer sans mode nommé
            # garde le mode par défaut, comportement historique).
            mode = prm.get("mode") or (None if won else state.whammy_mode)
            drop = prm.get("drop") or (None if don else state.whammy_drop)
            # -- PAS DE PC INUTILE A LA WHAMMY (2026-09-20) -------------------------------------
            # Cette fonction tourne a CHAQUE emission, scene comprise : elle renvoyait donc un
            # Program Change a la pedale a chaque changement de scene, meme quand rien ne la
            # concernait. Une Whammy DT branchee est DANS le chemin du signal et se tait le temps
            # de changer de programme : un PC inutile est un blip evitable. `_whammy_off` avait
            # deja cette garde (<< pas de PC inutile sur le bus, pas de blip de pitch >>).
            # ⚠ CE N'ETAIT PAS LE BLANC DE A VERS B, contrairement a ce que ce commentaire a dit :
            # la Whammy du mainteneur n'etait pas branchee. Le blanc etait GxEchoCat, qui figeait tout le
            # moteur audio (docs/audit-2026-09-21-latence-scenes.md §0). La garde reste juste.
            want = (mode, bool(won), drop, bool(don))
            have = (state.whammy_mode, bool(state.whammy_on),
                    state.whammy_drop, state.whammy_drop is not None)
            if force or want != have:
                midi_out.whammy_mode(mode, bool(won))                 # mode None -> reglage par defaut
                if drop is not None and (drop, bool(don)) != (mode, bool(won)):
                    midi_out.whammy_mode(drop, bool(don))             # 2e moteur, message distinct
            # le TREADLE est un CC continu : il ne fait pas taire la pedale, mais on ne le renvoie
            # que s'il bouge -- un CC de plus sur le bus DIN n'aide personne.
            if won and prm.get("pedal") is not None and int(prm["pedal"]) != state.whammy_pedal:
                midi_out.whammy_treadle(int(prm["pedal"]))
                state.whammy_pedal = int(prm["pedal"])
            state.whammy_on = bool(won)
            state.whammy_mode = prm.get("mode") if won else (prm.get("drop") if don else None)
            state.whammy_drop = prm.get("drop") if don else None
            return
    if not _scene_arms_whammy():
        _whammy_off()


def _midi_pedals_glue(baked):
    """Blocs `midi-pedal` (ref = descripteur mappings/<id>.json) -> MIDI matériel. Chantier ①
    audit 2026-08-12 : le pendant GÉNÉRIQUE de _whammy_dt_glue, pour les 7 autres descripteurs
    du registre (H9, MX200…). La Whammy DT garde son chemin nominatif ci-dessus, intouché.

    ⚠ Même doctrine : cette fonction est L'AUTORITÉ sur l'état de ces pédales, elle tourne à
    CHAQUE émission — une pédale engagée dont le preset n'a plus de bloc DOIT être éteinte
    (classe du bug Whammy 2026-07-26). Et pour éteindre il faut le NOM du réglage engagé quand
    la table a des PC de bypass PAR réglage : repli sur le dernier réglage connu (state)."""
    from . import rig
    seen = {}
    for b in rig.iter_blocks(baked):
        if b.get("type") != "midi-pedal" or not b.get("ref"):
            continue
        ref = str(b["ref"])
        if ref in seen:
            continue                     # deux blocs, une pédale physique : le premier fait foi
        prm = b.get("params") or {}
        active = (not b.get("bypass")) and prm.get("on", True) is not False
        prev = (state.midi_pedals or {}).get(ref) or {}
        setting = prm.get("setting") or (None if active else prev.get("setting"))
        sent = midi_out.pedal_mode(ref, setting, active)
        if active and prm.get("pedal") is not None:
            midi_out.pedal_treadle(ref, int(prm["pedal"]))
        seen[ref] = {"on": bool(active),
                     "setting": sent or prm.get("setting") or prev.get("setting")}
    # repli sans-bloc : tout ce qu'on croit engagé et qui n'a plus de bloc s'éteint —
    # matériel (PC de bypass du dernier réglage connu, si la table en a) ET état publié.
    for ref, st in (state.midi_pedals or {}).items():
        if ref in seen:
            continue
        if (st or {}).get("on"):
            midi_out.pedal_mode(ref, (st or {}).get("setting"), False)
        seen[ref] = {"on": False, "setting": (st or {}).get("setting")}
    state.midi_pedals = seen


def _hw_pedals_glue(baked):
    """Point d'entrée INJECTÉ dans le moteur (recall_mod.init) : Whammy nominatif d'abord,
    générique ensuite. Isolés l'un de l'autre — une exception d'un moteur ne prive pas l'autre
    de son émission (le moteur enveloppe déjà l'ensemble d'un suppress, jamais fatal)."""
    try:
        _whammy_dt_glue(baked)
    finally:
        _midi_pedals_glue(baked)


def _pedal_block_by_id(cur, bid):
    """Le bloc midi-pedal d'id `bid` dans le preset courant (toutes lanes), sinon None."""
    from . import store as _st
    for b, _k in _st._foot_blocks(cur or {}):
        if b.get("id") == bid and b.get("type") == "midi-pedal":
            return b
    return None


def _toggle_midi_pedal(b, want=None):
    """(Dés)arme une pédale MIDI générique au pied/à l'écran — patron _toggle_whammy : le
    réglage vient du bloc, sinon du dernier réglage connu (il FAUT un nom pour un bypass
    par-réglage). Reflète l'état dans state.midi_pedals (publié à l'UI)."""
    ref = str((b or {}).get("ref") or "")
    if not ref:
        return
    st = (state.midi_pedals or {}).get(ref) or {}
    new = (not st.get("on")) if want is None else bool(want)
    setting = ((b.get("params") or {}).get("setting")) or st.get("setting")
    sent = midi_out.pedal_mode(ref, setting, new)
    mp = dict(state.midi_pedals or {})
    mp[ref] = {"on": new, "setting": (sent if new else None) or setting or st.get("setting")}
    state.midi_pedals = mp


# _LAST_EMIT, _input_veto et _emit_sandbox_preset vivent dans bridge/recall.py (extraits
# avec le moteur — audit 2026-08-12 P2). invalidate_shape() remplace les pokes de _LAST_EMIT.


def _toggle_whammy(cur, new, fs=None):
    """(Dés)arme la Whammy DT en MIDI + reflète l'état — partagé stomp 6-10 / claim rangée scènes."""
    from . import store as _st
    fs = fs or (_st._foot_summary(cur) if cur else {"whammy_mode": None})
    sc = next((s for s in (cur or {}).get("scenes", []) if s.get("id") == state.scene_id), None)
    mode = (sc["whammy"].get("mode") if (sc and sc.get("whammy")) else None) or fs.get("whammy_mode")
    midi_out.whammy_mode(mode, new)
    if not new and state.whammy_drop:      # éteindre = éteindre les DEUX moteurs de la DT
        midi_out.whammy_mode(state.whammy_drop, False)
        state.whammy_drop = None
    state.whammy_on = new
    state.whammy_mode = mode if new else None


def _bind_foot_services(cur):
    """Enregistre les blocs PILOTÉS PAR LES FRONTS d'un preset : quel switch lance quoi.

    ⚠ À appeler sur TOUS les chemins qui posent un preset, pas seulement le recall. L'adoption
    au démarrage (`_boot_recall`, rig déjà monté) posait `scene_claims` — donc la tuile
    apparaissait à l'écran — mais laissait ces registres VIDES : après chaque `reload.sh`, un
    bloc standard/sample/batterie/arrangement au pied ne répondait plus, sans une ligne de log.
    Mesuré le 2026-08-07.

    Le veto de mode ne s'applique qu'à `sample` (docs/modes.md) : effectif = preset ∧ mode.

    ⚠ LE MODE LOOPER EST ICI AUSSI, et pour la même raison (2026-08-08). Il décide de ce que
    FAIT LA RANGÉE HAUTE — transport du looper, ou stomps — et il n'était calculé que dans
    `_do_recall`. Après un `reload.sh`, l'adoption laissait donc le drapeau à sa valeur par
    défaut : le comportement des switches 6-10 dépendait de « le bridge a-t-il redémarré depuis
    le dernier rappel ? ». Sur « ZZ Conflict » (bloc looper + wah en SW6 + whammy en SW7), la
    même pédale répondait ou non selon cet historique — impossible à comprendre, et c'est ce qui
    a fait échouer check-foot deux fois de suite sans que le rack ait changé.
    C'est exactement la panne que cette fonction existe pour empêcher : tout ce dont le PIED
    dépend se restaure ici, sur TOUS les chemins qui posent un preset.
    """
    from . import rig as _rig
    # ── LA RANGÉE DES SCÈNES EMPRUNTÉE ET LE SWITCH DU BACKING, ICI AUSSI (2026-09-15) ──────────
    # `scene_claims` n'était posé que par le recall et l'adoption au boot. Le Designer sauve le
    # preset QUI TOURNE et appelle cette fonction… qui ne le recalculait pas : le mainteneur pose le Click
    # sur SW4 de « Paper Kite », le fichier le dit, /live ne montre rien — et le PIED rappelait la
    # scène D (inexistante) au lieu du métronome, `_on_foot_scene` lisant la même table périmée.
    # `backing_sw` avait le même défaut : déplacer le backing laissait ses fronts sur l'ancien switch.
    recall_mod.bind_foot_claims(cur)
    # La TABLE DE BOUCLES (docs/looper.md §1) se restaure ICI, pour la raison qui vaut pour tout
    # ce bloc : elle décide QUEL switch porte QUELLE boucle. Posée seulement au recall, un
    # reload.sh rendrait au looper la carte par défaut 6/7/8 pendant qu'à l'écran on lit 6/7/9.
    _looper_ctl.set_loops(_rig.looper_loops(cur) if cur else None)
    _looper_ctl.forget_addr()                     # le rig se reconstruit : la piste du Looper peut changer de numéro
    state.looper = {**state.looper,
                    "enabled": bool(cur) and _rig.looper_enabled(cur)
                    and modes_mod.allows("looper", state.mode),
                    # l'écran a besoin de la table pour NOMMER les tuiles : « USB » deux fois ne
                    # dit rien, et ces switches n'ont pas de LED (docs/looper.md §5).
                    "loops": _looper_ctl.loops() if cur and _rig.looper_enabled(cur) else []}
    state.sample_switches = (sample_mod.switches(cur)
                             if cur and modes_mod.allows("sample", state.mode) else {})
    # veto de MODE (2026-09-08) : la boîte à rythmes et le lecteur de grilles sont des
    # services comme le looper — coupés par le mode, ils n'ont ni switch au pied ni tuile Live.
    state.drum_switches = drums_mod.switches(cur) if cur and modes_mod.allows("drummachine", state.mode) else {}
    state.standard_switches = standards_mod.switches(cur) if cur and modes_mod.allows("standard", state.mode) else {}
    state.standard_block = standards_mod.block_of(cur) if cur and modes_mod.allows("standard", state.mode) else None
    state.standard_meta = standards_mod.meta_of(cur) if cur else {}
    state.arr_switch = arrangement_mod.foot_switch(cur) if cur else None


def _on_foot_select(info):
    """Le mode sélection du pied se MONTRE (bandeau global de l'app, main.js)."""
    state.foot_select = info
    state.touch()
    broadcast_threadsafe()


# ── CE QUI EST FLASHÉ DANS LA PUCE (presets/.uno2-flashed.json, écrit par flash_uno2.py) ─────
# Un switch de la rangée des scènes flashé en `effect` envoie un ÉTAT (CC 127 = on, 0 = off) : on
# le lit en ordre ABSOLU, comme un stomp — diode et rack ne peuvent plus s'inverser. Un switch en
# `preset` envoie toujours 127 : là on BASCULE. ⚠ On LIT ce qui a été écrit dans la puce, on ne le
# déduit pas du preset : une réservation changée sans reflash, et « 127 = on » pour toujours
# empêcherait d'arrêter une prise. Pas de fichier, slot inconnu -> bascule, comme avant.
_FLASHED = {"mtime": None, "doc": {}}


def _flashed_effect(sw):
    path = os.path.join(C.PRESETS_DIR, ".uno2-flashed.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return False
    if mt != _FLASHED["mtime"]:
        _FLASHED["mtime"], _FLASHED["doc"] = mt, (_read_json(path, {}) or {})
    slot = recall_mod.slot_of_preset(state.preset_id) if state.preset_id else None
    return slot is not None and sw in ((_FLASHED["doc"].get("effect_switches") or {}).get(str(slot)) or [])


def _on_foot_scene(sc, val=None):
    """Appui FCB sur un switch de la rangée scènes : slot claimé par un bloc spécial
    -> route vers le service (doctrine foot_scene_claim) ; sinon recall de scène normal."""
    idx = "ABCDE".find(str(sc or ""))
    sw = idx + 1 if idx >= 0 else 0
    # ⚠ UN SWITCH DE SCÈNE EMPRUNTÉ PAR LE LOOPER NE FAIT PLUS SCÈNE. Chaque switch envoie sa
    # Note ET son CC de scène : sans ce garde, appuyer sur SW5 dans un preset looper lancerait
    # les boucles (par la Note) ET changerait de scène (par le CC) — deux actions pour un geste,
    # dont une que personne n'a demandée. Un claim explicite garde la priorité (il est testé
    # avant) : le looper ne prend SW5 que si personne d'autre ne l'a réclamé.
    if sw and (state.scene_claims or {}).get(sw):
        want = (int(val) >= 64) if (val is not None and _flashed_effect(sw)) else None
        _do_stomp(sw, want)
    elif sw and sw in _looper_ctl.switches() and state.looper.get("enabled"):
        return                                             # les fronts font le transport
    else:
        # ⚠ `None`, PAS `state.preset_id` (2026-09-20 : un blanc à chaque scène AU PIED, jamais
        # à l'écran). Passer l'id du preset faisait de chaque appui de scène un RAPPEL DE PRESET sans
        # ligne : `do_recall` rechargeait l'arrangement SANS la ligne de setlist et posait
        # `state.song = None`. À l'appui suivant, le PC que la puce envoie avec chaque scène ne
        # reconnaissait donc plus « déjà chargé, même ligne » et rappelait le preset ENTIER — scène
        # non nommée, donc `scenes[0]` : la scène A. Tracé sur le canal de commandes : chaque appui
        # écrivait `scene_apply A` PUIS la scène demandée. Aller de C à B passait par A, c'est-à-dire
        # par l'autre branche d'ampli — le blanc — et selon l'ordre des deux fils d'exécution, la
        # scène demandée pouvait perdre (« j'ai des scènes qui ne se sont pas activées »).
        # Le contrat de `do_recall_slot` le disait : « un changement de scène passe par
        # do_recall(None, scene) ». ⚠ On croyait que l'écran le faisait : FAUX, les tuiles de /live envoyaient le
        # preset aussi, et chaque tap effaçait la chanson (corrigé le 2026-10-09, app/page-live.js).
        recall_mod.schedule(None, sc)   # hors boucle ; le moteur notifie à la fin


# types SERVICE (doctrine deux-royaumes) : jamais togglés en FX par golem_rig —
# ils ont leur propre dispatch (tuner overlay, perf-rec, transport backing, MIDI Whammy,
# MIDI générique midi-pedal)
# + "arrangement" : recensé au pied depuis le 2026-09-30, il n'est JAMAIS un FX à basculer (ses fronts le pilotent)
SERVICE_TYPES = ("whammy-dt", "midi-pedal", "tuner", "rec", "backing-track", "looper", "compo", "arrangement")


# ── le décompte d'une prise lancée au pied (ou par la tuile de /live) ─────────────────────────
_COUNTIN = {"until": 0.0, "timer": None, "click_was_on": False}


def _countin_seconds():
    """Durée du décompte : N mesures du bloc Rec, dans la métrique du CLICK (celle de la ligne de
    setlist si elle en a une) et au tempo du preset."""
    bars = int(store.load_recorder_cfg().get("count_in") or 0)
    if bars <= 0:
        return 0.0
    ck = _click_cfg()
    cur = load_preset(state.preset_id) if state.preset_id else None
    bpm = float((recall_mod.effective_preset(cur) or {}).get("bpm") or 120) if cur else 120.0
    return bars * int(ck.get("beats") or 4) * (4.0 / int(ck.get("den") or 4)) * (60.0 / max(bpm, 20.0))


def _countin_begin(t_go):
    _COUNTIN["click_was_on"] = bool((state.click or {}).get("on"))
    if _COUNTIN["click_was_on"]:
        # le JSFX ne repart sur le « 1 » qu'à un FRONT 0->1 de son moteur : on le lui donne
        ck = _click_cfg()
        _click_cmd({"action": "click", "op": "set", "on": False, "level": ck["level"],
                       "beats": ck["beats"], "den": ck.get("den", 4), "groups": ck.get("groups") or [],
                       "div": 1, "out": store.click_out()})
    _arr_click_hold(True)
    _COUNTIN["until"] = t_go
    state.perf_countin = {"until": t_go, "seconds": round(t_go - time.time(), 2)}
    state.touch()
    broadcast_threadsafe()
    t = threading.Timer(max(0.0, t_go - time.time()), _countin_end)
    t.daemon = True
    _COUNTIN["timer"] = t
    t.start()


def _countin_end():
    """Fin (ou annulation) du décompte : le click rend la main — il reste allumé s'il l'était."""
    t, _COUNTIN["timer"] = _COUNTIN["timer"], None
    if t:
        t.cancel()
    if _COUNTIN["until"] <= 0:
        return
    _COUNTIN["until"] = 0.0
    if not _COUNTIN["click_was_on"]:
        _arr_click_hold(False)
    state.perf_countin = None
    state.touch()
    broadcast_threadsafe()


def _rec_with_backing(sw):
    """Le switch `sw` (rangée des scènes) porte-t-il le bloc Rec ET le bloc Backing ? Alors c'est
    UN geste : la prise démarre AVEC le backing (2026-09-21 : « je lance le backing via le
    SW5 et il se lance avec le REC »)."""
    types = {c.get("type") for c in ((state.scene_claims or {}).get(sw) or [])}
    if not types and state.preset_id:              # rangée des stomps (6-10) : même règle, même geste
        with contextlib.suppress(Exception):
            fs = store._foot_summary(load_preset(state.preset_id))
            types = {b.get("type") for s in fs.get("switches", []) if s.get("sw") == sw
                     for b in s.get("blocks", [])}
    return "rec" in types and "backing-track" in types


def _foot_perf_toggle(with_backing=False, want=None, countin=True, delay=None):
    """START/STOP de la prise perf-rec AU PIED — le SEUL chemin, quel que soit le geste
    (bloc Rec claimé sur un switch 1-5, `perf_foot`, ou bloc rec sur un stomp 6-10).
    ⚠ LE PIED NE PASSE PAS PAR /api/perf : un garde-fou posé sur la seule route HTTP
    laisserait le chemin le plus utilisé sans protection — et c'est précisément au pied
    qu'on lance une prise en jouant, donc sans regarder l'écran. Ce bloc existait en TROIS
    copies et le garde-fou disque (jalon 0.a) ne vivait que dans une seule : les chemins
    `perf_foot` et stomp 6-10 démarraient une prise sans vérifier la place (audit 2026-08-12)."""
    rec = bool((_read_json(os.path.join(C.PRESETS_DIR, ".perf.json"), {}) or {}).get("recording"))
    # ordre ABSOLU (diode d'un switch `effect`) : déjà dans l'état demandé -> rien. Le décompte
    # compte comme « en route » : diode allumée pendant le décompte, éteinte = on annule.
    if want is not None and bool(want) == (rec or _COUNTIN["until"] > time.time()):
        return
    if not rec:
        from . import disk
        ok_disk, why_disk = disk.check_start()
        if not ok_disk:
            state.perf_error = why_disk        # l'écran le dit : au pied, il n'y a pas de retour HTTP
            log_perf.warning(f"démarrage refusé — {why_disk}")
            return
        if not modes_mod.allows("perfrec", state.mode):
            return                             # veto de mode (4.1) — le stop passe toujours
    cmd = {"action": "perf_rec", "on": not rec}
    # CE QUE LA PRISE ENREGISTRE, republié à chaque DÉPART : la prise d'un riff ajoute les entrées de ses lanes
    # (compo.riff_inputs) ; golem_perfrec fige ce fichier au départ, la prise ordinaire suivante le retrouve propre.
    # Pas à l'arrêt : le take.json (monitors) le relit après la prise, ses `sources` doivent dire ce qui a été pris
    if not rec:
        with contextlib.suppress(Exception):
            from . import compo
            _write_json_atomic(os.path.join(C.PRESETS_DIR, ".perfsrc.json"),
                               store.rec_sources(load_preset(state.preset_id) if state.preset_id else None,
                                                 force=compo.riff_inputs()), indent=None)
    if not rec:
        _arr_ctl.clear_practice()              # une boucle de répète ferait enregistrer Reaper en boucle (live-pages §6.3 bis)
    # SECOND APPUI PENDANT LE DÉCOMPTE : on annule (golem_perfrec lâche son départ différé), et le
    # click forcé se tait. Sans ça, l'appui « stop » tombait dans le vide et la prise partait seule.
    if not rec and _COUNTIN["until"] > time.time():
        _countin_end()
        write_command({"action": "perf_rec", "on": False})
        return
    # PRISE + BACKING d'un seul geste : golem_perfrec coupait le bus du backing parce que le
    # transport ne tournait pas ENCORE (c'est la prise qui le lance) — et la Note du même switch
    # rejouait ensuite le geste du backing, qui se croyait en lecture et faisait « pause ». Mesuré
    # le 2026-09-21 : cinq « mute ON » dans .backing.log, aucun backing audible. Ici on le DIT à
    # golem_perfrec (le backing est voulu), et le transport de la prise fait jouer le backing.
    if with_backing and not rec and state.backing.get("present"):
        cmd["backing"] = True
        _backing_ctl._set_opt(True)
    elif with_backing and rec:
        _backing_ctl._set_opt(False)           # le stop de la prise arrête le transport, donc le backing
    # LE DÉCOMPTE (bloc Rec ▸ Count-in, 0-2 mesures — 2026-09-21) : une prise part de zéro,
    # donc sans lui on n'a le temps de poser ni le pied ni les mains. Le click est FORCÉ audible
    # le temps du décompte (même règle que l'arrangement, §13) ; golem_perfrec décompte LUI-MÊME
    # (`in_ms`) : le départ ne subit pas la gigue du chemin de commande.
    # `countin=False` : une prise ARMÉE porte son décompte dans le fichier du backing (docs/compo.md §12)
    # `delay` (s) : départ différé SANS click forcé — la prise lancée par un MORCEAU part à son premier temps,
    # c'est l'arrangement qui fait entendre son décompte (golem_perfrec décompte lui-même, comme ci-dessous)
    if not rec and delay and delay > 0:
        cmd["in_ms"] = round(delay * 1000)
    elif not rec and countin:
        secs = _countin_seconds()
        if secs > 0:
            t_go = time.time() + secs
            _countin_begin(t_go)
            cmd["in_ms"] = round(max(0.0, t_go - time.time()) * 1000)   # APRÈS l'envoi du click : le slot a pu attendre
    write_command(cmd)
    return True                                # un ordre est PARTI (les refus ci-dessus rendent None)


RIFF_SLUG = "riff-take"


def _riff_armed_start(path, alive, bed=None):
    """La prise armée (docs/compo.md §12) : le click de la prise dans la piste Backing, puis la prise AVEC
    le backing, départ à 0 — sans le décompte du Rec (il est dans le fichier). Rend (ok, raison).
    `bed = (fichier, gain_db)` (§12 ter) : les autres couches du riff, un SECOND stem de la même commande — posé à 0
    comme le click par golem_backing, donc sur la même grille ; retiré avec lui par _riff_restore (unload)."""
    files, mix = {"drums": path}, {"drums": {"mute": 0, "vol": 1.0}}
    if bed:
        files["other"] = bed[0]
        mix["other"] = {"mute": 0, "vol": round(10 ** (float(bed[1]) / 20.0), 6)}
    _backing_ctl.load_files(RIFF_SLUG, files, mix)
    t_end = time.time() + 8.0
    while time.time() < t_end:
        if not alive():
            return False, "cancelled"
        if state.backing.get("present") and state.backing.get("slug") == RIFF_SLUG:
            break
        time.sleep(0.1)
    else:
        return False, "the backing track did not load the click in time"
    if not alive():
        return False, "cancelled"
    before = state.perf_error
    _foot_perf_toggle(with_backing=True, want=True, countin=False)
    if state.perf_error and state.perf_error != before:
        return False, state.perf_error
    return True, None


def _riff_restore():
    """Après la prise armée : le backing du preset reprend sa place (ou plus rien s'il n'en a pas)."""
    if state.backing.get("slug") == RIFF_SLUG:
        _backing_ctl.unload()
    cur = load_preset(state.preset_id) if state.preset_id else None
    if cur:
        _backing_ctl.on_recall(recall_mod.effective_preset(cur), allowed=state.backing.get("enabled", True))


_STD_TAKE = {"click_was_on": False, "held": False}


def _std_take_start(a, alive):
    """La prise de standard (docs/compo.md §11) : la grille rendue pour la prise, le Standard ARMÉ sur le transport,
    puis la prise sans le décompte du Rec (il est dans la grille). Le tick 0 de la grille tombe sur l'échantillon 0
    du fichier, donc le premier temps à `downbeat_s`. Rend (ok, raison). Hors du fil du pied (compo._armed_start)."""
    from . import golemfm
    tg, take = a["target"], a["take"]
    st = tg["std"]
    cur = load_preset(state.preset_id) if state.preset_id else None
    # les réglages de jeu du bloc Standard du preset, s'il joue CETTE grille : c'est ce que le musicien a réglé
    blk = standards_mod.block_of(cur) or {}
    pm = blk if blk.get("standard") == st["slug"] else {}
    ck = _click_cfg()
    b = standards_mod.build(st["slug"], key=st.get("key"), motion=pm.get("motion") or "comp",
                            groove=pm.get("groove"), groove_take=pm.get("groove_take"),
                            parts=st["parts"], choruses=max(1, take["passes"]), count_in=take["count_in"],
                            rootless=(pm.get("voicing") or "rootless") == "rootless", bpm=take["bpm"],
                            play={k: pm.get(k) for k in standards_mod.PLAY_KEYS},
                            click_div=max(1, int(ck.get("div") or 1)))
    if not b:
        return False, "standard not on this golem"
    r = b["render"]
    if take["click"] == "count-in":
        # le clic du décompte seulement : ses ticks s'arrêtent au premier temps (les note-off d'un tick tombent avant)
        r = dict(r, events=[e for e in r["events"] if not (e[3] == standards_mod.LANE_CLICK and e[0] >= r["count_in_ppq"])])
        standards_mod.write_seq(r)
    if not alive():
        return False, "cancelled"
    parts = b["parts"]
    write_command({"action": "standard", "op": "play", "standard": st["slug"], "file": b["file"],
                   "arm": True, "bpm": take["bpm"], "loop": not take["passes"],
                   "arp": pm.get("arp") or "", "kit": pm.get("kit") or "black-pearl",
                   "keys": parts.get("keys", True), "bass": parts.get("bass", True),
                   "drums": bool(parts.get("drums")), "guitar": bool(parts.get("guitar"))})
    t_end = time.time() + 8.0
    while not _read_json(os.path.join(C.PRESETS_DIR, ".standard.json"), {}).get("armed"):
        if not alive():
            return False, "cancelled"
        if time.time() > t_end:
            return False, "the Standard did not arm in time"
        time.sleep(0.05)
    # le clic de la grille ne sonne que bloc Click allumé : on le tient allumé pendant la prise, et il rend la main
    # après — allumé s'il l'était. APRÈS l'armement : la grille armée tient déjà le click, qui ne compte pas seul
    _STD_TAKE.update(click_was_on=bool((state.click or {}).get("on")), held=True)
    _arr_click_hold(True)
    n = take["bars"]
    a["std_played"] = {"slug": st["slug"], "etag": golemfm._std_etags().get(st["slug"]),
                       "key": st.get("key") or b["grid"].get("key"), "semis": r["semis"], "bpm": take["bpm"],
                       "beats": take["sig"]["num"], "feel": r["feel"], "choruses": take["passes"],
                       "parts_heard": sorted(k for k, v in parts.items() if v),
                       "bars": [[c["sym"] for c in bar["chords"]] for bar in r["bars"][:n]]}
    before = state.perf_error
    _foot_perf_toggle(want=True, countin=False)
    if state.perf_error and state.perf_error != before:
        return False, state.perf_error
    return True, None


def _std_take_restore():
    """Après la prise de standard : la grille s'arrête (le tempo du preset revient avec elle, golem_chordseq.lua),
    et le click rend la main."""
    write_command({"action": "standard", "op": "stop"})
    if _STD_TAKE["held"]:
        _STD_TAKE["held"] = False
        if not _STD_TAKE["click_was_on"]:
            _arr_click_hold(False)


def _compo_tap(source="foot", person=None):
    """Le switch Compo (docs/compo.md §3, §11) — un seul chemin, comme _foot_perf_toggle : l'auteur est
    la personne du pédalier du rack (compo.foot_person) ou celle de l'appareil ; le veto de mode est
    vérifié dans compo.tap. La capture PASSE PAR la prise Rec (garde disque, décompte, départ différé).
    ⚠ `preset=cur` : `cur` n'existait pas ici — chaque appui levait NameError (trouvé le 2026-09-30)."""
    from . import compo
    cur = load_preset(state.preset_id) if state.preset_id else None
    return compo.tap(source=source, person=person, preset=cur,
                     toggle=lambda want: _foot_perf_toggle(want=want))


def _led_desired():
    """Les diodes de stomp que le rack a le DROIT d'aligner, et l'état voulu (foot_leds, docs/pedalboards.md § Diodes).
    Seulement : une puce qui sait l'appui à distance ET qu'on sait atteindre (même preuve que le goto bank — sinon le
    PC partirait vers la Whammy branchée à sa place) ; un switch en espèce `effect` (une diode d'état : ni le stomp à
    gestes du contrat, ni ceux de la bank looper) ; un stomp de CHAÎNE (pas un service qui a sa propre logique, pas
    un switch piloté par les fronts). Un switch libre est voulu éteint."""
    from . import pedalboard
    act = pedalboard.active()
    caps = ((act.get("device") or {}).get("capabilities") or {}).get("remote_press") or {}
    if not caps.get("supported") or not pedalboard._link_proven():
        return {}
    con = pedalboard.contract()
    gest = {int(st["switch"]) for st in con.get("stomps", []) if st.get("gestures")}
    slot = recall_mod.slot_of_preset(state.preset_id) if state.preset_id else None
    if slot is None:
        slot = pedalboard.believed_slot()
    _flashed_effect(0)                                     # rafraîchit _FLASHED (presets/.uno2-flashed.json)
    if slot is not None and int(slot) in (_FLASHED["doc"].get("looper_slots") or []):
        gest |= {int(x) for x in ((con.get("looper_bank") or {}).get("gestures") or [])}
    cur = load_preset(state.preset_id) if state.preset_id else None
    fs = store._foot_summary(cur) if cur else {"switches": []}
    blocks = {e["sw"]: {b["type"] for b in e["blocks"]} for e in fs["switches"]}
    edge = (set(state.sample_switches or {}) | set(state.drum_switches or {}) | set(state.standard_switches or {})
            | {state.arr_switch, recall_mod.backing_sw})
    if cur and state.looper.get("enabled"):
        edge |= set(_looper_ctl.switches())
    if cur:
        edge |= {cur.get("perf_foot"), cur.get("tuner_foot")}
    out = {}
    for st in con.get("stomps", []):
        sw = int(st["switch"])
        if sw in gest or sw in edge or (blocks.get(sw, set()) & set(SERVICE_TYPES + ("click",))):
            continue
        out[sw] = bool((state.stomps or {}).get(sw))
    return out


def _led_press(sw):
    """Appui À DISTANCE sur le switch `sw` (manuel UnO2 §4.3 : ProgramChange 00-09 = switch 1-10, sur le canal de
    télécommande). MESURÉ le 2026-10-08 : PC 7 canal 16 -> SW8 bascule et renvoie CC32 + Note 7."""
    from . import pedalboard
    caps = ((pedalboard.active().get("device") or {}).get("capabilities") or {}).get("remote_press") or {}
    ch = int(caps.get("channel", 0))
    pc = int(sw) - 1 + int(caps.get("pc_base", 0))
    if not (1 <= ch <= 16 and 0 <= pc <= 127):
        return False
    return bool(midi_out.program_change(pc, channel=ch))


foot_leds.configure(_led_desired, _led_press)


def _do_stomp(sw, want=None, source="foot"):
    """STOMP à la POSITION `sw` (6-10) : bascule (want=None, UI Live) ou POSE l'état (want=bool —
    FCB dont la LED alterne 127/0, et bientôt les cues) sur TOUS les blocs assignés à ce switch
    (block.foot == sw) — assignation libre, plusieurs blocs par switch (ex. 7 = delay+reverb). Les blocs
    FX sont togglés gapless par golem_rig (par id, estampille golem:<id>) ; un whammy-dt sur le switch
    pilote la Whammy en MIDI (PC actif/bypass). Reflète l'état dans state.stomps (clé = numéro de switch)."""
    from . import store
    try:
        sw = int(sw)
    except (TypeError, ValueError):
        return
    if ((state.sample_switches or {}).get(sw) or (state.drum_switches or {}).get(sw)
            or (state.standard_switches or {}).get(sw) or state.arr_switch == sw):
        # SAMPLE / DRUMS / STANDARD / ARRANGEMENT : pilotés par les FRONTS de Note. Au PIED, le CC
        # leur cède (anti double-déclenchement) : les fronts arrivent juste après.
        # ⚠ DEPUIS L'ÉCRAN, IL N'Y A PAS DE FRONTS — le tap EST le geste entier. Céder ici, c'était
        # ne rien faire du tout : la tuile Standard de /live était morte, comme le switch au pied
        # (mesuré le 2026-08-07 sur « ZZ Conflict »). On fabrique donc le geste : appui + relâchement
        # immédiat = un tap, ce que le contrôleur sait déjà interpréter.
        if source == "ui":
            _on_stomp_edge(sw, True)
            _on_stomp_edge(sw, False)
        return
    cur = load_preset(state.preset_id) if state.preset_id else None
    # lot 8 : le stomp dans la chronologie — le TYPE du (des) bloc(s) du switch, jamais un nom
    try:
        from . import diag as _diag
        _types = sorted({b.get("type") for b, _ in store.all_blocks(cur) if isinstance(b, dict) and b.get("foot") == sw}) if cur else []
        _diag.event("stomp", block_type="+".join(_types) if _types else f"sw{sw}",
                    on=bool(want) if want is not None else not bool((state.stomps or {}).get(sw)))
    except Exception as _e:
        _swallowed(_e, "diag stomp")
    # rangée SCÈNES empruntée (doctrine foot_scene_claim, 2026-07-20) : un bloc spécial
    # (tuner / whammy-dt / backing-track) assigné à un switch 1-5 remplace ce slot de scène.
    if 1 <= sw <= 5:
        claims = (store._scene_claims(cur) if cur else {}).get(sw) or []
        types = {c["type"] for c in claims}
        # `want` (switch flashé en `effect`) = l'état que la DIODE vient de prendre : on s'y aligne
        # au lieu de basculer. Déjà dans cet état -> rien (c'est ce qui RÉALIGNE après un refus).
        if "tuner" in types:
            _do_tuner(want if want is not None else not state.tuner.get("on"))
            return
        if "rec" in types:                                 # bloc Rec claimé : start/stop perf-rec
            _foot_perf_toggle(with_backing="backing-track" in types, want=want)   # + backing si le switch le porte
            return
        if "click" in types:                               # bloc Click claimé : métronome on/off
            if want is None or bool(want) != bool(_click_on()):
                _toggle_click()
            return
        if "compo" in types:                               # bloc Compo claimé : un riff (docs/compo.md)
            _compo_tap(source)
            return
        if "backing-track" in types:
            if state.backing.get("present"):
                _backing_ctl.api_action("toggle")
            return
        if "whammy-dt" in types:
            _toggle_whammy(cur, not state.whammy_on)
            state.touch()
            return
        if "midi-pedal" in types:                          # pédale MIDI générique claimée -> PC actif/bypass
            for c in claims:
                if c.get("type") == "midi-pedal":
                    b = _pedal_block_by_id(cur, c.get("id"))
                    if b:
                        _toggle_midi_pedal(b)
            state.touch()
            return
        # bloc de CHAÎNE claimé (ex. clean-boost) : toggle FX gapless, comme un stomp 6-10
        ids = [c["id"] for c in claims if c["type"] not in SERVICE_TYPES and c.get("id")]
        if ids:
            new = not bool((state.stomps or {}).get(sw))
            write_command({"action": "stomp", "preset": state.preset_id, "ids": ids, "on": new,
                           "_route": "rig_recall"})
            st = dict(state.stomps or {}); st[sw] = new; state.stomps = st
            state.touch()
        return                                             # switch 1-5 : jamais un stomp classique
    if _rec_with_backing(sw):                              # Rec + Backing sur un stomp 6-10 : UN geste, comme
        _foot_perf_toggle(with_backing=True)               # sur la rangée des scènes (avant : le CC cédait aux
        return                                             # fronts du backing et le Rec ne partait JAMAIS)
    if recall_mod.backing_sw is not None and sw == recall_mod.backing_sw:   # switch du bloc BACKING : transport piloté par
        return                                             # les Notes (edges) — CC ignoré (anti double-déclenchement)
    if cur and state.looper.get("enabled") and sw in _looper_ctl.switches():
        return                                             # transport du looper : piloté par les Notes
                                                           # (edges) — le CC lui cède. SW9 n'en est PAS.
    if cur and cur.get("perf_foot") == sw:                 # ce switch = REC de performance (utilitaire système, patron tuner)
        _foot_perf_toggle()
        return
    if cur and cur.get("tuner_foot") == sw:                # ce switch est l'ACCORDEUR (utilitaire système, pas un stomp)
        _do_tuner(not state.tuner.get("on"))               # toggle : arme -> overlay /live ; ré-appui -> désarme
        return
    fs = store._foot_summary(cur) if cur else {"switches": [], "whammy_mode": None}
    entry = next((s for s in fs["switches"] if s["sw"] == sw), None)
    if not entry or not entry["blocks"]:
        return                                             # switch non assigné -> no-op
    etypes = {b["type"] for b in entry["blocks"]}
    if "tuner" in etypes:                                  # bloc tuner sur un stomp 6-10
        _do_tuner(not state.tuner.get("on"))
        return
    if "rec" in etypes:                                    # bloc rec sur un stomp 6-10
        _foot_perf_toggle()
        return
    if "click" in etypes:                                  # bloc click sur un stomp 6-10
        _toggle_click()
        return
    if "compo" in etypes:                                  # bloc compo sur un stomp 6-10
        _compo_tap(source)
        return
    new = want if want is not None else not bool((state.stomps or {}).get(sw))
    ids = [b["id"] for b in entry["blocks"] if b["type"] not in SERVICE_TYPES and b["id"]]
    if ids:
        # golem_rig bascule TrackFX_SetEnabled des blocs estampillés golem:<id> (gapless, sans rebuild).
        # `_route:"rig_recall"` : garantit l'aiguillage vers golem_rig même sur un veilleur résident.
        write_command({"action": "stomp", "preset": state.preset_id, "ids": ids, "on": new,
                       "_route": "rig_recall"})
        from . import capture_module
        state.lane_toggles = capture_module.note_stomp(state.lane_toggles, ids, new, state.preset_id, state.scene_id)
    if entry["whammy"]:                                    # whammy-dt sur ce switch -> MIDI (comme l'ancien cas whammy)
        _toggle_whammy(cur, new, fs)
    for eb in entry["blocks"]:                             # pédale MIDI générique sur ce switch -> PC actif/bypass
        if eb["type"] == "midi-pedal":
            b = _pedal_block_by_id(cur, eb["id"])
            if b:
                _toggle_midi_pedal(b, new)
    st = dict(state.stomps or {}); st[sw] = new; state.stomps = st
    if source != "foot":                                   # depuis l'écran : la diode du pédalier doit suivre
        foot_leds.request_align()
    state.touch()


# ── MA LANE, SUR MON TÉLÉPHONE (docs/band-scenes.md, écran 5 — 2026-09-15) ─────────────────────
# Le Companion lit les blocs de SA lane (rôle de l'appareil) et en bascule un. Le rack en local (écran,
# outils) n'a pas de rôle : tout lui est permis. Un bloc seul sur un switch passe par le stomp — la LED
# et `state.stomps` restent justes ; sinon une commande de bascule par id, gardée pour la scène.
@app.get("/api/lane/mine")
def lane_mine(request: Request):
    from . import lane_stomps
    from . import inputmap as _im
    dev = auth_mod.device_of(request)
    # sans appareil (l'écran du rack, un aperçu) : ?role= ou ?person= choisissent la vue, sans pouvoir d'écrire
    role = request.query_params.get("role") if dev is None else dev.get("role")
    person = request.query_params.get("person") if dev is None else dev.get("person")
    # ?preset=<id> : les lignes de la personne dans UN AUTRE morceau (page « Between songs » : ce que je
    # jouerai dans le suivant) — en lecture, scène A ; le preset courant sinon
    other = request.query_params.get("preset")
    cur = load_preset(other) if other else (load_preset(state.preset_id) if state.preset_id else None)
    scene_id = None if other else state.scene_id
    sc = next((x for x in (cur or {}).get("scenes") or [] if isinstance(x, dict) and x.get("id") == scene_id), {})
    imap = _im.current() if person else None
    # les réglages personnels de golem.fm (docs/devices-people.md §8.1) voyagent avec « mes lignes » :
    # le Companion les lit sans une requête de plus, et un rack jamais appairé rend `{}`
    from . import roster as _roster
    prefs = _roster.prefs(person) if person else {}
    rights = (_roster.person(person).get("rights") if person else None) or None
    return {"preset": (cur or {}).get("id"), "preset_name": (cur or {}).get("name"), "scene": scene_id or (sc or {}).get("id"),
            "scene_name": sc.get("name"), "role": role, "person": person, "prefs": prefs, "rights": rights,
            "person_name": (dev or {}).get("person_name") if dev else ((imap and next((i.get("person_name") for i in (imap.get("inputs") or []) + (imap.get("usb") or []) if i.get("person") == person), None)) or person),
            "lanes": lane_stomps.mine(cur, scene_id, role, {} if other else state.lane_toggles, person=person, imap=imap)}


@app.get("/api/lane/capture")
def lane_capture_get(request: Request):
    from . import capture_module as CM, inputmap
    dev = auth_mod.device_of(request) or {}
    cur = load_preset(state.preset_id) if state.preset_id else None
    return {"preset": state.preset_id, "scene": state.scene_id,
            "modules": CM.owned(cur, state.scene_id, dev.get("role"), dev.get("person"), inputmap.current(), state.stomps, state.lane_toggles)}


@app.post("/api/lane/capture")
def lane_capture_set(request: Request, body: dict):
    from . import capture_module as CM, inputmap
    dev = auth_mod.device_of(request) or {}
    with recall_mod._RECALL_LOCK:
        if body.get("preset") != state.preset_id or body.get("scene") != state.scene_id:
            return JSONResponse({"ok": False, "error": "The song or scene changed; refresh the controls"}, status_code=409)
        cur = load_preset(state.preset_id) if state.preset_id else None
        rows = CM.owned(cur, state.scene_id, dev.get("role"), dev.get("person"), inputmap.current(), state.stomps, state.lane_toggles)
        row = next((r for r in rows if r["block"] == body.get("block")), None)
        if not row:
            return JSONResponse({"ok": False, "error": "This capture is not on your lane"}, status_code=403)
        try:
            normalized = CM.write_values(cur, state.scene_id, row, body.get("values"))
        except (ValueError, KeyError, TypeError) as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        for key, value in body["values"].items():
            sw = row["foot"].get(key)
            if sw:
                entry = next((s for s in store._foot_summary(cur)["switches"] if s["sw"] == sw), None)
                if entry and len(entry["blocks"]) == 1:
                    _do_stomp(sw, bool(value), source="ui")
            control = next(c for c in row["controls"] if c["id"] == key)
            if control.get("kind") == "toggle":
                target = row["block"] + "@capture" + str(control["slot"])
                state.lane_toggles = CM.note_stomp(state.lane_toggles, [target], bool(value), state.preset_id, state.scene_id)
        write_command({"action": "capture_params", "preset": state.preset_id, "block": row["block"],
                       "values": normalized, "_route": "rig_recall"})
        return {"ok": True, "values": {**row["values"], **body["values"]}}


@app.post("/api/lane/stomp")
async def lane_stomp(request: Request, body: dict):
    from . import lane_stomps
    from . import inputmap as _im
    dev = auth_mod.device_of(request)
    role = None if dev is None else dev.get("role")
    person = None if dev is None else dev.get("person")
    bid = str(body.get("block") or "")
    cur = load_preset(state.preset_id) if state.preset_id else None
    why = lane_stomps.check_toggle(cur, bid, role, person=person, imap=_im.current() if person else None)
    if why:
        return JSONResponse({"ok": False, "error": why}, status_code=403)
    rows = lane_stomps.mine(cur, state.scene_id, None, state.lane_toggles)
    blk = next((b for L in rows for b in L["blocks"] if b["id"] == bid), None)
    if blk is None:
        return JSONResponse({"ok": False, "error": "this block is not a pedal you switch"}, status_code=403)
    new = bool(body["on"]) if "on" in body else not blk["on"]
    fs = store._foot_summary(cur)
    entry = next((x for x in fs["switches"] if blk.get("foot") and x["sw"] == blk["foot"]), None)
    if entry and len(entry["blocks"]) == 1:
        _do_stomp(blk["foot"], new, source="ui")          # le switch ne tient que lui : même chemin que le pied
    else:
        write_command({"action": "stomp", "preset": state.preset_id, "ids": [bid], "on": new, "_route": "rig_recall"})
    state.lane_toggles = {**{k: v for k, v in (state.lane_toggles or {}).items()
                             if isinstance(v, dict) and v.get("preset") == state.preset_id and v.get("scene") == state.scene_id},
                          bid: {"on": new, "preset": state.preset_id, "scene": state.scene_id}}
    state.touch()
    await _broadcast()
    return {"ok": True, "block": bid, "on": new}


@app.post("/api/stomp")
async def stomp(body: dict):
    """Toggle le stomp à une POSITION FCB (parité pied ↔ écran Live). body = { switch: 6..10 }."""
    sw = body.get("switch", body.get("block"))            # 'block' = compat transitoire
    if sw is None:
        return JSONResponse({"error": "switch requis"}, status_code=400)
    # source="ui" : pas de fronts derrière ce clic, le dispatch doit fabriquer le geste lui-même
    _do_stomp(sw, body.get("on"), source="ui")             # on absent = toggle ; bool = état absolu (cues)
    await _broadcast()
    return {"ok": True, "state": state.snapshot()}


@app.post("/api/recall")
async def recall(request: Request, body: dict):
    """Rappelle un preset (rig) et/ou une scène A–H. Met à jour l'état, déclenche Reaper."""
    # rappel par LIGNE de setlist (docs/setlists.md §9) : {slot: n} — c'est ce que Live et le pupitre
    # font quand trois lignes partagent un preset ; le titre et le tempo de la ligne suivent.
    if body.get("slot") is not None and not body.get("preset"):
        try:
            slot = int(body["slot"])
        except (TypeError, ValueError):
            return JSONResponse({"error": "slot must be an integer"}, status_code=400)
        # ── LE RIG SE CHARGE (docs/devices-people.md, lot F) : « Start » attend, et tout le groupe voit qui
        # charge quoi (« le mainteneur loaded 1983 · the rig is ready »). Charger pendant qu'un morceau JOUE est un
        # geste qui l'arrête : un téléphone doit l'avoir confirmé (`confirm`), sinon 409 qui le dit.
        _dev = auth_mod.device_of(request)
        _by = (_dev or {}).get("person_name") or (_dev or {}).get("name") or "the rack screen"
        _arr = _arr_ctl.snapshot()
        if _dev and _dev.get("kind") == "Phone" and (_arr.get("running") or (state.backing or {}).get("playing")) and not body.get("confirm"):
            return JSONResponse({"error": "a song is playing — loading stops it", "confirm": True}, status_code=409)
        state.rig_loading = {"slot": slot, "since": time.time(), "by": _by}
        await _broadcast()
        try:
            await recall_mod.slot_async(slot, "screen")
        finally:
            state.rig_loading = None
            state.loaded_by = _by
        await _broadcast()
        return {"ok": True, "state": state.snapshot()}
    pid = body.get("preset")
    if pid and not load_preset(pid):
        return JSONResponse({"error": f"preset {pid} introuvable"}, status_code=404)
    # hors boucle (exécuteur du moteur) : le WebSocket et les autres requêtes vivent pendant
    # le bake/compile — et on ATTEND la fin pour renvoyer un snapshot déjà à jour.
    await recall_mod.recall_async(pid, body.get("scene"))
    await _broadcast()
    return {"ok": True, "state": state.snapshot()}


_SANDBOX_BUF = recall_mod.SANDBOX_BUF          # le chemin vit avec le moteur (reapply_sandbox)


@app.post("/api/sandbox_apply")
async def sandbox_apply(request: Request, body: dict):
    """Audition l'edit-buffer COURANT du Designer dans le sandbox, SANS persister le preset.
    body = { preset: <dict édité>, scene: <id> }. C'est le bouton « Appliquer » (écoute).
    Le buffer est PERSISTÉ dans presets/.sandbox.json : le travail non sauvegardé du Designer
    survit au reload de la page ET au reboot du rack (restauré par GET /api/sandbox). Seul ce
    chemin Designer écrit le fichier — un recall Live/FCB d'un autre preset n'écrase PAS le
    travail en cours."""
    preset = body.get("preset")
    if not isinstance(preset, dict):
        return JSONResponse({"error": "preset (dict) requis"}, status_code=400)
    from . import option_renames
    option_renames.apply(preset)                 # un écran resté ouvert avant le catalogue 31 envoie les vieilles étiquettes
    # ── LOT D (docs/devices-people.md) : un autre écran a écrit ce brouillon depuis que celui-ci l'a lu ──
    # AVANT l'audition : un brouillon périmé ne doit ni sonner ni s'écrire.
    from . import sandbox_edit
    _buf = _read_json(_SANDBOX_BUF, {}) or {}
    _clash = sandbox_edit.conflict(_buf, body.get("editor"), body.get("base"), bool(body.get("force")))
    if _clash:
        return JSONResponse({"ok": False, "conflict": True, **_clash}, status_code=409)
    _dev = auth_mod.device_of(request)
    _meta = sandbox_edit.after_write(_buf, body.get("editor"),
                                     (_dev or {}).get("name") or ("the rack screen" if auth_mod._is_local(request.client.host if request.client else "") else None))
    # Bloc Rec = singleton : régler une coche dans la FEUILLE doit valoir tout de suite, sans
    # passer par une sauvegarde (sinon « je change le mode puis j'appuie sur REC » ignorerait le
    # réglage frais). C'est ICI que ça vit — et NULLE PART ailleurs : ce chemin est le seul qui
    # porte une VRAIE édition. Le recall, lui, ne fait que consommer la config (cf. correctif
    # 2026-07-27 : il la réécrivait, et chaque preset imposait la sienne).
    with contextlib.suppress(Exception):
        # le brouillon d'AVANT : seule une case du Rec réellement changée ici devient la config globale
        store.save_recorder_cfg_from(preset, prev=(_buf.get("preset") if isinstance(_buf, dict) else None) or {})
    # PENDANT UN ESSAI (le preset courant est `sandbox-try`, docs/patches.md §19) : le Designer édite
    # ce même essai — on émet SOUS SON ID. Sinon la livemap dirait `nouveau-preset`, et l'appui de
    # scène suivant au pied (emit_sandbox("sandbox-try")) verrait un autre rig -> REBUILD complet en
    # plein jeu au lieu d'une bascule d'état (le GPF mediaafx des recalls rapides).
    # ⚠ SEULEMENT si le document EST un essai (patch ouvert, banc neuf). Vécu le 2026-09-23 : l'essai courant
    # était un patch batterie ; le mainteneur ouvre « Paper Kite » (preset NOMMÉ) dans le Designer -> cet id forcé
    # le rebaptisait `sandbox-try`, l'auto-save en place écrivait presets/sandbox-try.json (un fichier que
    # docs/patches.md §19 interdit), et le tiroir Arrangement cherchait une chanson pour « sandbox-try ».
    # UN PATCH NOMMÉ JOUE SOUS `patch:<id>` (docs/patches.md §6) — le même id qu'un rappel depuis
    # une bank de sons ; un banc sans nom sous `sandbox-try`. `tid` = l'id sous lequel CE brouillon joue.
    tid = recall_mod.trial_id(preset)
    ends_trial = recall_mod.is_trial_id(state.preset_id) and not recall_mod.is_trial_doc(preset)
    if recall_mod.is_trial_id(state.preset_id) and recall_mod.is_trial_doc(preset):
        preset = {**preset, "id": tid}
    # hors boucle : l'audition compile un rig complet — la boucle reste libre pendant ce temps
    err = await recall_mod.emit_preset_async(preset, body.get("scene"))   # None si OK, sinon l'erreur de compile
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=200)
    with contextlib.suppress(Exception):
        _write_json_atomic(_SANDBOX_BUF, {"preset": preset, "scene": body.get("scene"), **_meta})
    # L'ESSAI EST LE PRESET COURANT, depuis le rack aussi (docs/patches.md §19, complément 2026-09-14) :
    # un brouillon qui n'est pas un preset nommé est adopté sous `sandbox-try` à sa première audition —
    # /live et le pied jouent alors ce qui sonne. Jamais dans un mode verrouillé.
    # — et la SCÈNE choisie dans le Designer est la scène courante : /live et le pied la suivent (mesuré
    # le même jour : le rig jouait B, l'état disait A).
    wanted = body.get("scene")
    adopt = state.preset_id != tid
    if ((adopt or (wanted and wanted != state.scene_id)) and recall_mod.is_trial_doc(preset)
            and not ((state.mode or {}).get("ui") or {}).get("locked")):
        with contextlib.suppress(Exception):
            await recall_mod.recall_async(tid, wanted)
            if adopt:
                log_sandbox.info(f"brouillon adopté comme preset courant ({tid}) : « {preset.get('name')} »")
    # l'ESSAI est le preset courant et on vient de l'éditer sans le rappeler (même scène) : ce que
    # le pied lance doit suivre l'édition, comme pour un preset nommé à sa sauvegarde
    elif state.preset_id == tid and recall_mod.is_trial_doc(preset):
        with contextlib.suppress(Exception):
            _bind_foot_services(recall_mod.effective_preset(preset))
            await _broadcast()
    elif ends_trial and preset.get("id") and not ((state.mode or {}).get("ui") or {}).get("locked"):
        # un preset NOMMÉ ouvert dans le Designer met fin à l'essai : l'état suit ce qui sonne
        with contextlib.suppress(Exception):
            await recall_mod.recall_async(preset["id"], wanted)
            log_sandbox.info(f"fin de l'essai : le Designer édite le preset nommé « {preset.get('name')} » ({preset['id']})")
    # potards du bloc Click tournés dans le Designer : si le métronome tourne, on lui re-pousse la
    # config fraîche (level/beats/sortie) -> l'audition reste temps réel comme les autres blocs.
    # DIFFÉRÉ, et SEULEMENT sur ce chemin : .command.json est un slot unique, une commande click
    # émise dans la foulée écraserait la commande d'audition avant que golem_watch ne la lise.
    if _click_on():
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().call_later(0.8, _click_set, True)
    return {"ok": True, "rev": _meta["edit_rev"]}


@app.get("/api/sandbox")
def get_sandbox(prev: int = 0):
    """Dernier edit-buffer du Designer (persisté à chaque audition). {} si aucun.
    prev=1 : le brouillon GARDÉ avant qu'un patch-try de golem.fm ne prenne la place (patches.md §17)."""
    from . import option_renames
    if prev:
        doc = _read_json(_SANDBOX_BUF.replace(".sandbox.json", ".sandbox.prev.json"), {}) or {}
    else:
        doc = _read_json(_SANDBOX_BUF, {}) or {}
    option_renames.apply(doc)                    # un brouillon d'avant le catalogue 31 garde ses vieilles étiquettes
    return doc


@app.post("/api/whammy")
async def whammy(body: dict):
    """Pilote la Whammy DT (chemin MIDI prouvé). body: {mode?, active?, treadle?}."""
    if "treadle" in body:
        ok = midi_out.whammy_treadle(int(body["treadle"]))
    else:
        ok = midi_out.whammy_mode(body.get("mode"), bool(body.get("active", True)))
    return {"ok": ok, "port": midi_out.find_port()}


def _click_cfg():
    """Config du métronome telle qu'elle se JOUE : la globale (config/click.json), et par-dessus la
    signature de la LIGNE de setlist en cours (docs/setlists.md §9.9), quand elle en a une."""
    ck = store.load_click_cfg()
    with contextlib.suppress(Exception):
        ck.update(recall_mod.song_click())
    if _ARR_CLICK.get("meter"):                    # un morceau joue : la mesure de SA section (_arr_click_meter)
        ck.update(_ARR_CLICK["meter"])
    return ck


def _click_set(on):
    """Pousse l'état du métronome au moteur avec la config globale FRAÎCHE (config/click.json) :
    niveau, temps par mesure, et sortie (pastille OUT de la lane Click, sinon patch de la carte).
    Veto de mode : en click_mode « off » le click ne DÉMARRE jamais — l'arrêt passe toujours."""
    on = bool(on)
    if on and modes_mod.click_mode(state.mode) == "off":
        return False
    ck = _click_cfg()
    _click_cmd({"action": "click", "op": "set", "on": on,
                   "level": ck["level"], "beats": ck["beats"], "den": ck.get("den", 4),
                   "groups": ck.get("groups") or [], "div": 1,
                   "out": store.click_out()})
    return True


def _click_clock(run):
    """HORLOGE SILENCIEUSE (docs/arrangement.md §5) : fait tourner le compteur du click SANS
    produire de son. « Pas de son » n'est pas « pas d'horloge » — un arrangement en mode `bars`
    a besoin d'une mesure même quand le groupe ne veut pas de métronome.

    Sans veto de mode, DÉLIBÉRÉMENT : `click_mode: off` interdit au métronome de SONNER, pas au
    rig de savoir où il en est. Le seul chemin qui produit du son reste `_click_set`.
    """
    ck = _click_cfg()
    _click_cmd({"action": "click", "op": "set", "clock": bool(run),
                   "beats": ck["beats"], "den": ck.get("den", 4),
                   "groups": ck.get("groups") or [], "div": 1,
                   "out": store.click_out()})
    return True


def _click_on():
    return bool((_read_json(os.path.join(C.PRESETS_DIR, ".click.json"), {}) or {}).get("on"))


def _click_follow_preset(preset):
    """Mode « preset » : le bloc Click du preset chargé DÉCIDE — actif = le métronome joue, bypassé
    = il s'arrête. Appelé au recall : entre deux recalls, un geste manuel (pied, bouton) garde la
    main, comme un stomp basculé à la main que la scène suivante réécrit."""
    if modes_mod.click_mode(state.mode) != "preset":
        return
    # LE CLICK D'UN MORCEAU ATTEND SON DÉPART (2026-10-07, arrangement-controls §10.5) : une chanson
    # chargée, automation active, qui ne décoche pas Click -> c'est le ▶ / le switch qui le lancera. Au rappel,
    # il se tait (sinon il sonne pendant qu'on s'accorde). Et un changement de mode en plein morceau ne
    # touche pas au click que le morceau a pris.
    if _arr_ctl.snapshot().get("running"):
        return
    if arrangement_mod.plan(preset) and arrangement_mod.starts_of(preset).get("click") is not False:
        if _click_on():
            _click_set(False)
        return
    blocks = ((preset or {}).get("config") or {}).get("rec", {}).get("blocks") or []
    cb = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "click"), None)
    want = bool(cb) and not cb.get("bypass")
    if want != _click_on():
        _click_set(want)


def _toggle_click():
    """Bloc Click (claim 1-5 OU stomp 6-10) : bascule le métronome — chantier 2026-07-25."""
    _click_set(not _click_on())


_tuner_in_sent = {"n": None}


def _do_tuner(on):
    """Arme/désarme l'accordeur (cœur sync, réutilisé par l'API ET le pied). write_command -> golem_watch
    arme le JSFX ; _poll_tuner suit .tuner.json ; l'overlay /live suit state.tuner.on.
    LOT 2 : la lane écoutée voyage AVANT (ExtState golem/tuner_in via golem_apply) — .command.json
    est un slot unique, donc l'ordre d'armement part 0,4 s après quand la lane change."""
    on = bool(on)
    n, role, tid = store.tuner_source(load_preset(state.preset_id) if state.preset_id else None)
    from . import tunings as _tun
    tu = _tun.resolve(tid, role)                     # les cordes que /live affiche (6/7/8, basse 4/5)
    if on and _tuner_in_sent["n"] != n:
        write_command({"action": "extstate", "key": "tuner_in", "value": str(n)})
        _tuner_in_sent["n"] = n
        recall_mod._later(0.4, write_command, {"action": "tuner", "on": True})
    else:
        write_command({"action": "tuner", "on": on})
    state.tuner = {**state.tuner, "on": on, "role": role,
                   "tuning": ({"id": tu["id"], "label": tu["label"], "midi": tu["midi"]} if tu else None),
                   **({} if on else {"active": False})}
    state.touch()


@app.post("/api/golem/pull")
async def golem_pull_now():
    """Tire maintenant les .golem changés chez golem.fm pour les chansons que le rack porte (lot 2)."""
    from . import golem_pull as _gp
    todo = await asyncio.to_thread(_gp.refresh_all)
    return {"started": [s for s, _ in todo], "status": _gp.status()}


@app.get("/api/golem/pull")
def golem_pull_status():
    from . import golem_pull as _gp
    return {"status": _gp.status(), "etags": _gp.etags(), "refused": _gp.refused()}


@app.get("/api/inbox")
def get_inbox():
    """Le dossier surveillé (lot 1.4) et ses derniers événements : installé, refusé (et pourquoi)."""
    from . import inbox as _inbox
    return _inbox.recent()


@app.post("/api/inbox")
def set_inbox(body: dict):
    """Change le dossier surveillé — `{dir: chemin absolu}`. Le choix appartient à l'utilisateur."""
    from . import inbox as _inbox
    try:
        return {"dir": _inbox.set_dir((body or {}).get("dir"))}
    except (ValueError, OSError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/tunings")
def get_tunings(role: str = ""):
    """La table des accordages (copie de golem.fm) — `role` = ceux qu'une lane de ce rôle peut choisir."""
    from . import tunings as _tun
    doc = _tun.load()
    lst = _tun.for_role(role) if role else (doc.get("tunings") or [])
    return {"tunings": lst, "default": (doc.get("defaults") or {}).get(_tun.kind_of(role)) if role else None}


@app.post("/api/tuner")
async def tuner(body: dict):
    """Arme/désarme l'accordeur (écran). Toggle si `on` absent."""
    on = (not state.tuner.get("on")) if "on" not in body else bool(body.get("on"))
    _do_tuner(on)
    await _broadcast()
    return {"ok": True, "tuner": state.tuner}


def _persist_loop_level(slot, row):
    """Le volume d'une boucle vit dans la TABLE du preset (2026-10-14 : « oui, dans le preset »). Écrit dans le
    fichier du preset ET dans le brouillon du Designer s'il porte ce preset — SANS reconstruire le rig (sandbox_apply
    le ferait, et les boucles en cours y passeraient). La révision du brouillon avance : un Designer ouvert voit
    qu'un autre éditeur (le mixer) a écrit, au lieu d'écraser le réglage à sa prochaine sauvegarde."""
    from . import sandbox_edit
    pid = state.preset_id
    if not pid or str(pid).startswith("patch:") or recall_mod.is_trial_id(pid):
        return False

    def put(doc):
        for b in ((doc.get("config") or {}).get("gen") or {}).get("blocks") or []:
            if b.get("type") == "looper":
                rows = looper_mod.normalize_loops((b.get("params") or {}).get("loops"))
                if 0 <= slot < len(rows):
                    rows[slot] = {**rows[slot], **{k: row[k] for k in ("level",) if k in row}}
                    if row.get("mute"):
                        rows[slot]["mute"] = True
                    else:
                        rows[slot].pop("mute", None)
                    b.setdefault("params", {})["loops"] = rows
                    return True
        return False
    path = os.path.join(C.PRESETS_DIR, f"{pid}.json")
    doc = _read_json(path, None)
    if isinstance(doc, dict) and put(doc):
        _write_json_atomic(path, doc)
    buf = _read_json(_SANDBOX_BUF, {}) or {}
    if (buf.get("preset") or {}).get("id") == pid and put(buf["preset"]):
        meta = sandbox_edit.after_write(buf, "live-mixer", "the mixer")
        _write_json_atomic(_SANDBOX_BUF, {**buf, **meta})
    return True


@app.post("/api/looper")
async def looper_action(body: dict):
    """Transport du looper depuis l'écran (parité pied ↔ Live).
    body = { op: tap|dub|clear|toggle_all|clear_all, slot?: 0|1|2 }."""
    if not state.looper.get("enabled"):
        return JSONResponse({"error": "no looper on this preset"}, status_code=400)
    if body.get("op") == "level":            # le fader d'une boucle (mixer de /live) : le son, puis le preset
        try:
            slot = int(body.get("slot"))
        except (TypeError, ValueError):
            return JSONResponse({"error": "slot"}, status_code=400)
        row = _looper_ctl.set_slot_level(slot, body.get("db"), body.get("mute"))
        if row is None:
            return JSONResponse({"error": "no such loop"}, status_code=400)
        await asyncio.to_thread(_persist_loop_level, slot, row)
        return {"ok": True, "loop": row}
    r = _looper_ctl.api_action(body.get("op"), body.get("slot"))
    await _broadcast()
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@app.post("/api/sample")
async def sample_action(body: dict):
    """Lanceur de sample depuis l'écran (parité pied ↔ Live). body = { sw, op }.
    op = tap (coupe le courant + lance le suivant) | stop. Le switch doit porter un bloc sample."""
    sw = body.get("sw")
    try:
        sw = int(sw)
    except (TypeError, ValueError):
        sw = None
    smp = (state.sample_switches or {}).get(sw) or (state.sample_switches or {}).get(str(sw))
    if not smp:
        return JSONResponse({"error": "no sample block on this switch"}, status_code=400)
    if body.get("op") == "stop":
        _sample_ctl.stop(smp.get("block"))
    else:
        _sample_ctl.tap(smp.get("block"), smp.get("samples"), smp.get("foot_idx"))
    await _broadcast()
    return {"ok": True, "samples": _sample_ctl.snapshot()}


@app.post("/api/drums")
async def drums_action(body: dict):
    """Boîte à rythmes depuis l'écran (parité pied ↔ Live). body = { sw, op }.
    op = tap (play/stop) | variation | stop. Le switch doit porter un bloc drums."""
    sw = body.get("sw")
    try:
        sw = int(sw)
    except (TypeError, ValueError):
        sw = None
    if not modes_mod.allows("drummachine", state.mode):
        return JSONResponse({"error": "drum machine is off in this mode (Settings ▸ Mode ▸ Tools)"}, status_code=409)
    drm = (state.drum_switches or {}).get(sw) or (state.drum_switches or {}).get(str(sw))
    if not drm:
        return JSONResponse({"error": "no drums block on this switch"}, status_code=400)
    op = body.get("op")
    if op == "stop":
        _drums_ctl.stop(drm.get("block"))
    elif op == "variation":
        _drums_ctl.variation(drm.get("block"), drm.get("patterns"))
    else:
        _drums_ctl.tap(drm.get("block"), drm.get("patterns"), drm.get("fills"), drm.get("kit"),
                       sequence=drm.get("sequence"), seq_mode=drm.get("seq_mode"))
    await _broadcast()
    return {"ok": True, "drums": _drums_ctl.snapshot()}


@app.get("/api/arrangement/stacks-moved")
def arrangement_stacks_moved():
    """Ce que la migration du lot 3 (docs/arrangement.md §7) a retiré du switch de l'arrangement, par
    preset : le Designer le DIT une fois (« Click left switch 4 — it now starts with the song »)."""
    return _read_json(os.path.join(C.PRESETS_DIR, arrangement_mod.MIGRATION_FILE), {}) or {"items": []}


@app.post("/api/arrangement")
async def arrangement_action(request: Request, body: dict):
    """Transport du chef d'orchestre. body = { op: start | stop | next | load | select }.
    `select` + `song` charge une chanson sans la lancer (sa backing armée, son arrangement à l'arrêt) ; `unselect` la
    décharge (le preset reste, seul). Les deux sont RETENUS au redémarrage (`.live.json`).

    `start` lance le morceau : décompte s'il y en a un, puis les cues aux frontières de section.
    `next` n'a de sens qu'en mode `foot` (un appui = une section) — refusé en mode `bars`, où le
    temps commande : deux maîtres pour la même chose, non.
    """
    op = (body or {}).get("op") or "start"
    _dev = auth_mod.device_of(request)
    _by = (_dev or {}).get("person_name") or (_dev or {}).get("name") or "the rack screen"
    # ▶ PLAY DEPUIS LA PAGE SONGS (2026-09-24) : {op: start, song: <id>} — on charge le preset de la chanson
    # s'il n'est pas déjà celui qui joue, l'état dit quel morceau c'est (sans ligne), et l'arrangement
    # est celui de la chanson (recall.effective_preset relit sa fiche).
    sid = (body or {}).get("song")
    if op in ("start", "select") and sid:
        from . import songs as _songs
        doc = _songs.load(sid)
        if not doc:
            return JSONResponse({"error": f"unknown song: {sid}"}, status_code=404)
        pid = (doc.get("sheet") or {}).get("preset")
        if not pid or not load_preset(pid):
            return JSONResponse({"error": "this song has no preset on this rack yet"}, status_code=400)
        # l'état dit le morceau AVANT le rappel : c'est lui qui porte le TEMPO de la chanson jusqu'à Reaper
        # (recall.py : `cmd["bpm"] = song["bpm"]`) — posé après, Reaper partait au tempo du preset (88 vs 87)
        state.song = recall_mod.song_of_song(doc, pid)
        if state.preset_id == pid:
            # MÊME preset, chanson nouvellement posée : le pied doit la voir (switch de l'arrangement, samples de
            # la fiche). Le rappel le fait ; sans rappel, personne ne le faisait — /live ne montrait pas « Arr ».
            _bind_foot_services(recall_mod.effective_preset(load_preset(pid)))
        if state.preset_id != pid:
            if getattr(state, "rig_loading", None):
                return JSONResponse({"error": "the rig is still loading — start when it is ready"}, status_code=409)
            state.rig_loading = {"song": sid, "since": time.time(), "by": _by}
            await _broadcast()
            try:
                await recall_mod.recall_async(pid, None)
            finally:
                state.rig_loading = None
    # ── CHARGER une chanson SANS la lancer (2026-10-18, tiroir Backing du Designer : « No song loaded » doit pouvoir
    # en charger une). Même chemin que ▶ Play jusqu'ici — l'état dit la chanson, le preset est rappelé s'il le faut —
    # puis on arme SA backing (docs/song-backing.md) et son arrangement, transport à l'arrêt.
    if op in ("select", "unselect"):
        if op == "select" and not sid:
            return JSONResponse({"error": "select needs a song"}, status_code=400)
        if op == "unselect":
            # DÉCHARGER : le preset reste, seul — plus de chanson, donc plus de backing (docs/song-backing.md §1)
            _arr_ctl.stop()
            state.song = None
        cur = load_preset(state.preset_id) if state.preset_id else None
        eff = recall_mod.effective_preset(cur) if cur else None
        songs = ((eff or {}).get("backing") or {}).get("songs") or []
        state.backing = {**state.backing, "songs": songs,
                         "enabled": bool(songs) and modes_mod.allows("backing", state.mode)}
        _backing_ctl.on_recall(eff, allowed=state.backing["enabled"])
        _arr_ctl.load(eff)
        setattr(state, "arrangement", _arr_ctl.snapshot())
        # RETENU au redémarrage : `.live.json` n'était écrit qu'au RAPPEL d'un preset — une chanson chargée sur le
        # même preset était oubliée au prochain démarrage du bridge (adoption, accueil « last »)
        with contextlib.suppress(Exception):
            recall_mod.remember_live()
        state.touch()
        await _broadcast()
        return {"ok": True, "song": state.song}
    preset = load_preset(state.preset_id) if state.preset_id else None
    # ── LES GESTES DE RÉPÈTE (docs/live-pages.md §6.3 bis) : refusés quand le mode verrouille l'écran (Gig, Show), et
    # pendant une prise quand une backing joue — un seek déplacerait la tête d'enregistrement, une boucle native ferait
    # enregistrer Reaper en boucle.
    frm = (body or {}).get("from")
    practice = op in ("cue", "loop") or (op == "start" and frm is not None and frm != 0)
    if practice:
        if ((state.mode or {}).get("ui") or {}).get("locked"):
            return JSONResponse({"error": "rehearsal gestures are off in this mode"}, status_code=403)
        if backing_mod._perf_recording() and (state.backing or {}).get("present"):
            return JSONResponse({"error": "not while recording with a backing track — it would move the recording"},
                                status_code=409)
        # « Record with the song » : la prise part APRÈS le décompte et rejoue la backing depuis 0 — un départ depuis une
        # section serait alors décalé de tout le morceau (relecture de l'ingénieur du son)
        if op == "start" and preset and ((body or {}).get("rec")
                                          or arrangement_mod.starts_of(recall_mod.effective_preset(preset)).get("rec")):
            return JSONResponse({"error": "starting from a section does not record — untick “Record with the song”"},
                                status_code=409)
    if op == "stop":
        _arr_ctl.stop()
        r = {"ok": True}
    elif op == "cue":
        idx = (body or {}).get("index")
        r = _arr_ctl.cue(int(idx) if isinstance(idx, (int, float)) and not isinstance(idx, bool) else None)
    elif op == "loop":
        r = _arr_ctl.set_loop(bool((body or {}).get("on")))
    elif op == "next":
        r = _arr_ctl.next()
    elif op == "load":
        _arr_ctl.load(recall_mod.effective_preset(preset))    # l'arrangement de la LIGNE (setlists.md §9)
        r = {"ok": True}
    else:
        if not preset:
            return JSONResponse({"error": "no preset loaded"}, status_code=400)
        if getattr(state, "rig_loading", None):
            return JSONResponse({"error": "the rig is still loading — start when it is ready"}, status_code=409)
        # LA BACKING SE CHARGE EN DIFFÉRÉ après un rappel (backing.RECALL_SETTLE_S, puis Reaper lit les
        # stems) : un ▶ Play qui vient de charger le preset partirait sans elle. On l'attend, borné.
        want = _arr_backing_slugs() if state.backing.get("enabled", True) and modes_mod.allows("backing", state.mode) else []
        if want and backing_mod.golemfm.is_cached(want[0]):
            for _ in range(40):                                       # 8 s au plus
                if state.backing.get("present") and state.backing.get("slug") in want:
                    break
                await asyncio.sleep(0.2)
            else:
                return JSONResponse({"error": "the backing track is still loading — try again in a moment"}, status_code=409)
        state.rec_with_song_asked = bool((body or {}).get("rec"))    # « Record with the song » (répète)
        r = _arr_ctl.start(recall_mod.effective_preset(preset), by=_by,
                           from_idx=int(frm) if isinstance(frm, (int, float)) and not isinstance(frm, bool) else None)
    setattr(state, "arrangement", _arr_ctl.snapshot())
    await _broadcast()
    if not r.get("ok"):
        return JSONResponse(r, status_code=400)
    return {**r, "arrangement": _arr_ctl.snapshot()}


@app.post("/api/drums/mix")
async def drums_mix(body: dict):
    """Mixeur d'un kit multi-micros, poussé DEPUIS l'écran pendant qu'on écoute.

    La boîte à rythmes ne relit son kit qu'au `play` — or on mixe une batterie en l'entendant.
    L'onglet Mix envoie donc les valeurs QU'IL AFFICHE ({block, mix:[{ch,gain,pan}], master}) et
    le bridge relaie tel quel : pas de résolution kit+preset ici, donc pas de désynchro possible
    entre ce que l'écran montre et ce que le rig joue. Le mix repart aussi avec le prochain play
    (drums.switches), c'est lui qui fait foi au rappel du preset.
    """
    blk = body.get("block")
    mix = body.get("mix")
    if not blk or not isinstance(mix, list):
        return JSONResponse({"error": "block and mix[] required"}, status_code=400)
    clean = []
    for m in mix[:16]:
        try:
            clean.append({"ch": int(m["ch"]),
                          "gain": max(-60.0, min(12.0, float(m.get("gain") or 0))),
                          "pan": max(-1.0, min(1.0, float(m.get("pan") or 0)))})
        except (KeyError, TypeError, ValueError):
            return JSONResponse({"error": f"bad mix entry {m!r}"}, status_code=400)
    try:
        master = max(-24.0, min(12.0, float(body.get("master", -6))))
    except (TypeError, ValueError):
        master = -6.0
    write_command({"action": "drums", "op": "mix", "block": blk, "mix": clean, "master": master})
    return {"ok": True, "channels": len(clean)}


@app.post("/api/drums/stop-all")
async def drums_stop_all():
    """Coupe TOUTE batterie en cours, quel que soit le switch/preset. Source de vérité = .drums.json
    (rapport Reaper) — marche même si l'état optimiste du bridge est vide (après un reload). Utile
    comme « OFF » global quand le séquenceur boucle encore sans bloc drums dans le preset courant."""
    try:
        rep = (json.load(open(C.DRUMS_FILE)).get("blocks") or {})
        playing = [b for b, s in rep.items() if isinstance(s, dict) and s.get("playing")]
    except Exception:
        playing = []
    _drums_ctl.stop_orphans(set(), also_playing=playing)      # valid vide -> stoppe tout
    await _broadcast()
    return {"ok": True, "stopped": playing, "drums": _drums_ctl.snapshot()}


@app.post("/api/backing")
async def backing_action(body: dict):
    """Transport des backing tracks depuis l'écran (parité pied ↔ Live).
    body = { op: play|pause|toggle|stop|restart|seek|select|unload|mix, … }.
    `select` charge une chanson EN CACHE (slug) ; `mix` = {stem, mute?, vol?}."""
    op = body.get("op")
    if op in (None, ""):
        return JSONResponse({"error": "op required"}, status_code=400)
    # select/unload/mix restent permis hors preset-backing (ex. page Library qui pré-écoute) ;
    # le transport exige une chanson chargée pour ne pas lancer un transport à vide.
    if op in ("play", "pause", "toggle", "restart", "seek") and not state.backing.get("present"):
        return JSONResponse({"error": "no backing song loaded"}, status_code=400)
    r = _backing_ctl.api_action(op, **{k: v for k, v in body.items() if k != "op"})
    await _broadcast()
    return r if r.get("ok") else JSONResponse(r, status_code=400)


# ── banks FCB ──────────────────────────────────────────────────────────────────
@app.get("/api/foot-list")
@app.get("/api/fcb-banks")                 # ancien nom, gardé pour les outils (check-*.py) — docs/setlists.md §0
def get_fcb_banks():
    """LA LISTE AU PIED : ses lignes dans l'ordre, ligne n = bank #n du pédalier (docs/setlists.md §0).
    Assignations preset->bank (l'ordre de la setlist-source = les numéros de bank).
    banks[] résout id/nom/scènes pour l'UI ; capacity = banks physiques (accès au pied)."""
    from . import setlists as _sl
    sl = recall_mod.fcb_setlist()
    pids = sl.get("presets", [])
    banks = []
    for slot, pid in enumerate(pids):
        p = load_preset(pid)
        banks.append({
            "slot": slot,
            "preset": pid,
            "name": (p or {}).get("name") or "",   # jamais l'id en guise de nom : un manquant se voit
            "missing": bool(pid) and p is None,
            "free": not pid,
            "scenes": [s.get("id") for s in (p or {}).get("scenes", [])],
        })
    return {"id": sl.get("id"), "name": sl.get("name"), "capacity": recall_mod.FCB_PHYS_BANKS,
            "kind": sl.get("kind") or "songs",          # ▤ morceaux / ⛓ sons — l'écran le dit (patch-as-preset §7)
            "presets": pids, "banks": banks,
            # les LIGNES (docs/setlists.md §9) : titre, slug, tempo — ce que Live et la tablette affichent
            "lines": [_sl.view_line(ln) for ln in sl.get("lines") or []], "rev": sl.get("rev")}


@app.post("/api/foot-list")
@app.post("/api/fcb-banks")
async def save_fcb_banks(body: dict):
    """Enregistre l'ordre des banks. body = { presets: [pid, ...] } (index = numéro de bank)."""
    presets = body.get("presets")
    if not isinstance(presets, list):
        return JSONResponse({"error": "presets (list) requis"}, status_code=400)
    from . import setlists as _sl
    over = _sl.over_cap(presets)
    if over:
        return JSONResponse({"error": over}, status_code=409)
    sl = recall_mod.fcb_setlist()
    sl.update({"id": sl.get("id") or _sl.active_id(), "name": sl.get("name") or "Setlist", "fcb": True})
    try:
        _sl.set_presets(sl, presets)               # les lignes suivent leurs presets (titres, tempos gardés)
    except ValueError as e:                        # un morceau dans une bank de sons, ou l'inverse (§11)
        return JSONResponse({"error": str(e)}, status_code=400)
    _sl.save(sl)                                   # écrit la setlist ACTIVE, horodatée
    try:
        from . import golemfm
        golemfm.push_setlist(sl["id"])           # le rack a écrit : golem.fm converge (§9.5)
    except Exception as _e:
        _swallowed(_e)
    return {"ok": True, "count": len(presets), "setlist": sl["id"]}


@app.get("/api/gestures")
def get_gestures():
    """La table des gestes au pied (config/pedalboard/gestures.json) — lue par /live (glyphes des
    cases) et par l'onglet MIDI assign du Designer (phrases). + le switch de sélection du contrat."""
    t = _read_json(os.path.join(C.CONFIG_DIR, "pedalboard", "gestures.json"), {}) or {}
    return {"signs": t.get("signs") or [], "blocks": t.get("blocks") or {}, "select_switch": foot.SELECT_SWITCH}


@app.post("/api/foot/select/cancel")
async def foot_select_cancel():
    """Quitte le mode sélection depuis l'écran — la sortie du bandeau « type 2 digits »."""
    if _foot:
        _foot.cancel_select()
    return {"ok": True}


@app.post("/api/foot/inject")
async def foot_inject(body: dict):
    """DEV : rejoue un événement FCB sans pédalier (teste le contrat MIDI + la machine appui-long).
    body = {type:'pc', n} | {type:'cc', cc, val} | {type:'note', n, on:bool}."""
    if not _foot:
        return JSONResponse({"error": "foot reader absent"}, status_code=503)
    t = body.get("type")
    # canal = celui du CONTRAT de l'appareil ACTIF, jamais « 0 » en dur : depuis le filtre
    # anti-écho THRU, une ligne sur le mauvais canal est ignorée — un inject câblé en dur aurait
    # rendu check-foot muet sans rien dire (2026-08-04), et le ferait à nouveau au rollback.
    ch = foot.wire_channel()
    if t == "pc":
        line = f"Program change {ch}, program {int(body['n'])}"
    elif t == "cc":
        line = f"Control change {ch}, controller {int(body['cc'])}, value {int(body.get('val', 127))}"
    elif t == "note":
        on = bool(body.get("on", True))
        vel = int(body.get("vel", 100)) if on else 0
        line = f"Note {'on' if on else 'off'} {ch}, note {int(body['n'])}, velocity {vel}"
    elif t == "raw":
        line = str(body.get("line") or "")           # ligne aseqdump verbatim (ex. puce réelle SANS velocity)
    else:
        return JSONResponse({"error": "type invalide (pc|cc|note|raw)"}, status_code=400)
    _foot.feed(line)
    await _broadcast()
    return {"ok": True, "state": state.snapshot()}


# ── I/O config ───────────────────────────────────────────────────────────────
_IO_PATH = os.path.join(C.CONFIG_DIR, "io.json")
_IO_DEFAULT = {"samplerate": 48000, "outputs_count": 2,
               "fold_down": {"mode": "sum", "gain": -3},
               "levels": {"guitar": 0.0, "voice": 0.0, "master": 0.0}}


@app.get("/api/io")
def get_io():
    # io.json est de l'ÉTAT LOCAL (écrit à l'adoption d'une carte, hors du dépôt depuis le 2026-10-15) : sans lui,
    # la carte ACTIVE (C.alsa_card : registre, carte branchée) — plus la Volt de l'auteur pour tout le monde
    card = C.alsa_card()
    return _read_json(_IO_PATH, None) or {**_IO_DEFAULT, "device": f"hw:{card}" if card else ""}


@app.post("/api/io")
async def save_io(io: dict):
    _write_json_atomic(_IO_PATH, io)
    lv = io.get("levels", {})
    if "guitar" in lv: reaper.set_track_volume(1, lv["guitar"])
    if "voice" in lv: reaper.set_track_volume(2, lv["voice"])
    return {"ok": True}


# ── WebSocket ────────────────────────────────────────────────────────────────
_online = {}


def _online_list():
    """Un appareil = une entrée, même s'il a deux onglets ouverts."""
    seen, out = set(), []
    for d in _online.values():
        if d["id"] not in seen:
            seen.add(d["id"]); out.append(d)
    return out


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    if not auth_mod.allowed_ws(websocket):          # distant sans token : refusé (S-P0-1)
        await websocket.close(code=4403)
        return
    await websocket.accept()
    _clients.add(websocket)
    # UNE FENÊTRE GOLEM SUR CET ORDINATEUR (docs/installer.md §4) : la coquille le dit (`?shell=`), l'ordinateur seul
    # compte — `profile` suit la fenêtre (desktop tant qu'une est ouverte, server quand la dernière se ferme)
    _is_window = machine_mod.is_window_ws(websocket.query_params.get("shell"),
                                          websocket.client.host if websocket.client else "")
    if _is_window:
        machine_mod.window_opened()
        await _broadcast()
    # QUI EST CONNECTÉ (docs/devices-people.md, lot F — « Ready for the show » : « Ju's phone not connected »)
    _tok = (websocket.query_params.get("token") or websocket.cookies.get("golem_token") or "")
    _d = auth_mod._device_by_token(_tok) if _tok else None
    if _d:
        _online[id(websocket)] = {"id": _d.get("id"), "name": _d.get("name"), "kind": _d.get("kind"),
                                   "person_name": _d.get("person_name")}
        state.devices_online = _online_list()
        await _broadcast()
    async with _bcast_lock():                # jamais en même temps qu'une diffusion (voir _broadcast)
        await websocket.send_text(_snapshot_text())
    try:
        while True:
            await websocket.receive_text()   # on ignore l'entrant (push-only) ; garde la connexion
    except WebSocketDisconnect:
        _clients.discard(websocket)
    except Exception:
        _clients.discard(websocket)      # toute autre erreur : on nettoie sans la faire remonter à uvicorn
    finally:
        if _online.pop(id(websocket), None):
            state.devices_online = _online_list()
            with contextlib.suppress(Exception):
                await _broadcast()
        if _is_window:
            machine_mod.window_closed()
            # après le délai de grâce (une fenêtre qui se recharge ne bascule pas), le profil passe à server : on le dit
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().call_later(machine_mod.GRACE_S + 0.2, broadcast_threadsafe)
            # golem desktop : la croix de la fenêtre arrête golem (machine.close_stops_golem, 2026-11-08)
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().call_later(
                    machine_mod.CLOSE_STOP_S + 0.2,
                    lambda: threading.Thread(target=stop_if_window_closed, daemon=True).start())


def _window_alive():
    """Un processus du navigateur DÉDIÉ de golem tourne-t-il encore ? Jamais le navigateur personnel : seul compte
    le profil `--user-data-dir` du lanceur. Windows/macOS : provision.desktop.app_window_pids. Linux : le profil de
    provision/golem change selon le navigateur (~/.local/share/golem/browser, ~/snap/<nom>/common/golem/browser
    pour un snap) — tout profil qui finit par `golem/browser` compte. Dans le doute (ps impossible), vivante."""
    import sys
    if sys.platform != "linux":
        from provision import desktop
        return bool(desktop.app_window_pids())
    try:
        out = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return any(re.search(r"--user-data-dir=\S*golem/browser(\s|$)", ln) for ln in out.splitlines())


def stop_if_window_closed():
    """La dernière fenêtre de golem desktop est fermée (sa croix, Ctrl+W) : golem s'arrête comme par le ⏻, par la
    MÊME route (routes_dev.ui_quit {stop: true}) — REAPER enregistré puis fermé, le bridge en dernier, le lanceur
    avec lui. Le WebSocket peut tomber sans que la fenêtre parte (veille, bridge occupé) : on ne s'arrête que si
    les processus de la fenêtre ont VRAIMENT disparu (_window_alive)."""
    if getattr(state, "stopping", False) or not machine_mod.close_stops_golem():
        return False
    if _window_alive():
        get("ui").info("fenêtre golem toujours là (WebSocket coupé) : golem continue")
        return False
    get("ui").info("fenêtre golem fermée par sa croix : arrêt de golem (REAPER, puis le bridge)")
    asyncio.run(routes_dev.ui_quit({"stop": True}))
    return True


# ── statique : app + catalogue (l'app fetch ../library/...) ──────────────────
@app.get("/")
def root():
    return RedirectResponse("/app/")

app.mount("/library", StaticFiles(directory=os.path.join(C.ROOT, "library")), name="library")

# ── moteur de recall : injection de la glue (en FIN de module — toutes les fonctions existent).
# Le moteur (bridge/recall.py) ne connaît ni les contrôleurs ni la Whammy : app.py les lui prête.
recall_mod.init(
    arr_ctl=_arr_ctl, backing_ctl=_backing_ctl, drums_ctl=_drums_ctl,
    bind_foot_services=_bind_foot_services,
    # _hw_pedals_glue = Whammy (chemin nominatif prouvé) PUIS blocs midi-pedal génériques —
    # même point d'entrée f(baked), même autorité à chaque émission (chantier ① 2026-08-13)
    whammy_glue=_hw_pedals_glue,
    set_exp_blk=_set_exp_blk_from, set_exp_vol=_set_exp_vol_from, exp_bake=_exp_bake,
    click_follow=_click_follow_preset,
    notify=broadcast_threadsafe,
)
app.mount("/app", StaticFiles(directory=C.APP_DIR, html=True), name="app")
