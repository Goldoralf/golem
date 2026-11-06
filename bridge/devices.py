# SPDX-License-Identifier: GPL-3.0-or-later
"""Les APPAREILS MIDI CONNUS du rack — « connu ≠ branché » (docs/gear-registry.md, addendum 2026-09-23).

Avant : `config/soundcard.json` liait une PRISE (`usb1`, `usb2`…) à UN appareil. Or « USB n » n'est
pas une prise physique, c'est le RANG de l'appareil dans la liste détectée — brancher la Nitro seule
en fait « USB 1 ». Lier la Nitro sur USB 1 a donc ÉCRASÉ l'AKAI (rôles keys+pads, personne) le
2026-09-23, et un appareil débranché disparaissait de tous les écrans. « ils ont été connectés
au golem, ils ne disparaissent pas. Ils ne sont juste pas actifs. »

Maintenant : `config/devices.json` connaît des APPAREILS, par identité (VID:PID quand ALSA le donne,
sinon le nom), avec leurs rôles, leur personne, leur descripteur de kit, et quand on les a vus. La
prise est une CONSÉQUENCE : `bindings()` rend, pour chaque appareil connu actuellement détecté, une
entrée `usb<rang>` — la forme que tous les lecteurs d'avant attendent (inputmap, vital, hotplug,
routes_system, drumkits.resolve). Débranché = toujours connu, `connected: False`, listé partout avec
sa date. La seule sortie est `forget()`, explicite — jamais parce qu'un autre appareil a pris le rang.

Migration idempotente au premier chargement : `soundcard.json` (usbN) -> appareils connus (identité par
détection si l'appareil est là, sinon `name:<slug>`, ré-identifié par VID:PID dès qu'on le revoit) ;
chaque profil calibré `config/controllers/*.json` devient un appareil connu (keys+pads par défaut : un
appareil calibré A été connecté). L'ancien fichier est renommé `.migrated`, jamais effacé.
"""
import glob
import json
import os
import re
import sys
import time

from . import config as C
from .golog import get

log = get("devices")

MAX_PORTS = 4
_SEEN_THROTTLE = 60.0
_seen_at = 0.0


def _path():
    return os.path.join(C.CONFIG_DIR, "devices.json")


def _legacy_path():
    return os.path.join(C.CONFIG_DIR, "soundcard.json")


def _slug(name):
    return "name:" + (re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-") or "device")


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def _read():
    try:
        with open(_path(), encoding="utf8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("devices"), dict) else {"devices": {}}
    except Exception:
        return None


def _write(doc):
    from . import store
    os.makedirs(C.CONFIG_DIR, exist_ok=True)          # un rack neuf (ou un test) sans config/ encore
    store._write_json_atomic(_path(), doc, indent=1)


def _match(entry, dev):
    """Un appareil connu est-il CET appareil détecté ? VID:PID d'abord ; sinon le nom, en containment
    sans casse (le binding porte « MPK Mini Mk II », ALSA « AKAI MPK Mini Mk II »)."""
    eu, du = (entry.get("usb") or "").lower(), (dev.get("usb") or "").lower()
    if eu and du:
        return eu == du
    en, dn = str(entry.get("name") or "").strip().lower(), str(dev.get("name") or "").strip().lower()
    return bool(en and dn and (en in dn or dn in en))


# ── détection : le même ordre que Soundcard ▸ USB n, enrichi du VID:PID et du hw: ALSA ─────────
def _cards():
    """/proc/asound/cards : [{index, id, name, usb, pcm}] pour les cartes USB (MIDI ou audio)."""
    out = []
    try:
        txt = open("/proc/asound/cards").read()
    except OSError:
        return out
    for m in re.finditer(r"^\s*(\d+)\s+\[(\w+)\s*\]:\s*(.+?)\n\s+(.*)$", txt, re.M):
        idx, cid, drv, longname = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if "USB-Audio" not in drv:
            continue
        usb = ""
        try:
            usb = open(f"/proc/asound/card{idx}/usbid").read().strip()
        except OSError:
            pass
        out.append({"index": idx, "id": cid, "usb": usb, "name": longname.split(" at ")[0].strip(),
                    "short": drv.split(" - ", 1)[1].strip() if " - " in drv else cid,
                    "pcm": bool(glob.glob(f"/proc/asound/card{idx}/pcm*"))})
    return out


DETECT_TTL = 2.0
_det_cache = {"at": 0.0, "val": []}


def _usb_list():
    """Les appareils USB autres que la carte son, dans l'ordre des rangs « USB n » de l'écran Soundcard :
    [{name, kind}] — les cartes MIDI d'abord (ordre des index ALSA = ordre des clients seq du noyau),
    puis les cartes audio USB sans MIDI. Lu dans /proc/asound/cards, en microsecondes : la première
    version passait par routes_system.soundcard() — `aconnect -l` + sondes PCM, 880 ms par appel,
    `inputmap.current()` à 1,3 s, la suite de tests de 21 s à plus de dix minutes (mesuré 2026-09-23).
    routes_system.soundcard() garde SA liste pour l'écran ; les deux suivent le même ordre. Seam de
    test : monkeypatch cette fonction."""
    if sys.platform in ("win32", "darwin"):
        # pas d'ALSA : les ports MIDI de l'OS, hors prises DIN choisies (bridge/desktop_midi.py)
        from . import desktop_midi
        return desktop_midi.usb_devices()
    try:
        alsa = C.alsa_card()
    except Exception:
        alsa = None
    cards = _cards()
    midi = [c for c in cards if c["id"] != alsa and glob.glob(f"/proc/asound/card{c['index']}/midi*")]
    audio = [c for c in cards if c["id"] != alsa and c not in midi]
    return [{"name": c["short"], "kind": "midi"} for c in midi] + [{"name": c["short"], "kind": "audio"} for c in audio]


def detected():
    """Les appareils USB détectés, avec leur rang : [{port, name, kind, usb, hw}]. VID:PID et hw:
    viennent de /proc/asound/cards, par nom. Cache DETECT_TTL s (bindings() est appelé partout)."""
    now = time.monotonic()
    # la clé du cache inclut la fonction de détection elle-même : un test qui la remplace n'hérite pas
    # de la liste d'un autre test (vécu : deux tests à moins de 2 s se voyaient le même rack)
    if _det_cache.get("fn") is _usb_list and now - _det_cache["at"] < DETECT_TTL:
        return list(_det_cache["val"])
    try:
        usb = _usb_list()
    except Exception:
        usb = []
    cards = _cards()
    out = []
    for i, d in enumerate(usb[:MAX_PORTS]):
        nm = str(d.get("name") or "").strip().lower()
        card = next((c for c in cards if c["short"].strip().lower() == nm), None) or \
               next((c for c in cards if c["name"].strip().lower() == nm), None) or \
               next((c for c in cards if nm and (nm in c["name"].lower() or c["name"].lower() in nm)), None)
        # sous Windows/macOS le nom du port EST le nom que REAPER donne à l'entrée (golem_rig, keys_midi_dev)
        hw = ("hw:" + card["id"]) if card else (d.get("name") if sys.platform in ("win32", "darwin") else None)
        # Windows : le VID:PID vient du gestionnaire de périphériques (desktop_midi.usb_ids), pas d'ALSA
        out.append({"port": i + 1, "name": d.get("name"), "kind": d.get("kind"),
                    "usb": (card or {}).get("usb") or d.get("usb") or "", "hw": hw})
    _det_cache.update({"at": now, "val": list(out), "fn": _usb_list})
    return out


# ── le registre ────────────────────────────────────────────────────────────────────────────
def known():
    """{key: entry} — chargé, migré si besoin. entry = {name, usb, kind, roles, person?, nth?, kit?,
    first_seen, last_seen}."""
    doc = _read()
    if doc is None:
        try:
            doc = _migrate()
        except Exception as e:                        # jamais une exception depuis un LECTEUR (recall, compile…)
            log.warning("registre des appareils illisible/inécrivable : %s", e)
            return {}
    return dict(doc.get("devices") or {})


def _migrate():
    """soundcard.json (usbN) + profils calibrés -> devices.json. Idempotent : ne tourne que si
    devices.json n'existe pas ; l'ancien fichier est gardé en `.migrated`."""
    devs = {}
    legacy = {}
    try:
        with open(_legacy_path(), encoding="utf8") as f:
            legacy = json.load(f)
    except Exception:
        legacy = {}
    det = detected() if isinstance(legacy, dict) and legacy else []
    for key, b in sorted((legacy or {}).items()):
        if not (isinstance(b, dict) and b.get("enabled") and b.get("device")):
            continue
        d = next((x for x in det if _match({"name": b["device"]}, x)), None)
        k = (d or {}).get("usb") or _slug(b["device"])
        e = {"name": b["device"], "usb": (d or {}).get("usb") or "", "kind": b.get("kind") or "midi",
             "roles": list(b.get("roles") or ["keys", "pads"]), "first_seen": _now(), "last_seen": _now() if d else None}
        for f in ("person", "nth", "kit"):
            if b.get(f) is not None:
                e[f] = b[f]
        devs[k] = e
    # un profil calibré EST un appareil qui a été connecté : il ne disparaît pas parce qu'il est débranché
    for p in sorted(glob.glob(os.path.join(C.CONFIG_DIR, "controllers", "*.json"))):
        try:
            prof = json.load(open(p, encoding="utf8"))
        except Exception:
            continue
        if not isinstance(prof, dict) or not prof.get("name"):
            continue
        k = prof.get("usb") or _slug(prof["name"])
        if k in devs or any(_match(e, {"name": prof["name"], "usb": prof.get("usb")}) for e in devs.values()):
            continue
        devs[k] = {"name": prof["name"], "usb": prof.get("usb") or "", "kind": "midi", "roles": ["keys", "pads"],
                   "first_seen": prof.get("calibrated") or _now(), "last_seen": prof.get("calibrated")}
    doc = {"_comment": "Appareils MIDI connus du rack — connu ≠ branché (docs/gear-registry.md, 2026-09-23). "
                       "Une entrée par appareil (clé = VID:PID, ou name:<slug>) ; la prise USB n est dérivée de "
                       "la détection, jamais stockée. Seul « Forget » retire une entrée.",
           "devices": devs}
    _write(doc)
    if legacy:
        try:
            os.replace(_legacy_path(), _legacy_path() + ".migrated")
        except OSError:
            pass
    log.info("devices.json créé : %d appareil(s) connus (migration soundcard.json + profils)", len(devs))
    return doc


def _save(devs):
    doc = _read() or {"devices": {}}
    doc["devices"] = devs
    _write(doc)


def bindings():
    """La vue d'AVANT, dérivée : {usbN: {enabled, device, kind, roles, person?, nth?, kit?, key}} pour
    chaque appareil connu actuellement détecté au rang N. Un connu absent n'y figure pas ; un détecté
    inconnu non plus (le lier est un geste : bind())."""
    devs, out = known(), {}
    for d in detected():
        for k, e in devs.items():
            if _match(e, d):
                b = {"enabled": True, "device": e.get("name") or d.get("name"), "kind": e.get("kind") or d.get("kind"),
                     "roles": list(e.get("roles") or ["keys", "pads"]), "key": k}
                for f in ("person", "nth", "kit"):
                    if e.get(f) is not None:
                        b[f] = e[f]
                out[f"usb{d['port']}"] = b
                break
    return out


def mark_seen(force=False):
    """last_seen des connus détectés, VID:PID appris si l'entrée n'en avait pas (ré-identification).
    Throttlé : appelé par la veille hotplug à chaque tick."""
    global _seen_at
    if not force and time.monotonic() - _seen_at < _SEEN_THROTTLE:
        return
    _seen_at = time.monotonic()
    devs, changed = known(), False
    for d in detected():
        for k, e in list(devs.items()):
            if _match(e, d):
                if d.get("usb") and not e.get("usb"):
                    e["usb"] = d["usb"]
                    if k != d["usb"] and d["usb"] not in devs:
                        devs.pop(k); devs[d["usb"]] = e; changed = True
                stamp = time.strftime("%Y-%m-%d %H:%M")
                if e.get("last_seen") != stamp:
                    e["last_seen"] = stamp; changed = True
                if not e.get("name") and d.get("name"):
                    e["name"] = d["name"]; changed = True
                break
    if changed:
        _save(devs)


def listing():
    """Pour les écrans : connus ∪ détectés, chacun avec son état.
    [{key, name, usb, kind, roles, person, nth, kit, known, connected, port, hw, first_seen, last_seen}]"""
    devs, det, out, seen = known(), detected(), [], set()
    for k, e in devs.items():
        d = next((x for x in det if _match(e, x)), None)
        if d:
            seen.add(d["port"])
        out.append({"key": k, "name": e.get("name"), "usb": e.get("usb") or (d or {}).get("usb") or "",
                    "kind": e.get("kind") or (d or {}).get("kind"), "roles": list(e.get("roles") or ["keys", "pads"]),
                    "person": e.get("person"), "nth": e.get("nth"), "kit": e.get("kit"), "known": True,
                    "connected": bool(d), "port": (d or {}).get("port"), "hw": (d or {}).get("hw"),
                    "first_seen": e.get("first_seen"), "last_seen": e.get("last_seen")})
    for d in det:
        if d["port"] in seen:
            continue
        out.append({"key": None, "name": d.get("name"), "usb": d.get("usb") or "", "kind": d.get("kind"),
                    "roles": [], "person": None, "nth": None, "kit": None, "known": False, "connected": True,
                    "port": d["port"], "hw": d.get("hw"), "first_seen": None, "last_seen": None})
    out.sort(key=lambda x: (not x["connected"], x["port"] or 99, (x["name"] or "").lower()))
    return out


def _key_for(dev, devs):
    for k, e in devs.items():
        if _match(e, dev):
            return k
    return dev.get("usb") or _slug(dev.get("name"))


def bind(port, roles=None, kit=..., person=..., nth=...):
    """Lier l'appareil DÉTECTÉ au rang `port` : il devient connu (ou est mis à jour). Rend (key, entry).
    Lève ValueError si rien n'est branché là."""
    d = next((x for x in detected() if x["port"] == int(port)), None)
    if not d:
        raise ValueError(f"nothing plugged on USB {port} — plug the device, then assign it")
    devs = known()
    k = _key_for(d, devs)
    e = dict(devs.get(k) or {"name": d.get("name"), "usb": d.get("usb") or "", "kind": d.get("kind") or "midi",
                              "roles": ["keys", "pads"], "first_seen": _now()})
    e["last_seen"] = _now()
    if d.get("usb") and not e.get("usb"):
        e["usb"] = d["usb"]
    if roles is not None:
        if e.get("roles") and sorted(e["roles"]) != sorted(roles):
            e.pop("nth", None)                   # le numéro appartenait à l'ancien instrument
        e["roles"] = list(roles)
    return _apply(devs, k, e, kit=kit, person=person, nth=nth)


def update(key, roles=None, kit=..., person=..., nth=...):
    """Modifier un appareil CONNU, branché ou non (ses rôles, sa personne, son kit)."""
    devs = known()
    if key not in devs:
        raise KeyError(key)
    e = dict(devs[key])
    if roles is not None:
        if sorted(e.get("roles") or []) != sorted(roles):
            e.pop("nth", None)
        e["roles"] = list(roles)
    return _apply(devs, key, e, kit=kit, person=person, nth=nth)


def _apply(devs, k, e, kit=..., person=..., nth=...):
    if kit is not ...:
        if kit:
            e["kit"] = kit
        else:
            e.pop("kit", None)
    if "drums" not in (e.get("roles") or []):
        e.pop("kit", None)
    if person is not ...:
        if person:
            e["person"] = str(person)
        else:
            e.pop("person", None)
    if nth is not ...:
        if nth is None:
            e.pop("nth", None)
        else:
            e["nth"] = int(nth)
    devs[k] = e
    _save(devs)
    return k, e


def forget(key):
    """La SEULE façon de perdre un appareil : explicite. Rend l'entrée retirée, ou None."""
    devs = known()
    e = devs.pop(key, None)
    if e is not None:
        _save(devs)
        log.info("appareil oublié : %s (%s)", key, e.get("name"))
    return e


def key_at(port):
    """La clé de l'appareil connu au rang `port`, ou None."""
    b = bindings().get(f"usb{int(port)}")
    return (b or {}).get("key")
