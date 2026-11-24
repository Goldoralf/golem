# SPDX-License-Identifier: GPL-3.0-or-later
"""Un kit de batterie se dit disponible ICI ou non (2026-10-03 : Aasimonster choisi sous Windows, sans DrumGizmo
ni ses échantillons — pas de son, et le sélecteur ne disait rien)."""
from bridge import kits


def test_disponibilite_par_moteur(tmp_path, monkeypatch):
    monkeypatch.setattr(kits.C, "ROOT", str(tmp_path))
    inv = {"names": {"black pearl drumkit (robin gareus) (2 out)"}}
    assert kits.availability({"engine": "avldrums", "bank": "black-pearl"}, inv) == (True, None)
    ok, why = kits.availability({"engine": "avldrums", "bank": "red-zeppelin"}, inv)
    assert ok is False and "AVL Drumkits" in why
    ok, why = kits.availability({"engine": "drumgizmo", "drumkit": "library/drumkits/x/x.xml"}, inv)
    assert ok is False and "samples" in why                          # les fichiers d'abord, sans inventaire
    (tmp_path / "library" / "drumkits" / "x").mkdir(parents=True)
    (tmp_path / "library" / "drumkits" / "x" / "x.xml").write_text("<x/>")
    ok, why = kits.availability({"engine": "drumgizmo", "drumkit": "library/drumkits/x/x.xml"}, inv)
    assert ok is False and "DrumGizmo" in why
    assert kits.availability({"engine": "avldrums", "bank": "black-pearl"}, {"error": "x"}) == (None, None)
    assert kits.availability({"engine": "rs5k"}, inv) == (True, None)    # un kit de pads n'est pas jugé ici


def test_le_bloc_drumkit_est_barre_par_le_kit_d_une_scene(monkeypatch):
    from bridge import blockstatus as BS
    monkeypatch.setattr(kits, "get_kit", lambda kid: {"id": kid, "name": kid.title(), "engine": "avldrums" if kid == "pearl" else "drumgizmo"})
    monkeypatch.setattr(kits, "availability", lambda kit, inv=None: (True, None) if kit["id"] == "pearl" else (False, "its samples are not installed on this machine"))
    b = {"type": "drumkit", "id": "dk"}
    ok = {"scenes": [{"id": "A", "params": {"dk": {"kit": "pearl"}}}]}
    bad = {"scenes": [{"id": "A", "params": {"dk": {"kit": "pearl"}}}, {"id": "B", "params": {"dk": {"kit": "monster"}}}]}
    assert BS._drumkit_state(b, ok, None) is None
    st = BS._drumkit_state(b, bad, None)
    assert st["state"] == "unavailable" and "Monster" in st["why"]


def _fake(monkeypatch, docs, ok_ids):
    monkeypatch.setattr(kits, "get_kit", lambda kid: docs.get(kid))
    monkeypatch.setattr(kits, "availability", lambda kit, inv=None:
                        (True, None) if kit["id"] in ok_ids else (False, "its samples are not installed on this machine"))


DOCS = {"monster": {"id": "monster", "name": "Aasimonster", "engine": "drumgizmo", "fallback": "zep"},
        "zep": {"id": "zep", "name": "Red Zeppelin", "engine": "avldrums", "bank": "red-zeppelin"},
        "lone": {"id": "lone", "name": "Lone", "engine": "drumgizmo"}}


def test_un_kit_qui_ne_joue_pas_ici_joue_son_remplacant(monkeypatch):
    # 2026-11-24 : « Iron Thicket » (Aasimonster) restait sans batterie sous Windows
    _fake(monkeypatch, DOCS, {"zep"})
    k, asked = kits.playable("monster")
    assert k["id"] == "zep" and asked["id"] == "monster"
    assert kits.playable("lone") == (DOCS["lone"], None)            # sans remplaçant : le kit, tel quel
    assert kits.playable("absent") == (None, None)


def test_le_kit_joue_lui_meme_la_ou_il_joue(monkeypatch):
    _fake(monkeypatch, DOCS, {"monster", "zep"})                   # Linux : Aasimonster est là
    assert kits.playable("monster") == (DOCS["monster"], None)


def test_un_remplacant_qui_ne_joue_pas_non_plus_ne_remplace_rien(monkeypatch):
    _fake(monkeypatch, DOCS, set())
    assert kits.playable("monster") == (DOCS["monster"], None)


def test_le_bloc_drumkit_remplace_est_pret_et_le_dit(monkeypatch):
    from bridge import blockstatus as BS
    _fake(monkeypatch, DOCS, {"zep"})
    st = BS._drumkit_state({"type": "drumkit", "id": "dk", "params": {"kit": "monster"}}, {"scenes": []}, None)
    assert st["state"] == "ready" and "Red Zeppelin plays Aasimonster" in st["stand_in"]


def test_la_graine_porte_le_remplacant_jusqu_au_kit_deja_pose(tmp_path, monkeypatch):
    import json
    seeds, local = tmp_path / "seeds", tmp_path / "kits"
    seeds.mkdir()
    local.mkdir()
    seed = {"id": "drums-monster", "name": "M", "engine": "drumgizmo", "factory": True, "fallback": "drums-zep"}
    (seeds / "drums-monster.json").write_text(json.dumps(seed), encoding="utf-8")
    (local / "drums-monster.json").write_text(json.dumps({k: v for k, v in seed.items() if k != "fallback"}),
                                              encoding="utf-8")
    monkeypatch.setattr(kits, "FACTORY_DIR", str(seeds))
    monkeypatch.setattr(kits, "KITS_DIR", str(local))
    assert "drums-monster" in kits.seed_factory()
    assert json.loads((local / "drums-monster.json").read_text(encoding="utf-8"))["fallback"] == "drums-zep"
    assert "drums-monster" not in kits.seed_factory()               # idempotent
