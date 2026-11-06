# SPDX-License-Identifier: GPL-3.0-or-later

# ── LES CARTES CONNUES, BRANCHÉES OU NON (É3, 2026-09-12) ───────────────────────────────────
# L'écran ne montrait que le BRANCHÉ : préparer une 8×8 avant qu'elle arrive — nommer ses 18
# entrées, la déclarer dans un mode — était un travail que rien ne confirmait. /api/cards dit
# désormais, pour CHAQUE carte du registre, si elle est là, si elle est active, et si son patch
# d'entrées l'attend.
def test_le_registre_dit_branchee_active_et_preparee():
    from bridge import routes_system
    out = routes_system.cards_list()
    assert set(out) >= {"active", "connected", "registry"}
    for d in out["registry"]:
        assert isinstance(d.get("connected"), bool), d.get("id")
        assert isinstance(d.get("active"), bool), d.get("id")
        assert isinstance(d.get("prepared"), bool), d.get("id")   # config/inputmaps/hw-<id>.json
    # une seule carte peut être active, et elle l'est si et seulement si elle porte l'id actif
    act = [d for d in out["registry"] if d["active"]]
    assert len(act) <= 1
    if act:
        assert act[0]["id"] == out["active"]


def test_une_carte_absente_du_registre_nest_pas_inventee(tmp_path, monkeypatch):
    """`prepared` se lit sur le DISQUE, jamais sur une supposition : une carte sans patch doit le
    dire, sinon on croit préparé ce qui ne l'est pas — et on le découvre en branchant, sur scène."""
    from bridge import routes_system, config as C
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    (tmp_path / "inputmaps").mkdir()
    (tmp_path / "inputmaps" / "hw-XR18.json").write_text("{}")
    monkeypatch.setattr(routes_system, "_read_json", lambda *a, **k: {"device": "hw:V276"})
    import bridge.cards as cards_mod
    monkeypatch.setattr(cards_mod, "connected", lambda: [])
    monkeypatch.setattr(cards_mod, "registry", lambda: [{"id": "XR18"}, {"id": "iTwo"}])
    reg = {d["id"]: d for d in routes_system.cards_list()["registry"]}
    assert reg["XR18"]["prepared"] is True and reg["XR18"]["connected"] is False
    assert reg["iTwo"]["prepared"] is False
