# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/bump.py : monter une épingle d'un seul geste (docs/release-checklist.md A1-A2). Sur une COPIE jetable des vrais
fichiers d'épingle, avec des téléchargements factices : aucun réseau, rien d'écrit dans le dépôt."""
import hashlib
import importlib.util
import json
import os
import re
import shutil

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("golem_bump", os.path.join(ROOT, "tools", "bump.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

FILES = ["provision/golem_fx.py", "provision/golem_engine.py", "provision/downloads.sha256", "provision/windows/pins.json",
         "provision/macos/pins.json", "provision/components.json", "provision/install-reaper.sh", "provision/plugins.sh",
         "provision/dexed.py", "bridge/factory_demos.py", "docs/installer.md"]
COMMIT = "abcdef0123456789abcdef0123456789abcdef01"


def _copy(tmp_path):
    for rel in FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), dst)
    return tmp_path


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _release(family, ver, assets, info):
    """Une release factice de golem-binaries : {adresse: octets}, avec son SHA256SUMS et son BUILDINFO."""
    base = f"{B.BIN}/{family}-{ver}"
    web = {f"{base}/{a}": f"{family} {ver} {a}".encode() for a in assets}
    web[f"{base}/SHA256SUMS"] = "".join(f"{_sha(web[f'{base}/{a}'])}  {a}\n" for a in assets).encode()
    web[f"{base}/BUILDINFO.txt"] = info.encode()
    return web


def _fetch(web):
    def fetch(url):
        if url not in web:
            raise OSError("404")
        return web[url]
    return fetch


def _load(tmp_path, rel):
    return json.loads((tmp_path / rel).read_text(encoding="utf-8"))


def test_golem_fx_ecrit_tous_les_fichiers_de_l_epingle(tmp_path):
    root = _copy(tmp_path)
    web = _release("golem-fx", "9.9.9", B.FX_ASSETS.values(), f"[linux-x86_64] golem-fx {COMMIT} (tag 9.9.9)\n  61 VST3: gfx-a\n")
    plan = B.Plan(root, fetch=_fetch(web), today="2031-01-02")
    B.bump_golem_fx(plan, "9.9.9", fx_repo=tmp_path / "pas-de-depot")
    plan.write()
    assert 'VERSION = "9.9.9"' in (root / "provision/golem_fx.py").read_text()
    dl = (root / "provision/downloads.sha256").read_text()
    lin = _sha(web[f"{B.BIN}/golem-fx-9.9.9/golem-fx-linux-x86_64.tar.gz"])
    assert f"{lin}  {B.BIN}/golem-fx-9.9.9/golem-fx-linux-x86_64.tar.gz" in dl
    assert len(re.findall(r"/golem-fx-[^/]+/golem-fx-linux", dl)) == 1 and f"golem-fx {COMMIT[:7]}" in dl     # l'ancienne ligne est partie
    for system, asset in (("windows", "golem-fx-windows-x86_64.zip"), ("macos", "golem-fx-macos-universal.tar.gz")):
        g = _load(root, f"provision/{system}/pins.json")["golem_fx"]
        assert g["version"] == "9.9.9" and g["url"].endswith(f"/golem-fx-9.9.9/{asset}")
        assert g["sha256"] == _sha(web[g["url"]]) and "golem-fx-9.9.9 " in g["_comment"] and "61 VST3" in g["_comment"]
        assert f"golem-fx {COMMIT[:7]}" in g["_comment"] and "Posés par" in g["_comment"]                       # la suite du commentaire est gardée
    comp = next(c for c in _load(root, "provision/components.json")["components"] if c["id"] == "golem-fx")
    assert comp["version"] == "9.9.9" and comp["url"].endswith("/golem-fx-9.9.9")
    assert "`golem-fx-9.9.9` in Goldoralf/golem-binaries since 2031-01-02, 61" in (root / "docs/installer.md").read_text()
    assert any("sync-golem-fx-manifest" in t for t in plan.todo)          # sans le dépôt golem-fx au tag : dit, à la main


def test_une_empreinte_qui_ne_correspond_pas_n_ecrit_rien(tmp_path):
    root = _copy(tmp_path)
    web = _release("golem-fx", "9.9.9", B.FX_ASSETS.values(), f"golem-fx {COMMIT}\n 58 VST3")
    web[f"{B.BIN}/golem-fx-9.9.9/golem-fx-windows-x86_64.zip"] = b"un autre fichier"       # changé après la publication
    before = {rel: (root / rel).read_text() for rel in FILES}
    plan = B.Plan(root, fetch=_fetch(web))
    with pytest.raises(B.Refused, match="SHA256SUMS says"):
        B.bump_golem_fx(plan, "9.9.9", fx_repo=tmp_path / "x")
    assert {rel: (root / rel).read_text() for rel in FILES} == before          # tout ou rien : rien sur le disque


def test_une_release_pas_publiee_est_refusee(tmp_path):
    plan = B.Plan(_copy(tmp_path), fetch=_fetch({}))
    with pytest.raises(B.Refused, match="is the release published"):
        B.bump_golem_fx(plan, "9.9.9")


def test_le_moteur_monte_linux_et_laisse_windows_sans_archive(tmp_path):
    root = _copy(tmp_path)
    win_before = _load(root, "provision/windows/pins.json")["golem_engine"]
    web = _release("golem-engine", "9.9-g42", ["golem-engine-linux-x86_64.tar.gz"], f"golem-engine {COMMIT} (tag golem-engine-9.9-g42)")
    plan = B.Plan(root, fetch=_fetch(web), today="2031-01-02")
    B.bump_golem_engine(plan, "9.9-g42", "both")
    plan.write()
    assert 'VERSION = "9.9-g42"' in (root / "provision/golem_engine.py").read_text()
    assert "/golem-engine-9.9-g42/golem-engine-linux-x86_64.tar.gz" in (root / "provision/downloads.sha256").read_text()
    assert _load(root, "provision/windows/pins.json")["golem_engine"] == win_before     # l'archive Windows se téléverse à la main
    assert any("no Windows asset yet" in t for t in plan.todo) and any("benches" in t for t in plan.todo)
    with pytest.raises(B.Refused, match="no Windows asset"):
        B.bump_golem_engine(B.Plan(root, fetch=_fetch(web)), "9.9-g42", "windows")


def test_le_moteur_monte_windows_quand_son_archive_est_la(tmp_path):
    root = _copy(tmp_path)
    web = _release("golem-engine", "9.9-g42", ["golem-engine-linux-x86_64.tar.gz", "golem-engine-windows-x86_64.tar.gz"], f"golem-engine {COMMIT}")
    plan = B.Plan(root, fetch=_fetch(web))
    B.bump_golem_engine(plan, "9.9-g42", "windows")
    plan.write()
    g = _load(root, "provision/windows/pins.json")["golem_engine"]
    assert g["version"] == "9.9-g42" and g["sha256"] == _sha(web[g["url"]]) and "golem-engine-9.9-g42" in g["_comment"]
    assert 'VERSION = "9.9-g42"' not in (root / "provision/golem_engine.py").read_text()       # --system windows : Linux ne bouge pas


def test_reaper_ne_monte_pas_sans_avoir_ete_joue_au_rig(tmp_path):
    root = _copy(tmp_path)
    plan = B.Plan(root, fetch=_fetch({}))
    with pytest.raises(B.Refused, match="PLAYED on the rig"):
        B.bump_reaper(plan, "8.01", played=False)
    web = {f"https://www.reaper.fm/files/8.x/reaper801_{s}": s.encode() for s in ("linux_x86_64.tar.xz", "x64-install.exe", "universal.dmg")}
    plan = B.Plan(root, fetch=_fetch(web))
    B.bump_reaper(plan, "8.01", played=True)
    plan.write()
    sh = (root / "provision/install-reaper.sh").read_text()
    assert "REAPER_VERSION:-8.01}" in sh and f"REAPER_SHA256:-{_sha(b'linux_x86_64.tar.xz')}" in sh
    win, mac = _load(root, "provision/windows/pins.json")["reaper"], _load(root, "provision/macos/pins.json")["reaper"]
    assert win["version"] == mac["version"] == "8.01" and win["url"].endswith("reaper801_x64-install.exe")
    assert win["sha256"] == _sha(b"x64-install.exe") and win["signer"] == "Cockos Incorporated"   # ce qui n'est pas l'épingle reste
    assert mac["url"].endswith("reaper801_universal.dmg") and plan.also and plan.also[0].startswith("reaper")


def test_les_demos_d_usine_disent_avec_quoi_elles_ont_ete_rendues(tmp_path):
    root = _copy(tmp_path)
    idx = {"header": {"golem_fx_version": "0.8.2", "catalog_version": 52, "rack_commit": "0123456789"}, "sha256": "x"}
    plan = B.Plan(root, fetch=_fetch({f"{B.BIN}/factory-demos-v77/golem-factory-demos.json": json.dumps(idx).encode()}))
    B.bump_factory_demos(plan, "factory-demos-v77")
    plan.write()
    assert 'TAG = "factory-demos-v77"' in (root / "bridge/factory_demos.py").read_text()
    assert any("golem-fx 0.8.2 · catalogue 52" in d for d in plan.done) and any("golem.fm" in t for t in plan.todo)
    with pytest.raises(B.Refused):
        B.bump_factory_demos(B.Plan(root, fetch=_fetch({})), "v78")


def test_dexed_monte_sous_linux_et_sous_windows(tmp_path):
    root = _copy(tmp_path)
    base = "https://github.com/asb2m10/dexed/releases/download/v9.9.9"
    web = {f"{base}/Dexed-9.9.9-lnx.zip": b"lin", f"{base}/Dexed-9.9.9-win.zip": b"win"}
    plan = B.Plan(root, fetch=_fetch(web))
    B.bump_dexed(plan, "9.9.9")
    plan.write()
    assert 'DEXED_VER="9.9.9"' in (root / "provision/plugins.sh").read_text()
    py = (root / "provision/dexed.py").read_text()
    assert 'VERSION = "9.9.9"' in py and f'"sha256": "{_sha(b"win")}"' in py
    assert f"{_sha(b'lin')}  {base}/Dexed-9.9.9-lnx.zip" in (root / "provision/downloads.sha256").read_text()


def test_un_fichier_dont_la_forme_a_change_arrete_tout(tmp_path):
    root = _copy(tmp_path)
    (root / "provision/golem_fx.py").write_text("# plus de constante VERSION ici\n")
    web = _release("golem-fx", "9.9.9", B.FX_ASSETS.values(), f"golem-fx {COMMIT}\n 58 VST3")
    with pytest.raises(B.Refused, match="changed shape"):
        B.bump_golem_fx(B.Plan(root, fetch=_fetch(web)), "9.9.9", fx_repo=tmp_path / "x")


def test_ce_qui_n_est_pas_automatise_le_dit(capsys):
    assert B.main(["nam-lv2", "0.2.3"]) == 2
    assert "crash patch" in capsys.readouterr().err
