# SPDX-License-Identifier: GPL-3.0-or-later
"""La fenêtre de Vital (docs/plugin-window.md) : le son retouché relu dans le vst_chunk, rangé en preset « (edited) »,
et le bouton qui dit pourquoi il ne s'ouvre pas.

Mesuré le 2026-10-14 sur l'instance vivante : l'état de Vital est un vst_chunk JUCE (VstW/CcnK) qui porte le JSON
.vital entier ; deux lectures sans retouche rendent le même état à l'octet."""
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bridge import vital  # noqa: E402


def _chunk(tmp_path, preset):
    src = tmp_path / "src.vital"
    src.write_text(json.dumps(preset))
    return vital.splice_chunk(open(vital.TEMPLATE_CHUNK).read(), str(src))


def test_le_json_vital_se_relit_dans_le_chunk(tmp_path):
    preset = {"preset_name": "Pad", "author": "x", "settings": {"macro_control_1": 0.42}, "synth_version": "1.5.5"}
    data = vital.chunk_json(_chunk(tmp_path, preset))
    assert json.loads(data)["settings"]["macro_control_1"] == 0.42


def test_un_etat_qui_n_est_pas_vital_est_refuse():
    import base64
    import pytest
    with pytest.raises(ValueError):
        vital.chunk_json(base64.b64encode(b"\0" * 64).decode())


def test_une_retouche_est_rangee_a_part_puis_reecrite_au_meme_endroit(tmp_path, monkeypatch):
    monkeypatch.setattr(vital, "VITAL_DIR", str(tmp_path / "lib"))
    (tmp_path / "lib" / "user").mkdir(parents=True)
    (tmp_path / "lib" / "user" / "Pad.vital").write_text(json.dumps({"preset_name": "Warm Pad", "settings": {}}))
    data = json.dumps({"preset_name": "", "settings": {"macro_control_1": 0.5}}).encode()
    pid, name = vital.save_edited(data, "Pad", "vital-1")
    assert name == "Warm Pad (edited)"
    assert os.path.isfile(tmp_path / "lib" / "edited" / f"{pid}.vital")
    assert json.loads((tmp_path / "lib" / "user" / "Pad.vital").read_text())["preset_name"] == "Warm Pad"   # l'origine intacte
    # retoucher le son déjà retouché réécrit le même fichier, sans « (edited) (edited) »
    pid2, name2 = vital.save_edited(data, pid, "vital-1")
    assert (pid2, name2) == (pid, "Warm Pad (edited)")
    assert len(os.listdir(tmp_path / "lib" / "edited")) == 1


def _req(host):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=host))


def test_sous_linux_la_vue_marche_aussi_depuis_une_tablette(monkeypatch):
    from bridge import routes_content as R, plugin_view
    monkeypatch.setattr(R.sys, "platform", "linux")
    monkeypatch.setattr(plugin_view, "reaper_display", lambda: (":99", ""))
    assert R.plugin_window_caps(_req("192.168.0.22")) == {"available": True, "mode": "view"}
    monkeypatch.setattr(plugin_view, "reaper_display", lambda: None)
    caps = R.plugin_window_caps(_req("127.0.0.1"))
    assert caps["available"] is False and caps["why"]


def test_sous_windows_la_vraie_fenetre_reste_sur_l_ecran_de_la_machine(monkeypatch):
    from bridge import routes_content as R
    monkeypatch.setattr(R.sys, "platform", "win32")
    assert R.plugin_window_caps(_req("127.0.0.1")) == {"available": True, "mode": "native"}
    caps = R.plugin_window_caps(_req("192.168.0.22"))
    assert caps["available"] is False and "tablet" in caps["why"]


def test_un_geste_mal_forme_est_refuse(monkeypatch):
    from bridge import routes_content as R
    monkeypatch.setattr(R.sys, "platform", "linux")
    assert R.plugin_view_input("vital-1", {"ev": "drag", "x": 0, "y": 0}).status_code == 400
    assert R.plugin_view_input("../x", {"ev": "down", "x": 0, "y": 0}).status_code == 400
    assert R.plugin_view_input("vital-1", {"ev": "down", "x": "a", "y": 0}).status_code == 400
