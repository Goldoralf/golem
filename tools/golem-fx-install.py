#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installe les VST3 de golem-fx sur CETTE machine, et tient le journal de ce qui est installé.

golem-fx (dépôt séparé) fabrique un VST3 par effet ; la table du Golem Engine
(library/catalog/effects-golem-engine.json, clé `golem_fx`) dit quel bloc il joue. Tant qu'aucun installeur ne les pose,
ils arrivent par cet outil : copiés depuis le dossier de build de golem-fx dans ~/.vst3, notés au reçu d'install
(le désinstalleur les retire), puis le cache VST3 du Golem Engine est rafraîchi (le moteur les voit à son prochain
démarrage). Chaque pose est JOURNALISÉE (~/.local/share/golem/golem-fx-installed.json) : le bundle, le commit de
golem-fx et s'il avait des modifications non commitées, l'empreinte du binaire, la date — un son qui change entre deux
séances se retrouve là (une reconstruction garde le même identifiant de classe).

  ./tools/golem-fx-install.py                       # tous les bundles de golem-fx
  ./tools/golem-fx-install.py "GoleM FX Gate" …     # seulement ceux-là
  ./tools/golem-fx-install.py --list                # le journal : ce qui est installé, depuis quand, de quel commit
Options : --from <dépôt golem-fx> (défaut ~/code/golem-fx), --engine-dir (défaut ~/golem-engine).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = Path.home() / ".local" / "share" / "golem" / "golem-fx-installed.json"


def _sha(bundle):
    """Empreinte du binaire Linux du bundle (Contents/x86_64-linux/*.so)."""
    h = hashlib.sha256()
    for so in sorted((bundle / "Contents" / "x86_64-linux").glob("*.so")):
        h.update(so.read_bytes())
    return h.hexdigest()[:16]


def _git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def load_journal():
    try:
        return json.loads(JOURNAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"installed": {}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bundles", nargs="*", help="noms de bundles (sans .vst3) ; défaut : tous")
    ap.add_argument("--from", dest="src", default=os.path.expanduser("~/code/golem-fx"))
    ap.add_argument("--engine-dir", default=os.environ.get("GOLEM_ENGINE_DIR") or os.path.expanduser("~/golem-engine"))
    ap.add_argument("--list", action="store_true", help="afficher le journal et sortir")
    a = ap.parse_args()

    journal = load_journal()
    if a.list:
        for name, e in sorted(journal["installed"].items()):
            print(f"{name:24s} {e['installed_at']}  golem-fx {e['commit'][:10] if e.get('commit') else '?'}"
                  f"{' (+local changes)' if e.get('dirty') else ''}  so {e['sha']}")
        return 0

    built = Path(a.src) / "target" / "bundled"
    if not built.is_dir():
        raise SystemExit(f"no golem-fx build in {built}")
    names = a.bundles or sorted(p.stem for p in built.glob("*.vst3"))
    commit = _git(a.src, "rev-parse", "HEAD")
    dirty = bool(_git(a.src, "status", "--porcelain", "--untracked-files=no"))
    sys.path.insert(0, str(ROOT / "provision"))
    import receipt                                     # le reçu d'install : le désinstalleur retire ce qu'il liste

    dest = Path.home() / ".vst3"
    dest.mkdir(exist_ok=True)
    installed = []
    for n in names:
        src = built / f"{n}.vst3"
        if not src.is_dir():
            print(f"⚠ {n}: not in {built}")
            continue
        sha = _sha(src)
        prev = journal["installed"].get(n) or {}
        dst = dest / f"{n}.vst3"
        if prev.get("sha") == sha and dst.is_dir():
            print(f"= {n} (unchanged, {sha})")
            continue
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        receipt.add(str(dst), "dir", "tools/golem-fx-install.py", "plugins")
        journal["installed"][n] = {"sha": sha, "commit": commit, "dirty": dirty,
                                   "installed_at": time.strftime("%Y-%m-%d %H:%M"),
                                   "previous": {k: prev.get(k) for k in ("sha", "commit", "installed_at")} if prev else None}
        installed.append(dst)
        print(f"✓ {n}  {prev.get('sha', '—')} → {sha}")
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.write_text(json.dumps(journal, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # le cache VST3 d'Ardour : une seconde après la copie (un cache daté de la même seconde que le plugin est « périmé »)
    scan = Path(a.engine_dir) / "build" / "libs" / "fst" / "ardour-vst3-scanner"
    env_sh = Path(a.engine_dir) / "golem" / "dev" / "env.sh"
    if installed and scan.is_file():
        time.sleep(1.1)
        for dst in installed:
            p = subprocess.run(["bash", "-c", 'source "$0" >/dev/null 2>&1; exec "$@"', str(env_sh), str(scan), "-q", str(dst)],
                               capture_output=True, text=True, timeout=60)
            if p.returncode:
                print(f"⚠ VST3 scan failed for {dst.name}")
    if installed:
        print("The Golem Engine sees new or rebuilt plugins at its next start (System ▸ Dashboard ▸ restart).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
