# SPDX-License-Identifier: GPL-3.0-or-later
"""L'essai est le preset courant, depuis le rack aussi (docs/patches.md §19, complément 2026-09-14) :
le critère qui décide qu'un brouillon du Designer est un ESSAI (à adopter sous sandbox-try) et non un
preset nommé. `.venv/bin/python -m pytest tests/test_trial_adopt.py -q`"""
from bridge import recall


def test_un_patch_ouvert_ou_un_banc_neuf_sont_des_essais():
    assert recall.is_trial_doc({"id": "nouveau-preset", "name": "⛓ Sunfunk", "__patch": {"id": "sunfunk"}})
    assert recall.is_trial_doc({"id": "nouveau-preset", "name": "New preset"})
    assert recall.is_trial_doc({"id": "sandbox-try", "name": "1983"})
    assert recall.is_trial_doc({"name": "sans id"})


def test_un_preset_nomme_reste_lui_meme():
    assert not recall.is_trial_doc({"id": "velvetine", "name": "Velvetine"})
    assert not recall.is_trial_doc(None) and not recall.is_trial_doc("x")


def test_la_fiche_de_l_essai_porte_ses_stomps_et_ses_scenes(tmp_path, monkeypatch):
    """/live lit la fiche COMPACTE (switches, scenes) : l'essai doit en avoir une, comme un preset."""
    import json
    from bridge import config as C, store
    (tmp_path / "presets").mkdir(); monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    doc = {"id": "nouveau-preset", "name": "⛓ Paper Kite", "lanes_v": 2,
           "lanes": [{"id": "guitar", "role": "guitar", "chain": {"pre": [{"id": "b1", "type": "gate", "foot": 6}], "split": None, "post": []}}],
           "scenes": [{"id": "A", "name": "Intro", "blocks": {}}, {"id": "B", "name": "Wall", "blocks": {}}]}
    json.dump({"preset": doc, "scene": "A"}, open(tmp_path / "presets" / ".sandbox.json", "w"))
    p = store.load_preset(store.SANDBOX_TRY_ID)
    fiche = store.preset_summary(p)
    assert fiche["id"] == "sandbox-try" and [s["id"] for s in fiche["scenes"]] == ["A", "B"]
    assert fiche["used"] == [6] and fiche["switches"][0]["sw"] == 6 and fiche["switches"][0]["blocks"][0]["id"] == "b1"


def test_l_id_de_l_essai_n_est_jamais_un_fichier():
    """docs/patches.md §19 : aucun presets/sandbox-try.json. Vécu le 2026-09-23 — un preset nommé ouvert
    pendant un essai avait été rebaptisé sandbox-try par sandbox_apply, et l'auto-save l'avait écrit."""
    import asyncio, json
    from bridge import routes_content as RC
    for pid in ("sandbox-try", "nouveau-preset"):
        r = asyncio.run(RC.save_preset({"id": pid, "name": "x", "lanes": [], "scenes": []}))
        assert r.status_code == 400 and "not a preset" in json.loads(r.body)["error"]
