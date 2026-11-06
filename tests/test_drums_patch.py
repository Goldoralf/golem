# SPDX-License-Identifier: GPL-3.0-or-later
"""Un PATCH batterie (docs/drums-kit.md lot 2 bis) : le rôle drums est accepté par les jobs golem.fm, la
lane d'essai suit le port USB lié en drums (MIDI) puis l'entrée audio Drums, sinon un refus qui dit quoi
faire ; un patch drums n'atterrit jamais sur la guitare ; un drumkit sur une lane audio est retiré."""
import json

import pytest

from bridge import config as C, patches as P, tones_jobs as J
from bridge.state import state

CHAIN = {"pre": [{"id": "kit-1", "type": "drumkit", "params": {"kit": "drums-black-pearl"}}, {"id": "cp-1", "type": "comp"}],
         "split": None, "post": []}


def _blob(monkeypatch, doc):
    monkeypatch.setattr(J, "_job_doc", lambda job, tmp: json.loads(json.dumps(doc)))


def test_le_role_drums_est_accepte_et_la_lane_d_essai_suit_le_port_usb(monkeypatch):
    assert "drums" in J.ROLES
    _blob(monkeypatch, {"name": "Kit", "chain": CHAIN})
    from bridge import inputmap
    monkeypatch.setattr(state, "inputmap", {"card": "hw:V276", "inputs": [{"ch": "1", "role": "guitar", "nth": 1}],
                                            "usb": [{"ch": "usb2", "port": 2, "role": "drums", "bound": True, "device": "Nitro Drum Module"}]}, raising=False)
    preset, role, lane, scenes, settled, missing = J._trial_preset({"action": "patch-try", "sha": "x", "role": "drums"}, "/tmp")
    assert role == "drums" and lane["midi"] is True and lane["in_sel"] == "usb2" and lane["role"] == "drums"


def test_la_lane_d_essai_retombe_sur_l_entree_audio_puis_refuse_en_le_disant(monkeypatch):
    _blob(monkeypatch, {"name": "Kit", "chain": CHAIN})
    monkeypatch.setattr(state, "inputmap", {"card": "hw:XR18", "inputs": [{"ch": "3-4", "role": "drums", "nth": 1, "name": "Drums 1"}], "usb": []}, raising=False)
    preset, role, lane, *_ = J._trial_preset({"action": "patch-try", "sha": "x", "role": "drums"}, "/tmp")
    assert lane["midi"] is False and lane["in_sel"] == "3-4" and lane["in_role"] == "drums"
    monkeypatch.setattr(state, "inputmap", {"card": "hw:V276", "inputs": [{"ch": "1", "role": "guitar", "nth": 1}], "usb": []}, raising=False)
    # ni module ni entrée audio Drums : un Drum Kit ATTEND sur « usb » (2026-10-13) — plus de refus pour un kit MIDI
    preset, role, lane, *_ = J._trial_preset({"action": "patch-try", "sha": "x", "role": "drums"}, "/tmp")
    assert lane["midi"] is True and lane["in_sel"] == "usb"
    # …un kit AUDIO (sans bloc Drum Kit), lui, n'a rien à attendre : refusé en le disant, comme avant
    _blob(monkeypatch, {"name": "Mics", "chain": {"pre": [{"id": "cp-1", "type": "comp"}], "split": None, "post": []}})
    with pytest.raises(RuntimeError, match="bind a drum module on a USB port"):
        J._trial_preset({"action": "patch-try", "sha": "x", "role": "drums"}, "/tmp")


def test_un_patch_drums_n_atterrit_jamais_sur_la_guitare(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PATCHES_DIR", str(tmp_path))
    (tmp_path / "kit.json").write_text(json.dumps({"id": "kit", "name": "Kit", "role": "drums", "chain": CHAIN,
                                                   "scenes": [{"id": "A", "name": "A", "blocks": {}, "params": {}}]}))
    preset = {"id": "p", "lanes_v": 2, "scenes": [{"id": "A", "name": "A", "blocks": {}, "params": {}}],
              "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1", "chain": {"pre": [], "split": None, "post": []}}]}
    with pytest.raises(ValueError, match="no Drums lane"):
        P.apply_to(preset, "kit")
    preset["lanes"].append({"id": "drums-1", "role": "drums", "in_sel": "usb2", "chain": {"pre": [], "split": None, "post": []}})
    out = P.apply_to(preset, "kit")
    p2 = out[0] if isinstance(out, tuple) else out
    L = next(x for x in p2["lanes"] if x["id"] == "drums-1")
    assert [b["type"] for b in L["chain"]["pre"]] == ["drumkit", "comp"]


def test_un_drumkit_sur_une_lane_audio_est_retire_a_la_compile(tmp_path, monkeypatch):
    from bridge import compile_rig
    monkeypatch.setattr(compile_rig, "OUT_DIR", str(tmp_path / "FXChains"))
    monkeypatch.setattr(compile_rig, "IO_PATH", str(tmp_path / "io.json"))
    (tmp_path / "io.json").write_text(json.dumps({"outputs": [{"ch": 1}, {"ch": 2}], "mono_fallback": {"on": False, "gain": -3}}))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / ".cache"))
    preset = {"id": "t-adrums", "paths": [{"id": "drums-1", "name": "drums 1", "input": 3, "stereo": True,
                                           "chain": [{"id": "kit-1", "type": "drumkit", "params": {"kit": "drums-black-pearl"}}, {"id": "cp-1", "type": "comp", "params": {}}], "out": 1}]}
    plan = json.load(open(compile_rig.compile_preset(preset)))
    assert [b["type"] for b in plan["paths"][0]["tracks"][0]["blocks"]] == ["comp"]
