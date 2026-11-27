# SPDX-License-Identifier: GPL-3.0-or-later
"""L'inventaire des entités et sa page (tools/golem_inventory.py, tools/snapshot.py, docs/release-tool-plan.md §3).
Aucun réseau, aucun dépôt voisin : `sh` et `http` sont remplacés, la racine et le dossier personnel sont jetables."""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import golem_inventory as inv   # noqa: E402

_spec = importlib.util.spec_from_file_location("golem_snapshot", os.path.join(ROOT, "tools", "snapshot.py"))
snap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(snap)

TAGS = ["golem-engine-9.9-g8", "golem-engine-9.9-g3", "golem-engine-9.9-g10", "golem-fx-0.8.2", "golem-fx-0.8.1",
        "factory-demos-v4", "factory-demos-v10", "linux-plugins-v2"]


def _tree(tmp_path, engine="9.9-g3", fx="0.8.1", win_engine="9.9-g10", mac_fx=None):
    prov = tmp_path / "provision"
    (prov / "windows").mkdir(parents=True)
    (prov / "macos").mkdir()
    (prov / "golem_engine.py").write_text(f'VERSION = "{engine}"\n')
    (prov / "golem_fx.py").write_text(f'VERSION = "{fx}"\n')
    (prov / "windows" / "pins.json").write_text(json.dumps({"golem_engine": {"version": win_engine},
                                                            "golem_fx": {"version": fx}}))
    (prov / "macos" / "pins.json").write_text(json.dumps({"golem_fx": {"version": mac_fx or fx}}))
    return tmp_path


def _ctx(tmp_path, held=None, tags=TAGS):
    root = tmp_path / "golem"
    root.mkdir(exist_ok=True)
    if held is not None:
        (root / "provision").mkdir(exist_ok=True)
        (root / "provision" / "pins-held.json").write_text(json.dumps(held))

    def sh(cmd, cwd=None):
        if cmd[:3] == ["gh", "release", "list"]:
            return json.dumps([{"tagName": t} for t in tags])
        return None
    return inv.Ctx(root=root, home=tmp_path / "home", sh=sh, http=lambda url: None)


def test_les_versions_se_comparent_par_leurs_nombres():
    assert inv.norm("v0.7.3") == "0.7.3" and inv.norm("golem-fx-0.8.2") == "0.8.2" and inv.short("factory-demos-v4") == "v4"
    assert inv.vkey("9.9-g10") > inv.vkey("9.9-g8") and inv.vkey("v10") > inv.vkey("v4")       # pas un tri de texte
    assert inv.latest_of(TAGS, "golem-engine-") == "golem-engine-9.9-g10" and inv.latest_of(TAGS, "factory-demos-") == "factory-demos-v10"
    assert inv.latest_of(TAGS, "nam-") is None


def test_une_epingle_en_retard_est_rouge_et_dit_quoi_faire():
    st, note, fix = inv.compare("9.9-g3", "golem-engine-9.9-g8", what="Linux engine pin")
    assert st == "bad" and "9.9-g8" in note and "9.9-g8" in fix
    assert inv.compare("0.8.2", "golem-fx-0.8.2")[0] == "ok"
    assert inv.compare("7.82", "7.79")[0] == "ok"                       # en avance : rien à monter
    assert inv.compare(None, "1.0")[0] == "na" and inv.compare("1.0", None)[0] == "na"


def test_un_retard_voulu_est_orange_tant_que_rien_de_plus_recent_ne_sort():
    held = {"golem_fx": {"pinned": "0.8.1", "latest": "0.8.2", "reason": "editor archives only", "date": "2026-11-27"}}
    st, note, _ = inv.compare("0.8.1", "golem-fx-0.8.2", "golem_fx", held)
    assert st == "warn" and "editor archives only" in note
    assert inv.compare("0.8.1", "golem-fx-0.8.3", "golem_fx", held)[0] == "bad"     # la raison ne valait que pour 0.8.2
    assert inv.compare("0.8.1", "golem-fx-0.8.2", "reaper", held)[0] == "bad"       # ni pour un autre composant


def test_le_moteur_en_retard_sous_linux_se_voit(tmp_path):
    ctx = _ctx(tmp_path)
    _tree(ctx.root)
    e = inv.read_engine(ctx)
    rows = {r["label"]: r for r in e["rows"]}
    assert rows["Published"]["value"] == "9.9-g10"
    assert rows["Pinned · Linux"]["status"] == "bad" and "9.9-g10" in rows["Pinned · Linux"]["fix"]
    assert rows["Pinned · Windows"]["status"] == "ok" and rows["Pinned · macOS"]["status"] == "na"
    assert rows["Here"]["value"] == "not installed" and e["status"] == "bad"


def test_trois_systemes_qui_n_epinglent_pas_le_meme_golem_fx(tmp_path):
    ctx = _ctx(tmp_path)
    _tree(ctx.root, fx="0.8.2", mac_fx="0.8.1")
    r = {r["label"]: r for r in inv.read_fx(ctx)["rows"]}["Pinned · 3 OS"]
    assert r["status"] == "bad" and "macOS 0.8.1" in r["value"]


def test_sans_reseau_ni_depots_voisins_rien_ne_casse(tmp_path):
    ctx = inv.Ctx(root=tmp_path / "golem", home=tmp_path / "home", offline=True, sh=lambda c, cwd=None: None, http=lambda u: None)
    (tmp_path / "golem").mkdir()
    data = inv.collect(ctx)
    assert [e["id"] for e in data["entities"]] == ["golem", "engine", "fx", "reaper", "factory", "shell", "fm", "site",
                                                    "binaries", "third"]
    assert data["counts"]["bad"] == 0 and data["offline"] is True          # « pas lu » n'est jamais « en retard »
    assert all(r["status"] in inv.ORDER for e in data["entities"] for r in e["rows"])


def test_un_lecteur_qui_plante_ne_cache_pas_les_autres(tmp_path, monkeypatch):
    def boom(ctx):
        raise RuntimeError("boom")
    monkeypatch.setattr(inv, "READERS", [boom, inv.read_engine])
    ctx = _ctx(tmp_path)
    _tree(ctx.root)
    data = inv.collect(ctx)
    assert data["entities"][0]["status"] == "bad" and "boom" in data["entities"][0]["rows"][0]["value"]
    assert data["entities"][1]["id"] == "engine"


def test_la_page_montre_chaque_entite_et_echappe_le_texte(tmp_path):
    ctx = _ctx(tmp_path)
    _tree(ctx.root)
    data = inv.collect(ctx)
    data["entities"][0]["rows"].append(inv.row("Hack", "<script>x</script>", "ok"))
    page = snap.render(data)
    assert page.startswith("<!doctype html>") and "<script>x</script>" not in page and "&lt;script&gt;" in page
    for e in data["entities"]:
        assert f'id="{e["id"]}"' in page
    assert "Before the next release" in page and "9.9-g10" in page
    assert "http://" not in page and "https://" not in page                # autonome : aucune ressource externe


def test_le_fichier_des_retards_voulus_est_lisible():
    held = json.load(open(os.path.join(ROOT, "provision", "pins-held.json"), encoding="utf-8"))
    for key, h in held.items():
        if key.startswith("_"):
            continue
        assert {"pinned", "latest", "reason", "date"} <= set(h), key
