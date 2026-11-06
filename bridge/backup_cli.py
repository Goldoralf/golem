# SPDX-License-Identifier: GPL-3.0-or-later
"""La sauvegarde COMPLÈTE avant désinstallation (docs/uninstall.md §6), en ligne de commande — bridge arrêté, sans HTTP.

    python -m bridge.backup_cli full --dest DIR [--secrets] [--json]
    python -m bridge.backup_cli estimate --dest DIR [--secrets]     (JSON ; ne lit que des tailles, n'écrit rien)

Écrit dans DIR (jamais dans le dossier d'install, qui va disparaître) :
  golem-all-<ts>.zip      la catégorie `all` (backup.build) — restaurable par ⇅ I/O
  golem-songs-<ts>.zip    la catégorie `songs` — restaurable par ⇅ I/O
  identity/serial.json    le numéro à vie du rack (gardé par décision, 2026-10-15)
  identity/reaper-license.rk   la licence REAPER, si elle existe
  secrets/                SEULEMENT avec --secrets : integrations.json, auth-devices.json, network.json, .env
  captures/               les captures de l'utilisateur (le travail de bridge/plugin_capture.py, HORS du dossier
                          d'install : %LOCALAPPDATA%\\GoleM\\captures, ~/.cache/golem-build/captures — §9.5)
  README.txt              ce qu'est chaque fichier et comment le remettre

Puis VÉRIFIE : chaque zip relu, chaque sha256 du manifeste et l'empreinte globale (la vérification de l'import,
importer._verify) ; chaque copie comparée à sa source. Code de sortie ≠ 0 et message clair au moindre écart."""
import argparse
import json
import os
import shutil
import sys
import time
import zipfile

from . import backup as B
from . import config as C

MARGIN = 1.10                      # marge sur l'estimation (en-têtes zip, manifeste)
SLACK = 32 * 1024 * 1024           # + de quoi ne pas remplir le disque à l'octet près


class BackupFailed(Exception):
    pass


def identity_files():
    """(nom dans la sauvegarde, source) de l'identité du rack."""
    from . import serial
    return [("identity/serial.json", serial._path()),
            ("identity/reaper-license.rk", os.path.join(C.reaper_resource_dir(), "reaper-license.rk"))]


def secret_files():
    return [("secrets/integrations.json", os.path.join(C.CONFIG_DIR, "integrations.json")),
            ("secrets/auth-devices.json", os.path.join(C.CONFIG_DIR, "auth-devices.json")),
            ("secrets/network.json", os.path.join(C.CONFIG_DIR, "network.json")),
            ("secrets/.env", os.path.join(C.ROOT, ".env"))]


def captures_dir():
    """Le dossier des captures de l'utilisateur : le frère de l'environnement d'entraînement NAM
    (bridge/plugin_capture.py, train_home().parent / "captures") — Windows %LOCALAPPDATA%\\GoleM\\captures, macOS
    ~/Library/Application Support/GoleM/captures, Linux ~/.cache/golem-build/captures. Recalculé ici sans importer
    plugin_capture (la sauvegarde tourne bridge arrêté) ; tests/test_backup_cli.py vérifie qu'ils disent pareil."""
    if os.environ.get("GOLEM_NAM_TRAIN"):
        return os.path.join(os.path.dirname(os.path.abspath(os.environ["GOLEM_NAM_TRAIN"])), "captures")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "GoleM", "captures")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "GoleM", "captures")
    return os.path.join(os.path.expanduser("~"), ".cache", "golem-build", "captures")


def capture_files():
    """[(nom dans la sauvegarde, source)] de chaque fichier des captures (liens ignorés)."""
    base = captures_dir()
    out = []
    if not os.path.isdir(base):
        return out
    for r, ds, fs in os.walk(base):
        ds[:] = sorted(d for d in ds if not os.path.islink(os.path.join(r, d)))
        for n in sorted(fs):
            src = os.path.join(r, n)
            if os.path.isfile(src) and not os.path.islink(src):
                out.append(("captures/" + os.path.relpath(src, base).replace(os.sep, "/"), src))
    return out


def _inside(p, root):
    p, root = os.path.realpath(p), os.path.realpath(root)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def estimate(secrets=False):
    """Octets à prévoir : toutes les catégories de `all` + les chansons + identité (+ secrets)."""
    c = B.counts()
    n = sum(int((c.get(k) or {}).get("bytes") or 0) for k in B.ALL_PARTS if k != "originals")
    n += int((c.get("songs") or {}).get("bytes") or 0) * 2          # les originaux sont dans `all` ET dans songs
    for rel in ("library/catalog/tones-index.json", "library/catalog/images.json"):
        n += B._size(os.path.join(C.ROOT, rel))
    for _arc, src in identity_files() + (secret_files() if secrets else []) + capture_files():
        n += B._size(src)
    return n


def _free(dest):
    d = dest
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return shutil.disk_usage(d).free


def _sha(path):
    return B._sha256_file(path)


def verify_zip(path):
    """Relit un zip de sauvegarde avec la vérification de l'import : manifeste, chemins, taille + sha256 de chaque
    fichier, empreinte globale. Lève BackupFailed au premier écart."""
    from . import importer as I
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                raise BackupFailed("%s: damaged member %s" % (os.path.basename(path), bad))
            m = I._load_manifest(zf)
            I._verify(zf, m)
            return len(m.get("files") or [])
    except I.ImportError_ as e:
        raise BackupFailed("%s: %s" % (os.path.basename(path), e))
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupFailed("%s: unreadable (%s)" % (os.path.basename(path), e))


README = """golem — full backup made on {date}
{line}

This folder is what golem needs to come back exactly as it was. It was made before uninstalling
(or on request) and lives OUTSIDE the golem install folder.

Files
-----
{files}

How to restore
--------------
1. Install golem again (the graphical installer, or provision/bootstrap.sh).
2. Open golem, then ⇅ I/O ▸ Import, and choose each zip in turn:
     golem-all-*.zip    presets, patches, setlists, settings, captures, kits, recordings…
     golem-songs-*.zip  the song library
   The import checks every file before writing anything, and shows a plan first.
3. Identity and keys are NOT restored by the import (it refuses them on purpose). Copy them by hand,
   golem stopped (`golem stop`):
{copies}

{notes}Not in this backup, on purpose: DrumGizmo kits, SFZ pianos and the golem.fm backing cache —
the installer downloads them again.
"""
CAPTURES_NOTE = """Your captures (captures/) are copied back by hand too, golem stopped, into
     {dst}
   (the same folder on a new install; create it if needed).

"""
SECRETS_NOTE = """Keys (secrets/) are in clear text. On Linux and macOS only you can read them (file mode 600); on
Windows these file modes protect nothing (NTFS ignores them): keep this folder private, and delete secrets/
once you have restored them.

"""

DESCR = {
    "all": "everything except the song library (category `all`) — restore with ⇅ I/O",
    "songs": "the song library: every .golem song (category `songs`) — restore with ⇅ I/O",
    "identity/serial.json": "this rack's lifetime number (golem_N)",
    "identity/reaper-license.rk": "your REAPER license",
    "secrets/integrations.json": "API keys and the golem.fm pairing token — KEEP PRIVATE",
    "secrets/auth-devices.json": "paired tablets and phones — KEEP PRIVATE",
    "secrets/network.json": "Wi-Fi networks and the access point password — KEEP PRIVATE",
    "secrets/.env": "environment keys (TONE3000…) — KEEP PRIVATE",
    "captures/": "your amp and pedal captures in progress or done (capture work folders)",
}


def _readme(written, targets, captures=None, secrets=False):
    lines, copies = [], []
    for arc, size in written:
        key = "all" if arc.startswith("golem-all-") else "songs" if arc.startswith("golem-songs-") else arc
        lines.append("  %-34s %s (%s)" % (arc, DESCR.get(key, ""), _human(size)))
    for arc, dst in targets:
        copies.append("     %-30s -> %s" % (arc, dst))
    date = time.strftime("%Y-%m-%d %H:%M")
    head = "golem — full backup made on %s" % date
    notes = (CAPTURES_NOTE.format(dst=captures) if captures else "") + (SECRETS_NOTE if secrets else "")
    return README.format(date=date, line="=" * len(head), files="\n".join(lines),
                         copies="\n".join(copies) or "     (nothing to copy)", notes=notes)


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def full(dest, secrets=False, log=None):
    """La sauvegarde complète dans `dest`, vérifiée. Rend un résumé ; lève BackupFailed."""
    log = log or (lambda msg: None)
    dest = os.path.abspath(os.path.expanduser(dest))
    if _inside(dest, C.ROOT):
        raise BackupFailed("refused: %s is inside the golem install folder (%s), which an uninstall deletes"
                           % (dest, C.ROOT))
    need = int(estimate(secrets) * MARGIN) + SLACK
    free = _free(dest)
    if free < need:
        raise BackupFailed("not enough free space in %s: about %s needed, %s free" % (dest, _human(need), _human(free)))
    os.makedirs(dest, exist_ok=True)
    written, copies, targets = [], [], []
    log("building the full backup (all)…")
    r_all = B.build("all", dest_dir=dest)
    written.append((r_all["file"], r_all["size"]))
    log("building the song library backup (songs)…")
    r_songs = B.build("songs", dest_dir=dest)
    written.append((r_songs["file"], r_songs["size"]))
    extra = identity_files() + (secret_files() if secrets else [])
    for arc, src in extra:
        if not os.path.isfile(src):
            continue
        out = os.path.join(dest, *arc.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if arc.startswith("secrets/"):
            os.chmod(os.path.dirname(out), 0o700)
        shutil.copyfile(src, out)
        if arc.startswith("secrets/"):
            os.chmod(out, 0o600)
        copies.append((arc, src, out))
        written.append((arc, os.path.getsize(out)))
        targets.append((arc, src))
    # les captures (§9.5) : hors du dossier d'install, elles partiraient avec la désinstallation (le dossier de données
    # de golem sous Windows, ~/.cache/golem-build sous Linux) — copiées telles quelles, vérifiées fichier par fichier
    caps = capture_files()
    if caps:
        log("copying your captures…")
        total = 0
        for arc, src in caps:
            out = os.path.join(dest, *arc.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copyfile(src, out)
            copies.append((arc, src, out))
            total += os.path.getsize(out)
        written.append(("captures/", total))
    readme = os.path.join(dest, "README.txt")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(_readme(written, targets, captures=captures_dir() if caps else None,
                        secrets=any(a.startswith("secrets/") for a, _s, _o in copies)))
    # VÉRIFICATION : tout relu
    log("verifying…")
    checked = {}
    for name in (r_all["file"], r_songs["file"]):
        checked[name] = verify_zip(os.path.join(dest, name))
    for arc, src, out in copies:
        if _sha(src) != _sha(out):
            raise BackupFailed("%s: the copy differs from %s" % (arc, src))
    return {"ok": True, "dest": dest, "files": [{"path": a, "size": s} for a, s in written] + [
        {"path": "README.txt", "size": os.path.getsize(readme)}], "verified": checked,
        "secrets": bool(secrets), "estimated": need}


def estimate_report(dest, secrets=False):
    """Ce que l'écran « Back up » du désinstallateur affiche : la place à prévoir contre la place libre. N'écrit rien."""
    dest = os.path.abspath(os.path.expanduser(dest))
    n = estimate(secrets)
    need = int(n * MARGIN) + SLACK
    free = _free(dest)
    return {"ok": True, "dest": dest, "bytes": n, "need": need, "free": free, "fits": free >= need,
            "inside_install": _inside(dest, C.ROOT)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m bridge.backup_cli", description="golem backups from the command line.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("full", help="full backup before uninstalling (docs/uninstall.md §6)")
    f.add_argument("--dest", required=True, help="destination folder, outside the golem install folder")
    f.add_argument("--secrets", action="store_true", help="also copy keys, paired devices and Wi-Fi passwords")
    f.add_argument("--json", action="store_true", help="print the result as JSON")
    e = sub.add_parser("estimate", help="size of a full backup against the free space of DIR (JSON, writes nothing)")
    e.add_argument("--dest", required=True)
    e.add_argument("--secrets", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "estimate":
        try:
            print(json.dumps(estimate_report(a.dest, secrets=a.secrets)))
        except (ValueError, OSError) as ex:
            print(json.dumps({"ok": False, "error": str(ex)}))
            return 1
        return 0
    say = (lambda m: None) if a.json else (lambda m: print(m, flush=True))
    try:
        res = full(a.dest, secrets=a.secrets, log=say)
    except (BackupFailed, ValueError, OSError) as e:
        if a.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print("backup FAILED: %s" % e, file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for x in res["files"]:
            print("  %-36s %s" % (x["path"], _human(x["size"])))
        print("backup verified: %s" % res["dest"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
