# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 6 (2026-10-15) : textes montrés à l'écran en anglais, tranches de mixer numérotées, swap de bank
borné par MAX_SLOTS, fin de génération de démo lue dans `phase`, une seule animation `lp-pulse`.

Le scan de français est volontairement grossier (mots courants + accents) : il ne lit que les chaînes
littérales qui ne sont NI une docstring NI un message de journal — celles qui peuvent finir à l'écran."""
import ast
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULES = ["bridge/routes_content.py", "bridge/routes_standards.py", "bridge/preview.py",
           "bridge/transcribe_jobs.py", "bridge/pedalboard.py", "bridge/mixer.py"]
FR = re.compile(r"[àâçéèêëîïôûùüœ]|\b(introuvable|inconnue?|requise?s?|manquante?|invalide|aucune?|"
                r"déjà|vide|absente?|pas|est|une?|des|du|les?|la|sans|non|d'abord|fichier|dossier)\b", re.I)
LOG_CALLS = {"info", "warning", "error", "debug", "exception", "critical"}
# chaînes lues dans des données ANCIENNES (comparaison), jamais affichées
ALLOWED = {"CALIBRÉ"}


def _french_literals(path):
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    skip = set()
    for n in ast.walk(tree):
        body = getattr(n, "body", None)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            skip.add(id(body[0].value))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in LOG_CALLS \
                and isinstance(n.func.value, ast.Name) and n.func.value.id in ("log", "logger", "_log", "logging"):
            skip.update(id(s) for s in ast.walk(n))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
            and n.value not in ALLOWED and FR.search(n.value)]


@pytest.mark.parametrize("path", MODULES)
def test_pas_de_francais_dans_les_textes_rendus(path):
    assert _french_literals(path) == []


def test_tranches_de_mixer_numerotees(monkeypatch):
    from bridge import inputmap, mixer, store
    from bridge.state import state
    imap = {"inputs": [inputmap._enrich(e, inputmap._BY_ID) for e in inputmap.with_nth(
        [{"ch": "1", "role": "guitar"}, {"ch": "2", "role": "guitar"}])], "outputs": []}
    monkeypatch.setattr(inputmap, "current", lambda *a, **k: imap)
    monkeypatch.setattr(mixer, "levels", lambda: {})
    monkeypatch.setattr(store, "load_preset", lambda pid: None)
    monkeypatch.setattr(state, "preset_id", None, raising=False)
    lanes = [s["label"] for s in mixer.summary()["sources"] if s["kind"] == "lane"]
    assert lanes == ["Guitar 1", "Guitar 2"]


def test_swap_borne_par_max_slots(monkeypatch):
    from bridge import routes_content, setlists
    seen = {}

    def fake_swap(sid, a, b, cap):
        seen["cap"] = cap
        return {"ok": True}
    monkeypatch.setattr(setlists, "swap_lines", fake_swap)
    monkeypatch.setattr(setlists, "MAX_SLOTS", 7)
    routes_content.setlists_swap("x", {"from": 0, "to": 1})
    assert seen["cap"] == 7


def test_demo_de_patch_attend_la_phase():
    src = open(os.path.join(ROOT, "app/page-patches.js"), encoding="utf-8").read()
    # preview.status() n'a pas de `running` : le tester rendait la main dès le premier sondage
    assert "st.running" not in src
    assert "st.phase === 'done'" in src
    from bridge import preview
    assert "running" not in preview.status() and "phase" in preview.status()


def test_lp_pulse_defini_une_fois_en_opacite():
    css = open(os.path.join(ROOT, "app/style.css"), encoding="utf-8").read()
    defs = re.findall(r"@keyframes lp-pulse\{[^}]*\}", css)
    assert len(defs) == 1 and "opacity" in defs[0]
    assert "@keyframes lp-card-pulse" in css
