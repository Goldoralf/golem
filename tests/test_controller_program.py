# SPDX-License-Identifier: GPL-3.0-or-later
"""Donner aux pads leur propre canal (bridge/controller_program.py) et trier par canal (bridge/controllers.py) : le
modèle est une DONNÉE (config/controller-models/), seuls le canal des pads et leurs notes changent, et un contrôleur
dont on ne connaît pas les canaux garde « tous canaux »."""
import json

from bridge import controller_program as P, controllers as K, devices

# le programme 1 tel que l'AKAI MPK Mini Mk II du mainteneur l'a rendu le 2026-10-13 (pads canal 1, banques 44-51 / 32-39)
PROG1 = bytes.fromhex(
    "f047002667006d01000004000004000000030078000000010201012c0014012d0115012e0216012f031701300418013105190132061a0133"
    "071b0120081c0121091d01220a1e01230b1f01240c2001250d2101260e2201270f230101007f02007f03007f04007f05007f06007f07007f"
    "08007f0cf7")


def _mpk():
    m = P.model_for("09e8:0045", "")
    assert m and P.can_program(m), "le descripteur de l'AKAI MPK Mini Mk II est livré"
    return m


def test_le_modele_se_trouve_par_usb_ou_par_nom():
    assert P.model_for("09e8:0045")["id"] == "akai-mpk-mini-mk2"
    assert P.model_for("", "AKAI MPK Mini Mk II")["id"] == "akai-mpk-mini-mk2"     # le nom long du registre
    assert P.model_for("", "MPK Mini Mk II")["id"] == "akai-mpk-mini-mk2"          # le nom court d'ALSA
    assert P.model_for("1234:5678", "Arturia MiniLab") is None


def test_le_dump_se_lit_comme_l_a_mesure_la_piste_d_ecoute():
    p = P.decode(_mpk(), PROG1)
    assert p["prog"] == 1 and p["pad_ch"] == 1 and p["key_ch"] == 1
    assert p["notes"] == list(range(44, 52)) + list(range(32, 40))


def test_la_cible_ne_change_que_le_canal_des_pads_et_leurs_notes():
    m = _mpk()
    sp = m["program"]
    out = P.patched(m, PROG1)
    assert len(out) == sp["length"] and out[sp["command_at"]] == sp["command_load"]
    p = P.decode(m, out)
    from bridge import kits
    assert p["pad_ch"] == 10 and p["key_ch"] == 1 and p["notes"] == list(kits.DEFAULT_NOTES)   # GM, placement MPC
    assert P.is_target(m, out) and not P.is_target(m, PROG1)
    allowed = {sp["command_at"], sp["pad_channel_at"]} | {sp["pad_notes"]["at"] + i * sp["pad_notes"]["stride"] for i in range(16)}
    touched = {i for i in range(len(out)) if out[i] != PROG1[i]}
    assert touched <= allowed, f"octets touchés hors cible : {sorted(touched - allowed)}"
    assert P.patched(m, PROG1, 0)[sp["prog_at"]] == 0                               # la mémoire de travail


def test_un_dump_qui_n_est_pas_ce_modele_est_refuse():
    for bad in (PROG1[:-1], b"\xf0\x41\x10" + PROG1[3:], b""):
        try:
            P.decode(_mpk(), bad)
        except ValueError:
            continue
        raise AssertionError("dump invalide accepté")


def test_seuls_des_canaux_connus_et_distincts_trient_la_lane(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "DIR", str(tmp_path / "controllers"))
    monkeypatch.setattr(K, "KNOBS_JSON", str(tmp_path / "knobs.json"))
    monkeypatch.setattr(devices, "known", lambda: {"09e8:0045": {"name": "AKAI MPK Mini Mk II", "usb": "09e8:0045"}})
    monkeypatch.setattr(devices, "_save", lambda d: None)
    monkeypatch.setattr(devices, "detected", lambda: [{"name": "MPK Mini Mk II", "usb": "09e8:0045", "hw": "hw:II", "kind": "midi"}])
    assert K.channels_for("hw:II") is None                                          # rien de connu : tous canaux
    K.set_channels("09e8:0045", "AKAI MPK Mini Mk II", 1, 1)
    assert K.channels_for("hw:II") is None                                          # même canal : aucun tri possible
    prof = K.set_channels("09e8:0045", "AKAI MPK Mini Mk II", 1, 10, list(range(36, 52)))
    assert K.channels_for("hw:II") == {"keys": 1, "pads": 10}
    assert K.channels_for("hw:Autre") is None
    assert not prof.get("calibrated"), "les canaux seuls ne se font pas passer pour une calibration"
    assert not (tmp_path / "knobs.json").exists(), "les canaux seuls n'écrivent pas knobs.json"
    assert K.all_channels() and K.all_channels()[0][1:] == (1, 10)
    K.save({"usb": "09e8:0045", "name": "AKAI MPK Mini Mk II", "keys": {"lo": 48, "hi": 72}})   # recalibré, pads sautés
    assert K.channels_for("hw:II") == {"keys": 1, "pads": 10}, "une calibration sans mesure garde les canaux"


def test_chaque_descripteur_livre_est_coherent():
    for m in P.models():
        sp = m.get("program") or {}
        if sp.get("kind") != "sysex-dump":
            continue
        n = sp["length"]
        idx = [sp["command_at"], sp["prog_at"], sp["pad_channel_at"], sp["key_channel_at"]]
        idx += [sp["pad_notes"]["at"] + i * sp["pad_notes"]["stride"] for i in range(sp["pad_notes"]["count"])]
        assert all(0 < i < n - 1 for i in idx), f"{m['id']} : un octet hors du programme"
        assert len(set(idx)) == len(idx), f"{m['id']} : deux champs au même octet"
        req = P.read_request(m, 1)
        assert req[0] == 0xF0 and req[-1] == 0xF7, f"{m['id']} : la demande de lecture n'est pas un SysEx"
        json.dumps(m)
