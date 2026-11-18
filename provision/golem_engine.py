# SPDX-License-Identifier: GPL-3.0-or-later
"""Le Golem Engine — le moteur audio de golem (dépôt séparé Goldoralf/golem-engine, construit depuis Ardour,
GPL-2.0-or-later) — posé par l'installation, TOUJOURS, que REAPER soit coché ou non (docs/install-v2.md §1).

Le paquet autonome (golem-engine/golem/tools/bundle.py : le moteur, ses bibliothèques, son veilleur) est publié sur
Goldoralf/golem-binaries, release `golem-engine-<VERSION>`, ÉPINGLÉ à son empreinte comme golem-fx :
  · Linux   provision/downloads.sha256 — provision/install-golem-engine.sh le télécharge par fetch_verified et appelle
            `golem_engine.py --place ARCHIVE` ;
  · Windows / macOS : leur pins.json, clé `golem_engine` — le jour où le moteur y est porté (ASSETS le prévoit déjà ;
            sans épingle, install() le dit et ne pose rien).

Il va dans ~/opt/golem-engine (à côté de ~/opt/REAPER), sans droits d'administrateur. Le remplacement est ATOMIQUE :
l'archive est dépliée à côté, l'ancien moteur renommé `golem-engine.prev` (le retour arrière d'une mise à jour), le
nouveau prend sa place. Un ARBRE DE DEV (~/golem-engine, ou GOLEM_ENGINE_DIR) passe avant le paquet installé
(engine_dir) : la machine d'un développeur garde son build.

    python3 provision/golem_engine.py --check          # où est le moteur, quelle version ; rien n'est téléchargé
    python3 provision/golem_engine.py --place A.tar.gz # pose une archive DÉJÀ vérifiée (install-golem-engine.sh)
    python3 provision/golem_engine.py                  # Windows / macOS : télécharge, vérifie, pose
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "9.9-g2"    # la release épinglée (vide = aucune : l'installation le dit, sans échouer)
BASE = "https://github.com/Goldoralf/golem-binaries/releases/download/golem-engine-{version}"
ASSETS = {"linux": "golem-engine-linux-x86_64.tar.gz", "win32": "golem-engine-windows-x86_64.tar.gz",
          "darwin": "golem-engine-macos-universal.tar.gz"}
RUN = Path("golem") / "engine" / "run.sh"          # ce que le bridge lance (bridge/engine/ardour.py)
BY = "provision/golem_engine.py"


def _os(platform=None):
    p = platform or sys.platform
    return p if p in ("win32", "darwin") else "linux"


def installed_dir():
    return Path.home() / "opt" / "golem-engine"


def engine_dir(env=None, home=None):
    """Le dossier du moteur que golem lance : GOLEM_ENGINE_DIR, sinon un arbre de dev (~/golem-engine), sinon le paquet
    installé (~/opt/golem-engine). Rendu même s'il n'existe pas (le premier candidat) : l'appelant dit « pas installé ».
    LA MÊME RÈGLE est écrite dans bridge/engine/ardour.py et provision/lib-engine.sh (tests/test_golem_engine_install)."""
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    if env.get("GOLEM_ENGINE_DIR"):
        return Path(env["GOLEM_ENGINE_DIR"])
    cands = [home / "golem-engine", home / "opt" / "golem-engine"]
    return next((c for c in cands if (c / RUN).is_file()), cands[0])


def version_of(d):
    try:
        return (Path(d) / "VERSION").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def asset_url(platform=None):
    return BASE.format(version=VERSION) + "/" + ASSETS[_os(platform)]


def pin(platform=None):
    """{url, sha256} du paquet de CE système. RuntimeError (message en anglais : l'installateur le montre) s'il n'y a
    pas encore de release ou pas d'épingle pour ce système."""
    o = _os(platform)
    if not VERSION:
        raise RuntimeError("Golem Engine: no release is pinned yet")
    url = asset_url(platform)
    if o == "linux":
        for line in (HERE / "downloads.sha256").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and not line.startswith("#") and parts[1] == url:
                return {"url": url, "sha256": parts[0]}
        raise RuntimeError(f"Golem Engine: {url} is not pinned in provision/downloads.sha256")
    pins = json.loads((HERE / ("windows" if o == "win32" else "macos") / "pins.json").read_text(encoding="utf-8"))
    p = pins.get("golem_engine") or {}
    if not (p.get("url") and p.get("sha256")):
        raise RuntimeError("Golem Engine: not available on this system yet")
    return {"url": p["url"], "sha256": p["sha256"]}


def _safe_members(tar):
    """Les membres de l'archive, sous UN dossier de tête, sans chemin qui sort (lien ou « .. »)."""
    tops, out = set(), []
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if not parts or m.name.startswith("/") or ".." in parts:
            raise RuntimeError(f"Golem Engine: unsafe path in the archive: {m.name}")
        if (m.issym() or m.islnk()) and (m.linkname.startswith("/") or ".." in Path(m.linkname).parts):
            raise RuntimeError(f"Golem Engine: unsafe link in the archive: {m.name}")
        tops.add(parts[0])
        out.append(m)
    if len(tops) != 1:
        raise RuntimeError("Golem Engine: the archive must hold one top folder")
    return tops.pop(), out


def place(data, dest=None, log=print):
    """Déplie l'archive (octets) et la met à `dest`, atomiquement ; l'ancien moteur devient `<dest>.prev`. Rend la
    version posée. Une archive sans lanceur n'est jamais posée : l'ancien moteur reste."""
    dest = Path(dest) if dest else installed_dir()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
            top, members = _safe_members(t)
            t.extractall(tmp, members=members)             # noqa: S202 — membres filtrés ci-dessus
        root = tmp / top
        if not (root / RUN).is_file():
            raise RuntimeError("Golem Engine: the archive holds no engine launcher")
        prev = dest.with_name(dest.name + ".prev")
        if dest.exists():
            shutil.rmtree(prev, ignore_errors=True)
            dest.rename(prev)
        root.rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    v = version_of(dest)
    log(f"  ✓ Golem Engine {v or '?'} → {dest}")
    _record([dest, dest.with_name(dest.name + ".prev")])
    return v


def rollback(dest=None, log=print):
    """Le moteur d'avant reprend sa place (une mise à jour qui ne démarre pas). False s'il n'y en a pas."""
    dest = Path(dest) if dest else installed_dir()
    prev = dest.with_name(dest.name + ".prev")
    if not (prev / RUN).is_file():
        return False
    bad = dest.with_name(dest.name + ".bad")
    shutil.rmtree(bad, ignore_errors=True)
    if dest.exists():
        dest.rename(bad)
    prev.rename(dest)
    shutil.rmtree(bad, ignore_errors=True)
    log(f"  ↩ Golem Engine {version_of(dest) or '?'} is back")
    return True


def _record(paths):
    """Reçu d'install (docs/uninstall.md §2), dans un reçu qui EXISTE seulement ; jamais d'exception."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", HERE / "receipt.py")
        R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(R)
        if not R.exists():
            return
        for p in paths:
            R.add(str(p), "dir", BY, "engine")
    except Exception as e:
        print(f"  ⚠ install receipt not updated ({e})", file=sys.stderr)


def install(fetch=None, log=print, dest=None, platform=None):
    """Télécharge (ou `fetch(url) -> octets`), vérifie l'empreinte, pose. Rend la version, ou None quand rien n'est à
    poser ici (pas de release, système pas encore porté) — dit, jamais fatal : golem tourne alors sur REAPER."""
    try:
        p = pin(platform)
    except RuntimeError as e:
        log(f"  ⚠ {e}")
        return None
    data = fetch(p["url"]) if fetch else urllib.request.urlopen(p["url"], timeout=120).read()   # noqa: S310
    got = hashlib.sha256(data).hexdigest()
    if got != p["sha256"]:
        raise RuntimeError(f"Golem Engine: wrong checksum — expected {p['sha256']}, got {got}")
    return place(data, dest=dest, log=log)


def main(argv):
    if "--check" in argv:
        d = engine_dir()
        ok = (d / RUN).is_file()
        print(f"Golem Engine: {'installed' if ok else 'not installed'} — {d}" + (f" ({version_of(d) or 'dev tree'})" if ok else ""))
        return 0 if ok else 1
    if "--place" in argv:
        archive = Path(argv[argv.index("--place") + 1])
        place(archive.read_bytes())
        return 0
    return 0 if install() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
