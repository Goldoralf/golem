# SPDX-License-Identifier: GPL-3.0-or-later
"""L'ÉTAT DES BLOCS (docs/block-status.md). Ce que ces tests gardent : un plugin absent se lit dans
l'INVENTAIRE de Reaper et le CONSTAT de golem_rig l'emporte ; sans inventaire on ne barre rien ; une
capture est prête / à télécharger (golem.fm, TONE3000) / indisponible / vide ; un fichier effacé du
disque n'est plus « résolu » ; le résumé du bandeau compte juste ; un remplaçant est de la même
catégorie et disponible ici ; le battement publie `caps`."""
import json
import os

import pytest

from bridge import blockstatus as BS, config as C, rig


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr(BS.sys, "platform", "linux")
    presets = tmp_path / "presets"; presets.mkdir()
    monkeypatch.setattr(BS, "INVENTORY", str(presets / ".fx-inventory.json"))
    monkeypatch.setattr(BS, "OBSERVED", str(presets / ".rig-plugins.json"))
    for slot in (BS._INV,):
        slot.update(mtime=None, val=None)
    # effects.json réduit : trois plugins, une capture, un moteur à part, une quarantaine
    fx = {"effects": [
        {"type": "chorus", "category": "modulation", "engine": "plugin", "plugin": "Calf Multi Chorus"},
        {"type": "flanger", "category": "modulation", "engine": "plugin", "plugin": "Calf Flanger"},
        {"type": "reverb-shimmer", "category": "reverb", "engine": "plugin", "plugin": "Gxshimmizita"},
        {"type": "deesser", "category": "dynamics", "plugin": "golem_deesser"},
        {"type": "cab", "category": "cab", "engine": "plugin", "plugin": "x42 - IR Convolver Mono"},
        {"type": "piano", "category": "keys", "engine": "sfizz"},
        {"type": "phaser", "category": "modulation", "engine": "plugin", "plugin": "Calf Phaser", "roles": ["guitar"]},
        {"type": "detune", "category": "modulation", "engine": "plugin", "plugin": "GxDetune", "quarantine": "crashes Reaper"}]}
    fxp = tmp_path / "effects.json"; fxp.write_text(json.dumps(fx))
    monkeypatch.setattr(C, "EFFECTS", str(fxp))
    BS._EFFECTS.update(mtime=None, val=None)
    monkeypatch.setattr(BS, "aliases", lambda: {"chorus": ["Calf Multi Chorus"]})
    monkeypatch.setattr(rig, "quarantined_types", lambda: {"detune": "crashes Reaper"})
    return presets


def _inv(presets, names):
    (presets / ".fx-inventory.json").write_text(json.dumps({"at": 1, "reaper": "7.79", "fx": names}))
    BS._INV.update(mtime=None, val=None)


def test_sans_inventaire_on_ne_barre_rien(machine):
    assert BS.plugin_state("reverb-shimmer") is None
    assert BS.block_state({"type": "reverb-shimmer"})["state"] == "ready"
    assert BS.caps()["inventory"] is False and BS.caps()["unavailable"] == []


def test_linventaire_de_reaper_dit_ce_qui_manque(machine):
    _inv(machine, [["LV2: Calf Multi Chorus (Calf Studio Gear)", "http://calf/chorus"],
                   ["LV2: Calf Flanger (Calf Studio Gear)", "http://calf/flanger"],
                   ["LV2: x42 - IR Convolver Mono", "urn:x42"],
                   ["JS: GoleM De-esser", "golem/golem_deesser.jsfx"]])
    assert BS.plugin_state("chorus") is True
    assert BS.plugin_state("reverb-shimmer") is False                      # Windows : pas de guitarix
    assert BS.plugin_state("deesser") is True                              # un JSFX se trouve par son FICHIER
    assert BS.plugin_state("piano") is None                                # moteur à part : inconnu, dit comme tel
    s = BS.block_state({"type": "reverb-shimmer"})
    assert s["state"] == "unavailable" and s["reason"] == "plugin"
    assert "reverb-shimmer" in BS.caps()["unavailable"]


def test_le_constat_de_golem_rig_lemporte_sur_linventaire(machine):
    _inv(machine, [["LV2: Calf Multi Chorus (Calf Studio Gear)", ""]])
    (machine / ".rig-plugins.json").write_text(json.dumps({"types": {"chorus": {"ok": False, "at": 1},
                                                                     "reverb-shimmer": {"ok": True, "name": "X", "at": 1}}}))
    assert BS.plugin_state("chorus") is False and BS.plugin_state("reverb-shimmer") is True


def test_un_echec_plus_vieux_que_l_inventaire_ne_barre_plus_un_plugin_installe_depuis(machine):
    """2026-10-22 : Dragonfly installé, REAPER relancé, l'inventaire le voit — le bloc restait « not installed » sur la
    foi d'un rappel d'AVANT l'installation. Un échec plus récent que l'inventaire, lui, fait toujours foi."""
    _inv(machine, [["LV2: Calf Multi Chorus (Calf Studio Gear)", ""]])          # inventaire daté at=1
    (machine / ".rig-plugins.json").write_text(json.dumps({"types": {"chorus": {"ok": False, "at": 0}}}))
    assert BS.plugin_state("chorus") is True
    (machine / ".rig-plugins.json").write_text(json.dumps({"types": {"chorus": {"ok": False, "at": 2}}}))
    assert BS.plugin_state("chorus") is False
    (machine / ".rig-plugins.json").write_text(json.dumps({"types": {"flanger": {"ok": False, "at": 0}}}))
    assert BS.plugin_state("flanger") is False                                   # absent de l'inventaire : reste barré


def test_la_quarantaine_est_indisponible(machine):
    s = BS.block_state({"type": "detune"})
    assert s["state"] == "unavailable" and s["reason"] == "quarantine" and "crashes" in s["detail"]
    assert s["why"] == BS.QUARANTINE_WHY                  # affiché : en anglais, la mesure part en `detail`


@pytest.fixture
def library(machine, tmp_path, monkeypatch):
    from bridge import resolver
    ir = tmp_path / "mesa.wav"; ir.write_bytes(b"RIFF")
    nam = tmp_path / "twin.nam"; nam.write_text("{}")
    files = {"10": str(ir), "11": str(nam), "gone-cap": str(tmp_path / "gone.wav")}
    monkeypatch.setattr(resolver, "_components", lambda: {})
    monkeypatch.setattr(resolver, "_resolve", lambda ref, comps, model=None: files.get(str(ref).split(":")[-1]))
    return files


def test_les_etats_dune_capture(library):
    man = lambda: [{"id": "20", "uid": "t3k:20", "bytes": 5 * 1024 * 1024, "title": "Mesa OS"},
                   {"id": "21", "uid": "t3k:21", "bytes": 0, "title": "Lent", "lent_by": "Sam"}]
    st = lambda b: BS.block_state(b, {}, man)
    assert st({"type": "cab", "ref": "10"})["state"] == "ready"
    assert st({"type": "cab"})["state"] == "empty"
    w = st({"type": "cab", "ref": "11"})                                   # un .nam sur un baffle : mauvaise nature
    assert w["state"] == "unavailable" and w["reason"] == "capture"
    g = st({"type": "cab", "ref": "t3k:20"})
    assert g["state"] == "download" and g["source"] == "golem.fm" and g["uid"] == "t3k:20" and g["bytes"] == 5 * 1024 * 1024
    assert "Sam" in st({"type": "cab", "ref": "21"})["why"]              # un prêt se dit
    t = st({"type": "cab", "ref": "t3k:999"})
    assert t["state"] == "download" and t["source"] == "tone3000" and t["tid"] == "999" and t["bytes"] is None
    assert st({"type": "cab", "ref": "my-own-capture"})["state"] == "unavailable"
    gone = st({"type": "cab", "ref": "gone-cap"})                         # indexée, effacée du disque (id non-TONE3000)
    assert gone["state"] == "unavailable" and "missing on disk" in gone["why"]


def test_le_resume_du_bandeau(library):
    preset = {"id": "p", "lanes_v": 2, "lanes": [{"id": "g", "role": "guitar", "chain": {"pre": [
        {"id": "a", "type": "cab", "ref": "10"}, {"id": "b", "type": "cab", "ref": "t3k:20"},
        {"id": "c", "type": "cab", "ref": "t3k:999"}, {"id": "d", "type": "detune"}, {"id": "e", "type": "cab"}],
        "split": None, "post": []}}]}
    st = BS.preset_status(preset, manifest_fn=lambda: [{"id": "20", "uid": "t3k:20", "bytes": 3000}])
    s = st["summary"]
    assert s["missing"] == 4 and s["download"] == {"n": 2, "bytes": 3000, "unknown": 1}
    assert s["unavailable"] == 1 and s["empty"] == 1
    assert [b["lane"] for b in st["blocks"]] == ["g"] * 5


def test_un_fichier_efface_est_coupe_du_rig(tmp_path):
    gone = str(tmp_path / "x.nam")
    kept = rig._drop_empty_capture([{"id": "a", "type": "amp-nam", "ref": "1"}], lambda ref, model=None: gone)
    assert kept == []


def test_un_remplacant_est_de_la_meme_categorie_et_disponible_ici(machine):
    _inv(machine, [["LV2: Calf Multi Chorus (Calf Studio Gear)", ""], ["LV2: Calf Phaser", ""]])
    alt = BS.alternatives("flanger", "guitar")
    assert alt["category"] == "modulation"
    assert [b["type"] for b in alt["blocks"]] == ["chorus", "phaser"]      # ni lui, ni absent, ni quarantaine
    assert [b["type"] for b in BS.alternatives("flanger", "voice")["blocks"]] == ["chorus"]   # phaser : guitar only


def test_le_battement_publie_caps(machine, monkeypatch):
    from bridge import rigstatus
    _inv(machine, [["LV2: Calf Multi Chorus (Calf Studio Gear)", ""]])
    c = rigstatus.light()["caps"]
    assert c["engine"] == "reaper" and c["inventory"] is True and c["os"]
    assert "reverb-shimmer" in c["unavailable"] and "chorus" not in c["unavailable"]
    assert c["quarantine"] == ["detune"]
    assert c["compo_bed"] is True                                       # docs/compo.md §12


def test_la_capture_suggeree_nest_jamais_posee(library, monkeypatch):
    from bridge import resolver
    monkeypatch.setattr(resolver, "_tones_index", lambda: {"5": {"id": 5, "gear": "cab", "title": "Mesa Oversized 4x12 V30"}})
    b = {"id": "x", "type": "cab", "label": "Mesa Oversized 4x12 V30"}
    s = BS.suggestion(b, lambda: [])
    assert s["ref"] == "5" and s["source"] == "rack" and "ref" not in b
    assert s["uid"] == "local:5"                                           # la forme que golem.fm résout
    monkeypatch.setattr(resolver, "_tones_index", lambda: {})
    g = BS.suggestion(b, lambda: [{"id": "2595", "uid": "t3k:2595", "gear": "cab", "title": "Mesa Oversized 4x12 V30"}])
    assert g["source"] == "golem.fm" and g["uid"] == "t3k:2595"


@pytest.mark.parametrize("desktop", ["win32", "darwin"])
def test_desktop_core_inventory_uses_native_nam(machine, monkeypatch, desktop):
    monkeypatch.setattr(BS.sys, "platform", desktop)
    _inv(machine, [["VST3: NeuralAmpModeler", "nam"]])
    for kind in ("amp", "amp-nam", "cab"):
        assert BS.candidates(kind) == ["VST3: NeuralAmpModeler"]
        assert BS.plugin_state(kind) is True


def test_windows_block_status_matches_strict_catalogue(machine, tmp_path, monkeypatch):
    monkeypatch.setattr(BS.sys, "platform", "win32")
    overlay = tmp_path / "windows.json"
    overlay.write_text(json.dumps({"effects": {
        "chorus": {"plugin": "VST3: Windows Chorus"},
        "flanger": {"unsupported": "mapping unavailable"}}}))
    monkeypatch.setattr(BS, "WINDOWS_EFFECTS", str(overlay))
    monkeypatch.setattr(BS, "_WINDOWS_EFFECTS", BS._mtime_cache())
    _inv(machine, [["VST3: Windows Chorus", "chorus"], ["Calf Flanger", "flanger"]])
    assert BS.candidates("chorus") == ["VST3: Windows Chorus"]
    assert BS.plugin_state("chorus") is True
    assert BS.plugin_state("flanger") is False
    _inv(machine, [["Calf Multi Chorus", "chorus"]])
    assert BS.plugin_state("chorus") is False


def test_native_host_status_is_per_instance_not_shared_type(machine, monkeypatch):
    monkeypatch.setattr(BS.sys, "platform", "win32")
    _inv(machine, [["VST3: Available (Vendor)", "available"]])
    shared = {"vst-host": {"ok": False}}
    available = BS.block_state({"type": "vst-host", "plugin": "VST3: Available (Vendor)"}, obs=shared)
    missing = BS.block_state({"type": "vst-host", "plugin": "VST3: Missing (Vendor)"}, obs=shared)
    assert available["state"] == "ready"
    assert missing["state"] == "unavailable"


def test_desktop_inventory_keeps_requested_plugin_format(machine, tmp_path, monkeypatch):
    monkeypatch.setattr(BS.sys, "platform", "win32")
    overlay = tmp_path / "windows.json"
    overlay.write_text(json.dumps({"effects": {"chorus": {"plugin": "VST3: Same"}}}))
    monkeypatch.setattr(BS, "WINDOWS_EFFECTS", str(overlay))
    monkeypatch.setattr(BS, "_WINDOWS_EFFECTS", BS._mtime_cache())
    _inv(machine, [["CLAP: Same (Vendor)", "same"], ["CLAP: NeuralAmpModeler", "nam"]])
    assert BS.block_state({"type": "vst-host", "plugin": "VST3: Same (Vendor)"})["state"] == "unavailable"
    assert BS.plugin_state("chorus") is False
    assert BS.plugin_state("cab") is False
    _inv(machine, [["VST3: Same (Vendor)", "same"], ["VST3: NeuralAmpModeler (Vendor)", "nam"]])
    assert BS.block_state({"type": "vst-host", "plugin": "VST3: Same (Vendor)"})["state"] == "ready"
    assert BS.plugin_state("chorus") is True
    assert BS.plugin_state("cab") is True


def test_un_bloc_unsupported_sur_un_poste_se_dit_linux_seulement(machine, tmp_path, monkeypatch):
    """La table desktop marque `unsupported` ce que golem_rig ne posera jamais sur cet OS : on le dit
    (« only available on a Linux golem »), même sans inventaire — pas « plugin not installed »."""
    monkeypatch.setattr(BS.sys, "platform", "win32")
    overlay = tmp_path / "windows.json"
    overlay.write_text(json.dumps({"effects": {"chorus": {"unsupported": "Calf absent"}}}))
    monkeypatch.setattr(BS, "WINDOWS_EFFECTS", str(overlay))
    monkeypatch.setattr(BS, "_WINDOWS_EFFECTS", BS._mtime_cache())
    s = BS.block_state({"type": "chorus"})
    assert s["state"] == "unavailable" and s["reason"] == "plugin" and s["linux_only"] is True
    assert s["why"] == BS.LINUX_ONLY_WHY and s["detail"] == "Calf absent"
    assert BS.block_state({"type": "flanger"})["state"] == "ready"          # pas d'inventaire : on ne barre rien d'autre
    monkeypatch.setattr(BS.sys, "platform", "linux")
    assert BS.block_state({"type": "chorus"})["state"] == "ready"           # sur un golem Linux, la table ne compte pas


def test_un_bloc_indisponible_porte_ses_remplacants_proposes(machine, monkeypatch):
    asked = []

    def alts(t, role=None):
        asked.append((t, role))
        return {"category": "reverb", "blocks": [{"type": f"r{i}", "name": f"R{i}"} for i in range(12)]}
    monkeypatch.setattr(BS, "alternatives", alts)
    _inv(machine, [["LV2: x42 - IR Convolver Mono", "urn:x42"]])          # un inventaire : le shimmer y manque
    preset = {"id": "p", "lanes_v": 2, "lanes": [{"id": "b", "role": "bass", "chain": {"pre": [
        {"id": "x", "type": "reverb-shimmer"}, {"id": "y", "type": "reverb-shimmer"}, {"id": "z", "type": "cab"}],
        "split": None, "post": []}}]}
    blocks = BS.preset_status(preset, manifest_fn=lambda: [])["blocks"]
    assert blocks[0]["state"] == "unavailable" and len(blocks[0]["alternatives"]) == BS.ALTS_MAX
    assert blocks[0]["alternatives"][0] == {"type": "r0", "name": "R0"}
    assert asked == [("reverb-shimmer", "bass")]                         # une fois par (type, rôle)
    assert "alternatives" not in blocks[2]                                # vide, pas indisponible


def test_les_remplacants_publies_ne_proposent_pas_de_pedale_midi_externe(machine, monkeypatch):
    monkeypatch.setattr(BS, "alternatives", lambda t, role=None: {"category": "pitch", "blocks": [
        {"type": "whammy-dt", "name": "Whammy DT (MIDI)"}, {"type": "octaver", "name": "Octaver"}]})
    monkeypatch.setattr(BS, "effects", lambda: {"whammy-dt": {"engine": "midi"}, "octaver": {"engine": "lv2"}})
    assert BS._alts("detune", "guitar", {}) == [{"type": "octaver", "name": "Octaver"}]
