# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes du BUDGET CPU (docs/cpu-budget.md §9) : le profil mesuré, l'estimation d'un preset, d'une liste de presets,
d'un échange de capture, le coût d'un bloc, et le banc à la main. Toutes en lecture sauf `calibrate`.

Auth (bridge/auth.py) : `/api/cpu/` est dans SENSITIVE_GET_PREFIX — une estimation dit ce que contient un preset
(blocs, captures), comme /api/preset ; le Companion appairé passe. `POST /api/cpu/calibrate` est ADMIN_WRITES : le
moteur est pris dix minutes."""
import asyncio
import copy

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import cpu_bench as CBN
from . import cpu_budget as CB

router = APIRouter()


def _load(pid):
    """Le preset demandé : `sandbox` (ce que le Designer édite), `patch:<id>`, ou un preset par id."""
    from . import recall, store
    pid = str(pid or "").strip()
    if not pid or pid == "sandbox":
        sb = store._read_json(recall.SANDBOX_BUF, {}) or {}
        return sb.get("preset") if isinstance(sb.get("preset"), dict) else None
    if pid.startswith("patch:"):
        from . import patches as P
        doc = P.get_patch(pid[len("patch:"):])
        if doc:
            return P.as_preset(doc)
    return store.load_preset(pid)


def _bsizes():
    try:
        from .routes_system import AUDIO_BSIZES
        return tuple(AUDIO_BSIZES)
    except Exception:
        return (64, 96, 128, 192, 256, 384, 512)


def estimate_preset(preset, machine=None, profile=None):
    """L'estimation complète d'un preset (dict) — partagée par les routes et les tests."""
    machine = machine or CBN.machine_now()
    profile = CBN.usable_profile(profile, machine)
    plans = CB.scene_plans(preset)
    return CB.estimate(plans, profile, machine, CB.lighter_alternatives(plans), _bsizes())


def _with_pct(prof):
    budget = CB.budget_us((prof.get("machine") or {}).get("bsize"), (prof.get("machine") or {}).get("srate"))
    out = {}
    for k, e in (prof.get("blocks") or {}).items():
        if k == CBN.SYSTEM_KEY:
            continue
        us = CB.entry_us(e, (prof.get("machine") or {}).get("bsize"))
        out[k] = {"avg_us": e.get("avg_us"), "worst_us": e.get("worst_us"),
                  "pct": round(us / budget * 100.0, 1) if budget else None, "at": e.get("at"), "hash": e.get("hash")}
    return out


@router.get("/api/cpu/profile")
def cpu_profile():
    prof = CBN.load_profile()
    m = prof.get("machine") or {}
    return {"machine": {k: m.get(k) for k in ("cpu", "cores", "governor", "srate", "bsize", "engine")},
            "measured_at": prof.get("measured_at"), "budget_us": CB._r(CB.budget_us(m.get("bsize"), m.get("srate"))),
            "blocks": _with_pct(prof), "calibration": CBN.refresh_status(prof)}


@router.post("/api/cpu/calibrate")
def cpu_calibrate(body: dict = None):
    body = body or {}
    types = body.get("types")
    if types is not None and not (isinstance(types, list) and all(isinstance(t, str) for t in types)):
        return JSONResponse({"error": "types must be a list of block types"}, 400)
    why = CBN.start_run(manual=True, force=bool(body.get("force")), types=types or None)
    if why:
        return JSONResponse({"error": f"The calibration cannot start now: {why}.", "calibration": CBN.status()}, 409)
    return {"ok": True, "calibration": CBN.status()}


@router.get("/api/cpu/estimate")
async def cpu_estimate(preset: str = "sandbox"):
    p = _load(preset)
    if p is None:
        return JSONResponse({"error": f"unknown preset '{preset}'" if preset != "sandbox" else "no preset loaded"}, 404)
    try:
        return await asyncio.get_running_loop().run_in_executor(None, estimate_preset, p)
    except Exception as e:
        return JSONResponse({"error": f"This preset cannot be estimated: {e}"}, 422)


def _many(ids):
    machine = CBN.machine_now()
    prof = CBN.usable_profile(None, machine)
    out = {}
    for pid in ids:
        p = _load(pid)
        if p is None:
            out[pid] = {"verdict": "unknown", "worst": {"lane": None, "scene": None, "pct": None}, "error": "unknown preset"}
            continue
        try:
            out[pid] = CB.summary(estimate_preset(p, machine, prof))
        except Exception as e:
            out[pid] = {"verdict": "unknown", "worst": {"lane": None, "scene": None, "pct": None}, "error": str(e)}
    return out


@router.get("/api/cpu/estimate-many")
async def cpu_estimate_many(ids: str = ""):
    wanted = [i.strip() for i in ids.split(",") if i.strip()][:64]
    return await asyncio.get_running_loop().run_in_executor(None, _many, wanted)


def _swap(preset, block, ref, model):
    """La lane du bloc avant/après avoir remplacé sa capture par (ref, model)."""
    before = estimate_preset(preset)
    lane = next((ln for ln in before["lanes"] if any(b["id"] == block for b in ln["blocks"])), None)
    if lane is None:
        return None
    work = copy.deepcopy(preset)
    for b in CB._walk_ids(work, block):
        b["ref"] = ref
        if model not in (None, ""):
            b["model"] = int(model) if str(model).isdigit() else model
        else:
            b.pop("model", None)
    after = estimate_preset(work)
    lane_after = next((ln for ln in after["lanes"] if ln["id"] == lane["id"]), None) or {}
    lighter = next((f for f in after["fixes"] if f["id"] == f"lighter-capture:{lane['id']}:{block}"), None)
    lt = None
    if lighter:
        a = lighter["action"]
        pct = (lane_after.get("pct") or 0) - (lighter.get("gain_pct") or 0)
        lt = {"ref": a.get("ref"), "model": a.get("model"), "pct": CB._r(pct)}
    pa = lane_after.get("pct")
    v = lane_after.get("verdict") or CB._verdict_of(pa)
    return {"lane": lane["id"], "before_pct": lane.get("pct"), "after_pct": pa, "verdict_after": v, "lighter": lt}


@router.get("/api/cpu/swap")
async def cpu_swap(preset: str = "sandbox", block: str = "", ref: str = "", model: str = ""):
    if not block or not ref:
        return JSONResponse({"error": "block and ref are required"}, 400)
    p = _load(preset)
    if p is None:
        return JSONResponse({"error": f"unknown preset '{preset}'"}, 404)
    try:
        r = await asyncio.get_running_loop().run_in_executor(None, _swap, p, block, ref, model)
    except Exception as e:
        return JSONResponse({"error": f"This swap cannot be estimated: {e}"}, 422)
    if r is None:
        return JSONResponse({"error": f"no block '{block}' in this preset"}, 404)
    return r


def block_cost(btype, variant="", stereo=True, profile=None, machine=None):
    """{pct, avg_us, worst_us, measured} d'un bloc seul, au buffer d'aujourd'hui."""
    machine = machine or CBN.machine_now()
    prof = CBN.usable_profile(profile, machine)
    v = str(variant or "")
    kind = btype
    if btype in CB.NAM_TYPES or btype == "nam" or v.startswith("nam:"):
        kind, v = "nam", v[4:] if v.startswith("nam:") else v
    e = CB.lookup(prof, kind, v or None, stereo)
    bsize = machine.get("bsize") or (prof.get("machine") or {}).get("bsize")
    srate = machine.get("srate") or (prof.get("machine") or {}).get("srate")
    budget = CB.budget_us(bsize, srate)
    if e is None or not budget:
        return {"pct": None, "avg_us": None, "worst_us": None, "measured": False}
    us = CB.entry_us(e, bsize)
    return {"pct": CB._r(us / budget * 100.0), "avg_us": e.get("avg_us"), "worst_us": e.get("worst_us"), "measured": True}


@router.get("/api/cpu/block")
def cpu_block(type: str = "", variant: str = "", stereo: str = "true"):
    if not type:
        return JSONResponse({"error": "type is required"}, 400)
    return block_cost(type, variant, str(stereo).lower() not in ("0", "false", "no", "mono"))


@router.get("/api/cpu/cores")
async def cpu_cores():
    """System ▸ System ▸ CPU cores : la charge mesurée de chaque cœur, la part du moteur audio dedans et, sous le Golem
    Engine, le coût de chaque lane (bridge/cpu_cores.py). Lecture seule — la remise à zéro des compteurs du moteur est
    celle de sa sonde, sans effet sur le son."""
    from . import cpu_cores as CC
    return await asyncio.get_running_loop().run_in_executor(None, CC.snapshot)
