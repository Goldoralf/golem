# SPDX-License-Identifier: GPL-3.0-or-later
"""Les comptes AVANT l'installation (docs/install-v2.md, lots 4 et 5) : golem.fm et TONE3000 se connectent sur les
premières pages, golem n'existe pas encore sur la machine. Bibliothèque standard seulement (le Python du système).

  golem.fm   l'ALLER-RETOUR convenu avec golem.fm le 2026-11-18 : `POST /api/ext/pair/start`, la fenêtre part sur
             `approve_url` + `return_to=http://127.0.0.1:<port>/back`, et c'est CE serveur qui sonde
             `/api/ext/pair/poll` (la page est partie). Au retour la page lit l'état ici. golem.fm n'a pas de mot de
             passe : un compte naît à la première connexion — rien à saisir dans l'installateur.
  TONE3000   par le RELAIS de golem.fm (`/api/ext/t3k/relay`, le jeton d'appareil suffit) : le PKCE reste ici,
             l'échange se fait ici (tools/t3k.py du dossier source, son `.env` détourné vers un fichier privé).

Rien n'est écrit dans le dossier d'installation tant qu'il n'existe pas : les jetons restent EN MÉMOIRE, puis
  apply_env(target)       les jetons TONE3000 -> <target>/.env, dès que golem est copié (les captures se téléchargent
                          alors pendant le reste de l'installation) ;
  golem_token()           le jeton d'appareil, que l'étape « profile » range par la fonction même de Settings ▸ Connect.
Aucun jeton ne sort par state() : l'écran ne reçoit que des états.

--dry : aucune requête ; l'appairage est « approuvé » au troisième sondage, la connexion TONE3000 aussi."""
import hashlib
import importlib.util
import json
import os
import platform
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

POLL_S = 2.0
PAIR_TTL_S = 20 * 60          # la durée de vie d'un code chez golem.fm
RELAY_TTL_S = 10 * 60
_LOCK = threading.Lock()
_S = {"pair": {"phase": "idle"}, "t3k": {"phase": "idle"}, "token": "", "t3k_env": {}, "gen": 0}
DRY = {"on": False, "polls": 0}


def base_url():
    return (os.environ.get("GOLEM_SERVER_URL") or "https://golem.fm").rstrip("/")


def _http(method, path, body=None, token=None, timeout=8):
    """(statut, json|None) — 0 = golem.fm injoignable. Jamais d'exception."""
    req = urllib.request.Request(base_url() + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "golem-installer")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 — https://golem.fm ou GOLEM_SERVER_URL
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except (OSError, ValueError):
        return 0, None


def rack_id():
    """Le même identifiant que bridge/connect.py rack_id : golem.fm attribue le numéro à vie à la MACHINE."""
    try:
        mid = open("/etc/machine-id").read().strip()
    except OSError:
        mid = ""
    return hashlib.sha256(("golem-connect:" + mid).encode()).hexdigest()[:24] if mid else None


def rack(src):
    """`rack{}` de pair/start, comme rigstatus.rack_identity — liste blanche, rien qui identifie quelqu'un."""
    d = {"installer": "gui", "arch": platform.machine(), "platform": os.sys.platform}
    try:
        with open(os.path.join(src, "VERSION"), encoding="utf-8") as f:
            d["version"] = f.read().strip()
    except OSError:
        pass
    rid = rack_id()
    if rid:
        d["rack_id"] = rid
    return d


def state():
    """Ce que l'écran lit : des états, jamais un jeton."""
    with _LOCK:
        p, t = dict(_S["pair"]), dict(_S["t3k"])
        p.pop("poll_token", None)
        return {"server": base_url(), "pair": p, "paired": bool(_S["token"]),
                "t3k": t, "t3k_signed_in": bool(_S["t3k_env"].get("T3K_ACCESS_TOKEN"))}


def golem_token():
    with _LOCK:
        return _S["token"]


# ── golem.fm ────────────────────────────────────────────────────────────────────────────────────────────────
def with_return(approve_url, port):
    """`approve_url` + return_to : l'adresse de retour ne porte AUCUN jeton de l'installateur (il protège son API
    locale et ne part pas chez golem.fm) — la page le garde dans sessionStorage, `/back` le relit."""
    back = f"http://127.0.0.1:{int(port)}/back"
    sep = "&" if "?" in approve_url else "?"
    return approve_url + sep + "return_to=" + urllib.parse.quote(back, safe="")


def pair_start(src, port, device_name=None):
    if DRY["on"]:
        DRY["polls"] = 0
        d = (200, {"code": "DRY-RUN", "poll_token": "dry", "approve_url": base_url() + "/pair?code=DRY-RUN", "expires_in": PAIR_TTL_S})
    else:
        d = _http("POST", "/api/ext/pair/start", {"device_name": device_name or socket.gethostname() or "golem", "rack": rack(src)})
    st, data = d
    if st != 200 or not isinstance(data, dict) or not data.get("poll_token"):
        why = "golem.fm is not reachable — check the connection" if st == 0 else f"golem.fm refused the pairing ({st})"
        with _LOCK:
            _S["pair"] = {"phase": "error", "error": why}
        return state()
    with _LOCK:
        _S["gen"] += 1
        gen = _S["gen"]
        _S["pair"] = {"phase": "waiting", "code": data.get("code"), "poll_token": data["poll_token"],
                      "approve_url": with_return(data.get("approve_url") or base_url() + "/pair", port),
                      "until": time.time() + min(PAIR_TTL_S, float(data.get("expires_in") or PAIR_TTL_S))}
    threading.Thread(target=_pair_poll, args=(gen,), daemon=True, name="early-pair").start()
    return state()


def _pair_poll(gen):
    while True:
        with _LOCK:
            p = _S["pair"]
            if _S["gen"] != gen or p.get("phase") != "waiting":
                return
            poll_token, until = p["poll_token"], p["until"]
        if time.time() > until:
            with _LOCK:
                if _S["gen"] == gen:
                    _S["pair"] = {"phase": "expired", "error": "the code expired — try again"}
            return
        if DRY["on"]:
            DRY["polls"] += 1
            st, data = (200, {"status": "approved", "token": "dry-token", "name": "golem (dry)"}) if DRY["polls"] >= 3 else (200, {"status": "pending"})
        else:
            st, data = _http("POST", "/api/ext/pair/poll", {"poll_token": poll_token})
        if st == 200 and isinstance(data, dict) and data.get("status") == "approved" and data.get("token"):
            with _LOCK:
                if _S["gen"] == gen:
                    _S["token"] = str(data["token"])
                    _S["pair"] = {"phase": "paired", "name": data.get("name")}
            return
        if 400 <= st < 500:                                  # expirée, consommée ailleurs, refusée : la demande est morte
            with _LOCK:
                if _S["gen"] == gen:
                    _S["pair"] = {"phase": "expired", "error": "already claimed" if st == 409 else "the code expired — try again"}
            return
        time.sleep(POLL_S)


# ── TONE3000, par le relais de golem.fm ─────────────────────────────────────────────────────────────────────
def _t3k_module(src, env_path):
    """tools/t3k.py du dossier source, son `.env` détourné vers un fichier à nous : rien n'est écrit dans la source."""
    spec = importlib.util.spec_from_file_location("golem_t3k_early", os.path.join(src, "tools", "t3k.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ENV = env_path
    m.LOCK = env_path + ".lock"
    return m


def t3k_start(src):
    token = golem_token()
    if not token:
        with _LOCK:
            _S["t3k"] = {"phase": "error", "error": "pair with golem.fm first — it signs this golem in to TONE3000"}
        return state()
    if DRY["on"]:
        DRY["polls"] = 0
        with _LOCK:
            _S["t3k"] = {"phase": "waiting", "auth_url": "https://www.tone3000.com/"}
        threading.Thread(target=_t3k_dry, daemon=True).start()
        return state()
    fd, env_path = tempfile.mkstemp(prefix="golem-early-", suffix=".env")
    os.close(fd)
    os.chmod(env_path, 0o600)
    try:
        T = _t3k_module(src, env_path)
        verifier, challenge = T.pkce()
    except Exception as e:
        _unlink(env_path)
        with _LOCK:
            _S["t3k"] = {"phase": "error", "error": f"cannot start the sign-in ({e})"}
        return state()
    st, d = _http("POST", "/api/ext/t3k/relay", {"challenge": challenge}, token=token)
    if st != 200 or not isinstance(d, dict) or not d.get("authorize_url") or not d.get("state"):
        _unlink(env_path)
        why = "golem.fm is not reachable" if st == 0 else f"golem.fm could not start the TONE3000 sign-in ({st})"
        with _LOCK:
            _S["t3k"] = {"phase": "error", "error": why}
        return state()
    with _LOCK:
        _S["t3k"] = {"phase": "waiting", "auth_url": d["authorize_url"], "state": d["state"]}
    threading.Thread(target=_t3k_poll, args=(T, env_path, d["state"], verifier, token), daemon=True, name="early-t3k").start()
    return state()


def _t3k_dry():
    time.sleep(3 * 0.6)
    with _LOCK:
        _S["t3k_env"] = {"T3K_ACCESS_TOKEN": "dry", "T3K_REFRESH_TOKEN": "dry", "T3K_TOKEN_CLIENT": "dry"}
        _S["t3k"] = {"phase": "signed_in"}


def _unlink(p):
    for x in (p, p + ".lock"):
        try:
            os.remove(x)
        except OSError:
            pass


def _t3k_poll(T, env_path, relay_state, verifier, token):
    deadline = time.time() + RELAY_TTL_S
    err = "the sign-in expired — try again"
    try:
        while time.time() < deadline:
            with _LOCK:
                if _S["t3k"].get("state") != relay_state:
                    return                                    # une autre tentative a pris la place
            st, d = _http("GET", "/api/ext/t3k/relay/" + urllib.parse.quote(relay_state, safe=""), token=token)
            if st in (202, 0):
                time.sleep(POLL_S)
                continue
            if st == 200 and isinstance(d, dict) and d.get("status") == "ready":
                try:
                    T.token_request({"grant_type": "authorization_code", "code": d["code"], "redirect_uri": d["redirect_uri"],
                                     "client_id": d["client_id"], "code_verifier": verifier})
                    env = {k: v for k, v in T.env_read().items() if k.startswith("T3K_") and v}
                    with _LOCK:
                        _S["t3k_env"] = env
                        _S["t3k"] = {"phase": "signed_in"}
                    return
                except SystemExit as e:                       # tools/t3k.py sort ainsi sur un refus du point de jeton
                    err = "TONE3000 refused the sign-in — " + str(e)[:160]
                except (KeyError, TypeError):
                    err = "golem.fm answered without a sign-in code"
                break
            err = "sign-in refused on TONE3000" if (st == 200 and isinstance(d, dict) and d.get("status") == "denied") \
                else ("the sign-in expired — try again" if st == 410 else f"golem.fm could not relay the sign-in ({st})")
            break
        with _LOCK:
            if _S["t3k"].get("state") == relay_state:
                _S["t3k"] = {"phase": "error", "error": err}
    finally:
        _unlink(env_path)


def apply_env(target):
    """Les jetons TONE3000 -> <target>/.env par tools/t3k.py du dossier INSTALLÉ (0600, atomique). True si écrits."""
    with _LOCK:
        env = dict(_S["t3k_env"])
    if not env or DRY["on"]:
        return False
    spec = importlib.util.spec_from_file_location("golem_t3k_target", os.path.join(target, "tools", "t3k.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.env_set(env)
    return True


def reset():
    with _LOCK:
        _S.update(pair={"phase": "idle"}, t3k={"phase": "idle"}, token="", t3k_env={})
        _S["gen"] += 1
