# SPDX-License-Identifier: GPL-3.0-or-later
"""La sauvegarde COMPLÈTE avant désinstallation (docs/uninstall.md §6) : deux zips vérifiés, l'identité, les secrets
seulement sur demande, jamais dans le dossier d'install."""
import json
import os
import stat
import zipfile

import pytest

from bridge import backup as B, backup_cli as CLI, config as C


@pytest.fixture
def rack(tmp_path, monkeypatch):
    root = tmp_path / "rack"
    for d in ("presets", "setlists", "mappings", "templates", "library/catalog", "library/di-refs", "config",
              "songs", "assets/models"):
        (root / d).mkdir(parents=True)
    monkeypatch.setattr(C, "ROOT", str(root))
    for k, d in (("PRESETS_DIR", "presets"), ("SETLISTS_DIR", "setlists"), ("MAPPINGS_DIR", "mappings"),
                 ("TEMPLATES_DIR", "templates"), ("DI_REFS_DIR", "library/di-refs"), ("CONFIG_DIR", "config"),
                 ("SONGS_DIR", "songs")):
        monkeypatch.setattr(C, k, str(root / d))
    monkeypatch.setattr(C, "CATALOG", str(root / "library/catalog/tones-index.json"))
    monkeypatch.setattr(B, "BACKUP_DIR", str(root / "backups"))
    reaper = tmp_path / "reaper-res"
    reaper.mkdir()
    monkeypatch.setenv("GOLEM_REAPER_RESOURCE_DIR", str(reaper))
    (root / "presets/p1.json").write_text('{"id": "p1"}')
    (root / "setlists/s.json").write_text('{"presets": ["p1"]}')
    (root / "assets/models/a.nam").write_bytes(b'{"nam": 1}')
    json.dump({"tones": [{"id": "a", "gear": "amp", "models": [{"file": "assets/models/a.nam"}]}]},
              open(C.CATALOG, "w"))
    (root / "config/click.json").write_text("{}")
    (root / "config/serial.json").write_text('{"serial": "golem_7"}')
    (root / "config/integrations.json").write_text('{"golemfm": {"token": "gmt_secret"}}')
    (root / "config/auth-devices.json").write_text("{}")
    (root / "config/network.json").write_text('{"ap": {"psk": "secret123"}}')
    (root / ".env").write_text("T3K_KEY=abc\n")
    (reaper / "reaper-license.rk").write_text("LICENCE")
    return root


def test_sauvegarde_complete_verifiee(rack, tmp_path):
    dest = tmp_path / "out" / "golem-backup"
    res = CLI.full(str(dest))
    assert res["ok"]
    names = sorted(os.listdir(dest))
    zips = [n for n in names if n.endswith(".zip")]
    assert any(n.startswith("golem-all-") for n in zips) and any(n.startswith("golem-songs-") for n in zips)
    assert (dest / "identity/serial.json").read_text() == '{"serial": "golem_7"}'
    assert (dest / "identity/reaper-license.rk").read_text() == "LICENCE"
    assert not (dest / "secrets").exists()
    readme = (dest / "README.txt").read_text()
    assert "⇅ I/O" in readme and "identity/serial.json" in readme and str(rack / "config/serial.json") in readme
    assert "GoleM" not in readme
    # rien n'a été écrit dans le dossier d'install
    assert not (rack / "backups").exists()
    # le zip « all » ne porte aucun secret
    allz = zipfile.ZipFile(dest / [n for n in zips if n.startswith("golem-all-")][0]).namelist()
    assert "presets/p1.json" in allz and "config/click.json" in allz
    assert not any("integrations" in n or "serial" in n or "network" in n for n in allz)
    assert set(res["verified"]) == set(zips)


def test_secrets_seulement_avec_le_drapeau(rack, tmp_path):
    dest = tmp_path / "bk"
    CLI.full(str(dest), secrets=True)
    for n in ("integrations.json", "auth-devices.json", "network.json", ".env"):
        p = dest / "secrets" / n
        assert p.exists(), n
        if os.name == "posix":                               # Windows n'a pas de bits de mode : rien à affirmer
            assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    if os.name == "posix":                                   # Windows n'a pas de bits de mode
        assert stat.S_IMODE(os.stat(dest / "secrets").st_mode) == 0o700
    assert "KEEP PRIVATE" in (dest / "README.txt").read_text()


def test_destination_dans_le_dossier_d_install_refusee(rack):
    with pytest.raises(CLI.BackupFailed, match="inside the golem install folder"):
        CLI.full(str(rack / "backups" / "x"))
    with pytest.raises(CLI.BackupFailed):
        CLI.full(str(rack))
    assert CLI.main(["full", "--dest", str(rack / "y"), "--json"]) == 1


def test_place_insuffisante_refusee(rack, tmp_path, monkeypatch):
    monkeypatch.setattr(CLI, "_free", lambda d: 1000)
    with pytest.raises(CLI.BackupFailed, match="not enough free space"):
        CLI.full(str(tmp_path / "bk"))
    assert not (tmp_path / "bk").exists()


def test_un_zip_altere_est_detecte(rack, tmp_path):
    dest = tmp_path / "bk"
    CLI.full(str(dest))
    z = dest / [n for n in os.listdir(dest) if n.startswith("golem-all-")][0]
    with zipfile.ZipFile(z) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    members["presets/p1.json"] = b'{"id": "tampered"}'
    with zipfile.ZipFile(z, "w") as zf:
        for n, data in members.items():
            zf.writestr(n, data)
    with pytest.raises(CLI.BackupFailed, match="presets/p1.json"):
        CLI.verify_zip(str(z))


def test_verification_qui_echoue_rend_un_code_non_nul(rack, tmp_path, monkeypatch, capsys):
    def boom(path):
        raise CLI.BackupFailed("x.zip: checksum")
    monkeypatch.setattr(CLI, "verify_zip", boom)
    assert CLI.main(["full", "--dest", str(tmp_path / "bk")]) == 1
    assert "backup FAILED" in capsys.readouterr().err


def test_ligne_de_commande_json(rack, tmp_path, capsys):
    assert CLI.main(["full", "--dest", str(tmp_path / "bk"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["secrets"] is False
    assert {f["path"] for f in out["files"]} >= {"identity/serial.json", "README.txt"}


def test_les_captures_de_l_utilisateur_sont_sauvegardees(rack, tmp_path, monkeypatch):
    """docs/uninstall.md §9.5 : le travail des captures vit HORS du dossier d'install (%LOCALAPPDATA%\\GoleM\\captures,
    ~/.cache/golem-build/captures) — la désinstallation l'efface : la sauvegarde le copie et le vérifie."""
    train = tmp_path / "data" / "nam-train"
    monkeypatch.setenv("GOLEM_NAM_TRAIN", str(train))
    cap = tmp_path / "data" / "captures" / "my-amp-full-20261016"
    (cap / "full").mkdir(parents=True)
    (cap / "full" / "train.json").write_text('{"epochs": 100}')
    (cap / "done.json").write_text("{}")
    need_before = CLI.estimate()
    dest = tmp_path / "bk"
    res = CLI.full(str(dest), secrets=True)
    assert (dest / "captures/my-amp-full-20261016/full/train.json").read_text() == '{"epochs": 100}'
    assert (dest / "captures/my-amp-full-20261016/done.json").exists()
    assert any(f["path"] == "captures/" for f in res["files"])
    readme = (dest / "README.txt").read_text()
    assert str(tmp_path / "data" / "captures") in readme and "NTFS" in readme
    assert need_before >= len('{"epochs": 100}') + 2


def test_le_dossier_des_captures_est_celui_du_bridge(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLEM_NAM_TRAIN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    from bridge import plugin_capture
    assert CLI.captures_dir() == str(plugin_capture.train_home().parent / "captures")


def test_sans_les_cles_pas_de_note_sur_les_cles(rack, tmp_path):
    dest = tmp_path / "bk"
    CLI.full(str(dest))
    assert "NTFS" not in (dest / "README.txt").read_text()
