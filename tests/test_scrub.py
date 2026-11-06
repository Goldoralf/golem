# SPDX-License-Identifier: GPL-3.0-or-later
"""Le scrubber partagé (bridge/scrub.py, docs/diagnostics.md §7.1, lot D1) : bibliothèque standard seulement — l'installateur
le charge par son chemin, sans le paquet bridge — et les dossiers personnels des trois systèmes."""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "bridge", "scrub.py")


def _load():
    spec = importlib.util.spec_from_file_location("golem_scrub", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_se_charge_par_son_chemin_sans_le_paquet_bridge():
    # un interpréteur isolé (-I), hors du dépôt : seul le fichier, comme l'installateur
    code = ("import importlib.util as u; s = u.spec_from_file_location('x', %r); m = u.module_from_spec(s); "
            "s.loader.exec_module(m); import sys; assert 'bridge' not in sys.modules; print(m.Scrubber()('ok'))") % PATH
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd="/", timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_dossiers_personnels_des_trois_systemes():
    sc = _load().Scrubber()
    assert sc("/home/alice/golem/x.log") == "~/golem/x.log"
    assert sc("/Users/alice/Library/golem") == "~/Library/golem"
    assert sc(r"C:\Users\Alice\AppData\Local\GoleM\x") == r"~\AppData\Local\GoleM\x"
    assert sc("c:/users/alice/golem") == "~/golem"


def test_un_secret_tape_disparait_avant_tout_le_reste():
    sc = _load().Scrubber(secrets=["pk_live_abc123", "x"], roots=["/opt/golem-install"])
    out = sc("key pk_live_abc123 saved in /opt/golem-install/config")
    assert "pk_live_abc123" not in out and "<secret>" in out and "~/config" in out
    assert sc("x marks") == "x marks"                  # un « secret » de moins de 4 caractères n'efface rien


def test_libelles_connus_par_ordre_et_mot_entier():
    sc = _load().Scrubber(known=((["Set Léa"], "<preset>"), (["Léa"], "<name>")))
    assert sc("Set Léa by Léa, unclean") == "<preset> by <name>, unclean"
