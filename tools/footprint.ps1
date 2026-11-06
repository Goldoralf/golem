# SPDX-License-Identifier: GPL-3.0-or-later
# Empreinte d'une machine WINDOWS, pour juger une desinstallation (docs/uninstall.md 9.6) : tout ce qu'une
# installation de golem peut toucher, une ligne par fait, triee, en sections `## nom` comme tools/footprint.sh -
# deux releves se comparent ligne a ligne. LECTURE SEULE : rien n'est ecrit, rien n'est lance qui modifie.
# Lance DANS la VM de test par tools/check-uninstall-vm.sh --win, le script voyageant par l'entree standard de
# `provision/vm/win.sh ps` (rien a pousser dans la VM). ASCII seulement : l'entree standard est lue dans la page de
# code de la console.
#
# Le bruit que Windows fait tout seul (caches, Defender, Edge, OneDrive, Temp...) est filtre ICI grossierement pour
# garder le releve petit ; le juge (tools/uninstall-judge.py --win, WIN_NOISE) a la liste fine. Ce qui porte
# "golem" n'est JAMAIS filtre.
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

function Sec($name) { ''; "## $name" }
function IsGolem($p) { return ($p -match 'golem') }
$coarse = @(
    '\\AppData\\Local\\Temp(\\|$)', '\\AppData\\Local\\Microsoft(\\|$)', '\\AppData\\Local\\Packages(\\|$)',
    '\\AppData\\LocalLow(\\|$)', '\\AppData\\Roaming\\Microsoft(\\|$)', '\\AppData\\Local\\ConnectedDevicesPlatform(\\|$)',
    '\\AppData\\Local\\D3DSCache(\\|$)', '\\AppData\\Local\\CrashDumps(\\|$)', '\\AppData\\Local\\Google\\Chrome\\User Data(\\|$)',
    '\\ProgramData\\Microsoft(\\|$)', '\\ProgramData\\Packages(\\|$)', '\\ProgramData\\USOShared(\\|$)',
    '\\ProgramData\\USOPrivate(\\|$)', '\\ProgramData\\Windows Defender', '\\Prefetch(\\|$)'
)
function Noise($p) {
    foreach ($n in $coarse) { if ($p -match $n) { return $true } }
    return $false
}
# un dossier, recursivement jusqu'a $depth niveaux ; jamais a travers une jonction ou un lien
function Walk($dir, $depth) {
    Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $p = $_.FullName
        if ((Noise $p) -and -not (IsGolem $p)) { return }
        if ($_.PSIsContainer) { "d $p" } else { "f $p" }
        $link = [bool]($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        if ($_.PSIsContainer -and -not $link -and $depth -gt 1) { Walk $p ($depth - 1) }
    }
}

$uninstallRoots = @(
    @('HKLM', 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'),
    @('HKLM32', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'),
    @('HKCU', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')
)
$keys = @()
foreach ($r in $uninstallRoots) {
    Get-ChildItem -LiteralPath $r[1] -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
        if ($p -and $p.DisplayName) {
            $u = [string]$p.UninstallString
            $udir = ''
            if ($u -match '^"([^"]+)"') { $udir = Split-Path -Parent $matches[1] }
            elseif ($u -match '^(.+?\.exe)') { $udir = Split-Path -Parent $matches[1] }
            $keys += [pscustomobject]@{ Tag = $r[0]; Name = [string]$p.DisplayName; Version = [string]$p.DisplayVersion;
                                        Location = ([string]$p.InstallLocation).TrimEnd('\'); UDir = $udir }
        }
    }
}

# les programmes installes : une cle "Uninstall" par programme (HKLM 64 et 32 bits, HKCU)
Sec 'uninstall-keys'
$keys | ForEach-Object { "$($_.Tag) $($_.Name)" } | Sort-Object -Unique

# les versions a part : une mise a jour n'est pas une trace
Sec 'versions'
$keys | ForEach-Object { "$($_.Tag) $($_.Name) | $($_.Version)" } | Sort-Object -Unique

# ou vit chaque programme (InstallLocation, dossier de son desinstalleur) : le juge garde ce qui est dans un
# programme garde
Sec 'install-locations'
$keys | ForEach-Object { "$($_.Name) | $($_.Location) | $($_.UDir)" } | Sort-Object -Unique

# Program Files (un niveau) et les dossiers communs des plugins (VST3, LV2, CLAP : deux niveaux)
Sec 'program-files'
& {
    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($pf) { Walk $pf 1 }
    }
    foreach ($cf in @($env:CommonProgramFiles, ${env:CommonProgramFiles(x86)})) {
        if ($cf) { foreach ($k in 'VST3', 'LV2', 'CLAP') { $d = Join-Path $cf $k; if (Test-Path -LiteralPath $d) { "d $d"; Walk $d 2 } } }
    }
    $lp = Join-Path $env:LOCALAPPDATA 'Programs'
    if (Test-Path -LiteralPath $lp) { Walk $lp 4 }
} | Sort-Object -Unique

# les donnees : %APPDATA%, %LOCALAPPDATA% (hors Programs, deja vu), %ProgramData% (bruit filtre), le profil (un niveau)
Sec 'files'
& {
    Walk $env:APPDATA 5
    Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'Programs' } | ForEach-Object {
        $p = $_.FullName
        if ((Noise $p) -and -not (IsGolem $p)) { return }
        if ($_.PSIsContainer) { "d $p"; if (-not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Walk $p 4 } } else { "f $p" }
    }
    Walk $env:ProgramData 4
    Walk $env:USERPROFILE 1
    # ce que golem laisse dans %TEMP% (le reste de Temp est du bruit)
    # sauf golem-footprint.txt : la sortie de CE releve (check-uninstall-vm.sh), qui se voyait elle-meme
    Get-ChildItem -LiteralPath $env:TEMP -Force -Filter 'golem*' -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -ne 'golem-footprint.txt' } | ForEach-Object {
        if ($_.PSIsContainer) { "d $($_.FullName)" } else { "f $($_.FullName)" }
    }
} | Sort-Object -Unique

# les regles du pare-feu : nom, active, sens, action
Sec 'firewall'
Get-NetFirewallRule -ErrorAction SilentlyContinue | ForEach-Object {
    "$($_.DisplayName) | $($_.Enabled) | $($_.Direction) | $($_.Action)"
} | Sort-Object -Unique

# les raccourcis : Bureau (le sien et le public), menu Demarrer (le sien et le commun), Demarrage
Sec 'shortcuts'
& {
    foreach ($f in 'Desktop', 'CommonDesktopDirectory', 'Programs', 'CommonPrograms', 'Startup', 'CommonStartup') {
        $d = [Environment]::GetFolderPath($f)
        if ($d -and (Test-Path -LiteralPath $d)) {
            Get-ChildItem -LiteralPath $d -Recurse -Force -Include '*.lnk', '*.url' -ErrorAction SilentlyContinue |
                ForEach-Object { $_.FullName }
        }
    }
} | Sort-Object -Unique

# le plan d'alimentation actif (son GUID : le nom suit la langue de Windows)
Sec 'power'
$m = [regex]::Match((powercfg /getactivescheme | Out-String), '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
if ($m.Success) { "active $($m.Value.ToLower())" } else { 'active unknown' }
exit 0
