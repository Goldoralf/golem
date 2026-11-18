# SPDX-License-Identifier: GPL-3.0-or-later
"""« Record your own DI » (bridge/di_record.py, job `di-record`, validé par le mainteneur le 2026-11-18) : une prise
courte du signal sec d'UNE entrée, en « Tracks + DI » forcé le temps de la prise, rien gardé sur le rack. Ici le moteur
est simulé : la vraie prise se prouve sur le rack."""
import json
import os

import pytest

from bridge import config as C
from bridge import di_record as DR


@pytest.fixture
def rack(tmp_path, monkeypatch):
    presets, rec = tmp_path / "presets", tmp_path / "recordings"
    presets.mkdir()
    rec.mkdir()
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "PRESETS_DIR", str(presets))
    monkeypatch.setattr(DR, "refusal", lambda state: None)
    (presets / ".perf.json").write_text(json.dumps({"recording": False, "file": "recordings/perf-old"}))
    (presets / ".perfsrc.json").write_text(json.dumps({"in1": True, "in2": True, "mode": "mix", "mix": True}))
    log = []

    def engine(cmd):
        """Le moteur : au départ il lit les sources et se dit en prise ; à l'arrêt il écrit la piste sèche demandée."""
        log.append(cmd)
        if cmd["on"]:
            log.append(("sources", json.load(open(presets / ".perfsrc.json"))))
            (presets / ".perf.json").write_text(json.dumps({"recording": True, "file": ""}))
        else:
            src = next(x[1] for x in log if isinstance(x, tuple))
            d = rec / "perf-new"
            d.mkdir(exist_ok=True)
            for k, v in src.items():
                if k.startswith("in") and v and src["mode"] == "tracks_di":
                    (d / f"DI-Sandbox-Input-{k[2:]}.wav").write_bytes(b"R" * 4096)
            (presets / ".perf.json").write_text(json.dumps({"recording": False, "file": "recordings/perf-new"}))
    return {"presets": presets, "rec": rec, "engine": engine, "log": log}


def test_la_prise_force_tracks_di_sur_la_seule_entree_puis_rend_le_reglage(rack):
    restored = []
    r = DR.record(2, 5, state=object(), write_command=rack["engine"], restore=lambda: restored.append(1), sleep=lambda s: None)
    assert r["ok"] and r["file"].endswith("recordings/perf-new/DI-Sandbox-Input-2.wav")
    src = next(x[1] for x in rack["log"] if isinstance(x, tuple))
    assert src["mode"] == "tracks_di" and src["mix"] is False and src["in2"] is True and src["in1"] is False   # elle seule
    assert [c["on"] for c in rack["log"] if isinstance(c, dict)] == [True, False] and restored == [1]
    assert DR.STATE["running"] is False


def test_les_refus_se_disent_et_rien_ne_part(rack, monkeypatch):
    sent = []
    assert "between 3 and 30" in DR.record(1, 60, state=object(), write_command=sent.append)["error"]
    assert "no input 0" in DR.record(0, 5, state=object(), write_command=sent.append)["error"]
    monkeypatch.setattr(DR, "refusal", lambda state: "a take is recording — try after it")
    assert DR.record(1, 5, state=object(), write_command=sent.append)["error"] == "a take is recording — try after it"
    assert sent == [] and json.load(open(rack["presets"] / ".perfsrc.json"))["mode"] == "mix"   # le réglage n'a pas bougé


def test_une_entree_qui_ne_donne_rien_est_dite(rack, monkeypatch):
    monkeypatch.setattr(DR, "_wait", lambda pred, secs, step=0.15: pred())
    # le moteur n'écrit que l'entrée demandée ; on en demande une qu'il « n'a pas » en la retirant après coup
    def engine(cmd):
        rack["engine"](cmd)
        if not cmd["on"]:
            os.remove(rack["rec"] / "perf-new" / "DI-Sandbox-Input-3.wav")
    r = DR.record(3, 5, state=object(), write_command=engine, sleep=lambda s: None)
    assert r["ok"] is False and "nothing was recorded from input 3" in r["error"] and r["folder"].endswith("perf-new")


def test_seul_le_dossier_de_la_prise_peut_etre_retire(rack, tmp_path):
    d = rack["rec"] / "perf-new"
    d.mkdir()
    (d / "x.wav").write_bytes(b"x")
    keep = rack["rec"] / "song-of-mine"
    keep.mkdir()
    assert DR.discard(str(keep), recordings=str(rack["rec"])) is False and keep.is_dir()        # pas un dossier de prise
    assert DR.discard(str(tmp_path), recordings=str(rack["rec"])) is False                       # hors de recordings/
    assert DR.discard(str(rack["rec"] / ".." / "presets"), recordings=str(rack["rec"])) is False
    assert DR.discard(str(d), recordings=str(rack["rec"])) is True and not d.exists()


def test_le_job_refuse_un_decompte_et_demande_une_entree():
    from bridge import tones_jobs as J
    with pytest.raises(RuntimeError, match="count-in is not available yet"):
        J._di_record({"action": "di-record", "in_key": "1", "max_s": 5, "count_in": 1})
    with pytest.raises(RuntimeError, match="in_key or person required"):
        J._di_record({"action": "di-record", "max_s": 5})
    assert "di-record" in J._HANDLERS
