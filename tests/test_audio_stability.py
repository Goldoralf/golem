# SPDX-License-Identifier: GPL-3.0-or-later
"""Le buffer qui tient sur cette machine (docs/health.md §2 bis) : la mesure garde le plus petit buffer sans cycle en
retard, le dit pour les plus petits, et l'étape `stability` du first check ne fait échouer le bilan que si même le
plus grand claque."""
import pytest

from bridge import audio_stability as S
from bridge import config as C
from bridge import first_check as FC


class FakeEngine:
    """Un moteur dont chaque taille produit un nombre fixe de cycles en retard par écoute."""
    id = "ardour"
    BUFFERS = (32, 64, 96, 128, 192, 256, 384, 512, 1024)

    def __init__(self, late_per_size):
        self.late_per_size, self.buffer, self.count, self.sets = late_per_size, 256, 0, []

    def set_buffer(self, n):
        self.buffer = n
        self.count = 0                                   # le compteur repart de zéro à l'ouverture du flux
        self.sets.append(n)

    def audio(self):
        return {"buffer": self.buffer}

    def _status(self):
        return {"late_cycles": self.count, "buffer": self.buffer, "sample_rate": 48000,
                "latency_in": self.buffer + 72, "latency_out": self.buffer + 104}

    def tick(self, _s):                                  # sleep() : une écoute ajoute les clics de la taille
        self.count += self.late_per_size.get(self.buffer, 0)


def test_le_plus_petit_buffer_sans_clic_est_garde():
    eng = FakeEngine({64: 812, 128: 4, 256: 0})
    r = S.measure(eng, S.plan(eng), sleep=eng.tick)
    assert r["ok"] is True and r["buffer"] == 256 and eng.buffer == 256
    assert r["tried"] == [(64, 812), (128, 4), (256, 0)]           # la mise en place n'est pas comptée, l'écoute oui
    assert eng.sets == [64, 128, 256], "on s'arrête à la première taille qui tient"
    assert r["latency_ms"] == round((256 + 72 + 256 + 104) / 48000 * 1000, 1)


def test_meme_le_plus_grand_claque_on_le_garde_et_on_le_dit():
    eng = FakeEngine({n: 3 for n in S.CANDIDATES})
    r = S.measure(eng, S.plan(eng), sleep=eng.tick)
    assert r["ok"] is False and r["buffer"] == 1024 and len(r["tried"]) == 5


def test_un_moteur_sans_compteur_n_est_pas_mesure():
    class Reaper:
        id = "reaper"
    assert S.measurable(Reaper()) is False
    eng = FakeEngine({})
    eng._status = lambda: {"buffer": 256}                           # un moteur d'avant le patch 16
    assert S.measurable(eng) is False


@pytest.fixture
def rack(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    (tmp_path / "presets").mkdir()
    return tmp_path


def test_l_etape_stability_et_le_bilan(rack):
    for s in FC.STEPS:
        FC.record(s, ok=True, measured={"peak": 0.7, "heard": True})
    r = FC.record("stability", measured={"measured": True, "ok": True, "buffer": 256, "latency_ms": 14.3,
                                         "tried": [(64, 812), (128, 4), (256, 0)]})["result"]
    assert r["ok"] is True and r["tried"] == "64:812 128:4 256:0" and r["buffer"] == 256
    sec = FC.section()["steps"]["stability"]
    assert sec["buffer"] == 256 and sec["tried"] == "64:812 128:4 256:0"
    # même 1024 claque : le bilan est partiel ; non mesuré : il ne compte pas
    FC.record("stability", measured={"measured": True, "ok": False, "buffer": 1024, "tried": [(1024, 3)]})
    FC.finish()
    assert FC.status()["verdict"] == "partial"
    FC.reset()
    for s in FC.STEPS:
        FC.record(s, ok=True, measured={"peak": 0.7, "heard": True})
    FC.record("stability", measured={"measured": False})
    FC.finish()
    assert FC.status()["verdict"] in ("ok", "partial")
    assert FC.status()["steps"]["stability"]["ok"] is True
