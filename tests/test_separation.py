# SPDX-License-Identifier: GPL-3.0-or-later
"""La séparation sur le golem (docs/separation.md) : deux portes, un seul chemin, un test qui LIT les sorties, des
faux refusés, rien de nommé vers golem.fm, et le job song-separate jusqu'à son ack."""
import json
import os
import shutil
import threading
import time

import pytest

pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
if not shutil.which("ffmpeg"):
    pytest.skip("ffmpeg absent", allow_module_level=True)

from bridge import separation as S
from tests import separation_engines as T


@pytest.fixture
def sep(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "CFG_PATH", str(tmp_path / "separation.json"))
    monkeypatch.setattr(S, "ENG_DIR", str(tmp_path / "engines"))
    monkeypatch.setattr(S, "WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(S, "ENGINE_LOG", str(tmp_path / "work" / "engine.log"))
    monkeypatch.setattr(S, "EXCERPT_BASE", str(tmp_path / "work" / "excerpt"))
    clip = T.mix_clip(str(tmp_path / "clip.flac"), seconds=12)
    S.set_excerpt(open(clip, "rb").read(), "my song.flac")             # l'extrait de l'UTILISATEUR (§6)
    monkeypatch.setattr(S, "_CLIP_FOR_TESTS", clip, raising=False)
    monkeypatch.setattr(S, "_busy", lambda idle: None)
    monkeypatch.setattr(S, "_publish", lambda: None)
    return tmp_path


def _tested(eid):
    S.test(eid, wait=True)
    return S._engine(S.load(), eid)["test"]


def test_deux_moteurs_d_architectures_differentes_passent_par_le_meme_chemin(sep):
    """§1.1 : le bouclier de l'avocat — un graphe ONNX et un programme, sans rien en commun, même code."""
    onnx = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "test", accepted=True)
    prog = S.add_program(T.split_program(str(sep / "split.py")), ["--in", "{input}", "--out", "{outdir}"], "test",
                         accepted=True)
    a, b = _tested(onnx["id"]), _tested(prog["id"])
    assert a["ok"], a.get("why")
    assert sorted(a["stems"]) == ["high", "low", "mid"] and a["rtf"] > 0
    assert a["analysis"]["residual_db"] < -40                           # les bandes se somment au mix
    assert b["ok"], b.get("why")
    assert sorted(b["stems"]) == ["high", "low"]


def test_la_case_de_responsabilite_est_obligatoire(sep):
    with pytest.raises(S.SeparationError, match="tick the box"):
        S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "x", accepted=False)


def test_un_onnx_sans_contrat_est_refuse_a_l_ajout(sep):
    with pytest.raises(S.SeparationError, match="golem.contract"):
        S.add_onnx(T.no_contract_onnx(str(sep / "x.onnx")), "", accepted=True)
    assert not os.listdir(S.ENG_DIR)                                  # rien ne reste sur le disque


def test_des_copies_du_mix_sont_refusees(sep):
    e = S.add_onnx(T.copies_onnx(str(sep / "c.onnx")), "", accepted=True)
    t = _tested(e["id"])
    assert not t["ok"] and "the mix itself" in t["why"]
    with pytest.raises(S.SeparationError, match="test this engine first"):
        S.activate(e["id"])


def test_un_nan_sur_du_silence_est_refuse(sep):
    """Vécu au spike R0 : 0/0 dans un masque, tout le dernier segment d'un morceau en NaN."""
    e = S.add_onnx(T.nan_on_silence_onnx(str(sep / "n.onnx")), "", accepted=True)
    t = _tested(e["id"])
    assert not t["ok"] and "NaN" in t["why"]


def test_le_programme_est_lance_sans_shell_et_ses_jetons_sont_entiers(sep):
    p = T.split_program(str(sep / "split.py"))
    with pytest.raises(S.SeparationError, match="exactly once"):
        S.add_program(p, ["{input}"], accepted=True)
    with pytest.raises(S.SeparationError, match="whole argument"):
        S.add_program(p, ["--in={input}", "{input}", "{outdir}"], accepted=True)
    with pytest.raises(S.SeparationError, match="not found"):
        S.add_program(str(sep / "nope"), ["{input}", "{outdir}"], accepted=True)


def test_caps_ne_dit_que_stems_et_rtf(sep):
    e = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "my secret licence", accepted=True, label="Secret name")
    assert S.caps() is None                                            # pas de moteur actif : pas de clé
    _tested(e["id"])
    S.activate(e["id"])
    c = S.caps()
    assert set(c) == {"stems", "rtf"} and sorted(c["stems"]) == ["high", "low", "mid"]
    blob = json.dumps(c)
    assert "Secret" not in blob and "licence" not in blob and e["id"] not in blob


def test_les_journaux_ne_nomment_rien(sep, caplog):
    caplog.set_level("INFO")
    e = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "Licence X", accepted=True, label="Engine Z")
    _tested(e["id"])
    text = caplog.text
    assert "custom engine" in text
    assert "Engine Z" not in text and "Licence X" not in text and "bands.onnx" not in text


def test_un_moteur_retire_de_la_liste_passe_custom_et_se_desactive(sep):
    with S._lock:
        d = S.load()
        d["engines"].append({"id": "candidate-R2", "origin": "listed", "slug": "candidate-R2", "kind": "onnx",
                             "test": {"ok": True, "stems": ["vocals", "other"], "rtf": 0.2}})
        d["active"] = "candidate-R2"
        S._save(d)
    assert S.caps()
    S._withdrawn([], "rev2")
    e = S._engine(S.load(), "candidate-R2")
    assert e["origin"] == "custom" and not e["accepted_at"] and S.load()["active"] is None
    assert S.caps() is None
    with pytest.raises(S.SeparationError, match="tick the box"):
        S.activate("candidate-R2")
    S.activate("candidate-R2", accepted=True)
    assert S.caps()


def test_les_services_payants_sont_partis(sep, monkeypatch):
    """v0.6 (2026-10-31, docs/private/launch-plan.md §3) : un moteur « service » d'une config d'avant disparaît à la lecture,
    et une entrée `type: "service"` de la liste de golem.fm est ignorée — les moteurs listés gratuits restent."""
    import json
    with open(S.CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({"engines": [{"id": "svc-x", "origin": "listed", "kind": "service", "slug": "x",
                                "test": {"ok": True, "stems": ["vocals", "other"]}}], "active": "svc-x"}, f)
    d = S.load()
    assert d["engines"] == [] and d["active"] is None and S.caps() is None
    from bridge import golemfm
    monkeypatch.setattr(S, "_REMOTE", {"at": 0.0, "data": None})      # le cache de la liste ne fuit pas vers les autres tests
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://fm", "tok"))
    monkeypatch.setattr(golemfm, "_req", lambda *a, **k: (200, {"rev": "r1", "engines": [
        {"slug": "x", "type": "service"}, {"slug": "free", "type": "engine", "kind": "onnx"}]}))
    assert [x["slug"] for x in S.remote_list(fresh=True)["engines"]] == ["free"]


def test_la_reprise_ne_recalcule_que_les_segments_manquants(sep):
    """§5 : quelqu'un se met à jouer → processus tué ; la reprise repart du premier segment manquant."""
    e = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx"), seg=44100), "", accepted=True)
    mix = str(sep / "mix.f32")
    n = S.decode(S._CLIP_FOR_TESTS, mix)
    work, out = str(sep / "w"), str(sep / "o")
    with pytest.raises(S.Stopped, match="someone is playing"):          # occupé : tué, pas d'erreur
        S.separate(e, mix, n, work, out, lambda: "someone is playing")
    first, _, _ = S.separate(e, mix, n, work, out)
    segs = sorted(f for f in os.listdir(work) if f.startswith("seg-"))
    assert len(segs) > 4
    ref = {k: open(v, "rb").read() for k, v in first.items()}
    for f in segs[2:4]:                                                 # deux segments perdus (tué en plein calcul)
        os.unlink(os.path.join(work, f))
    again, _, _ = S.separate(e, mix, n, work, out)
    with open(os.path.join(out, "result.json")) as f:
        assert json.load(f)["computed"] == 2
    assert {k: open(v, "rb").read() for k, v in again.items()} == ref  # même résultat, à l'octet


# ── le job song-separate (§8) ──────────────────────────────────────────────────────────────────
@pytest.fixture
def job_env(sep, monkeypatch):
    e = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "", accepted=True)
    _tested(e["id"])
    S.activate(e["id"])
    acks, uploads = [], []
    done = threading.Event()
    from bridge import golem_pull, tones_jobs
    monkeypatch.setattr(golem_pull, "_download", lambda url, dest: shutil.copyfile(S._CLIP_FOR_TESTS, dest))

    def _req(method, path, body=None, **k):
        acks.append((path, body))
        done.set()
        return 200, {}
    monkeypatch.setattr(tones_jobs, "_req", _req)
    monkeypatch.setattr(S, "_upload", lambda path, stem, mp3: uploads.append((path, stem, os.path.getsize(mp3))))
    return {"acks": acks, "uploads": uploads, "done": done}


def _job(**kw):
    return {"id": 99, "_job": 42, "action": "song-separate", "song": "s-1", "kind": "song",
            "source_url": "/api/ext/files/x/original.mp3", "upload_url": "/api/ext/jobs/42/stems", **kw}


def test_le_job_separe_envoie_un_post_par_stem_et_acquitte(job_env):
    S.on_job(_job(stems_wanted=["low", "high"]))
    assert job_env["done"].wait(120)
    path, body = job_env["acks"][-1]
    assert path == "/api/ext/tones/jobs/42/ack"                        # l'id du JOB (`_job`), pas celui du contenu
    assert body == {"ok": True, "result": {"stems": ["low", "high"], "silent": []}}
    assert [u[1] for u in job_env["uploads"]] == ["low", "high"] and all(u[2] > 1000 for u in job_env["uploads"])
    assert all(u[0] == "/api/ext/jobs/42/stems" for u in job_env["uploads"])


def test_un_stem_demande_que_le_moteur_n_a_pas_rend_engine_changed(job_env):
    S.on_job(_job(stems_wanted=["vocals"]))
    assert job_env["done"].wait(60)
    assert job_env["acks"][-1][1] == {"ok": False, "error": "engine_changed"}
    assert job_env["uploads"] == []


def test_sans_moteur_actif_no_engine(job_env):
    S.deactivate()
    S.on_job(_job())
    assert job_env["done"].wait(60)
    assert job_env["acks"][-1][1] == {"ok": False, "error": "no_engine"}


def test_une_source_illisible_rend_source_unreadable(job_env, monkeypatch):
    from bridge import golem_pull
    monkeypatch.setattr(golem_pull, "_download", lambda url, dest: open(dest, "wb").write(b"not audio"))
    S.on_job(_job())
    assert job_env["done"].wait(60)
    assert job_env["acks"][-1][1] == {"ok": False, "error": "source_unreadable"}


def test_sans_extrait_choisi_le_test_le_demande(sep):
    S.clear_excerpt()
    e = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "", accepted=True)
    with pytest.raises(S.SeparationError, match="choose a test excerpt"):
        S.test(e["id"])


def test_l_extrait_doit_etre_de_l_audio_assez_long(sep):
    with pytest.raises(S.SeparationError, match="audio file"):
        S.set_excerpt(b"x", "notes.txt")
    with pytest.raises(S.SeparationError, match="could not be read"):
        S.set_excerpt(b"not audio at all", "fake.mp3")
    short = T.mix_clip(str(sep / "short.flac"), seconds=5)
    with pytest.raises(S.SeparationError, match="too short"):
        S.set_excerpt(open(short, "rb").read(), "short.flac")
    assert S.excerpt_info()["name"] == "my song.flac"                  # l'ancien choix est gardé


def test_un_extrait_a_un_seul_instrument_met_en_cause_l_extrait_pas_le_moteur(sep):
    """golem.fm (a) : un extrait pris au hasard peut ne porter qu'un instrument."""
    import subprocess
    one = str(sep / "one.flac")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=110:duration=15",
                    "-ac", "2", one], check=True)
    S.set_excerpt(open(one, "rb").read(), "bass only.flac")
    e = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "", accepted=True)
    t = _tested(e["id"])
    assert not t["ok"] and "choose" in t["why"] and "several" in t["why"]      # l EXTRAIT est mis en cause


def test_le_nom_de_l_extrait_n_est_jamais_journalise(sep, caplog):
    caplog.set_level("INFO")
    clip = T.mix_clip(str(sep / "c2.flac"), seconds=12)
    S.set_excerpt(open(clip, "rb").read(), "Secret Demo 2026.flac")
    assert "Secret Demo" not in caplog.text and "test excerpt chosen" in caplog.text


def test_seuls_les_moteurs_de_la_liste_ont_leur_carte_de_licence(sep):
    S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "Custom licence", accepted=True, label="Mine")
    with S._lock:
        d = S.load()
        d["engines"].append({"id": "eng-a", "origin": "listed", "slug": "eng-a", "kind": "onnx", "label": "Engine A",
                             "author": "Lab X", "licence": "CC BY 4.0", "licence_url": "https://example.org/l",
                             "attribution": "Engine A by Lab X, CC BY 4.0", "test": {}})
        S._save(d)
    cards = S.attributions()
    assert [c["name"] for c in cards] == ["Engine A"]                    # jamais le moteur ajouté à la main
    assert cards[0]["what"] == "Engine A by Lab X, CC BY 4.0" and cards[0]["kind"] == "separation"


def _tool_like_program(path):
    """Un programme qui nomme ses sorties À SA FAÇON, dans un sous-dossier (comme le font les vrais outils)."""
    import stat, sys, textwrap
    src = textwrap.dedent('''\
        #!%s
        import sys, os, shutil, subprocess
        inp, out = sys.argv[1], sys.argv[2]
        d = os.path.join(out, "separated", "input"); os.makedirs(d)
        import wave, array
        w = wave.open(inp, "rb"); ch, sr, n = w.getnchannels(), w.getframerate(), w.getnframes()
        x = array.array("h", w.readframes(n)); w.close()
        low = array.array("h", [0]) * len(x); acc = [0.0] * ch
        for i, v in enumerate(x):
            c = i %% ch; acc[c] += 0.02 * (v - acc[c]); low[i] = int(acc[c])
        rest = array.array("h", [max(-32768, min(32767, x[i] - low[i])) for i in range(len(x))])
        for name, data in (("input_(Bass)_m1.wav", low), ("input_(Instrumental)_m1.wav", rest)):
            o = wave.open(os.path.join(d, name), "wb"); o.setnchannels(ch); o.setsampwidth(2); o.setframerate(sr)
            o.writeframes(data.tobytes()); o.close()
        print("done: 2 files")
        ''' % sys.executable)
    open(path, "w").write(src)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def test_l_essai_a_blanc_lit_les_fichiers_et_propose_les_stems(sep):
    prog = _tool_like_program(str(sep / "tool.py"))
    r = S.probe_program(prog, ["{input}", "{outdir}"])
    assert r["ok"], r
    assert r["files"] == ["separated/input/input_(Bass)_m1.wav", "separated/input/input_(Instrumental)_m1.wav"]
    assert r["guess"] == {"separated/input/input_(Bass)_m1.wav": "bass", "separated/input/input_(Instrumental)_m1.wav": "other"}
    assert "done: 2 files" in r["log_tail"]
    assert S.load()["engines"] == []                                     # un essai n'enregistre rien


def test_un_programme_qui_nomme_a_sa_facon_passe_avec_l_association(sep):
    prog = _tool_like_program(str(sep / "tool.py"))
    e = S.add_program(prog, ["{input}", "{outdir}"], accepted=True,
                      outputs={"separated/input/input_(Bass)_m1.wav": "bass", "separated/input/input_(Instrumental)_m1.wav": "other"})
    t = _tested(e["id"])
    assert t["ok"], t.get("why")
    assert sorted(t["stems"]) == ["bass", "other"]


def test_sans_association_le_test_dit_quoi_faire_et_montre_les_fichiers(sep):
    prog = _tool_like_program(str(sep / "tool.py"))
    e = S.add_program(prog, ["{input}", "{outdir}"], accepted=True)
    t = _tested(e["id"])
    assert not t["ok"] and "match each file to a stem" in t["why"]
    assert t["files"] and "done: 2 files" in t["log_tail"]


def test_le_fichier_de_moteur_s_exporte_et_se_reimporte_sans_rien_activer(sep):
    prog = _tool_like_program(str(sep / "tool.py"))
    e = S.add_program(prog, ["{input}", "{outdir}"], accepted=True, label="My tool", licence="MIT",
                      outputs={"separated/input/input_(Bass)_m1.wav": "bass"})
    doc = S.export_engine(e["id"])
    assert doc["format"] == "golem-engine/1" and doc["outputs"] == {"separated/input/input_(Bass)_m1.wav": "bass"}
    assert "key" not in json.dumps(doc).lower().replace("\"kind\"", "")
    form = S.read_engine_file(json.loads(json.dumps(doc)))
    assert form["program"] == prog and form["args"] == ["{input}", "{outdir}"] and form["label"] == "My tool"
    with pytest.raises(S.SeparationError, match="not a golem engine file"):
        S.read_engine_file({"format": "other"})
    with pytest.raises(S.SeparationError, match="not an output file"):
        S.read_engine_file({**doc, "outputs": {"../../etc/passwd.wav": "bass"}})


def test_les_controles_du_programme_se_disent_un_par_un(sep):
    assert S.program_checks("/nope/x") == {"ok": False, "why": "file not found", "exists": False, "runnable": False,
                                            "not_script": False}
    plain = sep / "plain.txt"
    plain.write_text("x")
    c = S.program_checks(str(plain))
    assert c["exists"] and not c["runnable"] and "not executable" in c["why"]
    assert S.program_checks(T.split_program(str(sep / "split.py")))["ok"]


def test_le_fichier_onnx_se_lit_avant_l_ajout(sep):
    info = S.inspect_source(T.band_split_onnx(str(sep / "bands.onnx")))
    assert info["stems"] == ["low", "mid", "high"] and info["segment"] == 44100 * 4 and info["size_bytes"] > 0
    with pytest.raises(S.SeparationError, match="golem.contract"):
        S.inspect_source(T.no_contract_onnx(str(sep / "x.onnx")))


def test_le_navigateur_ne_montre_que_ce_qui_peut_servir(sep):
    (sep / "d").mkdir()
    T.band_split_onnx(str(sep / "d" / "m.onnx"))
    (sep / "d" / "notes.txt").write_text("x")
    T.split_program(str(sep / "d" / "tool.py"))
    assert S.browse(str(sep / "d"), "onnx")["files"] == ["m.onnx"]
    assert S.browse(str(sep / "d"), "program")["files"] == ["tool.py"]


def test_les_aides_par_symptome_ne_nomment_aucun_outil():
    h = S.hints("the program wrote no WAV file into {outdir}", "Output file(s): a.flac b.flac")
    assert h[0].startswith("It wrote another format")
    assert S.hints("the program exited with code 127")[0].startswith("The program could not find")
    assert any("memory" in x for x in S.hints("the program exited with code 1", "CUDA error: out of memory"))
    assert S.hints("fewer than 2 stems carry sound — choose an excerpt with several instruments") == \
        ["Choose a test excerpt with several instruments."]


# ── « Combine two of my engines » (mockups/separation-combine.html) ─────────────────────────────────────────────────
def _two_engines(sep):
    a = S.add_onnx(T.band_split_onnx(str(sep / "bands.onnx")), "", accepted=True, label="Bands")
    b = S.add_program(T.split_program(str(sep / "split.py")), ["--in", "{input}", "--out", "{outdir}"], accepted=True,
                      label="Split")
    assert _tested(a["id"])["ok"] and _tested(b["id"])["ok"]
    return a, b


def test_deux_moteurs_s_enchainent_et_la_somme_reste_le_morceau(sep):
    a, b = _two_engines(sep)
    c = S.add_combined(a["id"], ["low"], b["id"], "", accepted=True)
    assert c["label"] == "Bands + Split"
    t = _tested(c["id"])
    assert t["ok"], t.get("why")
    # low vient du premier ; le second sort low (le résidu, rangé dans other) et high
    assert sorted(t["stems"]) == ["high", "low", "other"]
    assert t["analysis"]["residual_db"] < -40                           # la somme est le morceau


def test_une_combinaison_refuse_ce_qui_n_a_pas_de_sens(sep):
    a, b = _two_engines(sep)
    with pytest.raises(S.SeparationError, match="two different"):
        S.add_combined(a["id"], ["low"], a["id"], accepted=True)
    with pytest.raises(S.SeparationError, match="at least one stem"):
        S.add_combined(a["id"], [], b["id"], accepted=True)
    with pytest.raises(S.SeparationError, match="leave at least one"):
        S.add_combined(a["id"], ["low", "mid", "high"], b["id"], accepted=True)
    c = S.add_combined(a["id"], ["low"], b["id"], accepted=True)
    with pytest.raises(S.SeparationError, match="another combination"):
        S.add_combined(c["id"], ["low"], b["id"], accepted=True)


def test_retirer_un_moteur_retire_ses_combinaisons_et_l_ecran_le_sait(sep):
    a, b = _two_engines(sep)
    c = S.add_combined(a["id"], ["low"], b["id"], "Combo", accepted=True)
    ov = {e["id"]: e for e in S.overview(remote=False)["engines"]}
    assert ov[a["id"]]["used_by"] == ["Combo"] and ov[c["id"]]["first_label"] == "Bands"
    S.remove(b["id"])
    ids = [e["id"] for e in S.load()["engines"]]
    assert a["id"] in ids and b["id"] not in ids and c["id"] not in ids


def test_une_combinaison_de_programmes_s_exporte_et_se_reinstalle(sep):
    p1 = S.add_program(T.split_program(str(sep / "split.py")), ["--in", "{input}", "--out", "{outdir}"], accepted=True,
                       label="Split")
    p2 = S.add_program(_tool_like_program(str(sep / "tool.py")), ["{input}", "{outdir}"], accepted=True, label="Tool",
                       outputs={"separated/input/input_(Bass)_m1.wav": "bass",
                                "separated/input/input_(Instrumental)_m1.wav": "other"})
    assert _tested(p1["id"])["ok"] and _tested(p2["id"])["ok"]
    c = S.add_combined(p1["id"], ["high"], p2["id"], "Combo", accepted=True)
    doc = S.export_engine(c["id"])
    assert doc["kind"] == "combined" and doc["keep"] == ["high"] and doc["first"]["label"] == "Split"
    for e in list(S.load()["engines"]):
        S.remove(e["id"])
    form = S.read_engine_file(json.loads(json.dumps(doc)))
    S.install_combined(form, accepted=True)
    for _ in range(600):
        if S._IMPORT["phase"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert S._IMPORT["phase"] == "done", S._IMPORT
    e = S._engine(S.load(), S._IMPORT["engine"])
    assert e["kind"] == "combined" and e["test"]["ok"] and sorted(e["test"]["stems"]) == ["bass", "high", "other"]
