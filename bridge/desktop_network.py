# SPDX-License-Identifier: GPL-3.0-or-later
"""L'onglet Network sous Windows — les MÊMES gestes que le rack Linux (bridge/routes_network.py), par les
outils de Windows au lieu de NetworkManager et du wrapper sudo :

  · lire  : `netsh wlan show interfaces / networks / profiles` (pas de droits) ;
  · rejoindre : un profil WiFi pour l'utilisateur courant (`netsh wlan add profile … user=current`),
    puis `netsh wlan connect` — le « confirmer-ou-revenir » de routes_network s'applique tel quel ;
  · oublier : `netsh wlan delete profile` ;
  · point d'accès : le « Point d'accès mobile » de Windows (provision/windows/hotspot.ps1, WinRT).

⚠ netsh parle la LANGUE DE WINDOWS (« État », « Authentification »…) : on ne lit que ce qui ne se
traduit pas — les SSID, les pourcentages, l'ordre des lignes, la structure « clé : valeur ».
"""
import contextlib
import json
import os
import re
import subprocess
import tempfile
from xml.sax.saxutils import escape

from . import config as C

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _netsh(*args, timeout=20):
    try:
        p = subprocess.run(["netsh", "wlan", *args], capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        out = p.stdout or b""
        # netsh écrit dans la page de code OEM de la console (cp850 en français)
        for enc in ("utf-8", "cp850", "mbcs"):
            try:
                return p.returncode, out.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return p.returncode, out.decode("latin-1")
    except Exception as e:
        return 1, str(e)


def _kv(line):
    m = re.match(r"^\s*(.+?)\s+:\s?(.*?)\s*$", line)
    return (m.group(1).strip(), m.group(2)) if m else (None, None)


def station():
    """{ssid, signal, connected} de l'interface WiFi, et le nombre d'interfaces."""
    rc, out = _netsh("show", "interfaces")
    radios, ssid, signal = 0, None, None
    for line in out.splitlines():
        k, v = _kv(line)
        if not k:
            continue
        if k.lower() in ("guid",):
            radios += 1
        elif k == "SSID":
            ssid = v or None
        elif k == "Signal":
            m = re.match(r"(\d+)", v)
            signal = int(m.group(1)) if m else None
    return {"ssid": ssid, "signal": signal, "radios": radios}


def scan():
    rc, out = _netsh("show", "networks", "mode=bssid", timeout=30)
    nets, cur = [], None
    current = station()["ssid"]
    for line in out.splitlines():
        m = re.match(r"^SSID \d+\s*:\s?(.*)$", line.strip())
        if m:
            cur = {"ssid": m.group(1).strip(), "signal": 0, "security": "", "in_use": False}
            if cur["ssid"]:
                nets.append(cur)
            continue
        if cur is None:
            continue
        k, v = _kv(line)
        if k and k.lower().startswith("authenti") and not cur["security"]:
            # « Ouvert » / « Open » = pas de mot de passe ; le reste se protège
            cur["security"] = "--" if re.match(r"(?i)^(open|ouvert)", v) else v
        elif k == "Signal":
            mm = re.match(r"(\d+)", v)
            if mm:
                cur["signal"] = max(cur["signal"], int(mm.group(1)))
    for n in nets:
        n["in_use"] = n["ssid"] == current
    nets.sort(key=lambda n: -n["signal"])
    return nets


def known():
    rc, out = _netsh("show", "profiles")
    names = []
    for line in out.splitlines():
        if not line.startswith("    "):
            continue
        k, v = _kv(line)
        if k and v and not v.startswith("<"):
            names.append({"name": v, "autoconnect": True})
    return names


def _profile_xml(ssid, psk):
    hexid = ssid.encode("utf-8").hex().upper()
    sec = (f"<authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption>"
           f"<useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType>"
           f"<protected>false</protected><keyMaterial>{escape(psk)}</keyMaterial></sharedKey>") if psk else \
          "<authEncryption><authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption>"
    return (f'<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
            f"<name>{escape(ssid)}</name><SSIDConfig><SSID><hex>{hexid}</hex><name>{escape(ssid)}</name></SSID></SSIDConfig>"
            f"<connectionType>ESS</connectionType><connectionMode>auto</connectionMode>"
            f"<MSM><security>{sec}</security></MSM></WLANProfile>")


def join(ssid, psk=None):
    """Rejoint `ssid` : avec un mot de passe, le profil est (re)posé pour l'utilisateur courant ; sans, on
    se sert du profil connu. Le fichier du profil (qui porte le mot de passe) est effacé aussitôt."""
    if psk is not None or ssid not in [k["name"] for k in known()]:
        fd, path = tempfile.mkstemp(suffix=".xml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_profile_xml(ssid, psk or ""))
            rc, out = _netsh("add", "profile", f"filename={path}", "user=current")
            if rc != 0:
                return rc, out
        finally:
            os.unlink(path)
    return _netsh("connect", f"name={ssid}", f"ssid={ssid}")


def up(name):
    return _netsh("connect", f"name={name}")


def forget(name):
    return _netsh("delete", "profile", f"name={name}")


def hotspot(action="status", ssid=None, psk=None):
    script = os.path.join(C.ROOT, "provision", "windows", "hotspot.ps1")
    env = {**os.environ, "GOLEM_AP_SSID": ssid or "", "GOLEM_AP_PSK": psk or ""}
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                            "-Action", action], capture_output=True, text=True, encoding="utf-8",
                           timeout=60, env=env, creationflags=NO_WINDOW)
        return json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as e:
        return {"state": "Off", "error": str(e)}


FIREWALL_RULE = "GoleM - bridge"     # posée par install-system.ps1 -Firewall : le port, TOUS les réseaux


def reachability():
    """{rule} : la règle du pare-feu est-elle là ? Elle ouvre le port sur tous les réseaux — maison
    (« Public » ou « Privé » pour Windows, peu importe) comme point d'accès de scène : la garde, c'est
    l'appairement des appareils (bridge/auth.py), comme sur le rack."""
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            f"[bool](Get-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -ErrorAction SilentlyContinue | "
                            "Where-Object Enabled -eq 'True')"],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        return {"rule": p.stdout.strip().lower() == "true"}
    except Exception:
        return {"rule": None}


def open_firewall():
    """Pose la règle du pare-feu DEPUIS LA PAGE, pour une installation faite avant qu'elle existe : le même
    script élevé que l'installateur (install-system.ps1 -Firewall), donc UNE invite Windows (UAC) que
    l'utilisateur approuve à l'écran. Rend (ok, journal)."""
    import sys
    script = os.path.join(C.ROOT, "provision", "windows", "install-system.ps1")
    fd, logf = tempfile.mkstemp(suffix=".log", prefix="golem-firewall-")
    os.close(fd)
    py = getattr(sys, "_base_executable", None) or sys.executable
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    inner = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f'"{script}"', "-Log", f'"{logf}"',
             "-Firewall", "-BridgePython", f'"{py}"']
    # le reçu d'install (docs/uninstall.md §9.2) : les règles posées ET celles de Windows retirées y sont notées
    from . import install_receipt
    rcpt = install_receipt.path()
    if rcpt:
        inner += ["-Receipt", f'"{rcpt}"']
    cmd = ("try { $p = Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
           "-ArgumentList @(" + ",".join(q(a) for a in inner) + "); exit $p.ExitCode } "
           "catch { Write-Output $_.Exception.Message; exit 1223 }")
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True,
                           text=True, timeout=300, creationflags=NO_WINDOW)
        with open(logf, encoding="utf-8-sig", errors="replace") as f:
            text = f.read().strip()
        if p.returncode == 1223:
            # le motif EXACT : « annulée par l'utilisateur » n'est pas « la fenêtre n'est jamais apparue »
            return False, "Windows permission was not granted: " + (p.stdout or "").strip()
        return p.returncode == 0, text
    finally:
        with contextlib.suppress(OSError):
            os.unlink(logf)
        if rcpt:
            install_receipt.merge_pending()


def lan_ips():
    """Les adresses IPv4 de ce poste sur ses réseaux (pour dire où GoleM POURRAIT être joint)."""
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                            "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' "
                            "-and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress"],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    except Exception:
        return []
