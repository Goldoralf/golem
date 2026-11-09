# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bloc VST Host suit la liste REAPER et n'accepte qu'un id de bloc."""

from unittest.mock import patch

import pytest

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
    assert any(c.args[0].endswith(".vst-host-list.json") for c in read.call_args_list)


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


# ── Linux (2026-11-09, docs/platforms.md §6.1) : le bloc s'ouvre, la capture NAM reste Windows/macOS ──────────
def test_catalogue_linux_annonce_vst_host_sans_capture_nam():
    with patch.object(content.sys, "platform", "linux"):
        data = content.get_effects()
    assert data["vst_host"] is True and data["vst_capture"] is False
    assert any(e["type"] == "vst-host" for e in data["effects"])
    with patch.object(content.sys, "platform", "win32"):
        assert content.get_effects()["vst_capture"] is True


def test_linux_inventaire_parametres_et_etat_natif_passent():
    with (patch.object(content.sys, "platform", "linux"),
          patch.object(content, "write_command", return_value=81) as send,
          patch.object(content, "_read_json", return_value={"seq": "81", "found": True, "plugins": [
              {"name": "CLAP: Surge XT (Surge Synth Team)", "ident": "surge"}],
              "params": [{"i": 0, "name": "Cutoff", "value": 0.3}],
              "kind": "clap_chunk", "chunk": "c3RhdGU="})):
        assert content.vst_host_plugins()["plugins"][0]["name"].startswith("CLAP: Surge XT")
        assert content.vst_host_params("vst-host-1")["params"][0]["name"] == "Cutoff"
        assert content.vst_host_state("vst-host-1")["kind"] == "clap_chunk"
    assert [c.args[0]["action"] for c in send.call_args_list] == ["vst_list", "vst_params", "vst_state"]


def test_linux_la_capture_nam_reste_refusee():
    with patch.object(content.sys, "platform", "linux"):
        assert content.vst_host_capture_status().status_code == 409


def test_lua_le_bloc_vst_host_n_est_plus_reserve_au_bureau():
    from pathlib import Path
    lua = (Path(__file__).resolve().parents[1] / "reaper" / "Scripts" / "golem_rig.lua").read_text(encoding="utf-8")
    line = next(ln for ln in lua.splitlines() if 'block.type == "vst-host" and not' in ln)
    assert "DESKTOP_FX" not in line
    # la fenêtre (vue filmée) lit l'état à l'ouverture : la garde Surge XT de vst_state vaut aussi pour elle
    pw = lua[lua.index('if cmd.action == "plugin_window" then'):lua.index('if cmd.action == "vst_open" then')]
    assert "surge xt" in pw


# ── lot 2 : les knobs (choix mémorisé par plugin, pédale EXP) ────────────────────────────────────────────────────
def test_knobs_memorises_par_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "VST_KNOBS", str(tmp_path / "vst-knobs.json"))
    plugin = "CLAP: Surge XT (Surge Synth Team)"
    assert content.vst_host_knobs(plugin) == {"plugin": plugin, "knobs": []}
    many = [{"i": i, "name": f"K{i}"} for i in range(12)] + [{"i": 3, "name": "dup"}, {"i": -1}, {"i": True}, "x"]
    saved = content.vst_host_knobs_save({"plugin": plugin, "knobs": many})
    assert [k["i"] for k in saved["knobs"]] == list(range(8))               # 8 au plus, sans doublon ni index invalide
    assert content.vst_host_knobs(plugin)["knobs"] == saved["knobs"]
    assert content.vst_host_knobs("VST3: Other (V)")["knobs"] == []
    content.vst_host_knobs_save({"plugin": plugin, "knobs": []})            # vider = oublier
    assert content.vst_host_knobs(plugin)["knobs"] == []


def test_knobs_refusent_un_nom_qui_n_est_pas_un_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "VST_KNOBS", str(tmp_path / "vst-knobs.json"))
    for bad in ("", "LV2: Calf", "../etc", "JS: golem"):
        assert content.vst_host_knobs_save({"plugin": bad, "knobs": [{"i": 1}]}).status_code == 400
    assert not (tmp_path / "vst-knobs.json").exists()


def test_la_pedale_exp_pilote_un_knob_vst_et_porte_son_nom(monkeypatch):
    from bridge import app as A
    preset = {"exp2": {"block": "host", "param": "p2", "min": 0, "max": 1},
              "lanes": [{"id": "g", "chain": {"pre": [{"id": "host", "type": "vst-host", "plugin": "CLAP: X (V)",
                                                        "knobs": [{"i": 2, "name": "Cutoff"}]}]}}]}
    monkeypatch.setattr(A, "_iter_ui_blocks", lambda p: [b for L in p["lanes"] for b in L["chain"]["pre"]])
    monkeypatch.setattr(A, "_EXP_BLK", dict(A._EXP_BLK))                    # l'état global du bridge reste intact
    monkeypatch.setattr(A.state, "exp2_target", getattr(A.state, "exp2_target", None), raising=False)
    A._set_exp_blk_from(preset)
    assert A._EXP_BLK["label"] == "Cutoff"
    sent = []
    monkeypatch.setattr(A, "_cached_json", lambda *a, **k: {"blocks": {"host": {"track": 3, "fx": 1, "type": "vst-host",
                        "params": {"p2": {"p": 2, "pmin": 0, "pmax": 1}}}}})
    monkeypatch.setattr(A.reaper, "set_fx_param", lambda t, f, p, v: sent.append((t, f, p, round(v, 3))))
    assert A._apply_exp(preset["exp2"], 127) is True and A._apply_exp(preset["exp2"], 0) is True
    assert sent == [(3, 1, 2, 1.0), (3, 1, 2, 0.0)]


# ── la liste propose les plugins NOUVEAUX (2026-11-09) ───────────────────────────────────────────────────────────
def test_la_liste_marque_ce_que_golem_joue_deja_et_cache_les_plugins_de_golem():
    from bridge.store import _read_json as real_read
    plugins = [{"name": "CLAP: Dragonfly Plate Reverb (Michael Willis)"}, {"name": "VST3: Surge XT Effects (Surge Synth Team)"},
               {"name": "CLAP: Surge XT (Surge Synth Team)"}, {"name": "CLAP: GoleM Freeze (GoleM)"},
               {"name": "CLAP: golem Capture (golem)"}, {"name": "VST: ReaPitch (Cockos)"}, {"name": "CLAP: Dexed (Digital Suburban)"}]
    fake = lambda path, default=None: ({"seq": "90", "plugins": plugins} if str(path).endswith(".vst-host-list.json")  # noqa: E731
                                       else real_read(path, default))
    with (patch.object(content.sys, "platform", "linux"),
          patch.object(content, "write_command", return_value=90),
          patch.object(content, "_read_json", side_effect=fake)):
        got = {p["name"]: p for p in content.vst_host_plugins()["plugins"]}
    assert "CLAP: GoleM Freeze (GoleM)" not in got and "CLAP: golem Capture (golem)" not in got     # les plugins de golem
    assert "VST: ReaPitch (Cockos)" not in got                                                        # quarantaine
    assert got["CLAP: Dragonfly Plate Reverb (Michael Willis)"]["block"].startswith("reverb")
    assert got["VST3: Surge XT Effects (Surge Synth Team)"]["block"] == "surge-spring"
    assert "block" not in got["CLAP: Surge XT (Surge Synth Team)"] and "block" not in got["CLAP: Dexed (Digital Suburban)"]


# ── où installer un plugin, et « Rescan plugins » (2026-11-09) ──────────────────────────────────────────────────────
def test_les_dossiers_viennent_de_reaper_ini_sinon_des_defauts(tmp_path, monkeypatch):
    from bridge import reaper_license
    monkeypatch.setattr(reaper_license, "resource_dir", lambda: str(tmp_path))
    with patch.object(content.sys, "platform", "linux"):
        rows = content.vst_host_folders()["folders"]
        assert {r["path"] for r in rows if r["format"] == "VST3"} == {"~/.vst3", "/usr/lib/vst3", "/usr/local/lib/vst3"}
        assert not any(r["custom"] for r in rows)
        (tmp_path / "reaper.ini").write_text("[REAPER]\nvstpath=/opt/vst;~/my vst\nclap_path_linux-x86_64=/opt/clap;%CLAP_PATH%\n"
                                             "[other]\nvstpath=/ignored\n", encoding="latin-1")
        rows = content.vst_host_folders()["folders"]
    assert [r["path"] for r in rows if r["format"] == "CLAP"] == ["/opt/clap"]           # %CLAP_PATH% n'est pas un dossier
    assert [r["path"] for r in rows if r["format"] == "VST3"] == ["/opt/vst", "~/my vst"]
    assert all(r["custom"] for r in rows)


def test_rescan_refuse_pendant_une_prise(monkeypatch):
    import asyncio
    from bridge import reamp
    monkeypatch.setattr(reamp, "busy_reason", lambda idle=True: "a take is recording")
    r = asyncio.run(content.vst_host_rescan())
    assert r.status_code == 409 and b"take" in r.body


def test_rescan_est_un_geste_d_admin_et_les_dossiers_ne_sont_pas_publics():
    from bridge import auth
    assert "/api/vst-host/rescan" in auth.ADMIN_PATHS
    assert any("/api/vst-host/folders".startswith(p) for p in auth.SENSITIVE_GET_PREFIX)


@pytest.mark.parametrize("platform, vst3, clap", [
    ("win32", r"C:\Program Files\Common Files\VST3", r"C:\Program Files\Common Files\CLAP"),
    ("darwin", "~/Library/Audio/Plug-Ins/VST3", "~/Library/Audio/Plug-Ins/CLAP"),
])
def test_les_dossiers_par_defaut_de_windows_et_macos(tmp_path, monkeypatch, platform, vst3, clap):
    from bridge import reaper_license
    monkeypatch.setattr(reaper_license, "resource_dir", lambda: str(tmp_path))
    with patch.object(content.sys, "platform", platform):
        d = content.vst_host_folders()
    assert d["platform"] == platform
    paths = {(r["format"], r["path"]) for r in d["folders"]}
    assert ("VST3", vst3) in paths and ("CLAP", clap) in paths and any(f == "VST" for f, _ in paths)
    # Windows : les chemins de reaper.ini 64 bits (vstpath64, clap_path_win64) remplacent les défauts
    if platform == "win32":
        (tmp_path / "reaper.ini").write_text("[REAPER]\nvstpath64=D:\\VST\nclap_path_win64=D:\\CLAP\n", encoding="latin-1")
        with patch.object(content.sys, "platform", platform):
            rows = content.vst_host_folders()["folders"]
        assert [r["path"] for r in rows if r["format"] == "CLAP"] == ["D:\\CLAP"]
