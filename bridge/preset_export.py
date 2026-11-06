# SPDX-License-Identifier: GPL-3.0-or-later
"""Export « preset complet » vers golem.fm — côté rack du Store de presets
(Sprint 5.A.4, contrat docs/message-maestrium.md + docs/archive/preset-schema.md).

Produit, pour un preset donné :
  { schema_version, preset (DOC NATIF tel qu'édité), deps[], foot_context?, unresolved? }

- `preset` : le doc natif complet (graphe pre/split/post par entrée, blocs
  type/id/ref/params/model, scènes A–H, exp1/exp2, foot par bloc). AUCUNE
  transformation — c'est la vérité du graphe, versionnée par `schema_version`.
- `deps` : manifest PLAT dédupliqué des assets référencés — [{sha256, uid, kind,
  bytes, name, source}]. `source: "t3k"` (capture TONE3000, tirée par le rack à
  l'install via son compte T3K) | `"golemfm"` (kit, .vital, capture perso :
  résolue depuis le blob store golem.fm par sha256). Les documents d'avant le 2026-10-15 portent `"maestrium"`, l'ancien
  nom de golem.fm : lu partout comme `"golemfm"` (STORE_SOURCES), jamais plus écrit. `sha256` = clé de dédup.
- `foot_context` : slot(s) de banks FCB où le preset est épinglé (jeu live).
- `unresolved` : blocs à asset dont le fichier est absent du rack — golem.fm
  bloque la publication tant qu'il en reste (miroir de sa validation).

La résolution asset→sha256 réutilise tones_sync.build_packs (les MÊMES packs que
la tones-sync) : zéro logique de hash dupliquée, cache sha partagé.
"""
import hashlib
import json
import os

from . import config as C
from . import store, tones_sync, inputmap as _inputmap

SCHEMA_VERSION = 1
CAP_TYPES = ("amp", "amp-nam", "cab", "pedal-nam", "preamp-nam", "comp-nam")


# la `source` d'un asset servi par le store golem.fm (accord golem.fm du 2026-10-15) : on écrit `golemfm` ; `maestrium`,
# l'ancien nom, reste LU pour toujours — des presets publiés le portent, et golem.fm les ressert tels quels
STORE_SOURCE = "golemfm"
STORE_SOURCES = ("golemfm", "maestrium")


def _iter_blocks(preset):
    """Tous les blocs porteurs d'asset, TOUTES lanes confondues (lot 4 : N lanes, v2 ou legacy)."""
    from .store import all_blocks
    for b, lane in all_blocks(preset):
        if isinstance(b, dict) and lane != "arr":
            yield b


def _indexes(packs):
    """Index des packs (build_packs) par clé de référence d'un bloc :
    captures par catalog_id, kits par kit_id, .vital par nom d'asset,
    samples one-shot par chemin (extra.rel = ce que params.samples référence)."""
    caps, kits, vitals, samples, grooves = {}, {}, {}, {}, {}
    for p in packs:
        ex = p.get("extra") or {}
        if p.get("kind") == "kit" and ex.get("kit_id") is not None:
            kits[str(ex["kit_id"])] = p
        elif p.get("kind") == "synth":                       # packs .vital
            for a in p.get("assets") or []:
                nm = (a.get("name") or "").strip().lower()
                vitals[nm] = (p, a)
                vitals[nm.replace(" ", "_")] = (p, a)
        elif p.get("kind") == "sample":                      # samples one-shot (bloc sample)
            for a in p.get("assets") or []:
                rel = (a.get("extra") or {}).get("rel")
                if rel:
                    samples[rel] = (p, a)
                    samples[os.path.normpath(rel)] = (p, a)
        elif p.get("kind") == "groove":                      # un .mid par pack (bloc drums : params.patterns/fills)
            for a in p.get("assets") or []:
                rel = (a.get("extra") or {}).get("rel")
                if rel:
                    grooves[rel] = (p, a)
                    grooves[os.path.normpath(rel)] = (p, a)
        elif ex.get("catalog_id") is not None:               # captures NAM/IR
            caps[str(ex["catalog_id"])] = p
    return caps, kits, vitals, samples, grooves


def _dep(pack, asset):
    uid = pack.get("uid") or ""
    d = {
        "sha256": asset["sha256"],
        "uid": uid,
        "kind": pack.get("kind"),
        "bytes": asset.get("bytes"),
        "name": asset.get("name") or pack.get("title"),   # la CAPTURE (le model utilisé)
        # t3k = tiré du compte TONE3000 du rack ; sinon résolu depuis le store golem.fm
        "source": "t3k" if uid.startswith("t3k:") else STORE_SOURCE,
    }
    if (pack.get("extra") or {}).get("factory"):
        d["factory"] = True                                  # livré avec chaque golem : golem.fm ne le transfère pas
    # NOM DU GEAR (ampli/pédale) distinct de la capture — golem.fm groupe par `uid` et affiche
    # « ampli + ses captures » (Ré-réponse 10). + arch NAM (badge A2) + marque/créateur/url si dispo.
    amp = pack.get("title")
    if amp and amp != d["name"]:
        d["amp"] = amp
    arch = (asset.get("extra") or {}).get("arch")
    if arch is not None:
        d["arch"] = str(arch)
    for k in ("brand", "creator", "url"):
        if pack.get(k):
            d[k] = pack[k]
    return d


def _resolve(block, caps, kits, vitals):
    """(pack, [assets]) référencés par ce bloc, ou None si non résoluble."""
    t = block.get("type")
    if t in CAP_TYPES and block.get("ref") is not None:
        # LA MÊME RÈGLE QUE LE MOTEUR (resolver._resolve, 2026-09-11) : un `ref` arrive en id de catalogue
        # (« 44209 ») OU en uid de pack (« t3k:44209 »). L'export ne connaissait que la première forme : le
        # 2026-09-29, les 13 captures des 6 presets du rack — toutes jouées sans problème par le moteur —
        # sortaient « missing », donc chaque preset était refusé à la publication, et AUCUN n'est arrivé
        # en prod. Un contrôle de publication qui lit autrement que le moteur ment dans les deux sens.
        cid = str(block["ref"]).split("/")[-1]
        keys = [cid] + ([cid.split(":", 1)[1]] if cid.startswith("t3k:") else [])
        pack = next((caps[k] for k in keys if k in caps), None)
        if not pack or not pack.get("assets"):
            return None
        mid = block.get("model")
        # UNE seule capture, comme le rig : le `model` épinglé sinon models[0] (le défaut)
        asset = None
        if mid is not None:
            asset = next((a for a in pack["assets"]
                          if str((a.get("extra") or {}).get("model_id")) == str(mid)), None)
        return pack, [asset or pack["assets"][0]]
    if t in ("pads", "drums"):                               # kit RS5k (library/kits/) — même canal
        kid = (block.get("params") or {}).get("kit")
        pack = kits.get(str(kid)) if kid is not None else None
        return (pack, pack["assets"]) if pack else None
    if t == "vital":
        nm = ((block.get("params") or {}).get("preset") or "").strip().lower()
        if not nm:
            return None
        hit = vitals.get(nm) or vitals.get(nm.replace(" ", "_")) or vitals.get(nm.replace("_", " "))
        return (hit[0], [hit[1]]) if hit else None
    return None


def _catalog():
    """(types de blocs valides, catalog_version) du catalogue effects.json."""
    try:
        c = json.load(open(C.EFFECTS))
    except (OSError, ValueError):
        return set(), 1
    types = {b.get("type") for b in (c.get("effects") or []) if isinstance(b, dict)}
    return types, c.get("catalog_version", 1)


def _unresolved_asset(block):
    """Entrée `unresolved` d'un bloc dont l'ASSET est absent du rack.
    Format tagué (demande golem.fm) : {what:"asset", ..., reason:"missing"}."""
    t = block.get("type")
    base = {"what": "asset", "id": block.get("id"), "type": t, "reason": "missing"}
    if t in CAP_TYPES and block.get("ref") is not None:
        return {**base, "ref": block.get("ref"), "model": block.get("model")}
    p = block.get("params") or {}
    if t in ("pads", "drums") and p.get("kit"):
        return {**base, "kit": p.get("kit")}
    if t == "vital" and p.get("preset"):
        return {**base, "preset": p.get("preset")}
    return None


def _lane_blocks(preset, lane):
    """Blocs (dicts) d'une lane, par id (lot 4 : n'importe quelle lane, plus seulement les trois d'origine)."""
    from .store import lanes_of, _lane_chain_blocks
    L = next((x for x in lanes_of(preset) if x["id"] == lane), None)
    return [b for b in _lane_chain_blocks(L["chain"]) if isinstance(b, dict)] if L else []


def _inputs(preset):
    """Annote chaque lane MONTÉE de son RÔLE INSTRUMENT (vocabulaire inputmap.INSTRUMENTS :
    guitar/bass/voice/keys/drums/pads/keys-pads/line/none), dérivé de l'input map de la carte
    ACTIVE — c'est l'instrumentation de la recette. Nourrit le tri golem.fm + le matching
    à l'import (par rôle, jamais par n° de port). Défaut sensé si le patch dit 'none'."""
    pt = _inputmap.current()
    by_ch = {str(i.get("ch")): i for i in (pt.get("inputs") or [])}
    midi = pt.get("midi") or {}
    inmap = preset.get("in") or {}

    def role_of(chain_key, default_role):
        port = str(inmap.get(chain_key) or chain_key)
        e = by_ch.get(port) or {}
        r = e.get("role")
        r = r if (r and r != "none") else default_role
        return {"role": r, "label": e.get("label") or r.replace("-", " ").title(), "port": port}

    # LOT 4 : une entrée PAR LANE (v2 ou legacy) — le rôle est celui que la lane porte (v2) ou celui de
    # son entrée patchée (legacy) ; `port` = l'entrée choisie (in_sel) ou 'usb'
    from .store import lanes_of, _lane_chain_blocks
    lanes = []
    for L in lanes_of(preset):
        if not [b for b in _lane_chain_blocks(L["chain"]) if isinstance(b, dict)]:
            continue
        if L["midi"]:
            kr = L.get("role") or midi.get("role") or "keys"
            lanes.append({"lane": L["id"], "role": kr if kr != "none" else "keys",
                          "label": L.get("name") or midi.get("label") or "Keys", "port": "usb"})
        else:
            e = by_ch.get(str(L["in_sel"])) or {}
            r = L.get("role") or e.get("role") or "guitar"
            lanes.append({"lane": L["id"], "role": r if r != "none" else "guitar",
                          "label": L.get("name") or e.get("label") or r.replace("-", " ").title(), "port": str(L["in_sel"])})
    if not lanes:                                            # preset vide -> lane guitar structurelle
        lanes.append({"lane": "guitar", **role_of("1", "guitar")})
    return lanes


def _foot_context(pid):
    """Slot(s) de banks FCB où le preset est épinglé — None si autonome."""
    # la liste AU PIED (config/setlist.json), pas fcb-banks.json — la setlist historique, pas un miroir (2026-09-30)
    try:
        from . import setlists as _sl
        d = _sl.load(_sl.active_id()) or {}
    except Exception:
        return None
    slots = [i for i, x in enumerate(d.get("presets") or []) if x == pid]
    if not slots:
        return None
    return {"bank": d.get("id") or "fcb-banks", "slots": slots}


def fingerprint(preset):
    """Empreinte du doc preset qui capte ce qui AFFECTE LE SON — sans les champs cosmétiques ou
    dérivés (preview = l'artefact lui-même, colors/anims = habillage Live). Change de son ->
    change de hash -> preview périmé (golem.fm compare export↔preview, Ré-réponse 14). JSON trié
    = stable et déterministe."""
    d = {k: v for k, v in (preset or {}).items() if k not in ("preview", "colors", "anims")}
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def build_export(pid):
    """Payload d'export d'un preset (ou None si le preset n'existe pas).
    Retourne aussi la blob_map {sha256: chemin} des deps résolus (2e valeur) —
    utile au push (upload des blobs manquants). Ne l'expose PAS dans le JSON."""
    preset = store.load_preset(pid)
    if not preset:
        return None, {}
    state = tones_sync._load_state()
    cache = state.setdefault("sha_cache", {})
    packs, blob_map = tones_sync.build_packs(cache)
    tones_sync._save_state(state)                            # le cache sha vaut d'être gardé
    caps, kits, vitals, samples, grooves = _indexes(packs)
    valid_types, catalog_version = _catalog()

    def _add_dep(pack, a):
        deps[a["sha256"]] = _dep(pack, a)
        if a["sha256"] in blob_map:
            dep_blobs[a["sha256"]] = blob_map[a["sha256"]]

    deps, dep_blobs, unresolved = {}, {}, []
    for b in _iter_blocks(preset):
        t = b.get("type")
        if t and t not in valid_types:                       # TYPE de bloc retiré du catalogue
            unresolved.append({"what": "block", "id": b.get("id"), "type": t, "reason": "retired"})
            continue
        if t == "sample":                                    # liste de .wav one-shot (params.samples)
            for rel in (b.get("params") or {}).get("samples") or []:
                hit = samples.get(rel) or samples.get(os.path.normpath(rel))
                if hit:
                    _add_dep(*hit)
                else:
                    unresolved.append({"what": "asset", "id": b.get("id"), "type": "sample",
                                       "sample": rel, "reason": "missing"})
            continue
        if t == "drums":                                     # ses GROOVES (2026-10-14) — le kit suit, plus bas
            pm = b.get("params") or {}
            for rel in list(pm.get("patterns") or []) + list(pm.get("fills") or []):
                hit = grooves.get(rel) or grooves.get(os.path.normpath(rel))
                if hit:
                    _add_dep(*hit)
                else:
                    unresolved.append({"what": "asset", "id": b.get("id"), "type": "groove",
                                       "groove": rel, "reason": "missing"})
        res = _resolve(b, caps, kits, vitals)
        if res is None:
            miss = _unresolved_asset(b)                       # ASSET absent du rack
            if miss:
                unresolved.append(miss)
            continue
        pack, assets = res
        for a in assets:
            _add_dep(pack, a)

    # clips de PREVIEW (guide sonore, docs/preset-preview.md) : deps kind 'preview', uploadés à
    # la publication. Non bloquant (la démo est un bonus, pas une dépendance de jouabilité).
    from . import preview as preview_mod
    _pdeps, _pblobs = preview_mod.export_deps(preset)
    for dep in _pdeps:
        deps[dep["sha256"]] = dep
        if dep["sha256"] in _pblobs:
            dep_blobs[dep["sha256"]] = _pblobs[dep["sha256"]]

    out = {"schema_version": SCHEMA_VERSION, "catalog_version": catalog_version,
           "preset": preset, "inputs": _inputs(preset), "deps": list(deps.values()),
           # empreinte du doc natif (son) : golem.fm la compare à celle du preview stocké
           # pour afficher « démo peut-être périmée · régénérer » (Ré-réponse 14).
           "preview_fingerprint": fingerprint(preset)}
    fc = _foot_context(pid)
    if fc:
        out["foot_context"] = fc
    if unresolved:
        out["unresolved"] = unresolved
    return out, dep_blobs
