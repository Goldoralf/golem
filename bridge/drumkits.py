# SPDX-License-Identifier: GPL-3.0-or-later
"""Descripteurs de KIT de batterie — `config/drumkits/<id>.json` (docs/drums-kit.md §3, lot 1).

Un module de batterie électronique parle MIDI avec SA table de notes ; le rack ne la connaît que par
un descripteur, EN DONNÉES, jamais une table en dur. Ce module :
  - charge et valide les descripteurs (la même validation que tools/check-descriptors.py, ici pour
    que le bridge refuse un fichier cassé au lieu de jouer n'importe quoi) ;
  - IDENTIFIE le module branché par le nom USB qu'ALSA lui donne (`identity.usb_names`, sous-chaîne,
    sans casse), avec `general-midi` en repli — et le dit (`auto: True`, `fallback: True`) ;
  - traduit une note du module vers un ÉLÉMENT du vocabulaire fermé (ELEMENTS), que les kits du rack
    comprennent (lot 2), et une valeur de CC de charleston vers une de TROIS positions (décision).
La provenance suit le vocabulaire de check-descriptors.py : source manual|imported|measured, confiance
verified|reported|unconfirmed — `reported` = lu dans un manuel, `unconfirmed` = supposé, `verified` =
mesuré sur CE kit branché (check-drums.py, lot 4). Tout module réécrit sa table : un descripteur
`verified` est toujours celui d'UN kit, pas d'un modèle.
"""
import json
import os
import re

from . import config as C
from .golog import get

log = get("drumkits")
DIR = os.path.join(C.CONFIG_DIR, "drumkits")
# MESURES DE CE RACK (2026-10-03) : un kit mesuré s'écrivait DANS les graines suivies (config/drumkits/) et
# écrasait le descripteur du modèle — l'état d'une machine dans le dépôt (CLAUDE.md règle 2). Il va ici,
# hors dépôt, et y prend le pas sur la graine du même id.
LOCAL_DIR = os.path.join(C.CONFIG_DIR, "drumkits.local")
FALLBACK = "general-midi"
SCHEMA_MAX = 1
ELEMENTS = ("kick", "snare", "snare-rim", "snare-xstick",
            "tom1", "tom1-rim", "tom2", "tom2-rim", "tom3", "tom3-rim", "tom4", "tom4-rim",
            "hh-open", "hh-half", "hh-closed", "hh-pedal", "hh-splash", "hh-open-edge", "hh-closed-edge",
            "crash1", "crash1-edge", "crash2", "crash2-edge", "ride", "ride-edge", "ride-bell",
            "splash", "china", "aux1", "aux1-rim", "aux2", "aux2-rim", "aux3", "aux3-rim", "ext", "ext-rim")
# Ce qu'une SORTIE AUDIO du module peut transporter (docs/drums-kit.md §6.3) : un élément du kit,
# ou `kit-mix` — le master, c'est-à-dire TOUT LE RESTE. `kit-mix` n'est pas dans ELEMENTS et n'y
# entrera pas : un élément nomme une peau ou une cymbale, le mix n'en nomme aucune. Deux natures,
# deux vocabulaires — le jour où on les mélange, `element_of()` rendra « kit-mix » pour une note.
KIT_MIX = "kit-mix"
MASTERS = ("stereo", "mono", None)
CHOKES = ("poly-aftertouch", "note-off", "none", "unknown")
HH_NOTES = ("distinct", "single")             # ouverte/fermée = deux notes, ou une seule + CC
SOURCES = ("manual", "imported", "measured")
CONFIDENCES = ("verified", "reported", "unconfirmed")
POSITIONS = ("closed", "half", "open")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def validate(d, name=None):
    """Les problèmes qui rendent un descripteur INUTILISABLE (liste vide = valide)."""
    out = []
    if not isinstance(d, dict):
        return ["not a JSON object"]
    if not isinstance(d.get("id"), str) or not SLUG.match(d.get("id") or ""):
        out.append("`id` missing or not a slug")
    elif name and d["id"] != name:
        out.append(f"`id` = {d['id']!r} but the file is {name!r}")
    if d.get("kind") != "drumkit":
        out.append("`kind` must be \"drumkit\"")
    if not isinstance(d.get("schema"), int) or not 1 <= d["schema"] <= SCHEMA_MAX:
        out.append(f"`schema` must be 1..{SCHEMA_MAX}")
    if not d.get("name"):
        out.append("`name` missing")
    ident = d.get("identity")
    if not isinstance(ident, dict) or not ident.get("brand") or not ident.get("model"):
        out.append("`identity.brand` / `identity.model` missing")
    elif ident.get("connection") not in ("usb", "din", "usb+din"):
        out.append("`identity.connection` must be usb | din | usb+din")
    elif not isinstance(ident.get("usb_names"), list) or any(not isinstance(x, str) or not x for x in ident["usb_names"]):
        out.append("`identity.usb_names` must be a list of non-empty strings (empty list = not identifiable)")
    if not isinstance(d.get("channel"), int) or not 1 <= d["channel"] <= 16:
        out.append("`channel` must be 1..16")
    m = d.get("map")
    if not isinstance(m, dict) or not m:
        out.append("`map` missing or empty")
    else:
        seen = {}
        for k, v in m.items():
            if not (isinstance(k, str) and k.isdigit() and 0 <= int(k) <= 127):
                out.append(f"`map` key {k!r} is not a note 0..127")
            if v not in ELEMENTS:
                out.append(f"`map[{k}]` = {v!r} is not a kit element")
            if v in seen:
                out.append(f"element {v!r} mapped twice ({seen[v]} and {k})")
            seen[v] = k
        for must in ("kick", "snare"):
            if must not in seen:
                out.append(f"`map` has no {must}")
    hh = d.get("hihat")
    if not isinstance(hh, dict):
        out.append("`hihat` missing")
    else:
        cc = hh.get("cc")
        if cc is not None and not (isinstance(cc, int) and 0 <= cc <= 127):
            out.append("`hihat.cc` must be 0..127 or null (pedal = a switch)")
        if cc is not None:
            for k in ("open_value", "closed_value"):
                if not (isinstance(hh.get(k), int) and 0 <= hh[k] <= 127):
                    out.append(f"`hihat.{k}` must be 0..127 when a CC is declared")
            if isinstance(hh.get("open_value"), int) and hh.get("open_value") == hh.get("closed_value"):
                out.append("`hihat.open_value` equals `closed_value` — no direction")
        if hh.get("positions") not in (2, 3):
            out.append("`hihat.positions` must be 2 or 3 (three today; continuous later)")
        b = hh.get("bands")
        if hh.get("positions") == 3 and not (isinstance(b, list) and len(b) == 2 and all(isinstance(x, int) for x in b) and 0 < b[0] < b[1] < 100):
            out.append("`hihat.bands` must be two percentages 0 < a < b < 100 for three positions")
        if hh.get("notes") not in HH_NOTES:
            out.append("`hihat.notes` must be distinct | single")
    if d.get("choke") not in CHOKES:
        out.append("`choke` must be " + " | ".join(CHOKES))
    # `audio_outs` (§6.4) : ADDITIF et OPTIONNEL — un descripteur d'avant le 2026-09-20 n'en a pas,
    # et reste valide : il vaut « master stéréo, rien d'autre », dit comme tel par `audio_outs_of()`.
    # Présent, il est validé : un champ mal formé qui passe est pire qu'un champ absent, parce que
    # l'écran d'ajout en DÉDUIT combien de lanes poser.
    ao = d.get("audio_outs")
    if ao is not None:
        if not isinstance(ao, dict):
            out.append("`audio_outs` must be an object")
        else:
            if ao.get("master") not in MASTERS:
                out.append("`audio_outs.master` must be stereo | mono | null")
            n = ao.get("direct")
            if not isinstance(n, int) or not 0 <= n <= 16:
                out.append("`audio_outs.direct` must be an integer 0..16")
            if not isinstance(ao.get("assignable"), bool):
                out.append("`audio_outs.assignable` must be true or false (can the module reassign its direct outs?)")
            dflt = ao.get("default")
            if dflt is not None:
                if not isinstance(dflt, list):
                    out.append("`audio_outs.default` must be a list of elements")
                else:
                    if isinstance(n, int) and len(dflt) > n:
                        out.append(f"`audio_outs.default` has {len(dflt)} entries for {n} direct out(s)")
                    for i, el in enumerate(dflt):
                        if el not in ELEMENTS and el != KIT_MIX:
                            out.append(f"`audio_outs.default[{i}]` = {el!r} is not a kit element")
            if ao.get("master") is None and not n:
                out.append("`audio_outs` declares no output at all — omit it instead")
    prov = d.get("provenance")
    if not isinstance(prov, dict):
        out.append("`provenance` missing")
    else:
        if prov.get("source") not in SOURCES:
            out.append("`provenance.source` must be " + " | ".join(SOURCES))
        if prov.get("confidence") not in CONFIDENCES:
            out.append("`provenance.confidence` must be " + " | ".join(CONFIDENCES))
        if not prov.get("note"):
            out.append("`provenance.note` empty — where does this table come from?")
        if prov.get("confidence") == "verified" and prov.get("source") != "measured":
            out.append("`verified` needs `source: measured` — only a kit under the sticks verifies a table")
    return out


def _read(path):
    with open(path, encoding="utf8") as fh:
        return json.load(fh)


def load_all(strict=False):
    """{id: descripteur} — un fichier invalide est journalisé et IGNORÉ (strict=True : levé)."""
    out = {}
    files = [(d, f) for d in (DIR, LOCAL_DIR) if os.path.isdir(d)       # la mesure locale APRÈS : elle gagne
             for f in sorted(os.listdir(d)) if f.endswith(".json")]
    for folder, f in files:
        path = os.path.join(folder, f)
        try:
            d = _read(path)
        except Exception as e:
            if strict:
                raise
            log.warning(f"descripteur illisible {f} : {e}")
            continue
        probs = validate(d, os.path.splitext(f)[0])
        if probs:
            if strict:
                raise ValueError(f"{f}: " + "; ".join(probs))
            log.warning(f"descripteur ignoré {f} : " + "; ".join(probs))
            continue
        out[d["id"]] = d
    return out


def get(kid):
    return load_all().get(str(kid or ""))


def listing():
    """Pour l'écran : [{id, name, brand, model, confidence, source, fallback}] — le repli en dernier."""
    rows = []
    for kid, d in load_all().items():
        p = d.get("provenance") or {}
        rows.append({"id": kid, "name": d["name"], "brand": d["identity"]["brand"], "model": d["identity"]["model"],
                     "confidence": p.get("confidence"), "source": p.get("source"), "fallback": kid == FALLBACK,
                     # les SORTIES AUDIO (§6.4) : c'est elles qui décident combien de lanes l'écran
                     # d'ajout propose. `declared: False` = personne n'a rempli le champ, l'écran le
                     # dit au lieu d'affirmer « ce module n'a qu'un master ».
                     "audio_outs": audio_outs_of(d),
                     "note": d.get("note")})
    rows.sort(key=lambda r: (r["fallback"], r["name"].lower()))
    return rows


def identify(device_name):
    """Le descripteur dont un `identity.usb_names` est une sous-chaîne (sans casse) du nom ALSA du
    périphérique ; le plus LONG motif gagne (« TD-17 » avant « TD- »). Repli : general-midi.
    Rend (id, auto:bool, fallback:bool)."""
    name = str(device_name or "").lower()
    best, best_len = None, 0
    if name:
        for kid, d in load_all().items():
            for pat in (d.get("identity") or {}).get("usb_names") or []:
                if pat.lower() in name and len(pat) > best_len:
                    best, best_len = kid, len(pat)
    if best:
        return best, True, False
    return FALLBACK, True, True


def resolve(binding):
    """Le kit d'un binding USB (soundcard.json usb{n}) : `kit` explicite s'il existe encore, sinon
    l'identification par le nom du périphérique. Rend {id, name, confidence, auto, fallback}."""
    kits = load_all()
    kid = (binding or {}).get("kit")
    auto, fallback = False, False
    if not kid or kid not in kits:
        kid, auto, fallback = identify((binding or {}).get("device"))
    d = kits.get(kid) or {}
    return {"id": kid, "name": d.get("name") or kid, "confidence": ((d.get("provenance") or {}).get("confidence")),
            "auto": auto, "fallback": fallback}


# L'ordre dans lequel on propose les éléments quand le descripteur ne dit rien (§6.4) : ce qu'un
# batteur sort en premier sur des directes, et le reste en paire. GÉNÉRIQUE, donc dit comme tel
# (`generic: True`) — les directes sont réassignables sur le module, cette liste est un point de
# départ à corriger à l'écran, jamais une vérité sur CE module.
GENERIC_OUTS = ("kick", "snare", "hh-closed", "tom1", "tom2", "tom3", "ride", "crash1")


def audio_outs_of(desc):
    """Ce que le module sort en AUDIO, normalisé (docs/drums-kit.md §6.4).

    Un descripteur sans `audio_outs` vaut « master stéréo, aucune sortie directe » — le cas de
    l'immense majorité des modules — et le DIT (`declared: False`) : l'écran distingue « le
    descripteur affirme qu'il n'y a que le master » de « personne n'a rempli ce champ ».
    `default` absent : une proposition générique, marquée `generic: True`."""
    ao = (desc or {}).get("audio_outs")
    if not isinstance(ao, dict):
        return {"master": "stereo", "direct": 0, "assignable": False,
                "default": [], "declared": False, "generic": True}
    n = int(ao.get("direct") or 0)
    dflt = [e for e in (ao.get("default") or []) if e in ELEMENTS or e == KIT_MIX]
    generic = not dflt
    if generic:
        dflt = list(GENERIC_OUTS[:n])
    return {"master": ao.get("master", "stereo"), "direct": n, "assignable": bool(ao.get("assignable")),
            "default": dflt[:n], "declared": True, "generic": generic}


def element_of(desc, note):
    """Note MIDI du module -> élément du kit, ou None (une note inconnue ne fait RIEN — même loi
    que la scène absente d'un arrangement)."""
    return ((desc or {}).get("map") or {}).get(str(int(note)))


def hihat_position(desc, cc_value):
    """Valeur du CC de charleston -> "closed" | "half" | "open", selon le SENS déclaré et les bandes."""
    hh = (desc or {}).get("hihat") or {}
    if hh.get("cc") is None or cc_value is None:
        return None
    o, c = hh.get("open_value", 0), hh.get("closed_value", 127)
    span = (c - o) or 1
    pct = max(0.0, min(100.0, (float(cc_value) - o) * 100.0 / span))     # 0 = ouvert … 100 = fermé
    if hh.get("positions") == 2:
        return "closed" if pct >= 50 else "open"
    a, b = (hh.get("bands") or [33, 66])
    return "open" if pct < a else ("half" if pct < b else "closed")


# ── la traduction module -> kit (lot 2) : ce que le JSFX golem_drumtrans lit dans gmem ──────────────
HH_FALLBACK = {"hh-half": ("hh-closed", "hh-open"), "hh-open": ("hh-half", "hh-closed"), "hh-closed": ("hh-half", "hh-open"),
               "snare-xstick": ("snare-rim", "snare"), "snare-rim": ("snare",), "tom1-rim": ("tom1",), "tom2-rim": ("tom2",),
               "tom3-rim": ("tom3",), "tom4-rim": ("tom4",), "tom4": ("tom3", "tom2"), "tom3": ("tom2",), "tom2": ("tom1",),
               "crash1-edge": ("crash1",), "crash2-edge": ("crash2", "crash1"), "crash2": ("crash1",), "ride-edge": ("ride",),
               "ride-bell": ("ride",), "hh-open-edge": ("hh-open",), "hh-closed-edge": ("hh-closed",), "hh-splash": ("hh-open",),
               "splash": ("crash1",), "china": ("crash2", "crash1"), "ext": ("tom4", "tom3"), "ext-rim": ("ext",),
               "aux1": ("tom4",), "aux2": ("tom4",), "aux3": ("tom4",)}


def kit_note(kit_notes, element):
    """La note du kit pour un élément — ou celle de l'élément le plus proche que le kit possède
    (un rim sans rim tombe sur la tête, un tom 4 sur un kit à deux toms tombe sur le dernier), ou None."""
    if element in kit_notes:
        return kit_notes[element]
    for alt in HH_FALLBACK.get(element, ()):
        if alt in kit_notes:
            return kit_notes[alt]
    return None


def translation(desc, kit_notes):
    """Descripteur du module + table du kit -> {map: [128 notes du kit, -1 = rien], hh: {cc, open_value,
    closed_value, band_a, band_b, positions, closed, half, open (notes du kit, -1 si absent)}, lost: [...]}.
    `lost` = les éléments du module que le kit ne sait pas jouer, même par repli — dits, jamais avalés."""
    m = [-1] * 128
    lost = []
    for k, el in ((desc or {}).get("map") or {}).items():
        n = kit_note(kit_notes or {}, el)
        if n is None:
            lost.append(el)
        else:
            m[int(k)] = n
    hh = dict((desc or {}).get("hihat") or {})
    bands = hh.get("bands") or [33, 66]
    out_hh = {"cc": hh.get("cc") if hh.get("cc") is not None else -1,
              "open_value": hh.get("open_value") if hh.get("open_value") is not None else 0,
              "closed_value": hh.get("closed_value") if hh.get("closed_value") is not None else 127,
              "band_a": bands[0] if len(bands) > 0 else 33, "band_b": bands[1] if len(bands) > 1 else 66,
              "positions": hh.get("positions") or 3}
    for pos, el in (("closed", "hh-closed"), ("half", "hh-half"), ("open", "hh-open")):
        n = kit_note(kit_notes or {}, el)
        out_hh[pos] = n if n is not None else -1
    return {"map": m, "hh": out_hh, "lost": sorted(set(lost)), "channel": int((desc or {}).get("channel") or 10)}
