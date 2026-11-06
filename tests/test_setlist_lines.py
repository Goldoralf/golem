# SPDX-License-Identifier: GPL-3.0-or-later
"""La LIGNE de setlist (docs/setlists.md §9, FIGÉ 2026-09-08) : vieilles listes lisibles, ordre
réconcilié sans perdre les lignes, fusion par id/rev (égalité au rack), complete, attente en mode
verrouillé, tempo de ligne au rappel."""
import json
import os

import pytest

from bridge import setlists as sl


@pytest.fixture
def sldir(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path))
    monkeypatch.setattr(sl, "ACTIVE_CFG", str(tmp_path / "active.json"))
    monkeypatch.setattr(sl, "PENDING_DIR", str(tmp_path / ".pending"))
    monkeypatch.setattr(sl, "SNAP_DIR", str(tmp_path / "snapshots"))
    return tmp_path


def test_une_vieille_liste_nue_devient_des_lignes(sldir):
    json.dump({"id": "fcb-banks", "name": "Repertoire", "presets": ["soad", "", "velvetine"]}, open(sldir / "fcb-banks.json", "w"))
    d = sl.load("fcb-banks")
    assert [sl.pid_of(ln) for ln in d["lines"]] == ["soad", "", "velvetine"]
    assert d["presets"] == ["soad", "", "velvetine"] and d["rev"] == 1
    assert all(ln["id"].startswith("r:fcb-banks:") and ln["rev"] == 1 for ln in d["lines"])


def test_set_presets_garde_les_lignes(sldir):
    d = sl.save({"id": "gig", "name": "Gig", "lines": [
        {"id": "w:1:1", "rev": 3, "preset": "soad", "title": "Aerials", "bpm": 78},
        {"id": "w:1:2", "rev": 1, "preset": "soad", "title": "Toxicity"},
        {"id": "w:1:3", "rev": 1, "preset": None, "title": "Guest"}]})
    sl.set_presets(d, ["soad", "", "velvetine", "soad"])      # réordonne, garde la ligne sans rig, ajoute
    ids = [ln["id"] for ln in d["lines"]]
    assert ids[0] == "w:1:1" and d["lines"][0]["bpm"] == 78            # 1re occurrence suit sa ligne
    assert d["lines"][1]["title"] == "Guest" and d["lines"][1]["preset"] is None
    assert sl.pid_of(d["lines"][2]) == "velvetine" and d["lines"][2]["id"].startswith("r:gig:")
    assert d["lines"][3]["id"] == "w:1:2" and d["rev"] == 2


def test_fusion_par_id_et_rev_le_rack_gagne_a_egalite(sldir):
    sl.save({"id": "s1", "name": "Klub", "rev": 2, "lines": [
        {"id": "w:1:1", "rev": 2, "preset": "soad", "title": "Aerials (rack)", "bpm": 78},
        {"id": "w:1:2", "rev": 1, "preset": "soad", "title": "Toxicity"},
        {"id": "r:s1:x", "rev": 1, "preset": "velvetine", "title": "Change"}]})
    doc = {"id": "s1", "name": "Klub 14/09", "rev": 3, "complete": True, "lines": [
        {"id": "w:1:1", "rev": 2, "preset": "soad", "title": "Aerials (web)", "bpm": 78},   # égalité, différent -> rack
        {"id": "w:1:2", "rev": 2, "preset": "soad", "title": "Toxicity", "bpm": 127},        # supérieur -> web
        {"id": "w:1:9", "rev": 1, "preset": "soad", "title": "Chop Suey"}]}                  # nouveau
    out, rep = sl.merge_push(doc)
    by = {ln["id"]: ln for ln in out["lines"]}
    assert by["w:1:1"]["title"] == "Aerials (rack)" and "w:1:1" in rep["resend"]
    assert by["w:1:2"]["bpm"] == 127 and "w:1:2" in rep["updated"]
    assert "w:1:9" in rep["added"] and rep["removed"] == ["r:s1:x"]     # complete : la locale absente part
    assert out["name"] == "Klub 14/09" and [ln["id"] for ln in out["lines"]] == ["w:1:1", "w:1:2", "w:1:9"]


def test_sans_complete_on_ajoute_jamais_on_ne_supprime(sldir):
    sl.save({"id": "s2", "name": "S", "rev": 5, "lines": [{"id": "r:s2:a", "rev": 1, "preset": "a"}]})
    out, rep = sl.merge_push({"id": "s2", "rev": 1, "lines": [{"id": "w:2:1", "rev": 1, "preset": "b"}]})
    assert rep["removed"] == [] and [sl.pid_of(ln) for ln in out["lines"]] == ["a", "b"]
    assert "*order*" in rep["resend"]            # rev de liste inférieur : l'ordre du rack repart


def test_mode_verrouille_met_en_attente_puis_applique(sldir, monkeypatch):
    sl.save({"id": "fcb-banks", "name": "Repertoire", "lines": [{"id": "r:f:1", "rev": 1, "preset": "a"}]})
    sl.set_active("fcb-banks")
    monkeypatch.setattr(sl, "_locked_now", lambda: True)
    out = sl.receive_push({"id": "fcb-banks", "rev": 9, "complete": True, "lines": [{"id": "w:9:1", "rev": 1, "preset": "b", "title": "B"}]})
    assert out["deferred"] is True
    assert [sl.pid_of(ln) for ln in sl.load("fcb-banks")["lines"]] == ["a"]          # rien sous les pieds
    monkeypatch.setattr(sl, "_locked_now", lambda: False)
    assert sl.apply_pending() == ["fcb-banks"]
    assert [ln.get("title") for ln in sl.load("fcb-banks")["lines"]] == ["B"]
    assert not os.listdir(str(sldir / ".pending"))


def test_fcb_true_est_un_souhait(sldir):
    sl.save({"id": "fcb-banks", "name": "Repertoire", "lines": []}); sl.set_active("fcb-banks")
    sl.receive_push({"id": "web-1", "name": "Klub", "fcb": True, "lines": [{"id": "w:1:1", "rev": 1, "preset": "a"}]})
    assert sl.active_id() == "fcb-banks" and sl.load("web-1").get("fcb_wanted") is True


def test_update_line_bump_rev_et_bpm_null_retire(sldir):
    d = sl.save({"id": "s3", "name": "S", "lines": [{"id": "w:3:1", "rev": 1, "preset": "a", "bpm": 90}]})
    d = sl.update_line("s3", "w:3:1", title="Aerials", bpm=None)
    ln = d["lines"][0]
    assert ln["rev"] == 2 and ln["title"] == "Aerials" and "bpm" not in ln


def test_le_tempo_de_ligne_voyage_dans_la_commande(monkeypatch):
    from bridge import recall
    from bridge.state import state
    sent = {}
    monkeypatch.setattr(recall, "write_command", lambda cmd: sent.update(cmd))
    monkeypatch.setattr(state, "song", {"line": "w:1:1", "preset": "soad", "bpm": 78}, raising=False)
    # on n'appelle pas emit_sandbox_preset (compile) : on vérifie la règle sur song_of_line + la clause
    sg = recall.song_of_line({"id": "w:1:1", "title": "Aerials", "bpm": 78}, "soad")
    assert {k: sg[k] for k in ("line", "preset", "title", "slug", "bpm", "arrangement")} == {"line": "w:1:1", "preset": "soad", "title": "Aerials", "slug": None, "bpm": 78, "arrangement": False}
    assert recall.song_of_line(None, "soad") is None


def test_lot2_arrangement_et_backing_sur_la_ligne(sldir):
    d = sl.save({"id": "s4", "name": "S", "lines": [{"id": "w:4:1", "rev": 1, "preset": "soad", "title": "Chop Suey"}]})
    arr = {"params": {"advance": "bars", "sig": {"num": 4, "den": 4}, "sections": [{"name": "intro", "bars": 8, "scene": "A"}]}}
    d = sl.update_line("s4", "w:4:1", arrangement=arr, backing={"slug": "soad_chop_suey"})
    ln = d["lines"][0]
    assert ln["arrangement"]["type"] == "arrangement" and ln["arrangement"]["id"] == "arr-line"
    assert ln["arrangement"]["params"]["sections"][0]["name"] == "intro" and ln["backing"] == "soad_chop_suey"
    d = sl.update_line("s4", "w:4:1", arrangement="n'importe quoi", backing="")
    assert "arrangement" not in d["lines"][0] and "backing" not in d["lines"][0]


def test_lot2_preset_effectif(sldir, monkeypatch):
    from bridge import recall
    from bridge.state import state
    arr = {"type": "arrangement", "id": "arr-line", "params": {"sections": [{"name": "v", "bars": 4, "scene": "A"}]}}
    sl.save({"id": "fcb-banks", "name": "R", "lines": [{"id": "w:1:1", "rev": 1, "preset": "soad", "arrangement": arr, "backing": "x_y"}]})
    sl.set_active("fcb-banks")
    p = {"id": "soad", "config": {"arr": {"blocks": [{"type": "arrangement", "id": "legacy", "params": {"sections": []}}]}},
         "backing": {"songs": [{"slug": "preset_song"}]}}
    monkeypatch.setattr(state, "song", None, raising=False)
    q = recall.effective_preset(p)
    # hors ligne : pas d'automation, et PAS de backing — elle appartient à la chanson (docs/song-backing.md §1)
    assert q["config"]["arr"]["blocks"] == [] and q["backing"]["songs"] == []
    monkeypatch.setattr(state, "song", {"line": "w:1:1", "setlist": "fcb-banks", "preset": "soad"}, raising=False)
    q = recall.effective_preset(p)
    # 2026-09-16 : le bloc JOUÉ est celui du RIG (son id, sa pédale, sa règle d'avance) nourri des PARTIES
    # de la ligne — `recall.merge_arrangement`. L'id du bloc de la ligne ne sort plus : c'est le pédalier
    # qui porte l'arrangement, et un stomp se lie à l'id du preset.
    blk = q["config"]["arr"]["blocks"][0]
    assert blk["id"] == "legacy" and blk["params"]["sections"] == arr["params"]["sections"]
    assert q["backing"]["songs"][0]["slug"] == "x_y"
    assert p["config"]["arr"]["blocks"][0]["id"] == "legacy"                                  # le preset n'est pas muté


def test_lot2_migration_legacy(sldir, monkeypatch):
    from bridge import setlists as _sl
    sl.save({"id": "s5", "name": "S", "lines": [{"id": "w:5:1", "rev": 1, "preset": "old"}, {"id": "w:5:2", "rev": 1, "preset": "new"}]})
    legacy = {"type": "arrangement", "id": "arr-1", "params": {"sections": [{"name": "a", "bars": 2, "scene": "A"}]}}
    monkeypatch.setattr(_sl, "_legacy_arrangement", lambda pid: legacy if pid == "old" else None)
    assert _sl.migrate_legacy_arrangements() == [("s5", "w:5:1")]
    d = sl.load("s5")
    assert d["lines"][0]["arrangement"]["params"]["sections"][0]["name"] == "a" and d["lines"][0]["rev"] == 2
    assert "arrangement" not in d["lines"][1]
    assert _sl.migrate_legacy_arrangements() == []                                         # idempotent


# ── LOT 3 (docs/setlists.md §9.9) : les BLOCS PAR MORCEAU ──────────────────────────────────────
def test_lot3_blocks_valides_et_vides(sldir):
    sl.save({"id": "s6", "name": "S", "lines": [{"id": "w:6:1", "rev": 1, "preset": "p"}]})
    d = sl.update_line("s6", "w:6:1", blocks={"smp-1": {"params": {"samples": ["a.wav"]}}, "clk": {"bypass": 1, "junk": 3},
                                            "": {"bypass": True}, "x": "pas un dict", "vide": {}})
    b = d["lines"][0]["blocks"]
    assert b == {"smp-1": {"params": {"samples": ["a.wav"]}}, "clk": {"bypass": True}}
    d = sl.update_line("s6", "w:6:1", blocks={})                    # {} = on retire toute surcharge
    assert "blocks" not in d["lines"][0]


def test_lot3_preset_effectif_par_bloc(sldir, monkeypatch):
    from bridge import recall
    from bridge.state import state
    sl.save({"id": "fcb-banks", "name": "R", "lines": [{"id": "w:1:1", "rev": 1, "preset": "soad",
             "blocks": {"smp-1": {"params": {"samples": ["song.wav"]}}, "clk": {"bypass": True, "params": {"beats": 3}},
                        "gone": {"bypass": True}}}]})
    sl.set_active("fcb-banks")
    p = {"id": "soad", "config": {
        "gen": {"blocks": [{"type": "sample", "id": "smp-1", "foot": 8, "params": {"samples": ["rig.wav"], "gain": -6}}]},
        "rec": {"blocks": [{"type": "click", "id": "clk", "params": {"beats": 4, "level": -12}}]}}}
    monkeypatch.setattr(state, "song", None, raising=False)
    q = recall.effective_preset(p)
    assert q["config"]["gen"]["blocks"][0]["params"]["samples"] == ["rig.wav"]          # hors ligne : le rig
    assert recall.song_click() == {}
    monkeypatch.setattr(state, "song", {"line": "w:1:1", "setlist": "fcb-banks", "preset": "soad"}, raising=False)
    q = recall.effective_preset(p)
    g = q["config"]["gen"]["blocks"][0]; c = q["config"]["rec"]["blocks"][0]
    assert g["params"] == {"samples": ["song.wav"], "gain": -6} and g["foot"] == 8      # params FUSIONNÉS, le reste intact
    assert c["bypass"] is True and c["params"] == {"beats": 3, "level": -12}
    assert p["config"]["gen"]["blocks"][0]["params"]["samples"] == ["rig.wav"]          # le preset n'est pas muté
    monkeypatch.setattr(recall, "load_preset", lambda pid: p if pid == "soad" else None)
    assert recall.song_click() == {"beats": 3}                                          # la signature de la ligne


def test_lot3_add_line_puis_plein(sldir):
    sl.save({"id": "s7", "name": "S", "lines": []})
    d = sl.add_line("s7", title="New song", preset="p", bpm=90)
    assert d["line_id"].startswith("r:s7:") and d["lines"][0]["title"] == "New song" and d["lines"][0]["rev"] == 1
    for _ in range(18):
        sl.add_line("s7", title="x")
    r = sl.add_line("s7", title="one too many")
    assert r.get("error") and len(sl.load("s7")["lines"]) == 19
    assert sl.add_line("nope", title="x") is None


def test_remove_line_retire_le_morceau_jamais_le_preset(sldir):
    """« Remove from setlist » (2026-09-14) : la ligne part, les autres gardent leur id et leur
    contenu, le rev de LISTE monte (l'ordre change — c'est lui que golem.fm arbitre), le preset n'est
    pas touché. Ligne ou setlist inconnue : None, rien n'est écrit."""
    sl.save({"id": "s", "name": "S", "lines": [], "rev": 3})
    a = sl.add_line("s", title="A", preset="p1")["line_id"]
    b = sl.add_line("s", title="B", preset="p2")["line_id"]
    c = sl.add_line("s", title="C")["line_id"]
    out = sl.remove_line("s", b)
    assert [ln["id"] for ln in out["lines"]] == [a, c]
    assert out["rev"] == 4 and out["presets"] == ["p1", ""]        # "" = ligne sans rig (dérivé)
    assert [ln["title"] for ln in sl.load("s")["lines"]] == ["A", "C"]
    assert sl.remove_line("s", "nope") is None and sl.remove_line("zz", a) is None
    assert sl.load("s")["rev"] == 4


# ── §9.12 : la CHANSON possède sa fiche, la ligne ne porte que ce soir (FIGÉ 2026-09-18) ───────
def test_les_trois_champs_de_golem_fm_sont_transportes_et_valides(sldir):
    sl.save({"id": "s", "lines": [{"id": "w:1", "rev": 1, "preset": "p"}]})
    out = sl.update_line("s", "w:1", band_song="bs:42", line_overrides=["arrangement", "bpm"], song_setlists=4)
    ln = out["lines"][0]
    assert ln["band_song"] == "bs:42" and ln["line_overrides"] == ["arrangement", "bpm"] and ln["song_setlists"] == 4
    # forme seulement : jamais interprétés, mais jamais gardés cassés non plus
    out = sl.update_line("s", "w:1", line_overrides="pas une liste", song_setlists="beaucoup")
    ln = out["lines"][0]
    assert "line_overrides" not in ln and "song_setlists" not in ln and ln["band_song"] == "bs:42"


def test_le_scope_est_une_consigne_a_part_jamais_un_champ_de_ligne(sldir):
    sl.save({"id": "s", "lines": [{"id": "w:1", "rev": 1, "preset": "p"}]})
    out = sl.update_line("s", "w:1", scope="song", arrangement={"type": "arrangement", "params": {"sections": []}})
    assert out["scopes"] == {"w:1": {"arrangement": "song"}}
    assert "scope" not in out["lines"][0]                       # la ligne ne dit pas où va une retouche
    # un geste qui ne touche AUCUN champ de la fiche ne pose pas de consigne (title, song_slug exclus)
    sl.save({"id": "s2", "lines": [{"id": "w:2", "rev": 1, "preset": "p"}]})
    out = sl.update_line("s2", "w:2", scope="song", title="Toxicity (acoustic)")
    assert not out.get("scopes") and out["lines"][0]["title"] == "Toxicity (acoustic)"
    # une consigne inconnue est ignorée (un rack d'un autre âge, un client bavard)
    out = sl.update_line("s2", "w:2", scope="partout", bpm=120)
    assert not out.get("scopes")


def test_une_consigne_par_CHAMP_survit_a_la_fusion_des_ecritures(sldir):
    """Le miroir fusionne les écritures : hors ligne, corriger l'arrangement (song) puis régler un
    tempo « tonight only » (line) sur la MÊME ligne ne doit pas envoyer l'arrangement en exception du
    soir. Une retouche ultérieure du MÊME champ, elle, remplace bien sa consigne."""
    sl.save({"id": "s", "lines": [{"id": "w:1", "rev": 1, "preset": "p"}]})
    sl.update_line("s", "w:1", scope="song", arrangement={"type": "arrangement", "params": {"sections": []}})
    out = sl.update_line("s", "w:1", scope="line", bpm=128)
    assert out["scopes"] == {"w:1": {"arrangement": "song", "bpm": "line"}}
    out = sl.update_line("s", "w:1", scope="line", arrangement={"type": "arrangement", "params": {"sections": [{"name": "intro", "bars": 4}]}})
    assert out["scopes"] == {"w:1": {"arrangement": "line", "bpm": "line"}}       # le même champ, réécrit


def test_le_defaut_du_scope_se_lit_sur_la_situation_de_jeu_pas_sur_le_verrou(sldir):
    """⚠ `ui.locked` ne commande que la sortie par le logo (docs/modes.md §7 bis) : un mode maison
    verrouillé pour qu'un enfant ne sorte pas du kiosque aurait rangé ses répètes en « tonight only ».
    C'est `take_kind` qui DIT la situation de jeu, et c'est le vocabulaire partagé avec golem.fm."""
    assert sl.default_scope({"id": "gig", "take_kind": "gig"}) == "line"          # un concert : ce soir
    assert sl.default_scope({"id": "kiosque", "ui": {"locked": True}}) == "song"  # verrouillé ≠ sur scène
    for m in ({"id": "studio"}, {"id": "rehearsal", "take_kind": "rehearsal"}, {"id": "pedalboard", "ui": {}},
              {"id": "un-mode-a-venir"}, {}):
        assert sl.default_scope(m) == "song", m                                   # aucune énumération d'ids


def test_une_consigne_ne_voyage_que_du_rack_vers_le_web(sldir):
    sl.save({"id": "s", "rev": 1, "lines": [{"id": "w:1", "rev": 1, "preset": "p"}]})
    out, _rep = sl.merge_push({"id": "s", "rev": 2, "complete": True, "scopes": {"w:1": "song"},
                               "lines": [{"id": "w:1", "rev": 2, "preset": "p", "band_song": "bs:7"}]})
    assert "scopes" not in out and out["lines"][0]["band_song"] == "bs:7"


def test_song_setlists_est_une_info_pas_du_contenu_de_ligne(sldir):
    """golem.fm, 2026-09-18 : le nombre change sans que la ligne change (un morceau ajouté à une 5e
    setlist fait passer de 4 à 5 les QUATRE autres). Le comparer produisait une boucle de `resend`
    sans fin. Il est hors du corps, et la valeur reçue fait foi quel que soit le rev."""
    sl.save({"id": "s", "rev": 1, "lines": [{"id": "w:1", "rev": 3, "preset": "p", "song_setlists": 4}]})
    doc = {"id": "s", "name": "s", "rev": 1, "complete": True,
           "lines": [{"id": "w:1", "rev": 3, "preset": "p", "song_setlists": 5}]}
    out, rep = sl.merge_push(doc)
    assert rep["kept"] == ["w:1"] and rep["resend"] == []          # AUCUN renvoi : le corps est identique
    assert out["lines"][0]["song_setlists"] == 5                    # …et le nombre reçu fait foi
    # même sur une ligne que le RACK gagne (rev égal, contenu différent)
    doc["lines"][0] = {"id": "w:1", "rev": 3, "preset": "autre", "song_setlists": 9}
    out, rep = sl.merge_push(doc)
    assert rep["resend"] == ["w:1"] and out["lines"][0]["preset"] == "p"
    assert out["lines"][0]["song_setlists"] == 9
