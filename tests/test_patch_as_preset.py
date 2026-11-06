# SPDX-License-Identifier: GPL-3.0-or-later
"""Un patch EST un preset — à un musicien (docs/patches.md), lot 1 : le rack JOUE un patch comme un
preset. Ce que ces tests gardent : les trois formes se LISENT (v2, kit, v1) sans déduire de `kind` ; la lane
se lie à la première entrée de son rôle, et une carte qui n'en a pas le dit ; `load_preset("patch:<id>")`
sert le brouillon du Designer quand il édite CE patch, le fichier sinon ; un patch n'est jamais un preset
sauvé ni publié ; /live sait le montrer."""
import json

import pytest

from bridge import config as C, patches as P, recall, store

IMAP = {"card": "hw:V276", "inputs": [{"ch": "1", "role": "guitar", "nth": 1, "name": "Guitar 1"},
                                      {"ch": "2", "role": "voice", "nth": 1, "name": "Voice 1"}], "usb": []}
CHAIN = {"pre": [{"id": "gate-1", "type": "gate"}], "split": None, "post": [{"id": "rev-1", "type": "reverb-plate"}]}


@pytest.fixture
def rack(tmp_path, monkeypatch):
    presets = tmp_path / "presets"; presets.mkdir()
    pdir = tmp_path / "patches"; pdir.mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(presets))
    monkeypatch.setattr(P, "PATCHES_DIR", str(pdir))
    P._cache.clear() if hasattr(P, "_cache") else None
    from bridge.state import state
    monkeypatch.setattr(state, "inputmap", IMAP, raising=False)
    from bridge import inputmap
    monkeypatch.setattr(inputmap, "current", lambda device=None: IMAP)   # le fichier de la MACHINE (store.lanes_of) : pas la carte de test
    return {"presets": presets, "patches": pdir}


def _write(rack, doc):
    json.dump(doc, open(rack["patches"] / f"{doc['id']}.json", "w"))


def test_un_patch_v1_se_joue_comme_un_preset_a_une_lane(rack):
    _write(rack, {"id": "doom", "name": "Doom", "role": "guitar", "chain": {"chain": CHAIN["pre"] + CHAIN["post"]},
                  "scenes": [{"id": "A", "name": "Riff", "blocks": {"gate-1": True}}, {"id": "B", "name": "Lead", "blocks": {"gate-1": False}}]})
    p = store.load_preset("patch:doom")
    assert p["id"] == "patch:doom" and p["kind"] == "patch" and p["__patch"]["id"] == "doom"
    (L,) = p["lanes"]
    assert L["role"] == "guitar" and L["in_sel"] == "1" and L["in_role"] == "guitar" and L["in_nth"] == 1
    assert [b["id"] for b in L["chain"]["pre"] + L["chain"]["post"]] == ["gate-1", "rev-1"]
    assert [s["id"] for s in p["scenes"]] == ["A", "B"] and p["scenes"][1]["blocks"] == {"gate-1": False}


def test_une_carte_sans_entree_du_role_le_dit(rack):
    _write(rack, {"id": "slap", "name": "Slap", "role": "bass", "chain": {"chain": CHAIN["pre"]}, "scenes": []})
    p = P.as_preset(P.get_patch("slap"), IMAP)
    assert p["lanes"][0]["in_sel"] == "NONE" and "no bass input on « V276 »" in p["lanes"][0]["bind_error"]
    assert [s["id"] for s in p["scenes"]] == ["A"]                         # au moins une scène


def test_la_forme_se_lit_elle_ne_se_deduit_pas_de_kind(rack):
    v2 = {"id": "wide", "name": "Wide", "role": "guitar", "kind": "patch", "patch_v": 2, "lanes_v": 2,
          "lanes": [{"id": "guitar-1", "role": "guitar", "name": "Guitar", "chain": CHAIN}],
          "scenes": [{"id": "A", "blocks": {}}], "config": {"gen": {"blocks": [{"id": "lp-1", "type": "looper"}]}},
          "colors": {"A": "#f00"}, "chain": {"pre": CHAIN["pre"], "split": None, "post": CHAIN["post"]}}
    p = P.as_preset(v2, IMAP)
    assert p["config"]["gen"]["blocks"][0]["type"] == "looper" and p["colors"] == {"A": "#f00"}
    assert p["lanes"][0]["in_sel"] == "1"
    fake = {"id": "fake", "name": "Fake", "role": "guitar", "kind": "patch", "patch_v": 2,        # déclare v2 sans lanes
            "chain": {"chain": CHAIN["pre"]}, "scenes": []}
    assert [b["id"] for b in P.as_preset(fake, IMAP)["lanes"][0]["chain"]["pre"]] == ["gate-1"]   # lu en v1


def test_un_kit_v1_devient_un_groupe_de_batterie(rack):
    kit = {"id": "nitro", "name": "Nitro", "role": "drums",
           "elements": [{"element": "kick", "chain": {"chain": [{"id": "eq-1", "type": "eq"}]}, "scenes": []},
                        {"element": "snare", "chain": {"chain": [{"id": "eq-1", "type": "eq"}]}, "scenes": []}]}
    p = P.as_preset(kit, IMAP)
    assert [L["element"] for L in p["lanes"]] == ["kick", "snare"] and p["__patch"]["drumset"] == "nitro"
    ids = [b["id"] for L in p["lanes"] for b in L["chain"]["pre"] + L["chain"]["post"]]
    assert len(ids) == len(set(ids))                                      # deux eq-1 : dédoublonnés


def test_le_brouillon_du_designer_fait_foi_quand_il_edite_ce_patch(rack):
    _write(rack, {"id": "doom", "name": "Doom", "role": "guitar", "chain": {"chain": CHAIN["pre"]}, "scenes": []})
    (rack["presets"] / ".sandbox.json").write_text(json.dumps({"preset": {
        "id": "nouveau-preset", "name": "⛓ Doom", "lanes_v": 2, "scenes": [{"id": "A"}, {"id": "C"}],
        "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1", "chain": CHAIN}],
        "__patch": {"id": "doom", "realm": "guitar-1", "role": "guitar"}}}))
    p = store.load_preset("patch:doom")
    assert p["id"] == "patch:doom" and [s["id"] for s in p["scenes"]] == ["A", "C"]        # le brouillon
    (rack["presets"] / ".sandbox.json").write_text(json.dumps({"preset": {"id": "x", "__patch": {"id": "autre"}}}))
    assert [s["id"] for s in store.load_preset("patch:doom")["scenes"]] == ["A"]            # le fichier
    assert store.load_preset("patch:inconnu") is None


def test_lid_sous_lequel_joue_un_brouillon():
    assert recall.trial_id({"__patch": {"id": "doom"}}) == "patch:doom"
    assert recall.trial_id({"__patch": {"id": None}}) == store.SANDBOX_TRY_ID
    assert recall.trial_id({"id": "nouveau-preset"}) == store.SANDBOX_TRY_ID
    assert recall.is_trial_id("patch:doom") and recall.is_trial_id("sandbox-try") and not recall.is_trial_id("velvetine")


def test_un_patch_ne_se_sauve_pas_comme_morceau_ni_ne_se_publie():
    import asyncio
    from bridge import routes_content, tones_sync
    r = asyncio.run(routes_content.save_preset({"id": "patch:doom", "name": "Doom"}))
    assert r.status_code == 400 and b"patch library" in r.body
    assert tones_sync.publish_preset("patch:doom")["ok"] is False


# ── LOT 2 : l'écriture v2 ─────────────────────────────────────────────────────────────────────
def _bench(**extra):
    """Le banc du Designer en mode patch : blank() a trois lanes (guitare, voix, claviers), seule la
    guitare EST le patch ; un looper, un backing et l'arrangement dans le ⚙ ; une pédale EXP et des couleurs."""
    p = {"id": "nouveau-preset", "name": "⛓ Doom", "lanes_v": 2, "bpm": 96, "exp2": {"target": "wah"}, "colors": {"A": "#f00"},
         "lanes": [{"id": "guitar", "role": "guitar", "in_sel": "1", "chain": CHAIN},
                   {"id": "voice", "role": "voice", "in_sel": "2", "chain": {"pre": [], "split": None, "post": []}}],
         "scenes": [{"id": "A", "name": "Riff", "blocks": {"gate-1": True}, "lanes": {"guitar": {"level": -3}, "voice": {"level": 0}}},
                    {"id": "B", "name": "  ", "blocks": {"rev-1": False}}],
         "config": {"gen": {"blocks": [{"id": "lp-1", "type": "looper"}, {"id": "bk-1", "type": "backing-track"}], "out": "1-2"},
                    "arr": {"blocks": [{"id": "arr-1", "type": "arrangement"}]}},
         "__patch": {"id": "doom", "realm": "guitar", "role": "guitar", "name": "Doom"}}
    p.update(extra)
    return p


def test_la_sauvegarde_ecrit_un_v2_au_miroir_identique(rack):
    _write(rack, {"id": "doom", "name": "Doom", "role": "guitar", "chain": {"chain": CHAIN["pre"]}, "scenes": [{"id": "A", "what": "heavy riff"}]})
    doc = P.save_patch("doom", _bench(), "guitar")
    assert doc["lanes_v"] == 2 and doc["kind"] == "patch" and [L["id"] for L in doc["lanes"]] == ["guitar"]   # pas la voix vide
    assert doc["chain"] == doc["lanes"][0]["chain"]                                   # garantie 1, à l'octet
    assert "in_sel" not in doc["lanes"][0]                                            # un patch est portable
    assert [b["type"] for b in doc["config"]["gen"]["blocks"]] == ["looper", "backing-track"]   # l'accompagnement, jamais l'arrangement (§4 bis)
    assert doc["exp2"] == {"target": "wah"} and doc["colors"] == {"A": "#f00"} and doc["bpm"] == 96
    a = doc["scenes"][0]
    assert a["lanes"] == {"guitar": {"level": -3}} and a["level"] == -3 and a["what"] == "heavy riff"   # descriptif gardé
    assert "name" not in doc["scenes"][1]                                             # des espaces ne sont pas un nom
    assert P.save_patch("doom", _bench(), "guitar") is not None                       # idempotent
    assert P.as_preset(P.get_patch("doom"), IMAP)["config"]["gen"]["blocks"][0]["type"] == "looper"   # relu v2


def test_depuis_la_lane_dun_morceau_pas_de_config(rack):
    song = _bench()
    song.pop("__patch")
    doc = P.create_from_lane(song, "guitar", name="From song")
    assert doc["lanes_v"] == 2 and "config" not in doc and "exp2" not in doc          # on ne devine pas le looper de quelqu'un


def test_un_patch_ne_melange_pas_deux_instruments(rack):
    with pytest.raises(ValueError, match="one instrument"):
        P.v2_fields(_bench(), ["guitar", "voice"])


# ── LOT 3 : le dépôt ──────────────────────────────────────────────────────────────────────────
def test_deposer_un_v2_ne_copie_que_la_lane_et_vise_le_role(rack):
    _write(rack, {"id": "doom", "name": "Doom", "role": "guitar", "chain": {"chain": CHAIN["pre"]}, "scenes": []})
    P.save_patch("doom", _bench(), "guitar")
    song = {"id": "s", "lanes_v": 2, "scenes": [{"id": "A"}],
            "lanes": [{"id": "voice-1", "role": "voice", "in_sel": "2", "chain": {"pre": [], "split": None, "post": []}},
                      {"id": "guitar-1", "role": "guitar", "in_sel": "1", "chain": {"pre": [], "split": None, "post": []}}],
            "config": {"gen": {"blocks": []}}}
    p, realm, _lost, _added, _sk = P.apply_to(song, "doom")
    assert realm == "guitar-1"                                                        # le RÔLE, pas un id « guitar »
    assert p["config"]["gen"]["blocks"] == []                                         # jamais la config du patch
    assert all("guitar" not in (sc.get("lanes") or {}) for sc in p["scenes"])         # pas d'entrée orpheline


# ── les jobs golem.fm reçoivent un v2 ─────────────────────────────────────────────────────────
def test_un_v2_venu_de_golem_fm_est_controle(rack, monkeypatch):
    from bridge import tones_jobs as J
    base = {"id": "x", "name": "X", "role": "guitar", "lanes_v": 2,
            "lanes": [{"id": "guitar-1", "role": "guitar", "chain": {"chain": CHAIN["pre"]}}], "scenes": [{"id": "A"}]}
    for doc, why in ((dict(base, chain={"chain": []}), "disagree"),
                     (dict(base, lanes=[dict(base["lanes"][0], role="bass")]), "one instrument"),
                     (dict(base, lanes=base["lanes"] * 2), "multi-lane")):
        monkeypatch.setattr(J, "_job_doc", lambda job, tmp, d=doc: d)
        with pytest.raises(RuntimeError, match=why):
            J._patch_doc({"role": "guitar"}, "t")
    monkeypatch.setattr(J, "_job_doc", lambda job, tmp: dict(base, chain={"chain": CHAIN["pre"]},
                                                             config={"gen": {"blocks": [{"type": "looper", "id": "lp"}, {"type": "backing-track", "id": "bk"},
                                                                                        {"type": "arrangement", "id": "arr"}]}}))
    monkeypatch.setattr(J, "_settle_captures", lambda blocks: {"matched": [], "installed": [], "failed": []})
    import bridge.golemfm as M
    monkeypatch.setattr(M, "push_patches", lambda *a, **k: None)
    J._patch_install({"role": "guitar", "patch_id": "x"})
    doc = P.get_patch("x")
    assert doc["lanes_v"] == 2 and doc["chain"] == doc["lanes"][0]["chain"]
    assert [b["type"] for b in doc["config"]["gen"]["blocks"]] == ["looper", "backing-track"]   # jamais l'arrangement (§4 bis)


def test_les_couleurs_dun_patch_vont_dans_son_fichier(rack):
    from bridge import tones_jobs as J
    _write(rack, {"id": "doom", "name": "Doom", "role": "guitar", "chain": {"chain": CHAIN["pre"]}, "scenes": []})
    J._set_appearance({"preset": "patch:doom", "colors": {"A": "#0f0"}})
    assert P.get_patch("doom")["colors"] == {"A": "#0f0"}
    assert not any(f.name.startswith("patch") for f in rack["presets"].iterdir())      # jamais un faux preset


# ── ACCOMPAGNEMENT OU FORME (docs/patches.md §4 bis, 2026-09-30) ─────────────────────────
BACKING = {"songs": [{"slug": "paper-kite", "title": "Paper Kite"}]}


def _solo_bench(with_block=True):
    blocks = [{"id": "bt-1", "type": "backing-track"}] if with_block else []
    return {"id": "nouveau-preset", "name": "⛓ Solo", "lanes_v": 2, "backing": BACKING,
            "lanes": [{"id": "guitar-1", "role": "guitar", "name": "Guitar", "chain": CHAIN}],
            "scenes": [{"id": "A"}, {"id": "B"}],
            "config": {"gen": {"blocks": blocks + [{"id": "arr", "type": "arrangement"}]}},
            "__patch": {"realm": "guitar-1", "id": None, "name": "Solo", "role": "guitar"}}


def test_un_patch_garde_sa_backing_mais_jamais_larrangement(rack):
    doc = P.v2_fields(_solo_bench(), ["guitar-1"])
    assert [b["type"] for b in doc["config"]["gen"]["blocks"]] == ["backing-track"]
    assert doc["backing"] == BACKING
    p = P.as_preset(dict(doc, id="solo", name="Solo"), IMAP)
    assert p["backing"] == BACKING                                           # backing.py la lit là
    assert "backing" not in P.v2_fields(_solo_bench(with_block=False), ["guitar-1"])   # sans bloc, elle ne voyage pas


def test_make_a_song_cree_un_morceau_sans_ecraser_ni_toucher_au_patch(rack, monkeypatch):
    import asyncio
    from bridge import routes_patches as RP, routes_content, tones_sync
    monkeypatch.setattr(tones_sync, "publish_soon", lambda *a, **k: None)
    doc = dict(P.v2_fields(_solo_bench(), ["guitar-1"]), id="solo", name="Solo")
    _write(rack, doc)
    json.dump({"id": "solo", "name": "Someone else's song"}, open(rack["presets"] / "solo.json", "w"))
    r = asyncio.run(RP.api_make_song("solo", {}))
    assert r["ok"] and r["id"] == "solo-2"                                   # jamais d'écrasement
    assert json.load(open(rack["presets"] / "solo.json"))["name"] == "Someone else's song"
    song = json.load(open(rack["presets"] / "solo-2.json"))
    assert song["backing"] == BACKING and "__patch" not in song and song.get("kind") != "patch"
    assert any(b.get("type") == "backing-track" for b in song["config"]["gen"]["blocks"])
    assert json.load(open(rack["patches"] / "solo.json")) == doc             # le patch reste intact


def test_le_niveau_dune_scene_v1_survit_a_la_sauvegarde(rack):
    """2026-10-11, Paper Kite basse : `level: 2` sur Chorus (patch v1). Le Designer le range sous `levels[guitar]`
    (le moteur le joue) ; la sauvegarde v2 ne relisait que `lanes[guitar].level` — l'auto-save l'effaçait."""
    _write(rack, {"id": "cr", "name": "CR", "role": "guitar", "chain": {"chain": CHAIN["pre"]},
                  "scenes": [{"id": "A", "name": "Verse"}, {"id": "B", "name": "Chorus", "level": 2}]})
    bench = _bench()
    bench["scenes"] = [{"id": "A", "name": "Verse", "blocks": {}, "lanes": {"guitar": {"state": "st-guitar-A"}}},
                       {"id": "B", "name": "Chorus", "blocks": {}, "levels": {"guitar": 2}, "lanes": {"guitar": {"state": "st-guitar-B"}}}]
    doc = P.save_patch("cr", bench, "guitar")
    b = doc["scenes"][1]
    assert b["lanes"]["guitar"]["level"] == 2 and b["lanes"]["guitar"]["state"] == "st-guitar-B" and b["level"] == 2
    assert "level" not in doc["scenes"][0] and "level" not in (doc["scenes"][0].get("lanes") or {}).get("guitar", {})   # jamais inventé
