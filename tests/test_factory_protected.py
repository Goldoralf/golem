# SPDX-License-Identifier: GPL-3.0-or-later
"""L'usine se cache, elle ne s'efface pas (décision du mainteneur, 2026-11-15) : chaque route de suppression la refuse."""
from fastapi.testclient import TestClient

from bridge import factory


def test_protected_reads_the_factory_catalog(monkeypatch):
    monkeypatch.setattr(factory, "catalog", lambda: {"patches": ["factory-x.json"], "grooves": ["golem-a.mid"]})
    assert factory.protected("patches", "factory-x")
    assert factory.protected("grooves", "golem-a")
    assert not factory.protected("patches", "mine")
    assert not factory.protected("unknown", "factory-x")


def test_delete_routes_refuse_factory_content(monkeypatch):
    import json
    from bridge import patches, grooves, setlists, store, routes_patches, routes_content as RC
    monkeypatch.setattr(factory, "catalog", lambda: {"patches": ["factory-x.json"], "presets": ["factory-p.json"],
                                                     "setlists": ["factory-s.json"], "grooves": ["golem-a.mid"]})
    gone = []
    monkeypatch.setattr(patches, "delete_patch", lambda pid: gone.append(pid) or True)
    monkeypatch.setattr(grooves, "delete_groove", lambda gid: gone.append(gid) or {"ok": True})
    monkeypatch.setattr(setlists, "remove", lambda sid: gone.append(sid) or {"ok": True})
    monkeypatch.setattr(store, "delete_preset", lambda pid: gone.append(pid) or {"deleted": True, "banks_freed": 0})
    for call in (lambda: routes_patches.api_delete("factory-x"), lambda: RC.delete_preset("factory-p"),
                 lambda: RC.setlists_delete("factory-s"), lambda: RC.groove_delete("golem-a")):
        r = call()
        body = json.loads(r.body)
        assert r.status_code == 403 and body["factory"] and "Hide it" in body["error"]
    assert gone == []
    # ce qui n'est pas d'usine s'efface toujours
    assert RC.groove_delete("mine") == {"ok": True} and gone == ["mine"]


def test_golem_fm_porte_le_reglage_de_l_usine_masquee_du_proprietaire(tmp_path, monkeypatch):
    # 2026-11-15 : UN réglage pour golem.fm et le golem — `prefs.factory_hidden` du propriétaire, servi au roster
    from bridge import factory, roster
    monkeypatch.setattr(factory, "VIS_FILE", str(tmp_path / "show.json"))
    band = {"people": [{"id": "u1", "rights": "member", "prefs": {"factory_hidden": "presets"}},
                       {"id": "u2", "rights": "owner", "prefs": {"factory_hidden": "patches,kits,bogus"}}]}
    monkeypatch.setattr(roster, "read", lambda: band)
    assert factory.fm_hidden() == {"patches", "kits"}                    # le propriétaire, pas un membre
    show = factory.visibility()
    assert show["patches"] is False and show["kits"] is False and show["presets"] is True
    assert factory.set_visibility({"patches": True})["patches"] is False   # golem.fm décide tant qu'il en dit quelque chose
    band["people"][1]["prefs"] = {"factory_hidden": ""}
    assert all(factory.visibility().values())                            # "" = tout montrer
    band["people"][1]["prefs"] = {}
    assert factory.fm_hidden() is None and factory.visibility()["patches"] is True   # rien de golem.fm : le local vaut
    band["people"] = []
    assert factory.fm_hidden() is None
