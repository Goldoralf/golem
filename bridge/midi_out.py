# SPDX-License-Identifier: GPL-3.0-or-later
"""Sortie MIDI matérielle de GoleM (Whammy DT via le MIDI OUT du Volt).

CONNEXION PERSISTANTE python-rtmidi (ALSA) : le port est ouvert UNE fois et réutilisé —
indispensable pour le treadle temps-réel (CC11 continu, FCB EXP2 -> Whammy) où l'ancien
`amidi` forkait un process PAR message (tempête de forks, cf. audit 2026-07-07).

Filet : si rtmidi est absent ou que l'envoi échoue (USB débranché), bascule sur le chemin
`amidi` PROUVÉ au POC (2026-07-01, LED Whammy allumée), un fork par message mais fiable.
La reconnexion est automatique : un échec ferme le port, l'appel suivant ré-énumère.

Thread-safe (lock) : appelé depuis le thread lecteur FCB (treadle) ET la boucle FastAPI.
Résilient : si aucun chemin dispo, no-op silencieux (le bridge ne plante pas).
Mesuré (2026-07-07, Volt 276) : sweep treadle complet 0→127 = 1,4 ms (0,011 ms/msg).
⚠ Tant que la connexion seq est ouverte, le kernel tient la rawmidi : un `amidi` EXTERNE
(CLI) répondra « busy » — normal. Le filet interne, lui, ne sert que si rtmidi est tombé
(port refermé -> rawmidi libérée).
Port : auto-détecté par nom « Volt » ; GOLEM_MIDI_PORT force la détection (hw:X,Y,Z pour
amidi, sous-chaîne du nom de port pour rtmidi).
"""
import json, os, shutil, subprocess, sys, threading
from . import config as C
from .midi_api import native_api
from .golog import get
from .golog import swallowed as _swallowed

log = get("midi_out")

try:
    import rtmidi
    _RT_ERR = None
except Exception as _e:                 # pip absent/cassé -> amidi only
    rtmidi, _RT_ERR = None, _e

_LOCK = threading.Lock()                # sérialise ouverture + envois (thread pied vs API)
_RT = {"out": None, "name": None}       # port rtmidi ouvert (persistant)
_PORT = None                            # port amidi hw:X,Y,Z (cache)
_WARNED = False


_HELD = {"on": False}                   # ports rendus au système (flash Control Center) : rien n'est envoyé


def held():
    """True tant que les ports de sortie sont rendus au système (Control Center)."""
    return _HELD["on"]


def hold(on):
    """Rend (True) ou reprend (False) les ports de SORTIE. Rendus : fermés tout de suite, et aucun
    envoi ne les rouvre (sinon le prochain changement de scène reprendrait le port en plein flash)."""
    _HELD["on"] = bool(on)
    if on:
        reset_ports()
    return _HELD["on"]


def reset_ports():
    """Oublie les ports MIDI cachés (changement de CARTE SON, gear-registry 2026-07-26) : la
    prochaine émission rouvre sur la carte active. Sans ça, rtmidi reste abonné à un client seq
    mort — ou RECYCLÉ par ALSA sur la nouvelle carte (même numéro) : ça marche par accident."""
    global _PORT, _WARNED
    try:
        if _RT["out"] is not None:
            _RT["out"].close_port()
    except Exception as _e:
        _swallowed(_e)
    _RT["out"], _RT["name"] = None, None
    # ports DÉDIÉS des descripteurs (bloc midi-pedal, champ midi_port) : même règle
    for ent in list(_RT_NAMED.values()):
        try:
            ent["out"].close_port()
        except Exception as _e:
            _swallowed(_e)
    _RT_NAMED.clear()
    _PORT, _WARNED = None, False
    log.info("ports oubliés (changement de carte) — re-résolution au prochain envoi")


# ── chemin rtmidi (persistant) ───────────────────────────────────────────────
def _rt_close():
    if _RT["out"] is not None:
        try:
            _RT["out"].close_port()
        except Exception as _e:
            _swallowed(_e)
    _RT["out"], _RT["name"] = None, None


# ── un BANC n'a pas de matériel MIDI (2026-10-27) ────────────────────────────────────────────────────────────────
# Un bridge de banc (tools/check-rig-materialize.py, tools/check-use.py) tourne sur la machine du rack : sans pédalier
# trouvé, le filet amidi retombait sur le port « volt » — la VRAIE Whammy du rack d'à côté changeait de programme quand
# le banc rappelait un patch. GOLEM_NO_HW_MIDI=1 : aucun envoi, aucune écoute, aucune sonde de matériel MIDI.
def hw_midi_off():
    return os.environ.get("GOLEM_NO_HW_MIDI") == "1"


def _rt_open():
    """Ouvre (une fois) le port Volt via rtmidi. Retourne le MidiOut ou None."""
    global _WARNED
    if hw_midi_off():
        return None                              # un banc n'ouvre pas le port du rack (GOLEM_NO_HW_MIDI)
    if rtmidi is None:
        # Linux a le filet amidi, qui prévient lui-même. Ailleurs il n'y a RIEN derrière :
        # sans cette ligne, toute la sortie MIDI se taisait sans un mot dans le journal.
        if sys.platform in ("win32", "darwin") and not _WARNED:
            log.warning("python-rtmidi ne se charge pas (%s) -> sortie MIDI désactivée (no-op)" % (_RT_ERR,))
            _WARNED = True
        return None
    if _RT["out"] is not None:
        return _RT["out"]
    try:
        want = os.environ.get("GOLEM_MIDI_PORT", "")
        want = "" if want.startswith("hw:") else want.lower()    # hw:… = syntaxe amidi, pas un nom
        if not want and sys.platform in ("win32", "darwin"):
            from . import desktop_midi                            # la prise MIDI OUT choisie dans Soundcard
            want = (desktop_midi.din_port("out") or "").lower()
        if not want and sys.platform in ("win32", "darwin"):
            # UNE fois, et avant d'allouer quoi que ce soit : _rt_open est rappelé à CHAQUE
            # message tant que rien n'est ouvert — un balayage de pédale EXP écrivait des
            # centaines de lignes identiques (même garde que le filet amidi plus bas).
            if not _WARNED:
                log.warning("aucune prise MIDI OUT choisie (Settings ▸ Gear ▸ Soundcard ▸ MIDI OUT) "
                            "-> sortie MIDI désactivée (no-op)")
                _WARNED = True
            return None
        mo = rtmidi.MidiOut(native_api(rtmidi), name="golem-bridge")
        if not want:                                             # défaut = le rawmidi de la carte ACTIVE
            _idx, _nm = _active_card_midi()
            want = (_nm or "volt").lower()
        for i, name in enumerate(mo.get_ports()):
            low = name.lower()
            if want in low:
                mo.open_port(i, name="whammy")
                _RT["out"], _RT["name"] = mo, name
                log.info(f"rtmidi connecté : {name}")
                return mo
    except Exception as e:
        log.warning("rtmidi indisponible : %s" % (e,))
    return None


# ── filet amidi (fork par message, chemin prouvé) ────────────────────────────
def _amidi():
    return shutil.which("amidi")


def _active_card_midi():
    """(index ALSA, nom rawmidi) de la carte ACTIVE (io.json.device) — chantier gear-registry :
    plus de « volt » codé en dur, le MIDI OUT suit la carte du moment (Volt, Presonus…).
    (None, None) si la carte est absente ou sans MIDI."""
    import re as _re
    try:
        dev = json.load(open(os.path.join(C.CONFIG_DIR, "io.json"))).get("device", "")
        cid = dev.split(":", 1)[1] if ":" in dev else dev
        m = _re.search(r"^\s*(\d+)\s+\[" + _re.escape(cid) + r"\s*\]",
                       open("/proc/asound/cards").read(), _re.M)
        if not m:
            return None, None
        idx = int(m.group(1))
        name = open(f"/proc/asound/card{idx}/midi0").read().splitlines()[0].strip()
        return idx, (name or None)
    except Exception:
        return None, None


def _amidi_port():
    global _PORT
    env = os.environ.get("GOLEM_MIDI_PORT")
    if env and env.startswith("hw:"):
        return env
    if _PORT:
        return _PORT
    a = _amidi()
    if not a:
        return None
    try:
        out = subprocess.check_output([a, "-l"], text=True, timeout=2)   # port USB zombie = gel sinon
    except Exception:
        return None
    idx, _nm = _active_card_midi()
    for line in out.splitlines():
        # 1) le port de la carte ACTIVE (hw:<index>,…) ; 2) repli legacy « volt »
        hit = (idx is not None and f"hw:{idx}," in line) or (idx is None and "volt" in line.lower())
        if hit:
            for tok in line.split():
                if tok.startswith("hw:"):
                    _PORT = tok
                    return tok
    return None


def _send_amidi(msg_bytes):
    global _WARNED
    a, port = _amidi(), _amidi_port()
    if not a or not port:
        if not _WARNED:
            log.warning("rtmidi ET amidi/port Volt absents -> sortie MIDI désactivée (no-op)")
            _WARNED = True
        return False
    hexs = " ".join("%02X" % (b & 0xFF) for b in msg_bytes)
    try:
        subprocess.run([a, "-p", port, "-S", hexs], check=True, timeout=2,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        log.error("échec envoi %s : %s" % (hexs, e))
        return False


# ── envoi unifié ─────────────────────────────────────────────────────────────
def _send(msg_bytes):
    if _HELD["on"] or hw_midi_off():
        return False
    with _LOCK:
        mo = _rt_open()
        if mo is not None:
            try:
                mo.send_message(msg_bytes)
                return True
            except Exception as e:
                log.warning("rtmidi échec (déconnexion ?) : %s -> filet amidi" % (e,))
                _rt_close()                       # le prochain appel ré-énumérera
        if sys.platform in ("win32", "darwin"):
            return False
        return _send_amidi(msg_bytes)


def find_port():
    """Nom du port actif (rtmidi persistant), sinon le hw:X,Y,Z amidi, sinon None."""
    if hw_midi_off():
        return None
    if _RT["name"]:
        return _RT["name"]
    if sys.platform in ("win32", "darwin"):
        return None
    return _amidi_port()


def program_change(pc, channel=1):
    return _send([0xC0 + (channel - 1), pc & 0x7F])


def control_change(cc, val, channel=1):
    return _send([0xB0 + (channel - 1), cc & 0x7F, val & 0x7F])


def send_sysex(data):
    """Envoie un dump SysEx complet (bytes/list, F0…F7) — ex. flash de la config FCB1010.
    Passe par la connexion persistante rtmidi (un seul message) ; filet amidi identique."""
    b = list(data)
    if not (b and b[0] == 0xF0 and b[-1] == 0xF7):
        log.warning("sysex invalide (F0…F7 attendu)")
        return False
    return _send(b)


# ── Whammy DT (mappings/whammy-dt.json) ──────────────────────────────────────
_WCFG = {"mtime": None, "cfg": None}     # cache sur mtime : relu seulement si le fichier change


def _whammy_cfg():
    """Config Whammy, tolérante (fichier absent/corrompu = {}) et cachée — appelée à CHAQUE
    message (treadle continu inclus), et depuis le thread pied (audit 2026-07-07 P1)."""
    path = os.path.join(C.MAPPINGS_DIR, "whammy-dt.json")
    try:
        mt = os.path.getmtime(path)
        if _WCFG["mtime"] != mt:
            with open(path) as f:
                _WCFG["cfg"] = json.load(f)
            _WCFG["mtime"] = mt
        return _WCFG["cfg"]
    except Exception as e:
        log.warning("whammy-dt.json illisible : %s" % (e,))
        return {}


def warm():
    """Arme la ligne MIDI OUT au démarrage du bridge (sans rien envoyer) — SAUF si le
    l'input map la met à None. Deux raisons : la latence du 1er message de scène disparaît,
    et l'indicateur MIDI OUT de Soundcard devient honnête (« ligne Whammy armée » = vert
    dès le boot, au lieu de gris jusqu'au premier envoi — retour UX 2026-07-19)."""
    from . import inputmap as _imap
    if _imap.din_role("midi_out") == "none":
        _rt_close()
        return False
    return _rt_open() is not None


def _din_out_off():
    """Kill-switch de l'input map (Soundcard v2) : MIDI OUT = None -> la glue pédales (Whammy
    ET génériques) se tait, avec un log (dégradé, jamais silencieux). Le flash SysEx FCB n'est
    PAS concerné (opération de maintenance volontaire, pas de la performance)."""
    from . import inputmap as _imap
    if _imap.din_role("midi_out") == "none":
        log.warning("MIDI OUT = None (input map Soundcard) — envoi pédale ignoré")
        return True
    return False


def whammy_mode(name=None, active=True):
    """Envoie le PC actif (ou bypass) du mode whammy nommé (défaut = default_mode du json)."""
    if _din_out_off():
        return False
    w = _whammy_cfg()
    name = name or w.get("default_mode")
    m = next((x for x in w.get("modes", []) if x["name"] == name), None)
    if not m:
        log.warning("mode whammy inconnu: %s" % (name,))
        return False
    pc = m.get("active_pc", m.get("pc")) if active else m.get("bypass_pc")
    if pc is None:
        return False
    return program_change(pc, w.get("channel", 1))


def whammy_treadle(value, channel=None):
    """Position du pitch (0-127) sur le CC treadle de la Whammy."""
    if _din_out_off():
        return False
    w = _whammy_cfg()
    return control_change(w.get("treadle_cc", 11), value, channel or w.get("channel", 1))


# ── Pédales MIDI génériques (bloc `midi-pedal`, descripteurs mappings/<id>.json) ─────────────
# Chantier ① audit 2026-08-12 §3 : le registre (docs/pedal-registry.md) décrit 8 pédales mais
# seule la Whammy avait sa glue. Ici : la MÊME mécanique (PC de réglage / PC de bypass PAR
# réglage quand la table le décrit, CC de treadle, canal du descripteur) pour N'IMPORTE QUEL
# descripteur installé. Le chemin Whammy ci-dessus reste NOMINATIF et intouché (prouvé matériel).
_PCFG = {}          # id -> {"mtime", "cfg"} — cache par descripteur (patron _WCFG)
_RT_NAMED = {}      # port DÉDIÉ d'un descripteur (champ midi_port) -> MidiOut persistant
_NO_BYPASS_WARNED = set()   # tables sans PC de bypass : on le dit UNE fois, pas à chaque scène


def pedal_cfg(pid):
    """Descripteur d'une pédale INSTALLÉE (mappings/<id>.json), tolérant ({} si absent/corrompu)
    et caché sur mtime — appelé à chaque émission, et depuis le thread pied (treadle relayé)."""
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9._-]", "", str(pid or ""))
    if not safe:
        return {}
    path = os.path.join(C.MAPPINGS_DIR, f"{safe}.json")
    ent = _PCFG.setdefault(safe, {"mtime": None, "cfg": {}})
    try:
        mt = os.path.getmtime(path)
        if ent["mtime"] != mt:
            with open(path) as f:
                ent["cfg"] = json.load(f)
            ent["mtime"] = mt
        return ent["cfg"]
    except Exception as e:
        log.warning("descripteur %s illisible : %s" % (safe, e))
        return {}


def resolve_setting(cfg, name=None, active=True):
    """Résout un RÉGLAGE d'un descripteur en message : {pc, channel, name} — ou None.

    Sémantique (cas général posé par la Whammy DT, docs/pedal-registry.md) :
    - active=True  -> `active_pc` (repli `pc`) du réglage nommé ; sans nom -> `default_mode`,
      sinon le PREMIER réglage de la table (les imports MIDNAM n'ont pas de défaut déclaré) ;
    - active=False -> le `bypass_pc` DU réglage QUAND la table le décrit. Une table MIDNAM n'en
      a pas : None — il n'y a rien d'honnête à envoyer, la pédale se bypasse au pied.
    Pur (aucun I/O) : c'est la fonction que testent les unitaires."""
    modes = (cfg or {}).get("modes") or []
    if not modes:
        return None
    nm = name or cfg.get("default_mode")
    m = next((x for x in modes if x.get("name") == nm), None) if nm else None
    if m is None:
        if name:                                  # réglage NOMMÉ introuvable -> on ne devine pas
            return None
        m = modes[0]                              # pas de défaut déclaré -> 1er réglage
    pc = m.get("active_pc", m.get("pc")) if active else m.get("bypass_pc")
    if pc is None:
        return None
    return {"pc": int(pc), "channel": int(cfg.get("channel", 1) or 1), "name": m.get("name")}


def pedal_treadle_cc(cfg):
    """CC de la pédale d'expression déclaré par le descripteur (treadle.cc, repli treadle_cc),
    None si la pédale n'en a pas (Drop/Raise fixes, multi-effets MIDNAM)."""
    return (cfg or {}).get("treadle", {}).get("cc") or (cfg or {}).get("treadle_cc")


def _send_named(port, msg_bytes):
    """Envoi sur le port DÉDIÉ d'un descripteur (champ `midi_port` : hw:X,Y,Z -> amidi direct,
    sinon sous-chaîne du nom rtmidi, connexion persistante par port). ⚠ JAMAIS de repli sur le
    port par défaut : rabattre, ce serait envoyer un PC à la mauvaise pédale."""
    if _HELD["on"]:
        return False
    if port.startswith("hw:"):
        a = _amidi()
        if not a:
            return False
        hexs = " ".join("%02X" % (b & 0xFF) for b in msg_bytes)
        try:
            subprocess.run([a, "-p", port, "-S", hexs], check=True, timeout=2,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            log.error("échec envoi %s sur %s : %s" % (hexs, port, e))
            return False
    if rtmidi is None:
        return False
    with _LOCK:
        ent = _RT_NAMED.get(port)
        if ent is None:
            try:
                mo = rtmidi.MidiOut(native_api(rtmidi), name="golem-bridge")
                want = port.lower()
                for i, nm in enumerate(mo.get_ports()):
                    if want in nm.lower():
                        mo.open_port(i, name="pedal")
                        ent = _RT_NAMED[port] = {"out": mo, "name": nm}
                        log.info(f"rtmidi connecté (port dédié) : {nm}")
                        break
            except Exception as e:
                log.warning("port dédié '%s' indisponible : %s" % (port, e))
        if ent is None:
            return False
        try:
            ent["out"].send_message(msg_bytes)
            return True
        except Exception as e:
            log.warning("rtmidi échec sur '%s' : %s" % (port, e))
            try:
                ent["out"].close_port()
            except Exception as _e:
                _swallowed(_e)
            _RT_NAMED.pop(port, None)             # le prochain appel ré-énumérera
            return False


def _pedal_send(cfg, msg_bytes):
    """Route un message vers le port du DESCRIPTEUR : `midi_port` s'il existe, sinon la ligne
    MIDI OUT par défaut (celle de la Whammy — le cas normal : tout est chaîné en DIN)."""
    port = str((cfg or {}).get("midi_port") or "").strip()
    return _send_named(port, msg_bytes) if port else _send(msg_bytes)


def pedal_mode(pid, setting=None, active=True):
    """Envoie le PC actif (ou bypass) du réglage `setting` d'une pédale installée.
    Retourne le NOM du réglage résolu (à mémoriser : c'est lui qu'il faudra nommer pour
    éteindre — sémantique Whammy), ou None si rien n'a été envoyé."""
    if _din_out_off():
        return None
    cfg = pedal_cfg(pid)
    r = resolve_setting(cfg, setting, active)
    if r is None:
        if active:
            log.warning("réglage inconnu pour %s : %s" % (pid, setting))
        elif pid not in _NO_BYPASS_WARNED:
            _NO_BYPASS_WARNED.add(pid)
            log.info("pas de PC de bypass dans la table %s — extinction MIDI impossible" % (pid,))
        return None
    ok = _pedal_send(cfg, [0xC0 + (r["channel"] - 1), r["pc"] & 0x7F])
    return r["name"] if ok else None


def pedal_treadle(pid, value):
    """Position de la pédale d'expression (0-127) sur le CC treadle du descripteur.
    False si le descripteur n'en déclare pas (rien n'est envoyé)."""
    if _din_out_off():
        return False
    cfg = pedal_cfg(pid)
    cc = pedal_treadle_cc(cfg)
    if cc is None:
        return False
    ch = int(cfg.get("channel", 1) or 1)
    return _pedal_send(cfg, [0xB0 + (ch - 1), int(cc) & 0x7F, int(value) & 0x7F])
