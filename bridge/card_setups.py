# SPDX-License-Identifier: GPL-3.0-or-later
"""Les configurations de carte son voyagent par golem.fm (docs/card-setups-exchange.md, accordé le 2026-10-11).

Chaque rack charge SA configuration (propre à l'OS et au nom sous lequel il voit la carte) ; golem.fm garde celle de
chaque rack de l'utilisateur, clée par identité USB, et rend à un rack les configurations SŒURS de la carte qu'il
tient. Un rack n'est jamais modifié à distance : « Offer this setup to the rack » dépose une proposition que le rack
visé affiche (chip), et l'utilisateur décide devant sa carte. Ici : la lecture des sœurs, l'application LOCALE d'une
configuration par les setters de l'input map (jamais par une écriture brute du fichier), la proposition, le job reçu,
la réponse, et la mémoire locale (« separate », « ask » à la première rencontre).

État local : config/.card-setups.json — {"<usb>": {"ask": bool, "separate": {"<rack>": "<fingerprint>"},
"offers": [{offer_id, from_rack, from_name, offered_at, usb, serial, card, os, fingerprint, setup}]}}.
Le fingerprint est TOUJOURS celui de golem.fm (calculé chez lui) ; le rack n'en calcule aucun.
"""
import datetime as _dt
import json
import os
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("card-setups")

STATE_PATH = os.path.join(C.CONFIG_DIR, ".card-setups.json")
_lock = threading.Lock()
_CACHE = {}                                    # usb -> (t, réponse de golem.fm) ; 60 s
CACHE_S = 60
EXT = "/api/ext/golem/card-setups"


# ── état local ────────────────────────────────────────────────────────────────────────────────────────────
def _state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(d):
    from .store import _write_json_atomic
    _write_json_atomic(STATE_PATH, d, indent=1)


def _entry(d, usb):
    return d.setdefault(usb, {"ask": False, "separate": {}, "offers": []})


def identity(dev):
    """(usb, serial) de la carte `dev` — usb = 'vvvv:pppp' (bridge/cards.usb_of), serial inconnu pour l'instant
    (stocké et rendu par golem.fm, jamais interprété : docs/card-setups-exchange.md §2)."""
    try:
        from . import cards
        return cards.usb_of(dev), None
    except Exception as e:
        _swallowed(e)
        return None, None


def updated_at(dev):
    """Date ISO (UTC) du fichier de configuration de la carte — None s'il n'existe pas encore."""
    try:
        from . import inputmap
        t = os.path.getmtime(inputmap._path(dev))
        return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def local_setup(dev):
    """La configuration de `dev` sous la forme du contrat ({inputs, outputs, midi_in, midi_out}) — la MÊME
    fabrique que le battement (rigstatus.setup_of) : ce que golem.fm compare est ce que le rack envoie."""
    from . import inputmap, rigstatus
    return rigstatus.setup_of(inputmap.current(dev))


# ── golem.fm ──────────────────────────────────────────────────────────────────────────────────────────────
def _http(method, path, body=None, timeout=15):
    from .plugin_recipes import _http as h          # le client de golem.fm (jeton, `detail` déplié)
    return h(method, path, body, timeout=timeout)


def fetch(usb, serial=None, fresh=False):
    """Les sœurs et propositions de golem.fm pour cette identité — None s'il est injoignable ou non appairé.
    Cache 60 s : la page Soundcard et le battement ne le martèlent pas."""
    if not usb:
        return None
    if _state().get("demo"):                     # DEV : une sœur fabriquée, pour voir l'écran sans golem.fm
        return _demo(usb)
    now = time.monotonic()
    hit = _CACHE.get(usb)
    if hit and not fresh and now - hit[0] < CACHE_S:
        return hit[1]
    q = f"?usb={usb}" + (f"&serial={serial}" if serial else "")
    st, body = _http("GET", EXT + q)
    if st != 200 or not isinstance(body, dict):
        if st not in (0, 401, 404):
            log.warning(f"card-setups {usb} : golem.fm {st} {body}")
        _CACHE[usb] = (now, None)
        return None
    _CACHE[usb] = (now, body)
    return body


def _demo(usb):
    return {"usb": usb, "fingerprint": "demo-here",
            "siblings": [{"rack": "rack-linux-demo", "rack_name": "Rack", "os": "linux", "card": "hw:V276",
                          "updated_at": "2026-10-04T09:12:00Z", "received_at": "2026-10-10T20:00:00Z",
                          "fingerprint": "demo-there", "same": False,
                          "inputs": [{"slot": "IN 1", "kind": "audio", "role": "guitar", "nth": 1, "name": "Guitar 1", "pair": None, "person": "player-1"},
                                     {"slot": "IN 2", "kind": "audio", "role": "voice", "nth": 1, "name": "Voice 1", "pair": None, "person": "player-1"}],
                          "outputs": [{"slot": "OUT 1-2", "role": "monitors", "type": None, "pair": "1-2", "person": None}],
                          "midi_in": "fcb", "midi_out": "whammy-dt"}],
            "offers": []}


# ── ce que la page lit ────────────────────────────────────────────────────────────────────────────────────
def status(dev, fresh=False):
    """{usb, serial, local, siblings[+separate], offers, ask, differs, reachable} pour la carte `dev`."""
    usb, serial = identity(dev)
    out = {"card": dev, "usb": usb, "serial": serial, "local": None, "siblings": [], "offers": [],
           "ask": False, "differs": False, "reachable": None}
    if not usb:
        return out
    try:
        out["local"] = local_setup(dev)
    except Exception as e:
        _swallowed(e)
    st = _state()
    ent = st.get(usb) or {}
    remote = fetch(usb, serial, fresh=fresh)
    out["reachable"] = remote is not None
    sep = ent.get("separate") or {}
    sibs = []
    for s in (remote or {}).get("siblings") or []:
        s = dict(s)
        s["separate"] = bool(s.get("fingerprint")) and sep.get(str(s.get("rack"))) == s.get("fingerprint")
        sibs.append(s)
    out["siblings"] = sibs
    # les propositions : celles de golem.fm si joignable, sinon celles reçues par job et gardées ici
    offers = (remote or {}).get("offers") if remote is not None else None
    if offers is None:
        offers = ent.get("offers") or []
    out["offers"] = offers
    out["ask"] = bool(ent.get("ask")) and bool(sibs)
    out["differs"] = any(not s.get("same") and not s.get("separate") for s in sibs)
    return out


# ── appliquer une configuration ICI, par les setters ──────────────────────────────────────────────────────
def apply_setup(dev, setup):
    """Pose `setup` ({inputs, outputs, midi_in, midi_out}, forme du contrat) sur la carte `dev`, entrée par entrée,
    par les setters de l'input map — leurs invariants (numéro unique par rôle, rôles connus, paires) restent les
    juges. Ce qui ne passe pas est DIT dans `skipped`, jamais inventé : une personne inconnue du roster est vidée
    (docs/card-setups-exchange.md §8), un slot absent de cette carte est sauté. Rend {"applied": n, "skipped": [...]}."""
    from . import inputmap as IM
    people = {p for p in IM._people() if p}
    skipped, applied = [], 0

    def cur_chs(kind):
        m = IM.current(dev)
        return [str(e.get("ch")) for e in (m.get("inputs" if kind == "input" else "outputs") or [])]

    def pairing(kind, ch):
        a, _, b = ch.partition("-")
        have = cur_chs(kind)
        if b and ch not in have:
            IM.set_pair(kind, a, b, True, dev)
        elif not b:
            pr = next((c for c in have if "-" in c and a in c.split("-")), None)
            if pr:
                x, y = pr.split("-")
                IM.set_pair(kind, x, y, False, dev)

    for e in setup.get("inputs") or []:
        slot = str(e.get("slot") or "")
        if not slot.startswith("IN ") or (e.get("kind") or "audio") != "audio":
            continue                                           # les ports USB sont ceux du RACK, pas de la carte
        ch = slot[3:].strip()
        try:
            n_in = len(cur_chs("input"))
            if max(int(x) for x in ch.split("-") if x.isdigit()) > max(n_in, 2) + 2 and ch not in cur_chs("input"):
                skipped.append(f"{slot}: not on this card")
                continue
            pairing("input", ch)
            role = e.get("role") or "none"
            if role not in IM._BY_ID:
                skipped.append(f"{slot}: unknown instrument {role}")
                continue
            IM.set_role("input", ch, role, dev)
            if e.get("nth"):
                IM.set_nth(ch, e["nth"], dev)
            p = e.get("person")
            if p and p not in people:
                skipped.append(f"{slot}: {p} is not in this rack's roster — left unassigned")
                p = None
            IM.set_person(ch, p, dev)
            applied += 1
        except ValueError as x:
            skipped.append(f"{slot}: {x}")
    for o in setup.get("outputs") or []:
        slot = str(o.get("slot") or "")
        if not slot.startswith("OUT "):
            continue
        ch = slot[4:].strip()
        try:
            pairing("output", ch)
            role = o.get("role") or "other"
            IM.set_role("output", ch, role if role in IM._OUT_BY_ID else "other", dev)
            p = o.get("person")
            if p and p not in people:
                skipped.append(f"{slot}: {p} is not in this rack's roster — left unassigned")
                p = None
            IM.set_out_person(ch, p, o.get("type") if o.get("type") in ("iem", "wedge") else None, dev)
            applied += 1
        except ValueError as x:
            skipped.append(f"{slot}: {x}")
    for kind in ("midi_in", "midi_out"):
        role = setup.get(kind)
        if not role:
            continue
        try:
            IM.set_role(kind, None, role, dev)
            applied += 1
        except ValueError as x:
            skipped.append(f"{kind}: {x}")
    try:
        from .routes_inputmap import _refresh
        _refresh(reemit=True)                                   # l'état suit, et le rig rejoue sur les bonnes prises
    except Exception as e:
        _swallowed(e)
    _CACHE.clear()                                               # `same` se relira chez golem.fm au prochain passage
    log.info(f"configuration appliquée sur {dev} : {applied} élément(s), {len(skipped)} sauté(s)")
    return {"applied": applied, "skipped": skipped}


def use_sibling(dev, rack):
    """« Use the rack's setup here » : la sœur `rack` (telle que golem.fm l'a rendue) posée sur `dev`."""
    usb, serial = identity(dev)
    remote = fetch(usb, serial) or {}
    s = next((x for x in remote.get("siblings") or [] if str(x.get("rack")) == str(rack)), None)
    if not s:
        raise ValueError("that rack's setup is not available right now")
    r = apply_setup(dev, {k: s.get(k) for k in ("inputs", "outputs", "midi_in", "midi_out")})
    with _lock:
        st = _state()
        _entry(st, usb)["ask"] = False
        _save_state(st)
    return r


# ── les gestes ────────────────────────────────────────────────────────────────────────────────────────────
def offer(dev, to_rack):
    """« Offer this setup to the rack » : la configuration de `dev` déposée chez golem.fm pour `to_rack`.
    Rend (status, corps) — 202 {offer_id, fingerprint} attendu."""
    usb, serial = identity(dev)
    if not usb:
        return 0, {"error": "this card has no USB identity — nothing to offer"}
    body = {"usb": usb, "to_rack": str(to_rack), "card": dev, "setup": local_setup(dev)}
    if serial:
        body["serial"] = serial
    st, res = _http("POST", EXT + "/offers", body)
    if st == 202:
        log.info(f"configuration de {dev} proposée au rack {to_rack} : {res}")
    return st, res


def separate(dev, rack):
    """« Keep them separate » : local au rack — la sœur `rack` ne réveille plus le chip tant que son fingerprint
    (celui de golem.fm) ne change pas."""
    usb, serial = identity(dev)
    remote = fetch(usb, serial) or {}
    s = next((x for x in remote.get("siblings") or [] if str(x.get("rack")) == str(rack)), None)
    if not s or not s.get("fingerprint"):
        raise ValueError("nothing to remember for that rack")
    with _lock:
        st = _state()
        ent = _entry(st, usb)
        ent.setdefault("separate", {})[str(rack)] = s["fingerprint"]
        ent["ask"] = False
        _save_state(st)
    return True


def first_seen(dev):
    """Appelé par inputmap._load quand une carte est SEMÉE sous un nom nouveau : la page Soundcard posera la question
    de la première rencontre si golem.fm connaît des sœurs. Un semis reste un semis — rien n'est deviné ici."""
    usb, _ = identity(dev)
    if not usb:
        return False
    with _lock:
        st = _state()
        _entry(st, usb)["ask"] = True
        _save_state(st)
    return True


def ask_later(dev):
    usb, _ = identity(dev)
    if not usb:
        return
    with _lock:
        st = _state()
        _entry(st, usb)["ask"] = False
        _save_state(st)


# ── une proposition reçue ─────────────────────────────────────────────────────────────────────────────────
def on_job(job):
    """Job `card-setup-offer` {offer_id, from_rack, from_name, offered_at, usb, serial, card, os, fingerprint, setup} :
    gardé ici, RIEN n'est appliqué ; la page Soundcard montre le chip. Ack {status: "shown"}."""
    usb = str(job.get("usb") or "").lower()
    if not usb or not isinstance(job.get("setup"), dict):
        raise RuntimeError("card-setup-offer without usb or setup")
    keep = {k: job.get(k) for k in ("offer_id", "from_rack", "from_name", "offered_at", "usb", "serial", "card", "os",
                                   "fingerprint", "setup")}
    with _lock:
        st = _state()
        ent = _entry(st, usb)
        ent["offers"] = [o for o in ent.get("offers") or [] if str(o.get("from_rack")) != str(keep.get("from_rack"))]
        ent["offers"].append(keep)
        _save_state(st)
    _CACHE.pop(usb, None)
    log.info(f"configuration proposée par {keep.get('from_name') or keep.get('from_rack')} pour la carte {usb}")
    return {"status": "shown"}


def reply(dev, offer_id, status_):
    """La réponse de l'utilisateur à une proposition : « applied » la pose ICI puis le dit à golem.fm, « declined »
    le dit seulement. Un 410 (proposition effacée ou remplacée) retire le chip sans rien appliquer de plus."""
    if status_ not in ("applied", "declined"):
        raise ValueError("status: applied | declined")
    usb, _ = identity(dev)
    st = _state()
    ent = st.get(usb) or {}
    local = next((o for o in ent.get("offers") or [] if str(o.get("offer_id")) == str(offer_id)), None)
    remote = fetch(usb, None) or {}
    off = local or next((o for o in remote.get("offers") or [] if str(o.get("offer_id")) == str(offer_id)), None)
    result = None
    if status_ == "applied":
        if not off:
            raise ValueError("that offer is no longer available")
        result = apply_setup(dev, off.get("setup") or {})
    code, body = _http("POST", f"{EXT}/offers/{offer_id}/reply", {"status": status_})
    if code == 410:
        log.info(f"proposition {offer_id} déjà effacée chez golem.fm — chip retiré")
    elif code not in (200, 0):
        log.warning(f"réponse à la proposition {offer_id} refusée : {code} {body}")
    with _lock:
        st = _state()
        ent = _entry(st, usb)
        ent["offers"] = [o for o in ent.get("offers") or [] if str(o.get("offer_id")) != str(offer_id)]
        ent["ask"] = False
        _save_state(st)
    _CACHE.pop(usb, None)
    return {"ok": True, "status": status_, "golem_fm": code, **({"result": result} if result else {})}
