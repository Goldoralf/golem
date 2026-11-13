# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests à froid du compilateur actif (bridge/compile_rig.py) : preset paths -> <id>.rig.json.

ZÉRO Reaper, ZÉRO vrai asset : une mini-bibliothèque factice vit dans tmp_path (des .nam qui
sont du JSON minimal avec metadata.loudness, des .wav vides) et TOUS les chemins du module
(OUT_DIR, ASSET_CACHE, IO_PATH, components.json, catalogue de tones) sont détournés par
monkeypatch — on ne lit ni n'écrit jamais library/ ou reaper/FXChains/ du dépôt.

Régressions visées :
  - bug volume 2026-07-23 : normalisation de loudness des captures NAM vers LOUD_TARGET (-18),
    le potard `output` de l'utilisateur restant un OFFSET par-dessus, clampé à ±20 ;
  - cab par défaut (DEFAULT_CAB) fondu quand une tête NAM n'a pas de cab — et tête SEULE quand
    le cab vit en aval dans une branche de split (split des cabs) ;
  - garde de format (doctrine « repli jamais silencieux ») : un .wav dans un bloc NAM -> bloc
    bypassé, pas un modèle fantôme muet ;
  - clamp des params hors plage (bug piste-6 Prism : chorus.mix=30 dans un port 0..1) ;
  - DÉTERMINISME de la sortie — le prérequis d'un futur témoin sha façon tools/fcb/check-uno2.py.
"""
import json
import os

import pytest

from bridge import compile_rig, resolver
from bridge import config as C


# ── mini-bibliothèque factice + détournement de tous les chemins ─────────────────────────────
@pytest.fixture
def rigc(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()

    def _nam(name, loudness):
        """Un .nam est du JSON ; seul metadata.loudness compte pour la compile."""
        meta = {"loudness": loudness} if loudness is not None else {}
        p = lib / f"{name}.nam"
        p.write_text(json.dumps({"metadata": meta}))
        return str(p)

    def _wav(name):
        p = lib / f"{name}.wav"
        p.write_bytes(b"RIFF")          # le contenu est indifférent : la compile ne lit que le chemin
        return str(p)

    # chemins ABSOLUS sous tmp_path : le résolveur ne sert que ce qui vit sous une racine autorisée
    # (audit 2026-09-13, B1) — on déclare la nôtre, sans toucher C.ROOT
    monkeypatch.setattr(C, "ASSET_ROOTS", [C.ROOT, str(tmp_path)])
    comps = {
        "amps": [{"id": "amp-clean", "file": _nam("amp-clean", -11.0)},
                 {"id": "amp-noloud", "file": _nam("amp-noloud", None)},
                 {"id": "amp-hot", "file": _nam("amp-hot", -45.0)}],
        "cabs": [{"id": "cab-412", "file": _wav("cab-412")},
                 {"id": compile_rig.DEFAULT_CAB, "file": _wav(compile_rig.DEFAULT_CAB)}],
        "pedals": [],
    }
    comp_file = tmp_path / "components.json"
    comp_file.write_text(json.dumps(comps))
    io_file = tmp_path / "io.json"
    io_file.write_text(json.dumps({"outputs": [{"ch": 1}, {"ch": 2}],
                                   "mono_fallback": {"on": False, "gain": -3}}))

    monkeypatch.setattr(resolver, "COMPONENTS", str(comp_file))
    monkeypatch.setattr(resolver, "_TONES", {"mtime": None, "idx": None})   # cache neuf par test
    monkeypatch.setattr(C, "CATALOG", str(tmp_path / "tones-absent.json"))  # pas de catalogue tones
    monkeypatch.setattr(compile_rig, "OUT_DIR", str(tmp_path / "FXChains"))
    monkeypatch.setattr(compile_rig, "IO_PATH", str(io_file))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / ".cache"))
    monkeypatch.setattr(compile_rig, "COMPILE_TARGET", "linux")
    # defs de params contrôlées (le vrai effects.json du dépôt ne doit pas influencer un test)
    monkeypatch.setattr(compile_rig, "_FX_DEFS",
                        {"delay": {"mix": {"id": "mix", "min": 0, "max": 1}}})
    return compile_rig


def _preset(chain, pid="t1", out=1):
    return {"id": pid,
            "paths": [{"id": "g", "name": "guitar", "input": 1, "chain": chain, "out": out}]}


def _compile(preset):
    path = compile_rig.compile_preset(preset)
    return json.load(open(path)), path


def _main_blocks(plan):
    return plan["paths"][0]["tracks"][0]["blocks"]


def _core_text(plan, track=0):
    fn = plan["paths"][0]["tracks"][track]["rfxchain"]
    return open(os.path.join(compile_rig.OUT_DIR, fn), "rb").read().decode("latin-1")


def test_native_core_keeps_amp_and_cab_independent(rigc, monkeypatch):
    monkeypatch.setattr(rigc, "COMPILE_TARGET", "win32")
    plan, _ = _compile(_preset([
        {"id": "a1", "type": "amp-nam", "ref": "amp-clean"},
        {"id": "c1", "type": "cab", "ref": "cab-412"},
    ]))
    track = plan["paths"][0]["tracks"][0]
    assert "rfxchain" not in track
    assert track["native_core"]["amp_id"] == "a1"
    assert track["native_core"]["cab_id"] == "c1"
    assert track["native_core"]["model"].endswith(".nam")
    assert track["native_core"]["ir"].endswith(".wav")


def test_native_core_cab_only_and_baked_cab(rigc, monkeypatch):
    monkeypatch.setattr(rigc, "COMPILE_TARGET", "darwin")
    cab, _ = _compile(_preset([{"id": "c1", "type": "cab", "ref": "cab-412"}], pid="cab"))
    core = cab["paths"][0]["tracks"][0]["native_core"]
    assert core["model"] == "" and core["ir"].endswith(".wav")
    baked, _ = _compile(_preset([{"id": "a1", "type": "amp", "ref": "amp-clean"}], pid="baked"))
    core = baked["paths"][0]["tracks"][0]["native_core"]
    assert core["model"].endswith(".nam") and core["ir"] == ""


# ── compilation d'un preset minimal ──────────────────────────────────────────────────────────
def test_preset_minimal_produit_un_plan_coherent(rigc):
    """1 lane guitare (gate + NAM + IR + delay) -> .rig.json : blocs DANS L'ORDRE, chemins
    NAM/IR résolus vers des fichiers existants, cœur file-loaders baké sans placeholder."""
    plan, path = _compile(_preset([
        {"type": "gate", "params": {"threshold": -50}},
        {"type": "amp-nam", "ref": "amp-clean"},
        {"type": "cab", "ref": "cab-412"},
        {"type": "delay", "params": {"mix": 0.3}},
    ]))
    assert path.endswith("t1.rig.json") and os.path.exists(path)
    assert plan["id"] == "t1"
    assert plan["mono_fallback"] == {"on": False, "gain": -3}

    track = plan["paths"][0]["tracks"][0]
    assert track["role"] == "main" and track["input"] == 1 and track["out"] == 1
    assert [b["type"] for b in track["blocks"]] == ["gate", "amp-nam", "cab", "delay"]

    amp = track["blocks"][1]
    cab = track["blocks"][2]
    assert amp["file"].endswith(".nam") and os.path.exists(amp["file"])
    assert cab["file"].endswith(".wav") and os.path.exists(cab["file"])

    # cœur NAM+x42 : les placeholders ont TOUS été substitués par les chemins assainis
    assert track["core_types"] == ["amp", "amp-nam", "cab"]
    core = _core_text(plan)
    assert "%MODEL%" not in core and "%IR%" not in core
    assert "amp-clean.nam" in core and "cab-412.wav" in core


# ── normalisation de loudness (le bug volume vécu) ───────────────────────────────────────────
def test_loudness_normalisee_vers_la_cible(rigc):
    """Capture à -11 dB, cible -18 : la sortie du bloc doit encaisser -7. Le potard `output`
    de l'utilisateur (+3) reste un offset PAR-DESSUS la sortie normalisée -> -4."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean"},
                                {"type": "cab", "ref": "cab-412"}]))
    amp = _main_blocks(plan)[0]
    assert amp["params"]["output"] == pytest.approx(-7.0)
    assert amp["params"]["_loud"] == pytest.approx(-11.0)      # traçabilité dans le rig.json

    plan2, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean", "params": {"output": 3}},
                                 {"type": "cab", "ref": "cab-412"}], pid="t2"))
    assert _main_blocks(plan2)[0]["params"]["output"] == pytest.approx(-4.0)


def test_outboard_normalise_comme_un_ampli_la_pedale_non(rigc):
    """Un préampli/compresseur CAPTURÉ (outboard, 2026-09-14) est un étage de gain complet : sa
    sortie est ramenée à la cible comme celle d'un ampli (-11 -> -7 de trim). Une pédale capturée
    ne l'est PAS : un boost doit booster."""
    plan, _ = _compile(_preset([{"type": "preamp-nam", "ref": "amp-clean"},
                                {"type": "comp-nam", "ref": "amp-clean", "params": {"output": 3}},
                                {"type": "pedal-nam", "ref": "amp-clean", "params": {"output": 3}},
                                {"type": "amp-nam", "ref": "amp-clean"}, {"type": "cab", "ref": "cab-412"}]))
    pre, comp, ped = _main_blocks(plan)[:3]
    assert pre["type"] == "preamp-nam" and pre["file"].endswith("amp-clean.nam")
    assert pre["params"]["output"] == pytest.approx(-7.0)
    assert comp["params"]["output"] == pytest.approx(-4.0)      # offset utilisateur par-dessus
    assert ped["params"]["output"] == pytest.approx(3.0)        # pédale : pas touchée


def test_loudness_clampee_a_la_plage_du_slider(rigc):
    """Capture très faible (-45) : le trim théorique (+27) dépasse le slider Output Lvl (±20)
    du plugin -> clamp à +20, jamais une valeur que le plugin ne peut pas prendre."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-hot"},
                                {"type": "cab", "ref": "cab-412"}]))
    assert _main_blocks(plan)[0]["params"]["output"] == pytest.approx(20.0)


def test_loudness_absente_ne_touche_pas_la_sortie(rigc):
    """Un .nam sans metadata.loudness (vieille capture) : on ne devine pas, on ne touche rien."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-noloud", "params": {"output": 2}},
                                {"type": "cab", "ref": "cab-412"}]))
    pm = _main_blocks(plan)[0]["params"]
    assert pm["output"] == 2 and "_loud" not in pm


# ── cab par défaut / split des cabs ──────────────────────────────────────────────────────────
def test_tete_isolee_recoit_le_cab_par_defaut(rigc):
    """Un ampli NAM sans aucun cab dans le path -> DEFAULT_CAB fondu dans le cœur (sinon la
    tête sortirait crue dans les moniteurs)."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean"}]))
    core = _core_text(plan)
    assert compile_rig.DEFAULT_CAB in core
    assert "%IR%" not in core


def test_tete_seule_quand_le_cab_est_en_aval(rigc):
    """Split des cabs : ampli avant un fan-out dont les branches portent les cabs -> la piste
    pre rend une TÊTE NAM seule (pas de cab défaut injecté), les branches rendent le x42."""
    preset = {"id": "t1", "paths": [{"id": "g", "input": 1, "out": None, "chain": [
        {"type": "amp-nam", "ref": "amp-clean"},
        {"split": {"merge": None, "branches": [
            {"id": "L", "blocks": [{"type": "cab", "ref": "cab-412"}], "out": 1},
            {"id": "R", "blocks": [{"type": "cab", "ref": "cab-412"}], "out": 2}]}}]}]}
    plan, _ = _compile(preset)
    tracks = plan["paths"][0]["tracks"]
    assert [t["role"] for t in tracks] == ["pre", "branch", "branch"]
    head = _core_text(plan, 0)
    assert "amp-clean.nam" in head
    assert "zeroconvolv" not in head                       # pas de convolver sur la tête
    assert compile_rig.DEFAULT_CAB not in head             # et surtout pas le cab par défaut
    branch = _core_text(plan, 1)
    assert "cab-412.wav" in branch and "neural-amp-modeler" not in branch


# ── robustesse : bypass, bloc inconnu, mauvais format ────────────────────────────────────────
def test_bloc_bypasse_et_bloc_inconnu_ne_cassent_rien(rigc):
    """Un bloc bypassé est porté tel quel ; un type inconnu du catalogue passe sans clamp ni
    crash (golem_rig tranchera) — la compile ne doit jamais tomber sur du contenu de preset."""
    plan, _ = _compile(_preset([
        {"type": "gate", "bypass": True},
        {"type": "blorptron-9000", "params": {"x": 3}},
        {"type": "amp-nam", "ref": "amp-clean"},
        {"type": "cab", "ref": "cab-412"},
    ]))
    blocks = _main_blocks(plan)
    assert blocks[0]["bypass"] is True
    assert blocks[1]["type"] == "blorptron-9000" and blocks[1]["params"] == {"x": 3}


def test_garde_de_format_bypasse_un_nam_nourri_dun_wav(rigc):
    """Doctrine « repli jamais silencieux » (bug voix looper-test 2026-07-19) : un bloc NAM
    dont la ref résout un .wav n'a PAS de modèle -> pas de `file`, bloc BYPASSÉ et tracé,
    au lieu d'un silence inexplicable."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "cab-412"}]))
    amp = _main_blocks(plan)[0]
    assert amp.get("bypass") is True
    assert "file" not in amp


def test_param_hors_plage_est_clampe(rigc):
    """Bug piste-6 Prism : delay.mix=30 dans un port 0..1 -> clampé à 1, jamais matérialisé
    tel quel dans le rig.json."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean"},
                                {"type": "cab", "ref": "cab-412"},
                                {"type": "delay", "params": {"mix": 30}}]))
    assert _main_blocks(plan)[2]["params"]["mix"] == 1


def test_bloc_looper_marqueur_consomme_au_niveau_preset(rigc):
    """Le bloc `looper` est un MARQUEUR : il active plan.looper (avec la table par défaut)
    et ne doit JAMAIS apparaître comme FX dans les blocs de piste."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean"},
                                {"type": "cab", "ref": "cab-412"},
                                {"type": "looper"}]))
    assert plan["looper"] and plan["looper"]["enabled"]
    assert [r["sw"] for r in plan["looper"]["loops"]] == [1, 2, 3]     # table par défaut (rangée proche)
    assert "looper" not in [b["type"] for b in _main_blocks(plan)]


# ── déterminisme ─────────────────────────────────────────────────────────────────────────────
def test_deux_compilations_rendent_les_memes_octets(rigc):
    """Prérequis d'un futur témoin sha (façon tools/fcb/check-uno2.py) : même preset, même
    bibliothèque -> .rig.json ET .RfxChain identiques octet pour octet."""
    preset = _preset([
        {"type": "gate", "params": {"threshold": -50}},
        {"type": "amp-nam", "ref": "amp-clean", "params": {"output": 1.5}},
        {"type": "cab", "ref": "cab-412"},
        {"type": "delay", "params": {"mix": 0.3}},
        {"type": "looper"},
    ])
    p1 = compile_rig.compile_preset(preset)
    first = open(p1, "rb").read()
    plan = json.loads(first)
    core1 = _core_text(plan)
    p2 = compile_rig.compile_preset(preset)
    assert p2 == p1
    assert open(p2, "rb").read() == first
    assert _core_text(json.loads(first)) == core1


# ── UID DE PACK EN `ref` (2026-09-11) ────────────────────────────────────────────────────────
# Un patch poussé par golem.fm référençait « t3k:44209 » — l'UID DE PACK (docs/private/exchanges/maestrium-tones-api.md),
# alors que l'index des tones est tenu par l'ID DU CATALOGUE (« 44209 »). Rien ne résolvait, le
# template gardait « %MODEL% », et le NAM se chargeait SANS modèle : patch MUET, aucune erreur.
def test_ref_accepte_luid_de_pack_t3k(monkeypatch):
    from bridge import resolver
    tone = {"id": 44209, "models": [{"id": 567082, "file": "assets/models/x/jcm800.nam"}]}
    # l'index se recharge sur le mtime du catalogue : on remplace la FONCTION, pas le cache
    monkeypatch.setattr(resolver, "_tones_index", lambda: {"44209": tone})
    par_id = resolver._resolve("44209", {})
    par_uid = resolver._resolve("t3k:44209", {})
    assert par_id and os.path.normpath(par_id).endswith(os.path.normpath("assets/models/x/jcm800.nam"))
    assert par_uid == par_id                      # les deux formes désignent le même tone
    assert resolver._resolve("t3k:45022", {}) is None   # pack non installé = toujours None, sans invention
    assert resolver._resolve("", {}) is None


# ── UN BLOC À CAPTURE VIDE COUPE SA BRANCHE (2026-09-11) ────────────────────────────────────
# Un NAM sans modèle et un convolver sans IR ne laissent RIEN passer. Le patch « 1983 » de
# golem.fm portait cinq blocs sans `ref` : les deux branches étaient muettes, et rien ne le
# disait puisqu'aucun fichier n'était ATTENDU. Le rig ne pose plus ces blocs — et le dit.
def test_un_bloc_a_capture_sans_fichier_est_retire_du_rig(tmp_path):
    from bridge import rig
    (tmp_path / "ok.nam").write_text("{}")                  # un fichier RÉEL : un chemin effacé ne compte plus
    resolve = lambda ref, model=None: str(tmp_path / ("%s.nam" % ref)) if ref in ("ok", "gone") else None
    blocks = [{"id": "c", "type": "comp"},
              {"id": "a1", "type": "amp-nam", "ref": "ok"},       # capture chargeable : gardé
              {"id": "a2", "type": "amp-nam"},                    # AUCUNE capture nommée
              {"id": "a3", "type": "amp-nam", "ref": "absent"},   # capture nommée, pas installée
              {"id": "cb", "type": "cab"},                        # idem pour l'IR
              {"id": "a4", "type": "amp-nam", "ref": "gone"},     # indexée, fichier effacé (block-status.md §3)
              {"id": "d", "type": "delay"}]
    assert [b["id"] for b in rig._drop_empty_capture(blocks, resolve)] == ["c", "a1", "d"]


def test_sans_resolver_on_ne_juge_pas():
    """Plan sans résolution de fichiers : on ne retire jamais ce qu'on n'a pas pu vérifier."""
    from bridge import rig
    blocks = [{"id": "a2", "type": "amp-nam"}]
    assert rig._drop_empty_capture(blocks, None) == blocks


# ── UNE BRANCHE VIDÉE PAR LE RIG SE TAIT (décision 2026-09-12) ────────────────────────
# Le cas qui pique n'est pas deux branches vides (on reconnaît du sec d'emblée) : c'est UNE
# branche pleine et UNE vidée. Du signal sec se glisse alors sous un vrai ampli, et ça s'entend
# comme un patch mal voisé — l'oreille va chercher le défaut dans l'ampli.
def _split_path(branches, gain=None):
    sp = {"merge": ({"gain": gain} if gain is not None else {}), "branches": branches}
    return {"id": "guitar", "name": "g", "input": "1", "out": "1-2", "out_sel": "1-2",
            "chain": [{"split": sp}]}


def _tracks(branches, gain=None, resolve=lambda ref, model=None: None):
    from bridge import rig
    return {t["name"]: t for t in rig._path_tracks(_split_path(branches, gain), resolve)}


def test_une_branche_videe_est_mutee_lautre_joue():
    br = [{"id": "a", "blocks": [{"id": "amp", "type": "amp-nam"}]},          # capture vide -> vidée
          {"id": "b", "blocks": [{"id": "d", "type": "delay"}]}]             # garde son bloc
    tr = _tracks(br)
    assert tr["GoleM:guitar/a"]["mute"] is True
    assert not tr["GoleM:guitar/b"]["mute"]


def test_si_TOUTES_sont_videes_une_voie_reste_passante():
    """Sinon le patch redevient muet — ce qu'on venait de corriger — et deux voies sèches
    sommées donneraient le même signal deux fois."""
    br = [{"id": "a", "blocks": [{"id": "amp1", "type": "amp-nam"}]},
          {"id": "b", "blocks": [{"id": "amp2", "type": "amp-nam"}]}]
    tr = _tracks(br)
    mutes = [bool(tr["GoleM:guitar/a"]["mute"]), bool(tr["GoleM:guitar/b"]["mute"])]
    assert mutes == [False, True]                     # exactement une voie passe


def test_une_branche_vide_DANS_LE_DOCUMENT_nest_pas_touchee():
    """Une voie sèche en parallèle de l'ampli est un CHOIX de son (blend dry), pas un accident :
    on ne tait que ce qu'on a soi-même vidé."""
    br = [{"id": "dry", "blocks": []},
          {"id": "amp", "blocks": [{"id": "d", "type": "delay"}]}]
    tr = _tracks(br)
    assert not tr["GoleM:guitar/dry"]["mute"]


def test_le_gain_de_somme_vaut_moins_3_par_defaut():
    """UNE convention : l'écran du Designer, le chemin legacy et preset-schema.md disaient tous
    −3 ; ce chemin appliquait 0, et l'écran mentait de 3 dB (mesuré sur « 1983 »)."""
    br = [{"id": "a", "blocks": [{"id": "d", "type": "delay"}]}]
    assert _tracks(br)["GoleM:guitar#merge"]["merge_gain"] == -3
    assert _tracks(br, gain=0)["GoleM:guitar#merge"]["merge_gain"] == 0     # explicite : respecté


# ── UNE REF PEUT RÉSOUDRE ET RESTER INUTILISABLE (patch « Titan », 2026-09-12) ──────────────
# Le bloc `cab` portait `t3k:53952` : une capture amp-cab au format NAM. La ref résolvait — le
# tone existe, le fichier est là — donc rien ne criait avant la compile. Mais le convolver x42
# ne charge pas un .nam : il n'a rien chargé, et la lane s'est tue. Vérifier qu'une ref EXISTE
# ne dit rien sur ce qu'elle CONTIENT.
def test_un_cab_qui_recoit_un_nam_est_refuse():
    from bridge import rig
    assert rig._wrong_kind({"type": "cab"}, "/x/blackstar-series-one-a2.nam")
    assert rig._wrong_kind({"type": "amp-nam"}, "/x/mesa-4x12.wav")
    assert rig._wrong_kind({"type": "pedal-nam"}, "/x/ir.wav")
    # QUATRE blocs à capture, pas trois : `amp` (le rig complet en une capture) charge un .nam.
    # Mon test d'hier affirmait le contraire et DÉFENDAIT le trou — golem.fm l'a relevé en
    # corrigeant le sien, qui affirmait qu'un `amp` ne charge rien.
    assert rig._wrong_kind({"type": "amp"}, "/x/une-ir.wav")
    # OUTBOARD (2026-09-14) : un pack TONE3000 gear=outboard peut être au format IR (une bande, une
    # console capturée en réponse impulsionnelle) — dans un bloc NAM, c'est un silence. Refusé, dit.
    assert rig._wrong_kind({"type": "preamp-nam"}, "/x/neve-1073-ir.wav")
    assert rig._wrong_kind({"type": "comp-nam"}, "/x/la2a.flac")


def test_les_bonnes_associations_passent():
    from bridge import rig
    assert rig._wrong_kind({"type": "cab"}, "/x/Mesa_4x12.wav") is None
    assert rig._wrong_kind({"type": "cab"}, "/x/IR.FLAC") is None          # casse ignorée
    assert rig._wrong_kind({"type": "amp-nam"}, "/x/evh-stealth-a2.nam") is None
    assert rig._wrong_kind({"type": "amp"}, "/x/jcm800-a2.nam") is None     # le rig complet EST un .nam
    assert rig._wrong_kind({"type": "delay"}, "/x/rien") is None            # pas un bloc à capture
    assert rig._wrong_kind({"type": "preamp-nam"}, "/x/1073MP - 40 dB - A.nam") is None
    assert rig._wrong_kind({"type": "comp-nam"}, "/x/1176LN - Inp0.nam") is None


def test_les_six_blocs_a_capture_sont_les_memes_partout():
    """UNE liste, quatre maisons (rig, export, jobs, patches) : un type ajouté d'un côté et
    oublié de l'autre est exactement le silence de septembre (un bloc que rien n'attend)."""
    from bridge import patches, preset_export, rig, tones_jobs
    six = {"amp", "amp-nam", "cab", "pedal-nam", "preamp-nam", "comp-nam"}
    assert set(rig.CAPTURE_TYPES) == six == set(rig.CAPTURE_EXT) == set(preset_export.CAP_TYPES) \
        == set(tones_jobs.CAPTURE_TYPES) == set(patches.BLOCK_GEARS)
    assert patches.BLOCK_GEARS["preamp-nam"] == patches.BLOCK_GEARS["comp-nam"] == ("outboard",)


def test_un_bloc_mal_type_est_bypasse_et_ne_nourrit_plus_le_coeur():
    """La doctrine « repli jamais silencieux » BYPASSE (elle ne retire pas) — mais le cœur
    ré-résolvait la ref sans voir le bypass, et le convolver recevait le .nam quand même.
    Bypassé = ne fournit plus son fichier : l'ampli retombe sur le cab par défaut."""
    from bridge import rig, compile_rig
    blocks = [rig._prep_block({"id": "amp", "type": "amp-nam", "ref": "a"}, lambda r, m=None: "/x/a.nam"),
              rig._prep_block({"id": "cab", "type": "cab", "ref": "b"}, lambda r, m=None: "/x/b.nam")]
    assert blocks[1]["bypass"] is True and "file" not in blocks[1]
    assert blocks[0]["file"] == "/x/a.nam"
    usable = [b for b in blocks if not b.get("bypass")]
    assert [b["id"] for b in usable] == ["amp"]        # le cœur ne verra plus le cab bypassé


def test_un_cab_bypasse_ne_prive_pas_lampli_de_baffle(rigc):
    """Suite du patch « Titan » : le cab bypassé faisait croire qu'un baffle attendait en aval,
    donc le cœur rendait une TÊTE SEULE — l'ampli sortait sans baffle, très fizzy. Un cab qui ne
    charge rien n'est pas un cab en aval : le cab par défaut reprend sa place."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean"},
                                {"type": "cab", "ref": "amp-clean"}]))   # une capture NAM sur un cab
    blocks = _main_blocks(plan)
    assert blocks[1].get("bypass") is True                               # la garde a fait son office
    core = [t for p in plan["paths"] for t in p["tracks"] if t.get("rfxchain")]
    assert core, "le cœur doit être rendu : ampli + cab par défaut, pas une tête nue"


# ── DEUX BAFFLES EN SÉRIE (2026-09-12) ──────────────────────────────────────────────────────
# La SEULE nature que le fichier ne peut pas trancher : `amp` seul contre `amp-cab` sont deux
# .nam. Elle reste déclarée, sa source est l'auteur de la capture, et golem.fm s'en protège avec
# la même déclaration — barrière faible des deux côtés. Le rack ne peut pas faire mieux sur la
# donnée ; il peut le DIRE, et il est le seul à parler quand quelqu'un ENTEND.
def _gear(**m):
    return lambda ref: m.get(str(ref))


def test_un_amp_cab_suivi_dun_cab_est_signale():
    from bridge import rig
    blocks = [{"id": "amp1", "type": "amp-nam", "ref": "53952"}, {"id": "cab1", "type": "cab", "ref": "42"}]
    assert rig.stacked_cab(blocks, _gear(**{"53952": "amp-cab", "42": "cab"})) == ["amp1"]


def test_un_amp_seul_suivi_dun_cab_est_NORMAL():
    """C'est la chaîne canonique : une tête + son baffle. Crier ici rendrait l'avertissement inutile."""
    from bridge import rig
    blocks = [{"id": "amp1", "type": "amp-nam", "ref": "28245"}, {"id": "cab1", "type": "cab", "ref": "42"}]
    assert rig.stacked_cab(blocks, _gear(**{"28245": "amp", "42": "cab"})) == []


def test_un_amp_cab_SANS_cab_derriere_est_normal():
    from bridge import rig
    blocks = [{"id": "amp1", "type": "amp-nam", "ref": "53952"}]
    assert rig.stacked_cab(blocks, _gear(**{"53952": "amp-cab"})) == []


def test_un_cab_bypasse_ne_compte_pas_comme_second_baffle():
    """Il ne charge rien : signaler un empilement qui ne sonne pas enverrait chercher un défaut
    qui n'existe pas."""
    from bridge import rig
    blocks = [{"id": "amp1", "type": "amp-nam", "ref": "53952"},
              {"id": "cab1", "type": "cab", "ref": "42", "bypass": True}]
    assert rig.stacked_cab(blocks, _gear(**{"53952": "amp-cab", "42": "cab"})) == []


# ── UNE SCÈNE QUI NE LAISSE AUCUN CHEMIN AUDIBLE (patch « Hammer », 2026-09-12) ─────────────
# Deux branches, une par son. Le bloc de la branche clean n'avait pas de capture : retiré, et dit.
# Mais la scène « Clean » MUTE l'autre branche — donc en scène A, la seule voie ouverte était une
# branche vide : un DI brut, inaudible. B/C/D sonnaient. L'avertissement parlait d'un BLOC, le
# silence arrivait au niveau d'une SCÈNE, et personne ne pouvait faire le lien.
def _lane2(a_blocks, b_blocks):
    return {"id": "g", "chain": {"pre": [], "post": [], "split": {"mode": "merge", "branches": [
        {"id": "lane-a", "blocks": a_blocks}, {"id": "lane-b", "blocks": b_blocks}]}}}


def test_la_scene_qui_mute_la_seule_branche_porteuse_est_signalee():
    from bridge import rig
    lane = _lane2([], [{"id": "b11", "type": "amp"}])          # lane-a vidée par le rig
    scenes = [{"id": "A", "branches": {"lane-b": {"mute": True}}},   # ne reste que le vide
              {"id": "B", "branches": {"lane-a": {"mute": True}}}]   # reste l'ampli : OK
    out = rig.silent_scenes(lane, scenes)
    assert [w["scene"] for w in out] == ["A"]
    assert out[0]["empty_branches"] == ["lane-a"]      # nommée : sinon on cherche dans les autres


def test_une_scene_qui_laisse_une_branche_pleine_ne_dit_rien():
    from bridge import rig
    lane = _lane2([{"id": "b1", "type": "amp"}], [{"id": "b2", "type": "amp"}])
    scenes = [{"id": "A", "branches": {"lane-b": {"mute": True}}}]
    assert rig.silent_scenes(lane, scenes) == []


def test_une_lane_sans_split_nest_jamais_concernee():
    from bridge import rig
    lane = {"id": "g", "chain": {"pre": [{"id": "b1", "type": "amp"}], "split": None, "post": []}}
    assert rig.silent_scenes(lane, [{"id": "A"}]) == []


# ── UN RIG COMPLET NE REÇOIT PAS DE BAFFLE EN PLUS (patch « Hammer », 2026-09-12) ───────────
# « ampli isolé -> cab défaut fondu » est juste pour une TÊTE, faux pour un Head+Cab : la capture
# porte déjà son baffle, et le défaut en ajoutait un second. Deux baffles en série s'entendent
# comme une couverture sur l'ampli — donc comme un mauvais réglage, et on cherche des heures.
def test_un_bloc_amp_ne_recoit_pas_le_cab_par_defaut():
    from bridge import compile_rig
    assert compile_rig._carries_cab({"type": "amp", "ref": "x"}) is True


def test_une_tete_seule_le_recoit():
    from bridge import compile_rig
    assert compile_rig._carries_cab({"type": "amp-nam", "ref": "inconnu-au-catalogue"}) is False


def test_une_capture_amp_cab_sur_une_tete_est_reconnue(monkeypatch):
    """Le mauvais appariement tombe par le second côté : golem.fm le refuse avant l'envoi, mais
    un document ancien peut encore le porter."""
    from bridge import compile_rig, resolver
    monkeypatch.setattr(resolver, "_tones_index", lambda: {"31332": {"gear": "amp-cab"}})
    assert compile_rig._carries_cab({"type": "amp-nam", "ref": "t3k:31332"}) is True
    assert compile_rig._carries_cab({"type": "amp-nam", "ref": "31332"}) is True


def test_un_ampli_coupe_par_la_scene_reste_dans_le_coeur(rigc):
    """Mesuré le 2026-09-14 (Sunfunk « Heavy ») : un ampli BYPASSÉ par la scène courante était exclu du
    cœur au compile — la branche se bâtissait sans NAM, et aucune bascule de scène ne pouvait le
    faire revenir. Le bypass de scène est un ÉTAT (posé côté rig) ; seule la mauvaise NATURE de
    fichier (`_wrong_kind`) retire un bloc du cœur : le NAM est là, le bloc reste marqué bypassé."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "amp-clean", "bypass": True}]))
    core = _core_text(plan)
    assert "amp-clean.nam" in core                          # le NAM est construit…
    assert _main_blocks(plan)[0].get("bypass") is True     # …et le bloc reste à couper par la scène


def test_un_nam_nourri_dun_wav_est_marque_et_exclu_du_coeur(rigc):
    """La garde de format garde son effet : le bloc porte `_wrong_kind` et ne fournit rien au cœur."""
    plan, _ = _compile(_preset([{"type": "amp-nam", "ref": "cab-412"}]))
    amp = _main_blocks(plan)[0]
    assert amp.get("bypass") is True and amp.get("_wrong_kind")
    assert "rfxchain" not in plan["paths"][0]["tracks"][0]   # aucun cœur : rien à charger


# ── HARMONIE gfx-pitch : Key/Scale suivent la tonalité du morceau (2026-11-13) ──────────────────
@pytest.fixture
def golem_engine(rigc, monkeypatch):
    """pitch est en quarantaine sous REAPER (ReaPitch) : ces tests compilent comme le Golem Engine (gfx-pitch)."""
    from bridge import rig
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: {"pitch"})
    return rigc


@pytest.mark.parametrize("s,want", [("Em", (4, True)), ("Bb", (10, False)), ("F#m", (6, True)),
                                    ("C minor", (0, True)), ("Eb maj", (3, False)), ("Cb", (11, False)),
                                    ("Original", None), ("Cmaj7", None), ("", None), (None, None)])
def test_une_tonalite_se_lit(s, want):
    assert compile_rig.parse_song_key(s) == want


def test_l_harmonie_prend_la_tonalite_du_patch(golem_engine):
    harm = {"id": "h", "type": "pitch", "params": {"shift": 4, "harmony": "Scale", "key": "C", "scale": "Major"}}
    plan, _ = _compile({**_preset([harm]), "key": "Em"})
    pm = _main_blocks(plan)[0]["params"]
    assert pm["key"] == "E" and pm["scale"] == "Minor" and "song_key" not in pm


def test_un_mode_de_la_bonne_famille_reste_et_song_key_eteint_garde_la_main(golem_engine):
    dor = {"id": "h", "type": "pitch", "params": {"harmony": "Scale", "scale": "Dorian"}}
    hand = {"id": "m", "type": "pitch", "params": {"harmony": "Scale", "key": "G", "scale": "Major", "song_key": False}}
    plan, _ = _compile({**_preset([dor, hand]), "key": "Am"})
    a, b = _main_blocks(plan)[:2]
    assert (a["params"]["key"], a["params"]["scale"]) == ("A", "Dorian")
    assert (b["params"]["key"], b["params"]["scale"]) == ("G", "Major") and "song_key" not in b["params"]


def test_sans_tonalite_rien_ne_bouge(golem_engine):
    harm = {"id": "h", "type": "pitch", "params": {"harmony": "Scale", "key": "D", "scale": "Lydian"}}
    pm = _main_blocks(_compile(_preset([harm]))[0])[0]["params"]
    assert (pm["key"], pm["scale"]) == ("D", "Lydian")


def test_la_tonalite_vient_du_bloc_standard_a_defaut():
    pre = {"id": "s", "lanes_v": 2, "lanes": [{"id": "g", "role": "guitar",
                                 "chain": {"pre": [{"id": "std", "type": "standard", "params": {"key": "Gm"}}]}}]}
    assert compile_rig.song_key_of(pre) == (7, True)
    assert compile_rig.song_key_of({**pre, "key": "D"}) == (2, False)


def test_le_plan_cuit_emporte_la_tonalite_jusqu_a_la_compile():
    from bridge import scene_bake
    p = {"id": "x", "lanes_v": 2, "key": "E minor", "scenes": [{"id": "A", "blocks": {}}],
         "lanes": [{"id": "guitar", "role": "guitar", "in_sel": "1",
                    "chain": {"pre": [{"id": "h", "type": "pitch", "params": {}}], "split": None, "post": []}}],
         "config": {"arr": {"blocks": [{"id": "std", "type": "standard", "params": {"key": "Bbm"}}]}}}
    assert scene_bake.to_paths_preset(p, "A")["key"] == "Em"            # le `key` du preset passe devant
    p.pop("key")
    assert scene_bake.to_paths_preset(p, "A")["key"] == "Bbm"           # sinon celui du bloc Standard
