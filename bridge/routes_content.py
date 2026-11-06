# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes contenu (effets, catalogue, presets CRUD, setlists, templates, intégrations, mappings)
— extrait d'app.py (P3). Aucune dépendance à l'état live."""
import os, json, glob, re, subprocess, contextlib, sys, time, asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse

from . import config as C
from .store import load_presets, load_preset, _read_json, _write_json_atomic, _safe_id, _list_dir_json
from .commands import write_command
from .golog import swallowed as _swallowed
from .http_body import read_body, TooLarge, MB

router = APIRouter()


@router.get("/api/live/lyrics")
def live_lyrics():
    """Les paroles de la chanson qui joue, pour le widget des pages de /live (docs/live-pages.md §5)."""
    from . import live_widgets
    from .state import state
    return live_widgets.lyrics(state)


@router.get("/api/genres")
def genres_taxonomy():
    """La taxonomie des genres (docs/genres.md) : 17 familles et leurs sous-genres. Copie du rack
    (config/genres.json) jusqu'à ce que golem.fm, propriétaire, la serve versionnée."""
    from . import genres
    return genres.load()


@router.get("/api/presets")
def get_presets():
    from . import factory, preview
    out = factory.mark("presets", load_presets())
    for p in out:                    # la démo de chaque lane, rangée avec le morceau (preview.lane_previews)
        lp = preview.lane_previews(p.get("id")) if isinstance(p, dict) and p.get("id") else None
        if lp:
            p["lane_previews"] = lp
        bp = preview.block_previews(p.get("id")) if isinstance(p, dict) and p.get("id") else None
        if bp:                       # 8 mesures de chaque bloc drums / standard au pied (docs/preset-preview.md §8)
            p["block_previews"] = bp
    return out


@router.get("/api/live/trial")
def get_live_trial():
    """La fiche compacte de l'ESSAI courant (sandbox-try, docs/patches.md §19) — même forme qu'une
    entrée de /api/presets, pour que /live montre ses scènes ET ses stomps. 404 hors essai."""
    from .store import preset_summary
    from .state import state
    from .recall import is_trial_id
    # un patch joué comme un preset (`patch:<id>`, docs/patches.md) n'est pas au catalogue non plus
    if not is_trial_id(state.preset_id):
        return JSONResponse({"error": "no trial playing"}, status_code=404)
    p = load_preset(state.preset_id)
    return preset_summary(p) if p else JSONResponse({"error": "no draft"}, status_code=404)


@router.get("/api/preset/{pid}")
def get_preset(pid: str):
    p = load_preset(pid)
    return p if p else JSONResponse({"error": "not found"}, status_code=404)


# ── effets, catalogue ────────────────────────────────────────────────────────
@router.get("/api/effects")
def get_effects():
    data = _read_json(C.EFFECTS, {"effects": []})
    if sys.platform in ("win32", "darwin"):            # macOS : M6, 2026-10-04 (le Lua est commun)
        from . import rig
        q = rig.quarantined_types()                    # par PLUGIN : un type joué ici par un JSFX golem sort du tiroir des interdits
        for e in data.get("effects", []):
            if e.get("quarantine") and e.get("type") not in q:
                e["quarantine_linux"] = e.pop("quarantine")
        data["vst_host"] = True
        data["effects"] = [*data.get("effects", []), {"type": "vst-host", "name": "VST Host",
            "short": "VST", "icon": "▣", "category": "utility", "color": "#8b9fd7",
            "params": []}]
    return data


@router.get("/api/vst-host/plugins")
def vst_host_plugins():
    """Demande l'inventaire à REAPER : sa liste tient compte de ses chemins de scan et caches."""
    if sys.platform not in ("win32", "darwin"):
        return {"plugins": []}
    path = os.path.join(C.PRESETS_DIR, ".vst-host-list.json")
    seq = write_command({"action": "vst_list", "_route": "rig_recall"})
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        data = _read_json(path, {})
        if str(data.get("seq")) == str(seq):
            # un plugin en quarantaine ne se propose pas, même par son nom (rig.quarantined_plugin)
            from . import rig
            return {"plugins": [p for p in data.get("plugins", [])
                                if not rig.quarantined_plugin(p.get("name"))]}
        time.sleep(0.05)
    return JSONResponse({"error": "REAPER did not return its plugin list"}, status_code=503)


@router.post("/api/vst-host/open")
def vst_host_open(body: dict):
    block = body.get("block")
    if sys.platform not in ("win32", "darwin") or not isinstance(block, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    write_command({"action": "vst_open", "block": block, "_route": "rig_recall"})
    from provision.desktop import _backend_pids
    from provision.desktop_window import focus_reaper_fx
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if focus_reaper_fx(_backend_pids(), block):
            return {"ok": True}
        time.sleep(0.05)
    return JSONResponse({"error": "Plugin window not found in REAPER"}, status_code=404)


# ── La fenêtre d'origine d'un instrument (Vital) : ouverte depuis son tiroir, son état est rangé à la fermeture.
# Windows et macOS seulement, et seulement sur L'ÉCRAN DE LA MACHINE : la fenêtre s'ouvre là où tourne REAPER,
# jamais sur une tablette (2026-10-14). golem_rig guette la fermeture (action plugin_window).
_WIN_BLOCK = re.compile(r"[A-Za-z0-9_-]{1,100}")


def _plugin_window_mode(request: Request):
    """'native' : la vraie fenêtre, sur l'écran de la machine (Windows / macOS, client local).
    'view'   : Linux — la fenêtre vit sur l'écran virtuel de REAPER, golem la filme et y rejoue les gestes
               (bridge/plugin_view.py) : depuis l'écran de la machine COMME depuis une tablette.
    None     : impossible ici."""
    from .auth import _is_local
    if sys.platform in ("win32", "darwin"):
        return "native" if _is_local(request.client.host if request.client else "") else None
    from . import plugin_view
    return "view" if plugin_view.reaper_display() else None


@router.get("/api/plugin-window")
def plugin_window_caps(request: Request):
    """Le bouton est TOUJOURS montré, grisé quand il ne peut pas marcher (2026-10-14 : « désactive-le »,
    pas « cache-le » — un bouton absent ne dit pas pourquoi). `why` = ce qu'un tap affiche."""
    mode = _plugin_window_mode(request)
    if mode:
        return {"available": True, "mode": mode}
    if sys.platform in ("win32", "darwin"):
        return {"available": False, "why": "Vital's window opens on the golem's own screen, not on a tablet"}
    return {"available": False, "why": "REAPER is not running"}


@router.post("/api/plugin-window/open")
def plugin_window_open(request: Request, body: dict):
    block = body.get("block")
    mode = _plugin_window_mode(request)
    if not mode:
        return JSONResponse({"error": "plugin windows cannot open from here"}, status_code=403)
    if not isinstance(block, str) or not _WIN_BLOCK.fullmatch(block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    path = os.path.join(C.PRESETS_DIR, f".plugin-window-{block}.json")
    seq = write_command({"action": "plugin_window", "op": "open", "block": block, "_route": "rig_recall"})
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        st = _read_json(path, {})
        if str(st.get("seq")) == str(seq):
            if st.get("state") == "missing":
                return JSONResponse({"error": "Plugin instance not loaded in REAPER", "missing": True}, status_code=404)
            if mode == "view":
                from . import plugin_view
                g = plugin_view.place(block)
                if not g:
                    return JSONResponse({"error": "Plugin window did not appear"}, status_code=504)
                return {"ok": True, "seq": str(seq), "mode": mode, "w": g["w"], "h": g["h"],
                        "readable": st.get("readable", False), "error": st.get("error") or ""}
            from provision.desktop import _backend_pids
            from provision.desktop_window import focus_reaper_fx
            for _ in range(20):
                if focus_reaper_fx(_backend_pids(), block):
                    break
                time.sleep(0.05)
            return {"ok": True, "seq": str(seq), "mode": mode, "readable": st.get("readable", False), "error": st.get("error") or ""}
        time.sleep(0.05)
    return JSONResponse({"error": "REAPER did not answer"}, status_code=503)


@router.post("/api/plugin-window/{block}/close")
def plugin_window_close(block: str):
    """Ferme la fenêtre (le « Done » de la vue intégrée) : golem_rig voit la fermeture et range l'état."""
    if not _WIN_BLOCK.fullmatch(block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    write_command({"action": "plugin_window", "op": "close", "block": block, "_route": "rig_recall"})
    return {"ok": True}


@router.get("/api/plugin-view/{block}/stream")
async def plugin_view_stream(block: str):
    """La fenêtre filmée, en MJPEG : un <img src> du navigateur la lit sans une ligne de JS."""
    import threading
    from fastapi.responses import StreamingResponse
    from starlette.concurrency import run_in_threadpool
    from . import plugin_view
    if sys.platform in ("win32", "darwin") or not _WIN_BLOCK.fullmatch(block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    stop = threading.Event()
    it = plugin_view.frames(block, stop=stop)

    async def body():
        try:
            while True:
                jpg = await run_in_threadpool(next, it, None)
                if jpg is None:
                    return
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode()
                       + b"\r\n\r\n" + jpg + b"\r\n")
        finally:
            stop.set()                                         # le client est parti : ffmpeg s'arrête au tour suivant
    return StreamingResponse(body(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@router.post("/api/plugin-view/{block}/input")
def plugin_view_input(block: str, body: dict):
    """Un geste du musicien rejoué dans la fenêtre : {ev: move|down|up|wheel, x, y ∈ [0,1], dy}."""
    from . import plugin_view
    if sys.platform in ("win32", "darwin") or not _WIN_BLOCK.fullmatch(block) or body.get("ev") not in ("move", "down", "up", "wheel"):
        return JSONResponse({"error": "invalid gesture"}, status_code=400)
    try:
        x, y, dy = float(body.get("x", 0)), float(body.get("y", 0)), float(body.get("dy", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid gesture"}, status_code=400)
    return {"ok": plugin_view.gesture(block, body["ev"], x, y, dy)}


@router.get("/api/plugin-window/{block}")
def plugin_window_status(block: str):
    """{seq, state: open|closed|lost|missing, changed?} — sans l'état lui-même (il reste côté rack)."""
    if not _WIN_BLOCK.fullmatch(block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    return _read_json(os.path.join(C.PRESETS_DIR, f".plugin-window-{block}.json"), {})


@router.post("/api/plugin-window/{block}/save-vital")
def plugin_window_save_vital(block: str, body: dict):
    """Range l'état relu à la fermeture comme un preset Vital (pack edited) -> {id, name}. Le Designer pose ensuite
    cet id à la place de l'ancien sur le bloc : le son retouché devient celui du patch, par le chemin habituel."""
    from . import vital
    if not _WIN_BLOCK.fullmatch(block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    st = _read_json(os.path.join(C.PRESETS_DIR, f".plugin-window-{block}.json"), {})
    if st.get("state") != "closed" or not st.get("changed") or str(st.get("seq")) != str(body.get("seq")):
        return JSONResponse({"error": "nothing to save"}, status_code=409)
    b64 = os.path.join(C.PRESETS_DIR, f".plugin-window-{block}.b64")
    if not os.path.isfile(b64):                                    # déjà rangé
        return JSONResponse({"error": "nothing to save"}, status_code=409)
    try:
        data = vital.chunk_json(open(b64).read())
    except (OSError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    pid, name = vital.save_edited(data, str(body.get("from") or ""), block)
    with contextlib.suppress(OSError):
        os.remove(b64)
    return {"ok": True, "id": pid, "name": name}


@router.get("/api/vst-host/params/{block}")
def vst_host_params(block: str):
    """Lit les vrais paramètres de l'instance REAPER, avec valeurs normalisées."""
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    path = os.path.join(C.PRESETS_DIR, ".vst-host-params.json")
    seq = write_command({"action": "vst_params", "block": block, "_route": "rig_recall"})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        data = _read_json(path, {})
        if str(data.get("seq")) == str(seq):
            if not data.get("found"):
                return JSONResponse({"error": "Plugin instance not loaded in REAPER"}, status_code=404)
            # Certains VST publient la matrice MIDI CC entière (16 canaux × 130 contrôles)
            # comme paramètres d'automation. Elle n'est pas un réglage sonore du tiroir.
            params = data.get("params", [])
            return {"params": [p for p in params if not re.match(
                r"(?i)^\s*MIDI[\s_-]*CC\b", str(p.get("name", "")))]}
        time.sleep(0.05)
    return JSONResponse({"error": "REAPER did not return plugin parameters"}, status_code=503)


@router.get("/api/vst-host/state/{block}")
def vst_host_state(block: str):
    """Capture ponctuelle de l'état natif chargé dans l'instance REAPER."""
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    path = os.path.join(C.PRESETS_DIR, ".vst-host-state.json")
    seq = write_command({"action": "vst_state", "block": block, "_route": "rig_recall"})
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        data = _read_json(path, {})
        if str(data.get("seq")) == str(seq):
            if not data.get("found"):
                return JSONResponse({"error": "Plugin instance not loaded in REAPER"}, status_code=404)
            if data.get("error"):
                return JSONResponse({"error": data["error"]}, status_code=422)
            kind, chunk = data.get("kind"), data.get("chunk")
            if kind not in ("vst_chunk", "clap_chunk") or not isinstance(chunk, str) or not chunk:
                return JSONResponse({"error": "Plugin did not provide native state"}, status_code=422)
            return {"kind": kind, "chunk": chunk, "params": data.get("params", [])}
        time.sleep(0.05)
    return JSONResponse({"error": "REAPER did not return plugin state"}, status_code=503)


# ── CAPTURE NAM D'UN BLOC VST (2026-10-05, docs/plugin-capture.md) ─────────────────────────
# Sur le poste seulement : rendu dans un REAPER séparé, entraînement sur la carte graphique, rangement
# dans la bibliothèque (bridge/plugin_capture.py). Le tiroir VST interroge puis lance.
@router.get("/api/vst-host/capture")
def vst_host_capture_status(block: str = "", plugin: str = ""):
    if sys.platform not in ("win32", "darwin"):
        return JSONResponse({"error": "Plugin captures are made on Windows or macOS"}, status_code=409)
    from . import plugin_capture
    out = {"job": plugin_capture.status(), "setup": plugin_capture.setup_status()}
    if block and plugin and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block):
        out["check"] = plugin_capture.check(block, plugin)
    return out


@router.get("/api/vst-host/capture/replacement")
def vst_host_capture_replacement(block: str, plugin: str):
    """La chaîne qui remplace le bloc VST dans le patch : les captures du dernier job et les traductions."""
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block):
        return JSONResponse({"error": "invalid block"}, status_code=400)
    from . import plugin_capture
    r = plugin_capture.replacement(block, plugin)
    return JSONResponse(r, status_code=409) if r.get("error") else r


@router.post("/api/vst-host/capture/cancel")
def vst_host_capture_cancel():
    """Arrête la capture en cours (rendu, entraînement ou mesure) — 2026-10-05."""
    from . import plugin_capture
    r = plugin_capture.cancel()
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.post("/api/vst-host/capture/setup")
def vst_host_capture_setup():
    """Pose les outils de capture sur ce poste (Python isolé, torch, entraîneur NAM, signal v3)."""
    from . import plugin_capture
    r = plugin_capture.start_setup()
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.post("/api/vst-host/capture")
def vst_host_capture_start(body: dict):
    block, plugin = str(body.get("block") or ""), str(body.get("plugin") or "")
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block) or not plugin:
        return JSONResponse({"error": "invalid block"}, status_code=400)
    from . import plugin_capture
    r = plugin_capture.start(block, plugin, str(body.get("patch") or "Capture")[:80], str(body.get("mode") or "full"),
                             name=body.get("name"), dest=str(body.get("dest") or "new"), new_patch=body.get("new_patch"),
                             confirmed=body.get("confirmed") is True, gear=body.get("gear"))
    return r if r.get("ok") else JSONResponse(r, status_code=409)


# ── CAPTURE DES POTARDS (HyperWaveNet, environnement séparé du NAM fixe) ─────────────────────
@router.get("/api/vst-host/capture/parametric")
def vst_host_parametric_status(block: str = "", plugin: str = ""):
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block) or not plugin:
        return JSONResponse({"error": "invalid block"}, status_code=400)
    from . import plugin_capture as P, plugin_capture_parametric as K
    return {"job": P.status(), "setup": K.setup_status(), "check": K.check(block, plugin)}


@router.post("/api/vst-host/capture/parametric/plan")
def vst_host_parametric_plan(body: dict):
    block, plugin = str(body.get("block") or ""), str(body.get("plugin") or "")
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block) or not plugin:
        return JSONResponse({"error": "invalid block"}, status_code=400)
    from . import plugin_capture as P, plugin_capture_parametric as K
    try:
        return K.plan(body.get("plan"), P._live_params(block), P.recipe_for(plugin) or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)


@router.post("/api/vst-host/capture/parametric")
def vst_host_parametric_start(body: dict):
    block, plugin = str(body.get("block") or ""), str(body.get("plugin") or "")
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block) or not plugin:
        return JSONResponse({"error": "invalid block"}, status_code=400)
    from . import plugin_capture_parametric as K
    r = K.start(block, plugin, str(body.get("patch") or "Capture")[:80], body.get("plan"),
                name=body.get("name"), dest=str(body.get("dest") or "new"), new_patch=body.get("new_patch"),
                confirmed=body.get("confirmed") is True, gear=body.get("gear"))
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.post("/api/vst-host/capture/parametric/setup")
def vst_host_parametric_setup():
    if sys.platform not in ("win32", "darwin"):
        return JSONResponse({"error": "Capture tools are installed on Windows or macOS"}, status_code=409)
    from . import plugin_capture_parametric as K
    r = K.start_setup()
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.get("/api/vst-host/capture/parametric/model")
def vst_host_parametric_model(ref: str, model: str = ""):
    from . import plugin_capture_parametric as K
    try:
        return K.model_status(ref, model)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.post("/api/vst-host/capture/parametric/bake")
def vst_host_parametric_bake(body: dict):
    from . import plugin_capture_parametric as K
    try:
        return K.bake(str(body.get("ref") or ""), body.get("values"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return JSONResponse({"error": str(e)}, status_code=409)


@router.get("/api/vst-host/capture/parametric/download")
def vst_host_parametric_download(ref: str):
    from fastapi.responses import FileResponse
    from . import plugin_capture_parametric as K
    try:
        return FileResponse(K.model_file(ref), filename="capture-parametric.nam", media_type="application/json")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# ── RECETTES DE CAPTURE (2026-10-10, docs/plugin-recipes.md) ──────────────────────────────────
# L'IA de golem.fm propose, le rack MESURE, le musicien VALIDE. Le tiroir VST lit l'état, lance l'analyse,
# valide ; la vérification arrive par la file de jobs (`plugin-recipe`) et tourne à côté.
@router.get("/api/vst-host/recipe")
def vst_host_recipe(plugin: str):
    from . import plugin_recipes
    # le brouillon ENTIER : le tiroir montre aussi ce que la mesure a rejeté (barré), pas seulement ce qui sert
    return plugin_recipes.poll(plugin) or {"plugin": plugin, "state": None}


@router.post("/api/vst-host/recipe/analyze")
def vst_host_recipe_analyze(body: dict):
    block, plugin = str(body.get("block") or ""), str(body.get("plugin") or "")
    if sys.platform not in ("win32", "darwin") or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", block) or not plugin:
        return JSONResponse({"error": "invalid block"}, status_code=400)
    from . import plugin_recipes
    cur = plugin_recipes.load(plugin) or {}
    if cur.get("state") in ("analyzing", "verifying") and not body.get("restart"):
        return {k: v for k, v in cur.items() if k != "draft"}
    doc = plugin_recipes._save(plugin, state="analyzing", step="sheet", block=block, error=None, draft=None,
                               verification=None, request_id=None, shared=False, waiting=None)
    _threading.Thread(target=plugin_recipes.analyze, args=(block, plugin), daemon=True).start()   # fiche ≈ 11 s
    return {k: v for k, v in doc.items() if k != "draft"}


@router.post("/api/vst-host/recipe/validate")
def vst_host_recipe_validate(body: dict):
    from . import plugin_recipes
    try:
        doc = plugin_recipes.validate(str(body.get("plugin") or ""), body.get("edits") or [])
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return {k: v for k, v in doc.items() if k != "draft"}


@router.post("/api/vst-host/recipe/forget")
def vst_host_recipe_forget(body: dict):
    from . import plugin_recipes
    plugin_recipes.forget(str(body.get("plugin") or ""))
    return {"ok": True}


# ── POIDS D'UNE CAPTURE (2026-07-30) ────────────────────────────────────────────────────────
# Mesuré (tools/bench-lanes.py) : entre la capture la plus légère et la plus lourde de la
# bibliothèque, le coût CPU va du SIMPLE AU QUINTUPLE — ~8 %/cœur contre ~40 %/cœur par lane.
# Quand six lanes tournent ensemble (docs/patches.md §11), ça décide si le rack tient ou pas.
#
# ⚠ ET LE BADGE NE DOIT PARAÎTRE QUE QUAND IL DIT QUELQUE CHOSE. 95 % de la bibliothèque pèse
# entre 285 et 296 Ko — la migration A2 a tout uniformisé. Afficher « 288 Ko » partout serait du
# bruit qui masquerait les 34 captures lourdes. Seuils calés sur la distribution RÉELLE :
#   < 150 Ko  -> `light`  (4 captures)      > 400 Ko -> `heavy` (34)      sinon rien (678)
# La taille du fichier est un PROXY, pas une mesure : les deux extrêmes mesurés sont la même
# architecture (WaveNet 2) à 61 Ko et 2251 Ko, donc ici la taille suit bien le coût — mais une
# architecture nouvelle pourrait démentir. Le seul juge reste bench-lanes.py sur la machine.
_LIGHT_MAX = 150 * 1024
_HEAVY_MIN = 400 * 1024
_WEIGHTS = {"mtime": None, "by_model": {}}


def _model_weights():
    """{id de modèle: {bytes, load}} — recalculé quand l'index bouge, pas à chaque requête."""
    try:
        mt = os.path.getmtime(C.CATALOG) if os.path.exists(C.CATALOG) else None
    except OSError:
        mt = None
    if _WEIGHTS["mtime"] == mt:
        return _WEIGHTS["by_model"]
    out = {}
    d = _read_json(C.CATALOG, {"tones": []})
    tones = d.get("tones") or []
    it = tones.items() if isinstance(tones, dict) else [(t.get("id"), t) for t in tones]
    for _tid, t in it:
        for m in (t.get("models") or []):
            f = m.get("file")
            if not (f and f.endswith(".nam")):
                continue
            try:
                n = os.path.getsize(os.path.join(C.ROOT, f))
            except OSError:
                continue
            out[str(m.get("id"))] = {"bytes": n,
                                     "load": "light" if n < _LIGHT_MAX else "heavy" if n > _HEAVY_MIN else None}
    _WEIGHTS["mtime"], _WEIGHTS["by_model"] = mt, out
    return out


@router.get("/api/catalog")
def get_catalog():
    """Le catalogue, enrichi du POIDS de chaque capture (cf. _model_weights)."""
    d = _read_json(C.CATALOG, {"tones": [], "stats": {}})
    w = _model_weights()
    from . import ir_quality
    irq = ir_quality.load()                                  # « pack à écho » (2026-09-14) : lu, jamais déclaré
    tones = d.get("tones") or []
    it = tones.values() if isinstance(tones, dict) else tones
    for t in it:
        if str(t.get("gear") or "") == "cab":
            e = ir_quality.echo_of(t.get("id"), irq)
            if e:
                t["echo"] = e
        for m in (t.get("models") or []):
            k = w.get(str(m.get("id")))
            if k:
                m["bytes"] = k["bytes"]
                if k["load"]:
                    m["load"] = k["load"]
    return d


@router.post("/api/vst-host/capture/module/import")
async def import_capture_module(request: Request):
    from . import capture_module as CM
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 32 * 1024 * 1024:
            return JSONResponse({"error": "Capture module exceeds 32 MiB"}, status_code=413)
    try:
        entry = CM.install(json.loads(raw))
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "tone": entry}


@router.get("/api/vst-host/capture/module/download")
def download_capture_module(ref: str):
    from . import capture_module as CM
    from .resolver import _resolve
    path = _resolve(ref, {})
    if not path or not str(path).lower().endswith(".gcap"):
        return JSONResponse({"error": "Capture module not found"}, status_code=404)
    try:
        CM.load(path)
    except (ValueError, KeyError, OSError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return FileResponse(path, filename="golem-capture.gcap", media_type="application/json")


@router.get("/api/vital/presets")
def get_vital_presets():
    """Bibliothèque des presets .vital (lane Keys) — library/synth/vital/ (récursif, packs)."""
    from . import vital
    return {"presets": [{k: v for k, v in p.items() if k != "file"} for p in vital.list_presets()]}


@router.post("/api/vital/upload")
async def vital_upload(request: Request):
    """Ajoute un preset/pack Vital. Corps BRUT = octets du fichier (pas de multipart -> pas de dép).
    Nom d'origine dans ?name= : .vital -> pack 'user' ; .vitalbank/.zip -> extrait dans un pack nommé."""
    from . import vital
    name = request.query_params.get("name") or "preset.vital"
    try:
        data = await read_body(request, 80 * MB)
    except TooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    if not data:
        return JSONResponse({"error": "empty body"}, status_code=400)
    if len(data) > 80 * 1024 * 1024:                       # garde-fou (un pack .vital reste modeste)
        return JSONResponse({"error": "file too large (>80 MB)"}, status_code=413)
    r = vital.save_upload(name, data)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.post("/api/vital/rescan")
def vital_rescan():
    """Ré-indexe la bibliothèque (après un dépôt manuel de .vital dans library/synth/vital/)."""
    from . import vital
    ps = vital.list_presets()
    return {"ok": True, "count": len(ps),
            "presets": [{k: v for k, v in p.items() if k != "file"} for p in ps]}


@router.delete("/api/vital/preset/{pid}")
def vital_delete(pid: str):
    """Supprime un preset Vital (corbeille). Le pack factory/ (seed) est protégé."""
    from . import vital
    r = vital.delete_preset(pid)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


# ── perf rec + loops : enregistrer sa performance, la réécouter (Library ▸ Loops) ──
_RECORDINGS = os.path.join(C.ROOT, "recordings")
_PERF_STATUS = os.path.join(C.PRESETS_DIR, ".perf.json")


@router.get("/api/perf")
def perf_status():
    """Statut de l'enregistrement de performance (écrit par golem_perf côté Reaper)."""
    return _read_json(_PERF_STATUS, {"recording": False}) or {"recording": False}


@router.post("/api/perf/{action}")
def perf_toggle(action: str):
    """start | stop — commande consommée par le veilleur Reaper (contrat perf_rec)."""
    if action not in ("start", "stop"):
        return JSONResponse({"error": "start|stop"}, status_code=400)
    if action == "start":                                   # veto de mode (4.1) : STOP toujours permis
        from . import modes as modes_mod
        from .state import state
        if not modes_mod.allows("perfrec", state.mode):
            return JSONResponse({"error": "recording is disabled in this mode"}, status_code=409)
        # garde-fou de place (roadmap 0.a) : le seul moment où dire non ne coûte rien.
        from . import disk
        ok, why = disk.check_start()
        if not ok:
            return JSONResponse({"error": why, "disk": disk.status()}, status_code=507)
    from .commands import write_command
    if action == "start":                                   # une boucle de répète ferait enregistrer Reaper en boucle
        with contextlib.suppress(Exception):
            from . import app as _app
            _app._arr_ctl.clear_practice()
    write_command({"action": "perf_rec", "on": action == "start"})
    return {"ok": True, "asked": action}


@router.post("/api/metronome")
def metronome(body: dict):
    """Click on/off — moteur golem_click (chantier 2026-07-25) : piste service « Click » + JSFX
    free-running, tique transport ARRÊTÉ, suit le BPM du preset. Le nom historique de la route est
    conservé (bouton Recordings). Config = singleton config/click.json ; sortie = rôle 'click' du
    patch de la carte (sinon monitors — la Volt sort sur les enceintes comme le reste)."""
    from . import app as _app                       # import tardif : app importe ce module
    # `clock` seul = HORLOGE SILENCIEUSE (docs/arrangement.md §5) : le compteur tourne, rien ne
    # sonne. Un arrangement en mode `bars` en a besoin même quand le groupe refuse le métronome —
    # et ce chemin n'a PAS de veto de mode, parce que « pas de son » n'est pas « pas d'horloge ».
    if "on" not in (body or {}) and "clock" in (body or {}):
        _app._click_clock(bool(body.get("clock")))
        return {"ok": True, "clock": bool(body.get("clock"))}
    on = bool(body.get("on"))
    if not _app._click_set(on):                      # veto de mode (click_mode « off ») — le stop passe toujours
        return JSONResponse({"error": "the click is off in this mode"}, status_code=409)
    return {"ok": True, "on": on}


@router.post("/api/click/level")
def click_level(body: dict):
    """Le volume du click (dB, −60…+6), pour TOUS les clicks : métronome, décompte du Rec, click d'une prise
    de riff (docs/compo.md §14). Appliqué tout de suite si le métronome tourne."""
    from . import store
    from . import app as _app
    try:
        cfg = store.save_click_level((body or {}).get("level"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "level (dB) required"}, status_code=400)
    from .state import state
    if (state.click or {}).get("on"):
        _app._click_set(True)
    return {"ok": True, "level": cfg["level"]}


@router.get("/api/click")
def click_status():
    """État live du métronome (écrit par golem_click.lua) + config globale."""
    from .store import load_click_cfg
    st = _read_json(os.path.join(C.PRESETS_DIR, ".click.json"), {}) or {}
    return {**load_click_cfg(), **st}


_TRK_NUM = re.compile(r"^\d+-")                      # préfixe de piste Reaper : « 16-… »
_TRK_TS = re.compile(r"-\d{6}_\d{4}(-\d+)?$")        # suffixe date Reaper : « -260726_1751[-01] »
_TRK_IN = re.compile(r"input\s*#?\s*(\d+)")
_TRK_PLAIN = ("guitar", "bass", "voice", "keys", "drums", "pads", "line", "synth")


def _track_label(fn, roles):
    """Nom PARLANT d'une piste (« Guitar DI », « Voice », « Backing track », « Song mix ») à
    partir du nom technique — celui de golem_perfrec (Input-1.wav, DI-Sandbox-Input-1.wav) ou
    celui de Reaper pour les fichiers à plat (16-Recording_Sandbox #Input 2-260726_1751.wav).
    `roles` = numéro d'entrée -> libellé du patch, figé dans take.json au moment de la prise ;
    sans lui on retombe sur « Input N », jamais sur un nom faux."""
    s = os.path.splitext(fn)[0]
    s = _TRK_TS.sub("", _TRK_NUM.sub("", s))
    s = re.sub(r"^Recording[_-]?", "", s).strip()
    if not s:
        return "Song mix"                            # rendu du mix stéréo (mode « mix »)
    low = s.lower().replace("_", " ").replace("-", " ").strip()
    # capture MIDI = la « DI » d'un instrument MIDI (notes/vélocité/pédale, avant le synthé)
    midi = low.startswith("midi ")
    if midi:
        low = low[5:].strip()
    di = low.startswith("di ")
    if di:
        low = low[3:].strip()
    if low == "mix" or low.endswith(" mix"):
        return "Song mix"                            # multipiste : le mix complet gardé à côté
    if "backing" in low:
        return "Backing track"
    if "click" in low:
        return "Click"
    if "looper" in low:
        return "Looper"
    merged = "merge" in low
    if merged:
        low = low.replace("merge", "").strip()
    m = _TRK_IN.search(low)
    if m:
        base = roles.get(m.group(1)) or ("Input " + m.group(1))
    elif low in _TRK_PLAIN:
        base = low.capitalize()
    else:
        base = s
    return base + (" MIDI" if midi else "") + (" DI" if di else "") + (" (merged)" if merged else "")


def _labels(files, man):
    """Table nom technique -> nom parlant pour une prise.

    Les rôles viennent d'ABORD du manifeste (figés au moment de la prise, donc toujours justes).
    À défaut — prises d'avant ce champ — on retombe sur le patch COURANT : c'est du meilleur
    effort, faux seulement si les entrées ont été rebranchées depuis, et de toute façon plus
    utile que « Input 1 ». Aucun patch du tout -> « Input N », jamais un nom inventé."""
    roles = ((man or {}).get("roles")) or {}
    if not roles:
        with contextlib.suppress(Exception):
            from .state import state
            # même bug qu'au manifeste : `state.patch` n'existe pas, c'est `state.inputmap`.
            # Ici l'échec était plus discret encore — le repli silencieux rendait juste des
            # libellés bruts (« DI-Sandbox-Input-1 ») au lieu de « Guitar DI ».
            roles = {str(i.get("ch")): i.get("label") or i.get("role")
                     for i in ((state.inputmap or {}).get("inputs") or []) if i.get("ch")}
    return {f: _track_label(f, roles or {}) for f in files}


def _take_manifest_path(d):
    """Le manifeste d'une prise : dossier multipiste ou sidecar d'un .wav à plat."""
    # anti path-traversal : même garde que take_delete — basename, et rien d'autre
    p = os.path.join(_RECORDINGS, os.path.basename(str(d or "")))
    if os.path.isdir(p):
        return os.path.join(p, "take.json")
    return (p + ".json") if os.path.isfile(p) else None


def _retag(name, band):
    """Réécrit le SEUL champ `band` d'un manifeste, en place (takes.retag : le reste est un
    constat de la prise, jamais réécrit après coup ; une prise sans manifeste en reçoit un)."""
    from .takes import retag
    return retag(name, band)


@router.post("/api/take/title")
def take_title(body: dict = None):
    """Nomme une prise depuis l'écran Loops. `{dir|uid, title}` — `title` vide rend son nom
    automatique à la prise. golem.fm respecte ce titre s'il est là, sinon il titre depuis le
    backing / le standard / la compo / le preset (message-golem-enregistrements.md §8)."""
    from . import takes
    b = body or {}
    key = b.get("dir") or b.get("uid")
    if not key:
        return JSONResponse({"error": "dir or uid required"}, status_code=400)
    name = next((e["name"] for e in takes._entries()
                 if e["name"] == key or takes.uid_of(e["name"]) == key), None)
    if name is None:
        return JSONResponse({"error": f"unknown take: {key}"}, status_code=404)
    try:
        title = takes.set_title(name, b.get("title"))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    with contextlib.suppress(Exception):
        from . import rigstatus
        rigstatus.push_soon()
    return {"ok": True, "title": title}


@router.post("/api/take/cut")
def take_cut(body: dict = None):
    """Découpe une prise en morceaux depuis l'écran Loops. `{uid}` (ou `{uids:[…]}`), et
    `{bounds:[{offset_sec, duration_sec}]}` pour imposer les frontières à la main.
    Synchrone — on veut voir le résultat tout de suite quand on l'a demandé à l'écran."""
    from . import takecut, takes
    b = body or {}
    uids = b.get("uids") or ([b["uid"]] if b.get("uid") else [])
    if not uids:
        return JSONResponse({"error": "uid required"}, status_code=400)
    by_uid = {takes.uid_of(e["name"]): e["name"] for e in takes._entries()}
    out = []
    for u in uids:
        if u not in by_uid:
            out.append({"uid": u, "ok": False, "reason": "unknown_take"})
            continue
        out.append({"uid": u, **takecut.cut(by_uid[u], bounds=b.get("bounds"))})
    with contextlib.suppress(Exception):
        from . import rigstatus
        rigstatus.push_soon()
    return {"ok": True, "takes": out}


@router.post("/api/take/upload")
def take_upload(body: dict = None):
    """Monte des prises vers golem.fm — le même geste que le job `take-upload`, mais depuis
    l'écran Loops. `{uids: [...]}` (absent = tout ce qui est tagué), `{kinds: ["di","midi"]}`
    pour ajouter les DI. Rend `queued` : la montée est asynchrone, et sa progression se lit
    dans le heartbeat comme celle du web (docs/private/exchanges/message-maestrium-ranger-prises.md §2)."""
    from . import uploader
    b = body or {}
    kinds = b.get("kinds")
    kinds = tuple(uploader.DEFAULT_KINDS) + tuple(kinds) if kinds else None
    return uploader.queue(b.get("uids"), kinds)


@router.post("/api/take/band")
def take_band(body: dict):
    """Retague des prises. `dirs` (une ou plusieurs) OU `session` (toute la répète).

    C'EST LA CORRECTION D'UNE OBSERVATION, PAS UN FORMULAIRE. Le tag est posé tout seul à
    l'enregistrement, d'après le groupe courant du rack ; ici on répare, parce que la caisse
    se prête et qu'un défaut se trompe parfois. `band: null` remet la prise « en attente » —
    elle reste sur le rack et le dit (docs/private/repete-vers-demo.md §4).

    ⚠ On n'invente rien : le groupe doit être connu du rack. Un id libre ferait des tags
    fantômes que le serveur refuserait, et la prise resterait bloquée sans qu'on sache pourquoi.
    """
    band = (body or {}).get("band")
    if band is not None:
        from .routes_patches import _read_band
        d = _read_band()
        known = {b.get("id"): b for b in (d.get("bands") or []) if isinstance(b, dict)}
        cur = d.get("band") or {}
        if cur.get("id"):
            known.setdefault(cur["id"], cur)
        bid = band.get("id") if isinstance(band, dict) else band
        if bid not in known:
            return JSONResponse({"error": f"band unknown to this rack: {bid}"}, status_code=404)
        k = known[bid]
        # ⚠ `source` dit d'OÙ vient l'autorité du tag : un roster synchronisé (`cache`) ou le
        # roster local provisoire. Retaguer ne doit pas le PROMOUVOIR en silence — le serveur
        # s'en sert pour savoir à quel point il doit vérifier. On garde donc celui du groupe
        # courant quand c'est le même groupe.
        src = k.get("source") or (cur.get("source") if cur.get("id") == bid else None) or "cache"
        band = {"id": bid, "name": k.get("name") or bid, "source": src}

    targets = []
    sess = (body or {}).get("session")
    if sess:
        for fn in os.listdir(_RECORDINGS) if os.path.isdir(_RECORDINGS) else []:
            mp = _take_manifest_path(fn)
            if not mp or not os.path.isfile(mp):
                continue
            with contextlib.suppress(Exception):
                if (json.load(open(mp)) or {}).get("session") == sess:
                    targets.append((fn, mp))
    for d in ((body or {}).get("dirs") or []):
        mp = _take_manifest_path(d)
        # un .wav à plat SANS sidecar est une prise quand même (d'avant le manifeste) :
        # takes.retag lui en crée un — la garde n'exige plus que le manifeste existe déjà
        if mp and all(t[0] != d for t in targets):
            targets.append((d, mp))
    if not targets:
        return JSONResponse({"error": "no take targeted (dirs or session required)"}, status_code=404)
    done = []
    for name, mp in targets:
        with contextlib.suppress(Exception):
            _retag(name, band)
            done.append(name)
    if done:                                   # l'écran « À ranger » de golem.fm suit le retag local
        with contextlib.suppress(Exception):
            from . import rigstatus
            rigstatus.push_soon()
    return {"ok": True, "tagged": len(done), "takes": done, "band": band}


@router.get("/api/loops")
def loops_list():
    """Les performances enregistrées, plus récentes d'abord : .wav plats (mode mix) ET
    dossiers de PRISE multipiste (recordings/perf-<ts>/ + take.json — modes tracks/tracks_di)."""
    out, takes = [], []
    if os.path.isdir(_RECORDINGS):
        for fn in os.listdir(_RECORDINGS):
            p = os.path.join(_RECORDINGS, fn)
            if fn.lower().endswith(".wav") and os.path.isfile(p):
                man = _read_json(p + ".json", None)          # sidecar du mode mix (take.json plat)
                out.append({"file": fn, "bytes": os.path.getsize(p), "mtime": os.path.getmtime(p),
                            "labels": _labels([fn], man),
                            **({"manifest": man} if man else {})})
            elif os.path.isdir(p) and fn.startswith("perf-"):
                wavs = sorted(f for f in os.listdir(p) if f.lower().endswith(".wav"))
                if not wavs:
                    continue
                tman = _read_json(os.path.join(p, "take.json"), None)
                # captures MIDI (.mid) : pas de forme d'onde ni de lecteur audio, mais elles font
                # partie de la prise (c'est la « DI » d'un instrument MIDI) -> listées à part.
                mids = sorted(f for f in os.listdir(p) if f.lower().endswith(".mid"))
                # partition : ce qui fait que le bouton sait s'il dit « Transcribe » ou
                # « Score », et s'il doit être grisé (docs/archive/tablature-study.md §12).
                from . import transcribe_jobs as _tj
                elig, why = _tj.eligible(p)
                takes.append({"dir": fn, "files": wavs, "midi": mids, "mtime": os.path.getmtime(p),
                              "bytes": sum(os.path.getsize(os.path.join(p, f)) for f in wavs + mids),
                              "labels": _labels(wavs + mids, tman), "manifest": tman,
                              "score": _tj.score_of(p), "can_transcribe": elig,
                              **({"no_transcribe": why} if not elig else {})})
    out.sort(key=lambda x: -x["mtime"])
    takes.sort(key=lambda x: -x["mtime"])
    return {"loops": out, "takes": takes}


@router.post("/api/take/transcribe")
def take_transcribe(body: dict):
    """Met une prise dans la file de transcription. Le geste principal du §12 — et le seul
    chemin qui peut transcrire ce qui a été enregistré AVANT que la fonction existe."""
    from . import transcribe_jobs as _tj
    d = str((body or {}).get("dir") or "")
    if not d.startswith("perf-") or "/" in d or ".." in d:
        return JSONResponse({"error": "invalid take folder"}, status_code=400)
    r = _tj.enqueue(d)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.get("/api/take/score/{fn:path}")
def take_score(fn: str):
    """Sert une partition d'une prise : <perf-…>/scores/<nom>.musicxml."""
    from fastapi.responses import FileResponse
    safe = os.path.normpath(fn)
    if safe.startswith("..") or os.path.isabs(safe) or not safe.endswith(".musicxml"):
        return JSONResponse({"error": "bad path"}, status_code=400)
    p = os.path.join(_RECORDINGS, safe)
    if not os.path.isfile(p):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/vnd.recordare.musicxml+xml",
                        filename=os.path.basename(safe))


@router.get("/api/take/rpp/{name}")
def take_rpp(name: str):
    """Une prise en projet REAPER (bridge/take_rpp.py) : écrit le .rpp À CÔTÉ de l'audio, puis le sert —
    le dossier de la prise s'ouvre tel quel dans REAPER (ou un autre DAW) ailleurs."""
    from fastapi.responses import FileResponse
    from . import take_rpp as _rpp
    try:
        out = _rpp.export(name)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404 if "not found" in str(e) else 400)
    return FileResponse(out, media_type="application/octet-stream", filename=os.path.basename(out))


def _within(base, rel):
    """Le chemin `rel` résolu SOUS `base`, ou None (audit 2026-10-15 : un préfixe de chaîne laissait passer
    `assets/samplesX`, et `C:x` changeait de lecteur sous Windows)."""
    try:
        root = os.path.realpath(base)
        p = os.path.realpath(os.path.join(root, rel))
    except (OSError, ValueError):
        return None
    return p if os.path.commonpath([root, p]) == root and p != root else None


@router.get("/api/loop/{fn:path}")
def loop_serve(fn: str):
    """Sert un enregistrement (fichier plat OU <dossier de prise>/<piste>.wav)."""
    from fastapi.responses import FileResponse
    safe = os.path.normpath(fn)
    if safe.startswith("..") or os.path.isabs(safe) or safe.count(os.sep) > 1:
        return JSONResponse({"error": "bad path"}, status_code=400)
    p = _within(_RECORDINGS, safe)                  # `C:x` passait isabs sous Windows et changeait de lecteur
    if not p or not os.path.isfile(p):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="audio/wav", filename=os.path.basename(safe))


_PEAK_CACHE = {}          # (chemin, mtime, taille) -> payload ; les prises ne changent jamais


def _wav_peaks(path, buckets=1000):
    """Enveloppe d'amplitude d'un .wav pour l'affichage façon DAW.

    ⚠ Pas de numpy dans le venv du bridge, et une prise de 5 min = ~15 M trames : une boucle
    Python par échantillon serait inutilisable. Astuce : on ne garde que l'octet de POIDS FORT
    de chaque échantillon (`raw[sw-1::sw]`, découpe au niveau C) — 7 bits d'amplitude, largement
    assez pour DESSINER — puis `translate()` donne la valeur absolue et `max()` par tranche
    travaille sur des `bytes`. Tout le travail lourd reste en C ; la boucle Python ne fait que
    `buckets` tours. Indépendant du nombre de canaux : les échantillons entrelacés sont mélangés,
    ce qui revient à prendre la crête sur toutes les voies (exactement ce qu'on veut afficher)."""
    import wave
    with wave.open(path, "rb") as w:
        nfr, sw, fr, nch = w.getnframes(), w.getsampwidth(), w.getframerate(), w.getnchannels()
        if not nfr or not fr:
            return {"peaks": [], "dur": 0}
        raw = w.readframes(nfr)
    hi = raw[sw - 1::sw]
    if sw == 1:                                    # 8 bits = NON signé, centré sur 128
        tbl = bytes(min(255, abs(i - 128) * 2) for i in range(256))
    else:                                          # 16/24/32 bits : octet fort signé
        tbl = bytes(min(255, (256 - i if i > 127 else i) * 2) for i in range(256))
    mag = hi.translate(tbl)
    total = len(mag)
    step = max(1, total // buckets)
    pk = [round(max(mag[i:i + step]) / 255, 3) for i in range(0, total, step)][:buckets]
    return {"peaks": pk, "dur": round(nfr / fr, 3), "rate": fr, "ch": nch}


_PEAK_ROOTS = ("assets", "library", "recordings")     # racines auditionnables (anti path-traversal)


@router.get("/api/peaks")
def any_peaks(file: str = ""):
    """Enveloppe d'amplitude de N'IMPORTE QUEL .wav du dépôt (samples, kits, prises) — même
    contrat que /api/sample?file=… : chemin RELATIF à la racine, cantonné à des racines connues.
    Sert la grammaire « mini-DAW » partout dans la Library, pas seulement dans Recordings."""
    safe = os.path.normpath(file or "")
    if not safe or safe.startswith("..") or os.path.isabs(safe) \
       or safe.split(os.sep)[0] not in _PEAK_ROOTS:
        return JSONResponse({"error": "bad path"}, status_code=400)
    p = os.path.join(C.ROOT, safe)
    if not os.path.isfile(p) or not p.lower().endswith(".wav"):
        return JSONResponse({"error": "not found"}, status_code=404)
    return _peaks_cached(p)


def _peaks_cached(p):
    st = os.stat(p)
    key = (p, st.st_mtime, st.st_size)
    if key not in _PEAK_CACHE:
        try:
            _PEAK_CACHE[key] = _wav_peaks(p)
        except Exception as e:
            _PEAK_CACHE[key] = {"peaks": [], "dur": 0, "error": str(e)}
        if len(_PEAK_CACHE) > 600:
            for k in list(_PEAK_CACHE)[:200]:
                _PEAK_CACHE.pop(k, None)
    return _PEAK_CACHE[key]


@router.get("/api/loop-peaks/{fn:path}")
def loop_peaks(fn: str):
    """Enveloppe d'amplitude d'une prise (dessin de la forme d'onde côté UI). Mise en cache :
    un enregistrement ne change plus une fois écrit, la clé porte mtime+taille par sécurité."""
    safe = os.path.normpath(fn)
    if safe.startswith("..") or os.path.isabs(safe) or safe.count(os.sep) > 1:
        return JSONResponse({"error": "bad path"}, status_code=400)
    p = os.path.join(_RECORDINGS, safe)
    if not os.path.isfile(p):
        return JSONResponse({"error": "not found"}, status_code=404)
    return _peaks_cached(p)


@router.delete("/api/take/{d}")
def take_delete(d: str):
    """Supprime un DOSSIER de prise multipiste entier (recordings/perf-<ts>/)."""
    import shutil as _sh
    safe = os.path.basename(d)
    p = os.path.join(_RECORDINGS, safe)
    if not (safe.startswith("perf-") and os.path.isdir(p)):
        return JSONResponse({"error": "not a take"}, status_code=404)
    _sh.rmtree(p, ignore_errors=True)
    return {"ok": True}


@router.delete("/api/loop/{fn}")
def loop_delete(fn: str):
    safe = os.path.basename(fn)
    p = os.path.join(_RECORDINGS, safe)
    if not os.path.isfile(p):
        return JSONResponse({"error": "not found"}, status_code=404)
    os.remove(p)
    return {"ok": True}


# ── instruments SFZ (bloc `piano`, P1 claviers) ──────────────────────────────
@router.get("/api/sfz")
def sfz_list():
    """Instruments .sfz de library/sfz (récursif) — dynamic enum de la sheet piano."""
    import glob as _g
    base = os.path.join(C.ROOT, "library", "sfz")
    out = []
    import re as _re
    for f in sorted(_g.glob(os.path.join(base, "**", "*.sfz"), recursive=True)):
        rel = C.rel(f)
        nm = os.path.splitext(os.path.basename(f))[0]
        # nom HUMAIN (passe UX 2026-07-23) : vire versions/dates, dé-CamelCase, tirets -> espaces
        # ("SalamanderGrandPianoRetuned-V3+20200602" -> "Salamander Grand Piano Retuned")
        nm = _re.sub(r"[-+_ ]*[Vv]\d+([.+]\d+)*", "", nm)
        nm = _re.sub(r"[-+_ ]*\d{6,}", "", nm)
        nm = _re.sub(r"[-_+]+", " ", nm)
        nm = _re.sub(r"(?<=[a-z])(?=[A-Z])", " ", nm).strip() or os.path.basename(f)
        out.append({"id": rel, "name": nm})
    return {"instruments": out}


# ── banques DX7 (bloc `ep`, P1 claviers) ─────────────────────────────────────
@router.get("/api/dx7")
def dx7_list():
    """Banques .syx de library/dx7 — dynamic enum de la sheet ep (Dexed)."""
    import glob as _g
    base = os.path.join(C.ROOT, "library", "dx7")
    out = []
    for f in sorted(_g.glob(os.path.join(base, "**", "*.syx"), recursive=True)):
        rel = C.rel(f)
        out.append({"id": rel, "name": os.path.splitext(os.path.basename(f))[0],
                    "patches": _dx7_patch_names(f)})
    return {"banks": out}


def _dx7_patch_names(path):
    """Les 32 NOMS de patchs d'un bulk dump DX7 (session UI ep 2026-07-23) : header SysEx
    6 octets, puis 32 voix × 128 octets packés — le nom = octets 118..127 de chaque voix
    (ASCII 7 bits). Fichier hors format -> liste vide (la feuille retombe sur les numéros)."""
    try:
        raw = open(path, "rb").read()
        if len(raw) < 6 + 4096 or raw[0] != 0xF0:
            return []
        names = []
        for i in range(32):
            v = raw[6 + i * 128: 6 + (i + 1) * 128]
            nm = "".join(chr(c) if 32 <= c < 127 else " " for c in v[118:128]).strip()
            names.append(nm or f"Patch {i + 1}")
        return names
    except Exception:
        return []


# ── kits de pads (bloc `pads`, docs/blocks-doctrine.md) ──────────────────────
@router.get("/api/kits")
def kits_list():
    """Kits + samples disponibles (sheet du bloc pads + dynamic enum pad-kits)."""
    from . import kits
    return {"kits": kits.list_kits(), "samples": kits.list_samples(),
            "default_notes": list(kits.DEFAULT_NOTES), "modes": list(kits.MODES)}


@router.post("/api/kit/audition")
def kit_audition(body: dict):
    """L'écoute d'un son depuis le tiroir Pads (tap sur un pad, ▶ d'un sample) : joué par REAPER À TRAVERS la piste
    de la lane qui porte le bloc (ses FX, ses enceintes). body = {file, db?, block?} ; file vide = arrêter."""
    from . import kits
    from .commands import write_command
    from .state import state
    f = str((body or {}).get("file") or "")
    if f and not kits.sample_ok(f):
        return JSONResponse({"error": "unknown sample"}, status_code=400)
    track = _lane_track_of_block((body or {}).get("block"), state.preset_id)
    write_command({"action": "sample_preview", "file": f, "db": float((body or {}).get("db") or 0),
                   **({"track_idx": track} if track else {})})
    return {"ok": True, "track": track}


def _lane_track_of_block(block_id, pid):
    """L'index de piste REAPER (1-based) de la lane qui porte ce bloc, lu dans presets/.livemap.json (réécrit à chaque
    rebuild) : le bloc lui-même s'il y est, sinon le DERNIER bloc de la même lane — la piste qui sort vers les enceintes
    (le premier peut être un instrument, qui n'écoute pas l'audio qu'on lui envoie)."""
    from . import store
    lm = _read_json(os.path.join(C.PRESETS_DIR, ".livemap.json"), {}) or {}
    blocks = lm.get("blocks") or {}
    if block_id and (blocks.get(block_id) or {}).get("track"):
        return int(blocks[block_id]["track"])
    p = store.load_preset(pid) if pid else None
    for L in (p or {}).get("lanes") or []:
        ids = [b.get("id") for part in (L.get("chain") or {}).values() if isinstance(part, list) for b in part
               if isinstance(b, dict)]
        if block_id in ids:
            for i in reversed(ids):          # le DERNIER bloc : la piste de sortie (merge), pas l'instrument
                if (blocks.get(i) or {}).get("track"):
                    return int(blocks[i]["track"])
    return None


@router.post("/api/kit")
async def kit_save(kit: dict):
    from . import kits
    r = kits.save_kit(kit)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.delete("/api/kit/{kid}")
def kit_delete(kid: str):
    from . import kits
    r = kits.delete_kit(kid)
    return r if r.get("ok") else JSONResponse(r, status_code=403 if r.get("factory") else 404)


@router.get("/api/kit/{kid}/export")
def kit_export(kid: str):
    """Export .golemkit (zip portable : kit.json + samples/) — onglet Library ▸ Kits."""
    from fastapi.responses import Response
    from . import kits
    fn, data = kits.export_kit(kid)
    if fn is None:
        return JSONResponse({"error": data}, status_code=404)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@router.post("/api/kit/import")
async def kit_import(request: Request):
    """Import d'un .golemkit (corps BRUT = octets du zip, idiome vital/ir)."""
    from . import kits
    try:
        data = await read_body(request, 500 * MB)
    except TooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    if len(data) > 500 * 1024 * 1024:
        return JSONResponse({"error": "file too large (>500 MB)"}, status_code=413)
    r = kits.import_kit(data)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.get("/api/sample")
def sample_get(file: str):
    """Stream un sample (pré-écoute/download, onglet Library ▸ Samples). ?file=<rel repo>."""
    from fastapi.responses import FileResponse
    import mimetypes
    p = _within(os.path.join(C.ROOT, "assets", "samples"), os.path.relpath(os.path.join(C.ROOT, os.path.normpath(file)),
                                                                      os.path.join(C.ROOT, "assets", "samples")))
    if not p:
        return JSONResponse({"error": "not a sample path"}, status_code=400)
    if not os.path.isfile(p):
        return JSONResponse({"error": "not found"}, status_code=404)
    mt = mimetypes.guess_type(p)[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt, filename=os.path.basename(p))


@router.delete("/api/sample")
def sample_delete(file: str):
    """Supprime un sample INUTILISÉ (refus avec la liste des kits sinon)."""
    from . import kits
    r = kits.delete_sample(file)
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.post("/api/sample/upload")
async def sample_upload(request: Request):
    """Dépose un sample pour les pads (corps BRUT, idiome vital/ir). ?name=<origine>."""
    from . import kits
    name = request.query_params.get("name") or "sample.wav"
    kind = request.query_params.get("kind") or "short"          # short | song — l'onglet où l'on dépose
    try:
        data = await read_body(request, 200 * MB)
    except TooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    if len(data) > 200 * 1024 * 1024:
        return JSONResponse({"error": "file too large (>200 MB)"}, status_code=413)
    r = kits.save_sample(name, data, kind=kind)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.post("/api/sample/kind")
async def sample_kind_set(body: dict):
    """Corrige le type d'un sample (short ↔ song). Refusé si le sample est un stem d'un backing."""
    from . import kits
    r = kits.set_sample_kind((body or {}).get("file") or "", (body or {}).get("kind") or "")
    return r if r.get("ok") else JSONResponse(r, status_code=409 if "used" in (r.get("error") or "") else 400)


# ── grooves : patterns MIDI de batterie (bloc drums, param patterns/fills) ────
# ── presets PAR BLOC (tiroirs v2, docs/archive/block-sheets.md — patron delay.jpeg du QC) ─────
# Un preset de bloc = un réglage nommé d'UN type de bloc : library/block-presets/<type>/<slug>.json
# {name, type, params{...}}. Fichiers plats -> portables, versionnables, miroirables (tones-sync).
_BP_DIR = os.path.join(C.ROOT, "library", "block-presets")
from . import option_renames  # noqa: E402 — un preset de bloc enregistré avant le catalogue 31 garde ses vieilles étiquettes
_BP_SAFE = __import__("re").compile(r"[^\w\-]+")


def _bp_slug(s):
    return _BP_SAFE.sub("-", str(s or "").strip().lower()).strip("-")[:60] or "preset"


@router.get("/api/block-presets/{btype}")
def block_presets_list(btype: str):
    out = []
    d = os.path.join(_BP_DIR, _bp_slug(btype))
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                bp = _read_json(os.path.join(d, fn), None)
                option_renames.apply(bp)
                if isinstance(bp, dict) and isinstance(bp.get("params"), dict):
                    out.append({"id": fn[:-5], "name": bp.get("name") or fn[:-5],
                                "params": bp["params"], "factory": bool(bp.get("factory")),
                                "default": bool(bp.get("default")),
                                "inst": bp.get("inst") or "any"})
    return {"presets": out}


@router.get("/api/block-defaults")
def block_defaults():
    """{type: {inst: params}} des presets `default:true` — l'UI applique à l'AJOUT selon
    l'instrument de la lane : (type, lane) -> repli (type, any). Un bloc naît avec un
    réglage musical DE SON INSTRUMENT (comp voix ≠ comp basse)."""
    out = {}
    if os.path.isdir(_BP_DIR):
        for btype in sorted(os.listdir(_BP_DIR)):
            d = os.path.join(_BP_DIR, btype)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    bp = _read_json(os.path.join(d, fn), None)
                    option_renames.apply(bp)
                    if isinstance(bp, dict) and bp.get("default") and isinstance(bp.get("params"), dict):
                        out.setdefault(btype, {})[bp.get("inst") or "any"] = bp["params"]
    return {"defaults": out}


_BP_INSTS = ("guitar", "bass", "voice", "drums", "keys", "any")


def _bp_clear_default(btype, inst, keep_slug=None):
    """Unicité du défaut PAR (type, instrument) : retire default:true des autres presets."""
    d = os.path.join(_BP_DIR, _bp_slug(btype))
    if not os.path.isdir(d):
        return
    for fn in os.listdir(d):
        if not fn.endswith(".json") or fn[:-5] == keep_slug:
            continue
        fp = os.path.join(d, fn)
        bp = _read_json(fp, None)
        if isinstance(bp, dict) and bp.get("default") and (bp.get("inst") or "any") == inst:
            bp["default"] = False
            _write_json_atomic(fp, bp)


@router.post("/api/block-presets/{btype}")
async def block_presets_save(btype: str, body: dict):
    name = (body.get("name") or "").strip()
    params = body.get("params")
    inst = body.get("inst") or "any"
    if inst not in _BP_INSTS:
        inst = "any"
    if not name or not isinstance(params, dict):
        return JSONResponse({"error": "name and params required"}, status_code=400)
    d = os.path.join(_BP_DIR, _bp_slug(btype))
    os.makedirs(d, exist_ok=True)
    slug = _bp_slug(name)
    o = {"name": name, "type": btype, "inst": inst, "params": params}
    if body.get("default"):
        _bp_clear_default(btype, inst, keep_slug=slug)
        o["default"] = True
    _write_json_atomic(os.path.join(d, slug + ".json"), o)
    return {"ok": True, "id": slug}


@router.post("/api/block-presets/{btype}/{slug}/set-default")
def block_presets_set_default(btype: str, slug: str):
    """Promeut un preset comme DÉFAUT de son (type, instrument) — l'ancien défaut est déchu."""
    fp = os.path.join(_BP_DIR, _bp_slug(btype), _bp_slug(slug) + ".json")
    bp = _read_json(fp, None)
    if not isinstance(bp, dict):
        return JSONResponse({"error": "unknown block preset"}, status_code=404)
    inst = bp.get("inst") or "any"
    _bp_clear_default(btype, inst, keep_slug=_bp_slug(slug))
    bp["default"] = True
    _write_json_atomic(fp, bp)
    return {"ok": True, "inst": inst}


@router.delete("/api/block-presets/{btype}/{slug}")
def block_presets_delete(btype: str, slug: str):
    p = os.path.join(_BP_DIR, _bp_slug(btype), _bp_slug(slug) + ".json")
    if not os.path.isfile(p):
        return JSONResponse({"error": "unknown block preset"}, status_code=404)
    os.remove(p)
    return {"ok": True}


@router.get("/api/grooves")
def grooves_list():
    """Grooves MIDI de la lib (Library ▸ Grooves) + songs (arrangements golem.fm, Addendum 12)."""
    from . import grooves
    return {"grooves": grooves.list_grooves(), "songs": grooves.list_songs()}


def _smf_notes(path, max_notes=2000):
    """Notes d'un Standard MIDI File, pour DESSINER un groove (piano-roll de la Library).
    Un groove n'a pas de forme d'onde : ce qu'on veut voir, ce sont les frappes. Parseur SMF
    minimal (formats 0 et 1, statut courant géré) — pas de dépendance, quelques dizaines de lignes."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"MThd":
        return {"notes": [], "ppq": 480, "beats": 0}
    ppq = int.from_bytes(d[12:14], "big") or 480
    notes, on = [], {}
    p, end = 14, len(d)
    while p + 8 <= end:                                   # parcourt chaque chunk MTrk
        cid, ln = d[p:p + 4], int.from_bytes(d[p + 4:p + 8], "big")
        p += 8
        if cid != b"MTrk":
            p += ln
            continue
        q, stop, t, run = p, min(p + ln, end), 0, 0
        while q < stop:
            dt = 0                                        # delta-time (longueur variable)
            while q < stop:
                c = d[q]; q += 1; dt = (dt << 7) | (c & 0x7F)
                if c < 0x80:
                    break
            t += dt
            if q >= stop:
                break
            st = d[q]
            if st < 0x80:                                 # statut COURANT (octet de statut omis)
                st = run
            else:
                q += 1
                if st < 0xF0:
                    run = st
            if st == 0xFF:                                # méta : type + longueur + corps
                q += 1
                ml = 0
                while q < stop:
                    c = d[q]; q += 1; ml = (ml << 7) | (c & 0x7F)
                    if c < 0x80:
                        break
                q += ml
            elif st in (0xF0, 0xF7):                      # sysex
                sl = 0
                while q < stop:
                    c = d[q]; q += 1; sl = (sl << 7) | (c & 0x7F)
                    if c < 0x80:
                        break
                q += sl
            else:
                hi = st & 0xF0
                n1 = d[q] if q < stop else 0; q += 1
                n2 = d[q] if q < stop and hi not in (0xC0, 0xD0) else 0
                if hi not in (0xC0, 0xD0):
                    q += 1
                if hi == 0x90 and n2 > 0:
                    on.setdefault(n1, []).append((t, n2))
                elif hi == 0x80 or (hi == 0x90 and n2 == 0):
                    st0 = on.get(n1)
                    if st0:
                        t0, v = st0.pop(0)
                        if len(notes) < max_notes:
                            notes.append({"t": t0, "d": max(1, t - t0), "n": n1, "v": v})
        p += ln
    for n1, lst in on.items():                            # notes jamais relâchées : durée par défaut
        for t0, v in lst:
            if len(notes) < max_notes:
                notes.append({"t": t0, "d": ppq // 4, "n": n1, "v": v})
    notes.sort(key=lambda x: (x["t"], x["n"]))
    span = max((x["t"] + x["d"] for x in notes), default=0)
    return {"notes": notes, "ppq": ppq, "beats": round(span / ppq, 3)}


@router.get("/api/groove-notes")
def groove_notes(file: str = ""):
    """Piano-roll d'un groove — même contrat de chemin que /api/peaks (racines cantonnées)."""
    safe = os.path.normpath(file or "")
    if not safe or safe.startswith("..") or os.path.isabs(safe) \
       or safe.split(os.sep)[0] not in _PEAK_ROOTS:
        return JSONResponse({"error": "bad path"}, status_code=400)
    p = os.path.join(C.ROOT, safe)
    if not os.path.isfile(p) or not p.lower().endswith((".mid", ".midi")):
        return JSONResponse({"error": "not found"}, status_code=404)
    st = os.stat(p)
    key = ("smf", p, st.st_mtime, st.st_size)
    if key not in _PEAK_CACHE:
        try:
            _PEAK_CACHE[key] = _smf_notes(p)
        except Exception as e:
            _PEAK_CACHE[key] = {"notes": [], "ppq": 480, "beats": 0, "error": str(e)}
    return _PEAK_CACHE[key]


@router.post("/api/groove/import")
async def groove_import(request: Request):
    """Import d'un .mid GM (corps BRUT = octets du fichier, idiome vital/ir). ?name=<origine>."""
    from . import grooves
    name = request.query_params.get("name") or "groove.mid"
    try:
        data = await read_body(request, 2 * MB)                   # grooves.save_groove refuse déjà au-delà de 2 Mo
    except TooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    r = grooves.save_groove(name, data)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.get("/api/groove/{gid}")
def groove_download(gid: str):
    """Télécharge le .mid (download/export depuis la lib)."""
    import os
    from fastapi.responses import FileResponse
    from . import grooves
    path = os.path.join(grooves.GROOVES_DIR, grooves._safe_id(gid) + ".mid")
    if not os.path.isfile(path):
        return JSONResponse({"error": "unknown groove"}, status_code=404)
    return FileResponse(path, media_type="audio/midi", filename=gid + ".mid")


@router.delete("/api/groove/{gid}")
def groove_delete(gid: str):
    from . import grooves
    r = grooves.delete_groove(gid)
    return r if r.get("ok") else JSONResponse(r, status_code=404)


@router.post("/api/ir/upload")
async def ir_upload(request: Request):
    """Ajoute un IR (.wav) déposé depuis l'onglet Library ▸ IR. Corps BRUT = octets du fichier
    (pas de multipart -> pas de dép, comme Vital). Nom d'origine dans ?name=. L'IR est écrit sous
    assets/irs/user/ et inscrit au catalogue (tone gear=cab/format=ir) -> visible dans le picker Cab.
    La suppression passe par le flux amp partagé (/api/amp/{id})."""
    from . import irlib
    name = request.query_params.get("name") or "impulse.wav"
    try:
        data = await read_body(request, irlib.MAX_BYTES)
    except TooLarge as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    r = irlib.save_upload(name, data)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.post("/api/tones/import")
async def tones_import(request: Request):
    """Library ▸ Tones ▸ + Add ▸ Import files (docs/tone-import.md) : UN fichier par appel, corps BRUT, nom dans ?name=.
    .nam / .gcap / .wav / .zip ; le rapport dit ce qui est entré, ce qui est écarté et pourquoi (200 même si rien n'entre)."""
    from . import tone_import
    name = request.query_params.get("name") or "file"
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > tone_import.MAX_BYTES:
            return JSONResponse({"error": "File too large (more than 512 MB)"}, status_code=413)
    # hors boucle : un paquet de 50 Mo se déplie et s'écrit sur le disque
    return await asyncio.get_running_loop().run_in_executor(None, tone_import.import_file, name, bytes(raw))


# ── presets (CRUD) ───────────────────────────────────────────────────────────
@router.post("/api/preset")
async def save_preset(preset: dict):
    from .store import ensure_volume, migrate_config, save_recorder_cfg_from
    if str(preset.get("id") or "").startswith("patch:"):   # un patch se sauve comme PATCH (docs/patches.md)
        return JSONResponse({"error": "this is a patch — it saves into the patch library, not as a song"}, status_code=400)
    pid = _safe_id(preset.get("id") or preset.get("name"))
    if pid in ("sandbox-try", "nouveau-preset"):        # docs/patches.md §19 : aucun fichier sous l'id de l'essai
        return JSONResponse({"error": "the trial is not a preset — name it first"}, status_code=400)
    preset["id"] = pid
    # Rec = singleton : ses cases se règlent dans la feuille, qui passe par /api/sandbox_apply. Sauver un preset ne
    # fait monter que ce qui DIFFÈRE du brouillon (rien, en pratique) — jamais un Rec figé dans un fichier
    from .store import _read_json as _rj
    save_recorder_cfg_from(preset, prev=((_rj(os.path.join(C.PRESETS_DIR, ".sandbox.json"), {}) or {}).get("preset") or {}))
    migrate_config(preset)                             # services -> lane config (idempotent) + ré-hydrate le Rec
    ensure_volume(preset)                              # utilitaire système (bloc volume master, non affiché)
    # UNICITÉ des ids de blocs (audit 2026-09-08 §1) : scènes, cues et blocs par morceau adressent
    # par id, à plat — un doublon est ambigu et la compile le refuse. Dire NON ici, à l'écran,
    # plutôt que de laisser un preset qui ne se rappelle plus.
    from .store import duplicate_block_ids, duplicate_branch_ids
    dupes = duplicate_block_ids(preset)
    if dupes:
        return JSONResponse({"error": "duplicate block ids: " + ", ".join(dupes) + " — two blocks share an id across lanes"}, status_code=409)
    bdupes = duplicate_branch_ids(preset)
    if bdupes:
        return JSONResponse({"error": "duplicate branch ids: " + ", ".join(bdupes) + " — two lanes share a split branch id; scene mutes would hit both"}, status_code=409)
    _write_json_atomic(os.path.join(C.PRESETS_DIR, f"{pid}.json"), preset)
    # miroir du compte sur golem.fm, AU FIL DE L'EAU (docs/private/exchanges/message-maestrium-ranger-prises.md
    # §6) : débouncé, et seulement si l'EMPREINTE SONORE a bougé — renommer une couleur de
    # tuile ne déclenche rien. Un preset poussé est privé au compte (vérifié côté serveur), et
    # sans cette cadence `publish_preset` restait une route sans bouton que rien n'appelait.
    with contextlib.suppress(Exception):
        from . import tones_sync as _ts
        _ts.publish_soon(pid, preset=preset)
    # (l'ancien compile.compile_preset — .RfxChain/.plan.json du modèle legacy — est débranché :
    #  plus aucun lecteur vivant, cf. audit 2026-07-07. Le pipeline actif est compile_rig au recall.)
    #
    # ── ÉDITER LE PRESET QUI TOURNE DOIT SE VOIR (2026-08-04) ────────────────────────────────
    # `state.standard_block` n'était calculé QUE dans `_do_recall`. Éditer le preset chargé
    # laissait donc l'état courant périmé jusqu'au prochain rappel : le réglage « Live view » du
    # tiroir Standard s'écrivait bien dans le fichier et ne changeait rien à l'écran. C'est
    # exactement la panne du bouton « Show on Live » qu'il remplace — un réglage qui n'agit pas
    # est pire qu'un réglage absent.
    #
    # ── DÉCISION RENVERSÉE (2026-08-07) : LES REGISTRES DU PIED AUSSI ────────────────────────
    # Ce bloc était VOLONTAIREMENT limité à `standard_block`, au motif que recalculer les
    # registres du pied « changerait ce que fait le pédalier au milieu d'un set, sans rappel ».
    #
    # Ce motif ne tient pas : en mode Gig, `ui.pages` vaut ["live"] et `locked` est vrai — le
    # Designer est INACCESSIBLE. On ne peut donc pas éditer un preset au milieu d'un set ; le
    # moteur de modes traite déjà la question, à un meilleur endroit.
    #
    # Ce que ça coûtait, en revanche, est mesuré : `standards.switches()` fige une COPIE des
    # params (`dict(pm)`) au rappel. Régler le bloc Standard dans le tiroir écrivait le fichier
    # et l'appui sur son switch continuait de jouer l'instantané d'avant. Constaté au son
    # (« c'est une autre chanson qui joue »), puis chiffré : /live rendait « Take Five » en
    # 766 événements — le rendu NU, sans pack de batterie ni voicings — quand les réglages
    # enregistrés en donnaient 1618. Même morceau, arrangement méconnaissable.
    # Un réglage qui n'agit pas est pire qu'un réglage absent : c'était déjà l'argument du
    # paragraphe qu'il remplace.
    from .state import state
    if pid == getattr(state, "preset_id", None):
        from . import standards as standards_mod
        state.standard_block = standards_mod.block_of(preset)
        state.standard_meta = standards_mod.meta_of(preset)
        with contextlib.suppress(Exception):
            from . import app as _app
            from . import recall as _recall
            # standard/sample/drums/arrangement, rangée des scènes empruntée, switch du backing : le pied
            # SUIT l'édition — sur le preset TEL QUE LA LIGNE LE JOUE, comme au recall (§9.9)
            _app._bind_foot_services(_recall.effective_preset(preset))
        # push WS immédiat (même idiome que routes_modes) : sans lui l'écran garde l'ancien état
        with contextlib.suppress(Exception):
            from . import app as _app
            await _app._broadcast()
    # liens chanson<->preset poussés vers golem.fm (thread démon, best-effort)
    from . import golemfm
    golemfm.push_song_links()
    return {"ok": True, "id": pid}


# ── BALANCE : appliquer une lane à toute la setlist (docs/band-scenes.md, écran 6) ──────────────
@router.post("/api/lane-apply/plan")
def lane_apply_plan(body: dict):
    """body = {doc: <preset du Designer>, lane, setlist?} -> le plan, sans rien écrire. Les cibles sont
    les lignes de la setlist (l'active par défaut) ; la source est le DOCUMENT envoyé — le brouillon du
    Designer peut être en avance sur le fichier (auto-save débouncé)."""
    from . import lane_apply, setlists as _sl
    from .store import migrate_config
    doc = body.get("doc")
    if not isinstance(doc, dict):
        return JSONResponse({"error": "doc (the preset) is required"}, status_code=400)
    sid = body.get("setlist") or _sl.active_id()
    sl = _sl.load(sid) or {}
    from . import songs as _songs
    targets = [{"preset": _sl.pid_of(ln), "title": _songs.line_title(ln)} for ln in sl.get("lines") or [] if _sl.pid_of(ln)]
    out = lane_apply.plan(migrate_config(json.loads(json.dumps(doc))), str(body.get("lane") or ""), targets)
    return {**out, "setlist": {"id": sl.get("id"), "name": sl.get("name")}, "undo": lane_apply.pending_undo()}


@router.post("/api/lane-apply")
async def lane_apply_do(body: dict):
    """body = {doc, lane, presets:[ids]} -> écrit la lane dans chaque preset (sauvegardé avant)."""
    from . import lane_apply
    from .store import migrate_config
    doc = body.get("doc")
    if not isinstance(doc, dict):
        return JSONResponse({"error": "doc (the preset) is required"}, status_code=400)
    r = lane_apply.apply(migrate_config(json.loads(json.dumps(doc))), str(body.get("lane") or ""), body.get("presets") or [])
    with contextlib.suppress(Exception):
        from . import tones_sync as _ts
        for a in r.get("applied") or []:
            _ts.publish_soon(a["preset"])
    return r


@router.post("/api/lane-apply/undo")
def lane_apply_undo():
    from . import lane_apply
    return lane_apply.undo()


@router.delete("/api/preset/{pid}")
def delete_preset(pid: str):
    """Corps partagé avec le job `preset-delete` de golem.fm : store.delete_preset (patches.md §21)."""
    from .store import delete_preset as _del
    r = _del(pid)
    if not r["deleted"]:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"ok": True, "banks_freed": r["banks_freed"]}


# ── preview (guide sonore) : génération de la démo par scène (docs/preset-preview.md) ──
import threading as _threading
import itertools as _itertools
_preview_seq = _itertools.count(1)
_preview_thread = None


# ⚠ AVANT /api/preview/{pid} : FastAPI sert la première route qui correspond — sinon « batch » passait pour un id
@router.post("/api/preview/batch")
async def preview_batch(request: Request):
    """LE RENDU PAR LOT (docs/preset-preview.md §7) : les démos des patchs d'usine, une à la fois, reprenable (une
    démo à jour est sautée). Body optionnel {ids: [patch id…], force: bool}. 409 si un rendu tourne déjà ou si une
    prise enregistre. Se suit par GET /api/preview/batch, s'arrête par POST /api/preview/batch/stop."""
    from . import preview as preview_mod
    from .state import state
    global _preview_thread
    try:
        body = await request.json()
    except Exception:
        body = {}
    if (_preview_thread and _preview_thread.is_alive()) or preview_mod._BATCH["running"]:
        return JSONResponse({"error": "a generation is already running"}, status_code=409)
    if (state.perf or {}).get("recording"):
        return JSONResponse({"error": "a take is recording — try after it"}, status_code=409)
    ids = (body or {}).get("ids")
    if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
        return JSONResponse({"error": "ids: a list of patch ids"}, status_code=400)
    _preview_thread = _threading.Thread(
        target=preview_mod.batch, kwargs={"ids": ids, "force": bool((body or {}).get("force")),
                                          "seq_of": lambda: next(_preview_seq)}, daemon=True)
    _preview_thread.start()
    return {"ok": True, "total": len(ids) if ids else
            len(preview_mod.factory_patch_ids()) + len(preview_mod._preset_lanes(preview_mod.factory_preset_ids()))}


@router.get("/api/preview/batch")
def preview_batch_status():
    from . import preview as preview_mod
    return preview_mod.batch_status()


@router.post("/api/preview/batch/stop")
def preview_batch_stop():
    """Arrête le lot APRÈS le patch en cours (un rendu commencé finit, le moteur est remis comme avant)."""
    from . import preview as preview_mod
    preview_mod.stop_batch()
    return {"ok": True, "running": preview_mod._BATCH["running"]}


@router.post("/api/preview/blocks")
async def preview_blocks(request: Request):
    """LE RENDU DES BLOCS (docs/preset-preview.md §8) : 8 mesures de chaque bloc drums / standard au pied des presets et
    patchs d'usine, une à la fois, reprenable. Body optionnel {ids: [preset id ou « patch:<id> »…], force: bool}. 409 si
    un rendu tourne ou si une prise enregistre. Se suit par GET /api/preview/blocks, s'arrête par …/blocks/stop."""
    from . import preview as preview_mod
    from .state import state
    global _preview_thread
    try:
        body = await request.json()
    except Exception:
        body = {}
    if (_preview_thread and _preview_thread.is_alive()) or preview_mod._BATCH["running"] or preview_mod._BLOCKS["running"]:
        return JSONResponse({"error": "a generation is already running"}, status_code=409)
    if (state.perf or {}).get("recording"):
        return JSONResponse({"error": "a take is recording — try after it"}, status_code=409)
    ids = (body or {}).get("ids")
    if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
        return JSONResponse({"error": "ids: a list of preset ids"}, status_code=400)
    _preview_thread = _threading.Thread(
        target=preview_mod.batch_blocks, kwargs={"pids": ids, "force": bool((body or {}).get("force")),
                                                 "seq_of": lambda: next(_preview_seq)}, daemon=True)
    _preview_thread.start()
    return {"ok": True}


@router.get("/api/preview/blocks")
def preview_blocks_status():
    from . import preview as preview_mod
    return preview_mod.blocks_status()


@router.post("/api/preview/blocks/stop")
def preview_blocks_stop():
    """Arrête le lot APRÈS le bloc en cours."""
    from . import preview as preview_mod
    preview_mod.stop_blocks()
    return {"ok": True, "running": preview_mod._BLOCKS["running"]}


@router.post("/api/preview/{pid}")
async def gen_preview(pid: str, request: Request):
    """Lance la génération de la démo du preset (thread : re-amp Reaper + encode opus).
    Body optionnel {input:'1'|'2'|'k', ref:'voice/female'…} — preview CONTEXTUEL à l'entrée
    sélectionnée dans la carte (2026-07-24) : IN 2 = chaîne voix -> réf chantée M/F."""
    from . import preview as preview_mod
    global _preview_thread
    try:
        body = await request.json()
    except Exception:
        body = {}
    if _preview_thread and _preview_thread.is_alive():
        return JSONResponse({"error": "a generation is already running"}, status_code=409)
    if preview_mod._BATCH["running"]:
        return JSONResponse({"error": "the factory demos are rendering — wait or stop them"}, status_code=409)
    in_key = (body or {}).get("input")
    patch_id = preview_mod._patch_of(pid)
    if patch_id:
        # un PATCH (« patch:<id> », page Patches, 2026-11-03) : rendu comme quand on le joue, sur l'entrée à
        # laquelle il se lie sur CETTE carte
        from . import patches as P
        if not P.get_patch(patch_id):
            return JSONResponse({"error": "patch not found"}, status_code=404)
        in_key = in_key or preview_mod.patch_input(patch_id)
        if not in_key:
            return JSONResponse({"error": "no input of this card plays this patch"}, status_code=409)
    elif not os.path.exists(os.path.join(C.PRESETS_DIR, f"{_safe_id(pid)}.json")):
        return JSONResponse({"error": "preset not found"}, status_code=404)
    from .state import state
    if (state.perf or {}).get("recording"):
        return JSONResponse({"error": "a take is recording — try after it"}, status_code=409)
    seq = next(_preview_seq)
    _preview_thread = _threading.Thread(
        target=preview_mod.generate, args=(pid, seq),
        kwargs={"in_key": str(in_key or "1"), "ref": (body or {}).get("ref")},
        daemon=True)
    _preview_thread.start()
    return {"ok": True}


@router.get("/api/preview/status")
def preview_status():
    from . import preview as preview_mod
    return preview_mod.status()



# ── setlists ─────────────────────────────────────────────────────────────────
# (l'ancien GET /api/setlists — simple dump du dossier, relique de la feature retirée — a été
#  supprimé le 2026-07-27 : il MASQUAIT la nouvelle route, déclarée plus bas, car FastAPI sert
#  la première correspondance. Le contrat vit désormais dans bridge/setlists.py.)


@router.post("/api/setlist")
async def save_setlist(sl: dict):
    sid = _safe_id(sl.get("id") or sl.get("name"))
    sl["id"] = sid
    # ÉPINGLE AUTOMATIQUE (docs/patches.md §9.1) : un morceau qui ENTRE dans une setlist gèle
    # ses liens de patch sur leur révision inlinée — le moment précis où « que rien ne bouge
    # sous mes pieds » commence à compter. Diff avant/après : on n'épingle que les NOUVEAUX.
    before = set()
    try:
        with open(os.path.join(C.SETLISTS_DIR, f"{sid}.json")) as f:
            before = set(json.load(f).get("presets") or [])
    except Exception as _e:
        _swallowed(_e)
    _write_json_atomic(os.path.join(C.SETLISTS_DIR, f"{sid}.json"), sl)
    # ⚠ ICI, entrer dans une setlist ÉPINGLAIT les patches des morceaux (« que rien ne bouge
    # sous mes pieds »). Supprimé avec tout le modèle à révisions : plus rien ne bouge JAMAIS
    # sous les pieds de personne, une setlist n'a donc plus rien à figer (patches.md §15).
    return {"ok": True, "id": sid}


# NB : les templates de lane ont été RETIRÉS (2026-07-20) — l'API de création/liste n'existe
# plus. Le dossier templates/ et sa plomberie backup/import restent (compat des vieilles
# sauvegardes qui pourraient en contenir).


# ── export / publication d'un preset vers golem.fm (Store, Sprint 5.A.4) ─────
@router.get("/api/preset/{pid}/export")
def export_preset(pid: str):
    """Payload « preset complet » : doc natif + deps (assets par sha256) +
    foot_context. Contrat docs/archive/preset-schema.md. Prévisualisation locale ; la
    publication vers golem.fm passe par POST /api/preset/{pid}/publish."""
    from . import preset_export
    out, _ = preset_export.build_export(_safe_id(pid))
    if out is None:
        return JSONResponse({"error": "preset not found"}, status_code=404)
    return out


@router.post("/api/preset/{pid}/publish")
def publish_preset(pid: str):
    """Publie le preset (doc natif + blobs manquants) vers le Store golem.fm."""
    from . import tones_sync
    return tones_sync.publish_preset(_safe_id(pid))


@router.get("/api/catalog-blocks")
def catalog_blocks():
    """Catalogue de blocs CONSOLIDÉ pour golem.fm (Ré-réponse 5) : chaque bloc porte son
    identité visuelle RÉELLEMENT DESSINÉE (`color`/`glyph`, fusion effects.json + les maps
    BLOCK_COLOR/ICON du front) — source unique, clé = `catalog_version`. Sert le tri/rendu
    du Store même sur un type que golem.fm ne connaît pas encore."""
    try:
        c = json.load(open(C.EFFECTS))
    except (OSError, ValueError):
        return {"catalog_version": 1, "blocks": []}
    blocks = [{"type": b.get("type"), "name": b.get("name"), "short": b.get("short"),
               "category": b.get("category"), "color": b.get("color"), "glyph": b.get("glyph"),
               "params": b.get("params") or []}
              for b in (c.get("effects") or []) if isinstance(b, dict)]
    return {"catalog_version": c.get("catalog_version", 1), "blocks": blocks}


# ── intégrations (clés API : Tone3000, golem.fm) ─────────────────────────────
# L'assistant IA a quitté le rack le 2026-09-09 (décision : il vit sur golem.fm, docs/patches.md §14) :
# plus de fournisseur, de modèle ni de clé IA ici — un secret de moins sur un rack qui vit en salle.
# Stockées dans config/integrations.json (GITIGNORÉ). Seed depuis .env au 1er accès.
# Les secrets sont MASQUÉS en GET (l'app est joignable sur le LAN) et « blank-to-keep » en POST.
_INTEGRATIONS_PATH = os.path.join(C.CONFIG_DIR, "integrations.json")


# ── UN JETON A UN PROPRIÉTAIRE ET UN MAGASIN (2026-09-13, retour golem.fm après le M2 de l'audit).
# Ce fichier SEMAIT access_token / refresh_token depuis .env au premier accès, puis vivait sa vie :
# tools/t3k.py rafraîchit dans .env, jamais ici. Résultat : un instantané PÉRIMÉ des jetons, avec le
# nom et la forme du vrai, lisible (masqué) et ÉCRIVABLE depuis le LAN — et un champ « coller un
# jeton » dans Settings ▸ Connect ▸ TONE3000 (ex-API) qui menait au mur : deux machines sur une même lignée = rejeu =
# « refresh_token_already_used » = famille révoquée (le 9 septembre). Désormais : ici ne vit que le
# NON-SECRET (publishable_key = client_id OAuth, lu et écrit dans .env, le magasin du bridge) ; les
# jetons n'ont qu'un exemplaire, .env sous verrou, obtenus par le flux QR — jamais collés.
_T3K_LEGACY_KEYS = ("access_token", "refresh_token")


def _t3k_env():
    from . import routes_t3k
    return routes_t3k._t3k


def _integrations_default():
    return {
        "tone3000": {
            "publishable_key": _t3k_env().own_key(),                  # l'exemple de .env.example ne compte pas
        },
        # golem.fm (backing tracks) : base_url = serveur LAN (non secret), token = jeton
        # d'appareil obtenu par appairage (page Appareils de golem.fm) — cf. bridge/golemfm.py
        "golemfm": {
            "base_url": server_url(),
            "token": os.environ.get("GOLEMFM_TOKEN", ""),
            "auto_push": False,      # pousser chaque backup vers le vault golem.fm
        },
    }


def _load_integrations():
    d = _integrations_default()
    saved = _read_json(_INTEGRATIONS_PATH)
    if isinstance(saved, dict):
        t3k = dict(saved.get("tone3000") or {})
        # purge du reliquat : un jeton périmé qui a la forme du vrai est pire qu'absent — et la clé
        # vit dans .env, pas ici : rien de TONE3000 ne reste sur ce disque-là
        if any(k in t3k for k in _T3K_LEGACY_KEYS + ("publishable_key",)):
            for k in _T3K_LEGACY_KEYS + ("publishable_key",):
                t3k.pop(k, None)
            with contextlib.suppress(Exception):
                _write_json_atomic(_INTEGRATIONS_PATH, {**saved, "tone3000": t3k})
        d["tone3000"].update(t3k)
        d["golemfm"].update(saved.get("golemfm") or {})
        # LE SERVEUR VIENT DE .env (2026-10-31) : un base_url sauvé ailleurs (l'ancien menu Advanced) bascule vers
        # GOLEM_SERVER_URL — son jeton reste rangé sous lui, celui du serveur configuré revient
        if _norm_url(d["golemfm"].get("base_url")) != server_url():
            switch_server(d["golemfm"], server_url())
        # les clés des services de séparation payants (retirés de la v0.6, 2026-10-31) ne sont plus relues : la
        # prochaine sauvegarde de la page API les efface du disque
    _seed_servers(d["golemfm"])
    return d


# ── SERVEUR golem.fm (2026-10-31 : plus de menu Advanced) ──────────────────────────────
# L'adresse vient de .env : GOLEM_SERVER_URL, golem.fm par défaut ; un développeur met
# GOLEM_SERVER_URL=http://localhost:5173. `base_url`/`token` restent l'ACTIF (tout le bridge les lit via
# golemfm._cfg) ; `servers` garde le jeton DE CHAQUE serveur, pour que changer la variable ne réappaire rien
# — et ne présente jamais le jeton d'un serveur à un autre.
DEFAULT_SERVER = "https://golem.fm"


def _norm_url(u):
    return (u or "").strip().rstrip("/")


def server_url():
    """Le serveur golem.fm de ce golem : GOLEM_SERVER_URL (.env), sinon golem.fm."""
    return _norm_url(os.environ.get("GOLEM_SERVER_URL")) or DEFAULT_SERVER


def _seed_servers(m):
    """`servers` = {url: {label, token}} — l'actif, et le jeton actif rangé sous son serveur. Idempotent, sans
    écriture disque (la prochaine sauvegarde l'écrit)."""
    srv = m.get("servers") if isinstance(m.get("servers"), dict) else {}
    cur = _norm_url(m.get("base_url"))
    if cur:
        row = srv.setdefault(cur, {"label": "Custom", "token": ""})
        if m.get("token") and not row.get("token"):
            row["token"] = m["token"]
    m["servers"] = srv
    return srv


def server_url_ok(url):
    """Audit 2026-10-15 (S2) : le serveur golem.fm reçoit le jeton du rack et lui commande des jobs. En clair
    (`http://`), seulement vers cette machine ou le réseau local (golem.fm de DEV) ; partout ailleurs, https."""
    import ipaddress
    from urllib.parse import urlsplit
    try:
        u = urlsplit(_norm_url(url))
    except ValueError:
        return False
    if u.scheme == "https" and u.hostname:
        return True
    if u.scheme != "http" or not u.hostname:
        return False
    h = u.hostname
    if h == "localhost" or h.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def switch_server(m, url):
    """Bascule l'ACTIF vers `url` : le jeton du serveur quitté reste rangé sous lui, celui du serveur
    choisi revient (vide s'il n'a jamais été appairé)."""
    srv = _seed_servers(m)
    cur, new = _norm_url(m.get("base_url")), _norm_url(url)
    if cur and m.get("token"):
        srv.setdefault(cur, {"label": "Custom", "token": ""})["token"] = m["token"]
    m["base_url"] = new
    if new:
        m["token"] = srv.setdefault(new, {"label": "Custom", "token": ""}).get("token") or ""
    else:
        m["token"] = ""
    return m


def _mask(v):
    v = v or ""
    return {"set": bool(v), "hint": ("…" + v[-4:]) if len(v) >= 4 else ("set" if v else "")}


@router.get("/api/integrations")
def get_integrations():
    d = _load_integrations()
    return {
        "tone3000": {k: _mask(v) for k, v in d["tone3000"].items()},
        # base_url n'est pas un secret : renvoyée en clair (l'écran la dit) ; le token est masqué
        "golemfm": {"base_url": d["golemfm"]["base_url"], "token": _mask(d["golemfm"]["token"]),
                      "auto_push": bool(d["golemfm"].get("auto_push"))},
    }


@router.post("/api/integrations")
async def save_integrations(body: dict):
    """Enregistre les intégrations. Secrets vides = inchangés (blank-to-keep)."""
    d = _load_integrations()
    t3k = body.get("tone3000") or {}
    if any(t3k.get(k) for k in _T3K_LEGACY_KEYS):          # le mur : on ne colle pas un jeton
        return JSONResponse({"error": "TONE3000 tokens are never pasted — connect with the QR in Settings ▸ Connect ▸ TONE3000"}, status_code=400)
    if t3k.get("publishable_key"):
        try:
            _t3k_env().env_set({"T3K_PUBLISHABLE_KEY": str(t3k["publishable_key"]).strip()})   # le seul magasin : .env
        except ValueError:
            return JSONResponse({"error": "this doesn't look like a TONE3000 key"}, status_code=400)
    d["tone3000"] = {}                                     # rien de TONE3000 ne se persiste ici
    mst = body.get("golemfm") or {}
    if "base_url" in mst and _norm_url(mst.get("base_url")) != _norm_url(d["golemfm"]["base_url"]):
        return JSONResponse({"error": "the golem.fm server is set by GOLEM_SERVER_URL in .env"}, status_code=400)
    if mst.get("token"):                                   # secret : blank-to-keep
        d["golemfm"]["token"] = mst["token"]
        cur = _norm_url(d["golemfm"]["base_url"])
        if cur:
            d["golemfm"]["servers"].setdefault(cur, {"label": "Custom", "token": ""})["token"] = mst["token"]
    if "auto_push" in mst:
        d["golemfm"]["auto_push"] = bool(mst["auto_push"])
    _write_json_atomic(_INTEGRATIONS_PATH, d)
    return {"ok": True}


# ── mappings (FCB1010, Whammy) ───────────────────────────────────────────────
@router.get("/api/mappings")
def list_mappings():
    """Les PÉDALES MIDI physiques du rig — un mapping par pédale (2026-07-28).

    Critère : un mapping qui porte des `modes` est une pédale (on peut lui envoyer des program
    changes et l'afficher). Le layout du FCB1010, qui vit dans le même dossier, n'en a pas : il
    n'est pas une pédale d'effet, il ne sort donc pas d'ici. Renvoie l'ENTÊTE seulement — la page
    liste des cartes, elle ne charge le détail (39 modes pour la Whammy) qu'à la sélection.
    """
    import glob as _glob
    out = []
    for p in sorted(_glob.glob(os.path.join(C.MAPPINGS_DIR, "*.json"))):
        d = _read_json(p, None)
        if not isinstance(d, dict) or not d.get("id"):
            continue
        # `kind` (contrat docs/pedal-registry.md) fait foi ; repli sur « porte des modes » pour
        # les fichiers antérieurs au schéma.
        kind = d.get("kind") or ("pedal" if isinstance(d.get("modes"), list) else "controller")
        if kind != "pedal" or not isinstance(d.get("modes"), list):
            continue
        fams = d.get("families") or {}
        out.append({
            "id": d["id"], "name": d.get("name") or d["id"], "device": d.get("device") or "",
            "midi_out": d.get("midi_out") or "", "channel": d.get("channel") or 1,
            "treadle_cc": (d.get("treadle") or {}).get("cc") or d.get("treadle_cc"),
            "modes": len(d["modes"]),
            "families": [{"id": k, "label": (v or {}).get("label") or k} for k, v in fams.items()],
            # niveau de confiance du mapping (docs/pedal-registry.md §2) : `provenance` fait foi,
            # repli sur l'ancien champ libre `_source` pour les fichiers d'avant le schéma.
            "confidence": (d.get("provenance") or {}).get("confidence")
                          or ("verified" if "CALIBRÉ" in (d.get("_source") or "").upper() else None),
            "source": (d.get("provenance") or {}).get("source"),
            "brand": (d.get("identity") or {}).get("brand"),
            "firmware": (d.get("identity") or {}).get("firmware"),
            "connection": (d.get("identity") or {}).get("connection"),
        })
    return {"pedals": out}


# ── catalogue de pédales (docs/pedal-registry.md) ────────────────────────────
# DEUX ENDROITS, et c'est une correction du contrat écrite au premier test réel (2026-07-29) :
#   library/pedals/  = le CATALOGUE livré, versionné, en lecture seule — le seed
#   mappings/        = les pédales INSTALLÉES sur CE rack
# Le contrat disait « le seed vit dans mappings/ » : faux. Supprimer sa pédale y effaçait aussi
# la référence, et il ne restait que le wizard manuel — qui ne sait même pas capturer les PC de
# bypass. Un catalogue qu'on peut détruire en désinstallant n'est pas un catalogue.
PEDALS_CATALOG = os.path.join(C.ROOT, "library", "pedals")


@router.get("/api/pedals/catalog")
def pedals_catalog():
    """Les modèles connus de GoleM, avec l'état « déjà installé sur ce rack »."""
    import glob as _glob
    installed = {os.path.splitext(os.path.basename(p))[0]
                 for p in _glob.glob(os.path.join(C.MAPPINGS_DIR, "*.json"))}
    out = []
    for p in sorted(_glob.glob(os.path.join(PEDALS_CATALOG, "*.json"))):
        d = _read_json(p, None)
        if not isinstance(d, dict) or not d.get("id"):
            continue
        idt = d.get("identity") or {}
        out.append({
            "id": d["id"], "name": d.get("name") or d["id"],
            "brand": idt.get("brand"), "model": idt.get("model"),
            "firmware": idt.get("firmware"), "connection": idt.get("connection"),
            "modes": len(d.get("modes") or []),
            "confidence": (d.get("provenance") or {}).get("confidence"),
            "source": (d.get("provenance") or {}).get("source"),
            "steps": sum(len(ph.get("steps") or []) for ph in ((d.get("install") or {}).get("phases") or [])),
            "installed": d["id"] in installed,
        })
    return {"pedals": out}


@router.post("/api/pedals/install")
def pedals_install(body: dict):
    """Installe un modèle du catalogue sur ce rack : copie le descripteur dans mappings/.

    C'est LE geste « correct du premier coup » — on ne recalibre pas ce qui est déjà connu.
    Refus si le fichier existe : réinstaller par-dessus effacerait des réglages locaux en
    silence (canal MIDI changé sur l'appareil, étiquettes corrigées…).
    """
    pid = _safe_id((body or {}).get("id") or "")
    src = os.path.join(PEDALS_CATALOG, f"{pid}.json")
    if not os.path.isfile(src):
        return JSONResponse({"error": f"model not in the catalogue: {pid}"}, status_code=404)
    dst = os.path.join(C.MAPPINGS_DIR, f"{pid}.json")
    if os.path.exists(dst):
        return JSONResponse({"error": "already installed — remove it first"}, status_code=409)
    d = _read_json(src, None)
    if not isinstance(d, dict):
        return JSONResponse({"error": "descripteur illisible"}, status_code=500)
    import time as _t                       # `_time` n'est importé que plus bas dans ce module
    d["installed_at"] = _t.strftime("%Y-%m-%dT%H:%M:%S")
    d["installed_from"] = "catalog"
    _write_json_atomic(dst, d)
    return {"ok": True, "id": pid, "modes": len(d.get("modes") or []),
            "steps": sum(len(ph.get("steps") or []) for ph in ((d.get("install") or {}).get("phases") or []))}


@router.post("/api/pedals/{pid}/verify")
def pedals_verify(pid: str, body: dict):
    """Verdict de la VÉRIFICATION sur CE rack (docs/pedal-registry.md §2, tier `verify`).

    Distinction qui compte : le catalogue peut dire `verified` — ça veut dire « vérifié par
    quelqu'un, quelque part ». Ici on écrit ce que TON rack a constaté, avec la date et le détail
    de ce qui a échoué. C'est cette information-là qui aurait de la valeur si on la remontait un
    jour (§7) : un descripteur confirmé par N racks n'est pas un descripteur affirmé par un.
    """
    p = os.path.join(C.MAPPINGS_DIR, f"{_safe_id(pid)}.json")
    d = _read_json(p, None)
    if not isinstance(d, dict):
        return JSONResponse({"error": "pedal not installed"}, status_code=404)
    b = body or {}
    failed = [str(x) for x in b.get("failed") or []]
    scope = "full" if b.get("scope") == "full" else "quick"
    import time as _t
    prov = dict(d.get("provenance") or {})
    prov["verified_here"] = {
        "at": _t.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok": not failed,
        "scope": scope,                      # quick = les contrôles canoniques · full = tous les modes
        "checked": int(b.get("checked") or 0),
        "failed": failed,
    }
    # UN SEUL verdict dans le fichier : l'ancien champ `verified` (écrit par la vérification
    # complète, qui réécrivait le mapping entier depuis le navigateur) disparaît. Deux champs qui
    # racontent la même chose, c'est ainsi qu'un fichier commence à mentir.
    d.pop("verified", None)
    # une vérif qui ÉCHOUE dégrade la confiance : le fichier ne peut plus se dire « verified »
    # sur ce rack — c'est précisément le cas où l'utilisateur doit voir un doute affiché.
    if failed:
        prov["confidence"] = "unconfirmed"
    d["provenance"] = prov
    _write_json_atomic(p, d)
    return {"ok": True, "verified": not failed, "failed": failed}


@router.delete("/api/pedals/{pid}")
def pedals_remove(pid: str):
    """Désinstalle une pédale de CE rack. Le catalogue n'est jamais touché : on peut la
    réinstaller d'un tap. (Manque relevé au premier test : il fallait effacer le fichier à la main.)"""
    p = os.path.join(C.MAPPINGS_DIR, f"{_safe_id(pid)}.json")
    if not os.path.isfile(p):
        return JSONResponse({"error": "not found"}, status_code=404)
    os.remove(p)
    return {"ok": True}


@router.get("/api/mapping/{name}")
def get_mapping(name: str):
    return _read_json(os.path.join(C.MAPPINGS_DIR, f"{_safe_id(name)}.json"), {})


@router.post("/api/mapping")
async def save_mapping(m: dict):
    mid = _safe_id(m.get("id") or m.get("name"))
    m["id"] = mid
    _write_json_atomic(os.path.join(C.MAPPINGS_DIR, f"{mid}.json"), m)
    return {"ok": True, "id": mid}


# ── gestion des amplis : usage (dépendances) + suppression avec corbeille ────
import shutil as _shutil
import time as _time

_CAT_INDEX = os.path.join(C.ROOT, "library", "catalog", "tones-index.json")
_IMG_OVERLAY = os.path.join(C.ROOT, "library", "catalog", "images.json")
_SANDBOX = os.path.join(C.PRESETS_DIR, ".sandbox.json")
_TRASH = os.path.join(C.ROOT, "assets", ".trash")


def _iter_blocks_all(p):
    """Tous les blocs d'un preset (guitare pre/split/post + voix), tous schémas.
    Ne rend QUE les dicts (l'ancien voice.chain est une liste de STRINGS 'gate'/'comp'…)."""
    from .store import all_blocks                                   # lot 4 : toutes les lanes, v2 ou legacy
    for b, lane in all_blocks(p):
        if isinstance(b, dict) and lane not in ("gen", "rec", "arr"):
            yield b


def _deps_of(tid):
    """Qui référence ce tone ? -> {presets:[{id,name,blocks:[label]}], templates:[...], sandbox:bool}"""
    tid = str(tid)
    deps = {"presets": [], "templates": [], "sandbox": False}
    for path in sorted(glob.glob(os.path.join(C.PRESETS_DIR, "*.json"))):
        if os.path.basename(path).startswith("."):
            continue
        p = _read_json(path, None)
        if not isinstance(p, dict):
            continue
        hit = [b.get("label") or b.get("type", "?") for b in _iter_blocks_all(p) if str(b.get("ref")) == tid]
        if hit:
            deps["presets"].append({"id": p.get("id"), "name": p.get("name"), "blocks": hit})
    for path in sorted(glob.glob(os.path.join(C.TEMPLATES_DIR, "*.json"))):
        t = _read_json(path, None) or {}
        if any(str(b.get("ref")) == tid for b in t.get("blocks", [])):
            deps["templates"].append(t.get("id") or os.path.basename(path))
    sb = _read_json(_SANDBOX, None)
    if sb and any(str(b.get("ref")) == str(tid) for b in _iter_blocks_all(sb.get("preset") or {})):
        deps["sandbox"] = True
    return deps


@router.get("/api/amp/{tid}/usage")
def amp_usage(tid: str):
    return _deps_of(tid)


@router.post("/api/amp/{tid}/family")
async def amp_family(tid: str, body: dict):
    """Section basse (QC-gap 1) : classe un tone en famille 'guitar'|'bass'.
    Écrit `family` dans tones-index.json ; null/absent = retour à l'heuristique
    (tag 'bass' → bass). L'UI filtre là-dessus (Amps, SimList, T3K)."""
    fam = (body or {}).get("family")
    if fam not in ("guitar", "bass", None):
        return JSONResponse({"error": "family: guitar | bass | null"}, status_code=400)
    d = _read_json(_CAT_INDEX, {"tones": []}) or {"tones": []}
    t = next((x for x in d.get("tones", []) if str(x.get("id")) == str(tid)), None)
    if t is None:
        return JSONResponse({"error": f"tone {tid} not found"}, status_code=404)
    if fam is None:
        t.pop("family", None)
    else:
        t["family"] = fam
    _write_json_atomic(_CAT_INDEX, d)
    return {"ok": True, "id": tid, "family": fam}


def _apply_ref_action(p, tid, action):
    """Applique l'action à tous les blocs du preset qui référencent tid.
    clear -> le bloc redevient « choose a model » (dégradation propre gérée par le Designer)."""
    changed = False
    for b in _iter_blocks_all(p):
        if str(b.get("ref")) != str(tid):
            continue
        if action.get("mode") == "replace" and action.get("ref"):
            b["ref"] = action["ref"]
            b.pop("model", None)
            if action.get("model") is not None:
                b["model"] = action["model"]
        else:                               # clear
            b.pop("ref", None)
            b.pop("model", None)
            b.pop("file", None)
        changed = True
    return changed


@router.delete("/api/amp/{tid}")
async def amp_delete(tid: str, body: dict = None):
    """Supprime un ampli du catalogue, en CORBEILLE (assets/.trash/<ts>/), avec gestion des
    dépendances PAR PRESET : body.actions = { "<preset_id>": {mode:"replace", ref, model?} |
    {mode:"clear"} } (défaut clear). Les .nam PARTAGÉS (packs éclatés) ne partent à la corbeille
    que si plus AUCUNE entrée restante ne les référence."""
    body = body or {}
    actions = body.get("actions") or {}
    cat = _read_json(_CAT_INDEX, {"tones": []}) or {"tones": []}
    entry = next((t for t in cat["tones"] if str(t.get("id")) == str(tid)), None)
    if not entry:
        return JSONResponse({"error": "unknown amp"}, status_code=404)

    # 1. presets dépendants : remplacer / vider (choix PAR PRESET)
    touched = []
    for dep in _deps_of(tid)["presets"]:
        path = os.path.join(C.PRESETS_DIR, f"{dep['id']}.json")
        p = _read_json(path, None)
        if p and _apply_ref_action(p, tid, actions.get(str(dep["id"]), {"mode": "clear"})):
            _write_json_atomic(path, p)
            touched.append(dep["id"])
    # templates + buffer sandbox : vidés (pas de choix, contenu jetable/regénérable)
    for path in sorted(glob.glob(os.path.join(C.TEMPLATES_DIR, "*.json"))):
        t = _read_json(path, None)
        if t and _apply_ref_action(t, tid, {"mode": "clear"}):
            _write_json_atomic(path, t)
    sb = _read_json(_SANDBOX, None)
    if sb and _apply_ref_action(sb.get("preset") or {}, tid, {"mode": "clear"}):
        _write_json_atomic(_SANDBOX, sb)

    # 2. catalogue : retire l'entrée (les dérivées d'un pack restent — refcount fichiers ci-dessous)
    cat["tones"] = [t for t in cat["tones"] if str(t.get("id")) != str(tid)]
    _write_json_atomic(_CAT_INDEX, cat)

    # 3. fichiers : corbeille si plus référencés par AUCUNE entrée restante
    still = {m.get("file") for t in cat["tones"] for m in t.get("models", [])}
    tdir = os.path.join(_TRASH, _time.strftime("%Y%m%d-%H%M%S") + f"_{tid}")
    trashed = []
    for m in entry.get("models", []):
        rel = m.get("file")
        # audit 2026-11-04 (H1) : le chemin vient du catalogue — confiné sous assets/, sinon on ne déplace rien
        from .resolver import _asset_path
        src = _asset_path(rel) if rel else None
        if src and rel not in still and os.path.exists(src):
            dst = os.path.join(tdir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _shutil.move(src, dst)
            trashed.append(rel)
    # photo : overlay + fichier
    ov = _read_json(_IMG_OVERLAY, {"tones": {}}) or {"tones": {}}
    img = (ov.get("tones") or {}).pop(str(tid), None)
    if img:
        _write_json_atomic(_IMG_OVERLAY, ov)
        src = os.path.join(C.ROOT, "library", img.get("file", ""))
        if os.path.exists(src):
            os.makedirs(tdir, exist_ok=True)
            _shutil.move(src, os.path.join(tdir, os.path.basename(img["file"])))
    # l'entrée elle-même (restaurable à la main)
    os.makedirs(tdir, exist_ok=True)
    _write_json_atomic(os.path.join(tdir, "catalog-entry.json"), entry)

    return {"ok": True, "trash": C.rel(tdir), "trashed_files": trashed,
            "presets_updated": touched}


# ── sample SETS : modèles ORDONNÉS pour le bloc Sample (2026-07-23) ─────────────────
# Un set = une liste nommée de samples dans l'ordre de cycle du pied — même philosophie que
# les Songs de la drum machine : un template qu'on APPLIQUE au bloc (le moteur ne change pas).
# library/sample-sets/<slug>.json {name, samples:[{file, name}], origin, pack?}. Poussé par
# golem.fm via le job "sample-pack" (Addendum 15) ou sauvé depuis la feuille du bloc.
_SS_DIR = os.path.join(C.ROOT, "library", "sample-sets")


@router.get("/api/sample-sets")
def sample_sets_list():
    out = []
    if os.path.isdir(_SS_DIR):
        for fn in sorted(os.listdir(_SS_DIR)):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(_SS_DIR, fn)))
                    d["slug"] = fn[:-5]
                    out.append(d)
                except Exception as _e:
                    _swallowed(_e)
    return {"sets": out}


@router.post("/api/sample-sets")
async def sample_sets_save(body: dict):
    name = (body.get("name") or "").strip()
    samples = [s for s in (body.get("samples") or []) if s.get("file")]
    if not name or not samples:
        return JSONResponse({"error": "name and samples required"}, status_code=400)
    slug = _bp_slug(name)
    os.makedirs(_SS_DIR, exist_ok=True)
    _write_json_atomic(os.path.join(_SS_DIR, slug + ".json"),
                       {"name": name, "samples": samples, "origin": body.get("origin") or "user"})
    return {"ok": True, "slug": slug}


@router.delete("/api/sample-sets/{slug}")
def sample_sets_delete(slug: str):
    p = os.path.join(_SS_DIR, _bp_slug(slug) + ".json")
    if not os.path.isfile(p):
        return JSONResponse({"error": "unknown set"}, status_code=404)
    os.remove(p)
    return {"ok": True}


# ── setlists (groupes de presets — contrat docs/setlists.md) ─────────────────
@router.get("/api/setlists")
def setlists_list():
    """Toutes les setlists (active en tête) + les instantanés. Une seule requête : la page en a
    besoin des deux, et elles sont minuscules."""
    from . import setlists as sl
    # les lignes telles qu'elles JOUENT (`view`) : une ligne {band_song} montre sa chanson (§9.7)
    from . import factory
    return {"active": sl.active_id(), "setlists": factory.mark("setlists", [sl.view(x) for x in sl.list_all()]),
            "snapshots": sl.list_snapshots()}


@router.post("/api/setlists")
def setlists_create(body: dict):
    """Crée une setlist, NOMMÉE à la création (2026-07-28).

    L'ancien « Save current banks » a disparu : il ne sauvegardait rien — toute assignation de
    bank est déjà écrite à la frappe dans la setlist active. C'était un duplicata déguisé en
    sauvegarde, qui pondait des noms jetables. Restent deux départs honnêtes :
      `from_banks: true` → copie de ce qui est au pied · sinon → vide (on compose dans la grille).
    """
    from . import setlists as sl
    presets = body.get("presets")
    if body.get("from_banks"):
        presets = (sl.load(sl.active_id()) or {}).get("presets") or []
    over = sl.over_cap(presets)
    if over:
        return JSONResponse({"error": over}, status_code=409)
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    # `kind` (docs/patches.md §7) : « songs » (défaut) ou « sounds » — une bank de patches, fixée ici
    kind = body.get("kind") if body.get("kind") in sl.KINDS else "songs"
    try:
        out = sl.create(name, presets, kind=kind)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _foot_lists_changed()
    return out


@router.post("/api/setlists/{sid}/patches")
def setlists_add_patches(sid: str, body: dict):
    """« Add to a bank » (Songs ▸ Patches) : des PATCHES en fin de bank de sons. body = {ids: [...]}.
    Refus dits : une setlist de morceaux, un patch inconnu, la bank pleine. Push miroir comme toute écriture."""
    from . import setlists as sl
    try:
        out = sl.add_patches(sid, (body or {}).get("ids") or [])
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)
    return sl.view(out)


@router.post("/api/setlists/{sid}/activate")
def setlists_activate(sid: str):
    """Active une setlist : c'est le SEUL geste qui change ce que fait le pied."""
    from . import setlists as sl
    r = sl.set_active(sid)
    if r.get("ok"):
        try:
            from . import rigstatus
            rigstatus.push_soon()                        # « on the foot » se lit dans le battement (setlist.active)
        except Exception as _e:
            _swallowed(_e)
    return r


@router.post("/api/setlists/{sid}/duplicate")
def setlists_duplicate(sid: str, body: dict = None):
    from . import setlists as sl
    r = sl.duplicate(sid, (body or {}).get("name"))
    return r or JSONResponse({"error": "not found"}, status_code=404)


@router.post("/api/setlists/{sid}/rename")
def setlists_rename(sid: str, body: dict):
    from . import setlists as sl
    r = sl.rename(sid, (body or {}).get("name"))
    if r:
        _foot_lists_changed()
    return r or JSONResponse({"error": "empty name or setlist not found"}, status_code=400)


@router.delete("/api/setlists/{sid}")
def setlists_delete(sid: str):
    from . import setlists as sl
    r = sl.remove(sid)
    if r.get("ok"):
        _foot_lists_changed()
    return r if r.get("ok") else JSONResponse(r, status_code=400)


def _foot_lists_changed():
    """Une liste créée, renommée ou supprimée : la table des modes republie `foot_lists` (patch-as-preset §9 bis-9)."""
    with contextlib.suppress(Exception):
        from . import rigstatus
        rigstatus.push_soon(with_modes=True)


@router.post("/api/setlists/{sid}/snapshot")
def setlists_snapshot(sid: str, body: dict = None):
    """Fige le CONTENU des presets — le seul objet qui permette de revenir en arrière sur les SONS."""
    from . import setlists as sl
    r = sl.snapshot(sid, (body or {}).get("name"))
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.post("/api/snapshots/{snid}/restore")
def snapshots_restore(snid: str, body: dict = None):
    """Remet les sons figés puis crée une setlist dans l'ordre. Un son de même id MODIFIÉ depuis l'instantané est un
    conflit : refusé (400 + conflicts) tant que l'écran n'a pas renvoyé `overwrite: true` après l'avoir montré."""
    from . import setlists as sl
    b = body or {}
    r = sl.restore(snid, b.get("name"), overwrite=bool(b.get("overwrite")))
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.post("/api/setlists/{sid}/presets")
def setlists_set_presets(sid: str, body: dict):
    """Remplace la LISTE ORDONNÉE d'une setlist (l'index = le numéro de bank).
    Un preset absent du disque est ACCEPTÉ : c'est un état normal (setlist reçue de golem.fm,
    preset pas encore synchronisé) — list_all() le signalera comme manquant."""
    from . import setlists as sl
    presets = body.get("presets")
    if not isinstance(presets, list):
        return JSONResponse({"error": "presets (list) required"}, status_code=400)
    cur = sl.load(sid)
    if not cur:
        return JSONResponse({"error": "not found"}, status_code=404)
    over = sl.over_cap(presets)          # une setlist = un concert : ça tient sur le pédalier
    if over:
        return JSONResponse({"error": over}, status_code=409)
    try:
        sl.set_presets(cur, [str(p) for p in presets])   # les lignes suivent leurs presets (titres, tempos gardés)
    except ValueError as e:                              # un morceau dans une bank de sons, ou l'inverse (§11)
        return JSONResponse({"error": str(e)}, status_code=400)
    out = sl.save(cur)
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)                  # le rack a écrit : golem.fm converge (§9.5)
    return out


@router.post("/api/setlists/{sid}/line")
def setlists_update_line(sid: str, body: dict):
    """Édite UNE ligne (docs/setlists.md §9) : {id, title?, bpm?, preset?, song_slug?}. `bpm: null`
    retire le tempo de ligne. Rev de ligne +1, push miroir.

    `scope` (§9.12, sens retour) : « song » = la retouche va à la CHANSON (toutes ses setlists
    suivent) · « line » = ce soir seulement. Absent, le DÉFAUT SE LIT DANS LA CARTE DU MODE
    (`ui.locked` -> line). C'est une consigne d'écriture : elle n'entre jamais dans la ligne."""
    from . import setlists as sl
    lid = (body or {}).get("id")
    fields = {k: body.get(k) for k in ("title", "bpm", "preset", "song_slug", "backing", "arrangement", "blocks",
                                       "tuning", "capo", "note") if k in (body or {})}
    scope = (body or {}).get("scope")
    if scope not in sl.SCOPES:
        scope = sl.default_scope()
    # sans id : une ligne NEUVE à la fin (« + Add a song », §9.9) — rend la setlist + `line_id`
    out = sl.update_line(sid, lid, scope=scope, **fields) if lid else sl.add_line(sid, **fields)
    if isinstance(out, dict) and out.get("error"):
        return JSONResponse(out, status_code=409)
    if out is None:
        return JSONResponse({"error": "setlist or line not found"}, status_code=404)
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)
    return {**out, "scope": scope} if isinstance(out, dict) else out       # l'écran lit la portée appliquée


# ── LE RÉPERTOIRE (docs/songs.md) ──────────────────────────────────────────────────────────
@router.get("/api/songs")
def api_songs():
    """Le répertoire du groupe + ce que chaque chanson réclame encore.

    `ready` est calculé ICI et pas à l'écran : « stage-ready » veut dire la même chose sur le rack,
    sur le téléphone et chez golem.fm, et trois calculs du même mot divergent."""
    from . import songs as SG
    from . import store as ST
    from . import golemfm
    paired = bool(golemfm._cfg()[1])                 # le jeton, lu en local — jamais un appel réseau par chanson
    rows = []
    try:
        lib = golemfm._lib_songs()
    except Exception:
        lib = []
    try:
        setlists = SG.SL.list_all()                  # une fois, pas une fois par chanson (songs.setlists_of)
    except Exception:
        setlists = []
    for d in SG.list_all():
        # la pochette, la photo de l'artiste et les instruments de la tab, comme les cartes de Library ▸ Tracks
        # (servis par /api/backing/asset/<id>/cover|photo) — le constat seul, rien n'est copié ici
        try:
            art = golemfm.local_art(d["id"], {"title": d.get("title"), "artist": d.get("artist")}, lib)
        except Exception:
            art = {}
        sh = d.get("sheet") or {}
        pid = sh.get("preset")
        parts = len((((sh.get("arrangement") or {}).get("params") or {}).get("sections")) or [])
        rows.append({**d,
                     "parts": parts,
                     "setlists": SG.setlists_of(d["id"], setlists),
                     # le preset est-il SUR CE RACK ? une setlist peut arriver avant ses presets
                     "preset_here": bool(pid and ST.load_preset(pid)),
                     "ready": bool(pid and ST.load_preset(pid) and parts),
                     # la MONTÉE vers golem.fm (§9.8) : synced / pending / rejected (+why) / rack_only
                     "sync": SG.sync_of(d, paired),
                     # ce que porte son .golem (lot 5) : complete / partial / card, lu dans l'archive
                     "file": SG.files_summary(d["id"], detail=False),
                     "has_cover": bool(art.get("cover")), "has_photo": bool(art.get("photo")),
                     "tab_parts": art.get("parts") or []})
    return {"songs": rows, **_song_spaces()}


@router.get("/api/songs/{sid}/files")
def api_song_files(sid: str):
    """« What this song carries » (lot 5) : chaque élément du .golem, présent / attendu absent / sans objet."""
    from . import songs as SG
    if not SG.load(sid):
        return JSONResponse({"error": "unknown song"}, status_code=404)
    return SG.files_summary(sid)


@router.get("/api/songs/{sid}/recording")
async def api_song_recording(sid: str):
    """« Get this recording » (song-sharing.md §2.6, lot 7) : l'enregistrement identifié par golem.fm et des liens
    vers des marchands sans DRM. Hors ligne : la dernière réponse, sinon MusicBrainz d'après le manifeste."""
    from . import recording
    r = await asyncio.to_thread(recording.of_song, sid)
    if r is None:
        return JSONResponse({"error": "unknown song"}, status_code=404)
    return r


@router.post("/api/golem/drop")
async def api_golem_drop(request: Request, name: str = "", replace: str = ""):
    """Déposer un .golem (lot 5) — le corps BRUT de la requête, écrit EN FLUX sur le disque (un .golem pèse
    jusqu'à des centaines de Mo). Le golem ne reçoit QUE des .golem (2026-10-08) : un MP3 est refusé
    avec le chemin vers golem.fm. `replace` = l'id d'une chanson dont un fichier du MÊME enregistrement
    remplace les médias (« Replace with a file… »). Même installation que le dossier surveillé ; l'issue
    rejoint ses derniers événements (GET /api/inbox)."""
    import uuid as _uuid
    from . import songs as SG, inbox as IB
    fname = os.path.basename(str(name or "file"))[:120]
    if not fname.lower().endswith(".golem"):
        ev = {"file": fname, "ok": False, "why": "not a .golem — make it on golem.fm", "golemfm": "https://golem.fm/songs?add=1"}
        IB._note(ev)
        return JSONResponse(ev, status_code=400)
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    tmp = os.path.join(C.SONGS_DIR, ".drop-%s.golem" % _uuid.uuid4().hex[:8])
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
        try:
            r = await asyncio.to_thread(SG.install_golem, tmp, replace or None)
            ev = {"file": fname, "ok": True, **r, **({"replaced": True} if replace else {})}
        except SG.InstallError as e:
            ev = {"file": fname, "ok": False, "why": str(e)}
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    IB._note(ev)
    if ev["ok"]:
        from . import inventory
        inventory.request_publish()                  # la carte de ce fichier monte sur golem.fm (§2.7)
    return ev if ev["ok"] else JSONResponse(ev, status_code=400)


@router.get("/api/golemfm/quotas")
async def api_golemfm_quotas():
    """Les places sur golem.fm, par section (song-sharing.md §2.7) — montrées AVANT d'y stocker un fichier."""
    from . import inventory
    q = await asyncio.to_thread(inventory.quotas)
    return {"online": q is not None, **(q or {})}


@router.post("/api/songs/{sid}/store")
async def api_song_store(sid: str, body: dict = None):
    """« Store on golem.fm » (song-sharing.md §2.7) : un GESTE, jamais automatique. body = {mode: full | light}
    (light = le texte seul : tab, paroles, grille, carte des mesures), `declared` : la déclaration d'origine licite cochée
    pour CE dépôt — golem.fm l'exige pour une `track` (separation-batch.md §7). Rend la réponse de golem.fm."""
    from . import inventory
    mode = (body or {}).get("mode") or "full"
    try:
        res = await asyncio.to_thread(inventory.upload, sid, mode, None, bool((body or {}).get("declared")))
    except inventory.UploadError as e:
        return JSONResponse({"ok": False, "why": str(e)}, status_code=400 if not e.status else (409 if e.status == 409 else 400))
    return {"ok": True, **res}


# ── LES DOSSIERS DE CHANSONS (docs/song-folders.md) ─────────────────────────────────────────
@router.get("/api/song-folders")
def api_song_folders():
    """System ▸ Song folders : chaque dossier, son état, ses comptes ; et le dossier surveillé (qui COPIE)."""
    from . import song_folders as SF, inbox as IB
    return {**SF.overview(), "drop_folder": IB.inbox_dir()}


@router.post("/api/song-folders")
def api_song_folders_add(body: dict):
    """Ajoute un dossier `{path}` — ou PLUSIEURS d'un coup `{paths: [...]}` (page Storage, 2026-10-09). Chacun est
    refusé s'il est illisible, introuvable, trop large ou déjà couvert (la raison s'affiche), sans bloquer les autres."""
    from . import song_folders as SF
    b = body or {}
    paths = b.get("paths") if isinstance(b.get("paths"), list) else [b.get("path")]
    done, refused = [], []
    for p in paths:
        try:
            done.append(SF.add(p, b.get("show_on_golemfm", True)))
        except SF.FolderError as e:
            refused.append({"path": p, "why": str(e)})
    if not done:
        return JSONResponse({"ok": False, "why": refused[0]["why"] if refused else "pick a folder", "refused": refused},
                            status_code=400)
    return {"ok": True, "path": done[0], "added": done, "refused": refused}


@router.get("/api/storage")
async def api_storage():
    """La page Storage : le disque, la musique par catégorie (+ l'âge de sa dernière sauvegarde, rack ou vault), les
    sons installés, les caches. Le vault est lu chez golem.fm ; injoignable, les âges viennent du rack seul."""
    from . import storage, golemfm, backup as B
    loop = asyncio.get_running_loop()
    o = await loop.run_in_executor(None, storage.overview)
    remote = await loop.run_in_executor(None, golemfm.list_remote)
    ages = await loop.run_in_executor(None, B.overview, (remote or {}).get("backups") or [])
    return {**o, "last": ages["last"], "last_full": ages["last_full"]}


@router.post("/api/storage/clear")
async def api_storage_clear(body: dict):
    """Vide un cache `{cache: peaks | work}` — reconstruit tout seul ; la chanson chargée n'est jamais touchée."""
    from . import storage
    try:
        return {"ok": True, **await asyncio.to_thread(storage.clear, (body or {}).get("cache"))}
    except storage.StorageError as e:
        return JSONResponse({"ok": False, "why": str(e)}, status_code=400)


@router.patch("/api/song-folders")
def api_song_folders_set(body: dict):
    from . import song_folders as SF
    b = body or {}
    # « kind » : ce que le dossier apporte (auto · song · vocals · standard — song-folders.md §2.9)
    if "kind" in b:
        if b["kind"] not in SF.KINDS:
            return JSONResponse({"ok": False, "why": "kind: auto | song | vocals | standard"}, status_code=400)
        if not SF.set_kind(b.get("path"), b["kind"]):
            return JSONResponse({"ok": False, "why": "unknown folder"}, status_code=404)
        if "show_on_golemfm" not in b:
            return {"ok": True}
    if "show_on_golemfm" not in b or not SF.set_show(b.get("path"), b["show_on_golemfm"]):
        return JSONResponse({"ok": False, "why": "unknown folder"}, status_code=404)
    return {"ok": True}


@router.delete("/api/song-folders")
def api_song_folders_remove(path: str):
    """Retire le dossier de la LISTE — jamais un fichier (song-folders.md §2.8)."""
    from . import song_folders as SF
    if not SF.remove(path):
        return JSONResponse({"ok": False, "why": "unknown folder"}, status_code=404)
    return {"ok": True}


@router.post("/api/song-folders/rescan")
def api_song_folders_rescan(body: dict = None):
    from . import song_folders as SF
    SF.request_scan((body or {}).get("path"))
    return {"ok": True}


@router.get("/api/song-folders/browse")
def api_song_folders_browse(path: str = ""):
    """L'explorateur servi par le rack : des sous-dossiers, aucun nom de fichier (song-folders.md §2.8)."""
    from . import song_folders as SF
    try:
        return SF.browse(path or None)
    except SF.FolderError as e:
        return JSONResponse({"ok": False, "why": str(e)}, status_code=400)


@router.get("/api/song-folders/songs")
def api_song_folders_songs(q: str = "", category: str = "", offset: int = 0, limit: int = 100):
    """Les chansons des dossiers, une par id, déjà-sur-le-golem exclues ; cherchées CÔTÉ RACK (des milliers)."""
    from . import song_folders as SF
    return SF.entries(q=q.strip() or None, category=category or None, offset=max(0, offset),
                      limit=max(1, min(int(limit), 500)))


@router.post("/api/song-folders/adopt")
async def api_song_folders_adopt(body: dict):
    """« Use on this golem » : la copie, vérifiée en entier. Le fichier du dossier n'est pas touché."""
    from . import song_folders as SF
    try:
        r = await asyncio.to_thread(SF.adopt, (body or {}).get("path"))
    except SF.AdoptError as e:
        return JSONResponse({"ok": False, "why": str(e)}, status_code=400)
    return {"ok": True, **r}


def _song_spaces():
    """Les ESPACES où une chanson peut vivre (docs/songs.md §9.2) : ceux que le rack connaît par son
    roster — l'espace personnel et les groupes. Le défaut d'une création est l'espace PERSONNEL
    (« elle va dans les chansons personnelles de l'user »). Le rack ne vérifie pas
    l'appartenance : c'est golem.fm qui le fera, au jeton, quand la chanson montera."""
    from . import roster
    r = roster.read() or {}
    spaces = [{"id": b.get("id"), "name": b.get("name") or b.get("id"), "kind": b.get("kind") or "band"}
              for b in (r.get("bands") or []) if isinstance(b, dict) and b.get("id")]
    personal = next((b["id"] for b in spaces if b["kind"] == "personal"), None)
    return {"spaces": spaces, "default_space": personal or ((r.get("band") or {}).get("id"))}


@router.post("/api/songs")
async def api_song_create(body: dict):
    """＋ New song (docs/songs.md §9.2) : une chanson NÉE SUR LE RACK, `rs:<uuid>`, pour toujours.
    body = {title, kind: cover|original, band?, preset?, bpm?, artist?}. La nature est OBLIGATOIRE
    (sans défaut) ; l'espace, s'il est donné, doit être un espace connu du roster."""
    from . import songs as SG
    b = body or {}
    band = b.get("band") or _song_spaces()["default_space"]
    if band and band not in {x["id"] for x in _song_spaces()["spaces"]}:
        return JSONResponse({"error": "unknown space — pick one of this rack's spaces"}, status_code=400)
    try:
        d = SG.create(b.get("title"), b.get("kind"), band=band, preset=b.get("preset") or None,
                      bpm=b.get("bpm"), artist=b.get("artist"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _push_songs_soon()
    return {"ok": True, "song": d}


def _push_songs_soon():
    """Une chanson a changé ici : elle monte vers golem.fm après un court calme (§9.8, lot 4)."""
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_songs()


@router.get("/api/songs/source")
def api_songs_source():
    """CE QU'ON PEUT TIRER, et ce qui manque pour pouvoir le tirer (docs/songs.md §7).

    ⚠ Au 2026-09-20, aucune route de golem.fm ne liste le répertoire d'un groupe pour un appareil
    apparié. L'écran d'import doit le DIRE — pas échouer sans explication, pas afficher une liste
    vide qu'on lira comme « le groupe n'a pas de chansons ». Cette route existe pour porter cette
    phrase, et elle deviendra le vrai appel le jour où leur moitié existe."""
    from . import golemfm
    st = golemfm.status()
    if not st.get("paired"):
        return {"available": False, "why": "not_paired",
                "says": "This rack is not paired with golem.fm yet — pair it in Settings ▸ Connect ▸ golem.fm.",
                "songs": []}
    # la route cible : GET /api/ext/golem/songs?band=<id>. Tant qu'elle n'existe pas, on ne
    # fabrique pas de liste : une liste vide se lirait « votre groupe n'a aucune chanson ».
    return {"available": False, "why": "not_on_golem_fm",
            "says": "golem.fm cannot list a band's repertoire yet. The rack is ready to receive it "
                    "(job « song-push »), and songs already arrive with your setlists.",
            "songs": []}


@router.get("/api/song/{sid:path}")
def api_song(sid: str):
    from . import songs as SG
    d = SG.load(sid)
    if not d:
        return JSONResponse({"error": "unknown song"}, status_code=404)
    from . import golemfm
    return {"song": d, "setlists": SG.setlists_of(sid), "sync": SG.sync_of(d, bool(golemfm._cfg()[1]))}


@router.post("/api/song/{sid:path}")
async def api_song_update(sid: str, body: dict):
    """Édite la fiche d'une chanson. TOUT ce qui arrive ici entre dans la CHANSON — il n'y a pas
    de portée à choisir dans Songs, on y est (docs/songs.md §2)."""
    from . import songs as SG
    adopted = bool(SG.in_folder(sid))                 # lue dans un dossier : la fiche s'écrit dans SA COPIE (song-folders.md §2.3)
    try:
        d = SG.update(sid, **(body or {}))
    except SG.InstallError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if d and adopted:
        from . import inventory
        inventory.request_publish()
        return {"ok": True, "song": d, "adopted": True,
                "says": "Added to this golem — the folder copy is untouched"}
    if not d:
        return JSONResponse({"error": "unknown song"}, status_code=404)
    _push_songs_soon()
    return {"ok": True, "song": d}


@router.post("/api/song-transfer/{sid:path}")
async def api_song_transfer(sid: str, body: dict):
    """« Give to <groupe> » (§9.6) : la chanson passe d'un espace PERSONNEL à un GROUPE. Même id,
    pas de copie. Seulement perso -> groupe (les mots du mainteneur) ; golem.fm vérifiera l'appartenance."""
    from . import songs as SG
    to = (body or {}).get("band")
    sp = {x["id"]: x for x in _song_spaces()["spaces"]}
    d = SG.load(sid)
    if not d:
        return JSONResponse({"error": "unknown song"}, status_code=404)
    if (sp.get(to) or {}).get("kind") != "band":
        return JSONResponse({"error": "a song is given to a band"}, status_code=400)
    if d.get("band") and (sp.get(d["band"]) or {}).get("kind") not in (None, "personal"):
        return JSONResponse({"error": "this song already belongs to a band"}, status_code=409)
    try:
        out = SG.transfer(sid, to)
    except SG.InstallError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if out:
        _push_songs_soon()
    return {"ok": bool(out), "song": out or d}


@router.delete("/api/song/{sid:path}")
def api_song_delete(sid: str):
    """Retire la chanson DU RACK — elle reste au répertoire du groupe chez golem.fm, SAUF si elle est
    née ici et n'est jamais montée : alors elle disparaît. Refusé tant qu'une setlist la joue — sa
    ligne jouerait une bank vide (§9.7)."""
    from . import songs as SG
    used = SG.setlists_of(sid)
    if used:
        return JSONResponse({"error": "remove it from " + ", ".join(x.get("name") or x["id"] for x in used) + " first",
                             "setlists": used}, status_code=409)
    return {"ok": SG.delete(sid)}


@router.get("/api/setlists/scope")
def setlists_scope():
    """La portée par DÉFAUT d'une écriture de ligne ici et maintenant (§9.12) : le tiroir l'affiche
    (« saves into the song » / « tonight only ») au lieu de poser une question à qui joue."""
    from . import setlists as sl
    from .state import state as _st
    m = _st.mode or {}
    return {"scope": sl.default_scope(m), "mode": m.get("id"), "mode_name": m.get("name"),
            "locked": bool((m.get("ui") or {}).get("locked"))}


@router.post("/api/setlists/{sid}/songs")
def setlists_add_songs(sid: str, body: dict):
    """« ＋ Add a song » = un choix dans le RÉPERTOIRE (docs/songs.md §9.6). body = {ids: [...]}.
    La setlist ne fabrique plus de chanson. Push miroir comme toute écriture de setlist."""
    from . import setlists as sl
    try:
        out = sl.add_songs(sid, (body or {}).get("ids") or [])
    except ValueError as e:                          # une bank de sons ne prend pas de morceaux
        return JSONResponse({"error": str(e)}, status_code=400)
    if out is None:
        return JSONResponse({"error": "setlist not found"}, status_code=404)
    if out.get("added"):
        with contextlib.suppress(Exception):
            from . import golemfm
            golemfm.push_setlist(sid)
    v = sl.view(out)
    if out.get("adopted"):                           # lues dans un dossier : copiées dans le golem (song-folders.md §2.3)
        v = {**v, "adopted": out["adopted"], "says": "Added to this golem — the folder copy is untouched"}
    return v


@router.post("/api/setlists/{sid}/line/{line_id}/to-song")
def setlists_line_to_song(sid: str, line_id: str, body: dict):
    """« ◆ Make it a song » (§9.6) : une ligne LIBRE devient une chanson du répertoire. body =
    {kind: cover|original, band?}. La nature se demande ici : elle est obligatoire."""
    from . import setlists as sl
    b = body or {}
    band = b.get("band") or _song_spaces()["default_space"]
    try:
        out = sl.line_to_song(sid, line_id, b.get("kind"), band=band)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if out is None:
        return JSONResponse({"error": "setlist or line not found"}, status_code=404)
    setl, song = out
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)
    return {**sl.view(setl), "song": song}


@router.post("/api/setlists/{sid}/place-song")
def setlists_place_song(sid: str, body: dict):
    """Range une CHANSON dans une bank {song, slot (0-based)} — la chanson, pas son seul preset (sélecteur de bank)."""
    from . import setlists as sl
    try:
        out = sl.place_song(sid, str((body or {}).get("song") or ""), int((body or {}).get("slot")))
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": str(e) or "song/slot required"}, status_code=400)
    if out is None:
        return JSONResponse({"error": "setlist not found"}, status_code=404)
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)
    return sl.view(out)


@router.post("/api/setlists/{sid}/swap")
def setlists_swap(sid: str, body: dict):
    """Échange deux banks {from, to} (0-based) — glisser-déposer du sélecteur de bank. Push miroir comme un ordre."""
    from . import setlists as sl
    try:
        out = sl.swap_lines(sid, int((body or {}).get("from")), int((body or {}).get("to")), cap=sl.MAX_SLOTS)
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": str(e) or "from/to required"}, status_code=400)
    if out is None:
        return JSONResponse({"error": "setlist not found"}, status_code=404)
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)
    return out


@router.delete("/api/setlists/{sid}/line/{line_id}")
def setlists_remove_line(sid: str, line_id: str, keep_slot: int = 0):
    """Retire une ligne (le morceau quitte la setlist, le preset reste). Rev de liste +1, push miroir
    `complete` : la ligne disparaît aussi chez golem.fm. `?keep_slot=1` : la ligne part mais son rang reste,
    vide — vider une bank sans décaler les suivantes (sélecteur de bank, 2026-10-08)."""
    from . import setlists as sl
    out = sl.remove_line(sid, line_id, keep_slot=bool(keep_slot))
    if out is None:
        return JSONResponse({"error": "setlist or line not found"}, status_code=404)
    with contextlib.suppress(Exception):
        from . import golemfm
        golemfm.push_setlist(sid)
    return out


@router.post("/api/setlists/{sid}/mirror")
def setlists_mirror(sid: str):
    """« Push now » du MIROIR golem.fm (docs/setlists.md §9.5) : la setlist telle qu'elle est sur
    disque, `complete: true`, sans débounce. Rien d'autre que ce que fait déjà chaque sauvegarde —
    pour la tablette et les tests d'aller-retour. ≠ `/push` ci-dessous, qui pousse la GRAPPE de
    sauvegarde (setlist + presets) par le canal backups."""
    from . import golemfm, setlists as sl
    if not sl.load(sid):
        return JSONResponse({"error": f"unknown setlist: {sid}"}, status_code=404)
    golemfm.push_setlist(sid, delay=0.0)
    return {"ok": True, "setlist": sid, "queued": True}


@router.post("/api/setlists/{sid}/push")
def setlists_push(sid: str):
    """Pousse la GRAPPE (setlist + ses presets) vers golem.fm par le canal `backups` existant.
    Renvoie AUSSI ce qui manquait sur le rack : une grappe ne doit pas arriver « verte » avec des
    presets absents (contrat docs/setlists.md §5)."""
    from . import backup as _backup, golemfm
    if not all(golemfm._cfg()):            # jamais appairé : ni zip écrit pour rien, ni « envoyé » (audit 31/10)
        return JSONResponse({"error": "not paired with golem.fm"}, status_code=409)
    try:
        r = _backup.build_setlist(sid)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    p = golemfm.push_backup(r["file"])
    return {**r, "push": p}


# ── packs d'animations de tuiles (docs/anim-packs.md) ────────────────────────
@router.get("/api/anim-packs")
def anim_packs():
    """`default` (socle livré, verrouillé) + les packs installés par golem.fm."""
    from . import anim_packs as AP
    return {"packs": AP.list_packs()}


@router.get("/api/anim-pack/{pid}/css")
def anim_pack_css(pid: str):
    """Le CSS d'un pack, re-validé au service. 404 = pack absent ou refusé (le log dit
    pourquoi) — l'app dégrade la tuile sans animation, jamais silencieusement."""
    from fastapi.responses import Response
    from . import anim_packs as AP
    css = AP.pack_css(pid)
    if css is None:
        return JSONResponse({"error": "unknown or rejected pack"}, status_code=404)
    return Response(css, media_type="text/css")


@router.post("/api/anim-packs/install")
async def anim_pack_install(body: dict):
    """Point d'entrée du job golem.fm : {pack:{…}, css:"…"}. Valide tout avant d'écrire."""
    from . import anim_packs as AP
    r = AP.install((body or {}).get("pack") or {}, (body or {}).get("css") or "")
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.delete("/api/anim-pack/{pid}")
def anim_pack_remove(pid: str):
    from . import anim_packs as AP
    r = AP.remove(pid)
    return r if r.get("ok") else JSONResponse(r, status_code=400)
