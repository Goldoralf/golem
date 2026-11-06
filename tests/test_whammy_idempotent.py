# SPDX-License-Identifier: GPL-3.0-or-later
"""La Whammy DT ne doit pas recevoir de Program Change INUTILE (coupure audio réelle).

2026-09-20, une heure avant une répète : « quand je passe de la scène A à la scène B il y a
une coupure audio qui n'est pas acceptable » — et les DEUX transitions coupaient.

La pédale est DANS le chemin du signal, et elle se tait le temps de changer de programme. La glu
whammy tourne à chaque émission, scène comprise : elle lui envoyait donc un PC à chaque changement
de scène, même quand rien ne la concernait. Aucune sonde interne à Reaper ne pouvait le voir — ni
rebuild, ni xrun, ni variation de PDC : la coupure était hors du logiciel.

`_whammy_off` avait déjà cette garde et disait pourquoi (« pas de PC inutile sur le bus, pas de
blip de pitch »). Elle manquait dans la glu.
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def glue():
    """La glu seule, avec un midi_out espionné — app.py importe Reaper, OSC et MIDI."""
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    i, j = src.index("def _whammy_dt_glue"), src.index("def _midi_pedals_glue")
    sent = []

    class MO:
        @staticmethod
        def whammy_mode(name=None, active=True):
            sent.append(("PC", name, active))

        @staticmethod
        def whammy_treadle(v):
            sent.append(("CC", v))

    class ST:
        whammy_on = False
        whammy_mode = None
        whammy_drop = None
        whammy_pedal = None

    ns = {"midi_out": MO, "state": ST, "_scene_arms_whammy": lambda: False,
          "_whammy_off": lambda: sent.append(("OFF",)),
          "rig": type("R", (), {"iter_blocks": staticmethod(lambda b: b)})}
    exec(compile(src[i:j].replace("    from . import rig\n", ""), "app.py", "exec"), ns)
    return ns["_whammy_dt_glue"], sent


def _blk(**prm):
    return [{"type": "whammy-dt", "bypass": False, "params": {"won": True, **prm}}]


def test_une_scene_qui_ne_touche_pas_la_pedale_ne_lui_parle_PAS(glue):
    g, sent = glue
    g(_blk(mode="Whammy Up 2 Oct"), force=True)
    sent.clear()
    g(_blk(mode="Whammy Up 2 Oct"))
    assert sent == [], "un PC inutile = une coupure audio réelle"
    g(_blk(mode="Whammy Up 2 Oct"))
    assert sent == []


def test_une_scene_qui_CHANGE_le_reglage_parle(glue):
    """La garde ne doit pas rendre la pédale sourde : c'est l'autre moitié du contrat."""
    g, sent = glue
    g(_blk(mode="Whammy Up 2 Oct"), force=True)
    sent.clear()
    g(_blk(mode="Whammy Down 1 Oct"))
    assert ("PC", "Whammy Down 1 Oct", True) in sent


def test_le_chargement_d_un_preset_RESYNCHRONISE(glue):
    """On ne sait pas ce que la pédale a reçu entre-temps, et un PC au chargement d'un morceau
    ne coupe rien qu'on entende — on n'est pas en train de jouer."""
    g, sent = glue
    g(_blk(mode="Whammy Up 2 Oct"), force=True)
    sent.clear()
    g(_blk(mode="Whammy Up 2 Oct"), force=True)
    assert ("PC", "Whammy Up 2 Oct", True) in sent


def test_le_treadle_ne_se_renvoie_que_s_il_BOUGE(glue):
    g, sent = glue
    g(_blk(mode="M", pedal=0), force=True)
    assert ("CC", 0) in sent
    sent.clear()
    g(_blk(mode="M", pedal=0))
    assert sent == []
    g(_blk(mode="M", pedal=64))
    assert ("CC", 64) in sent


def test_un_preset_SANS_bloc_whammy_eteint_toujours(glue):
    """Le bug du 2026-07-26 (« je change de preset et elle est toujours allumée ») ne revient pas."""
    g, sent = glue
    g([{"type": "amp"}])
    assert ("OFF",) in sent
