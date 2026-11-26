# SPDX-License-Identifier: GPL-3.0-or-later
"""golem-fx posé par les installateurs des trois systèmes (2026-11-15, docs/installer.md §2 Pins) : l'archive épinglée
par OS, la pose (bundles seulement, un build de dev gardé, rien hors de la racine), le reçu, le désinstalleur — et le
bridge qui cherche les bundles dans les dossiers VST3 de CHAQUE système (rig.golem_fx_dirs), plus seulement ~/.vst3."""
import hashlib
import io
import json
import os
import stat
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from bridge import rig as _rig
from provision import golem_fx as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_INSTALLED = _rig._golem_fx_installed            # conftest le remplace à chaque test : on garde le vrai
PLUGINS = json.load(open(os.path.join(ROOT, "library", "catalog", "golem-fx-plugins.json"), encoding="utf-8"))["plugins"]
GATE = next(cid for cid, p in PLUGINS.items() if p["name"] == "GoleM FX Gate")
# golem-fx 0.7 (2026-11-26) : recalculées sur les archives téléchargées, égales au SHA256SUMS de la release
SHAS = {"linux": "d81a0eb5751d93fd51354233cad9d0217a8387d69a30baa15b24af2da7f5fbe5",
        "win32": "9d140e9a9de67fd431ad075de81501bf19dbd464e654f473cf71b010a6ceeebd",
        "darwin": "824a4a65e92721ae799cdf9aa3bba7a9e40fcdae049cd09b751de437b443c7db"}


def _tgz(names=("Gate", "Delay"), extra=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        def add(name, data=None, mode=0o644):
            info = tarfile.TarInfo(name)
            if data is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                t.addfile(info)
            else:
                info.size, info.mode = len(data), mode
                t.addfile(info, io.BytesIO(data))
        for n in names:
            b = f"./GoleM FX {n}.vst3"
            add(b + "/")
            add(b + "/Contents/")
            add(b + "/Contents/x86_64-linux/")
            add(f"{b}/Contents/x86_64-linux/GoleM FX {n}.so", b"so-" + n.encode(), 0o755)
        add("./BUILDINFO.txt", b"golem-fx e98eec3")
        for name, data in extra:
            add(name, data)
    return buf.getvalue()


def _zip(names=("Gate",)):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(f"GoleM FX {n}.vst3/Contents/x86_64-win/GoleM FX {n}.vst3", b"dll-" + n.encode())
    return buf.getvalue()


# ── les épingles ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("plat", ["linux", "win32", "darwin"])
def test_l_archive_est_epinglee_la_ou_son_systeme_epingle(plat):
    p = G.pin(plat)
    assert p["url"] == f"{G.BASE}/{G.ASSETS[plat]}" and p["sha256"] == SHAS[plat]
    assert p["url"].startswith("https://github.com/Goldoralf/golem-binaries/releases/download/golem-fx-0.7/")


def test_le_script_linux_passe_par_fetch_verified():
    sh = open(os.path.join(ROOT, "provision", "install-golem-fx.sh"), encoding="utf-8").read()
    assert 'fetch_verified "$GFX_URL"' in sh and G.ASSETS["linux"] in sh and '--dest "$HOME/.vst3"' in sh
    inst = open(os.path.join(ROOT, "provision", "install.sh"), encoding="utf-8").read()
    assert '"$HERE/install-golem-fx.sh" || soft_fail golem-fx' in inst      # jamais fatal
    from installer import platform_linux as L
    assert L.RETRY["golem-fx"] == ("user", "install-golem-fx.sh")
    desk = open(os.path.join(ROOT, "provision", "desktop.py"), encoding="utf-8").read()
    assert "golem_fx.install()" in desk


# ── la pose ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_pose_les_bundles_seulement_executables_et_au_recu(tmp_path, monkeypatch):
    from provision import receipt as R
    rpath = tmp_path / "receipt.json"
    monkeypatch.setenv("GOLEM_RECEIPT", str(rpath))
    rpath.write_text(json.dumps(R._skeleton()), encoding="utf-8")         # un reçu qui EXISTE : l'install l'a créé
    dest = tmp_path / "vst3"
    posed, kept = G.place(_tgz(), G.ASSETS["linux"], dest, journal=tmp_path / "none.json", log=lambda *_: None)
    assert sorted(p.name for p in dest.iterdir()) == ["GoleM FX Delay.vst3", "GoleM FX Gate.vst3"]   # pas BUILDINFO
    so = dest / "GoleM FX Gate.vst3" / "Contents" / "x86_64-linux" / "GoleM FX Gate.so"
    assert so.read_bytes() == b"so-Gate" and (os.name == "nt" or so.stat().st_mode & stat.S_IXUSR)   # pas de bit x sous Windows
    assert kept == [] and len(posed) == 2
    items = {i["path"]: i for i in json.loads(rpath.read_text(encoding="utf-8"))["items"]}
    assert {str(p) for p in posed} <= {R.expand(k) for k in items}
    assert all(i["group"] == "plugins" and i["kind"] == "dir" and not i["prior"] for i in items.values())


def test_un_build_de_dev_est_garde(tmp_path):
    dest = tmp_path / "vst3"
    (dest / "GoleM FX Gate.vst3" / "Contents").mkdir(parents=True)
    (dest / "GoleM FX Gate.vst3" / "Contents" / "mine").write_text("dev build")
    journal = tmp_path / "golem-fx-installed.json"
    journal.write_text(json.dumps({"installed": {"GoleM FX Gate": {"sha": "abc", "commit": "deadbeef"}}}))
    said = []
    posed, kept = G.place(_tgz(), G.ASSETS["linux"], dest, journal=journal, log=said.append)
    assert kept == ["GoleM FX Gate"] and [p.name for p in posed] == ["GoleM FX Delay.vst3"]
    assert (dest / "GoleM FX Gate.vst3" / "Contents" / "mine").read_text() == "dev build"
    assert any("dev build" in s for s in said)


def test_une_archive_ne_sort_jamais_de_sa_racine(tmp_path):
    data = _tgz(extra=[("./GoleM FX Gate.vst3/../../evil.so", b"x")])
    with pytest.raises(RuntimeError, match="unsafe path"):
        G.place(data, G.ASSETS["linux"], tmp_path / "vst3", journal=tmp_path / "none.json", log=lambda *_: None)
    assert not (tmp_path / "evil.so").exists() and not (tmp_path / "vst3").exists()


@pytest.mark.parametrize("plat", ["win32", "darwin"])
def test_windows_et_macos_verifient_l_empreinte_puis_posent(tmp_path, monkeypatch, plat):
    data = _zip() if plat == "win32" else _tgz(("Gate",))
    monkeypatch.setattr(G, "pin", lambda o=None: {"url": f"{G.BASE}/{G.ASSETS[plat]}",
                                                  "sha256": hashlib.sha256(data).hexdigest()})
    monkeypatch.setattr(G, "_record", lambda paths: None)
    posed, _ = G.install(fetch=lambda url: data, log=lambda *_: None, dest=tmp_path, platform=plat,
                         journal=tmp_path / "none.json")
    assert [p.name for p in posed] == ["GoleM FX Gate.vst3"]
    monkeypatch.setattr(G, "pin", lambda o=None: {"url": f"{G.BASE}/{G.ASSETS[plat]}", "sha256": "0" * 64})
    with pytest.raises(RuntimeError, match="changed upstream"):
        G.install(fetch=lambda url: data, log=lambda *_: None, dest=tmp_path / "other", platform=plat)
    assert not (tmp_path / "other").exists()


def test_dossiers_d_installation_par_systeme(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert G.dest_dir("win32") == tmp_path / "Local" / "Programs" / "Common" / "VST3" / "GoleM"
    assert str(G.dest_dir("darwin")).endswith(os.path.join("Library", "Audio", "Plug-Ins", "VST3"))
    assert str(G.dest_dir("linux")).endswith(".vst3")
    with pytest.raises(RuntimeError):
        G.install(platform="linux")                       # Linux : install-golem-fx.sh (fetch_verified)


# ── le bridge : où il cherche, ce qu'il en conclut ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("plat", ["linux", "win32", "darwin"])
def test_le_bridge_trouve_les_bundles_dans_les_dossiers_de_son_systeme(tmp_path, monkeypatch, plat):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))             # « ~ » sous Windows
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("CommonProgramFiles", str(tmp_path / "Common Files"))
    monkeypatch.setattr(_rig, "_platform", lambda: plat)
    dirs = _rig.golem_fx_dirs()
    if plat == "win32":
        assert dirs[0] == os.path.join(str(tmp_path / "Local"), "Programs", "Common", "VST3", "GoleM")
        assert os.path.join(str(tmp_path / "Common Files"), "VST3") in dirs
    elif plat == "darwin":
        assert dirs[0] == os.path.join(str(tmp_path / "home"), "Library", "Audio", "Plug-Ins", "VST3")
        assert "/Library/Audio/Plug-Ins/VST3" in dirs
    else:
        assert dirs[0] == os.path.join(str(tmp_path / "home"), ".vst3")
    assert dirs[0] == str(G.dest_dir(plat))
    monkeypatch.setattr(_rig, "golem_fx_dirs", lambda platform=None: [str(tmp_path / "a"), str(tmp_path / "b")])
    assert REAL_INSTALLED() == set()
    (tmp_path / "b" / "GoleM FX Gate.vst3").mkdir(parents=True)
    assert REAL_INSTALLED() == {GATE}


@pytest.mark.parametrize("plat", ["win32", "darwin"])
def test_windows_et_macos_jouent_golem_fx_quand_il_est_installe(monkeypatch, plat):
    from bridge import engine
    monkeypatch.setattr(engine, "get", lambda: SimpleNamespace(id="reaper"))
    monkeypatch.setattr(_rig, "_platform", lambda: plat)
    monkeypatch.setattr(_rig, "_golem_fx_installed", lambda: set())
    assert _rig._engine_safe_types() == set()
    monkeypatch.setattr(_rig, "_golem_fx_installed", lambda: {GATE})
    assert "gate" in _rig._engine_safe_types()


def test_le_statut_d_un_bloc_golem_fx_sous_windows_suit_son_plugin(monkeypatch):
    # sous Windows, `met` est `unsupported` dans la table de l'OS — sauf quand golem-fx le joue ici
    from bridge import blockstatus as B
    monkeypatch.setattr(B.sys, "platform", "win32")
    monkeypatch.setattr(_rig, "_engine_safe_types", lambda: set())
    assert B.effects()["met"].get("unsupported")
    monkeypatch.setattr(_rig, "_engine_safe_types", lambda: {"met", "chorus"})
    e = B.effects()
    met = next(p for p in PLUGINS.values() if p["name"] == "GoleM FX Met")
    assert not e["met"].get("unsupported") and e["met"]["plugin"] == met["reaper"]
    assert e["chorus"]["plugin"].startswith("VST3: GoleM FX Chorus")        # plus le JSFX de la table Windows
    assert B.candidates("met") == [met["reaper"]]


def test_le_desinstalleur_linux_retire_golem_fx(tmp_path, monkeypatch):
    from provision import uninstall as U
    from tests.uninstall_fixtures import HOME, machine
    fs = machine(tmp_path / "fs")
    monkeypatch.setenv("GOLEM_RECEIPT", fs.p(HOME + "/.local/share/golem/install-receipt.json"))
    for n in ("Gate", "Delay"):
        fs.file(f"{HOME}/.vst3/GoleM FX {n}.vst3/Contents/x86_64-linux/GoleM FX {n}.so")
    it = {i["id"]: i for i in U.build_plan(fs.ctx())["items"]}["plugins:golem-fx"]
    assert it["default"] is True and it["origin"] == "golem-named" and it["action"] == "remove"
    assert sorted(os.path.basename(p) for p in it["_paths"]) == ["GoleM FX Delay.vst3", "GoleM FX Gate.vst3"]
    win = open(os.path.join(ROOT, "provision", "uninstall_win.py"), encoding="utf-8").read()
    assert '"plugins:golem-folder"' in win                  # Windows : le dossier GoleM entier (golem-fx, Dragonfly…)


def test_le_manifeste_des_composants_cite_golem_fx():
    comps = {c["id"]: c for c in json.load(open(os.path.join(ROOT, "provision", "components.json"),
                                                encoding="utf-8"))["components"]}
    c = comps["golem-fx"]
    assert c["license"] == "GPL-3.0" and c["version"] == G.VERSION
    assert any("GoleM FX" in g for g in c["check"]["glob"] + c["check_win"]["glob"] + c["check_mac"]["glob"])


# ── le rattrapage après une mise à jour (docs/update.md §3 bis) ─────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _tampon_isole(tmp_path, monkeypatch):
    # place() note la release posée : jamais dans le vrai ~/.local/share/golem pendant les tests
    monkeypatch.setattr(G, "STAMP", tmp_path / "stamp" / "golem-fx-release.json")


def test_needed_seulement_quand_aucun_bundle_n_est_la(tmp_path):
    dest = tmp_path / "vst3"
    assert G.needed(dest) is True                                          # dossier absent : à poser
    dest.mkdir()
    (dest / "Other.vst3").mkdir()
    assert G.needed(dest) is True                                          # les plugins des autres ne comptent pas
    G.place(_tgz(), G.ASSETS["linux"], dest, journal=tmp_path / "none.json", log=lambda *_: None)
    assert G.needed(dest) is False                                         # la release épinglée est là : rien
    assert G.installed_version() == G.VERSION


def test_une_release_plus_ancienne_est_reposee_une_fois(tmp_path):
    # 2026-11-26 : un golem installé en 0.6 et mis à jour par Settings ▸ About gardait sa 0.6 — le code ne voyait que
    # l'absence de bundles
    dest = tmp_path / "vst3"
    (dest / "GoleM FX Gate.vst3").mkdir(parents=True)
    none = tmp_path / "none.json"
    assert G.needed(dest, journal=none) is True                            # posée avant le tampon : ancienne
    G.STAMP.parent.mkdir(parents=True, exist_ok=True)
    G.STAMP.write_text('{"version": "0.6"}')
    assert G.needed(dest, journal=none) is True                            # une autre release : à reposer
    G.place(_tgz(), G.ASSETS["linux"], dest, journal=none, log=lambda *_: None)
    assert G.needed(dest, journal=none) is False                           # reposée : le tampon le dit


def test_des_builds_de_dev_seuls_ne_sont_jamais_reposes(tmp_path):
    dest = tmp_path / "vst3"
    (dest / "GoleM FX Gate.vst3").mkdir(parents=True)
    j = tmp_path / "dev.json"
    j.write_text('{"installed": {"GoleM FX Gate": {"sha": "x"}}}')
    assert G.needed(dest, journal=j) is False                              # le développeur choisit ses plugins
    (dest / "GoleM FX Boost.vst3").mkdir()
    assert G.needed(dest, journal=j) is True                               # un bundle de release, sans tampon


def test_les_lanceurs_rattrapent_avant_que_reaper_ne_scanne():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reload_sh = open(os.path.join(root, "provision", "reload.sh"), encoding="utf-8").read()
    # reload.sh : posé AVANT la décision d'arrêter REAPER, et des plugins neufs le relancent
    assert reload_sh.index('golem_fx_catch_up "$HERE" && FX_NEW=1') < reload_sh.index("stop_rack_reaper")
    assert '[ "$FX_NEW" = 1 ]' in reload_sh
    start_sh = open(os.path.join(root, "provision", "start.sh"), encoding="utf-8").read()
    assert start_sh.index('golem_fx_catch_up "$HERE"') < start_sh.index('setsid nohup "$REAPER_BIN"')
    desk = open(os.path.join(root, "provision", "desktop.py"), encoding="utf-8").read()
    restart = desk[desk.index("def restart("):desk.index("def _pending_pip(")]
    assert restart.index("_pending_golem_fx()") < restart.index("start(window=False)")   # avant de relancer REAPER et le bridge


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="the Linux launchers' shell library")
def test_le_rattrapage_ne_telecharge_ni_sans_besoin_ni_sans_reseau(tmp_path):
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fake = tmp_path / "golem" / "provision"
    fake.mkdir(parents=True)
    # un faux golem : la vraie bibliothèque, le vrai golem_fx.py, et un install-golem-fx.sh qui laisse une trace
    for name in ("lib-golem-fx.sh", "golem_fx.py", "receipt.py"):
        (fake / name).write_text(open(os.path.join(root, "provision", name), encoding="utf-8").read(), encoding="utf-8")
    (fake / "install-golem-fx.sh").write_text('#!/bin/sh\necho called >> "$(dirname "$0")/called"\n')
    (fake / "install-golem-fx.sh").chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()

    def run(home, net, extra=None):
        (bindir / "curl").write_text(f"#!/bin/sh\nexit {0 if net else 7}\n")
        (bindir / "curl").chmod(0o755)
        env = {**os.environ, "HOME": str(home), "PATH": f"{bindir}:{os.environ['PATH']}", **(extra or {})}
        env.pop("GOLEM_FX_CATCH_UP", None) if not extra else None
        return subprocess.run(["bash", "-c", f'. "{fake}/lib-golem-fx.sh"; golem_fx_catch_up "{fake.parent}"; echo rc=$?'],
                              env=env, capture_output=True, text=True, timeout=30).stdout

    empty = tmp_path / "home-empty"
    empty.mkdir()
    assert "rc=1" in run(empty, net=False) and not (fake / "called").exists()          # pas de réseau : on n'attend pas
    assert "rc=1" in run(empty, net=True, extra={"GOLEM_FX_CATCH_UP": "0"}) and not (fake / "called").exists()
    assert "rc=0" in run(empty, net=True) and (fake / "called").read_text() == "called\n"   # à poser, réseau là
    have = tmp_path / "home-have"
    (have / ".vst3" / "GoleM FX Gate.vst3").mkdir(parents=True)
    (have / ".local" / "share" / "golem").mkdir(parents=True)
    (have / ".local" / "share" / "golem" / "golem-fx-release.json").write_text('{"version": "%s"}' % G.VERSION)
    assert "rc=1" in run(have, net=True) and (fake / "called").read_text() == "called\n"    # la bonne release : rien
    old = tmp_path / "home-old"
    (old / ".vst3" / "GoleM FX Gate.vst3").mkdir(parents=True)                             # posée avant le tampon
    assert "rc=0" in run(old, net=True) and (fake / "called").read_text() == "called\ncalled\n"   # reposée
