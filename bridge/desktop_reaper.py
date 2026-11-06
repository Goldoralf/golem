# SPDX-License-Identifier: GPL-3.0-or-later
"""Le moteur REAPER sous Windows : mise à jour et retour arrière depuis Licenses ▸ Reaper.

2026-10-03 : « fais en sorte que le golem puisse mettre à jour Reaper ». Même contrat que le rack
(bridge/reaper_update.py) — le pin d'abord, la version publiée en option non validée, l'ancienne install
GARDÉE à côté, rollback automatique si le moteur ne revient pas — avec la mécanique de Windows :

  télécharger l'installeur officiel (non élevé, vérifié : sha256 du pin, ou journalisé s'il n'y en a pas)
  -> fermer REAPER comme le fait le changement de buffer (projet sauvé, jamais tué : desktop_audio)
  -> install-system.ps1 -ReaperUpdate, ÉLEVÉ : UNE invite Windows, sur l'écran du PC
     (copie « REAPER (x64).golem-prev », /S /D=<dossier>, version de l'exe jugée sur pièce)
  -> relancer REAPER, attendre running + lien OSC, sinon -ReaperSwap (retour) et relancer.

⚠ L'invite UAC s'affiche sur l'écran du PC : depuis un téléphone, personne ne peut la valider — le
journal le dit à l'étape « permission ». Refusée = rien n'est touché, REAPER repart tel quel.
"""
import contextlib, hashlib, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

from . import config as C
from .state import state

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PREV_SUFFIX = ".golem-prev"
VERIFY_TIMEOUT = 60
UAC_TIMEOUT = 600                     # l'invite attend quelqu'un devant le PC


def reaper_dir():
    from provision.desktop import reaper_binary
    return Path(reaper_binary()).parent


def prev_dir():
    d = reaper_dir()
    return d.with_name(d.name + PREV_SUFFIX)


def installer_url(ver):
    return f"https://www.reaper.fm/files/{ver.split('.')[0]}.x/reaper{ver.replace('.', '')}_x64-install.exe"


def download(ver, url, want_sha, log):
    """L'installeur dans le dossier runtime, vérifié. Rend (chemin, sha256 obtenu)."""
    dest = Path(C.runtime_file("reaper-installers")) / url.rsplit("/", 1)[-1]
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (golem engine update)"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            f.write(chunk)
    h = hashlib.sha256()
    with open(part, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if want_sha and got != want_sha.lower():
        part.unlink(missing_ok=True)
        raise RuntimeError(f"installer sha256 mismatch (got {got[:12]}…, pinned {want_sha[:12]}…) — refusing to install")
    os.replace(part, dest)
    log("✓ downloaded " + dest.name)
    log("✓ sha256 verified against the pinned release" if want_sha else
        f"⚠ version not validated for this release — nothing to verify against "
        f"(Cockos publishes no checksum). Downloaded sha256: {got}")
    return dest, got


def elevated(args, log):
    """install-system.ps1 ÉLEVÉ (UAC), son journal relu ligne à ligne. Lève en échec."""
    script = Path(C.ROOT) / "provision" / "windows" / "install-system.ps1"
    fd, logf = tempfile.mkstemp(suffix=".log", prefix="golem-reaper-")
    os.close(fd)
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    inner = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", f'"{script}"', "-Log", f'"{logf}"',
             *[a if a.startswith("-") else f'"{a}"' for a in args]]
    # le reçu d'install (docs/uninstall.md §9.2) : SON chemin, résolu ici (l'utilisateur) — jamais par l'administrateur
    from . import install_receipt
    rcpt = install_receipt.path()
    if rcpt:
        inner += ["-Receipt", f'"{rcpt}"']
    cmd = ("try { $p = Start-Process -FilePath powershell.exe -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
           "-ArgumentList @(" + ",".join(q(a) for a in inner) + "); exit $p.ExitCode } "
           "catch { Write-Output $_.Exception.Message; exit 1223 }")
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True,
                           text=True, timeout=UAC_TIMEOUT, creationflags=NO_WINDOW)
        with open(logf, encoding="utf-8-sig", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        for ln in lines:
            log(ln)
        if p.returncode == 1223 and not lines:
            raise RuntimeError("Windows permission was not granted — nothing was changed")
        if p.returncode != 0:
            raise RuntimeError(next((ln[2:] for ln in reversed(lines) if ln.startswith("✗")),
                                    f"elevated step failed (exit {p.returncode})"))
    finally:
        with contextlib.suppress(OSError):
            os.unlink(logf)
        if rcpt:
            install_receipt.merge_pending()          # ce que le script élevé a noté (REAPER (x64).golem-prev…)


def stop_engine(log):
    """Ferme le REAPER de la session comme le changement de buffer : projet sauvé, fenêtre fermée
    poliment, jamais tué. Rend les arguments pour le rouvrir sur le même projet."""
    from provision import desktop
    from provision.desktop_window import request_reaper_close
    from . import desktop_audio, recall
    with contextlib.suppress(Exception):
        recall.invalidate_shape()                    # projet rechargé -> REBUILD à la prochaine émission
    with contextlib.suppress(Exception):
        from . import diag
        diag.intent("reaper", "update")
    if not desktop.reaper_running():
        return desktop_audio._reopen_args(desktop.reaper_binary(), None)
    snap = desktop_audio._snapshot_reaper()
    if not (snap.get("PROJECT") and Path(snap["PROJECT"]).is_file()):
        target = desktop_audio._auto_save_target()
        snap = desktop_audio._snapshot_reaper(target)
        if not snap.get("AUTO_SAVED") or not target.is_file():
            raise RuntimeError("could not save the REAPER project — engine left untouched")
        desktop.remember_project(target)
        log(f"✓ project saved as {target.name}")
    reopen = desktop_audio._reopen_args(desktop.reaper_binary(), snap)
    # enregistré EN PLACE d'abord : un projet modifié ouvrait « Save project…? » derrière la coquille, et
    # la 1re mise à jour réelle (2026-10-03) a attendu 3 min une réponse que personne ne voyait
    if desktop_audio.save_project_in_place():
        log("✓ project saved")
    if not request_reaper_close(desktop._backend_pids()):
        raise RuntimeError("could not close this session's REAPER window")
    for _ in range(180):
        if not desktop.reaper_running():
            return reopen
        time.sleep(1)
    raise RuntimeError("REAPER is still open — check its save prompt")


def start_engine(reopen):
    from provision import desktop
    from . import desktop_midi
    if desktop.reaper_running():
        return
    with contextlib.suppress(Exception):            # REAPER fermé : le moment de poser ses masques MIDI
        desktop_midi.apply_reaper_masks(C.reaper_resource_dir())
    desktop.launch_reaper(reopen, cwd=str(C.ROOT))


def verify_alive(timeout=VERIFY_TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if state.reaper_running and state.reaper_connected:
            return True
        time.sleep(1)
    return False


def previous_version():
    from .reaper_update import installed_version
    p = prev_dir()
    return installed_version(str(p)) if (p / "reaper.exe").is_file() else None


# ── LA LICENCE, LUE CHEZ REAPER (2026-10-03) ───────────────────────────────────────────────────
# La 1re mise à jour réelle 7.27 → 7.79 a « réussi » — moteur debout, lien OSC vivant — et rendu un REAPER
# en ÉVALUATION : le même reaper-license.rk, au même endroit, que 7.27 acceptait et que 7.79 refuse (sa
# page licence : « evaluating REAPER for approximately 692 days »). La présence du fichier ne dit donc
# RIEN (même famille que « une ref qui existe ne dit pas ce qu'elle contient ») : le seul fait honnête est
# ce que REAPER AFFICHE, dans le titre de sa fenêtre principale (« Registered to … » / « EVALUATION
# LICENSE »), lisible même quand GoleM la cache. Une mise à jour qui perd la licence n'en est pas une.
def reaper_title():
    """Titre de la fenêtre principale de REAPER (classe REAPERwnd), ou None."""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as W
    u = ctypes.windll.user32
    found = []

    def cb(h, _):
        c = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, c, 64)
        if c.value == "REAPERwnd":
            n = u.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            found.append(b.value)
        return True
    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)(cb), 0)
    return found[0] if found else None


def license_state(title=None):
    """'registered' | 'evaluation' | None (pas de REAPER, ou titre illisible)."""
    t = title if title is not None else reaper_title()
    if not t:
        return None
    if "EVALUATION" in t.upper():
        return "evaluation"
    if "registered" in t.lower() or "license" in t.lower():
        return "registered"
    return None


def wait_title(version, timeout=30):
    """Le titre du REAPER qui tourne une fois que c'est BIEN la version attendue (« REAPER v7.79 »)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = reaper_title()
        if t and f"REAPER v{version}" in t:
            return t
        time.sleep(1)
    return reaper_title()


def run_update(old, new, validated, pin_url, pin_sha, step, log):
    """Le worker Windows (appelé dans le thread de reaper_update). Rend le dict `last`."""
    url = pin_url if validated and pin_url else installer_url(new)
    step("download", f"⏳ downloading REAPER {new}…")
    exe, _ = download(new, url, pin_sha if validated else None, log)
    lic_before = license_state()
    step("stop", "⏳ stopping audio engine (project saved)…")
    reopen = stop_engine(log)
    log("✓ audio engine stopped")
    try:
        step("permission", "⏳ Windows asks for permission on the PC screen — approve it there")
        args = ["-ReaperUpdate", "-ReaperDir", str(reaper_dir()), "-Installer", str(exe), "-Version", new]
        if validated and pin_sha:
            args += ["-Sha256", pin_sha]
        elevated(args, log)
    except Exception:
        start_engine(reopen)                         # rien n'a changé : le moteur repart tel quel
        raise
    step("restart", "⏳ restarting audio engine…")
    start_engine(reopen)
    step("verify", "⏳ verifying (engine boots + rig link alive)…")
    why = None
    if verify_alive():
        title = wait_title(new)
        lic_after = license_state(title)
        if lic_before == "registered" and lic_after == "evaluation":
            why = (f"REAPER {new} does not accept your license key ({old} did) — rolled back to {old}, "
                   f"still registered. Check the key in REAPER's About ▸ License, or ask Cockos.")
            step("rollback", f"✗ REAPER {new} runs in EVALUATION — your license key is not accepted; "
                             f"going back to {old} (Windows asks once more)…")
        else:
            log(f"✓ engine {new} is up — set loaded, OSC link alive"
                + (" — license kept" if lic_after == "registered" else ""))
            return {"ok": True, "from": old, "to": new, "rolled_back": False, "validated": validated}
    else:
        step("rollback", f"✗ engine {new} did not come back — rolling back to {old}…")
    stop_engine(log)
    elevated(["-ReaperSwap", "-ReaperDir", str(reaper_dir())], log)
    start_engine(reopen)
    log("✓ rolled back — previous engine is up" if verify_alive()
        else "⚠ rollback done but engine still not verified — check the Dashboard")
    return {"ok": False, "from": old, "to": new, "rolled_back": True, "validated": validated,
            "license_lost": bool(why),
            "error": why or f"engine {new} failed verification — rolled back to {old}"}


def run_switch(old, ver, step, log):
    """Retour à l'install gardée à côté : aucun réseau, une invite Windows."""
    step("stop", "⏳ stopping audio engine (project saved)…")
    reopen = stop_engine(log)
    try:
        step("permission", "⏳ Windows asks for permission on the PC screen — approve it there")
        elevated(["-ReaperSwap", "-ReaperDir", str(reaper_dir())], log)
    except Exception:
        start_engine(reopen)
        raise
    step("restart", "⏳ restarting audio engine…")
    start_engine(reopen)
    step("verify", "⏳ verifying (engine boots + rig link alive)…")
    if verify_alive():
        log(f"✓ engine {ver} is up — set loaded, OSC link alive")
        return {"ok": True, "from": old, "to": ver, "rolled_back": False, "switch": True}
    step("rollback", f"✗ engine {ver} did not come back — switching back to {old}…")
    stop_engine(log)
    elevated(["-ReaperSwap", "-ReaperDir", str(reaper_dir())], log)
    start_engine(reopen)
    verify_alive()
    return {"ok": False, "from": old, "to": ver, "rolled_back": True, "switch": True,
            "error": f"engine {ver} failed verification — switched back to {old}"}
