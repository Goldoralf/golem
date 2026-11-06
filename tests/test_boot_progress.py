# SPDX-License-Identifier: GPL-3.0-or-later
"""L'écran de chargement date des FAITS (bridge/boot_progress.py, maquette mockups/loading.html, 2026-10-11)."""
import json
import types

import pytest

from bridge import boot_progress as BP


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(BP, "LAST_PATH", str(tmp_path / ".boot.json"))
    BP.reset("test", needs_preset=True)
    yield
    BP.reset("test", needs_preset=True)


def _st(**k):
    d = dict(reaper_running=False, reaper_connected=False, audio={}, midi={}, preset_id=None, rig_loading=None)
    d.update(k)
    return types.SimpleNamespace(**d)


def test_les_transitions_sont_datees_une_fois_et_le_preset_conclut(fresh, monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr(BP.time, "time", lambda: clock["t"])
    BP.reset("test", needs_preset=True)                         # t0 = 100
    BP.observe(_st())
    assert BP.doc()["steps"] == {} and BP.doc()["done"] is None
    clock["t"] = 102.0; BP.observe(_st(reaper_running=True))
    clock["t"] = 106.4; BP.observe(_st(reaper_running=True, reaper_connected=True))
    clock["t"] = 108.0; BP.observe(_st(reaper_running=True, reaper_connected=True, audio={"ok": True}, midi={"ok": True}))
    clock["t"] = 109.0; BP.observe(_st(reaper_running=True, reaper_connected=True, audio={"ok": True}, midi={"ok": True}))
    d = BP.doc()
    assert d["steps"] == {"reaper": 102.0, "osc": 106.4, "audio": 108.0, "midi": 108.0}   # datées à la PREMIÈRE fois
    assert d["done"] is None                                      # le preset n'a pas encore joué
    clock["t"] = 111.5; BP.preset_done(True)
    d = BP.doc()
    assert d["done"] == 111.5 and d["steps"]["preset"] == 111.5 and d["last_took"] == 11.5
    assert json.load(open(BP.LAST_PATH))["last_took"] == 11.5    # la référence du prochain démarrage


def test_la_carte_ne_compte_qu_apres_le_lien_osc_et_un_echec_est_dit(fresh):
    BP.observe(_st(reaper_running=True, audio={"ok": True}))     # audio « ok » sans OSC : un vieux drapeau, pas une carte
    assert "audio" not in BP.doc()["steps"]
    BP.fail("REAPER did not start within 60 s")
    assert BP.doc()["failed"] == "REAPER did not start within 60 s" and BP.doc()["done"] is None


def test_apres_un_restart_le_golem_joue_des_que_la_carte_revient(fresh):
    BP.reset("restart")                                           # pas de bank 00 à rappeler : le preset est connu
    BP.observe(_st(reaper_running=True, reaper_connected=True, audio={"ok": True}, preset_id="paper-kite"))
    assert BP.doc()["done"] is not None and BP.doc()["why"] == "restart"
    BP.reset("restart")
    BP.observe(_st(reaper_running=True, reaper_connected=True, audio={"ok": True}, preset_id="paper-kite", rig_loading={"slot": 0}))
    assert BP.doc()["done"] is None                               # un preset en cours de chargement : on attend


def test_le_lien_golem_fm_est_date_quand_il_s_ouvre(fresh, monkeypatch):
    from bridge import follow_uplink
    monkeypatch.setattr(follow_uplink, "LINKED", {"ok": True, "t": 1.0})
    BP.observe(_st())
    assert "fm" in BP.doc()["steps"]


def test_fini_attend_la_carte_quand_la_bank_00_arrive_avant_la_telemetrie(fresh, monkeypatch):
    """/live arrivait avec « ⚠ No sound card » : le preset était rappelé avant la lecture de golem_clock."""
    clock = {"t": 200.0}
    monkeypatch.setattr(BP.time, "time", lambda: clock["t"])
    BP.reset("test", needs_preset=True)
    clock["t"] = 206.0; BP.observe(_st(reaper_running=True, reaper_connected=True))
    clock["t"] = 207.5; BP.preset_done(True)                         # bank 00 rappelée, carte pas encore lue
    assert BP.doc()["done"] is None and BP.doc()["steps"]["preset"] == 207.5
    clock["t"] = 208.4; BP.observe(_st(reaper_running=True, reaper_connected=True, audio={"ok": True}))
    assert BP.doc()["done"] == 208.4                                  # la carte lue : le golem joue


def test_golem_fm_revenu_apres_le_demarrage_eteint_la_pastille(fresh, monkeypatch):
    """2026-10-11 : golem.fm démarré APRÈS le chargement — « Paired — device token valid », mais la pastille
    des onglets Settings restait : `services.fm.ok` n'était suivi qu'avant « done »."""
    from bridge import follow_uplink
    monkeypatch.setattr(follow_uplink, "LINKED", {"ok": False, "t": None})
    BP.observe(_st(reaper_running=True, reaper_connected=True, audio={"ok": True}))
    BP.preset_done()
    assert BP.doc()["done"] and BP.doc()["services"]["fm"]["ok"] is False
    follow_uplink.LINKED["ok"] = True                            # le serveur local est lancé, l'uplink se rouvre
    BP.observe(_st())
    assert BP.doc()["services"]["fm"]["ok"] is True
    follow_uplink.LINKED["ok"] = False                           # et retombe : la pastille revient
    BP.observe(_st())
    assert BP.doc()["services"]["fm"]["ok"] is False
