# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/shell_release.py : la coquille vide d'une release en une commande (docs/release-tool-plan.md §3 bis, étape 6).
Ici ses parties pures : ce qui empêche de remettre une coquille, la coquille en ligne retrouvée, la remise écrite."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import shell_release as R      # noqa: E402
import shell_snapshot as S     # noqa: E402

ALL = [ex["name"] for ex in S.EXAMPLES]


def _man(tmp_path, **over):
    man = {"kind": "factory", "name": "factory", "commit": "c" * 40, "examples": list(ALL), "examples_failed": [],
           "refused": [], "failed": [], "kit_warnings": [], "rack": {"complete": True, "missing": []}, "reads": ["/api/state"],
           "catalog_version": 52, "made": "2026-11-27",
           "reference_kit": [{"what": "the reference rack", "recorded": {"commit": "4cdf4951aa"}}]}
    man.update(over)
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps(man))
    return man


def test_une_coquille_saine_n_a_aucun_probleme(tmp_path):
    _man(tmp_path)
    assert R.problems(str(tmp_path)) == []


def test_chaque_defaut_dit_quoi_refaire(tmp_path):
    _man(tmp_path, examples=[n for n in ALL if n not in ("companion-rec", "factory-health")],
         examples_failed=[{"name": "companion-rec", "route": "/app/m.html?tab=live&mode=rec", "why": "TimeoutError: anchor"}],
         refused=["/api/x"], kit_warnings=["/api/controllers .controllers: stale"], rack={"complete": False, "missing": ["fcb1010"]})
    bad = "\n".join(R.problems(str(tmp_path)))
    assert "example companion-rec failed (TimeoutError: anchor)" in bad
    assert "--section companion" in bad and "--merge-into " + str(tmp_path) in bad      # la commande exacte pour le refaire seul
    assert "refused" in bad and "reference kit: /api/controllers" in bad and "incomplete: fcb1010" in bad
    assert "examples not made: factory-health" in bad                                    # ni fait ni noté en échec : dit aussi
    _man(tmp_path, partial={"sections": ["live"]})
    assert "not a full factory snapshot" in "\n".join(R.problems(str(tmp_path)))
    _man(tmp_path, kind="smoke")
    assert "not a full factory snapshot" in "\n".join(R.problems(str(tmp_path)))
    assert R.problems(str(tmp_path / "nowhere"))[0].startswith("no SNAPSHOT.json")


def test_la_coquille_en_ligne_se_retrouve_par_son_commit(tmp_path):
    fm, work = tmp_path / "fm", tmp_path / "work"
    (fm / "frontend" / "public" / "golem-app").mkdir(parents=True)
    (fm / "frontend" / "public" / "golem-app" / "SOURCE.json").write_text(json.dumps({"commit": "4cdf4951deba74b3"}))
    assert R.online_shell(str(fm), str(work)) == ("4cdf4951deba74b3", None)               # connue, mais son instantané n'est pas ici
    pin = work / "pin-4cdf4951" / "factory"
    pin.mkdir(parents=True)
    (pin / "SNAPSHOT.json").write_text("{}")
    assert R.online_shell(str(fm), str(work)) == ("4cdf4951deba74b3", str(pin))
    assert R.online_shell(str(tmp_path / "no-fm"), str(work)) == (None, None)


def test_la_remise_dit_les_sections_les_ancres_et_les_commandes(tmp_path):
    man = _man(tmp_path)
    rep = {"added": ["new-one"], "removed": [],
           "sections": {"live": {"status": "changed", "review": ["golem-rising-live"], "added": [], "removed": [], "gone": [], "noise": []},
                        "settings/sys": {"status": "changed", "review": ["factory-health"], "added": [], "removed": [],
                                         "gone": ["health.guard"], "noise": []},
                        "songs": {"status": "unchanged", "review": [], "added": [], "removed": [], "gone": [], "noise": []}},
           "pages": {"start/phone.en.md": ["example companion-now"]}}
    text = R.handover("v9.9.9", "c" * 40, "/pins/factory", man, rep, "4cdf4951", [])
    assert text.startswith("# Empty shell v9.9.9 — handover")
    assert "| live | changed | golem-rising-live | — |" in text and "| settings/sys | changed | factory-health | health.guard |" in text
    assert "| songs | unchanged | — | — |" in text and "`start/phone.en.md`: example companion-now" in text
    assert "sync_golem_app.py %s --snapshot /pins/factory" % ("c" * 40) in text and "--no-graft" in text
    assert "NOT ready" not in text and "the reference rack (recorded at 4cdf4951)" in text
    bad = R.handover("v9.9.9", "c" * 40, "/pins/factory", man, None, None, ["example x failed"])
    assert "## NOT ready to hand over" in bad and "- example x failed" in bad and "no impact measured" in bad


def test_une_revision_donne_son_commit_et_un_nom():
    # HEAD, pas un tag : le dépôt de la CI n'a pas forcément les tags (clone superficiel)
    commit, version = R.resolve("HEAD")
    assert len(commit) == 40 and version
    import pytest
    with pytest.raises(SystemExit):
        R.resolve("no-such-rev-anywhere")


def test_sans_kit_la_commande_s_arrete_avant_d_extraire(tmp_path):
    class NoKit:
        def rack(self):
            return None

        def media(self):
            return {}
    bad = "\n".join(R.preconditions(NoKit(), engine=False, kit=str(tmp_path)))
    assert "no declared reference rack" in bad and "no demo take" in bad and "--record-take" in bad
