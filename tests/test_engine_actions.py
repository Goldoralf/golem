# SPDX-License-Identifier: GPL-3.0-or-later
"""Le garde-fou des commandes moteur (docs/ardour-plan.md §7d, lot 4) : une commande que le bridge envoie est CLASSÉE
pour le Golem Engine — traitée, en attente d'une fonction, ou sans objet avec sa raison. Le jour où quelqu'un ajoute
une commande côté REAPER, ce test échoue tant qu'elle n'est pas classée : l'écart ne se recreuse plus en silence."""
import glob
import json
import os
import re

from bridge.engine import actions as R
from bridge.engine.ardour import ArdourEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sent_by_the_bridge():
    """Tout littéral {"action": "<nom>"} du bridge — c'est ainsi que chaque commande est écrite."""
    found = {}
    for path in glob.glob(os.path.join(ROOT, "bridge", "**", "*.py"), recursive=True):
        if path.endswith(os.path.join("engine", "actions.py")):
            continue
        with open(path, encoding="utf-8") as f:
            for name in re.findall(r'"action":\s*"([a-z_]+)"', f.read()):
                found.setdefault(name, os.path.relpath(path, ROOT))
    return found


def test_chaque_commande_envoyee_est_classee():
    unknown = {a: f for a, f in sent_by_the_bridge().items() if a not in R.COMMANDS and a not in R.NOT_COMMANDS}
    assert not unknown, ("commande(s) non classée(s) pour le Golem Engine — à ajouter dans bridge/engine/actions.py "
                         f"(traitée, en attente d'une fonction, ou sans objet) : {unknown}")


def test_le_classement_dit_ce_que_l_adaptateur_accepte():
    handled = {a for a, e in R.COMMANDS.items() if e["ardour"] is True}
    assert handled == set(ArdourEngine.actions), (handled ^ set(ArdourEngine.actions))


def test_une_commande_en_attente_nomme_une_fonction_que_le_moteur_n_a_pas():
    feats = json.load(open(os.path.join(ROOT, "config", "engines", "features.json"), encoding="utf-8"))
    names = {f[0] for f in feats["features"]}
    caps = json.load(open(os.path.join(ROOT, "config", "engines", "ardour.json"), encoding="utf-8"))["capabilities"]
    for action, e in R.COMMANDS.items():
        if isinstance(e["ardour"], str):
            assert e["ardour"] in names, f"{action} : fonction inconnue « {e['ardour']} »"
            # la fonction déclarée « yes » alors que sa commande n'est pas traitée : le descripteur mentirait
            assert caps.get(e["ardour"]) != "yes", f"{action} : « {e['ardour']} » est dite jouée, sa commande ne l'est pas"
        elif e["ardour"] is None:
            assert e.get("why"), f"{action} : sans objet, mais sans raison"


def test_une_commande_inconnue_du_moteur_est_refusee_sans_bruit():
    eng = ArdourEngine(link=object())
    assert eng.send({"action": "vst_open"}) is None                    # écartée, une ligne de journal, rien n'est posé
    assert R.status("vst_open") is None and R.status("rig_recall") is True and R.status("perf_rec") is True
