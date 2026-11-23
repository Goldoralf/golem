# SPDX-License-Identifier: GPL-3.0-or-later
"""Le Golem Engine (construit depuis Ardour) derrière le contrat (docs/ardour-plan.md §2, lot A1.4).

Même forme que REAPER, mesurée au spike A1.4 :
  - commandes : le MÊME slot presets/.command.json + accusé (commands.enqueue), lu par le veilleur Lua du moteur
    (golem-engine/golem/engine/golem_watch.lua) ;
  - chemin rapide : la surface OSC d'Ardour (port 3819). Elle écrit la valeur BRUTE d'un paramètre de plugin : la
    valeur normalisée du bridge est convertie avec la plage publiée par le moteur (`load_ranges`) ; sans plage
    connue, on refuse plutôt que d'écrire n'importe quoi ;
  - télémétrie : le retour OSC d'Ardour est TRADUIT dans le vocabulaire que le bridge lit déjà (/track/N/vu,
    /track/N/mute) : app.on_osc ne sait pas quel moteur parle ;
  - process : `luasession` lancé par golem/engine/run.sh, qui écrit son PID dans presets/.engine.pid.
Ce lot ne sait que ping et status : le reste du vocabulaire arrive avec A2/A3.
"""
import contextlib
import json
import logging
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .. import config as C
from .base import EngineAdapter

log = logging.getLogger("golem.engine")

def _proc_names(pid):
    """Les noms (argv[0], argv[1]) du process `pid`, [] s'il n'existe pas ou n'est plus qu'un zombie. Linux : /proc ;
    macOS : `ps` ; Windows : `tasklist` (le nom de l'image seul)."""
    if os.path.isdir("/proc"):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().split(b"\0")
            with open(f"/proc/{pid}/stat") as f:
                if f.read().rsplit(")", 1)[-1].split()[0] == "Z":
                    return []
        except (OSError, ValueError, IndexError):
            return []
        return [os.path.basename(c.decode("utf-8", "replace")) for c in cmd if c]
    try:
        if sys.platform == "win32":
            # en OCTETS, décodés ici (2026-11-19) : la sortie de tasklist suit la page de code de la console (« 483 260 Ko »
            # avec une espace insécable) ; en texte sous PYTHONUTF8=1 le décodage échouait et stdout valait None
            raw = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True,
                                 timeout=5).stdout or b""
            out = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "mbcs", errors="replace").strip()
            name = out.split(",")[0].strip('"') if out.startswith('"') else ""
            return [os.path.splitext(name)[0]] if name else []
        out = subprocess.run(["ps", "-p", str(int(pid)), "-o", "stat=,comm="], capture_output=True, text=True, timeout=5).stdout.strip()
        if not out or out.split()[0].startswith("Z"):
            return []
        return [os.path.basename(out.split(None, 1)[1])] if len(out.split(None, 1)) > 1 else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def _engine_dir():
    """GOLEM_ENGINE_DIR, sinon un arbre de dev (~/golem-engine), sinon le paquet installé (~/opt/golem-engine) — la
    même règle que provision/golem_engine.py engine_dir et provision/lib-engine.sh (docs/install-v2.md §1)."""
    if os.environ.get("GOLEM_ENGINE_DIR"):
        return os.environ["GOLEM_ENGINE_DIR"]
    cands = [os.path.expanduser("~/golem-engine"), os.path.expanduser("~/opt/golem-engine")]
    return next((c for c in cands if os.path.isfile(os.path.join(c, "golem", "engine", "run.sh"))), cands[0])


ENGINE_DIR = _engine_dir()
OSC_PORT = int(os.environ.get("GOLEM_ENGINE_OSC", "3819"))
def card_device():
    """Le nom de la carte ACTIVE de golem (config/cards/<carte>.json, la même que REAPER ouvre) — le veilleur la retrouve
    parmi les périphériques ALSA d'Ardour par un nom contenu dans l'autre. None si aucune carte n'est connue.
    WINDOWS (2026-11-20) : pas de config/cards — la carte est le PILOTE ASIO réglé dans Settings ▸ Audio (le reaper.ini
    de golem, `asio_driver_name` en mode ASIO) ; le veilleur choisit le pilote « ASIO » de PortAudio et y retrouve ce
    nom. Un autre mode audio (WASAPI…) : None, le moteur reste sur le pilote factice plutôt que de deviner."""
    if sys.platform == "win32":
        try:
            from .. import desktop_audio as DA
            audio = DA._values(DA._read_ini(Path(C.reaper_resource_dir()) / "reaper.ini"), "audioconfig")
            return (audio.get("asio_driver_name") or "").strip('"') or None if audio.get("mode") == "3" else None
        except Exception:
            return None
    try:
        with open(os.path.join(C.ROOT, "config", "cards", f"{C.alsa_card()}.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("name") or None
    except (OSError, ValueError, AttributeError):
        return None


def card_buffer():
    """Le buffer que golem demande à la carte, quand il en demande un : Windows (2026-11-20), celui de Settings ▸ Audio
    (`asio_bsize` du reaper.ini de golem, s'il est demandé : `asio_bsize_use`). Le veilleur le prend si le moteur n'a
    pas son propre réglage (config/golem-engine.json, le Dashboard) — sans lui, PortAudio ouvrait l'ASIO à 1024
    échantillons, plus de 20 ms par sens. None ailleurs (ALSA : le réglage du moteur)."""
    if sys.platform != "win32":
        return None
    try:
        from .. import desktop_audio as DA
        audio = DA._values(DA._read_ini(Path(C.reaper_resource_dir()) / "reaper.ini"), "audioconfig")
        if audio.get("mode") == "3" and audio.get("asio_bsize_use") == "1":
            return int(audio.get("asio_bsize") or 0) or None
    except Exception:
        pass
    return None


# la carte de golem en ALSA par défaut ; sans carte connue (un banc, une machine neuve) : le pilote factice, sans son
DEVICE = os.environ.get("GOLEM_ENGINE_DEVICE", card_device() or "")
BACKEND = os.environ.get("GOLEM_ENGINE_BACKEND", ("PortAudio (default)" if sys.platform == "win32" else "ALSA")
                         if DEVICE else "None (Dummy)")
# la session vit DANS golem (sets/, état local comme sets/golem-set.rpp) : rien hors de l'install
SESSION_DIR = os.environ.get("GOLEM_ENGINE_SESSION", os.path.join(C.ROOT, "sets", "golem-engine"))
RUN_LOG = os.environ.get("GOLEM_ENGINE_LOG") or os.path.join("/tmp" if os.path.isdir("/tmp") else __import__("tempfile").gettempdir(),
                                                           "golem-engine.log")

# retour demandé à la surface : boutons (mute) + niveaux + vumètre en dB (bits 0, 1, 7 de /set_surface/feedback)
FEEDBACK = 1 | 2 | 128
STRIP_TYPES = 1 | 2 | 4          # pistes audio, pistes MIDI, bus audio : l'ordre des strips = celui du livemap
# « start » = revenir à ZÉRO : /goto_start irait au début de la PLAGE de la session, qu'une prise faite au milieu d'une
# chanson a posée là où elle a commencé (mesuré 2026-11-17 : retour à 101 s) — /locate nomme l'échantillon 0
_TRANSPORT = {"play": ("/transport_play", []), "pause": ("/transport_stop", []), "stop": ("/transport_stop", []),
              "start": ("/locate", [0, 0])}


def pid_file():
    return os.path.join(C.PRESETS_DIR, ".engine.pid")


def db_to_vu(db):
    """Vumètre d'Ardour (dB, -193 = silence) -> l'échelle du bridge, 1,0 = 0 dBFS (contrôle d'écrêtage d'app.on_osc)."""
    return 0.0 if db <= -120 else 10 ** (db / 20.0)


def _bpm(cmd):
    """Le TEMPO du morceau, comme golem_rig.lua le pose sur REAPER (SetCurrentBPM) : celui de la ligne de setlist
    (`cmd.bpm`), sinon celui du preset (presets/<id>.json) — les delays et trémolos synchronisés suivent l'hôte."""
    try:
        b = float(cmd.get("bpm"))
        if 20 <= b <= 400:
            return b
    except (TypeError, ValueError):
        pass
    try:                                       # le nom tel que golem_rig le lit : l'id brut de la commande
        with open(os.path.join(C.PRESETS_DIR, f"{cmd.get('preset')}.json"), encoding="utf-8") as f:
            b = float((json.load(f) or {}).get("bpm"))
        return b if 20 <= b <= 400 else None
    except (OSError, ValueError, TypeError):
        return None


def _win_documents():
    """Le dossier Documents tel que Windows le dit (CSIDL_PERSONAL, comme Ardour) : il peut être déplacé (OneDrive,
    autre disque) — ~/Documents n'est qu'un repli."""
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    with contextlib.suppress(Exception):
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # CSIDL_PERSONAL
            return buf.value
    return os.path.join(os.path.expanduser("~"), "Documents")


def preset_dir(vendor, name):
    """Le dossier où Ardour cherche les presets VST3 d'un plugin (VST3PluginInfo::preset_search_path, le premier : celui
    de l'utilisateur, où il écrit). Il dépend du système : sous Windows le bridge cherchait le chemin Linux, ne trouvait
    jamais l'état qu'un plugin hébergé venait de rendre, et le son de Vital n'arrivait pas au moteur (2026-11-19)."""
    if sys.platform == "win32":
        return os.path.join(_win_documents(), "VST3 Presets", vendor, name)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Audio", "Presets", vendor, name)
    return os.path.join(os.path.expanduser("~"), ".vst3", "presets", vendor, name)


def vstpreset(uid, component, controller=b""):
    """Un fichier .vstpreset (format du SDK VST3) : en-tête « VST3 », version, identifiant de classe (32 caractères),
    position de la liste ; l'état du composant, puis celui du contrôleur s'il y en a un ; la liste (« List », une
    entrée « Comp », et « Cont »)."""
    import struct
    data = component + controller
    head = b"VST3" + struct.pack("<i", 1) + uid.encode("ascii") + struct.pack("<q", 48 + len(data))
    entries = [b"Comp" + struct.pack("<qq", 48, len(component))]
    if controller:
        entries.append(b"Cont" + struct.pack("<qq", 48 + len(component), len(controller)))
    return head + data + b"List" + struct.pack("<i", len(entries)) + b"".join(entries)


def read_vstpreset(data):
    """(identifiant de classe, état du composant, état du contrôleur) d'un fichier .vstpreset. Lève ValueError."""
    import struct
    if len(data) < 48 or data[:4] != b"VST3":
        raise ValueError("not a VST3 preset")
    uid, pos = data[8:40].decode("ascii", "replace"), struct.unpack("<q", data[40:48])[0]
    if pos < 48 or pos + 8 > len(data) or data[pos:pos + 4] != b"List":
        raise ValueError("VST3 preset without a chunk list")
    n = struct.unpack("<i", data[pos + 4:pos + 8])[0]
    parts = {}
    for k in range(max(0, min(n, 16))):
        e = data[pos + 8 + k * 20:pos + 28 + k * 20]
        if len(e) == 20:
            off, size = struct.unpack("<qq", e[4:])
            parts[e[:4]] = data[off:off + size]
    return uid, parts.get(b"Comp", b""), parts.get(b"Cont", b"")


# L'ÉTAT D'UN PLUGIN VST3 TEL QUE REAPER LE RANGE (`vst_chunk`, ce que porte un bloc VST Host) : la taille de l'état du
# composant, un 1, l'état ; puis la taille de l'état du contrôleur, un 0, l'état. Vérifié sur les états de Vital que
# le compileur greffe (118 fichiers, 2026-11-17) ; un état qui n'a pas cette forme est refusé, jamais deviné.
def reaper_vst3_parts(raw):
    import struct
    if len(raw) < 16:
        return None
    n = struct.unpack("<I", raw[:4])[0]
    if 8 + n + 8 > len(raw):
        return None
    m = struct.unpack("<I", raw[8 + n:12 + n])[0]
    if 16 + n + m != len(raw):
        return None
    return raw[8:8 + n], raw[16 + n:16 + n + m]


def reaper_vst3_chunk(component, controller=b""):
    import struct
    return struct.pack("<II", len(component), 1) + component + struct.pack("<II", len(controller), 0) + controller


def _legal(name):
    """Comme ARDOUR::legalize_for_universal_path : le nom d'un dossier de presets."""
    out = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in str(name or ""))
    return out.rstrip(" .")


def host_plugin_info(name, presets_dir=None):
    """{ident, vendor, pname} du plugin que l'inventaire du moteur nomme `name` (presets/.vst-host-list.json, écrit par
    le veilleur au démarrage et à chaque inventaire), ou None."""
    try:
        with open(os.path.join(presets_dir or C.PRESETS_DIR, ".vst-host-list.json"), encoding="utf-8") as f:
            rows = (json.load(f) or {}).get("plugins") or []
    except (OSError, ValueError):
        return None
    return next((r for r in rows if r.get("name") == name and r.get("ident")), None)


def write_host_states(plan, presets_dir=None):
    """L'ÉTAT NATIF d'un bloc VST Host (capturé sous REAPER ou ici : `_vst_chunk`), écrit comme preset VST3 là où le
    moteur le lira — « golem-<bloc> » dans le dossier de presets du plugin — et donné au bloc comme son `preset`. Un
    état qui n'est pas celui d'un VST3, ou un plugin que l'inventaire ne connaît pas : dit, le plugin garde son état
    par défaut."""
    import base64
    import hashlib
    from .. import store
    for tr in plan.get("tracks") or []:
        for b in tr.get("blocks") or []:
            hs = b.pop("host_state", None)
            if not hs:
                continue
            try:
                parts = reaper_vst3_parts(base64.b64decode(hs["chunk"]))
                info = host_plugin_info(hs["plugin"], presets_dir)
                if not parts or not info:
                    raise ValueError("not a VST3 state" if not parts else "plugin not in the engine's inventory")
                name = "golem-" + store._safe_id(str(b.get("id") or "host"))
                d = preset_dir(_legal(info.get("vendor")), _legal(info.get("pname")))
                os.makedirs(d, exist_ok=True)
                data = vstpreset(info["ident"], *parts)
                path = os.path.join(d, name + ".vstpreset")
                try:
                    with open(path, "rb") as f:
                        same = f.read() == data
                except OSError:
                    same = False
                if not same:
                    tmp = path + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, path)
                b["preset"] = {"uri": f"VST3-S:{info['ident']}:{name}", "sig": hashlib.sha1(data).hexdigest()[:16]}
            except (OSError, ValueError, KeyError) as e:
                log.warning(f"ardour : état de {b.get('id')} non chargé ({e}) — le plugin garde son état par défaut")


def host_state_chunk(data):
    """La réponse `vst_state` du veilleur -> l'état au format du patch (`vst_chunk`, celui de REAPER : un patch passe
    d'un moteur à l'autre). Lit le preset que le moteur vient d'écrire, puis le retire. Lève ValueError."""
    import base64
    path = os.path.join(preset_dir(_legal(data.get("vendor")), _legal(data.get("pname"))), _legal(data.get("preset_label")) + ".vstpreset")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError(f"the engine's state file is missing ({e})") from e
    finally:
        try:
            os.remove(path)
        except OSError as e:
            log.warning(f"ardour : état VST3 lu mais non retiré ({e})")
    _uid, comp, ctrl = read_vstpreset(raw)
    if not comp:
        raise ValueError("the plugin gave an empty state")
    return base64.b64encode(reaper_vst3_chunk(comp, ctrl)).decode("ascii")


def write_presets(plan, chunk_dir=None):
    """L'ÉTAT des synthés du plan (le son de Vital), écrit comme preset VST3 là où le moteur le lira : le compileur a
    greffé le .vital dans un état REAPER (`vst_chunk` : 8 octets d'en-tête, l'état du composant, 8 octets de fin) ; on
    en garde le composant. Un fichier par bloc (« golem-<bloc> »), réécrit quand le son change ; le plan ne garde que
    son adresse et son empreinte. Un état illisible est dit et retiré : le synthé joue son son par défaut."""
    import base64
    import hashlib
    from .. import store
    from ..compile_rig import OUT_DIR
    for tr in plan.get("tracks") or []:
        for b in tr.get("blocks") or []:
            pr = b.get("preset")
            if not pr or "chunk" not in pr:
                continue
            try:
                with open(os.path.join(chunk_dir or OUT_DIR, pr["chunk"]), encoding="ascii") as f:
                    comp = base64.b64decode(f.read().strip())[8:-8]
                name = "golem-" + store._safe_id(str(b.get("id") or "synth"))
                d = preset_dir(pr["vendor"], pr["name"])
                os.makedirs(d, exist_ok=True)
                path, sig = os.path.join(d, name + ".vstpreset"), hashlib.sha1(comp).hexdigest()[:16]
                data = vstpreset(pr["uid"], comp)
                try:
                    same = open(path, "rb").read() == data
                except OSError:
                    same = False
                if not same:
                    tmp = path + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, path)
                b["preset"] = {"uri": f"VST3-S:{pr['uid']}:{name}", "sig": sig}
            except (OSError, ValueError) as e:
                log.warning(f"ardour : état de {b.get('id')} non écrit ({e}) — le plugin garde son son par défaut")
                b.pop("preset", None)


def write_captures(plan):
    """Le fichier d'une CAPTURE PILOTABLE tel que son lecteur LV2 le lit : le compileur garde l'état en base64 (la forme
    que REAPER greffe dans son projet) ; le LV2 lit du JSON. Décodé une fois, à côté, sous le même nom ; le bloc le
    reçoit comme n'importe quel fichier (`files`). Un état illisible est dit, et le bloc reste sans capture (muet)."""
    import base64
    for tr in plan.get("tracks") or []:
        for b in tr.get("blocks") or []:
            cap = b.pop("capture", None)
            if not cap:
                continue
            try:
                out = os.path.splitext(cap["chunk"])[0] + ".json"
                if not os.path.isfile(out):
                    with open(cap["chunk"], "rb") as f:
                        data = base64.b64decode(f.read())
                    json.loads(data)
                    tmp = out + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, out)
                b.setdefault("files", {})[cap["prop"]] = out
            except (OSError, ValueError) as e:
                log.warning(f"ardour : capture de {b.get('id')} illisible ({e}) — bloc sans capture")


def write_content(plan, preset_id, out_dir=None):
    """Les FICHIERS que le plan a composés (le kit de pads en SFZ) : écrits à côté du plan compilé, puis donnés au
    plugin comme n'importe quel fichier du bloc (`files`)."""
    from ..compile_rig import OUT_DIR, file_stem
    for tr in plan.get("tracks") or []:
        for b in tr.get("blocks") or []:
            w = b.pop("write", None)
            if not w:
                continue
            path = os.path.join(out_dir or OUT_DIR, f"{file_stem(preset_id or 'preset')}__{w['name']}")
            try:
                try:
                    same = open(path, encoding="utf-8").read() == w["text"]
                except OSError:
                    same = False
                if not same:
                    with open(path + ".tmp", "w", encoding="utf-8") as f:
                        f.write(w["text"])
                    os.replace(path + ".tmp", path)
                b.setdefault("files", {})[w["prop"]] = path
            except OSError as e:
                log.warning(f"ardour : fichier de {b.get('id')} non écrit ({e})")


def drums_play(cmd, root=None, out_dir=None):
    """Le `play` de la boîte à rythmes TEL QUE LE VEILLEUR L'EXÉCUTE (bridge/engine/drum_bank.py) : la banque des grooves
    et des fills déjà dépliée en événements, et le plugin du kit (son fichier SFZ écrit au besoin). Sous REAPER,
    golem_drums.lua lit lui-même les .mid et le descripteur du kit ; ici le veilleur ne lit rien."""
    from . import ardour_plan, drum_bank
    root = root or C.ROOT
    bank, skipped = drum_bank.bank(root, cmd.get("patterns"), cmd.get("fills"), cmd.get("notemap"))
    for s in skipped:
        log.warning(f"ardour : boîte à rythmes — {s}")
    try:
        avl = (ardour_plan.load_table().get("drumkit") or {}).get("avldrums") or {}
    except (OSError, ValueError):
        avl = {}
    kit, why = drum_bank.kit_plugin(root, cmd.get("kit"), avl)
    out = {**cmd, "bank": bank}
    if kit:
        plan = {"tracks": [{"blocks": [dict(kit, id="drums-kit")]}]}
        write_content(plan, "drum-machine", out_dir=out_dir)
        k = plan["tracks"][0]["blocks"][0]
        out["kit_plugin"] = {"lv2": k["lv2"], "files": k.get("files") or {}}
    else:
        log.warning(f"ardour : boîte à rythmes — {why}")
        out["kit_error"] = why
    return out


def standard_instruments(root=None):
    """Les fichiers des instruments d'un standard (le piano, la pompe), en chemins ABSOLUS de ce dépôt : le veilleur les
    donne à sfizz tels quels. Mêmes fichiers que sous REAPER (reaper/Scripts/golem_chordseq.lua)."""
    sfz = os.path.join(root or C.ROOT, "library", "sfz")
    return {"piano": os.path.join(sfz, "SalamanderGrandPiano-SFZ+FLAC-V3+20200602", "SalamanderGrandPiano-V3+20200602.sfz"),
            "guitar": os.path.join(sfz, "golem-pompe.sfz")}


_DURATIONS = {}


def audio_seconds(path):
    """La durée d'un fichier audio (s), gardée en mémoire par fichier : c'est elle qui dit au moteur quand un sample
    lancé a fini. Un WAV se lit à son en-tête ; les autres formats par ffprobe. Inconnue : 30 s (la note est relâchée
    après, sans conséquence pour un son déjà fini)."""
    try:
        key = (path, os.path.getmtime(path), os.path.getsize(path))
    except OSError:
        return 0.0
    if key in _DURATIONS:
        return _DURATIONS[key]
    dur = None
    try:
        import wave
        with wave.open(path, "rb") as w:
            dur = w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        with contextlib.suppress(Exception):
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                               capture_output=True, text=True, timeout=10)
            dur = float(r.stdout.strip())
    _DURATIONS[key] = round(dur + 0.1, 3) if dur else 30.0
    return _DURATIONS[key]


def sample_play(cmd, root=None):
    """Le `play` d'un sample TEL QUE LE VEILLEUR LE JOUE : les fichiers du bloc en chemins absolus (`files`, dans
    l'ordre de `samples` : les index ne bougent pas) et leurs durées (`durs`)."""
    root = root or C.ROOT
    files = [p if os.path.isabs(p) else os.path.join(root, p) for p in (cmd.get("samples") or [])]
    return {**cmd, "files": files, "durs": [audio_seconds(f) for f in files]}


SIX_STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")
BACKING_CACHE = os.path.join(C.ROOT, "assets", ".cache", "backing-wav")
BACKING_KEEP = 4                          # chansons gardées décodées (≈ 100 Mo par stem de 5 minutes)


def backing_load(cmd, rate=48000, cache_dir=None, ffmpeg="ffmpeg"):
    """Le `load` d'une backing TEL QUE LE MOTEUR LE JOUE BIEN : chaque stem décodé UNE fois en WAV à la fréquence du
    moteur, dans un cache, et la commande nomme ces fichiers (`files`).

    Ardour sait lire un mp3 posé sur une piste, mais s'y PLACER lui coûte un décodage depuis le début (mesuré
    2026-11-17 : la lecture ne part qu'au troisième essai, un seek ou une boucle traînent) ; REAPER indexe ses mp3.
    Un WAV à la fréquence de la session se lit et se parcourt instantanément. Les décodages se font en parallèle
    (quelques dixièmes de seconde par stem), un fichier déjà décodé est repris, et le cache ne garde que les
    dernières chansons. Un stem qu'on ne peut pas décoder est laissé tel quel : le moteur le lira lentement."""
    import concurrent.futures
    import hashlib
    cache = cache_dir or BACKING_CACHE
    src = dict(cmd.get("files") or {})
    if not src and cmd.get("dir"):
        src = {n: os.path.join(cmd["dir"], n + ".mp3") for n in SIX_STEMS}
    src = {n: p for n, p in src.items() if p and os.path.isfile(p)}
    if not src:
        return cmd
    key = hashlib.sha1(("|".join(f"{n}={p}:{os.path.getmtime(p):.0f}:{os.path.getsize(p)}" for n, p in sorted(src.items()))
                        + f"@{rate}").encode()).hexdigest()[:16]
    out_dir = os.path.join(cache, key)
    os.makedirs(out_dir, exist_ok=True)

    def decode(item):
        name, path = item
        wav = os.path.join(out_dir, name + ".wav")
        if os.path.isfile(wav) and os.path.getsize(wav) > 44:
            return name, wav
        tmp = wav + ".part.wav"
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-ar", str(rate), "-c:a", "pcm_s16le", tmp],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(tmp):
            log.warning(f"ardour : stem {name} non décodé ({(r.stderr or '').strip()[-120:]}) — lu tel quel")
            return name, path
        os.replace(tmp, wav)
        return name, wav

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        files = dict(ex.map(decode, src.items()))
    os.utime(out_dir, None)                              # la chanson qu'on vient de charger est la plus récente
    with contextlib.suppress(OSError):                   # le cache ne garde que les dernières chansons
        import shutil
        songs = sorted((d for d in (os.path.join(cache, x) for x in os.listdir(cache)) if os.path.isdir(d)),
                       key=os.path.getmtime, reverse=True)
        for old in songs[BACKING_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
    log.info(f"ardour : backing {cmd.get('slug')} — {len(files)} stem(s) prêts en {time.time() - t0:.1f} s")
    out = {k: v for k, v in cmd.items() if k != "dir"}
    out["files"] = files
    return out


def _console_python():
    """Le Python qui lance run.py. Sous Windows, jamais pythonw.exe (celui de `golem desktop`) : programme sans
    console, il ne peut pas en porter une cachée — le moteur qu'il lance ouvrirait la sienne, visible."""
    exe = sys.executable
    if sys.platform == "win32" and os.path.basename(exe).lower() == "pythonw.exe":
        con = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(con):
            return con
    return exe


class ArdourEngine(EngineAdapter):
    id = "ardour"
    actions = frozenset({"ping", "status", "rig_recall", "scene_apply", "stomp", "rig_verify", "dump", "audio_set",
                         "plugins", "snapshot", "gapmeter", "dspstats", "mixer_apply", "peaks", "audio_reset",
                         "midi_reinit", "midi_send", "perf_rec", "click", "drums",
                         "standard", "tuner", "extstate", "backing",
                         "preview", "sample", "sample_preview",
                         "vst_list", "vst_params", "vst_state", "capture_params"})
    # le moteur, tel que le système nomme son process : `luasession` (Linux), `ardour9-lua` (le build Windows de
    # golem/tools/win-build.sh, 2026-11-19 — tasklist rend le nom de l'image sans .exe)
    PROC_NAMES = ("luasession", "ardour9-lua")

    def __init__(self, link=None):
        self._link = link
        self._on_message = None
        self._ranges = {}            # (track, fx, param) -> (lower, upper, logarithmic)
        self._said_range = set()
        self._looper_addr = {}

    # ── commandes : le slot de toujours ──────────────────────────────────────────────────
    def _send(self, cmd):
        """Un rappel ou une scène emporte son plan MOTEUR dans la commande (bridge/engine/ardour_plan.py) : une scène
        en file ne peut pas écraser le plan d'un rappel pas encore lu, et l'écriture reste celle, atomique, du slot."""
        from .. import commands
        if cmd.get("action") in ("rig_recall", "scene_apply"):
            from . import ardour_plan
            try:
                with open(ardour_plan.rig_path(cmd.get("preset")), encoding="utf-8") as f:
                    plan = ardour_plan.build(json.load(f))
            except (OSError, ValueError) as e:
                log.error(f"ardour : plan compilé illisible pour {cmd.get('preset')} ({e}) — commande non envoyée")
                return None
            for s in plan["skipped"]:
                log.info(f"ardour : {s.get('id') or s.get('path')} {s.get('type') or ''} {s.get('param') or ''} — {s['why']}")
            plan["bpm"] = _bpm(cmd)
            from .. import mixer
            plan["mixer"] = mixer.levels()             # les trims du rig, reposés à chaque rappel (docs/mixer.md)
            write_presets(plan)
            write_captures(plan)
            write_host_states(plan)
            write_content(plan, cmd.get("preset"))
            cmd = {**cmd, "plan": plan}
        if cmd.get("action") == "drums" and cmd.get("op") in ("play", "load"):
            cmd = drums_play(cmd)                        # `load` : le kit seul (le rendu d'un bloc) — la banque est vide
        if cmd.get("action") == "sample" and cmd.get("op") == "play":
            cmd = sample_play(cmd)
        if cmd.get("action") == "sample_preview" and cmd.get("file"):
            cmd = {**cmd, "dur": audio_seconds(cmd["file"])}
        if cmd.get("action") == "backing" and cmd.get("op") == "load":
            cmd = backing_load(cmd, rate=int((self.audio() or {}).get("sample_rate") or 48000))
        if cmd.get("action") == "standard" and cmd.get("op") in ("play", "load"):
            cmd = {**cmd, "instruments": standard_instruments()}
        if cmd.get("action") in ("perf_rec", "preview") and (cmd.get("on") or cmd.get("action") == "preview"):
            # l'ASSEMBLEUR de la prise (bridge/engine/take_finalize.py) : le veilleur le lance à l'arrêt, avec CE Python
            import sys
            from . import take_finalize
            cmd = {**cmd, "finalizer": [sys.executable, os.path.abspath(take_finalize.__file__)]}
        return commands.enqueue(cmd)

    # ── lien OSC ─────────────────────────────────────────────────────────────────────────
    @property
    def link(self):
        if self._link is None:
            from ..reaper_osc import ReaperLink       # un lien UDP générique : envoi + écoute locale
            self._link = ReaperLink("127.0.0.1", OSC_PORT, C.BRIDGE_OSC_RECV_PORT, self._dispatch)
        return self._link

    def _dispatch(self, address, args):
        """Traduit le retour d'Ardour dans le vocabulaire du bridge."""
        if not self._on_message:
            return
        try:
            if address == "/strip/meter" and len(args) >= 2:
                return self._on_message(f"/track/{int(args[0])}/vu", (db_to_vu(float(args[1])),))
            if address == "/strip/mute" and len(args) >= 2:
                return self._on_message(f"/track/{int(args[0])}/mute", (float(args[1]),))
        except (TypeError, ValueError):
            return
        self._on_message(address, args)

    def start_feedback(self, on_message):
        self._on_message = on_message
        self.link.start()
        self.register_surface()

    def register_surface(self):
        """Dit à la surface où renvoyer son retour (port d'écoute du bridge) et quoi renvoyer. À refaire après chaque
        démarrage du moteur : la surface oublie ses clients."""
        lk = self.link
        lk.send("/set_surface/port", C.BRIDGE_OSC_RECV_PORT)
        lk.send("/set_surface/strip_types", STRIP_TYPES)
        lk.send("/set_surface/feedback", FEEDBACK)
        return True

    def stop_feedback(self):
        if self._link:
            self._link.stop()

    def talking(self):
        """La surface d'Ardour ne parle qu'à un changement : le battement du veilleur (presets/.engine-status.json,
        réécrit toutes les 2 s) dit qu'il lit ses commandes."""
        if self.pid() is None:
            return False
        try:
            return time.time() - os.stat(os.path.join(C.PRESETS_DIR, ".engine-status.json")).st_mtime < 6.0
        except OSError:
            return False

    def engine_started(self):
        if self._on_message:                         # le bridge écoute déjà : se réabonner auprès de la nouvelle surface
            self.register_surface()
        self.request_inventory()

    def request_inventory(self):
        """Demande au moteur lesquels des plugins de sa table sont installés (presets/.engine-plugins.json)."""
        from . import ardour_plan
        try:
            table = ardour_plan.load_table()
        except (OSError, ValueError):
            return None
        want = [{"type": t, **ardour_plan.plugin_of(e)} for t, e in table.items()]
        return self.send({"action": "plugins", "want": want})

    def inventory(self):
        """{at, found: {type: bool}, n, total} — None tant que le moteur n'a pas répondu."""
        try:
            with open(os.path.join(C.PRESETS_DIR, ".engine-plugins.json"), encoding="utf-8") as f:
                return json.load(f) or None
        except (OSError, ValueError):
            return None

    def missing_plugin(self, block_type):
        """Le type est dans la table mais son plugin n'est pas installé ici (inventaire du moteur)."""
        inv = self.inventory()
        return bool(inv) and (inv.get("found") or {}).get(block_type) is False

    # ── chemin rapide ────────────────────────────────────────────────────────────────────
    def load_ranges(self, ranges):
        """[{track, fx, param, lower, upper, log?}] — publiées par le moteur avec le livemap."""
        self._ranges = {(r["track"], r["fx"], r["param"]): (float(r["lower"]), float(r["upper"]), bool(r.get("log")))
                        for r in ranges or [] if {"track", "fx", "param", "lower", "upper"} <= set(r)}

    _lm = {"mtime": None, "ranges": {}}

    def _livemap_ranges(self):
        """(track, fx, p) -> (pmin, pmax, False), relu quand le livemap change (le moteur le réécrit à chaque rebuild)."""
        path = os.path.join(C.PRESETS_DIR, ".livemap.json")
        try:
            m = os.stat(path).st_mtime_ns
        except OSError:
            return {}
        if m != self._lm["mtime"]:
            rng = {}
            try:
                with open(path, encoding="utf-8") as f:
                    lm = json.load(f) or {}
                for b in (lm.get("blocks") or {}).values():
                    for pm in (b.get("params") or {}).values():
                        rng[(b.get("track"), b.get("fx"), pm.get("p"))] = (float(pm["pmin"]), float(pm["pmax"]), False)
            except (OSError, ValueError, KeyError, TypeError):
                rng = {}
            self._lm = {"mtime": m, "ranges": rng}
        return self._lm["ranges"]

    # les paramètres du looper, dans l'ordre des sliders de golem_super8 (bridge/looper.py les adresse par décalage
    # depuis « GoleM Cmd ») : commande, tempo, mode, niveau des quatre boucles, niveau de toutes
    LOOPER_RANGES = ((0, 16383), (0, 400), (0, 999), (-60, 0), (-60, 0), (-60, 0), (-60, 0), (0, 1))

    def _looper_range(self, track, fx, param):
        """La plage d'un paramètre du looper, s'il est adressé là où le veilleur l'a publié (presets/.looper.json)."""
        try:
            m = os.path.getmtime(C.LOOPER_FILE)
            if self._looper_addr.get("mtime") != m:
                with open(C.LOOPER_FILE, encoding="utf-8") as f:
                    d = json.load(f)
                self._looper_addr = {"mtime": m, "track": d.get("track"), "fx": d.get("fx"), "p0": d.get("cmd_param") or 0}
        except (OSError, ValueError):
            return None
        a = self._looper_addr
        i = param - a["p0"]
        if track == a["track"] and fx == a["fx"] and 0 <= i < len(self.LOOPER_RANGES):
            return (*self.LOOPER_RANGES[i], False)
        return None

    def raw_value(self, track, fx, param, norm):
        rng = (self._ranges.get((track, fx, param)) or self._livemap_ranges().get((track, fx, param))
               or self._looper_range(track, fx, param))
        if rng is None:
            return None
        lo, hi, logarithmic = rng
        n = max(0.0, min(1.0, float(norm)))
        if logarithmic and lo > 0 and hi > 0:
            return lo * math.pow(hi / lo, n)
        return lo + n * (hi - lo)

    def set_fx_param(self, track, fx, param, norm):
        raw = self.raw_value(track, fx, param, norm)
        if raw is None:
            key = (track, fx, param)
            if key not in self._said_range:
                self._said_range.add(key)
                log.warning(f"ardour : plage inconnue pour piste {track} fx {fx} param {param} — écriture refusée")
            return False
        # surface d'Ardour : strip (1-based, = piste du livemap), plugin et paramètre 1-based, valeur brute
        return self.link.send("/strip/plugin/parameter", [int(track), int(fx) + 1, int(param) + 1, float(raw)])

    def set_track_volume(self, track, value):
        return self.link.send("/strip/fader", [int(track), max(0.0, min(1.0, float(value)))])

    def set_track_mute(self, track, muted):
        return self.link.send("/strip/mute", [int(track), 1 if muted else 0])

    def transport(self, op):
        """Lecture, pause, arrêt, retour au début. Le bridge enchaîne « stop » puis « start » (retour au début) d'un seul
        geste : le transport d'Ardour REFUSE un déplacement pendant qu'il s'arrête (mesuré 2026-11-17 : la position
        restait où elle était). Le retour au début qui suit un arrêt de moins de 0,4 s est donc envoyé un peu après."""
        import threading
        now = time.monotonic()
        if op in ("stop", "pause"):
            self._stopped_at = now
        wait = 0.4 - (now - getattr(self, "_stopped_at", 0.0))
        if op == "start" and wait > 0:
            threading.Timer(wait, self.link.send, _TRANSPORT[op]).start()
            return True
        return self.link.send(*_TRANSPORT[op])

    def refresh(self):
        self.register_surface()
        return self.link.send("/refresh", [])

    # ── cycle de vie ─────────────────────────────────────────────────────────────────────
    def pid(self):
        try:
            pid = int(open(pid_file()).read().strip())
        except (OSError, ValueError):
            return None
        names = _proc_names(pid)
        return pid if names and any(n in self.PROC_NAMES for n in names[:2]) else None

    def ready_since(self, t0):
        from .. import monitors
        return monitors._watch_started_since(t0)        # golem_watch.lua écrit la même ligne « démarré. surveille »

    def stop(self, timeout=10.0):
        pid = self.pid()
        if pid is None:
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return True
        end = time.time() + timeout
        while time.time() < end:
            if self.pid() is None:
                return True
            time.sleep(0.2)
        return False

    def run_script(self):
        return os.path.join(ENGINE_DIR, "golem", "engine", "run.sh")

    def restart(self, why="requested"):
        script = self.run_script()
        if not os.path.isfile(script):
            raise RuntimeError(f"Golem Engine not found ({script})")
        dead = self.stop()
        # encodage explicite : sans PYTHONUTF8, Windows écrit en cp1252 et « ── » lève avant même de lancer le moteur
        logf = open(RUN_LOG, "a", encoding="utf-8")
        logf.write(time.strftime("\n── %Y-%m-%d %H:%M:%S ") + f"restart ({why}) — ancien arrêté : {dead}\n")
        logf.flush()
        # le lanceur des trois systèmes (run.py, bibliothèque standard) quand le moteur l'a ; un paquet plus ancien
        # n'a que run.sh
        py = os.path.join(os.path.dirname(script), "run.py")
        cmd = [_console_python(), py] if os.path.isfile(py) else ["bash", script]
        # Windows : CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP — une console CACHÉE, dont le moteur hérite. C'était
        # DETACHED_PROCESS (aucune console) : le moteur, programme console lancé par run.py, s'en ouvrait alors une
        # VISIBLE par-dessus golem, et son journal partait dans cette fenêtre au lieu de RUN_LOG (VM Windows 11 vierge,
        # 2026-11-23 : fenêtre noire « ardour9-lua.exe » au premier démarrage, golem-engine.log vide).
        detach = {"creationflags": 0x08000000 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
        env = dict(os.environ)
        buf = card_buffer() if DEVICE else None
        if buf:
            env["GOLEM_ENGINE_BUFFER"] = str(buf)              # le buffer de la carte (Windows : Settings ▸ Audio)
        subprocess.Popen([*cmd, C.ROOT, SESSION_DIR, BACKEND, DEVICE], stdout=logf, stderr=subprocess.STDOUT, env=env,
                         **detach)
        return {"ok": True, "restarting": True}

    _table = {"mtime": None, "types": frozenset()}

    def plays(self, block_type):
        """Un type joue ici s'il est dans library/catalog/effects-golem-engine.json (relue quand elle change). Un bloc
        de SERVICE (Rec, Click, Drum machine…) n'a pas de plugin dans cette table : c'est sa FONCTION qui le porte
        (config/engines/features.json) — il joue dès que le descripteur la déclare « yes »."""
        from . import ardour_plan
        from .. import engines
        if block_type == "vst-host":                    # le VST Host : un plugin VST3 installé, sans entrée dans la table
            return True
        with contextlib.suppress(Exception):
            feat = engines.feature_of_block().get(block_type)
            if feat:
                return ((self.descriptor() or {}).get("capabilities") or {}).get(feat) == "yes"
        try:
            m = os.stat(ardour_plan.TABLE).st_mtime_ns
            if m != self._table["mtime"]:
                # un bloc joué par le BRIDGE lui-même (la Whammy DT, une pédale MIDI : `engine: midi` au catalogue) ne
                # demande rien au moteur : il joue sur tous. De même un bloc de service SANS fonction propre dans
                # features.json (`virtual` : l'Arrangement, que le bridge mène avec le click, la boîte à rythmes et la
                # backing ; l'accordeur, traité par le veilleur) — les autres services sont portés par leur fonction.
                featured = set(engines.feature_of_block())
                midi = {t for t, e in ardour_plan.load_catalog().items()
                        if e.get("engine") == "midi" or (e.get("engine") in ("virtual", "mode") and t not in featured)}
                self._table = {"mtime": m, "types": frozenset(ardour_plan.load_table()) | frozenset(midi)}
        except (OSError, ValueError):
            return False
        return block_type in self._table["types"]

    # ── carte son (lot A2.2) ─────────────────────────────────────────────────────────────
    BUFFERS = (32, 64, 96, 128, 192, 256, 384, 512, 1024)

    def _status(self):
        try:
            with open(os.path.join(C.PRESETS_DIR, ".engine-status.json"), encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError):
            return {}

    def audio(self):
        st = self._status() if self.pid() is not None else {}
        out = {}
        if st.get("buffer"):
            out["buffer"] = int(st["buffer"])
        if st.get("sample_rate"):
            out["rate"] = int(st["sample_rate"])
        if st.get("backend"):
            out["backend"] = st["backend"]
        if st.get("dsp_load") is not None:
            out["dsp_load"] = round(float(st["dsp_load"]), 1)
        return out

    def xruns(self):
        st = self._status() if self.pid() is not None else {}
        return int(st["xruns"]) if st.get("xruns") is not None else None

    def adopt_audio(self, audio):
        """Pas encore de buffer à soi : prendre celui du moteur d'avant (REAPER à 192 -> le Golem Engine à 192, pas 1024),
        ou le plus proche au-dessus dans notre liste."""
        path = os.path.join(C.ROOT, "config", "golem-engine.json")
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except (OSError, ValueError):
            cfg = {}
        if cfg.get("buffer") or not audio.get("buffer"):
            return
        b = int(audio["buffer"])
        size = b if b in self.BUFFERS else next((x for x in self.BUFFERS if x >= b), self.BUFFERS[-1])
        cfg["buffer"] = size
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        os.replace(tmp, path)
        log.info(f"ardour : buffer {size} repris du moteur d'avant ({b})")

    def set_buffer(self, size):
        """À chaud : le veilleur arrête puis relance le moteur avec le nouveau buffer (~26 ms), la session reste. Le
        choix est gardé dans config/golem-engine.json (état local), relu à chaque démarrage du moteur."""
        if size not in self.BUFFERS:
            raise ValueError(f"size must be one of {list(self.BUFFERS)}")
        path = os.path.join(C.ROOT, "config", "golem-engine.json")
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
        except (OSError, ValueError):
            cfg = {}
        cfg["buffer"] = size
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        os.replace(tmp, path)
        seq = self.send({"action": "audio_set", "buffer": size}) if self.pid() is not None else None
        return {"ok": True, "size": size, "restarting": False, "applied_live": seq is not None,
                "theoretical_ms": round(2 * size / 48000 * 1000, 1)}

    _version = None

    def version(self):
        if self._version is None:
            # un moteur INSTALLÉ (le paquet de golem-engine/golem/tools/bundle.py) porte sa version dans un fichier ;
            # un arbre de dev la dit par git
            with contextlib.suppress(OSError):
                with open(os.path.join(ENGINE_DIR, "VERSION"), encoding="utf-8") as f:
                    self._version = f.read().strip() or None
            if self._version:
                return self._version
            try:
                out = subprocess.run(["git", "-C", ENGINE_DIR, "describe", "--tags", "--always"],
                                     capture_output=True, text=True, timeout=3).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                out = ""
            self._version = out or None
        return self._version
