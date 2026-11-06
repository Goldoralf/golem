# SPDX-License-Identifier: GPL-3.0-or-later
"""Standards et boîte à rythmes sont des services de mode ; Arrangement a une rangée (2026-09-08)."""
from bridge import modes


def test_les_deux_nouveaux_services_existent_et_drums_reste_lentree():
    assert {"standard", "drummachine", "arrangement", "drums", "compo"} <= set(modes.SERVICES)


def test_compo_on_en_repete_off_sur_scene():
    """docs/compo.md §7 : on en Rehearsal/Studio/Accompaniment, off en Gig/Pedalboard."""
    for mid in ("rehearsal", "studio", "accompaniment"):
        assert modes.allows("compo", modes.factory_def(mid)) is True, mid
    for mid in ("gig", "pedalboard"):
        assert modes.allows("compo", modes.factory_def(mid)) is False, mid


def test_defauts_dusine_2026_09_08():
    """Les défauts d'usine SONT les réglages du mainteneur (sauf band et card, locaux par nature) :
    Pedalboard coupe Standards et Drum machine ; Gig, lui, monte tout — le set du moment décide
    (décision 2026-09-08). Show a fusionné dans Gig le 2026-09-18 (§7 bis)."""
    fd = modes.factory_def("pedalboard")
    assert modes.allows("standard", fd) is False and modes.allows("drummachine", fd) is False
    for mid in ("studio", "accompaniment", "rehearsal", "gig"):
        fd = modes.factory_def(mid)
        assert modes.allows("standard", fd) and modes.allows("drummachine", fd), mid
    for mid in ("pedalboard", "studio", "accompaniment", "rehearsal", "gig"):
        fd = modes.factory_def(mid)
        assert "band" not in fd and "card" not in fd, f"{mid} : un identifiant local n'est pas une graine"


def test_un_mode_dun_autre_age_autorise_ce_quil_ne_connait_pas():
    assert modes.allows("drummachine", {"id": "x", "services": {"looper": False}}) is True


def test_le_boost_cpu_suit_la_scene():
    assert modes.perf_boost(modes.factory_def("gig")) is True
    for mid in ("pedalboard", "studio", "accompaniment", "rehearsal"):
        assert modes.perf_boost(modes.factory_def(mid)) is False, mid
    assert modes.perf_boost({"id": "vieux-mode"}) is False


# ── le magnétophone : UNE config globale, éditable depuis deux endroits (2026-09-08) ────────
def test_recorder_config_globale_ecrite_et_relue(tmp_path, monkeypatch):
    from bridge import store
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "recorder.json"))
    cfg = store.save_recorder_cfg({"in2": 0, "mode": "tracks_di", "transcribe": "auto", "junk": 1, "mix": None})
    assert cfg["in2"] is False and cfg["mode"] == "tracks_di" and cfg["transcribe"] == "auto" and "junk" not in cfg
    back = store.load_recorder_cfg()
    assert back["transcribe"] == "auto" and back["mode"] == "tracks_di"      # transcribe SURVIT à la relecture (bug corrigé)
    assert store.save_recorder_cfg({"mode": "n'importe quoi"})["mode"] == "tracks_di"
    assert store.rec_sources({})["mode"] == "tracks_di"
    assert not hasattr(modes, "rec_of")                                        # pas de REC par mode


def test_update_mode_garde_la_carte_et_l_espace(tmp_path, monkeypatch):
    """RÉGRESSION du 2026-09-08 (commit a44f2a6) : en retirant le REC par mode, le bloc `card` / `band`
    de update_mode était parti avec — « je ne peux pas sélectionner le XR18 » (2026-09-09) :
    la route répondait 200 et n'écrivait rien. Le contrat est ici, pour de bon."""
    import asyncio
    from bridge import routes_modes
    monkeypatch.setattr(modes, "LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr(routes_modes, "_guard_locked_active", lambda mid: None)
    monkeypatch.setattr(routes_modes, "_refresh_if_current", lambda mid: None)
    r = asyncio.run(routes_modes.update_mode({"id": "gig", "card": "hw:XR18", "band": "b_x"}))
    assert r["mode"]["card"] == "hw:XR18" and r["mode"]["band"] == "b_x"
    assert modes.factory_def("gig").get("card") is None                   # jamais une graine d'usine
    r = asyncio.run(routes_modes.update_mode({"id": "gig", "card": "", "band": ""}))
    assert "card" not in r["mode"] and "band" not in r["mode"]              # "" = « n'importe quelle carte »


def test_veto_par_entree_numerotee(tmp_path, monkeypatch):
    """2026-09-09 : la rangée Inputs d'un mode liste les entrées numérotées de SA carte, chacune on/off."""
    import asyncio
    from bridge import routes_modes, recall, store, inputmap
    from bridge.state import state
    monkeypatch.setattr(modes, "LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr(routes_modes, "_guard_locked_active", lambda mid: None)
    monkeypatch.setattr(routes_modes, "_refresh_if_current", lambda mid: None)
    r = asyncio.run(routes_modes.update_mode({"id": "gig", "inputs_off": ["voice#2", "nope", "guitar#3"]}))
    assert r["mode"]["inputs_off"] == ["guitar#3", "voice#2"]
    m = r["mode"]
    assert modes.input_allowed("voice", 1, m) and not modes.input_allowed("voice", 2, m) and modes.input_allowed("guitar", 2, m)
    assert not modes.input_allowed("voice", 1, {"id": "x", "services": {"voice": False}})      # le veto par instrument reste
    # sur le rig : Voice 2 (IN 4 du XR18) est coupée, Voice 1 (IN 3) reste
    card = inputmap.with_nth([{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "guitar"}, {"ch": "3", "role": "voice"}, {"ch": "4", "role": "voice"}])
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": card})
    monkeypatch.setattr(state, "inputmap", {"inputs": card}, raising=False)
    monkeypatch.setattr(state, "mode", m, raising=False)
    p = {"id": "p", "lanes_v": 2, "lanes": [
        {"id": "guitar", "role": "guitar", "in_sel": "1", "chain": {"pre": [], "split": None, "post": []}},
        {"id": "voice", "role": "voice", "in_role": "voice", "in_nth": 1, "chain": {"pre": [], "split": None, "post": []}},
        {"id": "ln-bv", "role": "voice", "in_sel": "4", "chain": {"pre": [], "split": None, "post": []}}], "scenes": [{"id": "A"}]}
    assert recall.input_veto(p) == {"ln-bv"}


def test_une_carte_declaree_fusionne_dans_la_carte_sondee(tmp_path, monkeypatch):
    """« XR18 » déclaré à la main, branché sous son nom ALSA « X18XR18 » : une seule carte, le patch suit."""
    import json, os
    from bridge import cards, inputmap
    monkeypatch.setattr(cards, "CARDS_DIR", str(tmp_path / "cards")); monkeypatch.setattr(cards, "_path", lambda cid: str(tmp_path / "cards" / (cid + ".json")))
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path / "maps")); monkeypatch.setattr(inputmap, "_card_device", lambda: "hw:V276")
    monkeypatch.setattr(modes, "LOCAL_DIR", str(tmp_path / "modes")); os.makedirs(tmp_path / "modes")
    json.dump({"id": "gig", "card": "hw:XR18"}, open(tmp_path / "modes" / "gig.json", "w"))
    monkeypatch.setattr(cards, "probe", lambda cid: None)
    cards.declare("XR18", "Behringer XR18", 18, 18)
    inputmap.set_role("input", "3", "voice", "hw:XR18")                    # le patch préparé à la maison
    monkeypatch.setattr(cards, "probe", lambda cid: {"id": cid, "usb": "1397:00d0", "name": "Behringer X18/XR18", "inputs": 18, "outputs": 18, "midi": {"in": False, "out": False}, "seen": "2026-09-20", "probed": True} if cid == "X18XR18" else None)
    d = cards.remember("X18XR18")
    assert d["merged_from"] == "XR18" and d["alias"] == "Behringer XR18" and cards.known("XR18") is None
    assert next(e for e in inputmap.current("hw:X18XR18")["inputs"] if e["ch"] == "3")["role"] == "voice"   # le patch a suivi
    assert json.load(open(tmp_path / "modes" / "gig.json"))["card"] == "hw:X18XR18"                          # le mode aussi


def test_drums_est_une_lane_coupee_en_pedalboard_seulement():
    """docs/drums-kit.md lot 0 : Pedalboard = guitare seule (comme voice/keys/pads) ; partout ailleurs la
    batterie joue — `allows` rend True pour un service que le mode ne déclare pas."""
    assert modes.allows("drums", modes.factory_def("pedalboard")) is False
    for mid in ("studio", "rehearsal", "gig", "accompaniment"):
        assert modes.allows("drums", modes.factory_def(mid)) is True, mid
    assert modes.input_allowed("drums", 1, {"id": "x", "inputs_off": ["drums#1"]}) is False


# ── Show FUSIONNE dans Gig (docs/modes.md §7 bis, 2026-09-18) ────────────────────────────
def test_gig_recupere_ce_que_show_avait_en_donnees():
    """La scène automatise (le mode INTERDISAIT l'arrangement, c'était le vrai défaut) et sa prise
    couvre le set — deux CHAMPS, pas un `if mode ==`."""
    gig = modes.factory_def("gig")
    assert modes.allows("arrangement", gig) is True
    assert modes.rec_scope(gig) == "set" and modes.take_kind(gig) == "gig"
    assert (gig.get("ui") or {}).get("locked") is True          # le verrou reste : il ne gèle rien (§7 bis.1)
    assert modes.factory_def("show") is None                     # la carte d'usine n'existe plus
    for mid in ("pedalboard", "studio", "accompaniment", "rehearsal"):
        assert modes.rec_scope(modes.factory_def(mid)) == "song", mid
    assert modes.rec_scope({"id": "x"}) == "song"                 # muet = le moins surprenant
    assert modes.rec_scope({"id": "x", "rec_scope": "venu-d-ailleurs"}) == "song"


def test_la_fusion_archive_la_carte_locale_et_remet_le_rack_sur_gig(tmp_path, monkeypatch):
    """§7 bis.4 CORRIGÉ le 2026-09-18 : `config/modes.local/` porte un fichier par mode d'usine (band
    et card ne vivent QUE là), donc « laisser la surcharge locale » aurait gardé Show vivant sur le
    rack même qui demandait la fusion. Le fichier est ARCHIVÉ (jamais relu), son contenu journalisé,
    et un rack persisté sur `show` revient sur `gig` — le repli générique l'aurait sorti de scène."""
    import json, os
    loc = tmp_path / "local"; loc.mkdir()
    fac = tmp_path / "factory"; fac.mkdir()
    st = tmp_path / ".mode.json"
    monkeypatch.setattr(modes, "STATE_FILE", str(st))
    monkeypatch.setattr(modes, "LOCAL_DIR", str(loc))
    monkeypatch.setattr(modes, "MODES_DIR", str(fac))
    (fac / "gig.json").write_text(json.dumps({"id": "gig", "name": "Gig"}))
    (loc / "show.json").write_text(json.dumps({"id": "show", "name": "Show", "band": "b_x", "card": "hw:XR18"}))
    st.write_text(json.dumps({"id": "show"}))
    r = modes.migrate_show_to_gig()
    assert r == {"archived": True, "band": "b_x", "card": "hw:XR18", "switched": True}
    assert not (loc / "show.json").exists() and (loc / "show.json.merged").exists()   # archivé, pas perdu
    assert json.load(open(st))["id"] == "gig"
    assert "show" not in {m["id"] for m in modes.list_modes()}                         # ne ressuscite pas
    assert modes.migrate_show_to_gig() is None                                         # idempotent


def test_la_fusion_ne_touche_pas_un_mode_cree_par_lutilisateur(tmp_path, monkeypatch):
    import json
    loc = tmp_path / "local"; loc.mkdir(); fac = tmp_path / "factory"; fac.mkdir()
    st = tmp_path / ".mode.json"
    monkeypatch.setattr(modes, "STATE_FILE", str(st)); monkeypatch.setattr(modes, "LOCAL_DIR", str(loc))
    monkeypatch.setattr(modes, "MODES_DIR", str(fac))
    (fac / "gig.json").write_text(json.dumps({"id": "gig", "name": "Gig"}))
    (loc / "mon-show.json").write_text(json.dumps({"id": "mon-show", "name": "Mon Show", "ui": {"live": "timeline"}}))
    st.write_text(json.dumps({"id": "mon-show"}))
    assert modes.migrate_show_to_gig() is None
    assert (loc / "mon-show.json").exists() and json.load(open(st))["id"] == "mon-show"
