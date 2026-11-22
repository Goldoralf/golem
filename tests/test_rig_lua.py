# SPDX-License-Identifier: GPL-3.0-or-later
"""Le MOTEUR (reaper/Scripts/golem_rig.lua), joué tel quel sous lupa sur un REAPER factice (tests/fakereaper.lua) —
docs/quality-automation.md, lot 4. Ce que ces tests prouvent : la matérialisation d'un plan compilé par le bridge
(pistes, FX résolus par le catalogue, sends, armement, carte vivante), la bascule de scène SANS rebuild, le stomp,
et les pièges de docs/pitfalls/reaper.md que le moteur doit déjouer. Ce qu'ils ne prouvent pas : le son, ni ce que
le vrai REAPER fait d'un chunk ou d'un plugin qui charge — ça, c'est tools/check-rig-materialize.py sur un vrai REAPER."""
import json
import os
from pathlib import Path
import re
import shutil

import pytest

lupa = pytest.importorskip("lupa")

ROOT = Path(__file__).resolve().parents[1]
FAKE = (ROOT / "tests" / "fakereaper.lua").read_text(encoding="utf-8")
RIG = (ROOT / "reaper" / "Scripts" / "golem_rig.lua").read_text(encoding="utf-8")

# le patch de banc de tools/check-rig-materialize.py : effets intégrés et JSFX seulement, deux branches, trois scènes
LANE = "guitar-ci"
STATES = [("A", "Both", {"chorus": False}, {}),
          ("B", "Branch A only", {"chorus": True, "dly": True}, {"lane-b": {"mute": True}}),
          ("C", "Branch B only", {"phaser": True}, {"lane-a": {"mute": True}})]
PATCH = {"id": "ci-engine", "name": "CI engine check", "role": "guitar", "kind": "patch", "patch_v": 2, "lanes_v": 2, "bpm": 120,
         "lanes": [{"id": LANE, "role": "guitar", "name": "CI engine check", "midi": False, "stereo": False,
                    "chain": {"pre": [{"id": "gate", "type": "gate"}],
                              "split": {"mode": "merge", "gain": -3, "branches": [
                                  {"id": "lane-a", "blocks": [{"id": "boost", "type": "clean-boost"}, {"id": "eq", "type": "eq"}]},
                                  {"id": "lane-b", "blocks": [{"id": "phaser", "type": "phaser-js", "foot": 6}, {"id": "comp", "type": "comp"}]}]},
                              "post": [{"id": "chorus", "type": "chorus", "foot": 7}, {"id": "dly", "type": "delay", "foot": 8},
                                       {"id": "kill", "type": "killswitch", "foot": 9}]},
                    "states": [{"id": f"st-{LANE}-{s}", "name": n, "blocks": b, "params": {}, "branches": br} for s, n, b, br in STATES]}],
         "scenes": [{"id": s, "name": n, "blocks": b, "branches": br, "lanes": {LANE: {"state": f"st-{LANE}-{s}"}}} for s, n, b, br in STATES],
         "config": {"gen": {"out": "1-2", "blocks": []}}}
BLOCK_IDS = {"gate", "boost", "eq", "phaser", "comp", "chorus", "dly", "kill"}


def _installed():
    """Ce qui « existe » sur la machine factice : tout plugin du catalogue qui n'est pas un VST/LV2/CLAP tiers
    (intégrés REAPER, JSFX du stock et de golem), plus les intégrés usuels."""
    cat = json.loads((ROOT / "library/catalog/effects.json").read_text(encoding="utf-8"))
    names = {"ReaGate", "ReaComp", "ReaEQ", "ReaDelay", "ReaFir", "ReaVerbate", "ReaPitch", "ReaTune", "ReaLimit",
             "ReaSamplOmatic5000", "Volume Adjustment", "ReaPlugs Volume"}
    for e in cat["effects"]:
        p = e.get("plugin")
        if isinstance(p, str) and p and not re.match(r"^(VST3?i?|LV2i?|CLAPi?|AUi?): ", p):
            names.add(p)
    for f in (ROOT / "reaper/Effects").glob("golem_*.jsfx"):        # les JSFX de golem (link-reaper.sh les pose)
        names.add(f.stem)
    return sorted(names)


class Lab:
    """Un dépôt jetable (scripts, catalogue, plan compilé par le VRAI compilateur) et un Lua avec le REAPER factice."""

    def __init__(self, tmp, os_name="Other"):
        self.root, self.res, self.rt = tmp / "root", tmp / "res", tmp / "rt"
        for d in (self.root / "reaper/Scripts", self.root / "reaper/FXChains", self.root / "presets", self.root / "library/catalog", self.res, self.rt):
            d.mkdir(parents=True, exist_ok=True)
        for f in ("golem_rig.lua", "golem_paths.lua", "golem_project.lua"):
            shutil.copy2(ROOT / "reaper/Scripts" / f, self.root / "reaper/Scripts" / f)
        for f in ("effects.json", "effects-windows.json", "effects-macos.json"):
            shutil.copy2(ROOT / "library/catalog" / f, self.root / "library/catalog" / f)
        (self.res / "golem-root.txt").write_text(str(self.root), encoding="utf-8")
        (self.res / "golem-runtime.txt").write_text(str(self.rt), encoding="utf-8")
        self.L = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.L.globals()
        g.FAKE_OS, g.FAKE_RESOURCE = os_name, str(self.res).replace("\\", "/")
        g.FAKE_INSTALLED = self.L.table_from(_installed())
        g.py_mkdir = lambda p: os.makedirs(p, exist_ok=True)
        self.L.execute(FAKE)
        self.F = g.FAKE

    def compile(self, patch, scene="A"):
        """Le chemin du bridge (recall.emit_sandbox_preset) : volume système, bake des scènes, compile -> .rig.json."""
        import copy
        from bridge import compile_rig, scene_bake, store
        work = copy.deepcopy(patch)
        store.ensure_volume(work)
        baked = scene_bake.to_paths_preset(work, scene, union=True)
        out_dir = compile_rig.OUT_DIR
        compile_rig.OUT_DIR = str(self.root / "reaper/FXChains")
        try:
            return compile_rig.compile_preset(baked)
        finally:
            compile_rig.OUT_DIR = out_dir

    def run(self, **cmd):
        """Une commande comme golem_watch la relaie, puis le script entier (fraîchement chargé, comme un dofile)."""
        (self.root / "presets/.command.json").write_text(json.dumps(cmd), encoding="utf-8")
        for k in list(self.F.calls):
            self.F.calls[k] = 0
        self.L.execute(RIG)
        return self

    # ── lectures ──
    def tracks(self):
        return [dict(name=t.name, fx=[dict(name=f.name, enabled=f.enabled, renamed=f.renamed) for f in t.fx.values()],
                     sends=[dict(s) for s in t.sends.values()], hw=t.hw, info=dict(t.info), ext=dict(t.ext))
                for t in self.F.snapshot().values()]

    def track(self, name):
        return next((t for t in self.tracks() if t["name"] == name), None)

    def livemap(self):
        return json.loads((self.root / "presets/.livemap.json").read_text(encoding="utf-8"))

    def log(self):
        p = self.root / "presets/.golem-rig.log"
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    def calls(self, name):
        return int(self.F.calls[name] or 0)


@pytest.fixture(params=["Other", "Win64", "macOS-arm64"], ids=["linux", "windows", "macos"])
def lab(tmp_path, request):
    """Le même moteur sous les trois systèmes : « Other » = Linux (catalogue nu), « Win64 » = effects-windows.json,
    « macOS-arm64 » = effects-macos.json (ce que REAPER 7 rend sur un Mac Apple silicon — premier Mac réel, 2026-11-04)."""
    lab = Lab(tmp_path, os_name=request.param)
    lab.compile(PATCH)
    return lab


# ── matérialisation ───────────────────────────────────────────────────────────────────────────────────
def test_le_rappel_fait_du_projet_celui_du_golem(lab):
    """golem_project.lua (2026-11-08) : les pistes de service ne s'installent que dans le projet du golem ; un projet
    sans chemin (premier démarrage, REAPER lancé avec -new) le devient au rappel. Une bascule de scène ne marque rien."""
    def owner():
        return lab.L.eval('select(2, reaper.GetProjExtState(0, "golem", "owner"))')
    lab.run(action="scene_apply", preset="ci-engine", scene="A")
    assert owner() == ""
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    assert owner() == "1", lab.log()


def test_un_projet_range_ailleurs_ne_devient_pas_celui_du_golem(lab, tmp_path):
    """Un rappel qui arrive pendant que le musicien est sur SON projet y monte le rig (comme avant), mais ne le
    marque pas : les pistes de service ne l'y suivent pas pour toujours."""
    lab.F.project_path = str(tmp_path / "Music" / "song.rpp")
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    assert lab.L.eval('select(2, reaper.GetProjExtState(0, "golem", "owner"))') == ""


def test_le_rappel_pose_toutes_les_pistes_et_tous_les_blocs(lab):
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    tracks = lab.tracks()
    names = [t["name"] for t in tracks]
    assert tracks, lab.log()
    live = lab.livemap()
    assert live["preset"] == "ci-engine", lab.log()
    assert BLOCK_IDS <= set(live["blocks"]), (sorted(live["blocks"]), lab.log())
    # chaque bloc a été résolu en un plugin que le catalogue nomme, et il est posé sur une piste du rig
    posed = {f["name"] for t in tracks for f in t["fx"]}
    assert "ReaGate" in posed and "ReaComp" in posed and "ReaEQ" in posed and "ReaDelay" in posed, (posed, names)
    assert any("phaser" in n.lower() for n in posed) and any("chorus" in n.lower() for n in posed), posed
    assert any("killswitch" in n.lower() for n in posed), posed


def test_la_racine_de_la_lane_est_armee_en_monitoring(lab):
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    live = lab.livemap()
    roots = {b["track"] for b in live["blocks"].values()}
    armed = [t for t in lab.tracks() if t["info"].get("I_RECARM") == 1]
    assert armed, ("aucune piste armée : l'entrée guitare n'entrerait jamais", [t["name"] for t in lab.tracks()])
    assert all(t["info"].get("I_RECMON") == 1 for t in armed), [(t["name"], t["info"]) for t in armed]
    assert roots, live


def test_un_send_ne_transporte_jamais_le_midi_par_defaut(lab):
    """docs/pitfalls/reaper.md « A send carries MIDI by default » : I_MIDIFLAGS = 31 sur chaque send interne."""
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    sends = [(t["name"], s) for t in lab.tracks() for s in t["sends"]]
    assert sends, "le split en deux branches doit créer des sends"
    bad = [(n, s) for n, s in sends if s["midiflags"] != 31]
    assert not bad, bad


def test_la_memoire_p_ext_survit_au_rappel(lab):
    """docs/pitfalls/reaper.md « SetTrackStateChunk also erases P_EXT » : la signature FX est relue après le chunk."""
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    with_fx = [t for t in lab.tracks() if t["fx"]]
    assert with_fx
    without_sig = [t["name"] for t in with_fx if not any(v for v in t["ext"].values())]
    assert not without_sig, (without_sig, "une piste à FX sans mémoire P_EXT sera reconstruite à chaque rappel")


# ── scène et stomp : sans rebuild ──────────────────────────────────────────────────────────────────────
def test_la_scene_bascule_les_blocs_sans_reconstruire(lab):
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    live = lab.livemap()
    tracks_before = [t["name"] for t in lab.tracks()]

    def enabled(bid):
        b = live["blocks"][bid]
        t = lab.tracks()[b["track"] - 1] if b["track"] - 1 < len(lab.tracks()) else None
        return t["fx"][b["fx"]]["enabled"] if t else None
    assert enabled("chorus") is False and enabled("dly") is True       # scène A : chorus coupé
    lab.compile(PATCH, scene="B")
    lab.run(action="scene_apply", preset="ci-engine", scene="B")
    assert lab.calls("TrackFX_AddByName") == 0 and lab.calls("TrackFX_Delete") == 0 and lab.calls("DeleteTrack") == 0, lab.log()
    assert [t["name"] for t in lab.tracks()] == tracks_before
    assert enabled("chorus") is True and enabled("dly") is True, lab.log()


def test_le_stomp_ne_touche_qu_un_bloc(lab):
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    live = lab.livemap()
    b = live["blocks"]["kill"]
    before = lab.tracks()[b["track"] - 1]["fx"][b["fx"]]["enabled"]
    lab.run(action="stomp", preset="ci-engine", ids=["kill"], on=not before)
    after = lab.tracks()[b["track"] - 1]["fx"][b["fx"]]["enabled"]
    assert after is (not before), lab.log()
    assert lab.calls("TrackFX_AddByName") == 0 and lab.calls("DeleteTrack") == 0


def test_la_scene_mute_la_branche_que_la_scene_coupe(lab):
    lab.run(action="rig_recall", preset="ci-engine", scene="A")

    def muted(suffix):
        t = next(t for t in lab.tracks() if t["name"].endswith(suffix))
        return t["info"].get("B_MUTE") == 1
    assert not muted("/lane-a") and not muted("/lane-b")
    lab.compile(PATCH, scene="B")
    lab.run(action="scene_apply", preset="ci-engine", scene="B")
    assert muted("/lane-b") and not muted("/lane-a"), lab.log()
    lab.compile(PATCH, scene="C")
    lab.run(action="scene_apply", preset="ci-engine", scene="C")
    assert muted("/lane-a") and not muted("/lane-b"), lab.log()


def test_une_scene_sur_un_projet_vide_retombe_sur_un_rebuild(lab):
    """Le bridge peut croire le rig vivant alors que REAPER a redémarré : scene_apply doit alors REBÂTIR, pas
    basculer dans le vide (docs/live-engine.md ; vécu le 2026-07-10 après un segfault)."""
    lab.run(action="scene_apply", preset="ci-engine", scene="A")
    assert lab.tracks(), lab.log()
    assert "rebuild" in lab.log().lower(), lab.log()
    assert BLOCK_IDS <= set(lab.livemap()["blocks"])


def test_un_rappel_identique_ne_reconstruit_rien(lab):
    """La signature FX en P_EXT : une piste dont la chaîne n'a pas changé n'est ni vidée ni reposée — c'est ce qui
    évite « delete piste pendant que son IR charge » (crash mediaafx, fix de fond 2026-07-10)."""
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    names = [t["name"] for t in lab.tracks()]
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    assert [t["name"] for t in lab.tracks()] == names
    assert lab.calls("TrackFX_Delete") == 0 and lab.calls("DeleteTrack") == 0, lab.log()
    assert lab.calls("TrackFX_AddByName") == 0, ("le second rappel a reposé des FX", lab.log())


def test_un_plugin_absent_est_dit_et_le_reste_de_la_chaine_tient(tmp_path):
    """Un bloc dont le plugin manque n'emporte pas sa lane : les autres blocs sont posés, et .rig-plugins.json
    nomme le type qui a échoué (ce que lit blockstatus et la quarantaine)."""
    import copy
    lab = Lab(tmp_path, os_name="Win64")                      # Dragonfly est un VST3 sous Windows : pas dans l'inventaire factice
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["post"].append({"id": "verb", "type": "reverb-room", "foot": 10})
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    live = lab.livemap()
    assert BLOCK_IDS <= set(live["blocks"]), lab.log()
    assert "verb" not in live["blocks"]
    seen = json.loads((lab.root / "presets/.rig-plugins.json").read_text(encoding="utf-8"))["types"]
    assert seen["reverb-room"]["ok"] is False, seen
    assert seen["delay"]["ok"] is True and seen["gate"]["ok"] is True


# ── mixer ─────────────────────────────────────────────────────────────────────────────────────────────
def test_le_mixer_regle_les_pistes_du_standard(lab):
    """2026-10-20 : le Standard a ses propres pistes (golem_chordseq.lua) ; le mixer de /live a une tranche par partie
    (`std-keys`…) et mixer_apply pose le trim sur le send matériel de la piste « Standard Keys »."""
    lab.L.execute('''
      local idx = reaper.CountTracks(0)
      reaper.InsertTrackAtIndex(idx, false)
      local tr = reaper.GetTrack(0, idx)
      reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "Standard Keys", true)
      reaper.CreateTrackSend(tr, nil)
    ''')
    lab.run(action="mixer_apply", levels={"std-keys": {"db": -6.0, "mute": False}, "std-bass": {"db": -12.0}})
    vol = lab.L.eval('(function() for _, t in ipairs(FAKE.tracks) do if t.name == "Standard Keys" then return t.hw[1].D_VOL end end end)()')
    assert vol is not None and abs(vol - 10 ** (-6 / 20)) < 1e-6, (vol, lab.log())
    assert "std-bass sans piste" in lab.log()          # une partie que ce standard ne joue pas : dite, pas une erreur


# ── bloc VST Host (Linux depuis le 2026-11-09, docs/platforms.md §6.1) ────────────────────────────────────────────
def test_le_bloc_vst_host_se_pose_sous_linux_et_ses_knobs_vont_a_la_livemap(tmp_path, monkeypatch):
    """Lot 1 : plus de refus par plateforme dans le moteur. Lot 2 : les potards choisis (block.knobs) sont publiés
    dans la livemap en valeur normalisée — la pédale EXP les pilote ; un index hors du plugin est ignoré."""
    import copy
    import sys
    plugin = "CLAP: Fake Synth (Vendor)"
    monkeypatch.setattr(sys.modules[__name__], "_installed", lambda real=_installed: [*real(), plugin])
    lab = Lab(tmp_path, os_name="Other")
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["post"].append({"id": "host", "type": "vst-host", "plugin": plugin, "label": plugin,
                                               "knobs": [{"i": 2, "name": "Cutoff"}, {"i": 99, "name": "Ghost"}],
                                               "params": {"p2": 0.25}})
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    live = lab.livemap()
    assert "host" in live["blocks"], lab.log()
    assert live["blocks"]["host"]["params"] == {"p2": {"p": 2, "pmin": 0, "pmax": 1}}


def test_une_scene_sans_niveau_revient_a_0_db(lab):
    """2026-11-12 (banc des presets sur deux moteurs) : une scène SANS niveau gardait celui de la scène d'avant — C à
    +3 dB puis D sans niveau sonnait à +3. Sans niveau = 0 dB, et le gain du merge (un plugin en tête) n'y est pour rien."""
    import copy
    p = copy.deepcopy(PATCH)
    p["scenes"][1]["lanes"][LANE]["level"] = 3                       # B à +3 dB, A et C sans niveau
    lab.compile(p, scene="A")
    lab.run(action="rig_recall", preset="ci-engine", scene="A")

    def vol():
        t = next(t for t in lab.tracks() if t["name"].endswith("#merge"))
        return t["info"].get("D_VOL")
    assert vol() == pytest.approx(1.0), lab.log()
    lab.compile(p, scene="B")
    lab.run(action="scene_apply", preset="ci-engine", scene="B")
    assert vol() == pytest.approx(10 ** (3 / 20)), lab.log()
    lab.compile(p, scene="C")
    lab.run(action="scene_apply", preset="ci-engine", scene="C")
    assert vol() == pytest.approx(1.0), lab.log()


def test_l_autowah_linux_ne_coupe_pas_son_plugin(tmp_path):
    """2026-11-12 : le « Wah » de l'autowah n'existe pas sur GxAutoWah (Linux) ; le repli au rang numérique écrivait
    0.45 dans son port BYPASS (rang 0) et coupait l'effet. `index_fallback: false` (catalogue v36) : rien n'est écrit."""
    import copy
    lab = Lab(tmp_path)
    lab.F.specs["GxAutoWah"] = lab.L.table_from([lab.L.table_from({"name": "BYPASS", "min": 0, "max": 1, "def": 1})])
    p = copy.deepcopy(PATCH)
    p["lanes"][0]["chain"]["pre"].append({"id": "env", "type": "autowah", "params": {"wah": 0.45}})
    lab.compile(p)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    vals = {q.name: q.val for q in fx["golem:env"].params.values()}
    assert vals["BYPASS"] == 1, lab.log()


def test_le_coupe_bas_de_reaeq_est_active(lab):
    """2026-11-12 : la bande 4 de ReaEQ (passe-haut = `lowcut`) est désactivée dans une instance neuve ; golem réglait sa
    fréquence et rien ne coupait (0,0 dB de 20 à 300 Hz, mesuré sur bruit blanc). golem_rig l'active à l'ajout."""
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    assert fx["golem:eq"].cfg["BANDENABLED4"] == "1", lab.log()


# ── golem-fx SOUS REAPER (docs/golem-fx-reaper.md, 2026-11-13) ──────────────────────────────────────────────────
# Un type que la table du moteur fait jouer par golem-fx le joue aussi sous REAPER — si le VST3 est installé dans CE
# REAPER ; sinon le bloc garde son plugin d'origine. Les valeurs du catalogue (dB, ms…) s'écrivent NORMALISÉES avec
# les bornes du plugin (golem-fx-plugins.json), une liste par son rang sur le nombre de choix du plugin.
# 2026-11-15 : les trois OS — les installateurs posent golem-fx, et un type qu'il joue échappe à la table de l'OS
OS3 = pytest.mark.parametrize("os_name", ["Other", "Win64", "macOS-arm64"], ids=["linux", "windows", "macos"])


@OS3
def test_golem_fx_sous_reaper_installe_ou_non(tmp_path, os_name):
    import copy
    lab = Lab(tmp_path, os_name=os_name)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    by_name = {p["name"]: p for p in plugins.values()}
    for nm in ("GoleM FX Delay", "GoleM FX Gate"):                 # installés ; le Chorus golem-fx, non
        p = by_name[nm]
        lab.F.installed[p["reaper"]] = True
        lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0})
                                                     for k in p["params"]])
    patch = copy.deepcopy(PATCH)
    post = patch["lanes"][0]["chain"]["post"]
    post[1]["params"] = {"time": "1/8", "feedback": 40, "mix": 25}
    patch["lanes"][0]["chain"]["pre"][0]["params"] = {"thresh": -50}
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    assert fx["golem:dly"].name == "VST3: GoleM FX Delay (GoleM)", lab.log()
    assert fx["golem:gate"].name == "VST3: GoleM FX Gate (GoleM)"
    assert fx["golem:chorus"].name != "VST3: GoleM FX Chorus (GoleM)"     # pas installé : le plugin d'origine

    def val(fid, name):
        return next(p.val for p in fx[fid].params.values() if p.name == name)
    rd = by_name["GoleM FX Delay"]["params"]
    fb = rd["Feedback"]
    assert val("golem:dly", "Feedback") == pytest.approx((40 - fb["min"]) / (fb["max"] - fb["min"]))
    opts = next(e for e in json.loads((ROOT / "library/catalog/effects.json").read_text(encoding="utf-8"))["effects"]
                if e["type"] == "delay")
    tdef = next(d for d in opts["params"] if d["id"] == "time")
    n = rd["Time"]["n"]
    assert val("golem:dly", "Time") == pytest.approx(tdef["options"].index("1/8") / (n - 1))
    th = by_name["GoleM FX Gate"]["params"]["Threshold"]
    assert val("golem:gate", "Threshold") == pytest.approx((-50 - th["min"]) / (th["max"] - th["min"]))
    assert "golem-fx sous REAPER : 2 type(s)" in lab.log()


def test_un_potard_absent_de_golem_fx_ne_salit_pas_le_journal(tmp_path):
    # 2026-11-20 : le `channel` de guitar-drive est `absent` (table du moteur) — gfx_range le cherchait quand même et
    # écrivait « absent du manifeste » à chaque lecture du catalogue. Tous les golem-fx installés : aucun faux avertissement.
    lab = Lab(tmp_path)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    for p in plugins.values():
        lab.F.installed[p["reaper"]] = True
        lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0})
                                                     for k in p["params"]])
    lab.compile(PATCH)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    assert "golem-fx sous REAPER" in lab.log()
    assert "absent du manifeste" not in lab.log(), lab.log()


def test_un_reglage_de_la_pedale_golem_fx_s_ecrit_sous_reaper(tmp_path, monkeypatch):
    # la feuille golem FX (docs/golem-fx-sheet.md) : Warmth n'existe que sur gfx-chorus — sous REAPER avec le plugin, il
    # s'écrit NORMALISÉ sur ses bornes (0–100 %) comme les potards du catalogue
    import copy
    lab = Lab(tmp_path)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    cid, p = next((k, v) for k, v in plugins.items() if v["name"] == "GoleM FX Chorus")
    from bridge import rig
    monkeypatch.setattr(rig, "_golem_fx_installed", lambda: {cid})     # le bridge le sait installé : il garde Warmth
    lab.F.installed[p["reaper"]] = True
    lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0}) for k in p["params"]])
    patch = copy.deepcopy(PATCH)
    post = patch["lanes"][0]["chain"]["post"]
    post[0] = {"id": "chorus", "type": "chorus", "foot": 7, "params": {"rate": 1.0, "warmth": 70, "mode": "Dual I"}}
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    ch = fx["golem:chorus"]
    assert ch.name == p["reaper"], lab.log()

    def val(name):
        return next(q.val for q in ch.params.values() if q.name == name)
    w = p["params"]["Warmth"]
    assert val("Warmth") == pytest.approx((70 - w["min"]) / (w["max"] - w["min"]))
    assert val("Mode") == pytest.approx(1 / (p["params"]["Mode"]["n"] - 1))


@OS3
def test_met_emet_shem_se_posent_sous_reaper_avec_golem_fx(tmp_path, monkeypatch, os_name):
    # les blocs du seul golem-fx (catalogue v43) : sous REAPER avec leurs plugins installés, posés par leur nom REAPER,
    # réglages de face avant ET experts écrits normalisés ; sans golem-fx, le compilateur les retire (quarantaine).
    # Windows et macOS aussi (2026-11-15) : `unsupported` dans leur table, ils y jouent dès que golem-fx est là
    import copy
    lab = Lab(tmp_path, os_name=os_name)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    want = {"met": "GoleM FX Met", "emet": "GoleM FX Emet", "shem": "GoleM FX Shem"}
    cids = {k for k, v in plugins.items() if v["name"] in want.values()}
    from bridge import rig
    monkeypatch.setattr(rig, "_golem_fx_installed", lambda: cids)
    for cid in cids:
        p = plugins[cid]
        lab.F.installed[p["reaper"]] = True
        lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0}) for k in p["params"]])
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["pre"] = [{"id": "met", "type": "met", "params": {"thresh": -60, "ratio": 4}},
                                          {"id": "emet", "type": "emet", "params": {"gain": 20, "tight": 510}},
                                          {"id": "shem", "type": "shem", "params": {"grind": 6, "voice": "Full"}}]
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    by_name = {v["name"]: v for v in plugins.values()}

    def norm(t, label, v):
        r = by_name[want[t]]["params"][label]
        return (v - r["min"]) / (r["max"] - r["min"]) if r["kind"] == "float" else v / (r["n"] - 1)

    def val(t, label):
        return next(q.val for q in fx["golem:" + t].params.values() if q.name == label)
    for t in want:
        assert fx["golem:" + t].name == by_name[want[t]]["reaper"], lab.log()
    assert val("met", "Threshold") == pytest.approx(norm("met", "Threshold", -60))
    assert val("met", "Ratio") == pytest.approx(norm("met", "Ratio", 4))
    assert val("emet", "Tight") == pytest.approx(norm("emet", "Tight", 510))
    assert val("shem", "Voice") == pytest.approx(norm("shem", "Voice", 1))

    monkeypatch.setattr(rig, "_golem_fx_installed", lambda: set())          # sans golem-fx : hors de la compile
    plan = lab.compile(patch)
    txt = json.dumps(plan)
    assert not any(f'"type": "{t}"' in txt for t in want), txt[:400]


@pytest.mark.parametrize("os_name", ["Win64", "macOS-arm64"], ids=["windows", "macos"])
def test_sans_le_plugin_dans_reaper_la_table_de_l_os_reprend_la_main(tmp_path, monkeypatch, os_name):
    # le bridge voit le bundle (dossier VST3) mais REAPER ne l'a pas scanné : golem_rig ne bascule rien, la table de l'OS
    # s'applique comme avant — Met y est `unsupported`, dit au journal, et le reste de la chaîne tient
    import copy
    lab = Lab(tmp_path, os_name=os_name)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    from bridge import rig
    monkeypatch.setattr(rig, "_golem_fx_installed", lambda: {k for k, v in plugins.items() if v["name"] == "GoleM FX Met"})
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["pre"] = [{"id": "met", "type": "met"}, {"id": "gate", "type": "gate"}]
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    assert "golem:met" not in fx and "golem:gate" in fx, lab.log()
    assert ("x bloc met : " + ("Windows" if os_name == "Win64" else "macOS")) in lab.log()
    assert "GoleM FX" not in fx["golem:gate"].name


def test_la_cle_du_gate_entend_le_di_de_la_lane(tmp_path, monkeypatch):
    # docs/golem-fx-sheet.md §4 : Met (catalogue v43) a une entrée de clé. Sur la piste d'ENTRÉE, golem_keytap en tête
    # recopie le DI sur 3/4 ; ailleurs (le merge, après l'ampli), un envoi PRÉ-FX de l'entrée arrive sur 3/4
    import copy
    lab = Lab(tmp_path)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    cid, p = next((k, v) for k, v in plugins.items() if v["name"] == "GoleM FX Met")
    from bridge import rig
    monkeypatch.setattr(rig, "_golem_fx_installed", lambda: {cid})
    lab.F.installed[p["reaper"]] = True
    lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0}) for k in p["params"]])
    patch = copy.deepcopy(PATCH)
    ch = patch["lanes"][0]["chain"]
    ch["pre"] = [{"id": "met", "type": "met"}]                                 # sur la piste d'entrée
    ch["post"] = [{"id": "met2", "type": "met"}] + ch["post"]                  # sur le merge, après les branches
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    tracks = lab.tracks()
    root = next(t for t in tracks if any(f["renamed"] == "golem:met" for f in t["fx"]))
    merge = next(t for t in tracks if any(f["renamed"] == "golem:met2" for f in t["fx"]))
    assert "keytap" in root["fx"][0]["name"].lower(), [f["name"] for f in root["fx"]]
    assert root["info"]["I_NCHAN"] == 4 and merge["info"]["I_NCHAN"] == 4, lab.log()
    raw = next(t for t in lab.F.tracks.values() if t.name == root["name"])
    sends = [dict(x) for x in raw.sends.values()]
    key = [x for x in sends if x["I_DSTCHAN"] == 2]
    assert len(key) == 1 and key[0]["I_SENDMODE"] == 1 and key[0]["I_MIDIFLAGS"] == 31 and key[0]["I_SRCCHAN"] == 1024
    assert key[0]["dest"].name == merge["name"]
    assert not any("keytap" in f["name"].lower() for f in merge["fx"])
    # les autres envois de l'entrée (vers les branches) restent sur 1/2 : la clé ne descend pas dans le son
    assert all(x["I_DSTCHAN"] == 0 and x["I_SRCCHAN"] == 0 for x in sends if x is not key[0] and x["I_DSTCHAN"] != 2)


def test_le_bloc_ir_fx_recoit_son_ir_entiere_dans_l_etat_du_convolveur(tmp_path, monkeypatch):
    # docs/library-tones.md §8 : posé par son nom (x42 IR Convolver Stereo), son IR écrite dans l'état LV2 (la ligne
    # #ir du gabarit du baffle) — et c'est la copie ENTIÈRE : la garde du baffle couperait l'écho
    import copy
    import struct
    import wave
    from bridge import compile_rig
    ir = tmp_path / "echo.wav"
    with wave.open(str(ir), "wb") as w:                      # une impulsion, puis un écho à 300 ms : ce que la garde coupe
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
        frames = [0] * 24000
        frames[0], frames[14400] = 30000, 15000
        w.writeframes(b"".join(struct.pack("<h", v) for v in frames))
    monkeypatch.setattr(compile_rig, "_resolve", lambda ref, comps=None, model=None: str(ir))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / "cache"))
    lab = Lab(tmp_path)
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["post"].append({"id": "re301", "type": "ir-fx", "ref": "101878", "model": "1",
                                               "params": {"wet": -6, "dry": 0}})
    lab.compile(patch)
    rig_json = json.loads(next((lab.root / "reaper/FXChains").glob("ci-engine*.rig.json")).read_text(encoding="utf-8"))
    files = [b.get("file") for p in rig_json["paths"] for t in p["tracks"] for b in t["blocks"] if b.get("type") == "ir-fx"]
    assert files and "_whole_" in files[0], files          # la copie entière, pas la copie coupée du baffle
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = next(f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name == "golem:re301")
    assert "IR Convolver Stereo" in fx.name, lab.log()
    assert ("zeroconvolv#ir " + files[0]) in (fx.state or ""), lab.log()[-2000:]


def test_le_pied_d_un_granular_joue_par_gfx_grains_tient_le_freeze(tmp_path):
    # golem-fx 2026-11-15 : le pied de gfx-grains TIENT le Freeze (comme GoleM Freeze), il ne coupe pas le bloc
    import copy
    lab = Lab(tmp_path)
    for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
        shutil.copy2(ROOT / "library/catalog" / f, lab.root / "library/catalog" / f)
    plugins = json.loads((ROOT / "library/catalog/golem-fx-plugins.json").read_text(encoding="utf-8"))["plugins"]
    p = next(p for p in plugins.values() if p["crate"] == "gfx-grains")
    lab.F.installed[p["reaper"]] = True
    lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0})
                                                 for k in p["params"]])
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["post"].append({"id": "grains", "type": "granular", "foot": 10})
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    g = fx["golem:grains"]
    assert g.name == p["reaper"], lab.log()
    freeze = lambda: next(q.val for q in g.params.values() if q.name == "Freeze")       # noqa: E731
    lab.run(action="stomp", preset="ci-engine", ids=["grains"], on=True)
    assert freeze() == 1 and g.enabled is True, lab.log()
    lab.run(action="stomp", preset="ci-engine", ids=["grains"], on=False)
    assert freeze() == 0 and g.enabled is True, lab.log()


# ── DEUX AMPLIS SUR UNE LANE (2026-11-15) ─────────────────────────────────────────────────────────────────
# Vu au rack : amp-x4x1 (Fender, coupé en scène A) AVANT amp-smku (EVH, allumé) sur une piste sans split. REAPER
# montrait UN seul NAM, non estampillé, chargé du Fender ; l'EVH n'existait pas, sa carte vivante pointait sur le
# Fender, et la vérification des fichiers disait « ok ». Ici : chaque ampli a son NAM, son fichier, son estampille.
NAM_LV2 = "LV2: Neural Amp Modeler (Mike Oliphant) (Mono)"
X42_LV2 = "LV2: x42 - IR Convolver Mono"
TWO = [("A", "EVH", {"amp-x4x1": False, "amp-smku": True}), ("B", "Fender", {"amp-x4x1": True, "amp-smku": False})]
TWO_AMPS = {"id": "two-amps", "name": "Two amps", "role": "guitar", "kind": "patch", "patch_v": 2, "lanes_v": 2, "bpm": 120,
            "lanes": [{"id": "gtr", "role": "guitar", "name": "Two amps", "midi": False, "stereo": False,
                       "chain": {"pre": [{"id": "gate", "type": "gate"},
                                         {"id": "amp-x4x1", "type": "amp", "ref": "6237", "params": {"output": -3}},
                                         {"id": "eq", "type": "eq"},
                                         {"id": "amp-smku", "type": "amp", "ref": "6440", "params": {"output": 2}}],
                                 "post": [{"id": "dly", "type": "delay"}]},
                       "states": [{"id": f"st-gtr-{s}", "name": n, "blocks": b, "params": {}, "branches": {}} for s, n, b in TWO]}],
            "scenes": [{"id": s, "name": n, "blocks": b, "branches": {}, "lanes": {"gtr": {"state": f"st-gtr-{s}"}}} for s, n, b in TWO],
            "config": {"gen": {"out": "1-2", "blocks": []}}}


def _amp_lab(tmp_path, monkeypatch, patch):
    from bridge import compile_rig
    files = {}
    # « head-a / head-b » : des têtes qu'aucun catalogue local ne connaît (6237/6440 sont, sur un rack réel, des captures
    # ampli + baffle : _carries_cab y lit le catalogue des tons et n'ajoute pas de baffle par défaut)
    for ref, name in (("6237", "fender-deluxe.nam"), ("6440", "evh-5150.nam"), ("head-a", "head-a.nam"),
                      ("head-b", "head-b.nam"), (compile_rig.DEFAULT_CAB, "mesa.wav")):
        p = tmp_path / "lib" / name
        p.parent.mkdir(exist_ok=True)
        if name.endswith(".nam"):
            p.write_text(json.dumps({"metadata": {"loudness": -18.0}}))
        else:
            p.write_bytes(b"RIFF")
        files[ref] = str(p)
    monkeypatch.setattr(compile_rig, "_resolve", lambda ref, comps=None, model=None: files.get(str(ref), ""))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / "cache"))
    # LE MÊME SYSTÈME DES DEUX CÔTÉS (2026-11-22) : le moteur factice est un Linux (Lab os_name « Other », NAM et x42 en
    # LV2) ; le compilateur, lui, lisait le VRAI système — sous Windows il rendait un cœur natif que ce moteur ne pose pas,
    # et six tests y étaient rouges depuis le 2026-11-15
    monkeypatch.setattr(compile_rig, "COMPILE_TARGET", "linux")
    monkeypatch.setattr(compile_rig, "_ir_guard", lambda src, dst: shutil.copy2(src, dst))   # un faux .wav
    lab = Lab(tmp_path)
    nam = [{"name": "Input Lvl", "min": -20, "max": 20, "def": 0}, {"name": "Output Lvl", "min": -20, "max": 20, "def": 0},
           {"name": "Neural Model", "min": 0, "max": 1, "def": 0}, {"name": "Quality", "min": 0, "max": 1, "def": 1}]
    x42 = [{"name": "Enable", "min": 0, "max": 1, "def": 1}, {"name": "Wet Signal Level", "min": -40, "max": 40, "def": 0},
           {"name": "Impulse Response", "min": 0, "max": 1, "def": 0}]
    lab.F.specs[NAM_LV2] = lab.L.table_from([lab.L.table_from(p) for p in nam])
    lab.F.specs[X42_LV2] = lab.L.table_from([lab.L.table_from(p) for p in x42])
    lab.compile(patch)
    return lab


@pytest.fixture
def two_amps(tmp_path, monkeypatch):
    return _amp_lab(tmp_path, monkeypatch, TWO_AMPS)


def _amp_fx(lab):
    """{estampille: (piste, index, fx)} des NAM posés."""
    out = {}
    for t in lab.F.tracks.values():
        for i, f in enumerate(t.fx.values()):
            if f.name == NAM_LV2:
                out[f.cfg.renamed_name or f"untagged#{i}"] = (t, i, f)
    return out


def test_deux_amplis_sur_une_lane_deux_nam_chacun_son_fichier(two_amps):
    lab = two_amps
    lab.run(action="rig_recall", preset="two-amps", scene="A")
    amps = _amp_fx(lab)
    assert set(amps) == {"golem:amp-x4x1", "golem:amp-smku"}, (sorted(amps), lab.log()[-3000:])
    (tf, i_f, fender), (te, i_e, evh) = amps["golem:amp-x4x1"], amps["golem:amp-smku"]
    assert tf is te                                                     # même piste : pas de split
    assert "fender-deluxe" in fender.state and "evh-5150" not in fender.state, fender.state
    assert "evh-5150" in evh.state and "fender-deluxe" not in evh.state, evh.state
    assert fender.guid != evh.guid                                      # la mémoire des fichiers est par FXID
    # l'ordre de la chaîne : gate, Fender, eq, EVH, delay
    tags = [f.cfg.renamed_name for f in tf.fx.values() if f.cfg.renamed_name]
    assert tags.index("golem:gate") < tags.index("golem:amp-x4x1") < tags.index("golem:eq") \
        < tags.index("golem:amp-smku") < tags.index("golem:dly"), tags
    # scène A : Fender coupé, EVH allumé
    assert fender.enabled is False and evh.enabled is True, lab.log()
    # la carte vivante : chaque ampli vise SON NAM (plus jamais les potards de l'EVH sur le Fender)
    live = lab.livemap()["blocks"]
    assert live["amp-x4x1"]["fx"] == i_f and live["amp-smku"]["fx"] == i_e and i_f != i_e, live
    assert "output" in live["amp-smku"]["params"], live["amp-smku"]
    # les potards de chaque bloc sur SON instance
    outp = lambda f: next(q.val for q in f.params.values() if q.name == "Output Lvl")    # noqa: E731
    assert outp(evh) != outp(fender), (outp(evh), outp(fender))


def test_deux_amplis_la_scene_bascule_sans_rebuild_et_le_rappel_reutilise(two_amps):
    lab = two_amps
    lab.run(action="rig_recall", preset="two-amps", scene="A")
    names = [t["name"] for t in lab.tracks()]
    lab.compile(TWO_AMPS, scene="B")
    lab.run(action="scene_apply", preset="two-amps", scene="B")
    assert lab.calls("TrackFX_AddByName") == 0 and lab.calls("TrackFX_Delete") == 0 and lab.calls("DeleteTrack") == 0
    amps = _amp_fx(lab)
    assert amps["golem:amp-x4x1"][2].enabled is True and amps["golem:amp-smku"][2].enabled is False, lab.log()
    # rappel identique : même signature -> REUSE, aucune chirurgie, aucun NAM rechargé
    lab.run(action="rig_recall", preset="two-amps", scene="B")
    assert lab.calls("TrackFX_Delete") == 0 and lab.calls("SetTrackStateChunk") == 0, lab.log()[-2000:]
    assert [t["name"] for t in lab.tracks()] == names
    amps = _amp_fx(lab)
    assert set(amps) == {"golem:amp-x4x1", "golem:amp-smku"}
    assert amps["golem:amp-x4x1"][2].enabled is True and amps["golem:amp-smku"][2].enabled is False


def test_deux_amplis_le_stomp_vise_le_bon_nam(two_amps):
    lab = two_amps
    lab.run(action="rig_recall", preset="two-amps", scene="A")
    lab.run(action="stomp", preset="two-amps", ids=["amp-x4x1"], on=True)
    amps = _amp_fx(lab)
    assert amps["golem:amp-x4x1"][2].enabled is True and amps["golem:amp-smku"][2].enabled is True


def test_la_verification_voit_le_mauvais_fichier(two_amps):
    """UN fichier chargé ne suffit plus : le NAM de l'EVH qui afficherait le modèle du Fender est un défaut."""
    lab = two_amps
    lab.run(action="rig_recall", preset="two-amps", scene="A")

    def verify():
        lab.F.ext["golem/rig_verify"] = "2"
        lab.L.execute(RIG)
        return json.loads((lab.root / "presets/.rig-check.json").read_text(encoding="utf-8"))
    ok = verify()
    assert ok["ok"] is True and ok["checked"] >= 1, (ok, lab.log()[-2000:])
    evh = _amp_fx(lab)["golem:amp-smku"][2]
    evh.shown = lab.L.table_from({"Neural Model": "fender-deluxe.nam"})
    bad = verify()
    assert bad["ok"] is False, bad
    assert any(i["kind"] == "model" and "evh-5150" in i["expected"] and i["loaded"] == "fender-deluxe.nam"
               for i in bad["issues"]), bad
    evh.shown = lab.L.table_from({"Neural Model": ""})                 # rien de chargé : déjà vu avant ce jour
    empty = verify()
    assert empty["ok"] is False and any(i["loaded"] == "" for i in empty["issues"]), empty


def _variant(blocks_pre, states, pid):
    import copy
    p = copy.deepcopy(TWO_AMPS)
    p["id"] = pid
    p["lanes"][0]["chain"]["pre"] = blocks_pre
    p["lanes"][0]["states"] = [{"id": f"st-gtr-{s}", "name": s, "blocks": b, "params": {}, "branches": {}} for s, b in states]
    p["scenes"] = [{"id": s, "name": s, "blocks": b, "branches": {}, "lanes": {"gtr": {"state": f"st-gtr-{s}"}}} for s, b in states]
    return p


def test_un_seul_ampli_se_pose_comme_avant(tmp_path, monkeypatch):
    """Le cas commun ne change pas : UN NAM du gabarit (FXID du gabarit, pas de core_ids), trouvé par son nom, la
    carte vivante sur lui, la scène qui l'allume et l'éteint."""
    from bridge import compile_rig
    patch = _variant([{"id": "gate", "type": "gate"}, {"id": "amp-smku", "type": "amp", "ref": "6440"}],
                     [("A", {"amp-smku": True}), ("B", {"amp-smku": False})], "one-amp")
    lab = _amp_lab(tmp_path, monkeypatch, patch)
    plan = json.loads((lab.root / "reaper/FXChains/one-amp.rig.json").read_text(encoding="utf-8"))
    track = plan["paths"][0]["tracks"][0]
    assert "core_ids" not in track
    core = (lab.root / "reaper/FXChains" / track["rfxchain"]).read_text(encoding="latin-1")
    model = compile_rig._safe_asset(str(tmp_path / "lib/evh-5150.nam"))
    assert core == compile_rig._tpl(compile_rig.TEMPLATE_HEAD, {"%MODEL%": model})
    lab.run(action="rig_recall", preset="one-amp", scene="A")
    amps = _amp_fx(lab)
    assert len(amps) == 1, (sorted(amps), lab.log())
    t, i, nam = next(iter(amps.values()))
    assert nam.guid == "{B43FDC6B-1DC5-9ACE-633B-9EB8BF0C5A1F}" and nam.enabled is True
    assert lab.livemap()["blocks"]["amp-smku"]["fx"] == i
    lab.compile(patch, scene="B")
    lab.run(action="scene_apply", preset="one-amp", scene="B")
    assert nam.enabled is False, lab.log()


def test_deux_tetes_chacune_son_baffle_qui_la_suit(tmp_path, monkeypatch):
    """Deux têtes NAM sans cab sur le path : chacune son baffle par défaut, juste derrière elle, qui s'éteint avec
    elle (scène comme pied) — sinon la DI de la tête coupée passerait dans son IR."""
    patch = _variant([{"id": "a1", "type": "amp-nam", "ref": "head-a"}, {"id": "a2", "type": "amp-nam", "ref": "head-b"}],
                     [("A", {"a1": True, "a2": False}), ("B", {"a1": False, "a2": True})], "two-heads")
    lab = _amp_lab(tmp_path, monkeypatch, patch)
    lab.run(action="rig_recall", preset="two-heads", scene="A")
    tr = next(t for t in lab.F.tracks.values() if any(f.cfg.renamed_name == "golem:a1" for f in t.fx.values()))
    fx = list(tr.fx.values())
    tags = [f.cfg.renamed_name for f in fx]
    assert tags.index("golem:a1") + 1 == tags.index("golem:a1~ir") < tags.index("golem:a2") < tags.index("golem:a2~ir"), tags
    by = {f.cfg.renamed_name: f for f in fx}

    def on(tag):
        f = by[tag]
        if f.name == X42_LV2:
            return f.enabled and next(q.val for q in f.params.values() if q.name == "Enable") == 1
        return f.enabled
    assert on("golem:a1") and on("golem:a1~ir") and not on("golem:a2") and not on("golem:a2~ir"), lab.log()
    live = lab.livemap()["blocks"]
    assert {"a1", "a2"} <= set(live) and "a1~ir" not in live and live["a1"]["fx"] != live["a2"]["fx"]
    lab.run(action="stomp", preset="two-heads", ids=["a2"], on=True)
    assert on("golem:a2") and on("golem:a2~ir"), lab.log()
    lab.compile(patch, scene="B")
    lab.run(action="scene_apply", preset="two-heads", scene="B")
    assert not on("golem:a1") and not on("golem:a1~ir") and on("golem:a2") and on("golem:a2~ir"), lab.log()
