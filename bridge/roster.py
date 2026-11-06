# SPDX-License-Identifier: GPL-3.0-or-later
"""Le roster en cache — `config/.band.json` — et sa RÉCONCILIATION avec golem.fm.

Contrat : docs/identity.md §3 et docs/private/exchanges/message-maestrium-espaces.md (« un rack, N espaces »,
2026-09-01). Le serveur sert MULTI-ESPACES depuis le 2026-09-06 (`GET /api/ext/band`) : tous
les espaces dont le propriétaire du jeton est membre, l'espace personnel en tête. C'est le
prérequis du lot B — sans lui, aucun tag `b_…` venu du web n'est reconnu ici, et rien ne monte.

Trois règles font tout :

  - **La synchro remplace le CATALOGUE, jamais le CHOIX de la salle.** `bands[]` et les
    rosters viennent du serveur ; le groupe courant est préservé PAR SON ID. Basculer d'espace
    est un geste local (`POST /api/band/current`) ; une synchro qui le réécrirait ferait
    exactement ce que « jamais d'auto-bascule » interdit (message « espaces » §3).
  - ⚠ **Les champs de transition `band` et `people` à la RACINE du payload sont IGNORÉS.**
    Le serveur les sert encore pour les racks d'avant la migration — ils reprennent `default`,
    c'est-à-dire le rattachement de l'APPAREIL. Les lire ici ramènerait ce rattachement dans
    la salle à chaque synchro : l'auto-bascule par la petite porte. On ne lit que `bands[]`,
    `default` et `synced`.
  - **Le rack sélectionne, il ne crée jamais.** Un espace absent du cache n'existe pas pour
    lui ; un courant disparu du roster fait un repli DÉTERMINISTE (`default`, sinon l'unique
    `personal`), journalisé — jamais un silence.

`people` à la racine du CACHE reste écrit, mais c'est NOUS qui l'écrivons : c'est le miroir du
roster de l'espace courant, ce que lisent déjà l'input map (la personne d'une entrée) et
l'écran. Il suit donc la bascule, et ne vient jamais du serveur.
"""
import json
import os
import re
import time

from . import config as C
from .golog import get

log = get("roster")

FILE = os.path.join(C.CONFIG_DIR, ".band.json")


_DEFAULT_FILE = FILE


def _file():
    """Le chemin du cache, RELU à chaque appel. Figé à l'import, il échappait aux tests : le faux roster
    d'un test vivait dans son dossier temporaire et `person()` lisait quand même celui de la machine — un
    test qui passe SEUL et tombe dans la suite (vécu le 2026-09-16). On suit `C.CONFIG_DIR`, sauf si
    quelqu'un a explicitement déplacé `FILE` (test_mode_band le fait), auquel cas c'est lui qui gagne."""
    return FILE if FILE != _DEFAULT_FILE else os.path.join(C.CONFIG_DIR, ".band.json")

_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


# ── le fichier ─────────────────────────────────────────────────────────────────────────────
def read():
    """Le cache, ou {} s'il n'existe pas / est illisible. Jamais d'exception : un roster
    absent n'est pas une panne, c'est un rack qui n'a pas encore de groupe."""
    try:
        d = json.load(open(_file()))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def write(d):
    """Écriture ATOMIQUE (même règle que partout ailleurs dans config/ : un `.tmp` puis un
    `os.replace`). Une coupure de courant pendant une synchro ne doit pas laisser un roster
    tronqué — le rack repartirait sans savoir à quel groupe appartiennent ses prises."""
    path = _file()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return d


def norm(s):
    """Casse, tirets, espaces et accents de frappe écrasés — pour APPARIER, jamais pour
    router. Le routage se fait sur l'id opaque, toujours (`b_haw6vqzh5u`)."""
    return _NOT_ALNUM.sub("", (s or "").strip().lower())


# ── la réconciliation (pure : ni disque ni réseau, donc testable) ──────────────────────────
def _entry(b):
    """Une entrée de `bands[]` telle qu'on la GARDE : l'id opaque, le libellé, le slug, le `kind`
    DÉCLARÉ par le serveur — et SES MEMBRES. `source: "cache"` dit au serveur, quand un tag remonte,
    que ce tag vient d'un roster synchronisé et non d'un seed frappé à la main.

    ⚠ LES MEMBRES DE CHAQUE ESPACE SONT GARDÉS (2026-09-16, docs/devices-people.md §8). Avant, seul
    l'espace COURANT gardait les siens : basculer hors ligne vers un autre espace montrait les membres
    du précédent — mesuré, l'espace perso du mainteneur (lui seul) s'affichait sous « le groupe ». Or la
    bascule hors ligne est exactement ce que le multi-espaces promet (docs/identity.md §3). C'est un
    cache : quelques dizaines de lignes par groupe, rien à côté d'un preset."""
    return {"id": b.get("id"), "name": b.get("name") or b.get("id"),
            **({"slug": b["slug"]} if b.get("slug") else {}),
            **({"kind": b["kind"]} if b.get("kind") else {}),
            "source": "cache", "people": _people(b)}


#: Ce qu'on garde d'une personne : l'identité, ses instruments, ses DROITS dans cet espace
#: (owner | admin | member, servis depuis le 2026-09-16) et ses RÉGLAGES personnels, plats et
#: opaques — tout ce qu'on ne comprend pas est gardé sans être lu (contrat §8.1).
PERSON_KEYS = ("id", "name", "roles", "gear", "rights", "prefs", "pending", "avatar")
# `avatar` (2026-10-03, docs/private/exchanges/message-maestrium-avatars.md) : l'URL de la photo du membre sur golem.fm —
# chemin relatif au serveur (`/api/ext/…`, lu avec le jeton du rack) ou URL absolue. Le rack la TÉLÉCHARGE
# à la synchro (config/avatars/) : sur scène il n'y a pas d'Internet, la photo doit déjà être là.


def _people(b):
    return [{k: v for k, v in p.items() if k in PERSON_KEYS}
            for p in (b.get("people") or []) if isinstance(p, dict) and p.get("id")]


def prefs(pid, cache=None):
    """Les réglages personnels d'une personne (contrat §8.1) : plats, opaques, `{}` si rien. Ils
    appartiennent à la PERSONNE, donc ils sont les mêmes dans chaque espace — on prend le premier
    non vide, au cas où un espace aurait été servi sans."""
    d = cache if cache is not None else read()
    p = person(pid, d)
    if p.get("prefs"):
        return dict(p["prefs"])
    for b in d.get("bands") or []:
        for q in (b.get("people") or []) if isinstance(b, dict) else []:
            if isinstance(q, dict) and q.get("id") == pid and q.get("prefs"):
                return dict(q["prefs"])
    return {}


def person(pid, cache=None):
    """La fiche d'une personne : dans l'espace COURANT d'abord, sinon dans n'importe quel espace connu
    (un téléphone appairé pour un autre groupe reste un appareil de cette personne). {} si inconnue."""
    if not pid or str(pid).startswith("guest:"):
        return {}
    d = cache if cache is not None else read()
    for p in d.get("people") or []:
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    for b in d.get("bands") or []:
        for p in (b.get("people") or []) if isinstance(b, dict) else []:
            if isinstance(p, dict) and p.get("id") == pid:
                return p
    return {}


def _seed_match(cur, bands):
    """L'id du SEED (`source: "local-temporary"`, docs/identity.md §3) a été frappé à la main —
    « night-shift » — là où le serveur grave un `public_id` opaque — « b_haw6vqzh5u ». Les 30
    prises déjà taguées portent donc un id qui n'existe pas côté serveur : sans ré-adressage
    elles ne monteraient JAMAIS, et le seul symptôme serait un 404 que personne ne lit.

    La signature, validée des deux côtés (message-golem-ranger-prises-2.md, question 3) :
    `source == "local-temporary"` ET l'id du seed correspond au slug (ou au nom) d'un espace
    servi, comparaison NORMALISÉE — un seed frappé « night-shift » face à un slug
    « nightshift » ne doit pas coûter 30 prises pour un tiret.

    ⚠ Une seule correspondance, sinon RIEN : à deux espaces qui matchent, l'ambiguïté est
    réelle et le tap redevient le bon geste (leur ceinture du 2026-09-02).
    ⚠ Et c'est une MIGRATION, pas une règle : la doctrine « on route par id, jamais par slug »
    reste entière. Cette comparaison-ci meurt avec le dernier seed `local-temporary`.
    """
    if (cur.get("source") or "") != "local-temporary" or not cur.get("id"):
        return None
    key, name = norm(cur["id"]), norm(cur.get("name"))
    hits = [b for b in bands
            if norm(b.get("slug")) == key or norm(b.get("id")) == key
            or (name and norm(b.get("name")) == name)]
    return hits[0] if len(hits) == 1 else None


def reconcile(payload, cache):
    """(payload serveur, cache actuel) -> (nouveau cache, rapport). PURE : pas de disque, pas
    de réseau, pas de ré-adressage de prises — l'appelant s'en charge d'après le rapport.

    Rapport : `{bands, current, was, readdress: {from, to}|None, fallback: str|None}`.
    """
    served = [b for b in (payload.get("bands") or []) if isinstance(b, dict) and b.get("id")]
    entries = [_entry(b) for b in served]
    by_id = {b["id"]: b for b in served}
    known = {e["id"]: e for e in entries}

    cur = cache.get("band") or {}
    had_key = "band" in cache                     # « aucun groupe » CHOISI vs jamais posé
    was = cur.get("id")
    default = payload.get("default")
    personal = next((e["id"] for e in entries if (by_id[e["id"]].get("kind") == "personal")), None)
    readdress, fallback = None, None

    if was and was in known:                      # le cas normal : on ne touche pas au courant
        target = was
    elif (hit := _seed_match(cur, served)):       # le seed d'avant la synchro -> son vrai id
        target = hit["id"]
        readdress = {"from": was, "to": target}
    elif was:                                     # l'espace courant a disparu du roster
        target = default if default in known else personal
        fallback = "default" if target == default else ("personal" if target else None)
    elif had_key and cache.get("band") is None:
        target = None                             # « Aucun » est un choix : on le respecte
    else:
        target = default if default in known else personal   # premier appairage

    d = dict(cache)
    d["bands"] = entries
    d["band"] = ({**known[target], "synced": payload.get("synced") or _now()}
                 if target in known else None)
    d["people"] = _people(by_id[target]) if target in by_id else []
    d["synced"] = payload.get("synced") or _now()
    return d, {"bands": len(entries), "current": target, "was": was,
               "readdress": readdress, "fallback": fallback}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def set_current(bid):
    """Change l'espace COURANT — parmi ceux que le rack connaît, jamais un nouveau.
    Rend `(True, band)` ou `(False, raison)`.

    ⚠ LE RACK SÉLECTIONNE, IL NE CRÉE PAS. Il n'y a pas de login ici : aucune autorité pour
    inventer un espace. Créer, inviter, exclure sont des gestes de golem.fm ; le rack choisit
    dans un cache et fonctionne hors ligne avec (docs/identity.md).

    `bid = None` est un CHOIX légitime (« Aucun ») : les prises attendent alors sur le rack,
    et le disent. Deux appelants : la puce ◈ de la topbar, et un mode qui déclare son espace
    (`mode.band`) — le second passe par ici pour qu'il n'existe qu'un seul chemin de bascule.
    """
    d = read()
    known = {b.get("id"): b for b in (d.get("bands") or []) if isinstance(b, dict) and b.get("id")}
    cur = d.get("band") or {}
    if cur.get("id"):
        known.setdefault(cur["id"], {"id": cur["id"], "name": cur.get("name") or cur["id"]})
    if bid is None:
        d["band"], d["people"] = None, []
    elif bid in known:
        k = known[bid]
        d["band"] = {**cur, **k,
                     "source": k.get("source") or (cur.get("source") if cur.get("id") == bid
                                                   else None) or "cache"}
        # ⚠ LE MIROIR SUIT L'ESPACE CHOISI, MÊME VIDE. Le repli « sinon les membres d'avant » gardait
        # le roster du groupe QUITTÉ quand la cible n'en avait pas — hors ligne, le groupe
        # s'affichait avec le seul membre de l'espace perso (mesuré le 2026-09-16). Il ne sert plus
        # qu'aux caches écrits AVANT que `bands[]` ne porte ses membres : sans la clé, on ne sait pas ;
        # avec une clé vide, on sait que l'espace n'a personne, et on le dit.
        d["people"] = _people(k) if "people" in k else (d.get("people") or [])
    else:
        return False, f"espace inconnu de ce rack : {bid}"
    # ⚠ ON PERSISTE LA LISTE. Elle était seulement DÉRIVÉE du courant à la lecture : passer à
    # « aucun » l'effaçait, et on ne pouvait plus jamais revenir — un aller sans retour, trouvé
    # au premier essai. La liste est un CACHE du rack ; le courant n'en est qu'un pointeur.
    # ⚠ `source` VOYAGE AVEC CHAQUE ENTRÉE : sans lui, quitter un espace puis y revenir
    # promouvait son tag de `local-temporary` à `cache` — le rack aurait dit au serveur que le
    # tag vient d'un roster synchronisé alors qu'il vient d'un seed.
    d["bands"] = [{k: v for k, v in b.items() if k in ("id", "name", "slug", "kind", "source", "people")}
                  for b in known.values() if b.get("id")]
    write(d)
    return True, d["band"]


# ── la synchro (effets : réseau, disque, prises) ───────────────────────────────────────────
# ── les PHOTOS des membres (2026-10-03) ───────────────────────────────────────────────────────────
_AV_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def _avatar_dir():
    return os.path.join(C.CONFIG_DIR, "avatars")


def avatar_file(pid):
    """Le fichier de la photo en cache de `pid`, ou None (pas de photo sur golem.fm, ou jamais tirée)."""
    import glob as _glob
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(pid))
    hits = _glob.glob(os.path.join(_avatar_dir(), safe + ".*"))
    return next((h for h in hits if not h.endswith(".json")), None)


def fetch_avatars(d):
    """Télécharge les photos annoncées par golem.fm (`people[].avatar`) — une fois par URL : l'index garde
    l'URL de chaque fichier, une photo inchangée ne repart pas. Ne lève jamais : une photo manquante
    laisse l'initiale, rien d'autre ne dépend d'elle."""
    import urllib.request
    from . import golemfm
    base, token = golemfm._cfg()
    idx_path = os.path.join(_avatar_dir(), "index.json")
    try:
        idx = json.load(open(idx_path, encoding="utf-8"))
    except Exception:
        idx = {}
    people = {}
    for b in d.get("bands") or []:
        for p in (b.get("people") or []) if isinstance(b, dict) else []:
            if isinstance(p, dict) and p.get("id"):
                people[p["id"]] = p
    changed = False
    for pid, p in people.items():
        url = str(p.get("avatar") or "").strip()
        if not url:
            continue
        if idx.get(pid) == url and avatar_file(pid):
            continue
        try:
            if url.startswith("/"):                              # chemin golem.fm : avec le jeton du rack
                st, blob = golemfm._req(url, token=token, raw=True)
                ctype = "image/jpeg" if blob[:3] == b"\xff\xd8\xff" else "image/png" if blob[:4] == b"\x89PNG" \
                    else "image/webp" if blob[8:12] == b"WEBP" else "image/gif" if blob[:3] == b"GIF" else ""
            else:
                with urllib.request.urlopen(url, timeout=10) as r:
                    st, blob, ctype = r.status, r.read(), r.headers.get_content_type()
            if st != 200 or ctype not in _AV_EXT or not blob or len(blob) > 2_000_000:
                log.warning(f"photo de {pid} ignorée ({st}, {ctype or 'type inconnu'}, {len(blob or b'')} o)")
                continue
            os.makedirs(_avatar_dir(), exist_ok=True)
            old = avatar_file(pid)
            if old:
                os.remove(old)
            safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(pid))
            with open(os.path.join(_avatar_dir(), safe + _AV_EXT[ctype]), "wb") as f:
                f.write(blob)
            idx[pid] = url
            changed = True
        except Exception as e:
            log.warning(f"photo de {pid} non téléchargée : {e}")
    if changed:
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(idx, f, indent=1)


def sync():
    """`GET /api/ext/band` -> réconciliation -> écriture -> ré-adressage éventuel des prises.

    Ne lève jamais : hors ligne, le cache fait foi (c'est tout l'intérêt d'un cache dans une
    salle de répète derrière la box de quelqu'un d'autre). Rend un rapport, toujours.
    """
    from . import golemfm
    st, data = golemfm.band_fetch()
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "status": st, "error": data if isinstance(data, str) else None}

    cache = read()
    d, rep = reconcile(data, cache)
    write(d)
    fetch_avatars(d)

    if rep["readdress"]:
        from . import takes
        tag = {k: v for k, v in (d.get("band") or {}).items()
               if k in ("id", "name", "source")}
        n = takes.readdress(rep["readdress"]["from"], tag)
        rep["readdress"]["takes"] = n
        log.info(f"seed ré-adressé : {rep['readdress']['from']} -> {tag['id']} "
                 f"({n} prise(s) ré-adressée(s), provenance gardée dans band_history)")
    if rep["fallback"]:
        log.warning(f"espace courant « {rep['was']} » absent du roster -> repli "
                    f"{rep['fallback']} ({rep['current']})")
    log.info(f"roster synchronisé : {rep['bands']} espace(s), courant {rep['current']}")
    return {"ok": True, **rep}
