# SPDX-License-Identifier: GPL-3.0-or-later
"""Un convolveur d'IR ne se bypasse jamais : le moteur actionne son interrupteur INTERNE.

Mesuré le 2026-09-21 (tools/check-block-stall.py --rig, IR chargée) : rallumer le convolveur x42 par
TrackFX_SetEnabled fige TOUT le moteur audio ~540 ms — c'était la coupure B->A du 2026-09-20. Son
paramètre « Enable » fait le même effet sonore en 0 à 2 ms. golem_rig ne se monte pas en test : on
lit sa source, comme test_sw5_rec_with_backing.py."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "reaper/Scripts/golem_rig.lua").read_text(encoding="utf8")


def _fn(name):
    i = SRC.index("local function " + name)
    return SRC[i:SRC.index("\nend\n", i)]


def test_fx_set_on_passe_par_l_interrupteur_interne_d_un_convolveur():
    # 2026-09-25 (docs/spectral.md) : le nom du paramètre-interrupteur vient de `switch_param_of` — « Enable »
    # pour le convolveur x42, « Freeze » pour GoleM Freeze ; fx_set_on écrit ce paramètre AVANT tout bypass.
    sw = _fn("switch_param_of")
    assert "is_ir_convolver(tr, fx)" in sw and 'return "Enable"' in sw and 'return "Freeze"' in sw
    body = _fn("fx_set_on")
    assert "switch_param_of(tr, fx)" in body and "find_param_by_name(tr, fx, pname)" in body
    assert body.index("TrackFX_SetParam") < body.rindex("TrackFX_SetEnabled(tr, fx, on)")


def test_le_convolveur_est_reconnu_meme_renomme():
    assert '"fx_name"' in _fn("is_ir_convolver")          # un cœur estampillé golem:<id> garde son nom d'origine ici


def test_les_trois_chemins_du_moteur_passent_par_fx_set_on():
    assert "fx_set_on(tr, engine_fx, not blk.bypass)" in _fn("set_block_enabled")
    core = _fn("apply_core_enabled")
    assert "fx_set_on(tr, fx, not blk.bypass)" in core and "fx_set_on(tr, ir, not blk.bypass)" in core
    assert "reaper.TrackFX_SetEnabled" not in core
    assert "fx_set_on(tr, fxs[1], grp.on)" in _fn("handle_stomp")


def test_une_branche_se_tait_par_un_mute_et_garde_son_niveau():
    """Retour au contrat (2026-09-21) : B_MUTE pour le silence, D_VOL reste le niveau (0 dB)."""
    i = SRC.index("UNE BRANCHE SE TAIT PAR UN MUTE DE PISTE")
    loop = SRC[i:SRC.index('log("scène appliquée SANS rebuild', i)]
    assert 'reaper.SetMediaTrackInfo_Value(m.tr, "B_MUTE", 1)' in loop
    assert 'SetMediaTrackInfo_Value(m.tr, "D_VOL", 0.0)' not in loop
    assert loop.index('"B_MUTE", 0') < loop.index('"B_MUTE", 1')            # rétablir d'abord, couper ensuite
    assert '"B_MUTE", (core_failed(tr) or' in SRC
    build = SRC[SRC.index('if spec.role == "branch" then\n      -- union'):]
    build = build[:build.index("    end")]
    assert '"D_VOL", 1.0' in build


def test_le_provisionnement_fige_le_traitement_des_pistes_muettes():
    src = (ROOT / "provision/reaper-ini-setup.py").read_text(encoding="utf8")
    assert re.search(r'ENGINE_FORCED = \{[^}]*"norunmute": "0"', src) and "overrides.update(ENGINE_FORCED)" in src
