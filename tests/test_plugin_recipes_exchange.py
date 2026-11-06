# SPDX-License-Identifier: GPL-3.0-or-later
"""Le cycle des recettes avec golem.fm (docs/plugin-recipes.md §2-§8), contre un FAUX golem.fm : demande d'analyse,
refus, brouillon reçu par la file, vérification À CÔTÉ de la file (ack différé, pas de doublon), validation, partage,
et signalement d'une recette partagée qui ne tient pas ici."""
import json
import time

import pytest

from bridge import plugin_capture as PC, plugin_recipes as R, tones_jobs as TJ

PLUG = "VST3: Example Lead Suite (Example Vendor)"
DRAFT = {"schema": 2, "full": {"label": "Full rig", "gear": "amp-cab", "off": {},
                               "refuse": [{"id": "logos", "when": {"Logos Active": "Active"}, "why": "w", "confidence": "low"}],
                               "captured": [{"id": "amp", "when": {"Active Amp": "Active"}, "why": "w", "confidence": "high"}]},
         "split": {"parts": [{"id": "head", "gear": "amp", "block": "amp-nam", "off": {}, "why": "w", "confidence": "low"}]}}


@pytest.fixture
def rack(monkeypatch, tmp_path):
    calls = []
    answers = {}
    monkeypatch.setattr(R, "LOCAL_DIR", tmp_path / "plugin-recipes")
    monkeypatch.setattr(PC, "train_home", lambda: tmp_path / "nam-train")
    monkeypatch.setattr(PC, "_live_state", lambda b: {"kind": "vst_chunk", "chunk": "CHUNK"})
    monkeypatch.setattr(R, "sheet", lambda b, p: {"plugin": p, "os": "windows", "plugin_version": "1.1.0.0",
                                                  "params": [], "steps": {}, "instrument": False})

    def http(method, path, body=None, timeout=30):
        calls.append((method, path.split("?")[0], body))
        return answers.get((method, path.split("?")[0]), (404, {"error": "not found"}))
    monkeypatch.setattr(R, "_http", http)
    acks = []
    monkeypatch.setattr(TJ, "_req", lambda m, path, body=None: acks.append((path, body)))
    import bridge.reamp as RA
    monkeypatch.setattr(RA, "busy_reason", lambda idle=True: None)
    return {"calls": calls, "answers": answers, "acks": acks}


def wait_state(plugin, *states, t=5):
    end = time.time() + t
    while time.time() < end:
        d = R.load(plugin) or {}
        if d.get("state") in states:
            return d
        time.sleep(0.02)
    raise AssertionError(f"state {R.load(plugin)}")


def test_une_analyse_demandee_puis_le_brouillon_mesure_et_acquitte(rack, monkeypatch):
    rack["answers"][("POST", R.API + "/analyze")] = (202, {"request_id": "rq-1"})
    d = R.analyze("vst-host-xf72", PLUG)
    assert d["state"] == "analyzing" and d["request_id"] == "rq-1" and d["plugin_version"] == "1.1.0.0"
    assert [c[:2] for c in rack["calls"]] == [("GET", R.API), ("POST", R.API + "/analyze")]

    monkeypatch.setattr("bridge.tones_jobs._blob_bytes", lambda j, n: json.dumps(DRAFT).encode())
    monkeypatch.setattr(R, "verify", lambda draft, sht, p, chunk, work: {
        "status": "partial", "verified": ["amp", "head"], "rejected": [{"id": "logos", "measure": {}, "why": "x"}],
        "declared": [], "errors": []})
    TJ._inflight.add(77)
    assert R.on_job({"id": 77, "action": "plugin-recipe", "request_id": "rq-1", "plugin": PLUG, "sha": "a" * 64}) is R.ASYNC_ACK
    doc = wait_state(PLUG, "to-validate")
    for _ in range(50):
        if rack["acks"]:
            break
        time.sleep(0.02)
    path, body = rack["acks"][0]
    assert path == "/api/ext/tones/jobs/77/ack" and body["ok"] is True
    assert body["result"]["status"] == "partial" and body["result"]["request_id"] == "rq-1"
    assert 77 not in TJ._inflight                                      # l'ack parti, le job quitte « en cours »
    assert doc["verification"]["status"] == "partial"


def test_valider_rend_la_recette_utilisable_sans_ce_que_la_mesure_a_rejete(rack, monkeypatch):
    R._save(PLUG, state="to-validate", os="windows", plugin_version="1.1.0.0", draft=DRAFT,
            verification={"status": "partial", "rejected": [{"id": "logos"}]})
    assert R.validated_recipe(PLUG) is None                            # pas encore validée : elle ne sert à rien
    rack["answers"][("POST", R.API)] = (201, {"ok": True})
    R.validate(PLUG, edits=[{"id": "amp", "label": "Amp (Clean)"}])
    rec = PC.recipe_for(PLUG)
    assert [c["id"] for c in rec["full"]["refuse"]] == []               # le rejeté est retiré
    assert [c["id"] for c in rec["full"]["captured"]] == ["amp"]
    method, path, body = rack["calls"][-1]
    assert (method, path) == ("POST", R.API) and body["plugin_version"] == "1.1.0.0" and body["format"] == "VST3"
    assert body["edits"] == [{"id": "amp", "label": "Amp (Clean)"}]


def test_les_erreurs_de_golem_fm_sont_lues_sous_detail(monkeypatch):
    """La VRAIE forme (FastAPI) : le faux golem.fm du dessus parle comme le rack l'imaginait, pas comme golem.fm
    répond — ce test passe par `_http` lui-même, sur des réponses HTTP brutes."""
    import io
    import urllib.error
    monkeypatch.setattr("bridge.golemfm._cfg", lambda: ("http://golem.fm", "tok"))
    bodies = iter([b'{"detail": {"code": "unsupported", "message": "reorderable pedalboard"}}',
                   b'{"detail": {"error": "ai_quota", "used": 50, "limit": 50, "message": "quota"}}',
                   b'{"detail": "unknown os macos"}'])

    def raise_http(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 409, "x", {}, io.BytesIO(next(bodies)))
    monkeypatch.setattr("urllib.request.urlopen", raise_http)
    st, b = R._http("POST", R.API + "/analyze", {})
    assert b["code"] == "unsupported" and b["error"] == "reorderable pedalboard"
    assert R._http("POST", R.API + "/analyze", {})[1]["error"] == "ai_quota"
    assert R._http("GET", R.API)[1] == {"error": "unknown os macos"}


def test_un_refus_de_golem_fm_est_dit(rack):
    rack["answers"][("POST", R.API + "/analyze")] = (409, {"code": "unsupported", "error": "reorderable pedalboard"})
    assert R.analyze("b", PLUG)["state"] == "unsupported"
    rack["answers"][("POST", R.API + "/analyze")] = (429, {"error": "ai_quota"})
    d = R.analyze("b", PLUG)
    assert d["state"] == "failed" and "quota" in d["error"]


def test_une_nouvelle_analyse_oublie_la_demande_d_avant(rack):
    R._save(PLUG, state="failed", request_id="old", error="broken")
    seen = []
    rack["answers"][("POST", R.API + "/analyze")] = (202, {"request_id": "new"})
    orig = R.sheet
    R.sheet = lambda b, p: (seen.append(R.load(PLUG).get("request_id")), orig(b, p))[1]
    try:
        d = R.analyze("b", PLUG)
    finally:
        R.sheet = orig
    assert seen == [None]                                              # pendant la fiche : plus d'ancienne demande
    assert d["request_id"] == "new" and d["error"] is None


def test_une_demande_sans_job_se_lit_par_son_statut(rack):
    R._save(PLUG, state="analyzing", request_id="rq-9")
    rack["answers"][("GET", R.API + "/analyze/rq-9")] = (200, {"status": "failed", "error": "ai down"})
    assert R.poll(PLUG)["state"] == "failed"


def test_une_recette_partagee_est_remesuree_ici_et_signalee_si_elle_ne_tient_pas(rack, monkeypatch):
    rack["answers"][("GET", R.API)] = (200, {"recipe": DRAFT, "validated": {"count": 4}, "version_match": False})
    monkeypatch.setattr(R, "verify", lambda *a, **k: {"status": "partial", "verified": ["amp"], "errors": [],
                                                      "rejected": [{"id": "head", "measure": {"peak": 0}, "why": "silence"}],
                                                      "declared": []})
    d = R.analyze("b", PLUG)
    assert d["state"] == "verifying" and d["shared"] is True
    wait_state(PLUG, "to-validate")
    for _ in range(50):
        if any(c[1] == R.API + "/report" for c in rack["calls"]):
            break
        time.sleep(0.02)
    rep = [c for c in rack["calls"] if c[1] == R.API + "/report"]
    assert rep and rep[0][2]["rejected"][0]["id"] == "head"
    assert all(c[1] != R.API + "/analyze" for c in rack["calls"])        # rien à analyser : une recette existait


def test_la_mesure_attend_que_le_rack_soit_libre(rack, monkeypatch):
    import bridge.reamp as RA
    seq = iter(["a take is recording", None])
    monkeypatch.setattr(RA, "busy_reason", lambda idle=True: next(seq, None))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    monkeypatch.setattr(R, "verify", lambda *a, **k: {"status": "verified", "verified": ["amp"], "rejected": [],
                                                      "declared": [], "errors": []})
    work = PC.train_home().parent / "recipes" / R._slug(PLUG)
    work.mkdir(parents=True)
    (work / "sheet.json").write_text("{}")
    (work / "state.json").write_text('{"chunk": "C"}')
    R._save(PLUG, state="verifying")
    R._start_verify(PLUG, DRAFT, "rq-2", ack_job=None)
    assert wait_state(PLUG, "to-validate")["waiting"] is None


def test_les_corrections_du_musicien_servent_renommer_et_retirer(rack):
    """2026-10-10 : on peut corriger une ligne avant de valider. Retirer une partie du split retire le split."""
    R._save(PLUG, state="to-validate", os="windows", plugin_version="1.1.0.0", draft=DRAFT,
            verification={"status": "verified", "rejected": []})
    rack["answers"][("POST", R.API)] = (201, {})
    R.validate(PLUG, edits=[{"id": "amp", "label": "Amp (Clean)"}, {"id": "head", "removed": True}])
    rec = PC.recipe_for(PLUG)
    assert [c["label"] for c in rec["full"]["captured"]] == ["Amp (Clean)"]
    assert "split" not in rec                                          # une capture par effet incomplète serait fausse
    assert [c["id"] for c in rec["full"]["refuse"]] == ["logos"]       # non rejeté, non retiré : il sert
