# SPDX-License-Identifier: GPL-3.0-or-later
"""Les jobs `preset-install`, `patch-install` (alias `patch-push`) et `patch-try` depuis golem.fm
(docs/private/exchanges/message-maestrium-patches-push-splits.md, confirmés le 2026-09-09) — sans réseau : le blob
est injecté, l'audition est un faux, les fichiers vont dans tmp."""
import json
import os

import pytest

from bridge import config as C, patches as P, recall, tones_jobs as J
from bridge.state import state


@pytest.fixture
def rack(tmp_path, monkeypatch):
    presets = tmp_path / "presets"; presets.mkdir()
    pdir = tmp_path / "patches"; pdir.mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(presets))
    monkeypatch.setattr(P, "PATCHES_DIR", str(pdir))
    monkeypatch.setattr(recall, "SANDBOX_BUF", str(presets / ".sandbox.json"))
    monkeypatch.setattr(recall, "_loop", None)
    # aucun push réseau depuis un test : on ENREGISTRE les appels (patch-install repousse le catalogue)
    from bridge import golemfm
    pushes = []
    monkeypatch.setattr(golemfm, "push_patches", lambda delay=5.0: pushes.append(delay))
    monkeypatch.setattr(J, "_pushes", pushes, raising=False)
    emitted = []
    # l'essai passe par do_recall (le chemin de tout rappel) : ici on en garde le contrat visible
    # depuis patch-try — charger le preset sous son id, l'émettre, poser l'état — sans Reaper ni pied
    monkeypatch.setattr(recall, "check_preset", lambda p, s: None)

    def _do_recall(pid, scene, line=None):
        p = recall.load_preset(pid)
        if not p:
            return False
        emitted.append((p, scene))
        state.preset_id = p["id"]; state.preset_name = p.get("name"); state.scene_id = scene
        return True
    monkeypatch.setattr(recall, "do_recall", _do_recall)
    monkeypatch.setattr(state, "mode", {"id": "studio", "name": "Home", "ui": {"locked": False}}, raising=False)
    monkeypatch.setattr(state, "perf", {"recording": False}, raising=False)
    monkeypatch.setattr(state, "inputmap", {"card": "hw:V276", "inputs": [
        {"ch": "1", "role": "guitar", "nth": 1, "name": "Guitar 1"}, {"ch": "2", "role": "voice", "nth": 1, "name": "Voice 1"}]}, raising=False)
    state.sandbox_rev = 0
    return {"presets": presets, "patches": pdir, "emitted": emitted}


def _blob(monkeypatch, doc):
    monkeypatch.setattr(J, "_blob_bytes", lambda job, tmp: json.dumps(doc).encode())


CHAIN = {"pre": [{"id": "gate-1", "type": "gate"}], "split": None, "post": [{"id": "reverb-1", "type": "reverb-plate"}]}


def test_preset_install_ecrit_sans_rappeler_et_refuse_les_ids_doubles(rack, monkeypatch):
    preset = {"id": "Fuzz Wall", "name": "Fuzz Wall", "lanes_v": 2, "scenes": [{"id": "A"}],
              "lanes": [{"id": "guitar", "role": "guitar", "in_sel": "1", "chain": CHAIN}]}
    _blob(monkeypatch, {"schema_version": 2, "preset": preset})
    r = J._preset_install({"action": "preset-install", "sha": "x", "name": "Fuzz Wall", "preset_id": "fuzz-wall"})
    assert r["preset_id"] == "fuzz-wall" and isinstance(r["unresolved"], list)
    saved = json.load(open(rack["presets"] / "fuzz-wall.json"))
    assert saved["origin"] == "golem.fm" and saved["id"] == "fuzz-wall"
    assert rack["emitted"] == []                                    # jamais de recall
    # le même id de golem.fm se remplace ; un preset LOCAL du même id est préservé (suffixe)
    r2 = J._preset_install({"action": "preset-install", "sha": "x", "preset_id": "fuzz-wall"})
    assert r2["preset_id"] == "fuzz-wall"
    json.dump({"id": "mine", "name": "mine"}, open(rack["presets"] / "mine.json", "w"))
    r3 = J._preset_install({"action": "preset-install", "sha": "x", "preset_id": "mine"})
    assert r3["preset_id"] == "mine-2" and json.load(open(rack["presets"] / "mine.json"))["name"] == "mine"
    # ids doublés = refus avec raison, rien d'écrit
    bad = dict(preset, lanes=[dict(preset["lanes"][0]), {"id": "voice-1", "role": "voice", "in_sel": "2", "chain": CHAIN}])
    _blob(monkeypatch, {"preset": bad})
    with pytest.raises(RuntimeError, match="duplicate block ids: gate-1"):
        J._preset_install({"action": "preset-install", "sha": "x", "preset_id": "bad"})
    assert not os.path.exists(rack["presets"] / "bad.json")


def test_patch_install_range_dans_la_bibliotheque_et_exige_un_role(rack, monkeypatch):
    _blob(monkeypatch, {"name": "Doom", "chain": CHAIN, "scenes": [{"id": "A", "blocks": {"gate-1": True}}], "tags": ["metal"]})
    r = J._patch_install({"action": "patch-push", "sha": "x", "name": "Doom", "role": "guitar", "patch_id": "doom"})
    doc = P.get_patch("doom")
    assert r["patch_id"] == "doom" and doc["role"] == "guitar" and doc["origin"] == "golem.fm"
    assert doc["chain"] == {"chain": CHAIN["pre"] + CHAIN["post"]} and doc["tags"] == ["metal"] and doc["scenes"][0]["id"] == "A"
    assert rack["emitted"] == []
    with pytest.raises(RuntimeError, match="role required"):
        J._patch_install({"action": "patch-install", "sha": "x", "patch_id": "norole"})
    _blob(monkeypatch, {"name": "Empty", "chain": {"pre": [], "split": None, "post": []}})
    with pytest.raises(RuntimeError, match="no blocks"):
        J._patch_install({"action": "patch-install", "sha": "x", "role": "voice", "patch_id": "empty"})


def test_patch_try_auditionne_dans_l_edit_buffer_et_garde_le_brouillon(rack, monkeypatch):
    json.dump({"preset": {"id": "draft", "name": "my draft"}}, open(rack["presets"] / ".sandbox.json", "w"))
    _blob(monkeypatch, {"name": "Try me", "chain": CHAIN, "scenes": [{"id": "A"}, {"id": "B"}]})
    r = J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert r["ok"] is True and r["lane"] == "guitar-try" and r["input"] == "1"
    (p, sc), = rack["emitted"]
    assert p["id"] == "sandbox-try" and p["lanes"][0]["in_role"] == "guitar" and p["lanes"][0]["in_nth"] == 1 and sc == "A"
    buf = json.load(open(rack["presets"] / ".sandbox.json"))
    assert buf["from"] == "golem.fm" and buf["preset"]["id"] == "sandbox-try"
    assert json.load(open(rack["presets"] / ".sandbox.prev.json"))["preset"]["id"] == "draft"   # le brouillon d'avant
    assert state.sandbox_rev == 1 and state.sandbox_from == "golem.fm"
    assert state.preset_id == "sandbox-try" and state.preset_name == "Try me"                     # l'essai EST le courant
    assert not (rack["presets"] / "sandbox-try.json").exists()                                    # rien laissé derrière


def test_patch_try_refuse_avec_la_raison(rack, monkeypatch):
    _blob(monkeypatch, {"name": "Bass", "chain": CHAIN})
    with pytest.raises(RuntimeError, match="no bass input on « V276 »"):
        J._patch_try({"action": "patch-try", "sha": "x", "role": "bass"})
    monkeypatch.setattr(state, "perf", {"recording": True}, raising=False)
    with pytest.raises(RuntimeError, match="a take is recording"):
        J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    monkeypatch.setattr(state, "perf", {"recording": False}, raising=False)
    monkeypatch.setattr(state, "mode", {"id": "show", "name": "Show", "ui": {"locked": True}}, raising=False)
    with pytest.raises(RuntimeError, match="rack is in Show mode"):
        J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    monkeypatch.setattr(state, "mode", {"id": "studio", "ui": {"locked": False}}, raising=False)
    monkeypatch.setattr(recall, "check_preset", lambda p, s: "bloc gx-detune en quarantaine")
    with pytest.raises(RuntimeError, match="gx-detune"):
        J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert not os.path.exists(rack["presets"] / ".sandbox.json")                                  # rien écrit sur refus
    assert state.sandbox_rev == 0


def test_la_table_des_jobs_connait_les_quatre_actions():
    for a in ("preset-install", "patch-install", "patch-push", "patch-try", "push-catalog"):
        assert a in J._HANDLERS, a


# ── LE RACK EST LE VALIDATEUR (2026-09-11) ──────────────────────────────────────────────────
# Un patch de golem.fm est arrivé avec un `split` SANS `mode` et des scènes SANS `id`. Le
# compilateur s'en sortait (post non vide -> merge), mais l'ÉCRAN lit `mode === 'merge'` : il
# dessinait un fan-out et cachait les cinq blocs du post — un patch qui se voit autrement qu'il
# ne sonne. Et les cinq onglets de scène s'affichaient vides. On complète à la réception.
def test_split_sans_mode_devient_un_merge_quand_il_y_a_un_post():
    from bridge import patches as P
    shape = {"pre": [{"id": "a"}], "split": {"branches": [{"id": "b1"}, {"id": "b2"}]},
             "post": [{"id": "z"}]}
    shape, _ = P.normalize_patch(shape, [])
    assert shape["split"]["mode"] == "merge"


def test_split_sans_mode_ni_post_reste_un_fanout():
    from bridge import patches as P
    shape, _ = P.normalize_patch({"pre": [], "split": {"branches": []}, "post": []}, [])
    assert shape["split"]["mode"] == "fanout"


def test_un_mode_fourni_nest_jamais_reecrit():
    from bridge import patches as P
    shape, _ = P.normalize_patch({"split": {"mode": "fanout", "branches": []},
                                  "post": [{"id": "z"}]}, [])
    assert shape["split"]["mode"] == "fanout"


def test_les_scenes_sans_id_recoivent_A_B_C_dans_l_ordre():
    from bridge import patches as P
    _, scs = P.normalize_patch({}, [{"name": "Clean"}, {"name": "crunch"}, {"id": "X", "name": "gardé"}])
    assert [s["id"] for s in scs] == ["A", "B", "X"]          # un id fourni est respecté


# ── UN BLOC SANS CAPTURE FAIT TAIRE SA BRANCHE (2026-09-11) ─────────────────────────────────
# Un NAM vide ne laisse RIEN passer : un seul bloc sans `ref` rendait muette toute sa branche,
# l'ampli qui la suit compris. À l'audition on le retire pour entendre le reste (la bibliothèque,
# elle, garde la recette intacte). La décision d'un silence mérite son test.
def _preset_2br():
    return {"lanes_v": 2, "lanes": [{"id": "guitar-try", "chain": {
        "pre": [{"id": "comp-1", "type": "comp"}, {"id": "ped-1", "type": "pedal-nam"}],
        "split": {"mode": "merge", "branches": [
            {"id": "br-a", "blocks": [{"id": "amp-a", "type": "amp-nam"}, {"id": "cab-a", "type": "cab"}]},
            {"id": "br-b", "blocks": [{"id": "amp-b", "type": "amp-nam"}]}]},
        "post": [{"id": "dly-1", "type": "delay"}]}}]}


def test_drop_blocks_retire_partout_et_garde_le_reste():
    from bridge import patches as P
    p = P.drop_blocks(_preset_2br(), {"ped-1", "amp-b"})
    ch = p["lanes"][0]["chain"]
    assert [b["id"] for b in ch["pre"]] == ["comp-1"]           # la pédale vide part
    assert [b["id"] for b in ch["post"]] == ["dly-1"]           # le post est intact
    brs = {br["id"]: [b["id"] for b in br["blocks"]] for br in ch["split"]["branches"]}
    assert brs == {"br-a": ["amp-a", "cab-a"], "br-b": []}      # retiré DANS la branche


def test_drop_blocks_sans_id_ne_touche_a_rien():
    from bridge import patches as P
    before = _preset_2br()
    after = P.drop_blocks(_preset_2br(), set())
    assert after == before
    assert P.drop_blocks(_preset_2br(), {None, ""}) == before


# ── DES SCÈNES QUI SEMBLENT AGIR ET NE LE PEUVENT PAS (2026-09-11) ──────────────────────────
# Trouvé par golem.fm dans son propre coffre après notre §4 : des patches dont les scènes portent
# bien `blocks: {…}` — mais dont les blocs de la chaîne n'ont AUCUN id, si bien que ces clés ne
# désignent rien. Une scène qui se lit comme une promesse et n'en tient aucune.
def test_les_blocs_sans_id_en_recoivent_un_stable():
    from bridge import patches as P
    shape = {"pre": [{"type": "comp"}, {"type": "comp"}], "split": None,
             "post": [{"id": "delay-1", "type": "delay"}, {"type": "delay"}]}
    posed = P.assign_block_ids(shape)
    assert posed == ["comp-1", "comp-2", "delay-2"]        # delay-1 est PRIS : on saute
    assert [b["id"] for b in shape["pre"]] == ["comp-1", "comp-2"]
    assert [b["id"] for b in shape["post"]] == ["delay-1", "delay-2"]


def test_un_id_fourni_nest_jamais_reecrit():
    from bridge import patches as P
    shape = {"chain": [{"id": "gardé", "type": "comp"}]}
    assert P.assign_block_ids(shape) == []
    assert shape["chain"][0]["id"] == "gardé"


def test_les_cles_de_scene_qui_ne_designent_rien_sont_nommees():
    from bridge import patches as P
    shape = {"pre": [{"id": "b1", "type": "comp"}], "split": None, "post": [{"id": "b2", "type": "delay"}]}
    scenes = [{"id": "A", "blocks": {"b1": False, "fantome": False}, "params": {"b2": {"mix": 1}}},
              {"id": "B", "blocks": {"delay": False}}]        # clé par TYPE : légitime, elle est lue
    orph = P.orphan_scene_keys(shape, scenes)
    assert orph == [{"scene": "A", "key": "fantome", "where": "blocks"}]


def test_une_chaine_sans_ids_rend_toutes_les_cles_orphelines():
    from bridge import patches as P
    shape = {"chain": [{"type": "comp"}, {"type": "amp-nam"}]}
    orph = P.orphan_scene_keys(shape, [{"id": "A", "blocks": {"b2": False}}])
    assert [o["key"] for o in orph] == ["b2"]


def test_la_provenance_du_document_ne_sinvente_pas():
    """golem.fm date ses documents depuis le 2026-09-11 ; un brouillon n'a PAS de date (il n'a
    jamais été sauvé) et un job d'avant n'en a pas non plus. Trois réponses, pas deux."""
    from bridge import tones_jobs as J
    assert J._origin_of({"draft": True}, {}) == "draft (never saved)"
    assert J._origin_of({"saved_at": "2026-09-10T18:22:41+00:00", "rev": 3}, {}) \
        == "saved 2026-09-10T18:22:41+00:00 rev 3"
    assert J._origin_of({}, {"rev": 2}) == "saved ? rev 2"       # le doc peut porter ce que le job tait
    assert "undated" in J._origin_of({}, {})


def test_unresolved_couvre_la_capture_du_MAUVAIS_TYPE():
    """Patch « Titan » : une capture amp-cab au format NAM sur un bloc `cab` RÉSOUT — le tone
    existe, le fichier est là — et le convolver ne charge rien. Bonne forme, mauvaise nature :
    l'ack doit le dire, sinon golem.fm apprend le silence après coup."""
    from bridge.rig import _wrong_kind
    assert _wrong_kind({"type": "cab"}, "/x/blackstar-series-one-a2.nam")
    assert _wrong_kind({"type": "amp-nam"}, "/x/mesa.wav")
    assert _wrong_kind({"type": "cab"}, "/x/mesa.wav") is None


# ── LA NATURE SE LIT, ELLE NE SE DÉCLARE PAS (2026-09-12) ───────────────────────────────────
# golem.fm a trouvé chez lui un `kind` DÉDUIT de l'endroit où l'utilisateur cherchait : un
# amp-cab installé depuis un bloc d'ampli entrait en « amp ». Ce champ voyage jusqu'à notre
# catalogue (`gear`), et c'est lui que nos gardes interrogent ensuite. Une déclaration fausse en
# amont devient une vérité ici — donc on lit l'extension du fichier posé.
def _pack(kind, fmt="nam"):
    return {"uid": "t3k:1", "kind": kind, "title": "T", "extra": {}}, fmt


def test_un_pack_dIR_declare_pedal_est_range_en_cab():
    from bridge import tones_jobs as J
    pack, _ = _pack("pedal")
    e = J._entry_from_pack(pack, [({"sha256": "a" * 12}, "assets/irs/x/mesa.wav")])
    assert e["gear"] == "cab" and e["format"] == "ir"


def test_un_pack_de_captures_declare_cab_est_range_en_amp_cab():
    from bridge import tones_jobs as J
    pack, _ = _pack("cab")
    e = J._entry_from_pack(pack, [({"sha256": "a" * 12}, "assets/models/x/blackstar-a2.nam")])
    assert e["gear"] == "amp-cab" and e["format"] == "nam"


def test_ce_qui_nest_PAS_lisible_reste_declare():
    """`amp` seul et `amp-cab` sont deux .nam : le contenu ne les distingue pas. On garde la
    déclaration faute de mieux — mais on ne la laisse jamais contredire une lecture."""
    from bridge import tones_jobs as J
    for kind in ("amp", "amp-cab", "pedal"):
        pack, _ = _pack(kind)
        e = J._entry_from_pack(pack, [({"sha256": "a" * 12}, "assets/models/x/a-a2.nam")])
        assert e["gear"] == kind and e["format"] == "nam"


# ── LA CAPTURE QU'ON POSSÈDE DÉJÀ EST ASSOCIÉE (décision 2026-09-12) ──────────────────
# « Hammer » nommait un « Roland Jazz Chorus-120 » sans ref, alors que le rack possédait trois
# captures de JC-120. Apparier par NOM est pourtant ce qui a produit le bug du « Blackstar 412
# Pro » : ces tests gardent les trois garde-fous, un par un.
TONES = [{"id": 6530, "gear": "amp-cab", "title": "Roland JC-120 Jazz Chorus"},
         {"id": 10912, "gear": "amp-cab", "title": "Roland JC 120B Jazz Chorus"},
         {"id": 127, "gear": "amp", "title": "Roland Jazz Chorus"},
         {"id": 53952, "gear": "amp-cab", "title": "Blackstar Series One 412 Pro B MK II"},
         {"id": 31332, "gear": "amp-cab", "title": "Randall X2 Warhead DIMEZONE Full Rigs"}]


def test_le_materiel_nomme_trouve_sa_capture():
    from bridge import patches as P
    tone, score = P.match_capture("Roland Jazz Chorus-120", "amp", TONES)
    assert tone["id"] == 6530 and score == 1.0          # le titre le plus proche, pas le premier


def test_le_TYPE_passe_avant_le_nom():
    """Le piège du « Blackstar 412 Pro » : un pack amp-cab dont le titre contient « 412 » ne doit
    JAMAIS être proposé pour un baffle. Aucun `gear: cab` ici, donc rien ne sort."""
    from bridge import patches as P
    tone, why = P.match_capture("Blackstar Series One 412 Pro", "cab", TONES)
    assert tone is None and "matches" in why


def test_un_label_trop_pauvre_ne_decide_de_rien():
    from bridge import patches as P
    assert P.match_capture("Marshall", "amp", TONES)[0] is None
    assert P.match_capture("", "amp", TONES)[0] is None


def test_lambiguite_ne_tranche_pas():
    """Deux captures également proches : choisir au hasard vaudrait moins que ne rien faire —
    l'utilisateur, lui, sait laquelle il veut."""
    from bridge import patches as P
    ex_aequo = [{"id": 1, "gear": "amp-cab", "title": "Vox AC30 Top Boost"},
                {"id": 2, "gear": "amp-cab", "title": "Vox AC30 Top Boost"}]
    tone, why = P.match_capture("Vox AC30 Top Boost", "amp", ex_aequo)
    assert tone is None and "equally" in why


# ── L'IDENTITÉ D'UN PATCH VOYAGE AVEC LUI (2026-09-12) ──────────────────────────────────────
# Sauver un patch essayé depuis golem.fm sous un id dérivé du NOM fabriquait paper-kite,
# paper-kite-ii, paper-kite-iii : trois objets pour un patch et deux reprises. Le `patch_id` de
# golem.fm est l'identité ; on la garde, et on n'écrase que le même patch revenu.
def _preset_une_lane():
    return {"id": "sandbox-try", "name": "Hammer", "lanes_v": 2, "scenes": [{"id": "A", "blocks": {}}],
            "lanes": [{"id": "guitar-try", "role": "guitar",
                       "chain": {"pre": [{"id": "b1", "type": "comp"}], "split": None, "post": []}}]}


def test_un_patch_de_golem_fm_garde_son_id_et_se_remplace(tmp_path, monkeypatch):
    from bridge import patches as P
    monkeypatch.setattr(P, "_path", lambda pid: str(tmp_path / f"{pid}.json"))
    monkeypatch.setattr(P, "PATCH_DIR", str(tmp_path), raising=False)
    a = P.create_from_lane(_preset_une_lane(), "guitar-try", name="Hammer", pid="hammer", origin="golem.fm")
    b = P.create_from_lane(_preset_une_lane(), "guitar-try", name="Hammer", pid="hammer", origin="golem.fm")
    assert a["id"] == b["id"] == "hammer"           # le même patch revenu : même id, pas de -2
    assert b["origin"] == "golem.fm"


def test_un_patch_de_lutilisateur_ne_secrase_jamais(tmp_path, monkeypatch):
    from bridge import patches as P
    monkeypatch.setattr(P, "_path", lambda pid: str(tmp_path / f"{pid}.json"))
    mine = P.create_from_lane(_preset_une_lane(), "guitar-try", name="Hammer")          # le mien, sans origine
    theirs = P.create_from_lane(_preset_une_lane(), "guitar-try", name="Hammer", pid="hammer", origin="golem.fm")
    assert mine["id"] == "hammer" and theirs["id"] == "hammer-2"   # le leur prend le suffixe, pas le mien


# ── L'ESSAI D'UN PATCH EST UN PRESET COURANT (décision 2026-09-12) ────────────────────
# Un patch essayé sonnait mais n'existait ni pour /live ni pour le pied, qui regardent « le
# preset courant ». Mesuré : Hammer en sandbox, /live affichait Velvetine en scène E. La sandbox
# est désormais servie comme un preset sous un id RÉSERVÉ — sans fichier, donc hors catalogue.
def test_la_sandbox_est_servie_comme_preset_sous_son_id_reserve(tmp_path, monkeypatch):
    import json
    from bridge import store, config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    (tmp_path / ".sandbox.json").write_text(json.dumps({"preset": {"id": "nouveau-preset", "name": "Hammer",
        "lanes_v": 2, "lanes": [], "scenes": [{"id": "A"}]}, "scene": "A"}))
    p = store.load_preset(store.SANDBOX_TRY_ID)
    assert p["name"] == "Hammer" and p["id"] == store.SANDBOX_TRY_ID   # l'id du Designer est écrasé
    assert store.load_preset("autre-chose") is None                    # rien d'autre ne change


def test_lessai_nentre_jamais_au_catalogue(tmp_path, monkeypatch):
    import json
    from bridge import store, config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    (tmp_path / ".sandbox.json").write_text(json.dumps({"preset": {"id": "x", "name": "Essai"}}))
    (tmp_path / "velvetine.json").write_text(json.dumps({"id": "velvetine", "name": "Velvetine"}))
    ids = [p.get("id") for p in store.load_presets()]
    assert "velvetine" in ids and store.SANDBOX_TRY_ID not in ids and "x" not in ids


def test_sans_sandbox_lessai_est_absent(tmp_path, monkeypatch):
    from bridge import store, config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    assert store.load_preset(store.SANDBOX_TRY_ID) is None


def test_lessai_ne_se_publie_jamais_vers_golem_fm(rack, monkeypatch):
    """Question golem.fm (2026-09-12) : leur ingestion fait un upsert par id sans exclure les ids
    réservés. Un `sandbox-try` entré une fois dans leur miroir y resterait pour toujours."""
    from bridge import tones_sync, preset_export
    json.dump({"preset": {"id": "x", "name": "Try me", "lanes_v": 2, "lanes": [], "scenes": []}},
              open(rack["presets"] / ".sandbox.json", "w"))
    called = []
    monkeypatch.setattr(preset_export, "build_export", lambda pid: called.append(pid) or (None, {}))
    r = tones_sync.publish_preset("sandbox-try")
    assert r["ok"] is False and "trial" in r["error"] and called == []      # refusé AVANT l'export


# ── CE QUE GOLEM.FM POSSÈDE, LE RACK SE LE FAIT ENVOYER (2026-09-12, « Prism ») ──
# Trois blocs nommés sans `ref` : « Fender Twin Reverb » (amp) — le rack a « Fender Twin Pack »,
# une TÊTE ; « Revv Generator 120 MKIII » — le rack a « … MK III » ; « Mesa Oversized 4x12 V30 » —
# seul golem.fm l'a. L'audition partait amputée des trois.
def test_mk_iii_et_mkiii_sont_le_meme_ampli():
    from bridge import patches as P
    assert P._tokens("Revv Generator 120 MKIII") == P._tokens("Revv Generator 120 MK III") == P._tokens("revv generator 120 mk-3")
    assert P._tokens("Mesa Mark IV") == P._tokens("Mesa Mark 4")


def test_un_bloc_ampli_suit_la_capture_trouvee():
    """Le patch dit `amp` (rig complet), le rack possède une TÊTE du même nom : on la prend et le
    bloc devient amp-nam — refuser pour le type laisse une branche muette (golem.fm ce soir)."""
    from bridge import patches as P
    tones = [{"id": 246, "gear": "amp", "title": "Fender Twin Reverb"}]
    tone, score, ntype = P.match_capture_family("Fender Twin Reverb", "amp", tones)
    assert tone["id"] == 246 and ntype == "amp-nam"
    tone, score, ntype = P.match_capture_family("Fender Twin Reverb", "cab", tones)   # un baffle ne devient pas un ampli
    assert tone is None and ntype == "cab"


def _rack_tones(monkeypatch, idx):
    """Un index de tones vivant : ce que `_install` ajoute devient résoluble à la seconde."""
    from bridge import resolver
    monkeypatch.setattr(resolver, "_tones_index", lambda: idx)
    monkeypatch.setattr(resolver, "_components", lambda: {})
    def _res(ref, comps, model=None):        # l'extension suit la nature (un baffle est une IR)
        t = idx.get(str(ref).split(":")[-1])
        return None if t is None else f"assets/{t['id']}." + ("wav" if t["gear"] == "cab" else "nam")
    monkeypatch.setattr(resolver, "_resolve", _res)


def test_un_bloc_sans_ref_nest_plus_apparie_il_est_propose(rack, monkeypatch):
    """docs/block-status.md §6 (amende patches.md §20) : un titre voisin n'est pas le son écouté. Le
    rapprochement par nom part en `suggested[]` ; le document n'est pas touché, rien n'est installé."""
    idx = {"42067": {"id": 42067, "gear": "amp", "title": "Revv Generator 120 MK III"},
           "246": {"id": 246, "gear": "amp", "title": "Fender Twin Pack"}}
    _rack_tones(monkeypatch, idx)
    monkeypatch.setattr(J, "_manifest_tones", lambda: [
        {"id": "246", "uid": "t3k:246", "gear": "amp", "title": "Fender Twin Reverb"},
        {"id": "2595", "uid": "t3k:2595", "gear": "cab", "title": "Mesa Oversized 4x12 V30"}])
    pulled = []
    monkeypatch.setattr(J, "_install", lambda uid: pulled.append(uid))
    _blob(monkeypatch, {"name": "Prism", "scenes": [{"id": "A"}], "chain": {"pre": [
        {"id": "b5", "type": "amp", "label": "Fender Twin Reverb"},
        {"id": "b8", "type": "amp-nam", "label": "Revv Generator 120 MKIII"},
        {"id": "b9", "type": "cab", "label": "Mesa Oversized 4x12 V30"}], "split": None, "post": []}})
    r = J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert r["matched"] == [] and pulled == []                                    # rien d'appliqué, rien de tiré
    by = {m["block"]: m for m in r["suggested"]}
    assert by["b8"]["ref"] == "42067" and by["b8"]["source"] == "rack"            # MKIII ≡ MK III, proposé
    assert by["b5"]["retyped"] == "amp-nam"                                       # la proposition dit le retypage
    assert by["b9"]["ref"] == "2595" and by["b9"]["source"] == "golem.fm"
    assert {u["block"] for u in r["unresolved"]} == {"b5", "b8", "b9"}            # vides, et dits


def test_une_ref_t3k_choisie_a_lecoute_vient_de_tone3000_si_golem_fm_ne_la_detient_pas(rack, monkeypatch):
    idx = {}
    _rack_tones(monkeypatch, idx)
    monkeypatch.setattr(J, "_manifest_tones", lambda: [])
    got = []
    def fake_t3k(payload):
        got.append(payload["tone_id"]); idx["777"] = {"id": 777, "gear": "amp-cab", "title": "Dumble"}
    monkeypatch.setattr(J, "_t3k_install", fake_t3k)
    _blob(monkeypatch, {"name": "T", "scenes": [{"id": "A"}], "chain": {"pre": [{"id": "b1", "type": "amp", "ref": "t3k:777"}], "split": None, "post": []}})
    r = J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert got == ["777"] and r["installed"][0]["source"] == "tone3000" and r["unresolved"] == []


def test_une_ref_connue_de_golem_fm_mais_absente_ici_est_installee(rack, monkeypatch):
    idx = {}
    _rack_tones(monkeypatch, idx)
    monkeypatch.setattr(J, "_manifest_tones", lambda: [{"id": "2595", "uid": "t3k:2595", "gear": "cab", "title": "Mesa OS"}])
    monkeypatch.setattr(J, "_install", lambda uid: idx.__setitem__("2595", {"id": 2595, "gear": "cab", "title": "Mesa OS"}))
    _blob(monkeypatch, {"name": "T", "scenes": [{"id": "A"}], "chain": {"pre": [{"id": "b9", "type": "cab", "ref": "t3k:2595"}], "split": None, "post": []}})
    r = J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert r["installed"][0]["uid"] == "t3k:2595" and r["unresolved"] == []


def test_un_echec_dinstallation_se_dit_et_namputte_pas_le_reste(rack, monkeypatch):
    _rack_tones(monkeypatch, {})
    monkeypatch.setattr(J, "_manifest_tones", lambda: [{"id": "2595", "uid": "t3k:2595", "gear": "cab", "title": "Mesa OS"}])
    def boom(uid): raise RuntimeError("disk full")
    monkeypatch.setattr(J, "_install", boom)
    _blob(monkeypatch, {"name": "T", "scenes": [{"id": "A"}], "chain": {"pre": [{"id": "b1", "type": "gate"}, {"id": "b9", "type": "cab", "ref": "t3k:2595"}], "split": None, "post": []}})
    r = J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert r["install_failed"][0]["why"] == "disk full" and r["unresolved"][0]["block"] == "b9"


def test_le_materiel_classe_compte_autant_que_le_titre_du_pack():
    """« Fender Twin Pack » (titre) / « Fender Twin Reverb » (matériel classé, `amp`) : le patch
    nomme le second, la bibliothèque le possède sous le premier."""
    from bridge import patches as P
    tones = [{"id": 246, "gear": "amp", "title": "Fender Twin Pack", "amp": "Fender Twin Reverb"}]
    tone, score = P.match_capture("Fender Twin Reverb", "amp-nam", tones)
    assert tone["id"] == 246 and score == 1.0


def test_une_marque_est_une_chaine():
    from bridge.store import brand_str
    assert brand_str("{'name': 'Marshall 1960TV 4x12'}") == "Marshall 1960TV 4x12"
    assert brand_str([{"name": "AKG c414"}]) == "AKG c414"
    assert brand_str({"name": "Revv"}) == "Revv" and brand_str("Fender") == "Fender"
    assert brand_str(None) == "" and brand_str("{broken") == ""


# ── AUDIT 2026-09-13, B1 + M4 : ce que golem.fm nous dicte ne sort pas d'assets/ et ne parle pas
# à notre place. `extra.rel` du manifest finissait tel quel dans un chemin disque ; `sha` du job
# tel quel dans une URL portée par notre Bearer.
def test_un_rel_de_manifest_ne_sort_pas_dassets():
    assert J._under_assets("assets/models/x/y.nam") == "assets/models/x/y.nam"
    assert J._under_assets("assets/../assets/irs/a.wav") == "assets/irs/a.wav"
    for bad in ("../.ssh/authorized_keys", "assets/../../etc/passwd", "/etc/passwd", "presets/velvetine.json", ""):
        with pytest.raises(RuntimeError, match="escapes"):
            J._under_assets(bad)


def test_un_sha_qui_nest_pas_64_hex_est_refuse_avant_le_reseau(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("réseau touché")))
    monkeypatch.setattr("bridge.golemfm._cfg", lambda: ("http://x", "tok"))
    for bad in ("../../admin", "x", "61570cbd" * 7, "61570CBD72F330F7E5ABD566EA5777F53625F50A56BC77930941EA65E6B8763Z"):
        with pytest.raises(RuntimeError, match="bad blob sha"):
            J._download_raw(bad, "/tmp/never")


def test_install_refuse_un_pack_dont_un_asset_sort_dassets(monkeypatch):
    monkeypatch.setattr(J, "_req", lambda m, p, **k: (200, {"packs": [{"uid": "t3k:1", "kind": "amp", "title": "X",
        "assets": [{"sha256": "a" * 64, "extra": {"rel": "../../.bashrc"}}]}]}))
    touched = []
    monkeypatch.setattr(J, "_download_raw", lambda sha, dest: touched.append(dest))
    with pytest.raises(RuntimeError, match="escapes"):
        J._install("t3k:1")
    assert touched == []                                                       # rien écrit


def test_un_fichier_de_catalogue_hors_depot_ne_se_resout_pas(monkeypatch):
    from bridge import resolver
    monkeypatch.setattr(resolver, "_tones_index", lambda: {"9": {"id": 9, "models": [{"id": 1, "file": "../../etc/shadow"}]}})
    assert resolver._resolve("9", {}) is None
    monkeypatch.setattr(resolver, "_tones_index", lambda: {"9": {"id": 9, "models": [{"id": 1, "file": "assets/models/a.nam"}]}})
    assert os.path.normpath(resolver._resolve("9", {})).endswith(os.path.normpath("assets/models/a.nam"))


# ── AUDIT 2026-09-13, M6 : la boucle de jobs n'est pas un téléchargeur ────────────────────────
def test_un_pack_trop_gros_nest_pas_tire_pendant_la_reception(rack, monkeypatch):
    _rack_tones(monkeypatch, {})
    monkeypatch.setattr(J, "_manifest_tones", lambda: [{"id": "7", "uid": "t3k:7", "gear": "cab", "title": "Mesa OS",
                                                       "bytes": 200 * 1024 * 1024}])
    pulled = []
    monkeypatch.setattr(J, "_install", lambda uid: pulled.append(uid))
    _blob(monkeypatch, {"name": "T", "scenes": [{"id": "A"}], "chain": {"pre": [{"id": "b9", "type": "cab", "ref": "7"}], "split": None, "post": []}})
    r = J._patch_try({"action": "patch-try", "sha": "x", "role": "guitar"})
    assert pulled == [] and "200 MB" in r["install_failed"][0]["why"] and "install t3k:7" in r["install_failed"][0]["why"]
    assert r["ok"] is True                                                    # auditionné quand même, amputé


def test_le_reglement_a_un_budget_de_temps(monkeypatch):
    import itertools, time
    from bridge import resolver
    monkeypatch.setattr(resolver, "_tones_index", lambda: {})
    monkeypatch.setattr(resolver, "_components", lambda: {})
    monkeypatch.setattr(J, "_manifest_tones", lambda: [
        {"id": "1", "uid": "t3k:1", "gear": "cab", "title": "Cab One", "bytes": 10},
        {"id": "2", "uid": "t3k:2", "gear": "cab", "title": "Cab Two", "bytes": 10}])
    clock = itertools.count(0, 50)                                            # chaque lecture = +50 s
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    pulled = []
    monkeypatch.setattr(J, "_install", lambda uid: pulled.append(uid))
    blocks = [{"id": "b1", "type": "cab", "ref": "1"}, {"id": "b2", "type": "cab", "ref": "2"}]
    monkeypatch.setattr(resolver, "_resolve", lambda ref, comps, model=None: None)
    r = J._settle_captures(blocks, budget_s=90)
    assert pulled == ["t3k:1"]                                                # le second arrive après le budget
    assert r["failed"][0]["block"] == "b2" and "time budget" in r["failed"][0]["why"]


def test_patch_install_repousse_le_catalogue_a_golem_fm(rack, monkeypatch):
    """Le document du rack fait foi : après un patch-install, le catalogue repart vers golem.fm
    (débouncé) au lieu d'attendre la synchro suivante — demande golem.fm du 2026-09-14
    (« ✎ Edit » réécrit un patch par patch-install {edit: true}, l'ack n'était qu'un pont)."""
    _blob(monkeypatch, {"schema_version": 2, "role": "voice", "chain": [{"type": "comp"}], "scenes": []})
    monkeypatch.setattr(J, "_settle_captures", lambda blocks, budget_s=0: {"matched": [], "installed": [], "failed": []})
    r = J._patch_install({"action": "patch-install", "sha": "x", "patch_id": "edited", "name": "Edited", "role": "voice", "edit": True})
    assert r["patch_id"] == "edited"
    assert J._pushes == [5.0]


def test_patch_delete_efface_repousse_et_tolere_l_absent(rack, monkeypatch):
    """§21 : patch-delete = P.delete_patch + push `complete` (c'est lui qui confirme chez golem.fm) ;
    un id absent acquitte deleted:false sans erreur."""
    P._write({"id": "hollow-choir", "name": "Hollow Choir", "role": "guitar", "origin": "golem.fm",
              "chain": [{"type": "comp", "id": "c1"}], "scenes": []})
    assert P.get_patch("hollow-choir") is not None
    r = J._patch_delete({"action": "patch-delete", "patch_id": "hollow-choir"})
    assert r["deleted"] is True and P.get_patch("hollow-choir") is None
    r2 = J._patch_delete({"action": "patch-delete", "patch_id": "hollow-choir"})
    assert r2["deleted"] is False
    assert J._pushes == [5.0, 5.0]                    # un push par job, même quand rien n'a été effacé
    with pytest.raises(RuntimeError, match="patch_id"):
        J._patch_delete({"action": "patch-delete"})


def test_preset_delete_libere_les_banks_et_refuse_le_preset_qui_joue(rack, monkeypatch):
    from bridge import setlists as SL, rigstatus, store
    open(os.path.join(C.PRESETS_DIR, "velvetine.json"), "w").write(json.dumps({"id": "velvetine", "name": "velvetine"}))
    freed = []
    monkeypatch.setattr(SL, "forget_preset", lambda pid: freed.append(pid) or 2)
    monkeypatch.setattr(rigstatus, "push_soon", lambda: freed.append("push"))
    from bridge import golemfm
    monkeypatch.setattr(golemfm, "push_song_links", lambda: None)
    state.preset_id = "velvetine"
    with pytest.raises(RuntimeError, match="playing"):
        J._preset_delete({"action": "preset-delete", "preset_id": "velvetine"})
    state.preset_id = "other"
    r = J._preset_delete({"action": "preset-delete", "preset_id": "velvetine"})
    assert r["deleted"] is True and r["banks_freed"] == 2
    assert not os.path.exists(os.path.join(C.PRESETS_DIR, "velvetine.json"))
    assert freed == ["velvetine", "push"]
    assert J._preset_delete({"action": "preset-delete", "preset_id": "velvetine"})["deleted"] is False
    # prise en cours : refusé en le disant
    state.perf = {"recording": True}
    with pytest.raises(RuntimeError, match="recording"):
        J._preset_delete({"action": "preset-delete", "preset_id": "x"})


def test_les_deux_jobs_sont_dans_la_table():
    assert {"patch-delete", "preset-delete"} <= set(J._HANDLERS)


def test_patch_preview_rend_chaque_scene_et_ne_laisse_rien(rack, monkeypatch):
    """§22 : le patch devient un preset TEMPORAIRE, chaque scène est re-ampée puis uploadée, l'ack
    porte {patch_id, di, instrument, fingerprint, scenes, missing} — et il ne reste ni preset ni clip."""
    from bridge import preview as PV
    _blob(monkeypatch, {"schema_version": 2, "role": "guitar", "chain": [{"type": "comp", "id": "c1"}],
                        "scenes": [{"id": "A", "name": "A"}, {"id": "B", "name": "B"}]})
    monkeypatch.setattr(J, "_settle_captures", lambda blocks, budget_s=0: {"matched": [], "installed": [], "failed": []})
    seen = {}

    def fake_generate(pid, seq, on_scene=None, in_key="1", ref=None):
        seen.update(pid=pid, in_key=in_key, ref=ref)
        p = json.load(open(os.path.join(C.PRESETS_DIR, pid + ".json")))         # le preset temporaire EXISTE pendant le rendu
        p["preview"] = {"ref": ref or "guitar/crunch", "instrument": "guitar", "fingerprint": "fp1", "scenes": {"A": "previews/x/A.opus", "B": "previews/x/B.opus"}}
        json.dump(p, open(os.path.join(C.PRESETS_DIR, pid + ".json"), "w"))
        for sc in ("A", "B"):
            on_scene(sc, f"previews/x/{sc}.opus")
    monkeypatch.setattr(PV, "generate", fake_generate)
    monkeypatch.setattr(PV, "status", lambda: {"phase": "done"})
    monkeypatch.setattr(PV, "push_clip", lambda pid, sc, rel: {"sha256": "s-" + sc, "duration": 6.0} if pid == "patch-paper-kite" else None)
    monkeypatch.setattr(PV, "_di_index", lambda: {"guitar/high-gain": {"file": "guitar/high-gain.wav", "name": "Strat bridge — palm mute"}})
    r = J._patch_preview({"action": "patch-preview", "sha": "x", "role": "guitar", "patch_id": "paper-kite", "ref": "guitar/high-gain", "id": 7})
    assert seen == {"pid": "preview-paper-kite", "in_key": "1", "ref": "guitar/high-gain"}
    assert r["patch_id"] == "paper-kite" and r["di"] == "guitar/high-gain" and r["instrument"] == "guitar" and r["fingerprint"] == "fp1"
    assert r["di_name"] == "Strat bridge — palm mute"                     # le nom de l'index, pour la fiche du Store
    assert r["scenes"] == {"A": {"sha256": "s-A", "duration": 6.0}, "B": {"sha256": "s-B", "duration": 6.0}}
    assert r["missing"] == [] and not os.path.exists(os.path.join(C.PRESETS_DIR, "preview-paper-kite.json"))
    assert "patch-preview" in J._HANDLERS


def test_patch_preview_refuse_en_le_disant(rack, monkeypatch):
    from bridge import preview as PV
    _blob(monkeypatch, {"schema_version": 2, "role": "guitar", "chain": [{"type": "comp", "id": "c1"}], "scenes": []})
    monkeypatch.setattr(J, "_settle_captures", lambda blocks, budget_s=0: {"matched": [], "installed": [], "failed": []})
    state.perf = {"recording": True}
    with pytest.raises(RuntimeError, match="recording"):
        J._patch_preview({"action": "patch-preview", "sha": "x", "role": "guitar", "patch_id": "p"})
    state.perf = {"recording": False}
    # DI de référence absente : l'erreur du moteur remonte telle quelle, et rien ne reste
    monkeypatch.setattr(PV, "generate", lambda *a, **k: None)
    monkeypatch.setattr(PV, "status", lambda: {"phase": "error", "error": "reference DI missing: guitar/clean (record it first)"})
    with pytest.raises(RuntimeError, match="reference DI missing"):
        J._patch_preview({"action": "patch-preview", "sha": "x", "role": "guitar", "patch_id": "p"})
    assert not os.path.exists(os.path.join(C.PRESETS_DIR, "preview-p.json"))
