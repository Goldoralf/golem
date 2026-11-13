# SPDX-License-Identifier: GPL-3.0-or-later
"""
GoleM — modèle rig « clean » (paths + splits) — le cœur data du pipeline actif.

Un preset = des PATHS nommés. Chaque path : une entrée physique -> une chaîne (avec AU PLUS un
split) -> une ou plusieurs sorties physiques. Pas de profils de lieu : le routage IN/OUT vit dans
le preset (choisi dans le Designer). Un fallback mono global (io.json.mono_fallback) peut replier
tout sur OUT1 au moment du routage (appliqué par golem, pas ici).

Split :
  merge = {gain}  -> branches sommées ; la chaîne CONTINUE jusqu'à path.out (blend, 1 sortie).
  merge = null    -> fan-out : chaque branche a sa propre .out ; le split TERMINE le path.

Contraintes de sortie (les pistes de tous les paths sont unmute ENSEMBLE par une scène) :
  - une sortie physique n'est assignée qu'une fois (pas de sommation accidentelle) ;
  - jamais plus de sorties qu'il n'y en a physiquement (out_count).

Pur Python, testable sans Reaper.
"""
import copy
import json
import os
import re
import sys

from .golog import get

log = get("rig")


class RigError(ValueError):
    pass


def is_split(node):
    return isinstance(node, dict) and "split" in node


def _path_blocks(path):
    for node in path.get("chain", []):
        if is_split(node):
            for br in node["split"].get("branches", []):
                for b in br.get("blocks", []):
                    yield b
        else:
            yield node


def iter_blocks(preset):
    for p in preset.get("paths", []):
        yield from _path_blocks(p)


def looper_enabled(preset):
    """Mode looper d'un preset (docs/blocks-doctrine.md) : la PRÉSENCE d'un bloc
    `looper` (marqueur, foot_mode transport) — ou le flag legacy preset.looper.enabled
    (anciens presets, jamais réécrit de force). Marche sur les deux formes de preset
    (Designer guitar/voice/keys OU paths compilé)."""
    if bool(((preset or {}).get("looper") or {}).get("enabled")):
        return True

    def _walk(o):
        if isinstance(o, dict):
            if o.get("type") == "looper":
                return True
            return any(_walk(v) for v in o.values())
        if isinstance(o, list):
            return any(_walk(v) for v in o)
        return False

    p = dict(preset or {})
    p.pop("looper", None)
    return _walk({k: v for k, v in p.items() if k in ("guitar", "voice", "keys", "paths", "config")})


def looper_loops(preset):
    """Table de boucles du preset (docs/looper.md §1) : [{sw, src, label}], l'ORDRE fait le slot.
    Lue sur les params du bloc `looper` ; à défaut sur le flag legacy `preset.looper.loops`.
    Absente -> la table par DÉFAUT (1/2/3 -> lanes 1/2/k), jamais écrite dans le fichier."""
    from . import looper as _lp

    found = []

    def _walk(o):
        if isinstance(o, dict):
            if o.get("type") == "looper":
                found.append((o.get("params") or {}).get("loops"))
                return
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk({k: v for k, v in (preset or {}).items()
           if k in ("guitar", "voice", "keys", "paths", "config")})
    raw = next((f for f in found if f), None)
    if raw is None:
        raw = ((preset or {}).get("looper") or {}).get("loops")
    return _lp.normalize_loops(raw)


def path_outputs(path):
    """Sorties physiques utilisées par un path : branches d'un fan-out, sinon la sortie terminale."""
    outs, fanned = [], False
    for node in path.get("chain", []):
        if is_split(node) and node["split"].get("merge") is None:
            fanned = True
            outs += [br["out"] for br in node["split"].get("branches", []) if br.get("out") is not None]
    if not fanned and path.get("out") is not None:
        outs.append(path["out"])
    return outs


def _assign_ids(preset):
    """id unique par bloc (type, type2, type3…) — clé des toggles de scène + du push param live."""
    seen = {b["id"] for b in iter_blocks(preset) if b.get("id")}
    for b in iter_blocks(preset):
        if not b.get("id"):
            base, cand, n = b.get("type", "blk"), b.get("type", "blk"), 1
            while cand in seen:
                n += 1
                cand = f"{base}{n}"
            b["id"] = cand
            seen.add(cand)


def _check_unique_block_ids(preset):
    ids = [b["id"] for b in iter_blocks(preset)]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        raise RigError("ids de blocs dupliqués : " + ", ".join(dupes))


def _validate_path(path, idx):
    who = f"path '{path.get('id', idx)}'"
    chain = path.get("chain")
    if not isinstance(chain, list):
        raise RigError(f"{who} : 'chain' absente")
    # chain=[] = lane VIDE -> passthrough (piste dry sans FX). Valide tant qu'il y a une sortie (vérifié plus bas).
    if path.get("input") is None:
        raise RigError(f"{who} : 'input' (canal d'entrée) requis")
    splits = [i for i, n in enumerate(chain) if is_split(n)]
    if len(splits) > 1:
        raise RigError(f"{who} : un seul split par path (v1)")
    if not splits:
        if path.get("out") is None:
            raise RigError(f"{who} : 'out' terminal requis (pas de split)")
        return
    si = splits[0]
    sp = chain[si]["split"]
    branches = sp.get("branches") or []
    if len(branches) < 2:
        raise RigError(f"{who} : un split a besoin de >=2 branches")
    if sp.get("merge") is None:                                   # fan-out
        if si != len(chain) - 1:
            raise RigError(f"{who} : un split fan-out (sans merge) doit être le DERNIER noeud du path")
        for j, br in enumerate(branches):
            if br.get("out") is None:
                raise RigError(f"{who} : branche {j} sans 'out' (fan-out)")
    else:                                                         # merge
        for j, br in enumerate(branches):
            if br.get("out") is not None:
                raise RigError(f"{who} : branche {j} porte un 'out' alors que le split merge")
        if path.get("out") is None:
            raise RigError(f"{who} : split merge -> 'out' terminal requis sur le path")


def normalize(preset):
    """Copie normalisée : ids paths/blocs assignés & uniques, structure des splits validée. Lève RigError."""
    p = copy.deepcopy(preset)
    paths = p.get("paths")
    if not paths:
        # la raison vient de scene_bake (`why_empty`) : elle s'affiche — en anglais, avec l'endroit où agir
        raise RigError(p.get("why_empty") or "nothing to play: no lane of this sound can be mounted")
    for i, pp in enumerate(paths):
        pp.setdefault("id", f"path{i + 1}")
        pp.setdefault("name", pp["id"])
        _validate_path(pp, i)
    pids = [pp["id"] for pp in paths]
    if len(pids) != len(set(pids)):
        raise RigError("ids de paths dupliqués")
    _assign_ids(p)
    _check_unique_block_ids(p)
    return p


def out_channels(sel):
    """Les canaux physiques d'un choix de sortie : "1-2" -> [1, 2], "3" -> [3], "NONE"/None -> []."""
    s = str(sel or "")
    if s.isdigit():
        return [int(s)]
    m = re.fullmatch(r"(\d+)-(\d+)", s)
    return [int(m.group(1)), int(m.group(2))] if m else []


def path_out_channels(path):
    """Canaux physiques vers lesquels un path SORT vraiment (out_sel, pas le marqueur `out`) :
    les branches d'un fan-out, sinon la sortie terminale. Défaut 1-2."""
    outs, fanned = [], False
    for node in path.get("chain", []):
        if is_split(node) and node["split"].get("merge") is None:
            fanned = True
            for br in node["split"].get("branches", []):
                outs += out_channels(br.get("out_sel") or "1-2")
    if not fanned:
        outs += out_channels(path.get("out_sel") or "1-2")
    return outs


def validate_routing(preset, out_count):
    """Contraintes de sortie : chaque canal RÉELLEMENT utilisé (out_sel) est dans [1..out_count].
    LOT 5 (audit N lanes) : l'ancienne règle comptait le MARQUEUR `out` (= rang de la lane) et
    exigeait qu'il soit unique — une 3e lane audio, ou la lane claviers (marqueur 3), échouait sur
    une carte à deux sorties alors que tout sortait en 1-2. Deux lanes sur la même sortie se
    SOMMENT dans le hardware send, chacune avec son trim : c'est voulu (lot 2, mixer).
    Lève RigError. Retourne {canal: [path ids]}."""
    used = {}
    for path in preset.get("paths", []):
        for o in path_out_channels(path):
            if o < 1 or o > out_count:
                raise RigError(f"path '{path['id']}' : sortie {o} hors de la carte (1..{out_count})")
            used.setdefault(o, []).append(path["id"])
    return used


PREFIX = "GoleM:"


def _split_index(chain):
    for i, n in enumerate(chain):
        if is_split(n):
            return i
    return -1


_QUARANTINE = None


def quarantined_types():
    """Types de blocs en QUARANTAINE (effects.json `quarantine`) : un plugin qui fait tomber Reaper
    ne doit plus jamais l'atteindre, quel que soit le preset qui le demande (GxDetune, 2026-09-07 :
    tas corrompu, abort au rebuild). La donnée vit dans le catalogue, pas ici.
    Ce qu'on met en quarantaine, c'est un PLUGIN : un type que la table fait jouer par un effet golem-fx (`golem_fx`,
    sous le Golem Engine, et sous REAPER quand le plugin est installé) n'atteint jamais le plugin fautif — il n'y est
    pas en quarantaine (pitch : ReaPitch figeait
    REAPER, gfx-pitch ne fige rien, 2026-11-12). Le moteur actif est relu à chaque appel : il peut changer en route."""
    base = _base_quarantine()
    safe = _engine_safe_types()
    return {t: why for t, why in base.items() if t not in safe} if safe else base


def _engine_safe_types():
    """Les types que le moteur ACTIF joue par un effet golem-fx. Golem Engine : sa table. REAPER sous Linux
    (docs/golem-fx-reaper.md) : la MÊME table, pour les plugins golem-fx installés ici (golem_rig.lua ne bascule un
    bloc vers golem-fx que si REAPER connaît le plugin ; sinon il garde son plugin d'origine). Windows / macOS : aucun."""
    try:
        from . import engine
        from .engine import ardour_plan
        eid = getattr(engine.get(), "id", None)
        table = ardour_plan.load_table()
        types = {t for t, spec in table.items() if spec.get("golem_fx")}
        if eid == "ardour":
            return types
        if eid != "reaper" or _platform() in ("win32", "darwin"):
            return set()
        installed = _golem_fx_installed()
        return {t for t in types if table[t].get("vst3") in installed}
    except Exception:
        return set()


def _golem_fx_installed():
    """Les class ids (hex) des VST3 golem-fx présents dans ~/.vst3 — le dossier où tools/golem-fx-install.py les pose
    et que REAPER scanne. Lu dans library/catalog/golem-fx-plugins.json (le nom de chaque bundle)."""
    try:
        from . import config as C
        plugins = json.load(open(os.path.join(C.ROOT, "library", "catalog", "golem-fx-plugins.json"))).get("plugins", {})
    except (OSError, ValueError):
        return set()
    home = os.path.join(os.path.expanduser("~"), ".vst3")
    return {cid for cid, p in plugins.items() if os.path.isdir(os.path.join(home, p.get("name", "") + ".vst3"))}


def _base_quarantine():
    """La quarantaine du catalogue, lue une fois (et ôtée des types qu'un JSFX golem joue sur cet OS)."""
    global _QUARANTINE
    if _QUARANTINE is None:
        try:
            from . import config as C
            data = json.load(open(os.path.join(C.ROOT, "library", "catalog", "effects.json")))
            _QUARANTINE = {e.get("type"): e.get("quarantine") for e in data.get("effects", []) if e.get("quarantine")}
            # ce qu'on met en quarantaine, c'est un PLUGIN : sur un OS où la table joue le type par un JSFX golem
            # (delay-echo → golem_echocat, 2026-10-22), le plugin fautif n'est jamais posé — le type n'y est pas
            # en quarantaine, et le tiroir le propose
            for t in list(_QUARANTINE):
                if str(_desktop_plugin(t) or "").startswith("JS:golem/"):
                    del _QUARANTINE[t]
        except Exception:
            _QUARANTINE = {}
    return _QUARANTINE


def _desktop_plugin(btype):
    """Le plugin que la table de CET OS (effects-windows/macos.json) nomme pour un type ; None ailleurs."""
    if _platform() not in ("win32", "darwin"):
        return None
    try:
        from . import config as C
        name = "effects-windows.json" if _platform() == "win32" else "effects-macos.json"
        data = json.load(open(os.path.join(C.ROOT, "library", "catalog", name), encoding="utf-8"))
        return (data.get("effects", {}).get(btype) or {}).get("plugin")
    except Exception:
        return None


_QUARANTINE_PLUGINS = None


def quarantined_plugin(name):
    """La raison de la quarantaine si <name> — un nom de plugin tel que REAPER le scanne
    (« VST: ReaPitch (Cockos) ») — désigne un PLUGIN mis en quarantaine par le catalogue, sinon None.

    ⚠ La quarantaine est tenue par TYPE DE BLOC (`pitch`, `delay-echo`, `detune`). Le bloc VST Host
    laisse choisir le plugin lui-même : sans cette porte, ReaPitch — qui fige tout le moteur 435 ms —
    redevenait posable par son nom (vu dans le sélecteur le 2026-10-01). Ce qu'on met en quarantaine,
    c'est un plugin ; le type n'en est que l'adresse habituelle."""
    global _QUARANTINE_PLUGINS
    if _QUARANTINE_PLUGINS is None:
        try:
            from . import config as C
            data = json.load(open(os.path.join(C.ROOT, "library", "catalog", "effects.json")))
            _QUARANTINE_PLUGINS = {str(e["plugin"]).casefold(): e["quarantine"]
                                   for e in data.get("effects", []) if e.get("quarantine") and e.get("plugin")}
        except Exception:
            _QUARANTINE_PLUGINS = {}
    bare = re.sub(r"^\s*[A-Za-z0-9]+:\s*", "", str(name or "")).casefold()      # sans « VST3: »
    return next((why for plug, why in _QUARANTINE_PLUGINS.items() if plug and plug in bare), None)


def _trial_done(plugin, ok):
    """Fin d'un essai sur banc : accepté, le brouillon est rejoué (le bloc entre dans le rig) ; refusé, il le reste —
    rejoué quand même, pour que l'écran relise l'état (le bloc dit pourquoi il ne joue pas)."""
    from . import recall
    recall.reapply_sandbox()


def _drop_quarantined(blocks):
    """Retire les blocs en quarantaine d'une liste, en le DISANT (jamais en silence)."""
    q = quarantined_types()
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") in q:
            log.warning(f"bloc {b.get('id') or b.get('type')} ({b.get('type')}) : EN QUARANTAINE, retiré du rig — {q[b['type']]}")
            continue
        why = quarantined_plugin(b.get("plugin")) if isinstance(b, dict) and b.get("type") == "vst-host" else None
        if why:
            log.warning(f"bloc {b.get('id') or 'vst-host'} (vst-host « {b.get('plugin')} ») : plugin EN QUARANTAINE, retiré du rig — {why}")
            continue
        # LE BANC DU PREMIER USAGE (Linux, 2026-11-09, docs/platforms.md §6.1 lot 3) : un plugin jamais essayé ici
        # n'entre pas dans le rig qui joue ; un REAPER séparé l'essaie d'abord, puis le brouillon est rejoué
        if isinstance(b, dict) and b.get("type") == "vst-host" and b.get("plugin"):
            from . import plugin_trial
            why = plugin_trial.failed(b["plugin"])
            if why:
                log.warning(f"bloc {b.get('id') or 'vst-host'} (vst-host « {b['plugin']} ») : REFUSÉ par le banc, retiré du rig — {why}")
                continue
            if plugin_trial.pending(b["plugin"]):
                plugin_trial.start(b["plugin"], on_done=_trial_done)
                log.info(f"bloc {b.get('id') or 'vst-host'} (vst-host « {b['plugin']} ») : essayé d'abord sur un banc, hors du rig")
                continue
        out.append(b)
    return out


# Blocs dont le SON vient d'un fichier : sans capture chargeable, ils n'atténuent pas — ils
# ÉTEIGNENT. Même liste que _prep_block.
# + les captures d'OUTBOARD (2026-09-14, TONE3000 gear=outboard) : préampli et compresseur capturés,
# même plugin NAM, même fichier .nam, même silence si la capture manque.
CAPTURE_TYPES = ("amp", "amp-nam", "cab", "pedal-nam", "preamp-nam", "comp-nam")

# Gain de sommation d'un split quand le document n'en porte pas. UNE convention, écrite partout
# ailleurs (écran du Designer, chemin legacy de scene_bake, preset-schema.md) — ce chemin-ci
# appliquait 0 et faisait mentir l'écran de 3 dB.
MERGE_GAIN_DEFAULT = -3


# Ce que CHAQUE bloc à capture sait charger. Le NAM lit du .nam, le convolver x42 lit une IR
# (.wav) : leur donner l'autre fichier n'est pas une approximation, c'est un plugin qui ne charge
# RIEN — donc une chaîne coupée.
# ⚠ QUATRE blocs, pas trois (2026-09-12, corrigé après golem.fm) : `amp` en fait partie. Il est le
# rig COMPLET en une capture (MODEL_GEARS: amp ← amp-cab) là où `amp-nam` est la tête seule, et il
# charge un .nam comme les autres — plus une IR dans son champ `cab`. Je l'avais exclu en le
# croyant « bundle, on ne juge pas », et un TEST défendait cette exclusion : le bloc le plus muet
# quand sa capture est fausse échappait au détecteur de silences. Un test qui protège un trou est
# pire que pas de test — il le rend invisible à la relecture suivante.
CAPTURE_EXT = {"amp": (".nam",), "amp-nam": (".nam",), "pedal-nam": (".nam",),
               "preamp-nam": (".nam",), "comp-nam": (".nam",),
               "cab": (".wav", ".flac")}
CAB_EXT = CAPTURE_EXT["cab"]


def _wrong_kind(b, path):
    """Le fichier résolu convient-il au bloc ? Rend la raison, ou None si tout va bien.

    ⚠ 2026-09-12, patch « Titan » muet : le bloc `cab` portait `t3k:53952`, une capture
    **amp-cab au format NAM**. La ref RÉSOLVAIT (le tone existe, le fichier est là), donc rien ne
    criait avant la compile — mais le convolver ne charge pas un .nam, et la lane entière se
    taisait. Même famille que « t3k:44209 contre 44209 » : une donnée plausible qui produit un
    silence. Vérifier qu'une ref existe ne dit RIEN sur ce qu'elle contient."""
    if path and str(path).lower().endswith(".gcap") and b.get("type") in ("amp", "amp-nam", "pedal-nam"):
        from .capture_module import load
        try:
            load(path)
            return None
        except (OSError, ValueError, KeyError, TypeError) as e:
            return "invalid capture module: " + str(e)
    exts = CAPTURE_EXT.get(b.get("type"))
    if not exts or not path:
        return None
    if path.lower().endswith(tuple(exts)):
        return _wrong_kind_for_os(path)
    got = os.path.splitext(path)[1].lower() or "?"
    return f"capture {got} sur un bloc qui charge {'/'.join(exts)}"


# ── Une capture A2 ne joue pas hors Linux (mesuré le 2026-10-01) ─────────────────────────────
# Sous Windows et macOS le cœur NAM est le VST3 officiel (compile_rig._native_core_for), et sa
# dernière version PUBLIÉE (0.7.13, déc. 2024) ne lit pas le format A2 (`architecture:
# SlimmableContainer`, arrivé dans NeuralAmpModelerCore en mars 2026) : chargé, il laisse passer la
# guitare À SEC, sans une erreur (docs/audit-2026-10-01-parite-coeurs-os.md §3.1). Sous Linux le NAM
# LV2 d'Oliphant le lit. La NATURE se lit dans le fichier, pas dans son nom (« -a2 » n'est qu'une
# habitude de nommage) : c'est `architecture` qui tranche. À retirer le jour où un NAM qui lit l'A2
# tourne sur ces OS — et seulement après l'avoir mesuré avec tools/check-core-parity.py.
_A2_ARCH = "SlimmableContainer"
_ARCH_CACHE = {}
A2_DESKTOP_WHY = ("A2 capture — this golem's NAM engine cannot play it "
                  "(the guitar would pass through dry)")


def _platform():
    return sys.platform


def nam_architecture(path):
    """`architecture` d'un .nam (WaveNet, LSTM, SlimmableContainer…), None s'il est illisible.
    Gardé par (chemin, date) : la compile repasse sur les mêmes fichiers à chaque preset."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _ARCH_CACHE:
        try:
            with open(path, encoding="utf-8") as f:
                _ARCH_CACHE[key] = json.load(f).get("architecture")
        except (OSError, ValueError, AttributeError):
            _ARCH_CACHE[key] = None
    return _ARCH_CACHE[key]


def _nam_golem_version():
    """La version du NAM bâti par golem posée sur cette machine (témoin écrit par l'installeur), « » sinon."""
    if _platform() == "win32":
        base = os.environ.get("CommonProgramFiles") or r"C:\Program Files\Common Files"
        mark = os.path.join(base, "VST3", "NeuralAmpModeler.vst3", "golem-nam-version.txt")
    elif _platform() == "darwin":
        mark = "/Library/Audio/Plug-Ins/VST3/.golem-nam-version"
    else:
        return ""
    try:
        with open(mark, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def nam_unreadable():
    """Les formats de capture (`architecture` du .nam) que le moteur NAM de CETTE machine ne joue pas.
    Publié au battement (`caps.nam_unreadable`, golem.fm le lit, liste vide comprise) et lu par la
    garde ci-dessous : une seule source. 2026-10-22 : le NAM 0.7.15 bâti par golem lit l'A2 (mesuré :
    A2.nam transforme le son, 0.7.13 le laissait à sec) — là où son témoin est posé, plus rien n'est refusé."""
    if _platform() not in ("win32", "darwin"):
        return []
    v = _nam_golem_version()
    try:
        ok = tuple(int(x) for x in v.split(".")[:3]) >= (0, 7, 14)
    except ValueError:
        ok = False
    return [] if ok else [_A2_ARCH]


def _wrong_kind_for_os(path):
    if path.lower().endswith(".nam") and nam_architecture(path) in nam_unreadable():
        return A2_DESKTOP_WHY
    return None


def stacked_cab(blocks, gear_of):
    """Les amplis qui portent DÉJÀ leur baffle et qu'un `cab` suit quand même — deux baffles en
    série. Rend la liste des ids fautifs.

    ⚠ 2026-09-12, la seule nature que le fichier ne peut PAS trancher : `amp` seul contre
    `amp-cab` sont deux `.nam`, rien ne les distingue au contenu. Elle reste donc DÉCLARÉE, et sa
    source est le `gear` de TONE3000 — c'est-à-dire l'auteur de la capture. golem.fm s'en protège
    à la construction de la lane, mais sa barrière est faible par construction : elle interroge la
    même déclaration. Le rack ne peut pas faire mieux sur la donnée — il peut le DIRE, et il est
    le seul à parler au moment où quelqu'un ENTEND.
    Pourquoi ça vaut un avertissement plutôt qu'un retrait : deux baffles s'entendent comme une
    couverture jetée sur l'ampli, donc comme un mauvais réglage — on cherche des heures dans les
    potards. Mais c'est peut-être voulu (un cab de caractère derrière une capture complète), et on
    ne retire pas un choix. On le nomme."""
    out, pending = [], None
    for b in blocks:
        if not isinstance(b, dict) or b.get("bypass"):
            continue
        t, ref = b.get("type"), b.get("ref")
        if t in ("amp", "amp-nam") and ref:
            pending = b if gear_of(ref) == "amp-cab" else None
        elif t == "cab" and ref and pending is not None:
            out.append(pending.get("id") or "amp")
            pending = None
    return out


def silent_scenes(lane, scenes):
    """Les scènes qui ne laissent AUCUN chemin porteur de son dans cette lane.

    ⚠ 2026-09-12, patch « Hammer » : deux branches, une par son. Le bloc de la branche clean
    n'avait pas de capture — le rack l'a retiré et l'a dit — mais la scène « Clean », elle, MUTE
    l'autre branche. Résultat : en scène A, la seule voie ouverte était une branche VIDE, donc un
    DI brut à ~−40 dBFS : inaudible. Les scènes B/C/D sonnaient parfaitement.
    Personne ne pouvait faire le lien : l'avertissement parlait d'un BLOC, le silence arrivait au
    niveau d'une SCÈNE, et seulement sur l'une d'elles. C'est le même silence que les cinq autres,
    un cran plus haut — et c'est le cran où l'utilisateur, lui, se trouve.
    Rend [{scene, why}]. Une lane sans split n'est jamais concernée."""
    ch = (lane or {}).get("chain") or {}
    branches = ((ch.get("split") or {}).get("branches") or [])
    if not branches:
        return []
    out = []
    for sc in scenes or []:
        # ⚠ `branches` VIDE ({}) renvoyait à `lanes`, où vivent aussi les lanes coupées (band-scenes) : une
        # seule lecture, celle du store, qui ne prend dans `lanes` que les anciens mutes de branche
        from .store import scene_branches
        muted = scene_branches(sc) if isinstance(sc, dict) else {}
        alive = [br for br in branches
                 if not ((muted.get(br.get("id")) or {}).get("mute") is True) and (br.get("blocks") or [])]
        if not alive:
            # NOMMER la branche en cause (repris de golem.fm) : dire « une scène est muette » sans
            # dire laquelle des voies est vide envoie chercher dans les autres, qui vont bien.
            empty = [br.get("id") for br in branches
                     if not (br.get("blocks") or [])
                     and not ((muted.get(br.get("id")) or {}).get("mute") is True)]
            out.append({"scene": (sc or {}).get("id"), "name": (sc or {}).get("name"),
                        "empty_branches": empty,
                        "why": "every branch carrying blocks is muted in this scene — only a bare DI "
                               "reaches the output (inaudible in practice)"
                               + (f"; the branch it keeps open has no block: {', '.join(empty)}" if empty else "")})
    return out


def _drop_empty_capture(blocks, resolve):
    """Retire les blocs à capture dont le fichier ne se résout pas — en le DISANT, jamais en silence.

    ⚠ Un NAM sans modèle et un convolver sans IR ne laissent RIEN passer : le bloc ne colore pas
    le signal, il le COUPE, et toute la branche avec lui. Le laisser en place, c'est livrer un
    silence sans cause — la panne la plus chère de ce projet (ampli ré-instancié vide le
    2026-09-07 ; patch de golem.fm sans une seule `ref` le 2026-09-11, cinq blocs vides, les deux
    branches muettes, et rien pour le dire puisqu'aucun fichier n'était ATTENDU).
    Le bloc reste dans le DOCUMENT — l'intention est conservée, l'écran le montre, il suffit de
    lui donner une capture ; seul le RIG ne le pose pas. Même patron que la quarantaine, et même
    intention que `_render_core_for`, qui ignore déjà un slot ampli/cab sans `ref`."""
    if not resolve:
        return blocks
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") in CAPTURE_TYPES:
            f = resolve(b["ref"], b.get("model")) if b.get("ref") else None
            # une entrée d'index dont le FICHIER a disparu « résolvait » : le NAM se posait sans modèle,
            # muet (docs/block-status.md §3). Un chemin absolu qui n'existe pas n'est pas une capture.
            if f and os.path.isabs(f) and not os.path.isfile(f):
                log.warning(f"bloc {b.get('id') or b.get('type')} ({b.get('type')}) : fichier absent du disque "
                            f"« {f.rsplit('/', 1)[-1]} » — retiré du rig")
                continue
            if not f:
                log.warning(f"bloc {b.get('id') or b.get('type')} ({b.get('type')}) : "
                            + ("capture « %s » introuvable" % b["ref"] if b.get("ref") else "AUCUNE capture")
                            + " — retiré du rig (un bloc à capture vide coupe le son de sa branche)")
                continue
        out.append(b)
    return out


def _usable(blocks, resolve):
    """Les blocs que le rig peut poser : ni en quarantaine, ni à capture vide."""
    return _drop_empty_capture(_drop_quarantined(blocks), resolve)


def _prep_block(b, resolve):
    """Copie d'un bloc pour le plan ; résout les fichiers NAM/IR si un resolver est fourni.
    amp (Ratatouille bundle) : `ref`=NAM -> file, `cab`=IR -> cab_file. amp-nam/cab : `ref` -> file."""
    b = dict(b)
    if resolve:
        if b.get("type") in CAPTURE_TYPES and b.get("ref"):
            f = resolve(b["ref"], b.get("model"))     # model = variante épinglée dans le pack (mic, A2…)
            if f:
                # GARDE de format (doctrine « repli jamais silencieux », docs/input-map.md §7) :
                # un bloc NAM nourri d'un .wav (ex. ref pointant un pack d'IRs — bug voix
                # looper-test 2026-07-19) resterait SANS modèle -> silence inexplicable.
                # Mauvais format => pas de fichier + bloc BYPASSÉ : le signal passe à sec,
                # et le log dit pourquoi.
                bad = _wrong_kind(b, f)
                if not bad:
                    b["file"] = f
                else:
                    b["bypass"] = True
                    b["_wrong_kind"] = bad        # la NATURE, dite : le cœur exclut sur ce marqueur, pas sur le bypass
                    log.warning(f"bloc {b.get('id') or b.get('type')} : '{f.rsplit('/', 1)[-1]}' — {bad}"
                                " — bloc bypassé (il ne fournit plus son fichier au cœur)")
        # ⚠ CHAMP HÉRITÉ, SANS SOURCE (mesuré le 2026-09-12, question de golem.fm) : `cab` sur un
        # bloc `amp` date de l'ère Ratatouille, où le bundle chargeait NAM + IR séparément. Le
        # bloc `amp` est aujourd'hui « Head+Cab (NAM) » : sa capture PORTE déjà le baffle. Aucune
        # UI ne pose ce champ, aucun des 44 blocs amp/amp-nam du dépôt ne le porte, le schéma ne
        # le documente pas et notre propre export l'ignore dans `deps[]`. Le chemin reste (il ne
        # coûte rien et il est gardé), mais il ne décrit plus l'époque : ne pas le lire comme un
        # usage courant — c'est exactement le genre de commentaire périmé qui m'a fait exclure le
        # bloc `amp` de la garde de format en le croyant « un bundle ».
        if b.get("type") == "amp" and b.get("cab"):
            cf = resolve(b["cab"], None)
            if cf and not cf.lower().endswith(CAB_EXT):
                # même règle que pour un bloc `cab` : un convolver ne charge pas un .nam. On ne
                # pose pas le fichier — l'ampli garde sa capture et tombera sur le cab par défaut.
                log.warning(f"bloc {b.get('id') or 'amp'} : cab '{cf.rsplit('/', 1)[-1]}' "
                            f"n'est pas une IR ({'/'.join(CAB_EXT)}) — ignoré")
            elif cf:
                b["cab_file"] = cf
    return b


def _path_tracks(path, resolve):
    """Traduit un path en liste de pistes (role/input/blocks/routing) pour golem.
    `path.level` (dB, optionnel) est porté sur la/les piste(s) de SORTIE (D_VOL côté golem)."""
    pid = path["id"]
    base = PREFIX + pid
    chain = path["chain"]
    si = _split_index(chain)
    level = path.get("level")
    out_sel = path.get("out_sel")
    tracks = []

    if si < 0:                                                   # linéaire : 1 piste
        tracks.append({"role": "main", "name": base, "input": path["input"],
                       "blocks": [_prep_block(b, resolve) for b in _usable(chain, resolve)],
                       "out": path.get("out"), "level": level, "out_sel": out_sel})
        if path.get("midi"):                                     # lane Keys / Drums : entrée = contrôleur MIDI
            tracks[-1]["midi"] = True
            tracks[-1]["midi_role"], tracks[-1]["in_sel"] = path.get("midi_role"), path.get("in_sel")
        if path.get("stereo"):                                   # paire stéréo (lot 5) : I_RECINPUT en paire
            tracks[-1]["stereo"] = True
        return tracks

    pre = [_prep_block(b, resolve) for b in _usable(chain[:si], resolve)]
    sp = chain[si]["split"]
    branches = sp["branches"]
    bnames = [f"{base}/{br.get('id') or ('b' + str(j + 1))}" for j, br in enumerate(branches)]

    # piste PRE (partagée) : entrée physique, blocs avant le split, envoie aux branches, pas de sortie directe
    tracks.append({"role": "pre", "name": base, "input": path["input"],
                   "blocks": pre, "sends_to": bnames, "out": None,
                   **({"stereo": True} if path.get("stereo") else {}),
                   # une lane MIDI avec un split perdait son entrée (trouvé en cartographiant le lot 2)
                   **({"midi": True, "midi_role": path.get("midi_role"), "in_sel": path.get("in_sel")} if path.get("midi") else {})})

    # ── UNE BRANCHE VIDÉE PAR LE RIG SE TAIT (décision 2026-09-12) ────────────────────
    # Une branche dont TOUS les blocs ont été retirés (captures vides, cf. _drop_empty_capture)
    # passait le signal SEC. Sous un vrai ampli venu de la branche voisine, ça ne s'entend pas
    # comme « il manque un bloc » : ça s'entend comme un patch mal voisé, et l'oreille va chercher
    # le défaut dans l'ampli (argument de golem.fm, meilleur que le nôtre — c'est le cas où elle
    # se fait piéger). Elle ne contribue donc plus.
    #   · Exception : si TOUTES les branches sont vidées, on en garde UNE passante — sinon le
    #     patch redevient muet, ce qu'on venait justement de corriger, et deux voies sèches
    #     sommées donneraient le même signal deux fois.
    #   · Une branche vide DANS LE DOCUMENT n'est PAS concernée : une voie sèche en parallèle de
    #     l'ampli est un choix de son (blend dry), pas un accident. On ne tait que ce qu'on a
    #     soi-même vidé.
    bblocks = [_usable(br.get("blocks", []), resolve) for br in branches]
    emptied = [bool(br.get("blocks")) and not usable for br, usable in zip(branches, bblocks)]
    if emptied and all(emptied):
        emptied[0] = False                                       # une voie reste, sinon plus rien ne sort
    muted = [br.get("mute") or gone for br, gone in zip(branches, emptied)]

    if sp.get("merge") is None:                                  # FAN-OUT : chaque branche -> SA sortie (out_sel propre)
        for j, br in enumerate(branches):
            tracks.append({"role": "branch", "name": bnames[j], "input": None,
                           "blocks": [_prep_block(b, resolve) for b in bblocks[j]],
                           "out": br.get("out"), "level": level, "out_sel": br.get("out_sel") or out_sel,
                           "mute": muted[j]})               # union : mute de scène -> D_MUTE de piste
    else:                                                        # MERGE : branches -> folder-parent -> post -> sortie
        merge_name = base + "#merge"
        post = [_prep_block(b, resolve) for b in _usable(chain[si + 1:], resolve)]
        # ⚠ défaut −3 dB, pas 0 (mesuré le 2026-09-12) : l'écran du Designer, le chemin legacy et
        # preset-schema.md disaient tous −3 quand `gain` est absent, seul CE chemin appliquait 0.
        # Un patch de golem.fm se VOYAIT à −3 et se JOUAIT à 0 — et deux branches sommées montaient
        # de +6 dB, le limiteur de sécurité travaillant en permanence pour rattraper.
        tracks.append({"role": "merge", "name": merge_name, "input": None,
                       "merge_gain": sp["merge"].get("gain", MERGE_GAIN_DEFAULT), "blocks": post,
                       "folder": "parent", "out": path.get("out"), "level": level, "out_sel": out_sel})
        for j, br in enumerate(branches):
            tracks.append({"role": "branch", "name": bnames[j], "input": None,
                           "blocks": [_prep_block(b, resolve) for b in bblocks[j]],
                           "folder": "child", "folder_of": merge_name, "out": None,
                           "mute": muted[j]})               # union : mute de scène -> D_MUTE de piste
    return tracks


def build_plan(preset, out_count, resolve=None, mono_fallback=None, strict_out=True):
    """Contrat pour golem : normalise, (valide le routage,) et rend {id, paths:[{id,name,tracks[]}], mono_fallback}.
    `resolve(ref)->path` résout les fichiers NAM/IR. Lève RigError si invalide.
    `strict_out=False` (sandbox) : n'exige PAS l'unicité des sorties physiques (les chaînes somment sur le
    moniteur), on garde juste la validation structurelle des splits."""
    p = normalize(preset)
    if strict_out:
        validate_routing(p, out_count)
    return {
        "id": p.get("id"),
        "mono_fallback": mono_fallback or {"on": False, "gain": -3},
        # looper : présent dans le plan SEULEMENT si le mode est actif (bloc marqueur OU flag
        # legacy, cf. looper_enabled) -> golem_rig crée/mute la piste Looper
        # looper : le plan porte l'activation ET la TABLE DE BOUCLES (docs/looper.md §6) —
        # golem_rig en déduit un send par ligne, path(src) -> paire(index de ligne).
        "looper": (dict(p.get("looper") or {"enabled": True}, loops=looper_loops(preset))
                   if looper_enabled(p) else None),
        "paths": [{"id": pp["id"], "name": pp["name"], "input": pp["input"],
                   "tracks": _path_tracks(pp, resolve)} for pp in p["paths"]],
    }
