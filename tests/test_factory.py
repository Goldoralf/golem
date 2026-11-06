# SPDX-License-Identifier: GPL-3.0-or-later
"""L'usine (docs/factory.md, bridge/factory.py) : la pose au démarrage n'écrase rien, ne ressuscite rien, et le
contenu livré ne porte rien de la machine qui l'a fabriqué."""
import glob
import re
import json
import os

from bridge import factory as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _setup(tmp_path, monkeypatch):
    src = tmp_path / "factory"
    (src / "patches").mkdir(parents=True)
    (src / "patches" / "factory-a.json").write_text('{"id": "factory-a", "v": "usine"}')
    (src / "patches" / "factory-b.json").write_text('{"id": "factory-b", "v": "usine"}')
    live = tmp_path / "patches"
    monkeypatch.setattr(F, "SRC", str(src))
    monkeypatch.setattr(F, "KINDS", {"patches": ("patches", str(live), ".json")})
    monkeypatch.setattr(F, "LEDGER", str(tmp_path / ".factory.json"))
    return live


def test_pose_ce_qui_manque_sans_ecraser(tmp_path, monkeypatch):
    live = _setup(tmp_path, monkeypatch)
    live.mkdir()
    (live / "factory-a.json").write_text('{"id": "factory-a", "v": "retouché"}')
    r = F.seed()
    assert r["placed"] == ["patches/factory-b.json"]
    assert json.loads((live / "factory-a.json").read_text())["v"] == "retouché"      # jamais d'écrasement


def test_un_objet_supprime_ne_revient_pas_sauf_restauration(tmp_path, monkeypatch):
    live = _setup(tmp_path, monkeypatch)
    F.seed()
    (live / "factory-b.json").unlink()                                               # l'utilisateur le supprime
    r = F.seed()
    assert r["placed"] == [] and r["removed_by_user"] == ["patches/factory-b.json"]
    assert not (live / "factory-b.json").exists()
    r = F.seed(force_ids=["factory-b.json"])                                         # « Restore factory content »
    assert r["placed"] == ["patches/factory-b.json"]


def test_l_usine_livree_ne_porte_rien_de_la_machine():
    files = glob.glob(os.path.join(ROOT, "library", "factory", "**", "*.json"), recursive=True)
    assert files, "library/factory/ est vide"
    for f in files:
        s = open(f, encoding="utf-8").read()
        for w in ('"persons"', '"foot_person"', '/home/', '"on_card"'):
            assert w not in s, f"{os.path.basename(f)} contient {w}"
        d = json.loads(s)
        for L in d.get("lanes") or []:
            if L.get("in_role") and not L.get("midi"):
                assert L.get("in_sel") in ("", None), f"{os.path.basename(f)} : la lane {L['id']} porte une entrée de carte"


def test_chaque_preset_d_usine_ne_reprend_que_des_patches_d_usine():
    have = {os.path.basename(f)[:-5] for f in glob.glob(os.path.join(ROOT, "library", "factory", "patches", "*.json"))}
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "presets", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for L in d.get("lanes") or []:
            src = (L.get("patch_from") or {}).get("id")
            assert src in have, f"{os.path.basename(f)} : la lane {L['id']} vient de « {src} », absent de l'usine"


def test_les_captures_d_usine_sont_lues_dans_les_patches_livres():
    refs = F._factory_refs()
    assert len(refs) >= 30, "les patches d'usine nomment leurs captures TONE3000"
    assert all(t.isdigit() for t in refs), "une ref d'usine est un id de catalogue (jamais t3k:…)"
    assert "2599" in refs and "419209" in refs["2599"], "le Klon de Texas Blues, avec son modèle précis"


def test_chaque_lane_d_usine_porte_le_role_de_son_nom():
    """Trois patches de basse livrés en rôle « guitar » (2026-10-13) : un patch se lie à l'entrée de SON rôle — une
    basse marquée guitare se branchait sur l'entrée guitare de la carte. La lane `bass-1` est une basse."""
    import re
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "**", "*.json"), recursive=True):
        d = json.load(open(f, encoding="utf-8"))
        lanes = [L for L in d.get("lanes") or [] if isinstance(L, dict)]
        for L in lanes:
            m = re.fullmatch(r"([a-z-]+?)-\d+", str(L.get("id") or ""))
            if m and L.get("role"):
                assert L["role"] == m.group(1), f"{os.path.basename(f)} : la lane {L['id']} a le rôle {L['role']}"
        if d.get("kind") == "patch" and len(lanes) == 1 and d.get("role"):
            assert d["role"] == lanes[0].get("role"), f"{os.path.basename(f)} : patch {d['role']}, lane {lanes[0].get('role')}"


def test_les_grooves_d_usine_sont_a_nous_et_tombent_pile_sur_la_barre():
    """Dix grooves composés par tools/make-factory-grooves.py : la fin de piste tombe sur la mesure (golem_drums
    arrondit la boucle à la barre — un octet de trop et la boucle prend une mesure vide), et seules les notes qui
    ont le même sens sur les kits du rack sont jouées."""
    from bridge import grooves
    files = sorted(glob.glob(os.path.join(ROOT, "library", "factory", "grooves", "*.mid")))
    meta = json.load(open(os.path.join(ROOT, "library", "factory", "grooves", "meta.json"), encoding="utf-8"))
    assert len(files) >= 13 and {os.path.basename(f)[:-4] for f in files} == set(meta)
    for f in files:
        notes, bars, ppq = grooves._probe(f)
        assert notes and ppq == 480, os.path.basename(f)
        assert meta[os.path.basename(f)[:-4]]["pack"] == "golem"
        b = open(f, "rb").read()
        assert b.endswith(b"\xff\x2f\x00"), os.path.basename(f)
        used = {b[i + 1] for i in range(len(b) - 2) if b[i] == 0x99}
        kit = meta[os.path.basename(f)[:-4]].get("kit") or ""
        from bridge import kits
        allowed = set(kits.DEFAULT_NOTES) if kit.startswith("pads-") else {36, 37, 38, 41, 42, 44, 45, 46, 49, 51, 53}
        assert used <= allowed, f"{os.path.basename(f)} : notes {sorted(used - allowed)} hors du kit {kit}"


def test_la_batterie_d_usine_joue_des_grooves_livres_sur_sw10():
    """Le tuto « SW10 = la batterie » (2026-10-13) : chaque bloc Drum Machine de l'usine est sur SW10, joue un
    groove LIVRÉ par l'usine (pas un fichier d'une machine) avec un kit du rack, et son objet porte un tempo."""
    have = {os.path.basename(f) for f in glob.glob(os.path.join(ROOT, "library", "factory", "grooves", "*.mid"))}
    n = 0
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "**", "*.json"), recursive=True):
        d = json.load(open(f, encoding="utf-8"))
        for b in ((d.get("config") or {}).get("gen") or {}).get("blocks") or []:
            if b.get("type") != "drums":
                continue
            n += 1
            assert b.get("foot") == 10, f"{os.path.basename(f)} : la batterie n'est pas sur SW10"
            pats = (b.get("params") or {}).get("patterns") or []
            assert pats and all(p.startswith("library/grooves/") and os.path.basename(p) in have for p in pats), os.path.basename(f)
            assert (b.get("params") or {}).get("kit", "").startswith("drums-"), os.path.basename(f)
            assert d.get("bpm"), f"{os.path.basename(f)} : un groove sans tempo joue à 120"
    assert n >= 10


def test_masquer_l_usine_ne_supprime_rien_et_restaurer_remet_ce_qui_manque(tmp_path, monkeypatch):
    """System ▸ System ▸ Factory : un interrupteur par sorte (masquer = ne pas montrer, jamais supprimer) ; « Restore »
    remet ce que l'utilisateur a supprimé — et seulement ça."""
    live = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(F, "VIS_FILE", str(tmp_path / ".factory-show.json"))
    assert all(F.visibility().values())                                              # par défaut : tout se voit
    assert F.set_visibility({"grooves": False, "inconnu": False})["grooves"] is False
    assert "inconnu" not in F.visibility()
    F.seed()
    items = F.mark("patches", [{"id": "factory-a"}, {"id": "mine"}])
    assert items[0].get("factory") is True and "factory" not in items[1]           # marqué, rien retiré
    (live / "factory-b.json").unlink()
    assert [r["id"] for r in F.removed()] == ["factory-b"]
    assert F.restore()["placed"] == ["patches/factory-b.json"]
    assert F.removed() == [] and (live / "factory-b.json").exists()


def test_un_preset_partage_emporte_les_grooves_de_sa_boite_a_rythmes():
    """Partage des grooves (2026-10-14, accord golem.fm) : chaque groove de la bibliothèque est un pack
    `local:groove-<id>` ; le bloc Drum Machine les déclare en deps, .mid joint ; un groove d'usine porte `factory`
    (golem.fm ne le transfère pas) ET son sha (un golem resté sur une ancienne version vérifie)."""
    from bridge import preset_export as E
    out, blobs = E.build_export("patch:factory-guitar-funk-clean")
    g = [d for d in out["deps"] if d["kind"] == "groove"]
    assert g and g[0]["uid"] == "local:groove-golem-funk-16" and g[0].get("factory") is True and g[0]["sha256"]
    assert any(p.endswith("golem-funk-16.mid") for p in blobs.values())
    assert not [u for u in out.get("unresolved") or [] if u.get("type") == "groove"]


def test_un_pack_groove_recu_s_installe_dans_les_grooves_jamais_dans_les_tones(tmp_path, monkeypatch):
    """Un pack `groove` venu de golem.fm : le .mid dans library/grooves/, ses métadonnées dans l'index — et RIEN dans
    le catalogue des tones (le chemin des captures l'y aurait rangé comme un ampli)."""
    from bridge import grooves, tones_jobs as T, loans
    monkeypatch.setattr(grooves, "GROOVES_DIR", str(tmp_path / "grooves"))
    monkeypatch.setattr(grooves, "_META", str(tmp_path / "grooves" / "index.json"))
    got = {}
    def fake_dl(sha, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").write(b"MThd")
        got["dest"] = dest
    monkeypatch.setattr(T, "_download_raw", fake_dl)
    pack = {"uid": "local:groove-my-beat", "kind": "groove", "title": "My beat",
            "extra": {"groove_id": "my-beat", "genre": "funk", "tempo": 98, "pack": "mine"},
            "assets": [{"sha256": "a" * 64, "bytes": 4}]}
    msg = T._install_groove(pack["uid"], pack)
    assert got["dest"] == str(tmp_path / "grooves" / "my-beat.mid") and "installed" in msg
    assert grooves._read_meta()["my-beat"] == {"name": "My beat", "genre": "funk", "tempo": 98, "pack": "mine"}
    bad = dict(pack, extra={"groove_id": "../../evil"})
    assert T._install_groove("x", bad)                          # _safe_id neutralise le chemin
    assert not os.path.exists(tmp_path / "evil.mid")


def test_un_refus_de_golem_fm_se_dit_en_une_raison_stable():
    """La case Riff de /live dit POURQUOI un riff n'est pas arrivé (codes lus chez golem.fm le 2026-10-14)."""
    from bridge.uploader import refusal
    assert refusal(401, "Unknown or revoked device token") == "relink"
    assert refusal(403, "Device token missing scope 'backups:write'") == "relink"
    assert refusal(403, {"error": "band_forbidden", "band": {"id": "x"}}) == "forbidden"
    assert refusal(404, {"error": "band_gone", "band": {"id": "x"}}) == "space_gone"
    assert refusal(413, "Band storage quota exceeded (1 > 0 bytes)") == "quota"
    assert refusal(413, {"error": "quota_exceeded", "used": 1, "incoming": 2, "quota": 2, "message": "…"}) == "quota"
    assert refusal(422, "No band tag on this take and the device is not attached to a band") == "no_space"
    assert refusal(0, "timed out") == "offline"
    assert refusal(500, "boom") == "open_500"


def test_un_patch_enregistre_garde_ses_switches_rec_et_riff():
    """REC et RIFF dans les banks de patches (2026-10-14) : enregistrer le patch depuis le Designer ne doit pas
    effacer leurs switches (seuls les blocs générateurs survivaient). On ne garde que le SWITCH : les réglages de ces
    singletons restent globaux."""
    from bridge import patches, store
    for pid, want in (("patch:factory-voice-clean", {"rec": 9}), ("patch:factory-voice-crooner", {"compo": 9})):
        p = store.load_preset(pid)
        out = patches.v2_fields(p, [p["lanes"][0]["id"]], with_config=True)
        rec = {b["type"]: b["foot"] for b in ((out.get("config") or {}).get("rec") or {}).get("blocks") or []}
        assert rec == want, pid
        assert all(set(b) == {"id", "type", "foot"} for b in out["config"]["rec"]["blocks"])


def test_rec_et_riff_jamais_ensemble_sur_un_objet_d_usine():
    """2026-10-13 puis 14 : REC (session sur le golem) et RIFF (idée vers golem.fm) dans le même objet brouillent
    le tuto — UN des deux par patch ou preset, réparti dans chaque bank. Un bloc sans switch ne s'affiche pas."""
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "p*", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        feet = {b.get("type") for k in ("rec", "gen") for b in ((d.get("config") or {}).get(k) or {}).get("blocks") or []
                if b.get("type") in ("rec", "compo") and b.get("foot")}
        assert len(feet) < 2, os.path.basename(f)
    banks = glob.glob(os.path.join(ROOT, "library", "factory", "setlists", "factory-*.json"))
    for f in banks:                                      # chaque bank d'instrument a les deux tutos, chacun sur son patch
        lines = json.load(open(f, encoding="utf-8")).get("lines") or []
        kinds = set()
        for ln in lines:
            pid = (ln.get("patch") or "").replace("patch:", "")
            pf = os.path.join(ROOT, "library", "factory", "patches", pid + ".json")
            if os.path.exists(pf):
                d = json.load(open(pf, encoding="utf-8"))
                kinds |= {b["type"] for b in ((d.get("config") or {}).get("rec") or {}).get("blocks") or [] if b.get("foot")}
        assert kinds == {"rec", "compo"}, os.path.basename(f)


def test_les_banques_dx7_de_l_usine_sont_livrees_et_creditees():
    """Le bloc EP d'usine ne cite que des banques LIVRÉES (library/factory/dx7, déposées dans library/dx7) — les banques
    d'origine du rack (ROM Yamaha, cartouches de la communauté) ne se redistribuaient pas (2026-10-14)."""
    have = {os.path.basename(f) for f in glob.glob(os.path.join(ROOT, "library", "factory", "dx7", "*.syx"))}
    assert have and open(os.path.join(ROOT, "library", "factory", "dx7", "CREDITS.md")).read().count("SynprezFM")
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "**", "*.json"), recursive=True):
        s = open(f, encoding="utf-8").read()
        for bank in set(re.findall(r'"bank": "library/dx7/([^"]+)"', s)):
            assert bank in have, f"{os.path.basename(f)} : banque {bank} non livrée"


def test_chaque_patch_d_usine_donne_de_quoi_jouer_et_garder_une_trace():
    """Alex, 2026-10-17 : les patches d'usine portent des blocs de service choisis pour s'amuser seul — un Standard
    (jazz, blues) ou une boîte à rythmes sur SW10, et Rec ou Riff. Le Standard exclut la boîte à rythmes ; un Standard
    joue sans la partie de l'instrument du patch (on ne s'accompagne pas soi-même)."""
    part = {"bass": "bass", "keys": "keys", "drums": "drums"}
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "patches", "factory-*.json")):
        d = json.load(open(f, encoding="utf-8"))
        gen = {b["type"]: b for b in ((d.get("config") or {}).get("gen") or {}).get("blocks") or []}
        rec = {b["type"] for b in ((d.get("config") or {}).get("rec") or {}).get("blocks") or []}
        name = os.path.basename(f)
        assert gen or rec, f"{name} : rien pour jouer seul"
        assert not ("standard" in gen and "drums" in gen), name
        if "standard" in gen:
            s = gen["standard"]
            factory_std = {os.path.basename(x)[:-6] for x in glob.glob(os.path.join(ROOT, "library", "factory", "standards", "*.golem"))}
            assert s["foot"] == 10 and s["params"]["standard"] in factory_std, name
            own = part.get(d.get("role"))
            if own:
                assert s["params"][own] is False, f"{name} : le Standard joue la partie de l'instrument"


def test_les_standards_de_l_usine_sont_libres_et_anonymes():
    """Alex, 2026-10-17 : toute grille que joue un patch ou un preset d'usine est un standard d'USINE (un golem neuf
    l'a), en CC0, au domaine public, avec un id de CONTENU (ct:) — jamais us: (une chanson perso de golem.fm) — et sans
    nom de personne ni trace de machine."""
    import re
    import zipfile
    from bridge import golemfile as G
    have = {os.path.basename(f)[:-6] for f in glob.glob(os.path.join(ROOT, "library", "factory", "standards", "*.golem"))}
    used = set()
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "**", "*.json"), recursive=True):
        def walk(x):
            if isinstance(x, dict):
                if x.get("type") == "standard" and (x.get("params") or {}).get("standard"):
                    used.add(x["params"]["standard"])
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(json.load(open(f, encoding="utf-8")))
    assert used and used <= have, sorted(used - have)
    for n in have:
        p = os.path.join(ROOT, "library", "factory", "standards", n + ".golem")
        z = zipfile.ZipFile(p)
        m = json.loads(z.read(G.MANIFEST))
        src = json.loads(z.read(G.CHART)).get("source") or {}
        assert m["id"].startswith("ct:") and m["id"] == G.content_id(m["artist"], m["title"], m["kind"]), n
        assert (m.get("rights") or {}).get("work") == "public-domain" and src.get("licence") == "CC0-1.0", n
        blob = " ".join(z.read(x).decode("utf-8", "replace") for x in z.namelist())
        assert not re.search(r"(?i)mucchielli|rapha[eë]l|/home/|golem_\d|serial", blob), n


def test_chaque_objet_d_usine_a_un_theme_sur_chaque_case_occupee():
    """Alex, 2026-10-20 : pas de preset d'usine sans animation (Diesel Heart l'était, « c'était une erreur »). Chaque
    case OCCUPÉE — une scène, un switch qui porte un bloc — a la couleur du thème et une animation de la palette."""
    from bridge import anim_packs
    known = {e["id"] for e in anim_packs.DEFAULT["effects"] if e["id"]}

    def blocks(ln):
        ch = ln.get("chain") or {}
        return (ch.get("pre") or []) + [x for br in ((ch.get("split") or {}).get("branches") or []) for x in br.get("blocks") or []] \
            + (ch.get("post") or [])
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "p*", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        feet = {b["foot"] for ln in d.get("lanes") or [] for b in blocks(ln) if b.get("foot")}
        feet |= {b["foot"] for v in (d.get("config") or {}).values() if isinstance(v, dict)
                 for b in v.get("blocks") or [] if b.get("foot")}
        cells = {s["id"] for s in d.get("scenes") or []} | {str(x) for x in feet}
        name = os.path.basename(f)
        assert cells <= set(d.get("colors") or {}), (name, cells - set(d.get("colors") or {}))
        assert len(set(d["colors"][k] for k in cells)) == 1, f"{name} : une seule couleur de thème"
        assert cells <= set(d.get("anims") or {}) and all(d["anims"][k] in known for k in cells), name


def test_le_champ_presets_d_une_setlist_d_usine_liste_ce_que_jouent_ses_lignes():
    """2026-10-20 : un générateur y avait écrit un NOMBRE. `presets` = l'id joué par chaque ligne, dans l'ordre —
    `patch:<id>` pour une banque de sons, l'id du preset pour une setlist de morceaux."""
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "setlists", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        want = [("patch:" + ln["patch"]) if ln.get("patch") else ln.get("preset") for ln in d["lines"]]
        assert d.get("presets") == want, os.path.basename(f)


def test_chaque_reglage_a_choix_d_un_objet_d_usine_est_une_option_du_catalogue():
    """2026-10-20 : neuf objets demandaient « 1/4• » au Tempo Delay, qui ne le proposait pas — golem_rig retombe alors
    SANS RIEN DIRE sur la première option. Une valeur d'énumération (bloc, état ou scène) est une option du catalogue."""
    cat = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"), encoding="utf-8"))
    enums = {e["type"]: {p["id"]: p["options"] for p in e.get("params") or [] if p.get("type") == "enum" and p.get("options")}
             for e in cat["effects"] if e.get("type")}

    def blocks(ln):
        ch = ln.get("chain") or {}
        return (ch.get("pre") or []) + [x for br in ((ch.get("split") or {}).get("branches") or []) for x in br.get("blocks") or []] \
            + (ch.get("post") or []) + (ch.get("chain") or [])
    bad = []
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "p*", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        types = {}
        for ln in d.get("lanes") or []:
            for b in blocks(ln):
                types[b["id"]] = b["type"]
                for pid, v in (b.get("params") or {}).items():
                    opts = enums.get(b["type"], {}).get(pid)
                    if opts and isinstance(v, str) and v not in opts:
                        bad.append((os.path.basename(f), b["id"], pid, v))
        overrides = [s.get("params") or {} for ln in d.get("lanes") or [] for s in ln.get("states") or []] + \
                    [s.get("params") or {} for s in d.get("scenes") or []]
        for over in overrides:
            for bid, ps in over.items():
                for pid, v in (ps or {}).items():
                    opts = enums.get(types.get(bid), {}).get(pid)
                    if opts and isinstance(v, str) and v not in opts:
                        bad.append((os.path.basename(f), bid, pid, v))
    assert not bad, bad


def test_une_ancienne_version_intacte_suit_l_usine_une_retouche_jamais(tmp_path, monkeypatch):
    """2026-10-22 : un golem posé le 19 jouait 37 objets d'usine périmés (la setlist d'usine ignorait le 9e preset), parce
    que la pose n'écrasait jamais rien. Désormais : une ANCIENNE version d'usine intacte (connue de history.json) est
    remplacée au démarrage ; une retouche reste, signalée par edited(), et seul reset() la remplace."""
    live = _setup(tmp_path, monkeypatch)
    live.mkdir()
    old_a, old_b = b'{"id": "factory-a", "v": "vieille"}', '{"id": "factory-b", "v": "retouché"}'
    (live / "factory-a.json").write_bytes(old_a.replace(b"\n", b"\r\n"))             # vieille version, posée en CRLF
    (live / "factory-b.json").write_text(old_b)
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"patches/factory-a.json": [F.hashlib.sha256(old_a).hexdigest()]}))
    monkeypatch.setattr(F, "HISTORY", str(hist))
    r = F.seed()
    assert r["updated"] == ["patches/factory-a.json"] and r["placed"] == []
    assert json.loads((live / "factory-a.json").read_text())["v"] == "usine"
    assert json.loads((live / "factory-b.json").read_text())["v"] == "retouché"        # une retouche ne bouge pas
    assert [e["file"] for e in F.edited()] == ["factory-b.json"]
    assert F.seed()["updated"] == []                                                  # rien ne se rejoue
    assert F.reset(["factory-b.json"])["reset"] == ["patches/factory-b.json"]
    assert json.loads((live / "factory-b.json").read_text())["v"] == "usine" and F.edited() == []


def test_ce_que_la_machine_ecrit_ne_bloque_pas_l_usine(tmp_path, monkeypatch):
    """2026-10-24 : un rack Windows gardait des patches d'usine périmés que personne n'avait ouverts — refresh_deps() y avait
    écrit les `deps` de sa bibliothèque, le Designer ses liaisons d'entrée, le Rec sa config. Une ANCIENNE version qui ne
    diffère que par ces écritures suit l'usine EN GARDANT les liaisons ; un vrai réglage changé reste une retouche."""
    live = _setup(tmp_path, monkeypatch)
    live.mkdir()
    old = {"id": "factory-a", "v": "vieille", "lanes": [{"id": "guitar-1", "in_sel": "1"}], "config": {"rec": {"tap": None}}}
    (tmp_path / "factory" / "patches" / "factory-a.json").write_text(json.dumps(
        {"id": "factory-a", "v": "usine", "lanes": [{"id": "guitar-1", "in_sel": "1"}], "config": {"rec": {"tap": None}}}))
    old_bytes = json.dumps(old).encode()
    machine = dict(old, deps=[{"bytes": 1023}], deps_sig="x",
                   lanes=[{"id": "guitar-1", "in_sel": "2", "in_name": "Guitar 1", "stereo": False}],
                   config={"rec": {"tap": "post"}})
    (live / "factory-a.json").write_text(json.dumps(machine))
    (live / "factory-b.json").write_text(json.dumps({"id": "factory-b", "v": "retouché", "deps_sig": "y"}))
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"patches/factory-a.json": [F.hashlib.sha256(old_bytes).hexdigest()],
                                "canon:patches/factory-a.json": [F.canon_sha(old_bytes)]}))
    monkeypatch.setattr(F, "HISTORY", str(hist))
    assert [e["file"] for e in F.edited()] == ["factory-b.json"]
    assert F.seed()["updated"] == ["patches/factory-a.json"]
    a = json.loads((live / "factory-a.json").read_text(encoding="utf-8"))
    assert a["v"] == "usine"                                                          # la nouvelle version d'usine…
    assert a["lanes"][0]["in_sel"] == "2" and a["lanes"][0]["in_name"] == "Guitar 1"  # …branchée comme avant
    assert a["config"]["rec"] == {"tap": "post"}
    assert [e["file"] for e in F.edited()] == ["factory-b.json"]
    assert F.seed()["updated"] == []                                                  # rien ne se rejoue


def test_l_historique_livre_connait_la_version_courante_de_chaque_objet_d_usine():
    """Sans elle, la prochaine release prendrait la version d'aujourd'hui pour une retouche et ne la mettrait jamais à
    jour. Le remède : `python tools/gen-factory-history.py` après toute modification de library/factory/."""
    hist = F._history()
    missing = []
    for kind, files in F.catalog().items():
        sub = F.KINDS[kind][0]
        for fn in files:
            if F._sha(os.path.join(F.SRC, sub, fn)) not in set(hist.get(f"{sub}/{fn}") or []):
                missing.append(f"{sub}/{fn}")
    assert not missing, f"run tools/gen-factory-history.py — not in history.json: {missing}"
