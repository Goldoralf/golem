# SPDX-License-Identifier: GPL-3.0-or-later
"""Dexed sous Windows (provision/dexed.py, 2026-11-20) : le synthé du bloc ep existait pour Windows sans que rien ne
l'installe — le Golem Engine ne pouvait pas jouer le piano électrique. Le setup pose désormais le bundle VST3,
vérifié, sans droits d'administrateur, à la version que Linux installe."""
import hashlib
import io
import json
import os
import re
import zipfile

import pytest

from provision import dexed as D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _archive(extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Dexed.vst3/Contents/x86_64-win/Dexed.vst3", b"dll")
        z.writestr("Dexed.vst3/Contents/Resources/moduleinfo.json", b"{}")
        z.writestr("Dexed.clap", b"clap")
        z.writestr("Dexed.exe", b"exe")
        for name in extra:
            z.writestr(name, b"x")
    return buf.getvalue()


def test_la_version_est_celle_de_linux_et_l_archive_est_epinglee():
    sh = open(os.path.join(ROOT, "provision", "plugins.sh"), encoding="utf-8").read()
    assert re.search(r'DEXED_VER="%s"' % re.escape(D.VERSION), sh)
    assert D.PIN["url"].startswith("https://github.com/asb2m10/dexed/releases/download/") and len(D.PIN["sha256"]) == 64


def test_pose_seulement_le_vst3_verifie(tmp_path, monkeypatch):
    data = _archive()
    monkeypatch.setitem(D.PIN, "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(D, "_record", lambda *a, **k: None)
    dest = D.install(fetch=lambda url: data, log=lambda *_: None, dest=tmp_path)
    assert sorted(p.name for p in dest.iterdir()) == ["Dexed.vst3"]       # ni CLAP, ni standalone, ni .part
    assert (dest / "Dexed.vst3" / "Contents" / "x86_64-win" / "Dexed.vst3").read_bytes() == b"dll"
    calls = []
    D.install(fetch=lambda url: calls.append(url), log=lambda *_: None, dest=tmp_path)   # déjà là : rien ne se télécharge
    assert calls == []


def test_une_archive_changee_en_amont_n_est_pas_posee(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_record", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="changed upstream"):
        D.install(fetch=lambda url: _archive(), log=lambda *_: None, dest=tmp_path)
    assert not any(tmp_path.iterdir())


def test_une_archive_ne_sort_jamais_de_son_dossier(tmp_path, monkeypatch):
    data = _archive(extra=("Dexed.vst3/../../evil.dll",))
    monkeypatch.setitem(D.PIN, "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(D, "_record", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="unsafe path"):
        D.install(fetch=lambda url: data, log=lambda *_: None, dest=tmp_path / "vst3")
    assert not (tmp_path / "evil.dll").exists()
    assert not (tmp_path / "vst3" / "Dexed.vst3.part").exists()


def test_le_setup_windows_pose_dexed_et_la_table_le_dit():
    desk = open(os.path.join(ROOT, "provision", "desktop.py"), encoding="utf-8").read()
    assert "dexed.install()" in desk
    win = json.load(open(os.path.join(ROOT, "library", "catalog", "effects-windows.json"), encoding="utf-8"))
    ep = win["unmapped"]["ep"]
    assert ep["family"] == "installed-plugin" and "provision/dexed.py" in ep["note"]
    # le moteur le joue par son identifiant VST3 : celui du bundle officiel (moduleinfo.json de la release 1.0.1)
    eng = json.load(open(os.path.join(ROOT, "library", "catalog", "effects-golem-engine.json"), encoding="utf-8"))
    assert eng["effects"]["ep"]["vst3"] == "ABCDEF019182FAEB4447534244657864"
