# SPDX-License-Identifier: GPL-3.0-or-later
"""Les captures d'usine sur un PC Windows neuf (2026-11-03) : le Cloudflare de TONE3000 refusait le User-Agent
« Python-urllib » (403 « error code: 1010 ») et chaque capture attendait ~4 min de nouvelles tentatives inutiles ;
puis l'A1 épinglé par l'usine (tone 2282, model 75210) était écarté par son jumeau A2 — « no model selected »."""
import pytest

from bridge import rig
from bridge import routes_t3k as R


# ── le User-Agent ────────────────────────────────────────────────────────────────────────────────────────────────
def test_chaque_requete_tone3000_dit_golem(monkeypatch):
    seen = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"
    monkeypatch.setattr(R._t3k.urllib.request, "urlopen", lambda req, timeout=None: seen.append(req) or Resp())
    R._t3k.http_json("GET", "https://www.tone3000.com/api/v1/models/1/download/x.nam", raw=True)
    ua = seen[0].get_header("User-agent")
    assert ua == R._t3k.USER_AGENT and "golem" in ua and "Mozilla" not in ua


def test_un_ua_pose_par_l_appelant_est_garde(monkeypatch):
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req)
        raise OSError("no network")
    monkeypatch.setattr(R._t3k.urllib.request, "urlopen", urlopen)
    with pytest.raises(OSError):
        R._t3k.http_json("GET", "https://x", headers={"User-Agent": "custom"})
    assert seen[0].get_header("User-agent") == "custom"


# ── 403 Cloudflare 1010 : pas de nouvelle tentative ──────────────────────────────────────────────────────────────
def test_un_refus_cloudflare_1010_echoue_tout_de_suite(monkeypatch, tmp_path):
    calls, sleeps = [], []
    monkeypatch.setattr(R._blib.t3k, "access_token", lambda: "tok")
    monkeypatch.setattr(R._blib.t3k, "http_json", lambda *a, **k: calls.append(a) or (403, "error code: 1010\n"))
    monkeypatch.setattr(R._blib.time, "sleep", lambda s: sleeps.append(s))
    r = R._blib.download("https://www.tone3000.com/api/v1/models/1/download/x.nam", str(tmp_path / "x.nam"))
    assert str(r).startswith("err403") and "1010" in r
    assert len(calls) == 1 and sum(sleeps) < 5, "avant : 5 essais et 20+40+60+80 s de pauses par capture"


def test_un_403_anti_rafale_reste_retente(monkeypatch, tmp_path):
    answers = [(403, "rate limited"), (200, b"{}")]
    monkeypatch.setattr(R._blib.t3k, "access_token", lambda: "tok")
    monkeypatch.setattr(R._blib.t3k, "http_json", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(R._blib.time, "sleep", lambda s: None)
    assert R._blib.download("https://x/y.nam", str(tmp_path / "y.nam")) == "ok"


# ── un id demandé passe avant l'écart A1/A2 ──────────────────────────────────────────────────────────────────────
PAGES = {
    "/api/v1/tones/7": {"title": "Amp 7", "gear": "amp", "format": "nam", "user": {"username": "maker"}},
    "/api/v1/models?tone_id=7&architecture=2&page=1": {"data": [
        {"id": 902, "name": "Clean G7", "architecture_version": "2", "model_url": "https://t/902.nam"},
        {"id": 903, "name": "Lead", "architecture_version": "2", "model_url": "https://t/903.nam"}], "total_pages": 1},
    "/api/v1/models?tone_id=7&page=1": {"data": [
        {"id": 102, "name": "Clean G7", "architecture_version": "1", "model_url": "https://t/102.nam"},
        {"id": 103, "name": "Lead", "architecture_version": "1", "model_url": "https://t/103.nam"}], "total_pages": 1},
}


@pytest.fixture
def install(monkeypatch, tmp_path):
    monkeypatch.setattr(rig, "_platform", lambda: "linux")              # l'A2 se lit : les jumeaux A1 sont écartés
    monkeypatch.setattr(R._t3k, "api_get", lambda p: (200, PAGES[p]))
    monkeypatch.setattr(R, "INDEX", str(tmp_path / "tones-index.json"))
    got = []
    monkeypatch.setattr(R, "_download_model", lambda m, reldir, title, fmt: got.append(m["id"]) or {"id": m["id"]})
    monkeypatch.setattr(R, "_ST", dict(R._ST))
    return got


def test_l_a1_epingle_par_l_usine_s_installe_meme_avec_un_jumeau_a2(install):
    assert [m["id"] for m in R._fetch_models(7)] == [902, 903], "navigation : l'A2 seul, les jumeaux A1 écartés"
    R._install_worker(7, [102])
    assert R._ST["phase"] == "done", R._ST
    assert install == [102], "l'usine dit 102 : on installe 102 (avant : « no model selected »)"


def test_les_ids_demandes_gardent_l_ordre_prefere(install):
    R._install_worker(7, [102, 903])
    assert R._ST["phase"] == "done" and install == [903, 102]


def test_un_id_inconnu_reste_une_erreur_dite(install):
    R._install_worker(7, [999])
    assert R._ST["phase"] == "error" and R._ST["error"] == "no model selected"
