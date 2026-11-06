# SPDX-License-Identifier: GPL-3.0-or-later
"""L'installateur démarre golem pour les captures d'usine (bridge_start, Windows et macOS). PC Windows neuf,
2026-11-03 : quatre clics, quatre lanceurs — bridge_start ne regardait pas si golem tournait, sondait
/api/factory/captures en 1 s (un golem vivant mais lent passait pour « not started »), et chaque lanceur restait
bloqué sur une boîte modale invisible. Désormais : /api/health, un seul lancement, aucune boîte."""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _platform_module(name):
    if name == "platform_windows" and sys.platform != "win32":
        pytest.skip("platform_windows ne s'importe que sous Windows (ctypes.windll)")
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    try:
        spec = importlib.util.spec_from_file_location(f"{name}_bs", os.path.join(ROOT, "installer", f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(os.path.join(ROOT, "installer"))
    return mod


@pytest.fixture(params=["platform_windows", "platform_macos"])
def P(request, monkeypatch, tmp_path):
    mod = _platform_module(request.param)
    if request.param == "platform_windows":
        py = tmp_path / ".venv" / "Scripts" / "pythonw.exe"
    else:
        py = tmp_path / ".venv" / "bin" / "python"
        monkeypatch.setattr(mod, "venv_python", lambda target: str(py))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "launcher.log") if "Logs" in p else p)
    py.parent.mkdir(parents=True)
    py.write_text("")
    launches = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda argv, **k: launches.append((argv, k)))
    monkeypatch.setattr("time.sleep", lambda s: None)
    mod._launches = launches
    mod._ctx = type("Ctx", (), {"S": {"dir": str(tmp_path)}})()
    return mod


def test_golem_qui_repond_n_est_pas_relance(P, monkeypatch):
    monkeypatch.setattr(P, "golem_answers", lambda port=8770: True)
    assert P.bridge_start(P._ctx) is None
    assert P._launches == [], "un deuxième clic ne lance pas un deuxième golem"


def test_golem_absent_est_lance_une_fois_sans_boite(P, monkeypatch):
    answers = iter([False, False, False, True])
    monkeypatch.setattr(P, "golem_answers", lambda port=8770: next(answers))
    assert P.bridge_start(P._ctx) is None
    assert len(P._launches) == 1
    argv, kw = P._launches[0]
    assert argv[-3:] == ["-m", "provision.desktop", "server"]
    assert kw["env"]["GOLEM_NO_DIALOG"] == "1", "le lanceur n'a pas d'écran : aucune boîte modale"


def test_la_sonde_est_api_health():
    for name in ("platform_windows.py", "platform_macos.py"):
        src = open(os.path.join(ROOT, "installer", name), encoding="utf-8").read()
        body = src[src.index("def bridge_start"):src.index("def golem_answers")]
        assert "/api/factory/captures" not in body and "golem_answers()" in body, name
        assert "/api/health" in src[src.index("def golem_answers"):], name


def test_notify_sans_ecran_ecrit_et_rend_la_main(monkeypatch, capsys):
    sys.path.insert(0, ROOT)
    from provision import desktop
    monkeypatch.setenv("GOLEM_NO_DIALOG", "1")
    monkeypatch.setattr(desktop.subprocess, "run", lambda *a, **k: pytest.fail("pas de notification système"))
    if sys.platform == "win32":
        import ctypes
        monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", lambda *a: pytest.fail("pas de boîte modale"))
    monkeypatch.setattr(sys, "stderr", None)
    desktop._notify("golem is running without a window")
    assert "golem is running without a window" in capsys.readouterr().out
