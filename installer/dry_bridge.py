# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bridge FACTICE de l'installateur (--dry) — le pendant de dry_step.py pour l'écran Connect.

En --dry, le relais de l'installateur vers golem (server.py `_bridge`) ne fait AUCUNE requête HTTP : il appelle
`call()` ici. Raison (2026-10-15) : sur le poste de développement, 127.0.0.1:8770 est le VRAI rack — un appairage
ou une connexion TONE3000 lancés depuis une démonstration écriraient sa config. Les réponses ont la FORME de
celles du bridge (bridge/routes_content.py, routes_backing.py, routes_t3k.py, golemfm.py), avec des valeurs
inventées et un déroulé déterministe, compté en appels :

  · appairage golem.fm : un code, puis « approuvé » au 3e poll de /api/golemfm/pair/status ;
  · TONE3000 : la clé doit faire 8 caractères ou plus ; la connexion aboutit au 3e poll de /api/t3k/auth/status ;
  · captures d'usine : 14 manquantes, le téléchargement avance de 3 par lecture, la dernière échoue (pour voir
    l'erreur à l'écran) ;
  · écran Done, « Continue on a tablet » : une adresse `.local`, aucun appareil principal, un code d'appairage.

`GOLEM_INSTALLER_DRY_BRIDGE=down` simule un golem qui ne répond pas (la carte « The rack is not answering yet »).
"""
import os
import threading

SERVER = "https://golem.fm.example"    # inventé : jamais une adresse réelle en démonstration
CODE = "K7QX-4MPD"
TOTAL = 14

_LOCK = threading.Lock()
_S = {}


def reset():
    with _LOCK:
        _S.clear()
        _S.update(base_url=SERVER, token="", pair_polls=None, key="", authed=False, signin_polls=None,
                  present=0, dl=None)


reset()


def _mask(v):
    return {"set": bool(v), "hint": ("…" + v[-4:]) if len(v) >= 4 else ("set" if v else "")}


def _down():
    return os.environ.get("GOLEM_INSTALLER_DRY_BRIDGE") == "down"


def call(method, path, body=None):
    """Une réponse inventée, de la forme de celle du bridge ; lève ConnectionError si « golem » est éteint."""
    if _down():
        raise ConnectionError("dry run: golem is not answering (GOLEM_INSTALLER_DRY_BRIDGE=down)")
    body = body or {}
    with _LOCK:
        s = _S
        if (method, path) == ("GET", "/api/integrations"):
            return {"tone3000": {"publishable_key": _mask(s["key"])},
                    "golemfm": {"base_url": s["base_url"], "token": _mask(s["token"]), "auto_push": False}}
        if (method, path) == ("POST", "/api/integrations"):
            t3k, fm = body.get("tone3000") or {}, body.get("golemfm") or {}
            if t3k.get("publishable_key"):
                k = str(t3k["publishable_key"]).strip()
                if len(k) < 8:
                    return {"error": "this doesn't look like a TONE3000 key"}
                s["key"], s["authed"] = k, False
            if fm.get("token"):
                s["token"] = fm["token"]
            return {"ok": True}
        if (method, path) == ("GET", "/api/golemfm/status"):
            return {"configured": bool(s["base_url"]), "paired": bool(s["token"]),
                    "reachable": bool(s["base_url"]), "authed": bool(s["base_url"] and s["token"])}
        if (method, path) == ("POST", "/api/golemfm/pair"):
            if not s["base_url"]:
                return {"ok": False, "error": "set the golem.fm server URL first"}
            s["pair_polls"] = 0
            return {"ok": True, "code": CODE, "approve_url": s["base_url"] + "/devices?code=" + CODE, "expires_in": 600,
                    "qr": [[1, 0], [0, 1]]}
        if (method, path) == ("GET", "/api/golemfm/pair/status"):
            if s["pair_polls"] is None:
                return {"active": False}
            s["pair_polls"] += 1
            if s["pair_polls"] >= 3:
                s["pair_polls"], s["token"] = None, "dry-device-token-0001"
                return {"active": False, "approved": True}
            return {"active": True, "code": CODE, "approve_url": s["base_url"] + "/devices?code=" + CODE,
                    "pending": True, "unreachable": False}
        if (method, path) == ("GET", "/api/band"):
            return {"band": {"id": "dry", "name": "The Dry Runs"}, "people": [], "bands": []} if s["token"] \
                else {"band": None, "people": [], "bands": []}
        if (method, path) == ("POST", "/api/t3k/auth/start"):
            relay = bool(s["token"])                     # appairé à golem.fm : le relais, sans clé (routes_t3k.py)
            if not s["key"] and not relay:
                return {"error": "no TONE3000 publishable key on this golem yet — paste it in the field above "
                                 "(tone3000.com ▸ Settings ▸ API Keys), save 💾, then Connect"}
            s["signin_polls"] = 0
            return {"auth_url": "https://www.tone3000.com/api/v1/oauth/authorize?client_id=dry&state=dry",
                    **({"relay": True} if relay else {"relay": False,
                                                       "redirect_uri": "http://192.168.1.20:8770/api/t3k/auth/callback"}),
                    "desktop": False, "qr": [[1, 0], [0, 1]]}
        if (method, path) == ("GET", "/api/t3k/auth/status"):
            if s["signin_polls"] is not None:
                s["signin_polls"] += 1
                if s["signin_polls"] >= 3:
                    s["signin_polls"], s["authed"] = None, True
            if s["authed"]:
                return {"authed": True}
            return {"authed": False, "reason": None if s["key"] or s["token"] else "no TONE3000 publishable key"}
        if (method, path) == ("GET", "/api/factory/captures"):
            dl = s["dl"]
            if dl and dl["phase"] == "running":
                dl["done"] = min(dl["total"], dl["done"] + 3)
                s["present"] = min(TOTAL - 1, s["present"] + 3)
                dl["current"] = f"capture {dl['done']} of {dl['total']}"
                if dl["done"] >= dl["total"]:
                    dl.update(phase="done", current=None, installed=[{"tone": i} for i in range(dl["total"] - 1)],
                              failed=[{"tone": 9999, "title": "Plexi 1969 (dry run)", "why": "simulated failure"}])
            missing = [{"tone": 9000 + i} for i in range(TOTAL - s["present"])]
            return {"total": TOTAL, "present": s["present"], "missing": missing, "connected": s["authed"],
                    "download": dict(dl) if dl else {"phase": "idle"}}
        if (method, path) == ("POST", "/api/factory/captures/download"):
            if not s["authed"]:
                return {"ok": False, "error": "connect to TONE3000 first"}
            s["dl"] = {"phase": "running", "done": 0, "total": TOTAL - s["present"], "current": None,
                       "installed": [], "failed": []}
            return {"ok": True}
        # l'écran Done, « Continue on a tablet » : l'adresse qui marche, les appareils, un code d'appairage
        if (method, path) == ("GET", "/api/network/open-url"):
            return {"url": "http://golem-dry.local:8770/app/", "named": True}
        if (method, path) == ("GET", "/api/auth/devices"):
            return {"devices": [], "people": []}
        if (method, path) == ("POST", "/api/auth/pair-code"):
            return {"code": "482913", "expires_in": 600}
    return {"error": f"dry run: {method} {path} is not simulated"}
