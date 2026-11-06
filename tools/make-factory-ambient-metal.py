#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LE PRESET D'USINE « Ambient Metal » (2026-10-20) : metal progressif moderne — des clairs aériens (chorus, grande salle,
shimmer), une rythmique grave et serrée façon djent, un lead qui chante, un piano qui fleurit en nappe, une voix en
falsetto. Cinq scènes : deux claires (Halo Clean, Glass Verse), trois saturées (Low Riff, Wall Chorus, Soaring Solo).

D'où vient le son : le MATÉRIEL a été proposé par l'IA de patch de golem.fm (une tête 6505+ devant un 4x12 V30, une
basse en bi-ampli SVT + Darkglass B7K), la NATURE de chaque capture relue dans ses fichiers .nam (une capture « full rig »
ne prend pas de baffle derrière elle), les réglages et l'étagement posés à la main. Aucun nom d'artiste nulle part
(docs/factory.md §1) : les noms de scène et d'état sont des noms de jeu.

Il écrit, dans library/factory/ :
  - patches/factory-guitar-ambient-djent.json   guitare 1 : JC-120 pour les clairs, TS9 + 6505+ + V30 pour la rythmique ;
  - patches/factory-guitar-soaring-lead.json    guitare 2 : Twin Reverb pour les clairs, TS9 + EVH 5150 pour le lead ;
  - patches/factory-bass-biamp-grit.json        basse : SVT clair + B7K saturée en parallèle ;
  - patches/factory-keys-cathedral-piano.json   piano : Salamander, qui fleurit en nappe par le shimmer ;
  - patches/factory-voice-halo.json             voix : falsetto, doublage, plate, grain pour les refrains lourds ;
  - presets/factory-ambient-metal.json          le preset : chaque lane DÉPOSÉE depuis son patch (patches.apply_to),
                                                la boîte à rythmes sur SW10 avec les sept grooves metal, et
                                                l'Arrangement sur SW9 (c'est le preset de « Golem Rising ») ;
  - setlists/factory-{guitar,bass,keys,voice}.json  chaque patch dans sa banque.

    .venv/bin/python tools/make-factory-ambient-metal.py
"""
import copy
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bridge import patches  # noqa: E402

# les outils de la chanson d'usine (charger un bloc d'un patch d'usine, écrire, lire les blocs d'une lane)
_spec = importlib.util.spec_from_file_location("make_factory_song", os.path.join(ROOT, "tools", "make-factory-song.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

BPM = 120
G = "library/grooves/golem-metal-"
# l'ordre COMPTE : l'arrangement de « Golem Rising » désigne un groove par son rang dans cette liste
GROOVES = ("intro", "verse", "chorus", "breakdown", "solo", "fill", "end")
KIT = "drums-black-pearl"          # joue sur toute installation (aasimonster est un pack optionnel de 2,3 Go)
SALAMANDER = "library/sfz/SalamanderGrandPiano-SFZ+FLAC-V3+20200602/SalamanderGrandPiano-V3+20200602.sfz"


def _drums(groove):
    return {"type": "drums", "id": "drums", "foot": 10, "params": {"patterns": [G + groove + ".mid"], "fills": [], "kit": KIT}}


def _cells(states, feet):
    return [sid for sid, *_ in states] + [str(f) for f in sorted(feet)]


def patch(pid, name, role, tags, chain, states, *, service, color, anims, midi=False):
    """Un patch d'usine : une lane, ses états, une scène par état, de quoi jouer seul (batterie SW10, REC ou Riff SW9),
    le thème sur chaque case occupée. Posé dans library/patches/ (l'état local, d'où le dépôt le lit), ses DEPS calculées
    par l'export (comme patches.refresh_deps), puis écrit dans library/factory/patches/."""
    lane_id = f"{role}-1"
    lane = {"id": lane_id, "role": role, "name": name, "midi": midi, "chain": chain,
            "states": [{"id": f"st-{lane_id}-{sid}", "name": nm, "blocks": bl, "params": pa, "branches": br}
                       for sid, nm, bl, pa, br, _lvl in states]}
    scenes = []
    for sid, nm, bl, pa, br, lvl in states:
        sc = {"id": sid, "name": nm, "blocks": bl, "lanes": {lane_id: {"state": f"st-{lane_id}-{sid}", **({"level": lvl} if lvl else {})}}}
        if pa:
            sc["params"] = pa
        if br:
            sc["branches"] = br
        if lvl:
            sc["level"] = lvl
        scenes.append(sc)
    feet = {b["foot"] for b in S._lane_blocks(lane) + (chain.get("chain") or []) if b.get("foot")} | {9, 10}
    cells = _cells(states, feet)
    assert set(anims) == set(cells), (pid, sorted(set(cells) ^ set(anims)))
    rec = {"id": "rec-global", "type": "rec", "foot": 9} if service == "rec" else \
        {"id": "compo-global", "type": "compo", "foot": 9}
    doc = {"id": pid, "name": name, "role": role, "tags": tags, "kind": "patch", "patch_v": 2, "lanes_v": 2,
           "lanes": [lane], "scenes": scenes,
           "config": {"gen": {"out": "1-2", "blocks": [_drums(states and service_groove[pid])]}, "rec": {"blocks": [rec]}},
           "bpm": BPM, "chain": copy.deepcopy(chain), "needs": patches.needs_of(chain), "origin": "factory", "factory": True,
           "colors": {k: color for k in cells}, "anims": anims}
    local = os.path.join(ROOT, "library", "patches", pid + ".json")
    with open(local, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    from bridge import preset_export
    out, _blobs = preset_export.build_export(patches.PATCH_PREFIX + pid)
    if out is not None:
        doc["deps"], doc["deps_sig"] = out.get("deps") or [], patches._v2_sig(doc)
        if out.get("unresolved"):
            doc["unresolved"] = out["unresolved"]
    with open(local, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    S._dump(f"patches/{pid}.json", doc)
    return doc


# le groove de chaque patch joué seul (SW10)
service_groove = {"factory-guitar-ambient-djent": "verse", "factory-guitar-soaring-lead": "solo",
                  "factory-bass-biamp-grit": "breakdown", "factory-keys-cathedral-piano": "intro",
                  "factory-voice-halo": "chorus"}


# ── 1. GUITARE 1 : Ambient Djent ──────────────────────────────────────────────────────────────────────────────────
def ambient_djent():
    """Les clairs : un JC-120 (full rig, la plus grande réserve de propreté de l'usine) sous chorus et grande salle. La
    rythmique : une TS9 qui resserre le grave d'une tête 6505+ moins saturée que la Stealth, dans un 4x12 V30 — le
    montage djent classique. Une seule branche ouverte par état ; la salle n'est jamais coupée (seul son mix bouge), pour
    qu'une traîne claire continue sous le premier coup lourd."""
    ts = S._block("factory-guitar-singing-clean", "ts")
    ts.update(foot=6, params={"input": 0, "output": -3})
    peavey = {"id": "peavey", "type": "amp-nam", "label": "Peavey 6505+", "ref": "29230", "model": "418311",
              "params": {"input": 0, "output": 0}}
    v30 = S._block("factory-guitar-modern-metal", "v30")
    jc = dict(S._block("factory-guitar-jazz-clean", "jc"), params={"input": -3, "output": 0})
    chain = {
        "pre": [{"id": "gate", "type": "gate", "params": {"thresh": -50, "attack": 1, "hold": 30, "release": 70, "hyst": -4}},
                {"id": "comp", "type": "comp", "params": {"thresh": -26, "ratio": 3, "makeup": 3, "attack": 20, "release": 180}},
                ts],
        "split": {"mode": "merge", "gain": -3, "branches": [{"id": "lane-a", "blocks": [peavey, v30]},
                                                            {"id": "lane-b", "blocks": [jc]}]},
        "post": [{"id": "eq", "type": "eq-para", "params": {"lowcut_on": True, "lowcut": 90, "bass": 0, "f1": 450, "g1": -3,
                                                            "f2": 1500, "g2": 1, "f3": 6500, "g3": -2.5, "treble": 0}},
                 {"id": "chorus", "type": "chorus-js", "foot": 8, "params": {"length": 18, "voices": 3, "rate": 0.35, "wet": -10, "dry": 0}},
                 {"id": "dly", "type": "delay", "foot": 7, "params": {"time": "1/8•", "feedback": 35, "mix": 16}},
                 {"id": "verb", "type": "reverb", "params": {"mix": 22, "decay": 3.2, "size": 40, "hicut": 6500}}],
    }
    clean_eq = {"lowcut": 80, "g1": -1, "g2": 0, "g3": -1}
    states = [
        ("A", "Halo Clean", {"comp": True, "ts": False, "chorus": True, "dly": True},
         {"gate": {"thresh": -66}, "eq": clean_eq, "dly": {"time": "1/4", "feedback": 40, "mix": 20},
          "verb": {"mix": 30, "decay": 3.8, "size": 46}}, {"lane-a": {"mute": True}}, 0),
        ("B", "Glass Arp", {"comp": True, "ts": False, "chorus": True, "dly": True},
         {"gate": {"thresh": -66}, "eq": clean_eq, "dly": {"time": "1/8•", "feedback": 30, "mix": 14},
          "verb": {"mix": 20, "decay": 2.6, "size": 36}}, {"lane-a": {"mute": True}}, 0),
        ("C", "Low Riff", {"comp": False, "ts": True, "chorus": False, "dly": False},
         {"gate": {"thresh": -48, "release": 50}, "verb": {"mix": 8, "decay": 1.4, "size": 24}}, {"lane-b": {"mute": True}}, 0),
        ("D", "Wall", {"comp": False, "ts": True, "chorus": False, "dly": True},
         {"dly": {"time": "1/4", "feedback": 22, "mix": 8}, "verb": {"mix": 16, "decay": 2.6}}, {"lane-b": {"mute": True}}, 0),
        ("E", "Lead", {"comp": False, "ts": True, "chorus": False, "dly": True},
         {"eq": {"g1": -1, "f2": 900, "g2": 2.5}, "dly": {"time": "1/8•", "feedback": 32, "mix": 18},
          "verb": {"mix": 20, "decay": 2.8}}, {"lane-b": {"mute": True}}, 3),
    ]
    return patch("factory-guitar-ambient-djent", "Ambient Djent", "guitar", ["metal", "progressive", "ambient", "djent"],
                 chain, states, service="rec", color="#3d348b",
                 anims={"A": "aurora", "B": "wave", "C": "pulse", "D": "smoke", "E": "sheen",
                        "6": "vu", "7": "rain", "8": "ripple", "9": "heartbeat", "10": "stars"})


# ── 2. GUITARE 2 : Soaring Lead ───────────────────────────────────────────────────────────────────────────────────
def soaring_lead():
    """Le lead : une TS9 devant un EVH 5150 (full rig, une autre voix de 5150 que la guitare 1 : les deux restent
    distinctes), deux delays (croche pointée, noire), et un shimmer qui ouvre le ciel dans le dernier état. Les clairs :
    un Twin Reverb full rig, plus chaud que le JC de la guitare 1 — une nappe de shimmer, ou des échos."""
    ts = S._block("factory-guitar-singing-clean", "ts")
    ts.update(foot=8, params={"input": 0, "output": -2})
    evh = S._block("factory-guitar-brown-lead", "evh")
    twin = dict(S._block("factory-guitar-jazz-clean", "twin"), params={"input": -3, "output": 0})
    chain = {
        "pre": [{"id": "gate", "type": "gate", "params": {"thresh": -52, "attack": 1, "hold": 20, "release": 120, "hyst": -3}},
                {"id": "comp", "type": "comp", "params": {"thresh": -28, "ratio": 3, "makeup": 3, "attack": 30, "release": 220}},
                ts],
        "split": {"mode": "merge", "gain": -3, "branches": [{"id": "lane-a", "blocks": [evh]},
                                                            {"id": "lane-b", "blocks": [twin]}]},
        "post": [{"id": "eq", "type": "eq-para", "params": {"lowcut_on": True, "lowcut": 100, "bass": 0, "f1": 400, "g1": -1.5,
                                                            "f2": 900, "g2": 2, "f3": 6500, "g3": -2.5, "treble": 0}},
                 {"id": "chorus", "type": "chorus-js", "params": {"length": 20, "voices": 3, "rate": 0.3, "wet": -10, "dry": 0}},
                 {"id": "dly", "type": "delay", "foot": 7, "params": {"time": "1/8•", "feedback": 30, "mix": 16}},
                 {"id": "echo", "type": "delay", "params": {"time": "1/4", "feedback": 35, "mix": 12}},
                 {"id": "shim", "type": "reverb-shimmer", "foot": 6, "params": {"mix": 30, "decay": 6, "shimmer": 35, "pitch": 5, "hicut": 5500}},
                 {"id": "verb", "type": "reverb", "params": {"mix": 20, "decay": 2.8, "size": 40, "hicut": 6500}}],
    }
    st = lambda comp, ts_, ch, d, e, sh: {"comp": comp, "ts": ts_, "chorus": ch, "dly": d, "echo": e, "shim": sh}  # noqa: E731
    states = [
        ("A", "Shimmer Pad", st(True, False, True, False, True, True),
         {"gate": {"thresh": -68}, "eq": {"lowcut": 120, "g1": -2, "g2": 0, "g3": -1}, "echo": {"feedback": 45, "mix": 18},
          "shim": {"mix": 40, "decay": 7}, "verb": {"mix": 30, "decay": 3.8, "size": 48}}, {"lane-a": {"mute": True}}, 0),
        ("B", "Clean Echo", st(True, False, True, True, False, False),
         {"gate": {"thresh": -66}, "eq": {"lowcut": 90, "g1": -1, "g2": 0, "g3": -1}, "dly": {"mix": 14, "feedback": 28},
          "verb": {"mix": 22, "decay": 3.0}}, {"lane-a": {"mute": True}}, 0),
        ("C", "Riff Double", st(False, True, False, False, False, False),
         {"gate": {"thresh": -48, "release": 60}, "eq": {"lowcut": 90, "f1": 450, "g1": -3, "f2": 1500, "g2": 1},
          "verb": {"mix": 8, "decay": 1.4, "size": 24}}, {"lane-b": {"mute": True}}, 0),
        ("D", "Soaring Lead", st(False, True, False, True, True, False),
         {"dly": {"mix": 16, "feedback": 30}, "echo": {"mix": 10, "feedback": 30}, "verb": {"mix": 20, "decay": 2.8}},
         {"lane-b": {"mute": True}}, 3),
        ("E", "Halo Lead", st(False, True, False, True, True, True),
         {"shim": {"mix": 18, "decay": 5, "shimmer": 25}, "verb": {"mix": 24, "decay": 3.4}}, {"lane-b": {"mute": True}}, 2),
    ]
    return patch("factory-guitar-soaring-lead", "Soaring Lead", "guitar", ["metal", "progressive", "lead", "ambient"],
                 chain, states, service="compo", color="#c9a227",
                 anims={"A": "aurora", "B": "ripple", "C": "pulse", "D": "sheen", "E": "vortex",
                        "6": "stars", "7": "rain", "8": "fire", "9": "snow", "10": "heartbeat"})


# ── 3. BASSE : Bi-Amp Grit ────────────────────────────────────────────────────────────────────────────────────────
def biamp_grit():
    """Bi-ampli : un SVT très clair (Ultra Lo, MD421) tient le grave, une Darkglass B7K (full rig : pédale, ampli, baffle,
    micro) donne le grain. Ce sont deux captures COMPLÈTES : aucun baffle derrière. Le compresseur est avant le split,
    pour que les deux amplis voient la même dynamique. SVT à −4 : la B7K est très basse et sa normalisation plafonne
    (compile_rig, +20 dB), les deux branches arrivent ainsi au même niveau."""
    svt = dict(S._block("factory-bass-vintage-round", "svt"), model="379989", params={"input": 0, "output": -4})
    b7k = {"id": "b7k", "type": "amp", "label": "Darkglass B7K Ultra", "ref": "27698", "model": "413366",
           "params": {"input": 0, "output": 0}}
    chain = {
        "pre": [{"id": "gate", "type": "gate", "params": {"thresh": -50, "attack": 1, "hold": 20, "release": 80}},
                {"id": "comp", "type": "comp", "params": {"thresh": -24, "ratio": 4, "makeup": 3, "attack": 10, "release": 120}}],
        "split": {"mode": "merge", "gain": -3, "branches": [{"id": "lane-a", "blocks": [svt]}, {"id": "lane-b", "blocks": [b7k]}]},
        "post": [{"id": "eq", "type": "eq-para", "params": {"lowcut_on": True, "lowcut": 35, "bass": 0, "f1": 250, "g1": -2,
                                                            "f2": 800, "g2": 1, "f3": 2500, "g3": 2, "treble": -1}}],
    }
    states = [
        ("A", "Sub Clean", {}, {}, {"lane-b": {"mute": True}}, -1),
        ("B", "Grit Blend", {}, {}, {}, 0),
        ("C", "Tight Grit", {}, {"gate": {"thresh": -44}, "comp": {"ratio": 8, "attack": 5}}, {}, 1),
        ("D", "Growl", {}, {"svt": {"output": -8}}, {}, 1),
    ]
    return patch("factory-bass-biamp-grit", "Bi-Amp Grit", "bass", ["metal", "progressive", "drive"],
                 chain, states, service="rec", color="#9d0208",
                 anims={"A": "smoke", "B": "fire", "C": "glitch", "D": "lightning", "9": "snow", "10": "heartbeat"})


# ── 4. PIANO : Cathedral Piano ────────────────────────────────────────────────────────────────────────────────────
def cathedral_piano():
    """Le piano devant au couplet, qui FLEURIT en nappe par le shimmer (une lane clavier n'empile pas deux instruments :
    l'état shimmer EST la nappe), et qui se retire du grave quand les guitares lourdes entrent."""
    chain = {"chain": [
        {"id": "piano", "type": "piano", "params": {"sfz": SALAMANDER, "volume": 0}},
        {"id": "comp", "type": "comp", "params": {"thresh": -22, "ratio": 2.5, "makeup": 2, "attack": 15, "release": 200}},
        {"id": "eq", "type": "eq", "params": {"lowcut": 50, "midgain": -1.5, "midfreq": 400, "highs": 0}},
        {"id": "dly", "type": "delay", "foot": 7, "params": {"time": "1/4", "feedback": 30, "mix": 14}},
        {"id": "shim", "type": "reverb-shimmer", "foot": 6, "params": {"mix": 30, "decay": 6, "shimmer": 40, "pitch": 5, "hicut": 6000}},
        {"id": "verb", "type": "reverb", "params": {"mix": 26, "decay": 3.4, "size": 44, "hicut": 7000}}]}
    states = [
        ("A", "Hall Piano", {"dly": False, "shim": False}, {}, {}, 0),
        ("B", "Halo", {"dly": True, "shim": True}, {"shim": {"mix": 34, "decay": 7, "shimmer": 45}, "verb": {"mix": 30, "decay": 3.8}}, {}, 0),
        ("C", "Under", {"dly": False, "shim": False},
         {"eq": {"lowcut": 160, "midgain": -3, "midfreq": 350, "highs": 2}, "comp": {"thresh": -26, "ratio": 4},
          "verb": {"mix": 16, "decay": 2.2, "size": 30}}, {}, 0),
        ("D", "Bloom", {"dly": True, "shim": True},
         {"eq": {"lowcut": 140, "midgain": -2, "highs": 1}, "shim": {"mix": 26, "decay": 6, "shimmer": 40}, "dly": {"mix": 10},
          "verb": {"mix": 22, "decay": 3.0}}, {}, 0),
    ]
    return patch("factory-keys-cathedral-piano", "Cathedral Piano", "keys", ["ambient", "piano", "metal"],
                 chain, states, service="rec", color="#e0e1dd", midi=True,
                 anims={"A": "wave", "B": "stars", "C": "smoke", "D": "aurora", "6": "snow", "7": "ripple", "9": "heartbeat", "10": "pulse"})


# ── 5. VOIX : Halo Vocal ──────────────────────────────────────────────────────────────────────────────────────────
def halo_vocal():
    """Falsetto doublé dans l'espace, couplet serré, un grain pour les passages lourds, un refrain-hymne. Une plate
    plutôt qu'une salle : son pré-délai garde les mots intelligibles ; un de-esser, parce qu'une grande réverbe grossit
    les sifflantes."""
    scream = S._block("factory-voice-metal", "scream")
    scream["foot"] = 6
    chain = {"chain": [
        {"id": "gate", "type": "gate", "params": {"thresh": -55, "attack": 2, "hold": 40, "release": 200}},
        {"id": "ess", "type": "deesser", "params": {"thresh": -28, "freq": 7000, "range": 10}},
        scream,
        {"id": "comp", "type": "comp", "params": {"thresh": -22, "ratio": 3.5, "makeup": 4, "attack": 8, "release": 140}},
        {"id": "eq", "type": "eq-para", "params": {"lowcut_on": True, "lowcut": 110, "bass": 0, "f1": 280, "g1": -2, "f2": 1200, "g2": 0,
                                                   "f3": 5000, "g3": 1.5, "treble": 2}},
        {"id": "double", "type": "chorus-js", "foot": 8, "params": {"length": 22, "voices": 2, "rate": 0.3, "wet": -14, "dry": 0}},
        {"id": "dly", "type": "delay", "foot": 7, "params": {"time": "1/4", "feedback": 32, "mix": 16}},
        {"id": "verb", "type": "reverb-plate", "params": {"mix": 26, "decay": 2.6, "predelay": 40, "hicut": 7000}}]}
    states = [
        ("A", "Falsetto Halo", {"scream": False, "double": True, "dly": True},
         {"dly": {"feedback": 38, "mix": 18}, "verb": {"mix": 32, "decay": 3.0, "predelay": 40}}, {}, 0),
        ("B", "Close Verse", {"scream": False, "double": False, "dly": False},
         {"verb": {"mix": 16, "decay": 1.8, "predelay": 30}}, {}, 0),
        ("C", "Grit Belt", {"scream": True, "double": False, "dly": False},
         {"gate": {"thresh": -45}, "comp": {"ratio": 5}, "verb": {"mix": 12, "decay": 1.2, "predelay": 20}}, {}, 1),
        ("D", "Anthem", {"scream": False, "double": True, "dly": True},
         {"double": {"wet": -10}, "dly": {"time": "1/8•", "feedback": 25, "mix": 12}, "verb": {"mix": 24, "decay": 2.4, "predelay": 40}}, {}, 1),
    ]
    return patch("factory-voice-halo", "Halo Vocal", "voice", ["metal", "ambient", "falsetto"],
                 chain, states, service="compo", color="#9d4edd",
                 anims={"A": "aurora", "B": "wave", "C": "fire", "D": "sheen", "6": "lightning", "7": "rain", "8": "ripple",
                        "9": "vu", "10": "stars"})


# ── 6. LE PRESET « Ambient Metal » ────────────────────────────────────────────────────────────────────────────────
LANES = [  # id, nom, rôle, patch, MIDI, n° d'entrée de son rôle
    ("guitar-1", "Guitar 1", "guitar", "factory-guitar-ambient-djent", False, 1),
    ("guitar-2", "Guitar 2", "guitar", "factory-guitar-soaring-lead", False, 2),
    ("bass-1", "Bass", "bass", "factory-bass-biamp-grit", False, 1),
    ("keys-1", "Piano", "keys", "factory-keys-cathedral-piano", True, None),
    ("voice-1", "Voice", "voice", "factory-voice-halo", False, 1),
]
# deux scènes claires, trois saturées dont le solo : pour chaque lane, le NOM de l'état joué et son niveau (dB)
SCENES = [
    ("A", "Halo Clean", {"guitar-1": ("Halo Clean", -2), "guitar-2": ("Shimmer Pad", -5), "bass-1": ("Sub Clean", -3),
                         "keys-1": ("Halo", 0), "voice-1": ("Falsetto Halo", 0)}),
    ("B", "Glass Verse", {"guitar-1": ("Glass Arp", -1), "guitar-2": ("Clean Echo", -6), "bass-1": ("Sub Clean", -1),
                          "keys-1": ("Hall Piano", -1), "voice-1": ("Close Verse", 1)}),
    ("C", "Low Riff", {"guitar-1": ("Low Riff", 0), "guitar-2": ("Riff Double", -2), "bass-1": ("Tight Grit", 0),
                       "keys-1": ("Under", -6), "voice-1": ("Grit Belt", 1)}),
    ("D", "Wall Chorus", {"guitar-1": ("Wall", -1), "guitar-2": ("Riff Double", -3), "bass-1": ("Grit Blend", -1),
                          "keys-1": ("Bloom", -3), "voice-1": ("Anthem", 2)}),
    # le solo : la guitare 2 à +3, tout le reste dessous ; la voix à −6 et pas coupée (les ad-libs)
    ("E", "Soaring Solo", {"guitar-1": ("Wall", -4), "guitar-2": ("Soaring Lead", 3), "bass-1": ("Grit Blend", -2),
                           "keys-1": ("Bloom", -6), "voice-1": ("Close Verse", -6)}),
]
# le pied du preset, réécrit APRÈS les dépôts (les ids sont ceux d'après patches._dedupe) ; SW9 = l'Arrangement
FEET = {6: ["shim", "shim-2"],          # Shimmer : la guitare 2 et le piano
        7: ["dly", "dly-4"],            # Echo : la guitare 1 et la voix
        8: ["scream"]}                  # Grit : la voix


def ambient_metal():
    p = {"id": "factory-ambient-metal", "name": "Ambient Metal", "lanes_v": 2, "lanes": [], "scenes": [], "bpm": BPM,
         "style": "metal", "styles": ["metal"], "factory": True}
    for lid, name, role, _pid, midi, nth in LANES:
        p["lanes"].append({"id": lid, "key": lid, "role": role, "name": name, "in_sel": "usb" if midi else "", "out_sel": "1-2",
                           "chain": {"pre": [], "split": None, "post": []}, "midi": midi,
                           "in_role": None if midi else role, "in_nth": nth, "states": []})
    p["scenes"] = [{"id": sid, "name": nm} for sid, nm, _ in SCENES]
    for lid, _n, _r, pid, _m, _nth in LANES:
        p, realm, _lost, _added, _skip = patches.apply_to(p, pid, lane=lid)
        assert realm == lid, (pid, realm)
    for L, (lid, name, *_rest) in zip(p["lanes"], LANES):
        L["name"] = name
    # le pied : on retire celui des patches, on pose celui du preset — chaque id vérifié
    blocks = {b["id"]: b for L in p["lanes"] for b in S._lane_blocks(L) + ((L.get("chain") or {}).get("chain") or [])}
    for b in blocks.values():
        b.pop("foot", None)
    for sw, ids in FEET.items():
        for bid in ids:
            assert bid in blocks, f"SW{sw} : bloc {bid} absent du preset ({sorted(blocks)})"
            blocks[bid]["foot"] = sw
    by_id = {L["id"]: L for L in p["lanes"]}
    scenes = []
    for sid, nm, want in SCENES:
        sc = {"id": sid, "name": nm, "blocks": {}, "params": {}, "branches": {}, "lanes": {}}
        for lid, (state_name, lvl) in want.items():
            L = by_id[lid]
            st = next((s for s in L.get("states") or [] if s.get("name") == state_name), None)
            assert st, f"{lid} : pas d'état « {state_name} » ({[s.get('name') for s in L.get('states') or []]})"
            ids, types, brs = S._lane_sets(L)
            ids |= {b.get("id") for b in ((L.get("chain") or {}).get("chain") or [])}
            sc["blocks"].update({k: v for k, v in (st.get("blocks") or {}).items() if k in ids or k in types})
            sc["params"].update({k: v for k, v in (st.get("params") or {}).items() if k in ids})
            sc["branches"].update({k: v for k, v in (st.get("branches") or {}).items() if k in brs})
            sc["lanes"][lid] = {"state": st["id"], **({"level": lvl} if lvl else {})}
        scenes.append(sc)
    p["scenes"] = scenes
    rock = S._load("presets/factory-rock-classics.json")["config"]
    p["config"] = {
        # les sept grooves metal, dans l'ordre que l'ARRANGEMENT de « Golem Rising » désigne par leur rang (GROOVES de
        # tools/make-factory-song.py) — le break et le coup final y compris : une partie d'arrangement ne joue qu'un motif
        "gen": {"out": "1-2", "blocks": [{"type": "drums", "id": "drums", "foot": 10, "params": {
            "patterns": [G + g + ".mid" for g in GROOVES], "fills": [], "kit": KIT}}]},
        "rec": {"click_out": "1-2", "blocks": [
            {"id": "rec-global", "type": "rec", "params": rock["rec"]["blocks"][0]["params"]},
            {"id": "click-global", "type": "click", "bypass": True, "params": {"level": 0.0, "beats": 4}},
            {"id": "compo-global", "type": "compo", "params": {"keep_s": 30, "transcribe": True}}]},
        # SW9 = l'ARRANGEMENT : un appui lance « Golem Rising » — scènes, grooves et pédales suivent seuls
        "arr": {"blocks": [{"id": "arrangement", "type": "arrangement", "foot": 9, "params": {"advance": "bars", "sections": []}}]},
    }
    violet = "#7b2cbf"
    p["colors"] = {k: violet for k in ("A", "B", "C", "D", "E", "6", "7", "8", "9", "10")}
    p["anims"] = {"A": "aurora", "B": "wave", "C": "pulse", "D": "vortex", "E": "sheen",
                  "6": "stars", "7": "ripple", "8": "fire", "9": "glitch", "10": "heartbeat"}
    S._dump("presets/factory-ambient-metal.json", p)
    return p


def banks(docs):
    """Chaque patch dans la banque de son instrument (une fois)."""
    for d in docs:
        rel = f"setlists/factory-{d['role']}.json"
        b = S._load(rel)
        if not any(ln.get("patch") == d["id"] for ln in b["lines"]):
            b["lines"].append({"id": f"r:factory-{d['role']}:{d['id'].split('-', 2)[-1]}", "rev": 1, "title": d["name"], "patch": d["id"]})
        b["presets"] = ["patch:" + ln["patch"] for ln in b["lines"]]
        S._dump(rel, b)


if __name__ == "__main__":
    docs = [ambient_djent(), soaring_lead(), biamp_grit(), cathedral_piano(), halo_vocal()]
    banks(docs)
    p = ambient_metal()
    print(f"Ambient Metal : {len(p['lanes'])} lanes, {len(p['scenes'])} scènes · patches : " + ", ".join(d["name"] for d in docs))
    for d in docs:
        if d.get("unresolved"):
            print(f"  ⚠ {d['name']} : {len(d['unresolved'])} référence(s) non résolue(s) sur cette machine")
