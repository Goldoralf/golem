#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""golem EN USAGE, comme un testeur (docs/quality-automation.md §9) : l'interface, cliquée par Playwright, sur un banc
jetable — jamais le rack de la machine.

Le banc : le même que tools/check-rig-materialize.py — un `git worktree` (le contenu d'USINE seul : ni les presets ni
les patches de la machine, pour qu'une passe se rejoue à l'identique), un REAPER isolé en audio factice, un bridge
jetable sur des ports libres. Ici les écritures NE SONT PAS interceptées : on crée, on efface, on rappelle, on
enregistre — le banc est fait pour ça, il part à la fin.

Trois passes, dans l'ordre :
  1. les PARCOURS (tools/use/journeys.py) : ce qu'un musicien fait, page par page, avec le contenu d'usine — rappeler
     un patch, changer de scène, poser un setlist au pied, éditer un preset dans le Designer, parcourir la Library,
     chaque onglet de Settings, le Companion ;
  2. le SINGE (--monkey N) : N gestes tirés au hasard (graine --seed : la même suite à chaque fois) sur ce qui est
     cliquable à l'écran — boutons, liens, champs remplis de texte absurde, menus — y compris ce qui n'a pas de sens ;
     seuls les gestes qui tueraient le banc (arrêter golem, redémarrer, verrouiller, mettre à jour…) sont écartés ;
  3. le SON (--audio, défaut) : aux points de contrôle des parcours, la DI de banc rendue à travers le preset posé —
     silence, saturation numérique, valeurs non finies, et la référence tests/golden/renders.json si elle existe.

Après CHAQUE geste, les oracles : erreur JavaScript ou console, réponse 5xx de l'API, ERROR/Traceback dans le journal
du bridge, erreur Lua, REAPER mort, page qui défile, texte français, marque mal écrite, geste qui ne rend pas la main.
Et à chaque écran, des mesures d'UX : cibles tactiles trop petites, texte tronqué, commandes qui se chevauchent ou
sortent de l'écran. Tout va dans --out : report.html (les manquements d'abord, chaque geste avec sa capture),
report.json, steps.jsonl (rejouable), les captures et les rendus audio.

    python tools/check-use.py                         # parcours + 200 gestes du singe + son
    python tools/check-use.py --monkey 1000 --seed 7  # une autre suite, plus longue
    python tools/check-use.py --only live,songs       # les parcours de ces hubs seulement
    python tools/check-use.py --serve                 # monte le banc et le garde ouvert (explorer à la main)

Code 1 si un oracle a vu un manquement. Rien ne joue sur la machine : audio factice, aucune carte son touchée."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RIG = _load("golem_check_rig", ROOT / "tools" / "check-rig-materialize.py")      # le banc et le rendu de la DI
UI = _load("golem_check_ui", ROOT / "tools" / "check-ui.py")                     # les détecteurs (français, marque)
# le contenu local que le banc copie : les MODÈLES et les IR (jamais dans git), pas les presets ni les patches de la
# machine — une passe doit se rejouer à l'identique ailleurs
BENCH_CONTENT = tuple(x for x in RIG.LOCAL_CONTENT if x not in ("library/patches", "presets"))


class Bench:
    """Le golem jetable : worktree + REAPER isolé (audio factice) + bridge. `with Bench(...) as b:` → b.base."""

    def __init__(self, work, log, reaper=None, boot=300, rev="HEAD", keep=False):
        self.work, self.log, self.boot, self.rev, self.keep = Path(work), log, boot, rev, keep
        self.reaper = Path(reaper or RIG.reaper_binary()).resolve()
        self.root = self.bridge_p = self.reaper_p = None

    def __enter__(self):
        self.work.mkdir(parents=True, exist_ok=True)
        saved = RIG.LOCAL_CONTENT
        RIG.LOCAL_CONTENT = BENCH_CONTENT
        try:
            self.root = RIG.make_root(self.work, self.log, rev=self.rev)
        finally:
            RIG.LOCAL_CONTENT = saved
        resource, runtime = self.work / "REAPER", self.work / "runtime"
        runtime.mkdir(exist_ok=True)
        self.port, osc_send, osc_recv = RIG.free_port(), RIG.free_port(), RIG.free_port()
        self.env = {**os.environ, "GOLEM_RUNTIME_DIR": str(runtime), "GOLEM_REAPER_RESOURCE_DIR": str(resource),
                    "GOLEM_PORT": str(self.port), "GOLEM_OSC_SEND": str(osc_send), "GOLEM_OSC_RECV": str(osc_recv),
                    "GOLEM_NO_REACH": "1", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "GOLEM_NO_HW_MIDI": "1", "GOLEM_BENCH_CARD": "golem-bench"}
        RIG.py_in_root(self.root, self.env, "from bridge import factory; factory.seed()")
        self.log("factory content seeded")
        RIG.prepare_reaper(self.root, resource, self.env, osc_send, osc_recv, self.log, self.reaper)
        self.base = f"http://127.0.0.1:{self.port}"
        self.bridge_log = self.work / "bridge.log"
        self.bridge_p = subprocess.Popen([sys.executable, "-m", "uvicorn", "bridge.app:app", "--host", "127.0.0.1",
                                          "--port", str(self.port)], cwd=self.root, env=self.env,
                                         stdout=self.bridge_log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 60
        while True:
            if self.bridge_p.poll() is not None:
                raise RuntimeError("bridge exited: " + self.bridge_log.read_text(errors="replace")[-3000:])
            try:
                if RIG.http(self.base, "/api/health", timeout=1).get("ok"):
                    break
            except (URLError, OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("bridge not ready after 60 s")
            time.sleep(0.3)
        self.reaper_p = subprocess.Popen([str(self.reaper), "-newinst", "-nosplash", "-cfgfile", str(resource / "reaper.ini"), "-new"],
                                         env={**os.environ, "GOLEM_RUNTIME_DIR": str(runtime)},
                                         stdout=(self.work / "reaper.log").open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
        deadline = time.monotonic() + self.boot
        while not RIG.http(self.base, "/api/state").get("reaper_connected"):
            if self.reaper_p.poll() is not None:
                raise RuntimeError(f"REAPER exited with {self.reaper_p.returncode}")
            if time.monotonic() > deadline:
                raise RuntimeError(f"REAPER never spoke to the bridge in {self.boot} s")
            time.sleep(0.5)
        RIG.wait_rig(self.base, self.root / "presets", 30)
        self.log(f"bench up: {self.base}/app/ (REAPER {self.reaper_p.pid})")
        return self

    def alive(self):
        """None si tout tourne, sinon ce qui est mort."""
        if self.bridge_p.poll() is not None:
            return f"the bridge died (exit {self.bridge_p.returncode})"
        if self.reaper_p.poll() is not None:
            return f"REAPER died (exit {self.reaper_p.returncode})"
        return None

    def __exit__(self, *exc):
        RIG.kill(self.reaper_p)
        RIG.kill(self.bridge_p)
        if self.root:
            for name in (".watch.log", ".lua-errors.log", ".rig-check.json", ".livemap.json"):
                src = self.root / "presets" / name
                if src.exists():
                    shutil.copy2(src, self.work / name.lstrip("."))
            if not self.keep:
                RIG.drop_root(self.root)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / ".cache" / "use-check", help="le rapport et les captures")
    ap.add_argument("--work", type=Path, help="dossier du banc (défaut : temporaire)")
    ap.add_argument("--reaper", type=Path, help="binaire REAPER (défaut : comme check-rig-materialize)")
    ap.add_argument("--seed", type=int, default=0, help="graine du singe (défaut 0 : la même suite à chaque fois)")
    ap.add_argument("--monkey", type=int, default=200, help="gestes du singe (0 : aucun)")
    ap.add_argument("--only", help="les parcours de ces hubs seulement (live,songs,designer,library,settings,companion)")
    ap.add_argument("--no-audio", action="store_true", help="ne pas rendre la DI aux points de contrôle")
    ap.add_argument("--working-tree", action="store_true", help="le banc sur l'arbre de travail (changements non commités)")
    ap.add_argument("--keep", action="store_true", help="garder le banc (journaux REAPER, bridge, Lua)")
    ap.add_argument("--serve", action="store_true", help="monter le banc et le garder ouvert jusqu'à Ctrl-C")
    ap.add_argument("--headed", action="store_true", help="voir le navigateur")
    a = ap.parse_args()
    log = lambda *s: print(*s, flush=True)
    work = (a.work or Path(tempfile.mkdtemp(prefix="golem-use-"))).resolve()
    rev = RIG.working_tree_commit() if a.working_tree else "HEAD"
    import signal
    # arrêté par un outil (SIGTERM) : on sort par le `with`, qui arrête REAPER et le bridge et retire le worktree —
    # sinon une passe coupée laissait son worktree dans `git worktree list`
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with Bench(work, log, reaper=a.reaper, rev=rev, keep=a.keep) as bench:
        if a.serve:
            (work / "bench.json").write_text(json.dumps({"base": bench.base, "root": str(bench.root), "work": str(work)}))
            log(f"serving — {bench.base}/app/  (bench.json in {work}; Ctrl-C to stop)")
            try:
                while not bench.alive():
                    time.sleep(1)
                log(bench.alive())
            except KeyboardInterrupt:
                pass
            return 0
        from use import runner
        code = runner.run(bench, a, log, UI, RIG)
    if not (a.keep or a.serve):
        shutil.rmtree(work, ignore_errors=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
