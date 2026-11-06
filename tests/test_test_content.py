# SPDX-License-Identifier: GPL-3.0-or-later
"""Le PACK DE TEST (library/test-content, bridge/test_content.py — docs/quality-automation.md §8) tient debout : il se
pose et se retire sans laisser de trace ni toucher ce qui était là, chaque patch et preset se compile pour chacune de
ses scènes avec le vrai compilateur, tout ce qu'il référence existe (kit de pads et ses 16 samples d'usine, kit de
batterie, grooves, standard, chanson), ses setlists ne pointent que vers lui, et ses `.golem` se vérifient."""
import json
from pathlib import Path
import zipfile

import pytest

from bridge import config as C, golemfile as G, test_content as T

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "library" / "test-content"
EFFECTS = {e["type"]: e for e in json.loads((ROOT / "library/catalog/effects.json").read_text(encoding="utf-8"))["effects"]}
BUILTIN = ("Rea", "JS", "golem_", "Volume")


def _json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _blocks(x, out):
    if isinstance(x, dict):
        if isinstance(x.get("type"), str) and "id" in x:
            out.append(x)
        for k, v in x.items():
            if k not in ("scenes", "states"):
                _blocks(v, out)
    elif isinstance(x, list):
        for v in x:
            _blocks(v, out)
    return out


@pytest.fixture
def rack(tmp_path, monkeypatch):
    """Un rack vide, où le pack se pose : les dossiers de vie déplacés, la source (le dépôt) inchangée."""
    root = tmp_path / "root"
    for d in ("library/patches", "library/standards/golem", "presets", "setlists", "songs"):
        (root / d).mkdir(parents=True)
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "PRESETS_DIR", str(root / "presets"))
    monkeypatch.setattr(C, "SETLISTS_DIR", str(root / "setlists"))
    monkeypatch.setattr(C, "SONGS_DIR", str(root / "songs"))
    return root


def test_le_pack_se_pose_et_se_retire_sans_trace_ni_degat(rack):
    mine = rack / "library/patches/test-guitar-bench.json"
    mine.write_text('{"mine": true}', encoding="utf-8")            # un fichier de l'utilisateur au même nom
    r = T.install()
    assert len(r["placed"]) >= 10 and [Path(k).name for k in r["kept"]] == ["test-guitar-bench.json"]
    assert mine.read_text(encoding="utf-8") == '{"mine": true}'    # jamais écrasé
    st = T.status()
    assert st["installed"] and len(st["present"]) == len(st["placed"])
    songs = list((rack / "songs").glob("*.golem"))
    assert len(songs) == 1 and G.verify(str(songs[0]))["unknown"] == []
    assert G.verify(str(rack / "library/standards/golem/test-standard.golem"))["unknown"] == []
    r2 = T.remove()
    assert len(r2["removed"]) == len(r["placed"]) and not r2["missing"]
    left = [p.relative_to(rack).as_posix() for p in rack.rglob("*") if p.is_file()]
    assert left == ["library/patches/test-guitar-bench.json"], left     # le fichier de l'utilisateur, seul survivant
    assert T.status()["installed"] is False


def test_la_chanson_de_test_porte_audio_paroles_grille_et_deux_stems(rack):
    T.install()
    song = next((rack / "songs").glob("*.golem"))
    with zipfile.ZipFile(song) as z:
        names = set(z.namelist())
        m = json.loads(z.read("golem.json"))
    assert {"golem.json", G.LYRICS, G.CHART, "audio/original.wav", "stems/drums.wav", "stems/bass.wav"} <= names
    assert m["id"] == T.song_id() and m["files"]["stems/drums.wav"]["part"] == "drums"
    sl = _json(rack / "setlists/test-songs.json")
    assert sl["lines"][0]["band_song"] == m["id"]                   # la setlist nomme la chanson posée
    T.remove()


def _pack_docs():
    return sorted(SRC.glob("patches/*.json")) + sorted(SRC.glob("presets/*.json"))


@pytest.mark.parametrize("file", _pack_docs(), ids=lambda p: p.stem)
def test_chaque_document_du_pack_ne_pose_que_des_blocs_disponibles_partout(file):
    doc = _json(file)
    assert doc["id"].startswith("test-") and doc.get("origin") == "test" and doc["id"] == file.stem
    for b in _blocks(doc, []):
        e = EFFECTS.get(b["type"])
        assert e, (file.name, b["id"], "type inconnu", b["type"])
        if e.get("engine", "plugin") == "plugin":
            assert str(e.get("plugin", "")).startswith(BUILTIN), (file.name, b["id"], b["type"], e.get("plugin"), "pas un intégré ni un JSFX : indisponible sur un runner")


@pytest.mark.parametrize("file", _pack_docs(), ids=lambda p: p.stem)
def test_chaque_document_du_pack_se_compile_pour_chacune_de_ses_scenes(file, tmp_path):
    from tests.test_contracts import _check_plan, _compile
    doc = _json(file)
    scenes = [s["id"] for s in doc.get("scenes") or []] or ["A"]
    assert len(scenes) >= 1
    for sid in scenes:
        plan = _compile(doc, sid, tmp_path)
        _check_plan(plan, doc, f"{file.name} scène {sid}")


def test_tout_ce_que_le_pack_reference_existe():
    kits = {p.stem: _json(p) for p in (ROOT / "library/kits-factory").glob("*.json")}
    grooves = {p.name for p in (ROOT / "library/factory/grooves").glob("*.mid")}
    refs = []
    for file in _pack_docs():
        for b in _blocks(_json(file), []):
            p = b.get("params") or {}
            if b["type"] == "pads":
                kit = kits.get(p["kit"])
                assert kit and kit["engine"] == "rs5k", (file.name, p["kit"])
                for pad in kit["pads"]:
                    assert (ROOT / pad["sample"]).is_file(), (p["kit"], pad["sample"], "sample d'usine absent")
                refs.append(("pads", p["kit"], len(kit["pads"])))
            if b["type"] == "drums":
                assert p["kit"] in kits, (file.name, p["kit"])
                for pat in p.get("patterns") or []:
                    assert Path(pat).name in grooves, (file.name, pat, "groove d'usine absent")
            if b["type"] == "standard":
                assert p["standard"] == "test-standard" and (SRC / "standards/test-standard/song.gsx").is_file()
    assert any(r[0] == "pads" and r[2] == 16 for r in refs), "le kit de pads d'usine doit avoir ses 16 samples"


def test_les_setlists_du_pack_ne_pointent_que_vers_le_pack():
    patches = {p.stem for p in SRC.glob("patches/*.json")}
    presets = {p.stem for p in SRC.glob("presets/*.json")}
    sounds, songs = _json(SRC / "setlists/test-sounds.json"), _json(SRC / "setlists/test-songs.json")
    assert sounds["kind"] == "sounds" and {ln["patch"] for ln in sounds["lines"]} <= patches
    assert len(sounds["lines"]) > len({ln["patch"] for ln in sounds["lines"]})    # un patch partagé par deux lignes
    assert songs["kind"] == "songs" and {ln["preset"] for ln in songs["lines"]} <= presets
    assert songs["lines"][0]["band_song"] == "@TEST_SONG_ID@"                     # substitué à la pose


def test_le_pack_couvre_les_blocs_de_service_et_les_deux_splits():
    types, modes = set(), set()
    for file in _pack_docs():
        doc = _json(file)
        types |= {b["type"] for b in _blocks(doc, [])}
        for lane in doc.get("lanes") or []:
            sp = (lane.get("chain") or {}).get("split")
            if sp:
                modes.add(sp["mode"])
    assert {"rec", "click", "compo", "arrangement", "looper", "tuner", "backing-track", "standard", "drums", "pads"} <= types, types
    assert modes == {"merge", "fanout"}
