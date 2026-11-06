# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 3 (audit N lanes) — le document v2 : `lanes[]` est la vérité (`lanes_v: 2`), les trois clés
d'origine sont des miroirs regénérés ; parcours, dépôt de patch et bake passent par la liste."""
import copy

from bridge import patches, scene_bake as sb, store


def _v2():
    return {"id": "band", "lanes_v": 2, "lanes": [
        {"id": "guitar", "role": "guitar", "name": "Alex", "chain": {"pre": [{"id": "amp-1", "type": "amp"}], "split": None, "post": []}},
        {"id": "ln-sam", "role": "guitar", "name": "Sam", "in_sel": "2", "chain": {"pre": [{"id": "amp-2", "type": "amp", "foot": 7}], "split": None, "post": []}},
        {"id": "voice", "role": "voice", "name": "Lead", "in_sel": "NONE", "chain": {"chain": [{"id": "eq-1", "type": "eq"}]}},
        {"id": "keys", "role": "keys-pads", "name": "Keys", "chain": {"pre": [{"id": "vital-1", "type": "vital"}], "split": None, "post": []}},
    ], "scenes": [{"id": "A", "blocks": {"amp-2": False}, "lanes": {"ln-sam": {"level": -5}}}], "config": {"gen": {"blocks": [{"id": "smp", "type": "sample"}]}}}


def _quiet(monkeypatch):
    from bridge import inputmap
    monkeypatch.setattr(inputmap, "current", lambda: {})


def test_v2_normalise_et_miroirs(monkeypatch):
    _quiet(monkeypatch)
    p = _v2()
    lanes = store.lanes_of(p)
    assert [L["id"] for L in lanes] == ["guitar", "ln-sam", "voice", "keys"]
    g, sam, v, k = lanes
    assert g["key"] == "1" and g["input"] == 1 and g["out"] == 1
    assert sam["key"] == "ln-sam" and sam["input"] == 2 and sam["out"] == 2 and sam["role"] == "guitar"
    assert v["disabled"] and v["chain"]["pre"][0]["id"] == "eq-1"          # `{chain}` plat accepté
    assert k["midi"] and k["input"] == 3 and k["in_sel"] == "usb"
    # les miroirs legacy : les lecteurs non migrés voient les trois premières lanes comme avant
    assert p["guitar"]["pre"][0]["id"] == "amp-1" and p["voice"] == {"chain": [{"id": "eq-1", "type": "eq"}]}
    assert p["keys"]["chain"][0]["id"] == "vital-1" and p["in"] == {"2": "NONE"} and p["names"]["1"] == "Alex"


def test_v2_parcours_et_pied(monkeypatch):
    _quiet(monkeypatch)
    p = _v2()
    assert [(b["id"], l) for b, l in store.all_blocks(p)] == [("amp-1", "guitar"), ("amp-2", "ln-sam"), ("eq-1", "voice"), ("vital-1", "keys"), ("smp", "gen")]
    foot = [(b["id"], k) for b, k in store._foot_blocks(p)]
    assert ("amp-2", "ln-sam") in foot and ("amp-1", "1") in foot and ("smp", "cfg") in foot
    assert store.duplicate_block_ids(p) == []


def test_v2_bake_un_path_par_lane(monkeypatch):
    _quiet(monkeypatch)
    out = sb.to_paths_preset(copy.deepcopy(_v2()), "A", union=True)
    ids = [q["id"] for q in out["paths"]]
    assert ids == ["guitar", "ln-sam", "keys"]                            # la voix est à IN NONE
    sam = out["paths"][1]
    assert sam["input"] == 2 and sam["level"] == -5 and sam["chain"][0]["bypass"] is True   # scène : niveau par lane + bloc coupé
    assert out["paths"][2]["midi"] is True


def test_v2_depot_dans_une_lane_choisie(monkeypatch):
    _quiet(monkeypatch)
    doc = {"id": "stone", "name": "Stone", "role": "guitar", "chain": {"pre": [{"id": "amp-1", "type": "amp"}, {"id": "dly-1", "type": "delay"}], "split": None, "post": []},
           "scenes": [{"id": "A", "blocks": {"dly-1": False}}]}
    monkeypatch.setattr(patches, "get_patch", lambda pid: doc)
    p, realm, lost, added, _sk = patches.apply_to(_v2(), "stone", lane="ln-sam")
    assert realm == "ln-sam"
    sam = next(L for L in p["lanes"] if L["id"] == "ln-sam")
    assert [b["id"] for b in sam["chain"]["pre"]] == ["amp-2", "dly-1"]    # amp-1 collisionnait avec la lane du mainteneur
    assert sam["patch_from"]["id"] == "stone" and store.duplicate_block_ids(p) == []
    # sans lane : la première lane de ce rôle
    p2, realm2, _l, _a, _s = patches.apply_to(_v2(), "stone")
    assert realm2 == "guitar"
    assert patches.chain_of(_v2(), "voice") == {"chain": [{"id": "eq-1", "type": "eq"}]} and patches.lane_ids(_v2())[1] == "ln-sam"
    assert patches.role_of_lane(_v2(), "ln-sam") == "guitar"


def test_legacy_reste_legacy(monkeypatch):
    _quiet(monkeypatch)
    p = {"guitar": {"pre": []}, "voice": {"chain": []}, "keys": {"chain": []}}
    assert not store.is_v2(p) and [L["id"] for L in store.lanes_of(p)] == ["guitar", "voice", "keys"]


def test_v2_le_volume_systeme_va_dans_la_lane(monkeypatch):
    _quiet(monkeypatch)
    p = _v2()
    store.ensure_volume(p)
    g = next(L for L in p["lanes"] if L["id"] == "guitar")
    assert [b["id"] for b in g["chain"]["pre"]] == ["amp-1", "volume-sys"]
    store.ensure_volume(p)                                                     # idempotent
    assert [b["id"] for b in g["chain"]["pre"]] == ["amp-1", "volume-sys"]
    out = sb.to_paths_preset(copy.deepcopy(p), "A", union=True)
    assert any(b.get("id") == "volume-sys" for b in out["paths"][0]["chain"])   # et il atteint le rig


# ── LOT 4 : les lecteurs legacy passent par les lanes ; veto et REC par lane ────────────────────
def test_lot4_resume_des_entrees_et_export_voient_la_4e_lane(monkeypatch):
    _quiet(monkeypatch)
    p = _v2()
    keys = [e["key"] for e in store._inputs_summary(p)]
    assert keys == ["1", "ln-sam", "2", "k"]                    # une entrée PAR LANE avec des blocs, dans l'ordre de la liste
    from bridge import preset_export
    monkeypatch.setattr(preset_export._inputmap, "current", lambda: {"inputs": [{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "voice"}], "midi": {"role": "keys-pads"}})
    ins = preset_export._inputs(p)
    assert [(i["lane"], i["role"], i["port"]) for i in ins] == [("guitar", "guitar", "1"), ("ln-sam", "guitar", "2"), ("voice", "voice", "NONE"), ("keys", "keys-pads", "usb")]
    assert [b["id"] for b in preset_export._lane_blocks(p, "ln-sam")] == ["amp-2"]
    from bridge import arrangement
    assert {"amp-2", "smp"} <= arrangement._block_ids(p)


def test_lot4_veto_par_lane_sur_son_role(monkeypatch):
    _quiet(monkeypatch)
    from bridge import recall
    from bridge.state import state
    monkeypatch.setattr(state, "mode", {"id": "x", "services": {"voice": False, "pads": False}}, raising=False)
    v = recall.input_veto(_v2())
    assert v == {"2"}                                             # la voix (clé legacy 2) ; le mainteneur (guitare sur IN 2) n'est PAS coupé ; keys-pads garde keys
    monkeypatch.setattr(state, "mode", {"id": "y", "services": {"guitar": False}}, raising=False)
    assert recall.input_veto(_v2()) == {"1", "ln-sam"}


def test_lot4_rec_sources_par_entree(monkeypatch, tmp_path):
    _quiet(monkeypatch)
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "r.json"))
    (tmp_path / "r.json").write_text('{"in1": true, "in2": false, "usb": false, "mode": "tracks", "mix": true}')
    p = _v2(); p["lanes"][2]["in_sel"] = "4"                       # la voix sur IN 4
    src = store.rec_sources(p)
    assert src["in1"] is True and src["in2"] is False and src["in4"] is True and src["in3"] is False   # in3 = la lane MIDI, suit usb


# ── LOT 5 : la carte 8×8 (sans la carte) ──────────────────────────────────────────────────────
def test_lot5_lane_midi_numerotee_selon_la_carte_et_paire_stereo(monkeypatch):
    from bridge import inputmap
    p = _v2(); p["lanes"][1]["in_sel"] = "3-4"                         # le mainteneur en paire stéréo
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": "1"}, {"ch": "2"}]})
    lanes = {L["id"]: L for L in store.lanes_of(copy.deepcopy(p))}
    assert lanes["keys"]["input"] == 3                                 # 2 entrées : le root historique In3
    assert lanes["ln-sam"]["input"] == 3 and lanes["ln-sam"]["stereo"] is True
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": str(i)} for i in range(1, 9)]})
    lanes = {L["id"]: L for L in store.lanes_of(copy.deepcopy(p))}
    assert lanes["keys"]["input"] == 101 and store.midi_input_base(8) == 101   # 8 entrées : In3 est de l'audio
    out = sb.to_paths_preset(copy.deepcopy(p), "A", union=True)
    sam = next(q for q in out["paths"] if q["id"] == "ln-sam")
    assert sam["input"] == 3 and sam["stereo"] is True
    from bridge import rig
    n = rig.normalize(out); plan = rig.build_plan(n, out_count=8)
    root = next(t for pp in plan["paths"] if pp["id"] == "ln-sam" for t in pp["tracks"] if t.get("input") is not None)
    assert root["stereo"] is True                                        # golem_rig : I_RECINPUT = 1024 + 2
    assert rig.validate_routing(n, out_count=2)                          # trois lanes en 1-2 sur une carte à 2 sorties : OK (lot 5)


def test_lot5_rec_sources_dit_les_entrees_midi(monkeypatch, tmp_path):
    from bridge import inputmap
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": str(i)} for i in range(1, 9)]})
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "r.json"))
    (tmp_path / "r.json").write_text('{"in1": true, "in2": true, "usb": true, "mode": "tracks_di", "mix": true}')
    src = store.rec_sources(_v2())
    assert src["midi_inputs"] == [101] and src["in101"] is True and "in3" not in src


def test_la_prise_d_un_riff_enregistre_ses_lanes(monkeypatch, tmp_path):
    """Riff de clavier sur USB alors que la case USB du Rec est éteinte : la prise du riff la prend quand même,
    une prise ordinaire non (2026-11-02)."""
    from bridge import inputmap
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": str(i)} for i in range(1, 9)]})
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "r.json"))
    (tmp_path / "r.json").write_text('{"in1": true, "in2": false, "usb": false, "mode": "tracks_di", "mix": true}')
    assert store.rec_sources(_v2())["in101"] is False
    src = store.rec_sources(_v2(), force=("usb", "2"))
    assert src["usb"] is True and src["in101"] is True and src["in2"] is True


def test_une_lane_hors_carte_n_est_pas_montee_et_le_dit(monkeypatch):
    """Preset fait sur une 8×8, joué sur une Volt : le mainteneur demande IN 3. Il n'est pas monté, le plan le dit,
    la lane claviers garde son root In3 pour elle seule, le preset reste intact."""
    from bridge import inputmap
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": "1"}, {"ch": "2"}]})
    p = _v2(); p["lanes"][1]["in_sel"] = "3"
    out = sb.to_paths_preset(copy.deepcopy(p), "A", union=True)
    assert [q["id"] for q in out["paths"]] == ["guitar", "keys"]
    assert out["unmounted"] == [{"id": "ln-sam", "name": "Sam", "input": "3", "reason": "needs IN 3, this card has 2"}]
    assert next(L for L in store.lanes_of(copy.deepcopy(p)) if L["id"] == "ln-sam")["on_card"] is False
    # sur une 8×8, le mainteneur monte et le plan ne dit rien
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": str(i)} for i in range(1, 9)]})
    out = sb.to_paths_preset(copy.deepcopy(p), "A", union=True)
    assert [q["id"] for q in out["paths"]] == ["guitar", "ln-sam", "keys"] and "unmounted" not in out


def test_une_lane_se_lie_a_une_entree_par_son_nom(monkeypatch):
    """Lien fort entrée-nom (2026-09-09) : « Voice 1 » = IN 3 en Gig (8×8), IN 2 à la maison (Volt)."""
    from bridge import inputmap
    p = _v2(); p["lanes"][2]["in_sel"] = "3"; p["lanes"][2]["in_role"] = "voice"; p["lanes"][2]["in_nth"] = 1
    # la Volt : sa seule voix EST « Voice 1 » sans qu'on la numérote (with_nth pose le rang par rôle)
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": inputmap.with_nth([{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "voice"}])})
    v = next(L for L in store.lanes_of(copy.deepcopy(p)) if L["id"] == "voice")
    assert v["in_sel"] == "2" and v["input"] == 2 and v["on_card"] is True and v["in_name"] == "Voice 1"
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": inputmap.with_nth([{"ch": str(i), "role": r} for i, r in enumerate(["guitar", "guitar", "voice", "bass"], 1)])})
    v = next(L for L in store.lanes_of(copy.deepcopy(p)) if L["id"] == "voice")
    assert v["in_sel"] == "3" and v["input"] == 3
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": [{"ch": "1"}, {"ch": "2"}]})   # carte sans voix : le numéro, hors carte
    v = next(L for L in store.lanes_of(copy.deepcopy(p)) if L["id"] == "voice")
    assert v["in_sel"] == "3" and v["on_card"] is False


def test_le_patch_d_une_carte_debranchee_s_edite(monkeypatch, tmp_path):
    from bridge import inputmap, cards
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    monkeypatch.setattr(inputmap, "_card_device", lambda: "hw:V276")
    monkeypatch.setattr(cards, "known", lambda cid: {"id": cid, "inputs": 8, "outputs": 8} if cid == "X88" else None)
    monkeypatch.setattr(cards, "probe", lambda cid: None)
    dev = inputmap.device_of("X88"); assert dev == "hw:X88"
    m = inputmap.current(dev)
    assert len(m["inputs"]) == 8                                       # semée depuis le registre
    # le contrôleur USB est au RACK, pas à la carte (2026-09-09) : même réponse que pour la carte active
    assert m["midi"] == inputmap.current()["midi"] and [u["ch"] for u in m["usb"]] == ["usb1", "usb2", "usb3", "usb4"]
    inputmap.set_role("input", "3", "voice", dev); inputmap.set_role("input", "6", "voice", dev)
    m = inputmap.set_nth("6", 1, dev)                                     # IN 6 = Voice 1, donc IN 3 devient Voice 2
    by = {x["ch"]: x for x in m["inputs"]}
    assert by["6"]["name"] == "Voice 1" and by["3"]["name"] == "Voice 2"
    import pytest
    with pytest.raises(ValueError):
        inputmap.set_nth("3", 1, dev)                                     # 1 est pris par IN 6
    m = inputmap.set_role("input", "6", "guitar", dev)                    # changer d'instrument oublie le numéro
    assert next(x for x in m["inputs"] if x["ch"] == "3")["name"] == "Voice 1"
    assert inputmap.current()["card"] == "hw:V276"                       # la carte active n'a pas bougé


def test_une_carte_declaree_a_la_main_seme_son_patch(monkeypatch, tmp_path):
    from bridge import cards, inputmap
    monkeypatch.setattr(cards, "CARDS_DIR", str(tmp_path / "cards")); monkeypatch.setattr(cards, "_path", lambda cid: str(tmp_path / "cards" / (cid + ".json")))
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path / "maps")); monkeypatch.setattr(inputmap, "_card_device", lambda: "hw:V276")
    monkeypatch.setattr(cards, "probe", lambda cid: None)
    d = cards.declare("UMC 18/20", "Behringer UMC1820", 8, 10)
    assert d["id"] == "UMC-18-20" and d["inputs"] == 8 and d["declared"] and not d["probed"]
    m = inputmap.current(inputmap.device_of(d["id"]))
    assert len(m["inputs"]) == 8 and len(m["outputs"]) == 5                     # semé depuis la déclaration
    inputmap.set_role("input", "5", "drums", inputmap.device_of(d["id"])); m = inputmap.set_nth("5", 2, inputmap.device_of(d["id"]))
    assert next(x for x in m["inputs"] if x["ch"] == "5")["name"] == "Drums 2"
    import pytest
    with pytest.raises(ValueError):
        cards.declare("")


def test_une_lane_v2_vide_fait_un_path_passthrough_pas_une_legacy():
    """Audit 2026-09-09 : une entrée COCHÉE est jouée — même sans bloc (comme `guitar` depuis toujours).
    Un preset legacy garde son silence : `voice: {chain: []}` n'y est pas une intention."""
    from bridge import scene_bake
    empty = {"pre": [], "split": None, "post": []}
    v2 = {"id": "p", "lanes_v": 2, "scenes": [{"id": "A"}], "lanes": [
        {"id": "guitar", "role": "guitar", "in_sel": "1", "chain": empty},
        {"id": "voice-1", "role": "voice", "in_sel": "2", "chain": empty},
        {"id": "keys-pads-1", "role": "keys-pads", "midi": True, "in_sel": "usb1", "chain": empty}]}
    b = scene_bake.to_paths_preset(v2, "A", union=True, veto=set())
    assert [(x["id"], x["chain"]) for x in b["paths"]] == [("guitar", []), ("voice-1", []), ("keys-pads-1", [])]
    assert b["paths"][2]["midi"] is True
    legacy = {"id": "l", "scenes": [{"id": "A"}], "guitar": {"pre": [], "split": None, "post": []}, "voice": {"chain": []}, "keys": {"chain": []}}
    assert [x["id"] for x in scene_bake.to_paths_preset(legacy, "A", union=True, veto=set())["paths"]] == ["guitar"]


def test_une_lane_liee_par_nom_attend_sa_carte_au_lieu_de_retomber_sur_le_numero(monkeypatch):
    """Finalisation de l'audit 2026-09-09 : « Guitar 2 » (guitar, 2) sur une Volt qui n'a que Guitar 1
    et Voice 1 n'est PAS montée sur IN 2 (le micro) — elle attend sa carte, et le bake le dit."""
    from bridge import inputmap, scene_bake
    card = inputmap.with_nth([{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "voice"}])
    monkeypatch.setattr(inputmap, "current", lambda device=None: {"inputs": card, "usb": []})
    empty = {"pre": [], "split": None, "post": []}
    p = {"id": "p", "lanes_v": 2, "scenes": [{"id": "A"}], "lanes": [
        {"id": "guitar", "role": "guitar", "in_sel": "1", "in_role": "guitar", "in_nth": 1, "chain": empty},
        {"id": "guitar-2", "role": "guitar", "in_sel": "2", "in_role": "guitar", "in_nth": 2, "chain": empty},
        {"id": "voice-1", "role": "voice", "in_sel": "4", "in_role": "voice", "in_nth": 1, "chain": empty}]}
    lanes = {L["id"]: L for L in store.lanes_of(p)}
    assert lanes["guitar"]["on_card"] and lanes["guitar"]["in_sel"] == "1"
    assert lanes["guitar-2"]["on_card"] is False
    assert lanes["voice-1"]["on_card"] and lanes["voice-1"]["in_sel"] == "2"       # Voice 1 suit le patch : IN 2 ici
    b = scene_bake.to_paths_preset(p, "A", union=True, veto=set())
    assert [x["id"] for x in b["paths"]] == ["guitar", "voice-1"]
    assert b["unmounted"][0]["id"] == "guitar-2" and "Guitar 2" in b["unmounted"][0]["reason"]
