# SPDX-License-Identifier: GPL-3.0-or-later
"""Import d'un kit de BATTERIE par le rack — « + Add » dans Library ▸ Drums ▸ Drums (2026-10-11 ;
maquette mockups/drums-add.html, contrat docs/drums-kit.md §8).

Ce que ça rouvre : la porte fermée le 2026-09-18 (« importer une batterie : non »), aux conditions posées ce
jour-là — un kit DrumGizmo (drumkit.xml + midimap.xml + échantillons) ou un kit SFZ ; des gigaoctets ne passent
pas par un navigateur, donc LE RACK LIT un dossier de ce poste, une clé USB ou une URL ; la table pièce → note
se LIT dans le midimap (ou dans les clés du .sfz), elle n'est pas déclarée ; et le moteur doit exister sur CE
rack, sinon la feuille le dit et le bouton reste gris. Le kit installé est « this golem only » : seule sa CARTE
(nom, moteur, pièces, taille) part vers golem.fm (tones_sync : un kit sans échantillon = le JSON seul).

Trois temps, trois fonctions : `scan` (qu'y a-t-il à cet endroit), `read` (ce que le rack LIT dans le kit,
avant d'écrire quoi que ce soit) et `install` (copie + fiche kit). Les parseurs sont purs et testés
(tests/test_kit_import.py)."""
import os, re, sys, json, time, shutil, threading, uuid, struct
import xml.etree.ElementTree as ET

from . import config as C
from .golog import get as _get

log = _get("kit_import")

def _dest_root(engine):
    """Où un kit importé s'installe : library/drumkits/ (DrumGizmo) ou library/sfz/ (SFZ) — tous deux hors dépôt."""
    return os.path.join(C.ROOT, "library", "drumkits" if engine == "drumgizmo" else "sfz")


def _dl_dir():
    return os.path.join(C.ROOT, "library", ".import")       # téléchargements d'URL, extraits ici avant lecture
SCAN_MAX_DEPTH = 3
SCAN_MAX_HITS = 60
_AUDIO = (".wav", ".flac", ".ogg", ".aif", ".aiff")
_SAFE = re.compile(r"[^\w\-]+")


def _safe_id(s):
    return _SAFE.sub("-", str(s or "").strip().lower()).strip("-")[:60] or "kit"


# ── 1. LES PARSEURS (purs) ─────────────────────────────────────────────────────────────────────────────────

def parse_drumkit_xml(text):
    """drumkit.xml de DrumGizmo → {name, description, channels:[nom…], instruments:[{name, file}]}."""
    root = ET.fromstring(text)
    if root.tag.lower() != "drumkit":
        raise ValueError("not a DrumGizmo drumkit (root <%s>)" % root.tag)
    md = root.find("metadata")
    name = root.get("name") or (md.findtext("title") if md is not None else None) or ""
    desc = root.get("description") or (md.findtext("description") if md is not None else None) or ""
    channels = [c.get("name") for c in root.iter("channel") if c.get("name") and c.get("name") not in ()]
    # <channels> globales d'abord ; les <channel> d'un <instrument> sont des routages, pas des sorties
    glob_ch = root.find("channels")
    if glob_ch is not None:
        channels = [c.get("name") for c in glob_ch.findall("channel") if c.get("name")]
    instruments = [{"name": i.get("name") or "", "file": i.get("file") or ""}
                   for i in root.iter("instrument") if i.get("name")]
    return {"name": name.strip(), "description": desc.strip(), "channels": channels, "instruments": instruments}


def parse_midimap_xml(text):
    """midimap.xml de DrumGizmo → {note:int → nom d'instrument} (la PREMIÈRE table rencontrée par note)."""
    root = ET.fromstring(text)
    out = {}
    for m in root.iter("map"):
        try:
            note = int(m.get("note"))
        except (TypeError, ValueError):
            continue
        if 0 <= note <= 127 and m.get("instr") and note not in out:
            out[note] = m.get("instr")
    return out


# le nom d'une pièce → un élément de drumkits.ELEMENTS. Lu dans le NOM (midimap, fichier d'échantillon) :
# « Snare », « HiHat_Open », « Tom2-Rim », « 36-Kick »… Ce qu'on ne reconnaît pas rend None, et c'est dit.
_TOM_WORDS = {"hi": 1, "high": 1, "mid": 2, "low": 3, "floor": 3, "lowfloor": 4}


def guess_element(name, crash_seen=0):
    s = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    if not s:
        return None
    w = s.split()
    has = lambda *ks: any(k in s for k in ks)
    if has("kick", "bass drum", "bassdrum") or "bd" in w or "kck" in w:
        return "kick"
    if has("xstick", "x stick", "cross stick", "crossstick", "sidestick", "side stick"):
        return "snare-xstick"
    if has("rimshot") and not has("tom"):
        return "snare-rim"
    if has("snare", "snr") or "sd" in w or "sn" in w:
        if has("rim"):
            return "snare-rim"
        if has("cross", "side"):
            return "snare-xstick"
        return "snare"
    if has("hihat", "hi hat", "hat") or "hh" in w:
        if has("pedal", "foot", "chick", "stomp"):
            return "hh-pedal"
        if has("half", "semi", "mid", "loose"):
            return "hh-half"
        if has("splash"):
            return "hh-splash"
        if has("open", "opn"):
            return "hh-open-edge" if has("edge") else "hh-open"
        return "hh-closed-edge" if has("edge") else "hh-closed"
    if has("tom"):
        n = None
        m = re.search(r"tom\s*(\d)", s)
        compact = s.replace(" ", "")
        if m:
            n = int(m.group(1))
        elif "lowfloor" in compact or "floor2" in compact:
            n = 4
        elif "floor" in compact or "low" in compact:
            n = 3
        elif "mid" in compact:
            n = 2
        elif "high" in compact or "hi" in w:
            n = 1
        n = min(4, max(1, n or 1))
        return f"tom{n}-rim" if has("rim") else f"tom{n}"
    if has("ride"):
        return "ride-bell" if has("bell") else "ride-edge" if has("edge") else "ride"
    if has("china"):
        return "china"
    if has("splash"):
        return "splash"
    if has("crash"):
        m = re.search(r"crash\s*(\d)", s)
        n = int(m.group(1)) if m else (crash_seen + 1)
        n = 1 if n < 2 else 2
        return f"crash{n}-edge" if has("edge") else f"crash{n}"
    if has("cowbell", "bell", "block", "tamb", "clap", "stick", "perc"):
        return "aux1"
    return None


def pieces_from_names(note_names):
    """{note → nom} → ({element → note}, [noms non reconnus]). Une pièce ne prend qu'UNE note (la plus basse
    rencontrée) : les variantes d'une même pièce (deux charlestons fermés) restent dans `extra`."""
    pieces, unknown, extra, crash_seen = {}, [], {}, 0
    for note in sorted(note_names):
        nm = note_names[note]
        el = guess_element(nm, crash_seen)
        if el is None:
            unknown.append(f"{nm} ({note})")
            continue
        if el.startswith("crash") and el not in pieces:
            crash_seen += 1
        if el in pieces:
            extra.setdefault(el, []).append(note)
        else:
            pieces[el] = note
    return pieces, unknown, extra


# ── SFZ : les régions, avec #include, default_path, et l'héritage <global>/<master>/<group>/<region> ──
_SFZ_HDR = re.compile(r"<(global|master|group|region|control|curve|effect)>", re.I)
_SFZ_OPC = re.compile(r"([A-Za-z0-9_]+)=")


def parse_sfz(text, base_dir=None, _depth=0, _reader=None):
    """Le texte d'un .sfz → (régions [{opcodes…}], default_path). `_reader(path)` lit un #include ; sans
    lecteur les #include sont ignorés. Les opcodes d'un <region> héritent de <group>, <master>, <global>."""
    regions, default_path = [], ""
    ctx = {"global": {}, "master": {}, "group": {}}
    cur = None
    # commentaires // et /* */ retirés, puis les #include dépliés
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    lines = []
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        m = re.match(r'#include\s+"([^"]+)"', line)
        if m:
            inc = m.group(1)
            if _reader and _depth < 8:
                try:
                    sub, _dp = parse_sfz(_reader(inc), base_dir, _depth + 1, _reader)
                    regions.extend(sub)
                except Exception as e:                                   # un include absent n'annule pas le kit
                    log.warning("sfz #include %s : %s", inc, e)
            continue
        if line.startswith("#"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    # découpe par en-têtes <…>
    pos, parts = 0, []
    for m in _SFZ_HDR.finditer(body):
        parts.append((None, body[pos:m.start()]))
        pos = m.end()
        parts.append((m.group(1).lower(), None))
    parts.append((None, body[pos:]))
    kind = None
    def close():
        if kind == "region" and cur is not None:
            regions.append({**ctx["global"], **ctx["master"], **ctx["group"], **cur})
    for hdr, chunk in parts:
        if hdr is not None:
            close()
            kind, cur = hdr, {}
            if hdr in ("global", "master", "group"):
                ctx[hdr] = {}
                if hdr == "global":
                    ctx["master"], ctx["group"] = {}, {}
                elif hdr == "master":
                    ctx["group"] = {}
            continue
        if chunk is None or kind is None:
            continue
        # opcodes : clé=valeur, la valeur court jusqu'à la clé suivante (un chemin peut porter des espaces)
        keys = list(_SFZ_OPC.finditer(chunk))
        for i, k in enumerate(keys):
            v = chunk[k.end():keys[i + 1].start() if i + 1 < len(keys) else len(chunk)].strip()
            key = k.group(1).lower()
            if kind == "control":
                if key == "default_path":
                    default_path = v
                continue
            if kind in ("global", "master", "group"):
                ctx[kind][key] = v
            elif kind == "region":
                cur[key] = v
    close()
    return regions, default_path


def _note_of(v):
    """Un opcode de note SFZ : nombre, ou nom (c4, f#2, bb1 — c4 = 60 chez sfizz)."""
    s = str(v or "").strip().lower()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    m = re.fullmatch(r"([a-g])([#b]?)(-?\d+)", s)
    if not m:
        return None
    base = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}[m.group(1)]
    base += 1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0
    return (int(m.group(3)) + 1) * 12 + base


def sfz_note_names(regions):
    """Régions SFZ → {note → nom lisible} : la note d'une région est `key`, sinon `lokey` (= `pitch_keycenter`
    quand lokey==hikey) ; le nom vient du NOM de fichier de l'échantillon, puis de `region_label`/`group_label`."""
    out = {}
    for r in regions:
        note = _note_of(r.get("key")) if r.get("key") is not None else _note_of(r.get("lokey"))
        if note is None and r.get("pitch_keycenter") is not None:
            note = _note_of(r.get("pitch_keycenter"))
        if note is None or not (0 <= note <= 127) or note in out:
            continue
        nm = r.get("region_label") or r.get("group_label") or r.get("global_label") or ""
        if not nm and r.get("sample"):
            nm = os.path.splitext(os.path.basename(str(r["sample"]).replace("\\", "/")))[0]
        out[note] = nm or f"note {note}"
    return out


# ── 2. LIRE UN DOSSIER ─────────────────────────────────────────────────────────────────────────────────────

def _wav_info(path):
    """(sample_rate, bits) d'un .wav ou .flac, lu dans l'en-tête ; (None, None) sinon."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            i = head.find(b"fmt ")
            if i >= 0 and len(head) >= i + 24:
                _fmt, ch, sr, _br, _ba, bits = struct.unpack_from("<HHIIHH", head, i + 8)
                return sr, bits
        if head[:4] == b"fLaC" and len(head) >= 26:
            b = head[18:26]                                               # STREAMINFO : sr 20 bits, ch 3, bps 5
            v = int.from_bytes(b[0:4], "big")
            sr = v >> 12
            bits = ((v >> 4) & 0x1F) + 1
            return sr, bits
    except OSError:
        pass
    return None, None


def folder_stats(path, limit_probe=8):
    """Taille, nombre de fichiers, fréquence/bits (lus dans les premiers échantillons) d'un dossier."""
    total, files, probed, sr, bits = 0, 0, 0, None, None
    # parcours TRIÉ : os.walk rend l'ordre du système de fichiers (ext4 : l'ordre de hachage), et « les premiers
    # échantillons » changeaient d'un dossier à l'autre — kick1.wav (48 kHz) ou kick2.wav (44,1 kHz) en premier
    # selon le tmp du runner (tests/test_kit_import.py, rouge une fois sur deux sur ubuntu-24.04, 2026-10-19)
    for root, dirs, fns in os.walk(path):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fn in sorted(fns):
            p = os.path.join(root, fn)
            try:
                total += os.path.getsize(p)
            except OSError:
                continue
            files += 1
            if probed < limit_probe and fn.lower().endswith(_AUDIO):
                s, b = _wav_info(p)
                if s:
                    probed += 1
                    sr, bits = sr or s, bits or b
    return {"bytes": total, "files": files, "sample_rate": sr, "bits": bits}


def _find_drumkit_xml(folder):
    """Le drumkit.xml d'un dossier DrumGizmo (n'importe quel .xml dont la racine est <drumkit>) et son midimap."""
    kit, midimap = None, None
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None, None
    for fn in names:
        if not fn.lower().endswith(".xml"):
            continue
        p = os.path.join(folder, fn)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(4000)
        except OSError:
            continue
        if re.search(r"<drumkit[\s>]", head) and kit is None:
            kit = p
        elif re.search(r"<midimap[\s>]", head) and midimap is None:
            midimap = p
    return kit, midimap


def scan(root, max_depth=SCAN_MAX_DEPTH):
    """Ce qui ressemble à un kit sous `root` : [{path, engine, name}] — un dossier DrumGizmo (drumkit + midimap)
    ou un fichier .sfz. Profondeur bornée, dossiers cachés ignorés, `SCAN_MAX_HITS` au plus."""
    root = os.path.abspath(root)
    hits = []
    if not os.path.isdir(root):
        return hits
    base_depth = root.rstrip(os.sep).count(os.sep)
    for cur, dirs, fns in os.walk(root):
        depth = cur.rstrip(os.sep).count(os.sep) - base_depth
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in ("$recycle.bin", "system volume information"))
        if depth >= max_depth:
            dirs[:] = []
        kit, mm = _find_drumkit_xml(cur)
        if kit and mm:
            hits.append({"path": cur, "engine": "drumgizmo", "name": _dg_name(kit) or os.path.basename(cur)})
            dirs[:] = []                                                  # un kit n'en contient pas un autre
        else:
            for fn in sorted(fns):
                if fn.lower().endswith(".sfz"):
                    hits.append({"path": os.path.join(cur, fn), "engine": "sfz", "name": os.path.splitext(fn)[0]})
        if len(hits) >= SCAN_MAX_HITS:
            break
    return hits[:SCAN_MAX_HITS]


def _dg_name(kit_xml):
    try:
        with open(kit_xml, "r", encoding="utf-8", errors="replace") as f:
            return parse_drumkit_xml(f.read()).get("name") or ""
    except Exception:
        return ""


_MIC_GROUPS = (("kick", ("kick", "bd", "bass")), ("snare", ("snare", "sn", "sd")), ("toms", ("tom", "floor")),
               ("oh", ("oh", "overhead", "over")), ("room", ("room", "amb", "ambience", "ambient")),
               ("cym", ("hh", "hihat", "hat", "ride", "crash", "cym", "china", "splash")), ("trig", ("trig", "trigger")))


def _mix_from_channels(channels):
    """Les canaux d'un drumkit.xml → le `mix` d'usine d'un kit (docs/drums-kit.md, kits.MIC_GROUPS) : groupe
    lu dans le nom, panoramique L/R lu dans le nom, 0 dB partout, les triggers coupés."""
    mix = []
    for i, nm in enumerate(channels[:16]):
        s = re.sub(r"[^a-z0-9]+", " ", nm.lower()).strip()
        w = s.split()
        group = "other"
        for g, keys in _MIC_GROUPS:
            if any(k in w or k in s.replace(" ", "") for k in keys):
                group = g
                break
        pan = 0.0
        if s in ("left", "l", "stereo l", "mix l"):        # une paire stéréo déjà mixée : tout à gauche / à droite
            pan = -1.0
        elif s in ("right", "r", "stereo r", "mix r"):
            pan = 1.0
        elif s.endswith(" l") or " left" in s or s.endswith("l") and len(w) == 1 and len(s) > 2 and s[-2:] in ("hl", "ml"):
            pan = -0.9
        elif s.endswith(" r") or " right" in s or s.endswith("r") and len(w) == 1 and len(s) > 2 and s[-2:] in ("hr", "mr"):
            pan = 0.9
        short = "".join(x[0] for x in w[:3]).upper()[:5] or str(i + 1)
        mix.append({"ch": i + 1, "name": nm[:24], "short": short, "group": group,
                    "gain": -60.0 if group == "trig" else 0.0, "pan": pan})
    return mix


def _os_note(engine):
    if engine == "drumgizmo":
        return "DrumGizmo runs on Linux only — this kit would be silent on Windows / macOS"
    if engine == "sfz":
        return "sfizz runs on Linux, Windows and macOS"
    return ""


def availability(engine):
    """(available: bool|None, why) du MOTEUR sur cette machine, par l'inventaire REAPER (kits.availability)."""
    from . import kits, blockstatus
    inv = blockstatus.inventory()
    if engine == "sfz":
        if not inv or inv.get("error"):
            return None, "REAPER inventory not read yet"
        names = inv.get("names") or set()
        return (True, None) if any(str(n).startswith("sfizz") for n in names) else (False, "sfizz is not in REAPER's plugin list — not installed, or REAPER not restarted since")
    if engine == "drumgizmo":
        return kits.availability({"engine": "drumgizmo"}, inv)
    return None, None


def read(path):
    """Ce que le rack LIT dans un kit, avant d'écrire quoi que ce soit : {ok, name, engine, path, pieces,
    pieces_src, unknown, extra, mics, bytes, files, sample_rate, bits, free_bytes, available, why, os_note,
    id, dest, exists}. Un chemin de .sfz lit SON dossier (les échantillons sont relatifs au fichier)."""
    path = os.path.abspath(str(path or ""))
    if not os.path.exists(path):
        return {"ok": False, "error": "no such file or folder"}
    t0 = time.time()
    doc = {"ok": True, "path": path}
    if os.path.isfile(path) and path.lower().endswith(".sfz"):
        folder, sfz = os.path.dirname(path), path
        engine = "sfz"
    elif os.path.isdir(path):
        kit, mm = _find_drumkit_xml(path)
        if kit:
            folder, engine = path, "drumgizmo"
            if not mm:
                return {"ok": False, "error": "DrumGizmo kit without a midimap.xml — the rack cannot learn which note plays which piece"}
        else:
            sfzs = [fn for fn in sorted(os.listdir(path)) if fn.lower().endswith(".sfz")]
            if not sfzs:
                return {"ok": False, "error": "no drumkit.xml and no .sfz here — pick the kit's folder (DrumGizmo) or its .sfz file"}
            folder, sfz, engine = path, os.path.join(path, sfzs[0]), "sfz"
            if len(sfzs) > 1:
                doc["sfz_choices"] = sfzs
    else:
        return {"ok": False, "error": "pick a folder (DrumGizmo) or a .sfz file"}
    doc["engine"], doc["folder"] = engine, folder
    try:
        if engine == "drumgizmo":
            with open(kit, "r", encoding="utf-8", errors="replace") as f:
                dk = parse_drumkit_xml(f.read())
            with open(mm, "r", encoding="utf-8", errors="replace") as f:
                table = parse_midimap_xml(f.read())
            pieces, unknown, extra = pieces_from_names(table)
            doc.update({"name": dk["name"] or os.path.basename(folder), "description": dk["description"],
                        "mics": len(dk["channels"]), "channels": dk["channels"], "instruments": len(dk["instruments"]),
                        "drumkit_xml": os.path.basename(kit), "midimap_xml": os.path.basename(mm),
                        "pieces_src": "midimap.xml"})
        else:
            def reader(inc):
                with open(os.path.join(folder, inc.replace("\\", "/")), "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            with open(sfz, "r", encoding="utf-8", errors="replace") as f:
                regions, default_path = parse_sfz(f.read(), folder, 0, reader)
            table = sfz_note_names(regions)
            pieces, unknown, extra = pieces_from_names(table)
            doc.update({"name": os.path.splitext(os.path.basename(sfz))[0], "sfz_file": os.path.basename(sfz),
                        "regions": len(regions), "mics": 2, "pieces_src": "the .sfz keys"})
    except ET.ParseError as e:
        return {"ok": False, "error": f"unreadable XML: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"cannot read this kit: {e}"}
    doc.update({"pieces": pieces, "unknown": unknown, "extra": extra, "notes_table": {str(k): v for k, v in sorted(table.items())}})
    doc.update(folder_stats(folder))
    try:
        doc["free_bytes"] = shutil.disk_usage(C.ROOT).free
    except OSError:
        doc["free_bytes"] = None
    av, why = availability(engine)
    doc.update({"available": av, "why": why, "os_note": _os_note(engine), "os": sys.platform})
    kid = "drums-" + _safe_id(doc["name"])
    dest = os.path.join(_dest_root(engine), _safe_id(doc["name"]))
    doc.update({"id": kid, "dest": C.rel(dest).replace(os.sep, "/"),
                "exists": os.path.exists(dest) or _kit_exists(kid), "read_ms": int((time.time() - t0) * 1000)})
    return doc


def _kit_exists(kid):
    from . import kits
    return kits.get_kit(kid) is not None


# ── 3. INSTALLER ───────────────────────────────────────────────────────────────────────────────────────────

_jobs, _lock = {}, threading.Lock()


def job(jid):
    with _lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def _start(kind, fn):
    jid = uuid.uuid4().hex[:12]
    j = {"id": jid, "kind": kind, "state": "running", "done_bytes": 0, "total_bytes": 0, "at": time.time(), "error": None, "result": None}
    with _lock:
        _jobs[jid] = j
    def run():
        try:
            res = fn(j)
            with _lock:
                j.update({"state": "done", "result": res})
        except Exception as e:                                           # dit au client, et journalisé
            log.warning("kit import %s : %s", kind, e)
            with _lock:
                j.update({"state": "error", "error": str(e)})
    threading.Thread(target=run, name="kit-import-" + kind, daemon=True).start()
    return jid


def _copy_tree(src, dst, j):
    """shutil.copytree qui compte les octets dans le job (une barre honnête sur 2,4 Go)."""
    total = 0
    for root, dirs, fns in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    with _lock:
        j["total_bytes"] = total
    for root, dirs, fns in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel = os.path.relpath(root, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for fn in fns:
            s, d = os.path.join(root, fn), os.path.join(out, fn)
            with open(s, "rb") as fi, open(d, "wb") as fo:
                while True:
                    b = fi.read(4 << 20)
                    if not b:
                        break
                    fo.write(b)
                    with _lock:
                        j["done_bytes"] += len(b)
            shutil.copystat(s, d)


def install(path, name=None, sfz_file=None):
    """Lance l'installation (copie dans library/drumkits/<id>/ ou library/sfz/<id>/, puis la fiche kit) ;
    rend l'id du job. `read()` d'abord : on n'écrit que ce qu'on a su lire."""
    r = read(path)
    if not r.get("ok"):
        raise ValueError(r.get("error"))
    if r.get("available") is False:
        raise ValueError(r.get("why") or "engine not available on this machine")
    if name:
        r["name"] = str(name).strip()[:60] or r["name"]
    if sfz_file and r.get("sfz_choices") and sfz_file in r["sfz_choices"]:
        r["sfz_file"] = sfz_file
    kid = "drums-" + _safe_id(r["name"])
    dest = os.path.join(_dest_root(r["engine"]), _safe_id(r["name"]))
    if os.path.exists(dest) or _kit_exists(kid):
        raise ValueError(f"« {r['name']} » is already installed — delete it first, or give this one another name")
    if r.get("free_bytes") is not None and r["bytes"] > r["free_bytes"] - (512 << 20):
        raise ValueError("not enough free space on the rack for this kit")

    def run(j):
        from . import kits
        _copy_tree(r["folder"], dest, j)
        rel = C.rel(dest).replace(os.sep, "/")
        doc = {"id": kid, "name": r["name"], "role": "drum", "engine": r["engine"],
               "notes": r["pieces"], "hint": (r.get("description") or "")[:80] or ("imported " + r["engine"] + " kit"),
               "notes_note": f"read in {r['pieces_src']} at import" + (" — unrecognised: " + ", ".join(r["unknown"][:8]) if r["unknown"] else ""),
               "imported": {"at": int(time.time()), "from": r["path"], "bytes": r["bytes"], "files": r["files"],
                            "dir": rel, "sample_rate": r.get("sample_rate"), "bits": r.get("bits")}}
        if r["engine"] == "drumgizmo":
            doc["drumkit"] = rel + "/" + r["drumkit_xml"]
            doc["midimap"] = rel + "/" + r["midimap_xml"]
            doc["mix"] = _mix_from_channels(r.get("channels") or [])
        else:
            doc["sfz"] = rel + "/" + r["sfz_file"]
        res = kits.save_kit(doc, allow_drums=True)
        if not res.get("ok"):
            shutil.rmtree(dest, ignore_errors=True)
            raise RuntimeError(res.get("error"))
        log.info("kit importé : %s (%s, %d Mo) ← %s", kid, r["engine"], r["bytes"] >> 20, r["path"])
        try:
            from . import arrivals
            arrivals.note("kit-install")                                # l'écran Drums se recharge (library_rev)
        except Exception:
            pass
        kits._sync_soon()                                                # la carte part (packs + rig-manifest)
        return {"kit": res["kit"]}
    return _start("install", run)


# ── 4. D'OÙ : volumes, URL ─────────────────────────────────────────────────────────────────────────────────

def volumes():
    """Les volumes où chercher un kit : clés USB d'abord, puis les disques. [{path, label, removable}]."""
    out = []
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = f"{chr(65 + i)}:\\"
            t = k32.GetDriveTypeW(root)                                  # 2 = amovible, 3 = fixe, 4 = réseau
            if t not in (2, 3, 4):
                continue
            buf = ctypes.create_unicode_buffer(261)
            k32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
            out.append({"path": root, "label": (buf.value or ("Removable" if t == 2 else "Disk")) + f" ({root[:2]})", "removable": t == 2})
    elif sys.platform == "darwin":
        for fn in sorted(os.listdir("/Volumes") if os.path.isdir("/Volumes") else []):
            p = os.path.join("/Volumes", fn)
            if os.path.isdir(p) and not os.path.samefile(p, "/") if os.path.exists(p) else False:
                out.append({"path": p, "label": fn, "removable": True})
        out.append({"path": os.path.expanduser("~"), "label": "Home", "removable": False})
    else:
        for base in ("/media", "/run/media", "/mnt"):
            if not os.path.isdir(base):
                continue
            for a in sorted(os.listdir(base)):
                pa = os.path.join(base, a)
                if base != "/mnt" and os.path.isdir(pa) and not os.path.ismount(pa):
                    for b in sorted(os.listdir(pa)):                     # /media/<user>/<volume>
                        pb = os.path.join(pa, b)
                        if os.path.isdir(pb):
                            out.append({"path": pb, "label": b, "removable": True})
                elif os.path.isdir(pa):
                    out.append({"path": pa, "label": a, "removable": os.path.ismount(pa)})
        out.append({"path": os.path.expanduser("~"), "label": "Home", "removable": False})
    out.sort(key=lambda v: (not v["removable"], v["label"].lower()))
    return out


def _looks_like_kit(folder):
    """Un coup d'œil, pas une lecture : un dossier DrumGizmo porte drumkit.xml + midimap.xml, un kit SFZ un .sfz."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    low = {n.lower() for n in names}
    if "drumkit.xml" in low or ("midimap.xml" in low and any(n.endswith(".xml") for n in low)):
        return "drumgizmo"
    if any(n.endswith(".sfz") for n in low):
        return "sfz"
    return None


def browse(path=None):
    """« Browse… » de la feuille d'import (2026-10-14 : « je n'ai qu'un champ ») : les dossiers et les .sfz d'un
    dossier de CE poste, lus par le rack. Chaque sous-dossier dit s'il ressemble à un kit (🥁). Sans chemin : le
    dossier personnel. Dossiers cachés ignorés."""
    p = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(p):
        raise ValueError("no such folder")
    dirs, sfz = [], []
    try:
        with os.scandir(p) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        dirs.append({"name": e.name, "kit": _looks_like_kit(e.path)})
                    elif e.is_file() and e.name.lower().endswith(".sfz"):
                        sfz.append(e.name)
                except OSError:
                    continue
    except OSError:
        raise ValueError("folder not readable")
    parent = os.path.dirname(p)
    return {"path": p, "parent": parent if parent != p else None, "kit": _looks_like_kit(p),
            "dirs": sorted(dirs, key=lambda d: (d["kit"] is None, d["name"].lower()))[:400],
            "sfz": sorted(sfz, key=str.lower)[:400]}


def _safe_extract(archive, dest):
    """Extrait un .zip / .tar(.gz|.xz|.bz2) sans laisser un membre sortir de `dest`."""
    import zipfile, tarfile
    dest = os.path.abspath(dest)
    def inside(p):
        return os.path.abspath(os.path.join(dest, p)).startswith(dest + os.sep)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for m in zf.infolist():
                if not inside(m.filename):
                    raise ValueError("archive member escapes the folder: " + m.filename)
            zf.extractall(dest)
        return True
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for m in tf.getmembers():
                if not inside(m.name) or m.issym() or m.islnk():
                    raise ValueError("archive member refused: " + m.name)
            tf.extractall(dest)
        return True
    return False


MAX_DOWNLOAD = 4 << 30          # 4 Go : le plus gros kit DrumGizmo connu en fait ~2


def _public_host(host):
    """Audit 2026-10-15 (S3) : l'import par URL faisait fetcher au bridge N'IMPORTE QUELLE adresse — lui-même en
    127.0.0.1, où il se croit l'écran local donc admin (clé Wi-Fi, sauvegardes, diag). Toutes les adresses que
    le nom résout doivent être PUBLIQUES."""
    import ipaddress, socket
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        raise ValueError("unknown host")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError("only public internet addresses can be imported")


def _open_public(u):
    """urlopen qui revérifie l'hôte à CHAQUE redirection (une URL publique pouvait rediriger vers 127.0.0.1)."""
    import urllib.request, urllib.parse

    class _Guard(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            nu = urllib.parse.urlparse(newurl)
            if nu.scheme not in ("http", "https") or not nu.hostname:
                raise ValueError("redirect refused")
            _public_host(nu.hostname)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    _public_host(urllib.parse.urlparse(u).hostname or "")
    req = urllib.request.Request(u, headers={"User-Agent": "golem-rack"})
    return urllib.request.build_opener(_Guard).open(req, timeout=60)


def fetch_url(url):
    """Télécharge une archive (zip / tar) ou un fichier .sfz dans library/.import/<nom>/, l'extrait, et rend
    l'id du job ; `result.path` est le dossier à LIRE ensuite (un seul dossier de tête : on y descend)."""
    import urllib.request, urllib.parse
    u = str(url or "").strip()
    if not re.match(r"^https?://", u):
        raise ValueError("a http(s) URL is expected")
    _public_host(urllib.parse.urlparse(u).hostname or "")                # refusé tout de suite, pas dans le job
    fn = os.path.basename(urllib.parse.urlparse(u).path) or "kit.zip"
    stem = _safe_id(os.path.splitext(fn)[0]) or "kit"
    work = os.path.join(_dl_dir(), stem + "-" + uuid.uuid4().hex[:6])

    def run(j):
        os.makedirs(work, exist_ok=True)
        arch = os.path.join(work, fn)
        with _open_public(u) as resp, open(arch, "wb") as fo:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD:
                raise ValueError("file too large")
            with _lock:
                j["total_bytes"] = total
            got = 0
            while True:
                b = resp.read(1 << 20)
                if not b:
                    break
                got += len(b)
                if got > MAX_DOWNLOAD:
                    raise ValueError("file too large")
                fo.write(b)
                with _lock:
                    j["done_bytes"] += len(b)
        out = os.path.join(work, "kit")
        os.makedirs(out, exist_ok=True)
        if _safe_extract(arch, out):
            os.remove(arch)
            entries = [e for e in os.listdir(out) if not e.startswith(".")]
            if len(entries) == 1 and os.path.isdir(os.path.join(out, entries[0])):
                out = os.path.join(out, entries[0])
        else:
            shutil.move(arch, os.path.join(out, fn))                     # un .sfz nu, ou un fichier inconnu : read() dira
        return {"path": out}
    return _start("download", run)


def cleanup_downloads(max_age_s=7 * 86400):
    """Les téléchargements d'URL plus vieux qu'une semaine (un kit installé en est une COPIE)."""
    if not os.path.isdir(_dl_dir()):
        return
    for fn in os.listdir(_dl_dir()):
        p = os.path.join(_dl_dir(), fn)
        try:
            if time.time() - os.path.getmtime(p) > max_age_s:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
