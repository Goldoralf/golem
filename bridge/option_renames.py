# SPDX-License-Identifier: GPL-3.0-or-later
"""LES ÉTIQUETTES D'UN CHOIX QUI CHANGENT DE NOM (catalogue `renamed` sur un paramètre enum, 2026-10-22).

Un réglage à choix se range sous son ÉTIQUETTE (« 1/4 »), pas sous sa valeur. Quand une étiquette mentait — le Tape
Delay disait « 1/4 » pour un tick de Calf, une double croche —, la corriger sans migration ferait jouer l'option 0 à
tous les presets existants (golem_rig.index_of ne trouve plus l'étiquette). Le catalogue déclare donc, sur le
paramètre, `renamed: {ancienne: nouvelle}`, et ce module réécrit au CHARGEMENT tout document qui porte encore
l'ancienne — preset, patch, preset de bloc, .golem importé, document venu de golem.fm.

Règles, pour qu'une réécriture ne puisse jamais se tromper de sens :
  - une ancienne étiquette n'est JAMAIS une nouvelle option (le test du catalogue l'exige) : réécrire est pur et
    idempotent, un document déjà migré ne bouge plus ;
  - seuls les blocs du TYPE déclaré sont touchés (« 1/4 » est aussi une option du Delay, qui garde la sienne) : leurs
    params, puis les params rangés sous leur id dans les états de lane et les scènes.

Rend le nombre de valeurs réécrites (0 : rien n'a changé)."""
import json
import os

from . import config as C

_cache = {"mtime": None, "val": {}}


def table():
    """{type de bloc: {id de paramètre: {ancienne: nouvelle}}}, lu dans effects.json (relu s'il change)."""
    try:
        mt = os.path.getmtime(C.EFFECTS)
    except OSError:
        return {}
    if _cache["mtime"] != mt:
        out = {}
        try:
            with open(C.EFFECTS, encoding="utf-8") as f:
                effects = json.load(f).get("effects", [])
        except (OSError, ValueError):
            effects = []
        for e in effects:
            for p in e.get("params") or []:
                if isinstance(p.get("renamed"), dict) and p.get("id"):
                    out.setdefault(e.get("type"), {})[p["id"]] = dict(p["renamed"])
        _cache.update(mtime=mt, val=out)
    return _cache["val"]


def _rename(params, renames):
    n = 0
    if not isinstance(params, dict):
        return 0
    for pid, ren in renames.items():
        v = params.get(pid)
        if isinstance(v, str) and v in ren:
            params[pid] = ren[v]
            n += 1
    return n


def apply(doc, tbl=None):
    """Réécrit EN PLACE les anciennes étiquettes de `doc` (n'importe quel document : preset, patch, preset de bloc).
    Rend le nombre de valeurs réécrites."""
    tbl = table() if tbl is None else tbl
    if not tbl or not isinstance(doc, (dict, list)):
        return 0
    by_id = {}                                   # id de bloc -> renommages de son type
    n = 0

    def blocks(o):
        nonlocal n
        if isinstance(o, dict):
            t = o.get("type")
            if isinstance(t, str) and t in tbl:
                n += _rename(o.get("params"), tbl[t])
                if o.get("id") is not None:
                    by_id[str(o["id"])] = tbl[t]
            for v in o.values():
                blocks(v)
        elif isinstance(o, list):
            for v in o:
                blocks(v)

    def keyed(o):
        nonlocal n
        if isinstance(o, dict):
            ps = o.get("params")
            if isinstance(ps, dict):
                for bid, ren in by_id.items():
                    n += _rename(ps.get(bid), ren)
            for v in o.values():
                keyed(v)
        elif isinstance(o, list):
            for v in o:
                keyed(v)

    blocks(doc)
    if by_id:
        keyed(doc)
    return n
