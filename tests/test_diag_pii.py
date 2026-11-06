# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 8 (docs/diagnostics.md §6) — ce qui ne doit JAMAIS sortir : un prénom du roster, un nom de
preset ou de lane, un jeton, un chemin /home/<user>, une IP du LAN, le hostname — ni dans
report.json, ni dans la chronologie, ni dans un log. C'est « rig_status ne laisse pas fuir qui
joue » (test_mcp.py), étendu au paquet entier. `.venv/bin/python -m pytest tests/test_diag_pii.py -q`"""
import io
import json
import os
import zipfile

from bridge import config as C, diag

LEA = "Léa"
TOKEN = "gmt_abcDEF123456789xyz"
PRESET = "Set Léa"
SONG = "Blue Bossa Léa"
IP = "192.168.0.22"


def _rack(tmp_path, monkeypatch):
    root = tmp_path
    (root / "config").mkdir()
    (root / "presets").mkdir()
    json.dump({"band": {"id": "b1", "name": "Night Shift", "slug": "night-shift"},
               "people": [{"id": "lea", "name": LEA, "roles": ["voice"]}]}, open(root / "config" / ".band.json", "w"))
    json.dump({"golemfm": {"base_url": f"http://{IP}:5173", "token": TOKEN}}, open(root / "config" / "integrations.json", "w"))
    json.dump({"id": "set-lea", "name": PRESET, "lanes_v": 2,
               "lanes": [{"id": "l1", "role": "voice", "name": "Léa vox", "chain": [{"id": "b1", "type": "deesser"}]}]},
              open(root / "presets" / "set-lea.json", "w"))
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "CONFIG_DIR", str(root / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(root / "presets"))
    monkeypatch.setattr(diag, "_scrubber", None)
    return root


def _scrubber():
    # informé à la main (les lecteurs de roster/presets/setlists sont des dépendances lourdes) :
    # ce test vérifie le SCRUB, test_diag_whitelist vérifie la table
    return diag.Scrubber(names=[LEA, "Night Shift", "lea"], presets=[PRESET, "Léa vox"], songs=[SONG])


def test_scrub_efface_tout_ce_que_le_rack_sait():
    sc = _scrubber()
    home = os.path.expanduser("~")
    s = (f"recall {PRESET} scene B by {LEA} from {home}/golem/presets/x.json token={TOKEN} "
         f"at {IP} mac 3c:52:82:aa:bb:cc song {SONG} sha 0123456789abcdef0123456789abcdef")
    out = sc(s)
    for bad in (LEA, PRESET, SONG, TOKEN, home, IP, "3c:52:82", "0123456789abcdef0123456789abcdef"):
        assert bad not in out, f"{bad!r} a fui : {out}"
    assert "<name>" in out and "<preset>" in out and "<token>" in out and "<ip>" in out


def test_scrub_deep_traite_les_cles_et_les_listes():
    sc = _scrubber()
    out = sc.deep({PRESET: [LEA, {"x": TOKEN}]})
    assert json.dumps(out, ensure_ascii=False).count("<") >= 3
    assert LEA not in json.dumps(out, ensure_ascii=False)


def test_le_paquet_entier_ne_contient_aucune_pii(tmp_path, monkeypatch):
    """Le zip complet — report.json, timeline, logs — est grep-é pour chaque PII connue."""
    root = _rack(tmp_path, monkeypatch)
    monkeypatch.setattr(diag, "scrubber", lambda fresh=False: _scrubber())
    monkeypatch.setattr(diag, "collect_logs", lambda w, sc=None: (
        {"bridge.log": "\n".join(sc(x) for x in [f"golem.recall I recall {PRESET} for {LEA}",
                                                  f"golem.golemfm I Bearer {TOKEN} -> http://{IP}:5173",
                                                  f"path {os.path.expanduser('~')}/golem/presets/set-lea.json"])}, ["apport.log"]))
    diag.open_session()
    diag.event("error", logger="recall", msg=f"recall {PRESET} failed for {LEA}")
    r = diag.build("event", event_={"type": "requested", "detail": f"{LEA} says {PRESET} is silent"})
    assert r and r["file"].startswith("golem-event-")
    z = zipfile.ZipFile(os.path.join(str(root), "diag", r["file"]))
    names = z.namelist()
    assert "golem-report.json" in names and "report.json" in names and "timeline.ndjson" in names and "logs/bridge.log" in names
    blob = b"".join(z.read(n) for n in names).decode("utf-8", "replace")
    for bad in (LEA, PRESET, SONG, TOKEN, IP, os.path.expanduser("~"), "set-lea", "Night Shift"):
        assert bad not in blob, f"{bad!r} a fui dans le paquet"
    man = json.loads(z.read("golem-report.json"))
    assert man["golem_report"] == diag.MANIFEST_VERSION and man["missing"] == ["apport.log"]
    rep = json.loads(z.read("report.json"))
    assert rep["event"]["type"] == "requested" and "<name>" in rep["event"]["detail"]
    assert diag.violations(rep) == []


def test_case_decochee_ne_fabrique_rien(tmp_path, monkeypatch):
    root = _rack(tmp_path, monkeypatch)
    diag.set_auto(False)
    assert diag.auto() is False
    diag.open_session()
    assert diag.build("boot") is None
    assert not [f for f in os.listdir(os.path.join(str(root), "diag")) if f.endswith(".zip")]
    # la chronologie locale s'écrit quand même (dépannage), rien ne sort
    assert os.path.exists(os.path.join(str(root), "diag", "timeline.ndjson"))
    # `force` (outil local) reste permis
    monkeypatch.setattr(diag, "collect_logs", lambda w, sc=None: ({}, []))
    assert diag.build("boot", force=True)["kind"] == "boot"


def test_un_nom_court_ne_mange_pas_le_milieu_des_mots():
    """« Lea » (une ligne de setlist de ce rack, 2026-09-13) transformait `unclean` en `unc<name>n`
    et `clean` en `c<name>n` — deux valeurs du CONTRAT. Un nom se remplace entier, jamais au
    milieu d'un mot ; mais « Lea vox », « lea » seul et « LEA » partent toujours."""
    sc = diag.Scrubber(names=["Lea"], presets=[], songs=[])
    assert sc("session unclean, ended clean, cleanup") == "session unclean, ended clean, cleanup"
    assert sc("lane Lea vox by lea / LEA") == "lane <name> vox by <name> / <name>"
    assert sc("Lea's amp") == "<name>'s amp"


def test_un_id_ou_un_slug_de_chanson_ne_monte_pas():
    """song-sharing.md §2.8 (2026-10-11) : un rapport monte chez golem.fm — « song-install rs:… (slug) » y relierait
    ce compte à une chanson et à une date."""
    sc = diag.Scrubber(names=[], presets=[], songs=["glass_lanterns_paper_kite"])
    line = ("song-install rs:39ed665f37334aedbec58369fe09d6c7 (glass_lanterns_paper_kite) · bs:2 · ct:0a1b · "
            "songs/rs-39ed665f37334aedbec58369fe09d6c7.golem")
    out = sc(line)
    for leak in ("39ed665f", "bs:2", "ct:0a1b", "kite"):
        assert leak not in out, (leak, out)
    assert out.count("<song-id>") == 4 and "<song>" in out
    assert sc("region us-east-1, rs-232 error") == "region us-east-1, rs-232 error"   # pas des ids
