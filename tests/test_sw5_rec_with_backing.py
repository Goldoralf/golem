# SPDX-License-Identifier: GPL-3.0-or-later
"""SW5 porte le bloc Rec ET le bloc Backing : UN geste lance la prise AVEC le backing.

2026-09-21 : « je lance le backing via le SW5 et il se lance avec le REC ». Mesuré le même
jour : cinq « mute (perf-rec actif) : ON » dans .backing.log, aucun backing audible. Deux chemins
se battaient — le CC lançait la prise, et golem_perfrec coupait le bus parce que le transport ne
tournait pas ENCORE ; puis la Note du même switch rejouait le geste du backing, qui se croyait en
lecture (la prise avait lancé le transport) et faisait « pause ». Et après chaque redémarrage du
bridge, l'adoption du rig ne réarmait pas le backing du tout.
app.py et les scripts Reaper ne se montent pas en test : on lit leur source, comme
test_foot_scene_no_preset_recall.py."""
from bridge import backing as backing_mod
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(path, start, end):
    s = (ROOT / path).read_text(encoding="utf8")
    return s[s.index(start):s.index(end, s.index(start))]


def test_le_cc_du_switch_lance_la_prise_avec_le_backing():
    body = _src("bridge/app.py", "def _do_stomp", "if \"click\" in types:")
    assert '_foot_perf_toggle(with_backing="backing-track" in types, want=want)' in body
    toggle = _src("bridge/app.py", "def _foot_perf_toggle", "def _compo_tap")
    assert 'cmd["backing"] = True' in toggle


def test_la_note_du_meme_switch_ne_rejoue_pas_le_geste_du_backing():
    body = _src("bridge/app.py", "def _on_stomp_edge", "smp = ")
    assert body.index("_rec_with_backing(sw)") < body.index("_backing_ctl.on_edge(sw, on)")


def test_golem_perfrec_ne_coupe_pas_un_backing_voulu():
    lua = (ROOT / "reaper/Scripts/golem_perfrec.lua").read_text(encoding="utf8")
    assert "local function op_start(want_backing)" in lua
    assert lua.index("if want_backing then") < lua.index("elseif not was_playing then")
    assert "local want = body:find('\"backing\"%s*:%s*true') ~= nil" in lua and "op_start(want)" in lua


def test_le_demarrage_du_bridge_rearme_le_backing():
    body = _src("bridge/recall.py", "# ADOPTION", "log_boot.info(f\"rig déjà monté")
    assert '"enabled": bool(songs) and modes_mod.allows("backing", state.mode)' in body
    assert "_backing_ctl.adopt(songs, " in body                      # + la règle des stems (song-backing.md §3)


def test_une_prise_part_de_zero_et_y_revient():
    lua = (ROOT / "reaper/Scripts/golem_perfrec.lua").read_text(encoding="utf8")
    start = lua[lua.index("local function op_start"):lua.index("local function op_stop")]
    assert "from_zero = not was_playing" in start
    assert start.index("SetEditCurPos(0, false, false)") < start.rindex("CSurf_OnRecord()")   # rindex : le 1er est un commentaire
    fin = lua[lua.index("local function finalize"):]
    assert "if from_zero then" in fin


def test_le_decompte_est_decompte_par_reaper_et_s_annule():
    lua = (ROOT / "reaper/Scripts/golem_perfrec.lua").read_text(encoding="utf8")
    assert "start_at = { t = reaper.time_precise() + in_ms / 1000, backing = want }" in lua
    assert "décompte annulé" in lua
    toggle = _src("bridge/app.py", "def _foot_perf_toggle", "def _compo_tap")
    assert 'cmd["in_ms"]' in toggle and "_countin_end()" in toggle


def test_count_in_borne_de_0_a_2_mesures(tmp_path, monkeypatch):
    from bridge import store
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "recorder.json"))
    assert store.load_recorder_cfg()["count_in"] == 0
    assert store.save_recorder_cfg({"count_in": 7})["count_in"] == 2
    assert store.save_recorder_cfg({"count_in": "x"})["count_in"] == 0
    assert store.save_recorder_cfg({"count_in": 1})["count_in"] == 1
    assert store.load_recorder_cfg()["count_in"] == 1


def test_adopt_arme_la_liste_sans_rien_envoyer(monkeypatch):
    sent = []
    monkeypatch.setattr(backing_mod, "write_command", lambda c: sent.append(c))
    ctl = backing_mod.BackingControl(osc=None)
    ctl.adopt([{"slug": "glass_lanterns_paper_kite"}])
    assert ctl.snapshot_extra()["songs"] == [{"slug": "glass_lanterns_paper_kite"}] and sent == []
