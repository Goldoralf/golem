# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto-identification des périphériques MIDI USB à l'insertion (audit 2026-08-12 §3, ⑤).

La découverte était une mosaïque : la carte son avait sa bannière d'adoption, le pédalier
n'était sondé qu'au démarrage du bridge, un contrôleur calibré restait invisible jusqu'au
binding manuel. Ce module apporte la couche « quelque chose vient d'apparaître » :

  · scan()     lit /proc/asound/cards — la MÊME source que cards.py et controllers.py — et
               rend les périphériques USB qui parlent MIDI ;
  · step()     est PUR : le débounce d'insertion (l'USB s'énumère en plusieurs temps) et la
               détection des départs, sans jamais re-signaler un appareil stable ;
  · identify() est PUR : (appareil, contexte) -> verdict — descripteur de pédalier USB,
               carte son, profil calibré (VID:PID d'abord), ou inconnu.

La boucle vit dans monitors._poll_hotplug ; l'état publié voyage dans state.hotplug -> WS
(bannière de la page Soundcard). Doctrine : on DÉTECTE et on PROPOSE — jamais d'action
système sans geste utilisateur (la seule action automatique est la sonde SysEx d'identité,
qui ne fait que POSER UNE QUESTION à l'appareil). La pédale DIN reste hors sujet, doctrine
assumée : le DIN ne s'annonce pas.
"""
import glob
import json
import os
import re
import sys

from . import config as C
from .golog import swallowed as _swallowed

# Un appareil doit rester visible ≥ SETTLE s (deux scans à la cadence de _poll_hotplug) avant
# d'exister : l'USB s'énumère en plusieurs temps, et un nom peut se compléter entre deux
# lectures. Un appareil vu UNE fois puis disparu n'a jamais existé — silence complet.
SETTLE = 2.5
EVENTS_MAX = 8              # événements récents gardés dans state.hotplug (pas un historique)

_RE_CARD = re.compile(r"^\s*(\d+)\s+\[(\w+)\s*\]:\s*(.+?)\n\s+(.*)$", re.M)


# ── énumération (lecture seule, même idiome que cards.connected / controllers.detected) ──

def scan():
    """Périphériques USB qui parlent MIDI : [{index, id, name, usb, pcm}].
    pcm=True -> l'appareil est AUSSI une carte son (Volt avec son DIN, HX Stomp…) : le
    classement en tient compte, la bannière carte son garde son étage (state.cards)."""
    out = []
    if sys.platform in ("win32", "darwin"):
        # WINDOWS (2026-10-03), macOS (2026-10-04) : pas de /proc — les ports MIDI de l'OS, hors prises DIN choisies (elles
        # sont la carte son) et ports logiciels, avec le VID:PID du gestionnaire de périphériques
        from . import desktop_midi
        return [{"index": None, "id": d["name"], "usb": d.get("usb") or "", "name": d["name"], "pcm": False}
                for d in desktop_midi.usb_devices()]
    try:
        txt = open("/proc/asound/cards").read()
    except OSError:
        return out
    for m in _RE_CARD.finditer(txt):
        idx, drv = int(m.group(1)), m.group(3)
        if "USB-Audio" not in drv:
            continue
        if not glob.glob(f"/proc/asound/card{idx}/midi*"):
            continue                       # pas de MIDI : le PCM pur est l'affaire de _poll_cards
        usb = ""
        try:
            usb = open(f"/proc/asound/card{idx}/usbid").read().strip()
        except OSError:
            pass
        out.append({"index": idx, "id": m.group(2), "usb": usb,
                    "name": m.group(4).split(" at ")[0].strip(),
                    "pcm": bool(glob.glob(f"/proc/asound/card{idx}/pcm*"))})
    return out


def context():
    """Le contexte d'identification, relu à chaque tick (petits fichiers ; les descripteurs
    de pédalier sont déjà cachés sur mtime côté pedalboard). Toujours un dict complet —
    un fichier illisible vaut « rien de connu », jamais une exception."""
    profiles = []
    for p in sorted(glob.glob(os.path.join(C.CONFIG_DIR, "controllers", "*.json"))):
        try:
            d = json.load(open(p))
            if isinstance(d, dict):
                profiles.append(d)
        except Exception:
            continue
    bound = set()
    try:
        from . import devices                       # connu = à sa place, branché ou non (2026-09-23)
        for e in devices.known().values():
            if e.get("name"):
                bound.add(str(e["name"]).strip().lower())
        devices.mark_seen()                          # last_seen des connus détectés (throttlé)
    except Exception as _e:
        _swallowed(_e)
    pb_usb, active_pb = [], None
    try:
        from . import pedalboard
        pb_usb = [d for d in pedalboard.devices().values()
                  if (d.get("transport") or {}).get("kind") == "usb"]
        act = pedalboard.active()
        # « déjà lui » = mesuré ET confirmé : un match seulement déclaré mérite encore sa sonde
        if act.get("source") == "measured" and not act.get("stale"):
            active_pb = act.get("id")
    except Exception as _e:
        _swallowed(_e)
    # modules de batterie (docs/calibration.md addendum 2026-09-23) : un module lié en drums est « à sa
    # place » — la bannière le disait « unknown MIDI device — calibrate it » (mesuré, Nitro liée en USB 1)
    drum_names = []
    try:
        from . import drumkits
        for kid, d in drumkits.load_all().items():
            if kid == drumkits.FALLBACK:
                continue
            for pat in (d.get("identity") or {}).get("usb_names") or []:
                drum_names.append((str(pat).strip().lower(), d.get("name") or kid))
    except Exception as _e:
        _swallowed(_e)
    return {"profiles": profiles, "bound": bound, "pb_usb": pb_usb, "active_pb": active_pb,
            "drum_names": drum_names}


# ── identification (PURE : ni fichier, ni horloge — c'est elle que les tests couvrent) ────

def identify(dev, ctx):
    """Verdict pour un appareil scanné : {kind, label, propose, …}. Ordre de priorité :

      1. descripteur de pédalier à transport USB (port_match dans le nom) — AVANT le test
         PCM : un HX Stomp est aussi une carte son, c'est d'abord un pédalier ;
      2. PCM présent -> carte son : l'étage bannière+adoption existe déjà (state.cards) ;
      3. profil calibré (controllers/*.json) — VID:PID d'abord, nom en repli (le VID:PID
         manque sur un profil appris à la main) ;
      4. inconnu — doctrine gear-registry : le probe d'abord, la base en overlay.

    `propose` = l'UI a quelque chose à suggérer (binder, calibrer) ; False quand l'appareil
    est déjà à sa place (contrôleur bindé, pédalier actif confirmé). UI en ANGLAIS."""
    name = (dev.get("name") or "").strip()
    low = name.lower()
    for d in ctx.get("pb_usb") or []:
        pm = ((d.get("transport") or {}).get("port_match") or "").strip().lower()
        if pm and pm in low:
            return {"kind": "pedalboard", "match": d.get("id"),
                    "label": "USB pedalboard — %s" % (d.get("name") or d.get("id")),
                    "propose": d.get("id") != ctx.get("active_pb")}
    if dev.get("pcm"):
        return {"kind": "soundcard", "label": "sound card", "propose": False}
    prof = next((p for p in ctx.get("profiles") or []
                 if p.get("usb") and dev.get("usb") and p["usb"] == dev["usb"]), None)
    if prof is None and low:
        # repli par NOM (audit §3 : « le name d'un profil vit sur la 2e ligne de
        # /proc/asound/cards ») — en containment, les deux côtés abrègent différemment
        prof = next((p for p in ctx.get("profiles") or []
                     if p.get("name") and (str(p["name"]).strip().lower() in low
                                           or low in str(p["name"]).strip().lower())), None)
    if prof is not None:
        # en CONTAINMENT, comme le repli par nom : le binding (soundcard.json) porte le nom court
        # d'ALSA (« MPK Mini Mk II »), le scan à chaud le nom complet (« AKAI MPK Mini Mk II »).
        # En égalité stricte l'AKAI branché ET lié était re-proposé à chaque visite (2026-09-09).
        is_bound = any(b and (b in low or low in b) for b in (ctx.get("bound") or set()))
        return {"kind": "controller", "match": prof.get("usb") or prof.get("name"),
                "label": "known controller — %s" % (prof.get("name") or name),
                "bound": is_bound, "propose": not is_bound}
    is_bound = any(b and (b in low or low in b) for b in (ctx.get("bound") or set()))
    for pat, nm in ctx.get("drum_names") or []:
        if pat and pat in low:                       # un module de batterie connu du registre
            return {"kind": "drums", "match": nm, "label": "drum module — %s" % nm,
                    "bound": is_bound, "propose": not is_bound}
    if is_bound:                                     # lié (drums ou autre) sans profil : à sa place, silence
        return {"kind": "bound", "label": "bound MIDI device", "bound": True, "propose": False}
    return {"kind": "unknown", "label": "unknown MIDI device", "propose": True}


# ── débounce (PUR) ───────────────────────────────────────────────────────────────────────

def key_of(dev):
    """Identité STABLE d'un appareil scanné : le VID:PID d'abord (l'index ALSA change à
    chaque ré-énumération — vécu sur la Volt), l'id ALSA en repli."""
    return dev.get("usb") or dev.get("id") or dev.get("name") or "?"


def new_watch():
    return {"pending": {}, "present": {}}


def step(st, seen, now, settle=SETTLE):
    """Un tick de veille. st = {"pending": {key: t0}, "present": {key: dev}} ; seen = la
    liste scannée ; now = l'horloge (injectée : la fonction reste pure et testable).

    Rend (st', arrivals, departures). Un appareil n'arrive qu'UNE fois par insertion (il
    passe dans `present` et y reste : aucun re-signalement tant qu'il est stable) ; il ne
    re-arrivera qu'après un vrai départ. Un appareil vu puis disparu avant SETTLE n'émet
    rien du tout."""
    seen_by = {key_of(d): d for d in seen}
    pending = dict(st.get("pending") or {})
    present = dict(st.get("present") or {})
    arrivals, departures = [], []
    for k, d in seen_by.items():
        if k in present:
            present[k] = d                 # rafraîchit le nom (il peut se compléter après coup)
        elif k not in pending:
            pending[k] = now
        elif now - pending[k] >= settle:
            pending.pop(k)
            present[k] = d
            arrivals.append(d)
    for k in list(pending):
        if k not in seen_by:
            pending.pop(k)                 # apparu-disparu pendant l'énumération : silence
    for k in list(present):
        if k not in seen_by:
            departures.append(present.pop(k))
    return {"pending": pending, "present": present}, arrivals, departures


def snapshot(present, events, ctx):
    """Ce qui part dans state.hotplug : les appareils présents IDENTIFIÉS + les événements
    récents. Les cartes son pures sont tues ici — leur bannière existe déjà (state.cards)."""
    devs = []
    for d in sorted(present.values(), key=lambda x: (x.get("name") or "", key_of(x))):
        v = identify(d, ctx)
        if v["kind"] == "soundcard":
            continue
        devs.append({"id": d.get("id"), "name": d.get("name"), "usb": d.get("usb"), **v})
    return {"devices": devs, "events": list(events)[-EVENTS_MAX:]}
