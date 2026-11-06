# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce qui ne peut se faire qu'APRÈS la fermeture du désinstallateur, sous Windows (docs/uninstall.md §9.3, §9.4) :
désinstaller le Python sur lequel il tourne (toolchain:python), et effacer sa copie dans %TEMP%
(golem-uninstaller-<hasard>) quand elle n'a pas pu partir avec lui (un processus ne peut pas effacer son répertoire
courant ; le profil du navigateur de la fenêtre reste verrouillé quelques secondes après sa fermeture).

UN « veilleur » PowerShell fait les deux : il attend que le processus du désinstallateur soit parti, lance le
désinstalleur de Python, puis efface la copie — SEULEMENT si elle porte le marqueur. Il écrit son journal dans
%TEMP%\\golem-after-uninstall-<horodatage>.log (ce qu'il a attendu, la commande, son code, le dossier de Python
parti ou non, la copie partie ou non) : l'écran Done le cite, le test en VM le lit. Son script s'efface à la fin.

POURQUOI WMI (Win32_Process.Create) et pas un enfant détaché (VM Windows, 2026-10-16 : le veilleur lancé par
subprocess.Popen(DETACHED_PROCESS) n'a JAMAIS lancé le désinstalleur de Python — aucune trace dans le journal
Application de Windows) : un enfant, même détaché, reste dans l'ARBRE et dans le JOB de son parent. `taskkill /T`
sur un ancêtre, ou un job « kill on close » (une session OpenSSH, un terminal, un lanceur) qui se ferme, l'emporte
avec lui. Un processus créé par WMI naît sous WmiPrvSE.exe : hors de notre arbre, hors de tout job, dans la session
de l'utilisateur, sans droits d'administrateur. Une tâche planifiée échapperait aussi à l'arbre, mais elle laisse une
trace à effacer (le planificateur, son dossier) si son auto-désinscription échoue, et peut être bloquée par une
stratégie de groupe : WMI ne laisse rien derrière lui.

Bibliothèque standard seulement, aucun import du dépôt : le moteur (provision/uninstall_win.py) le charge par son
chemin, le désinstallateur (installer/uninstaller.py) depuis sa copie."""
import os
import subprocess
import time

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOG_PREFIX = "golem-after-uninstall-"
COPY_PREFIX = "golem-uninstaller-"                    # installer/uninstaller.py, TMP_PREFIX
COPY_MARKER = ".golem-uninstaller"                    # installer/uninstaller.py, MARKER
WAIT_HOURS = 12                                       # un désinstallateur resté ouvert une nuit : on abandonne


def ps_quote(s):
    """Une chaîne PowerShell entre apostrophes (les apostrophes doublées)."""
    return "'" + str(s).replace("'", "''") + "'"


def _arg(a):
    """Start-Process JOINT ArgumentList par des espaces : un argument qui en contient est mis entre guillemets."""
    a = str(a)
    if len(a) >= 2 and a.startswith('"') and a.endswith('"'):
        return a
    return '"%s"' % a if (" " in a or "\t" in a) else a


def is_copy(path):
    """Une copie du désinstallateur : son nom (golem-uninstaller-*) — le marqueur, lui, est vérifié au moment
    d'effacer, par le veilleur."""
    return bool(path) and os.path.basename(os.path.normpath(path)).startswith(COPY_PREFIX)


def script(wait_pid, log, python=None, copy_dir=None):
    """Le script du veilleur (texte PowerShell, fonction PURE). python = {"exe", "args", "dir"} ou None ;
    copy_dir = la copie du désinstallateur à effacer, ou None."""
    q = ps_quote
    out = [
        "# généré par installer/after_exit_win.py (docs/uninstall.md §9.3) — jetable : il s'efface à la fin",
        "$ErrorActionPreference = 'Continue'",
        "$ProgressPreference = 'SilentlyContinue'",
        "$log = %s" % q(log),
        # le journal : ajouté ligne à ligne, UTF-8 sans BOM, jamais une erreur qui arrête le veilleur
        "function Say($m) { try { [IO.File]::AppendAllText($log, ((Get-Date -Format 's') + ' ' + $m + \"`r`n\"), "
        "(New-Object Text.UTF8Encoding($false))) } catch { } }",
        "$wait = %d" % int(wait_pid),
        "Say (\"waiter started (pid {0}), waiting for the uninstaller (pid {1}) to exit\" -f $PID, $wait)",
        "$t0 = Get-Date",
        "while (Get-Process -Id $wait -ErrorAction SilentlyContinue) {",
        "    if (((Get-Date) - $t0).TotalHours -ge %d) { Say 'gave up: the uninstaller is still running'; "
        "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue; exit 1 }" % WAIT_HOURS,
        "    Start-Sleep -Seconds 1",
        "}",
        "Say 'the uninstaller has exited'",
        # quelques secondes : le navigateur de la fenêtre lâche son profil, Windows ferme les fichiers de Python
        "Start-Sleep -Seconds 3",
    ]
    if python and python.get("exe"):
        args = "@(" + ", ".join(q(_arg(a)) for a in python.get("args") or []) + ")" if python.get("args") else "@()"
        out += [
            "# le désinstalleur de Python (la commande QUIET de sa clé « Uninstall », HKCU)",
            "$exe = %s" % q(python["exe"]),
            "$a = %s" % args,
            "$pdir = %s" % q(python.get("dir") or ""),
            "Say (\"python uninstall: {0} {1}\" -f $exe, ($a -join ' '))",
            "try {",
            "    $p = Start-Process -FilePath $exe -ArgumentList $a -Wait -PassThru -WindowStyle Hidden",
            "    Say (\"python uninstaller exit code: {0}\" -f $p.ExitCode)",
            "} catch { Say (\"python uninstaller did not start: {0}\" -f $_.Exception.Message) }",
            # jugé SUR PIÈCE : le dossier de Python parti (attente bornée, un désinstalleur Burn finit en arrière-plan)
            "if ($pdir) {",
            "    for ($i = 0; $i -lt 60 -and (Test-Path -LiteralPath $pdir); $i++) { Start-Sleep -Seconds 1 }",
            "    Say (\"python folder gone: {0} ({1})\" -f (-not (Test-Path -LiteralPath $pdir)), $pdir)",
            "}",
        ]
    if copy_dir:
        out += [
            "# les copies du désinstallateur : CELLE-CI et toute autre restée d'un essai raté (la désinstallation est",
            "# finie, aucune autre ne tourne) — SEULEMENT celles qui portent le marqueur, et le marqueur effacé EN DERNIER",
            "# (un navigateur qui tient encore son profil ne doit pas laisser un reste que plus rien ne reconnaît)",
            "$copy = %s" % q(copy_dir),
            "$mk = %s" % q(COPY_MARKER),
            "Get-ChildItem -LiteralPath (Split-Path -Parent $copy) -Directory -Filter %s -ErrorAction SilentlyContinue |"
            % q(COPY_PREFIX + "*"),
            "  Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName $mk) } | ForEach-Object {",
            "    $d = $_.FullName",
            "    # une copie dont le serveur (pid noté dans le marqueur) VIT est celle d'un autre désinstallateur : on n'y touche pas",
            "    $alive = @(Select-String -LiteralPath (Join-Path $d $mk) -Pattern '^pid=(\\d+)' -ErrorAction SilentlyContinue |",
            "        ForEach-Object { [int]$_.Matches[0].Groups[1].Value } | Where-Object { $_ -ne $wait -and (Get-Process -Id $_ -ErrorAction SilentlyContinue) })",
            "    if ($alive.Count) { Say (\"uninstaller copy in use by pid {0}, left as is ({1})\" -f ($alive -join ','), $d); return }",
            "    for ($i = 0; $i -lt 30; $i++) {",
            "        Get-ChildItem -LiteralPath $d -Force | Where-Object { $_.Name -ne $mk } |",
            "            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue",
            "        if (-not (Get-ChildItem -LiteralPath $d -Force | Where-Object { $_.Name -ne $mk })) {",
            "            Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue; break }",
            "        Start-Sleep -Seconds 1",
            "    }",
            "    Say (\"uninstaller copy removed: {0} ({1})\" -f (-not (Test-Path -LiteralPath $d)), $d)",
            "}",
            "if (-not (Test-Path -LiteralPath $copy)) { Say (\"this uninstaller's copy is gone ({0})\" -f $copy) }",
        ]
    out += ["Say 'done'",
            "Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue",
            "exit 0"]
    return "\n".join(out) + "\n"


def launcher(ps1, cwd):
    """Le -Command qui crée le veilleur PAR WMI (hors de l'arbre et du job de l'appelant) ; il écrit
    « @@WAITER <code WMI> <pid> ». La fenêtre est cachée (Win32_ProcessStartup.ShowWindow = 0, et -WindowStyle
    Hidden si la structure est refusée)."""
    return (
        "$ErrorActionPreference = 'Stop'; "
        "$ps = Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'; "
        "$cl = '\"{0}\" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"{1}\"' -f $ps, %s; "
        "$a = @{ CommandLine = $cl; CurrentDirectory = %s }; "
        "try { $a.ProcessStartupInformation = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly "
        "-Property @{ ShowWindow = [uint16]0 } } catch { }; "
        # la structure de démarrage refusée : on recrée sans elle (-WindowStyle Hidden cache quand même la console)
        "try { $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $a } "
        "catch { $a.Remove('ProcessStartupInformation'); "
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $a }; "
        "Write-Output ('@@WAITER {0} {1}' -f $r.ReturnValue, $r.ProcessId); "
        "if ($r.ReturnValue -ne 0) { exit 1 }" % (ps_quote(ps1), ps_quote(cwd)))


def _run(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def schedule(wait_pid, temp, python=None, copy_dir=None, runner=None):
    """Écrit le veilleur dans `temp` (%TEMP%) et le crée par WMI. Rend (ok, chemin du journal, message). runner(argv)
    -> (code, sortie) : les tests le remplacent. Un échec laisse un journal qui le dit."""
    stamp = "%s-%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid())
    ps1 = os.path.join(temp, LOG_PREFIX + stamp + ".ps1")
    log = os.path.join(temp, LOG_PREFIX + stamp + ".log")
    with open(ps1, "w", encoding="utf-8-sig") as f:          # le BOM : PowerShell 5.1 lirait sinon en cp1252
        f.write(script(wait_pid, log, python, copy_dir))
    rc, out = (runner or _run)(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                launcher(ps1, temp)])
    line = next((ln for ln in (out or "").splitlines() if ln.startswith("@@WAITER ")), "")
    parts = line.split()
    ok = rc == 0 and len(parts) == 3 and parts[1] == "0"
    msg = ("waiter started (pid %s)" % parts[2]) if ok else ("the waiter could not start: %s"
                                                            % ((out or "").strip()[-300:] or "exit %s" % rc))
    if not ok:
        try:
            os.unlink(ps1)
        except OSError:
            pass
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write("%s scheduled by pid %d: %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid(), msg))
    except OSError:
        pass
    return ok, log, msg
