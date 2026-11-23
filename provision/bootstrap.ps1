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
# CLE(S) DE RELEASE (docs/release-signing.md) - COPIE de GOLEM_RELEASE_SIGNERS de provision/bootstrap.sh, au format de
# provision/release-signers (tests/test_installer_windows.py verifie que les deux scripts disent la meme chose).
# Renseignee : la release telechargee doit porter une liste de fichiers SIGNEE par cette cle, et lui correspondre
# fichier pour fichier (Verify-Release). Elle vit ICI, dans le script servi par la ligne d'installation, et pas dans
# l'archive telechargee : une release piegee ne choisit pas la cle qui la verifie. Vide = pas de verification.
$releaseSigners = 'golem namespaces="git" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEnQjtX6NBOBAr+L3HV0C8Q8LTAa/T7XvA4mQ3TCo47I golem release 2'
# COPIE de provision/windows/pins.json (" python ") : ce script tourne avant que le depot soit la.
# tests/test_installer_windows.py verifie que les deux disent la meme chose.
$pyVersion = '3.12.10'
$pyUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$pySha = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb'

function Say($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Die($m) { Write-Host "x $m" -ForegroundColor Red; exit 1 }

# LA LISTE SIGNEE DE LA RELEASE (docs/release-signing.md, section 5 ; pendant de verify_archive de bootstrap.sh). Une
# archive GitHub ne se signe pas : la release joint SHA256SUMS (l'empreinte de chaque fichier du tag) et SHA256SUMS.sig.
# On verifie la signature avec la cle ci-dessus (ssh-keygen.exe, le client OpenSSH de Windows), puis chaque fichier
# extrait - et aucun fichier en plus. Tout ecart : on efface et on s'arrete.
# Rend $true (verifiee) ou $false (ssh-keygen.exe absent : on le dit et on continue, comme avant 2026-11-23).
function Verify-Release($dir, $ref) {
    $keygen = Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if (-not $keygen) {
        $c = Join-Path $env:WINDIR 'System32\OpenSSH\ssh-keygen.exe'
        if (Test-Path $c) { $keygen = $c }
    }
    if (-not $keygen) {
        Write-Host "! ssh-keygen.exe is missing (Windows' OpenSSH client): the release signature is NOT checked." -ForegroundColor Yellow
        return $false
    }
    $tmp = Join-Path $cache "verify-$ref"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    function Bad($m) {
        Remove-Item -Recurse -Force $dir, $tmp -ErrorAction SilentlyContinue
        Die $m
    }
    $sums = Join-Path $tmp 'SHA256SUMS'; $sig = Join-Path $tmp 'SHA256SUMS.sig'; $signers = Join-Path $tmp 'signers'
    curl.exe -fL --retry 3 -sS -o $sums "$repo/releases/download/$ref/SHA256SUMS"
    if ($LASTEXITCODE -eq 0) { curl.exe -fL --retry 3 -sS -o $sig "$repo/releases/download/$ref/SHA256SUMS.sig" }
    if ($LASTEXITCODE -ne 0) { Bad "release $ref has no signed file list - not installing it." }
    # sans BOM, fin de ligne LF : ssh-keygen lit le fichier tel quel
    [IO.File]::WriteAllText($signers, $releaseSigners + "`n", (New-Object Text.UTF8Encoding($false)))
    # la liste passe par l'ENTREE STANDARD, octet pour octet : cmd.exe la redirige (un tube PowerShell la reecrirait)
    cmd.exe /d /c "`"$keygen`" -Y verify -f `"$signers`" -I golem -n git -s `"$sig`" < `"$sums`" >nul 2>&1"
    if ($LASTEXITCODE -ne 0) { Bad "release $ref is NOT signed by the golem release key - not installing it." }
    # chaque ligne : 64 chiffres, deux espaces, le chemin (avec des /) - le format de sha256sum
    $want = @{}
    foreach ($line in [IO.File]::ReadAllLines($sums, (New-Object Text.UTF8Encoding($false)))) {
        if ($line.Length -lt 67) { continue }
        $want[$line.Substring(66)] = $line.Substring(0, 64).ToLower()
    }
    if ($want.Count -eq 0) { Bad "the signed file list of $ref is empty - not installing it." }
    $root = (Resolve-Path -LiteralPath $dir).Path.TrimEnd('\') + '\'
    $sha = [Security.Cryptography.SHA256]::Create()
    $seen = 0
    foreach ($f in [IO.Directory]::EnumerateFiles($root, '*', [IO.SearchOption]::AllDirectories)) {
        $rel = $f.Substring($root.Length).Replace('\', '/')
        if (-not $want.ContainsKey($rel)) { Bad "the download of $ref holds a file its signed list does not name ($rel) - not installing it." }
        $stream = [IO.File]::OpenRead($f)
        try { $hash = -join ($sha.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) } finally { $stream.Dispose() }
        if ($hash -ne $want[$rel]) { Bad "the downloaded files of $ref do not match its signed list ($rel) - not installing it." }
        $seen++
    }
    if ($seen -ne $want.Count) { Bad "the download of $ref misses files of its signed list ($seen of $($want.Count)) - not installing it." }
    Remove-Item -Recurse -Force $tmp
    Say "release ${ref}: signed file list verified ($seen files)"
    return $true
}

#  1. le strict minimum 
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    Die 'golem needs 64-bit Windows on an x64 processor (the neural plugins ship for x64 only).'
}
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 19041) { Die "golem needs Windows 10 version 2004 or later (this is build $build)." }

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
    Say "golem $ref"
    $src = Join-Path $cache "golem-$ref"
    if ($releaseSigners) {
        # une branche ne se signe pas ; et jamais un cache qu'on n'a pas verifie nous-memes
        if ($ref -eq 'main') { Die 'no signed release found - refusing to install an unverified branch.' }
        if (Test-Path $src) { Remove-Item -Recurse -Force $src }
    }
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
        if ($releaseSigners) { Verify-Release $src $ref | Out-Null }
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
    Say 'the golem installer opens in its own window'
    Start-Process -FilePath $pythonw -ArgumentList ($argsList | ForEach-Object { '"' + $_ + '"' }) -WorkingDirectory $src
} else {
    Say 'opening the installer in your browser - keep this window open until the install is done'
    & $python @argsList
}
