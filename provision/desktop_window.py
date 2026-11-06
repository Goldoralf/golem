# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep REAPER's audio engine running without showing its main window on Windows.

macOS (2026-10-04, docs/platforms.md) : pas de fenêtres à énumérer par PID — `open -j` ne rend
même pas le PID de REAPER. La fermeture polie et la visibilité passent par Apple Events, adressés à
l'IDENTIFIANT de l'app (`com.cockos.reaper`), pas à son nom (« REAPER » ou « REAPER64 » selon la
version). ⚠ Le masquage passe par « System Events » : macOS demande une fois l'autorisation
d'automatisation (Réglages ▸ Confidentialité ▸ Automatisation) ; refusée, REAPER reste visible et rien
d'autre ne casse. La fermeture (« quit ») n'en demande pas : c'est REAPER lui-même qu'on adresse.
"""
import ctypes
import subprocess
import sys

if sys.platform == "win32":
    from ctypes import wintypes

MAC_BUNDLE = "com.cockos.reaper"


def _osascript(script):
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def mac_quit_reaper():
    """« Quit » poli, comme Cmd+Q : REAPER enregistre sa config et pose ses questions de sauvegarde."""
    return _osascript(f'tell application id "{MAC_BUNDLE}" to quit')


def mac_set_reaper_visible(visible):
    return _osascript('tell application "System Events" to set visible of (first process whose '
                      f'bundle identifier is "{MAC_BUNDLE}") to {"true" if visible else "false"}')


def focus_reaper_fx(allowed_pids, block_id):
    """Remonte la fenêtre flottante d'un bloc VST de cette session au-dessus du navigateur.
    macOS : REAPER est une app masquée (`open -j`) — sa fenêtre flottante ne se voit qu'une fois l'app
    ACTIVÉE (Apple Event « activate »). Sa fenêtre principale réapparaît avec : la recette dira si ça gêne."""
    if sys.platform == "darwin":
        return bool(block_id) and _osascript(f'tell application id "{MAC_BUNDLE}" to activate')
    if sys.platform != "win32" or not allowed_pids or not block_id:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    found = []
    prefix = f"golem:{block_id} - Track "

    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in allowed_pids or not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value.startswith(prefix):
            found.append(hwnd)
        return True

    user32.EnumWindows(callback(visit), 0)
    if len(found) != 1:
        return False
    hwnd = found[0]
    # Windows refuse parfois SetForegroundWindow depuis le bridge ; le passage TOPMOST
    # puis NOTOPMOST relève la fenêtre sans la laisser au-dessus de toutes les autres.
    flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)
    user32.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0, flags)
    user32.SetForegroundWindow(hwnd)
    return True


def focus_window(allowed_pids, title):
    """Ramène au premier plan la fenêtre GoleM déjà ouverte (titre exact, processus du profil dédié).
    Un second clic sur l'icône GoleM ne doit pas empiler une seconde fenêtre branchée sur le même rig."""
    if sys.platform != "win32" or not allowed_pids:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    found = []

    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in allowed_pids or not user32.IsWindowVisible(hwnd):
            return True
        text = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
        user32.GetWindowTextW(hwnd, text, len(text))
        if text.value == title:
            found.append(hwnd)
        return True

    user32.EnumWindows(callback(visit), 0)
    if not found:
        return False
    if user32.IsIconic(found[0]):
        user32.ShowWindow(found[0], 9)                     # SW_RESTORE
    user32.SetForegroundWindow(found[0])
    return True


def _reaper_main_windows(allowed_pids):
    """Windows : les fenêtres principales REAPER (titre « - REAPER v », image reaper.exe) des PID de
    cette session, en [(hwnd, pid)]. Jamais une autre instance : un REAPER ouvert à la main n'est pas à nous."""
    if sys.platform != "win32" or not allowed_pids:
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    found = []

    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in allowed_pids:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        if " - REAPER v" in title.value and _is_reaper_exe(kernel32, pid.value):
            found.append((hwnd, pid.value))
        return True

    user32.EnumWindows(callback(visit), 0)
    return found


def _is_reaper_exe(kernel32, pid):
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    process = kernel32.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return False
    try:
        path = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(path))
        return bool(kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size))
                    and path.value.rsplit("\\", 1)[-1].casefold() == "reaper.exe")
    finally:
        kernel32.CloseHandle(process)


def request_reaper_close(allowed_pids):
    """Envoie WM_CLOSE aux fenêtres REAPER de cette session, sans tuer le projet.
    macOS : « quit » par Apple Event (aucun PID enregistré : on adresse l'app de la machine)."""
    if sys.platform == "darwin":
        return 1 if mac_quit_reaper() else 0
    if sys.platform != "win32" or not allowed_pids:
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    return sum(1 for hwnd, _pid in _reaper_main_windows(allowed_pids) if user32.PostMessageW(hwnd, 0x0010, 0, 0))


# ── UN REAPER FIGÉ NE SE FERME PAS POLIMENT (2026-10-05) ──────────────────────────────────────
# Vécu : une attente active de golem_rig tenait le thread principal de REAPER à 100 %. WM_CLOSE, la
# sauvegarde par OSC et l'instantané Lua attendaient tous ce même thread : ni le ⏻, ni « Restart
# REAPER », ni le lanceur ne le fermaient, il fallait le tuer à la main à chaque fois. On ne tue
# REAPER que si son thread principal ne traite plus AUCUN message — c'est la définition Windows de
# « ne répond pas ». Une boîte « Enregistrer ? » ne compte pas : une boîte modale fait tourner la
# file de messages, la fenêtre répond, on la laisse à l'utilisateur.
def reaper_hung(allowed_pids, seconds=15.0):
    """Vrai si le thread principal d'un REAPER de cette session ne répond à aucun message pendant
    `seconds` (un rebuild légitime le tient quelques secondes : une seule sonde ne suffit pas).
    Rend dès la première réponse — quelques millisecondes pour un REAPER vivant. Hors Windows : faux."""
    import time
    windows = _reaper_main_windows(allowed_pids)
    if not windows:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageTimeoutW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
    user32.SendMessageTimeoutW.restype = ctypes.c_size_t
    deadline = time.monotonic() + seconds
    while True:
        for hwnd, _pid in windows:
            result = ctypes.c_size_t()
            if user32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002, 3000, ctypes.byref(result)):  # WM_NULL, SMTO_ABORTIFHUNG
                return False
        if time.monotonic() >= deadline:
            return True
        time.sleep(0.5)


def force_close_reaper(allowed_pids):
    """Termine les reaper.exe de cette session (et eux seuls). Réservé à un REAPER que `reaper_hung`
    a déclaré figé : le projet non enregistré est perdu, mais celui de GoleM est réécrit au rebuild."""
    if sys.platform != "win32" or not allowed_pids:
        return 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    killed = 0
    for pid in set(allowed_pids):
        if not _is_reaper_exe(kernel32, pid):
            continue
        process = kernel32.OpenProcess(0x0001, False, pid)             # PROCESS_TERMINATE
        if not process:
            continue
        try:
            if kernel32.TerminateProcess(process, 1):
                killed += 1
        finally:
            kernel32.CloseHandle(process)
    return killed


def is_reaper_main(cls_name, title):
    """La FENÊTRE PRINCIPALE de REAPER : sa classe `REAPERwnd` (stable), ou son titre « … - REAPER v… » (celui
    qu'on lisait seul jusqu'au 2026-10-11 — pendant le chargement du projet il n'est pas encore là, et REAPER restait
    visible plusieurs secondes par-dessus l'écran de chargement). Ses boîtes (« Enregistrer ? », licence) ne le sont
    pas : on ne les masque jamais."""
    return cls_name == "REAPERwnd" or " - REAPER v" in (title or "")


def set_reaper_windows_visible(allowed_pids, visible):
    """Change only owned REAPER main windows; leave dialogs actionable."""
    if sys.platform == "darwin":
        return 1 if mac_set_reaper_visible(visible) else 0
    if sys.platform != "win32":
        return 0
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (enum_callback, wintypes.LPARAM)
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.ShowWindowAsync.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    hidden = 0

    def visit(hwnd, _):
        nonlocal hidden
        if bool(user32.IsWindowVisible(hwnd)) == visible:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        if length:
            user32.GetWindowTextW(hwnd, title, length + 1)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if not is_reaper_main(cls.value, title.value):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in allowed_pids:
            return True
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return True
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            if (kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size))
                    and path.value.rsplit("\\", 1)[-1].casefold() == "reaper.exe"):
                if user32.ShowWindowAsync(hwnd, 5 if visible else 0):
                    hidden += 1
        finally:
            kernel32.CloseHandle(process)
        return True

    user32.EnumWindows(enum_callback(visit), 0)
    return hidden
