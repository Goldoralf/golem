# SPDX-License-Identifier: GPL-3.0-or-later
"""Profils de contrôleurs USB clavier/pads (docs/calibration.md, lot 2 — 2026-07-26).

Un contrôleur MIDI USB (AKAI MPK…) apparaît en classe USB-Audio SANS flux PCM — c'est
l'inverse exact de cards.connected(). Le stepper de calibration construit son PROFIL
(config/controllers/<slug>.json) : plage clavier, table des pads, CC des potards,
capacités vérifiées (arp, sustain, molettes). Le profil est l'objet partageable
(base mutualisée golem.fm, opt-in, plus tard).

Consommateurs actifs : la sauvegarde écrit AUSSI config/knobs.json (bankA/kb_range/
kb_name) — la chaîne existante (golem_knobs, KeyZone) suit sans migration risquée.
Identité stable = VID:PID USB, jamais l'index ALSA.
"""
import glob
import json
import os
import re
import time

from . import config as C
from .golog import swallowed as _swallowed

DIR = os.path.join(C.CONFIG_DIR, "controllers")
KNOBS_JSON = os.path.join(C.CONFIG_DIR, "knobs.json")                  # LOCAL (calibration), hors dépôt
KNOBS_DEFAULT = os.path.join(C.CONFIG_DIR, "knobs.default.json")       # GRAINE suivie


def knobs_config():
    """Banques de CC + plage du clavier : la calibration locale, sinon la graine (2026-10-03 : knobs.json
    est sorti du dépôt — c'est l'état de CE rack, pas une recette)."""
    for p in (KNOBS_JSON, KNOBS_DEFAULT):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return {}


def detected():
    """Contrôleurs MIDI USB branchés : [{index, id, name, usb}] — MIDI présent, PCM absent."""
    out = []
    try:
        txt = open("/proc/asound/cards").read()
    except OSError:
        return out
    for m in re.finditer(r"^\s*(\d+)\s+\[(\w+)\s*\]:\s*(.+?)\n\s+(.*)$", txt, re.M):
        idx, cid, drv, longname = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if "USB-Audio" not in drv:
            continue
        if glob.glob(f"/proc/asound/card{idx}/pcm*"):        # carte SON -> gear-registry, pas ici
            continue
        if not glob.glob(f"/proc/asound/card{idx}/midi*"):
            continue
        usb = ""
        try:
            usb = open(f"/proc/asound/card{idx}/usbid").read().strip()
        except OSError:
            pass
        out.append({"index": idx, "id": cid, "usb": usb,
                    "name": longname.split(" at ")[0].strip()})
    return out


def _slug(usb, name=""):
    base = usb.replace(":", "-") if usb else re.sub(r"[^\w-]", "_", name or "unknown")
    return base


def _path(usb, name=""):
    return os.path.join(DIR, _slug(usb, name) + ".json")


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def load(usb, name=""):
    """Le profil de CE contrôleur. ⚠ 2026-10-03 : un même clavier avait deux profils — sous le VID:PID
    (Linux) et sous son nom (Windows, qui ne connaissait pas le VID:PID). Le profil cherché sous le VID:PID
    ne retombait jamais sur le nom : une calibration faite sous Windows était perdue sous Linux, et
    inversement la plus récente pouvait rester cachée. On lit les deux et on rend la plus RÉCENTE."""
    profs = [prof for _, prof in _profiles_of(usb, name)]
    return max(profs, key=lambda x: str(x.get("calibrated") or "")) if profs else None


def _profiles_of(usb, name):
    """[(chemin, profil)] de CET appareil : la règle du registre (devices._match) — VID:PID égal quand les
    deux en ont un, sinon un nom contenu dans l'autre (« MPK Mini Mk II » / « AKAI MPK Mini Mk II »)."""
    from . import devices
    out = []
    for p in sorted(glob.glob(os.path.join(DIR, "*.json"))):
        prof = _read(p)
        if prof and devices._match({"usb": prof.get("usb"), "name": prof.get("name")}, {"usb": usb, "name": name}):
            out.append((p, prof))
    return out


def save(profile, stamp=True):
    """Persiste le profil (atomique) et propage aux consommateurs actifs (config/knobs.json).
    Champs attendus : usb, name, keys{lo,hi,middle}, pads[notes…], knobs[cc…], caps{…}, channels{keys,pads}.
    `stamp=False` : une mise à jour partielle (les canaux seuls) ne se fait pas passer pour une calibration."""
    profile = dict(profile)
    # une calibration qui n'a pas MESURÉ les canaux (étape Pads sautée) ne les efface pas : sinon le tri de la
    # lane Keys s'arrêtait en silence, et un pad rejouait l'instrument
    if not profile.get("channels"):
        old = load(profile.get("usb") or "", profile.get("name") or "")
        if old and old.get("channels"):
            profile["channels"] = old["channels"]
    if stamp or not profile.get("calibrated"):
        profile["calibrated"] = time.strftime("%Y-%m-%d %H:%M") if stamp else None
    stamp_at = profile.get("calibrated") or time.strftime("%Y-%m-%d %H:%M")
    # un contrôleur calibré EST un appareil connu (2026-09-23) : il n'attend pas un binding pour exister
    try:
        from . import devices
        devs = devices.known()
        if not any(devices._match(e, {"name": profile.get("name"), "usb": profile.get("usb")}) for e in devs.values()):
            devs[profile.get("usb") or devices._slug(profile.get("name"))] = {
                "name": profile.get("name"), "usb": profile.get("usb") or "", "kind": "midi",
                "roles": ["keys", "pads"], "first_seen": stamp_at, "last_seen": stamp_at}
            devices._save(devs)
    except Exception as _e:
        _swallowed(_e)
    os.makedirs(DIR, exist_ok=True)
    p = _path(profile.get("usb", ""), profile.get("name", ""))
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=1, ensure_ascii=False)
    from . import winfs
    winfs.replace(tmp, p)
    _drop_twins(p, profile.get("usb", ""), profile.get("name", ""))
    # une mise à jour partielle (les canaux seuls) ne propage RIEN : knobs.json est l'affaire d'une vraie
    # calibration (mesuré le 2026-10-13 : sinon il naissait d'une simple programmation des pads, kb_name changé)
    return _propagate(profile) if stamp else profile


def _drop_twins(keep, usb, name):
    """Une seule calibration par appareil : les autres fichiers du MÊME appareil (rangés sous le nom par un
    Windows d'avant usb_ids) sont retirés une fois le profil écrit sous sa clé."""
    if not usb:
        return
    for p, _ in _profiles_of(usb, name):
        if os.path.normcase(p) != os.path.normcase(keep):
            try:
                os.remove(p)
            except OSError as e:
                _swallowed(e)


def consolidate(usb, name):
    """Range sous le VID:PID le profil le plus RÉCENT de cet appareil et retire ses doublons. Appelé quand
    le VID:PID d'un contrôleur est connu (listing). Rend le profil, ou None."""
    found = _profiles_of(usb, name)
    if not usb or len(found) < 2 and not any(not prof.get("usb") for _, prof in found):
        return load(usb, name)
    best = dict(max((prof for _, prof in found), key=lambda x: str(x.get("calibrated") or "")), usb=usb)
    p = _path(usb, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(best, f, indent=1, ensure_ascii=False)
    from . import winfs
    winfs.replace(tmp, p)
    _drop_twins(p, usb, name)
    from .golog import get
    get("controllers").info("profil consolidé sous %s (%d fichier(s) pour cet appareil)", os.path.basename(p), len(found))
    return best


def _propagate(profile):
    # propagation : knobs.json = ce que golem_knobs/KeyZone lisent DÉJÀ (pas de nouveau contrat)
    knobs = profile.get("knobs") or []
    keys = profile.get("keys") or {}
    try:
        cur = {k: v for k, v in knobs_config().items() if k != "_comment"}
        if len(knobs) >= 1:
            cur["bankA"] = [int(c) for c in knobs][:8]
        if keys.get("lo") is not None and keys.get("hi") is not None:
            cur["kb_range"] = [int(keys["lo"]), int(keys["hi"])]
        if profile.get("name"):
            cur["kb_name"] = profile["name"]
        cur["_comment"] = ("Écrit par la CALIBRATION (docs/calibration.md) — profil complet dans "
                          f"config/controllers/{_slug(profile.get('usb',''), profile.get('name',''))}.json")
        _wja(KNOBS_JSON, cur, indent=1)
    except OSError:
        pass
    return profile


def listing():
    """Contrôleurs CONNUS ∪ branchés (bridge/devices.py, « connu ≠ branché », 2026-09-23), enrichis de
    leur profil. Un contrôleur calibré puis débranché reste listé, `connected: False` — avant, il
    disparaissait de l'écran avec son profil intact sur le disque (« je repars de zéro »)."""
    from . import devices
    out = []
    for d in devices.listing():
        if "drums" in (d.get("roles") or []) or (d.get("kind") and d["kind"] != "midi"):
            continue                                        # un module de batterie a son onglet ; une carte audio n'est pas un contrôleur
        # VID:PID connu (Linux, ou Windows depuis usb_ids) : un éventuel doublon rangé sous le nom est fusionné
        prof = consolidate(d.get("usb") or "", d.get("name") or "")
        # ce que le rack sait FAIRE de ce modèle (descripteur config/controller-models/) et ses canaux connus
        from . import controller_program as _cp
        m = _cp.model_for(d.get("usb") or "", d.get("name") or "")
        out.append({**d, "id": d.get("key"), "profile": prof, "calibrated": (prof or {}).get("calibrated"),
                    "model": {"id": m["id"], "name": m.get("name"), "can_program": _cp.can_program(m)} if m else None,
                    "channels": (prof or {}).get("channels"), "split": bool(channels_of(prof))})
    return out


# ── LES CANAUX (2026-10-13) : pads et clavier séparés, ou pas ─────────────────────────────────────
# Le profil porte `channels: {keys, pads}` (1-16), MESURÉS par la calibration (note-on des étapes Keys et Pads) ou
# posés par la programmation des pads (bridge/controller_program.py). Le moteur s'en sert pour trier la lane Keys —
# canal des pads -> les pads, canal du clavier -> l'instrument — et SEULEMENT s'ils diffèrent : sur un même canal,
# un tri rendrait les pads muets ou ne séparerait rien. Un contrôleur sans profil garde « tous canaux », comme avant.

def channels_of(profile):
    ch = (profile or {}).get("channels") or {}
    try:
        k, p = int(ch.get("keys") or 0), int(ch.get("pads") or 0)
    except (TypeError, ValueError):
        return None
    return {"keys": k, "pads": p} if 1 <= k <= 16 and 1 <= p <= 16 and k != p else None


def channels_for(midi_in):
    """Les canaux du contrôleur BRANCHÉ que Reaper nomme `midi_in` (« hw:II », ou le port sous Windows), ou None."""
    if not midi_in:
        return None
    from . import devices
    for d in devices.detected():
        if d.get("hw") == midi_in:
            return channels_of(load(d.get("usb") or "", d.get("name") or ""))
    return None


def all_channels():
    """(appareil, clavier, pads) de tous les profils triables — pour la FORME d'un rappel (recall.scene_shape) :
    apprendre ou changer des canaux change le câblage de la lane Keys, donc exige un rebuild."""
    out = []
    for p in sorted(glob.glob(os.path.join(DIR, "*.json"))):
        ch = channels_of(_read(p))
        if ch:
            out.append((os.path.basename(p), ch["keys"], ch["pads"]))
    return tuple(out)


def set_channels(usb, name, keys, pads, pad_notes=None):
    """Met à jour les canaux (et les notes des pads) du profil de CET appareil, sans toucher au reste de sa
    calibration ; crée un profil minimal s'il n'en a pas. Rend le profil."""
    prof = dict(load(usb, name) or {"usb": usb, "name": name})
    prof["channels"] = {"keys": int(keys), "pads": int(pads)}
    if pad_notes:
        prof["pads"] = [int(n) for n in pad_notes]
    if usb:
        prof["usb"] = usb
    return save(prof, stamp=False)


def _wja(path, data, indent=1):
    """tmp + fsync + replace (audit 2026-10-15) — import tardif : store importe ce module."""
    from .store import _write_json_atomic
    _write_json_atomic(path, data, indent=indent)
