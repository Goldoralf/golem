# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que fait un preset au-delà du son (Alex, 2026-10-17) : le filtre « With » du sélecteur de presets et ses icônes.
Les blocs qui DISTINGUENT un preset, présence seule, où qu'ils soient ; les permanents (Rec, Click…) n'en sont pas."""
from bridge import preset_view as PV


def test_les_blocs_speciaux_dans_l_ordre():
    p = {"backing": {"songs": [{"slug": "kite"}]},
         "config": {"gen": {"blocks": [{"type": "standard"}, {"type": "drums"}]}, "rec": {"blocks": [{"type": "rec"}]}},
         "lanes": [{"chain": {"pre": [{"type": "pads"}, {"type": "amp"}]}}]}
    assert PV.features(p) == ["backing", "standard", "drums", "pads"]


def test_le_looper_ancien_et_nouveau():
    assert PV.features({"looper": {"enabled": True}}) == ["looper"]
    assert PV.features({"config": {"gen": {"blocks": [{"type": "looper"}]}}}) == ["looper"]


def test_rien_de_special():
    assert PV.features({"backing": {"songs": []}, "config": {"rec": {"blocks": [{"type": "rec"}, {"type": "click"}]}}}) == []


def test_un_patch_porte_ses_blocs_de_service():
    # la lane ⚙ d'un patch (docs/patches.md §3) : backing-track compte comme backing, la boîte à rythmes `drums`,
    # pas le kit `drumkit`
    from bridge import patches as P
    p = {"config": {"gen": {"blocks": [{"type": "backing-track"}, {"type": "drums"}]}},
         "lanes": [{"chain": {"chain": [{"type": "drumkit"}]}}]}
    assert PV.features(p) == ["backing", "drums"]
    assert all("features" in x for x in P.list_patches())


def test_rec_et_riff_comptent_pour_un_patch_pas_pour_un_preset():
    p = {"config": {"gen": {"blocks": [{"type": "drums"}]}, "rec": {"blocks": [{"type": "rec", "foot": 9}, {"type": "compo"}]}}}
    assert PV.features(p) == ["drums"]                              # un preset : Rec/Riff sont toujours là
    assert PV.features(p, capture=True) == ["drums", "rec"]         # un patch : seulement s'ils ont un switch
