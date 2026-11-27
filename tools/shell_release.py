#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LA COQUILLE VIDE D'UNE RELEASE, d'une seule commande (docs/release-tool-plan.md §3 bis, étape 6, 2026-11-27).

    tools/shell_release.py v0.7.3

fait, sur le rack, tout ce qui se faisait à la main entre trois sessions :
  1. VÉRIFIE ce qu'il lui faut (le kit de référence : le rack déclaré et la prise de démo ; un moteur de banc ; la
     coquille en ligne, pour comparer) ;
  2. EXTRAIT la coquille complète au commit du tag — son propre bridge et son propre moteur, à côté du rack qui joue ;
  3. la CONTRÔLE : aucun exemple en échec, aucune lecture refusée, le kit à la bonne forme ;
  4. MESURE l'impact sur la doc par rapport à la coquille en ligne, section par section du menu ;
  5. écrit la REMISE (`HANDOVER.md`) : ce que golem.fm doit ré-épingler, les sections à relire, les ancres parties, les
     pages de doc concernées, les commandes à lancer.

Tout va dans `~/golem-doc-work/pin-<commit>/` (la coquille `factory/`, ses captures `factory-shots/`, `extract.log`,
`impact.txt`, `impact.json`, `HANDOVER.md`). L'outil ne touche à AUCUN autre dépôt et ne publie rien : golem.fm ré-épingle
de son côté (`sync_golem_app.py`), avec la remise sous les yeux.

    --rev            un commit au lieu d'un tag (la version se dit alors par `git describe`)
    --previous DIR   la coquille à laquelle comparer (défaut : celle que golem.fm sert, cherchée dans ~/golem-doc-work)
    --keep           garder une extraction déjà faite à ce commit, ne refaire que le contrôle, l'impact et la remise
    --no-engine      sans moteur de banc (plus rapide ; Health, looper et arrangement montrent un rack qui ne joue pas)

Rend 0 quand la coquille est bonne à remettre, 1 sinon (et dit quoi refaire : `shell_snapshot.py --section … --merge-into`).
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shell_overlay    # noqa: E402
import shell_snapshot   # noqa: E402

WORK = os.path.expanduser("~/golem-doc-work")
FM = os.path.expanduser("~/code/maestrium")
RACK_BRIDGE = "http://localhost:8770"


def _git(*args):
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _doc_impact():
    spec = importlib.util.spec_from_file_location("doc_impact", os.path.join(ROOT, "tools", "doc-impact.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def resolve(rev):
    """(commit, version) : le commit du tag ou de la révision, et le nom de version de la coquille."""
    commit = _git("rev-parse", "--verify", rev + "^{commit}")
    if not commit:
        raise SystemExit("✗ %s is not a tag or a commit of this repository" % rev)
    exact = _git("describe", "--tags", "--exact-match", commit)
    return commit, exact or _git("describe", "--tags", commit) or commit[:8]


def online_shell(fm=FM, work=WORK):
    """La coquille que golem.fm sert : (commit, dossier de son instantané dans ~/golem-doc-work, ou None)."""
    try:
        with open(os.path.join(fm, "frontend", "public", "golem-app", "SOURCE.json"), encoding="utf-8") as f:
            commit = json.load(f).get("commit")
    except (OSError, ValueError):
        return None, None
    if not commit:
        return None, None
    d = os.path.join(work, "pin-" + commit[:8], "factory")
    return commit, d if os.path.isfile(os.path.join(d, "SNAPSHOT.json")) else None


def preconditions(overlay, engine, kit):
    """Ce qui manque pour une coquille complète : [] quand tout est là."""
    bad = []
    if not overlay.rack():
        bad.append("no declared reference rack (%s)" % shell_overlay.RACK_FILE)
    if not overlay.media():
        bad.append("no demo take in the reference kit (%s/demo-take) — record it once from a snapshot that has it: "
                   "tools/shell_overlay.py --record-take <snapshot dir> <kit dir>" % (kit or shell_overlay.kit_dir()))
    if engine:
        try:
            shell_snapshot.golem_engine_env("/tmp")
        except SystemExit as e:
            bad.append("%s — or run with --no-engine" % e)
    try:
        import playwright  # noqa: F401
    except ImportError:
        bad.append("Playwright is not installed in this Python (use .venv/bin/python)")
    return bad


def problems(snap_dir):
    """Ce qui empêche de remettre cette coquille : [] quand elle est bonne. Chaque ligne dit quoi refaire."""
    try:
        with open(os.path.join(snap_dir, "SNAPSHOT.json"), encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError) as e:
        return ["no SNAPSHOT.json in %s (%s)" % (snap_dir, e)]
    bad = []
    for e in man.get("examples_failed") or []:
        sec = shell_snapshot.section_of(e.get("route", ""))
        bad.append("example %s failed (%s) — fix it, then: tools/shell_snapshot.py --factory --rev %s --section %s --out <tmp> "
                   "--merge-into %s" % (e["name"], e.get("why"), str(man.get("commit"))[:8], sec, snap_dir))
    if man.get("refused"):
        bad.append("reads refused, a trace was left after redaction: %s" % ", ".join(man["refused"][:5]))
    if man.get("failed"):
        bad.append("reads failed: %s" % ", ".join(man["failed"][:5]))
    for w in man.get("kit_warnings") or []:
        bad.append("reference kit: %s" % w)
    if not (man.get("rack") or {}).get("complete"):
        bad.append("the reference rack is incomplete: %s" % ", ".join((man.get("rack") or {}).get("missing") or ["?"]))
    if man.get("partial") or man.get("kind") != "factory":
        bad.append("this is not a full factory snapshot")
    want = {ex["name"] for ex in shell_snapshot.EXAMPLES}
    missing = sorted(want - set(man.get("examples") or []) - {e["name"] for e in man.get("examples_failed") or []})
    if missing:
        bad.append("examples not made: %s" % ", ".join(missing))
    return bad


def handover(version, commit, snap_dir, man, rep, prev_commit, bad):
    """La remise, en Markdown : ce que golem.fm lit avant de ré-épingler."""
    out = ["# Empty shell %s — handover" % version, "",
           "- golem commit: `%s`" % commit,
           "- snapshot: `%s` (name `%s`, %d examples, %d reads, catalogue %s, made %s)" % (
               snap_dir, man.get("name"), len(man.get("examples") or []), len(man.get("reads") or []),
               man.get("catalog_version"), man.get("made")),
           "- reference kit: " + "; ".join("%s (recorded at %s)" % (k.get("what"), str((k.get("recorded") or {}).get("commit"))[:8])
                                             for k in man.get("reference_kit") or []) or "- reference kit: none",
           "- compared with the shell online: `%s`" % (prev_commit or "not found — no impact measured"), ""]
    if bad:
        out += ["## NOT ready to hand over", ""] + ["- " + b for b in bad] + [""]
    if rep:
        secs = rep.get("sections") or {}
        out += ["## Sections of the menu", "", "| Section | Status | Examples to review | Anchors gone |", "|---|---|---|---|"]
        for name, s in secs.items():
            out.append("| %s | %s | %s | %s |" % (name, s["status"], ", ".join(s["review"] + s["added"]) or "—",
                                                  ", ".join(sorted(set(s["gone"]))) or "—"))
        if rep.get("added") or rep.get("removed"):
            out += ["", "Examples new: %s. Removed: %s." % (", ".join(rep.get("added") or []) or "none",
                                                           ", ".join(rep.get("removed") or []) or "none")]
        out += ["", "## Doc pages to look at", ""]
        pages = rep.get("pages") or {}
        out += ["- `%s`: %s" % (p, ", ".join(why)) for p, why in sorted(pages.items())] or ["None cites a changed example."]
        out.append("")
    out += ["## What golem.fm runs", "",
            "```", "cd ~/code/maestrium/backend && uv run python tools/sync_golem_app.py %s --snapshot %s" % (commit, snap_dir),
            "uv run pytest -q tests/test_golem_app_vendor.py", "```", "",
            "While golem-site lives: `python3 tools/update_site.py --commit %s --snapshot %s --no-graft`." % (commit, snap_dir), ""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The empty shell of a release, in one command.")
    ap.add_argument("version", nargs="?", help="the golem tag the shell comes from (v0.7.3)")
    ap.add_argument("--rev", help="a commit instead of a tag")
    ap.add_argument("--previous", help="the shell to compare with (default: the one golem.fm serves)")
    ap.add_argument("--keep", action="store_true", help="keep an extraction already made at this commit")
    ap.add_argument("--no-engine", action="store_true")
    ap.add_argument("--kit", help="the reference kit's folder (default $GOLEM_SHELL_KIT or ~/golem-doc-work/reference)")
    ap.add_argument("--work", default=WORK, help="where the pin folders live (default ~/golem-doc-work)")
    a = ap.parse_args(argv)
    if not (a.version or a.rev):
        ap.error("give a tag (v0.7.3) or --rev <commit>")
    commit, version = resolve(a.rev or a.version)
    pin = os.path.join(a.work, "pin-" + commit[:8])
    snap = os.path.join(pin, "factory")
    print("empty shell %s — golem %s → %s" % (version, commit[:8], pin))

    overlay = shell_overlay.Overlay.load(kit=a.kit, log=lambda m: print("  " + m))
    pre = preconditions(overlay, not a.no_engine, a.kit)
    if pre:
        for p in pre:
            print("✗ " + p)
        return 1

    if a.keep and os.path.isfile(os.path.join(snap, "SNAPSHOT.json")):
        print("1. extraction kept (%s)" % snap)
    else:
        os.makedirs(snap, exist_ok=True)
        log_path = os.path.join(pin, "extract.log")
        print("1. extracting — about ten minutes, its own bridge and engine (log: %s)" % log_path)
        t0 = time.monotonic()
        # le Detect du pédalier n'est PAS rejoué sur le rack : le rack est déclaré (aucune écriture MIDI vers le rack qui joue)
        sep = RACK_BRIDGE if _answers(RACK_BRIDGE) else None
        with open(log_path, "w", encoding="utf-8") as lf:
            def log(msg):
                lf.write(str(msg) + "\n")
                lf.flush()
            os.environ.setdefault("GOLEM_NO_HW_MIDI", "1")
            try:
                shell_snapshot.factory_snapshot(snap, commit, log=log, engine=not a.no_engine, overlay=overlay,
                                                separation=sep, reference="http://127.0.0.1:9", version=version)
            except BaseException as e:
                log("ABORTED: %r" % (e,))
                print("✗ the extraction stopped: %s (see %s)" % (e, log_path))
                return 1
        print("   done in %d min %02d s" % divmod(int(time.monotonic() - t0), 60))

    with open(os.path.join(snap, "SNAPSHOT.json"), encoding="utf-8") as f:
        man = json.load(f)
    bad = problems(snap)
    print("2. control: %d examples, %d reads — %s" % (len(man.get("examples") or []), len(man.get("reads") or []),
                                                     "ok" if not bad else "%d problem(s)" % len(bad)))
    for b in bad:
        print("   ✗ " + b)

    prev_commit, prev = online_shell(work=a.work)
    if a.previous:
        prev, prev_commit = a.previous, (json.load(open(os.path.join(a.previous, "SNAPSHOT.json"), encoding="utf-8")).get("commit"))
    rep = None
    if prev and os.path.abspath(prev) != os.path.abspath(snap):
        print("3. doc impact against the shell online (%s)" % str(prev_commit)[:8])
        di = _doc_impact()
        rep = di.compare(prev, snap)
        pages = os.path.join(FM, "frontend", "src", "content", "docs")
        rep["pages"] = di.pages_citing(pages, rep) if os.path.isdir(pages) else {}
        with open(os.path.join(pin, "impact.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            di.main([prev, snap, "--pages", pages])
        with open(os.path.join(pin, "impact.txt"), "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        for name, s in (rep.get("sections") or {}).items():
            if s["status"] != "unchanged":
                print("   %-10s %-18s %s" % ("TO REVIEW" if s["status"] == "changed" else "noise only", name,
                                            ", ".join(s["review"] + s["added"]) or ""))
        same = sum(1 for s in (rep.get("sections") or {}).values() if s["status"] == "unchanged")
        print("   %d section(s) unchanged · %d doc page(s) to look at" % (same, len(rep["pages"])))
    else:
        print("3. doc impact: no previous shell found in %s (pin-%s) — not measured" % (a.work, str(prev_commit)[:8]))

    text = handover(version, commit, snap, man, rep, prev_commit, bad)
    with open(os.path.join(pin, "HANDOVER.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print("4. handover written: %s" % os.path.join(pin, "HANDOVER.md"))
    print("✓ shell %s is ready to hand over to golem.fm" % version if not bad else "✗ shell %s is NOT ready" % version)
    return 1 if bad else 0


def _answers(base):
    import urllib.request
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=2) as r:     # noqa: S310
            return r.status == 200
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
