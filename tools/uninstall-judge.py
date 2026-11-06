#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le JUGE d'une désinstallation (docs/uninstall.md §7) : compare deux relevés de tools/footprint.sh (machine vierge,
machine désinstallée) et range chaque différence dans une de trois classes.

    uninstall-judge.py new-paths BEFORE AFTER
        ce qu'il faut passer à `dpkg -S` DANS la VM, un par ligne : les chemins apparus (section files), leurs
        dossiers parents sous /etc, et un motif par unité apparue (`*/systemd/user/x.service`, `/etc/init.d/x`)
    uninstall-judge.py new-links BEFORE AFTER
        les liens symboliques apparus sous /etc — la VM y répond par « lien<TAB>cible » (readlink -f)
    uninstall-judge.py judge BEFORE AFTER --out DIR [--plan PLAN] [--owners FILE] [--autoremove FILE] [--home DIR]
                                                    [--links FILE]
    uninstall-judge.py judge --win BEFORE AFTER --out DIR [--plan PLAN] [--home USERPROFILE]
        WINDOWS (docs/uninstall.md §9.6) : relevés de tools/footprint.ps1 — règles de judge_win (plus bas)

  (a) upgraded   un paquet de base monté de version (même nom, autre version) — pour information
  (b) kept       gardé exprès : la base du système (NEVER_APT de provision/uninstall.py) et les fichiers de ses
                 paquets, ce qu'un paquet d'avant golem possède, ce que le désinstallateur a proposé et que
                 l'utilisateur a gardé (le plan relevé après l'installation ; l'élément le plus précis gagne, et un
                 élément « revert » laisse son fichier en place), une dépendance qu'un paquet gardé retient encore,
                 la sauvegarde ; un lien sous /etc dont la cible est à un paquet gardé, un fichier écrit par le
                 postinst d'un paquet gardé dans un dossier de ce paquet, une unité activée par son paquet gardé ;
                 les caches du bureau (mimeinfo.cache, base MIME, icon-theme.cache…) dont une source reste ; un
                 dossier qui ne porte que du gardé, un dossier XDG standard vide — pour information
     Ce qui porte le nom de golem (hors du chemin du dossier personnel) n'est gardé que s'il a été proposé et gardé.
  (c) leftovers  tout le reste : une vraie trace, ou quelque chose d'avant golem qui a disparu -> code 1

Chaque classe va dans son fichier (upgraded.txt, kept.txt, leftovers.txt dans DIR), une ligne de diff par ligne,
suivie de sa raison. Bibliothèque standard seulement ; ne lance rien, ne touche à rien hors de DIR."""
import argparse
import fnmatch
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_U = _load("golem_uninstall_engine", "provision/uninstall.py")
NEVER_APT = _U.NEVER_APT
sys.modules.setdefault("uninstall", _U)             # la couche Windows du moteur importe le moteur commun sous ce nom
_W = _load("golem_uninstall_win", "provision/uninstall_win.py")
# les groupes que l'écran « golem » montre en lecture seule (installer/uninstaller.py) : coché = DOIT partir
GOLEM_GROUPS = ("golem", "reaper-links", "reaper-ini", "system", "dedicated")


# ── lecture ──────────────────────────────────────────────────────────────────────────────────────────
def sections(path):
    """Un relevé -> {section: set(lignes)} (les lignes avant la première section sont ignorées)."""
    out, cur = {}, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.startswith("## "):
                cur = ln[3:].strip()
                out.setdefault(cur, set())
            elif cur is not None and ln.strip():
                out[cur].add(ln.rstrip("\r"))       # un relevé Windows arrive en CRLF
    return out


def _never(pkg):
    return any(fnmatch.fnmatchcase(pkg, n) for n in NEVER_APT)


def _path_of(line):
    """« f /chemin » -> /chemin (section files)."""
    parts = line.split(" ", 1)
    return parts[1] if len(parts) == 2 and len(parts[0]) == 1 else None


def _inside(p, root):
    root = root.rstrip("/")
    return p == root or p.startswith(root + "/")


def parse_owners(text):
    """La sortie de `dpkg -S chemin…` -> {chemin: [paquets]} (les lignes « diversion » sont ignorées)."""
    own = {}
    for ln in (text or "").splitlines():
        if ln.startswith("diversion ") or ": " not in ln:
            continue
        pkgs, path = ln.split(": ", 1)
        own.setdefault(path.strip(), [])
        for p in pkgs.split(","):
            p = p.strip().split(":", 1)[0]
            if p and p not in own[path.strip()]:
                own[path.strip()].append(p)
    return own


def parse_sim(text):
    """La sortie de `apt-get -s autoremove --purge` -> les paquets qu'apt retirerait (même lecture que le moteur)."""
    return set(_U._sim_removed(text))


def parse_links(text):
    """links.txt (« chemin<TAB>cible », relevé par `readlink -f` dans la VM) -> {lien: cible}."""
    out = {}
    for ln in (text or "").splitlines():
        if "\t" in ln:
            p, t = ln.split("\t", 1)
            if p.strip() and t.strip():
                out[p.strip()] = t.strip()
    return out


def _etc_ancestors(p):
    """Les dossiers parents de `p` sous /etc, /etc lui-même exclu (il appartient à base-files : tout y passerait)."""
    out, cur = [], os.path.dirname(p)
    while cur.startswith("/etc/"):
        out.append(cur)
        cur = os.path.dirname(cur)
    return out


def _new_units(b, a):
    return sorted(a.get("units", set()) - b.get("units", set()))


def _unit_globs(line):
    """« user pipewire.service enabled » -> les motifs `dpkg -S` du fichier d'unité (et du script SysV)."""
    parts = line.split()
    if len(parts) < 2:
        return []
    scope, unit = parts[0], parts[1]
    out = ["*/systemd/%s/%s" % ("user" if scope == "user" else "system", unit)]
    if scope == "system":
        out.append("/etc/init.d/%s" % unit.rsplit(".", 1)[0])
    return out


def new_paths(before, after):
    """Ce qu'il faut demander à `dpkg -S` DANS la VM : les chemins apparus, leurs parents sous /etc (un fichier
    écrit par le postinst d'un paquet vit dans un dossier de ce paquet), et le fichier de chaque unité apparue."""
    b, a = sections(before), sections(after)
    new = sorted(p for p in (_path_of(x) for x in a.get("files", set()) - b.get("files", set())) if p)
    extra = {d for p in new if p.startswith("/etc/") for d in _etc_ancestors(p)} - set(new)
    globs = [g for ln in _new_units(b, a) for g in _unit_globs(ln)]
    return new + sorted(extra) + globs


def new_links(before, after):
    """Les liens symboliques apparus sous /etc : leur cible (readlink -f, dans la VM) dit à quel paquet ils servent."""
    b, a = sections(before), sections(after)
    return sorted(ln[2:] for ln in a.get("files", set()) - b.get("files", set())
                  if ln.startswith("l /etc/"))


# les fichiers que le postinst d'un paquet ÉCRIT dans un dossier partagé (*.d) : dpkg -S ne les connaît pas, et le
# dossier appartient à tout le monde — on dit lequel (relevé en VM, 2026-10-16)
GENERATED_BY = (
    ("/etc/security/limits.d/audio.conf", "jackd2"),
    ("/etc/security/limits.d/audio.conf.disabled", "jackd2"),
)
# les bases du bureau : (motif d'une SOURCE, motif d'un CACHE régénéré à partir d'elle)
DESKTOP_TREES = (
    (("~/.local/share/applications/*.desktop", "~/.gnome/apps/*.desktop"),
     ("~/.local/share/applications/mimeinfo.cache", "~/.local/share/applications/defaults.list",
      "~/.config/menus/applications-merged/xdg-desktop-menu-dummy.menu")),
    (("~/.local/share/icons/hicolor/**",), ("~/.local/share/icons/hicolor/icon-theme.cache",)),
    (("~/.local/share/mime/packages/*",), ("~/.local/share/mime/**",)),
)
# les dossiers de base du bureau (XDG) : n'importe quel outil les crée ; vides ou ne portant que du gardé, ils restent
XDG_BASE = ("~/.config", "~/.local", "~/.local/bin", "~/.local/share", "~/.local/state", "~/.local/share/applications",
            "~/.local/share/icons", "~/.local/share/icons/hicolor", "~/.local/share/mime", "~/.config/menus",
            "~/.config/menus/applications-merged", "~/.config/autostart", "~/.config/systemd",
            "~/.config/systemd/user")


def _glob_match(pat, p):
    """`**` = n'importe quelle profondeur (au moins un niveau) ; sinon comparaison composant par composant."""
    if pat.endswith("/**"):
        return p.startswith(pat[:-2])
    return _U._match(pat, p)


def _desk_source(tree, p, expand):
    """Une SOURCE de cette base du bureau (une entrée .desktop, une icône, un paquet MIME) — jamais un cache exact."""
    return any(_glob_match(expand(x), p) for x in tree[0]) \
        and not any(_glob_match(expand(c), p) for c in tree[1] if not c.endswith("/**"))


def _desk_cache(tree, p, expand):
    return any(_glob_match(expand(c), p) for c in tree[1]) and not _desk_source(tree, p, expand)


# ── le jugement ──────────────────────────────────────────────────────────────────────────────────────
def judge(before, after, plan=None, owners=None, autoremove=None, home=None, links=None):
    """Rend {"upgraded": [(ligne, raison)], "kept": [...], "leftovers": [...]} — fonction PURE sur ses entrées."""
    b, a = sections(before), sections(after)
    if "versions" not in b or "versions" not in a:
        raise ValueError("a footprint has no '## versions' section: take it again with the current tools/footprint.sh")
    owners, autoremove, plan, links = owners or {}, autoremove or set(), plan or {}, links or {}
    res = {"upgraded": [], "kept": [], "leftovers": []}

    def put(cls, line, why):
        res[cls].append((line, why))

    items = plan.get("items") or []
    apt_items = {i["id"][4:] for i in items if i.get("group") == "apt"}
    apt_deps = set(plan.get("apt_deps") or [])

    def expand(p):
        return (home + p[1:]) if home and (p == "~" or p.startswith("~/")) else p

    # les chemins proposés par le désinstallateur : (chemin, id, doit partir). Un élément « revert »/« restore »
    # (reaper.ini, ufw, un original remis) laisse son chemin EN PLACE : il ne « doit » pas disparaître
    offered = [(expand(p), i["id"], i.get("group") in GOLEM_GROUPS and bool(i.get("default"))
                and i.get("action") not in ("revert", "restore"), i.get("action"))
               for i in items for p in (i.get("paths") or [])]
    before_pkgs = {ln.split()[0] for ln in b.get("packages", set())}
    after_installed = {ln.split()[0] for ln in a.get("packages", set()) if "(" not in ln}

    def pkg_class(name):
        """(classe, raison) pour un paquet encore là après la désinstallation."""
        if _never(name):
            return "kept", "system base (NEVER_APT): never removed"
        if name in before_pkgs:
            return "kept", "installed before golem"
        if name in apt_items:
            return "kept", "offered by the uninstaller and kept"
        if name in apt_deps:
            if name in autoremove:
                return "leftovers", "golem dependency left behind (apt would autoremove it)"
            return "kept", "dependency still needed by a package that stays"
        return "leftovers", "not in golem's plan" if plan else "no plan to explain it"

    def owner_class(pkgs, what):
        """Un fichier rattaché à des paquets : gardé si l'un d'eux est gardé ET encore installé."""
        kinds = []
        for o in pkgs:
            if a.get("packages") and o not in after_installed:
                kinds.append((o, "leftovers", "%s is no longer installed: its file stayed behind" % o))
            else:
                kinds.append((o,) + pkg_class(o))
        ok = [k for k in kinds if k[1] == "kept"]
        k = ok[0] if ok else kinds[0]
        return k[1], "%s %s (%s)" % (what, k[0], k[2])

    def golem_named(p):
        """Le NOM de golem dans le chemin — hors du dossier personnel, dont l'utilisateur peut s'appeler golem (VM)."""
        if home and _inside(p, home):
            p = p[len(home):]
        return "golem" in p.lower()

    def offered_hit(p):
        """L'élément proposé le plus PRÉCIS qui contient `p` ; à précision égale, le gardé gagne."""
        hits = [o for o in offered if _inside(p, o[0])]
        if not hits:
            return None
        return max(hits, key=lambda o: (len(o[0]), not o[2]))

    # (a) les montées de version
    bv = dict(ln.split(" ", 1) for ln in b["versions"] if " " in ln)
    av = dict(ln.split(" ", 1) for ln in a["versions"] if " " in ln)
    for name in sorted(set(bv) & set(av)):
        if bv[name] != av[name]:
            put("upgraded", "~ %s %s -> %s" % (name, bv[name], av[name]), "upgraded base package")

    # ── les fichiers : d'abord tout ce qui n'est pas un dossier, puis les dossiers du plus profond au moins profond ──
    new_files = sorted(a.get("files", set()) - b.get("files", set()))
    all_after = {_path_of(x) for x in a.get("files", set())} - {None}
    dirs_after = {_path_of(x) for x in a.get("files", set()) if x.startswith("d ")}
    children = {}
    for p in all_after:
        children.setdefault(os.path.dirname(p), []).append(p)
    verdict = {}                                            # chemin -> (classe, raison)

    def file_class(kind, p):
        if "golem-backup-" in p:
            return "kept", "your backup"
        hit = offered_hit(p)
        if hit:
            if hit[2]:
                return "leftovers", "should have gone with %s" % hit[1]
            if hit[3] in ("revert", "restore") and hit[0] == p:
                return "kept", "set back in place by %s (the file itself stays)" % hit[1]
            return "kept", "offered by the uninstaller (%s) and kept" % hit[1]
        if owners.get(p):
            return owner_class(owners[p], "belongs to")
        if golem_named(p):
            return "leftovers", "carries golem's name, not offered by the uninstaller"
        if kind == "l" and p in links and owners.get(links[p]):
            return owner_class(owners[links[p]], "link to a file of")
        gen = [pkg for f, pkg in GENERATED_BY if p == f]
        if gen:
            return owner_class(gen, "written by the postinst of")
        if p.startswith("/etc/") and kind != "d":
            for d in _etc_ancestors(p):
                if d.endswith(".d") or d.startswith("/etc/systemd"):
                    break                                   # un dossier partagé : son propriétaire ne dit rien
                if owners.get(d):
                    return owner_class(owners[d], "written in a folder of")
        return None

    sources = []                                            # les caches du bureau se jugent après leurs sources
    for ln in new_files:
        kind, p = ln[0], _path_of(ln) or ""
        if kind == "d":
            continue
        tree = next((t for t in DESKTOP_TREES if _desk_cache(t, p, expand)), None)
        if tree and not offered_hit(p) and not owners.get(p):
            sources.append((ln, p, tree))
            continue
        verdict[p] = file_class(kind, p) or ("leftovers", "not owned by any package, not offered by the uninstaller")
    for ln, p, tree in sources:
        src = [q for q in all_after if _desk_source(tree, q, expand) and q not in dirs_after]
        alive = [q for q in src if verdict.get(q, ("kept",))[0] == "kept"]
        if alive:
            verdict[p] = ("kept", "desktop cache of entries that stay (%s)" % os.path.basename(sorted(alive)[0]))
        elif src:
            verdict[p] = ("leftovers", "desktop cache of %s, itself a leftover" % os.path.basename(sorted(src)[0]))
        else:
            verdict[p] = ("leftovers", "desktop cache left behind: nothing it describes is here any more")
    xdg = {expand(x) for x in XDG_BASE}
    for ln in sorted((x for x in new_files if x[0] == "d"), key=lambda x: -len(x)):
        p = _path_of(ln) or ""
        c = file_class("d", p)
        if c is None or (c[0] == "leftovers" and not offered_hit(p) and not golem_named(p)):
            kids = children.get(p, [])
            if kids and all(verdict.get(k, ("kept",))[0] == "kept" for k in kids):
                held = sorted(k for k in kids if k in verdict) or sorted(kids)
                c = ("kept", "holds only what stays (%s)" % os.path.basename(held[0]))
            elif not kids and p in xdg:
                c = ("kept", "standard desktop folder (XDG), empty")
            elif c is None:
                c = ("leftovers", "empty folder, not owned by any package" if not kids else
                     "not owned by any package, not offered by the uninstaller")
        verdict[p] = c

    for sec in sorted(set(a) | set(b)):
        if sec == "versions":
            continue
        gone = sorted(b.get(sec, set()) - a.get(sec, set()))
        new = sorted(a.get(sec, set()) - b.get(sec, set()))
        for ln in gone:
            put("leftovers", "< [%s] %s" % (sec, ln), "was here before golem, and is gone or changed")
        for ln in new:
            tag = "> [%s] %s" % (sec, ln)
            if "golem-backup-" in ln:
                put("kept", tag, "your backup")
            elif sec == "packages":
                cls, why = pkg_class(ln.split()[0])
                put(cls, tag, why)
            elif sec == "files":
                cls, why = verdict[_path_of(ln) or ""]
                put(cls, tag, why)
            elif sec == "units":
                cls, why = unit_class(ln, owners, owner_class)
                put(cls, tag, why)
            elif sec == "reaper.ini" and "golem" not in ln.lower() \
                    and any(i["id"] == "reaper:config" for i in items):
                put("kept", tag, "REAPER settings, kept (reaper:config)")
            else:
                put("leftovers", tag, "changed by golem and not put back")
    return res


def unit_class(line, owners, owner_class):
    """Une unité activée ou masquée qui n'y était pas : jugée comme le paquet qui la livre (son fichier d'unité ou
    son script SysV, trouvés par `dpkg -S` dans la VM)."""
    parts = line.split()
    if len(parts) < 2 or "golem" in line.lower():
        return "leftovers", "changed by golem and not put back"
    scope, unit = parts[0], parts[1]
    want = ["/systemd/%s/%s" % ("user" if scope == "user" else "system", unit)]
    if scope == "system":
        want.append("/etc/init.d/%s" % unit.rsplit(".", 1)[0])
    pkgs = []
    for path, pk in owners.items():
        if any(path.endswith(w) if w.startswith("/systemd/") else path == w for w in want):
            pkgs += [x for x in pk if x not in pkgs]
    if not pkgs:
        return "leftovers", "changed by golem and not put back (no package ships this unit)"
    cls, why = owner_class(pkgs, "unit of")
    state = parts[2] if len(parts) > 2 else "enabled"
    return cls, why + (": %s by its package" % state if cls == "kept" else "")


# ── WINDOWS (docs/uninstall.md §9.6) ─────────────────────────────────────────────────────────────────
# Le BRUIT de Windows : ce qui bouge tout seul entre deux relevés, sans rapport avec golem. Liste EXPLICITE (regex sur
# le chemin, sans casse) — à compléter quand une VM montre un nouveau bruit, jamais pour cacher une trace : un chemin
# qui porte « golem » n'est JAMAIS du bruit. tools/footprint.ps1 en filtre déjà le gros (pour la taille du relevé).
WIN_NOISE = (
    (r"\\AppData\\Local\\Temp(\\|$)", "temporary files"),
    (r"\\AppData\\Local\\Microsoft(\\|$)", "Windows, Edge and OneDrive caches"),
    (r"\\AppData\\Roaming\\Microsoft(\\|$)", "Windows profile churn (recent files, PowerShell history, credentials)"),
    (r"\\AppData\\Local\\Packages(\\|$)", "Store apps"),
    (r"\\AppData\\LocalLow(\\|$)", "low-integrity caches"),
    (r"\\AppData\\Local\\(ConnectedDevicesPlatform|D3DSCache|CrashDumps|Comms|PlaceholderTileLogoFolder|Publishers|"
     r"PeerDistRepub)(\\|$)", "Windows caches"),
    (r"\\AppData\\Local\\IconCache\.db$", "icon cache"),
    (r"\\AppData\\Local\\(Google\\Chrome|Mozilla)(\\|$)", "your own browser"),
    (r"\\AppData\\Local\\OneDrive(\\|$)|\\OneDrive(\\|$)", "OneDrive"),
    (r"\\ProgramData\\Microsoft(\\|$)", "Windows, Defender, Search, WER"),
    (r"\\ProgramData\\(Packages|USOShared|USOPrivate|regid\.[^\\]*|ssh)(\\|$)", "Windows Update, Store, ssh server"),
    (r"\\Prefetch(\\|$)", "Prefetch"),
    (r"\\(NTUSER\.DAT|ntuser\.dat\.LOG\d|ntuser\.ini)", "your registry hive"),
)
# un programme tiers proposé : ses motifs de DisplayName (ceux du moteur) ; le runtime VC++ = la base du système
WIN_PROGRAMS = {"programs:%s" % p[0]: p[4] for p in _W.PROGRAMS}
WIN_PROGRAMS["toolchain:python"] = _W.PYTHON_PATTERNS
WIN_EXES = {"programs:reaper": ("reaper.exe",), "toolchain:python": ("python.exe", "pythonw.exe")}
# les mots d'un raccourci de menu Démarrer qu'un programme gardé pose lui-même
# le bundle de plugin que chaque programme proposé pose dans Common Files\VST3|LV2|CLAP (ses sondes, dans le moteur) :
# un fichier y est rangé au programme dont il est le bundle — jamais à toolchain:python
WIN_BUNDLES = {"programs:%s" % p[0]: tuple(os.path.basename(rel).lower() for _v, rel in p[3]) for p in _W.PROGRAMS}
# les composants que Windows pose ou met à jour TOUT SEUL entre deux relevés (VM, 2026-10-16 : OneDrive s'est
# réenregistré dans HKCU avec son raccourci du menu Démarrer) : leur clé « Uninstall » et leur raccourci apparus sont
# du va-et-vient, jamais une trace de golem. Liste EXPLICITE, à compléter d'après une VM
WIN_CHURN_PROGRAMS = ("Microsoft OneDrive", "OneDrive", "Microsoft Edge", "Microsoft Edge Update",
                      "Microsoft Edge WebView2 Runtime", "Microsoft Update Health Tools", "Microsoft Teams*",
                      # la base de correctifs de compatibilité : Windows l'enregistre seul la première fois qu'il examine un
                      # programme installé (3e cycle VM, 2026-10-16) — un composant de Windows, pas de golem
                      "Microsoft Windows Application Compatibility Fix Database")
# le journal du veilleur (installer/after_exit_win.py) : gardé exprès, il dit ce qui s'est passé après la fermeture
AFTER_LOG = "golem-after-uninstall-"
WIN_SHORTCUT_WORDS = {"programs:reaper": ("reaper",), "programs:nam_vst3": ("neural",), "programs:avldrums": ("avl",),
                      "programs:sfizz": ("sfizz",), "programs:pawpaw": ("pawpaw",), "toolchain:python": ("python",)}


def _wl(p):
    return p.replace("/", "\\").rstrip("\\").lower()


def _winside(p, root):
    p, root = _wl(p), _wl(root)
    return bool(root) and (p == root or p.startswith(root + "\\"))


def _wmatch(name, pats):
    return any(fnmatch.fnmatch(name.lower(), x.lower()) for x in pats)


def _wnoise(p, home=None):
    """La raison si `p` est du bruit de Windows ; None sinon. Le nom de golem n'est jamais du bruit (hors du chemin du
    profil : l'utilisateur de la VM peut s'appeler golem)."""
    import re
    if "golem" in (p[len(home):] if home and _winside(p, home) else p).lower():
        return None
    return next((why for rx, why in WIN_NOISE if re.search(rx, p, re.I)), None)


def parse_chosen(text):
    """Ce que l'utilisateur a VRAIMENT choisi, relevé dans la VM -> set d'ids, ou None (rien de lisible : le juge
    prend alors les choix par défaut du plan). Lit : une liste JSON (select-<n>.json du désinstallateur, ou {"items":
    […]}), des lignes « SELECT <json> » (tools/check-uninstall-vm.sh, une par tentative : réunies), et le journal
    de la désinstallation (« <date> [<étape>] <id> OK|FAILED <message> », à côté de la sauvegarde)."""
    import re
    text = (text or "").strip()
    if not text:
        return None
    ids = set()

    def take(data):
        if isinstance(data, dict):
            data = data.get("items") or data.get("ids") or []
        for x in data if isinstance(data, list) else []:
            if isinstance(x, str):
                ids.add(x)
            elif isinstance(x, dict) and x.get("id") and x.get("selected", True):
                ids.add(x["id"])
    try:
        take(json.loads(text))
        return ids or None
    except ValueError:
        pass
    logline = re.compile(r"^\S+ \[[^\]]+\] (.+?) (OK|FAILED)( |$)")
    for ln in text.splitlines():
        ln = ln.strip().lstrip("\ufeff")
        if ln.startswith("LOG "):
            ln = ln[4:]
        if ln.startswith("SELECT "):
            try:
                take(json.loads(ln[7:]))
            except ValueError:
                pass
            continue
        m = logline.match(ln)
        if m and m.group(1) != "-":
            ids.add(m.group(1))
    return ids or None


def judge_win(before, after, plan=None, home=None, chosen=None):
    """Windows : {"upgraded": [], "kept": [...], "leftovers": [...]} — fonction PURE. Règles, dans l'ordre :
      · un programme (clé « Uninstall ») : la base du système (VC++) -> gardé ; un programme que le désinstallateur a
        PROPOSÉ (groupes programs, toolchain) et qui est encore là -> gardé (l'utilisateur l'a décoché) ; sinon trace ;
      · un fichier : la sauvegarde -> gardé ; dans un élément proposé -> l'élément le plus précis décide (de l'écran
        golem coché : il devait partir) ; dans le dossier d'un programme GARDÉ (InstallLocation, dossier de son
        désinstalleur) -> gardé ; un bundle de plugin (sous Common Files\\VST3|LV2|CLAP) : au programme dont il est
        le bundle (gardé -> gardé, retiré -> trace), un bundle inconnu à un PROGRAMME gardé (jamais à Python, jamais le
        dossier commun lui-même) ; le journal du veilleur (golem-after-uninstall-*.log) -> gardé ; le cache d'installeurs de Windows (Package Cache) d'un programme gardé -> gardé ; le bruit
        (WIN_NOISE) -> gardé ; le nom de golem -> trace ; le reste -> trace. Un dossier : gardé s'il ne porte que du
        gardé ;
      · une règle du pare-feu apparue : une règle de golem (proposée et choisie, un nom fixe, le nom de golem) ->
        trace ; proposée et gardée (un nom « golem* » qui n'est pas à golem) -> gardé ; celle d'un programme gardé
        (reaper.exe, python.exe) -> gardé, d'un programme retiré -> trace ; toute autre -> gardé (le va-et-vient des
        applis de Windows). Une règle d'AVANT golem disparue (ou changée) -> trace (elle devait être recréée) ;
      · un raccourci : dans un élément proposé ou au nom d'un programme gardé -> gardé ; sinon trace ;
      · le plan d'alimentation changé -> trace. Pas de « montée de version » sous Windows (a) : vide.
      · toute ligne d'avant golem disparue -> trace (sauf un chemin du bruit de Windows : la version de OneDrive
        remplacée, un .tmp de Temp).
    `chosen` : les ids que l'utilisateur a VRAIMENT choisis (parse_chosen) ; None = les choix par défaut du plan
    (l'écran golem coché, les tiers selon leur case par défaut)."""
    b, a = sections(before), sections(after)
    plan = plan or {}
    res = {"upgraded": [], "kept": [], "leftovers": []}
    items = plan.get("items") or []

    def put(cls, line, why):
        res[cls].append((line, why))
    keys_after = {ln.split(" ", 1)[1] for ln in a.get("uninstall-keys", set()) if " " in ln}
    keys_before = {ln.split(" ", 1)[1] for ln in b.get("uninstall-keys", set()) if " " in ln}
    offered_ids = {i["id"] for i in items}

    def must_go(i):
        # un « revert »/« restore » laisse son chemin en place ; un dossier commun vidé n'est retiré que s'il est vide
        if i.get("action") in ("revert", "restore", "remove-empty-dirs"):
            return False
        if chosen is not None:
            return i["id"] in chosen
        return i.get("group") in GOLEM_GROUPS and bool(i.get("default"))
    present_prog = {pid for pid, pats in WIN_PROGRAMS.items() if pid in offered_ids
                    and any(_wmatch(k, pats) for k in keys_after)}
    # un programme GARDÉ : proposé, encore là, et pas choisi (choisi et encore là = son désinstalleur a échoué)
    kept_prog = {pid for pid in present_prog if chosen is None or pid not in chosen}
    vc = any(_wmatch(k, _W.NEVER_PATTERNS) for k in keys_after)
    kept_names = {k for k in keys_after if _wmatch(k, _W.NEVER_PATTERNS) or k in keys_before
                  or any(_wmatch(k, WIN_PROGRAMS[p]) for p in kept_prog)}
    roots = []
    for ln in a.get("install-locations", set()):
        parts = [x.strip() for x in ln.split(" | ")]
        if len(parts) == 3 and parts[0] in kept_names:
            roots += [(r, parts[0]) for r in parts[1:] if r]
    # un dossier commun des plugins (system:common-dirs) ne « contient » rien : ce qu'il porte est jugé pour soi, et
    # lui-même comme un dossier (gardé s'il ne porte que du gardé, trace s'il est resté vide)
    offered = [(p, i["id"], must_go(i), i.get("action"))
               for i in items if i.get("action") != "remove-empty-dirs" for p in (i.get("paths") or [])]

    def offered_hit(p):
        hits = [o for o in offered if _winside(p, o[0])]
        return max(hits, key=lambda o: (len(o[0]), not o[2])) if hits else None

    def file_class(p):
        if "golem-backup-" in p.lower():
            return "kept", "your backup"
        hit = offered_hit(p)
        if hit:
            if hit[2]:
                return "leftovers", "should have gone with %s" % hit[1]
            if hit[3] in ("revert", "restore") and _wl(hit[0]) == _wl(p):
                return "kept", "set back in place by %s (the file itself stays)" % hit[1]
            if hit[1] in WIN_PROGRAMS and hit[1] not in kept_prog:
                return "leftovers", "left behind by the uninstaller of %s" % hit[1]
            return "kept", "offered by the uninstaller (%s) and kept" % hit[1]
        own = next((n for r, n in roots if _winside(p, r)), None)
        if own:
            return "kept", "inside %s, a program that stays" % own
        low = _wl(p)
        # un BUNDLE de plugin (un niveau sous Common Files\VST3|LV2|CLAP, ou plus bas) : rangé au programme dont il
        # est le bundle ; un bundle inconnu (PawPaw en pose plusieurs) à un PROGRAMME gardé — jamais à
        # toolchain:python, et jamais le dossier commun lui-même (il se juge comme un dossier)
        m = next((low.split("\\common files\\%s\\" % k, 1)[1] for k in ("vst3", "lv2", "clap")
                  if "\\common files\\%s\\" % k in low), None)
        if m and "golem" not in low:
            bundle = m.split("\\", 1)[0]
            owner = next((pid for pid, names in WIN_BUNDLES.items() if bundle in names), None)
            if owner and owner in kept_prog:
                return "kept", "a plugin of %s, a program you kept" % owner
            if owner and owner in offered_ids:
                return "leftovers", "a plugin of %s, left behind by its uninstaller" % owner
            progs = sorted(x for x in kept_prog if x.startswith("programs:"))
            if not owner and progs:
                return "kept", "a plugin of a program you kept (%s)" % ", ".join(progs)
        if AFTER_LOG in low and low.endswith(".log"):
            return "kept", "the uninstaller's after-exit log (Python removal, copy cleanup): kept for you to read"
        if "\\package cache\\" in low + "\\":
            if "\\programdata\\" in low and vc:
                return "kept", "installer cache of the Visual C++ runtime (system base)"
            if "toolchain:python" in kept_prog:
                return "kept", "installer cache of the Python you kept"
        why = _wnoise(p, home)
        if why:
            return "kept", "Windows noise: %s" % why
        if "golem" in (p[len(home):] if home and _winside(p, home) else p).lower():
            return "leftovers", "carries golem's name, not removed"
        return None

    def prog_class(name):
        if _wmatch(name, _W.NEVER_PATTERNS):
            return "kept", "system base (Visual C++ runtime): never offered"
        hit = next((p for p, pats in WIN_PROGRAMS.items() if _wmatch(name, pats) and p in offered_ids), None)
        if hit and hit not in kept_prog:
            return "leftovers", "chosen for removal (%s), still installed" % hit
        if hit:
            return "kept", "offered by the uninstaller (%s) and kept" % hit
        if "golem" in name.lower():
            return "leftovers", "golem's own program entry"
        if _wmatch(name, WIN_CHURN_PROGRAMS):
            return "kept", "Windows churn: a Microsoft component Windows installs or updates by itself"
        return "leftovers", "a program the install added, not offered by the uninstaller"

    verdict = {}
    for sec in ("program-files", "files"):
        new = sorted(a.get(sec, set()) - b.get(sec, set()))
        allp = {_path_of(x) for x in a.get(sec, set())} - {None}
        children = {}
        for q in allp:
            children.setdefault(_wl(q.rsplit("\\", 1)[0]), []).append(q)
        for ln in new:
            if ln.startswith("d "):
                continue
            p = _path_of(ln) or ""
            verdict[p] = file_class(p) or ("leftovers", "not offered by the uninstaller")
        for ln in sorted((x for x in new if x.startswith("d ")), key=lambda x: -len(x)):
            p = _path_of(ln) or ""
            c = file_class(p)
            if c is None:
                kids = children.get(_wl(p), [])
                if kids and all(verdict.get(k, ("kept",))[0] == "kept" for k in kids):
                    c = ("kept", "holds only what stays")
                else:
                    c = ("leftovers", "empty folder left behind" if not kids else "not offered by the uninstaller")
            verdict[p] = c
    kept_exes = {e for p in kept_prog for e in WIN_EXES.get(p, ())}
    gone_exes = {e: p for p in offered_ids - kept_prog for e in WIN_EXES.get(p, ())}
    prog_words = {w for p in kept_prog for w in WIN_SHORTCUT_WORDS.get(p, ())}
    # les règles du pare-feu de golem : celles que le plan proposait (system:firewall:<nom>), ses noms fixes, et tout
    # nom qui porte « golem » ; le reste des règles apparues est le va-et-vient de Windows (applis du Store mises à
    # jour : Teams, Xbox, Calculatrice…) — jamais une règle d'AVANT golem disparue, qui reste une trace
    fw_plan = {i["id"][len("system:firewall:"):].lower(): i for i in items if i["id"].startswith("system:firewall:")
               and i["id"] != "system:firewall-restore"}
    fw_fixed = {n.lower() for n in _W.FIREWALL_FIXED}

    def exe_of(name):
        n = name.lower()
        return next((e for e in set(kept_exes) | set(gone_exes) if n == e or n.startswith(e.rsplit(".", 1)[0])), None)

    def _fw_ours(name, exe_of):
        """Une règle que golem a pu toucher : à son nom, ou liée à un programme qu'il a posé ou retiré."""
        n = name.lower()                          # python : l'installation supprime les règles Windows de son Python
        return "golem" in n or n in fw_fixed or n.startswith("python") or bool(exe_of(name))

    def fw_class(name):
        it = fw_plan.get(name.lower())
        if it is not None:
            if must_go(it):
                return "leftovers", "golem's firewall rule, not removed"
            return "kept", "offered by the uninstaller (%s) and kept" % it["id"]
        if name.lower() in fw_fixed or "golem" in name.lower():
            return "leftovers", "golem's firewall rule, not removed"
        e = exe_of(name)
        if e and e in kept_exes:
            return "kept", "Windows' own rule for a program you kept"
        if e:
            return "leftovers", "Windows' rule for %s, which was removed: the rule stayed" % gone_exes[e]
        return "kept", "Windows churn: a rule a Windows or Store app update added, not golem's"
    for sec in sorted(set(a) | set(b)):
        if sec in ("versions", "install-locations"):
            continue
        for ln in sorted(b.get(sec, set()) - a.get(sec, set())):
            why = _wnoise(_path_of(ln) or "", home) if sec in ("program-files", "files") else None
            if why:
                put("kept", "< [%s] %s" % (sec, ln), "Windows noise, gone by itself: %s" % why)
            elif sec == "firewall" and not _fw_ours(ln.split(" | ", 1)[0], exe_of):
                # une règle d'appli du Store que Windows a mise à jour pendant le test (2e cycle, 2026-10-16) — le
                # désinstalleur ne touche qu'aux règles de golem ; une règle à NOM de golem qui disparaît (« GoleM sshd »,
                # 1er cycle) ou liée à un programme que golem a touché reste un vrai reste
                put("kept", "< [%s] %s" % (sec, ln), "Windows churn: a rule a Windows or Store app update removed")
            else:
                put("leftovers", "< [%s] %s" % (sec, ln), "was here before golem, and is gone or changed")
        for ln in sorted(a.get(sec, set()) - b.get(sec, set())):
            tag = "> [%s] %s" % (sec, ln)
            if sec == "uninstall-keys":
                cls, why = prog_class(ln.split(" ", 1)[1] if " " in ln else ln)
                put(cls, tag, why)
            elif sec in ("program-files", "files"):
                cls, why = verdict[_path_of(ln) or ""]
                put(cls, tag, why)
            elif sec == "firewall":
                cls, why = fw_class(ln.split(" | ", 1)[0])
                put(cls, tag, why)
            elif sec == "shortcuts":
                hit = offered_hit(ln)
                low = os.path.basename(ln.replace("\\", "/")).lower()
                if hit and not hit[2]:
                    put("kept", tag, "offered by the uninstaller (%s) and kept" % hit[1])
                elif not hit and "golem" not in low and any(w in _wl(ln) for w in prog_words):
                    put("kept", tag, "a shortcut of a program you kept")
                elif not hit and "golem" not in low and _wmatch(low.rsplit(".", 1)[0], WIN_CHURN_PROGRAMS):
                    put("kept", tag, "Windows churn: the shortcut of a Microsoft component Windows updates by itself")
                else:
                    put("leftovers", tag, "a shortcut left behind")
            elif sec == "power":
                put("leftovers", tag, "power plan not set back")
            else:
                put("leftovers", tag, "changed by golem and not put back")
    return res


def write(res, out):
    os.makedirs(out, exist_ok=True)
    for cls, rows in res.items():
        with open(os.path.join(out, cls + ".txt"), "w", encoding="utf-8") as f:
            for line, why in rows:
                f.write("%s\t# %s\n" % (line, why))


def summary(res, out, head=12):
    lab = {"upgraded": "(a) upgraded base packages — informational",
           "kept": "(b) kept by design or by choice — informational",
           "leftovers": "(c) REAL leftovers"}
    for cls in ("upgraded", "kept", "leftovers"):
        rows = res[cls]
        print("%s %s: %d → %s" % ("✗" if cls == "leftovers" and rows else "·", lab[cls], len(rows),
                                  os.path.join(out, cls + ".txt")))
        # une raison, un compte : le résumé tient sur un écran même avec des centaines de lignes
        by = {}
        for _line, why in rows:
            by[why] = by.get(why, 0) + 1
        for why, n in sorted(by.items(), key=lambda x: -x[1]):
            print("    %4d  %s" % (n, why))
        for line, why in rows[:200 if cls == "leftovers" else head]:
            print("        %s   # %s" % (line, why))
        if len(rows) > (200 if cls == "leftovers" else head):
            print("        …")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="uninstall-judge.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new-paths")
    n.add_argument("before")
    n.add_argument("after")
    nl = sub.add_parser("new-links")
    nl.add_argument("before")
    nl.add_argument("after")
    j = sub.add_parser("judge")
    j.add_argument("before")
    j.add_argument("after")
    j.add_argument("--out", required=True)
    j.add_argument("--plan")
    j.add_argument("--owners")
    j.add_argument("--autoremove")
    j.add_argument("--home")
    j.add_argument("--links")
    j.add_argument("--win", action="store_true", help="Windows footprints (tools/footprint.ps1)")
    j.add_argument("--chosen", help="--win: what was really chosen (select-*.json, the uninstall log, or SELECT/LOG "
                                    "lines); without it, the plan's defaults")
    o = ap.parse_args(argv)
    if o.cmd in ("new-paths", "new-links"):
        print("\n".join((new_paths if o.cmd == "new-paths" else new_links)(o.before, o.after)))
        return 0

    def read(p):
        if not p or not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    plan = None
    if read(o.plan):
        try:
            plan = json.loads(read(o.plan))
        except ValueError:
            print("⚠ %s is not a plan (JSON): offered items cannot be recognised" % o.plan)
    if plan is None:
        print("⚠ no uninstall plan (take it at the `installed` step): what you chose to keep counts as a leftover")
    try:
        if o.win:
            chosen = parse_chosen(read(o.chosen))
            print("· what you chose: %s" % ("%d item(s), read from %s" % (len(chosen), o.chosen) if chosen is not None
                                            else "unknown — the plan's defaults are assumed"))
            res = judge_win(o.before, o.after, plan, o.home, chosen)
        else:
            res = judge(o.before, o.after, plan, parse_owners(read(o.owners)), parse_sim(read(o.autoremove)), o.home,
                        parse_links(read(o.links)))
    except ValueError as e:
        print("✗ %s" % e)
        return 2
    write(res, o.out)
    summary(res, o.out)
    if res["leftovers"]:
        return 1
    print("✓ nothing left: the machine is back to its clean state (upgrades and what you kept aside)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
