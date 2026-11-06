# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/golemfm-protocol.md suit le code — sinon il redevient un document de plus qui ment.

Deux tables sont lues et comparées au code :
  - §3 (la table dont l'en-tête commence par `| Action |`) : la première colonne, entre backticks, doit être
    EXACTEMENT `set(bridge.tones_jobs._HANDLERS)` ; la colonne Lane doit dire la voie que `lane_of` choisit ;
  - §4 (la table dont l'en-tête commence par `| Path |`) : chaque chaîne littérale `/api/ext/...` des fichiers
    `bridge/*.py` (lue par l'AST, f-strings et `%s` comprises) doit y figurer, et chaque chemin de la table doit
    prolonger un chemin réellement écrit dans le code (une coquille dans le document se voit).
Normalisation des deux côtés : la requête (`?…`) tombe, `{n'importe quoi}` / `%s` / `%d` deviennent `{}`,
un littéral qui finit par `/` (concaténé ensuite) vaut `…/{}`."""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "golemfm-protocol.md")
BRIDGE = os.path.join(ROOT, "bridge")


def _section(text, num):
    """Le corps de la section `## <num>…` jusqu'à la section `## ` suivante."""
    m = re.search(r"^## %s\b.*?$(.*?)(?=^## |\Z)" % re.escape(str(num)), text, re.M | re.S)
    assert m, f"section '## {num}' not found in {DOC}"
    return m.group(1)


def _table(section, header):
    """Les lignes (listes de cellules) de la table dont la 1re cellule d'en-tête vaut `header`."""
    lines = section.splitlines()
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.lstrip().startswith("|") and cells and cells[0] == header:
            rows = []
            for row in lines[i + 2:]:                     # saute l'en-tête et la ligne |---|
                if not row.lstrip().startswith("|"):
                    break
                # un `\|` dans une cellule est un caractère, pas un séparateur
                rows.append([c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))])
            return rows
    raise AssertionError(f"no table with header '| {header} |' in this section of {DOC}")


def _first_code(cell):
    m = re.search(r"`([^`]+)`", cell)
    return m.group(1) if m else None


def _norm(path):
    p = path.split("?", 1)[0]
    p = re.sub(r"\{[^}]*\}|%[sd]", "{}", p)
    return p[:-1] + "/{}" if p.endswith("/") else p


def _code_paths():
    """{chemin normalisé: [fichier:ligne]} de chaque littéral qui COMMENCE par /api/ext/ dans bridge/*.py."""
    found = {}
    for name in sorted(os.listdir(BRIDGE)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(BRIDGE, name), encoding="utf-8").read())
        joined_parts = set()
        for node in ast.walk(tree):
            raw = None
            if isinstance(node, ast.JoinedStr):
                raw = "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
                              for v in node.values)
                joined_parts.update(id(v) for v in node.values)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in joined_parts:
                raw = node.value
            if raw and raw.startswith("/api/ext/"):
                found.setdefault(_norm(raw), []).append(f"{name}:{node.lineno}")
    return found


def _doc():
    with open(DOC, encoding="utf-8") as f:
        return f.read()


def test_job_table_lists_exactly_the_handlers():
    from bridge import tones_jobs
    rows = _table(_section(_doc(), 3), "Action")
    doc = [_first_code(r[0]) for r in rows]
    assert None not in doc, "a row of the §3 action table has no `action` in backticks"
    dupes = sorted({a for a in doc if doc.count(a) > 1})
    assert not dupes, f"actions listed twice in §3: {dupes}"
    code = set(tones_jobs._HANDLERS)
    missing, extra = sorted(code - set(doc)), sorted(set(doc) - code)
    assert not missing and not extra, (
        f"docs/golemfm-protocol.md §3 is out of date — missing actions: {missing}; "
        f"listed but not in _HANDLERS: {extra}")


def test_job_table_lanes_follow_the_prefix_rule():
    from bridge import tones_jobs
    wrong = []
    for r in _table(_section(_doc(), 3), "Action"):
        action, lane = _first_code(r[0]), (r[1].split() or [""])[0]
        if lane != tones_jobs.lane_of(action):
            wrong.append(f"{action}: doc says {lane!r}, lane_of says {tones_jobs.lane_of(action)!r}")
    assert not wrong, "§3 lane column disagrees with tones_jobs.lane_of: " + "; ".join(wrong)


def test_ext_paths_table_covers_the_code():
    code = _code_paths()
    assert code, "no /api/ext/ literal found in bridge/*.py — the scanner is broken"
    doc = {_norm(p) for p in (_first_code(r[0]) for r in _table(_section(_doc(), 4), "Path")) if p}
    missing = sorted(p for p in code if p not in doc)
    assert not missing, ("docs/golemfm-protocol.md §4 is missing /api/ext paths used by the bridge: "
                         + "; ".join(f"{p} ({', '.join(code[p])})" for p in missing))


def test_ext_paths_table_has_no_invented_path():
    code = set(_code_paths())
    doc = [_first_code(r[0]) for r in _table(_section(_doc(), 4), "Path")]
    assert None not in doc, "a row of the §4 path table has no `/api/ext/...` path in backticks"
    stem = lambda p: p[:-3] if p.endswith("/{}") else p
    invented = sorted(p for p in doc
                      if not any(_norm(p) == c or _norm(p).startswith(stem(c) + "/") for c in code))
    assert not invented, f"§4 lists paths that no bridge/*.py literal starts: {invented}"
