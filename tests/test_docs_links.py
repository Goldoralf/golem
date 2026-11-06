# SPDX-License-Identifier: GPL-3.0-or-later
"""Les docs PUBLIÉS tiennent debout : aucun lien relatif mort, aucun renvoi vers docs/archive/ ou docs/private/ (ils ne
partent pas dans le dépôt public), et l'index docs/README.md cite chaque doc publié. Sans ce test, une référence
périme en silence — c'est ce qui était arrivé à maestrium-exchange.md (16 jobs manquants)."""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNPUBLISHED = ("docs/archive/", "docs/private/")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _published_md():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
                         capture_output=True, text=True).stdout.split()
    return [f for f in out if not f.startswith(UNPUBLISHED) and os.path.isfile(os.path.join(ROOT, f))]


def test_aucun_lien_mort_ni_vers_le_non_publie():
    bad = []
    for f in _published_md():
        here = os.path.dirname(f)
        for m in LINK.finditer(open(os.path.join(ROOT, f), encoding="utf-8").read()):
            target = m.group(1).split("#")[0]
            if not target or re.match(r"^[a-z]+:|^/", target):
                continue
            p = os.path.normpath(os.path.join(here, target))
            if not os.path.exists(os.path.join(ROOT, p)):
                bad.append(f"{f} → {target} (absent)")
            elif p.startswith(UNPUBLISHED):
                bad.append(f"{f} → {target} (non publié)")
    assert not bad, "liens à réparer :\n" + "\n".join(bad)


def test_l_index_cite_chaque_doc_publie():
    index = open(os.path.join(ROOT, "docs", "README.md"), encoding="utf-8").read()
    missing = [f for f in _published_md()
               if f.startswith("docs/") and f != "docs/README.md" and os.path.relpath(f, "docs").replace(os.sep, "/") not in index]
    assert not missing, "absents de docs/README.md :\n" + "\n".join(missing)
