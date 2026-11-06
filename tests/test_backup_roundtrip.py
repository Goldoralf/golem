# SPDX-License-Identifier: GPL-3.0-or-later
"""Une sauvegarde se RESTAURE (2026-10-09). Trouvé à l'étude du modal I/O : « kits » et « all » rangeaient les prises
(`recordings/`) que l'import refusait — UN chemin refusé fait refuser TOUTE la sauvegarde, donc aucune sauvegarde
complète d'un rack qui a enregistré ne se restaurait. Sous Windows, les chemins en sous-dossier partaient avec « \\ »,
refusés aussi. Et les captures `outboard` n'étaient dans aucune sauvegarde. Ici : chaque catégorie construite puis
relue par l'import, et les prises reviennent."""
import json
import os
import posixpath

import pytest

from bridge import backup as B, config as C, importer as I


@pytest.fixture
def rack(tmp_path, monkeypatch):
    root = tmp_path / "rack"
    for d in ("presets", "setlists", "mappings", "templates", "library/kits", "library/di-refs", "library/catalog",
              "assets/samples", "assets/models", "recordings/perf-20261001-172739"):
        (root / d).mkdir(parents=True)
    monkeypatch.setattr(C, "ROOT", str(root))
    for k, d in (("PRESETS_DIR", "presets"), ("SETLISTS_DIR", "setlists"), ("MAPPINGS_DIR", "mappings"),
                 ("TEMPLATES_DIR", "templates"), ("DI_REFS_DIR", "library/di-refs")):
        monkeypatch.setattr(C, k, str(root / d))
    monkeypatch.setattr(C, "CATALOG", str(root / "library/catalog/tones-index.json"))
    monkeypatch.setattr(B, "KITS_DIR", str(root / "library/kits"))
    monkeypatch.setattr(B, "SAMPLES_DIR", str(root / "assets/samples"))
    monkeypatch.setattr(B, "RECORDINGS_DIR", str(root / "recordings"))
    monkeypatch.setattr(B, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(I, "STAGING", str(tmp_path / "backups" / ".staging"))
    (root / "recordings/perf-20261001-172739/take.wav").write_bytes(b"RIFF take")
    (root / "recordings/perf-20261001-172739/take.json").write_text('{"kind": "perf"}')
    (root / "assets/samples/kick.wav").write_bytes(b"RIFF kick")
    (root / "library/kits/k.json").write_text("{}")
    (root / "assets/models/preamp.nam").write_bytes(b'{"nam": 1}')
    (root / "assets/models/fuzz.nam").write_bytes(b'{"nam": 2}')
    json.dump({"tones": [{"id": "ob1", "gear": "outboard", "models": [{"file": "assets/models/preamp.nam"}]},
                         {"id": "pd1", "gear": "pedal", "models": [{"file": "assets/models/fuzz.nam"}]}]},
              open(C.CATALOG, "w"))
    return root


def _names(r):
    import zipfile
    return set(zipfile.ZipFile(os.path.join(B.BACKUP_DIR, r["file"])).namelist())


@pytest.mark.parametrize("kind", ["presets", "banks", "amps", "cabs", "pedals", "kits", "songs", "originals", "all"])
def test_chaque_categorie_se_relit(rack, kind):
    r = B.build(kind)
    plan = I.inspect(os.path.join(B.BACKUP_DIR, r["file"]))          # lève si un seul chemin est refusé
    assert plan["ok"] and plan["kind"] == kind


def test_les_prises_reviennent(rack):
    r = B.build("recordings")                         # les prises ont leur catégorie depuis la refonte (2026-10-09)
    assert "recordings/perf-20261001-172739/take.wav" in _names(r)
    os.remove(rack / "recordings/perf-20261001-172739/take.wav")
    plan = I.inspect(os.path.join(B.BACKUP_DIR, r["file"]))
    assert plan["recordings"] == {"new": 1, "present": 1}
    res = I.apply(os.path.join(B.BACKUP_DIR, r["file"]))
    assert res["recordings"] == 1
    assert (rack / "recordings/perf-20261001-172739/take.wav").read_bytes() == b"RIFF take"


def test_une_prise_presente_ne_s_ecrase_jamais(rack):
    r = B.build("recordings")
    (rack / "recordings/perf-20261001-172739/take.wav").write_bytes(b"RIFF newer take")
    I.apply(os.path.join(B.BACKUP_DIR, r["file"]), "overwrite")
    assert (rack / "recordings/perf-20261001-172739/take.wav").read_bytes() == b"RIFF newer take"


def test_l_outboard_est_sauvegarde(rack):
    assert "assets/models/preamp.nam" in _names(B.build("pedals"))
    assert "assets/models/preamp.nam" in _names(B.build("all"))
    assert B.counts()["pedals"]["n"] == 2


@pytest.mark.skipif(os.path is not posixpath, reason="simulates Windows separators from POSIX; on Windows the real thing is tested")
def test_sous_windows_les_chemins_du_zip_restent_en_slash(rack, monkeypatch):
    """relpath de Windows rend « perf-…\\take.wav » : le zip doit quand même porter « / »."""
    real = posixpath.relpath                          # os.path EST posixpath ici : garder la vraie avant de la remplacer
    with monkeypatch.context() as m:                  # un contexte À PART : undo() défaisait aussi le rack du test
        m.setattr(B.os, "sep", "\\")
        m.setattr(B.os.path, "relpath", lambda p, start: real(p, start).replace("/", "\\"))
        r = B.build("recordings")
    assert not any("\\" in n for n in _names(r))
    assert I.inspect(os.path.join(B.BACKUP_DIR, r["file"]))["ok"]


# ── LA REFONTE (mockups/io-modal.html, 2026-10-09) ──────────────────────────────────────────────

@pytest.fixture
def more(rack, monkeypatch):
    for k, d in (("PATCHES_DIR", "library/patches"), ("VITAL_DIR", "library/synth/vital"),
                 ("GROOVES_DIR", "library/grooves"), ("STANDARDS_DIR", "library/standards")):
        monkeypatch.setattr(B, k, str(rack / d))
        (rack / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(C, "CONFIG_DIR", str(rack / "config"))
    (rack / "library/patches/paper-kite.json").write_text('{"id": "paper-kite"}')
    for pack in ("factory", "user"):
        (rack / "library/synth/vital" / pack).mkdir()
        (rack / "library/synth/vital" / pack / "pad.vital").write_text("{}")
    (rack / "library/grooves/rock-basic.mid").write_bytes(b"MThd")
    (rack / "library/grooves/index.json").write_text("{}")
    (rack / "library/grooves/packs").mkdir()
    (rack / "library/grooves/packs/jazz.mid").write_bytes(b"MThd")
    (rack / "library/standards/golem").mkdir()
    (rack / "library/standards/golem/so-what.golem").write_bytes(b"PK")
    (rack / "config/cards").mkdir(parents=True)
    for f in ("click.json", "recorder.json", "integrations.json", "auth-devices.json", "network.json", "serial.json"):
        (rack / "config" / f).write_text("{}")
    (rack / "config/cards/V276.json").write_text("{}")
    return rack


def test_les_categories_neuves_portent_ce_qu_il_faut(more):
    assert _names(B.build("patches")) >= {"library/patches/paper-kite.json"}
    syn = _names(B.build("synths"))
    assert "library/synth/vital/user/pad.vital" in syn and not any("factory" in n for n in syn)   # l'usine se réinstalle
    gr = _names(B.build("grooves"))
    assert {"library/grooves/rock-basic.mid", "library/grooves/index.json"} <= gr and not any("packs" in n for n in gr)
    assert "library/standards/golem/so-what.golem" in _names(B.build("standards"))
    assert "recordings/perf-20261001-172739/take.wav" not in _names(B.build("kits"))          # les prises ont leur catégorie


def test_les_reglages_jamais_un_secret(more):
    names = _names(B.build("settings"))
    assert {"config/click.json", "config/recorder.json", "config/cards/V276.json"} <= names
    for secret in ("integrations.json", "auth-devices.json", "network.json", "serial.json"):
        assert "config/" + secret not in names
    # et l'import refuse un réglage hors de la liste, même déclaré au manifeste
    assert not I._safe_path("config/integrations.json") and I._safe_path("config/click.json")


def test_une_selection_fait_un_seul_fichier(more):
    r = B.build(["presets", "patches", "banks"])
    assert r["kind"] == "custom" and r["file"].startswith("golem-presets_patches_banks-")    # « _ » : golem.fm refuse « + »
    import zipfile
    m = json.loads(zipfile.ZipFile(os.path.join(B.BACKUP_DIR, r["file"])).read(B.MANIFEST))
    assert m["kind"] == "custom" and m["kinds"] == ["presets", "patches", "banks"]
    lb = {b["file"]: b for b in B.list_backups()}[r["file"]]
    assert lb["kind"] == "custom" and lb["kinds"] == ["presets", "patches", "banks"]
    assert B.vault_refusal(r["file"]) is None                          # golem.fm v0.54.1 accepte `custom`
    assert B.vault_refusal(B.build("all")["file"]) is None and B.vault_refusal(B.build("amps")["file"]) is None
    assert "stays on this rack" in B.vault_refusal(B.build(["songs", "presets"])["file"])
    assert I.inspect(os.path.join(B.BACKUP_DIR, r["file"]))["kinds"] == ["presets", "patches", "banks"]


def test_le_plan_dit_nouveau_different_identique_et_keep_mine_garde(more):
    r = B.build(["patches", "settings"])
    (more / "library/patches/paper-kite.json").write_text('{"id": "paper-kite", "edited": true}')   # différent ici
    os.remove(more / "config/click.json")                                                            # absent ici
    p = I.inspect(os.path.join(B.BACKUP_DIR, r["file"]))
    assert p["cats"]["patches"] == {"new": 0, "diff": 1, "same": 0}
    assert p["cats"]["settings"]["new"] == 1 and p["cats"]["settings"]["same"] >= 2 and p["diff_total"] == 1
    res = I.apply(os.path.join(B.BACKUP_DIR, r["file"]), "skip")                                     # « Keep mine »
    assert json.loads((more / "library/patches/paper-kite.json").read_text())["edited"] is True
    assert (more / "config/click.json").exists() and res["kept"] == 1 and res["settings"] == 1
    I.apply(os.path.join(B.BACKUP_DIR, r["file"]), "overwrite")                                      # « Use the backup »
    assert "edited" not in json.loads((more / "library/patches/paper-kite.json").read_text())


def test_les_calibrations_mesurees_reviennent(more):
    """Audit 2026-10-15 : profils de contrôleurs, knobs.json et kits mesurés n'étaient dans aucune sauvegarde."""
    cal = {"config/controllers/09e8-0045.json": '{"name": "MPK"}', "config/knobs.json": '{"bankA": [1]}',
           "config/drumkits.local/nitro.json": '{"id": "nitro", "measured": true}'}
    for rel, body in cal.items():
        (more / rel).parent.mkdir(parents=True, exist_ok=True)
        (more / rel).write_text(body)
    r = B.build("settings")
    assert set(cal) <= _names(r)
    assert set(cal) <= _names(B.build("all"))
    for rel in cal:
        os.remove(more / rel)
    plan = I.inspect(os.path.join(B.BACKUP_DIR, r["file"]))           # lève si un chemin est refusé
    assert plan["ok"]
    I.apply(os.path.join(B.BACKUP_DIR, r["file"]))
    for rel, body in cal.items():
        assert (more / rel).read_text() == body
