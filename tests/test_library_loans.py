# SPDX-License-Identifier: GPL-3.0-or-later
"""Les prêts de Library au groupe, face rack (docs/library-loans.md). Ce que ces tests gardent : un pack
prêté se trouve APRÈS les nôtres et le nôtre gagne ; sa provenance est notée à l'installation ; la synchro
ne le renvoie JAMAIS (pack entier par uid, fichier d'un pack agrégé par sha256, blob jamais téléversé) ;
le Store refuse un preset qui en dépend ; un prêt retiré est marqué, jamais effacé ; un patch qui arrive
peut tirer une capture prêtée ; le rappel ne retente pas en boucle."""
import pytest

from bridge import loans, tones_jobs, tones_sync

WHO_R = {"band": {"id": "b_1", "name": "Night Shift"}, "owner": {"handle": "alex"}}
WHO_G = {"band": {"id": "b_2", "name": "Earth"}, "owner": {"handle": "sam"}}


def _pack(uid, kind="amp", shas=("aa",), cat=None):
    return {"uid": uid, "kind": kind, "title": uid.upper(),
            "extra": {"catalog_id": cat or uid.split(":", 1)[1]},
            "assets": [{"sha256": s, "bytes": 10, "filename": f"{s}.nam", "extra": {"rel": f"assets/amps/{s}.nam"}} for s in shas]}


def _manifest(own=(), lent=()):
    return {"rev": 1, "packs": list(own), "missing_blobs": [], "lent_rev": "r1",
            "lent": list(lent)}


@pytest.fixture(autouse=True)
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(loans, "REG", str(tmp_path / ".lent.json"))
    monkeypatch.setattr(loans, "_server", lambda: "http://localhost:5173")
    loans._tried.clear(); loans._pulling.clear()
    return tmp_path


# ── trouver ──────────────────────────────────────────────────────────────────────────────────
def test_les_notres_dabord_puis_les_prets_et_le_notre_gagne():
    m = _manifest(own=[_pack("t3k:1")], lent=[{**WHO_R, "packs": [{**_pack("t3k:1"), "loan": {}}, {**_pack("t3k:2"), "loan": {}}]}])
    assert loans.find_pack(m, "t3k:1") == (m["packs"][0], None)          # le même uid chez nous : le nôtre
    p, who = loans.find_pack(m, "t3k:2")
    assert p["uid"] == "t3k:2" and who == [{"band": "Night Shift", "band_id": "b_1", "owner": "alex"}]
    assert loans.find_pack(m, "t3k:9") == (None, None)
    assert "t3k:1" not in loans.lent_packs(m)


def test_le_meme_pret_de_deux_sections_porte_ses_deux_provenances():
    m = _manifest(lent=[{**WHO_R, "packs": [_pack("t3k:2")]}, {**WHO_G, "packs": [_pack("t3k:2")]}])
    assert [w["owner"] for w in loans.lent_packs(m)["t3k:2"][1]] == ["alex", "sam"]


# ── le registre ──────────────────────────────────────────────────────────────────────────────
def test_retire_marque_jamais_efface_et_redevenu_notre_sort_du_registre():
    loans.record_install("t3k:2", _pack("t3k:2"), [{"owner": "alex"}])
    loans.record_install("t3k:3", _pack("t3k:3", shas=("cc",)), [{"owner": "alex"}])
    m = _manifest(own=[_pack("t3k:3", shas=("cc",))],                  # Keep a copy : t3k:3 est à nous
                  lent=[{**WHO_R, "packs": [], "incomplete": [{"kind": "patch", "ref": "polaris"}],
                         "gone": [{"kind": "tone", "ref": "t3k:9701"}]}])
    d = loans.refresh(m)
    assert d["installed"]["t3k:2"]["state"] == "no_longer_lent"          # retiré : marqué, gardé
    assert "t3k:3" not in d["installed"]                                  # redevenu nôtre
    assert d["incomplete"][0]["ref"] == "polaris" and d["gone"][0]["ref"] == "t3k:9701"
    assert d["lent_rev"] == "r1"


# ── LA GARDE DE LA SYNCHRO ───────────────────────────────────────────────────────────────────
def test_la_synchro_ne_renvoie_jamais_un_pret():
    loans.record_install("t3k:2", _pack("t3k:2", shas=("aa",)), [])
    loans.record_item("ss", {"kind": "sample", "name": "Hit"}, [])
    packs = [_pack("t3k:2", shas=("aa",)), _pack("t3k:5", shas=("bb",)),
             {"uid": "local:samples", "kind": "sample", "assets": [{"sha256": "ss"}, {"sha256": "mine"}]},
             {"uid": "local:synth-vital-x", "kind": "synth", "assets": [{"sha256": "aa"}]}]
    blob_map = {"aa": "/a", "bb": "/b", "ss": "/s", "mine": "/m"}
    out, dropped = loans.filter_packs(packs, blob_map)
    assert [p["uid"] for p in out] == ["t3k:5", "local:samples"]         # pack prêté et pack vidé : dehors
    assert [a["sha256"] for a in out[1]["assets"]] == ["mine"]            # le sample prêté sort du pack agrégé
    assert set(blob_map) == {"bb", "mine"} and dropped == 3               # jamais téléversés


def test_sans_pret_la_synchro_est_intacte():
    packs = [_pack("t3k:5")]
    assert loans.filter_packs(packs) == (packs, 0)


def test_le_store_refuse_un_preset_qui_depend_dun_pret(monkeypatch):
    loans.record_install("t3k:2", _pack("t3k:2", shas=("aa",)), [{"owner": "alex", "band": "Night Shift"}])
    from bridge import preset_export
    monkeypatch.setattr(preset_export, "build_export", lambda pid: ({"deps": [{"uid": "t3k:2", "sha256": "aa", "source": "maestrium"}]}, {}))
    monkeypatch.setattr(tones_sync, "_req", lambda *a, **k: pytest.fail("rien ne doit partir"))
    r = tones_sync.publish_preset("paper-kite")
    assert r["ok"] is False and r["error"] == "uses T3K:2, lent by alex — keep a copy first"


# ── tirer à la demande ───────────────────────────────────────────────────────────────────────
def test_install_dun_pret_note_sa_provenance(monkeypatch, tmp_path):
    m = _manifest(lent=[{**WHO_R, "packs": [_pack("t3k:2", kind="synth", shas=("aa",))]}])
    monkeypatch.setattr(tones_jobs, "_req", lambda *a, **k: (200, m))
    got = []
    monkeypatch.setattr(tones_jobs, "_download_raw", lambda sha, dest: got.append(sha))
    tones_jobs._install("t3k:2")
    assert got == ["aa"] and loans.is_lent_uid("t3k:2")
    assert loans.status()["installed"]["t3k:2"]["lent_by"][0]["owner"] == "alex"


def test_un_patch_qui_arrive_voit_les_captures_pretees(monkeypatch):
    m = _manifest(own=[_pack("t3k:1")], lent=[{**WHO_R, "packs": [_pack("t3k:2", kind="cab"), _pack("local:kit-x", kind="kit")]}])
    monkeypatch.setattr(tones_jobs, "_req", lambda *a, **k: (200, m))
    tones = tones_jobs._manifest_tones()
    assert [t["uid"] for t in tones] == ["t3k:1", "t3k:2"]                  # les nôtres d'abord, pas le kit
    assert tones[1]["lent_by"][0]["owner"] == "alex"


def test_le_rappel_tire_une_capture_pretee_une_fois(monkeypatch):
    loans.refresh(_manifest(lent=[{**WHO_R, "packs": [_pack("t3k:2")]}]))
    monkeypatch.setattr(loans, "missing_lent_refs", lambda p: ["t3k:2"])
    started = []
    monkeypatch.setattr(loans.threading, "Thread", lambda target, **k: type("T", (), {"start": lambda s: started.append(target)})())
    assert loans.pull_for_preset({"id": "x"}) == ["t3k:2"]
    assert loans.pull_for_preset({"id": "x"}) == []                          # pas de boucle install -> reposer -> install
    assert len(started) == 1


def test_une_ref_se_resout_par_id_de_catalogue_ou_par_uid():
    d = loans.refresh(_manifest(lent=[{**WHO_R, "packs": [_pack("t3k:44209")]}]))
    assert loans.available_for_ref("44209", d) == "t3k:44209"
    assert loans.available_for_ref("t3k:44209", d) == "t3k:44209"
    assert loans.available_for_ref("amps/44209", d) == "t3k:44209"
    assert loans.available_for_ref("999", d) is None


def test_un_pret_vu_en_local_ne_survit_pas_en_prod_mais_ne_part_vers_aucun(monkeypatch):
    """Panneau de dev (2026-09-30) : chaque serveur a sa section — un rack qui bascule ne montre pas en
    prod un prêt vu en local ; mais le fichier prêté reste gardé hors de la synchro, QUEL QUE SOIT le serveur."""
    loans.record_install("t3k:2", _pack("t3k:2", shas=("aa",)), [{"owner": "dev"}])
    monkeypatch.setattr(loans, "_server", lambda: "https://golem.fm")
    assert loans.status()["installed"] == {}                                  # la section prod est vide
    out, dropped = loans.filter_packs([_pack("t3k:2", shas=("aa",))])
    assert out == [] and dropped == 1                                          # …et le prêt ne part pas en prod
    assert loans.lent_deps([{"uid": "t3k:2", "sha256": "aa"}])
