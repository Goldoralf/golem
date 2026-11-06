# SPDX-License-Identifier: GPL-3.0-or-later
"""Un `setlist-push` SANS lignes mais avec `presets[]` sur une setlist qui existe (le sélecteur de bank de golem.fm, qui
ne connaît pas les id/rev des lignes) suit le geste de la page du rack, set_presets : le nouvel ordre gagne, chaque
ligne garde ce qu'elle porte. Avant, normalize en faisait des lignes `r:<sid>:<n>` en rev 1, battues par les lignes
locales — le changement du web était perdu en silence (comparaison du contrat, 2026-10-15)."""
import pytest

from bridge import config as C, setlists as SL


@pytest.fixture
def lists(tmp_path, monkeypatch):
    (tmp_path / "setlists").mkdir()
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path / "setlists"))
    monkeypatch.setattr(SL, "_locked_now", lambda: False)
    sid = SL.create("Gig", presets=["a", "b", "c"])["id"]
    sl = SL.load(sid)
    sl["lines"][1]["title"] = "Bee"
    SL.save(sl)
    return sid


def test_un_ordre_pousse_sans_lignes_gagne_et_garde_les_lignes(lists):
    r = SL.receive_push({"id": lists, "name": "Gig", "presets": ["c", "b", "a"]})
    sl = SL.load(lists)
    assert [SL.pid_of(ln) for ln in sl["lines"]] == ["c", "b", "a"]
    assert next(ln for ln in sl["lines"] if SL.pid_of(ln) == "b").get("title") == "Bee"   # la ligne a suivi son preset
    assert r["deferred"] is False


def test_une_setlist_absente_se_cree_comme_avant(lists):
    SL.receive_push({"id": "new-one", "name": "New", "presets": ["x", "y"]})
    assert [SL.pid_of(ln) for ln in SL.load("new-one")["lines"]] == ["x", "y"]
