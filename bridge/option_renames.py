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


# ── LES TYPES DE BLOCS RETIRÉS (2026-11-13) : un type qui fait double emploi disparaît du catalogue, et un document
# qui le porte encore est réécrit au chargement vers le type qui reste, valeurs CONVERTIES. Pur et idempotent : le
# type retiré n'existe plus au catalogue, donc un document réécrit ne le porte plus.
def _flanger_from_calf(pm):
    """Calf Flanger (`flanger` : rate Hz, depth = largeur du balayage en ms, feedback linéaire -0.9…0.9) -> le flanger
    qui reste (`flanger-js` : length ms, feedback dB, wet/dry dB, rate Hz). La traduction est celle de golem-fx
    (gfx-flanger-calf `translate`, qui jouait ce bloc sous le Golem Engine) : balayage de min_delay 0,5 ms à
    0,5 + depth, |feedback| en dB et son signe en `fb_polarity` (plafond -1 dB, celui du moteur ; le catalogue s'arrêtait à -6 et
    l'a suivi en v40 pour qu'un « Jet » à 0,85 garde son caractère), Amount 0,5 de Calf = wet -6 dB. Sous REAPER, le JSFX n'a pas de polarité : le
    compilateur retire `fb_polarity` (engine_only) et le signe s'y perd."""
    import math
    pm = pm if isinstance(pm, dict) else {}
    out = {}
    if "rate" in pm:
        out["rate"] = round(min(2.0, max(0.05, float(pm["rate"]))), 3)
    if "depth" in pm:
        out["length"] = round(min(30.0, 0.5 + max(0.0, float(pm["depth"]))), 2)
    if "feedback" in pm:
        fb = abs(float(pm["feedback"]))
        out["feedback"] = -60.0 if fb < 0.001 else round(min(-1.0, max(-60.0, 20 * math.log10(fb))), 1)
        if float(pm["feedback"]) < 0 and fb >= 0.001:
            out["fb_polarity"] = "Inverted"                # le signe passe par la polarité (Golem Engine seulement)
    if pm.get("depth") is not None or pm.get("rate") is not None or pm.get("feedback") is not None:
        out.setdefault("wet", -6.0)
        out.setdefault("dry", 0.0)
    return out


RETIRED = {"flanger": ("flanger-js", _flanger_from_calf)}


def _retire(doc):
    """Réécrit les blocs d'un type retiré (et leurs réglages rangés sous leur id : scènes, états de lane)."""
    n = 0
    ids = {}

    def blocks(o):
        nonlocal n
        if isinstance(o, dict):
            t = o.get("type")
            if isinstance(t, str) and t in RETIRED:
                to, conv = RETIRED[t]
                o["type"] = to
                if isinstance(o.get("params"), dict):
                    o["params"] = conv(o["params"])
                if o.get("id") is not None:
                    ids[str(o["id"])] = conv
                n += 1
            for v in o.values():
                blocks(v)
        elif isinstance(o, list):
            for v in o:
                blocks(v)

    def keyed(o):
        if isinstance(o, dict):
            ps = o.get("params")
            if isinstance(ps, dict):
                for bid, conv in ids.items():
                    if isinstance(ps.get(bid), dict):
                        ps[bid] = conv(ps[bid])
            for v in o.values():
                keyed(v)
        elif isinstance(o, list):
            for v in o:
                keyed(v)

    blocks(doc)
    if ids:
        keyed(doc)
    return n


def apply(doc, tbl=None):
    """Réécrit EN PLACE les anciennes étiquettes de `doc` (n'importe quel document : preset, patch, preset de bloc).
    Rend le nombre de valeurs réécrites."""
    if not isinstance(doc, (dict, list)):
        return 0
    retired = _retire(doc) if tbl is None else 0           # un type retiré d'abord : ses renommages sont ceux du type qui reste
    tbl = table() if tbl is None else tbl
    if not tbl:
        return retired
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
    return n + retired
