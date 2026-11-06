# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes des modes machine (docs/modes.md) — GET /api/modes, POST /api/mode.

Un switch de mode ré-applique le veto de services sur le preset courant
(effectif = preset ∧ mode) sans re-recall : la matérialisation Reaper ne
change pas en v1, seuls les services et la surface UI suivent.
"""
import contextlib

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import modes as modes_mod
from . import roster
from .golog import get
from .state import state

log = get("modes")
from .store import load_preset

router = APIRouter()


def clear_practice():
    """Un CHANGEMENT de mode lève la boucle et le cue de répète (docs/live-pages.md §6.3 bis) — pas une simple édition
    du mode courant (personnaliser ses widgets ne doit pas couper une boucle en cours)."""
    with contextlib.suppress(Exception):
        from . import app as _app
        _app._arr_ctl.clear_practice()


def _re_veto():
    """Recalcule les enables de services du preset courant sous le mode courant.
    Mêmes formules que le chemin de recall (app.py) — preset ∧ mode."""
    from . import rig as _rig  # import tardif (rig charge des ressources)
    cur = load_preset(state.preset_id) if state.preset_id else None
    from . import recall as _recall                          # la backing JOUÉE est celle de la chanson (song-backing.md)
    cur_eff = _recall.effective_preset(cur) if cur else None
    state.looper = {**state.looper,
                    "enabled": bool(cur) and _rig.looper_enabled(cur) and modes_mod.allows("looper", state.mode)}
    songs = ((cur_eff or {}).get("backing") or {}).get("songs") or []
    state.backing = {**state.backing,
                     "enabled": bool(songs) and modes_mod.allows("backing", state.mode)}
    # SAMPLE : même loi (2026-07-31). Basculer de mode coupe/rend les lanceurs SANS recall —
    # sinon le veto ne prendrait effet qu'au prochain morceau, ce qui n'est pas ce qu'on promet.
    from . import sample as _sample_mod
    state.sample_switches = (_sample_mod.switches(cur)
                             if cur and modes_mod.allows("sample", state.mode) else {})
    # STANDARDS et BOÎTE À RYTHMES (2026-09-08) : même loi que sample — le veto prend effet
    # à la bascule, pas au prochain morceau ; ce qui tournait s'arrête.
    from . import drums as _drums_mod, standards as _standards_mod
    dm_ok, std_ok = modes_mod.allows("drummachine", state.mode), modes_mod.allows("standard", state.mode)
    state.drum_switches = _drums_mod.switches(cur) if cur and dm_ok else {}
    state.standard_switches = _standards_mod.switches(cur) if cur and std_ok else {}
    state.standard_block = _standards_mod.block_of(cur) if cur and std_ok else None
    # 2026-10-24 : `also_playing=True` levait « 'bool' object is not iterable » à chaque édition de mode — la batterie
    # en cours ne s'arrêtait jamais, et l'arrêt de la grille qui suivait dans le même try non plus. Les blocs EN COURS
    # viennent du rapport de REAPER (.drums.json), comme /api/drums/stop-all ; chacun son try.
    from . import app as _app, config as C
    from .store import _read_json
    if not dm_ok:
        try:
            rep = (_read_json(C.DRUMS_FILE, {}) or {}).get("blocks") or {}
            playing = [b for b, s in rep.items() if isinstance(s, dict) and s.get("playing")]
            _app._drums_ctl.stop_orphans(set(), also_playing=playing)
        except Exception as e:
            log.warning(f"veto boîte à rythmes non appliqué à chaud : {e}")
    if not std_ok:
        try:
            _app._standard_cmd("stop", None)
        except Exception as e:
            log.warning(f"veto standard non appliqué à chaud : {e}")
    state.touch()
    # politique du CLICK : « off » coupe un métronome qui tournait, « preset » resynchronise sur
    # le bloc du preset courant (« manual » ne touche à rien : c'est l'utilisateur qui décide).
    try:
        from . import app as _app
        cm = modes_mod.click_mode(state.mode)
        if cm == "off":
            if _app._click_on():
                _app._click_set(False)
        elif cm == "preset":
            from . import recall as _recall
            _app._click_follow_preset(_recall.effective_preset(cur) if cur else cur)   # la chanson, comme au rappel
    except Exception as e:
        log.warning(f"politique click non appliquée : {e}")
    # veto d'ENTRÉE (lane coupée par le mode) : la topologie change -> re-matérialiser le rig.
    # Fire-and-forget vers le worker du moteur : le compile ne bloque pas la route, et une
    # erreur est loggée par le moteur lui-même (submit -> _log_future). Jamais fatal.
    try:
        from . import recall
        recall.submit(recall.emit_sandbox, state.preset_id, state.scene_id)
    except Exception as e:
        log.warning(f"re-emit après veto échoué : {e}")


@router.get("/api/modes")
def get_modes():
    # `max` : le plafond d'emplacements, publié pour que l'UI dessine les cases libres sans
    # recopier la constante (une seule source de vérité, côté machine).
    return {"modes": modes_mod.list_modes(), "current": (state.mode or {}).get("id"),
            "max": modes_mod.MAX_MODES}


@router.post("/api/mode")
async def set_mode(body: dict):
    """Bascule de mode — et, si le mode le déclare, d'ESPACE de destination des prises.

    ⚠ C'est le SEUL endroit où un mode change l'espace : jamais au boot, jamais à la synchro,
    jamais depuis un poll. « Jamais d'auto-bascule » vise ces trois-là ; un changement de mode
    est un tap, donc une intention (message-golem-modes-espaces.md §1.1).
    """
    mid = (body or {}).get("id") or ""
    target = next((x for x in modes_mod.list_modes() if x["id"] == mid), None)
    want = modes_mod.band_of(target) if target else None
    cur_band = ((roster.read().get("band") or {}).get("id"))
    if want and want != cur_band:
        # 2 TAPS quand une prise tourne ou qu'on est dans un mode verrouillé : la prise EN
        # COURS ne bouge pas (son tag est gelé à son départ), c'est la SUIVANTE qui changera
        # d'espace — mais ça mérite d'être dit avant, pas découvert après.
        #
        # ⚠ SAUF QUAND ON S'ÉCHAPPE. Quitter un mode VERROUILLÉ pour un mode qui ne l'est pas,
        # c'est l'appui long sur le logo — la SEULE porte de sortie du kiosk, et elle envoie
        # `{id: "studio"}` sans `confirm`. Sans cette exception, un mode Home qui déclare un
        # espace suffisait à transformer un 409 en enfermement : Gig verrouille l'UI, la porte
        # répondait « confirm required », et l'utilisateur restait dedans. Mesuré le
        # 2026-09-07, sur le scénario exact. Le dépôt est catégorique là-dessus : on ne livre
        # jamais un mode sans sa sortie testée — c'est déjà arrivé, il a fallu Alt+F4.
        locked_now = bool(((state.mode or {}).get("ui") or {}).get("locked"))
        locked_next = bool(((target or {}).get("ui") or {}).get("locked"))
        escaping = locked_now and not locked_next
        risky = (bool((getattr(state, "perf", None) or {}).get("recording")) or locked_now) \
            and not escaping
        if risky and not (body or {}).get("confirm"):
            return JSONResponse(
                {"error": "confirm required", "needs_confirm": True, "band": want,
                 "message": "The take in progress keeps its space — the next one changes."},
                status_code=409)
    _prev_kind = modes_mod.take_kind(state.mode) if state.mode else None
    try:
        m = modes_mod.set_current(mid)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    state.mode = m
    clear_practice()
    # lot 8 : le passage en Gig/Show est « le concert commence » (docs/diagnostics.md §3.1)
    with contextlib.suppress(Exception):
        from . import diag as _diag
        _diag.event("mode", **{"from": _prev_kind, "to": modes_mod.take_kind(m),
                               "locked": bool((m.get("ui") or {}).get("locked"))})
    if want and want != cur_band:
        ok, res = roster.set_current(want)
        if ok:
            log.info(f"mode « {m.get('name')} » → espace {res.get('name')} ({want})")
        else:
            # espace inconnu du cache : le MODE bascule quand même, l'espace ne bouge pas.
            # Refuser la bascule entière punirait le musicien d'un roster pas encore
            # synchronisé — et le mode, lui, est parfaitement jouable.
            log.warning(f"mode « {m.get('name')} » déclare un espace inconnu ({want}) — "
                        f"espace courant conservé")
    _re_veto()
    # setlists poussées PENDANT un mode verrouillé : appliquées maintenant (docs/setlists.md §9.6)
    with contextlib.suppress(Exception):
        from . import setlists as _sl
        done = _sl.apply_pending()
        if done:
            log.info(f"setlist(s) en attente appliquée(s) à la bascule : {done}")
    # LA LISTE AU PIED DU MODE (docs/patches.md §7) : un défaut, jamais un verrou — dit si elle a disparu
    foot = {"applied": False, "why": None}
    with contextlib.suppress(Exception):
        applied, why = modes_mod.apply_foot_list(m)
        fl = modes_mod.resolve_foot_list(m.get("foot_list")) if m.get("foot_list") else None   # @instrument -> l'id
        foot = {"applied": applied, "why": why, "list": fl}
        if applied:
            log.info(f"mode « {m.get('name')} » : liste au pied → {fl}")
        elif why:
            log.warning(why)
        if applied or why:                          # golem.fm le voit tout de suite (`foot` au battement)
            from . import rigstatus
            rigstatus.push_soon()
    # BOOST CPU : suit le mode (Gig/Show = on, sinon off) — en thread, sudo peut prendre 1 s
    with contextlib.suppress(Exception):
        from . import routes_system as _sys
        import asyncio as _aio
        _aio.get_running_loop().run_in_executor(None, _sys.apply_perf_for_mode, m, " (bascule)")
    # push WS immédiat : les cartes de mode (power ⏻) reflètent la bascule SANS recharger la page
    with contextlib.suppress(Exception):
        from . import app as _app
        await _app._broadcast()
    return {"ok": True, "mode": m, "foot": foot}


# ── édition (1+2 du plan config-modes) : chips togglables, duplicata, reset ──

def _refresh_if_current(mid):
    """Un mode édité/reseté qui est le mode COURANT doit se re-propager (state + veto)."""
    if (state.mode or {}).get("id") == mid:
        state.mode = modes_mod.current()
        _re_veto()


def _guard_locked_active(mid):
    """Le mode actif verrouillé (Gig sur scène) ne s'édite pas depuis lui-même :
    il faut d'abord en sortir (appui long logo). Protège le set."""
    cur = state.mode or {}
    if cur.get("id") == mid and (cur.get("ui") or {}).get("locked"):
        return JSONResponse({"error": "this mode is active and locked — exit it first"}, status_code=409)
    return None


@router.post("/api/mode/update")
async def update_mode(body: dict):
    mid = (body or {}).get("id") or ""
    m = next((x for x in modes_mod.list_modes() if x["id"] == mid), None)
    if m is None:
        return JSONResponse({"error": f"unknown mode: {mid}"}, status_code=400)
    guard = _guard_locked_active(mid)
    if guard:
        return guard
    # UN chemin pour la feuille et le job `mode-set` de golem.fm (modes.apply_update / commit — addendum
    # 2026-09-26 de docs/modes.md) : c'est là que `live_view` est enfin écrit.
    modes_mod.apply_update(m, body)
    saved = modes_mod.commit(m)
    # golem.fm apprend la table des modes AU MOMENT où elle change (jamais en cadence) :
    # push hors cadence, débouncé, avec la table (message-maestrium-prises-kind.md §3)
    with contextlib.suppress(Exception):
        from . import rigstatus
        rigstatus.push_soon(with_modes=True)
    _refresh_if_current(mid)
    return {"ok": True, "mode": saved}


@router.get("/api/recorder")
def recorder_cfg():
    """La config GLOBALE du magnétophone — la seule (décision 2026-09-08 : pas de config par
    mode). Le bloc Rec du Designer et le tiroir REC de Settings ▸ Mode éditent la même chose."""
    from . import store
    return store.load_recorder_cfg()


@router.get("/api/compo")
def compo_cfg():
    """La config GLOBALE du bloc Compo (docs/compo.md) + les cibles « Follow Golem » en mémoire et,
    pour le preset chargé, les lanes de chaque personne de la carte (ce que le tiroir affiche)."""
    from . import compo, store
    cfg = store.load_compo_cfg()
    cur = load_preset(state.preset_id) if state.preset_id else None
    imap = compo._imap()
    persons = sorted({e["person"] for e in (imap.get("inputs") or []) + (imap.get("usb") or []) if e.get("person")})
    return {**cfg, "targets": state.compo.get("targets") or {}, "foot_person_effective": compo.foot_person(cfg, imap),
            "lanes": {pid: compo.lanes_of_person(cur, pid, cfg, imap) for pid in persons}}


@router.post("/api/compo")
def compo_set(body: dict):
    """Écrit la config globale Compo (clés partielles : keep_s, transcribe, foot_person, persons)."""
    from . import store
    return store.save_compo_cfg(body or {})


@router.post("/api/compo/target")
def compo_target(body: dict):
    """SONDE (comme /api/foot/inject) : rejoue la commande uplink `compo-target` sans golem.fm —
    `{person, target:{id, mode, title, band}}` ou `{person, clear:true}`. En vrai, la cible arrive
    par follow_uplink (docs/compo.md §10) ; ici on vérifie /live et le Companion sans la page web."""
    from . import compo
    ok, why = compo.set_target((body or {}).get("person"), (body or {}).get("target"), clear=bool((body or {}).get("clear")))
    return {"ok": ok, "why": why, "targets": state.compo.get("targets") or {}}


@router.post("/api/compo/tap")
def compo_tap(body: dict = None):
    """Le switch Riff depuis l'ÉCRAN ou le Companion (docs/compo.md §11) — le MÊME chemin que le pied
    (app._compo_tap : prise Rec, décompte, garde disque). `person` = celle de l'appareil ; absent = le
    propriétaire du pédalier. Démarre une capture, ou arrête celle qui tourne."""
    from . import app as _app
    return _app._compo_tap(source=(body or {}).get("source") or "screen", person=(body or {}).get("person"))


@router.post("/api/compo/drop")
def compo_drop(body: dict = None):
    """Jette le dernier riff PENDANT ses 20 s (§11) : il ne monte jamais, il reste sur le disque."""
    from . import compo
    ok, why = compo.drop((body or {}).get("uid"))
    return {"ok": ok, "why": why} if ok else JSONResponse({"ok": False, "why": why}, status_code=409)


@router.post("/api/recorder")
def recorder_set(body: dict):
    """Écrit la config globale ({in1,in2,usb,mode,mix,transcribe}, clés partielles acceptées) et
    republie presets/.perfsrc.json — ce que golem_perfrec lit — sans attendre un rappel de preset."""
    import os
    from . import config as C
    from . import store
    cfg = store.save_recorder_cfg(body or {})
    with contextlib.suppress(Exception):
        cur = load_preset(state.preset_id) if state.preset_id else None
        store._write_json_atomic(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), store.rec_sources(cur), indent=None)
    with contextlib.suppress(Exception):                     # golem.fm affiche cette config avec la feuille des modes
        from . import rigstatus
        rigstatus.push_soon(with_modes=True)
    return cfg


@router.post("/api/mode/new")
async def new_mode(body: dict):
    """Crée un mode dans la surcouche locale, À PARTIR d'un mode existant.

    Remplace l'ancien /api/mode/duplicate (décision 2026-07-28) : même
    mécanique, mais l'utilisateur NOMME et CHOISIT son icône au lieu de récolter
    un « Gig copy ». `from` est obligatoire — un mode « vierge » n'existe pas :
    un service absent vaut AUTORISÉ, donc partir de rien = repartir de Home.
    """
    b = body or {}
    src_id = b.get("from") or ""
    src = next((x for x in modes_mod.list_modes() if x["id"] == src_id), None)
    if src is None:
        return JSONResponse({"error": f"unknown source mode: {src_id}"}, status_code=400)
    name = (b.get("name") or "").strip()[:80]
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    existing = modes_mod.list_modes()
    if len(existing) >= modes_mod.MAX_MODES:
        return JSONResponse(
            {"error": f"all {modes_mod.MAX_MODES} mode slots are taken — delete one first"},
            status_code=409)
    taken_ids = {x["id"] for x in existing}
    new = {k: v for k, v in src.items() if not k.startswith("_")}
    new["id"] = modes_mod.new_id(name, taken_ids)
    new["name"] = name
    if isinstance(b.get("icon"), str) and b["icon"].strip():
        new["icon"] = b["icon"].strip()[:24]
    if isinstance(b.get("desc"), str) and b["desc"].strip():
        new["desc"] = b["desc"].strip()[:160]
    new["order"] = max((x.get("order", 0) for x in existing), default=0) + 1
    saved = modes_mod.save_local(new)
    return {"ok": True, "mode": saved}


@router.post("/api/mode/reset")
async def reset_mode(body: dict):
    """Mode livré → reset usine (retire la surcouche). Duplicata → suppression
    (refusée s'il est le mode courant)."""
    mid = (body or {}).get("id") or ""
    m = next((x for x in modes_mod.list_modes() if x["id"] == mid), None)
    if m is None:
        return JSONResponse({"error": f"unknown mode: {mid}"}, status_code=400)
    guard = _guard_locked_active(mid)
    if guard:
        return guard
    if m["_custom"] and (state.mode or {}).get("id") == mid:
        return JSONResponse({"error": "cannot delete the active mode — switch first"}, status_code=409)
    modes_mod.delete_local(mid)
    _refresh_if_current(mid)
    return {"ok": True, "removed": m["_custom"]}
