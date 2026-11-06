# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — ce qui demande les droits d'administrateur sous Windows, en UNE autorisation (UAC).
#
# Lancé ÉLEVÉ par l'installeur graphique (installer/platform_windows.py), jamais à la main :
#     install-system.ps1 -Log <fichier> [-Receipt <reçu>] [-Vcredist] [-Reaper] [-Nam]
#
# Chaque composant est idempotent : présent = laissé tel quel (on ne rétrograde JAMAIS le REAPER de
# quelqu'un), absent = téléchargé à la version épinglée de provision/windows/pins.json, VÉRIFIÉ
# (empreinte, ou signature pour le runtime Microsoft), installé en silence, puis JUGÉ SUR PIÈCE
# (le fichier posé, pas le code retour — l'installeur de REAPER rend 1223 en ayant tout installé).
#
# Le journal va dans -Log, ligne par ligne : un processus élevé n'a pas de sortie que l'installeur
# (non élevé) puisse lire, alors il lit ce fichier en direct.
#
# LE REÇU D'INSTALLATION (docs/uninstall.md §9.2) : -Receipt est le chemin du reçu DE L'UTILISATEUR, résolu par
# l'appelant NON élevé (installer/platform_windows.py, bridge/desktop_reaper.py, bridge/desktop_network.py). On ne
# le résout JAMAIS ici : élevé par un autre compte administrateur, %LOCALAPPDATA% serait celui de l'administrateur.
# On n'écrit pas le reçu lui-même (verrou, fusion, « le premier gagne » : c'est provision/receipt.py) : on dépose
# un FRAGMENT à côté, <reçu>.pending-system-<pid>.json, réécrit après chaque composant (un échec au milieu garde
# ce qui a déjà été posé) ; le prochain passage de receipt.py le verse. Sans -Receipt : rien n'est noté.
param(
    [Parameter(Mandatory = $true)][string]$Log,
    [switch]$Vcredist, [switch]$Reaper, [switch]$Nam, [switch]$Firewall, [switch]$Avldrums, [switch]$Sfizz, [switch]$Vitalium, [switch]$Proteus,
    # le Python qui fait tourner le bridge (celui du venv n'est qu'un relais : c'est le Python de base
    # qui ouvre le port) — la règle « GoleM ouvert au réseau » vise CE programme sur CE port
    [string]$BridgePython = '', [int]$Port = 8770,
    # MISE À JOUR DU MOTEUR depuis Licenses ▸ Reaper (bridge/desktop_reaper.py) : l'installeur officiel
    # déjà téléchargé ET vérifié par le bridge, re-vérifié ici après copie dans un dossier d'admin
    [switch]$ReaperUpdate, [string]$Installer = '', [string]$Sha256 = '', [string]$Version = '',
    # RETOUR : échange l'install active et la précédente (« REAPER (x64).golem-prev »)
    [switch]$ReaperSwap, [string]$ReaperDir = '',
    # le reçu de l'utilisateur (docs/uninstall.md §9.2) — passé par l'appelant non élevé, jamais deviné ici
    [string]$Receipt = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$pins = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'pins.json') | ConvertFrom-Json
$golemData = Join-Path $env:ProgramData 'GoleM'
$golemDataExisted = Test-Path $golemData
$dl = Join-Path $golemData 'installers'
New-Item -ItemType Directory -Force -Path $dl | Out-Null

# UN flux, ouvert une fois, PARTAGÉ en lecture et écriture : l'installeur lit ce fichier pendant qu'on
# l'écrit. `Add-Content` l'ouvrait sans partage à chaque ligne et tombait sur « being used by another
# process » dès que le lecteur passait (vécu en VM le 2026-10-02, au premier essai).
$script:logStream = [IO.File]::Open($Log, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
$script:logWriter = New-Object IO.StreamWriter($script:logStream, (New-Object Text.UTF8Encoding($false)))
$script:logWriter.AutoFlush = $true
function Say($line) {
    $script:logWriter.WriteLine($line)
}

# ── le fragment de reçu (docs/uninstall.md §9.2) ──
# Format lu par provision/receipt.py (_apply_fragment) : items [{path, kind, group, owner, existed, moved_to}],
# prior {clé.pointée: valeur} (le premier gagne), append {clé.pointée: [valeurs]} (complété, dédoublonné).
$script:rcpt = @{ format = 1; by = 'provision/windows/install-system.ps1'; items = @(); prior = @{}; append = @{} }
$script:rcptFile = if ($Receipt) { "$Receipt.pending-system-$PID.json" } else { '' }
function Rcpt-Save {
    if (-not $script:rcptFile) { return }
    try {
        $dir = Split-Path -Parent $script:rcptFile
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $json = $script:rcpt | ConvertTo-Json -Depth 8
        # SANS BOM (Set-Content -Encoding UTF8 de PowerShell 5.1 en pose un), puis remplacement atomique
        $tmp = "$($script:rcptFile).tmp"
        [IO.File]::WriteAllText($tmp, $json, (New-Object Text.UTF8Encoding($false)))
        Move-Item -Force -LiteralPath $tmp -Destination $script:rcptFile
    } catch {
        Say "⚠ install receipt not updated ($($_.Exception.Message))"
    }
}
function Rcpt-Item($path, $kind, $group, [bool]$existed) {
    $script:rcpt.items += @(@{ path = [string]$path; kind = $kind; group = $group; owner = 'root'; existed = $existed })
    Rcpt-Save
}
function Rcpt-Prior($key, $value) {
    if (-not $script:rcpt.prior.ContainsKey($key)) { $script:rcpt.prior[$key] = $value }
    Rcpt-Save
}
function Rcpt-Append($key, $value) {
    if (-not $script:rcpt.append.ContainsKey($key)) { $script:rcpt.append[$key] = @() }
    $script:rcpt.append[$key] += @($value)
    Rcpt-Save
}

# Les clés « Uninstall » de Windows (HKLM 64 et 32 bits, HKCU) : leur chemin, pour voir ce qu'un installeur ajoute.
$script:uninstallRoots = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                           'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
                           'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall')
function UninstallKeys {
    $keys = @()
    foreach ($r in $script:uninstallRoots) {
        $keys += @(Get-ChildItem -LiteralPath $r -ErrorAction SilentlyContinue | ForEach-Object { $_.PSPath })
    }
    $keys
}
# Le commutateur silencieux connu de chaque famille d'installeur, quand la clé n'a pas de QuietUninstallString
$script:silentSwitch = @{ nsis = '/S'; inno = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'; burn = '/uninstall /quiet /norestart' }
# La commande de désinstallation d'un composant, lue dans le registre JUSTE APRÈS son installation : la clé
# APPARUE pendant l'installation ($before = UninstallKeys d'avant) dont le DisplayName correspond ; à défaut, la
# première clé qui correspond. Rend @{display_name, key, uninstall, quiet} ou $null (on le dit, on ne devine pas).
function UninstallEntry($before, $pattern, $family) {
    $all = UninstallKeys
    $new = @($all | Where-Object { $before -notcontains $_ })
    $found = $null
    foreach ($set in @($new, $all)) {
        foreach ($k in $set) {
            $p = Get-ItemProperty -LiteralPath $k -ErrorAction SilentlyContinue
            if ($p -and $p.DisplayName -and $p.DisplayName -like $pattern -and ($p.QuietUninstallString -or $p.UninstallString)) {
                $found = $p; break
            }
        }
        if ($found) { break }
    }
    # aucun nom ne correspond, mais l'installeur a ajouté UNE seule clé : c'est la sienne
    if (-not $found -and $new.Count -eq 1) {
        $p = Get-ItemProperty -LiteralPath $new[0] -ErrorAction SilentlyContinue
        if ($p -and ($p.QuietUninstallString -or $p.UninstallString)) { $found = $p }
    }
    if (-not $found) { return $null }
    $quiet = [bool]$found.QuietUninstallString
    $cmd = if ($quiet) { [string]$found.QuietUninstallString } else { [string]$found.UninstallString }
    if (-not $quiet) {
        $sw = $script:silentSwitch[$family]
        if ($sw -and $cmd -notlike "*$(($sw -split ' ')[0])*") { $cmd = "$cmd $sw" }
    }
    @{ display_name = [string]$found.DisplayName; key = ([string]$found.PSPath -replace '^Microsoft\.PowerShell\.Core\\Registry::', '');
       uninstall = $cmd; quiet = $quiet }
}
# Un composant : « installed » (on a lancé son installeur) ou « existed » (déjà là, laissé tel quel) — clés
# prior.programs.<id>.* ; installé, la commande de désinstallation du fabricant l'accompagne.
function Rcpt-Program($id, [bool]$installed, $path, $version, $entry) {
    Rcpt-Prior "programs.$id.installed_by_golem" $installed
    if ($path) { Rcpt-Prior "programs.$id.path" ([string]$path) }
    if ($version) { Rcpt-Prior "programs.$id.version" ([string]$version) }
    if ($installed) {
        if ($entry) {
            Rcpt-Prior "programs.$id.uninstall" $entry.uninstall
            Rcpt-Prior "programs.$id.display_name" $entry.display_name
            Rcpt-Prior "programs.$id.uninstall_key" $entry.key
        } else {
            Rcpt-Prior "programs.$id.uninstall" $null
            Say "⚠ $id : no uninstall command found in the registry — the uninstaller will not remove it"
        }
    }
}

# l'export d'une règle du pare-feu AVANT de la supprimer : de quoi la recréer à l'identique (prior.firewall_deleted)
function Export-Rule($r) {
    $af = $r | Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue
    $pf = $r | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
    @{ name = [string]$r.Name; displayname = [string]$r.DisplayName; program = [string]$af.Program;
       direction = [string]$r.Direction; action = [string]$r.Action; profile = [string]$r.Profile;
       protocol = [string]$pf.Protocol; ports = @($pf.LocalPort | ForEach-Object { [string]$_ });
       enabled = [string]$r.Enabled }
}

if ($Receipt) {
    Rcpt-Item $golemData 'dir' 'system' $golemDataExisted
    # les dossiers communs des plugins EXISTAIENT-ILS avant les installeurs des éditeurs ? (prior.common_dirs) Leurs
    # désinstalleurs les laissent vides : la désinstallation retire ceux que golem a fait naître, s'ils sont vides
    # (docs/uninstall.md §9.3). Noté avant tout composant ; le premier passage gagne (un passage plus tardif, pare-feu
    # ou mise à jour du moteur, les voit déjà là et ne change rien).
    foreach ($k in 'VST3', 'LV2', 'CLAP') {
        Rcpt-Prior "common_dirs.$k" ([bool](Test-Path -LiteralPath (Join-Path $env:CommonProgramFiles $k)))
    }
}

function Fetch($url, $name) {
    $path = Join-Path $dl $name
    if (-not (Test-Path $path)) {
        Say "→ downloading $name"
        curl.exe -fL --retry 3 -sS -A 'Mozilla/5.0' -o "$path.part" $url
        if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
        Move-Item -Force "$path.part" $path
    }
    $path
}

function CheckSha($path, $want) {
    $got = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $want.ToLower()) {
        Remove-Item -Force $path
        throw "checksum mismatch for $(Split-Path -Leaf $path) (got $got) — file removed, nothing installed"
    }
    Say "→ sha256 OK (pinned)"
}

function Install($exe, $arguments, $what, $okCodes) {
    $p = Start-Process $exe -ArgumentList $arguments -Wait -PassThru
    if ($okCodes -notcontains $p.ExitCode) { throw "$what : installer exit code $($p.ExitCode)" }
    $p.ExitCode
}

# où REAPER trouve un bundle LV2 sous Windows : jugé SUR PIÈCE après l'installation
function LvBundle($name) {
    foreach ($root in @((Join-Path $env:CommonProgramFiles 'LV2'), (Join-Path $env:ProgramFiles 'LV2'),
                        (Join-Path $env:APPDATA 'LV2'))) {
        $p = Join-Path $root $name
        if (Test-Path $p) { return $p }
    }
    return $null
}
function AvlBundle { LvBundle 'avldrums.lv2' }

function ExeVersion($dir) {
    $exe = Join-Path $dir 'reaper.exe'
    if (Test-Path $exe) { (Get-Item $exe).VersionInfo.ProductVersion } else { $null }
}

# L'install précédente reste À CÔTÉ, entière : c'est le filet d'une mise à jour (retour en un tap, sans
# réseau), comme reaper-versions/ sur le rack. Un dossier, pas une désinstallation : la config et la
# licence vivent dans %APPDATA%\REAPER, partagées par les deux.
function SwapReaper($dir) {
    $prev = "$dir.golem-prev"
    $tmp = "$dir.golem-swap"
    if (-not (Test-Path (Join-Path $prev 'reaper.exe'))) { throw "no previous REAPER next to $dir" }
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Rename-Item -LiteralPath $dir -NewName (Split-Path -Leaf $tmp)
    Rename-Item -LiteralPath $prev -NewName (Split-Path -Leaf $dir)
    Rename-Item -LiteralPath $tmp -NewName (Split-Path -Leaf $prev)
}

try {
    # ── RETOUR à l'install précédente (Licenses ▸ Reaper, « Use 7.27 », ou rollback automatique) ──
    if ($ReaperSwap) {
        if (-not $ReaperDir) { throw '-ReaperSwap needs -ReaperDir' }
        $from = ExeVersion $ReaperDir
        SwapReaper $ReaperDir
        Say "✓ REAPER $from → $(ExeVersion $ReaperDir) ($from kept next to it)"
    }

    # ── MISE À JOUR du moteur (Licenses ▸ Reaper) ──
    if ($ReaperUpdate) {
        if (-not ($ReaperDir -and $Installer -and $Version)) { throw '-ReaperUpdate needs -ReaperDir, -Installer and -Version' }
        $from = ExeVersion $ReaperDir
        if (-not $from) { throw "no reaper.exe in $ReaperDir" }
        # l'exécutable qu'on lance ÉLEVÉ vient d'un dossier de l'utilisateur : on le copie d'abord ici,
        # puis on vérifie CETTE copie — l'empreinte vue par le bridge ne vaut que pour son fichier à lui
        $ri = Join-Path $dl ([IO.Path]::GetFileName($Installer))
        Copy-Item -Force -LiteralPath $Installer -Destination $ri
        if ($Sha256) { CheckSha $ri $Sha256 }
        else {
            $got = (Get-FileHash $ri -Algorithm SHA256).Hash.ToLower()
            if ($got -ne (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLower()) { throw 'installer changed while copying' }
            # audit 2026-11-04 (M8) : Cockos ne publie pas d'empreinte, mais SIGNE ses installateurs — un exécutable
            # lancé élevé sans empreinte doit au moins porter la signature de Cockos (vérifié sur 7.79, O=Cockos Incorporated)
            $sig = Get-AuthenticodeSignature $ri
            if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike "*O=$($pins.reaper.signer)*") {
                Remove-Item -Force $ri
                throw "the REAPER installer is not signed by $($pins.reaper.signer) ($($sig.Status)) — removed"
            }
            Say "→ sha256 $got, signature OK ($($pins.reaper.signer))"
        }
        $prev = "$ReaperDir.golem-prev"
        if (Test-Path $prev) { Remove-Item -Recurse -Force $prev }
        Say "→ keeping REAPER $from next to it"
        Copy-Item -Recurse -Force -LiteralPath $ReaperDir -Destination $prev
        Rcpt-Item $prev 'dir' 'system' $false
        try {
            # /D= DOIT être le dernier argument (NSIS) : l'install va là où GoleM lance REAPER
            Install $ri @('/S', "/D=$ReaperDir") 'Reaper' @(0, 1223) | Out-Null
            $v = ExeVersion $ReaperDir
            if ($v -ne $Version) { throw "unexpected version after install: $v" }
            Say "✓ REAPER $from → $v"
        } catch {
            Say "✗ $($_.Exception.Message) — restoring $from"
            Remove-Item -Recurse -Force $ReaperDir
            Rename-Item -LiteralPath $prev -NewName (Split-Path -Leaf $ReaperDir)
            throw
        }
    }

    # ── le runtime Visual C++ : sans lui python-rtmidi ne se charge pas, pédalier et MIDI muets ──
    if ($Vcredist) {
        Say '▶ Microsoft Visual C++ runtime (x64)'
        $k = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64'
        if ((Get-ItemProperty $k -ErrorAction SilentlyContinue).Installed -eq 1) {
            Say '→ already installed'
            Rcpt-Program 'vcredist' $false $null (Get-ItemProperty $k -ErrorAction SilentlyContinue).Version $null
        } else {
            $vc = Fetch $pins.vcredist.url 'vc_redist.x64.exe'
            # pas d'adresse figée chez Microsoft : on vérifie la SIGNATURE au lieu d'une empreinte
            $sig = Get-AuthenticodeSignature $vc
            if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike "*O=$($pins.vcredist.signer)*") {
                Remove-Item -Force $vc
                throw "vc_redist.x64.exe is not signed by $($pins.vcredist.signer) ($($sig.Status)) — removed"
            }
            Say '→ signature OK (Microsoft Corporation)'
            # 1638 = une version plus récente est déjà là ; 3010 = installé, redémarrage conseillé
            $before = UninstallKeys
            $rc = Install $vc @('/install', '/quiet', '/norestart') 'Visual C++ runtime' @(0, 1638, 3010)
            if ((Get-ItemProperty $k -ErrorAction SilentlyContinue).Installed -ne 1) { throw 'Visual C++ runtime not registered after install' }
            # 1638 : rien n'a été posé — une version plus récente était là avant nous
            Rcpt-Program 'vcredist' ($rc -ne 1638) $null (Get-ItemProperty $k -ErrorAction SilentlyContinue).Version `
                (UninstallEntry $before 'Microsoft Visual C++ * Redistributable (x64)*' 'burn')
            Say ('✓ Visual C++ runtime installed' + $(if ($rc -eq 3010) { ' — Windows suggests a restart' } else { '' }))
        }
    }

    # ── REAPER ──
    if ($Reaper) {
        Say "▶ Reaper $($pins.reaper.version)"
        # -ReaperDir : le dossier CHOISI à l'écran (un REAPER ailleurs que sur C:, 2026-10-17) ; sinon Program Files
        $rdir = if ($ReaperDir) { $ReaperDir } else { Join-Path $env:ProgramFiles 'REAPER (x64)' }
        $rexe = Join-Path $rdir 'reaper.exe'
        if (Test-Path $rexe) {
            $v = (Get-Item $rexe).VersionInfo.ProductVersion
            Say "→ already installed ($v) — kept as is"
            Rcpt-Program 'reaper' $false (Split-Path $rexe) $v $null
            # prior.reaper : la même forme que sous Linux (docs/uninstall.md §2)
            Rcpt-Prior 'reaper.installed_by_golem' $false
            Rcpt-Prior 'reaper.path' (Split-Path $rexe)
            Rcpt-Prior 'reaper.version' $v
        } else {
            $ri = Fetch $pins.reaper.url ([IO.Path]::GetFileName($pins.reaper.url))
            CheckSha $ri $pins.reaper.sha256
            # ⚠ /S rend 1223 (« annulé ») alors qu'il a TOUT installé — mesuré 3 fois le 2026-10-01 : on
            # juge sur pièce, la version de l'exécutable posé
            $before = UninstallKeys
            # /D= DOIT être le dernier argument (NSIS) et sans guillemets : c'est la règle de l'installateur de REAPER
            Install $ri @('/S', "/D=$rdir") 'Reaper' @(0, 1223) | Out-Null
            if (-not (Test-Path $rexe)) { throw "reaper.exe missing after install ($rdir)" }
            $v = (Get-Item $rexe).VersionInfo.ProductVersion
            $entry = UninstallEntry $before 'REAPER*' 'nsis'
            Rcpt-Program 'reaper' $true (Split-Path $rexe) $v $entry
            Rcpt-Prior 'reaper.installed_by_golem' $true
            Rcpt-Prior 'reaper.path' (Split-Path $rexe)
            Rcpt-Prior 'reaper.version' $v
            if ($entry) { Rcpt-Prior 'reaper.uninstall' $entry.uninstall }
            if ($v -ne $pins.reaper.version) { throw "Reaper: unexpected version $v" }
            Say "✓ Reaper $v in $(Split-Path $rexe)"
        }
    }

    # ── le cœur ampli + baffle : NeuralAmpModeler VST3 officiel ──
    if ($Nam) {
        Say "▶ NeuralAmpModeler VST3 $($pins.nam_vst3.version) (the amp and cab core)"
        $vst = Join-Path $env:CommonProgramFiles 'VST3\NeuralAmpModeler.vst3'
        if (Test-Path $vst) {
            Say '→ already installed — kept as is'
            Rcpt-Program 'nam_vst3' $false $vst $null $null
        } else {
            $z = Fetch $pins.nam_vst3.url ([IO.Path]::GetFileName($pins.nam_vst3.url))
            CheckSha $z $pins.nam_vst3.sha256
            $x = Join-Path $dl 'NAM-installer'
            if (Test-Path $x) { Remove-Item -Recurse -Force $x }
            Expand-Archive $z -DestinationPath $x
            $before = UninstallKeys
            Install (Join-Path $x 'NeuralAmpModeler Installer.exe') @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/COMPONENTS=vst3_64') 'NAM VST3' @(0) | Out-Null
            Rcpt-Program 'nam_vst3' $true $vst $pins.nam_vst3.version (UninstallEntry $before '*Neural*Amp*Modeler*' 'inno')
            if (-not (Test-Path $vst)) { throw 'NeuralAmpModeler.vst3 missing after install' }
            Say "✓ NeuralAmpModeler VST3 in $(Split-Path $vst)"
        }
        # ── 0.7.15 bâti par golem (lit les captures A2) : remplace la DLL du 0.7.13 OFFICIEL, rien d'autre — un NAM
        # que quelqu'un a posé lui-même (autre version, autre build) est laissé tel quel. Témoin : golem-nam-version.txt
        $dll = Join-Path $vst 'Contents\x86_64-win\NeuralAmpModeler.vst3'
        $mark = Join-Path $vst 'golem-nam-version.txt'
        $have = if (Test-Path $mark) { (Get-Content -Raw $mark).Trim() } else { '' }
        if ($have -eq $pins.nam_golem.version) {
            Say "→ NeuralAmpModeler $have (golem build) already in place"
        } elseif ((Test-Path $dll) -and ((Get-FileHash $dll -Algorithm SHA256).Hash.ToLower() -eq $pins.nam_golem.replaces_sha256)) {
            Say "▶ NeuralAmpModeler $($pins.nam_golem.version) (golem build — plays A2 captures)"
            $gz = Fetch $pins.nam_golem.url ([IO.Path]::GetFileName($pins.nam_golem.url))
            CheckSha $gz $pins.nam_golem.sha256
            $gx = Join-Path $dl 'NAM-golem'
            if (Test-Path $gx) { Remove-Item -Recurse -Force $gx }
            Expand-Archive $gz -DestinationPath $gx
            Copy-Item -Force -LiteralPath $dll -Destination (Join-Path $dl 'NeuralAmpModeler-0.7.13.vst3')   # l'ancienne DLL, gardée
            Copy-Item -Force -LiteralPath (Join-Path $gx 'NeuralAmpModeler.vst3') -Destination $dll
            [IO.File]::WriteAllText($mark, $pins.nam_golem.version)
            Rcpt-Prior 'programs.nam_vst3.golem_build' $pins.nam_golem.version
            Say "✓ NeuralAmpModeler $($pins.nam_golem.version) in $(Split-Path $vst)"
        } else {
            Say '→ NeuralAmpModeler is not the official 0.7.13 — kept as is (A2 captures stay unavailable)'
        }
    }
    # ── le moteur du bloc drumkit : AVL Drumkits (x42, GPL, LV2) ──
    # 2026-10-03 : un patch drums ne sonnait pas sous Windows — le MIDI du module arrivait, le moteur des
    # kits manquait. L'installeur officiel est un NSIS NON SIGNÉ : on se fie à son empreinte épinglée.
    if ($Avldrums) {
        Say "▶ AVL Drumkits $($pins.avldrums.version) (the drum kits — Black Pearl, Red Zeppelin, Blonde Bop…)"
        $found = AvlBundle
        if ($found) {
            Say "→ already installed — kept as is ($found)"
            Rcpt-Program 'avldrums' $false $found $null $null
        } else {
            $ai = Fetch $pins.avldrums.url ([IO.Path]::GetFileName($pins.avldrums.url))
            CheckSha $ai $pins.avldrums.sha256
            $before = UninstallKeys
            Install $ai @('/S') 'AVL Drumkits' @(0) | Out-Null
            $found = AvlBundle
            Rcpt-Program 'avldrums' $true $found $pins.avldrums.version (UninstallEntry $before '*avl*drum*' 'nsis')
            if (-not $found) { throw 'avldrums.lv2 missing after install' }
            Say "✓ AVL Drumkits in $found"
        }
    }

    # ── sfizz : le moteur des kits SFZ (docs/drums-kit.md §6, 2026-10-11) — le seul format de batterie importable
    # sur les trois OS. Inno Setup NON signé : l'empreinte épinglée est le seul contrôle. Pose sfizz.lv2 (lu par
    # golem_drums.lua sous son nom LV2) et sfizz.vst3 dans Common Files.
    if ($Sfizz) {
        Say "▶ sfizz $($pins.sfizz.version) (the SFZ sampler — imported SFZ drum kits)"
        $found = LvBundle 'sfizz.lv2'
        if ($found) {
            Say "→ already installed — kept as is ($found)"
            Rcpt-Program 'sfizz' $false $found $null $null
        } else {
            $si = Fetch $pins.sfizz.url ([IO.Path]::GetFileName($pins.sfizz.url))
            CheckSha $si $pins.sfizz.sha256
            $before = UninstallKeys
            Install $si @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'sfizz' @(0) | Out-Null
            $found = LvBundle 'sfizz.lv2'
            Rcpt-Program 'sfizz' $true $found $pins.sfizz.version (UninstallEntry $before '*sfizz*' 'inno')
            if (-not $found) { throw 'sfizz.lv2 missing after install' }
            Say "✓ sfizz in $found"
        }
    }

    # ── Proteus (GuitarML, GPL-3, VST3) : le bloc boost (2026-10-22) — la table Windows le nommait, rien ne
    # l'installait. Inno Setup NON signé : l'empreinte épinglée est le seul contrôle. Pose Proteus.vst3.
    if ($Proteus) {
        Say "▶ Proteus $($pins.proteus.version) (the Boost block)"
        $vst = Join-Path $env:CommonProgramFiles 'VST3\Proteus.vst3'
        if (Test-Path $vst) {
            Say "→ already installed — kept as is ($vst)"
            Rcpt-Program 'proteus' $false $vst $null $null
        } else {
            $pr = Fetch $pins.proteus.url ([IO.Path]::GetFileName($pins.proteus.url))
            CheckSha $pr $pins.proteus.sha256
            $before = UninstallKeys
            Install $pr @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-') 'Proteus' @(0) | Out-Null
            Rcpt-Program 'proteus' $true $vst $pins.proteus.version (UninstallEntry $before '*Proteus*' 'inno')
            if (-not (Test-Path $vst)) { throw 'Proteus.vst3 missing after install' }
            Say "✓ Proteus in $(Split-Path $vst)"
        }
    }

    # ── le synthé du bloc vital : Vitalium (DISTRHO, GPL, LV2), livré par PawPaw ──
    # 2026-10-03 : le Vital officiel ne se télécharge qu'avec un compte — pas d'installation automatique
    # possible. Vitalium est sa version libre ; PawPaw est la seule distribution Windows publiée (Inno Setup
    # NON signé : l'empreinte épinglée est le seul contrôle). Le bloc préfère Vital officiel s'il est là.
    if ($Vitalium) {
        Say "▶ Vitalium (PawPaw $($pins.pawpaw.version)) — the free build of Vital, for the Vital block"
        $found = LvBundle 'vitalium.lv2'
        if ($found) {
            Say "→ already installed — kept as is ($found)"
            Rcpt-Program 'pawpaw' $false $found $null $null
        } else {
            $pi = Fetch $pins.pawpaw.url ([IO.Path]::GetFileName($pins.pawpaw.url))
            CheckSha $pi $pins.pawpaw.sha256
            $before = UninstallKeys
            Install $pi @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') 'PawPaw (Vitalium)' @(0) | Out-Null
            $found = LvBundle 'vitalium.lv2'
            # PawPaw installe TOUS ses plugins : sa désinstallation les retire tous (docs/uninstall.md §9.3)
            Rcpt-Program 'pawpaw' $true $found $pins.pawpaw.version (UninstallEntry $before '*PawPaw*' 'inno')
            if (-not $found) { throw 'vitalium.lv2 missing after install' }
            Say "✓ Vitalium in $found"
        }
    }

    # ── le pare-feu : REAPER n'accepte RIEN du réseau ──
    # REAPER ouvre son port OSC sur TOUTES les interfaces alors que GoleM ne lui parle qu'en local
    # (127.0.0.1) ; au premier lancement Windows demandait « Allow public and private networks? »
    # (vu sur un Windows vierge le 2026-10-02). Une règle « entrant bloqué » pour reaper.exe répond
    # d'avance la réponse sûre : la boucle locale n'est pas filtrée, GoleM lui parle toujours, et plus
    # personne sur le réseau ne peut le piloter. Rien en sortie n'est touché.
    if ($Firewall) {
        Say '▶ Firewall: Reaper accepts nothing from the network (GoleM talks to it locally)'
        # le REAPER que golem lance — où qu'il soit (-ReaperDir, passé par l'installateur), Program Files sinon
        $rexe = Join-Path $(if ($ReaperDir) { $ReaperDir } else { Join-Path $env:ProgramFiles 'REAPER (x64)' }) 'reaper.exe'
        $name = 'GoleM - Reaper, no inbound network'
        if (-not (Test-Path $rexe)) {
            Say '→ Reaper not installed — skipped'
        } elseif (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) {
            Say '→ rule already there'
            Rcpt-Append 'firewall.added' $name
        } else {
            New-NetFirewallRule -DisplayName $name -Direction Inbound -Program $rexe -Action Block -Profile Any | Out-Null
            Rcpt-Append 'firewall.added' $name
            Say "✓ inbound blocked for $rexe"
        }
        # ── GoleM OUVERT AU RÉSEAU (2026-10-03) : la tablette et les téléphones du groupe le rejoignent,
        # comme le rack. Le port du bridge, pour SON programme, sur les réseaux PRIVÉS seulement — un WiFi
        # de café (« Public » pour Windows) n'en voit rien. Sans cette règle Windows demandait, au premier
        # lancement, d'autoriser « Python » — et un « Annuler » y posait une règle de BLOCAGE silencieuse.
        # Le bridge exige de toute façon qu'un appareil distant soit appairé (bridge/auth.py).
        # TOUS LES RÉSEAUX (2026-10-03 : « les appareils doivent s'enregistrer sur le golem pour y
        # avoir accès ») : le WiFi de la maison qu'il soit « Public » ou « Privé » pour Windows, et le point
        # d'accès de scène (192.168.137.1, sans catégorie). La garde est l'APPAIREMENT (bridge/auth.py),
        # comme sur le rack — pas la catégorie que Windows a donnée au réseau. Un premier jet n'ouvrait
        # que les réseaux « Privé » : il fallait aller reclasser son WiFi dans Windows, pour rien.
        foreach ($old in 'GoleM - bridge, private networks', 'GoleM - bridge, mobile hotspot') {
            Get-NetFirewallRule -DisplayName $old -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        }
        $bname = 'GoleM - bridge'
        Get-NetFirewallRule -DisplayName $bname -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        # le port du bridge, et 80 : le bridge y renvoie vers $Port, pour que `http://golem.local` suffise
        # (bridge/reach.py, 2026-10-03)
        $rule = @{ DisplayName = $bname; Direction = 'Inbound'; Protocol = 'TCP'; LocalPort = @($Port, 80);
                   Action = 'Allow'; Profile = 'Any' }
        if ($BridgePython -and (Test-Path $BridgePython)) { $rule.Program = $BridgePython }
        New-NetFirewallRule @rule | Out-Null
        Rcpt-Append 'firewall.added' $bname
        Say "✓ GoleM open on TCP $Port and 80, every network$(if ($rule.Program) { " ($BridgePython)" }) — devices still have to be paired"
        # le nom `golem.local` : le bridge répond lui-même aux questions mDNS (UDP 5353)
        $mname = 'GoleM - golem.local (mDNS)'
        Get-NetFirewallRule -DisplayName $mname -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        $mrule = @{ DisplayName = $mname; Direction = 'Inbound'; Protocol = 'UDP'; LocalPort = 5353;
                    Action = 'Allow'; Profile = 'Any' }
        if ($rule.Program) { $mrule.Program = $rule.Program }
        New-NetFirewallRule @mrule | Out-Null
        Rcpt-Append 'firewall.added' $mname
        Say '✓ golem.local answered on every network (mDNS, UDP 5353)'
        # ce que Windows a posé TOUT SEUL pour ce Python à son invite « Autoriser Python sur le réseau ? »
        # (le bridge écoutait avant que la règle existe) : un BLOCAGE l'emporterait sur la nôtre, et une
        # AUTORISATION « tous ports » ouvrirait n'importe quel programme Python, pas seulement le port de
        # GoleM. Ce sont des règles nommées « python.exe ».
        # Chaque règle est EXPORTÉE dans le reçu AVANT d'être supprimée (prior.firewall_deleted) : la
        # désinstallation la recrée telle qu'elle était (docs/uninstall.md §9.2).
        if ($rule.Program) {
            Get-NetFirewallApplicationFilter -Program $BridgePython -ErrorAction SilentlyContinue | Get-NetFirewallRule |
                Where-Object { $_.Direction -eq 'Inbound' -and $_.DisplayName -notlike 'GoleM*' -and
                               ($_.Action -eq 'Block' -or $_.DisplayName -like 'python*') } |
                ForEach-Object {
                    Say "→ removing Windows' own rule « $($_.DisplayName) » ($($_.Action), $($_.Profile)) for this Python"
                    Rcpt-Append 'prior.firewall_deleted' (Export-Rule $_)
                    Remove-NetFirewallRule -Name $_.Name
                }
        }
    }
    Say '✅ system step done'
    $script:logWriter.Dispose()
    exit 0
} catch {
    Say "✗ $($_.Exception.Message)"
    $script:logWriter.Dispose()
    exit 1
}
