# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings ▸ Health, couche « Now » (docs/health.md §1.1, §4.2) : des faits datés qui ne disent que ce qui est
mesuré, un verdict qui monte du pire fait, la dérive de l'environnement comparée entre deux passages, et une route
qui ne se lit pas sans jeton depuis le LAN. `.venv/bin/python -m pytest tests/test_health.py -q`"""
import json
import os
import time
from types import SimpleNamespace as NS

import pytest

from bridge import auth, health as H


@pytest.fixture
def rack(tmp_path, monkeypatch):
    """Un rack isolé : config et presets dans tmp, toutes les sondes externes neutres (chacune se surcharge)."""
    from bridge import config as C
    (tmp_path / "config").mkdir()
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(H, "_cache", {"at": 0.0, "doc": None})
    monkeypatch.setattr(H, "_setlist_cache", {"key": None, "at": 0.0, "value": None})
    monkeypatch.setattr(H, "START", time.time() - 120)          # le bridge tourne depuis 2 min : plus de grâce
    import bridge.rigstatus as RS
    monkeypatch.setattr(RS, "reaper_version", lambda: "7.80")
    monkeypatch.setattr(RS, "engine_doc", lambda: {"device": "Volt 276", "samplerate": 48000, "bsize": 128, "latency_ms": 2.7})
    monkeypatch.setattr(RS, "disk", lambda: {"total_gb": 420.0, "free_gb": 184.0, "used_pct": 56})
    monkeypatch.setattr(RS, "golem_version", lambda: "v0.40")
    import bridge.pedalboard as PB
    monkeypatch.setattr(PB, "active", lambda: {"id": "fcb1010-uno2", "name": "FCB1010", "source": "measured", "stale": False, "firmware": "2.0"})
    import bridge.blockstatus as BS
    monkeypatch.setattr(BS, "caps", lambda: {"inventory": True, "inventory_at": "2026-10-20T10:00:00Z", "quarantine": [], "unavailable": []})
    monkeypatch.setattr(BS, "inventory", lambda: {"at": 1000, "n": 61})
    monkeypatch.setattr(H, "_setlist_status", lambda: {"id": "factory", "name": "Factory", "presets": 6, "not_ready": [],
                                                       "missing_blocks": 0, "download_bytes": 0, "inventory": True})
    import bridge.boot_progress as BP
    monkeypatch.setattr(BP, "doc", lambda: {"services": {"fm": {"configured": True, "ok": True}}})
    import bridge.follow_uplink as FU
    monkeypatch.setattr(FU, "LINKED", {"ok": True, "t": time.time() - 3600})
    import bridge.reamp as RE
    monkeypatch.setattr(RE, "busy_reason", lambda idle=True: None)
    import bridge.activity as AC
    monkeypatch.setattr(AC, "last", lambda: {"src": "screen", "idle_s": 660.0})
    from bridge.state import state as st
    monkeypatch.setattr(st, "reaper_running", True)
    monkeypatch.setattr(st, "reaper_connected", True)
    monkeypatch.setattr(st, "audio", {"ok": True})
    monkeypatch.setattr(st, "latency_ms", 2.7)
    monkeypatch.setattr(st, "xruns", 0)
    monkeypatch.setattr(st, "xruns_recent", 0)
    monkeypatch.setattr(st, "xruns_last", None)
    monkeypatch.setattr(st, "midi", {"ok": True, "issues": []})
    monkeypatch.setattr(st, "preset_name", "Test — Guitar bench")
    monkeypatch.setattr(st, "preset_id", "ci-engine")
    monkeypatch.setattr(st, "rig_check", {"t": time.time() - 30, "ok": True, "checked": 2, "issues": []})
    monkeypatch.setattr(st, "rig_error", None)
    monkeypatch.setattr(st, "rig_loading", None)
    return st


def _by(doc, fid):
    return next(f for f in doc["facts"] if f["id"] == fid)


def test_tout_va_bien_tout_est_vert_et_le_verdict_le_dit(rack):
    d = H.facts(fresh=True)
    levels = {f["id"]: f["level"] for f in d["facts"]}
    assert levels == {"engine": "ok", "audio": "ok", "dropouts": "ok", "pedalboard": "ok", "playing": "ok", "setlist": "ok",
                      "plugins": "ok", "disk": "ok", "golemfm": "ok", "scripts": "ok", "environment": "wait"}
    assert d["verdict"]["level"] == "ok" and d["verdict"]["title"] == "Everything checks out."
    assert d["verdict"]["counts"] == {"ok": 10, "warn": 0, "bad": 0, "wait": 1, "total": 11}
    assert all(f["source"] for f in d["facts"]), "chaque fait nomme sa source"
    assert "Volt 276 · 48 kHz · 128 samples · 2.7 ms" == _by(d, "audio")["text"]
    assert d["guard"] == {"free": True, "why": None, "idle_s": 660.0, "src": "screen"}
    b = H.brief()
    assert b["level"] == "ok" and b["bad"] == 0 and b["warn"] == 0 and b["at"] == d["at"]


def test_un_orange_porte_son_geste_et_monte_dans_le_verdict(rack, monkeypatch):
    monkeypatch.setattr(H, "_setlist_status", lambda: {
        "id": "factory", "name": "Factory", "presets": 10, "inventory": True, "missing_blocks": 2, "download_bytes": 38e6,
        "not_ready": [{"preset": "Rooftop Prowl", "missing": 2, "download": 2, "unavailable": 0}],
        "reasons": {"plugin": 0, "format": 0, "capture": 2, "other": 0}})
    d = H.facts(fresh=True)
    f = _by(d, "setlist")
    assert f["level"] == "warn"
    assert f["text"] == "“Factory” · 2 blocks will not play here on “Rooftop Prowl”: 2 to download (38 MB)"
    assert f["fix"] == {"label": "Patches →", "go": "songs/patches"}, "Health ne télécharge rien : il mène là où chaque bloc se répare"
    # …et quand c'est la machine qui ne peut pas (plugin absent, format de capture) : dit, avec le pourquoi, vers Patches
    monkeypatch.setattr(H, "_setlist_status", lambda: {
        "id": "factory", "name": "Factory Guitar", "presets": 10, "inventory": True, "missing_blocks": 38, "download_bytes": 0,
        "not_ready": [{"preset": f"P{i}", "missing": 4, "download": 0, "unavailable": 4} for i in range(10)],
        "reasons": {"plugin": 21, "format": 14, "capture": 3, "other": 0}})
    f = _by(H.facts(fresh=True), "setlist")
    assert f["text"].startswith("“Factory Guitar” · 38 blocks will not play here across 10 of 10 presets: 21 need a plugin not installed on this")
    assert "14 are captures this engine cannot play" in f["text"] and f["text"].endswith("3 to download")
    assert f["fix"]["go"] == "songs/patches"
    assert d["verdict"]["level"] == "warn"
    assert d["verdict"]["title"] == "Playing is safe. One thing to look at."
    assert "Rooftop Prowl" in d["verdict"]["text"]


def test_un_rouge_gagne_sur_tout_et_nomme_le_fait(rack, monkeypatch):
    monkeypatch.setattr(rack, "audio", {"ok": False, "why": "the audio thread stopped", "fix": "restart REAPER"})
    monkeypatch.setattr(rack, "xruns_recent", 3)
    monkeypatch.setattr(rack, "xruns", 12)
    monkeypatch.setattr(rack, "xruns_last", time.time() - 120)
    d = H.facts(fresh=True)
    assert _by(d, "audio")["level"] == "bad" and _by(d, "audio")["fix"]["go"] == "system/gear/sound"
    assert _by(d, "dropouts")["level"] == "warn" and "3 in the last 10 min · 12 since start · last 2 min ago" == _by(d, "dropouts")["text"]
    assert d["verdict"]["level"] == "bad"
    assert d["verdict"]["title"] == "Something is wrong: sound card."
    assert H.brief()["bad"] == 1 and H.brief()["warn"] == 1


def test_ce_qui_n_est_pas_mesure_est_dit_wait_jamais_alarme(rack, monkeypatch):
    """Le moteur qui démarre, un pédalier seulement déclaré, pas de preset : des « wait », et le verdict dit
    « Still starting » — jamais un rouge sur une ignorance."""
    monkeypatch.setattr(H, "START", time.time() - 5)
    monkeypatch.setattr(rack, "reaper_running", False)
    monkeypatch.setattr(rack, "reaper_connected", False)
    monkeypatch.setattr(rack, "audio", {})
    monkeypatch.setattr(rack, "preset_name", None)
    monkeypatch.setattr(rack, "preset_id", None)
    import bridge.pedalboard as PB
    monkeypatch.setattr(PB, "active", lambda: {"id": "fcb1010", "name": "FCB1010", "source": "declared"})
    d = H.facts(fresh=True)
    assert {f["id"]: f["level"] for f in d["facts"] if f["id"] in ("engine", "audio", "pedalboard", "playing")} == \
        {"engine": "wait", "audio": "wait", "pedalboard": "wait", "playing": "wait"}
    assert d["verdict"]["level"] == "wait" and d["verdict"]["title"] == "Still starting."
    # …mais après une minute sans REAPER, c'est une panne, avec le geste
    monkeypatch.setattr(H, "START", time.time() - 120)
    d = H.facts(fresh=True)
    assert _by(d, "engine")["level"] == "bad" and _by(d, "engine")["fix"]["go"] == "system/sys"


def test_les_fichiers_non_charges_du_preset_joue_sont_rouges_repares_oranges(rack, monkeypatch):
    monkeypatch.setattr(rack, "rig_check", {"t": time.time(), "ok": False, "checked": 3,
                                            "issues": [{"kind": "nam", "expected": "x.nam", "repaired": False}]})
    d = H.facts(fresh=True)
    assert _by(d, "playing")["level"] == "bad" and "1 file not loaded (nam)" in _by(d, "playing")["text"]
    monkeypatch.setattr(rack, "rig_check", {"t": time.time(), "ok": False, "checked": 3,
                                            "issues": [{"kind": "ir", "expected": "x.wav", "repaired": True}]})
    d = H.facts(fresh=True)
    assert _by(d, "playing")["level"] == "warn" and "repaired after the build" in _by(d, "playing")["text"]


def test_une_erreur_lua_depuis_le_depart_est_dite_avec_sa_ligne_un_vieux_journal_non(rack, tmp_path):
    p = tmp_path / "presets" / ".lua-errors.log"
    p.write_text("2026-10-19 22:01:03 golem_rig.lua:120: attempt to index nil\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(p, (old, old))                                     # plus vieux que le départ du bridge (−120 s)
    assert _by(H.facts(fresh=True), "scripts")["level"] == "ok"
    p.write_text("2026-10-20 10:00:00 golem_rig.lua:120: attempt to index nil\n2026-10-20 10:00:05 golem_click.lua:9: boom\n", encoding="utf-8")
    f = _by(H.facts(fresh=True), "scripts")
    assert f["level"] == "warn" and f["text"].endswith("golem_click.lua:9: boom")


def test_la_derive_de_l_environnement_est_datee_et_gardee(rack, tmp_path, monkeypatch):
    """Premier passage : rien à comparer. Même valeurs : rien. REAPER et le buffer changent : deux changements
    datés, dits sur la ligne, gardés dans config/.env-snapshot.json. None ne compte jamais comme un changement."""
    now = time.time()
    cur = {"golem": "v0.40", "reaper": "7.27", "os": "Linux 6.8", "card": "Volt 276", "samplerate": 48000, "bsize": 128,
           "plugins": 61, "governor": "performance", "kernel": "x"}
    r = H.env_update(dict(cur), now=now - 86400)
    assert r["first"] is True and r["changes"] == []
    assert H.env_update(dict(cur), now=now - 80000) == {"first": False, "changes": []}
    r = H.env_update(dict(cur, reaper="7.80", bsize=256, card=None), now=now)
    assert [(c["key"], c["from"], c["to"]) for c in r["changes"]] == [("reaper", "7.27", "7.80"), ("bsize", 128, 256)]
    saved = json.load(open(tmp_path / "config" / ".env-snapshot.json", encoding="utf-8"))
    assert saved["values"]["card"]["value"] == "Volt 276", "une sonde muette ne remplace pas la valeur connue"
    assert len(saved["changes"]) == 2
    # la ligne de Health : un changement depuis le départ du bridge est orange et nommé
    monkeypatch.setattr(H, "env_current", lambda: dict(cur, reaper="7.80", bsize=256, plugins=63))
    f = _by(H.facts(fresh=True), "environment")
    assert f["level"] == "warn" and f["text"] == "changed: REAPER 7.27 → 7.80 · buffer 128 → 256 · plugins 61 → 63"
    # la version de golem seule : une information en vert, jamais une pastille (Alex, 2026-10-20)
    H.env_update(dict(cur, reaper="7.80", bsize=256, plugins=63), now=now)
    monkeypatch.setattr(H, "START", time.time())
    monkeypatch.setattr(H, "env_current", lambda: dict(cur, reaper="7.80", bsize=256, plugins=63, golem="v0.41"))
    f = _by(H.facts(fresh=True), "environment")
    assert f["level"] == "ok" and f["text"] == "golem updated: golem v0.40 → v0.41 · nothing else changed"
    # et quand l'environnement est stable depuis le départ : vert
    monkeypatch.setattr(H, "START", time.time() + 1)
    assert _by(H.facts(fresh=True), "environment")["level"] == "ok"


def test_le_cache_rend_le_meme_document_pendant_cinq_secondes(rack, monkeypatch):
    d1 = H.facts(fresh=True)
    monkeypatch.setattr(rack, "xruns_recent", 50)
    assert H.facts() is d1, "le cache sert la page sans resonder"
    assert _by(H.facts(fresh=True), "dropouts")["level"] == "bad"


def test_la_route_est_un_get_sensible_mais_le_pouls_reste_public(monkeypatch):
    monkeypatch.setattr(auth, "_device_by_token", lambda t: {"id": "d1"} if t == "ok" else None)

    def req(path, host="192.168.0.50", token=""):
        return NS(method="GET", url=NS(path=path, hostname="192.168.0.22"), client=NS(host=host),
                  headers={"x-golem-token": token} if token else {}, cookies={}, query_params={})
    assert auth.allowed_http(req("/api/health/facts")) is False            # LAN, sans jeton
    assert auth.allowed_http(req("/api/health/facts", token="ok")) is True
    assert auth.allowed_http(req("/api/health/facts", host="127.0.0.1")) is True
    assert auth.allowed_http(req("/api/health")) is True                    # le lanceur, avant appairage


def test_la_route_rend_les_faits_du_cache(rack):
    from bridge import routes_health as R
    d = R.health_facts()
    assert d["verdict"]["level"] == "ok" and len(d["facts"]) == 11
    assert R.health_facts(fresh=1)["at"] >= d["at"]
