# SPDX-License-Identifier: GPL-3.0-or-later
"""ÉCOUTER UNE CAPTURE DEPUIS LA LIBRARY (docs/library-tones.md §4) : « toucher = écouter ».

Une capture (ampli, tête + baffle, baffle, pédale, outboard) se fait entendre DANS LE PATCH QUI JOUE :
une COPIE du preset courant, où le bloc de même nature de la lane guitare (ou basse, pour une capture de
basse) prend la capture touchée, est émise au rack sous l'id `audition`. Rien n'est écrit : ni le preset,
ni le brouillon du Designer, ni l'état (preset_id / scene_id ne bougent pas). Arrêter = rappeler le preset
courant ; l'id différent force un REBUILD (jamais une bascule de scène sur le rig de l'écoute).

Le choix du bloc, dans la chaîne de la lane (pre, la branche que la scène courante fait entendre, post) :
  - tête seule (gear amp)    -> le premier bloc ampli devient `amp-nam` ; sans baffle après lui, le baffle
                                 d'un autre bloc ne s'invente pas : l'écoute le dit (`no_cab`) ;
  - tête + baffle (amp-cab)  -> le premier bloc ampli devient `amp` ; les baffles de la chaîne se taisent
                                 (sinon deux baffles) ;
  - baffle (cab)             -> le premier `cab` prend l'IR ; sans lui, un `cab` est posé après l'ampli ;
  - pédale (pedal)           -> le premier `pedal-nam`, sinon posée devant l'ampli ;
  - outboard                 -> `comp-nam` (compresseurs) ou `preamp-nam` (le reste), le premier de ce type,
                                 sinon posé en tête de chaîne (comp) ou devant l'ampli (préampli) ;
  - IR d'effet (ir-fx)       -> le premier `ir-fx`, sinon posé en fin de chaîne.
Le bloc se déduit de la nature ET du format (bridge/playable.py) : une IR de pédale courte va au baffle.
Le bloc touché est forcé ALLUMÉ dans la scène courante (un TS éteint à la scène A ne s'entendrait pas)."""
import copy
import re

AUDITION_ID = "audition"
AMP_TYPES = ("amp", "amp-nam", "capture-module")
COMP_WORDS = re.compile(r"1176|la-?2a|la-?3a|\bcomp|limit|distressor|fairchild|ssl|bus comp|opto|vari-?mu|dbx", re.I)


class AuditionError(Exception):
    """Une écoute impossible : le message (anglais) est montré tel quel au musicien."""


def outboard_type(tone):
    txt = " ".join([str(tone.get("amp") or ""), str(tone.get("title") or "")] + [str(m) for m in tone.get("makes") or []])
    return "comp-nam" if COMP_WORDS.search(txt) else "preamp-nam"


def _is_bass(tone):
    return (tone.get("family") == "bass" or "bass" in (tone.get("tags") or []) or tone.get("style") == "bass"
            or bool(re.search(r"\bbass\b", str(tone.get("amp") or tone.get("title") or ""), re.I)))


def _pick_lane(preset, tone):
    lanes = [L for L in preset.get("lanes") or [] if isinstance(L, dict) and isinstance(L.get("chain"), dict)]
    want = "bass" if _is_bass(tone) else "guitar"
    for L in lanes:
        if (L.get("in_role") or L.get("role")) == want:
            return L
    if want == "bass":                                   # pas de lane basse : la guitare l'entend quand même
        for L in lanes:
            if (L.get("in_role") or L.get("role")) == "guitar":
                return L
    raise AuditionError(f"The patch that is playing has no {want} lane to hear this on.")


def _path(lane, scene):
    """Les listes de blocs que la scène fait entendre, dans l'ordre : pre, la branche ouverte, post."""
    ch = lane["chain"]
    out = [ch.setdefault("pre", [])]
    sp = ch.get("split")
    if isinstance(sp, dict) and sp.get("branches"):
        muted = {k for k, v in ((scene or {}).get("branches") or {}).items() if isinstance(v, dict) and v.get("mute")}
        br = next((b for b in sp["branches"] if b.get("id") not in muted), sp["branches"][0])
        out.append(br.setdefault("blocks", []))
    out.append(ch.setdefault("post", []))
    return out


def _find(path, types):
    for lst in path:
        for i, b in enumerate(lst):
            if isinstance(b, dict) and b.get("type") in types:
                return lst, i
    return None, None


def _new_id(preset, base):
    used = set()

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") and x.get("id"):
                used.add(x["id"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(preset.get("lanes"))
    n, cand = 1, base
    while cand in used:
        n += 1
        cand = f"{base}-{n}"
    return cand


def build(preset, scene_id, tone, model_id=None):
    """(document d'écoute, info) — ne modifie pas `preset`. `tone` = l'entrée du catalogue (/api/catalog),
    `model_id` = un de ses modèles (le premier par défaut)."""
    if not isinstance(preset, dict) or not preset.get("lanes"):
        raise AuditionError("Load a patch first: a capture is heard in the patch that is playing.")
    models = tone.get("models") or []
    m = next((x for x in models if str(x.get("id")) == str(model_id)), None) if model_id is not None else None
    if m is None:
        if model_id is not None or not models:
            raise AuditionError("This capture has no such model on the rack.")
        m = models[0]
    from . import playable as PL
    # le BLOC qui la joue, par la règle commune (docs/library-tones.md §7) : une IR de pédale courte est un baffle, une
    # IR d'outboard (ou de pédale longue) un ir-fx — jamais déduit de la seule nature
    btype = PL.block_for(tone.get("gear"), tone.get("format") or "nam", tone.get("ir_kind"))
    gear = {"amp-nam": "amp", "amp": "amp-cab", "cab": "cab", "pedal-nam": "pedal", "preamp-nam": "outboard",
            "ir-fx": "ir-fx"}.get(btype)
    doc = copy.deepcopy(preset)
    scenes = doc.get("scenes") or []
    scene = next((s for s in scenes if s.get("id") == scene_id), scenes[0] if scenes else None)
    lane = _pick_lane(doc, tone)
    path = _path(lane, scene)
    ref, mid, label = str(tone.get("id")), str(m.get("id")), tone.get("amp") or tone.get("title") or ""
    info = {"lane": lane.get("id"), "gear": gear, "ref": ref, "model": mid, "notes": []}

    def put(lst, i, btype, replace):
        if replace:
            old = lst[i]
            blk = {"id": old.get("id"), "type": btype, "label": label, "ref": ref, "model": mid,
                   "params": {k: v for k, v in (old.get("params") or {}).items() if k in ("input", "output", "level")}}
            if old.get("foot") is not None:
                blk["foot"] = old["foot"]
            lst[i] = blk
        else:
            blk = {"id": _new_id(doc, btype), "type": btype, "label": label, "ref": ref, "model": mid, "params": {}}
            lst.insert(i, blk)
        return blk

    if gear in ("amp", "amp-cab"):
        lst, i = _find(path, AMP_TYPES)
        if lst is None:
            raise AuditionError("The guitar lane of this patch has no amp block to swap.")
        blk = put(lst, i, "amp-nam" if gear == "amp" else "amp", True)
        cabs = [(l2, j) for l2 in path for j, b in enumerate(l2) if isinstance(b, dict) and b.get("type") == "cab"]
        if gear == "amp-cab":
            for l2, j in cabs:                            # le baffle est DANS la capture : pas un deuxième
                _force(doc, scene, lane, l2[j]["id"], False)
        elif not cabs:
            info["notes"].append("no_cab")
    elif gear == "cab":
        lst, i = _find(path, ("cab",))
        if lst is not None:
            blk = put(lst, i, "cab", True)
        else:
            al, ai = _find(path, AMP_TYPES)
            if al is None:
                raise AuditionError("The guitar lane of this patch has no amp to put this cab after.")
            blk = put(al, ai + 1, "cab", False)
            if al[ai].get("type") == "amp":
                info["notes"].append("amp_has_cab")      # une tête + baffle devant : deux baffles, on le dit
    elif gear == "pedal":
        lst, i = _find(path, ("pedal-nam",))
        if lst is not None:
            blk = put(lst, i, "pedal-nam", True)
        else:
            al, ai = _find(path, AMP_TYPES)
            blk = put(al, ai, "pedal-nam", False) if al is not None else put(path[0], len(path[0]), "pedal-nam", False)
    elif gear == "outboard":
        bt = outboard_type(tone)
        info["type"] = bt
        lst, i = _find(path, (bt,))
        if lst is not None:
            blk = put(lst, i, bt, True)
        elif bt == "comp-nam":
            blk = put(path[0], 0, bt, False)
        else:
            al, ai = _find(path, AMP_TYPES)
            blk = put(al, ai, bt, False) if al is not None else put(path[0], len(path[0]), bt, False)
    elif gear == "ir-fx":                                 # un ressort, un écho : en fin de chaîne (ou celui qui y est)
        lst, i = _find(path, ("ir-fx",))
        blk = put(lst, i, "ir-fx", True) if lst is not None else put(path[-1], len(path[-1]), "ir-fx", False)
    else:
        raise AuditionError("This capture cannot be heard from the Library.")
    _force(doc, scene, lane, blk["id"], True)
    info["block"] = blk["id"]
    doc["id"] = AUDITION_ID
    doc["name"] = f"{preset.get('name') or 'Patch'} · {label}"
    doc.pop("factory", None)
    return doc, info


def _force(doc, scene, lane, bid, on):
    """Le bloc allumé (ou éteint) dans la scène courante ET dans l'état de lane qu'elle porte."""
    if scene is None:
        return
    scene.setdefault("blocks", {})[bid] = on
    st_id = ((scene.get("lanes") or {}).get(lane.get("id")) or {}).get("state")
    for st in lane.get("states") or []:
        if st.get("id") == st_id:
            st.setdefault("blocks", {})[bid] = on
