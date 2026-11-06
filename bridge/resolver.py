# SPDX-License-Identifier: GPL-3.0-or-later
"""Résolution des refs de blocs -> fichiers NAM/IR (+ écriture latin-1 des .RfxChain).

Extrait de l'ancien bridge/compile.py (pipeline legacy supprimé, audit 2026-07-07) : ces quatre
fonctions sont les seules survivantes, utilisées par compile_rig (pipeline actif paths+splits).
"""
import os, json

from . import config as C

COMPONENTS = os.path.join(C.ROOT, "library", "components.json")


def _components():
    d = json.load(open(COMPONENTS)) if os.path.exists(COMPONENTS) else {}
    idx = {}
    for cat in ("amps", "cabs", "pedals"):
        for c in d.get(cat, []):
            idx[c["id"]] = c
    return idx


# Cache du catalogue, invalidé sur mtime (un tone fraîchement téléchargé est visible sans restart).
_TONES = {"mtime": None, "idx": None}


def _tones_index():
    try:
        mt = os.path.getmtime(C.CATALOG) if os.path.exists(C.CATALOG) else None
    except Exception:
        mt = None
    if _TONES["idx"] is None or _TONES["mtime"] != mt:
        d = json.load(open(C.CATALOG)) if os.path.exists(C.CATALOG) else {"tones": []}
        _TONES["idx"] = {str(t["id"]): t for t in d.get("tones", [])}
        _TONES["mtime"] = mt
    return _TONES["idx"]


def _asset_path(rel):
    """Chemin absolu d'un fichier du catalogue, ou None s'il sort du dépôt (audit 2026-09-13, B1 :
    le catalogue est réécrit par ce que golem.fm nous envoie — un `file` en `../` ne se charge pas)."""
    if not rel:
        return None
    p = os.path.realpath(os.path.join(C.ROOT, str(rel)))
    for root in C.ASSET_ROOTS:
        if p.startswith(os.path.realpath(root) + os.sep):
            return p
    return None


def _resolve(ref, comps, model_id=None):
    """ref 'amps/xxx' / 'xxx' / un id de tone (catalogue) -> chemin absolu du fichier.
    model_id (optionnel) = l'`id` du modèle précis dans le pack (IR d'un cab, variante mic d'un ampli) ;
    à défaut (None ou introuvable) -> le 1er modèle du tone (comportement historique)."""
    if not ref:
        return None
    cid = ref.split("/")[-1]
    # ⚠ 2026-09-11 — « t3k:44209 » est l'UID DE PACK (docs/private/exchanges/maestrium-tones-api.md, `deps.uid`) ;
    # l'index des tones, lui, est tenu par l'ID DU CATALOGUE (« 44209 », cf. _entry_from_pack).
    # Un patch de golem.fm est arrivé avec l'uid dans le `ref` d'un bloc : rien ne résolvait, le
    # template gardait « %MODEL% » (_tpl ne substitue que si la valeur est non vide) et le NAM se
    # chargeait SANS modèle — muet, sans une erreur. Les deux formes désignent le même tone : on
    # les accepte. La forme canonique d'un `ref` reste l'id du catalogue.
    keys = [cid]
    if cid.startswith("t3k:"):
        keys.append(cid.split(":", 1)[1])
    for k in keys:
        c = comps.get(k)
        if c and c.get("file"):
            return _asset_path(c["file"])
        t = _tones_index().get(k)
        if t and t.get("models"):
            models = t["models"]
            chosen = next((m for m in models if str(m.get("id")) == str(model_id)), None) if model_id is not None else None
            return _asset_path(playable_twin(chosen or models[0], models)["file"])
    return None


# ── LA JUMELLE A1 d'une capture A2 (2026-10-03, « ça ne télécharge pas la capture ») ─────
# Hors Linux le cœur NAM ne lit pas l'A2 (rig.nam_unreadable). TONE3000 publie chaque ré-entraînement
# A2 À CÔTÉ de sa capture d'origine, sous le MÊME nom (vérifié sur Fender Twin 246, Big Muff 37818,
# JCM800 44209) : c'est le même réglage, la même prise, deux formats. Un patch fait sous Linux épingle
# l'A2 ; ici, si la jumelle est installée, c'est ELLE qui joue — le document ne change pas, il rejoue
# l'A2 sur un rack qui le lit. Seulement une jumelle du MÊME nom : jamais un autre réglage en silence.
_SIZE_SUFFIXES = (" feather", " lite", " nano", " standard", " xstd")


def twin_name(name):
    n = " ".join(str(name or "").lower().split())
    for s in _SIZE_SUFFIXES:
        if n.endswith(s):
            return n[: -len(s)].rstrip(" -")
    return n


def is_a2(m):
    if str(m.get("arch") or m.get("architecture_version") or "") == "2":
        return True
    return str(m.get("file") or "").lower().endswith("-a2.nam")


def playable_twin(m, models):
    """`m`, ou sa jumelle non-A2 installée si cette machine ne lit pas l'A2. Standard avant feather/lite."""
    from .rig import nam_unreadable
    if not is_a2(m) or "SlimmableContainer" not in nam_unreadable():
        return m
    want = twin_name(m.get("name"))
    twins = [x for x in models if not is_a2(x) and x.get("file") and twin_name(x.get("name")) == want]
    twins.sort(key=lambda x: 0 if " ".join(str(x.get("name") or "").lower().split()) == want else 1)
    return twins[0] if twins else m


def _write(path, text):
    open(path, "wb").write(text.encode("latin-1"))
