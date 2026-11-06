# SPDX-License-Identifier: GPL-3.0-or-later
"""Accès fichiers configs-as-code (presets, JSON atomiques, ids sûrs) — extrait d'app.py (P3)."""
import contextlib
import os, json, glob, re, tempfile, time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("store")
log_presets = get("presets")


from . import preset_view as _PV
from .preset_view import (  # noqa: F401 — les noms d'avant, que tout le bridge lit en store.X
    FCB_SWITCHES, SERVICE_GEN, SERVICE_REC, SERVICE_ARR, SERVICE_ALL, DROPPED_TYPES,
    migrate_scene_branches, is_legacy_branch_mute, scene_branches, scene_lane_level, OUT_DEFAULT, LEGACY_LANES,
    _rich_chain, LANES_V, LEGACY_KEY, MIDI_ROLES, rich_chain, is_v2, midi_input_base, _parse_in, _norm_lane,
    _mirror_legacy, _lane_chain_blocks, _arr_blocks, _config_blocks, _guitar_blocks, _lanes_summary,
    _block_on_in_scene, lane_chain_sets, scene_lane_slice, state_id_for, write_lane_slice, assign_lane_state,
    _canon, ensure_lane_states, scene_lane_states, _IDENTITY_TYPES)

FCB_STOMPS = ["boost", "delay", "reverb", "tremolo", "whammy"]   # (legacy) types de la rangée haute



# ── chantier REC global (décision 2026-07-25, pattern « Global Blocks » Fractal) : le bloc
# Rec est PERMANENT (un par preset, non supprimable) et sa config est un SINGLETON partagé
# (config/recorder.json) — éditer le Rec dans n'importe quel preset le change PARTOUT. Seule
# l'assignation au pied (block.foot, claim 1-5) reste locale au preset. ──
RECORDER_CFG = os.path.join(C.CONFIG_DIR, "recorder.json")
# `mix` = garder AUSSI le mix stéréo complet quand on enregistre en multipiste (coche du bloc Rec,
# 2026-07-27). En mode « mix » le réglage n'a pas de sens : la prise EST le mix.
REC_DEFAULTS = {"in1": True, "in2": True, "usb": True, "mode": "mix", "mix": True}
# bloc Click (2e bloc permanent de la lane Recorder, chantier 2026-07-25) : même pattern singleton
CLICK_CFG = os.path.join(C.CONFIG_DIR, "click.json")
# "out" = sortie audio du click (pastille OUT de la lane Click) : "1" | "2" | "1-2" | "NONE",
# ou "auto" = suivre l'input map de la carte (rôle « click », sinon « monitors »).
# `beats` = NUMÉRATEUR (pulsations/mesure), `den` = DÉNOMINATEUR (l'unité de pulsation).
# Le BPM désigne toujours la noire : durée_pulsation = (4/den)·60/bpm (docs/arrangement.md §5.2).
# `groups` = groupement d'accents ([3,2,2] pour un 7/8) ; absent = accent sur la seule pulsation 1,
# c'est-à-dire le comportement historique. Cette config est le DÉFAUT — ce qui bat quand aucun
# arrangement ne tourne.
CLICK_DEFAULTS = {"level": -12, "beats": 4, "den": 4, "groups": None, "out": "auto"}
DENOMINATORS = (1, 2, 4, 8, 16)
CLICK_OUTS = ("1", "2", "1-2", "NONE")
# bloc COMPO (3e bloc permanent de la lane Global, docs/compo.md FIGÉ 2026-09-17) : même pattern
# singleton. `keep_s` = les N dernières secondes gardées par un tap ; `transcribe` = partition
# MusicXML calculée sur le rack ; `foot_person` = à QUI appartient le switch du pédalier du rack
# (None = la première entrée de la carte qui porte une personne) ; `persons` = par personne, les
# lanes qu'elle NE capture PAS (`off`) — absent = toutes ses lanes, pour qu'une lane neuve soit
# prise par défaut sans qu'on ait à revenir dans le tiroir.
COMPO_CFG = os.path.join(C.CONFIG_DIR, "compo.json")
COMPO_DEFAULTS = {"keep_s": 30, "transcribe": True, "foot_person": None, "persons": {}}
COMPO_KEEP = (15, 30, 60)


def load_compo_cfg():
    """Config GLOBALE du bloc Compo (docs/compo.md §2, §4). Les cibles « Follow Golem », elles,
    sont un état en mémoire (compo.py), jamais dans ce fichier."""
    try:
        d = json.load(open(COMPO_CFG))
    except Exception:
        d = {}
    return _clean_compo(d)


def _clean_compo(d, base=None):
    """Une config Compo propre : valeurs connues seulement ; ce qui manque ou ne vaut rien garde
    `base` (les défauts au load, la config en place au save)."""
    out = dict(base or COMPO_DEFAULTS)
    if not isinstance(d, dict):
        return out
    try:
        k = int(d.get("keep_s", 0))
        if k in COMPO_KEEP:
            out["keep_s"] = k
    except (TypeError, ValueError):
        pass
    if "transcribe" in d:
        out["transcribe"] = bool(d["transcribe"])
    if "foot_person" in d:
        fp = d.get("foot_person")
        out["foot_person"] = str(fp)[:64] if fp else None
    if isinstance(d.get("persons"), dict):
        persons = {}
        for pid, v in d["persons"].items():
            if not pid or not isinstance(v, dict):
                continue
            off = [str(x)[:80] for x in (v.get("off") or []) if x]
            if off:
                persons[str(pid)[:64]] = {"off": off}
        out["persons"] = persons
    return out


def save_compo_cfg(d):
    """Écrit la config globale Compo (clés partielles acceptées, validées comme au load)."""
    cur = load_compo_cfg()
    # une valeur hors table (keep_s 45) ne remplace pas la valeur en place : on nettoie AVANT d'écrire
    merged = _clean_compo({k: v for k, v in (d or {}).items() if k in ("keep_s", "transcribe", "foot_person", "persons")}, base=cur)
    _write_json_atomic(COMPO_CFG, merged, indent=1)
    return load_compo_cfg()


def load_click_cfg():
    """Config GLOBALE du métronome : {level dB, beats, out}. L'on/off est un état LIVE (Reaper)."""
    try:
        d = json.load(open(CLICK_CFG))
    except Exception:
        d = {}
    out = dict(CLICK_DEFAULTS)
    out.update({k: d[k] for k in CLICK_DEFAULTS if k in d})
    return out


def save_click_level(level):
    """Le VOLUME du click, écrit seul (tiroir du bloc Click, 2026-09-30 : « on ne l'entend pas assez »).
    Bornes du JSFX : −60…+6 dB. Rend la config. Le reste de click.json (mesure, sortie) n'est pas touché."""
    lv = max(-60.0, min(6.0, float(level)))
    try:
        d = json.load(open(CLICK_CFG))
    except Exception:
        d = {}
    d["level"] = round(lv, 1)
    _write_json_atomic(CLICK_CFG, d, indent=1)
    return load_click_cfg()


def click_out():
    """Sortie EFFECTIVE du click : le choix explicite de la pastille OUT, sinon l'input map de la carte."""
    sel = load_click_cfg().get("out")
    if sel in CLICK_OUTS:
        return sel
    from . import inputmap as inputmap_mod    # pas de cycle : inputmap n'importe que config
    return inputmap_mod.click_out()


def load_recorder_cfg():
    """Config GLOBALE du magnétophone : {in1,in2,usb,mode}. Défauts = le mix entendu."""
    try:
        d = json.load(open(RECORDER_CFG))
    except Exception:
        d = {}
    out = dict(REC_DEFAULTS)
    out.update({k: d[k] for k in REC_DEFAULTS if k in d})
    out.update({k: bool(v) for k, v in d.items() if re.fullmatch(r"in\d+", k)})   # in3, in4… (cartes à N entrées)
    if d.get("transcribe") in ("manual", "auto"):
        out["transcribe"] = d["transcribe"]
    out["count_in"] = _count_in(d.get("count_in"))
    return out


def _count_in(v):
    """Décompte avant une prise lancée au pied, en MESURES : 0 (aucun), 1 ou 2 (2026-09-21)."""
    try:
        return min(2, max(0, int(v)))
    except (TypeError, ValueError):
        return 0


def save_recorder_cfg(d):
    """Écrit la config GLOBALE du magnétophone depuis un dict (tiroir REC de Settings ▸ Mode, qui
    édite LA MÊME chose que le bloc Rec du Designer — décision 2026-09-08 : pas de config par
    mode). Clés inconnues ignorées ; rend la config écrite."""
    cfg = load_recorder_cfg()
    for k in [*(k for k in d if re.fullmatch(r"in\d+", k)), "usb", "mix"]:
        if k in d and d[k] is not None:
            cfg[k] = bool(d[k])
    if d.get("mode") in ("mix", "tracks", "tracks_di"):
        cfg["mode"] = d["mode"]
    if d.get("transcribe") in ("manual", "auto"):
        cfg["transcribe"] = d["transcribe"]
    if d.get("count_in") is not None:
        cfg["count_in"] = _count_in(d["count_in"])
    _write_json_atomic(RECORDER_CFG, cfg, indent=1)
    return cfg


def _rec_params(p):
    rb = next((b for b, _k in _foot_blocks(p or {}) if b.get("type") == "rec"), None)
    return (rb.get("params") or {}) if rb is not None else None


def save_recorder_cfg_from(p, prev=None):
    """Extrait la config des 2 blocs permanents de la lane Recorder & Click et la PERSISTE en
    global. Appelé AVANT migrate_config au save de preset, et au bake sandbox : une édition
    n'importe où devient la vérité partout. Renvoie la config Rec écrite (None si pas de bloc Rec
    — l'extraction du Click, elle, reste faite : les deux blocs sont INDÉPENDANTS).

    `prev` (le brouillon d'AVANT, même document) : seules les cases du Rec QUI ONT CHANGÉ montent dans la config
    globale — et rien si `prev` est un AUTRE preset (on en charge un, on ne l'édite pas). Régression du 2026-10-15
    au 2026-10-23 : les presets d'usine portent un Rec figé « IN 1 oui, IN 2 non » (la Volt d'alors : guitare sur
    IN 1) ; chaque écriture de brouillon ou sauvegarde de l'un d'eux le recopiait, et l'enregistreur n'armait plus
    IN 2 — la guitare, aujourd'hui. Prises muettes, guitare absente du Mix aussi (golem_perfrec filtre par entrée)."""
    cfg = None
    rb = next((b for b, _k in _foot_blocks(p or {}) if b.get("type") == "rec"), None)
    if rb is not None:
        cfg = load_recorder_cfg()
        pm = rb.get("params") or {}
        if prev is not None:
            same = isinstance(prev, dict) and prev.get("id") == (p or {}).get("id")
            old = _rec_params(prev) or {}
            pm = {k: v for k, v in pm.items() if same and old.get(k) != v}
        for k in [*(k for k in pm if re.fullmatch(r"in\d+", k)), "usb", "mix"]:
            if k in pm:
                cfg[k] = bool(pm[k])
        # « Transcribe takes » (docs/archive/tablature-study.md §12) : le réglage vit ICI, dans la config
        # du Rec, et pas dans un bloc Tablature — la transcription est une conséquence de
        # l'enregistrement, pas un truc que le rig FAIT pendant qu'on joue. Valeurs : manual
        # (défaut) | auto. « starred » attend que la note des prises existe (lot 6).
        if pm.get("transcribe") in ("manual", "auto"):
            cfg["transcribe"] = pm["transcribe"]
        if pm.get("rec_mode") in ("mix", "tracks", "tracks_di"):
            cfg["mode"] = pm["rec_mode"]
        if pm.get("count_in") is not None:
            cfg["count_in"] = _count_in(pm["count_in"])
        try:
            _write_json_atomic(RECORDER_CFG, cfg, indent=1)
        except OSError:
            pass
    # bloc Click : ses params (level/beats) ET la pastille OUT de la lane (config.rec.click_out).
    # La sortie est lue MÊME sans bloc dans le payload : elle vit sur la lane, pas sur le bloc.
    cb = next((b for b, _k in _foot_blocks(p or {}) if b.get("type") == "click"), None)
    co = ((p.get("config") or {}).get("rec") or {}).get("click_out")
    if cb is not None or co in CLICK_OUTS:
        ck = load_click_cfg()
        pm = (cb or {}).get("params") or {}
        if isinstance(pm.get("level"), (int, float)):
            ck["level"] = float(pm["level"])
        try:
            if 1 <= int(pm.get("beats", 0)) <= 32:
                ck["beats"] = int(pm["beats"])
        except (TypeError, ValueError):
            pass
        try:
            if int(pm.get("den", 0)) in DENOMINATORS:
                ck["den"] = int(pm["den"])
        except (TypeError, ValueError):
            pass
        # groupement : une liste d'entiers ≥1 dont la SOMME vaut le numérateur, sinon on n'en
        # met pas — on n'invente jamais un accent que personne n'a demandé.
        g = pm.get("groups")
        if isinstance(g, list) and g and all(isinstance(x, int) and x >= 1 for x in g):
            ck["groups"] = g if sum(g) == ck["beats"] else None
        elif g is not None:
            ck["groups"] = None
        if co in CLICK_OUTS:
            ck["out"] = co
        try:
            _write_json_atomic(CLICK_CFG, ck, indent=1)
        except OSError:
            pass
    # bloc Compo : ses params (keep_s, transcribe, foot_person, persons) — même contrat singleton.
    kb = next((b for b, _k in _foot_blocks(p or {}) if b.get("type") == "compo"), None)
    if kb is not None and isinstance(kb.get("params"), dict):
        try:
            save_compo_cfg(kb["params"])
        except OSError:
            pass
    return cfg


# ── LA FICHE ET LA MIGRATION PURES vivent dans bridge/preset_view.py (partagé avec golem.fm, docs/shell.md
# §4 bis). Ici : ce qui dépend de la MACHINE — l'input map de la carte, les singletons Rec/Click/Compo — et
# les mêmes noms qu'avant, pour les appelants.
def _imap():
    """L'input map de la carte active, sans I/O bloquante ; {} si elle n'est pas lisible (rôles par défaut)."""
    try:
        from . import inputmap
        return inputmap.current() or {}
    except Exception:
        return {}


def lanes_of(p):
    """La liste de lanes d'un preset, selon la carte branchée (preset_view.lanes_of)."""
    return _PV.lanes_of(p, _imap())


def tuner_input(preset):
    """L'ENTRÉE que l'accordeur écoute (lot 2, audit N lanes) : celle de la lane qui porte le bloc
    tuner — « posé dans une lane, il DÉSIGNE la source » (blocks-doctrine) — sinon In 1."""
    return tuner_source(preset)[0]


def tuner_source(preset):
    """(entrée, rôle, id d'accordage) de la lane écoutée par l'accordeur. L'ACCORDAGE (2026-10-08) est le
    paramètre `tuning` du bloc Tuner — un id de library/catalog/tunings.json ; "" = le défaut du rôle (bridge/tunings).
    Il choisit les cordes affichées sur /live — la détection, elle, reste chromatique."""
    try:
        lanes = lanes_of(preset) if preset else []
        for b, key in _foot_blocks(preset or {}):
            if isinstance(b, dict) and b.get("type") == "tuner":
                tid = str(((b.get("params") or {}).get("tuning")) or "")
                for L in lanes:
                    if L.get("key") == key:
                        return int(L.get("input") or 1), L.get("role") or "guitar", tid
        # pas de bloc tuner : la première lane À CORDES (un accordeur sert la guitare et la basse), sinon la
        # première lane. « In 1 » ne vaut que si une lane y est : avec la voix sur IN 1 et la guitare sur IN 2,
        # l'accordeur écoutait le micro.
        for L in [L for L in lanes if L.get("role") in ("guitar", "bass")] + lanes:
            if int(L.get("input") or 0) >= 1:
                return int(L["input"]), L.get("role") or "guitar", ""
    except Exception as _e:
        _swallowed(_e)
    return 1, "guitar", ""



def migrate_config(p):
    """La migration du document (preset_view.migrate : lanes, états, blocs service vers la lane config, blocs
    permanents posés) PUIS l'hydratation de ce qui appartient à la machine. Idempotent. Mute le preset EN PLACE et
    le renvoie. Point de passage unique : appelé au load ET au save (routes_content) — les vieux presets sont
    remontés en mémoire pour tous les consommateurs sans réécriture de masse.
    Le bloc Rec permanent est HYDRATÉ depuis la config globale (chantier REC) — au save, l'extraction
    save_recorder_cfg_from passe AVANT : l'hydratation relit ses valeurs."""
    from . import genres as _genres
    from . import option_renames
    option_renames.apply(p)                      # étiquettes de choix renommées au catalogue (Tape Delay, catalogue 31)
    _PV.migrate(p, _imap(), _genres.migrate_styles)
    if not isinstance(p, dict):
        return p
    rec = p["config"]["rec"]
    rb = next(b for b in rec["blocks"] if isinstance(b, dict) and b.get("type") == "rec")
    if not os.path.exists(RECORDER_CFG) and rb.get("params"):
        save_recorder_cfg_from(p)              # seed : 1re rencontre d'une config Rec legacy -> devient la globale
    g = load_recorder_cfg()
    # ⚠ REMPLACEMENT, pas fusion (correctif 2026-07-27). L'ancien `{**(rb.get("params") or {}), …}`
    # conservait les clés du preset non listées ici — `mix` notamment — de sorte qu'une valeur
    # figée sur le disque survivait à l'hydratation et pouvait ensuite REMONTER dans la config
    # globale. Le bloc Rec est un SINGLETON : ses paramètres sont ceux de config/recorder.json,
    # point. Rien de ce que porte un preset ne doit pouvoir les contredire.
    rb["params"] = {**{k: v for k, v in g.items() if re.fullmatch(r"in\d+", k)},
                    "in1": g["in1"], "in2": g["in2"], "usb": g["usb"],
                    "rec_mode": g["mode"], "mix": g["mix"], "count_in": g.get("count_in", 0),
                    **({"transcribe": g["transcribe"]} if g.get("transcribe") in ("manual", "auto") else {})}
    # bloc Click PERMANENT (même contrat que le Rec : config globale, foot local)
    cb = next(b for b in rec["blocks"] if isinstance(b, dict) and b.get("type") == "click")
    ck = load_click_cfg()
    cb["params"] = {**(cb.get("params") or {}), "level": ck["level"], "beats": ck["beats"]}
    rec["click_out"] = click_out()          # la pastille montre la sortie EFFECTIVE (auto résolu)
    # bloc Compo PERMANENT (docs/compo.md §2) : config globale, foot local — REMPLACEMENT des
    # params comme pour le Rec (un preset ne contredit jamais le singleton).
    kb = next(b for b in rec["blocks"] if isinstance(b, dict) and b.get("type") == "compo")
    kb["params"] = load_compo_cfg()
    from . import capture_module
    capture_module.hydrate(p)
    return p




def all_blocks(p):
    """TOUS les blocs d'un preset, avec leur lane : lanes de signal (v2 : la liste ; legacy :
    guitar pre/branches/post, voice.chain, keys.chain) puis lanes config (gen/rec/arr). Rend (bloc, lane)."""
    if is_v2(p):
        for L in lanes_of(p):
            for b in _lane_chain_blocks(L["chain"]):
                yield b, L["id"]
        cfg = p.get("config") or {}
        for lane in ("gen", "rec", "arr"):
            for b in (cfg.get(lane) or {}).get("blocks") or []:
                yield b, lane
        return
    g = p.get("guitar") or {}
    for b in g.get("pre") or []:
        yield b, "guitar"
    for br in ((g.get("split") or {}).get("branches") or []):
        for b in br.get("blocks") or []:
            yield b, "guitar"
    for b in g.get("post") or []:
        yield b, "guitar"
    for lane in ("voice", "keys"):
        for b in (p.get(lane) or {}).get("chain") or []:
            yield b, lane
    cfg = p.get("config") or {}
    for lane in ("gen", "rec", "arr"):
        for b in (cfg.get(lane) or {}).get("blocks") or []:
            yield b, lane


def duplicate_block_ids(p):
    """Les ids de blocs portés par PLUSIEURS blocs (toutes lanes confondues). Scènes, potards de
    scène, cues d'arrangement et blocs par morceau adressent les blocs par id, à plat : un doublon
    est une commande ambiguë, et la compile le refuse (audit 2026-09-08 §1)."""
    seen, dupes = {}, []
    for b, lane in all_blocks(p):
        bid = b.get("id") if isinstance(b, dict) else None
        if not bid:
            continue
        if bid in seen and bid not in dupes:
            dupes.append(bid)
        seen[bid] = lane
    return sorted(dupes)


def lane_branch_ids(p):
    """(id de branche, id de lane) pour toutes les lanes de signal — v2 : la liste ; legacy : le split
    de la guitare seulement."""
    if is_v2(p):
        for L in lanes_of(p):
            for br in (((L.get("chain") or {}).get("split") or {}).get("branches") or []):
                if isinstance(br, dict) and br.get("id"):
                    yield str(br["id"]), L["id"]
        return
    for br in (((p.get("guitar") or {}).get("split") or {}).get("branches") or []):
        if isinstance(br, dict) and br.get("id"):
            yield str(br["id"]), "guitar"


def duplicate_branch_ids(p):
    """Les ids de branches portés par PLUSIEURS lanes. Le mute par branche d'une scène
    (`scene.branches[<id>]`, scene_bake._lane_muted) est cherché à plat, toute la scène : deux lanes à
    split sorties du constructeur de golem.fm portaient toutes deux `lane-a`/`lane-b`, et couper la
    branche claire de la guitare coupait aussi la branche A de la basse (retour golem.fm,
    2026-09-14). Même règle que duplicate_block_ids : un doublon est une commande ambiguë."""
    seen, dupes = {}, []
    for bid, lane in lane_branch_ids(p):
        if bid in seen and seen[bid] != lane and bid not in dupes:
            dupes.append(bid)
        seen.setdefault(bid, lane)
    return sorted(dupes)


def _inputs_summary(p):
    return _PV._inputs_summary(p, _imap())


def _chain_has_volume(g):
    """Un bloc `volume` quelque part dans cette chaîne (pre, post ou branches du split) ?"""
    if not isinstance(g, dict):
        return False
    branches = [x for br in ((g.get("split") or {}).get("branches") or []) for x in (br.get("blocks") or [])]
    return any(isinstance(b, dict) and b.get("type") == "volume"
               for b in list(g.get("pre") or []) + list(g.get("post") or []) + branches)


def ensure_volume(preset):
    """Utilitaire SYSTÈME : garantit UN bloc volume (master, cible de la pédale EXP) dans la chaîne guitare.
    Jamais affiché dans le Designer, mais nécessaire au rig. Placé en fin de POST si split MERGE (après la
    somme), sinon fin de PRE (linéaire/fanout : la scène ignore post). Idempotent. Mute le preset en place."""
    # v2 (lot 3) : la lane guitare de la LISTE (la clé legacy n'est qu'un miroir, regénéré) ; sinon la 1re lane
    # ⚠ BONNE FORME, MAUVAISE NATURE (2026-10-07, Paper Kite) : la lane visée était « id == guitar, sinon la
    # PREMIÈRE lane » — or les lanes s'appellent `guitar-1` depuis les N lanes, et le Designer les retrie selon
    # les entrées de la carte. Voix en tête : on ne regardait QUE la voix, on y ajoutait un second
    # `volume-sys`, la compile refusait les ids dupliqués, l'audition échouait sans écrire la sandbox — et le
    # rechargement de la page rouvrait le document d'AVANT (un patch). On cherche donc le volume dans TOUTES
    # les lanes, et la cible se choisit par le RÔLE, pas par la position.
    if is_v2(preset):
        lanes = [L for L in preset["lanes"] if isinstance(L, dict)]
        if any(_chain_has_volume(rich_chain(L.get("chain"))) for L in lanes):
            return preset
        g = next((L for L in lanes if L.get("id") == "guitar"), None) \
            or next((L for L in lanes if not L.get("midi") and (L.get("role") or L.get("in_role")) == "guitar"), None) \
            or next((L for L in lanes if not L.get("midi")), None)
        if g is None:
            return preset
        g["chain"] = rich_chain(g.get("chain"))
        g = g["chain"]
    else:
        g = preset.get("guitar")
    if not isinstance(g, dict):
        return preset
    if _chain_has_volume(g):
        return preset
    vol = {"type": "volume", "id": "volume-sys"}
    sp = g.get("split") or {}
    if sp.get("branches") and sp.get("mode") != "fanout":
        g.setdefault("post", []).append(vol)          # merge : master après la somme
    else:
        g.setdefault("pre", []).append(vol)           # linéaire/fanout : fin de chaîne
    return preset


def _foot_blocks(p):
    """(bloc, clé de lane) de tous les blocs assignables au pied (preset_view._foot_blocks)."""
    return _PV._foot_blocks(p, _imap())


def _role_by_key(p):
    return _PV._role_by_key(p, _imap())


def _scene_claims(p):
    """Claims de la RANGÉE SCÈNES (doctrine 2026-07-20, foot_scene_claim) : blocs spéciaux
    (tuner, whammy-dt, backing-track) assignés aux switches 1-5 — ils REMPLACENT ce slot de
    scène (tuile Live + appui FCB routé vers le service). -> {sw: [{id,type}]}"""
    out = {}
    role_of = _role_by_key(p)
    for b, _k in _foot_blocks(p):
        f = b.get("foot")
        if isinstance(f, int) and 1 <= f <= 5 and b.get("type"):
            # role + label + variant (2026-09-15) : un service seul sur la rangée des scènes prend la
            # PILE, comme les stomps — l'accordeur d'une lane guitare dit GTR, le Click dit SVC
            c = {"id": b.get("id"), "type": b.get("type"), "role": role_of.get(_k) or "guitar",
                 "label": b.get("label") or None, "variant": b.get("variant") or None}
            if b.get("type") == "midi-pedal":     # la tuile Live nomme la pédale et lit son état par ref
                c["ref"], c["label"] = b.get("ref"), b.get("label")
            out.setdefault(f, []).append(c)
    return out


# ── L'ESPÈCE D'UN SWITCH RÉSERVÉ (2026-09-21) ────────────────────────────────────────────────
# Un switch de la rangée des scènes pris par un bloc est soit un ON/OFF (Rec, Click, Tuner, Rec +
# Backing = la prise), soit piloté par des GESTES (backing seul, sample, drums, standard,
# arrangement, compo : tap / double-tap / appui long, donc besoin des deux fronts). C'est CETTE
# règle que le compilateur de la puce importe (tools/fcb/gen_uno2_syx.py) pour décider quels
# switches passent en `effect` (diode on/off, aucun relâchement) — une seule définition, celle du
# rack, comme pour `rig.looper_enabled` : une puce flashée en désaccord avec le rack qui la pilote
# est la pire des pannes, celle qui ne se voit qu'au pied.
GESTURE_CLAIMS = frozenset({"backing-track", "sample", "drums", "standard", "arrangement", "compo", "looper"})


def claim_species(claims):
    """"toggle" | "gesture" | None (rien de réservé) pour la liste de claims d'UN switch."""
    types = {c.get("type") for c in (claims or []) if isinstance(c, dict)}
    if not types:
        return None
    if {"rec", "backing-track"} <= types:
        return "toggle"                       # la PRISE : un seul geste (docs/blocks-doctrine.md)
    return "gesture" if types & GESTURE_CLAIMS else "toggle"


def toggle_claim_switches(p, select_switch=1):
    """Les switches 1-5 de ce preset qui sont de purs ON/OFF — ceux qui peuvent porter une diode
    d'état. JAMAIS le switch de sélection : son appui long (saisie d'un n° de slot) a besoin du
    relâchement, qu'un `effect` n'émet pas."""
    return sorted(sw for sw, cl in _scene_claims(p or {}).items()
                  if sw != select_switch and claim_species(cl) == "toggle")


def rec_sources(p, force=()):
    """Sources d'enregistrement (coches IN 1 / IN 2 / USB + mode mix/tracks/tracks_di).
    Chantier REC 2026-07-25 : la vérité est GLOBALE (config/recorder.json) — le preset passé en
    argument n'est gardé que pour la compat d'appel (les blocs Rec sont hydratés depuis la même
    source). Publié en presets/.perfsrc.json au recall ; golem_perfrec filtre ses receives par
    entrée (Sandbox #Input 1/2 -> in1/in2, 3+ -> usb ; Backing/Looper toujours inclus)."""
    g = load_recorder_cfg()
    out = {"in1": g["in1"], "in2": g["in2"], "usb": g["usb"], "mode": g["mode"], "mix": g["mix"]}
    # LOT 4 : une clé PAR ENTRÉE PHYSIQUE du preset (`in3`, `in4`…), à plat — golem_perfrec lit
    # `in<N>` d'abord, sinon le triplet historique (1→in1, 2→in2, ≥3→usb). Les entrées 1 et 2
    # suivent les coches du bloc Rec ; les autres lanes audio s'enregistrent (rien ne permet
    # encore de les décocher — la feuille du Rec reste à trois cases) ; la lane MIDI suit `usb`.
    with contextlib.suppress(Exception):
        midi_ins = []
        for L in lanes_of(p or {}):
            if L.get("disabled"):
                continue
            n = int(L["input"])
            if L["midi"]:
                out[f"in{n}"] = bool(g["usb"])
                midi_ins.append(n)
            elif n == 1:
                out["in1"] = bool(g["in1"])
            elif n == 2:
                out["in2"] = bool(g["in2"])
            else:
                out.setdefault(f"in{n}", bool(g.get(f"in{n}", True)))   # la case de l'entrée N, si elle existe
        if midi_ins:
            out["midi_inputs"] = midi_ins                   # pour disk.py : ce ne sont pas des entrées audio
    # UN RIFF ENREGISTRE SES LANES (docs/compo.md) : `force` = les entrées qu'il a déclarées ("usb" | "1"…), prises
    # quoi que disent les cases du Rec — un riff de clavier ou de batterie sur USB n'attend pas qu'on coche USB
    for v in force or ():
        if v == "usb":
            out["usb"] = True
            for n in out.get("midi_inputs") or ():
                out[f"in{n}"] = True
        elif str(v).isdigit():
            out[f"in{v}"] = True
    return out


def _foot_summary(p):
    """Résumé « pédalier » d'un preset (preset_view._foot_summary), selon la carte branchée."""
    return _PV._foot_summary(p, _imap())


def load_presets():
    out = []
    for path in sorted(glob.glob(os.path.join(C.PRESETS_DIR, "*.json"))):
        if os.path.basename(path).startswith("."):
            continue
        try:
            p = json.load(open(path))
        except Exception:
            continue
        if not isinstance(p, dict):        # ignore les .json qui ne sont pas des presets (ex. dump de calibration)
            continue
        # ⚠ PLUS DE RAFRAÎCHISSEMENT (docs/patches.md §15) : un patch est COPIÉ à l'assignation,
        # rien ne se propage. Ce qui est dans le preset EST le son du morceau — le résumé le dit
        # donc tel quel, sans aller chercher une « vraie » version ailleurs.
        # …mais tel que le rack le LIT : la même migration idempotente que load_preset (lanes dérivées,
        # états de lane) — sans elle, /live ne voyait aucun état tant que le fichier n'avait pas été resauvé
        out.append(preset_summary(migrate_config(p)))
    return out


def preset_summary(p):
    """La fiche COMPACTE d'un preset déjà migré — ce que /api/presets sert (preset_view.preset_summary)."""
    return _PV.preset_summary(p, _imap())


# ── L'ESSAI D'UN PATCH EST UN PRESET COURANT (décision 2026-09-12) ─────────────────────
# Avant : un patch essayé SONNAIT (le rig le jouait) mais n'existait ni pour /live ni pour le pied,
# qui regardent tous deux « le preset courant » — c'est-à-dire le dernier RAPPELÉ. Mesuré : Hammer
# en sandbox, /live affichait Velvetine en scène E (que Hammer n'a pas), stomps tous éteints, et un
# coup de pied envoyait un ordre à un rig qui n'était plus là.
# Le remède n'est pas un second état « essai » que cinq surfaces devraient apprendre : c'est que
# la sandbox devienne un preset servi sous un id RÉSERVÉ. Alors do_recall, le pied, la livemap,
# boot_recall et Live marchent sans savoir que c'est un essai. Pas de fichier presets/<id>.json :
# le catalogue (load_presets) ne le voit jamais, rien ne peut l'y sauver.
SANDBOX_TRY_ID = "sandbox-try"


def _load_sandbox_try():
    sb = _read_json(os.path.join(C.PRESETS_DIR, ".sandbox.json"), {}) or {}
    p = sb.get("preset")
    if not isinstance(p, dict):
        return None
    p = dict(p)
    p["id"] = SANDBOX_TRY_ID                 # le Designer y écrit `nouveau-preset` : l'id courant est celui-ci
    return migrate_config(p)                 # comme un preset du disque : lanes dérivées, états de lane


# ── LE KARAOKÉ EST UN PRESET VOLATIL (docs/karaoke.md, 2026-10-06) ─────────────────────────────
# Même patron que l'essai : un id RÉSERVÉ servi depuis un dotfile de presets/ (volatil, gitignoré), que
# load_preset rend comme un preset — do_recall, le pied et /live le jouent sans savoir que c'est un
# karaoké. Pas de fichier presets/<id>.json : le catalogue ne le voit jamais. Écrit par bridge/karaoke.py.
KARAOKE_ID = "karaoke"
KARAOKE_FILE = ".karaoke.json"


def _load_karaoke():
    p = _read_json(os.path.join(C.PRESETS_DIR, KARAOKE_FILE), {}) or {}
    if not isinstance(p.get("lanes"), list):
        return None
    return migrate_config(dict(p, id=KARAOKE_ID))


def _load_patch_preset(patch_id):
    """UN PATCH JOUÉ COMME UN PRESET (docs/patches.md §6). Si le Designer ÉDITE ce patch en ce
    moment, c'est son brouillon qui fait foi — comme pour l'essai : sinon un changement de scène au pied
    reconstruirait le son depuis une sauvegarde en retard sur l'écran. Sinon, le fichier du patch."""
    sb = _read_json(os.path.join(C.PRESETS_DIR, ".sandbox.json"), {}) or {}
    p = sb.get("preset")
    if isinstance(p, dict) and str(((p.get("__patch") or {}).get("id") or "")) == patch_id:
        p = dict(p, id="patch:" + patch_id, kind="patch")
        return migrate_config(p)
    try:
        from . import patches as P
        doc = P.get_patch(patch_id)
        p = P.as_preset(doc) if doc else None
        return migrate_config(p) if p else None
    except Exception as e:
        log_presets.warning(f"patch {patch_id} illisible comme preset : {e}")
        return None


def load_preset(pid):
    """Charge un preset ; None si absent OU corrompu (appelé aussi depuis le thread FCB :
    une exception ici tuerait la session aseqdump — audit 2026-07-07 P1).
    pid passe par _safe_id : anti path-traversal (S-P2-2), cohérent avec l'écriture."""
    if not pid:
        return None                          # emplacement de bank LIBRE (None) : pas un preset
    if pid == SANDBOX_TRY_ID:
        return _load_sandbox_try()           # l'essai d'un patch : un preset comme les autres
    if pid == KARAOKE_ID:
        return _load_karaoke()               # le karaoké de golem.fm : un preset volatil
    if str(pid).startswith("patch:"):
        return _load_patch_preset(str(pid)[len("patch:"):])
    path = os.path.join(C.PRESETS_DIR, f"{_safe_id(pid)}.json")
    try:
        if not os.path.exists(path):
            return None
        # ⚠ ICI PASSAIT LE RAFRAÎCHISSEMENT DES PATCHES. Il est SUPPRIMÉ (docs/patches.md §15) :
        # un morceau ne change plus jamais parce qu'on a touché un patch ailleurs. C'était le
        # seul endroit du code capable de modifier un son que personne ne regardait.
        return migrate_config(json.load(open(path)))
    except Exception as e:
        log_presets.warning(f"{pid}.json illisible : {e}")
        return None


def _read_json(path, default=None):
    try:
        return json.load(open(path))
    except Exception as e:
        # fichier ABSENT = cas normal (config pas encore créée) : silence. Mais un fichier
        # PRÉSENT et illisible (JSON corrompu, coupure en pleine écriture) mérite une trace —
        # sinon le default masque une perte de données (audit 2026-08-12).
        if os.path.exists(path):
            log.warning(f"{path} existe mais illisible ({e}) — valeur par défaut servie")
        return default


def _write_json_atomic(path, data, indent=2, newline=False):
    """tmp + os.replace : LE chemin d'écriture JSON du bridge. Sur un rack, la coupure
    secteur est un cas normal — une écriture directe laisse un fichier tronqué (audit
    2026-08-12 : la moitié des writers de config ne passaient pas par ici). `indent`/
    `newline` préservent le format historique de chaque fichier (diffs propres)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    # encoding explicite : sous Windows sans PYTHONUTF8, open() écrit en cp1252 et « — » rend le JSON illisible
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        if newline:
            f.write("\n")
        # FSYNC (audit 2026-10-15) : sans lui, le rename peut atteindre le disque AVANT les données — après une
        # coupure, la config est un fichier vide sous le bon nom. Quelques ms : ces fichiers s'écrivent à un geste.
        f.flush()
        os.fsync(f.fileno())
    # ⚠ WINDOWS : une cible ouverte ailleurs refuse os.replace — bridge/winfs.py réessaie (2026-10-03)
    from . import winfs
    winfs.replace(tmp, path)
    # toute mutation du catalogue (install T3K, import, IR, suppression) programme
    # un push débouncé de la tone library vers golem.fm — no-op si non appairé
    if os.path.abspath(path) == os.path.abspath(C.CATALOG):
        try:
            from . import tones_sync
            tones_sync.schedule()
        except Exception as _e:
            _swallowed(_e)


def _safe_id(s):
    """Un id de fichier sûr depuis un nom. TRANSLITTÉRÉ d'abord (audit 2026-09-13, m4) : « Été »
    donnait « t » et « 日本 » donnait « untitled » — deux presets différents, un seul fichier,
    écrasement silencieux. NFKD retire les accents ; ce qui reste hors ASCII tombe, et un nom qui
    n'a plus rien garde son empreinte pour ne pas rejoindre tous les autres sous « untitled »."""
    import unicodedata, hashlib
    raw = str(s or "")
    txt = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    out = re.sub(r"[^a-z0-9\-_]", "", txt.lower().replace(" ", "-"))
    if out:
        return out
    return "untitled" if not raw.strip() else "untitled-" + hashlib.sha1(raw.encode()).hexdigest()[:6]


def _list_dir_json(d):
    out = []
    for path in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(path).startswith("."):
            continue
        j = _read_json(path)
        if j:
            out.append(j)
    return out


def brand_str(v):
    """Une MARQUE est une chaîne. TONE3000 rend parfois `makes: [{"name": …}]`, et la valeur a été
    stringifiée telle quelle à la synchro initiale (2026-07-19) : « {'name': 'Marshall 1960TV 4x12'} »
    affiché comme marque, et poussé à golem.fm — six packs de leur miroir (mesuré par eux le
    2026-09-12). dict → name ; liste → le premier name ; repr de dict → relu ; sinon la chaîne."""
    if isinstance(v, dict):
        return str(v.get("name") or v.get("brand") or "").strip()
    if isinstance(v, (list, tuple)):
        return brand_str(v[0]) if v else ""
    s = str(v or "").strip()
    if s.startswith("{") or s.startswith("["):
        import ast
        try:
            return brand_str(ast.literal_eval(s))
        except (ValueError, SyntaxError):
            return ""
    return s


def delete_preset(pid):
    """Supprime un preset : le fichier, ses emplacements de banks LIBÉRÉS (jamais retirés,
    setlists.forget_preset), le preset COURANT oublié s'il l'était (sinon boot_recall échoue en
    silence au prochain démarrage — audit 2026-09-13, m5), et les liens de morceau repoussés à
    golem.fm hors du fil d'appel. Rend {deleted, banks_freed}. Un id absent n'est PAS une erreur :
    {deleted: False} — le but (« ce preset n'existe plus ici ») est atteint.
    Corps partagé par `DELETE /api/preset/{pid}` et le job `preset-delete` (patches.md §21)."""
    import threading as _threading
    sid = _safe_id(pid)
    path = os.path.join(C.PRESETS_DIR, f"{sid}.json")
    if not os.path.exists(path):
        return {"deleted": False, "banks_freed": 0}
    os.remove(path)
    from . import golemfm, setlists as _sl
    from .state import state as _state
    freed = _sl.forget_preset(sid)
    if _state.preset_id == sid:
        with contextlib.suppress(OSError):
            os.remove(os.path.join(C.PRESETS_DIR, ".live.json"))
        _state.preset_id = None; _state.preset_name = None; _state.song = None
        _state.touch()
    _threading.Thread(target=golemfm.push_song_links, daemon=True).start()
    return {"deleted": True, "banks_freed": freed}
