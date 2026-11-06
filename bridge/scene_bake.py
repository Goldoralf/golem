# SPDX-License-Identifier: GPL-3.0-or-later
"""
Shim ancien modèle -> modèle « paths » (pour le SANDBOX).

Le Designer parle encore l'ancien schéma (`guitar.lanes|chain` + `voice.chain` + `scenes`).
Le sandbox tourne sur le NOUVEAU moteur (rig.py / compile_rig / golem_rig, paths+splits).
Ce module convertit `(preset ancien, scène active) -> preset schéma paths`, en BAKANT la scène
(bypass par bloc, mute de lane, voix on/off, niveau guitare). Le résultat repart ensuite tel quel
dans `compile_rig.compile_preset` (résolution NAM/IR + cœur + validation routing déjà éprouvés).

Convention d'entrées FIXES (décidée) : guitare -> In1/Out1, voix -> In2/Out2.

Pur Python, testable sans Reaper.
"""
import copy
from .golog import swallowed as _swallowed


# ---- entrées FIXES du sandbox (In1 = guitare, In2 = voix, In3 = clavier MIDI) ----
GUITAR_IN, GUITAR_OUT = 1, 1
VOICE_IN, VOICE_OUT = 2, 2
KEYS_IN, KEYS_OUT = 3, 3     # In3 = lane Keys (contrôleur MIDI GoleM USB -> Vital), pas une entrée audio
OUT_DEFAULT = "1-2"          # sortie par défaut d'une chaîne = les 2 baffles (OUT 1/2)
LANE_MUTE_DB = -150.0        # une lane coupée dans une scène : son niveau au plancher (D_VOL ≈ 3e-8), jamais retirée


def _out_sel(preset, input_key):
    """Choix de sortie d'une chaîne, réglé dans le Designer : '1' | '2' | '1-2' (défaut)."""
    return ((preset.get("out") or {}).get(input_key)) or OUT_DEFAULT


def _chain_name(preset, input_key, default):
    """Nom éditable de la chaîne (Designer), sinon défaut Guitare/Voix."""
    return ((preset.get("names") or {}).get(input_key)) or default


def _chain_disabled(preset, key):
    """Chaîne désactivée si son entrée OU sa sortie est NONE (réglé dans le Designer)."""
    ins = (preset.get("in") or {}).get(key) or key
    out = (preset.get("out") or {}).get(key) or OUT_DEFAULT
    return ins == "NONE" or out == "NONE"


def _scene(preset, scene_id):
    """La scène active (par id), sinon la 1re, sinon un défaut permissif (voix ON)."""
    scenes = preset.get("scenes") or []
    if scene_id is not None:
        for s in scenes:
            if s.get("id") == scene_id:
                return s
    return scenes[0] if scenes else {"voice": True, "blocks": {}, "levels": {}, "branches": {}}


def _to_chain(guitar):
    """Normalise `guitar` en {pre, split, post} (le modèle « chaîne + split à un point »).
    Accepte le NOUVEAU format (pre/split/post) OU l'ancien (chain linéaire | lanes = split merge dès le début)."""
    g = guitar or {}
    if "pre" in g or "split" in g:                        # nouveau format
        return {"pre": g.get("pre") or [], "split": g.get("split"), "post": g.get("post") or []}
    if g.get("lanes"):                                    # ancien : lanes = split merge @début
        branches = [{"id": L.get("id") or f"b{i + 1}", "blocks": L.get("blocks") or []}
                    for i, L in enumerate(g["lanes"])]
        return {"pre": [], "split": {"mode": "merge", "branches": branches,
                                     "gain": (g.get("merge") or {}).get("gain", -3)},
                "post": g.get("post") or []}
    return {"pre": g.get("chain") or [], "split": None, "post": []}   # ancien : linéaire


_DEFAULTS = {"key": None, "map": {}}


def _param_defaults(btype):
    """{param id: défaut} d'un type de bloc, depuis le catalogue (C.EFFECTS), en cache par mtime."""
    import json, os
    from . import config as C
    try:
        key = (C.EFFECTS, os.path.getmtime(C.EFFECTS))
    except OSError:
        return {}
    if _DEFAULTS["key"] != key:
        try:
            data = json.load(open(C.EFFECTS)) or {}
        except (OSError, ValueError):
            data = {}
        _DEFAULTS["map"] = {e.get("type"): {p["id"]: p.get("default") for p in e.get("params") or [] if p.get("id")}
                            for e in data.get("effects") or [] if e.get("type")}
        _DEFAULTS["key"] = key
    return _DEFAULTS["map"].get(btype) or {}


def touched_params(preset):
    """{bloc id: {param ids réglés dans AU MOINS une scène}} — l'ensemble des potards qu'une scène a
    touchés quelque part dans le preset. Un potard touché en C doit être ÉCRIT dans chaque scène
    (base ou défaut), sinon le plugin garde la valeur de la scène précédente : mesuré le 2026-09-14
    (clean-boost à 2,6 dB en scène A, réglé en C, A ne disant rien). Un potard jamais touché n'est
    pas écrit : rien ne change pour lui."""
    out = {}
    for sc in preset.get("scenes") or []:
        for bid, ov in ((sc or {}).get("params") or {}).items():
            if isinstance(ov, dict):
                out.setdefault(bid, set()).update(k for k in ov if k)
    return out


def _bake_block(b, scene_blocks, scene_params=None, touched=None):
    """Copie d'un bloc avec l'état de la scène appliqué (bypass + potards).
    scene.blocks[id] absent ou None -> clé par type, puis bypass de base ; ==True -> forcé ON ; ==False -> forcé OFF.
    scene.params[id] = overrides de potards fusionnés PAR-DESSUS la base (block.params).
    `touched[id]` = potards réglés dans une autre scène : s'ils manquent ici, on écrit la base ou
    le défaut du catalogue — une scène sans réglage RAMÈNE le potard, elle ne laisse pas le
    précédent (docs/live-engine.md : une scène est un état, pas une différence)."""
    b = copy.deepcopy(b)
    bid, btype = b.get("id"), b.get("type")
    # une valeur `None` vaut « pas de clé » (même règle que preset_view._block_on_in_scene) : sinon
    # `not None` coupait le bloc pendant que l'écran et les diodes le montraient allumé
    if scene_blocks.get(bid) is not None:
        b["bypass"] = not scene_blocks[bid]
    elif scene_blocks.get(btype) is not None:
        # clé par TYPE (créateur IA + page Foot, sémantique stomp : vaut pour tous les blocs du type).
        # Ignorée jusqu'ici -> la wah RIOT restait active en scènes B/C/D (bug repéré 2026-07-08).
        b["bypass"] = not scene_blocks[btype]
    elif "bypass" in b:
        b["bypass"] = bool(b["bypass"])
    ovr = (scene_params or {}).get(bid)
    if ovr:
        b["params"] = {**(b.get("params") or {}), **ovr}   # base <- override scène
    need = (touched or {}).get(bid)
    if need:
        cur = dict(b.get("params") or {})
        dflt = _param_defaults(btype)
        for k in need:
            if k not in cur and dflt.get(k) is not None:
                cur[k] = dflt[k]
        if cur:
            b["params"] = cur
    return b


def _bake_blocks(blocks, scene_blocks, scene_params=None, touched=None):
    return [_bake_block(b, scene_blocks, scene_params, touched) for b in (blocks or [])]


def _lane_muted(lane, scene_lanes):
    """Mute effectif d'une lane pour la scène (override de scène prioritaire sur le mute de base)."""
    lid = lane.get("id")
    if lid in scene_lanes:
        return bool((scene_lanes[lid] or {}).get("mute"))
    return bool(lane.get("mute"))


def _lane_path(lane, preset, sc, union=False):
    """Traduit UNE lane (pre + split{merge|fanout} + post) + scène -> un path (None si tout mute).
    LOT 1 (audit 2026-09-08) : l'ex-`_guitar_path`, promu pour TOUTES les lanes — la voix et les
    claviers ont désormais le split, le mute par branche et le NIVEAU DE SCÈNE (leur `scene.levels`
    était écrit et jamais appliqué). `scene.lanes[lane.id].level` a priorité sur le legacy
    `scene.levels[level_key]`.

    `union=True` (moteur live) : TOUTES les branches sont posées quoi qu'il arrive, chacune portant son
    `mute` de scène (scene.branches[id].mute, ex-`lanes`) — le mute devient un D_MUTE de piste, PAS un retrait. La
    topologie ne dépend donc plus de la scène (mêmes pistes/FX d'une scène à l'autre) : un changement de
    scène = bascule d'état sans rebuild (cf. docs/live-engine.md). `union=False` (défaut, ex. usages
    hors-live) : ancien comportement — branches mutées RETIRÉES, collapse à 1 branche, None si tout mute."""
    g = lane["chain"]
    sblk = sc.get("blocks") or {}
    sparams = sc.get("params") or {}
    touched = touched_params(preset)
    from .store import scene_branches
    slanes = scene_branches(sc)
    pre = _bake_blocks(g["pre"], sblk, sparams, touched)
    # NIVEAU DE SCÈNE : `scene.lanes[id].level` (le modèle neuf, toutes lanes) ; sinon le legacy
    # `scene.levels.guitar` — et SEULEMENT la guitare : `levels.voice/keys` existent sur disque
    # (Velvetine : -4/-8/-6 dB, écrits par les dépôts de patch) sans avoir jamais sonné, et aucune
    # feuille ne permet encore de les régler. Les appliquer d'un coup baisserait la voix sur scène
    # sans moyen de la remonter : ça attend le Designer du lot 3. Rejeu identique garanti.
    lvl = ((sc.get("lanes") or {}).get(lane["id"]) or {}).get("level")
    level_db = lvl if lvl is not None else ((sc.get("levels") or {}).get("guitar") if lane["id"] == "guitar" else None)
    # LANE COUPÉE DANS LA SCÈNE (docs/band-scenes.md §4, écran 3 — 2026-09-15) : `scene.lanes[id].mute`.
    # Pas de retrait de path — la topologie du moteur live ne doit pas dépendre de la scène — mais le
    # NIVEAU de la lane au plancher : le même D_VOL de piste que le niveau de scène, donc une bascule
    # d'état sans rebuild, et une lane qui revient à son niveau à la scène suivante.
    if ((sc.get("lanes") or {}).get(lane["id"]) or {}).get("mute") is True:
        level_db = LANE_MUTE_DB
    pid, name, lin, lout, out_sel = lane["id"], lane["name"], lane["input"], lane["out"], lane["out_sel"]
    split = g.get("split")

    def finish(path):
        if level_db is not None:
            path["level"] = level_db
        if lane.get("midi"):
            path["midi"] = True
            path["midi_role"] = lane.get("role")            # drums-kit lot 2 : le contrôleur se choisit par RÔLE…
            path["in_sel"] = lane.get("in_sel")             # …et par PORT (usbN) quand la lane en nomme un
        if lane.get("stereo"):
            path["stereo"] = True
        return path

    if not split:                                         # LINÉAIRE
        # ⚠ l'ancien _guitar_path IGNORAIT `post` sans split (le Designer ne le remplit qu'avec un
        # split) ; la voix et les claviers n'en ont jamais eu. On le concatène : sans post, identique.
        return finish({"id": pid, "name": name, "input": lin, "out": lout,
                       "out_sel": out_sel, "chain": pre + _bake_blocks(g["post"], sblk, sparams, touched)})

    if union:                                             # UNION : toutes les branches, mute porté par branche
        branches = split.get("branches") or []
        if split.get("mode") == "fanout":
            node = {"split": {"merge": None, "branches": [
                {"id": b.get("id"), "blocks": _bake_blocks(b.get("blocks"), sblk, sparams, touched),
                 "out": j + 1, "out_sel": b.get("out") or OUT_DEFAULT, "mute": _lane_muted(b, slanes)}
                for j, b in enumerate(branches)]}}
            return finish({"id": pid, "name": name, "input": lin, "chain": pre + [node]})
        # ⚠ −3 et non 0 : UNE convention (écran, chemin legacy, preset-schema.md). Mesuré le
        # 2026-09-12 sur « 1983 » — merge à 0,0 dB alors que l'écran annonçait −3.
        node = {"split": {"merge": {"gain": split.get("gain", -3)}, "branches": [
            {"id": b.get("id"), "blocks": _bake_blocks(b.get("blocks"), sblk, sparams, touched),
             "mute": _lane_muted(b, slanes)} for b in branches]}}
        return finish({"id": pid, "name": name, "input": lin, "out": lout,
                       "out_sel": out_sel,
                       "chain": pre + [node] + _bake_blocks(g["post"], sblk, sparams, touched)})

    # branches actives (mute par scène via scene.branches[branch.id].mute)
    active = [b for b in (split.get("branches") or [])
              if not bool((slanes.get(b.get("id")) or {}).get("mute"))]
    if not active:
        return None

    fanout = split.get("mode") == "fanout"

    if len(active) == 1:                                  # 1 branche -> collapse en linéaire
        b = active[0]
        chain = pre + _bake_blocks(b.get("blocks"), sblk, sparams, touched)
        if fanout:
            osel = b.get("out") or OUT_DEFAULT
        else:
            chain += _bake_blocks(g["post"], sblk, sparams, touched)
            osel = out_sel
        return finish({"id": pid, "name": name, "input": lin, "out": lout,
                       "out_sel": osel, "chain": chain})

    if fanout:                                            # FAN-OUT : chaque branche -> SA sortie, pas de post
        node = {"split": {"merge": None, "branches": [
            {"id": b.get("id"), "blocks": _bake_blocks(b.get("blocks"), sblk, sparams, touched),
             "out": j + 1, "out_sel": b.get("out") or OUT_DEFAULT}    # out = marqueur ; out_sel = routage réel
            for j, b in enumerate(active)]}}
        return finish({"id": pid, "name": name, "input": lin, "chain": pre + [node]})

    # MERGE : branches sommées -> post -> une sortie ; défaut −3, la convention unique (cf. plus haut)
    node = {"split": {"merge": {"gain": split.get("gain", -3)}, "branches": [
        {"id": b.get("id"), "blocks": _bake_blocks(b.get("blocks"), sblk, sparams, touched)} for b in active]}}
    return finish({"id": pid, "name": name, "input": lin, "out": lout,
                   "out_sel": out_sel, "chain": pre + [node] + _bake_blocks(g["post"], sblk, sparams, touched)})


def _guitar_path(preset, sc, union=False):
    """Compat : le chemin de la lane guitare (tests, outils). Le vrai constructeur est _lane_path."""
    from .store import lanes_of
    lane = next((L for L in lanes_of(preset) if L["id"] == "guitar"), None)
    return _lane_path(lane, preset, sc, union) if lane else None


def _path_blocks(path):
    """Nombre de blocs d'un path baké (branches de split comprises)."""
    n = 0
    for node in path.get("chain") or []:
        sp = node.get("split") if isinstance(node, dict) else None
        if isinstance(sp, dict):
            n += sum(len(br.get("blocks") or []) for br in sp.get("branches") or [])
        else:
            n += 1
    return n


# ── UNE ENTRÉE, UNE LANE (2026-10-10 : « les VSTs ne sont pas chargés ») ─────────────────────────────────
# golem_rig pose une piste PAR ENTRÉE (« Sandbox #Input N ») : deux lanes sur la même entrée reconstruisaient la
# même piste l'une après l'autre, et la dernière gagnait. Vécu : un patch guitare neuf (lane guitare assise sur
# IN 2) gardait la lane voix vide du preset vierge, elle aussi sur IN 2 — le Titan et le SpecOps étaient posés,
# puis effacés par la lane voix (0 FX), à chaque rebuild, sans un mot ; la guitare sortait sèche puis plus rien.
# Désormais une seule lane par entrée : celle qui porte le plus de blocs (à égalité, la première) ; l'autre est
# NON MONTÉE et dite (puce de /live, journal), jamais effacée du preset.
def _one_lane_per_input(paths, unmounted):
    taken, kept = {}, []
    for p in sorted(paths, key=lambda x: -_path_blocks(x)):           # sorted est stable : à égalité, l'ordre
        if p.get("midi") or p.get("input") is None:
            continue
        taken.setdefault(p["input"], p)
    for p in paths:
        owner = None if p.get("midi") or p.get("input") is None else taken.get(p["input"])
        if owner is not None and owner is not p:
            unmounted.append({"id": p.get("id"), "name": p.get("_lane_name") or p.get("id"), "input": str(p["input"]),
                              "reason": f"IN {p['input']} is already played by lane « {owner.get('_lane_name') or owner.get('id')} »"})
            continue
        kept.append(p)
    for p in kept:
        p.pop("_lane_name", None)
    return kept


def to_paths_preset(preset, scene_id=None, union=False, veto=None):
    """`(preset ancien, scene_id) -> preset schéma paths` avec la scène bakée.
    Un path par LANE (store.lanes_of) ; les entrées physiques restent les constantes legacy
    jusqu'au lot 2 (le patch de la carte les donnera). Prêt pour compile_rig.
    `union=True` (moteur live) : toutes les branches posées + `mute` par branche -> topologie stable
    entre scènes (bascule d'état sans rebuild). Cf. _guitar_path.
    `veto` (set de clés '1'/'2'/'k' ou d'ids de lane) : lanes coupées par le MODE courant (docs/modes.md) — leur
    entrée n'est PAS montée (même effet que IN/OUT NONE, mais décidé par le mode+patch, pas le preset)."""
    veto = veto or set()
    sc = _scene(preset, scene_id)
    paths = []
    # LOT 1 : une boucle sur LA LISTE DE LANES (store.lanes_of — dérivée du document legacy tant que
    # le Designer parle les trois royaumes). Une lane vetoée par le mode, ou à IN/OUT NONE, n'est
    # pas montée ; une lane v2 sans bloc est un passthrough (entrée cochée = jouée), une legacy vide non.
    from .store import lanes_of, is_v2
    lanes = lanes_of(preset)                       # v2 ou legacy, toujours NORMALISÉE (input/out/disabled)
    unmounted = []                                 # les lanes que CETTE carte ne peut pas prendre — dites, jamais tues
    n_card = None
    try:
        from . import inputmap
        n_card = len((inputmap.current() or {}).get("inputs") or []) or None
    except Exception as _e:
        _swallowed(_e)
    vetoed = []                                    # les lanes coupées par le MODE — la raison d'un son vide
    for lane in lanes:
        if lane.get("key") in veto or lane.get("id") in veto:
            vetoed.append(lane.get("in_name") or lane.get("name") or lane.get("id"))
            continue
        if lane.get("disabled"):
            # une lane de patch que la carte n'a pas pu lier (patches.bind_input) : IN NONE, mais pas par choix —
            # sa raison remonte, sinon le son disait « no lane » et l'onglet restait vert (campagne 2026-10-25)
            why = next((L.get("bind_error") for L in preset.get("lanes") or []
                        if isinstance(L, dict) and L.get("id") == lane.get("id") and L.get("bind_error")), None)
            if why:
                unmounted.append({"id": lane["id"], "name": lane.get("name") or lane["id"], "input": "NONE",
                                  "reason": "cannot be mounted: " + str(why)})
            continue
        if lane.get("on_card") is False:
            # input-map.md §7 : repli SIGNALÉ. On ne monte pas une lane sur une entrée que la carte
            # n'a pas (elle serait muette — et sur une carte à 2 entrées, « In 3 » est le root des
            # claviers : deux lanes se disputaient la même piste). Le preset reste intact : la lane
            # attend la bonne carte, ou une autre entrée choisie dans le Designer.
            need = lane.get("in_name") or f"IN {lane['in_sel']}"
            unmounted.append({"id": lane["id"], "name": lane["name"], "input": lane["in_sel"],
                              "reason": f"needs {need}, this card has {n_card or '?'} inputs and no {need}" if lane.get("in_name")
                              else f"needs IN {lane['in_sel']}, this card has {n_card or '?'}"})
            continue
        ch = lane["chain"]
        # Une lane VIDE : en v2 elle est une entrée COCHÉE par l'utilisateur (input-map.md §3.2), donc
        # jouée — un path passthrough, comme `guitar` l'a toujours été (audit 2026-09-09 : six lanes
        # cochées sur le XR18, un seul path bakė). En LEGACY on garde le silence d'avant : un vieux
        # preset porte souvent `voice: {chain: []}` sans intention — monter un micro nu dans les
        # retours à la relecture d'un preset d'il y a un an, c'est un larsen sur scène.
        if not is_v2(preset) and lane["id"] != "guitar" and not ch["pre"] and not ch.get("split") and not ch["post"]:
            continue
        path = _lane_path(lane, preset, sc, union)
        if path:
            path["_lane_name"] = lane.get("name") or lane.get("id")
            paths.append(path)
    paths = _one_lane_per_input(paths, unmounted)
    # mode looper : le bloc marqueur vit désormais dans la lane config (plus dans la chaîne guitare) —
    # on calcule sa présence sur le preset natif et on la propage au plan comme flag top-level.
    from . import rig
    # La TABLE DE BOUCLES voyage ici : le bloc looper vit dans la lane config, qui ne devient pas
    # un path — sans ce relais, golem_rig ne verrait jamais ce que l'utilisateur a réglé.
    looper = ({"enabled": True, "loops": rig.looper_loops(preset)}
              if rig.looper_enabled(preset) else preset.get("looper"))
    annotate_drumkit_union(preset, paths)
    out = {"id": preset.get("id"), "name": preset.get("name"),
           "style": preset.get("style"), "scene": sc.get("id"), "paths": paths,
           "looper": looper, **({"unmounted": unmounted} if unmounted else {})}
    if not paths:
        out["why_empty"] = _why_empty(vetoed, unmounted)
    return out


def _why_empty(vetoed, unmounted):
    """La phrase du refus d'un son sans aucune lane (docs/modes.md §3.2, 2026-10-24) : un testeur Windows avait coupé
    « Guitar 1 » dans son mode, et chaque son guitare répondait « preset sans 'paths' » — en français, sans indice. Elle
    s'AFFICHE (bandeau du Designer, incident « Files not loaded ») : en anglais, avec l'endroit où agir."""
    if vetoed:
        try:
            from . import modes as _modes
            mname = _modes.current().get("name") or _modes.current().get("id") or "this mode"
        except Exception:
            mname = "this mode"
        names = ", ".join(dict.fromkeys(str(v) for v in vetoed))
        verb = "is" if len(set(vetoed)) == 1 else "are"
        return f"nothing to play: {names} {verb} off in mode « {mname} » — turn it back on in Settings ▸ Mode"
    if unmounted:
        u = unmounted[0]
        return f"nothing to play: {u.get('name') or u.get('id')} {u.get('reason')}"
    return "nothing to play: this sound has no lane"


# ── L'UNION DES KITS (docs/drums-kit.md lot 2 e, 2026-09-23) ─────────────────────────────
# Le kit d'un bloc Drum Kit est un paramètre PAR SCÈNE — mais un kit est un PLUGIN : en changer par
# scene_apply ne changeait rien, et en faire un rebuild (l'après-midi du 23/09) ouvrait ~1 s de trou
# par scène, 3 Go à recharger pour Aasimonster. Même doctrine que les lanes : le preset pose TOUS les
# kits que ses scènes utilisent, la scène en allume un. Ici on ANNOTE chaque bloc drumkit bakė de
# l'ensemble `kits` (base ∪ overrides de toutes les scènes, trié) ; compile_rig en fait N moteurs,
# golem_rig N paires, et la forme du rebuild est cet ensemble — pas le kit du moment.
def _walk_blocks(node, out):
    if isinstance(node, dict):
        if node.get("type") == "drumkit" and node.get("id"):
            out.append(node)
        for v in node.values():
            _walk_blocks(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_blocks(v, out)
    return out


def drumkit_kits(preset, bid, base_kit=None):
    """Les kits qu'un bloc Drum Kit `bid` utilise, toutes scènes confondues (base + overrides), triés."""
    kits = {base_kit} if base_kit else set()
    for sc in (preset or {}).get("scenes") or []:
        k = ((sc.get("params") or {}).get(bid) or {}).get("kit")
        if k:
            kits.add(k)
    return sorted(kits)


def annotate_drumkit_union(preset, paths):
    from .store import lanes_of
    base = {}
    try:
        for b in _walk_blocks([ln.get("chain") for ln in lanes_of(preset)], []):
            base[b["id"]] = (b.get("params") or {}).get("kit")
    except Exception as _e:
        _swallowed(_e)
    for b in _walk_blocks(paths, []):
        cur = (b.get("params") or {}).get("kit")
        b["kits"] = drumkit_kits(preset, b["id"], base.get(b["id"]) or cur) or ([cur] if cur else [])
