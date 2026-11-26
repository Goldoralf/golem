# SPDX-License-Identifier: GPL-3.0-or-later
"""golem-fx — les effets de golem (dépôt séparé, GPL-3) — posés par l'installation sur les TROIS systèmes.

2026-11-15 : golem-fx 0.5 publie des VST3 précompilés pour Linux, Windows et macOS (release `golem-fx-0.5` de
Goldoralf/golem-binaries, vérifiée par golem-fx : 54 bundles « GoleM FX <Nom>.vst3 » à la racine de l'archive).
L'archive est ÉPINGLÉE à son empreinte, par système :
  · Linux   provision/downloads.sha256 — provision/install-golem-fx.sh la télécharge par fetch_verified
            (lib-fetch.sh) et appelle `golem_fx.py --place ARCHIVE` ;
  · Windows provision/windows/pins.json `golem_fx` ;
  · macOS   provision/macos/pins.json `golem_fx` ;
ces deux-là par install() ci-dessous, depuis `provision/desktop.py setup` (l'étape « golem itself »).

Pas de droits d'administrateur, nulle part : les bundles vont dans le dossier VST3 PAR UTILISATEUR que REAPER
parcourt déjà — ~/.vst3 (Linux, là où tools/golem-fx-install.py pose les builds de dev), %LOCALAPPDATA%\\Programs\\
Common\\VST3\\GoleM (Windows, à côté de Dragonfly et Surge), ~/Library/Audio/Plug-Ins/VST3 (macOS ; un
téléchargement par urllib ne porte pas l'attribut de quarantaine). bridge/rig.py golem_fx_dirs() y regarde.

Chaque bundle posé entre au reçu d'install (le désinstalleur le retire). Une pose qui échoue n'est jamais fatale :
les blocs gardent leurs plugins d'origine (guitarix, Calf, Dragonfly, Zam… restent installés).

Un BUILD DE DEV posé par tools/golem-fx-install.py (son journal ~/.local/share/golem/golem-fx-installed.json) est
plus neuf que la release : il est GARDÉ tel quel, et le journal de l'install le dit. La release est la base.

    python provision/golem_fx.py                 # Windows / macOS : télécharge, vérifie, pose
    python provision/golem_fx.py --check         # dit combien de bundles sont là, sans rien télécharger
    python3 provision/golem_fx.py --place A.tgz  # Linux (install-golem-fx.sh) : pose une archive DÉJÀ vérifiée
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "0.7"
BASE = f"https://github.com/Goldoralf/golem-binaries/releases/download/golem-fx-{VERSION}"
ASSETS = {"linux": "golem-fx-linux-x86_64.tar.gz", "win32": "golem-fx-windows-x86_64.zip",
          "darwin": "golem-fx-macos-universal.tar.gz"}
PREFIX = "GoleM FX "
JOURNAL = Path.home() / ".local" / "share" / "golem" / "golem-fx-installed.json"
# LA RELEASE POSÉE (2026-11-26, passage à 0.7) : {version, dest, at}, écrit par place(). Sans elle, needed() ne voyait que
# l'ABSENCE de bundles — un golem mis à jour par Settings ▸ About gardait sa 0.6 pour toujours.
STAMP = Path.home() / ".local" / "share" / "golem" / "golem-fx-release.json"
BY = "provision/golem_fx.py"


def _os(platform=None):
    p = platform or sys.platform
    return p if p in ("win32", "darwin") else "linux"


def dest_dir(platform=None):
    o = _os(platform)
    if o == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "Programs" / "Common" / "VST3" / "GoleM"
    if o == "darwin":
        return Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3"
    return Path.home() / ".vst3"


def pin(platform=None):
    """{url, sha256} de l'archive de CE système, lus là où ce système épingle ses téléchargements."""
    o = _os(platform)
    if o == "linux":
        url = f"{BASE}/{ASSETS['linux']}"
        for line in (HERE / "downloads.sha256").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and not line.startswith("#") and parts[1] == url:
                return {"url": url, "sha256": parts[0]}
        raise RuntimeError(f"golem-fx: {url} is not pinned in provision/downloads.sha256")
    pins = json.loads((HERE / ("windows" if o == "win32" else "macos") / "pins.json").read_text(encoding="utf-8"))
    p = pins.get("golem_fx") or {}
    if not (p.get("url") and p.get("sha256")):
        raise RuntimeError("golem-fx: no pinned URL or checksum in pins.json")
    return {"url": p["url"], "sha256": p["sha256"]}


def dev_builds(journal=None):
    """Les bundles qu'un build de dev a posés (tools/golem-fx-install.py) : {nom: entrée du journal}."""
    try:
        data = json.loads(Path(journal or JOURNAL).read_text(encoding="utf-8"))
        inst = data.get("installed") if isinstance(data, dict) else None
        return inst if isinstance(inst, dict) else {}
    except (OSError, ValueError):
        return {}


def _members(data, name):
    """[(chemin relatif « GoleM FX X.vst3/… », est-un-dossier, mode, lecteur d'octets)] de l'archive. Refuse ce qui
    sortirait de la racine, un lien, et tout ce qui n'est pas dans un bundle GoleM FX."""
    out = []
    if name.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(data))
        for info in z.infolist():
            mode = (info.external_attr >> 16) & 0o777
            out.append((info.filename, info.is_dir(), mode or (0o755 if info.is_dir() else 0o644),
                        (lambda i=info: z.read(i))))
    else:
        t = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
        for m in t.getmembers():
            if not (m.isdir() or m.isfile()):
                raise RuntimeError(f"golem-fx: unexpected entry {m.name} (link or device)")
            out.append((m.name, m.isdir(), m.mode & 0o777, (lambda m=m: t.extractfile(m).read())))
    rows = []
    for raw, is_dir, mode, read in out:
        rel = raw.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        rel = rel.rstrip("/")
        if not rel:
            continue
        parts = rel.split("/")
        if rel.startswith("/") or ".." in parts or ":" in parts[0]:
            raise RuntimeError(f"golem-fx: unsafe path {raw}")
        if not (parts[0].startswith(PREFIX) and parts[0].endswith(".vst3")):
            continue                                    # BUILDINFO, SHA256SUMS… : pas des plugins
        rows.append((rel, is_dir, mode, read))
    return rows


def place(data, name, dest, journal=None, log=print, stamp=None):
    """Pose les bundles de l'archive (octets DÉJÀ vérifiés) dans dest. Rend (posés, gardés) : les chemins posés,
    et les noms gardés parce qu'un build de dev les a mis là."""
    dest = Path(dest)
    rows = _members(data, name)
    bundles = sorted({r[0].split("/")[0] for r in rows})
    if not bundles:
        raise RuntimeError("golem-fx: no « GoleM FX … .vst3 » bundle in the archive")
    dev = dev_builds(journal)
    dest.mkdir(parents=True, exist_ok=True)
    posed, kept = [], []
    for b in bundles:
        stem = b[:-len(".vst3")]
        final = dest / b
        if stem in dev and final.is_dir():
            kept.append(stem)
            continue
        # posé à côté puis renommé : un REAPER qui scanne ne voit jamais un bundle à moitié copié
        tmp = dest / (b + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        for rel, is_dir, mode, read in rows:
            if rel.split("/")[0] != b:
                continue
            out = tmp.joinpath(*rel.split("/")[1:])
            if is_dir:
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(read())
            if os.name != "nt":
                os.chmod(out, (mode or 0o644) & 0o755 | 0o600)   # l'exécutable reste exécutable (macOS, .so)
        if final.exists():
            shutil.rmtree(final)
        os.replace(tmp, final)
        posed.append(final)
    if kept:
        log(f"  = golem-fx: {len(kept)} dev build(s) from tools/golem-fx-install.py kept as is "
            f"({', '.join(sorted(kept)[:6])}{'…' if len(kept) > 6 else ''})")
    _record(posed)
    _stamp(dest, stamp)
    log(f"✓ golem-fx {VERSION}: {len(posed)} plugin(s) → {dest} (golem's audio engine sees them at its next start)")
    return posed, kept


def _stamp(dest, stamp=None):
    """Note la release posée (needed() la relit). Jamais d'exception : un tampon manquant fait seulement reposer."""
    try:
        import time
        path = Path(stamp or STAMP)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps({"version": VERSION, "dest": str(dest),
                                   "at": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        print(f"  ⚠ golem-fx release not noted ({e})", file=sys.stderr)


def _record(paths):
    """Reçu d'install (docs/uninstall.md §2), dans un reçu qui EXISTE seulement ; jamais d'exception. Un bundle
    golem-fx est à golem par son nom : jamais « existait avant » (une réinstallation le repose)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golem_receipt", HERE / "receipt.py")
        R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(R)
        if not R.exists():
            return
        for p in paths:
            R.add(str(p), "dir", BY, "plugins")
    except Exception as e:
        print(f"  ⚠ install receipt not updated ({e})", file=sys.stderr)


def found(dest=None):
    dest = Path(dest or dest_dir())
    try:
        return sorted(p.name for p in dest.iterdir() if p.name.startswith(PREFIX) and p.name.endswith(".vst3"))
    except OSError:
        return []


def installed_version(stamp=None):
    """La release golem-fx que place() a posée sur cette machine, ou None (jamais posée, ou posée avant le tampon)."""
    try:
        v = json.loads(Path(stamp or STAMP).read_text(encoding="utf-8")).get("version")
        return v if isinstance(v, str) and v else None
    except (OSError, ValueError, AttributeError):
        return None


def needed(dest=None, stamp=None, journal=None):
    """LE RATTRAPAGE APRÈS UNE MISE À JOUR (docs/update.md §3 bis) : à poser quand
      · aucun bundle golem-fx n'est sur cette machine (2026-11-22 : un golem d'avant golem-fx, v0.6.4, se retrouvait
        avec une usine refaite sur des effets qu'il n'avait pas) ;
      · ou la release posée n'est pas celle qu'épingle CE code (2026-11-26) : Settings ▸ About ▸ Update pose le code,
        pas les plugins — sans ce test, un golem installé en 0.6 la gardait. Une pose d'avant le tampon compte
        comme ancienne : elle est reposée une fois.
    SAUF si chaque bundle présent vient d'un build de dev (tools/golem-fx-install.py) : le développeur choisit ses
    plugins, et place() les garderait de toute façon. Les lanceurs (reload.sh, start.sh, desktop.py) posent alors
    avant que REAPER ne relise ses plugins."""
    have = found(dest)
    if not have:
        return True
    if installed_version(stamp) == VERSION:
        return False
    dev = dev_builds(journal)
    return not all(n[:-len(".vst3")] in dev for n in have)


def install(fetch=None, log=print, dest=None, platform=None, journal=None, timeout=300):
    """Windows / macOS : télécharge l'archive épinglée, vérifie son empreinte, pose les bundles. `fetch(url) -> bytes`
    remplaçable par les tests."""
    o = _os(platform)
    if o == "linux" and dest is None:
        raise RuntimeError("golem-fx: on Linux, provision/install-golem-fx.sh installs it (pinned fetch)")
    p = pin(o)
    if fetch is None:
        def fetch(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (golem install)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
    name = p["url"].rsplit("/", 1)[-1]
    log(f"→ downloading {name} (golem-fx {VERSION}, GPL-3)")
    data = fetch(p["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != p["sha256"]:
        raise RuntimeError(f"golem-fx archive changed upstream (sha256 {got[:12]}…, pinned {p['sha256'][:12]}…) "
                           "— not installed")
    return place(data, name, dest or dest_dir(o), journal=journal, log=log)


def main(argv):
    if "--check" in argv:
        n = found()
        print(f"{'✓' if n else '✗'} {len(n)} golem-fx plugin(s) in {dest_dir()}")
        return 0 if n else 1
    if "--needed" in argv:                       # 0 : à poser (aucun bundle) ; 1 : rien à faire
        return 0 if needed() else 1
    if "--place" in argv:
        i = argv.index("--place")
        if i + 1 >= len(argv):
            print("usage: golem_fx.py --place ARCHIVE [--dest DIR]", file=sys.stderr)
            return 2
        archive = Path(argv[i + 1])
        dest = Path(argv[argv.index("--dest") + 1]) if "--dest" in argv else dest_dir()
        place(archive.read_bytes(), archive.name, dest)
        return 0
    install()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
