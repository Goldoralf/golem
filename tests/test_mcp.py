# SPDX-License-Identifier: GPL-3.0-or-later
"""Le serveur MCP du rack est une VUE EN LECTURE — et ces tests gardent cette frontière.

Demande golem.fm du 2026-09-12 : ils déduisaient l'état de la machine en lisant notre code au lieu
de le demander. On leur ouvre huit lectures (sept, plus `diag_report` du lot 8). Ce qui doit rester vrai, quoi qu'on ajoute ensuite :
rien n'écrit, et `rig_status` ne laisse pas fuir qui joue.
"""
from __future__ import annotations

from bridge import mcp


def _call(name, args=None, rid=1):
    return mcp._dispatch({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                          "params": {"name": name, "arguments": args or {}}})


# ── poignée de main ──────────────────────────────────────────────────────────────────────────
def test_initialize_annonce_le_protocole_et_les_outils():
    r = mcp._dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r["result"]["protocolVersion"] == mcp.PROTOCOL
    assert r["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert "job queue" in r["result"]["instructions"]      # la frontière est dite au client


def test_une_notification_ne_repond_rien():
    """Spec JSON-RPC : pas d'`id` -> pas de réponse. Répondre casserait les clients stricts."""
    assert mcp._dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_methode_inconnue():
    r = mcp._dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/nope"})
    assert r["error"]["code"] == mcp.METHOD_NOT_FOUND


# ── le catalogue d'outils ────────────────────────────────────────────────────────────────────
def test_tools_list_expose_les_huit_lectures_avec_leur_schema():
    r = mcp._dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    tools = r["result"]["tools"]
    assert {t["name"] for t in tools} == {"rig_check", "resolve", "captures", "jobs_log",
                                          "patch", "preset_export", "rig_status",
                                          "diag_report"}        # lot 8 (2026-09-13)
    for t in tools:
        assert t["inputSchema"]["type"] == "object"        # un client MCP valide les arguments
        assert "handler" not in t                          # le callable ne part JAMAIS sur le fil


def test_aucun_outil_ne_peut_ecrire():
    """La garde de la doctrine : écrire passe par la file de jobs, ordonnée et auditable. Un
    outil dont le nom annonce une mutation est un second chemin pour changer la machine."""
    interdits = ("set", "write", "install", "delete", "remove", "apply", "recall", "push", "update")
    for name in mcp.BY_NAME:
        assert not any(name.startswith(v) or name.endswith(v) for v in interdits), name


# ── les arguments ────────────────────────────────────────────────────────────────────────────
def test_outil_inconnu_et_arguments_manquants():
    assert _call("nope")["error"]["code"] == mcp.METHOD_NOT_FOUND
    assert _call("resolve")["error"]["code"] == mcp.INVALID_PARAMS        # ref obligatoire
    assert _call("preset_export")["error"]["code"] == mcp.INVALID_PARAMS  # id obligatoire


def test_un_outil_qui_casse_ne_tue_pas_la_session():
    """Une exception d'outil devient une erreur JSON-RPC, jamais une 500 : le client garde sa
    session et peut poser la question suivante."""
    def boom(_a):
        raise RuntimeError("la sonde a glissé")
    mcp.BY_NAME["__boom"] = {"name": "__boom", "handler": boom}
    try:
        r = _call("__boom")
        assert r["error"]["code"] == mcp.INTERNAL and "glissé" in r["error"]["message"]
    finally:
        del mcp.BY_NAME["__boom"]


# ── ce qui ne doit pas fuir ──────────────────────────────────────────────────────────────────
def test_rig_status_ne_dit_jamais_QUI_joue():
    """Le mode porte `band` (id d'espace) et le roster porte des prénoms : le contrat d'identité
    dit que ça ne sort pas du rack (docs/identity.md). rig_status répond « ce que la machine
    autorise », pas « pour qui »."""
    import json as _json
    out = _json.dumps(mcp.t_rig_status({}))
    for fuite in ("band", "person", "people", "roster", "token"):
        assert fuite not in out, fuite


def test_resolve_dit_pourquoi_quand_il_ne_trouve_pas():
    """« found: false » sans raison relance la devinette que ce serveur existe pour supprimer."""
    out = mcp.t_resolve({"ref": "t3k:000000-jamais-installe"})
    assert out["found"] is False and out["why"]


def test_le_contenu_est_rendu_DEUX_fois_texte_et_structure():
    """Spec 2025-06-18 : un outil qui rend du structuré doit aussi rendre le texte, pour les
    clients qui ne lisent que `content`."""
    r = _call("rig_status")["result"]
    assert r["isError"] is False
    assert r["content"][0]["type"] == "text"
    import json as _json
    assert _json.loads(r["content"][0]["text"]) == r["structuredContent"]


# ── L'ARTEFACT LE PLUS PRÉCIEUX ÉTAIT LE PLUS FUGACE (question golem.fm, 2026-09-12) ────────
# `.rig-check.json` ne garde que la DERNIÈRE passe : les quatre anomalies « expected %MODEL% »
# du 2026-09-11 avaient déjà été effacées par la compilation suivante quand on est venu les lire.
def test_une_passe_verte_nencombre_pas_le_journal(tmp_path, monkeypatch):
    from bridge import monitors
    monkeypatch.setattr(monitors, "RIG_CHECK_HIST", str(tmp_path / "h.json"))
    monitors._archive_rig_check({"t": 1, "ok": True, "checked": 2, "issues": []})
    assert not (tmp_path / "h.json").exists()      # rien à dire : l'état courant le dit déjà


def test_une_passe_anormale_survit_a_la_suivante(tmp_path, monkeypatch):
    import json
    from bridge import monitors
    monkeypatch.setattr(monitors, "RIG_CHECK_HIST", str(tmp_path / "h.json"))
    bad = {"t": 10, "ok": False, "checked": 2,
           "issues": [{"track": "Sandbox #Input 1/lane-a", "fx": 0, "kind": "model",
                       "expected": "%MODEL%", "repaired": True}]}
    monitors._archive_rig_check(bad)
    monitors._archive_rig_check(bad)                                  # même passe relue
    monitors._archive_rig_check({**bad, "t": 11})
    hist = json.loads((tmp_path / "h.json").read_text())
    assert [h["t"] for h in hist] == [10, 11]                         # pas de doublon sur `t`
    assert hist[0]["issues"][0]["expected"] == "%MODEL%"


def test_le_journal_est_borne(tmp_path, monkeypatch):
    import json
    from bridge import monitors
    monkeypatch.setattr(monitors, "RIG_CHECK_HIST", str(tmp_path / "h.json"))
    for t in range(monitors.RIG_CHECK_KEEP + 5):
        monitors._archive_rig_check({"t": t, "ok": False, "checked": 1, "issues": []})
    hist = json.loads((tmp_path / "h.json").read_text())
    assert len(hist) == monitors.RIG_CHECK_KEEP and hist[-1]["t"] == monitors.RIG_CHECK_KEEP + 4


# ── LE PIÈGE DE TEST, signalé par golem.fm après y être tombé ───────────────────────────────
# Comparer `model=<premier modèle du pack>` à `model` absent donne le MÊME fichier : un tel test
# passe que le code lise l'argument ou non. On épingle donc un modèle qui n'est PAS `models[0]`.
def test_le_model_epingle_choisit_un_AUTRE_fichier_que_le_premier():
    from bridge import resolver, mcp as m
    tone = {"id": 44209, "models": [
        {"id": 567082, "file": "assets/x/blend-1.nam"},        # models[0] : le repli
        {"id": 567080, "file": "assets/x/the-sound-sm58.nam"},
        {"id": 234548, "file": "assets/x/test-sm57.nam"}]}
    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(resolver, "_tones_index", lambda: {"44209": tone})
        assert m.t_resolve({"ref": "44209"})["file"].endswith("blend-1.nam")
        assert m.t_resolve({"ref": "44209", "model": 567080})["file"].endswith("the-sound-sm58.nam")
        assert m.t_resolve({"ref": "t3k:44209", "model": 234548})["file"].endswith("test-sm57.nam")
        # un id inconnu retombe sur models[0] — documenté, et mesuré par golem.fm
        assert m.t_resolve({"ref": "44209", "model": 999999})["file"].endswith("blend-1.nam")
