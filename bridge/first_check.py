# SPDX-License-Identifier: GPL-3.0-or-later
"""LA VÉRIFICATION DE PREMIÈRE INSTALLATION (docs/health.md §2, maquette mockups/first-check.html validée le
2026-10-20). Une fois, à la fin du premier démarrage — et rejouable depuis Settings ▸ Health. Elle continue l'écran
de chargement : d'abord ce que la machine a vu toute seule (moteur, carte, contenu d'usine, premier preset posé —
les faits de bridge/health.py), puis trois gestes qu'aucune machine ne peut faire à la place du musicien :
brancher et jouer (du signal sur UNE entrée de la carte, n'importe laquelle : on dit laquelle, ce qui y est branché, et si
le gain est bon), écouter (le clic joue sur la sortie : l'entend-il ?), appuyer sur un switch
(le pédalier répond). Chaque geste a UNE mesure et un verdict d'une phrase ; l'écran a toujours une sortie.

Le résultat vit dans `config/.first-check.json` (local) et part dans le paquet de démarrage (diag, section
`first_check`) : quand quelqu'un dit plus tard « ça n'a jamais marché chez moi », on sait ce que la machine a vu le
premier jour. `pending()` tant qu'elle n'a été ni finie ni passée ; un rack installé avant cette version la voit
une fois, à son prochain démarrage — « Skip for now » suffit."""
import contextlib
import json
import os
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("first-check")
PATH = lambda: os.path.join(C.CONFIG_DIR, ".first-check.json")   # noqa: E731 — le dossier de config du MOMENT
STEPS = ("input", "output", "foot")
_FC_TITLES = {"input": "No signal on any input", "output": "The click was not heard", "foot": "The pedalboard did not answer"}
# Le vumètre OSC de REAPER (TRACK_VU n/track/@/vu) est LINÉAIRE EN dB : 0 → −72 dB, 1 → +6 dB. Mesuré au rig le
# 2026-10-20 : crête −18,0 dBFS (Track_GetPeakInfo, tools/check-silence.py) ↔ vumètre 0,685 (formule : 0,692) ; le
# silence à −78 dBFS rend 0. Ce n'est PAS une amplitude : 20·log10 du vumètre donnait −3 dB pour une crête à −18.
VU_MIN_DB, VU_MAX_DB = -72.0, 6.0
INPUT_MIN_DB = -45               # crête au-dessus : quelqu'un joue (le bruit de fond d'une entrée vide est sous −72)
GAIN_LOW_DB = -24                # crête sous ce seuil : le gain de la carte est trop bas (on joue, mais faible)
GAIN_HOT_DB = -3                 # crête au-dessus : trop chaud, l'écrêtage n'est pas loin
FOOT_WAIT_S = 30                 # rien n'est une erreur avant son délai : le pédalier a trente secondes


def _read():
    try:
        with open(PATH(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d):
    from .store import _write_json_atomic
    os.makedirs(os.path.dirname(PATH()), exist_ok=True)
    _write_json_atomic(PATH(), d)


def pending():
    d = _read()
    return not (d.get("done_at") or d.get("skipped_at"))


def _verdict(d):
    """ok : les trois gestes verts · partial : un geste rouge ou passé · None : pas fini."""
    steps = d.get("steps") or {}
    if not d.get("done_at"):
        return None
    return "ok" if all((steps.get(s) or {}).get("ok") for s in STEPS) else "partial"


_BRIEF = {"key": None, "value": None}


def brief():
    """Pour `state.snapshot()` : l'écran décide d'afficher la vérification là-dessus. Appelé à chaque diffusion (jusqu'à
    20 Hz pendant qu'on joue) : un `stat` du fichier, et le document n'est relu que s'il a changé."""
    try:
        st = os.stat(PATH())
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if _BRIEF["key"] == key and _BRIEF["value"] is not None:
        return _BRIEF["value"]
    d = _read()
    v = {"pending": not (d.get("done_at") or d.get("skipped_at")), "done_at": d.get("done_at"),
         "skipped_at": d.get("skipped_at"), "verdict": _verdict(d)}
    _BRIEF.update(key=key, value=v)
    return v


def vu_db(vu):
    """Le vumètre OSC normalisé (0..1) en dBFS ; None sous le plancher (0 = rien au-dessus de −72 dB)."""
    try:
        v = float(vu)
    except (TypeError, ValueError):
        return None
    return round(VU_MIN_DB + v * (VU_MAX_DB - VU_MIN_DB), 1) if v > 0 else None


_db = vu_db


def gain_of(peak_db, clipped=False):
    """Le verdict de gain d'une crête : low · good · hot. L'écrêtage vu par le bridge (state.clip) l'emporte."""
    if clipped:
        return "hot"
    if peak_db is None:
        return None
    return "low" if peak_db < GAIN_LOW_DB else "hot" if peak_db > GAIN_HOT_DB else "good"


def auto_facts():
    """Ce que la machine a vu toute seule — les faits de Health, dits pour cet écran. Toujours quatre lignes ;
    une sonde absente rend « wait », jamais une invention."""
    from . import health
    from .state import state as st
    hf = {f["id"]: f for f in (health.facts() or {}).get("facts", [])}
    out = []
    eng = hf.get("engine") or {"level": "wait", "text": "not measured"}
    out.append({"id": "engine", "name": "Engine", "level": eng["level"],
                "text": eng["text"].replace("running · talking to the bridge", "started and answers the bridge")})
    au = hf.get("audio") or {"level": "wait", "text": "not measured"}
    out.append({"id": "audio", "name": "Sound card", "level": au["level"], "text": au["text"]})
    # le contenu d'usine : ce qu'il y a à jouer, et les plugins que REAPER a trouvés
    try:
        from .routes_system import system_content
        c = system_content() or {}
        sizes = c.get("sizes") or {}
        many = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")      # « 1 song », pas « 1 songs »
        bits = [many(c.get("presets", 0), "preset"), many((sizes.get("patches") or {}).get("n", 0), "patch").replace("patchs", "patches"),
                many((sizes.get("songs") or {}).get("n", 0), "song"), many((sizes.get("kits") or {}).get("n", 0), "kit")]
        with contextlib.suppress(Exception):
            from . import blockstatus as BS
            n = (BS.inventory() or {}).get("n")
            if n is not None:
                bits.append(many(n, "plugin") + " found")
        out.append({"id": "content", "name": "Factory content", "level": "ok", "text": " · ".join(bits)})
    except Exception as e:
        _swallowed(e)
        out.append({"id": "content", "name": "Factory content", "level": "wait", "text": "not counted"})
    # le premier preset : posé, et ses fichiers vérifiés (rig-check) — le nombre de blocs vient du livemap
    name = (str(st.preset_name).replace("⛓", "", 1).strip() if st.preset_name else None) or st.preset_id
    rc = st.rig_check or {}
    blocks = None
    with contextlib.suppress(Exception):
        with open(os.path.join(C.PRESETS_DIR, ".livemap.json"), encoding="utf-8") as f:
            blocks = len((json.load(f) or {}).get("blocks") or {})
    if not name:
        out.append({"id": "preset", "name": "First preset", "level": "wait", "text": "not loaded yet"})
    elif rc.get("ok") is True:
        out.append({"id": "preset", "name": "First preset", "level": "ok",
                    "text": f"“{name}” posed" + (f": {blocks} blocks" if blocks else "") + f", every file loaded ({rc.get('checked', 0)} checked)"})
    elif rc.get("ok") is False:
        bad = [i for i in rc.get("issues") or [] if isinstance(i, dict) and not i.get("repaired")]
        out.append({"id": "preset", "name": "First preset", "level": "bad" if bad else "warn",
                    "text": f"“{name}” posed, {len(bad)} file{'s' if len(bad) != 1 else ''} not loaded" if bad
                    else f"“{name}” posed, files repaired after the build"})
    else:
        out.append({"id": "preset", "name": "First preset", "level": "wait", "text": f"“{name}” posed, not verified yet"})
    return out


def status():
    d = _read()
    return {"pending": pending(), "started_at": d.get("started_at"), "steps": d.get("steps") or {},
            "current": d.get("current"), "done_at": d.get("done_at"), "skipped_at": d.get("skipped_at"),
            "took_s": d.get("took_s"), "verdict": _verdict(d), "auto": auto_facts(), "now": round(time.time(), 3),
            "foot_wait_s": FOOT_WAIT_S}


def begin(step=None):
    """Ouvre la vérification (ou un geste) : date le départ — la référence des mesures (le pédalier doit avoir
    répondu APRÈS ce moment, pas la veille). Les gestes d'une passe précédente finie ou passée sont oubliés."""
    now = round(time.time(), 3)
    d = _read()
    if d.get("done_at") or d.get("skipped_at") or not d.get("started_at"):
        prev = {k: d[k] for k in ("done_at", "skipped_at", "steps", "took_s") if k in d}
        d = {"started_at": now, "steps": {}, **({"previous": prev} if prev else {})}
    if step:
        if step not in STEPS:
            raise ValueError(f"unknown step '{step}'")
        d["current"] = {"step": step, "at": now}
    _write(d)
    return {"ok": True, "at": now, "step": step}


def record(step, ok=None, measured=None):
    """Le verdict d'un geste. La machine vérifie ce qu'elle peut : pour le pédalier, un message reçu APRÈS le
    départ du geste (foot.last_heard) ; pour l'écoute, que le clic a vraiment tourné (.click.json) ; pour le
    signal, la crête que l'écran a vue sur le vumètre OSC (en dB)."""
    if step not in STEPS:
        raise ValueError(f"unknown step '{step}'")
    d = _read()
    if not d.get("started_at") or d.get("done_at") or d.get("skipped_at"):
        begin()
        d = _read()
    now = round(time.time(), 3)
    cur = d.get("current") or {}
    since = float(cur.get("at") or d.get("started_at") or now) if cur.get("step") == step else float(d.get("started_at") or now)
    m = dict(measured or {})
    entry = {"at": now, "took_s": round(now - since, 1)}
    if step == "input":
        # l'entrée où l'écran a vu jouer (n'importe laquelle), ce que le musicien y a confirmé (un INSTRUMENT, jamais
        # un nom) et le verdict de gain de sa crête
        peak = m.get("peak")
        entry["peak_db"] = _db(peak)
        try:
            entry["input"] = int(m.get("input")) if m.get("input") is not None else None
        except (TypeError, ValueError):
            entry["input"] = None
        if m.get("role"):
            entry["role"] = str(m["role"])[:24]
        entry["ok"] = bool(ok) if ok is not None else (entry["peak_db"] is not None and entry["peak_db"] >= INPUT_MIN_DB)
        entry["gain"] = gain_of(entry["peak_db"], bool(m.get("clipped"))) if entry["ok"] else None
    elif step == "output":
        ticks = None
        with contextlib.suppress(Exception):
            with open(os.path.join(C.PRESETS_DIR, ".click.json"), encoding="utf-8") as f:
                ticks = (json.load(f) or {}).get("ticks")
        entry["click_ticks"] = ticks
        entry["heard"] = bool(m.get("heard")) if "heard" in m else bool(ok)
        entry["ok"] = entry["heard"]
    else:
        heard = None
        with contextlib.suppress(Exception):
            from . import foot
            heard = foot.last_heard()
        entry["answered"] = bool(heard and float(heard) >= since)
        entry["ok"] = entry["answered"] if ok is None else (bool(ok) and entry["answered"])
    d.setdefault("steps", {})[step] = entry
    d.pop("current", None)
    _write(d)
    # un geste raté est un incident ; réussi plus tard, il se ferme (docs/assistant.md §3.1)
    with contextlib.suppress(Exception):
        from . import incidents
        incidents.probe("first_check", step, not entry["ok"], _FC_TITLES[step], match_code=True)
    log.info(f"première installation : {step} → {'ok' if entry['ok'] else 'ko'} ({entry})")
    return {"ok": True, "step": step, "result": entry}


def finish():
    d = _read()
    now = round(time.time(), 3)
    d["done_at"] = now
    d["took_s"] = round(now - float(d.get("started_at") or now), 1)
    d.pop("current", None)
    d.pop("skipped_at", None)
    _write(d)
    log.info(f"première installation finie en {d['took_s']} s : {_verdict(d)}")
    return {"ok": True, "done_at": now, "verdict": _verdict(d), "took_s": d["took_s"]}


def skip():
    d = _read()
    d["skipped_at"] = round(time.time(), 3)
    d.pop("current", None)
    _write(d)
    return {"ok": True, "skipped_at": d["skipped_at"]}


def reset():
    """Rejouer depuis Settings ▸ Health : la vérification redevient « pending », la passe d'avant est gardée."""
    d = _read()
    prev = {k: d[k] for k in ("done_at", "skipped_at", "steps", "took_s") if k in d}
    _write({"previous": prev} if prev else {})
    return {"ok": True, "pending": True}


def section():
    """La section `first_check` du paquet de diagnostic (docs/diagnostics.md §2.2) : des verdicts et des durées,
    jamais un nom. None tant que rien n'a été fait."""
    d = _read()
    if not d.get("started_at"):
        return None
    steps = {}
    for s in STEPS:
        e = d.get("steps", {}).get(s)
        if e:
            steps[s] = {k: e.get(k) for k in ("ok", "took_s", "peak_db", "input", "role", "gain", "click_ticks", "heard", "answered") if k in e}
    return {"done_at": d.get("done_at"), "skipped": bool(d.get("skipped_at")), "took_s": d.get("took_s"),
            "verdict": _verdict(d), "steps": steps}
