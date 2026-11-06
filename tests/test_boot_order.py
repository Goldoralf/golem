# SPDX-License-Identifier: GPL-3.0-or-later
"""La fenêtre d'abord, REAPER ensuite (2026-10-11) : l'écran de chargement ne se voyait pas, REAPER partait
avant la fenêtre. Le lanceur ouvre la fenêtre, attend sa connexion (`screens` de /api/health), puis lance REAPER —
sans jamais retenir le moteur plus de 4 s pour un écran. `golem server` : REAPER tout de suite."""
from provision import desktop


def test_la_fenetre_est_ouverte_puis_connectee_puis_reaper_part(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "open_window", lambda port, shell, reset, fullscreen: calls.append("window"))
    monkeypatch.setattr(desktop, "wait_for_screen", lambda port, timeout=4.0: calls.append("screen") or True)
    monkeypatch.setattr(desktop, "launch_reaper", lambda args, **k: calls.append("reaper"))
    desktop._bring_up(8770, ["reaper.exe", "-nosplash"], window=True)
    assert calls == ["window", "screen", "reaper"]


def test_sans_fenetre_reaper_part_tout_de_suite(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "open_window", lambda *a, **k: calls.append("window"))
    monkeypatch.setattr(desktop, "launch_reaper", lambda args, **k: calls.append("reaper"))
    monkeypatch.setattr(desktop, "_notify", lambda msg: None)
    monkeypatch.setattr(desktop, "server_message", lambda port: "")
    desktop._bring_up(8770, ["reaper"], window=False)
    assert calls == ["reaper"]


def test_une_fenetre_lente_ne_retient_pas_le_moteur(monkeypatch):
    seen = {"n": 0}
    monkeypatch.setattr(desktop, "bridge_health", lambda port: {"ok": True, "screens": 0})
    monkeypatch.setattr(desktop.time, "sleep", lambda s: seen.__setitem__("n", seen["n"] + 1))
    clock = {"t": 0.0}
    monkeypatch.setattr(desktop.time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 0.5) or clock["t"])
    assert desktop.wait_for_screen(8770, timeout=4.0) is False          # 4 s, puis REAPER part quand même
    monkeypatch.setattr(desktop, "bridge_health", lambda port: {"ok": True, "screens": 1})
    assert desktop.wait_for_screen(8770, timeout=4.0) is True


def test_la_fenetre_principale_de_reaper_se_reconnait_a_sa_classe():
    """Pendant le chargement du projet, le titre n'a pas encore « - REAPER v » : la classe `REAPERwnd` suffit."""
    from provision.desktop_window import is_reaper_main
    assert is_reaper_main("REAPERwnd", "") and is_reaper_main("REAPERwnd", "REAPER v7.27")
    assert is_reaper_main("#32770", "golem-set - REAPER v7.27 - Registered")      # l'ancienne règle reste vraie
    assert not is_reaper_main("#32770", "Save project?") and not is_reaper_main("JUCE_1", "JUCEWindow")
