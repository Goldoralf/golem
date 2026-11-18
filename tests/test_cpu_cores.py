# SPDX-License-Identifier: GPL-3.0-or-later
"""System ▸ CPU cores (bridge/cpu_cores.py) : la charge de chaque cœur, la part du moteur, le coût de chaque lane —
calculés depuis des lectures, sans rien toucher à la machine."""
from bridge import cpu_cores as CC

STAT_A = """cpu  100 0 100 800 0 0 0 0 0 0
cpu0 50 0 50 400 0 0 0 0 0 0
cpu1 50 0 50 400 0 0 0 0 0 0
intr 1
"""
STAT_B = """cpu  200 0 150 1650 0 0 0 0 0 0
cpu0 140 0 60 800 0 0 0 0 0 0
cpu1 60 0 90 850 0 0 0 0 0 0
"""


def test_la_charge_d_un_coeur_est_la_difference_de_deux_lectures():
    a, b = CC.read_stat(STAT_A), CC.read_stat(STAT_B)
    assert set(a) == {0, 1}                                      # la ligne « cpu » (le total) n'est pas un cœur
    use = CC.diff_cores(a, b)
    assert round(use[0]) == 20 and round(use[1]) == 10            # cœur 0 : 100 jiffies occupés sur 500


def test_la_part_du_moteur_se_range_sur_le_coeur_ou_est_le_fil():
    a = {10: (100, 0), 11: (50, 1)}
    b = {10: (150, 3), 11: (50, 1), 12: (20, 3)}                  # le fil 10 a tourné et il est maintenant sur le cœur 3
    share = CC.engine_share(a, b, dt=2.0, hz=100)
    assert share == {3: 25.0}                                     # 50 jiffies en 2 s = 25 % d'un cœur ; un fil neuf ne compte pas
    assert CC.engine_share(a, b, dt=0, hz=100) == {}


def test_le_cout_d_une_lane_est_son_chemin_pas_la_somme_de_ses_branches():
    stats = {"routes": [
        {"name": "GoleM:guitar-1", "procs": [{"avg": 100}, {"avg": 60}]},
        {"name": "GoleM:guitar-1/lane-a", "procs": [{"avg": 200}]},
        {"name": "GoleM:guitar-1/lane-b", "procs": [{"avg": 220}]},
        {"name": "GoleM:guitar-1#merge", "procs": [{"avg": 300}]},
        {"name": "GoleM:voice-1", "procs": [{"avg": 400}]},
        {"name": "golem:click", "procs": [{"avg": 40}]}, {"name": "golem:looper", "procs": {}}]}
    lanes, services = CC.lane_costs(stats, cycle_us=4000.0)
    assert [(x["id"], x["us"], x["pct"], x["branches"]) for x in lanes] == [("guitar-1", 680.0, 17.0, 2), ("voice-1", 400.0, 10.0, 0)]
    assert services == 1.0                                        # les services de golem, à part
    assert CC.lane_costs(None, 4000.0) == ([], 0.0)


def test_les_coeurs_p_et_e_se_lisent_la_ou_le_systeme_les_dit(tmp_path):
    (tmp_path / "cpu_core").mkdir()
    (tmp_path / "cpu_atom").mkdir()
    (tmp_path / "cpu_core" / "cpus").write_text("0-3\n")
    (tmp_path / "cpu_atom" / "cpus").write_text("4,6-7\n")
    assert CC.core_kinds(str(tmp_path)) == {0: "P", 1: "P", 2: "P", 3: "P", 4: "E", 6: "E", 7: "E"}
    assert CC.core_kinds(str(tmp_path / "absent")) == {}          # un processeur sans cœurs de deux sortes


def test_la_route_est_derriere_le_prefixe_protege():
    from bridge import auth
    assert any("/api/cpu/cores".startswith(p) for p in getattr(auth, "ADMIN_PREFIXES", ()) or ()) \
        or "/api/cpu/" in open(auth.__file__, encoding="utf-8").read()
