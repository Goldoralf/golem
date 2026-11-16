# SPDX-License-Identifier: GPL-3.0-or-later
"""LE BANC CPU (docs/cpu-budget.md §2, lot 1) : ce que coûte chaque bloc sur CETTE machine -> config/cpu-profile.json.

COMMENT on mesure (jamais sur le chemin vivant) : le moteur des démos (bridge/preview.py, golem_preview.lua).
  1. un patch de banc d'UNE lane qui ne porte que le bloc mesuré, avec ses défauts du catalogue, est posé par le chemin
     du rappel (recall.emit_sandbox_preset) — la lane est COUPÉE dans sa scène (niveau au plancher) : rien ne sort aux
     baffles pendant le banc, même si quelqu'un branche une guitare ;
  2. golem_preview clone la lane (piste jetable, sans sortie matérielle, désarmée) et y pose une DI de référence ;
  3. op « render » + `bench: N` : N rendus HORS LIGNE pleine vitesse, chronométrés (time_precise autour de l'action de
     rendu), puis les FX du clone retirés et N rendus de la même DI sans aucun FX (la ligne de base : lecture, écriture
     du WAV, rééchantillonnage) ;
  4. coût du bloc = (médiane avec − médiane sans) / nombre de buffers rendus, moins le coût mesuré une fois de la lane
     VIDE (les FX système que golem pose sur toute lane : volume-sys…). Le pire = le rendu le plus lent contre le plus
     rapide sans FX.
LIMITES (dites, pas cachées) : un temps de rendu total ne voit pas les pointes d'UN buffer (une simulation de circuit
qui décroche une fois par seconde) ; « worst » est l'écart entre tours, pas le pire buffer. Le rendu hors ligne tourne
sur un fil pendant que le moteur vivant tourne aussi : le bruit de la machine entre dans les deux mesures et se
soustrait en moyenne. Précision attendue : quelques µs par buffer sur un rendu d'une dizaine de secondes.

QUAND : au repos seulement (reamp.busy_reason : 10 min sans geste, pas de prise, pas de morceau, pas en Gig, pas
d'autre rendu), un bloc à la fois, la règle relue avant chacun ; reprenable (chaque mesure est écrite dès qu'elle
tombe). Ne re-mesure que ce qui manque ou a changé : l'empreinte du plugin (binaire golem-fx, identifiant scanné par
REAPER, version du NAM), la machine (CPU, cœurs, fréquence, buffer, moteur). Une nouvelle installation (pas de
profil), une mise à jour qui change un plugin, un plugin ajouté, une autre machine : tout ça devient « en attente » de
lui-même. POST /api/cpu/calibrate le lance à la main (sans la règle des 10 min : quelqu'un est devant l'écran).
Le moteur est rendu à la fin (la sandbox d'avant reposée) — seulement si le rig est encore celui du banc.
"""
import contextlib
import hashlib
import itertools
import json
import os
import platform
import re
import threading
import time

from . import config as C
from . import cpu_budget as CB
from .golog import get

log = get("cpu-bench")

RUNS = 3                       # rendus avec le bloc, puis autant sans aucun FX
SETTLE_S = 3.0                 # le rig du banc se construit, NAM/IR chargent (preview.FIRST_SETTLE_S)
CLONE_SETTLE_S = 2.0           # le clone recharge ses plugins (preview.CLONE_SETTLE_S)
POLL_TIMEOUT_S = 120.0
IDLE_EVERY_S = 60.0
BENCH_DOC_ID = "cpu-bench"
LANE_ID = "bench-1"
SYSTEM_KEY = CB.profile_key("_system")       # la lane vide : ce que golem pose sur toute lane
DI_PREFS = ("guitar/clean", "guitar/crunch", "guitar/high-gain")

_ST = {"state": "idle", "done": 0, "total": 0, "current": None, "waiting_for": None, "error": None,
       "running": False, "manual": False}
_lock = threading.Lock()
_stop = threading.Event()
_thread = {"idle": None, "run": None}
_seq = itertools.count(70000)


def profile_path():
    return os.path.join(C.CONFIG_DIR, "cpu-profile.json")


def work_dir():
    return os.path.join(C.PRESETS_DIR, ".cpu-bench")


def load_profile():
    try:
        with open(profile_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_profile(prof):
    from . import store
    os.makedirs(os.path.dirname(profile_path()), exist_ok=True)
    store._write_json_atomic(profile_path(), prof)


# ── la machine ──────────────────────────────────────────────────────────────────────────────────────────────────
def _cpu_model():
    with contextlib.suppress(OSError):
        m = re.search(r"^model name\s*:\s*(.+)$", open("/proc/cpuinfo", encoding="utf-8").read(), re.M)
        if m:
            return m.group(1).strip()
    return platform.processor() or platform.machine() or None


def _srate():
    with contextlib.suppress(Exception):
        from . import rigstatus
        sr = (rigstatus.engine_doc() or {}).get("samplerate")
        if sr:
            return int(sr)
    with contextlib.suppress(Exception):
        from .routes_system import REAPER_INI
        m = re.search(r"^linux_audio_srate=(\d+)", open(REAPER_INI, encoding="utf-8", errors="replace").read(), re.M)
        if m:
            return int(m.group(1))
    return None


def machine_now():
    """{cpu, cores, governor, srate, bsize, engine} — ce que la machine est AUJOURD'HUI (chaque sonde tolérante)."""
    out = {"cpu": _cpu_model(), "cores": os.cpu_count(), "governor": None, "srate": None, "bsize": None, "engine": None}
    with contextlib.suppress(Exception):
        from .routes_system import _cpu_governor, _read_bsize
        out["governor"] = _cpu_governor()
        out["bsize"] = _read_bsize()
    out["srate"] = _srate()
    with contextlib.suppress(Exception):
        from . import engine
        out["engine"] = engine.get().id
    return out


def remeasure_fp(m):
    """Ce qui oblige à re-mesurer (§2) : CPU, cœurs, fréquence, buffer, moteur. Le gouverneur non (il se dit)."""
    return "|".join(str((m or {}).get(k)) for k in ("cpu", "cores", "srate", "bsize", "engine"))


def valid_fp(m):
    """Ce qui rend une mesure FAUSSE (pas seulement à refaire) : un autre processeur ou un autre moteur. Un buffer ou
    une fréquence qui change se corrige au prorata des échantillons (cpu_budget.entry_us) en attendant le banc."""
    return "|".join(str((m or {}).get(k)) for k in ("cpu", "cores", "engine"))


def usable_profile(prof=None, machine=None):
    """Le profil tel que l'estimation peut le lire : vide si la machine a changé de processeur ou de moteur."""
    prof = load_profile() if prof is None else prof
    machine = machine or machine_now()
    if prof.get("machine") and valid_fp(prof["machine"]) != valid_fp(machine):
        return dict(prof, blocks={})
    return prof


# ── les empreintes des plugins ───────────────────────────────────────────────────────────────────────────────────
_SHA = {}


def _sha_file(path):
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _SHA:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _SHA[key] = h.hexdigest()
    return _SHA[key]


def _bundle_hash(bundle):
    """sha256 des binaires d'un bundle VST3 (Contents/<arch>/*.so|.dll|.dylib…), « » s'il n'y en a pas."""
    h = hashlib.sha256()
    found = False
    for root, _d, files in sorted(os.walk(bundle)):
        for f in sorted(files):
            if f.endswith((".so", ".dll", ".dylib", ".vst3")) or "MacOS" in root:
                with contextlib.suppress(OSError):
                    h.update(_sha_file(os.path.join(root, f)).encode())
                    found = True
    return h.hexdigest() if found else ""


def _gfx_tables():
    from .engine import ardour_plan
    table = ardour_plan.load_table()
    with open(os.path.join(C.ROOT, "library", "catalog", "golem-fx-plugins.json"), encoding="utf-8") as f:
        plugins = json.load(f).get("plugins", {})
    return table, plugins


def golem_fx_hash(btype, tables=None):
    """L'empreinte du binaire golem-fx qui joue ce type sous REAPER (table de l'Engine), « » si aucun ne le joue."""
    try:
        from . import rig
        table, plugins = tables or _gfx_tables()
        spec = table.get(btype) or {}
        cid = spec.get("vst3") if spec.get("golem_fx") else None
        if not cid:
            return ""
        name = (plugins.get(cid) or {}).get("name")
        for d in rig.golem_fx_dirs():
            b = os.path.join(d, f"{name}.vst3")
            if name and os.path.isdir(b):
                return _bundle_hash(b)
    except Exception:
        return ""
    return ""


_INV = {"key": None, "rows": [], "reaper": None}


def _inventory():
    from . import blockstatus as BS
    try:
        st = os.stat(BS.INVENTORY)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return [], None
    if _INV["key"] != key:
        try:
            d = json.load(open(BS.INVENTORY, encoding="utf-8")) or {}
            _INV.update(key=key, rows=[r for r in d.get("fx") or [] if isinstance(r, list) and r], reaper=d.get("reaper"))
        except (OSError, ValueError):
            _INV.update(key=key, rows=[], reaper=None)
    return _INV["rows"], _INV["reaper"]


def _ident(plugin):
    """L'identifiant que REAPER a scanné pour ce plugin (fichier, URI, version…), « » s'il n'est pas trouvé."""
    from . import blockstatus as BS
    rows, _r = _inventory()
    n = BS._norm(plugin)
    for r in rows:
        if n and n in BS._norm(r[0]):
            return str(r[1] if len(r) > 1 else r[0])
    return ""


def _h(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── ce qu'on mesure ──────────────────────────────────────────────────────────────────────────────────────────────
def _defaults(entry):
    return {p["id"]: p.get("default") for p in entry.get("params") or [] if p.get("id") and p.get("default") is not None}


def _plugin_targets():
    """Un bloc du catalogue que REAPER joue par un plugin : défauts du catalogue. Jamais un bloc en quarantaine, ni un
    bloc qui n'a pas passé le banc de gel (`bench: pending` — il peut figer REAPER), ni un instrument, ni un bloc qui
    charge un fichier (captures et IR : mesurés par architecture et par longueur), ni un plugin absent d'ici."""
    from . import blockstatus as BS, rig
    cat = CB._catalog()
    try:
        quarantine = set(rig.quarantined_types())
    except Exception:
        quarantine = set()
    inv = None
    with contextlib.suppress(Exception):
        inv = BS.inventory()
    _rows, reaper_v = _inventory()
    try:
        tables = _gfx_tables()
    except Exception:
        tables = ({}, {})
    out = []
    for t, e in cat.items():
        plugin = e.get("plugin")
        if not plugin or e.get("engine") not in ("plugin", None) or e.get("bench") or t in quarantine:
            continue
        if t in CB.NAM_TYPES or t in CB.IR_TYPES or t in CB.INSTRUMENT_TYPES or e.get("loads") or e.get("content_param"):
            continue
        if t == "capture-module":                       # joue un module .gcap : rien à mesurer sans lui
            continue
        gfx = golem_fx_hash(t, tables)
        try:
            absent = bool(inv) and not gfx and not BS._in_inventory(plugin, inv)
        except (KeyError, TypeError):
            absent = False                               # inventaire d'une autre forme : on tente, le banc le dira
        if absent:
            continue                                     # pas installé ici : « non mesuré », pas une mesure à 0
        block = {"id": "b1", "type": t, "params": _defaults(e)}
        out.append({"key": CB.profile_key(t), "kind": t, "variant": None, "label": e.get("name") or t, "block": block,
                    "hash": _h(plugin, block["params"], gfx, _ident(plugin), reaper_v)})
    return out


def _capture_targets():
    """Une capture NAM INSTALLÉE par architecture (bloc amp : la capture seule, sans baffle fondu), une IR par classe
    de longueur (la plus longue de sa classe : prudence), pour le baffle (x42 mono) et pour ir-fx (x42 stéréo)."""
    from . import rig
    from .resolver import _components, _resolve, _tones_index
    rows, reaper_v = _inventory()
    nam_v = rig._nam_golem_version() if hasattr(rig, "_nam_golem_version") else ""
    try:
        unreadable = set(rig.nam_unreadable())
    except Exception:
        unreadable = set()
    nam, irs = {}, {}
    for tone in _tones_index().values():
        gear = tone.get("gear")
        for m in tone.get("models") or []:
            f = os.path.join(C.ROOT, str(m.get("file") or ""))
            if not m.get("file") or not os.path.isfile(f):
                continue
            if f.lower().endswith((".nam", ".json")):
                if str(m.get("arch")) == "2":
                    if "SlimmableContainer" in unreadable:
                        continue
                    v = "a2"
                else:
                    v = CB.nam_variant(f)
                if v and v not in nam:
                    nam[v] = (str(tone.get("id")), m.get("id"), m.get("name") or tone.get("title"))
            elif f.lower().endswith(".wav"):
                kind = "cab" if gear == "cab" else "ir-fx"
                ms = CB.wav_ms(f)
                b = CB.ir_bucket(ms)
                if b and (ms or 0) > irs.get((kind, b), (0,))[0]:
                    irs[(kind, b)] = (ms, str(tone.get("id")), m.get("id"), m.get("name") or tone.get("title"))
    # le baffle par défaut qu'une tête isolée reçoit (compile_rig.DEFAULT_CAB) : sa classe est toujours mesurée
    with contextlib.suppress(Exception):
        from . import compile_rig
        f = _resolve(compile_rig.DEFAULT_CAB, _components())
        ms = CB.wav_ms(f) if f else None
        b = CB.ir_bucket(ms)
        if b and ("cab", b) not in irs:
            irs[("cab", b)] = (ms, compile_rig.DEFAULT_CAB, None, "default cab")
    nam_ident = _ident("neural_amp_modeler") or _ident("Neural Amp Modeler")
    out = []
    for v, (ref, model, name) in sorted(nam.items()):
        out.append({"key": CB.profile_key("nam", v), "kind": "nam", "variant": v, "label": f"NAM {v} ({name})",
                    "block": {"id": "b1", "type": "amp", "ref": ref, **({"model": model} if model is not None else {})},
                    "hash": _h("nam", v, nam_ident, nam_v, reaper_v)})
    for (kind, b), (_ms, ref, model, name) in sorted(irs.items()):
        plugin = "x42 - IR Convolver Mono" if kind == "cab" else "x42 - IR Convolver Stereo"
        out.append({"key": CB.profile_key(kind, b), "kind": kind, "variant": b, "label": f"{kind} IR {'over 5 s' if b == 'long' else '≤ ' + b} ({name})",
                    "block": {"id": "b1", "type": kind, "ref": ref, **({"model": model} if model is not None else {})},
                    "hash": _h(kind, b, _ident(plugin), reaper_v)})
    return out


def _vst_host_targets():
    """Les plugins choisis dans VST Host qui figurent dans un preset ou la sandbox : mesurés la première fois (§2)."""
    from . import recall, rig, store
    seen = {}
    docs = []
    with contextlib.suppress(Exception):
        sb = store._read_json(recall.SANDBOX_BUF, {}) or {}
        if isinstance(sb.get("preset"), dict):
            docs.append(sb["preset"])
    import glob
    for p in sorted(glob.glob(os.path.join(C.PRESETS_DIR, "*.json"))):
        if not os.path.basename(p).startswith("."):
            docs.append(store._read_json(p, {}) or {})
    for d in docs:
        for b in CB._walk_typed(d, "vst-host"):
            name = str(b.get("plugin") or "")
            if name and not rig.quarantined_plugin(name):
                seen.setdefault(CB.plugin_slug(name), name)
    _rows, reaper_v = _inventory()
    return [{"key": CB.profile_key("vst-host", slug), "kind": "vst-host", "variant": slug, "label": name,
             "block": {"id": "b1", "type": "vst-host", "plugin": name}, "hash": _h("vst-host", name, _ident(name), reaper_v)}
            for slug, name in sorted(seen.items())]


_TG = {"at": 0.0, "list": None}
TARGETS_TTL_S = 60.0


def targets(fresh=False):
    """Tout ce que le banc sait mesurer sur cette machine, la lane vide d'abord (les autres s'y soustraient). Gardé
    une minute : Health et /api/cpu/profile le relisent souvent, le catalogue change rarement."""
    if not fresh and _TG["list"] is not None and time.time() - _TG["at"] < TARGETS_TTL_S:
        return list(_TG["list"])
    out = _targets()
    _TG.update(at=time.time(), list=out)
    return list(out)


def _targets():
    _rows, reaper_v = _inventory()
    out = [{"key": SYSTEM_KEY, "kind": "_system", "variant": None, "label": "empty lane", "block": None,
            "hash": _h("_system", reaper_v)}]
    for fn in (_plugin_targets, _capture_targets, _vst_host_targets):
        try:
            out += fn()
        except Exception as e:                           # une famille qui casse n'emporte pas les autres
            log.warning(f"banc CPU : cibles {fn.__name__} : {e}")
    return out


def pending(prof, tgts, machine, force=False, types=None):
    """Les cibles à (re)mesurer : absentes, d'une autre empreinte de plugin, d'une autre machine (§2). Un échec
    n'est retenté qu'à empreinte ou machine changée (ou `force`). `types` : seulement ces types (et la lane vide si
    elle manque)."""
    fp = remeasure_fp(machine)
    pfp = remeasure_fp(prof.get("machine")) if prof.get("machine") else None
    blocks, failed = prof.get("blocks") or {}, prof.get("failed") or {}
    out = []
    for t in tgts:
        if types and t["kind"] not in types and t["key"] != SYSTEM_KEY:
            continue
        e = blocks.get(t["key"])
        stale = force or e is None or e.get("hash") != t["hash"] or (e.get("fp") or pfp) != fp
        if not stale:
            continue
        f = failed.get(t["key"])
        if f and not force and f.get("hash") == t["hash"] and f.get("fp") == fp:
            continue
        out.append(t)                                    # `tgts` porte la lane vide en tête : elle passe d'abord
    return out


# ── une mesure dans REAPER ───────────────────────────────────────────────────────────────────────────────────────
class BenchError(Exception):
    pass


class Interrupted(Exception):
    """Quelqu'un a repris le rig pendant la mesure (un rappel), ou REAPER n'a pas répondu à temps : la mesure est
    jetée SANS être notée comme un échec (elle sera refaite), le banc s'arrête."""


def bench_doc(block):
    """Le patch de banc : une lane audio, le bloc seul (ou rien : la lane vide), COUPÉE dans sa scène."""
    return {"id": BENCH_DOC_ID, "name": "CPU bench", "role": "guitar", "kind": "patch", "patch_v": 2, "lanes_v": 2,
            "bpm": 120, "tags": [], "config": {}, "needs": [], "deps": [],
            "lanes": [{"id": LANE_ID, "role": "guitar", "name": "CPU bench", "midi": False, "stereo": False,
                       "chain": {"chain": [dict(block)] if block else []},
                       "states": [{"id": f"st-{LANE_ID}-A", "name": "Bench", "blocks": {}, "params": {}, "branches": {}}]}],
            "scenes": [{"id": "A", "name": "Bench", "lanes": {LANE_ID: {"state": f"st-{LANE_ID}-A", "mute": True}}}]}


def _di():
    from . import preview as PV
    idx = PV._di_index()
    for ref in DI_PREFS + tuple(sorted(idx)):
        e = idx.get(ref) or {}
        p = os.path.join(C.DI_REFS_DIR, e.get("file") or "")
        if e.get("file") and e.get("kind") != "midi" and os.path.isfile(p):
            return p
    return None


def _poll(scene, timeout):
    from . import store
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = store._read_json(C.PREVIEW_FILE, None)
        if d and d.get("scene") == scene and d.get("done"):
            return d
        if _stop.is_set():
            return None
        time.sleep(0.4)
    return None


def _floats(s):
    return [float(x) for x in str(s or "").split(",") if x.strip()]


def measure_reaper(target, machine, seq):
    """Une mesure : patch de banc posé, clone rendu N fois avec et sans FX par golem_preview. Rend la mesure BRUTE
    {avg_us, worst_us, nfx, srate, bsize} (la lane vide pas encore soustraite)."""
    from . import patches as P, preview as PV, recall
    from .commands import write_command
    pre = P.as_preset(bench_doc(target.get("block")))
    if not pre:
        raise BenchError("the bench patch cannot be built")
    in_key = PV.audition_input(pre, LANE_ID)
    if not in_key:
        raise BenchError("no audio input on this card for the bench lane")
    di = _di()
    if not di:
        raise BenchError("no reference DI (library/di-refs)")
    err = recall.emit_sandbox_preset(pre, "A")
    if err:
        raise BenchError(str(err))
    time.sleep(SETTLE_S)
    os.makedirs(work_dir(), exist_ok=True)
    wav = os.path.join(work_dir(), f"bench-{seq}.wav")
    scene = f"cpu-{seq}"
    with contextlib.suppress(OSError):
        os.remove(C.PREVIEW_FILE)
    cmd = {"action": "preview", "seq": seq, "op": "render", "scene": scene, "di": di, "out": wav, "tail": 0.25,
           "chain": "Sandbox #Input " + str(in_key), "tree": True, "settle": CLONE_SETTLE_S, "bench": RUNS,
           "_route": "preview"}
    if machine.get("srate"):
        cmd["sr"] = int(machine["srate"])
    try:
        write_command(cmd)
        got = _poll(scene, POLL_TIMEOUT_S)
    finally:
        with contextlib.suppress(OSError):
            os.remove(wav)
    if (recall._LAST_EMIT.get("pid") or "") != pre["id"]:
        raise Interrupted("the rig was recalled during the measure")
    if not got:
        raise Interrupted("REAPER did not answer the bench render")
    if got.get("error"):
        raise BenchError(f"REAPER: {got['error']}")
    srate = int(got.get("srate") or machine.get("srate") or 0) or None
    bsize = int(got.get("bsize") or machine.get("bsize") or 0) or None
    m = CB.per_buffer(_floats(got.get("times")), _floats(got.get("base")), float(got.get("len") or 0), srate, bsize)
    return dict(m, nfx=int(got.get("nfx") or 0), srate=srate, bsize=bsize)


def _restore_if_ours():
    """Rend le moteur : la sandbox d'avant reposée — seulement si le rig est encore le patch de banc (un rappel au
    pied pendant le banc a déjà posé ce que la personne veut)."""
    from . import recall
    with contextlib.suppress(Exception):
        if str(recall._LAST_EMIT.get("pid") or "").endswith(BENCH_DOC_ID):
            recall.reapply_sandbox()


# ── l'exécution ──────────────────────────────────────────────────────────────────────────────────────────────────
def busy(manual=False):
    """La raison de ne PAS prendre le moteur, ou None. Automatique : la règle du re-amp entière (10 min sans geste).
    Manuel : sans les 10 min — la personne qui appuie est devant l'écran."""
    from . import preview as PV, reamp
    from .state import state
    try:
        from . import engine
        if engine.get().id != "reaper":
            return "the bench runs under REAPER only"
    except Exception:
        pass
    if not getattr(state, "reaper_running", True):
        return "REAPER is not running"
    return reamp.busy_reason(idle=not manual) or ("the demo batch is running" if PV._BATCH.get("running") else None) \
        or ("a demo is rendering" if PV.rendering() else None)


def _record(prof, target, m, machine):
    sys_e = (prof.get("blocks") or {}).get(SYSTEM_KEY)
    avg, worst = m["avg_us"], m["worst_us"]
    if target["key"] != SYSTEM_KEY and sys_e is not None:
        if m.get("nfx", 0) <= int(sys_e.get("nfx") or 0):
            raise BenchError("the plugin did not load in the bench lane")
        avg = max(0.0, avg - float(sys_e.get("avg_us") or 0))
        worst = max(avg, worst - float(sys_e.get("avg_us") or 0))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mach = dict(machine, srate=m.get("srate") or machine.get("srate"), bsize=m.get("bsize") or machine.get("bsize"))
    prof.setdefault("version", 1)
    prof["machine"] = mach
    prof["measured_at"] = now
    prof.setdefault("blocks", {})[target["key"]] = {
        "avg_us": round(avg, 2), "worst_us": round(worst, 2), "at": now, "hash": target["hash"],
        # l'empreinte de la machine telle que le banc la relira (machine_now), pas ce que REAPER a rapporté : sinon une
        # fréquence que reaper.ini ne dit pas rendrait tout « à refaire » pour toujours
        "fp": remeasure_fp(machine), "bsize": mach.get("bsize"), "srate": mach.get("srate"), "nfx": m.get("nfx"),
        "label": target.get("label"), "runs": RUNS}
    (prof.get("failed") or {}).pop(target["key"], None)


def run(manual=False, force=False, types=None, measure=None, busy_fn=None, seq_of=None, restore=None):
    """Le banc, bloquant : une cible à la fois, la règle relue avant chacune, chaque mesure écrite dès qu'elle tombe.
    `measure`/`busy_fn`/`restore` : injectables (tests). Rend l'état final."""
    measure = measure or measure_reaper
    busy_fn = busy_fn or (lambda: busy(manual))
    restore = restore or _restore_if_ours
    seq_of = seq_of or (lambda: next(_seq))
    machine = machine_now()
    prof = load_profile()
    todo = pending(prof, targets(fresh=True), machine, force=force, types=types)
    _stop.clear()
    _ST.update(state="running" if todo else "done", total=len(todo), done=0, current=None, waiting_for=None,
               error=None, running=bool(todo), manual=manual)
    took = False
    try:
        for t in todo:
            why = busy_fn()
            if why or _stop.is_set():
                _ST.update(state="waiting", waiting_for=why or "stopped", current=None)
                return status()
            from . import preview as PV
            if not PV._gen_lock.acquire(blocking=False):
                _ST.update(state="waiting", waiting_for="a demo is rendering", current=None)
                return status()
            if t["key"] != SYSTEM_KEY and SYSTEM_KEY not in (load_profile().get("blocks") or {}):
                PV._gen_lock.release()
                _ST.update(state="failed", error="the empty lane could not be measured", current=None)
                return status()
            _ST["current"] = t["label"]
            try:
                took = True
                m = measure(t, machine, seq_of())
                prof = load_profile()                    # relu : une autre écriture a pu passer entre-temps
                _record(prof, t, m, machine)
                log.info(f"banc CPU : {t['key']} → {prof['blocks'][t['key']]['avg_us']} µs (pire "
                         f"{prof['blocks'][t['key']]['worst_us']})")
            except Interrupted as e:
                _ST.update(state="waiting", waiting_for=str(e), current=None)
                return status()
            except (BenchError, ValueError) as e:
                prof = load_profile()
                prof.setdefault("failed", {})[t["key"]] = {"reason": str(e), "hash": t["hash"],
                                                          "fp": remeasure_fp(machine),
                                                          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                log.warning(f"banc CPU : {t['key']} non mesuré — {e}")
            finally:
                PV._gen_lock.release()
            save_profile(prof)
            _ST["done"] += 1
        _ST.update(state="done", current=None, waiting_for=None)
        return status()
    except Exception as e:                               # le banc ne meurt jamais en silence
        _ST.update(state="failed", error=str(e), current=None)
        log.error(f"banc CPU interrompu : {e}")
        return status()
    finally:
        _ST["running"] = False
        if took:
            restore()


def status():
    """L'objet `calibration` du contrat (§9)."""
    return {"state": _ST["state"], "done": _ST["done"], "total": _ST["total"], "current": _ST["current"],
            "waiting_for": _ST["waiting_for"], "error": _ST["error"]}


def refresh_status(prof=None, machine=None):
    """L'état quand rien ne tourne : « done » si tout est à jour, « waiting » s'il reste à mesurer (avec la raison)."""
    if _ST["running"]:
        return status()
    with contextlib.suppress(Exception):
        prof = load_profile() if prof is None else prof
        machine = machine or machine_now()
        tg = targets()
        todo = pending(prof, tg, machine)
        if not todo and _ST["state"] != "failed":
            _ST.update(state="done", done=len(tg), total=len(tg), waiting_for=None)
        elif todo and _ST["state"] in ("idle", "done", "waiting"):
            _ST.update(state="waiting", total=len(tg), done=len(tg) - len(todo),
                       waiting_for=_ST["waiting_for"] or busy(False) or "the next idle moment")
    return status()


def start_run(manual=True, force=False, types=None):
    """Lance le banc dans un fil. Rend None, ou le texte du refus (déjà en cours, ou le rack est pris)."""
    with _lock:
        if _ST["running"] or (_thread["run"] and _thread["run"].is_alive()):
            return "the calibration is already running"
        why = busy(manual)
        if why:
            return why
        _ST.update(running=True, state="running", waiting_for=None, error=None)
        th = threading.Thread(target=run, kwargs={"manual": manual, "force": force, "types": types},
                              daemon=True, name="cpu-bench")
        _thread["run"] = th
        th.start()
    return None


def idle_tick():
    """Un pas du veilleur : lance le banc si quelque chose attend et que le rack est libre. Rend la raison d'attendre."""
    if _ST["running"]:
        return "running"
    prof, machine = load_profile(), machine_now()
    try:
        todo = pending(prof, targets(), machine)
    except Exception as e:
        log.warning(f"banc CPU : {e}")
        return "error"
    if not todo:
        refresh_status(prof, machine)
        return "nothing to measure"
    why = busy(False)
    if why:
        _ST.update(state="waiting", waiting_for=why)
        return why
    with _lock:                                          # un appui sur Calibrate a pu partir entre-temps
        if _ST["running"]:
            return "running"
        _ST["running"] = True
    run(manual=False)
    return None


def start_idle():
    """Le veilleur, démarré avec le bridge. GOLEM_CPU_BENCH=0 le coupe (un banc, la CI)."""
    if os.environ.get("GOLEM_CPU_BENCH", "1") == "0" or (_thread["idle"] and _thread["idle"].is_alive()):
        return

    def loop():
        time.sleep(30.0)                                  # le temps que le rack se lève
        while True:
            try:
                why = idle_tick()
            except Exception as e:                       # le veilleur ne meurt jamais
                log.error(f"banc CPU au repos : {e}")
                why = "error"
            time.sleep(IDLE_EVERY_S if why else 5.0)
    th = threading.Thread(target=loop, daemon=True, name="cpu-bench-idle")
    _thread["idle"] = th
    th.start()


def fact():
    """La ligne de Health / golem doctor : l'âge du profil et s'il reste à mesurer (§10). (level, text)."""
    # aucune sonde ici (ni moteur, ni machine, ni catalogue) : Health l'appelle souvent, et une sonde qui attend un
    # moteur muet gelait la page. L'état vient du veilleur (idle_tick le tient à jour), le reste du profil sur disque.
    prof = load_profile()
    st = status()
    if not prof.get("blocks"):
        return "wait", ("not calibrated yet — golem measures each block when the rack is idle"
                        + (f" ({st['waiting_for']})" if st.get("waiting_for") else ""))
    n = len(prof.get("blocks") or {}) - (1 if SYSTEM_KEY in (prof.get("blocks") or {}) else 0)
    at = prof.get("measured_at") or "?"
    if st["state"] == "running":
        return "wait", f"calibrating: {st['done']}/{st['total']} ({st.get('current') or '…'})"
    if st["state"] in ("waiting",) and st.get("total"):
        left = st["total"] - st["done"]
        return "wait", f"{n} blocks measured {at[:10]} · {left} to measure ({st.get('waiting_for') or 'when idle'})"
    if st["state"] == "failed":
        return "warn", f"{n} blocks measured {at[:10]} · the last calibration stopped: {st.get('error')}"
    return "ok", f"{n} blocks measured {at[:10]} on this machine"
