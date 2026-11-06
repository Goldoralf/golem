# SPDX-License-Identifier: GPL-3.0-or-later
"""L'écran Install en phases (installer/phases.py) : marqueurs, estimation, manques non fatals, ↻ Try again."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import phases as PH  # noqa: E402

STEPS = [("source", "Copy"), ("system", "System"), ("start", "Start")]
PHASES = [{"id": "source", "step": "source", "label": "Copy golem", "est": 10},
          {"id": "packages", "step": "system", "label": "System packages", "est": 100},
          {"id": "build", "step": "system", "label": "Building plugins", "est": 200},
          {"id": "sounds", "step": "system", "label": "Sounds", "est": 300},
          {"id": "start", "step": "start", "label": "First start", "est": 30}]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def tracker():
    c = Clock()
    return PH.Tracker(PHASES, STEPS, now=c), c


def by_id(pub):
    return {p["id"]: p for p in pub["phases"]}


def test_avant_l_installation_l_estimation_est_la_somme_des_phases():
    t, _ = tracker()
    pub = t.public()
    assert pub["total_est"] == 640 and pub["left"] is None and pub["progress"] == 0
    assert all(p["state"] == "pending" for p in pub["phases"])


def test_les_marqueurs_ouvrent_les_phases_et_ne_vont_pas_dans_la_trace():
    t, c = tracker()
    t.step_started("source"); c.t += 12; t.step_ended("source", True)
    t.step_started("system")
    assert t.current()["id"] == "packages"          # l'étape ouvre sa première phase : le temps avant le marqueur y compte
    assert t.marker("@@phase packages", "system")
    c.t += 100
    assert t.marker("@@phase build", "system") and t.marker("@@sub Prisma — 3 of 4", "system")
    assert not t.marker("▶ Paquets apt", "system")
    p = by_id(t.public())
    assert p["packages"]["state"] == "ok" and p["packages"]["secs"] == 100
    assert p["build"]["state"] == "running" and p["build"]["sub"] == "Prisma — 3 of 4"


def test_une_etape_sans_marqueur_ouvre_sa_phase_et_une_plateforme_sans_phases_en_a_une_par_etape():
    t, _ = tracker()
    t.step_started("source")
    assert t.current()["id"] == "source"
    w = PH.Tracker([], STEPS)
    assert [p["label"] for p in w.public()["phases"]] == ["Copy", "System", "Start"]
    assert w.public()["total_est"] is None          # pas de durée mesurée : l'écran montre l'écoulé, pas un décompte


def test_le_decompte_suit_la_vitesse_observee_et_ne_dit_jamais_zero_pendant_une_phase():
    t, c = tracker()
    t.step_started("source"); c.t += 20; t.step_ended("source", True)
    t.step_started("system"); t.marker("@@phase packages", "system")
    c.t += 200                                       # deux fois plus lent que prévu (100 s)
    t.marker("@@phase build", "system")
    assert t.speed() == 2.0                          # (20 + 200) / (10 + 100)
    pub = t.public()
    assert by_id(pub)["sounds"]["est"] == 600
    assert pub["left"] == 400 + 600 + 60
    c.t += 5000                                      # la phase dépasse de loin : il lui reste au moins FLOOR_S
    assert by_id(t.public())["build"]["left"] == PH.FLOOR_S


def test_la_vitesse_reste_1_tant_que_le_prevu_passe_est_trop_court():
    t, c = tracker()
    t.step_started("source"); c.t += 60; t.step_ended("source", True)   # 6 × plus lent, mais sur 10 s prévues
    assert t.speed() == 1.0


def test_un_manque_non_fatal_finit_la_phase_en_warn_et_le_retry_le_leve():
    t, c = tracker()
    t.step_started("system"); t.marker("@@phase build", "system")
    t.marker("@@warn nam|The NAM fix could not be built — amps play with the standard NAM.", "system")
    t.marker("@@warn |Vital is missing — the Keys lane stays silent.", "system")
    t.marker("@@phase sounds", "system")
    c.t += 10; t.step_ended("system", True)
    p = by_id(t.public())
    assert p["packages"]["state"] == "ok" and not p["packages"]["skipped"]  # ouverte avec l'étape, finie au marqueur
    assert p["build"]["state"] == "warn"
    assert [w["retry"] for w in p["build"]["warns"]] == ["nam", None]
    t.warn_resolved("nam")
    p = by_id(t.public())
    assert p["build"]["state"] == "warn" and len(p["build"]["warns"]) == 1  # Vital reste : pas de ↻ pour lui


def test_un_echec_marque_la_phase_et_le_retry_garde_ce_qui_est_fini():
    t, c = tracker()
    t.step_started("source"); c.t += 10; t.step_ended("source", True)
    t.step_started("system"); t.marker("@@phase packages", "system"); c.t += 50; t.step_ended("system", False)
    p = by_id(t.public())
    assert p["source"]["state"] == "ok" and p["packages"]["state"] == "fail"
    t.reset_unfinished()
    p = by_id(t.public())
    assert p["source"]["state"] == "ok" and p["packages"]["state"] == "pending"


def test_la_fin_arrete_le_chrono():
    t, c = tracker()
    for sid, _ in STEPS:
        t.step_started(sid); c.t += 10; t.step_ended(sid, True)
    pub = t.public()
    assert pub["finished"] and pub["left"] is None
    c.t += 999
    assert t.public()["elapsed"] == 30


def test_les_phases_de_linux_couvrent_chaque_marqueur_d_install_sh():
    import re
    import platform_linux as L
    ids = {p["id"] for p in L.phases({"src": ROOT, "dir": ROOT, "packs": ["di", "piano"]})}
    txt = open(os.path.join(ROOT, "provision", "install.sh"), encoding="utf-8").read()
    marked = set(re.findall(r"^\s*mark phase (\S+)", txt, re.M))
    assert marked and marked <= ids
    retry = set(re.findall(r"\|\| soft_fail (\S+) ", txt))
    assert retry and retry <= set(L.RETRY)          # chaque ↻ proposé à l'écran a son script


def test_install_sh_n_imprime_aucun_marqueur_hors_de_l_installateur():
    # la sortie terminal reste celle d'avant : `mark` ne parle qu'à l'installateur graphique
    out = subprocess.run(["bash", "-c", 'mark() { if [ "${GOLEM_INSTALLER:-}" = 1 ]; then echo "@@$*"; fi; }; mark phase x'],
                         capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "GOLEM_INSTALLER"})
    assert out.stdout == ""
    src = open(os.path.join(ROOT, "provision", "install.sh"), encoding="utf-8").read()
    assert 'mark() { if [ "${GOLEM_INSTALLER:-}" = 1 ]; then echo "@@$*"; fi; }' in src


def test_une_phase_sautee_par_un_marqueur_dit_qu_il_n_y_avait_rien_a_faire():
    t, c = tracker()
    t.step_started("system"); c.t += 30
    t.marker("@@phase sounds", "system")            # --light, ou tout est déjà là : « build » n'a jamais tourné
    p = by_id(t.public())
    assert p["packages"]["secs"] == 30 and not p["packages"]["skipped"]
    assert p["build"]["state"] == "ok" and p["build"]["skipped"]


def test_pendant_les_sons_le_temps_restant_vient_du_debit_mesure():
    # VM 2026-10-23 : 31 min prévues, 11 réelles — l'avancement mesuré remplace l'estimation dès qu'il dit quelque chose
    t, c = tracker()
    t.step_started("system"); t.marker("@@phase sounds", "system")
    t.marker("@@progress 0 3000", "system")
    c.t += 5; t.marker("@@progress 50 3000", "system")
    assert by_id(t.public())["sounds"]["left"] == 295                    # trop tôt : encore l'estimation (300 - 5)
    c.t += 55; t.marker("@@progress 600 3000", "system")                 # 600 Mo en 60 s : 10 Mo/s
    s = by_id(t.public())["sounds"]
    assert s["left"] == 240 and s["progress"] == {"done": 600, "total": 3000}
    assert t.marker("@@progress", "system")                              # un marqueur mal formé est avalé, sans casser


def test_une_phase_reseau_n_apprend_ni_ne_subit_la_vitesse_de_calcul():
    # VM 2026-10-23 : apt à 220 s au lieu de 130 faisait annoncer une compilation 30 % plus longue
    ph = [dict(p) for p in PHASES]
    ph[1]["learn"] = False                           # packages
    ph[3]["learn"] = False                           # sounds
    c = Clock()
    t = PH.Tracker(ph, STEPS, now=c)
    t.step_started("source"); c.t += 10; t.step_ended("source", True)
    t.step_started("system"); c.t += 300             # packages : 3 × plus lent que prévu
    t.marker("@@phase build", "system")
    assert t.speed() == 1.0                          # rien appris (source : 10 s prévues, sous le seuil)
    c.t += 400; t.marker("@@phase sounds", "system")  # build : 2 × plus lent → la machine calcule lentement
    assert t.speed() == (10 + 400) / (10 + 200)     # source + build ; packages n'y entre pas
    pub = by_id(t.public())
    assert pub["start"]["est"] == round(30 * 410 / 210)   # une phase de calcul suit la vitesse…
    assert pub["sounds"]["left"] == 300              # … une phase réseau garde son estimation (puis son débit mesuré)


def test_une_compilation_imprevue_allonge_la_phase():
    # précompilé indisponible : le script dit la durée de SA compilation (provision/lib-prebuilt.sh compiling)
    t, c = tracker()
    t.step_started("system"); t.marker("@@phase build", "system")
    c.t += 150
    assert by_id(t.public())["build"]["left"] == 50
    assert t.marker("@@est-add 145", "system")
    assert by_id(t.public())["build"]["left"] == 195
    assert t.marker("@@est-add oops", "system")                          # mal formé : avalé, rien ne casse
