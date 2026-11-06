# SPDX-License-Identifier: GPL-3.0-or-later
"""Classement par marque et nom d'appareil (tools/classify.py) : `makes` de TONE3000 liste toute la
CHAÎNE d'enregistrement (micro, HP, loadbox, préampli), pas l'appareil capturé. Le rack lit
l'appareil par LISTE BLANCHE de marques (un micro n'est jamais une marque d'ampli) et par LISTE
NOIRE de bruit pour le nom. golem.fm classait Shure SM57 en amp-cab (350 tones) — 2026-09-14."""

import importlib.util
import os

_spec = importlib.util.spec_from_file_location("golem_classify", os.path.join(os.path.dirname(__file__), "..", "tools", "classify.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def test_un_micro_ou_un_preampli_de_chaine_ne_fait_ni_la_marque_ni_le_nom():
    makes = ["Shure SM57", "Celestion Vintage 30", "Neve 1073", "Marshall JCM800 2203"]
    assert C.detect_brand(makes, "JCM800 through 1073", "amp-cab") == "Marshall"
    assert C.clean_amp_name(makes, "JCM800 through 1073", "amp-cab") == "Marshall JCM800 2203"
    assert C.detect_brand(["Shure SM57", "Royer R-121"], "SM57 + R121 blend", "amp-cab") == "Custom / Other"


def test_outboard_l_appareil_est_le_preampli():
    assert C.detect_brand(["BAE 1073"], "BAE 1073MP Preamp", "outboard") == "BAE"
    assert C.clean_amp_name(["BAE 1073"], "BAE 1073MP Preamp", "outboard") == "BAE 1073"
    assert C.detect_brand(["Neve 31102"], "Neve 31102 Stereo Pair", "outboard") == "Neve"
    assert C.detect_brand(["Universal Audio 610-B", "Shure SM7B"], "UA 610-B Tube Preamp", "outboard") == "Universal Audio"
    assert C.detect_brand([], "1176LN Limiter, Color Only", "outboard") == "Universal Audio"
    assert C.detect_brand([], "Culture Vulture Super 15", "outboard") == "Thermionic Culture"
    assert C.detect_brand([], "Some DIY strip", "outboard") == "Custom / Other"


def test_le_make_qui_porte_la_marque_bat_le_plus_long():
    makes = ["Darkglass Alpha Omicron", "Darkglass B3K", "Darkglass Vintage Microtubes", "Mesa Subway Bass DI-Preamp"]
    assert C.detect_brand(makes, "Subway bass", "amp") == "Mesa/Boogie"
    assert C.clean_amp_name(makes, "Subway bass", "amp", "Mesa/Boogie") == "Mesa Subway Bass DI-Preamp"
    assert C.clean_amp_name(makes, "Subway bass", "amp") == "Mesa Subway Bass DI-Preamp"   # v2 : même sans marque, une pédale n'est pas le nom d'un ampli


def test_le_baffle_de_la_chaine_ne_fait_pas_la_marque():
    makes = ["Lichtlaerm Audio The King In Yellow", "Mesa Rectifier 4x12", "Revv Generator 120 MK III", "Revv RV30"]
    assert C.detect_brand(makes, "Revvolutionary", "amp-cab") == "Revv"
    assert C.detect_brand(["Mesa Rectifier 4x12"], "Recto cab", "cab") == "Mesa/Boogie"


def test_contrat_golem_fm_module_autonome_et_versionne():
    """golem.fm copie tools/classify.py + classify-data/ par script à chaque release (décision 
    2026-09-14) : le module s'importe seul (stdlib), n'écrit rien à l'import, porte sa version,
    et legendary() lit le fichier livré à côté de lui."""
    import ast
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "classify.py")).read()
    tree = ast.parse(src)
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} \
        | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"sys", "os", "json", "re", "collections"}, mods
    assert isinstance(C.CLASSIFIER_VERSION, int) and C.CLASSIFIER_VERSION >= 1
    leg = C.legendary()
    assert len(leg) >= 10 and {"make", "search", "style", "category"} <= set(leg[0])
    assert any(a["make"] == "Fender Twin Reverb" for a in leg)
    assert os.path.exists(C.LEGENDARY) and "classify-data" in C.LEGENDARY
    # rien n'est écrit à l'import : le main() est derrière __name__ == "__main__"
    assert 'if __name__ == "__main__":' in src


def test_le_heartbeat_porte_la_version_du_classifieur():
    from bridge import rigstatus
    assert rigstatus.classifier_version() == C.CLASSIFIER_VERSION >= 1
    assert rigstatus.rack_identity()["classifier_version"] == C.CLASSIFIER_VERSION


def test_v2_clones_bus_comp_et_noms_de_pedales():
    """Mesuré par golem.fm sur 2 288 tones du marché (2026-09-14) : trois défauts de la v1."""
    # 1. le make voisin « Neve » ne doit pas voler la marque d'un clone ; clones absents ajoutés
    assert C.detect_brand(["Neve", "Rupert Neve Designs Shelford Channel"], "Shelford Channel", "outboard") == "Rupert Neve Designs"
    assert C.detect_brand(["Petroglyph 1073"], "Petroglyph 1073 preamp", "outboard") == "Petroglyph"
    assert C.detect_brand(["Neve 1073"], "1073 through SM7B", "outboard") == "Neve"
    # 2. « bus comp » n'est pas SSL
    assert C.detect_brand(["Audioscape Bus Comp"], "Audioscape Bus Comp", "outboard") == "Audioscape"
    assert C.detect_brand(["SSL G Bus Compressor"], "GSSL", "outboard") == "SSL"
    # 3. pour une PÉDALE, les motifs de pédale sont l'appareil, pas du bruit : le nom vient du make
    assert C.clean_amp_name(["Ibanez TS808 Tube Screamer"], "Simulated TS808 Tube Screamer", "pedal", "Ibanez") == "Ibanez TS808 Tube Screamer"
    assert C.clean_amp_name(["Ibanez TS808 Tube Screamer", "Shure SM57"], "TS808-OCD", "pedal", "Ibanez") == "Ibanez TS808 Tube Screamer"
    # ampli : les pédales de la chaîne restent du bruit pour le nom
    assert C.clean_amp_name(["Boss SD-1", "Marshall JCM800"], "x", "amp-cab", "Marshall") == "Marshall JCM800"
    # outboard : CAPI/VP28 est l'appareil, pas un préampli de chaîne
    assert C.detect_brand(["CAPI VP28"], "VP28 pre", "outboard") == "CAPI"
    assert C.clean_amp_name(["CAPI VP28", "Shure SM57"], "VP28 pre", "outboard", "CAPI") == "CAPI VP28"
    assert C.CLASSIFIER_VERSION == 2
