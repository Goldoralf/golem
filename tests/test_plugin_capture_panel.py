# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bilan du panneau de capture (docs/plugin-capture.md §11, maquette mockups/vst-capture-panel.html).

golem ne coupe rien à la place du musicien : il NOMME ce qui empêche la capture, ce qui sera capturé, ce qui
devient un bloc golem et ce qui s'y perd. Les paramètres ci-dessous sont ceux d'une vraie suite d'ampli commerciale,
lus dans REAPER le 2026-10-10 (chorus allumé), sous un nom de plugin FICTIF : le dépôt ne livre plus de recette pour un
plugin nommé (avis de l'avocat, 2026-10-20), la recette vit dans tests/fixtures/plugin-capture-recipe.json."""
import json
from pathlib import Path

import pytest

from bridge import plugin_capture as P

PLUGIN = "VST3: Example Amp Suite (Example Vendor)"
RECIPE = json.loads((Path(__file__).parent / "fixtures/plugin-capture-recipe.json").read_text(encoding="utf-8"))["plugins"][PLUGIN]
SHOWN = {"Pitch Section Active": "Active", "WOW Active": "Inactive", "OCT Active": "Inactive",
         "Pedal Section Active": "Active", "OD Active": "Inactive", "DRT Active": "Inactive",
         "PHSR Active": "Inactive", "CHR Active": "Active", "CHR Mix": "0.39",
         "Amp Section Active": "Active", "Amp Type": "CLN Amp", "EQ Section Active": "Active",
         "Cab Section Active": "Active", "Cab 1 Mic IR": "Dynamic 57",
         "FX Section Active": "Active", "DLY Active": "Active", "DLY Mod Active": "Active", "DLY Sync Note": "1/4",
         "REV Active": "Active", "Gate Amount": "-80.0"}


@pytest.fixture
def plugin(monkeypatch):
    shown = dict(SHOWN)
    monkeypatch.setattr(P, "_live_params", lambda block: [{"name": k, "display": v} for k, v in shown.items()])
    monkeypatch.setattr(P, "environment", lambda: {"ready": True, "missing": []})
    monkeypatch.setattr(P, "recipe_for", lambda plugin: RECIPE if plugin == PLUGIN else None)
    return shown


def test_le_chorus_est_nomme_avec_sa_place_et_son_reglage(plugin):
    c = P.check("b", PLUGIN)
    assert c["ok"] is False
    assert c["blockers"] == [{"label": "Chorus", "kind": "modulation", "where": "Pedal section, before the amp",
                              "detail": "mix 39 %"}]
    assert [(x["label"], x["detail"]) for x in c["captured"]] == [("Amp", "CLN Amp"), ("EQ", None), ("Cab", "Dynamic 57")]
    assert [(x["label"], x["detail"], x["loss"]) for x in c["rebuilt"]] == [
        ("Gate", "-80.0 dB", None), ("Delay", "1/4", "its modulation is not kept"), ("Reverb", None, None)]


def test_un_effet_actif_dans_une_section_coupee_ne_bloque_pas(plugin):
    """La garde lisait l'interrupteur seul : un chorus « Active » dans une section Pedal coupée ne joue pas."""
    plugin["Pedal Section Active"] = "Inactive"
    c = P.check("b", PLUGIN)
    assert c["ok"] is True and c["blockers"] == []


def test_chorus_coupe_la_capture_est_prete_avec_ses_deux_modes(plugin):
    plugin["CHR Active"] = "Inactive"
    c = P.check("b", PLUGIN)
    assert c["ok"] is True
    assert [p["id"] for p in c["split"]] == ["head", "cab"]


def test_un_plugin_sans_recette_se_capture_apres_confirmation(plugin, monkeypatch):
    c = P.check("b", "VST3: Example Amp (Other Vendor)")
    assert c["ok"] is True and c["recipe"] is False and c["needs_confirm"] is True
    monkeypatch.setattr(P, "_job", {"state": "idle"})
    assert "Check the plugin first" in P.start("b", "VST3: Example Amp (Other Vendor)", "Patch")["error"]
    assert "cab" in P.start("b", "VST3: Example Amp (Other Vendor)", "Patch", confirmed=True)["error"]
    r = P.generic_recipe("VST3: Example Amp (Other Vendor)", "amp")
    assert r["vendor"] == "Other Vendor" and r["full"] == {"label": "The whole plugin", "gear": "amp", "off": {}}
    assert P._vendor("VST3i: BM-VOID (UJAM) (32 out)") == "UJAM"


def test_self_esr_zero_pour_un_son_fixe_et_haute_pour_un_son_qui_bouge(tmp_path):
    """Le même passage joué deux fois (signal v3) : un plugin sans effet temporel rend 0 au bit près."""
    import math
    t, n = 200, 1000
    seg = [math.sin(i * 0.3) for i in range(t)]
    fixed = seg + [0.1] * (n - 2 * t) + seg
    moving = seg + [0.1] * (n - 2 * t) + [math.sin(i * 0.3) * (1 + 0.3 * math.sin(i * 0.01)) for i in range(t)]
    P.write_wav(tmp_path / "fixed.wav", fixed)
    P.write_wav(tmp_path / "moving.wav", moving)
    assert P.self_esr(tmp_path / "fixed.wav", n, t_validate=t) == pytest.approx(0, abs=1e-12)
    assert P.self_esr(tmp_path / "moving.wav", n, t_validate=t) > P.SELF_ESR_MAX
    assert P.self_esr(tmp_path / "fixed.wav", n + 5, t_validate=t) is None        # rendu trop court : pas de verdict
