# SPDX-License-Identifier: GPL-3.0-or-later
"""Les binaires du provisioning sont vérifiés (audit 2026-10-15, lot 5) : provision/lib-fetch.sh refuse une URL non
épinglée et un fichier dont l'empreinte ne correspond pas ; provision/downloads.sha256 est bien formé et couvre chaque
URL de binaire écrite en dur dans les scripts."""
import hashlib
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMS = os.path.join(ROOT, "provision", "downloads.sha256")
LIB = os.path.join(ROOT, "provision", "lib-fetch.sh")


def _table():
    rows = {}
    for ln in open(SUMS, encoding="utf-8"):
        if ln.strip() and not ln.startswith("#"):
            sha, url = ln.split()
            assert re.fullmatch(r"[0-9a-f]{64}", sha), ln
            assert url.startswith("https://"), ln
            rows[url] = sha
    return rows


def test_la_table_est_bien_formee_et_sans_doublon():
    lines = [ln for ln in open(SUMS, encoding="utf-8") if ln.strip() and not ln.startswith("#")]
    assert len(_table()) == len(lines) >= 10


def test_les_urls_ecrites_en_dur_sont_epinglees():
    rows = _table()
    for script in ("plugins.sh", "plugins-deb.sh", "fetch-assets.sh"):
        src = "\n".join(ln for ln in open(os.path.join(ROOT, "provision", script), encoding="utf-8")
                        if not ln.lstrip().startswith("#"))                     # une ligne commentée ne télécharge rien
        for url in re.findall(r'"(https://[^"$]+\.(?:deb|zip|tgz|tar\.gz|tar\.xz|so))"', src):
            assert url in rows, f"{script} : {url}"


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("curl")), reason="bash/curl absents")
@pytest.mark.skipif(os.name != "posix", reason="the shell library (bash, sha256sum, file://) is POSIX")
def test_fetch_verified_garde_le_bon_refuse_le_faux_et_le_non_epingle(tmp_path):
    blob = tmp_path / "plugin.tgz"
    blob.write_bytes(b"un binaire")
    url = "file://" + str(blob)
    sums = tmp_path / "sums"

    def run(table):
        sums.write_text(table)
        dest = tmp_path / "out"
        if dest.exists():
            dest.unlink()
        r = subprocess.run(["bash", "-c", f'. "{LIB}"; fetch_verified "$1" "$2"', "_", url, str(dest)],
                           env={**os.environ, "GOLEM_SUMS": str(sums)}, capture_output=True, text=True)
        return r.returncode, dest.exists(), r.stderr

    good = hashlib.sha256(b"un binaire").hexdigest()
    assert run(f"{good}  {url}\n")[:2] == (0, True)
    rc, kept, err = run(f"{'0' * 64}  {url}\n")
    assert (rc, kept) == (1, False) and "EMPREINTE FAUSSE" in err
    rc, kept, err = run("")
    assert (rc, kept) == (1, False) and "non épinglé" in err
