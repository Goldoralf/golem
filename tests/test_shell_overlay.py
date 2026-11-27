# SPDX-License-Identifier: GPL-3.0-or-later
"""Le kit de référence de la coquille vide (tools/shell_overlay.py) : le matériel déclaré et la prise de démo, rejoués
pendant l'extraction au lieu d'être branchés ou greffés à la main."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shell_overlay as O      # noqa: E402
import shell_snapshot as S     # noqa: E402

RACK = {"what": "rack", "recorded": {"commit": "abc"}, "rack": {"variant": "drums+keys", "seen": ["Nitro", "MPK Mini"]},
        "set": {"/api/controllers": {"controllers": [{"name": "MPK", "usb": "1", "port": 1}]},
                "/api/soundcard": {"card": {"name": "Volt 276"}, "usb": [{"name": "MPK", "kind": "midi"}]}},
        "state": {"hotplug": {"devices": [{"name": "MPK"}]}},
        "examples": {"bound": {"skip_gestures": True, "set": {"/api/controllers": {"controllers": []}},
                               "state": {"hotplug": {"devices": []}}}}}
TAKE = {"what": "take", "add": {"/api/loops": {"key": "takes", "id": "dir", "entries": [{"dir": "perf-1", "files": ["Mix.wav"]}]}},
        "whole": {"/api/loop-peaks/perf-1/Mix.wav": {"peaks": [1, 2]}},
        "media": {"/api/loop/perf-1/Mix.wav": {"file": "media/perf-1/Mix.wav", "type": "audio/ogg"}}}


def test_une_lecture_garde_ce_que_le_kit_ne_remplace_pas():
    ov = O.Overlay([(RACK, None)])
    live = {"card": {"name": "USB Audio"}, "bsize": 192, "usb": [], "new_key_of_the_bridge": True}
    out = ov.read("/api/soundcard", live)
    assert out["card"] == {"name": "Volt 276"} and out["usb"][0]["name"] == "MPK"
    assert out["bsize"] == 192 and out["new_key_of_the_bridge"] is True          # le code extrait garde la main sur le reste
    assert live["card"] == {"name": "USB Audio"}                                  # jamais modifié en place
    assert ov.read("/api/presets", {"x": 1}) == {"x": 1} and not ov.covers("/api/presets")
    assert ov.covers("/api/soundcard?card=x") and ov.read("/api/soundcard?card=x", live)["card"]["name"] == "Volt 276"


def test_l_etat_et_un_exemple_ont_leurs_propres_valeurs():
    ov = O.Overlay([(RACK, None)])
    assert ov.state({"hotplug": {"devices": []}, "scene_id": "B"}) == {"hotplug": {"devices": [{"name": "MPK"}]}, "scene_id": "B"}
    assert ov.state({"hotplug": 1}, example="bound")["hotplug"] == {"devices": []}
    assert ov.read("/api/controllers", {"controllers": [1]}, example="bound") == {"controllers": []}
    assert ov.read("/api/controllers", {"controllers": [1]}, example="other")["controllers"][0]["name"] == "MPK"
    assert ov.skip_gestures("bound") and not ov.skip_gestures("other")
    assert ov.rack()["variant"] == "drums+keys" and ov.rack()["recorded"] == {"commit": "abc"}


def test_la_prise_s_ajoute_a_la_liste_et_apporte_ses_lectures_entieres():
    ov = O.Overlay([(TAKE, None)])
    out = ov.read("/api/loops", {"takes": [{"dir": "perf-0"}]})
    assert [t["dir"] for t in out["takes"]] == ["perf-0", "perf-1"]
    assert [t["dir"] for t in ov.read("/api/loops", out)["takes"]] == ["perf-0", "perf-1"]      # pas deux fois
    assert ov.whole("/api/loop-peaks/perf-1/Mix.wav") == {"peaks": [1, 2]} and ov.whole("/api/loops") is None
    assert ov.covers("/api/loop-peaks/perf-1/Mix.wav") and ov.read("/api/loop-peaks/perf-1/Mix.wav", None) == {"peaks": [1, 2]}
    assert ov.rack() is None and not O.Overlay() and bool(ov)


def test_une_forme_qui_a_vieilli_se_dit():
    ov = O.Overlay([(RACK, None)])
    same = {"controllers": [{"name": "Volt", "usb": "9", "port": 3}]}
    assert ov.shape_warnings("/api/controllers", same) == []
    newer = {"controllers": [{"name": "Volt", "usb": "9", "port": 3, "battery": None}]}
    w = ov.shape_warnings("/api/controllers", newer)
    assert len(w) == 1 and "no battery" in w[0] and "re-record" in w[0]
    older = {"controllers": [{"name": "Volt", "usb": "9"}]}
    assert "no longer returns: port" in ov.shape_warnings("/api/controllers", older)[0]
    assert ov.shape_warnings("/api/controllers", {"controllers": []}) == []        # rien à comparer : rien d'affirmé


def test_l_instantane_ecrit_passe_par_le_kit(tmp_path):
    kit = tmp_path / "kit"
    (kit / "media" / "perf-1").mkdir(parents=True)
    (kit / "media" / "perf-1" / "Mix.wav").write_bytes(b"ogg")
    out = tmp_path / "snap"
    res = {"written": ["/api/soundcard", "/api/loops", "/api/state", "/api/presets"]}
    for read, data in (("/api/soundcard", {"card": {"name": "USB Audio"}, "bsize": 192}), ("/api/loops", {"takes": []}),
                       ("/api/state", {"hotplug": {"devices": []}, "scene_id": "A"}), ("/api/presets", [1])):
        p = S.out_path(str(out), read)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(data, open(p, "w"))
    ov = O.Overlay([(RACK, None), (TAKE, str(kit))])
    media, warns = ov.apply_to_snapshot(str(out), res, S.out_path, log=lambda *_: None)
    rd = lambda r: json.load(open(S.out_path(str(out), r)))   # noqa: E731
    assert rd("/api/soundcard") == {"card": {"name": "Volt 276"}, "bsize": 192, "usb": [{"name": "MPK", "kind": "midi"}]}
    assert rd("/api/loops")["takes"][0]["dir"] == "perf-1" and rd("/api/state")["hotplug"]["devices"] == [{"name": "MPK"}]
    assert rd("/api/presets") == [1] and rd("/api/loop-peaks/perf-1/Mix.wav") == {"peaks": [1, 2]}
    assert "/api/loop-peaks/perf-1/Mix.wav" in res["written"]
    assert media == {"/api/loop/perf-1/Mix.wav": {"file": "media/api/loop/perf-1/Mix.wav", "type": "audio/ogg"}}
    assert (out / "media" / "api" / "loop" / "perf-1" / "Mix.wav").read_bytes() == b"ogg" and warns == []


def test_une_prise_abimee_arrete_l_extraction(tmp_path):
    d = tmp_path / "demo-take"
    d.mkdir()
    lay = dict(TAKE, media={"/api/loop/perf-1/Mix.wav": {"file": "media/Mix.wav", "type": "audio/ogg", "sha256": "0" * 64}})
    (d / "take.json").write_text(json.dumps(lay))
    with pytest.raises(RuntimeError, match="missing"):
        O.Overlay.load(rack=None, kit=str(tmp_path), log=lambda *_: None)
    (d / "media").mkdir()
    (d / "media" / "Mix.wav").write_bytes(b"another file")
    with pytest.raises(RuntimeError, match="sha256 differs"):
        O.Overlay.load(rack=None, kit=str(tmp_path), log=lambda *_: None)


def test_sans_kit_l_extraction_le_dit_et_continue(tmp_path):
    said = []
    ov = O.Overlay.load(rack=str(tmp_path / "none.json"), kit=str(tmp_path), log=said.append)
    assert not ov and any("no rack file" in s for s in said) and any("no demo take" in s for s in said)


def test_le_rack_du_depot_est_coherent_avec_les_exemples():
    rack = json.load(open(O.RACK_FILE, encoding="utf-8"))
    assert rack["rack"]["variant"] == "drums+keys" and {"Nitro", "MPK Mini"} <= set(rack["rack"]["seen"])
    names = {ex["name"] for ex in S.EXAMPLES}
    assert set(rack.get("examples") or {}) <= names                      # un exemple renommé ne laisse pas une couche orpheline
    # un exemple dont le geste demande l'appareil est couvert par le kit
    for ex in S.EXAMPLES:
        if ex.get("rack") and ex.get("gestures"):
            assert rack["examples"][ex["name"]]["skip_gestures"] is True, ex["name"]
    ports = [c["port"] for c in rack["set"]["/api/controllers"]["controllers"]]
    assert ports == sorted(set(ports))
    assert all(S.MACHINE.match(r) for r in rack["set"])                  # le kit ne touche que des lectures « machine »
    assert not S.leaks(rack)                                             # rien de personnel dans le dépôt public


def test_le_rack_se_reenregistre_en_deux_passes(tmp_path):
    """Pas assez de ports USB pour le Nitro ET le MPK : une passe par appareil, fusionnées par appareil."""
    def snap(d, devices, card_present, seen, bound=None):
        (d / "examples").mkdir(parents=True)
        json.dump({"commit": "c" * 40, "made": "2026-12-01", "rack": {"seen": seen}}, open(d / "SNAPSHOT.json", "w"))
        for read, data in (("/api/controllers", {"controllers": devices}), ("/api/devices", {"devices": devices}),
                           ("/api/soundcard", {"card": {"name": "Volt 276", "present": card_present}, "midi": {"present": True},
                                               "usb": [{"name": x["name"], "kind": x.get("kind", "midi")} for x in devices]}),
                           ("/api/cards", {"connected": [{"id": "V276", "name": "Universal Audio Volt 276"}], "active": ""}),
                           ("/api/state", {"hotplug": {"devices": [{"usb": x["usb"], "name": x["name"], **({"kind": x["kind"]} if "kind" in x else {})}
                                                       for x in devices], "events": []}})):
            p = S.out_path(str(d), read)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump(data, open(p, "w"))
        if bound:
            json.dump({"reads": {"/api/devices": {"devices": bound}, "/api/sandbox": {}}}, open(d / "examples" / "reference-drums-bound.json", "w"))
        return str(d)
    keys = snap(tmp_path / "keys", [{"name": "Volt 276", "usb": "v", "port": 1}, {"name": "MPK Mini Mk II", "usb": "m", "port": 2}],
                True, ["Volt 276", "MPK Mini"])
    # une AUTRE carte du poste (un dongle USB, kind « audio ») n'entre pas dans le rack de référence (2026-11-27)
    dongle = {"name": "USB Audio", "usb": "d", "kind": "audio", "port": 3}
    drums = snap(tmp_path / "drums", [{"name": "Volt 276", "usb": "v", "port": 1}, {"name": "Alesis Nitro", "usb": "n", "port": 2}, dongle],
                 True, ["Volt 276", "Nitro"], bound=[{"name": "Alesis Nitro", "usb": "n", "roles": ["drums"], "port": 1}, dongle])
    lay = O.rack_from_snapshots([keys, drums])
    ctl = lay["set"]["/api/controllers"]["controllers"]
    assert [(c["name"], c["port"]) for c in ctl] == [("Volt 276", 1), ("MPK Mini Mk II", 2), ("Alesis Nitro", 3)]
    assert [u["name"] for u in lay["set"]["/api/soundcard"]["usb"]] == ["Volt 276", "MPK Mini Mk II", "Alesis Nitro"]
    assert lay["rack"] == {"variant": "drums+keys", "seen": ["MPK Mini", "Nitro", "Volt 276"]}
    # le Nitro lié tel que sa passe l'a relevé, + les appareils de l'autre passe (tous branchés ensemble), sans le dongle
    assert [(d["name"], d["port"]) for d in lay["examples"]["reference-drums-bound"]["set"]["/api/devices"]["devices"]] == \
        [("Alesis Nitro", 1), ("Volt 276", 2), ("MPK Mini Mk II", 3)]
    assert lay["examples"]["reference-drums-bound"]["set"]["/api/devices"]["devices"][0]["roles"] == ["drums"]
    assert len(lay["state"]["hotplug"]["devices"]) == 3 and "one pass per USB device" in lay["recorded"]["how"]
