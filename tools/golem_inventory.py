#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'INVENTAIRE des entités de golem (docs/release-tool-plan.md §3, 2026-11-27) : où en est chacune — ce qui est ICI (le
dépôt ou l'installation de cette machine), ce qui est PUBLIÉ (le dernier tag, la dernière release), ce que golem ÉPINGLE.

Demandé après la v0.7.2, sortie avec le Golem Engine 9.9-g3 sous Linux alors que la g8 était publiée, et REAPER 7.79 alors
que la 7.86 existait : personne ne comparait les épingles à ce qui était publié. Lu par tools/snapshot.py (la page) et, à
venir, par tools/release.py (l'outil de publication guidé).

LIT, NE DEVINE PAS, NE CHANGE RIEN : chaque version vient de sa source (un fichier, un tag, une release GitHub, la page de
l'éditeur), jamais d'une doc. Une lecture qui échoue (pas de réseau, dépôt voisin absent) rend une ligne grise « not
read », jamais une valeur inventée ni une exception.

Chaque lecteur rend une ENTITÉ : {id, name, role, rows: [{label, value, status, note, fix}]}. `status` : ok | warn | bad |
na. `fix` : ce qu'il faut faire, dit à qui lit la page. Les lecteurs reçoivent un `Ctx` dont `sh` (une commande -> son
texte) et `http` (une adresse -> son texte) sont remplaçables : les tests ne touchent ni au réseau ni aux dépôts voisins.

UN RETARD VOULU s'écrit dans provision/pins-held.json : {"<clé>": {"pinned", "latest", "reason", "date"}}. Tant que
l'épingle et la dernière version publiée sont celles notées, la ligne est orange avec sa raison ; dès qu'une version plus
récente sort, elle redevient rouge — une raison ne vaut que pour la version qu'elle a regardée.
"""
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARIES = "Goldoralf/golem-binaries"
GOLEM = "Goldoralf/golem"
ORDER = {"bad": 3, "warn": 2, "ok": 1, "na": 0}


# ── le contexte : où sont les dépôts, comment on lit ────────────────────────────────────────────────────────────────
class Ctx:
    """Les chemins et les deux lectures du monde extérieur. `offline` : aucune lecture réseau (lignes grises)."""

    def __init__(self, root=ROOT, home=None, offline=False, sh=None, http=None, siblings=None):
        self.root = Path(root)
        self.home = Path(home) if home else Path.home()
        self.offline = offline
        self._sh = sh or _run
        self._http = http or _get
        s = siblings or {}
        self.engine_repo = Path(s.get("engine") or self.home / "golem-engine")
        self.fx_repo = Path(s.get("fx") or self.home / "code" / "golem-fx")
        self.fm_repo = Path(s.get("fm") or self.home / "code" / "maestrium")
        self.site_repo = Path(s.get("site") or self.home / "code" / "golem-site")
        self.binaries_repo = Path(s.get("binaries") or self.home / "golem-binaries")
        self._cache = {}

    def sh(self, *cmd, cwd=None, net=False):
        """Le texte d'une commande, ou None (échec, ou réseau demandé en mode hors ligne)."""
        if net and self.offline:
            return None
        key = (cmd, str(cwd))
        if key not in self._cache:
            self._cache[key] = self._sh(list(cmd), cwd)
        return self._cache[key]

    def git(self, repo, *args):
        return self.sh("git", "-C", str(repo), *args) if Path(repo).exists() else None

    def http(self, url):
        if self.offline:
            return None
        if url not in self._cache:
            self._cache[url] = self._http(url)
        return self._cache[url]

    def read(self, *parts):
        try:
            return (self.root.joinpath(*parts)).read_text(encoding="utf-8")
        except OSError:
            return None

    def json(self, path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def _run(cmd, cwd=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=40)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "golem-inventory"})
        with urllib.request.urlopen(req, timeout=15) as r:      # noqa: S310 — adresses fixes de ce fichier
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


# ── petites briques ─────────────────────────────────────────────────────────────────────────────────────────────────
def norm(v):
    """Une version comparable : sans « v » de tête ni préfixe de famille (golem-fx-0.8.2 -> 0.8.2)."""
    v = str(v or "").strip()
    v = re.sub(r"^(golem-fx-|golem-engine-|factory-demos-|linux-plugins-)", "", v)
    return v[1:] if re.match(r"^v\d", v) else v


def short(v):
    """Ce qu'on AFFICHE d'un tag : sans son préfixe de famille, le reste tel quel (factory-demos-v4 -> v4)."""
    return re.sub(r"^(golem-fx-|golem-engine-|factory-demos-|linux-plugins-)", "", str(v or "")) or "?"


def vkey(v):
    """Clé de tri d'une version : ses nombres (9.9-g8 -> (9, 9, 8) ; v4 -> (4,))."""
    return tuple(int(n) for n in re.findall(r"\d+", norm(v)))


def row(label, value, status="na", note="", fix=""):
    return {"label": label, "value": value if value not in (None, "") else "not read", "status": status,
            "note": note, "fix": fix}


def entity(eid, name, role, rows):
    worst = max((r["status"] for r in rows), key=lambda s: ORDER[s], default="na")
    return {"id": eid, "name": name, "role": role, "rows": rows, "status": worst}


def holds(ctx):
    return ctx.json(ctx.root / "provision" / "pins-held.json") or {}


def compare(pinned, latest, key=None, held=None, what="", fix=""):
    """Le statut d'une épingle face à la dernière version publiée. -> (status, note, fix)."""
    if not pinned or not latest:
        return "na", "", ""
    if norm(pinned) == norm(latest) or vkey(pinned) >= vkey(latest):
        return "ok", "", ""
    h = (held or {}).get(key or "")
    if h and norm(h.get("pinned")) == norm(pinned) and norm(h.get("latest")) == norm(latest):
        return "warn", "behind on purpose: " + str(h.get("reason") or "no reason written"), ""
    return "bad", f"{norm(latest)} is published", fix or f"move the {what or 'pin'} to {norm(latest)}"


def releases(ctx):
    """Les releases de golem-binaries : [tag, …] (une seule lecture)."""
    out = ctx.sh("gh", "release", "list", "-R", BINARIES, "-L", "200", "--json", "tagName", net=True)
    try:
        return [r["tagName"] for r in json.loads(out)] if out else []
    except ValueError:
        return []


def latest_of(tags, prefix):
    fam = [t for t in tags if t.startswith(prefix)]
    return max(fam, key=vkey) if fam else None


def pins(ctx, system):
    return ctx.json(ctx.root / "provision" / system / "pins.json") or {}


def _const(text, name):
    """La valeur d'une constante `NAME = "x"` ou `NAME="x"` (Python, shell) dans un texte."""
    m = re.search(rf'^\s*{re.escape(name)}\s*=\s*"?\$?\{{?(?:{re.escape(name)}:-)?([^"\s}}#]+)', text or "", re.M)
    return m.group(1) if m else None


def _repo_state(ctx, repo):
    """(describe, sale: n fichiers, retard sur l'origine: n commits) d'un dépôt voisin ; None s'il est absent."""
    if not Path(repo).exists():
        return None
    desc = ctx.git(repo, "describe", "--tags", "--always")
    dirty = len([ln for ln in (ctx.git(repo, "status", "--porcelain") or "").splitlines() if ln.strip()])
    behind = ctx.git(repo, "rev-list", "--count", "HEAD..@{upstream}")
    return desc, dirty, int(behind) if (behind or "").isdigit() else None


def _state_text(desc, dirty, behind):
    bits = [desc or "?"]
    if dirty:
        bits.append(f"{dirty} file{'s' if dirty > 1 else ''} not committed")
    if behind:
        bits.append(f"{behind} commit{'s' if behind > 1 else ''} behind origin")
    return " · ".join(bits)


# ── golem (le rack) ─────────────────────────────────────────────────────────────────────────────────────────────────
def read_golem(ctx):
    desc, dirty, behind = _repo_state(ctx, ctx.root) or ("?", 0, None)
    last = ctx.git(ctx.root, "describe", "--tags", "--abbrev=0")
    since = ctx.git(ctx.root, "rev-list", "--count", f"{last}..HEAD") if last else None
    head = ctx.git(ctx.root, "rev-parse", "HEAD")
    rows = [row("Here", _state_text(desc, dirty, behind), "warn" if dirty or behind else "ok")]
    if since and since != "0":
        rows.append(row("Not released", f"{since} commit{'s' if since != '1' else ''} since {last}", "warn",
                        fix="the next release carries them"))
    runs = ctx.sh("gh", "run", "list", "-R", GOLEM, "-L", "30", "--json", "headSha,name,conclusion,status", net=True)
    ci = None
    try:
        ci = next((r for r in json.loads(runs or "[]") if r["headSha"] == head and r["name"] == "CI"), None)
    except ValueError:
        pass
    if ci:
        ok = ci.get("conclusion") == "success"
        rows.append(row("CI of HEAD", ci.get("conclusion") or ci.get("status"), "ok" if ok else
                        ("warn" if ci.get("status") != "completed" else "bad"),
                        fix="" if ok or ci.get("status") != "completed" else "fix CI before anything else"))
    else:
        rows.append(row("CI of HEAD", None if runs is None else "no run for this commit", "na" if runs is None else "warn"))
    pub = ctx.sh("gh", "api", f"repos/{GOLEM}/releases/latest", "-q", ".tag_name", net=True)
    rows.append(row("Published", pub and f"{pub} · Latest", "ok" if pub and pub == last else ("na" if not pub else "warn"),
                    note="" if not pub or pub == last else f"the last local tag is {last}"))
    cat = (ctx.json(ctx.root / "library" / "catalog" / "effects.json") or {}).get("catalog_version")
    rows.append(row("Catalogue", f"v{cat}" if cat else None, "ok" if cat else "na"))
    return entity("golem", "golem", "the rack · " + GOLEM, rows)


# ── Golem Engine ────────────────────────────────────────────────────────────────────────────────────────────────────
def read_engine(ctx):
    tags = releases(ctx)
    latest = latest_of(tags, "golem-engine-")
    held = holds(ctx)
    lin = _const(ctx.read("provision", "golem_engine.py"), "VERSION")
    win = (pins(ctx, "windows").get("golem_engine") or {}).get("version")
    mac = (pins(ctx, "macos").get("golem_engine") or {}).get("version")
    rows = [row("Published", latest and norm(latest), "ok" if latest else "na")]
    for label, key, pinned in (("Pinned · Linux", "golem_engine.linux", lin), ("Pinned · Windows", "golem_engine.windows", win)):
        st, note, fix = compare(pinned, latest, key, held, what=label.split(" · ")[1] + " engine pin")
        rows.append(row(label, pinned, st, note, fix))
    rows.append(row("Pinned · macOS", mac or "not ported (REAPER only)", compare(mac, latest)[0] if mac else "na"))
    # ICI : un arbre de dev passe avant le paquet installé (provision/golem_engine.py engine_dir)
    dev, inst = ctx.home / "golem-engine", ctx.home / "opt" / "golem-engine"
    if (dev / "golem" / "engine" / "run.sh").is_file():
        tag = ctx.git(dev, "describe", "--tags", "--always") or "?"
        built = None
        try:
            built = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(dev / "build" / "libs" / "ardour" / "libardour.so")))
        except OSError:
            pass
        tagged = ctx.git(dev, "log", "-1", "--format=%cs", "HEAD")
        stale = bool(built and tagged and built < tagged)
        behind = latest and vkey(tag) < vkey(latest)
        rows.append(row("Here", f"dev tree · sources {norm(tag)}" + (f" · built {built}" if built else ""),
                        "bad" if stale or behind else "ok",
                        note="the build is older than its sources" if stale else "",
                        fix=f"rebuild ~/golem-engine at {norm(latest)} (nobody playing) — the update catch-up never "
                            "touches a dev tree" if stale or behind else ""))
    elif (inst / "golem" / "engine" / "run.sh").is_file() or (inst / "golem" / "engine" / "run.py").is_file():
        try:
            v = (inst / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            v = None
        st, note, _ = compare(v, lin)
        rows.append(row("Here", v and f"installed package {v}", st, note,
                        fix="restart golem: the catch-up installs the pinned engine" if st == "bad" else ""))
    else:
        rows.append(row("Here", "not installed", "na"))
    return entity("engine", "Golem Engine", "audio engine · built from Ardour 9.9 · Goldoralf/golem-engine", rows)


# ── golem-fx ────────────────────────────────────────────────────────────────────────────────────────────────────────
def read_fx(ctx):
    tags = releases(ctx)
    latest = latest_of(tags, "golem-fx-")
    held = holds(ctx)
    ver = _const(ctx.read("provision", "golem_fx.py"), "VERSION")
    rows = []
    st = _repo_state(ctx, ctx.fx_repo)
    repo_tag = ctx.git(ctx.fx_repo, "describe", "--tags", "--abbrev=0")
    if st:
        newer = repo_tag and latest and vkey(repo_tag) > vkey(latest)
        rows.append(row("Repository", _state_text(*st), "warn" if st[1] or st[2] or newer else "ok",
                        note="this tag is not published yet" if newer else ""))
    else:
        rows.append(row("Repository", None))
    rows.append(row("Published", latest and norm(latest), "ok" if latest else "na"))
    pv = {"Linux": ver, "Windows": (pins(ctx, "windows").get("golem_fx") or {}).get("version"),
          "macOS": (pins(ctx, "macos").get("golem_fx") or {}).get("version")}
    same = len(set(pv.values())) == 1
    s, note, fix = compare(ver, latest, "golem_fx", held, fix=f"move golem-fx to {norm(latest)} on the three systems")
    rows.append(row("Pinned · 3 OS", ver if same else " / ".join(f"{k} {v}" for k, v in pv.items()),
                    s if same else "bad", note if same else "the three systems do not pin the same version",
                    fix if same else "pin the same golem-fx on the three systems"))
    man = (ctx.json(ctx.root / "library" / "catalog" / "golem-fx-plugins.json") or {}).get("golem_fx_commit")
    tag_commit = ctx.git(ctx.fx_repo, "rev-list", "-n", "1", ver) if ver else None
    if man and tag_commit:
        ok = man == tag_commit
        rows.append(row("Param. manifest", f"commit {man[:7]}" + (f" = {ver}" if ok else f" ≠ {ver} ({tag_commit[:7]})"),
                        "ok" if ok else "bad", fix="" if ok else "run tools/sync-golem-fx-manifest.py at the pinned tag"))
    else:
        rows.append(row("Param. manifest", man and f"commit {man[:7]}", "na"))
    stamp = ctx.json(ctx.home / ".local" / "share" / "golem" / "golem-fx-release.json") or {}
    here = stamp.get("version")
    hs, hnote, _ = compare(here, ver)
    rows.append(row("Here", here and f"{here} installed", hs, hnote,
                    fix="restart golem: the catch-up installs the pinned golem-fx" if hs == "bad" else ""))
    return entity("fx", "golem-fx", "golem's effects · VST3 · Goldoralf/golem-fx", rows)


# ── REAPER ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def read_reaper(ctx):
    held = holds(ctx)
    up = None
    m = re.match(r"\s*v(\d+\.\d+)", ctx.http("https://www.reaper.fm/whatsnew.txt") or "")
    if m:
        up = m.group(1)
    rows = [row("Published", up and f"{up} on reaper.fm", "ok" if up else "na")]
    fix = (f"install {up} on this rack (Settings ▸ About ▸ REAPER), play a patch, change scenes, record a take; then "
           "write the three pins and their hashes") if up else ""
    for label, key, v in (("Pinned · Linux", "reaper", _const(ctx.read("provision", "install-reaper.sh"), "REAPER_VERSION")),
                          ("Pinned · Windows", "reaper", (pins(ctx, "windows").get("reaper") or {}).get("version")),
                          ("Pinned · macOS", "reaper", (pins(ctx, "macos").get("reaper") or {}).get("version"))):
        s, note, f = compare(v, up, key, held, fix=fix)
        rows.append(row(label, v, s, note, f if label.endswith("Linux") else ""))
    here = None
    out = ctx.sh("curl", "-s", "--max-time", "3", "http://localhost:8770/api/system/reaper-update?check=0")
    try:
        d = json.loads(out or "{}")
        here, pinned = d.get("installed"), d.get("pinned")
        if here:
            rows.append(row("Here", here, "ok" if norm(here) == norm(pinned) else "warn",
                            note="" if norm(here) == norm(pinned) else "not the version this release validated"))
    except ValueError:
        pass
    if not here:
        rows.append(row("Here", None))
    return entity("reaper", "REAPER", "second audio engine · Cockos · commercial", rows)


# ── le contenu d'usine ──────────────────────────────────────────────────────────────────────────────────────────────
def read_factory(ctx):
    tags = releases(ctx)
    latest = latest_of(tags, "factory-demos-")
    tag = _const(ctx.read("bridge", "factory_demos.py"), "TAG")
    s, note, fix = compare(tag, latest, what="factory demos tag (bridge/factory_demos.py TAG)")
    rows = [row("Published", latest, "ok" if latest else "na"), row("Pinned by golem", tag, s, note, fix)]
    served = (ctx.json(ctx.fm_repo / "backend" / "app" / "data" / "golem-factory-renders.json") or {}).get("release")
    rows.append(row("Served by golem.fm", served, "na" if not served else ("ok" if served == tag else "bad"),
                    fix="" if not served or served == tag else f"tell golem.fm to serve {tag}"))
    # AVEC QUOI le lot a été rendu : l'en-tête de son index (rack_commit, catalog_version, golem_fx_version)
    idx = None
    if tag:
        raw = ctx.sh("gh", "release", "download", tag, "-R", BINARIES, "-p", "golem-factory-demos.json", "-O", "-", net=True)
        try:
            idx = json.loads(raw) if raw else None
        except ValueError:
            idx = None
    head = (idx or {}).get("header") or idx or {}
    cat = (ctx.json(ctx.root / "library" / "catalog" / "effects.json") or {}).get("catalog_version")
    fx = _const(ctx.read("provision", "golem_fx.py"), "VERSION")
    r_cat, r_fx = head.get("catalog_version"), head.get("golem_fx_version")
    if r_cat or r_fx:
        ok = str(r_cat) == str(cat) and norm(r_fx) == norm(fx)
        rows.append(row("Rendered with", f"golem-fx {r_fx} · catalogue {r_cat}", "ok" if ok else "bad",
                        note="" if ok else f"golem now pins golem-fx {fx} and catalogue {cat}: the blocks added since have no demo",
                        fix="" if ok else "render a new factory release on the rack (tools/pack-factory-demos.py, about an "
                                          "hour, nobody playing), publish it, send the tag to golem.fm"))
    else:
        rows.append(row("Rendered with", None))
    return entity("factory", "Factory content", "patches, presets, setlists, renders · shared with golem.fm", rows)


# ── la coquille vide ────────────────────────────────────────────────────────────────────────────────────────────────
def read_shell(ctx):
    src = ctx.json(ctx.fm_repo / "frontend" / "public" / "golem-app" / "SOURCE.json") or {}
    snap = ctx.json(ctx.fm_repo / "frontend" / "public" / "golem-app" / "snapshots" / "factory" / "SNAPSHOT.json") or {}
    commit = src.get("commit")
    last = ctx.git(ctx.root, "describe", "--tags", "--abbrev=0")
    rows = []
    if commit:
        desc = ctx.git(ctx.root, "describe", "--tags", commit) or commit[:7]
        n = ctx.git(ctx.root, "rev-list", "--count", f"{commit}..{last or 'HEAD'}", "--", "app")
        changed = int(n) if (n or "").isdigit() else None
        rows.append(row("Last extraction", f"{commit[:7]} = {desc} · {snap.get('made') or '?'} · catalogue "
                                           f"{snap.get('catalog_version') or '?'}", "bad" if changed else "ok"))
        rows.append(row("Target", f"shell {last}" + (f" · {changed} commit{'s' if changed != 1 else ''} touched the app since"
                                                     if changed else " · the app did not change"),
                        "bad" if changed else "ok",
                        fix=f"extract shell {last} (tools/shell_snapshot.py --factory --rev {last}), measure the doc impact, "
                            "hand it to golem.fm" if changed else ""))
    else:
        rows.append(row("Last extraction", None))
    site = (ctx.json(ctx.site_repo / "SITE.json") or {}).get("shell_commit")
    for label, c in (("golem.fm runs", commit), ("golem-site runs", site)):
        rows.append(row(label, c and c[:7], "na" if not c else ("ok" if c == commit else "bad"),
                        note="" if not c or c == commit else "not the shell golem.fm runs"))
    return entity("shell", "Empty shell", "the demo golem: app + factory snapshot + examples · docs, showcase, Library", rows)


# ── golem.fm (maestrium) et golem-site ──────────────────────────────────────────────────────────────────────────────
def read_fm(ctx):
    st = _repo_state(ctx, ctx.fm_repo)
    if not st:
        return entity("fm", "golem.fm", "the service · maestrium", [row("Here", None)])
    last = ctx.git(ctx.fm_repo, "describe", "--tags", "--abbrev=0")
    since = ctx.git(ctx.fm_repo, "rev-list", "--count", f"{last}..HEAD") if last else None
    rows = [row("Here", _state_text(*st), "warn" if st[1] or st[2] else "ok"),
            row("Last release", last, "ok" if last else "na")]
    if since and since != "0":
        rows.append(row("Not released", f"{since} commit{'s' if since != '1' else ''} since {last}", "warn"))
    docs = ctx.git(ctx.fm_repo, "log", "-1", "--format=%cs", "--", "frontend/src/content/docs")
    rows.append(row("Its docs", docs and f"last change {docs} · shell not recorded", "warn" if docs else "na",
                    note="no page records the shell it was written against"))
    fxsrc = ctx.json(ctx.fm_repo / "frontend" / "src" / "lib" / "golemFx" / "SOURCE.json") or {}
    fx = fxsrc.get("tag") or fxsrc.get("ref")
    pinned = _const(ctx.read("provision", "golem_fx.py"), "VERSION")
    rows.append(row("golem-fx it draws", fx, "na" if not fx else ("ok" if norm(fx) == norm(pinned) else "warn"),
                    note="" if not fx or norm(fx) == norm(pinned) else f"golem pins {pinned}"))
    return entity("fm", "golem.fm", "the service · maestrium", rows)


def read_site(ctx):
    st = _repo_state(ctx, ctx.site_repo)
    if not st:
        return entity("site", "golem-site", "golem.fm's public site (temporary)", [row("Here", None)])
    site = ctx.json(ctx.site_repo / "SITE.json") or {}
    rows = [row("Here", _state_text(*st), "warn" if st[1] or st[2] else "ok")]
    pub = ctx.home / "golem-public" / "site"
    pst = _repo_state(ctx, pub)
    rows.append(row("Public copy", pst and _state_text(*pst), "na" if not pst else ("warn" if pst[1] or pst[2] else "ok")))
    fm_head = (site.get("docs_from") or {}).get("maestrium_head")
    fm_now = ctx.git(ctx.fm_repo, "rev-parse", "HEAD")
    if fm_head and fm_now:
        n = ctx.git(ctx.fm_repo, "rev-list", "--count", f"{fm_head}..HEAD", "--", "frontend/src/content/docs",
                    "frontend/src/pages/docs")
        late = int(n) if (n or "").isdigit() else 0
        rows.append(row("Its docs", f"built from golem.fm {fm_head[:7]}" + (f" · {late} doc commit{'s' if late != 1 else ''} since"
                                                                            if late else ""),
                        "warn" if late else "ok", fix="rebuild the site's docs (update_site.py --site-only)" if late else ""))
    fxd = (ctx.json(ctx.site_repo / "assets" / "fx" / "fx-data.json") or {}).get("source") or {}
    fxv = fxd.get("tag") or fxd.get("ref")
    rows.append(row("/fx page", fxv and f"golem-fx {fxv}", "ok" if fxv else "na"))
    return entity("site", "golem-site", "golem.fm's public site · temporary, until golem.fm serves it", rows)


# ── golem-binaries : chaque famille, publiée / épinglée ─────────────────────────────────────────────────────────────
def read_binaries(ctx):
    tags = releases(ctx)
    held = holds(ctx)
    base = _const(ctx.read("provision", "fetch-prebuilt.sh") or "", "GOLEM_PREBUILT_BASE") or ""
    lp = re.search(r"linux-plugins-v\d+", ctx.read("provision", "fetch-prebuilt.sh") or base or "")
    fam = [("golem-engine", "golem-engine-", _const(ctx.read("provision", "golem_engine.py"), "VERSION"), "golem_engine.linux"),
           ("golem-fx", "golem-fx-", _const(ctx.read("provision", "golem_fx.py"), "VERSION"), "golem_fx"),
           ("linux-plugins", "linux-plugins-", lp and lp.group(0), "linux_plugins"),
           ("factory-demos", "factory-demos-", _const(ctx.read("bridge", "factory_demos.py"), "TAG"), "factory_demos")]
    rows = []
    for name, prefix, pinned, key in fam:
        latest = latest_of(tags, prefix)
        s, note, fix = compare(pinned, latest, key, held)
        rows.append(row(name, f"{short(latest)} / {short(pinned)}", s, note))
    st = _repo_state(ctx, ctx.binaries_repo)
    rows.append(row("Repository", st and _state_text(*st), "na" if not st else ("warn" if st[1] or st[2] else "ok")))
    return entity("binaries", "golem-binaries", "prebuilt archives (published / pinned) · " + BINARIES, rows)


# ── les plugins tiers que les installateurs épinglent ───────────────────────────────────────────────────────────────
THIRD = [  # (nom, dépôt amont, clé de retard voulu, lecteur de l'épingle, note)
    ("Dexed", "asb2m10/dexed", "dexed", lambda c: _const(c.read("provision", "plugins.sh"), "DEXED_VER"), ""),
    ("NAM LV2", "mikeoliphant/neural-amp-modeler-lv2", "nam_lv2", lambda c: _const(c.read("provision", "plugins.sh"), "NAM_VER"),
     "carries golem's crash patch: a bump means rebasing it (provision/install-nam.sh)"),
    # le build golem (nam_golem) est posé PAR-DESSUS l'officiel 0.7.13, dernier publié en binaire : c'est lui qui joue
    ("NAM VST3", "sdatkinson/NeuralAmpModelerPlugin", "nam_vst3",
     lambda c: (pins(c, "windows").get("nam_golem") or {}).get("version"), ""),
    ("Surge XT", "surge-synthesizer/releases-xt", "surge", lambda c: _const(c.read("provision", "install-plugins.sh"), "SURGE_VER"), ""),
    ("sfizz", "sfztools/sfizz", "sfizz", lambda c: (pins(c, "windows").get("sfizz") or {}).get("version"), ""),
    ("PaulXStretch", "essej/paulxstretch", "paulxstretch",
     lambda c: (re.search(r'PXS_COMMIT=.*#\s*(v[\d.]+)', c.read("provision", "install-spectral.sh") or "") or [None, None])[1], ""),
]


def read_third_party(ctx):
    held = holds(ctx)
    rows = []
    for name, repo, key, reader, hint in THIRD:
        pinned = reader(ctx)
        up = ctx.sh("gh", "api", f"repos/{repo}/releases/latest", "-q", ".tag_name", net=True)
        s, note, fix = compare(pinned, up, key, held, fix=f"read the {name} {norm(up)} changelog, then move the pin or "
                                                          "write the reason in provision/pins-held.json")
        rows.append(row(name, f"{norm(pinned) if pinned else '?'} / {norm(up) if up else '?'}", s,
                        note or "", (fix + (" — " + hint if hint and fix else ""))))
    return entity("third", "Third-party plugins", "what the installers pin (pinned / upstream latest)", rows)


READERS = [read_golem, read_engine, read_fx, read_reaper, read_factory, read_shell, read_fm, read_site, read_binaries,
           read_third_party]


def collect(ctx=None):
    """L'inventaire complet : {made, entities, counts, next}. Jamais d'exception d'un lecteur : son entité le dit."""
    ctx = ctx or Ctx()
    ents = []
    for reader in READERS:
        try:
            ents.append(reader(ctx))
        except Exception as e:                           # un lecteur cassé ne cache pas les autres
            ents.append(entity(reader.__name__[5:], reader.__name__[5:], "", [row("Reader", f"failed: {e}", "bad")]))
    counts = {s: sum(1 for e in ents for r in e["rows"] if r["status"] == s) for s in ORDER}
    todo = [{"entity": e["name"], "label": r["label"], "fix": r["fix"]} for e in ents for r in e["rows"]
            if r["status"] == "bad" and r["fix"]]
    last = ctx.git(ctx.root, "describe", "--tags", "--abbrev=0")
    return {"made": time.strftime("%Y-%m-%d %H:%M"), "offline": ctx.offline, "last_release": last, "entities": ents,
            "counts": counts, "todo": todo}


if __name__ == "__main__":
    import sys
    print(json.dumps(collect(Ctx(offline="--offline" in sys.argv)), indent=1, ensure_ascii=False))
