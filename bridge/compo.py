# SPDX-License-Identifier: GPL-3.0-or-later
"""Bloc COMPO — un riff vers le composer de golem.fm (docs/compo.md, FIGÉ 2026-09-17).

Ce module porte ce qui n'est PAS la config globale (store.load_compo_cfg) :
  - les CIBLES « Follow Golem » (§10) : par personne, EN MÉMOIRE SEULEMENT — golem.fm les renvoie à
    chaque reconnexion de l'uplink, un redémarrage du rack ne perd rien et ne ressuscite rien ;
  - l'AUTEUR d'un tap (§4) : la personne de l'appareil qui tape — au pédalier du rack c'est
    `foot_person`, à défaut la première entrée de la carte qui porte une personne ;
  - ses LANES : celles dont l'entrée numérotée porte sa personne dans la carte du mode, moins
    celles qu'elle a décochées dans le tiroir (`persons[p].off`).
Lot A (docs/compo.md §11) : la CAPTURE, sur le chemin de la prise Rec — tap = démarre (décompte du
Rec), tap = arrête ; le manifeste déclare `kind:"riff"`, `by`, `target`, `lanes[]` ; 20 s de fenêtre de
drop, puis transcription et montée des SEULS fichiers de la personne.
La PRISE DE STANDARD (docs/compo.md §11) : la même cible, `kind:"standard-take"` — le Standard joue la grille sur la
lane de la personne, sur l'horloge de l'enregistrement, et take.json dit ce qui a été joué.
"""
import contextlib
import math
import re
import threading
import time

from . import config as C  # noqa: F401  (chemins, cohérence avec les autres modules)
from .golog import get
from .state import state

log = get("compo")
MODES = ("append", "replace")
_lock = threading.Lock()
_on_change = None


def init(on_change=None):
    """Injecté par app.py : le broadcast WebSocket, pour que /live et le Companion voient une cible
    arriver sans attendre un autre événement."""
    global _on_change
    _on_change = on_change


def _changed():
    state.touch()
    if _on_change:
        try:
            _on_change()
        except Exception as e:                       # jamais fatal : l'état est déjà posé
            log.warning(f"broadcast compo : {e}")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── cibles « Follow Golem » (§10) ──────────────────────────────────────────────────────────────
def set_target(person, target=None, clear=False):
    """`{cmd:"compo-target", person, target:{id, mode, title, band}}` ou `{…, person, clear:true}`.
    Rend (ok, why). `target.id` est OPAQUE : recopié, jamais interprété."""
    person = str(person or "").strip()[:64]
    if not person:
        return False, "no person"
    with _lock:
        targets = dict(state.compo.get("targets") or {})
        if clear or not target:
            had = person in targets
            targets.pop(person, None)
            state.compo = {**state.compo, "targets": targets}
            if had:
                log.info(f"cible retirée pour {person}")
            _changed()
            return True, "cleared" if had else "nothing armed"
        if not isinstance(target, dict) or not target.get("id"):
            return False, "target needs an id"
        std = target.get("kind") == STD_KIND
        mode = str(target.get("mode") or ("replace" if std else "append"))
        # ⚠ une prise de standard a SES modes (replace | add) : `add` n'est pas un mode de riff, `append` n'en est pas un d'elle
        if mode not in (STD_MODES if std else MODES):
            return False, f"unknown mode: {mode}"
        t = {"id": str(target["id"])[:120], "mode": mode,
             "title": str(target.get("title") or "")[:120] or None,
             "band": str(target.get("band") or "")[:64] or None, "since": _now()}
        if target.get("lane"):
            t["lane"] = str(target["lane"])[:64]
        # LA PLACE DE L'ESPACE, FIGÉE À L'ARMEMENT (golem.fm, 2026-10-14) : `space` en octets, et `blocked: "quota"` sous
        # 64 Mio. On garde la cible ET la raison : /live dit « storage full », et le tap est refusé (rien ne partirait)
        sp = target.get("space")
        if isinstance(sp, dict):
            with contextlib.suppress(TypeError, ValueError):
                t["space"] = {"free_bytes": int(sp.get("free_bytes")), "quota_bytes": int(sp.get("quota_bytes"))}
        if target.get("blocked") in ("quota",):
            t["blocked"] = target["blocked"]
        if std:
            st, take, bad = standard_params(target)
            if bad:
                _refuse(person, bad)                 # la page armée le lit dans les frames `pos`, comme un tap refusé
                return False, bad
            # recopiée telle quelle dans take.json (docs/compo.md §11) : golem.fm range la prise d'après ce qu'IL a envoyé
            t.update(kind=STD_KIND, std=st, take=take, sent=_copy_target(target))
        else:
            take, bad = take_params(target)
            if bad:
                return False, bad
            if take:
                t["take"] = take
            if target.get("bed") is not None:
                bad = _bed_of(t, target["bed"])
                if bad:
                    return False, bad
        targets[person] = t
        state.compo = {**state.compo, "targets": targets}
    log.info(f"cible pour {person} : « {t['title'] or t['id']} » · {mode}"
             + (f" · bed {t['bed'].get('sha256', '?')[:8]} {t['bed']['state']}" if t.get("bed") else ""))
    _changed()
    if (t.get("bed") or {}).get("state") == "fetching":
        threading.Thread(target=_bed_prefetch, args=(person, dict(t["bed"])), daemon=True, name="bed-prefetch").start()
    return True, "armed"


# ── le bed (§12 ter) : les autres instruments, prémixés par golem.fm, un fichier par sha à côté du click ─────────────────────────
def _bed_of(t, raw):
    """Pose `t["bed"]` d'après `target.bed`. Rend la raison d'un REFUS de l'armement, ou None. Un bed qu'on ne peut pas
    jouer (offset, format, sha mal formé) n'est pas un refus : la cible est armée, `bed: "failed: …"` le dit avant le tap,
    et le tap est refusé avec cette raison — on ne retombe jamais en silence sur le click seul."""
    from . import compo_bed
    take = t.get("take")
    if not take:
        return "bad take: a bed needs bpm and bars"
    if not take["passes"]:
        return "bad take: no bed in loop mode"
    bed, why = compo_bed.clean(raw)
    if why:
        sha = str((raw or {}).get("sha256") or "")[:64] if isinstance(raw, dict) else ""
        t["bed"] = {"sha256": sha, "state": compo_bed.state_of(why)}
    else:
        t["bed"] = {**bed, "state": compo_bed.state_of(path=compo_bed.cached(bed))}
    return None


def _bed_state(person, sha, st):
    """Le nouvel état du bed de la cible de `person`, si c'est toujours CE bed (un réarmement a pu le remplacer)."""
    with _lock:
        targets = dict(state.compo.get("targets") or {})
        t = targets.get(person)
        if not t or (t.get("bed") or {}).get("sha256") != sha or t["bed"].get("state") == st:
            return
        targets[person] = {**t, "bed": {**t["bed"], "state": st}}
        state.compo = {**state.compo, "targets": targets}
    _changed()


def _bed_prefetch(person, bed):
    from . import compo_bed
    path, why = compo_bed.fetch(bed)
    if why:
        log.warning(f"bed {bed['sha256'][:8]} pour {person} : {why}")
    _bed_state(person, bed["sha256"], compo_bed.state_of(why, path))


def armed_frames():
    """Avant le tap (§12 ter) : l'état du bed de chaque cible armée qui en porte un — pour les frames `pos`."""
    out = []
    for person, t in sorted((state.compo.get("targets") or {}).items()):
        if (t or {}).get("bed"):
            out.append({"person": person, "target_id": t.get("id"), "bed": t["bed"].get("state")})
    return out


def take_params(target):
    """LA PRISE ARMÉE (§12, lot B) : ce que golem.fm envoie avec l'armement pour qu'un tap enregistre
    PAR-DESSUS un riff — `bpm`, `sig:{num,den}`, `count_in` (mesures), `bars`, `passes`, `click`.
    Le rack ne devine rien : sans `bpm` ET `bars`, c'est une capture libre (lot A). Rend (take|None, erreur|None)."""
    if not isinstance(target, dict) or target.get("bpm") is None or target.get("bars") is None:
        return None, None
    try:
        bpm = float(target["bpm"])
        sig = target.get("sig") or {"num": 4, "den": 4}
        num, den = int(sig.get("num") or 4), int(sig.get("den") or 4)
        take = {"bpm": bpm, "sig": {"num": num, "den": den}, "count_in": int(target.get("count_in") or 0),
                # `passes: 0` = EN BOUCLE jusqu'au Stop (§12 bis) — absent = 1
                "bars": int(target["bars"]), "passes": int(1 if target.get("passes") is None else target["passes"]),
                "click": "count-in" if target.get("click") == "count-in" else "always"}
    except (TypeError, ValueError, AttributeError):
        return None, "bad take: bpm, sig, count_in, bars and passes are numbers"
    if not 20 <= take["bpm"] <= 400:
        return None, "bad take: bpm out of 20-400"
    if not (1 <= num <= 32 and den in (1, 2, 4, 8, 16, 32)):
        return None, "bad take: sig"
    if not 0 <= take["count_in"] <= 4 or not 1 <= take["bars"] <= 512 or not 0 <= take["passes"] <= 16:
        return None, "bad take: count_in 0-4, bars 1-512, passes 0-16 (0 = loop until Stop)"
    # L'ACCORDAGE DU RIFF (2026-10-29, golem.fm le lit sur le riff gardé) : des notes MIDI, une par corde. Le rack en
    # déduit la guitare jouée (inharm.guitar_for) au lieu de croire un nom de profil déclaré par la page
    tun = target.get("tuning")
    if tun is not None:
        if not (isinstance(tun, list) and 4 <= len(tun) <= 9
                and all(isinstance(p, int) and not isinstance(p, bool) and 0 <= p <= 127 for p in tun)):
            return None, "bad take: tuning is 4 to 9 MIDI notes"
        take["tuning"] = sorted(tun)
    return take, None


# ── la prise de standard (docs/compo.md §11) ─────────────────────────────────────────────────────────────────
STD_KIND = "standard-take"
STD_MODES = ("replace", "add")
STD_PARTS = ("keys", "bass", "drums", "guitar")
# le rôle de la cible -> les rôles de lane qui le jouent (lane_stomps.LANE_ROLES_OF_DEVICE, sans `line` : une entrée
# ligne peut être n'importe quoi, et une prise sur la mauvaise lane ne se rattrape pas)
STD_LANE_ROLES = {"guitar": ("guitar",), "bass": ("bass",), "keys": ("keys", "keys-pads")}


def _copy_target(target):
    """La cible telle que golem.fm l'a envoyée, bornée : des scalaires et `parts`/`space`, rien d'autre."""
    out = {}
    for k, v in list(target.items())[:32]:
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)[:32]] = v[:200] if isinstance(v, str) else v
        elif isinstance(v, dict) and k in ("parts", "space"):
            out[k] = {str(a)[:32]: b for a, b in list(v.items())[:8] if isinstance(b, (str, int, float, bool))}
    return out


def standard_params(target):
    """La cible d'une prise de standard (docs/compo.md §11) -> (std, take, erreur). `take` a la forme de la prise armée d'un riff
    (riffclick.timing) : un tour de grille = `bars`, les tours = `passes` (0 = en boucle jusqu'au Stop)."""
    from . import standards
    slug = str(target.get("standard") or "").strip()[:120]
    if not slug:
        return None, None, "a standard take needs a standard"
    grid = standards.get_grid(slug)
    if not grid:
        return None, None, "standard not on this golem"
    role = target.get("role")
    if role not in STD_LANE_ROLES:
        return None, None, "bad take: role is guitar, bass or keys"
    click = target.get("click") or "count-in"
    if click not in ("count-in", "always"):
        return None, None, "bad take: click is count-in or always"
    try:
        bpm = float(target["bpm"])
        count_in = int(target.get("count_in") or 0)
        choruses = int(1 if target.get("choruses") is None else target["choruses"])
    except (KeyError, TypeError, ValueError):
        return None, None, "bad take: bpm, count_in and choruses are numbers"
    if not 20 <= bpm <= 400:
        return None, None, "bad take: bpm out of 20-400"
    if not 0 <= count_in <= 4 or not 0 <= choruses <= 16:
        return None, None, "bad take: count_in 0-4, choruses 0-16 (0 = loop until Stop)"
    key = str(target["key"])[:8] if target.get("key") else None
    flat = standards.flatten(grid, key=key, choruses=1)   # UN tour : les fins déroulées dedans, tous les tours égaux
    if not flat["bars"] or len(flat["bars"]) > 512:
        return None, None, "this standard has no playable form"
    beats = int(flat.get("beats") or 4)
    parts = target.get("parts") if isinstance(target.get("parts"), dict) else {}
    std = {"slug": slug, "key": key, "role": role,
           "parts": {k: bool(parts.get(k)) for k in STD_PARTS}}
    if target.get("lane"):
        std["lane"] = str(target["lane"])[:64]
    take = {"bpm": bpm, "sig": {"num": beats, "den": 4}, "count_in": count_in, "bars": len(flat["bars"]),
            "passes": choruses, "click": click}
    return std, take, None


def standard_lane(preset, person, std, cfg=None, imap=None):
    """LA lane de la prise (docs/compo.md §11) -> (lane, refus). Sans `lane` dans la cible : la lane allumée de la personne qui a
    le rôle demandé. Zéro ou plusieurs : refus, sans en choisir une au hasard."""
    lanes = [l for l in lanes_of_person(preset, person, cfg, imap) if l["on"]]
    if std.get("lane"):
        hit = [l for l in lanes if l["id"] == std["lane"]]
    else:
        hit = [l for l in lanes if l.get("role") in STD_LANE_ROLES[std["role"]]]
    if not hit:
        return None, "lane not in this preset"
    if len(hit) > 1:
        names = ", ".join(l["name"] for l in hit)
        return None, f"{person} has {len(hit)} {std['role']} lanes in this preset ({names}) — turn the others off in the Compo drawer"
    return hit[0], None


def target_of(person):
    return (state.compo.get("targets") or {}).get(str(person or ""))


def apply_cmd(msg):
    """Branche de follow_uplink._apply_cmd. Rend True si la commande était pour nous."""
    if isinstance(msg, dict) and msg.get("cmd") in ("compo-start", "compo-stop"):
        ok, why = remote(msg["cmd"], msg.get("person"))
        if not ok:
            log.warning(f"{msg['cmd']} refusée : {why} — {str(msg)[:160]}")
        return True
    if not isinstance(msg, dict) or msg.get("cmd") != "compo-target":
        return False
    ok, why = set_target(msg.get("person"), msg.get("target"), clear=bool(msg.get("clear")))
    if not ok:
        log.warning(f"compo-target refusée : {why} — {str(msg)[:160]}")
    return True


# ── l'auteur et ses lanes (§4) ─────────────────────────────────────────────────────────────────
def _imap():
    from . import inputmap
    try:
        return inputmap.current() or {}
    except Exception:
        return {}


def foot_person(cfg=None, imap=None):
    """À qui appartient le switch du pédalier du rack : `foot_person` de la config, sinon la
    première entrée (dans l'ordre des canaux) qui porte une personne, sinon None."""
    from . import store
    cfg = cfg or store.load_compo_cfg()
    if cfg.get("foot_person"):
        return cfg["foot_person"]
    m = imap if imap is not None else _imap()
    ents = sorted((e for e in (m.get("inputs") or []) if e.get("person")), key=lambda e: int(e.get("ch") or 0))
    if ents:
        return ents[0]["person"]
    for u in (m.get("usb") or []):
        if u.get("bound") and u.get("person"):
            return u["person"]
    return None


def _entry_of_lane(L, imap):
    """L'entrée de la carte qu'une lane occupe : (rôle, n°) d'abord, sinon l'entrée physique."""
    by_ch = {str(e.get("ch")): e for e in (imap.get("inputs") or [])}
    by_rn = {(e.get("role"), int(e["nth"])): e for e in by_ch.values() if e.get("nth") and e.get("role")}
    if L.get("midi"):
        # le port que le moteur joue (vital.lane_port) — un « usb » nu n'est pas le port 1
        lp = imap.get("lane_ports")
        if str(L.get("in_sel") or "usb") != "usb":
            port = int(re.sub(r"\D", "", str(L.get("in_sel"))) or 1)
        else:
            port = lp.get(L.get("role") or "keys") if isinstance(lp, dict) else 1
        return next((u for u in (imap.get("usb") or []) if int(u.get("port") or 0) == port), None)
    r, n = L.get("in_role"), L.get("in_nth")
    if r and n:
        return by_rn.get((r, int(n)))
    return by_ch.get(str(L.get("in_sel") or ""))


def lanes_of_person(preset, person, cfg=None, imap=None):
    """Les lanes de `person` dans ce preset : [{id, name, role, on}] — `on` = capturée (pas
    décochée dans le tiroir). Vide si la personne n'a aucune entrée dans la carte du mode."""
    from . import store
    if not preset or not person:
        return []
    cfg = cfg or store.load_compo_cfg()
    m = imap if imap is not None else _imap()
    off = set(((cfg.get("persons") or {}).get(person) or {}).get("off") or [])
    out = []
    for L in store.lanes_of(preset):
        e = _entry_of_lane(L, m)
        if e and e.get("person") == person:
            out.append({"id": L["id"], "name": L.get("name") or L["id"], "role": L.get("role"),
                        "on": L["id"] not in off})
    return out


# ── la capture (lot A, docs/compo.md §11) ──────────────────────────────────────────────────────
DROP_S = 20
_STALE_S = 30                  # un départ qui ne roule jamais (refus Reaper, disque) est oublié
RIFF = {"active": None, "last": None}
_CAP = re.compile(r"Input-(\d+)", re.I)


def _perf_status():
    import json, os
    try:
        return json.load(open(os.path.join(C.PRESETS_DIR, ".perf.json")))
    except Exception:
        return {}


def _publish():
    a, l = RIFF["active"], RIFF["last"]
    if a:
        st = {"state": "rec" if a.get("rolling") else ("loading" if a.get("loading") else "counting"),
              "person": a["person"]}
        if a.get("take"):
            st["take"] = a["take"]
    elif l:
        st = {k: l.get(k) for k in ("state", "person", "uid", "until")}
    else:
        st = None
    state.compo = {**state.compo, "riff": st}
    _changed()


def note_upload(name, rep):
    """Le résultat de l'envoi d'une prise (bridge/uploader.py). Si c'est un RIFF : le dernier refus va dans l'état
    publié (`compo.riff_fail` : {why, uid, at}) — la case Riff de /live le dit ; un envoi réussi l'efface."""
    from . import takes
    man = takes._read_json(takes.manifest_path_of(name) or "") or {}
    if man.get("kind") not in ("riff", STD_KIND):
        return
    fail = None if rep.get("ok") else {"why": rep.get("why") or rep.get("reason") or "failed",
                                       "uid": rep.get("uid"), "at": _now()}
    if (state.compo or {}).get("riff_fail") != fail:
        state.compo = {**(state.compo or {}), "riff_fail": fail}
        _changed()


def _lane_inputs(preset, lanes, imap):
    """{lane id: n° d'entrée audio ("1"…) | "usb"} — l'entrée que chaque lane de la personne occupe."""
    from . import store
    out = {}
    by_id = {L["id"]: L for L in store.lanes_of(preset)}
    for ln in lanes:
        L = by_id.get(ln["id"])
        e = _entry_of_lane(L, imap) if L else None
        if not e:
            continue
        out[ln["id"]] = "usb" if L.get("midi") else str(e.get("ch"))
    return out


def _lane_tracks(preset, lanes):
    """{lane id: n° de la piste d'entrée du rig} — pour une lane MIDI, celui de « MIDI-Input-N.mid » ET de
    « Input-N.wav », le son de son instrument (une lane MIDI n'a pas de n° d'entrée audio)."""
    from . import store
    by_id = {L["id"]: L for L in store.lanes_of(preset)}
    return {ln["id"]: str(by_id[ln["id"]]["input"]) for ln in lanes if by_id.get(ln["id"], {}).get("input") is not None}


def _check_recorder(inputs):
    """Raison d'un refus, ou None. Un riff déclare SES lanes : il faut des pistes par entrée, et au moins une
    entrée — la prise les enregistre toutes (riff_inputs)."""
    from . import modes as modes_mod, store
    if not modes_mod.allows("perfrec", state.mode):
        return f"the recorder is off in {(state.mode or {}).get('name') or 'this mode'}"
    rc = store.load_recorder_cfg() or {}
    if rc.get("mode") not in ("tracks", "tracks_di"):
        return "the recorder is on Mix — a riff needs one track per input (Rec ▸ Multi)"
    if not inputs:
        return "none of your lanes has an input — set one in the Designer"
    # les cases IN / USB du Rec ne comptent pas ici : la prise du riff enregistre les entrées de SES lanes
    # (store.rec_sources(force=…), publié par app._foot_perf_toggle) — un riff de clavier sur USB était refusé
    return None


def riff_inputs():
    """Les entrées ("usb" | "1"…) des lanes du riff armé — ce que sa prise doit enregistrer. () sans riff."""
    a = RIFF["active"]
    return tuple(sorted({ln.get("input") for ln in (a or {}).get("lanes") or () if ln.get("input")}))


def tap(source="foot", person=None, preset=None, hold=False, toggle=None):
    """Un appui sur le switch Compo (ou l'écran / le Companion). `person` vient de l'appareil ; au pied
    du rack c'est foot_person(). `toggle(want)` = le chemin de la prise Rec (app._foot_perf_toggle :
    garde disque, veto, décompte, départ différé). Rend le compte rendu posé dans state.compo.last."""
    from . import modes as modes_mod, store
    cfg = store.load_compo_cfg()
    a = RIFF["active"]
    if a and not a.get("rolling") and time.time() - a["t"] > _STALE_S and not _perf_status().get("recording"):
        if a.get("kind") == STD_KIND:
            _restore(a)                              # la grille armée n'attend plus une prise qui ne viendra pas
        RIFF["active"] = a = None                    # un départ jamais parti ne bloque pas le suivant
    who = person or (a or {}).get("person") or foot_person(cfg)
    rep = {"t": _now(), "source": source, "person": who, "hold": bool(hold)}
    if a:
        # ── l'ARRÊT : la même personne, ou le pied du rack ─────────────────────────────────────
        if person and person != a["person"]:
            rep["refused"] = f"{a['person']} is recording a riff — only they can stop it"
        else:
            a["t_stop"] = time.time()                # l'instant du geste : la boucle en cours s'arrête LÀ
            if toggle:
                toggle(False)
            if not a.get("rolling"):
                RIFF["active"] = None                # arrêté pendant le décompte = annulé, rien n'est écrit
                rep["capture"] = "cancelled"
            else:
                rep["capture"] = "stop"
    elif not modes_mod.allows("compo", state.mode):
        rep["refused"] = f"off in {(state.mode or {}).get('name') or 'this mode'}"
    elif not who:
        rep["refused"] = "no one owns this switch — set the person in the Compo drawer"
    else:
        rep["target"] = target_of(who)
        std = (rep["target"] or {}).get("kind") == STD_KIND
        why_lane = None
        if std:
            # UNE lane, celle du rôle de la prise (docs/compo.md §11) — pas toutes celles de la personne
            lane, why_lane = standard_lane(preset, who, rep["target"]["std"], cfg)
            lanes = [lane] if lane else []
        else:
            lanes = [l for l in lanes_of_person(preset, who, cfg) if l["on"]]
        rep["lanes"] = [l["id"] for l in lanes]
        inputs = _lane_inputs(preset, lanes, _imap()) if lanes else {}
        perf = _perf_status()
        if not lanes:
            rep["refused"] = why_lane or f"{who} has no lane in this preset"
        elif perf.get("recording") or (state.perf_countin or {}).get("until", 0) > time.time():
            rep["refused"] = "a take is already recording — stop it first"
        else:
            why = _check_recorder(inputs)
            if not why and (rep["target"] or {}).get("blocked") == "quota":
                why = "this golem.fm space is full — free some room or upgrade the plan"
            if not why and std:
                why = _standard_refusal()
            if not why and not std and (rep["target"] or {}).get("take") and not modes_mod.allows("backing", state.mode):
                why = (f"the backing track is off in {(state.mode or {}).get('name') or 'this mode'} — "
                       "a take on a riff plays its click there")
            if not why and not std and (rep["target"] or {}).get("take") and (state.backing or {}).get("playing"):
                # la prise armée part À ZÉRO sur la timeline, avec son click : un transport qui roule déjà
                # la ferait partir ailleurs, et le « 1 » ne tomberait plus à `downbeat_s`
                why = "the backing is playing — stop it first"
            if why:
                rep["refused"] = why
            else:
                take = (rep["target"] or {}).get("take")
                tracks = _lane_tracks(preset, lanes)
                RIFF["active"] = {"person": who, "t": time.time(), "rolling": False, "source": source,
                                  "target": dict(rep["target"]) if rep["target"] else None,
                                  "lanes": [dict(l, input=inputs.get(l["id"]), track=tracks.get(l["id"])) for l in lanes],
                                  "toggle": toggle, "take": take, "kind": STD_KIND if std else "riff"}
                RIFF["last"] = None
                if take and _HOOKS.get("standard_start" if std else "armed_start"):
                    # LA PRISE ARMÉE (§12) : le click est un FICHIER sur la timeline, la prise part à 0 avec
                    # lui — le « 1 » tombe à `downbeat_s` exactement. Rendu + chargement hors du fil du pied.
                    RIFF["active"]["loading"] = True
                    threading.Thread(target=_armed_start, args=(RIFF["active"],), daemon=True, name="riff-armed").start()
                    rep["capture"] = "start-armed"
                else:
                    if toggle:
                        toggle(True)
                    rep["capture"] = "start"
    state.compo = {**state.compo, "last": rep}
    if rep.get("refused"):
        RIFF["refused"] = {"person": who, "why": rep["refused"], "t": time.time(),
                           "target_id": (rep.get("target") or target_of(who) or {}).get("id")}
        log.warning(f"tap {source} par {who or '?'} refusé : {rep['refused']}")
    else:
        RIFF["refused"] = None
        tg = rep.get("target")
        log.info(f"riff {rep.get('capture')} ({source}) par {who}"
                 + (f" · lanes {rep['lanes']}" if rep.get("lanes") else "")
                 + (f" · → « {tg.get('title') or tg.get('id')} » {tg.get('mode')}" if tg else ""))
    _publish()
    return rep


def _standard_refusal():
    """Ce qui empêche une prise de standard de partir (docs/compo.md §11), ou None. La prise part à 0 AVEC le Standard : une
    backing ou une boîte à rythmes qui roule déjà ferait deux horloges. Présentes mais à l'arrêt, elles ne gênent pas."""
    from . import modes as modes_mod
    if not modes_mod.allows("standard", state.mode):
        return f"the Standard is off in {(state.mode or {}).get('name') or 'this mode'}"
    if (state.backing or {}).get("playing"):
        return "the backing is playing — stop it first"
    if any((d or {}).get("playing") for d in (state.drums or {}).values() if isinstance(d, dict)):
        return "the drum machine is playing — stop it first"
    return None


def on_perf_start():
    """monitors : la prise a VRAIMENT démarré (front du perf-rec) — le riff roule."""
    a = RIFF["active"]
    if a and not a.get("rolling"):
        a["rolling"] = True
        a["t_rolling"] = time.time()
        take = a.get("take")
        if take and a.get("armed"):
            # LONGUEUR FIXE (§12) : décompte + bars × passes, plus un temps de marge — l'arrêt n'a pas
            # à tomber pile, golem.fm coupe au sample depuis `downbeat_s`
            from . import riffclick
            beat, _bar, _down, total = riffclick.timing(take)
            t = threading.Timer(total + beat, _auto_stop, args=(a,))
            t.daemon = True
            a["stop_timer"] = t
            t.start()
        _publish()


def claim_riff():
    """monitors, à l'écriture du manifeste : le riff de CETTE prise (et on l'oublie), ou None."""
    a = RIFF["active"]
    if a and a.get("rolling"):
        RIFF["active"] = None
        a.setdefault("t_stop", time.time())
        t = a.get("stop_timer")
        if t:
            t.cancel()
        if a.get("armed"):
            _restore(a)                              # le backing du preset reprend sa place / le Standard s'arrête
        return a
    return None


# ── la prise armée (§12, lot B) ────────────────────────────────────────────────────────────────
# app.py branche ici ce que compo ne connaît pas : charger un fichier dans la piste Backing, lancer la
# prise AVEC le backing et sans le décompte du Rec, reposer le backing du preset après.
_HOOKS = {}


def bind(**hooks):
    _HOOKS.update(hooks)


def _restore(a):
    """Après une prise armée : chaque sorte rend ce qu'elle a pris (le riff la piste Backing, le standard la grille,
    le tempo et le click)."""
    hook = _HOOKS.get("standard_restore" if a.get("kind") == STD_KIND else "restore")
    if hook:
        try:
            hook()
        except Exception as e:
            log.warning(f"état du preset non reposé après la prise armée : {e}")


def _armed_start(a):
    import os
    from . import riffclick
    alive = lambda: RIFF["active"] is a                # noqa: E731
    try:
        if a.get("kind") == STD_KIND:
            ok, why = _HOOKS["standard_start"](a, alive)
        else:
            bed = (a.get("target") or {}).get("bed")
            extra = {}
            ok, why = True, None
            if bed:
                # LE BED (§12 ter) : attendu ici, pendant `loading` — absent, la prise ne part pas (jamais le click seul)
                from . import compo_bed
                if not bed.get("url"):
                    bp, bwhy = None, bed["state"].removeprefix("failed: ")
                else:
                    bp, bwhy = compo_bed.wait(bed, alive)
                    _bed_state(a["person"], bed["sha256"], compo_bed.state_of(bwhy, bp))
                if bp:
                    extra["bed"] = (bp, bed["gain_db"])
                    a["bed_sha"] = bed["sha256"]
                else:
                    ok, why = False, f"bed not available: {bwhy}"
            if ok:
                path = os.path.join(C.PRESETS_DIR, ".riff-click.wav")
                from . import store
                riffclick.render(a["take"], path, level_db=(store.load_click_cfg() or {}).get("level", -12.0))
                ok, why = _HOOKS["armed_start"](path, alive, **extra)
    except Exception as e:
        ok, why = False, str(e)
    if RIFF["active"] is not a:
        if a.get("kind") == STD_KIND:
            _restore(a)                              # une grille armée partirait au prochain play du transport
        return                                       # annulé pendant le chargement
    a["loading"] = False
    if not ok:
        RIFF["active"] = None
        state.compo = {**state.compo, "last": {**(state.compo.get("last") or {}), "refused": why}}
        # le refus d'après `loading` passe par les frames `pos` comme les autres (§13) — sinon la page voyait
        # loading → rien → « Armed », sans un mot (test réel du 2026-09-30)
        RIFF["refused"] = {"person": a["person"], "why": why, "t": time.time(),
                           "target_id": (a.get("target") or {}).get("id")}
        log.warning(f"prise armée non partie : {why}")
        _restore(a)
    else:
        a["armed"] = True
    _publish()


def backing_needed():
    """monitors : une prise armée occupe la piste Backing (son click) — il faut la lire, preset ou pas."""
    a = RIFF["active"]
    return bool(a and a.get("take") and a.get("kind") != STD_KIND)   # une prise de standard n'a pas de click-fichier


def _auto_stop(a):
    if RIFF["active"] is a and a.get("rolling") and a.get("toggle"):
        log.info(f"riff de {a['person']} : longueur atteinte — arrêt")
        a["t_stop"] = time.time()
        a["toggle"](False)


# ── le départ depuis la page (§13, lot D) ─────────────────────────────────────────────────────
_REFUSED_S = 6.0


def _refuse(person, why):
    RIFF["refused"] = {"person": person, "why": why, "t": time.time(),
                       "target_id": (target_of(person) or {}).get("id")}
    _publish()
    return False, why


def remote(cmd, person):
    """`compo-start` / `compo-stop` venus de golem.fm (docs/compo.md §13) — les garde-fous du mainteneur
    (2026-09-30) : la personne qui a ARMÉ seulement, jamais pendant une prise, jamais en mode verrouillé.
    Le départ passe par LE chemin du pied (app._compo_tap) : aucune règle n'existe en deux copies."""
    person = str(person or "").strip()[:64]
    if not person:
        return False, "no person"
    tap_fn = _HOOKS.get("tap")
    if not tap_fn:
        return _refuse(person, "the rack is not ready")
    a = RIFF["active"]
    if cmd == "compo-stop":
        if not a:
            return _refuse(person, "nothing is recording")
        if a["person"] != person:
            return _refuse(person, f"{a['person']} is recording — only they can stop it")
        rep = tap_fn(source="golem.fm", person=person)
        return (False, rep["refused"]) if rep.get("refused") else (True, None)
    if (state.mode or {}).get("ui", {}).get("locked"):
        return _refuse(person, f"the rack is in {(state.mode or {}).get('name') or 'a locked'} mode — start at the foot")
    if not target_of(person):
        return _refuse(person, "arm the rack on a riff first")
    if a or _perf_status().get("recording"):
        return _refuse(person, "a take is already recording")
    rep = tap_fn(source="golem.fm", person=person)
    if rep.get("refused"):
        return _refuse(person, rep["refused"])
    return True, None


def riff_frame():
    """Le compte, pour les frames `pos` de l'uplink (§12) — dit par le rack, au temps du FICHIER."""
    from . import riffclick
    # `target_id` : la cible ARMÉE de la prise, recopiée opaque — deux pages peuvent armer la même personne (une
    # section depuis le player, le riff ouvert ailleurs) ; sans l'id elles ne savent pas laquelle tourne. Absent = capture libre
    def tid(out, t):
        return {**out, "target_id": t} if t else out
    rf = RIFF.get("refused")
    if rf and time.time() - rf["t"] < _REFUSED_S and not RIFF["active"]:
        return tid({"person": rf["person"], "state": "refused", "why": rf["why"]}, rf.get("target_id"))
    a = RIFF["active"]
    if not a:
        l = RIFF["last"]
        return (tid({"state": "arriving", "person": l.get("person")}, l.get("target_id"))
                if l and l.get("state") in ("held", "sending") else None)
    take = a.get("take")
    out = tid({"person": a["person"]}, (a.get("target") or {}).get("id"))
    if (a.get("target") or {}).get("bed"):
        # l'état du bed de CETTE cible, tel qu'il est maintenant (le tap l'attend pendant `loading`)
        cur = (target_of(a["person"]) or {}).get("bed") or {}
        out["bed"] = cur.get("state") if cur.get("sha256") == a["target"]["bed"].get("sha256") else a["target"]["bed"].get("state")
    if a.get("loading"):
        return {**out, "state": "loading"}
    if not take or not a.get("rolling"):
        return {**out, "state": "count" if not a.get("rolling") else "rec"}
    beat, bar, down, total = riffclick.timing(take)
    # le temps de la prise : celui du FICHIER du click (backing) pour un riff ; une prise de standard n'a pas de
    # backing, elle compte depuis son départ
    pos = (None if a.get("kind") == STD_KIND else (state.backing or {}).get("pos")) or (time.time() - a.get("t_rolling", time.time()))
    pos = float(pos)
    if pos < down:
        n = int(pos / beat)
        beats = int(round(down / beat))
        return {**out, "state": "count", "beat": n + 1, "beats": beats, "count_in": beats - n}
    k = int((pos - down) / bar)
    num = take["sig"]["num"]
    # le TEMPS dans la mesure (1..num) : la page allume une case par temps (maquette validée)
    b = min(int((pos - down - k * bar) / beat) + 1, num)
    if not take["passes"]:
        # EN BOUCLE (§12 bis) : la mesure DANS la boucle, `bars` = une boucle, `pass` = la boucle en cours
        return {**out, "state": "rec", "bar": k % take["bars"] + 1, "bars": take["bars"], "beat": b, "beats": num,
                "pass": k // take["bars"] + 1, "passes": 0}
    bars = take["bars"] * take["passes"]
    return {**out, "state": "rec", "bar": min(k + 1, bars), "bars": bars, "beat": b, "beats": num,
            "pass": min(k // take["bars"] + 1, take["passes"]), "passes": take["passes"]}


def _files_of(inp, files, track=None):
    """Les fichiers d'une entrée dans le dossier de la prise (golem_perfrec : « DI-Sandbox-Input-1.wav »,
    « Input-1merge.wav », « MIDI-<src>.mid »). Une lane MIDI (`inp` "usb") a son `midi` ET son `wet` : le son de
    l'instrument du patch, post-plugin et FX, sur la piste `track` (« Input-3.wav ») — pas de `di` pour du MIDI."""
    out = {}
    for f in files:
        m = _CAP.search(f)
        if inp == "usb":
            if f.lower().endswith(".mid") and (track is None or (m and m.group(1) == str(track))):
                out["midi"] = f
            elif track is not None and m and m.group(1) == str(track) and not f.startswith("DI-") \
                    and f.lower().endswith((".wav", ".flac")):
                out["wet"] = f
            continue
        if not m or m.group(1) != inp or not f.lower().endswith(".wav"):
            continue
        # `wet`, PAS `track` (compo.md §10.4, FIGÉ) : `track` est le KIND de la piste montée, pas la clé
        # de lane — golem.fm ne lit que wet | di | score | midi (écart trouvé sur la prise 175)
        out["di" if f.startswith("DI-") else "wet"] = f
    return out


def stamp_manifest(man, riff):
    """Complète le take.json d'une capture de riff (§11). Mute `man`."""
    from . import takes
    files = man.get("files") or []
    std = riff.get("kind") == STD_KIND
    man["kind"] = STD_KIND if std else "riff"     # DÉCLARÉ à l'armement, jamais déduit de `standard` (docs/compo.md §11)
    man["by"] = riff["person"]
    man["drop_window_s"] = DROP_S
    tg = riff.get("target")
    if tg:
        band = tg.get("band")
        known = takes.resolve_band(band) if band else None
        if band and not known:
            man["target_dropped"] = "unknown band"
        else:
            man["target"] = {k: tg[k] for k in ("id", "mode", "title", "band") if tg.get(k)}
            if std:
                # la cible ENTIÈRE, telle qu'envoyée, plus la lane que le rack a retenue
                man["target"] = {**(tg.get("sent") or man["target"]),
                                 "lane": (riff["lanes"][0]["id"] if riff.get("lanes") else None)}
            if known:
                man["band"] = known
    lanes = []
    for l in riff["lanes"]:
        fs = _files_of(l.get("input"), files, l.get("track")) if l.get("input") else {}
        if fs:
            lanes.append({"id": l["id"], "name": l.get("name"), "role": l.get("role"),
                          "input": l.get("input"), "files": fs})
    man["lanes"] = lanes
    # CE AVEC QUOI LE RIFF A ÉTÉ JOUÉ, dit clairement (2026-09-30) : `preset_name` était pris pour le TITRE
    # par golem.fm (« le groupe » pour chaque riff) et, pour un patch, portait « ⛓ … ». Le rig voyage en
    # information ; le titre d'une capture LIBRE est générique et daté — le NUMÉRO est celui de golem.fm (rf:N),
    # le rack n'en fabrique pas un second. Une capture sur un riff armé n'a pas de titre : elle entre dans CE riff.
    pid = str(man.get("preset") or "")
    pname = str(man.get("preset_name") or "").replace("⛓", "", 1).strip() or None
    if pid.startswith("patch:"):
        man["rig"] = {"kind": "patch", "id": pid[len("patch:"):], "name": pname}
    elif pid == "sandbox-try":
        man["rig"] = {"kind": "trial", "id": None, "name": pname}
    elif pid:
        man["rig"] = {"kind": "preset", "id": pid, "name": pname}
    if not man.get("target") and not man.get("title"):
        when = str(man.get("started_at") or _now()).replace("T", " ")[:16]
        man["title"] = f"Riff {when}"
    if riff.get("bed_sha"):
        man["bed"] = {"sha256": riff["bed_sha"]}   # ce que la prise a entendu (§12 ter) — rien d'autre
    take = riff.get("take") if riff.get("armed") else None
    man["tempo_source"] = ("standard" if std else "riff") if take else "preset"   # libre : le tempo du PRESET
    if take:
        # LE REPÈRE (§12) : golem.fm pose la prise sur le riff à `downbeat_s` et découpe par passe
        from . import riffclick
        _beat, _bar, down, _total = riffclick.timing(take)
        man.update(bpm=take["bpm"], sig=take["sig"], bars=take["bars"], passes=take["passes"],
                   count_in=take["count_in"], downbeat_s=round(down, 6))
        if take.get("tuning"):
            # la guitare QUI A CET ACCORDAGE (la jouée, `active`, si deux l'ont) ; aucune : `guitar: null`, l'accordage
            # reste gravé et la transcription s'en sert, sans étalonnage
            from . import inharm
            man["tuning"] = take["tuning"]
            man["guitar"] = inharm.guitar_for(take["tuning"])
        if not take["passes"] and riff.get("t_rolling") and riff.get("t_stop"):
            # EN BOUCLE : les boucles COMMENCÉES (indicatif — golem.fm compte les complètes sur la durée)
            played = riff["t_stop"] - riff["t_rolling"] - down
            man["loops"] = max(0, math.ceil(played / (take["bars"] * _bar) - 1e-6))
    if std and take and riff.get("std_played"):
        # CE QUE LE RACK A JOUÉ (docs/compo.md §11) — golem.fm compare `bars` à sa propre forme : différente, la prise arrive marquée.
        # Fusionné dans le `standard` que la prise porte déjà (id, title, played : monitors.PERF_CTX) — `bars` y
        # devient la forme d'un tour, et `played` est vrai par construction : la grille est partie avec la prise.
        man["standard"] = {**(man.get("standard") or {}), **riff["std_played"], "played": True}
    man["upload"] = {"state": "held", "until": time.time() + DROP_S, "at": _now()}
    return man


def after_written(name, riff):
    """Le manifeste est sur le disque : 20 s de fenêtre de drop, puis transcription, puis montée."""
    from . import takes
    uid = takes.uid_of(name)
    RIFF["last"] = {"state": "held", "person": riff["person"], "uid": uid, "name": name,
                    "until": time.time() + DROP_S, "target_id": (riff.get("target") or {}).get("id")}
    _publish()
    threading.Thread(target=_settle, args=(name,), daemon=True, name="riff-settle").start()


def _manifest(name):
    from . import takes
    return takes.manifest_path_of(name), takes._read_json(takes.manifest_path_of(name) or "") or {}


def _write(mp, man):
    import json, os
    tmp = mp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    os.replace(tmp, mp)


def drop(uid=None):
    """Jette le dernier riff pendant sa fenêtre : jamais monté, GARDÉ sur le disque. Rend (ok, why)."""
    l = RIFF["last"]
    if not l or (uid and l.get("uid") != uid):
        return False, "no riff to drop"
    if l.get("state") != "held" or time.time() > (l.get("until") or 0):
        return False, "too late — the riff has left (20 s window)"
    mp, man = _manifest(l["name"])
    if not mp:
        return False, "riff not found"
    man["upload"] = {"state": "dropped", "at": _now()}
    _write(mp, man)
    l["state"] = "dropped"
    log.info(f"riff {l['uid']} jeté par {l.get('person')} (gardé sur le disque)")
    _publish()

    def _forget(uid=l["uid"]):                       # la puce « dropped » se tait après quelques secondes
        if (RIFF["last"] or {}).get("uid") == uid:
            RIFF["last"] = None
            _publish()
    t = threading.Timer(5.0, _forget)
    t.daemon = True
    t.start()
    return True, None


def _label(fn):
    """Le nom qu'une source porte dans scores/index.json — MÊME règle que transcribe_cli (préfixes
    retirés du plus long au plus court)."""
    import os
    base = os.path.splitext(fn)[0]
    for pref in ("DI-Sandbox-", "MIDI-", "DI-"):
        if base.startswith(pref):
            return base[len(pref):]
    return base


def _transcribe(name, man):
    """Transcription avant la montée (§5) : rend "done" | "failed" | "off" | "unavailable" et pose
    `files.score` sur chaque lane transcrite."""
    import json, os
    from . import store, transcribe_jobs as tj, takes
    if not (store.load_compo_cfg() or {}).get("transcribe"):
        return "off"
    if not tj.available():
        return "unavailable"
    r = tj.enqueue(name)
    if not r.get("ok"):
        return "failed"
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(2)
        with tj._lock:
            busy = (tj._cur or {}).get("dir") == name or name in tj._queue
        if not busy:
            break
    try:
        idx = json.load(open(os.path.join(takes.RECORDINGS, name, "scores", "index.json")))
    except Exception:
        return "failed"
    by_src = {str(x.get("src")): x for x in idx.get("sources") or [] if x.get("file")}
    got = False
    for ln in man.get("lanes") or []:
        fs = ln.get("files") or {}
        src = fs.get("midi") or fs.get("di")
        hit = by_src.get(_label(src)) if src else None
        if hit:
            fs["score"] = hit["file"]
            got = True
    return "done" if got else "failed"


def _settle(name):
    l = RIFF["last"]
    wait = (l.get("until") or time.time()) - time.time() if l else DROP_S
    time.sleep(max(0.0, wait))
    mp, man = _manifest(name)
    if not mp or (man.get("upload") or {}).get("state") == "dropped":
        return
    if l and l.get("name") == name:
        l["state"] = "sending"
        _publish()
    # LA FENÊTRE EST FERMÉE, LA TRANSCRIPTION COMMENCE : la prise n'est plus `held` mais pas encore due — sans cet état,
    # une passe du monteur (n'importe quel `queue`) l'envoyait SANS sa partition, puis la fin de la transcription la
    # renvoyait avec une piste de plus et golem.fm refusait (409 « Track 2 already uploaded », rec 242, 2026-10-29)
    man["upload"] = {"state": "transcribing", "since": time.time(), "at": _now()}
    _write(mp, man)
    try:
        man["transcribe"] = _transcribe(name, man)
    except Exception as e:
        log.warning(f"transcription du riff {name} : {e}")
        man["transcribe"] = "failed"
    mp, cur = _manifest(name)
    if (cur.get("upload") or {}).get("state") in ("dropped", "done"):
        if (cur.get("upload") or {}).get("state") == "done":
            log.warning(f"riff {name} déjà monté avant la fin de sa transcription — partition non envoyée")
        return
    cur["lanes"], cur["transcribe"] = man.get("lanes") or cur.get("lanes"), man["transcribe"]
    cur["upload"] = {"state": "pending", "at": _now()}
    _write(mp, cur)
    try:
        from . import uploader, takes
        uploader.queue([takes.uid_of(name)])
    except Exception as e:
        log.warning(f"montée du riff {name} : {e}")
    if l and l.get("name") == name:
        RIFF["last"] = None
        _publish()


