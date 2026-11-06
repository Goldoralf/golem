# SPDX-License-Identifier: GPL-3.0-or-later
"""Surge XT Effects sous Windows/macOS (2026-10-22, mesuré au banc) : « FX Type » est un paramètre VST3 NORMALISÉ (29
types, Spring = 26/28), les 17 fentes changent de NOM selon le type, et le plugin RÉINITIALISE ses paramètres au bloc
audio suivant — la table pose le type par `fx_init`, demande une seconde passe (`late_params`), et golem_rig la fait.
Le bloc delay-echo, en quarantaine sous Linux (GxEchoCat fige le moteur), est joué ici par golem_echocat.jsfx : la
quarantaine est un fait sur un PLUGIN, pas sur un type."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _table(name):
    return json.load(open(os.path.join(ROOT, "library", "catalog", name), encoding="utf-8"))["effects"]


def test_les_tables_posent_le_type_surge_en_normalise_et_demandent_la_seconde_passe():
    for osn in ("effects-windows.json", "effects-macos.json"):
        t = _table(osn)
        for btype, idx in (("surge-spring", 26), ("surge-freqshift", 6), ("surge-treemonster", 23)):
            e = t[btype]
            assert e["plugin"].startswith("VST3: Surge XT Effects") and e["param_mode"] == "norm" and e["late_params"] is True
            assert abs(e["fx_init"]["FX Type"] - idx / 28) < 0.000001
            assert "Wet" not in e["params"]                                 # le Mix du catalogue = le Wet de REAPER, inchangé
        assert t["surge-spring"]["params"]["size"] == "Reverb Size"


def test_golem_rig_lit_fx_init_et_late_params_et_rejoue_apres_la_construction():
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    assert "if override.fx_init then e.fx_init = override.fx_init end" in lua
    assert "(schema and schema.fx_init) or FX_INIT[block.type]" in lua
    assert "function flush_late_params(effects)" in lua and "flush_late_params(effects)" in lua.split("function flush_late_params")[1]
    assert "params._late" in lua


def test_la_quarantaine_est_par_plugin_sur_le_bureau(monkeypatch):
    from bridge import rig
    monkeypatch.setattr(rig, "_QUARANTINE", None)
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    assert "delay-echo" in rig.quarantined_types() and "detune" in rig.quarantined_types()
    monkeypatch.setattr(rig, "_QUARANTINE", None)
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    q = rig.quarantined_types()
    assert "delay-echo" not in q and "detune" in q                          # golem_echocat joue, GxDetune reste interdit
    monkeypatch.setattr(rig, "_QUARANTINE", None)


def test_l_installeur_windows_pose_surge_xt(tmp_path):
    import io
    import zipfile
    from provision import surge
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Surge XT Effects.vst3/Contents/x86_64-win/Surge XT Effects.vst3", b"x")
        z.writestr("Surge XT.vst3/Contents/x86_64-win/Surge XT.vst3", b"y")
    data = buf.getvalue()
    import hashlib
    surge.PIN["sha256"] = hashlib.sha256(data).hexdigest()
    dest = surge.install(fetch=lambda url: data, log=lambda *a: None, dest=tmp_path)
    assert (dest / "Surge XT Effects.vst3" / "Contents").is_dir() and not (dest / "Surge XT.vst3").exists()
    src = open(os.path.join(ROOT, "provision", "desktop.py"), encoding="utf-8").read()
    assert "from provision import surge" in src


def test_la_passe_differee_rejoue_les_parametres_apres_la_reinitialisation_du_plugin(tmp_path):
    """Le REAPER factice ne renomme pas ses fentes ; on simule la REINITIALISATION de Surge (Size remis a 0,5 apres le
    build) et on fait tourner les defers : la seconde passe doit remettre la valeur du preset, et FX Type est pose
    par fx_init (26/28), pas par le FX_INIT statique (27 brut)."""
    import copy
    import pytest
    pytest.importorskip("lupa")
    from tests.test_rig_lua import Lab, PATCH
    lab = Lab(tmp_path, os_name="Win64")
    names = ["FX Type", "Reverb Size", "Reverb Decay", "Reverb Reflections", "Reverb HF Damping", "Modulation Spin", "Modulation Chaos", "Modulation Knock", "Wet"]
    lab.F.installed["VST3: Surge XT Effects (Surge Synth Team)"] = True          # l'inventaire factice le connait
    lab.F.specs["VST3: Surge XT Effects (Surge Synth Team)"] = lab.L.table_from(
        [lab.L.table_from({"name": n, "min": 0, "max": 1, "def": 0.5}) for n in names])
    patch = copy.deepcopy(PATCH)
    patch["lanes"][0]["chain"]["post"] += [{"id": "spr", "type": "surge-spring", "params": {"size": 0.8, "decay": 0.3, "mix": 0.35}}]
    lab.compile(patch)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    assert "golem:spr" in fx, lab.log()
    val = lambda name: next(p.val for p in fx["golem:spr"].params.values() if p.name == name)
    assert val("FX Type") == pytest.approx(26 / 28, abs=0.00001) and val("Reverb Size") == pytest.approx(0.8, abs=0.0001)
    # Surge se reinitialise au bloc suivant : on le simule, puis on laisse courir les defers (0,35 s puis 1,2 s factices)
    for p in fx["golem:spr"].params.values():
        if p.name == "Reverb Size":
            p.val = 0.5
    for _ in range(1500):
        if lab.F.run_defers() == 0:
            break
    assert val("Reverb Size") == pytest.approx(0.8, abs=0.0001), lab.log()
    assert "late params : passe 2" in lab.log()
