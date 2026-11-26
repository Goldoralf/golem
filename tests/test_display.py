# SPDX-License-Identifier: GPL-3.0-or-later
"""Les animations de l'écran (Settings ▸ System ▸ Display, 2026-11-25) : le réglage, sa réparation proposée par Health
quand le son claque avec les cases animées, et le conseil du « safe mode » de la carte."""
from types import SimpleNamespace

import pytest

from bridge import config as C
from bridge import display, fixes, health


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_le_reglage_a_un_defaut_et_refuse_l_inconnu(cfg):
    assert display.get() == {"animations": "auto", "blinks": True, "still_tiles": "pedals"}
    assert display.set_("on")["animations"] == "on"
    assert display.set_(blinks=False) == {"animations": "on", "blinks": False, "still_tiles": "pedals"}
    assert display.set_(still_tiles="glyphs")["still_tiles"] == "glyphs"
    with pytest.raises(ValueError):
        display.set_(still_tiles="neon")
    with pytest.raises(ValueError):
        display.set_("sometimes")
    assert display.brief()["animations"] == "on"


def test_health_propose_de_calmer_l_ecran_quand_ca_claque_animations_actives(cfg):
    st = SimpleNamespace(xruns_recent=4)
    assert health._f_display(st)["level"] == "ok", "auto : les cases sont figées sur la machine audio"
    display.set_("on")
    f = health._f_display(st)
    assert f["level"] == "warn" and "clicks" in f["text"]
    assert fixes.suggest(f) == {"action": "display_animations", "params": {"animations": "auto"}}
    plan = fixes.plan("display_animations", {"animations": "auto"})
    assert plan["ok"] and plan["before"]["value"] == "on" and plan["after"]["value"] == "auto"
    assert health._f_display(SimpleNamespace(xruns_recent=0))["level"] == "ok", "pas de clic : rien à proposer"


def test_le_safe_mode_est_un_conseil_jamais_une_alarme(monkeypatch):
    from bridge import desktop_audio
    monkeypatch.setattr(desktop_audio, "asio_safe_mode", lambda: [])
    assert health._f_safemode(None) is None, "sans pilote qui le déclare, le fait n'apparaît pas"
    monkeypatch.setattr(desktop_audio, "asio_safe_mode", lambda: [{"driver": "UniversalAudioUsbAudio", "on": True}])
    f = health._f_safemode(None)
    assert f["level"] == "ok" and "3 ms" in f["advice"]
    monkeypatch.setattr(desktop_audio, "asio_safe_mode", lambda: [{"driver": "UniversalAudioUsbAudio", "on": False}])
    assert "advice" not in health._f_safemode(None)
