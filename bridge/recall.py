# SPDX-License-Identifier: GPL-3.0-or-later
"""Le moteur de RECALL — extrait d'app.py (audit 2026-08-12, P2), sérialisé et hors boucle.

Ce module porte le chemin le plus critique du rack : preset/scène -> bake -> compile ->
commande Reaper. Trois raisons d'exister, toutes constatées :

1. **app.py était un god-file** (1650 l.) : le moteur y côtoyait le dispatch du pied, la glue
   Whammy/EXP et 20 routes. Le moteur vit ici ; la glue reste dans app.py et est INJECTÉE par
   init() — c'est elle qui connaît les contrôleurs (arrangement, backing, drums) et les
   pédales. Aucun import de app.py ici, jamais : c'est la condition pour rester testable.

2. **Le recall bloquait la boucle asyncio** : deepcopy + bake + compile_rig + écritures
   fichiers tournaient SUR la boucle — WebSocket, polls et API gelés à chaque recall.
   Le cœur tourne désormais dans un exécuteur à UN SEUL worker (_EXEC) : la boucle reste
   libre, et le FIFO du worker préserve l'ordre des gestes — une cue d'arrangement émet
   « la scène d'abord, les bascules ensuite » (contrat §3 bis), deux workers pourraient
   les inverser.

3. **La sérialisation des recalls concurrents était ACCIDENTELLE** (conséquence du point 2 :
   tout passait par la boucle, donc tout était séquentiel). Elle est maintenant explicite :
   _RECALL_LOCK. Un threading.RLock, PAS un asyncio.Lock — le moteur a des portes d'entrée
   HORS boucle (le worker _EXEC, le thread preview qui restaure le rig après une génération,
   le worker jobs golem.fm) qu'un verrou asyncio ne couvre pas. RLock et non Lock :
   do_recall appelle emit_sandbox, deux entrées publiques — un Lock simple s'auto-bloquerait.

Les planifications différées (+0,8 s : click, stop des batteries orphelines) passent par
_later(), qui rejoint la boucle principale depuis n'importe quel thread — l'ancien idiome
« call_later, sinon RuntimeError -> appel direct » supposait qu'on tournait sur la boucle,
ce qui n'est plus jamais le cas ici.
"""
import asyncio
import contextlib
import copy as _copy
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from . import foot_leds
from . import config as C
from . import modes as modes_mod
from . import scene_bake
from . import store
from .commands import write_command
from .golog import get
from .state import state
from .store import load_preset, _read_json, _write_json_atomic
from .golog import swallowed as _swallowed

log_boot = get("boot")
log_bank = get("bank")
log_sandbox = get("sandbox")
log_click = get("click")
log_recall = get("recall")

# ── contexte injecté par app.py (init) : la glue qui reste là-bas ────────────────────────────
_arr_ctl = None            # contrôleur d'arrangement (stop/load au changement de preset)
_backing_ctl = None        # contrôleur backing (on_recall)
_drums_ctl = None          # contrôleur drums (stop_orphans)
_bind_foot_services = None # enregistre les blocs pilotés par les fronts (app.py)
_whammy_dt_glue = None     # bloc whammy-dt -> MIDI matériel (app.py, autorité sur la pédale)
_set_exp_blk_from = None   # cible du rôle bloc des pédales EXP (app.py)
_set_exp_vol_from = None   # cible du rôle volume (app.py)
_exp_bake = None           # la position connue des pédales écrite dans la copie émise (app.py)
_click_follow_preset = None  # politique click « preset » (app.py)
_notify = None             # broadcast_threadsafe : pousser l'état aux WebSockets

_loop = None               # boucle asyncio principale (attach_loop, au startup)

# ── sérialisation ────────────────────────────────────────────────────────────────────────────
_RECALL_LOCK = threading.RLock()
_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="golem-recall")

# switch (6-10) du bloc backing-track du preset courant — posé au recall, lu par le dispatch
# du pied (app._on_stomp_edge / _do_stomp). Vivait en global dans app.py ; il suit le moteur.
backing_sw = None

SANDBOX_BUF = os.path.join(C.PRESETS_DIR, ".sandbox.json")
_LIVEMAP_STATE_PATH = os.path.join(C.PRESETS_DIR, ".livemap.json")


def init(arr_ctl, backing_ctl, drums_ctl, bind_foot_services, whammy_glue,
         set_exp_blk, set_exp_vol, click_follow, notify, exp_bake=None):
    """Branche la glue d'app.py. Appelé UNE fois, en fin de module app (les fonctions doivent
    exister). Le moteur ne démarre rien ici — attach_loop() vient au startup uvicorn."""
    global _arr_ctl, _backing_ctl, _drums_ctl, _bind_foot_services, _whammy_dt_glue
    global _set_exp_blk_from, _set_exp_vol_from, _click_follow_preset, _notify, _exp_bake
    _arr_ctl, _backing_ctl, _drums_ctl = arr_ctl, backing_ctl, drums_ctl
    _bind_foot_services = bind_foot_services
    _whammy_dt_glue = whammy_glue
    _set_exp_blk_from, _set_exp_vol_from = set_exp_blk, set_exp_vol
    _exp_bake = exp_bake
    _click_follow_preset = click_follow
    _notify = notify


def attach_loop(loop):
    """La boucle principale — pour _later() et les wrappers async."""
    global _loop
    _loop = loop


def _later(delay, fn, *a):
    """Planifie `fn` à +delay s SUR LA BOUCLE PRINCIPALE, depuis n'importe quel thread
    (loop.call_later n'est pas thread-safe : on la rejoint par call_soon_threadsafe).
    Sans boucle attachée (tests, appel avant startup) : appel direct — write_command
    absorbe désormais le slot unique par l'attente polie du protocole ACK (≤0,9 s)."""
    lp = _loop
    if lp is not None:
        lp.call_soon_threadsafe(lambda: lp.call_later(delay, fn, *a))
    else:
        fn(*a)


def _log_future(fut):
    """Une exception dans le worker mourrait en silence dans la Future : on la logge —
    l'équivalent de ce qu'asyncio faisait pour les callbacks du pied sur la boucle."""
    e = fut.exception()
    if e is not None:
        log_recall.error(f"recall en tâche de fond échoué : {e!r}")


def submit(fn, *a):
    """Soumet un travail au worker du recall (fire-and-forget, FIFO). C'est LA porte des
    appels qui n'attendent pas de retour : pied, cues d'arrangement, re-emit de mode."""
    _EXEC.submit(fn, *a).add_done_callback(_log_future)


def schedule(pid, scene):
    """Recall fire-and-forget (pied : changement de scène). Le moteur notifie à la fin."""
    submit(do_recall, pid, scene)


def schedule_slot(slot, source=None):
    """Recall de slot fire-and-forget (pied : PC de bank). Le moteur notifie à la fin."""
    submit(do_recall_slot, slot, source)


async def recall_async(pid, scene):
    """Recall depuis la boucle (routes API) : le cœur part dans l'exécuteur, la boucle
    reste libre. Retourne le résultat de do_recall."""
    return await asyncio.get_running_loop().run_in_executor(_EXEC, do_recall, pid, scene)


async def slot_async(slot, source=None):
    return await asyncio.get_running_loop().run_in_executor(_EXEC, do_recall_slot, slot, source)


async def emit_preset_async(preset, scene, action="rig_recall"):
    """emit_sandbox_preset hors boucle — le chemin du Designer (sandbox_apply), qui a besoin
    du retour (message d'erreur de compile, remonté à l'UI)."""
    return await asyncio.get_running_loop().run_in_executor(
        _EXEC, emit_sandbox_preset, preset, scene, action)


def invalidate_shape():
    """Reaper redémarre (restart volontaire, update moteur, crash) : le rig matérialisé n'est
    plus garanti -> la prochaine émission doit faire un REBUILD, jamais un scene_apply sur un
    projet fraîchement rechargé. Remplace les pokes directs de _LAST_EMIT depuis
    routes_system/reaper_update."""
    _LAST_EMIT.update(pid=None, shape=None)


# ── le rig vivant ────────────────────────────────────────────────────────────────────────────
def rig_is_live(pid):
    """Le rig matérialisé (dernier build de golem_rig) correspond-il à ce preset ? Lu dans la livemap
    (réécrite à chaque REBUILD, pas à chaque scene_apply -> reste valide entre scènes).
    INVARIANT ANTI-RESTART (bug AKAI muet 2026-07-23) : une livemap plus VIEILLE que le démarrage
    du process Reaper est périmée par construction (le build vivait dans l'ancien process — l'armement
    MIDI/état réel n'est plus garanti même si le projet recharge les pistes). Ceinture en plus du
    compteur reaper_gen, qui a été pris en défaut (scene_apply sur un rig jamais rebuilt)."""
    from . import monitors
    lm = _read_json(_LIVEMAP_STATE_PATH, {}) or {}
    if lm.get("preset") != pid:
        return False
    try:
        rpid = monitors.reaper_pid_recent()
        if rpid is None:
            return False
        reaper_started = monitors._process_started(rpid)
        return os.stat(_LIVEMAP_STATE_PATH).st_mtime > reaper_started
    except Exception:
        return True                                   # introuvable/portabilité : on retombe sur reaper_gen


def input_veto(preset=None):
    """Clés des lanes dont le RÔLE est coupé par le mode courant (docs/modes.md : veto d'entrée =
    preset ∧ mode). LOT 4 : PAR LANE, sur le rôle que la lane porte (v2) ou celui de son entrée
    patchée (legacy) — une 2e guitare n'est plus jugée sur le rôle de l'entrée 2, et « voice: false »
    coupe les lanes de voix, pas les autres. `keys-pads` tombe si keys ET pads sont coupés.
    Une lane vetoée n'est pas montée par to_paths_preset (comme IN/OUT NONE, mais décidé par le mode)."""
    veto = set()
    try:
        lanes = store.lanes_of(preset) if preset else []
    except Exception:
        lanes = []
    # LA MÊME SOURCE QUE lanes_of (audit 2026-10-10) : le fichier de la carte, pas la copie `state.inputmap` —
    # elle datait du démarrage et pouvait décrire l'ancien pilote ; deux lectures, deux cartes, un veto faux
    imap = store._imap() or {}
    if not lanes:                                             # sans preset : l'ancien calcul, par entrée
        by_ch = {str(i.get("ch")): i for i in (imap.get("inputs") or [])}
        for ck in ("1", "2"):
            role = (by_ch.get(ck) or {}).get("role")
            if role and role not in ("none", "other") and not modes_mod.allows(role, state.mode):
                veto.add(ck)
        mrole = (imap.get("midi") or {}).get("role")
        if mrole and mrole != "none":
            roles = ["keys", "pads"] if mrole == "keys-pads" else [mrole]
            if all(not modes_mod.allows(r, state.mode) for r in roles):
                veto.add("k")
        return veto
    by_ch = {str(i.get("ch")): i for i in (imap.get("inputs") or [])}
    by_usb = {str(u.get("ch")): u for u in (imap.get("usb") or [])}
    for L in lanes:
        role = L.get("role")
        if not role or role in ("none", "other"):
            continue
        roles = ["keys", "pads"] if role == "keys-pads" else [role]
        if all(not modes_mod.allows(r, state.mode) for r in roles):
            veto.add(L["key"])
            continue
        # veto PAR ENTRÉE NUMÉROTÉE (2026-09-09) : la lane est liée à (rôle, n°), sinon on lit
        # l'entrée physique qu'elle occupe sur la carte du moment
        r, n = L.get("in_role"), L.get("in_nth")
        if not (r and n):
            # une lane MIDI occupe un PORT USB du rack — un « usb » nu, celui où le moteur la joue (vital.lane_port),
            # une lane audio une entrée
            sel = str(L.get("in_sel") or "")
            if L.get("midi") and sel in ("", "usb"):
                from . import vital as _vital
                sel = "usb%s" % (_vital.lane_port(L.get("role"), sel) or 1)
            e = (by_usb.get(sel) if L.get("midi") else by_ch.get(sel)) or {}
            r, n = e.get("role"), e.get("nth")
        if r and n and not modes_mod.input_allowed(r, n, state.mode):
            veto.add(L["key"])
    return veto


def scene_shape(preset, scene_id):
    """« Forme » du plan bakée pour une scène = tout ce dont un changement EXIGE un rebuild : topologie
    (pistes, split, routage), fichiers (NAM/IR) et son Vital (chunk). IGNORE bypass/potards/niveaux —
    eux s'appliquent sans rebuild (scene_apply) — dont le MUTE de lane (union). Deux scènes de même
    forme -> bascule d'état pure sûre."""
    from . import rig
    baked = scene_bake.to_paths_preset(preset, scene_id, union=True, veto=input_veto(preset))

    def blk(b):
        s = (b.get("id"), b.get("type"), b.get("ref"), b.get("cab"), b.get("model"))
        # LE FICHIER RÉSOLU, pas seulement l'identifiant (2026-10-05) : la forme disait « fichiers (NAM/IR) »
        # mais ne lisait que `ref`/`model`. Une capture réécrite sous le même identifiant (conversion de
        # format, pack réinstallé) restait « même forme » -> scene_apply -> REAPER gardait l'ancien modèle.
        if b.get("type") in rig.CAPTURE_TYPES and b.get("ref"):
            with contextlib.suppress(Exception):
                from .resolver import _resolve
                s += (_resolve(b.get("ref"), {}, b.get("model")),)
        # BLOC VST HOST (2026-11-09) : son plugin (en changer = un autre FX), et son état au banc du premier usage
        # (bridge/plugin_trial.py) — le rig le RETIRE tant qu'il n'est pas essayé : le verdict change ce qui est posé.
        # Sans ça, le brouillon rejoué après le verdict avait la même forme -> scene_apply -> le plugin jamais posé
        # (vu au rack le 2026-11-09 : « open plugin window » ne montrait plus rien, 404 « missing »).
        if b.get("type") == "vst-host":
            from . import plugin_trial
            plug = b.get("plugin")
            s += (plug, "pending" if plugin_trial.pending(plug) else "refused" if plugin_trial.failed(plug) else "ok")
        if b.get("type") == "vital":                       # son Vital = vst_chunk greffé -> rebuild
            s += ((b.get("params") or {}).get("preset"),)
        # fichiers d'instrument chargés PAR CHIRURGIE DE CHUNK (pas des potards) : en changer
        # EXIGE un rebuild (bug piano 2026-07-23 : sfz changé en feuille -> scene_apply -> sfizz
        # restait sur sa sinusoïde par défaut). Même logique pour la banque DX7 de l'EP.
        if b.get("type") == "piano":
            s += ((b.get("params") or {}).get("sfz"),)
        if b.get("type") == "ep":
            s += ((b.get("params") or {}).get("bank"),)   # patch = PC vivant (slider dx7-ctl), pas un rebuild
        # Drum Kit : la forme est L'ENSEMBLE des kits que les scènes utilisent (union, scene_bake) — pas le
        # kit du moment. Toutes les paires sont posées au build, la scène en allume une (zéro rebuild) ;
        # ajouter un kit à une scène change l'ensemble -> rebuild. Le 23/09 midi la forme portait le kit
        # courant : chaque scène à kit différent rebâtissait (1 s de trou, 3 Go pour Aasimonster).
        if b.get("type") == "drumkit":
            s += (tuple(b.get("kits") or [(b.get("params") or {}).get("kit")]),)
        # Pads : le kit = les samples chargés dans les RS5k AU BUILD (un fichier par pad, pas un potard). Sans lui
        # dans la forme, changer de kit au tiroir ne faisait qu'un scene_apply et les pads gardaient l'ancien kit
        # (2026-10-13 : « quand je change le kit il ne se passe rien »).
        if b.get("type") == "pads":
            kid = (b.get("params") or {}).get("kit")
            s += (kid,)
            # ET SON CONTENU : un kit réenregistré sous le même id (« Save » de l'éditeur de pads, kit d'usine
            # réorganisé) change les samples sans changer le nom — même classe que la capture réécrite plus haut
            with contextlib.suppress(Exception):
                from . import kits as _kits
                k = _kits.get_kit(kid) if kid else None
                s += (tuple((p.get("note"), p.get("sample"), p.get("mode"), p.get("level")) for p in (k or {}).get("pads") or []),)
        return s

    def node(n):
        if rig.is_split(n):
            sp = n["split"]
            return ("split", sp.get("merge") is None,
                    tuple((br.get("id"), br.get("out"), br.get("out_sel"),
                           tuple(blk(b) for b in br.get("blocks", []))) for br in sp.get("branches", [])))
        return blk(n)

    # le mode looper (bloc marqueur OU flag legacy) fait partie de la forme :
    # l'activer/désactiver crée/supprime la piste -> rebuild
    # ⚠ SA TABLE DE BOUCLES AUSSI (docs/looper.md) : elle décide des SENDS vers la piste Looper.
    # Sans elle, changer la source d'une boucle dans le Designer ne produisait qu'un scene_apply
    # — l'écran montrait la nouvelle carte, le câblage gardait l'ancienne, en silence. C'est
    # exactement la classe de panne que ce chantier supprime.
    # les CANAUX des contrôleurs (profils de calibration, bridge/controllers.py) : les connaître change le câblage
    # de la lane Keys (sous-piste des pads, envois filtrés par canal) -> rebuild quand ils apparaissent ou changent
    chans = ()
    with contextlib.suppress(Exception):
        from . import controllers
        chans = controllers.all_channels()
    return (chans, rig.looper_enabled(preset),
            tuple((r["sw"], r["src"]) for r in rig.looper_loops(preset))) + tuple(
        (p.get("id"), p.get("input"), p.get("out"), p.get("out_sel"), bool(p.get("midi")),
         tuple(node(n) for n in p.get("chain", []))) for p in baked.get("paths", []))


def stomp_states(preset, scene_id):
    """État on/off des stomps UTILISÉS, par SWITCH (6-10), depuis la scène active. Un switch = ON si tous
    ses blocs assignés (block.foot) sont on dans la scène ; un switch portant un whammy-dt suit
    state.whammy_on (piloté en MIDI, pas un FX de scène). Clés = numéro de switch."""
    # le calcul vit dans preset_view (pur, partagé avec golem.fm) : une seule source
    from . import preset_view
    return preset_view.stomp_states(preset, scene_id, state.whammy_on, store._imap())


# ── banks FCB (slot -> preset via la setlist-source) ─────────────────────────────────────────
from . import setlists as _setlists_mod
FCB_PHYS_BANKS = _setlists_mod.MAX_SLOTS   # 19 banks au pied = la taille d'une setlist (une seule
                                           # source : setlists.MAX_SLOTS). Décision 2026-07-28 :
                                           # une setlist = un concert, ça tient sur le pédalier.


def fcb_setlist():
    """La setlist ACTIVE — plus l'unique fcb-banks.json (contrat docs/setlists.md). L'id vient de
    la config globale config/setlist.json ; on ne le devine pas et on ne l'écrit jamais ici."""
    from . import setlists as _sl
    return _sl.load(_sl.active_id()) or {}


def remember_live():
    """Note ce qui joue dans `.live.json` : preset, scène, et le MORCEAU (ligne de setlist, ou chanson de Songs). Relu
    au démarrage du bridge (adoption) et par l'accueil « last » (startup_home)."""
    _sg = state.song or {}
    _write_json_atomic(os.path.join(C.PRESETS_DIR, ".live.json"),
                       {"preset": state.preset_id, "scene": state.scene_id,
                        **({"line": _sg["line"], "setlist": _sg.get("setlist")} if _sg.get("line") else {}),
                        **({"band_song": _sg["band_song"]} if _sg.get("band_song") and not _sg.get("line") else {})})


def _song_from_live(live, pid):
    """Le morceau noté dans `.live.json` au dernier rappel, s'il est TOUJOURS là : sa ligne existe encore dans la
    setlist active et porte ce preset (sinon la chanson de la page Songs, si sa fiche joue ce preset). Ou None."""
    from . import setlists as _sl
    lid = (live or {}).get("line")
    if lid:
        sl = fcb_setlist()
        if (live.get("setlist") in (None, sl.get("id"))):
            ln = next((x for x in sl.get("lines") or [] if isinstance(x, dict) and x.get("id") == lid), None)
            if ln and _sl.pid_of(ln) == pid:
                return song_of_line(ln, pid)
        return None
    bs = (live or {}).get("band_song")
    if bs:
        from . import songs as _songs
        doc = _songs.load(bs)
        if doc and (doc.get("sheet") or {}).get("preset") == pid:
            return song_of_song(doc, pid)
    return None


def _fcb_slot_line(slot):
    """La LIGNE de la bank `slot` de la setlist active (docs/setlists.md §9), ou None."""
    from . import setlists as _sl
    return _sl.line_at(fcb_setlist(), slot)


def _fcb_slot_pid(slot):
    from . import setlists as _sl
    return _sl.pid_of(_fcb_slot_line(slot)) or None


def song_of_line(line, pid):
    """Ce que le rack SAIT du morceau quand il vient d'une ligne : titre, slug opaque, tempo
    surchargé, id de ligne (et sa setlist), backing et arrangement de la ligne (drapeaux).
    None hors ligne — à ce moment-là rien ne dit quel morceau on joue."""
    if not isinstance(line, dict):
        return None
    # la fiche JOUÉE, pas celle que la ligne stocke : une ligne ajoutée depuis le répertoire ne porte
    # que `band_song`, et son tempo est celui de sa chanson (docs/songs.md §9.7)
    from . import songs as _songs
    sh = _songs.line_sheet(line)
    return {"line": line.get("id"), "setlist": (fcb_setlist() or {}).get("id"), "preset": pid,
            "title": _songs.line_title(line), "slug": line.get("song_slug"), "bpm": sh.get("bpm"),
            "backing": sh.get("backing"), "arrangement": bool(sh.get("arrangement")),
            **({"band_song": line["band_song"]} if line.get("band_song") else {})}


def song_of_song(doc, pid):
    """Ce que le rack SAIT du morceau quand il vient de la PAGE SONGS (▶ Play sans setlist) : la même
    forme que song_of_line, sans ligne. effective_preset relit alors la fiche de la chanson."""
    if not isinstance(doc, dict):
        return None
    sh = doc.get("sheet") or {}
    return {"line": None, "setlist": None, "preset": pid, "title": doc.get("title"), "slug": None,
            "bpm": sh.get("bpm"), "backing": sh.get("backing"), "arrangement": bool(sh.get("arrangement")),
            "band_song": doc.get("id")}


def bind_foot_claims(p):
    """Ce que les switches 1-5 EMPRUNTÉS et le switch du BACKING valent pour ce preset : la table que
    lisent la rangée des scènes de /live et `_on_foot_scene` au pied, et le switch dont les fronts vont
    au transport du backing. Appelé par app._bind_foot_services, donc sur TOUS les chemins qui posent
    ou éditent le preset courant (recall, adoption au boot, sauvegarde du Designer, audition d'un essai)
    — n'être calculé qu'au recall laissait le Click posé sur SW4 invisible et muet (2026-09-15)."""
    global backing_sw
    from . import backing as backing_mod
    state.scene_claims = store._scene_claims(p) if p else {}
    backing_sw = backing_mod.backing_switch(p) if p else None


def merge_arrangement(preset, line_arr):
    """Le bloc joué : les parties de la LIGNE, la pédale et la règle d'avance du PRESET.
    Sans bloc dans le preset (rig d'avant la migration), la ligne fait foi telle quelle."""
    from . import arrangement as _arr
    blk = dict(line_arr or {})
    rig = _arr.block_of(preset) or {}
    if not rig:
        return blk
    blk["id"] = rig.get("id") or blk.get("id") or "arr-1"
    if rig.get("foot"):
        blk["foot"] = rig["foot"]
    else:
        blk.pop("foot", None)
    if (rig.get("params") or {}).get("advance"):
        blk["params"] = {**(blk.get("params") or {}), "advance": rig["params"]["advance"]}
    return blk


def effective_preset(p):
    """Le preset TEL QUE LA LIGNE LE JOUE (docs/setlists.md §9.3, arrangement.md §4 corrigé) :
    l'arrangement et le backing de la ligne remplacent ceux du preset. HORS ligne (rappel direct),
    PAS d'automation — l'arrangement vit sur la ligne, un seul lieu — et le backing du preset reste.
    La ligne est RELUE sur disque : une retouche de l'arrangement prend effet au prochain load/start."""
    if not p:
        return p
    song = getattr(state, "song", None) or {}
    q = dict(p)
    cfg = dict(q.get("config") or {})
    line = None
    if song.get("line") and song.get("preset") == q.get("id"):
        from . import setlists as _sl
        line = _sl.line_by_id(song.get("setlist") or _sl.active_id(), song["line"])
    # ▶ PLAY DEPUIS LA PAGE SONGS (2026-09-24, « comment je lance un arrangement ? ») : le morceau
    # joué peut être une CHANSON sans ligne de setlist — même fiche, même fusion, la ligne en moins.
    sheet = None
    if line is None and song.get("band_song") and not song.get("line") and song.get("preset") == q.get("id"):
        from . import songs as _songs
        doc = _songs.load(song["band_song"])
        sheet = dict((doc or {}).get("sheet") or {}) if doc else None
    if line is not None or sheet is not None:
        # ── LE RIG ET LA CHANSON, CHACUN SA MOITIÉ (docs/arrangement.md §4 bis, 2026-09-16) ────
        # La LIGNE porte les parties (elles sont la chanson) ; le PRESET porte le bloc Arrangement,
        # donc la PÉDALE et la règle d'avance — §6 : « chaque preset porte sa règle », et une pédale
        # appartient au pédalier, pas au morceau. Avant, la pédale voyageait dans la ligne : deux
        # chansons sur le même rig pouvaient démarrer avec deux pédales différentes, et le pédalier
        # ne savait même pas que l'arrangement existait.
        # la fiche JOUÉE (docs/songs.md §9.7) : celle de la chanson, surchargée par les seules
        # exceptions déclarées de la ligne — une ligne {band_song} seule joue toute sa chanson
        from . import songs as _songs
        if sheet is None:
            sheet = _songs.line_sheet(line)
        arr = sheet.get("arrangement")
        cfg["arr"] = {"blocks": [merge_arrangement(p, arr)]} if arr else {"blocks": []}
        # le TEMPO joué est celui de la fiche (Reaper le reçoit déjà au recall, ligne « cmd["bpm"] ») :
        # sans ça, arrangement.plan() comptait les mesures au tempo du PRESET — 88 contre 87 sur Kite
        # Rock, 3 s de dérive sur cinq minutes (trouvé le 2026-09-24 en posant ▶ Play)
        if sheet.get("bpm"):
            q["bpm"] = sheet["bpm"]
        # LA BACKING EST CELLE DE LA CHANSON (docs/song-backing.md §2, 2026-10-18) : ses stems, sinon la backing de sa
        # fiche — jamais une chanson choisie par le preset. Elle ne joue que si le preset a le LECTEUR (Backing Track).
        song_backing = sheet.get("backing")
        # LOT 3 (§9.9) : les BLOCS PAR MORCEAU — la ligne surcharge les blocs config du preset PAR ID
        # (params fusionnés, bypass remplacé). Un id que le rig n'a plus est ignoré, et dit.
        ovs = sheet.get("blocks") or {}
        if ovs:
            seen = set()
            for lane in ("gen", "rec"):
                blocks = []
                for b in ((cfg.get(lane) or {}).get("blocks") or []):
                    if isinstance(b, dict) and b.get("id") in ovs:
                        ov = ovs[b["id"]]
                        seen.add(b["id"])
                        b = {**b, "params": {**(b.get("params") or {}), **(ov.get("params") or {})}}
                        if "bypass" in ov:
                            b["bypass"] = bool(ov["bypass"])
                    blocks.append(b)
                if lane in cfg:
                    cfg[lane] = {**cfg[lane], "blocks": blocks}
            lost = sorted(set(ovs) - seen)
            if lost:
                log_recall.warning(f"{'ligne ' + str(line.get('id')) if line else 'chanson ' + str(song.get('band_song'))} : surcharge de blocs absents du rig, ignorée : {lost}")
    else:
        cfg["arr"] = {"blocks": []}
    q["config"] = cfg
    # ── QUELLE BACKING JOUE (docs/song-backing.md §2) ──────────────────────────────────────────────────────────
    # Celle de la CHANSON jouée : ses stems (`.golem`), sinon la backing de sa fiche (ligne comprise). Un preset joué
    # SEUL n'en joue aucune. Le bloc Backing Track ajoute le pied et la règle des stems ; il n'est PAS requis pour que
    # la chanson joue sa backing (une ligne de setlist la jouait déjà sans lui). L'ancien `backing.songs` du
    # preset est IGNORÉ (recopié sur ses chansons et ses lignes par backing_owner.migrate). Clé résolue ICI, une
    # fois : tout ce qui compare « la backing chargée » à « celle du morceau » lit la même (lot 1.5).
    from . import backing_owner as _bo
    from . import golemfm as _mae
    bsongs = []
    if line is not None or sheet is not None:
        bs_id = ((line or {}).get("band_song")) or (song.get("band_song") if song.get("preset") == q.get("id") else None)
        if bs_id and _mae._golem_stems(bs_id):
            d = _songs.load(bs_id) or {}
            bsongs = [{"slug": bs_id, "title": d.get("title"), "artist": d.get("artist")}]
        elif song_backing:
            bsongs = _mae.resolve_backing_songs([{"slug": song_backing}], bs_id)
    # ⚠ le KARAOKÉ est l'exception voulue : un preset ÉPHÉMÈRE fabriqué POUR une chanson (karaoke.py), rappelé seul —
    # sa liste est celle de la soirée Vocals, elle joue telle quelle
    if q.get("id") == store.KARAOKE_ID:
        return q
    # la RÈGLE DES STEMS du preset (§3) voyage avec : le lecteur la pose sur le mix de la chanson au chargement
    q["backing"] = {"songs": bsongs, "mute": _bo.rule(q)}
    return q


def song_click():
    """Ce que la CHANSON jouée dit du click (§9.9) : {beats?, den?} — vide sans chanson ou sans surcharge.
    À fusionner sur la config globale dans toute commande `click` (app._click_cfg). Une chanson chargée depuis Songs
    (sans ligne) compte aussi (docs/designer-song.md §6) : avant, sa mesure était ignorée."""
    song = getattr(state, "song", None) or {}
    if not ((song.get("line") or song.get("band_song")) and song.get("preset")):
        return {}
    p = load_preset(song["preset"])
    eff = effective_preset(p) if p else None
    blocks = (((eff or {}).get("config") or {}).get("rec") or {}).get("blocks") or []
    cb = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "click"), None)
    prm = (cb or {}).get("params") or {}
    out = {}
    for k in ("beats", "den"):
        v = prm.get(k)
        if isinstance(v, (int, float, str)) and str(v).strip().isdigit() and 1 <= int(v) <= 16:
            out[k] = int(v)
    return out


def _align_pedalboard(slot):
    """Amène le pédalier sur `slot` s'il n'y est pas déjà. Idempotent, et silencieux sur un
    appareil qui ne sait pas recevoir (la 1.0.4 : DIN à sens unique).

    La mémoire de position vit dans bridge/pedalboard.py, avec l'ordre qui la modifie."""
    from . import pedalboard
    if slot is None or pedalboard.believed_slot() == slot:
        return False
    return pedalboard.goto_bank(slot)


def slot_of_preset(pid):
    """Le slot qu'occupe ce preset dans la setlist active, ou None s'il n'y est pas."""
    try:
        return fcb_setlist().get("presets", []).index(pid)
    except ValueError:
        return None


# ── le cœur ──────────────────────────────────────────────────────────────────────────────────
def is_trial_doc(preset):
    """Un brouillon du Designer qui N'EST PAS un preset nommé : un patch ouvert (`__patch`) ou un banc
    neuf (`nouveau-preset`). C'est lui que le rack adopte sous `sandbox-try` dès sa première audition
    (docs/patches.md §19, complément 2026-09-14) — pour que /live et le pied jouent ce qui sonne."""
    if not isinstance(preset, dict):
        return False
    pid = preset.get("id")
    return bool(preset.get("__patch")) or pid in (None, "", "nouveau-preset", store.SANDBOX_TRY_ID)


def trial_id(preset):
    """L'id sous lequel un brouillon du Designer JOUE (docs/patches.md §6) : un patch NOMMÉ joue
    sous `patch:<id>` — le même id qu'un rappel depuis une bank de sons ; un banc sans nom sous `sandbox-try`."""
    pid = ((preset or {}).get("__patch") or {}).get("id")
    return ("patch:" + str(pid)) if pid else store.SANDBOX_TRY_ID


def is_trial_id(pid):
    """Le preset courant est-il un essai (brouillon sans nom) ou un patch joué comme un preset ?"""
    return pid == store.SANDBOX_TRY_ID or str(pid or "").startswith("patch:")


def do_recall(pid, scene, line=None):
    """Coeur du recall (sync, réutilisé par l'API ET le pied — sous _RECALL_LOCK). Retourne True si ok.
    pid=None -> recall de scène sur le morceau courant. Un changement de SCÈNE de forme invariante
    (mêmes pistes/FX/fichiers/Vital, seuls bypass/potards/niveaux changent) est appliqué SANS rebuild
    (action scene_apply) — pas de chirurgie de FX pendant l'audio (cause du GPF mediaafx sur recalls
    rapides). Sinon (preset différent, topologie/Vital modifiés) -> rebuild complet (rig_recall)."""
    from . import backing as backing_mod
    from . import midi_out
    from . import rig as _rig
    from . import diag as _diag
    global backing_sw
    _t0 = time.monotonic()
    _preset_changed = False        # recall de SCENE seule : le preset ne bouge pas (voir plus bas)
    with _RECALL_LOCK:
        p = load_preset(pid) if pid else None
        if pid and not p:
            _diag.event("recall", ok=False, ms=0)
            return False
        if p:
            # RÈGLE 1 (docs/arrangement.md §12) : un arrangement ne traverse JAMAIS un changement de
            # preset. Il s'arrête net — sinon l'ancien continuerait de commander des scènes qui
            # n'existent plus dans le nouveau. Le cas normal (le pupitre charge le morceau suivant) est
            # couvert par le même chemin : `load` réarme le nouveau à la mesure 1, à l'arrêt.
            _preset_changed = p["id"] != state.preset_id
            if _preset_changed:
                _arr_ctl.stop(silent=True)
                # Le morceau change par un autre chemin que le pied (écran, setlist, cue) : le
                # pédalier doit suivre, sinon son prochain appui de scène renverra l'ancien PC et
                # ramènera le rack en arrière. No-op s'il y est déjà, ou s'il ne sait pas recevoir.
                _align_pedalboard(slot_of_preset(p["id"]))
                # golem.fm affiche « ce qui joue » : un PRESET qui change part hors cadence (débouncé — une
                # rafale de rappels ne coûte qu'un PUT) ; une scène seule attend le prochain envoi
                with contextlib.suppress(Exception):
                    from . import rigstatus
                    rigstatus.push_soon(delay=3.0)
            state.preset_id = p["id"]; state.preset_name = p.get("name")
            # la LIGNE de setlist d'où vient ce rappel (tempo, titre, slug) — ou rien. ⚠ MÊME PRESET SANS LIGNE
            # (2026-10-09, « no song · sounds only — load it » après chaque tap de scène sur /live) : on
            # GARDE le morceau. Un tap de scène envoyait {preset, scene} et ce rappel « sans ligne » effaçait
            # Paper Kite ; même panne que celle du pied le 2026-09-20 (app.py). Seul un AUTRE preset, ou une
            # vraie ligne, change le morceau.
            if line is not None or _preset_changed or not state.song:
                state.song = song_of_line(line, p["id"])
            scenes = p.get("scenes", [])
            if scene is None and scenes:
                scene = scenes[0]["id"]
        if p:
            _arr_ctl.load(effective_preset(p))   # plan prêt à jouer, transport à l'arrêt — l'arrangement de la LIGNE
        if scene is not None:
            state.scene_id = scene
            # ⚠ NE PAS remettre l'état Whammy à zéro ici. C'était un reset SILENCIEUX (aucun MIDI) qui,
            # en plus de laisser la pédale physiquement enclenchée, OUBLIAIT le mode engagé — donc même
            # le bypass suivant n'avait plus de nom à envoyer. L'autorité, c'est _whammy_dt_glue, qui
            # tourne à chaque émission (fin de cette fonction) et éteint quand le preset n'a pas de bloc.
            cur = load_preset(state.preset_id) if state.preset_id else None
            sc = next((s for s in (cur or {}).get("scenes", []) if s.get("id") == scene), None)
            if sc and "voice" in sc:
                state.voice_on = bool(sc["voice"])
            if sc and sc.get("whammy"):             # scène qui arme la Whammy -> PC direct (chemin prouvé)
                mode = sc["whammy"].get("mode")
                midi_out.whammy_mode(mode, True)
                state.whammy_on = True
                state.whammy_mode = mode
        # seed de l'état des stomps (rangée haute de la Live) depuis la scène active
        cur = load_preset(state.preset_id) if state.preset_id else None
        state.stomps = stomp_states(cur, state.scene_id)
        foot_leds.request_align()          # les diodes du pédalier suivent la scène (docs/pedalboards.md § Diodes)
        state.scene_claims = store._scene_claims(cur) if cur else {}   # rangée scènes empruntée (doctrine foot_scene_claim)
        # sources du bloc Rec (coches IN 1/IN 2/USB) : publiées pour golem_perfrec (lues à chaque op_start —
        # le start manuel de la Library honore aussi la config du preset actif)
        try:
            # atomique : golem_perfrec LIT ce fichier côté Reaper — une écriture directe expose une
            # lecture déchirée même sans coupure de courant (audit 2026-08-12)
            store._write_json_atomic(os.path.join(C.PRESETS_DIR, ".perfsrc.json"),
                                     store.rec_sources(cur), indent=None)
        except OSError:
            pass
        # click : en mode « preset », le bloc Click du preset qu'on charge décide (joue / s'arrête).
        # DIFFÉRÉ (idiome drums/backing) : .command.json est un slot UNIQUE et le rig_recall est écrit
        # en fin de do_recall — envoyer le click ici le ferait écraser avant que golem_watch ne le lise.
        try:
            if modes_mod.click_mode(state.mode) == "preset":
                _later(0.8, _click_follow_preset, effective_preset(cur))   # le click de la LIGNE (§9.9)
        except Exception as e:
            log_click.warning(f"politique preset non appliquée : {e}")
        # mode looper (bloc marqueur OU flag legacy) : les stomps deviennent le transport ; _poll_looper suit
        # VETO du mode machine (docs/modes.md) : effectif = preset ∧ mode (le preset fournit, le mode autorise)
        state.looper = {**state.looper,
                        "enabled": bool(cur) and _rig.looper_enabled(cur) and modes_mod.allows("looper", state.mode)}
        # backing tracks : arme la liste de chansons + le switch du bloc, et planifie l'auto-load
        # de songs[0] à +0,7 s (> SETTLE du veilleur — jamais de load pendant un rebuild)
        cur_eff = effective_preset(cur)          # le backing de la LIGNE remplace celui du preset
        backing_sw = backing_mod.backing_switch(cur_eff)
        songs = ((cur_eff or {}).get("backing") or {}).get("songs") or []
        state.backing = {**state.backing,
                         "enabled": bool(songs) and modes_mod.allows("backing", state.mode), "songs": songs}
        _backing_ctl.on_recall(cur_eff, allowed=state.backing["enabled"])
        # blocs SAMPLE (lanceurs de one-shots, foot_scene_claim + stomps) : switch -> {block, samples}
        # VETO du mode (docs/modes.md, décision 2026-07-31) : effectif = preset ∧ mode, exactement
        # comme looper/backing. Il coupe LE PIED AUSSI, pas seulement l'automation — « un mode dit ce
        # que le rig FAIT, pas ce que l'écran affiche ». Un veto déclaré qui ne coupait rien mentait à
        # qui l'avait réglé (constaté en auditant les 12 services : `sample` était le seul non appliqué).
        _bind_foot_services(effective_preset(cur))   # les samples de la LIGNE au pied (§9.9)
        # coupe toute batterie encore en boucle dont le bloc n'est plus dans le preset rappelé (le
        # séquenceur JSFX boucle jusqu'à un stop explicite). Changement de scène = même bloc -> pas coupé.
        # Source de vérité = .drums.json (rapport Reaper), robuste même après un reload du bridge. On SÉQUENCE
        # le stop APRÈS le recall (+0,8 s) : la commande unique .command.json est écrasée par le rig_recall
        # émis juste après -> le stop doit partir ensuite pour que golem_watch le voie (idiome backing).
        _valid = {(d or {}).get("block") for d in (state.drum_switches or {}).values()}
        try:
            _rep = (json.load(open(C.DRUMS_FILE)).get("blocks") or {})
            _playing = [b for b, s in _rep.items() if isinstance(s, dict) and s.get("playing")]
        except Exception:
            _playing = []
        if _playing:
            _later(0.8, lambda: _drums_ctl.stop_orphans(_valid, also_playing=_playing))
        state.touch()
        # ÉTAT LIVE persistant : de quoi ré-adopter le rig au démarrage du bridge sans le reconstruire
        # (cf. boot_recall). Le livemap de golem_rig dit QUEL preset est monté, mais pas sur quelle
        # SCÈNE — c'est ici qu'on la garde.
        # la décision rebuild vs scene_apply (forme invariante) vit dans emit_sandbox_preset (_LAST_EMIT)
        # ── UN RECALL QUI NE COMPILE PAS ÉCHOUE (audit 2026-09-13, B2). Avant : .live.json était
        # écrit AVANT l'émission et l'erreur de compile s'arrêtait dans emit_sandbox — do_recall rendait
        # True, /live et le pied affichaient le preset, et boot_recall le ré-adoptait au démarrage
        # suivant : « le rack dit qu'il joue et rien ne sort ». L'erreur est maintenant portée par
        # l'état (puce ⚠ RIG sur /live), le rappel rend False, et le live n'est mémorisé que si
        # l'émission a été acceptée.
        _shape0 = (_LAST_EMIT.get("pid"), _LAST_EMIT.get("shape"))
        err = emit_sandbox(state.preset_id, state.scene_id)
        state.rig_error = err or None
        # lot 8 : le recall dans la chronologie — hash (jamais l'id), scène, durée, rebuild ou non,
        # TYPES de blocs (pour `block_types_used`) ; un simple changement de scène = `scene`
        _rebuild = (_LAST_EMIT.get("pid"), _LAST_EMIT.get("shape")) != _shape0
        _ms = round((time.monotonic() - _t0) * 1000)
        if pid is None:
            _diag.event("scene", to=state.scene_id, ms=_ms)
        else:
            _diag.event("recall", preset_hash=_diag.preset_hash_of(state.preset_id), scene=state.scene_id,
                        ms=_ms, ok=not err, rebuild=_rebuild,
                        blocks=sorted({b.get("type") for b, _ in store.all_blocks(cur) if isinstance(b, dict) and b.get("type")}) if cur else [])
        if err:
            log_sandbox.error(f"recall {state.preset_id}/{state.scene_id} refusé : {err}")
            state.touch()
            if _notify:
                _notify()
            return False
        with contextlib.suppress(Exception):
            # + le MORCEAU (2026-10-09) : sans lui, un redémarrage du bridge réadoptait le preset SANS sa ligne —
            # /live affichait « no song · sounds only — load it » et le pied perdait l'arrangement
            remember_live()
        # l'émission vient de trancher l'état Whammy (glu des blocs) : le seed de stomps ci-dessus l'a
        # lu AVANT. On re-sème le switch qui porte la Whammy et on re-notifie, sinon la pastille /live
        # affiche l'état du preset PRÉCÉDENT jusqu'au prochain geste.
        with contextlib.suppress(Exception):
            after = stomp_states(cur, state.scene_id)
            if after != state.stomps:
                state.stomps = after
                foot_leds.request_align()
                state.touch()
    if pid:
        with contextlib.suppress(Exception):     # un preset rappelé au rack quitte le karaoké (docs/karaoke.md)
            from . import karaoke
            karaoke.on_recall(pid)
    if _notify:
        _notify()          # hors verrou : l'état est posé, les WebSockets peuvent le lire
    return True


def do_recall_slot(slot, source=None):
    """Recall d'un SLOT de bank. Résout slot->preset via la setlist-source. Idempotent :
    ne reconstruit que si le preset change (un changement de scène passe par do_recall(None, scene)).

    `source="pc"` = le pédalier annonce SA bank : on l'enregistre AVANT de recaller, ce qui
    neutralise le réalignement plus bas. Toute autre source (pavé numérique, écran) laisse la
    mémoire sur l'ancienne bank, donc l'alignement part.
    """
    with _RECALL_LOCK:
        if source == "pc":
            from . import pedalboard
            prev = pedalboard.believed_slot()
            pedalboard.note_foot_bank(slot)
            # UN ESSAI TIENT TANT QUE LE PIED NE CHANGE PAS DE BANK (patches.md §19, bug du 2026-09-30 :
            # « je ne peux pas appuyer sur les scènes de mon FCB sinon ça change le patch en cours »).
            # La puce envoie le PC de SA bank avec CHAQUE appui de scène ou de stomp : ce PC-là n'est pas
            # une demande de morceau, c'est la bank où le pied se trouvait déjà. Un patch ouvert depuis le
            # Designer (patch:<id>, sandbox-try) n'a pas de slot : sans cette garde, chaque appui rappelait
            # le morceau de la bank, puis appliquait la scène. Un PC DIFFÉRENT (UP/DOWN puis un switch) est,
            # lui, un vrai choix de morceau. Bank inconnue (rack qui démarre) : le dernier geste — l'écran —
            # garde la main, et la bank est apprise.
            if is_trial_id(state.preset_id) and prev in (None, slot) and _fcb_slot_pid(slot) != state.preset_id:
                log_bank.info(f"PC{slot} de la bank du pied pendant l'essai {state.preset_id} — gardé (seule la scène suit)")
                return True
        else:
            _align_pedalboard(slot)
        line = _fcb_slot_line(slot)
        pid = _fcb_slot_pid(slot)
        from . import songs as _songs
        title = _songs.line_title(line)
        if not pid:
            if line and title:
                # ligne SANS rig (§9.4) : le pied affiche le titre et ne charge rien
                state.song = song_of_line(line, None)
                log_bank.info(f"slot {slot} : « {title} » sans rig — rien à charger")
            else:
                log_bank.warning(f"slot {slot} vide (setlist active)")
            r = False
        elif pid == state.preset_id and (state.song or {}).get("line") == (line or {}).get("id"):
            r = True                        # déjà chargé, même ligne -> no-op (pas de rebuild)
        else:
            log_bank.info(f"slot {slot} -> preset {pid}" + (f" (« {title} »)" if title else ""))
            # MÊME PRESET, ligne inconnue (rappel précédent venu de l'écran, sans ligne) : on adopte la
            # ligne mais on GARDE LA SCÈNE COURANTE. `scene=None` retombe sur `scenes[0]`, et le pied
            # envoie ce PC avec CHAQUE appui de scène : le guitariste traversait la scène A à chaque
            # geste (2026-09-20). Un preset DIFFÉRENT démarre toujours sur sa première scène.
            keep = state.scene_id if pid == state.preset_id else None
            return do_recall(pid, keep, line=line)     # do_recall notifie lui-même
    if _notify:
        _notify()      # même un no-op se montre (position de bank) — l'ancien câblage diffusait toujours
    return r


def emit_sandbox(pid, scene, action="rig_recall"):
    """Matérialise un preset PERSISTÉ (par id) dans le sandbox. Utilisé par le recall / le pied.
    `action` = "scene_apply" pour une bascule de scène sans rebuild (cf. do_recall)."""
    if not pid:
        return None
    preset = load_preset(pid)
    if not preset:
        return f"unknown preset '{pid}'"
    return emit_sandbox_preset(preset, scene, action)       # texte du refus ou None — l'appelant décide


def reapply_sandbox():
    """Ré-applique le .sandbox.json (l'état live d'avant) — appelé après une génération de preview
    qui a pris le moteur pour rendre. No-op si aucun sandbox persisté."""
    sb = _read_json(SANDBOX_BUF, {}) or {}
    if isinstance(sb.get("preset"), dict):
        emit_sandbox_preset(sb["preset"], sb.get("scene"))


# dernière matérialisation émise : (preset id, FORME du plan). Si la nouvelle émission a la MÊME
# forme (mêmes pistes/FX/fichiers/Vital — seuls bypass/potards/niveaux/mutes changent), on bascule
# l'état SANS rebuild (scene_apply) : couvre les changements de scène ET les éditions du Designer
# (potard, bypass, toggle de scène, mute de lane, niveau, foot…). Ajout/retrait/DÉPLACEMENT de bloc,
# changement de capture ou de son Vital = forme différente -> rebuild. Réinitialisé quand Reaper
# redémarre (invalidate_shape, appelée par routes_system/reaper_update) — plus jamais de chirurgie
# de FX pendant l'audio pour une simple retouche. (Cause des 2 crashs GPF mediaafx.)
_LAST_EMIT = {"pid": None, "shape": None, "gen": -1}


def check_preset(preset, scene):
    """Essai À BLANC d'un preset (dict) : même bake et même plan que l'émission, sans rien écrire ni
    toucher l'état. Retourne le texte du refus, ou None. `do_recall` avale le retour de la compile
    (emit_sandbox ne le lit pas) : un appelant qui doit REFUSER avant d'engager — patch-try, qui
    écrit la sandbox puis rappelle — passe par ici d'abord."""
    try:
        from . import compile_rig
        work = _copy.deepcopy(preset)
        store.ensure_volume(work)
        baked = scene_bake.to_paths_preset(work, scene, union=True, veto=input_veto(work))
        compile_rig.plan_preset(baked)
    except Exception as e:
        return str(e)
    return None


def emit_sandbox_preset(preset, scene, action="rig_recall"):
    """Matérialise un preset (dict, persisté OU edit-buffer) dans le SANDBOX : shim ancien->paths,
    compile, puis déclenche golem_rig. L'action est choisie ICI : si la forme du plan est identique
    à la dernière émission ET que le rig est vivant -> "scene_apply" (bascule d'état sur les pistes
    posées, zéro TrackFX_Add/Delete) ; sinon "rig_recall" (rebuild). Le .rig.json est recompilé dans
    les deux cas (golem_rig y lit les états bakés). `_route:"rig_recall"` : le veilleur route par
    sous-chaîne -> l'aiguillage vers golem_rig tient sans relancer le veilleur. Jamais fatal."""
    pid = preset.get("id")
    if not pid:
        log_sandbox.warning("preset sans id : ignoré")
        return "preset sans id"
    # UNE CAPTURE PRÊTÉE QUI MANQUE (docs/library-loans.md §2) : tirée en tâche de fond — le rappel ne
    # l'attend jamais — puis la sandbox est reposée, seulement si ce preset est encore celui qui joue.
    # Résolution locale d'abord : dans le cas courant (rien ne manque), aucun réseau.
    with contextlib.suppress(Exception):
        from . import loans

        def _again(got, pid=pid):
            if (_LAST_EMIT.get("pid") or pid) == pid:
                log_sandbox.info(f"prêt(s) installé(s) pour {pid} : {', '.join(got)} — sandbox reposée")
                reapply_sandbox()
        loans.pull_for_preset(preset, on_done=_again)
    with _RECALL_LOCK:
        try:
            from . import compile_rig
            # COPIE de travail : ensure_volume MUTAIT le preset reçu, et la persistance sandbox
            # réécrivait ce preset muté -> le bloc système volume-sys apparaissait comme une TUILE
            # au refresh sur les presets sans volume manuel (bug 2026-07-23). Le bloc système reste
            # invisible : il ne vit que dans la copie émise (bake + cibles EXP).
            work = _copy.deepcopy(preset)
            store.ensure_volume(work)                      # utilitaire système : master de volume (cible EXP), jamais dans le Designer
            if _exp_bake:                                  # la position connue des pédales, rebuild comme bascule de scène
                with contextlib.suppress(Exception):
                    _exp_bake(work)
            # union=True : toutes les lanes posées (mute par scène = D_MUTE) -> topologie stable entre scènes,
            # donc scene_apply peut basculer une scène sans rebuild (un seul chemin de matérialisation).
            baked = scene_bake.to_paths_preset(work, scene, union=True, veto=input_veto(work))
            # lanes que la carte ne peut pas prendre : dans l'état (puce ⚠ sur /live) et le journal
            um = baked.get("unmounted") or []
            if um != (getattr(state, "rig_unmounted", None) or []):
                state.rig_unmounted = um
                for u in um:
                    log_sandbox.warning(f"lane « {u['name']} » non montée : {u['reason']}")
            compile_rig.compile_preset(baked)
        except Exception as e:
            # « nothing to play » (scene_bake._why_empty) : un son SANS lane jouable — sortie mise sur NONE, lane coupée
            # dans le mode, entrée absente de la carte. C'est un état choisi et déjà DIT à l'écran, pas une panne : en
            # ERROR, il partait dans les rapports comme une erreur à chaque compilation (tools/check-use.py, 2026-10-27).
            (log_sandbox.warning if str(e).startswith("nothing to play") else log_sandbox.error)(
                f"compile {pid}/{scene} échoué : {e}")
            return str(e)                               # -> l'appelant (sandbox_apply) le remonte à l'UI
        shape = None
        with contextlib.suppress(Exception):
            shape = scene_shape(preset, scene)
        # `gen` : un restart/crash de Reaper depuis la dernière émission invalide le cache (le livemap
        # sur disque est périmé mais présent -> sans ce check, recall = scene_apply sur un projet VIDE,
        # rig muet ; constaté 2026-07-10 après un segfault mediaafx au lancement).
        if (action == "rig_recall" and shape is not None and _LAST_EMIT["pid"] == pid
                and _LAST_EMIT["shape"] == shape and _LAST_EMIT["gen"] == state.reaper_gen
                and state.reaper_running and rig_is_live(pid)):
            action = "scene_apply"                      # forme invariante -> bascule d'état, pas de rebuild
        # le preset a-t-il CHANGÉ depuis la dernière émission ? (la Whammy reçoit son PC « forcé » à ce moment-là).
        # Audit 2026-10-15 : cette ligne lisait `_preset_changed`, local à une AUTRE fonction — NameError avalé par le
        # suppress ci-dessous, et la Whammy DT ne recevait plus rien depuis le rappel (ruff F821).
        preset_changed = _LAST_EMIT["pid"] != pid
        _LAST_EMIT.update(pid=pid, shape=shape, gen=state.reaper_gen)
        cmd = {"action": action, "preset": pid, "scene": scene, "_route": "rig_recall"}
        # tempo de la LIGNE de setlist (docs/setlists.md §9.3) : joint à la commande quand le
        # rappel vient d'une ligne de CE preset — jamais écrit dans le preset
        song = getattr(state, "song", None) or {}
        if song.get("bpm") and song.get("preset") == pid:
            cmd["bpm"], cmd["bpm_from"] = song["bpm"], "line"
        elif preset.get("bpm"):
            # LE TEMPO DU DOCUMENT JOUÉ, joint à la commande (2026-10-13) : golem_rig le relisait dans
            # presets/<id>.json — un PATCH (patch:<id>) n'y est pas, donc son tempo n'était JAMAIS posé et Reaper
            # gardait celui du preset d'avant (96, 120…). Invisible tant que tous les patches étaient à 120 ; audible
            # dès qu'un patch porte un groove. Le bridge a le document exact, brouillon du Designer compris.
            cmd["bpm"], cmd["bpm_from"] = preset["bpm"], "preset"
        write_command(cmd)
        # PAS de trigger_action ici : golem_watch (defer) route la commande vers golem_rig.
        # L'action _RS… pointait sur golem_apply (ancien moteur) -> double exécution (audit 2026-07-07).
        with contextlib.suppress(Exception):
            # `force` au changement de PRESET seulement : on ne sait pas ce que la pedale a recu
            # entre-temps, et un PC de plus au chargement d'un morceau ne coupe rien qu'on entende.
            # Sur un changement de SCENE, un PC inutile ferait un blip sur une Whammy branchee
            # (voir _whammy_dt_glue) -- ce n'etait pas le blanc de A vers B du 2026-09-20.
            _whammy_dt_glue(baked, force=preset_changed)   # bloc whammy-dt -> PC/CC vers la pedale (jamais fatal)
        # ⚠ UN RECALL N'ÉCRIT JAMAIS UNE CONFIG GLOBALE (correctif 2026-07-27). Il y avait ici un
        # save_recorder_cfg_from(preset) : chaque rappel repoussait dans config/recorder.json les
        # paramètres Rec FIGÉS dans le preset. Résultat mesuré — les coches IN 2 / USB se remettaient
        # toutes seules au moindre recall, et chaque preset imposait son propre mode (polaris = tracks,
        # alex-test = mix). Le « singleton global » était donc écrasé par le dernier preset chargé.
        # L'extraction reste faite là où il y a une VRAIE édition : POST /api/preset (feuille du bloc).
        # Ici on ne fait que PUBLIER la config globale pour golem_perfrec.
        with contextlib.suppress(Exception):
            store._write_json_atomic(os.path.join(C.PRESETS_DIR, ".perfsrc.json"),
                                     store.rec_sources(preset), indent=None)
        with contextlib.suppress(Exception):
            _set_exp_blk_from(preset)               # cible du rôle bloc pour ce rig (wah, mix, whammy…)
        with contextlib.suppress(Exception):
            _set_exp_vol_from(work)                 # cible du rôle volume (voit le volume-sys de la copie)


# ── boot ─────────────────────────────────────────────────────────────────────────────────────
def _restore_arrival():
    """Un patch de golem.fm ESSAYÉ mais pas encore sauvé doit survivre à un redémarrage du bridge.

    ⚠ 2026-09-12 : `state.sandbox_rev` repart de 0 à chaque `reload.sh`, donc la bannière « a
    patch arrived » disparaissait — et avec elle le seul chemin vers le mode patch (« Open it »).
    Le Designer rouvrait alors un banc vide, et le patch restait dans la sandbox sans qu'on puisse
    le retrouver autrement qu'en le repoussant depuis golem.fm. Le seul indice qui survit au
    disque est `preset.__patch` (le Designer le renvoie tel quel à chaque audition) : `id` vide +
    origine golem.fm = pas encore en bibliothèque, donc l'arrivée est toujours d'actualité."""
    try:
        sb = _read_json(SANDBOX_BUF, {}) or {}
        pre = sb.get("preset") or {}
        pm = pre.get("__patch")
        # l'origine se lit sur le marqueur (générations récentes) OU sur le preset (posé par
        # patch-try depuis le début) : un marqueur d'avant le 12/09 n'a pas encore `origin`
        origin = (pm or {}).get("origin") or pre.get("origin")
        if isinstance(pm, dict) and not pm.get("id") and origin == "golem.fm":
            state.sandbox_rev = max(int(getattr(state, "sandbox_rev", 0) or 0), 1)
            state.sandbox_from = "golem.fm"
    except Exception as _e:
        _swallowed(_e)


async def boot_recall():
    _restore_arrival()                                     # avant tout retour anticipé
    """Au démarrage, charger un preset TOUT SEUL : sinon /live est vide et le rig est muet tant
    que personne n'a ouvert un navigateur pour cliquer. Or le rack démarre sans clavier.

    Deux cas, et la distinction compte :
    • Le rig est DÉJÀ monté (redémarrage du bridge pendant qu'on joue, ou après un crash) ->
      on ADOPTE ce qui tourne, sans rien reconstruire. Forcer la bank 00 ici ferait sauter le
      musicien à un autre son en plein morceau — le pire moment possible.
    • Rien n'est monté (vrai démarrage à froid) -> on rappelle la BANK 00 de la setlist active,
      c'est-à-dire ce que le pied jouerait en premier.

    On attend que Reaper réponde : un rig_recall émis avant que le moteur soit là part dans le vide.
    """
    from . import backing as backing_mod
    global backing_sw
    for _ in range(120):                                   # ~60 s de patience, puis on renonce
        if state.reaper_running:
            break
        await asyncio.sleep(0.5)
    else:
        log_boot.warning("Reaper absent après 60 s — aucun preset chargé au démarrage")
        from . import boot_progress
        boot_progress.fail("REAPER did not start within 60 s")
        return
    await asyncio.sleep(1.5)                               # laisse le projet finir de s'ouvrir
    from . import boot_progress
    if state.preset_id:
        boot_progress.preset_done(True)                    # quelqu'un a déjà rappelé entre-temps : le golem joue
        return
    live = _read_json(os.path.join(C.PRESETS_DIR, ".live.json"), {}) or {}
    pid = live.get("preset")
    # ⚠ le preset ÉPHÉMÈRE du karaoké ne s'adopte pas (2026-10-18) : laissé dans REAPER par une soirée Vocals, il
    # n'appartient à aucune bank — un redémarrage du bridge ouvrait /live sur « bank #00 » vide, et l'accueil choisi
    # était ignoré. On applique l'accueil à la place (golem.fm recharge le karaoké s'il pilote encore la soirée).
    if pid == store.KARAOKE_ID:
        log_boot.info("rig monté sur le karaoké (éphémère) : non adopté — l'accueil s'applique")
        pid = None
    if pid and load_preset(pid) and rig_is_live(pid):
        # ADOPTION : on s'aligne sur ce qui SONNE, sans toucher au moteur.
        p = load_preset(pid)
        state.preset_id, state.preset_name = pid, p.get("name")
        scenes = [s.get("id") for s in (p.get("scenes") or [])]
        state.scene_id = live.get("scene") if live.get("scene") in scenes else (scenes[0] if scenes else None)
        state.stomps = stomp_states(p, state.scene_id)
        foot_leds.request_align()
        state.scene_claims = store._scene_claims(p)
        # LE MORCEAU aussi (2026-10-09) : la ligne de setlist (ou la chanson de la page Songs) qui jouait. Sans elle,
        # chaque redémarrage du bridge laissait le preset « seul » : bandeau « no song · sounds only — load it »,
        # et ni l'arrangement ni les samples de la ligne au pied, jusqu'à un rappel à la main.
        state.song = _song_from_live(live, pid)
        if state.song:
            _arr_ctl.load(effective_preset(p))       # l'arrangement de la LIGNE, transport à l'arrêt (comme au rappel)
        # les REGISTRES du pied, sans quoi la tuile s'affiche et l'appui ne fait rien
        _bind_foot_services(effective_preset(p) if state.song else p)
        # les CIBLES DES PÉDALES EXP (2026-10-09) : l'adoption ne les calculait pas — après chaque redémarrage du
        # bridge, ni le volume ni le bloc ne répondaient à la pédale, et /live affichait « EXP 1 · Whammy » (la
        # valeur par défaut) jusqu'au premier rappel. Deux calculs purs, rien n'est envoyé au moteur.
        with contextlib.suppress(Exception):
            _eff = effective_preset(p) if state.song else p
            _set_exp_blk_from(_eff)
            _work = _copy.deepcopy(_eff)
            store.ensure_volume(_work)               # le master de volume système, comme à l'émission (cible EXP)
            _set_exp_vol_from(_work)
        backing_sw = backing_mod.backing_switch(p)
        # le BACKING aussi (2026-09-21) : l'adoption ne le réarmait pas, et après CHAQUE redémarrage
        # du bridge il restait « désactivé » jusqu'au prochain rappel du morceau — le switch 5 ne
        # lançait plus rien. On ne recharge pas les stems : ils sont déjà dans Reaper (rig adopté).
        # la backing de la CHANSON (song-backing.md §2), clés déjà résolues par effective_preset — comme au rappel
        _eff_bk = (effective_preset(p) or {}).get("backing") or {}
        songs = _eff_bk.get("songs") or []
        state.backing = {**state.backing, "songs": songs,
                         "enabled": bool(songs) and modes_mod.allows("backing", state.mode)}
        _backing_ctl.adopt(songs, _eff_bk.get("mute") or {})
        state.touch()
        if _notify:
            _notify()
        log_boot.info(f"rig déjà monté -> adopté : {pid} (scène {state.scene_id}"
                      f", {len(state.standard_switches or {})+len(state.sample_switches or {})+len(state.drum_switches or {})} bloc(s) au pied)")
        boot_progress.preset_done(True)
        return
    # L'ACCUEIL (bridge/startup_home.py) : un objet posé, le dernier joué, ou la bank 00 d'avant
    from . import startup_home
    steps = startup_home.plan()
    if steps:
        ok = await asyncio.get_running_loop().run_in_executor(_EXEC, startup_home.apply, steps)
        log_boot.info(f"accueil joué : {ok} — {steps}")
    else:
        first = startup_home.first_slot()                  # la première bank qui porte quelque chose, pas un trou
        ok = await slot_async(first)                       # à froid : hors boucle, comme tout recall
        log_boot.info(f"bank {first:02d} rappelée (la première non vide) : {ok}")
    from . import setlists as _sl
    _banks = (_sl.load(_sl.active_id()) or {}).get("presets") or []
    boot_progress.preset_done(bool(ok) or not any(_banks))              # setlist vide : rien à charger, on joue
    if _notify:
        _notify()
