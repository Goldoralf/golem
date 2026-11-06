# SPDX-License-Identifier: GPL-3.0-or-later
"""La fenêtre d'un plugin, montrée DANS golem (Linux) — docs/plugin-window.md.

Sous Linux, REAPER dessine sur un écran X virtuel (Xvfb, provision/start.sh) : la fenêtre de Vital y existe, mais
personne ne la voit, et une fenêtre X ne change pas d'écran. On la FILME (ffmpeg x11grab, un flux MJPEG qu'un <img>
du navigateur lit tel quel) et on y REJOUE les gestes du musicien (extension XTEST : mouvements, clics, molette).
Ça marche aussi depuis une tablette — c'est la raison de ce chemin plutôt que de mettre REAPER à l'écran.

Aucune dépendance de plus : ffmpeg est déjà là (séparation, rendus), libX11/libXtst viennent avec Xvfb.
"""
import ctypes
import ctypes.util
import os
import subprocess
import threading
import time

_X = _XT = None
_lock = threading.Lock()
_dpy = {}                                   # nom d'écran -> Display* (connexion des gestes, réutilisée)


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("c_class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


def _libs():
    global _X, _XT
    if _X is None:
        _X = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        _XT = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        _X.XOpenDisplay.restype = ctypes.c_void_p
        _X.XOpenDisplay.argtypes = [ctypes.c_char_p]
        _X.XDefaultRootWindow.restype = ctypes.c_ulong
        _X.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        _X.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                  ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                                  ctypes.POINTER(ctypes.c_uint)]
        _X.XFetchName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_char_p)]
        _X.XFree.argtypes = [ctypes.c_void_p]
        _X.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XWindowAttributes)]
        _X.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                                             ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                             ctypes.POINTER(ctypes.c_ulong)]
        _X.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
        _X.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        _X.XFlush.argtypes = [ctypes.c_void_p]
        _XT.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        _XT.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    return _X, _XT


def reaper_display():
    """(DISPLAY, XAUTHORITY) du REAPER qui tourne — lus dans son environnement, jamais devinés : `--dev` le met sur
    l'écran réel, le défaut sur Xvfb :99. None si REAPER ne tourne pas (ou pas sous X)."""
    try:
        out = subprocess.run(["pgrep", "-x", "reaper"], capture_output=True, text=True, timeout=2).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    for pid in out:
        try:
            env = dict(kv.split("=", 1) for kv in open(f"/proc/{pid}/environ", "rb").read().decode(
                errors="replace").split("\0") if "=" in kv)
        except OSError:
            continue
        if env.get("DISPLAY"):
            return env["DISPLAY"], env.get("XAUTHORITY", "")
    return None


def _open(name, xauth=""):
    X, _ = _libs()
    if name not in _dpy:
        if xauth:
            os.environ.setdefault("XAUTHORITY", xauth)
        d = X.XOpenDisplay(name.encode())
        if not d:
            raise OSError(f"cannot open display {name}")
        _dpy[name] = d
    return _dpy[name]


def _find(d, block):
    """La fenêtre flottante du bloc : REAPER la titre « golem:<id> - Track N … » (renamed_name du FX)."""
    X, _ = _libs()
    want = f"golem:{block} ".encode()
    stack = [X.XDefaultRootWindow(d)]
    while stack:
        w = stack.pop()
        name = ctypes.c_char_p()
        if X.XFetchName(d, w, ctypes.byref(name)) and name.value:
            hit = name.value.startswith(want)
            X.XFree(name)
            if hit:
                return w
        root, parent = ctypes.c_ulong(), ctypes.c_ulong()
        kids, n = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if X.XQueryTree(d, w, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(n)):
            stack.extend(kids[i] for i in range(n.value))
            if kids:
                X.XFree(kids)
    return None


def _geom(d, w):
    X, _ = _libs()
    a = _XWindowAttributes()
    if not X.XGetWindowAttributes(d, w, ctypes.byref(a)) or a.map_state != 2:      # 2 = IsViewable
        return None
    x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
    X.XTranslateCoordinates(d, w, X.XDefaultRootWindow(d), 0, 0, ctypes.byref(x), ctypes.byref(y), ctypes.byref(child))
    return {"x": x.value, "y": y.value, "w": a.width, "h": a.height}


def _content(d, w):
    """Le plugin SANS le bandeau de REAPER : la fenêtre flottante porte en haut 28 px de REAPER (menu de presets
    « No preset », Param, 2 out, UI) — un menu qui ne dit rien de ce que golem a chargé (il pose l'état directement)
    et un bouton « UI » qui remplacerait Vital par la grille de paramètres. On filme le plus grand enfant visible."""
    X, _ = _libs()
    root, parent = ctypes.c_ulong(), ctypes.c_ulong()
    kids, n = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
    best, area = None, 0
    if X.XQueryTree(d, w, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(kids), ctypes.byref(n)):
        for i in range(n.value):
            g = _geom(d, kids[i])
            if g and g["w"] * g["h"] > area:
                best, area = (kids[i], g), g["w"] * g["h"]
        if kids:
            X.XFree(kids)
    return best


def window(block):
    """{display, x, y, w, h, win} de la zone du plugin dans la fenêtre visible du bloc (`top` = la fenêtre REAPER)."""
    disp = reaper_display()
    if not disp:
        return None
    with _lock:
        d = _open(*disp)
        w = _find(d, block)
        g = _geom(d, w) if w else None
        inner = _content(d, w) if g else None
    if not g:
        return None
    if inner and inner[1]["w"] * inner[1]["h"] >= 0.5 * g["w"] * g["h"]:
        g = inner[1]
    return dict(g, display=disp[0], win=w)


def place(block, timeout=4.0):
    """Attend la fenêtre du bloc, la pose en haut à gauche de l'écran virtuel et au premier plan. REAPER l'ouvre là
    où il l'a laissée la dernière fois — mesuré 2026-10-14 : 1475×892 à +695+90, qui DÉBORDE d'un écran de 1920 de
    large, et x11grab refuse de filmer hors de l'écran. Rend la géométrie, ou None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        g = window(block)
        if g:
            X, _ = _libs()
            with _lock:
                d = _open(g["display"])
                if g["x"] or g["y"]:
                    X.XMoveWindow(d, g["win"], 0, 0)
                X.XRaiseWindow(d, g["win"])
                X.XFlush(d)
            time.sleep(0.15)
            return window(block) or g
        time.sleep(0.1)
    return None


def gesture(block, ev, x, y, dy=0):
    """Rejoue un geste à (x, y) ∈ [0,1]² de la fenêtre : move | down | up | wheel (dy > 0 = vers le bas)."""
    g = window(block)
    if not g:
        return False
    X, XT = _libs()
    px = g["x"] + int(max(0.0, min(1.0, x)) * (g["w"] - 1))
    py = g["y"] + int(max(0.0, min(1.0, y)) * (g["h"] - 1))
    with _lock:
        d = _open(g["display"])
        XT.XTestFakeMotionEvent(d, -1, px, py, 0)
        if ev == "down":
            XT.XTestFakeButtonEvent(d, 1, 1, 0)
        elif ev == "up":
            XT.XTestFakeButtonEvent(d, 1, 0, 0)
        elif ev == "wheel":
            b = 5 if dy > 0 else 4
            for _ in range(min(5, max(1, int(abs(dy) / 40) or 1))):
                XT.XTestFakeButtonEvent(d, b, 1, 0)
                XT.XTestFakeButtonEvent(d, b, 0, 0)
        X.XFlush(d)
    return True


def frames(block, fps=15, width=1024, stop=None):
    """Flux MJPEG de la fenêtre (générateur de JPEG). S'arrête quand la fenêtre disparaît ou bouge (le client
    relance) ou quand `stop` (threading.Event) est posé — le client parti. Réduit à `width` px : une tablette en Wi-Fi n'a que faire des 1475 px d'origine."""
    g = window(block)
    if not g:
        return
    env = dict(os.environ, DISPLAY=g["display"])
    cmd = ["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps),
           "-video_size", f"{g['w']}x{g['h']}", "-i", f"{g['display']}+{g['x']},{g['y']}",
           "-vf", f"scale={min(width, g['w'])}:-2", "-f", "mjpeg", "-q:v", "6", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    buf, last_check = b"", time.monotonic()
    try:
        while not (stop and stop.is_set()):
            chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
            if not chunk:
                return
            buf += chunk
            while True:
                i = buf.find(b"\xff\xd8")
                j = buf.find(b"\xff\xd9", i + 2) if i >= 0 else -1
                if i < 0 or j < 0:
                    break
                yield buf[i:j + 2]
                buf = buf[j + 2:]
            if time.monotonic() - last_check > 1.0:
                last_check = time.monotonic()
                now = window(block)
                if not now or (now["x"], now["y"], now["w"], now["h"]) != (g["x"], g["y"], g["w"], g["h"]):
                    return
    finally:
        proc.kill()
        proc.wait(timeout=2)
