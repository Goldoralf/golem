# SPDX-License-Identifier: GPL-3.0-or-later
"""L'instantané de la coquille golem.fm (docs/shell.md) : tout ce qui identifie quelqu'un ou une machine est retiré, et un
fichier où il reste UNE trace n'est jamais écrit — il part sur un site public."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import shell_snapshot as S  # noqa: E402


@pytest.fixture(autouse=True)
def _pseudos():
    S._PSEUDO.clear(); S.KNOWN.clear()
    yield
    S._PSEUDO.clear(); S.KNOWN.clear()


@pytest.fixture(autouse=True)
def _hosts_fixes(monkeypatch):
    # le nom de CETTE machine ne doit pas décider du test (un FQDN « host.docker.internal » expurgeait « host »)
    monkeypatch.setattr(S, "HOSTS", {"studiopc"})


@pytest.mark.parametrize("raw,want", [
    ("write to alex@example.com", "write to <email>"),
    ("rack at 192.168.1.42:8770", "rack at <ip>:8770"),
    ("link fe80::1 and 2001:db8:85a3:0:0:8a2e:370:7334", "link <ip> and <ip>"),
    ("card 00:1A:2B:3C:4D:5E", "card <mac>"),
    ("this is golem_2", "this is golem_0"),
    ("nas starnas.local", "nas <host>"),
    ("/media/alex/HD Save/golem", "<path>"),
    ("/run/user/1000/gvfs/smb-share:server=x,share=y", "<path>"),
    ("C:\\Users\\alex\\golem", "<path>"),
])
def test_ce_qui_identifie_est_retire(raw, want):
    assert S.redact_str(raw) == want


def test_ce_qui_ne_identifie_pas_reste():
    for keep in ("2026-10-09 02:45:05", "v0.54.1", "Am", "120 bpm", "Paper Kite", "12:34", "assets/models/x.nam"):
        assert S.redact_str(keep) == keep


def test_un_chemin_du_rack_devient_relatif_un_chemin_perso_devient_tilde():
    assert S.redact_str(os.path.join(S.ROOT, "songs", "a.golem")) == "songs/a.golem"
    assert S.redact_str(os.path.expanduser("~") + "/golem-inbox") == "~/golem-inbox"


def test_les_champs_secrets_et_la_tonalite():
    out = S.redact({"token": "abc", "password": "x", "email": "a@b.co", "ip": "1.2.3.4", "serial": "golem_2",
                    "key": "Am", "nested": {"api_key": "zz", "host": "titan"}})
    assert out["token"] == out["password"] == out["email"] == out["ip"] == out["serial"] == S.REDACTED
    assert out["nested"]["api_key"] == out["nested"]["host"] == S.REDACTED
    assert out["key"] == "Am"                          # la tonalité d'un morceau n'est pas une clé secrète


def test_les_personnes_ont_un_pseudonyme_constant():
    data = {"inputs": [{"person": "alex", "person_name": "Alex"}, {"person": "sam", "person_name": "Sam"}],
            "loaded_by": "Alex", "editor": "Alex's iPhone"}
    S.collect(data)
    out = S.redact(data)
    a, b = out["inputs"]
    assert a["person"] == a["person_name"] == out["loaded_by"] == "Musician A"   # id et nom : la même personne
    assert b["person_name"] == "Musician B" and out["editor"] == "Device A"


def test_la_verification_voit_ce_que_l_expurgation_aurait_rate():
    assert S.leaks({"note": "mail alex@example.com"}) and S.leaks({"person_name": "Alex"}) and S.leaks({"token": "x"})
    assert S.leaks(S.redact({"person_name": "Alex", "note": "ok"})) == []


def test_un_fichier_ou_il_reste_une_trace_n_est_pas_ecrit(tmp_path, monkeypatch):
    data = {"/api/presets": [{"id": "a"}], "/api/state": {"note": "alex@example.com"}}
    monkeypatch.setattr(S, "_get", lambda base, path: data[path])
    monkeypatch.setattr(S, "redact", lambda x, key=None: x)                       # une expurgation qui raterait
    r = S.snapshot("http://x", str(tmp_path), ["/api/presets", "/api/state"], log=lambda *a: None)
    assert r["written"] == ["/api/presets"] and r["refused"][0][0] == "/api/state"
    assert not os.path.exists(tmp_path / "api" / "state.json")


def test_les_lectures_interdites_ne_sont_jamais_lues(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(S, "_get", lambda base, path: asked.append(path) or {})
    reads = ["/api/auth/devices", "/api/network", "/api/integrations", "/api/connect", "/api/presets"]
    r = S.snapshot("http://x", str(tmp_path), reads, log=lambda *a: None)
    assert asked == ["/api/band", "/api/presets"] and len(r["skipped"]) == 4      # le roster : LU pour relever…
    assert not (tmp_path / "api" / "band.json").exists() and r["written"] == ["/api/presets"]   # …jamais écrit


def test_le_chemin_du_fichier_est_portable():
    p = S.out_path("/o", "/api/song/rs:abc?x=1")
    assert p.replace(os.sep, "/") == "/o/api/song/rs%3Aabc__x%3D1.json"         # pas de « : » (Windows)
    assert S.out_path("/o", "/api/preset/patch:kim").endswith("patch%3Akim.json")


def test_les_personnes_relevees_partout_meme_en_cle(tmp_path):
    """Troisième relecture : `persons: {"alex": {…}}` (réglages Rec d'un preset), `people: {"1": "alex"}` (une prise),
    et le roster `people: [{id, name, roles…}]` — dont les CLÉS de fiche (`name`, `id`, `owner`) ne sont pas des personnes."""
    roster = {"band": {"name": "Night Shift", "people": [{"id": "alex", "name": "Alex", "roles": ["guitar"], "rights": "owner"}]}}
    preset = {"name": "RIOT", "rec": {"persons": {"alex": {"keep_s": 30}}}, "take": {"people": {"1": "alex"}}}
    S.collect(roster); S.collect(preset)
    assert set(S.KNOWN) == {"alex"}                                     # ni « name », ni « id », ni « owner »
    out = S.redact(preset)
    assert out["name"] == "RIOT" and list(out["rec"]["persons"]) == ["Musician A"] and out["take"]["people"]["1"] == "Musician A"
    assert S.leaks(out) == []


def test_un_nom_complet_sans_accents_meme_dans_une_phrase():
    S.remember("Alex Martin")                                     # le nom git du dépôt
    out = S.redact({"source": {"by": "Alex Mârtin"}, "note": "chart by Alex Mârtin, 2026"})
    assert out["source"]["by"] == "Musician A" and out["note"] == "chart by Musician A, 2026"


def test_les_credits_publics_restent():
    """`author` et `by` portent aussi les crédits des logiciels libres et des captures : ils restent."""
    S.remember("alex")
    out = S.redact({"components": [{"name": "zeroconvo", "by": "Robin Gareus"}], "author": "Mike Oliphant",
                    "type": "eq-graphic", "label": "Whammy DT"})
    assert out == {"components": [{"name": "zeroconvo", "by": "Robin Gareus"}], "author": "Mike Oliphant",
                   "type": "eq-graphic", "label": "Whammy DT"}             # « graphic » contient « alex » : intact


def test_la_separation_n_entre_jamais_dans_une_coquille():
    """L'état de la séparation porte le nom de l'extrait de l'utilisateur et l'indice d'une clé (docs/separation.md §1)."""
    assert S.NEVER.match("/api/separation") and S.NEVER.match("/api/separation/keys")
    out = S.redact({"services": [{"key": {"set": True, "hint": "…a1b2"}}]})
    assert "a1b2" not in str(out)


# ── l'audio de la démo et la page Separation du rack de référence (2026-11-04) ──
def test_le_dossier_de_la_demo_est_le_seul_chemin_qui_passe():
    assert S.redact_str("/home/golem/opt/audio-separator/bin/audio-separator") == "/home/golem/opt/audio-separator/bin/audio-separator"
    assert S.redact_str("/media/someone/disk/x.wav") == "<path>"
    assert S.leaks({"program": "/home/golem/opt/x"}) == []
    assert S.leaks({"program": "/home/someone/opt/x"})


def test_la_page_separation_du_rack_de_reference(tmp_path, monkeypatch):
    home = os.path.expanduser("~").rstrip("/")
    page = {"engines": [{"label": "local-model", "program": home + "/opt/audio-separator/bin/audio-separator",
                         "args": ["{input}", "--model_file_dir", home + "/opt/audio-separator/models"]}],
            "excerpt": {"name": "A protected song (original).mp3", "seconds": 30.0, "start": 59.6}, "threads": 4}
    monkeypatch.setattr(S, "_get", lambda base, read: json.loads(json.dumps(page)))
    S.separation_from("http://rack", str(tmp_path))
    got = json.loads((tmp_path / "api" / "separation.json").read_text())
    e = got["engines"][0]
    assert e["program"] == "/home/golem/opt/audio-separator/bin/audio-separator"
    assert e["args"][2] == "/home/golem/opt/audio-separator/models"
    assert got["excerpt"] == {"name": S.DEMO_EXCERPT, "seconds": 30.0, "start": 59.6} and got["threads"] == 4


def test_la_prise_de_demo_ne_garde_que_la_musique(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo_take", os.path.join(os.path.dirname(S.__file__), "demo_take.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    src = tmp_path / "perf-20261104-000346"
    src.mkdir()
    (src / "Mix.wav").write_bytes(b"RIFF")
    (src / "take.json").write_text(json.dumps({
        "preset": "patch:factory-guitar-jazz-clean", "preset_name": "Jazz Clean", "bpm": 180, "scene": "D",
        "band": {"id": "b_x", "name": "A Band"}, "people": {"2": "someone"}, "session": "sess-1", "guitar": "eight",
        "machine_mode": "studio", "upload": {"rec_id": 3},
        "marks": [{"sec": 0, "kind": "scene", "value": "D"}, {"sec": 1, "kind": "flag", "by": "someone"}]}))
    dst = m.demo_take(str(src), str(tmp_path / "out"), "Rooftop Prowl — solo")
    got = json.loads(open(os.path.join(dst, "take.json")).read())
    assert got["preset_name"] == "Jazz Clean" and got["title"] == "Rooftop Prowl — solo" and got["bpm"] == 180
    for k in ("band", "people", "session", "guitar", "machine_mode", "upload"):
        assert k not in got, k
    assert got["marks"] == [{"sec": 0, "kind": "scene", "value": "D"}]
    assert os.path.isfile(os.path.join(dst, "Mix.wav"))
