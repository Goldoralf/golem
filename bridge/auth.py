# SPDX-License-Identifier: GPL-3.0-or-later
"""Auth du bridge (Sprints 3.1 + 3.5 — SECURITY.md, ferme S-P0-1).

Appareils NOMMÉS (Sprint 3.5) : chaque appareil distant a SON token, scellé par
une invitation à usage unique :
  - 127.0.0.1/::1 (kiosk, outils locaux) : auto-authentifié ;
  - « + Add device » crée une INVITATION nommée -> QR ; le 1er scan l'ÉCHANGE
    (POST /api/auth/claim) contre un token d'appareil frais et la consomme —
    le QR photographié ne sert plus à rien ;
  - mutations (POST/PUT/DELETE/PATCH) et GET sensibles : token d'appareil exigé
    pour le distant ; révocation par appareil OU totale ;
  - Origin étranger : refusé même avec cookie (anti-CSRF LAN).
Le token voyage en header X-Golem-Token, cookie golem_token, ou ?token= (WS).
Migration : l'ancien secret partagé (config/auth.token) devient un appareil
« Legacy device » — les appareils déjà appairés continuent de marcher.
"""
import contextlib
import os
import re
import sys
import json
import time
import secrets
import subprocess

from . import config as C
from .golog import get as _get_log

log = _get_log("auth")

TOKEN_PATH = os.path.join(C.ROOT, "config", "auth.token")            # legacy 3.1 (migré puis supprimé)
DEVICES_PATH = os.path.join(C.ROOT, "config", "auth-devices.json")   # 0600, gitignoré

# GET protégés comme des mutations (fuites : PSK WiFi en QR, tokens d'invitation…)
SENSITIVE_GET = ("/api/network/qr", "/api/auth/qr", "/api/auth/devices", "/api/backups",
                 # cet ordinateur (docs/installer.md §4) : gardés pour que le palier ADMIN s'applique aussi à la lecture
                 "/api/system/autostart", "/api/system/harden",
                 # audit 2026-11-04 (M3) : un GET hors des listes sensibles ne passe JAMAIS par le palier admin — ces trois
                 # lectures (serveur golem.fm et bout du jeton ; branche, fichiers modifiés, `?fetch=1` qui lance git ;
                 # `?force=1` qui interroge Cockos) étaient ouvertes à tout le LAN malgré ADMIN_PATHS
                 "/api/integrations", "/api/system/update", "/api/system/reaper-update")
# …et les DONNÉES DU GROUPE (audit 2026-08-12, E-1) : sans ces préfixes, n'importe quel
# appareil du LAN/AP — même jamais appairé — pouvait télécharger un backup complet
# (presets + recordings/) et streamer les prises de répète. Préfixes, pas égalité :
# ces routes portent un nom de fichier ({name}, {fn:path}, {slug}).
#   /api/backup/        liste distante, téléchargement du zip, statut de push
#   /api/loop           /api/loops (index des prises) + /api/loop/{fn} + /api/loop-peaks/{fn}
#   /api/take/          partitions de prise (score)
#   /api/backing/asset/ stems des backings (contenu sous licence)
# Les appareils appairés passent sans rien changer (le token voyage déjà en cookie).
# …et L'ÉTAT DU RACK (audit 2026-09-13, M3) : /api/state porte les PRÉNOMS du roster (person_name
# sur chaque entrée), le mode, le preset courant ; /api/sandbox le document entier en cours
# d'édition ; presets, patches, setlists, modes et patch d'entrées, ce que le groupe joue et qui
# joue quoi. docs/identity.md : le roster ne sort pas du rack. Un appareil du LAN jamais appairé
# lisait tout ça en GET (mesuré : 200 sur 192.168.0.22 sans jeton). Le kiosk et les outils sont en
# localhost (auto-auth), le Companion présente son cookie : rien de connu ne change.
SENSITIVE_GET_PREFIX = ("/api/backup/", "/api/loop", "/api/take/", "/api/backing/asset/",
                        "/api/state", "/api/sandbox", "/api/preset", "/api/patch", "/api/setlist",
                        "/api/mode", "/api/inputmap", "/api/song", "/api/roster", "/api/band",
                        # …et les PAQUETS DE DIAGNOSTIC (lot 8) : scrubbés, mais un état complet de la machine
                        "/api/diag",
                        # les moteurs de séparation : chemins et commandes saisis (docs/separation.md §1)
                        "/api/separation",
                        # audit 2026-10-15 : les formes d'onde d'une prise, les samples du groupe et le résultat d'un
                        # import étaient lisibles par tout le LAN sans token
                        "/api/peaks", "/api/sample", "/api/kits/import/job",
                        # Settings ▸ Health (docs/health.md) : le preset joué, la setlist et ses presets — `/api/health`
                        # tout court (le pouls du lanceur, avant appairage) reste public : la barre oblique compte
                        "/api/health/",
                        # Le modèle complet contient les captures privées de plugins.
                        "/api/vst-host/capture/parametric", "/api/vst-host/capture/module", "/api/lane/capture",
                        # audit 2026-11-04 (H3) : le statut d'appairage golem.fm porte le code et l'URL d'approbation
                        "/api/golemfm/pair",
                        # audit 2026-11-04 (M1) : le système de fichiers du rack (dossiers, volumes, chemins absolus, nom
                        # d'utilisateur) se parcourait sans jeton ; /api/separation/browse, la même fonction, était admin
                        "/api/kits/import", "/api/song-folders", "/api/inbox", "/api/storage")

# ── palier ADMIN (audit 2026-08-12, M-1) : le rôle d'un appareil (Guitar, Voice…) est un
# INSTRUMENT, pas un privilège — et tout appareil appairé pouvait flasher le FCB, changer le
# réseau ou tout révoquer. Les mutations SYSTÈME exigent désormais un appareil promu admin
# (flag `admin` sur la fiche, posé depuis l'écran du rack) ; l'écran du rack (localhost)
# reste tout-puissant — c'est lui qui porte le groupe (docs/identity.md). Défaut sain :
# aucun appareil admin -> ces gestes ne se font que debout devant le rack. ──
ADMIN_PATHS = ("/api/auth/qr",       # audit 2026-11-04 (L1) : le QR d'une invitation EST son jeton
               "/api/connect/settings", "/api/auth/revoke", "/api/auth/promote", "/api/auth/conductor", "/api/auth/extend", "/api/auth/pair-code",
               "/api/ui/quit", "/api/system/update",
               "/api/system/reaper-update", "/api/system/reaper-restart", "/api/audio-buffer",
               "/api/fcb/flash",
               # 2026-10-03 : `/api/fcb/flash` n'était plus qu'un ALIAS de /api/pedalboard/load — le vrai
               # chemin du flash restait ouvert à tout appareil appairé. Avec lui, ce qui réécrit le pédalier
               # ou coupe ses prises ; et le moteur (bascule de version, fichier de licence).
               "/api/pedalboard/load", "/api/pedalboard/hold", "/api/pedalboard/flashed",
               "/api/pedalboard/select", "/api/pedalboard/learn/save",
               "/api/system/reaper-switch", "/api/system/reaper-license",
               "/api/karaoke/cmd",
               # audit 2026-10-15 (S1, S2) : changer le serveur golem.fm, son jeton ou une clé qui finit dans .env,
               # et relancer le bridge qui les relit — un téléphone appairé y gagnait l'exécution de code
               "/api/integrations", "/api/system/bridge-restart",
               # audit 2026-10-15 (lot 5) : les SONDES DE DÉVELOPPEMENT (routes_dev) pilotent REAPER — recharger le
               # projet, le stresser, poser une piste de test. Les outils tools/check-* tournent sur le rack : local = admin.
               "/api/rig_recall", "/api/loadtest", "/api/chunkdump", "/api/namtest", "/api/projreload",
               "/api/fxprobe", "/api/fxdump", "/api/gapmeter", "/api/lcbench",
               # 2026-10-16 (docs/installer.md §4) : cet ORDINATEUR — rouvrir sa fenêtre, le faire démarrer avec lui,
               # le verrouiller (pare-feu, mises à jour figées : mot de passe de l'utilisateur). Comme ⏻ Stop golem.
               "/api/ui/show", "/api/system/autostart", "/api/system/harden")
# …et l'ÉCRITURE de la config du rack, qu'un téléphone de musicien n'a jamais à toucher (la lire reste permis) :
# éditer un mode, le recorder, la carte d'entrées, les appareils connus, lancer la file de jobs golem.fm à la main
ADMIN_WRITES = ("/api/mode/update", "/api/mode/new", "/api/mode/reset", "/api/recorder",
                "/api/inputmap", "/api/inputmap/pair", "/api/tones-jobs/run",
                "/api/vst-host/capture/parametric/setup",
                # Health ▸ Fix (docs/assistant.md §3) : redémarre REAPER, change le buffer — le geste d'un admin
                "/api/health/fix",
                # « Ask golem » : envoie l'état de la machine à golem.fm (docs/assistant.md §6) — le geste d'un admin
                "/api/health/assistant",
                # les démos d'usine par lot (docs/preset-preview.md §7) : le moteur pris une demi-heure
                "/api/preview/batch",
                # le rendu des blocs (docs/preset-preview.md §8) : le moteur pris, comme le lot des démos
                "/api/preview/blocks", "/api/preview/blocks/stop")
ADMIN_WRITE_PREFIX = ("/api/devices/",)              # vérification du karaoké : remplace le preset joué
ADMIN_PREFIX = ("/api/network/", "/api/auth/devices", "/api/backup", "/api/cards/",
                # docs/separation.md : ajouter un moteur « programme », c'est faire EXÉCUTER un fichier choisi
                "/api/separation",
                # audit 2026-11-04 (H1) : restaurer une sauvegarde réécrit presets/, library/ (effects.json), config/ et
                # FUSIONNE un catalogue sans le valider — un invité y gagnait un `file` hors assets/ puis sa lecture par
                # /api/vst-host/capture/parametric/download. Comme /api/backup : un geste d'écran.
                "/api/import",
                # audit 2026-11-04 (H2) : le paquet de diagnostic embarque le journal du bridge, où uvicorn écrit le
                # chemin du WebSocket avec son `?token=` ; scrubbé ou non, c'est l'état complet de la machine
                "/api/diag",
                # audit 2026-11-04 (H3) : l'appairage golem.fm — le code et l'URL d'approbation étaient lisibles par
                # tout le LAN, et un membre pouvait lier le rack à son propre compte. Comme /api/integrations.
                "/api/golemfm/pair",
                # audit 2026-11-04 (M1) : parcourir les dossiers et les volumes du rack, comme /api/separation/browse
                "/api/kits/import/browse", "/api/kits/import/scan", "/api/kits/import/read",
                "/api/kits/import/volumes", "/api/song-folders/browse")

_db = None      # {"devices":[{id,name,token,created,last_seen}], "invites":[{id,name,token,created}]}


def _now():
    return int(time.time())


# ── durées (docs/devices-people.md, lots A et C — 2026-09-15) ───────────────────────────────────
INVITE_TTL = 15 * 60          # une invitation non scannée meurt : un QR photographié ne vit pas une semaine
GUEST_TTL = 24 * 3600         # défaut d'un invité : un soir (prolongeable)
# DURÉE D'ACCÈS D'UN INVITÉ (décision 2026-09-16, docs/devices-people.md §8) : le remplaçant d'un
# soir et le batteur qui répète tout l'automne sont deux durées du MÊME geste. Sans ça, un musicien sans
# compte golem.fm re-scannait un QR à chaque répète — et c'est ce qui rendait tentant d'inventer des
# « membres sans compte » côté serveur, pour un besoin qui n'était qu'une durée.
# SANS FIN (2026-11-02) : `days` = 0. golem.fm n'ouvre pas avec la v0.6 — un membre du groupe sans compte
# golem.fm ne doit pas re-scanner un QR tous les mois ; l'accès dure jusqu'à ce qu'on retire l'appareil.
GUEST_DAYS = (1, 7, 30, 0)


def guest_ttl(days=None):
    """Secondes d'accès pour un invité ; 0 = sans fin. Hors de la table : un jour, jamais une durée inventée."""
    try:
        d = int(days)
    except (TypeError, ValueError):
        return GUEST_TTL
    return d * 24 * 3600 if d in GUEST_DAYS else GUEST_TTL


def _set_guest_ttl(d, ttl):
    """Pose l'échéance d'un appareil invité — ou l'enlève (sans fin)."""
    if ttl:
        d["expires"], d["guest_days"] = _now() + ttl, round(ttl / 86400)
    else:
        d.pop("expires", None)
        d["guest_days"] = 0
PAIR_TTL = 10 * 60            # le code d'appairage du premier écran
PAIR_TRIES = 10               # essais ratés avant que le code ne meure (six chiffres sur le LAN)


def _people():
    """Le groupe en cache (docs/identity.md §3) : {id: prénom}. Vide si le rack n'a jamais vu golem.fm."""
    try:
        with open(os.path.join(C.CONFIG_DIR, ".band.json")) as f:
            return {p.get("id"): p.get("name") for p in (json.load(f).get("people") or []) if isinstance(p, dict) and p.get("id")}
    except Exception:
        return {}


def _purge(db):
    """Retire les invitations et le code d'appairage expirés. Rend True si quelque chose est parti."""
    now = _now()
    before = (len(db["invites"]), bool(db.get("pair")))
    db["invites"] = [i for i in db["invites"] if (i.get("created") or now) + INVITE_TTL > now]
    p = db.get("pair")
    if p and ((p.get("created") or 0) + PAIR_TTL <= now or (p.get("fails") or 0) >= PAIR_TRIES):
        db.pop("pair", None)
    return before != (len(db["invites"]), bool(db.get("pair")))


def _save():
    tmp = DEVICES_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(_db, f, indent=1)
    os.replace(tmp, DEVICES_PATH)


def _load():
    global _db
    if _db is not None:
        return _db
    try:
        _db = json.load(open(DEVICES_PATH))
        _db.setdefault("devices", []); _db.setdefault("invites", [])
    except Exception:
        _db = {"devices": [], "invites": []}
    # Migration 3.1 -> 3.5 : le secret partagé devient un appareil nommé (zéro re-scan).
    try:
        legacy = open(TOKEN_PATH).read().strip()
        if legacy and not any(d.get("token") == legacy for d in _db["devices"]):
            _db["devices"].append({"id": secrets.token_urlsafe(6), "name": "Legacy device",
                                   "token": legacy, "created": _now(), "last_seen": None})
        os.remove(TOKEN_PATH)
        _save()
    except OSError:
        pass
    return _db


# ── gestion des appareils (routes_system) ───────────────────────────────────

def list_devices():
    """Vue UI — SANS les tokens (ils ne repassent jamais sur le réseau). Chaque appareil dit sa
    PERSONNE (lot A) ; `expired` pour un invité dont l'appareil a expiré ; `left_band` quand sa personne
    n'est plus dans le groupe synchronisé (jamais révoqué en silence : le roster peut être incomplet)."""
    db = _load()
    if _purge(db):
        _save()
    now, ppl = _now(), _people()
    out = []
    for d in db["devices"]:
        row = {k: d.get(k) for k in ("id", "name", "role", "kind", "model", "mac", "ip", "created", "last_seen",
                                      "admin", "conductor", "person", "person_name", "expires", "screen", "via", "guest_days")}
        if d.get("person") and not str(d["person"]).startswith("guest:"):
            row["person_name"] = ppl.get(d["person"]) or d.get("person_name") or d["person"]
            row["left_band"] = bool(ppl) and d["person"] not in ppl
        row["expired"] = bool(d.get("expires") and d["expires"] <= now)
        out.append(row)
    return {"devices": out,
            "invites": [{**{k: i.get(k) for k in ("id", "name", "role", "kind", "created", "person", "person_name")},
                         "expires": (i.get("created") or now) + INVITE_TTL} for i in db["invites"]],
            "people": [{"id": k, "name": v} for k, v in ppl.items()]}


ROLES = ("Guitar", "Bass", "Voice", "Keys", "Drums", "Pads", "Keys + Pads")
KINDS = ("Phone", "Tablet", "Computer")


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:24] or "guest"


def create_invite(role, kind, person=None, guest=None, days=None):
    """Invitation TAGUÉE : QUI × QUOI. Depuis le 2026-09-15 (docs/devices-people.md, lot A), le « qui »
    est une PERSONNE du groupe (`person` = id du roster) ou un INVITÉ d'un soir (`guest` = son prénom,
    appareil qui expire en 24 h) ; le rôle ne sert plus qu'à une personne SANS entrée (batterie sans pad,
    ingé son) pour choisir la vue. Sans personne, l'ancien comportement : un rôle. Ce n'est pas une
    authentification (docs/identity.md §1) : on SÉLECTIONNE un prénom. La fiche technique est capturée au scan."""
    db = _load()
    _purge(db)
    kind = kind if kind in KINDS else "Phone"
    role = role if role in ROLES else None
    inv = {"id": secrets.token_urlsafe(6), "kind": kind, "role": role,
           "token": secrets.token_urlsafe(32), "created": _now()}
    if guest and str(guest).strip():
        nm = str(guest).strip()[:24]
        inv.update(person="guest:" + _slug(nm), person_name=nm, guest=True, ttl=guest_ttl(days))
    elif person:
        ppl = _people()
        if ppl and person not in ppl:
            return {"error": "this person is not in the band"}
        inv.update(person=str(person), person_name=ppl.get(person) or str(person))
    elif not role:
        inv["role"] = role = "Guitar"
    inv["name"] = f"{inv.get('person_name') or role}"          # « · Phone » s'ajoute au scan (kind_from_ua)
    db["invites"].append(inv)
    _save()
    return {"id": inv["id"], "name": inv["name"], "role": role, "kind": kind, "ttl": inv.get("ttl"),
            "person": inv.get("person"), "person_name": inv.get("person_name"), "expires": inv["created"] + INVITE_TTL}


def _grant_conductor(dev):
    """LES DROITS DU GROUPE DESCENDENT JUSQU'AU RACK (décision 2026-09-16, §8). Le téléphone d'un
    owner ou d'un admin de l'espace est CONDUCTOR d'office : c'est déjà lui qui décide sur golem.fm, et
    l'écran du rack n'a pas à le redire. Les autres restent en lecture — un doigt de plus capable de
    charger un morceau en plein set, c'est le son du groupe qui coupe (lot F).

    Uniquement À LA CRÉATION, et uniquement si personne n'a encore tranché : un `conductor` déjà posé
    (donné ou retiré à la main sur l'écran) n'est jamais réécrit par une synchro de roster."""
    if dev.get("kind") != "Phone" or "conductor" in dev:
        return dev
    pid = dev.get("person")
    if not pid or str(pid).startswith("guest:"):
        return dev
    try:
        from . import roster
        if (roster.person(pid).get("rights") or "member") in ("owner", "admin"):
            dev["conductor"] = True
    except Exception as e:                       # roster illisible : l'appareil existe quand même
        log.warning(f"droits du groupe illisibles : {e}")
    return dev


def _model_from_ua(ua):
    """Modèle lisible depuis le User-Agent du scan (heuristiques simples, "" si inconnu)."""
    ua = ua or ""
    m = re.search(r"\(([^)]*)\)", ua)
    inner = m.group(1) if m else ""
    if "iPhone" in ua:
        return "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Android" in inner:
        parts = [x.strip() for x in inner.split(";")]
        cand = parts[-1].split(" Build")[0].strip() if parts else ""
        # Chrome Android récent fige l'UA à « Android 10; K » (vie privée) : pas un modèle
        return "Android" if cand in ("", "K") else cand
    if "CrOS" in inner:
        return "Chromebook"
    if "Windows" in inner:
        return "Windows PC"
    if "Macintosh" in inner or "Mac OS X" in inner:
        return "Mac"
    if "Linux" in inner:
        return "Linux"
    return ""


def kind_from_ua(ua):
    """Téléphone, tablette ou ordinateur, LU au scan (2026-10-03 : « pourquoi sélectionner smartphone
    ou tablette ? tu peux le savoir une fois connecté »). Ce qui compte : un Phone ouvre le Companion
    (/app/m.html), le reste l'app complète. Un iPad récent se présente en « Macintosh » : il tombe en
    Computer, qui ouvre la même app qu'une tablette — l'erreur ne coûte rien. None si l'UA est vide."""
    ua = ua or ""
    if not ua:
        return None
    if "iPhone" in ua or "iPod" in ua or ("Android" in ua and "Mobile" in ua):
        return "Phone"
    if "iPad" in ua or "Android" in ua or "Tablet" in ua:
        return "Tablet"
    return "Computer"


def _mac_of(ip):
    """MAC de l'appareil via la table de voisinage (le claim vient d'arriver : l'entrée est fraîche)."""
    if not ip:
        return ""
    try:
        for line in open("/proc/net/arp").read().splitlines()[1:]:
            f = line.split()
            if len(f) >= 4 and f[0] == ip and f[3] != "00:00:00:00:00:00":
                return f[3]
    except OSError:
        pass
    try:                                            # IPv6 (absente de /proc/net/arp)
        out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"lladdr\s+([0-9a-f:]{17})", out)
        return m.group(1) if m else ""
    except Exception:
        return ""


def invite_token(iid):
    db = _load()
    if _purge(db):
        _save()
    for i in db["invites"]:
        if i["id"] == iid:
            return i["token"]
    return None


def claim(invite_tok, ua="", ip=""):
    """Échange invitation -> token d'appareil, UNE fois (l'invitation est consommée).
    Le token d'appareil est FRAIS : celui du QR ne circule plus après le scan.
    C'est ICI qu'on remplit la fiche de l'appareil : modèle (User-Agent), MAC, IP."""
    db = _load()
    _purge(db)                                    # une invitation expirée ne s'échange plus
    for i in list(db["invites"]):
        if _same(i.get("token", ""), invite_tok or ""):
            db["invites"].remove(i)
            # le type d'appareil se LIT au scan ; celui de l'invitation ne sert que si l'UA ne dit rien
            kind = kind_from_ua(ua) or i.get("kind")
            name = f"{i.get('person_name') or i.get('role') or 'Device'} · {kind}"
            dev = {"id": i["id"], "name": name, "role": i.get("role"), "kind": kind,
                   "model": _model_from_ua(ua), "mac": _mac_of(ip), "ip": ip,
                   "token": secrets.token_urlsafe(32), "created": _now(), "last_seen": _now()}
            for k in ("person", "person_name"):
                if i.get(k):
                    dev[k] = i[k]
            if i.get("guest"):
                _set_guest_ttl(dev, i.get("ttl", GUEST_TTL))
            _grant_conductor(dev)
            db["devices"].append(dev)
            _save()
            return {"token": dev["token"], "name": dev["name"]}
    return None


def remove(did):
    """Révoque UN appareil (ou annule une invitation) par id."""
    db = _load()
    before = len(db["devices"]) + len(db["invites"])
    db["devices"] = [d for d in db["devices"] if d["id"] != did]
    db["invites"] = [i for i in db["invites"] if i["id"] != did]
    changed = before != len(db["devices"]) + len(db["invites"])
    if changed:
        _save()
    return changed


def revoke():
    """Panique : révoque TOUS les appareils + invitations."""
    global _db
    _load()
    _db = {"devices": [], "invites": []}
    _save()


def set_person(did, person=None, guest=None, days=None):
    """Dit QUI utilise un appareil déjà appairé, sans rescanner (2026-09-15 : son téléphone était
    « Guitar »). `person` du groupe, `guest` un prénom d'invité (expire en 24 h), ni l'un ni l'autre : on
    retire la personne. Rend {ok} ou {error}."""
    db = _load()
    d = next((x for x in db["devices"] if x["id"] == did), None)
    if d is None:
        return {"error": "unknown device"}
    for k in ("person", "person_name"):
        d.pop(k, None)
    if guest and str(guest).strip():
        nm = str(guest).strip()[:24]
        d.update(person="guest:" + _slug(nm), person_name=nm)
        _set_guest_ttl(d, guest_ttl(days))
    elif person:
        ppl = _people()
        if ppl and person not in ppl:
            return {"error": "this person is not in the band"}
        d.update(person=str(person), person_name=ppl.get(person) or str(person))
        d.pop("expires", None); d.pop("guest_days", None)
        _grant_conductor(d)
    kind = d.get("kind") or "Device"
    d["name"] = f"{d.get('person_name') or d.get('role') or 'Device'} · {kind}"
    _save()
    return {"ok": True}


def extend(did, hours=24, days=None):
    """Prolonge l'appareil d'un invité (ou lui en donne une échéance). `days` (1, 7, 30) l'emporte sur
    `hours` : c'est le geste de l'écran, « encore une semaine ». True si l'appareil existe."""
    db = _load()
    add = guest_ttl(days) if days is not None else int(hours) * 3600
    for d in db["devices"]:
        if d["id"] == did:
            if not add:                       # « sans fin »
                _set_guest_ttl(d, 0)
                _save()
                return True
            d["expires"] = max(d.get("expires") or 0, _now()) + add
            if days is not None:
                d["guest_days"] = round(add / 86400)
            _save()
            return True
    return False


# ── LE PREMIER ÉCRAN D'UN RACK SANS ÉCRAN (docs/devices-people.md, lot C) ───────────────────────
# Un rack `headless` n'a pas d'écran pour montrer un QR, et créer une invitation exige d'être en local
# ou admin : un rack neuf ne pouvait donc JAMAIS avoir son premier écran. Un CODE à six chiffres,
# créé en local (`golem pair`) ou publié au démarrage tant qu'aucun admin n'existe, valable 10 min,
# usage unique : le premier appareil qui le saisit devient « Rack screen » (tablette, sans personne, admin).
def admin_exists():
    return any(d.get("admin") for d in _load()["devices"])


def create_pair_code():
    db = _load()
    code = f"{secrets.randbelow(1_000_000):06d}"
    db["pair"] = {"code": code, "created": _now(), "fails": 0}
    _save()
    return {"code": code, "expires": db["pair"]["created"] + PAIR_TTL}


def pair_code_pending():
    db = _load()
    if _purge(db):
        _save()
    p = db.get("pair")
    return {"expires": p["created"] + PAIR_TTL} if p else None


def claim_pair(code, ua="", ip=""):
    """Échange le code contre un token d'appareil ADMIN « Rack screen ». None si le code est faux ou mort."""
    db = _load()
    _purge(db)
    p = db.get("pair")
    if not p:
        _save()
        return None
    if not _same(str(p.get("code") or ""), str(code or "").strip()):
        p["fails"] = (p.get("fails") or 0) + 1
        _purge(db)
        _save()
        return None
    db.pop("pair", None)
    dev = {"id": secrets.token_urlsafe(6), "name": "Rack screen", "role": None, "kind": "Tablet", "screen": True,
           "admin": True, "model": _model_from_ua(ua), "mac": _mac_of(ip), "ip": ip,
           "token": secrets.token_urlsafe(32), "created": _now(), "last_seen": _now()}
    db["devices"].append(dev)
    _save()
    return {"token": dev["token"], "name": dev["name"]}


# ── LE CONDUCTOR (docs/devices-people.md, lot F — décision 2026-09-15) ────────────────────────
# Charger un morceau reconstruit le rig pendant quelques secondes : cinq téléphones capables de le faire,
# c'est un doigt qui coupe le son du groupe. Un TÉLÉPHONE ne charge, ne lance, n'arrête un morceau ou la
# prise que s'il est CONDUCTOR (ou admin). Les écrans (tablette, ordinateur) gardent ce qu'ils avaient.
CONDUCTOR_PATHS = ("/api/recall", "/api/arrangement", "/api/perf/start", "/api/perf/stop", "/api/backing")


def set_conductor(did, flag):
    db = _load()
    for d in db["devices"]:
        if d["id"] == did:
            d["conductor"] = bool(flag)
            _save()
            return True
    return False


def set_admin(did, flag):
    """Promeut/rétrograde un appareil (flag `admin`). True si l'appareil existe."""
    db = _load()
    for d in db["devices"]:
        if d["id"] == did:
            d["admin"] = bool(flag)
            _save()
            return True
    return False


# ── verdicts (middleware) ────────────────────────────────────────────────────

def _device_by_token(tok):
    """La fiche COMPLÈTE de l'appareil dont c'est le token, None si inconnu.
    Met à jour last_seen (flush disque ≤ 1/min/appareil : les _save des autres
    mutations persistent le reste opportunément)."""
    if not tok:
        return None
    for d in _load()["devices"]:
        if _same(d.get("token", ""), tok):
            if d.get("expires") and d["expires"] <= _now():
                return None                       # l'invité d'hier soir : son appareil ne parle plus
            stale = (d.get("last_seen") or 0) < _now() - 60
            d["last_seen"] = _now()
            if stale:
                _save()
            return d
    return None


# ── CONNECTÉ PAR GOLEM.FM (docs/connect.md, lot R1 — 2026-09-16) ─────────────────────────────────
# golem.fm/connect redirige le téléphone avec un ticket ; `connect.redeem` le rachète et appelle ceci.
# Pas d'invitation, pas de QR : golem.fm s'est porté garant de la personne. Un même téléphone revient
# avec le même `client` (haché par golem.fm avec l'id stable du rack) : il retrouve SA fiche et SON jeton,
# ce qui garde valides le jeton rangé sous l'IP et celui rangé sous le nom `.local`.
# Ce qu'un appareil distant NON APPAIRÉ peut lire (audit 2026-11-04, M4) : de quoi charger l'app et apprendre qu'il doit
# s'appairer (app/lib.js redirige alors vers unpaired.html), le pouls du lanceur, le catalogue des blocs (aucune donnée
# du groupe), et le retour de connexion TONE3000, où atterrit un téléphone qui peut ne pas être appairé.
PUBLIC_GET = ("/api/auth/whoami", "/api/health", "/api/app-build", "/api/effects", "/api/t3k/auth/callback")

OPEN_EXCHANGES = ("/api/auth/claim", "/api/auth/pair", "/api/auth/connect", "/api/auth/handoff/claim")
HANDOFF_TTL = 60
_handoffs = {}                                   # code -> (id d'appareil, échéance) — en mémoire : 60 s de vie


def open_path(kind):
    return "/app/m.html" if kind == "Phone" else "/app/"


def connect_device(person=None, kind="Phone", screen=False, client=None, ua="", ip=""):
    """Crée ou retrouve l'appareil d'une personne connectée par golem.fm. `screen` : la tablette du
    propriétaire devient « Rack screen » (sans personne, admin — comme le code d'appairage du lot C).
    Rend {token, name, kind, screen, open} ou {error}."""
    kind = kind if kind in KINDS else "Phone"
    if not screen and not (isinstance(person, dict) and person.get("id")):
        return {"error": "golem.fm did not say who you are"}
    db = _load()
    _purge(db)
    d = next((x for x in db["devices"] if client and x.get("client") == client), None)
    if d is None:
        d = {"id": secrets.token_urlsafe(6), "token": secrets.token_urlsafe(32), "created": _now()}
        db["devices"].append(d)
    d.update(kind=kind, via="golem.fm", ip=ip, last_seen=_now(),
             model=_model_from_ua(ua) or d.get("model") or "", mac=_mac_of(ip) or d.get("mac") or "")
    if client:
        d["client"] = client
    d.pop("expires", None)
    d.pop("role", None)
    if screen:
        d.update(kind="Tablet", screen=True, admin=True, name="Rack screen")
        d.pop("person", None); d.pop("person_name", None)
    else:
        if d.pop("screen", None):
            d.pop("admin", None)                 # l'admin venait de l'écran du rack, pas d'une promotion
        d.update(person=str(person["id"])[:64], person_name=str(person.get("name") or person["id"])[:40])
        d["name"] = f"{d['person_name']} · {kind}"
        if isinstance(person.get("rights"), str) and "conductor" not in d and kind == "Phone":
            d["conductor"] = person["rights"] in ("owner", "admin")   # le ticket porte les droits
        _grant_conductor(d)                                           # sinon le roster les porte
    _save()
    return {"token": d["token"], "name": d["name"], "kind": d["kind"], "screen": bool(d.get("screen")),
            "open": open_path(d["kind"])}


def create_handoff(device_id):
    """Un code à usage unique (60 s) pour poser le jeton de CET appareil sous une autre origine : la page
    ouverte par IP bascule vers `http://<rack>.local:8770`, que le téléphone garde de la répète à la scène."""
    now = _now()
    for c in [c for c, (_, exp) in _handoffs.items() if exp <= now]:
        _handoffs.pop(c, None)
    code = secrets.token_urlsafe(24)
    _handoffs[code] = (device_id, now + HANDOFF_TTL)
    return {"code": code, "expires": now + HANDOFF_TTL}


def claim_handoff(code):
    code = str(code or "")
    hit = next((c for c in list(_handoffs) if _same(c, code)), None) if code else None
    if hit is None:
        return None
    did, exp = _handoffs.pop(hit)
    if exp <= _now():
        return None
    d = next((x for x in _load()["devices"] if x["id"] == did), None)
    if d is None or (d.get("expires") and d["expires"] <= _now()):
        return None
    return {"token": d["token"], "name": d.get("name"), "kind": d.get("kind"), "open": open_path(d.get("kind"))}


def _valid(tok):
    """Token d'appareil connu ?"""
    return _device_by_token(tok) is not None


def device_of(request):
    """La fiche PUBLIQUE de l'appareil qui parle (par son token), None si local/inconnu.
    Sert whoami (routage Companion) et la signature des flags de take."""
    tok = _presented(request)
    if not tok:
        return None
    d = _device_by_token(tok)
    if d is None:
        return None
    out = {k: d.get(k) for k in ("id", "name", "role", "kind", "person", "person_name", "screen", "admin", "conductor")}
    if d.get("person") and not str(d["person"]).startswith("guest:"):
        out["person_name"] = _people().get(d["person"]) or d.get("person_name") or d["person"]
    return out


def token_state(request):
    """« none » (aucun jeton présenté), « ok », ou « unknown » : un jeton présenté que le rack ne
    reconnaît plus (révoqué, invité expiré, rack réinitialisé). Lot B : l'app le DIT au lieu de
    s'ouvrir figée. Le jeton du WebSocket passe par la query : on l'accepte ici aussi, en lecture."""
    tok = _presented(request) or request.query_params.get("token") or ""
    if not tok:
        return "none"
    return "ok" if _device_by_token(tok) is not None else "unknown"


def _is_local(host):
    return host in ("127.0.0.1", "::1", "localhost")


def request_is_admin(request):
    """L'écran local, ou un appareil promu."""
    if _is_local(request.client.host if request.client else ""):
        return True
    dev = _device_by_token(_presented(request))
    return bool(dev and dev.get("admin"))


def is_guest(dev):
    """Un appareil d'INVITÉ : appairé pour quelques jours, hors du roster du groupe."""
    return bool(dev.get("expires")) or str(dev.get("person") or "").startswith("guest:")


def host_ok(host):
    """Audit 2026-10-15 (S4) — DNS REBINDING : une page web ouverte sur la machine du rack fait résoudre SON nom
    vers 127.0.0.1 ; le navigateur la croit chez elle, l'Origin et le Host portent le même nom étranger, et le
    bridge la prenait pour l'écran local, donc admin. Le rack ne se nomme que par une IP, `localhost`, son nom
    de machine ou un nom `.local` (mDNS, et le DNS de son point d'accès) — tout autre nom est refusé.
    `GOLEM_ALLOWED_HOSTS` (virgules) ajoute des noms pour qui sert le rack derrière son propre DNS."""
    import ipaddress, socket
    h = (host or "").strip().lower()
    if h.startswith("["):                                   # [::1]:8770
        h = h[1:h.find("]")] if "]" in h else h
    elif h.count(":") == 1:
        h = h.split(":")[0]
    h = h.rstrip(".")
    if not h:
        return True                                         # pas de Host (HTTP/1.0, un outil) : pas un navigateur
    try:
        ipaddress.ip_address(h)
        return True                                         # une IP ne se « rebinde » pas
    except ValueError:
        pass
    me = socket.gethostname().lower()
    short = me.split(".")[0]
    extra = [x.strip().lower() for x in os.environ.get("GOLEM_ALLOWED_HOSTS", "").split(",") if x.strip()]
    # audit 2026-11-04 (M6) : N'IMPORTE QUEL `.local` passait — or tout appareil du LAN répond en mDNS pour le nom qu'il
    # veut (`evil.local` → 127.0.0.1), et c'est le rebinding qu'on bloque. Seuls les noms que CE rack annonce :
    # golem.local ou golem-<machine>.local (bridge/reach.py), <machine>.local (avahi, connect.mdns_name).
    local_names = {"golem.local", f"golem-{short}.local", f"{short}.local", f"{me}.local"}
    with contextlib.suppress(Exception):
        from . import reach as _reach
        if _reach._STATE.get("name"):
            local_names.add(_reach._STATE["name"].lower() + ".local")
    # `testserver` : le Host du TestClient de Starlette — dans les tests seulement, jamais sur un rack
    test = "testserver" if "pytest" in sys.modules else None
    return (h in ("localhost", me, short, test) or h in local_names
            or h.endswith(".localhost") or h in extra)


def _same(a, b):
    """Comparaison à temps constant de deux jetons. En OCTETS : sur deux str, compare_digest lève TypeError dès qu'un
    caractère n'est pas ASCII — un en-tête « X-Golem-Token: é » faisait un 500 au lieu d'un refus (revue 2026-10-25)."""
    if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
        return False                      # un jeton absent ne correspond jamais (ni à un autre absent, ni à « None »)
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _presented(request):
    """Le token présenté par une requête HTTP : header ou cookie. PAS la query (audit 2026-09-13,
    m3) : un `?token=` finit dans l'historique du navigateur, les journaux d'un proxy, un lien
    copié. Seul le WebSocket y a droit (allowed_ws) — il ne peut pas poser de header."""
    return (request.headers.get("x-golem-token")
            or request.cookies.get("golem_token") or "")


def _origin_ok(request):
    """Origin absent (curl, WS natif) = OK ; présent -> doit viser NOTRE hôte (anti-CSRF :
    une page tierce chargée sur le LAN rejouerait les cookies, pas le header)."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    try:
        from urllib.parse import urlsplit
        o = urlsplit(origin)
        # le PORT compte : une autre appli web de la machine (un serveur de dev sur localhost:5173…) est une origine
        # étrangère — sans lui, son POST sans corps (pas de preflight) passait pour l'écran local, admin (revue 2026-10-25)
        default = {"http": 80, "https": 443, "ws": 80, "wss": 443}
        if (o.port or default.get(o.scheme)) != (request.url.port or default.get(request.url.scheme)):
            return False
        return o.hostname == (request.url.hostname or "") or _is_local(o.hostname or "")
    except Exception:
        return False


def allowed_http(request):
    """Verdict pour une requête HTTP. (request = starlette Request)"""
    method = request.method.upper()
    path = request.url.path
    if not host_ok(request.headers.get("host")):
        return False
    if path in OPEN_EXCHANGES:
        return _origin_ok(request)            # l'échange (invitation, code, ticket, transfert) EST l'authentification
    guarded = (method in ("POST", "PUT", "DELETE", "PATCH") or path in SENSITIVE_GET
               or path.startswith(SENSITIVE_GET_PREFIX))
    if not guarded:
        # audit 2026-11-04 (M4, décision du 2026-11-05) : un appareil JAMAIS APPAIRÉ ne lit plus rien de l'API — les
        # paroles, la setlist, les appareils et les personnes se lisaient sans jeton faute d'être dans une liste.
        # Le défaut s'inverse : seul PUBLIC_GET reste ouvert ; un appareil appairé (cookie) lit comme avant.
        if (method in ("GET", "HEAD") and path.startswith("/api/") and path not in PUBLIC_GET
                and not _is_local(request.client.host if request.client else "")):
            return _device_by_token(_presented(request)) is not None
        return True
    client = request.client.host if request.client else ""
    if _is_local(client):
        return _origin_ok(request)            # même en local, un Origin étranger est louche
    if not _origin_ok(request):
        return False
    dev = _device_by_token(_presented(request))
    if dev is None:
        return False
    if path in ADMIN_PATHS or path.startswith(ADMIN_PREFIX):
        return bool(dev.get("admin"))         # M-1 : les gestes SYSTÈME exigent la promotion
    if method != "GET" and (path in ADMIN_WRITES or path.startswith(ADMIN_WRITE_PREFIX)):
        return bool(dev.get("admin"))
    if method == "DELETE" and is_guest(dev) and not dev.get("admin"):
        return False                          # audit 2026-10-15 : un invité de 24 h n'efface pas les prises du groupe
    if (dev.get("kind") == "Phone" and (path in CONDUCTOR_PATHS or path.startswith("/api/backing/"))
            and path not in ("/api/backing/meta",) and not path.startswith("/api/backing/meta/")):
        return bool(dev.get("conductor") or dev.get("admin"))   # lot F : un téléphone ne lance le groupe que s'il est conductor
    return True


def allowed_ws(websocket):
    """Verdict pour le WebSocket /ws (starlette WebSocket)."""
    if not host_ok(websocket.headers.get("host")):
        return False
    # Audit 2026-10-15 : le navigateur ne protège PAS un WebSocket par la même origine — toute page ouverte
    # sur la machine du rack lisait l'état complet par ws://localhost:8770/ws. Même règle Origin que le HTTP,
    # local compris : l'app, le Companion et la fenêtre du rack sont servis par le bridge (même origine).
    if not _origin_ok(websocket):
        return False
    client = websocket.client.host if websocket.client else ""
    if _is_local(client):
        return True
    t = (websocket.query_params.get("token")
         or websocket.cookies.get("golem_token")
         or websocket.headers.get("x-golem-token") or "")
    return _valid(t)
