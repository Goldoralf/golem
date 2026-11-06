# SPDX-License-Identifier: GPL-3.0-or-later
"""Licenses ▸ GoleM : « local changes » ne compte que le CODE — l'état de la machine (config/, presets/,
sets/, mappings/) change en jouant et ne doit pas griser le passage à une release (2026-10-03)."""
from types import SimpleNamespace

from bridge import routes_system as S


def test_l_etat_de_la_machine_n_est_pas_un_changement_de_code(monkeypatch):
    porcelain = (" M config/inputmaps/hw-V276.json\n M presets/kite.json\n M sets/golem-set.rpp\n"
                 " M mappings/foot.json\n M bridge/app.py\nR  app/a.js -> app/b.js\n")
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout=porcelain)
    monkeypatch.setattr(S.subprocess, "run", run)
    assert S._code_changes() == ["bridge/app.py", "app/b.js"]
    assert "--untracked-files=no" in seen["cmd"]          # un fichier non suivi ne bloque pas un checkout
