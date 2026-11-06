# SPDX-License-Identifier: GPL-3.0-or-later
"""Le DÉSINSTALLATEUR graphique (docs/uninstall.md §4) — un MODE de installer/server.py, pas un second serveur :
même jeton à usage unique, même askpass (le mot de passe ne quitte jamais la mémoire), même allure. Ce module ne
fait que tenir l'état des six écrans et lancer les deux vraies commandes, qui restent la vérité :

  la sauvegarde   <root>/.venv/bin/python -m bridge.backup_cli full --dest DIR [--secrets] --json   (cwd = root)
  le moteur       python3 provision/uninstall.py plan --json  ·  run --select FILE --yes --json --log FILE

Le serveur se COPIE d'abord dans /tmp/golem-uninstaller-<hasard>/ (self_copy) et repart de là : il supprime le
dossier d'où il vient. Sous Windows (docs/uninstall.md §9.4) : %TEMP%\\golem-uninstaller-<hasard>, et il repart DÉTACHÉ
avec le Python de BASE (relaunch_detached) — Windows n'a pas d'exec, et le venv est supprimé. Ce dossier temporaire part avec lui, quelle que soit la sortie (cleanup, appelé par
server.cleanup). En --dry, le plan est lu POUR DE VRAI (il ne touche à rien) ; la sauvegarde et la
désinstallation sont jouées par installer/dry_step.py, qui écrit exactement ce qu'écrivent les vraies commandes.
"""
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP_PREFIX = "golem-uninstaller-"
MARKER = ".golem-uninstaller"           # un dossier sans ce fichier n'est JAMAIS effacé par remove_tmp
# ce que la copie emporte : de quoi servir les écrans et lancer le moteur, rien d'autre (motifs relatifs au dépôt)
FILES = ("installer/server.py", "installer/platform_linux.py", "installer/dry_step.py", "installer/dry_bridge.py",
         "installer/uninstaller.py", "installer/phases.py",       # server.py l'importe (l'écran Install en phases)
         "installer/report.py", "bridge/scrub.py",                # server.py l'importe (le rapport d'échec, §7.1)
         # Windows (§9.4) : son module de plateforme (et ce qu'il importe : desktop_steps, provision/desktop pour la
         # fenêtre d'application), l'élévation partagée avec l'installateur, la couche Windows du moteur
         "installer/platform_windows.py", "installer/desktop_steps.py", "installer/elevate_win.py",
         "installer/after_exit_win.py",
         "provision/desktop.py", "provision/uninstall_win.py", "provision/receipt.py",
         "installer/ui/*", "provision/uninstall.py", "bridge/engines.py", "bridge/reaper_license.py",
         "app/vendor/htm-preact-standalone.module.js", "app/icons/favicon-32.png")
OPTIONAL = ("app/icons/favicon-32.png",)
# l'écran « golem » (lecture seule) et l'écran « Third-party software » (cases à cocher), docs/uninstall.md §4
GOLEM_GROUPS = ("golem", "reaper-links", "reaper-ini", "system", "dedicated")
THIRD_GROUPS = ("plugins", "reaper", "programs", "apt", "toolchain")
# Windows : pas d'exec — le serveur copié repart DÉTACHÉ (relaunch_detached) ; ses commandes sans console
DETACHED = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── la copie de soi dans /tmp ──────────────────────────────────────────────────────────────────────────
def self_copy(src, base=None):
    """Copie le nécessaire de `src` (le dépôt installé) dans un dossier temporaire neuf ; rend son chemin."""
    if os.name == "nt":
        # PAS mkdtemp sous Windows (VM, 2026-10-16) : depuis Python 3.12 il pose une ACL « propriétaire seul » sans
        # héritage — et Edge, lancé pendant que la fenêtre de golem tourne (un autre Edge), ne pouvait pas écrire le profil
        # de la fenêtre dans la copie : « can't read and write to its data directory », aucune fenêtre, rien à l'écran.
        # %TEMP% est déjà propre à l'utilisateur : un dossier ordinaire, au nom imprévisible, hérite de ses droits.
        import secrets
        root_tmp = base or tempfile.gettempdir()
        while True:
            tmp = os.path.join(root_tmp, TMP_PREFIX + secrets.token_hex(6))
            try:
                os.mkdir(tmp)
                break
            except FileExistsError:
                continue
    else:
        tmp = tempfile.mkdtemp(prefix=TMP_PREFIX, dir=base)
        os.chmod(tmp, 0o700)
    try:
        with open(os.path.join(tmp, MARKER), "w", encoding="utf-8") as f:
            f.write("golem uninstaller copy of %s — removed when the uninstaller closes\n" % src)
        for pat in FILES:
            hits = [h for h in sorted(glob.glob(os.path.join(src, pat))) if os.path.isfile(h)]
            if not hits and pat not in OPTIONAL:
                raise FileNotFoundError("the uninstaller needs %s (not found in %s)" % (pat, src))
            for h in hits:
                dst = os.path.join(tmp, os.path.relpath(h, src))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(h, dst)
    except Exception:
        remove_tmp(tmp)
        raise
    return tmp


def remove_tmp(tmp):
    """Efface la copie — SEULEMENT si c'est bien la nôtre (nom + marqueur). Rend True si elle est partie. Sous Windows
    un fichier encore ouvert (le navigateur de la fenêtre, à peine fermé) bloque l'effacement : on réessaie un peu."""
    if not tmp or not os.path.basename(os.path.normpath(tmp)).startswith(TMP_PREFIX):
        return False
    if not os.path.isfile(os.path.join(tmp, MARKER)):
        return False
    # le MARQUEUR EN DERNIER (VM Windows, 2026-10-16) : effacée d'un bloc, une copie dont le navigateur tenait encore
    # le profil perdait son marqueur au premier essai, et le reste n'était plus reconnu par personne — il restait
    for _ in range(10 if DETACHED else 1):
        for name in os.listdir(tmp):
            if name == MARKER:
                continue
            p = os.path.join(tmp, name)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        if [n for n in os.listdir(tmp) if n != MARKER] == []:
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.exists(tmp):
                return True
        time.sleep(0.5)
    return not os.path.exists(tmp)


def base_python():
    """Le Python qui relance la copie. Linux : celui-ci (os.execv). Windows : le Python de BASE, jamais celui du venv
    (le venv est dans le dossier qu'on supprime), en console (python.exe : pythonw n'a pas de sortie standard)."""
    if not DETACHED:
        return sys.executable
    exe = getattr(sys, "_base_executable", None) or sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        exe = alt if os.path.isfile(alt) else exe
    return exe


def relaunch_detached(argv, tmp):
    """Windows : relance `argv` DÉTACHÉ (sans console, son propre groupe), depuis la copie. Rend True s'il est parti —
    l'appelant sort alors. Linux : False (l'appelant fait os.execv)."""
    if not DETACHED:
        return False
    # PYTHONUTF8 : la sortie du processus détaché part dans DEVNULL avec l'encodage de Windows (cp1252), qui ne sait pas
    # écrire « → » — le serveur mourait sur son premier print et effaçait sa copie : « Uninstall golem » ne s'ouvrait
    # pas, sans un mot (VM Windows, 2026-10-16)
    subprocess.Popen(argv, cwd=tmp, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return True


def reexec_argv(tmp, root, dry=False, open_=False, port=0):
    """La ligne de commande du serveur relancé depuis sa copie."""
    argv = [base_python(), os.path.join(tmp, "installer", "server.py"), "--uninstall", "--root", root,
            "--owned-tmp", tmp]
    if dry:
        argv.append("--dry")
    if open_:
        argv.append("--open")
    if port:
        argv += ["--port", str(port)]
    return argv


# ── l'état des écrans ──────────────────────────────────────────────────────────────────────────────────
def default_dest():
    return os.path.expanduser("~/golem-backup-" + datetime.date.today().isoformat())


U = {
    "root": None, "tmp": None, "dry": False, "venv": False, "privilege": "sudo",
    "plan": None, "plan_error": None, "plan_at": 0,
    "backup": {"enabled": True, "dest": None, "secrets": False, "skip_confirmed": False,
               "state": "idle", "result": None, "error": None},
    "third": {},                       # id -> bool : les choix de l'écran « Third-party software »
    "run": {"state": "idle", "ok": None, "items": {}, "chosen": [], "failed": [], "attempt": 0, "error": None,
            "log_path": None, "done_ids": [], "steps": {}, "current": None, "deps_removed": 0, "kept": [],
            "after_log": None},
    # le rapport d'échec (docs/diagnostics.md §7.1) : ENVOYÉ TOUT SEUL quand une désinstallation échoue — décision du
    # 2026-10-27 (« un utilisateur qui désinstalle n'enverra rien ») ; l'écran le dit, avec ce qu'il contient
    "report": {"state": None, "code": None, "path": None, "error": None},
    "version": None,                   # lue AVANT de désinstaller : après, le dépôt n'est peut-être plus là
}
LOCK = threading.Lock()
CTX = None                             # le Ctx du serveur : S, log, job_env
_EST = {}                              # cache de l'estimation de taille, par `secrets`


def init(ctx, root, tmp, dry, privilege="sudo"):
    global CTX
    CTX = ctx
    # privilege : « sudo » (Linux : le mot de passe, à l'écran Review) ou « uac » (Windows : l'invite de Windows, une
    # fois, au début de la passe élevée — aucun mot de passe ne passe par nous)
    U.update(root=os.path.abspath(root), tmp=tmp, dry=bool(dry), privilege=privilege or "sudo")
    # le marqueur dit QUI sert depuis cette copie : le veilleur d'un essai précédent ne vide jamais une copie dont le
    # serveur est vivant (VM Windows, 2026-10-16 : il avait vidé celle d'un désinstallateur en train de tourner)
    try:
        if tmp and os.path.isfile(os.path.join(tmp, MARKER)):
            with open(os.path.join(tmp, MARKER), "a", encoding="utf-8") as f:
                f.write("pid=%d\n" % os.getpid())
    except OSError:
        pass
    U["venv"] = venv_python(U["root"]) is not None
    if dry:                                     # --dry simule une sauvegarde : le venv n'y sert pas, sauf à le dire absent
        U["venv"] = os.environ.get("GOLEM_DRY_NO_VENV") != "1"
    try:
        import report as RP
        U["version"] = RP.version(U["root"])
    except Exception:
        U["version"] = None
    U["backup"]["dest"] = default_dest()
    if not U["venv"]:
        U["backup"]["enabled"] = False          # rien pour la faire : l'écran le dit et demande une confirmation


def cleanup():
    """Le dossier temporaire part avec le serveur (appelé à TOUTES les sorties par server.cleanup). Windows : un
    processus ne peut pas effacer son répertoire courant — on en sort d'abord ; et le profil du navigateur de la
    fenêtre (<copie>\\browser) reste verrouillé quelques secondes après sa fermeture. Si la copie résiste, elle est
    confiée au VEILLEUR (installer/after_exit_win.py), qui attend notre fin et l'efface (marqueur vérifié) — VM
    Windows, 2026-10-16 : la copie, son profil et select-1.json restaient dans %TEMP%."""
    t, U["tmp"] = U["tmp"], None
    if not t:
        return
    if DETACHED:
        _leave(t)
    if remove_tmp(t) or not DETACHED or not os.path.isdir(t):
        return
    try:
        hand_over(t)
    except Exception:
        pass


def _leave(tmp):
    """Sortir de la copie si on y a son répertoire courant (vers son parent, %TEMP%)."""
    try:
        if _inside(os.getcwd(), tmp):
            os.chdir(os.path.dirname(os.path.normpath(tmp)))
    except OSError:
        pass


def hand_over(tmp):
    """Confie la copie au veilleur : il attend la fin de CE processus, puis l'efface. Rend (ok, journal, message)."""
    import after_exit_win
    return after_exit_win.schedule(os.getpid(), os.path.dirname(os.path.normpath(tmp)), copy_dir=tmp)


def venv_rel():
    """Le Python du venv, relatif au dossier d'install : .venv/bin/python, ou .venv\\Scripts\\python.exe sous Windows."""
    return os.path.join(".venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(".venv", "bin", "python")


def venv_python(root):
    p = os.path.join(root, venv_rel())
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None


def _log(line, step=None):
    if CTX is not None:
        CTX.log(line, step)


def _env():
    return CTX.job_env() if CTX is not None else dict(os.environ)


def _parse_json(out):
    out = (out or "").strip()
    try:
        return json.loads(out)
    except ValueError:
        i = out.find("{")
        try:
            return json.loads(out[i:]) if i >= 0 else None
        except ValueError:
            return None


def _inside(p, root):
    p, root = os.path.realpath(p), os.path.realpath(root)
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def _free(path):
    d = path
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    try:
        return shutil.disk_usage(d or "/").free
    except OSError:
        return None


# ── le plan (lu pour de vrai, même en --dry : il ne touche à rien) ─────────────────────────────────────
def engine_path():
    return os.path.join(U["tmp"] or os.path.dirname(HERE), "provision", "uninstall.py")


def load_plan(force=False):
    if U["plan"] is not None and not force:
        return U["plan"]
    cmd = [sys.executable, engine_path(), "plan", "--root", U["root"], "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=U["tmp"] or None,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        plan = _parse_json(r.stdout) if r.returncode == 0 else None
        if not isinstance(plan, dict) or "items" not in plan:
            raise RuntimeError((r.stderr or r.stdout or "no output").strip()[-400:])
    except Exception as e:
        with LOCK:
            U["plan_error"] = "could not read the uninstall plan: %s" % e
        return None
    with LOCK:
        U["plan"], U["plan_error"], U["plan_at"] = plan, None, time.time()
    return plan


def plan_view():
    plan = load_plan()
    if plan is None:
        return {"error": U["plan_error"]}
    return {**plan, "golem_groups": list(GOLEM_GROUPS), "third_groups": list(THIRD_GROUPS), "third": U["third"]}


def selection(plan, third=None):
    """Les ids à retirer : le groupe golem tel que le moteur le propose (lecture seule), les tiers selon les cases."""
    third = U["third"] if third is None else third
    ids = []
    for it in plan.get("items") or []:
        g = it.get("group")
        if g in GOLEM_GROUPS:
            pick = bool(it.get("default"))
        elif g in THIRD_GROUPS:
            pick = bool(third.get(it["id"], it.get("default")))
        else:
            pick = False
        if pick:
            ids.append(it["id"])
    return ids


def set_third(choices):
    plan = load_plan() or {"items": []}
    ok = {it["id"] for it in plan["items"] if it.get("group") in THIRD_GROUPS}
    with LOCK:
        for k, v in (choices or {}).items():
            if k in ok and isinstance(v, bool):
                U["third"][k] = v


def review():
    plan = load_plan()
    if plan is None:
        return {"error": U["plan_error"]}
    ids = selection(plan)
    by = {it["id"]: it for it in plan["items"]}
    chosen = [by[i] for i in ids]
    return {"ids": ids, "items": chosen, "kept": [it for it in plan["items"] if it["id"] not in ids],
            "needs_password": U["privilege"] == "sudo" and any(it.get("privilege") == "root" for it in chosen),
            "needs_uac": U["privilege"] == "uac" and any(it.get("privilege") in ("admin", "root") for it in chosen),
            "gate": gate(ids), "root": U["root"], "mode": plan.get("mode"),
            "check_yourself": plan.get("check_yourself") or []}


# ── la sauvegarde ──────────────────────────────────────────────────────────────────────────────────────
def set_backup(b):
    """Réglages de l'écran « Back up ». Rend une erreur à dire, ou None."""
    B = U["backup"]
    err = None
    with LOCK:
        if B["state"] == "running":
            return "the backup is running"
        before = (B["enabled"], B["dest"], B["secrets"])
        if isinstance(b.get("enabled"), bool):
            if b["enabled"] and not U["venv"]:
                err = "golem's Python environment is missing: the backup cannot run"
            else:
                B["enabled"] = b["enabled"]
        if b.get("dest") is not None:
            d = os.path.abspath(os.path.expanduser(str(b["dest"]).strip() or default_dest()))
            if _inside(d, U["root"]):
                err = "this folder is inside the golem install folder, which the uninstall deletes — pick another one"
            elif U["tmp"] and _inside(d, U["tmp"]):
                err = "this folder is the uninstaller's temporary copy — pick another one"
            else:
                B["dest"] = d
        if isinstance(b.get("secrets"), bool):
            B["secrets"] = b["secrets"]
        if isinstance(b.get("skip_confirmed"), bool):
            B["skip_confirmed"] = b["skip_confirmed"]
        # une sauvegarde faite ailleurs ou sans les clés n'est plus CELLE qui est demandée : à refaire
        if (B["enabled"], B["dest"], B["secrets"]) != before and B["state"] in ("ok", "fail"):
            B.update(state="idle", result=None, error=None)
    return err


def estimate(dest=None, secrets=None):
    """La place à prévoir contre la place libre de la destination. En --dry : une taille simulée."""
    B = U["backup"]
    dest = os.path.abspath(os.path.expanduser(dest or B["dest"] or default_dest()))
    secrets = B["secrets"] if secrets is None else bool(secrets)
    free = _free(dest)
    if U["dry"]:
        need = 900_000_000 + (5_000 if secrets else 0)
        return {"need": need, "free": free, "fits": free is None or free >= need, "simulated": True, "dest": dest}
    py = venv_python(U["root"])
    if not py:
        return {"need": None, "free": free, "fits": None, "dest": dest}
    if secrets not in _EST:
        try:
            r = subprocess.run([py, "-m", "bridge.backup_cli", "estimate", "--dest", dest] + (["--secrets"] if secrets else []),
                               cwd=U["root"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                               creationflags=NO_WINDOW)
            res = _parse_json(r.stdout)
            if not (isinstance(res, dict) and res.get("ok")):
                return {"need": None, "free": free, "fits": None, "dest": dest,
                        "error": (res or {}).get("error") or (r.stderr or "").strip()[-200:] or "no estimate"}
            _EST[secrets] = int(res["need"])
        except Exception as e:
            return {"need": None, "free": free, "fits": None, "dest": dest, "error": str(e)}
    need = _EST[secrets]
    return {"need": need, "free": free, "fits": free is None or free >= need, "dest": dest}


def backup_cmd():
    B = U["backup"]
    sec = ["--secrets"] if B["secrets"] else []
    if U["dry"]:
        return [sys.executable, os.path.join(U["tmp"] or os.path.dirname(HERE), "installer", "dry_step.py"), "backup", B["dest"]] + sec, U["tmp"]
    return [venv_python(U["root"]) or os.path.join(U["root"], venv_rel()), "-m", "bridge.backup_cli",
            "full", "--dest", B["dest"], "--json"] + sec, U["root"]


def _do_backup():
    B = U["backup"]
    cmd, cwd = backup_cmd()
    _log("$ " + " ".join(cmd), "backup")
    _log("▶ Full backup to %s%s — then every file is read back and checked" % (B["dest"], " (with your keys)" if B["secrets"] else ""), "backup")
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=6 * 3600, stdin=subprocess.DEVNULL,
                           env=dict(os.environ), creationflags=NO_WINDOW)
        res = _parse_json(r.stdout)
        ok = r.returncode == 0 and isinstance(res, dict) and res.get("ok") is True and res.get("verified") is not None
        err = None if ok else ((res or {}).get("error") if isinstance(res, dict) else None) \
            or (r.stderr or "").strip()[-300:] or "the backup stopped (exit %s)" % r.returncode
    except Exception as e:
        ok, res, err = False, None, str(e)
    with LOCK:
        B.update(state="ok" if ok else "fail", result=res if ok else None, error=err)
    if ok:
        for f in res.get("files") or []:
            _log("  %s" % f.get("path"), "backup")
        _log("✓ backup verified: %s" % res.get("dest"), "backup")
    else:
        _log("✗ backup FAILED: %s" % err, "backup")


def start_backup():
    B = U["backup"]
    with LOCK:
        if B["state"] == "running":
            return None
        if not B["enabled"]:
            return "the backup is unticked"
        if not U["venv"]:
            return "golem's Python environment is missing: the backup cannot run"
        B.update(state="running", result=None, error=None)
    threading.Thread(target=_do_backup, daemon=True).start()
    return None


def gate(ids=()):
    """Ce qui empêche encore de désinstaller (None = rien). docs/uninstall.md §4 : sauvegarde cochée et ratée = bloqué.
    Et §3 : « la licence REAPER est toujours sauvegardée d'abord » — le moteur ne la copie pas lui-même, donc retirer
    ~/.config/REAPER sans sauvegarde vérifiée (qui porte identity/reaper-license.rk) est refusé ici."""
    B = U["backup"]
    if "reaper:config" in ids and B["state"] != "ok":
        return "removing the REAPER settings folder needs a verified backup first: it keeps your REAPER license"
    if B["enabled"]:
        if B["state"] == "fail":
            return "the backup failed its verification — nothing is removed. Fix the cause and back up again, or untick the backup."
        if B["state"] != "ok":
            return "back up first (or untick the backup)"
    elif not U["venv"] and not B["skip_confirmed"]:
        return "confirm that you continue without a backup"
    return None


# ── la désinstallation ─────────────────────────────────────────────────────────────────────────────────
def run_cmd(sel, attempt):
    if U["dry"]:
        planf = os.path.join(U["tmp"], "plan.json")
        with open(planf, "w", encoding="utf-8") as f:
            json.dump(U["plan"] or {"items": []}, f)
        return [sys.executable, os.path.join(U["tmp"], "installer", "dry_step.py"), "uninstall-run", sel, planf,
                "--attempt", str(attempt)]
    cmd = [sys.executable, engine_path(), "run", "--root", U["root"], "--select", sel, "--yes", "--json"]
    if U["run"]["log_path"]:
        cmd += ["--log", U["run"]["log_path"]]
    return cmd


def _log_path():
    """Le journal de la désinstallation : à côté de la sauvegarde s'il y en a une (il survit), sinon dans la copie."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    res = U["backup"]["result"] or {}
    if U["backup"]["state"] == "ok" and res.get("dest") and not res.get("dry"):
        return os.path.join(res["dest"], "uninstall-%s.log" % ts)
    return os.path.join(U["tmp"], "uninstall-%s.log" % ts) if U["tmp"] else None


def _do_run(ids, attempt):
    R = U["run"]
    sel = os.path.join(U["tmp"], "select-%d.json" % attempt)
    with open(sel, "w", encoding="utf-8") as f:
        json.dump(ids, f)
    cmd = run_cmd(sel, attempt)
    _log("$ " + " ".join(cmd), "uninstall")
    seen_done = None
    env = _env()
    env["GOLEM_UNINSTALL_WAIT_PID"] = str(os.getpid())   # Windows : Python ne part qu'après nous (il nous fait tourner)
    if U["tmp"]:
        env["GOLEM_UNINSTALLER_COPY"] = U["tmp"]          # Windows : le même veilleur efface la copie après nous
    try:
        p = subprocess.Popen(cmd, cwd=U["tmp"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        for ln in p.stdout:
            ln = ln.rstrip("\n")
            ev = None
            if ln.startswith("{"):
                try:
                    ev = json.loads(ln)
                except ValueError:
                    ev = None
            if not isinstance(ev, dict) or "step" not in ev:
                if ln.strip():
                    _log(ln, "uninstall")
                continue
            ok, item, msg = bool(ev.get("ok")), ev.get("item"), str(ev.get("msg") or "")
            kept = bool(ev.get("kept"))             # gardé exprès (un paquet d'avant golem en a besoin) : ni fait ni raté
            with LOCK:
                if item:
                    R["items"][item] = {"ok": ok, "msg": msg, "step": ev.get("step"), "kept": kept}
                if isinstance(ev.get("after_log"), str):
                    R["after_log"] = ev["after_log"]     # Windows : le journal du veilleur (Python après la fermeture)
                if isinstance(ev.get("deps"), int):
                    R["deps_removed"] += ev["deps"]
                if ev.get("step") != "done":            # l'avancement par étape du §5, pour la colonne de gauche
                    st = R["steps"].setdefault(str(ev.get("step")), {"n": 0, "fail": 0})
                    st["n"] += 1
                    st["fail"] += 0 if ok or kept else 1
                    R["current"] = ev.get("step")
                if ev.get("step") == "done":
                    seen_done = ok
            _log("%s %-7s %s%s" % ("✓" if ok else "✗", ev.get("step"), (item + ": ") if item else "", msg), "uninstall")
        rc = p.wait()
    except Exception as e:
        rc, seen_done = 127, False
        _log("✗ cannot start the uninstall: %s" % e, "uninstall")
    with LOCK:
        failed = [i for i in ids if not (R["items"].get(i) or {}).get("ok") and not (R["items"].get(i) or {}).get("kept")]
        R["failed"] = failed
        R["kept"] = sorted(i for i, v in R["items"].items() if v.get("kept"))
        R["done_ids"] = sorted({i for i, v in R["items"].items() if v.get("ok")})
        R["ok"] = bool(seen_done) and not failed
        R["error"] = None if seen_done is not None else "the uninstall stopped before the end (exit %s)" % rc
        R["state"], R["current"] = "done", None
        failed_run = not R["ok"]
    if failed_run:
        send_report()


def send_report():
    """Le rapport d'une désinstallation qui a échoué, envoyé sans clic (docs/diagnostics.md §7.1). Même paquet que
    l'installateur (installer/report.py), scrubbé par la copie de bridge/scrub.py ; en --dry : construit, jamais envoyé."""
    import tempfile
    import report as RP
    R, S = U["run"], CTX.S
    with LOCK:
        if U["report"]["state"] == "sending":
            return
        U["report"] = {"state": "sending", "code": None, "path": None, "error": None}
        steps = [{"id": k, "state": "fail" if v.get("fail") else "ok", "secs": None} for k, v in R["steps"].items()]
        if R["error"] and not any(x["state"] == "fail" for x in steps):
            steps.append({"id": "run", "state": "fail", "secs": None})
        st = {"src": U["tmp"] or os.path.dirname(HERE), "dir": U["root"], "running": False, "dry": U["dry"],
              "log_file": S.get("log_file"), "log": list(S.get("log") or []), "version": U["version"],
              "platform_name": getattr(CTX, "platform_name", None), "privilege": U["privilege"],
              "steps": steps, "failed_items": list(R["failed"]), "install": {"phases": []}}
        secrets_ = [S.get("sudo_pw")]
    try:
        b = RP.build(st, "uninstall", os.path.join(tempfile.gettempdir(), "golem-reports"), secrets=secrets_)
    except Exception as e:
        _log("✗ report not built: %s: %s" % (type(e).__name__, e), "report")
        with LOCK:
            U["report"] = {"state": "fail", "code": None, "path": None, "error": "the report could not be built (%s)" % e}
        return
    if U["dry"]:
        _log("(dry run) report built, not sent: %s" % b["path"], "report")
        with LOCK:
            U["report"] = {"state": "dry", "code": None, "path": b["path"], "error": None}
        return
    r = RP.send(b["path"], "uninstall")
    _log("report %s (%s)" % ("sent, code " + r["code"] if r["ok"] else "not sent: %s" % r["error"], b["path"]), "report")
    with LOCK:
        U["report"] = {"state": "sent" if r["ok"] else "fail", "code": r.get("code"), "path": b["path"],
                       "error": None if r["ok"] else r["error"]}


def start_run(retry=False):
    """Lance `uninstall.py run` sur la sélection (ou, en Retry, sur ce qui a échoué). Rend une erreur ou None."""
    R = U["run"]
    if R["state"] == "running":
        return None
    if not retry or U["report"]["state"] != "sending":
        U["report"] = {"state": None, "code": None, "path": None, "error": None}   # une nouvelle passe, un nouveau rapport
    g = gate()
    if g:
        return g
    if retry:
        plan = load_plan(force=not U["dry"])                # ce qui a échoué et existe ENCORE (le moteur refuse le reste)
        if plan is None:
            return U["plan_error"]
        present = {it["id"] for it in plan["items"]}
        ids = [i for i in R["failed"] if i in present]
        if not ids:
            return "nothing left to retry"
    else:
        if R["attempt"]:
            return "already uninstalled — use Retry for what failed"
        plan = load_plan()
        if plan is None:
            return U["plan_error"]
        ids = selection(plan)
        if not ids:
            return "nothing selected"
        g = gate(ids)
        if g:
            return g
    by = {it["id"]: it for it in plan["items"]}
    if U["privilege"] == "sudo" and any((by.get(i) or {}).get("privilege") == "root" for i in ids) and not U["dry"] \
            and not (CTX is not None and CTX.S.get("sudo_ok")):
        return "your password first"
    with LOCK:
        R["attempt"] += 1
        if not retry:
            R["chosen"] = list(ids)
            R["log_path"] = _log_path()
        R.update(state="running", ok=None, error=None, steps={}, current=None)
        attempt = R["attempt"]
    threading.Thread(target=_do_run, args=(ids, attempt), daemon=True).start()
    return None


def busy():
    return U["backup"]["state"] == "running" or U["run"]["state"] == "running"


def public():
    B = U["backup"]
    with LOCK:
        return {"root": U["root"], "tmp": U["tmp"], "venv": U["venv"], "privilege": U["privilege"],
                "venv_path": os.path.join(U["root"] or "", ".venv"),
                "backup": {k: B[k] for k in ("enabled", "dest", "secrets", "skip_confirmed", "state", "result", "error")},
                "run": json.loads(json.dumps(U["run"])), "gate": gate(), "plan_error": U["plan_error"],
                "report": dict(U["report"])}


# ── HTTP : les routes propres au mode (server.py garde /api/state, /api/log, /api/sudo, /api/quit) ──────────────
def handle_get(path, q):
    if path == "/api/uplan":
        return 200, plan_view()
    if path == "/api/backup/estimate":
        return 200, estimate(q.get("dest", [None])[0], (q.get("secrets", [None])[0] == "1") if "secrets" in q else None)
    if path == "/api/review":
        return 200, review()
    return None


def handle_post(path, b):
    if path == "/api/backup/config":
        err = set_backup(b)
        return 200, {"ok": err is None, "error": err, **public()}
    if path == "/api/backup/start":
        err = start_backup()
        return (200 if err is None else 400), {"ok": err is None, "error": err}
    if path == "/api/third":
        set_third(b.get("third") or {})
        return 200, {"ok": True, "third": U["third"]}
    if path in ("/api/uninstall", "/api/uninstall/retry"):
        if isinstance(b.get("third"), dict):
            set_third(b["third"])
        err = start_run(retry=path.endswith("/retry"))
        return (200 if err is None else 400), {"ok": err is None, "error": err}
    return None
