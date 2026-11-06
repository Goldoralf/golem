# SPDX-License-Identifier: GPL-3.0-or-later
"""Lecteur FCB1010 → bridge (remplace golem_foot.lua).

Lit le MIDI entrant du pédalier via `aseqdump` (ALSA séquenceur) — sans dépendance pip — et
interprète PC/CC/Note selon le CONTRAT v2. Les tables d'intention viennent de
config/pedalboard/contract.json (via set_device/apply_intent — docs/pedalboards.md §10),
DEFAULT_INTENT étant le repli. Valeurs du contrat gelé :

  Program Change n      -> recall SLOT n (idempotent : no-op si le preset est déjà chargé)
  Control Change 20-24  -> scène A-E du preset courant
  Control Change 30-34  -> toggle stomp (boost/delay/reverb/tremolo/whammy)
  Control Change 11     -> pédale EXP 2 (ExpB) — rôle volume|bloc résolu par app.py (config/pedals.json)
  Control Change 7      -> pédale EXP 1 (ExpA) — idem (les CC physiques sont figés par le flash FCB)
  Note 1-10             -> identité du switch (appui long switch 1 -> saisie 2 chiffres -> recall slot NN)

Chaque switch d'une bank envoie, à l'appui : sa Note (identité/durée) + PC n (slot, idempotent) + son CC (scène/stomp).
Donc n'importe quel switch pressé dans la bank N sélectionne d'abord le bon preset, PUIS fait sa scène/stomp.

Le lecteur tourne dans un thread (aseqdump bloquant). Les handlers sont fournis par app.py. Testable sans pédalier via
`feed(line)` (endpoint /api/foot/inject) : on rejoue des lignes aseqdump synthétiques.

⚠ NE PAS lancer golem_foot.lua en même temps (double traitement du MIDI FCB).
⚠ Contrat v2 : le pédalier physique doit être (re)programmé (UnO ControlCenter) pour envoyer PC=slot / CC20-24=scène /
  CC30-34=stomp / Note=identité. En attendant la puce, on valide tout via /api/foot/inject.
"""
import contextlib, ctypes, os, queue, re, shutil, signal, subprocess, sys, threading, time

from .golog import get
from .golog import swallowed as _swallowed
from .midi_api import native_api

log = get("foot")


def _die_with_parent():
    """PR_SET_PDEATHSIG : l'aseqdump enfant meurt avec le bridge (sinon chaque reload.sh
    laissait un aseqdump zombie accroché au port FCB — constaté ×5 le 2026-07-07)."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # 1 = PR_SET_PDEATHSIG
    except Exception as _e:
        _swallowed(_e)

# ── L'INTENTION : compilée depuis config/pedalboard/contract.json, plus jamais écrite ici ────
# Les tables (CC=scène, CC=stomp, pédales d'expression, appui long) étaient portées EN DUR ici,
# en DOUBLE du contrat — deux copies d'une même vérité qui auraient fini par diverger, et la
# divergence ne se serait vue qu'au pied (audit 2026-08-12 §3). Désormais l'intention arrive par
# set_device() (wire_contract() la porte), compilée par apply_intent().
#
# DEFAULT_INTENT est le REPLI — même schéma que contract.json, mêmes valeurs qu'au jour du gel.
# Ce n'est PAS une deuxième vérité : c'est la même, dans le même schéma, compilée par la même
# fonction — utilisée seulement si le fichier manque ou ne se lit pas (le rack doit démarrer).
DEFAULT_INTENT = {
    "scenes": [{"switch": 1, "name": "A", "cc": 20}, {"switch": 2, "name": "B", "cc": 21},
               {"switch": 3, "name": "C", "cc": 22}, {"switch": 4, "name": "D", "cc": 23},
               {"switch": 5, "name": "E", "cc": 24}],
    "stomps": [{"switch": 6, "cc": 30}, {"switch": 7, "cc": 31}, {"switch": 8, "cc": 32},
               {"switch": 9, "cc": 33}, {"switch": 10, "cc": 34}],
    "expression": [{"pedal": 1, "role": "volume", "cc": 7},
                   {"pedal": 2, "role": "block", "cc": 11}],
    "select": {"switch": 1, "long_press_s": 1.5, "timeout_s": 8.0},
    # long_press_s = 1.5 : durée d'appui pour entrer en sélection. Elle valait 0,5 s jusqu'au
    # 2026-09-21 : un appui de pied un peu appuyé sur le switch 1 — c'est-à-dire un retour en
    # scène A — faisait entrer en sélection SANS LE DIRE, et l'appui de scène suivant devenait un
    # chiffre (mesuré : SW1 tenu 0,7 s puis SW2 -> on reste en A, « sélection : chiffre 2 »).
    # C'était le « deuxième A->B qui accroche » de Paper Kite. Décision le mainteneur : 1,5 s + visible.
    # timeout_s = 8.0 : abandon auto entre deux chiffres (4 s = trop court au pied, vécu 2026-07-24).
}


def _compile_intent(con):
    """Contrat d'intention (schéma de contract.json) -> tables du lecteur. Chaque section
    absente retombe sur DEFAULT_INTENT — un contrat partiel ne rend pas le pied à moitié muet."""
    con = con or {}
    scenes = con.get("scenes") or DEFAULT_INTENT["scenes"]
    stomps = con.get("stomps") or DEFAULT_INTENT["stomps"]
    expr = con.get("expression") or DEFAULT_INTENT["expression"]
    sel = con.get("select") or DEFAULT_INTENT["select"]
    volume_cc, treadle_cc = 7, 11
    for p in expr:
        if int(p.get("pedal", 0)) == 1:
            volume_cc = int(p.get("cc", 7))
        elif int(p.get("pedal", 0)) == 2:
            treadle_cc = int(p.get("cc", 11))
    # Pavé numérique de l'appui long : le switch N tape le chiffre N, le 10 tape 0. Dérivé des
    # switches déclarés (scènes + stomps) — pas une table de plus à tenir à jour.
    switches = sorted({int(s["switch"]) for s in list(scenes) + list(stomps) if s.get("switch")})
    return {
        "scene_cc": {int(s["cc"]): str(s["name"]) for s in scenes if s.get("cc") is not None},
        "stomp_cc": {int(s["cc"]): int(s["switch"]) for s in stomps if s.get("cc") is not None},
        "volume_cc": volume_cc, "treadle_cc": treadle_cc,
        "digit_of_switch": {sw: sw % 10 for sw in switches},
        "select_switch": int(sel.get("switch", 1)),
        "longpress_s": float(sel.get("long_press_s", 1.5)),
        "select_timeout_s": float(sel.get("timeout_s", 8.0)),
    }


def apply_intent(con):
    """Applique un contrat d'intention aux tables du lecteur (None -> repli DEFAULT_INTENT).

    Blindé : un contrat malformé ne doit JAMAIS laisser les tables cassées — on retombe sur le
    repli et on le dit. Un pied qui obéit à l'ancienne table vaut mieux qu'un pied mort."""
    global SCENE_CC, STOMP_CC, TREADLE_CC, VOLUME_CC
    global DIGIT_OF_SWITCH, SELECT_SWITCH, LONGPRESS_S, SELECT_TIMEOUT_S
    try:
        t = _compile_intent(con)
    except Exception as e:
        log.warning("contrat d'intention illisible (%s) -> tables de REPLI" % (e,))
        t = _compile_intent(None)
    SCENE_CC = t["scene_cc"]
    STOMP_CC = t["stomp_cc"]        # CC physique -> POSITION de switch ; les blocs sur ce switch sont résolus par le bridge (block.foot)
    TREADLE_CC = t["treadle_cc"]
    VOLUME_CC = t["volume_cc"]
    DIGIT_OF_SWITCH = t["digit_of_switch"]
    SELECT_SWITCH = t["select_switch"]        # appui long sur ce switch -> mode sélection numérique
    LONGPRESS_S = t["longpress_s"]
    SELECT_TIMEOUT_S = t["select_timeout_s"]


apply_intent(None)   # tables utilisables dès l'import ; set_device() applique le contrat réel

# ── CE QUI DÉPEND DE LA PUCE, ET QUI NE VIT PLUS ICI ─────────────────────────────────────────
# Le canal du contrat et les travers de la puce viennent du DESCRIPTEUR de l'appareil actif
# (config/pedalboard/devices/<id>.json, contrat docs/pedalboards.md). Ils étaient en dur, et
# ça coûtait cher : la UnO2 émet sur le canal 2, la 1.0.4 sur le canal 1 — ressouder l'autre
# puce rendait le rack SOURD, chaque appui jeté par le filtre de canal, sans un mot de log.
#
# Pourquoi un filtre de canal, d'abord : la UnO2 renvoie TOUT ce qui entre sur son MIDI IN vers
# son OUT (« MIDI THRU behavior », non désactivable, contrairement au MIDI MERGE de la 1.0.4).
# Câblée Volt OUT -> FCB IN, elle nous renvoie nos propres ordres Whammy — mesuré le soir de la
# bascule : des PC fantômes en boucle. La parade est à nous : le Whammy garde le canal 1, le
# pédalier parle sur le 2, ce lecteur n'écoute QUE le canal du contrat.
#
# ⚠ Le canal du CONTRAT est 1-16 ; le canal SUR LE FIL est 0-15 (aseqdump numérote depuis 0).
# `wire_channel` est déjà converti. Confondre les deux est exactement ce qui rend sourd.
#
# Instantané, pas relecture : ces valeurs sont lues à CHAQUE message MIDI. Le dictionnaire est
# rafraîchi par set_device(), appelé au démarrage et quand l'appareil actif change.
_DEVICE = {"device_id": None, "wire_channel": 1, "note_edges": "clean", "note_base": 0,
           # par où le pédalier ARRIVE (descripteur `transport`) : din-soundcard = le DIN de la
           # carte son active (comportement historique) ; usb = son propre port ALSA (port_match).
           "transport": {"kind": "din-soundcard"},
           # les switches qui délivrent VRAIMENT un relâchement (pedalboard.edge_switches()).
           # None = pas encore renseigné -> on ne synthétise rien, comportement d'avant.
           "edge_switches": None}

# Le lecteur enregistré (FootReader.start) : set_device() doit pouvoir le REBRANCHER quand le
# transport change — l'aseqdump courant écoute l'ancien port, et personne d'autre ne le sait.
_READER = None


def set_device(wire):
    """Applique le contrat de fil de l'appareil actif (bridge/pedalboard.wire_contract())."""
    global _BOUND
    before = dict(_DEVICE)
    _DEVICE.update({k: wire[k] for k in ("device_id", "wire_channel", "note_edges", "note_base",
                                         "transport", "bindings") if k in wire})
    _BOUND = _index_bindings(_DEVICE.get("bindings"))
    if "edge_switches" in wire:
        _DEVICE["edge_switches"] = set(wire["edge_switches"] or ())
    # L'INTENTION voyage avec le contrat de fil : une seule application, un seul ordre au boot
    # (l'appareil DÉCLARÉ d'abord, la sonde corrige ensuite — app.py::_apply_pedalboard).
    if "intent" in wire:
        apply_intent(wire["intent"])
    if before != _DEVICE:
        log.info("pédalier « %s » : canal %d sur le fil, fronts %s%s"
                 % (_DEVICE["device_id"], _DEVICE["wire_channel"], _DEVICE["note_edges"],
                    (", %d liaisons apprises" % len(_BOUND)) if _BOUND else ""))
    # Transport changé -> le port d'écoute n'est plus le bon : on tue l'aseqdump courant, la
    # boucle _supervise re-résout (même mécanique que le changement de carte son, cf. rebind()).
    if _READER is not None and before.get("transport") != _DEVICE.get("transport"):
        log.info("transport du pédalier changé (%s) -> re-résolution du port d'écoute"
                 % ((_DEVICE.get("transport") or {}).get("kind"),))
        _READER.rebind()


def wire_channel():
    """Le canal écouté, sur le fil (0-15). Utilisé aussi par /api/foot/inject : injecter sur un
    autre canal serait ignoré en silence, et le test paraîtrait muet sans raison."""
    return _DEVICE["wire_channel"]


# ── « quand le rack a-t-il ENTENDU le pied pour la dernière fois ? » ─────────────────────────
# Ce n'est pas la même question que « quelle puce est branchée ». Une puce peut s'identifier
# parfaitement et le rack ne rien recevoir d'elle — câble de jeu débranché, mauvais canal, MIDI IN
# coupé dans l'input map. C'est CETTE panne-là qu'on voit en répète, et rien ne la montrait.
_HEARD = {"t": None}


def note_heard():
    _HEARD["t"] = time.time()
    from . import activity                  # un pied posé = quelqu'un joue (docs/reamp.md §2)
    activity.touch("foot")


def last_heard():
    """Horodatage du dernier message RETENU (donc venu du pédalier, pas un écho). None si rien."""
    return _HEARD["t"]


# ── LIAISONS : ce que l'appareil ENVOIE -> ce que le rack COMPREND ───────────────────────────
# Les deux FCB sont des exceptions assumées : on les PROGRAMME pour qu'ils parlent le contrat
# GoleM, donc leur interprétation est écrite en dur plus bas. Le cas général est l'inverse —
# un pédalier envoie ce qu'il envoie, et c'est au rack de s'y adapter. Les docs constructeur le
# confirment (contrat §8 bis) : un ENGL Z9 ou un Diezel Columbus n'émettent QUE des Program
# Change, sans Note d'identité ni front de relâchement. Aucun réglage ne changera ça.
#
# Un descripteur appris porte donc une TABLE : (type, canal, numéro) -> intention.
_BOUND = {}          # (type, canal, numéro) -> intention, index construit par set_device()


def _index_bindings(bindings):
    idx = {}
    for b in bindings or []:
        ev, intent = b.get("event") or {}, b.get("intent") or {}
        if ev.get("type") and intent.get("kind"):
            idx[(ev["type"], int(ev.get("channel", 0)), int(ev.get("number", 0)))] = intent
    return idx


# ── ÉCOUTE : regarder sans agir ──────────────────────────────────────────────────────────────
# Sert à apprendre un pédalier inconnu. Deux règles, et les deux comptent :
#   · on n'agit PAS — sinon appuyer sur un switch pour le déclarer changerait le morceau ;
#   · on écoute TOUS LES CANAUX — le canal d'un appareil inconnu fait partie de ce qu'on apprend.
_LEARN = {"on": False, "seq": 0, "last": None, "seen": {}, "vals": {}}
_LEARN_MAX = 64


def learn_start():
    _LEARN.update(on=True, seq=0, last=None, seen={}, vals={})
    log.info("ÉCOUTE : le pédalier ne pilote plus rien, on note ce qu'il envoie")


def learn_stop():
    _LEARN["on"] = False
    log.info("écoute terminée")


def learn_state():
    """Ce que l'écran interroge : le dernier événement, et le RÉSUMÉ de ce qui a été vu.

    Le résumé est ce qui distingue une pédale d'expression d'un switch sans rien demander à
    l'utilisateur : un switch envoie deux valeurs (127 et 0), une pédale en balaie trente.
    """
    seen = [dict(v) for v in _LEARN["seen"].values()]
    seen.sort(key=lambda s: -s["count"])
    return {"on": _LEARN["on"], "seq": _LEARN["seq"], "last": _LEARN["last"], "seen": seen[:_LEARN_MAX]}


def _learn_note(ev):
    key = (ev["type"], ev["channel"], ev["number"])
    slot = _LEARN["seen"].get(key)
    if slot is None:
        slot = {"type": ev["type"], "channel": ev["channel"], "number": ev["number"],
                "count": 0, "min": 127, "max": 0, "values": 0}
        _LEARN["seen"][key] = slot
        _LEARN["vals"][key] = set()
    slot["count"] += 1
    v = ev.get("value")
    if isinstance(v, int):
        slot["min"] = min(slot["min"], v)
        slot["max"] = max(slot["max"], v)
        # Le NOMBRE DE VALEURS DISTINCTES est ce qui sépare un switch d'une pédale : un switch
        # en envoie deux (127 puis 0), une pédale en balaie des dizaines. On plafonne le comptage
        # — au-delà de quelques valeurs la réponse est déjà donnée, et un balayage continu
        # remplirait la mémoire pour rien.
        vals = _LEARN["vals"][key]
        if len(vals) <= 8:
            vals.add(v)
        slot["values"] = len(vals)
    _LEARN["seq"] += 1
    ev["seq"] = _LEARN["seq"]
    _LEARN["last"] = ev


def _learn_capture(line):
    m = _RE_NOTE.search(line)
    if m:
        vel = m.group(4)
        _learn_note({"type": "note", "channel": int(m.group(2)), "number": int(m.group(3)),
                     "value": int(vel) if vel is not None else 0,
                     "on": m.group(1) == "on" and vel is not None and int(vel) > 0})
        return
    m = _RE_PC.search(line)
    if m:
        _learn_note({"type": "pc", "channel": int(m.group(1)), "number": int(m.group(2)),
                     "value": int(m.group(2))})
        return
    m = _RE_CC.search(line)
    if m:
        _learn_note({"type": "cc", "channel": int(m.group(1)), "number": int(m.group(2)),
                     "value": int(m.group(3))})

_RE_PC   = re.compile(r"Program change\s+(\d+), program (\d+)")
_RE_CC   = re.compile(r"Control change\s+(\d+), controller (\d+), value (\d+)")
# Bench puce UnO 1.0.4 (2026-07-24, docs/archive/fcb1010-mapping.md) : les Notes arrivent SANS champ
# velocity et press ET release s'affichent tous deux « Note off » -> velocity optionnelle,
# fronts reconstruits par APPARIEMENT (1er événement = press, 2e = release).
_RE_NOTE = re.compile(r"Note (on|off)\s+(\d+), note (\d+)(?:, velocity (\d+))?")


def midi_line(message):
    """Convertit un message RtMidi dans le format déjà interprété par le lecteur."""
    if not message:
        return None
    status = message[0]
    channel = status & 0x0F
    kind = status & 0xF0
    if kind == 0xC0 and len(message) >= 2:
        return f"Program change {channel}, program {message[1]}"
    if kind == 0xB0 and len(message) >= 3:
        return f"Control change {channel}, controller {message[1]}, value {message[2]}"
    if kind in (0x80, 0x90) and len(message) >= 3:
        edge = "on" if kind == 0x90 and message[2] else "off"
        return f"Note {edge} {channel}, note {message[1]}, velocity {message[2]}"
    return None


def resolve_port(listing, transport, card_name):
    """Choisit le port du pédalier dans la sortie d'`aseqdump -l`, selon le TRANSPORT déclaré
    par le descripteur (docs/pedalboards.md §10). Pur, donc testable à froid.

      · din-soundcard (défaut) : le pédalier entre par le DIN de la carte son ACTIVE — on
        cherche la ligne de la carte (`card_name`, ex. « Volt 276 » ; repli « volt »).
      · usb : le pédalier EST son propre port ALSA (HX Stomp, Morningstar…) — on cherche
        `port_match` dans le nom. Avant ce champ, le lecteur était soudé au DIN : un pédalier
        USB n'était JAMAIS entendu, sans un mot de log (audit 2026-08-12 §3).

    Port absent (appareil débranché, motif vide) -> None : la boucle _supervise réessaie, comme
    elle l'a toujours fait pour un DIN manquant. Jamais d'exception.
    """
    kind = (transport or {}).get("kind") or "din-soundcard"
    if kind == "usb":
        want = ((transport or {}).get("port_match") or "").strip().lower()
        if not want:
            return None                 # motif manquant : introuvable, pas un crash
    else:
        want = (card_name or "volt").lower()
    for line in (listing or "").splitlines():
        if want in line.lower():
            m = re.match(r"\s*(\d+:\d+)", line)
            if m:
                return m.group(1)
    return None


_HOLD = threading.Event()        # port du pédalier rendu au système (flash Control Center)
_HOLD_TIMER = {"t": None}
HOLD_MAX_S = 15 * 60             # un oubli ne laisse pas le pédalier muet pour la soirée


def hold_ports(on):
    """Rend (on=True) ou reprend (False) le port MIDI d'ENTRÉE du pédalier — lecteur natif seulement
    (Windows, macOS). Sous Linux le séquenceur ALSA partage les ports : rien à rendre. Se lève tout
    seul au bout de HOLD_MAX_S."""
    t = _HOLD_TIMER["t"]
    if t is not None:
        t.cancel()
        _HOLD_TIMER["t"] = None
    if on:
        _HOLD.set()
        timer = threading.Timer(HOLD_MAX_S, lambda: hold_ports(False))
        timer.daemon = True
        timer.start()
        _HOLD_TIMER["t"] = timer
    else:
        _HOLD.clear()
        log.info("port du pédalier repris")
    if _READER is not None:
        _READER._rebind.set()
    return _HOLD.is_set()


def ports_held():
    return _HOLD.is_set()


class FootReader:
    def __init__(self, on_scene, on_stomp, on_recall=None, on_treadle=None, on_volume=None,
                 on_stomp_edge=None, on_select=None):
        self.on_scene = on_scene
        # on_scene(nom) ou on_scene(nom, valeur du CC) : la valeur sert aux switches de la rangée
        # des scènes flashés en `effect` (ils envoient un ÉTAT, 127/0 — 2026-09-21). Un appelant à
        # un seul argument (tests, anciens câblages) reste servi tel quel.
        try:
            import inspect
            ps = inspect.signature(on_scene).parameters.values()
            self._scene_val = (len(ps) >= 2) or any(p.kind == p.VAR_POSITIONAL for p in ps)
        except (TypeError, ValueError):
            self._scene_val = False
        self.on_stomp = on_stomp                    # signature (sw, want=None) : want = état absolu (FCB)
        # on_recall(slot, source) : source = "pc" (le pédalier annonce SA bank) | "select" (pavé
        # numérique — le pédalier n'a PAS bougé). La distinction décide du réalignement.
        self.on_recall = on_recall or (lambda slot, source=None: None)
        self.on_treadle = on_treadle or (lambda v: None)
        self.on_volume = on_volume or (lambda v: None)
        # fronts press/release des switches 1-10 (Note on/off) — gestes du looper (tap/double/long, boucles
        # en 1-4, play-all 5, kill 10) et des blocs pilotés par les fronts ; app.py tranche selon le preset
        self.on_stomp_edge = on_stomp_edge or (lambda sw, on: None)
        self.select_blocked = lambda sw: False      # posé par app.py : ce switch porte-t-il un geste du preset ?
        # on_select(info | None) : le mode sélection se MONTRE. Invisible, il avalait les appuis de
        # scène pendant 8 s sans que rien à l'écran ne le dise (2026-09-21).
        self.on_select = on_select or (lambda info: None)
        self._proc = None
        self._rebind = threading.Event()
        self._native_connected = threading.Event()
        self._sysex_lock = threading.Lock()
        self._sysex_queue = None
        self._note_down = {}                        # sw -> t press (appariement des Notes sans velocity)
        self._thread = None
        self._last_treadle = None
        self._last_volume = None
        self._stop = False
        self._retry = 3   # secondes entre deux tentatives de connexion
        # état machine appui-long / saisie chiffres
        self._mode = "normal"        # "normal" | "select"
        self._lp_timer = None        # Timer d'appui long (switch SELECT_SWITCH)
        self._sel_timer = None       # Timer d'abandon du mode sélection
        self._digits = []

    def _find_port(self):
        """Port seq d'écoute, selon le `transport` du descripteur actif (resolve_port).
        din-soundcard : le pied suit la carte du moment (gear-registry 2026-07-26, plus de
        « volt » en dur). usb : le pédalier est cherché par SON nom ALSA — sans passer par la
        carte son, dont il ne dépend pas."""
        env = os.environ.get("GOLEM_FCB_PORT")
        if env:
            return env
        a = shutil.which("aseqdump")
        if not a:
            return None
        try:
            out = subprocess.check_output([a, "-l"], text=True, timeout=2)   # port zombie = gel sinon
        except Exception:
            return None
        tr = _DEVICE.get("transport") or {}
        nm = None
        if (tr.get("kind") or "din-soundcard") != "usb":
            from . import midi_out
            _idx, nm = midi_out._active_card_midi()  # nom rawmidi de la carte active (« Volt 276 »…)
        return resolve_port(out, tr, nm)

    def start(self):
        global _READER
        from . import midi_out
        if midi_out.hw_midi_off():
            log.info("GOLEM_NO_HW_MIDI : lecteur pied désactivé (un banc n'écoute pas le pédalier du rack)")
            return False
        if sys.platform in ("win32", "darwin"):
            try:
                import rtmidi
            except ImportError as e:
                # ⚠ « absent » était FAUX une fois sur deux : sur un Windows vierge le paquet est
                # bien installé, c'est sa DLL qui ne se charge pas (pas de runtime Visual C++ —
                # mesuré sur la VM le 2026-10-01). On dit ce que Python a dit.
                log.warning("python-rtmidi ne se charge pas (%s) -> lecteur pied désactivé" % e)
                return False
            _READER = self
            self._thread = threading.Thread(target=self._supervise_rtmidi, daemon=True)
            self._thread.start()
            return True
        if not shutil.which("aseqdump"):
            log.warning("aseqdump absent (alsa-utils) -> lecteur pied désactivé (inject reste dispo)")
            return False
        _READER = self          # set_device() nous rebranche si le transport change
        self._thread = threading.Thread(target=self._supervise, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop = True
        self._rebind.set()
        if self._proc:
            self._proc.terminate()

    def rebind(self):
        """Force la re-résolution du port (changement de CARTE SON, gear-registry 2026-07-26) :
        tue l'aseqdump courant — la boucle _supervise se reconnecte au port de la nouvelle carte.
        Sans ça, l'ancien aseqdump reste accroché à un client seq mort (ou RECYCLÉ par ALSA :
        même numéro, autre carte — ça « marche » par accident jusqu'au jour où non)."""
        with contextlib.suppress(Exception):
            if self._proc:
                self._proc.terminate()
        self._rebind.set()

    def _native_port(self, names):
        """Résout un port par nom sans supposer les index persistants de WinMM/CoreMIDI."""
        tr = _DEVICE.get("transport") or {}
        kind = tr.get("kind") or "din-soundcard"
        from . import desktop_midi
        # un pédalier USB se cherche par SON nom (descripteur) ; un pédalier DIN est sur la prise MIDI IN
        # choisie dans Soundcard (desktop_midi : GOLEM_FCB_PORT d'abord, l'écran ensuite)
        if kind == "usb":
            want = os.environ.get("GOLEM_FCB_PORT") or tr.get("port_match") or ""
        else:
            want = (desktop_midi.din_port("in") or tr.get("port_match") or
                    os.environ.get("GOLEM_MIDI_PORT") or "")
        want = want.strip().lower()
        if not want or want.startswith("hw:"):
            return None
        return next(((i, name) for i, name in enumerate(names)
                     if want in name.lower() or desktop_midi.same(name, want)), None)

    def _supervise_rtmidi(self):
        """Écoute native avec reconnexion ; le callback MIDI ne fait aucun travail métier."""
        import rtmidi
        status = None
        while not self._stop:
            # TENU (hold_ports) : le port est rendu au système, pour qu'un autre logiciel s'y connecte
            # — Control Center, qui flashe la puce UnO2 sous Windows et macOS. Sous Windows un port
            # MIDI ne s'ouvre qu'UNE fois : tant que GoleM le tient, l'éditeur ne peut rien envoyer.
            if _HOLD.is_set():
                if status != "held":
                    log.info("port du pédalier rendu (flash par un autre logiciel)")
                    status = "held"
                self._rebind.wait(0.5)
                self._rebind.clear()
                continue
            midi_in = None
            try:
                midi_in = rtmidi.MidiIn(native_api(rtmidi), name="golem-foot")
                hit = self._native_port(midi_in.get_ports())
                if hit is None:
                    if status != "noport":
                        log.warning("port FCB introuvable — réessai auto…")
                        status = "noport"
                else:
                    idx, name = hit
                    messages = queue.SimpleQueue()
                    self._rebind.clear()

                    def receive(event, _data):
                        data = event[0]
                        if data and data[0] == 0xF0:
                            subscriber = self._sysex_queue
                            if subscriber is not None:
                                subscriber.put_nowait(event)
                            return
                        line = midi_line(data)
                        if line:
                            messages.put_nowait(line)

                    midi_in.ignore_types(sysex=False, timing=True, active_sense=True)
                    midi_in.open_port(idx, name="golem-foot")
                    midi_in.set_callback(receive)
                    self._native_connected.set()
                    status = "ok"
                    log.info("connecté au FCB (%s) : PC, CC et notes actifs" % name)
                    while not self._stop and not self._rebind.is_set() and not _HOLD.is_set():
                        try:
                            self._handle(messages.get(timeout=0.25))
                        except queue.Empty:
                            if name not in midi_in.get_ports():
                                break
            except Exception as e:
                if status != "busy":
                    log.warning("port MIDI du pédalier indisponible : %s" % e)
                    status = "busy"
            finally:
                self._native_connected.clear()
                if midi_in is not None:
                    with contextlib.suppress(Exception):
                        midi_in.cancel_callback()
                        midi_in.close_port()
            if not self._stop:
                self._rebind.wait(self._retry)
                self._rebind.clear()


    def _supervise(self):
        """Boucle auto-réparante : (re)connecte aseqdump dès que le device FCB est disponible.
        Utile car Reaper peut tenir le device MIDI du Volt en exclusif (le foot se connecte
        automatiquement dès que Reaper le libère — pas besoin de relancer le bridge)."""
        status = None   # évite de spammer le log (ok / busy / noport)
        while not self._stop:
            port = self._find_port()
            if not port:
                if status != "noport":
                    log.warning("port FCB introuvable — réessai auto…"); status = "noport"
                time.sleep(self._retry); continue
            connected = lost = False
            try:
                cmd = ["aseqdump", "-p", port]
                if shutil.which("stdbuf"):
                    cmd = ["stdbuf", "-oL"] + cmd   # line-buffering : sinon stdout bloc-bufferisé en pipe -> events retardés
                self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                              stderr=subprocess.STDOUT, text=True, bufsize=1,
                                              preexec_fn=_die_with_parent)   # pas d'aseqdump zombie après un reload
                for line in self._proc.stdout:
                    if "Waiting for data" in line:
                        connected = True; status = "ok"
                        log.info("connecté au FCB (aseqdump -p %s) : PC->slot, CC20-24->scène, CC30-34->stomp, Note->id" % port)
                        continue
                    if "Cannot connect" in line:
                        break
                    if "Port unsubscribed" in line:
                        # ⚠ LE PÉDALIER SOURD QUI SE CROIT BRANCHÉ. Quand le port source disparaît
                        # (carte son ré-énumérée, câble USB), aseqdump l'écrit — et RESTE VIVANT,
                        # abonné à rien : au retour de la carte personne ne le rebranche. Mesuré le
                        # 2026-10-01 : audio réparé tout seul, `midi ok` à l'écran, et plus un
                        # switch n'arrivait. Cette ligne tombait dans _handle, qui l'ignorait.
                        lost = True
                        break
                    self._handle(line)
            except Exception as e:
                log.warning("erreur aseqdump: %s" % (e,))
            if lost:
                with contextlib.suppress(Exception):
                    self._proc.terminate()                  # il ne sortira pas de lui-même
                log.warning("le port MIDI du pédalier a disparu (%s) — reconnexion auto…" % port)
                status = "lost"
                if ((_DEVICE.get("transport") or {}).get("kind") or "din-soundcard") != "usb":
                    # pédalier en DIN : la sortie MIDI vit sur la MÊME carte, et rtmidi reste
                    # abonné à un client mort sans lever la moindre erreur à l'envoi
                    from . import midi_out as _mo
                    _mo.reset_ports()
            if not connected and status != "busy":
                log.warning("port MIDI du pédalier occupé (%s — Reaper tient l'entrée ?) — réessai auto…"
                            % port); status = "busy"
            time.sleep(self._retry)

    # ── résolution par TABLE (pédalier appris) ──────────────────────────────────
    def _handle_bound(self, line):
        """Dispatche via la table de liaisons. Rend True si l'événement a été traité.

        Un événement non lié n'est PAS une erreur : un pédalier envoie souvent plus que ce
        qu'on lui a demandé (une bank qu'on n'utilise pas, un switch non déclaré). On rend
        False, et le chemin codé prend le relais — ou l'événement finit ignoré, tracé.
        """
        m = _RE_NOTE.search(line)
        if m:
            vel = m.group(4)
            on = m.group(1) == "on" and vel is not None and int(vel) > 0
            return self._fire(("note", int(m.group(2)), int(m.group(3))), 127 if on else 0, on)
        m = _RE_PC.search(line)
        if m:
            return self._fire(("pc", int(m.group(1)), int(m.group(2))), int(m.group(2)), True)
        m = _RE_CC.search(line)
        if m:
            val = int(m.group(3))
            return self._fire(("cc", int(m.group(1)), int(m.group(2))), val, val >= 64)
        return False

    def _fire(self, key, value, on):
        intent = _BOUND.get(key)
        if intent is None:
            return False
        note_heard()
        try:                                              # lot 8 : chaque message lié, sans nom
            from . import diag as _diag
            _diag.event("foot", msg=key[0], n=int(key[2]))
        except Exception:
            pass
        kind = intent.get("kind")
        if kind == "scene":
            if not on:
                return True                         # relâchement : la scène est déjà posée
            log.info("%s%d ch%d -> scène %s" % (key[0].upper(), key[2], key[1] + 1,
                                                intent.get("name")))
            self.on_scene(intent.get("name"))
        elif kind == "stomp":
            sw = int(intent.get("switch", 0))
            log.info("%s%d ch%d -> stomp switch %d %s" % (key[0].upper(), key[2], key[1] + 1,
                                                          sw, "ON" if on else "OFF"))
            # Un appareil qui ne sait pas alterner 127/0 (un Program Change, par exemple) n'a pas
            # d'état à donner : on bascule. `absolute` dit lequel des deux cas on a appris.
            self.on_stomp(sw, on if intent.get("absolute") else None)
            self._on_note_edge(sw, on) if intent.get("edges") else None
        elif kind == "slot":
            slot = intent["slot"] if "slot" in intent else value
            log.info("%s%d ch%d -> recall slot %d" % (key[0].upper(), key[2], key[1] + 1, slot))
            self.on_recall(int(slot), "pc")
        elif kind == "expression":
            pedal = int(intent.get("pedal", 1))
            (self.on_volume if pedal == 1 else self.on_treadle)(value)
        else:
            return False
        return True

    def _on_note_edge(self, sw, on):
        """Fronts d'un switch appris qui en porte (gestes du looper, appui long)."""
        if on:
            self._note_down[sw] = time.monotonic()
        else:
            self._note_down.pop(sw, None)
        self.on_stomp_edge(sw, on)

    # ── injection (tests sans pédalier) ─────────────────────────────────────────
    def feed(self, line):
        """Rejoue une ligne aseqdump synthétique (endpoint /api/foot/inject).

        ⚠ N'ARME PAS le témoin « le pédalier a parlé » : une injection vient du rack, pas du
        pied. Sans ça, lancer check-foot.py rendait `foot_heard` frais et le diagnostic
        répondait « le pédalier émet » à quelqu'un dont le câble est débranché — c'est-à-dire
        qu'il mentait exactement dans le cas pour lequel il existe (vu le 2026-08-07)."""
        keep = _HEARD["t"]
        try:
            self._handle(line)
        finally:
            _HEARD["t"] = keep

    # ── parsing ─────────────────────────────────────────────────────────────────
    def _handle(self, line):
        # Blindé : une exception d'un callback ne doit JAMAIS tuer la boucle de lecture aseqdump
        # (sinon = déconnexion du FCB en plein set — audit 2026-07-07 P1).
        try:
            # ÉCOUTE : on regarde sans agir. Le pédalier ne doit RIEN piloter pendant qu'on
            # l'apprend — sinon appuyer sur un switch pour le déclarer changerait le morceau.
            # Et on écoute TOUS LES CANAUX : d'un appareil inconnu, on ne sait pas encore
            # lequel il utilise. C'est justement une des choses qu'on apprend.
            if _LEARN["on"]:
                _learn_capture(line)
                return
            # kill-switch de l'input map (Soundcard v2) : MIDI IN = None -> tout événement
            # entrant est ignoré (un câble parasite ne pilote plus rien). Lecture cachée
            # sur mtime — coût ~stat() par événement.
            from . import inputmap as _imap
            if _imap.din_role("midi_in") == "none":
                return
            if _DEVICE.get("bindings"):
                if self._handle_bound(line):
                    return
            m = _RE_NOTE.search(line)
            if m:
                if int(m.group(2)) != _DEVICE["wire_channel"]:
                    return                                  # écho THRU (Whammy, remote…) — pas le pied
                note_heard()
                sw = int(m.group(3)) - _DEVICE["note_base"] + 1   # note du fil -> switch 1-10
                vel = m.group(4)
                explicit_on = (m.group(1) == "on") and vel is not None and int(vel) > 0
                if _DEVICE["note_edges"] == "paired":
                    # ⚠ RATTRAPAGE SPÉCIFIQUE À LA 1.0.4 : cette puce affiche l'appui ET le
                    # relâchement en « Note off », souvent sans vélocité. Les fronts sont donc
                    # reconstruits par appariement : 1er événement = press, 2e = release.
                    # L'appliquer à une puce qui émet des fronts francs INVERSERAIT les gestes —
                    # c'est pour ça que le travers est déclaré dans le descripteur, pas deviné.
                    on = explicit_on or sw not in self._note_down
                else:
                    # Fronts francs (UnO2) : un NoteOn de vélocité non nulle est un appui, tout
                    # le reste est un relâchement. Aucun état n'est nécessaire pour décider —
                    # donc une perte de message se rattrape au coup suivant, au lieu d'inverser
                    # ce switch jusqu'au prochain redémarrage.
                    on = explicit_on
                if on:
                    self._note_down[sw] = time.monotonic()
                else:
                    self._note_down.pop(sw, None)
                self._on_note(sw, on)
                # ── UN SWITCH QUI NE RELÂCHE JAMAIS EST UN TAP, PAS UN APPUI SANS FIN ────────
                # ⚠ Sans ça, un geste À DURÉE n'est pas inopérant : il est INCONTRÔLABLE. La
                # minuterie armée à l'appui n'est jamais annulée, donc elle FINIT PAR PARTIR.
                # Mesuré le 2026-08-07 : sur un stomp `effect` (SW6-9), zéro relâchement — le
                # « hold = clear this loop » du looper effaçait donc la boucle 0,6 s après le
                # 3e appui, sans que personne n'ait rien tenu. Le backing, la batterie et les
                # samples arment le même genre de minuterie.
                # On synthétise le relâchement TOUT DE SUITE : la sémantique devient celle que
                # le switch a vraiment — un tap. Les gestes de durée deviennent impossibles
                # (plutôt qu'aléatoires) et, bonus mesuré à la lecture des moteurs, les actions
                # qui vivaient dans la branche « release » (stop, overdub) REDEVIENNENT
                # accessibles. Un switch qui relâche pour de bon n'est pas touché.
                es = _DEVICE.get("edge_switches")
                if on and es is not None and sw not in es:
                    self._note_down.pop(sw, None)
                    self._on_note(sw, False)
                return
            m = _RE_PC.search(line)
            if m:
                if int(m.group(1)) != _DEVICE["wire_channel"]:
                    return                                  # écho THRU — pas le pied
                note_heard()
                self._on_pc(int(m.group(2)))
                return
            m = _RE_CC.search(line)
            if m:
                if int(m.group(1)) != _DEVICE["wire_channel"]:
                    return                                  # écho THRU — pas le pied
                note_heard()
                self._on_cc(int(m.group(2)), int(m.group(3)))
                return
        except Exception as e:
            log.warning("erreur handler (event ignoré) : %s | %s" % (e, line.strip()))

    def _on_pc(self, slot):
        if self._mode == "select":
            return                                  # en sélection, on ignore les PC/CC (on lit les Notes = chiffres)
        # source="pc" : le PÉDALIER est déjà sur cette bank, c'est lui qui nous l'annonce. Le rack
        # ne doit surtout pas lui répondre un « va à la bank n » — ce serait une boucle.
        log.info("PC%d -> recall slot %d" % (slot, slot))
        self.on_recall(slot, "pc")

    def _on_cc(self, cc, val):
        if cc == TREADLE_CC:
            if val != self._last_treadle:           # dédup : évite le flood amidi
                self._last_treadle = val
                log.info("CC11 EXP2 -> %d" % val)   # rôle (volume|bloc) résolu par app.py
                self.on_treadle(val)
            return
        if cc == VOLUME_CC:
            # ⚠ SYMÉTRIE DE TRACE (2026-08-04) : EXP1 ne s'imprimait PAS, contrairement à EXP2.
            # Au bench UnO2, l'absence de ligne « EXP1 » m'a fait diagnostiquer une pédale morte
            # et envoyer le mainteneur calibrer — alors qu'elle marchait. Un canal qu'on ne trace pas est
            # un canal qu'on croit muet : les deux pédales se logent, ou aucune.
            if val != self._last_volume:            # même dédup que le treadle (anti-flood)
                self._last_volume = val
                log.info("CC7 EXP1 -> %d" % val)
            self.on_volume(val); return
        if self._mode == "select":
            return                                  # scène/stomp ignorés pendant la saisie de chiffres
        if cc in SCENE_CC:
            log.info("CC%d(%d) -> scène %s" % (cc, val, SCENE_CC[cc]))
            if self._scene_val:
                self.on_scene(SCENE_CC[cc], val)
            else:
                self.on_scene(SCENE_CC[cc])
        elif cc in STOMP_CC:
            # puce UnO (toggling activé) : CC alterné 127/0 = l'ÉTAT de la LED du stomp.
            # On le passe en ORDRE ABSOLU (127=ON, 0=OFF) : LED et son ne peuvent plus être
            # inversés — au pire un appui à vide se réaligne après un recall (cf. cues-format §2).
            from . import foot_leds
            if foot_leds.on_stomp_cc(STOMP_CC[cc], val >= 64):
                # ÉCHO d'un appui à distance (diode alignée par le rack) : la puce le renvoie comme un coup de pied —
                # le suivre allumerait TOUS les blocs d'un switch partagé. On l'avale (docs/pedalboards.md § Diodes).
                log.info("CC%d(%d) -> écho de l'appui à distance sur SW%d, avalé" % (cc, val, STOMP_CC[cc]))
                return
            log.info("CC%d(%d) -> stomp switch %d %s" % (cc, val, STOMP_CC[cc], "ON" if val >= 64 else "OFF"))
            self.on_stomp(STOMP_CC[cc], val >= 64)
        else:
            log.info("CC%d=%d reçu (non mappé)" % (cc, val))

    def _on_note(self, sw, on):
        if self._mode == "select":
            if on:
                self._collect_digit(sw)
            return
        # mode normal : fronts de la rangée du fond 6-10 (press ET release) -> gestes du preset (stomps,
        # kill du looper en 10 ; app.py décide ; les CC30-34 n'ont pas de release, seules les Notes portent
        # la durée). La rangée des scènes (1-5, où vivent les boucles) est traitée juste après.
        if 6 <= sw <= 10:
            from . import foot_leds
            if on and foot_leds.on_stomp_note(sw):
                return                                      # la Note de l'écho d'un appui à distance
            self.on_stomp_edge(sw, on)
            return
        # ⚠ RANGÉE DES SCÈNES (1-5) : les fronts doivent passer AUSSI. Corrigé le 2026-08-07.
        # Un bloc piloté par les FRONTS (standard, sample, batterie, arrangement) qui revendique
        # un switch de cette rangée n'était déclenché par PERSONNE : le chemin CC lui cédait la
        # main (« les fronts s'en occupent », app.py::_do_stomp) et les fronts s'arrêtaient à 6.
        # L'appui ne faisait rien, sans une ligne de log — mesuré sur « ZZ Conflict », bloc
        # Standard en switch 5. Seuls le tuner et le Rec marchaient, parce qu'ils passent par le CC.
        # Ce lecteur ne connaît pas les revendications (c'est de l'état de preset) : on transmet,
        # app.py tranche et ignore si personne ne revendique.
        if 1 <= sw <= 5:
            self.on_stomp_edge(sw, on)
        # seul le switch SELECT sert à armer l'appui long — sauf s'il porte une BOUCLE (amendement looper du
        # 2026-10-14) : son appui long efface la boucle, il ne doit pas ouvrir la saisie de bank en plus
        if sw != SELECT_SWITCH or self.select_blocked(sw):
            return
        if on:
            self._cancel_timer("_lp_timer")
            self._lp_timer = threading.Timer(LONGPRESS_S, self._enter_select)
            self._lp_timer.daemon = True
            self._lp_timer.start()
        else:
            self._cancel_timer("_lp_timer")         # relâché avant le seuil -> appui court (la scène a déjà été jouée)

    # ── machine appui-long / saisie 2 chiffres ──────────────────────────────────
    def _enter_select(self):
        self._mode = "select"
        self._digits = []
        log.info("appui long switch %d -> MODE SÉLECTION (tape 2 chiffres)" % SELECT_SWITCH)
        self._cancel_timer("_sel_timer")
        self._sel_timer = threading.Timer(SELECT_TIMEOUT_S, self._cancel_select)
        self._sel_timer.daemon = True
        self._sel_timer.start()
        self._publish_select()

    def _publish_select(self):
        info = None
        if self._mode == "select":
            info = {"digits": list(self._digits), "timeout_s": SELECT_TIMEOUT_S, "switch": SELECT_SWITCH}
        try:
            self.on_select(info)
        except Exception as e:                       # l'affichage ne doit jamais casser le pied
            log.warning("affichage du mode sélection : %s" % (e,))

    def cancel_select(self):
        """Sortie par l'ÉCRAN (bouton Cancel du bandeau) : un mode qu'on voit doit se quitter."""
        if self._mode == "select":
            log.info("sélection annulée (écran)")
            self._exit_select()

    def _collect_digit(self, sw):
        d = DIGIT_OF_SWITCH.get(sw)
        if d is None:
            return
        self._digits.append(d)
        log.info("sélection : chiffre %d (%s)" % (d, "".join(map(str, self._digits))))
        self._cancel_timer("_sel_timer")             # chaque chiffre relance le chrono
        self._sel_timer = threading.Timer(SELECT_TIMEOUT_S, self._cancel_select)
        self._sel_timer.daemon = True
        self._sel_timer.start()
        if len(self._digits) < 2:
            self._publish_select()
        if len(self._digits) >= 2:
            slot = self._digits[0] * 10 + self._digits[1]
            self._exit_select()
            # source="select" : le pavé numérique déplace le RACK, et le pédalier reste sur SA
            # bank. C'est le seul geste du pied qui demande un réalignement — sans lui, le premier
            # appui de scène renvoie l'ancien PC et ramène le rack en arrière (roadmap §0.d).
            log.info("sélection -> recall slot %d" % slot)
            self.on_recall(slot, "select")

    def _cancel_select(self):
        log.info("sélection abandonnée (timeout)")
        self._exit_select()

    def _exit_select(self):
        self._mode = "normal"
        self._digits = []
        self._cancel_timer("_sel_timer")
        self._publish_select()

    def _cancel_timer(self, attr):
        t = getattr(self, attr, None)
        if t:
            t.cancel()
            setattr(self, attr, None)


class _SysexStream:
    """Adaptateur minimal pour la sonde d'identité de pedalboard.py."""
    def __init__(self, reader, events):
        self.reader, self.events = reader, events

    def get_message(self):
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def close_port(self):
        with self.reader._sysex_lock:
            if self.reader._sysex_queue is self.events:
                self.reader._sysex_queue = None


def native_sysex_stream(timeout=4):
    """Abonne la sonde au port déjà ouvert par le lecteur, sans deuxième client WinMM."""
    reader = _READER
    if reader is None or sys.platform not in ("win32", "darwin"):
        return None
    events = queue.SimpleQueue()
    with reader._sysex_lock:
        if reader._sysex_queue is not None:
            return None
        reader._sysex_queue = events
    if not reader._native_connected.wait(timeout):
        with reader._sysex_lock:
            if reader._sysex_queue is events:
                reader._sysex_queue = None
        return None
    return _SysexStream(reader, events)
