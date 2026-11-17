# SPDX-License-Identifier: GPL-3.0-or-later
"""Le mode performance suit golem (bridge/routes_system.py, décision du 2026-11-17) : allumé tant qu'il tourne, sous les
deux moteurs, sauf sur batterie ou interrupteur coupé ; reposé quand le système le retire ; rendu à l'arrêt."""
import os
import subprocess

import pytest

from bridge import routes_system as RS

HOME = {"name": "Home", "perf_boost": False}
# les vraies fonctions, prises à l'import : tests/conftest.py neutralise les appelants automatiques pour tous les tests
REAL = {k: getattr(RS, k) for k in ("apply_perf_for_mode", "perf_guard_tick", "perf_status")}


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """Une machine de test : son gouverneur, sa marque, son réglage — et les appels « sudo » notés, jamais faits."""
    m = {"gov": "powersave", "calls": [], "ok": True}
    monkeypatch.setattr(RS, "PERF_CFG", str(tmp_path / "perf.json"))
    monkeypatch.setattr(RS, "PERF_PREV", str(tmp_path / ".perf-prev"))
    monkeypatch.setattr(RS, "_cpu_governor", lambda: m["gov"])
    monkeypatch.setattr(RS, "on_battery", lambda: False)
    monkeypatch.setattr(RS.sys, "platform", "linux")

    def apply(on):
        m["calls"].append(on)
        if m["ok"]:
            m["gov"] = "performance" if on else "powersave"
        return m["ok"], "" if m["ok"] else "sudo: a password is required"
    monkeypatch.setattr(RS, "apply_perf", apply)
    monkeypatch.setattr(RS, "_PERF_GUARD", {"last": 0.0, "said": None})
    for k, fn in REAL.items():
        monkeypatch.setattr(RS, k, fn)
    return m


def test_golem_allume_le_boost_et_note_le_mode_d_avant(machine):
    assert RS.apply_perf_for_mode(HOME) is True and machine["gov"] == "performance"
    assert open(RS.PERF_PREV).read() == "powersave"                       # ce que stop.sh rendra
    assert RS.apply_perf_for_mode(HOME) is True and machine["calls"] == [True]   # déjà allumé : pas de sudo pour rien


def test_le_gardien_repose_le_boost_que_le_systeme_a_retire(machine):
    RS.apply_perf_for_mode(HOME)
    machine["gov"] = "powersave"                                          # power-profiles-daemon est passé par là
    assert RS.perf_guard_tick(HOME, now=1000.0) is True and machine["gov"] == "performance"
    machine["gov"] = "powersave"
    assert RS.perf_guard_tick(HOME, now=1005.0) is False                  # pas plus d'une fois toutes les 20 s
    assert RS.perf_guard_tick(HOME, now=1021.0) is True


def test_sur_batterie_ou_interrupteur_coupe_golem_ne_touche_a_rien(machine, monkeypatch):
    monkeypatch.setattr(RS, "on_battery", lambda: True)
    assert RS.wants_boost(HOME) == (False, "on battery")
    assert RS.apply_perf_for_mode(HOME) is True and machine["calls"] == []   # il ne l'a pas allumé : il ne l'éteint pas
    assert RS.perf_guard_tick(HOME, now=1000.0) is False and machine["calls"] == []
    monkeypatch.setattr(RS, "on_battery", lambda: False)
    RS.set_perf_auto(False)
    assert RS.perf_auto() is False and RS.wants_boost(HOME)[0] is False
    assert RS.wants_boost({"name": "Gig", "perf_boost": True})[0] is True   # un mode qui l'exige l'emporte
    RS.set_perf_auto(True)
    assert RS.wants_boost(HOME) == (True, "golem is running")


def test_quand_l_automatisme_est_coupe_golem_rend_ce_qu_il_avait_allume(machine):
    RS.apply_perf_for_mode(HOME)
    RS.set_perf_auto(False)
    assert RS.apply_perf_for_mode(HOME) is True and machine["gov"] == "powersave" and not os.path.exists(RS.PERF_PREV)
    machine["gov"] = "performance"                                        # la personne l'allume À LA MAIN (pas de marque)
    assert RS.apply_perf_for_mode(HOME) is True and machine["gov"] == "performance"   # golem ne l'éteint pas


def test_sans_la_regle_sudo_c_est_dit_et_health_le_montre(machine):
    from bridge import health

    class St:
        mode = HOME
    machine["ok"] = False
    assert RS.apply_perf_for_mode(HOME) is False and not os.path.exists(RS.PERF_PREV)
    f = health._f_perf(St())
    assert f["level"] == "warn" and "off although golem is running" in f["text"] and "setup-perf-sudo" in f["text"]
    machine["ok"], machine["gov"] = True, "performance"
    assert health._f_perf(St())["level"] == "ok"


def test_la_batterie_se_lit_sur_l_alimentation_secteur(tmp_path):
    assert RS.on_battery(str(tmp_path / "absent")) is False               # pas de dossier : une tour, un rack
    (tmp_path / "BAT0").mkdir()
    (tmp_path / "BAT0" / "type").write_text("Battery\n")
    assert RS.on_battery(str(tmp_path)) is False                          # une batterie sans prise secteur connue : pas de verdict
    (tmp_path / "AC").mkdir()
    (tmp_path / "AC" / "type").write_text("Mains\n")
    (tmp_path / "AC" / "online").write_text("1\n")
    assert RS.on_battery(str(tmp_path)) is False
    (tmp_path / "AC" / "online").write_text("0\n")
    assert RS.on_battery(str(tmp_path)) is True


def test_golem_stop_rend_le_mode_d_avant(tmp_path):
    """provision/lib-engine.sh golem_perf_restore : la marque lue et retirée ; sans marque, rien."""
    here = tmp_path / "golem"
    (here / "presets").mkdir(parents=True)
    (here / "provision").mkdir()
    (here / "provision" / "perf-mode.sh").write_text("#!/bin/sh\necho \"$1\" >> \"$(dirname \"$0\")/called\"\n")
    (here / "provision" / "perf-mode.sh").chmod(0o755)
    lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "provision", "lib-engine.sh")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "sudo").write_text("#!/bin/sh\n[ \"$1\" = -n ] && shift\nexec \"$@\"\n")   # un sudo qui exécute, sans privilège
    (fake / "sudo").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}

    def run():
        # /usr/local/sbin/golem-perf-mode peut exister sur le poste : le test ne doit JAMAIS l'appeler
        script = f'. "{lib}"; golem_perf_restore() {{ :; }}; . /dev/null'
        src = open(lib).read().replace("/usr/local/sbin/golem-perf-mode", str(tmp_path / "no-such-script"))
        (tmp_path / "lib.sh").write_text(src)
        return subprocess.run(["bash", "-c", f'. "{tmp_path / "lib.sh"}"; golem_perf_restore "{here}"'], env=env,
                              capture_output=True, text=True, timeout=20)
    run()
    assert not (here / "provision" / "called").exists()                   # pas de marque : golem n'avait rien allumé
    (here / "presets" / ".perf-prev").write_text("powersave")
    r = run()
    assert (here / "provision" / "called").read_text() == "off\n" and not (here / "presets" / ".perf-prev").exists(), r.stderr
    (here / "presets" / ".perf-prev").write_text("performance")           # il était déjà en performance avant golem
    run()
    assert (here / "provision" / "called").read_text() == "off\n"         # rien de plus : on le laisse comme il était
