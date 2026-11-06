# SPDX-License-Identifier: GPL-3.0-or-later
"""Lane Drums en MIDI (docs/drums-kit.md lot 2) : la traduction module -> kit, le contrôleur choisi
par PORT puis par RÔLE (jamais l'AKAI pour une batterie), le bloc drumkit compilé avec sa table."""
import json, os

import pytest

from bridge import drumkits, kits, vital


@pytest.fixture(autouse=True)
def _factory_kits(tmp_path, monkeypatch):
    """Le bridge sème ces kits au boot ; les tests à froid le font en tmp."""
    monkeypatch.setattr(kits, "KITS_DIR", str(tmp_path / "kits"))
    kits.seed_factory()


def test_la_table_du_kit_est_validee_et_ressemee():
    bp = kits.get_kit("drums-black-pearl")
    n = kits.kit_notes(bp)
    assert n["kick"] == 36 and n["hh-closed"] == 42 and n["hh-half"] == 46 and n["hh-open"] == 48 and n["tom2"] == 41
    aa = kits.kit_notes(kits.get_kit("drums-aasimonster"))
    assert aa["hh-half"] == 41 and aa["tom4"] == 43 and aa["china"] == 52            # midimap.xml, pas GM
    assert kits.kit_notes({"notes": {"gong": 60, "kick": 200, "snare": 38}}) == {"snare": 38}   # l'inconnu et l'hors-plage sont ignorés


def test_traduction_nitro_vers_black_pearl_et_reperes_de_repli():
    """La Nitro telle qu'elle est MESURÉE (2026-09-23) : onze notes, pédale interrupteur."""
    nitro = drumkits.get("alesis-nitro"); bp = kits.kit_notes(kits.get_kit("drums-black-pearl"))
    tr = drumkits.translation(nitro, bp)
    m = tr["map"]
    assert len(m) == 128 and m[36] == 36 and m[38] == 38 and m[40] == 40            # kick, snare, rim
    assert m[46] == 48 and m[42] == 42 and m[44] == 44                              # HH ouverte/fermée/pédale -> notes AVL
    assert m[23] == -1 and m[21] == -1 and m[41] == -1                              # jamais émises par ce module
    assert m[99] == -1                                                              # note que le module n'a pas
    assert tr["hh"] == {"cc": -1, "open_value": 0, "closed_value": 127, "band_a": 33, "band_b": 66, "positions": 2,
                        "closed": 42, "half": 46, "open": 48}
    assert tr["lost"] == []
    # un kit sans mi-ouverte : la position « half » retombe sur la fermée dans le JSFX
    tr2 = drumkits.translation(nitro, {"kick": 36, "snare": 38, "hh-closed": 42, "hh-open": 46})
    assert tr2["hh"]["half"] == 42 and "tom1" in tr2["lost"]


def test_les_replis_dun_module_plus_riche_que_le_kit():
    """Le MÉCANISME de repli, sur un module synthétique : un tom 4 tombe sur le tom le plus grave que
    le kit possède, un cercle sur sa peau, un splash sur la charleston ouverte. Il ne se teste plus
    par la Nitro, qui n'a ni tom 4 ni splash (mesuré) — un test de mécanisme ne s'appuie pas sur une
    table de terrain, sinon la mesure suivante le casse."""
    bp = kits.kit_notes(kits.get_kit("drums-black-pearl"))
    rich = {"channel": 10, "map": {"41": "tom4", "39": "tom4-rim", "21": "hh-splash", "50": "tom1-rim"},
            "hihat": {"cc": 4, "open_value": 0, "closed_value": 127, "positions": 3, "bands": [33, 66]}}
    tr = drumkits.translation(rich, bp)
    assert tr["map"][41] == bp["tom2"] and tr["map"][39] == bp["tom2-rim"]    # tom4 -> le plus grave du kit
    assert tr["map"][21] == bp["hh-open"] and tr["map"][50] == bp["tom1-rim"]
    assert tr["hh"]["cc"] == 4 and tr["hh"]["positions"] == 3


def test_le_controleur_dune_lane_se_choisit_par_port_puis_par_role(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    (tmp_path / "soundcard.json").write_text(json.dumps({
        "usb1": {"enabled": True, "device": "MPK Mini Mk II", "kind": "midi", "roles": ["keys", "pads"]},
        "usb2": {"enabled": True, "device": "Nitro Drum Module", "kind": "midi", "roles": ["drums"]}}))
    cards = {"MPK Mini Mk II": "hw:II", "Nitro Drum Module": "hw:Nitro"}
    monkeypatch.setattr(vital, "_hw_of", lambda name: cards.get(name))
    from bridge import devices                          # connu ≠ branché : le rang usbN suit la détection
    monkeypatch.setattr(devices, "_usb_list", lambda: [{"name": n, "kind": "midi"} for n in ("MPK Mini Mk II", "Nitro Drum Module") if n in cards])
    assert vital.midi_input_for("drums", "usb2") == "hw:Nitro"
    assert vital.midi_input_for("drums", None) == "hw:Nitro"                        # par rôle
    assert vital.midi_input_for("keys", "usb1") == "hw:II"
    assert vital.midi_input_for("keys", None) == "hw:II"
    cards.pop("Nitro Drum Module")                                                   # module débranché
    assert vital.midi_input_for("drums", "usb2") is None                             # jamais l'AKAI pour une batterie


def test_le_bloc_drumkit_compile_avec_sa_table(tmp_path, monkeypatch):
    from bridge import compile_rig, inputmap, config as C
    monkeypatch.setattr(compile_rig, "OUT_DIR", str(tmp_path / "FXChains"))
    monkeypatch.setattr(compile_rig, "IO_PATH", str(tmp_path / "io.json"))
    (tmp_path / "io.json").write_text(json.dumps({"outputs": [{"ch": 1}, {"ch": 2}], "mono_fallback": {"on": False, "gain": -3}}))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / ".cache"))
    monkeypatch.setattr(inputmap, "usb_ports", lambda: [{"ch": "usb2", "port": 2, "role": "drums", "bound": True,
                                                         "device": "Nitro Drum Module", "kit": {"id": "alesis-nitro", "auto": True}}])
    monkeypatch.setattr(vital, "midi_input_for", lambda role, in_sel: "hw:Nitro" if role == "drums" else "hw:II")
    preset = {"id": "t-drums", "paths": [{"id": "drums-1", "name": "drums 1", "input": 3, "midi": True, "midi_role": "drums", "in_sel": "usb2",
                                          "chain": [{"id": "kit-1", "type": "drumkit", "params": {"kit": "drums-black-pearl"}}], "out": 1}]}
    plan = json.load(open(compile_rig.compile_preset(preset)))
    t = plan["paths"][0]["tracks"][0]
    assert t["midi"] is True and t["midi_in"] == "hw:Nitro" and t["midi_strict"] is True
    b = t["blocks"][0]
    assert b["kit_engine"] == "avldrums" and b["kit_bank"] == "black-pearl" and b["drum_desc"] == "alesis-nitro"
    assert len(b["drum_map"]) == 128 and b["drum_map"][36] == 36 and b["drum_map"][46] == 48 and b["drum_slot"] == 0
    assert b["drum_hh"]["closed"] == 42 and b["drum_hh"]["cc"] == -1     # pédale interrupteur (mesuré)
    assert b["drum_hh"]["positions"] == 2


def test_le_battement_porte_les_kits_de_batterie():
    from bridge import rigstatus
    dk = rigstatus.drum_kits()
    ids = {k["id"]: k for k in dk}
    assert ids["drums-black-pearl"]["playable"] is True and ids["drums-black-pearl"]["engine"] == "avldrums"
    assert ids["drums-aasimonster"]["playable"] is True and ids["drums-aasimonster"]["engine"] == "drumgizmo"   # porté le 2026-09-23
    assert all(set(k) == {"id", "name", "engine", "playable"} for k in dk)


# ── lot 3 : les deux à la fois — le module en audio ET le module en MIDI ───────────────────────
IMAP_BOTH = {"card": "hw:XR18",
             "inputs": [{"ch": "1", "role": "guitar", "nth": 1}, {"ch": "7-8", "role": "drums", "nth": 1, "name": "Drums 1"}],
             "usb": [{"ch": "usb2", "port": 2, "role": "drums", "nth": 2, "bound": True, "device": "Nitro Drum Module",
                      "kit": {"id": "alesis-nitro", "auto": True}}]}

PRESET_BOTH = {"id": "both", "lanes_v": 2, "bpm": 120,
    "scenes": [{"id": "A", "name": "module", "blocks": {}, "params": {}, "lanes": {"drums-2": {"mute": True}}},
               {"id": "B", "name": "kit du rack", "blocks": {}, "params": {}, "lanes": {"drums-1": {"mute": True}}}],
    "lanes": [
      {"id": "drums-1", "role": "drums", "in_role": "drums", "in_nth": 1, "in_sel": "7-8", "name": "Drums audio",
       "out_sel": "1-2", "chain": {"pre": [{"id": "d-comp", "type": "comp"}], "split": None, "post": []}},
      {"id": "drums-2", "role": "drums", "midi": True, "in_sel": "usb2", "name": "Drums MIDI", "out_sel": "1-2",
       "chain": {"pre": [{"id": "kit-1", "type": "drumkit", "params": {"kit": "drums-black-pearl"}}], "split": None, "post": []}}]}


def test_une_lane_audio_et_une_lane_midi_cohabitent(monkeypatch):
    """docs/drums-kit.md lot 3 : le module sonne par la carte ET envoie son MIDI au rack. Deux lanes,
    pas un mode — décision « plusieurs entrées audio = N lanes » (§5). Mesuré sur le rig le
    2026-09-18 : deux pistes matérialisées, la bascule de scène SANS rebuild."""
    import copy
    from bridge import inputmap, scene_bake as sb, store
    monkeypatch.setattr(inputmap, "current", lambda *a, **k: IMAP_BOTH)
    lanes = {L["id"]: L for L in store.lanes_of(copy.deepcopy(PRESET_BOTH))}
    assert lanes["drums-1"]["midi"] is False and lanes["drums-1"]["stereo"] is True      # paire ⛓ : le module en stéréo
    assert lanes["drums-2"]["midi"] is True and lanes["drums-2"]["stereo"] is False      # port USB : le kit du rack
    assert lanes["drums-1"]["role"] == lanes["drums-2"]["role"] == "drums"
    out = sb.to_paths_preset(copy.deepcopy(PRESET_BOTH), "A", union=True)
    assert {q["id"] for q in out["paths"]} == {"drums-1", "drums-2"}
    assert next(q for q in out["paths"] if q["id"] == "drums-2")["midi"] is True


def test_la_scene_choisit_la_SOURCE_module_ou_kit_du_rack(monkeypatch):
    """« Choix module / kit du rack par scène » : c'est un MUTE de lane, donc une bascule d'état
    (union materialization, -150 dB), jamais un rebuild — et ça ne demande aucun mécanisme neuf."""
    import copy
    from bridge import inputmap, scene_bake as sb
    monkeypatch.setattr(inputmap, "current", lambda *a, **k: IMAP_BOTH)
    lv = lambda sc: {q["id"]: q.get("level") for q in sb.to_paths_preset(copy.deepcopy(PRESET_BOTH), sc, union=True)["paths"]}
    assert lv("A") == {"drums-1": None, "drums-2": -150.0}      # le MODULE joue, le kit se tait
    assert lv("B") == {"drums-1": -150.0, "drums-2": None}      # le KIT DU RACK joue, le module se tait


def test_la_prise_grave_le_descripteur_en_service(monkeypatch):
    """lot 3 : le .mid capté est le flux BRUT du module — ses notes ne veulent dire « caisse claire »
    qu'à travers le descripteur en service ce jour-là. Sans lui, la prise d'hier se relirait avec la
    table d'aujourd'hui. On grave l'ID, jamais la table (versionnée ; la copier la figerait)."""
    from bridge import inputmap, monitors
    monkeypatch.setattr(inputmap, "usb_ports", lambda: [
        {"ch": "usb1", "port": 1, "role": "keys", "bound": True, "device": "MPK Mini Mk II"},
        {"ch": "usb2", "port": 2, "role": "drums", "bound": True, "device": "Nitro Drum Module",
         "kit": {"id": "alesis-nitro", "auto": True, "fallback": False}},
        {"ch": "usb3", "port": 3, "role": "none", "bound": False}])
    assert monitors._drums_ctx() == [{"slot": "USB 2", "device": "Nitro Drum Module",
                                      "descriptor": "alesis-nitro", "descriptor_auto": True, "fallback": False}]
    monkeypatch.setattr(inputmap, "usb_ports", lambda: [{"ch": "usb1", "port": 1, "role": "keys", "bound": True}])
    assert monitors._drums_ctx() == []                      # pas de batterie MIDI : rien à graver


def _preset_deux_kits():
    lane = {"id": "drums-1", "role": "drums", "midi": True, "in_sel": "usb", "chain": {"pre": [
        {"type": "drumkit", "id": "kit1", "params": {"kit": "drums-black-pearl"}}], "split": None, "post": []},
        "states": [{"id": "st-A", "blocks": {}, "branches": {}, "params": {}}, {"id": "st-B", "blocks": {}, "branches": {}, "params": {}}]}
    return {"id": "t", "lanes_v": 2, "lanes": [lane], "scenes": [
        {"id": "A", "blocks": {}, "branches": {}, "lanes": {"drums-1": {"state": "st-A"}}, "params": {}},
        {"id": "B", "blocks": {}, "branches": {}, "lanes": {"drums-1": {"state": "st-B"}}, "params": {"kit1": {"kit": "drums-aasimonster"}}},
        {"id": "C", "blocks": {}, "branches": {}, "lanes": {"drums-1": {"state": "st-B"}}, "params": {"kit1": {"kit": "drums-black-pearl"}}}]}


def test_l_union_des_kits_est_bakee_et_la_scene_ne_change_que_le_kit_actif():
    """docs/drums-kit.md lot 2 e (2026-09-23 : « sur une section je passe de Black Pearl à un autre kit, puis je
    reviens »). Le bloc bakė porte l'ENSEMBLE des kits que les scènes utilisent ; `params.kit` reste celui de la scène."""
    from bridge import scene_bake
    p = _preset_deux_kits()
    for sid, active in (("A", "drums-black-pearl"), ("B", "drums-aasimonster"), ("C", "drums-black-pearl")):
        baked = scene_bake.to_paths_preset(p, sid, union=True)
        b = baked["paths"][0]["chain"][0]
        assert b["kits"] == ["drums-aasimonster", "drums-black-pearl"] and b["params"]["kit"] == active


def test_changer_de_scene_n_est_PAS_un_rebuild_ajouter_un_kit_l_est():
    """La forme du plan = l'ensemble des kits (union), pas le kit du moment : A(Black Pearl) et B(Aasimonster)
    ont la MÊME forme (bascule d'état, zéro rebuild, Aasimonster chargé une fois) ; ajouter un 3e kit à une
    scène change l'ensemble -> rebuild. Le 23/09 midi, la forme portait le kit courant : 1 s de trou par scène."""
    from bridge import recall
    p = _preset_deux_kits()
    a, b, c = (recall.scene_shape(p, sid) for sid in ("A", "B", "C"))
    assert a == b == c
    p["scenes"][2]["params"]["kit1"]["kit"] = "drums-red-zeppelin"
    assert recall.scene_shape(p, "A") != a


def test_le_plan_compile_un_moteur_par_kit_avec_son_slot_de_traduction(tmp_path, monkeypatch):
    from bridge import compile_rig, inputmap, scene_bake
    monkeypatch.setattr(compile_rig, "OUT_DIR", str(tmp_path / "FXChains"))
    monkeypatch.setattr(compile_rig, "IO_PATH", str(tmp_path / "io.json"))
    (tmp_path / "io.json").write_text(json.dumps({"outputs": [{"ch": 1}, {"ch": 2}], "mono_fallback": {"on": False, "gain": -3}}))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / ".cache"))
    monkeypatch.setattr(inputmap, "usb_ports", lambda: [{"ch": "usb1", "port": 1, "role": "drums", "bound": True,
                                                         "device": "Alesis Nitro", "kit": {"id": "alesis-nitro", "auto": True}}])
    monkeypatch.setattr(vital, "midi_input_for", lambda role, in_sel: "hw:Nitro")
    baked = scene_bake.to_paths_preset(_preset_deux_kits(), "B", union=True)
    plan = json.load(open(compile_rig.compile_preset(baked)))
    b = plan["paths"][0]["tracks"][0]["blocks"][0]
    assert [e["kit_id"] for e in b["engines"]] == ["drums-aasimonster", "drums-black-pearl"]
    assert [e["drum_slot"] for e in b["engines"]] == [0, 1]                         # un slot gmem par traducteur
    assert b["engines"][0]["kit_engine"] == "drumgizmo" and b["engines"][0]["kit_drumkit"].endswith("aasimonster.xml")
    assert b["engines"][1]["kit_engine"] == "avldrums" and b["engines"][1]["kit_bank"] == "black-pearl"
    assert b["kit_id"] == "drums-aasimonster" and b["kit_engine"] == "drumgizmo"    # le kit ACTIF de cette scène, à plat
    assert b["engines"][0]["drum_map"][46] != b["engines"][1]["drum_map"][46]        # chaque kit sa table (hh-open 46 vs 48)


def test_changer_le_kit_d_un_bloc_pads_change_la_forme():
    """Le kit d'un bloc Pads = les samples chargés dans les RS5k au build : en changer EXIGE un rebuild. Sans lui dans
    la forme, le tiroir changeait le kit et les pads gardaient l'ancien (2026-10-13)."""
    import copy
    import os
    from bridge import recall
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = json.load(open(os.path.join(root, "library", "factory", "presets", "factory-loop-station.json"), encoding="utf-8"))

    def pads_of(o, out):
        if isinstance(o, dict):
            if o.get("type") == "pads":
                out.append(o)
            for v in o.values():
                pads_of(v, out)
        elif isinstance(o, list):
            for v in o:
                pads_of(v, out)
        return out
    for sc in p.get("scenes") or []:                     # un kit posé par scène ne doit pas masquer le changement
        for bp in (sc.get("params") or {}).values():
            if isinstance(bp, dict):
                bp.pop("kit", None)
    assert pads_of(p, []), "Loop Station porte un bloc Pads"
    q = copy.deepcopy(p)
    for b in pads_of(q, []):
        b.setdefault("params", {})["kit"] = "pads-lofi" if (b.get("params") or {}).get("kit") == "pads-trap" else "pads-trap"
    assert recall.scene_shape(p, "A") != recall.scene_shape(q, "A")


def test_reenregistrer_un_kit_de_pads_sous_le_meme_id_change_la_forme(monkeypatch):
    """« Save » dans l'éditeur de pads garde l'id du kit et change ses samples : la forme doit le voir."""
    from bridge import kits, recall
    p = {"id": "t", "lanes_v": 2, "lanes": [{"id": "keys-pads-1", "role": "keys-pads", "midi": True, "in_sel": "usb",
         "chain": {"pre": [{"id": "pads", "type": "pads", "params": {"kit": "k1"}}]}}],
         "scenes": [{"id": "A", "name": "A"}]}
    contenu = {"pads": [{"note": 36, "sample": "a/kick.wav", "mode": "oneshot", "level": 0}]}
    monkeypatch.setattr(kits, "get_kit", lambda kid: contenu)
    avant = recall.scene_shape(p, "A")
    contenu = {"pads": [{"note": 36, "sample": "a/snare.wav", "mode": "oneshot", "level": 0}]}
    assert recall.scene_shape(p, "A") != avant


def test_une_batterie_que_reaper_ne_joue_plus_est_reconnue_arretee(monkeypatch):
    """Crash de Reaper pendant que la batterie « joue » (2026-10-13) : l'état optimiste restait playing, le tap
    suivant devenait un FILL et SW10 ne relançait plus rien. Le silence de Reaper fait foi — après un délai, pour
    ne pas défaire un play qu'il n'a pas encore publié."""
    from bridge import drums
    sent = []
    ctl = drums.DrumControl(emit=sent.append)
    t = [100.0]
    monkeypatch.setattr(drums._time, "monotonic", lambda: t[0])
    ctl.tap("drums", ["library/grooves/golem-funk-16.mid"], [], "drums-black-pearl")
    assert ctl.snapshot()["drums"]["playing"] and sent[-1]["op"] == "play"
    ctl.apply_feedback({}, authoritative=True)                  # Reaper n'a pas encore publié : on attend
    assert ctl.snapshot()["drums"]["playing"]
    t[0] += 5
    ctl.apply_feedback({}, authoritative=False)                 # fichier absent/illisible : pas une preuve
    assert ctl.snapshot()["drums"]["playing"]
    ctl.apply_feedback({}, authoritative=True)                  # Reaper publie, sans ce bloc : il est arrêté
    assert not ctl.snapshot()["drums"]["playing"]
    ctl.tap("drums", ["library/grooves/golem-funk-16.mid"], [], "drums-black-pearl")
    assert sent[-1]["op"] == "play", "le tap suivant relance la batterie"


def test_rappuyer_sur_le_switch_coupe_la_batterie(monkeypatch):
    """2026-10-13 : « si je rappuie dessus ça doit couper » — tap = lancer, tap = arrêter (au pied comme à
    l'écran). L'appui long arrête toujours ; l'appui moyen reste la variation."""
    from bridge import drums
    sent = []
    ctl = drums.DrumControl(emit=sent.append)
    t = [10.0]
    monkeypatch.setattr(drums._time, "monotonic", lambda: t[0])
    args = ("drums", ["library/grooves/golem-funk-16.mid"], [], "drums-black-pearl")
    ctl.on_edge(10, True, *args); t[0] += 0.2; ctl.on_edge(10, False, *args)
    assert sent[-1]["op"] == "play" and ctl.snapshot()["drums"]["playing"]
    ctl.on_edge(10, True, *args); t[0] += 0.2; ctl.on_edge(10, False, *args)
    assert sent[-1]["op"] == "stop" and not ctl.snapshot()["drums"]["playing"]
    ctl.tap(*args); ctl.tap(*args)                               # l'écran : même geste
    assert [c["op"] for c in sent[-2:]] == ["play", "stop"]
