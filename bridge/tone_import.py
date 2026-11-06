# SPDX-License-Identifier: GPL-3.0-or-later
"""IMPORTER DES FICHIERS DE SON (Library ▸ Tones ▸ + Add ▸ Import files, docs/tone-import.md).

Un seul geste pour ce qu'on reçoit hors TONE3000 : un `.nam` (A1 ou A2), un module `.gcap`, un IR `.wav`, ou un
`.zip` qui mélange tout ça (les paquets de captures de golem, un dossier de .nam zippé). Avant 2026-10-24 il n'y avait
aucune porte pour un .nam : il fallait écrire le catalogue à la main — et une écriture à la main l'avait rendu illisible.

Ce qui entre est inscrit au catalogue (tones-index.json) comme n'importe quel tone ; ce qui ne peut pas jouer ICI est
dit, jamais deviné :
  - un `.nam` paramétrique (HyperWaveNet) ne joue que DANS un module .gcap : écarté, avec sa raison ;
  - une A2 (SlimmableContainer) sur un NAM qui ne la lit pas (rig.nam_unreadable) : inscrite, mais signalée ;
  - un `.wav` de plus de 2 s n'est pas un IR (les A/B d'écoute des paquets) : écarté.

Rien d'exécutable n'est jamais pris dans un paquet : des données seulement (JSON de .nam/.gcap, WAV)."""
import io
import json
import os
from pathlib import PurePosixPath
import re
import wave
import zipfile

from . import config as C
from .store import _read_json, _write_json_atomic

MAX_BYTES = 512 * 1024 * 1024            # un paquet de captures avec ses A/B pèse ~50 Mo
MAX_UNZIPPED = 1024 * 1024 * 1024        # garde-fou contre une archive qui se déplie à l'infini
IR_MAX_SECONDS = 2.0
DEST = ("assets", "models", "captures", "imported")
PARAMETRIC = "HyperWaveNet"
A2 = "SlimmableContainer"
# gear_type des métadonnées NAM -> nature de capture du catalogue ; sans métadonnée, amp-cab (comme tones_sync, faute de mieux)
_GEAR = {"amp": "amp", "amp_cab": "amp-cab", "amp_pedal": "amp", "amp_pedal_cab": "amp-cab", "pedal": "pedal",
         "pedal_amp": "amp", "preamp": "outboard", "studio": "outboard"}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:60] or "capture"


def _pretty(stem):
    s = re.sub(r"[-_]+", " ", str(stem)).strip()
    return s[:1].upper() + s[1:] if s else "Capture"


def _nam(data):
    """Le JSON d'un .nam, ou None s'il n'en est pas un."""
    try:
        d = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    return d if isinstance(d, dict) and d.get("architecture") and "weights" in d else None


def _wav_seconds(data):
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (wave.Error, EOFError, ValueError):
        return None


def _unreadable():
    from .rig import nam_unreadable
    try:
        return set(nam_unreadable())
    except Exception:
        return set()


class _Report:
    def __init__(self):
        self.installed, self.skipped, self.warnings, self.ignored = [], [], [], 0

    def skip(self, name, reason):
        self.skipped.append({"file": name, "reason": reason})

    def out(self):
        return {"ok": bool(self.installed), "installed": self.installed, "skipped": self.skipped,
                "warnings": self.warnings, "ignored": self.ignored}


def _write_model(rel, data):
    path = os.path.join(C.ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _put_tones(entries):
    """Inscrit (ou remplace, même id) des tones au catalogue, en une écriture."""
    if not entries:
        return
    cat = _read_json(C.CATALOG, {"tones": []}) or {"tones": []}
    ids = {e["id"] for e in entries}
    cat["tones"] = [t for t in cat.get("tones", []) if t.get("id") not in ids] + entries
    _write_json_atomic(C.CATALOG, cat)


def _check_nam(name, doc, rep, unreadable):
    """True si ce .nam peut entrer au catalogue ; dit pourquoi sinon, et prévient si cette machine ne le joue pas."""
    arch = doc.get("architecture")
    if arch == PARAMETRIC:
        rep.skip(name, "parametric source: it plays only inside a golem capture module (.gcap)")
        return False
    if arch in unreadable:
        rep.warnings.append(f"{name}: this golem's NAM cannot play {arch} (A2) captures yet")
    return True


def _nam_tone(tid, title, gear, models, origin):
    return {"id": tid, "title": title, "slug": tid, "creator": "imported", "gear": gear, "format": "nam",
            "amp": title, "brand": "Imported", "source_group": "import", "pack": False, "tags": ["import"],
            "models": models, "source": "import", "origin": origin, "private": True}


def _group_nams(group_name, files, rep, unreadable, origin):
    """Des .nam (nom, octets) d'un même dossier -> UN tone, un modèle par fichier."""
    tid = "imp-" + _slug(group_name)
    models, gears = [], []
    for name, data in files:
        doc = _nam(data)
        if doc is None:
            rep.skip(name, "not a NAM capture")
            continue
        if not _check_nam(name, doc, rep, unreadable):
            continue
        stem = PurePosixPath(name).stem
        rel = "/".join((*DEST, tid, _slug(stem) + ".nam"))
        _write_model(rel, data)
        gears.append(_GEAR.get(str((doc.get("metadata") or {}).get("gear_type") or "").lower(), "amp-cab"))
        models.append({"id": f"{tid}-{len(models) + 1}", "name": _pretty(stem), "file": rel,
                       "arch": "2" if doc.get("architecture") == A2 else "1"})
    if not models:
        return None
    gear = max(set(gears), key=gears.count)
    return _nam_tone(tid, _pretty(group_name), gear, models, origin)


def _gcap(name, data, rep):
    from . import capture_module as CM
    try:
        entry = CM.install(json.loads(data))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
        rep.skip(name, f"not a valid golem capture module: {e}")
        return
    rep.installed.append({"id": entry["id"], "title": entry.get("title"), "kind": "module", "models": 1})


def _ir(name, data, rep, in_zip=False):
    from . import irlib
    secs = _wav_seconds(data)
    if secs is None:
        rep.skip(name, "not a readable WAV file")
        return
    if secs > IR_MAX_SECONDS:
        if in_zip:
            rep.ignored += 1             # les A/B d'écoute d'un paquet : pas un son manqué, rien à signaler un par un
        else:
            rep.skip(name, f"audio of {secs:.1f} s, not an impulse response")
        return
    r = irlib.save_upload(PurePosixPath(name).name, data)
    if r.get("ok"):
        rep.installed.append({"id": r["id"], "title": r["name"], "kind": "ir", "models": 1})
    else:
        rep.skip(name, r.get("error") or "IR refused")


def _safe_rel(rel):
    """Un chemin de modèle d'un fragment de catalogue : sous assets/models/ ou assets/irs/, sans remontée."""
    parts = PurePosixPath(str(rel or "").replace("\\", "/")).parts
    return (len(parts) >= 3 and parts[0] == "assets" and parts[1] in ("models", "irs")
            and not any(p in ("..", "") for p in parts) and not PurePosixPath(rel).is_absolute())


def _from_zip(zname, data, rep, unreadable):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        rep.skip(zname, "not a valid ZIP archive")
        return
    infos = [i for i in z.infolist() if not i.is_dir() and ".." not in PurePosixPath(i.filename).parts
             and not i.filename.startswith(("/", "__MACOSX/"))]
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        rep.skip(zname, "archive too large once unpacked")
        return
    names = {i.filename: i for i in infos}
    used = set()
    stem = PurePosixPath(zname).stem
    origin = {"file": zname}

    # 1. LES FRAGMENTS DE CATALOGUE de golem (library/catalog/*.json : {"tones": [...]}) — les paquets de captures en
    #    portent un ; ses entrées gardent leur id, leurs noms de modèles (« HOT Amp Gain 29.9% … ») et leur nature
    tones = []
    for fn in names:
        p = PurePosixPath(fn)
        if p.suffix.lower() != ".json" or p.parent.name != "catalog" or p.parent.parent.name != "library":
            continue
        try:
            frag = json.loads(z.read(fn))
        except (ValueError, UnicodeDecodeError):
            continue
        root = str(p.parent.parent.parent)
        root = "" if root == "." else root + "/"
        for t in (frag.get("tones") if isinstance(frag, dict) else None) or []:
            if not isinstance(t, dict) or not t.get("id"):
                continue
            keep = []
            for m in t.get("models") or []:
                rel = str((m or {}).get("file") or "").replace("\\", "/")
                src = root + rel
                if not _safe_rel(rel) or src not in names:
                    continue
                used.add(src)
                blob = z.read(src)
                if rel.endswith(".nam"):
                    doc = _nam(blob)
                    if doc is None or not _check_nam(src, doc, rep, unreadable):
                        continue
                elif rel.endswith(".gcap"):
                    _gcap(src, blob, rep)
                    continue
                _write_model(rel, blob)
                keep.append(m)
            if keep:
                tones.append({**t, "models": keep, "source": t.get("source") or "import", "private": True})
        used.add(fn)
    _put_tones(tones)
    for t in tones:
        rep.installed.append({"id": t["id"], "title": t.get("title"), "kind": "tone", "models": len(t["models"])})

    # 2. ce que les fragments n'ont pas nommé : modules, .nam groupés par dossier, IR courts
    groups = {}
    for fn in sorted(names):
        if fn in used:
            continue
        ext = PurePosixPath(fn).suffix.lower()
        if ext == ".gcap":
            _gcap(fn, z.read(fn), rep)
        elif ext == ".nam":
            parent = PurePosixPath(fn).parent
            label = stem if str(parent) in (".", "models") else f"{stem} {parent.name}"
            groups.setdefault(label, []).append((fn, z.read(fn)))
        elif ext == ".wav":
            _ir(fn, z.read(fn), rep, in_zip=True)
        else:
            rep.ignored += 1
    entries = [e for e in (_group_nams(label, files, rep, unreadable, origin) for label, files in groups.items()) if e]
    _put_tones(entries)
    for e in entries:
        rep.installed.append({"id": e["id"], "title": e["title"], "kind": "tone", "models": len(e["models"])})


def import_file(filename, data):
    """Importe UN fichier déposé (.nam, .gcap, .wav, .zip). Rend {ok, installed, skipped, warnings, ignored}."""
    rep = _Report()
    name = PurePosixPath(str(filename or "").replace("\\", "/")).name or "file"
    if not data:
        rep.skip(name, "empty file")
        return rep.out()
    if len(data) > MAX_BYTES:
        rep.skip(name, "file too large (more than 512 MB)")
        return rep.out()
    ext = PurePosixPath(name).suffix.lower()
    unreadable = _unreadable()
    if ext == ".zip":
        _from_zip(name, data, rep, unreadable)
    elif ext == ".nam":
        e = _group_nams(PurePosixPath(name).stem, [(name, data)], rep, unreadable, {"file": name})
        if e:
            _put_tones([e])
            rep.installed.append({"id": e["id"], "title": e["title"], "kind": "tone", "models": 1})
    elif ext == ".gcap":
        _gcap(name, data, rep)
    elif ext == ".wav":
        _ir(name, data, rep)
    else:
        rep.skip(name, "unsupported file: import .nam, .gcap, .wav or .zip")
    return rep.out()
