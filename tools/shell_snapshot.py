#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'INSTANTANÉ pour la coquille de golem.fm (docs/shell.md, 2026-10-09).

golem.fm affiche l'interface EXACTE du rack, en lecture seule, dans une iframe : son `shell.js` répond aux lectures
`/api/…` avec des JSON qu'il possède. Cet outil les fabrique : il parcourt les lectures GET de l'app sur un bridge qui
tourne, et écrit `<out>/api/<chemin>.json` — EXPURGÉ (la liste vit dans docs/shell.md §3).

Deux couches, jamais une seule :
  1. EXPURGER : par NOM de champ (jetons, mots de passe, e-mails, adresses…) et par FORME de valeur (IP, MAC, e-mail,
     chemin de disque, nom de machine, numéro de série du rack) ;
  2. VÉRIFIER : chaque fichier est relu après expurgation ; s'il reste UNE trace, l'outil n'écrit pas ce fichier, le dit,
     et sort en erreur. Un instantané part sur un site public : une fuite ne se rattrape pas.

    ./tools/shell_snapshot.py [--base http://localhost:8770] [--out shell-snapshot] [--list lectures.txt]

`--list` : un fichier, une lecture par ligne (`/api/presets`, `/api/preset/paper-kite`…) — celle que golem.fm relève
dans l'app ; sans lui, la liste par défaut ci-dessous (+ chaque preset, patch et chanson du rack).
"""
import argparse
import contextlib
import json
import os
import re
import socket
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── les lectures ─────────────────────────────────────────────────────────────────────────────────
DEFAULT_READS = [
    "/api/state", "/api/presets", "/api/patches", "/api/setlists", "/api/foot-list", "/api/songs", "/api/effects",
    "/api/block-defaults", "/api/gestures", "/api/genres", "/api/tunings", "/api/standards", "/api/standards/state",
    "/api/standards/grooves/tree", "/api/grooves", "/api/kits", "/api/drumkits", "/api/sfz", "/api/dx7",
    "/api/vital/presets", "/api/sample-sets", "/api/loops", "/api/backing/catalog", "/api/backing/cache",
    "/api/pedals/catalog", "/api/mappings", "/api/pedalboard", "/api/soundcard", "/api/cards", "/api/inputmap",
    "/api/mixer", "/api/modes", "/api/engines", "/api/recorder", "/api/knobs/config", "/api/controllers",
    "/api/anim-packs", "/api/app-build", "/api/system", "/api/system/health", "/api/system/libraries", "/api/storage",
    "/api/song-folders", "/api/song-folders/songs", "/api/backups", "/api/backups/overview", "/api/tones-sync",
    "/api/library/lent", "/api/sandbox", "/api/perf", "/api/golemfm/quotas",
]
# JAMAIS dans un instantané, même expurgé : appairage, réseau, appareils, comptes, jetons, et ce qui pilote la machine
NEVER = re.compile(r"^/api/(auth|network|connect|integrations|golemfm/pair|t3k/auth|band/invite|devices|"
                   r"desktop|diag|system/update|system/reaper-update|system/reaper-license|song-folders/browse|"
                   r"meters|calibrate|ui/geometry|backup/|import|"
                   # la séparation : le nom de l'extrait choisi (un titre de l'utilisateur), des chemins saisis, l'indice
                   # d'une clé de service (docs/separation.md §1) — jamais dans une coquille
                   r"separation)")


# L'INSTANTANÉ D'USINE seulement (bridge jetable, ni extrait ni clé) : la page Separation n'est pas vide. `/api/devices` est le
# REGISTRE DU MATÉRIEL (claviers, modules, pas les appareils appairés) : sur le bridge jetable il ne connaît personne, et
# sans lui Gear ▸ Drums disait « No drum module known or connected » à côté d'un Nitro branché (2026-10-22). Restent hors de
# tout instantané : `browse` (des chemins du disque), les options d'une clé, et `programs` (ce que CETTE machine a
# installé — celle du développeur qui lance l'outil, pas un golem d'usine).
FACTORY_ALLOW = re.compile(r"^/api/(separation(/batch)?|devices)$")


def _never(read, factory=False):
    return bool(NEVER.match(read)) and not (factory and FACTORY_ALLOW.match(read.split("?")[0]))


def reads_for(base, listed=None):
    """La liste à parcourir : `listed`, sinon la liste par défaut + chaque preset, patch et chanson du rack."""
    if listed:
        return [r for r in listed if r.startswith("/api/")]
    out = list(DEFAULT_READS)
    # un patch se LIT comme un preset : /api/preset/patch:<id> (docs/patches.md)
    for path, key, tpl in (("/api/presets", "id", "/api/preset/%s"), ("/api/patches", "id", "/api/preset/patch:%s"),
                           ("/api/songs", "id", "/api/song/%s")):
        try:
            data = _get(base, path)
        except Exception:
            continue
        rows = data.get("songs") if isinstance(data, dict) and "songs" in data else (
            data.get("patches") if isinstance(data, dict) and "patches" in data else data)
        for x in rows if isinstance(rows, list) else []:
            if isinstance(x, dict) and x.get(key):
                out.append(tpl % urllib.parse.quote(str(x[key]), safe=":"))
                if tpl == "/api/song/%s":
                    out.append("/api/songs/%s/files" % urllib.parse.quote(str(x[key]), safe=""))
    return out


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=20) as r:
        return json.loads(r.read() or b"null")


# ── EXPURGER (docs/shell.md §3) ──────────────────────────────────────────────────────────────────
REDACTED = "<redacted>"
# des CLÉS dont la valeur ne sort jamais (comparées sans la casse, `-` et `_` ignorés). ⚠ Pas « key » seul : la
# tonalité d'un morceau s'appelle `key` (« Am »).
SECRET_KEYS = {"token", "accesstoken", "refreshtoken", "devicetoken", "secret", "clientsecret", "password", "passwd",
               "psk", "passphrase", "apikey", "publishablekey", "privatekey", "hint", "auth", "authorization", "cookie",
               "email", "mail", "owneremail", "ip", "ips", "ipv4", "ipv6", "addr", "address", "localaddress",
               "mac", "macaddress", "hostname", "host", "ssid", "bssid", "serial", "serialnumber", "issuedby"}
# des PERSONNES et des APPAREILS (trouvé à la première relecture, 2026-10-09 : `person_name: "le mainteneur"` dans l'état et la
# carte des entrées) : remplacés par un PSEUDONYME CONSTANT — la même personne garde le même alias d'un fichier à
# l'autre, l'écran reste cohérent (« Musician A joue GTR ») sans nommer personne.
# ⚠ SEULEMENT les champs du ROSTER (deuxième relecture, 2026-10-09) : `author` et `by` portent aussi des CRÉDITS
# publics (auteurs des logiciels libres, créateurs de captures) qu'un instantané doit garder, et « golem », « Whammy
# DT », le nom du groupe auraient été remplacés partout. Les vraies personnes se relèvent à leur source (collect_private).
PERSON_KEYS = {"personname", "person", "loadedby", "ownername", "username", "displayname", "membername"}
DEVICE_KEYS = {"devicename", "editor"}
# des CONTENEURS de personnes : leurs CLÉS et leurs valeurs texte sont des personnes (`persons: {"alex": {…}}` dans les
# réglages Rec d'un preset, `people: {"1": "alex"}` dans une prise, `people: [{id, name}]` au roster)
PERSON_CONTAINERS = {"persons", "people", "members", "roster"}
COLLECT_ONLY = ("/api/band",)                         # lues pour RELEVER les personnes, jamais écrites
_PSEUDO = {}
KNOWN = {}                                            # personne connue (minuscules) -> "Musician"/"Device"


def pseudo(value, kind="Musician"):
    """« le mainteneur » -> « Musician A » (toujours le même pour la même valeur)."""
    k = (kind, _fold(value))                           # « alex » (id), « le mainteneur », « Alex Martin » : la même personne
    if k not in _PSEUDO:
        n = sum(1 for (kk, _v) in _PSEUDO if kk == kind)
        _PSEUDO[k] = "%s %s" % (kind, chr(65 + n) if n < 26 else str(n + 1))
    return _PSEUDO[k]


def is_pseudo(v):
    return isinstance(v, str) and bool(re.fullmatch(r"(Musician|Device) ([A-Z]|\d+)", v))


RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
# IPv6 : 4 groupes au moins, ou une forme compressée « :: » — une HEURE « 02:45:05 » n'en est pas une (vu au 1er essai)
RE_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}(?![\w:])|(?<![\w:])(?:[0-9a-fA-F]{1,4}:){1,6}:(?:[0-9a-fA-F]{1,4})?(?![\w:.])")
RE_MAC = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
RE_SERIAL = re.compile(r"\bgolem_[1-9]\d*\b")
RE_LOCALHOST = re.compile(r"\b[A-Za-z0-9-]+\.local\b")
# les chemins ABSOLUS : sous le rack -> relatifs ; sous le dossier personnel -> « ~ » ; tout autre -> « <path> »
RE_ABS = re.compile(r"(?:(?<![\w/.~])/(?:home|media|mnt|run|Users|Volumes|tmp|opt|root|srv|var|data)/[^\s\"']*)|"
                    r"(?:\b[A-Za-z]:\\[^\s\"']*)")


RE_ABS_START = re.compile(r"^(?:/(?:home|media|mnt|run|Users|Volumes|tmp|opt|root|srv|var|data)/|[A-Za-z]:\\)")


def _norm_key(k):
    return re.sub(r"[-_\s]", "", str(k)).lower()


def _host_names():
    names = set()
    # des mots GÉNÉRIQUES ne sont pas des noms de machine : un poste dont le FQDN est « host.docker.internal »
    # (Docker Desktop) expurgeait le mot « host » partout — jusque dans « <host> » déjà posé et dans les clés
    generic = ("localhost", "127.0.0.1", "host", "internal", "local", "localdomain", "docker", "lan", "home")
    for n in (socket.gethostname(), socket.getfqdn()):
        for part in {n, n.split(".")[0]}:
            if part and part.lower() not in generic and len(part) > 2:
                names.add(part)
    return names


HOSTS = _host_names()


# LE DOSSIER PERSONNEL DE LA DÉMO (2026-11-04) : la page Separation de la démo montre les moteurs du mainteneur, leur
# commande comprise — son dossier personnel y devient celui d'un compte « golem », et ce chemin-là reste affiché tel quel
# (`separation_from`). C'est le SEUL chemin absolu qu'un instantané laisse passer.
DEMO_HOME = "/home/golem"


def _demo_path(p):
    return p == DEMO_HOME or p.startswith(DEMO_HOME + "/")


def redact_str(s):
    root, home = ROOT.rstrip("/\\"), os.path.expanduser("~").rstrip("/\\")

    def path(m):
        p = m.group(0)
        if _demo_path(p):
            return p
        if p == root or p.startswith(root + "/") or p.startswith(root + "\\"):
            return p[len(root):].lstrip("/\\").replace("\\", "/") or "."       # relatif au dépôt, en « / » partout
        if p == home or p.startswith(home + "/") or p.startswith(home + "\\"):
            return "~" + p[len(home):].replace("\\", "/")
        return "<path>"
    # une valeur qui COMMENCE par un chemin absolu est un chemin ENTIER, espaces comprises (« /media/alex/HD Save/… » :
    # coupé à l'espace, « Save/golem » restait) ; à l'intérieur d'une phrase, on coupe aux blancs
    m = RE_ABS_START.match(s)
    s = path(type("M", (), {"group": lambda self, i=0: s})()) if m else RE_ABS.sub(path, s)
    s = RE_EMAIL.sub("<email>", s)
    s = RE_MAC.sub("<mac>", s)
    s = RE_IPV4.sub("<ip>", s)
    s = RE_IPV6.sub("<ip>", s)
    s = RE_SERIAL.sub("golem_0", s)
    s = RE_LOCALHOST.sub("<host>", s)
    for h in HOSTS:
        s = re.sub(r"\b%s\b" % re.escape(h), "<host>", s, flags=re.I)
    return s


def _fold(v):
    """Comparaison sans casse ni accents : « Mârtin » et « Martin » sont le même nom."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(v)) if not unicodedata.combining(c)).strip().lower()


def remember(name, kind="Musician"):
    if isinstance(name, str) and len(name.strip()) > 1:
        KNOWN.setdefault(_fold(name), kind)


def collect_private(extra=()):
    """Les personnes privées qu'aucun champ ne désigne : l'utilisateur de la machine (nom complet), le nom git du dépôt,
    et `--private-name`."""
    import subprocess
    for n in extra or ():
        remember(n)
    try:
        import pwd
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
        remember(gecos)
    except Exception:
        pass
    try:
        remember(subprocess.run(["git", "-C", ROOT, "config", "user.name"], capture_output=True, text=True,
                                timeout=5).stdout.strip())
    except Exception:
        pass


def collect(x, key=None):
    """Premier temps : relever les personnes et appareils connus, dans TOUTES les lectures, avant d'expurger."""
    nk = _norm_key(key) if key is not None else None
    if nk in PERSON_KEYS | DEVICE_KEYS and isinstance(x, str) and x.strip():
        remember(x, "Device" if nk in DEVICE_KEYS else "Musician")
    if nk in PERSON_CONTAINERS and isinstance(x, dict) and x:
        # { personne: {fiche} } -> les CLÉS sont des personnes ; { n: "personne" } -> les VALEURS. Une FICHE ({id, name,
        # roles…}, valeurs mêlées) n'est PAS une liste de personnes : ses clés sont des noms de champs (troisième
        # relecture : « name », « id », « owner » relevés comme personnes auraient été remplacés partout)
        if all(isinstance(v, dict) for v in x.values()):
            for k in x:
                if isinstance(k, str) and not k.isdigit():
                    remember(k)
        elif all(isinstance(v, str) for v in x.values()):
            for v in x.values():
                remember(v)
    if nk in PERSON_CONTAINERS and isinstance(x, list):
        for v in x:
            if isinstance(v, dict):
                remember(v.get("id"))
                remember(v.get("name"))
            elif isinstance(v, str):
                remember(v)
    if isinstance(x, dict):
        for k, v in x.items():
            collect(v, k)
    elif isinstance(x, list):
        for v in x:
            collect(v, key if nk in PERSON_KEYS else None)   # pas le conteneur : une fiche n'en est pas un


def _known(v):
    return isinstance(v, str) and len(v.strip()) > 1 and _fold(v) in KNOWN


def _names_inside(s):
    """Un NOM COMPLET connu (deux mots ou plus) au milieu d'une phrase -> son pseudonyme. Un nom d'un seul mot n'est
    remplacé que s'il est TOUTE la valeur : « le mainteneur » ne doit pas toucher « graphic »."""
    for name, kind in KNOWN.items():
        if " " not in name:
            continue
        # repli CARACTÈRE PAR CARACTÈRE : les positions du texte replié sont celles du texte d'origine, on y remplace
        # (« chart by Alex Mârtin » contient « alex martin » — vu au test)
        folded = "".join((_fold(c) or c)[:1] if c.strip() else c for c in s)
        i = folded.find(name)
        while i >= 0:
            p = pseudo(name, kind)
            s = s[:i] + p + s[i + len(name):]
            folded = folded[:i] + p.lower() + folded[i + len(name):]
            i = folded.find(name, i + len(p))
    return s


def redact(x, key=None):
    """L'objet expurgé (une copie)."""
    if key is not None and _norm_key(key) in SECRET_KEYS and x not in (None, "", [], {}):
        return REDACTED
    if _known(x):                                     # une personne connue, où qu'elle soit
        return pseudo(x, KNOWN[_fold(x)])
    if key is not None and _norm_key(key) in PERSON_KEYS | DEVICE_KEYS:
        kind = "Device" if _norm_key(key) in DEVICE_KEYS else "Musician"
        if isinstance(x, str) and x:
            return pseudo(x, kind)
        if isinstance(x, list):
            return [pseudo(v, kind) if isinstance(v, str) else redact(v) for v in x]
    if isinstance(x, dict):
        return {(pseudo(k, KNOWN[_fold(k)]) if _known(k) else redact_str(k)) if isinstance(k, str) else k: redact(v, k)
                for k, v in x.items()}
    if isinstance(x, list):
        return [redact(v) for v in x]
    if isinstance(x, str):
        return _names_inside(redact_str(x))
    return x


# ── VÉRIFIER : il ne reste RIEN ──────────────────────────────────────────────────────────────────
def leaks(obj):
    """Ce qui reste d'identifiant après expurgation : [(motif, extrait)]. Vide = propre."""
    text = json.dumps(obj, ensure_ascii=False)
    out = []
    for name, rx in (("email", RE_EMAIL), ("ipv4", RE_IPV4), ("mac", RE_MAC), ("serial", RE_SERIAL),
                     ("host .local", RE_LOCALHOST), ("absolute path", RE_ABS)):
        for m in rx.finditer(text):
            if name == "absolute path" and _demo_path(m.group(0)):
                continue                                      # le dossier personnel de la démo (DEMO_HOME)
            out.append((name, m.group(0)[:60]))
    for h in HOSTS:
        if re.search(r"\b%s\b" % re.escape(h), text, flags=re.I):
            out.append(("hostname", h))

    def walk(x, key=None):
        if key is not None and _norm_key(key) in SECRET_KEYS and x not in (None, "", [], {}, REDACTED):
            out.append(("secret field", str(key)))
        if key is not None and _norm_key(key) in PERSON_KEYS | DEVICE_KEYS and isinstance(x, str) and x and not is_pseudo(x):
            out.append(("person or device name", str(key)))
        if _known(x):
            out.append(("known person", str(x)))
        if isinstance(x, str):
            out.extend(("known full name", n) for n in KNOWN if " " in n and n in _fold(x))
        if isinstance(x, dict):
            out.extend(("known person (key)", k) for k in x if _known(k))
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return out


def out_path(out_dir, read):
    """`/api/song/rs:abc?x=1` -> `<out>/api/song/rs%3Aabc__x%3D1.json` : chaque segment encodé (pas de « : » sous Windows)."""
    u = urllib.parse.urlsplit(read)
    segs = [urllib.parse.quote(urllib.parse.unquote(s), safe="") for s in u.path.strip("/").split("/")]
    name = segs[-1] + ("__" + urllib.parse.quote(u.query, safe="") if u.query else "")
    return os.path.join(out_dir, *segs[:-1], name + ".json")


def snapshot(base, out_dir, listed=None, log=print, private=(), factory=False):
    """Parcourt, expurge, VÉRIFIE, écrit. Rend {written, skipped, refused, failed}."""
    res = {"written": [], "skipped": [], "refused": [], "failed": []}
    got = {}
    collect_private(private)
    for read in COLLECT_ONLY:                                 # le roster : relevé, jamais écrit
        try:
            collect(_get(base, read))
        except Exception:
            pass
    files = set()
    for read in dict.fromkeys(reads_for(base, listed)):       # 1er temps : tout lire, relever les personnes
        if out_path(out_dir, read) in files:                  # « rs:abc » et « rs%3Aabc » : la même lecture
            continue
        files.add(out_path(out_dir, read))
        if _never(read, factory):
            res["skipped"].append(read)
            continue
        try:
            got[read] = _get(base, read)
        except ValueError:
            # pas du JSON : une IMAGE (la pochette d'un morceau, `/api/backing/asset/…/cover`) — l'app la charge par
            # <img src>, hors de fetch : golem.fm la sert sur une vraie route. Images seulement, jamais un autre binaire.
            try:
                with urllib.request.urlopen(base + read, timeout=20) as r:
                    ctype, body = r.headers.get_content_type(), r.read()
            except Exception as e:
                res["failed"].append((read, str(e)[:80]))
                continue
            if not ctype.startswith("image/"):
                res["failed"].append((read, "not JSON, not an image: " + ctype))
                continue
            p = out_path(os.path.join(out_dir, "assets"), read)[:-len(".json")]
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(body)
            res.setdefault("assets", {})[read] = {"file": os.path.relpath(p, out_dir), "type": ctype}
            continue
        except Exception as e:
            res["failed"].append((read, str(e)[:80]))
            continue
        collect(got[read])
    for read, data in got.items():                            # 2e temps : expurger, vérifier, écrire
        clean = redact(data)
        bad = leaks(clean)
        if bad:
            res["refused"].append((read, bad[:3]))
            log("✗ %s — NOT written, a trace is left: %s" % (read, bad[:3]))
            continue
        p = out_path(out_dir, read)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=1)
        res["written"].append(read)
    return res


# ── L'INSTANTANÉ D'USINE (docs/shell.md §3 bis) ──────────────────────────────────────────────────
# La doc des musiciens sur golem.fm montre l'écran du rack chargé du contenu d'USINE, celui que tous les golems ont :
# un bridge JETABLE sur un worktree (tools/check-ui.py : contenu d'usine seul, ni personne ni appareil), Chrome
# headless sur chaque page, et le relevé de chaque lecture GET que l'app fait VRAIMENT — page par page. Le relevé
# observé vaut mieux qu'un grep : il ne confond pas une lecture et une écriture, et il voit les adresses construites.

def _check_ui():
    """tools/check-ui.py (nom à tiret) : son bridge jetable et sa liste de pages."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_ui", os.path.join(ROOT, "tools", "check-ui.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _materialize():
    """tools/check-rig-materialize.py : son REAPER isolé (audio factice, ressources à lui, ports OSC du bridge)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_rig", os.path.join(ROOT, "tools", "check-rig-materialize.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Engine:
    """UN GOLEM QUI JOUE (décision de 2026-10-22) : le bridge jetable reçoit son propre REAPER, comme
    tools/check-rig-materialize.py — audio factice, dossier de ressources à lui, les ports OSC du bridge. Sans lui,
    Health disait « REAPER not answering » avec un incident ouvert, et Loop Station n'avait pas de boucles. Le REAPER
    du rack d'à côté n'est jamais touché : on arrête CE processus par son PID, jamais par motif."""

    def __init__(self, br, log, boot=300):
        self.br, self.log, self.boot, self.proc, self._logf = br, log, boot, None, None

    def __enter__(self):
        import subprocess
        import time
        from pathlib import Path
        rm = self.rm = _materialize()
        env, root = self.br.env, Path(self.br.root)
        resource = Path(env["GOLEM_REAPER_RESOURCE_DIR"])
        reaper = rm.reaper_binary().resolve()
        rm.prepare_reaper(root, resource, env, int(env["GOLEM_OSC_SEND"]), int(env["GOLEM_OSC_RECV"]), self.log, reaper)
        if sys.platform.startswith("linux"):
            # « Dummy Audio » ([audioconfig] mode=4) est une clé WINDOWS : sous Linux, ce REAPER n'avait aucun périphérique,
            # son thread audio ne tournait pas, l'horloge figeait et Health concluait « sound card lost? ». Le PCM `null`
            # d'ALSA est un VRAI périphérique muet : le moteur tourne, rien ne sort, la carte du rack d'à côté reste libre.
            ini = resource / "reaper.ini"
            text = ini.read_text(encoding="latin-1")
            keys = {"linux_audio_mode": "1", "alsa_indev": "null", "alsa_outdev": "null", "linux_audio_srate": "48000",
                    "linux_audio_bsize": "256", "linux_audio_bufs": "3", "linux_audio_nch_in": "2", "linux_audio_nch_out": "2"}
            text = re.sub(r"^(?:%s)=.*\n" % "|".join(keys), "", text, flags=re.M)
            text = text.replace("[reaper]\n", "[reaper]\n" + "".join("%s=%s\n" % kv for kv in keys.items()), 1)
            ini.write_text(text, encoding="latin-1")
        self._logf = open(os.path.join(os.path.dirname(str(resource)), "reaper.log"), "w", encoding="utf-8")
        self.proc = subprocess.Popen([str(reaper), "-newinst", "-nosplash", "-cfgfile", str(resource / "reaper.ini"), "-new"],
                                     env={**os.environ, "GOLEM_RUNTIME_DIR": env["GOLEM_RUNTIME_DIR"]},
                                     stdout=self._logf, stderr=subprocess.STDOUT)
        base = "http://127.0.0.1:%s" % env["GOLEM_PORT"]
        deadline = time.monotonic() + self.boot
        while not _get(base, "/api/state").get("reaper_connected"):
            if self.proc.poll() is not None:
                raise RuntimeError("REAPER exited with %s" % self.proc.returncode)
            if time.monotonic() > deadline:
                raise RuntimeError("REAPER never spoke to the disposable bridge in %d s" % self.boot)
            time.sleep(0.5)
        rm.wait_rig(base, root / "presets", 60)                  # le bridge rappelle son premier preset : on le laisse finir
        # un golem neuf qui DÉMARRE pour de bon ouvre la vérification de première installation à la place de /live : les
        # exemples montrent un golem qui joue — son musicien l'a passée (« Skip for now »). Les exemples ?boot=firstcheck
        # gardent leur démo intégrée, qui ne lit pas cet état.
        _post(base, "/api/health/first-check", {"action": "skip"})
        self.log("engine: REAPER %d connected to the disposable bridge (dummy audio)" % self.proc.pid)
        return self

    def __exit__(self, *exc):
        self.rm.kill(self.proc)
        if self._logf:
            self._logf.close()


def _page_url(base, target, ro):
    """Les TROIS formes de route d'un exemple, comme la coquille de golem.fm les ouvre (2026-10-22) : `#/live` (l'app
    du rack), `?boot=firstcheck&at=input[#/…]` (une démo de l'app ouverte par sa query) et `/app/m.html?tab=now` (le
    Companion du téléphone). `shell=ro` est ajouté à la query — l'écran tel que la doc le montre."""
    if target.startswith("#"):
        return base + ("/app/?shell=ro" if ro else "/app/") + target
    if target.startswith("?"):
        q, _, frag = target[1:].partition("#")
        return base + "/app/?" + q + ("&shell=ro" if ro else "") + ("#" + frag if frag else "")
    if ro and target.startswith("/app/m.html"):
        return base + target + ("&" if "?" in target else "?") + "shell=ro"
    return base + target


def factory_pages(base, cu):
    """Les pages à parcourir : celles de check-ui, plus l'intérieur de chaque chanson, setlist et ligne d'usine."""
    rack = [p for p in cu.RACK_PAGES if p.startswith("#")]
    q = lambda s: urllib.parse.quote(str(s), safe="")  # noqa: E731
    try:
        songs = _get(base, "/api/songs")
        for s in (songs.get("songs") if isinstance(songs, dict) else songs) or []:
            if isinstance(s, dict) and s.get("id"):
                rack.append("#/songs/songs/" + q(s["id"]))
    except Exception:
        pass
    try:
        sl = _get(base, "/api/setlists")
        for s in (sl.get("setlists") if isinstance(sl, dict) else sl) or []:
            if not (isinstance(s, dict) and s.get("id")):
                continue
            rack.append("#/songs/setlists/" + q(s["id"]))
            for ln in (s.get("lines") or [])[:2]:            # deux lignes suffisent : la page est la même
                if isinstance(ln, dict) and ln.get("id"):
                    rack.append("#/songs/setlists/%s/%s" % (s["id"], ln["id"]))      # brut, comme go()
    except Exception:
        pass
    return rack, list(cu.PHONE_PAGES)


# DES LECTURES FAITES EN POST (le corps porte le preset TEL QU'IL EST dans le Designer, brouillon compris) : pures, vérifiées
# dans le code (2026-10-21). La coquille de golem.fm jette toute écriture et répond {ok: true} : sans leur réponse, le
# Designer perdait EN SILENCE l'état des blocs (captures à télécharger) et le tiroir Backing. Le relevé les laisse passer
# sur le bridge jetable et garde leur réponse, servie sous la clé « POST /api/… » (shell.js la connaît).
POST_READS = ("/api/blocks/status", "/api/backing/drawer")

_ANCHORS_JS = "() => [...new Set([...document.querySelectorAll('[data-doc]')].map(e => e.getAttribute('data-doc')))].sort()"
# les ancres présentes mais SANS TAILLE (cachées par ?shell=ro, comme la barre d'outils de /live) : on peut les cliquer,
# jamais les entourer d'un halo — un halo sur un élément invisible ne se voit pas
_HIDDEN_JS = ("() => [...new Set([...document.querySelectorAll('[data-doc]')].filter(e => !(e.offsetWidth || e.offsetHeight"
              " || e.getClientRects().length)).map(e => e.getAttribute('data-doc')))].sort()")


def crawl(base, rack_pages, phone_pages, settle_ms=1500, log=print, shot=None, click=None, anchors=None, boot_skip=None,
          ro=False, hidden=None, posts=None):
    """Ouvre chaque page, relève ses lectures GET /api/… (chemin + requête). Les écritures sont INTERCEPTÉES (règle 3
    du CLAUDE.md) même sur un bridge jetable : le relevé ne doit pas dépendre d'un geste qui aurait changé l'état."""
    from playwright.sync_api import sync_playwright
    by_page = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        for size, pages in (((1024, 600), rack_pages), ((390, 844), phone_pages)):
            for target in pages:
                seen = []

                wrote = []

                def guard(route, _request=None, seen=seen, wrote=wrote):
                    r = route.request
                    if r.method != "GET":
                        path = urllib.parse.urlsplit(r.url).path
                        wrote.append(r.method + " " + path)
                        if path in POST_READS:                   # une lecture en POST : elle passe, sa réponse est gardée
                            return route.continue_()
                        return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
                    u = urllib.parse.urlsplit(r.url)
                    seen.append(u.path + ("?" + u.query if u.query else ""))
                    return route.continue_()
                page = browser.new_page(viewport={"width": size[0], "height": size[1]})
                answers = {}
                status_seen = []
                page.on("response", lambda r, s=status_seen: s.append(1)
                        if urllib.parse.urlsplit(r.url).path == "/api/blocks/status" else None)

                def keep(resp, answers=answers):
                    path = urllib.parse.urlsplit(resp.url).path
                    if resp.request.method == "POST" and path in POST_READS:
                        try:
                            answers["POST " + path] = resp.json()
                        except Exception:
                            pass
                if posts is not None:
                    page.on("response", keep)
                if boot_skip:                                    # « Open the app anyway » : l'écran /loading passé
                    page.add_init_script("try { sessionStorage.setItem('golemBootSkip', '%s'); } catch (e) {}" % boot_skip)
                page.route("**/api/**", guard)
                try:
                    # ro : l'écran tel que golem.fm le montre (?shell=ro) — ce qui y est caché se mesure à part
                    page.goto(_page_url(base, target, ro), wait_until="domcontentloaded")
                    page.wait_for_timeout(settle_ms)
                    # LE DESIGNER sait quels blocs manquent 350 ms après son rendu (POST /api/blocks/status) : un tap
                    # parti avant ouvre le tiroir ordinaire au lieu de la fiche « capture manquante », un relevé fait
                    # avant ne voit pas le bandeau — sur un banc chargé, settle_ms ne suffit pas (2026-11-04 : ancres
                    # designer.block-status et designer.missing perdues)
                    if "#/designer" in target:
                        for _ in range(80):
                            if status_seen:
                                break
                            page.wait_for_timeout(100)
                        page.wait_for_timeout(300)
                    seen_anchors = set(page.evaluate(_ANCHORS_JS)) if anchors is not None else set()
                    seen_hidden = set(page.evaluate(_HIDDEN_JS)) if hidden is not None else set()
                    # ouvrir un tiroir comme le fera golem.fm : un clic sur chaque ancre de la séquence « a > b ». Les
                    # ancres comptées = celles du chargement ET celles qui n'existent qu'après un clic (le panneau ouvert)
                    for step in [c.strip() for c in (click or "").split(">") if c.strip()]:
                        page.wait_for_selector('[data-doc="%s"]' % step, state="attached", timeout=6000)
                        page.evaluate("(a) => document.querySelector('[data-doc=\"' + a + '\"]').click()", step)
                        page.wait_for_timeout(settle_ms)
                        if anchors is not None:
                            seen_anchors |= set(page.evaluate(_ANCHORS_JS))
                        if hidden is not None:
                            seen_hidden |= set(page.evaluate(_HIDDEN_JS))
                    if anchors is not None:                      # les ancres data-doc RENDUES (docs/user-docs.md §4)
                        anchors[target] = sorted(seen_anchors)
                    if hidden is not None:
                        hidden[target] = sorted(seen_hidden)
                    if shot:                                     # pour la relecture humaine, jamais publié
                        page.screenshot(path=shot)
                except Exception as e:
                    log("  ! %s: %s" % (target, str(e)[:80]))
                try:
                    page.close()
                except Exception:
                    pass
                by_page[target] = sorted(set(seen))
                if posts is not None:
                    # ce que la page ÉCRIT sans qu'on ait rien touché (chargement + clics de l'exemple) ; une écriture
                    # au chargement qui n'est pas une lecture en POST est un bug de la page
                    posts[target] = {"sent": sorted(set(wrote)), "answers": answers}
                log("  %-48s %3d reads" % (target, len(by_page[target])))
        browser.close()
    return by_page


# des lectures qui décrivent la MACHINE qui fabrique l'instantané (carte son branchée, contrôleurs USB, CPU, disque,
# REAPER) et pas le contenu d'usine : écrites quand même (l'écran a besoin d'une réponse), mais DÉCLARÉES dans
# SNAPSHOT.json (`machine`) — golem.fm sait qu'elles montrent le poste du développeur, pas « tous les golems ».
MACHINE = re.compile(r"^/api/(cards|soundcard|controllers|inputmap|card-setups|system|system/health|system/libraries|"
                     r"storage|engines|audio-buffer|state|backups|backups/overview|pedalboard|devices)(\?|$)")

# LE RACK DE RÉFÉRENCE (2026-10-21) : le matériel que la doc montre dans les pages Gear — et que les lectures
# `machine` décrivent. L'instantané se fabrique SUR ce matériel ; l'outil VÉRIFIE ce qui est branché (lu dans les
# réponses du bridge jetable, pas déclaré) et l'écrit dans SNAPSHOT.json `rack` : golem.fm ne sert les lectures
# `machine` que si `rack.complete`. Un nom = une sous-chaîne cherchée (sans la casse) dans /api/cards et /api/controllers.
REFERENCE_RACK = {
    "card": "Volt 276",                    # carte son, 2 entrées
    "pedalboard": "fcb1010",               # pédalier, puce UnO2 — reconnu par la sonde d'identité
    # DEUX VARIANTES (2026-10-21) : le poste n'a pas assez de ports USB pour la batterie ET le clavier. Un
    # instantané par variante, au même commit : `factory` (drums) et `factory-keys` (keys) ; les pages claviers et
    # Controllers lisent le second.
    "variants": {"drums": ["Nitro"],       # batterie électronique Alesis Nitro
                 "keys": ["MPK Mini"]},    # clavier et pads Akai MPK Mini Mk II
}


# LE NOM de l'instantané, écrit dans SNAPSHOT.json (golem.fm le LIT, il ne le déduit pas du dossier) : les pages de doc
# citent `snapshot="factory"` — la variante drums garde ce nom, quoi qu'il arrive à la liste des variantes.
SNAPSHOT_NAMES = {"drums": "factory", "keys": "factory-keys"}

# le bridge du rack de référence, celui de la machine où l'instantané se fabrique : il sonde le pédalier
REFERENCE_URL = "http://localhost:8770"


def rack_check(base, reference=REFERENCE_URL):
    """Ce que le bridge jetable VOIT du rack de référence : {reference, seen, missing, complete}.

    Le pédalier n'a pas de nom USB (il passe par la prise MIDI de la carte) : il se reconnaît par la SONDE
    D'IDENTITÉ de la puce UnO2 — le geste « Detect » de Settings ▸ Gear ▸ Pedalboard, rejoué sur le bridge DU RACK
    (`reference`) : un banc jetable ne touche pas au MIDI de la machine (GOLEM_NO_HW_MIDI, 2026-10-27) et sa sonde
    rend toujours « rien » — l'instantané se disait incomplet, FCB allumé (2026-11-04).
    Une requête SysEx, aucune note : elle ne joue rien (CLAUDE.md, « une sonde ne lance jamais une prise »)."""
    blob = ""
    try:
        pb = _post(reference, "/api/pedalboard/detect", {})
        if pb.get("probed"):
            blob += json.dumps(pb.get("active") or {}, ensure_ascii=False).lower()
    except Exception:
        pass
    for read in ("/api/cards", "/api/controllers", "/api/soundcard"):
        try:
            blob += json.dumps(_get(base, read), ensure_ascii=False).lower()
        except Exception:
            pass
    base_want = [REFERENCE_RACK["card"], REFERENCE_RACK["pedalboard"]]
    every = base_want + [w for v in REFERENCE_RACK["variants"].values() for w in v]
    seen = [w for w in every if w.lower() in blob]
    variant = next((k for k, v in REFERENCE_RACK["variants"].items() if all(w in seen for w in v)), None)
    want = base_want + (REFERENCE_RACK["variants"][variant] if variant else [])
    return {"reference": REFERENCE_RACK, "variant": variant, "seen": seen,
            "missing": [w for w in base_want if w not in seen] + ([] if variant else ["a variant: " + " or ".join(
                "+".join(v) for v in REFERENCE_RACK["variants"].values())]),
            "complete": bool(variant) and all(w in seen for w in want)}


# des lectures que l'app fait SANS cesse ou qui ne disent rien d'un écran figé : pas dans un instantané
VOLATILE = re.compile(r"^/api/(health$|app-build|meters|tuner|perf/|clock)")


# LES EXEMPLES de la doc : un geste de musicien REJOUÉ sur le bridge jetable (une ligne de la setlist d'usine, une
# scène), puis l'état et les lectures de la page relevés tels quels. golem.fm les sert par-dessus l'instantané
# (`<GolemScreen snapshot="factory" example="…">`) : `state` = la forme de state.snapshot() (le WebSocket), `reads` =
# les seules lectures qui DIFFÈRENT de l'instantané de base (le brouillon du Designer, la fiche du preset chargé…).
# `line` = le titre d'une ligne de la setlist d'usine active (« Factory Golem ») ; `preset` = un preset hors setlist ;
# `click` = des ancres data-doc touchées après le chargement, en séquence « a > b » (un tiroir ouvert), comme golem.fm
# le fera dans l'iframe — par element.click(), qui marche aussi sur un bouton caché en ?shell=ro ;
# `gestures` = d'autres gestes du musicien, rejoués AVANT (POST [chemin, corps]) — régler la vue de /live d'un mode,
# basculer de mode ; `undo` = ce qui remet le bridge jetable comme avant, pour que l'exemple suivant parte du même état.
_LINE = "#/songs/setlists/factory/r:factory:8"           # l'app met l'id de ligne BRUT dans l'adresse (go())
_SONG = "#/songs/songs/" + urllib.parse.quote("rs:f3f0252689f96910f01c81be0325855f", safe="")
EXAMPLES = [
    {"name": "golem-rising-live", "title": "Golem Rising, scene B, on the Live screen",
     "line": "Golem Rising", "scene": "B", "route": "#/live"},
    {"name": "golem-rising-designer", "title": "Golem Rising in the Designer",
     "line": "Golem Rising", "scene": "B", "route": "#/designer"},
    {"name": "golem-rising-amp-sheet", "title": "Golem Rising: the Peavey amp, its capture not downloaded yet",
     "line": "Golem Rising", "scene": "B", "route": "#/designer", "click": "designer.block:peavey"},
    {"name": "golem-rising-delay-sheet", "title": "Golem Rising: the Tempo Delay's drawer, opened by a tap",
     "line": "Golem Rising", "scene": "B", "route": "#/designer", "click": "designer.block:dly"},
    {"name": "golem-rising-scenes-sheet", "title": "Golem Rising: Scenes & sounds, what each lane plays in each scene",
     "line": "Golem Rising", "scene": "B", "route": "#/designer", "click": "designer.menu > designer.menu.scenes"},
    {"name": "golem-rising-scene-sheet", "title": "Golem Rising: scene B's sheet (name, level)",
     "line": "Golem Rising", "scene": "B", "route": "#/designer", "click": "designer.scene-name"},
    {"name": "golem-rising-keys", "title": "Golem Rising: the piano lane, played from the MPK Mini",
     "line": "Golem Rising", "scene": "B", "route": "#/designer/keys-1", "rack": "keys"},
    {"name": "reference-controllers", "title": "Settings ▸ Gear ▸ Controllers with the MPK Mini plugged",
     "line": "Golem Rising", "scene": "B", "route": "#/system/gear/controllers", "rack": "keys"},
    # un bloc PRÊT : sur un golem d'usine, toucher l'ampli ouvre la feuille « capture à télécharger », pas son tiroir
    {"name": "golem-rising-delay-presets", "title": "Golem Rising: the Tempo Delay's drawer, Presets tab",
     "line": "Golem Rising", "scene": "B", "route": "#/designer", "click": "designer.block:dly > designer.sheet.presets"},
    {"name": "golem-rising-delay-assign", "title": "Golem Rising: the Tempo Delay's drawer, MIDI assign tab",
     "line": "Golem Rising", "scene": "B", "route": "#/designer", "click": "designer.block:dly > designer.sheet.assign"},
    {"name": "factory-patches", "title": "Songs ▸ Patches: the factory patches",
     "line": "Golem Rising", "scene": "B", "route": "#/songs/patches"},
    {"name": "library-amps", "title": "Library ▸ Tones ▸ Amps",
     "line": "Golem Rising", "scene": "B", "route": "#/library/tones/amps"},
    {"name": "settings-mode", "title": "Settings ▸ Mode: the five factory modes, Home selected",
     "line": "Golem Rising", "scene": "B", "route": "#/system/mode"},
    {"name": "reference-soundcard", "title": "Settings ▸ Gear ▸ Soundcard on the reference rack (Volt 276)",
     "line": "Golem Rising", "scene": "B", "route": "#/system/gear/sound"},
    {"name": "reference-pedalboard", "title": "Settings ▸ Gear ▸ Pedalboard: the FCB1010 with its UnO2 chip",
     "line": "Golem Rising", "scene": "B", "route": "#/system/gear/board"},
    {"name": "reference-drums", "title": "Settings ▸ Gear ▸ Drums with the Alesis Nitro plugged",
     "line": "Golem Rising", "scene": "B", "route": "#/system/gear/drums", "rack": "drums"},
    {"name": "settings-mode-compare", "title": "Settings ▸ Mode ▸ every mode side by side",
     "line": "Golem Rising", "scene": "B", "route": "#/system/mode/compare"},
    {"name": "factory-songs", "title": "Songs ▸ Songs: the factory song",
     "line": "Golem Rising", "scene": "B", "route": "#/songs/songs"},
    {"name": "factory-content", "title": "Settings ▸ Content ▸ Factory: what every golem ships with",
     "line": "Golem Rising", "scene": "B", "route": "#/system/content/factory"},
    {"name": "metal-for-all-designer", "title": "Metal for all: six lanes, scene Verse",
     "preset": "factory-metal-for-all", "scene": "B", "route": "#/designer"},
    {"name": "blues-night-live", "title": "Rented Room Blues, organ solo",
     "line": "Rented Room Blues", "scene": "C", "route": "#/live"},
    {"name": "factory-setlist", "title": "The Factory Golem setlist, Rooftop Prowl loaded",
     "line": "Rooftop Prowl", "scene": "A", "route": "#/songs/setlists/factory"},
    {"name": "factory-setlist-line", "title": "The Golem Rising line of the Factory Golem setlist",
     "line": "Golem Rising", "scene": "A", "route": _LINE},
    {"name": "golem-rising-song", "title": "The Golem Rising song page",
     "line": "Golem Rising", "scene": "A", "route": _SONG},
    {"name": "golem-rising-config", "title": "Golem Rising's ⚙ lane: Click, Rec, Riff, players, arrangement",
     "line": "Golem Rising", "scene": "A", "route": "#/designer/config"},
    {"name": "metal-for-all-drums", "title": "Metal for all: the drum lane",
     "preset": "factory-metal-for-all", "scene": "B", "route": "#/designer/drums-1"},
    {"name": "loop-station-live", "title": "Loop Station on the Live screen: the looper on the foot",
     "preset": "factory-loop-station", "scene": "A", "route": "#/live"},
    {"name": "golem-rising-mixer", "title": "Golem Rising: the Live mixer",
     "line": "Golem Rising", "scene": "B", "route": "#/live", "click": "live.tool.mixer"},
    {"name": "golem-rising-assign", "title": "Golem Rising: ✎ Assign, the pedalboard editor",
     "line": "Golem Rising", "scene": "B", "route": "#/live", "click": "live.tool.assign"},
    {"name": "golem-rising-rehearsal", "title": "Golem Rising on the Rehearsal page (Rehearsal mode)",
     "line": "Golem Rising", "scene": "A", "route": "#/live",
     "gestures": [["/api/mode/update", {"id": "rehearsal", "live_view": "rehearsal"}], ["/api/mode", {"id": "rehearsal"}]],
     "undo": [["/api/mode", {"id": "studio"}]]},
    {"name": "golem-rising-concert", "title": "Golem Rising on the Concert page (Gig mode)",
     "line": "Golem Rising", "scene": "A", "route": "#/live",
     "gestures": [["/api/mode/update", {"id": "gig", "live_view": "concert"}], ["/api/mode", {"id": "gig"}]],
     "undo": [["/api/mode", {"id": "studio"}]]},
    # pages modes, setlists, songs, arrangement, captures, factory (2026-10-22) — un tap local, jamais une écriture
    {"name": "settings-mode-gig", "title": "Settings ▸ Mode: the Gig mode's sheet (locked, Concert page)",
     "line": "Golem Rising", "scene": "B", "route": "#/system/mode", "click": "mode.item:gig"},
    {"name": "factory-setlists", "title": "Songs ▸ Banks & Setlists: the factory lists",
     "line": "Rooftop Prowl", "scene": "A", "route": "#/songs/setlists"},
    {"name": "factory-setlist-banks", "title": "The Factory Golem setlist laid out on the pedalboard (⇅ Banks)",
     "line": "Rooftop Prowl", "scene": "A", "route": "#/songs/setlists/factory", "click": "setlists.banks"},
    {"name": "golem-rising-songs-picker", "title": "Live: the songs of the setlist on the foot — a tap on the song's title",
     "line": "Golem Rising", "scene": "B", "route": "#/live", "click": "live.song"},
    {"name": "golem-rising-setlist-picker", "title": "Live: what the pedalboard plays — choosing the list on the foot",
     "line": "Golem Rising", "scene": "B", "route": "#/live", "click": "live.setlist"},
    {"name": "golem-rising-part-sheet", "title": "The Golem Rising song page: the first Chorus opened",
     "line": "Golem Rising", "scene": "A", "route": _SONG, "click": "arr.part.4"},
    {"name": "golem-rising-rehearsal-chorus", "title": "Golem Rising on the Rehearsal page, ready to start from the Chorus",
     "line": "Golem Rising", "scene": "A", "route": "#/live", "click": "live.section.4",
     "gestures": [["/api/mode/update", {"id": "rehearsal", "live_view": "rehearsal"}], ["/api/mode", {"id": "rehearsal"}]],
     "undo": [["/api/mode", {"id": "studio"}]]},
    {"name": "library-amp-detail", "title": "Library ▸ Tones ▸ Amps: the Peavey 6505 — no capture on this rack yet",
     "line": "Golem Rising", "scene": "B", "route": "#/library/tones/amps", "click": "tones.amp:peavey-6505"},
    # les pages golem restantes (2026-10-22) : Settings, Library, Connect — l'écran d'un golem neuf qui joue
    {"name": "factory-health", "title": "Settings ▸ System ▸ Health on a new golem",
     "line": "Golem Rising", "scene": "B", "route": "#/system/sys/health"},
    {"name": "factory-storage", "title": "Settings ▸ Content ▸ Storage on a new golem",
     "line": "Golem Rising", "scene": "B", "route": "#/system/content/storage"},
    {"name": "factory-backups", "title": "Settings ▸ Content ▸ Storage: the backups (⇅ Back up…)",
     "line": "Golem Rising", "scene": "B", "route": "#/system/content/storage", "click": "storage.backup"},
    {"name": "factory-standards", "title": "Library ▸ Tracks ▸ Standards: the three factory standards",
     "line": "Rooftop Prowl", "scene": "A", "route": "#/library/tracks/standards"},
    {"name": "standard-rooftop-prowl", "title": "Library ▸ Tracks ▸ Standards: Rooftop Prowl's chart",
     "line": "Rooftop Prowl", "scene": "A", "route": "#/library/tracks/standards", "click": "standards.card:rooftop-prowl"},
    {"name": "library-keys", "title": "Library ▸ Keys ▸ Instruments: the rack's piano, e-piano and organ",
     "line": "Golem Rising", "scene": "B", "route": "#/library/keys/instruments"},
    {"name": "library-grooves", "title": "Library ▸ Drums ▸ Grooves: the 26 factory grooves",
     "line": "Golem Rising", "scene": "B", "route": "#/library/drums/grooves"},
    {"name": "library-kits", "title": "Library ▸ Drums ▸ Kits: the factory pad kits",
     "line": "Golem Rising", "scene": "B", "route": "#/library/drums/kits"},
    {"name": "library-samples", "title": "Library ▸ Samples ▸ Short: one-shots by type",
     "line": "Golem Rising", "scene": "B", "route": "#/library/samples/short"},
    {"name": "library-backings", "title": "Library ▸ Tracks ▸ Backings on a golem not paired with golem.fm",
     "line": "Golem Rising", "scene": "B", "route": "#/library/tracks/backing"},
    {"name": "library-vocals", "title": "Library ▸ Tracks ▸ Vocals",
     "line": "Golem Rising", "scene": "B", "route": "#/library/tracks/vocals"},
    {"name": "library-recordings", "title": "Library ▸ Tracks ▸ Recordings on a new golem",
     "line": "Golem Rising", "scene": "B", "route": "#/library/tracks/recordings"},
    {"name": "connect-tone3000", "title": "Settings ▸ Connect ▸ TONE3000, not connected yet",
     "line": "Golem Rising", "scene": "B", "route": "#/system/connect/tone3000"},
    {"name": "connect-golemfm", "title": "Settings ▸ Connect ▸ golem.fm, not paired yet",
     "line": "Golem Rising", "scene": "B", "route": "#/system/connect/golemfm"},
    {"name": "connect-devices", "title": "Settings ▸ Connect ▸ Devices: guests and rack screens",
     "line": "Golem Rising", "scene": "B", "route": "#/system/connect/devices"},
    {"name": "engines-separation", "title": "Settings ▸ Engines ▸ Separation on a new golem",
     "line": "Golem Rising", "scene": "B", "route": "#/system/engines/separation"},
    {"name": "golem-rising-riff", "title": "Golem Rising's ⚙ lane: the Riff block's drawer",
     "line": "Golem Rising", "scene": "A", "route": "#/designer/config", "click": "designer.block:compo-global"},
    # la vérification de première installation (sa démo intégrée, ?boot=firstcheck) et le Companion du téléphone
    {"name": "first-check", "title": "The first-install check, before it starts",
     "line": "Golem Rising", "scene": "A", "route": "?boot=firstcheck"},
    {"name": "first-check-input", "title": "The first-install check: guitar in",
     "line": "Golem Rising", "scene": "A", "route": "?boot=firstcheck&at=input"},
    {"name": "first-check-done", "title": "The first-install check: its verdict",
     "line": "Golem Rising", "scene": "A", "route": "?boot=firstcheck&at=done"},
    {"name": "companion-now", "title": "The phone Companion: Now, during Golem Rising",
     "line": "Golem Rising", "scene": "B", "route": "/app/m.html?tab=now"},
    {"name": "companion-song", "title": "The phone Companion: the song",
     "line": "Golem Rising", "scene": "B", "route": "/app/m.html?tab=song"},
    {"name": "companion-rec", "title": "The phone Companion: Rec",
     "line": "Golem Rising", "scene": "B", "route": "/app/m.html?tab=rec"},
    # EN DERNIER : le Nitro devient « drums » (le geste « This is a drum module »), et rien ne le défait derrière
    {"name": "reference-drums-bound", "title": "Settings ▸ Gear ▸ Drums: the Alesis Nitro bound as drums, ready to measure",
     "line": "Golem Rising", "scene": "B", "route": "#/system/gear/drums", "rack": "drums",
     "gestures": [["/api/soundcard/usb", {"port": 1, "enabled": True, "roles": ["drums"]}]]},
]


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"null")


def make_example(base, ex, base_reads, settle_ms, log, out_dir):
    """Rejoue l'exemple, visite sa page, rend {name, title, route, state, reads}. Bridge JETABLE seulement : ces
    écritures (recall, sandbox_apply) changent l'état d'un rack — jamais contre un vrai bridge."""
    pid, slot = ex.get("preset"), None
    if ex.get("line"):
        sl = _get(base, "/api/setlists")
        act = next(s for s in (sl.get("setlists") if isinstance(sl, dict) else sl) if s.get("active"))
        slot = next(i for i, ln in enumerate(act["lines"]) if ln.get("title") == ex["line"])
        pid = act["lines"][slot]["preset"]
    for path, body in ex.get("gestures") or []:
        _post(base, path, body)
    doc = _get(base, "/api/preset/" + urllib.parse.quote(pid, safe=":"))
    # le brouillon du Designer = ce preset à cette scène (sinon le Designer et le WebSocket se contredisent)
    _post(base, "/api/sandbox_apply", {"preset": doc, "scene": ex["scene"]})
    if slot is not None:
        _post(base, "/api/recall", {"slot": slot})
        _post(base, "/api/recall", {"scene": ex["scene"]})
    else:
        _post(base, "/api/recall", {"preset": pid, "scene": ex["scene"]})
    shots = os.path.join(out_dir, "..", os.path.basename(out_dir.rstrip("/")) + "-shots")
    os.makedirs(shots, exist_ok=True)
    anchors, hidden, posts = {}, {}, {}
    t0 = ((_get(base, "/api/state") or {}).get("boot") or {}).get("t0")
    phone = ex["route"].startswith("/app/m.html")                # le Companion se mesure à 390×844
    by_page = crawl(base, [] if phone else [ex["route"]], [ex["route"]] if phone else [], settle_ms, log=lambda *_: None,
                    shot=os.path.join(shots, ex["name"] + ".png"),
                    click=ex.get("click"), anchors=anchors, boot_skip=t0, ro=True, hidden=hidden, posts=posts)
    reads = {}
    for r in by_page.get(ex["route"], []):
        if VOLATILE.match(r) or _never(r, True):
            continue
        try:
            data = redact(_get(base, r))
        except Exception:
            continue
        if data != base_reads.get(r):
            reads[r] = data
    for key, data in ((posts.get(ex["route"]) or {}).get("answers") or {}).items():
        reads[key] = redact(data)                            # « POST /api/blocks/status » : servie telle quelle
    st = redact(_get(base, "/api/state"))
    for path, body in ex.get("undo") or []:
        _post(base, path, body)
    # un exemple montre UN RACK QUI JOUE : le démarrage est fini et le moteur répond. Le bridge jetable n'a pas de
    # REAPER ; sans ceci, /live montrerait l'écran « /loading » (showBoot, app/boot-model.mjs). Rien d'autre n'est retouché.
    st.pop("boot", None)
    st["reaper_connected"] = True
    # les écrans appairés au bridge jetable = le Chrome du relevé lui-même : personne, pas un appareil du rack
    st["devices_online"] = []
    out = {"name": ex["name"], "title": ex["title"], "route": ex["route"], "preset": pid, "scene": ex["scene"],
           "click": ex.get("click"), "state": st, "reads": reads, "anchors": anchors.get(ex["route"], []),
           "anchors_hidden": hidden.get(ex["route"], [])}
    bad = leaks(out)
    if bad:
        raise RuntimeError("example %s: a trace is left: %s" % (ex["name"], bad[:3]))
    log("  example %-28s %s · scene %s · %d reads differ" % (ex["name"], st.get("preset_name") or pid,
                                                            st.get("scene_id"), len(reads)))
    return out


# ── L'AUDIO DE LA DÉMO (docs/private/launch-plan.md §4, 2026-11-04) ─────────────────────────────────────────────────────
# Un visiteur ENTEND chaque son d'usine : les démos (une phrase de référence rendue à travers chaque patch, scène par
# scène, et les lanes des presets d'usine), plus une vraie prise dans Recordings. L'app les charge par <audio src>,
# HORS de fetch — golem.fm les sert sur de vraies routes : l'instantané les met dans `media/` et `SNAPSHOT.json`
# (`media`) dit, pour chacun, l'adresse que l'app demande, le fichier et son type.
# + les rendus des blocs drums / standard au pied (docs/preset-preview.md §8) : block-<preset>/<switch>/<type>.opus
DEMO_PREFIXES = ("patch-factory-", "preset-factory-", "block-factory-", "block-patch-factory-")
RE_DEMO_CLIP = re.compile(r"^library/previews/[^\s\"]+\.opus$")
# les sons des kits de PADS d'usine (48 one-shots synthétisés par golem, CC0 — docs/licence.md) : Library ▸ Drums ▸ Kits
# les joue par /api/sample?file=… et dessine leur forme par /api/peaks?file=… ; aucun autre échantillon ne part
RE_KIT_SAMPLE = re.compile(r"^assets/samples/kits/[^\s\"]+\.wav$")
DEMO_TAKE_KBPS = "96k"            # les pistes d'une prise, converties : 9 pistes d'une minute en WAV pèsent 150 Mo


def seed_demos(bench_root, log=print, src_root=ROOT):
    """Les démos d'usine du rack (library/previews/patch-factory-*, preset-factory-*) copiées dans le banc : le banc ne
    les rend pas, il montre celles qu'on a faites (décision du mainteneur, 2026-11-04)."""
    import shutil
    src = os.path.join(src_root, "library", "previews")
    dst = os.path.join(str(bench_root), "library", "previews")
    n = 0
    for d in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if d.startswith(DEMO_PREFIXES) and os.path.isdir(os.path.join(src, d)):
            shutil.copytree(os.path.join(src, d), os.path.join(dst, d), dirs_exist_ok=True)
            n += 1
    log("demos: %d factory demo folder(s) copied into the bench" % n)
    return n


def seed_take(bench_root, take, title=None, log=print, drop_roles=None):
    """La prise de démo, nettoyée (tools/demo_take.py), posée dans les prises du banc."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo_take", os.path.join(ROOT, "tools", "demo_take.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dst = mod.demo_take(take, os.path.join(str(bench_root), "recordings"), title, drop_roles)
    log("take: %s placed in the bench's Recordings" % os.path.basename(dst))
    return dst


def take_reads(base):
    """Les formes d'onde de chaque piste de chaque prise (/api/loop-peaks/<prise>/<piste>) : la page ne les lit qu'en
    ouvrant une prise, le relevé par page ne les voit donc pas."""
    try:
        takes = _get(base, "/api/loops").get("takes") or []
    except Exception:
        return []
    q = lambda p: "/".join(urllib.parse.quote(s, safe="") for s in p.split("/"))
    return ["/api/loop-peaks/" + q(t["dir"] + "/" + f) for t in takes for f in t.get("files") or []]


def _strings(x, rx, out):
    if isinstance(x, str) and rx.match(x):
        out.add(x)
    elif isinstance(x, dict):
        for v in x.values():
            _strings(v, rx, out)
    elif isinstance(x, list):
        for v in x:
            _strings(v, rx, out)
    return out


def kit_reads(base):
    """Les formes d'onde des sons des kits de pads d'usine (/api/peaks?file=…), lues par la page en ouvrant un kit."""
    try:
        files = _strings(_get(base, "/api/kits"), RE_KIT_SAMPLE, set())
    except Exception:
        return []
    return ["/api/peaks?file=" + urllib.parse.quote(f, safe="") for f in sorted(files)]


def collect_media(base, out_dir, written, log=print):
    """Les fichiers audio que les lectures écrites désignent → `<out>/media/…`. Rend {adresse: {file, type}}."""
    import subprocess
    media = {}

    def save(url, rel, body=None, transcode=False):
        p = os.path.join(out_dir, "media", *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if body is None:
            with urllib.request.urlopen(base + url, timeout=60) as r:
                body = r.read()
        if transcode:                                       # une piste de prise : opus, même adresse
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "-", "-c:a", "libopus", "-b:a", DEMO_TAKE_KBPS,
                                "-f", "ogg", p], input=body, capture_output=True)
            if r.returncode:
                raise RuntimeError(r.stderr.decode()[:200])
        else:
            with open(p, "wb") as f:
                f.write(body)
        media[url] = {"file": os.path.relpath(p, out_dir), "type": "audio/ogg"}

    clips = set()

    def walk(x):
        if isinstance(x, str) and RE_DEMO_CLIP.match(x):
            clips.add(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for read in written:
        try:
            with open(out_path(out_dir, read), encoding="utf-8") as f:
                walk(json.load(f))
        except (OSError, ValueError):
            pass
    for c in sorted(clips):
        save("/" + c, c)
    n_take = 0
    for read in written:
        if read.startswith("/api/loop-peaks/"):
            url = "/api/loop/" + read[len("/api/loop-peaks/"):]
            save(url, urllib.parse.unquote(url.lstrip("/")), transcode=True)
            n_take += 1
    kits = set()
    for read in written:
        if read.startswith("/api/peaks?file="):
            f = urllib.parse.unquote(read[len("/api/peaks?file="):])
            if RE_KIT_SAMPLE.match(f):
                kits.add(f)
    for f in sorted(kits):
        save("/api/sample?file=" + urllib.parse.quote(f, safe=""), "api/sample/" + f)
        media["/api/sample?file=" + urllib.parse.quote(f, safe="")]["type"] = "audio/wav"
    log("media: %d demo clip(s), %d take track(s), %d pad sample(s)" % (len(clips), n_take, len(kits)))
    return media


# LA PAGE SEPARATION de la démo : celle du mainteneur, ses moteurs et ses réglages, lue sur SON rack — la seule lecture
# d'un instantané d'usine qui ne vienne pas du banc. Son dossier personnel devient celui du compte de démo, et l'extrait
# d'essai (un fichier à lui, titre d'un morceau protégé compris) prend un nom de l'usine.
DEMO_EXCERPT = "Golem Rising (mix).wav"


def _neutral_engines(data):
    """Aucun modèle de séparation nommé dans la coquille publique (règle de separation.md) : le libellé, les arguments
    (fichiers de modèle), les noms de fichiers produits et les renvois entre moteurs d'un rack les nomment tous.
    Vécu le 2026-11-06 : l'instantané d'usine servi par le site les portait encore."""
    for i, e in enumerate(data.get("engines") or []):
        if not isinstance(e, dict):
            continue
        stems = sorted({v for v in (e.get("map") or {}).values() if isinstance(v, str)})
        e["label"] = "Local engine %d" % (i + 1)
        e["args"] = ["{input}", "--output_dir", "{outdir}", "--output_format", "WAV"]
        e["map"] = {"input_(%s).wav" % s: s for s in stems}
        e["used_by"] = []
        for k in list(e):
            if k.endswith("_label"):
                e[k] = "Local engine"
    return data


def separation_from(url, out_dir, log=print):
    data = _get(url.rstrip("/"), "/api/separation")
    home = os.path.expanduser("~").rstrip("/")

    def fix(x):
        if isinstance(x, str):
            return x.replace(home + "/", DEMO_HOME + "/") if x.startswith(home + "/") or (home + "/") in x else x
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        if isinstance(x, list):
            return [fix(v) for v in x]
        return x
    data = _neutral_engines(fix(data))
    if isinstance(data.get("excerpt"), dict) and data["excerpt"].get("name"):
        data["excerpt"] = dict(data["excerpt"], name=DEMO_EXCERPT)
    clean = redact(data)
    bad = leaks(clean)
    if bad:
        raise RuntimeError("the separation page keeps a trace: %s" % bad[:3])
    p = out_path(out_dir, "/api/separation")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)
    log("separation: the reference rack's page (%d engine(s)), home → %s" % (len(clean.get("engines") or []), DEMO_HOME))
    return "/api/separation"


def factory_snapshot(out_dir, rev="HEAD", settle_ms=1500, log=print, engine=True, demos=True, take=None,
                     take_title=None, separation=None, reference=REFERENCE_URL, take_drop=None):
    """Bridge jetable d'usine → relevé par page → instantané expurgé et vérifié, + `MANIFEST.json`."""
    import subprocess
    import time
    cu = _check_ui()
    commit = subprocess.run(["git", "-C", ROOT, "rev-parse", rev], capture_output=True, text=True, check=True).stdout.strip()
    br = cu.Bridge(test_content=False, rev=commit)
    with br as base, (Engine(br, log) if engine else contextlib.nullcontext()):
        log("factory snapshot: disposable bridge on %s (worktree of %s, factory content only%s)"
            % (base, commit[:8], ", its own REAPER" if engine else ", no engine"))
        if demos:
            seed_demos(br.root, log)
        if take:
            seed_take(br.root, take, take_title, log, take_drop)
        rack_seen = rack_check(base, reference)
        log("reference rack (%s): seen %s%s" % (rack_seen["variant"] or "no variant", ", ".join(rack_seen["seen"]) or "nothing",
                                          "" if rack_seen["complete"] else " — MISSING " + ", ".join(rack_seen["missing"])))
        rack, phone = factory_pages(base, cu)
        page_anchors, page_posts = {}, {}
        by_page = crawl(base, rack, phone, settle_ms, log, anchors=page_anchors, posts=page_posts)
        observed = sorted({r for v in by_page.values() for r in v if not VOLATILE.match(r) and not _never(r, True)})
        listed = list(dict.fromkeys(observed + reads_for(base) + take_reads(base) + kit_reads(base)))
        res = snapshot(base, out_dir, listed, log, factory=True)
        res["media"] = collect_media(base, out_dir, res["written"], log)
        if separation:
            separation_from(separation, out_dir, log)
        base_reads = {}
        for r in res["written"]:
            with open(out_path(out_dir, r), encoding="utf-8") as f:
                base_reads[r] = json.load(f)
        # un exemple marqué `rack` n'est fait que sur cette variante (les claviers sur `keys`) ; les autres, partout
        examples = [make_example(base, ex, base_reads, settle_ms, log, out_dir) for ex in EXAMPLES
                    if ex.get("rack") in (None, rack_seen["variant"])]
    os.makedirs(os.path.join(out_dir, "examples"), exist_ok=True)
    for ex in examples:
        with open(os.path.join(out_dir, "examples", ex["name"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(ex, f, ensure_ascii=False, indent=1)
    # la version du catalogue AU COMMIT de l'instantané, pas celle de l'arbre de travail
    catalog_version = json.loads(subprocess.run(["git", "-C", ROOT, "show", commit + ":library/catalog/effects.json"],
                                                capture_output=True, text=True, check=True).stdout).get("catalog_version")
    manifest = {
        "kind": "factory", "name": SNAPSHOT_NAMES.get(rack_seen["variant"]) or "factory", "commit": commit, "catalog_version": catalog_version, "made": time.strftime("%Y-%m-%d"),
        "reads": sorted(res["written"]), "examples": [e["name"] for e in examples],
        "assets": res.get("assets", {}),
        # l'AUDIO (2026-11-04) : {adresse que l'app demande: {file, type}} — golem.fm le sert à cette adresse exacte
        "media": res.get("media", {}),
        "machine": sorted(r for r in res["written"] if MACHINE.match(r)),
        "rack": rack_seen,
        # les lectures faites en POST (servies par les exemples sous « POST /api/… »), et ce que chaque page ÉCRIT au
        # chargement sans aucun geste — hors de ces lectures, chaque entrée est un bug de la page
        "post_reads": list(POST_READS),
        "load_writes": {k: [w for w in v["sent"] if w.split(" ", 1)[1] not in POST_READS]
                        for k, v in page_posts.items() if any(w.split(" ", 1)[1] not in POST_READS for w in v["sent"])},
        # ce que chaque page lit : golem.fm sait ainsi quelles lectures une page de doc doit avoir
        "pages": by_page,
        # les ancres data-doc présentes sur chaque page et dans chaque exemple, MESURÉES au rendu : une ancre
        # dynamique (designer.block:<id>) ne se trouve pas par un grep du code
        "anchors": {"pages": {k: v for k, v in page_anchors.items() if v},
                    "examples": {e["name"]: e["anchors"] for e in examples}},
        "written": sorted(res["written"]), "skipped": sorted(res["skipped"]),
        "failed": [r for r, _ in res["failed"]], "refused": [r for r, _ in res["refused"]],
    }
    with open(os.path.join(out_dir, "SNAPSHOT.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://localhost:8770")
    ap.add_argument("--factory", action="store_true",
                    help="the FACTORY snapshot: a disposable bridge with factory content only, every page crawled in "
                         "headless Chrome, every GET it makes recorded, named examples replayed (SNAPSHOT.json, examples/); --base is ignored")
    ap.add_argument("--rev", default="HEAD", help="with --factory: the commit the disposable bridge runs")
    ap.add_argument("--no-engine", action="store_true",
                    help="with --factory: no REAPER for the disposable bridge (faster; Health, looper and arrangement then show a rack that does not play)")
    ap.add_argument("--no-demos", action="store_true",
                    help="with --factory: without the factory demos of this rack (library/previews/patch-factory-*, preset-factory-*)")
    ap.add_argument("--take", help="with --factory: a take folder (recordings/perf-…) shown in Recordings, cleaned by tools/demo_take.py")
    ap.add_argument("--take-title", help="with --take: its title")
    ap.add_argument("--take-drop-role", action="append", default=[],
                    help="with --take: leave out the tracks of the input with this role (e.g. a silent Voice)")
    ap.add_argument("--separation-from", metavar="URL",
                    help="with --factory: the Settings ▸ Engines ▸ Separation page read on this bridge (the reference rack), "
                         "home folder shown as " + DEMO_HOME)
    ap.add_argument("--reference", metavar="URL", default=REFERENCE_URL,
                    help="with --factory: the reference rack's bridge, which probes the pedalboard (default %(default)s)")
    ap.add_argument("--out", default=os.path.join(ROOT, "shell-snapshot"))
    ap.add_argument("--list", help="a file: one GET read per line")
    ap.add_argument("--private-name", action="append", default=[], help="a person's name to pseudonymize everywhere")
    a = ap.parse_args(argv)
    listed = None
    if a.list:
        with open(a.list, encoding="utf-8") as f:
            listed = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if a.factory:
        os.makedirs(a.out, exist_ok=True)
        collect_private(a.private_name)
        r = factory_snapshot(a.out, a.rev, engine=not a.no_engine, demos=not a.no_demos, take=a.take,
                             take_title=a.take_title, separation=a.separation_from,
                             reference=a.reference, take_drop=a.take_drop_role)
    else:
        r = snapshot(a.base.rstrip("/"), a.out, listed, private=a.private_name)
    print("written %d · skipped (never in a snapshot) %d · failed %d · REFUSED %d -> %s"
          % (len(r["written"]), len(r["skipped"]), len(r["failed"]), len(r["refused"]), a.out))
    for read, why in r["failed"]:
        print("  failed %s: %s" % (read, why))
    return 1 if r["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
