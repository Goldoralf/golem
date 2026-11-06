# SPDX-License-Identifier: GPL-3.0-or-later
"""La prise de standard (docs/compo.md §11) : golem.fm arme le rack sur une grille, le Standard la joue sur
l'horloge de l'enregistrement, take.json dit ce qui a été joué — et chaque refus a sa raison."""
import time

import pytest

from bridge import compo, standards, store
from bridge.state import state

# deux mesures, puis une section à deux fins : un tour = 2 + (1 + 1) + (1 + 1) = 6 mesures
GRID = {"key": "C", "beats": 4, "tempo": 120, "feel": "swing", "sections": [
    {"id": "A1", "label": "A", "endings": [],
     "bars": [[{"beat": 1, "len": 4, "sym": "Cm7"}], [{"beat": 1, "len": 2, "sym": "Fm7"}, {"beat": 3, "len": 2, "sym": "Bb7"}]]},
    {"id": "B2", "label": "B", "bars": [[{"beat": 1, "len": 4, "sym": "EbM7"}]],
     "endings": [[[{"beat": 1, "len": 4, "sym": "G7"}]], [[{"beat": 1, "len": 4, "sym": "Cm7"}]]]}]}

IMAP = {"card": "hw:V276",
        "inputs": [{"ch": "1", "role": "guitar", "nth": 1, "person": "alex"},
                   {"ch": "2", "role": "guitar", "nth": 2, "person": "alex"},
                   {"ch": "3", "role": "bass", "nth": 1, "person": "ju"}]}


def _lane(i, role, nth, ch):
    return {"id": f"{role}-{nth}", "role": role, "in_role": role, "in_nth": nth, "in_sel": ch,
            "name": f"{role.title()} {nth}", "chain": {"pre": [], "split": None, "post": []}}


PRESET = {"id": "p", "lanes_v": 2, "lanes": [_lane(0, "guitar", 1, "1"), _lane(2, "bass", 1, "3")]}
TWO_GUITARS = {"id": "p2", "lanes_v": 2, "lanes": [_lane(0, "guitar", 1, "1"), _lane(1, "guitar", 2, "2")]}
TARGET = {"id": "st:7", "mode": "replace", "title": "Blue Bossa", "band": "b_me", "kind": "standard-take",
          "standard": "blue-bossa", "key": "Cm", "bpm": 400, "count_in": 1, "choruses": 2, "role": "guitar",
          "parts": {"keys": True, "bass": True, "drums": True, "guitar": False}, "click": "count-in"}


@pytest.fixture
def rack(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "COMPO_CFG", str(tmp_path / "compo.json"))
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "recorder.json"))
    monkeypatch.setattr(standards, "get_grid", lambda slug: dict(GRID) if slug == "blue-bossa" else None)
    state.compo = {"targets": {}, "last": None}
    state.mode = {"id": "rehearsal", "name": "Rehearsal", "services": {"compo": True}}
    state.perf_countin = None
    monkeypatch.setattr(state, "backing", {}, raising=False)
    monkeypatch.setattr(state, "drums", {}, raising=False)
    compo.RIFF.update(active=None, last=None, refused=None)
    monkeypatch.setattr(compo, "_HOOKS", {})
    monkeypatch.setattr(compo, "_perf_status", lambda: {})
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    from bridge import takes                                     # l'espace PERSONNEL est dans le roster (kind: personal)
    monkeypatch.setattr(takes, "resolve_band", lambda b: {"id": b, "name": "Alex", "source": "cache"} if b == "b_me" else None)
    store.save_recorder_cfg({"mode": "tracks_di", "in1": True, "in2": True, "in3": True, "usb": False})
    yield tmp_path
    compo.RIFF.update(active=None, last=None)


def test_larmement_deroule_un_tour_et_valide_ses_propres_modes(rack):
    assert compo.set_target("alex", TARGET) == (True, "armed")
    t = compo.target_of("alex")
    assert t["kind"] == "standard-take" and t["mode"] == "replace"
    # un tour = les fins DÉROULÉES dedans : 2 + 2 + 2 mesures ; `choruses` -> `passes` comme un riff en boucle
    assert t["take"] == {"bpm": 400.0, "sig": {"num": 4, "den": 4}, "count_in": 1, "bars": 6, "passes": 2,
                         "click": "count-in"}
    assert t["std"] == {"slug": "blue-bossa", "key": "Cm", "role": "guitar",
                        "parts": {"keys": True, "bass": True, "drums": True, "guitar": False}}
    assert t["sent"]["standard"] == "blue-bossa" and t["sent"]["parts"]["drums"] is True   # recopiée telle qu'envoyée
    assert compo.set_target("alex", dict(TARGET, mode="add"))[0]
    # `append` est un mode de riff, pas d'une prise de standard — et inversement
    assert compo.set_target("alex", dict(TARGET, mode="append")) == (False, "unknown mode: append")
    assert compo.set_target("alex", {"id": "rf:1", "mode": "add"}) == (False, "unknown mode: add")
    assert compo.set_target("alex", dict(TARGET, choruses=17))[1].startswith("bad take: count_in 0-4, choruses 0-16")
    assert compo.set_target("alex", dict(TARGET, role="voice"))[1] == "bad take: role is guitar, bass or keys"


def test_un_standard_absent_est_refuse_et_la_page_le_lit(rack):
    assert compo.set_target("alex", dict(TARGET, standard="giant-steps")) == (False, "standard not on this golem")
    assert compo.riff_frame() == {"person": "alex", "state": "refused", "why": "standard not on this golem"}
    assert compo.target_of("alex") is None                       # jamais une prise sur une autre grille


def test_la_lane_est_celle_du_role_et_jamais_choisie_au_hasard(rack):
    compo.set_target("alex", TARGET)
    std = compo.target_of("alex")["std"]
    lane, why = compo.standard_lane(PRESET, "alex", std)
    assert lane["id"] == "guitar-1" and why is None
    assert compo.standard_lane(PRESET, "alex", dict(std, role="bass")) == (None, "lane not in this preset")
    lane, why = compo.standard_lane(TWO_GUITARS, "alex", std)
    assert lane is None and why.startswith("alex has 2 guitar lanes in this preset (Guitar 1, Guitar 2)")
    assert compo.standard_lane(TWO_GUITARS, "alex", dict(std, lane="guitar-2"))[0]["id"] == "guitar-2"
    rep = compo.tap(preset=TWO_GUITARS, person="alex")
    assert rep["refused"].startswith("alex has 2 guitar lanes")


@pytest.mark.parametrize("setup, why", [
    (lambda: setattr(state, "backing", {"playing": True}), "the backing is playing — stop it first"),
    (lambda: setattr(state, "drums", {"d1": {"playing": True}}), "the drum machine is playing — stop it first"),
    (lambda: setattr(state, "mode", {"id": "gig", "name": "Gig", "services": {"compo": True, "standard": False}}),
     "the Standard is off in Gig"),
])
def test_ce_qui_roule_deja_ou_le_mode_refuse_la_prise(rack, setup, why):
    compo.set_target("alex", TARGET)
    setup()
    assert compo.tap(preset=PRESET, person="alex")["refused"] == why


def test_la_prise_part_par_le_standard_sarrete_seule_et_dit_ce_quelle_a_joue(rack):
    started, restored, toggles = [], [], []

    def start(a, alive):
        started.append((a["kind"], [l["id"] for l in a["lanes"]], alive()))
        a["std_played"] = {"slug": "blue-bossa", "etag": "e1", "key": "Cm", "semis": 0, "bpm": 400.0, "beats": 4,
                           "feel": "swing", "choruses": 1, "parts_heard": ["bass", "drums", "keys"],
                           "bars": [["Cm7"], ["Fm7", "Bb7"]]}
        return True, None
    compo.bind(standard_start=start, standard_restore=lambda: restored.append(1),
               armed_start=lambda *a: (_ for _ in ()).throw(AssertionError("pas le click-fichier du riff")))
    compo.set_target("alex", dict(TARGET, count_in=0, choruses=1))
    rep = compo.tap(preset=PRESET, person="alex", toggle=toggles.append)
    assert rep["capture"] == "start-armed" and rep["lanes"] == ["guitar-1"] and toggles == []
    for _ in range(50):
        if started and not compo.RIFF["active"].get("loading"):
            break
        time.sleep(0.02)
    assert started == [("standard-take", ["guitar-1"], True)]
    assert not compo.backing_needed()                            # pas de click-fichier sur la piste Backing
    compo.on_perf_start()
    time.sleep(3.9)                                              # un tour de 6 mesures à 400 = 3,6 s, plus un temps
    assert toggles == [False]
    riff = compo.claim_riff()
    assert restored == [1]                                       # la grille, le tempo et le click rendus
    man = {"files": ["DI-Sandbox-Input-1.wav", "Input-1merge.wav", "Input-3merge.wav"],
           "standard": {"id": "blue-bossa", "title": "Blue Bossa", "played": True, "bars": 6}}
    compo.stamp_manifest(man, riff)
    assert man["kind"] == "standard-take" and man["tempo_source"] == "standard"
    assert man["target"]["id"] == "st:7" and man["target"]["lane"] == "guitar-1" and man["target"]["role"] == "guitar"
    assert man["target"]["parts"] == TARGET["parts"]             # la cible entière, plus la lane retenue
    assert man["lanes"] == [{"id": "guitar-1", "name": "Guitar 1", "role": "guitar", "input": "1",
                             "files": {"di": "DI-Sandbox-Input-1.wav", "wet": "Input-1merge.wav"}}]   # pas la basse de ju
    s = man["standard"]
    assert s["bars"] == [["Cm7"], ["Fm7", "Bb7"]] and s["played"] is True and s["id"] == "blue-bossa"
    assert (s["etag"], s["beats"], s["bpm"], s["feel"]) == ("e1", 4, 400.0, "swing")
    assert man["downbeat_s"] == 0.0 and man["bars"] == 6 and man["passes"] == 1 and man["bpm"] == 400.0


def test_le_compte_dune_prise_de_standard_ne_lit_pas_la_backing(rack, monkeypatch):
    compo.set_target("alex", TARGET)
    take = compo.target_of("alex")["take"]
    compo.RIFF["active"] = {"person": "alex", "rolling": True, "take": take, "kind": "standard-take",
                            "t_rolling": time.time() - (0.6 + 0.6 * 6 + 0.01)}   # décompte + un tour à 400
    monkeypatch.setattr(state, "backing", {"pos": 99.0}, raising=False)        # une position périmée ne compte pas
    f = compo.riff_frame()
    assert (f["state"], f["bar"], f["pass"], f["passes"]) == ("rec", 7, 2, 2)


def test_un_depart_annule_rend_la_grille_armee(rack):
    restored = []

    def start(a, alive):
        compo.RIFF["active"] = None                              # Stop pendant le chargement
        return False, "cancelled"
    compo.bind(standard_start=start, standard_restore=lambda: restored.append(1))
    compo.set_target("alex", TARGET)
    compo.tap(preset=PRESET, person="alex")
    for _ in range(50):
        if restored:
            break
        time.sleep(0.02)
    assert restored == [1]                                       # sinon elle partirait au prochain play du transport


def test_le_depart_rend_la_grille_arme_le_standard_et_lance_la_prise(rack, monkeypatch, tmp_path):
    from bridge import app as A, golemfm
    cmds, holds, perf = [], [], []
    seqs = []
    real_write = standards.write_seq
    monkeypatch.setattr(standards, "write_seq", lambda r, path=None: (seqs.append(r), real_write(r, str(tmp_path / "s.seq")))[1])
    monkeypatch.setattr(A, "write_command", cmds.append)
    monkeypatch.setattr(A, "load_preset", lambda pid: None)
    monkeypatch.setattr(A, "_read_json", lambda p, d=None: {"armed": True} if p.endswith(".standard.json") else d)
    monkeypatch.setattr(A, "_arr_click_hold", holds.append)
    monkeypatch.setattr(A, "_foot_perf_toggle", lambda **kw: perf.append(kw) or True)
    monkeypatch.setattr(A, "_click_cfg", lambda: {"div": 1, "level": -12})
    monkeypatch.setattr(golemfm, "_std_etags", lambda: {"blue-bossa": "etag-9"})
    monkeypatch.setattr(state, "click", {"on": False}, raising=False)
    monkeypatch.setattr(state, "preset_id", None, raising=False)
    compo.set_target("alex", TARGET)
    a = {"target": compo.target_of("alex"), "take": compo.target_of("alex")["take"]}
    assert A._std_take_start(a, lambda: True) == (True, None)
    cmd = cmds[-1]
    assert cmd["op"] == "play" and cmd["arm"] is True and cmd["bpm"] == 400.0 and cmd["loop"] is False
    assert (cmd["keys"], cmd["bass"], cmd["drums"], cmd["guitar"]) == (True, True, True, False)
    assert holds == [True] and perf == [{"want": True, "countin": False}]
    # click « count-in » : les ticks de la grille s'arrêtent au premier temps
    r = seqs[-1]
    ticks = [e for e in r["events"] if e[3] == standards.LANE_CLICK and e[2] > 0]
    assert ticks and max(e[0] for e in ticks) < r["count_in_ppq"] == 4 * standards.PPQ
    p = a["std_played"]
    assert p["bars"] == [["Cm7"], ["Fm7", "Bb7"], ["EbM7"], ["G7"], ["EbM7"], ["Cm7"]]   # UN tour, transposé (Cm -> C : 0)
    assert (p["etag"], p["key"], p["choruses"], p["beats"]) == ("etag-9", "Cm", 2, 4)
    assert p["parts_heard"] == ["bass", "drums", "keys"]
    A._std_take_restore()
    assert cmds[-1] == {"action": "standard", "op": "stop"} and holds == [True, False]   # le click rend la main
