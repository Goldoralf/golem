# SPDX-License-Identifier: GPL-3.0-or-later
"""Le jumeau CLI de Calibration ▸ Drums (`tools/check-drums.py`, lot D4). L'analyse vit dans
bridge/drumlearn.py (tests/test_drumlearn.py) ; ici on garde ce que le CLI fait SEUL : lire aseqdump
sans se faire noyer par l'horloge, rendre le rapport sans rien arrondir, refuser une mesure d'un
ancien format, et ne pas écrire une mesure qui se contredit."""
import importlib.util
import json
import os
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def cd():
    spec = importlib.util.spec_from_file_location("check_drums", os.path.join(ROOT, "tools", "check-drums.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeProc:
    def __init__(self, lines):
        self.stdout, self.stderr = iter(lines), None

    def poll(self):
        return None

    def terminate(self):
        pass


def test_aseqdump_est_lu_sans_l_horloge_et_avec_l_heure(cd, monkeypatch):
    lines = [" 32:0   Clock\n"] * 50 + [
        " 32:0   Note on                 9, note 38, velocity 94\n",
        " 32:0   Note off                9, note 38\n",
        " 32:0   Control change          9, controller 4, value 127\n",
        " 32:0   Polyphonic aftertouch   9, note 46, value 127\n",
    ]
    monkeypatch.setattr(cd.subprocess, "Popen", lambda *a, **k: _FakeProc(lines))
    monkeypatch.setattr(cd.time, "sleep", lambda s: None)
    t = cd.AlsaTap("32:0", "Alesis Nitro")
    time.sleep(0.2)
    got = t.take()
    assert [(e["k"], e["c"], e["n"], e["v"]) for e in got] == [(1, 9, 38, 94), (2, 9, 4, 127), (3, 9, 46, 127)]
    assert got[0]["t"] <= got[1]["t"] <= got[2]["t"] and t.clock is True


def test_le_rendu_dit_les_jumeaux_les_ecarts_et_la_pedale(cd, capsys):
    from bridge import drumlearn as D
    from tests.test_drumlearn import nitro_measure
    m = nitro_measure(pedal_ok=True)
    base = json.load(open(os.path.join(ROOT, "config", "drumkits", "alesis-nitro.json"), encoding="utf8"))
    base["hihat"] = {"cc": 4, "open_value": 0, "closed_value": 127, "positions": 3, "bands": [33, 66], "notes": "distinct"}
    base["choke"] = "poly-aftertouch"
    rep = D.analyse(m)
    cd.render(rep, D.compare(rep, base), base)
    out = capsys.readouterr().out
    assert "tom1-rim      note  48  — la MÊME que tom1" in out
    assert "pédale interrupteur, aucun CC, 2 positions" in out and "le descripteur dit CC 4, 3 positions" in out
    assert "étouffement : none" in out and "le descripteur dit poly-aftertouch" in out
    assert "aftertouch reçu HORS étouffement pendant : hh-closed, hh-half, hh-splash" in out
    assert "canal 10" in out and "écart(s)" in out


def test_une_mesure_qui_se_contredit_ne_s_ecrit_pas_et_le_dit(cd, capsys, monkeypatch, tmp_path):
    """Le 23/09, « pédale seule » a rendu 46 — la note de l'ouverte. Rien ne s'écrit, on dit lesquels."""
    from bridge import drumkits
    from tests.test_drumlearn import nitro_measure
    m = nitro_measure(pedal_ok=False)
    json.dump(m, open(tmp_path / "learn.json", "w", encoding="utf8"))
    monkeypatch.setattr(cd, "OUT", str(tmp_path / "learn.json"))
    monkeypatch.setattr(drumkits, "DIR", str(tmp_path))          # aucun descripteur réel ne bouge
    monkeypatch.setattr(drumkits, "LOCAL_DIR", str(tmp_path))   # les mesures aussi : jamais config/ réel
    monkeypatch.setattr(cd.sys, "argv", ["check-drums.py", "--write", "--kit", "alesis-nitro"])
    with pytest.raises(SystemExit) as e:
        cd.main()
    out = capsys.readouterr().out
    assert "la mesure se contredit" in out and "note 46 : hh-open, hh-pedal" in out
    assert "rien n'est écrit" in str(e.value.code)
    assert not list(tmp_path.glob("*.json.bak")) and not (tmp_path / "alesis-nitro.json").exists()


def test_une_mesure_d_un_ancien_format_est_refusee(cd, monkeypatch, tmp_path):
    json.dump({"elements": {"kick": {"note": 36}}}, open(tmp_path / "old.json", "w"))
    monkeypatch.setattr(cd, "OUT", str(tmp_path / "old.json"))
    with pytest.raises(SystemExit, match="ancien format"):
        cd.load_measure()
