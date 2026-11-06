# SPDX-License-Identifier: GPL-3.0-or-later
"""La mise à jour PAR ARCHIVE d'une install sans git — Windows, macOS (docs/update.md §3, 2026-11-06) : GitHub dit la
release, son zip est posé par la fonction de l'installateur, l'état local reste, ce que la version n'a plus part."""
import io
import json
import os
import zipfile

import pytest

from bridge import config as C
from bridge import release_update as U
from installer import desktop_steps as D


def test_les_versions_se_comparent_par_nombres():
    assert U.vkey("v0.6.10") > U.vkey("v0.6.9") > U.vkey("v0.6") > U.vkey("nightly")
    assert U.vkey("0.6.1") == U.vkey("v0.6.1") == (0, 6, 1)


@pytest.mark.parametrize("name,tag", [("golem-v0.6.2", "v0.6.2"), ("golem-0.6.2", "v0.6.2"),
                                      ("golem-main", None), ("golem", None)])
def test_le_nom_du_dossier_dit_la_release(name, tag):
    assert D.release_of("/tmp/x/" + name) == tag


def _write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.fixture
def install(tmp_path, monkeypatch):
    """Une install v0.6.1 sans git : du code, un module retiré par la version suivante, de l'état local."""
    root = tmp_path / "golem"
    for rel, txt in {"bridge/app.py": "v1", "bridge/old.py": "gone soon", "provision/x.sh": "v1",
                     "bridge/requirements.lock": "a==1", "presets/mine.json": "MINE",
                     "config/click.json": "my click"}.items():
        _write(str(root), rel, txt)
    D.write_release_marker(str(root), "v0.6.1",
                           ["bridge/app.py", "bridge/old.py", "provision/x.sh", "bridge/requirements.lock",
                            "config/click.json"])
    monkeypatch.setattr(C, "ROOT", str(root))
    return root


def _release(tmp_path, lock="a==1"):
    src = tmp_path / "dl" / "golem-0.6.2"
    for rel, txt in {"bridge/app.py": "v2", "bridge/new.py": "new", "provision/x.sh": "v2",
                     "bridge/requirements.lock": lock, "config/click.json": "factory click",
                     "presets/mine.json": "factory"}.items():
        _write(str(src), rel, txt)
    return lambda tag, work: str(src)


def _read(root, rel):
    return open(os.path.join(root, *rel.split("/")), encoding="utf-8").read()


def test_la_release_est_posee_et_l_etat_local_reste(tmp_path, install, monkeypatch):
    monkeypatch.setattr(U.sys, "platform", "linux")
    r = U.apply("v0.6.2", fetch_src=_release(tmp_path))
    assert r == {"ok": True, "pip": False, "removed": 1}
    assert _read(install, "bridge/app.py") == "v2" and _read(install, "bridge/new.py") == "new"
    assert not (install / "bridge" / "old.py").exists()                 # la nouvelle version ne l'a plus
    assert _read(install, "presets/mine.json") == "MINE"                 # l'état local n'est jamais écrasé
    assert _read(install, "config/click.json") == "my click"             # ni retiré
    assert U.installed() == "v0.6.2"
    assert "bridge/new.py" in json.loads(_read(install, ".golem-files"))


def test_un_verrou_pip_change_sous_windows_laisse_le_drapeau(tmp_path, install, monkeypatch):
    monkeypatch.setattr(U.sys, "platform", "win32")
    r = U.apply("v0.6.2", fetch_src=_release(tmp_path, lock="a==2"))
    assert r["pip"] is True and (install / ".golem-pip-pending").exists()   # pip au redémarrage, bridge arrêté


def test_l_etat_dit_la_release_et_ses_notes(install, monkeypatch):
    monkeypatch.setattr(U, "check", lambda fetch=False: {"latest": "v0.6.2", "notes": "What's new", "fetch_error": None})
    st = U.status(fetch=True)
    assert (st["current"], st["latest"], st["status"], st["notes"], st["mode"]) == \
        ("v0.6.1", "v0.6.2", "update-available", "What's new", "archive")
    monkeypatch.setattr(U, "check", lambda fetch=False: {"latest": "v0.6.1", "notes": "x", "fetch_error": None})
    assert U.status()["status"] == "up-to-date"
    os.remove(install / ".golem-release")                                  # une install d'avant : version inconnue
    assert U.status()["status"] == "update-available" and U.status()["current"] == "unknown"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_la_question_a_github_et_hors_ligne(install, monkeypatch):
    body = json.dumps({"tag_name": "v0.6.2", "body": "notes"}).encode()
    monkeypatch.setattr(U.urllib.request, "urlopen", lambda req, timeout=0: _Resp(body))
    assert U.check(fetch=True) == {"latest": "v0.6.2", "notes": "notes", "fetch_error": None}

    def offline(req, timeout=0):
        raise OSError("no network")
    monkeypatch.setattr(U.urllib.request, "urlopen", offline)
    c = U.check(fetch=True)
    assert c["latest"] == "v0.6.2" and "cannot reach GitHub" in c["fetch_error"]   # la dernière réponse reste


def _zip(entries):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return b.getvalue()


def test_le_zip_est_extrait_et_jamais_hors_de_son_dossier(tmp_path, monkeypatch):
    good = _zip({"golem-0.6.2/bridge/app.py": "x", "golem-0.6.2/provision/a.sh": "y"})
    monkeypatch.setattr(U.urllib.request, "urlopen", lambda req, timeout=0: _Resp(good))
    out = U.download("v0.6.2", str(tmp_path))
    assert os.path.basename(out) == "golem-0.6.2" and os.path.isfile(os.path.join(out, "bridge", "app.py"))
    evil = _zip({"golem-0.6.2/bridge/app.py": "x", "golem-0.6.2/provision/a.sh": "y", "../evil.txt": "z"})
    monkeypatch.setattr(U.urllib.request, "urlopen", lambda req, timeout=0: _Resp(evil))
    (tmp_path / "2").mkdir()
    with pytest.raises(ValueError):
        U.download("v0.6.2", str(tmp_path / "2"))


def test_la_page_about_passe_par_l_archive_sans_git(install, monkeypatch):
    from bridge import routes_system as R
    monkeypatch.setattr(U, "check", lambda fetch=False: {"latest": "v0.6.2", "notes": "n", "fetch_error": None})
    st = R.system_update(fetch=1)
    assert st["mode"] == "archive" and st["status"] == "update-available"
