# SPDX-License-Identifier: GPL-3.0-or-later
"""ENTENDRE UN KIT DE BATTERIE ET UN GROOVE SUR UN KIT (docs/drums-library.md, maquette validée le 2026-11-14).

  - la DÉMO d'un kit : les quatre phrases MIDI de référence (library/di-refs/drums/{rock,funk,jazz,metal}.mid, à
    changer quand on veut : leur sha256 entre dans l'empreinte, un fichier changé refait le clip) jouées par le kit ;
  - un GROOVE sur un kit : un groove de la bibliothèque joué par le kit choisi, au tempo du fichier, à sa moitié ou
    au tempo du patch, rendu au premier toucher puis gardé (cache borné).

Le moteur est celui des rendus de blocs (preview.render_block, docs/preset-preview.md §8) : golem_drums POSE le kit
sur la piste Drums sans jouer (op « load »), golem_preview clone la piste sans son séquenceur et y joue les notes,
hors ligne, sans sortie matérielle. Jamais pendant qu'un groove ou un standard joue (preview.live_players_busy).
Rangement : library/previews/kit-<id>/<phrase>.opus + preview.json ; library/previews/groove-on-kit/<clé>.opus."""
import hashlib
import json
import math
import os
import threading
import time

from . import config as C
from . import store
from .golog import get

log = get("drum-preview")

REFS = ("drums/rock", "drums/funk", "drums/jazz", "drums/metal")
GOK_DIR = os.path.join(C.PREVIEWS_DIR, "groove-on-kit")
GOK_KEEP = 40
GOK_MIN_BARS = 4                  # un groove court se boucle jusqu'à 4 mesures : on entend qu'il tourne
PREFIX = "kit:"                   # un élément du lot des démos d'usine


# ── le dessin : le type de batterie (drumKit de golem-fx) d'un kit, par son style puis son nom ──────────────────────
def kit_type(k):
    n, h = str(k.get("name") or "").lower(), str(k.get("hint") or "").lower()
    if k.get("role") != "drum" and (k.get("engine") or "rs5k") == "rs5k":   # sans moteur = rs5k (bridge/kits.py)
        return "pads"
    if any(w in n + " " + h for w in ("electronic", "808", "909", "e-kit", "edrum")):
        return "electronic"
    if "hybrid" in n or "hybrid" in h:
        return "hybrid"
    if "metal" in h or "metal" in n:
        return "metal"
    if "jazz" in h or "bop" in n or "jazz" in n:
        return "jazz"
    # une PHOTO par type (golem-fx 00ccb5d) : deux kits du même type ont la même image — Red Zeppelin (rock · dry) prend
    # la batterie rock, laquée rouge ; Black Pearl reste la vintage, nacrée
    if any(w in n for w in ("pearl", "vintage", "60s", "70s")):
        return "vintage"
    return "rock"


def _sha(path):
    from . import sound_preview
    return sound_preview._sha256(path)


def _ref_path(ref):
    from . import preview as PV
    e = PV._di_index().get(ref) or {}
    p = os.path.join(C.DI_REFS_DIR, e.get("file") or "")
    return p if e.get("file") and os.path.isfile(p) else None


def kit_dir(kit_id):
    return os.path.join(C.PREVIEWS_DIR, "kit-" + store._safe_id(kit_id))


def gm_net(k):
    """La traduction GM → kit d'une BATTERIE dont la table n'est pas General MIDI (kit_import.gm_translation) ; {}
    pour un kit GM ou un kit de pads (ses pads sont déjà sur les notes GM, kits.DEFAULT_NOTES)."""
    from . import kit_import as KI
    if (k or {}).get("role") != "drum" or not isinstance(k.get("notes"), dict):
        return {}
    return KI.gm_translation(k["notes"])


def _kit_fp(k):
    """Ce qui fait le son d'un kit : son moteur et ce qu'il charge (banque avldrums, kit drumgizmo, sfz) — et, pour un
    kit de PADS, chaque son et son réglage (des samples refaits changent l'écoute d'un groove sur ce kit, 2026-11-15)."""
    pads = []
    for p in k.get("pads") or []:
        if isinstance(p, dict) and p.get("sample"):
            f = os.path.join(C.ROOT, p["sample"])
            pads.append([p.get("note"), p.get("mode"), p.get("level"), _sha(f) if os.path.isfile(f) else p["sample"]])
    # les pads seulement quand il y en a : l'empreinte d'une batterie ne bouge pas (ses démos restent à jour)
    # la TABLE d'un kit importé aussi (réécrite en General MIDI le 2026-11-15 : les démos d'avant tapaient à côté) ;
    # seulement pour un import, l'empreinte des batteries d'usine ne bouge pas
    mm = []
    if k.get("imported") and k.get("midimap"):
        f = os.path.join(C.ROOT, k["midimap"])
        mm = [k["midimap"], _sha(f) if os.path.isfile(f) else None]
    # le FILET d'un kit non GM (2026-11-15) : sa traduction change ce qu'on entend ; seulement quand il y en a une,
    # l'empreinte d'un kit GM ne bouge pas
    net = sorted(gm_net(k).items())
    return hashlib.sha1(json.dumps([k.get("engine"), k.get("bank"), k.get("drumkit"), k.get("sfz"), k.get("mix")]
                                   + ([pads] if pads else []) + ([mm] if mm else []) + ([["gm-net", net]] if net else []),
                                   sort_keys=True, default=str).encode()).hexdigest()[:16]


def entry(kit_id):
    return store._read_json(os.path.join(kit_dir(kit_id), "preview.json"), None)


def demo(k):
    """L'état des démos d'un kit : {status: ready|pending|none, clips: {ref: {clip, seconds}}} — `pending` aussi quand
    une phrase a changé (son sha256) ou le kit (son empreinte)."""
    if k.get("role") != "drum" or k.get("available") is False:
        return {"status": "none", "clips": {}}
    e = entry(k["id"]) or {}
    clips, fresh = {}, e.get("fingerprint") == _kit_fp(k)
    for ref in REFS:
        c = (e.get("clips") or {}).get(ref)
        if c and os.path.isfile(os.path.join(C.ROOT, c.get("file") or "")):
            clips[ref] = {"clip": "/" + c["file"].lstrip("/"), "seconds": c.get("seconds"),
                          "name": ref.split("/")[-1].capitalize()}
            p = _ref_path(ref)
            if p and c.get("ref_sha") and c["ref_sha"] != _sha(p):
                fresh = False
    have = all(r in clips for r in REFS if _ref_path(r))
    return {"status": "ready" if have and fresh else "pending", "clips": clips}


# ── le rendu : des notes datées en secondes, jouées par un kit ─────────────────────────────────────────────────────
def _render(kit, dur, lines, opus, seq, scene):
    """Le cœur commun (comme preview.render_block) : pose le kit, rend, refuse un silence, encode. (ok, raison)."""
    from . import preview as PV, drums as D
    files = []
    os.makedirs(os.path.dirname(opus), exist_ok=True)
    f = opus[:-5] + ".midi.txt"
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(f"len {dur:.6f}\n" + "\n".join(lines) + "\n")
    files.append(f)
    wav = opus[:-5] + ".wav"
    load = {"action": "drums", "op": "load", "block": "library", "kit": kit["id"], **D.resolve_mix(kit["id"], {})}
    settle = PV.BLOCK_LOAD_SETTLE_DG_S if kit.get("engine") == "drumgizmo" else PV.BLOCK_LOAD_SETTLE_S
    cmd = {"action": "preview", "seq": seq, "op": "render", "scene": scene, "out": wav, "tail": PV.BLOCK_TAIL_S,
           "chains": "Drums", "midis": f, "strip": "drumseq", "settle": PV.MIDI_CLONE_SETTLE_S, "_route": "preview"}
    try:
        got, pk = None, None
        for attempt in (1, 2):
            busy = PV.live_players_busy()
            if busy:
                return False, busy
            PV.write_command(load)
            time.sleep(settle * attempt)
            with __import__("contextlib").suppress(OSError):
                os.remove(C.PREVIEW_FILE)
            PV.write_command(dict(cmd, settle=cmd["settle"] * attempt))
            got = PV._poll_scene(seq, scene, timeout=150)
            pk = PV._peak_db(got, start=PV.MIDI_LEAD_IN, dur=2.0) if got and os.path.isfile(got) else None
            if pk is None or pk >= PV.SILENT_DB:
                break
            log.warning(f"kit {kit['id']} {scene} : début muet ({pk:.0f} dBFS), nouveau rendu plus patient")
        if not (got and os.path.isfile(got)):
            return False, "no clip rendered (check REAPER)"
        if pk is not None and pk < PV.SILENT_DB:
            return False, f"silent twice ({pk:.0f} dBFS): check the kit"
        if not PV._encode_opus(got, opus, start=PV.MIDI_LEAD_IN - PV.MIDI_KEEP_S):
            return False, "encoding failed"
        return True, None
    finally:
        for x in files + [wav]:
            with __import__("contextlib").suppress(OSError):
                os.remove(x)


def _get_kit(kit_id):
    from . import kits as K
    return K.get_kit(kit_id)


def render_kit(kit_id, seq_of, force=False):
    """Les démos d'un kit (les quatre phrases). Bloquant. {"status", "reason"?} comme le lot des démos."""
    from . import preview as PV
    k = _get_kit(kit_id)
    if not k:
        return {"status": "skipped", "reason": "unknown kit"}
    if k.get("role") != "drum":
        return {"status": "skipped", "reason": "a pad kit is heard pad by pad"}
    if k.get("available") is False:
        return {"status": "skipped", "reason": k.get("unavailable_why") or "not on this machine"}
    if not force and demo(k)["status"] == "ready":
        return {"status": "skipped", "reason": "up to date"}
    from . import kit_import as KI
    net = gm_net(k)
    d = kit_dir(kit_id)
    old = (entry(kit_id) or {}).get("clips") or {}
    clips, fails, new = {}, [], 0
    for ref in REFS:
        p = _ref_path(ref)
        if not p:
            fails.append(f"{ref}: reference missing")
            continue
        dur, lines = PV.midi_events(p, offset=PV.MIDI_LEAD_IN)
        lines = KI.translate_lines(lines, net)          # un kit non GM : chaque note GM vers SA pièce (le filet)
        opus = os.path.join(d, ref.split("/")[-1] + ".opus")
        ok, why = _render(k, dur, lines, opus, seq_of(), f"kit-{kit_id}-{ref.split('/')[-1]}")
        if not ok:
            fails.append(f"{ref}: {why}")
            if old.get(ref):
                clips[ref] = old[ref]                    # l'ancien clip reste tant qu'aucun nouveau ne le remplace
            continue
        clips[ref] = {"file": C.rel_posix(opus), "seconds": PV._clip_duration(opus), "sha256": _sha(opus),
                      "ref_sha": _sha(p)}
        new += 1
    if clips:
        store._write_json_atomic(os.path.join(d, "preview.json"), {
            "kit": kit_id, "name": k.get("name"), "engine": k.get("engine"), "fingerprint": _kit_fp(k),
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "clips": clips})
    if fails:
        return {"status": "failed", "reason": "; ".join(fails) + (f" ({new} of {len(REFS)} rendered)" if new else "")}
    return {"status": "rendered"}


def factory_kits():
    from . import kits as K
    return [k["id"] for k in K.list_kits() if k.get("factory") and k.get("role") == "drum" and k.get("available") is not False]


# ── un groove sur un kit, à la demande ─────────────────────────────────────────────────────────────────────────────
_GOK = {"phase": "idle", "key": None, "clip": None, "error": None, "gen": 0}


def gok_status():
    return {k: _GOK[k] for k in ("phase", "key", "clip", "error")}


def tempo_of(gid, mode, patch_bpm=None):
    """Le tempo d'écoute : celui du fichier, sa moitié, ou celui du patch qui joue (120 sinon)."""
    from . import grooves as G
    a = G.analyze(os.path.join(G.GROOVES_DIR, G._safe_id(gid) + ".mid")) or {}
    fb = a.get("bpm") or 120.0
    if mode == "half":
        return round(fb / 2, 1)
    if mode == "patch":
        return float(patch_bpm or 120.0)
    return float(fb)


def groove_lines(path, bpm, min_bars=GOK_MIN_BARS):
    """(durée, lignes golem_preview) : le groove ENTIER une fois, bouclé jusqu'à `min_bars` mesures s'il est court."""
    from . import preview as PV
    hits, length, bar = PV._mid_hits(path)
    loops = max(1, math.ceil(min_bars * bar / length - 1e-9)) if length else 1
    spb = 60.0 / float(bpm)
    lines = []
    for k in range(loops):
        for q, note, vel in hits:
            s = PV.MIDI_LEAD_IN + (k * length + q) * spb
            lines.append(f"n {s:.6f} {s + PV.DRUMS_HIT_S:.6f} {PV.DRUMS_CHANNEL} {note} {vel}")
    return PV.MIDI_LEAD_IN + loops * length * spb, lines


def gok_key(gid, kit_id, bpm):
    from . import grooves as G
    p = os.path.join(G.GROOVES_DIR, G._safe_id(gid) + ".mid")
    k = _get_kit(kit_id) or {}
    raw = json.dumps([_sha(p), kit_id, _kit_fp(k), round(float(bpm), 1)])
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def hear(gid, kit_id, bpm, seq):
    """Lance (thread) ou rend tout de suite l'écoute d'un groove sur un kit. Le statut se lit par gok_status()."""
    from . import grooves as G
    p = os.path.join(G.GROOVES_DIR, G._safe_id(gid) + ".mid")
    k = _get_kit(kit_id)
    if not os.path.isfile(p) or not k:
        _GOK.update(phase="error", key=None, clip=None, error="unknown groove or kit")
        return gok_status()
    key = gok_key(gid, kit_id, bpm)
    opus = os.path.join(GOK_DIR, key + ".opus")
    _GOK["gen"] += 1
    if os.path.isfile(opus):
        os.utime(opus)
        _GOK.update(phase="ready", key=key, clip="/" + C.rel_posix(opus), error=None)
        return gok_status()
    _GOK.update(phase="render", key=key, clip=None, error=None)
    threading.Thread(target=_hear, args=(_GOK["gen"], p, k, bpm, key, opus, seq), daemon=True).start()
    return gok_status()


def _hear(gen, path, kit, bpm, key, opus, seq):
    from . import preview as PV
    import glob

    def done(**kw):
        if _GOK["gen"] == gen:
            _GOK.update(**kw)
    if not PV._gen_lock.acquire(blocking=False):
        return done(phase="error", error="a demo is already rendering")
    try:
        from . import kit_import as KI
        dur, lines = groove_lines(path, bpm)
        lines = KI.translate_lines(lines, gm_net(kit))  # un kit non GM : chaque note GM vers SA pièce (le filet)
        ok, why = _render(kit, dur, lines, opus, seq, f"gok-{key}")
        if not ok:
            return done(phase="error", error=why)
        clips = sorted(glob.glob(os.path.join(GOK_DIR, "*.opus")), key=os.path.getmtime, reverse=True)
        for old in clips[GOK_KEEP:]:
            with __import__("contextlib").suppress(OSError):
                os.remove(old)
        done(phase="ready", clip="/" + C.rel_posix(opus), error=None)
    except Exception as e:                                # une écoute ratée le dit, ne casse rien
        log.error(f"groove sur kit : {e}")
        done(phase="error", error=str(e))
    finally:
        PV._gen_lock.release()


def render_blob(data, kit_id, tempo="file", mapping=None, seq=0, patch_bpm=None):
    """UN GROOVE NON INSTALLÉ rendu sur un kit (golem.fm « Render on my golem », job `groove-render`, décidé par le
    mainteneur le 2026-11-18). `data` = les octets du .mid ; `mapping` = sa correspondance de notes, appliquée en
    mémoire ; `tempo` = file | half | patch | un nombre de BPM. Le fichier n'entre PAS dans library/grooves : il vit
    dans un fichier temporaire le temps du rendu. Synchrone ; un seul rendu à la fois (le verrou des démos).
    Rend {ok, opus (chemin relatif au dépôt), bpm, kit} ou {ok: False, error}. L'appelant retire le clip."""
    import tempfile
    from . import grooves as G, kit_import as KI, preview as PV, tones_sync as TS
    if not data or data[0:4] != b"MThd":
        return {"ok": False, "error": "not a Standard MIDI File (.mid)"}
    kit = _get_kit(kit_id)
    if not kit:
        return {"ok": False, "error": f"kit « {kit_id} » not found on this golem"}
    ok, why = TS.kit_available(kit)
    if ok is False:
        return {"ok": False, "error": f"kit « {kit_id} » cannot play here: {why}"}
    try:
        m = {int(k): int(v) for k, v in (mapping or {}).items()}
    except (TypeError, ValueError, AttributeError):
        return {"ok": False, "error": "remap: {note: note}"}
    if any(not (0 <= k < 128 and 0 <= v < 128) for k, v in m.items()):
        return {"ok": False, "error": "notes are 0..127"}
    if m:
        data = G._remap_bytes(data, m)
    fd, tmp = tempfile.mkstemp(prefix="golem-groove-", suffix=".mid")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        a = G.analyze(tmp) or {}
        fb = float(a.get("bpm") or 120.0)
        try:
            bpm = {"file": fb, "half": round(fb / 2, 1), "patch": float(patch_bpm or 120.0)}.get(tempo) or float(tempo)
        except (TypeError, ValueError):
            return {"ok": False, "error": "tempo: file, half, patch or a number of BPM"}
        if not 20 <= bpm <= 400:
            return {"ok": False, "error": "tempo out of range (20–400 BPM)"}
        key = hashlib.sha1(json.dumps([hashlib.sha256(data).hexdigest(), kit_id, _kit_fp(kit), round(bpm, 1)]).encode()).hexdigest()[:16]
        opus = os.path.join(C.PREVIEWS_DIR, "groove-render", key + ".opus")
        if not PV._gen_lock.acquire(blocking=False):
            return {"ok": False, "error": "a demo is already rendering — try again in a moment"}
        try:
            dur, lines = groove_lines(tmp, bpm)
            lines = KI.translate_lines(lines, gm_net(kit))
            done, why = _render(kit, dur, lines, opus, seq, f"gr-{key}")
        finally:
            PV._gen_lock.release()
        if not done:
            return {"ok": False, "error": why or "the render failed"}
        return {"ok": True, "opus": C.rel_posix(opus), "bpm": round(bpm, 1), "kit": kit_id}
    finally:
        with __import__("contextlib").suppress(OSError):
            os.remove(tmp)


# ── ce que la page montre ─────────────────────────────────────────────────────────────────────────────────────────
def catalog():
    """Library ▸ Drums ▸ Kits : chaque kit (batteries et pads) avec son type de dessin, son origine et ses démos."""
    from . import kits as K
    out = []
    for k in K.list_kits():
        imp = k.get("imported") if isinstance(k.get("imported"), dict) else None
        out.append({**{x: k.get(x) for x in ("id", "name", "role", "engine", "factory", "bank", "hint", "available",
                                              "unavailable_why", "pads")},
                    "mics": len(k.get("mix") or []) or None, "imported": imp,
                    "type": kit_type(k), "demo": demo(k)})
    return {"kits": out}


# ── vers golem.fm (sa page Drums, 2026-11-15) ─────────────────────────────────────────────────────────────────────
# Ce que golem.fm doit LIRE plutôt que deviner : le type de photo (notre règle, kit_type — jamais recopiée là-bas),
# les pièces, les micros, les pads dans l'ordre, la source. Les crédits connus seulement : rien d'inventé (les kits
# avldrums n'ont pas de licence écrite dans le dépôt ; leur source, oui).
FACTORY_CREDITS = {
    "drums-aasimonster": {"credit": "The Aasimonster v2.1 — the DrumGizmo team", "licence": "CC BY 4.0",
                          "source": "https://drumgizmo.org/wiki/doku.php?id=kits:the_aasimonster"},
}


def _pad_label(sample):
    import re
    stem = os.path.splitext(os.path.basename(str(sample)))[0]
    return re.sub(r"^\d+[_\- ]*", "", stem).replace("_", " ") or stem


def kit_card(k):
    """La fiche d'un kit pour le manifeste (extra du pack local:kit-*) : {type, hint, pieces, notes, mics, bank, pads, samples,
    credit}. pads : les 16 dans l'ordre du contrôleur, le pad 1 en bas à gauche."""
    out = {"type": kit_type(k), "hint": k.get("hint") or None, "bank": k.get("bank") or None}
    if isinstance(k.get("notes"), dict) and k["notes"]:
        out["pieces"] = sorted(k["notes"].keys())
        # la table JOUÉE (pièce → note MIDI ; General MIDI pour un kit importé) : golem.fm la montre sur la page du kit
        out["notes"] = {el: n for el, n in sorted(k["notes"].items()) if isinstance(n, int)}
    if k.get("mix"):
        out["mics"] = [{"name": m.get("name"), "group": m.get("group")} for m in k["mix"] if isinstance(m, dict)]
    pads = [p for p in k.get("pads") or [] if isinstance(p, dict) and p.get("sample")]
    if pads:
        # le NOM du fichier (sans chemin) : l'ordre des pads n'est pas celui des fichiers (pad 2 = 03_snare.wav), et
        # golem.fm retrouve le son d'un pad parmi les assets du pack par ce nom (2026-11-15)
        out["pads"] = [{"pad": i + 1, "note": p.get("note"), "label": _pad_label(p["sample"]),
                        "sample": os.path.basename(str(p["sample"]))} for i, p in enumerate(pads)]
        out["samples"] = len(pads)
    src = k.get("source") if isinstance(k.get("source"), dict) else None
    # la source d'un kit de pads d'usine est une note interne (en français, un chemin de développeur) : jamais telle quelle
    cred = FACTORY_CREDITS.get(k.get("id")) or (
        {"credit": "Synthesized by golem (drumsynth)", "licence": "golem's own: no third-party sample"}
        if src and str(src.get("licence") or "").startswith("own") else None)
    if not cred and k.get("engine") == "avldrums":
        cred = {"source": "avldrums.lv2 (AVL Drumkits)"}
    if cred:
        out["credit"] = {x: v for x, v in cred.items() if v}
    return {x: v for x, v in out.items() if v not in (None, [], {})}


def rendered():
    """Les démos de kits rendues ici : [{kit, factory, clips: {phrase: {sha256, seconds}}}] — le heartbeat (kit_previews)."""
    from . import kits as K
    out = []
    if not os.path.isdir(C.PREVIEWS_DIR):
        return out
    for d in sorted(os.listdir(C.PREVIEWS_DIR)):
        if not d.startswith("kit-"):
            continue
        e = store._read_json(os.path.join(C.PREVIEWS_DIR, d, "preview.json"), None)
        if not isinstance(e, dict) or not e.get("kit") or not e.get("clips"):
            continue
        k = K.get_kit(e["kit"]) or {}
        out.append({"kit": e["kit"], "factory": bool(k.get("factory")),
                    "clips": {r.split("/")[-1]: {"sha256": c.get("sha256"), "seconds": c.get("seconds")}
                              for r, c in e["clips"].items() if isinstance(c, dict)}})
    return out


def _is_user(kit_id):
    from . import kits as K
    k = K.get_kit(kit_id)
    return bool(k) and not k.get("factory")


def push(kit_id):
    """Envoie les démos d'un kit au blob store de golem.fm ; un clip envoyé est marqué (pushed = son sha256)."""
    from . import preview as PV
    e = entry(kit_id)
    if not e:
        return None
    sent = {}
    for ref, c in (e.get("clips") or {}).items():
        if c.get("pushed") == c.get("sha256"):
            continue
        one = PV.push_clip("kit-" + str(kit_id), ref.split("/")[-1], c.get("file") or "")
        if one:
            c["pushed"] = one["sha256"]
            sent[ref.split("/")[-1]] = {"sha256": one["sha256"], "seconds": c.get("seconds")}
    if sent:
        store._write_json_atomic(os.path.join(kit_dir(kit_id), "preview.json"), e)
    return {"kit": kit_id, "clips": sent} if sent else None


def push_user(kit_id):
    """Les démos d'un kit IMPORTÉ partent à golem.fm (les kits d'usine : jamais, golem.fm les a par ailleurs)."""
    if not _is_user(kit_id):
        return None
    r = push(kit_id)
    if r:
        log.info(f"démos de kit envoyées à golem.fm : {kit_id}")
    else:
        e = entry(kit_id) or {}
        if any(c.get("pushed") != c.get("sha256") for c in (e.get("clips") or {}).values()):
            log.warning(f"démos de kit NON envoyées à golem.fm : {kit_id} (injoignable ou pas appairé ; réessai au repos)")
    return r


def unpushed():
    """Un kit importé dont une démo n'est pas (ou plus) chez golem.fm, ou None."""
    if not os.path.isdir(C.PREVIEWS_DIR):
        return None
    for d in sorted(os.listdir(C.PREVIEWS_DIR)):
        if not d.startswith("kit-"):
            continue
        e = store._read_json(os.path.join(C.PREVIEWS_DIR, d, "preview.json"), None) or {}
        if e.get("kit") and any(c.get("pushed") != c.get("sha256") for c in (e.get("clips") or {}).values()) \
                and _is_user(e["kit"]):
            return e["kit"]
    return None
