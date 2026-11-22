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
    assert r["ok"] and r["file"].replace("\\", "/").endswith("recordings/perf-new/DI-Sandbox-Input-2.wav")   # Windows : « \\ »
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


# ── l'essai d'un job sans golem.fm, les références, la DI choisie, les démos au repos (2026-11-18) ─────────────
def test_l_essai_d_un_job_note_ses_envois_au_lieu_de_les_faire(monkeypatch):
    from bridge import tones_jobs as J, tones_sync as TS

    def handler(job):
        assert TS._req("POST", "/api/ext/tones/assets?sha256=x&filename=a.opus", raw_file=__file__) == (200, {})
        assert TS._req("POST", f"/api/ext/tones/jobs/{job['id']}/progress", body={"scene": "A"}) == (200, {})
        return {"done": True}
    monkeypatch.setitem(J._HANDLERS, "fake-render", handler)
    r = J.try_job({"action": "fake-render"})
    assert r["ok"] and r["ack"] == {"done": True} and [s["path"] for s in r["sent"]] == \
        ["/api/ext/tones/assets", "/api/ext/tones/jobs/try/progress"] and r["sent"][0]["bytes"] > 0
    assert TS._DRY is None                                           # un vrai job, après, envoie pour de bon
    monkeypatch.setitem(J._HANDLERS, "fake-refused", lambda job: (_ for _ in ()).throw(RuntimeError("rack is in gig mode")))
    assert J.try_job({"action": "fake-refused"}) | {"seconds": 0} == {"ok": False, "error": "rack is in gig mode", "sent": [], "seconds": 0}
    assert "unknown action" in J.try_job({"action": "nope"})["error"] and TS._DRY is None


def test_les_references_disent_ce_qui_est_jouable(tmp_path, monkeypatch):
    from bridge import preview as PV
    monkeypatch.setattr(C, "DI_REFS_DIR", str(tmp_path))
    (tmp_path / "guitar").mkdir()
    (tmp_path / "guitar" / "clean.flac").write_bytes(b"x")
    (tmp_path / "index.json").write_text(json.dumps({"refs": {
        "guitar/clean": {"file": "guitar/clean.flac", "name": "Clean chords"},
        "voice/male": {"file": "voice/male.wav", "name": "Male"},
        "keys/piano": {"file": "keys/piano.mid", "kind": "midi"}}}))
    by = {r["id"]: r for r in PV.refs_list()}
    assert by["guitar/clean"] == {"id": "guitar/clean", "role": "guitar", "name": "Clean chords", "kind": "audio", "available": True}
    assert by["voice/male"]["available"] is False and by["keys/piano"]["kind"] == "midi"


def test_la_di_choisie_est_gardee_avec_la_demo_et_l_automatique_l_efface(tmp_path, monkeypatch):
    from bridge import preview as PV
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path))
    d = tmp_path / "patch-mine-in2"
    d.mkdir()
    (d / "preview.json").write_text(json.dumps({"ref": "guitar/djent", "scenes": {"A": "x"}}))
    monkeypatch.setitem(PV._ST, "phase", "done")
    PV._remember_choice("patch:mine", "2", "guitar/djent")
    assert json.load(open(d / "preview.json"))["chosen"] == "guitar/djent"
    PV._remember_choice("patch:mine", "2", None)
    assert "chosen" not in json.load(open(d / "preview.json"))
    monkeypatch.setitem(PV._ST, "phase", "error")                    # un rendu raté ne change rien
    PV._remember_choice("patch:mine", "2", "guitar/lead")
    assert "chosen" not in json.load(open(d / "preview.json"))


def test_au_repos_seuls_les_patchs_de_l_utilisateur_sans_demo_a_jour_sont_rendus(monkeypatch):
    from bridge import factory, patches as P, preview as PV
    monkeypatch.setattr(P, "list_patches", lambda: [{"id": "fac", "role": "guitar"}, {"id": "pads", "role": "pads"},
                                                    {"id": "nocard", "role": "bass"}, {"id": "fresh", "role": "guitar"},
                                                    {"id": "novoice", "role": "voice"}, {"id": "stale", "role": "guitar"}])
    monkeypatch.setattr(factory, "mark", lambda kind, lst: [dict(x, factory=(x["id"] == "fac")) for x in lst])
    monkeypatch.setattr(PV, "patch_input", lambda pid: None if pid == "nocard" else "2")
    monkeypatch.setattr(PV, "patch_preview", lambda pid: {"chosen": "guitar/lead"} if pid == "stale" else None)
    seen = []

    def plan(pid, in_key="1", ref=None, **kw):
        seen.append((pid, in_key, ref))
        return "reference DI missing: voice/male (record it first)" if pid == "patch:novoice" else {"id": pid}
    monkeypatch.setattr(PV, "plan", plan)
    monkeypatch.setattr(PV, "_up_to_date", lambda pl: pl["id"] == "patch:fresh")
    monkeypatch.setattr(PV, "_IDLE_PATCH", {"failed": {}, "done": 0, "current": None})
    assert PV.idle_patch_pending() == ("stale", "2", "guitar/lead")          # avec SA référence choisie
    assert [s[0] for s in seen] == ["patch:fresh", "patch:novoice", "patch:stale"]   # ni l'usine, ni les pads, ni sans entrée
    # un rendu raté n'est pas réessayé avant le redémarrage
    monkeypatch.setattr(PV, "generate", lambda *a, **k: PV._ST.update(phase="error", error="engine busy"))
    assert PV.idle_patch_tick(1) is True and PV._IDLE_PATCH["failed"] == {"stale": "engine busy"}
    assert PV.idle_patch_pending() is None and PV.idle_patch_tick(2) is False
