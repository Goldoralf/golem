# SPDX-License-Identifier: GPL-3.0-or-later
"""Input map — le branchement d'entrées/sorties PAR CARTE (docs/input-map.md).

Renommé depuis « patch » (2026-07-31) : le mot est repris par le PATCH-son du musicien
(docs/patches.md) ; ici on ne décrit que du câblage. Chaque carte connue a son fichier
config/inputmaps/<carte>.json : « port physique →
instrument (rôle) ». On change de carte → GoleM charge SON patch. Première
détection → seed de défauts sensés (Volt : IN1 guitare, IN2 voix). Le label
affiché DÉCOULE de l'instrument choisi (saisie par icônes, pas de texte —
kiosk sans clavier). Le rôle du contrat = l'id de l'instrument.

Le MIDI (lane Keys) n'est PAS stocké ici : son rôle vient du binding USB
existant (config/soundcard.json, rôles keys/pads) — une seule source de vérité.
"""
import json
import os
import re
import sys

from . import config as C
from .golog import swallowed as _swallowed

INPUTMAPS_DIR = os.path.join(C.CONFIG_DIR, "inputmaps")
_LEGACY_DIR = os.path.join(C.CONFIG_DIR, "patches")          # emplacement d'avant le renommage


def _migrate():
    """Idempotent, au chargement du module : un rack mis à jour retrouve ses fichiers.
    Ancien dossier seul -> renommé ; les deux -> on complète sans écraser (le nouveau gagne)."""
    if os.path.isdir(_LEGACY_DIR):
        if not os.path.isdir(INPUTMAPS_DIR):
            os.rename(_LEGACY_DIR, INPUTMAPS_DIR)
        else:
            for fn in os.listdir(_LEGACY_DIR):
                dst = os.path.join(INPUTMAPS_DIR, fn)
                if fn.endswith(".json") and not os.path.exists(dst):
                    os.rename(os.path.join(_LEGACY_DIR, fn), dst)


_migrate()

# instruments assignables à une ENTRÉE (saisie par icône — id = rôle stable du contrat)
INSTRUMENTS = [
    {"id": "guitar",    "name": "Guitar",      "icon": "🎸"},
    {"id": "bass",      "name": "Bass",        "icon": "🎸"},
    {"id": "voice",     "name": "Voice",       "icon": "🎤"},
    {"id": "keys",      "name": "Keys",        "icon": "🎹"},
    {"id": "drums",     "name": "Drums",       "icon": "🥁"},
    {"id": "pads",      "name": "Pads",        "icon": "▦"},
    {"id": "keys-pads", "name": "Keys + Pads", "icon": "🎹"},
    {"id": "line",      "name": "Line",        "icon": "〜"},
    {"id": "none",      "name": "Unassigned",  "icon": "·"},
]
# destinations assignables à une SORTIE (paire)
OUT_ROLES = [
    {"id": "monitors", "name": "Monitors", "icon": "🔊"},
    {"id": "pa",       "name": "PA",       "icon": "📢"},
    {"id": "amp",      "name": "Amp",      "icon": "🔌"},
    {"id": "click",    "name": "Click",    "icon": "◔"},   # sortie dédiée métronome (retour batteur 8×8)
    # les RETOURS (docs/returns.md, R1 2026-09-26) : une sortie peut porter une PERSONNE et un type —
    # « la personne est une propriété de l'entrée » (devices-people §8.1) s'étend à la sortie
    {"id": "iem",      "name": "In-ear",   "icon": "🎧"},
    {"id": "wedge",    "name": "Wedge",    "icon": "🔈"},
    {"id": "other",    "name": "Other",    "icon": "·"},
]
OUT_TYPES = ("iem", "wedge")
# rôles des ports MIDI DIN (v1) — « none » = kill-switch (câble parasite inoffensif) ;
# « controller » (clavier DIN -> lane Keys) attend du matériel pour être câblé (soon).
MIDI_IN_ROLES = [
    {"id": "fcb",        "name": "Pedalboard (FCB1010)", "icon": "🦶"},
    {"id": "controller", "name": "Controller",           "icon": "🎹", "soon": True},
    {"id": "none",       "name": "None",                 "icon": "·"},
]
MIDI_OUT_ROLES = [
    {"id": "whammy-dt", "name": "Whammy DT", "icon": "Ⓦ"},
    {"id": "none",      "name": "None",      "icon": "·"},
]

_BY_ID = {i["id"]: i for i in INSTRUMENTS}
_OUT_BY_ID = {o["id"]: o for o in OUT_ROLES}
_MIN_BY_ID = {m["id"]: m for m in MIDI_IN_ROLES}
_MOUT_BY_ID = {m["id"]: m for m in MIDI_OUT_ROLES}


def _card_device():
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        if sys.platform == "darwin":
            # « périphériques système par défaut » n'est pas une carte : la carte d'entrées se clé sur le
            # périphérique que REAPER a OUVERT quand on le connaît (audit 2026-10-10, NON VÉRIFIÉ sur Mac)
            name = desktop_audio.configured_coreaudio_input()
            if name == desktop_audio.DEFAULT_DEVICE:
                try:
                    from . import cards
                    name = cards.mac_opened_input() or name
                except Exception:
                    pass
            return "coreaudio:" + name
        settings = desktop_audio.settings()
        return "asio:" + (settings.get("driver") or "unconfigured")
    try:
        with open(os.path.join(C.CONFIG_DIR, "io.json")) as f:
            return (json.load(f).get("device") or "unknown").strip()
    except Exception:
        return "unknown"


def _slug(device):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", device) or "unknown"


def _path(device=None):
    return os.path.join(INPUTMAPS_DIR, _slug(device or _card_device()) + ".json")


def _card_channels(device):
    """Canaux (entrées, sorties) de la carte : le registre config/cards/ d'abord (rempli à
    l'adoption, cards.remember), le probe /proc/asound sinon (carte branchée jamais adoptée).
    Repli (2, 2) — la supposition historique — quand rien ne sait compter (carte absente ET
    inconnue). Audit 2026-08-12 §3 chantier ④."""
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        if sys.platform == "darwin":
            actual = desktop_audio._public_actual() or {}
            if (device == _card_device() and
                    actual.get("MODE", "").replace(" ", "").casefold() == "coreaudio"):
                try:
                    return int(actual["INPUT_COUNT"]), int(actual["OUTPUT_COUNT"])
                except (KeyError, TypeError, ValueError):
                    pass
            return (2, 2)
        settings = desktop_audio.settings()
        if sys.platform == "win32" and device == "asio:" + settings.get("driver", ""):
            actual = settings.get("actual") or {}
            opened = (actual.get("IDENT_IN", "") + " " + actual.get("IDENT_OUT", "")).casefold()
            if settings["driver"] and settings["driver"].casefold() in opened:
                try:
                    return int(actual["INPUT_COUNT"]), int(actual["OUTPUT_COUNT"])
                except (KeyError, TypeError, ValueError):
                    pass
            return (settings["input_last"] - settings["input_first"] + 1,
                    settings["output_last"] - settings["output_first"] + 1)
    cid = device.split(":", 1)[1] if ":" in device else device
    try:
        from . import cards
        d = cards.known(cid) or cards.probe(cid) or {}
        n_in, n_out = int(d.get("inputs") or 0), int(d.get("outputs") or 0)
        if n_in > 0 or n_out > 0:
            return (n_in or 2, n_out or 2)
    except Exception as _e:
        _swallowed(_e)
    return (2, 2)


def _seed(device):
    """Défauts à la première détection d'une carte, DIMENSIONNÉS PAR LE PROBE (le nombre
    réel d'entrées/sorties, plus « 2 supposées »). Rôles : Volt = l'existant formalisé
    (IN1 guitare, IN2 voix) ; carte inconnue = IN1 guitare, le reste unassigned.
    IN1 suit l'instrument choisi à l'installation (first_run.input_role : guitare, basse ou voix) ; une voix en IN1
    libère l'IN2 de la Volt. Sorties par paires : la première = monitors, les suivantes 'other' (contrat §4)."""
    n_in, n_out = _card_channels(device)
    from . import first_run
    in1 = first_run.input_role()
    roles = {"1": in1}
    if ("V276" in device or "volt" in device.casefold()) and in1 != "voice":
        roles["2"] = "voice"
    inputs = [{"ch": str(i), "role": roles.get(str(i), "none")} for i in range(1, n_in + 1)]
    outputs, a = [], 1
    while a <= n_out:
        ch = f"{a}-{a + 1}" if a + 1 <= n_out else str(a)   # canal impair en queue = mono
        outputs.append({"ch": ch, "role": "monitors" if a == 1 else "other"})
        a += 2
    if not outputs:                                          # carte sans playback : paire logique
        outputs = [{"ch": "1-2", "role": "monitors"}]
    return {"card": device, "inputs": inputs, "outputs": outputs,
            "midi_in": "fcb", "midi_out": "whammy-dt"}


def inherit(old_device, new_device):
    """Le PILOTE change (ASIO4ALL -> natif), pas la carte : la carte d'entrées du nouveau pilote reprend les rôles
    de l'ancienne — entrées, sorties, prises MIDI, personnes — si elle n'existe pas encore. Rend True si copié.
    Les canaux que le nouveau pilote révélera en plus sont ajoutés par _load, comme d'habitude."""
    if not old_device or not new_device or old_device == new_device or os.path.isfile(_path(new_device)):
        return False
    try:
        with open(_path(old_device), encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return False
    # DEUX GARDES (audit 2026-10-10) : une AUTRE carte (clés USB connues et différentes : UMC -> Volt) ne lègue
    # rien ; et une carte restée à ses défauts d'usine (`asio:unconfigured`, le « périphérique par défaut » du
    # Mac) non plus — sinon la Volt héritait « guitare seule » et sa voix sur 2 ne naissait jamais.
    try:
        from . import cards
        ou, nu = cards.usb_of(old_device), cards.usb_of(new_device)
        if ou and nu and ou != nu:
            return False
    except Exception:
        pass
    try:
        same_as_seed = [(str(i.get("ch")), i.get("role")) for i in (old.get("inputs") or [])] == \
                       [(str(i.get("ch")), i.get("role")) for i in (_seed(old_device).get("inputs") or [])] \
                       and not any(i.get("person") or i.get("nth") for i in (old.get("inputs") or []))
    except Exception:
        same_as_seed = False
    if same_as_seed:
        return False
    new = json.loads(json.dumps(old))
    new["card"] = new_device
    new["inherited_from"] = old_device
    _save(new)
    return True


def _covered_channels(items):
    covered = set()
    for item in items:
        parts = str(item.get("ch", "")).split("-")
        if len(parts) in (1, 2) and all(part.isdigit() for part in parts):
            covered.update(range(int(parts[0]), int(parts[-1]) + 1))
    return covered


def _load(device=None):
    device = device or _card_device()
    p = _path(device)
    try:
        with open(p) as f:
            result = json.load(f)
        if sys.platform in ("win32", "darwin") and device == _card_device():
            # Le pilote peut ouvrir plus de canaux après que le patch a été créé.
            # Ajouter les prises révélées sans toucher aux rôles déjà affectés.
            n_in, n_out = _card_channels(device)
            existing_in = {str(item.get("ch")) for item in result.get("inputs", [])}
            covered_in = _covered_channels(result.get("inputs", []))
            for ch in range(1, n_in + 1):
                if ch not in covered_in:
                    result.setdefault("inputs", []).append({"ch": str(ch), "role": "none"})
            existing_out = {str(item.get("ch")) for item in result.get("outputs", [])}
            covered_out = _covered_channels(result.get("outputs", []))
            for ch in range(1, n_out + 1, 2):
                free = [n for n in (ch, ch + 1) if n <= n_out and n not in covered_out]
                if free:
                    slot = f"{free[0]}-{free[1]}" if len(free) == 2 else str(free[0])
                    result.setdefault("outputs", []).append({"ch": slot, "role": "other"})
            if ({str(item.get("ch")) for item in result.get("inputs", [])} != existing_in or
                    {str(item.get("ch")) for item in result.get("outputs", [])} != existing_out):
                _save(result)
        return result
    except Exception as _e:
        _swallowed(_e)
    seeded = _seed(device)
    _save(seeded)
    try:                                         # première rencontre : la page Soundcard proposera les sœurs (golem.fm)
        from . import card_setups
        card_setups.first_seen(device)
    except Exception as _e:
        _swallowed(_e)
    return seeded


def _save(imap):
    from . import store
    store._write_json_atomic(_path(imap.get("card")), imap, indent=1)


def _midi_role():
    """Rôle de la lane MIDI dérivé du binding USB existant (soundcard.json)."""
    try:
        from . import devices
        for b in devices.bindings().values():       # les connus BRANCHÉS (2026-09-23)
            if isinstance(b, dict) and b.get("enabled"):
                roles = b.get("roles") or ["keys", "pads"]
                if "drums" in roles:
                    continue                    # un module de batterie n'est pas la lane Keys legacy
                if "keys" in roles and "pads" in roles:
                    return "keys-pads"
                return roles[0] if roles else "keys"
    except Exception as _e:
        _swallowed(_e)
    return None                    # pas de contrôleur lié


# ── PORTS USB = ENTRÉES DU RACK, pas de la carte (2026-09-09, docs/input-map.md §3.3) ──
# Le contrôleur MIDI est branché sur le serveur GoleM, en Home sur la Volt comme en Show sur le
# XR18. Quatre ports fixes, USB 1..4, toujours listés ; un port lié (soundcard.json usb<n>) porte un
# rôle (keys / pads / keys-pads), un numéro dans son rôle (partagé avec les entrées audio : « Keys +
# Pads 1 ») et une personne. Un port sans appareil reste affiché, non cochable.
USB_PORTS = 4
USB_ROLES = ("keys", "pads", "keys-pads", "drums", "none")   # drums : un module de batterie en USB-MIDI (docs/drums-kit.md)


def _is_usb(ch):
    return bool(re.fullmatch(r"usb[1-9]", str(ch or "")))


def _usb_cfg_path():
    return os.path.join(C.CONFIG_DIR, "soundcard.json")


def _usb_cfg():
    """La vue « usbN » — DÉRIVÉE du registre des appareils connus (bridge/devices.py, 2026-09-23) :
    un appareil connu et détecté au rang N. Plus jamais lue dans un fichier par prise."""
    from . import devices
    return devices.bindings()


def _usb_write(cfg):
    from . import store
    store._write_json_atomic(_usb_cfg_path(), cfg, indent=1)


def usb_ports():
    """Les USB_PORTS ports du rack, liés ou non — BRUTS (le numéro et le libellé viennent de current())."""
    cfg, out = _usb_cfg(), []
    for n in range(1, USB_PORTS + 1):
        b = cfg.get(f"usb{n}")
        bound = isinstance(b, dict) and bool(b.get("enabled"))
        roles = (b.get("roles") or ["keys", "pads"]) if bound else []
        role = "keys-pads" if ("keys" in roles and "pads" in roles) else (roles[0] if roles else "none")
        e = {"ch": f"usb{n}", "port": n, "role": role, "bound": bound,
             "device": (b.get("device") if bound else None), "kind": (b.get("kind") if bound else None)}
        if bound and b.get("nth"):
            e["nth"] = b["nth"]
        if bound and b.get("person"):
            e["person"] = b["person"]
        if bound and role == "drums":               # docs/drums-kit.md lot 1 : quel module, et à quel point y croire
            from . import drumkits
            e["kit"] = drumkits.resolve(b)
        out.append(e)
    return out


def _usb_update(ch, role=None, person=..., nth=...):
    """Une mutation d'un port USB va dans le REGISTRE DES APPAREILS (bridge/devices.py), jamais dans le
    patch d'une carte : on modifie l'appareil connu qui est à ce rang. `role: none` = l'oublier (le
    seul geste qui retire un appareil, et il est explicite — décision 2026-09-23)."""
    from . import devices
    m = re.fullmatch(r"usb([1-9])", str(ch))
    port = int(m.group(1)) if m else 0
    if not 1 <= port <= USB_PORTS:
        raise ValueError(f"USB port must be 1..{USB_PORTS}")
    key = devices.key_at(port)
    if role is not None:
        if role not in USB_ROLES:
            raise ValueError(f"a USB port carries keys, pads, keys-pads or drums — not {role}")
        if role == "none":
            if key:
                devices.forget(key)
            return
        roles = ["keys", "pads"] if role == "keys-pads" else [role]
        if key:
            devices.update(key, roles=roles)
        else:
            devices.bind(port, roles=roles)          # lève si rien n'est branché à ce rang
            key = devices.key_at(port)
    if person is not ...:
        if not key:
            raise ValueError(f"USB {port} is not bound — assign an instrument first")
        devices.update(key, person=(str(person) if person else None))
    if nth is not ...:
        if not key:
            raise ValueError(f"USB {port} is not bound — assign an instrument first")
        devices.update(key, nth=nth)

def _people():
    """Roster en cache (docs/identity.md §3) — pour libeller person_name sans re-lire partout."""
    try:
        with open(os.path.join(C.CONFIG_DIR, ".band.json")) as f:
            return {p.get("id"): p.get("name") for p in json.load(f).get("people") or []}
    except Exception:
        return {}


def device_of(card_id=None):
    """Le device d'une carte du registre (« V276 » -> « hw:V276 »), ou la carte active sans argument.
    Sert à éditer le patch d'une carte DÉBRANCHÉE (celle qu'un mode déclare) — 2026-09-09 :
    « configurer les entrées de la carte du groupe dans les modes »."""
    if not card_id:
        return _card_device()
    cid = str(card_id)
    if sys.platform == "win32" and ":" not in cid:
        from . import desktop_audio
        if cid in desktop_audio.asio_drivers():
            return "asio:" + cid
    if sys.platform == "darwin" and ":" not in cid:
        from . import desktop_audio
        devices = desktop_audio.coreaudio_devices()
        if cid in devices["inputs"] or cid in devices["outputs"]:
            return "coreaudio:" + cid
    return cid if ":" in cid else f"hw:{cid}"


NTH_MAX = 10


def with_nth(inputs):
    """Pose `nth` sur chaque entrée : le numéro déclaré (1..10, unique par rôle), sinon le rang de
    l'entrée parmi celles de son rôle. « Guitar 1 » = (guitar, 1) : une clé GÉNÉRIQUE que toute carte
    satisfait — la seule voix de la Volt est « Voice 1 » sans qu'on la nomme (2026-09-09)."""
    taken, out = {}, []
    for e in inputs or []:
        role = e.get("role") or "none"
        n = e.get("nth")
        n = int(n) if isinstance(n, (int, float, str)) and str(n).isdigit() and 1 <= int(n) <= NTH_MAX else None
        if n is not None and n in taken.get(role, set()):
            n = None
        out.append((e, role, n))
        if n is not None:
            taken.setdefault(role, set()).add(n)
    res = []
    for e, role, n in out:
        if n is None and role not in ("none", "other"):
            n = 1
            while n in taken.get(role, set()):
                n += 1
            taken.setdefault(role, set()).add(n)
        res.append({**e, "nth": n} if n is not None else {**e})
    return res


def _enrich(e, table, people=None):
    it = table.get(e.get("role") or "none", table["none" if "none" in table else "other"])
    # `label` = le nom de l'instrument (compat) ; `name` = « Guitar 2 » DÉRIVÉ de (rôle, nth) — plus de
    # nom libre (2026-09-09 : « un numéro de 1 à 10, ça garde quelque chose de simple et générique »)
    role = e.get("role") or "none"
    name = f"{it['name']} {e['nth']}" if e.get("nth") is not None and role not in ("none", "other") else None
    out = {**e, "label": it["name"], "icon": it["icon"], "name": name}
    # la PERSONNE est une propriété de l'ENTRÉE (docs/patches.md §4 bis, Lot 5) : on la libelle
    # depuis le roster ; une personne sortie du groupe garde son id (l'attribution ne casse pas)
    if e.get("person") and people is not None:
        out["person_name"] = people.get(e["person"]) or e["person"]
    return out


def click_out():
    """Canal hardware du MÉTRONOME pour la carte active (chantier Click 2026-07-25) :
    rôle 'click' de l'input map s'il est déclaré (grosse carte : retour batteur), sinon le rôle
    'monitors' (Volt : OUT 1-2, les enceintes — la maison), sinon '1-2'."""
    outs = _load().get("outputs") or []
    for role in ("click", "monitors"):
        e = next((o for o in outs if o.get("role") == role), None)
        if e and e.get("ch"):
            return str(e["ch"])
    return "1-2"


def current(device=None):
    """L'input map de la carte ACTIVE (ou d'une carte donnée), enrichie (label/icône par rôle) —
    diffusée dans le state WS. Le contrôleur MIDI n'est connu que pour la carte active."""
    raw = _load(device)
    mr = _midi_role()                     # le contrôleur est au RACK : même réponse pour toute carte
    ppl = _people()
    audio = list(raw.get("inputs", []))
    # le NUMÉRO dans le rôle couvre audio ET USB (« Keys 1 » en IN 5 audio, « Keys + Pads 1 » en USB 1)
    numbered = with_nth([*audio, *usb_ports()])
    ins, usb = numbered[:len(audio)], numbered[len(audio):]
    return {
        "card": raw.get("card"),
        "inputs": [_enrich(i, _BY_ID, ppl) for i in ins],
        "usb": [_enrich(u, _BY_ID, ppl) for u in usb],
        "outputs": [_enrich(o, _OUT_BY_ID, ppl) for o in raw.get("outputs", [])],
        "midi": _enrich({"role": mr}, _BY_ID) if mr else None,
        "midi_in": _enrich({"role": raw.get("midi_in") or "fcb"}, _MIN_BY_ID),
        "midi_out": _enrich({"role": raw.get("midi_out") or "whammy-dt"}, _MOUT_BY_ID),
        # le port qu'une lane MIDI à `in_sel` nu joue, par rôle (vital.lane_port) — le Designer et le Riff le lisent
        "lane_ports": _lane_ports(),
    }


def _lane_ports():
    try:
        from . import vital
        return {r: vital.lane_port(r) for r in ("keys", "drums")}
    except Exception as e:
        _swallowed(e)
        return {}


# ── chemin CHAUD (un appel par événement MIDI) : cache sur mtime du fichier ──
_din_cache = {"path": None, "mtime": None, "raw": None}


def din_role(kind):
    """Rôle courant d'un port DIN ('midi_in' | 'midi_out') — lecture cachée,
    consommé par foot.feed (entrée) et midi_out.whammy_* (sortie)."""
    p = _path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        mt = None
    if _din_cache["path"] != p or _din_cache["mtime"] != mt:
        _din_cache.update(path=p, mtime=mt, raw=_load())
    dflt = "fcb" if kind == "midi_in" else "whammy-dt"
    return (_din_cache["raw"] or {}).get(kind) or dflt


def set_nth(ch, nth, device=None):
    """Le NUMÉRO d'une entrée dans son rôle (« Guitar 2 » = guitar #2), 1..10, unique par rôle sur la
    carte — ValueError si le numéro est déjà pris par une autre entrée du même rôle. None = automatique."""
    if _is_usb(ch):
        n = int(nth) if nth not in (None, "", 0) else None
        if n is not None and not 1 <= n <= NTH_MAX:
            raise ValueError(f"number must be 1..{NTH_MAX}")
        cur = current(device)
        u = next((x for x in cur["usb"] if x["ch"] == str(ch)), None)
        if n is not None and u and any(x.get("role") == u.get("role") and x.get("nth") == n and x["ch"] != str(ch)
                                       for x in [*cur["inputs"], *cur["usb"]]):
            raise ValueError(f"{u.get('label')} {n} is already taken")
        _usb_update(ch, nth=n)
        return current(device)
    raw = _load(device)
    items = raw.setdefault("inputs", [])
    e = next((x for x in items if str(x.get("ch")) == str(ch)), None)
    if e is None:
        e = {"ch": str(ch), "role": "none"}
        items.append(e)
    if nth in (None, "", 0, "0"):
        e.pop("nth", None)
    else:
        n = int(nth)
        if not 1 <= n <= NTH_MAX:
            raise ValueError(f"number must be 1..{NTH_MAX}")
        for x in items:
            if x is not e and (x.get("role") or "none") == (e.get("role") or "none") and int(x.get("nth") or 0) == n:
                raise ValueError(f"{e.get('role')} {n} is already IN {x.get('ch')}")
        for u in usb_ports():                    # un port USB du même rôle compte aussi (numéro partagé)
            if u.get("role") == (e.get("role") or "none") and int(u.get("nth") or 0) == n:
                raise ValueError(f"{e.get('role')} {n} is already USB {u['port']}")
        e["nth"] = n
    _save(raw)
    return current(device)


def set_role(kind, ch, role, device=None):
    """Assigne un rôle à une entrée ('input') ou une sortie ('output') de l'input map
    de la carte active — ou d'une carte donnée (device). Lève ValueError si invalide."""
    if kind == "input" and _is_usb(ch):
        _usb_update(ch, role=role)
        return current(device)
    raw = _load(device)
    if kind in ("midi_in", "midi_out"):
        table = _MIN_BY_ID if kind == "midi_in" else _MOUT_BY_ID
        it = table.get(role)
        if it is None:
            raise ValueError(f"unknown MIDI role: {role}")
        if it.get("soon"):
            raise ValueError(f"{it['name']}: not wired yet (needs hardware — coming with bloc C)")
        raw[kind] = role
        _save(raw)
        return current(device)
    if kind == "input":
        if role not in _BY_ID:
            raise ValueError(f"unknown instrument: {role}")
        items = raw.setdefault("inputs", [])
    elif kind == "output":
        if role not in _OUT_BY_ID:
            raise ValueError(f"unknown destination: {role}")
        items = raw.setdefault("outputs", [])
    else:
        raise ValueError("kind: input | output | midi_in | midi_out")
    e = next((x for x in items if str(x.get("ch")) == str(ch)), None)
    if e is None:
        e = {"ch": str(ch)}
        items.append(e)
    if (e.get("role") or "none") != role:
        e.pop("nth", None)                       # le numéro appartenait à l'ancien instrument
    e["role"] = role
    _save(raw)
    return current(device)


def set_pair(kind, ch_a, ch_b, linked, device=None):
    """Maillon stéréo (⛓, contrat §5) : lie deux ports adjacents en UN connecteur
    logique 'a-b' (un seul rôle), ou les délie en deux mono. `device` : une carte donnée
    (le job `inputmap-set` écrit la carte du concert sans qu'elle soit active — trouvé au test,
    2026-09-26 : sans lui, la paire du XR18 s'écrivait sur la Volt)."""
    raw = _load(device)
    items = raw.setdefault("inputs" if kind == "input" else "outputs", [])
    a, b, pair = str(ch_a), str(ch_b), f"{ch_a}-{ch_b}"
    if linked:
        kept = [x for x in items if str(x.get("ch")) not in (a, b, pair)]
        role = next((x.get("role") for x in items if str(x.get("ch")) in (a, b)), None) or "line"
        kept.append({"ch": pair, "role": role if kind == "input" else (role if role in _OUT_BY_ID else "monitors")})
        raw["inputs" if kind == "input" else "outputs"] = sorted(kept, key=lambda x: str(x["ch"]))
    else:
        kept = [x for x in items if str(x.get("ch")) != pair]
        kept += [{"ch": a, "role": "none" if kind == "input" else "other"},
                 {"ch": b, "role": "none" if kind == "input" else "other"}]
        raw["inputs" if kind == "input" else "outputs"] = sorted(kept, key=lambda x: str(x["ch"]))
    _save(raw)
    return current(device)


def set_out_person(ch, person, out_type=..., device=None):
    """Un RETOUR (docs/returns.md) : la sortie `ch` (« 3-4 ») est celle de `person` (handle du roster,
    None = retirer) et de type `out_type` (« iem » | « wedge » | None). C'est une DÉCLARATION pour le
    rider et, le jour où le rack tient les sorties (mixer par destination, lot R2), la cible d'un mix."""
    raw = _load(device)
    items = raw.setdefault("outputs", [])
    e = next((x for x in items if str(x.get("ch")) == str(ch)), None)
    if e is None:
        raise ValueError(f"no output {ch} on this card")
    if person:
        e["person"] = str(person)
    else:
        e.pop("person", None)
    if out_type is not ...:
        if out_type in (None, "", "none"):
            e.pop("type", None)
        elif out_type in OUT_TYPES:
            e["type"] = out_type
        else:
            raise ValueError(f"output type: iem | wedge — not {out_type}")
    _save(raw)
    return current(device)


def set_person(ch, person, device=None):
    """Lot 5 (docs/patches.md §4 bis) : la personne s'attribue sur l'ENTRÉE — une sélection
    dans le roster, jamais une authentification (docs/identity.md §4). person=None = retirer."""
    if _is_usb(ch):
        _usb_update(ch, person=person)
        return current(device)
    raw = _load(device)
    items = raw.setdefault("inputs", [])
    e = next((x for x in items if str(x.get("ch")) == str(ch)), None)
    if e is None:
        e = {"ch": str(ch), "role": "none"}
        items.append(e)
    if person:
        e["person"] = str(person)
    else:
        e.pop("person", None)
    _save(raw)
    return current(device)
