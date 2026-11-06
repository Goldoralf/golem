# SPDX-License-Identifier: GPL-3.0-or-later
"""L'installateur (installer/server.py) et le manifeste des bibliothèques (bridge/libraries.py) —
la logique PURE : vérifications, tailles, détection de Reaper, état installé par composant.
Rien ici ne lance apt, sudo ni un navigateur."""
import importlib.util
import json
import os
import sys

import pytest


from bridge import libraries

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server():
    if sys.platform != "linux":
        pytest.skip("installateur apt réservé à Linux")
    spec = importlib.util.spec_from_file_location("golem_installer", os.path.join(ROOT, "installer", "server.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _linux():
    """Depuis le 2026-10-02 la logique Linux vit dans installer/platform_linux.py (server.py ne connaît
    aucun OS) : les vérifications, les tailles, Reaper et l'askpass se testent là."""
    if sys.platform != "linux":
        pytest.skip("installateur apt réservé à Linux")
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    import platform_linux
    return platform_linux


# ── manifeste + état installé ────────────────────────────────────────────────────────────

def test_le_manifeste_est_lisible_et_chaque_composant_a_une_licence_et_une_source():
    comps = libraries.load_manifest()
    assert len(comps) >= 40
    for c in comps:
        assert c.get("name") and c.get("license") and c.get("url") and c.get("kind"), c["id"]
        assert c.get("check"), f"{c['id']} : pas de check — on ne saurait pas dire s'il est là"


def test_l_etat_installe_vient_de_dpkg_du_venv_et_des_fichiers():
    comps = [
        {"id": "a", "name": "A", "license": "MIT", "url": "u", "kind": "plugin", "check": {"dpkg": ["nope", "calf-plugins"]}},
        {"id": "b", "name": "B", "license": "MIT", "url": "u", "kind": "python", "check": {"pip": ["fastapi"]}},
        {"id": "c", "name": "C", "license": "MIT", "url": "u", "kind": "plugin", "check": {"glob": ["~/.lv2/x.lv2"]}},
        {"id": "d", "name": "D", "license": "MIT", "url": "u", "kind": "js", "check": {"always": True}},
        {"id": "e", "name": "E", "license": "MIT", "url": "u", "kind": "plugin", "check": {"dpkg": ["absent"]}},
    ]
    dpkg = {"calf-plugins": "0.90.3-1"}
    res = [libraries.check_one(c, "/r", "/h", dpkg, {"fastapi"}, exists=lambda pats: pats == ["~/.lv2/x.lv2"]) for c in comps]
    assert res == [(True, "0.90.3-1"), (True, None), (True, None), (True, None), (False, None)]


def test_le_rapport_compte_les_installes_et_liste_les_licences(tmp_path):
    man = tmp_path / "components.json"
    man.write_text(json.dumps({"components": [
        {"id": "a", "name": "A", "license": "GPL-3.0", "url": "u", "kind": "plugin", "check": {"dpkg": ["x"]}},
        {"id": "b", "name": "B", "license": "MIT", "url": "u", "kind": "plugin", "check": {"dpkg": ["y"]}},
        {"id": "p", "name": "P", "license": "CC-BY-4.0", "url": "u", "kind": "asset", "pack": "drums", "mb": 2300, "check": {"glob": ["z"]}}]}))
    r = libraries.report(root="/r", home="/h", manifest=str(man), dpkg={"x": "1"}, pip_names=set(),
                         exists=lambda p: False, platform="linux")
    assert (r["installed"], r["checked"]) == (1, 3)
    assert r["licenses"] == ["CC-BY-4.0", "GPL-3.0", "MIT"]
    assert [c["installed"] for c in r["components"]] == [True, False, False]
    assert "check" not in r["components"][0]
    assert libraries.pack_sizes(str(man)) == {"drums": 2300}


def test_sous_windows_le_manifeste_lit_check_win_et_dit_linux_only(tmp_path):
    """2026-10-03 : 51 composants sur 53 « missing » sous Windows, REAPER et FastAPI compris."""
    man = tmp_path / "components.json"
    man.write_text(json.dumps({"components": [
        {"id": "reaper", "name": "R", "license": "Commercial", "url": "u", "kind": "engine",
         "check": {"glob": ["~/opt/REAPER/reaper"]}, "check_win": {"glob": ["%ProgramFiles%/REAPER (x64)/reaper.exe"]}},
        {"id": "calf", "name": "C", "license": "LGPL", "url": "u", "kind": "plugin", "check": {"dpkg": ["calf-plugins"]}},
        {"id": "fastapi", "name": "F", "license": "MIT", "url": "u", "kind": "python", "check": {"pip": ["fastapi"]}}]}))
    seen = []
    r = libraries.report(root="/r", home="/h", manifest=str(man), dpkg={}, pip_names={"fastapi"},
                         exists=lambda p: seen.append(p) or True, platform="win32")
    st = {c["id"]: (c["installed"], c.get("only")) for c in r["components"]}
    assert st == {"reaper": (True, None), "calf": (None, "linux"), "fastapi": (True, None)}
    assert seen == [["%ProgramFiles%/REAPER (x64)/reaper.exe"]] and "check_win" not in r["components"][0]
    assert (r["installed"], r["checked"]) == (2, 2)


def test_le_venv_windows_est_lu(tmp_path):
    (tmp_path / ".venv" / "Lib" / "site-packages" / "fastapi").mkdir(parents=True)
    assert "fastapi" in libraries.installed_pip(str(tmp_path))


# ── installateur ─────────────────────────────────────────────────────────────────────────

def test_les_verifications_disent_ce_qui_bloque(monkeypatch):
    m = _linux()
    monkeypatch.setattr(m, "os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "22.04", "PRETTY_NAME": "Ubuntu 22.04"})
    monkeypatch.setattr(m, "has_internet", lambda *a, **k: False)
    monkeypatch.setattr(m, "mem_gb", lambda: 4.0)
    monkeypatch.setattr(m, "free_mb", lambda p: 100000)
    # une autre version d'Ubuntu (apt) : orange, pas rouge — golem doit s'installer sur tout Linux (2026-11-03)
    monkeypatch.setattr(m.shutil, "which", lambda n: "/usr/bin/" + n)
    ch = {c["id"]: c for c in m.checks()}
    assert ch["os"]["ok"] is False and ch["os"]["blocking"] is False and "Debian 13" in ch["os"]["detail"]
    assert ch["net"]["ok"] is False and ch["net"]["blocking"] is True
    assert ch["mem"]["ok"] is False and ch["mem"]["blocking"] is False      # orange, pas rouge
    assert ch["disk"]["ok"] is True


def test_sans_apt_le_systeme_bloque_et_dit_pourquoi(monkeypatch):
    m = _linux()
    monkeypatch.setattr(m, "os_release", lambda: {"ID": "fedora", "VERSION_ID": "41", "PRETTY_NAME": "Fedora Linux 41"})
    monkeypatch.setattr(m, "has_internet", lambda *a, **k: True)
    monkeypatch.setattr(m, "mem_gb", lambda: 16.0)
    monkeypatch.setattr(m, "free_mb", lambda p: 100000)
    real = m.shutil.which
    monkeypatch.setattr(m.shutil, "which", lambda n: None if n == "apt-get" else real(n))
    ch = {c["id"]: c for c in m.checks()}
    assert ch["os"]["ok"] is False and ch["os"]["blocking"] is True and "apt" in ch["os"]["detail"]
    monkeypatch.setattr(m, "os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04", "PRETTY_NAME": "Ubuntu 24.04"})
    assert {c["id"]: c for c in m.checks()}["os"]["ok"] is True
    # les autres systèmes où l'install a été menée au bout (VM Debian 13 et Mint 22, 2026-11-03) : verts
    for osr in ({"ID": "debian", "VERSION_ID": "13"}, {"ID": "linuxmint", "VERSION_ID": "22.1"},
                {"ID": "ubuntu", "VERSION_ID": "26.04"}):
        monkeypatch.setattr(m, "os_release", lambda osr=osr: osr)
        assert {c["id"]: c for c in m.checks()}["os"]["ok"] is True, osr


def test_la_taille_vient_du_manifeste_et_de_l_espace_libre(monkeypatch):
    m = _linux()
    monkeypatch.setattr(m, "free_mb", lambda p: 5000)
    sz = m.sizes(ROOT, "/tmp")
    assert sz["free_mb"] == 5000
    assert set(sz["packs"]) == {"di", "piano", "drums", "guitar"} and sz["packs"]["piano"] == 714 and sz["packs"]["guitar"] == 442
    assert sz["required_packs"] == ["di"]                 # les DI de référence : toujours, pas une case à cocher
    assert sz["fixed"]["plugins"] > 250 and sz["fixed"]["system"] == 900


def test_reaper_detecte_epingle_et_liens(tmp_path, monkeypatch):
    m = _linux()
    assert m.reaper_pinned(ROOT) and m.reaper_pinned(ROOT)[0] == "7"
    home = tmp_path / "home"; (home / "opt" / "REAPER").mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home), 1))
    monkeypatch.setattr(m.shutil, "which", lambda x: None)
    d = m.reaper_detect(ROOT)
    assert d["found"] is False and d["download_url"].startswith("https://www.reaper.fm")
    (home / "opt" / "REAPER" / "reaper").write_text("")
    (home / "opt" / "REAPER" / "whatsnew.txt").write_text("v7.78 - September 1 2026\n")
    d = m.reaper_detect(ROOT)
    assert d["found"] is True and d["version"] == "7.78"


def test_l_askpass_ne_contient_jamais_le_mot_de_passe(tmp_path, monkeypatch):
    """Le mot de passe voyage dans l'ENVIRONNEMENT du job ; le helper askpass n'en écrit aucun octet."""
    srv, m = _server(), _linux()
    monkeypatch.setattr(m.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    m._ASKPASS_DIR = None
    srv.S["sudo_pw"] = "s3cret"
    env = srv.job_env({"X": "1"})
    helper = env["SUDO_ASKPASS"]
    assert open(helper).read().count("s3cret") == 0 and "GOLEM_SUDO_PW" in open(helper).read()
    assert env["GOLEM_SUDO_PW"] == "s3cret" and env["X"] == "1" and env["DEBIAN_FRONTEND"] == "noninteractive"
    assert oct(os.stat(helper).st_mode & 0o777) == "0o700"


def test_le_mode_dry_ne_touche_a_rien_mais_joue_les_etapes():
    m = _server()
    m.S.update(src=ROOT, dry=True, sudo_pw="golem", log=[])
    rc = m.run(m.dry_cmd("system"), "system")
    assert rc == 0 and any("Provisioning complete" in l["line"] for l in m.S["log"])


def test_le_poll_d_appairage_clot_la_demande_sur_TOUT_4xx(monkeypatch):
    """Demande golem.fm 2026-09-09 : le jeton naît au POLL, donc deux polls qui se croisent donnent
    un 409 « déjà délivrée ». Traité en « pending », l'écran Connect tournait pour toujours."""
    from bridge import golemfm as M
    for code, why in ((404, "expired"), (409, "already claimed"), (403, "expired")):
        M._pair.update(active=True, code="ABCD", poll_token="pt", approve_url="u", error=None)
        monkeypatch.setattr(M, "_req", lambda *a, **k: (code, {"detail": "x"}))
        r = M.pair_status()
        assert r == {"active": False, "error": why}, code
        assert M._pair["active"] is False
    # injoignable (0) et 5xx restent une ATTENTE : le rack ne jette pas une demande vivante
    M._pair.update(active=True, code="ABCD", poll_token="pt", approve_url="u", error=None)
    monkeypatch.setattr(M, "_req", lambda *a, **k: (0, "unreachable"))
    assert M.pair_status()["pending"] is True and M._pair["active"] is True
    monkeypatch.setattr(M, "_req", lambda *a, **k: (503, "down"))
    assert M.pair_status()["pending"] is True and M._pair["active"] is True


def test_le_pack_guitar_se_telecharge_verifie_sous_windows_et_macos(tmp_path, monkeypatch):
    # la pompe du bloc Standard : même URL et même empreinte que fetch-assets.sh ; une empreinte fausse n'installe rien
    import hashlib
    import io
    import zipfile
    from installer import desktop_steps as D
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Shinyguitar/Programs/acoustic_two.sfz", "<region>")
    data = buf.getvalue()
    (tmp_path / "provision").mkdir()
    logs = []

    class Ctx:
        S = {"dry": False, "packs": ["di", "guitar"]}
        def log(self, msg, sid): logs.append(msg)
    monkeypatch.setattr(D, "_sound_di", lambda ctx, target: None)
    monkeypatch.setattr(D.urllib.request, "urlretrieve", lambda url, dst, reporthook=None: open(dst, "wb").write(data))
    (tmp_path / "provision" / "downloads.sha256").write_text(f"{'0' * 64}  {D.GUITAR_URL}\n")
    D.step_sounds(Ctx(), str(tmp_path))
    assert not (tmp_path / "library" / "sfz" / "Shinyguitar").exists() and "mismatch" in logs[-1]
    (tmp_path / "provision" / "downloads.sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  {D.GUITAR_URL}\n")
    D.step_sounds(Ctx(), str(tmp_path))
    assert (tmp_path / "library" / "sfz" / "Shinyguitar" / "Programs" / "acoustic_two.sfz").exists()
    assert not (tmp_path / "library" / "sfz" / "shinyguitar.zip").exists()
    pinned = open(os.path.join(ROOT, "provision", "downloads.sha256")).read()
    assert D.GUITAR_URL in pinned and D.GUITAR_URL in open(os.path.join(ROOT, "provision", "fetch-assets.sh")).read()


def test_l_instrument_de_l_ecran_play_part_dans_first_run(tmp_path):
    """L'écran « What do you play? » (2026-10-27) : guitare par défaut, un instrument inconnu ignoré, et step_profile
    écrit config/first-run.json — que le bridge applique une fois (bridge/first_run.py, mêmes instruments)."""
    srv = _server()
    from bridge import first_run
    assert srv.INSTRUMENTS == first_run.INSTRUMENTS and srv.S["instrument"] == "guitar"
    srv.S["instrument"] = "bass"
    srv.Ctx.write_first_run(str(tmp_path))
    with open(tmp_path / "config" / "first-run.json", encoding="utf-8") as f:
        assert json.load(f)["instrument"] == "bass"
