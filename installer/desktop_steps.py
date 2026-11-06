# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que les installateurs DESKTOP (Windows, macOS) font pareil — sorti de platform_windows.py le
2026-10-04 quand macOS est arrivé (docs/platforms.md) : copier GoleM sans écraser l'état de
l'utilisateur, poser les DI de référence, sonder le disque et le réseau. Aucun appel propre à un OS ici.
"""
import hashlib
import os
import shutil
import socket
import tarfile
import urllib.request
import zipfile

# l'état local de l'utilisateur : une réinstallation par-dessus ne l'écrase JAMAIS (ses presets, ses
# réglages, ses prises). Les graines versionnées n'y sont copiées que si elles manquent.
LOCAL_STATE = ("presets", "sets", "mappings", "config", "setlists", "recordings", "assets")
DI_URL = os.environ.get("GOLEM_DI_URL",
                        "https://github.com/Goldoralf/golem-binaries/releases/download/di-refs-v1/golem-di-refs-v1.tar.gz")
# la pompe du bloc Standard (docs/standards.md §10) — MÊME URL que provision/fetch-assets.sh, épinglée dans downloads.sha256
# le piano du bloc piano (lane Keys) : Salamander Grand v3, la même source et la même empreinte que fetch-assets.sh
PIANO_URL = "https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SFZ+FLAC-V3+20200602.tar.gz"
PIANO_DIR = "SalamanderGrandPiano-SFZ+FLAC-V3+20200602"
GUITAR_URL = ("https://github.com/sfzinstruments/karoryfer.shinyguitar/releases/download/v1.001/"
              "Karoryfer.Shinyguitar.v1.001.zip")


def free_mb(path):
    p = path
    while p and not os.path.isdir(p):
        p = os.path.dirname(p)
    try:
        return int(shutil.disk_usage(p or os.path.expanduser("~")).free / 1024 / 1024)
    except Exception:
        return None


def has_internet(host="www.reaper.fm", port=443, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False


def step_source(ctx, src, target):
    src, target = os.path.abspath(src), os.path.abspath(target)
    if os.path.normcase(src) == os.path.normcase(target):
        ctx.log("→ installing in place (the installer runs from the target folder)", "source")
        return 0
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("source"), "source")
    fresh = not os.path.isdir(os.path.join(target, "provision"))
    ctx.log(f"→ copying golem to {target}" if fresh else
            f"→ {target} already holds golem — code updated, your presets, settings and takes kept", "source")
    n = kept = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in (".venv", "__pycache__", ".git")]
        rel = os.path.relpath(root, src)
        top = rel.split(os.sep)[0]
        dest_dir = target if rel == "." else os.path.join(target, rel)
        os.makedirs(dest_dir, exist_ok=True)
        for fn in files:
            dst = os.path.join(dest_dir, fn)
            if not fresh and top in LOCAL_STATE and os.path.exists(dst):
                kept += 1
                continue
            shutil.copy2(os.path.join(root, fn), dst)
            n += 1
    ctx.log(f"✓ {n} files copied" + (f", {kept} of yours kept as they were" if kept else ""), "source")
    return 0


def _py_env():
    # PYTHONUNBUFFERED : sous un pipe, la sortie d'un Python est tamponnée — l'écran ne voyait les lignes du setup qu'en
    # bloc, à la fin (2026-10-24, 16 min de « golem itself » sans un mot)
    return {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}


# Mo TÉLÉCHARGÉS par pack (Content-Length des archives épinglées, 2026-10-23) — comme fetch-assets.sh sous Linux
DL_MB = {"piano": 707, "guitar": 351}
_SOUNDS = {"done": 0, "total": 0, "n": 0, "of": 0}


def _fetch(ctx, url, dest, pack, label):
    """urlretrieve, en disant l'avancement à l'écran Install (installer/phases.py `@@progress`) : sous Windows la phase
    « Sounds » annonçait 295 s pour 94 réelles (VM 2026-10-24) — le débit réel remplace l'estimation."""
    import time as _t
    _SOUNDS["n"] += 1
    ctx.log(f"@@sub {label} — {_SOUNDS['n']} of {_SOUNDS['of']}", "sounds")
    last = [0.0]

    def hook(blocks, bsize, _size):
        now = _t.time()
        if now - last[0] >= 5:
            last[0] = now
            ctx.log(f"@@progress {_SOUNDS['done'] + blocks * bsize // 1048576} {_SOUNDS['total']}", "sounds")
    try:
        urllib.request.urlretrieve(url, dest, reporthook=hook)
    finally:
        _SOUNDS["done"] += DL_MB.get(pack, 0)
        ctx.log(f"@@progress {_SOUNDS['done']} {_SOUNDS['total']}", "sounds")


def step_sounds(ctx, target):
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("sounds"), "sounds")
    packs = ctx.S.get("packs") or ()
    sfz = os.path.join(target, "library", "sfz")
    todo = [p for p, d in (("piano", PIANO_DIR), ("guitar", "Shinyguitar"))
            if p in packs and not os.path.isdir(os.path.join(sfz, d))]
    _SOUNDS.update(done=0, total=sum(DL_MB[p] for p in todo), n=0, of=len(todo))
    _sound_di(ctx, target)
    if "piano" in (ctx.S.get("packs") or ()):
        _sound_piano(ctx, target)
    if "guitar" in (ctx.S.get("packs") or ()):
        _sound_guitar(ctx, target)
    return 0


def _sound_piano(ctx, target):
    """Le pack piano : Salamander Grand v3 (CC-BY), pendant de fetch-assets.sh sous Linux — tar.gz vérifié
    AVANT extraction (empreinte de provision/downloads.sha256), dans library/sfz/."""
    sfz = os.path.join(target, "library", "sfz")
    if os.path.isdir(os.path.join(sfz, PIANO_DIR)):
        ctx.log("✓ Salamander grand piano already present", "sounds")
        return
    sha = _pinned(target, PIANO_URL)
    if not sha:
        ctx.log("⚠ Salamander: no pinned checksum — not downloaded", "sounds")
        return
    os.makedirs(sfz, exist_ok=True)
    tgz = os.path.join(sfz, "salamander.tar.gz")
    ctx.log(f"↓ Salamander grand piano (~450 MB) ← {PIANO_URL}", "sounds")
    try:
        _fetch(ctx, PIANO_URL, tgz, "piano", "Piano (Salamander)")
        h = hashlib.sha256()
        with open(tgz, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != sha:
            ctx.log("⚠ Salamander: checksum mismatch — not installed", "sounds")
            return
        with tarfile.open(tgz) as t:
            t.extractall(sfz, filter="data")              # `data` : aucun membre ne sort du dossier
        ctx.log("✓ Salamander grand piano", "sounds")
    except Exception as e:
        # une source qui manque n'emporte pas l'install : le bloc piano dira « no instrument »
        ctx.log(f"⚠ Salamander unavailable ({e}) — the piano block has no instrument yet", "sounds")
    finally:
        if os.path.exists(tgz):
            os.remove(tgz)


def _sound_di(ctx, target):
    # library/di-refs : là où le bridge les lit (bridge/config.py DI_REFS_DIR) — c'était library/di, qu'il ne lit pas
    di = os.path.join(target, "library", "di-refs")
    if os.path.isdir(di) and any(f.lower().endswith((".wav", ".flac")) for _r, _d, fs in os.walk(di) for f in fs):
        ctx.log("✓ reference DIs already present", "sounds")
        return
    # PAS ENCORE ENREGISTRÉES (2026-10-24) : sans empreinte épinglée, on ne télécharge pas — comme fetch-assets.sh,
    # et comme toute archive qu'on extrait (celle-ci partait sans aucune vérification)
    want = _pinned(target, DI_URL)
    if not want:
        ctx.log("⏭ reference DIs: not published yet — the preset previews will wait; nothing else depends on it", "sounds")
        return
    os.makedirs(di, exist_ok=True)
    tgz = os.path.join(di, "di.tgz")
    ctx.log(f"↓ golem reference DIs ← {DI_URL}", "sounds")
    try:
        urllib.request.urlretrieve(DI_URL, tgz)
        h = hashlib.sha256()
        with open(tgz, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != want:
            raise ValueError("sha256 mismatch — file rejected")
        with tarfile.open(tgz) as t:
            t.extractall(di, filter="data")
        ctx.log("✓ reference DIs", "sounds")
    except Exception as e:
        # même règle que sous Linux (fetch-assets.sh) : une source qui manque n'emporte pas l'install
        ctx.log(f"⚠ reference DIs unavailable ({e}) — the preset previews will wait; nothing else depends on it", "sounds")
    finally:
        if os.path.exists(tgz):
            os.remove(tgz)


def _pinned(target, url):
    """L'empreinte épinglée d'une URL (provision/downloads.sha256, le même fichier que lib-fetch.sh sous Linux)."""
    try:
        with open(os.path.join(target, "provision", "downloads.sha256"), encoding="utf-8") as f:
            for line in f:
                bits = line.split()
                if len(bits) == 2 and not line.startswith("#") and bits[1] == url:
                    return bits[0].lower()
    except OSError:
        pass
    return None


def _sound_guitar(ctx, target):
    """La pompe du bloc Standard : Shinyguitar (CC0), pendant de fetch-assets.sh sous Linux."""
    sfz = os.path.join(target, "library", "sfz")
    if os.path.isdir(os.path.join(sfz, "Shinyguitar")):
        ctx.log("✓ Shinyguitar already present", "sounds")
        return
    sha = _pinned(target, GUITAR_URL)
    if not sha:
        ctx.log("⚠ Shinyguitar: no pinned checksum — not downloaded", "sounds")
        return
    os.makedirs(sfz, exist_ok=True)
    zp = os.path.join(sfz, "shinyguitar.zip")
    ctx.log(f"↓ Shinyguitar, the gypsy rhythm guitar (~350 MB) ← {GUITAR_URL}", "sounds")
    try:
        _fetch(ctx, GUITAR_URL, zp, "guitar", "Guitar (Shinyguitar)")
        h = hashlib.sha256()
        with open(zp, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != sha:
            ctx.log("⚠ Shinyguitar: checksum mismatch — not installed", "sounds")
            return
        with zipfile.ZipFile(zp) as z:                 # extractall neutralise les chemins en « .. »
            z.extractall(sfz)
        ctx.log("✓ Shinyguitar", "sounds")
    except Exception as e:
        # une source qui manque n'emporte pas l'install : le bloc Standard jouera sans pompe
        ctx.log(f"⚠ Shinyguitar unavailable ({e}) — the Standard block plays without the pompe", "sounds")
    finally:
        if os.path.exists(zp):
            os.remove(zp)
