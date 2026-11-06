# SPDX-License-Identifier: GPL-3.0-or-later
"""Registre des cartes son (docs/gear-registry.md, É1-É3 — 2026-07-26).

Un fichier par carte RENCONTRÉE dans config/cards/<ID>.json : le descriptor décrit le
MATÉRIEL (canaux, MIDI, identité USB), l'input map config/inputmaps/ décrit l'USAGE (rôles).
Doctrine : sonder d'abord (le probe suffit à fonctionner), enrichir ensuite (labels,
phones, buffer sûr — champs facultatifs, jamais requis).

Identité stable = l'ID ALSA (« V276 », « iTwo »…) + le VID:PID USB. JAMAIS l'index
de carte : il change à chaque ré-énumération (vécu : la Volt est passée carte 3 → 1
dans la nuit du 25 au 26).
"""
import glob
import json
import os
import re
import sys

from . import config as C
from .golog import swallowed as _swallowed

CARDS_DIR = os.path.join(C.CONFIG_DIR, "cards")


# ── probe ALSA (lecture seule, sans dépendance) ──────────────────────────────

def connected():
    """Les cartes USB audio présentes : [{index, id, name}] — les chips internes
    (HDA Intel/NVidia) sont exclus, GoleM ne pilote que des interfaces USB."""
    out = []
    # UN BANC (tools/check-use.py, check-rig-materialize.py, 2026-10-27) : sa carte est VIRTUELLE (audio factice) et les
    # vraies cartes de la machine sont celles du rack d'à côté — le banc ne voit que la sienne, branchée, et ne propose
    # jamais de basculer REAPER sur le matériel du rack.
    bench = os.environ.get("GOLEM_BENCH_CARD")
    if bench:
        return [{"index": -1, "id": bench, "name": "golem bench (virtual card)"}]
    if sys.platform == "win32":
        from . import desktop_audio
        settings = desktop_audio.settings()
        actual = settings.get("actual") or {}
        name = settings.get("driver") or ""
        opened = (actual.get("MODE", "").upper() == "ASIO" and
                  name.casefold() in (actual.get("IDENT_IN", "") + " " +
                                      actual.get("IDENT_OUT", "")).casefold())
        return [{"index": 0, "id": name, "name": name}] if name and opened else []
    if sys.platform == "darwin":
        # macOS (docs/platforms.md, M2) : la carte est le périphérique d'ENTRÉE Core Audio que
        # REAPER a OUVERT — comme le pilote ASIO sous Windows. Sans ça, /proc/asound/cards : aucune carte.
        # PLUS les interfaces branchées (2026-11-04) : comme les cartes USB-Audio sous Linux, elles sont
        # candidates (« Switch to ») — le micro et les haut-parleurs intégrés, Continuity, les périphériques
        # virtuels (Teams, agrégats) ne le sont pas.
        name = mac_opened_input()
        out = [{"index": 0, "id": name, "name": name}] if name else []
        out += [{"index": i + 1, "id": n, "name": n} for i, n in enumerate(mac_interfaces()) if n != name]
        return out
    try:
        txt = open("/proc/asound/cards").read()
    except OSError:
        return out
    for m in re.finditer(r"^\s*(\d+)\s+\[(\w+)\s*\]:\s*(.+?)\n\s+(.*)$", txt, re.M):
        idx, cid, drv, longname = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if "USB-Audio" not in drv:
            continue
        # cartes SON uniquement : un contrôleur MIDI USB (AKAI MPK…) est AUSSI en classe
        # USB-Audio mais SANS flux PCM — jamais une candidate. (Bug vécu 2026-07-26 : la
        # bannière proposait « Switch to » l'AKAI ; adopté = Reaper sur hw:II sans audio,
        # rig muet — récupéré par re-switch iTwo via la bannière inverse.)
        if not glob.glob(f"/proc/asound/card{idx}/pcm*"):
            continue
        out.append({"index": idx, "id": cid, "name": clean_name(longname.split(" at ")[0])})
    return out


def clean_name(name):
    """Le nom lisible d'une carte, tel qu'ALSA le compose : constructeur + produit. Certains firmwares
    mettent le constructeur dans les DEUX chaînes USB, et le longname devient « PreSonus PreSonus
    AudioBox iTwo » (vu sur l'iTwo, 2026-09-24). On ne garde qu'un mot de tête répété."""
    s = " ".join((name or "").split())
    return re.sub(r"^(\S+)( \1)+\b", r"\1", s)


def _stream_channels(idx):
    """(capture, playback) : le MAX de canaux annoncé par les altsets de stream0."""
    try:
        s = open(f"/proc/asound/card{idx}/stream0").read()
    except OSError:
        return 0, 0

    def chans(section):
        m = re.search(section + r":(.*?)(?:\n(?:Playback|Capture):|\Z)", s, re.S)
        if not m:
            return 0
        return max((int(x) for x in re.findall(r"Channels: (\d+)", m.group(1))), default=0)

    return chans("Capture"), chans("Playback")


MAC_INTERFACE_TRANSPORTS = ("usb", "thunderbolt", "firewire", "pci")


def mac_interfaces():
    """Les interfaces audio BRANCHÉES (Core Audio, avec au moins une entrée), par nom — inventaire caché 10 s."""
    from . import desktop_audio
    details = (desktop_audio.coreaudio_devices() or {}).get("details") or {}
    return [n for n, d in details.items()
            if d.get("transport") in MAC_INTERFACE_TRANSPORTS and d.get("inputs", 0) > 0]


def mac_opened_input():
    """Le périphérique d'entrée Core Audio configuré, s'il est OUVERT par REAPER (None sinon). Réglé
    sur « périphériques système par défaut » : le nom que REAPER rapporte (IDENT_IN) en tient lieu."""
    from . import desktop_audio
    actual = desktop_audio._public_actual() or {}
    if actual.get("MODE", "").replace(" ", "").casefold() != "coreaudio":
        return None
    # REAPER préfixe le nom (« CoreAudio Microphone MacBook Air », 2026-11-04) : la carte se clé sur le NOM du
    # périphérique, celui que l'utilisateur choisit — sinon la même carte avait deux clés (et deux patchs d'entrées)
    opened = (actual.get("IDENT_IN") or "").strip().removeprefix("CoreAudio ").strip()
    name = desktop_audio.configured_coreaudio_input()
    if name == desktop_audio.DEFAULT_DEVICE:
        return opened or None
    return name if opened and name.casefold() in opened.casefold() else None


def probe(cid):
    """Descriptor sondé d'une carte CONNECTÉE (par id ALSA). None si absente."""
    entry = next((c for c in connected() if c["id"] == cid), None)
    if entry is None:
        return None
    if sys.platform == "win32":
        from . import desktop_audio
        settings = desktop_audio.settings()
        active = cid == settings.get("driver")
        import time as _t
        return {"id": cid, "usb": "", "name": cid,
                "inputs": settings["input_last"] + 1 if active else 0,
                "outputs": settings["output_last"] + 1 if active else 0,
                "midi": {"in": False, "out": False},
                "seen": _t.strftime("%Y-%m-%d"), "probed": active}
    if sys.platform == "darwin":
        from . import desktop_audio
        actual = desktop_audio._public_actual() or {}
        import time as _t
        try:
            if cid != mac_opened_input():
                raise KeyError(cid)                # une candidate : ce que Core Audio en dit, pas le périphérique ouvert
            n_in, n_out = int(actual["INPUT_COUNT"]), int(actual["OUTPUT_COUNT"])
        except (KeyError, TypeError, ValueError):
            d = ((desktop_audio.coreaudio_devices() or {}).get("details") or {}).get(cid) or {}
            n_in, n_out = int(d.get("inputs") or 0), int(d.get("outputs") or 0)
        return {"id": cid, "usb": "", "name": cid, "inputs": n_in, "outputs": n_out,
                "midi": {"in": False, "out": False},
                "seen": _t.strftime("%Y-%m-%d"), "probed": bool(n_in or n_out)}
    idx = entry["index"]
    cin, cout = _stream_channels(idx)
    usbid = ""
    try:
        usbid = open(f"/proc/asound/card{idx}/usbid").read().strip()
    except OSError:
        pass
    midi = bool(glob.glob(f"/proc/asound/card{idx}/midi*"))
    import time as _t
    return {
        "id": cid, "usb": usbid, "name": entry["name"],
        "inputs": cin, "outputs": cout,
        "midi": {"in": midi, "out": midi},          # ALSA n'expose pas le sens : raffiné à l'usage
        "seen": _t.strftime("%Y-%m-%d"), "probed": True,
    }


# ── registre (config/cards/<ID>.json) ────────────────────────────────────────

def _path(cid):
    return os.path.join(CARDS_DIR, re.sub(r"[^\w-]", "_", cid) + ".json")


def known(cid):
    try:
        return json.load(open(_path(cid)))
    except Exception:
        return None


def usb_of(device):
    """La clé USB (« 2b5a:0023 ») d'une carte nommée dans la clé de N'IMPORTE quel système : `hw:<id>` -> le
    registre (config/cards/<id>.json), `asio:<pilote>` -> le pilote natif connu (provision/desktop.KNOWN_USB_ASIO).
    None si rien ne la relie à un appareil USB (un pilote générique, une carte inconnue)."""
    import re as _re
    d = str(device or "")
    if d.startswith("hw:"):
        cid = d[3:]
        for c in registry():
            if c.get("id") == cid and c.get("usb"):
                return str(c["usb"]).lower()
        return None
    if d.startswith("asio:"):
        try:
            from provision.desktop import KNOWN_USB_ASIO
        except Exception:
            return None
        ident = KNOWN_USB_ASIO.get(d[5:].casefold())
        m = _re.search(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", ident or "")
        return f"{m.group(1).lower()}:{m.group(2).lower()}" if m else None
    if d.startswith("coreaudio:"):
        return _mac_usb_of(d[len("coreaudio:"):])
    return None


# ── macOS : le nom Core Audio ne porte pas la clé USB — system_profiler, si (2026-10-10) ──────────────
# ⚠ NON VÉRIFIÉ SUR UN MAC. Écrit sous Windows, testé sur des sorties FABRIQUÉES : la forme de system_profiler
# change selon la version de macOS (SPUSBDataType avant Sonoma, SPUSBHostDataType après, des noms de champs
# différents). D'où une lecture par la FORME (un champ « vendor…id » et un « product…id » dans le même objet)
# plutôt que par un nom figé. À lancer sur une vraie machine avant de s'y fier : `python -c "from bridge import
# cards; print(cards._mac_usb_devices())"` doit lister la Volt avec 2b5a:0023.
_MAC_USB_CACHE = {"at": 0.0, "val": None}


def _hexid(v):
    """« 0x2b5a », « 0x2b5a  (Universal Audio) » ou l'entier 11098 -> « 2b5a ». Une chaîne sans 0x n'est pas devinée."""
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:04x}" if 0 <= v <= 0xFFFF else None
    m = re.search(r"0x([0-9a-fA-F]{1,4})(?![0-9a-fA-F])", str(v or ""))
    return m.group(1).lower().zfill(4) if m else None


def _walk_usb(node, out):
    if isinstance(node, dict):
        vid = next((v for k, v in node.items() if re.search(r"vendor.?id", k, re.I)), None)
        pid = next((v for k, v in node.items() if re.search(r"product.?id", k, re.I)), None)
        name = node.get("_name") or next((v for k, v in node.items() if re.search(r"product.?name|device.?name", k, re.I)), None)
        if vid and pid and name and _hexid(vid) and _hexid(pid):
            out.append((str(name), f"{_hexid(vid)}:{_hexid(pid)}"))
        for v in node.values():
            _walk_usb(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_usb(v, out)
    return out


def _mac_usb_devices():
    """[(nom, « vvvv:pppp »)] des appareils USB d'un Mac. Caché 60 s (system_profiler coûte ~1 s)."""
    import subprocess
    import time as _t
    if sys.platform != "darwin":
        return []
    if _MAC_USB_CACHE["val"] is not None and _t.time() - _MAC_USB_CACHE["at"] < 60:
        return list(_MAC_USB_CACHE["val"])
    found = []
    for dtype in ("SPUSBDataType", "SPUSBHostDataType"):
        try:
            out = subprocess.run(["system_profiler", dtype, "-json"], capture_output=True, text=True, timeout=15).stdout
            found += _walk_usb(json.loads(out or "{}"), [])
        except Exception as e:
            _swallowed(e, f"system_profiler {dtype}")
    _MAC_USB_CACHE.update(at=_t.time(), val=found)
    return list(found)


def _mac_usb_of(name):
    """La clé USB d'un périphérique Core Audio par son NOM (« Volt 276 » <-> « Volt 276 » ou « Universal Audio Volt
    276 »). Réglé sur « périphériques système par défaut », le nom vient de ce que REAPER a ouvert. Une seule
    correspondance, sinon None : on ne devine pas entre deux appareils."""
    from . import desktop_audio
    if name == desktop_audio.DEFAULT_DEVICE:
        name = mac_opened_input() or ""
    n = str(name or "").strip().casefold()
    if not n:
        return None
    hits = {usb for dev, usb in _mac_usb_devices() if n in dev.casefold() or dev.casefold() in n}
    return hits.pop() if len(hits) == 1 else None


def same_card(a, b):
    """Deux noms pour le MÊME appareil ? `hw:V276` (Linux) et `asio:Universal Audio Volt` (Windows) le sont : la
    clé USB est la passerelle (docs/returns.md, « l'identité d'une carte reste par système »)."""
    if not a or not b:
        return False
    if a == b:
        return True
    ua, ub = usb_of(a), usb_of(b)
    return bool(ua) and ua == ub


def registry():
    out = []
    for p in sorted(glob.glob(os.path.join(CARDS_DIR, "*.json"))):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        if d.get("name"):
            d["name"] = clean_name(d["name"])        # les fiches écrites avant le nettoyage du nom
        out.append(d)
    return out


def declare(cid, name=None, inputs=2, outputs=2):
    """Une carte DÉCLARÉE À LA MAIN, jamais branchée (2026-09-09 : « créer un preset pour jouer en
    répète avec la carte du batteur »). Entre au registre avec `declared: True`, `probed: False` ;
    le jour où elle est branchée, `remember` pose par-dessus ce que le probe mesure."""
    import re as _re
    cid = _re.sub(r"[^A-Za-z0-9_-]+", "-", str(cid or "")).strip("-")[:32]
    if not cid:
        raise ValueError("card id required")
    n_in, n_out = max(1, min(64, int(inputs or 2))), max(0, min(64, int(outputs or 2)))
    old = known(cid) or {}
    if old.get("probed"):
        raise ValueError(f"{cid} is already known (probed) — nothing to declare")
    d = {**old, "id": cid, "name": (name or cid).strip()[:60], "inputs": n_in, "outputs": n_out,
         "midi": old.get("midi") or {"in": False, "out": False}, "declared": True, "probed": False,
         "seen": old.get("seen") or _today()}
    os.makedirs(CARDS_DIR, exist_ok=True)
    _wja(_path(cid), d, indent=1)
    return d


def _today():
    import time
    return time.strftime("%Y-%m-%d")


def _merge_declared(cid, d):
    """Une carte DÉCLARÉE à la main (« XR18 », 18 entrées) que l'on branche pour de vrai s'annonce sous
    son nom ALSA (« X18XR18 ») : sans ceci, deux cartes au registre et le patch préparé sur la mauvaise
    (2026-09-09). Si UNE SEULE carte déclarée a le même nombre d'entrées, elle est fusionnée :
    son patch d'entrées est renommé, les modes qui la déclaraient pointent la carte sondée, son
    descripteur disparaît. Rend l'id fusionné, ou None."""
    cands = [c for c in registry() if c.get("declared") and not c.get("probed")
             and c.get("id") != cid and int(c.get("inputs") or 0) == int(d.get("inputs") or 0)]
    if len(cands) != 1:
        return None
    decl = cands[0]
    from . import inputmap, modes
    src, dst = inputmap._path(f"hw:{decl['id']}"), inputmap._path(f"hw:{cid}")
    if os.path.exists(src) and not os.path.exists(dst):
        os.replace(src, dst)
        try:
            m = json.load(open(dst)); m["card"] = f"hw:{cid}"
            _wja(dst, m, indent=1)
        except Exception as _e:
            _swallowed(_e)
    for p in glob.glob(os.path.join(modes.LOCAL_DIR, "*.json")):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        if m.get("card") == f"hw:{decl['id']}":
            m["card"] = f"hw:{cid}"
            _wja(p, m, indent=1)
    try:
        os.remove(_path(decl["id"]))
    except OSError:
        pass
    d["alias"] = decl.get("name") or decl["id"]
    d["merged_from"] = decl["id"]
    return decl["id"]


def remember(cid):
    """Sonde la carte et l'inscrit au registre. Les champs ENRICHIS d'un descriptor
    existant (labels, phones, buffer_safe…) sont CONSERVÉS — le probe ne rafraîchit
    que ce qu'il sait mesurer."""
    d = probe(cid)
    if d is None:
        return None
    old = known(cid) or {}
    if not old:
        _merge_declared(cid, d)                          # une carte déclarée à la main qui arrive pour de vrai
    merged = {**old, **d}
    for k in ("phones", "labels", "buffer_safe"):
        if k in old:
            merged[k] = old[k]
    os.makedirs(CARDS_DIR, exist_ok=True)
    _wja(_path(cid), merged, indent=1)
    return merged


def midi_out_port(cid):
    """Nom du port MIDI OUT ALSA de la carte (pour io.json.midi_out — la Whammy).
    Convention ALSA : « <nom carte> MIDI 1 » ; vérifié à l'adoption via /proc."""
    entry = next((c for c in connected() if c["id"] == cid), None)
    if entry is None:
        return None
    if not glob.glob(f"/proc/asound/card{entry['index']}/midi*"):
        return None
    return f"{entry['name']} MIDI 1"


# ── LES PÉRIPHÉRIQUES USB PRÉSENTS, hors Linux (2026-10-05) ────────────────────────────────────
# Sous Windows, REAPER ouvre un PILOTE ASIO, pas une carte : la Volt 276 jouait derrière ASIO4ALL et le
# battement la disait « non branchée » (golem.fm : « pas d'interface audio »). Une carte du registre porte
# son identifiant USB (`usb`: "2b5a:0023") : elle est BRANCHÉE si ce périphérique est présent, quel que
# soit le pilote qui l'ouvre. Interrogé au plus une fois par minute (PowerShell coûte ~1 s).
_usb_cache = {"t": 0.0, "ids": set()}


def present_usb_ids():
    """{'vvvv:pppp'} des périphériques USB présents (Windows : PnP ; macOS : system_profiler, `_mac_usb_devices`).
    Linux : ensemble vide (la carte s'y lit dans /proc/asound)."""
    import subprocess, time
    if sys.platform == "darwin":
        return {usb for _name, usb in _mac_usb_devices()}
    if sys.platform != "win32":
        return set()
    if time.time() - _usb_cache["t"] < 60:
        return set(_usb_cache["ids"])
    ids = set()
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB*VID_*' } "
                              "| ForEach-Object { $_.InstanceId }"],
                             capture_output=True, text=True, timeout=20, creationflags=0x08000000).stdout
        for m in re.finditer(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", out):
            ids.add(f"{m.group(1).lower()}:{m.group(2).lower()}")
    except Exception as e:
        _swallowed(e, "énumération USB")
        return set(_usb_cache["ids"])
    _usb_cache.update(t=time.time(), ids=ids)
    return set(ids)


def _wja(path, data, indent=1):
    """tmp + fsync + replace (audit 2026-10-15) — import tardif : store importe ce module."""
    from .store import _write_json_atomic
    _write_json_atomic(path, data, indent=indent)
