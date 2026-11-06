# SPDX-License-Identifier: GPL-3.0-or-later
"""Installation et lancement utilisateur de GoleM sur Windows et macOS.

REAPER et les plugins restent des dépendances natives installées séparément.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
OSC_LINE = 'OSC "golem" 3 8000 "127.0.0.1" 9000 1024 10 "golem"'
# Lancé par un raccourci, le lanceur tourne sous pythonw.exe : SANS console. Chaque programme
# console qu'il appelle (tasklist, powershell, le python du venv) en ouvrirait alors une, visible,
# qui clignote — d'où ce drapeau sur tous ses sous-processus.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def resource_dir():
    from bridge.config import reaper_resource_dir
    return Path(reaper_resource_dir())


# ── le reçu d'installation (docs/uninstall.md §2, §9.2) ──────────────────────────────────────────
# Le setup, les raccourcis et l'autostart notent ce qu'ils posent et l'état d'AVANT, par provision/receipt.py
# chargé par son chemin. Deux règles, celles du bridge (bridge/install_receipt.py) : jamais d'exception (un reçu
# raté ne casse pas l'installation), et SEULEMENT dans un reçu qui existe — l'installateur le crée à l'étape
# « source » ; un setup lancé à la main sur une install d'avant le reçu y mettrait nos propres valeurs, prises
# pour celles d'avant golem.
RECEIPT_BY = "provision/desktop.py"


def _receipt():
    """Le module receipt.py si le reçu EXISTE, sinon None. Windows seulement : macOS suivra (docs/uninstall.md §9)."""
    if sys.platform != "win32":
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", ROOT / "provision" / "receipt.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod if mod.exists() else None
    except Exception:
        return None


def _record(fn, *args, **kwargs):
    """Appelle receipt.<fn>(…) si le reçu existe ; avale toute erreur (dite, jamais fatale)."""
    R = _receipt()
    if R is None:
        return None
    try:
        return getattr(R, fn)(*args, **kwargs)
    except Exception as exc:
        print(f"⚠ install receipt not updated ({exc})", file=sys.stderr)
        return None


def reaper_pids():
    """Les PID de tous les REAPER de la machine (Windows : tasklist ; ailleurs : pgrep -x)."""
    if sys.platform == "win32":
        raw = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, check=True, creationflags=NO_WINDOW).stdout
        out = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "ascii",
                         errors="replace")
        pids = set()
        for line in out.splitlines():
            cells = [c.strip('"') for c in line.split('","')]
            if len(cells) > 1 and cells[0].strip('"').lower() == "reaper.exe" and cells[1].isdigit():
                pids.add(int(cells[1]))
        return pids
    pids = set()
    for name in ("REAPER", "reaper"):
        r = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True)
        pids |= {int(x) for x in r.stdout.split() if x.isdigit()}
    return pids


def bench_reaper_pids():
    """Les REAPER de BANC (capture, recette) inscrits par le bridge (bridge/plugin_capture.py) — ceux qui vivent encore."""
    try:
        from bridge.plugin_capture import bench_pids_file
        return set(json.loads(bench_pids_file().read_text(encoding="utf-8")))
    except Exception:
        return set()


def reaper_running():
    """Ne jamais réécrire reaper.ini pendant que REAPER peut le sauvegarder. Le REAPER PRINCIPAL : un REAPER de banc
    (capture, recette — il a sa propre config) ne compte pas ; il n'empêche ni de démarrer ni de régler l'audio."""
    pids = reaper_pids()
    return bool(pids - bench_reaper_pids()) if pids else False


COREAUDIO_DEFAULT = "<default system devices>"     # le choix « système » de REAPER macOS (bridge/desktop_audio.py)


def coreaudio_default_devices():
    """(entrée, sortie) par défaut du système, par leur NOM. Pas « <default system devices> » : REAPER
    rapporte alors « CoreAudio Default », la carte d'entrées se clé sur ce nom-là et perd le rôle choisi à
    l'installation (mesuré le 2026-11-04 : le patch basse refusé, « no lane »). Repli : le choix système."""
    names = [COREAUDIO_DEFAULT, COREAUDIO_DEFAULT]
    try:
        out = subprocess.run(["system_profiler", "-json", "SPAudioDataType"],
                             capture_output=True, text=True, timeout=15, check=True).stdout
        for group in json.loads(out).get("SPAudioDataType", []):
            for item in group.get("_items", []):
                name = item.get("_name")
                if not isinstance(name, str) or any(c in name for c in "\n\r="):
                    continue
                if item.get("coreaudio_default_audio_input_device") == "spaudio_yes":
                    names[0] = name
                if item.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                    names[1] = name
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        pass
    return tuple(names)


def configure_ini(path, audio_driver=None, dummy_audio=False, prior=None, coreaudio=False):
    """Ajoute la surface OSC et garde tous les réglages audio/MIDI de l'utilisateur.
    `prior(key, value)` : le reçu d'installation (docs/uninstall.md §9.2) — la valeur d'AVANT de chaque clé que
    golem écrit, None = absente (le premier passage gagne, c'est receipt.prior) ; même forme que sous Linux
    (prior.reaper_ini.keys, .existed, .csurf_added), plus prior.reaper_ini.audioconfig pour la section [audioconfig]."""
    path = Path(path)
    existed = path.exists()
    raw = path.read_bytes().decode("latin-1") if existed else "[reaper]\n"
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == "[reaper]"), None)
    if start is None:
        raise RuntimeError(f"no [reaper] section in {path}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    section = lines[start + 1:end]
    keys = {line.split("=", 1)[0].strip(): start + 1 + i
            for i, line in enumerate(section) if "=" in line}
    changed = False
    notes = {}                                  # clé -> valeur d'avant (None = absente), pour le reçu
    # ⚠ Au premier lancement, un REAPER épinglé (provision/windows/pins.json) qui n'est plus le dernier
    # ouvre une boîte MODALE « REAPER New Version Notification » : tant qu'elle est ouverte, __startup.lua
    # ne tourne pas et GoleM reste sans moteur (mesuré sur un Windows vierge le 2026-10-02, cachée
    # derrière le navigateur). GoleM épingle sa version : la vérification au démarrage est coupée, SI
    # l'utilisateur n'a rien choisi (une clé présente lui appartient). Help ▸ Check for new versions reste.
    if "verchk" not in keys:
        lines.insert(end, "verchk=0")
        end += 1
        changed = True
        notes["verchk"] = None
    # Forcées comme sous Linux (provision/reaper-ini-setup.py, ENGINE_FORCED) : norunmute=0 garde les
    # branches muettes traitées, automute=0 empêche REAPER de couper une piste à +6 dB en plein morceau.
    for key in ("norunmute", "automute"):
        want = f"{key}=0"
        # notées même déjà à 0 : la valeur d'avant golem, c'est 0 — le premier passage la fige
        notes[key] = lines[keys[key]].split("=", 1)[1] if key in keys else None
        if key in keys and lines[keys[key]] == want:
            continue
        if key in keys:
            lines[keys[key]] = want
        else:
            lines.insert(end, want)
            end += 1
        changed = True
    if not any(re.match(r"csurf_\d+=OSC \"golem\"(?: |$)", line) for line in lines[start + 1:end]):
        indices = [int(m.group(1)) for line in lines[start + 1:end]
                   if (m := re.match(r"csurf_(\d+)=", line))]
        index = max(indices, default=-1) + 1
        lines.insert(end, f"csurf_{index}={OSC_LINE}")
        end += 1
        count = index + 1
        count_idx = next((i for i in range(start + 1, end) if lines[i].startswith("csurf_cnt=")), None)
        if count_idx is None:
            lines.insert(end, f"csurf_cnt={count}")
        else:
            old = int(lines[count_idx].split("=", 1)[1])
            lines[count_idx] = f"csurf_cnt={max(old, count)}"
        changed = True
    # ⚠ macOS, même boîte que sous Windows : un profil REAPER neuf, sans périphérique Core Audio, ouvre
    # « REAPER Preferences » au premier lancement — lancé par `open -j`, donc caché — et tant qu'elle est
    # ouverte __startup.lua ne tourne pas (mesuré sur un MacBook Air le 2026-11-04). Choisir un seul
    # périphérique dans cette boîte l'écrit en entrée ET en sortie (le micro intégré : 0 sortie). On sème
    # donc les périphériques système par défaut, chacun dans son sens, 48 kHz / 256, SI l'utilisateur
    # n'a encore rien choisi. Pas d'équivalent de « Dummy Audio » ici : l'entrée par défaut est ouverte
    # (le micro intégré sur un portable — baisser le volume avant de jouer un son à fort gain).
    # `coreaudio` : True (les défauts lus maintenant) ou un couple (entrée, sortie) — les tests.
    if coreaudio and "coreaudioindevnew" not in keys and "coreaudiooutdevnew" not in keys:
        indev, outdev = coreaudio if isinstance(coreaudio, tuple) else coreaudio_default_devices()
        for key, value in (("coreaudioindevnew", indev), ("coreaudiooutdevnew", outdev),
                           ("coreaudiosrate", "48000"), ("coreaudiosrateuse", "1"),
                           ("coreaudiobs", "256"), ("coreaudiobsuse", "1")):
            notes[key] = lines[keys[key]].split("=", 1)[1] if key in keys else None
            if key in keys:
                lines[keys[key]] = f"{key}={value}"
            else:
                lines.insert(end, f"{key}={value}")
                end += 1
        changed = True
    audio_notes = None
    if audio_driver is not None or dummy_audio:
        audio_start = next((i for i, line in enumerate(lines)
                            if line.strip().lower() == "[audioconfig]"), None)
        audio_end = (next((i for i in range(audio_start + 1, len(lines))
                           if lines[i].startswith("[")), len(lines))
                     if audio_start is not None else None)
        # Une préférence audio existante appartient à l'utilisateur. On ne sème
        # l'ASIO qu'avant le tout premier démarrage de REAPER.
        if audio_start is None or not any(line.startswith("mode=")
                                           for line in lines[audio_start + 1:audio_end]):
            if audio_driver is not None:
                name, index = audio_driver
                settings = ["mode=3", f"asio_driver={index}",
                            f'asio_driver_name="{name}"', "asio_input0=0", "asio_input1=1",
                            "asio_output0=0", "asio_output1=1", "asio_srate_use=0",
                            "asio_bsize_use=0"]
            else:
                # ⚠ SANS AUCUN réglage audio, REAPER ouvre à CHAQUE lancement une boîte modale
                # « You have not yet selected an audio device » — et tant qu'elle est ouverte,
                # __startup.lua n'est pas exécuté : pas de veilleur, aucune commande consommée,
                # un GoleM inerte derrière un lanceur qui a écrit « lancé » (mesuré sur la VM
                # Windows le 2026-10-01 ; n'importe quel `mode=` suffit à la faire taire).
                # 4 = « Dummy Audio » : le moteur tourne, AUCUNE entrée n'est ouverte. Pas
                # DirectSound (1), qui marcherait « tout de suite » : il ouvre le micro par
                # défaut du poste, et un ampli à fort gain dessus, c'est un larsen au premier
                # lancement. Le son vient quand l'utilisateur choisit sa carte dans l'app.
                settings = ["mode=4"]
            before = {}
            if audio_start is not None:
                for line in lines[audio_start + 1:audio_end]:
                    if "=" in line:
                        before.setdefault(line.split("=", 1)[0].strip(), line.split("=", 1)[1])
            audio_notes = {"section_added": audio_start is None,
                           "keys": {s.split("=", 1)[0]: before.get(s.split("=", 1)[0]) for s in settings}}
            if audio_start is None:
                lines.extend(["[audioconfig]", *settings])
            else:
                lines[audio_start + 1:audio_start + 1] = settings
            changed = True
    if prior is not None:
        try:
            if not existed:
                prior("reaper_ini.existed", False)
            for key, value in notes.items():
                prior(f"reaper_ini.keys.{key}", value)
            # la surface OSC de golem est là (ajoutée maintenant ou par une install d'avant) : à retirer
            prior("reaper_ini.csurf_added", True)
            if audio_notes:
                prior("reaper_ini.audioconfig.section_added", audio_notes["section_added"])
                for key, value in audio_notes["keys"].items():
                    prior(f"reaper_ini.audioconfig.keys.{key}", value)
        except Exception as exc:
            print(f"⚠ install receipt not updated ({exc})", file=sys.stderr)
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        tmp = path.with_suffix(path.suffix + ".golem-tmp")
        tmp.write_bytes((newline.join(lines) + newline).encode("latin-1"))
        os.replace(tmp, path)
    return changed


# Le pilote ASIO NATIF d'une carte, par son identité USB (nom du pilote en minuscules -> VID&PID lu dans
# Get-PnpDevice). Identités MESURÉES, jamais une correspondance vague par marque (qui prendrait le pilote
# d'une autre interface). Volt 276 : TUSBAUDIO_ENUM\VID_2B5A&PID_0023 (PC de 2026-10-10).
KNOWN_USB_ASIO = {"umc asio driver": "VID_1397&PID_0509",
                  "universal audio volt": "VID_2B5A&PID_0023"}
# Des pilotes GÉNÉRIQUES : ils ré-emballent le point d'entrée Windows d'une carte, ils ne sont pas son pilote.
# ⚠ Mesuré le 2026-10-10 sur la Volt 276 : ASIO4ALL perdait la prise IN 2 (aucun des deux canaux ne la
# portait, IN 1 arrivait sur le canal 2) ; le pilote natif « Universal Audio Volt » rend les deux prises.
GENERIC_ASIO = ("asio4all", "flexasio", "rearoute", "realtek asio")


def is_generic_asio(name):
    n = str(name or "").casefold()
    return any(g in n for g in GENERIC_ASIO)


def native_asio_driver(drivers, media):
    """Le pilote natif d'UNE carte présente, (nom, index) ; None si aucune carte connue n'est branchée ou si
    deux le sont (on ne devine pas)."""
    candidates = []
    for index, name in enumerate(drivers):
        identity = KNOWN_USB_ASIO.get(name.casefold())
        if identity and any(identity in (device.get("InstanceId") or "").upper()
                            for device in media):
            candidates.append((name, index))
    return candidates[0] if len(candidates) == 1 else None


def select_asio_driver(drivers, media, requested=None):
    """Auto-select only hardware whose ASIO driver and USB identity we know."""
    if requested:
        matches = [(name, i) for i, name in enumerate(drivers)
                   if name.casefold() == requested.casefold()]
        if not matches:
            raise RuntimeError(f"ASIO driver not found: {requested}")
        return matches[0]
    return native_asio_driver(drivers, media)


def present_media():
    """Les cartes son PRÉSENTES et en état (Get-PnpDevice -Class MEDIA) : [{FriendlyName, InstanceId}]."""
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             "Get-PnpDevice -PresentOnly -Class MEDIA | "
             "Where-Object Status -eq OK | "
             "Select-Object FriendlyName,InstanceId | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
            creationflags=NO_WINDOW)
        media = json.loads(result.stdout) if result.stdout.strip() else []
        return [media] if isinstance(media, dict) else media
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def windows_asio_driver():
    if sys.platform != "win32":
        return None
    import winreg
    try:
        # REAPER desktop est x64 même si l'interpréteur Python lancé est x86.
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ASIO", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            drivers = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except OSError:
        return None
    if not drivers:
        return None
    requested = os.environ.get("GOLEM_ASIO_DRIVER")
    if requested:
        return select_asio_driver(drivers, [], requested)
    return select_asio_driver(drivers, present_media())


def copy_resources(dest, record=None):
    """Copie les ressources nécessaires et conserve le startup utilisateur.
    `record(path, kind, group, moved_to=None)` : le reçu d'installation (docs/uninstall.md §9.2) — appelé par le
    setup seulement (start() recopie aussi, sans rien noter)."""
    dest = Path(dest)
    scripts = dest / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    startup = scripts / "__startup.lua"
    source = ROOT / "reaper" / "Scripts" / "__startup.lua"
    hook = "-- GoleM desktop startup hook"
    user_startup = scripts / "__startup.golem-user.lua"
    if startup.exists() and not startup.read_text(encoding="utf-8", errors="replace").startswith(hook):
        if startup.read_bytes() != source.read_bytes():
            if user_startup.exists():
                shutil.copy2(user_startup, scripts / f"__startup.golem-user.lua.bak.{time.time_ns()}")
            shutil.copy2(startup, user_startup)
    wrapper = [hook, "local res = reaper.GetResourcePath()"]
    if user_startup.exists():
        wrapper += ['local ok, err = pcall(dofile, res .. "/Scripts/__startup.golem-user.lua")',
                    'if not ok then reaper.ShowConsoleMsg("GoleM: user startup: " .. tostring(err) .. "\\n") end']
    # protégé comme le startup de l'utilisateur : une erreur dans celui de golem se DIT dans la console de REAPER
    wrapper += ['local gok, gerr = pcall(dofile, res .. "/Scripts/golem/__startup.lua")',
                'if not gok then reaper.ShowConsoleMsg("GoleM: startup: " .. tostring(gerr) .. "\\n") end', ""]
    startup.write_text("\n".join(wrapper), encoding="utf-8")
    shutil.copytree(ROOT / "reaper" / "Scripts", scripts / "golem", dirs_exist_ok=True)
    shutil.copytree(ROOT / "reaper" / "Effects", dest / "Effects" / "golem", dirs_exist_ok=True)
    osc = dest / "OSC"
    osc.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "reaper" / "OSC" / "golem.ReaperOSC", osc / "golem.ReaperOSC")
    from bridge import config as C
    Path(C.RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    for name, value in (("golem-root.txt", str(ROOT)), ("golem-runtime.txt", C.RUNTIME_DIR)):
        tmp = dest / (name + ".tmp")
        tmp.write_text(value + "\n", encoding="utf-8")
        os.replace(tmp, dest / name)
    if record is not None:
        # __startup.lua : l'original de l'utilisateur vit désormais dans __startup.golem-user.lua (même posé par
        # une install d'avant le reçu) — la désinstallation l'y reprend
        record(startup, "file", "reaper-links", moved_to=user_startup if user_startup.exists() else None)
        for path, kind in ((scripts / "golem", "dir"), (dest / "Effects" / "golem", "dir"),
                           (osc / "golem.ReaperOSC", "file"), (dest / "golem-root.txt", "file"),
                           (dest / "golem-runtime.txt", "file"),
                           # journaux, verrou, dernier projet (golem_paths.lua, remember_project) : né au 1er démarrage
                           (dest / "GoleM", "dir")):
            record(path, kind, "reaper-links")


def venv_python():
    return ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def setup():
    if reaper_running():
        raise RuntimeError("Close REAPER before the setup: it rewrites reaper.ini when it quits.")
    if sys.platform == "darwin":
        # dit, sans arrêter : comme sous Windows, le setup pose GoleM même sans REAPER (la CI macos-26 le
        # joue sans) — c'est `start` qui refuse de démarrer un moteur absent, avec la même adresse
        for line in mac_prerequisites():
            print("⚠ " + line)
    dest = resource_dir()
    R = _receipt()
    # LES REPÈRES (2026-10-24) : un testeur Windows est resté 16 min sur « golem itself » sans une ligne — la sortie du
    # setup, tamponnée sous un pipe, ne disait rien de l'endroit. Chaque étape s'annonce, `flush` compris.
    step = lambda what: print("→ " + what, flush=True)                                   # noqa: E731

    def record(path, kind, group, moved_to=None):
        _record("add", str(path), kind, RECEIPT_BY, group, moved_to=str(moved_to) if moved_to else None)
    step("REAPER scripts and effects")
    copy_resources(dest, record if R is not None else None)
    step("golem capture reader")
    from provision.capture_player import install_bundled as install_capture_player
    install_capture_player()
    step("looking for the sound card's ASIO driver" if sys.platform == "win32" else "audio device (Core Audio)")
    driver = windows_asio_driver()
    configure_ini(dest / "reaper.ini", driver, dummy_audio=sys.platform == "win32",
                  prior=(lambda k, v: _record("prior", k, v)) if R is not None else None,
                  coreaudio=sys.platform == "darwin")
    if R is not None:
        # le dossier de GoleM sous %LOCALAPPDATA% : le runtime, le profil du navigateur, l'environnement NAM
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "GoleM"
        record(local, "dir", "golem")
        record(browser_profile(), "dir", "golem")
    if driver:
        print(f"ASIO driver found: {driver[0]} (used if REAPER has no audio setting yet).")
    elif sys.platform == "win32":
        print("No known ASIO driver: with no audio setting yet, REAPER starts without a sound card "
              "(Dummy Audio). Pick your driver in golem ▸ Settings ▸ Soundcard ▸ Configure ASIO…")
    python = venv_python()
    if R is not None:
        # Windows (le reçu n'existe que là) : le cache de pip (%LOCALAPPDATA%\pip) existait-il avant golem ? Noté
        # AVANT le premier pip (le bootstrap l'a déjà noté s'il est passé : le premier gagne) — la désinstallation ne
        # l'efface que s'il est né de golem
        pip_cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "pip"
        _record("prior", "pip_cache_existed", pip_cache.exists())
    if not python.exists():
        step("creating golem's Python environment (about a minute)")
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True)
    step("golem's Python packages (pip)")
    # le VERROU, empreintes comprises (audit 2026-10-15) : résolu pour Windows, macOS Intel/Apple Silicon et Linux
    # (simulé avec `uv pip install --dry-run --python-platform …` le jour où il a été écrit)
    subprocess.run([str(python), "-m", "pip", "install", "--require-hashes", "-r",
                    str(ROOT / "bridge" / "requirements.lock")], check=True)
    # INSTALLÉ n'est pas CHARGEABLE. Sur un Windows vierge, pip pose python-rtmidi sans erreur
    # et son module natif ne se charge pas : il lui faut le runtime Visual C++, que Python
    # n'apporte pas. Le bridge démarre quand même — pied et sortie MIDI muets, sans un mot à
    # l'écran (mesuré sur la VM le 2026-10-01). On le vérifie ici, où quelqu'un lit.
    step("checking that MIDI loads")
    probe = subprocess.run([str(python), "-c", "import rtmidi"], capture_output=True, text=True)
    if probe.returncode != 0:
        why = (probe.stderr.strip().splitlines() or ["unknown error"])[-1]
        hint = ("\nInstall the « Microsoft Visual C++ Redistributable (x64) » — "
                "https://aka.ms/vs/17/release/vc_redist.x64.exe — then run the setup again."
                if sys.platform == "win32" else "")
        raise RuntimeError(f"python-rtmidi is installed but does not load ({why}): "
                           f"the pedalboard and MIDI output would stay silent.{hint}")
    # le tape delay Airwindows : même plugin que sous Linux, sans droits d'admin. Non fatal — une source
    # tierce qui casse ne bloque pas l'installation, le bloc reste barré et l'onglet Libraries le dit.
    if sys.platform == "win32":
        step("desktop plugins: Airwindows, Dragonfly Reverb, Surge XT Effects")
        try:
            from provision import airwindows
            airwindows.install()
        except Exception as exc:
            print(f"⚠ Airwindows TapeDelay2 not installed ({exc}) — its block stays unavailable.")
        # les réverbes Dragonfly (2026-10-22) : la table Windows les nommait, rien ne les posait — sans elles
        # presque toute l'usine jouait sans réverbe. Même règle : sans droits d'admin, non fatal.
        try:
            from provision import dragonfly
            dragonfly.install()
        except Exception as exc:
            print(f"⚠ Dragonfly Reverb not installed ({exc}) — the Reverb, Plate and Room blocks stay unavailable.")
        # Surge XT Effects (2026-10-22) : les trois blocs surge-* — la table le disait installé, rien ne le posait
        try:
            from provision import surge
            surge.install()
        except Exception as exc:
            print(f"⚠ Surge XT Effects not installed ({exc}) — the Spring, Freq Shifter and Treemonster blocks stay unavailable.")
    for path in install_shortcuts():
        print(f"Shortcut: {path}")
    print(f"golem is ready in {ROOT}.")


def reaper_binary():
    override = os.environ.get("REAPER_BIN")
    if override:
        return Path(override)
    if sys.platform == "win32":
        # OÙ QU'IL SOIT : le chemin retenu à l'installation, le registre, puis Program Files (2026-10-17 — un REAPER
        # sur D: était invisible). La même fonction que l'installateur : bridge/reaper_license.windows_exe.
        from bridge.reaper_license import windows_exe
        return Path(windows_exe())
    return Path("/Applications/REAPER.app/Contents/MacOS/REAPER")


def remember_project(project):
    """Remember an automatically saved GoleM session for the next desktop launch."""
    project = Path(project).resolve()
    if not project.is_file() or not project.is_relative_to((ROOT / "sets").resolve()):
        raise ValueError("golem project outside the sets folder")
    marker = resource_dir() / "GoleM" / "last-project.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(str(project) + "\n", encoding="utf-8")
    os.replace(tmp, marker)


def desktop_project():
    """Resume the last GoleM session when it was saved automatically."""
    marker = resource_dir() / "GoleM" / "last-project.txt"
    try:
        project = Path(marker.read_text(encoding="utf-8").strip()).resolve()
        if project.is_file() and project.is_relative_to((ROOT / "sets").resolve()):
            return project
    except (OSError, ValueError):
        pass
    return ROOT / "sets" / "golem-set.rpp"


def launch_reaper(args, **kwargs):
    """Start the desktop audio backend without presenting its main UI."""
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        if not show_reaper():
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
        process = subprocess.Popen(args, startupinfo=startup, **kwargs)
        register_reaper_pid(process.pid)
        return process
    if sys.platform == "darwin":
        binary = PurePosixPath(args[0])
        app = next((parent for parent in binary.parents if parent.suffix == ".app"), None)
        if app is not None:
            return subprocess.Popen(["open", "-j", "-a", str(app), "--args", *args[1:]], **kwargs)
    return subprocess.Popen(args, **kwargs)


def _backend_pids_file():
    session = os.environ.get("GOLEM_DESKTOP_SESSION")
    if not session:
        return None
    from bridge import config as C
    return Path(C.runtime_file(f"desktop-pids-{session}.json"))


def register_reaper_pid(pid):
    path = _backend_pids_file()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        pids = set(json.loads(path.read_text(encoding="ascii")))
    except (OSError, ValueError):
        pids = set()
    pids.add(pid)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(sorted(pids)), encoding="ascii")
    os.replace(tmp, path)


def unregister_reaper_pid(pid):
    path = _backend_pids_file()
    if path is None:
        return
    pids = _backend_pids()
    pids.discard(pid)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(sorted(pids)), encoding="ascii")
    os.replace(tmp, path)


def _backend_pids():
    path = _backend_pids_file()
    if path is None:
        return set()
    try:
        return set(json.loads(path.read_text(encoding="ascii")))
    except (OSError, ValueError):
        return set()


def show_reaper():
    """`start --dev` : REAPER à l'écran, comme `golem desktop --dev` sous Linux."""
    return os.environ.get("GOLEM_SHOW_REAPER") == "1"


def start_reaper_window_guard():
    """Catch REAPER windows that appear after startup or an audio restart."""
    if sys.platform != "win32" or show_reaper():
        return
    from provision.desktop_window import set_reaper_windows_visible, focus_window

    # PENDANT LE DÉMARRAGE (et après « Restart REAPER »), toutes les 25 ms : REAPER se montre par-dessus l'écran de
    # chargement et prend le focus (2026-10-11) ; à 500 ms, on le voyait. Masqué, le premier plan revient à la
    # fenêtre golem (« /desktop »). Le golem joue : 500 ms suffisent pour les fenêtres qui réapparaissent plus tard.
    def booting():
        try:
            from bridge import boot_progress
            d = boot_progress.doc()
            return d.get("done") is None and (d.get("now", 0) - d.get("t0", 0)) < 90
        except Exception:
            return False

    def watch():
        refocused_for = None
        while True:
            fast = booting()
            try:
                if set_reaper_windows_visible(_backend_pids(), False) and fast:
                    try:
                        from bridge import boot_progress
                        t0 = boot_progress.doc().get("t0")
                    except Exception:
                        t0 = None
                    if t0 != refocused_for:                   # une fois par démarrage, pas à chaque masquage
                        refocused_for = t0
                        try:
                            focus_window(app_window_pids(), "/desktop")
                        except Exception:
                            pass
            except OSError:
                pass
            time.sleep(0.025 if fast else 0.5)

    threading.Thread(target=watch, name="golem-reaper-window", daemon=True).start()


# ── LA FENÊTRE GOLEM (pendant Windows/macOS de provision/golem) ─────────────────────────────
# Sous Linux, `golem desktop` ouvre l'app dans une fenêtre APPLICATIVE : Chromium `--app` (pas
# d'onglets, pas de barre d'adresse), sur la coquille tablette `device.html` qui garantit un écran
# de 1024×600 exact, avec un profil de navigateur DÉDIÉ et la taille/le zoom mémorisés. Même chose
# ici, trait pour trait — avant, le lanceur Windows ouvrait /app/ dans un onglet du navigateur
# personnel (webbrowser.open), à la taille de ce navigateur. Le contrat de la mémoire de fenêtre
# (config/.desktop.json, ?shell=, base/forced) est celui de docs/ui-architecture.md : on ne le
# réinvente pas, on rejoue la fonction `geom` du lanceur Linux.
PANEL_W, PANEL_H = 1024, 600
# coquille -> (requête de device.html, largeur, hauteur) : mêmes nombres que provision/golem
SHELLS = {
    "device": ("", PANEL_W + 52 + 24, PANEL_H + 52 + 72),
    "phone": ("?d=phone", 390 + 28 + 130, 844 + 28 + 96),
    "ui": (None, PANEL_W, PANEL_H),
}
GEOM_FILE = ROOT / "config" / ".desktop.json"


def app_browser():
    """Un Chromium capable de `--app` : Chrome d'abord (comme sous Linux), Edge ensuite — Edge est
    livré avec Windows, mais il peut manquer (retiré par l'utilisateur : c'est le cas sur le poste
    de 2026-10-02). GOLEM_BROWSER force un exécutable."""
    override = os.environ.get("GOLEM_BROWSER")
    if override:
        return override if Path(override).is_file() else None
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser"):
            exe = Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / app
            if exe.is_file():
                return str(exe)
        return None
    found = []
    for exe in ("chrome.exe", "msedge.exe"):
        # « App Paths » : là où les installeurs déclarent leur exécutable, quel que soit le dossier
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                with contextlib.suppress(OSError), winreg.OpenKey(
                        hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                    found.append(winreg.QueryValue(key, None))
        except ImportError:
            pass
        sub = (r"Google\Chrome\Application" if exe == "chrome.exe" else r"Microsoft\Edge\Application")
        for base in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if os.environ.get(base):
                found.append(os.path.join(os.environ[base], sub, exe))
    return next((p.strip('"') for p in found if p and Path(p.strip('"')).is_file()), None)


def browser_profile():
    """PROFIL DÉDIÉ — pas un confort : si le navigateur tourne déjà avec le profil par défaut, un
    nouveau processus lui passe l'URL et s'arrête, --window-size et --app compris (provision/golem)."""
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GoleM" / "browser"
    return Path.home() / "Library" / "Application Support" / "GoleM" / "browser"


def app_window_pids():
    """Les processus du navigateur DÉDIÉ — jamais le navigateur personnel : on ne retient que ceux
    dont la ligne de commande porte `--user-data-dir=<profil de GoleM>`, tel quel."""
    marker = f"--user-data-dir={browser_profile()}".casefold()
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                 "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='msedge.exe'\" | "
                 "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
                capture_output=True, text=True, encoding="utf-8", timeout=15, creationflags=NO_WINDOW).stdout
            rows = json.loads(out) if out.strip() else []
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        rows = [rows] if isinstance(rows, dict) else rows
        return [int(r["ProcessId"]) for r in rows
                if marker in str(r.get("CommandLine") or "").replace('"', "").casefold()]
    try:
        out = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(line.split(None, 1)[0]) for line in out.splitlines()
            if marker in line.casefold() and line.split(None, 1)[0].isdigit()]


def close_app_windows():
    """Ferme les fenêtres GoleM (le ✕ et le ⏻ de la coquille, `stop`). Rend le nombre de processus."""
    pids = app_window_pids()
    for pid in pids:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               timeout=10, creationflags=NO_WINDOW)
            else:
                os.kill(pid, 15)
    return len(pids)


def window_geometry(shell, width, height, reset=False, reused=False):
    """La fonction `geom` de provision/golem : (largeur, hauteur, échelle forcée ou 0)."""
    try:
        data = json.loads(GEOM_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    mem = data.get(shell) if isinstance(data.get(shell), dict) else {}
    if reset and shell in data:
        mem = {}
        data.pop(shell)
        _write_geometry(data)
    w = int(mem.get("w") or 0) or width
    h = int(mem.get("h") or 0) or height
    dpr, base = float(mem.get("dpr") or 0), float(mem.get("base") or 0)
    # on ne force l'échelle QUE si l'utilisateur a vraiment zoomé (dpr ≠ l'échelle naturelle) ;
    # un navigateur déjà lancé sur ce profil ignore nos drapeaux : on ne prétend pas avoir forcé
    dsf = 0 if reused else (dpr if dpr and base and abs(dpr - base) > 0.01 else 0)
    if mem:
        # on ÉCRIT ce qu'on force : la page saura que le dpr qu'elle voit n'est pas celui de l'écran
        mem["forced"] = round(dsf, 4)
        data[shell] = mem
        _write_geometry(data)
    return w, h, round(dsf, 4)


def _write_geometry(data):
    with contextlib.suppress(OSError):
        GEOM_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = GEOM_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, GEOM_FILE)


def wait_for_screen(port, timeout=4.0):
    """Vrai dès qu'une page de l'app est connectée au bridge (`screens` de /api/health) ; faux après `timeout`."""
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        if int((bridge_health(port) or {}).get("screens") or 0) > 0:
            return True
        time.sleep(0.1)
    return False


# ── LA FENÊTRE D'ABORD, REAPER ENSUITE (2026-10-11) ───────────────────────────────────────────
# L'écran de chargement (mockups/loading.html) remplace /live tant que le premier preset ne joue pas. Il ne se
# voyait pas : REAPER partait AVANT la fenêtre, et tout était fini quand Chrome affichait la page. L'ordre est
# donc bridge -> fenêtre -> REAPER, REAPER partant dès que la page est CONNECTÉE (pas « ouverte » : un process
# Chrome qui existe n'affiche encore rien) — avec un filet de 4 s si la fenêtre tarde (navigateur par défaut,
# machine lente) : on ne retient jamais le moteur pour un écran. `golem server` (sans fenêtre) : REAPER tout de suite.
def _bring_up(port, reaper_args, window, shell="device", reset=False, fullscreen=False):
    url = f"http://127.0.0.1:{port}/app/"
    if window:
        open_window(port, shell, reset, fullscreen)
        if not wait_for_screen(port):
            print("golem window is slow to show — starting REAPER anyway")
    # REAPER ne tient pas encore le pilote ASIO : il dit ses tailles de buffer (une fois par pilote, bridge/asio_probe.py)
    try:
        from bridge import desktop_audio
        desktop_audio.probe_asio_if_missing()
    except Exception:
        pass
    launch_reaper(reaper_args, cwd=ROOT)
    if window:
        print(f"golem is running: {url} — Ctrl+C here, or ⏻ in the golem window, stops it.")
    else:
        # le message ne bloque pas : sous pythonw une boîte Windows est MODALE, et ce processus doit
        # rester sur bridge.wait() (c'est lui qui rend REAPER visible quand GoleM s'arrête)
        threading.Thread(target=_notify, args=(server_message(port),), daemon=True).start()


def open_window(port, shell="device", reset=False, fullscreen=False):
    """Ouvre GoleM dans sa fenêtre applicative. Sans Chromium : le navigateur par défaut, et on le dit."""
    query, width, height = SHELLS[shell]
    if query is None:
        url = f"http://127.0.0.1:{port}/app/?shell={shell}"
    else:
        url = f"http://127.0.0.1:{port}/app/device.html{query}{'&' if query else '?'}shell={shell}"
    browser = app_browser()
    if browser is None:
        print("No Chrome or Edge found: golem opens in your default browser, in a tab "
              "(install Google Chrome to get the golem window).")
        webbrowser.open(url)
        return None
    pids = app_window_pids()
    reused = bool(pids)
    # la coquille porte son titre (device.html : « /desktop » ou « /phone ») : déjà ouverte, on la ramène
    title = {"device": "/desktop", "phone": "/phone"}.get(shell)
    if reused and title and sys.platform == "win32":
        from provision.desktop_window import focus_window
        if focus_window(set(pids), title):
            return None
    if reused:
        print("A golem window is already open: the browser reuses it, the remembered zoom does not apply to the new one.")
    w, h, dsf = window_geometry(shell, width, height, reset=reset, reused=reused)
    profile = browser_profile()
    profile.mkdir(parents=True, exist_ok=True)
    # FENÊTRE, jamais kiosque : le kiosque a été retiré sous Linux le 2026-07-29 (il enferme).
    # `--fullscreen` est un plein écran NAVIGATEUR, dont F11 sort.
    extra = ["--start-fullscreen"] if fullscreen else [f"--window-size={w},{h}"]
    if dsf and not fullscreen:
        extra.append(f"--force-device-scale-factor={dsf}")
    args = [browser, f"--app={url}", f"--user-data-dir={profile}", *extra,
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)


ICON = ROOT / "app" / "icons" / "golem.ico"
PHONE_ICON = ROOT / "app" / "icons" / "golem-phone.ico"


def base_pythonw(root=None):
    """Le pythonw.exe du Python de BASE (celui du bootstrap), jamais celui du venv : le désinstallateur supprime le
    venv (docs/uninstall.md §9.4). Dans l'ordre : `home` de <root>/.venv/pyvenv.cfg (le dossier du Python qui a
    créé le venv — vrai quel que soit le Python qui appelle), sys._base_executable, sys.executable. None si aucun
    pythonw.exe n'existe là."""
    root = Path(root or ROOT)
    cands = []
    try:
        for line in (root / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip().lower() == "home" and value.strip():
                cands.append(Path(value.strip()) / "pythonw.exe")
    except OSError:
        pass
    for exe in (getattr(sys, "_base_executable", None), sys.executable):
        if exe:
            cands.append(Path(exe).with_name("pythonw.exe"))
    venv = (root / ".venv").resolve() if (root / ".venv").exists() else None
    for c in cands:
        try:
            if venv is not None and venv in c.resolve().parents:
                continue                          # un pythonw DU venv : il part avec lui
        except OSError:
            pass
        if c.is_file():
            return c
    return None


def uninstall_shortcut(root=None):
    """(cible, arguments, dossier de travail) du raccourci « Uninstall golem », ou None sans Python de base.
    Le désinstallateur vit dans <root>\\installer : il s'y copie dans %TEMP% et s'y relance (docs/uninstall.md §9.4).
    Dossier de travail : le home, JAMAIS l'install — Windows ne supprime pas le dossier courant d'un processus."""
    root = Path(root or ROOT)
    pyw = base_pythonw(root)
    if pyw is None:
        return None
    server = root / "installer" / "server.py"
    return pyw, f'"{server}" --uninstall --root "{root}" --open', Path.home()


def install_shortcuts():
    """Les icônes GoleM de Windows — pendant de provision/install-desktop.sh (golem.desktop et ses
    actions « coquille tablette » / « arrêter », et `golem phone`) : GoleM et GoleM Phone sur le
    Bureau et dans le menu Démarrer, « Stop GoleM » dans le menu Démarrer. La cible est pythonw.exe : PAS de console noire à côté
    de la fenêtre GoleM (les erreurs passent par une boîte Windows, voir _tell)."""
    if sys.platform == "darwin":
        return mac_shortcuts()
    if sys.platform != "win32":
        return []
    pythonw = venv_python().with_name("pythonw.exe")
    if not pythonw.is_file():
        raise RuntimeError(f"{pythonw} is missing: run the golem setup first")
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    # DEUX USAGES (docs/installer.md §4, 2026-10-06) : GoleM (une fenêtre) et GoleM Server (sans fenêtre,
    # une tablette est l'écran). « GoleM Phone » n'est plus proposé : la coquille de téléphone est un
    # outil de dev (`python -m provision.desktop start --shell phone`) — ses anciens raccourcis sont retirés.
    rig, server = "golem — your guitar rig", "golem server — no window: play from a tablet or a phone"
    run = lambda command: (pythonw, "-m provision.desktop " + command, ROOT)
    links = [("Desktop", "golem", run("start"), ICON, rig),
             ("Programs", "golem", run("start"), ICON, rig),
             ("Desktop", "golem server", run("server"), ICON, server),
             ("Programs", "golem server", run("server"), ICON, server),
             ("Programs", "Stop golem", run("stop"), ICON, "Stop golem: REAPER, the bridge and the golem windows")]
    # « Uninstall golem » (docs/uninstall.md §9.4) : le Python de BASE — celui du venv part avec lui
    uninst = uninstall_shortcut()
    if uninst is not None:
        links.append(("Programs", "Uninstall golem", uninst, ICON,
                      "Uninstall golem: choose what goes, back up your work first"))
    else:
        print("⚠ no base Python found: the « Uninstall golem » shortcut is not created", file=sys.stderr)
    script = ["$s = New-Object -ComObject WScript.Shell"]
    # les anciennes icônes : « GoleM Phone » (2026-10-06 : du dev) et les noms à l'ancienne casse « GoleM »
    # (la marque s'écrit golem). NTFS ignore la casse : écrire golem.lnk sur un GoleM.lnk garderait le
    # VIEUX nom affiché — on retire d'abord.
    script += [f"Remove-Item -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('{folder}')) '{old}.lnk')"
               for folder in ("Desktop", "Programs") for old in LEGACY_NAMES]
    # GetFolderPath : le VRAI Bureau (OneDrive le redirige souvent) ; FullName rend le chemin réel, noté au reçu
    for folder, name, (target, arguments, workdir), icon, about in links:
        script.append(
            f"$l = $s.CreateShortcut((Join-Path ([Environment]::GetFolderPath('{folder}')) {q(name + '.lnk')})); "
            f"$l.TargetPath = {q(target)}; $l.Arguments = {q(arguments)}; "
            f"$l.WorkingDirectory = {q(workdir)}; $l.IconLocation = {q(str(icon) + ',0')}; "
            f"$l.Description = {q(about)}; $l.Save(); Write-Output $l.FullName")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                          "; ".join(script)], capture_output=True, text=True, timeout=60,
                         creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(f"Could not create the golem shortcuts: {out.stderr.strip()}")
    made = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    for path in made:                             # le reçu (docs/uninstall.md §9.2) : chaque .lnk, par son vrai chemin
        _record("add", path, "file", RECEIPT_BY, "golem")
    return made


# ── macOS (2026-10-04, docs/platforms.md M7) ─────────────────────────────────────────────
# Le pendant des raccourcis Windows : trois petites apps dans ~/Applications (le Launchpad et Spotlight
# les trouvent), chacune un script qui lance `python -m provision.desktop <commande>` du venv. Une app
# fabriquée SUR le Mac n'a pas l'attribut de quarantaine : Gatekeeper ne la bloque pas, sans signature.
# Pas de Terminal à côté de la fenêtre GoleM : la sortie va dans le journal du lanceur.
MAC_APPS = (("golem", "start", "golem — your guitar rig"),
            ("golem server", "server", "golem server — no window: play from a tablet or a phone"),
            ("Stop golem", "stop", "Stop golem: REAPER, the bridge and the golem windows"))
# les noms d'avant (2026-10-06) : la marque s'écrit golem, et « GoleM Phone » était du dev. Retirés avant
# d'écrire les nouveaux — NTFS et APFS ignorent la casse : le nouveau nom n'écraserait pas l'ancien affichage.
LEGACY_NAMES = ("GoleM", "GoleM Server", "Stop GoleM", "GoleM Phone")


def mac_app_script(command, root=None, python=None):
    root = str(root or ROOT)
    python = str(python or venv_python())
    q = lambda s: "'" + str(s).replace("'", "'\\''") + "'"
    log = q(Path.home() / "Library" / "Logs" / "GoleM-launcher.log")
    return ("#!/bin/bash\n"
            "# GoleM — généré par `python -m provision.desktop setup` (provision/desktop.py, mac_shortcuts)\n"
            f"cd {q(root)} || exit 1\n"
            'mkdir -p "$HOME/Library/Logs"\n'
            f"exec {q(python)} -m provision.desktop {command} >>{log} 2>&1\n")


def mac_app_plist(name, about):
    import plistlib
    return plistlib.dumps({"CFBundleName": name, "CFBundleDisplayName": name, "CFBundleExecutable": "run",
                           "CFBundleIdentifier": "fm.golem." + name.lower().replace(" ", "-"),
                           "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0",
                           "CFBundleGetInfoString": about, "LSUIElement": True})


def mac_shortcuts(dest=None):
    """Écrit golem.app, golem server.app et Stop golem.app dans ~/Applications. Rend leurs chemins.
    Les apps d'avant (LEGACY_NAMES) sont retirées d'abord."""
    dest = Path(dest or (Path.home() / "Applications"))
    for old in LEGACY_NAMES:
        shutil.rmtree(dest / f"{old}.app", ignore_errors=True)
    out = []
    for name, command, about in MAC_APPS:
        app = dest / f"{name}.app"
        macos = app / "Contents" / "MacOS"
        macos.mkdir(parents=True, exist_ok=True)
        (app / "Contents" / "Info.plist").write_bytes(mac_app_plist(name, about))
        run = macos / "run"
        run.write_text(mac_app_script(command), encoding="utf-8", newline="\n")
        run.chmod(0o755)
        out.append(str(app))
    return out


def mac_prerequisites():
    """Ce que GoleM n'installe pas encore sur un Mac (REAPER, NAM VST3) : présents, ou la phrase qui dit
    quoi faire. Rend la liste des manques (vide = prêt). Les adresses viennent de provision/macos/pins.json."""
    pins = json.loads((ROOT / "provision" / "macos" / "pins.json").read_text(encoding="utf-8"))
    missing = []
    if not reaper_binary().is_file():
        missing.append(f"REAPER {pins['reaper']['version']} is not in /Applications — install it from "
                       f"{pins['reaper']['url']} (or set REAPER_BIN), then run the setup again.")
    nam = [Path("/Library/Audio/Plug-Ins/VST3/NeuralAmpModeler.vst3"),
           Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3" / "NeuralAmpModeler.vst3"]
    if not any(p.exists() for p in nam):
        missing.append(f"Neural Amp Modeler (VST3) is not installed — amps and cabs stay silent. Install "
                       f"{pins['nam_vst3']['version']} from {pins['nam_vst3']['url']}")
    return missing


def connect(body):
    """Les deux clés de l'écran Connect de l'installateur, écrites SANS lancer GoleM (2026-10-02 :
    GoleM ne démarre qu'à la fin). On passe par la fonction même de Settings ▸ API (bridge, POST
    /api/integrations) : un seul magasin, une seule règle (le jeton golem.fm suit son serveur, la clé
    TONE3000 va dans .env). Corps : {golem_token?, t3k_key?} ; rien = l'état, masqué."""
    import asyncio
    from bridge import routes_content as R
    golem_token = str(body.get("golem_token") or "").strip()
    t3k_key = str(body.get("t3k_key") or "").strip()
    save = {}
    if t3k_key:
        save["tone3000"] = {"publishable_key": t3k_key}
    if golem_token:
        save["golemfm"] = {"token": golem_token}           # sous le serveur de GOLEM_SERVER_URL (.env), golem.fm par défaut
    if save:
        result = asyncio.run(R.save_integrations(save))
        if not isinstance(result, dict):              # une JSONResponse = un refus de la règle
            raise RuntimeError(json.loads(result.body).get("error") or "refused")
    current = R.get_integrations()
    return {"golem_token": current["golemfm"]["token"],
            "t3k_key": current["tone3000"].get("publishable_key") or {"set": False, "hint": ""}}


def bridge_health(port):
    """{"ok": True} golem tourne · {"stopping": True} il s'arrête (⏻) · None personne ne répond."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return json.loads(r.read() or b"{}")
    except (OSError, ValueError):
        return None


def bridge_answers(port):
    return bool((bridge_health(port) or {}).get("ok"))


def wait_stopped(port, seconds=45):
    """Un golem EN TRAIN DE S'ARRÊTER (⏻ « Stop golem ») : attendre qu'il soit parti — bridge muet, REAPER fermé —
    avant de démarrer. Rend True s'il est parti. L'arrêt prend jusqu'à ~25 s (projet enregistré, REAPER fermé,
    boîte « enregistrer ? » comprise) : 45 s couvrent le pire mesuré."""
    for _ in range(int(seconds * 2)):
        if bridge_health(port) is None and not reaper_running():
            return True
        time.sleep(0.5)
    return False


def _golem_reaper_pids():
    """Les reaper.exe de GoleM, retrouvés SANS le bridge (Windows) : le registre de session disparaît avec
    lui, donc on lit la ligne de commande — GoleM ouvre toujours un projet de son dossier sets/. Un REAPER
    que le musicien a ouvert lui-même n'y figure pas, et n'est jamais touché."""
    if sys.platform != "win32":
        return set()
    script = ("Get-CimInstance Win32_Process -Filter \"Name='reaper.exe'\" | "
              "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                             text=True, timeout=20, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    sets = str(ROOT / "sets").casefold()
    pids = set()
    for line in out.splitlines():
        pid, _, cmd = line.partition("	")
        if pid.strip().isdigit() and sets in cmd.casefold():
            pids.add(int(pid))
    return pids


def _close_hung_reaper():
    """REAPER de GoleM FIGÉ (thread principal muet 15 s) -> terminé. Rend le nombre de process fermés.
    Vivant (une boîte « Enregistrer ? » répond) : on n'y touche pas. Vécu le 2026-10-05 : le bridge parti,
    un REAPER figé restait ouvert, et `restart` s'arrêtait sur « Close REAPER first » à chaque fois."""
    from provision.desktop_window import reaper_hung, force_close_reaper
    pids = _golem_reaper_pids()
    if not pids or not reaper_hung(pids):
        return 0
    killed = force_close_reaper(pids)
    for _ in range(20):
        if not reaper_running():
            break
        time.sleep(0.5)
    return killed


def stop():
    """`golem stop` : le ⏻ de la coquille — fenêtres, REAPER, puis le bridge."""
    port = int(os.environ.get("GOLEM_PORT", "8770"))
    if not bridge_answers(port):
        closed = close_app_windows()
        forced = _close_hung_reaper() if reaper_running() else 0
        print("golem is not running." + (f" {closed} golem window process(es) closed." if closed else "")
              + (" REAPER had stopped responding and was closed." if forced else ""))
        return
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ui/quit", data=b'{"stop": true}',
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30):
        pass
    for _ in range(60):
        if not bridge_answers(port):
            # le bridge part au bout de 20 s même si REAPER est encore là : « stopped » ne se dit
            # qu'une fois REAPER fermé — sinon le relancement échouait sans qu'on sache pourquoi
            for _ in range(20):
                if not reaper_running():
                    print("golem stopped.")
                    return
                time.sleep(0.5)
            if _close_hung_reaper() and not reaper_running():
                print("golem stopped (REAPER had stopped responding and was closed).")
                return
            raise RuntimeError("golem stopped, but REAPER is still open — it may be asking to save "
                               "its project. Answer it, then start golem again.")
        time.sleep(0.5)
    raise RuntimeError("golem did not stop: REAPER may be asking to save its project.")


# ── UN SEUL LANCEUR À LA FOIS (premier essai en VM Windows vierge, 2026-10-16) ─────────────────────────────────
# « Close the installer and open golem » lançait le golem ; l'utilisateur, ne voyant rien venir (le premier démarrage
# sur un Windows neuf est LONG : imports, Defender), le relançait par l'icône. Le second lanceur ne voyait pas encore
# de bridge, en démarrait un second, qui se heurtait au port OSC du premier — et les deux tombaient (« The golem bridge
# stopped »). Un verrou du SYSTÈME sur un fichier, tenu toute la vie du lanceur : le système le rend si le lanceur
# meurt, donc jamais de verrou périmé.
_LOCK = None
# le temps laissé au bridge pour répondre, processus vivant (premier démarrage d'une machine neuve compris)
BRIDGE_START_S = int(os.environ.get("GOLEM_BRIDGE_START_S", "300"))


def _launcher_lock():
    """Prend le verrou des lanceurs ; rend True si on l'a (premier lanceur), False si un autre le tient.
    Idempotent dans le processus : `restart()` le prend en attendant que l'ancien lanceur le rende, puis `start()`
    le redemande — sous Windows un second handle sur le même octet verrouillé échoue, même depuis le processus qui
    le tient."""
    global _LOCK
    if _LOCK is not None:
        return True
    path = resource_dir() / "GoleM" / "launcher.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _LOCK = f                                            # gardé ouvert : le verrou vit avec le processus
    return True


def _wait_other_launcher(port, seconds=None):
    """Un autre lanceur démarre le golem : attendre que son bridge réponde. Rend True s'il répond."""
    seconds = seconds if seconds is not None else BRIDGE_START_S + 60     # au moins le délai du premier lanceur
    for _ in range(int(seconds * 2)):
        if bridge_answers(port):
            return True
        time.sleep(0.5)
    return False


def start(shell="device", reset=False, fullscreen=False, window=True):
    """`window=False` = `golem server` (docs/installer.md §4) : le même GoleM, sans fenêtre — une tablette
    ou un téléphone est l'écran. Lancé alors que GoleM tourne : la fenêtre s'ouvre, ou l'adresse se redit."""
    python = venv_python()
    reaper = reaper_binary()
    if not python.exists():
        raise RuntimeError("golem is not set up yet; run first: python -m provision.desktop setup")
    port = int(os.environ.get("GOLEM_PORT", "8770"))
    # UN AUTRE LANCEUR DÉMARRE DÉJÀ LE GOLEM : on l'attend, puis on fait comme « déjà lancé » (la fenêtre, ou l'adresse)
    if not _launcher_lock():
        print("golem is already starting — waiting for it…")
        if not _wait_other_launcher(port):
            raise RuntimeError("golem is still starting (the first start on a new machine can take a few minutes). "
                               "Wait a moment, then open golem again.")
        if not window:
            _notify(server_message(port))
            return
        open_window(port, shell, reset, fullscreen)
        print(f"golem is already running: window opened on http://127.0.0.1:{port}/app/")
        return
    # EN TRAIN DE S'ARRÊTER : relancé pendant le ⏻, le lanceur ouvrait une fenêtre sur le bridge mourant et ne
    # démarrait rien — « Bridge link lost » jusqu'à une seconde relance (2026-10-10). On attend la fin.
    if (bridge_health(port) or {}).get("stopping"):
        print("golem is stopping — waiting for it to finish before starting again…")
        if not wait_stopped(port):
            raise RuntimeError("golem is still stopping (REAPER may be asking to save). Answer it, then start golem again.")
    # DÉJÀ LANCÉ : on ouvre la fenêtre, c'est tout — comme `golem desktop` sous Linux, dont le
    # start.sh ne relance rien. Le raccourci du bureau se clique deux fois ; la seconde ne doit pas
    # finir sur « port déjà utilisé ».
    if bridge_answers(port):
        if not window:
            _notify(server_message(port))
            return
        open_window(port, shell, reset, fullscreen)
        print(f"golem is already running: window opened on http://127.0.0.1:{port}/app/")
        return
    if not reaper.is_file():
        hint = (f"install it from {json.loads((ROOT / 'provision' / 'macos' / 'pins.json').read_text(encoding='utf-8'))['reaper']['url']} "
                "or set REAPER_BIN" if sys.platform == "darwin" else "set REAPER_BIN to its reaper.exe")
        raise RuntimeError(f"REAPER not found: {reaper} ({hint})")
    if reaper_running():
        raise RuntimeError("Close REAPER first: golem loads its scripts when REAPER starts.")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already in use by another program.")
    # Le script de télémétrie REAPER est copié dans son dossier de ressources.
    # Le rafraîchir à chaque lancement permet au bridge et à REAPER de lire le même contrat.
    copy_resources(resource_dir())
    from provision.capture_player import install_bundled as install_capture_player
    install_capture_player()
    # REAPER est fermé (vérifié plus haut) : ses masques MIDI se posent maintenant — la prise du
    # pédalier rendue au bridge, les claviers liés ouverts (bridge/desktop_midi.py)
    try:
        from bridge import desktop_midi
        desktop_midi.apply_reaper_masks(str(resource_dir()))
    except Exception as exc:
        print(f"REAPER MIDI settings not updated: {exc}")
    log_dir = resource_dir() / "GoleM" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.environ["GOLEM_DESKTOP_SESSION"] = uuid.uuid4().hex
    # OUVERT AU RÉSEAU (2026-10-03) : une tablette ou un téléphone rejoint GoleM comme sur le rack.
    # Sans danger de plus que le rack : le bridge n'accepte d'un appareil distant que ce qu'un appareil
    # APPAIRÉ peut faire (bridge/auth.py, QR d'invitation) ; le pare-feu de Windows n'ouvre le port que sur
    # les réseaux privés (install-system.ps1 -Firewall). GOLEM_BIND=127.0.0.1 referme.
    bind = os.environ.get("GOLEM_BIND", "0.0.0.0")
    with (log_dir / "bridge.log").open("a", encoding="utf-8") as log:
        bridge = subprocess.Popen([str(python), "-m", "uvicorn", "bridge.app:app",
                                   "--host", bind, "--port", str(port)],
                                  cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                  env={**os.environ, "PYTHONUTF8": "1",
                                       "GOLEM_DESKTOP_BACKEND": "1", "GOLEM_BIND": bind,
                                       "GOLEM_LAUNCH": "desktop" if window else "server"},
                                  # une console CACHÉE, héritée par tout ce que le bridge lance
                                  # (tasklist, powershell…) : sinon chacun ferait clignoter la sienne
                                  creationflags=NO_WINDOW)
    url = f"http://127.0.0.1:{port}/app/"
    try:
        # BORNÉ DANS LE TEMPS, PAS EN TOURS (VM Windows vierge, 2026-10-16) : un refus de connexion revient tout de
        # suite, donc « 100 tours » faisaient ~10 s — et le PREMIER démarrage d'un Windows neuf (imports, Defender,
        # presets d'usine posés) en prend bien plus. Le lanceur tuait un bridge en bonne santé et disait « did not
        # start ». Tant que le processus VIT, on attend (BRIDGE_START_S) ; on n'échoue tout de suite que s'il meurt.
        deadline = time.monotonic() + BRIDGE_START_S
        while True:
            if bridge.poll() is not None:
                raise RuntimeError(f"The golem bridge stopped; see {log_dir / 'bridge.log'}")
            try:
                with urllib.request.urlopen(url, timeout=1):
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if time.monotonic() > deadline:
                    raise RuntimeError(f"The golem bridge did not start within {BRIDGE_START_S} s; "
                                       f"see {log_dir / 'bridge.log'}")
                time.sleep(0.5)
        project = desktop_project()
        args = [str(reaper), "-nosplash"]
        if project.is_file():
            args.append(str(project))
        else:
            args.append("-new")
            print("No sets/golem-set.rpp yet: REAPER starts with a new empty project.")
        _bring_up(port, args, window, shell, reset, fullscreen)
        bridge.wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if bridge.poll() is None:
                bridge.terminate()
                bridge.wait(timeout=5)
        finally:
            if sys.platform in ("win32", "darwin"):      # REAPER réapparaît : ses questions de sauvegarde se voient
                from provision.desktop_window import set_reaper_windows_visible
                set_reaper_windows_visible(_backend_pids(), True)
            path = _backend_pids_file()
            if path is not None:
                path.unlink(missing_ok=True)


def server_message(port):
    """Ce qu'on dit en lançant `golem server` : l'adresse qui MARCHE (le nom s'il répond, sinon l'IP —
    /api/network/open-url), et un code d'appairage si aucun appareil principal n'existe encore."""
    def get(path, data=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read() or b"{}")
        except (OSError, ValueError):
            return {}
    for _ in range(40):                                  # le bridge vient peut-être de démarrer
        if bridge_answers(port):
            break
        time.sleep(0.5)
    url = get("/api/network/open-url").get("url") or f"http://<this computer>:{port}/app/"
    msg = f"golem is running without a window. On your tablet, open {url}"
    if not any(d.get("admin") for d in get("/api/auth/devices").get("devices") or []):
        code = get("/api/auth/pair-code", b"{}").get("code")
        if code:
            msg += f"\n\nFirst tablet: open {url.rstrip('/').removesuffix('/app')}/app/pair.html and type {code} (10 min, once)."
    return msg + "\n\nStop golem from your main tablet (System ▸ Dashboard) or with the 'Stop golem' shortcut."


def _notify(message):
    """Le message d'un GoleM SANS fenêtre : une boîte Windows, une notification macOS, la console sinon.
    GOLEM_NO_DIALOG (posé par l'installateur, 2026-11-03) : le lanceur n'a pas d'écran à qui parler — une boîte
    modale sous pythonw restait cachée derrière l'installateur et gardait le processus en vie jusqu'au clic OK."""
    if os.environ.get("GOLEM_NO_DIALOG"):
        print(message)
        return
    if sys.platform == "darwin":
        q = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        subprocess.run(["osascript", "-e", f'display notification "{q}" with title "golem server"'],
                       capture_output=True, timeout=10)
        print(message)
    elif sys.platform == "win32" and sys.stderr is None:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "golem server", 0x40)
    else:
        print(message)


# ── la boîte dédiée : `golem server` avec la session (docs/installer.md §4) ─────────────────────
# REAPER est une application à fenêtres : il lui faut une session ouverte. On le lance donc à
# l'OUVERTURE DE SESSION (dossier Démarrage de Windows, LaunchAgent de macOS) ; pour qu'une boîte
# démarre seule, l'utilisateur active l'ouverture de session automatique de son système — on ne la
# règle pas à sa place (il faudrait son mot de passe). Linux, lui, démarre sans session (linger).
def _startup_link():
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "golem server.lnk"


def _launch_agent():
    return Path.home() / "Library" / "LaunchAgents" / "fm.golem.server.plist"


def autostart(state="status"):
    """on | off | status. Rend la phrase d'état."""
    target = _startup_link() if sys.platform == "win32" else _launch_agent()
    if state == "status":
        return ("autostart: on — golem server starts when you sign in" if target.exists()
                else "autostart: off")
    if sys.platform == "win32" and state != "status":
        (target.parent / "GoleM Server.lnk").unlink(missing_ok=True)   # l'ancienne casse (NTFS l'ignore)
    if state == "off":
        target.unlink(missing_ok=True)
        return "autostart: off — golem no longer starts with your session"
    if sys.platform == "win32":
        pythonw = venv_python().with_name("pythonw.exe")
        q = lambda v: "'" + str(v).replace("'", "''") + "'"
        target.parent.mkdir(parents=True, exist_ok=True)
        script = (f"$s = New-Object -ComObject WScript.Shell; $l = $s.CreateShortcut({q(target)}); "
                  f"$l.TargetPath = {q(pythonw)}; $l.Arguments = '-m provision.desktop server'; "
                  f"$l.WorkingDirectory = {q(ROOT)}; $l.IconLocation = {q(str(ICON) + ',0')}; $l.Save()")
        out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        if out.returncode != 0:
            raise RuntimeError(f"Could not create the startup shortcut: {out.stderr.strip()}")
        # le reçu : le lien de démarrage (son nom est le nôtre : même déjà là, c'est un golem d'avant qui l'a posé)
        _record("add", str(target), "file", RECEIPT_BY, "golem")
        where = "Windows Settings ▸ Accounts ▸ Sign-in options"
    else:
        import plistlib
        target.parent.mkdir(parents=True, exist_ok=True)
        run = Path.home() / "Applications" / "golem server.app" / "Contents" / "MacOS" / "run"
        target.write_bytes(plistlib.dumps({"Label": "fm.golem.server", "ProgramArguments": [str(run)],
                                           "RunAtLoad": True}))
        where = "System Settings ▸ Users & Groups ▸ Automatically log in"
    return (f"autostart: on — golem server starts when you sign in. For a dedicated machine that starts "
            f"on its own, turn on automatic sign-in ({where}).")


def restart(shell="device"):
    """`restart` : après le passage à une release (Licenses ▸ GoleM). Lancé DÉTACHÉ par le bridge, qui va
    s'arrêter : on attend qu'il ait rendu sa réponse, on arrête tout, puis on relance comme le raccourci."""
    time.sleep(1.5)
    stop()
    port = int(os.environ.get("GOLEM_PORT", "8770"))
    for _ in range(60):                                  # le port libéré, REAPER vraiment fermé
        if not bridge_answers(port) and not reaper_running():
            break
        time.sleep(0.5)
    # … ET L'ANCIEN LANCEUR PARTI (2026-10-19). Il tient le verrou des lanceurs jusqu'à sa sortie, quelques
    # instants APRÈS que le port s'est tu : relancé trop tôt, `start()` le prenait pour « un autre lanceur qui
    # démarre » et attendait six minutes un bridge que personne ne lançait — mesuré à la pile (py-spy), golem
    # resté éteint après un `restart`. On attend le verrou ici ; `start()` le retrouve pris (idempotent).
    for _ in range(120):
        if _launcher_lock():
            break
        time.sleep(0.5)
    # le bridge qui nous lance nous passe son GOLEM_LAUNCH : un `golem server` revient server (sans fenêtre,
    # code d'appairage), pas desktop
    if os.environ.get("GOLEM_LAUNCH") == "server":
        start(window=False)
    else:
        start(shell)


def _tell(message, error=False):
    """Sous pythonw.exe (lancé par un raccourci) il n'y a pas de console : une erreur imprimée
    disparaîtrait, et l'icône « ne ferait rien ». On l'affiche dans une boîte Windows."""
    if sys.stderr is None and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "golem", 0x10 if error else 0x40)
    else:
        print(message, file=sys.stderr if error else sys.stdout)


def main():
    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("This launcher is for Windows and macOS; on Linux use provision/golem.")
    parser = argparse.ArgumentParser(description="Set up, start or stop golem on Windows and macOS.")
    parser.add_argument("command", choices=("setup", "start", "server", "stop", "restart", "shortcuts", "connect", "autostart"))
    parser.add_argument("state", nargs="?", choices=("on", "off", "status"), default="status",
                        help="autostart only: on | off | status")
    parser.add_argument("--shell", choices=tuple(SHELLS), default="device",
                        help="device: the tablet shell (default) · phone: the Companion · ui: a plain window")
    parser.add_argument("--reset", action="store_true", help="forget the window's remembered size and zoom")
    parser.add_argument("--fullscreen", action="store_true", help="browser full screen (F11 leaves it)")
    parser.add_argument("--dev", action="store_true", help="show REAPER (hidden by default)")
    args = parser.parse_args()
    if args.dev:
        os.environ["GOLEM_SHOW_REAPER"] = "1"
    try:
        if args.command == "setup":
            setup()
        elif args.command == "stop":
            stop()
        elif args.command == "restart":
            restart(args.shell)
        elif args.command == "connect":
            # les secrets arrivent par l'entrée standard, jamais sur la ligne de commande (visible de tous)
            raw = (sys.stdin.read() if sys.stdin and not sys.stdin.isatty() else "").lstrip("\ufeff")
            print(json.dumps(connect(json.loads(raw) if raw.strip() else {})))
        elif args.command == "server":
            start(window=False)
        elif args.command == "autostart":
            _tell(autostart(args.state))
        elif args.command == "shortcuts":
            for path in install_shortcuts():
                print(f"shortcut {path}")
        else:
            start(args.shell, args.reset, args.fullscreen)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        _tell(str(exc), error=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
