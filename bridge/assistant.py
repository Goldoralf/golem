# SPDX-License-Identifier: GPL-3.0-or-later
"""« ASK GOLEM » — L'ASSISTANT, RÉPONDU PAR golem.fm (docs/assistant.md §5–§8, maquette mockups/health-fix.html écran 4).

Le rack pose la question, golem.fm répond, LA MACHINE DÉCIDE. Une question part vers `POST /api/ext/assistant/ask`
(jeton d'appairage, scope `assistant:ask`) avec : la question et les tours précédents, les faits de Health (texte
passé au scrubber des rapports : ni preset, ni chanson, ni personne), les verdicts (incidents ouverts, dernière
chasse au silence, premier check), le REGISTRE d'actions de cette machine (bridge/fixes.py — la machine reste la
seule source de ce qu'elle sait faire), un contexte bridé (rôles des entrées, TYPES de blocs, buffer, OS), et la
garde du moment (`busy`). golem.fm rend {answer, cites, propose?} ; la proposition est REVALIDÉE ici contre le
registre et la garde avant d'être montrée — un tap ouvre ensuite la même feuille que « Fix… ».

Rien ne part sans le consentement donné une fois (config/.assistant.json, local), retirable depuis le tiroir.
golem.fm ne garde aucun texte (une ligne de consommation) ; le consentement le dit, et dit que la question passe par
le fournisseur d'IA de golem.fm. Absent quand le rack n'est pas appairé, ou quand le mode coupe le service
`assistant` (docs/modes.md §3.1 — absent du mode = permis)."""
import contextlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("assistant")
PATH = lambda: os.path.join(C.CONFIG_DIR, ".assistant.json")   # noqa: E731 — le dossier de config du MOMENT
ASK_PATH = "/api/ext/assistant/ask"
TIMEOUT_S = 90                    # golem.fm attend son fournisseur jusqu'à 180 s ; au-delà de 90 s, on le dit ici
MAX_Q, MAX_HISTORY, MAX_TURN = 2000, 20, 2000
MAX_CITES = 4
CITE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")   # les ids de l'aide de golem.fm : <section>/<page>


# ── le consentement ────────────────────────────────────────────────────────────────────────────────────────────────
def _read():
    try:
        with open(PATH(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def consent(on):
    from .store import _write_json_atomic
    d = _read()
    if on:
        d["consent_at"] = round(time.time(), 3)
    else:
        d.pop("consent_at", None)
        d["revoked_at"] = round(time.time(), 3)
    os.makedirs(os.path.dirname(PATH()), exist_ok=True)
    _write_json_atomic(PATH(), d)
    return status()


def status():
    """Le panneau existe-t-il ici, et pourquoi pas : {available, why, consent}. `why` est une phrase pour l'écran."""
    from .golemfm import _cfg
    base, token = _cfg()
    why = None
    if not base or not token:
        why = "pair this golem with golem.fm to ask questions"
    else:
        with contextlib.suppress(Exception):
            from .state import state
            mode = state.mode or {}
            if (mode.get("services") or {}).get("assistant") is False:
                why = f"off in {mode.get('name') or mode.get('id') or 'this'} mode"
    return {"available": why is None, "why": why, "consent": bool(_read().get("consent_at"))}


# ── ce qui part : une liste blanche, construite champ par champ (docs/assistant.md §6) ──────────────────────────
def _scrub(s):
    with contextlib.suppress(Exception):
        from . import diag
        return diag.scrub(str(s or ""))[:300]
    return ""


def _busy():
    with contextlib.suppress(Exception):
        from . import reamp
        return reamp.busy_reason(idle=False)
    return None


def payload(question, history=None):
    """La requête entière. Les faits sont scrubbés (le preset joué devient « <preset> ») ; le contexte ne porte que
    des TYPES et des rôles ; rien d'autre n'entre — un champ ajouté demain à Health n'y est pas."""
    from . import fixes, health, incidents
    from .state import state as st
    doc = health.facts() or {}
    facts = [{"id": f.get("id"), "name": f.get("name"), "level": f.get("level"), "text": _scrub(f.get("text")),
              **({"repair": (f.get("repair") or {}).get("action")} if f.get("repair") else {})}
             for f in doc.get("facts") or []]
    v = doc.get("verdict") or {}
    verdicts = {"health": {"level": v.get("level"), "counts": v.get("counts")},
                "incidents_open": [{"kind": i.get("kind"), "code": i.get("code"), "title": i.get("title"), "state": i.get("state")}
                                   for i in incidents.items(10) if i.get("state") != "closed"]}
    with contextlib.suppress(Exception):
        from . import silence
        s = silence.status() or {}
        rep = s.get("report") or {}
        if s.get("phase") == "done" and rep.get("verdict") and time.time() - float(s.get("at") or 0) < 1800:
            verdicts["silence"] = {k: rep["verdict"].get(k) for k in ("code", "level", "stage")}
    with contextlib.suppress(Exception):
        from . import first_check
        verdicts["first_check"] = first_check.section()
    ctx = {"os": {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")}
    with contextlib.suppress(Exception):
        from . import rigstatus
        ctx["golem"] = rigstatus.golem_version()
        eng = rigstatus.engine_doc() or {}
        ctx["audio"] = {"samplerate": eng.get("samplerate"), "buffer": eng.get("bsize"), "latency_ms": st.latency_ms}
    with contextlib.suppress(Exception):
        ins = (st.inputmap or {}).get("inputs") or []
        ctx["inputs"] = [{"ch": str(i.get("ch")), "role": i.get("role")} for i in ins if isinstance(i, dict)]
    with contextlib.suppress(Exception):
        from . import diag
        p = diag._section_preset(st) or {}
        ctx["preset"] = {"blocks": [b["type"] for b in p.get("blocks") or []], "lanes": (p.get("lanes") or {}).get("roles"),
                         "scene": p.get("scene")}
    with contextlib.suppress(Exception):
        m = st.mode or {}
        ctx["mode"] = {"id": m.get("id"), "locked": bool((m.get("ui") or {}).get("locked"))}
    hist = []
    for t in (history or [])[-MAX_HISTORY:]:
        if isinstance(t, dict):
            hist.append({"q": str(t.get("q") or "")[:MAX_TURN], "a": str(t.get("a") or "")[:MAX_TURN],
                         **({"action": t["action"], "result": str(t.get("result") or "")[:200]} if t.get("action") else {})})
    actions = [{k: a[k] for k in ("name", "label", "description", "risk", "params", "live_allowed", "help")}
               for a in fixes.registry()]
    return {"question": str(question)[:MAX_Q], "history": hist, "facts": facts, "verdicts": verdicts,
            # la LANGUE DE LA QUESTION (2026-10-20) : le musicien qui demande en français est répondu en français.
            # Pas de détection ici (peu fiable sur « ça grésille », bornée à quelques langues) : « auto » demande à
            # golem.fm de répondre dans la langue de la question, en anglais si elle est ambiguë. Les libellés de
            # l'écran (boutons, feuille « Fix ») restent en anglais : ce sont l'interface, pas la conversation.
            "actions": actions, "context": ctx, "busy": _busy(), "lang": "auto"}


# ── l'appel, et la réponse revalidée ───────────────────────────────────────────────────────────────────────────────
def _post(body):
    """(status, dict) — le corps est GARDÉ (le code `ai_quota`, `retry_after`), jamais d'exception."""
    from .golemfm import _cfg
    base, token = _cfg()
    if not base or not token:
        return 0, {"detail": {"error": "not_paired", "message": "This golem is not paired with golem.fm."}}
    req = urllib.request.Request(base + ASK_PATH, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except Exception as e:
        _swallowed(e)
        return 0, {"detail": {"error": "unreachable", "message": "golem.fm did not answer. Check the network, then ask again."}}


def _refusal(code, body):
    """Un refus, dit pour le panneau : {error, message, retry_after?}. Le 403 du scope est une CHAÎNE chez golem.fm
    (pas un objet) — décision du 2026-10-20 : on réappaire, on ne migre pas les jetons."""
    from .golemfm import error_text
    d = (body or {}).get("detail") if isinstance(body, dict) else None
    err = d.get("error") if isinstance(d, dict) else None
    if code == 403 and "assistant:ask" in str(d or ""):
        return {"error": "repair", "message": "This golem was paired before the assistant existed. Pair it again "
                                              "(Settings ▸ Connect ▸ golem.fm) to ask questions."}
    msg = (d.get("message") if isinstance(d, dict) else None) or error_text(body, "") or "golem.fm refused the question."
    out = {"error": err or (f"http_{code}" if code else "unreachable"), "message": msg}
    if isinstance(d, dict):
        for k in ("retry_after", "used", "limit"):
            if d.get(k) is not None:
                out[k] = d[k]
    return out


def check_answer(body, busy):
    """La réponse de golem.fm, relue comme une entrée inconnue : un texte borné, des ids d'aide au format attendu,
    et AU PLUS une proposition qui passe le registre, son schéma et la garde du moment — sinon elle tombe (et on dit
    pourquoi). golem.fm valide aussi ; la machine ne s'en remet pas à lui."""
    from . import fixes
    answer = str((body or {}).get("answer") or "").strip()[:4000]
    cites = [c for c in (body or {}).get("cites") or [] if isinstance(c, str) and CITE_RE.match(c)][:MAX_CITES]
    out = {"answer": answer or "golem.fm gave no answer.", "cites": cites}
    p = (body or {}).get("propose")
    if isinstance(p, dict) and p.get("action"):
        name, params = str(p["action"]), p.get("params") if isinstance(p.get("params"), dict) else {}
        ok_params, err = fixes.validate(name, params)
        risk = (fixes.ACTIONS.get(name) or {}).get("risk")
        if err:
            out["dropped"] = f"golem.fm proposed something this golem cannot do ({err})"
        elif busy and risk != "read":
            out["dropped"] = f"golem.fm proposed a change, but not while {busy}"
        else:
            out["propose"] = {"action": name, "params": ok_params, "why": str(p.get("why") or "")[:300],
                              "label": fixes.label_for(name, ok_params), "blocked": fixes.blocked(name)}
    return out


def _event(**fields):
    with contextlib.suppress(Exception):
        from . import diag
        diag.event("assist", **fields)


def ask(question, history=None):
    """Une question, une réponse. Rend {ok: True, answer, cites, propose?, dropped?} ou {ok: False, error, message…}."""
    q = str(question or "").strip()
    if not q:
        return {"ok": False, "error": "empty", "message": "Ask something first."}
    st = status()
    if not st["available"]:
        return {"ok": False, "error": "unavailable", "message": st["why"]}
    if not st["consent"]:
        return {"ok": False, "error": "consent", "message": "Allow the question to be sent first."}
    body = payload(q, history)
    t0 = time.time()
    code, resp = _post(body)
    ms = int((time.time() - t0) * 1000)
    if code != 200:
        r = _refusal(code, resp)
        _event(ok=False, error=r["error"], ms=ms)
        log.info(f"assistant : refus {code} {r['error']}")
        return {"ok": False, **r}
    out = check_answer(resp, body["busy"])
    _event(ok=True, cites=out["cites"], proposed=(out.get("propose") or {}).get("action"), dropped=bool(out.get("dropped")), ms=ms)
    return {"ok": True, **out}
