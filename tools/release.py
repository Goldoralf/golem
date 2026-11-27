#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""PUBLIER UNE RELEASE DE golem, PAS À PAS (docs/release-tool-plan.md §2, docs/release-checklist.md, 2026-11-27).

Le mainteneur publie depuis SON golem. À chaque étape, l'outil vérifie ce qui se mesure, rappelle ce que seul un humain
fait (jouer le rig, monter REAPER, relire les notes) et fait, après un oui, ce qui s'automatise (la suite de tests,
l'instantané, le brouillon des notes, release.sh). Demandé après la v0.7.2, sortie avec un moteur et un REAPER en retard
sans que rien ne le dise.

    tools/release.py v0.7.4              # reprend là où on en était (ou commence)
    tools/release.py v0.7.4 --status     # où on en est, étape par étape
    tools/release.py v0.7.4 --dry-run    # toutes les vérifications, aucune action, aucune question
    tools/release.py v0.7.4 --done ID    # un rappel est fait (jouer le rig…)
    tools/release.py v0.7.4 --yes ID     # lancer une action
    tools/release.py v0.7.4 --skip ID "raison"   # sauter une étape : la raison est écrite et finit dans les notes
    tools/release.py v0.7.4 --from ID    # refaire à partir de cette étape

Trois sortes d'étapes, dites comme telles : VÉRIFICATION (mesurée, ✅ ou ✗ avec la preuve), RAPPEL (un humain fait ou
décide ; l'outil attend « fait », « sauté — raison » ou l'arrêt), ACTION (l'outil la fait après un oui).

Dans un terminal, il pose ses questions. Sans terminal (lancé par `!` depuis une session Claude), il s'arrête à la
première étape qui attend une réponse et dit la commande qui la donne : rien ne se décide à la place du mainteneur.

L'état vit dans ~/.local/share/golem/release/<version>.json (le RECORD) : un arrêt, une suite de tests de neuf minutes,
un banc, ne font jamais tout recommencer. tools/release.sh refuse de signer tant que le record n'est pas complet.
La signature reste dans le terminal du mainteneur : une session Claude ne signe pas (son agent SSH refuse).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import golem_inventory as inv   # noqa: E402

REPO = "Goldoralf/golem"
BRIDGE = "http://localhost:8770"
RECORDS = Path.home() / ".local" / "share" / "golem" / "release"
VERSION_RX = re.compile(r"^v\d+\.\d+\.\d+$")
CHECK, REMINDER, ACTION = "check", "reminder", "action"
DONE_STATES = ("done", "skipped")


# ── le contexte d'une release : la version, le record, les lectures (remplaçables par les tests) ────────────────────
class Release:
    def __init__(self, version, root=ROOT, records=RECORDS, sh=None, ask=None, out=print, interactive=None,
                 inventory=None, now=None):
        self.version, self.root = version, Path(root)
        self.path = Path(records) / (version + ".json")
        self._sh = sh or _run
        self.ask = ask or input
        self.out = out
        self.interactive = sys.stdin.isatty() if interactive is None else interactive
        self._inventory = inventory
        self.now = now or (lambda: time.strftime("%Y-%m-%d %H:%M"))
        self.record = self.load()

    # le record
    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": self.version, "started": None, "steps": {}, "notes": []}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.record.setdefault("started", self.now())
        self.path.write_text(json.dumps(self.record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def mark(self, sid, status, evidence="", reason=""):
        self.record["steps"][sid] = {"status": status, "at": self.now(), "evidence": evidence, **({"reason": reason} if reason else {})}
        self.save()

    def note(self, line):
        """Une ligne que les notes de version doivent porter (un retard voulu, une épingle non rattrapée)."""
        if line not in self.record["notes"]:
            self.record["notes"].append(line)
            self.save()

    # les lectures
    def sh(self, *cmd, cwd=None, timeout=60):
        return self._sh(list(cmd), str(cwd or self.root), timeout)

    def git(self, *args):
        r = self.sh("git", *args)
        return r[1].strip() if r[0] == 0 else None

    def previous(self):
        return self.git("describe", "--tags", "--abbrev=0", "HEAD")

    def inventory(self):
        if self._inventory is None:
            self._inventory = inv.collect(inv.Ctx(root=self.root))
        return self._inventory

    def entity(self, eid):
        return next((e for e in self.inventory()["entities"] if e["id"] == eid), {"rows": []})

    def dir(self):
        d = self.path.parent / self.version
        d.mkdir(parents=True, exist_ok=True)
        return d


def _run(cmd, cwd=None, timeout=60):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)


def _get(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:     # noqa: S310 — le bridge local
            return json.loads(r.read() or b"null")
    except Exception:
        return None


class Result:
    """Ce qu'une étape rend : ok (passe), warn (passe, avec une note), fail (bloque), wait (un humain doit répondre)."""

    def __init__(self, status, evidence="", fixes=(), notes=()):
        self.status, self.evidence, self.fixes, self.notes = status, evidence, list(fixes), list(notes)


def ok(evidence="", notes=()):
    return Result("ok", evidence, notes=notes)


def warn(evidence, notes=()):
    return Result("warn", evidence, notes=notes)


def fail(evidence, *fixes):
    return Result("fail", evidence, fixes)


# ── les étapes ──────────────────────────────────────────────────────────────────────────────────────────────────────
STEPS = []


def step(sid, phase, kind, title):
    def wrap(fn):
        STEPS.append({"id": sid, "phase": phase, "kind": kind, "title": title, "fn": fn})
        return fn
    return wrap


# 0. L'environnement
@step("env.repo", "Environment", CHECK, "main, a clean tree, nothing unpushed")
def env_repo(r):
    branch = r.git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        return fail("on branch %s" % branch, "git switch main")
    # pas r.git : il retire l'espace de tête de la sortie, et « ␠M tools/x » perdait la 1re lettre du chemin
    dirty = [ln for ln in r.sh("git", "status", "--porcelain", "--untracked-files=no")[1].splitlines() if ln.strip()]
    if dirty:
        return fail("%d file(s) not committed: %s" % (len(dirty), ", ".join(ln[3:] for ln in dirty[:5])),
                    "commit them (one commit per subject, the message in English) or put them aside")
    r.sh("git", "fetch", "-q", "origin", timeout=60)
    head, origin = r.git("rev-parse", "HEAD"), r.git("rev-parse", "origin/main")
    if head != origin:
        ahead = r.git("rev-list", "--count", "origin/main..HEAD")
        return fail("HEAD %s, origin/main %s (%s commit(s) not pushed)" % (str(head)[:8], str(origin)[:8], ahead), "git push")
    return ok("main = origin/main = %s" % head[:8])


@step("env.tools", "Environment", CHECK, "the release key in the agent, GitHub reachable")
def env_tools(r):
    key = Path.home() / ".ssh" / "golem_release.pub"
    bits = []
    if not key.exists():
        return fail("no release key at %s" % key, "the maintainer's key: docs/release-signing.md")
    agent = r.sh("ssh-add", "-L")[1]
    keyed = key.read_text().split()[1] in agent
    rc = r.sh("gh", "auth", "status")[0]
    if rc != 0:
        return fail("gh is not signed in", "gh auth login")
    bits.append("gh signed in")
    if not keyed:
        # pas bloquant ici : la clé ne sert qu'à la signature, des heures plus tard peut-être
        return warn("gh signed in; the release key is NOT in the agent yet — needed at the signature: ssh-add %s" % key.with_suffix(""))
    return ok("gh signed in, release key in the agent")


@step("env.rack", "Environment", CHECK, "the local golem answers, nothing is recording")
def env_rack(r):
    st = _get(BRIDGE + "/api/state")
    if not isinstance(st, dict):
        return warn("the local bridge does not answer (%s): the rig steps will need it" % BRIDGE)
    if st.get("recording"):
        return fail("a take is recording", "stop the take first: a release never runs during a take")
    eng = (st.get("engine") or {}).get("name") or "?"
    return ok("bridge up, engine %s, nothing recording" % eng)


@step("env.siblings", "Environment", CHECK, "the sibling repositories are here and up to date")
def env_siblings(r):
    ctx = inv.Ctx(root=r.root)
    rows, late = [], []
    for name, repo in (("golem-engine", ctx.engine_repo), ("golem-fx", ctx.fx_repo), ("golem-binaries", ctx.binaries_repo),
                       ("golem.fm (maestrium)", ctx.fm_repo), ("golem-site", ctx.site_repo)):
        if not repo.exists():
            rows.append("%s: absent" % name)
            continue
        r.sh("git", "-C", str(repo), "fetch", "-q", timeout=60)
        st = inv._repo_state(ctx, repo)
        rows.append("%s: %s" % (name, inv._state_text(*st)))
        if st and st[2]:
            late.append(name)
    return (warn("; ".join(rows) + " — behind origin: " + ", ".join(late)) if late else ok("; ".join(rows)))


# 1. La version
@step("version", "Version", CHECK, "the version number")
def version(r):
    v = r.version
    if not VERSION_RX.match(v):
        return fail("%s is not vX.Y.Z" % v, "give the number as v0.7.4")
    if r.git("rev-parse", "-q", "--verify", "refs/tags/" + v):
        return fail("%s already exists — a published tag never moves" % v, "choose the next number")
    prev = r.previous()
    since = r.git("rev-list", "--count", "%s..HEAD" % prev) if prev else "?"
    if prev and VERSION_RX.match(prev):
        a, b = [tuple(int(x) for x in t[1:].split(".")) for t in (prev, v)]
        nxt = {(a[0], a[1], a[2] + 1), (a[0], a[1] + 1, 0), (a[0] + 1, 0, 0)}
        if b not in nxt:
            return warn("%s after %s (%s commits) — not the next number: the maintainer chose it" % (v, prev, since))
    return ok("%s after %s, %s commit(s) since" % (v, prev, since))


# 2. Où en est chaque entité
@step("snapshot", "Snapshot", CHECK, "the snapshot page")
def snapshot(r):
    import importlib.util
    spec = importlib.util.spec_from_file_location("golem_snapshot", r.root / "tools" / "snapshot.py")
    snap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(snap)
    data = r.inventory()
    page = r.dir() / "snapshot.html"
    page.write_text(snap.render(data), encoding="utf-8")
    c = data["counts"]
    return ok("%d behind, %d to watch, %d aligned — %s" % (c["bad"], c["warn"], c["ok"], page))


def _rows(r, eids, labels=None):
    for eid in eids:
        e = r.entity(eid)
        for row in e["rows"]:
            if labels and row["label"] not in labels:
                continue
            yield e.get("name", eid), row


# 3 et 4. Les épingles
@step("pins.reaper", "Pins", REMINDER, "REAPER: the pinned version against reaper.fm")
def pins_reaper(r):
    bad = [(n, row) for n, row in _rows(r, ["reaper"]) if row["label"].startswith("Pinned") and row["status"] == "bad"]
    held = [(n, row) for n, row in _rows(r, ["reaper"]) if row["label"].startswith("Pinned") and row["status"] == "warn"]
    if bad:
        return fail("REAPER pinned %s; %s" % (bad[0][1]["value"], bad[0][1]["note"]),
                    "play the new version on the rig (Settings ▸ About ▸ REAPER ▸ Install; a patch, scenes, a stomp, a take), "
                    "then: tools/bump.py reaper <version> --played-on-rig",
                    "or keep it on purpose: write the reason in provision/pins-held.json (key reaper)")
    if held:
        return warn("REAPER " + held[0][1]["note"], notes=["golem keeps REAPER %s (%s)" % (held[0][1]["value"], held[0][1]["note"])])
    return ok("REAPER pinned at the latest published")


@step("pins.own", "Pins", CHECK, "golem's own components: Golem Engine, golem-fx, prebuilt plugins")
def pins_own(r):
    bad, held, ev = [], [], []
    for name, row in _rows(r, ["engine", "fx", "binaries"]):
        if row["label"].startswith(("Pinned", "Param.")) or name == "golem-binaries" and row["label"] != "Repository":
            if row["status"] == "bad":
                bad.append("%s %s: %s %s" % (name, row["label"], row["value"], row["note"]))
            elif row["status"] == "warn":
                held.append("%s %s: %s" % (name, row["label"], row["note"]))
            elif row["status"] == "ok":
                ev.append("%s %s %s" % (name, row["label"], row["value"]))
    if bad:
        return fail("; ".join(bad), "tools/bump.py golem-engine|golem-fx <version> (hashes recomputed, every file written)",
                    "or keep it on purpose: provision/pins-held.json")
    return (warn("; ".join(held), notes=held) if held else ok("all at the latest published"))


@step("pins.third", "Pins", REMINDER, "the third-party plugins the installers pin")
def pins_third(r):
    bad = [(n, row) for n, row in _rows(r, ["third"]) if row["status"] == "bad"]
    held = [row for n, row in _rows(r, ["third"]) if row["status"] == "warn"]
    if bad:
        return fail("; ".join("%s %s (%s)" % (row["label"], row["value"], row["note"]) for _, row in bad),
                    *[row["fix"] for _, row in bad if row["fix"]])
    return (warn("; ".join("%s: %s" % (h["label"], h["note"]) for h in held)) if held else ok("all at the latest upstream"))


@step("pins.catchup", "Pins", CHECK, "every moved pin reaches a golem that updates")
def pins_catchup(r):
    """Les épingles qui ont bougé depuis la release précédente, et si une mise à jour les apporte (docs/update.md §3 bis)."""
    prev = r.previous()
    if not prev:
        return ok("no previous release")
    files = (r.git("diff", "--name-only", prev, "HEAD", "--", "provision") or "").splitlines()
    caught = {"provision/golem_fx.py": "golem-fx", "provision/golem_engine.py": "the Golem Engine"}
    moved = [caught[f] for f in files if f in caught]
    others = [f for f in files if f in ("provision/install-reaper.sh", "provision/plugins.sh", "provision/install-plugins.sh",
                                        "provision/dexed.py", "provision/surge.py", "provision/fetch-prebuilt.sh")]
    notes = ["An update brings %s by itself, at the next start." % " and ".join(moved)] if moved else []
    if others:
        notes.append("New installs get the new %s; an updated golem keeps what it has until the install line is run again."
                     % ", ".join(sorted({os.path.basename(f) for f in others})))
        return warn("caught up after an update: %s; NOT caught up: %s (said in the notes)" % (", ".join(moved) or "none",
                                                                                              ", ".join(others)), notes=notes)
    return ok("caught up after an update: %s" % (", ".join(moved) or "no pin moved"), notes=notes)


# 5. Le contenu d'usine
@step("factory", "Factory content", CHECK, "the factory demos match the pinned golem-fx and catalogue")
def factory(r):
    rows = {row["label"]: row for _, row in _rows(r, ["factory"])}
    bad = [row for row in rows.values() if row["status"] == "bad"]
    if bad:
        return fail("; ".join("%s: %s (%s)" % (b["label"], b["value"], b["note"]) for b in bad), *[b["fix"] for b in bad if b["fix"]])
    return ok("; ".join("%s %s" % (k, v["value"]) for k, v in rows.items()))


# 6. Les vérifications du dépôt
def _suite_cmds(r):
    py = str(r.root / ".venv" / "bin" / "python")
    return [("ruff", [py, "-m", "ruff", "check", "."]), ("syntax", [py, "tools/check-syntax.py"]),
            ("node", ["bash", "-c", "node --test app/*.test.mjs"]), ("pytest", [py, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"])]


@step("checks.suite", "Checks", ACTION, "the whole suite: ruff, check-syntax, node --test, pytest (about 9 minutes)")
def checks_suite(r):
    res = []
    for name, cmd in _suite_cmds(r):
        rc, out, err = r.sh(*cmd, timeout=1800)
        last = ((out or err).strip().splitlines() or ["?"])[-1][:120]
        res.append("%s %s" % (name, "ok" if rc == 0 else "FAILED (%s)" % last))
        if rc != 0:
            return fail("; ".join(res), "fix it, then: tools/release.py %s --yes checks.suite" % r.version)
    r.record["suite_head"] = r.git("rev-parse", "HEAD")      # publish.ci vérifie que rien n'a été commité depuis
    return ok("; ".join(res))


@step("checks.ui", "Checks", ACTION, "every page rendered as CI does it (check-ui --test-content, about 4 minutes)")
def checks_ui(r):
    rc, out, err = r.sh(str(r.root / ".venv" / "bin" / "python"), "tools/check-ui.py", "--test-content", timeout=1800)
    last = ((out or err).strip().splitlines() or ["?"])[-1][:200]
    return ok(last) if rc == 0 else fail(last, "read the FAIL lines of tools/check-ui.py --test-content")


def engine_pins(r, rev):
    """Les versions du moteur épinglées à une révision : {linux, windows} (provision/golem_engine.py, pins.json)."""
    out = {}
    py = r.git("show", "%s:provision/golem_engine.py" % rev) or ""
    m = re.search(r'^VERSION = "([^"]*)"', py, re.M)
    out["linux"] = m.group(1) if m else None
    try:
        out["windows"] = (json.loads(r.git("show", "%s:provision/windows/pins.json" % rev) or "{}").get("golem_engine") or {}).get("version")
    except ValueError:
        out["windows"] = None
    return out


@step("checks.engine", "Checks", REMINDER, "the engine benches, when the engine moved")
def checks_engine(r):
    prev = r.previous()
    if not prev:
        return ok("no previous release")
    a, b = engine_pins(r, prev), engine_pins(r, "HEAD")
    moved = {k: (a[k], b[k]) for k in b if a.get(k) != b.get(k)}
    if not moved:
        return ok("the engine pin did not move since %s (%s)" % (prev, ", ".join("%s %s" % kv for kv in b.items())))
    return fail("the engine pin moved since %s: %s" % (prev, ", ".join("%s %s → %s" % (k, x, y) for k, (x, y) in moved.items())),
                "nobody playing: tools/check-engine-ardour.py --engine-dir <the pinned package> five times "
                "(docs/linux-pass-2026-11.md §2), then: tools/release.py %s --done checks.engine" % r.version)


@step("checks.scan", "Checks", CHECK, "the public scan finds nothing")
def checks_scan(r):
    rc, out, err = r.sh("python3", "tools/public_export.py", "--deny", str(Path.home() / "golem-public" / "denylist.txt"),
                        "--allow", str(Path.home() / "golem-public" / "allowlist.txt"), "--summary", timeout=300)
    last = ((out or err).strip().splitlines() or ["?"])[-1]
    return ok(last) if " 0 forbidden" in last else fail(last, "remove the words it lists (first names, private names)")


# 7. Le rig
@step("rig.play", "Rig", REMINDER, "play the rig")
def rig_play(r):
    return fail("on this golem: reload, play a patch, change scenes, press a stomp, record and play back a take",
                "then: tools/release.py %s --done rig.play" % r.version)


@step("rig.versions", "Rig", CHECK, "this golem runs the versions the release pins")
def rig_versions(r):
    rows = [(n, row) for n, row in _rows(r, ["fx", "engine", "reaper"], labels={"Here"})]
    bad = ["%s: %s %s" % (n, row["value"], row["note"]) for n, row in rows if row["status"] == "bad"]
    if bad:
        return fail("; ".join(bad), *[row["fix"] for _, row in rows if row["status"] == "bad" and row["fix"]])
    return ok("; ".join("%s %s" % (n, row["value"]) for n, row in rows))


# 8. Publier
@step("publish.ci", "Publish", CHECK, "CI is green on the exact commit")
def publish_ci(r):
    head = r.git("rev-parse", "HEAD")
    tested = r.record.get("suite_head")
    if tested and tested != head:
        return fail("commits since the suite ran (%s → %s)" % (tested[:8], head[:8]),
                    "rerun the checks on what will be published: tools/release.py %s --from checks.suite" % r.version)
    for _ in range(40):                                  # au plus 20 minutes : la CI dure ~12 min
        rc, out, _err = r.sh("gh", "run", "list", "-R", REPO, "-L", "20", "--json", "headSha,name,status,conclusion")
        runs = [x for x in (json.loads(out) if rc == 0 and out else []) if x["headSha"] == head and x["name"] == "CI"]
        if runs and runs[0]["status"] == "completed":
            c = runs[0]["conclusion"]
            return ok("CI %s on %s" % (c, head[:8])) if c == "success" else fail("CI %s on %s" % (c, head[:8]),
                                                                                  "gh run view --log-failed -R %s" % REPO)
        if not runs:
            return fail("no CI run for %s" % head[:8], "push the commit: CI runs on every push")
        if not r.interactive:
            return fail("CI %s on %s" % (runs[0]["status"], head[:8]), "wait for it, then rerun tools/release.py %s" % r.version)
        time.sleep(30)
    return fail("CI still running on %s after 20 minutes" % head[:8], "rerun later")


def notes_draft(r):
    """Le brouillon des notes de version : les sujets des commits depuis la release précédente, les versions épinglées,
    les retards voulus et ce qu'une mise à jour n'apporte pas, le chemin de mise à jour. En anglais : l'écran de mise à
    jour les montre. Le mainteneur le relit et le réécrit."""
    prev = r.previous()
    subjects = (r.git("log", "--format=%s", "--reverse", "%s..HEAD" % prev) or "").splitlines() if prev else []
    internal = re.compile(r"^(Tests?|Docs?|CI|UI inventory|Public scan)\b|^golem-fx sync at ")
    lines = ["golem %s — <one line: what this release brings>" % r.version, ""]
    lines += ["- " + s for s in subjects if not internal.match(s)] or ["- <what changed>"]
    pins = {}
    for _, row in _rows(r, ["fx", "engine", "reaper"]):
        if row["label"].startswith("Pinned"):
            pins.setdefault(row["label"], row["value"])
    fx = next((v for k, v in pins.items() if k.startswith("Pinned · 3 OS")), "?")
    eng = "%s (Linux), %s (Windows)" % (pins.get("Pinned · Linux", "?"), pins.get("Pinned · Windows", "?"))
    reaper = next((row["value"] for _, row in _rows(r, ["reaper"]) if row["label"] == "Pinned · Linux"), "?")
    lines += ["", "Versions: golem-fx %s, Golem Engine %s, REAPER %s." % (fx, eng, reaper)]
    extra = list(dict.fromkeys(r.record.get("notes") or []))
    skipped = ["%s was skipped: %s" % (k, v.get("reason")) for k, v in r.record["steps"].items() if v["status"] == "skipped"]
    if extra or skipped:
        lines += [""] + ["- " + x for x in extra + skipped]
    lines += ["", "Updating from %s: Settings > About > Update to %s." % (prev or "the previous release", r.version),
              "Updating from v0.6.2–v0.6.4: run the install line of the README once."]
    return "\n".join(lines) + "\n"


@step("publish.notes", "Publish", ACTION, "the release notes: a draft written, then read and rewritten by the maintainer")
def publish_notes(r):
    path = r.dir() / "notes.md"
    if not path.exists():
        path.write_text(notes_draft(r), encoding="utf-8")
        return fail("draft written: %s" % path, "read it, rewrite it in plain English for musicians, save it, then: "
                                                 "tools/release.py %s --done publish.notes" % r.version)
    return ok(str(path))


@step("publish.sign", "Publish", ACTION, "sign and publish: tools/release.sh (the maintainer's terminal)")
def publish_sign(r):
    notes = r.dir() / "notes.md"
    cmd = ["tools/release.sh", r.version, str(notes)]
    if not r.interactive:
        return fail("signing needs the maintainer's terminal (the release key is in his agent)",
                    "in your terminal: %s" % " ".join(cmd), "then: tools/release.py %s --done publish.sign" % r.version)
    rc = subprocess.call(cmd, cwd=str(r.root), env={**os.environ, "GOLEM_RELEASE_RECORD": str(r.path)})
    return ok("%s published" % r.version) if rc == 0 else fail("release.sh stopped (exit %d)" % rc, "read its message, fix, run again")


# 9. Après
@step("after.verify", "After", CHECK, "the release is published, signed and seen")
def after_verify(r):
    v = r.version
    rc, _o, _e = r.sh("git", "fetch", "-q", "--tags", "origin")
    rc, out, err = r.sh("git", "-c", "gpg.format=ssh", "-c", "gpg.ssh.allowedSignersFile=provision/release-signers", "verify-tag", v)
    if rc != 0:
        return fail("tag %s does not verify: %s" % (v, (err or out).strip()[:120]), "is the release published? tools/release.sh")
    rc, out, _e = r.sh("gh", "api", "repos/%s/releases/latest" % REPO, "-q", ".tag_name")
    if out.strip() != v:
        return fail("releases/latest is %s, not %s" % (out.strip() or "?", v), "gh release edit %s --latest -R %s" % (v, REPO))
    up = _get(BRIDGE + "/api/system/update?fetch=1", timeout=30) or {}
    seen = "this golem sees %s (%s)" % (up.get("latest"), up.get("status")) if up else "the local bridge did not answer"
    return ok("tag %s signed, releases/latest = %s, %s" % (v, v, seen))


@step("after.shell", "After", ACTION, "the empty shell of this release, handed to golem.fm")
def after_shell(r):
    row = next((row for _, row in _rows(r, ["shell"], labels={"Target"})), None)
    if row and row["status"] == "ok":
        return ok("the app did not change since the shell golem.fm serves: no new shell")
    return fail("the app changed since the shell golem.fm serves", "tools/shell_release.py %s (7 minutes), then hand "
                "~/golem-doc-work/pin-<commit>/HANDOVER.md to the golem-fm session; then: tools/release.py %s --done after.shell"
                % (r.version, r.version))


@step("after.tell", "After", REMINDER, "tell the others")
def after_tell(r):
    return fail("update the other golems (Settings ▸ About ▸ Update), tell the golem-fm and golem-site sessions the tag, "
                "a Discussions post if the release matters to users",
                "then: tools/release.py %s --done after.tell" % r.version)


# ── le déroulé ──────────────────────────────────────────────────────────────────────────────────────────────────────
KIND_LABEL = {CHECK: "check", REMINDER: "reminder", ACTION: "action"}
SIGN_GATE = "publish.sign"


def ready_to_sign(record):
    """Toutes les étapes AVANT la signature sont faites ou sautées avec une raison : ce que release.sh exige."""
    before = [s["id"] for s in STEPS[:[s["id"] for s in STEPS].index(SIGN_GATE)]]
    missing = [sid for sid in before if (record.get("steps") or {}).get(sid, {}).get("status") not in DONE_STATES]
    return missing


def run(r, dry=False, yes=(), done=(), skip=None, start=None):
    """Déroule les étapes dans l'ordre. Rend 0 quand tout est fait, 1 à l'arrêt (une réponse attendue ou un échec)."""
    steps = r.record["steps"]
    for sid in done:
        if sid not in {s["id"] for s in STEPS}:
            r.out("✗ unknown step %s" % sid)
            return 2
        r.mark(sid, "done", "confirmed by the maintainer")
    if skip:
        sid, reason = skip
        if not reason.strip():
            r.out("✗ a skip needs a reason")
            return 2
        r.mark(sid, "skipped", reason=reason.strip())
        r.note("%s skipped: %s" % (sid, reason.strip()))
    if start:
        ids = [s["id"] for s in STEPS]
        if start not in ids:
            r.out("✗ unknown step %s" % start)
            return 2
        for sid in ids[ids.index(start):]:
            steps.pop(sid, None)
        r.save()
    phase = None
    for s in STEPS:
        sid = s["id"]
        if steps.get(sid, {}).get("status") in DONE_STATES and not dry:
            continue
        if s["phase"] != phase:
            phase = s["phase"]
            r.out("\n── %s" % phase)
        if s["kind"] == ACTION and not dry and sid not in yes and not _confirm(r, s):
            return _stop(r, s, "to run it: tools/release.py %s --yes %s   (or, done by hand: --done %s)" % (r.version, sid, sid))
        if s["kind"] == ACTION and dry:
            r.out("  · %-15s [action]   %s — not run (dry run)" % (sid, s["title"]))
            continue
        res = s["fn"](r)
        for n in res.notes:
            if not dry:
                r.note(n)
        if res.status in ("ok", "warn"):
            r.out("  %s %-15s [%s] %s — %s" % ("✅" if res.status == "ok" else "⚠️", sid, KIND_LABEL[s["kind"]], s["title"], res.evidence))
            if not dry:
                r.mark(sid, "done", res.evidence)
            continue
        r.out("  ✗ %-15s [%s] %s — %s" % (sid, KIND_LABEL[s["kind"]], s["title"], res.evidence))
        for f in res.fixes:
            r.out("      → %s" % f)
        if dry:
            continue
        if r.interactive:
            ans = _ask(r, "      [r]etry, [d]one, [s]kip with a reason, [q]uit? ")
            if ans.startswith("d"):
                r.mark(sid, "done", "confirmed by the maintainer")
                continue
            if ans.startswith("s"):
                reason = _ask(r, "      reason (it goes in the notes): ").strip()
                if reason:
                    r.mark(sid, "skipped", reason=reason)
                    r.note("%s skipped: %s" % (sid, reason))
                    continue
            if ans.startswith("r"):
                return run(r)
        r.mark(sid, "failed", res.evidence)
        return _stop(r, s, "fix it and rerun: tools/release.py %s   ·   or: --done %s   ·   or: --skip %s \"reason\""
                     % (r.version, sid, sid))
    if dry:
        r.out("\n(dry run: nothing was written)")
        return 0
    r.out("\n✓ %s: every step is done" % r.version)
    return 0


def _ask(r, prompt):
    try:
        return (r.ask(prompt) or "").strip().lower()
    except EOFError:
        return "q"


def _confirm(r, s):
    if not r.interactive:
        return False
    return _ask(r, "  ▶ %s [action] %s — run it? [y/N] " % (s["id"], s["title"])).startswith("y")


def _stop(r, s, how):
    r.out("\n⏸ stopped at %s (%s). %s" % (s["id"], s["title"], how))
    return 1


def status(r):
    steps = r.record["steps"]
    r.out("%s — record %s%s" % (r.version, r.path, "" if r.path.exists() else " (not started)"))
    for s in STEPS:
        st = steps.get(s["id"], {})
        mark = {"done": "✅", "skipped": "⤼", "failed": "✗"}.get(st.get("status"), "·")
        tail = st.get("reason") or st.get("evidence") or ""
        r.out("  %s %-15s %-9s %s%s" % (mark, s["id"], "[" + KIND_LABEL[s["kind"]] + "]", s["title"],
                                         (" — " + tail[:110]) if tail else ""))
    missing = ready_to_sign(r.record)
    r.out("ready to sign: %s" % ("yes" if not missing else "no — " + ", ".join(missing)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Publish a golem release, step by step.")
    ap.add_argument("version", help="the version to publish, vX.Y.Z (the maintainer chooses it)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="every check, no action, no question, nothing written")
    ap.add_argument("--done", action="append", default=[], metavar="ID", help="this reminder or action was done")
    ap.add_argument("--yes", action="append", default=[], metavar="ID", help="run this action")
    ap.add_argument("--skip", nargs=2, metavar=("ID", "REASON"), help="skip a step; the reason is recorded and goes in the notes")
    ap.add_argument("--from", dest="start", metavar="ID", help="redo from this step")
    ap.add_argument("--check-record", action="store_true", help="exit 0 only if every step before the signature is done "
                                                                  "(used by tools/release.sh)")
    a = ap.parse_args(argv)
    r = Release(a.version)
    if a.check_record:
        missing = ready_to_sign(r.record)
        if missing:
            print("the release record %s is not complete: %s" % (r.path, ", ".join(missing)), file=sys.stderr)
        return 1 if missing else 0
    if a.status:
        return status(r)
    return run(r, dry=a.dry_run, yes=a.yes, done=a.done, skip=a.skip, start=a.start)


if __name__ == "__main__":
    sys.exit(main())
