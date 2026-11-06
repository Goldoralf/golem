# SPDX-License-Identifier: GPL-3.0-or-later
"""Kits de pads — objets de bibliothèque référencés par le bloc `pads`
(docs/blocks-doctrine.md : le contenu vit dans la LIB, pas dans le bloc).

Un kit = library/kits/<id>.json : jusqu'à 16 pads {note, sample, mode, level}
(16 notes GM au placement MPC : DEFAULT_NOTES).
  - note   : note MIDI envoyée par le pad du contrôleur (AKAI MPK mini : 36-43)
  - sample : chemin relatif repo d'un .wav/.flac/.mp3 sous assets/samples/
  - mode   : gate (note-off coupe) | oneshot (joue jusqu'au bout, re-tap relance)
             | toggle (re-tap coupe)
  - level  : dB (défaut 0)

Les samples entrent par POST /api/sample/upload (corps brut, idiome vital/ir)
ou dépôt direct dans assets/samples/. Le miroir golem.fm prendra les kits par
le canal packs (kind dédié) dans un second temps.
"""
import json, os, re

from . import config as C
from .store import _read_json, _write_json_atomic

KITS_DIR = os.path.join(C.ROOT, "library", "kits")
SAMPLES_DIR = os.path.join(C.ROOT, "assets", "samples")
SFZ_DIR = os.path.join(C.ROOT, "library", "sfz")
DRUMKITS_DIR = os.path.join(C.ROOT, "library", "drumkits")
MODES = ("gate", "oneshot", "toggle")
_EXTS = (".wav", ".flac", ".mp3", ".ogg", ".aif", ".aiff")
_SAFE = re.compile(r"[^\w\-]+")

# rôle du kit : `pad` = joué à la main sur les pads (notes 36-51) ; `drum` = batterie
# GM déclenchée par la boîte à rythmes (bloc `drums`, .mid GM). Cosmétique côté engine
# (le mapping note reste l'identité), sert au filtre Library + au tiroir contextuel.
ROLES = ("pad", "drum")
# moteur audio du kit — lu côté golem_drums.lua qui construit la chaîne FX en conséquence :
#   rs5k     = N ReaSamplOmatic5000 (1 par pad, samples sous assets/samples/) — historique
#   sfz      = 1 sfizz LV2 chargeant un .sfz de library/sfz/ (velocity/round-robin)
#   avldrums = 1 avldrums.lv2 (kit acoustique GM intégré ; `bank` choisit la banque)
#   drumgizmo= 1 drumgizmo.lv2 chargeant un kit MULTI-MICROS de library/drumkits/
#              (`drumkit` = le .xml du kit, `midimap` = la table note->instrument)
ENGINES = ("rs5k", "sfz", "avldrums", "drumgizmo")
# ── LES BATTERIES ARRIVENT AVEC LE RACK (décision 2026-09-15) ────────────────────────────
# Un kit à moteur BATTERIE (sfz / avldrums / drumgizmo) n'est ni créé, ni importé, ni supprimé
# depuis un écran : il est une GRAINE versionnée (library/kits-factory/), ressemée au démarrage
# dans library/kits/ si elle manque (le 2 août, un `git rm` avait vidé library/kits/ — six
# semaines sans signal). Les kits de PADS (rs5k) gardent leur cycle complet (golem.fm crée,
# kit-install pose, l'écran supprime).
DRUM_ENGINES = ("sfz", "avldrums", "drumgizmo")
FACTORY_DIR = os.path.join(C.ROOT, "library", "kits-factory")
# banques du plugin avldrums.lv2 : 1 kit = 1 URI LV2 (mapping id->URI dans golem_drums.lua)
# black-pearl = rock ambiant, red-zeppelin = rock sec, blonde-bop = jazz/brushes.
AVL_BANKS = ("black-pearl", "red-zeppelin", "blonde-bop")
# moteur drumgizmo : un micro par canal, et l'UI du mixeur RANGE par famille (c'est ainsi qu'on
# pense un mix de batterie, pas dans l'ordre de câblage). `trig` = sorties de déclenchement, PAS
# de l'audio : elles sont montrées à part et coupées par défaut.
MIC_GROUPS = ("kick", "snare", "toms", "cym", "oh", "room", "other", "trig")
MAX_MICS = 16

# LES 16 PADS EN GENERAL MIDI, AU PLACEMENT MPC (2026-10-13 : « tout harmoniser ») — case i de la grille =
# pad i du contrôleur (1 en bas à gauche, banque A puis B) = la note GM du son qu'on y joue. Les kits, les grooves,
# golem.fm et le programme de l'AKAI (bridge/controller_program.py) parlent tous GM ; le placement reste sous les doigts :
#   A bas : kick 36 · snare 38 · charleston fermé 42 · ouvert 46   A haut : clap 39 · rim 37 · tom 45 · crash 49
#   B bas : kick sub 35 · pédale 44 · tom bas 41 · tom haut 48     B haut : ride 51 · crash 2 57 · cloche 53 · cowbell 56
# (Avant : 36-51 dans l'ordre — un groove GM sonnait faux sur 15 notes sur 16.) La sheet affiche 2 pages 4×2 (A/B)
# qui suivent cet ordre.
DEFAULT_NOTES = (36, 38, 42, 46, 39, 37, 45, 49, 35, 44, 41, 48, 51, 57, 53, 56)


def _safe_id(s):
    return _SAFE.sub("-", str(s or "").strip().lower()).strip("-")[:60] or "kit"


def is_factory(kit):
    """Une batterie d'usine : le drapeau `factory`, ou un moteur batterie SANS `imported` — depuis le
    2026-10-11 (« + Add », docs/drums-kit.md §8) une batterie a une seconde origine : importée par le
    rack (kit_import), et celle-là se supprime."""
    return bool(isinstance(kit, dict) and (kit.get("factory")
                or (kit.get("engine") in DRUM_ENGINES and not kit.get("imported"))))



def _sync_soon():
    """Une carte vit tant qu'un rig-manifest la liste (golem.fm, 2026-10-11) : après un import ou une suppression
    de batterie, on programme le sync débouncé qui pousse les packs ET le rig-manifest. No-op si non appairé."""
    try:
        from . import tones_sync
        tones_sync.schedule()
    except Exception:
        pass


def is_imported(kit):
    return bool(isinstance(kit, dict) and isinstance(kit.get("imported"), dict) and kit.get("engine") in DRUM_ENGINES)


def factory_seeds():
    """Les graines de library/kits-factory/ : [{doc}], dans l'ordre des fichiers."""
    out = []
    if os.path.isdir(FACTORY_DIR):
        for fn in sorted(os.listdir(FACTORY_DIR)):
            if fn.endswith(".json"):
                d = _read_json(os.path.join(FACTORY_DIR, fn), None)
                # une BATTERIE d'usine, ou un KIT DE PADS d'usine (2026-10-13 : « livrer les sons » — les kits de
                # pads de l'usine sont livrés avec le golem, sons sous assets/samples/kits/, drumsynth : à nous)
                if isinstance(d, dict) and d.get("id") and (d.get("engine") in DRUM_ENGINES
                                                            or (d.get("engine") == "rs5k" and d.get("factory"))):
                    out.append({**d, "factory": True})
    return out


def seed_factory():
    """Ressème dans library/kits/ chaque batterie d'usine qui MANQUE (ou qui n'y est pas marquée
    d'usine : un doc du même id posé par l'ancien créateur est remplacé par la graine). Ne touche
    à rien d'autre. Rend les ids (re)posés. Appelé au démarrage du bridge."""
    done = []
    os.makedirs(KITS_DIR, exist_ok=True)
    for seed in factory_seeds():
        p = os.path.join(KITS_DIR, f"{_safe_id(seed['id'])}.json")
        cur = _read_json(p, None) if os.path.isfile(p) else None
        if isinstance(cur, dict) and cur.get("factory"):
            # docs/drums-kit.md lot 2 : la table ÉLÉMENT -> NOTE (`notes`) vit dans la GRAINE ; un kit
            # d'usine déjà posé la reprend quand elle change (une graine est la vérité d'un kit d'usine)
            if seed.get("notes") and cur.get("notes") != seed.get("notes"):
                _write_json_atomic(p, {**cur, "notes": seed["notes"], "notes_note": seed.get("notes_note")})
                done.append(seed["id"])
            continue
        _write_json_atomic(p, seed)
        done.append(seed["id"])
    return done


def kit_notes(kit):
    """La table élément -> note MIDI du kit (docs/drums-kit.md §3, vocabulaire drumkits.ELEMENTS),
    validée : {element: note} — un élément inconnu ou une note hors 0..127 est ignoré, et dit."""
    from . import drumkits
    from .golog import get as _get
    out, bad = {}, []
    for el, n in ((kit or {}).get("notes") or {}).items():
        if el in drumkits.ELEMENTS and isinstance(n, int) and 0 <= n <= 127:
            out[el] = n
        else:
            bad.append(f"{el}={n!r}")
    if bad:
        _get("kits").warning(f"kit {(kit or {}).get('id')} : notes ignorées {bad}")
    return out


def availability(kit, inv=None):
    """(available: bool|None, why) d'un kit BATTERIE sur CETTE machine — None = on ne sait pas (pas d'inventaire).
    2026-10-03 : sous Windows le sélecteur laissait choisir Aasimonster (DrumGizmo + 2,3 Go d'échantillons,
    ni l'un ni l'autre posés) — le patch ne sonnait pas, et rien ne le disait."""
    eng = (kit or {}).get("engine")
    if eng not in DRUM_ENGINES:
        return True, None
    if eng == "drumgizmo":
        xml = (kit or {}).get("drumkit") or ""
        if xml and not os.path.isfile(os.path.join(C.ROOT, xml)):
            return False, "its samples are not installed on this machine"
    if eng == "sfz":
        sfz = (kit or {}).get("sfz") or ""
        if sfz and not os.path.isfile(os.path.join(C.ROOT, sfz)):
            return False, "its samples are not installed on this machine"
    if inv is None:
        from . import blockstatus
        inv = blockstatus.inventory()
    if not inv or inv.get("error"):
        return None, None
    names = " | ".join(sorted(inv.get("names") or ()))
    if eng == "avldrums":
        want = ((kit or {}).get("bank") or "").replace("-", " ") + " drumkit"
        return (True, None) if want in names else (False, "AVL Drumkits is not installed on this machine")
    if eng == "drumgizmo":
        return (True, None) if "drumgizmo" in names else (False, "DrumGizmo is not installed on this machine")
    if eng == "sfz":
        # sfizz : LV2 sur le rack Linux, VST3 sous Windows/macOS (golem_drums.lua charge le .sfz par l'un ou l'autre)
        return (True, None) if "sfizz" in names else (False, "sfizz is not in REAPER's plugin list — not installed, or REAPER not restarted since")
    return None, None


def list_kits():
    out = []
    inv = None
    if os.path.isdir(KITS_DIR):
        for fn in sorted(os.listdir(KITS_DIR)):
            if not fn.endswith(".json"):
                continue
            k = _read_json(os.path.join(KITS_DIR, fn), None)
            if isinstance(k, dict) and k.get("id"):
                row = {**k, "factory": is_factory(k)}
                if k.get("engine") in DRUM_ENGINES:
                    if inv is None:
                        from . import blockstatus
                        inv = blockstatus.inventory() or {}
                    row["available"], row["unavailable_why"] = availability(k, inv)
                out.append(row)
    return out


def get_kit(kid):
    p = os.path.join(KITS_DIR, f"{_safe_id(kid)}.json")
    k = _read_json(p, None)
    return k if isinstance(k, dict) else None


def save_kit(kit, allow_drums=False):
    """Valide + écrit un kit. Rend {ok, kit} ou {ok:False, error}. Un moteur BATTERIE est refusé
    sauf `allow_drums` (la graine) : une batterie arrive par une mise à jour du rack, pas par
    un écran (2026-09-15).

    Format : {id, name, role, engine, ...} où la clé engine détermine le reste :
      rs5k     -> pads[] (chaque pad {note, sample, mode, level})
      sfz      -> sfz (chemin .sfz sous library/sfz/)
      avldrums -> bank (une de AVL_BANKS)
      drumgizmo-> drumkit (.xml sous library/drumkits) + midimap (.xml, même racine)
    """
    if not isinstance(kit, dict):
        return {"ok": False, "error": "kit must be an object"}
    kid = _safe_id(kit.get("id") or kit.get("name"))
    role = kit.get("role") if kit.get("role") in ROLES else "pad"
    engine = kit.get("engine") if kit.get("engine") in ENGINES else "rs5k"
    if engine in DRUM_ENGINES and not allow_drums:
        return {"ok": False, "error": f"a {engine} drum kit ships with the rack (library/kits-factory) — it is not created, imported or deleted from a screen"}
    doc = {"id": kid, "name": (kit.get("name") or kid)[:60], "role": role, "engine": engine}

    if engine == "avldrums":
        bank = kit.get("bank")
        if bank not in AVL_BANKS:
            return {"ok": False, "error": f"bank must be one of {AVL_BANKS} ({bank!r})"}
        doc["bank"] = bank
    elif engine == "drumgizmo":
        # deux fichiers, tous deux OBLIGATOIRES : le kit ne sonne pas sans sa table de
        # correspondance note->instrument (drumgizmo.lv2 n'a AUCUN mapping par défaut).
        for key, label in (("drumkit", "drumkit"), ("midimap", "midimap")):
            rel = os.path.normpath(kit.get(key) or "")
            if rel.startswith("..") or os.path.isabs(rel) or not rel.startswith(os.path.join("library", "drumkits")):
                return {"ok": False, "error": f"{label} must live under library/drumkits ({kit.get(key)!r})"}
            if not os.path.isfile(os.path.join(C.ROOT, rel)):
                return {"ok": False, "error": f"{label} not found: {rel}"}
            doc[key] = rel.replace(os.sep, "/")                      # un chemin de fiche s'écrit à « / », même sous Windows
        # `mix` = le mix D'USINE du kit, un objet par micro. Il DOIT survivre à un save : sans
        # lui le kit remonte tous ses micros à 0 dB au centre, triggers compris (clic par frappe).
        mix = []
        for m in (kit.get("mix") or [])[:MAX_MICS]:
            ch = m.get("ch") if isinstance(m, dict) else None
            if not isinstance(ch, int) or not (1 <= ch <= MAX_MICS):
                return {"ok": False, "error": f"mix: bad channel {ch!r}"}
            mix.append({"ch": ch, "name": str(m.get("name") or f"Ch {ch}")[:24],
                        "short": str(m.get("short") or "")[:5],
                        "group": m.get("group") if m.get("group") in MIC_GROUPS else "other",
                        "gain": max(-60.0, min(12.0, float(m.get("gain") or 0))),
                        "pan": max(-1.0, min(1.0, float(m.get("pan") or 0)))})
        doc["mix"] = mix
        if m2 := kit.get("bleed"):
            doc["bleed"] = max(0.0, min(1.0, float(m2)))
    elif engine == "sfz":
        sfz = os.path.normpath(kit.get("sfz") or "")
        if sfz.startswith("..") or os.path.isabs(sfz) or not sfz.startswith(os.path.join("library", "sfz")):
            return {"ok": False, "error": f"sfz must live under library/sfz ({kit.get('sfz')!r})"}
        if not os.path.isfile(os.path.join(C.ROOT, sfz)):
            return {"ok": False, "error": f"sfz not found: {sfz}"}
        doc["sfz"] = sfz.replace(os.sep, "/")
    else:  # rs5k
        pads = []
        for p in (kit.get("pads") or [])[:16]:
            if not isinstance(p, dict):
                continue
            note = p.get("note")
            sample = p.get("sample") or ""
            if not isinstance(note, int) or not (0 <= note <= 127):
                return {"ok": False, "error": f"bad note {note!r}"}
            if sample:
                rel = os.path.normpath(sample)
                if rel.startswith("..") or os.path.isabs(rel) or not rel.startswith("assets/samples"):
                    return {"ok": False, "error": f"sample must live under assets/samples ({sample})"}
                if not os.path.isfile(os.path.join(C.ROOT, rel)):
                    return {"ok": False, "error": f"sample not found: {rel}"}
                sample = rel
            mode = p.get("mode") if p.get("mode") in MODES else "gate"
            try:
                level = max(-60.0, min(12.0, float(p.get("level") or 0)))
            except Exception:
                level = 0.0
            pads.append({"note": note, "sample": sample, "mode": mode, "level": level})
        doc["pads"] = pads

    if engine in DRUM_ENGINES:
        # ce qu'une batterie porte en plus (la graine l'écrit directement ; l'import passe ici) : la table
        # pièce → note, sa provenance, l'accroche, et l'origine d'un kit importé (kit_import)
        for k in ("notes", "notes_note", "hint", "imported"):
            if kit.get(k):
                doc[k] = kit[k]
    os.makedirs(KITS_DIR, exist_ok=True)
    _write_json_atomic(os.path.join(KITS_DIR, f"{kid}.json"), doc)
    return {"ok": True, "kit": doc}


def delete_kit(kid):
    p = os.path.join(KITS_DIR, f"{_safe_id(kid)}.json")
    if not os.path.isfile(p):
        return {"ok": False, "error": "unknown kit"}
    cur = _read_json(p, None)
    if is_factory(cur):
        return {"ok": False, "factory": True,
                "error": "factory drum kit — it ships with the rack and comes back at the next start; not deletable"}
    os.remove(p)
    # une batterie IMPORTÉE possède son dossier (library/drumkits/<id>/ ou library/sfz/<id>/, posé par
    # kit_import) : il part avec elle — des gigaoctets qu'aucune autre fiche ne référence
    freed = 0
    if is_imported(cur):
        rel = os.path.normpath(str((cur.get("imported") or {}).get("dir") or ""))
        roots = (os.path.join("library", "drumkits"), os.path.join("library", "sfz"))
        if rel and not rel.startswith("..") and not os.path.isabs(rel) and any(rel.startswith(r + os.sep) for r in roots):
            full = os.path.join(C.ROOT, rel)
            if os.path.isdir(full):
                for root, _d, fns in os.walk(full):
                    for fn in fns:
                        try:
                            freed += os.path.getsize(os.path.join(root, fn))
                        except OSError:
                            pass
                import shutil
                shutil.rmtree(full, ignore_errors=True)
        _sync_soon()                                                     # la carte disparaît du rig-manifest
    return {"ok": True, "freed_bytes": freed}


# ── LE TYPE D'UN SAMPLE : `short` (one-shot, pads, bloc Sample) | `song` (un fichier long, un stem
# d'un backing local — décision 2026-09-15, docs/samples-backings.md). CHOISI À L'IMPORT, jamais
# deviné par la durée (« un type deviné est un type faux un jour de concert »). Sidecar
# assets/samples/.kinds.json {rel: {"kind", "loudness_db"}} ; absent = short (les fichiers d'avant).
SAMPLE_KINDS = ("short", "song")
KINDS_FILE = os.path.join(SAMPLES_DIR, ".kinds.json")
LOUD_TARGET_DB = -18.0        # même cible que les captures (compile_rig.LOUD_TARGET) : un stem local sort au niveau d'un stem golem.fm


def _kinds():
    return _read_json(KINDS_FILE, {}) or {}


def _set_kind(rel, kind, loudness_db=None):
    d = _kinds()
    entry = dict(d.get(rel) or {})
    entry["kind"] = kind if kind in SAMPLE_KINDS else "short"
    if loudness_db is not None:
        entry["loudness_db"] = round(float(loudness_db), 1)
    d[rel] = entry
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    _write_json_atomic(KINDS_FILE, d)
    return entry


def sample_kind(rel):
    return ((_kinds().get(rel) or {}).get("kind")) or "short"


def set_sample_kind(rel, kind):
    """Corrige le type d'un sample existant (le geste « → Songs » / « → Short » de la Library)."""
    rel = os.path.normpath(rel)
    if not rel.startswith(os.path.join("assets", "samples")) or not os.path.isfile(os.path.join(C.ROOT, rel)):
        return {"ok": False, "error": "unknown sample"}
    if kind not in SAMPLE_KINDS:
        return {"ok": False, "error": f"kind must be one of {SAMPLE_KINDS}"}
    if kind == "short":
        users = backing_usage().get(rel)
        if users:
            return {"ok": False, "error": "used as a stem by backing(s): " + ", ".join(users)}
    loud = sample_loudness_db(os.path.join(C.ROOT, rel)) if kind == "song" else None
    return {"ok": True, "kind": _set_kind(rel, kind, loud)["kind"], "loudness_db": loud}


def sample_loudness_db(path):
    """RMS (dBFS) d'un .wav — la mesure qui permet de sortir un stem local au niveau d'un stem
    golem.fm. None si le format n'est pas lisible ici (mp3/ogg : le stem joue à 0 dB)."""
    try:
        from .compile_rig import _read_wav_mono
        import math
        samples, _sr = _read_wav_mono(path)
        if not samples:
            return None
        step = max(1, len(samples) // 400000)          # ~400 k points suffisent pour un RMS
        acc = 0.0; n = 0
        for i in range(0, len(samples), step):
            v = samples[i]; acc += v * v; n += 1
        if not n or acc <= 0:
            return None
        return 20 * math.log10(math.sqrt(acc / n))
    except Exception:
        return None


def stem_gain(rel):
    """Le gain LINÉAIRE qui ramène un sample song à LOUD_TARGET_DB (borné ×0,1..×4) ; 1.0 si la
    loudness n'est pas connue."""
    ld = (_kinds().get(os.path.normpath(rel)) or {}).get("loudness_db")
    if ld is None:
        return 1.0
    return max(0.1, min(4.0, 10 ** ((LOUD_TARGET_DB - float(ld)) / 20)))


# la FAMILLE d'un son de pad, lue dans son nom (tiroir Pads v2, 2026-10-14) — pour ranger le navigateur ; un nom qui
# ne dit rien tombe dans « perc »
_CATS = (("kick", ("kick", "bd", "bassdrum")), ("snare", ("snare", "sd")), ("clap", ("clap",)),
         ("hat", ("hat", "hh", "hihat")), ("tom", ("tom",)), ("cym", ("crash", "ride", "cymbal", "splash", "china")),
         ("perc", ("rim", "cowbell", "shaker", "perc", "tamb", "conga", "bongo", "click", "stick")))


def sample_cat(name):
    toks = set(re.split(r"[^a-z]+", str(name).lower()))
    low = str(name).lower()
    for cat, keys in _CATS:
        if any(k in toks or (len(k) > 3 and k in low) for k in keys):
            return cat
    return "perc"


def _dur_s(path):
    """La durée d'un WAV, lue dans son en-tête (sans décoder) — None pour un autre format."""
    if not path.lower().endswith(".wav"):
        return None
    try:
        import wave
        with wave.open(path) as w:
            return round(w.getnframes() / float(w.getframerate()), 2)
    except Exception:
        return None


def sample_ok(rel):
    """Un chemin de sample qu'on accepte d'écouter : sous assets/samples, existant, d'un format connu."""
    full = os.path.realpath(os.path.join(C.ROOT, str(rel)))
    return (full.startswith(os.path.realpath(SAMPLES_DIR) + os.sep) and os.path.isfile(full)
            and os.path.splitext(full)[1].lower() in _EXTS)


def list_samples(kind=None):
    out = []
    kinds = _kinds()
    if os.path.isdir(SAMPLES_DIR):
        for dirp, _, files in os.walk(SAMPLES_DIR):
            for fn in sorted(files):
                if os.path.splitext(fn)[1].lower() in _EXTS:
                    rel = os.path.relpath(os.path.join(dirp, fn), C.ROOT)
                    k = (kinds.get(rel) or {}).get("kind") or "short"
                    if kind and k != kind:
                        continue
                    nm = os.path.splitext(fn)[0]
                    # d'où vient le son : le dossier du kit (« pads-house » -> House), sinon « My samples »
                    src = os.path.relpath(dirp, SAMPLES_DIR).split(os.sep)
                    kit = src[1] if len(src) > 1 and src[0] == "kits" else None
                    out.append({"file": rel, "name": nm,
                                "bytes": os.path.getsize(os.path.join(dirp, fn)), "kind": k,
                                "loudness_db": (kinds.get(rel) or {}).get("loudness_db"),
                                "cat": sample_cat(nm), "kit": kit,
                                "dur": _dur_s(os.path.join(dirp, fn)) if k != "song" else None})
    return out


def backing_usage():
    """{sample_rel: [slug de backing local…]} — un sample song qui sert de stem ne se supprime pas."""
    used = {}
    try:
        from . import golemfm
        for b in golemfm.list_local_backings():
            for rel in (b.get("stems") or {}).values():
                if rel and b["slug"] not in used.setdefault(rel, []):
                    used[rel].append(b["slug"])
    except Exception:
        pass
    return used


def sample_usage():
    """{sample_rel: [kit_id…]} — pour l'onglet Library (suppression sûre)."""
    used = {}
    for k in list_kits():
        for p in k.get("pads", []):
            if p.get("sample") and k["id"] not in used.setdefault(p["sample"], []):
                used[p["sample"]].append(k["id"])
    return used


def delete_sample(rel):
    rel = os.path.normpath(rel)
    if not rel.startswith(os.path.join("assets", "samples")):
        return {"ok": False, "error": "not a sample path"}
    users = sample_usage().get(rel)
    if users:
        return {"ok": False, "error": "used by kit(s): " + ", ".join(users)}
    bk = backing_usage().get(rel)
    if bk:
        return {"ok": False, "error": "used as a stem by backing(s): " + ", ".join(bk)}
    path = os.path.join(C.ROOT, rel)
    if not os.path.isfile(path):
        return {"ok": False, "error": "not found"}
    os.remove(path)
    d = _kinds()
    if rel in d:
        d.pop(rel); _write_json_atomic(KINDS_FILE, d)
    return {"ok": True}


# ── format d'échange .golemkit : zip portable = kit.json + samples/<fichiers> ─
def export_kit(kid):
    """Rend (filename, bytes zip) ou (None, error). kit.json embarqué référence
    ses samples en RELATIF au zip (samples/<fichier>) — portable entre racks."""
    import io, zipfile
    k = get_kit(kid)
    if not k:
        return None, "unknown kit"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        doc = {"golemkit": 1, "id": k["id"], "name": k["name"], "pads": []}
        for p in k.get("pads", []):
            entry = dict(p)
            if p.get("sample"):
                base = os.path.basename(p["sample"])
                src = os.path.join(C.ROOT, p["sample"])
                if os.path.isfile(src) and f"samples/{base}" not in zf.namelist():
                    zf.write(src, f"samples/{base}")
                entry["sample"] = f"samples/{base}"
            doc["pads"].append(entry)
        zf.writestr("kit.json", json.dumps(doc, indent=1))
    return f"{k['id']}.golemkit", buf.getvalue()


def import_kit(data):
    """Importe un .golemkit (octets zip). Samples reposés sous assets/samples/
    (jamais d'écrasement — suffixe), kit renommé si l'id existe. {ok, kit}."""
    import io, zipfile
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        doc = json.loads(zf.read("kit.json"))
    except Exception as e:
        return {"ok": False, "error": f"not a .golemkit: {e}"}
    if doc.get("golemkit") != 1 or not isinstance(doc.get("pads"), list):
        return {"ok": False, "error": "bad kit.json (magic golemkit==1 required)"}
    pads = []
    for p in doc["pads"][:16]:
        entry = {"note": p.get("note"), "mode": p.get("mode"), "level": p.get("level"), "sample": ""}
        s = p.get("sample") or ""
        if s:
            if s not in zf.namelist() or not s.startswith("samples/"):
                return {"ok": False, "error": f"sample missing in zip: {s}"}
            r = save_sample(os.path.basename(s), zf.read(s))
            if not r.get("ok"):
                return r
            entry["sample"] = r["file"]
        pads.append(entry)
    kid = _safe_id(doc.get("id") or doc.get("name"))
    if get_kit(kid):
        i = 2
        while get_kit(f"{kid}-{i}"):
            i += 1
        kid = f"{kid}-{i}"
    return save_kit({"id": kid, "name": doc.get("name") or kid, "pads": pads})


def save_sample(name, data, kind="short"):
    """Dépose un sample (corps brut). `kind` = short | song, CHOISI par l'appelant (l'onglet où
    l'utilisateur dépose, ou le pack golem.fm). Rend {ok, file, kind} ou {ok:False, error}."""
    base = os.path.basename(name or "sample.wav")
    ext = os.path.splitext(base)[1].lower()
    if ext not in _EXTS:
        return {"ok": False, "error": f"expected one of {', '.join(_EXTS)}"}
    if not data:
        return {"ok": False, "error": "empty body"}
    stem = _safe_id(os.path.splitext(base)[0])
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    rel = os.path.join("assets", "samples", f"{stem}{ext}")
    dest = os.path.join(C.ROOT, rel)
    i = 2
    while os.path.exists(dest):                    # jamais d'écrasement silencieux
        rel = os.path.join("assets", "samples", f"{stem}-{i}{ext}")
        dest = os.path.join(C.ROOT, rel)
        i += 1
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    kind = kind if kind in SAMPLE_KINDS else "short"
    loud = sample_loudness_db(dest) if kind == "song" else None
    _set_kind(rel, kind, loud)
    return {"ok": True, "file": rel, "kind": kind, "loudness_db": loud}
