# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio device preferences for the Windows/macOS REAPER launcher."""
import json
import os
import contextlib
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import config as C


SAMPLE_RATES = (44100, 48000, 88200, 96000, 176400, 192000)
BUFFER_SIZES = (64, 96, 128, 192, 256, 384, 512, 1024, 2048)
DEFAULT_DEVICE = "<default system devices>"
# ⚠ Les messages d'erreur de ce module s'AFFICHENT dans l'app (Settings ▸ Gear ▸ Soundcard, Dashboard) :
# ils sont en anglais, comme toute l'interface (CLAUDE.md, règle 4).
_lock = threading.Lock()
_status = {"phase": "idle", "error": None}
# CE QUE LE PILOTE ASIO ACCEPTE (bridge/asio_probe.py, 2026-10-24) : sondé REAPER FERMÉ, gardé par pilote ; une taille que
# le pilote a remplacée à l'ouverture est retenue aussi. Le reste se grise à l'écran, et la demande est refusée AVANT de
# fermer REAPER, avec les tailles que le pilote offre.
ASIO_BUFFERS = "asio-buffers.json"
_DRIVER_ONLY = tuple(2 ** k for k in range(4, 13))     # 16…4096 : les puissances de 2 qu'un pilote peut offrir en plus
_started = 0.0                  # l'heure de départ du changement en cours (le message « déjà en cours » la dit)


def _read_ini(path):
    # ⚠ WINDOWS (2026-10-05) : pendant que REAPER réécrit reaper.ini, une lecture lève PermissionError.
    # Elle tuait la boucle des cartes (monitors._poll_cards, « Task exception was never retrieved ») :
    # plus d'état de carte jusqu'au redémarrage, et le battement partait sans `cards`. On réessaie
    # le temps d'une écriture, comme winfs.replace le fait pour les nôtres.
    data = b""
    for attempt in range(20):
        try:
            data = path.read_bytes() if path.exists() else b""
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
    # Surrogateescape keeps any legacy bytes intact while new device names can be UTF-8.
    return data.decode("utf-8", errors="surrogateescape")


def _with_mode(value):
    """Sous Core Audio, GetAudioDeviceInfo("MODE") répond ok mais VIDE (REAPER 7.82 macOS-arm64, vu le
    2026-11-04) : tout le code qui teste MODE == "coreaudio" voyait la carte absente alors que REAPER
    jouait. Le nom du périphérique, lui, porte le préfixe « CoreAudio » : il fait foi."""
    if isinstance(value, dict) and sys.platform == "darwin" and not str(value.get("MODE") or "").strip():
        idents = (str(value.get("IDENT_IN") or ""), str(value.get("IDENT_OUT") or ""))
        if any(i.startswith("CoreAudio ") and i[len("CoreAudio "):].strip() for i in idents):
            value["MODE"] = "CoreAudio"
    return value


def _actual(since=0):
    path = Path(C.runtime_file("desktop-audio.json"))
    try:
        modified = path.stat().st_mtime
        if modified >= since and time.time() - modified < 6:
            # Le script Lua réécrit le fichier en place : une lecture peut tomber entre
            # l'ouverture et la fin du JSON. Relire brièvement évite un faux « — ».
            for _ in range(3):
                try:
                    return _with_mode(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    time.sleep(0.02)
    except OSError:
        pass
    return None


def _public_actual():
    value = _actual()
    return {key: value[key] for key in ("MODE", "IDENT_IN", "IDENT_OUT", "BSIZE", "SRATE",
                                       "INPUT_COUNT", "OUTPUT_COUNT", "INPUT_NAMES", "OUTPUT_NAMES",
                                       "INPUT_LATENCY_SAMPLES", "OUTPUT_LATENCY_SAMPLES",
                                       "AUDIO_XRUN_TIME", "MEDIA_XRUN_TIME", "XRUN_CLOCK")
            if key in value} if value else None


def latency_ms(actual=None):
    """Latence entrée + sortie rapportée par REAPER, ou estimation nominale si indisponible."""
    actual = _public_actual() if actual is None else actual
    try:
        rate = int(actual["SRATE"])
        incoming = int(actual["INPUT_LATENCY_SAMPLES"])
        outgoing = int(actual["OUTPUT_LATENCY_SAMPLES"])
        if rate > 0 and incoming >= 0 and outgoing >= 0 and incoming + outgoing > 0:
            return round(1000 * (incoming + outgoing) / rate, 1), "reaper"
    except (KeyError, TypeError, ValueError):
        pass
    return nominal_latency_ms(actual), "nominal"


def driver_override(actual=None):
    """Le PILOTE impose-t-il son propre buffer ? (2026-10-18, un testeur Windows : Focusrite, buffer 192 demandé,
    40 ms déclarés.) Beaucoup de pilotes ASIO prennent la taille de bloc demandée par REAPER pour une suggestion :
    le vrai réglage vit dans LEUR panneau. Signe : la latence que le pilote déclare dépasse largement deux blocs
    au buffer ouvert. Rend {reported_ms, expected_ms, driver} ou None (rien à dire, ou rien de mesuré)."""
    if sys.platform == "darwin":
        # Core Audio n'a pas de panneau de pilote qui garde la main : la latence déclarée en plus des blocs est
        # celle du périphérique (marges de sécurité, convertisseurs). Le micro et les haut-parleurs d'un
        # MacBook Air déclarent 1809 + 1620 échantillons à 256 (71 ms, 2026-11-04) — et l'écran conseillait
        # « Focusrite Control / ASIO Configuration », deux choses qui n'existent pas sur un Mac.
        return None
    actual = _public_actual() if actual is None else actual
    lat, src = latency_ms(actual) if actual else (None, None)
    nominal = nominal_latency_ms(actual) if actual else None
    if src != "reaper" or not lat or not nominal:
        return None
    # une marge : un pilote honnête ajoute ses convertisseurs et un bloc de sécurité (quelques ms) — on ne parle
    # qu'au-delà du double ET de 8 ms de plus, pour ne pas crier au loup
    if lat <= max(2 * nominal, nominal + 8):
        return None
    return {"reported_ms": lat, "expected_ms": nominal,
            "driver": str((actual or {}).get("IDENT_IN") or "").removeprefix("ASIO ")[:80] or None}


def nominal_latency_ms(actual=None):
    """Deux blocs audio au taux ouvert par REAPER ; estimation, pas une mesure aller-retour."""
    actual = _public_actual() if actual is None else actual
    try:
        return round(2000 * int(actual["BSIZE"]) / int(actual["SRATE"]), 1)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _snapshot_reaper(save_target=None):
    from provision import desktop
    output = Path(C.runtime_file("desktop-audio-snapshot.json"))
    request = Path(C.runtime_file("desktop-audio-save-path.txt"))
    signal = Path(C.runtime_file("desktop-audio-snapshot-request.txt"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    request.unlink(missing_ok=True)
    signal.unlink(missing_ok=True)
    if save_target is not None:
        request.write_text(str(save_target) + "\n", encoding="utf-8")
    script = desktop.ROOT / "reaper" / "Scripts" / "golem_audio_snapshot.lua"
    process = None
    completed = False
    try:
        if sys.platform in ("win32", "darwin"):
            # Le CLI -nonewinst peut créer une seconde instance vide sur Windows ; sur macOS, `open`
            # ne transmet pas d'arguments à une app déjà ouverte. Le script déjà chargé dans le vrai
            # moteur (golem_desktop_audio.lua, lancé par __startup sur les deux OS) traite cette
            # demande : un seul chemin, celui mesuré sous Windows (docs/platforms.md, M2).
            signal.write_text("snapshot\n", encoding="ascii")
        else:
            process = desktop.launch_reaper([str(desktop.reaper_binary()), "-nonewinst", str(script)])
        for _ in range(100):
            try:
                snapshot = json.loads(output.read_text(encoding="utf-8"))
                completed = True
                return snapshot
            except (OSError, ValueError):
                time.sleep(0.1)
        raise RuntimeError("Could not read the active project from REAPER")
    finally:
        if process is not None and sys.platform == "win32":
            if process.poll() is not None or not completed:
                desktop.unregister_reaper_pid(process.pid)
            if not completed and process.poll() is None:
                # A failed IPC command may have become a separate REAPER instance.
                # Expose it for recovery; never terminate a process with user data.
                from provision.desktop_window import set_reaper_windows_visible
                set_reaper_windows_visible({process.pid}, True)
        request.unlink(missing_ok=True)
        signal.unlink(missing_ok=True)


def save_project_in_place(wait=1.0):
    """Enregistre le projet OUVERT dans REAPER, là où il est, avant une fermeture polie (WM_CLOSE).

    ⚠ 2026-10-03, trois fois le même soir : chaque rebuild du rig marque le projet modifié, et fermer
    REAPER ouvrait « Save project golem-set.rpp before closing? » DERRIÈRE la coquille — l'arrêt de GoleM
    se suspendait, le changement de buffer répondait « REAPER is still open », la mise à jour du moteur
    abandonnait au bout de 3 min. Le projet est celui de GoleM (sets/, réécrit en jouant). Par l'action
    native « File: Save project » (40026) sur le lien OSC — servie par REAPER même si nos scripts Lua ne
    tournent plus. Seulement un projet qui a un chemin : sinon 40026 ouvrirait « Enregistrer sous »
    (le cas sans chemin, c'est _snapshot_reaper + _auto_save_target qui le traite). Rend le chemin, ou None."""
    from provision import desktop
    actual = _actual() or {}
    if actual and not actual.get("PROJECT"):
        # PROJET SANS CHEMIN (2026-11-04, premier Mac réel) : un golem neuf démarre REAPER sur `-new` (pas encore de
        # sets/golem-set.rpp) ; on ne l'enregistrait pas, et CHAQUE arrêt laissait « Save project? » ouverte —
        # `golem stop` finissait sur « REAPER is still open », trois fois dans la journée. Même chemin que le
        # changement d'audio : l'instantané Lua l'enregistre dans sets/ et le rouvre, propre ; il devient le set.
        target = _auto_save_target()
        try:
            state = _snapshot_reaper(target)
        except Exception:
            return None
        if not (state.get("AUTO_SAVED") and target.is_file()):
            return None
        desktop.remember_project(target)
        return str(target)
    project = actual.get("PROJECT") or str(desktop.desktop_project())
    if not (project and os.path.isfile(project)):
        return None
    from pythonosc.udp_client import SimpleUDPClient
    SimpleUDPClient(C.REAPER_OSC_HOST, C.REAPER_OSC_SEND_PORT).send_message("/action", 40026)
    time.sleep(wait)
    return project


def _auto_save_target():
    from provision import desktop
    folder = desktop.ROOT / "sets"
    folder.mkdir(parents=True, exist_ok=True)
    default = folder / "golem-set.rpp"
    if not default.exists():
        return default
    return folder / f"golem-session-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.rpp"


def _section(raw, name):
    lines = raw.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == f"[{name.lower()}]"), None)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines)) if start is not None else None
    return lines, start, end


def _values(raw, name):
    lines, start, end = _section(raw, name)
    return {line.split("=", 1)[0].strip().lower(): line.split("=", 1)[1].strip()
            for line in lines[start + 1:end] if "=" in line} if start is not None else {}


def _set_values(raw, name, updates):
    lines, start, end = _section(raw, name)
    if start is None:
        lines += [f"[{name}]", *[f"{key}={value}" for key, value in updates.items()]]
    else:
        found = set()
        for i in range(start + 1, end):
            if "=" not in lines[i]:
                continue
            key = lines[i].split("=", 1)[0].strip().lower()
            if key in updates:
                lines[i] = f"{key}={updates[key]}"
                found.add(key)
        lines[end:end] = [f"{key}={value}" for key, value in updates.items() if key not in found]
    newline = "\r\n" if "\r\n" in raw else "\n"
    return newline.join(lines) + newline


def asio_drivers():
    if sys.platform != "win32":
        return []
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ASIO", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except OSError:
        return []


_CA_CACHE = {"at": 0.0, "val": None}
_CA_TTL = 10.0


def coreaudio_devices():
    """Inventaire Core Audio. Caché 10 s : `system_profiler` coûte ~1 s, et Soundcard sonde toutes les
    3 s (settings() est appelé à chaque sondage) — sans cache, un process par sondage."""
    if sys.platform != "darwin":
        return {"inputs": [], "outputs": [], "enumeration_warning": None}
    now = time.monotonic()
    if _CA_CACHE["val"] is not None and now - _CA_CACHE["at"] < _CA_TTL:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _CA_CACHE["val"].items()}
    _CA_CACHE["val"] = _coreaudio_scan()
    _CA_CACHE["at"] = time.monotonic()
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _CA_CACHE["val"].items()}


def _coreaudio_scan():
    try:
        result = subprocess.run(["system_profiler", "-json", "SPAudioDataType"],
                                capture_output=True, text=True, timeout=15, check=True)
        rows = json.loads(result.stdout).get("SPAudioDataType", [])
    except (OSError, subprocess.SubprocessError, ValueError):
        rows = []
    devices = {"inputs": [DEFAULT_DEVICE], "outputs": [DEFAULT_DEVICE],
               "enumeration_warning": None, "details": {}}
    found = []
    def collect(value):
        if isinstance(value, list):
            for part in value:
                collect(part)
        elif isinstance(value, dict):
            if value.get("_name"):
                found.append(value)
            if "_items" in value:
                collect(value["_items"])
    collect(rows)
    directional = any("coreaudio_device_input" in item or "coreaudio_device_output" in item
                      for item in found)
    for item in found:
        name = item.get("_name")
        if not isinstance(name, str) or any(char in name for char in "\n\r="):
            continue
        if (not directional or item.get("coreaudio_device_input")) and name not in devices["inputs"]:
            devices["inputs"].append(name)
        if (not directional or item.get("coreaudio_device_output")) and name not in devices["outputs"]:
            devices["outputs"].append(name)
        # transport et canaux : cards.mac_interfaces y lit les INTERFACES branchées (USB, Thunderbolt…) — sans eux,
        # une carte branchée n'était jamais proposée (seul le périphérique ouvert par REAPER existait, 2026-11-04)
        if "_items" not in item:
            def _count(v):
                try:
                    return int(v or 0)
                except (TypeError, ValueError):
                    return 0
            devices["details"][name] = {
                "transport": str(item.get("coreaudio_device_transport") or "").removeprefix("coreaudio_device_type_"),
                "inputs": _count(item.get("coreaudio_device_input")),
                "outputs": _count(item.get("coreaudio_device_output"))}
    if not found:
        devices["enumeration_warning"] = "No CoreAudio device detected; only the system default devices are available."
    elif not directional:
        devices["enumeration_warning"] = "CoreAudio does not report directions; check input/output availability after applying."
    return devices


def configured_coreaudio_input():
    """Identité configurée, sans inventaire matériel dans le chemin MIDI chaud."""
    raw = _read_ini(Path(C.reaper_resource_dir()) / "reaper.ini")
    return _values(raw, "reaper").get("coreaudioindevnew", DEFAULT_DEVICE)


def settings():
    path = Path(C.reaper_resource_dir()) / "reaper.ini"
    raw = _read_ini(path)
    audio = _values(raw, "audioconfig")
    main = _values(raw, "reaper")
    if sys.platform == "win32":
        drivers = asio_drivers()
        name = audio.get("asio_driver_name", "").strip('"')
        shown, allowed = buffer_choices(name)
        return {"platform": "windows", "drivers": drivers, "driver": name,
                "mode": audio.get("mode"), "input_first": int(audio.get("asio_input0", "0")),
                "input_last": int(audio.get("asio_input1", "1")),
                "output_first": int(audio.get("asio_output0", "0")),
                "output_last": int(audio.get("asio_output1", "1")),
                "sample_rate": int(audio.get("asio_srate", "48000")),
                "sample_rate_use": audio.get("asio_srate_use", "0") == "1",
                "buffer_size": int(audio.get("asio_bsize", "256")),
                "buffer_size_use": audio.get("asio_bsize_use", "0") == "1",
                "sample_rates": SAMPLE_RATES, "buffer_sizes": shown, "buffer_sizes_ok": allowed,
                "actual": _public_actual()}
    devices = coreaudio_devices()
    return {"platform": "macos", **devices,
            "input_device": main.get("coreaudioindevnew", DEFAULT_DEVICE),
            "output_device": main.get("coreaudiooutdevnew", DEFAULT_DEVICE),
            "sample_rate": int(main.get("coreaudiosrate", "48000")),
            "sample_rate_use": main.get("coreaudiosrateuse", "0") == "1",
            "buffer_size": int(main.get("coreaudiobs", "256")),
            "buffer_size_use": main.get("coreaudiobsuse", "0") == "1",
            "sample_rates": SAMPLE_RATES, "buffer_sizes": BUFFER_SIZES, "actual": _public_actual()}


def _asio_cache():
    try:
        with open(C.runtime_file(ASIO_BUFFERS), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _asio_save(d):
    path = C.runtime_file(ASIO_BUFFERS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, path)


def probe_asio(driver):
    """Demande au pilote ses tailles de buffer, dans un processus à part. ⚠ REAPER FERMÉ seulement : beaucoup de
    pilotes ASIO sont mono-client, les ouvrir pendant que REAPER joue peut couper le son. Rend l'info, ou None."""
    if sys.platform != "win32" or not driver:
        return None
    try:
        r = subprocess.run([sys.executable, "-m", "bridge.asio_probe", driver], cwd=C.ROOT, capture_output=True,
                           text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        info = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None
    if not isinstance(info, dict) or info.get("error"):
        from .golog import get
        get("desktop-audio").warning("sonde ASIO « %s » : %s", driver, (info or {}).get("error") if isinstance(info, dict) else info)
        return None
    d = _asio_cache()
    d[driver] = {**{k: v for k, v in (d.get(driver) or {}).items() if k == "refused"},
                 **{k: info[k] for k in ("min", "max", "preferred", "granularity")}, "at": int(time.time())}
    _asio_save(d)
    return info


def probe_asio_if_missing(driver=None):
    """La sonde, une fois par pilote, si REAPER ne tourne pas (le lanceur l'appelle avant de démarrer REAPER)."""
    from provision import desktop
    driver = driver or settings().get("driver")
    if sys.platform != "win32" or not driver or "min" in (_asio_cache().get(driver) or {}) or desktop.reaper_running():
        return None
    return probe_asio(driver)


def _note_refused(driver, size):
    d = _asio_cache()
    entry = d.setdefault(driver, {})
    entry["refused"] = sorted(set(entry.get("refused") or []) | {int(size)})
    _asio_save(d)


def buffer_choices(driver=None):
    """(tailles à montrer, tailles que le pilote accepte | None si on n'en sait rien). Les tailles d'un pilote hors de
    la liste de golem (32, ou 528 pour un pilote à taille fixe) s'ajoutent à la liste montrée."""
    from .asio_probe import sizes
    if sys.platform != "win32":
        return list(BUFFER_SIZES), None
    if driver is None:
        driver = settings().get("driver")
    entry = _asio_cache().get(driver) or {}
    refused = set(entry.get("refused") or [])
    candidates = sorted(set(BUFFER_SIZES) | set(_DRIVER_ONLY) | ({int(entry["preferred"])} if entry.get("preferred") else set()))
    allowed = sizes(entry, candidates)
    if allowed is None:
        return list(BUFFER_SIZES), ([n for n in BUFFER_SIZES if n not in refused] if refused else None)
    allowed = [n for n in allowed if n not in refused]
    shown = sorted(set(BUFFER_SIZES) | {n for n in allowed if 32 <= n <= 2048 or n == entry.get("preferred")})
    return shown, allowed


def validate(body, current):
    rate = body.get("sample_rate")
    size = body.get("buffer_size")
    driver = body.get("driver") if sys.platform == "win32" else None
    shown, allowed = buffer_choices(driver if isinstance(driver, str) else "")
    if type(rate) is not int or rate not in SAMPLE_RATES or type(size) is not int or size not in shown:
        raise ValueError("Invalid sample rate or buffer size")
    if type(body.get("sample_rate_use")) is not bool or type(body.get("buffer_size_use")) is not bool:
        raise ValueError("Invalid sample rate or buffer options")
    if sys.platform == "win32":
        if not isinstance(driver, str) or driver not in current["drivers"]:
            raise ValueError("Choose an installed ASIO driver")
        if body["buffer_size_use"] and allowed is not None and size not in allowed:
            raise ValueError(f"{driver} does not offer {size} samples — it offers "
                             + ", ".join(str(n) for n in allowed) if allowed else f"{driver} does not offer {size} samples")
        updates = {"mode": "3", "asio_driver": str(current["drivers"].index(driver)),
                   "asio_driver_name": f'"{driver}"', "asio_srate": str(rate),
                   "asio_srate_use": str(int(body["sample_rate_use"])),
                   "asio_bsize": str(size), "asio_bsize_use": str(int(body["buffer_size_use"]))}
        for prefix in ("input", "output"):
            first, last = body.get(f"{prefix}_first"), body.get(f"{prefix}_last")
            if type(first) is not int or type(last) is not int or not (0 <= first <= last < 128):
                raise ValueError("Invalid channel range")
            updates[f"asio_{prefix}0"] = str(first)
            updates[f"asio_{prefix}1"] = str(last)
        return "audioconfig", updates
    devices = coreaudio_devices()
    updates = {"coreaudiosrate": str(rate), "coreaudiosrateuse": str(int(body["sample_rate_use"])),
               "coreaudiobs": str(size), "coreaudiobsuse": str(int(body["buffer_size_use"]))}
    for field, choices in (("input_device", "inputs"), ("output_device", "outputs")):
        device = body.get(field)
        if not isinstance(device, str) or device not in devices[choices]:
            raise ValueError("Choose a connected CoreAudio device")
        updates["coreaudioindevnew" if field == "input_device" else "coreaudiooutdevnew"] = device
    return "REAPER", updates


_NATIVE_CACHE = {"at": 0.0, "val": None}


def native_driver_advice(current):
    """Pour la page Audio (Windows) : le pilote NATIF de la carte branchée quand REAPER tourne sur un pilote
    GÉNÉRIQUE (ASIO4ALL…). {native, generic} ou None. Un appel PowerShell (~1 s), caché 30 s — jamais dans
    settings(), que inputmap._card_device() lit sur le chemin chaud."""
    if sys.platform != "win32" or not current.get("driver"):
        return None
    from provision import desktop
    if not desktop.is_generic_asio(current["driver"]):
        return None
    now = time.time()
    if now - _NATIVE_CACHE["at"] > 30:
        _NATIVE_CACHE.update(at=now, val=desktop.native_asio_driver(current.get("drivers") or [], desktop.present_media()))
    native = _NATIVE_CACHE["val"]
    if not native or native[0] == current["driver"]:
        return None
    return {"native": native[0], "generic": current["driver"]}


def apply_ini(section, updates):
    path = Path(C.reaper_resource_dir()) / "reaper.ini"
    if not path.exists():
        raise RuntimeError("reaper.ini is missing; run the golem setup")
    raw = _read_ini(path)
    changed = _set_values(raw, section, updates)
    if changed == raw:
        return
    shutil.copy2(path, path.with_suffix(".ini.golem-audio.bak"))
    tmp = path.with_suffix(".ini.golem-audio.tmp")
    tmp.write_bytes(changed.encode("utf-8", errors="surrogateescape"))
    os.replace(tmp, path)


def _reopen_args(binary, actual):
    from provision import desktop
    project = (actual or {}).get("PROJECT")
    if project and Path(project).is_file():
        return [str(binary), "-nosplash", project]
    if actual is not None:
        return [str(binary), "-nosplash", "-new"]
    default = desktop.desktop_project()
    if default.is_file():
        return [str(binary), "-nosplash", str(default)]
    return [str(binary), "-nosplash", "-new"]


def _verify_actual(section, updates, actual):
    if section == "REAPER":
        if actual.get("MODE", "").replace(" ", "").casefold() != "coreaudio":
            return f"REAPER opened {actual.get('MODE', 'no device')} instead of CoreAudio"
        for key, reported, direction in (("coreaudioindevnew", "IDENT_IN", "input"),
                                         ("coreaudiooutdevnew", "IDENT_OUT", "output")):
            wanted = updates.get(key, DEFAULT_DEVICE)
            opened = actual.get(reported, "")
            # Le périphérique système change de nom : vérifier son ouverture, pas son alias.
            if not opened or (wanted != DEFAULT_DEVICE and wanted.casefold() not in opened.casefold()):
                return f"REAPER opened {direction} {opened or 'no device'} instead of {wanted}"
        fields = (("coreaudiosrate", "coreaudiosrateuse", "SRATE", "sample rate"),
                  ("coreaudiobs", "coreaudiobsuse", "BSIZE", "buffer size"))
    else:
        wanted = updates["asio_driver_name"].strip('"')
        opened = " ".join((actual.get("IDENT_IN", ""), actual.get("IDENT_OUT", "")))
        if actual.get("MODE", "").upper() != "ASIO" or wanted.casefold() not in opened.casefold():
            return f"REAPER opened {opened.strip() or actual.get('MODE', 'no device')} instead of {wanted}"
        for direction, reported in (("input", "INPUT_COUNT"), ("output", "OUTPUT_COUNT")):
            expected = int(updates[f"asio_{direction}1"]) - int(updates[f"asio_{direction}0"]) + 1
            if reported in actual and int(actual[reported]) != expected:
                return f"REAPER opened {actual[reported]} {direction} channels instead of {expected}"
        fields = (("asio_srate", "asio_srate_use", "SRATE", "sample rate"),
                  ("asio_bsize", "asio_bsize_use", "BSIZE", "buffer size"))
    for requested, enabled, reported, label in fields:
        if updates.get(enabled) == "1" and str(actual.get(reported, "")) != updates[requested]:
            got = actual.get(reported, "unknown")
            # LE PILOTE ASIO DÉCIDE (2026-10-24, UA Volt : 192 demandé, 128 ouvert, rien d'autre) : la taille demandée
            # n'est qu'une suggestion pour beaucoup de pilotes — dire OÙ se règle la vraie, pas seulement constater
            if section != "REAPER" and reported == "BSIZE":
                with contextlib.suppress(Exception):
                    _note_refused(wanted, updates[requested])
                return (f"{wanted} kept its own buffer ({got} samples instead of {updates[requested]}). "
                        "Set the buffer in the driver's own panel (REAPER ▸ Preferences ▸ Audio ▸ Device ▸ "
                        "ASIO Configuration, or the card's control app), then restart REAPER from the Reaper tile")
            return f"REAPER opened {label} {got} instead of {updates[requested]}"
    return None


def _reaper_hung():
    """Le thread principal du REAPER de cette session ne traite plus aucun message (Windows)."""
    if sys.platform != "win32":
        return False
    from provision import desktop
    from provision.desktop_window import reaper_hung
    return reaper_hung(desktop._backend_pids())


def _apply_worker(section, updates, was_running, project_state, ensure_running=False, hung=False):
    from provision import desktop
    global _status
    reopen = None
    failure = None
    saved_project = _status.get("saved_project")
    try:
        reopen = _reopen_args(desktop.reaper_binary(), project_state)
        if was_running and hung:
            # figé : rien ne passe plus par son thread principal (ni sauvegarde ni WM_CLOSE)
            from provision.desktop_window import force_close_reaper
            _status = {"phase": "waiting_for_reaper", "error": None, "saved_project": None}
            from .golog import get
            get("desktop-audio").warning("REAPER ne répond plus (thread principal figé) : fermeture forcée "
                                         f"({force_close_reaper(desktop._backend_pids())} process), puis relance")
            for _ in range(20):
                if not desktop.reaper_running():
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("REAPER stopped responding and could not be closed")
        elif was_running:
            # REAPER asks to save a dirty project; never force-kill a REAPER that still answers.
            _status = {"phase": "waiting_for_reaper", "error": None, "saved_project": saved_project}
            save_project_in_place()                     # sinon « Save project…? » bloque la fermeture
            from . import plugin_capture                # un REAPER de banc ne doit pas recevoir le « quit »
            plugin_capture.stop_benches()
            # Windows : WM_CLOSE ; macOS : « quit » par Apple Event (provision/desktop_window.py)
            from provision.desktop_window import request_reaper_close
            if not request_reaper_close(desktop._backend_pids()):
                raise RuntimeError("Could not close this session's REAPER window")
            for _ in range(180):
                if not desktop.reaper_running():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("REAPER is still open; check its save prompt")
        _status = {"phase": "writing", "error": None, "saved_project": saved_project}
        # REAPER est fermé : le seul moment où l'on peut demander au pilote ses tailles sans risquer le son
        if section == "audioconfig":
            with contextlib.suppress(Exception):
                probe_asio_if_missing(updates["asio_driver_name"].strip('"'))
        from . import inputmap
        before = inputmap._card_device()
        apply_ini(section, updates)
        # LE PILOTE CHANGE, PAS LA CARTE : les rôles (voix sur 1, guitare sur 2…) suivent — sinon le musicien
        # retrouvait une carte d'entrées neuve, aux défauts d'usine (vu au passage ASIO4ALL -> natif, 2026-10-10)
        try:
            inputmap.inherit(before, inputmap._card_device())
            from .state import state as _st                  # sinon as_preset/bind_input liaient contre l'ancien
            _st.inputmap = inputmap.current()                # pilote jusqu'au redémarrage (audit 2026-10-10)
        except Exception as exc:
            from .golog import get
            get("desktop-audio").warning("rôles de la carte d'entrées non reportés : %s", exc)
        # REAPER est fermé : c'est LE moment où ses masques MIDI se changent (prises DIN rendues au
        # bridge, claviers liés ouverts — bridge/desktop_midi.py). Un échec ici ne coûte pas le son.
        try:
            from . import desktop_midi
            desktop_midi.apply_reaper_masks(C.reaper_resource_dir())
        except Exception as exc:
            from .golog import get
            get("midi").warning("masques MIDI de REAPER non écrits : %s", exc)
    except Exception as exc:
        failure = str(exc)
    finally:
        # A failed write must not leave the live rig shut down.
        if (was_running or (ensure_running and failure is None)) and reopen is not None:
            try:
                if not desktop.reaper_running():
                    with contextlib.suppress(OSError):
                        Path(C.runtime_file("desktop-audio.json")).unlink(missing_ok=True)
                    _status = {"phase": "verifying", "error": None,
                               "saved_project": saved_project}
                    launched_at = time.time()
                    desktop.launch_reaper(reopen)
                    if failure is None:
                        actual = None
                        for _ in range(30):
                            actual = _actual(launched_at)
                            if actual and actual.get("MODE"):
                                break
                            time.sleep(1)
                        if not actual or not actual.get("MODE"):
                            failure = "REAPER did not confirm an open audio device"
                        else:
                            failure = _verify_actual(section, updates, actual)
            except Exception as exc:
                failure = f"{failure + '; ' if failure else ''}Could not restart REAPER: {exc}"
        _status = {"phase": "error" if failure else "done", "error": failure,
                   "saved_project": saved_project}
        _lock.release()


def start_apply(body, *, ensure_running=False):
    global _status, _started
    from provision import desktop
    if not _lock.acquire(blocking=False):
        # DIRE où en est le changement en cours (2026-10-18, un testeur Windows) : « already in progress » seul faisait
        # croire à une panne, alors que REAPER se fermait / se relançait pour le changement précédent
        ph = PHASE_LABEL.get(_status.get("phase"), _status.get("phase") or "working")
        since = int(time.time() - (_started or time.time()))
        raise RuntimeError(f"REAPER is restarting with the previous audio change ({ph}, {since} s) — "
                           "wait for it to finish, then try again")
    try:
        section, updates = validate(body, settings())
        running = desktop.reaper_running()
        # Un REAPER FIGÉ ne répond ni à l'instantané Lua ni à la sauvegarde : « Restart REAPER » refusait
        # alors de le relancer (« Could not read the active project ») — exactement le cas où on en a
        # besoin (2026-10-05). Figé : on ne lui demande rien, il sera terminé puis rouvert sur le
        # dernier projet de GoleM (desktop_project).
        hung = running and _reaper_hung()
        project_state = _snapshot_reaper() if running and not hung else None
        if running and not hung and not (project_state.get("PROJECT") and Path(project_state["PROJECT"]).is_file()):
            target = _auto_save_target()
            project_state = _snapshot_reaper(target)
            if not project_state.get("AUTO_SAVED") or not target.is_file() or Path(project_state.get("PROJECT", "")).resolve() != target.resolve():
                raise RuntimeError("Could not auto-save the REAPER project; no audio setting was changed")
            desktop.remember_project(target)
        saved_project = Path(project_state["PROJECT"]).name if running and not hung and project_state.get("AUTO_SAVED") else None
        _started = time.time()
        _status = {"phase": "starting", "error": None, "saved_project": saved_project}
        threading.Thread(target=_apply_worker,
                         args=(section, updates, running, project_state, ensure_running, hung), daemon=True).start()
    except BaseException:
        _lock.release()
        raise
    return _status


# les étapes d'un changement, dites au musicien (le message « déjà en cours », l'écran)
PHASE_LABEL = {"starting": "starting", "waiting_for_reaper": "waiting for REAPER to close",
               "writing": "writing the settings", "verifying": "reopening REAPER on the new settings"}


def status():
    """Où en est le changement : phase, erreur, et `busy` tant que le verrou est pris."""
    return {**_status, "busy": _lock.locked()}
