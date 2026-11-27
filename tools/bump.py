#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""MONTER UNE ÉPINGLE, d'un seul geste (docs/release-tool-plan.md §4, docs/release-checklist.md A1-A2, 2026-11-27).

Une version épinglée vit dans plusieurs fichiers (golem-fx : dix). À la main, on en oublie un — `install-golem-fx.sh`
gardait sa copie du numéro, l'essai à blanc de l'installateur disait « 9.9-g1 » sous une épingle à 9.9-g8. Cet outil
télécharge les archives de la version demandée, RECALCULE leurs empreintes, les compare au SHA256SUMS de la release quand
elle en publie un, puis écrit TOUS les fichiers de l'épingle. Tout ou rien : une empreinte qui ne correspond pas, un
fichier dont la forme a changé (le motif attendu ne s'y trouve pas exactement une fois), et rien n'est écrit.

    tools/bump.py golem-fx 0.8.3
    tools/bump.py golem-engine 9.9-g9 [--system linux|windows|both]
    tools/bump.py reaper 7.86 --played-on-rig      # REAPER se JOUE au rig avant d'être épinglé : l'outil le demande
    tools/bump.py factory-demos factory-demos-v5
    tools/bump.py dexed 1.1.1
    tools/bump.py surge 1.3.5
    … --dry-run                                     # télécharge et vérifie, dit ce qui changerait, n'écrit rien

Il ne commite pas, ne lance pas les tests, ne publie rien. À la fin il dit ce qui reste à la main : les lignes d'histoire
des docs, les tests qui citent l'ancienne version, les bancs à refaire. `tests/test_pins_coherent.py` et
`tools/snapshot.py` disent ensuite si tout se tient.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = "https://github.com/Goldoralf/golem-binaries/releases/download"


class Refused(Exception):
    """L'épingle ne peut pas être montée : rien n'a été écrit."""


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "golem-bump"})
    with urllib.request.urlopen(req, timeout=300) as r:        # noqa: S310 — adresses construites ici
        return r.read()


class Plan:
    """Les fichiers à réécrire, en mémoire jusqu'au bout : tout ou rien."""

    def __init__(self, root=ROOT, fetch=None, today=None):
        self.root = Path(root)
        self.fetch = fetch or _fetch
        self.today = today or time.strftime("%Y-%m-%d")
        self.files = {}          # chemin relatif -> nouveau texte
        self.done = []           # ce qui a été vérifié (dit à la fin)
        self.todo = []           # ce qui reste à la main
        self.old = None          # l'ancienne version (pour chercher ce qui la cite encore)
        self.sync = []           # les outils à lancer après l'écriture (golem-fx : manifeste et presets)

    def text(self, rel):
        if rel not in self.files:
            self.files[rel] = (self.root / rel).read_text(encoding="utf-8")
        return self.files[rel]

    def sub(self, rel, pattern, repl, flags=re.M):
        """Remplace UNE occurrence exactement : un fichier dont la forme a changé arrête tout."""
        new, n = re.subn(pattern, lambda m: repl(m) if callable(repl) else repl, self.text(rel), flags=flags)
        if n != 1:
            raise Refused(f"{rel}: expected the pattern once, found it {n} time(s) — the file changed shape, edit bump.py")
        self.files[rel] = new

    def json_edit(self, rel, fn):
        raw = self.text(rel)
        data = json.loads(raw)
        indent = next((i for i in (1, 2, 4) if json.dumps(data, indent=i, ensure_ascii=False) + "\n" == raw), None)
        if indent is None:
            raise Refused(f"{rel}: cannot keep its JSON layout")
        fn(data)
        self.files[rel] = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"

    def download(self, url, want=None, what=""):
        """Télécharge, rend l'empreinte ; la compare à `want` (le SHA256SUMS de la release) quand il y en a un."""
        try:
            data = self.fetch(url)
        except Exception as e:
            raise Refused(f"cannot download {url} ({e})") from e
        got = hashlib.sha256(data).hexdigest()
        if want and got != want:
            raise Refused(f"{what or url}: the downloaded file is {got}, the release's SHA256SUMS says {want}")
        self.done.append(f"{what or url.rsplit('/', 1)[-1]}: sha256 {got[:12]}… "
                         + ("= the release's SHA256SUMS" if want else "(the publisher gives no checksum: HTTPS only)"))
        return got

    def sums(self, base):
        try:
            text = self.fetch(base + "/SHA256SUMS").decode("utf-8", "replace")
        except Exception as e:
            raise Refused(f"cannot read {base}/SHA256SUMS ({e}) — is the release published?") from e
        return {p[1].lstrip("*"): p[0] for p in (ln.split() for ln in text.splitlines()) if len(p) == 2}

    def buildinfo(self, base):
        try:
            return self.fetch(base + "/BUILDINFO.txt").decode("utf-8", "replace")
        except Exception:
            return ""

    def changed(self):
        return {rel: txt for rel, txt in self.files.items() if (self.root / rel).read_text(encoding="utf-8") != txt}

    def write(self):
        for rel, txt in self.changed().items():
            (self.root / rel).write_text(txt, encoding="utf-8")


def _const(plan, rel, name):
    m = re.search(rf'^{name}\s*=\s*"([^"]+)"', plan.text(rel), re.M)
    return m.group(1) if m else None


# ── golem-fx ────────────────────────────────────────────────────────────────────────────────────────────────────────
FX_ASSETS = {"linux": "golem-fx-linux-x86_64.tar.gz", "windows": "golem-fx-windows-x86_64.zip",
             "macos": "golem-fx-macos-universal.tar.gz"}


def bump_golem_fx(plan, ver, fx_repo=None, run=subprocess.run):
    plan.old = _const(plan, "provision/golem_fx.py", "VERSION")
    base = f"{BIN}/golem-fx-{ver}"
    sums, info = plan.sums(base), plan.buildinfo(base)
    m = re.search(r"golem-fx ([0-9a-f]{40})", info)
    n = re.search(r"(\d+) VST3", info)
    if not m:
        raise Refused(f"golem-fx-{ver}: BUILDINFO.txt does not say which commit was built")
    commit, count = m.group(1), n.group(1) if n else "?"
    sha = {}
    for system, asset in FX_ASSETS.items():
        if asset not in sums:
            raise Refused(f"golem-fx-{ver}: {asset} is not in the release's SHA256SUMS")
        sha[system] = plan.download(f"{base}/{asset}", sums[asset], asset)
    why = f"golem-fx {commit[:7]} ; empreinte recalculée sur l'archive téléchargée et comparée au SHA256SUMS de la release, {plan.today}"
    plan.sub("provision/golem_fx.py", r'^VERSION = "[^"]+"', f'VERSION = "{ver}"')
    plan.sub("provision/downloads.sha256",
             r"# golem-fx \(les effets de golem, GPL-3\) — release golem-fx-.*?\n[0-9a-f]{64}  \S+/golem-fx-linux-x86_64\.tar\.gz",
             f"# golem-fx (les effets de golem, GPL-3) — release golem-fx-{ver} de Goldoralf/golem-binaries ({why}) ;\n"
             "# provision/install-golem-fx.sh. Windows et macOS : leurs pins.json (clé golem_fx).\n"
             f"{sha['linux']}  {base}/{FX_ASSETS['linux']}", flags=re.S)
    for system in ("windows", "macos"):
        def edit(d, system=system):
            g = d["golem_fx"]
            g["version"], g["url"], g["sha256"] = ver, f"{base}/{FX_ASSETS[system]}", sha[system]
            tail = g["_comment"][g["_comment"].index("Posés par"):] if "Posés par" in g["_comment"] else ""
            g["_comment"] = (f"golem-fx (les effets de golem, GPL-3) : {count} VST3 « GoleM FX <Nom>.vst3 » à la racine de "
                             f"l'archive, release golem-fx-{ver} de Goldoralf/golem-binaries ({why}). {tail}").strip()
        plan.json_edit(f"provision/{system}/pins.json", edit)

    def comp(d):
        c = next(c for c in d["components"] if c["id"] == "golem-fx")
        c["version"], c["url"] = ver, f"https://github.com/Goldoralf/golem-binaries/releases/tag/golem-fx-{ver}"
    plan.json_edit("provision/components.json", comp)
    plan.sub("docs/installer.md", r"`golem-fx-[\w.]+` in Goldoralf/golem-binaries since \d{4}-\d\d-\d\d, \d+",
             f"`golem-fx-{ver}` in Goldoralf/golem-binaries since {plan.today}, {count}")
    # le manifeste des paramètres et les presets viennent du dépôt golem-fx AU TAG : sans lui, à faire à la main
    repo = Path(fx_repo) if fx_repo else Path.home() / "code" / "golem-fx"
    at = run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True)
    if at.returncode == 0 and at.stdout.strip() == commit:
        plan.sync = [[sys.executable, str(plan.root / "tools" / "sync-golem-fx-manifest.py"), "--from", str(repo)],
                     [sys.executable, str(plan.root / "tools" / "sync-golem-fx-presets.py"), "--from", str(repo)]]
    else:
        plan.todo.append(f"check out golem-fx at {ver} ({commit[:7]}) in {repo}, then run tools/sync-golem-fx-manifest.py "
                         "and tools/sync-golem-fx-presets.py (the parameter manifest must come from the pinned commit)")
    plan.todo += ["docs/golem-fx-migration.md and docs/golem-fx-reaper.md: add the history line of this version",
                  "a golem already installed moves to it by itself at its next start (update.md §3 bis): say so in the notes"]


# ── Golem Engine ────────────────────────────────────────────────────────────────────────────────────────────────────
def bump_golem_engine(plan, ver, system="both"):
    plan.old = _const(plan, "provision/golem_engine.py", "VERSION")
    base = f"{BIN}/golem-engine-{ver}"
    sums, info = plan.sums(base), plan.buildinfo(base)
    m = re.search(r"golem-engine ([0-9a-f]{40})", info)
    commit = m.group(1)[:9] if m else "?"
    if system in ("linux", "both"):
        asset = "golem-engine-linux-x86_64.tar.gz"
        if asset not in sums:
            raise Refused(f"golem-engine-{ver}: no Linux asset in the release")
        sha = plan.download(f"{base}/{asset}", sums[asset], asset)
        plan.sub("provision/golem_engine.py", r'^VERSION = "[^"]+"', f'VERSION = "{ver}"')
        plan.sub("provision/downloads.sha256",
                 r"# Golem Engine \(le moteur audio de golem.*?\n[0-9a-f]{64}  \S+/golem-engine-linux-x86_64\.tar\.gz",
                 f"# Golem Engine (le moteur audio de golem, construit depuis Ardour, GPL-2.0-or-later) — release golem-engine-{ver} de\n"
                 f"# Goldoralf/golem-binaries (golem-engine {commit} ; empreinte recalculée sur l'archive téléchargée et comparée au\n"
                 f"# SHA256SUMS de la release, {plan.today}) ; provision/install-golem-engine.sh, provision/golem_engine.py.\n"
                 f"{sha}  {base}/{asset}", flags=re.S)
    if system in ("windows", "both"):
        asset = "golem-engine-windows-x86_64.tar.gz"
        if asset not in sums:
            if system == "windows":
                raise Refused(f"golem-engine-{ver}: no Windows asset in the release (it is uploaded by hand from the dev box)")
            plan.todo.append(f"golem-engine-{ver} has no Windows asset yet: Windows keeps its pin (upload it, then "
                             f"tools/bump.py golem-engine {ver} --system windows)")
        else:
            sha = plan.download(f"{base}/{asset}", sums[asset], asset)

            def edit(d):
                g = d["golem_engine"]
                g["version"], g["url"], g["sha256"] = ver, f"{base}/{asset}", sha
                g["_comment"] = re.sub(r"golem-engine-\d+\.\d+-g\d+", f"golem-engine-{ver}", g.get("_comment", ""))
            plan.json_edit("provision/windows/pins.json", edit)
    plan.todo += ["run the engine benches on the pinned package, nobody playing (docs/linux-pass-2026-11.md §2: "
                  "tools/check-engine-ardour.py --engine-dir <package>, 5 runs)",
                  "an installed engine moves to it at the next start (update.md §3 bis); a dev tree does not: rebuild it"]


# ── REAPER ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def bump_reaper(plan, ver, played=False):
    if not re.fullmatch(r"\d+\.\d+", ver):
        raise Refused(f"REAPER version {ver!r}: expected major.minor (7.86)")
    if not played:
        raise Refused(f"REAPER {ver} must be PLAYED on the rig before it is pinned: install it on the rack (Settings ▸ About ▸ "
                      "REAPER ▸ Install), play a patch, change scenes, press a stomp, record and play back a take. Then run "
                      "this again with --played-on-rig.")
    m = re.search(r"REAPER_VERSION:-([\d.]+)", plan.text("provision/install-reaper.sh"))
    plan.old = m.group(1) if m else None
    plan.also = [f"reaper{plan.old.replace('.', '')}"] if plan.old else []      # le nom de ses fichiers : reaper779_…
    major, flat = ver.split(".")[0], ver.replace(".", "")
    urls = {"linux": f"https://www.reaper.fm/files/{major}.x/reaper{flat}_linux_x86_64.tar.xz",
            "windows": f"https://www.reaper.fm/files/{major}.x/reaper{flat}_x64-install.exe",
            "macos": f"https://www.reaper.fm/files/{major}.x/reaper{flat}_universal.dmg"}
    sha = {k: plan.download(u) for k, u in urls.items()}
    plan.sub("provision/install-reaper.sh", r"REAPER_VERSION:-[\d.]+", f"REAPER_VERSION:-{ver}")
    plan.sub("provision/install-reaper.sh", r"REAPER_SHA256:-[0-9a-f]{64}", f"REAPER_SHA256:-{sha['linux']}")
    for system in ("windows", "macos"):
        def edit(d, system=system):
            d["reaper"].update(version=ver, url=urls[system], sha256=sha[system])
        plan.json_edit(f"provision/{system}/pins.json", edit)
    plan.todo += ["Cockos publishes no checksum: these hashes are those of today's downloads, protected by HTTPS only",
                  "Windows and macOS: the same version must be tried there before the release (the pins moved for the three systems)"]


# ── les démos d'usine ───────────────────────────────────────────────────────────────────────────────────────────────
def bump_factory_demos(plan, tag):
    if not re.fullmatch(r"factory-demos-v\d+", tag):
        raise Refused(f"{tag!r}: expected factory-demos-vN")
    m = re.search(r'^TAG = "([^"]+)"', plan.text("bridge/factory_demos.py"), re.M)
    plan.old = m.group(1) if m else None
    try:
        idx = json.loads(plan.fetch(f"{BIN}/{tag}/golem-factory-demos.json"))
    except Exception as e:
        raise Refused(f"cannot read the index of {tag} ({e}) — is it published?") from e
    head = idx.get("header") or idx
    plan.done.append(f"{tag}: rendered with golem-fx {head.get('golem_fx_version')} · catalogue {head.get('catalog_version')} "
                     f"· rack {str(head.get('rack_commit'))[:8]}")
    plan.sub("bridge/factory_demos.py", r'^TAG = "[^"]+"', f'TAG = "{tag}"')
    plan.todo += [f"send golem.fm the tag {tag} and the archive's sha256 (it serves the same release)",
                  "reload the bridge (./provision/reload.sh): a running golem keeps the old tag until then"]


# ── Dexed, Surge XT : la même version sous Linux (un script) et sous Windows (un module Python) ─────────────────────
def _third(plan, ver, name, sh_file, sh_var, py_file, linux_url, win_url, line_pat):
    m = re.search(rf'^{sh_var}="([^"]+)"', plan.text(sh_file), re.M)
    plan.old = m.group(1) if m else None
    lin, win = plan.download(linux_url), plan.download(win_url)
    plan.sub(sh_file, rf'^{sh_var}="[^"]+"', f'{sh_var}="{ver}"')
    plan.sub(py_file, r'^VERSION = "[^"]+"', f'VERSION = "{ver}"')
    plan.sub(py_file, r'"sha256": "[0-9a-f]{64}"', f'"sha256": "{win}"')
    plan.sub("provision/downloads.sha256", line_pat, f"{lin}  {linux_url}")
    plan.todo += [f"{name}: its publisher gives no checksum file — these are the hashes of today's downloads",
                  f"{name}: play its block on the rig (and run tools/check-block-stall.py for it) before the release"]


def bump_dexed(plan, ver):
    base = f"https://github.com/asb2m10/dexed/releases/download/v{ver}"
    _third(plan, ver, "Dexed", "provision/plugins.sh", "DEXED_VER", "provision/dexed.py", f"{base}/Dexed-{ver}-lnx.zip",
           f"{base}/Dexed-{ver}-win.zip", r"^[0-9a-f]{64}  https://github\.com/asb2m10/dexed/\S+-lnx\.zip$")


def bump_surge(plan, ver):
    base = f"https://github.com/surge-synthesizer/releases-xt/releases/download/{ver}"
    _third(plan, ver, "Surge XT", "provision/install-plugins.sh", "SURGE_VER", "provision/surge.py",
           f"{base}/surge-xt-linux-x64-{ver}.deb", f"{base}/surge-xt-win64-{ver}-pluginsonly.zip",
           r"^[0-9a-f]{64}  https://github\.com/surge-synthesizer/releases-xt/\S+\.deb$")


COMPONENTS = {"golem-fx": bump_golem_fx, "golem-engine": bump_golem_engine, "reaper": bump_reaper,
              "factory-demos": bump_factory_demos, "dexed": bump_dexed, "surge": bump_surge}
NOT_YET = {"nam-lv2": "NAM LV2 carries golem's crash patch (provision/install-nam.sh NAM_COMMIT, provision/patches): a new "
                      "version means rebasing the patch and rebuilding the prebuilt archive in golem-binaries first.",
           "linux-plugins": "a new linux-plugins-vN changes four pinned archives and provision/fetch-prebuilt.sh: build it "
                            "in golem-binaries first, then edit provision/downloads.sha256."}


def leftovers(plan, limit=25):
    """Ce qui cite ENCORE l'ancienne version : à relire, l'outil n'y touche pas. Les TESTS d'abord (un littéral y fait
    échouer la suite), puis le code, puis les docs (souvent une ligne d'histoire, juste telle quelle). `also` : une autre
    forme du même numéro (REAPER : « 779 » dans le nom de ses fichiers)."""
    if not plan.old:
        return []
    forms = [plan.old] + list(getattr(plan, "also", []))
    changed, hits = set(plan.changed()), []
    for form in forms:
        out = subprocess.run(["git", "-C", str(plan.root), "grep", "-n", "-F", form, "--", "provision", "installer", "bridge",
                              "tests", "tools", "app", "docs", "README.md"], capture_output=True, text=True).stdout
        hits += [ln for ln in out.splitlines() if ln.split(":", 1)[0] not in changed and ln not in hits
                 and re.search(rf"(?<![\d.]){re.escape(form)}(?![\d.])", ln)]
    rank = lambda ln: (0 if ln.startswith("tests/") else 2 if ln.startswith("docs/") else 1, ln)   # noqa: E731
    return sorted(hits, key=rank)[:limit]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Move a pinned version: every file, hashes recomputed.")
    ap.add_argument("component", choices=sorted(list(COMPONENTS) + list(NOT_YET)))
    ap.add_argument("version")
    ap.add_argument("--dry-run", action="store_true", help="download and verify, say what would change, write nothing")
    ap.add_argument("--system", choices=("linux", "windows", "both"), default="both", help="golem-engine only")
    ap.add_argument("--played-on-rig", action="store_true", help="reaper only: this version was played on the rig")
    a = ap.parse_args(argv)
    if a.component in NOT_YET:
        print(f"✗ {a.component}: not automated — {NOT_YET[a.component]}", file=sys.stderr)
        return 2
    plan = Plan()
    try:
        if a.component == "golem-engine":
            bump_golem_engine(plan, a.version, a.system)
        elif a.component == "reaper":
            bump_reaper(plan, a.version, a.played_on_rig)
        else:
            COMPONENTS[a.component](plan, a.version)
    except Refused as e:
        print(f"✗ {e}\n  Nothing was written.", file=sys.stderr)
        return 1
    changed = plan.changed()
    print(f"{a.component}: {plan.old or '?'} → {a.version}")
    for d in plan.done:
        print(f"  ✓ {d}")
    if not changed:
        print("  Nothing to change: the files already pin this version.")
    for rel in sorted(changed):
        print(f"  {'would write' if a.dry_run else 'wrote'} {rel}")
    if not a.dry_run:
        plan.write()
        for cmd in plan.sync:
            r = subprocess.run(cmd, capture_output=True, text=True)
            last = (r.stdout.strip().splitlines() or ["?"])[-1]
            print(f"  {'✓' if r.returncode == 0 else '✗'} {Path(cmd[1]).name}: {last}")
    elif plan.sync:
        print("  would run tools/sync-golem-fx-manifest.py and tools/sync-golem-fx-presets.py")
    left = leftovers(plan) if plan.old != a.version else []      # même version : tout la cite, rien à relire
    if left:
        print(f"\nStill quoting {plan.old} — read each one (a test's literal, a doc's history line):")
        for ln in left:
            print(f"  {ln[:170]}")
    print("\nLeft to do by hand:")
    for t in plan.todo + ["run .venv/bin/python -m pytest tests (tests/test_pins_coherent.py first), then tools/snapshot.py"]:
        print(f"  · {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
