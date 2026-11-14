# SPDX-License-Identifier: GPL-3.0-or-later
"""ÉCOUTER UN SON DE CLAVIER SEUL (docs/preset-preview.md §9, 2026-11-14) — la fiche d'un son sur golem.fm
(/library/keys/:id) a sa carte Listen. Un NAM se re-ampe dans le navigateur ; un piano, un DX7, l'orgue ou un preset
Vital ne jouent que sur golem : c'est donc le rack qui rend.

Un SON a un identifiant (la page de golem.fm le prend tel quel) :
  piano:<stem du .sfz>   ·   ep:<banque DX7>/<programme 0-31>   ·   organ:b3   ·   vital:<sha256 du .vital>
Il est rendu SEUL : un patch d'essai d'une lane clavier qui ne porte que l'instrument (aucune chaîne, sec, stéréo),
joué hors ligne par une référence MIDI (library/di-refs/keys/*.mid) — le moteur des démos de patch
(preview.generate, golem_preview op render + midi), sans sortie matérielle. Un clip par (son, référence).

La référence par nature : piano -> keys/piano, DX7 -> keys/epiano (keys/piano pour un piano acoustique, un clavecin ;
keys/organ pour un orgue), orgue -> keys/organ, Vital par son preset_style (Pad -> pad, Lead/Sequence -> lead,
Keys -> piano, Bass -> keys/bass). Percussion, SFX : pas de phrase qui leur aille — pas de clip, et la fiche le dit.

Rangement, comme les démos de patch : library/previews/sound-<kind>-<id>/<ref>.opus + preview.json
{sound, name, engine, ref, refs, fingerprint, generated, clips: {ref: {file, seconds, sha256}}}.
L'empreinte : sha256 du .vital, ou pour un instrument intégré (moteur, fichier, programme) — un clip est périmé quand
elle change.

USINE D'ABORD : chaque son d'usine (les variantes du piano — toutes si 3 ou moins, sinon la principale —, une
douzaine de programmes DX7 choisis, l'orgue, chaque preset Vital d'usine) entre dans le lot des démos d'usine.
Les presets de l'utilisateur : À LA DEMANDE seulement (plus tard, une commande de golem.fm), jamais à l'import."""
import hashlib
import json
import os
import shutil
import time

from . import config as C
from . import store
from .golog import get

log = get("sound-preview")

PREFIX = "sound:"                     # un élément du lot des démos d'usine
DX7_DIR = os.path.join(C.ROOT, "library", "dx7")
SFZ_DIR = os.path.join(C.ROOT, "library", "sfz")
PIANO_MAX_VARIANTS = 3                # au-delà : seule la variante principale a son clip (décision du mainteneur)
# la variante principale : celle des patchs d'usine
PIANO_DEFAULT = "SalamanderGrandPiano-V3+20200602"
# une douzaine de programmes DX7 choisis (décision du mainteneur, 2026-11-14 : pas les 192) — la fiche liste tous les
# sons, seuls ceux-ci ont « Listen ». Des pianos électriques d'abord (Rhodes, Wurlitzer, le E.PIANO 1 du DX7), puis
# ce qui se joue aussi au clavier d'un groupe : CP-70, clavinet, clavecin, vibraphone.
CURATED_EP = (("rom1a", 10), ("epiano1", 0), ("epiano1", 2), ("epiano1", 24), ("epiano2", 22), ("epiano2", 25),
              ("epiano2", 19), ("synprezfm-02", 23), ("piano1", 10), ("piano1", 16), ("piano1", 28), ("rom1a", 20))
# le preset_style de Vital -> la référence ; absent de la table (Percussion, SFX, Drums) = pas de phrase
STYLE_REF = {"pad": "keys/pad", "ambient": "keys/pad", "strings": "keys/pad", "experiment": "keys/pad",
             "experimental": "keys/pad", "": "keys/pad",
             "lead": "keys/lead", "pluck": "keys/lead", "arp": "keys/lead", "sequence": "keys/lead",
             "keys": "keys/piano", "bass": "keys/bass"}


# ── les sons ──────────────────────────────────────────────────────────────────────────────────────────────────────
def piano_variants():
    """{stem: chemin} des .sfz de PIANO (un dossier dont le nom dit « piano ») — pas la guitare pompe ni Shinyguitar,
    que le même dossier library/sfz/ range aussi."""
    out = {}
    for root, _dirs, files in os.walk(SFZ_DIR):
        if "piano" not in os.path.relpath(root, SFZ_DIR).lower():
            continue
        for f in files:
            if f.endswith(".sfz"):
                out[f[:-4]] = os.path.join(root, f)
    return dict(sorted(out.items()))


def dx7_names(bank):
    """Les 32 noms d'une banque DX7 (bulk 32 voix : 6 octets d'en-tête, 128 par voix, le nom aux octets 118-127)."""
    try:
        b = open(os.path.join(DX7_DIR, bank + ".syx"), "rb").read()
    except OSError:
        return []
    return [b[6 + i * 128 + 118:6 + i * 128 + 128].decode("ascii", "replace").strip() for i in range(32)]


def _sha256(path):
    from . import tones_sync
    state = tones_sync._load_state()
    sha = tones_sync._sha256_cached(path, state.setdefault("sha_cache", {}))
    tones_sync._save_state(state)
    return sha


def vital_by_sha(sha):
    """Le preset Vital (list_presets) dont le fichier a ce sha256 — usine ou utilisateur ; None sinon."""
    from . import vital
    for p in vital.list_presets():
        if _sha256(p["file"]) == sha:
            return p
    return None


def factory_sounds():
    """Les sons d'usine qui ont une démo, dans l'ordre du lot."""
    from . import vital
    pianos = piano_variants()
    keep = list(pianos) if len(pianos) <= PIANO_MAX_VARIANTS else [s for s in pianos if s == PIANO_DEFAULT]
    out = [f"piano:{s}" for s in keep]
    out += [f"ep:{b}/{n}" for b, n in CURATED_EP if os.path.isfile(os.path.join(DX7_DIR, b + ".syx"))]
    out.append("organ:b3")
    out += [f"vital:{_sha256(p['file'])}" for p in vital.list_presets() if p.get("pack") == "factory"]
    return out


def _ep_ref(name):
    n = name.upper()
    if "ORG" in n:
        return "keys/organ"
    if any(w in n for w in ("HARPSI", "CEMBALO", "CP 70", "AK.PIANO", "FLUEGEL", "PIANO   ")):
        return "keys/piano"
    return "keys/epiano"


def describe(sound):
    """{sound, kind, name, engine, block, refs, fingerprint} — ou le texte du refus (anglais : l'écran le montre)."""
    kind, _, rest = str(sound or "").partition(":")
    if kind == "piano":
        path = piano_variants().get(rest)
        if not path:
            return f"no piano variant named {rest}"
        return {"sound": sound, "kind": kind, "name": rest, "engine": "sfizz", "refs": ["keys/piano"],
                "block": {"id": "piano", "type": "piano", "params": {"sfz": C.rel_posix(path), "volume": 0}},
                "fingerprint": _fp("sfizz", _sha256(path))}
    if kind == "ep":
        bank, _, prog = rest.partition("/")
        path = os.path.join(DX7_DIR, bank + ".syx")
        if "/" in bank or ".." in bank or not os.path.isfile(path) or not prog.isdigit() or not 0 <= int(prog) <= 31:
            return f"no DX7 program {rest}"
        name = (dx7_names(bank) or [""] * 32)[int(prog)]
        return {"sound": sound, "kind": kind, "name": name or rest, "engine": "dexed", "refs": [_ep_ref(name)],
                "block": {"id": "ep", "type": "ep",
                          "params": {"bank": C.rel_posix(path), "patch": int(prog), "fcut": 1.0, "res": 0.0, "out": 0.8}},
                "fingerprint": _fp("dexed", _sha256(path), prog)}
    if kind == "organ":
        if rest != "b3":
            return f"no organ named {rest}"
        return {"sound": sound, "kind": kind, "name": "Tonewheel organ", "engine": "b3", "refs": ["keys/organ"],
                "block": {"id": "organ", "type": "organ", "params": {}}, "fingerprint": _fp("b3", _organ_defaults())}
    if kind == "vital":
        p = vital_by_sha(rest)
        if not p:
            return "no Vital preset with this sha256 on the rack"
        style = str(p.get("style") or "").strip().lower()
        ref = STYLE_REF.get(style)
        return {"sound": sound, "kind": kind, "name": p.get("name") or p["id"], "engine": "vital",
                "refs": [ref] if ref else [], "style": p.get("style") or "",
                "why": None if ref else f"no reference phrase fits a {p.get('style')} sound",
                "block": {"id": "vital", "type": "vital", "params": {"preset": p["id"]}}, "fingerprint": _fp("vital", rest)}
    return f"unknown sound {sound}"


def _organ_defaults():
    from . import scene_bake
    return json.dumps(scene_bake._param_defaults("organ"), sort_keys=True)


def _fp(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def sound_dir(sound):
    kind, _, rest = str(sound).partition(":")
    return os.path.join(C.PREVIEWS_DIR, "sound-" + kind + "-" + store._safe_id(rest.replace("/", "-")))


def leaf(ref):
    return str(ref).split("/")[-1]


def entry(sound):
    return store._read_json(os.path.join(sound_dir(sound), "preview.json"), None)


def up_to_date(d, refs):
    e = entry(d["sound"]) or {}
    clips = e.get("clips") or {}
    return (e.get("fingerprint") == d["fingerprint"] and all(r in clips for r in refs)
            and all(os.path.isfile(os.path.join(C.ROOT, (clips[r] or {}).get("file") or "")) for r in refs))


# ── le rendu ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _doc(d):
    """Le patch d'essai : une lane clavier, l'instrument SEUL, une scène."""
    return {"id": "sound", "name": d["name"], "role": "keys", "kind": "patch", "patch_v": 2, "lanes_v": 2, "bpm": 120,
            "tags": [], "config": {}, "needs": [], "deps": [],
            "lanes": [{"id": "keys-1", "role": "keys", "name": d["name"], "midi": True, "stereo": True,
                       "chain": {"chain": [dict(d["block"])]},
                       "states": [{"id": "st-keys-1-A", "name": "Sound", "blocks": {}, "params": {}, "branches": {}}]}],
            "scenes": [{"id": "A", "name": "Sound", "lanes": {"keys-1": {"state": "st-keys-1-A"}}}]}


def render(sound, seq_of, refs=None, force=False):
    """Rend la démo d'un son. Bloquant (prend le moteur, le rend après chaque clip). {"status", "reason"} comme le lot :
    rendered · skipped (up to date, pas de phrase, son inconnu) · failed."""
    from . import patches as P, preview as PV
    d = describe(sound)
    if isinstance(d, str):
        return {"status": "skipped", "reason": d}
    refs = list(refs or d["refs"])
    if not refs:
        return {"status": "skipped", "reason": d.get("why") or "no reference phrase for this sound"}
    missing = [r for r in refs if not PV._have_di(r)]
    if missing:
        return {"status": "skipped", "reason": f"reference missing: {', '.join(missing)} (run tools/make-midi-refs.py)"}
    if not force and up_to_date(d, refs):
        return {"status": "skipped", "reason": "up to date"}
    pre = P.as_preset(_doc(d))
    if not pre:
        return {"status": "skipped", "reason": "this sound cannot be played on this rack"}
    tmp_id = "preview-sound-" + d["fingerprint"]
    ppath = os.path.join(C.PRESETS_DIR, tmp_id + ".json")
    out_tmp = os.path.join(C.PREVIEWS_DIR, tmp_id + "-ink")
    dst = sound_dir(sound)
    store._write_json_atomic(ppath, dict(pre, id=tmp_id))
    clips, fails = {}, []
    try:
        for ref in refs:
            PV.generate(tmp_id, seq_of(), in_key="k", ref=ref)
            st = PV.status()
            # une démo d'entrée autre que « 1 » s'écrit sous preview.alt.<entrée> (preview._generate_locked)
            pv = ((store._read_json(ppath, {}) or {}).get("preview") or {}).get("alt") or {}
            rel = ((pv.get("k") or {}).get("scenes") or {}).get("A")
            if st.get("phase") != "done" or not rel:
                fails.append(f"{ref}: {st.get('error') or 'no clip'}")
                continue
            os.makedirs(dst, exist_ok=True)
            out = os.path.join(dst, leaf(ref) + ".opus")
            shutil.copy2(os.path.join(C.ROOT, rel), out)
            clips[ref] = {"file": C.rel_posix(out), "seconds": PV._clip_duration(out), "sha256": _sha256(out)}
    finally:
        with __import__("contextlib").suppress(OSError):
            os.remove(ppath)
        shutil.rmtree(out_tmp, ignore_errors=True)
    if not clips:
        return {"status": "failed", "reason": "; ".join(fails) or "no clip rendered"}
    old = (entry(sound) or {}).get("clips") or {}
    keep = {r: c for r, c in old.items() if r not in clips and (entry(sound) or {}).get("fingerprint") == d["fingerprint"]}
    store._write_json_atomic(os.path.join(dst, "preview.json"), {
        "sound": sound, "name": d["name"], "engine": d["engine"], "ref": refs[0], "refs": refs,
        "fingerprint": d["fingerprint"], "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clips": {**keep, **clips}})
    return {"status": "rendered" if not fails else "failed", **({"reason": "; ".join(fails)} if fails else {})}


# ── vers golem.fm ─────────────────────────────────────────────────────────────────────────────────────────────────
def rendered():
    """Les démos de sons rendues sur ce rack : [{sound, ref, fingerprint, clips: {ref: {sha256, seconds}}}] — ce que
    le heartbeat porte (`keys_previews`), pour que golem.fm relie un clip envoyé à la fiche de son son."""
    out = []
    if not os.path.isdir(C.PREVIEWS_DIR):
        return out
    for d in sorted(os.listdir(C.PREVIEWS_DIR)):
        if not d.startswith("sound-"):
            continue
        e = store._read_json(os.path.join(C.PREVIEWS_DIR, d, "preview.json"), None)
        if isinstance(e, dict) and e.get("sound") and e.get("clips"):
            out.append({"sound": e["sound"], "ref": e.get("ref"), "fingerprint": e.get("fingerprint"),
                        "clips": {r: {"sha256": c.get("sha256"), "seconds": c.get("seconds")}
                                  for r, c in e["clips"].items() if isinstance(c, dict)}})
    return out


def push(sound):
    """Envoie les clips d'un son au blob store de golem.fm (le chemin des démos de patch). L'accusé d'une commande :
    {sound, preview: {ref, fingerprint, clips: {ref: {sha256, seconds}}}} ; None si rien n'est parti."""
    from . import preview as PV
    e = entry(sound)
    if not e:
        return None
    sent = {}
    for ref, c in (e.get("clips") or {}).items():
        one = PV.push_clip("sound-" + str(sound).replace(":", "-").replace("/", "-"), leaf(ref), c.get("file") or "")
        if one:
            sent[ref] = {"sha256": one["sha256"], "seconds": c.get("seconds") or one.get("duration")}
    return {"sound": sound, "preview": {"ref": e.get("ref"), "fingerprint": e.get("fingerprint"), "clips": sent}} if sent else None
