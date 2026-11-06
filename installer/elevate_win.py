# SPDX-License-Identifier: GPL-3.0-or-later
"""L'élévation Windows en UN geste (UAC) : un script PowerShell lancé `Start-Process -Verb RunAs`, son journal lu
en direct. Un processus élevé n'a pas de sortie lisible par son parent non élevé : il écrit un fichier, que l'on
lit pendant qu'il tourne. Refuser l'autorisation rend 1223 (ERROR_CANCELLED), un échec dit — jamais un plantage.

Partagé par l'installateur (installer/platform_windows.py, run_elevated : provision/windows/install-system.ps1) et
le désinstallateur (provision/uninstall_win.py : son script généré, docs/uninstall.md §9.3). Bibliothèque standard
seulement, aucun import du dépôt : le désinstallateur le charge par son chemin depuis sa copie dans %TEMP%."""
import subprocess
import threading
import time

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DENIED = 1223                     # l'utilisateur a refusé l'invite UAC (ou personne n'a pu l'approuver)


def ps_quote(s):
    """Une chaîne PowerShell entre apostrophes (les apostrophes doublées)."""
    return "'" + str(s).replace("'", "''") + "'"


def _arg(a):
    """Start-Process JOINT ArgumentList par des espaces : un argument qui en contient (« C:\\Program Files\\… »,
    « C:\\Users\\Jean Paul\\… ») est mis entre guillemets, sinon il devient deux arguments."""
    a = str(a)
    if len(a) >= 2 and a.startswith('"') and a.endswith('"'):
        return a
    return '"%s"' % a if (" " in a or "\t" in a) else a


def command(script, args):
    """Le -Command du PowerShell NON élevé : lance `script` élevé, attend, rend son code (1223 si refusé)."""
    inner = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script] + [str(a) for a in args]
    return ("$ErrorActionPreference='Stop'; try { $p = Start-Process -FilePath powershell.exe -Verb RunAs "
            "-WindowStyle Hidden -Wait -PassThru -ArgumentList @(" + ",".join(ps_quote(_arg(a)) for a in inner) + "); "
            "exit $p.ExitCode } catch { Write-Output ('✗ Windows permission was not granted: ' + $_.Exception.Message); "
            "exit %d }" % DENIED)


def argv(script, args):
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command(script, args)]


def run(script, args, logf, emit, runner, poll=0.5):
    """Lance `script` élevé avec `args` ; chaque ligne de `logf` (que le script écrit) passe à emit(ligne) pendant
    qu'il tourne. runner(argv) lance la commande et rend son code (bloquant). Rend ce code."""
    stop = threading.Event()

    def tail():
        pos = 0
        while True:
            try:
                with open(logf, encoding="utf-8-sig", errors="replace") as f:
                    f.seek(pos)
                    for ln in f:
                        emit(ln)
                    pos = f.tell()
            except OSError:
                pass
            if stop.is_set():
                return
            time.sleep(poll)
    t = threading.Thread(target=tail, daemon=True)
    t.start()
    try:
        rc = runner(argv(script, args))
    finally:
        time.sleep(min(0.6, poll + 0.1))
        stop.set()
        t.join(timeout=3)
    return rc
