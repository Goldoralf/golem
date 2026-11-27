#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quand l'interface du golem change : QUOI mettre à jour dans la doc des musiciens (docs/user-docs.md §8).

Compare deux instantanés d'usine de la même variante (`tools/shell_snapshot.py --factory`) — l'épinglé et le nouveau —
exemple par exemple, puis dit quelles pages de doc citent les exemples touchés :

    python tools/doc-impact.py OLD_SNAPSHOT NEW_SNAPSHOT [--pages DIR] [--json]

Pour chaque exemple : nouveau, disparu, ou changé — route ou clic changés, ancres apparues ou disparues, ancres
désormais masquées en ?shell=ro, lectures qui diffèrent, et le RENDU (si les dossiers de captures `<snapshot>-shots`
existent : part des pixels qui diffèrent, mesurée par Chrome). Puis les fichiers de l'app changés entre les deux commits
(`git diff --stat`). Les pages : chaque `::golem{… example="…"}` d'un dossier de pages (défaut ~/golem-doc-work/docs-pages)
qui cite un exemple touché, et chaque `halo=` qui vise une ancre disparue.

Ne touche rien : il lit deux dossiers et le dépôt."""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shell_snapshot  # noqa: E402 — les sections du menu (section_of)

# LE BRUIT : des lectures qui changent d'une extraction à l'autre SANS que rien n'ait changé pour le musicien — le disque
# libre, la charge du processeur, la date d'une sauvegarde. Le matériel (contrôleurs, carte son) n'en est pas : il est
# déclaré (tools/shell/reference-rack.json), une différence y est un vrai changement de la page Gear.
NOISE = re.compile(r"^/api/(storage|system|system/health|system/libraries|backups|backups/overview|health/\w+)(\?|$)")

PIXEL_THRESHOLD = 0.002          # sous 0,2 % des pixels : le curseur qui clignote, une horloge — pas un changement


def load(snap):
    with open(os.path.join(snap, "SNAPSHOT.json"), encoding="utf-8") as f:
        man = json.load(f)
    ex = {}
    for name in man.get("examples", []):
        with open(os.path.join(snap, "examples", name + ".json"), encoding="utf-8") as f:
            ex[name] = json.load(f)
    return man, ex


def shots_dir(snap):
    d = snap.rstrip("/") + "-shots"
    return d if os.path.isdir(d) else None


def pixel_diffs(pairs):
    """{name: part des pixels qui diffèrent} — les deux PNG peints sur un canvas de Chrome (Playwright, déjà requis par
    l'instantané). Taille différente = 1.0."""
    if not pairs:
        return {}
    import base64
    from playwright.sync_api import sync_playwright
    js = """async ([a, b]) => {
      const img = src => new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = src; });
      const [x, y] = await Promise.all([img(a), img(b)]);
      if (x.width !== y.width || x.height !== y.height) return 1;
      const px = i => { const c = document.createElement('canvas'); c.width = i.width; c.height = i.height;
        const g = c.getContext('2d'); g.drawImage(i, 0, 0); return g.getImageData(0, 0, i.width, i.height).data; };
      const p = px(x), q = px(y); let n = 0;
      for (let k = 0; k < p.length; k += 4) if (Math.abs(p[k]-q[k]) + Math.abs(p[k+1]-q[k+1]) + Math.abs(p[k+2]-q[k+2]) > 24) n++;
      return n / (p.length / 4);
    }"""
    data = lambda p: "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()  # noqa: E731
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        page = b.new_page()
        for name, (a, c) in pairs.items():
            out[name] = page.evaluate(js, [data(a), data(c)])
        b.close()
    return out


def compare(old, new):
    (mo, eo), (mn, en) = load(old), load(new)
    report = {"old_routes": {n: e.get("route", "") for n, e in eo.items()},
              "old": {"commit": mo.get("commit"), "name": mo.get("name")},
              "new": {"commit": mn.get("commit"), "name": mn.get("name")},
              "added": sorted(set(en) - set(eo)), "removed": sorted(set(eo) - set(en)), "changed": {}}
    so, sn = shots_dir(old), shots_dir(new)
    pairs = {}
    for name in sorted(set(eo) & set(en)):
        a, b = eo[name], en[name]
        d = {}
        for k in ("route", "click"):
            if a.get(k) != b.get(k):
                d[k] = [a.get(k), b.get(k)]
        aa, ab = set(a.get("anchors") or []), set(b.get("anchors") or [])
        if aa - ab:
            d["anchors_gone"] = sorted(aa - ab)
        if ab - aa:
            d["anchors_new"] = sorted(ab - aa)
        hidden = set(b.get("anchors_hidden") or []) - set(a.get("anchors_hidden") or [])
        if hidden:
            d["anchors_now_hidden"] = sorted(hidden)
        ra, rb = a.get("reads") or {}, b.get("reads") or {}
        reads = sorted(k for k in set(ra) | set(rb) if stable(ra.get(k)) != stable(rb.get(k)))
        if reads:
            d["reads"] = reads
        if so and sn and os.path.exists(os.path.join(so, name + ".png")) and os.path.exists(os.path.join(sn, name + ".png")):
            pairs[name] = (os.path.join(so, name + ".png"), os.path.join(sn, name + ".png"))
        if d:
            report["changed"][name] = d
    for name, frac in pixel_diffs(pairs).items():
        if frac > PIXEL_THRESHOLD:
            report["changed"].setdefault(name, {})["pixels"] = round(frac, 4)
    co, cn = mo.get("commit"), mn.get("commit")
    if co and cn and co != cn:
        r = subprocess.run(["git", "-C", ROOT, "diff", "--stat", co, cn, "--", "app/"], capture_output=True, text=True)
        report["app_files"] = [ln.split("|")[0].strip() for ln in r.stdout.splitlines() if "|" in ln]
    report["sections"] = by_section(report, en)
    return report


# CE QUI CHANGE À CHAQUE EXTRACTION sans rien dire de l'écran (mesuré le 2026-11-27 entre deux extractions du même code :
# aucun pixel ne différait, dix exemples « changés » quand même) : l'heure du démarrage du banc (`boot`), l'heure du
# relevé (`now`), un compteur de battement (`hb`), une durée dite en clair (« in use (screen, 3 s ago) »).
# Et, dans l'état : toute date Unix (`at`, `t`, `skipped_at`, `updated`…) et le disque libre du poste (`disk`).
VOLATILE_KEYS = {"boot", "now", "hb", "last_took", "disk"}
_AGO = re.compile(r"\b\d+(\.\d+)? ?(s|sec|min|h|d) ago\b")


def stable(x):
    """La même lecture sans ses horodatages : ce qu'on compare d'une coquille à l'autre."""
    if isinstance(x, dict):
        return {k: stable(v) for k, v in x.items() if k not in VOLATILE_KEYS}
    if isinstance(x, list):
        return [stable(v) for v in x]
    if isinstance(x, str):
        return _AGO.sub("N ago", x)
    if isinstance(x, (int, float)) and not isinstance(x, bool) and 1.5e9 < x < 2.5e9:
        return "<time>"                                  # une date Unix (2017 à 2049) : l'heure du relevé, pas un contenu
    return x


def to_review(d):
    """Un exemple changé demande-t-il une RELECTURE ? Oui dès que l'écran a bougé (route, clic, ancres, pixels) ou qu'une
    lecture de CONTENU diffère. Non quand seules des lectures volatiles diffèrent (disque libre, CPU, sauvegardes :
    NOISE) sans qu'un pixel bouge — du bruit, pas un changement de la doc."""
    if any(k in d for k in ("route", "click", "anchors_gone", "anchors_new", "anchors_now_hidden", "pixels")):
        return True
    return any(not NOISE.match(r.split(" ", 1)[-1]) for r in d.get("reads", []))


def by_section(report, new_examples):
    """{section: {status, review: […], noise: […], added: […], removed: […], gone: [ancres]}} — la relecture se fait
    section par section du menu ; `unchanged` : rien à relire dans cette section."""
    route = {n: e.get("route", "") for n, e in new_examples.items()}
    out = {}

    def sec(name):
        return out.setdefault(shell_snapshot.section_of(route.get(name, report.get("old_routes", {}).get(name, ""))),
                              {"review": [], "noise": [], "added": [], "removed": [], "gone": []})
    for name in report["added"]:
        sec(name)["added"].append(name)
    for name in report["removed"]:
        sec(name)["removed"].append(name)
    for name, d in report["changed"].items():
        s = sec(name)
        (s["review"] if to_review(d) else s["noise"]).append(name)
        s["gone"] += d.get("anchors_gone", [])
    for name in route:                                   # les sections où rien n'a bougé apparaissent aussi
        sec(name)
    for s in out.values():
        s["status"] = "changed" if s["review"] or s["added"] or s["removed"] else ("noise only" if s["noise"] else "unchanged")
    return {k: out[k] for k in sorted(out)}


def pages_citing(pages_dir, report):
    """{page: [raisons]} — les pages qui citent un exemple touché, ou visent une ancre disparue."""
    # seulement ce qui demande une relecture : un exemple dont seul du bruit a changé (disque, CPU) ne cite aucune page
    touched = {n for n, d in report["changed"].items() if to_review(d)} | set(report["removed"])
    gone = {an: name for name, d in report["changed"].items() for an in d.get("anchors_gone", [])}
    out = {}
    for dirpath, _dirs, files in os.walk(pages_dir):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            txt = open(path, encoding="utf-8").read()
            why = []
            for m in re.finditer(r'example="([^"]+)"', txt):
                if m.group(1) in touched:
                    why.append("example " + m.group(1))
            for m in re.finditer(r'halo="([^"]+)"', txt):
                for an in m.group(1).split():
                    if an in gone:
                        why.append("halo " + an + " gone")
            if why:
                out[os.path.relpath(path, pages_dir)] = sorted(set(why))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--pages", default=os.path.expanduser("~/golem-doc-work/docs-pages"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = compare(a.old, a.new)
    rep["pages"] = pages_citing(a.pages, rep) if os.path.isdir(a.pages) else {}
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    print("%s %s → %s" % (rep["new"]["name"], (rep["old"]["commit"] or "?")[:8], (rep["new"]["commit"] or "?")[:8]))
    for k in ("added", "removed"):
        if rep[k]:
            print("  examples %s: %s" % (k, ", ".join(rep[k])))
    # PAR SECTION DU MENU (2026-11-27) : ce qui est à relire, ce qui n'est que du bruit, ce qui n'a pas bougé
    secs = rep.get("sections") or {}
    print("  by section — to review: %d · noise only: %d · unchanged: %d" % (
        sum(1 for s in secs.values() if s["status"] == "changed"), sum(1 for s in secs.values() if s["status"] == "noise only"),
        sum(1 for s in secs.values() if s["status"] == "unchanged")))
    for name, s in secs.items():
        bits = []
        if s["review"]:
            bits.append("review " + ", ".join(s["review"]))
        if s["added"]:
            bits.append("new " + ", ".join(s["added"]))
        if s["removed"]:
            bits.append("removed " + ", ".join(s["removed"]))
        if s["gone"]:
            bits.append("anchors gone " + ", ".join(sorted(set(s["gone"]))))
        if s["noise"]:
            bits.append("noise (disk, CPU, backups): " + ", ".join(s["noise"]))
        print("  %-11s %-18s %s" % ({"changed": "TO REVIEW", "noise only": "noise only", "unchanged": "unchanged"}[s["status"]],
                                    name, "; ".join(bits)))
    for name, d in rep["changed"].items():
        print("  changed  %-32s %s" % (name, "; ".join("%s %s" % (k, v) for k, v in d.items())))
    if rep.get("app_files"):
        print("  app files: " + ", ".join(rep["app_files"]))
    for page, why in sorted(rep["pages"].items()):
        print("  page     %-32s %s" % (page, ", ".join(why)))
    if not (rep["added"] or rep["removed"] or rep["changed"]):
        print("  nothing changed for the doc")
    return 0


if __name__ == "__main__":
    sys.exit(main())
