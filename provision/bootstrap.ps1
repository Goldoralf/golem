# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM - le bootstrap Windows en une ligne (docs/installer.md, section 8), pendant de bootstrap.sh :
#     irm https://raw.githubusercontent.com/Goldoralf/golem/main/provision/bootstrap.ps1 | iex
#     (ou : powershell -File provision\bootstrap.ps1 - get.golem.fm/win n'a pas de DNS, verifie le 2026-11-09)
#
# Il ne fait QUE trois choses, SANS droits d'administrateur :
#   1. verifier le strict minimum (Windows 10 2004+ ou 11, x64) - le reste est verifie A L'ECRAN ;
#   2. trouver Python 3.10+ ou poser Python 3.12 POUR CET UTILISATEUR (empreinte et signature verifiees,
#      dans %LOCALAPPDATA%\Programs\Python, sans toucher au PATH) ;
#   3. recuperer GoleM a la derniere release dans %LOCALAPPDATA%\golem-installer, et ouvrir
#      l'installateur graphique (installer/server.py) dans le navigateur.
# Rien n'est installe dans Program Files avant que l'utilisateur ait vu les ecrans et approuve UAC.
#
# Variables : GOLEM_REF (tag)  GOLEM_REPO (defaut GitHub)  GOLEM_SRC (un depot deja pose : on s'en
# sert tel quel)  GOLEM_INSTALLER_DRY=1 (les ecrans sans rien installer).
#  Ecrit pour tourner par `irm | iex` : pas de $PSScriptRoot, pas de param(), tout par variables.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = if ($env:GOLEM_REPO) { $env:GOLEM_REPO } else { 'https://github.com/Goldoralf/golem' }
$cache = Join-Path $env:LOCALAPPDATA 'golem-installer'
# COPIE de provision/windows/pins.json (" python ") : ce script tourne avant que le depot soit la.
# tests/test_installer_windows.py verifie que les deux disent la meme chose.
$pyVersion = '3.12.10'
$pyUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$pySha = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'

function Say($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "x $m" -ForegroundColor Red; exit 1 }

#  1. le strict minimum 
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    Die 'GoleM needs 64-bit Windows on an x64 processor (the neural plugins ship for x64 only).'
}
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 19041) { Die "GoleM needs Windows 10 version 2004 or later (this is build $build)." }

#  2. Python 
# le cache de pip (%LOCALAPPDATA%\pip) existait-il AVANT golem ? Note des maintenant, avant tout pip (celui du venv,
# au setup, le cree) : la desinstallation ne propose de l'effacer que s'il est ne de golem (prior.pip_cache_existed)
$pipCacheExisted = [bool](Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'pip'))
function Find-Python {
    $cands = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe')
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    # le `python.exe` de WindowsApps est un raccourci vers le Store, pas un Python : on l'ecarte
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' } | Select-Object -First 1
    if ($onPath) {
        $v = & $onPath.Source -c 'import sys; print(sys.version_info >= (3, 10))' 2>$null
        if ($v -eq 'True') { return $onPath.Source }
    }
    return $null
}
$python = Find-Python
$pythonByGolem = $false
if (-not $python) {
    Say "installing Python $pyVersion for you only (no administrator rights needed)"
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $pyExe = Join-Path $cache "python-$pyVersion-amd64.exe"
    curl.exe -fL --retry 3 -sS -o $pyExe $pyUrl
    if ($LASTEXITCODE -ne 0) { Die "download failed: $pyUrl" }
    if ((Get-FileHash $pyExe -Algorithm SHA256).Hash.ToLower() -ne $pySha) {
        Remove-Item -Force $pyExe; Die 'the Python installer does not match its pinned checksum - removed, nothing installed.'
    }
    $sig = Get-AuthenticodeSignature $pyExe
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike '*Python Software Foundation*') {
        Remove-Item -Force $pyExe; Die "the Python installer is not signed by the Python Software Foundation ($($sig.Status))."
    }
    $p = Start-Process $pyExe -ArgumentList @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0',
                                               'Include_test=0', 'Shortcuts=0', 'AssociateFiles=0') -Wait -PassThru
    if ($p.ExitCode -ne 0) { Die "the Python installer stopped with code $($p.ExitCode)." }
    $python = Find-Python
    if (-not $python) { Die 'Python was installed but cannot be found.' }
    $pythonByGolem = $true
}
Say "Python: $python"

#  2 bis. le recu d'installation (docs/uninstall.md, section 9.2) : prior.python
# Le depot n'existe pas encore : pas de provision/receipt.py a appeler. On depose un FRAGMENT a cote du recu,
# <recu>.pending-bootstrap.json, que receipt.py verse au premier passage (l'etape " source " de l'installateur,
# set-root) - le premier gagne. installed_by_golem n'est vrai QUE si ce script vient de poser Python lui-meme.
# Un fragment deja la n'est jamais remplace : relance apres un Python pose par nous, il dirait " deja la ".
# Un echec ici ne casse jamais l'installation.
try {
    $receipt = if ($env:GOLEM_RECEIPT) { $env:GOLEM_RECEIPT } else { Join-Path $env:LOCALAPPDATA 'GoleM\install-receipt.json' }
    $frag = "$receipt.pending-bootstrap.json"
    if (-not (Test-Path $frag)) {
        $pyVer = (& $python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null | Select-Object -First 1)
        $prior = @{ 'python.installed_by_golem' = $pythonByGolem; 'python.version' = [string]$pyVer;
                    'python.path' = [string]$python; 'pip_cache_existed' = $pipCacheExisted }
        # pose par nous : SA commande de desinstallation, celle du BUNDLE (cle HKCU " Python 3.12.10 (64-bit) ",
        # QuietUninstallString " "...\Package Cache\{guid}\python-3.12.10-amd64.exe" /uninstall /quiet ") - jamais
        # un de ses MSI (" Core Interpreter ", SystemComponent=1)
        if ($pythonByGolem) {
            $k = Get-ChildItem -LiteralPath 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue |
                ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue } |
                Where-Object { $_.DisplayName -like "Python $pyVersion (*-bit)" -and $_.QuietUninstallString -and $_.SystemComponent -ne 1 } |
                Select-Object -First 1
            if ($k) { $prior['python.uninstall'] = [string]$k.QuietUninstallString }
        }
        $doc = @{ format = 1; by = 'provision/bootstrap.ps1'; items = @(); append = @{}; prior = $prior }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $frag) | Out-Null
        # sans BOM : Set-Content -Encoding UTF8 de PowerShell 5.1 en poserait un
        [IO.File]::WriteAllText($frag, ($doc | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    }
} catch {
    Write-Host "! install receipt not updated ($($_.Exception.Message))" -ForegroundColor Yellow
}

#  3. GoleM a la derniere release 
if ($env:GOLEM_SRC -and (Test-Path (Join-Path $env:GOLEM_SRC 'provision'))) {
    $src = $env:GOLEM_SRC
    Say "using $src"
} else {
    $ref = $env:GOLEM_REF
    $api = 'https://api.github.com/repos/' + ($repo -replace '^https://github.com/', '')
    if (-not $ref) { try { $ref = (Invoke-RestMethod "$api/releases/latest").tag_name } catch { } }
    # le PLUS RECENT par numero de version, pas le premier que l'API rend : v2.10.0 passe apres v2.9.0 (fichier ASCII : PowerShell 5)
    if (-not $ref) { try { $ref = ((Invoke-RestMethod "$api/tags") | Where-Object { $_.name -match '^v\d+(\.\d+)+$' } |
        Sort-Object { [version]$_.name.Substring(1) } -Descending | Select-Object -First 1).name } catch { } }
    if (-not $ref) { $ref = 'main' }
    Say "GoleM $ref"
    $src = Join-Path $cache "golem-$ref"
    if (-not (Test-Path (Join-Path $src 'provision'))) {
        New-Item -ItemType Directory -Force -Path $cache | Out-Null
        $zip = "$src.zip"
        curl.exe -fL --retry 3 -sS -o $zip "$repo/archive/refs/tags/$ref.zip"
        if ($LASTEXITCODE -ne 0) { curl.exe -fL --retry 3 -sS -o $zip "$repo/archive/refs/heads/$ref.zip" }
        if ($LASTEXITCODE -ne 0) { Die "download failed ($repo @ $ref)" }
        $tmp = "$src.tmp"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive $zip -DestinationPath $tmp
        # l'archive GitHub range tout dans UN dossier " golem-<ref> " : on le remonte
        $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
        if (Test-Path $src) { Remove-Item -Recurse -Force $src }
        Move-Item $inner.FullName $src
        Remove-Item -Recurse -Force $tmp, $zip
    }
}

#  4. l'installateur graphique 
$env:PYTHONUTF8 = '1'
$argsList = @("$src\installer\server.py", '--src', $src, '--open')
if ($env:GOLEM_INSTALLER_DRY -eq '1') { $argsList += '--dry' }
# Une VRAIE application : l'installateur s'ouvre dans sa propre fenetre (Chrome/Edge --app) et vit
# autant qu'elle. Il tourne sous pythonw.exe, sans console : celle-ci peut se fermer. Sans pythonw
# (Python exotique), l'ancien chemin : le serveur dans cette console, qu'il faut garder ouverte.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (Test-Path $pythonw) {
    Say 'the GoleM installer opens in its own window'
    Start-Process -FilePath $pythonw -ArgumentList ($argsList | ForEach-Object { '"' + $_ + '"' }) -WorkingDirectory $src
} else {
    Say 'opening the installer in your browser - keep this window open until the install is done'
    & $python @argsList
}
