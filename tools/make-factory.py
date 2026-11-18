#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'USINE DE GOLEM, REFAITE (2026-11-16, demande du mainteneur : « on repart sur du neuf », sur NOS blocs golem-fx).

Ce script écrit TOUT le contenu sonore d'usine dans library/factory/ : les patches (une banque par instrument), les
presets (un groupe complet par style), les banques (setlists `sounds`), la setlist d'usine et la chanson « Golem Rising ».
Les anciens patches, presets et setlists d'usine sont effacés d'abord (les grooves, standards, banque DX7 et kits restent).

Les règles (docs/factory.md §1) :
  - AUCUN nom d'artiste, de groupe ou de chanson dans ce qui est livré : les sons sont INSPIRÉS de styles (un blues
    texan, un metal groove, un nu metal 8 cordes…), leurs noms sont des noms de jeu. Les inspirations restent ici, en
    commentaire, jamais dans un fichier livré ;
  - les captures NAM sont des refs TONE3000 (+ modèle) du catalogue des tons, choisies parmi celles qui sont sur le rack ;
    une capture « full rig » ne prend pas de baffle derrière ; un modèle dont le nom cite un artiste ou un titre n'est
    pas pris ;
  - guitare/basse : un gate d'abord, une seule source de saturation ouverte par état, une seule branche d'ampli ouverte
    par état (jamais deux amplis sommés), les solos à +2/+3 dB ; claviers : chaîne linéaire ; voix : Grit / Morph sont
    les seules saturations ;
  - chaque patch a 4–5 scènes contrastées ; chaque preset est un groupe complet fait de patches de banque (au moins une
    lane claviers), avec ses blocs spéciaux (boîte à rythmes, Standard, looper, arrangement, REC) ;
  - une couleur de thème et une animation par case occupée.

    .venv/bin/python tools/make-factory.py
Puis : python tools/gen-factory-history.py (docs/factory.md §2).
"""
import copy
import glob
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FACTORY = os.path.join(ROOT, "library", "factory")

from bridge import option_renames, patches  # noqa: E402

G = "library/grooves/golem-"
SAL = "library/sfz/SalamanderGrandPiano-SFZ+FLAC-V3+20200602/SalamanderGrandPiano-V3+20200602.sfz"
DX7 = "library/dx7/synprezfm-02.syx"
ANIMS = ["aurora", "wave", "pulse", "smoke", "sheen", "stars", "rain", "ripple", "heartbeat", "fire", "vortex", "glitch",
         "ember", "vu", "snow", "lightning", "scanner", "strobe", "monster"]


# ── outils ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _dump(rel, doc):
    with open(os.path.join(FACTORY, rel), "w", encoding="utf-8") as f:
        option_renames.apply(doc)
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _load(rel):
    with open(os.path.join(FACTORY, rel), encoding="utf-8") as f:
        return json.load(f)


def B(bid, btype, foot=None, **params):
    """Un bloc golem (golem-fx ou service) : ses réglages sont ceux du catalogue v50."""
    b = {"id": bid, "type": btype, "params": params}
    if foot:
        b["foot"] = foot
    return b


def CAP(bid, btype, ref, model, label, foot=None, **params):
    """Une capture TONE3000 (ampli, baffle, pédale NAM) : ref + modèle, le nom de l'appareil — jamais un nom d'artiste."""
    b = {"id": bid, "type": btype, "label": label, "ref": str(ref), "model": str(model), "params": params}
    if foot:
        b["foot"] = foot
    return b


def lane_blocks(chain):
    ch = chain or {}
    return (ch.get("pre") or []) + [b for br in ((ch.get("split") or {}).get("branches") or []) for b in br.get("blocks") or []] \
        + (ch.get("post") or []) + (ch.get("chain") or [])


def _lane_sets(L):
    ch = L.get("chain") or {}
    blocks = lane_blocks(ch)
    brs = {br.get("id") for br in ((ch.get("split") or {}).get("branches") or []) if br.get("id")}
    return {b.get("id") for b in blocks if b.get("id")}, {b.get("type") for b in blocks if b.get("type")}, brs


def drums_service(grooves, kit="drums-black-pearl"):
    return {"type": "drums", "id": "drums", "foot": 10, "params": {"patterns": [G + g + ".mid" for g in grooves], "fills": [], "kit": kit}}


# LE STANDARD DES PATCHES JAZZ ET BLUES (2026-11-16, le mainteneur) : sur SW10, à la place de la boîte à rythmes — une grille
# d'usine et le combo qui l'accompagne, sans la partie de l'instrument du patch (on ne s'accompagne pas soi-même).
# pid -> (grille, kit, voicing). Le feel reste « swing » : le blues lent à 66 se joue en triolets, comme un 12/8.
PATCH_STD = {
    "factory-guitar-jazz-box": ("rooftop-prowl", "blonde-bop", "rootless"),
    "factory-guitar-texas-shuffle": ("rented-room-blues", "black-pearl", "full"),
    "factory-guitar-wailing-blues": ("rented-room-blues", "black-pearl", "full"),
    "factory-bass-upright-jazz": ("rooftop-prowl", "blonde-bop", "rootless"),
    "factory-bass-blues-round": ("rented-room-blues", "black-pearl", "full"),
    "factory-keys-jazz-piano": ("rooftop-prowl", "blonde-bop", "rootless"),
    "factory-keys-blues-organ": ("rented-room-blues", "black-pearl", "full"),
    "factory-voice-crooner": ("rooftop-prowl", "blonde-bop", "rootless"),
    "factory-voice-blues-shout": ("rented-room-blues", "black-pearl", "full"),
    "factory-drums-jazz-brushes": ("rooftop-prowl", "blonde-bop", "rootless"),
    "factory-drums-vintage-rock": ("rented-room-blues", "red-zeppelin", "full"),
}


def _patch_gen(pid, role, groove, kit, gen):
    """Le bloc de SW10 d'un patch : celui qu'on lui donne, sinon son Standard, sinon la boîte à rythmes."""
    if gen is not None:
        return gen
    if pid in PATCH_STD:
        chart, skit, voicing = PATCH_STD[pid]
        parts = {"keys": True, "bass": True, "drums": True}
        own = {"bass": "bass", "keys": "keys", "drums": "drums"}.get(role)
        if own:
            parts[own] = False
        return [std(chart, skit, "swing", voicing=voicing, **parts)]
    return [] if role == "drums" or groove is None else [drums_service([groove], kit)]


def _anims(cells, seed):
    """Une animation par case, tirée de la palette d'usine, stable d'une génération à l'autre."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    # « monster » est l'animation d'une case VIERGE sur /live (page-live.js, EMPTY_ANIM) : une case occupée qui la
    # porte se lit comme vide. Le tirage garde ses 19 rangs (les autres cases ne bougent pas) ; celui qui tombe sur
    # le monstre en prend une autre, tirée d'un autre morceau du même hachage.
    rest = [a for a in ANIMS if a != "monster"]
    out = {}
    for i, c in enumerate(cells):
        a = ANIMS[(h + i * 7) % len(ANIMS)]
        out[c] = rest[((h >> 16) + i * 5) % len(rest)] if a == "monster" else a
    return out


PATCHES = {}


def _explicit(pid, chain, states):
    # CHAQUE ÉTAT DIT TOUT (2026-11-16) : un bloc qu'une scène ne cite pas reste ALLUMÉ au rig (scene_bake) — écrit
    # « Crushed : crush on » sans l'éteindre ailleurs, le bitcrusher jouait dans les quatre scènes et « Crushed » ne
    # changeait rien. Un bloc qu'un état bascule est donc écrit dans TOUS : éteint s'il a un switch (un effet qu'on
    # enclenche), allumé sinon (une room qu'une seule scène coupe). Et deux scènes au même contenu sont refusées.
    feet_of = {b["id"]: b.get("foot") for b in lane_blocks(chain)}
    toggled = sorted(set().union(*[set(s[2]) for s in states]))
    states = [(sid, nm, {**{b: not feet_of.get(b) for b in toggled}, **bl}, pa, br, lvl) for sid, nm, bl, pa, br, lvl in states]
    seen = {}
    for sid, nm, bl, pa, br, _lvl in states:
        key = json.dumps([bl, pa, br], sort_keys=True)
        assert key not in seen, f"{pid} : la scène « {nm} » ne change rien par rapport à « {seen[key]} » (même contenu, au niveau près)"
        seen[key] = nm
    return states


# ── LES SONS VALIDÉS À L'OREILLE (2026-11-16) ─────────────────────────────────────────────────────────────────────
# Un patch d'usine retouché dans le Designer puis validé au rig a sa chaîne, ses états et ses scènes dans
# tools/factory-validated/<id>.json (écrit par `--validate`, docs/factory.md §5.1) : ce fichier REMPLACE alors ce que la
# fonction du patch décrit plus bas, qui ne reste que comme point de départ lisible. Le générateur garde la main sur
# l'identité, le thème, le bloc de SW10 quand le fichier n'en dit rien, les dépendances — et les presets reprennent la
# lane validée, par les NOMS d'états : un état renommé fait échouer la génération, on le voit tout de suite.
VALIDATED = os.path.join(ROOT, "tools", "factory-validated")
VALID_KEYS = ("chain", "states", "scenes", "bpm", "gen", "colors", "anims")


def _validated(pid):
    f = os.path.join(VALIDATED, pid + ".json")
    return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else None


def validate(ids):
    """`--validate [id…]` : les patches d'usine retouchés sur ce rack (tous, ou ceux nommés) deviennent la source."""
    from bridge import factory
    mine = [e["id"] for e in factory.edited() if e["kind"] == "patches" and (not ids or e["id"] in ids)]
    os.makedirs(VALIDATED, exist_ok=True)
    for pid in mine:
        d = json.load(open(os.path.join(ROOT, "library", "patches", pid + ".json"), encoding="utf-8"))
        L = d["lanes"][0]
        out = {"chain": L["chain"], "states": L.get("states") or [], "scenes": d["scenes"], "bpm": d.get("bpm"),
               "gen": ((d.get("config") or {}).get("gen") or {}).get("blocks") or [],
               "colors": d.get("colors") or {}, "anims": d.get("anims") or {}}
        with open(os.path.join(VALIDATED, pid + ".json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        print("validé :", pid)
    return mine


def patch(pid, name, role, tags, chain, states, *, color, groove, bpm=120, service="rec", midi=False, kit="drums-black-pearl", gen=None):
    """Un patch d'usine : UNE lane, ses états, une scène par état, de quoi jouer seul (la boîte à rythmes sur SW10, le REC
    ou le Riff sur SW9), le thème sur chaque case. `states` : (id, nom, blocs on/off, réglages, branches, niveau dB)."""
    lane_id = f"{role}-1"
    val = _validated(pid)
    if val:
        return _emit_patch(pid, name, role, tags, val["chain"], val["states"], val["scenes"], color=color,
                           bpm=val.get("bpm") or bpm, service=service, midi=midi,
                           gen=val["gen"] if "gen" in val else _patch_gen(pid, role, groove, kit, gen), val=val)
    # SANS SPLIT, TOUT EST DANS `pre` (2026-11-16) : le Designer ne dessine `post` que derrière un split — une chaîne
    # écrite {pre, split: None, post} s'affichait coupée après `pre` (Jazz Box : Gate, Comp, et pas d'ampli à l'écran,
    # alors que le moteur le jouait). Les fonctions g_*/b_*/… gardent leur écriture ; la forme livrée est celle-ci.
    if "chain" not in chain and not chain.get("split"):
        chain = {"pre": list(chain.get("pre") or []) + list(chain.get("post") or []), "split": None, "post": []}
    known_ids, _types, known_brs = _lane_sets({"chain": chain})
    for sid, nm, bl, pa, br, _lvl in states:                 # une faute de frappe ne passe pas en silence
        bad = (set(bl) | set(pa)) - known_ids
        assert not bad, f"{pid} état {nm} : blocs inconnus {sorted(bad)}"
        assert not (set(br) - known_brs), f"{pid} état {nm} : branches inconnues {sorted(set(br) - known_brs)}"
    states = _explicit(pid, chain, states)
    lane_states = [{"id": f"st-{lane_id}-{sid}", "name": nm, "blocks": bl, "params": pa, "branches": br}
                   for sid, nm, bl, pa, br, _lvl in states]
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
    return _emit_patch(pid, name, role, tags, chain, lane_states, scenes, color=color, bpm=bpm, service=service, midi=midi,
                       gen=_patch_gen(pid, role, groove, kit, gen))


def _emit_patch(pid, name, role, tags, chain, lane_states, scenes, *, color, bpm, service, midi, gen, val=None):
    """Écrit le patch : la forme livrée, la copie locale, les dépendances. `val` : le son validé à l'oreille, s'il y en
    a un — ses couleurs et animations de case sont gardées là où il en a choisi."""
    lane_id = f"{role}-1"
    # UN split, DEUX branches au plus (règle du mainteneur, 2026-11-16) : le Designer n'en dessine que deux — une troisième
    # sonnait sans pouvoir se voir ni se régler (Bass Lab, Pop Chorus). Vaut aussi pour un son validé à l'oreille.
    assert len((chain.get("split") or {}).get("branches") or []) <= 2, f"{pid} : un split a deux branches au plus"
    lane = {"id": lane_id, "role": role, "name": name, "midi": midi, "chain": chain, "states": lane_states}
    feet = sorted({b["foot"] for b in lane_blocks(chain) if b.get("foot")} | {9} | {b["foot"] for b in gen if b.get("foot")})
    cells = [s["id"] for s in scenes] + [str(f) for f in feet]
    rec = {"id": "rec-global", "type": "rec", "foot": 9} if service == "rec" else {"id": "compo-global", "type": "compo", "foot": 9}
    doc = {"id": pid, "name": name, "role": role, "tags": tags, "kind": "patch", "patch_v": 2, "lanes_v": 2,
           "lanes": [lane], "scenes": scenes, "config": {"gen": {"out": "1-2", "blocks": gen}, "rec": {"blocks": [rec]}},
           "bpm": bpm, "chain": copy.deepcopy(chain), "needs": patches.needs_of(chain), "origin": "factory", "factory": True,
           "colors": {k: color for k in cells}, "anims": _anims(cells, pid)}
    if val:
        doc["colors"].update({k: v for k, v in (val.get("colors") or {}).items() if k in cells})
        doc["anims"].update({k: v for k, v in (val.get("anims") or {}).items() if k in cells})
    local = os.path.join(ROOT, "library", "patches", pid + ".json")
    with open(local, "w", encoding="utf-8") as f:
        option_renames.apply(doc)
        json.dump(doc, f, indent=1, ensure_ascii=False)
    from bridge import preset_export
    out, _blobs = preset_export.build_export(patches.PATCH_PREFIX + pid)
    if out is not None:
        doc["deps"], doc["deps_sig"] = out.get("deps") or [], patches._v2_sig(doc)
        if out.get("unresolved"):
            doc["unresolved"] = out["unresolved"]
    with open(local, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    _dump(f"patches/{pid}.json", doc)
    PATCHES[pid] = doc
    return doc


def S(sid, name, blocks=None, params=None, branches=None, level=0):
    return (sid, name, blocks or {}, params or {}, branches or {}, level)


A_OFF, B_OFF = {"lane-a": {"mute": True}}, {"lane-b": {"mute": True}}      # deux branches au plus : pas de C


def two(a_blocks, b_blocks, gain=-3):
    return {"mode": "merge", "gain": gain, "branches": [{"id": "lane-a", "blocks": a_blocks}, {"id": "lane-b", "blocks": b_blocks}]}


# ── les captures (refs TONE3000 du catalogue des tons, toutes présentes sur le rack le 2026-11-16) ──────────────────
def twin():        return CAP("twin", "amp", 43620, 382264, "Fender Twin Reverb", input=-3, output=0)
def jc120():       return CAP("jc", "amp", 6530, 397610, "Roland JC-120", input=-3, output=0)
def super_rv():    return CAP("super", "amp", 19, 379723, "Fender Super Reverb", input=0, output=0)
def dumble():      return CAP("ods", "amp-nam", 94, 420125, "Dumble Overdrive Special", input=0, output=0)
def deluxe_cab():  return CAP("cab12", "cab", 27465, 220918, "Fender Deluxe Reverb 1x12", level=0)
def ts808(foot=None, out=-2): return CAP("ts", "pedal-nam", 70280, 577277, "Ibanez TS808 Tube Screamer", foot=foot, input=0, output=out)
def ts9(foot=None, out=-3):   return CAP("ts", "pedal-nam", 36827, 381617, "Ibanez TS9 Tube Screamer", foot=foot, input=0, output=out)
def sd1(foot=None):           return CAP("sd1", "pedal-nam", 35426, 381318, "Boss SD-1 Super Overdrive", foot=foot, input=0, output=-2)
def jcm800():      return CAP("jcm", "amp-nam", 1071, 418179, "Marshall JCM800 2203", input=0, output=0)
def greenback(bid="gb"): return CAP(bid, "cab", 45022, 239238, "Marshall 4x12 Greenback", level=0)
def v30(bid="v30", model=239394): return CAP(bid, "cab", 45023, model, "Mesa 4x12 Vintage 30", level=0)
def pro_reverb():  return CAP("pro", "amp", 55360, 383837, "Fender Pro Reverb", input=-2, output=0)
def p6505():       return CAP("p6505", "amp-nam", 29230, 418311, "Peavey 6505+", input=0, output=0)
def bogner():      return CAP("bogner", "amp-nam", 6510, 398704, "Bogner Ecstasy 101B", input=0, output=0)
def deluxe65():    return CAP("drri", "amp", 51649, 383455, "Fender Deluxe Reverb 65", input=-2, output=0)
def warhead():     return CAP("x2", "amp", 31332, 382070, "Randall Warhead X2", input=0, output=0)
def twin_rig():    return CAP("twin", "amp", 43620, 382265, "Fender Twin Reverb", input=-3, output=0)
def ds1(foot=None, model=419260): return CAP("ds1", "pedal-nam", 2508, model, "Boss DS-1 Distortion", foot=foot, input=0, output=-3)
def klon(foot=None):          return CAP("klon", "pedal-nam", 2599, 419209, "Klon Centaur", foot=foot, input=0, output=-2)
def drii(bid="drii", model=418153): return CAP(bid, "amp", 6237, model, "Fender Deluxe Reverb II", input=-2, output=0)
def bigmuff(foot=None):       return CAP("muff", "pedal-nam", 37818, 413514, "EHX Op-Amp Big Muff", foot=foot, input=0, output=-4)
def muff_bright(foot=None):   return CAP("muff", "pedal-nam", 37818, 413521, "EHX Op-Amp Big Muff", foot=foot, input=0, output=-2)
def jcm800_mod():  return CAP("jcm", "amp", 44209, 567082, "Marshall JCM800 2203 Modified", input=0, output=0)
def twin_bright(): return CAP("twin", "amp-nam", 246, 418200, "Fender Twin Reverb", input=-2, output=0)
def creamback():   return CAP("cab12", "cab", 5004, 67597, "Palmer 2x12 Creamback", level=0)
def warhead_rhythm(): return CAP("x2", "amp", 31332, 380970, "Randall Warhead X2", input=0, output=0)
def jc120b():      return CAP("jc", "amp", 10912, 379740, "Roland JC-120B", input=-2, output=0)
def jubilee(model=106490, bid="jub"): return CAP(bid, "amp-nam", 27435, model, "Marshall Silver Jubilee", input=0, output=0)
def dualrec():     return CAP("rect", "amp-nam", 70207, 576906, "Mesa Dual Rectifier", input=0, output=0)
# basse
def b15():         return CAP("b15", "amp", 26828, 379842, "Ampeg B-15", input=0, output=0)
def svt_rig(model=379988, bid="svt"): return CAP(bid, "amp", 28202, model, "Ampeg SVT 6x10", input=0, output=-2)
def svt_head(model=382790, bid="svtcl"): return CAP(bid, "amp-nam", 45809, model, "Ampeg SVT-CL", input=0, output=0)
def gk_cab(model=72421, bid="gkcab"): return CAP(bid, "cab", 64815, model, "Gallien-Krueger 4x10", level=0)
def b7k():         return CAP("b7k", "amp", 27698, 413366, "Darkglass B7K Ultra", input=0, output=0)
def alpha():       return CAP("alpha", "amp", 27697, 418278, "Darkglass Alpha Omega", input=0, output=0)
def gk_head():     return CAP("rb800", "amp-nam", 2694, 419204, "Gallien-Krueger RB800", input=0, output=0)
def aou():         return CAP("aou", "amp", 2420, 425030, "Darkglass Alpha Omega Ultra", input=0, output=0)
def xultra():      return CAP("xultra", "amp-nam", 71220, 588114, "Darkglass X Ultra", input=0, output=0)


def gate(t=-55, **kw):  return B("gate", "gate", thresh=t, release=kw.pop("release", 120), **kw)
def met(t=-48, **kw):   return B("met", "met", thresh=t, **kw)
def comp(ch="Clean", **kw): return B("comp", "comp", character=ch, **{"thresh": -22, "ratio": 3, "makeup": 3, "attack": 15, **kw})
def eq(**kw):           return B("eq", "eq", **{"lowcut": 80, "midgain": 0, "midfreq": 800, "highs": 0, **kw})
def verb(algo="Hall", bid="verb", foot=None, **kw): return B(bid, "reverb", foot=foot, **{"algo": algo, "mix": 20, "decay": 1.8, "size": 30, "hicut": 7000, **kw})
def plate(bid="plate", foot=None, **kw): return B(bid, "reverb-plate", foot=foot, **{"mix": 20, "decay": 1.4, "size": 24, "hicut": 8000, **kw})
def room(bid="room", foot=None, **kw):   return B(bid, "reverb-room", foot=foot, **{"mix": 16, "decay": 0.8, "size": 14, "hicut": 7000, **kw})
def dly(bid="dly", foot=None, **kw):     return B(bid, "delay", foot=foot, **{"model": "Digital", "time": "1/8•", "feedback": 30, "mix": 16, **kw})
def chorus(bid="chorus", foot=None, **kw): return B(bid, "chorus", foot=foot, **{"profile": "Guitar Clean", "mode": "Classic", "rate": 0.6, "depth": 4, "mix": 0.4, **kw})
def shimmer(bid="shim", foot=None, **kw): return B(bid, "reverb-shimmer", foot=foot, **{"mix": 30, "decay": 5, "shimmer": 40, "hicut": 6000, **kw})


# ══ GUITARE ══════════════════════════════════════════════════════════════════════════════════════════════════════
def g_jazz_box():
    # jazz : un Twin très propre, un compresseur opto, une plate courte ; le solo avance les médiums
    chain = {"pre": [gate(-62), comp("Opto", thresh=-24, ratio=2.5, makeup=2, attack=25)],
             "split": None,
             "post": [twin(), eq(lowcut=70, midgain=0, midfreq=700, highs=-4),
                      chorus(foot=7, mode="Dimension 1", mix=0.25), plate(mix=16, decay=1.2), dly(foot=6, model="Tape", time="1/4", feedback=20, mix=10)]}
    st = [S("A", "Comping", {"chorus": False, "dly": False}),
          S("B", "Chord Melody", {"chorus": True, "dly": False}, {"plate": {"mix": 22, "decay": 1.6}}),
          S("C", "Solo", {"chorus": False, "dly": True}, {"eq": {"midgain": 2.5, "midfreq": 900, "highs": -3}}, level=2),
          S("D", "Ballad", {"chorus": True, "dly": True}, {"plate": {"mix": 28, "decay": 2.2}, "dly": {"mix": 14}}),
          S("E", "Bright Swing", {"chorus": False, "dly": False}, {"eq": {"highs": -1, "midgain": 1}})]
    return patch("factory-guitar-jazz-box", "Jazz Box", "guitar", ["jazz", "clean"], chain, st, color="#c9a227", groove="swing", bpm=160)


def g_texas_shuffle():
    # blues texan : une Tube Screamer devant un Super Reverb, un ODS pour le lead, un Vibratone, une spring
    chain = {"pre": [gate(-60), ts808(foot=6, out=-1)],
             "split": two([super_rv()], [dumble(), deluxe_cab()]),
             "post": [eq(lowcut=75, midgain=1, midfreq=800, highs=-1),
                      B("vibratone", "rotary", foot=7, speed="fast", cabinet="Vibratone", drive=10, balance=50),
                      dly(foot=8, model="Tape", time="1/8", feedback=12, mix=12),
                      verb("Spring", mix=18, decay=1.6, size=20)]}
    st = [S("A", "Clean Shuffle", {"ts": False, "vibratone": False, "dly": False}, branches=B_OFF),
          S("B", "Texas Rhythm", {"ts": True, "vibratone": False, "dly": False}, branches=B_OFF),
          S("C", "Lead", {"ts": True, "vibratone": False, "dly": True}, {"eq": {"midgain": 2.5}}, A_OFF, 3),
          S("D", "Vibratone", {"ts": False, "vibratone": True, "dly": False}, branches=B_OFF),
          S("E", "Slow Burn", {"ts": False, "vibratone": False, "dly": True}, {"verb": {"mix": 26, "decay": 2.2}, "dly": {"time": "1/4", "feedback": 25, "mix": 14}}, A_OFF, 2)]
    return patch("factory-guitar-texas-shuffle", "Texas Shuffle", "guitar", ["blues", "texas"], chain, st, color="#d4572a", groove="shuffle", bpm=96)


def g_wailing_blues():
    # blues rock qui chante : une SD-1 devant un JCM800 et un 4x12, un sustainer pour les notes tenues, un Pro Reverb clair
    chain = {"pre": [gate(-58), sd1(foot=6)],
             "split": two([jcm800(), greenback()], [pro_reverb()]),
             "post": [eq(lowcut=80, midgain=1.5, midfreq=750, highs=-2),
                      B("sustain", "sustainer", foot=8, harmonic="Octave", delay=500, rise=1500, bloom=-8, mode="Feedback"),
                      dly(foot=7, model="BBD", time="1/4", feedback=28, mix=15),
                      verb("Hall", mix=22, decay=2.4, size=36)]}
    st = [S("A", "Clean Ballad", {"sd1": False, "sustain": False, "dly": True}, {"verb": {"mix": 28}}, A_OFF),
          S("B", "Crunch", {"sd1": False, "sustain": False, "dly": False}, branches=B_OFF),
          S("C", "Singing Lead", {"sd1": True, "sustain": False, "dly": True}, {"eq": {"midgain": 3}}, B_OFF, 3),
          S("D", "Endless Bend", {"sd1": True, "sustain": True, "dly": True}, {"eq": {"midgain": 3}}, B_OFF, 3),
          S("E", "Rhythm", {"sd1": True, "sustain": False, "dly": False}, branches=B_OFF)]
    return patch("factory-guitar-wailing-blues", "Wailing Blues", "guitar", ["blues", "rock", "lead"], chain, st,
                 color="#8d0801", groove="six-eight", bpm=66, service="compo")


def g_ambient_djent():
    # djent ambiant : JC-120 pour les clairs (chorus, shimmer), TS9 + 6505+ + V30 pour la rythmique grave et serrée
    chain = {"pre": [met(-50), comp("Clean", thresh=-26, ratio=3, attack=20), ts9(foot=6)],
             "split": two([p6505(), v30()], [jc120()]),
             "post": [eq(lowcut=90, midgain=1, midfreq=1500, highs=-1, mid2gain=-3, mid2freq=450),
                      chorus(foot=8, mode="Dimension 2", mix=0.35),
                      dly(foot=7, time="1/8•", feedback=35, mix=16),
                      shimmer(mix=24, decay=6, shimmer=35),
                      verb("Hall", mix=20, decay=3.0, size=40)]}
    st = [S("A", "Halo Clean", {"comp": True, "ts": False, "chorus": True, "dly": True, "shim": True},
            {"met": {"thresh": -70}, "dly": {"time": "1/4", "feedback": 40, "mix": 20}}, A_OFF),
          S("B", "Glass Arp", {"comp": True, "ts": False, "chorus": True, "dly": True, "shim": False},
            {"met": {"thresh": -70}, "dly": {"time": "1/8•", "feedback": 30, "mix": 14}}, A_OFF),
          S("C", "Low Riff", {"comp": False, "ts": True, "chorus": False, "dly": False, "shim": False},
            {"verb": {"mix": 8, "decay": 1.4, "size": 24}}, B_OFF),
          S("D", "Wall", {"comp": False, "ts": True, "chorus": False, "dly": True, "shim": True},
            {"dly": {"time": "1/4", "feedback": 22, "mix": 8}, "shim": {"mix": 14}}, B_OFF),
          S("E", "Lead", {"comp": False, "ts": True, "chorus": False, "dly": True, "shim": False},
            {"eq": {"midgain": 2.5, "midfreq": 900}, "dly": {"time": "1/8•", "feedback": 32, "mix": 18}}, B_OFF, 3)]
    return patch("factory-guitar-ambient-djent", "Ambient Djent", "guitar", ["metal", "progressive", "ambient", "djent"],
                 chain, st, color="#3d348b", groove="metal-verse", bpm=120)


def g_hero_lead():
    # hero lead instrumental : une TS9 à 0 de gain qui pousse un Bogner, un clair Deluxe, une harmonie, des delays
    chain = {"pre": [gate(-56), comp("Clean", thresh=-26, ratio=2.5, attack=30), ts9(foot=6, out=-1)],
             "split": two([bogner(), v30()], [deluxe65()]),
             "post": [B("wah", "wah", foot=8, wah=0.5, mode="manual"),
                      B("harm", "pitch", foot=7, engine="Poly", shift=4, mix=35, harmony="Scale", key="E", scale="Major"),
                      eq(lowcut=90, midgain=2, midfreq=900, highs=-2),
                      chorus(mode="Dimension 1", mix=0.3),
                      dly("dly", model="Digital", time="1/8•", feedback=30, mix=16),
                      dly("echo", model="Tape", time="1/4", feedback=35, mix=10),
                      verb("Plate", mix=20, decay=2.6, size=34)]}
    st = [S("A", "Clean Arp", {"ts": False, "wah": False, "harm": False, "chorus": True, "dly": True, "echo": True}, branches=A_OFF),
          S("B", "Rhythm Drive", {"ts": False, "wah": False, "harm": False, "chorus": False, "dly": False, "echo": False}, branches=B_OFF),
          S("C", "Hero Lead", {"ts": True, "wah": False, "harm": False, "chorus": False, "dly": True, "echo": True}, branches=B_OFF, level=3),
          S("D", "Harmony Lead", {"ts": True, "wah": False, "harm": True, "chorus": False, "dly": True, "echo": False}, branches=B_OFF, level=3),
          S("E", "Vocal Wah", {"ts": True, "wah": True, "harm": False, "chorus": False, "dly": True, "echo": True}, branches=B_OFF, level=3)]
    return patch("factory-guitar-hero-lead", "Hero Lead", "guitar", ["rock", "lead", "instrumental"], chain, st,
                 color="#0081a7", groove="rock-solo", bpm=132, service="compo")


def g_groove_metal():
    # metal groove : un full rig à transistors pris au micro (2026-11-16, le mainteneur : le son d'avant manquait de patate — la tête
    # RG-100 seule derrière une IR, et −6 dB à 800 Hz par-dessus), un creux de médiums plus léger, un gate à clé ; un
    # clair chorusé sur un JC-120B micro SM57
    chain = {"pre": [met(-44, hold=10, release=60), B("boost", "shem", foot=6, grind=4, voice="Focused")],
             "split": two([warhead_rhythm()], [jc120b()]),
             "post": [B("geq", "eq-graphic", layout="Guitar 7", gt_100=2, gt_200=1, gt_400=-2, gt_800=-3, gt_1k6=0, gt_3k2=2, gt_6k4=1),
                      chorus(foot=8, mode="Classic", mix=0.4),
                      dly(foot=7, time="1/4", feedback=25, mix=12),
                      room(mix=10, decay=0.7)]}
    st = [S("A", "Southern Riff", {"boost": True, "chorus": False, "dly": False}, branches=B_OFF),
          S("B", "Chug Breakdown", {"boost": True, "chorus": False, "dly": False}, {"met": {"thresh": -40}, "geq": {"gt_400": -4, "gt_800": -5}}, B_OFF),
          S("C", "Scooped Wall", {"boost": False, "chorus": False, "dly": False}, branches=B_OFF),
          S("D", "Clean Chorus", {"boost": False, "chorus": True, "dly": True}, {"met": {"thresh": -70}}, A_OFF),
          S("E", "Lead", {"boost": True, "chorus": False, "dly": True}, {"geq": {"gt_800": 1, "gt_1k6": 3}}, B_OFF, 3)]
    return patch("factory-guitar-groove-metal", "Groove Metal", "guitar", ["metal", "groove"], chain, st,
                 color="#6a040f", groove="half-time", bpm=140, kit="drums-aasimonster")


def g_squeal_lead():
    # le lead qui crie : un full rig à transistors très saturé, une wah, une octave, un flanger pour les riffs
    chain = {"pre": [met(-46, release=80)],
             "split": None,
             "post": [warhead(), B("wah", "wah", foot=6, wah=0.6, mode="manual", q=120),
                      B("whammy", "pitch", foot=7, engine="Whammy", shift=12, mix=50),
                      B("flange", "flanger-js", foot=8, mode="Mistress", rate=0.25, feedback=-12, depth=80),
                      eq(lowcut=90, midgain=2, midfreq=1000, highs=0),
                      dly(time="1/4", feedback=30, mix=14), room(mix=12, decay=0.9)]}
    st = [S("A", "Lead", {"wah": False, "whammy": False, "flange": False}, level=2),
          S("B", "Wah Lead", {"wah": True, "whammy": False, "flange": False}, level=2),
          S("C", "Octave Squeal", {"wah": False, "whammy": True, "flange": False}, level=2),
          S("D", "Flanged Riff", {"wah": False, "whammy": False, "flange": True}, {"dly": {"mix": 6}}),
          S("E", "Dive", {"wah": False, "whammy": True, "flange": False}, {"whammy": {"shift": -12, "mix": 100}}, level=2)]
    return patch("factory-guitar-squeal-lead", "Squeal Lead", "guitar", ["metal", "groove", "lead"], chain, st,
                 color="#6a040f", groove="metal-solo", bpm=140, service="compo", kit="drums-aasimonster")


def g_glass_ambient():
    # rock ambiant : un Twin full rig, un trémolo, une DS-1 qui claque, un granulaire qui fige, un modulateur en anneau
    chain = {"pre": [gate(-60), ds1(foot=6, model=419260)],
             "split": None,
             "post": [twin_rig(), B("trem", "tremolo", foot=7, rate=5.5, depth=0.6, wave="Sine", model="Optical"),
                      B("grain", "granular", foot=8, grains=16, size=180, mix=40, mode="Cloud"),
                      B("ring", "ringmod", carrier="Free", freq=0.35, mix=0.5),
                      dly(model="Tape", time="1/8•", feedback=40, mix=18),
                      verb("Cloud", mix=26, decay=3.5, size=44)]}
    st = [S("A", "Glass Clean", {"ds1": False, "trem": True, "grain": False, "ring": False}),
          S("B", "Crunch Burst", {"ds1": True, "trem": False, "grain": False, "ring": False}, {"verb": {"mix": 12}}),
          S("C", "Frozen Pad", {"ds1": False, "trem": False, "grain": True, "ring": False}, {"grain": {"mix": 70}, "verb": {"mix": 34}}),
          S("D", "Ring Glitch", {"ds1": False, "trem": False, "grain": False, "ring": True}),
          S("E", "Tape Echo", {"ds1": False, "trem": False, "grain": False, "ring": False}, {"dly": {"feedback": 55, "mix": 26}}, level=1)]
    return patch("factory-guitar-glass-ambient", "Glass Ambient", "guitar", ["ambient", "alternative", "art-rock"], chain, st,
                 color="#118ab2", groove="lofi", bpm=84)


def g_loop_indie():
    # indie à boucles : un Deluxe clair, une Klon pour pousser, un swell pour poser des nappes, des échos pointés
    chain = {"pre": [gate(-60), klon(foot=6)],
             "split": None,
             "post": [drii(model=418153), B("swell", "swell", foot=8, rise=600, sens=50),
                      chorus(foot=7, mode="Classic", mix=0.35),
                      dly(time="1/8•", feedback=38, mix=20), verb("Hall", mix=22, decay=2.2, size=32)]}
    st = [S("A", "Jangle", {"klon": False, "swell": False, "chorus": True}),
          S("B", "Dotted Echo", {"klon": False, "swell": False, "chorus": False}, {"dly": {"mix": 26, "feedback": 45}}),
          S("C", "Klon Push", {"klon": True, "swell": False, "chorus": False}, {"dly": {"mix": 12}}),
          S("D", "Swell Pad", {"klon": False, "swell": True, "chorus": True}, {"verb": {"mix": 34, "decay": 3.4}}),
          S("E", "Lead Out", {"klon": True, "swell": False, "chorus": True}, level=2)]
    return patch("factory-guitar-loop-indie", "Loop Indie", "guitar", ["indie", "loop", "pop"], chain, st,
                 color="#06d6a0", groove="rock-8", bpm=112)


def g_fuzz_grunge():
    # grunge épais, refait sur la guitare d'un preset du mainteneur qui sonne (2026-11-16) : DEUX amplis derrière un split —
    # une Big Muff à op-amp (tonalité haute, peu de sustain) dans un JCM800 modifié pris au micro pour le mur, un Twin
    # brillant et un 2x12 Creamback pour le clair. Par-dessus : un phaser pour le pont, un flanger sur le clair, un
    # écho à bande pour le solo.
    chain = {"pre": [gate(-52, release=90)],
             "split": two([twin_bright(), creamback()], [muff_bright(foot=6), jcm800_mod()]),
             "post": [B("phase", "phaser-js", foot=7, model="Script 90", rate=0.4, feedback=-6, wet=-3),
                      B("flange", "flanger-js", foot=8, mode="Mistress", rate=0.18, feedback=-14, depth=70),
                      eq(lowcut=80, midgain=0, midfreq=700, highs=0), dly(model="Tape", time="1/4", feedback=25, mix=10), room(mix=14)]}
    st = [S("A", "Verse Crunch", {"muff": False, "phase": False, "flange": False}, branches=A_OFF),
          S("B", "Fuzz Wall", {"muff": True, "phase": False, "flange": False}, branches=A_OFF),
          S("C", "Fuzz Lead", {"muff": True, "phase": False, "flange": False}, {"eq": {"midgain": 3, "midfreq": 800}, "dly": {"mix": 18}}, A_OFF, 3),
          S("D", "Phased Bridge", {"muff": True, "phase": True, "flange": False}, branches=A_OFF),
          S("E", "Jet Clean", {"muff": False, "phase": False, "flange": True}, {"room": {"mix": 20}}, B_OFF)]
    return patch("factory-guitar-fuzz-grunge", "Fuzz Grunge", "guitar", ["grunge", "alternative", "fuzz"], chain, st,
                 color="#9c6644", groove="rock-8", bpm=128)


def g_funk_clean():
    # funk : un Marshall clair très dynamique, un compresseur, une enveloppe pour le funk, un chorus pour les accords
    chain = {"pre": [gate(-62), comp("Pedal", thresh=-24, ratio=4, makeup=4, attack=5)],
             "split": None,
             "post": [jubilee(106490), greenback(), B("env", "autowah", foot=6, type="Wah", peak=5, attack=4, release=120),
                      chorus(foot=7, mode="Classic", rate=0.8, mix=0.4), eq(lowcut=100, midgain=1, midfreq=1200, highs=1),
                      dly(foot=8, time="1/8", feedback=18, mix=10), room(mix=12)]}
    st = [S("A", "Chop", {"env": False, "chorus": False, "dly": False}),
          S("B", "Neck Chords", {"env": False, "chorus": True, "dly": False}, {"eq": {"highs": -1}}),
          S("C", "Envelope", {"env": True, "chorus": False, "dly": False}),
          S("D", "Bright Slap", {"env": False, "chorus": False, "dly": True}, {"eq": {"highs": 3}}),
          S("E", "Swirl", {"env": False, "chorus": True, "dly": True}, {"room": {"mix": 20}})]
    return patch("factory-guitar-funk-clean", "Funk Clean", "guitar", ["funk", "clean"], chain, st,
                 color="#ef476f", groove="funk-16", bpm=100)


def g_funk_drive():
    # funk rock saturé : une DS-1 et le canal crunch du même Marshall, une wah pour le lead, une fuzz golem pour le solo
    chain = {"pre": [gate(-56), ds1(foot=6, model=419263), B("fuzz", "fuzz", foot=8, fuzz=75, tone=10, level=-3, model="Si Four")],
             "split": None,
             "post": [jubilee(106491), greenback(), B("wah", "wah", foot=7, wah=0.5, mode="manual"),
                      B("flange", "flanger-js", mode="Mistress", rate=0.2, feedback=-14), eq(lowcut=90, midgain=1.5, midfreq=1000),
                      dly(time="1/4", feedback=22, mix=12), room(mix=14)]}
    st = [S("A", "Crunch Rhythm", {"ds1": False, "fuzz": False, "wah": False, "flange": False}),
          S("B", "Dirty Chords", {"ds1": True, "fuzz": False, "wah": False, "flange": False}),
          S("C", "Wah Lead", {"ds1": True, "fuzz": False, "wah": True, "flange": False}, {"dly": {"mix": 16}}, level=3),
          S("D", "Fuzz Solo", {"ds1": False, "fuzz": True, "wah": False, "flange": False}, {"dly": {"mix": 18}}, level=3),
          S("E", "Flanged Crunch", {"ds1": False, "fuzz": False, "wah": False, "flange": True})]
    return patch("factory-guitar-funk-drive", "Funk Drive", "guitar", ["funk", "rock", "drive"], chain, st,
                 color="#ef476f", groove="funk-16", bpm=100, service="compo")


def g_eight_string_nu():
    # nu metal 8 cordes : une Dual Rectifier rouge moderne, un 4x12 V30, des clairs JC rêveurs (chorus, delay, nuage)
    chain = {"pre": [met(-46, hold=20, release=90)],
             "split": two([dualrec(), v30()], [jc120()]),
             "post": [eq(lowcut=60, midgain=-2, midfreq=600, highs=1),
                      B("oct", "pitch", foot=8, engine="Whammy", shift=-12, mix=45),
                      chorus(foot=6, mode="Dimension 3", mix=0.4),
                      dly(foot=7, model="Tape", time="1/4", feedback=35, mix=16),
                      verb("Cloud", mix=24, decay=3.2, size=42)]}
    st = [S("A", "Dream Clean", {"oct": False, "chorus": True, "dly": True}, {"met": {"thresh": -70}}, A_OFF),
          S("B", "Whisper Clean", {"oct": False, "chorus": False, "dly": False}, {"met": {"thresh": -70}, "verb": {"mix": 14}}, A_OFF),
          S("C", "Heavy Low", {"oct": False, "chorus": False, "dly": False}, {"verb": {"mix": 8, "decay": 1.2}}, B_OFF),
          S("D", "Shoegaze Wall", {"oct": False, "chorus": True, "dly": True}, {"verb": {"mix": 30, "decay": 3.8}}, B_OFF),
          S("E", "Octave Dive", {"oct": True, "chorus": False, "dly": True}, branches=B_OFF, level=2)]
    return patch("factory-guitar-eight-string-nu", "Eight-String Nu", "guitar", ["nu-metal", "metal", "eight-string", "shoegaze"],
                 chain, st, color="#5a189a", groove="metal-chorus", bpm=120)


def g_pop_chorus():
    # pop rock : un Deluxe clair et son canal crunch, une simulation de guitare classique pour un solo de nylon
    # la nylon n'est PAS une troisième branche (deux au plus, règle du mainteneur) : un bloc avant le split, allumé dans sa scène
    chain = {"pre": [gate(-60), comp("Clean", thresh=-22, ratio=2.5),
                     B("nylon", "acoustic-sim", model="Classical", body=60, top=40, mic=70, mix=100)],
             "split": two([drii("clean", 418153)], [drii("crunch", 413045)]),
             "post": [chorus(foot=6, mode="Classic", rate=0.5, mix=0.35), dly(foot=7, time="1/4", feedback=28, mix=14),
                      plate(mix=22, decay=1.8)]}
    st = [S("A", "Verse Clean", {"nylon": False, "chorus": True, "dly": False}, branches=B_OFF),
          S("B", "Chorus Crunch", {"nylon": False, "chorus": False, "dly": False}, branches=A_OFF),
          S("C", "Nylon Solo", {"nylon": True, "chorus": False, "dly": True}, {"plate": {"mix": 26}}, B_OFF, 2),
          S("D", "Ballad Arp", {"nylon": False, "chorus": True, "dly": True}, branches=B_OFF),
          S("E", "Bridge Drive", {"nylon": False, "chorus": True, "dly": True}, branches=A_OFF, level=1)]
    return patch("factory-guitar-pop-chorus", "Pop Chorus", "guitar", ["pop", "rock", "ballad"], chain, st,
                 color="#ffb703", groove="rock-8", bpm=76)


def g_gypsy_acoustic():
    # manouche : la DI devient une guitare acoustique au micro (pas d'ampli ni de baffle derrière), et le Standard de
    # SW10 joue la POMPE et la contrebasse de « Crooked Lantern » — on prend le thème et les chorus. Dans aucun preset
    # ni chanson : c'est un patch pour jouer seul (le mainteneur, 2026-11-16).
    chain = {"pre": [gate(-62), B("acoustic", "acoustic-sim", model="Parlor", body=45, top=60, mic=75, mix=100, twelve=False),
                     comp("Opto", thresh=-22, ratio=2.5, makeup=2, attack=20), eq(lowcut=90, midgain=1, midfreq=1800, highs=1),
                     dly(foot=6, model="Tape", time="1/8", feedback=12, mix=10), room(mix=14, decay=0.9, size=14)],
             "split": None, "post": []}
    st = [S("A", "Theme", {"dly": False}),
          S("B", "Chorus", {"dly": False}, {"acoustic": {"top": 70, "mic": 85}, "eq": {"midgain": 2.5, "midfreq": 2200, "highs": 2}}, level=2),
          S("C", "Ballad", {"dly": True}, {"acoustic": {"model": "Concert", "body": 60, "top": 45}, "room": {"mix": 24, "decay": 1.5}}),
          S("D", "Nylon", {"dly": False}, {"acoustic": {"model": "Classical", "body": 60, "top": 40, "mic": 70}}),
          S("E", "Rhythm", {"dly": False}, {"acoustic": {"body": 55, "top": 50}, "eq": {"midgain": 0, "highs": 0}}, level=-2)]
    return patch("factory-guitar-gypsy-acoustic", "Gypsy Acoustic", "guitar", ["jazz", "manouche", "acoustic"], chain, st,
                 color="#b08968", groove=None, bpm=200,
                 gen=[std("crooked-lantern", "blonde-bop", "swing", bass=True, guitar=True)])


# ══ BASSE ════════════════════════════════════════════════════════════════════════════════════════════════════════
def bass_patch(pid, name, tags, pre, split, post, st, color, groove, bpm, service="rec", kit="drums-black-pearl"):
    return patch(pid, name, "bass", tags, {"pre": pre, "split": split, "post": post}, st, color=color, groove=groove, bpm=bpm,
                 service=service, kit=kit)


def b_upright_jazz():
    # CHAQUE SCÈNE S'ENTEND (2026-11-16, comme les claviers) : plus de scène à 3 dB d'aigus près
    st = [S("A", "Walking"),
          S("B", "Ballad", params={"eq": {"highs": -7, "lows": 2}, "room": {"mix": 26, "decay": 1.6}, "comp": {"ratio": 2}}, level=-1),
          S("C", "Solo", params={"eq": {"midgain": 5, "midfreq": 900, "highs": 1}, "comp": {"ratio": 5, "makeup": 4}, "room": {"mix": 18}}, level=3),
          S("D", "Bright Pluck", params={"eq": {"highs": 6, "midgain": 2, "midfreq": 1800, "lowcut": 60}, "room": {"mix": 5}})]
    return bass_patch("factory-bass-upright-jazz", "Upright Jazz", ["jazz"], [gate(-62), comp("Opto", thresh=-24, ratio=3, attack=20)], None,
                      [b15(), eq(lowcut=35, midgain=0, midfreq=600, highs=-2), room(mix=12, decay=0.9)], st, "#c9a227", "swing", 160)


def b_blues_round():
    st = [S("A", "Round", {"drive": False}), S("B", "Push", {"drive": True}),
          S("C", "Warm Ballad", {"drive": False}, {"eq": {"highs": -8, "lows": 2}, "comp": {"ratio": 2}}, level=-1),
          S("D", "Growl Fill", {"drive": True}, {"drive": {"gain": 72, "tone_stack": 60}, "eq": {"midgain": 4, "midfreq": 900}}, level=2)]
    return bass_patch("factory-bass-blues-round", "Blues Round", ["blues", "rock"],
                      [gate(-60), comp("Opto", thresh=-22, ratio=3), B("drive", "emet", foot=6, gain=35, tone_stack=45, level=0)], None,
                      [svt_rig(379985), eq(lowcut=35, midgain=1, midfreq=700, highs=-1)], st, "#d4572a", "shuffle", 96)


def b_prog_biamp():
    # deux voix en parallèle, et chaque scène change ce qu'on entend d'elles : le grave seul, le mélange, le grain seul
    # serré, puis le mélange poussé par un boost
    st = [S("A", "Sub Clean", {"boost": False}, branches=B_OFF, level=-1), S("B", "Grit Blend", {"boost": False}),
          S("C", "Tight Grit", {"boost": False}, {"comp": {"ratio": 8, "attack": 5}, "met": {"thresh": -42}}, A_OFF, 1),
          S("D", "Growl", {"boost": True}, {"eq": {"midgain": 4, "midfreq": 1000}}, level=1)]
    return bass_patch("factory-bass-prog-biamp", "Prog Bi-Amp", ["metal", "progressive"],
                      [met(-50), comp("FET", thresh=-24, ratio=4, attack=10), B("boost", "shem", foot=6, grind=10, voice="Full")],
                      two([svt_rig(379989)], [b7k()]),
                      [eq(lowcut=35, midgain=1, midfreq=800, highs=1)], st, "#3d348b", "metal-breakdown", 120)


def b_metal_grind():
    # refait le 2026-11-16 (le mainteneur) : un SPLIT — un SVT propre pour le grave, une Darkglass Alpha Omega Ultra dans un 4x10
    # pour le grain. Grind = les deux ; Tight = le grain seul, gate serré ; Clean Low = le SVT seul ; Solo Growl = les
    # deux, poussés par le boost, médiums en avant.
    st = [S("A", "Grind", {"drive": False}),
          S("B", "Tight", {"drive": False}, {"met": {"thresh": -40}, "comp": {"ratio": 8, "attack": 4}}, A_OFF),
          S("C", "Clean Low", {"drive": False}, branches=B_OFF, level=-1),
          S("D", "Solo Growl", {"drive": True}, {"eq": {"midgain": 3, "midfreq": 1000, "highs": 3}}, level=2)]
    return bass_patch("factory-bass-metal-grind", "Metal Grind", ["metal", "groove"],
                      [met(-46), comp("FET", thresh=-24, ratio=5, attack=8), B("drive", "shem", foot=6, grind=10, voice="Full")],
                      two([svt_rig(379988)], [aou(), gk_cab(72421)]),
                      [eq(lowcut=40, midgain=-2, midfreq=500, highs=2)], st, "#6a040f", "half-time", 140,
                      kit="drums-aasimonster")


def b_synth_ambient():
    st = [S("A", "Round", {"oct": False, "synth": False, "tape": False}),
          S("B", "Sub Octave", {"oct": True, "synth": False, "tape": False}),
          S("C", "Synth Bass", {"oct": False, "synth": True, "tape": False}),
          S("D", "Tape Fuzz", {"oct": False, "synth": False, "tape": True}, {"tape": {"input": 14, "wear": 40}})]
    return bass_patch("factory-bass-synth-ambient", "Synth Ambient", ["ambient", "alternative", "synth"],
                      [gate(-60), comp("Opto", thresh=-22, ratio=3)], None,
                      [b15(), B("oct", "octaver", foot=6, direct=0.7, octave1=0.6, mode="Clean", instrument="Bass"),
                       B("synth", "polysynth", foot=7, engine="Mono", wave="Saw", cutoff=900, reso=30, filt_env=18, synth=-4, dry=-12),
                       B("tape", "tape", foot=8, model="Cassette", input=6, mix=100), eq(lowcut=35, midgain=0, highs=-1)],
                      st, "#118ab2", "lofi", 84)


def b_fuzz_bass():
    st = [S("A", "Pick Drive", {"muff": False, "drive": True}), S("B", "Fuzz Bass", {"muff": True, "drive": False}),
          S("C", "Clean Verse", {"muff": False, "drive": False}, {"eq": {"highs": -5, "midgain": -1}, "comp": {"ratio": 2}}, level=-2),
          S("D", "Wall", {"muff": True, "drive": True}, {"eq": {"midgain": 4, "midfreq": 900, "lows": 2}}, level=1)]
    return bass_patch("factory-bass-fuzz", "Fuzz Bass", ["grunge", "rock", "fuzz"],
                      [gate(-56), comp("FET", thresh=-22, ratio=4), B("drive", "emet", gain=40, tone_stack=55, level=0), bigmuff(foot=6)], None,
                      [svt_rig(379986), eq(lowcut=40, midgain=1, midfreq=700, highs=0)], st, "#9c6644", "rock-8", 128)


def b_funk_slap():
    st = [S("A", "Slap", {"env": False, "oct": False}),
          S("B", "Fingers Pocket", {"env": False, "oct": False}, {"eq": {"highs": -6, "lows": 0, "midgain": 2, "midfreq": 800}, "comp": {"ratio": 3, "attack": 15}}),
          S("C", "Envelope", {"env": True, "oct": False}), S("D", "Octave Funk", {"env": False, "oct": True}, level=1),
          S("E", "Solo Pop", {"env": True, "oct": False}, {"eq": {"highs": 6, "midgain": 1, "midfreq": 1500}}, level=3)]
    return bass_patch("factory-bass-funk-slap", "Funk Slap", ["funk"],
                      [gate(-60), comp("FET", thresh=-26, ratio=6, makeup=4, attack=3)], None,
                      [gk_head(), gk_cab(72415), B("env", "autowah", foot=6, type="Low-pass", peak=6, attack=3, release=100, low=200, high=1800),
                       B("oct", "octaver", foot=7, direct=0.8, octave1=0.5, mode="Clean", instrument="Bass"),
                       eq(lowcut=35, lows=3, midgain=-3, midfreq=500, highs=3)], st, "#ef476f", "funk-16", 100)


def b_nu_low():
    st = [S("A", "Clean Low", branches=B_OFF, level=-1), S("B", "Heavy Blend"), S("C", "Grind Only", branches=A_OFF, level=1),
          S("D", "Chorus Low", {"chorus": True}, branches=B_OFF)]
    return bass_patch("factory-bass-nu-low", "Nu Low", ["nu-metal", "metal"],
                      [met(-48), comp("FET", thresh=-24, ratio=5, attack=8)], two([svt_rig(379989)], [alpha()]),
                      [chorus(foot=6, profile="Bass", mode="Classic", rate=0.4, mix=0.3), eq(lowcut=30, midgain=-1, midfreq=500, highs=1)],
                      st, "#5a189a", "metal-chorus", 120)


def b_pop_pick():
    st = [S("A", "Pick Verse", {"drive": False, "chorus": False}), S("B", "Chorus Drive", {"drive": True, "chorus": False}),
          S("C", "Ballad", {"drive": False, "chorus": False}, {"eq": {"highs": -7, "lows": 2}, "comp": {"ratio": 2}}, level=-1),
          S("D", "Chorus Bass", {"drive": False, "chorus": True}),
          S("E", "Melodic", {"drive": False, "chorus": False}, {"eq": {"midgain": 5, "midfreq": 900, "highs": 2}}, level=2)]
    return bass_patch("factory-bass-pop-pick", "Pop Pick", ["pop", "rock"],
                      [gate(-60), comp("Clean", thresh=-22, ratio=4), B("drive", "emet", foot=6, gain=30, tone_stack=55, level=0)], None,
                      [svt_head(382790), gk_cab(72431), chorus(foot=7, profile="Bass", mix=0.3), eq(lowcut=35, midgain=0, highs=1)],
                      st, "#ffb703", "rock-8", 76)


def b_lab():
    # la basse « instrument » : deux voix en parallèle — un grave propre, une Darkglass — et un synthé qui se pose
    # PAR-DESSUS, en série après la somme. Un split se fait en DEUX branches, pas plus (règle du mainteneur, 2026-11-16 :
    # le Designer n'en dessine que deux, la troisième sonnait sans pouvoir se voir ni se régler).
    st = [S("A", "Sub Only", {"synth": False}, branches=B_OFF),
          S("B", "Grit Blend", {"synth": False}),
          S("C", "Synth Layer", {"synth": True}, branches=B_OFF),
          S("D", "Full Stack", {"synth": True}, level=1),
          S("E", "Solo Chorus", {"synth": False, "chorus": True}, level=3)]
    return bass_patch("factory-bass-lab", "Bass Lab", ["bass", "progressive", "synth"],
                      [gate(-58), comp("FET", thresh=-24, ratio=4, attack=8)],
                      two([svt_rig(379988)], [xultra(), gk_cab(72421)], gain=-4),
                      [B("synth", "polysynth", foot=7, engine="Mono", wave="Pulse", cutoff=1400, reso=35, filt_env=20, synth=-4, dry=-3),
                       chorus(foot=6, profile="Bass", mode="Dimension 2", mix=0.35), eq(lowcut=30, midgain=0, highs=1),
                       B("wide", "widener", mode="Double", amount=40)], st, "#00b4d8", "funk-16", 100, service="compo")


# ══ CLAVIERS ═════════════════════════════════════════════════════════════════════════════════════════════════════
def keys_patch(pid, name, tags, chain, st, color, groove, bpm, role="keys", service="rec"):  # noqa: E501
    return patch(pid, name, role, tags, {"chain": chain}, st, color=color, groove=groove, bpm=bpm, midi=True, service=service)


def k_jazz_piano():
    # CHAQUE SCÈNE S'ENTEND (2026-11-16, le mainteneur : « des scènes identiques, aucun intérêt ») : plus de scène qui ne bouge
    # qu'un demi-réglage d'EQ — une salle, un club sec, un piano de solo qui avance, un vieux piano sur bande.
    st = [S("A", "Trio", {"hall": False, "tape": False}),
          S("B", "Ballad", {"hall": True, "tape": False}, {"room": {"mix": 8}, "eq": {"highs": -4}}),
          S("C", "Solo", {"hall": False, "tape": False}, {"eq": {"midgain": 4, "midfreq": 2500, "highs": 3}, "comp": {"ratio": 4, "makeup": 4}, "room": {"mix": 10}}, level=3),
          S("D", "Soft", {"hall": False, "tape": True}, {"eq": {"highs": -9, "midgain": -2, "midfreq": 3000}, "room": {"mix": 24, "decay": 1.4}}, level=-2)]
    return keys_patch("factory-keys-jazz-piano", "Jazz Piano", ["jazz", "piano"],
                      [B("piano", "piano", sfz=SAL, volume=0), comp("Opto", thresh=-20, ratio=2, makeup=2, attack=20),
                       eq(lowcut=40, midgain=0, highs=-2), B("tape", "tape", model="Home Reel", wear=45, mix=100),
                       room(mix=18, decay=1.1, size=16), verb("Hall", bid="hall", mix=34, decay=3.2, size=40)], st, "#c9a227", "swing", 160)


def k_blues_organ():
    st = [S("A", "Gospel Bed", {"drive": False}), S("B", "Fast Leslie", {"drive": False}, {"organ": {"leslie": "fast"}}),
          S("C", "Screaming", {"drive": True}, {"organ": {"leslie": "fast", "db4": 8, "db2": 6}}, level=2),
          S("D", "Soft Pad", {"drive": False}, {"organ": {"leslie": "slow", "db8": 4, "db513": 4}}, level=-2)]
    return keys_patch("factory-keys-blues-organ", "Blues Organ", ["blues", "organ"],
                      [B("organ", "organ", db16=8, db513=8, db8=8, db4=4, db223=0, db2=0, db135=0, db113=0, db1=0, leslie="slow", perc=True),
                       B("drive", "emet", foot=6, gain=40, tone_stack=48, level=0), room(mix=14, decay=0.9)], st, "#d4572a", "shuffle", 96)


def k_cathedral_piano():
    st = [S("A", "Hall Piano", {"dly": False, "shim": False}), S("B", "Halo", {"dly": True, "shim": True}, {"shim": {"mix": 40, "decay": 8}}),
          S("C", "Under", {"dly": False, "shim": False}, {"eq": {"lowcut": 260, "midgain": -4, "midfreq": 400, "highs": -5}, "verb": {"mix": 10, "decay": 1.6}}, level=-3),
          S("D", "Bloom", {"dly": True, "shim": False}, {"eq": {"lowcut": 140, "highs": 3}, "dly": {"mix": 26, "feedback": 45}, "verb": {"mix": 34, "decay": 5}})]
    return keys_patch("factory-keys-cathedral-piano", "Cathedral Piano", ["ambient", "piano", "metal"],
                      [B("piano", "piano", sfz=SAL, volume=0), comp("Clean", thresh=-22, ratio=2.5, makeup=2),
                       eq(lowcut=50, midgain=-1.5, midfreq=400, highs=0), dly(foot=7, time="1/4", feedback=30, mix=14),
                       shimmer(foot=6, mix=30, decay=6, shimmer=40), verb("Cathedral", mix=24, decay=3.4, size=44)], st, "#3d348b", "metal-intro", 120)


def k_hero_pad():
    st = [S("A", "Sky Pad", {"shim": False, "chorus": False}),
          S("B", "Bright", {"shim": False, "chorus": True}, {"vital": {"fcut": 0.95}, "dly": {"mix": 24}}),
          S("C", "Under", {"shim": False, "chorus": False}, {"vital": {"fcut": 0.2, "rmix": 0.1}, "dly": {"mix": 0}}, level=-4),
          S("D", "Shimmer Rise", {"shim": True, "chorus": True}, {"vital": {"fcut": 0.75}, "shim": {"mix": 45, "decay": 8}}, level=1)]
    return keys_patch("factory-keys-hero-pad", "Hero Pad", ["rock", "pad", "instrumental"],
                      [B("vital", "vital", preset="Sparkly_Dreamy_Pad", fcut=0.55, rmix=0.3, dmix=0.2, vol=0.6),
                       chorus(profile="Keys", mode="Ensemble", mix=0.5),
                       shimmer(foot=6, mix=28, decay=5), dly(time="1/4•", feedback=30, mix=14)], st, "#0081a7", "rock-solo", 132)


def k_dark_pad():
    st = [S("A", "Dark Pad", {"crush": False}),
          S("B", "Low Drone", {"crush": False}, {"vital": {"fcut": 0.2, "transpose": -12, "rmix": 0.15}, "verb": {"mix": 14}}),
          S("C", "Swell", {"crush": False}, {"vital": {"fcut": 0.9, "rmix": 0.5}, "verb": {"mix": 40, "decay": 6}}, level=1),
          S("D", "Crushed", {"crush": True})]
    return keys_patch("factory-keys-dark-pad", "Dark Pad", ["metal", "pad", "dark"],
                      [B("vital", "vital", preset="Dark_Ambient", fcut=0.5, rmix=0.3, dmix=0.15, vol=0.55),
                       B("crush", "bitcrusher", foot=6, quant=0.75, rate=0.45, nonlin=0.1), verb("Hall", mix=24, decay=3)], st, "#6a040f", "half-time", 140,
                      service="compo")


def k_glass_rhodes():
    st = [S("A", "Glass Rhodes", {"trem": True}), S("B", "Tape Rhodes", {"trem": False, "tape": True}),
          S("C", "Dry Keys", {"trem": False, "tape": False}, {"verb": {"mix": 10}}), S("D", "Underwater", {"trem": True, "tape": True}, {"verb": {"mix": 36}})]
    return keys_patch("factory-keys-glass-rhodes", "Glass Rhodes", ["ambient", "rhodes", "alternative"],
                      [B("ep", "ep", bank=DX7, patch=15, fcut=1, res=0, out=0.8), B("trem", "tremolo", foot=6, rate=4.5, depth=0.5, wave="Sine"),
                       B("tape", "tape", foot=7, model="Cassette", wear=30, mix=100), verb("Cloud", mix=24, decay=3.2, size=40)],
                      st, "#118ab2", "lofi", 84)


def k_electro_pads():
    st = [S("A", "Beat", {"crush": False}), S("B", "Crushed Beat", {"crush": True}), S("C", "Tape Beat", {"tape": True}),
          S("D", "Dub Beat", {"dly": True}, level=-1)]
    return keys_patch("factory-keys-electro-pads", "Electro Pads", ["ambient", "electronic", "pads"],
                      [B("pads", "pads", kit="pads-lofi"), B("crush", "bitcrusher", foot=6, quant=0.5, rate=0.4, nonlin=0.1),
                       B("tape", "tape", foot=7, model="Portable Cassette", wear=40, mix=100), dly(foot=8, time="1/8•", feedback=40, mix=18),
                       comp("Bus", thresh=-20, ratio=3, makeup=2)], st, "#118ab2", None, 84, role="keys-pads")


def k_loop_synth():
    st = [S("A", "Bass & Beat", {"dly": False}), S("B", "Bass Only", {"pads": False, "dly": False}),
          S("C", "Filtered", {"dly": True}, {"vital": {"fcut": 0.15}}, level=-2),
          S("D", "Big Drop", {"dly": False}, {"vital": {"fcut": 1.0, "transpose": -12, "vol": 0.75}, "comp": {"ratio": 6, "makeup": 4}}, level=2)]
    return keys_patch("factory-keys-loop-synth", "Loop Synth & Beat", ["indie", "loop", "synth"],
                      [B("vital", "vital", preset="Kickbass", fcut=0.55, rmix=0.0, dmix=0.0, vol=0.65), B("pads", "pads", kit="pads-house"),
                       dly(time="1/8•", feedback=45, mix=24), comp("Bus", thresh=-20, ratio=3, makeup=2, attack=10)], st, "#06d6a0", None, 112, role="keys-pads")


def k_strings_wash():
    st = [S("A", "Strings Wash", {"chorus": False}), S("B", "Chorus Strings", {"chorus": True}),
          S("C", "Thin", {"chorus": False}, {"eq": {"lowcut": 400, "highs": 3}, "verb": {"mix": 10, "decay": 1.4}}, level=-3),
          S("D", "Big Swell", {"chorus": True}, {"verb": {"mix": 42, "decay": 5}, "eq": {"lowcut": 80, "highs": 1}}, level=2)]
    return keys_patch("factory-keys-strings-wash", "Strings Wash", ["grunge", "strings", "pad"],
                      [B("ep", "ep", bank=DX7, patch=20, fcut=1, res=0, out=0.8), chorus(foot=6, profile="Keys", mode="Ensemble", mix=0.5),
                       eq(lowcut=120, midgain=0, highs=-2), verb("Hall", mix=24, decay=2.6)], st, "#9c6644", "rock-8", 128)


def k_funk_clav():
    st = [S("A", "Clav", {"env": False, "phase": False}), S("B", "Envelope Clav", {"env": True, "phase": False}),
          S("C", "Phased", {"env": False, "phase": True}),
          S("D", "Stab", {"env": False, "phase": False}, {"comp": {"ratio": 8, "thresh": -28, "makeup": 5}, "ep": {"fcut": 0.55}, "room": {"mix": 0}}, level=2)]
    return keys_patch("factory-keys-funk-clav", "Funk Clav", ["funk", "clavinet"],
                      [B("ep", "ep", bank=DX7, patch=28, fcut=1, res=0, out=0.8), B("env", "autowah", foot=6, type="Wah", peak=5, attack=3, release=100),
                       B("phase", "phaser-js", foot=7, model="Script 90", rate=0.5), comp("FET", thresh=-22, ratio=4, attack=3), room(mix=10)],
                      st, "#ef476f", "funk-16", 100)


def k_nu_pad():
    st = [S("A", "Haze", {"glitch": False}), S("B", "Glitch Haze", {"glitch": True}),
          S("C", "Low Haze", {"glitch": False}, {"vital": {"fcut": 0.18, "transpose": -12}, "dly": {"mix": 6}}, level=-3),
          S("D", "Open Haze", {"glitch": False}, {"vital": {"fcut": 0.95}, "dly": {"mix": 30, "feedback": 50}, "verb": {"mix": 38, "decay": 6}}, level=1)]
    return keys_patch("factory-keys-nu-pad", "Nu Haze", ["nu-metal", "pad", "electronic"],
                      [B("vital", "vital", preset="Retro_Ambient_Pluck", fcut=0.5, rmix=0.25, dmix=0.25, vol=0.55),
                       B("glitch", "glitch", foot=6, mix=40), dly(time="1/4", feedback=35, mix=16), verb("Cloud", mix=26, decay=3.5)],
                      st, "#5a189a", "metal-intro", 120, service="compo")


def k_pop_piano():
    st = [S("A", "Ballad Piano", {"dly": False, "chorus": False}),
          S("B", "Bright Pop", {"dly": False, "chorus": True}, {"eq": {"highs": 5, "midgain": 2, "midfreq": 3000}, "comp": {"ratio": 5, "makeup": 4}, "plate": {"mix": 12}}, level=1),
          S("C", "Echo Piano", {"dly": True, "chorus": False}, {"dly": {"mix": 26, "feedback": 40}}),
          S("D", "Soft Bed", {"dly": False, "chorus": False}, {"eq": {"highs": -8, "lowcut": 120}, "plate": {"mix": 38, "decay": 3}}, level=-3)]
    return keys_patch("factory-keys-pop-piano", "Pop Piano", ["pop", "piano", "ballad"],
                      [B("piano", "piano", sfz=SAL, volume=0), comp("Clean", thresh=-20, ratio=3, makeup=2),
                       eq(lowcut=60, midgain=0, highs=1), chorus(profile="Keys", mode="Classic", rate=0.5, mix=0.35),
                       dly(foot=6, time="1/4", feedback=25, mix=12), plate(mix=22, decay=1.8)],
                      st, "#ffb703", "rock-8", 76)


# ══ VOIX ═════════════════════════════════════════════════════════════════════════════════════════════════════════
def voice_patch(pid, name, tags, chain, st, color, groove, bpm, service="rec"):
    return patch(pid, name, "voice", tags, {"chain": chain}, st, color=color, groove=groove, bpm=bpm, service=service)


def ess():  return B("ess", "deesser", thresh=-28, freq=6500, range=10)


def v_crooner():
    st = [S("A", "Close"), S("B", "Ballad", params={"plate": {"mix": 30, "decay": 2.2}}), S("C", "Slap", {"dly": True}), S("D", "Big Room", params={"plate": {"mix": 34}}, level=1)]
    return voice_patch("factory-voice-crooner", "Crooner", ["jazz", "vocal"],
                       [gate(-58, release=200), comp("Opto", thresh=-22, ratio=3, makeup=3, attack=10), ess(), eq(lowcut=90, midgain=0, highs=1.5),
                        dly(foot=7, model="Tape", time="1/8", feedback=10, mix=10), plate(mix=22, decay=1.6)], st, "#c9a227", "swing", 160)


def v_blues_shout():
    st = [S("A", "Shout", {"grit": False}), S("B", "Grit", {"grit": True}), S("C", "Slap Echo", {"dly": True}), S("D", "Ballad", {"grit": False}, {"room": {"mix": 24}})]
    return voice_patch("factory-voice-blues-shout", "Blues Shout", ["blues", "vocal"],
                       [gate(-55), comp("FET", thresh=-22, ratio=4, makeup=3), ess(),
                        B("grit", "morph", foot=6, drive=30, morph=10, box=0, mix=60, object="None"), eq(lowcut=100, midgain=1, midfreq=1500, highs=1),
                        dly(foot=7, model="Tape", time="1/8", feedback=15, mix=12), room(mix=16, decay=1)], st, "#d4572a", "shuffle", 96)


def v_halo():
    st = [S("A", "Falsetto Halo", {"double": True, "shim": True}), S("B", "Close Verse", {"double": False, "shim": False}, {"plate": {"mix": 14}}),
          S("C", "Grit Belt", {"scream": True, "double": False, "shim": False}, level=1),
          S("D", "Anthem", {"double": True, "shim": False}, {"dly": {"mix": 14}}, level=1)]
    return voice_patch("factory-voice-halo", "Halo Vocal", ["metal", "ambient", "falsetto"],
                       [gate(-55, release=200), ess(), B("tune", "pitch-correct", corr=0.3, filter=0.2, fastmode=True, key="F#", scale="Minor", song_key=True),
                        B("scream", "morph", foot=8, drive=55, morph=30, box=10, mix=70, object="None"), comp("Clean", thresh=-22, ratio=3.5, makeup=4),
                        eq(lowcut=110, midgain=0, highs=2), B("double", "golem-double", foot=7, shift=12, voice1=-14, formant=0),
                        dly(time="1/4", feedback=32, mix=16), shimmer(foot=6, mix=22, decay=5), plate(mix=24, decay=2.4)], st, "#3d348b", "metal-chorus", 120,
                       service="compo")


def v_metal_scream():
    st = [S("A", "Scream", {"scream": True}), S("B", "Growl", {"scream": True}, {"scream": {"morph": 70, "drive": 75}}),
          S("C", "Clean Shout", {"scream": False}), S("D", "Megaphone", {"scream": False, "radio": True})]
    return voice_patch("factory-voice-metal-scream", "Metal Scream", ["metal", "scream"],
                       [gate(-45, release=90), ess(), B("scream", "morph", foot=6, drive=65, morph=40, box=0, mix=100, object="None"),
                        B("radio", "radio", foot=7, model="Megaphone", drive=30), comp("FET", thresh=-20, ratio=5, makeup=3, attack=5),
                        eq(lowcut=120, midgain=2, midfreq=2000, highs=1), room(mix=10)], st, "#6a040f", "half-time", 140, service="compo")


def v_ethereal():
    # la justesse douce reste allumée partout ; « Robot Falsetto » la durcit
    st = [S("A", "Ethereal", {"tune": True, "dly": True}), S("B", "Close", {"tune": True, "dly": False}, {"verb": {"mix": 16}}),
          S("C", "Robot Falsetto", {"tune": True}, {"tune": {"corr": 1.0, "filter": 0.02}}),
          S("D", "Cloud", {"tune": True, "dly": True, "formant": True}, {"verb": {"mix": 40}})]
    return voice_patch("factory-voice-ethereal", "Ethereal Falsetto", ["ambient", "alternative", "falsetto"],
                       [gate(-58, release=220), ess(), B("tune", "pitch-correct", foot=8, corr=0.4, filter=0.15, fastmode=True, key="A", scale="Minor", song_key=True),
                        comp("Opto", thresh=-22, ratio=3, makeup=3), B("formant", "formant", foot=6, formant=3, mix=50),
                        eq(lowcut=110, highs=2), dly(foot=7, model="Tape", time="1/4•", feedback=40, mix=20), verb("Cloud", mix=28, decay=3.4)],
                       st, "#118ab2", "lofi", 84)


def v_indie_double():
    st = [S("A", "Double", {"double": True}), S("B", "Single", {"double": False}), S("C", "Slap", {"dly": True}), S("D", "Shout", {"double": True}, {"comp": {"ratio": 5}}, level=1)]
    return voice_patch("factory-voice-indie-double", "Indie Double", ["indie", "loop", "vocal"],
                       [gate(-58), ess(), comp("Clean", thresh=-22, ratio=3.5, makeup=3), eq(lowcut=100, highs=1.5),
                        chorus("double", foot=6, profile="Voice", mode="Doubler", mix=0.4), dly(foot=7, model="Tape", time="1/8", feedback=15, mix=12),
                        plate(mix=18, decay=1.4)], st, "#06d6a0", None, 112)


def v_grunge_raw():
    st = [S("A", "Raw", {"grit": False}), S("B", "Gravel", {"grit": True}), S("C", "Quiet Verse", {"grit": False}, {"room": {"mix": 10}}, level=-1),
          S("D", "Scream", {"grit": True}, {"grit": {"drive": 65}}, level=1)]
    return voice_patch("factory-voice-grunge-raw", "Raw Grunge", ["grunge", "vocal"],
                       [gate(-52), ess(), B("grit", "morph", foot=6, drive=45, morph=20, mix=70, object="None"),
                        comp("FET", thresh=-20, ratio=4, makeup=3), eq(lowcut=110, midgain=1.5, midfreq=1800), room(mix=16, decay=1)],
                       st, "#9c6644", "rock-8", 128)


def v_funk_rap():
    st = [S("A", "Rap", {"radio": False}), S("B", "Phone Verse", {"radio": True}), S("C", "Chorus Double", {"double": True}),
          S("D", "Slap Hook", {"dly": True}, level=1)]
    return voice_patch("factory-voice-funk-rap", "Funk Rap", ["funk", "rap", "vocal"],
                       [gate(-55), ess(), comp("FET", thresh=-22, ratio=5, makeup=4, attack=5), B("radio", "radio", foot=6, model="Telephone"),
                        chorus("double", foot=7, profile="Voice", mode="Doubler", mix=0.35), eq(lowcut=110, midgain=1, highs=2),
                        dly(foot=8, model="Digital", time="1/8", feedback=12, mix=12), room(mix=10)], st, "#ef476f", "funk-16", 100)


def v_whisper_scream():
    st = [S("A", "Whisper", {"scream": False, "formant": False}, {"plate": {"mix": 26}}),
          S("B", "Dream", {"scream": False, "formant": True, "dly": True}, {"plate": {"mix": 30}}),
          S("C", "Scream", {"scream": True, "formant": False}, level=1),
          S("D", "Low Growl", {"scream": True, "formant": True}, {"formant": {"formant": -5, "growl": 40}}, level=1)]
    return voice_patch("factory-voice-whisper-scream", "Whisper & Scream", ["nu-metal", "vocal", "scream"],
                       [gate(-58, release=180), ess(), B("formant", "formant", foot=7, formant=-3, growl=0, mix=60),
                        B("scream", "morph", foot=6, drive=60, morph=35, mix=90, object="None"), comp("Clean", thresh=-22, ratio=4, makeup=4),
                        eq(lowcut=100, midgain=0, highs=2), dly(foot=8, model="Tape", time="1/4", feedback=30, mix=14), plate(mix=20, decay=2)],
                       st, "#5a189a", "metal-chorus", 120, service="compo")


def v_pop_tuned():
    st = [S("A", "Pop Verse", {"double": False}), S("B", "Chorus Double", {"double": True}), S("C", "Ballad", {"double": False}, {"plate": {"mix": 30}}),
          S("D", "Hard Tune", {"double": False}, {"tune": {"corr": 1.0, "filter": 0.02}}, level=1)]
    return voice_patch("factory-voice-pop-tuned", "Pop Tuned", ["pop", "vocal"],
                       [gate(-58, release=200), B("tune", "pitch-correct", foot=7, corr=0.6, filter=0.15, fastmode=True, key="C", scale="Major", song_key=True),
                        comp("Clean", thresh=-20, ratio=3, makeup=3), eq(lowcut=100, midgain=0, highs=2), ess(),
                        chorus("double", foot=6, profile="Voice", mode="Doubler", mix=0.35), dly(time="1/4", feedback=22, mix=12), plate(mix=22, decay=1.8)],
                       st, "#ffb703", "rock-8", 76)


def v_karaoke():
    # la voix PAR DÉFAUT de Vocals sur golem.fm (id attendu : factory-voice-karaoke, 2026-11-18) : un chanteur amateur qui
    # sonne bien sans rien régler — coupe-bas, compression douce, de-esser, plaque courte, un doublage au pied ; rien d'extrême
    st = [S("A", "Karaoke"), S("B", "Ballad", params={"plate": {"mix": 28, "decay": 2.0}}), S("C", "Chorus Double", {"double": True}),
          S("D", "Echo", {"dly": True}, level=1)]
    return voice_patch("factory-voice-karaoke", "Karaoke", ["pop", "vocal", "karaoke"],
                       [gate(-60, release=220), comp("Opto", thresh=-20, ratio=2.5, makeup=3, attack=12), ess(), eq(lowcut=100, midgain=0, highs=1.5),
                        chorus("double", foot=6, profile="Voice", mode="Doubler", mix=0.3), dly(foot=7, model="Tape", time="1/4", feedback=18, mix=12),
                        plate(mix=20, decay=1.4)], st, "#ff6fb5", "rock-8", 100)


# ══ BATTERIE (un kit électronique joué au pad, en MIDI) ═══════════════════════════════════════════════════════════
def drums_patch(pid, name, tags, kit, extra, st, color, bpm, service="rec"):
    chain = [B("kit", "drumkit", kit=kit), comp("Bus", thresh=-20, ratio=4, makeup=3, attack=20), eq(lowcut=35, midgain=0, highs=1)] + extra
    return patch(pid, name, "drums", tags, {"chain": chain}, st, color=color, groove=None, bpm=bpm, midi=True, service=service)


def d_brushes():
    return drums_patch("factory-drums-jazz-brushes", "Jazz Brushes", ["jazz", "drums"], "drums-blonde-bop", [room(mix=16, decay=1)],
                       [S("A", "Brushes"), S("B", "Ride Swing", params={"room": {"mix": 22}, "eq": {"highs": 3}}),
                        S("C", "Soft", params={"eq": {"highs": -3}, "comp": {"ratio": 2}}, level=-3),
                        S("D", "Solo", params={"comp": {"ratio": 6, "thresh": -24}, "room": {"mix": 10, "decay": 0.7},
                                               "eq": {"midgain": 2, "midfreq": 2500}}, level=2)], "#c9a227", 160)


def d_vintage():
    return drums_patch("factory-drums-vintage-rock", "Vintage Rock", ["blues", "rock", "drums"], "drums-red-zeppelin", [room(foot=6, mix=20, decay=1.2, size=20)],
                       [S("A", "Shuffle", {"room": True}), S("B", "Big Room", {"room": True}, {"room": {"mix": 32, "decay": 1.8, "size": 30}}),
                        S("C", "Tight", {"room": False}, {"comp": {"ratio": 6}}),
                        S("D", "Ballad", {"room": True}, {"room": {"mix": 26, "decay": 1.6}, "eq": {"highs": -2}}, level=-2)],
                       "#d4572a", 96)


def d_studio():
    return drums_patch("factory-drums-studio-rock", "Studio Rock", ["rock", "pop", "drums"], "drums-black-pearl",
                       [B("punch", "transient", foot=6, attack=8, sustain=0), room(mix=14, decay=0.9)],
                       [S("A", "Tight", {"punch": False}), S("B", "Punch", {"punch": True}),
                        S("C", "Roomy", {"punch": False}, {"room": {"mix": 26, "decay": 1.3}}),
                        S("D", "Soft", {"punch": False}, {"eq": {"highs": -3}, "comp": {"ratio": 2}}, level=-3)],
                       "#ffb703", 120)


def d_metal():
    return drums_patch("factory-drums-metal", "Metal Kit", ["metal", "drums"], "drums-aasimonster",
                       [B("punch", "transient", attack=10, sustain=-6), room(foot=6, mix=10, decay=0.8, size=14)],
                       [S("A", "Blast", {"room": True}),
                        S("B", "Breakdown", {"room": True}, {"comp": {"ratio": 6}, "room": {"mix": 18, "decay": 1.2}, "punch": {"sustain": 0}}),
                        S("C", "Tight", {"room": False}),
                        S("D", "Clean Intro", {"room": True}, {"room": {"mix": 22, "decay": 1.5}, "punch": {"attack": 0, "sustain": 0},
                                                              "eq": {"highs": -2}}, level=-3)],
                       "#6a040f", 140, service="compo")


def d_lofi():
    return drums_patch("factory-drums-lofi", "Lo-Fi Kit", ["ambient", "electronic", "indie", "drums"], "drums-black-pearl",
                       [B("tape", "tape", foot=6, model="Cassette", wear=35, mix=100), B("crush", "bitcrusher", foot=7, quant=0.55, rate=0.45, nonlin=0.1),
                        room(mix=14)],
                       [S("A", "Tape Kit", {"tape": True, "crush": False}), S("B", "Crushed", {"tape": False, "crush": True}),
                        S("C", "Dry", {"tape": False, "crush": False}), S("D", "Dusty", {"tape": True, "crush": True}, level=-1)], "#118ab2", 84)


# ══ PRESETS ══════════════════════════════════════════════════════════════════════════════════════════════════════
REC_PARAMS = {"in1": True, "in2": False, "usb": False, "rec_mode": "tracks_di", "mix": True, "count_in": 0, "transcribe": "manual"}


def preset(pid, name, style, bpm, lanes, scenes, feet, color, gen=None, arr_foot=None, rec_foot=9):
    """Un preset d'usine : chaque lane DÉPOSÉE depuis son patch (patches.apply_to), les scènes nommées pour la chanson qui
    pointent chaque lane sur un état, le pied du preset (SW6–8 des pédales, SW9 le service, SW10 la batterie) et ses blocs
    spéciaux. `lanes` : (id, nom, rôle, patch, midi, n° d'entrée) ; `scenes` : (id, nom, {lane: (nom d'état, dB)}) ;
    `feet` : {sw: [(lane, id de bloc du patch)]}."""
    p = {"id": pid, "name": name, "lanes_v": 2, "lanes": [], "scenes": [], "bpm": bpm, "style": style, "styles": [style], "factory": True}
    for lid, lname, role, _src, midi, nth in lanes:
        p["lanes"].append({"id": lid, "key": lid, "role": role, "name": lname, "in_sel": "usb" if midi else "", "out_sel": "1-2",
                           "chain": {"pre": [], "split": None, "post": []}, "midi": midi, "in_role": None if midi else role,
                           "in_nth": nth, "states": []})
    p["scenes"] = [{"id": sid, "name": nm} for sid, nm, _ in scenes]
    origin = {}
    for lid, _n, _r, src, _m, _nth in lanes:
        before = {b["id"] for L in p["lanes"] for b in lane_blocks(L.get("chain"))}
        p, realm, _lost, _added, _skip = patches.apply_to(p, src, lane=lid)
        assert realm == lid, (pid, src, realm)
        L = next(x for x in p["lanes"] if x["id"] == lid)
        # l'id d'un bloc dans le patch -> son id dans le preset (patches._dedupe suffixe -2, -3…)
        src_ids = [b["id"] for b in lane_blocks(PATCHES[src]["lanes"][0]["chain"])]
        got = [b["id"] for b in lane_blocks(L.get("chain")) if b["id"] not in before]
        origin[lid] = dict(zip(src_ids, got))
    for L, (lid, lname, *_r) in zip(p["lanes"], lanes):
        L["name"] = lname
    blocks = {b["id"]: b for L in p["lanes"] for b in lane_blocks(L.get("chain"))}
    for b in blocks.values():
        b.pop("foot", None)
    used_feet = set()
    for sw, refs in feet.items():
        for lid, bid in refs:
            real = origin[lid].get(bid)
            assert real and real in blocks, f"{pid} SW{sw} : {lid}/{bid} absent ({sorted(origin[lid])})"
            blocks[real]["foot"] = sw
            used_feet.add(sw)
    by_id = {L["id"]: L for L in p["lanes"]}
    out = []
    for sid, nm, want in scenes:
        sc = {"id": sid, "name": nm, "blocks": {}, "params": {}, "branches": {}, "lanes": {}}
        for lid, (state_name, lvl) in want.items():
            L = by_id[lid]
            st = next((s for s in L.get("states") or [] if s.get("name") == state_name), None)
            assert st, f"{pid} {lid} : pas d'état « {state_name} » ({[s.get('name') for s in L.get('states') or []]})"
            ids, types, brs = _lane_sets(L)
            sc["blocks"].update({k: v for k, v in (st.get("blocks") or {}).items() if k in ids or k in types})
            sc["params"].update({k: v for k, v in (st.get("params") or {}).items() if k in ids})
            sc["branches"].update({k: v for k, v in (st.get("branches") or {}).items() if k in brs})
            sc["lanes"][lid] = {"state": st["id"], **({"level": lvl} if lvl else {})}
        out.append(sc)
    p["scenes"] = out
    rec_blocks = [{"id": "rec-global", "type": "rec", "params": dict(REC_PARAMS), **({"foot": rec_foot} if rec_foot else {})},
                  {"id": "click-global", "type": "click", "bypass": True, "params": {"level": 0.0, "beats": 4}},
                  {"id": "compo-global", "type": "compo", "params": {"keep_s": 30, "transcribe": True}}]
    arr = {"id": "arrangement", "type": "arrangement", "params": {"advance": "bars", "sections": []}}
    if arr_foot:
        arr["foot"] = arr_foot
    p["config"] = {"gen": {"out": "1-2", "blocks": gen or []}, "rec": {"click_out": "1-2", "blocks": rec_blocks}, "arr": {"blocks": [arr]}}
    gen_feet = {b["foot"] for b in (gen or []) if b.get("foot")}
    cells = [s[0] for s in scenes] + [str(x) for x in sorted(used_feet | gen_feet | ({rec_foot} if rec_foot else set()) | ({arr_foot} if arr_foot else set()))]
    p["colors"] = {k: color for k in cells}
    p["anims"] = _anims(cells, pid)
    _dump(f"presets/{pid}.json", p)
    return p


# la tonalité du Standard suit le morceau fictif du preset (Rail Yard Shuffle en mi, Harbour Rain en do)
# le Standard d'un preset ACCOMPAGNE quand on joue seul (comme le Chill Jazz d'avant) : ses parties claviers, basse et
# batterie sont ouvertes ; quand les musiciens sont là, on ne l'appuie pas
def std(standard, kit, feel, **kw):
    return {"type": "standard", "id": "standard", "foot": 10, "params": {"standard": standard, "key": "Original", "feel": feel, "motion": "comp",
            "voicing": "rootless", "arp": "Off", "keys": False, "bass": False, "drums": False, "guitar": False, "pompe": "auto", "groove": "auto", "kit": kit, "choruses": 4, **kw}}


PRESETS = []


def presets():
    PRESETS.append(preset("factory-jazz-club", "Blue Lantern Trio", "jazz", 160, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-jazz-box", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-upright-jazz", False, 1),
        ("keys-1", "Piano", "keys", "factory-keys-jazz-piano", True, None),
        ("drums-1", "Drums", "drums", "factory-drums-jazz-brushes", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-crooner", False, 1)], [
        ("A", "Head", {"guitar-1": ("Chord Melody", 0), "bass-1": ("Walking", 0), "keys-1": ("Trio", -2), "drums-1": ("Brushes", 0), "voice-1": ("Close", 0)}),
        ("B", "Guitar Solo", {"guitar-1": ("Solo", 2), "bass-1": ("Walking", 0), "keys-1": ("Soft", -4), "drums-1": ("Ride Swing", 0), "voice-1": ("Close", -10)}),
        ("C", "Piano Solo", {"guitar-1": ("Comping", -4), "bass-1": ("Walking", 0), "keys-1": ("Solo", 2), "drums-1": ("Ride Swing", 0), "voice-1": ("Close", -10)}),
        ("D", "Ballad", {"guitar-1": ("Ballad", -1), "bass-1": ("Ballad", 0), "keys-1": ("Ballad", 0), "drums-1": ("Soft", 0), "voice-1": ("Ballad", 0)}),
        ("E", "Bass Solo", {"guitar-1": ("Comping", -6), "bass-1": ("Solo", 2), "keys-1": ("Soft", -6), "drums-1": ("Soft", 0), "voice-1": ("Close", -10)})],
        {6: [("guitar-1", "dly")], 7: [("guitar-1", "chorus")], 8: [("voice-1", "dly")]}, "#c9a227",
        gen=[std("rooftop-prowl", "blonde-bop", "swing", keys=True, bass=True, drums=True)]))
    PRESETS.append(preset("factory-texas-blues", "Rail Yard", "blues", 112, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-texas-shuffle", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-blues-round", False, 1),
        ("keys-1", "Organ", "keys", "factory-keys-blues-organ", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-blues-shout", False, 1)], [
        ("A", "Shuffle", {"guitar-1": ("Texas Rhythm", 0), "bass-1": ("Round", 0), "keys-1": ("Gospel Bed", -3), "voice-1": ("Shout", 0)}),
        ("B", "Verse", {"guitar-1": ("Clean Shuffle", -1), "bass-1": ("Round", 0), "keys-1": ("Gospel Bed", -4), "voice-1": ("Shout", 0)}),
        ("C", "Guitar Solo", {"guitar-1": ("Lead", 3), "bass-1": ("Push", 0), "keys-1": ("Soft Pad", -6), "voice-1": ("Shout", -10)}),
        ("D", "Organ Solo", {"guitar-1": ("Clean Shuffle", -4), "bass-1": ("Round", 0), "keys-1": ("Screaming", 2), "voice-1": ("Shout", -10)}),
        ("E", "Vibe Out", {"guitar-1": ("Vibratone", 0), "bass-1": ("Warm Ballad", 0), "keys-1": ("Fast Leslie", -3), "voice-1": ("Slap Echo", 0)})],
        {6: [("guitar-1", "ts")], 7: [("guitar-1", "vibratone")], 8: [("voice-1", "grit")]}, "#d4572a",
        gen=[std("rented-room-blues", "black-pearl", "swing", key="E", voicing="full", keys=True, bass=True, drums=True)]))
    PRESETS.append(preset("factory-blues-ballad", "Harbour Rain", "blues", 68, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-wailing-blues", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-blues-round", False, 1),
        ("keys-1", "Organ", "keys", "factory-keys-blues-organ", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-blues-shout", False, 1)], [
        ("A", "Intro", {"guitar-1": ("Clean Ballad", 0), "bass-1": ("Warm Ballad", 0), "keys-1": ("Soft Pad", -3), "voice-1": ("Ballad", -10)}),
        ("B", "Verse", {"guitar-1": ("Crunch", -3), "bass-1": ("Warm Ballad", 0), "keys-1": ("Gospel Bed", -4), "voice-1": ("Ballad", 0)}),
        ("C", "Chorus", {"guitar-1": ("Rhythm", -2), "bass-1": ("Round", 0), "keys-1": ("Fast Leslie", -3), "voice-1": ("Grit", 1)}),
        ("D", "Solo", {"guitar-1": ("Singing Lead", 3), "bass-1": ("Round", 0), "keys-1": ("Soft Pad", -5), "voice-1": ("Ballad", -10)}),
        ("E", "Last Bend", {"guitar-1": ("Endless Bend", 3), "bass-1": ("Round", 0), "keys-1": ("Gospel Bed", -4), "voice-1": ("Ballad", -10)})],
        {6: [("guitar-1", "sd1")], 7: [("guitar-1", "dly")], 8: [("guitar-1", "sustain")]}, "#8d0801",
        gen=[std("rented-room-blues", "black-pearl", "swing", key="C", voicing="full", keys=True, bass=True, drums=True)]))
    PRESETS.append(preset("factory-ambient-djent", "Velvet Ossuary", "metal", 94, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-ambient-djent", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-prog-biamp", False, 1),
        ("keys-1", "Piano", "keys", "factory-keys-cathedral-piano", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-halo", False, 1)], [
        ("A", "Piano Intro", {"guitar-1": ("Halo Clean", -4), "bass-1": ("Sub Clean", -3), "keys-1": ("Halo", 0), "voice-1": ("Falsetto Halo", 0)}),
        ("B", "Verse", {"guitar-1": ("Glass Arp", -1), "bass-1": ("Sub Clean", -1), "keys-1": ("Hall Piano", -1), "voice-1": ("Close Verse", 1)}),
        ("C", "Low Riff", {"guitar-1": ("Low Riff", 0), "bass-1": ("Tight Grit", 0), "keys-1": ("Under", -6), "voice-1": ("Grit Belt", 1)}),
        ("D", "Wall Chorus", {"guitar-1": ("Wall", -1), "bass-1": ("Grit Blend", -1), "keys-1": ("Bloom", -3), "voice-1": ("Anthem", 2)}),
        ("E", "Lead", {"guitar-1": ("Lead", 3), "bass-1": ("Grit Blend", -2), "keys-1": ("Bloom", -6), "voice-1": ("Close Verse", -8)})],
        {6: [("guitar-1", "ts")], 7: [("keys-1", "shim")], 8: [("voice-1", "scream")]}, "#3d348b",
        gen=[drums_service(["metal-intro", "metal-verse", "metal-chorus", "metal-breakdown", "metal-solo", "metal-fill", "metal-end"])]))
    PRESETS.append(preset("factory-hero-instrumental", "Glass Summit", "rock", 120, [
        ("guitar-1", "Lead Guitar", "guitar", "factory-guitar-hero-lead", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-lab", False, 1),
        ("keys-1", "Pad", "keys", "factory-keys-hero-pad", True, None),
        ("drums-1", "Drums", "drums", "factory-drums-studio-rock", True, None)], [
        ("A", "Clean Theme", {"guitar-1": ("Clean Arp", 0), "bass-1": ("Sub Only", 0), "keys-1": ("Sky Pad", -3), "drums-1": ("Soft", 0)}),
        ("B", "Riff", {"guitar-1": ("Rhythm Drive", 0), "bass-1": ("Grit Blend", 0), "keys-1": ("Under", -6), "drums-1": ("Tight", 0)}),
        ("C", "Melody", {"guitar-1": ("Hero Lead", 3), "bass-1": ("Grit Blend", 0), "keys-1": ("Sky Pad", -4), "drums-1": ("Punch", 0)}),
        ("D", "Harmony", {"guitar-1": ("Harmony Lead", 3), "bass-1": ("Full Stack", 0), "keys-1": ("Shimmer Rise", -2), "drums-1": ("Roomy", 0)}),
        ("E", "Wah Outro", {"guitar-1": ("Vocal Wah", 3), "bass-1": ("Grit Blend", 0), "keys-1": ("Bright", -4), "drums-1": ("Punch", 0)})],
        {6: [("guitar-1", "ts")], 7: [("guitar-1", "harm")], 8: [("guitar-1", "wah")]}, "#0081a7",
        gen=[drums_service(["rock-intro", "rock-verse", "rock-chorus", "rock-solo", "rock-fill", "rock-end"])]))
    PRESETS.append(preset("factory-groove-metal", "Iron Thicket", "metal", 132, [
        ("guitar-1", "Guitar 1", "guitar", "factory-guitar-groove-metal", False, 1),
        ("guitar-2", "Guitar 2", "guitar", "factory-guitar-squeal-lead", False, 2),
        ("bass-1", "Bass", "bass", "factory-bass-metal-grind", False, 1),
        ("keys-1", "Pad", "keys", "factory-keys-dark-pad", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-metal-scream", False, 1),
        ("drums-1", "Drums", "drums", "factory-drums-metal", True, None)], [
        ("A", "Clean Intro", {"guitar-1": ("Clean Chorus", 0), "guitar-2": ("Flanged Riff", -10), "bass-1": ("Clean Low", 0), "keys-1": ("Dark Pad", -4), "voice-1": ("Clean Shout", -10), "drums-1": ("Clean Intro", 0)}),
        ("B", "Groove Riff", {"guitar-1": ("Southern Riff", 0), "guitar-2": ("Flanged Riff", -2), "bass-1": ("Grind", 0), "keys-1": ("Low Drone", -10), "voice-1": ("Scream", 0), "drums-1": ("Tight", 0)}),
        ("C", "Breakdown", {"guitar-1": ("Chug Breakdown", 0), "guitar-2": ("Flanged Riff", -3), "bass-1": ("Tight", 0), "keys-1": ("Low Drone", -10), "voice-1": ("Growl", 0), "drums-1": ("Breakdown", 0)}),
        ("D", "Squeal Solo", {"guitar-1": ("Scooped Wall", -3), "guitar-2": ("Octave Squeal", 3), "bass-1": ("Grind", 0), "keys-1": ("Dark Pad", -8), "voice-1": ("Scream", -10), "drums-1": ("Blast", 0)}),
        ("E", "Wah Solo", {"guitar-1": ("Scooped Wall", -3), "guitar-2": ("Wah Lead", 3), "bass-1": ("Grind", 0), "keys-1": ("Dark Pad", -8), "voice-1": ("Megaphone", -6), "drums-1": ("Blast", 0)})],
        {6: [("guitar-1", "boost")], 7: [("guitar-2", "whammy")], 8: [("guitar-2", "wah")]}, "#6a040f",
        gen=[drums_service(["half-time", "metal-breakdown", "metal-fill"], kit="drums-aasimonster")]))
    PRESETS.append(preset("factory-glass-ambient", "Paper Satellites", "alternative", 86, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-glass-ambient", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-synth-ambient", False, 1),
        ("keys-1", "Rhodes", "keys", "factory-keys-glass-rhodes", True, None),
        ("keys-pads-1", "Pads", "keys-pads", "factory-keys-electro-pads", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-ethereal", False, 1),
        ("drums-1", "Drums", "drums", "factory-drums-lofi", True, None)], [
        ("A", "Glass Intro", {"guitar-1": ("Glass Clean", 0), "bass-1": ("Round", -2), "keys-1": ("Glass Rhodes", 0), "keys-pads-1": ("Beat", -4), "voice-1": ("Ethereal", 0), "drums-1": ("Tape Kit", 0)}),
        ("B", "Verse", {"guitar-1": ("Tape Echo", -2), "bass-1": ("Synth Bass", 0), "keys-1": ("Dry Keys", -3), "keys-pads-1": ("Crushed Beat", 0), "voice-1": ("Close", 0), "drums-1": ("Crushed", 0)}),
        ("C", "Burst", {"guitar-1": ("Crunch Burst", 1), "bass-1": ("Tape Fuzz", 0), "keys-1": ("Tape Rhodes", -4), "keys-pads-1": ("Tape Beat", 0), "voice-1": ("Ethereal", 0), "drums-1": ("Dry", 0)}),
        ("D", "Frozen", {"guitar-1": ("Frozen Pad", 0), "bass-1": ("Sub Octave", 0), "keys-1": ("Underwater", 0), "keys-pads-1": ("Dub Beat", -2), "voice-1": ("Cloud", 0), "drums-1": ("Dusty", 0)}),
        ("E", "Glitch Out", {"guitar-1": ("Ring Glitch", 0), "bass-1": ("Synth Bass", 0), "keys-1": ("Glass Rhodes", -3), "keys-pads-1": ("Crushed Beat", 0), "voice-1": ("Robot Falsetto", 0), "drums-1": ("Crushed", 0)})],
        {6: [("guitar-1", "ds1")], 7: [("guitar-1", "trem")], 8: [("voice-1", "tune")]}, "#118ab2",
        gen=[drums_service(["lofi", "boom-bap"])]))
    PRESETS.append(preset("factory-loop-indie", "Room With Echoes", "indie", 104, [
        ("keys-pads-1", "Synth & Beat", "keys-pads", "factory-keys-loop-synth", True, None),
        ("guitar-1", "Guitar", "guitar", "factory-guitar-loop-indie", False, 1),
        ("voice-1", "Voice", "voice", "factory-voice-indie-double", False, 1)], [
        ("A", "Beat", {"keys-pads-1": ("Bass & Beat", 0), "guitar-1": ("Jangle", 0), "voice-1": ("Single", 0)}),
        ("B", "Layer", {"keys-pads-1": ("Bass & Beat", 0), "guitar-1": ("Dotted Echo", 0), "voice-1": ("Double", 0)}),
        ("C", "Push", {"keys-pads-1": ("Big Drop", 0), "guitar-1": ("Klon Push", 0), "voice-1": ("Shout", 1)}),
        ("D", "Breathe", {"keys-pads-1": ("Filtered", 0), "guitar-1": ("Swell Pad", 0), "voice-1": ("Slap", 0)})],
        {6: [("guitar-1", "klon")], 7: [("guitar-1", "dly")], 8: [("voice-1", "double")]}, "#06d6a0",
        gen=[{"type": "looper", "id": "looper", "foot": 10, "params": {"loops": [
            {"sw": 1, "src": "keys-pads-1", "label": "Beat"}, {"sw": 2, "src": "guitar-1", "label": "Guitar"},
            {"sw": 3, "src": "voice-1", "label": "Voice"}, {"sw": 4, "src": "guitar-1", "label": "Guitar 2"}], "length": "free"}}]))
    PRESETS.append(preset("factory-fuzz-grunge", "Velvet Wasp", "grunge", 118, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-fuzz-grunge", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-fuzz", False, 1),
        ("keys-1", "Strings", "keys", "factory-keys-strings-wash", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-grunge-raw", False, 1),
        ("drums-1", "Drums", "drums", "factory-drums-studio-rock", True, None)], [
        ("A", "Quiet Verse", {"guitar-1": ("Verse Crunch", 0), "bass-1": ("Clean Verse", 0), "keys-1": ("Thin", -6), "voice-1": ("Quiet Verse", 0), "drums-1": ("Tight", 0)}),
        ("B", "Loud Chorus", {"guitar-1": ("Fuzz Wall", 0), "bass-1": ("Fuzz Bass", 0), "keys-1": ("Strings Wash", -4), "voice-1": ("Gravel", 1), "drums-1": ("Punch", 0)}),
        ("C", "Solo", {"guitar-1": ("Fuzz Lead", 3), "bass-1": ("Wall", 0), "keys-1": ("Big Swell", -4), "voice-1": ("Raw", -10), "drums-1": ("Punch", 0)}),
        ("D", "Bridge", {"guitar-1": ("Phased Bridge", 0), "bass-1": ("Pick Drive", 0), "keys-1": ("Chorus Strings", -3), "voice-1": ("Raw", 0), "drums-1": ("Roomy", 0)}),
        ("E", "Jet Outro", {"guitar-1": ("Jet Clean", 0), "bass-1": ("Clean Verse", 0), "keys-1": ("Big Swell", -2), "voice-1": ("Scream", 1), "drums-1": ("Roomy", 0)})],
        {6: [("guitar-1", "muff")], 7: [("guitar-1", "phase")], 8: [("guitar-1", "flange")]}, "#9c6644",
        gen=[drums_service(["rock-8", "rock-chorus", "rock-fill"])]))
    PRESETS.append(preset("factory-funk-rock", "Sunset Ladder", "funk", 98, [
        ("guitar-1", "Clean Guitar", "guitar", "factory-guitar-funk-clean", False, 1),
        ("guitar-2", "Drive Guitar", "guitar", "factory-guitar-funk-drive", False, 2),
        ("bass-1", "Bass", "bass", "factory-bass-funk-slap", False, 1),
        ("keys-1", "Clav", "keys", "factory-keys-funk-clav", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-funk-rap", False, 1)], [
        ("A", "Groove", {"guitar-1": ("Chop", 0), "guitar-2": ("Crunch Rhythm", -10), "bass-1": ("Slap", 0), "keys-1": ("Clav", -2), "voice-1": ("Rap", 0)}),
        ("B", "Verse", {"guitar-1": ("Envelope", 0), "guitar-2": ("Crunch Rhythm", -10), "bass-1": ("Fingers Pocket", 0), "keys-1": ("Envelope Clav", -3), "voice-1": ("Phone Verse", 0)}),
        ("C", "Chorus", {"guitar-1": ("Neck Chords", -2), "guitar-2": ("Dirty Chords", 0), "bass-1": ("Octave Funk", 0), "keys-1": ("Stab", -2), "voice-1": ("Chorus Double", 1)}),
        ("D", "Wah Solo", {"guitar-1": ("Chop", -4), "guitar-2": ("Wah Lead", 3), "bass-1": ("Fingers Pocket", 0), "keys-1": ("Clav", -6), "voice-1": ("Rap", -10)}),
        ("E", "Fuzz Solo", {"guitar-1": ("Swirl", -4), "guitar-2": ("Fuzz Solo", 3), "bass-1": ("Solo Pop", 0), "keys-1": ("Phased", -6), "voice-1": ("Slap Hook", -10)})],
        {6: [("guitar-1", "env")], 7: [("guitar-2", "wah")], 8: [("guitar-2", "ds1")]}, "#ef476f",
        gen=[drums_service(["funk-16"])]))
    nu = preset("factory-nu-metal-eight", "Low Tide", "metal", 120, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-eight-string-nu", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-nu-low", False, 1),
        ("keys-1", "Synth", "keys", "factory-keys-nu-pad", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-whisper-scream", False, 1)], [
        ("A", "Dream Clean", {"guitar-1": ("Dream Clean", 0), "bass-1": ("Chorus Low", -2), "keys-1": ("Haze", -2), "voice-1": ("Whisper", 0)}),
        ("B", "Whisper Verse", {"guitar-1": ("Whisper Clean", -1), "bass-1": ("Clean Low", 0), "keys-1": ("Glitch Haze", -3), "voice-1": ("Dream", 0)}),
        ("C", "Heavy Low", {"guitar-1": ("Heavy Low", 0), "bass-1": ("Heavy Blend", 0), "keys-1": ("Low Haze", -8), "voice-1": ("Scream", 1)}),
        ("D", "Shoegaze Wall", {"guitar-1": ("Shoegaze Wall", 0), "bass-1": ("Grind Only", -1), "keys-1": ("Open Haze", -4), "voice-1": ("Dream", 1)}),
        ("E", "Octave Dive", {"guitar-1": ("Octave Dive", 2), "bass-1": ("Heavy Blend", 0), "keys-1": ("Haze", -6), "voice-1": ("Low Growl", 0)})],
        {6: [("guitar-1", "chorus")], 7: [("guitar-1", "dly")], 8: [("guitar-1", "oct")]}, "#5a189a", arr_foot=9, rec_foot=None,
        gen=[drums_service(["metal-intro", "metal-verse", "metal-chorus", "metal-breakdown", "metal-solo", "metal-fill", "metal-end"])])
    PRESETS.append(nu)
    PRESETS.append(preset("factory-pop-rock", "Paper Promises", "pop", 76, [
        ("guitar-1", "Guitar", "guitar", "factory-guitar-pop-chorus", False, 1),
        ("bass-1", "Bass", "bass", "factory-bass-pop-pick", False, 1),
        ("keys-1", "Piano", "keys", "factory-keys-pop-piano", True, None),
        ("voice-1", "Voice", "voice", "factory-voice-pop-tuned", False, 1),
        ("drums-1", "Drums", "drums", "factory-drums-studio-rock", True, None)], [
        ("A", "Verse", {"guitar-1": ("Verse Clean", 0), "bass-1": ("Pick Verse", 0), "keys-1": ("Ballad Piano", -2), "voice-1": ("Pop Verse", 0), "drums-1": ("Soft", 0)}),
        ("B", "Chorus", {"guitar-1": ("Chorus Crunch", 0), "bass-1": ("Chorus Drive", 0), "keys-1": ("Bright Pop", -3), "voice-1": ("Chorus Double", 1), "drums-1": ("Punch", 0)}),
        ("C", "Nylon Solo", {"guitar-1": ("Nylon Solo", 2), "bass-1": ("Ballad", 0), "keys-1": ("Soft Bed", -4), "voice-1": ("Ballad", -10), "drums-1": ("Soft", 0)}),
        ("D", "Bridge", {"guitar-1": ("Bridge Drive", 0), "bass-1": ("Melodic", 0), "keys-1": ("Echo Piano", -3), "voice-1": ("Ballad", 0), "drums-1": ("Roomy", 0)}),
        ("E", "Outro", {"guitar-1": ("Ballad Arp", 0), "bass-1": ("Ballad", 0), "keys-1": ("Ballad Piano", 0), "voice-1": ("Ballad", 0), "drums-1": ("Soft", 0)})],
        {6: [("guitar-1", "chorus")], 7: [("guitar-1", "dly")], 8: [("voice-1", "double")]}, "#ffb703",
        gen=[drums_service(["rock-8", "rock-chorus", "six-eight"])]))
    PRESETS.append(preset("factory-bass-lab", "Bass Workshop", "funk", 100, [
        ("bass-1", "Bass", "bass", "factory-bass-lab", False, 1),
        ("keys-1", "Pad", "keys", "factory-keys-hero-pad", True, None)], [
        ("A", "Sub", {"bass-1": ("Sub Only", 0), "keys-1": ("Under", -8)}),
        ("B", "Grit", {"bass-1": ("Grit Blend", 0), "keys-1": ("Under", -10)}),
        ("C", "Synth", {"bass-1": ("Synth Layer", 0), "keys-1": ("Sky Pad", -6)}),
        ("D", "Stack", {"bass-1": ("Full Stack", 0), "keys-1": ("Under", -8)}),
        ("E", "Solo", {"bass-1": ("Solo Chorus", 3), "keys-1": ("Sky Pad", -6)})],
        {6: [("bass-1", "chorus")]}, "#00b4d8", gen=[drums_service(["funk-16", "boom-bap"])]))
    return nu


# ══ BANQUES, SETLIST, CHANSON ════════════════════════════════════════════════════════════════════════════════════
BANK_NAMES = {"guitar": "Factory Guitar", "bass": "Factory Bass", "keys": "Factory Keys", "voice": "Factory Voice", "drums": "Factory Drums"}


def banks():
    for role, title in BANK_NAMES.items():
        mine = [d for d in PATCHES.values() if (d["role"] if d["role"] != "keys-pads" else "keys") == role]
        lines = [{"id": f"r:factory-{role}:{d['id'].split('-', 2)[-1]}", "rev": 1, "title": d["name"], "patch": d["id"]} for d in mine]
        _dump(f"setlists/factory-{role}.json", {"id": f"factory-{role}", "name": title, "fcb": True, "rev": 4, "kind": "sounds",
                                                 "origin": "factory", "factory": True, "lines": lines,
                                                 "presets": ["patch:" + ln["patch"] for ln in lines]})


# les morceaux FICTIFS de la setlist d'usine : titre, preset, BPM, tonalité (aucun titre réel) — noms proposés par le plan
# de golem.fm (2026-11-16, conception/plan-factory-golem-fx.json), le plan seul porte les inspirations
SONGS = [("Rooftop Prowl", "factory-jazz-club", 160, "F"), ("Rail Yard Shuffle", "factory-texas-blues", 112, "E"),
         ("Harbour Rain", "factory-blues-ballad", 68, "Cm"), ("Velvet Ossuary", "factory-ambient-djent", 94, "F#m"),
         ("Glass Summit", "factory-hero-instrumental", 120, "E"), ("Iron Thicket", "factory-groove-metal", 132, "Eb"),
         ("Paper Satellites", "factory-glass-ambient", 86, "D"), ("Room With Echoes", "factory-loop-indie", 104, "A"),
         ("Velvet Wasp", "factory-fuzz-grunge", 118, "Eb"), ("Sunset Ladder", "factory-funk-rock", 98, "Em"),
         ("Paper Promises", "factory-pop-rock", 76, "Cm"), ("Low End Workshop", "factory-bass-lab", 100, "D")]


# Golem Rising, refaite sur le preset nu metal 8 cordes : même forme (13 parties, 57 mesures), d'autres sons
INTRO, VERSE, CHORUS, BREAKDOWN, SOLO, FILL, END = range(7)
RISING = [  # nom, mesures, scène, groove, bascules {(lane, id de bloc du patch): on}
    ("Intro", 4, "A", INTRO, {("keys-1", "glitch"): True}),
    ("Verse 1", 7, "B", VERSE, {("guitar-1", "chorus"): True}),
    ("Fill", 1, None, FILL, {("guitar-1", "oct"): True, ("voice-1", "scream"): True}),
    ("Chorus", 8, "D", CHORUS, {("guitar-1", "dly"): True}),
    ("Verse 2", 7, "C", BREAKDOWN, {("bass-1", "chorus"): False}),
    ("Fill", 1, None, FILL, {("guitar-1", "oct"): True, ("voice-1", "scream"): True}),
    ("Chorus", 7, "D", CHORUS, {("voice-1", "formant"): True}),
    ("Fill", 1, None, FILL, {("guitar-1", "dly"): True, ("voice-1", "scream"): True}),
    ("Solo", 4, "E", SOLO, {("guitar-1", "chorus"): True}),
    ("Solo · climb", 4, None, None, {("guitar-1", "dly"): True}),
    ("Chorus", 8, "D", CHORUS, {("voice-1", "formant"): True, ("keys-1", "glitch"): True}),
    ("Outro", 4, "C", BREAKDOWN, {("voice-1", "scream"): True}),
    ("End", 1, None, END, {("guitar-1", "dly"): True, ("keys-1", "glitch"): True}),
]
TITLE = "Golem Rising"
SONG_ID = "rs:" + hashlib.sha256(b"golem-factory|golem-rising").hexdigest()[:32]


def _rising_sheet(nu):
    # l'id d'un bloc DANS LE PRESET (après le dépôt) : retrouvé par son id dans le patch
    ids = {}
    for L in nu["lanes"]:
        src = (L.get("patch_from") or {}).get("id")
        src_ids = [b["id"] for b in lane_blocks(PATCHES[src]["lanes"][0]["chain"])]
        got = [b["id"] for b in lane_blocks(L.get("chain"))]
        ids[L["id"]] = dict(zip(src_ids, got))
    secs = []
    for name, bars, scene, groove, toggles in RISING:
        s = {"name": name, "bars": bars}
        if scene:
            s["scene"] = scene
        if groove is not None:
            s["drums"] = groove
        bl = {}
        for (lid, bid), on in toggles.items():
            real = ids[lid].get(bid)
            assert real, f"Golem Rising {name} : {lid}/{bid} absent"
            bl[real] = on
        if bl:
            s["blocks"] = bl
        secs.append(s)
    return {"preset": nu["id"], "bpm": 120, "tuning": "Standard",
            "arrangement": {"type": "arrangement", "id": "arr-song", "params": {
                "advance": "bars", "sig": {"num": 4, "den": 4}, "count_in": 1,
                "starts": {"drums": True, "click": False, "backing": False}, "sections": secs}}}


def setlist(nu):
    lines = [{"id": f"r:factory:{i}", "rev": 1, "preset": p, "title": t, "bpm": bpm, "key": k} for i, (t, p, bpm, k) in enumerate(SONGS)]
    sheet = _rising_sheet(nu)
    lines.append({"id": f"r:factory:{len(SONGS)}", "rev": 1, "band_song": SONG_ID, "title": TITLE, "key": "F#m", **sheet})
    _dump("setlists/factory.json", {"id": "factory", "name": "Factory Golem", "fcb": True, "rev": 3, "kind": "songs",
                                    "presets": [ln["preset"] for ln in lines], "origin": "factory", "factory": True, "lines": lines})
    return sheet


def song_file(sheet):
    """Le .golem de Golem Rising, ses images reprises du fichier livré (tools/gen-factory-song-art.py les a faites)."""
    from bridge import golemfile as GF
    from bridge import songs as SG
    out = os.path.join(FACTORY, "songs", SG._safe(SONG_ID) + ".golem")
    art = {n: GF.read_member(out, f"art/{n}.jpg") for n in ("cover", "band")}
    clean = SG.clean_sheet(sheet)
    assert clean.get("arrangement", {}).get("params", {}).get("sections") == sheet["arrangement"]["params"]["sections"], \
        "la fiche ne survit pas à songs.clean_sheet"
    m = {"format": GF.FORMAT, "type": "song", "id": SONG_ID, "title": TITLE, "artist": "golem",
         "genres": [{"family": "metal", "subgenre": None}], "credits": {"work": {"composers": ["golem"]}},
         "kind": "original", "rights": {"work": "own"},
         "recording": {"duration_ms": round(sum(x[1] for x in RISING) * 4 * 60000 / 120)},
         "repertoire": {"rev": 2}, "files": {"art/cover.jpg": {"role": "cover"}, "art/band.jpg": {"role": "band"}}}
    GF.write(out, m, {"art/cover.jpg": art["cover"], "art/band.jpg": art["band"],
                      "sheet.json": json.dumps(clean, ensure_ascii=False, indent=1).encode("utf-8")})
    GF.verify(out)
    return out


# LA DISTRIBUTION DES DÉMOS (docs/preset-preview.md §1) : la DI que joue chaque scène — un clair joue la DI clean (funk :
# la DI funk), un riff la DI de son gain (crunch, high-gain, djent = la 8 cordes), seule une vraie scène de solo prend une
# DI lead (lead-clean derrière un ampli clair). Les patches basse, voix, claviers et batterie suivent la règle automatique.
CASTING = {
    "factory-guitar-jazz-box": {"A": "guitar/clean", "B": "guitar/clean", "C": "guitar/lead-clean", "D": "guitar/clean", "E": "guitar/clean"},
    "factory-guitar-texas-shuffle": {"A": "guitar/clean", "B": "guitar/crunch", "C": "guitar/lead", "D": "guitar/clean", "E": "guitar/lead"},
    "factory-guitar-wailing-blues": {"A": "guitar/clean", "B": "guitar/crunch", "C": "guitar/lead", "D": "guitar/lead", "E": "guitar/crunch"},
    "factory-guitar-ambient-djent": {"A": "guitar/clean", "B": "guitar/clean", "C": "guitar/djent", "D": "guitar/djent", "E": "guitar/lead"},
    "factory-guitar-hero-lead": {"A": "guitar/clean", "B": "guitar/crunch", "C": "guitar/lead", "D": "guitar/lead", "E": "guitar/lead"},
    "factory-guitar-groove-metal": {"A": "guitar/high-gain", "B": "guitar/high-gain", "C": "guitar/high-gain", "D": "guitar/clean", "E": "guitar/lead"},
    "factory-guitar-squeal-lead": {"A": "guitar/lead", "B": "guitar/lead", "C": "guitar/lead", "D": "guitar/high-gain", "E": "guitar/lead"},
    "factory-guitar-glass-ambient": {"A": "guitar/clean", "B": "guitar/crunch", "C": "guitar/clean", "D": "guitar/clean", "E": "guitar/clean"},
    "factory-guitar-loop-indie": {"A": "guitar/clean", "B": "guitar/clean", "C": "guitar/crunch", "D": "guitar/clean", "E": "guitar/lead-clean"},
    "factory-guitar-fuzz-grunge": {"A": "guitar/crunch", "B": "guitar/crunch", "C": "guitar/lead", "D": "guitar/crunch", "E": "guitar/clean"},
    "factory-guitar-funk-clean": {"A": "guitar/funk", "B": "guitar/clean", "C": "guitar/funk", "D": "guitar/funk", "E": "guitar/clean"},
    "factory-guitar-funk-drive": {"A": "guitar/crunch", "B": "guitar/crunch", "C": "guitar/lead", "D": "guitar/lead", "E": "guitar/crunch"},
    "factory-guitar-eight-string-nu": {"A": "guitar/clean", "B": "guitar/clean", "C": "guitar/djent", "D": "guitar/djent", "E": "guitar/djent"},
    "factory-guitar-pop-chorus": {"A": "guitar/clean", "B": "guitar/crunch", "C": "guitar/lead-clean", "D": "guitar/clean", "E": "guitar/crunch"},
    # LA BASSE (2026-11-16, décidé par le mainteneur) : `finger` sur les riffs jazz et metal aux doigts, `pick` sur le rock et
    # le metal, `sustain` (notes longues) sur tout le reste. Une exception voulue : Funk Slap garde le riff aux doigts
    # sur ses scènes à attaque (un filtre d'enveloppe ne s'ouvre pas sur une note tenue).
    "factory-bass-upright-jazz": {"A": "bass/finger", "B": "bass/sustain", "C": "bass/finger", "D": "bass/finger"},
    "factory-bass-blues-round": {"A": "bass/sustain", "B": "bass/pick", "C": "bass/sustain", "D": "bass/pick"},
    "factory-bass-prog-biamp": {"A": "bass/sustain", "B": "bass/finger", "C": "bass/finger", "D": "bass/pick"},
    "factory-bass-metal-grind": {"A": "bass/pick", "B": "bass/finger", "C": "bass/sustain", "D": "bass/pick"},
    "factory-bass-synth-ambient": {"A": "bass/sustain", "B": "bass/sustain", "C": "bass/sustain", "D": "bass/finger"},
    "factory-bass-fuzz": {"A": "bass/pick", "B": "bass/pick", "C": "bass/sustain", "D": "bass/pick"},
    "factory-bass-funk-slap": {"A": "bass/finger", "B": "bass/finger", "C": "bass/finger", "D": "bass/finger", "E": "bass/sustain"},
    "factory-bass-nu-low": {"A": "bass/sustain", "B": "bass/finger", "C": "bass/pick", "D": "bass/sustain"},
    "factory-bass-pop-pick": {"A": "bass/pick", "B": "bass/pick", "C": "bass/sustain", "D": "bass/sustain", "E": "bass/sustain"},
    "factory-bass-lab": {"A": "bass/sustain", "B": "bass/finger", "C": "bass/sustain", "D": "bass/pick", "E": "bass/sustain"},
}


def casting():
    old = _load("demo-casting.json")
    for pid, scenes in CASTING.items():
        assert set(scenes) <= {s["id"] for s in PATCHES[pid]["scenes"]}, pid
    _dump("demo-casting.json", {"_comment": old.get("_comment"), "patches": CASTING})


def wipe():
    """Efface les anciens patches, presets et setlists d'usine (livrés ET posés localement par l'ancienne usine, tant
    qu'ils sont intacts : les copies locales modifiées ne sont jamais touchées — c'est bridge/factory.py qui décide)."""
    for kind in ("patches", "presets", "setlists"):
        for f in glob.glob(os.path.join(FACTORY, kind, "*.json")):
            os.remove(f)


GUITAR = [g_jazz_box, g_texas_shuffle, g_wailing_blues, g_ambient_djent, g_hero_lead, g_groove_metal, g_squeal_lead,
          g_glass_ambient, g_loop_indie, g_fuzz_grunge, g_funk_clean, g_funk_drive, g_eight_string_nu, g_pop_chorus, g_gypsy_acoustic]
BASS = [b_upright_jazz, b_blues_round, b_prog_biamp, b_metal_grind, b_synth_ambient, b_fuzz_bass, b_funk_slap, b_nu_low, b_pop_pick, b_lab]
KEYS = [k_jazz_piano, k_blues_organ, k_cathedral_piano, k_hero_pad, k_dark_pad, k_glass_rhodes, k_electro_pads, k_loop_synth,
        k_strings_wash, k_funk_clav, k_nu_pad, k_pop_piano]
VOICE = [v_karaoke, v_crooner, v_blues_shout, v_halo, v_metal_scream, v_ethereal, v_indie_double, v_grunge_raw, v_funk_rap, v_whisper_scream, v_pop_tuned]
DRUMS = [d_brushes, d_vintage, d_studio, d_metal, d_lofi]

def guard_edits():
    """Refuse de tourner quand un patch d'usine a été RETOUCHÉ sur ce rack (2026-11-16) : `patch()` réécrit la copie
    locale library/patches/<id>.json, donc relancer le générateur effaçait un son réglé à l'oreille dans le Designer.
    On reporte d'abord la retouche ici (ou on la sauve ailleurs), puis `--overwrite-edits`."""
    import sys
    from bridge import factory
    def _same(pid):                                        # déjà validé tel quel : le régénérer ne perd rien
        v = _validated(pid)
        d = json.load(open(os.path.join(ROOT, "library", "patches", pid + ".json"), encoding="utf-8"))
        return bool(v) and (v["chain"], v["states"], v["scenes"]) == (d["lanes"][0]["chain"], d["lanes"][0].get("states") or [], d["scenes"])
    mine = [e for e in factory.edited() if e["kind"] == "patches" and not _same(e["id"])]
    if mine and "--overwrite-edits" not in sys.argv:
        names = ", ".join(e["name"] for e in mine)
        sys.exit(f"make-factory : {len(mine)} patch(es) d'usine retouché(s) sur ce rack — {names}.\n"
                 "Les régénérer les effacerait : les valider (--validate [id…]) ou les abandonner (--overwrite-edits).")


if __name__ == "__main__":
    import sys as _sys
    if "--validate" in _sys.argv:
        validate([a for a in _sys.argv[1:] if not a.startswith("--")])
    guard_edits()
    wipe()
    for fn in GUITAR + BASS + KEYS + VOICE + DRUMS:
        fn()
    banks()
    casting()
    nu = presets()
    sheet = setlist(nu)
    print(os.path.relpath(song_file(sheet), ROOT))
    print(f"{len(PATCHES)} patches, {len(PRESETS)} presets, {len(SONGS) + 1} songs")
    for d in PATCHES.values():
        if d.get("unresolved"):
            print(f"  ⚠ {d['name']} : {len(d['unresolved'])} référence(s) non résolue(s) : {d['unresolved'][:2]}")
