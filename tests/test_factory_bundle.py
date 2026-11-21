# SPDX-License-Identifier: GPL-3.0-or-later
"""LE LOT D'USINE PARTAGÉ avec golem.fm (2026-11-21, docs/preset-preview.md §10, docs/factory.md §3 bis) : ce que
l'index du lot dit de plus (documents, DI de référence, chaque rendu, chaque patch et sa raison), les objets d'usine
retouchés signalés au battement, et le job `factory-reset` qui repousse l'original."""
import importlib.util
import json
import os

import pytest

from bridge import factory, tones_jobs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("pack_factory_demos", os.path.join(ROOT, "tools", "pack-factory-demos.py"))
PK = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PK)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else json.dumps(data).encode())


def test_les_di_de_reference_sont_dites_avec_leur_sha_et_les_absentes_nommees(tmp_path):
    src = str(tmp_path)
    _write(os.path.join(src, "index.json"), {"refs": {"guitar/clean": {"file": "guitar/clean.flac"},
                                                        "keys/pad": {"file": "keys/pad.mid", "kind": "midi"},
                                                        "voice/male": {"file": "voice/male.wav"},
                                                        "evil": {"file": "../secret.wav"}}})
    _write(os.path.join(src, "guitar", "clean.flac"), b"flac")
    _write(os.path.join(src, "keys", "pad.mid"), b"mid")
    doc, files = PK.di_refs(src)
    assert set(doc["refs"]) == {"guitar/clean", "keys/pad"} and doc["missing"] == ["evil", "voice/male"]
    assert doc["refs"]["keys/pad"] == {"file": "di-refs/keys/pad.mid", "sha256": PK._sha_file(os.path.join(src, "keys", "pad.mid")),
                                       "kind": "midi"}
    assert doc["refs"]["guitar/clean"]["kind"] == "audio"
    assert sorted(a for _p, a in files) == ["di-refs/guitar/clean.flac", "di-refs/index.json", "di-refs/keys/pad.mid"]


def test_chaque_rendu_dit_son_patch_sa_scene_sa_di_et_sa_duree(tmp_path):
    root = str(tmp_path)
    for d, extra in (("patch-factory-a", {}), ("patch-factory-a-in2", {}), ("patch-factory-a-plus", {}),
                     ("preset-factory-p/guitar-1", {"made": "copied", "from": "factory-a"})):
        _write(os.path.join(root, d, "A.opus"), d.encode())
        _write(os.path.join(root, d, "preview.json"),
               dict({"ref": "guitar/clean", "refs": {"A": "guitar/crunch"}, "fingerprint": "f" * 16, "generated": "2026-11-16T00:00:00Z",
                     "scenes": {"A": f"library/previews/{d}/A.opus", "B": f"library/previews/{d}/B.opus"}}, **extra))
    di = {"guitar/crunch": {"sha256": "c" * 64}}
    got = PK.renders(root, sorted(os.listdir(root)), ["factory-a"], ["factory-p"], di, lambda f: 12.5)
    # « factory-a-plus » est un AUTRE patch : son dossier n'est pas un rendu de « factory-a » ; la scène B sans fichier non plus
    assert [(r["kind"], r["id"], r.get("input"), r.get("lane"), r["scene"]) for r in got] == [
        ("patch", "factory-a", "1", None, "A"), ("patch", "factory-a", "2", None, "A"), ("preset", "factory-p", None, "guitar-1", "A")]
    r = got[1]
    assert r["file"] == "patch-factory-a-in2/A.opus" and r["sha256"] == PK._sha_file(os.path.join(root, "patch-factory-a-in2", "A.opus"))
    assert (r["duration"], r["di_ref"], r["di_sha256"], r["fingerprint"]) == (12.5, "guitar/crunch", "c" * 64, "f" * 16)
    assert got[2]["made"] == "copied" and got[2]["from"] == "factory-a" and "made" not in r


def test_chaque_patch_d_usine_a_ses_rendus_ou_sa_raison():
    rendered = [{"kind": "patch", "id": "a"}, {"kind": "patch", "id": "a"}, {"kind": "preset", "id": "b"}, {"kind": "patch", "id": "c"}]
    why = {"a": (None, False), "b": ("reference DI missing: voice/male (record it first)", False), "c": (None, True)}
    assert PK.coverage(["c", "a", "b"], rendered, lambda pid, n: why[pid]) == [
        {"id": "a", "renders": 2}, {"id": "b", "renders": 0, "reason": "reference DI missing: voice/male (record it first)"},
        {"id": "c", "renders": 1, "stale": True}]


def test_les_documents_d_usine_sont_ceux_du_depot_avec_leur_empreinte():
    from bridge import preset_export
    docs, hist, files = PK.documents()
    by = {(d["kind"], d["id"]): d for d in docs}
    assert len(docs) == sum(len(v) for v in factory.catalog().values()) == len(files) - 1
    assert hist["file"] == "factory/history.json" and hist["sha256"] == PK._sha_file(factory.HISTORY)
    pid = factory.catalog()["patches"][0][:-5]
    p = os.path.join(factory.SRC, "patches", pid + ".json")
    d = by[("patches", pid)]
    assert d["file"] == f"factory/patches/{pid}.json" and d["sha256"] == PK._sha_file(p)
    assert d["fingerprint"] == preset_export.fingerprint(json.load(open(p, encoding="utf-8")))
    assert all(x["fingerprint"] is None for x in docs if x["kind"] in ("grooves", "dx7"))


def test_l_en_tete_dit_avec_quoi_le_lot_a_ete_rendu():
    h = PK.header("factory-demos-vX")
    cat = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"), encoding="utf-8"))["catalog_version"]
    assert h["tag"] == "factory-demos-vX" and h["catalog_version"] == cat and h["golem_fx_version"]
    assert set(h) == {"tag", "rack_commit", "rack_dirty", "catalog_version", "golem_fx_version"}


def test_un_golem_ne_pose_toujours_que_les_demos(tmp_path):
    # l'index gagne des clés pour golem.fm ; le golem ne lit que `items` (documents et DI viennent avec le dépôt)
    from bridge import factory_demos
    index = {"items": {"patch-factory-a": {"A.opus": "x"}}, "documents": [{"file": "factory/patches/a.json"}],
             "di": {"refs": {"guitar/clean": {"file": "di-refs/guitar/clean.flac"}}}, "renders": [], "patches": []}
    assert factory_demos.missing(index, str(tmp_path)) == {"patch-factory-a": ["A.opus"]}


def test_les_objets_retouches_partent_au_battement_en_kind_id(monkeypatch):
    calls = []
    monkeypatch.setattr(factory, "edited", lambda: calls.append(1) or [
        {"kind": "patches", "file": "factory-x.json", "id": "factory-x", "name": "X"}])
    monkeypatch.setitem(factory._EDITED, "at", 0.0)
    assert factory.edited_ids(now=1000.0) == [{"kind": "patches", "id": "factory-x"}]
    assert factory.edited_ids(now=1030.0) == [{"kind": "patches", "id": "factory-x"}] and len(calls) == 1     # gardé
    factory.edited_ids(now=1000.0 + factory.EDITED_TTL + 1)
    assert len(calls) == 2
    assert factory.files_of([{"kind": "patches", "id": "factory-x"}, {"kind": "grooves", "id": "g"}, {"kind": "nope", "id": "z"},
                             {"kind": "presets", "id": "../x"}, "junk", {"kind": "presets"}]) == ["factory-x.json", "g.mid"]


def test_factory_reset_repousse_l_original_des_objets_nommes(monkeypatch):
    from bridge import rigstatus
    from bridge.state import state
    asked, pushed = [], []
    monkeypatch.setattr(tones_jobs, "_guard_quiet", lambda what: None)
    monkeypatch.setattr(factory, "reset", lambda files=None: asked.append(sorted(files)) or {"reset": ["patches/factory-x.json"]})
    monkeypatch.setattr(factory, "catalog", lambda: {"patches": ["factory-x.json"], "presets": ["factory-p.json"]})
    monkeypatch.setattr(rigstatus, "push_soon", lambda *a, **k: pushed.append(1))
    monkeypatch.setattr(state, "preset_id", "other", raising=False)
    r = tones_jobs._factory_reset({"ids": [{"kind": "patches", "id": "factory-x"}, {"kind": "presets", "id": "factory-p"}]})
    assert asked == [["factory-p.json", "factory-x.json"]] and pushed == [1]
    assert r["reset"] == ["patches/factory-x.json"] and r["unchanged"] == ["factory-p.json"]      # pas retouché : pas touché
    assert "factory-reset" in tones_jobs._HANDLERS
    # sans cible : refusé (tout remettre d'un coup ne se demande pas à distance) ; le preset qui joue : refusé
    with pytest.raises(RuntimeError, match="without ids or files"):
        tones_jobs._factory_reset({})
    monkeypatch.setattr(state, "preset_id", "factory-p", raising=False)
    with pytest.raises(RuntimeError, match="playing right now"):
        tones_jobs._factory_reset({"files": ["factory-p.json"]})


def test_le_rack_pousse_tout_tant_que_golem_fm_ne_dit_pas_ce_qu_il_sert(monkeypatch):
    # `complete: true` : ce qui manque au lot est SUPPRIMÉ sur le site — on ne retire les patches d'usine du lot que
    # lorsque la réponse du battement dit que le magasin de golem.fm les sert, sorte par sorte
    monkeypatch.setattr(factory, "catalog", lambda: {"patches": ["factory-x.json"], "presets": ["factory-p.json"], "setlists": []})
    monkeypatch.setitem(factory._FM_STORE, "kinds", frozenset())
    assert not factory.fm_serves("patches") and not factory.fm_serves("patches", "factory-x")
    factory.set_fm_store({"kinds": ["patches", "bogus"], "rack_commit": "abc"})
    assert factory.fm_serves("patches", "factory-x") and not factory.fm_serves("patches", "mine")
    assert not factory.fm_serves("presets", "factory-p")                        # pas annoncé : poussé comme avant
    for gone in (None, {}, {"kinds": "patches"}, True):                         # absent ou illisible = comme avant
        factory.set_fm_store(gone)
        assert not factory.fm_serves("patches")


def test_un_patch_d_usine_servi_par_golem_fm_ne_part_plus_et_ne_se_rend_plus(monkeypatch):
    from bridge import golemfm, patches, tones_sync
    monkeypatch.setattr(factory, "catalog", lambda: {"patches": ["factory-x.json"], "presets": ["factory-p.json"], "setlists": []})
    monkeypatch.setattr(patches, "list_patches", lambda: [{"id": "factory-x"}, {"id": "mine"}])
    monkeypatch.setattr(patches, "refresh_deps", lambda: None)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://x", "tok"))
    sent = []
    monkeypatch.setattr(golemfm, "_req", lambda path, body=None, token=None, **k: sent.append((path, body)) or (200, {}))

    class Now:                                                  # le minuteur de l'anti-rebond, tiré tout de suite
        def __init__(self, _delay, fn):
            self.fn = fn

        def start(self):
            self.fn()

        def cancel(self):
            pass
        daemon = True
    monkeypatch.setattr(golemfm.threading, "Timer", Now)
    monkeypatch.setitem(factory._FM_STORE, "kinds", frozenset())
    golemfm.push_patches()
    assert [d["id"] for d in sent[-1][1]["patches"]] == ["factory-x", "mine"] and sent[-1][1]["complete"] is True
    monkeypatch.setitem(factory._FM_STORE, "kinds", frozenset({"patches", "presets"}))
    golemfm.push_patches()
    assert [d["id"] for d in sent[-1][1]["patches"]] == ["mine"]
    with pytest.raises(RuntimeError, match="factory content"):
        tones_jobs._patch_preview({"patch_id": "factory-x"})
    with pytest.raises(RuntimeError, match="factory content"):
        tones_jobs._generate_preview({"preset": "factory-p"})
    assert tones_sync.needs_publish("factory-p", {"id": "factory-p"}) is False
    assert tones_sync.publish_preset("factory-p")["ok"] is False


def test_le_battement_dit_les_ids_d_usine_poses_ici(monkeypatch, tmp_path):
    live = tmp_path / "patches"
    live.mkdir()
    (live / "factory-x.json").write_text("{}")
    monkeypatch.setattr(factory, "catalog", lambda: {"patches": ["factory-x.json", "factory-new.json"], "presets": [], "setlists": []})
    monkeypatch.setitem(factory.KINDS, "patches", ("patches", str(live), ".json"))
    assert factory.held()["patches"] == ["factory-x"]             # le patch d'usine plus récent n'est pas (encore) posé


def test_le_lot_n_emporte_que_le_rendu_le_plus_recent_d_un_patch(tmp_path):
    # un patch rendu sur une autre entrée qu'avant garde son ancien dossier : périmé, il ne part pas à côté du bon
    root = str(tmp_path)
    for d, gen in (("patch-factory-a", "2026-11-21T12:00:00Z"), ("patch-factory-a-in2", "2026-11-16T20:00:00Z"),
                   ("patch-factory-a-plus-in2", "2026-11-16T20:00:00Z"), ("patch-factory-b-in2", "2026-11-16T20:00:00Z")):
        _write(os.path.join(root, d, "preview.json"), {"generated": gen})
    dirs = sorted(os.listdir(root)) + ["block-factory-x"]
    assert PK.newest_per_patch(root, dirs, ["factory-a", "factory-a-plus", "factory-b"]) == [
        "patch-factory-a", "patch-factory-a-plus-in2", "patch-factory-b-in2", "block-factory-x"]


def test_un_patch_rendu_sur_une_entree_empruntee_y_est_lie_par_son_numero(monkeypatch, tmp_path):
    # 2026-11-21, carte voix + guitare : le preset temporaire d'un patch de basse restait lié à « Bass 1 », que la carte
    # n'a pas — la lane attendait sa carte et les 6 premiers patches de basse du lot sortaient « no clip rendered »
    from bridge import patches, preview, store
    written = {}
    monkeypatch.setattr(patches, "get_patch", lambda pid: {"id": pid, "role": "bass", "tags": ["rock"]})
    monkeypatch.setattr(preview, "_borrowed_imap", lambda role: ({"inputs": [{"ch": "1", "role": role, "nth": 1}]}, "1"))
    monkeypatch.setattr(patches, "as_preset", lambda doc, imap=None: {"lanes": [
        {"id": "bass-1", "role": "bass", "in_sel": "1", "in_role": "bass", "in_nth": 1, "in_name": "Voice 1"},
        {"id": "keys-1", "role": "keys", "midi": True, "in_role": "keys", "in_nth": 1}]})
    monkeypatch.setattr(preview.C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(store, "_write_json_atomic", lambda path, doc: written.update(doc=doc))
    monkeypatch.setattr(preview, "plan", lambda *a, **k: "stop here")
    assert preview.render_patch_borrowed("factory-bass-x", 1) == {"status": "skipped", "reason": "stop here"}
    bass, keys = written["doc"]["lanes"]
    assert bass == {"id": "bass-1", "role": "bass", "in_sel": "1"}                 # le rôle reste : il choisit la DI
    assert keys["in_role"] == "keys"                                               # une lane MIDI n'emprunte rien


def test_l_enveloppe_d_un_preset_d_usine_garde_les_deps_et_rien_du_rack_de_reference():
    from bridge import preset_export
    shipped = {"id": "factory-p", "name": "P", "lanes": [{"id": "guitar-1", "in_role": "guitar", "in_nth": 1}]}
    out = {"schema_version": 3, "catalog_version": 51, "preset": dict(shipped, lanes=[{"id": "guitar-1", "in_sel": "2"}]),
           "inputs": [{"lane": "guitar-1", "port": "2"}], "foot_context": {"bank": "factory", "slots": [1]},
           "deps": [{"sha256": "a", "kind": "amp", "source": "t3k", "uid": "t3k:1"}, {"sha256": "b", "kind": "kit", "factory": True},
                    {"sha256": "c", "kind": "preview"}], "preview_fingerprint": "bound-to-the-card"}
    env = PK.export_envelope(shipped, out)
    assert env["preset"] == shipped and set(env) == {"schema_version", "catalog_version", "preset", "deps", "preview_fingerprint"}
    assert [d["sha256"] for d in env["deps"]] == ["a", "b"] and env["preview_fingerprint"] == preset_export.fingerprint(shipped)
    assert PK.export_envelope(shipped, dict(out, unresolved=[{"what": "asset"}]))["unresolved"] == [{"what": "asset"}]


def test_une_setlist_d_usine_ne_se_fusionne_jamais_depuis_golem_fm(monkeypatch):
    from bridge import golemfm, setlists
    got = []
    monkeypatch.setattr(factory, "catalog", lambda: {"setlists": ["factory-guitar.json"]})
    monkeypatch.setattr(setlists, "receive_push", lambda doc: got.append(doc["id"]) or {"added": [], "updated": [], "removed": []})
    monkeypatch.setattr(golemfm, "push_setlist", lambda *a, **k: None)
    monkeypatch.setitem(factory._FM_STORE, "kinds", frozenset())           # même sans magasin annoncé
    with pytest.raises(RuntimeError, match="factory content"):
        tones_jobs._setlist_push({"setlist": {"id": "factory-guitar", "lines": []}})
    tones_jobs._setlist_push({"setlist": {"id": "mine", "lines": []}})
    assert got == ["mine"]
