# SPDX-License-Identifier: GPL-3.0-or-later
"""La moitié rack des recettes de capture (docs/plugin-recipes.md) : le contrôle d'un brouillon, le plan des
rendus, et les verdicts — sur des rendus SYNTHÉTIQUES (aucun REAPER ici). Les chiffres réels de d'une suite d'ampli (11 rendus,
61 s) sont dans le contrat, §6."""
import math

import pytest

from bridge import plugin_recipes as R

SR = 48000
N = 2 * R.T_PROBE + int(R.GAP_S * SR) + int(R.TAIL_S * SR)

SHEET = {"params": [
    {"i": 0, "name": "Gate", "display": "-65.0", "norm": 0.38, "display_min": "-90.0", "display_max": "0.0"},
    {"i": 1, "name": "Pedals Active", "display": "Active", "norm": 1.0},
    {"i": 2, "name": "Logos Active", "display": "Active", "norm": 1.0},
    {"i": 3, "name": "Time Active", "display": "Active", "norm": 1.0},
    {"i": 4, "name": "Reverb Active", "display": "Active", "norm": 1.0},
    {"i": 5, "name": "Active Amp", "display": "Active", "norm": 1.0},
    {"i": 6, "name": "Cab Active", "display": "Active", "norm": 1.0},
    {"i": 7, "name": "Amp Type", "display": "Clean", "norm": 0.0}],
    "steps": {str(i): ["Inactive", "Active"] for i in range(1, 7)} | {"7": ["Clean", "Rhythm", "Lead"]}}
A = "Active"


def draft():
    return {"schema": 2, "full": {
        "off": {"Time Active": "Inactive"},
        "refuse": [{"id": "logos", "kind": "modulation", "when": {"Pedals Active": A, "Logos Active": A},
                    "switch": "Logos Active", "why": "w", "confidence": "low"}],
        "captured": [{"id": "amp", "when": {"Active Amp": A}, "why": "w", "confidence": "high"}]},
        "split": {"parts": [{"id": "cab", "gear": "cab", "block": "cab", "ir": True, "when": {"Cab Active": A},
                             "off": {"Active Amp": "Inactive", "Time Active": "Inactive"}, "why": "w", "confidence": "medium"}]},
        "translate": [{"id": "reverb", "block": "reverb", "when": {"Time Active": A, "Reverb Active": A},
                       "switch": "Reverb Active", "why": "w", "confidence": "high"}]}


def sig(moving=False, tail=False, gain=1.0):
    """La sonde rendue : deux passages identiques (ou non), puis la queue (ou le silence)."""
    seg = [0.3 * math.sin(i * 0.05) for i in range(R.T_PROBE)]
    seg2 = [v * (1.2 if moving else 1.0) for v in seg]
    end = [0.02 * math.exp(-i / SR) for i in range(int(R.TAIL_S * SR))] if tail else [0.0] * int(R.TAIL_S * SR)
    return [gain * v for v in seg + [0.0] * int(R.GAP_S * SR) + seg2 + end]


def test_le_controle_refuse_un_nom_ou_une_valeur_que_le_plugin_n_a_pas():
    assert R.check_draft(draft(), SHEET) == []
    d = draft()
    d["full"]["off"]["Reverb Mix"] = "0"
    d["full"]["refuse"][0]["when"]["Logos Active"] = "On"
    d["translate"][0]["confidence"] = "sure"
    errs = R.check_draft(d, SHEET)
    assert any("unknown parameter « Reverb Mix »" in e for e in errs)
    assert any("« On » is not a value of « Logos Active »" in e for e in errs)
    assert any("missing why/confidence" in e for e in errs)


def test_un_bout_de_course_d_un_parametre_continu_est_une_valeur_valide():
    """Le `-96.0` du gate d'une suite d'ampli : ni un cran, ni l'affichage courant — l'affichage au minimum."""
    d = draft()
    d["translate"][0]["unless"] = {"Gate": "-90.0"}
    assert R.check_draft(d, SHEET) == []
    d["translate"][0]["unless"] = {"Gate": "-12.0"}
    assert any("is not a value « Gate » shows" in e for e in R.check_draft(d, SHEET))


def test_chaque_configuration_est_complete_et_n_herite_de_rien():
    configs, tests = R.plan(draft(), SHEET)
    names = [c["name"] for c in configs]
    assert names == ["quiet", "on-logos", "on-amp", "off-amp", "part-cab", "part-cab-half", "on-reverb"]
    keys = set(configs[0]["set"])
    assert all(set(c["set"]) == keys for c in configs)              # toutes les clés, à chaque rendu
    quiet = configs[0]["set"]
    assert quiet["Logos Active"] == "Inactive" and quiet["Reverb Active"] == "Inactive" and quiet["Time Active"] == "Inactive"
    on_rev = dict(configs[-1]["set"])
    assert on_rev["Reverb Active"] == A and on_rev["Time Active"] == A   # la SECTION est rallumée avec l'interrupteur
    assert configs[5]["gain"] == 0.5


def test_les_verdicts_suivent_la_mesure():
    still = sig()
    renders = {"quiet": still, "on-logos": [v * 1.8 for v in still],     # audible mais ne bouge pas : rejeté
               "on-amp": [v * 2 for v in still], "off-amp": still,      # audible et stable : vérifié
               "part-cab": still, "part-cab-half": sig(gain=0.5),        # linéaire : vérifié
               "on-reverb": sig(tail=True)}                              # une queue : vérifié
    configs, tests = R.plan(draft(), SHEET)
    verified, rejected, declared, measures = R.judge(tests, renders)
    assert set(verified) == {"amp", "cab", "reverb"}
    assert [r["id"] for r in rejected] == ["logos"]
    assert rejected[0]["why"] == "doesn't move the sound: it could be captured"
    assert "amp:nature" in declared


def test_un_element_capture_inaudible_avec_ces_reglages_n_est_pas_rejete():
    """L'EQ de d'une suite d'ampli, réglé à plat : allumé ou coupé, le même son au bit près. Il n'est pas faux, il est inaudible ici."""
    still = sig()
    renders = {"quiet": still, "on-logos": sig(moving=True), "on-amp": still, "off-amp": still,
               "part-cab": still, "part-cab-half": sig(gain=0.5), "on-reverb": sig(tail=True)}
    _c, tests = R.plan(draft(), SHEET)
    verified, rejected, declared, _m = R.judge(tests, renders)
    assert "amp" not in verified and all(r["id"] != "amp" for r in rejected)
    assert "amp:inaudible with your settings" in declared


def test_un_baffle_qui_n_est_pas_lineaire_est_rejete():
    renders = {"quiet": sig(), "on-logos": sig(moving=True), "on-amp": [v * 2 for v in sig()], "off-amp": sig(),
               "part-cab": [math.tanh(3 * v) for v in sig()], "part-cab-half": [math.tanh(3 * v) for v in sig(gain=0.5)],
               "on-reverb": sig(tail=True)}
    _c, tests = R.plan(draft(), SHEET)
    verified, rejected, _d, _m = R.judge(tests, renders)
    assert "logos" in verified                                            # il bouge : il bloque à raison
    assert [r["id"] for r in rejected] == ["cab"] and "not linear" in rejected[0]["why"]


def test_un_banc_muet_n_est_jamais_un_rejet(monkeypatch):
    """Le job 3 de d'une suite d'ampli : bruit de fond seul. Une seconde mesure ; muette encore -> « pas pu mesurer », pas `rejected`."""
    import random
    noise = [random.gauss(0, 1e-7) for _ in range(N)]
    renders = {"quiet": noise, "on-logos": noise, "on-amp": noise, "off-amp": noise,
               "part-cab": [0.0] * N, "part-cab-half": [0.0] * N, "on-reverb": noise}
    calls = []
    monkeypatch.setattr(R, "render_many", lambda *a, **k: calls.append(1) or renders)
    with pytest.raises(RuntimeError, match="no signal"):
        R.verify(draft(), SHEET, "VST3: X (Y)", "chunk", work=None, retry_s=0)
    assert len(calls) == 2
    good = {"quiet": sig(), "on-logos": sig(moving=True), "on-amp": [v * 2 for v in sig()], "off-amp": sig(),
            "part-cab": sig(), "part-cab-half": sig(gain=0.5), "on-reverb": sig(tail=True)}
    seq = iter([renders, good])
    monkeypatch.setattr(R, "render_many", lambda *a, **k: next(seq))
    assert R.verify(draft(), SHEET, "VST3: X (Y)", "chunk", work=None, retry_s=0)["status"] == "verified"


def test_si_le_calme_bouge_encore_toute_la_recette_tombe(monkeypatch):
    renders = {"quiet": sig(moving=True), "on-logos": sig(moving=True), "on-amp": sig(), "off-amp": sig(),
               "part-cab": sig(), "part-cab-half": sig(gain=0.5), "on-reverb": sig(tail=True)}
    monkeypatch.setattr(R, "render_many", lambda *a, **k: renders)
    res = R.verify(draft(), SHEET, "VST3: X (Y)", "chunk", work=None)
    assert res["status"] == "rejected"
    assert res["rejected"][0]["id"] == "full"
