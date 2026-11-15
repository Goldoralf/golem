# SPDX-License-Identifier: GPL-3.0-or-later
"""Les démos d'usine téléchargées plutôt que rendues (bridge/factory_demos.py, docs/preset-preview.md §10)."""
import hashlib
import io
import json
import tarfile

from bridge import config as C
from bridge import factory_demos as F


def _publish(tmp, files):
    """Une « release » sur le disque : l'archive et son index, comme tools/pack-factory-demos.py les fait."""
    src = tmp / "release"
    src.mkdir()
    index = {"items": {}}
    with tarfile.open(src / (F.NAME + ".tar"), "w") as tf:
        for path, data in files.items():
            d, _, f = path.rpartition("/")
            index["items"].setdefault(d, {})[f] = hashlib.sha256(data).hexdigest()
            ti = tarfile.TarInfo(path)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    index["sha256"] = hashlib.sha256((src / (F.NAME + ".tar")).read_bytes()).hexdigest()
    (src / (F.NAME + ".json")).write_text(json.dumps(index))
    return src


def test_only_missing_demos_are_placed_and_a_local_one_is_never_overwritten(tmp_path, monkeypatch):
    src = _publish(tmp_path, {"patch-factory-x/A.opus": b"A", "preset-factory-y/keys-1/A.opus": b"L",
                              "kit-drums-z/rock.opus": b"R"})
    prev = tmp_path / "previews"
    (prev / "kit-drums-z").mkdir(parents=True)
    (prev / "kit-drums-z" / "rock.opus").write_bytes(b"rendered here, newer")
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(prev))
    monkeypatch.setattr(F, "STATE", str(prev / ".factory-demos.json"))
    monkeypatch.setattr(F, "BASE", src.as_uri() + "/")
    F.fetch()
    assert F.status()["state"] == "done" and F.status()["added"] == 2
    assert (prev / "patch-factory-x" / "A.opus").read_bytes() == b"A"
    assert (prev / "preset-factory-y" / "keys-1" / "A.opus").read_bytes() == b"L"      # un niveau plus bas
    assert (prev / "kit-drums-z" / "rock.opus").read_bytes() == b"rendered here, newer"
    F.fetch()                                                                         # rien ne manque : rien ne descend
    assert F.status()["added"] == 0


def test_an_archive_that_does_not_match_its_index_is_refused(tmp_path, monkeypatch):
    src = _publish(tmp_path, {"patch-factory-x/A.opus": b"A"})
    idx = json.loads((src / (F.NAME + ".json")).read_text())
    idx["sha256"] = "0" * 64
    (src / (F.NAME + ".json")).write_text(json.dumps(idx))
    prev = tmp_path / "previews"
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(prev))
    monkeypatch.setattr(F, "STATE", str(prev / ".factory-demos.json"))
    monkeypatch.setattr(F, "BASE", src.as_uri() + "/")
    F.fetch()
    assert F.status()["state"] == "error" and not (prev / "patch-factory-x").exists()


def test_an_index_never_writes_outside_the_previews(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path))
    assert F.missing({"items": {"../evil": {"x": "0"}, "/abs": {"x": "0"}, "ok": {"../x": "0", "a.opus": "0"}}}) == {"ok": ["a.opus"]}
