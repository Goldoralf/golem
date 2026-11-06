# SPDX-License-Identifier: GPL-3.0-or-later
"""Le mixer de sorties — doser ce qui sort du rack (contrat docs/mixer.md).

Le rack produit plusieurs sources sonores (les lanes d'instruments, le backing, les samples,
la batterie, le looper, le clic) et, jusqu'ici, aucun moyen de les doser entre elles. Ce module
porte le modèle : SOURCES × DESTINATIONS, même quand il n'y a qu'une destination — parce que le
mix d'enregistrement en est une deuxième, virtuelle, et qu'un modèle qui commence en liste plate
devra être refait le jour d'une carte à plusieurs sorties.

── OÙ VIT LE NIVEAU, ET POURQUOI LÀ ─────────────────────────────────────────────────────────
Côté Reaper, chaque piste-source a UN send matériel (catégorie 1) vers la carte. Ce send porte
son propre volume (D_VOL) — inutilisé jusqu'ici. C'est là que vit le trim du mixer :

    D_VOL de PISTE  = niveau de scène   -> autorité du PRESET (scene.level, golem_rig)
    D_VOL du SEND   = trim du mixer     -> autorité du RIG    (ce fichier)

Deux étages, deux propriétaires, aucune dispute — et le bloc Volume (pédale EXP) reste une
commande de jeu en amont, intouchée.

── CE QUE CES NIVEAUX NE SONT PAS ───────────────────────────────────────────────────────────
Des paramètres de preset. Ton mix de retour ne change pas parce que quelqu'un a lancé le
morceau suivant : les niveaux vivent dans config/mixer.json (état du rig, hors dépôt), et un
recall ne les touche pas — golem_rig relit ce fichier à chaque matérialisation pour reposer
les trims sur les sends qu'il vient de recréer.

── LE TRIM ATTÉNUE ──────────────────────────────────────────────────────────────────────────
0 dB = unité, jamais de gain. Tout se somme dans une seule paire sur une petite carte, et
c'est là que ça clippe — un fader qui peut ajouter 6 dB juste avant le convertisseur, c'est le
bug de volume de juillet qui revient. -60 dB vaut -inf (send à zéro).
"""
import json
import os

from . import config as C
from . import commands
from .golog import get

log = get("mixer")
from .state import state

MIXER_FILE = os.path.join(C.CONFIG_DIR, "mixer.json")

DB_MIN, DB_MAX = -60.0, 0.0            # -60 = silence (le send passe à 0), 0 = unité

# Blocs de service qui produisent du son -> id de source mixer. Le clic est permanent ; les
# autres existent selon le preset (lane Players).
SERVICE_SOURCES = {"backing-track": "backing", "sample": "sample",
                   "drums": "drums", "looper": "looper"}
# Le STANDARD : UNE TRANCHE PAR PARTIE (2026-10-20). Il a ses propres pistes (golem_chordseq.lua : « Standard Keys »,
# « … Bass », « … Drums », « … Guitar ») — l'ancienne idée « il joue à travers les lanes d'instruments » datait d'avant
# elles, et le laissait sans fader sur /live. Les parties par défaut sont celles du moteur (standards.py, `parts`).
STANDARD_PARTS = (("keys", "std-keys", "Piano", True), ("bass", "std-bass", "Bass", True),
                  ("drums", "std-drums", "Drums", False), ("guitar", "std-guitar", "Guitar", False))
SERVICE_LABELS = {"backing": "Backing", "sample": "Sample", "drums": "Drums",
                  "looper": "Looper", "click": "Click"}

_cache = {"mtime": None, "data": None}


def _load():
    try:
        mt = os.path.getmtime(MIXER_FILE)
        if _cache["mtime"] != mt:
            with open(MIXER_FILE, encoding="utf8") as fh:
                _cache["data"] = json.load(fh)
            _cache["mtime"] = mt
    except OSError:
        _cache["data"] = {}
    except Exception as e:
        log.warning("mixer.json illisible : %s" % (e,))
        _cache["data"] = {}
    return _cache["data"] or {}


def levels():
    """Les niveaux persistés : {source_id: {db, mute}}. Absent = 0 dB, non muté."""
    return dict(_load().get("levels") or {})


def _save(lv):
    try:
        from . import store
        store._write_json_atomic(MIXER_FILE, {"levels": lv}, indent=1, newline=True)
        _cache["mtime"] = None
    except Exception as e:
        log.warning("mixer.json non écrit : %s" % (e,))


def set_level(source, db=None, mute=None):
    """Pose le trim d'une source, persiste, et pousse à chaud vers Reaper.

    La commande porte TOUS les niveaux (idempotente) : golem_rig applique ce qui existe et
    ignore silencieusement les pistes absentes — une valeur posée avant que la piste n'existe
    s'applique au prochain recall (la matérialisation relit le fichier).
    """
    return set_levels({source: {"db": db, "mute": mute}})[source]


def set_levels(changes):
    """Pose PLUSIEURS trims d'un coup — une persistance, une commande.

    C'est le chemin des faders LIÉS (groupe temporaire, façon VCA) : un drag de groupe à
    7 tranches émettrait sinon 7 requêtes par tick de throttle, chacune poussant déjà tous
    les niveaux — 7 écritures du fichier de commande pour un seul geste.
    """
    lv = levels()
    out = {}
    for source, ch in changes.items():
        cur = dict(lv.get(source) or {})
        if ch.get("db") is not None:
            cur["db"] = round(max(DB_MIN, min(DB_MAX, float(ch["db"]))), 1)
        if ch.get("mute") is not None:
            cur["mute"] = bool(ch["mute"])
        lv[source] = cur
        out[source] = cur
    _save(lv)
    push()
    return out


def push():
    """Émet l'application à chaud (action mixer_apply, routée vers golem_rig — sans rebuild)."""
    commands.write_command({"action": "mixer_apply", "levels": levels()})


def _service_blocks_of(preset):
    """Les sources de service présentes dans CE preset (lane Players, preset.config.gen)."""
    out = set()
    gen = ((preset or {}).get("config") or {}).get("gen") or {}
    for b in gen.get("blocks") or []:
        sid = SERVICE_SOURCES.get(b.get("type"))
        if sid:
            out.add(sid)
    return out


def _lane_name(preset, key):
    """Le nom d'une lane (« Voice 1 ») à partir de sa clé de looper (« voice-1 », « 1 », « k »)."""
    for L in (preset or {}).get("lanes") or []:
        if key in (L.get("id"), L.get("key")):
            return L.get("name") or L.get("id")
    return {"k": "Keys"}.get(str(key), str(key or "loop"))


def summary():
    """Ce que l'écran affiche : les sources (déduites, jamais une liste en dur), les niveaux,
    les destinations.

    Les sources de lane viennent du PATCH de la carte (rôles d'entrée) ; les services, du
    preset courant — mais on les liste TOUS : les niveaux sont du rig, ils survivent au
    changement de morceau, donc les tranches ne doivent pas apparaître/disparaître. Une
    source absente du preset est simplement éteinte à l'écran.
    """
    from . import inputmap, store
    imap = inputmap.current()
    lv = levels()

    sources = []
    for i in imap.get("inputs") or []:
        role = i.get("role")
        if not role or role == "none":
            continue
        sid = "in%s" % i.get("ch")
        sub = "IN %s" % i.get("ch") + (" · %s" % i["person"] if i.get("person") else "")
        # `name` = « Guitar 2 » (rôle + numéro) : deux guitares ne doivent pas porter la même tranche
        sources.append({"id": sid, "label": i.get("name") or i.get("label") or role.capitalize(),
                        "sub": sub, "kind": "lane", "role": role, "present": True})
    if imap.get("midi"):                            # un contrôleur clavier patché = la lane Keys (In3, ou 101 sur une carte à ≥3 entrées — lot 5)
        sources.append({"id": "in%d" % store.midi_input_base(len(imap.get("inputs") or [])), "label": "Keys", "sub": "MIDI",
                        "kind": "lane", "role": "keys", "present": True})

    preset = store.load_preset(state.preset_id) if state.preset_id else None
    present = _service_blocks_of(preset)
    for sid in ("backing", "sample", "drums", "looper"):
        sources.append({"id": sid, "label": SERVICE_LABELS[sid], "sub": "block",
                        "kind": "block", "present": sid in present})
        if sid == "looper" and sid in present:
            # UNE TRANCHE PAR BOUCLE (2026-10-14) : son volume à la LECTURE, dans le JSFX — pas un send. Le niveau
            # vit dans la table du preset (le geste passe par /api/looper op « level »), pas dans config/mixer.json.
            from . import rig
            for i, r in enumerate(rig.looper_loops(preset)):
                lid = "loop:%d" % i
                sources.append({"id": lid, "label": r.get("label") or _lane_name(preset, r.get("src")),
                                "sub": "SW %d" % r["sw"], "kind": "loop", "slot": i, "present": True})
                lv = {**lv, lid: {"db": r.get("level", 0.0), "mute": bool(r.get("mute"))}}
    std = next((b for b in (((preset or {}).get("config") or {}).get("gen") or {}).get("blocks") or []
                if b.get("type") == "standard"), None)
    if std:
        pa = std.get("params") or {}
        for part, sid, label, dflt in STANDARD_PARTS:
            if pa.get(part, dflt):                  # une partie que le standard ne joue pas n'a pas de tranche
                sources.append({"id": sid, "label": label, "sub": "standard", "kind": "block", "present": True})
    sources.append({"id": "click", "label": "Click", "sub": "service",
                    "kind": "service", "present": True})

    # Destinations : celles que le PATCH déclare (une seule sur la Volt), plus le mix
    # d'enregistrement — virtuelle, mais réelle pour l'utilisateur : c'est ce que la prise
    # contiendra. En v1 le rec SUIT le mix principal (même trim recopié sur le send vers la
    # piste Recording) ; le découplage attendra qu'un besoin le prouve.
    dests = [{"id": "out%s" % (o.get("ch") or ""), "ch": o.get("ch"),
              "label": "OUT %s" % (o.get("ch") or "?"),
              "role": o.get("label") or o.get("role") or ""}
             for o in imap.get("outputs") or []]
    dests.append({"id": "rec", "label": "Rec mix", "role": "follows the main mix",
                  "virtual": True})

    return {"sources": sources, "levels": lv, "destinations": dests,
            "db_min": DB_MIN, "db_max": DB_MAX}
