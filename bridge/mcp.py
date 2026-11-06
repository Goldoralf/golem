# SPDX-License-Identifier: GPL-3.0-or-later
"""Serveur MCP du rack — LECTURE SEULE (demande golem.fm du 2026-09-12, contrat docs/rack-mcp.md).

Pourquoi il existe : golem.fm DÉDUISAIT l'état de cette machine au lieu de le lui demander — en
lisant notre code source pour connaître une RÈGLE (`resolver._resolve`, `scene_bake`), puis sa
propre base pour deviner un ÉTAT. Ça marche jusqu'au jour où ça ne marche plus, et ça ne prévient
pas : le 2026-09-11, l'artefact qui disait « l'ampli est vide » (`presets/.rig-check.json`) est
resté chez nous pendant qu'une soirée passait à le reconstruire de l'autre côté.

── La frontière, et elle ne bouge pas ────────────────────────────────────────────────────────
  LIRE passe par ici. ÉCRIRE passe par la FILE DE JOBS, jamais par ce serveur.
La file est ordonnée, acquittée, auditable : un `patch-try` laisse une trace, une raison de refus
et un `unresolved[]`. Un appel MCP qui monterait un preset ouvrirait un SECOND chemin pour changer
la machine, sans ordre garanti ni historique — et le soir où quelque chose sonne mal, plus
personne ne saurait par où c'est arrivé. Aucun outil de ce fichier n'écrit quoi que ce soit.

── Ce que ce serveur N'EST PAS ───────────────────────────────────────────────────────────────
Un canal de production. Un rack vit derrière la box de son propriétaire : il n'est pas joignable
depuis le nuage, et ça ne changera pas (docs/identity.md — c'est le rack qui pousse). Ce serveur
sert le DÉVELOPPEMENT et le DIAGNOSTIC, là où les deux moitiés tournent sur la même machine, ou
sur un LAN partagé. D'où l'auth : localhost passe, le distant présente un jeton d'appareil
(bridge/auth.py) — et comme tout est en lecture, un jeton volé ne peut rien casser.

── Transport ────────────────────────────────────────────────────────────────────────────────
JSON-RPC 2.0 sur POST /mcp (MCP « streamable HTTP », protocole 2025-06-18), écrit à la main :
le SDK `mcp` ajouterait une dépendance et son arbre à un rack qui doit démarrer sans réseau, pour
trois méthodes (`initialize`, `tools/list`, `tools/call`). Les batchs n'existent plus dans cette
révision du protocole : un objet par requête. Une notification (pas d'`id`) ne répond rien.
"""
import json
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import auth as auth_mod
from . import config as C

router = APIRouter()

PROTOCOL = "2025-06-18"
SERVER_INFO = {"name": "golem-rack", "title": "GoleM rack (read-only)", "version": "1.0.0"}

# Codes JSON-RPC (spec 2.0)
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603


# ── les outils : une lecture = une question que golem.fm s'est posée sans pouvoir y répondre ──

def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def t_rig_check(args):
    """LA priorité de leur demande : l'artefact qui dit si les fichiers attendus sont VRAIMENT
    chargés dans les plugins (golem_rig relit en clair « Neural Model » / « Impulse Response »).

    `history` : les dernières passes ANORMALES, horodatées. Sans elle, l'artefact le plus précieux
    du rack était le plus fugace — `.rig-check.json` ne garde que la dernière passe, et les quatre
    anomalies « expected %MODEL% » du 2026-09-11 avaient déjà été effacées par la compilation
    suivante quand on est venu les lire (question golem.fm, 2026-09-12)."""
    d = _read_json(os.path.join(C.PRESETS_DIR, ".rig-check.json"))
    hist = _read_json(os.path.join(C.PRESETS_DIR, ".rig-check.history.json"), []) or []
    n = (args or {}).get("history")
    hist = hist[-n:] if isinstance(n, int) and n > 0 else hist
    if d is None:
        return {"present": False, "history": hist,
                "why": "no rig check yet — it is written a couple of seconds after each recall"}
    return {"present": True, **d, "history": hist}


def t_resolve(args):
    """Essai à blanc d'une `ref` de capture : rien n'est monté, rien ne joue. C'est la question
    derrière la panne du 2026-09-11 — `t3k:44209` contre `44209` se serait vu en une seconde."""
    ref = (args or {}).get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("ref (string) is required")
    model = (args or {}).get("model")
    from .resolver import _components, _resolve
    path = _resolve(ref.strip(), _components(), model)
    if not path:
        return {"found": False, "ref": ref,
                "why": "unknown tone or component on this rack — nothing named %r is installed" % ref}
    rel = C.rel(path)
    exists = os.path.exists(path)
    # `type` : le bloc qui la portera. Une ref peut RÉSOUDRE et rester inutilisable — « Titan »
    # (2026-09-12) nommait une capture amp-cab au format NAM sur un bloc `cab`, le convolver n'a
    # rien chargé et la lane s'est tue. Vérifier qu'une ref existe ne dit rien sur son CONTENU.
    from .rig import _wrong_kind
    btype = (args or {}).get("type")
    bad = _wrong_kind({"type": btype}, path) if btype else None
    out = {"found": True, "ref": ref, "model": model, "file": rel, "exists": exists,
           "why": None if exists else "catalog entry found but the file is missing on disk"}
    if btype:
        out["usable_as"] = btype if not bad else False
        if bad:
            out["why"] = bad + " — the rack will leave this block out of the rig"
    return out


def t_captures(args):
    """Ce qui est INSTALLÉ, à la seconde — pas la photo du heartbeat, vieille de cinq minutes."""
    from . import rigstatus
    limit = (args or {}).get("limit")
    caps = rigstatus.captures(limit) if isinstance(limit, int) and limit > 0 else rigstatus.captures()
    return {"count": len(caps), "captures": caps}


def t_jobs_log(_args):
    """Notre côté de la file : ce que la boucle a fait des jobs, là où ils ne voient que
    « pending » jusqu'à l'acquittement."""
    from . import tones_jobs
    return tones_jobs.status()


def t_patch(args):
    """Ce que le rack DÉTIENT vraiment — pour comparer à ce qui a été envoyé. Sans `id` : la liste."""
    from . import patches as P
    pid = (args or {}).get("id")
    if not pid:
        return {"patches": P.list_patches()}
    p = P.get_patch(str(pid))
    if p is None:
        return {"found": False, "id": pid}
    return {"found": True, "patch": p}


def t_preset_export(args):
    """L'enveloppe d'export d'un preset du rack, `deps[]` et `unresolved[]` compris."""
    pid = (args or {}).get("id")
    if not pid:
        raise ValueError("id (string) is required")
    from . import preset_export
    try:
        return preset_export.build_export(str(pid)) or {"found": False, "id": pid}
    except FileNotFoundError:
        return {"found": False, "id": pid}


def t_rig_status(_args):
    """Mode, verrou, prise en cours — de quoi griser un bouton. FILTRÉ : ni roster, ni prénoms,
    ni identifiant d'espace. Le mode dit ce qu'il AUTORISE, pas pour qui (docs/identity.md)."""
    from .state import state
    mode = state.mode or {}
    return {
        "mode": {"id": mode.get("id"), "name": mode.get("name"),
                 "locked": bool((mode.get("ui") or {}).get("locked")),
                 "services": mode.get("services") or {}},
        "recording": bool((state.perf or {}).get("recording")),
        "preset": {"id": state.preset_id, "name": state.preset_name, "scene": state.scene_id},
        "engine": {"running": bool(state.reaper_running), "linked": bool(state.reaper_connected)},
        "audio": state.audio, "midi": {"ok": (state.midi or {}).get("ok"),
                                       "issues": (state.midi or {}).get("issues") or []},
        "card": (state.inputmap or {}).get("card"),
        "t": int(time.time()),
    }


def t_diag_report(args):
    """Le dernier paquet de diagnostic (lot 8) : `report.json` en clair + la queue de la chronologie.
    Lecture seule, déjà scrubbé — pour l'agent qui débugue à côté du rack sans ouvrir un zip."""
    import zipfile
    from . import diag
    rows = diag.index()
    if not rows:
        return {"reports": [], "hint": "no report built yet — POST /api/diag/build"}
    last = rows[-1]
    p = diag.report_path(last.get("report_id"))
    out = {"index": last, "reports": len(rows)}
    if p:
        with zipfile.ZipFile(p) as z:
            out["report"] = json.loads(z.read("report.json"))
            tl = z.read("timeline.ndjson").decode("utf-8").splitlines()
            n = int(args.get("tail") or 50)
            out["timeline_tail"] = [json.loads(x) for x in tl[-n:] if x.strip()]
    return out


TOOLS = [
    {"name": "diag_report", "title": "The last diagnostic package",
     "description": "report.json of the most recent package built by the rack (whitelisted, scrubbed) "
                    "and the tail of its event timeline. Never carries names, people or credentials.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"tail": {"type": "integer", "minimum": 1, "description": "timeline lines to return"}}},
     "handler": t_diag_report},
    {"name": "rig_check", "title": "Files really loaded in the plugins",
     "description": "The rack's own verdict on NAM/IR files: what each block was supposed to load "
                    "and what the plugin actually reports. Empty issues = every file is in. "
                    "`history` keeps the last 20 ABNORMAL passes — the current one is overwritten "
                    "by the next compile, the history is not.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"history": {"type": "integer", "minimum": 1,
                                                "description": "keep only the N most recent abnormal passes"}}},
     "handler": t_rig_check},
    {"name": "resolve", "title": "Would this capture ref resolve?",
     "description": "Dry run of a block's `ref` (+ optional `model`) against this rack's catalog. "
                    "Mounts nothing, plays nothing. Accepts both the catalog id (\"44209\") and the "
                    "pack uid (\"t3k:44209\").",
     "inputSchema": {"type": "object", "required": ["ref"], "additionalProperties": False,
                     "properties": {"ref": {"type": "string", "description": "block ref, e.g. 44209 or t3k:44209"},
                                    "model": {"description": "pinned model id inside the pack (optional)"},
                                    "type": {"type": "string", "description": "block type that will carry it "
                                             "(amp-nam, cab, pedal-nam, preamp-nam, comp-nam) — checks the file SUITS it, not just that it exists"}}},
     "handler": t_resolve},
    {"name": "captures", "title": "Captures installed right now",
     "description": "Every tone of the local catalog with at least one file on disk. This is the "
                    "data that decides whether a patch will sound.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"limit": {"type": "integer", "minimum": 1}}},
     "handler": t_captures},
    {"name": "jobs_log", "title": "The rack's side of the job queue",
     "description": "What the worker did with the pulled jobs: last result, counters, recent log.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "handler": t_jobs_log},
    {"name": "patch", "title": "A patch the rack holds",
     "description": "The stored document, to compare with what was pushed. Without `id`: the list.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"id": {"type": "string"}}},
     "handler": t_patch},
    {"name": "preset_export", "title": "A preset as the rack would export it",
     "description": "Export envelope of a stored preset, with deps[] and unresolved[].",
     "inputSchema": {"type": "object", "required": ["id"], "additionalProperties": False,
                     "properties": {"id": {"type": "string"}}},
     "handler": t_preset_export},
    {"name": "rig_status", "title": "Mode, lock, take in progress",
     "description": "Enough to grey out a button. Never carries roster, people or space id.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "handler": t_rig_status},
]
BY_NAME = {t["name"]: t for t in TOOLS}


def _public(tool):
    return {k: v for k, v in tool.items() if k != "handler"}


# ── JSON-RPC ─────────────────────────────────────────────────────────────────────────────────

def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message, data=None):
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rid, "error": e}


def _call_tool(params):
    name = (params or {}).get("name")
    tool = BY_NAME.get(name)
    if tool is None:
        raise LookupError(f"unknown tool: {name!r}")
    args = (params or {}).get("arguments") or {}
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    data = tool["handler"](args)
    # `content` pour les clients qui lisent du texte, `structuredContent` pour ceux qui lisent
    # des objets : la spec 2025-06-18 demande les deux quand on rend du structuré.
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
            "structuredContent": data, "isError": False}


def _dispatch(msg):
    """Rend la réponse JSON-RPC, ou None pour une notification (rien à renvoyer)."""
    rid = msg.get("id")
    method = msg.get("method")
    if not isinstance(method, str):
        return _err(rid, INVALID_REQUEST, "method is required")
    if method.startswith("notifications/"):
        return None                                    # initialized, cancelled… : rien à dire
    if method == "initialize":
        return _ok(rid, {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": SERVER_INFO,
                         "instructions": "Read-only view of a GoleM rack. Writing goes through the "
                                         "job queue (patch-try, patch-install, install…), never here."})
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(rid, {"tools": [_public(t) for t in TOOLS]})
    if method == "tools/call":
        try:
            return _ok(rid, _call_tool(msg.get("params")))
        except LookupError as e:
            return _err(rid, METHOD_NOT_FOUND, str(e))
        except ValueError as e:
            return _err(rid, INVALID_PARAMS, str(e))
        except Exception as e:                          # un outil qui casse ne tue pas la session
            return _err(rid, INTERNAL, f"{type(e).__name__}: {e}")
    return _err(rid, METHOD_NOT_FOUND, f"unknown method: {method!r}")


ADMIN_TOOLS = ("diag_report",)


@router.post("/mcp")
async def mcp_post(request: Request):
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse(_err(None, PARSE_ERROR, "invalid JSON"), status_code=400)
    if not isinstance(msg, dict):
        # les batchs ont été RETIRÉS du protocole en 2025-06-18 : on le dit plutôt que de deviner.
        return JSONResponse(_err(None, INVALID_REQUEST, "one request object per call (batches were "
                                                        "removed in protocol 2025-06-18)"), status_code=400)
    # audit 2026-10-15 : le paquet de diagnostic est une donnée ADMIN (/api/diag est un GET sensible) — ici il
    # sortait vers tout appareil appairé
    if (msg.get("method") == "tools/call" and ((msg.get("params") or {}).get("name") in ADMIN_TOOLS)
            and not auth_mod.request_is_admin(request)):
        return JSONResponse(_err(msg.get("id"), INVALID_PARAMS, "this tool needs the rack's main device"))
    out = _dispatch(msg)
    if out is None:
        return Response(status_code=202)               # notification : accusé vide
    return JSONResponse(out)


@router.get("/mcp")
def mcp_get():
    """Pas de canal SSE : ce serveur ne pousse rien, il répond. Un GET dit quoi faire à la place —
    plutôt qu'un 405 sec qui laisse croire à une panne."""
    return JSONResponse({"server": SERVER_INFO, "protocolVersion": PROTOCOL,
                         "transport": "POST /mcp (JSON-RPC 2.0) — no server-initiated stream",
                         "tools": [t["name"] for t in TOOLS],
                         "writes": "never — use the job queue"}, status_code=200)
