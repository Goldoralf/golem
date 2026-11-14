# SPDX-License-Identifier: GPL-3.0-or-later
"""Grooves — patterns MIDI de batterie (objets de bibliothèque référencés par le bloc
`drums`, param `patterns`/`fills`). Un groove = library/grooves/<id>.mid, un Standard
MIDI File en convention batterie General MIDI (36=kick, 38=snare, 42=hi-hat fermé…).

Le bloc drums porte des CHEMINS relatifs de .mid ; ce module = la LIB browsable + l'import
de .mid GM standard (portable depuis n'importe quel pack de loops). Le parse (note-ons,
mesures) est purement informatif pour l'UI — golem_drums.lua reparse le .mid au play.
"""
import os, re, struct

from . import config as C

GROOVES_DIR = os.path.join(C.ROOT, "library", "grooves")
_META = os.path.join(GROOVES_DIR, "index.json")   # sidecar id -> {genre, tempo, bars} (packs golem.fm)
_SAFE = re.compile(r"[^\w\-]+")


def _read_meta():
    try:
        import json
        with open(_META) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_meta(m):
    import json, tempfile
    os.makedirs(GROOVES_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=GROOVES_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(m, f, indent=1)
    os.replace(tmp, _META)


def _safe_id(s):
    return _SAFE.sub("-", str(s or "").strip().lower()).strip("-")[:60] or "groove"


def _u16(b, i):
    return b[i] * 256 + b[i + 1]


def _u32(b, i):
    return (b[i] << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]


def _probe(path):
    """(note_ons, bars, ppq) d'un SMF, ou (None, None, None) si illisible. Tolérant."""
    try:
        b = open(path, "rb").read()
    except OSError:
        return None, None, None
    if len(b) < 14 or b[0:4] != b"MThd":
        return None, None, None
    ppq = _u16(b, 12)
    if ppq == 0 or ppq >= 0x8000:            # 0 ou SMPTE : on ne calcule pas les mesures
        ppq = ppq or 480
    notes, max_tick, bar_ppq = 0, 0, 4 * ppq      # mesures calculées en 4/4 (suffisant pour l'affichage)
    pos = 0
    while pos + 8 <= len(b):
        cid, ln = b[pos:pos + 4], _u32(b, pos + 4)
        tstart = pos + 8
        pos = tstart + ln
        if cid != b"MTrk":
            continue
        i, tend, abstick, running = tstart, min(tstart + ln, len(b)), 0, None
        while i < tend:
            v = 0
            while i < tend:                  # VLQ delta-time
                x = b[i]; i += 1; v = v * 128 + (x & 0x7F)
                if x < 128:
                    break
            abstick += v
            if i >= tend:
                break
            st = b[i]
            if st >= 0x80:
                running = st; i += 1
            else:
                st = running
            if st is None:
                break
            if st == 0xFF:                   # méta : on saute (type + longueur VLQ + données)
                i += 1
                ml = 0
                while i < tend:
                    x = b[i]; i += 1; ml = ml * 128 + (x & 0x7F)
                    if x < 128:
                        break
                i += ml
            elif st in (0xF0, 0xF7):         # sysex
                sl = 0
                while i < tend:
                    x = b[i]; i += 1; sl = sl * 128 + (x & 0x7F)
                    if x < 128:
                        break
                i += sl; running = None
            else:
                hi = st & 0xF0
                if hi == 0x90:               # note-on
                    if i + 1 < tend and b[i + 1] > 0:
                        notes += 1
                    i += 2
                elif hi in (0x80, 0xA0, 0xB0, 0xE0):
                    i += 2
                elif hi in (0xC0, 0xD0):
                    i += 1
                else:
                    break
            if abstick > max_tick:
                max_tick = abstick
    bars = max(1, -(-max_tick // bar_ppq)) if bar_ppq else None    # ceil
    return notes, bars, ppq


def list_grooves():
    out = []
    meta = _read_meta()
    if os.path.isdir(GROOVES_DIR):
        for fn in sorted(os.listdir(GROOVES_DIR)):
            if not fn.lower().endswith(".mid"):
                continue
            p = os.path.join(GROOVES_DIR, fn)
            gid = fn[:-4]
            notes, bars, ppq = _probe(p)
            tags = meta.get(gid) or {}
            # la lecture complète (2026-11-14) : la signature, la longueur réelle, le tempo du fichier, les voix
            a = analyze(p) or {}
            out.append({"id": gid, "name": tags.get("name") or gid, "file": C.rel(p),
                        "bytes": os.path.getsize(p), "mtime": os.path.getmtime(p),
                        "notes": a.get("hits", notes), "bars": a.get("bars", bars),
                        "meter": a.get("meter") or "4/4", "file_bpm": a.get("bpm"), "played": bool(a.get("played")),
                        "voices": {str(k): v for k, v in (a.get("voices") or {}).items()},
                        "unknown": a.get("unknown") or [], "remap": tags.get("remap") or {},
                        "use": tags.get("use") or guess_use(gid, a),
                        "genre": tags.get("genre"), "tempo": tags.get("tempo"), "kit": tags.get("kit"),
                        "pack": tags.get("pack"), "factory": bool(tags.get("factory"))})
    return out


def save_groove(name, data, meta=None):
    """Import d'un .mid GM (corps brut). Valide l'en-tête SMF. Rend {ok, groove} ou {ok:False, error}.
    `meta` (optionnel, packs golem.fm) = {genre, tempo, bars, kit, pack} persisté dans le sidecar
    index.json (`kit` = suggestion de kit Add.12 ; `pack` = nom du pack d'origine Add.14)."""
    if not data or data[0:4] != b"MThd":
        return {"ok": False, "error": "not a Standard MIDI File (.mid)"}
    if len(data) > 2 * 1024 * 1024:
        return {"ok": False, "error": "file too large (>2 MB)"}
    gid = _safe_id(re.sub(r"\.midi?$", "", str(name or ""), flags=re.I))
    os.makedirs(GROOVES_DIR, exist_ok=True)
    path = os.path.join(GROOVES_DIR, gid + ".mid")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    if isinstance(meta, dict):
        tags = {k: meta.get(k) for k in ("genre", "tempo", "bars", "kit", "pack") if meta.get(k) is not None}
        if tags:
            idx = _read_meta(); idx[gid] = tags; _write_meta(idx)
    notes, bars, _ = _probe(path)
    return {"ok": True, "groove": {"id": gid, "name": gid,
            "file": C.rel(path), "notes": notes, "bars": bars}}


# ── songs (arrangements golem.fm, contrat Addendum 12) — clé réservée "_songs" du sidecar ──
def save_song(name, kit, steps, mode="once"):
    """Persiste un arrangement {steps:[{id,times}], kit?} sous _songs. times : 0 = infini (∞).
    Un song ne consomme AUCUN slot moteur : c'est une liste de références vers des grooves."""
    sid = _safe_id(name)
    idx = _read_meta()
    songs = idx.setdefault("_songs", {})
    songs[sid] = {"name": str(name or sid), "kit": kit or None, "mode": mode, "steps": list(steps)}
    _write_meta(idx)
    return {"id": sid, "name": str(name or sid), "kit": kit or None, "mode": mode, "steps": list(steps)}


def list_songs():
    """Arrangements connus, avec steps filtrés sur les grooves ENCORE présents sur disque."""
    out = []
    for sid, s in sorted((_read_meta().get("_songs") or {}).items()):
        steps = [st for st in (s.get("steps") or [])
                 if os.path.isfile(os.path.join(GROOVES_DIR, _safe_id(st.get("id")) + ".mid"))]
        out.append({"id": sid, "name": s.get("name") or sid, "kit": s.get("kit"),
                    "mode": s.get("mode") or "once", "steps": steps})
    return out


def delete_song(sid):
    idx = _read_meta()
    songs = idx.get("_songs") or {}
    if _safe_id(sid) not in songs:
        return {"ok": False, "error": "unknown song"}
    del songs[_safe_id(sid)]
    _write_meta(idx)
    return {"ok": True}


def delete_groove(gid):
    path = os.path.join(GROOVES_DIR, _safe_id(gid) + ".mid")
    if not os.path.isfile(path):
        return {"ok": False, "error": "unknown groove"}
    os.remove(path)
    # l'original d'un groove remappé part avec lui (il n'a plus de sens seul)
    with __import__("contextlib").suppress(OSError):
        os.remove(os.path.join(GROOVES_DIR, ".orig", _safe_id(gid) + ".mid"))
    return {"ok": True}


# ── lecture COMPLÈTE d'un SMF (au-delà de _probe, qui ne fait que compter) ────────────────
# `_probe` sert à l'UI (combien de frappes, combien de mesures). Ici on veut les ÉVÉNEMENTS :
# le bloc Standard rend la batterie dans sa propre liste, à côté du piano et de la basse, pour
# qu'ils partagent une seule tête de lecture (docs/standards.md, Addendum 5).
def read_smf(path):
    """{ppq, num, den, bars, events:[(tick, note, vel)]} ou None si illisible.

    Tolérant : running status, méta ignorées sauf la signature, SysEx sautés. Ne lève jamais.
    """
    try:
        b = open(path, "rb").read()
    except OSError:
        return None
    if len(b) < 14 or b[0:4] != b"MThd":
        return None
    ppq = _u16(b, 12)
    if not (0 < ppq < 0x8000):
        ppq = 480
    num, den, ev, pos = 4, 4, [], 0
    while pos + 8 <= len(b):
        cid, ln = b[pos:pos + 4], _u32(b, pos + 4)
        t0 = pos + 8
        pos = t0 + ln
        if cid != b"MTrk":
            continue
        i, tend, abst, run = t0, min(t0 + ln, len(b)), 0, None
        while i < tend:
            v = 0
            while i < tend:                       # delta-time VLQ
                x = b[i]; i += 1; v = v * 128 + (x & 0x7F)
                if x < 128:
                    break
            abst += v
            if i >= tend:
                break
            st = b[i]
            if st >= 0x80:
                run = st; i += 1
            else:
                st = run                          # running status
            if st is None:
                break
            hi = st & 0xF0
            if hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                if i + 1 >= tend:
                    break
                d1, d2 = b[i], b[i + 1]; i += 2
                if hi == 0x90 and d2 > 0:
                    ev.append((abst, d1, d2))
            elif hi in (0xC0, 0xD0):
                i += 1
            elif st == 0xFF:
                if i >= tend:
                    break
                ty = b[i]; i += 1; l = 0
                while i < tend:
                    x = b[i]; i += 1; l = l * 128 + (x & 0x7F)
                    if x < 128:
                        break
                if ty == 0x58 and l >= 2 and i + 1 < tend:      # time signature
                    num, den = b[i], 2 ** b[i + 1]
                i += l
            elif st in (0xF0, 0xF7):
                l = 0
                while i < tend:
                    x = b[i]; i += 1; l = l * 128 + (x & 0x7F)
                    if x < 128:
                        break
                i += l
            else:
                break
    if not ev:
        return None
    ev.sort()
    bar_ticks = num * ppq * 4 // den
    bars = max(1, -(-(max(t for t, _, _ in ev) + 1) // bar_ticks))   # arrondi SUPÉRIEUR
    return {"ppq": ppq, "num": num, "den": den, "bars": bars, "events": ev}


# ── CE QUE DIT UN GROOVE (docs/drums-library.md §3, maquette validée le 2026-11-14) ─────────────────────────────────
# Les imports sont de toutes formes : 1, 2, 4, 8 mesures, 4/4 ou 6/8, joués ou quantifiés, au mapping de leur
# bibliothèque. On lit la SIGNATURE (1re), la LONGUEUR (la fin de piste, pas seulement la dernière frappe : une mesure
# qui finit sur un silence reste une mesure), le TEMPO du fichier, les voix, et les notes qu'aucun kit ne joue.
# Le mapping General MIDI des pièces qu'un kit du rack sait jouer (avldrums, drumgizmo, pads) :
KIT_NOTES = {35: "kick", 36: "kick", 37: "rim", 38: "snare", 39: "clap", 40: "snare", 41: "tom", 42: "hats",
             43: "tom", 44: "pedal hat", 45: "tom", 46: "open hat", 47: "tom", 48: "tom", 49: "crash", 50: "tom",
             51: "ride", 52: "china", 53: "ride bell", 54: "tambourine", 55: "splash", 56: "cowbell", 57: "crash",
             59: "ride"}
# les cibles proposées pour une note inconnue (une par pièce)
MAP_TARGETS = [(36, "Kick"), (38, "Snare"), (37, "Rim"), (39, "Clap"), (42, "Hi-hat"), (44, "Pedal hat"),
               (46, "Open hat"), (49, "Crash"), (51, "Ride"), (53, "Ride bell"), (52, "China"), (55, "Splash"),
               (48, "High tom"), (45, "Mid tom"), (41, "Floor tom"), (56, "Cowbell"), (54, "Tambourine")]
USES = ("loop", "oneshot", "fill", "intro", "end")
_ANALYSIS = {}


def analyze(path):
    """{num, den, meter, bars, beats, bpm, hits, voices {note: n}, unknown [notes], played} — None si illisible.
    `played` : plus d'un quart des frappes hors de la grille (doubles croches et triolets de croches), à 1/32 de temps
    près — un jeu humain enregistré, pas un motif quantifié."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime, st.st_size)
    if key in _ANALYSIS:
        return _ANALYSIS[key]
    try:
        b = open(path, "rb").read()
    except OSError:
        return None
    if len(b) < 14 or b[0:4] != b"MThd":
        return None
    ppq = _u16(b, 12)
    if not (0 < ppq < 0x8000):
        return None
    num = den = None
    tempo, ev, last, pos = None, [], 0, 14
    while pos + 8 <= len(b):
        cid, ln = b[pos:pos + 4], _u32(b, pos + 4)
        i, tend = pos + 8, min(pos + 8 + ln, len(b))
        pos = pos + 8 + ln
        if cid != b"MTrk":
            continue
        t, run = 0, None
        while i < tend:
            v = 0
            while i < tend:
                x = b[i]; i += 1; v = v * 128 + (x & 0x7F)
                if x < 128:
                    break
            t += v
            if i >= tend:
                break
            s = b[i]
            if s >= 0x80:
                i += 1
                if s < 0xF0:
                    run = s
            else:
                s = run
            if s is None:
                break
            if s == 0xFF:
                ty = b[i]; i += 1; ml = 0
                while i < tend:
                    x = b[i]; i += 1; ml = ml * 128 + (x & 0x7F)
                    if x < 128:
                        break
                d = b[i:i + ml]; i += ml
                if ty == 0x58 and ml >= 2 and num is None:
                    num, den = d[0], 2 ** d[1]
                elif ty == 0x51 and ml == 3 and tempo is None:
                    tempo = round(60e6 / max(1, int.from_bytes(d, "big")), 1)
                last = max(last, t)                      # la fin de piste (0x2F) compte : un silence final reste
            elif s in (0xF0, 0xF7):
                sl = 0
                while i < tend:
                    x = b[i]; i += 1; sl = sl * 128 + (x & 0x7F)
                    if x < 128:
                        break
                i += sl; run = None
            else:
                hi = s & 0xF0
                if hi in (0xC0, 0xD0):
                    i += 1
                    continue
                if i + 1 >= tend:
                    break
                d1, d2 = b[i], b[i + 1]; i += 2
                if hi == 0x90 and d2 > 0:
                    ev.append((t, d1))
                last = max(last, t)
    if not ev:
        return None
    num, den = num or 4, den or 4
    bar = ppq * 4 * num / den
    import math
    bars = max(1, math.ceil(last / bar - 1e-3))
    voices = {}
    for _t, n in ev:
        voices[n] = voices.get(n, 0) + 1
    grid = [ppq / 4, ppq / 3]                            # doubles croches, triolets de croches
    off = sum(1 for t, _ in ev if min(min(t % g, g - t % g) for g in grid) > ppq / 32)
    out = {"num": num, "den": den, "meter": f"{num}/{den}", "bars": bars, "beats": round(bars * bar / ppq, 3),
           "bpm": tempo, "hits": len(ev), "voices": voices,
           "unknown": sorted(n for n in voices if n not in KIT_NOTES), "played": off > len(ev) / 4}
    _ANALYSIS[key] = out
    return out


def guess_use(gid, a):
    """L'usage par défaut, lu dans le nom : fill, intro, end/outro ; un long jeu (8 mesures et plus) joué une fois."""
    n = str(gid).lower()
    for w, u in (("fill", "fill"), ("intro", "intro"), ("outro", "end"), ("end", "end"), ("break", "fill")):
        if w in n:
            return u
    return "oneshot" if a and a["bars"] >= 8 and a["played"] else "loop"


def set_use(gid, use):
    gid = _safe_id(gid)
    if use not in USES:
        return {"ok": False, "error": f"use: one of {', '.join(USES)}"}
    if not os.path.isfile(os.path.join(GROOVES_DIR, gid + ".mid")):
        return {"ok": False, "error": "unknown groove"}
    idx = _read_meta()
    idx.setdefault(gid, {})["use"] = use
    _write_meta(idx)
    return {"ok": True, "use": use}


# ── une note inconnue, associée à une pièce : le .mid est RÉÉCRIT (le moteur le relit tel quel au jeu), l'original
# gardé à côté (library/grooves/.orig/, jamais servi) ; un mapping vide le rend tel qu'il était.
ORIG_DIR = os.path.join(GROOVES_DIR, ".orig")


def _remap_bytes(b, mapping):
    """Les note-on/off/aftertouch des notes du mapping, renumérotées ; tout le reste octet pour octet."""
    out = bytearray(b)
    pos = 14
    while pos + 8 <= len(b):
        cid, ln = b[pos:pos + 4], _u32(b, pos + 4)
        i, tend = pos + 8, min(pos + 8 + ln, len(b))
        pos = pos + 8 + ln
        if cid != b"MTrk":
            continue
        run = None
        while i < tend:
            while i < tend:
                x = b[i]; i += 1
                if x < 128:
                    break
            if i >= tend:
                break
            s = b[i]
            if s >= 0x80:
                i += 1
                if s < 0xF0:
                    run = s
            else:
                s = run
            if s is None:
                break
            if s == 0xFF:
                i += 1; ml = 0
                while i < tend:
                    x = b[i]; i += 1; ml = ml * 128 + (x & 0x7F)
                    if x < 128:
                        break
                i += ml
            elif s in (0xF0, 0xF7):
                sl = 0
                while i < tend:
                    x = b[i]; i += 1; sl = sl * 128 + (x & 0x7F)
                    if x < 128:
                        break
                i += sl; run = None
            else:
                hi = s & 0xF0
                if hi in (0xC0, 0xD0):
                    i += 1
                    continue
                if hi in (0x80, 0x90, 0xA0) and b[i] in mapping:
                    out[i] = mapping[b[i]]
                i += 2
    return bytes(out)


def remap(gid, mapping):
    """mapping {note: note} (les clés : des notes de ce groove) ; {} rend l'original. Les grooves d'usine : refusé."""
    gid = _safe_id(gid)
    path = os.path.join(GROOVES_DIR, gid + ".mid")
    if not os.path.isfile(path):
        return {"ok": False, "error": "unknown groove"}
    idx = _read_meta()
    if (idx.get(gid) or {}).get("factory"):
        return {"ok": False, "error": "a factory groove is not remapped"}
    try:
        m = {int(k): int(v) for k, v in (mapping or {}).items()}
    except (TypeError, ValueError):
        return {"ok": False, "error": "mapping: {note: note}"}
    if any(not (0 <= k < 128 and 0 <= v < 128) for k, v in m.items()):
        return {"ok": False, "error": "notes are 0..127"}
    orig = os.path.join(ORIG_DIR, gid + ".mid")
    if not os.path.isfile(orig):
        os.makedirs(ORIG_DIR, exist_ok=True)
        with open(path, "rb") as f, open(orig, "wb") as g:
            g.write(f.read())
    src = open(orig, "rb").read()
    data = _remap_bytes(src, m) if m else src
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    idx.setdefault(gid, {})["remap"] = {str(k): v for k, v in m.items()}
    if not m:
        idx[gid].pop("remap", None)
    _write_meta(idx)
    return {"ok": True, "remap": m}
