# SPDX-License-Identifier: GPL-3.0-or-later
"""Le tableau d'avancement de docs/golem-fx-migration.md suit le catalogue (tools/golem-fx-progress.py)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_le_tableau_d_avancement_golem_fx_est_a_jour():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "golem-fx-progress.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
