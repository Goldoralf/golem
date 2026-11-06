# SPDX-License-Identifier: GPL-3.0-or-later
"""L'écran Connect de l'installateur Windows : deux clés écrites par la fonction de Settings ▸ API, sans
lancer GoleM (provision.desktop connect). Le jeton golem.fm va sous le serveur du .env."""
import pytest

from bridge import routes_content as R
from provision import desktop


@pytest.fixture
def saved(monkeypatch):
    calls = []

    async def save(body):
        calls.append(body)
        return {"ok": True}
    monkeypatch.setattr(R, "save_integrations", save)
    monkeypatch.setattr(R, "get_integrations", lambda: {
        "golemfm": {"token": {"set": True, "hint": "…abcd"}}, "tone3000": {"publishable_key": {"set": True, "hint": "…wxyz"}}})
    return calls


def test_rien_a_ecrire_rend_l_etat_masque(saved):
    assert desktop.connect({}) == {"golem_token": {"set": True, "hint": "…abcd"},
                                   "t3k_key": {"set": True, "hint": "…wxyz"}}
    assert saved == []


def test_le_jeton_va_sous_le_serveur_du_env(saved):
    # le serveur n'est jamais écrit par l'installateur : il vient de GOLEM_SERVER_URL (golem.fm par défaut)
    desktop.connect({"golem_token": " tok ", "t3k_key": "pk"})
    assert saved == [{"tone3000": {"publishable_key": "pk"}, "golemfm": {"token": "tok"}}]
