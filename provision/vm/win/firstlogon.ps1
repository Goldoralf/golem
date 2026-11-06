# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — première ouverture de session de la VM Windows de test (lancé par autounattend.xml).
#
# Rend la machine PILOTABLE depuis l'hôte, puis la FIGE :
#   - serveur OpenSSH (MSI posé sur l'ISO : aucun téléchargement au premier boot)
#   - clé publique de l'hôte pour les administrateurs
#   - ni veille ni extinction d'écran (une capture `win.sh shot` doit montrer le bureau)
#   - mises à jour automatiques coupées : une base qui change seule n'est plus une base
#
# Tout est journalisé dans C:\golem-firstlogon.log ; C:\golem-ready.txt est écrit EN DERNIER —
# c'est lui que win.sh attend, pas l'ouverture du port 22.
$ErrorActionPreference = 'Continue'
Start-Transcript -Path 'C:\golem-firstlogon.log' -Append

# ── SSH ──────────────────────────────────────────────────────────────────────────────────
$msi = Get-ChildItem -Path $PSScriptRoot -Filter 'OpenSSH-Win64-*.msi' | Select-Object -First 1
if ($msi) {
    $p = Start-Process msiexec.exe -ArgumentList '/i', "`"$($msi.FullName)`"", '/qn', '/norestart' -Wait -PassThru
    Write-Output "OpenSSH msi -> code $($p.ExitCode)"
} else {
    Write-Output 'OpenSSH msi ABSENT du media : pas de SSH'
}

# un compte ADMINISTRATEUR ne lit pas ~/.ssh/authorized_keys mais ce fichier-ci, et sshd le
# refuse si d'autres que Administrators/SYSTEM peuvent l'écrire (SID : indépendants de la langue)
New-Item -ItemType Directory -Force -Path 'C:\ProgramData\ssh' | Out-Null
$keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
Copy-Item -Path (Join-Path $PSScriptRoot 'authorized_keys') -Destination $keys -Force
icacls.exe $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F'

if (-not (Get-NetFirewallRule -Name 'golem-sshd' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'golem-sshd' -DisplayName 'GoleM sshd' -Enabled True `
        -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
Set-Service -Name sshd -StartupType Automatic
Restart-Service -Name sshd

# ── la machine ne s'endort pas ───────────────────────────────────────────────────────────
powercfg.exe /change monitor-timeout-ac 0
powercfg.exe /change standby-timeout-ac 0
powercfg.exe /hibernate off

# ── figée : pas de mise à jour ni de redémarrage tout seuls ──────────────────────────────
$au = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
New-Item -Path $au -Force | Out-Null
Set-ItemProperty -Path $au -Name NoAutoUpdate -Value 1 -Type DWord

# chemins longs (pip, dépôts profonds)
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1 -Type DWord

Set-Content -Path 'C:\golem-ready.txt' -Value (Get-Date -Format o)
Stop-Transcript
