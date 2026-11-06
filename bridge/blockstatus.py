# SPDX-License-Identifier: GPL-3.0-or-later
"""ÉTAT DES BLOCS (docs/block-status.md) — ce qui manque se voit, se télécharge ou se remplace.

Chaque bloc d'un preset a un état calculé ICI, à partir de ce que la machine a vraiment :
  · `ready`       tout est là ;
  · `download`    la capture manque, une source la connaît (golem.fm : nos packs ou un prêt ; TONE3000) ;
  · `unavailable` rien ne peut la faire venir : plugin absent de CETTE machine, quarantaine, fichier de
                  mauvaise nature, capture que personne ne connaît ;
  · `empty`       bloc à capture sans capture choisie (le « ∅ » du Designer).
Un bloc qui n'est pas `ready` est coupé par la compile (rig._usable) et barré à l'écran — jamais muet
sans le dire, jamais remplacé sans le demander.

Plugins : l'inventaire de REAPER (presets/.fx-inventory.json, golem_fxinventory.lua) prédit ; le constat
de golem_rig (presets/.rig-plugins.json) l'emporte. Pas d'inventaire lisible → état INCONNU, dit comme tel
(`caps.inventory: false`), et rien n'est barré sur une ignorance."""
import contextlib
import json
import logging
import os
import platform
import re
import threading
import time
import sys

from . import config as C

log = logging.getLogger("golem.blockstatus")

INVENTORY = os.path.join(C.PRESETS_DIR, ".fx-inventory.json")
OBSERVED = os.path.join(C.PRESETS_DIR, ".rig-plugins.json")
RIG_LUA = os.path.join(C.ROOT, "reaper", "Scripts", "golem_rig.lua")

# les blocs dont le son vient d'un fichier — MÊME liste que rig.CAPTURE_TYPES (importée plus bas)
_PREFIX = re.compile(r"^\s*(vst3i?|vsti?|lv2i?|clapi?|js|au|dx)\s*:\s*", re.I)


def _mtime_cache():
    return {"mtime": None, "val": None}


_WINDOWS_EFFECTS = _mtime_cache()
WINDOWS_EFFECTS = os.path.join(C.ROOT, "library", "catalog", "effects-windows.json")
MACOS_EFFECTS = os.path.join(C.ROOT, "library", "catalog", "effects-macos.json")   # M6, 2026-10-04


def desktop_table():
    """La table de plugins de CET OS desktop (golem_rig.lua lit la même : DESKTOP_TABLE), ou None (rack)."""
    return {"win32": WINDOWS_EFFECTS, "darwin": MACOS_EFFECTS}.get(sys.platform)


_EFFECTS = _mtime_cache()
_ALIAS = _mtime_cache()
_INV = _mtime_cache()


def _cached(slot, path, load):
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = None
    if slot["val"] is None or slot["mtime"] != mt:
        slot["val"] = load(path) if mt is not None else None
        slot["mtime"] = mt
    return slot["val"]


def effects():
    """{type: entrée effects.json}."""
    def load(p):
        return {e.get("type"): e for e in json.load(open(p)).get("effects", []) if e.get("type")}
    base = _cached(_EFFECTS, C.EFFECTS, load) or {}
    table = desktop_table()
    if table is None:
        return base
    if _WINDOWS_EFFECTS.get("path") != table:          # un cache par table (les tests changent d'OS)
        _WINDOWS_EFFECTS.update(mtime=None, val=None, path=table)
    try:
        overrides = _cached(_WINDOWS_EFFECTS, table,
                            lambda p: json.load(open(p, encoding="utf-8")).get("effects", {})) or {}
    except (OSError, ValueError):
        overrides = {}
    return {t: {**entry, **overrides[t], "windows_strict": True} if t in overrides else entry
            for t, entry in base.items()}


def aliases():
    """ADD_ALIAS de golem_rig, lu dans SON source : une seule liste de noms de repli, pas deux."""
    def load(p):
        lua = open(p, encoding="utf8").read()
        i = lua.index("local ADD_ALIAS")
        body = lua[i:lua.index("\n}", i)]
        out = {}
        for m in re.finditer(r'^\s*\[?"?([\w-]+)"?\]?\s*=\s*\{([^}]*)\}', body, re.M):
            out[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
        return out
    try:
        return _cached(_ALIAS, RIG_LUA, load) or {}
    except (OSError, ValueError) as e:
        log.warning(f"ADD_ALIAS illisible dans golem_rig.lua : {e}")
        return {}


def candidates(btype):
    """Les noms que golem_rig essaie, DANS SON ORDRE : effects.json `plugin`, ADD_ALIAS, le type."""
    if sys.platform in ("win32", "darwin") and btype in ("amp", "amp-nam", "cab"):
        return ["VST3: NeuralAmpModeler"]
    e = effects().get(btype) or {}
    if e.get("unsupported"):
        return []
    if e.get("windows_strict"):
        return [e["plugin"]] if e.get("plugin") else []
    out = []
    for n in [e.get("plugin")] + list(aliases().get(btype) or []) + [btype]:
        if n and n not in out:
            out.append(n)
    return out


def is_plugin_block(btype):
    """Un bloc que golem_rig pose par TrackFX_AddByName (add_block_fx). Les moteurs à part (rs5k, sfizz,
    dexed, b3, drumkit…) n'ont pas de nom de plugin déclaré : leur état est INCONNU (block-status.md §3)."""
    if sys.platform in ("win32", "darwin") and btype in ("amp", "amp-nam", "cab"):
        return True
    e = effects().get(btype) or {}
    return bool(e.get("plugin")) and e.get("engine") in ("plugin", None)


def inventory():
    """L'inventaire Reaper : {at, reaper, os, names:set, idents:set} ou None s'il n'est pas lisible."""
    def load(p):
        d = json.load(open(p))
        if d.get("error") or not isinstance(d.get("fx"), list):
            return {"error": d.get("error") or "no fx list", "reaper": d.get("reaper")}
        names, qualified_names, idents = set(), set(), set()
        for row in d["fx"]:
            if isinstance(row, list) and row:
                names.add(_norm(row[0]))
                qualified_names.add(str(row[0]).strip().casefold())
                if len(row) > 1 and row[1]:
                    idents.add(str(row[1]).lower())
        return {"at": d.get("at"), "reaper": d.get("reaper"), "os": d.get("os"), "names": names,
                "idents": idents, "qualified_names": qualified_names, "n": len(d["fx"])}
    try:
        inv = _cached(_INV, INVENTORY, load)
    except (OSError, ValueError) as e:
        log.warning(f"inventaire des plugins illisible : {e}")
        return None
    return inv if inv and not inv.get("error") else None


def _norm(name):
    return _PREFIX.sub("", str(name or "")).strip().lower()


def _in_inventory(name, inv, strict=False):
    """Le nom qu'on donnerait à TrackFX_AddByName se trouve-t-il dans ce que Reaper a scanné ?
    AddByName accepte un nom partiel (« ReaComp » pose « VST: ReaComp (Cockos) ») : on compare en
    sous-chaîne, préfixe de format retiré ; un chemin JS (« JS:golem/x ») se compare à l'identifiant."""
    n = _norm(name)
    if strict and "/" not in n:
        # Les alias Linux restent permissifs ; un mapping natif conserve son format. Un JSFX nommé par son
        # CHEMIN (« JS:golem/golem_eq », table desktop 2026-10-22) se juge à son fichier, plus bas : son nom
        # affiché (« JS: GoleM Parametric EQ ») ne contient pas le chemin.
        prefix = _PREFIX.match(str(name))
        if prefix:
            fmt = prefix.group().strip().casefold()
            return any(full.startswith(fmt) and n in _norm(full)
                       for full in inv.get("qualified_names", set()))
    if not n:
        return False
    if "/" in n:                                         # chemin JSFX : golem/golem_killswitch[.jsfx]
        stem = n[:-5] if n.endswith(".jsfx") else n
        return any(i == stem or i.startswith(stem + ".") or i.endswith("/" + stem) or stem in i for i in inv["idents"])
    if any(n in full for full in inv["names"]):
        return True
    # un JSFX se désigne aussi par son FICHIER (« golem_deesser » → golem/golem_deesser.jsfx) : son nom
    # affiché (« GoleM De-esser ») ne le contient pas, et le repli sur le type (« deesser ») attraperait
    # le Calf Deesser — un autre plugin. Qu'on compare au fichier AVANT d'en arriver là.
    return any(i.rsplit("/", 1)[-1].split(".")[0] == n for i in inv["idents"] if "/" in i)


def observed():
    """Le constat de golem_rig : {type: {ok, name, at}}."""
    try:
        d = json.load(open(OBSERVED))
        t = d.get("types") if isinstance(d, dict) else None
        return t if isinstance(t, dict) else {}
    except (OSError, ValueError):
        return {}


def plugin_state(btype, inv=None, obs=None):
    """True = le plugin est là ; False = absent ICI ; None = on ne sait pas (non-plugin, pas d'inventaire)."""
    if effects().get(btype, {}).get("unsupported"):
        return False
    obs = observed() if obs is None else obs
    seen = obs.get(btype)
    inv = inventory() if inv is None else inv
    predicted = None
    if is_plugin_block(btype) and inv is not None:
        strict = bool(effects().get(btype, {}).get("windows_strict")) or (
            sys.platform in ("win32", "darwin") and btype in ("amp", "amp-nam", "cab"))
        predicted = any(_in_inventory(n, inv, strict=strict) for n in candidates(btype))
    # le constat l'emporte sur la prédiction — AUSSI pour les moteurs à part (drumkit…), dont on ne sait
    # rien prédire mais dont golem_rig dit s'il a pu les poser (2026-10-03 : kit « ready » sans moteur)…
    # SAUF un échec PLUS VIEUX que l'inventaire qui voit maintenant le plugin (2026-10-22 : Dragonfly installé,
    # REAPER relancé, le bloc restait « not installed » sur la foi d'un rappel d'avant l'installation)
    if isinstance(seen, dict) and "ok" in seen:
        stale = (not seen["ok"] and predicted and isinstance(inv.get("at"), (int, float))
                 and isinstance(seen.get("at"), (int, float)) and inv["at"] > seen["at"])
        if not stale:
            return bool(seen["ok"])
    if not is_plugin_block(btype):
        return None
    return predicted


def unavailable_types():
    """Les types de blocs À PLUGIN absents de cette machine (inventaire ou constat)."""
    inv, obs = inventory(), observed()
    return sorted(t for t in effects() if plugin_state(t, inv, obs) is False)


def caps():
    """Ce que le rack publie de lui-même au battement (block-status.md §7)."""
    from . import rig
    inv = inventory()
    at = None
    if inv and inv.get("at"):
        with contextlib.suppress(Exception):
            at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(inv["at"])))
    ver = None
    with contextlib.suppress(Exception):
        from .rigstatus import reaper_version
        ver = reaper_version()
    out = {"os": platform.system().lower(), "engine": "reaper", "engine_version": ver,
           "inventory": inv is not None, "inventory_at": at,
           "unavailable": unavailable_types(), "quarantine": sorted(rig.quarantined_types()),
           "nam_unreadable": rig.nam_unreadable(),
           # docs/compo.md §12 : le rack joue le bed d'une prise armée — golem.fm n'en envoie qu'à un rack qui le dit
           "compo_bed": True}
    # docs/separation.md §10 : {stems, rtf} du moteur actif testé — jamais son nom ; pas de moteur → pas de clé
    with contextlib.suppress(Exception):
        from . import separation
        sep = separation.caps()
        if sep:
            out["separation"] = sep
    return out


# ── les sources d'une capture absente ──────────────────────────────────────────────────────
_MANIFEST = {"at": 0.0, "tones": None}
_MANIFEST_TTL = 120.0
_MLOCK = threading.Lock()


def manifest_tones(fresh=False):
    """Ce que golem.fm peut nous envoyer (nos packs + les prêts), gardé 2 min : l'écran redemande
    l'état à chaque chargement, golem.fm n'a pas à répondre à chaque fois."""
    with _MLOCK:
        if fresh or _MANIFEST["tones"] is None or time.monotonic() - _MANIFEST["at"] > _MANIFEST_TTL:
            try:
                from .tones_jobs import _manifest_tones
                _MANIFEST["tones"] = _manifest_tones()
            except Exception as e:
                log.warning(f"manifest golem.fm : {e}")
                _MANIFEST["tones"] = _MANIFEST["tones"] or []
            _MANIFEST["at"] = time.monotonic()
        return list(_MANIFEST["tones"] or [])


def _tid(ref):
    cid = str(ref).split("/")[-1]
    return cid.split(":", 1)[1] if cid.startswith("t3k:") else cid


def _capture_state(b, comps, manifest_fn):
    """(state, why, extra) d'un bloc à capture."""
    from . import rig
    from .resolver import _resolve
    ref = b.get("ref")
    if not ref:
        return "empty", "no capture chosen", {}
    f = _resolve(ref, comps, b.get("model"))
    if f and os.path.isfile(f):
        bad = rig._wrong_kind(b, f)
        if bad:
            return "unavailable", bad, {"ref": ref}
        return "ready", None, {"ref": ref}
    tid = _tid(ref)
    pack = next((t for t in manifest_fn() if str(t.get("id")) == tid), None)
    if pack is not None:
        why = "not on this rack — on golem.fm" + (f" (lent by {pack['lent_by']})" if pack.get("lent_by") else "")
        return "download", why, {"ref": ref, "source": "golem.fm", "uid": pack.get("uid"),
                                 "bytes": int(pack.get("bytes") or 0) or None, "title": pack.get("title")}
    if str(ref).split("/")[-1].startswith("t3k:") or tid.isdigit():
        return "download", "not on this rack — on TONE3000", {"ref": ref, "source": "tone3000", "tid": tid,
                                                               "uid": f"t3k:{tid}", "bytes": None}
    return "unavailable", ("file missing on disk" if f else "capture unknown here and on golem.fm"), {"ref": ref}


def install_playable(b):
    """Raison `format` (capture A2 hors Linux) : tire de TONE3000 la jumelle classique de la capture que le
    bloc joue (même pack, même nom) — resolver.playable_twin la fait jouer ensuite. Rend les noms posés."""
    from .resolver import _tones_index
    from .routes_t3k import install_twins
    tid = _tid(b.get("ref") or "")
    tone = _tones_index().get(tid)
    if not tone or not tone.get("models"):
        raise RuntimeError("this capture's pack is not on this rack")
    models = tone["models"]
    m = next((x for x in models if str(x.get("id")) == str(b.get("model"))), None) if b.get("model") is not None else None
    return install_twins(tid, [(m or models[0]).get("name")])


# `why` est AFFICHÉ (feuille du bloc, bandeau de golem.fm) : en anglais. La raison mesurée du catalogue
# (`effects.json` `quarantine`, en français, pour nous) part à côté dans `detail` — vu le 2026-10-01
# sur l'écran du Designer, la phrase française de ReaPitch s'affichait telle quelle à l'utilisateur.
QUARANTINE_WHY = "quarantined — this plugin is known to freeze or crash the audio engine"
LINUX_ONLY_WHY = "only available on a Linux golem — its plugin does not exist on this system"


def block_state(b, comps=None, manifest_fn=None, inv=None, obs=None):
    """{state, why, …} d'UN bloc."""
    from . import rig
    from .resolver import _components
    t = b.get("type")
    if t == "vst-host":
        inv = inventory() if inv is None else inv
        name = b.get("plugin") or ""
        # Deux refus qui ne se ressemblent pas : ailleurs que sous Windows le bloc ne se pose
        # JAMAIS (golem_rig le saute) — dire « invalid plugin » d'un plugin parfaitement valide
        # enverrait chercher une faute dans le preset, alors que c'est la machine qui ne joue pas.
        if sys.platform not in ("win32", "darwin"):
            return {"state": "unavailable", "why": "VST Host blocks only play on a Windows or macOS golem",
                    "reason": "plugin"}
        if not re.match(r"^(?:VST3?i?|CLAPi?):", name):
            return {"state": "unavailable", "why": "invalid plugin name", "reason": "plugin"}
        from . import rig
        why = rig.quarantined_plugin(name)
        if why:
            return {"state": "unavailable", "why": QUARANTINE_WHY, "reason": "quarantine", "detail": why}
        if inv is not None and name.strip().casefold() not in inv.get("qualified_names", set()):
            return {"state": "unavailable", "why": "plugin not installed on this machine", "reason": "plugin"}
        return {"state": "ready", "why": None, "plugin_known": inv is not None}
    q = rig.quarantined_types()
    if t in q:
        return {"state": "unavailable", "why": QUARANTINE_WHY, "reason": "quarantine", "detail": q[t]}
    # `unsupported` de la table desktop : golem_rig ne posera JAMAIS ce bloc sur cet OS, inventaire ou
    # pas. « plugin not installed » laissait chercher un plugin à installer (2026-10-20) : on dit que
    # c'est la machine, et la feuille propose un VST Host. La raison mesurée (FR) part dans `detail`.
    if desktop_table() is not None and effects().get(t, {}).get("unsupported"):
        return {"state": "unavailable", "why": LINUX_ONLY_WHY, "reason": "plugin", "linux_only": True,
                "detail": effects()[t]["unsupported"]}
    if t in rig.CAPTURE_TYPES:
        ps = plugin_state(t, inv, obs)
        if ps is False:
            return {"state": "unavailable", "why": "plugin not installed on this machine", "reason": "plugin"}
        st, why, extra = _capture_state(b, comps if comps is not None else _components(), manifest_fn or manifest_tones)
        # `format` et pas `capture` : la capture est là et elle est bonne, c'est le moteur NAM de CETTE
        # machine qui ne lit pas son format (A2 hors Linux, rig.A2_DESKTOP_WHY) — la télécharger
        # ailleurs n'y changerait rien. Même mot que golem.fm.
        reason = None if st == "ready" else ("format" if why == rig.A2_DESKTOP_WHY else "capture")
        return dict({"state": st, "why": why, "reason": reason}, **extra)
    ps = plugin_state(t, inv, obs)
    if ps is False:
        return {"state": "unavailable", "why": "plugin not installed on this machine", "reason": "plugin"}
    return {"state": "ready", "why": None, "plugin_known": ps is not None}


def _drumkit_state(b, preset, inv):
    """Un bloc drumkit se juge sur les KITS qu'il joue (son réglage et celui de chaque scène), pas sur un
    constat par type : sous Windows, Black Pearl joue (AVL Drumkits) et Aasimonster non (ni DrumGizmo ni ses
    2,3 Go d'échantillons) — 2026-10-03, un patch Aasimonster s'affichait « ready » et ne sonnait pas."""
    from . import kits
    ids = [((b.get("params") or {}).get("kit"))]
    for sc in (preset or {}).get("scenes") or []:
        ids.append(((sc.get("params") or {}).get(b.get("id")) or {}).get("kit"))
    for kid in [k for k in dict.fromkeys(ids) if k]:
        kit = kits.get_kit(kid)
        if not kit:
            return {"state": "unavailable", "why": f"drum kit « {kid} » is not on this machine", "reason": "plugin"}
        ok, why = kits.availability(kit, inv)
        if ok is False:
            return {"state": "unavailable", "why": f"{kit.get('name') or kid}: {why}", "reason": "plugin"}
    return None


def preset_status(preset, manifest_fn=None):
    """L'état de chaque bloc d'un preset + le résumé du bandeau (« 3 blocks missing — 38 MB »)."""
    from .resolver import _components
    from .store import all_blocks
    comps, inv, obs = _components(), inventory(), observed()
    cache = {}

    def mf():                                            # le manifeste n'est demandé que s'il sert
        if "m" not in cache:
            cache["m"] = (manifest_fn or manifest_tones)()
        return cache["m"]
    blocks = []
    for b, lane in all_blocks(preset or {}):
        if not isinstance(b, dict) or not b.get("type"):
            continue
        s = block_state(b, comps, mf, inv, obs)
        if b.get("type") == "drumkit" and s.get("state") == "ready":
            s = _drumkit_state(b, preset, inv) or s
        if s.get("state") == "unavailable":
            s = dict(s, alternatives=_alts(b.get("type"), _role(preset, lane), cache))
        blocks.append(dict(s, lane=lane, id=b.get("id"), type=b.get("type"),
                           label=b.get("label") or b.get("name")))
    dl = [x for x in blocks if x["state"] == "download"]
    summary = {"missing": sum(1 for x in blocks if x["state"] != "ready"),
               "download": {"n": len(dl), "bytes": sum(x.get("bytes") or 0 for x in dl),
                            "unknown": sum(1 for x in dl if not x.get("bytes"))},
               "unavailable": sum(1 for x in blocks if x["state"] == "unavailable"),
               "empty": sum(1 for x in blocks if x["state"] == "empty")}
    return {"preset": (preset or {}).get("id"), "blocks": blocks, "summary": summary,
            "caps": {"inventory": inv is not None}}


ALTS_MAX = 8


def _role(preset, lane):
    """Le rôle de la lane d'un bloc ; None pour les lanes config (gen/rec/arr), qui n'en ont pas."""
    if lane in ("gen", "rec", "arr"):
        return None
    from . import patches as P
    try:
        return P.role_of_lane(preset, lane)
    except Exception:
        return None


def _alts(btype, role, cache):
    """Les remplaçants PROPOSÉS d'un bloc indisponible (§6) : `alternatives()` borné, calculé une fois par (type, rôle).
    Sans les pédales MIDI externes : le rack connaît son interface MIDI, pas la pédale branchée derrière — proposer
    un appareil que le musicien n'a peut-être pas n'est pas un remplaçant (golem.fm, 2026-10-28)."""
    k = ("alts", btype, role)
    if k not in cache:
        fx = effects()
        cache[k] = [a for a in alternatives(btype, role)["blocks"]
                    if (fx.get(a["type"]) or {}).get("engine") != "midi"][:ALTS_MAX]
    return cache[k]


def alternatives(btype, role=None):
    """Les blocs de la MÊME catégorie, disponibles ici, hors quarantaine, offerts à ce rôle."""
    from . import rig
    fx = effects()
    cat = (fx.get(btype) or {}).get("category")
    if not cat:
        return {"category": None, "blocks": []}
    try:
        data = json.load(open(C.EFFECTS))
    except (OSError, ValueError):
        data = {}
    role_blocks = (data.get("role_blocks") or {}).get(role) if role else None
    q, inv, obs = rig.quarantined_types(), inventory(), observed()
    out = []
    for t, e in fx.items():
        if t == btype or e.get("category") != cat or t in q or e.get("engine") in ("virtual", "mode"):
            continue
        if isinstance(role_blocks, list) and t not in role_blocks:
            continue
        roles = e.get("roles")
        if role and isinstance(roles, list) and role not in roles:
            continue
        if plugin_state(t, inv, obs) is False:
            continue
        out.append({"type": t, "name": e.get("name") or t})
    return {"category": cat, "blocks": out}


def suggestion(b, manifest_fn=None):
    """La capture POSSÉDÉE ou chez golem.fm que le nom du bloc désigne — une PROPOSITION (§6), jamais
    posée dans le document. {ref, title, score, source, retyped?} ou None."""
    from . import patches as P
    from .resolver import _tones_index
    label = b.get("label") or b.get("name")
    t = b.get("type")
    if not label or t not in P.BLOCK_GEARS and t not in P.AMP_FAMILY:
        return None
    for source, tones in (("rack", lambda: list(_tones_index().values())), ("golem.fm", manifest_fn or manifest_tones)):
        tone, info, ntype = P.match_capture_family(label, t, tones())
        if tone is not None:
            # `ref` = la forme canonique du RACK (id de catalogue) ; `uid` = celle que golem.fm résout telle
            # quelle (`t3k:<id>` ou `local:…`, la même que la synchro pousse) — demande golem.fm 2026-09-30
            if source == "rack":
                from .tones_sync import _uid
                uid = _uid(tone)
            else:
                uid = tone.get("uid")
            out = {"block": b.get("id"), "type": t, "label": label, "ref": str(tone["id"]), "uid": uid,
                   "title": tone.get("title"), "score": round(info, 2), "source": source}
            if ntype != t:
                out["retyped"] = ntype
            return out
    return None


# ── téléchargement à la demande (tâche de fond) ─────────────────────────────────────────────
_FETCH = {"running": False, "done": [], "failed": [], "total": 0, "preset": None}
_FLOCK = threading.Lock()


def fetch_status():
    with _FLOCK:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _FETCH.items()}


def _fetch_one(item):
    if item.get("source") == "golem.fm" and item.get("uid"):
        from .tones_jobs import _install
        return _install(item["uid"])
    if item.get("source") == "tone3000" and item.get("tid"):
        from .tones_jobs import _t3k_install
        return _t3k_install({"tone_id": item["tid"]})
    raise RuntimeError("no source to download from")


def fetch(preset, ids=None, on_done=None):
    """Tire en tâche de fond les blocs `download` du preset (ceux de `ids`, ou tous). Un uid/tid n'est
    tiré qu'une fois même si deux blocs le partagent. `on_done(done)` quand au moins un est arrivé."""
    st = preset_status(preset)
    want = [x for x in st["blocks"] if x["state"] == "download" and (not ids or x["id"] in ids)]
    seen, todo = set(), []
    for x in want:
        key = x.get("uid") or ("t3k:" + str(x.get("tid")))
        if key not in seen:
            seen.add(key)
            todo.append(x)
    with _FLOCK:
        if _FETCH["running"]:
            raise RuntimeError("a download is already running")
        if not todo:
            return []
        _FETCH.update(running=True, done=[], failed=[], total=len(todo), preset=(preset or {}).get("id"))

    def work():
        done = []
        for x in todo:
            try:
                msg = _fetch_one(x)
                done.append(x["id"])
                with _FLOCK:
                    _FETCH["done"].append({"block": x["id"], "msg": msg})
            except Exception as e:
                log.warning(f"téléchargement du bloc {x['id']} ({x.get('uid') or x.get('tid')}) : {e}")
                with _FLOCK:
                    _FETCH["failed"].append({"block": x["id"], "why": str(e)})
        with _FLOCK:
            _FETCH["running"] = False
        if done and on_done:
            with contextlib.suppress(Exception):
                on_done(done)
    threading.Thread(target=work, daemon=True, name="block-fetch").start()
    return [x["id"] for x in todo]
