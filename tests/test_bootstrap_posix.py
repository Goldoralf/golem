# SPDX-License-Identifier: GPL-3.0-or-later
"""`curl -fsSL https://get.golem.fm | sh` lance le bootstrap avec /bin/sh — dash sur Ubuntu. Un `set -o pipefail`
nu le tuait à la ligne 9 (premier test en VM, 2026-10-15) ; `sh -n` ne le voit pas : il faut l'EXÉCUTER sous dash."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOT = os.path.join(ROOT, "provision", "bootstrap.sh")


@pytest.mark.skipif(os.name != "posix" or not shutil.which("dash"), reason="dash absent (Git for Windows ships one, but PATH and chmod are POSIX here)")
def test_le_bootstrap_demarre_sous_dash(tmp_path):
    # on coupe avant le réseau et le serveur : un faux python3 qui s'arrête dès que le script le sonde
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "python3").write_text("#!/bin/sh\necho FAKE-PY \"$@\"; exit 0\n")
    (fake / "python3").chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "GOLEM_SRC": ROOT, "HOME": str(tmp_path)}
    r = subprocess.run(["dash", BOOT], env=env, capture_output=True, text=True, timeout=60)
    assert "Illegal option" not in r.stderr, r.stderr
    assert "FAKE-PY" in r.stdout, (r.stdout, r.stderr)   # il est allé jusqu'au lancement de l'installateur


def test_aucun_appel_apt_ne_peut_poser_de_question():
    """L'installateur n'a pas de terminal : une question de paquet (jackd2, 2026-10-15) figeait l'installation. Chaque
    apt-get/dpkg -i porte DEBIAN_FRONTEND=noninteractive — sur sa ligne (sudo efface l'environnement), ou par un
    export en tête d'un script qui tourne déjà en root."""
    import glob
    import re
    bad = []
    for p in sorted(glob.glob(os.path.join(ROOT, "provision", "*.sh"))):
        src = open(p, encoding="utf-8").read()
        exported = "export DEBIAN_FRONTEND=noninteractive" in src
        for n, ln in enumerate(src.splitlines(), 1):
            code = ln.split("#", 1)[0]
            if not re.search(r"\b(apt-get|dpkg -i)\b", code) or "DEBIAN_FRONTEND=noninteractive" in code:
                continue
            if re.search(r"\bsudo\s+(apt-get|dpkg)", code) or not exported:
                bad.append(f"{os.path.basename(p)}:{n}: {ln.strip()}")
    assert not bad, "\n".join(bad)
