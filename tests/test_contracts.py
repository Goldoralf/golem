# SPDX-License-Identifier: GPL-3.0-or-later
"""Les COUTURES entre couches, tenues comme des contrats (docs/quality-automation.md, lot 6) : le vocabulaire de
commandes bridge -> REAPER, le catalogue contre sa doctrine (docs/blocks-doctrine.md) et ses recouvrements par OS,
chaque patch et preset d'usine qui se compile pour chacune de ses scènes avec un plan cohérent, la carte vivante
écrite par le moteur relue par le bridge, et des presets tirés au hasard qui se compilent sans casser un invariant.
Un champ renommé d'un seul côté doit faire tomber un test ici."""
import copy
import json
import os
from pathlib import Path
import random
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "library/catalog/effects.json").read_text(encoding="utf-8"))
EFFECTS = {e["type"]: e for e in CATALOG["effects"]}

# docs/blocks-doctrine.md §2.1 et §2.2 : les vocabulaires fermés
CATEGORIES = {"dynamics", "preamp", "drive", "lofi", "filter", "amp", "cab", "eq", "modulation", "delay", "reverb", "pitch",
              "utility", "drums", "keys", "pads", "hardware"}
ENGINES = {"plugin", "midi", "rs5k", "drumkit", "b3", "sfizz", "dexed", "virtual", "mode"}
MAP_MODES = {"raw", "norm", "pow"}
PARAM_TYPES = {"enum", "bool", "kitref", "midilist", "samplelist", "standardref"}
FOOT_MODES = {"transport", "sample", "drums"}


# ── 1. le vocabulaire de commandes : ce que le bridge émet, REAPER le comprend ─────────────────────────
def _emitted_actions():
    out = {}
    for f in sorted((ROOT / "bridge").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"write_command\(\s*\{(.{0,400}?)\}", src, re.S):
            a = re.search(r'"action":\s*"([a-z_]+)"', m.group(1))
            if a:
                out.setdefault(a.group(1), set()).add(f.name)
    return out


def _lua_vocabulary():
    words = set()
    for f in (ROOT / "reaper/Scripts").glob("*.lua"):
        words |= set(re.findall(r'"([a-z_]+)"', f.read_text(encoding="utf-8", errors="replace")))
    return words


def test_chaque_action_emise_par_le_bridge_est_connue_cote_reaper():
    emitted, lua = _emitted_actions(), _lua_vocabulary()
    assert len(emitted) >= 20, emitted                       # la sonde lit bien les appels
    unknown = {a: sorted(fs) for a, fs in emitted.items() if a not in lua}
    assert not unknown, f"actions écrites dans .command.json qu'aucun script REAPER ne nomme : {unknown}"


def test_le_veilleur_route_les_actions_du_moteur_vers_golem_rig():
    """golem_watch choisit golem_rig par sous-chaîne d'action : chaque action que golem_rig traite doit y être aiguillée,
    sinon elle tombe dans golem_apply (l'ancien modèle) et ne fait rien."""
    watch = (ROOT / "reaper/Scripts/golem_watch.lua").read_text(encoding="utf-8", errors="replace")
    rig = (ROOT / "reaper/Scripts/golem_rig.lua").read_text(encoding="utf-8", errors="replace")
    handled = set(re.findall(r'cmd\.action == "([a-z_]+)"', rig))
    assert {"rig_recall", "scene_apply", "stomp", "mixer_apply"} <= handled, handled
    routed = set(re.findall(r"find\('\"([a-z_]+)\"'", watch))
    # une action que le veilleur ne nomme pas doit lui arriver avec un `_route` qu'il nomme (routes_content :
    # {"action": "vst_list", "_route": "rig_recall"}) — depuis le bridge ou depuis une sonde de tools/
    carried = set()
    for f in list((ROOT / "bridge").glob("*.py")) + list((ROOT / "tools").glob("*.py")):
        src = f.read_text(encoding="utf-8", errors="replace")
        routes = set(re.findall(r'"_route":\s*"([a-z_]+)"', src))
        if routes & routed:                              # ce fichier émet vers golem_rig : ses actions y arrivent
            carried |= set(re.findall(r'"([a-z_]+)"', src)) & handled
    missing = handled - routed - carried
    assert not missing, f"golem_rig traite {sorted(missing)} mais rien ne les lui route (ni golem_watch, ni un `_route`)"


# ── 2. le catalogue contre sa doctrine ───────────────────────────────────────────────────────────────
def test_le_catalogue_respecte_la_doctrine_des_blocs():
    seen, bad = set(), []
    for e in CATALOG["effects"]:
        t = e.get("type")
        if not isinstance(t, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", t):
            bad.append(f"type illisible : {t!r}"); continue
        if t in seen:
            bad.append(f"{t}: type en double")
        seen.add(t)
        if e.get("category") not in CATEGORIES:
            bad.append(f"{t}: category {e.get('category')!r} hors doctrine")
        if e.get("engine", "plugin") not in ENGINES:
            bad.append(f"{t}: engine {e.get('engine')!r} hors doctrine")
        if e.get("foot_mode") and e["foot_mode"] not in FOOT_MODES:
            bad.append(f"{t}: foot_mode {e['foot_mode']!r}")
        if e.get("engine", "plugin") == "plugin" and not e.get("unsupported") and not e.get("plugin") and not e.get("virtual"):
            bad.append(f"{t}: bloc plugin sans `plugin`")
        ids = set()
        for p in e.get("params") or []:
            pid = p.get("id")
            if not pid:
                bad.append(f"{t}: param sans id : {p}"); continue
            if pid in ids:
                bad.append(f"{t}.{pid}: id de param en double")
            ids.add(pid)
            m = p.get("map")
            mode = m.get("mode") if isinstance(m, dict) else m
            if mode is not None and mode not in MAP_MODES:
                bad.append(f"{t}.{pid}: map {mode!r}")
            if p.get("type") is not None and p["type"] not in PARAM_TYPES:
                bad.append(f"{t}.{pid}: type {p['type']!r}")
            if p.get("type") in (None, "enum") and all(isinstance(p.get(k), (int, float)) for k in ("min", "max", "default")):
                lo, hi = sorted((p["min"], p["max"]))
                if not lo <= p["default"] <= hi:
                    bad.append(f"{t}.{pid}: default {p['default']} hors [{p['min']}, {p['max']}]")
            if p.get("type") == "enum" and not (p.get("options") or p.get("values") or p.get("dynamic")):
                bad.append(f"{t}.{pid}: enum sans options")
        for other in e.get("conflicts") or []:
            if other not in EFFECTS:
                bad.append(f"{t}: conflicts avec un type inconnu {other!r}")
    for role, cats in (CATALOG.get("role_categories") or {}).items():
        for c in ([] if role.startswith("_") else cats):            # les clés `_…` sont de la documentation
            if c not in CATEGORIES:
                bad.append(f"role_categories[{role}]: {c!r}")
    for role, types in (CATALOG.get("role_blocks") or {}).items():
        for t in ([] if role.startswith("_") else types):
            if t not in EFFECTS:
                bad.append(f"role_blocks[{role}]: type inconnu {t!r}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("overlay", ["effects-windows.json", "effects-macos.json"])
def test_un_recouvrement_par_os_ne_parle_que_de_blocs_et_de_params_qui_existent(overlay):
    data = json.loads((ROOT / "library/catalog" / overlay).read_text(encoding="utf-8"))
    table = data.get("effects", data)
    bad = []
    for t, ov in table.items():
        if t.startswith("_"):
            continue
        if t not in EFFECTS:
            bad.append(f"{t}: type absent de effects.json"); continue
        ids = {p["id"] for p in EFFECTS[t].get("params") or [] if p.get("id")}
        for key in ("params", "param_modes", "param_ranges"):
            for pid in (ov.get(key) or {}):
                if pid not in ids:
                    bad.append(f"{t}.{key}[{pid}]: param inconnu")
        if ov.get("param_mode") and ov["param_mode"] not in MAP_MODES:
            bad.append(f"{t}: param_mode {ov['param_mode']!r}")
        if ov.get("plugin") and not re.match(r"^(VST3?i?|CLAPi?|AUi?|JS|LV2i?): |^[A-Z]", str(ov["plugin"])):
            bad.append(f"{t}: nom de plugin suspect {ov['plugin']!r}")
    assert not bad, "\n".join(bad)


# ── 3. le contenu d'usine se compile, scène par scène ────────────────────────────────────────────────
def _compile(preset, scene, out_dir):
    from bridge import compile_rig, scene_bake, store
    work = copy.deepcopy(preset)
    store.ensure_volume(work)
    baked = scene_bake.to_paths_preset(work, scene, union=True)
    saved = compile_rig.OUT_DIR
    compile_rig.OUT_DIR = str(out_dir)
    try:
        path = compile_rig.compile_preset(baked)
    finally:
        compile_rig.OUT_DIR = saved
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    plan["_unmounted"] = baked.get("unmounted") or []      # les lanes que la carte ne prend pas : dites, jamais tues
    return plan


def _block_ids(preset):
    """Tous les blocs déclarés : la chaîne audio (pre/split/post) comme les blocs d'une lane MIDI (clavier, batterie)
    et les blocs de service de `config` — tout dict qui porte un `id` et un `type`, hors scènes et états."""
    ids = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("id"), str) and isinstance(x.get("type"), str):
                ids.add(x["id"])
            for k, v in x.items():
                if k not in ("scenes", "states", "deps", "needs"):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(preset)
    return ids


def _check_plan(plan, preset, where):
    """Les invariants d'un plan : noms de pistes uniques, sends et dossiers vers des pistes qui existent,
    aucun bloc inventé, un seul bloc par id."""
    problems = []
    names, seen_blocks = [], {}
    for path in plan.get("paths") or []:
        for tr in path.get("tracks") or []:
            names.append(tr["name"])
            for b in tr.get("blocks") or []:
                seen_blocks.setdefault(b["id"], []).append(tr["name"])
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        problems.append(f"pistes en double : {sorted(dup)}")
    for path in plan.get("paths") or []:
        for tr in path.get("tracks") or []:
            for dest in tr.get("sends_to") or []:
                if dest not in names:
                    problems.append(f"{tr['name']} envoie vers {dest!r} qui n'existe pas")
            if tr.get("folder_of") and tr["folder_of"] not in names:
                problems.append(f"{tr['name']} enfant de {tr['folder_of']!r} qui n'existe pas")
    known = _block_ids(preset) | {"volume-sys"}
    invented = {bid for bid in seen_blocks if bid not in known and not bid.startswith("__")}
    if invented and preset.get("lanes"):
        problems.append(f"blocs du plan absents du preset : {sorted(invented)}")
    twice = {bid: trs for bid, trs in seen_blocks.items() if len(trs) > 1}
    if twice:
        problems.append(f"un bloc posé deux fois : {twice}")
    # chaque lane est soit posée, soit dite « non montée » avec sa raison (docs/song-folders… non : scene_bake
    # _one_lane_per_input, « IN 2 is already played by… ») — jamais perdue en silence
    if preset.get("lanes"):
        declared = {lane["id"] for lane in preset["lanes"]}
        posed = {p.get("id") for p in plan.get("paths") or []}
        said = {u["id"] for u in plan.get("_unmounted") or []}
        lost = declared - posed - said
        if lost:
            problems.append(f"lanes disparues sans raison : {sorted(lost)}")
        if posed & said:
            problems.append(f"lanes à la fois posées et dites non montées : {sorted(posed & said)}")
    assert not problems, f"{where} :\n" + "\n".join(problems)


def _factory_files():
    return sorted((ROOT / "library/factory/patches").glob("*.json")) + sorted((ROOT / "library/factory/presets").glob("*.json"))


@pytest.mark.parametrize("file", _factory_files(), ids=lambda p: p.stem)
def test_chaque_patch_et_preset_d_usine_se_compile_pour_chacune_de_ses_scenes(file, tmp_path):
    preset = json.loads(file.read_text(encoding="utf-8"))
    scenes = [s.get("id") for s in preset.get("scenes") or [] if s.get("id")] or ["A"]
    for scene in scenes:
        plan = _compile(preset, scene, tmp_path)
        assert plan.get("id") == preset["id"]
        _check_plan(plan, preset, f"{file.name} scène {scene}")


# ── 4. la carte vivante écrite par le moteur, relue par le bridge ────────────────────────────────────
def test_la_carte_vivante_du_moteur_est_celle_que_le_bridge_lit(tmp_path, monkeypatch):
    pytest.importorskip("lupa")
    from tests.test_rig_lua import Lab, PATCH, BLOCK_IDS
    lab = Lab(tmp_path)
    lab.compile(PATCH)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    live = lab.livemap()
    assert set(live) >= {"preset", "blocks"}
    for bid, b in live["blocks"].items():
        assert isinstance(b.get("track"), int) and b["track"] >= 1, (bid, b)
        assert isinstance(b.get("fx"), int) and b["fx"] >= 0, (bid, b)
        assert isinstance(b.get("type"), str) and b["type"] in EFFECTS, (bid, b)
        for pname, pm in (b.get("params") or {}).items():
            assert set(pm) >= {"p", "pmin", "pmax"}, (bid, pname, pm)
    assert BLOCK_IDS <= set(live["blocks"])
    plugins = json.loads((lab.root / "presets/.rig-plugins.json").read_text(encoding="utf-8"))
    assert set(plugins) == {"types"}
    for t, v in plugins["types"].items():
        assert t in EFFECTS and isinstance(v.get("ok"), bool) and "at" in v, (t, v)
    # le lecteur du bridge : même fichier, même verdict (un REAPER « démarré avant » la carte, donc vivante)
    from bridge import monitors, recall
    monkeypatch.setattr(recall, "_LIVEMAP_STATE_PATH", str(lab.root / "presets/.livemap.json"))
    monkeypatch.setattr(monitors, "_reaper_pid", lambda: 4242)
    monkeypatch.setattr(monitors, "_process_started", lambda pid: 0.0)
    assert recall.rig_is_live("ci-engine") is True
    assert recall.rig_is_live("another-preset") is False


# ── 5. des presets tirés au hasard : les invariants tiennent ─────────────────────────────────────────
POOL = ["gate", "comp", "eq", "delay", "clean-boost", "chorus-js", "phaser-js", "flanger-js", "killswitch",
        "boost", "reverb-room", "reverb-plate", "delay-tape", "wah"]


def _random_preset(seed):
    rnd = random.Random(seed)
    lanes, scenes_blocks, n = [], {}, 0

    def blk(prefix):
        nonlocal n
        n += 1
        return {"id": f"{prefix}{n}", "type": rnd.choice(POOL)}
    nl = rnd.choice([1, 1, 2])
    for li in range(nl):
        role = ["guitar", "bass"][li]
        chain = {"pre": [blk("p") for _ in range(rnd.randint(0, 2))], "post": [blk("q") for _ in range(rnd.randint(0, 3))]}
        if rnd.random() < 0.6:
            chain["split"] = {"mode": rnd.choice(["merge", "merge", "fanout"]), "gain": rnd.choice([0, -3, -6]),
                              "branches": [{"id": f"br{li}a", "blocks": [blk("a") for _ in range(rnd.randint(1, 2))]},
                                           {"id": f"br{li}b", "blocks": [blk("b") for _ in range(rnd.randint(1, 2))]}]}
        lane = {"id": f"lane{li}", "role": role, "name": f"Lane {li}", "midi": False, "stereo": rnd.random() < 0.3, "chain": chain, "states": []}
        lanes.append(lane)
    ns = rnd.randint(1, 3)
    all_ids = _block_ids({"lanes": lanes})
    scenes = []
    for si in range(ns):
        sid = "ABC"[si]
        off = {bid: False for bid in all_ids if rnd.random() < 0.3}
        branches = {}
        for lane in lanes:
            sp = (lane["chain"].get("split") or {})
            for br in sp.get("branches") or []:
                if rnd.random() < 0.25:
                    branches[br["id"]] = {"mute": True}
            lane["states"].append({"id": f"st-{lane['id']}-{sid}", "name": sid, "blocks": off, "params": {}, "branches": branches})
        scenes.append({"id": sid, "name": sid, "blocks": off, "branches": branches,
                       "lanes": {lane["id"]: {"state": f"st-{lane['id']}-{sid}"} for lane in lanes}})
        scenes_blocks[sid] = off
    return {"id": f"rnd-{seed}", "name": f"Random {seed}", "role": "guitar", "kind": "patch", "patch_v": 2, "lanes_v": 2,
            "bpm": rnd.choice([80, 120, 160]), "lanes": lanes, "scenes": scenes, "config": {"gen": {"out": "1-2", "blocks": []}}}, scenes_blocks


@pytest.mark.parametrize("seed", range(24))
def test_un_preset_tire_au_hasard_se_compile_et_respecte_les_scenes(seed, tmp_path):
    preset, scenes_blocks = _random_preset(seed)
    for sid, off in scenes_blocks.items():
        plan = _compile(preset, sid, tmp_path)
        _check_plan(plan, preset, f"seed {seed} scène {sid}")
        posed_lanes = {p.get("id") for p in plan["paths"]}
        in_plan = {b["id"]: b for p in plan["paths"] for tr in p["tracks"] for b in tr.get("blocks") or []}
        for lane in preset["lanes"]:
            ch = lane["chain"]
            ids = {b["id"] for b in ch["pre"]} | {b["id"] for br in (ch.get("split") or {}).get("branches", []) for b in br["blocks"]} | {b["id"] for b in ch["post"]}
            if lane["id"] not in posed_lanes:                # non montée (dite) : rien d'elle dans le plan
                assert not (ids & set(in_plan)), (seed, sid, lane["id"], "lane non montée mais des blocs posés")
                continue
            expected = ids
            if (ch.get("split") or {}).get("mode") == "fanout":
                # FAN-OUT : chaque branche va à SA sortie, il n'y a pas de post (scene_bake) — les blocs post n'existent pas
                post = {b["id"] for b in ch["post"]}
                assert not (post & set(in_plan)), (seed, sid, "post après un fanout, pourtant posé :", post & set(in_plan))
                expected = ids - post
            missing = expected - set(in_plan)
            assert not missing, (seed, sid, lane["id"], "blocs de la lane absents du plan :", missing)
            wanted_off = {bid for bid, on in off.items() if on is False and bid in expected}
            not_bypassed = {bid for bid in wanted_off if not in_plan[bid].get("bypass")}
            assert not not_bypassed, (seed, sid, "blocs coupés par la scène mais pas contournés dans le plan :", not_bypassed)
