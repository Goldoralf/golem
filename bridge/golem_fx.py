# SPDX-License-Identifier: GPL-3.0-or-later
"""LA FEUILLE golem FX (docs/golem-fx-sheet.md) : les réglages d'un bloc joué par golem-fx, tels que golem-fx les a
prévus — la face avant de la pédale, puis ses groupes experts et leurs interrupteurs « Custom ».

La source : le DESCRIPTEUR de chaque plugin (library/catalog/golem-fx-plugins.json, tools/sync-golem-fx-manifest.py).
Ce module le fond avec le catalogue, pour un type :
  - un réglage du descripteur qui EST un potard du catalogue (même nom de plugin, via la table du moteur) garde l'id,
    les bornes et la carte du catalogue — un preset garde ses réglages, et REAPER sans golem-fx sait encore le jouer ;
    il prend le nom golem-fx en libellé ;
  - les autres deviennent des potards NOUVEAUX : id golem-fx (préfixé `gfx_` s'il heurte un id du catalogue), unités et
    bornes du plugin, valeur brute (`map.mode: raw`), `engine_only: "golem"` — le compilateur les retire là où golem-fx
    ne joue pas le bloc ;
  - les potards du catalogue que le plugin n'a pas restent, cachés.
Lus par /api/effects (la feuille, les scènes, l'EXP), le compilateur (bornes, retrait) et le plan du Golem Engine.
golem_rig.lua applique la MÊME règle côté REAPER (apply_golem_fx)."""
import json
import os

from . import config as C

_cache = {"key": None, "plugins": {}, "table": {}}


def _load():
    pj = os.path.join(C.ROOT, "library", "catalog", "golem-fx-plugins.json")
    tj = os.path.join(C.ROOT, "library", "catalog", "effects-golem-engine.json")
    try:
        key = (os.path.getmtime(pj), os.path.getmtime(tj))
    except OSError:
        return {}, {}
    if _cache["key"] != key:
        try:
            plugins = json.load(open(pj, encoding="utf-8")).get("plugins", {})
            table = json.load(open(tj, encoding="utf-8")).get("effects", {})
        except (OSError, ValueError):
            plugins, table = {}, {}
        _cache.update(key=key, plugins=plugins, table=table)
    return _cache["plugins"], _cache["table"]


def descriptor_for(btype):
    """(descripteur, spec de la table) d'un type joué par golem-fx, ou (None, None)."""
    plugins, table = _load()
    spec = table.get(btype)
    if not (isinstance(spec, dict) and spec.get("golem_fx")):
        return None, None
    p = plugins.get(spec.get("vst3")) or {}
    return p.get("descriptor"), spec


def merged(btype, catalog_params):
    """(params fusionnés, feuille) d'un type : la liste de potards que la feuille golem FX montre (même forme que le
    catalogue) et {front, groups, provisional, presets}. (catalog_params, None) si le type n'a pas de descripteur."""
    desc, spec = descriptor_for(btype)
    if not desc:
        return list(catalog_params or []), None
    labels = spec.get("params") or {}
    absent = spec.get("absent") or {}
    cat = [dict(d) for d in (catalog_params or []) if d.get("id")]
    cat_ids = {d["id"] for d in cat}
    by_label = {}
    for d in cat:
        if d["id"] not in absent:
            by_label.setdefault(labels.get(d["id"]) or d.get("name"), d)
    dparams = desc.get("params") or {}
    identity = spec.get("identity") or {}                # ce que le type EST (Plate, Room, GCB-95) : ni montré ni réglé
    keys = {}                                            # id golem-fx -> id du bloc
    for gid, p in dparams.items():
        c = by_label.get(p.get("name"))
        keys[gid] = c["id"] if c else (("gfx_" + gid) if gid in cat_ids else gid)
    order = list(desc.get("front") or [])
    groups = desc.get("groups") or []
    where = {g: None for g in order}
    for grp in groups:
        for gid in grp.get("params") or []:
            where.setdefault(gid, grp.get("id"))
            order.append(gid)
    out, seen = [], set()
    for gid in order:
        p = dparams.get(gid)
        if not p or gid in seen:
            continue
        seen.add(gid)
        key = keys[gid]
        c = next((d for d in cat if d["id"] == key), None)
        kind = p.get("kind") or "float"
        if c:
            d = c
            d["label"] = p.get("name") or d.get("label")
            if p.get("unit") and not d.get("unit"):
                d["unit"] = p["unit"]
            # une liste du catalogue est le DÉBUT de celle du plugin (même rang : le Delay s'arrête à 1/16, le plugin
            # ajoute 1/2… et Free) : ses libellés restent (les presets), les choix en plus du plugin s'ajoutent
            popts = list(p.get("options") or [])
            if d.get("type") == "enum" and len(popts) > len(d.get("options") or []):
                d["options"] = list(d.get("options") or []) + popts[len(d.get("options") or []):]
                d.pop("values", None)
        else:
            d = {"id": key, "name": p.get("name"), "label": p.get("name"), "map": {"mode": "raw"}, "engine_only": "golem"}
            if kind == "enum":
                opts = list(p.get("options") or [])
                dflt = p.get("default")
                d.update(type="enum", options=opts,
                         default=opts[int(dflt)] if isinstance(dflt, (int, float)) and 0 <= int(dflt) < len(opts) else (opts[0] if opts else None))
            elif kind == "bool":
                d.update(type="bool", default=bool(p.get("default")))
            else:
                d.update(min=p.get("min"), max=p.get("max"), default=p.get("default"))
                if p.get("unit"):
                    d["unit"] = p["unit"]
                if p.get("decimals") is not None:
                    d["fmt"] = p["decimals"]
        if p.get("exp"):                                 # la pédale d'expression : ce que golem-fx déclare pilotable
            d["exp"] = True
        dep = p.get("depends")
        if isinstance(dep, dict) and dep.get("param") in keys:
            d["depends"] = {keys[dep["param"]]: _equals_as_block(dep, dparams, cat, keys)}
        d["gfx"] = {"id": gid, "group": where.get(gid), "help": p.get("help")}
        if gid in identity:
            d["hidden"] = True
            d["gfx"]["identity"] = identity[gid]
        out.append(d)
    used = {d["id"] for d in out}
    for d in cat:                                        # ce que le plugin n'a pas : gardé, caché (presets, autres moteurs)
        if d["id"] not in used:
            out.append(dict(d, hidden=True))
    sheet = {"front": [keys[g] for g in (desc.get("front") or []) if g in keys],
             "groups": [{"id": g.get("id"), "name": g.get("name") or g.get("id"),
                         "custom": keys.get(g.get("custom")) if g.get("custom") else None,
                         "params": [keys[x] for x in (g.get("params") or []) if x in keys]} for g in groups],
             "provisional": bool(desc.get("provisional"))}  # les presets : des fichiers (tools/sync-golem-fx-presets.py)
    return out, sheet


def preset_params(btype, gparams, catalog_params):
    """Les réglages d'un preset de golem-fx (ids et libellés du PLUGIN) dans le vocabulaire du BLOC : l'id que la feuille
    montre, une liste par son RANG (le libellé du catalogue au même rang : « Slow » -> « slow »). Rend (params, refus) ;
    un réglage d'IDENTITÉ du type (`identity`) n'est pas écrit — refusé s'il dit autre chose que ce que le type est."""
    params, sheet = merged(btype, catalog_params)
    if not sheet:
        return {}, ["no golem-fx descriptor for this type"]
    desc, spec = descriptor_for(btype)
    dparams = desc.get("params") or {}
    identity = spec.get("identity") or {}
    by_gid = {d["gfx"]["id"]: d for d in params if d.get("gfx")}
    out, bad = {}, []
    for gid, v in (gparams or {}).items():
        if gid in identity:
            if v != identity[gid]:
                bad.append(f"{gid}={v!r}: this type is {identity[gid]!r}")
            continue
        d, p = by_gid.get(gid), dparams.get(gid)
        if not d or not p:
            bad.append(f"{gid}: unknown parameter")
            continue
        if d.get("type") == "enum":
            popts = p.get("options") or []
            if v not in popts:
                bad.append(f"{gid}={v!r}: not an option")
                continue
            i = popts.index(v)
            opts = d.get("options") or []
            v = opts[i] if i < len(opts) else v
        out[d["id"]] = v
    return out, bad


def _equals_as_block(dep, dparams, cat, keys):
    """La valeur attendue d'une dépendance, dans le vocabulaire du BLOC : un libellé du plugin (« Slow ») devient celui du
    catalogue au même rang (« slow ») quand le réglage visé est un potard du catalogue."""
    eq = dep.get("equals", True)
    target = dparams.get(dep.get("param")) or {}
    c = next((x for x in cat if x["id"] == keys.get(dep.get("param"))), None)
    popts = target.get("options") or []
    if isinstance(eq, str) and c and c.get("type") == "enum" and eq in popts:
        i = popts.index(eq)
        copts = c.get("options") or []
        return copts[i] if i < len(copts) else eq
    return eq


def gfx_only_keys(btype, catalog_params):
    """Les ids de bloc qui n'existent QUE sur le plugin golem-fx (retirés là où golem-fx ne joue pas le bloc)."""
    params, sheet = merged(btype, catalog_params)
    return {d["id"] for d in params if d.get("engine_only") == "golem" and d.get("gfx")} if sheet else set()
