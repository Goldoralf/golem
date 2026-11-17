# SPDX-License-Identifier: GPL-3.0-or-later
"""Le Golem Engine posé par l'installation (provision/golem_engine.py, docs/install-v2.md §1) : pose atomique, retour
arrière, archive refusée si elle sort de son dossier, et UNE règle pour trouver le moteur partout."""
import importlib.util
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("golem_engine_prov", ROOT / "provision" / "golem_engine.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


def _archive(version="9.9-g1", launcher=True, extra=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        def add(name, data=b"x"):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        add("golem-engine-x/VERSION", version.encode() + b"\n")
        if launcher:
            add("golem-engine-x/golem/engine/run.sh", b"#!/bin/sh\n")
        for n in extra or []:
            add(n)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _no_receipt(monkeypatch):
    monkeypatch.setattr(G, "_record", lambda paths: None)


def test_la_pose_est_atomique_et_garde_le_moteur_d_avant(tmp_path):
    dest = tmp_path / "opt" / "golem-engine"
    assert G.place(_archive("9.9-g1"), dest=dest, log=lambda s: None) == "9.9-g1"
    assert (dest / G.RUN).is_file() and not (tmp_path / "opt" / "golem-engine.new").exists()
    assert G.place(_archive("9.9-g2"), dest=dest, log=lambda s: None) == "9.9-g2"
    assert G.version_of(tmp_path / "opt" / "golem-engine.prev") == "9.9-g1"      # le retour arrière d'une mise à jour
    assert G.rollback(dest, log=lambda s: None) and G.version_of(dest) == "9.9-g1"
    assert G.rollback(dest, log=lambda s: None) is False                         # plus rien derrière


def test_une_archive_sans_lanceur_ou_qui_sort_de_son_dossier_n_est_jamais_posee(tmp_path):
    dest = tmp_path / "golem-engine"
    G.place(_archive("9.9-g1"), dest=dest, log=lambda s: None)
    with pytest.raises(RuntimeError, match="launcher"):
        G.place(_archive("9.9-g2", launcher=False), dest=dest, log=lambda s: None)
    with pytest.raises(RuntimeError, match="unsafe path"):
        G.place(_archive("9.9-g2", extra=["golem-engine-x/../../evil"]), dest=dest, log=lambda s: None)
    with pytest.raises(RuntimeError, match="one top folder"):
        G.place(_archive("9.9-g2", extra=["other/file"]), dest=dest, log=lambda s: None)
    assert G.version_of(dest) == "9.9-g1" and not dest.with_name("golem-engine.new").exists()   # l'ancien est resté


def test_l_empreinte_fausse_est_refusee_et_sans_release_rien_n_est_pose(tmp_path, monkeypatch):
    data = _archive()
    monkeypatch.setattr(G, "pin", lambda platform=None: {"url": "u", "sha256": "0" * 64})
    with pytest.raises(RuntimeError, match="wrong checksum"):
        G.install(fetch=lambda url: data, dest=tmp_path / "e", log=lambda s: None)
    assert not (tmp_path / "e").exists()
    monkeypatch.undo()
    monkeypatch.setattr(G, "_record", lambda paths: None)
    monkeypatch.setattr(G, "VERSION", "")
    said = []
    assert G.install(fetch=lambda url: data, dest=tmp_path / "e", log=said.append) is None      # dit, jamais fatal
    assert "no release is pinned yet" in said[0] and not (tmp_path / "e").exists()
    # un système où le moteur n'est pas encore porté : pas d'épingle dans son pins.json
    monkeypatch.setattr(G, "VERSION", "9.9-g1")
    with pytest.raises(RuntimeError, match="not available on this system yet"):
        G.pin("win32")


def _mk(d):
    (d / "golem" / "engine").mkdir(parents=True)
    (d / "golem" / "engine" / "run.sh").write_text("#!/bin/sh\n")


def test_le_moteur_se_trouve_partout_par_la_meme_regle(tmp_path, monkeypatch):
    """GOLEM_ENGINE_DIR, sinon l'arbre de dev, sinon le paquet installé — provision, bridge et lanceur."""
    from bridge import engines
    from bridge.engine import ardour as A
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GOLEM_ENGINE_DIR", raising=False)
    req = {"env": "GOLEM_ENGINE_DIR", "default": ["~/golem-engine", "~/opt/golem-engine"], "file": "golem/engine/run.sh"}

    def sh():
        out = subprocess.run(["bash", "-c", f'. "{ROOT}/provision/lib-engine.sh"; start_golem_engine() {{ :; }}; '
                              'dir="${GOLEM_ENGINE_DIR:-}"; if [ -z "$dir" ]; then dir="$HOME/golem-engine"; '
                              '[ -f "$dir/golem/engine/run.sh" ] || { [ -f "$HOME/opt/golem-engine/golem/engine/run.sh" ] '
                              '&& dir="$HOME/opt/golem-engine"; }; fi; echo "$dir"'],
                             env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
        return out.stdout.strip()
    assert G.engine_dir(home=home) == home / "golem-engine" and not engines._requires_ok(req)   # rien : le 1er candidat
    _mk(home / "opt" / "golem-engine")
    assert G.engine_dir(home=home) == home / "opt" / "golem-engine" and engines._requires_ok(req)
    assert A._engine_dir() == str(home / "opt" / "golem-engine") == sh()
    _mk(home / "golem-engine")                                                   # un arbre de dev passe devant
    assert G.engine_dir(home=home) == home / "golem-engine" and A._engine_dir() == str(home / "golem-engine") == sh()
    monkeypatch.setenv("GOLEM_ENGINE_DIR", str(tmp_path / "x"))
    assert G.engine_dir(home=home) == tmp_path / "x" and A._engine_dir() == str(tmp_path / "x")
    assert not engines._requires_ok(req)                                          # la variable désigne un dossier vide


def test_le_descripteur_du_moteur_cherche_aux_deux_endroits():
    import json
    d = json.load(open(ROOT / "config" / "engines" / "ardour.json", encoding="utf-8"))
    assert d["platforms"]["linux"]["requires"]["default"] == ["~/golem-engine", "~/opt/golem-engine"]
