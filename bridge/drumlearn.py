# SPDX-License-Identifier: GPL-3.0-or-later
"""Calibration ▸ Drums — l'ANALYSE d'une mesure de module de batterie (docs/calibration.md, addendum
2026-09-23, lot D2). Partagée par le stepper de l'écran (`POST /api/drumkits/measure`) et par
`tools/check-drums.py` : une seule règle de la frappe, une seule comparaison, une seule écriture.

Une MESURE = ce qui est arrivé du module pendant chaque étape, tel quel :
    {"port": "Alesis Nitro", "kit": "alesis-nitro" | None, "measured_at": "…",
     "steps": {"kick": {"events": [{"k": 1, "n": 36, "v": 94, "c": 9, "t": 12.3}, …]}, …}}
`k` 1 = note-on, 2 = CC, 3 = aftertouch poly (le tampon de drum-tap.jsfx, ou aseqdump traduit).
Une étape absente = pas posée ; une étape sans événement = l'utilisateur a passé (« n'existe pas »).

Les trois règles apprises sur l'Alesis Nitro le 2026-09-23, et que ce module fait respecter :
  1. LA FRAPPE EST LA NOTE LA PLUS FORTE du geste — pas la première, pas la plus fréquente. Un geste
     en produit plusieurs (chick de pédale puis frappe ; peau faible + diaphonie du pad voisin).
  2. LA NATURE SE LIT À L'ENDROIT OÙ L'ÉVÉNEMENT ARRIVE : de l'aftertouch pendant l'étape de choke
     est un choke ; pendant la pédale de charleston, c'est la pédale. Une présence ne nomme rien.
  3. UNE NOTE NE SERT QU'UN ÉLÉMENT : quand la mesure en propose deux, rien ne s'écrit et on dit
     lesquels — écrire écraserait un élément juste par un élément douteux.
"""
import json
import os
import re
import time

from . import config as C
from . import drumkits

# Les étapes, dans l'ordre du stepper : `el` = l'élément du vocabulaire fermé (drumkits.ELEMENTS) que
# la frappe mesure, `group` = ce que l'étape renseigne en plus (charleston, étouffement). Une étape
# `gesture` ne prend PAS de ligne dans la table : elle mesure un comportement (le choke).
STEPS = [
    {"id": "kick",         "el": "kick"},
    {"id": "snare",        "el": "snare"},
    {"id": "snare-rim",    "el": "snare-rim"},
    {"id": "tom1",         "el": "tom1"},
    {"id": "tom1-rim",     "el": "tom1-rim"},
    {"id": "tom2",         "el": "tom2"},
    {"id": "tom2-rim",     "el": "tom2-rim"},
    {"id": "tom3",         "el": "tom3"},
    {"id": "tom3-rim",     "el": "tom3-rim"},
    {"id": "tom4",         "el": "tom4"},
    {"id": "tom4-rim",     "el": "tom4-rim"},
    {"id": "hh-closed",    "el": "hh-closed",  "group": "hihat"},
    {"id": "hh-open",      "el": "hh-open",    "group": "hihat"},
    {"id": "hh-half",      "el": "hh-half",    "group": "hihat"},
    {"id": "hh-pedal",     "el": "hh-pedal",   "group": "hihat"},
    # splash = frappe ouverte PUIS fermeture de la pédale : le chick arrive APRÈS, souvent plus fort
    # (mesuré Nitro : 46@101 puis 44@104). Ici, et seulement ici, la frappe est la PREMIÈRE note.
    {"id": "hh-splash",    "el": "hh-splash",  "group": "hihat", "pick": "first"},
    {"id": "crash1",       "el": "crash1"},
    {"id": "crash1-choke", "el": None, "gesture": "choke", "of": "crash1"},
    {"id": "crash2",       "el": "crash2"},
    {"id": "ride",         "el": "ride"},
    {"id": "ride-bell",    "el": "ride-bell"},
]
STEP_BY_ID = {s["id"]: s for s in STEPS}
WEAK_VEL = 20              # en dessous : « zone réelle, ou diaphonie du pad voisin ? »
TWIN_RATIO = 0.5           # une seconde note à ≥ 50 % de la frappe = deux notes fortes, dit
NOTE, CC, POLY = 1, 2, 3


def strike(events, pick="loudest"):
    """La note de la FRAPPE d'un geste, avec sa force, et les autres notes du geste — règle 1.
    `pick` "first" : la première note-on (le splash). Rend ((note, vel), [(note, vel), …] par force
    décroissante) ou (None, [])."""
    best, first = {}, None
    for e in events or []:
        if e.get("k") == NOTE:
            n, v = int(e["n"]), int(e["v"])
            best[n] = max(best.get(n, 0), v)
            first = n if first is None else first
    if not best:
        return None, []
    order = sorted(best, key=lambda n: -best[n])
    if pick == "first" and first is not None:
        order.remove(first); order.insert(0, first)
    return (order[0], best[order[0]]), [(n, best[n]) for n in order[1:]]


# Un élément DÉRIVÉ (cercle, cloche, bord, mi-course, splash) qui rend la note d'un élément de BASE n'est
# pas une zone : c'est le même pad. Deux éléments de BASE sur la même note, c'est une mesure qui se
# contredit — règle 3 : on ne tranche pas à leur place.
def rank(el):
    return 1 if el.endswith(("-rim", "-bell", "-edge", "-xstick")) or el in ("hh-half", "hh-splash") else 0


def _kinds(events, k):
    return [e for e in (events or []) if e.get("k") == k]


def analyse(measure):
    """Une mesure -> ce qu'elle dit, structuré (rien n'est imprimé ici : l'écran et le CLI rendent).

    elements : {el: {note, vel, also: [[n, v]…], flags: [weak|twins|aftertouch|cc], step}}
    hihat    : {cc: n|None, positions: 2|3, notes: {el: note}} — décidé par les étapes `hihat` (règle 2)
    choke    : "poly-aftertouch" | "note-off" | "none" — décidé par l'étape `choke` seule (règle 2)
    aftertouch_elsewhere : [step…] — de l'aftertouch reçu hors choke (la pédale de la Nitro), dit
    channel  : [canaux 1-16 vus] ; clock : bool ; skipped : [étapes passées]
    clash    : {note: [el…]} — deux éléments sur la même note (règle 3) ; twins : {el: main} — un
               élément dont la note est celle d'un autre, plus fort : une seule zone sur ce pad
    """
    steps = (measure or {}).get("steps") or {}
    out = {"elements": {}, "skipped": [], "channel": set(), "clock": bool((measure or {}).get("clock")),
           "aftertouch_elsewhere": [], "hihat": {"cc": None, "positions": 2, "notes": {}}, "choke": "none"}
    hh_cc = {}
    for st in STEPS:
        sid = st["id"]
        if sid not in steps:
            continue
        evts = (steps[sid] or {}).get("events") or []
        for e in evts:
            if "c" in e:
                out["channel"].add(int(e["c"]) + 1)
        s, others = strike(evts, st.get("pick", "loudest"))
        polys = _kinds(evts, POLY)
        ccs = _kinds(evts, CC)
        if st.get("gesture") == "choke":
            if polys:
                out["choke"] = "poly-aftertouch"
            elif any(e.get("k") == NOTE and int(e["v"]) == 0 for e in evts):
                out["choke"] = "note-off"
            continue
        if s is None:
            out["skipped"].append(sid)
            if polys:
                out["aftertouch_elsewhere"].append(sid)
            continue
        note, vel = s
        flags = []
        if others and others[0][1] >= vel * TWIN_RATIO:
            flags.append("twins")
        elif vel <= WEAK_VEL:
            flags.append("weak")
        if polys:
            flags.append("aftertouch")
            out["aftertouch_elsewhere"].append(sid)
        if ccs:
            flags.append("cc")
        out["elements"][st["el"]] = {"note": note, "vel": vel, "also": [list(o) for o in others],
                                     "flags": flags, "step": sid}
        if st.get("group") == "hihat":
            out["hihat"]["notes"][st["el"]] = note
            for e in ccs:
                hh_cc.setdefault(int(e["n"]), []).append(int(e["v"]))
    # LE CHICK SE DÉDUIT DU GESTE « FERMÉ » (2026-09-23, stepper au vrai kit) : l'étape « pédale seule » est
    # souvent passée (on ne pense pas à appuyer sans frapper), et sur la Nitro elle a rendu la note de l'ouverte.
    # Or « fermé » = la pédale qui s'enfonce (chick 44) PUIS la frappe (42) : la seconde note forte de ce geste,
    # si aucun autre élément ne la porte, EST la pédale. Dit comme tel (`flags: inferred`).
    if "hh-pedal" not in out["elements"] and "hh-closed" in out["elements"]:
        taken = {m["note"] for el, m in out["elements"].items() if el != "hh-closed"}
        closed = out["elements"]["hh-closed"]
        cand = next((n for n, v in closed.get("also") or [] if v >= closed["vel"] * TWIN_RATIO and n not in taken), None)
        if cand is not None:
            out["elements"]["hh-pedal"] = {"note": cand, "vel": max(v for n, v in closed["also"] if n == cand),
                                           "also": [], "flags": ["inferred"], "step": "hh-closed"}
            out["hihat"]["notes"]["hh-pedal"] = cand
            out["skipped"] = [x for x in out["skipped"] if x != "hh-pedal"]
    out["channel"] = sorted(out["channel"])
    # charleston (règle 2) : le CC vu PENDANT les étapes de charleston, sinon pédale interrupteur ;
    # trois positions seulement si la mi-course a rendu une note DISTINCTE de l'ouverte
    if hh_cc:
        cc = max(hh_cc, key=lambda n: len(hh_cc[n]))
        out["hihat"]["cc"] = cc
        out["hihat"]["cc_range"] = [min(hh_cc[cc]), max(hh_cc[cc])]
    hn = out["hihat"]["notes"]
    out["hihat"]["positions"] = 3 if ("hh-half" in hn and hn["hh-half"] not in (hn.get("hh-open"), hn.get("hh-closed"))) else 2
    # règle 3 : une note, un élément. Un élément dont la note est celle d'un autre, plus fort, n'est
    # pas une zone : c'est le même pad (cercle de tom = peau faible ; cloche = ride).
    by_note = {}
    for el, m in out["elements"].items():
        by_note.setdefault(m["note"], []).append(el)
    out["twins"], out["clash"] = {}, {}
    for n, els in by_note.items():
        if len(els) < 2:
            continue
        mains = [e for e in els if rank(e) == 0]
        if len(mains) > 1:
            out["clash"][n] = sorted(mains)          # deux éléments de base : la mesure se contredit
        main = max(mains or els, key=lambda e: out["elements"][e]["vel"])
        for e in els:
            if e != main:
                out["twins"][e] = main
    return out


def compare(report, desc):
    """Le rapport contre un descripteur : une ligne par élément, et les verdicts charleston / choke /
    canal. `rows` : [{el, note, declared, status}] avec status ok | differs | absent | twin.
    `ghosts` : les lignes déclarées que personne n'a reçues."""
    declared = {v: int(k) for k, v in ((desc or {}).get("map") or {}).items()}
    rows, taken = [], set()
    for el, m in sorted(report["elements"].items(), key=lambda x: (x[1]["note"], x[0])):
        if el in report["twins"]:
            rows.append({"el": el, "note": m["note"], "declared": declared.get(el), "status": "twin",
                         "of": report["twins"][el], "vel": m["vel"], "vel_of": report["elements"][report["twins"][el]]["vel"]})
            continue
        taken.add(m["note"])
        d = declared.get(el)
        rows.append({"el": el, "note": m["note"], "declared": d,
                     "status": "absent" if d is None else ("ok" if d == m["note"] else "differs"), "vel": m["vel"]})
    ghosts = [{"el": e, "note": n} for e, n in sorted(declared.items(), key=lambda x: x[1])
              if e not in report["elements"] and n not in taken]
    hh = (desc or {}).get("hihat") or {}
    verdict = {
        "hihat_cc": {"declared": hh.get("cc"), "measured": report["hihat"]["cc"],
                     "ok": hh.get("cc") == report["hihat"]["cc"]},
        "hihat_positions": {"declared": hh.get("positions"), "measured": report["hihat"]["positions"],
                            "ok": hh.get("positions") == report["hihat"]["positions"]},
        "choke": {"declared": (desc or {}).get("choke"), "measured": report["choke"],
                  "ok": (desc or {}).get("choke") == report["choke"]},
        "channel": {"declared": (desc or {}).get("channel"), "measured": report["channel"],
                    "ok": not report["channel"] or report["channel"] == [(desc or {}).get("channel")]},
    }
    bad = sum(1 for r in rows if r["status"] in ("differs", "absent")) + sum(1 for v in verdict.values() if not v["ok"])
    return {"rows": rows, "ghosts": ghosts, "verdict": verdict, "bad": bad,
            "provenance": ((desc or {}).get("provenance") or {}).get("confidence")}


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")
    return s or "drum-module"


def descriptor(report, measure, base=None):
    """Le descripteur qui SORT d'une mesure : la table des éléments mesurés (les jumeaux exclus), la
    charleston et le choke décidés par les étapes, la provenance `measured / verified`. `base` =
    le descripteur existant à corriger (ses lignes jamais reçues partent dans `reported_map`, sa note
    dans `reported_note`) ; None = un module inconnu, créé depuis la mesure."""
    if report.get("clash"):
        raise ValueError("two elements claim the same note: " + json.dumps(report["clash"])
                         + " — redo those steps (a base element and its pad cannot share a note)")
    port = (measure or {}).get("port") or "unknown module"
    base = base or {}
    d = {k: v for k, v in base.items()}
    if not base:
        d.update({"schema": 1, "kind": "drumkit", "id": _slug(port), "name": port,
                  "identity": {"brand": port.split(" ")[0], "model": " ".join(port.split(" ")[1:]) or port,
                               "connection": "usb", "usb_names": [port]},
                  "editable_on_module": True})       # audio_outs : rien tant que personne ne l'a câblé
    d["channel"] = report["channel"][0] if report["channel"] else base.get("channel", 10)
    m = {}
    for el, mm in report["elements"].items():
        if el in report["twins"]:
            continue
        m[str(mm["note"])] = el
    d["map"] = {k: m[k] for k in sorted(m, key=int)}
    hh = {"cc": report["hihat"]["cc"], "positions": report["hihat"]["positions"], "notes": "distinct"}
    if hh["cc"] is not None:
        rng = report["hihat"].get("cc_range") or [0, 127]
        if rng[0] == rng[1]:                          # une seule valeur vue : aucun sens lisible
            rng = [0, 127]
        # le sens (quelle valeur est « fermé ») n'est PAS mesuré ici : le stepper ne l'a pas demandé.
        # On garde min -> ouvert, max -> fermé (Medeli/Yamaha) ; un Roland (0 -> 90) se corrige à la main.
        hh.update({"open_value": rng[0], "closed_value": rng[1]})
        if hh["positions"] == 3:
            hh["bands"] = list(((base.get("hihat") or {}).get("bands")) or [33, 66])
    d["hihat"] = hh
    d["choke"] = report["choke"]
    prov = dict(base.get("provenance") or {})
    old_map = base.get("map") or {}
    ghosts = {k: v for k, v in old_map.items() if k not in d["map"] and v not in d["map"].values()}
    if prov.get("note"):
        prov["reported_note"] = prov.pop("note")
    if prov.get("url"):
        prov["reported_url"] = prov.pop("url")
    if ghosts:
        prov["reported_map"] = ghosts
    n = len(d["map"])
    prov.update({"source": "measured", "confidence": "verified",
                 "measured_at": (measure or {}).get("measured_at") or time.strftime("%Y-%m-%d"),
                 "measured_on": port,
                 "note": f"Table mesurée pad par pad (Calibration ▸ Drums), {n} éléments. "
                         f"Charleston : {'CC ' + str(hh['cc']) if hh['cc'] is not None else 'pédale interrupteur, aucun CC'}, "
                         f"{hh['positions']} positions. Étouffement : {report['choke']}."
                         + (" Aftertouch reçu hors étouffement pendant : " + ", ".join(report["aftertouch_elsewhere"]) + "."
                            if report["aftertouch_elsewhere"] else "")})
    d["provenance"] = prov
    return d


def write(desc):
    """Écrit un descripteur MESURÉ dans config/drumkits.local/ (hors dépôt, prend le pas sur la graine du même
    id) après validation — sauvegarde `.bak` de l'ancien. Jamais dans les graines suivies (2026-10-03)."""
    probs = drumkits.validate(desc, desc.get("id"))
    if probs:
        raise ValueError("descriptor invalid: " + "; ".join(probs))
    os.makedirs(drumkits.LOCAL_DIR, exist_ok=True)
    path = os.path.join(drumkits.LOCAL_DIR, desc["id"] + ".json")
    if os.path.isfile(path):
        os.replace(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(desc, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def measure_and_write(measure, kit=None):
    """Le geste complet du bouton « Save as measured » : analyse -> comparaison -> descripteur -> fichier.
    Rend {report, compare, descriptor, path} ; lève ValueError (règle 3, ou descripteur invalide)."""
    base = drumkits.get(kit) if kit else None
    rep = analyse(measure)
    cmp_ = compare(rep, base) if base else None
    desc = descriptor(rep, measure, base)
    path = write(desc)
    return {"report": rep, "compare": cmp_, "descriptor": desc, "path": path}
