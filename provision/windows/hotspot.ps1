# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM - le point d'acces mobile de Windows, pour l'onglet Network (bridge/desktop_network.py).
# Pendant du verbe ap-up / ap-down du wrapper Linux (provision/net.sh) : sous Windows c'est le
# « Point d'acces mobile » des Parametres, pilote par l'API WinRT NetworkOperatorTetheringManager.
# Aucun droit administrateur. Il partage la connexion Internet courante — et marche SANS (scène).
#     -Action status | on | off      SSID et mot de passe : variables GOLEM_AP_SSID / GOLEM_AP_PSK
#     (par l'environnement, jamais sur la ligne de commande : elle est lisible par tous)
# Sortie : une ligne JSON {state, ssid, psk, clients, max, profile, error?}
param([string]$Action = 'status')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } |
    Select-Object -First 1
$asAction = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } |
    Select-Object -First 1
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function AwaitAction($op) { $t = $asAction.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }
function Out($o) { $o | ConvertTo-Json -Compress; exit 0 }
try {
    $NetInfo = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]
    $Tether = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
    # (⚠ PowerShell ignore la casse : $TM et $tm seraient LA MÊME variable — d'où ces noms longs)
    # SUR SCÈNE IL N'Y A PAS D'INTERNET, et le point d'accès de Windows « partage une connexion ». MESURÉ
    # le 2026-10-03 (WiFi coupé, poste de dev) : sans profil Internet, n'importe quel profil CONNU suffit
    # — même celui d'une carte débranchée (« Ethernet 2 ») : StartTetheringAsync -> Success, 192.168.137.1.
    # On prend donc le profil Internet s'il existe, sinon le premier profil dont Windows fait un partage.
    $cp = $NetInfo::GetInternetConnectionProfile()
    $tm = $null
    foreach ($p in @($cp) + @($NetInfo::GetConnectionProfiles())) {
        if (-not $p) { continue }
        try { $tm = $Tether::CreateFromConnectionProfile($p); $cp = $p; break } catch { }
    }
    if (-not $tm) { Out @{ state = 'Off'; error = 'Windows has no network profile to start its mobile hotspot from' } }
    $resType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
    $err = $null
    if ($Action -eq 'on') {
        $c = $tm.GetCurrentAccessPointConfiguration()
        if ($env:GOLEM_AP_SSID) { $c.Ssid = $env:GOLEM_AP_SSID }
        if ($env:GOLEM_AP_PSK) { $c.Passphrase = $env:GOLEM_AP_PSK }
        if ($env:GOLEM_AP_SSID -or $env:GOLEM_AP_PSK) { AwaitAction ($tm.ConfigureAccessPointAsync($c)) }
        if ($tm.TetheringOperationalState -ne 'On') {
            $r = Await ($tm.StartTetheringAsync()) $resType
            if ($r.Status -ne 'Success') { $err = "Windows refused to start the access point: $($r.Status) $($r.AdditionalErrorMessage)" }
        }
    } elseif ($Action -eq 'off') {
        if ($env:GOLEM_AP_SSID -or $env:GOLEM_AP_PSK) {
            $c = $tm.GetCurrentAccessPointConfiguration()
            if ($env:GOLEM_AP_SSID) { $c.Ssid = $env:GOLEM_AP_SSID }
            if ($env:GOLEM_AP_PSK) { $c.Passphrase = $env:GOLEM_AP_PSK }
            AwaitAction ($tm.ConfigureAccessPointAsync($c))
        }
        if ($tm.TetheringOperationalState -ne 'Off') {
            $r = Await ($tm.StopTetheringAsync()) $resType
            if ($r.Status -ne 'Success') { $err = "Windows refused to stop the access point: $($r.Status)" }
        }
    } elseif ($env:GOLEM_AP_SSID -or $env:GOLEM_AP_PSK) {
        $c = $tm.GetCurrentAccessPointConfiguration()
        if ($env:GOLEM_AP_SSID) { $c.Ssid = $env:GOLEM_AP_SSID }
        if ($env:GOLEM_AP_PSK) { $c.Passphrase = $env:GOLEM_AP_PSK }
        AwaitAction ($tm.ConfigureAccessPointAsync($c))
    }
    $c = $tm.GetCurrentAccessPointConfiguration()
    Out @{ state = [string]$tm.TetheringOperationalState; ssid = $c.Ssid; psk = $c.Passphrase;
           clients = $tm.ClientCount; max = $tm.MaxClientCount; profile = $cp.ProfileName; error = $err }
} catch {
    Out @{ state = 'Off'; error = $_.Exception.Message }
}
