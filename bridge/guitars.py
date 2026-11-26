# SPDX-License-Identifier: GPL-3.0-or-later
"""LES GUITARES DU RACK — le profil de chaque guitare : son accordage, ses cases, son nom (docs/transcription.md §4).

Ce qui reste de bridge/inharm.py depuis que l'écoute est passée à golem.fm (2026-11-26) : l'étalonnage des cordes
(B à vide), la main et la carte du manche sont partis avec la transcription du rack. Le fichier garde son nom,
`config/string-calib.json` (état local, jamais commité), pour ne pas perdre les profils déjà écrits sur les racks :
    {"active": "<id>", "<id>": {"name", "tuning": [MIDI, de la grave à l'aiguë] | "strings": n, "frets"}}
Les anciennes clés (`b_open`, `hand`, `neckmap`) y restent sans être lues.
"""
import json
import os

CALIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "string-calib.json")
STANDARD = {6: (40, 45, 50, 55, 59, 64), 7: (35, 40, 45, 50, 55, 59, 64), 8: (30, 35, 40, 45, 50, 55, 59, 64)}
DEFAULT_FRETS = 22


def _doc(path):
    try:
        with open(path) as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _tuning_ok(t):
    return (isinstance(t, list) and 4 <= len(t) <= 9
            and all(isinstance(p, int) and not isinstance(p, bool) and 0 <= p <= 127 for p in t))


def active_guitar(path=None):
    """L'id de la guitare jouée en ce moment (`active`, sinon « default »)."""
    a = _doc(path or CALIB).get("active")
    return a if isinstance(a, str) and a else "default"


def guitar(path=None, gid=None):
    """Le profil d'une guitare : {id, name, tuning (grave -> aigu), frets, declared}. `declared` = le profil DIT son
    accordage ; sinon c'est une 6 cordes standard (ou le standard de son nombre de cordes) supposée."""
    doc = _doc(path or CALIB)
    gid = gid if isinstance(gid, str) and gid else active_guitar(path)
    g = doc.get(gid) if isinstance(doc.get(gid), dict) else {}
    tuning = g.get("tuning")
    declared = _tuning_ok(tuning)
    if not declared:
        try:
            n = int(g.get("strings") or 6)
        except (TypeError, ValueError):
            n = 6
        tuning = list(STANDARD.get(n, STANDARD[6]))
    try:
        frets = max(12, min(30, int(g.get("frets") or DEFAULT_FRETS)))
    except (TypeError, ValueError):
        frets = DEFAULT_FRETS
    return {"id": gid, "name": g.get("name") or gid, "tuning": sorted(tuning), "frets": frets, "declared": declared}


def guitar_for(tuning, path=None):
    """L'id du profil dont l'accordage EST `tuning` (mêmes notes, même nombre de cordes) — l'actif d'abord si
    plusieurs l'ont (deux 6 cordes standard) ; None si aucun."""
    want = sorted(tuning or [])
    doc = _doc(path or CALIB)
    ids = [k for k, v in doc.items() if isinstance(v, dict) and not k.startswith("_")]
    hits = [k for k in ids if guitar(path, k)["tuning"] == want]
    act = active_guitar(path)
    return act if act in hits else (hits[0] if hits else None)


# ── L'INSTRUMENT DE CHAQUE LANE D'UNE PRISE (docs/transcription.md §4, 2026-11-26) ─────────────────────────────────────
# Ce que golem.fm lit pour écrire une tab : cordes, accordage (MIDI, la VÉRITÉ), capo, cases, profil — et d'où vient
# l'accordage (`source`), pour qu'il DEMANDE à la personne quand rien ne l'a dit (« default »). Rien n'est deviné en
# silence : une lane sans rôle guitare/basse n'a pas d'entrée.
BASS_DEFAULT = [28, 33, 38, 43]
BASS_FRETS = 20


def _tuning_id(midi):
    """L'id de library/catalog/tunings.json dont les notes SONT celles-ci (le nom affiché), ou None."""
    from . import tunings
    want = sorted(midi or [])
    hit = next((t for t in tunings.load().get("tunings") or [] if sorted(t.get("midi") or []) == want), None)
    return hit.get("id") if hit else None


def _tuner_of_lane(preset, lane_id):
    """L'id d'accordage du bloc Tuner de cette lane du preset joué, ou None."""
    from . import store
    for b, lid in store.all_blocks(preset or {}):
        if lid == lane_id and isinstance(b, dict) and b.get("type") == "tuner":
            t = (b.get("params") or {}).get("tuning")
            return t if isinstance(t, str) and t else None
    return None


def _lane_of_input(preset, inp):
    """La lane du preset qui joue cette entrée : par (rôle, rang), sinon par canal (comme lane_stomps)."""
    from . import store
    try:
        lanes = list(store.lanes_of(preset)) if preset and store.is_v2(preset) else []
    except Exception:
        lanes = []
    for L in lanes:
        if L.get("in_role") and L.get("in_nth") is not None and \
                L.get("in_role") == inp.get("role") and L.get("in_nth") == inp.get("nth"):
            return L
    ch = str(inp.get("ch") or "")
    return next((L for L in lanes if str(L.get("in_sel") or "") == ch), None)


def instruments_of(inputs, preset=None, capo=None, path=None):
    """{canal: {role, strings, tuning, tuning_id, capo, frets, guitar, source}} pour chaque entrée guitare ou basse.
    `inputs` = state.inputmap["inputs"] ; `preset` = le preset joué ; `capo` = sheet.capo du morceau joué, ou None."""
    from . import tunings
    out = {}
    cap = capo if isinstance(capo, int) and not isinstance(capo, bool) and capo >= 0 else None
    for inp in inputs or []:
        role, ch = inp.get("role"), inp.get("ch")
        if role not in ("guitar", "bass") or not ch:
            continue
        tuning, source, prof = None, None, None
        lane = _lane_of_input(preset, inp)
        tid = _tuner_of_lane(preset, lane.get("id")) if lane else None
        if tid:
            t = next((x for x in tunings.for_role(role) if x.get("id") == tid), None)
            if t and _tuning_ok(t.get("midi")):
                tuning, source = sorted(t["midi"]), "tuner"
        if role == "guitar":
            gid = guitar_for(tuning, path) if tuning else active_guitar(path)
            prof = guitar(path, gid) if gid else None
            if tuning is None and prof:
                tuning, source = prof["tuning"], ("profile" if prof["declared"] else "default")
            frets = prof["frets"] if prof else DEFAULT_FRETS
            g = {"id": prof["id"], "name": prof["name"]} if prof and gid in _doc(path or CALIB) else None
        else:
            if tuning is None:
                tuning, source = list(BASS_DEFAULT), "default"
            frets, g = BASS_FRETS, None
        out[str(ch)] = {"role": role, "strings": len(tuning), "tuning": tuning, "tuning_id": _tuning_id(tuning),
                        "capo": cap, "frets": frets, "guitar": g, "source": source}
    return out


def apply_riff_tuning(instruments, tuning, path=None):
    """Un Riff armé dit l'accordage (golem.fm, compo-target) : il l'emporte sur les lanes guitare (`source: riff`)."""
    if not _tuning_ok(tuning):
        return instruments
    t = sorted(tuning)
    gid = guitar_for(t, path)
    prof = guitar(path, gid) if gid else None
    for e in (instruments or {}).values():
        if e.get("role") == "guitar":
            e.update(strings=len(t), tuning=t, tuning_id=_tuning_id(t), source="riff",
                     frets=prof["frets"] if prof else e.get("frets"),
                     guitar={"id": prof["id"], "name": prof["name"]} if prof else None)
    return instruments
