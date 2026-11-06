# SPDX-License-Identifier: GPL-3.0-or-later
"""reaper.ini : la carte de REAPER est la carte ACTIVE en ALSA — jamais la Volt de l'auteur par défaut (2026-11-03 :
un golem neuf avec une PreSonus iTwo restait figé sur « Error opening devices », JACK puis hw:V276 absente)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path, monkeypatch, ini_text, card, present):
    spec = importlib.util.spec_from_file_location("reaper_ini_setup_audio", ROOT / "provision/reaper-ini-setup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ini = tmp_path / "reaper.ini"
    ini.write_text(ini_text, encoding="latin-1")
    monkeypatch.setattr(m, "INI", str(ini))
    monkeypatch.setattr(m, "reaper_running", lambda: False)
    monkeypatch.setattr(m, "_read_keys_sources", lambda: (None, None))
    monkeypatch.setattr(m, "keys_name_patterns", lambda *a: ([], ""))
    monkeypatch.setattr(m, "write_keys_sidecar", lambda *a: None)
    monkeypatch.setattr(m, "midi_enable_keys", lambda: ({}, ""))
    monkeypatch.setattr(m, "midi_enable_out", lambda: ({}, ""))
    monkeypatch.setattr(m, "active_card", lambda: card)
    monkeypatch.setattr(m, "card_present", lambda dev: dev in present)
    m.main()
    return dict(ln.split("=", 1) for ln in ini.read_text(encoding="latin-1").splitlines() if "=" in ln)


def test_ini_vierge_prend_la_carte_branchee_en_alsa(tmp_path, monkeypatch):
    v = _run(tmp_path, monkeypatch, "[reaper]\n", "iTwo", {"hw:iTwo"})
    assert v["linux_audio_mode"] == "1"
    assert v["alsa_indev"] == v["alsa_outdev"] == "hw:iTwo"
    assert "V276" not in (tmp_path / "reaper.ini").read_text(encoding="latin-1")


def test_aucune_carte_peripherique_null(tmp_path, monkeypatch):
    """Rien de branché : le PCM `null`, un périphérique muet qui s'ouvre — pas de modale qui fige REAPER."""
    v = _run(tmp_path, monkeypatch, "[reaper]\n", "", set())
    assert v["alsa_indev"] == v["alsa_outdev"] == "null"


def test_carte_absente_remplacee_par_la_carte_branchee(tmp_path, monkeypatch):
    v = _run(tmp_path, monkeypatch, "[reaper]\nalsa_indev=hw:V276\nalsa_outdev=hw:V276\n", "iTwo", {"hw:iTwo"})
    assert v["alsa_indev"] == v["alsa_outdev"] == "hw:iTwo"


def test_null_remplace_quand_une_carte_arrive(tmp_path, monkeypatch):
    v = _run(tmp_path, monkeypatch, "[reaper]\nalsa_indev=null\nalsa_outdev=null\n", "iTwo", {"hw:iTwo"})
    assert v["alsa_indev"] == "hw:iTwo"


def test_carte_presente_de_l_utilisateur_jamais_touchee(tmp_path, monkeypatch):
    """La Volt branchée et choisie : rien ne change, même si une autre carte est active ailleurs."""
    v = _run(tmp_path, monkeypatch, "[reaper]\nlinux_audio_mode=2\nalsa_indev=hw:V276\nalsa_outdev=hw:V276\n",
             "iTwo", {"hw:iTwo", "hw:V276"})
    assert v["alsa_indev"] == "hw:V276" and v["linux_audio_mode"] == "2"


def test_carte_active_absente_rien_ne_bouge(tmp_path, monkeypatch):
    """La carte adoptée (io.json) est débranchée : on ne bascule pas sur une autre carte en douce."""
    v = _run(tmp_path, monkeypatch, "[reaper]\nalsa_indev=hw:V276\nalsa_outdev=hw:V276\n", "V276", {"hw:iTwo"})
    assert v["alsa_indev"] == "hw:V276"
