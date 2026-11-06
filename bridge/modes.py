# SPDX-License-Identifier: GPL-3.0-or-later
"""Modes machine (docs/modes.md) — v1.

Un mode = profil déclaratif livré dans config/modes/*.json : VETO de services
(effectif = preset ∧ mode), surface UI (pages visibles, verrouillage Gig),
page de boot. Le mode appartient à la MACHINE (pas au preset) : persisté dans
config/.mode.json (gitignoré), restauré au démarrage du bridge — le rack
redémarre en répète, il revient en Rehearsal.

v1 n'applique PAS : le swap de carte (Rehearsal, chantier dédié) ni le buffer
par mode (le buffer reste dans Settings ; le lier au mode viendra avec la
validation « buffer par combinaison de flags » du contrat §4).
"""
import json
import os
import re

from . import config as C
from .golog import swallowed as _swallowed

MODES_DIR = os.path.join(C.CONFIG_DIR, "modes")            # défauts d'usine (versionnés)
LOCAL_DIR = os.path.join(C.CONFIG_DIR, "modes.local")      # édits utilisateur (gitignoré) — même id = surcharge
STATE_FILE = os.path.join(C.CONFIG_DIR, ".mode.json")
DEFAULT_ID = "studio"

# services connus (chips de l'UI) — un service absent d'un mode = autorisé.
# Entrées audio (guitar/bass/voice/drums/line) + contrôleur (keys/pads) = vocabulaire du patch
# Soundcard (couture Mode ⇄ Soundcard, patch.INSTRUMENTS) ; outils logiciels
# (looper/backing/sample/perfrec) séparés — même contrat que la lane Players du Designer.
# `arrangement` (2026-07-30) : l'automation ne doit PAS partir toute seule dans une situation
# où on ne l'a pas demandée. L'ÉDITION reste possible partout — on construit chez soi, on joue
# sur scène (docs/arrangement.md §7 bis).
# Défauts : Show (c'est SON mode), Rehearsal (là où on la teste) et Home (là où on la fabrique
# et où on veut l'entendre). ÉTEINT en Pedalboard — « le mode où rien ne peut mal tourner » — et
# en Gig, qu'on ouvre délibérément le jour où le set est automatisé.
# ⚠ Le corriger a demandé de constater une évidence : Show MASQUE le Designer (ui.pages=['live']).
# Avec « Show seulement », le bouton disait « Off in … » partout où l'on peut éditer, et l'état
# « Armed » était littéralement inatteignable.
# `standard` (le lecteur de grilles) et `drummachine` (la boîte à rythmes) — 2026-09-08, le mainteneur :
# ils n'avaient PAS de clé, donc « inconnu = autorisé » et ils tournaient partout, Pedalboard
# compris. ⚠ `drums` reste l'ENTRÉE batterie (micros), la boîte à rythmes est `drummachine`.
SERVICES = ("guitar", "bass", "voice", "drums", "line", "keys", "pads",
            "looper", "backing", "sample", "perfrec", "arrangement", "standard", "drummachine",
            "compo")   # docs/compo.md §7 : on en Rehearsal/Studio/Accompaniment, off en Gig/Show/Pedalboard

# Plafond de modes (décision 2026-07-28) : la page Modes montre 8 emplacements, les
# libres en pointillé. Le plafond est vérifié ICI et pas seulement dans l'UI — un mode se
# crée aussi par un POST direct.
MAX_MODES = 8


def _read_dir(d):
    out = {}
    try:
        for fn in os.listdir(d):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn)) as f:
                    m = json.load(f)
                if m.get("id"):
                    out[m["id"]] = m
            except Exception:
                continue
    except FileNotFoundError:
        pass
    return out


def list_modes():
    """Usine + surcouche locale fusionnées, triées par 'order'. Chaque mode porte
    ses drapeaux d'origine : _factory (livré), _modified (livré ET surchargé),
    _custom (n'existe qu'en local — duplicata utilisateur)."""
    factory, local = _read_dir(MODES_DIR), _read_dir(LOCAL_DIR)
    out = []
    for mid, m in {**factory, **local}.items():
        m = dict(m)
        m["_factory"] = mid in factory
        m["_modified"] = mid in factory and mid in local
        m["_custom"] = mid not in factory
        out.append(m)
    out.sort(key=lambda m: m.get("order", 99))
    return out


def factory_def(mode_id):
    return _read_dir(MODES_DIR).get(mode_id)


def save_local(mode):
    """Écrit un mode dans la surcouche locale (édition ou duplicata)."""
    from . import store
    clean = {k: v for k, v in mode.items() if not k.startswith("_")}
    store._write_json_atomic(os.path.join(LOCAL_DIR, f"{clean['id']}.json"), clean)
    return clean


# ── ÉDITION d'un mode : UN chemin pour la feuille du rack ET le job `mode-set` de golem.fm
# (docs/modes.md, addendum 2026-09-26). Les champs éditables, leurs filtres et la détection « revenu à
# l'usine » vivaient dans la route /api/mode/update ; un second appelant les aurait recopiés — et
# c'est là que la rangée « Live screen » s'était perdue (la feuille envoyait `live_view`, la route
# l'ignorait, rien ne persistait : trouvé le 2026-09-26 en lisant pour golem.fm).
EDITABLE = ("name", "icon", "desc", "services", "click_mode", "inputs_off", "card", "band", "live_view",
            # la LISTE AU PIED par défaut du mode (docs/patches.md §7, tranché 2026-09-30) : l'id
            # d'une setlist de morceaux ou d'une bank de sons ; null / "" = le mode ne touche pas au pied
            "foot_list",
            # les widgets des pages de /live (docs/live-pages.md §5) : {page: {slot: widget | null}}
            "widgets")
# ce qui ne s'édite JAMAIS à distance ni par ce chemin : le verrou et la forme du kiosk (`ui.locked`,
# `ui.pages`, `ui.boot` — un verrou posé du web enferme l'écran), `perf_boost`, `perfrec_mode`, `take_kind`
NEVER_REMOTE = ("ui", "locked", "pages", "boot", "perf_boost", "perfrec_mode", "take_kind", "order", "id")


def validate_update(body, known_cards=None, known_bands=None):
    """Les REFUS d'une édition stricte (le job distant) : [(champ, pourquoi)]. La feuille du rack reste
    tolérante (elle n'envoie que des valeurs de ses propres chips) ; un appelant distant est validé champ
    par champ, et un seul refus = rien d'écrit (tout-ou-rien, à la charge de l'appelant)."""
    out = []
    for k in body:
        if k in ("id", "mode", "space"):
            continue
        if k in NEVER_REMOTE:
            out.append((k, "never set remotely"))
        elif k not in EDITABLE:
            out.append((k, "unknown field"))
    sv = body.get("services")
    if sv is not None:
        if not isinstance(sv, dict):
            out.append(("services", "must be an object {service: bool}"))
        else:
            for k in sv:
                if k not in SERVICES:
                    out.append(("services", f"unknown service {k}"))
    if "click_mode" in body and body["click_mode"] not in CLICK_MODES:
        out.append(("click_mode", f"one of {', '.join(CLICK_MODES)}"))
    if "live_view" in body and body["live_view"] not in LIVE_VIEWS:
        out.append(("live_view", f"one of {', '.join(LIVE_VIEWS)}"))
    if "widgets" in body:
        wg = body["widgets"]
        if not isinstance(wg, dict):
            out.append(("widgets", "an object {page: {slot: widget | null}}"))
        else:
            for page, slots in wg.items():
                if page not in WIDGET_SLOTS or not isinstance(slots, dict):
                    out.append(("widgets", f"unknown page {page}"))
                    continue
                for slot, w in slots.items():
                    size = WIDGET_SLOTS[page].get(slot)
                    if not size:
                        out.append(("widgets", f"unknown slot {page}.{slot}"))
                    elif w is not None and size not in WIDGET_SIZES.get(w, ()):
                        out.append(("widgets", f"{w} does not fit the {size} slot {page}.{slot}"))
    if "inputs_off" in body:
        io = body["inputs_off"]
        if not isinstance(io, list) or any(not (isinstance(k, str) and "#" in k) for k in io):
            out.append(("inputs_off", 'a list of "role#n" keys'))
    if "card" in body and body.get("card") and known_cards is not None:
        c = str(body["card"]).strip()
        if (c[3:] if c.startswith("hw:") else c) not in known_cards:
            out.append(("card", f"unknown card {c} — declare it on the rack first"))
    if "band" in body and body.get("band") and known_bands is not None:
        if str(body["band"]).strip() not in known_bands:
            out.append(("band", "unknown space — the rack never creates one"))
    for k in ("name", "icon", "desc"):
        if k in body and not (isinstance(body[k], str) and body[k].strip()):
            out.append((k, "a non-empty string"))
    if "foot_list" in body and body["foot_list"] not in (None, ""):
        fl = body["foot_list"]
        if not isinstance(fl, str) or len(fl) > 120:
            out.append(("foot_list", "a setlist id (≤ 120 characters) or null"))
        elif fl != INSTRUMENT:
            from . import setlists as _sl
            if _sl.load(fl) is None:
                out.append(("foot_list", f"unknown setlist {fl} on this rack"))
    return out


def apply_update(m, body):
    """Applique les champs éditables de `body` sur le mode `m` (en place) — la sémantique de la feuille :
    services filtrés sur la liste connue en booléens ; name/icon/desc non vides, 80 car. ; click_mode et
    live_view dans leur vocabulaire ; inputs_off = clés « role#n » ; card et band : "" (ou null) = on
    RETIRE le champ (« n'importe quelle carte » / « garde l'espace courant »), jamais une chaîne vide
    stockée, pour que factory_def() se compare juste. Rend `m`."""
    if isinstance(body.get("services"), dict):
        m["services"] = {k: bool(v) for k, v in body["services"].items() if k in SERVICES}
    for k in ("name", "icon", "desc"):
        if isinstance(body.get(k), str) and body[k].strip():
            m[k] = body[k].strip()[:80]
    if body.get("click_mode") in CLICK_MODES:
        m["click_mode"] = body["click_mode"]
    if body.get("live_view") in LIVE_VIEWS:                        # la vue de /live (ui.live) — enfin écrite
        ui = dict(m.get("ui") or {})
        ui["live"] = body["live_view"]
        m["ui"] = ui
    if isinstance(body.get("widgets"), dict):                      # les widgets des pages (docs/live-pages.md §5)
        ui = dict(m.get("ui") or {})
        cur = {p: dict(v) for p, v in (ui.get("widgets") or {}).items() if isinstance(v, dict)}
        for page, slots in body["widgets"].items():
            if page in WIDGET_SLOTS and isinstance(slots, dict):
                for slot, w in slots.items():
                    size = WIDGET_SLOTS[page].get(slot)
                    if size and (w is None or size in WIDGET_SIZES.get(w, ())):
                        cur.setdefault(page, {})[slot] = w
        ui["widgets"] = cur
        m["ui"] = ui
    if isinstance(body.get("inputs_off"), list):
        off = [str(k)[:40] for k in body["inputs_off"] if isinstance(k, str) and "#" in k][:64]
        if off:
            m["inputs_off"] = sorted(set(off))
        else:
            m.pop("inputs_off", None)
    for k in ("card", "band", "foot_list"):
        if k in body:
            v = (body.get(k) or "").strip()[:64] if isinstance(body.get(k), str) or body.get(k) is None else ""
            if v:
                m[k] = v
            else:
                m.pop(k, None)
    return m


def commit(m):
    """Écrit le mode édité : revenu à l'IDENTIQUE de sa définition livrée → la surcouche locale saute
    (sinon le badge EDITED reste collé après un aller-retour de chip) ; sinon save_local. Rend le mode propre."""
    clean = {k: v for k, v in m.items() if not k.startswith("_")}
    if clean == factory_def(clean.get("id")):
        delete_local(clean["id"])
        return clean
    return save_local(m)


def doc(m):
    """Un mode tel que golem.fm l'affiche (feuille Settings ▸ Mode entière) — lecture seule, liste blanche."""
    ui = m.get("ui") or {}
    return {"id": m.get("id"), "label": m.get("name"), "name": m.get("name"), "icon": m.get("icon"),
            "order": m.get("order"), "desc": m.get("desc"),
            "factory": bool(m.get("_factory")), "modified": bool(m.get("_modified")), "custom": bool(m.get("_custom")),
            "band": m.get("band") or None, "card": card_of(m),
            "services": {k: bool((m.get("services") or {}).get(k, True)) for k in SERVICES},
            "inputs_off": list(m.get("inputs_off") or []),
            "live_view": live_view(m), "click_mode": click_mode(m),
            "perfrec": m.get("perfrec_mode") or None, "perfrec_mode": m.get("perfrec_mode") or None,
            "take_kind": take_kind(m), "locked": bool(ui.get("locked")), "perf_boost": bool(m.get("perf_boost")),
            "foot_list": m.get("foot_list") or None, "widgets": widgets(m)}


def vocab():
    """Les vocabulaires que le widget ne doit pas coder en dur."""
    return {"services": list(SERVICES), "click_modes": list(CLICK_MODES), "live_views": dict(LIVE_VIEWS),
            "widget_slots": WIDGET_SLOTS, "widget_sizes": {k: list(v) for k, v in WIDGET_SIZES.items()},
            "editable": list(EDITABLE)}


def delete_local(mode_id):
    """Retire la surcouche locale d'un id : reset usine (si livré) ou suppression
    d'un duplicata. True si un fichier a été enlevé."""
    p = os.path.join(LOCAL_DIR, f"{mode_id}.json")
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


# ── ui.live : QUELLE VUE la page Live rend (décision 2026-07-30) ────────────────────────
# `ui.pages` dit quelles pages sont VISIBLES ; il manquait de quoi dire à quoi ressemble Live.
# Un mode Show qui affiche le miroir du pédalier n'est pas un mode Show : c'est ce qui rendait
# l'emplacement d'usine inutile. On reste sur « mode = données » — la page lit un nom de vue,
# exactement comme la nav lit `pages`. Aucun `if mode ==` nulle part.
LIVE_VIEWS = {
    "pedalboard": "Pedalboard — the FCB mirror: stomps, scenes, banks",
    # docs/live-pages.md (2026-10-15) : la Timeline devient DEUX pages. L'id `timeline` reste celui du CONCERT —
    # c'est le mot déjà écrit dans les modes des racks et dans ce que golem.fm édite ; seul le libellé change.
    "rehearsal": "Rehearsal — pick a section, start from it, loop it",
    "timeline": "Concert — the music stand: readable from 2 m, the foot plays",
}

# ── LES WIDGETS DES PAGES DE /live (docs/live-pages.md §5) : des EMPLACEMENTS FIXES par page, une taille par
# emplacement ; un widget ne va que là où il tient. Quatre au plus par page — la page ne défile jamais.
WIDGET_SLOTS = {"rehearsal": {"right": "M", "bottom": "L"},
                "timeline": {"top1": "S", "top2": "S", "bottom": "L"}}
# relecture UX (2026-10-15) : `next` et `loops` répétaient la zone NOW et le ⟲ de la carte — retirés ; `song_time`
# est déjà dans la bande du Concert, il ne tient donc qu'en M (la Répète)
WIDGET_SIZES = {"lyrics": ("L",), "song_time": ("M",), "set_clock": ("S",),
                "chords": ("M", "L"), "notes": ("S", "M"), "instruments": ("S", "M")}
WIDGET_DEFAULTS = {"rehearsal": {"right": "chords", "bottom": "lyrics"},
                   "timeline": {"top1": "notes", "top2": "set_clock", "bottom": "lyrics"}}


def widgets(mode=None):
    """Les widgets de chaque page pour ce mode : le défaut d'usine, surchargé emplacement par emplacement par
    `ui.widgets` (une valeur null = l'emplacement est VIDE, choisi). Un widget qui ne tient pas (surcouche écrite à la
    main) retombe sur le défaut — jamais un emplacement qui casse la page."""
    mine = ((mode or current()).get("ui") or {}).get("widgets") or {}
    out = {}
    for page, slots in WIDGET_SLOTS.items():
        got = mine.get(page) if isinstance(mine.get(page), dict) else {}
        out[page] = {}
        for slot, size in slots.items():
            w = got.get(slot, WIDGET_DEFAULTS[page].get(slot)) if slot in got else WIDGET_DEFAULTS[page].get(slot)
            out[page][slot] = w if (w is None or size in WIDGET_SIZES.get(w, ())) else WIDGET_DEFAULTS[page].get(slot)
    return out
DEFAULT_LIVE_VIEW = "pedalboard"


def live_view(mode=None):
    """Vue de la page Live pour ce mode. Un mode qui ne déclare rien (ou déclare une vue
    inconnue — surcouche locale écrite à la main, mode importé d'un autre rack) retombe sur
    le pédalier : jamais d'écran vide parce qu'une chaîne ne matchait pas."""
    v = ((mode or current()).get("ui") or {}).get("live")
    return v if v in LIVE_VIEWS else DEFAULT_LIVE_VIEW


def card_of(mode):
    """Carte DÉCLARÉE par un mode (« hw:V276 »), ou None = « n'importe quelle carte ».
    Un mode sans carte n'est jamais invalidé par un changement d'interface."""
    c = (mode or {}).get("card")
    return c.strip() if isinstance(c, str) and c.strip() else None


TAKE_KINDS = ("rehearsal", "gig", "show")


def take_kind(mode=None):
    """Ce qu'une prise faite dans ce mode DIT d'elle-même à golem.fm : « gig » (LE CONCERT) ou
    « rehearsal » (tout le reste : Pedalboard, Home, Rehearsal, Jam — id `accompaniment`).
    ⚠ CETTE PHRASE DISAIT LE CONTRAIRE jusqu'au 2026-09-18 — « show (concert), gig (répète de groupe
    en conditions) » — alors que la carte du mode Gig annonce « On stage » : le rack se contredisait
    sur ces deux mots. En anglais `gig` et `show` désignent LE MÊME concert (vu du groupe ou vu de la
    salle) ; une répète se dit `rehearsal`. golem.fm a corrigé la même erreur chez lui le même jour.
    Depuis la fusion Show → Gig (docs/modes.md §7 bis), le rack n'ÉMET plus « show » — il l'accepte
    encore à la LECTURE (des prises en portent sur des disques, on ne réécrit jamais l'histoire), et
    une carte locale qui le déclare continue de marcher : la donnée décide.
    Décision 2026-09-08 : golem.fm ne traite pas pareil un concert,
    une répète et un riff sur le pouce — et c'est le rack qui le sait, au moment du REC.
    La donnée décide (`take_kind` du mode) ; le repli sur l'id ne sert qu'à un mode local
    d'avant ce champ."""
    m = mode if mode is not None else current()
    if isinstance(m, dict):
        k = m.get("take_kind")
        if k in TAKE_KINDS:
            return k
        m = m.get("id")
    return take_kind_of_id(m)


def take_kind_of_id(mode_id):
    return {"gig": "gig", "show": "show"}.get(mode_id or "", "rehearsal")


# ── rec_scope : JUSQU'OÙ va une prise lancée par un morceau (docs/modes.md §7 bis, 2026-09-18) ──
# « song » (défaut) : la prise suit le morceau — c'est la case « Record with the song » du conductor.
# « set » : la prise part avec la PREMIÈRE chanson de la setlist si rien ne tourne, et couvre toute la
# soirée (elle ne s'arrête pas en fin de morceau) ; un REC arrêté exprès ne repart pas tout seul.
# Ce champ REMPLACE le seul `if mode == "show"` du rack (bridge/app._on_song) : le contrat §2 interdit
# ce motif, et c'était le dernier endroit qui le violait.
REC_SCOPES = ("song", "set")


def rec_scope(mode=None):
    """« song » | « set ». Un mode muet (ou une valeur inconnue, cas d'un mode importé d'un autre
    rack) vaut « song » : le comportement le moins surprenant — une prise qui s'arrête avec ce
    qu'on vient de jouer."""
    m = mode if mode is not None else current()
    v = (m or {}).get("rec_scope") if isinstance(m, dict) else None
    return v if v in REC_SCOPES else "song"


# ── Show FUSIONNE dans Gig (2026-09-18) — migration au démarrage ─────────────────────────
def migrate_show_to_gig():
    """Retire ce qui reste du mode `show` et remet le rack sur `gig` s'il y était.

    ⚠ CORRECTION DU CONTRAT, mesurée sur le rack de le 2026-09-18 : §7 bis.4 disait « une
    surcharge locale de show est laissée telle quelle ». C'était FAUX en pratique — `config/modes.local/`
    contient un fichier pour CHAQUE mode d'usine, parce que `band` et `card` ne vivent QUE là (§4).
    Laisser le fichier local aurait donc gardé Show vivant sur le seul rack qui demandait la fusion :
    `list_modes()` fusionne usine ∪ local, et un local sans usine passe même pour un mode « custom ».
    Le fichier local de `show` est donc ARCHIVÉ (`show.json.merged`, hors du glob `*.json`) et son
    contenu journalisé — rien n'est perdu, rien ne ressuscite. Un mode que l'utilisateur a CRÉÉ depuis
    Show porte un autre id : il n'est pas concerné.

    Rend {archived: bool, band: str|None, card: str|None, switched: bool} ou None si rien à faire.
    Idempotent."""
    out = {"archived": False, "band": None, "card": None, "switched": False}
    local = os.path.join(LOCAL_DIR, "show.json")
    if os.path.isfile(local) and "show" not in _read_dir(MODES_DIR):
        try:
            with open(local) as f:
                d = json.load(f)
            out["band"], out["card"] = d.get("band"), d.get("card")
        except Exception as _e:
            _swallowed(_e)
        try:
            os.replace(local, local + ".merged")          # `.merged` : jamais relu (_read_dir filtre *.json)
            out["archived"] = True
        except OSError as _e:
            _swallowed(_e)
    try:
        with open(STATE_FILE) as f:
            cur = json.load(f).get("id")
    except Exception as _e:
        _swallowed(_e)
        cur = None
    if cur == "show" and _by_id("show") is None and _by_id("gig") is not None:
        from . import store
        store._write_json_atomic(STATE_FILE, {"id": "gig"}, indent=None)
        out["switched"] = True
    return out if (out["archived"] or out["switched"]) else None


def perf_boost(mode=None):
    """Le mode demande-t-il le BOOST CPU (gouverneur performance) ? Gig et Show : oui — sur scène,
    la latence prime sur la consommation. Les autres : non, on rend la machine à son économie.
    Décision 2026-09-08 ; la donnée décide (`perf_boost`), un mode muet = pas de boost."""
    m = mode if mode is not None else current()
    return bool((m or {}).get("perf_boost")) if isinstance(m, dict) else False


def band_of(mode):
    """ESPACE déclaré par un mode (« b_haw6vqzh5u »), ou None = « garde l'espace courant ».
    Même contrat que `card_of` — et c'est voulu : le mainteneur a validé la symétrie le 2026-09-06
    (`~/code/maestrium/conception/message-golem-modes-espaces.md` §1.1).

    « Home » enregistre pour l'espace perso, « Rehearsal » et « Gig » pour le groupe : le
    musicien ne tague plus rien, il choisit un mode. Les cinq modes d'usine ne déclarent
    RIEN — un rack qui ne synchronise pas ne voit aucune différence.
    """
    b = (mode or {}).get("band")
    return b.strip() if isinstance(b, str) and b.strip() else None


def for_card(device):
    """Le mode à prendre quand la carte ACTIVE devient `device`. None = ne rien faire.

    Règle (docs/modes.md §4) : on ne bascule QUE si le mode courant déclare une AUTRE
    carte — il n'est alors plus jouable (le rig de répète sur la 8×8 n'a pas de sens
    quand on rebranche la Volt). Cible = le premier mode, dans l'ordre d'affichage, qui
    déclare cette carte ; à défaut le premier qui n'en déclare aucune.

    Deux garde-fous : un mode « n'importe quelle carte » ne déclenche jamais rien, et on
    ne sort JAMAIS d'un mode verrouillé — brancher quelque chose ne doit pas pouvoir
    changer le rig au milieu d'un set.
    """
    cur = current()
    want = card_of(cur)
    if not want or want == device:
        return None
    if (cur.get("ui") or {}).get("locked"):
        return None
    ms = list_modes()
    return (next((m for m in ms if card_of(m) == device), None)
            or next((m for m in ms if card_of(m) is None), None))


def new_id(name, taken):
    """Id technique dérivé du NOM saisi (l'utilisateur ne tape jamais d'id).
    Suffixé tant qu'il collisionne — y compris avec un id d'usine."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "mode"
    base = base[:24]
    mid, n = base, 2
    while mid in taken:
        mid, n = f"{base}-{n}", n + 1
    return mid


def _by_id(mode_id):
    return next((m for m in list_modes() if m["id"] == mode_id), None)


def current():
    """Le mode courant (persisté), avec repli sûr sur Studio puis premier livré."""
    mid = DEFAULT_ID
    try:
        with open(STATE_FILE) as f:
            mid = json.load(f).get("id", DEFAULT_ID)
    except Exception as _e:
        _swallowed(_e)
    m = _by_id(mid) or _by_id(DEFAULT_ID)
    if m is None:
        ms = list_modes()
        m = ms[0] if ms else {"id": DEFAULT_ID, "name": "Home", "icon": "🏠",
                              "services": {}, "ui": {"pages": None, "boot": "live", "locked": False}}
    return m


def set_current(mode_id):
    """Bascule et persiste. Lève ValueError si le mode n'existe pas."""
    m = _by_id(mode_id)
    if m is None:
        raise ValueError(f"unknown mode: {mode_id}")
    from . import store
    # atomique : .mode.json corrompu par une coupure = mode au boot inconnu (audit 2026-08-12)
    store._write_json_atomic(STATE_FILE, {"id": mode_id}, indent=None)
    return m


def input_key(role, nth):
    """La clé d'une entrée numérotée : « voice#2 » — celle que `mode.inputs_off` liste."""
    return f"{role}#{int(nth)}" if role and nth else None


def input_allowed(role, nth, mode=None):
    """Veto PAR ENTRÉE (2026-09-09) : « ce mode joue Guitar 2 ? » — la liste `inputs_off` du mode,
    ET le veto par instrument historique (`services[role]`, ex. Pedalboard coupe la voix)."""
    m = mode or current()
    roles = ["keys", "pads"] if role == "keys-pads" else ([role] if role else [])
    if roles and all(not allows(r, m) for r in roles):
        return False
    k = input_key(role, nth)
    return not (k and k in (m.get("inputs_off") or []))


def allows(service, mode=None):
    """Veto de service : True si le mode courant autorise `service`.
    Un service inconnu du mode = autorisé (les nouveaux services restent
    mode-agnostiques tant qu'on ne les déclare pas)."""
    m = mode or current()
    return bool(m.get("services", {}).get(service, True))


# ── politique du CLICK (chantier 2026-07-25) : le métronome est GLOBAL dans sa config
# (config/click.json) mais son DÉCLENCHEMENT dépend de la situation de jeu, donc du mode :
#   off    : ne démarre jamais (Gig — un click qui fuit en façade, jamais ; Pedalboard)
#   preset : suit le bloc Click du preset chargé (actif = joue) — la répète (Rehearsal)
#   manual : interrupteur global, indépendant des presets (Home/Studio) — comportement v1
# Un mode qui ne déclare rien = manual (pas de surprise sur les modes existants/custom).
CLICK_MODES = ("off", "preset", "manual")


def click_mode(mode=None):
    m = mode or current()
    v = m.get("click_mode")
    return v if v in CLICK_MODES else "manual"



# LA BANQUE DE SONS DE L'INSTRUMENT (docs/modes.md §2, 2026-10-24) : le mode Pedalboard (« un instrument ») mettait au
# pied « Factory Golem », des chansons à batterie, claviers et voix dans un mode qui les coupe — un testeur Windows a
# changé de liste à la main, puis ouvert une chanson hors de sa banque : plus de ◀ ▶. `@instrument` se résout à l'entrée
# du mode : la banque d'usine du PREMIER rôle posé sur la carte active (ordre des entrées), sinon celle de la guitare.
INSTRUMENT = "@instrument"
_BANK_OF_ROLE = {"guitar": "factory-guitar", "bass": "factory-bass", "voice": "factory-voice",
                 "keys": "factory-keys", "keys-pads": "factory-keys", "drums": "factory-drums", "pads": "factory-drums"}


def resolve_foot_list(fl):
    """L'id de liste que désigne `fl` : lui-même, ou pour `@instrument` la banque de sons de l'instrument de la carte."""
    if fl != INSTRUMENT:
        return fl
    from . import inputmap, setlists as _sl
    try:
        roles = [i.get("role") for i in (inputmap.current().get("inputs") or [])]
    except Exception:
        roles = []
    first = next((r for r in roles if r and r != "none"), None)
    bank = _BANK_OF_ROLE.get(first)
    return bank if bank and _sl.load(bank) is not None else "factory-guitar"


def apply_foot_list(m):
    """EN ENTRANT DANS UN MODE, sa liste au pied par défaut (docs/patches.md §7) : met la setlist ou
    la bank `foot_list` au pied si elle existe encore. Rend (appliquée: bool, raison|None) — une liste
    disparue ne s'invente pas : le pied garde la sienne et la raison se DIT (puce), pas un silence. Le tap
    « On the foot » reste libre jusqu'au prochain changement de mode : le mode donne un défaut, rien de plus."""
    global _LAST_FOOT
    fl = (m or {}).get("foot_list")
    if not fl:
        _LAST_FOOT = None                            # ce mode ne touche pas au pied : rien à dire
        return False, None
    fl = resolve_foot_list(fl)
    from . import setlists as _sl
    if _sl.load(fl) is None:
        why = f"mode {m.get('name') or m.get('id')}: its foot list « {fl} » is gone — the foot keeps « {_sl.active_id()} »"
        _LAST_FOOT = {"applied": False, "why": why, "list": fl}
        return False, why
    if _sl.active_id() == fl:
        _LAST_FOOT = {"applied": False, "why": None, "list": fl}
        return False, None
    _sl.set_active(fl)
    _LAST_FOOT = {"applied": True, "why": None, "list": fl}
    return True, None


# le DERNIER résultat de `apply_foot_list` — publié au battement (`foot`, demande golem.fm 2026-09-30) : sans
# lui, une liste au pied disparue ne se disait que dans la réponse de la route locale, jamais sur golem.fm
_LAST_FOOT = None


def last_foot():
    return dict(_LAST_FOOT) if _LAST_FOOT else None
