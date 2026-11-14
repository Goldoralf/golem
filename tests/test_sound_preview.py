# SPDX-License-Identifier: GPL-3.0-or-later
"""Un son de clavier écouté seul (bridge/sound_preview.py, docs/preset-preview.md §9) — demande golem.fm du
2026-11-14, validée par le mainteneur : usine d'abord, une douzaine de DX7 choisis, le piano par variante."""
import json
import os

import pytest

from bridge import config as C
from bridge import sound_preview as S


@pytest.fixture(autouse=True)
def _no_sync_state_write(monkeypatch):
    # les sha256 se mémoïsent dans l'état de la synchro des tones : un test ne l'écrit pas sur le vrai rack
    from bridge import tones_sync
    monkeypatch.setattr(tones_sync, "_save_state", lambda st: None)


def test_the_piano_is_its_variants_never_the_guitar_sfz():
    v = S.piano_variants()
    assert v and all("piano" in os.path.relpath(p, S.SFZ_DIR).lower() for p in v.values())
    assert "golem-pompe" not in v and not any("Shinyguitar" in p for p in v.values())
    from bridge import rigstatus
    assert rigstatus.keys_instruments()[0]["items"] == list(v)        # l'adresse piano:<item> chez golem.fm


def test_factory_sounds_are_the_variants_a_curated_dozen_the_organ_and_every_factory_vital():
    from bridge import vital
    fs = S.factory_sounds()
    pianos = [s for s in fs if s.startswith("piano:")]
    assert len(pianos) == (len(S.piano_variants()) if len(S.piano_variants()) <= 3 else 1)
    assert len([s for s in fs if s.startswith("ep:")]) == len(S.CURATED_EP) == 12
    assert fs.count("organ:b3") == 1
    assert len([s for s in fs if s.startswith("vital:")]) == len([p for p in vital.list_presets() if p["pack"] == "factory"])


def test_the_reference_follows_the_nature_of_the_sound(monkeypatch):
    assert S.describe("ep:piano1/10")["refs"] == ["keys/piano"]       # CP 70 B : un piano acoustique
    assert S.describe("ep:epiano2/22")["refs"] == ["keys/epiano"]     # N.Y.RHODES
    assert S.describe("organ:b3")["refs"] == ["keys/organ"]
    for style, want in (("Pad", ["keys/pad"]), ("Sequence", ["keys/lead"]), ("Keys", ["keys/piano"]),
                        ("Bass", ["keys/bass"]), ("Percussion", []), ("SFX", [])):
        monkeypatch.setattr(S, "vital_by_sha", lambda sha, st=style: {"id": "x", "name": "X", "style": st})
        d = S.describe("vital:abc")
        assert d["refs"] == want, style
        assert bool(d["why"]) == (not want)
    assert isinstance(S.describe("ep:../x/1"), str) and isinstance(S.describe("ep:rom1a/32"), str)
    assert isinstance(S.describe("synth:x"), str)


def test_a_sound_without_a_fitting_phrase_is_skipped_with_its_reason(monkeypatch):
    monkeypatch.setattr(S, "vital_by_sha", lambda sha: {"id": "x", "name": "X", "style": "SFX"})
    r = S.render("vital:abc", lambda: 1)
    assert r["status"] == "skipped" and "SFX" in r["reason"]


def test_a_rendered_sound_is_up_to_date_and_reported_to_golem_fm(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path))
    d = S.describe("organ:b3")
    dst = S.sound_dir("organ:b3")
    os.makedirs(dst)
    clip = os.path.join(dst, "organ.opus")
    open(clip, "wb").write(b"x")
    json.dump({"sound": "organ:b3", "ref": "keys/organ", "refs": ["keys/organ"], "fingerprint": d["fingerprint"],
               "clips": {"keys/organ": {"file": clip, "seconds": 9.5, "sha256": "f" * 64}}},
              open(os.path.join(dst, "preview.json"), "w"))
    monkeypatch.setattr(C, "ROOT", "/")                               # le clip est rangé en chemin absolu ici
    assert S.up_to_date(d, ["keys/organ"]) and not S.up_to_date(dict(d, fingerprint="other"), ["keys/organ"])
    assert S.render("organ:b3", lambda: 1)["reason"] == "up to date"
    assert S.rendered() == [{"sound": "organ:b3", "ref": "keys/organ", "fingerprint": d["fingerprint"],
                             "clips": {"keys/organ": {"sha256": "f" * 64, "seconds": 9.5}}}]


def test_the_sound_alone_patch_holds_only_the_instrument():
    doc = S._doc(S.describe("ep:rom1a/10"))
    lane = doc["lanes"][0]
    assert lane["midi"] and lane["chain"]["chain"] == [S.describe("ep:rom1a/10")["block"]]
    assert [s["id"] for s in doc["scenes"]] == ["A"]


def test_vital_assets_carry_what_the_preset_says(tmp_path):
    from bridge import tones_sync
    p = tmp_path / "Lead.vital"
    p.write_text(json.dumps({"preset_name": "Lead", "author": "me", "preset_style": "Lead", "comments": "bright",
                             "macro1": "CUTOFF", "macro2": "", "settings": {}}))
    m = tones_sync._vital_meta(str(p))
    assert m == {"preset_name": "Lead", "style": "Lead", "author": "me", "comments": "bright",
                 "macros": ["Cutoff", "Macro 2", "Macro 3", "Macro 4"]}
