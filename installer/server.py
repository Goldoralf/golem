#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""GoleM — l'installateur graphique (docs/installer.md).

Un serveur HTTP en BIBLIOTHÈQUE STANDARD (rien à installer avant d'installer), lié à 127.0.0.1
sur un port libre, protégé par un jeton à usage unique, qui sert sept écrans Preact/htm (même
langage que l'app) et exécute les scripts de provision/ — la vérité reste dans le dépôt, l'écran
n'est qu'une fenêtre dessus.

Ce fichier ne connaît AUCUN système (2026-10-02) : tout ce qui dépend de Linux ou de Windows — les
vérifications, Reaper, les tailles, les droits, les étapes — vit dans installer/platform_linux.py et
installer/platform_windows.py et installer/platform_macos.py (2026-10-04), derrière la même interface. Une seule porte « quel OS ? » : P, plus bas.

    python3 installer/server.py [--src DIR] [--open] [--dry] [--port N]
    python3 installer/server.py --uninstall [--root DIR] [--open] [--dry]

  --src   le dépôt (checkout git ou archive extraite) ; défaut = le parent de ce fichier
  --open  ouvre le navigateur (xdg-open) sur l'URL avec le jeton
  --dry   ne lance RIEN de réel : chaque étape joue installer/dry_step.py (écrans, tests)
  --uninstall  le DÉSINSTALLATEUR (docs/uninstall.md §4), un mode de ce même serveur : il se copie dans
          /tmp/golem-uninstaller-<hasard>/, repart de là (il supprime le dossier d'où il vient) et efface cette
          copie en sortant. --root = le dossier d'install (défaut : le parent de ce fichier). Linux et Windows
          (docs/uninstall.md §9.4 : %TEMP%\\golem-uninstaller-<hasard>, relancé DÉTACHÉ avec le Python de base).
          Ses écrans et ses deux commandes : installer/uninstaller.py.

Sécurité : 127.0.0.1 seulement, jeton dans l'URL puis en en-tête X-Golem-Token sur chaque appel
API. Linux : le mot de passe sudo ne quitte jamais la mémoire du processus (askpass lu dans
l'environnement du job, platform_linux._askpass). Windows : pas de mot de passe, UNE autorisation
UAC pour le seul script qui écrit dans Program Files (platform_windows.run_elevated).
"""
import argparse
import atexit
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
sys.path.insert(0, HERE)

# ── LA porte « quel OS ? » : un module, choisi une fois ──────────────────────────────
import importlib  # noqa: E402

P = importlib.import_module({"win32": "platform_windows", "darwin": "platform_macos"}.get(sys.platform, "platform_linux"))
import uninstaller as UN  # noqa: E402  — le mode --uninstall (docs/uninstall.md §4)
import dry_bridge as DB  # noqa: E402  — golem simulé pour l'écran Connect en --dry (jamais le vrai :8770)
import phases as PH  # noqa: E402  — les phases de l'écran Install et l'estimateur de temps
import report as RP  # noqa: E402  — le rapport d'échec envoyé sur un clic (docs/diagnostics.md §7.1)


# ── les moteurs audio : le MÊME lecteur que le bridge (bridge/engines.py, bibliothèque standard),
# chargé par son chemin pour ne pas mettre tout le dépôt sur sys.path. Descripteurs lus dans --src.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("golem_engines", os.path.join(os.path.dirname(HERE), "bridge", "engines.py"))
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)

# ── la licence REAPER (écran 3, 2026-10-16) : la MÊME écriture que Settings ▸ Licenses (bridge/reaper_license.py,
# bibliothèque standard), chargée par son chemin — le bridge ne tourne pas pendant l'installation.
_spec = importlib.util.spec_from_file_location("golem_reaper_license", os.path.join(os.path.dirname(HERE), "bridge", "reaper_license.py"))
RL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RL)

# l'écran « What do you play? » : les instruments de bridge/first_run.py (le bridge ne tourne pas pendant l'installation)
INSTRUMENTS = ("guitar", "bass", "keys", "drums", "voice")

# ── état partagé (un seul installateur à la fois) ─────────────────────────────────────
STEPS = P.STEPS


def _default_packs():
    # le pack requis (DI) + le piano là où il joue ; jamais un pack que ce système ne joue pas
    sz = P.sizes(os.path.dirname(HERE), os.path.expanduser("~"))
    return sorted({*sz["required_packs"], *(p for p in ("piano", "guitar")
                                             if p in sz["packs"] and p not in sz["packs_unavailable"])})


S = {
    "token": secrets.token_urlsafe(18),
    "src": None, "dry": False,
    # une installation, deux usages (docs/installer.md §4) : plus de « boîte dédiée » ici — un réglage de l'app
    "dir": P.default_dir(), "packs": _default_packs(),
    "sudo_ok": False, "sudo_pw": None,
    "steps": [{"id": i, "label": l, "state": "pending", "rc": None} for i, l in STEPS],
    "log": [], "running": False, "done": False, "error": None,
    "reaper_job": None,
    # où installer REAPER quand golem le pose (Windows) : vide = Program Files ; choisi à l'écran 3
    "reaper_dir": "",
    "engine": None,                              # moteur audio choisi (écran Engine) ; posé dans main() depuis --src
    "instrument": "guitar",                      # écran « What do you play? » → config/first-run.json (bridge/first_run.py)
    "mode": "install",                           # « uninstall » : les écrans du désinstallateur (installer/uninstaller.py)
    # le rapport d'échec (docs/diagnostics.md §7.1) : jamais construit ni envoyé sans le clic de l'écran
    "report": {"state": None, "code": None, "path": None, "error": None},
    "seen": time.time(),                         # dernier appel reçu (le chien de garde du désinstallateur)
}
LOCK = threading.Lock()
LOG_MAX = 6000
# les phases de l'écran Install (installer/phases.py) : créées au premier « Install now », gardées au Retry
TRACK = []
# le ↻ Try again d'un manque non fatal : {"id", "phase": running|ok|fail} — un seul à la fois, jamais pendant le job
RETRY = {"id": None, "state": None}


def phase_list():
    return P.phases(S) if hasattr(P, "phases") else []


def install_view():
    """Ce que l'écran Install lit : les phases (après Install now), sinon l'estimation de la page « Before you start »."""
    if TRACK:
        return TRACK[0].public()
    try:
        return {**PH.Tracker(phase_list(), STEPS).public(), "preview": True}     # ce qui va se passer, avec les durées
    except Exception:
        return {"phases": None, "total_est": None, "preview": True}


# LA TRACE SUR DISQUE ET LE SILENCE (2026-10-24, un testeur Windows : figé 16 min sur « golem itself », relancé — et
# plus rien ne disait où ni pourquoi, la trace ne vivait qu'en mémoire). Chaque ligne va AUSSI dans un fichier du dossier
# temporaire, gardé après l'installation ; une étape muette depuis STALL_SECS est dite à l'écran, avec un geste pour
# l'arrêter (le Retry habituel repart de cette étape). Une étape ÉLEVÉE (UAC) ne s'arrête pas d'ici : l'installateur ne
# l'est pas.
STALL_SECS = 180
LOGFILE = {"path": None, "f": None}
CUR = {"proc": None, "step": None, "last": None, "elevated": False}


def open_log_file(kind="install"):
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"golem-{kind}-{time.strftime('%Y%m%d-%H%M%S')}.log")
    try:
        LOGFILE["f"] = open(path, "a", encoding="utf-8")
        LOGFILE["path"] = S["log_file"] = path
    except OSError:
        pass


def log(line, step=None):
    line = str(line).rstrip("\n")
    with LOCK:
        CUR["last"] = time.time()                         # un marqueur de progression aussi : ça bouge
        # un marqueur de phase (provision/install.sh `mark`) nourrit l'écran ; il n'entre pas dans la trace
        if TRACK and line.startswith("@@") and TRACK[0].marker(line, step):
            return
        S["log"].append({"n": len(S["log"]), "t": time.time(), "step": step, "line": str(line).rstrip("\n")})
        if len(S["log"]) > LOG_MAX:
            del S["log"][: len(S["log"]) - LOG_MAX]
        if LOGFILE["f"]:
            try:
                LOGFILE["f"].write(f"{time.strftime('%H:%M:%S')} [{step or '-'}] {line}\n")
                LOGFILE["f"].flush()
            except (OSError, ValueError):
                pass


def stop_step():
    """■ Stop this step : tue la commande de l'étape en cours (et ses enfants) ; l'étape échoue, Retry la reprend."""
    with LOCK:
        p, step, elevated = CUR["proc"], CUR["step"], CUR["elevated"]
        if not S["running"] or p is None or p.poll() is not None:
            return {"ok": False, "error": "no step is running"}
        if elevated:
            return {"ok": False, "error": "this step runs with Windows' permission and cannot be stopped from here"}
        quiet = round(time.time() - (CUR["last"] or time.time()))
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        p.kill()
    log(f"✗ stopped by you after {quiet // 60} min {quiet % 60:02d} s without output — tap Retry", step)
    return {"ok": True}


def set_step(sid, **kw):
    with LOCK:
        for st in S["steps"]:
            if st["id"] == sid:
                st.update(kw)


def job_env(extra=None):
    env = dict(os.environ)
    env.update(extra or {})
    env["GOLEM_INSTALLER"] = "1"
    env["DEBIAN_FRONTEND"] = "noninteractive"        # aucun paquet ne pose de question (sudo la retire : voir les scripts)
    if P.PRIVILEGE == "sudo":
        env = P.job_env(env, S)
    return env


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(cmd, step, cwd=None, extra_env=None):
    """Lance une commande, verse sa sortie dans le journal ligne par ligne, rend le code retour."""
    log("$ " + " ".join(str(c) for c in cmd), step)
    try:
        # NO_WINDOW : sous pythonw (l'installateur-application n'a pas de console), chaque commande
        # console ouvrirait SA fenêtre noire — sa sortie arrive de toute façon dans le journal à l'écran
        # stdin FERMÉ : sinon une étape hérite du terminal qui a lancé l'installateur (ssh, curl | sh) et une
        # question de paquet (jackd2, 2026-10-15) y attend une réponse que personne ne voit — l'install se fige
        p = subprocess.Popen(cmd, cwd=cwd, env=job_env(extra_env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, text=True, bufsize=1, encoding="utf-8", errors="replace",
                             creationflags=NO_WINDOW)
    except Exception as e:
        log(f"✗ cannot start: {e}", step)
        return 127
    with LOCK:
        CUR.update(proc=p, step=step, last=time.time(),
                   elevated=any("-Verb RunAs" in str(c) for c in cmd))      # installer/elevate_win.py
    try:
        for ln in p.stdout:
            log(ln, step)
        return p.wait()
    finally:
        with LOCK:
            if CUR["proc"] is p:
                CUR.update(proc=None, elevated=False)


def dry_cmd(name):
    return [sys.executable, os.path.join(S["src"], "installer", "dry_step.py"), name]


def wait_bridge(secs):
    import urllib.request
    t0 = time.time()
    while True:
        try:
            urllib.request.urlopen("http://127.0.0.1:8770/api/app-build", timeout=2).read()
            return True
        except Exception:
            if time.time() - t0 >= secs:
                return False
            time.sleep(min(2, secs))



# ── LE RELAIS VERS GOLEM (écran Connect, docs/installer.md §2 écran 7 et §6) ─────────────────────────────────────
# Télécharger une capture TONE3000 demande le COMPTE de l'utilisateur (OAuth), dont le retour arrive SUR LE BRIDGE ;
# l'appairage golem.fm est un « device flow » que le bridge relaie et dont il garde le jeton. L'écran Connect a donc
# besoin de golem (127.0.0.1:8770) — mais la PAGE ne l'appelle jamais : tout passe par ce serveur, et seulement par
# les routes de BRIDGE_ALLOW (2026-10-15 : avant, sous Linux, l'écran chargeait l'app entière dans un cadre). Sous
# Windows et macOS golem est démarré en mode serveur, sans fenêtre, par `P.bridge_start` (captures d'usine) ; sous
# Linux l'étape « start » l'a lancé.
# --dry : AUCUNE requête HTTP — le bridge est simulé par installer/dry_bridge.py. Sur un poste de dev, :8770 est le
# vrai rack : une démonstration ne doit ni l'appairer, ni le connecter à TONE3000, ni écrire sa config.
BRIDGE = "http://127.0.0.1:8770"
BRIDGE_ALLOW = frozenset({
    ("GET", "/api/integrations"), ("POST", "/api/integrations"),          # état masqué ; clé TONE3000, jeton golem.fm
    ("GET", "/api/golemfm/status"),                                        # configuré / joignable / appairé
    ("POST", "/api/golemfm/pair"), ("GET", "/api/golemfm/pair/status"),   # le device flow
    ("GET", "/api/band"),                                                  # le nom du groupe, une fois appairé
    ("POST", "/api/t3k/auth/start"), ("GET", "/api/t3k/auth/status"),     # OAuth TONE3000
    ("GET", "/api/factory/captures"), ("POST", "/api/factory/captures/download"),
    # l'écran Done, « Continue on a tablet » (docs/installer.md §4) : l'adresse et son QR, un code si aucun appareil
    # principal n'existe — ce que server_message (provision/desktop.py) et le panneau 📱 de l'app demandent aussi
    ("GET", "/api/network/open-url"), ("GET", "/api/auth/devices"), ("POST", "/api/auth/pair-code"),
})
# ce que l'installateur a le droit d'ÉCRIRE par /api/integrations : rien d'autre ne passe, même si on le lui envoie
_INTEG_KEYS = {"golemfm": ("base_url", "token"), "tone3000": ("publishable_key",)}


# les clés tapées pendant CETTE installation : en mémoire seulement, pour que le rapport d'échec les efface (§7.1)
TYPED = set()


def _integrations_body(body):
    out = {}
    for grp, keys in _INTEG_KEYS.items():
        v = (body or {}).get(grp)
        if isinstance(v, dict):
            out[grp] = {k: str(v[k]) for k in keys if v.get(k)}
            TYPED.update(out[grp].values())
    return out


def _bridge(method, path, body=None, timeout=8):
    """Une route de BRIDGE_ALLOW, vers golem — ou vers sa simulation en --dry. Lève si golem ne répond pas."""
    if (method, path) not in BRIDGE_ALLOW:
        raise PermissionError(f"{method} {path} is not relayed by the installer")
    if method == "POST" and path == "/api/integrations":
        body = _integrations_body(body)
    if S["dry"]:
        return DB.call(method, path, body)
    import urllib.error
    import urllib.request
    req = urllib.request.Request(BRIDGE + path, method=method,
                                 data=json.dumps(body or {}).encode() if method == "POST" else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {"error": f"golem answered {e.code}"}


def _open(url):
    """Ouvre un lien dans le navigateur de l'utilisateur — jamais en --dry (rien de réel ne part d'une démonstration)."""
    if S["dry"]:
        log(f"(dry run) would open {url}")
        return
    P.open_url(url)


DOWN = {"ok": False, "down": True, "error": "golem is not answering — start it, then try again"}


def _host(url):
    return urllib.parse.urlsplit(url or "").netloc or url or ""


def _server(integ):
    """Le serveur golem.fm de ce golem (GOLEM_SERVER_URL de son .env, golem.fm par défaut), depuis GET /api/integrations."""
    url = (integ.get("golemfm") or {}).get("base_url") or ""
    return {"label": _host(url), "url": url}


def link_state():
    """L'état des deux cartes de l'écran Connect, en un appel (lectures seulement)."""
    try:
        integ = _bridge("GET", "/api/integrations")
    except Exception:
        return {"up": False, "dry": S["dry"]}
    if "golemfm" not in integ:
        return {"up": True, "dry": S["dry"], "error": integ.get("error") or "golem refused to answer"}
    srv = _server(integ)
    try:
        fm = _bridge("GET", "/api/golemfm/status", timeout=12)
    except Exception as e:
        fm = {"error": str(e)}
    band = None
    if fm.get("authed"):
        try:
            band = ((_bridge("GET", "/api/band") or {}).get("band") or {}).get("name")
        except Exception:
            band = None
    key = (integ.get("tone3000") or {}).get("publishable_key") or {"set": False, "hint": ""}
    # lu même SANS clé : appairé à golem.fm, golem se connecte à TONE3000 par le relais (aucune clé à poser)
    try:
        auth = _bridge("GET", "/api/t3k/auth/status", timeout=15)
    except Exception:
        auth = {"authed": False}
    return {"up": True, "dry": S["dry"],
            "golemfm": {"server": {"label": srv.get("label"), "url": srv.get("url"), "host": _host(srv.get("url"))},
                        **{k: fm.get(k) for k in ("configured", "paired", "reachable", "authed", "error")},
                        "band": band},
            "t3k": {"key": key, "authed": bool(auth.get("authed")), "reason": auth.get("reason")},
            "factory": link_factory()}


def link_factory():
    try:
        cap = _bridge("GET", "/api/factory/captures")
    except Exception:
        return {"up": False}
    return {"up": True, "total": cap.get("total"), "present": cap.get("present"),
            "missing": len(cap.get("missing") or []), "connected": cap.get("connected"), "download": cap.get("download")}


def link_pair():
    """Lance l'appairage golem.fm (le serveur vient du .env du golem : rien à poser avant)."""
    try:
        r = _bridge("POST", "/api/golemfm/pair", {"device_name": "golem rack"}, timeout=20)
    except Exception:
        return DOWN
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or "golem.fm did not start the pairing"}
    return {"ok": True, **{k: r.get(k) for k in ("code", "approve_url", "expires_in")}}


def link_pair_status():
    try:
        return _bridge("GET", "/api/golemfm/pair/status", timeout=12)
    except Exception:
        return {**DOWN, "active": False}


def link_token(body):
    """« I have a device token » : écrit par la route même de Settings ▸ API (sous le serveur du .env du golem)."""
    tok = str((body or {}).get("token") or "").strip()
    if not tok:
        return {"ok": False, "error": "paste the token first"}
    try:
        r = _bridge("POST", "/api/integrations", {"golemfm": {"token": tok}})
    except Exception:
        return DOWN
    return {"ok": False, "error": r["error"]} if r.get("error") else {"ok": True}


def link_t3k_key(body):
    key = str((body or {}).get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "paste the key first"}
    try:
        r = _bridge("POST", "/api/integrations", {"tone3000": {"publishable_key": key}})
    except Exception:
        return DOWN
    return {"ok": False, "error": r["error"]} if r.get("error") else {"ok": True}


def link_t3k_signin():
    try:
        a = _bridge("POST", "/api/t3k/auth/start", timeout=15)
    except Exception:
        return DOWN
    if a.get("error") or not a.get("auth_url"):
        return {"ok": False, "error": a.get("error") or "golem could not start the TONE3000 sign-in"}
    out = {"ok": True, "auth_url": a["auth_url"], "redirect_uri": a.get("redirect_uri")}
    try:
        _open(a["auth_url"])
    except Exception as e:
        out["open_error"] = f"could not open the browser: {e}"
    return out


def link_t3k_status():
    try:
        return _bridge("GET", "/api/t3k/auth/status", timeout=15)
    except Exception:
        return {"authed": False, "down": True}


def factory_state():
    try:
        cap = _bridge("GET", "/api/factory/captures")
    except Exception:
        return {"up": False}
    try:
        auth = _bridge("GET", "/api/t3k/auth/status", timeout=15)
    except Exception:
        auth = {"authed": False}
    return {"up": True, "authed": bool(auth.get("authed")), "reason": auth.get("reason"),
            "total": cap.get("total"), "present": cap.get("present"), "missing": len(cap.get("missing") or []),
            "download": cap.get("download")}


def factory_start():
    """golem en serveur (s'il ne répond pas), puis : connexion TONE3000 si besoin, sinon le téléchargement.
    (Le chemin Windows/macOS ; en --dry il joue contre installer/dry_bridge.py, sans lancer golem.)"""
    st = factory_state()
    if not st.get("up"):
        if S["dry"] or not hasattr(P, "bridge_start"):
            return {"ok": False, "error": "start golem first, then come back to this screen"}
        err = P.bridge_start(Ctx)
        if err:
            return {"ok": False, "error": err}
        st = factory_state()
        if not st.get("up"):
            return {"ok": False, "error": "golem did not answer in time — start it, then try again"}
    if not st.get("authed"):
        a = _bridge("POST", "/api/t3k/auth/start")
        if a.get("error"):
            return {"ok": False, "error": a["error"]}
        try:
            _open(a["auth_url"])
        except Exception as e:
            return {"ok": False, "error": f"could not open the browser: {e}", "auth_url": a.get("auth_url")}
        return {"ok": True, "step": "signin", "redirect_uri": a.get("redirect_uri"), "auth_url": a.get("auth_url")}
    if not st.get("missing"):
        return {"ok": True, "step": "done", **st}
    d = _bridge("POST", "/api/factory/captures/download")
    return {"ok": not d.get("error"), "step": "download", **({"error": d["error"]} if d.get("error") else {})}


# ── l'écran Done : « Continue on a tablet » (docs/installer.md §4, FIXÉ 2026-10-16) ─────────────────────────────────
# golem en SERVEUR (sans fenêtre), puis, SUR CET ÉCRAN, ce dont la tablette a besoin : l'adresse qui marche, son QR,
# et un code d'appairage si aucun appareil principal n'existe. Les mêmes routes du bridge que server_message
# (provision/desktop.py) et le panneau 📱 de l'app (app/tablet-sheet.js), relayées (BRIDGE_ALLOW) — la page n'appelle
# jamais :8770. golem met du temps à répondre (premier démarrage) : on démarre en tâche de fond, la page interroge.
# --dry : tout vient de dry_bridge, rien n'est lancé.
TAB = {"phase": "idle", "error": None, "info": None, "t0": None}
TAB_WAIT_S = 300


def _tablet_info():
    """Lève si golem ne répond pas ; le code d'appairage n'est créé qu'UNE fois (pas un nouveau à chaque lecture)."""
    op = _bridge("GET", "/api/network/open-url")
    if not isinstance(op, dict) or op.get("error"):
        raise ConnectionError((op or {}).get("error") or "no address yet")
    url = op.get("url") or "http://<this computer>:8770/app/"
    base = url.rstrip("/").removesuffix("/app")
    info = {"url": url, "named": bool(op.get("named")), "pair_url": base + "/app/pair.html", "code": None,
            "paired": False}
    devs = _bridge("GET", "/api/auth/devices")
    info["paired"] = any(d.get("admin") for d in (devs or {}).get("devices") or [])
    if not info["paired"]:
        old = (TAB.get("info") or {}).get("code")
        info["code"] = old or (_bridge("POST", "/api/auth/pair-code") or {}).get("code")
    return info


def tablet_state():
    if TAB["phase"] == "starting":
        try:
            TAB["info"], TAB["phase"] = _tablet_info(), "ready"
        except Exception:
            if time.time() - (TAB["t0"] or time.time()) > TAB_WAIT_S:
                TAB.update(phase="error", error="golem did not answer in time — open golem Server from its icon")
    out = {k: TAB[k] for k in ("phase", "error", "info")}
    out["dry"] = S["dry"]
    return out


def tablet_start():
    """« Continue on a tablet » : golem server s'il ne répond pas, puis l'adresse (la page interroge GET /api/tablet)."""
    if TAB["phase"] in ("starting", "ready"):
        return tablet_state()
    TAB.update(phase="starting", error=None, info=None, t0=time.time())
    try:
        TAB["info"], TAB["phase"] = _tablet_info(), "ready"          # golem tourne déjà (Linux : étape « start »)
        return tablet_state()
    except Exception:
        pass
    if S["dry"]:
        TAB.update(phase="error", error="dry run: golem is not answering")
        return tablet_state()
    if not hasattr(P, "bridge_start"):
        TAB.update(phase="error", error="start golem Server from its icon, then try again")
        return tablet_state()

    def run():
        err = P.bridge_start(Ctx)            # Windows/macOS : attend jusqu'à 90 s ; Linux : rend la main tout de suite
        if err:
            TAB.update(phase="error", error=err)
    threading.Thread(target=run, daemon=True).start()
    log("→ golem Server is starting, without a window — a tablet or a phone will be the screen", None)
    return tablet_state()


_DRY_QR = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 29 29" shape-rendering="crispEdges">'
           b'<rect width="29" height="29" fill="#fff"/><path d="M2 2h7v7H2zM20 2h7v7h-7zM2 20h7v7H2z" fill="#000"/>'
           b'<text x="14.5" y="16" font-size="3.2" text-anchor="middle" font-family="sans-serif">dry run</text></svg>')


def tablet_qr():
    """Le QR de l'adresse, relayé depuis golem (image) ; une image factice en --dry. (None, type) s'il manque."""
    if S["dry"]:
        return _DRY_QR, "image/svg+xml"
    import urllib.request
    try:
        with urllib.request.urlopen(BRIDGE + "/api/network/open-qr", timeout=8) as r:
            return r.read(), r.headers.get("Content-Type") or "image/png"
    except Exception:
        return None, "application/json"


# ── la licence REAPER (écran 3) ───────────────────────────────────────────────────────────────────────────────────
# Le contenu est un SECRET : jamais renvoyé, jamais au journal, jamais dans S (donc jamais dans /api/state).
# --dry : simulée — rien n'est écrit, la carte dit « saved » pour la démonstration.
_DRY_LICENSE = {"saved": False}
# l'état d'avant golem pour le reçu (docs/uninstall.md §2), en attente tant que le reçu n'existe pas encore : l'écran 3
# vient AVANT l'étape « source » qui le crée (set-root). Versé après chaque étape réussie (job) ; le premier gagne.
_PENDING_PRIOR = {}
_RECEIPT = []


def _receipt():
    """provision/receipt.py, chargé par son chemin ; None si le module de plateforme n'a pas de reçu (P.RECEIPT :
    Linux et Windows aujourd'hui, comme au bridge — bridge/install_receipt.py)."""
    if not getattr(P, "RECEIPT", False):
        return None
    if not _RECEIPT:
        try:
            spec = importlib.util.spec_from_file_location("golem_receipt", os.path.join(os.path.dirname(HERE), "provision", "receipt.py"))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            _RECEIPT.append(m)
        except Exception:
            _RECEIPT.append(None)
    return _RECEIPT[0]


def _license_prior(key, value):
    if S["dry"]:
        return
    R = _receipt()
    if R is None:
        return
    if R.exists():
        R.prior(key, value)
    else:
        _PENDING_PRIOR.setdefault(key, value)


def flush_priors():
    """Le reçu existe maintenant (étape source) : y verser ce que l'écran 3 a noté avant lui. Jamais fatal."""
    R = _receipt() if _PENDING_PRIOR else None
    if R is None:
        return
    try:
        if R.exists():
            for k in list(_PENDING_PRIOR):
                R.prior(k, _PENDING_PRIOR.pop(k))
    except Exception:
        pass


def license_present():
    try:
        return RL.present() or (S["dry"] and _DRY_LICENSE["saved"])
    except Exception:
        return False


def license_save(body):
    """POST /api/reaper/license {license} : écrit <ressources REAPER>/reaper-license.rk, comme le bridge."""
    text = (body or {}).get("license")
    lic, err = RL.clean(text)
    if err:
        return {"ok": False, "error": err}
    if S["dry"]:
        _DRY_LICENSE["saved"] = True
        log("(dry run) the REAPER license would be saved in REAPER's settings folder", "reaper")
        return {"ok": True, "dry": True, "present": True}
    try:
        RL.write(lic, prior=_license_prior)
    except (OSError, ValueError) as e:
        # le message d'une OSError porte un chemin, jamais le contenu
        return {"ok": False, "error": f"could not save the license: {e}"}
    log("✓ REAPER license saved in REAPER's settings folder — REAPER reads it when it starts", "reaper")
    return {"ok": True, "present": True}


class Ctx:
    """Ce que le module de plateforme reçoit : l'état et les outils, rien d'autre."""
    S = S
    platform_name = P.NAME                       # le rapport d'échec (installer/report.py) dit quel module a tourné
    run = staticmethod(run)
    log = staticmethod(log)
    dry_cmd = staticmethod(dry_cmd)
    wait_bridge = staticmethod(wait_bridge)
    job_env = staticmethod(job_env)


    @staticmethod
    def write_engine(target):
        """config/engine.json du dossier installé (appelé par step_profile de chaque plateforme).
        Lit les descripteurs de la SOURCE : la cible n'a peut-être pas encore son config/engines."""
        eid = S["engine"] or E.default_id(S["src"])
        if os.path.isdir(os.path.join(target, "config", "engines")):
            E.write_choice(eid, root=target, set_by="installer")    # vérifie qu'il est disponible ici
        else:
            _write_engine_raw(target, eid)
        log(f"→ audio engine « {eid} » written to config/engine.json", "profile")


    @staticmethod
    def write_first_run(target):
        """config/first-run.json du dossier installé : l'instrument de l'écran « What do you play? », que le bridge
        applique une fois à son premier démarrage (bridge/first_run.py). Appelé par step_profile de chaque plateforme."""
        os.makedirs(os.path.join(target, "config"), exist_ok=True)
        with open(os.path.join(target, "config", "first-run.json"), "w", encoding="utf-8") as f:
            json.dump({"instrument": S["instrument"], "at": time.strftime("%Y-%m-%d %H:%M")}, f, indent=1)
        log(f"→ instrument « {S['instrument']} » written to config/first-run.json", "profile")


def _write_engine_raw(target, eid):
    os.makedirs(os.path.join(target, "config"), exist_ok=True)
    with open(os.path.join(target, "config", E.CHOICE_FILE), "w", encoding="utf-8") as f:
        json.dump({"engine": eid, "set_by": "installer", "at": time.strftime("%Y-%m-%d %H:%M")}, f, indent=1)


# ── le rapport d'échec (docs/diagnostics.md §7.1) ─────────────────────────────────────────
CHECKS_LAST = []                                 # les dernières vérifications montrées (écran Checks)


def send_report(kind="install"):
    """Construit le paquet puis l'envoie à golem.fm — sur le clic de l'écran d'échec, jamais autrement. En --dry : construit,
    jamais envoyé. Le paquet reste dans le dossier temporaire : si l'envoi échoue, l'écran donne son chemin."""
    with LOCK:
        if S["report"]["state"] == "sending":
            return
        S["report"] = {"state": "sending", "code": None, "path": None, "error": None}
        st = {k: S.get(k) for k in ("src", "dir", "steps", "running", "log_file", "packs", "engine", "instrument", "dry")}
        st["log"] = list(S["log"])
        st["install"] = install_view()
        st["quiet"] = round(time.time() - CUR["last"]) if CUR["last"] else None
        st["stalled"] = bool(S["error"]) and (st["quiet"] or 0) >= STALL_SECS
        st["platform_name"], st["privilege"] = P.NAME, P.PRIVILEGE
        secrets_ = [S.get("sudo_pw"), *TYPED]
    try:
        import tempfile
        b = RP.build(st, kind, os.path.join(tempfile.gettempdir(), "golem-reports"), secrets=secrets_, checks=CHECKS_LAST)
    except Exception as e:
        log(f"✗ report not built: {type(e).__name__}: {e}", "report")
        with LOCK:
            S["report"] = {"state": "fail", "code": None, "path": None, "error": f"the report could not be built ({e})"}
        return
    if S["dry"]:
        log(f"(dry run) report built, not sent: {b['path']}", "report")
        with LOCK:
            S["report"] = {"state": "dry", "code": None, "path": b["path"], "error": None}
        return
    r = RP.send(b["path"], kind)
    log(f"report {'sent, code ' + r['code'] if r['ok'] else 'not sent: ' + str(r['error'])} ({b['path']})", "report")
    with LOCK:
        S["report"] = {"state": "sent" if r["ok"] else "fail", "code": r.get("code"), "path": b["path"],
                       "error": None if r["ok"] else r["error"]}


# ── le job d'installation ─────────────────────────────────────────────────────────────
def job():
    with LOCK:
        S["running"], S["error"] = True, None
        S["report"] = {"state": None, "code": None, "path": None, "error": None}   # un nouvel échec, un nouveau rapport
        for st in S["steps"]:
            if st["state"] != "ok":
                st.update(state="pending", rc=None)
        if not TRACK:
            try:
                TRACK.append(PH.Tracker(phase_list(), STEPS))
            except Exception:                            # une estimation qui casse n'empêche jamais l'installation
                TRACK.append(PH.Tracker([], STEPS))
        else:
            TRACK[0].reset_unfinished()
    try:
        for sid, _ in STEPS:
            if next(st for st in S["steps"] if st["id"] == sid)["state"] == "ok":
                continue
            set_step(sid, state="running")
            with LOCK:
                TRACK[0].step_started(sid)
            t0 = time.time()
            try:
                rc = P.run_step(sid, Ctx)
            except Exception as e:                      # une étape qui lève est une étape qui échoue, dite
                log(f"✗ {type(e).__name__}: {e}", sid)
                rc = 1
            set_step(sid, state="ok" if rc == 0 else "fail", rc=rc, secs=round(time.time() - t0))
            with LOCK:
                TRACK[0].step_ended(sid, rc == 0)
            if rc == 0:
                flush_priors()                           # le reçu est né avec la source : l'écran 3 y verse son « avant »
            if rc != 0:
                with LOCK:
                    S["error"] = f"{sid} failed (exit {rc})"
                log(f"✗ step « {sid} » failed (exit {rc}) — fix the cause and tap Retry", sid)
                return
        with LOCK:
            S["done"] = True
        log("✅ golem is installed.", None)
    finally:
        with LOCK:
            S["running"] = False


def retry_item(rid):
    """↻ Try again sur UN manque non fatal (un plugin compilé qui a échoué) : son seul script, après l'installation."""
    if not hasattr(P, "run_retry") or rid not in getattr(P, "RETRY", {}):
        return {"ok": False, "error": "this cannot be retried from here"}
    with LOCK:
        if S["running"] or RETRY["state"] == "running":
            return {"ok": False, "error": "wait until the current step ends"}
        if not TRACK or not any(w["retry"] == rid for p in TRACK[0].ph for w in p["warns"]):
            return {"ok": False, "error": "nothing to retry"}
        RETRY.update(id=rid, state="running")

    def go():
        try:
            rc = P.run_retry(rid, Ctx)
        except Exception as e:
            log(f"✗ {type(e).__name__}: {e}", "retry")
            rc = 1
        with LOCK:
            if rc == 0:
                TRACK[0].warn_resolved(rid)
            RETRY.update(state="ok" if rc == 0 else "fail")
        log(f"✓ {rid} installed" if rc == 0 else f"✗ {rid} failed again (exit {rc})", "retry")
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


# ── HTTP ──────────────────────────────────────────────────────────────────────────────
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json", ".ico": "image/x-icon"}


class H(BaseHTTPRequestHandler):
    server_version = "GoleMInstaller/1"

    def log_message(self, *a):          # pas de journal HTTP sur la console
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(path)[1]
        with open(path, "rb") as f:
            self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    def _auth(self):
        tok = self.headers.get("X-Golem-Token") or urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("t", [""])[0]
        return secrets.compare_digest(tok or "", S["token"])

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        S["seen"] = time.time()
        uninstall = S["mode"] == "uninstall"
        if u.path == "/":
            if not self._auth():
                what = b"uninstaller" if uninstall else b"installer"
                return self._send(403, b"<h1>golem " + what + b"</h1><p>Open the exact link printed in the terminal (it carries a one-time token).</p>", "text/html")
            return self._file(os.path.join(UI, "uninstall.html" if uninstall else "index.html"))
        if u.path.startswith("/ui/"):
            return self._file(os.path.join(UI, os.path.basename(u.path)))
        if u.path.startswith("/vendor/"):
            return self._file(os.path.join(S["src"], "app", "vendor", os.path.basename(u.path)))
        if u.path.startswith("/icons/"):
            return self._file(os.path.join(S["src"], "app", "icons", os.path.basename(u.path)))
        if not u.path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        if not self._auth():
            return self._send(403, {"error": "bad token"})
        if u.path == "/api/state":
            with LOCK:
                st = {k: v for k, v in S.items() if k not in ("sudo_pw", "log", "token", "reaper_job")}
                st["install"] = install_view() if not uninstall else None
                st["retry"] = dict(RETRY)
                # le silence de l'étape en cours (secondes sans une ligne) : l'écran le dit passé STALL_SECS
                st["quiet"] = round(time.time() - CUR["last"]) if S["running"] and CUR["last"] else None
                st["stall_secs"] = STALL_SECS
                st["stoppable"] = CUR["proc"] is not None and not CUR["elevated"]
            st["platform"] = {"os": P.NAME, "privilege": P.PRIVILEGE, "ui": P.ui()}
            # l'écran Done : « Restart your computer to finish » seulement quand l'install vient de donner les droits
            # temps réel à une session qui ne les a pas encore (platform_linux.restart_needed)
            if not uninstall and hasattr(P, "restart_needed"):
                # (en dry, toujours : les écrans de démonstration montrent ce cas, rien ne redémarre — restart() le dit)
                st["platform"]["restart"] = bool(S["dry"] or P.restart_needed())
            if uninstall:
                st["uninstall"] = UN.public()
            return self._send(200, st)
        if uninstall:
            r = UN.handle_get(u.path, q)
            if r is not None:
                return self._send(*r)
            if u.path != "/api/log":
                return self._send(404, {"error": "not found"})
        if u.path == "/api/checks":
            CHECKS_LAST[:] = P.checks()
            return self._send(200, {"checks": CHECKS_LAST})
        if u.path == "/api/connect" and hasattr(P, "connect_status"):
            return self._send(200, P.connect_status(Ctx))
        if u.path == "/api/factory":
            return self._send(200, factory_state())
        # l'écran Connect (Linux) : ses lectures, relayées vers golem (BRIDGE_ALLOW)
        if u.path == "/api/link":
            return self._send(200, link_state())
        if u.path == "/api/link/pair":
            return self._send(200, link_pair_status())
        if u.path == "/api/link/t3k":
            return self._send(200, link_t3k_status())
        if u.path == "/api/link/factory":
            return self._send(200, link_factory())
        if u.path == "/api/tablet":
            return self._send(200, tablet_state())
        if u.path == "/api/tablet/qr":
            body, ctype = tablet_qr()
            return self._send(200 if body else 404, body or {"error": "no QR yet"}, ctype)
        if u.path == "/api/vital" and hasattr(P, "vital_status"):
            return self._send(200, P.vital_status())
        if u.path == "/api/engines":
            return self._send(200, {"current": S["engine"],
                                    "features": [{"id": i, "label": l} for i, l in E.features(S["src"])],
                                    "engines": E.descriptors(S["src"])})
        if u.path == "/api/reaper":
            d = P.reaper_detect(S["src"])
            d["job"] = S["reaper_job"]
            d["license_present"] = license_present()     # présence seulement — jamais le contenu
            return self._send(200, d)
        if u.path == "/api/size":
            return self._send(200, P.sizes(S["src"], q.get("dir", [S["dir"]])[0]))
        if u.path == "/api/log":
            since = int(q.get("since", ["0"])[0])
            with LOCK:
                lines = [l for l in S["log"] if l["n"] >= since]
            return self._send(200, {"lines": lines, "n": (S["log"][-1]["n"] + 1) if S["log"] else 0})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if not self._auth():
            return self._send(403, {"error": "bad token"})
        S["seen"] = time.time()
        b = self._json()
        if S["mode"] == "uninstall" and u.path not in ("/api/sudo", "/api/quit", "/api/open"):
            r = UN.handle_post(u.path, b)
            return self._send(*(r if r is not None else (404, {"error": "not found"})))
        if u.path == "/api/sudo":
            if P.PRIVILEGE != "sudo":
                return self._send(400, {"ok": False, "error": "no password on this system"})
            ok, err = P.sudo_check(str(b.get("password") or ""), S["dry"])
            with LOCK:
                S["sudo_ok"] = ok
                S["sudo_pw"] = str(b.get("password")) if ok else None
            if ok and not S["dry"]:
                threading.Thread(target=P.keepalive, args=(Ctx,), daemon=True).start()
            return self._send(200, {"ok": ok, "error": err if not ok else None})
        if u.path == "/api/config":
            sz = P.sizes(S["src"], S["dir"])
            with LOCK:
                if b.get("dir"):
                    S["dir"] = os.path.expanduser(str(b["dir"]))
                # seul un moteur DISPONIBLE ici se choisit (aujourd'hui : Reaper) — le reste est ignoré
                if b.get("engine") in {e["id"] for e in E.descriptors(S["src"]) if e["available"]}:
                    S["engine"] = b["engine"]
                if b.get("instrument") in INSTRUMENTS:
                    S["instrument"] = b["instrument"]
                if isinstance(b.get("packs"), list):
                    S["packs"] = sorted({*(p for p in b["packs"] if p in sz["packs"] and p not in sz["packs_unavailable"]),
                                         *sz["required_packs"]})
            return self._send(200, {"ok": True, "dir": S["dir"], "packs": S["packs"],
                                    "engine": S["engine"], "instrument": S["instrument"]})
        if u.path == "/api/report":
            # « Send this report to golem » (docs/diagnostics.md §7.1) : seulement après un échec, dans un fil (≤ 30 s)
            if not S["error"]:
                return self._send(400, {"ok": False, "error": "nothing failed: there is nothing to report"})
            threading.Thread(target=send_report, args=("install",), daemon=True).start()
            return self._send(200, {"ok": True})
        if u.path == "/api/reaper/locate":
            # « J'ai déjà REAPER ailleurs » (2026-10-17) : on RETIENT le dossier indiqué — s'il contient reaper.exe
            if not hasattr(P, "reaper_locate"):
                return self._send(400, {"ok": False, "error": "not available on this system"})
            try:
                exe = P.reaper_locate(S["src"], str(b.get("path") or ""))
            except Exception as e:
                return self._send(200, {"ok": False, "error": str(e)})
            log(f"✓ Reaper found at {exe} — golem will use this one", "reaper")
            return self._send(200, {"ok": True, "path": exe})
        if u.path == "/api/reaper/install":
            if S["reaper_job"] == "running":
                return self._send(200, {"ok": True, "job": "running"})
            if isinstance(b.get("dir"), str):
                S["reaper_dir"] = b["dir"].strip()

            def rj():
                S["reaper_job"] = "running"
                rc = run(dry_cmd("reaper"), "reaper") if S["dry"] else P.reaper_install(Ctx)
                S["reaper_job"] = "ok" if rc == 0 else "fail"
            threading.Thread(target=rj, daemon=True).start()
            return self._send(200, {"ok": True, "job": "running"})
        if u.path == "/api/reaper/license":
            return self._send(200, license_save(b))
        if u.path == "/api/stop-step":
            return self._send(200, stop_step())
        if u.path == "/api/retry-item":
            return self._send(200, retry_item(str(b.get("id") or "")))
        if u.path == "/api/install" or u.path == "/api/retry":
            if S["running"]:
                return self._send(200, {"ok": True, "running": True})
            if P.PRIVILEGE == "sudo" and not S["sudo_ok"]:
                return self._send(400, {"ok": False, "error": "sudo first"})
            threading.Thread(target=job, daemon=True).start()
            return self._send(200, {"ok": True, "running": True})
        if u.path == "/api/open":
            url = str(b.get("url") or "")
            if url.startswith("http://") or url.startswith("https://"):
                try:
                    _open(url)
                except Exception as e:
                    return self._send(200, {"ok": False, "error": str(e)})
            return self._send(200, {"ok": True})
        if u.path == "/api/connect" and hasattr(P, "connect_save"):
            TYPED.update(str(b.get(k)) for k in ("golem_token", "t3k_key") if b.get(k))   # effacées du rapport (§7.1)
            return self._send(200, P.connect_save(Ctx, b))
        if u.path == "/api/tablet":
            return self._send(200, tablet_start())
        if u.path == "/api/factory/start":
            return self._send(200, factory_start())
        if u.path == "/api/factory/download":
            try:
                return self._send(200, _bridge("POST", "/api/factory/captures/download"))
            except Exception as e:
                return self._send(200, {"error": str(e)})
        # l'écran Connect (Linux) : ses gestes — chacun compose des routes de BRIDGE_ALLOW, aucun corps relayé tel quel
        if u.path == "/api/link/pair":
            return self._send(200, link_pair())
        if u.path == "/api/link/token":
            return self._send(200, link_token(b))
        if u.path == "/api/link/t3k-key":
            return self._send(200, link_t3k_key(b))
        if u.path == "/api/link/t3k-signin":
            return self._send(200, link_t3k_signin())
        if u.path == "/api/restart" and S["mode"] != "uninstall" and hasattr(P, "restart"):
            ok, why = P.restart(Ctx)
            if not ok:
                return self._send(200, {"ok": False, "error": "the computer did not restart" + (": " + why if why else "")
                                        + " — restart it from the system menu"})
            threading.Thread(target=lambda: (time.sleep(1), close_window(), _exit(0)), daemon=True).start()
            return self._send(200, {"ok": True})
        if u.path in ("/api/quit", "/api/finish"):
            if S["mode"] == "uninstall" and UN.busy():
                return self._send(400, {"ok": False, "error": "wait until the current step ends"})
            # « finish » : lancer GoleM PUIS fermer — un seul geste à la fin (2026-10-02)
            if u.path == "/api/finish" and hasattr(P, "finish"):
                if not P.finish(Ctx):
                    return self._send(200, {"ok": False, "error": "golem is not installed in " + S["dir"]})
                # on ne ferme qu'une fois golem LÀ (VM Windows 2026-10-24) : le premier démarrage met ~50 s avant d'ouvrir
                # sa fenêtre, et l'installateur fermé aussitôt laissait un écran vide — « rien ne se passe », on
                # relançait par l'icône. Sa fenêtre s'ouvre dès que le bridge répond : on attend ça, plafonné.
                threading.Thread(target=lambda: (S["dry"] or wait_bridge(FINISH_WAIT_S), time.sleep(3),
                                                 close_window(), _exit(0)), daemon=True).start()
                return self._send(200, {"ok": True, "starting": True})
            # « Close the installer » quand un redémarrage est dû : ce que l'installateur a démarré (bridge, REAPER sans
            # rtprio) ne doit pas survivre et être réutilisé après la reconnexion (platform_linux.stop_golem)
            if S["mode"] != "uninstall" and hasattr(P, "restart_needed") and P.restart_needed():
                P.stop_golem(Ctx)
            threading.Thread(target=lambda: (time.sleep(0.5), close_window(), _exit(0)), daemon=True).start()
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


FINISH_WAIT_S = 150  # « Open golem » : l'installateur reste ouvert jusqu'à ce que golem réponde, au plus ce temps
WINDOW = []          # la fenêtre d'application de l'installateur, quand c'est nous qui l'avons ouverte


def cleanup():
    """Ce que l'installateur laisse derrière lui disparaît avec lui (Linux : le dossier de l'askpass dans /tmp,
    docs/uninstall.md §8). Toutes les sorties y passent : os._exit saute atexit, d'où les appels explicites."""
    try:
        if hasattr(P, "cleanup"):
            P.cleanup()
    except Exception:
        pass
    if S.get("mode") == "uninstall" and UN.DETACHED:
        close_window()                   # Windows : la fenêtre d'abord, son profil vit dans la copie qu'on va effacer
    try:
        UN.cleanup()                     # la copie /tmp/golem-uninstaller-* du désinstallateur
    except Exception:
        pass


def _exit(code=0):
    cleanup()
    os._exit(code)


def close_window():
    """« Close the installer » arrêtait le serveur et laissait la fenêtre ouverte, figée : rien ne
    semblait se passer (2026-10-02). La fenêtre est notre processus : on la ferme avec lui."""
    for w in WINDOW:
        try:
            P.close_app(w) if hasattr(P, "close_app") else w.terminate()
        except Exception:
            pass


def _in_cache(path):
    caches = [os.path.expanduser("~/.cache"), os.environ.get("LOCALAPPDATA") or ""]
    return any(c and os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(c))) for c in caches)


def start_uninstall(a, dry):
    """Le mode --uninstall. Premier passage : se copier dans le dossier temporaire et s'y relancer (Linux : os.execv,
    même processus ; Windows, qui n'a pas d'exec : un processus DÉTACHÉ avec le Python de base, puis on sort).
    Second passage (--owned-tmp) : servir depuis la copie, qui part avec le serveur. Rend True si on sert."""
    if not getattr(P, "UNINSTALL", False):       # le module de plateforme dit s'il sait désinstaller (Linux, Windows)
        print("The graphical uninstaller is not available on this system yet (docs/uninstall.md).", file=sys.stderr)
        sys.exit(2)
    root = os.path.abspath(os.path.expanduser(a.root or os.path.dirname(HERE)))
    if not a.owned_tmp:
        tmp = UN.self_copy(os.path.dirname(HERE))
        argv = UN.reexec_argv(tmp, root, dry=dry, open_=a.open, port=a.port)
        try:
            os.chdir(tmp)                # le moteur refuse le dossier d'install tant qu'on y a son répertoire courant
            if UN.relaunch_detached(argv, tmp):
                sys.exit(0)              # la copie sert désormais ; ce processus-ci ne tient plus rien du dossier
            os.execv(argv[0], argv)
        except OSError:
            UN.remove_tmp(tmp)
            raise
        return False                     # (un execv simulé par les tests)
    S["mode"], S["src"] = "uninstall", os.path.dirname(HERE)       # les écrans et /vendor viennent de la copie
    if hasattr(P, "ASKPASS_BASE"):
        P.ASKPASS_BASE = a.owned_tmp     # l'askpass naît DANS la copie : pas un golem-installer-* de plus dans /tmp
    if hasattr(P, "APP_PROFILE"):
        # la fenêtre d'application garde son profil DANS la copie : celui de l'installateur vit dans le dossier de
        # données de golem, que la désinstallation supprime (un profil ouvert y bloquerait l'effacement)
        P.APP_PROFILE = os.path.join(a.owned_tmp, "browser")
    UN.init(Ctx, root, a.owned_tmp, dry, privilege=P.PRIVILEGE)
    return True


def _watchdog(idle_secs=900):
    """Le désinstallateur n'a pas de fenêtre à lui (un onglet) : onglet fermé et rien en cours depuis 15 min, il
    s'en va — et sa copie dans /tmp avec lui. L'écran l'appelle toutes les 10 s tant qu'il est ouvert."""
    while True:
        time.sleep(30)
        if time.time() - S["seen"] > idle_secs and not UN.busy():
            _exit(0)


def main(argv=None):
    # une sortie qui ne sait pas écrire un caractère (Windows, cp1252 : « → ») ne doit jamais tuer le serveur
    for _st in (sys.stdout, sys.stderr):
        try:
            _st.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.dirname(HERE))
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--dir", default=None, help="target folder proposed on screen 3")
    ap.add_argument("--uninstall", action="store_true", help="the graphical uninstaller (docs/uninstall.md)")
    ap.add_argument("--root", default=None, help="--uninstall: the golem install folder")
    ap.add_argument("--owned-tmp", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    dry = a.dry or os.environ.get("GOLEM_INSTALLER_DRY") == "1"
    S["dry"] = dry
    if a.uninstall:
        if not start_uninstall(a, dry):
            return
    else:
        S["src"] = os.path.abspath(a.src)
        S["engine"] = E.default_id(S["src"])         # coché par défaut : le moteur `default` des descripteurs
        if a.dir:
            S["dir"] = os.path.abspath(os.path.expanduser(a.dir))
        elif (os.path.isdir(os.path.join(S["src"], ".git")) and not _in_cache(S["src"])
              and not getattr(P, "tcc_protected", lambda _p: None)(S["src"])):
            S["dir"] = S["src"]                       # lancé depuis un dépôt déjà posé : on installe SUR PLACE
        # macOS : un dépôt dans le Bureau, les Documents ou les Téléchargements n'est PAS installé sur place —
        # ni le bash élevé, ni golem.app, ni l'agent d'ouverture de session n'y lisent (TCC). Copié dans ~/golem.
    open_log_file("uninstall" if a.uninstall else "install")
    # le ménage AVANT d'ouvrir le port : une sortie précoce (port pris…) efface aussi la copie du désinstallateur
    atexit.register(cleanup)
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):     # terminal fermé, kill : même ménage
        if sig is not None:
            try:
                signal.signal(sig, lambda *_: _exit(0))
            except (ValueError, OSError):
                pass
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={S['token']}"
    what = "uninstaller" if S["mode"] == "uninstall" else "installer"
    # « open this link » laissait croire qu'il FALLAIT cliquer, alors que la fenêtre s'ouvre seule (2026-11-03) :
    # le lien n'est qu'un secours
    if a.open:
        print(f"golem {what}{' (DRY RUN)' if S['dry'] else ''} — opening its window…\n"
              f"  If no window appears, open this link in your browser:\n  {url}", flush=True)
    else:
        print(f"golem {what}{' (DRY RUN)' if S['dry'] else ''} → open this link in your browser:\n  {url}", flush=True)
    if S["mode"] == "uninstall":
        threading.Thread(target=_watchdog, daemon=True).start()
    if a.open:
        try:
            # une FENÊTRE d'application quand l'OS sait en ouvrir une, un onglet sinon. Le DÉSINSTALLATEUR Linux reste
            # en onglet (docs/uninstall.md §4) : les profils dédiés des fenêtres sont parmi ce qu'il efface
            app = hasattr(P, "open_app") and not (S["mode"] == "uninstall" and P.NAME == "linux")
            window = P.open_app(url) if app else P.open_url(url)
        except Exception:
            window = None
        if window is not None:
            WINDOW.append(window)

            def close_with_window():
                # fermer la fenêtre = fermer l'installateur, comme une vraie application. Une
                # installation en cours va à son terme d'abord : on ne coupe pas une étape élevée.
                window.wait()
                # le processus lancé a pu PASSER LA MAIN à un autre (un Edge qui tourne déjà) : la fenêtre vit tant
                # qu'un navigateur porte son profil (platform_windows.app_alive)
                while hasattr(P, "app_alive") and P.app_alive():
                    time.sleep(2)
                while S["running"] or (S["mode"] == "uninstall" and UN.busy()):
                    time.sleep(1)
                _exit(0)
            threading.Thread(target=close_with_window, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
