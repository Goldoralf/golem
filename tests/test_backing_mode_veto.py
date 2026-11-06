# SPDX-License-Identifier: GPL-3.0-or-later
"""Un mode qui coupe le backing ne charge RIEN — et surtout pas à chaque changement de scène.

Mesuré le 2026-09-21 (tools/check-scene-gap.py --listen, mode Pedalboard) : chaque scène de
« Paper Kite » était suivie, 0,7 s plus tard, d'un rechargement des six stems. La garde « déjà
chargée » lisait l'état publié par Reaper, que le moniteur ne relaie plus quand le backing est
coupé : elle ne voyait jamais rien de chargé."""

from bridge import backing as backing_mod


PRESET = {"backing": {"songs": [{"slug": "glass_lanterns_paper_kite"}]}}


def _ctl(monkeypatch):
    sent = []
    monkeypatch.setattr(backing_mod, "write_command", lambda cmd: sent.append(cmd))
    monkeypatch.setattr(backing_mod.golemfm, "is_cached", lambda slug: True)
    started = []

    class _Timer:
        def __init__(self, delay, fn):
            self.fn = fn
            self.daemon = False

        def start(self):
            started.append(self.fn)

        def cancel(self):
            pass

    monkeypatch.setattr(backing_mod.threading, "Timer", _Timer)
    return backing_mod.BackingControl(osc=None), sent, started


def test_sous_veto_rien_n_est_charge_meme_scene_apres_scene(monkeypatch):
    ctl, sent, started = _ctl(monkeypatch)
    for _ in range(3):                                   # trois changements de scène
        ctl.on_recall(PRESET, allowed=False)
    assert started == [] and sent == []


def test_sous_veto_une_chanson_deja_chargee_est_dechargee_une_fois(monkeypatch):
    ctl, sent, started = _ctl(monkeypatch)
    ctl._slug = "glass_lanterns_paper_kite"          # chargée avant le veto ; `_fb` jamais nourri
    ctl.on_recall(PRESET, allowed=False)
    ctl.on_recall(PRESET, allowed=False)
    assert [c.get("op") for c in sent] == ["unload"]


def test_permis_et_deja_charge_rien_ne_repart(monkeypatch):
    ctl, sent, started = _ctl(monkeypatch)
    ctl.set_feedback({"present": True, "slug": "glass_lanterns_paper_kite", "playing": False})
    ctl.on_recall(PRESET, allowed=True)
    assert started == [] and sent == []


def test_permis_et_absent_le_chargement_est_planifie(monkeypatch):
    ctl, sent, started = _ctl(monkeypatch)
    ctl.on_recall(PRESET, allowed=True)
    assert len(started) == 1 and sent == []
