# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/release.py : publier pas à pas (docs/release-tool-plan.md §2). Le DÉROULÉ est testé avec des étapes factices —
reprise, réponses, arrêt sans terminal, raison obligatoire, verrou de release.sh ; aucune vraie commande ne part."""
import importlib.util
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("golem_release", os.path.join(ROOT, "tools", "release.py"))
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


@pytest.fixture
def steps(monkeypatch):
    """Quatre étapes factices à la place des vraies, dont la signature (ready_to_sign s'y arrête)."""
    calls, verdicts = [], {}

    def mk(sid, kind):
        def fn(r):
            calls.append(sid)
            return verdicts.get(sid, R.ok("fine"))
        return {"id": sid, "phase": "P", "kind": kind, "title": sid, "fn": fn}
    fake = [mk("a.check", R.CHECK), mk("b.remind", R.REMINDER), mk("c.act", R.ACTION), mk(R.SIGN_GATE, R.ACTION), mk("z.after", R.REMINDER)]
    monkeypatch.setattr(R, "STEPS", fake)
    return calls, verdicts


def _rel(tmp_path, out, interactive=False, answers=()):
    it = iter(answers)
    return R.Release("v9.9.9", records=tmp_path, out=out.append, interactive=interactive, inventory={"entities": []},
                     ask=lambda prompt: next(it), now=lambda: "T")


def test_sans_terminal_il_s_arrete_a_l_action_et_dit_la_commande(tmp_path, steps):
    calls, _ = steps
    out = []
    assert R.run(_rel(tmp_path, out)) == 1
    assert calls == ["a.check", "b.remind"]                                   # l'action n'est pas lancée sans un oui
    assert any("--yes c.act" in line for line in out)
    rec = _rel(tmp_path, []).record["steps"]
    assert rec["a.check"]["status"] == "done" and "c.act" not in rec


def test_il_reprend_la_ou_il_s_etait_arrete(tmp_path, steps):
    calls, _ = steps
    R.run(_rel(tmp_path, []))
    calls.clear()
    assert R.run(_rel(tmp_path, []), yes=["c.act"]) == 1                        # s'arrête à la signature, action suivante
    assert calls == ["c.act"]                                                  # a et b ne sont pas refaits


def test_un_echec_bloque_et_se_saute_seulement_avec_une_raison(tmp_path, steps):
    calls, verdicts = steps
    verdicts["b.remind"] = R.fail("REAPER 7.86 is out", "play it on the rig")
    out = []
    assert R.run(_rel(tmp_path, out)) == 1
    assert any("→ play it on the rig" in line for line in out) and any("--skip b.remind" in line for line in out)
    assert R.run(_rel(tmp_path, []), skip=("b.remind", "  ")) == 2              # pas de raison, pas de saut
    R.run(_rel(tmp_path, []), skip=("b.remind", "kept for the tour, played on 7.79"))
    rec = _rel(tmp_path, []).record
    assert rec["steps"]["b.remind"] == {"status": "skipped", "at": "T", "evidence": "", "reason": "kept for the tour, played on 7.79"}
    assert "b.remind skipped: kept for the tour, played on 7.79" in rec["notes"]   # la raison finit dans les notes


def test_un_rappel_fait_se_dit_par_done(tmp_path, steps):
    calls, verdicts = steps
    verdicts["b.remind"] = R.fail("play the rig")
    R.run(_rel(tmp_path, []))
    calls.clear()
    R.run(_rel(tmp_path, []), done=["b.remind"])
    assert "b.remind" not in calls and _rel(tmp_path, []).record["steps"]["b.remind"]["status"] == "done"
    assert R.run(_rel(tmp_path, []), done=["nope"]) == 2


def test_dans_un_terminal_il_pose_ses_questions(tmp_path, steps):
    calls, verdicts = steps
    verdicts["b.remind"] = R.fail("play the rig")
    out = []
    # b échoue → « d » (fait) ; c → « y » ; la signature → « n » : arrêt avant de signer
    assert R.run(_rel(tmp_path, out, interactive=True, answers=["d", "y", "n"])) == 1
    assert calls == ["a.check", "b.remind", "c.act"]
    assert R.ready_to_sign(_rel(tmp_path, []).record) == []                    # tout ce qui précède la signature est fait


def test_from_refait_a_partir_d_une_etape(tmp_path, steps):
    calls, _ = steps
    R.run(_rel(tmp_path, []), yes=["c.act"])
    calls.clear()
    R.run(_rel(tmp_path, []), start="b.remind", yes=["c.act"])
    assert calls == ["b.remind", "c.act"]


def test_le_parcours_a_blanc_n_ecrit_rien_et_ne_lance_aucune_action(tmp_path, steps):
    calls, verdicts = steps
    verdicts["a.check"] = R.fail("dirty tree")
    out = []
    assert R.run(_rel(tmp_path, out), dry=True) == 0
    assert "c.act" not in calls and "a.check" in calls and "z.after" in calls     # il va jusqu'au bout malgré l'échec
    assert not (tmp_path / "v9.9.9.json").exists()


def test_la_signature_attend_que_tout_ce_qui_precede_soit_fait(tmp_path, steps):
    rec = {"steps": {"a.check": {"status": "done"}, "b.remind": {"status": "skipped"}}}
    assert R.ready_to_sign(rec) == ["c.act"]
    rec["steps"]["c.act"] = {"status": "failed"}
    assert R.ready_to_sign(rec) == ["c.act"]
    rec["steps"]["c.act"] = {"status": "done"}
    assert R.ready_to_sign(rec) == []                                           # z.after vient après : pas exigé


def test_les_vraies_etapes_sont_dans_l_ordre_du_plan():
    ids = [s["id"] for s in R.STEPS]
    assert ids[0] == "env.repo" and ids.index("version") < ids.index("snapshot") < ids.index("pins.reaper")
    assert ids.index("checks.suite") < ids.index("rig.play") < ids.index("publish.ci") < ids.index("publish.notes") < ids.index(R.SIGN_GATE)
    assert ids.index(R.SIGN_GATE) < ids.index("after.verify") < ids.index("after.shell")
    assert len(ids) == len(set(ids)) and all(s["kind"] in (R.CHECK, R.REMINDER, R.ACTION) for s in R.STEPS)


def test_release_sh_refuse_sans_record_complet():
    sh = open(os.path.join(ROOT, "tools", "release.sh"), encoding="utf-8").read()
    i = sh.index("tools/release.py \"$TAG\" --check-record")
    assert sh.index("never move a published tag") < i < sh.index("tag -s")       # avant de signer quoi que ce soit
    assert "GOLEM_RELEASE_NO_RECORD" in sh
    r = subprocess.run(["python3", os.path.join(ROOT, "tools", "release.py"), "v0.0.0-no-such", "--check-record"],
                       capture_output=True, text=True, env={**os.environ, "HOME": "/nonexistent-home"})
    assert r.returncode == 1 and "not complete" in r.stderr


def test_le_brouillon_des_notes(tmp_path, monkeypatch):
    rel = R.Release("v9.9.9", records=tmp_path, out=lambda *_: None, interactive=False, now=lambda: "T",
                    inventory={"entities": [
                        {"id": "fx", "rows": [{"label": "Pinned · 3 OS", "value": "0.8.2", "status": "ok"}]},
                        {"id": "engine", "rows": [{"label": "Pinned · Linux", "value": "9.9-g8", "status": "ok"},
                                                  {"label": "Pinned · Windows", "value": "9.9-g8", "status": "ok"}]},
                        {"id": "reaper", "rows": [{"label": "Pinned · Linux", "value": "7.86", "status": "ok"}]}]})
    monkeypatch.setattr(rel, "previous", lambda: "v9.9.8")
    monkeypatch.setattr(rel, "git", lambda *a: "Companion: a Control mode\nTests: seven tests\nDocs: a page\nWindows: a fix"
                        if a[0] == "log" else None)
    rel.record["notes"] = ["An update brings golem-fx by itself, at the next start."]
    rel.record["steps"]["pins.third"] = {"status": "skipped", "reason": "Dexed 1.1.1 not tried yet"}
    text = R.notes_draft(rel)
    assert text.startswith("golem v9.9.9 — ")
    assert "- Companion: a Control mode" in text and "- Windows: a fix" in text and "Tests:" not in text and "Docs:" not in text
    assert "Versions: golem-fx 0.8.2, Golem Engine 9.9-g8 (Linux), 9.9-g8 (Windows), REAPER 7.86." in text
    assert "- An update brings golem-fx by itself" in text and "pins.third was skipped: Dexed 1.1.1 not tried yet" in text
    assert "Updating from v9.9.8: Settings > About > Update to v9.9.9." in text
