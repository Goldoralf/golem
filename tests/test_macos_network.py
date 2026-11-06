# SPDX-License-Identifier: GPL-3.0-or-later
"""Network sous macOS (docs/platforms.md, M4) : adresses par `ifconfig`, page qui ne plante plus."""
from subprocess import CompletedProcess

from bridge import connect, desktop_macos, routes_network

IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether 3c:22:fb:00:00:01
\tinet6 fe80::1%en0 prefixlen 64 secured scopeid 0xe
\tinet 192.168.1.42 netmask 0xffffff00 broadcast 192.168.1.255
en1: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 10.0.0.7 netmask 0xffffff00 broadcast 10.0.0.255
en5: flags=8822<BROADCAST,SMART,SIMPLEX,MULTICAST> mtu 1500
\tinet 172.16.0.2 netmask 0xffff0000
utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
\tinet 100.64.0.9 --> 100.64.0.9 netmask 0xffffffff
bridge100: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.2.1 netmask 0xffffff00 broadcast 192.168.2.255
awdl0: flags=8943<UP,BROADCAST,RUNNING,PROMISC,SIMPLEX,MULTICAST> mtu 1500
"""


def test_ifconfig_keeps_physical_running_interfaces_only():
    assert connect.parse_ifconfig(IFCONFIG) == [{"ip": "192.168.1.42", "dev": "en0"},
                                                {"ip": "10.0.0.7", "dev": "en1"}]


def test_the_default_route_comes_first():
    a = connect._mac_addresses(IFCONFIG, primary="10.0.0.7")
    assert a["primary"] == "10.0.0.7" and a["ipv4"][0]["dev"] == "en1" and a["ap"] is False


def test_a_default_route_on_a_virtual_interface_is_not_announced():
    a = connect._mac_addresses(IFCONFIG, primary="100.64.0.9")       # VPN : pas où vit un téléphone
    assert a["primary"] == "192.168.1.42"


def test_bonjour_name_is_the_mac_local_hostname(monkeypatch):
    monkeypatch.setattr(connect.sys, "platform", "darwin")
    monkeypatch.setattr(connect.subprocess, "run", lambda args, **k: CompletedProcess(args, 0, "Williams-MacBook\n", ""))
    assert connect.mdns_host() == "Williams-MacBook.local"


def test_firewall_reading():
    P = desktop_macos.parse_firewall
    assert P("Firewall is disabled. (State = 0)") is True
    assert P("Firewall is enabled. (State = 1)", "The application /x/python3.12 is blocked from incoming connections.") is False
    assert P("Firewall is enabled. (State = 1)", "The application /x/python3.12 is permitted") is True
    assert P("Firewall is enabled. (State = 1)", "") is None
    assert P("") is None


def test_mac_network_status_has_the_page_shape(monkeypatch):
    """L'ancienne réponse n'avait ni `ap` ni `station` : la page lisait `net.ap.up` et plantait."""
    monkeypatch.setenv("GOLEM_BIND", "0.0.0.0")
    monkeypatch.setattr(connect, "addresses", lambda: {"primary": "192.168.1.42",
                        "ipv4": [{"ip": "192.168.1.42", "dev": "en0"}], "ap": False, "ipv6_prefixes": []})
    monkeypatch.setattr(desktop_macos, "firewall_open", lambda: None)
    monkeypatch.setattr(routes_network, "_reach", lambda: {"host": "golem.local", "url": "http://golem.local"})
    s = routes_network._mac_status()
    assert s["macos"] and s["ap"]["up"] is False and s["station"]["ip"] == "192.168.1.42"
    assert s["reachable"] == ["http://192.168.1.42:8770/app/"] and s["local_only"] is False
    for key in ("mode", "radios", "eth", "pending_confirm", "confirm_window_s", "nm_available", "golem"):
        assert key in s


def test_mac_wifi_gestures_are_refused_in_english(monkeypatch):
    import asyncio
    monkeypatch.setattr(routes_network, "DESKTOP", True)
    r = asyncio.run(routes_network.network_join({"ssid": "x"}))
    assert r.status_code == 501 and b"macOS" in r.body
