# SPDX-License-Identifier: GPL-3.0-or-later
"""Cet ordinateur : sa fenêtre golem, son démarrage, son durcissement (docs/installer.md §4, FIXÉ 2026-10-16).

Une installation, deux usages : golem ouvre une fenêtre sur l'ordinateur (desktop) ou n'en ouvre pas (server, une
tablette est l'écran). Le bridge sait lequel MAINTENANT — pas seulement au lancement :

  · `profile` suit la fenêtre : `desktop` dès qu'une fenêtre golem (la coquille device.html, ou `golem ui`) est
    connectée au WebSocket DEPUIS CET ORDINATEUR, `server` quand la dernière se ferme (après un court délai : un ↻
    de la coquille recharge la page, il ne doit pas faire basculer le profil). Avant toute fenêtre : GOLEM_LAUNCH.
  · `can_show` : peut-on rouvrir la fenêtre sur cet ordinateur ? Windows/macOS : golem server tourne dans la
    session de l'utilisateur, oui. Linux : seulement si une session graphique de cet utilisateur est joignable — un
    golem parti au boot sans session (linger) n'a aucun écran où s'ouvrir : on le DIT, on ne promet pas.
  · le démarrage avec l'ordinateur (autostart) : les mécanismes existants, rien de réécrit —
    provision/autostart/install-autostart.sh (Linux, SANS durcissement), provision.desktop autostart (Windows/macOS).
  · le durcissement (Linux seul, geste séparé) : provision/harden.sh, le mot de passe par un askpass qui le lit dans
    l'ENVIRONNEMENT du job — jamais écrit sur le disque, jamais au journal, oublié à la fin (règle de l'installateur).

GOLEM_MACHINE_DRY=1 : chaque geste est SIMULÉ (rien ne s'ouvre, rien ne s'installe) — tests, captures, démonstration.
"""
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from . import config as C
from .golog import get as _get_log

log = _get_log("machine")

GRACE_S = 3.0                    # une fenêtre qui se recharge ne fait pas basculer le profil
CLOSE_STOP_S = 8.0               # la croix de la fenêtre arrête golem desktop : après ce délai, fenêtre vraiment partie
_LOCK = threading.Lock()
_W = {"open": 0, "last_close": None, "seen": False, "detached": False}


def dry():
    return os.environ.get("GOLEM_MACHINE_DRY") == "1"


# ── la fenêtre et le profil ──────────────────────────────────────────────────────────────────────
def window_opened():
    with _LOCK:
        _W["open"] += 1
        _W["seen"] = True
        _W["last_close"] = None
        _W["detached"] = False                   # une fenêtre rouverte : sa croix arrête de nouveau golem


def window_closed():
    with _LOCK:
        _W["open"] = max(0, _W["open"] - 1)
        if _W["open"] == 0:
            _W["last_close"] = time.monotonic()


def windows():
    return _W["open"]


def window_detached():
    """La fenêtre se ferme EXPRÈS sans arrêter golem : « Continue on a tablet » (/api/ui/quit sans stop)."""
    with _LOCK:
        _W["detached"] = True


def close_stops_golem(now=None):
    """LA CROIX ARRÊTE GOLEM DESKTOP (décision du 2026-11-08, docs/ui-architecture.md §5). Fermer un logiciel par
    sa croix le ferme : la fenêtre de golem fermée laissait REAPER et le bridge tourner sans rien à l'écran. Vrai
    quand golem a été lancé AVEC fenêtre (GOLEM_LAUNCH=desktop — Windows, macOS et Linux ; pas `golem server`, ni
    l'autostart d'une boîte dédiée, qui lance `golem server`), que la dernière fenêtre de cet ordinateur est fermée
    depuis CLOSE_STOP_S (un rechargement de page se reconnecte avant) et qu'elle ne l'a pas été exprès pour passer
    sur une tablette. ⚠ Linux : codé le 2026-11-08 sous Windows, À VÉRIFIER sur le rack."""
    if dry() or os.environ.get("GOLEM_LAUNCH") != "desktop":
        return False
    with _LOCK:
        if not _W["seen"] or _W["open"] > 0 or _W["detached"] or _W["last_close"] is None:
            return False
        now = time.monotonic() if now is None else now
        return now - _W["last_close"] >= CLOSE_STOP_S


def profile(now=None):
    """`desktop` | `server` — ce que golem est MAINTENANT (docs/installer.md §4)."""
    with _LOCK:
        if _W["open"] > 0:
            return "desktop"
        if _W["last_close"] is not None:
            now = time.monotonic() if now is None else now
            return "server" if now - _W["last_close"] >= GRACE_S else "desktop"
    return "server" if os.environ.get("GOLEM_LAUNCH") == "server" else "desktop"


def is_window_ws(shell, client_host):
    """Une connexion WebSocket est-elle une FENÊTRE golem sur cet ordinateur ? La page le dit (`?shell=`), et
    seul l'ordinateur lui-même compte : une tablette qui prétendrait être la fenêtre ne change pas le profil."""
    from .auth import _is_local
    return shell in ("device", "ui") and _is_local(client_host or "")


# ── peut-on montrer golem sur cet ordinateur ? ───────────────────────────────────────────────────
NO_SESSION = "no one is signed in on this computer: there is no screen to open golem on"
_CACHE = {"at": 0.0, "v": None}


def _xvfb():
    return os.environ.get("GOLEM_XVFB_DISPLAY", ":99")


def _usable_display(env):
    """Le sous-environnement graphique utilisable de `env` (WAYLAND_DISPLAY ou DISPLAY LOCAL dont la socket existe),
    ou None. L'écran virtuel de REAPER (Xvfb) n'est pas un écran : personne ne le regarde."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    rt = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    keep = {k: env[k] for k in ("XDG_RUNTIME_DIR", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE")
            if env.get(k)}
    wl = env.get("WAYLAND_DISPLAY")
    if wl:
        path = wl if os.path.isabs(wl) else os.path.join(rt, wl)
        if os.path.exists(path):
            out = {**keep, "WAYLAND_DISPLAY": wl, "XDG_RUNTIME_DIR": rt}
            if env.get("DISPLAY") and env["DISPLAY"] != _xvfb():
                out["DISPLAY"] = env["DISPLAY"]          # XWayland : Chrome s'y rabat si besoin
            return out
    d = env.get("DISPLAY") or ""
    if d and d != _xvfb():
        host, _, num = d.partition(":")
        num = num.split(".")[0]
        # seulement un écran LOCAL : `localhost:10` (ssh -X) affiche ailleurs, pas sur cet ordinateur
        if host in ("", "unix") and num.isdigit() and os.path.exists(f"/tmp/.X11-unix/X{num}"):
            return {**keep, "DISPLAY": d}
    return None


def _systemd_user_env():
    """L'environnement du gestionnaire systemd de l'utilisateur : une session graphique y publie DISPLAY et
    WAYLAND_DISPLAY (GNOME, KDE) — c'est par là qu'un golem lancé AVANT la connexion trouve l'écran d'après."""
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True,
                             timeout=3, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    env = {}
    for line in out.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            env[k] = v
    return env


def _graphical_session():
    """True / False si logind sait dire si l'utilisateur a une session GRAPHIQUE ; None s'il ne sait pas."""
    if not shutil.which("loginctl"):
        return None
    try:
        r = subprocess.run(["loginctl", "show-user", str(os.getuid()), "--property=Display", "--value"],
                           capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return False          # « user not logged in » : linger sans session
    return bool(r.stdout.strip())


def linux_display_env():
    """L'environnement graphique où ouvrir la fenêtre, ou None (aucune session graphique joignable)."""
    if _graphical_session() is False:
        return None
    return _usable_display(dict(os.environ)) or _usable_display(_systemd_user_env())


def _can_show_now():
    if sys.platform == "win32":
        # un service (session 0) n'a pas de bureau ; un golem server lancé par l'utilisateur en a un
        if (os.environ.get("SESSIONNAME") or "").lower() == "services" or \
                (os.environ.get("USERNAME") or "").upper() == "SYSTEM":
            return {"ok": False, "why": NO_SESSION}
        return {"ok": True, "why": None}
    if sys.platform == "darwin":
        return {"ok": True, "why": None}
    return {"ok": True, "why": None} if linux_display_env() else {"ok": False, "why": NO_SESSION}


def can_show(max_age=5.0):
    """{ok, why} — mis en cache quelques secondes : l'état part à chaque diffusion WebSocket."""
    now = time.monotonic()
    # `>=` et pas `>` : sous Windows, time.monotonic() avance par pas de ~15 ms ; deux appels dans le même pas avec
    # max_age=0 rendaient la valeur EN CACHE (tests/test_machine_switch.py), jamais la fraîche
    if _CACHE["v"] is None or now - _CACHE["at"] >= max_age:
        try:
            v = _can_show_now()
        except Exception as e:                    # ne jamais casser l'état pour une sonde
            v = {"ok": False, "why": f"cannot tell whether this computer has a screen ({e})"}
        _CACHE.update(at=now, v=v)
    return _CACHE["v"]


def ui_state():
    """La part de l'état (state.snapshot) : `profile` et `ui`."""
    return {"profile": profile(), "ui": {"windows": windows(), "can_show": can_show()}}


def show(port=8770):
    """Rouvre la fenêtre golem sur l'ordinateur — le son ne s'arrête pas. Rend {ok} ou {ok: False, why}."""
    cs = can_show(max_age=0)
    if not cs["ok"]:
        return {"ok": False, "why": cs["why"]}
    if dry():
        log.info("(dry) la fenêtre golem s'ouvrirait sur cet ordinateur")
        return {"ok": True, "dry": True}
    try:
        if sys.platform in ("win32", "darwin"):
            # la fenêtre du lanceur, taille et zoom retenus (provision/desktop.py open_window) — pas une copie
            from provision import desktop
            desktop.open_window(port)
        else:
            env = {**os.environ, **(linux_display_env() or {})}
            # `golem window` : la partie fenêtre de `golem desktop` (provision/golem), sans relancer la pile
            subprocess.Popen([os.path.join(C.ROOT, "provision", "golem"), "window"], cwd=C.ROOT, env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    except Exception as e:
        log.warning(f"fenêtre non ouverte : {e}")
        return {"ok": False, "why": f"the window did not open: {e}"}
    log.info("fenêtre golem ouverte sur cet ordinateur (Settings ▸ System ▸ Dashboard)")
    return {"ok": True}


# ── démarrer avec l'ordinateur (autostart) ───────────────────────────────────────────────────────
# la phrase de l'interrupteur (une ligne dans Settings ▸ System ▸ Dashboard) ; Windows/macOS : l'ouverture de session automatique,
# que golem ne règle pas à la place de l'utilisateur (il faudrait son mot de passe)
WIN_HINT = ("Starts golem server when you sign in. To start on its own, turn on automatic sign-in "
            "(Windows Settings ▸ Accounts ▸ Sign-in options).")
MAC_HINT = ("Starts golem server when you log in. To start on its own, turn on automatic login "
            "(System Settings ▸ Users & Groups).")
LINUX_HINT = "Starts golem server at boot, with no sign-in and no window: a tablet or a phone is the screen."
_DRY_AUTOSTART = {"on": False}


def _unit_path():
    return os.path.join(os.path.expanduser("~"), ".config", "systemd", "user", "golem-server.service")


def autostart_status():
    if dry():
        on = _DRY_AUTOSTART["on"]
    elif sys.platform in ("win32", "darwin"):
        from provision import desktop
        on = (desktop._startup_link() if sys.platform == "win32" else desktop._launch_agent()).exists()
    else:
        on = False
        if os.path.isfile(_unit_path()):
            try:
                r = subprocess.run(["systemctl", "--user", "is-enabled", "golem-server.service"],
                                   capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
                on = r.stdout.strip() == "enabled"
            except (OSError, subprocess.SubprocessError):
                on = True                          # l'unité est là : on ne sait pas mieux
    hint = WIN_HINT if sys.platform == "win32" else MAC_HINT if sys.platform == "darwin" else LINUX_HINT
    out = {"on": bool(on), "platform": sys.platform, "hint": hint}
    if sys.platform.startswith("linux"):
        user = os.environ.get("USER") or ""
        out["linger"] = bool(user) and os.path.exists(f"/var/lib/systemd/linger/{user}")
    return out


def _tail(text, n=12):
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-n:]


def autostart_set(on):
    """Le MÊME mécanisme que `golem autostart on|off` / `provision.desktop autostart on|off` ; le reçu d'installation
    note ce qu'il pose (install-autostart.sh : unité et linger d'avant ; desktop.autostart : le lien de démarrage)."""
    on = bool(on)
    if dry():
        _DRY_AUTOSTART["on"] = on
        log.info(f"(dry) autostart {'on' if on else 'off'}")
        return {**autostart_status(), "ok": True, "dry": True}
    if sys.platform in ("win32", "darwin"):
        from provision import desktop
        try:
            msg = desktop.autostart("on" if on else "off")
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            return {**autostart_status(), "ok": False, "why": str(e)}
        return {**autostart_status(), "ok": True, "message": msg}
    script = os.path.join(C.ROOT, "provision", "autostart", "install-autostart.sh")
    argv = [script] + ([] if on else ["--off"])
    try:
        r = subprocess.run(argv, cwd=C.ROOT, capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as e:
        return {**autostart_status(), "ok": False, "why": str(e)}
    out = _tail(r.stdout + "\n" + r.stderr)
    log.info(f"autostart {'on' if on else 'off'} : code {r.returncode}")
    if r.returncode != 0:
        why = next((ln for ln in reversed(out) if ln.lstrip().startswith(("✗", "⚠"))), None) or \
            (out[-1] if out else f"exit {r.returncode}")
        return {**autostart_status(), "ok": False, "why": why.strip(), "output": out}
    return {**autostart_status(), "ok": True, "output": out}


# ── verrouiller cette machine (Linux) ────────────────────────────────────────────────────────────
# Les fichiers que harden.sh pose (lisibles par tous) : leur présence dit que le durcissement est appliqué.
HARDEN_MARKERS = ("/etc/udev/rules.d/90-golem-usb-power.rules", "/etc/sysctl.d/90-golem-port80.conf")
_H = {"phase": "idle", "error": None, "log": [], "at": None}
_DRY_HARDEN = {"applied": False}


def _receipt_says_hardened():
    try:
        from . import install_receipt
        m = install_receipt._usable()
        if m is None:
            return False
        data = m.load() if hasattr(m, "load") else None
        return any(i.get("group") == "dedicated" for i in ((data or {}).get("items") or []))
    except Exception:
        return False


def harden_status():
    avail = sys.platform.startswith("linux")
    if dry():
        applied = _DRY_HARDEN["applied"]
    else:
        applied = avail and (any(os.path.exists(p) for p in HARDEN_MARKERS) or _receipt_says_hardened())
    return {"available": avail, "applied": bool(applied), "phase": _H["phase"], "error": _H["error"],
            "log": _H["log"][-12:]}


def sudo_check(password):
    """Le mot de passe est-il bon ? `sudo -S` le lit sur l'entrée standard — jamais sur la ligne de commande."""
    try:
        r = subprocess.run(["sudo", "-k", "-S", "-p", "", "-v"], input=password + "\n", capture_output=True,
                           text=True, timeout=20, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, None
    return False, "wrong password" if "incorrect" in (r.stderr or "").lower() or "sorry" in (r.stderr or "").lower() \
        else ((r.stderr or "").strip().splitlines() or ["sudo refused"])[-1]


def _askpass_dir():
    """Un helper askpass qui imprime $GOLEM_SUDO_PW (installer/platform_linux._askpass) : le mot de passe vit dans
    l'ENVIRONNEMENT du job, le helper ne le contient jamais. Dossier 0700, retiré à la fin du job."""
    d = tempfile.mkdtemp(prefix="golem-askpass-")
    os.chmod(d, 0o700)
    p = os.path.join(d, "askpass")
    with open(p, "w") as f:
        f.write('#!/bin/sh\nprintf "%s\\n" "$GOLEM_SUDO_PW"\n')
    os.chmod(p, 0o700)
    return d, p


def _harden_job(password):
    d, res = None, ("fail", "harden.sh did not run")
    try:
        d, helper = _askpass_dir()
        env = {**os.environ, "SUDO_ASKPASS": helper, "GOLEM_SUDO_PW": password,
               "GOLEM_KIOSK_OK": "1", "DEBIAN_FRONTEND": "noninteractive"}
        password = None                                    # plus aucune référence hors de l'environnement du job
        p = subprocess.Popen([os.path.join(C.ROOT, "provision", "harden.sh")], cwd=C.ROOT, env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", start_new_session=True)
        env = None
        for ln in p.stdout:
            ln = ln.rstrip("\n")
            if ln.strip():
                _H["log"] = (_H["log"] + [ln])[-200:]
        rc = p.wait()
        res = ("done", None) if rc == 0 else ("fail", f"harden.sh failed (exit {rc})")
        log.info(f"durcissement : code {rc}")
    except Exception as e:
        res = ("fail", str(e))
        log.warning(f"durcissement : {e}")
    finally:
        if d:
            shutil.rmtree(d, ignore_errors=True)      # le helper part AVANT que le job se dise fini
        _H["phase"], _H["error"] = res
        _H["at"] = time.time()


def harden_start(password):
    """Vérifie le mot de passe, puis lance harden.sh en tâche de fond. Rend {ok, …} tout de suite."""
    if not sys.platform.startswith("linux"):
        return {"ok": False, "why": "locking down the machine is offered on Linux only"}
    if _H["phase"] == "running":
        return {"ok": False, "why": "already running", **harden_status()}
    password = str(password or "")
    if not password:
        return {"ok": False, "why": "type your password"}
    if dry():
        _DRY_HARDEN["applied"] = True
        _H.update(phase="done", error=None, log=["(dry) firewall, mDNS, frozen updates, USB autosuspend off, CPU governor"])
        return {"ok": True, "dry": True, **harden_status()}
    ok, err = sudo_check(password)
    if not ok:
        return {"ok": False, "why": err or "wrong password"}
    _H.update(phase="running", error=None, log=[])
    threading.Thread(target=_harden_job, args=(password,), name="golem-harden", daemon=True).start()
    password = None
    return {"ok": True, **harden_status()}


def _reset_for_tests():
    with contextlib.suppress(Exception):
        _W.update(open=0, last_close=None, seen=False, detached=False)
        _CACHE.update(at=0.0, v=None)
        _H.update(phase="idle", error=None, log=[], at=None)
        _DRY_AUTOSTART["on"] = False
        _DRY_HARDEN["applied"] = False
