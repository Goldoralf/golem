# SPDX-License-Identifier: GPL-3.0-or-later
"""Les prises MIDI de la carte son ne sont pas des instruments (PC Windows, 2026-11-03) : avec le pilote PreSonus,
l'AudioBox iTwo publiait « AudioBox iTwo MIDI In / Out », que Controllers, Drums et les bannières de branchement
proposaient de calibrer. Sous Linux, la carte son active est écartée par son id ALSA ; sous Windows, par le
fabricant qui signe son pilote ASIO et le parent PnP de ses ports. Un module de batterie USB reste."""
from bridge import desktop_midi as M

ITWO = "TUSBAUDIO_ENUM\\VID_194F&PID_0403&KS\\AB5C21071722"
NITRO = "USB\\VID_2467&PID_2026\\0001"
INV = {
    "signer": 'CN="PreSonus Audio Electronics, Inc.", OU=Software Engineering, O="PreSonus Audio Electronics, Inc."',
    "audio": [ITWO, NITRO, "HDAUDIO\\FUNC_01&VEN_10EC"],
    "midi": [
        {"name": "AudioBox iTwo MIDI In", "parent": ITWO, "provider": "PreSonus"},
        {"name": "AudioBox iTwo MIDI Out", "parent": ITWO, "provider": "PreSonus"},
        {"name": "Nitro Max", "parent": NITRO, "provider": "Microsoft"},          # module de batterie audio + MIDI
        {"name": "MPK Mini Mk II", "parent": "USB\\VID_09E8&PID_0045\\x", "provider": "Microsoft"},
        {"name": "Service Test Loopback A", "parent": "SWD\\MIDISRV\\MIDIU_DIAG_TRANSPORT", "provider": "Microsoft"},
    ],
}


def test_les_prises_de_la_carte_active_sont_reconnues_et_rien_d_autre():
    assert M.card_ports_from(INV) == {"audiobox itwo midi in", "audiobox itwo midi out"}


def test_au_moindre_doute_on_n_ecarte_rien():
    assert M.card_ports_from({**INV, "signer": ""}) == set(), "DLL non signée : rien d'écarté"
    assert M.card_ports_from({**INV, "signer": "CN=Microsoft Windows"}) == set(), "un pilote Microsoft ne désigne rien"
    assert M.card_ports_from({**INV, "audio": []}) == set(), "un appareil sans sortie audio n'est pas une carte son"
    assert M.card_ports_from({}) == set() and M.card_ports_from(None) == set()


def test_un_autre_fabricant_signe_le_pilote_et_les_prises_presonus_restent():
    assert M.card_ports_from({**INV, "signer": 'CN="Focusrite Audio Engineering Ltd."'}) == set()


def test_controllers_et_drums_ne_voient_plus_les_prises_de_la_carte(monkeypatch):
    monkeypatch.setattr(M, "ports", lambda: {"in": ["AudioBox iTwo MIDI In", "MPK Mini Mk II", "Nitro Max"],
                                             "out": ["AudioBox iTwo MIDI Out", "Nitro Max"]})
    monkeypatch.setattr(M, "din_port", lambda kind: None)
    monkeypatch.setattr(M, "usb_ids", lambda names=None: {})
    monkeypatch.setattr(M, "card_ports", lambda names: {"audiobox itwo midi in", "audiobox itwo midi out"})
    assert [d["name"] for d in M.usb_devices()] == ["MPK Mini Mk II", "Nitro Max"]


def test_sur_la_boucle_asyncio_card_ports_ne_bloque_jamais(monkeypatch):
    """L'inventaire coûte ~3 s : appelé depuis la boucle, il part en fond et rend tout de suite (leçon du 2026-11-03)."""
    import asyncio
    import threading
    import time
    from bridge import desktop_audio
    monkeypatch.setattr(M.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", lambda: {"driver": "AudioBox ASIO Driver"})
    monkeypatch.setattr(M, "_CARD_PORTS", {"key": None, "val": set(), "busy": None})
    release = threading.Event()

    def slow(driver):
        release.wait(5)
        return INV
    monkeypatch.setattr(M, "_card_inventory", slow)

    async def on_loop():
        t0 = time.monotonic()
        got = M.card_ports(["AudioBox iTwo MIDI In"])
        return got, time.monotonic() - t0
    got, took = asyncio.new_event_loop().run_until_complete(on_loop())
    assert got == set() and took < 0.5, "la boucle n'attend pas l'inventaire"
    release.set()
    M._CARD_PORTS["busy"].join(5)
    assert M.card_ports(["AudioBox iTwo MIDI In"]) == {"audiobox itwo midi in", "audiobox itwo midi out"}


def test_hors_windows_card_ports_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(M.sys, "platform", "linux")
    assert M.card_ports(["AudioBox iTwo MIDI In"]) == set()
