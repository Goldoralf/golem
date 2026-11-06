# SPDX-License-Identifier: GPL-3.0-or-later
"""CE QUE LE PILOTE ASIO ACCEPTE COMME BUFFER (Windows, docs/platforms.md §5.3).

2026-10-24, une UA Volt : golem proposait 64, 96, 128, 192…, le pilote n'ouvre que 32, 64, 128, 256… — 192 demandé,
128 ouvert, et rien ne disait pourquoi. L'API ASIO le sait : `getBufferSize(min, max, préféré, granularité)` ;
granularité -1 = puissances de 2 entre min et max, 0 = la seule taille préférée, n > 0 = pas de n.

⚠ Ouvrir un pilote ASIO que REAPER tient déjà peut couper le son (beaucoup sont mono-client) : le bridge n'appelle
cette sonde QUE REAPER fermé (desktop_audio), et toujours dans un PROCESSUS À PART (`python -m bridge.asio_probe
"<pilote>"`) — un pilote qui plante n'emporte pas le bridge. Sortie : une ligne JSON {min, max, preferred, granularity}
ou {error}."""
import json
import sys

# l'interface IASIO : IUnknown (0-2), init 3, getDriverName 4, getDriverVersion 5, getErrorMessage 6, start 7, stop 8,
# getChannels 9, getLatencies 10, getBufferSize 11
_INIT, _GET_BUFFER_SIZE, _RELEASE = 3, 11, 2


def sizes(info, candidates):
    """Les tailles de `candidates` que le pilote accepte, d'après getBufferSize ; None si on ne sait rien."""
    try:
        lo, hi, pref, gran = (int(info[k]) for k in ("min", "max", "preferred", "granularity"))
    except (KeyError, TypeError, ValueError):
        return None
    if lo <= 0 or hi < lo:
        return None
    if gran == -1:
        ok = lambda n: lo <= n <= hi and n & (n - 1) == 0      # noqa: E731
    elif gran == 0 or lo == hi:
        ok = lambda n: n == pref                               # noqa: E731
    else:
        ok = lambda n: lo <= n <= hi and (n - lo) % gran == 0  # noqa: E731
    return [n for n in candidates if ok(n)]


def _probe(driver):
    import ctypes
    from ctypes import POINTER, byref, c_long, c_void_p
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\ASIO\{driver}") as k:
            clsid_text = winreg.QueryValueEx(k, "CLSID")[0]
    except OSError:
        return {"error": f"ASIO driver not registered: {driver}"}

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    ole32 = ctypes.OleDLL("ole32")
    clsid = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(clsid_text), byref(clsid))
    ole32.CoInitialize(None)
    obj = c_void_p()
    try:
        # un pilote ASIO se crée avec SON CLSID comme identifiant d'interface
        ole32.CoCreateInstance(byref(clsid), None, 1, byref(clsid), byref(obj))
    except OSError as e:
        return {"error": f"could not load the ASIO driver: {e}"}
    vtbl = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))

    def method(index, *args):
        return ctypes.CFUNCTYPE(c_long, c_void_p, *args)(vtbl[index])

    try:
        hwnd = ctypes.windll.user32.GetDesktopWindow()
        if not method(_INIT, c_void_p)(obj, hwnd):
            return {"error": "the ASIO driver refused to start (is another program using it?)"}
        lo, hi, pref, gran = c_long(), c_long(), c_long(), c_long()
        err = method(_GET_BUFFER_SIZE, *(POINTER(c_long),) * 4)(obj, byref(lo), byref(hi), byref(pref), byref(gran))
        if err != 0:                                            # ASE_OK
            return {"error": f"getBufferSize failed ({err})"}
        return {"min": lo.value, "max": hi.value, "preferred": pref.value, "granularity": gran.value}
    finally:
        method(_RELEASE)(obj)


if __name__ == "__main__":
    if sys.platform != "win32" or len(sys.argv) != 2:
        print(json.dumps({"error": "usage (Windows): python -m bridge.asio_probe <driver name>"}))
        sys.exit(2)
    print(json.dumps(_probe(sys.argv[1])))
