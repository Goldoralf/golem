# SPDX-License-Identifier: GPL-3.0-or-later
"""AUDIT 2026-09-13, m6 : un échec TONE3000 se dit en une phrase, avec le geste."""
from bridge.routes_t3k import _t3k_error


def test_une_session_morte_se_dit_en_une_phrase():
    raw = SystemExit('✗ token endpoint 400: {"code":400,"error_code":"refresh_token_already_used"}')
    assert _t3k_error(raw) == "TONE3000 session expired — reconnect it in Settings ▸ Connect ▸ TONE3000"
    assert "Settings" in _t3k_error(SystemExit("✗ Pas de refresh token. Relance : ./tools/t3k.py auth"))


def test_une_autre_erreur_passe_telle_quelle():
    assert _t3k_error(RuntimeError("timeout")) == "timeout"


def test_jamais_connecte_n_est_pas_expire():
    """VM Windows vierge, 2026-10-16 : l'écran de chargement disait « session expired » à qui ne s'était jamais connecté."""
    msg = _t3k_error(SystemExit("✗ Pas de token. Lance d'abord : ./tools/t3k.py auth"))
    assert "not signed in" in msg and "expired" not in msg
