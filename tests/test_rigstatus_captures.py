# SPDX-License-Identifier: GPL-3.0-or-later
"""Le statut du rack dit ce qu'il A (captures installées) et la VERSION de ce qu'il SAIT (catalogue) —
réponse golem.fm du 2026-09-09 : « absent ≠ vide », et le catalogue entier n'est jamais dans le
heartbeat (job push-catalog)."""
import json
import os

from bridge import config as C, rigstatus


def _catalog(tmp_path, monkeypatch, tones):
    root = tmp_path
    cat = root / "library" / "catalog"; cat.mkdir(parents=True)
    json.dump({"catalog_version": 7, "amps": [{"id": "marshall-jcm800", "name": "JCM800", "_note": "x"}],
               "pedals": [{"id": "ts9"}], "cabs": [{"id": "412"}], "categories": [{"id": "drive"}],
               "effects": [{"type": "gate", "name": "Gate", "category": "dyn", "params": [{"id": "thr"}]},
                           {"type": "gx-detune", "name": "Detune", "quarantine": "kills Reaper (signal 6)"},
                           {"type": "old", "name": "Old", "quarantine": True}]}, open(cat / "effects.json", "w"))
    json.dump({"brands": [{"id": "marshall"}]}, open(cat / "brands.json", "w"))
    json.dump({"tones": tones}, open(cat / "tones-index.json", "w"))
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "CONFIG_DIR", str(root / "config"))
    return root


def test_captures_ne_liste_que_ce_qui_est_sur_le_disque(tmp_path, monkeypatch):
    root = _catalog(tmp_path, monkeypatch, [
        {"id": 19, "title": "Fender Super Reverb", "gear": "amp-cab", "style": "rock", "tags": ["clean"], "models": [{"id": 1, "file": "assets/a.nam"}, {"id": 2, "file": "assets/missing.nam"}]},
        {"id": 20, "title": "Darkglass B7K", "gear": "pedal", "style": "bass", "tags": ["bass"], "models": [{"id": 3, "file": "assets/b.nam"}]},
        {"id": 21, "title": "Mesa 4x12", "gear": "cab", "style": "metal", "models": [{"id": 4, "file": "assets/c.wav"}]},
        {"id": 22, "title": "Gone", "gear": "amp", "models": [{"id": 5, "file": "assets/nope.nam"}]},
    ])
    (root / "assets").mkdir()
    for f in ("a.nam", "b.nam", "c.wav"):
        (root / "assets" / f).write_text("x")
    caps = rigstatus.captures()
    assert [(c["ref"], c["type"], c["family"], c["models"]) for c in caps] == [("19", "nam", "guitar", 1), ("20", "nam", "bass", 1), ("21", "ir", "guitar", 1)]
    assert rigstatus.captures(limit=2) and len(rigstatus.captures(limit=2)) == 2


def test_le_heartbeat_porte_la_version_du_catalogue_et_les_captures_jamais_le_catalogue(tmp_path, monkeypatch):
    _catalog(tmp_path, monkeypatch, [])
    monkeypatch.setattr(rigstatus, "golem_version", lambda: "v1.9.0")
    monkeypatch.setattr(rigstatus, "reaper_version", lambda: "7.78")
    st = rigstatus.light()
    assert st["catalog_version"] == 7 and st["captures"] == []          # vide = « aucun son » (starter set)
    assert "catalog" not in st and "amps" not in st


def test_le_catalogue_a_la_demande_porte_le_materiel_et_la_quarantaine(tmp_path, monkeypatch):
    _catalog(tmp_path, monkeypatch, [])
    cat = rigstatus.catalog()
    assert cat["catalog_version"] == 7 and cat["amps"] == [{"id": "marshall-jcm800", "name": "JCM800"}]
    assert cat["brands"] == [{"id": "marshall"}] and len(cat["pedals"]) == 1 and len(cat["cabs"]) == 1
    blocks = {b["type"]: b for b in cat["blocks"]}
    assert blocks["gate"]["quarantine"] is False
    assert blocks["gate"]["params"] == [{"id": "thr"}]
    # la RAISON de la quarantaine voyage en clair (golem.fm l'affiche) ; un `true` nu reste un booléen
    assert blocks["gx-detune"]["quarantine"] == "kills Reaper (signal 6)" and blocks["old"]["quarantine"] is True


def test_l_identite_du_rack_a_l_appairage_est_une_liste_blanche(tmp_path, monkeypatch):
    root = _catalog(tmp_path, monkeypatch, [])
    (root / "config").mkdir()
    # 2026-10-06 (docs/installer.md §4) : `profile` = comment GoleM a été LANCÉ (GOLEM_LAUNCH), la trace
    # d'installation vient de config/engine.json — un ancien profile.json ne dit plus le profil
    json.dump({"profile": "rack", "set_by": "installer", "at": "2026-09-01 10:00"}, open(root / "config" / "profile.json", "w"))
    json.dump({"engine": "reaper", "set_by": "installer", "at": "2026-09-09 20:12"}, open(root / "config" / "engine.json", "w"))
    monkeypatch.setenv("GOLEM_LAUNCH", "server")
    monkeypatch.setattr(rigstatus, "golem_version", lambda: "v1.9.0")
    from bridge import connect, serial
    monkeypatch.setattr(connect, "rack_id", lambda: "9f2c" * 6)
    machine = {"arch": "x86_64", "cpu": "Ryzen 5 8500G", "cores": 12, "ram_mb": 31744, "disk_gb": 205,
               "hostname": "golem-rack", "board": "ASRock B650I"}
    monkeypatch.setattr(serial, "machine", lambda: dict(machine))
    r = rigstatus.rack_identity()
    # classifier_version (2026-09-14) : golem.fm classe le marché avec une copie de tools/classify.py
    # et compare cette version à la sienne — un entier, jamais le module
    # rack_id + fiche machine (2026-09-24, docs/connect.md §4.5) : le numéro à vie suit la MACHINE
    assert r == {"version": "v1.9.0", "profile": "server", "installed_at": "2026-09-09 20:12", "installer": "gui",
                 "catalog_version": 7, "classifier_version": rigstatus.classifier_version(),
                 "rack_id": "9f2c" * 6, **machine}
    assert isinstance(r["classifier_version"], int) and r["classifier_version"] >= 1
    assert set(r) <= {"version", "profile", "installed_at", "installer", "catalog_version", "classifier_version",
                      "rack_id", "arch", "cpu", "cores", "ram_mb", "disk_gb", "hostname", "board"}


def test_le_heartbeat_dit_le_mode_le_verrou_et_la_prise_en_cours(tmp_path, monkeypatch):
    """golem.fm grise « Try on my rack » AVANT le clic : mode, locked, recording sont dans le heartbeat."""
    from bridge.state import state
    _catalog(tmp_path, monkeypatch, [])
    monkeypatch.setattr(rigstatus, "golem_version", lambda: "v1.9.0")
    monkeypatch.setattr(rigstatus, "reaper_version", lambda: "7.78")
    monkeypatch.setattr(state, "mode", {"id": "show", "name": "Show", "ui": {"locked": True}}, raising=False)
    monkeypatch.setattr(state, "perf", {"recording": True}, raising=False)
    st = rigstatus.light()
    assert (st["mode"], st["locked"], st["recording"]) == ("show", True, True)
