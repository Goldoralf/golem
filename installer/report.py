# SPDX-License-Identifier: GPL-3.0-or-later
"""LE RAPPORT D'INSTALLATION (docs/diagnostics.md §7.1, lot D2, 2026-10-27) : un échec d'installation qui part chez
golem.fm SUR UN CLIC, jamais tout seul — personne n'a encore coché de case, le rack n'est pas appairé.

Même forme que les paquets du rack (§2.1), `kind` = install | uninstall :
  golem-report.json   le manifeste {golem_report: 2, kind, report_id, created_at, files{nom: sha256}, truncated, missing[]}
  report.json         report, platform, golem {version, target_version, installer, dry}, install {…}, checks[]
  logs/install.log    la trace de l'installateur, scrubbée, le dernier Mo
Le scrubber est bridge/scrub.py, chargé par son chemin (bibliothèque standard ; le bridge ne tourne pas). Bibliothèque
standard ici aussi : l'installateur tourne avec le Python du système."""
import hashlib
import importlib.util
import io
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("install", "uninstall")
LOG_BUDGET = 1024 * 1024          # la trace : le dernier Mo (les lignes récentes gagnent)
MAX_ZIP = 2 * 1024 * 1024         # le plafond de golem.fm (413 au-delà)
SEND_TIMEOUT_S = 30
# golem.fm de PRODUCTION — le même que bridge/routes_content.DEFAULT_SERVER (un test le vérifie) ; GOLEM_SERVER_URL le
# remplace comme pour le bridge, GOLEM_REPORTS_URL pour les seuls rapports (un golem.fm de dev)
PROD_URL = "https://golem.fm"


def reports_url():
    return (os.environ.get("GOLEM_REPORTS_URL") or os.environ.get("GOLEM_SERVER_URL") or PROD_URL).rstrip("/")


def _scrub_module(src):
    path = os.path.join(src or os.path.dirname(HERE), "bridge", "scrub.py")
    spec = importlib.util.spec_from_file_location("golem_scrub", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def version(src):
    """La version de la source : `git describe` d'un clone, sinon le nom du dossier que bootstrap a déballé
    (`golem-<tag>`), sinon None — jamais devinée."""
    try:
        r = subprocess.run(["git", "-C", src, "describe", "--tags", "--always", "--dirty"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    m = re.match(r"golem-(v\d[\w.\-]*)$", os.path.basename(os.path.normpath(src or "")))
    return m.group(1) if m else None


def _ram_mb():
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            m = re.search(r"^MemTotal:\s+(\d+)\s+kB", f.read(), re.M)
        return int(m.group(1)) // 1024 if m else None
    except OSError:
        return None


def platform_section():
    """Les champs de diag.platform_info (§2.2) qu'on lit sans le bridge ; un champ illisible est absent."""
    out = {"os": None, "kernel": platform.release() or None, "arch": platform.machine() or None,
           "cpu_count": os.cpu_count(), "ram_total_mb": _ram_mb()}
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            kv = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', f.read(), re.M))
        out["os"] = f"{kv.get('ID')} {kv.get('VERSION_ID') or ''}".strip() if kv.get("ID") else None
    except OSError:
        out["os"] = {"Windows": "windows " + platform.version(), "Darwin": "macos " + platform.mac_ver()[0]}.get(
            platform.system()) or platform.system().lower() or None
    return {k: v for k, v in out.items() if v is not None}


def failure_line(lines, step):
    """La ligne qui dit l'échec : la dernière ✗ / error / Traceback de l'étape tombée, sinon la dernière de l'étape."""
    own = [ln for ln in lines if ln.get("step") == step] or lines
    for ln in reversed(own):
        t = ln.get("line") or ""
        if re.match(r"✗ step « .* » failed", t):          # le résumé de l'installateur : le même pour toutes les pannes
            continue
        if t.startswith("✗") or re.search(r"\berror\b|Traceback|exception|failed", t, re.I):
            return t
    return (own[-1].get("line") if own else "") or ""


def _tail(path, budget):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - budget))
            data = f.read()
        return data.decode("utf-8", "replace"), size > budget
    except OSError:
        return None, False


def build(state, kind, out_dir, secrets=(), checks=None):
    """Construit le paquet ; rend {report_id, path, sha256, bytes, sig}. `state` = l'état de l'installateur (S, plus
    `install_view`), lu champ par champ — jamais recopié. Le mot de passe sudo et les clés tapées sont des `secrets`."""
    if kind not in KINDS:
        raise ValueError("kind: install | uninstall")
    src = state.get("src")
    sc = _scrub_module(src).Scrubber(secrets=[s for s in secrets if s], roots=[state.get("dir"), src])
    rid = uuid.uuid4().hex
    steps = [{"id": s.get("id"), "state": s.get("state"), "secs": s.get("secs")} for s in state.get("steps") or []]
    failed = next((s["id"] for s in steps if s["state"] == "fail"), None)
    if failed is None and state.get("running"):
        failed = next((s["id"] for s in steps if s["state"] == "running"), None)    # une étape muette arrêtée
    SC = _scrub_module(src)
    src_line = SC.normalize(sc(failure_line(state.get("log") or [], failed)))
    view = state.get("install") or {}
    phases = [{"id": p.get("id"), "state": p.get("state"), "secs": p.get("secs"),
               "warns": len(p.get("warns") or [])} for p in view.get("phases") or []]
    rc = next((s.get("rc") for s in state.get("steps") or [] if s.get("id") == failed), None)
    ver = state.get("version") or version(src)
    report = {
        "report": {"schema": "golem-report/2", "kind": kind, "report_id": rid,
                   "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "platform": platform_section(),
        # l'installateur pose SA source : la version qu'il installe est la sienne
        "golem": {"version": ver, "target_version": ver, "installer": state.get("platform_name"),
                  "dry": bool(state.get("dry"))},
        "install": {"failed_step": failed, "rc": rc, "sig": SC.sig(src_line), "sig_src": src_line,
                    "stalled": bool(state.get("stalled")), "quiet_s": state.get("quiet"),
                    "elapsed_s": sum(s["secs"] or 0 for s in steps), "steps": steps, "phases": phases,
                    "packs": list(state.get("packs") or []), "engine": state.get("engine"),
                    "instrument": state.get("instrument"), "privilege": state.get("privilege"),
                    # désinstallation : les éléments qui n'ont pas pu partir (ids du plan : `reaper:config`, `apt:…`)
                    "failed_items": list(state.get("failed_items") or [])[:50]},
        "checks": [{"id": c.get("id"), "ok": bool(c.get("ok")), "blocking": bool(c.get("blocking"))}
                   for c in checks or [] if isinstance(c, dict)],
    }
    report = sc.deep(report)
    report["install"]["sig"] = SC.sig(report["install"]["sig_src"])     # golem.fm recalcule : la forme ENVOYÉE fait foi
    files, missing, truncated = {}, [], False
    files["report.json"] = json.dumps(report, indent=1, ensure_ascii=False).encode("utf-8")
    text, truncated = _tail(state.get("log_file") or "", LOG_BUDGET) if state.get("log_file") else (None, False)
    if text is None:
        missing.append("logs/install.log")
    else:
        files["logs/install.log"] = "\n".join(sc(ln) for ln in text.splitlines()).encode("utf-8")
    manifest = {"golem_report": 2, "kind": kind, "report_id": rid, "created_at": report["report"]["created_at"],
                "files": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()},
                "truncated": truncated, "missing": missing}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("golem-report.json", json.dumps(manifest, indent=1))
        for n, b in files.items():
            z.writestr(n, b)
    data = buf.getvalue()
    if len(data) > MAX_ZIP:
        raise ValueError(f"report too large ({len(data)} bytes)")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"golem-{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{rid[:8]}.zip")
    with open(path, "wb") as f:
        f.write(data)
    return {"report_id": rid, "path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "sig": report["install"]["sig"]}


def send(path, kind, base=None, timeout=SEND_TIMEOUT_S):
    """POST /api/ext/install-reports, le zip en corps brut, SANS jeton. Rend {ok, code} ou {ok: False, error}."""
    with open(path, "rb") as f:
        data = f.read()
    h = hashlib.sha256(data).hexdigest()
    url = f"{(base or reports_url())}/api/ext/install-reports?kind={kind}&sha256={h}"
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/zip", "Content-Length": str(len(data))})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read() or b"{}")
        return {"ok": bool(body.get("code")), "code": body.get("code"), "error": None if body.get("code") else "no code"}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        return {"ok": False, "error": body.get("message") or body.get("error") or f"golem.fm answered {e.code}"}
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": f"golem.fm is not reachable ({getattr(e, 'reason', e)})"}
