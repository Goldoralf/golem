# SPDX-License-Identifier: GPL-3.0-or-later
"""Bloc vital sous Windows : Vitalium (LV2, PawPaw) installé par GoleM, preset .vital posé par le chunk.

Mesuré le 2026-10-03 sur REAPER 7.27 / Vitalium PawPaw 1.1 : un LV2 n'a pas de vst_chunk ; un preset LV2
chargé par TrackFX_SetPreset n'applique QUE les ports ; l'état binaire seul est écrasé par les ports, que
l'hôte possède. Seul le chunk de piste avec les ports ET l'état rend le .vital entier (0 paramètre
différent, wavetables et modulations identiques). Ces tests gardent la conversion et le câblage."""
import base64
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bridge import vital  # noqa: E402


def _vital_file(tmp_path, settings, name="t.vital"):
    p = tmp_path / name
    p.write_bytes(json.dumps({"preset_name": "T", "settings": settings}).encode() + b"\x00")
    return str(p)


def test_la_table_couvre_les_ports_et_ses_bornes_sont_lues():
    ports = vital.lv2_ports()
    assert len(ports) == 772                                   # tous les ports de paramètre de vitalium.ttl
    assert ports["volume"] == ("volume", 0.0, 7399.4404296875)
    assert ports["polyphony"] == ("polyphony", 1.0, 32.0)
    assert ports["reverb_switch"][0] == "reverb_on"
    assert ports["envelope_1_attack"][0] == "env_1_attack"     # un nom de port n'est PAS l'id Vital
    assert all(hi > lo for _, lo, hi in ports.values())


def test_l_etat_lv2_normalise_borne_et_garde_le_json(tmp_path):
    f = _vital_file(tmp_path, {"volume": 1849.86010742, "polyphony": 99, "reverb_on": 1.0,
                               "wavetables": [{"name": "Sine"}]})
    txt = vital.lv2_state(f)
    p = dict(l.split()[1:] for l in txt.splitlines() if l.startswith("P "))
    assert abs(float(p["volume"]) - 0.25) < 1e-6               # linéaire, vérifié au plugin à 0,25
    assert p["polyphony"] == "1"                               # hors bornes -> borné
    assert p["reverb_switch"] == "1"
    assert "chorus_switch" not in p                            # absent du .vital -> défaut de l'instance
    b64 = "".join(l[2:] for l in txt.splitlines() if l.startswith("B "))
    raw = base64.b64decode(b64)
    assert raw.endswith(b"}\x00")                              # le JSON + UN NUL, comme Vitalium le sérialise
    assert json.loads(raw[:-1])["settings"]["wavetables"] == [{"name": "Sine"}]


def test_un_booleen_n_est_pas_une_valeur(tmp_path):
    f = _vital_file(tmp_path, {"volume": True})
    assert not any(l.startswith("P volume ") for l in vital.lv2_state(f).splitlines())


def test_la_compile_ecrit_les_deux_etats():
    src = open(os.path.join(ROOT, "bridge", "compile_rig.py"), encoding="utf-8").read()
    assert 'b["vitalium_state"] = fl' in src and "_vital.lv2_state(vf)" in src
    assert 'b["vital_chunk"] = fn' in src                      # le VST3 (Vital officiel) reste


def test_golem_rig_choisit_selon_le_moteur_pose():
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    assert "local function chunk_set_vitalium(" in lua
    assert re.search(r'eft:find\("LV2"\).*?chunk_set_vitalium', lua, re.S)
    # le moteur d'un bloc vital n'est jamais le note-zone JS — ni à la matérialisation, ni en scène
    assert lua.count("instrument_engine(tr, fxs)") >= 3
    assert 'ft:find("VST") then engine = fi end' not in lua
    # un changement de preset Vitalium change la signature (sinon REUSE : son inchangé)
    assert '"|lh:"' in lua


def test_windows_le_bloc_vital_n_est_plus_refuse():
    win = json.load(open(os.path.join(ROOT, "library", "catalog", "effects-windows.json"), encoding="utf-8"))
    assert "vital" not in win["effects"]                       # strict = un seul nom : on veut Vital PUIS Vitalium
    assert win["unmapped"]["vital"]["family"] == "installed-plugin"
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    alias = re.search(r'^\s*vital\s*=\s*\{([^}]*)\}', lua, re.M).group(1)
    assert re.findall(r'"([^"]+)"', alias) == ["VST3i:Vital", "VST3i:Vitalium", "Vitalium"]


def test_l_installeur_pose_vitalium_et_propose_vital():
    pins = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json")))
    assert re.fullmatch(r"[0-9a-f]{64}", pins["pawpaw"]["sha256"])
    assert pins["pawpaw"]["url"].startswith("https://github.com/DISTRHO/PawPaw/")
    ps1 = open(os.path.join(ROOT, "provision", "windows", "install-system.ps1"), encoding="utf-8-sig").read()
    assert "[switch]$Vitalium" in ps1 and "LvBundle 'vitalium.lv2'" in ps1
    win = open(os.path.join(ROOT, "installer", "platform_windows.py"), encoding="utf-8").read()
    assert '"-Avldrums", "-Vitalium", "-Sfizz"' in win                # sfizz : piano Keys + kits SFZ (2026-10-11)
    assert "def vital_status(" in win and '"vital": True' in win
    srv = open(os.path.join(ROOT, "installer", "server.py"), encoding="utf-8").read()
    assert '"/api/vital"' in srv and 'hasattr(P, "vital_status")' in srv
    js = open(os.path.join(ROOT, "installer", "ui", "installer.js"), encoding="utf-8").read()
    assert "Download Vital from vital.audio" in js


def test_les_bibliotheques_disent_vitalium_sous_windows():
    comps = {c["id"]: c for c in json.load(open(os.path.join(ROOT, "provision", "components.json"),
                                                encoding="utf-8"))["components"]}
    assert comps["vitalium"]["check_win"]["glob"] == ["%CommonProgramFiles%/LV2/vitalium.lv2"]
    assert comps["avldrums"]["check_win"]["glob"] == ["%CommonProgramFiles%/LV2/avldrums.lv2"]
