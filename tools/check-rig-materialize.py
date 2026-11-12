#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chaque patch d'usine MATÉRIALISÉ dans un vrai REAPER, sans rack ni humain (docs/quality-automation.md, lot 3a).

Ce que la sonde fait, de bout en bout :
  1. un DÉPÔT JETABLE : `git worktree` de HEAD dans --work (le vrai dépôt n'est jamais touché : ni ses presets/,
     ni son .command.json — un rack qui tourne à côté ne voit rien) ; le contenu d'usine y est semé ;
     les modèles et IR locaux (assets/models, assets/irs, library/tones — jamais dans git) y sont COPIÉS
     depuis le dépôt courant, ou téléchargés par le bridge (--fetch) ;
  2. un REAPER ISOLÉ : son propre dossier de ressources (-cfgfile), les scripts et JSFX de golem copiés comme le
     fait le lanceur desktop, audio factice (aucune carte son), ports OSC à lui ;
  3. un BRIDGE JETABLE qui parle à ce REAPER et à ce dépôt (ports HTTP et OSC libres, runtime temporaire) ;
  4. pour chaque patch d'usine dont tous les blocs sont prêts : un rappel, puis ce que le moteur a RÉELLEMENT
     posé — `.rig-check.json` (les fichiers que chaque plugin a chargés, lus sur le plugin), `.livemap.json`
     (les blocs posés, piste et slot FX) comparé aux blocs du patch, `.rig-plugins.json` (chaque type de bloc a
     trouvé son plugin), `rig_error` du bridge ; puis un changement de scène si le patch en a plusieurs.

Un patch dont un bloc manque sur cette machine (plugin absent, modèle à télécharger) est SAUTÉ et dit pourquoi :
la sonde juge le moteur, pas l'inventaire. Rapport JSON (--json), code 1 si un patch rappelé échoue ou si aucun
n'a pu l'être. ~10 s par patch. Rien ne joue : audio factice, aucune prise, aucun fichier du dépôt courant écrit.

    python tools/check-rig-materialize.py                      # REAPER trouvé comme le lanceur (REAPER_BIN sinon)
    python tools/check-rig-materialize.py --only kite --keep  # un patch, et garder --work pour lire les journaux
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
# le contenu local du dépôt courant (jamais dans git) dont un rappel a besoin : modèles, IR, captures téléchargées
LOCAL_CONTENT = ("assets/models", "assets/irs", "assets/samples", "library/tones", "library/catalog/tones-index.json",
                 "assets/.cache/capture-modules", "library/patches", "presets")   # patches et presets de l'utilisateur aussi (--all)
CACHE_FILES = ("*.nam", "*.wav", "*.gcap", "*.json")          # les captures à plat dans assets/.cache (pas les bancs)
# ce que REAPER met des minutes à refaire sur un dossier vierge, et que le REAPER de la machine a déjà :
# l'inventaire des plugins (150 VST3 ici, dont des suites d'ampli commerciales qui mettent des secondes chacun) et la licence
REAPER_WARM = ("reaper-vstplugins64.ini", "reaper-vstplugins.ini", "reaper-vstplugins_arm64.ini", "reaper-vstshells64.ini",
               "reaper-clap-win64.ini", "reaper-clap-linux-x86_64.ini", "reaper-clap-macos-arm64.ini",
               "reaper-clap-macos-x86_64.ini", "reaper-auplugins64.ini", "reaper-license.rk")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(base, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(base + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(req, timeout=timeout) as r:
        return json.load(r)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def kill(proc):
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=15)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait()


# ── le dépôt jetable ─────────────────────────────────────────────────────────────────────────────────
def working_tree_commit():
    """Un commit FANTÔME de l'arbre de travail, sans toucher ni la branche ni l'index (comme tools/check-ui.py) :
    vérifier un correctif dans le vrai REAPER AVANT de le committer."""
    fd, idx = tempfile.mkstemp(prefix="golem-rig-index-")
    os.close(fd); os.unlink(idx)
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    g = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], env=env, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    try:
        g("read-tree", "HEAD")
        g("add", "-A", ".")
        return g("commit-tree", g("write-tree"), "-p", "HEAD", "-m", "golem rig check: working tree")
    finally:
        if os.path.exists(idx):
            os.unlink(idx)


def make_root(work, log, content_from=None, rev="HEAD"):
    """Le dépôt jetable, et le contenu local copié depuis `content_from` (défaut : ce dépôt) — sur un runner qui
    travaille dans son propre clone, c'est le dossier du golem de la machine (GOLEM_RACK_ROOT) qui a les modèles."""
    root = work / "root"
    # un run précédent gardé (--keep) puis effacé par le runner laisse un worktree « missing but already registered »
    subprocess.run(["git", "-C", str(ROOT), "worktree", "prune"], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "-f", "-q", str(root), rev], check=True)
    log(f"worktree: {root}" + ("" if rev == "HEAD" else f" (working tree, {rev[:10]})"))
    source = Path(content_from).resolve() if content_from else ROOT
    if source != ROOT:
        log(f"local content from: {source}")
    for rel in LOCAL_CONTENT:
        src, dst = source / rel, root / rel
        if src.is_dir():
            # jamais les fichiers cachés : presets/.command.json, .sandbox.json… sont l'état VIVANT du rack à côté
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=lambda d, names: [n for n in names if n.startswith(".")])
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
    cache = source / "assets" / ".cache"
    if cache.is_dir():
        (root / "assets" / ".cache").mkdir(parents=True, exist_ok=True)
        for pat in CACHE_FILES:
            for f in cache.glob(pat):
                if f.is_file():
                    shutil.copy2(f, root / "assets" / ".cache" / f.name)
    write_bench_card(root)
    return root


def write_bench_card(root):
    """Une carte de banc qui a une entrée de CHAQUE rôle audio : sans elle, la carte « unknown » n'avait que des
    guitares, et chaque patch basse ou voix sortait « cannot be mounted » (campagne 2026-10-25) — la sonde juge le
    moteur sur tous les patches, pas la carte de la machine. Les claviers et la batterie passent par l'USB."""
    cfg = root / "config"
    (cfg / "inputmaps").mkdir(parents=True, exist_ok=True)
    (cfg / "io.json").write_text(json.dumps({"device": "golem-bench", "samplerate": 48000, "outputs_count": 2}) + "\n",
                                 encoding="utf-8")
    roles = ("guitar", "bass", "voice", "guitar")
    (cfg / "inputmaps" / "golem-bench.json").write_text(json.dumps({
        "card": "golem-bench", "inputs": [{"ch": str(i + 1), "role": r} for i, r in enumerate(roles)],
        "outputs": [{"ch": "1-2", "role": "monitors"}]}) + "\n", encoding="utf-8")


def drop_root(root):
    subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(root)],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(ROOT), "worktree", "prune"], check=False, stdout=subprocess.DEVNULL)


FIXTURE_ID = "ci-engine"


def write_fixture(root):
    """Un patch de banc qui ne demande AUCUN téléchargement ni plugin tiers : effets intégrés à REAPER (ReaGate,
    ReaComp, ReaEQ, ReaDelay), JSFX du stock (phaser, chorus) et de golem (killswitch), deux branches, trois
    scènes. Il exerce le moteur — pistes, split/merge, armement, scènes, stomps — là où les patches d'usine
    sautent faute de modèles (un runner vierge)."""
    lane = "guitar-ci"
    chain = {"pre": [{"id": "gate", "type": "gate"}],
             "split": {"mode": "merge", "gain": -3, "branches": [
                 {"id": "lane-a", "blocks": [{"id": "boost", "type": "clean-boost"}, {"id": "eq", "type": "eq"}]},
                 {"id": "lane-b", "blocks": [{"id": "phaser", "type": "phaser-js", "foot": 6}, {"id": "comp", "type": "comp"}]}]},
             "post": [{"id": "chorus", "type": "chorus-js", "foot": 7}, {"id": "dly", "type": "delay", "foot": 8},
                      {"id": "kill", "type": "killswitch", "foot": 9}]}
    states = [("A", "Both", {"chorus": False}, {}),
              ("B", "Branch A only", {"chorus": True, "dly": True}, {"lane-b": {"mute": True}}),
              ("C", "Branch B only", {"phaser": True}, {"lane-a": {"mute": True}})]
    patch = {"id": FIXTURE_ID, "name": "CI engine check", "role": "guitar", "tags": ["ci"], "kind": "patch",
             "patch_v": 2, "lanes_v": 2, "bpm": 120, "origin": "ci",
             "lanes": [{"id": lane, "role": "guitar", "name": "CI engine check", "midi": False, "stereo": False,
                        "chain": chain,
                        "states": [{"id": f"st-{lane}-{s}", "name": n, "blocks": b, "params": {}, "branches": br}
                                   for s, n, b, br in states]}],
             "scenes": [{"id": s, "name": n, "blocks": b, "branches": br, "lanes": {lane: {"state": f"st-{lane}-{s}"}}}
                        for s, n, b, br in states],
             "config": {"gen": {"out": "1-2", "blocks": []}}}
    dest = root / "library" / "patches" / f"{FIXTURE_ID}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(patch, indent=1, ensure_ascii=False), encoding="utf-8")
    return dest


ENGINE_FIXTURE_ID = "ci-golem-engine"


def write_engine_fixture(root):
    """Le patch de banc du Golem Engine (docs/ardour-plan.md §7c) : seulement des blocs de sa table
    (library/catalog/effects-golem-engine.json) — une tête NAM et un cab IR du contenu d'usine (Fuzz Wall), un Tape
    Delay au pied — deux scènes. Ce que REAPER fait avec `ci-engine`, ce moteur le fait avec celui-ci."""
    lane = "guitar-ge"
    chain = {"pre": [{"id": "amp", "type": "amp-nam", "label": "Fender Twin Reverb", "ref": "246", "model": "418200"},
                     {"id": "cab", "type": "cab", "label": "Palmer 2x12 G12M-65 Creamback", "ref": "5004", "model": "67597"}],
             "post": [{"id": "dly", "type": "delay-tape", "foot": 8}]}
    states = [("A", "Dry", {"dly": False}, {}), ("B", "Delay, hotter amp", {"dly": True}, {"amp": {"input": 4}})]
    patch = {"id": ENGINE_FIXTURE_ID, "name": "CI Golem Engine check", "role": "guitar", "tags": ["ci"], "kind": "patch",
             "patch_v": 2, "lanes_v": 2, "bpm": 120, "origin": "ci",
             "lanes": [{"id": lane, "role": "guitar", "name": "CI Golem Engine check", "midi": False, "stereo": False,
                        "chain": chain,
                        "states": [{"id": f"st-{lane}-{s}", "name": n, "blocks": b, "params": pr, "branches": {}}
                                   for s, n, b, pr in states]}],
             "scenes": [{"id": s, "name": n, "blocks": b, "params": pr, "branches": {}, "lanes": {lane: {"state": f"st-{lane}-{s}"}}}
                        for s, n, b, pr in states],
             "config": {"gen": {"out": "1-2", "blocks": []}}}
    dest = root / "library" / "patches" / f"{ENGINE_FIXTURE_ID}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(patch, indent=1, ensure_ascii=False), encoding="utf-8")
    return dest


# ── la prise de standard (docs/compo.md §11) : le départ armé, MESURÉ ──────────────────────────────────────────────
STD_SLUG = "blues-for-alice"           # 12 mesures en 4/4 : à 240, une prise d'un tour dure 13 s
STD_PATCH = "ci-standard-take"
STD_PERSON = "bench"


def write_standard_bench(root, source):
    """Ce que la prise demande au banc : la grille (le corpus n'est pas dans git), une personne sur l'entrée 1 de la carte
    de banc, un patch avec SA lane guitare sur cette entrée, et le Rec en multipiste AVEC le mix — `Mix.wav` reçoit la
    sortie de chaque piste du rack sauf le Click, donc celle du Standard : la mesure se fait sur le vrai fichier de la
    prise. Sans transcription (rien à transcrire, et elle occuperait le banc)."""
    corpus = source / "library" / "standards" / "jazz-standards.json"
    if not corpus.is_file():
        raise SystemExit(f"--standard-take needs the chart corpus: {corpus} is missing")
    # le rack ne lit que les grilles REÇUES (library/standards/synced/, standards._load_raw) : on en pose une comme
    # tools/seed-standards.py, marquée `seeded`
    sys.path.insert(0, str(ROOT))
    from bridge.standards import slugify
    raw = next((r for r in json.loads(corpus.read_text(encoding="utf-8")) if slugify(r.get("Title") or "") == STD_SLUG), None)
    if not raw:
        raise SystemExit(f"--standard-take: {STD_SLUG} is not in {corpus}")
    raw["_golem"] = {"slug": STD_SLUG, "synced_at": None, "source": "check-rig-materialize --standard-take", "seeded": True}
    dst = root / "library" / "standards" / "synced" / f"{STD_SLUG}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    write_take_bench(root)


def write_take_bench(root):
    """Une personne sur l'entrée 1, le Rec en multipiste avec le mix, sans transcription, et le patch de la prise."""
    cfg = root / "config"
    im = cfg / "inputmaps" / "golem-bench.json"
    m = json.loads(im.read_text(encoding="utf-8"))
    m["inputs"][0]["person"] = STD_PERSON
    im.write_text(json.dumps(m) + "\n", encoding="utf-8")
    (cfg / "recorder.json").write_text(json.dumps({"mode": "tracks", "in1": True, "in2": False, "in3": False, "in4": False,
                                                   "usb": False, "mix": True}) + "\n", encoding="utf-8")
    (cfg / "compo.json").write_text(json.dumps({"transcribe": False}) + "\n", encoding="utf-8")
    lane = {"id": "guitar-1", "role": "guitar", "name": "Guitar 1", "in_role": "guitar", "in_nth": 1, "midi": False,
            "stereo": False, "chain": {"pre": [{"id": "gate", "type": "gate"}], "split": None, "post": []}}
    patch = {"id": STD_PATCH, "name": "CI standard take", "role": "guitar", "tags": ["ci"], "kind": "patch", "patch_v": 2,
             "lanes_v": 2, "bpm": 120, "origin": "ci", "lanes": [lane],
             "scenes": [{"id": "A", "name": "A", "blocks": {}, "lanes": {}}], "config": {"gen": {"out": "1-2", "blocks": []}}}
    dest = root / "library" / "patches" / f"{STD_PATCH}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(patch, indent=1), encoding="utf-8")


STD_BPM = 240
STD_DOWN = 1.0                         # le 1 de la grille : une mesure de décompte à 240


def _first_sound(x, sr, after, before):
    """Le premier échantillon non nul entre `after` et `before` (s) — exact, pour une attaque qui sort du SILENCE."""
    import numpy as np
    i0 = int(after * sr)
    nz = np.flatnonzero(np.abs(x[i0:int(before * sr)]) > 1e-6)
    return int(i0 + nz[0]) if len(nz) else None


def _run_take(base, root, target, timeout, stop_after=None):
    """La cible golem.fm rejouée, un tap, et la prise qu'il a écrite : (dossier, take.json, problème). `stop_after` (s) :
    un second tap l'arrête (une prise en boucle ne s'arrête pas seule avant LOOP_MAX_S)."""
    r = http(base, "/api/compo/target", {"person": STD_PERSON, "target": target})
    if not r.get("ok"):
        return None, None, f"arming refused: {r.get('why')}"
    rec = root / "recordings"
    before = {d.name for d in rec.glob("perf-*")} if rec.is_dir() else set()
    rep = http(base, "/api/compo/tap", {"person": STD_PERSON})
    if rep.get("refused"):
        return None, None, f"tap refused: {rep['refused']}"
    if stop_after:
        time.sleep(stop_after)
        http(base, "/api/compo/tap", {"person": STD_PERSON})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new = [d for d in rec.glob("perf-*") if d.name not in before and (d / "take.json").is_file()] if rec.is_dir() else []
        if new:
            return new[0], json.loads((new[0] / "take.json").read_text(encoding="utf-8")), None
        last = (http(base, "/api/state").get("compo") or {}).get("last") or {}
        if last.get("refused"):
            return None, None, f"start refused: {last['refused']}"
        time.sleep(0.5)
    return None, None, f"no take after {timeout} s"


def _mix(take):
    f = next((f for f in take.glob("*.wav") if f.name.lower().startswith("mix")), None)
    return read_wav(f) if f else (None, None)


def riff_reference_round(base, root, timeout):
    """LE TÉMOIN : une prise de Riff armée, dont le clic est un FICHIER posé à 0 sur la timeline (riffclick) — le
    départ que golem.fm a déjà validé. Chaque blip sort du silence : son premier échantillon dit, exactement, où
    « juste » tombe dans un fichier de prise de ce banc. Un décalage commun vient de l'enregistrement, pas de la grille."""
    target = {"id": "rf:ci", "mode": "append", "bpm": STD_BPM, "sig": {"num": 4, "den": 4}, "count_in": 1, "bars": 2,
              "passes": 1, "click": "always"}
    take, man, why = _run_take(base, root, target, timeout)
    if why:
        return {"issues": [f"riff reference: {why}"]}
    x, sr = _mix(take)
    if x is None:
        return {"take": take.name, "issues": ["riff reference: no Mix.wav"]}
    blip = _first_sound(x, sr, STD_DOWN - 0.1, STD_DOWN + 0.05)
    if blip is None:
        return {"take": take.name, "issues": ["riff reference: click not found in Mix.wav"]}
    return {"take": take.name, "blip": blip, "offset_ms": round((blip / sr - STD_DOWN) * 1000, 3),
            "sound_at_0": bool(abs(x[:240]).max() > 1e-6), "issues": []}


def standard_take_round(base, root, n, timeout, ref, parts):
    """Une prise de standard par le vrai chemin (cible golem.fm rejouée, tap, prise, take.json), comparée au TÉMOIN
    (`ref`, le clic-fichier du Riff) ; budget 1 ms.
      · `bass` : le décompte sonne sur la lane basse — son tick 0 doit sonner, comme le blip 0 du Riff ;
      · `drums` : le décompte se tait (sa lane est coupée), le 1 de la grille sort du SILENCE — son premier
        échantillon se compare exactement à celui du blip du Riff ;
      · `loop` : la même, EN BOUCLE (`choruses: 0`), arrêtée au tap après un tour et demi — le tour 2 reprend APRÈS le
        décompte : rejoué, il ferait une mesure de silence (la batterie seule ne décompte pas)."""
    loop = parts == "loop"
    target = {"id": f"st:ci{n}", "mode": "replace", "title": "CI", "kind": "standard-take", "standard": STD_SLUG,
              "bpm": STD_BPM, "count_in": 1, "choruses": 0 if loop else 1, "role": "guitar",
              "parts": {"keys": False, "bass": parts == "bass", "drums": parts != "bass", "guitar": False},
              "click": "count-in"}
    chorus = 12 * 4 * 60.0 / STD_BPM
    take, man, why = _run_take(base, root, target, timeout, stop_after=(STD_DOWN + 1.5 * chorus) if loop else None)
    if why:
        return {"parts": parts, "issues": [why]}
    issues = []
    for k, want in (("kind", "standard-take"), ("tempo_source", "standard"), ("downbeat_s", STD_DOWN)):
        if man.get(k) != want:
            issues.append(f"take.json {k} = {man.get(k)!r}, not {want!r}")
    st = man.get("standard") or {}
    if not (isinstance(st.get("bars"), list) and len(st["bars"]) == 12 and st.get("beats") == 4):
        issues.append(f"take.json standard.bars/beats: {str(st.get('bars'))[:80]} / {st.get('beats')}")
    if (man.get("target") or {}).get("lane") != "guitar-1":
        issues.append(f"take.json target.lane = {(man.get('target') or {}).get('lane')!r}")
    x, sr = _mix(take)
    if x is None:
        return {"parts": parts, "take": take.name, "issues": issues + ["no Mix.wav"]}
    out = {"parts": parts, "take": take.name, "issues": issues}
    sj = read_json(root / "presets" / ".standard.json") or {}
    out["start"] = {"t0_s": sj.get("t0"), "first": sj.get("first")}   # témoins du JSFX : où le transport l'a pris
    if parts == "bass":
        out["sound_at_0"] = bool(abs(x[:240]).max() > 1e-6)
        if ref.get("sound_at_0") and not out["sound_at_0"]:
            issues.append("the grid's tick 0 is silent (the riff's click sounds there)")
    if loop:
        import numpy as np
        # le 1 du tour 2 tombe à `downbeat_s + un tour` (dans le fichier, au décalage d'enregistrement près, < 20 ms)
        seg = x[int((STD_DOWN + chorus + 0.05) * sr):int((STD_DOWN + chorus + 0.95) * sr)]
        out["chorus2_rms"] = round(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0, 5)
        if out["chorus2_rms"] < 1e-4:
            issues.append("a bar of silence at the top of chorus 2: the loop replayed the count-in")
        if man.get("passes") != 0:
            issues.append(f"take.json passes = {man.get('passes')!r}, not 0 (loop)")
    if parts != "bass":
        first = _first_sound(x, sr, STD_DOWN - 0.2, STD_DOWN + 0.1)
        if first is None:
            issues.append("the grid's first beat not found in Mix.wav")
        else:
            out["vs_riff_samples"] = first - ref["blip"]
            out["vs_riff_ms"] = [round(out["vs_riff_samples"] / sr * 1000, 3)]
    issues += [f"{e} ms from the riff's click" for e in out.get("vs_riff_ms") or [] if abs(e) > 1.0]
    return out


# ── le bed d'une prise armée (docs/compo.md §12 ter) : les autres couches, à 0 comme le click, MESURÉ ─────────────────────
BED_FILE = Path("/tmp/golem-compo-bed-test/bed-96bpm.flac")   # le bed d'essai de golem.fm (backend/tools/make_test_bed.py)
BED_BPM, BED_DOWN = 96, 2.5            # 96 bpm 4/4, une mesure de décompte : le « 1 » de la section à 2,5 s
BED_LAST_BLIP = 1.875                  # le dernier blip du décompte (click « count-in » : il se tait ensuite)


def bed_meta(path):
    """{sha256, bytes, length_s, first} du bed d'essai : son JSON s'il est à côté, sinon lu dans le fichier."""
    import hashlib
    blob = path.read_bytes()
    meta = read_json(path.with_suffix(".json"), {}) or {}
    sys.path.insert(0, str(ROOT))
    from bridge.compo_bed import streaminfo
    si = streaminfo(str(path))
    if not si:
        raise SystemExit(f"--compo-bed: {path} is not a FLAC")
    return {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob), "length_s": si[3] / si[0],
            "first": int(meta.get("first_downbeat_sample") or round(BED_DOWN * si[0]))}


def seed_bed(root, path, meta):
    """Le bed dans le cache du banc (presets/.cache/beds/<sha>.flac) : le banc n'a pas de golem.fm, le rack le sert
    par sha comme au renvoi d'un armement — le téléchargement, 404 et 304 compris, est éprouvé par tests/test_compo_bed.py."""
    d = root / "presets" / ".cache" / "beds"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, d / f"{meta['sha256']}.flac")
    return d


def _peak_db(x, sr, a, b):
    import numpy as np
    seg = x[int(a * sr):int(b * sr)]
    return round(20 * float(np.log10(max(float(np.abs(seg).max()) if len(seg) else 0.0, 1e-12))), 2)


def compo_bed_round(base, root, n, meta, gain=-6.0, with_bed=True, sha=None):
    """Une prise de riff armée AVEC son bed, par le vrai chemin. Le critère de P6 : le premier échantillon du bed et le
    « 1 » de la prise tombent à moins de 1 ms l'un de l'autre DANS le Mix.wav. Le « 1 » se lit sur le dernier blip du
    décompte (il sort du silence, à 1,875 s) : l'écart d'enregistrement commun s'annule."""
    tid = f"rf:ci{n}|ly:2|b:1-4"
    target = {"id": tid, "mode": "append", "bpm": BED_BPM, "sig": {"num": 4, "den": 4}, "count_in": 1, "bars": 4,
              "passes": 1, "click": "count-in"}
    if with_bed:
        target["bed"] = {"sha256": sha or meta["sha256"], "bytes": meta["bytes"], "length_s": meta["length_s"],
                         "gain_db": gain, "format": "flac", "offset_s": 0.0,
                         "url": f"/api/ext/compo/beds/bench/{sha or meta['sha256']}.flac"}
    out = {"gain_db": gain if with_bed else None, "bed": with_bed, "issues": []}
    take, man, why = _run_take(base, root, target, 60)
    if why:
        out["why"] = why
        if not sha:
            out["issues"].append(why)
        return out
    issues = out["issues"]
    out["take"] = take.name
    want_bed = {"sha256": meta["sha256"]} if with_bed else None
    if man.get("bed") != want_bed:
        issues.append(f"take.json bed = {man.get('bed')!r}, not {want_bed!r}")
    if (man.get("target") or {}).get("id") != tid:
        issues.append(f"take.json target.id = {(man.get('target') or {}).get('id')!r}, not {tid!r}")
    if man.get("downbeat_s") != BED_DOWN:
        issues.append(f"take.json downbeat_s = {man.get('downbeat_s')!r}, not {BED_DOWN}")
    x, sr = _mix(take)
    if x is None:
        return {**out, "issues": issues + ["no Mix.wav"]}
    blip = _first_sound(x, sr, BED_LAST_BLIP - 0.1, BED_LAST_BLIP + 0.03)
    out["peak_db"] = _peak_db(x, sr, BED_DOWN, BED_DOWN + 9.5)
    if blip is None:
        issues.append("the count-in click not found in Mix.wav")
        return out
    if not with_bed:
        if out["peak_db"] > -80:
            issues.append(f"sound after the count-in without a bed ({out['peak_db']} dB)")
        return out
    first = _first_sound(x, sr, BED_DOWN - 0.3, BED_DOWN + 0.05)
    if first is None:
        issues.append("the bed's first downbeat not found in Mix.wav")
        return out
    # le blip sort de sin(0) = 0 : son premier échantillon non nul est le SUIVANT de son départ
    want = round((BED_DOWN - BED_LAST_BLIP) * sr) + (meta["first"] - round(BED_DOWN * sr)) - 1
    out["vs_click_samples"] = (first - blip) - want
    out["vs_click_ms"] = round(out["vs_click_samples"] / sr * 1000, 3)
    if abs(out["vs_click_ms"]) > 1.0:
        issues.append(f"the bed is {out['vs_click_ms']} ms from the take's downbeat")
    if out["peak_db"] >= 0.0:
        issues.append(f"the Mix clips at gain {gain} dB ({out['peak_db']} dBFS)")
    return out


def compo_bed_rounds(base, root, n, meta, log):
    """N prises alignées, puis le gain (−60 / 0), un bed qui ne vaut pas son sha, et la prise sans bed (le témoin).
    Après chaque prise : la Backing est rendue (plus de bed)."""
    out = []

    def note(r, label):
        r["label"] = label
        bk = (http(base, "/api/state").get("backing") or {})
        if bk.get("slug") == "riff-take" and not r.get("why"):
            time.sleep(3)
            bk = (http(base, "/api/state").get("backing") or {})
            if bk.get("slug") == "riff-take":
                r["issues"].append("the take's backing (click + bed) still loaded after the take")
        out.append(r)
        log(("  ok     " if not r["issues"] else "  FAIL   ") + f"{label}: "
            + ", ".join(f"{k} {r[k]}" for k in ("vs_click_ms", "vs_click_samples", "peak_db", "why") if k in r)
            + "".join("\n           " + x for x in r["issues"]))
    for k in range(n):
        time.sleep(3)
        note(compo_bed_round(base, root, k, meta), f"bed take {k + 1} (gain -6)")
    for g in (-60.0, 0.0):
        time.sleep(3)
        note(compo_bed_round(base, root, 90 + int(-g), meta, gain=g), f"bed take (gain {g:+.0f})")
    peaks = {r["gain_db"]: r.get("peak_db") for r in out if r.get("peak_db") is not None}
    if None not in (peaks.get(-6.0), peaks.get(-60.0), peaks.get(0.0)):
        if abs((peaks[0.0] - peaks[-6.0]) - 6.0) > 1.0 or peaks[-60.0] - peaks[-6.0] > -50.0:
            out[-1]["issues"].append(f"gain does not follow gain_db: peaks {peaks}")
    time.sleep(3)
    bad = "f" * 64
    shutil.copy2(root / "presets" / ".cache" / "beds" / f"{meta['sha256']}.flac", root / "presets" / ".cache" / "beds" / f"{bad}.flac")
    r = compo_bed_round(base, root, 99, meta, sha=bad)
    if "bed not available" not in (r.get("why") or ""):
        r["issues"].append(f"a bed whose bytes are not its sha was not refused ({r.get('why') or 'the take ran'})")
    if (root / "presets" / ".cache" / "beds" / f"{bad}.flac").exists():
        r["issues"].append("the bad file stayed in the cache")
    note(r, "bed with a wrong sha")
    time.sleep(3)
    note(compo_bed_round(base, root, 98, meta, with_bed=False), "take without a bed")
    return out


def py_in_root(root, env, code, timeout=600):
    return subprocess.run([sys.executable, "-c", code], cwd=root, env=env, check=True, timeout=timeout,
                          capture_output=True, text=True)


# ── REAPER isolé ─────────────────────────────────────────────────────────────────────────────────────
def prepare_reaper(root, resource, env, osc_send, osc_recv, log, reaper_bin, cold=False):
    """Les ressources de golem dans un dossier REAPER vierge, par le même code que le lanceur desktop."""
    resource.mkdir(parents=True, exist_ok=True)
    (resource / "reaper.ini").write_text("[reaper]\nnolastproject=1\nopenallrecent=0\nsplashscreen=0\n",
                                         encoding="ascii")
    if not cold:
        # le REAPER de la machine (pas l'override de l'environnement : c'est le vrai dossier qu'on veut)
        saved = {k: os.environ.pop(k) for k in ("GOLEM_REAPER_RESOURCE_DIR",) if k in os.environ}
        try:
            sys.path.insert(0, str(ROOT))
            from bridge.reaper_license import resource_dir as real_resource_dir
            real = Path(real_resource_dir())
        finally:
            os.environ.update(saved)
        warmed = [n for n in REAPER_WARM if (real / n).is_file() and not shutil.copy2(real / n, resource / n) is None]
        if warmed:
            log(f"warm start from {real}: " + ", ".join(warmed))
    # les JSFX du STOCK de REAPER (guitar/phaser, sstillwell/chorus_stereo, Volume Adjustment…) vivent dans le
    # dossier de ressources de l'installation, pas dans le binaire : un dossier -cfgfile vierge ne les a pas, et
    # les blocs chorus-js/phaser-js/clean-boost sortaient « plugin not installed » sur le runner (2026-10-19).
    # On les recopie depuis le REAPER de la machine, ou depuis l'installation portable (à côté du binaire).
    stock = None
    for cand in ([Path(os.environ.get("APPDATA", "")) / "REAPER"] if sys.platform == "win32" else []) + \
                ([Path.home() / "Library/Application Support/REAPER"] if sys.platform == "darwin" else []) + \
                ([Path.home() / ".config/REAPER"] if sys.platform == "linux" else []) + [Path(reaper_bin).parent]:
        if (cand / "Effects").is_dir() and any((cand / "Effects").iterdir()):
            stock = cand / "Effects"; break
    if stock:
        n = 0
        for src in stock.rglob("*"):
            rel = src.relative_to(stock)
            if src.is_file() and rel.parts[0] != "golem" and not (resource / "Effects" / rel).exists():
                (resource / "Effects" / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, resource / "Effects" / rel); n += 1
        log(f"stock JSFX: {n} files from {stock}")
    else:
        log("stock JSFX: none found — chorus-js, phaser-js and clean-boost blocks will be unavailable")
    py_in_root(root, env, "from pathlib import Path\n"
                          "from provision.desktop import copy_resources, configure_ini\n"
                          f"copy_resources(Path({str(resource)!r}))\n"
                          f"configure_ini(Path({str(resource)!r}) / 'reaper.ini', dummy_audio=True)\n")
    ini = resource / "reaper.ini"
    text = ini.read_text(encoding="latin-1")
    # la surface OSC écrite par configure_ini parle sur 8000/9000 : ici, les ports de CE bridge
    text = re.sub(r'(csurf_\d+=OSC "golem" 3 )\d+( "127\.0\.0\.1" )\d+', rf"\g<1>{osc_send}\g<2>{osc_recv}", text)
    if sys.platform == "linux":
        # l'audio factice de configure_ini est celui de Windows ([audioconfig] mode=4) : sous Linux, REAPER le lit dans
        # [reaper] — `linux_audio_mode=2` = Dummy Audio (mesuré sur 7.82 : 0 et 1 n'y ont rien démarré, 3 =
        # PulseAudio). Sans lui, le banc tournait SANS moteur audio : aucun @block, ce que seule une prise révèle.
        text = re.sub(r"(?m)^linux_audio_(mode|srate)=.*\n?", "", text)
        text = re.sub(r"(?m)^\[reaper\]\s*$", "[reaper]\nlinux_audio_mode=2\nlinux_audio_srate=48000", text, count=1)
    ini.write_text(text, encoding="latin-1")
    pointer = (resource / "golem-root.txt").read_text(encoding="utf-8").strip()
    if Path(pointer).resolve() != root.resolve():
        raise RuntimeError(f"golem-root.txt points at {pointer}, expected {root}")
    log(f"REAPER resources: {resource} (OSC listen {osc_send}, send {osc_recv})")


def reaper_binary():
    if os.environ.get("REAPER_BIN"):
        return Path(os.environ["REAPER_BIN"])
    if sys.platform == "linux":
        # le lanceur desktop ne connaît pas Linux (le rack lance REAPER par provision/) : le PATH, puis les
        # installations habituelles — à VÉRIFIER lors de la passe Linux (docs/quality-automation.md §3)
        found = shutil.which("reaper")
        for cand in ([Path(found)] if found else []) + [Path.home() / "opt/REAPER/reaper", Path("/opt/REAPER/reaper"),
                                                         Path("/usr/local/bin/reaper")]:
            if cand.is_file():
                return cand
        raise SystemExit("REAPER not found on PATH: pass --reaper or set REAPER_BIN")
    sys.path.insert(0, str(ROOT))
    from provision.desktop import reaper_binary as rb
    return rb()


# ── la vérification d'un patch ────────────────────────────────────────────────────────────────────────
def _outboard_types():
    """Les blocs `engine: midi` (Whammy DT…) : une vraie pédale pilotée par le bridge, jamais posée dans REAPER —
    absents de la carte vivante PAR CONSTRUCTION (faux échecs de la campagne 2026-10-25)."""
    out = set()
    for f in (ROOT / "library" / "catalog").glob("effects*.json"):
        fx = (read_json(f, {}) or {}).get("effects") or []
        out |= {e["type"] for e in fx if isinstance(e, dict) and e.get("engine") == "midi" and e.get("type")}
    return out


def patch_block_ids(p):
    ids, outboard = set(), _outboard_types()
    for lane in p.get("lanes") or []:
        chain = lane.get("chain") or {}
        blocks = list(chain.get("pre") or []) + list(chain.get("post") or [])
        for br in (chain.get("split") or {}).get("branches") or []:
            blocks += list(br.get("blocks") or [])
        ids |= {b["id"] for b in blocks if b.get("type") not in outboard}
    return ids


def wait_rig(base, presets, timeout, pid=None, prev_t=-1):
    """Attend la fin du rappel : plus de `rig_loading`, la carte vivante au nom du preset demandé, et un
    `.rig-check.json` STRICTEMENT plus récent que celui d'avant (golem_rig l'écrit ~2 s après la carte : une
    tolérance en secondes prenait la passe du patch précédent pour la nôtre)."""
    deadline = time.monotonic() + timeout
    st, rc = None, None
    while time.monotonic() < deadline:
        st = http(base, "/api/state")
        rc = read_json(presets / ".rig-check.json")
        live = read_json(presets / ".livemap.json") or {}
        if not st.get("rig_loading") and rc and rc.get("t", 0) > prev_t and (pid is None or live.get("preset") == pid):
            return st, rc
        time.sleep(0.5)
    return st, rc


SERVICES_SOFT = False     # --engine golem-engine : les blocs de SERVICE (lanes gen/rec/arr) pas encore portés ne cachent pas le rig


def check_patch(base, presets, p, timeout, log, ctx=None):
    pid = "patch:" + p["id"]
    status = http(base, f"/api/blocks/status?preset={pid}")
    services = []
    if SERVICES_SOFT:
        services = [f"{b['id']}:{b['type']}" for b in status.get("blocks", [])
                    if b.get("state") != "ready" and b.get("reason") == "engine" and b.get("lane") in ("gen", "rec", "arr")]
    not_ready = [f"{b['id']}:{b['type']} ({b['state']}{': ' + b['why'] if b.get('why') else ''})"
                 for b in status.get("blocks", []) if b.get("state") != "ready"
                 and f"{b['id']}:{b['type']}" not in services]
    if not_ready:
        return {"id": p["id"], "name": p.get("name"), "verdict": "skipped", "needs": not_ready}
    t0 = time.time()
    prev_t = (read_json(presets / ".rig-check.json") or {}).get("t", -1)
    try:
        http(base, "/api/recall", {"preset": pid}, timeout=120)
    except Exception as e:
        return {"id": p["id"], "name": p.get("name"), "verdict": "fail", "issues": [f"recall: {e}"]}
    st, rc = wait_rig(base, presets, timeout, pid=pid, prev_t=prev_t)
    # la carte factice n'a pas l'entrée du rôle (une voix, des claviers) : c'est l'inventaire, pas le moteur
    if "cannot be mounted:" in str(st.get("rig_error") or ""):
        return {"id": p["id"], "name": p.get("name"), "verdict": "skipped", "needs": [st["rig_error"]]}
    issues = []
    if st.get("preset_id") != pid:
        issues.append(f"bridge says preset {st.get('preset_id')!r}, not {pid!r}")
    if st.get("rig_error"):
        issues.append(f"rig_error: {st['rig_error']}")
    if not rc or rc.get("t", 0) <= prev_t:
        issues.append("no rig-check after the recall (golem_watch rig_verify never ran)")
    else:
        if not rc.get("ok"):
            issues.append("rig-check not ok")
        issues += [f"rig-check: {i}" for i in rc.get("issues") or []]
    live = read_json(presets / ".livemap.json") or {}
    if live.get("preset") != pid:
        issues.append(f"livemap is for {live.get('preset')!r}")
    else:
        want, got = patch_block_ids(p), set((live.get("blocks") or {}).keys())
        missing = sorted(want - got)
        if missing:
            issues.append("blocks of the patch absent from the live map: " + ", ".join(missing))
    plugins = (read_json(presets / ".rig-plugins.json") or {}).get("types") or {}
    for bid, b in (live.get("blocks") or {}).items():
        t = b.get("type")
        if t in plugins and not plugins[t].get("ok"):
            issues.append(f"plugin of block type {t} not found ({plugins[t].get('name')})")
    scenes = [s.get("id") for s in p.get("scenes") or [] if s.get("id")]
    scene_note = ""
    if len(scenes) > 1 and not issues:
        target = scenes[1]
        try:
            http(base, "/api/recall", {"scene": target}, timeout=60)
            time.sleep(1.5)
            st2 = http(base, "/api/state")
            if st2.get("scene_id") != target:
                issues.append(f"scene {target} asked, bridge on {st2.get('scene_id')!r}")
            if st2.get("rig_error"):
                issues.append(f"rig_error after scene change: {st2['rig_error']}")
            scene_note = f"scene {scenes[0]}→{target}"
        except Exception as e:
            issues.append(f"scene change: {e}")
    renders = []
    if ctx and ctx.get("render") and not issues:
        renders, more = render_patch(ctx, p, pid, scenes, log)
        issues += more
    return {"id": p["id"], "name": p.get("name"), "verdict": "fail" if issues else "ok", "issues": issues,
            "blocks": len(live.get("blocks") or {}), "rig_check": {"checked": (rc or {}).get("checked"), "t": (rc or {}).get("t")},
            "scene": scene_note, "renders": renders, "seconds": round(time.time() - t0, 1),
            **({"services_not_here": services} if services else {})}


def engine_pid(presets):
    try:
        return int((presets / ".engine.pid").read_text().strip())
    except (OSError, ValueError):
        return None


def kill_restart_round(base, presets, log):
    """Le Golem Engine tué net (un crash), puis relancé par le bouton du Dashboard : le bridge doit voir la chute, le
    fait Health « engine » passer au rouge, la relance repartir, le moteur reparler, et le DERNIER patch revenir tout seul
    (monitors._remount_after_restart) — docs/ardour-plan.md §7c, A2.1."""
    import signal
    issues = []
    st = http(base, "/api/state")
    want = st.get("preset_id")
    old = engine_pid(presets)
    if not old:
        return ["no engine PID before the kill"]
    os.kill(old, signal.SIGKILL)
    t_kill = time.time()
    down = False
    for _ in range(40):
        if not http(base, "/api/state").get("reaper_running"):
            down = True
            break
        time.sleep(0.25)
    if not down:
        issues.append("the bridge never saw the engine go down")
    fact = next((f for f in http(base, "/api/health/facts?fresh=1").get("facts") or [] if f.get("id") == "engine"), {})
    if fact.get("level") not in ("bad", "wait"):
        issues.append(f"health fact 'engine' is {fact.get('level')!r} while the engine is dead: {fact.get('text')}")
    log(f"  engine killed — bridge saw it in {time.time() - t_kill:.1f} s, health: {fact.get('level')} ({fact.get('text')})")
    t0 = time.time()
    http(base, "/api/system/reaper-restart", {})
    back = None
    for _ in range(120):
        st = http(base, "/api/state")
        if st.get("reaper_running") and st.get("reaper_connected") and engine_pid(presets) not in (None, old):
            back = time.time() - t0
            break
        time.sleep(0.25)
    if back is None:
        issues.append("the engine did not come back talking within 30 s of the restart")
        return issues
    remount = None
    for _ in range(180):
        live = read_json(presets / ".livemap.json") or {}
        try:
            fresh = (presets / ".livemap.json").stat().st_mtime > t0
        except OSError:
            fresh = False
        if fresh and live.get("preset") == want:
            remount = time.time() - t0
            break
        time.sleep(0.25)
    if remount is None:
        issues.append(f"{want} was not remounted on the new engine within 45 s")
    fact = next((f for f in http(base, "/api/health/facts?fresh=1").get("facts") or [] if f.get("id") == "engine"), {})
    if fact.get("level") != "ok":
        issues.append(f"health fact 'engine' is {fact.get('level')!r} after the restart: {fact.get('text')}")
    log(f"  restarted: talking after {back:.1f} s, {want} remounted after {remount or 0:.1f} s, health: {fact.get('level')}")
    return issues


def real_card_setup(root, log):
    """La carte du rack pour le banc (--real-card) : sa config (io.json, registre, carte des entrées) copiée dans le
    worktree, et ses deux noms (id ALSA, nom du registre). Refuse si le rack la tient : REAPER, ou son bridge."""
    if subprocess.run(["pgrep", "-x", "reaper"], capture_output=True).stdout.strip():
        raise SystemExit("--real-card: REAPER is running — the card is his (golem stop first)")
    if subprocess.run(["pgrep", "-f", "uvicorn bridge.app:app --host 0.0.0.0"], capture_output=True).stdout.strip():
        raise SystemExit("--real-card: the rack's bridge is running — its pedalboard and MIDI are its own (golem stop first)")
    sys.path.insert(0, str(ROOT))
    from bridge import config as RC
    from bridge.engine.ardour import card_device
    card_id, card_name = RC.alsa_card(), card_device()
    if not card_id or not card_name:
        raise SystemExit("--real-card: no active card in this golem's config")
    for rel in ("config/io.json", f"config/cards/{card_id}.json", f"config/inputmaps/hw-{card_id}.json"):
        src, dst = ROOT / rel, root / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    log(f"real card: {card_name} (hw:{card_id}) — no engine output is linked to it")
    return card_id, card_name


def soundcard_round(base, presets, log, card_id):
    """Le Golem Engine sur la vraie carte (docs/ardour-plan.md §7c, A2.3) : le périphérique ouvert, ses entrées et sorties
    vues, la latence mesurée par le bridge (hw_params ALSA), les vumètres d'entrée sur les entrées physiques, la lane de
    chaque rôle sur l'entrée que la carte des entrées lui donne, les ports MIDI de la carte — et rien vers les sorties."""
    issues = []
    st = read_json(presets / ".engine-status.json") or {}
    if st.get("backend") != "ALSA":
        issues.append(f"engine backend is {st.get('backend')!r}")
    if not st.get("inputs") or not st.get("outputs"):
        issues.append(f"card I/O seen by the engine: {st.get('inputs')} in, {st.get('outputs')} out")
    s = http(base, "/api/state")
    if s.get("latency_ms") is None:
        issues.append("no latency measured (ALSA hw_params closed: the engine does not hold the card)")
    imap = read_json(presets.parent / "config" / "inputmaps" / f"hw-{card_id}.json") or {}
    want = next((int(i["ch"]) for i in imap.get("inputs") or [] if i.get("role") == "guitar" and str(i.get("ch", "")).isdigit()), None)
    p = os.path.join(presets, ".engine-dump.json")
    with contextlib.suppress(OSError):
        os.remove(p)
    http(base, "/api/recall", {"preset": "patch:" + ENGINE_FIXTURE_ID}, timeout=60)
    wait_rig(base, presets, 30, pid="patch:" + ENGINE_FIXTURE_ID)
    # le dump n'est pas un geste du bridge : posé à la main dans le slot du worktree, après le rappel
    seq = int(time.time() * 1000)
    (presets / ".command.json").write_text(json.dumps({"action": "dump", "seq": seq}))
    dump = None
    for _ in range(40):
        dump = read_json(presets / ".engine-dump.json")
        if dump:
            break
        time.sleep(0.25)
    tracks = (dump or {}).get("tracks") or []
    lane = next((t for t in tracks if t.get("input")), {})
    got = [c for c in lane.get("input") or []]
    if not want:
        issues.append(f"no guitar input in the card's input map (hw-{card_id}.json)")
    elif not any(c.endswith(f"capture_{want}") for c in got):
        issues.append(f"the guitar lane listens to {got}, the card's input map puts guitar on input {want}")
    outs = [c for t in tracks for c in t.get("output") or [] if "playback" in c]
    if outs:
        issues.append(f"engine outputs linked to the card although GOLEM_ENGINE_NO_OUTPUT: {outs}")
    time.sleep(2)
    lv = http(base, "/api/state").get("levels") or {}
    st = read_json(presets / ".engine-status.json") or {}
    log(f"  card: {st.get('device')} · {st.get('inputs')} in / {st.get('outputs')} out · {st.get('sample_rate')} Hz · "
        f"buffer {st.get('buffer')} · latency {s.get('latency_ms')} ms · DSP {round(st.get('dsp_load') or 0, 1)} % · "
        f"xruns {st.get('xruns')}")
    log(f"  guitar lane on {got} (input map: {want}) · outputs linked: {outs or 'none'} · input levels {lv}")
    log(f"  MIDI in: {st.get('midi_in')} · MIDI out: {st.get('midi_out')}")
    return issues


def dashboard_round(base, presets, log):
    """Ce que le Dashboard lit, sous le Golem Engine (docs/ardour-plan.md §7c, A2.2) : le moteur nommé, son buffer, sa
    fréquence et sa charge DSP lus dans le moteur, la tuile process sur SON pid, le témoin « le thread audio avance »
    (presets/.clock.json écrit par le veilleur), les xruns comptés, et un changement de buffer appliqué À CHAUD."""
    issues = []
    sysd = http(base, "/api/system")
    eng = sysd.get("engine") or {}
    if eng.get("id") != "ardour" or eng.get("name") != "Golem Engine":
        issues.append(f"/api/system engine is {eng}")
    for k in ("audio_bsize", "audio_srate", "audio_dsp_load"):
        if sysd.get(k) is None:
            issues.append(f"/api/system {k} is empty")
    hp = (http(base, "/api/system/health").get("reaper") or {})
    if not hp.get("running") or hp.get("pid") != engine_pid(presets):
        issues.append(f"process tile: {hp} (engine pid {engine_pid(presets)})")
    st = http(base, "/api/state")
    if not (st.get("audio") or {}).get("ok"):
        issues.append(f"audio thread witness not ok: {st.get('audio')}")
    if st.get("xruns") is None:
        issues.append("xruns not counted")
    before = sysd.get("audio_bsize")
    target = 256 if before != 256 else 512
    t0 = time.time()
    try:
        r = http(base, "/api/audio-buffer", {"size": target})
    except Exception as e:
        return issues + [f"buffer change: {e}"]
    if r.get("restarting") is not False:
        issues.append(f"buffer change answered {r}")
    got = None
    for _ in range(40):
        got = http(base, "/api/system").get("audio_bsize")
        if got == target:
            break
        time.sleep(0.25)
    took = time.time() - t0
    if got != target:
        issues.append(f"buffer {target} asked, engine on {got}")
    cfg = read_json(presets.parent / "config" / "golem-engine.json") or {}
    if cfg.get("buffer") != target:
        issues.append(f"config/golem-engine.json says {cfg}")
    st2 = http(base, "/api/state")
    if not st2.get("reaper_running"):
        issues.append("engine down after the buffer change")
    log(f"  dashboard: {eng.get('name')} {eng.get('version')} · buffer {before} → {got} in {took:.1f} s (no restart) · "
        f"{sysd.get('audio_srate')} Hz · DSP {sysd.get('audio_dsp_load')} % · pid {hp.get('pid')} · "
        f"xruns {st.get('xruns')} · audio {'ok' if (st.get('audio') or {}).get('ok') else st.get('audio')}")
    return issues


# ── enchaînement : chercher à casser ────────────────────────────────────────────────────────────────
# Des rappels lancés sans attendre la fin du précédent, une scène demandée en plein rebuild (la fenêtre SETTLE) :
# ce que fait un pied pressé. Après chaque salve, REAPER doit vivre, et ce qui est posé doit être le DERNIER patch
# demandé, complet — jamais un mélange, jamais l'avant-dernier.
def chain_round(base, presets, pool, rng, reaper_p, timeout, lua_errors_before):
    seq, gestures = [], []
    for _ in range(rng.randint(3, 6)):
        p = rng.choice(pool)
        seq.append(p)
        http(base, "/api/recall", {"preset": "patch:" + p["id"]}, timeout=120)
        gestures.append(p["id"])
        time.sleep(rng.uniform(0, 1.2))
        scenes = [s.get("id") for s in p.get("scenes") or [] if s.get("id")]
        if len(scenes) > 1 and rng.random() < .6:
            sc = rng.choice(scenes[1:])
            http(base, "/api/recall", {"scene": sc}, timeout=60)
            gestures.append(f"scene {sc}")
            time.sleep(rng.uniform(0, .8))
    last = seq[-1]
    pid = "patch:" + last["id"]
    st, rc = wait_rig(base, presets, timeout * 2, pid=pid)
    time.sleep(2.5)                       # golem_rig réécrit rig-check ~2 s après la carte : lire la passe finale
    st, rc = http(base, "/api/state"), read_json(presets / ".rig-check.json") or {}
    issues = []
    if reaper_p.poll() is not None:
        return gestures, [f"REAPER died (exit {reaper_p.returncode})"]
    if st.get("preset_id") != pid:
        issues.append(f"bridge on {st.get('preset_id')!r}, last asked {pid!r}")
    if st.get("rig_loading"):
        issues.append("still rig_loading after the series")
    if st.get("rig_error"):
        issues.append(f"rig_error: {st['rig_error']}")
    if not rc.get("ok"):
        issues.append("rig-check not ok: " + "; ".join(rc.get("issues") or []))
    live = read_json(presets / ".livemap.json") or {}
    if live.get("preset") != pid:
        issues.append(f"livemap is for {live.get('preset')!r}")
    else:
        missing = sorted(patch_block_ids(last) - set((live.get("blocks") or {}).keys()))
        if missing:
            issues.append("blocks absent from the live map: " + ", ".join(missing))
    errs = presets / ".lua-errors.log"
    size = errs.stat().st_size if errs.exists() else 0
    if size > lua_errors_before:
        issues.append("Lua errors: " + errs.read_text(encoding="utf-8", errors="replace")[lua_errors_before:][-600:])
    return gestures, issues


# ── main ─────────────────────────────────────────────────────────────────────────────────────────────
# ── lot 3b : rendus de référence ─────────────────────────────────────────────────────────────────────
# Le son d'un patch posé, mesuré : une phrase DI rejouée HORS LIGNE à travers la lane (golem_preview.lua, le
# chemin du reamp — clone de la chaîne, aucun son aux baffles), puis une EMPREINTE compacte (enveloppe RMS par
# 100 ms, équilibre spectral en 8 bandes, crête, niveau) comparée à la référence versionnée dans tests/golden/.
# Une régression silencieuse — convolveur contourné, killswitch, gain, mono — change l'empreinte sans rien planter.
GOLDEN = ROOT / "tests" / "golden" / "renders.json"
SR = 48000
BANDS = ((60, 150), (150, 400), (400, 1000), (1000, 2500), (2500, 5000), (5000, 8000), (8000, 12000), (12000, 20000))
CHAINS = ("Sandbox #Input 1", "Sandbox #Input 2", "Sandbox #Input 3")     # la lane posée : guitare, basse, clavier


def make_di(path):
    """Une phrase DI SYNTHÉTIQUE et déterministe (aucun droit, rien à livrer) : silence, une note pincée (110 Hz et
    ses harmoniques, décroissance), un glissando 80 Hz → 5 kHz, un souffle court, puis du silence pour la queue des
    delays et réverbes. Mono, 48 kHz, 16 bits, 4 s."""
    import math
    import struct
    import wave
    n = int(SR * 4.0)
    out = [0.0] * n

    def add(start, dur, fn):
        s0 = int(start * SR)
        for i in range(int(dur * SR)):
            if s0 + i < n:
                out[s0 + i] += fn(i / SR)
    add(0.3, 1.4, lambda t: sum(0.5 / (k * k) * math.sin(2 * math.pi * 110 * k * t) for k in range(1, 7)) * math.exp(-3.0 * t) * 0.6)
    f0, f1, d = 80.0, 5000.0, 1.0
    add(1.9, d, lambda t: 0.25 * math.sin(2 * math.pi * f0 * d / math.log(f1 / f0) * (math.exp(t / d * math.log(f1 / f0)) - 1)))
    seed = [12345]

    def noise(t):
        seed[0] = (1103515245 * seed[0] + 12345) % 2 ** 31
        return (seed[0] / 2 ** 31 - 0.5) * 0.3 * math.exp(-8.0 * t)
    add(3.0, 0.3, noise)
    with wave.open(str(path), "wb") as w:
        w.setparams((1, 2, SR, n, "NONE", "not compressed"))
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in out))
    return path


def read_wav(path):
    """Échantillons mono (flottants, -1..1) et fréquence : PCM 16/24/32 ou flottant 32 (ce que REAPER rend)."""
    import struct
    import numpy as np
    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, fmt, raw = 12, None, b""
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    tag, ch, sr, _, _, bits = struct.unpack_from("<HHIIHH", fmt, 0)
    if tag == 0xFFFE and len(fmt) >= 26:                       # WAVE_FORMAT_EXTENSIBLE : le vrai format dans le GUID
        tag = struct.unpack_from("<H", fmt, 24)[0]
    if tag == 3:
        x = np.frombuffer(raw, dtype="<f4" if bits == 32 else "<f8").astype(np.float64)
    elif bits == 16:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    elif bits == 24:
        b = np.frombuffer(raw[:len(raw) - len(raw) % 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        x = (b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16))
        x = np.where(x >= 2 ** 23, x - 2 ** 24, x) / 2 ** 23
    elif bits == 32:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2 ** 31
    else:
        raise ValueError(f"unsupported WAV: tag {tag}, {bits} bits")
    if ch > 1:
        x = x[:len(x) - len(x) % ch].reshape(-1, ch).mean(axis=1)
    return x, sr


def fingerprint(x, sr):
    import numpy as np

    def db(v):
        return float(20 * np.log10(max(float(v), 1e-9)))
    frame = int(sr * 0.1)
    env = [db(np.sqrt(np.mean(x[i * frame:(i + 1) * frame] ** 2))) for i in range(len(x) // frame)]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    total = float(spec.sum()) or 1e-18
    bands = [db(np.sqrt(spec[(freqs >= lo) & (freqs < hi)].sum() / total)) for lo, hi in BANDS]
    return {"seconds": round(len(x) / sr, 3), "peak_db": round(db(np.max(np.abs(x))), 2),
            "rms_db": round(db(np.sqrt(np.mean(x ** 2))), 2),
            "env_db": [round(e, 1) for e in env], "bands_db": [round(b, 1) for b in bands]}


def compare_fp(got, want, tol_env, tol_band):
    """Les raisons de douter ; vide si les deux empreintes se ressemblent dans les tolérances (dB)."""
    why = []
    if abs(got["seconds"] - want["seconds"]) > 0.15:
        why.append(f"length {got['seconds']} s vs {want['seconds']} s")
    if got["rms_db"] < -60 <= want["rms_db"]:
        why.append("silence where the reference has sound")
    n = min(len(got["env_db"]), len(want["env_db"]))
    worst = max((abs(g - w) for g, w in zip(got["env_db"][:n], want["env_db"][:n]) if max(g, w) > -70), default=0.0)
    if worst > tol_env:
        why.append(f"envelope differs by {worst:.1f} dB (tolerance {tol_env})")
    wb = max(abs(g - w) for g, w in zip(got["bands_db"], want["bands_db"]))
    if wb > tol_band:
        why.append(f"spectral balance differs by {wb:.1f} dB (tolerance {tol_band})")
    return why


def patch_sig(p):
    """Ce qui fait le son du patch : une référence ne vaut que pour cette forme-là (lanes, scènes, config)."""
    import hashlib
    body = json.dumps({"lanes": p.get("lanes"), "scenes": p.get("scenes"), "config": p.get("config")},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def render_scene(ctx, pid, scene, chain):
    """Demande à golem_preview.lua le rendu hors ligne de la DI à travers la lane posée — rend (wav, erreur)."""
    presets = ctx["root"] / "presets"
    out = ctx["work"] / "renders" / f"{pid.replace(':', '_')}-{scene}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    try:
        (presets / ".preview.json").unlink()
    except OSError:
        pass
    cmd = {"action": "preview", "op": "render", "scene": scene, "di": ctx["di"].as_posix(), "out": out.as_posix(),
           "tail": 1.5, "chain": chain, "tree": True, "_route": "preview",
           # une vraie DI (--di) : rendue à 48 kHz, la fréquence du Golem Engine qu'on compare (--against) ; la phrase
           # synthétique garde la fréquence du projet, celle des références tests/golden/renders.json
           **({"sr": SR} if ctx.get("real_di") else {})}
    subprocess.run([sys.executable, str(ctx["root"] / "reaper" / "golem-cmd.py"), json.dumps(cmd)], cwd=ctx["root"],
                   env={**ctx["env"], "GOLEM_ROOT": str(ctx["root"])}, check=True, capture_output=True, timeout=60)
    deadline = time.monotonic() + ctx["render_timeout"]
    while time.monotonic() < deadline:
        st = read_json(presets / ".preview.json") or {}
        if st.get("scene") == scene and (st.get("done") or st.get("error")):
            if st.get("error"):
                return None, st["error"]
            return (out, None) if out.exists() else (None, "REAPER said done but wrote no file")
        time.sleep(0.5)
    return None, f"no render after {ctx['render_timeout']} s"


def render_scene_engine(ctx, pid, scene):
    """Le Golem Engine (docs/ardour-plan.md §5, A3 étape 3) : la session TELLE QUE LA SCÈNE L'A MONTÉE (commande
    `snapshot` du veilleur), copiée, la DI posée sur la piste d'entrée de la lane et jouée du disque, les sorties de la
    lane vers le master (golem-place --disk --to-master), rendue par l'export d'Ardour — rend (wav, erreur)."""
    presets = ctx["root"] / "presets"
    name = f"bench-{scene}"
    stem = f"{pid.replace(':', '_')}-{scene}"
    out = ctx["work"] / "renders" / f"{stem}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    snap = presets / ".engine-snapshot.json"
    snap.unlink(missing_ok=True)
    subprocess.run([sys.executable, str(ctx["root"] / "reaper" / "golem-cmd.py"), json.dumps({"action": "snapshot", "name": name})],
                   cwd=ctx["root"], env={**ctx["env"], "GOLEM_ROOT": str(ctx["root"])}, check=True, capture_output=True,
                   timeout=60)
    st, deadline = None, time.monotonic() + 30
    while time.monotonic() < deadline:
        st = read_json(snap) or {}
        if st.get("name") == name:
            break
        time.sleep(0.25)
    else:
        return None, "the engine saved no snapshot within 30 s"
    tracks = (read_json(presets / ".engine-dump.json") or {}).get("tracks") or []
    ins = [t["name"] for t in tracks if any("capture" in c for c in t.get("input") or [])]
    outs = [t["name"] for t in tracks if any("playback" in c for c in t.get("output") or [])]
    if not ins:
        return None, "no lane input track in the engine dump"
    if not outs:
        return None, "pas de sortie : no route of the rig goes to the card"
    copy = ctx["work"] / "engine-renders" / stem
    shutil.rmtree(copy, ignore_errors=True)
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(st["dir"], copy, ignore=shutil.ignore_patterns("*.pending", "*.lock"))
    b = ctx["engine_dir"] / "build"
    env_sh = ctx["engine_dir"] / "golem" / "dev" / "env.sh"
    # l'environnement de dev du moteur (ses bibliothèques), puis la commande telle quelle ("$@" : aucun nom réinterprété)
    run = ['bash', '-c', 'source "$0" >/dev/null 2>&1; exec "$@"', str(env_sh)]
    envx = {**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    logs = []
    for cmd, t in (([str(b / "golem" / "golem-place"), str(copy), name, ins[0], str(ctx["di"]), "1.5", "--disk",
                     "--to-master", ",".join(outs)], 60),
                   ([str(b / "session_utils" / "golem-engine9-export"), "-b", "float", "-o", str(out), str(copy), name], 180)):
        p = subprocess.run(run + cmd, env=envx, capture_output=True, text=True, timeout=t)
        logs.append(" ".join(cmd) + "\n" + p.stdout + p.stderr)
        if p.returncode:
            break
    (copy.parent / f"{stem}.log").write_text("\n".join(logs), encoding="utf-8")
    if len(ins) > 1:
        logs.append(f"several lane inputs ({ins}): the DI went to {ins[0]} only")
    return (out, None) if out.is_file() else (None, f"engine render failed (engine-renders/{stem}.log)")


WARMUP_S = 4                 # secondes de début laissées hors du nul REAPER / Golem Engine (vs_reaper)


def engine_blocks_only(root, log):
    """--engine-blocks-only : les patches du worktree RÉDUITS aux blocs que le Golem Engine joue (sa table,
    library/catalog/effects-golem-engine.json) — sur les DEUX moteurs, pour comparer tout le reste (blocs du même
    binaire, branches, fusion, scènes) avant que golem-fx livre les autres (docs/ardour-plan.md §5, A3 étape 3).
    Un bloc retiré l'est aussi des scènes et des états (blocks, params) ; rend {patch: [types retirés]}."""
    sys.path.insert(0, str(ROOT))
    from bridge.engine import ardour_plan as P
    playable = set(P.load_table())
    known = set(P.load_catalog())
    out = {}
    for d in (root / "library" / "patches", root / "library" / "factory" / "patches"):
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            p = json.loads(f.read_text(encoding="utf-8"))
            gone, types = set(), set()

            def strip(o):
                if isinstance(o, list):
                    keep = []
                    for x in o:
                        t = x.get("type") if isinstance(x, dict) else None
                        if t in known and t not in playable:
                            gone.add(x.get("id"))
                            types.add(t)
                            continue
                        keep.append(strip(x))
                    return keep
                if isinstance(o, dict):
                    return {k: strip(v) for k, v in o.items()}
                return o
            p["lanes"] = strip(p.get("lanes") or [])
            if not gone:
                continue

            def unref(o):
                if isinstance(o, dict):
                    for k in ("blocks", "params"):
                        if isinstance(o.get(k), dict):
                            o[k] = {i: v for i, v in o[k].items() if i not in gone}
                    for v in o.values():
                        unref(v)
                elif isinstance(o, list):
                    for v in o:
                        unref(v)
            unref(p.get("scenes"))
            unref(p["lanes"])
            f.write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
            out[p.get("id", f.stem)] = sorted(types)
    log(f"engine blocks only: {len(out)} patch(es) reduced to what the Golem Engine plays")
    return out


def vs_reaper(ctx, wav):
    """Le même rendu fait par REAPER (un run --render précédent, gardé : --against) : décalage, niveau, nul, pire tiers
    d'octave (check-core-parity.py, le banc de parité des blocs) — None sans rendu REAPER du même nom."""
    ref = ctx.get("against") and ctx["against"] / "renders" / wav.name
    if not ref or not ref.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_core_parity", ROOT / "tools" / "check-core-parity.py")
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)
    x, sr = read_wav(ref)
    y, _ = read_wav(wav)
    full = cp._metrics(list(x), list(y))
    # sans la CHAUFFE : le Golem Engine pré-roule 2 s avant d'exporter, le rendu de démo de REAPER part à froid — un NAM
    # rend ses premières centaines de ms autrement (mesuré en A0) et un delay en répète l'écart ~3 s (2026-11-12)
    m = cp._metrics(list(x[WARMUP_S * sr:]), list(y[WARMUP_S * sr:]))
    m["null_full_db"] = full["null_db"]
    # le pire tiers d'octave AUDIBLE : une bande à plus de 50 dB sous le total (au-dessus de 10 kHz derrière un baffle,
    # -60 à -90 dB) ne compte pas — son écart est du bruit de quantification (REAPER rend en 24 bits entiers)
    import numpy as np
    a, b = np.asarray(x[WARMUP_S * sr:]), np.asarray(y[WARMUP_S * sr:])
    k = min(len(a), len(b))
    A, B = np.abs(np.fft.rfft(a[:k])) ** 2, np.abs(np.fft.rfft(b[:k])) ** 2
    f = np.fft.rfftfreq(k, 1 / sr)
    worst, at = 0.0, 0.0
    for i in range(-15, 13):
        fc = 1000 * 2 ** (i / 3)
        sel = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        if not sel.any() or A[sel].sum() < A.sum() * 1e-5:
            continue
        dv = 10 * np.log10((B[sel].sum() + 1e-30) / A[sel].sum())
        if abs(dv) > abs(worst):
            worst, at = float(dv), fc
    m["band_audible_db"], m["band_audible_hz"] = worst, at
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()}


def render_patch(ctx, p, pid, scenes, log):
    """Rend les premières scènes, compare chaque empreinte à la référence ; rend (liste par scène, problèmes)."""
    results, issues = [], []
    sig, chain = patch_sig(p), None
    if p.get("role") in ("keys", "keys-pads", "pads", "drums"):
        # une lane MIDI : la DI audio n'y entre pas (le synthé joue des notes) — rien à comparer
        return [{"scene": s, "status": "skipped (MIDI lane)"} for s in scenes[:ctx["render_scenes"]] or ["A"]], []
    if ctx.get("di_auto"):
        # la DI des démos par scène (bridge/preview.py) : le genre du patch choisit le seau ; sans genre, la clean
        sys.path.insert(0, str(ROOT))
        from bridge import preview as _pv
        bucket = _pv._bucket_from_tags(p.get("role"), p.get("tags")) or "guitar/clean"
        di = ROOT / "library" / "di-refs" / f"{bucket}.wav"
        if not di.is_file():
            return [{"scene": s, "status": f"skipped (no DI recorded for {bucket})"} for s in scenes[:ctx["render_scenes"]] or ["A"]], []
        ctx["di"] = di
        log(f"    DI {bucket}")
    for scene in scenes[:ctx["render_scenes"]] or ["A"]:
        try:
            http(ctx["base"], "/api/recall", {"scene": scene}, timeout=60)
            time.sleep(1.5)
        except Exception as e:
            results.append({"scene": scene, "status": "error", "why": f"scene: {e}"}); continue
        wav = err = None
        for cand in ([] if ctx.get("engine_dir") else [chain] if chain else CHAINS):
            wav, err = render_scene(ctx, pid, scene, cand)
            # « piste absente » ou « pas de sortie » : ce n'est pas la lane du patch, on essaie la suivante
            if wav or not ("absente" in str(err) or "pas de sortie" in str(err)):
                chain = cand; break
        if ctx.get("engine_dir"):
            wav, err = render_scene_engine(ctx, pid, scene)
        if not wav:
            results.append({"scene": scene, "status": "error", "why": err}); issues.append(f"render {scene}: {err}"); continue
        try:
            x, sr = read_wav(wav)
            fp = fingerprint(x, sr)
        except Exception as e:
            results.append({"scene": scene, "status": "error", "why": f"unreadable render: {e}"}); issues.append(f"render {scene}: {e}"); continue
        ref = (ctx["golden"].get(pid) or {}).get(scene)
        entry = {"scene": scene, "fp": fp, "wav": wav.name, "chain": chain}
        vs = vs_reaper(ctx, wav)
        if vs:
            entry["vs_reaper"] = vs
            log(f"    {scene}: vs REAPER — lag {vs.get('lag')}, level {vs.get('level_db'):+.2f} dB, null {vs.get('null_db'):.1f} dB, "
                f"worst audible third-octave {vs.get('band_audible_db'):+.1f} dB @ {vs.get('band_audible_hz'):.0f} Hz (null from the start "
                f"{vs.get('null_full_db'):.1f} dB)")
        if ctx["update_golden"]:
            ctx["golden"].setdefault(pid, {})[scene] = {"sig": sig, "fp": fp, "os": sys.platform, "at": time.strftime("%Y-%m-%d")}
            entry["status"] = "updated"
        elif ctx.get("real_di"):
            entry["status"] = "rendered (real DI: no golden)"     # les références sont faites avec la phrase synthétique
        elif not ref:
            entry["status"] = "no golden"
        elif ref.get("sig") != sig:
            entry["status"] = "golden stale (the patch changed since the reference)"
        else:
            why = compare_fp(fp, ref["fp"], ctx["tol_env"], ctx["tol_band"])
            entry["status"] = "match" if not why else "MISMATCH"
            if why:
                entry["why"] = why; issues.append(f"render {scene} differs from the reference: " + "; ".join(why))
        results.append(entry)
    return results, issues


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reaper", type=Path, help="binaire REAPER (défaut : celui du lanceur, ou REAPER_BIN)")
    ap.add_argument("--engine", choices=("reaper", "golem-engine"), default="reaper",
                    help="le moteur du banc : REAPER (défaut) ou le Golem Engine (docs/ardour-plan.md §7c : son veilleur, "
                         "backend factice, session jetable ; un patch dont un bloc ne joue pas sur ce moteur est « skipped »)")
    ap.add_argument("--engine-dir", type=Path, default=Path.home() / "golem-engine",
                    help="l'arbre du Golem Engine construit (défaut ~/golem-engine)")
    ap.add_argument("--work", type=Path, help="dossier de travail (défaut : temporaire)")
    ap.add_argument("--only", help="ne rappeler que les patches dont l'id contient ce texte")
    ap.add_argument("--all", action="store_true", help="tous les patches, pas seulement ceux d'usine")
    ap.add_argument("--limit", type=int, default=0, help="au plus N patches")
    ap.add_argument("--fetch", action="store_true", help="laisser le bridge télécharger les modèles manquants")
    ap.add_argument("--fixture", action="store_true",
                    help=f"ajouter le patch de banc « {FIXTURE_ID} » (effets intégrés et JSFX seulement : aucun téléchargement)")
    ap.add_argument("--timeout", type=int, default=25, help="secondes accordées à un rappel (défaut 25)")
    ap.add_argument("--boot", type=int, default=300, help="secondes accordées à REAPER pour parler au bridge (défaut 300)")
    ap.add_argument("--cold", action="store_true", help="sans l'inventaire de plugins ni la licence du REAPER de la machine")
    ap.add_argument("--working-tree", action="store_true",
                    help="le worktree part de l'ARBRE DE TRAVAIL (modifs non committées comprises), pas de HEAD")
    ap.add_argument("--keep", action="store_true", help="garder --work (journaux REAPER, bridge, Lua)")
    ap.add_argument("--json", help="écrire le rapport ici")
    ap.add_argument("--content-from", default=os.environ.get("GOLEM_RACK_ROOT") or None,
                    help="le golem dont copier modèles, IR, captures et patches (défaut : ce dépôt, ou GOLEM_RACK_ROOT)")
    ap.add_argument("--chain", type=int, default=0,
                    help="après la passe : N salves de rappels et de scènes sans attendre, sur les patches passés")
    ap.add_argument("--seed", type=int, default=0, help="graine des salves (défaut 0 : la même suite à chaque fois)")
    ap.add_argument("--standard-take", type=int, default=0, metavar="N",
                    help="au lieu des patches : N prises de standard par le vrai chemin, et l'écart du départ armé "
                         "mesuré sur le Mix.wav de chaque prise (budget 1 ms)")
    ap.add_argument("--compo-bed", type=int, default=0, metavar="N",
                    help="au lieu des patches : N prises de riff armées AVEC un bed (docs/compo.md §12 ter), l'écart bed / "
                         "« 1 » de la prise mesuré sur le Mix.wav (budget 1 ms), puis gain, mauvais sha et prise sans bed")
    ap.add_argument("--bed", type=Path, default=BED_FILE, help=f"le bed d'essai (défaut {BED_FILE})")
    ap.add_argument("--real-card", action="store_true",
                    help="--engine golem-engine : la VRAIE carte de ce golem (ALSA), SANS aucune sortie reliée "
                         "(GOLEM_ENGINE_NO_OUTPUT) ; la config de carte du rack est copiée dans le worktree. Refuse si "
                         "REAPER ou le bridge du rack tournent (la carte et le MIDI sont à eux)")
    ap.add_argument("--dashboard", action="store_true",
                    help="--engine golem-engine : ce que lit le Dashboard (moteur, buffer, DSP, process, témoin audio) et un "
                         "changement de buffer à chaud")
    ap.add_argument("--kill-restart", action="store_true",
                    help="--engine golem-engine : après la passe, tuer le moteur, le relancer par le Dashboard, et vérifier "
                         "que le bridge le voit, que Health le dit et que le dernier patch revient")
    g = ap.add_argument_group("rendus de référence (lot 3b)")
    g.add_argument("--render", action="store_true", help="rendre la DI à travers chaque patch posé et comparer à tests/golden/renders.json")
    g.add_argument("--render-scenes", type=int, default=2, help="scènes rendues par patch (défaut 2)")
    g.add_argument("--di", help="la DI rendue : un nom de library/di-refs (« guitar/crunch »), un chemin, ou « auto » (celle "
                                "que le genre du patch choisit, comme les démos par scène) ; défaut : une phrase "
                                "synthétique (celle des références tests/golden/renders.json)")
    g.add_argument("--engine-blocks-only", action="store_true",
                   help="réduire les patches (des deux moteurs) aux blocs que le Golem Engine joue, pour comparer le reste "
                        "en attendant golem-fx")
    g.add_argument("--against", type=Path, help="le --work GARDÉ d'un run --render REAPER : chaque rendu y est comparé au "
                                                 "sien (décalage, niveau, nul, tiers d'octave) — le banc des presets sur "
                                                 "deux moteurs (docs/ardour-plan.md §5, A3 étape 3)")
    g.add_argument("--update-golden", action="store_true", help="écrire les empreintes rendues comme nouvelles références")
    g.add_argument("--golden", type=Path, default=GOLDEN, help=f"le fichier des références (défaut {GOLDEN.relative_to(ROOT)})")
    g.add_argument("--tol-env", type=float, default=2.0, help="tolérance d'enveloppe, dB (défaut 2)")
    g.add_argument("--tol-band", type=float, default=3.0, help="tolérance d'équilibre spectral, dB (défaut 3)")
    g.add_argument("--render-timeout", type=int, default=45, help="secondes accordées à un rendu (défaut 45)")
    a = ap.parse_args()
    if a.update_golden:
        a.render = True
    golem_engine = a.engine == "golem-engine"
    global SERVICES_SOFT
    SERVICES_SOFT = golem_engine
    if golem_engine:
        reaper = (a.engine_dir / "golem" / "engine" / "run.sh").resolve()
        if not reaper.is_file():
            raise SystemExit(f"Golem Engine not found: {reaper} (set --engine-dir)")
        if a.standard_take or a.compo_bed:
            raise SystemExit("--standard-take and --compo-bed need REAPER for now")
    else:
        reaper = (a.reaper or reaper_binary()).resolve()
        if not reaper.is_file():
            raise SystemExit(f"REAPER not found: {reaper} (set --reaper or REAPER_BIN)")
    work = (a.work or Path(tempfile.mkdtemp(prefix="golem-rig-check-"))).resolve()
    work.mkdir(parents=True, exist_ok=True)
    t_start = time.monotonic()
    log = lambda *s: print(*s, flush=True)
    report = {"reaper": str(reaper), "work": str(work), "patches": []}
    root = resource = ctx = None
    bridge_p = reaper_p = None
    try:
        root = make_root(work, log, content_from=a.content_from,
                         rev=working_tree_commit() if a.working_tree else "HEAD")
        resource, runtime = work / "REAPER", work / "runtime"
        runtime.mkdir(exist_ok=True)
        port, osc_send, osc_recv = free_port(), free_port(), free_port()
        env = {**os.environ, "GOLEM_RUNTIME_DIR": str(runtime), "GOLEM_REAPER_RESOURCE_DIR": str(resource),
               "GOLEM_PORT": str(port), "GOLEM_OSC_SEND": str(osc_send), "GOLEM_OSC_RECV": str(osc_recv),
               # pas d'annonce mDNS : ce bridge ne doit pas se faire passer pour le rack de la machine
               "GOLEM_NO_REACH": "1", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
               # ni pédalier ni Whammy : le banc tourne sur la machine du rack, son MIDI matériel n'est pas à lui
               "GOLEM_NO_HW_MIDI": "1",
               "GOLEM_BENCH_CARD": "golem-bench"}
        if golem_engine and a.real_card:
            card_id, card_name = real_card_setup(root, log)
            env.pop("GOLEM_BENCH_CARD", None)
            env.update({"GOLEM_ALSA_CARD": card_id})
        if golem_engine:
            env.update({"GOLEM_ENGINE": "ardour", "GOLEM_ENGINE_DIR": str(a.engine_dir),
                        "GOLEM_ENGINE_SESSION": str(work / "engine-session"), "GOLEM_ENGINE_BACKEND": "None (Dummy)",
                        "GOLEM_ENGINE_LOG": str(work / "engine.log")})
            if a.real_card:
                env.update({"GOLEM_ENGINE_BACKEND": "ALSA", "GOLEM_ENGINE_DEVICE": card_name,
                            "GOLEM_ENGINE_NO_OUTPUT": "1"})
        py_in_root(root, env, "from bridge import factory; factory.seed()")
        log("factory content seeded in the worktree")
        if a.engine_blocks_only:
            for pid_, types in engine_blocks_only(root, log).items():
                log(f"  {pid_}: without {', '.join(types)}")
        if a.fixture:
            log(f"fixture patch: {write_engine_fixture(root) if golem_engine else write_fixture(root)}")
            if not golem_engine and a.render:
                # le patch de banc du Golem Engine aussi : rendu par REAPER, il sert de référence au même patch rendu par
                # le Golem Engine (--against), le seul que les deux moteurs jouent en entier tant que golem-fx manque
                log(f"fixture patch: {write_engine_fixture(root)}")
        if a.standard_take:
            write_standard_bench(root, Path(a.content_from).resolve() if a.content_from else ROOT)
        if a.compo_bed:
            if not a.bed.is_file():
                raise SystemExit(f"--compo-bed needs the test bed: {a.bed} is missing (golem.fm backend/tools/make_test_bed.py)")
            bmeta = bed_meta(a.bed)
            write_take_bench(root)
            log(f"bed {bmeta['sha256'][:12]} ({bmeta['bytes']} bytes, {bmeta['length_s']} s) in {seed_bed(root, a.bed, bmeta)}")
        if not golem_engine:
            prepare_reaper(root, resource, env, osc_send, osc_recv, log, reaper, cold=a.cold)
        presets = root / "presets"
        base = f"http://127.0.0.1:{port}"
        bridge_log = (work / "bridge.log").open("w", encoding="utf-8")
        bridge_p = subprocess.Popen([sys.executable, "-m", "uvicorn", "bridge.app:app", "--host", "127.0.0.1",
                                     "--port", str(port)], cwd=root, env=env, stdout=bridge_log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while True:
            if bridge_p.poll() is not None:
                raise RuntimeError("bridge exited: " + (work / "bridge.log").read_text(encoding="utf-8", errors="replace")[-3000:])
            try:
                if http(base, "/api/health", timeout=1).get("ok"):
                    break
            except (URLError, OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("bridge not ready after 60 s")
            time.sleep(0.3)
        log(f"bridge: {base}")
        reaper_log = (work / ("engine.log" if golem_engine else "reaper.log")).open("a", encoding="utf-8")
        if golem_engine:            # le lanceur de start.sh (provision/lib-engine.sh) : run.sh écrit presets/.engine.pid
            reaper_p = subprocess.Popen(["bash", str(reaper), str(root), env["GOLEM_ENGINE_SESSION"],
                                         env["GOLEM_ENGINE_BACKEND"], env.get("GOLEM_ENGINE_DEVICE", "")],
                                        env=env, stdout=reaper_log, stderr=subprocess.STDOUT)
        else:
            reaper_p = subprocess.Popen([str(reaper), "-newinst", "-nosplash", "-cfgfile", str(resource / "reaper.ini"), "-new"],
                                        env={**os.environ, "GOLEM_RUNTIME_DIR": str(runtime)}, stdout=reaper_log, stderr=subprocess.STDOUT)
        deadline, last_note = time.monotonic() + a.boot, 0
        while True:
            st = http(base, "/api/state")
            if st.get("reaper_connected"):
                break
            # le Golem Engine ne parle en OSC qu'à un changement : son veilleur prêt + le bridge qui le voit suffisent
            if golem_engine and st.get("reaper_running") and "démarré. surveille" in (
                    (presets / ".watch.log").read_text(errors="replace") if (presets / ".watch.log").exists() else ""):
                break
            if reaper_p.poll() is not None:
                raise RuntimeError(f"REAPER exited with {reaper_p.returncode}")
            if time.monotonic() > deadline:
                lua = read_json(presets / ".clock.json")
                raise RuntimeError(f"REAPER never spoke to the bridge in {a.boot} s "
                                   f"(watch log: {(presets / '.watch.log').read_text(errors='replace')[-1500:] if (presets / '.watch.log').exists() else 'absent'}; clock: {lua})")
            if time.monotonic() - last_note > 20:
                last_note = time.monotonic()
                scan = resource / "reaper-vstplugins64.ini"
                log(f"  waiting for REAPER… (plugin inventory: {scan.stat().st_size if scan.exists() else 0} bytes)")
            time.sleep(0.5)
        log(f"{'Golem Engine' if golem_engine else 'REAPER'} {reaper_p.pid} connected after {round(time.monotonic() - t_start)} s")
        # le bridge rappelle lui-même son premier preset (bank0) : on le laisse finir avant de prendre la main
        wait_rig(base, presets, 30)
        if a.standard_take:
            r = check_patch(base, presets, {"id": STD_PATCH, "name": "CI standard take"}, a.timeout, log)
            report["patches"].append(r)
            log(f"  {r['verdict']:7}{STD_PATCH}" + "".join("\n           " + x for x in r.get("issues") or r.get("needs") or []))
            report["standard_take"] = []
            if r["verdict"] == "ok":
                ref = riff_reference_round(base, root, 60)
                report["riff_reference"] = ref
                log(("  ok     " if not ref["issues"] else "  FAIL   ") + f"riff click (reference): {ref.get('offset_ms')} ms in the file"
                    + "".join("\n           " + x for x in ref["issues"]))
                for n in range(a.standard_take if not ref["issues"] else 0):
                    for parts in ("bass", "drums") + (("loop",) if n == 0 else ()):
                        time.sleep(3)
                        t = standard_take_round(base, root, n, 60, ref, parts)
                        report["standard_take"].append(t)
                        log(("  ok     " if not t["issues"] else "  FAIL   ") + f"take {n + 1} ({parts}): "
                            + ("tick 0 sounds" if t.get("sound_at_0") else f"{t.get('vs_riff_ms')} ms from the riff's click")
                            + (f", chorus 2 rms {t['chorus2_rms']}" if "chorus2_rms" in t else "")
                            + (f" ({t['vs_riff_samples']} samples)" if "vs_riff_samples" in t else "")
                            + f" · grid started at transport {t.get('start')}"
                            + "".join("\n           " + x for x in t["issues"]))
        if a.compo_bed:
            r = check_patch(base, presets, {"id": STD_PATCH, "name": "CI standard take"}, a.timeout, log)
            report["patches"].append(r)
            log(f"  {r['verdict']:7}{STD_PATCH}" + "".join("\n           " + x for x in r.get("issues") or r.get("needs") or []))
            report["compo_bed"] = compo_bed_rounds(base, root, a.compo_bed, bmeta, log) if r["verdict"] == "ok" else []
        patches = [] if a.standard_take or a.compo_bed else http(base, "/api/patches").get("patches") or []
        if not a.all:
            patches = [p for p in patches if p.get("factory") or p.get("id") in (FIXTURE_ID, ENGINE_FIXTURE_ID)]
        if a.only:
            patches = [p for p in patches if a.only in p["id"]]
        if a.limit:
            patches = patches[:a.limit]
        log(f"{len(patches)} patches to materialize")
        ctx = None
        if a.render:
            golden = read_json(a.golden, {}) or {}
            if a.di == "auto":
                di = None                          # choisie par patch (render_patch), comme les démos par scène
            else:
                di = make_di(work / "di.wav") if not a.di else (Path(a.di) if Path(a.di).is_file()
                                                                 else ROOT / "library" / "di-refs" / f"{a.di}.wav")
                if not di.is_file():
                    raise SystemExit(f"--di: {di} not found")
                di = di.resolve()
            ctx = {"base": base, "root": root, "env": env, "work": work, "di": di, "di_auto": a.di == "auto", "render": True,
                   "real_di": bool(a.di),
                   "engine_dir": a.engine_dir.resolve() if golem_engine else None,
                   "against": a.against.resolve() if a.against else None,
                   "render_scenes": a.render_scenes, "golden": golden, "update_golden": a.update_golden,
                   "tol_env": a.tol_env, "tol_band": a.tol_band, "render_timeout": a.render_timeout}
            log(f"renders: DI {ctx['di'].name if ctx['di'] else 'per patch (genre tags)'}, references {a.golden} ({sum(len(v) for v in golden.values())} scenes known)"
                + (" — UPDATING" if a.update_golden else ""))
        if a.fetch:
            # le bridge tire les modèles d'UN preset à la fois (blockstatus.fetch) : patch après patch
            for p in patches:
                try:
                    started = http(base, "/api/blocks/fetch", {"preset": "patch:" + p["id"]}, timeout=30).get("started")
                except Exception as e:
                    log(f"  fetch {p['id']}: {e}"); continue
                if not started:
                    continue
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline and http(base, "/api/blocks/fetch").get("running"):
                    time.sleep(2)
                fs = http(base, "/api/blocks/fetch")
                log(f"  fetch {p['id']}: {len(fs.get('done') or [])} downloaded, {len(fs.get('failed') or [])} failed"
                    + ("" if not fs.get("failed") else " — " + "; ".join(f"{f['block']}: {f['why']}" for f in fs["failed"][:3])))
        for p in patches:
            r = check_patch(base, presets, p, a.timeout, log, ctx)
            report["patches"].append(r)
            mark = {"ok": "  ok     ", "fail": "  FAIL   ", "skipped": "  skip   "}[r["verdict"]]
            extra = r.get("needs") or r.get("issues") or []
            rend = " · ".join(f"{x['scene']}:{x['status']}" for x in r.get("renders") or [])
            log(f"{mark}{p['id']:34} {r.get('blocks', '')!s:>3} {r.get('scene', '')} {rend}" +
                ("" if not extra else "\n" + "\n".join("           " + x for x in extra)))
        pool = [p for p, r in zip(patches, report["patches"]) if r["verdict"] == "ok"]
        if a.chain and len(pool) > 1:
            import random
            rng = random.Random(a.seed)
            report["chain"] = []
            log(f"chain: {a.chain} series over {len(pool)} patches (seed {a.seed})")
            for n in range(a.chain):
                errs = presets / ".lua-errors.log"
                gestures, issues = chain_round(base, presets, pool, rng, reaper_p, a.timeout,
                                               errs.stat().st_size if errs.exists() else 0)
                report["chain"].append({"gestures": gestures, "issues": issues})
                log(("  ok     " if not issues else "  FAIL   ") + f"series {n + 1}: " + " → ".join(gestures)
                    + ("" if not issues else "\n" + "\n".join("           " + x for x in issues)))
                if reaper_p.poll() is not None:
                    break
        if a.real_card and golem_engine:
            sc = soundcard_round(base, presets, log, env["GOLEM_ALSA_CARD"])
            report["soundcard"] = sc
            log(("  ok     " if not sc else "  FAIL   ") + "the engine on the real card"
                + "".join("\n           " + x for x in sc))
        if a.dashboard and golem_engine:
            di = dashboard_round(base, presets, log)
            report["dashboard"] = di
            log(("  ok     " if not di else "  FAIL   ") + "dashboard reads the engine"
                + "".join("\n           " + x for x in di))
        if a.kill_restart and golem_engine:
            ki = kill_restart_round(base, presets, log)
            report["kill_restart"] = ki
            log(("  ok     " if not ki else "  FAIL   ") + "engine killed and restarted"
                + "".join("\n           " + x for x in ki))
    finally:
        if golem_engine and root:                 # le moteur relancé par le bridge n'est pas reaper_p : son PID
            with contextlib.suppress(OSError, TypeError):
                os.kill(engine_pid(root / "presets"), 15)
        kill(reaper_p); kill(bridge_p)
        for name in (".watch.log", ".lua-errors.log", ".rig-check.json", ".livemap.json", ".rig-plugins.json"):
            src = (root / "presets" / name) if root else None
            if src and src.exists():
                shutil.copy2(src, work / name.lstrip("."))
        if root and not a.keep:
            drop_root(root)
    done = [r for r in report["patches"] if r["verdict"] != "skipped"]
    bad = ([r for r in done if r["verdict"] == "fail"] + [c for c in report.get("chain") or [] if c["issues"]]
           + ([{"kill_restart": report["kill_restart"]}] if report.get("kill_restart") else [])
           + ([{"dashboard": report["dashboard"]}] if report.get("dashboard") else [])
           + ([{"soundcard": report["soundcard"]}] if report.get("soundcard") else [])
           + [t for t in report.get("standard_take") or [] if t["issues"]]
           + [t for t in report.get("compo_bed") or [] if t["issues"]]
           + ([report["riff_reference"]] if (report.get("riff_reference") or {}).get("issues") else []))
    if a.standard_take and len(report.get("standard_take") or []) < 2 * a.standard_take + 1:
        bad.append("standard takes not run")
    if a.compo_bed and len(report.get("compo_bed") or []) < a.compo_bed + 4:
        bad.append("bed takes not run")
    report.update({"verified": len(done), "failed": len(bad), "skipped": len(report["patches"]) - len(done),
                   "seconds": round(time.monotonic() - t_start)})
    if a.update_golden and ctx:
        a.golden.parent.mkdir(parents=True, exist_ok=True)
        a.golden.write_text(json.dumps(ctx["golden"], indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        report["golden_written"] = str(a.golden)
        log(f"references written: {a.golden}")
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"{len(done)} patches materialized, {len(bad)} failed, {report['skipped']} skipped, {report['seconds']} s"
        + (f" — logs kept in {work}" if a.keep else ""))
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if bad or not done else 0


if __name__ == "__main__":
    sys.exit(main())
