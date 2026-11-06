# SPDX-License-Identifier: GPL-3.0-or-later
"""config/pedalboard/gestures.json DÉCRIT les gestes, le bridge les EXÉCUTE : ce test les accroche.

/live dessine ses glyphes et le Designer écrit ses phrases depuis cette table (2026-09-21).
Un seuil changé dans le code sans toucher la table ferait mentir l'écran — ici ça casse."""
import json
import os

from bridge import backing, config as C, drums, foot, looper, sample, standards

T = json.load(open(os.path.join(C.ROOT, "config", "pedalboard", "gestures.json"), encoding="utf8"))


def _s(block, state, g):
    return next(x["s"] for x in T["blocks"][block]["states"][state]["gestures"] if x["g"] == g)


def test_les_durees_sont_celles_du_code():
    assert _s("backing-track", "playing", "double") == backing.DOUBLE_S
    assert _s("backing-track", "playing", "hold") == backing.LONG_S
    assert _s("sample", "playing", "hold") == sample.LONG_S
    assert _s("drums", "playing", "hold") == drums.VAR_S
    assert _s("drums", "playing", "longhold") == drums.STOP_S
    assert _s("standard", "playing", "hold") == standards.RESTART_S
    # 2026-10-08 : le switch du morceau n'a plus d'appui long — un tap démarre, un tap arrête
    assert [x["g"] for x in T["blocks"]["arrangement"]["states"]["playing"]["gestures"]] == ["tap"]
    for st in ("play", "dub"):
        assert _s("looper-slot", st, "double") == looper.DOUBLE_S
        assert _s("looper-slot", st, "hold") == looper.LONG_S
    assert _s("looper-kill", "any", "hold") == looper.CONFIRM_S


def test_l_appui_long_de_selection_suit_le_contrat_du_pedalier():
    con = json.load(open(os.path.join(C.ROOT, "config", "pedalboard", "contract.json"), encoding="utf8"))
    assert _s("select", "any", "hold") == foot._compile_intent(con)["longpress_s"]


def test_la_table_est_bien_formee_et_en_anglais():
    import re
    for name, b in T["blocks"].items():
        for st, d in b["states"].items():
            assert d["gestures"], (name, st)
            for g in d["gestures"]:
                assert g["g"] in T["signs"] and g["icon"] and g["text"], (name, st, g)
                assert not re.search(r"[àâçéèêëîïôûùœ]", g["text"], re.I), g["text"]   # règle 4 : l'UI est en anglais


def test_les_libelles_de_la_batterie_disent_ce_que_fait_drums():
    """2026-10-13  : en cours, un tap ARRÊTE — la table disait encore « Fill », le geste d'avant.
    On rejoue chaque geste sur un vrai DrumControl et on compare l'op émise au libellé affiché."""
    from unittest import mock
    sent = []
    dc = drums.DrumControl(sent.append)
    t = [100.0]
    expected = {"Play the groove": "play", "Stop": "stop", "Fill": "fill",
                "Next variation, on the bar": "variation"}
    with mock.patch.object(drums._time, "monotonic", lambda: t[0]), \
            mock.patch.object(drums.threading, "Timer", mock.MagicMock()):
        def gesture(dur):
            dc.on_edge(1, True, block="d", patterns=["a", "b"], fills=["f"])
            t[0] += dur
            dc.on_edge(1, False)
            t[0] += 10
            return sent[-1]["op"] if sent else None

        tap = next(x for x in T["blocks"]["drums"]["states"]["stopped"]["gestures"] if x["g"] == "tap")
        assert gesture(0.1) == expected[tap["text"]]                        # arrêté + tap
        tap = next(x for x in T["blocks"]["drums"]["states"]["playing"]["gestures"] if x["g"] == "tap")
        assert gesture(0.1) == expected[tap["text"]]                        # en cours + tap
        gesture(0.1)                                                        # relance
        assert gesture(drums.VAR_S + 0.1) == expected[_text("drums", "playing", "hold")]


def _text(block, state, g):
    return next(x["text"] for x in T["blocks"][block]["states"][state]["gestures"] if x["g"] == g)
