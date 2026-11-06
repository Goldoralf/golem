# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bloc VST Host suit la liste REAPER et n'accepte qu'un id de bloc."""

from unittest.mock import patch

from bridge import routes_content as content


def test_catalogue_windows_annonce_vst_host():
    with patch.object(content.sys, "platform", "win32"):
        data = content.get_effects()
    assert data["vst_host"] is True
    assert any(e["type"] == "vst-host" for e in data["effects"])


def test_inventaire_issu_de_reaper():
    with (patch.object(content.sys, "platform", "win32"),
          patch.object(content, "write_command", return_value=72) as send,
          patch.object(content, "_read_json", return_value={"seq": "72", "plugins": [
              {"name": "VST3: Example", "ident": "example"}]}) as read):
        result = content.vst_host_plugins()
    assert result["plugins"][0]["name"] == "VST3: Example"
    assert send.call_args.args[0]["action"] == "vst_list"
    assert read.call_args.args[0].endswith(".vst-host-list.json")


def test_ouverture_refuse_identifiant_invalide():
    with patch.object(content.sys, "platform", "win32"), patch.object(content, "write_command") as send:
        result = content.vst_host_open({"block": "../other"})
    assert result.status_code == 400
    send.assert_not_called()


def test_ouverture_remonte_la_fenetre_du_plugin():
    from provision import desktop, desktop_window

    with (patch.object(content.sys, "platform", "win32"),
          patch.object(content, "write_command") as send,
          patch.object(desktop, "_backend_pids", return_value={42}),
          patch.object(desktop_window, "focus_reaper_fx", return_value=True) as focus):
        result = content.vst_host_open({"block": "vst-host-1"})
    assert result == {"ok": True}
    assert send.call_args.args[0]["action"] == "vst_open"
    focus.assert_called_once_with({42}, "vst-host-1")


def test_parametres_lus_sur_instance_reaper():
    with (patch.object(content.sys, "platform", "win32"),
          patch.object(content, "write_command", return_value=73) as send,
          patch.object(content, "_read_json", return_value={"seq": "73", "found": True,
              "params": [{"i": 0, "name": "Gain", "value": 0.5, "display": "0 dB"},
                         {"i": 119, "name": "MIDI CC 0|0", "value": 0},
                         {"i": 120, "name": "MidiCC 7", "value": 0},
                         {"i": 121, "name": "MIDI-CC #8", "value": 0},
                         {"i": 12, "name": "Pedal Section Active", "value": 1}]})):
        result = content.vst_host_params("vst-host-1")
    assert result["params"][0]["name"] == "Gain"
    assert [p["i"] for p in result["params"]] == [0, 12]
    assert send.call_args.args[0]["action"] == "vst_params"


def test_parametres_refusent_identifiant_invalide():
    with patch.object(content.sys, "platform", "win32"):
        result = content.vst_host_params("../other")
    assert result.status_code == 400


def test_capture_etat_natif_de_l_instance_reaper():
    with (patch.object(content.sys, "platform", "win32"),
          patch.object(content, "write_command", return_value=74) as send,
          patch.object(content, "_read_json", return_value={"seq": "74", "found": True,
              "kind": "vst_chunk", "chunk": "cHJlc2V0", "params": [{"i": 7, "value": 0.42}]})):
        result = content.vst_host_state("vst-host-1")
    assert result == {"kind": "vst_chunk", "chunk": "cHJlc2V0",
                      "params": [{"i": 7, "value": 0.42}]}
    assert send.call_args.args[0]["action"] == "vst_state"


def test_capture_etat_natif_refuse_un_etat_absent():
    with (patch.object(content.sys, "platform", "win32"),
          patch.object(content, "write_command", return_value=74),
          patch.object(content, "_read_json", return_value={"seq": "74", "found": True,
              "kind": "vst_chunk", "chunk": "", "params": []})):
        result = content.vst_host_state("vst-host-1")
    assert result.status_code == 422


def test_scene_retablit_la_valeur_vst_de_base():
    from bridge.scene_bake import _bake_block

    block = {"id": "vst-host-1", "type": "vst-host", "params": {"p7": 0.25}}
    touched = {"vst-host-1": {"p7"}}
    assert _bake_block(block, {}, {"vst-host-1": {"p7": 0.75}}, touched)["params"]["p7"] == 0.75
    assert _bake_block(block, {}, {}, touched)["params"]["p7"] == 0.25


def test_potard_vst_survit_au_patch_sauve_et_recharge(tmp_path, monkeypatch):
    import json
    from bridge import patches
    from bridge.scene_bake import _bake_block

    monkeypatch.setattr(patches, "PATCHES_DIR", str(tmp_path))
    block = {"id": "vst-host-1", "type": "vst-host",
             "plugin": "VST3: Example (Maker)",
             "params": {"p7": 0.25, "_vst_chunk": "cHJlc2V0"}}
    preset = {"id": "source", "name": "Source", "lanes_v": 2,
              "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1",
                         "chain": {"pre": [block], "split": None, "post": []}}],
              "scenes": [{"id": "A"}, {"id": "B", "params": {"vst-host-1": {"p7": 0.75}}}]}
    created = patches.create_from_lane(preset, "guitar-1", name="VST recall")
    path = tmp_path / (created["id"] + ".json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved_block = next(patches.shape_blocks(saved["lanes"][0]["chain"]))
    assert saved_block["params"]["p7"] == 0.25
    assert saved_block["params"]["_vst_chunk"] == "cHJlc2V0"
    saved_b = next(scene for scene in saved["scenes"] if scene["id"] == "B")
    assert saved_b["params"]["vst-host-1"]["p7"] == 0.75

    song = {"id": "song", "name": "Song", "lanes_v": 2,
            "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1",
                       "chain": {"pre": [], "split": None, "post": []}}],
            "scenes": [{"id": "A"}, {"id": "B"}]}
    patches._cache.clear()  # simule une lecture neuve depuis le fichier du patch
    restored, *_ = patches.apply_to(song, created["id"], lane="guitar-1")
    loaded = next(patches.shape_blocks(patches.chain_of(restored, "guitar-1")))
    assert loaded["plugin"] == block["plugin"]
    assert loaded["params"]["_vst_chunk"] == "cHJlc2V0"
    assert _bake_block(loaded, {}, restored["scenes"][1].get("params"),
                       {loaded["id"]: {"p7"}})["params"]["p7"] == 0.75
    assert _bake_block(loaded, {}, restored["scenes"][0].get("params"),
                       {loaded["id"]: {"p7"}})["params"]["p7"] == 0.25


def test_lua_capture_actions_share_host_bypass_filter():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "reaper/Scripts/golem_rig.lua").read_text(encoding="utf-8")
    # Les deux chemins utilisent la même capture testée par tools/check-vst-host.lua.
    for action, names in (("vst_params", "true"), ("vst_state", "false")):
        body = source.split(f'if cmd.action == "{action}" then', 1)[1].split('    return\n', 1)[0]
        assert f"rows = vst_host_param_rows(tr, fx, {names})" in body
