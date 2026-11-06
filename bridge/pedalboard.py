# SPDX-License-Identifier: GPL-3.0-or-later
"""Quel pédalier est branché — et ce que le rack en déduit.

Contrat : `docs/pedalboards.md`. Trois objets, et le découpage est tout l'enjeu :

    config/pedalboard/contract.json        l'INTENTION — sans appareil, sans canal, sans octet
    config/pedalboard/devices/<id>.json    le DESCRIPTEUR — canal, travers, capacités, recette
    config/.pedalboard.json                l'ÉTAT — l'appareil déclaré, la dernière sonde

Sans ce module, des faits d'appareil vivaient dans du code (`CONTRACT_WIRE_CHANNEL` en dur) et
dans des phrases d'écran écrites à la main. Ressouder l'autre puce rendait alors le rack sourd,
sans une ligne de log.

── LA SONDE, ET SA LIMITE ────────────────────────────────────────────────────────────────
La UnO2 répond à la demande d'identité SysEx (mesuré : type 8, firmware 2.0, série 2-211).
La 1.0.4 ne répond à rien — DIN muette, c'est la raison d'être du registre de pédales.

> **Le silence n'identifie personne : il élimine la UnO2.**

D'où l'ordre : on sonde ; si ça répond, c'est MESURÉ (avec firmware et série) ; sinon on retient
l'appareil DÉCLARÉ. L'écran doit toujours distinguer les deux — confondre une mesure et une
déclaration, c'est chercher la panne au mauvais étage.
"""
import json
import os
import re
import sys
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("pedalboard")

PEDALBOARD_DIR = os.path.join(C.CONFIG_DIR, "pedalboard")
CONTRACT_FILE = os.path.join(PEDALBOARD_DIR, "contract.json")
DEVICES_DIR = os.path.join(PEDALBOARD_DIR, "devices")
STATE_FILE = os.path.join(C.CONFIG_DIR, ".pedalboard.json")

# Plus d'appareil par défaut (2026-11-03) : « fcb1010-uno2 » était le pédalier du rack de développement, et une
# install neuve sans pédalier affichait « FCB1010 · declared, not confirmed » (golem doctor, Health). Sans
# déclaration ni mesure, c'est FALLBACK : « no pedalboard declared ». Une puce qui répond à la sonde reste
# reconnue toute seule (source "measured").
PROBE_TIMEOUT = 2.0

# Ce que le lecteur suppose si TOUT manque (fichiers effacés, install à moitié faite). On prend
# la puce en place : un défaut qui décrit le rack tel qu'il est se remarque moins vite qu'une
# panne, mais il ne fabrique pas de silence.
FALLBACK = {"id": "unknown", "name": "unknown pedalboard", "channel": 2,
            "quirks": {"note_edges": "clean", "note_base": 0},
            "capabilities": {}, "load": {}}

_LOCK = threading.Lock()
_CACHE = {}                 # chemin -> (mtime, contenu)
_ON_CHANGE = []             # rappels à jouer quand l'appareil actif change


def on_change(fn):
    """Enregistre un rappel joué quand l'appareil actif change (foot.py s'y abonne)."""
    _ON_CHANGE.append(fn)


def _load(path, default=None):
    """Lecture cachée sur mtime — appelée souvent, et tolérante : un fichier illisible ne doit
    pas empêcher le rack de démarrer."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return default
    hit = _CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf8") as fh:
            data = json.load(fh)
    except Exception as e:
        log.warning("%s illisible : %s" % (os.path.basename(path), e))
        return default
    _CACHE[path] = (mt, data)
    return data


def contract():
    """L'intention — ce que GoleM veut d'un pédalier, quel qu'il soit."""
    return _load(CONTRACT_FILE, {}) or {}


def devices():
    """Tous les descripteurs connus, par id."""
    out = {}
    try:
        names = sorted(os.listdir(DEVICES_DIR))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        d = _load(os.path.join(DEVICES_DIR, name))
        if d and d.get("id"):
            out[d["id"]] = d
    return out


def device(device_id):
    return devices().get(device_id)


def _state():
    return _load(STATE_FILE, {}) or {}


def _write_state(st):
    try:
        from . import store
        store._write_json_atomic(STATE_FILE, st, indent=1, newline=True)
        _CACHE.pop(STATE_FILE, None)
    except Exception as e:
        log.warning("état non écrit : %s" % (e,))


# ── résolution ───────────────────────────────────────────────────────────────────────────

def active():
    """L'appareil actif, et SUR QUELLE BASE on le dit.

    Rend un dict : id · name · device (le descripteur) · source ("measured"|"declared"|
    "fallback") · firmware · serial · probed_at. `source` n'est pas décoratif : c'est la
    différence entre « la puce l'a dit » et « quelqu'un l'a coché ».
    """
    known = devices()
    st = _state()
    probe = st.get("probe") or {}
    found = probe.get("found")
    if found and found in known:
        # `stale` : mesuré, mais la dernière sonde n'a pas confirmé. On CONTINUE de s'en servir
        # (le canal est le bon) et on le DIT — cf. la décision renversée dans probe().
        return {"id": found, "name": known[found].get("name", found), "device": known[found],
                "source": "measured", "firmware": probe.get("firmware"),
                "serial": probe.get("serial"), "probed_at": probe.get("at"),
                "stale": bool(probe.get("stale")), "last_fail": probe.get("last_fail")}
    declared = st.get("declared")
    if declared in known:
        return {"id": declared, "name": known[declared].get("name", declared),
                "device": known[declared], "source": "declared", "firmware": None,
                "serial": None, "probed_at": probe.get("at")}
    return {"id": FALLBACK["id"], "name": FALLBACK["name"], "device": FALLBACK,
            "source": "fallback", "firmware": None, "serial": None, "probed_at": None}


def select(device_id):
    """Déclare l'appareil branché à la main. Efface la sonde : une déclaration explicite prime
    sur une mesure périmée — sinon changer d'avis serait impossible sans débrancher."""
    if device_id not in devices():
        raise ValueError("unknown pedalboard: %s" % device_id)
    st = _state()
    st["declared"] = device_id
    st.pop("probe", None)
    _write_state(st)
    _notify()
    return active()


def _notify():
    for fn in list(_ON_CHANGE):
        try:
            fn(active())
        except Exception as e:
            log.warning("rappel de changement en échec : %s" % (e,))


# ── la sonde ─────────────────────────────────────────────────────────────────────────────

def probe(timeout=PROBE_TIMEOUT):
    """Demande au pédalier de s'identifier. Rend le dict de sonde, ou None.

    On émet par le chemin de sortie habituel (midi_out, avec son filet) et on écoute par un
    port rtmidi distinct sous Linux (ALSA accepte plusieurs clients). Sur Windows/macOS,
    la sonde reçoit les SysEx via le lecteur déjà connecté au port natif.
    """
    try:
        import rtmidi
    except Exception:
        log.warning("python-rtmidi absent -> sonde indisponible, appareil DÉCLARÉ seulement")
        return None
    from . import midi_out
    if midi_out.hw_midi_off():
        return None                     # un banc ne sonde pas le pédalier du rack d'à côté

    # On ne sonde qu'avec les appareils qui savent répondre. Les autres n'ont pas de `probe`,
    # et leur silence ne prouverait rien de toute façon.
    candidates = [d for d in devices().values() if d.get("identity", {}).get("probe")]
    if not candidates:
        return None

    port_hint = (midi_out.find_port() or "")
    midi_in = None
    try:
        if sys.platform in ("win32", "darwin"):
            from . import foot
            midi_in = foot.native_sysex_stream()
            if midi_in is None:
                log.warning("port MIDI du pédalier non connecté -> sonde impossible")
                return None
        else:
            from .midi_api import native_api
            midi_in = rtmidi.MidiIn(native_api(rtmidi), name="golem-probe")
            midi_in.ignore_types(sysex=False, timing=True, active_sense=True)
            want = os.environ.get("GOLEM_MIDI_PORT", "") or "volt"
            want = ("" if want.startswith("hw:") else want).lower() or "volt"
            opened = False
            for i, name in enumerate(midi_in.get_ports()):
                if want in name.lower():
                    midi_in.open_port(i, name="probe")
                    opened = True
                    break
            if not opened:
                log.warning("aucun port MIDI d'entrée « %s » -> sonde impossible" % want)
                return None

        for cand in candidates:
            spec = cand["identity"]["probe"]
            midi_out.send_sysex(bytes(spec["request"]))
            hit = _await_identity(midi_in, spec, timeout)
            if hit:
                hit["found"] = cand["id"]
                hit["at"] = int(time.time())
                hit["port"] = port_hint
                with _LOCK:
                    st = _state()
                    st["probe"] = hit
                    _write_state(st)
                log.info("MESURÉ : %s — firmware %s, série %s"
                         % (cand["name"], hit.get("firmware"), hit.get("serial")))
                _notify()
                return hit
    except Exception as e:
        log.warning("sonde MIDI indisponible : %s" % e)
        return None
    finally:
        if midi_in is not None:
            try:
                midi_in.close_port()
            except Exception as _e:
                _swallowed(_e)

    # ── PERSONNE N'A RÉPONDU : ON GARDE LA MESURE, ON LA MARQUE NON CONFIRMÉE ──────────────
    # ⚠ DÉCISION RENVERSÉE (2026-08-08). Le code effaçait la sonde, au motif que « garder une
    # mesure périmée ferait croire à une identité qui n'est plus là ». Le raisonnement se tient
    # dans l'absolu ; la mesure le contredit.
    # Ce qui s'est passé : au démarrage du bridge la sonde n'a pas pu joindre la puce (MIDI
    # occupé), la mesure a été effacée, et le repli a choisi le DÉCLARÉ — une 1.0.4, canal 1,
    # fronts appariés — alors qu'une UnO2 (canal 2, fronts francs) était branchée. Le rack a
    # cessé d'entendre le pédalier ENTIÈREMENT, et s'est mis à agir sur les Program Change de
    # l'écho THRU du Whammy, qui vit justement sur le canal 1. Pédalier sourd, gestes fantômes,
    # et rien nulle part pour le dire.
    # Les deux erreurs ne coûtent PAS la même chose : une mesure périmée se trompe de NOM (et
    # tombe juste sur le canal neuf fois sur dix), un repli se trompe de CANAL — et un canal
    # faux, c'est un pédalier mort. On garde donc, et on marque `stale` pour que l'écran le dise.
    # Un `select()` explicite continue d'effacer la sonde : une déclaration prime toujours.
    with _LOCK:
        st = _state()
        pr = st.get("probe")
        if pr and pr.get("found"):
            pr["stale"] = True
            pr["last_fail"] = int(time.time())
            st["probe"] = pr
            _write_state(st)
            _notify()
            log.warning("aucune réponse -> on GARDE « %s » (mesuré le %s), marqué NON "
                        "CONFIRMÉ. Effacer aurait basculé sur le déclaré, au canal peut-être différent."
                        % (pr["found"], pr.get("at")))
        else:
            log.warning("aucune réponse à la demande d'identité -> appareil DÉCLARÉ (%s)"
                        % active()["id"])
    return None


def _await_identity(midi_in, spec, timeout):
    """Attend une réponse d'identité conforme. Ignore tout le reste — l'écho THRU nous renvoie
    nos propres octets, et le pied reste libre d'émettre un appui pendant l'attente."""
    prefix = list(spec.get("reply_prefix", []))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = midi_in.get_message()
        if msg is None:
            time.sleep(0.002)
            continue
        data = list(msg[0])
        if len(data) != spec.get("reply_len") or data[:len(prefix)] != prefix:
            continue
        if data[spec["device_byte"]] != spec["device_id"]:
            continue
        ver = data[spec["version_byte"]]
        lo, hi = spec.get("serial_bytes", [0, 0])
        return {"firmware": "%d.%d" % (ver >> 4, ver & 0x0F),
                "serial": "%d-%d" % (data[lo] >> 1, data[hi] + 128 * (data[lo] & 1))}
    return None


# ── piloter le pédalier ──────────────────────────────────────────────────────────────────
# Où l'on CROIT que le pédalier se trouve. Cette mémoire vit ICI, avec l'ordre qui la modifie :
# la garder ailleurs laissait un chemin (le banc /goto) déplacer le pédalier sans que le rack le
# sache, donc un alignement légitime pouvait ensuite être sauté comme « déjà bon ».
#
# ⚠ INVARIANT : on n'écrit ici que sur des MOTIFS. Deux seulement —
#   1. le pédalier a annoncé sa bank (PC entrant) : fait établi, il fait autorité ;
#   2. on lui a envoyé un ordre ET la sonde a prouvé qu'on l'atteint.
# Tout le reste est une supposition, et une supposition enregistrée devient un mensonge que
# personne ne vient corriger. Cf. `_link_proven`.
_BELIEVED = {"slot": None}


def believed_slot():
    return _BELIEVED["slot"]


def _link_proven():
    """Le rack ATTEINT-IL le pédalier ? Seule la sonde d'identité en fait la preuve.

    C'est le seul aller-retour complet du système : on émet un SysEx par la sortie DIN et la
    puce répond par l'entrée. Tout le reste du dialogue est à sens unique, et le MIDI n'accuse
    jamais réception — un `control_change()` qui rend True dit seulement que les octets ont
    quitté le port, pas que quelqu'un les a reçus.

    `stale` = la dernière sonde est restée sans réponse, donc la sortie DIN ne mène pas (ou
    plus) au pédalier. C'est le cas quand le câble est sur un autre appareil — configuration de
    JEU normale sur un rig à une seule sortie DIN, pas une panne.
    """
    act = active()
    return act.get("source") == "measured" and not act.get("stale")


def note_foot_bank(slot):
    """Le pédalier a annoncé SA bank (PC entrant) : il fait autorité sur notre mémoire."""
    _BELIEVED["slot"] = slot


def goto_bank(slot):
    """Aligne le pédalier sur `slot`. Rend True si l'ordre est parti.

    C'est le retour du lien, qui n'a longtemps existé que dans un sens : le pédalier parlait au
    rack, le rack ne lui répondait jamais. D'où le bug du pavé numérique — on sautait au slot 03,
    le pédalier restait sur SA bank, et le premier appui de scène renvoyait l'ancien PC qui
    ramenait le rack en arrière (roadmap §0.d).

    ⚠ L'appelant décide QUAND aligner, pas cette fonction. Recaler le pédalier après un PC qu'il
    vient d'émettre créerait une boucle de rétroaction : on ne réaligne jamais contre le pied.

    L'écho THRU nous renverra cet ordre ; il est inoffensif, le lecteur ne retient que le canal
    du contrat et celui-ci part sur le canal de télécommande.
    """
    act = active()
    caps = (act["device"].get("capabilities") or {}).get("goto_bank") or {}
    if not caps.get("supported"):
        return False
    ch = int(caps.get("channel", 0))
    value = int(slot) + int(caps.get("index_base", 0))
    if not (1 <= ch <= 16 and 0 <= value <= 127):
        log.warning("goto bank %r impossible (canal %r, valeur %r)" % (slot, ch, value))
        return False
    from . import midi_out
    ok = midi_out.control_change(int(caps.get("controller", 0)), value, channel=ch)
    if ok:
        log.info("goto bank %d (CC%d = %d, canal %d)"
                 % (slot, int(caps.get("controller", 0)), value, ch))
        # `ok` ne dit QUE « les octets ont quitté le port ». Sans preuve qu'ils arrivent, on
        # n'enregistre rien : sinon l'alignement suivant se croirait « déjà bon » et ne partirait
        # même plus — le rack cesserait d'essayer sans avoir jamais réussi une seule fois.
        if _link_proven():
            _BELIEVED["slot"] = slot
        else:
            log.warning("... lien NON prouvé (sonde muette) -> position non enregistrée, "
                        "on réessaiera au prochain alignement")
    return bool(ok)


# ── apprendre un pédalier inconnu ────────────────────────────────────────────────────────

def save_learned(name, bindings, channel, edges=True, notes=None):
    """Écrit un descripteur APPRIS et le rend actif. Rend son id.

    Sa provenance est `measured` : ce fichier ne vient pas d'un manuel, il vient de ce que
    l'appareil a réellement envoyé pendant qu'on appuyait dessus. C'est la seule sorte de
    descripteur dont on puisse dire ça sans mentir.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-") or "pedalier"
    known = devices()
    base, n = slug, 2
    while slug in known:                             # ne jamais écraser un descripteur existant
        slug, n = "%s-%d" % (base, n), n + 1
    doc = {
        "id": slug,
        "name": name or slug,
        "kind": "pedalboard",
        "schema": 2,
        "identity": {"brand": "?", "model": name or slug, "connection": "din",
                     "note": "Learned by listening on this rack — the device did not identify "
                             "itself; what it SENDS was measured."},
        "channel": int(channel),
        "quirks": {"note_edges": "clean" if edges else "paired", "note_base": 0,
                   "thru_echo": False, "display_base": 0},
        "capabilities": {"identifies": False, "gestures": bool(edges),
                         "goto_bank": {"supported": False}, "load": "none"},
        "bindings": bindings,
        "verify": {"checks": [{"label": "Every learned switch answers",
                               "expect": "each switch you assigned drives the rack"}]},
        "provenance": {"source": "measured", "confidence": "verified",
                       "note": notes or "learned by listening (Calibration ▸ Pedalboard)"},
    }
    from . import store
    path = os.path.join(DEVICES_DIR, slug + ".json")
    # atomique : ce fichier est une calibration APPRISE — une coupure pendant l'écriture
    # perdait une soirée de mode écoute (audit 2026-08-12)
    store._write_json_atomic(path, doc, indent=1, newline=True)
    _CACHE.pop(path, None)
    select(slug)
    log.info("appris : %s (%d liaisons, canal %d)" % (slug, len(bindings), channel))
    return slug


# Garde de ré-entrance de detect_async : un Lock, pas un booléen — release() est légal depuis
# un autre thread, et c'est le thread de sonde qui rend la main.
_PROBING = threading.Lock()


def detect_async():
    """Sonde en tâche de fond — au démarrage du bridge (on ne bloque pas sur un pédalier
    éteint : 2 s de garde × le nombre de candidats) ET à l'insertion d'un pédalier USB
    (monitors._poll_hotplug, audit 2026-08-12 §3 ⑤ — avant, la sonde ne tournait qu'au boot).
    NON RÉENTRANTE : une sonde déjà en cours n'en empile pas une deuxième, le hotplug peut
    appeler sans compter."""
    if not _PROBING.acquire(blocking=False):
        return

    def _run():
        try:
            probe()
        finally:
            _PROBING.release()

    try:
        threading.Thread(target=_run, daemon=True, name="pedalboard-probe").start()
    except Exception:
        _PROBING.release()
        raise


# ── ce que le rack en tire ───────────────────────────────────────────────────────────────

def wire_contract():
    """Ce dont `foot.py` a besoin, et rien d'autre : le canal sur le fil et les travers.

    ⚠ Le canal du CONTRAT est 1-16, le canal SUR LE FIL est 0-15 (aseqdump numérote depuis 0).
    Confondre les deux rend le rack sourd sans erreur — c'est exactement ce qui est arrivé.
    """
    act = active()
    dev = act["device"]
    quirks = dev.get("quirks", {})
    return {"device_id": act["id"], "wire_channel": int(dev.get("channel", 2)) - 1,
            "note_edges": quirks.get("note_edges", "clean"),
            "note_base": int(quirks.get("note_base", 0)),
            "display_base": int(quirks.get("display_base", 0)),
            # Par où le pédalier ARRIVE : din-soundcard (défaut) = le DIN de la carte son
            # active, le comportement historique ; usb = son propre port ALSA (port_match).
            # Sans ce champ, le lecteur était soudé au DIN et un pédalier USB n'était JAMAIS
            # entendu (audit 2026-08-12 §3).
            "transport": dev.get("transport") or {"kind": "din-soundcard"},
            # L'INTENTION voyage avec le contrat de fil : foot.py compile ses tables depuis
            # contract.json par le MÊME chemin que le canal et les travers — une application
            # (set_device), un ordre au boot (déclaré d'abord, la sonde corrige ensuite).
            "intent": contract(),
            # Les appareils APPRIS portent leur table ; les deux FCB n'en ont pas et gardent le
            # chemin codé. Un pédalier qu'on programme et un pédalier qu'on subit ne se lisent
            # pas de la même façon — et c'est le second, le cas général.
            "bindings": dev.get("bindings") or [],
            # Quels switches relâchent VRAIMENT — pour que foot.py sache lesquels sont des
            # « taps » et n'y laisse jamais courir une minuterie d'appui long (cf. edge_switches).
            "edge_switches": sorted(edge_switches())}


def edge_switches():
    """Les switches qui délivrent VRAIMENT les deux fronts, appui ET relâchement.

    ⚠ Ce n'est PAS la capacité de l'appareil (« cette puce sait faire des gestes ») mais un fait
    PAR SWITCH, et il est structurel : sur la UnO2 un stomp `effect` tient sa LED d'état au prix
    du relâchement — sa face « off » est un second appui. Seuls les stomps que l'intention
    déclare `gestures` sont compilés en `trigger`, et eux seuls relâchent.
    La rangée des scènes relâche toujours : elle est compilée en `preset`, dont la face « off »
    est un vrai NoteOff (tools/fcb/gen_uno2_syx.py).

    Mesuré au pied le 2026-08-07 : SW6 et SW7 -> 0 relâchement · SW10 -> les deux fronts.
    """
    con = contract()
    caps = (active()["device"] or {}).get("capabilities", {})
    out = {int(sc["switch"]) for sc in con.get("scenes", []) if sc.get("switch")}
    if caps.get("gestures"):
        out |= {int(st["switch"]) for st in con.get("stomps", []) if st.get("gestures")}
    return out


def summary():
    """Vue complète pour l'écran — l'appareil, l'intention, et ce qui n'est PAS satisfait."""
    act = active()
    con = contract()
    dev = act["device"]
    caps = dev.get("capabilities", {})
    unmet = []
    if not caps.get("gestures"):
        unmet = [s["switch"] for s in con.get("stomps", []) if s.get("gestures")]
    return {
        "active": {k: act[k] for k in ("id", "name", "source", "firmware", "serial", "probed_at")},
        "device": dev,
        "contract": con,
        "wire": wire_contract(),
        "unmet_gestures": unmet,
        "devices": [{"id": d["id"], "name": d.get("name", d["id"]),
                     "firmware": d.get("identity", {}).get("firmware"),
                     "identifies": bool(d.get("capabilities", {}).get("identifies"))}
                    for d in sorted(devices().values(), key=lambda x: x.get("name", ""))],
    }
