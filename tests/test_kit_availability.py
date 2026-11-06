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
