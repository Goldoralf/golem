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


_SHA = {}


def _sha256(path):
    """sha256 d'un fichier, mémoïsé EN MÉMOIRE par (chemin, date, taille). Jamais dans l'état de la synchro des tones :
    deux lectures de page simultanées y écrivaient le même fichier temporaire (500 sur /api/drums/kits, 2026-11-14) —
    une page qui lit ne doit rien écrire."""
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key not in _SHA:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _SHA[key] = h.hexdigest()
    return _SHA[key]


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


def _ref_sha(ref):
    """Le sha256 du fichier d'une phrase de référence ; None si elle n'est pas là."""
    from . import preview as PV
    e = PV._di_index().get(ref) or {}
    p = os.path.join(C.DI_REFS_DIR, e.get("file") or "")
    if not (e.get("file") and os.path.isfile(p)):
        return None
    return _sha256(p)


def _ref_fresh(c, ref):
    """Un clip rendu avant qu'on note la phrase (pas de ref_sha) reste bon ; sinon la phrase n'a pas changé."""
    return not c.get("ref_sha") or c["ref_sha"] == _ref_sha(ref)


def up_to_date(d, refs):
    e = entry(d["sound"]) or {}
    clips = e.get("clips") or {}
    return (e.get("fingerprint") == d["fingerprint"] and all(r in clips for r in refs)
            and all(os.path.isfile(os.path.join(C.ROOT, (clips[r] or {}).get("file") or "")) for r in refs)
            and all(_ref_fresh(clips[r], r) for r in refs))


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
            # le sha256 de la PHRASE : une phrase de démo remplacée (on peut les changer) refait le clip
            clips[ref] = {"file": C.rel_posix(out), "seconds": PV._clip_duration(out), "sha256": _sha256(out),
                          "ref_sha": _ref_sha(ref)}
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
    {sound, preview: {ref, fingerprint, clips: {ref: {sha256, seconds}}}} ; None si rien n'est parti. Un clip envoyé
    est marqué (`pushed` = son sha256) : il ne repart pas, et un clip refait repart."""
    from . import preview as PV
    e = entry(sound)
    if not e:
        return None
    sent = {}
    for ref, c in (e.get("clips") or {}).items():
        one = PV.push_clip("sound-" + str(sound).replace(":", "-").replace("/", "-"), leaf(ref), c.get("file") or "")
        if one:
            sent[ref] = {"sha256": one["sha256"], "seconds": c.get("seconds") or one.get("duration")}
            c["pushed"] = one["sha256"]
    if sent:
        store._write_json_atomic(os.path.join(sound_dir(sound), "preview.json"), e)
    return {"sound": sound, "preview": {"ref": e.get("ref"), "fingerprint": e.get("fingerprint"), "clips": sent}} if sent else None


# LES CLIPS DE TES PRESETS VONT À GOLEM.FM (décision du mainteneur, 2026-11-14) : chaque clip d'un preset Vital de
# l'utilisateur part UNE fois au blob store, derrière l'appairage ; golem.fm le relie par `keys_previews` (heartbeat) et
# le sert à son propriétaire seul. Les sons d'USINE ne partent pas : golem.fm les copie lui-même, pour tous.
def _is_user(sound):
    if not str(sound).startswith("vital:"):
        return False
    p = vital_by_sha(str(sound)[6:])
    return bool(p) and p.get("pack") != "factory"


def unpushed():
    """Un son de l'utilisateur dont un clip n'est pas (ou plus) chez golem.fm, ou None."""
    if not os.path.isdir(C.PREVIEWS_DIR):
        return None
    for d in sorted(os.listdir(C.PREVIEWS_DIR)):
        if not d.startswith("sound-vital-"):
            continue
        e = store._read_json(os.path.join(C.PREVIEWS_DIR, d, "preview.json"), None) or {}
        clips = e.get("clips") or {}
        if e.get("sound") and any(c.get("pushed") != c.get("sha256") for c in clips.values()) and _is_user(e["sound"]):
            return e["sound"]
    return None


def push_user(sound):
    """Envoie les clips d'un son s'il est à l'utilisateur ; silencieux sans appairage (rien ne part, on réessaiera)."""
    if not _is_user(sound):
        return None
    r = push(sound)
    if r:
        log.info(f"clips envoyés à golem.fm : {sound[:24]}")
    else:
        log.warning(f"clips NON envoyés à golem.fm : {sound[:24]} (injoignable ou pas appairé ; réessai au repos)")
    return r


# ── Library ▸ Keys (docs/preset-preview.md §9.1) ─────────────────────────────────────────────────────────────────
def _shas(paths):
    return {p: _sha256(p) for p in paths}


def _demo(sound, refs):
    """{status: ready|pending|none, clip, seconds, ref} — la démo d'un son, telle qu'elle est sur ce rack."""
    e = entry(sound) or {}
    clips = e.get("clips") or {}
    for r in list(refs) + list(clips):
        c = clips.get(r)
        if c and os.path.isfile(os.path.join(C.ROOT, c.get("file") or "")):
            # une phrase changée depuis : le clip s'écoute encore, mais il est à refaire (« pending »)
            return {"status": "ready" if _ref_fresh(c, r) else "pending", "clip": "/" + c["file"].lstrip("/"),
                    "seconds": c.get("seconds"), "ref": r}
    return {"status": "pending" if refs else "none", "clip": None, "seconds": None, "ref": refs[0] if refs else None}


def _comments(path):
    """Le commentaire que le sound designer a laissé dans le .vital (« comments »), vide sinon."""
    try:
        return str((json.load(open(path, encoding="utf-8")) or {}).get("comments") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def _ref_name(ref):
    from . import preview as PV
    return ((PV._di_index().get(ref) or {}).get("name")) if ref else None


def catalog():
    """Ce que Library ▸ Keys montre : les instruments (piano, E-Piano par banque et programme, orgue) et les presets
    Vital, chacun avec son identifiant de son, de quoi le dessiner (keysUnit de golem-fx) et l'état de sa démo."""
    from . import vital
    curated = {f"ep:{b}/{n}" for b, n in CURATED_EP}

    def one(sound, name, refs, **kw):
        d = _demo(sound, refs)
        return {"sound": sound, "name": name, **kw, **d, "phrase": _ref_name(d["ref"])}
    pianos = [one(f"piano:{s}", s.replace("+20200602", "").replace("-V3", "").replace("SalamanderGrandPiano", "Grand")
                  .replace("Retuned", ", retuned") or s, ["keys/piano"]) for s in piano_variants()]
    banks = []
    for f in sorted(os.listdir(DX7_DIR)) if os.path.isdir(DX7_DIR) else []:
        if not f.endswith(".syx"):
            continue
        bank = f[:-4]
        progs = []
        for i, nm in enumerate(dx7_names(bank)):
            s = f"ep:{bank}/{i}"
            # seuls les programmes CHOISIS ont une démo d'usine ; les autres : « essaie-le au clavier »
            progs.append(one(s, nm or str(i + 1), [_ep_ref(nm)] if s in curated else [], n=i))
        banks.append({"bank": bank, "programs": progs})
    synths = []
    presets = vital.list_presets()
    shas = _shas([p["file"] for p in presets])
    for p in presets:
        style = str(p.get("style") or "").strip()
        ref = STYLE_REF.get(style.lower())
        synths.append(one(f"vital:{shas[p['file']]}", p.get("name") or p["id"], [ref] if ref else [], id=p["id"],
                          author=p.get("author") or "", style=style, pack=p.get("pack"), macros=p.get("macros") or [],
                          macro_vals=p.get("macro_vals") or [], comments=_comments(p["file"]),
                          why=None if ref else f"No phrase fits a {style or 'style-less'} sound."))
    return {"instruments": [{"type": "piano", "engine": "sfizz", "sounds": pianos},
                            {"type": "ep", "engine": "dexed", "banks": banks},
                            {"type": "organ", "engine": "b3", "sounds": [one("organ:b3", "Tonewheel", ["keys/organ"])]}],
            "synths": synths, "idle": idle_status()}


# ── LES DÉMOS DE TES PRESETS, QUAND LE RACK EST AU REPOS (§9.2) ─────────────────────────────────────────────────────
# Décision du mainteneur (2026-11-14) : les presets de l'utilisateur ont leur démo SANS geste, mais seulement quand
# personne ne se sert du rack — la règle du re-amp (reamp.busy_reason : 10 min sans geste ni signal, pas en Gig,
# pas de prise, pas de morceau, pas de chargement, pas d'autre rendu). Un son à la fois ; la règle est relue avant
# chacun, et le moteur est rendu après chacun. Un rendu raté n'est pas retenté avant que le son change.
IDLE_EVERY_S = 60.0
_IDLE = {"current": None, "waiting_for": None, "done": 0, "failed": {}}
_idle_thread = None


def idle_status():
    return {"current": _IDLE["current"], "waiting_for": _IDLE["waiting_for"], "rendered": _IDLE["done"],
            "failed": len(_IDLE["failed"])}


def _next_pending():
    from . import vital
    presets = [p for p in vital.list_presets() if p.get("pack") != "factory"]
    shas = _shas([p["file"] for p in presets])
    for p in presets:
        s = f"vital:{shas[p['file']]}"
        if STYLE_REF.get(str(p.get("style") or "").strip().lower()) and s not in _IDLE["failed"] \
                and _demo(s, [STYLE_REF[str(p.get("style") or "").strip().lower()]])["status"] == "pending":
            return s
    return None


def idle_tick(seq_of):
    """Un pas du veilleur : rend UN preset en attente si le rack est libre. Rend la raison d'attendre, ou None."""
    from . import preview as PV, reamp
    why = reamp.busy_reason() or ("the demo batch is running" if PV._BATCH["running"] else None) \
        or ("a demo is rendering" if PV.rendering() else None)
    if why:
        _IDLE["waiting_for"] = why
        return why
    s = _next_pending()
    if not s:
        # puis les kits de batterie importés (docs/drums-library.md) : leurs quatre démos, un kit à la fois
        from . import drum_preview as DP, kits as K
        kid = next((k["id"] for k in K.list_kits() if not k.get("factory") and k.get("role") == "drum"
                    and k.get("available") is not False and ("kit:" + k["id"]) not in _IDLE["failed"]
                    and DP.demo(k)["status"] == "pending"), None)
        if not kid:
            _IDLE["waiting_for"] = None
            # rien à rendre : un clip qui n'a pas pu partir (golem.fm injoignable, pas encore appairé) repart, un par pas
            u = unpushed()
            if u and push_user(u):
                return None
            uk = DP.unpushed()                          # les démos d'un kit importé, de même
            if uk and DP.push_user(uk):
                return None
            return "nothing to render"
        _IDLE.update(current="kit:" + kid, waiting_for=None)
        try:
            r = DP.render_kit(kid, seq_of)
            if r["status"] == "rendered":
                _IDLE["done"] += 1
                DP.push_user(kid)
            else:
                _IDLE["failed"]["kit:" + kid] = r.get("reason")
            log.info(f"démo au repos : kit {kid} → {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else ""))
        finally:
            _IDLE["current"] = None
        return None
    _IDLE.update(current=s, waiting_for=None)
    try:
        r = render(s, seq_of)
        if r["status"] == "rendered":
            _IDLE["done"] += 1
            push_user(s)
        else:
            _IDLE["failed"][s] = r.get("reason")
        log.info(f"démo au repos : {s[:20]} → {r['status']}" + (f" ({r.get('reason')})" if r.get("reason") else ""))
    finally:
        _IDLE["current"] = None
    return None


def start_idle():
    """Le veilleur, démarré avec le bridge. GOLEM_KEYS_IDLE_RENDER=0 le coupe (un banc, la CI)."""
    global _idle_thread
    if os.environ.get("GOLEM_KEYS_IDLE_RENDER", "1") == "0" or (_idle_thread and _idle_thread.is_alive()):
        return
    import itertools
    import threading
    seq = itertools.count(60000)

    def loop():
        while True:
            try:
                busy = idle_tick(lambda: next(seq))
            except Exception as e:                     # le veilleur ne meurt jamais
                log.error(f"démo au repos : {e}")
                busy = "error"
            time.sleep(IDLE_EVERY_S if busy else 2.0)
    _idle_thread = threading.Thread(target=loop, daemon=True, name="keys-idle-render")
    _idle_thread.start()
