# SPDX-License-Identifier: GPL-3.0-or-later
"""Les PRÊTS de Library au groupe — face rack (docs/library-loans.md).

Un coéquipier prête un son à un groupe ; golem.fm le sert dans `lent[]` du manifeste. Ce module tient
le REGISTRE de provenance (`library/catalog/.lent.json`) et répond à trois questions :
  - où trouver un pack qui n'est pas à nous (`find_pack`, `available_captures`) — tiré À LA DEMANDE,
    jamais d'office (décision « b ») ;
  - qu'est-ce qui, sur ce disque, est un prêt (`is_lent_uid`, `lent_shas`) — pour ne JAMAIS le renvoyer
    chez golem.fm comme s'il était au membre (`filter_packs`, `lent_deps`) ;
  - qu'est-ce que l'écran dit (`status`).
Rien n'est jamais effacé ici : un prêt retiré garde son fichier (patches.md §9.3, un orphelin joue).
"""
import contextlib
import json
import os
import threading
import time

from . import config as C
from .golog import get

log = get("loans")

REG = os.path.join(C.ROOT, "library", "catalog", ".lent.json")
CAPTURE_KINDS = ("amp", "amp-cab", "cab", "pedal")
_lock = threading.RLock()


# ── le registre — UNE SECTION PAR SERVEUR (panneau de dev, 2026-09-30) ─────────────────────────
# Un rack qui bascule entre la prod et golem.fm en local ne doit pas faire survivre en prod un prêt vu
# en local (ni l'inverse) : chaque serveur a sa section. Mais les GARDES (ne jamais repousser, refuser
# au Store) regardent TOUTES les sections : un fichier prêté ne part vers AUCUN serveur.
_KEYS = (("available", {}), ("installed", {}), ("installed_items", {}),
         ("available_items", {}), ("incomplete", []), ("gone", []))


def _server():
    try:
        from .golemfm import _cfg
        return (_cfg()[0] or "").strip().rstrip("/")
    except Exception:
        return ""


def _file():
    try:
        with open(REG, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    if "by_server" not in d:                       # ancienne forme à plat : gardée sous « » (serveur inconnu)
        d = {"by_server": {"": d} if d else {}}
    return d


def _section(d):
    d = dict(d or {})
    d.setdefault("lent_rev", "")
    for k, v in _KEYS:
        d.setdefault(k, type(v)())
    return d


def _load():
    return _section(_file()["by_server"].get(_server()))


def _save(d):
    f = _file()
    f["by_server"][_server()] = d
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    tmp = REG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(f, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, REG)


def _all_installed():
    """(installed, installed_items) de TOUTES les sections — ce que les gardes consultent."""
    inst, items = {}, {}
    for sec in _file()["by_server"].values():
        sec = _section(sec)
        inst.update(sec["installed"])
        items.update(sec["installed_items"])
    return {"installed": inst, "installed_items": items}


def _who(section):
    b, o = section.get("band") or {}, section.get("owner") or {}
    return {"band": b.get("name") or b.get("slug") or b.get("id"), "band_id": b.get("id"),
            "owner": o.get("handle") or o.get("name")}


def _add_who(lst, who):
    if not any(x.get("band_id") == who.get("band_id") and x.get("owner") == who.get("owner") for x in lst):
        lst.append(who)
    return lst


# ── lire le manifeste ────────────────────────────────────────────────────────────────────────
def own_uids(manifest):
    return {str(p.get("uid")) for p in (manifest or {}).get("packs") or [] if p.get("uid")}


def lent_packs(manifest):
    """{uid: (pack, lent_by[])} — les packs prêtés qui ne sont PAS déjà à nous (le nôtre gagne)."""
    mine = own_uids(manifest)
    out = {}
    for sec in (manifest or {}).get("lent") or []:
        who = _who(sec)
        for p in sec.get("packs") or []:
            uid = str(p.get("uid") or "")
            if not uid or uid in mine:
                continue
            if uid in out:
                _add_who(out[uid][1], who)
            else:
                out[uid] = (p, [who])
    return out


def lent_items(manifest):
    """{sha: (item, lent_by[])} — les contenus golem.fm prêtés (samples, sets, kits, grooves)."""
    out = {}
    for sec in (manifest or {}).get("lent") or []:
        who = _who(sec)
        for it in sec.get("items") or []:
            sha = str(it.get("sha") or "")
            if not sha:
                continue
            if sha in out:
                _add_who(out[sha][1], who)
            else:
                out[sha] = (it, [who])
    return out


def find_pack(manifest, uid):
    """(pack, lent_by|None) : NOS packs d'abord, puis les prêtés. (None, None) si personne ne l'a."""
    uid = str(uid)
    for p in (manifest or {}).get("packs") or []:
        if str(p.get("uid")) == uid:
            return p, None
    got = lent_packs(manifest).get(uid)
    return (got[0], got[1]) if got else (None, None)


# ── la synchro relit le registre (tones_sync._worker, après le GET manifest) ─────────────────
def refresh(manifest):
    """Met le registre à jour depuis le manifeste : le disponible, l'incomplet, les pierres tombales ;
    un uid redevenu NÔTRE sort du registre ; un installé qui a quitté `lent[]` -> « no_longer_lent »
    (jamais effacé). Rend le registre."""
    if not isinstance(manifest, dict):
        return _load()
    with _lock:
        d = _load()
        mine = own_uids(manifest)
        lp, li = lent_packs(manifest), lent_items(manifest)
        d["lent_rev"] = manifest.get("lent_rev") or ""
        d["available"] = {uid: {"title": p.get("title") or uid, "kind": p.get("kind"),
                                "catalog_id": str((p.get("extra") or {}).get("catalog_id") or uid.split(":", 1)[-1]),
                                "bytes": sum(int(a.get("bytes") or 0) for a in p.get("assets") or []),
                                "lent_by": who}
                          for uid, (p, who) in lp.items()}
        d["available_items"] = {sha: {"kind": it.get("kind"), "name": it.get("name"), "lent_by": who}
                                for sha, (it, who) in li.items()}
        d["incomplete"], d["gone"] = [], []
        for sec in manifest.get("lent") or []:
            who = _who(sec)
            d["incomplete"] += [{**x, "lent_by": who} for x in sec.get("incomplete") or []]
            d["gone"] += [{**x, "lent_by": who} for x in sec.get("gone") or []]
        for uid in list(d["installed"]):
            if uid in mine:                            # Keep a copy / déjà à nous : ce n'est plus un prêt
                d["installed"].pop(uid)
            elif uid in lp:
                d["installed"][uid].update(state="lent", lent_by=lp[uid][1])
            else:
                d["installed"][uid]["state"] = "no_longer_lent"
        for sha, row in d["installed_items"].items():
            row["state"] = "lent" if sha in li else "no_longer_lent"
            if sha in li:
                row["lent_by"] = li[sha][1]
        _save(d)
        return d


def record_install(uid, pack, lent_by):
    """Après l'installation d'un pack PRÊTÉ : sa provenance, et les sha256 de ses fichiers (pour que les
    packs agrégés — samples, Vital — ne les renvoient pas)."""
    with _lock:
        d = _load()
        d["installed"][str(uid)] = {"title": pack.get("title") or uid, "kind": pack.get("kind"),
                                    "catalog_id": str((pack.get("extra") or {}).get("catalog_id") or str(uid).split(":", 1)[-1]),
                                    "lent_by": lent_by or [], "state": "lent",
                                    "shas": [a.get("sha256") for a in pack.get("assets") or [] if a.get("sha256")],
                                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _save(d)


def record_item(sha, item, lent_by):
    with _lock:
        d = _load()
        d["installed_items"][str(sha)] = {"kind": item.get("kind"), "name": item.get("name"),
                                          "lent_by": lent_by or [], "state": "lent",
                                          "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        _save(d)


# ── ce qui est un prêt sur ce disque ─────────────────────────────────────────────────────────
def is_lent_uid(uid, reg=None):
    return str(uid) in (reg or _all_installed())["installed"]


def lent_shas(reg=None):
    d = reg or _all_installed()
    s = set(d["installed_items"])
    for row in d["installed"].values():
        s.update(x for x in row.get("shas") or [] if x)
    return s


def filter_packs(packs, blob_map=None):
    """LA GARDE DE LA SYNCHRO (docs/library-loans.md §4) : retire des packs à pousser tout ce qui est un
    prêt — un pack entier par son uid, un fichier d'un pack agrégé par son sha256 — et retire ces sha de
    `blob_map` (jamais téléversés). Rend (packs, retirés). Tous serveurs confondus."""
    d = _all_installed()
    uids, shas = set(d["installed"]), lent_shas(d)
    if not uids and not shas:
        return packs, 0
    out, dropped = [], 0
    for p in packs:
        if str(p.get("uid")) in uids:
            dropped += 1
            continue
        assets = [a for a in p.get("assets") or [] if a.get("sha256") not in shas]
        if len(assets) != len(p.get("assets") or []):
            dropped += len(p.get("assets") or []) - len(assets)
            if not assets:
                continue
            p = {**p, "assets": assets}
        out.append(p)
    if blob_map is not None:
        for s in shas:
            blob_map.pop(s, None)
    return out, dropped


def lent_deps(deps):
    """LA GARDE DU STORE : les dépendances d'un export de preset qui sont des prêts — [] si aucune.
    Tous serveurs confondus."""
    d = _all_installed()
    uids, shas = d["installed"], lent_shas(d)
    out = []
    for dep in deps or []:
        uid, sha = str(dep.get("uid") or ""), dep.get("sha256")
        row = uids.get(uid)
        if row or (sha and sha in shas):
            who = (row or {}).get("lent_by") or []
            out.append({"uid": uid or None, "title": (row or {}).get("title") or dep.get("name") or uid,
                        "owner": (who[0] if who else {}).get("owner")})
    return out


# ── tirer à la demande ───────────────────────────────────────────────────────────────────────
def available_for_ref(ref, reg=None):
    """L'uid d'un pack PRÊTÉ (disponible, pas encore chez nous) qui porte ce `ref` — id de catalogue
    (« 44209 ») ou uid (« t3k:44209 »). None sinon."""
    if not ref:
        return None
    d = reg or _load()
    ref = str(ref).split("/")[-1]
    if ref in d["available"]:
        return ref
    for uid, row in d["available"].items():
        if row.get("catalog_id") == ref or uid.split(":", 1)[-1] == ref:
            return uid
    return None


def missing_lent_refs(preset):
    """Les uids PRÊTÉS dont une capture du preset a besoin et que le rack n'a pas (résolution locale,
    sans réseau). Vide dans le cas courant : c'est ce qui rend l'appel bon marché à chaque rappel."""
    from .store import lanes_of, _lane_chain_blocks
    from .resolver import _components, _resolve
    from .tones_jobs import CAPTURE_TYPES
    d = _load()
    if not d["available"]:
        return []
    comps, out = None, []
    for L in lanes_of(preset or {}):
        for b in _lane_chain_blocks(L.get("chain") or {}):
            if not isinstance(b, dict) or b.get("type") not in CAPTURE_TYPES or not b.get("ref"):
                continue
            comps = comps if comps is not None else _components()
            if _resolve(b["ref"], comps, b.get("model")) is not None:
                continue
            uid = available_for_ref(b["ref"], d)
            if uid and uid not in out:
                out.append(uid)
    return out


_pulling = set()
_tried = {}                        # uid -> heure de la dernière tentative
RETRY_S = 600.0


def pull_for_preset(preset, on_done=None):
    """Au RAPPEL d'un preset : si une de ses captures manque et qu'elle est prêtée, on l'installe en tâche
    de fond, puis `on_done()` (la sandbox est reposée par l'appelant). Ne bloque jamais le rappel.
    ⚠ Une tentative par uid et par RETRY_S : une install « réussie » dont le ref ne résoudrait toujours
    pas relancerait sinon install -> sandbox reposée -> install… sans fin."""
    now = time.time()
    uids = [u for u in missing_lent_refs(preset)
            if u not in _pulling and now - _tried.get(u, 0) > RETRY_S]
    if not uids:
        return []
    for u in uids:
        _tried[u] = now

    def work():
        from .tones_jobs import _install
        got = []
        for uid in uids:
            _pulling.add(uid)
            try:
                _install(uid)
                got.append(uid)
            except Exception as e:
                log.warning(f"prêt {uid} non installé : {e}")
            finally:
                _pulling.discard(uid)
        if got and on_done:
            with contextlib.suppress(Exception):
                on_done(got)
    threading.Thread(target=work, daemon=True, name="loans-pull").start()
    return uids


_ALL = {"running": False, "done": 0, "total": 0, "errors": []}


def pull_all():
    """« Download all lent » : tout ce qui est prêté et pas encore là — packs (sauf incomplets) et items."""
    if _ALL["running"]:
        return dict(_ALL)
    from .resolver import _tones_index
    d = _load()
    incomplete = {str(x.get("ref")) for x in d["incomplete"]}
    have = set(_tones_index())
    packs = [u for u, row in d["available"].items()
             if u not in d["installed"] and u not in incomplete and u.split(":", 1)[-1] not in have
             and row.get("catalog_id") not in have]
    items = [s for s in d["available_items"] if s not in d["installed_items"]]
    _ALL.update(running=True, done=0, total=len(packs) + len(items), errors=[])

    def work():
        from . import tones_jobs as TJ
        try:
            for uid in packs:
                try:
                    TJ._install(uid)
                except Exception as e:
                    _ALL["errors"].append({"uid": uid, "why": str(e)[:200]})
                _ALL["done"] += 1
            for sha in items:
                row = d["available_items"][sha]
                try:
                    install_item(sha, row)
                except Exception as e:
                    _ALL["errors"].append({"sha": sha, "why": str(e)[:200]})
                _ALL["done"] += 1
        finally:
            _ALL["running"] = False
    threading.Thread(target=work, daemon=True, name="loans-pull-all").start()
    return dict(_ALL)


def install_item(sha, row):
    """Un item golem.fm prêté, par les jobs qui les installent déjà (le blob passe par la même route)."""
    from . import tones_jobs as TJ
    kind, name = row.get("kind"), row.get("name") or sha[:12]
    job = {"sha": sha, "name": name}
    if kind == "kit":
        TJ._kit_install(job)
    elif kind in ("groove",):
        TJ._groove_install(job)
    elif kind in ("groove-pack", "groove_pack"):
        TJ._groove_pack(job)
    elif kind in ("set", "sample-pack", "sample_pack"):
        TJ._sample_pack(job)
    elif kind == "sample":
        import re
        fn = re.sub(r"[^A-Za-z0-9._ -]", "-", name).strip() or sha[:12]
        if not os.path.splitext(fn)[1]:
            fn += ".wav"
        TJ._download_raw(sha, os.path.join(C.ROOT, "assets", "samples", fn))
    else:
        raise RuntimeError(f"lent item kind {kind!r} not handled on the rack")
    record_item(sha, row, row.get("lent_by"))


def status():
    d = _load()
    # par id de CATALOGUE : c'est ce que l'écran connaît d'un son (tones-index), pas l'uid de pack
    by_catalog = {row.get("catalog_id") or uid.split(":", 1)[-1]: {"uid": uid, "state": row.get("state"),
                                                                   "lent_by": row.get("lent_by") or []}
                  for uid, row in d["installed"].items()}
    return {"lent_rev": d["lent_rev"], "by_catalog": by_catalog,
            "available": d["available"], "available_items": d["available_items"],
            "installed": d["installed"], "installed_items": d["installed_items"],
            "incomplete": d["incomplete"], "gone": d["gone"],
            "pending": len([u for u in d["available"] if u not in d["installed"]])
                       + len([s for s in d["available_items"] if s not in d["installed_items"]]),
            "pull_all": dict(_ALL)}
