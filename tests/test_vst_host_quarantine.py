# SPDX-License-Identifier: GPL-3.0-or-later
"""La quarantaine vaut aussi pour le VST Host (2026-10-01).

Le catalogue met un PLUGIN en quarantaine en marquant son type de bloc (`pitch` -> ReaPitch, qui
fige tout le moteur 435 ms). Le bloc VST Host laisse choisir le plugin par son nom : ReaPitch
réapparaissait dans le sélecteur, posable, compilé, joué."""
from bridge import blockstatus, rig


def test_un_plugin_en_quarantaine_se_reconnait_sous_son_nom_scanne():
    assert rig.quarantined_plugin("VST: ReaPitch (Cockos)")
    assert rig.quarantined_plugin("LV2: GxEchoCat")
    assert rig.quarantined_plugin("VST: ReaDelay (Cockos)") is None
    assert rig.quarantined_plugin("") is None and rig.quarantined_plugin(None) is None


def test_la_compile_retire_un_vst_host_qui_pointe_un_plugin_en_quarantaine():
    blocks = [{"id": "a", "type": "vst-host", "plugin": "VST: ReaPitch (Cockos)"},
              {"id": "b", "type": "vst-host", "plugin": "VST: ReaEQ (Cockos)"},
              {"id": "c", "type": "delay"}]
    assert [b["id"] for b in rig._drop_quarantined(blocks)] == ["b", "c"]


def test_l_etat_du_bloc_dit_la_quarantaine(monkeypatch):
    monkeypatch.setattr(blockstatus.sys, "platform", "win32")
    st = blockstatus.block_state({"id": "a", "type": "vst-host", "plugin": "VST: ReaPitch (Cockos)"},
                                 inv={"qualified_names": {"vst: reapitch (cockos)"}})
    assert st["state"] == "unavailable" and st["reason"] == "quarantine"
