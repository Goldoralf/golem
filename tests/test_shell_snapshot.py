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
    home = os.path.expanduser("~")
    want = home + "/golem-inbox" if S._demo_path(home) else "~/golem-inbox"   # compte « golem » : la forme de la démo
    assert S.redact_str(home + "/golem-inbox") == want


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
    page = {"engines": [{"label": "model-x", "program": home + "/opt/audio-separator/bin/audio-separator",
                         "args": ["{input}", "--model_filename", "model-x_6s.yaml", "--model_file_dir", home + "/opt/m"],
                         "map": {"input_(Bass)_model-x_6s.wav": "bass", "input_(Vocals)_model-x_6s.wav": "vocals"},
                         "used_by": ["model-y + model-x"], "first_label": "model-y"}],
            "excerpt": {"name": "A protected song (original).mp3", "seconds": 30.0, "start": 59.6}, "threads": 4}
    monkeypatch.setattr(S, "_get", lambda base, read: json.loads(json.dumps(page)))
    S.separation_from("http://rack", str(tmp_path))
    got = json.loads((tmp_path / "api" / "separation.json").read_text())
    e = got["engines"][0]
    assert e["program"] == "/home/golem/opt/audio-separator/bin/audio-separator"
    # aucun modèle nommé : libellé, arguments, fichiers produits, renvois entre moteurs
    assert "model-" not in json.dumps(got)
    assert e["label"] == "Local engine 1" and e["map"] == {"input_(bass).wav": "bass", "input_(vocals).wav": "vocals"}
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


# ── l'outil ne dérive plus sans bruit (docs/release-tool-plan.md §3 bis, 2026-11-27) ────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_les_exemples_du_companion_visitent_des_pages_qui_existent():
    """Les routes du Companion ont changé le 2026-11-26 (?tab=live&mode=…) ; les exemples gardaient ?tab=now jusqu'au
    ré-épinglage suivant. Une route d'exemple du Companion doit être une des pages que check-ui parcourt."""
    cu = S._check_ui()
    phone = [ex["route"] for ex in S.EXAMPLES if ex["route"].startswith("/app/m.html")]
    assert phone and all(r in cu.PHONE_PAGES for r in phone), [r for r in phone if r not in cu.PHONE_PAGES]


def test_la_mini_coquille_cite_des_pages_et_des_exemples_qui_existent():
    cu = S._check_ui()
    names = [ex["name"] for ex in S.EXAMPLES]
    assert len(names) == len(set(names))                                   # un nom = un fichier d'exemple
    assert all(n in names for n in S.SMOKE_EXAMPLES)
    assert all(p in cu.RACK_PAGES + cu.PHONE_PAGES for p in S.SMOKE_PAGES)
    assert names[-1] == "reference-drums-bound"                            # son geste n'est pas défait : il reste le dernier


def test_le_moteur_du_banc_passe_apres_les_reglages_du_bridge_jetable():
    """check-ui.Bridge pose « pas de Golem Engine » pour que la CI et le poste voient la même machine ; l'instantané
    d'usine, lui, donne SON Golem Engine au bridge. L'ordre décide : ce que l'appelant impose passe en dernier."""
    src = open(os.path.join(ROOT, "tools", "check-ui.py"), encoding="utf-8").read()
    assert src.index('"no-golem-engine"') < src.index("env.update(self.extra_env)") < src.index("self.env = env")
    cu = S._check_ui()
    br = cu.Bridge(env={"GOLEM_ENGINE_DIR": "/the/engine"})
    try:
        assert br.extra_env == {"GOLEM_ENGINE_DIR": "/the/engine"}
    finally:
        br.tmp.cleanup()
    snap = open(os.path.join(ROOT, "tools", "shell_snapshot.py"), encoding="utf-8").read()
    assert "br.extra_env.update(engine_env)" in snap


def test_un_exemple_qui_echoue_defait_quand_meme_son_geste(monkeypatch):
    sent = []
    monkeypatch.setattr(S, "_post", lambda base, path, body: sent.append(path))

    def boom(*a, **k):
        raise RuntimeError("the anchor is gone")
    monkeypatch.setattr(S, "_make_example", boom)
    ex = {"name": "x", "title": "X", "preset": "p", "scene": "A", "route": "#/live",
          "gestures": [["/api/mode", {"id": "gig"}]], "undo": [["/api/mode", {"id": "home"}]]}
    with pytest.raises(RuntimeError):
        S.make_example("http://b", ex, {}, 0, lambda *_: None, "/tmp/out")
    assert sent == ["/api/mode", "/api/mode"]                              # le geste, puis son retour — malgré l'échec


def test_la_mini_coquille_dit_ce_qui_ne_va_pas(tmp_path):
    man = {"examples": ["golem-rising-live"], "pages": {"#/live": ["/api/state"], "#/designer": []},
           "written": ["/api/state", "/api/presets"]}
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps(man))
    res = {"refused": [("/api/x", "trace")], "examples_failed": [{"name": "companion-now", "why": "boom"}]}
    bad = "\n".join(S.smoke_problems(res, str(tmp_path)))
    for want in ("refused", "companion-now (boom)", "examples not made: reference-controllers, companion-now", "page #/designer made no read",
                 "the declared reference rack", "page #/system/gear/controllers made no read",
                 "page /app/m.html?tab=live&mode=now made no read", "/api/effects is not in the snapshot"):
        assert want in bad, want
    ok = {"examples": S.SMOKE_EXAMPLES, "pages": {p: ["/api/state"] for p in S.SMOKE_PAGES},
          "written": ["/api/state", "/api/presets", "/api/effects"], "rack": {"declared": {"commit": "x"}}, "kit_warnings": [],
          "screens": {n: "0123456789abcdef" for n in S.SMOKE_EXAMPLES}}
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps(ok))
    assert S.smoke_problems({"refused": [], "examples_failed": []}, str(tmp_path)) == []
    assert S.smoke_problems({"refused": []}, str(tmp_path / "nowhere"))[0].startswith("no SNAPSHOT.json")


def test_l_app_ne_lit_aucun_de_ses_fichiers_par_un_chemin_absolu():
    """golem.fm sert l'app sous /golem-app/<commit>/ : un `fetch('/app/…')` y donne 404 (2026-11-27, app/anim-tiles.mjs —
    le Companion de la coquille perdait ses animations). Un fichier de l'app se lit relativement au module."""
    import glob
    import re
    bad = []
    for path in glob.glob(os.path.join(ROOT, "app", "*.js")) + glob.glob(os.path.join(ROOT, "app", "*.mjs")):
        if path.endswith(".test.mjs"):
            continue
        for i, line in enumerate(open(path, encoding="utf-8"), 1):
            if re.search(r"""(fetch|import)\(\s*['"`]/app/""", line):
                bad.append("%s:%d" % (os.path.basename(path), i))
    assert bad == []


# ── la signature d'écran d'un exemple (demandée par golem.fm pour ses pages relues, 2026-11-27) ─────────────────────
def test_la_signature_suit_l_ecran_pas_ses_donnees():
    base = S.screen_signature("#/system/gear/controllers", None, ["gear.tab", "gear.list"], [], ["button | USB 1", "tab | Drums"])
    assert len(base) == 16 and base == S.screen_signature("#/system/gear/controllers", None, ["gear.list", "gear.tab"], [],
                                                         ["tab | Drums", "button | USB 2"])       # l'ordre et un chiffre : rien
    assert base != S.screen_signature("#/system/gear/controllers", None, ["gear.tab"], [], ["button | USB 1", "tab | Drums"])  # une ancre partie
    assert base != S.screen_signature("#/system/gear/controllers", None, ["gear.tab", "gear.list"], ["gear.list"], ["button | USB 1", "tab | Drums"])
    assert base != S.screen_signature("#/system/gear/controllers", None, ["gear.tab", "gear.list"], [], ["button | USB 1", "tab | Drum kits"])
    assert base != S.screen_signature("#/system/gear/pedals", None, ["gear.tab", "gear.list"], [], ["button | USB 1", "tab | Drums"])
    assert base != S.screen_signature("#/system/gear/controllers", "gear.list", ["gear.tab", "gear.list"], [], ["button | USB 1", "tab | Drums"])


def test_la_mini_coquille_exige_une_signature_par_exemple(tmp_path):
    ok = {"examples": S.SMOKE_EXAMPLES, "pages": {p: ["/api/state"] for p in S.SMOKE_PAGES},
          "written": ["/api/state", "/api/presets", "/api/effects"], "rack": {"declared": {"commit": "x"}}, "kit_warnings": [],
          "screens": {n: "0123456789abcdef" for n in S.SMOKE_EXAMPLES}}
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps(ok))
    assert S.smoke_problems({"refused": [], "examples_failed": []}, str(tmp_path)) == []
    ok["screens"][S.SMOKE_EXAMPLES[0]] = None
    (tmp_path / "SNAPSHOT.json").write_text(json.dumps(ok))
    assert "no screen signature" in "\n".join(S.smoke_problems({"refused": [], "examples_failed": []}, str(tmp_path)))
