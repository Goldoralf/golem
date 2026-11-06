# SPDX-License-Identifier: GPL-3.0-or-later
"""BALANCE — APPLIQUER UNE LANE À TOUTE LA SETLIST (docs/band-scenes.md §4, écran 6 — 2026-09-15).

Le modèle COPIE (docs/patches.md §15) coûte cher à un groupe : l'ingé son règle le compresseur de
basse à la balance, et dix-neuf presets portent l'ancienne valeur. Ce geste est un DÉPÔT EN MASSE,
explicite, par rôle de lane : la lane source (blocs, potards, captures, ÉTATS) remplace la lane du
même rôle dans chaque morceau choisi. Pas d'étiquette de provenance, pas de lien caché (§15.3) :
le lien est le geste, une fois, confirmé, annulable.

Ce que ça TOUCHE : la chaîne de la lane et ses états. Ce que ça NE TOUCHE PAS : les scènes du
morceau (chaque scène garde son état par NOM — « Pick » reste « Pick »), les switches (un bloc
garde son pied s'il existe encore, par id puis par type), les niveaux et mutes par scène, les
autres lanes. Chaque morceau est sauvegardé avant (`presets/.lane-apply-undo.json`) : un tap annule.
"""
import copy
import json
import os
import time

from . import config as C
from . import store

UNDO = lambda: os.path.join(C.PRESETS_DIR, ".lane-apply-undo.json")


def _lane(p, lane_id):
    return next((L for L in (p or {}).get("lanes") or [] if isinstance(L, dict) and L.get("id") == lane_id), None)


def target_lane(p, src):
    """La lane d'un morceau qui reçoit la source : même rôle ; à égalité, le même id ; une lane MIDI
    ne reçoit jamais une lane audio (et inversement). (lane, None) ou (None, la raison, en anglais)."""
    same = [L for L in (p.get("lanes") or []) if isinstance(L, dict) and L.get("role") == src.get("role")]
    if not same:
        return None, "no " + str(src.get("role") or "such") + " lane"
    L = next((x for x in same if x.get("id") == src.get("id")), same[0])
    if bool(L.get("midi")) != bool(src.get("midi")):
        return None, ("this " + str(src.get("role")) + " lane is a " + ("MIDI instrument" if L.get("midi") else "audio input")
                      + ", the source is " + ("MIDI" if src.get("midi") else "audio"))
    return L, None


def _params_of(L):
    return {b["id"]: (b.get("type"), b.get("params") or {}, b.get("ref"), b.get("label"))
            for b in store._lane_chain_blocks(L.get("chain") or {}) if isinstance(b, dict) and b.get("id")}


def diff(src, dst):
    """Ce que la lane source change dans une lane cible, lisible : [« Comp · ratio 4 → 6 », …]."""
    out = []
    a, b = _params_of(dst), _params_of(src)
    by_type_dst = {}
    for bid, (t, pm, ref, lb) in a.items():
        by_type_dst.setdefault(t, (bid, pm, ref, lb))
    for bid, (t, pm, ref, lb) in b.items():
        old = a.get(bid) if bid in a and a[bid][0] == t else by_type_dst.get(t)
        name = lb or t
        if old is None:
            out.append(f"+ {name}")
            continue
        _obid, opm, oref, _olb = old if len(old) == 4 else (None, old[1], old[2], old[3])
        if ref != oref:
            out.append(f"{name} · capture changed")
        for k in sorted(set(pm) | set(opm)):
            if pm.get(k) != opm.get(k):
                out.append(f"{name} · {k} {opm.get(k, '—')} → {pm.get(k, '—')}")
    src_types = {v[0] for v in b.values()}
    for bid, (t, _pm, _ref, lb) in a.items():
        if t not in src_types:
            out.append(f"− {lb or t}")
    sn = {s.get("name") for s in (src.get("states") or []) if not s.get("implicit")}
    dn = {s.get("name") for s in (dst.get("states") or []) if not s.get("implicit")}
    out += [f"+ state {n}" for n in sorted(sn - dn)]
    return out


def plan(src_preset, lane_id, targets):
    """Le plan, sans rien écrire : pour chaque preset cible, la lane visée, les états qu'il utilise, ce
    qui change, ou la raison de l'exclure. `targets` = [{preset, title}] (lignes de setlist)."""
    src = _lane(src_preset, lane_id)
    if not src:
        return {"error": "unknown lane"}
    rows, seen = [], set()
    for t in targets:
        pid = t.get("preset")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        row = {"preset": pid, "title": t.get("title") or pid, "this": pid == src_preset.get("id")}
        if row["this"]:
            rows.append({**row, "title": t.get("title") or src_preset.get("name") or pid, "ok": False, "why": "this song"}); continue
        p = store.load_preset(pid)
        if p is None:
            rows.append({**row, "ok": False, "why": "not on this rack"}); continue
        row["title"] = t.get("title") or p.get("name") or pid
        L, why = target_lane(p, src)
        if why:
            rows.append({**row, "ok": False, "why": why}); continue
        used = []
        for sc in p.get("scenes") or []:
            st = next((x for x in L.get("states") or [] if x.get("id") == ((sc.get("lanes") or {}).get(L["id"]) or {}).get("state")), None)
            if st and not st.get("implicit") and st.get("name") not in used:
                used.append(st.get("name"))
        rows.append({**row, "ok": True, "lane": L["id"], "states": used, "changes": diff(src, L)})
    return {"lane": {"id": src["id"], "name": src.get("name"), "role": src.get("role"),
                     "states": [s.get("name") for s in src.get("states") or [] if not s.get("implicit")]},
            "songs": rows}


def _apply_one(p, src, src_preset):
    """Remplace dans `p` (migré) la lane du rôle de `src`. Rend l'id de la lane remplacée."""
    from . import patches
    L, why = target_lane(p, src)
    if why:
        raise ValueError(why)
    tl, sl = L["id"], src["id"]
    old_chain = copy.deepcopy(L.get("chain") or {})
    old_states = {s.get("id"): s for s in L.get("states") or []}
    feet = [(b.get("id"), b.get("type"), b.get("foot")) for b in store._lane_chain_blocks(old_chain)
            if isinstance(b, dict) and b.get("foot")]
    # la chaîne source, ids renommés s'ils sont pris ailleurs dans CE morceau — et les états avec
    states_src = [copy.deepcopy(s) for s in src.get("states") or [] if isinstance(s, dict) and s.get("id")]
    chain, states_ren, _ren = patches._dedupe(copy.deepcopy(src.get("chain") or {}), states_src,
                                              patches._taken_outside(p, tl), patches._taken_branches_outside(p, tl))
    states_ren = states_ren or []
    # LES SWITCHES NE BOUGENT PAS : un bloc garde le pied du bloc qu'il remplace (même id, sinon même type)
    new_blocks = [b for b in store._lane_chain_blocks(chain) if isinstance(b, dict)]
    for b in new_blocks:
        b.pop("foot", None)
    free = list(new_blocks)
    for bid, btype, foot in feet:
        m = next((b for b in free if b.get("id") == bid), None) or next((b for b in free if b.get("type") == btype), None)
        if m is not None:
            m["foot"] = foot
            free.remove(m)
    # les états prennent l'espace de noms de la lane cible
    prefix_s, prefix_t = f"st-{sl}-", f"st-{tl}-"
    idmap = {}
    for s in states_ren:
        nid = prefix_t + s["id"][len(prefix_s):] if s["id"].startswith(prefix_s) else s["id"]
        idmap[s["id"]] = nid
        s["id"] = nid
    by_name = {str(s.get("name") or "").strip().lower(): s for s in states_ren if not s.get("implicit")}
    src_scene_ptr = {sc.get("id"): idmap.get(((sc.get("lanes") or {}).get(sl) or {}).get("state"))
                     for sc in src_preset.get("scenes") or [] if isinstance(sc, dict)}
    by_id = {s["id"]: s for s in states_ren}
    others = frozenset().union(*[store.lane_chain_sets(x.get("chain"))[1] for x in p.get("lanes") or []
                                 if isinstance(x, dict) and x.get("id") != tl]) if len(p.get("lanes") or []) > 1 else frozenset()
    L["chain"] = chain
    L["states"] = states_ren
    if isinstance(src.get("patch_from"), dict):
        L["patch_from"] = dict(src["patch_from"])
    else:
        L.pop("patch_from", None)
    for sc in p.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        ent = (sc.get("lanes") or {}).get(tl) or {}
        old = old_states.get(ent.get("state")) or {}
        # l'état que la scène jouait, retrouvé par NOM ; sinon ce que la scène de même lettre joue à la source
        st = by_name.get(str(old.get("name") or "").strip().lower()) if not old.get("implicit") else None
        st = st or by_id.get(src_scene_ptr.get(sc.get("id")))
        store.write_lane_slice(sc, old_chain, {}, others)            # les clés de l'ANCIENNE chaîne partent
        if st:
            store.write_lane_slice(sc, chain, {k: st.get(k) or {} for k in ("blocks", "params", "branches")}, others)
            sc.setdefault("lanes", {})[tl] = {**ent, "state": st["id"]}
        else:
            e = {k: v for k, v in ent.items() if k != "state"}
            if e:
                sc.setdefault("lanes", {})[tl] = e
            elif isinstance(sc.get("lanes"), dict):
                sc["lanes"].pop(tl, None)
    return tl


def apply(src_preset, lane_id, preset_ids):
    """Écrit la lane source dans chaque preset cible (sauvegardé avant). Rend {applied, skipped}."""
    src = _lane(src_preset, lane_id)
    if not src:
        return {"ok": False, "error": "unknown lane"}
    backup, applied, skipped = {}, [], []
    for pid in preset_ids or []:
        if pid == src_preset.get("id"):
            continue
        p = store.load_preset(pid)
        if p is None:
            skipped.append({"preset": pid, "why": "not on this rack"}); continue
        raw = json.load(open(os.path.join(C.PRESETS_DIR, f"{store._safe_id(pid)}.json")))
        try:
            lane = _apply_one(p, src, src_preset)
        except ValueError as e:
            skipped.append({"preset": pid, "why": str(e)}); continue
        store.migrate_config(p)
        dupes = store.duplicate_block_ids(p) or store.duplicate_branch_ids(p)
        if dupes:
            skipped.append({"preset": pid, "why": "duplicate ids: " + ", ".join(dupes)}); continue
        backup[pid] = raw
        store._write_json_atomic(os.path.join(C.PRESETS_DIR, f"{store._safe_id(pid)}.json"), p)
        applied.append({"preset": pid, "lane": lane})
    if backup:
        store._write_json_atomic(UNDO(), {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": src_preset.get("id"),
                                          "lane": lane_id, "docs": backup})
    return {"ok": True, "applied": applied, "skipped": skipped, "undo": bool(backup)}


def undo():
    """Remet chaque preset tel qu'il était avant le dernier geste, et oublie la sauvegarde."""
    d = store._read_json(UNDO(), None)
    if not isinstance(d, dict) or not d.get("docs"):
        return {"ok": False, "error": "nothing to undo"}
    for pid, doc in d["docs"].items():
        store._write_json_atomic(os.path.join(C.PRESETS_DIR, f"{store._safe_id(pid)}.json"), doc)
    os.remove(UNDO())
    return {"ok": True, "restored": sorted(d["docs"])}


def pending_undo():
    d = store._read_json(UNDO(), None)
    return {"at": d.get("at"), "source": d.get("source"), "lane": d.get("lane"), "count": len(d.get("docs") or {})} if isinstance(d, dict) and d.get("docs") else None
