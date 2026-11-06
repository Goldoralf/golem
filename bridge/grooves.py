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
            out.append({"id": gid, "name": tags.get("name") or gid, "file": C.rel(p),
                        "bytes": os.path.getsize(p), "mtime": os.path.getmtime(p),
                        "notes": notes, "bars": bars,
                        "genre": tags.get("genre"), "tempo": tags.get("tempo"),
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
