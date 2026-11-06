#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LA CHANSON D'USINE « Golem Rising » (2026-10-20) : le cas d'usage que l'usine ne montrait pas — une chanson écrite de
bout en bout, dont l'ARRANGEMENT change, à chaque partie, la scène, le groove de la boîte à rythmes et des pédales
(docs/arrangement.md §1 et §6). Metal progressif moderne, 120 BPM, 57 mesures, sur le preset « Ambient Metal »
(tools/make-factory-ambient-metal.py) : des clairs aériens, une rythmique grave et serrée, un solo qui s'envole.

2026-10-20 : la première version (preset rock « Rock Anthem », grooves rock) était molle ; la chanson garde sa
structure et prend les sons et les rythmes d'Ambient Metal. Rock Anthem a quitté l'usine.

Pourquoi un script : comme les grooves (tools/make-factory-grooves.py), un objet d'usine se relit, se corrige et se
régénère. Il écrit, dans library/factory/ :
  - patches/factory-guitar-hero-lead.json   le patch Hero Lead de la banque guitare, fait de captures DÉJÀ livrées ;
  - songs/rs-<id>.golem                     LA CHANSON : sa fiche (preset, tempo, arrangement — scène, groove et
                                            pédales par partie), sa pochette et la photo du groupe
                                            (tools/gen-factory-song-art.py, Nano Banana) ;
  - setlists/factory.json                   la ligne « Golem Rising », qui JOUE la chanson ; et l'arrangement RETIRÉ de
                                            « Rented Room Blues » (2026-10-20 : pas d'arrangement sur un standard) ;
  - setlists/factory-guitar.json            Hero Lead dans la banque de guitare.
Le preset vient AVANT : lancer d'abord tools/make-factory-ambient-metal.py.

    .venv/bin/python tools/make-factory-song.py [--art <dossier des images>]
"""
import argparse
import copy
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FACTORY = os.path.join(ROOT, "library", "factory")

from bridge import patches  # noqa: E402

BPM = 120
# le rang de chaque groove dans les motifs du bloc Drum Machine d'Ambient Metal (GROOVES de make-factory-ambient-metal.py)
INTRO, VERSE, CHORUS, BREAKDOWN, SOLO, FILL, END = range(7)
PRESET = "factory-ambient-metal"


def _load(rel):
    with open(os.path.join(FACTORY, rel), encoding="utf-8") as f:
        return json.load(f)


def _dump(rel, doc):
    with open(os.path.join(FACTORY, rel), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _block(pid, bid):
    """Un bloc d'un patch d'usine, tel quel (ref et modèle TONE3000 compris) — Hero Lead ne demande rien de neuf."""
    d = _load(f"patches/{pid}.json")
    ch = d["lanes"][0]["chain"]
    for b in (ch.get("pre") or []) + [x for br in ((ch.get("split") or {}).get("branches") or []) for x in br.get("blocks") or []] \
            + (ch.get("post") or []) + (ch.get("chain") or []):
        if b.get("id") == bid:
            return copy.deepcopy(b)
    raise SystemExit(f"bloc {bid} introuvable dans {pid}")


# ── 1. HERO LEAD : la guitare 2 ───────────────────────────────────────────────────────────────────────────────────
def hero_lead():
    """Le son du solo, au bord de la saturation (2026-10-20 : « superbe son clair, et saturation avec une tube scream
    cristalline ») : pas un ampli high-gain — une TS9 réglée bas en gain et haut en niveau qui pousse un Fender Deluxe
    au bord de la saturation, un compresseur lent qui laisse passer l'attaque, deux delays (croche pointée au centre,
    écho à bande en ping-pong, bas dans le mix) et une plate. Le clair : un Twin Reverb « bright », le plus propre de
    l'usine. Deux branches (merge), une SEULE ouverte par état : jamais deux amplis sommés. La TS reste en tête de
    chaîne : au pied (SW7) sur le clair, elle pousse le Twin — un clair boosté qui brille, voulu."""
    ts = _block("factory-guitar-singing-clean", "ts")
    deluxe = _block("factory-guitar-singing-clean", "deluxe")
    dxcab = _block("factory-guitar-singing-clean", "dxcab")
    twin = dict(_block("factory-guitar-fuzz-wall", "b4"), id="twin", params={"input": 0, "output": 0})
    twcab = dict(copy.deepcopy(dxcab), id="twcab")
    # la TS9 (Drive 2 · Tone 7 · Level 10) est déjà la plus forte du pack et pedal-nam n'est PAS normalisé
    # (compile_rig.NORMALIZED_TYPES) : sortie à 0, sinon le lead s'écrase et grésille
    ts.update(foot=7, params=dict(ts.get("params") or {}, input=0, output=0))
    deluxe["params"] = dict(deluxe.get("params") or {}, input=0, output=0)
    chain = {
        "pre": [{"id": "gate", "type": "gate", "params": {"thresh": -62, "attack": 2, "release": 180}},
                {"id": "comp", "type": "comp", "params": {"thresh": -24, "ratio": 2.5, "makeup": 2, "attack": 30, "release": 200}},
                ts],
        "split": {"mode": "merge", "gain": -3, "branches": [{"id": "lane-a", "blocks": [deluxe, dxcab]},
                                                            {"id": "lane-b", "blocks": [twin, twcab]}]},
        # le Calf a SON tempo (pas celui du projet) : posé à 120, sinon l'écho dérive
        "post": [{"id": "dly", "type": "delay", "foot": 8, "params": {"time": "1/8•", "feedback": 22, "mix": 12}},
                 {"id": "echo", "type": "delay-tape", "params": {"time": "1/4", "time_r": "1/2", "tempo": BPM, "feedback": 15,
                                                                 "mix": 8, "medium": "Tape"}},
                 {"id": "verb", "type": "reverb-plate", "params": {"mix": 16, "decay": 2.0, "predelay": 30, "hicut": 7000}}],
    }
    off = {"comp": False, "ts": False, "dly": False, "echo": False}
    lead = {**off, "comp": True, "ts": True, "dly": True, "echo": True}
    states = [
        ("A", "Clean Arp", {**off, "comp": True, "dly": True, "echo": True},
         {"dly": {"mix": 12, "feedback": 22}, "echo": {"mix": 8}, "verb": {"mix": 18, "decay": 2.0}}, {"lane-a": {"mute": True}}, 0),
        ("B", "Rhythm Drive", {**off, "ts": True}, {"deluxe": {"input": -2}, "verb": {"mix": 12, "decay": 1.4}},
         {"lane-b": {"mute": True}}, 0),
        ("C", "Hero Lead", lead, {"deluxe": {"input": 0}, "dly": {"mix": 14, "feedback": 25}, "echo": {"mix": 10, "feedback": 18},
                                  "verb": {"mix": 16, "decay": 2.0, "predelay": 30}}, {"lane-b": {"mute": True}}, 2),
        ("D", "Big Lead", lead, {"dly": {"mix": 18, "feedback": 32}, "echo": {"mix": 14, "feedback": 25},
                                 "verb": {"mix": 24, "decay": 2.6}}, {"lane-b": {"mute": True}}, 1),
    ]
    lane = {"id": "guitar-1", "role": "guitar", "name": "Hero Lead", "midi": False, "chain": chain,
            "states": [{"id": f"st-guitar-1-{sid}", "name": nm, "blocks": bl, "params": pa, "branches": br}
                       for sid, nm, bl, pa, br, _lvl in states]}
    scenes = []
    for sid, nm, bl, pa, br, lvl in states:
        sc = {"id": sid, "name": nm, "blocks": bl, "lanes": {"guitar-1": {"state": f"st-guitar-1-{sid}", **({"level": lvl} if lvl else {})}}}
        if pa:
            sc["params"] = pa
        if br:
            sc["branches"] = br
        if lvl:
            sc["level"] = lvl
        scenes.append(sc)
    gold = "#d9a520"
    doc = {"id": "factory-guitar-hero-lead", "name": "Hero Lead", "role": "guitar", "tags": ["rock", "lead", "solo"],
           "kind": "patch", "patch_v": 2, "lanes_v": 2, "lanes": [lane], "scenes": scenes,
           # de quoi jouer seul (tests/test_factory.py) : la boîte à rythmes sur SW10, REC sur SW9
           "config": {"gen": {"out": "1-2", "blocks": [{"type": "drums", "id": "drums", "foot": 10, "params": {
               "patterns": ["library/grooves/golem-rock-8.mid"], "fills": [], "kit": "drums-black-pearl"}}]},
                      "rec": {"blocks": [{"id": "rec-global", "type": "rec", "foot": 9}]}},
           "bpm": BPM, "chain": copy.deepcopy(chain), "needs": patches.needs_of(chain), "origin": "factory", "factory": True,
           # le thème sur chaque case OCCUPÉE : les scènes, SW7 (TS), SW8 (delay), SW9 (REC), SW10 (batterie)
           "colors": {k: gold for k in ("A", "B", "C", "D", "7", "8", "9", "10")},
           "anims": {"A": "ripple", "B": "ember", "C": "sheen", "D": "vortex", "7": "pulse", "8": "rain", "9": "heartbeat", "10": "stars"}}
    # posé dans library/patches/ (l'état local), comme le bridge le fait au démarrage : le dépôt et l'export le lisent là
    local = os.path.join(ROOT, "library", "patches", "factory-guitar-hero-lead.json")
    with open(local, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    # ses DEPS (ce que golem.fm lit : l'empreinte de chaque capture) — calculées comme patches.refresh_deps, par l'export
    from bridge import preset_export
    out, _blobs = preset_export.build_export(patches.PATCH_PREFIX + doc["id"])
    if out is not None:
        doc["deps"], doc["deps_sig"] = out.get("deps") or [], patches._v2_sig(doc)
        if out.get("unresolved"):
            doc["unresolved"] = out["unresolved"]
    with open(local, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    _dump("patches/factory-guitar-hero-lead.json", doc)
    return doc


# ── 2. OUTILS DE LANE (aussi pour tools/make-factory-ambient-metal.py) ─────────────────────────────────────────────
def _lane_sets(L):
    """Les ids, types et branches d'une lane — la même tranche que le Designer (app/designer-model.js laneSets)."""
    ch = L.get("chain") or {}
    blocks = (ch.get("pre") or []) + [b for br in ((ch.get("split") or {}).get("branches") or []) for b in br.get("blocks") or []] \
        + (ch.get("post") or [])
    brs = {br.get("id") for br in ((ch.get("split") or {}).get("branches") or []) if br.get("id")}
    return {b.get("id") for b in blocks if b.get("id")}, {b.get("type") for b in blocks if b.get("type")}, brs


# ── 3. LA LIGNE « Golem Rising » ET SON ARRANGEMENT ───────────────────────────────────────────────────────────────
SECTIONS = [  # nom, mesures, scène (None = celle qui joue), groove (None = celui d'avant), bascules de pédales
    # Les BASCULES (docs/arrangement.md §1 : « la scène d'abord, puis les bascules ») touchent les pédales — jamais un
    # ampli ni un baffle, c'est l'affaire de la scène. Une partie qui rappelle une scène repart de ce que la scène dit :
    # une bascule ne vaut que pour SA partie. Ids d'Ambient Metal (après le dépôt des patches) :
    #   guitare 1 : ts, chorus, dly · guitare 2 : ts-2, chorus-2, dly-2, echo, shim · piano : dly-3, shim-2
    #   voix : scream (grain), double (doublage), dly-4 · basse : pas de pédale — ses états ouvrent ou ferment la
    #   Darkglass, elle suit les scènes
    # Scènes : A Halo Clean · B Glass Verse (clairs) · C Low Riff · D Wall Chorus · E Soaring Solo (saturées)
    ("Intro", 4, "A", INTRO, {"dly-3": True}),                                       # la nappe, le piano en écho
    ("Verse 1", 7, "B", VERSE, {"shim-2": True}),                                    # le piano devant, un halo dessous
    ("Fill", 1, None, FILL, {"ts": True, "scream": True}),                           # un trait saturé, un cri
    ("Chorus", 8, "D", CHORUS, {"chorus-2": True}),                                  # le mur, la guitare 2 élargie
    ("Verse 2", 7, "C", BREAKDOWN, {"dly-3": True}),                                 # le 2e couplet tombe dans le grave
    ("Fill", 1, None, FILL, {"shim": True, "scream": True}),
    ("Chorus", 7, "D", CHORUS, {"echo": True}),                                      # le riff de la 2 part en écho
    ("Fill", 1, None, FILL, {"dly-2": True, "scream": True}),                        # l'écho annonce le solo
    ("Solo", 4, "E", SOLO, {"chorus": True}),                                        # le lit s'élargit sous le lead
    ("Solo · climb", 4, None, None, {"shim": True}),                                 # le shimmer ouvre le ciel
    ("Chorus", 8, "D", CHORUS, {"shim": True, "double": True, "dly-3": True}),       # le dernier refrain, plein ciel
    ("Outro", 4, "C", BREAKDOWN, {"shim-2": True, "scream": True}),                  # on finit dans le grave
    ("End", 1, None, END, {"dly": True, "shim": True, "shim-2": True}),              # le coup final et sa traîne
]
TITLE, ARTIST = "Golem Rising", "golem"
# l'id d'une chanson née sur un rack (docs/songs.md §2) — frappé ici UNE fois, d'après son nom, pour que chaque
# génération rende le même fichier ; il ne change plus jamais
SONG_ID = "rs:" + hashlib.sha256(b"golem-factory|golem-rising").hexdigest()[:32]


def _sections(p):
    """Les parties, chaque bascule vérifiée : un bloc qui n'existe pas dans le preset est une faute de frappe, pas une
    bascule ignorée en silence au premier concert."""
    known = {b["id"] for ln in p["lanes"] for b in _lane_blocks(ln)}
    secs = []
    for name, bars, scene, groove, blocks in SECTIONS:
        bad = sorted(set(blocks) - known)
        if bad:
            raise SystemExit(f"partie {name} : blocs inconnus du preset {bad}")
        s = {"name": name, "bars": bars}
        if scene:
            s["scene"] = scene
        if groove is not None:
            s["drums"] = groove
        if blocks:
            s["blocks"] = dict(blocks)
        secs.append(s)
    return secs


def _lane_blocks(ln):
    ch = ln.get("chain") or {}
    return (ch.get("pre") or []) + [b for br in ((ch.get("split") or {}).get("branches") or []) for b in br.get("blocks") or []] \
        + (ch.get("post") or [])


def _sheet(p):
    return {"preset": p["id"], "bpm": BPM, "tuning": "Standard",
            "arrangement": {"type": "arrangement", "id": "arr-song", "params": {
                "advance": "bars", "sig": {"num": 4, "den": 4}, "count_in": 1,
                "starts": {"drums": True, "click": False, "backing": False}, "sections": _sections(p)}}}


def song_line(p):
    sl = _load("setlists/factory.json")
    lines = [ln for ln in sl["lines"] if ln.get("title") != TITLE]
    for ln in lines:
        if ln.get("title") == "Rented Room Blues":
            ln.pop("arrangement", None)               # pas d'arrangement sur un standard (2026-10-20)
    # la ligne JOUE la chanson (`band_song`, docs/songs.md §9.7) et porte aussi une COPIE de sa fiche : une chanson
    # supprimée par l'utilisateur laisse la ligne jouer ce qu'elle porte, jamais une ligne vide
    lines.append({"id": "r:factory:8", "rev": 1, "band_song": SONG_ID, "title": TITLE, **_sheet(p)})
    sl["lines"] = lines
    sl["presets"] = [ln.get("preset") for ln in lines]           # la LISTE des presets joués, ligne à ligne
    _dump("setlists/factory.json", sl)
    g = _load("setlists/factory-guitar.json")
    if not any(ln.get("patch") == "factory-guitar-hero-lead" for ln in g["lines"]):
        g["lines"].append({"id": "r:factory-guitar:herolead", "rev": 1, "title": "Hero Lead", "patch": "factory-guitar-hero-lead"})
        g["presets"] = ["patch:" + ln["patch"] for ln in g["lines"]]
        _dump("setlists/factory-guitar.json", g)
    return sum(x[1] for x in SECTIONS)


# ── 4. LA CHANSON : library/factory/songs/<id>.golem ──────────────────────────────────────────────────────────────
def song_file(p, art_dir=None):
    """Le `.golem` de la chanson (docs/golem-format.md) : manifeste, fiche (sheet.json) et images. Les IMAGES viennent
    de `art_dir` (tools/gen-factory-song-art.py) ou, à défaut, du fichier déjà livré : on ne les régénère pas à chaque
    passage. Pas de copie du preset dans la fiche (`preset_doc`) : l'usine pose le preset elle-même, et le rack la
    calcule en tâche de fond (songs.snapshot_preset)."""
    from bridge import golemfile as GF
    from bridge import songs as SG
    out = os.path.join(FACTORY, "songs", SG._safe(SONG_ID) + ".golem")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    art = {}
    for name in ("cover", "band"):
        src = os.path.join(art_dir, name + ".jpg") if art_dir else None
        if src and os.path.exists(src):
            with open(src, "rb") as f:
                art[name] = f.read()
        elif os.path.exists(out):
            art[name] = GF.read_member(out, f"art/{name}.jpg")
        else:
            raise SystemExit(f"pas d'image {name} : tools/gen-factory-song-art.py <dossier>, puis --art <dossier>")
    sheet = SG.clean_sheet(_sheet(p))
    if sheet.get("arrangement", {}).get("params", {}).get("sections") != _sheet(p)["arrangement"]["params"]["sections"]:
        raise SystemExit("la fiche ne survit pas au nettoyeur de lignes (songs.clean_sheet) : un champ de partie s'y perd")
    m = {"format": GF.FORMAT, "type": "song", "id": SONG_ID, "title": TITLE, "artist": ARTIST,
         "genres": [{"family": "rock", "subgenre": None}],
         "credits": {"work": {"composers": [ARTIST]}},
         "kind": "original", "rights": {"work": "own"},
         "recording": {"duration_ms": round(sum(x[1] for x in SECTIONS) * 4 * 60000 / BPM)},
         "repertoire": {"rev": 1},
         "files": {"art/cover.jpg": {"role": "cover"}, "art/band.jpg": {"role": "band"}}}
    GF.write(out, m, {"art/cover.jpg": art["cover"], "art/band.jpg": art["band"],
                      "sheet.json": json.dumps(sheet, ensure_ascii=False, indent=1).encode("utf-8")})
    GF.verify(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--art", help="le dossier des images neuves (cover.jpg, band.jpg) — sinon celles du .golem livré")
    a = ap.parse_args()
    hero_lead()
    p = _load(f"presets/{PRESET}.json")
    bars = song_line(p)
    print(os.path.relpath(song_file(p, a.art), ROOT))
    print(f"Golem Rising sur {p['name']} ({len(p['lanes'])} lanes, {len(p['scenes'])} scènes) : {bars} mesures, "
          f"{bars * 4 * 60 / BPM:.0f} s à {BPM} BPM")
