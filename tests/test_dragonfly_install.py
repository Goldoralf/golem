# SPDX-License-Identifier: GPL-3.0-or-later
"""Dragonfly Reverb sous Windows (provision/dragonfly.py, 2026-10-22) : effects-windows.json nommait les VST3
Dragonfly sans que rien ne les installe — sur le poste de dev, 45 objets d'usine sur 47 jouaient sans réverbe.
Le setup pose désormais les trois bundles que la table nomme, vérifiés, sans droits d'administrateur."""
import hashlib
import io
import json
import os
import zipfile

import pytest

from provision import dragonfly as D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _archive(extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for b in ("DragonflyEarlyReflections",) + tuple(n[:-5] for n in D.BUNDLES):
            z.writestr(f"{D.ROOT_IN_ZIP}{b}.vst3/Contents/x86_64-win/{b}.vst3", b"dll")
            z.writestr(f"{D.ROOT_IN_ZIP}{b}-vst.dll", b"vst2")
        for name in extra:
            z.writestr(name, b"x")
    return buf.getvalue()


def test_les_bundles_sont_ceux_que_la_table_windows_nomme():
    win = json.load(open(os.path.join(ROOT, "library", "catalog", "effects-windows.json"), encoding="utf-8"))["effects"]
    named = {v["plugin"] for k, v in win.items() if "Dragonfly" in str(v.get("plugin"))}
    assert len(named) == len(D.BUNDLES) == 3
    for b in D.BUNDLES:                                       # « DragonflyPlateReverb » ↔ « Dragonfly Plate Reverb »
        words = b[:-5].replace("Dragonfly", "Dragonfly ").replace("Reverb", " Reverb").split()
        assert any(all(w in n for w in words) for n in named), b
    assert D.PIN["url"].startswith("https://github.com/michaelwillis/") and len(D.PIN["sha256"]) == 64


def test_pose_seulement_les_trois_vst3_verifies(tmp_path, monkeypatch):
    data = _archive()
    monkeypatch.setitem(D.PIN, "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(D, "_record", lambda *a, **k: None)
    dest = D.install(fetch=lambda url: data, log=lambda *_: None, dest=tmp_path)
    assert sorted(p.name for p in dest.iterdir()) == sorted(D.BUNDLES)    # ni VST2, ni Early Reflections, ni .part
    assert (dest / "DragonflyPlateReverb.vst3" / "Contents" / "x86_64-win" / "DragonflyPlateReverb.vst3").read_bytes() == b"dll"
    calls = []
    D.install(fetch=lambda url: calls.append(url), log=lambda *_: None, dest=tmp_path)   # déjà là : rien ne se télécharge
    assert calls == []


def test_une_archive_changee_en_amont_n_est_pas_posee(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_record", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="changed upstream"):
        D.install(fetch=lambda url: _archive(), log=lambda *_: None, dest=tmp_path)
    assert not any(tmp_path.iterdir())


def test_une_archive_ne_sort_jamais_de_son_dossier(tmp_path, monkeypatch):
    data = _archive(extra=(f"{D.ROOT_IN_ZIP}DragonflyHallReverb.vst3/../../evil.dll",))
    monkeypatch.setitem(D.PIN, "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(D, "_record", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="unsafe path"):
        D.install(fetch=lambda url: data, log=lambda *_: None, dest=tmp_path / "vst3")
    assert not (tmp_path / "evil.dll").exists()


def test_le_setup_windows_et_l_installeur_posent_reverbes_et_proteus():
    desk = open(os.path.join(ROOT, "provision", "desktop.py"), encoding="utf-8").read()
    assert "dragonfly.install()" in desk
    inst = open(os.path.join(ROOT, "installer", "platform_windows.py"), encoding="utf-8").read()
    assert '"-Proteus"' in inst
    ps1 = open(os.path.join(ROOT, "provision", "windows", "install-system.ps1"), encoding="utf-8-sig").read()
    assert "[switch]$Proteus" in ps1 and "CheckSha $pr $pins.proteus.sha256" in ps1
    pins = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json"), encoding="utf-8"))
    assert len(pins["proteus"]["sha256"]) == 64 and pins["proteus"]["url"].startswith("https://github.com/GuitarML/")
