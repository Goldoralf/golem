# SPDX-License-Identifier: GPL-3.0-or-later
"""Un golem jamais appairé n'envoie rien (README, docs/golemfm-protocol.md) — même si l'adresse du serveur est
toujours connue depuis GOLEM_SERVER_URL (golem.fm par défaut). Seul l'appairage, un geste, parle au serveur."""
import urllib.request

from bridge import golemfm


def _unpaired(monkeypatch):
    sent = []
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", ""))
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: sent.append(req.full_url))
    return sent


def test_sans_jeton_rien_ne_part(monkeypatch):
    sent = _unpaired(monkeypatch)
    assert golemfm._req("/api/ext/songs?tagged=1") == (0, "not paired")
    assert golemfm._req("/api/health") == (0, "not paired")
    assert golemfm.catalog()["online"] is False
    assert golemfm.status() == {"configured": True, "paired": False, "reachable": False, "authed": False}
    assert sent == []


def test_l_appairage_parle_au_serveur(monkeypatch):
    sent = _unpaired(monkeypatch)
    golemfm._req("/api/ext/pair/start", body={"device_name": "x"})
    assert sent == ["https://golem.fm/api/ext/pair/start"]


def test_un_envoi_non_appaire_ne_dit_pas_envoye(monkeypatch):
    sent = _unpaired(monkeypatch)
    r = golemfm.push_backup("anything.zip")
    assert r == {"ok": False, "error": "not paired with golem.fm"}
    assert sent == []
