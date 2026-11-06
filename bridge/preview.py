# SPDX-License-Identifier: GPL-3.0-or-later
"""Guide sonore d'un preset (docs/preset-preview.md) — génération de la démo par scène.

Re-amp d'une phrase DI de référence (GoleM-owned, library/di-refs/) à travers la chaîne
du preset, scène par scène : le bridge bake les plans par scène + résout le DI, envoie
une commande {action:"preview"} à golem_preview.lua (piste clone jetable, render stem
WAV), poll presets/.preview.json, puis encode chaque WAV -> opus (ffmpeg) dans
library/previews/<id>/<scene>.opus et écrit preset["preview"].

Réf-DI UNIQUEMENT (jamais le jeu de l'user) : la composition est à GoleM, le son au
preset -> propre à distribuer (store golem.fm). Cf. le contrat.
"""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse

from . import config as C
from .golog import get

log = get("preview")
from . import store, scene_bake, compile_rig
from .commands import write_command

# buckets de DI par style. Depuis 2026-10-06 un preset porte des FAMILLES (docs/genres.md) : `metal` -> DI
# high-gain, punk/rock/blues -> crunch. Un preset ex-« djent » est devenu `metal` : sa DI djent ne se choisit
# plus qu'à la main (paramètre `ref` du bloc d'aperçu). Les anciens noms restent lus.
_GUITAR = {"djent": ["djent"], "high-gain": ["metal"],
           "crunch": ["punk", "math rock", "rock", "blues"]}
_BASS = {"pick": ["djent", "metal", "punk", "rock", "math rock"]}


# Les TAGS d'abord (2026-11-03) : un patch n'a pas de style, seulement des tags (« jazz », « clean »…), et
# Jazz Clean partait en high-gain sur le style « metal » resté dans un brouillon du Designer. Ordre = priorité :
# le plus spécifique gagne (« metal, djent » → djent ; « clean, crunch » → clean).
_GUITAR_TAGS = (("djent", ("djent",)),
                ("high-gain", ("metal", "high-gain", "metalcore", "hardcore")),
                ("clean", ("clean", "jazz", "funk")),
                ("crunch", ("crunch", "rock", "blues", "punk", "fuzz", "math rock")))
_BASS_TAGS = (("finger", ("finger", "funk", "jazz", "soul")),
              ("pick", ("djent", "metal", "punk", "rock", "math rock", "pick")))

# claviers et batterie (références MIDI, tools/make-midi-refs.py) : l'INSTRUMENT nommé d'abord, puis le genre
_KEYS_TAGS = (("organ", ("organ", "hammond", "b3", "gospel")), ("pad", ("pad", "strings")),
              ("lead", ("lead", "synthwave")), ("epiano", ("rhodes", "wurli", "epiano", "dx7", "electric piano")),
              ("piano", ("piano",)),
              ("pad", ("ambient",)), ("piano", ("jazz", "classical")), ("epiano", ("soul", "funk")),
              ("organ", ("rock", "blues")), ("lead", ("electro", "synth")))
_DRUMS_TAGS = (("metal", ("metal", "djent", "metalcore")), ("jazz", ("jazz", "swing", "bossa")),
               ("rock", ("rock", "pop", "punk", "indie", "70s")), ("funk", ("funk", "soul", "disco")))


def _bucket_from_tags(role, tags):
    have = {str(t).strip().lower() for t in tags or () if t}
    r = role if role in ("bass", "keys", "drums") else "guitar"
    table = {"bass": _BASS_TAGS, "keys": _KEYS_TAGS, "drums": _DRUMS_TAGS}.get(r, _GUITAR_TAGS)
    for bucket, words in table:
        if have & set(words):
            return f"{r}/{bucket}"
    return None


def _bucket(role, style):
    r = "bass" if role == "bass" else "guitar"
    st = str(style or "").lower()
    table = _BASS if r == "bass" else _GUITAR
    for bucket, styles in table.items():
        if st in styles:
            return f"{r}/{bucket}"
    return f"{r}/{'finger' if r == 'bass' else 'clean'}"   # défaut sensé par rôle


def _di_index():
    try:
        return (json.load(open(os.path.join(C.DI_REFS_DIR, "index.json"))) or {}).get("refs") or {}
    except (OSError, ValueError):
        return {}


def _main_role(preset):
    """Rôle instrument principal du preset (guitar|bass) depuis l'input map de la carte active."""
    from . import inputmap as _imap
    pt = _imap.current()
    by_ch = {str(i.get("ch")): i for i in (pt.get("inputs") or [])}
    inmap = preset.get("in") or {}
    for ck in ("1", "2"):
        role = (by_ch.get(str(inmap.get(ck) or ck)) or {}).get("role")
        if role in ("guitar", "bass"):
            return role
    return "guitar"


def input_role(in_key):
    """Rôle PATCH d'une entrée ('1'/'2' -> rôle Soundcard ; 'k' -> keys). Le preview est
    CONTEXTUEL à l'entrée (remarque 2026-07-24) : IN 2 = voix -> réfs chantées M/F."""
    if str(in_key) == "k":
        return "keys"
    from . import inputmap as _imap
    pt = _imap.current()
    for i in (pt.get("inputs") or []):
        if str(i.get("ch")) == str(in_key):
            return i.get("role") or "guitar"
    return "guitar"


def _midi_lane(preset):
    """La première lane MIDI du preset (claviers, batterie…), ou None."""
    try:
        from .store import lanes_of
        return next((L for L in lanes_of(preset) if L.get("midi")), None)
    except Exception:
        return None


_ROLES = ("guitar", "bass", "voice", "keys", "drums")


def _role_of(preset, in_key):
    """Le rôle rendu = celui de la LANE qui joue sur cette entrée : c'est elle qui dit si c'est une voix, une basse ou
    une guitare. Le lot du 2026-11-03 rendait les patchs voix d'usine avec la DI GUITARE — le rôle venait de l'entrée
    de la carte (« l'instrument principal » de l'IN 1). Repli sur la carte quand aucune lane ne le dit. L'entrée MIDI
    ('k') : la première lane MIDI (clavier ou batterie électronique)."""
    try:
        from .store import lanes_of
        lanes = lanes_of(preset)
    except Exception:
        lanes = preset.get("lanes") or []
    if str(in_key) == "k":
        lane = _midi_lane(preset) or {}
        role = lane.get("role") or "keys"
        return "drums" if role == "drums" else ("keys" if role in ("keys", "synth", "piano", "organ") else role)
    for L in lanes:
        if not L.get("midi") and str(L.get("input") or L.get("in_sel") or "") == str(in_key) and L.get("role") in _ROLES:
            return L["role"]
    return input_role(in_key) if str(in_key) != "1" else _main_role(preset)


# DEUX secondes avant la première note (premier rendu MIDI au rig, 2026-11-03) : au départ d'un rendu hors ligne,
# l'instrument (Dexed vu au rig) met un moment à se réveiller, et le premier accord sortait coupé en 0,1 s — à
# 0,25 s d'avance sur chaque scène, à 1 s sur certaines. L'encodage retire ce silence (MIDI_KEEP_S en reste) :
# le clip démarre comme une démo de DI.
MIDI_LEAD_IN = 2.0
MIDI_KEEP_S = 0.25


def midi_events(path, offset=0.0):
    """Un .mid (format 0 ou 1, carte de tempo comprise) en événements DATÉS EN SECONDES, pour golem_preview :
    `n début fin canal note vélocité` et `c temps statut canal d1 d2` (CC, bend…). Rend (durée, lignes). La durée
    est la fin de piste — la référence la laisse une mesure après le dernier coup, pour la queue."""
    import struct
    b = open(path, "rb").read()
    if b[:4] != b"MThd":
        raise ValueError("not a MIDI file")
    _fmt, ntr, ppq = struct.unpack(">HHH", b[8:14])
    i, raw = 14, []                                  # (tick, ordre, type, données)
    for _ in range(ntr):
        ln = struct.unpack(">I", b[i + 4:i + 8])[0]
        d, j, t, run = b[i + 8:i + 8 + ln], 0, 0, None
        i += 8 + ln

        def vlq():
            nonlocal j
            v = 0
            while True:
                c = d[j]; j += 1; v = (v << 7) | (c & 0x7F)
                if not c & 0x80:
                    return v
        while j < len(d):
            t += vlq()
            st = d[j]
            if st == 0xFF:
                ty = d[j + 1]; j += 2; n = vlq(); data = d[j:j + n]; j += n
                raw.append((t, 0, "tempo", int.from_bytes(data, "big")) if ty == 0x51 else (t, 0, "end", 0) if ty == 0x2F else None)
                continue
            if st in (0xF0, 0xF7):
                j += 1; n = vlq(); j += n; continue
            if st & 0x80:
                run = st; j += 1
            k = run & 0xF0
            nb = 1 if k in (0xC0, 0xD0) else 2
            d1, d2 = d[j], (d[j + 1] if nb == 2 else 0); j += nb
            raw.append((t, 1, "ev", (run, d1, d2)))
    raw = sorted((r for r in raw if r), key=lambda r: (r[0], r[1]))
    sec, last, us = 0.0, 0, 500000
    lines, open_, end = [], {}, 0.0
    for t, _o, kind, data in raw:
        sec += (t - last) / ppq * us / 1e6; last = t
        if kind == "tempo":
            us = data
        elif kind == "end":
            end = max(end, sec)
        else:
            st, d1, d2 = data
            k, ch = st & 0xF0, st & 0x0F
            if k == 0x90 and d2 > 0:
                open_.setdefault((ch, d1), []).append((sec, d2))
            elif k in (0x80, 0x90):
                if open_.get((ch, d1)):
                    s0, v = open_[(ch, d1)].pop(0)
                    lines.append(f"n {s0 + offset:.6f} {sec + offset:.6f} {ch} {d1} {v}")
            elif k in (0xB0, 0xE0):
                lines.append(f"c {sec + offset:.6f} {k} {ch} {d1} {d2}")
            end = max(end, sec)
    return round(end + offset, 6), lines


def resolve_di(preset, block, in_key="1", ref_override=None):
    """(ref_id, chemin_DI_absolu) pour ce preset ET cette entrée : override UI d'abord (ex.
    voice/female), sinon ref de la fiche, sinon 'auto' = bucket par rôle DE L'ENTRÉE + style.
    None si le fichier DI n'existe pas (à enregistrer)."""
    role = _role_of(preset, in_key)
    ref = ref_override or ((block or {}).get("params") or {}).get("ref") or "auto"
    if ref == "auto":
        if role == "voice":
            ref = "voice/male"                        # défaut voix ; l'UI propose Male/Female
        elif role in ("keys", "drums"):               # références MIDI (tools/make-midi-refs.py)
            ref = _bucket_from_tags(role, preset.get("tags")) or ("keys/piano" if role == "keys" else "drums/rock")
        else:
            ref = (_bucket_from_tags(role, preset.get("tags"))
                   or _bucket(role, preset.get("style") or (preset.get("styles") or [None])[0]))
    entry = _di_index().get(ref)
    if not entry:
        return ref, None
    path = os.path.join(C.DI_REFS_DIR, entry["file"])
    return ref, (path if os.path.isfile(path) else None)


def preview_block(preset):
    """Le bloc `preview` de la lane config, ou None."""
    for b in store._config_blocks(preset or {}):
        if isinstance(b, dict) and b.get("type") == "preview":
            return b
    return None


def _scenes_of(preset, block):
    sc = ((block or {}).get("params") or {}).get("scenes") or "all"
    ids = [s.get("id") for s in (preset.get("scenes") or []) if s.get("id")]
    if isinstance(sc, list):
        return [s for s in ids if s in sc] or ids
    return ids


def _encode_opus(wav, opus, start=0.0):
    """WAV -> opus (STÉRÉO, ~96 kbps, loudnorm léger) via ffmpeg. True si OK. Stéréo depuis le 2026-11-03 : le
    mono effaçait ce que la démo doit montrer (chorus, delays ping-pong, reverbs)."""
    os.makedirs(os.path.dirname(opus), exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", *(["-ss", f"{start:.3f}"] if start > 0 else []), "-i", wav, "-ac", "2",
             "-af", "loudnorm=I=-16:TP=-1.5",
             "-c:a", "libopus", "-b:a", "96k", opus],
            check=True, capture_output=True, timeout=60)
        return os.path.isfile(opus)
    except (subprocess.SubprocessError, OSError) as e:
        log.error(f"encode {os.path.basename(opus)} : {e}")
        return False


# ── LA DÉMO D'UN PATCH (2026-11-03) ───────────────────────────────────────────────────────────────────
# Un patch se rend comme un preset : `patch:<id>` se charge, se matérialise et change de scène par le
# chemin de tout rappel (store.load_preset). Seule la PERSISTANCE diffère : la démo ne s'écrit pas dans le
# fichier du patch (un patch d'usine est réensemencé, et le patch part chez golem.fm) mais à côté de
# ses clips, library/previews/patch-<id>[-in<k>]/preview.json — relu par GET /api/patches.
PATCH_PREFIX = "patch:"


def _patch_of(pid):
    return str(pid)[len(PATCH_PREFIX):] if str(pid).startswith(PATCH_PREFIX) else None


def patch_input(patch_id):
    """L'entrée sur laquelle le patch se joue sur CETTE carte ('1', '2'…, 'k') — None s'il ne se lie à rien."""
    preset = store.load_preset(PATCH_PREFIX + patch_id) or {}
    for lane in preset.get("lanes") or []:
        if lane.get("bind_error"):
            return None
        if lane.get("midi"):
            return "k"
        sel = str(lane.get("in_sel") or "").strip()
        # « NONE » : aucune entrée de ce rôle sur la carte (une basse sur une carte sans entrée basse) — le lot du
        # 2026-11-03 rendait ces patchs sur une piste « Sandbox #Input NONE » et les marquait en échec
        return sel if sel and sel.upper() != "NONE" else None
    return None


def patch_preview(patch_id):
    """La démo enregistrée du patch (la plus récente, toutes entrées confondues), ou None."""
    best = None
    for d in glob.glob(os.path.join(C.PREVIEWS_DIR, "patch-" + store._safe_id(patch_id) + "*", "preview.json")):
        e = store._read_json(d, None)
        if isinstance(e, dict) and e.get("scenes") and (best is None or e.get("generated", "") > best.get("generated", "")):
            best = e
    return best


# état de génération (poll UI) : {phase, done, total, msg, error}
_ST = {"phase": "idle", "preset": None, "done": 0, "total": 0, "msg": "", "error": None}


def status():
    return dict(_ST)


# le bridge (app) injecte l'applicateur de scène live + le restaurateur du rig (évite l'import circulaire).
# _restore_live ré-applique le .sandbox.json (l'état live d'avant) : générer PREND le moteur (on
# matérialise le preset scène par scène), on le REMET comme avant à la fin (décision).
_apply_scene = None
_restore_live = None


def set_scene_applier(fn):
    global _apply_scene
    _apply_scene = fn


def set_restore(fn):
    global _restore_live
    _restore_live = fn


_gen_lock = threading.Lock()   # une seule génération à la fois (UI ET jobs golem.fm)
# après le clone, côté Lua : les plugins du clone rechargent leur état (NAM son modèle, un kit ses samples) —
# même délai que le re-amp (reamp.CLONE_SETTLE_S)
CLONE_SETTLE_S = 2.0
FIRST_SETTLE_S = 3.0               # la pose du preset avant la 1re scène (reamp.SETTLE_S)
# un INSTRUMENT (Dexed et sa banque .syx, Vital, un kit) recharge son état en tâche de fond dans le clone : avec les
# délais d'un ampli, la scène A d'un piano électrique sortait muette et le 1er accord d'une autre était coupé
# (premier rendu MIDI au rig, 2026-11-03)
MIDI_CLONE_SETTLE_S = 4.0
MIDI_FIRST_SETTLE_S = 5.0
SILENT_DB = -60.0                  # un clip plus bas que ça n'a rien rendu : on le refait une fois, plus patiemment


def _peak_db(wav):
    """La crête d'un WAV rendu, en dBFS (ffmpeg décode tous les formats de REAPER) ; None si illisible."""
    import array
    import math
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-f", "s16le", "-ac", "1", "-"],
                           capture_output=True, timeout=60)
        a = array.array("h")
        a.frombytes(r.stdout[:len(r.stdout) // 2 * 2])
        return 20 * math.log10(max((abs(x) for x in a), default=0) / 32768 + 1e-12)
    except (subprocess.SubprocessError, OSError):
        return None


def generate(pid, seq, on_scene=None, in_key="1", ref=None, casting=None):
    """Génère la démo du preset `pid` (thread). Pour CHAQUE scène : applique la scène sur le
    sandbox live (moteur testé) puis demande à golem_preview de cloner+rendre la scène courante,
    poll le WAV, encode en opus. Écrit preset['preview']. Ne lève jamais.
    Choix : le bridge pilote le pas-à-pas des scènes (réutilise la matérialisation existante) ;
    le Lua ne fait QUE cloner la chaîne live courante + render stem (isolé, sans sortie hw)."""
    if not _gen_lock.acquire(blocking=False):
        _ST.update(phase="error", error="a generation is already running"); return
    try:
        _generate_locked(pid, seq, on_scene, in_key=in_key, ref=ref, casting=casting)
    finally:
        _gen_lock.release()


# ── LA DI PAR SCÈNE (2026-11-03) ───────────────────────────────────────────────────────────────────────────
# Une scène joue la phrase de SON son : un son clair la DI clean, un riff la DI de son gain, et seule une vraie scène
# de solo une DI lead (`lead-clean` derrière un ampli clair, `lead` derrière un ampli saturé).
#  · les patchs d'USINE ont leur distribution écoutée et décidée scène par scène (library/factory/demo-casting.json) ;
#  · les autres suivent une règle prudente, sur le NOM de la scène : « solo »/« lead » → la DI lead, « clean » → la DI
#    clean. Plus jamais tout un patch en solo sur un tag : Singing Clean (tagué « lead ») jouait le solo partout.
# Seulement quand la DI est choisie automatiquement, et seulement avec des DI qui existent.
_SOLO_WORDS = ("solo", "lead")
CASTING = os.path.join(C.ROOT, "library", "factory", "demo-casting.json")


def _casting(patch_id):
    if not patch_id:
        return {}
    return ((store._read_json(CASTING, {}) or {}).get("patches") or {}).get(patch_id) or {}


def _have_di(ref):
    e = _di_index().get(ref)
    return bool(e) and os.path.isfile(os.path.join(C.DI_REFS_DIR, e["file"]))


def _scene_refs(preset, scenes, ref, role, explicit, patch_id=None, casting=None):
    refs = {sc: ref for sc in scenes}
    if explicit or role != "guitar" or not str(ref).startswith("guitar/"):
        return refs
    cast = casting if casting is not None else _casting(patch_id)
    lead = "guitar/lead-clean" if ref == "guitar/clean" else "guitar/lead"
    names = {str(s.get("id")): str(s.get("name") or "").lower() for s in preset.get("scenes") or [] if isinstance(s, dict)}
    for sc in scenes:
        want = cast.get(str(sc))
        if want and _have_di(want):
            refs[sc] = want                       # la distribution décidée (une DI pas encore enregistrée : la règle)
            continue
        name = names.get(str(sc), "")
        if any(w in name for w in _SOLO_WORDS) and _have_di(lead):
            refs[sc] = lead
        elif "clean" in name and ref != "guitar/clean" and _have_di("guitar/clean"):
            refs[sc] = "guitar/clean"
    return refs


def plan(pid, in_key="1", ref=None, casting=None):
    """Ce qu'un rendu demande, calculé SANS rien rendre — partagé par la génération et le lot (qui saute une démo
    déjà à jour). Rend un dict, ou le texte du refus (anglais : l'écran le montre)."""
    preset = store.load_preset(pid)
    if not preset:
        return "preset not found"
    # le bloc Preview est OPTIONNEL (« Listen to your preset » marche sur tout preset) : absent -> défaut auto (DI
    # choisi par style/rôle, toutes les scènes). Le bloc ne sert qu'à SURCHARGER le DI de réf dans le Designer.
    block = preview_block(preset) or {"params": {"ref": "auto", "scenes": "all"}}
    patch_id = _patch_of(pid)
    if patch_id and not preset.get("tags"):
        # un patch ouvert dans le Designer se rend depuis son BROUILLON, qui n'a pas ses tags : on les reprend au
        # patch — ce sont eux qui choisissent la DI (_bucket_from_tags)
        from . import patches as P
        preset = dict(preset, tags=(P.get_patch(patch_id) or {}).get("tags") or [])
    explicit = bool(ref) or (((block or {}).get("params") or {}).get("ref") or "auto") != "auto"
    ref, di = resolve_di(preset, block, in_key=in_key, ref_override=ref)
    if not di:
        return f"reference DI missing: {ref} (record it first)"
    midi = (_di_index().get(ref) or {}).get("kind") == "midi"
    if str(in_key) == "k" and not midi:
        return f"no MIDI reference for this lane ({ref})"
    scenes = _scenes_of(preset, block)
    role = _role_of(preset, in_key)
    refs = _scene_refs(preset, scenes, ref, role, explicit, patch_id, casting)
    dis = {sc: (di if r == ref else resolve_di(preset, block, in_key=in_key, ref_override=r)[1]) for sc, r in refs.items()}
    if str(in_key) == "k":
        # la racine d'une lane MIDI est « Sandbox #Input <input> » : 3 sur une carte à deux entrées, 101+ au-delà
        # (preset_view.midi_input_base) — jamais un 3 écrit en dur
        chain = "Sandbox #Input " + str((_midi_lane(preset) or {}).get("input") or 3)
    else:
        chain = "Sandbox #Input " + str(in_key)
    from . import preset_export
    out_dir = os.path.join(C.PREVIEWS_DIR, ("patch-" + store._safe_id(patch_id)) if patch_id else store._safe_id(pid))
    out_dir += "" if str(in_key) == "1" else "-in" + str(in_key)
    return {"preset": preset, "patch_id": patch_id, "ref": ref, "refs": refs, "dis": dis, "midi": midi,
            "scenes": scenes, "role": role, "chain": chain, "out_dir": out_dir,
            "fingerprint": preset_export.fingerprint(preset)}    # empreinte SON au moment de la génération


def _generate_locked(pid, seq, on_scene=None, in_key="1", ref=None, casting=None):
    try:
        pl = plan(pid, in_key=in_key, ref=ref, casting=casting)
        if isinstance(pl, str):
            _ST.update(phase="error", error=pl); return
        if _apply_scene is None:
            _ST.update(phase="error", error="scene engine unavailable"); return
        preset, patch_id, ref, refs, midi = pl["preset"], pl["patch_id"], pl["ref"], pl["refs"], pl["midi"]
        scenes, role, chain, out_dir, fp = pl["scenes"], pl["role"], pl["chain"], pl["out_dir"], pl["fingerprint"]
        os.makedirs(out_dir, exist_ok=True)
        _ST.update(phase="render", preset=pid, done=0, total=len(scenes), msg="re-amp + capture…", error=None)
        ppath = os.path.join(C.PRESETS_DIR, f"{store._safe_id(pid)}.json")

        out_scenes = {}
        try:
            for i, sc in enumerate(scenes):
                _apply_scene(pid, sc)                                  # applique la scène (PREND le moteur)
                # laisse le rig se poser : la PREMIÈRE scène reconstruit le rig (on quitte le son live), et un
                # instrument (Vital, un kit) met plus d'une seconde à charger — la scène A d'un clavier sortait muette
                # avec 1,2 s (2026-11-03) ; les suivantes ne font que basculer des états
                time.sleep((MIDI_FIRST_SETTLE_S if midi else FIRST_SETTLE_S) if i == 0 else 1.2)
                wav = os.path.join(out_dir, f"{sc}.wav")
                try:
                    os.remove(C.PREVIEW_FILE)
                except OSError:
                    pass
                # `tree` : TOUTE la lane (racine, branches d'un split, merge), comme le re-amp (reamp.py). Sans lui,
                # golem_preview ne copiait que les FX de la racine : une lane splittée rendait la DI sans ses
                # amplis ni ses branches (premier essai au rig, Jazz Clean, 2026-11-03)
                di = pl["dis"][sc]
                cmd = {"action": "preview", "seq": seq, "op": "render", "scene": sc,
                       "di": di, "out": wav, "tail": 5.0, "chain": chain, "tree": True,
                       "settle": MIDI_CLONE_SETTLE_S if midi else CLONE_SETTLE_S, "_route": "preview"}
                if midi:
                    # une référence MIDI se JOUE par l'instrument de la lane : ses événements, datés en secondes,
                    # dans un fichier que golem_preview pose en item MIDI sur la racine clonée
                    ev = os.path.join(out_dir, f"{sc}.midi.txt")
                    dur, lines = midi_events(di, offset=MIDI_LEAD_IN)
                    with open(ev, "w", encoding="utf-8") as f:
                        f.write(f"len {dur:.6f}\n" + "\n".join(lines) + "\n")
                    cmd["midi"] = ev
                write_command(cmd)
                got = _poll_scene(seq, sc, timeout=150)                # attend le WAV rendu (render ~45 s/scène)
                pk = _peak_db(got) if got and os.path.isfile(got) else None
                if pk is not None and pk < SILENT_DB:
                    # muet : le rig n'avait pas construit la lane (vue au rig juste après un redémarrage du bridge :
                    # racine muette, 0 FX), ou l'instrument du clone n'avait pas fini de charger. On RÉAPPLIQUE la
                    # scène, puis on rend une seconde fois, deux fois plus patient
                    log.warning(f"preview {pid} scène {sc} : clip muet ({pk:.0f} dBFS), scène réappliquée, nouveau rendu")
                    _apply_scene(pid, sc)
                    time.sleep(MIDI_FIRST_SETTLE_S if midi else FIRST_SETTLE_S)
                    with __import__("contextlib").suppress(OSError):
                        os.remove(C.PREVIEW_FILE)
                    write_command(dict(cmd, settle=cmd["settle"] * 2))
                    got = _poll_scene(seq, sc, timeout=150)
                if got and os.path.isfile(got):
                    opus = os.path.join(out_dir, f"{sc}.opus")
                    if midi:
                        with __import__("contextlib").suppress(OSError):
                            os.remove(os.path.join(out_dir, f"{sc}.midi.txt"))
                    if _encode_opus(got, opus, start=(MIDI_LEAD_IN - MIDI_KEEP_S) if midi else 0.0):
                        out_scenes[sc] = C.rel(opus)
                        with __import__("contextlib").suppress(OSError):
                            os.remove(got)
                        # écriture INCRÉMENTALE : scène A jouable dans /library pendant que B/C rendent
                        entry = {"instrument": role, "ref": ref, "refs": refs, "fingerprint": fp,
                                 "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "scenes": out_scenes}
                        fresh = None if patch_id else (store.load_preset(pid) or preset)
                        if patch_id:                             # à côté des clips, jamais dans le patch
                            store._write_json_atomic(os.path.join(out_dir, "preview.json"), dict(entry, input=str(in_key)))
                        elif str(in_key) == "1":
                            pv = fresh.get("preview") or {}
                            entry["alt"] = pv.get("alt") or {}
                            fresh["preview"] = entry             # legacy : IN 1 au top-level
                        else:
                            pv = fresh.setdefault("preview", {})
                            pv.setdefault("alt", {})[str(in_key)] = entry   # démos par ENTRÉE (IN 2…)
                        if fresh is not None:
                            store._write_json_atomic(ppath, fresh)
                        # hook INCRÉMENTAL (job golem.fm) : upload + progress DÈS que la scène est prête
                        if on_scene is not None:
                            with __import__("contextlib").suppress(Exception):
                                on_scene(sc, out_scenes[sc])
                _ST.update(done=i + 1)
        finally:
            # REMET le moteur comme avant (on l'a pris pour rendre) — décision .
            if _restore_live is not None:
                with __import__("contextlib").suppress(Exception):
                    _restore_live()

        if not out_scenes:
            _ST.update(phase="error", error="no clip rendered (check on the rig)"); return
        _ST.update(phase="done", msg=f"demo generated ({len(out_scenes)} scene(s))", error=None)
    except Exception as e:
        _ST.update(phase="error", error=str(e))


def _poll_scene(seq, scene, timeout):
    """Attend presets/.preview.json {scene, done:true, wav:'…'} — chemin WAV | None.
    On matche sur (scene, done) et PAS sur seq : write_command réécrit le seq avec son propre
    nonce (le Lua le republie), et on vide .preview.json avant chaque commande -> toute publication
    `scene==sc, done` qui apparaît est la bonne."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = store._read_json(C.PREVIEW_FILE, None)
        if d and d.get("scene") == scene and d.get("done"):
            if d.get("error"):
                _ST.update(msg=f"REAPER: {d['error']}")
                return None
            return d.get("wav")
        time.sleep(0.4)
    return None


def _clip_duration(path):
    """Durée d'un clip en SECONDES (float, 2 déc.) via ffprobe — None si indéterminable."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=10)
        return round(float(r.stdout.strip()), 2)
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def push_clip(pid, scene, rel):
    """Upload UN clip (une scène) vers le blob store golem.fm — {sha256, duration} | None.
    Stocké chez golem.fm -> l'user l'écoute même GoleM éteint, et tout le store y a accès."""
    from . import tones_sync
    path = os.path.join(C.ROOT, rel)
    if not os.path.isfile(path):
        return None
    state = tones_sync._load_state()
    cache = state.setdefault("sha_cache", {})
    sha = tones_sync._sha256_cached(path, cache)
    tones_sync._save_state(state)
    st, _ = tones_sync._req(
        "POST", "/api/ext/tones/assets?sha256=%s&filename=%s"
        % (sha, urllib.parse.quote(f"{store._safe_id(pid)}-{scene}.opus")), raw_file=path)
    if st != 200:
        return None
    return {"sha256": sha, "duration": _clip_duration(path)}


def push_clips(pid):
    """Upload TOUS les clips du preset (fallback non-incrémental). {scene:{sha256,duration}} + ref."""
    preset = store.load_preset(pid) or {}
    pv = preset.get("preview") or {}
    out = {}
    for sc, rel in (pv.get("scenes") or {}).items():
        one = push_clip(pid, sc, rel)
        if one:
            out[sc] = one
    return {"ref": pv.get("ref"), "instrument": pv.get("instrument"), "scenes": out}


def export_deps(preset):
    """(deps[], blob_map) des clips de preview pour l'export golem.fm (kind 'preview')."""
    from . import tones_sync
    deps, blobs = [], {}
    for sc, rel in ((preset.get("preview") or {}).get("scenes") or {}).items():
        path = os.path.join(C.ROOT, rel)
        if not os.path.isfile(path):
            continue
        state = tones_sync._load_state()
        sha = tones_sync._sha256_cached(path, state.setdefault("sha_cache", {}))
        tones_sync._save_state(state)
        deps.append({"sha256": sha, "uid": f"local:preview-{preset.get('id')}-{sc}",
                     "kind": "preview", "bytes": os.path.getsize(path),
                     "name": f"{preset.get('id')} · scene {sc}", "source": "golemfm"})
        blobs[sha] = path
    return deps, blobs


# ── LE RENDU PAR LOT (docs/preset-preview.md §7, 2026-11-03) ──────────────────────────────────────────────────
# Les démos de TOUS les patchs d'usine, une à la fois (le moteur est pris pour chaque rendu, puis rendu), à lancer
# quand personne ne joue. REPRENABLE : une démo dont l'empreinte du son et les DI par scène n'ont pas bougé est
# sautée — un lot interrompu (arrêt, prise lancée) se relance là où il en était. Un patch qui ne peut pas se rendre
# (DI pas encore enregistrée, pas d'entrée de ce rôle sur la carte) est sauté AVEC sa raison, jamais en silence.
_BATCH = {"running": False, "total": 0, "done": 0, "current": None, "items": [], "stopped": None,
          "started": None, "ended": None}
_batch_stop = threading.Event()
BATCH_ROLES_SKIPPED = ("pads", "keys-pads")      # des échantillons déclenchés : aucune phrase n'y a de sens


def factory_patch_ids():
    from . import patches as P, factory
    return sorted(x["id"] for x in factory.mark("patches", P.list_patches())
                  if isinstance(x, dict) and x.get("factory") and x.get("role") not in BATCH_ROLES_SKIPPED)


def batch_status():
    return dict(_BATCH, items=[dict(i) for i in _BATCH["items"]], current_scene=dict(_ST))


def _up_to_date(pl):
    e = store._read_json(os.path.join(pl["out_dir"], "preview.json"), None)
    if not isinstance(e, dict) or e.get("fingerprint") != pl["fingerprint"] or e.get("refs") != pl["refs"]:
        return False
    clips = e.get("scenes") or {}
    return set(clips) == set(pl["scenes"]) and all(os.path.isfile(os.path.join(C.ROOT, r)) for r in clips.values())


def stop_batch():
    _batch_stop.set()


def _preset_lanes(preset_ids):
    out = []
    for pid in preset_ids:
        p = store.load_preset(pid)
        for L in store.lanes_of(p) if p else []:
            if L.get("role") not in BATCH_ROLES_SKIPPED:
                out.append(f"preset:{pid}/{L['id']}")
    return out


def _batch_lane(target, force, seq):
    """Une lane de preset du lot : copiée depuis son patch, rendue seule, ou sautée avec sa raison."""
    pid, lane_id = target[len("preset:"):].split("/", 1)
    pl = lane_plan(pid, lane_id)
    if isinstance(pl, str):
        return {"status": "skipped", "reason": pl}
    if not force and lane_up_to_date(pl, pid, lane_id):
        return {"status": "skipped", "reason": "up to date"}
    if "copy" in pl:
        copy_lane(pid, lane_id, pl)
        return {"status": "copied", "reason": f"from {pl['from']}"}
    scenes, why = render_lane(pid, lane_id, pl, seq)
    if why:
        return {"status": "skipped" if "reference DI missing" in why or "no input" in why else "failed", "reason": why}
    return {"status": "rendered", "reason": pl.get("render")}


def batch(ids=None, force=False, seq_of=None):
    """Rend les démos des patchs `ids` (défaut : ceux de l'usine, PUIS les lanes des presets d'usine). Bloquant : à
    lancer dans un thread. Ne lève jamais."""
    from .state import state
    ids = list(ids) if ids else factory_patch_ids() + _preset_lanes(factory_preset_ids())
    _batch_stop.clear()
    _BATCH.update(running=True, total=len(ids), done=0, current=None, stopped=None, ended=None,
                  started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  items=[{"id": i, "status": "waiting"} for i in ids])
    try:
        for n, patch_id in enumerate(ids):
            item = _BATCH["items"][n]
            if _batch_stop.is_set():
                _BATCH["stopped"] = "stopped"; break
            if (state.perf or {}).get("recording"):
                _BATCH["stopped"] = "a take started — run it again after, it resumes"; break
            _BATCH["current"] = patch_id
            if patch_id.startswith("preset:"):
                item.update(_batch_lane(patch_id, force, seq_of() if seq_of else n + 1))
                _BATCH["done"] = n + 1
                log.info(f"lot de démos : {patch_id} → {item['status']}" + (f" ({item.get('reason')})" if item.get("reason") else ""))
                continue
            pid = PATCH_PREFIX + patch_id
            in_key = patch_input(patch_id)
            if not in_key:
                # pas d'entrée de son rôle sur cette carte : une entrée audio EMPRUNTÉE le temps du rendu
                item.update(render_patch_borrowed(patch_id, seq_of() if seq_of else n + 1, force))
            else:
                pl = plan(pid, in_key=in_key)
                if isinstance(pl, str):
                    item.update(status="skipped", reason=pl)
                elif not force and _up_to_date(pl):
                    item.update(status="skipped", reason="up to date")
                else:
                    item.update(status="rendering")
                    generate(pid, seq_of() if seq_of else n + 1, in_key=in_key)
                    st = status()
                    item.update(status="rendered" if st.get("phase") == "done" else "failed",
                                **({} if st.get("phase") == "done" else {"reason": st.get("error") or "failed"}))
            _BATCH["done"] = n + 1
            log.info(f"lot de démos : {patch_id} → {item['status']}" + (f" ({item.get('reason')})" if item.get("reason") else ""))
    except Exception as e:                                   # le lot ne meurt jamais en silence
        _BATCH["stopped"] = f"error: {e}"
        log.error(f"lot de démos interrompu : {e}")
    finally:
        _BATCH.update(running=False, current=None, ended=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ── LA DÉMO D'UN PRESET, LANE PAR LANE (2026-11-03) ───────────────────────────────────────────────────────────
# Une lane de morceau a SA démo, rangée avec le morceau (library/previews/preset-<id>/<lane>/preview.json + un clip
# par scène du MORCEAU) — aucun lien vivant avec le patch d'où elle vient : retoucher le patch ou la lane ne touche
# pas une démo faite. Pour la faire : si la lane SONNE exactement comme son patch d'origine (`patch_from`, posé au
# dépôt) — même chaîne, mêmes réglages de l'état que la scène lui donne, identifiants renommés (comp-2) et volume
# système mis à part —, le clip de la scène du patch qui pose ce même état est COPIÉ ; sinon la lane est rendue par
# le moteur, posée seule sur une entrée de son rôle. Lecture seule côté Presets, sans notion de carte son.
_SYS_VOLUME = lambda b: isinstance(b, dict) and b.get("type") == "volume" and str(b.get("id") or "").endswith("-sys")


def _sound(c):
    """Le SON d'une chaîne : types, réglages, captures, ordre et branches — pas les identifiants (renommés dans un
    morceau), pas le pied, pas le volume système."""
    if isinstance(c, dict):
        return {k: _sound(v) for k, v in c.items() if k not in ("id", "foot")}
    if isinstance(c, list):
        return [_sound(v) for v in c if not _SYS_VOLUME(v)]
    return c


def _ids(c, out):
    """Les identifiants de blocs ET de branches, dans l'ordre d'une marche déterministe (clés triées)."""
    if isinstance(c, dict):
        if c.get("id") is not None and ("type" in c or "blocks" in c):
            out.append(str(c["id"]))
        for k in sorted(c):
            if k != "id":
                _ids(c[k], out)
    elif isinstance(c, list):
        for v in c:
            if not _SYS_VOLUME(v):
                _ids(v, out)
    return out


def _id_map(lane_chain, patch_chain):
    """{id de la lane: id du patch} si les deux chaînes ont le même son, sinon None."""
    if json.dumps(_sound(lane_chain), sort_keys=True) != json.dumps(_sound(patch_chain), sort_keys=True):
        return None
    a, b = _ids(lane_chain, []), _ids(patch_chain, [])
    return dict(zip(a, b)) if len(a) == len(b) else None


def _num(v):
    """1 et 1.0 sont le même réglage."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return {k: _num(x) for k, x in v.items()} if isinstance(v, dict) else v
    return float(v)


def _chain_parts(chain):
    """(blocs {id: allumé par défaut}, branches [id]) d'une chaîne."""
    blocks, branches = {}, []

    def walk(c):
        if isinstance(c, dict):
            if c.get("id") is not None and "type" in c and not _SYS_VOLUME(c):
                blocks[str(c["id"])] = not c.get("bypass")
            elif c.get("id") is not None and "blocks" in c:
                branches.append(str(c["id"]))
            for v in c.values():
                walk(v)
        elif isinstance(c, list):
            for v in c:
                walk(v)
    walk(chain)
    return blocks, branches


def _state_sound(state, idmap, chain):
    """Ce qu'un état fait EFFECTIVEMENT entendre — chaque bloc allumé ou non (un bloc absent de l'état garde son état
    de base), chaque branche coupée ou non, les réglages — traduit dans les identifiants du patch. Deux écritures du
    même son (« comp »: true explicite contre l'état de base, 1.0 contre 1) donnent la même empreinte."""
    st = state or {}
    blocks, branches = _chain_parts(chain)
    sb, sp, sr = st.get("blocks") or {}, st.get("params") or {}, st.get("branches") or {}
    m = lambda k: idmap.get(str(k), str(k))
    out = {"blocks": {m(b): (sb[b] is not False) if sb.get(b) is not None else on for b, on in blocks.items()},
           "params": {m(k): _num(v) for k, v in sp.items() if v},
           "branches": {m(b): bool((sr.get(b) or {}).get("mute")) for b in branches}}
    return json.dumps(out, sort_keys=True)


def _scene_state(preset, scene, lane_id):
    """(état de la lane dans cette scène, coupée ?) — l'état est un dict de la lane, ou None."""
    e = ((scene.get("lanes") or {}).get(lane_id) or {}) if isinstance(scene, dict) else {}
    lane = next((L for L in store.lanes_of(preset) if L["id"] == lane_id), {})
    st = next((s for s in lane.get("states") or [] if s.get("id") == e.get("state")), None)
    return st, bool(e.get("mute"))


def lane_dir(preset_id, lane_id):
    return os.path.join(C.PREVIEWS_DIR, "preset-" + store._safe_id(preset_id), store._safe_id(lane_id))


def lane_previews(preset_id):
    """{lane: démo} d'un preset (pour GET /api/presets)."""
    out = {}
    base = os.path.join(C.PREVIEWS_DIR, "preset-" + store._safe_id(preset_id))
    for d in glob.glob(os.path.join(base, "*", "preview.json")):
        e = store._read_json(d, None)
        if isinstance(e, dict) and e.get("scenes") and e.get("lane"):
            out[e["lane"]] = e
    return out


def lane_plan(preset_id, lane_id):
    """Comment faire la démo d'une lane : {"copy": {scène du morceau: (patch, scène du patch)}, …} si elle sonne comme
    son patch, {"render": raison} sinon, ou le texte du refus (anglais)."""
    preset = store.load_preset(preset_id)
    if not preset:
        return "preset not found"
    lane = next((L for L in store.lanes_of(preset) if L["id"] == lane_id), None)
    if not lane:
        return "lane not found"
    if lane.get("role") in BATCH_ROLES_SKIPPED:
        return "pads trigger samples — no demo"
    src = (lane.get("patch_from") or {}).get("id")
    pdoc = store.load_preset(PATCH_PREFIX + src) if src else None
    plane = (pdoc.get("lanes") or [None])[0] if pdoc else None
    idmap = _id_map(lane.get("chain"), plane.get("chain")) if plane else None
    base = {"preset": preset, "lane": lane, "from": src,
            "fingerprint": hashlib.sha1(json.dumps([_sound(lane.get("chain")),
                                                     [_state_sound(s, {}, lane.get("chain")) for s in lane.get("states") or []]],
                                                    sort_keys=True).encode()).hexdigest()[:16]}
    if idmap is None:
        return dict(base, render="the lane was changed since its patch" if src else "the lane does not come from a patch")
    pdemo = patch_preview(src) or {}
    by_state = {}                                         # ce que l'état fait entendre -> scène du patch qui le pose
    for ps in pdoc.get("scenes") or []:
        st, mute = _scene_state(pdoc, ps, plane["id"])
        if st and not mute:
            by_state.setdefault(_state_sound(st, {}, plane.get("chain")), ps["id"])
    copy, missing = {}, []
    for sc in preset.get("scenes") or []:
        st, mute = _scene_state(preset, sc, lane_id)
        if mute or not st:
            continue                                      # la lane se tait dans cette scène : rien à entendre
        pscene = by_state.get(_state_sound(st, idmap, lane.get("chain")))
        if not pscene:
            return dict(base, render=f"scene {sc['id']} sets a state its patch does not have")
        if not (pdemo.get("scenes") or {}).get(pscene):
            missing.append(sc["id"])
        copy[sc["id"]] = pscene
    if missing:
        return f"the patch {src} has no demo yet"
    return dict(base, copy=copy, patch_demo=pdemo)


def _write_lane_preview(preset_id, lane_id, entry):
    d = lane_dir(preset_id, lane_id)
    os.makedirs(d, exist_ok=True)
    store._write_json_atomic(os.path.join(d, "preview.json"), dict(entry, lane=lane_id))


def lane_up_to_date(pl, preset_id, lane_id):
    e = store._read_json(os.path.join(lane_dir(preset_id, lane_id), "preview.json"), None)
    if not isinstance(e, dict) or e.get("fingerprint") != pl["fingerprint"]:
        return False
    if "copy" in pl and e.get("source_generated") != (pl["patch_demo"] or {}).get("generated"):
        return False                                       # la démo du patch a été refaite : on recopie
    return all(os.path.isfile(os.path.join(C.ROOT, r)) for r in (e.get("scenes") or {}).values())


def copy_lane(preset_id, lane_id, pl):
    """Copie les clips du patch dans la démo de la lane (des fichiers à part, plus jamais liés)."""
    d = lane_dir(preset_id, lane_id)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    pdemo = pl["patch_demo"]
    scenes, refs = {}, {}
    for sc, psc in pl["copy"].items():
        dst = os.path.join(d, f"{sc}.opus")
        shutil.copy2(os.path.join(C.ROOT, pdemo["scenes"][psc]), dst)
        scenes[sc] = C.rel(dst)
        refs[sc] = (pdemo.get("refs") or {}).get(psc) or pdemo.get("ref")
    _write_lane_preview(preset_id, lane_id, {
        "instrument": pdemo.get("instrument"), "ref": pdemo.get("ref"), "refs": refs, "scenes": scenes,
        "fingerprint": pl["fingerprint"], "made": "copied", "from": pl["from"], "from_scenes": pl["copy"],
        "source_generated": pdemo.get("generated"),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return scenes


def render_lane(preset_id, lane_id, pl, seq):
    """La lane rendue SEULE : un preset d'essai fait d'elle, lié à une entrée de son rôle sur cette carte (ou à
    l'entrée MIDI), ses scènes = celles du morceau ; la DI de chaque scène suit la distribution du patch d'origine
    par le NOM de l'état. Rend (clips, raison du refus)."""
    from . import patches as P, tones_jobs
    preset, lane = pl["preset"], pl["lane"]
    try:
        doc = P.v2_fields(preset, [lane_id], with_config=False)
    except ValueError as e:
        return None, str(e)
    tmp_id = "preview-lane-" + store._safe_id(preset_id) + "-" + store._safe_id(lane_id)
    # les TAGS du patch d'origine (ceux du morceau sinon) : ce sont eux qui choisissent la référence — sans eux la
    # batterie de Metal for All partait sur drums/rock (premier lot des presets, 2026-11-03)
    tags = ((P.get_patch(pl["from"]) or {}).get("tags") if pl.get("from") else None) or preset.get("tags") or []
    doc.update(id=tmp_id, name=f"{preset.get('name')} · {lane.get('name')}", role=lane.get("role"), tags=tags)
    try:
        trial, *_ = tones_jobs._trial_preset({"_doc": doc, "patch_id": tmp_id, "role": lane.get("role")},
                                             ".lane-preview.tmp", pid=tmp_id)
    except RuntimeError as e:
        return None, str(e)
    trial["tags"] = tags                                 # le preset d'essai ne reprend pas les tags du document
    tl = (trial.get("lanes") or [{}])[0]
    in_key = "k" if tl.get("midi") else str(tl.get("in_sel") or "")
    if not in_key or in_key.upper() == "NONE":
        return None, "no input of this card plays this role"
    # la distribution : le NOM de l'état que chaque scène du morceau donne à la lane -> la scène du patch d'origine
    # qui porte ce nom -> sa DI (library/factory/demo-casting.json)
    src_cast, cast = _casting(pl.get("from")), {}
    pdoc = store.load_preset(PATCH_PREFIX + pl["from"]) if pl.get("from") else None
    pnames = {}
    if pdoc:
        pl0 = (pdoc.get("lanes") or [{}])[0]
        for ps in pdoc.get("scenes") or []:
            st, _m = _scene_state(pdoc, ps, pl0.get("id"))
            if st and st.get("name"):
                pnames.setdefault(st["name"], ps["id"])
    for sc in preset.get("scenes") or []:
        st, _m = _scene_state(preset, sc, lane_id)
        ps = pnames.get((st or {}).get("name"))
        if ps and src_cast.get(ps):
            cast[sc["id"]] = src_cast[ps]
    ppath = os.path.join(C.PRESETS_DIR, tmp_id + ".json")
    store._write_json_atomic(ppath, trial)
    out_tmp = os.path.join(C.PREVIEWS_DIR, tmp_id + ("" if in_key == "1" else "-in" + in_key))
    try:
        generate(tmp_id, seq, in_key=in_key, casting=cast)
        st = status()
        if st.get("phase") != "done":
            return None, st.get("error") or "generation failed"
        e = store._read_json(os.path.join(C.PRESETS_DIR, tmp_id + ".json"), {}) or {}
        pv = e.get("preview") or {}
        pv = pv if in_key == "1" else ((pv.get("alt") or {}).get(in_key) or {})
        d = lane_dir(preset_id, lane_id)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        scenes = {}
        for sc, rel in (pv.get("scenes") or {}).items():
            dst = os.path.join(d, f"{sc}.opus")
            shutil.copy2(os.path.join(C.ROOT, rel), dst)
            scenes[sc] = C.rel(dst)
        _write_lane_preview(preset_id, lane_id, {
            "instrument": pv.get("instrument"), "ref": pv.get("ref"), "refs": pv.get("refs"), "scenes": scenes,
            "fingerprint": pl["fingerprint"], "made": "rendered", "from": pl.get("from"), "why": pl.get("render"),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return scenes, None
    finally:
        with __import__("contextlib").suppress(OSError):
            os.remove(ppath)
        shutil.rmtree(out_tmp, ignore_errors=True)


def factory_preset_ids():
    from . import factory
    return sorted(factory.ids("presets"))


# ── UNE ENTRÉE EMPRUNTÉE (2026-11-04) ───────────────────────────────────────────────────────────────────────────
# Rendre une démo n'a pas besoin du RÔLE des entrées de la carte : la phrase de référence entre dans le clone, hors
# ligne. Un patch de basse sur une carte sans entrée basse (le rack du mainteneur : voix et guitare) se rend donc sur
# une entrée audio EMPRUNTÉE le temps du rendu — le patch est lié à une copie de la carte où cette entrée porte son
# rôle ; la vraie carte n'est pas touchée.
BORROW_ROLES = ("bass", "voice", "guitar")


def _borrowed_imap(role):
    from . import inputmap
    imap = json.loads(json.dumps(inputmap.current() or {}))
    ins = [e for e in imap.get("inputs") or [] if str(e.get("ch") or "").isdigit()]
    if not ins:
        return None, None
    ins[0].update(role=role, nth=1)
    return imap, str(ins[0]["ch"])


def render_patch_borrowed(patch_id, seq, force=False):
    """La démo d'un patch dont le rôle n'a pas d'entrée sur cette carte. Rend {"status", "reason"} comme le lot."""
    from . import patches as P
    doc = P.get_patch(patch_id)
    if not doc or doc.get("role") not in BORROW_ROLES:
        return {"status": "skipped", "reason": "no input of this card plays it"}
    imap, ch = _borrowed_imap(doc["role"])
    if not imap:
        return {"status": "skipped", "reason": "this card has no audio input"}
    pre = P.as_preset(doc, imap=imap)
    if not pre:
        return {"status": "skipped", "reason": "this patch cannot be played"}
    tmp_id = "preview-borrow-" + store._safe_id(patch_id)
    ppath = os.path.join(C.PRESETS_DIR, tmp_id + ".json")
    out_tmp = os.path.join(C.PREVIEWS_DIR, tmp_id + ("" if ch == "1" else "-in" + ch))
    d = os.path.join(C.PREVIEWS_DIR, "patch-" + store._safe_id(patch_id) + ("" if ch == "1" else "-in" + ch))
    # écrit AVANT de le planifier : le moteur et `plan` le chargent par son id, comme tout preset
    store._write_json_atomic(ppath, dict(pre, id=tmp_id, tags=doc.get("tags") or []))
    try:
        pl = plan(tmp_id, in_key=ch, casting=_casting(patch_id))
        if isinstance(pl, str):
            return {"status": "skipped", "reason": pl}
        if not force and _up_to_date(dict(pl, out_dir=d)):
            return {"status": "skipped", "reason": "up to date"}
        generate(tmp_id, seq, in_key=ch, casting=_casting(patch_id))
        st = status()
        if st.get("phase") != "done":
            return {"status": "failed", "reason": st.get("error") or "generation failed"}
        e = store._read_json(ppath, {}) or {}
        pv = e.get("preview") or {}
        pv = pv if ch == "1" else ((pv.get("alt") or {}).get(ch) or {})
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        scenes = {}
        for sc, rel in (pv.get("scenes") or {}).items():
            dst = os.path.join(d, f"{sc}.opus")
            shutil.copy2(os.path.join(C.ROOT, rel), dst)
            scenes[sc] = C.rel(dst)
        store._write_json_atomic(os.path.join(d, "preview.json"), dict(pv, scenes=scenes, input=ch, borrowed=True))
        return {"status": "rendered", "reason": f"on input {ch}, borrowed for the render"}
    finally:
        with __import__("contextlib").suppress(OSError):
            os.remove(ppath)
        shutil.rmtree(out_tmp, ignore_errors=True)
