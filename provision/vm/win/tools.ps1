# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — outillage de la VM Windows de test (lancé par `win.sh tools`, en SSH).
#
# Pose ce que le contrat desktop suppose DÉJÀ installé (docs/platforms.md) :
# Python 3.12 x64, REAPER x64, le VST3 officiel NeuralAmpModeler — aux versions que la CI de la
# PR épingle (REAPER 7.80, NAM 0.7.13) — plus ffmpeg et Node.js, que les suites de tests appellent.
# Rejouable : un installeur déjà téléchargé n'est pas re-téléchargé.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$dl = 'C:\golem-tools'
New-Item -ItemType Directory -Force -Path $dl | Out-Null

function Fetch($url, $name) {
    $path = Join-Path $dl $name
    if (-not (Test-Path $path)) {
        curl.exe -fL --retry 3 -sS -A 'Mozilla/5.0' -o "$path.part" $url
        if ($LASTEXITCODE -ne 0) { throw "téléchargement échoué : $name" }
        Move-Item "$path.part" $path
    }
    $path
}

function Run($exe, $arguments, $what, $okCodes = @(0)) {
    $p = Start-Process $exe -ArgumentList $arguments -Wait -PassThru
    if ($okCodes -notcontains $p.ExitCode) { throw "$what : code $($p.ExitCode)" }
    Write-Output "ok  $what (code $($p.ExitCode))"
}

# ── Python 3.12 (dernier installeur binaire de la branche) ───────────────────────────────
$py = Fetch 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' 'python-3.12.10-amd64.exe'
Run $py @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0') 'Python 3.12.10'

# ── REAPER 7.80 ──────────────────────────────────────────────────────────────────────────
$reaper = Fetch 'https://www.reaper.fm/files/7.x/reaper780_x64-install.exe' 'reaper780_x64-install.exe'
# ⚠ L'installeur silencieux de REAPER rend 1223 (« annulé par l'utilisateur ») alors qu'il a TOUT
# installé. Mesuré le 2026-10-01, trois fois : en SSH, en SSH sans ShellExecute, et dans la session
# graphique élevée — même code, même résultat (2425 fichiers, désinstalleur enregistré, 7.80).
# Ce n'est donc pas un problème d'élévation. Le code ne prouve rien ici : on JUGE SUR PIÈCE,
# la version de l'exécutable posé. (La CI de la PR installe en /PORTABLE, qui rend 0.)
Run $reaper @('/S') 'REAPER 7.80' @(0, 1223)
$rexe = 'C:\Program Files\REAPER (x64)\reaper.exe'
if (-not (Test-Path $rexe)) { throw 'reaper.exe absent après installation' }
if ((Get-Item $rexe).VersionInfo.ProductVersion -ne '7.80') { throw "REAPER : version inattendue $((Get-Item $rexe).VersionInfo.ProductVersion)" }

# ── NAM VST3 0.7.13 (archive vérifiée : même empreinte que la CI de la PR) ───────────────
$nam = Fetch 'https://github.com/sdatkinson/NeuralAmpModelerPlugin/releases/download/v0.7.13/NeuralAmpModeler-v0.7.13-win.zip' 'NeuralAmpModeler-v0.7.13-win.zip'
if ((Get-FileHash $nam -Algorithm SHA256).Hash -ne '8DA37AFDE1F0797C773D6B8709DA89BDDA40C0E45F67CF3E4D87291E9B5E9DA5') {
    throw 'empreinte de l''archive NAM inattendue'
}
$namDir = Join-Path $dl 'NAM-installer'
if (Test-Path $namDir) { Remove-Item -Recurse -Force $namDir }
Expand-Archive $nam -DestinationPath $namDir
Run (Join-Path $namDir 'NeuralAmpModeler Installer.exe') @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/COMPONENTS=vst3_64') 'NAM VST3 0.7.13'
if (-not (Test-Path 'C:\Program Files\Common Files\VST3\NeuralAmpModeler.vst3')) { throw 'NeuralAmpModeler.vst3 absent après installation' }

# ── ffmpeg ───────────────────────────────────────────────────────────────────────────────
if (-not (Test-Path 'C:\ffmpeg\bin\ffmpeg.exe')) {
    $ff = Fetch 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' 'ffmpeg-release-essentials.zip'
    $ffDir = Join-Path $dl 'ffmpeg-x'
    if (Test-Path $ffDir) { Remove-Item -Recurse -Force $ffDir }
    Expand-Archive $ff -DestinationPath $ffDir
    Move-Item (Get-ChildItem $ffDir -Directory | Select-Object -First 1).FullName 'C:\ffmpeg'
}
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($machinePath -notlike '*C:\ffmpeg\bin*') {
    [Environment]::SetEnvironmentVariable('Path', "$machinePath;C:\ffmpeg\bin", 'Machine')
}
Write-Output 'ok  ffmpeg'

# ── Node.js LTS : les tests *.test.mjs de l'app, et un test pytest qui joue un parseur JS ──
if (-not (Test-Path 'C:\Program Files\nodejs\node.exe')) {
    $node = Fetch 'https://nodejs.org/dist/v24.21.0/node-v24.21.0-x64.msi' 'node-v24.21.0-x64.msi'
    Run 'msiexec.exe' @('/i', "`"$node`"", '/qn', '/norestart') 'Node.js 24.21.0'
}

# le service sshd a hérité de l'ancien PATH : c'est `win.sh tools` qui redémarre la VM ensuite
Write-Output 'OUTILLAGE TERMINE'
