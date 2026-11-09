# SPDX-License-Identifier: GPL-3.0-or-later
"""Config du bridge GoleM. Chemins + ports OSC/HTTP."""
import os
import sys
from .golog import swallowed as _swallowed
from . import reaper_license as _reaper_license

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# racines où un fichier du catalogue a le droit de vivre (audit 2026-09-13, B1). Les tests posent des fichiers sous
# tmp_path et l'ajoutent ici — jamais en production.
# audit 2026-11-04 (H1) : assets/ seulement — la racine du dépôt entière laissait une entrée
# importée pointer sur config/auth-devices.json ou .env et le faire servir par une route de téléchargement
ASSET_ROOTS = [os.path.join(ROOT, "assets")]


def rel_posix(path, start=None):
    """`rel` écrit avec des « / » sur tous les systèmes : pour un chemin qui part dans un fichier partagé ou une adresse
    (démos de library/previews, listes d'un dossier) — sous Windows, `rel` rend des « \\ » et un manifeste écrit là
    différait de celui de Linux (CI Desktop tests, 2026-11-09)."""
    return (rel(path) if start is None else rel(path, start)).replace(os.sep, "/")


def rel(path, start=None):
    """`os.path.relpath` qui ne casse pas sous Windows quand `path` est sur un AUTRE lecteur que le dépôt (dossier de
    chansons sur D:, cache sous %TEMP%…) : relpath lève alors ValueError. On rend le chemin absolu tel quel — un
    chemin absolu reste lisible par tout ce qui joint à ROOT (os.path.join ignore la base devant un absolu)."""
    try:
        return os.path.relpath(path, ROOT if start is None else start)
    except ValueError:
        return os.path.abspath(path)


_DOTENV_PREFIXES = ("GOLEM_", "T3K_", "GOLEMFM_", "GOOGLE_API_KEY")


def _load_dotenv(path):
    """Charge .env (KEY=VALUE) dans l'environnement, sans dépendance pip. Les clés API (T3K_*, GOOGLE_API_KEY…)
    y vivent -> l'onglet API les pré-remplit (masquées). N'écrase pas une variable déjà définie."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                # audit 2026-10-15 (S1) : seules NOS clés entrent dans l'environnement — un LD_PRELOAD ou un
                # PATH glissé dans .env serait hérité par chaque ffmpeg, git ou curl que lance le bridge
                if not k.startswith(_DOTENV_PREFIXES):
                    continue
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(ROOT, ".env"))
APP_DIR = os.path.join(ROOT, "app")


# le dossier de ressources de REAPER et le home : UNE implémentation, partagée avec l'installateur (qui la charge
# par son chemin) — bridge/reaper_license.py
reaper_resource_dir = _reaper_license.resource_dir
user_home = _reaper_license.user_home


def runtime_dir():
    """Répertoire d'échange bridge/Reaper : tmpfs historique sur Linux."""
    override = os.environ.get("GOLEM_RUNTIME_DIR")
    if override:
        if not os.path.isabs(override):
            raise ValueError("GOLEM_RUNTIME_DIR doit être un chemin absolu")
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(user_home(), "AppData", "Local")
        return os.path.join(base, "GoleM", "runtime")
    if sys.platform == "darwin":
        return os.path.join(user_home(), "Library", "Caches", "GoleM", "runtime")
    return "/dev/shm"


# macOS (2026-10-04, docs/platforms.md) : le Python de python.org n'a AUCUN certificat racine tant
# que son « Install Certificates.command » n'a pas tourné — tout appel HTTPS de la bibliothèque standard
# (golem.fm, reaper.fm, TONE3000) échouerait en CERTIFICATE_VERIFY_FAILED. Le magasin du système est là.
if sys.platform == "darwin" and not os.environ.get("SSL_CERT_FILE") and os.path.isfile("/etc/ssl/cert.pem"):
    os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"

RUNTIME_DIR = runtime_dir()
REAPER_RESOURCE_DIR = reaper_resource_dir()


def runtime_file(name):
    """Chemin d'un état fugitif ; nom simple pour éviter une sortie du répertoire."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("nom de fichier runtime invalide")
    return os.path.join(RUNTIME_DIR, name)


PRESETS_DIR = os.path.join(ROOT, "presets")
MAPPINGS_DIR = os.path.join(ROOT, "mappings")
SETLISTS_DIR = os.path.join(ROOT, "setlists")
SONGS_DIR = os.path.join(ROOT, "songs")        # le RÉPERTOIRE du groupe (docs/songs.md) — jamais commité
TEMPLATES_DIR = os.path.join(ROOT, "templates")   # templates de lane (Designer)



def alsa_card():
    """Id ALSA de la carte ACTIVE : env > io.json.device > registre config/cards/ (une carte
    connue et BRANCHÉE, sinon l'unique non-ignorée) > la première carte USB BRANCHÉE et non ignorée > « » (aucune).
    PAS DE CARTE PAR DÉFAUT (2026-11-03) : le dernier repli était le littéral « V276 », la Volt de l'auteur — sur un
    golem neuf avec une autre carte (PreSonus iTwo), REAPER ouvrait hw:V276, absente, et le démarrage restait figé.
    Fonction (pas une constante) : la carte peut changer PENDANT que le bridge tourne (adoption)."""
    env = os.environ.get("GOLEM_ALSA_CARD")
    if env:
        return env
    try:
        import json as _j
        dev = (_j.load(open(os.path.join(ROOT, "config", "io.json"))) or {}).get("device", "")
        cid = dev.split(":", 1)[1] if ":" in dev else dev
        if cid:
            return cid
    except Exception as _e:
        _swallowed(_e)
    try:                       # io.json muet : le registre des cartes rencontrées (gear-registry)
        from . import cards as _cards
        reg = [d for d in _cards.registry() if not d.get("ignored")]
        conn = {c["id"] for c in _cards.connected()}
        hit = next((d["id"] for d in reg if d["id"] in conn), None)
        if hit:
            return hit
        if len(reg) == 1:      # une seule carte jamais rencontrée : c'est elle
            return reg[0]["id"]
        ignored = {d["id"] for d in _cards.registry() if d.get("ignored")}
        plugged = next((c["id"] for c in _cards.connected() if c["id"] not in ignored), None)
        if plugged:            # golem neuf, registre vide : la carte qui est LÀ
            return plugged
    except Exception as _e:
        _swallowed(_e)
    return ""                  # aucune carte : les appelants disent « pas de carte », jamais celle d'un autre
CONFIG_DIR = os.path.join(ROOT, "config")
CATALOG = os.path.join(ROOT, "library", "catalog", "tones-index.json")
EFFECTS = os.path.join(ROOT, "library", "catalog", "effects.json")
COMMAND_FILE = os.path.join(ROOT, "presets", ".command.json")   # bridge -> ReaScript
TUNER_FILE = os.path.join(ROOT, "presets", ".tuner.json")       # golem_tuner.lua -> bridge (note/cents détectés)
LOOPER_FILE = os.path.join(ROOT, "presets", ".looper.json")     # golem_looper.lua -> bridge (états des loops)
SAMPLE_FILE = os.path.join(ROOT, "presets", ".sample.json")     # golem_sample.lua -> bridge (états des one-shots)
DRUMS_FILE  = os.path.join(ROOT, "presets", ".drums.json")      # golem_drums.lua -> bridge (états des grooves)
LOOPER_CMD_FILE = os.path.join(ROOT, "presets", ".looper-cmd.json")  # bridge -> golem_looper.lua (fallback de commande)
BACKING_FILE = os.path.join(ROOT, "presets", ".backing.json")    # golem_backing.lua -> bridge (transport/position)
BACKING_DIR = os.path.join(ROOT, "assets", "backing")            # cache des stems golem.fm (<slug>/{stem}.mp3 + meta.json)
PREVIEW_FILE = os.path.join(ROOT, "presets", ".preview.json")    # golem_preview.lua -> bridge (rendus WAV par scène)
PREVIEWS_DIR = os.path.join(ROOT, "library", "previews")         # démos par preset : <presetid>/<scene>.opus
DI_REFS_DIR = os.path.join(ROOT, "library", "di-refs")           # phrases DI de référence GoleM-owned (index.json)

# HTTP (app + API)
HTTP_HOST = "0.0.0.0"
HTTP_PORT = int(os.environ.get("GOLEM_PORT", "8770"))

# OSC — bridge <-> Reaper (cf. reaper/OSC/golem.ReaperOSC)
REAPER_OSC_HOST = os.environ.get("GOLEM_REAPER_HOST", "127.0.0.1")
REAPER_OSC_SEND_PORT = int(os.environ.get("GOLEM_OSC_SEND", "8000"))   # bridge -> Reaper (Reaper écoute)
BRIDGE_OSC_RECV_PORT = int(os.environ.get("GOLEM_OSC_RECV", "9000"))   # Reaper -> bridge (bridge écoute)

# Action ReaScript déclenchée par le bridge pour appliquer un preset/scène.
# À remplacer par l'ID réel (_RS...) une fois le script enregistré dans Reaper (cf. P1 wiring).
RECALL_ACTION = os.environ.get("GOLEM_RECALL_ACTION", "_RS_GOLEM_APPLY")
