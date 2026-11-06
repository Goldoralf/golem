# SPDX-License-Identifier: GPL-3.0-or-later
"""LA FICHE D'UN PRESET — un module PUR, partagé avec golem.fm (docs/shell.md §4 bis).

Ce que /live, la carte Presets et le pied lisent d'un preset n'est pas le document : c'est une fiche CALCULÉE
(switches, scènes, états de lane, entrées…). golem.fm affiche la même interface sur ses fiches preset et patch ;
plutôt qu'une copie en TypeScript qui dériverait, il VENDORISE ce fichier octet pour octet, au même commit que
`app/` (son tools/sync_golem_app.py, test d'empreinte — le patron de golemfile).

D'où trois règles, qui tiennent ce module :
  - bibliothèque standard SEULEMENT, aucun import relatif, aucune lecture ni écriture (ni config, ni carte) ;
  - ce qui dépend de la machine ENTRE en paramètre : `imap` (l'input map de la carte, inputmap.current()),
    `migrate_styles` (la taxonomie des genres) — absents, les valeurs nominales ;
  - le rack l'appelle LUI-MÊME (bridge/store.py, bridge/recall.py) : une seule source, jamais deux.
Changer le NOM ou la FORME de `summary`, `stomps`, `migrate`, `preset_summary` ou `stomp_states` est un
changement de contrat pour golem.fm : à dire dans le message de commit, comme une forme de lecture GET.

Entrées publiques :
  summary(doc, imap=None)                       -> l'entrée de GET /api/presets pour ce document (migration comprise)
  stomps(doc, scene_id, whammy_on=False, imap=None) -> ce que le rack pose dans state.stomps
  migrate(p, imap=None, migrate_styles=None)    -> la migration du document, sans les singletons du rack
"""
import copy
import json
import re

FCB_SWITCHES = [6, 7, 8, 9, 10]                                  # positions physiques des stomps FCB (CC 30-34)

# Lane CONFIG (docs/blocks-doctrine.md — 2026-07-21) : les blocs SERVICE transversaux vivent hors
# des chaînes de signal, dans preset["config"] = {gen:{blocks,out}, rec:{blocks}}.
#   gen  = « Players » : générateurs + looper (IN capture + OUT vers la façade)
#   rec  = « Recorder & Click » : les blocs PERMANENTS rec + click (config globale)
SERVICE_GEN = ("looper", "backing-track", "sample", "drums")
SERVICE_REC = ("rec", "compo")
# lane `arr` — le CHEF D'ORCHESTRE (docs/arrangement.md §7). Ni `gen` (il n'est pas mixé, il ne
# produit aucun audio) ni `rec` (dont la lane Click porte le badge « GLOBAL · tous les presets »,
# or l'arrangement est ce qu'un preset a de plus personnel).
SERVICE_ARR = ("arrangement",)
SERVICE_ALL = SERVICE_GEN + SERVICE_REC + SERVICE_ARR
# bloc `preview` RETIRÉ (2026-07-21) : la démo se génère depuis Library (« Listen to your preset »),
# sans bloc. On strippe tout bloc preview résiduel au load (la démo elle-même = preset["preview"], séparée).
DROPPED_TYPES = ("preview",)


def migrate_scene_branches(p):
    """« lane » a quatre sens dans le dépôt (audit 2026-09-08 §2.4) ; celui-ci disparaît : le mute
    par BRANCHE de split d'une scène s'appelle `scenes[].branches` (ex-`lanes`). Lecture legacy,
    écriture neuve, idempotent. `scene.lanes` est réservé aux vraies lanes d'instrument (lot 1)."""
    lane_ids = {str(L.get("id")) for L in (p.get("lanes") or []) if isinstance(L, dict) and L.get("id")}
    for sc in p.get("scenes") or []:
        if isinstance(sc, dict) and "lanes" in sc and "branches" not in sc:
            # ⚠ 2026-09-15 : `lanes` a DEUX vies — les mutes legacy de branches, et les entrées par lane
            # d'INSTRUMENT (level, state). Déplacer tout le dict emportait ces dernières dans `branches`
            # à la passe suivante (un `lanes[<lane>].level` posé par le Designer sur une scène sans
            # `branches` disparaissait ; le pointeur d'état des lanes, pareil). On ne déplace que ce
            # qui est un mute de branche ; le reste reste une entrée de lane.
            lanes = sc.get("lanes") if isinstance(sc.get("lanes"), dict) else {}
            # une clé qui est l'id d'une LANE du preset n'est jamais une branche, même sans state ni level
            mutes = {k: v for k, v in lanes.items() if is_legacy_branch_mute(v) and k not in lane_ids}
            keep = {k: v for k, v in lanes.items() if k not in mutes}
            sc["branches"] = mutes
            if keep:
                sc["lanes"] = keep
            else:
                sc.pop("lanes", None)
    return p


def is_legacy_branch_mute(v):
    """Une entrée de `scene.lanes` est un ANCIEN mute de BRANCHE (avant le 2026-09-08, le mute par
    branche vivait là) si elle porte `mute` et rien d'une entrée de LANE d'instrument : ni `state`
    (docs/band-scenes.md, posé sur toute lane par la migration), ni `level`. Depuis le 2026-09-15,
    `scene.lanes[<lane>].mute` veut aussi dire « lane coupée dans la scène » — les deux sens se
    distinguent par ces clés, UN critère pour tous les lecteurs (store, rig, patches ; golem.fm le copie)."""
    return isinstance(v, dict) and "mute" in v and "state" not in v and "level" not in v


def scene_branches(sc):
    """Le mute par branche d'une scène, quel que soit l'âge du document : `branches` (nom depuis
    le 2026-09-08) PLUS les entrées de l'ancien `lanes` qui portent un `mute` — jamais celles qui
    portent un `level` (le niveau par lane d'instrument, l'autre vie de `lanes`). Avant, `branches`
    présent masquait des mutes legacy encore sous `lanes` (retour golem.fm, 2026-09-14)."""
    sc = sc or {}
    legacy = {k: v for k, v in (sc.get("lanes") or {}).items() if is_legacy_branch_mute(v)}
    return {**legacy, **(sc.get("branches") or {})}


def scene_lane_level(sc, lane_id):
    """Le niveau d'une lane dans une scène (v2 `lanes[<id>].level`), ou None."""
    v = ((sc or {}).get("lanes") or {}).get(lane_id)
    return v.get("level") if isinstance(v, dict) else None


# ── LES LANES (audit 2026-09-08, lot 1) ──────────────────────────────────────────────────────
# Le document sur disque parle encore les trois royaumes (`guitar` / `voice` / `keys`) ; le reste du
# rack lit une LISTE `p["lanes"]`, dérivée ici à chaque load/save (jamais une vérité à part : si le
# document change, la liste est recalculée — sur disque ce n'est qu'un cache). Une lane :
#   id        "guitar" | "voice" | "keys"   — l'id de PATH (nom des pistes Reaper, livemap) ; stable
#   key       "1" | "2" | "k"               — la clé legacy (p.in / p.out / p.names, veto, pied)
#   role      rôle de l'ENTRÉE patchée (inputmap), descriptif — jamais une identité
#   name      nom éditable (p.names[key]) ou défaut
#   input/out numéros physiques (legacy : 1/1, 2/2, 3/3 — le lot 2 les prendra du patch)
#   out_sel   '1' | '2' | '1-2' | 'NONE' ; disabled = IN ou OUT à NONE
#   chain     {pre, split, post} — le graphe RICHE pour TOUTES les lanes (la voix et les claviers
#             étaient des chaînes plates de seconde classe : plus de split, pas de niveau de scène)
#   midi      True pour la lane clavier (entrée = contrôleur, pas de l'audio)
#   level_key la clé legacy de scene.levels (== id) — appliquée pour la guitare seule tant que le
#             Designer ne règle pas un niveau par lane ; scene.lanes[id].level a priorité (lot 1)
OUT_DEFAULT = "1-2"
LEGACY_LANES = (("1", "guitar", 1, "Input 1"), ("2", "voice", 2, "Input 2"), ("k", "keys", 3, "Keys"))


def _rich_chain(realm, src):
    """{pre, split, post} depuis le royaume legacy : la guitare l'a déjà (ou l'ancien `lanes`/`chain`),
    voix et claviers sont des `chain` plates (anciens types nus en string acceptés)."""
    g = src or {}
    if realm == "guitar":
        if "pre" in g or "split" in g:
            return {"pre": g.get("pre") or [], "split": g.get("split"), "post": g.get("post") or []}
        if g.get("lanes"):                                    # ancien : lanes = split merge @début
            branches = [{"id": L.get("id") or f"b{i + 1}", "blocks": L.get("blocks") or []}
                        for i, L in enumerate(g["lanes"])]
            return {"pre": [], "split": {"mode": "merge", "branches": branches,
                                         "gain": (g.get("merge") or {}).get("gain", -3)}, "post": []}
        return {"pre": g.get("chain") or [], "split": None, "post": []}
    chain = [{"type": t} if isinstance(t, str) else t for t in (g.get("chain") or []) if isinstance(t, (str, dict))]
    return {"pre": chain, "split": None, "post": []}


LANES_V = 2                         # `p["lanes_v"] == 2` : la liste de lanes est LA vérité du document
LEGACY_KEY = {"guitar": "1", "voice": "2", "keys": "k"}
MIDI_ROLES = ("keys", "pads", "keys-pads")


def rich_chain(c):
    """{pre, split, post} depuis n'importe quelle forme de chaîne (riche, `{chain}` plate, ou legacy guitare)."""
    c = c or {}
    if "pre" in c or "split" in c or "post" in c:
        return {"pre": list(c.get("pre") or []), "split": c.get("split") or None, "post": list(c.get("post") or [])}
    return _rich_chain("voice", c)


def is_v2(p):
    return isinstance(p, dict) and p.get("lanes_v") == LANES_V and isinstance(p.get("lanes"), list)


def midi_input_base(n_card_inputs):
    """Le numéro d'ENTRÉE (= nom du root Reaper « Sandbox #Input N ») de la 1re lane MIDI : In3 sur
    une carte à deux entrées (le root historique du .rpp), 101 au-delà — sur une 8×8, In3 est une
    vraie entrée audio (lot 5). Les claviers suivants prennent +1."""
    return 3 if (n_card_inputs or 0) < 3 else 101


def _parse_in(in_sel):
    """"3" -> (3, False) · "3-4" -> (3, True) · autre -> (None, False)."""
    s = str(in_sel or "")
    if s.isdigit():
        return int(s), False
    m = re.fullmatch(r"(\d+)-(\d+)", s)
    return (int(m.group(1)), True) if m else (None, False)


def _first_of_role(by_ch, role):
    """Le canal de la PREMIÈRE entrée de la carte qui porte `role` (numéro `nth` le plus bas), None sinon."""
    hits = [e for e in by_ch.values() if e.get("role") == role]
    hits.sort(key=lambda e: int(e.get("nth") or 1))
    return str(hits[0].get("ch")) if hits else None


def _norm_lane(L, idx, by_ch, midi_role, midi_seq=0, by_name=None):
    """Une lane v2 telle qu'elle est stockée -> une lane complète (mêmes champs que le legacy)."""
    lid = str(L.get("id") or f"ln-{idx + 1}")
    role = str(L.get("role") or ("keys" if L.get("midi") else "guitar"))
    # une lane liée à un port USB est MIDI quel que soit son rôle (un module de batterie en USB,
    # docs/drums-kit.md) ; `drums` n'entre PAS dans MIDI_ROLES : en audio stéréo c'est une lane comme la basse
    midi = bool(L.get("midi")) or role in MIDI_ROLES or str(L.get("in_sel") or "").startswith("usb")
    key = str(L.get("key") or LEGACY_KEY.get(lid) or lid)
    # SANS ENTRÉE NI LIAISON : l'entrée de son RÔLE sur la carte (audit 2026-10-10) — pas le numéro que porte son
    # NOM (`guitar` -> '1'), qui est le micro sur une carte où la guitare est en 2. Le numéro legacy reste le
    # repli d'une carte qui n'a pas ce rôle.
    seat = None if (midi or L.get("in_sel")) else _first_of_role(by_ch, role)
    in_sel = str(L.get("in_sel") or seat or (LEGACY_KEY.get(lid) if lid in ("guitar", "voice") else ("usb" if midi else str(idx + 1))))
    # LE LIEN FORT ENTRÉE-NOM (2026-09-09) : la lane se lie à une entrée par son NOM (« Voice 1 »),
    # le numéro suit le patch de la carte du moment — un preset fait en Gig (Voice 1 = In 3) joue en
    # Home (Voice = In 2) sans qu'on le rebranche. Sans nom, ou nom absent de cette carte : le numéro.
    # LE LIEN FORT ENTRÉE-NOM (2026-09-09) : la lane se lie à (rôle, numéro) de l'entrée — « Voice 1 »
    # = (voice, 1) — une clé générique que toute carte satisfait ; `in_name` est le libellé dérivé.
    in_nth = L.get("in_nth")
    in_role = str(L.get("in_role") or "").strip() or None
    # le libellé de la liaison : celui de l'ENTRÉE sur la carte (« Guitar 1 »), sinon « Guitar 1 » dérivé — pas
    # « guitar 1 » : ce champ est le TITRE de la lane à l'écran, et il était réécrit en minuscules à chaque
    # sauvegarde (presets/paper-kite.json, audit 2026-10-10)
    in_name = f"{in_role.title()} {in_nth}" if in_role and in_nth else None
    named_missing = False
    if in_role and in_nth and not midi and by_name:
        if (in_role, int(in_nth)) in by_name:
            in_sel = by_name[(in_role, int(in_nth))]
            in_name = (by_ch.get(in_sel) or {}).get("name") or in_name
            # LANE ET INSTRUMENT SE RÉSOLVENT PAR L'ENTRÉE (2026-09-09) : l'app le faisait, le bridge gardait
            # `role` — le tiroir disait voix, le veto de mode jugeait guitare (audit 2026-10-10)
            if in_role not in MIDI_ROLES:
                role = in_role
        else:
            # liée PAR NOM et la carte n'a pas cette entrée (« Guitar 2 » sur une Volt) : la lane ATTEND
            # sa carte — jamais un repli sur le numéro brut, qui est un AUTRE instrument (IN 2 = le micro).
            # Trouvé en finalisant l'audit 2026-09-09 : vide elle se taisait, en passthrough c'était
            # le micro nu dans les retours.
            named_missing = True
    out_sel = str(L.get("out_sel") or OUT_DEFAULT)
    stereo = False
    if midi:
        phys_in = midi_input_base(len(by_ch)) + midi_seq
    else:
        n, stereo = _parse_in(in_sel)
        phys_in = n if n else idx + 1
    # LIÉE PAR RÔLE ET SANS ENTRÉE SUR CETTE CARTE : aucun numéro (2026-10-13 — « BASS en IN 1 » sur une carte
    # où IN 1 est le micro). Le numéro gardé dans le document vient d'une autre carte ; le moteur n'y monte rien
    # (`on_card` False), et aucun écran ne doit l'y montrer non plus. `phys_in` reste calculé pour le rang.
    if named_missing:
        in_sel = "—"
    lane = {"id": lid, "key": key, "role": role, "name": str(L.get("name") or f"Lane {idx + 1}"),
            "input": phys_in, "out": idx + 1, "in_sel": in_sel, "out_sel": out_sel,
            "disabled": in_sel == "NONE" or out_sel == "NONE",
            "chain": rich_chain(L.get("chain")), "midi": midi, "stereo": stereo, "level_key": lid,
            **({"in_name": in_name, "in_role": in_role, "in_nth": int(in_nth)} if in_name else {}),
            # l'entrée demandée EXISTE-t-elle sur la carte branchée ? (un preset fait sur une 8×8 qui
            # arrive sur une Volt) — sinon la lane n'est pas montée, et on le DIT (input-map.md §7)
            "on_card": True if midi or in_sel == "NONE" else (not named_missing and ((in_sel in by_ch or (str(phys_in) in by_ch)) or not by_ch))}
    # ── GROUPE DE BATTERIE (docs/drums-kit.md §6.3) : trois champs OPAQUES pour le moteur ──────
    # `drumset` = l'id du groupe (deux lanes qui le partagent sont le même instrument) ;
    # `drumset_module` = un descripteur config/drumkits ; `element` = ce que CETTE entrée porte.
    # Ils ne changent RIEN à la matérialisation : sept lanes montent comme sept lanes, I_RECINPUT
    # compris. Ils servent le repli à l'écran et la pose en un geste.
    # ⚠ JAMAIS `kit` : ce mot est pris par le paramètre du bloc `drumkit`, qui est le kit SONORE du
    # rack (drums-black-pearl) joué en MIDI. Deux natures sous un nom, c'est le bug de la semaine.
    for k in ("drumset", "drumset_module", "element"):
        v = L.get(k)
        if isinstance(v, str) and v.strip():
            lane[k] = v.strip()
    # POURQUOI LA LANE ATTEND (patches.as_preset : « no guitar input on … — assign one in Modes ▸ Inputs ») : gardé tant
    # qu'elle est à IN NONE. Perdu ici, le rappel d'un patch disait seulement « this sound has no lane » (2026-11-04,
    # setlist guitare sur une carte réglée basse) alors que scene_bake sait dire où agir.
    if lane["in_sel"] == "NONE" and isinstance(L.get("bind_error"), str) and L["bind_error"].strip():
        lane["bind_error"] = L["bind_error"].strip()
    if isinstance(L.get("patch_from"), dict):
        lane["patch_from"] = L["patch_from"]
    if isinstance(L.get("states"), list):        # les ÉTATS de la lane (docs/band-scenes.md §3)
        lane["states"] = [st for st in L["states"] if isinstance(st, dict) and st.get("id")]
    return lane


def _mirror_legacy(p, lanes):
    """Les trois clés d'origine (`guitar`/`voice`/`keys`, `in`/`out`/`names`) REGÉNÉRÉES depuis les
    lanes v2 : les lecteurs qui n'ont pas encore migré (export, IA, résumés, tones_sync…) voient les
    trois premières lanes comme avant. Les lanes supplémentaires leur sont invisibles (lot 4)."""
    by_id = {L["id"]: L for L in lanes}
    p["in"], p["out"], p["names"] = {}, {}, {}
    for lid, key in LEGACY_KEY.items():
        L = by_id.get(lid)
        if not L:
            p.pop(lid, None)
            continue
        c = L["chain"]
        if lid == "guitar":
            doc = {"pre": c["pre"], "split": c["split"], "post": c["post"]}
        else:
            doc = {"chain": (c["pre"] + c["post"]) if not c["split"] else c["pre"]}
        if L.get("patch_from"):
            doc["patch_from"] = L["patch_from"]
        p[lid] = doc
        if L["in_sel"] not in (key, "usb") and not str(L["in_sel"]).startswith("usb"):
            p["in"][key] = L["in_sel"]
        if L["out_sel"] != OUT_DEFAULT:
            p["out"][key] = L["out_sel"]
        p["names"][key] = L["name"]
    for k in ("in", "out", "names"):
        if not p[k]:
            p.pop(k)


def lanes_of(p, imap=None):
    """La liste de lanes d'un preset — v2 (`lanes_v: 2`, la liste EST le document, les clés legacy
    sont des miroirs) ou legacy (dérivée des trois royaumes). `imap` = l'input map de la carte
    ({inputs: [{ch, role, nth}], midi: {role}}, c'est-à-dire inputmap.current()) ; absente, les rôles par
    défaut (guitare / voix / claviers) et aucune entrée « hors carte »."""
    imap = imap if isinstance(imap, dict) else {}
    by_ch = {str(i.get("ch")): i for i in (imap.get("inputs") or [])}
    midi_role = ((imap.get("midi") or {}).get("role")) or "keys"
    if is_v2(p):
        by_name = {(str(e.get("role")), int(e.get("nth"))): str(e.get("ch")) for e in by_ch.values() if e.get("nth") is not None and e.get("role")}
        lanes, midi_seq = [], 0
        for i, L in enumerate(p["lanes"]):
            if not isinstance(L, dict):
                continue
            lane = _norm_lane(L, i, by_ch, midi_role, midi_seq, by_name)
            midi_seq += 1 if lane["midi"] else 0
            lanes.append(lane)
        _mirror_legacy(p, lanes)
        return lanes
    ins, outs, names = p.get("in") or {}, p.get("out") or {}, p.get("names") or {}
    lanes = []
    for key, realm, phys, dflt in LEGACY_LANES:
        src = p.get(realm)
        if not isinstance(src, dict):
            continue
        # LEGACY : la chaîne `guitar` est l'instrument guitare — sans `p.in` explicite, elle prend l'entrée de ce
        # rôle sur la carte (IN 2 sur le rack de dev), pas le numéro historique '1' (le micro). Audit 2026-10-10.
        in_sel = ins.get(key) or (realm != "keys" and _first_of_role(by_ch, realm)) or key
        if realm == "keys":
            role = midi_role
        else:
            r = (by_ch.get(in_sel) or {}).get("role")
            role = r if r and r not in ("none", "other") else realm
        out_sel = outs.get(key) or OUT_DEFAULT
        if realm == "keys":
            phys = midi_input_base(len(by_ch))              # lot 5 : In3 sur 2 entrées, 101 au-delà
        else:
            n, _st = _parse_in(in_sel)
            phys = n if n else phys                          # p.in choisi (« IN 2 pour la guitare ») — plus décoratif
        lanes.append({"id": realm, "key": key, "role": role, "name": names.get(key) or dflt,
                      "input": phys, "out": phys, "in_sel": in_sel, "out_sel": out_sel,
                      "disabled": in_sel == "NONE" or out_sel == "NONE",
                      "chain": _rich_chain(realm, src), "midi": realm == "keys",
                      "stereo": _parse_in(in_sel)[1], "level_key": realm,
                      "on_card": realm == "keys" or in_sel == "NONE" or in_sel in by_ch or str(phys) in by_ch or not by_ch})
    return lanes


def _lane_chain_blocks(c):
    for b in c.get("pre") or []:
        yield b
    for br in ((c.get("split") or {}).get("branches") or []):
        for b in br.get("blocks") or []:
            yield b
    for b in c.get("post") or []:
        yield b


def _arr_blocks(p):
    """Le bloc ARRANGEMENT (lane config `arr`). ⚠ Il n'était PAS recensé au pied (trouvé le 2026-09-30) :
    sa lane est à part depuis le 16/09 (arrangement.md §4 bis) et `_foot_blocks` ne parcourait que gen/rec.
    Le rack savait lancer la chanson (arrangement.foot_switch), mais /live, les conflits de switches, la
    réservation de la rangée 1-5 et la puce ne le voyaient pas. Séparé de `_config_blocks` : ceux qui lisent
    les SERVICES (preview, Rec, Click…) n'ont pas à le recevoir."""
    for b in ((p.get("config") or {}).get("arr") or {}).get("blocks") or []:
        if isinstance(b, dict):
            yield b


def _config_blocks(p):
    """Blocs de la lane config (gen puis rec)."""
    cfg = p.get("config") or {}
    for lane in ("gen", "rec"):
        for b in (cfg.get(lane) or {}).get("blocks") or []:
            yield b


def _guitar_blocks(p):
    """Blocs de la chaîne guitare, tous schémas (pre/split/post OU ancien chain)."""
    g = p.get("guitar") or {}
    for b in g.get("pre") or g.get("chain") or []:
        yield b
    for br in ((g.get("split") or {}).get("branches") or []):
        yield from br.get("blocks") or []
    yield from g.get("post") or []


def _lanes_summary(p):
    """Vue compacte de la chaîne pour les LISTES (mini-chaîne des cartes Presets) :
    une entrée par lane {id: branche|None, blocks:[{id,type,bypass}]} (split -> pre+branche+post aplatis).
    L'id de branche permet de croiser scene.lanes[id].mute (lane coupée par la scène)."""
    g = p.get("guitar") or {}
    mk = lambda blocks: [{"id": b.get("id"), "type": b.get("type"), "bypass": bool(b.get("bypass"))}
                         for b in (blocks or []) if b and b.get("type")]
    pre, post = mk(g.get("pre") or g.get("chain")), mk(g.get("post"))
    branches = ((g.get("split") or {}).get("branches") or [])
    if branches:
        return [{"id": br.get("id"), "blocks": pre + mk(br.get("blocks")) + post} for br in branches]
    return [{"id": None, "blocks": pre + post}]


def _inputs_summary(p, imap=None):
    """Vue STRUCTURÉE des entrées pour reconstituer la « ligne audio » read-only des cartes Presets :
    In 1 (guitare : pre → split{branches} → post → out), In 2 (voix), USB 1 (keys). Chaque entrée :
    {key, name, in, pre:[blk], split:{mode,branches:[{id,label,blocks,out}]}|None, post:[blk], out}."""
    names, outs = p.get("names") or {}, p.get("out") or {}
    # CONTENU CHARGÉ (décision 2026-07-31) : pour les blocs sans capture, le résumé
    # remonte la valeur du paramètre qui fait identité (vital→preset, drums→kit…). Sans lui,
    # trois Vital sur une lane sont trois tuiles identiques dans la carte. La table est ici
    # plutôt que dans le catalogue lu à l'export : le résumé doit rester autonome et rapide.
    _CONTENT = {"vital": "preset", "pads": "kit", "piano": "sfz", "ep": "bank", "drums": "kit"}

    def _blk(b):   # voix legacy = liste de types en string ; sinon bloc {id,type,params,bypass}
        if isinstance(b, str):
            return {"id": None, "type": b, "bypass": False}
        if isinstance(b, dict) and b.get("type"):
            out = {"id": b.get("id"), "type": b.get("type"), "bypass": bool(b.get("bypass")),
                   "foot": b.get("foot")}
            ck = _CONTENT.get(b.get("type"))
            if ck:
                v = (b.get("params") or {}).get(ck)
                if v:
                    out["content"] = v
                # la scène a le dernier mot (scene-first) : on remonte AUSSI la table par scène,
                # la carte affiche celle de la scène qu'elle montre
                per = {sc.get("id"): ((sc.get("params") or {}).get(b.get("id")) or {}).get(ck)
                       for sc in (p.get("scenes") or []) if isinstance(sc, dict) and sc.get("id")}
                per = {k: v2 for k, v2 in per.items() if v2}
                if per:
                    out["content_scenes"] = per
            return out
        return None
    mk = lambda blocks: [x for x in (_blk(b) for b in (blocks or [])) if x]
    # LOT 4 : une entrée PAR LANE (v2 ou legacy) — la carte Presets voit une 4e lane comme les autres.
    # La 1re lane figure toujours (passthrough) ; les autres seulement si elles ont des blocs.
    res = []
    for i, L in enumerate(lanes_of(p, imap)):
        c = L["chain"]
        pre, post = mk(c.get("pre")), mk(c.get("post"))
        sp = c.get("split") or {}
        branches = sp.get("branches") or []
        split = None
        if branches:
            split = {"mode": sp.get("mode") or "merge",
                     "branches": [{"id": br.get("id"), "label": chr(65 + j), "blocks": mk(br.get("blocks")),
                                   "out": br.get("out") or "1-2"} for j, br in enumerate(branches)]}
        if i and not (pre or post or branches):
            continue
        res.append({"key": L["key"], "name": L["name"], "in": "k" if L["midi"] else str(L["in_sel"]),
                    "role": L["role"], "pre": pre, "split": split, "post": post, "out": L["out_sel"]})
    return res


def _block_on_in_scene(x, scene_blocks):
    """État EFFECTIF d'un bloc dans une scène — MÊME ordre que scene_bake._bake_block :
    clé par id > clé par type > bypass de base. `x` = {id, type, bypass}.
    Une valeur `None` vaut « pas de clé » : on passe au cran suivant, comme le moteur."""
    if x["id"] is not None and scene_blocks.get(x["id"]) is not None:
        return scene_blocks[x["id"]] is not False
    if x["type"] is not None and scene_blocks.get(x["type"]) is not None:
        return scene_blocks[x["type"]] is not False
    return not x["bypass"]


def _chain_foot_blocks(p, imap=None):
    """Tous les blocs assignables au pied, TOUTES CHAÎNES confondues : (bloc, entrée '1'|'2'|'k').
    Un switch physique pilote les blocs de n'importe quelle entrée (ex. reverb du chant au pied).
    v2 : (bloc, clé de lane) — la clé legacy 1/2/k pour les trois premières, l'id pour les autres."""
    if is_v2(p):
        for L in lanes_of(p, imap):
            for b in _lane_chain_blocks(L["chain"]):
                if isinstance(b, dict):
                    yield b, L["key"]
        for b in _config_blocks(p):
            if isinstance(b, dict):
                yield b, "cfg"
        for b in _arr_blocks(p):
            yield b, "cfg"
        return
    for b in _guitar_blocks(p):
        yield b, "1"
    for b in (p.get("voice") or {}).get("chain") or []:
        if isinstance(b, dict):                    # rétro-compat : anciens types nus (string) ignorés
            yield b, "2"
    for b in (p.get("keys") or {}).get("chain") or []:
        if isinstance(b, dict):
            yield b, "k"
    for b in _config_blocks(p):                    # lane config (services transversaux)
        if isinstance(b, dict):
            yield b, "cfg"
    for b in _arr_blocks(p):                       # + l'arrangement (sa lane à part, cf. _arr_blocks)
        yield b, "cfg"


# ── LES ÉTATS DE LANE (docs/band-scenes.md §3, lot 1 — 2026-09-15) ───────────────────────────
# Une lane porte ses ÉTATS nommés (« Pick », « Fuzz » : les scènes du patch déposé, gardées avec
# leur nom) ; une scène en CHOISIT un par lane (`scene.lanes[<lane>].state`). Au lot 1, la table
# plate de la scène (`scene.blocks/params/branches`) reste la VÉRITÉ du son — le bake, le Designer et
# golem.fm la lisent comme avant — et chaque état pointé est RECOPIÉ depuis elle à chaque passage
# ici (load et save). Ce qui est neuf et durable : l'identité et le NOM de l'état par lane et par
# scène, que /live affiche. Le lot 3 renverse le sens (l'état devient la vérité, la table plate son
# miroir) quand le dictionnaire permettra de choisir et de PARTAGER un état entre scènes.
def lane_chain_sets(chain):
    """Les identités d'une chaîne : ids de blocs, types (clés de scène « sémantique stomp »), ids de
    branches — ce qui délimite, dans une scène, la part qui appartient à CETTE lane."""
    ids, types, brs = set(), set(), set()
    for b in _lane_chain_blocks(chain or {}):
        if isinstance(b, dict):
            if b.get("id"):
                ids.add(str(b["id"]))
            if b.get("type"):
                types.add(str(b["type"]))
    for br in (((chain or {}).get("split") or {}).get("branches") or []):
        if isinstance(br, dict) and br.get("id"):
            brs.add(str(br["id"]))
    return ids, types, brs


def scene_lane_slice(sc, chain):
    """La tranche d'une scène qui vise une lane : {blocks, params, branches} restreints à sa chaîne."""
    ids, types, brs = lane_chain_sets(chain)
    sc = sc or {}
    out = {"blocks": {k: v for k, v in (sc.get("blocks") or {}).items() if k in ids or k in types},
           "params": {k: v for k, v in (sc.get("params") or {}).items() if k in ids},
           "branches": {k: v for k, v in scene_branches(sc).items() if k in brs}}
    return out


def state_id_for(lane_id, scene_id):
    return f"st-{lane_id}-{scene_id}"


def write_lane_slice(sc, chain, content, other_types=frozenset()):
    """Pose dans la table plate d'une scène la tranche `content` d'une lane : ses clés d'ids de blocs,
    de params et de branches sont REMPLACÉES. Les clés par TYPE (legacy, « sémantique stomp ») valent
    pour toutes les lanes qui ont ce type : on ne retire que celles qu'aucune autre lane ne partage."""
    ids, types, brs = lane_chain_sets(chain)
    blocks = {k: v for k, v in (sc.get("blocks") or {}).items()
              if k not in ids and not (k in types and k not in other_types)}
    blocks.update((content or {}).get("blocks") or {})
    params = {k: v for k, v in (sc.get("params") or {}).items() if k not in ids}
    params.update((content or {}).get("params") or {})
    branches = {k: v for k, v in (sc.get("branches") or {}).items() if k not in brs}
    branches.update((content or {}).get("branches") or {})
    sc["blocks"], sc["params"], sc["branches"] = blocks, params, branches


def assign_lane_state(p, lane_id, scene_id, state_id):
    """La scène `scene_id` joue l'état `state_id` sur la lane `lane_id` : pointeur posé ET tranche de
    l'état recopiée dans la table plate (le miroir que le bake lit). Le geste du dictionnaire, côté
    serveur (le Designer a le même en JS : designer-model.assignLaneState). Rend True si fait."""
    L = next((x for x in (p.get("lanes") or []) if isinstance(x, dict) and x.get("id") == lane_id), None)
    sc = next((x for x in (p.get("scenes") or []) if isinstance(x, dict) and x.get("id") == scene_id), None)
    st = next((x for x in ((L or {}).get("states") or []) if isinstance(x, dict) and x.get("id") == state_id), None)
    if not (L and sc and st):
        return False
    others = frozenset().union(*[lane_chain_sets(x.get("chain"))[1] for x in p.get("lanes") or []
                                 if isinstance(x, dict) and x.get("id") != lane_id]) if len(p.get("lanes") or []) > 1 else frozenset()
    write_lane_slice(sc, L.get("chain"), {k: st.get(k) or {} for k in ("blocks", "params", "branches")}, others)
    sc.setdefault("lanes", {}).setdefault(lane_id, {})["state"] = state_id
    return True


def _canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False)


def ensure_lane_states(p):
    """Chaque (lane, scène) d'un preset v2 pointe un ÉTAT de la lane, nommé. Idempotent.

    LOT 1 : un état créé ici (« implicit ») est la copie de ce que la scène disait déjà pour cette lane,
    nommé comme la scène (son nom, sinon sa lettre) — aucun son ne change.

    LOT 3 (le dictionnaire, 2026-09-15) : un état peut être PARTAGÉ par plusieurs scènes (« Pick » sur
    A, B et D). L'état devient alors la vérité, et la table plate de chaque scène qui le pointe en est
    le MIROIR — c'est elle que le bake, le Designer et golem.fm lisent. La réconciliation, sans suivi
    d'édition, suit une règle unique : parmi les scènes qui pointent l'état, celles dont la tranche
    DIFFÈRE de l'état ont été éditées ; si elles disent toutes la même chose, cette chose devient
    l'état (et gagne toutes les scènes) ; si elles se contredisent, l'état gagne. Le Designer propage
    déjà côté client (designer-model.propagateLaneStates) : ici c'est le filet des autres écrivains.

    Un état implicite que plus aucune scène ne pointe est retiré ; un état EXPLICITE (déposé avec un
    patch, créé ou renommé par l'utilisateur) reste : « Fingers » existe même si ce morceau ne s'en sert pas."""
    if not is_v2(p):
        return p
    scenes = [sc for sc in (p.get("scenes") or []) if isinstance(sc, dict) and sc.get("id")]
    lanes = [L for L in (p.get("lanes") or []) if isinstance(L, dict) and L.get("id")]
    types_of = {L["id"]: lane_chain_sets(L.get("chain"))[1] for L in lanes}
    for L in lanes:
        lid = L["id"]
        other_types = frozenset().union(*[t for k, t in types_of.items() if k != lid]) if len(lanes) > 1 else frozenset()
        states = [st for st in (L.get("states") or []) if isinstance(st, dict) and st.get("id")]
        by_id = {st["id"]: st for st in states}
        pointing = {}
        for sc in scenes:
            if not isinstance(sc.get("branches"), dict):
                sc["branches"] = scene_branches(sc)     # `lanes` sans `branches` = clé legacy des mutes : fixée d'abord
            ent = (sc.get("lanes") or {}).get(lid)
            ent = ent if isinstance(ent, dict) else {}
            sid = ent.get("state")
            if not sid or sid not in by_id:
                sid = state_id_for(lid, sc["id"])
                st = by_id.get(sid)
                if st is not None and (not st.get("implicit") or sid in pointing):
                    k = 2                                # l'id est pris (état explicite, ou déjà pointé ce passage) : un id neuf
                    while f"{sid}-{k}" in by_id:
                        k += 1
                    sid, st = f"{sid}-{k}", None
                if st is None:
                    nm = sc.get("name") if isinstance(sc.get("name"), str) and sc["name"].strip() else str(sc["id"])
                    st = {"id": sid, "name": nm.strip(), "implicit": True, **scene_lane_slice(sc, L.get("chain"))}
                    states.append(st); by_id[sid] = st
                sc.setdefault("lanes", {})[lid] = {**ent, "state": sid}
            pointing.setdefault(sid, []).append(sc)
        for sid, scs in pointing.items():
            st = by_id[sid]
            slices = [scene_lane_slice(sc, L.get("chain")) for sc in scs]
            have = {k: st[k] for k in ("blocks", "params", "branches") if k in st}
            if len(have) < 3:                           # état sans contenu (déposé nu) : la 1re scène le donne
                new = slices[0]
            else:
                differ = {_canon(sl) for sl in slices if _canon(sl) != _canon(have)}
                new = json.loads(differ.pop()) if len(differ) == 1 else have
            st.update(new)
            for sc, sl in zip(scs, slices):
                if _canon(sl) != _canon(new):
                    write_lane_slice(sc, L.get("chain"), new, other_types)
        L["states"] = [st for st in states if st["id"] in pointing or not st.get("implicit")]
    return p


def scene_lane_states(p):
    """Par scène, ce que chaque lane y fait — pour /live et les résumés : une ligne par lane
    {id, role, name, state, glyph_type, mute, level}, dans l'ordre des lanes. [] hors v2."""
    if not is_v2(p):
        return {}
    out = {}
    lanes = [L for L in (p.get("lanes") or []) if isinstance(L, dict) and L.get("id")]
    for sc in (p.get("scenes") or []):
        if not isinstance(sc, dict) or not sc.get("id"):
            continue
        rows = []
        for L in lanes:
            ent = (sc.get("lanes") or {}).get(L["id"])
            ent = ent if isinstance(ent, dict) else {}
            st = next((x for x in (L.get("states") or []) if isinstance(x, dict) and x.get("id") == ent.get("state")), None)
            blocks = [b for b in _lane_chain_blocks(L.get("chain") or {}) if isinstance(b, dict) and b.get("type")]
            # le glyphe de la ligne : le bloc qui fait l'IDENTITÉ de la lane (ampli, capture, instrument), sinon le premier
            ident = next((b for b in blocks if b.get("type") in _IDENTITY_TYPES and _block_on_in_scene({"id": b.get("id"), "type": b.get("type"), "bypass": bool(b.get("bypass"))}, sc.get("blocks") or {})), None)                 or next((b for b in blocks if b.get("type") in _IDENTITY_TYPES), None) or (blocks[0] if blocks else None)
            brs = scene_branches(sc)
            all_muted = bool(((L.get("chain") or {}).get("split") or {}).get("branches")) and                 all((brs.get(br.get("id")) or {}).get("mute") for br in ((L["chain"]["split"] or {}).get("branches") or []))
            rows.append({"id": L["id"], "role": L.get("role") or "guitar", "name": L.get("name"),
                         "state": (st or {}).get("name") or None,
                         # un état IMPLICITE (créé à la migration, nommé comme la scène) ne dit rien de plus que la
                         # scène : /live montre alors le bloc d'identité de la lane (« Twin Reverb »), pas « Intro » trois fois
                         "implicit": bool((st or {}).get("implicit")),
                         "glyph_type": (ident or {}).get("type"),
                         "block": {"type": (ident or {}).get("type"), "label": (ident or {}).get("label"), "variant": (ident or {}).get("variant")} if ident else None,
                         "mute": bool(ent.get("mute")) or all_muted or L.get("disabled", False),
                         "level": ent.get("level")})
        out[sc["id"]] = rows
    return out


_IDENTITY_TYPES = ("amp", "amp-nam", "pedal-nam", "preamp-nam", "vital", "piano", "organ", "ep", "pads", "drive", "comp")


def _role_by_key(p, imap=None):
    """Rôle de la lane par clé de `_foot_blocks` (v2 : L.key -> L.role ; legacy : 1 guitare, 2 voix,
    k claviers ; cfg = service) — l'étiquette GTR/VOX/SVC des piles de /live, sur les deux rangées."""
    role_of = {"1": "guitar", "2": "voice", "k": "keys", "cfg": "service"}
    if is_v2(p):
        for L in lanes_of(p, imap):
            role_of[L["key"]] = L.get("role") or role_of.get(L["key"]) or "guitar"
    return role_of


def _foot_blocks(p, imap=None):
    """Un seul bloc visible ; ses interrupteurs capturés ont des cibles MIDI distinctes."""
    for b, key in _chain_foot_blocks(p, imap):
        yield b, key
        if not b.get("capture_foot"):
            continue
        for c in b.get("capture_controls") or []:
            sw = b["capture_foot"].get(c["id"])
            if c.get("kind") == "toggle" and isinstance(sw, int) and 6 <= sw <= 10:
                value = (b.get("params") or {}).get(c["id"], c["default"])
                yield {"id": b["id"] + "@capture" + str(c["slot"]), "type": "capture-control", "foot": sw,
                       "label": c["name"], "bypass": not value, "capture_parent": b["id"],
                       "capture_control": c["id"]}, key


def _foot_on_in_scene(x, scene):
    if x.get("capture_parent"):
        values = (scene.get("params") or {}).get(x["capture_parent"]) or {}
        return bool(values.get(x["capture_control"], not x["bypass"]))
    return _block_on_in_scene(x, scene.get("blocks") or {})


def _foot_summary(p, imap=None):
    """Résumé « pédalier » d'un preset — modèle ASSIGNATION LIBRE : chaque switch FCB (6-10) tient les
    blocs dont `block.foot == N`, TOUTES entrées confondues (IN 1/IN 2/USB 1 — champ `in` par bloc ;
    plusieurs blocs par switch, ex. 7 = delay+reverb ; PAS de défaut par type). Nourrit le modal
    d'assign, la vue Pedalboard, la carte Presets, la page Live.
      switches : [{sw, blocks:[{id,type,bypass,in}], whammy:bool}]
      scenes[].on : liste des SWITCHS allumés (tous leurs blocs on) dans la scène."""
    by_sw = {n: [] for n in FCB_SWITCHES}
    wham, has_wah = None, False
    role_of = _role_by_key(p, imap)
    for b, key in _foot_blocks(p, imap):
        t = b.get("type")
        if t == "whammy-dt" and key == "1":
            wham = b
        if str(t).startswith("wah") or t == "autowah":
            has_wah = True
        f = b.get("foot")
        if f in by_sw and b.get("id"):
            # role + label (2026-09-15) : la tuile /live empile une ligne par bloc — « Phaser · GTR »,
            # « PEQ · VOX » — au lieu de deux glyphes et un nom composé
            by_sw[f].append({"id": b.get("id"), "type": t, "bypass": bool(b.get("bypass")), "in": key,
                             "role": role_of.get(key) or "guitar", "label": b.get("label") or None,
                             "variant": b.get("variant") or None,
                             **({"capture_parent": b["capture_parent"], "capture_control": b["capture_control"]}
                                if b.get("capture_parent") else {})})
    switches = [{"sw": n, "blocks": by_sw[n],
                 "whammy": any(x["type"] == "whammy-dt" for x in by_sw[n])} for n in FCB_SWITCHES]
    used = [n for n in FCB_SWITCHES if by_sw[n]]
    wmode = ((wham or {}).get("params") or {}).get("mode")
    scenes = []
    by_scene = scene_lane_states(p)
    for s in p.get("scenes", []):
        blk = s.get("blocks") or {}
        scenes.append({"id": s.get("id"), "name": s.get("name"),
                       "lanes": by_scene.get(s.get("id")) or [],   # une ligne par lane : l'ÉTAT que la scène y choisit (band-scenes.md)
                       # switch allumé = TOUS ses blocs assignés sont on dans la scène
                       "on": [n for n in used if all(_foot_on_in_scene(x, s) for x in by_sw[n])],
                       "off": [k for k, v in blk.items() if v is False],     # blocs (id/type) coupés dans la scène — mini-chaîne
                       "on_blk": [k for k, v in blk.items() if v is True],   # blocs forcés on (override du bypass de base)
                       "branches_off": [k for k, v in scene_branches(s).items()
                                        if (v or {}).get("mute")],         # branches mutées dans la scène
                       "whammy": (s.get("whammy") or {}).get("mode")
                                 or ((s.get("params") or {}).get((wham or {}).get("id"), {}) or {}).get("mode")
                                 or (wmode if wham else None)})
    return {"switches": switches, "used": used, "has_wah": has_wah,
            "whammy": bool(wham), "whammy_mode": wmode, "exp2": p.get("exp2"), "scenes": scenes}


# CE QUE FAIT un preset — ou un patch, dont la lane ⚙ porte aussi des blocs de service (docs/patches.md §3) — au-delà du
# son (2026-10-17 : le filtre « With » des deux sélecteurs, et ses icônes) :
# les blocs qui DISTINGUENT un preset. Les permanents (Arrangement, Rec, Click, Compo) sont dans tous : pas ici.
FEATURES = ("backing", "standard", "drums", "looper", "pads")
# REC et RIFF (compo) : permanents dans un preset (aucun tri), mais un PATCH ne porte leur switch que s'il l'a choisi
# (docs/patches.md §3) — côté patches, ils distinguent (2026-10-17)
CAPTURE = ("rec", "compo")


def features(p, capture=False):
    """Les blocs spéciaux d'un preset ou d'un patch, dans l'ordre de FEATURES — présence seule, où qu'ils soient (la
    lane config `gen`, une chaîne de lane, une branche). `capture` (un patch) : Rec et Riff aussi, s'ils ont un switch."""
    found = set()
    if ((p.get("backing") or {}).get("songs")) if isinstance(p.get("backing"), dict) else False:
        found.add("backing")
    if (p.get("looper") or {}).get("enabled") if isinstance(p.get("looper"), dict) else False:
        found.add("looper")

    def walk(x):
        if isinstance(x, dict):
            t = x.get("type")
            t = "backing" if t == "backing-track" else t          # le bloc backing d'un patch (docs/patches.md §3)
            if isinstance(t, str) and t in FEATURES:
                found.add(t)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(p.get("config"))
    walk(p.get("lanes_v2") or p.get("lanes"))
    out = [f for f in FEATURES if f in found]
    if capture:
        rec = ((p.get("config") or {}).get("rec") or {}).get("blocks") or [] if isinstance(p.get("config"), dict) else []
        have = {b.get("type") for b in rec if isinstance(b, dict) and b.get("foot")}
        out += [f for f in CAPTURE if f in have]
    return out


def preset_summary(p, imap=None):
    """La fiche COMPACTE d'un preset — ce que /api/presets sert et que /live, Presets, le pied lisent
    (scènes, switches, lanes…). Sortie de load_presets pour que l'ESSAI (sandbox-try, docs/patches.md
    §19) ait la même fiche : /live montrait un essai sans tuiles de stomps (2026-09-14)."""
    fs = _foot_summary(p, imap)
    return {"id": p.get("id"), "name": p.get("name"), "style": p.get("style"), "styles": p.get("styles"), "artist": p.get("artist"),
            "bpm": p.get("bpm"), "colors": p.get("colors"), "anims": p.get("anims"),
            "tags": p.get("tags") or [],
            "looper": bool((p.get("looper") or {}).get("enabled")),
            "backing": [s.get("slug") for s in ((p.get("backing") or {}).get("songs")) or []],
            # standards utilisés : le bloc vit dans la lane config `gen` (Players)
            "standards": sorted({(b.get("params") or {}).get("standard")
                                 for b in (((p.get("config") or {}).get("gen") or {}).get("blocks") or [])
                                 if b.get("type") == "standard"
                                 and (b.get("params") or {}).get("standard")}),
            "switches": fs["switches"], "used": fs["used"], "has_wah": fs["has_wah"],
            "whammy": fs["whammy"], "whammy_mode": fs["whammy_mode"], "exp2": fs["exp2"],
            "scenes": fs["scenes"], "lanes": _lanes_summary(p), "inputs": _inputs_summary(p, imap),
            "preview": p.get("preview"),   # guide sonore (démo par scène) pour le ▶ Library
            "features": features(p)}


def migrate(p, imap=None, migrate_styles=None):
    """La migration PURE d'un document (idempotente, mute `p` en place et le rend) : branches de scène,
    liste de lanes, états de lane, blocs SERVICE sortis des chaînes vers la lane config, blocs permanents
    (Arrangement, Rec, Click, Compo) POSÉS. Leurs paramètres — les singletons config/recorder|click|compo.json
    de la machine — ne sont PAS ici : bridge/store.migrate_config les hydrate ensuite. Aucun champ de la fiche
    n'en dépend. `migrate_styles(p)` ramène les styles à des familles (bridge/genres) ; absent, ils restent."""
    migrate_scene_branches(p)
    p["lanes"] = lanes_of(p, imap)               # la liste dérivée, recalculée à chaque passage (lot 1)
    ensure_lane_states(p)                        # les ÉTATS de lane (band-scenes.md, lot 1)
    if not isinstance(p, dict):
        return p
    # le style d'un preset = des FAMILLES de la taxonomie (docs/genres.md) ; les anciens styles à plat
    # (djent, manouche, rap…) sont ramenés à leur famille ici, au passage — jamais de réécriture de masse
    if migrate_styles:
        migrate_styles(p)
    cfg = p.get("config") if isinstance(p.get("config"), dict) else {}
    gen = cfg.get("gen") if isinstance(cfg.get("gen"), dict) else {}
    rec = cfg.get("rec") if isinstance(cfg.get("rec"), dict) else {}
    arr = cfg.get("arr") if isinstance(cfg.get("arr"), dict) else {}
    gen.setdefault("blocks", []); gen.setdefault("out", "1-2")
    rec.setdefault("blocks", [])
    arr.setdefault("blocks", [])
    cfg["gen"], cfg["rec"], cfg["arr"] = gen, rec, arr
    p["config"] = cfg

    def _take(lst):
        if not isinstance(lst, list):
            return
        keep = []
        for b in lst:
            t = b.get("type") if isinstance(b, dict) else None
            if t in DROPPED_TYPES:
                continue                       # bloc retiré du produit (ex. preview) -> supprimé
            if t in SERVICE_GEN:
                gen["blocks"].append(b)
            elif t in SERVICE_REC:
                rec["blocks"].append(b)
            elif t in SERVICE_ARR:
                arr["blocks"].append(b)
            else:
                keep.append(b)
        lst[:] = keep

    g = p.get("guitar")
    if isinstance(g, dict):
        _take(g.get("pre")); _take(g.get("chain"))
        for br in ((g.get("split") or {}).get("branches") or []):
            _take(br.get("blocks"))
        _take(g.get("post"))
    _take((p.get("voice") or {}).get("chain"))
    _take((p.get("keys") or {}).get("chain"))
    gen["blocks"] = [b for b in gen["blocks"] if (b.get("type") if isinstance(b, dict) else None) not in DROPPED_TYPES]
    rec["blocks"] = [b for b in rec["blocks"] if (b.get("type") if isinstance(b, dict) else None) not in DROPPED_TYPES]
    arr["blocks"] = [b for b in arr["blocks"] if (b.get("type") if isinstance(b, dict) else None) not in DROPPED_TYPES]
    # bloc Arrangement PERMANENT (2026-07-30) : il a son propre onglet dans le Designer, donc on
    # n'« ajoute » plus un arrangement — on écrit la structure du morceau. L'onglet est toujours
    # là, vide tant qu'aucune section n'est posée. Même contrat que Rec et Click, à ceci près que
    # ses données sont PAR PRESET (pas de config globale à hydrater).
    if not any(isinstance(b, dict) and b.get("type") == "arrangement" for b in arr["blocks"]):
        arr["blocks"].append({"id": "arrangement", "type": "arrangement",
                              "params": {"advance": "bars", "sections": []}})
    # blocs Rec, Click, Compo PERMANENTS (le foot/claim reste local ; les params viennent de la machine)
    if not any(isinstance(b, dict) and b.get("type") == "rec" for b in rec["blocks"]):
        rec["blocks"].insert(0, {"id": "rec-global", "type": "rec"})
    cb = next((b for b in rec["blocks"] if isinstance(b, dict) and b.get("type") == "click"), None)
    if cb is None:
        cb = {"id": "click-global", "type": "click"}
        rec["blocks"].append(cb)
    # le Click naît BYPASSÉ : en mode « preset » (docs/modes.md) le bloc actif fait JOUER le
    # métronome — un preset neuf ne doit pas se mettre à ticquer tout seul. Un bypass explicite
    # (l'utilisateur l'a activé puis sauvé) est évidemment conservé.
    if "bypass" not in cb:
        cb["bypass"] = True
    if not any(isinstance(b, dict) and b.get("type") == "compo" for b in rec["blocks"]):
        rec["blocks"].append({"id": "compo-global", "type": "compo"})
    return p


def stomp_states(preset, scene_id, whammy_on=False, imap=None):
    """État on/off des stomps UTILISÉS, par SWITCH (6-10), depuis la scène active, pour un preset DÉJÀ migré.
    Un switch = ON si tous ses blocs assignés (block.foot) sont on dans la scène ; un switch portant un
    whammy-dt suit `whammy_on` (piloté en MIDI, pas un FX de scène). Clés = numéro de switch."""
    fs = _foot_summary(preset, imap) if preset else {"used": [], "switches": [], "scenes": []}
    scn = next((s for s in fs["scenes"] if s["id"] == scene_id), None)
    on = set((scn or {}).get("on") or [])
    st = {n: (n in on) for n in fs["used"]}
    for sw in fs["switches"]:
        if sw["whammy"] and sw["sw"] in st:
            st[sw["sw"]] = bool(whammy_on)
    return st


def summary(doc, imap=None, migrate_styles=None):
    """L'entrée de GET /api/presets pour ce document, migration comprise. `doc` n'est pas modifié."""
    return preset_summary(migrate(copy.deepcopy(doc), imap, migrate_styles), imap)


def stomps(doc, scene_id, whammy_on=False, imap=None):
    """Ce que le rack pose dans state.stomps quand ce document joue la scène `scene_id`. `doc` n'est pas modifié."""
    return stomp_states(migrate(copy.deepcopy(doc), imap) if doc else None, scene_id, whammy_on, imap)
