# SPDX-License-Identifier: GPL-3.0-or-later
"""Le MIDI du poste Windows/macOS : ce que la page Soundcard appelle « MIDI IN / OUT » et « USB 1-4 ».

Sous Linux, tout se lit dans ALSA : le MIDI de la CARTE SON est la prise DIN (pédalier en entrée,
Whammy en sortie), les AUTRES cartes MIDI sont les prises USB du rack (/proc/asound). Windows n'a rien
de tel : une liste de ports MIDI à plat (WinMM), où l'interface audio, un clavier USB et un pilote
virtuel se ressemblent. D'où deux règles, dites ici une fois :

  · les prises DIN sont CHOISIES (config/midi-ports.json, écran Soundcard ▸ MIDI IN / OUT) — elles
    remplacent GOLEM_FCB_PORT / GOLEM_MIDI_PORT (docs/archive/integration-windows.md, « à refaire »), qui
    restent prioritaires pour qui les a posées ;
  · les prises USB 1-4 sont les AUTRES ports MIDI, dans l'ordre où Windows les donne.

⚠ SOUS WINDOWS UN PORT MIDI NE S'OUVRE QU'UNE FOIS. Si REAPER tient l'entrée du pédalier, le bridge
ne l'ouvre pas (« port MIDI du pédalier indisponible ») ; si REAPER ne tient pas le clavier, la lane
Keys est muette. Les deux se règlent dans les masques de reaper.ini (midiins / midiouts), indexés par
le cache de REAPER (reaper-midihw.ini, [mididevcache] — même piège que sous Linux : l'ordre de première
rencontre, pas l'ordre de Windows). Un masque ne se change pas à chaud (golem_midi.lua, mesuré) : on
l'écrit REAPER FERMÉ — au lancement (provision/desktop.py) et à chaque redémarrage du moteur
(desktop_audio). D'où le « restart » que la page propose après un changement.
"""
import json
import os
import re
import sys
import time

from . import config as C
from .golog import get

log = get("midi")

_CACHE = {"at": 0.0, "val": None}
TTL = 2.0
# ce qui n'est pas un appareil branché : le synthé logiciel de Windows, les ports virtuels
_NOT_A_DEVICE = re.compile(r"wavetable|loopmidi|loopbe|virtual|midi through|midi 2\.0|iac driver", re.I)


def clean(name):
    """Le nom d'un port tel qu'un humain (et REAPER) le connaît : Windows préfixe un doublon
    (« 2- Volt 276 »), et REAPER garde ce préfixe. (L'index que rtmidi ajoute, « Volt 276 1 », est
    retiré dans ports(), où l'on SAIT quel index il porte : « Volt 276 » finit déjà par un nombre.)"""
    return re.sub(r"^\d+-\s*", "", str(name or "").strip()).strip()


def _rtmidi_name(name, index):
    """rtmidi/WinMM rend « <nom> <index> » : on retire CET index-là, rien d'autre."""
    n = str(name or "").strip()
    if sys.platform == "win32" and n.endswith(f" {index}"):
        n = n[: -len(f" {index}")]
    return clean(n)


def same(a, b):
    return bool(a and b) and clean(a).casefold() == clean(b).casefold()


def ports():
    """{"in": [...], "out": [...]} — les noms propres des ports MIDI présents, dans l'ordre de l'OS."""
    now = time.monotonic()
    if _CACHE["val"] is not None and now - _CACHE["at"] < TTL:
        return _CACHE["val"]
    val = {"in": [], "out": []}
    try:
        import rtmidi
        from .midi_api import native_api
        for kind, cls in (("in", rtmidi.MidiIn), ("out", rtmidi.MidiOut)):
            port = cls(native_api(rtmidi))
            for i, nm in enumerate(port.get_ports()):
                n = _rtmidi_name(nm, i)
                if n and n not in val[kind]:
                    val[kind].append(n)
            del port
    except Exception as e:                          # rtmidi absent ou cassé : aucune prise, dit au journal
        log.warning("ports MIDI illisibles : %s", e)
    _CACHE.update(at=now, val=val)
    return val


# ── les prises DIN choisies ───────────────────────────────────────────────────────────────
def _cfg_path():
    return os.path.join(C.CONFIG_DIR, "midi-ports.json")


def _cfg():
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


_ENV = {"in": "GOLEM_FCB_PORT", "out": "GOLEM_MIDI_PORT"}


def din_port(kind):
    """Le port choisi pour la prise DIN `in` (pédalier) ou `out` (Whammy) : la variable d'environnement
    d'abord (l'ancien réglage, gardé pour qui l'a posé), sinon l'écran Soundcard. None = aucun."""
    env = (os.environ.get(_ENV[kind]) or "").strip()
    if env and not env.startswith("hw:"):
        return env
    return _cfg().get(kind) or None


def din_source(kind):
    env = (os.environ.get(_ENV[kind]) or "").strip()
    return "env" if env and not env.startswith("hw:") else ("screen" if _cfg().get(kind) else None)


def set_din_port(kind, name):
    if kind not in ("in", "out"):
        raise ValueError("kind must be in|out")
    d = _cfg()
    if name:
        d[kind] = clean(name)
    else:
        d.pop(kind, None)
    os.makedirs(C.CONFIG_DIR, exist_ok=True)
    from . import store
    store._write_json_atomic(_cfg_path(), d, indent=1)
    return d


def _is_din(name):
    return any(same(name, din_port(k)) or (din_port(k) and din_port(k).casefold() in clean(name).casefold())
               for k in ("in", "out"))


# ── L'IDENTIFIANT USB SOUS WINDOWS (2026-10-03) ──────────────────────────────────────────────
# Linux lit le VID:PID dans /proc/asound ; WinMM ne donne qu'un NOM. Un même clavier avait donc deux
# identités — « 09e8:0045 » sous Linux, « MPK Mini Mk II » sous Windows — et sa calibration deux profils
# (config/controllers/09e8-0045.json et MPK_Mini_Mk_II.json). Le gestionnaire de périphériques, lui,
# connaît l'identifiant : « MPK Mini Mk II » = USB\VID_09E8&PID_0045 (mesuré). On rattache par le NOM
# affiché, le seul lien entre un port WinMM et son appareil. Lent (~1 s) : caché, relu seulement
# quand la liste des ports change.
_USB_IDS = {"key": None, "val": {}}


def _hex_id(v):
    """« 0x09e8 », « 0x09e8  (AKAI professional M.I. Corp.) », 2536 -> « 09e8 » ; None sinon."""
    if isinstance(v, int):
        return f"{v:04x}" if 0 <= v <= 0xFFFF else None
    m = re.match(r"\s*0x([0-9A-Fa-f]{1,4})(?![0-9A-Fa-f])", str(v or ""))
    return m.group(1).lower().zfill(4) if m else None


def parse_system_profiler_usb(data):
    """{nom casefold: "vvvv:pppp"} depuis `system_profiler -json SPUSBDataType SPUSBHostDataType`.
    Tolérant aux deux formes (Apple a déplacé l'USB dans SPUSBHostDataType avec macOS 15, et les noms de
    clés diffèrent) : toute entrée qui porte un `_name` et deux clés « vendor » / « product » d'id."""
    val = {}

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            name = x.get("_name")
            vid = next((_hex_id(v) for k, v in x.items() if "vendor" in k.lower() and "id" in k.lower()), None)
            pid = next((_hex_id(v) for k, v in x.items() if "product" in k.lower() and "id" in k.lower()), None)
            if isinstance(name, str) and name.strip() and vid and pid:
                val.setdefault(clean(name).casefold(), f"{vid}:{pid}")
            for v in x.values():
                if isinstance(v, (list, dict)):
                    walk(v)
    walk(data)
    return val


def _mac_usb_ids():
    import json
    import subprocess
    r = subprocess.run(["system_profiler", "-json", "SPUSBDataType", "SPUSBHostDataType"],
                       capture_output=True, text=True, timeout=20)
    return parse_system_profiler_usb(json.loads(r.stdout or "{}"))


def usb_ids(names=None):
    """{nom casefold: "vvvv:pppp"} des appareils USB présents (Windows, macOS ; {} ailleurs).
    macOS (2026-10-04, M5) : `system_profiler` — même rôle que Get-PnpDevice, même cache."""
    if sys.platform not in ("win32", "darwin"):
        return {}
    key = tuple(sorted(clean(n).casefold() for n in (names or [])))
    if _USB_IDS["key"] == key and key:
        return _USB_IDS["val"]
    if sys.platform == "darwin":
        try:
            val = _mac_usb_ids()
        except Exception as e:
            log.warning("identifiants USB illisibles (system_profiler) : %s", e)
            return _USB_IDS["val"]
        _USB_IDS.update(key=key, val=val)
        return val
    import subprocess
    cmd = ("Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^USB\\\\VID_' } | "
           "ForEach-Object { $_.FriendlyName + \"`t\" + $_.InstanceId }")
    val = {}
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd],
                           capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            name, _, inst = line.partition("\t")
            m = re.match(r"USB\\VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", inst.strip())
            if m and name.strip():
                val.setdefault(clean(name).casefold(), f"{m.group(1)}:{m.group(2)}".lower())
    except Exception as e:
        log.warning("identifiants USB illisibles (Get-PnpDevice) : %s", e)
        return _USB_IDS["val"]
    _USB_IDS.update(key=key, val=val)
    return val


# ── LES PRISES MIDI DE LA CARTE SON NE SONT PAS DES INSTRUMENTS (PC Windows, 2026-11-03) ───────────────────────────
# Sous Linux, _usb_list écarte la carte son ACTIVE (son id ALSA). Sous Windows, ses prises DIN arrivent dans la liste
# WinMM comme n'importe quel clavier : avec le pilote PreSonus, l'AudioBox iTwo publiait « AudioBox iTwo MIDI In » et
# « … MIDI Out », que Controllers et Drums proposaient de calibrer alors que rien n'y était branché (une prise DIN ne
# dit pas ce qu'on y branche). Elles restent dans Soundcard ▸ MIDI IN / OUT (ports()), pas parmi les instruments.
# Le lien pilote ASIO actif → appareil : la DLL du pilote (CLSID → InprocServer32) est SIGNÉE par son fabricant, et le
# port MIDI a pour PARENT un appareil qui porte aussi des sorties audio et dont le pilote vient du même fabricant.
# Un module de batterie USB (lui aussi audio + MIDI) a un autre fabricant de pilote, ou celui de Microsoft : il reste.
# Au moindre doute (pas de pilote choisi, pas de signature, PowerShell muet) on n'écarte RIEN — l'ancien comportement.
# ⚠ Get-PnpDeviceProperty -InstanceId <liste> rend des résultats INCOMPLETS au hasard (mesuré : un parent vide sur deux,
# jamais les mêmes) ; appareil par appareil il est fiable mais coûte ~1 s chacun. GetDeviceProperties par CIM, une
# entité à la fois, est stable (3 × le même inventaire) en ~3 s : c'est lui. Jamais sur la boucle asyncio (card_ports).
_CARD_PORTS = {"key": None, "val": set(), "busy": None}

_CARD_PS = r"""
$dll = $env:GOLEM_ASIO_DLL
$co = ''
try { $co = (Get-AuthenticodeSignature -LiteralPath $dll -ErrorAction Stop).SignerCertificate.Subject } catch {}
$all = @(Get-CimInstance Win32_PnPEntity -Filter "PNPClass='AudioEndpoint' OR PNPClass='SoftwareDevice' OR PNPClass='MidiEndpoint'" -ErrorAction SilentlyContinue)
$want = @($all | Where-Object { $_.PNPClass -eq 'AudioEndpoint' -or $_.DeviceID -match 'MIDI' })
function Prop($ent, $key) {
  $r = Invoke-CimMethod -InputObject $ent -MethodName GetDeviceProperties -Arguments @{ devicePropertyKeys = @($key) } -ErrorAction SilentlyContinue
  if ($r -and $r.deviceProperties) { $r.deviceProperties[0].Data } else { $null }
}
$par = @{}
foreach ($e in $want) { $par[$e.DeviceID] = Prop $e 'DEVPKEY_Device_Parent' }
$prov = @{}
foreach ($u in @($par.Values | Where-Object { $_ } | Sort-Object -Unique)) {
  $pe = Get-CimInstance Win32_PnPEntity -Filter ("DeviceID='" + ($u -replace '\\', '\\' -replace "'", "\'") + "'") -ErrorAction SilentlyContinue
  if ($pe) { $prov[$u] = Prop $pe 'DEVPKEY_Device_DriverProvider' }
}
$audio = @($want | Where-Object PNPClass -eq 'AudioEndpoint' | ForEach-Object { $par[$_.DeviceID] } | Where-Object { $_ })
$midi = @($want | Where-Object PNPClass -ne 'AudioEndpoint' | ForEach-Object {
  $p = $par[$_.DeviceID]; [pscustomobject]@{ name = $_.Name; parent = $p; provider = $(if ($p) { $prov[$p] } else { '' }) } })
@{ signer = $co; audio = $audio; midi = $midi } | ConvertTo-Json -Depth 3 -Compress
"""


def _vendor(s):
    """Le premier mot d'un nom de fabricant : « CN="PreSonus Audio Electronics, Inc.", OU=… » et « PreSonus »."""
    s = re.sub(r'^\s*CN\s*=\s*"?', "", str(s or ""))
    m = re.match(r"\s*([A-Za-z0-9][\w\-]*)", s)
    return m.group(1).casefold() if m else ""


def card_ports_from(inv):
    """{nom casefold} des ports MIDI de la carte son active, depuis l'inventaire de _CARD_PS (pur, testable)."""
    signer = _vendor((inv or {}).get("signer"))
    if not signer or signer == "microsoft":
        return set()
    audio = {a for a in (inv.get("audio") or []) if a}
    out = set()
    for m in inv.get("midi") or []:
        if m.get("parent") in audio and _vendor(m.get("provider")) == signer and m.get("name"):
            out.add(clean(m["name"]).casefold())
    return out


def _asio_dll(driver):
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\ASIO\{driver}", 0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        clsid = winreg.QueryValueEx(k, "CLSID")[0]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\InprocServer32") as k:
        return winreg.QueryValueEx(k, "")[0]


def _card_inventory(driver):
    import json as _json
    import subprocess
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + _CARD_PS],
                       capture_output=True, timeout=60, env={**os.environ, "GOLEM_ASIO_DLL": _asio_dll(driver)},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return _json.loads(r.stdout.decode("utf-8", "replace").strip() or "{}")


def _refresh_card_ports(key, driver):
    try:
        val = card_ports_from(_card_inventory(driver))
        _CARD_PORTS.update(key=key, val=val)
    except Exception as e:                  # rien de mémorisé : le prochain appel réessaie
        log.warning("prises MIDI de la carte son non identifiées : %s", e)
    finally:
        _CARD_PORTS["busy"] = None


def card_ports(names):
    """Les ports MIDI (parmi les présents) qui appartiennent à la carte son ACTIVE — Windows seulement ; set() sinon.
    Lent (~3 s, PowerShell/CIM) : caché, relu quand le pilote choisi ou la liste des ports change. Hors de la boucle
    asyncio (la veille hotplug, les routes synchrones) on attend la réponse ; SUR la boucle on ne bloque jamais — le
    calcul part en fond et la dernière réponse connue sert (leçon du 2026-11-03 : la boucle saturée)."""
    if sys.platform != "win32" or not names:
        return set()
    try:
        from . import desktop_audio
        driver = (desktop_audio.settings().get("driver") or "").strip()
    except Exception:
        return set()
    if not driver:
        return set()
    key = (driver, tuple(sorted(clean(n).casefold() for n in names)))
    if _CARD_PORTS["key"] == key:
        return _CARD_PORTS["val"]
    try:
        import asyncio
        asyncio.get_running_loop()
        on_loop = True
    except RuntimeError:
        on_loop = False
    import threading
    busy = _CARD_PORTS.get("busy")
    if busy is None or not busy.is_alive():
        busy = threading.Thread(target=_refresh_card_ports, args=(key, driver), daemon=True, name="golem-card-ports")
        _CARD_PORTS["busy"] = busy
        busy.start()
    if not on_loop:
        busy.join(timeout=65)
        if _CARD_PORTS["key"] == key:
            return _CARD_PORTS["val"]
    return _CARD_PORTS["val"] if _CARD_PORTS["key"] and _CARD_PORTS["key"][0] == driver else set()


def usb_devices():
    """Les prises USB 1-4 : les appareils MIDI présents qui ne sont ni une prise DIN choisie, ni une prise de la
    carte son active, ni un port logiciel. Un appareil = un nom (entrée et/ou sortie). [{name, kind: "midi", usb}]"""
    p = ports()
    out = []
    names = p["in"] + [o for o in p["out"] if o not in p["in"]]
    card = card_ports([n for n in names if not _NOT_A_DEVICE.search(n)])
    for n in names:
        if _NOT_A_DEVICE.search(n) or _is_din(n) or clean(n).casefold() in card or any(same(n, x["name"]) for x in out):
            continue
        out.append({"name": n, "kind": "midi"})
    ids = usb_ids([x["name"] for x in out]) if out else {}
    for x in out:
        x["usb"] = ids.get(clean(x["name"]).casefold(), "")
    return out


# ── les masques de REAPER (reaper.ini), REAPER FERMÉ ─────────────────────────────────────────
def _device_cache(resource):
    """reaper-midihw.ini [mididevcache] -> {"in": {index: nom}, "out": {index: nom}}."""
    out = {"in": {}, "out": {}}
    try:
        # REAPER macOS écrit les noms en UTF-8 (audit du premier Mac, 2026-11-04) ; un vieux REAPER Windows en ANSI :
        # UTF-8 d'abord, latin-1 sinon — lu en latin-1, « Clé » devenait « ClÃ© » et ne retrouvait plus l'appareil
        with open(os.path.join(resource, "reaper-midihw.ini"), "rb") as f:
            data = f.read()
    except OSError:
        return out
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    sect = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            sect = line.lower()
        elif sect == "[mididevcache]":
            m = re.match(r"^(in|on)(\d+)=(.*)$", line)
            if m:
                out["in" if m.group(1) == "in" else "out"][int(m.group(2))] = m.group(3)
    return out


def wanted_masks(resource, current_in, current_out, keys_names, out_names=None):
    """Les masques que REAPER doit avoir : les prises DIN FERMÉES (elles sont au bridge), les appareils
    liés OUVERTS en ENTRÉE (lanes Keys, pads, drums), et en SORTIE seulement ceux qui en ont l'usage
    (`out_names` : l'horloge MIDI des claviers) — le reste tel que l'utilisateur l'a laissé.
    Rend (midiins, midiouts).

    ⚠ 2026-10-03 : la sortie de l'Alesis Nitro était ouverte comme celle d'un clavier. Après chaque
    démarrage de REAPER le module cessait d'émettre par USB — le module sonnait dans son casque, mais
    plus un message n'arrivait à Windows (lu en direct), alors que le rebranchement le rendait. Une
    batterie n'a pas l'usage d'une sortie : on ne l'ouvre plus, et on la FERME si elle l'était."""
    out_names = keys_names if out_names is None else out_names
    cache = _device_cache(resource)
    want = {"in": current_in, "out": current_out}
    for kind, din, names in (("in", din_port("in"), keys_names), ("out", din_port("out"), out_names)):
        for i, nm in cache[kind].items():
            if din and same(nm, din):
                want[kind] &= ~(1 << i)
            elif any(same(nm, k) for k in names):
                want[kind] |= (1 << i)
            elif kind == "out" and any(same(nm, k) for k in keys_names):
                want[kind] &= ~(1 << i)               # lié, mais sans usage de sortie (une batterie)
    return want["in"], want["out"]


def keys_device_names():
    """Les appareils liés à une lane MIDI (keys, pads, drums) : REAPER doit tenir leur ENTRÉE."""
    from . import devices
    return [e.get("name") for e in devices.known().values() if e.get("name")]


OUT_ROLES = ("keys", "pads")


def out_device_names():
    """Ceux dont REAPER doit tenir la SORTIE : les claviers et pads (l'horloge MIDI de golem_clock)."""
    from . import devices
    return [e.get("name") for e in devices.known().values()
            if e.get("name") and set(e.get("roles") or ["keys", "pads"]) & set(OUT_ROLES)]


def apply_reaper_masks(resource):
    """Écrit midiins / midiouts dans reaper.ini. REAPER DOIT ÊTRE FERMÉ (il réécrit l'ini en quittant).
    Rend True si le fichier a changé."""
    path = os.path.join(resource, "reaper.ini")
    try:
        raw = open(path, "rb").read().decode("latin-1")
    except OSError:
        return False
    def get(key):
        m = re.search(rf"^{key}=(-?\d+)\s*$", raw, re.M)
        return int(m.group(1)) if m else 0
    cur_in, cur_out = get("midiins"), get("midiouts")
    new_in, new_out = wanted_masks(resource, cur_in, cur_out, keys_device_names(), out_device_names())
    if (new_in, new_out) == (cur_in, cur_out):
        return False
    newline = "\r\n" if "\r\n" in raw else "\n"
    for key, val in (("midiins", new_in), ("midiouts", new_out)):
        if re.search(rf"^{key}=", raw, re.M):
            raw = re.sub(rf"^{key}=-?\d+", f"{key}={val}", raw, count=1, flags=re.M)
        else:
            raw = re.sub(r"^\[reaper\]\s*$", lambda m: m.group(0) + newline + f"{key}={val}", raw,
                         count=1, flags=re.M | re.I)
    tmp = path + ".golem-midi.tmp"
    with open(tmp, "wb") as f:
        f.write(raw.encode("latin-1"))
    os.replace(tmp, path)
    log.info("masques MIDI de REAPER : midiins %d -> %d, midiouts %d -> %d", cur_in, new_in, cur_out, new_out)
    return True


def masks_pending(resource):
    """Le reaper.ini courant diffère-t-il de ce que les prises demandent ? (= un redémarrage du moteur
    est nécessaire pour que le changement prenne)"""
    path = os.path.join(resource, "reaper.ini")
    try:
        raw = open(path, "rb").read().decode("latin-1")
    except OSError:
        return False
    def get(key):
        m = re.search(rf"^{key}=(-?\d+)\s*$", raw, re.M)
        return int(m.group(1)) if m else 0
    cur = (get("midiins"), get("midiouts"))
    return wanted_masks(resource, *cur, keys_device_names(), out_device_names()) != cur
