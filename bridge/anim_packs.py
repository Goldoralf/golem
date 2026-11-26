# SPDX-License-Identifier: GPL-3.0-or-later
"""Packs d'animations de tuiles (docs/anim-packs.md) — 20 effets par pack.

Les animations des tuiles Live (et des sections d'arrangement) vivent dans des PACKS :
  · `default` — les 20 effets livrés avec GoleM. Intégré au CSS de l'app, **immuable et
    indésinstallable** : c'est le socle sur lequel tout preset peut compter ;
  · les autres — installés UNIQUEMENT par golem.fm (job `anim-pack-install`), jamais à la
    main dans l'UI. Un pack = un dossier `library/anim-packs/<id>/` : `pack.json` + `pack.css`
    (+ ses images, en data: URI DANS le CSS — voir la validation).

POURQUOI UNE VALIDATION, ET PAS UNE CONFIANCE
Le CSS n'exécute pas de JS, mais dans un kiosk il peut : appeler le réseau (`url(https://…)`
= une fuite et une dépendance à la connexion, sur scène), recouvrir l'écran (`position:fixed`),
ou injecter du texte (`content`). Le rack accepte donc du CSS LIBRE mais BORNÉ, vérifié à
l'installation ET au service : chaque sélecteur doit vivre dans l'espace de nom du pack,
aucune ressource distante, aucun échappement de la tuile.

La valeur stockée dans un preset est `"<pack>/<effet>"` (`"fire"` seul = pack default, forme
historique conservée). Un pack absent ne casse rien : la tuile perd son animation, garde sa
couleur — dégradé jamais silencieux, le nom du pack manquant est rapporté par /api/anim-packs.
"""
import json
import os
import re
import xml.etree.ElementTree as ET

from . import config as C
from .golog import get

log = get("anim-packs")

PACKS_DIR = os.path.join(C.ROOT, "library", "anim-packs")
SCHEMA = 1
PACK_SIZE = 20                     # un pack = 20 tuiles, ni plus ni moins (« les packs vont par 20 »)
MAX_CSS = 512 * 1024               # 512 Ko de CSS par pack, images data: comprises

# le pack DEFAULT — l'ordre EST celui d'ANIM_STYLES (app/designer-model.js) ; « none » occupe
# la 1re case et n'a pas de CSS. Ces effets sont dans app/style.css, pas dans un fichier de pack.
DEFAULT = {
    "schema": SCHEMA, "id": "default", "name": "Default", "author": "golem",
    "version": 1, "builtin": True, "locked": True,
    "effects": [
        {"id": "", "name": "None"}, {"id": "pulse", "name": "Pulse"},
        {"id": "heartbeat", "name": "Heartbeat"}, {"id": "wave", "name": "Wave"},
        {"id": "sheen", "name": "Sheen"}, {"id": "scanner", "name": "Scanner"},
        {"id": "ember", "name": "Ember"}, {"id": "vu", "name": "VU reactive"},
        {"id": "ripple", "name": "Ripple (drop)"}, {"id": "rain", "name": "Rain"},
        {"id": "snow", "name": "Snow"}, {"id": "lightning", "name": "Lightning"},
        {"id": "strobe", "name": "Strobe"}, {"id": "monster", "name": "Monster"},
        {"id": "stars", "name": "Stars"}, {"id": "aurora", "name": "Aurora"},
        {"id": "fire", "name": "Fire"}, {"id": "smoke", "name": "Smoke"},
        {"id": "vortex", "name": "Vortex"}, {"id": "glitch", "name": "Glitch"},
    ],
}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")     # palette / effects[].color — finit dans un `style=` de l'app

# ── validation du CSS d'un pack ────────────────────────────────────────────────────────────
_BANNED = (
    (re.compile(r"@import", re.I), "@import — un pack est autonome, il ne charge rien"),
    (re.compile(r"expression\s*\(", re.I), "expression() — code déguisé"),
    (re.compile(r"javascript\s*:", re.I), "javascript: — code déguisé"),
    (re.compile(r"position\s*:\s*(fixed|sticky)", re.I),
     "position:fixed/sticky — une animation ne sort JAMAIS de sa tuile"),
    (re.compile(r"@(font-face|page)", re.I), "@font-face/@page — hors du périmètre d'un pack"),
    # audit 2026-10-15 : ces fonctions chargent une image SANS passer par url() — `image-set("https://…")`
    # appelait le réseau en contournant le contrôle des url() ci-dessous
    (re.compile(r"(?<![a-z-])(-webkit-)?(image-set|image|cross-fade|element|src)\s*\(", re.I),
     "image-set()/image()/src() — une image ne se charge que par url(data:…)"),
)
_CSS_ESC = re.compile(r"\\([0-9a-fA-F]{1,6})\s?")


def _unescape(css):
    """Les échappements CSS décodés : `\\75rl(` EST `url(` pour le navigateur, il doit l'être pour le contrôle."""
    def one(m):
        try:
            return chr(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return "\ufffd"
    return _CSS_ESC.sub(one, css).replace("\\", "")
# ⚠ PAS D'EXPRESSION RÉGULIÈRE POUR LES url() — piège signalé par l'agent golem.fm le
# 2026-07-31, et VÉRIFIÉ : le motif `url\(\s*['"]?([^'")]+)` coupe une data: URI au premier
# « ) » qu'elle contient (une SVG en porte : `rgba(…)`, `filter='url(%23n)'`), puis reprend le
# balayage DANS l'image et prend `url(%23n)` pour une seconde URL, distante. Un pack
# parfaitement valide était refusé. On lit donc le jeton url() à la main, et on ne regarde
# JAMAIS l'intérieur d'une data:.
def _urls(css):
    """Rend (url, fin) pour chaque jeton url(...) — en sautant le contenu des data: URI."""
    i, n = 0, len(css)
    low = css.lower()
    while True:
        j = low.find("url(", i)
        if j < 0:
            return
        k = j + 4
        while k < n and css[k] in " \t\r\n":
            k += 1
        if k < n and css[k] in "'\"":
            q = css[k]; k += 1; st = k
            while k < n and css[k] != q:
                k += 2 if css[k] == "\\" else 1
            u, i = css[st:k], k + 1
        else:
            st, depth = k, 1
            while k < n and depth:
                depth += (css[k] == "(") - (css[k] == ")")
                k += 1
            u, i = css[st:k - 1], k
        yield u.strip(), i
# un sélecteur de pack DOIT commencer par sa classe d'espace de nom (les at-rules @keyframes
# et @media sont acceptées telles quelles — elles ne ciblent rien par elles-mêmes)


# Propriétés qui forcent un REPEINT (ou pire, un layout) à chaque image. Mesuré le 2026-08-01
# sur une vraie fenêtre Chrome, 24 tuiles, 10 s : 0,009 s de thread principal en transform+
# opacity contre 0,99 s en background-position+box-shadow+filter — 106×, soit ~10 % d'un cœur
# EN CONTINU. Sur un rack qui fait tourner un moteur audio temps réel à côté, ce n'est pas une
# animation moins fluide, ce sont des xruns (cf. docs/anim-packs.md, et la leçon JSFX).
# AVERTISSEMENT, PAS REFUS : le pack `default` livré avec le rack les emploie NEUF fois
# (6 background-position, 2 box-shadow, 1 filter). On ne refuse pas aux autres ce qu'on
# s'autorise — la règle deviendra un refus le jour où les 20 effets maison seront corrigés.
_REPAINT = ("background-position", "background-size", "box-shadow", "filter", "backdrop-filter",
            "width", "height", "top", "left", "right", "bottom", "inset", "margin", "padding",
            "border-radius", "border-width", "font-size")
_KF_RE = re.compile(r"@(?:-webkit-)?keyframes\s+([a-z0-9_-]+)", re.I)


def _perf_warnings(css):
    """Les propriétés coûteuses animées, avec leur @keyframes. Informatif : golem.fm les montre
    à l'auteur du pack, personne n'est bloqué."""
    out = []
    for m in _KF_RE.finditer(css):
        i, depth = css.find("{", m.end()), 0
        if i < 0:
            continue
        j = i
        while j < len(css):
            depth += (css[j] == "{") - (css[j] == "}")
            j += 1
            if not depth:
                break
        bad = sorted({p for p in re.findall(r"([a-z-]+)\s*:", css[i:j]) if p in _REPAINT})
        if bad:
            out.append(f"@keyframes {m.group(1)} anime {', '.join(bad)} — repeint à chaque image ; "
                       "préférer transform/opacity (composités), le rack tient un moteur audio à côté")
    return out


def _check_css(css, pack_id):
    """Renvoie (ok, [erreurs], [avertissements]). Refuse plutôt que d'assainir : un pack qui ne
    respecte pas l'espace de nom est un pack mal construit, et le dire est plus utile que le
    réparer. Les avertissements, eux, ne bloquent rien."""
    errs = []
    if len(css.encode()) > MAX_CSS:
        errs.append(f"CSS de {len(css.encode()) // 1024} Ko — maximum {MAX_CSS // 1024} Ko")
    # ⚠ LES COMMENTAIRES NE SONT PAS DU CSS (2026-09-15) : le premier pack poussé depuis le studio
    # golem.fm commençait par « /* <nom du groupe> — 20 effets · ambiance … */ » et le balayage des
    # têtes de blocs a pris ce commentaire pour un sélecteur hors espace de nom — pack refusé, job en
    # erreur, jamais reproposé. On retire les `/* … */` AVANT tout contrôle : un commentaire ne
    # s'exécute pas, ne sélectionne rien, et un pack qui se signe n'est pas un pack mal construit.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = _unescape(css)
    for rx, why in _BANNED:
        if rx.search(css):
            errs.append(why)
    for u, _end in _urls(css):
        if not u.lower().startswith("data:"):
            errs.append(f"url({u[:40]}…) — seules les data: URI sont permises (le rack joue hors ligne)")
            break
    ns = f".anim-{pack_id}-"
    # ⚠ balayage CONSCIENT DE LA PROFONDEUR : un découpage naïf sur « } » prend les étapes
    # « 50% { } » d'un @keyframes pour des sélecteurs (mon 1er jet refusait tous les packs
    # valides). On ne vérifie donc QUE les têtes de blocs qui ciblent vraiment des éléments :
    # niveau 0, et l'intérieur d'un @media/@supports. L'intérieur d'un @keyframes est sauté.
    # `decl` = on est DANS le corps d'une règle (entre le « { » d'un sélecteur et son « } ») : ce qui
    # s'y accumule est de la déclaration, pas une tête — le garde-fou des 400 c. ne s'y applique pas.
    # ⚠ 2026-09-15, job #58 : le premier pack du studio golem.fm portait des dégradés et des data:
    # URI SVG de 400+ caractères dans ses déclarations, et le garde-fou, qui comptait TOUT depuis
    # le dernier « { », les prenait pour une « tête de bloc démesurée ». Le pack Default n'en a
    # pas d'aussi longs : le trou ne s'est vu qu'au premier pack venu d'ailleurs.
    depth, head, skip_until, decl = 0, [], None, False
    for ch in css:
        if ch == "{":
            h = "".join(head).strip()
            head = []
            at = h.lower().startswith("@")
            if skip_until is None:
                if at and (h.lower().startswith("@keyframes") or h.lower().startswith("@-webkit-keyframes")):
                    skip_until = depth           # tout l'intérieur est de la timeline, pas des sélecteurs
                elif at:
                    pass                          # @media/@supports : ses enfants seront vérifiés
                else:
                    for one in h.split(","):
                        one = one.strip()
                        if one and not one.startswith(ns):
                            errs.append(f"sélecteur « {one[:48]} » hors de l'espace de nom {ns}*")
                            break
                        # `~` et `+` visent les VOISINS de la tuile : hors d'elle, donc hors du pack
                        # (les parenthèses retirées d'abord : `:nth-child(2n+1)` est permis)
                        if re.search(r"[~+]", re.sub(r"\([^)]*\)", "", one)):
                            errs.append(f"sélecteur « {one[:48]} » — les combinateurs ~ et + sortent de la tuile")
                            break
                    if errs:
                        break
                    decl = True                   # un sélecteur ouvre des DÉCLARATIONS
            depth += 1
        elif ch == "}":
            depth -= 1
            head = []
            decl = False
            if skip_until is not None and depth <= skip_until:
                skip_until = None
        else:
            head.append(ch)
            # une TÊTE de 1 500 c. n'est pas un sélecteur (du binaire, une feuille cassée) ; 400 refusait une
            # liste légitime de vingt « .anim-u1-x::before, .anim-u1-x::after » sous @media (645 c., job #58)
            if not decl and skip_until is None and len(head) > 1500:
                errs.append("CSS illisible (tête de bloc démesurée)")
                break
    return (not errs), errs, _perf_warnings(css)


# ── L'IMAGE FIXE D'UN EFFET (docs/anim-packs.md §8, 2026-11-26) ─────────────────────────────────
# Quand les cases du Live sont figées, chaque effet montre SON image, dessinée pour être immobile. Un SVG en chaîne,
# fond transparent, `currentColor` = la couleur de la case. Golem.fm valide les packs AVANT de les distribuer avec
# la MÊME liste (backend/app/services/anim_packs.py) : toute règle ajoutée ici lui est envoyée, sinon un pack accepté
# là-bas serait refusé en entier sur scène. Refuser, jamais assainir.
STILL_MAX = 16 * 1024                       # octets UTF-8 de la chaîne
# éléments permis : du dessin seul. Ni filtre (un flou repeint à chaque geste coûte sur un rack à 2 cœurs), ni image
# (un bitmap ferait sauter le budget et flouterait), ni style, ni script, ni foreignObject, ni animation SMIL.
STILL_ELEMENTS = frozenset((
    "svg", "g", "defs", "symbol", "use", "title", "desc",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan",
    "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask",
))
_TAG_RE = re.compile(r"<\s*(/?)\s*([A-Za-z_][\w:.-]*)([^>]*)>", re.S)
_ATTR_RE = re.compile(r"([A-Za-z_][\w:.-]*)\s*=\s*(\"[^\"]*\"|'[^']*')", re.S)
_ENT_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});)")
_STILL_BANNED = ("animation", "@keyframes", "@import", "javascript:", "data:", "<script", "foreignobject")


def check_still(svg):
    """L'image fixe d'un effet : (ok, raison). Les règles, dans l'ordre (golem.fm les applique telles quelles) :
    chaîne ; ≤ STILL_MAX octets UTF-8 ; commence par `<svg` et finit par `</svg>` (espaces autour ignorés) ; ni `<!`
    (DOCTYPE, ENTITY, CDATA, commentaire) ni `<?` (prologue XML) ; seules les entités &amp; &lt; &gt; &quot; &apos; et
    numériques ; aucun des mots de _STILL_BANNED (casse ignorée) ; chaque élément dans STILL_ELEMENTS (casse exacte) ;
    aucun attribut `on…` ; `href`/`xlink:href` = `#id` ; chaque `url(…)` = `url(#id)` ; XML bien formé."""
    if not isinstance(svg, str):
        return False, "still must be an SVG string"
    if len(svg.encode("utf-8")) > STILL_MAX:
        return False, f"still of {len(svg.encode('utf-8'))} bytes, maximum {STILL_MAX}"
    s = svg.strip()
    if not (s.startswith("<svg") and s.endswith("</svg>")):
        return False, "still must start with <svg and end with </svg>"
    if "<!" in s or "<?" in s:
        return False, "no <!…> or <?…> in a still (DOCTYPE, ENTITY, CDATA, comment, XML prologue)"
    if _ENT_RE.search(s):
        return False, "only &amp; &lt; &gt; &quot; &apos; and numeric entities are allowed"
    low = s.lower()
    for word in _STILL_BANNED:
        if word in low:
            return False, f"« {word} » is not allowed in a still (no motion, nothing loaded, no code)"
    for _close, name, rest in _TAG_RE.findall(s):
        if name not in STILL_ELEMENTS:
            return False, f"element <{name}> is not allowed in a still"
        for attr, val in _ATTR_RE.findall(rest):
            v = val[1:-1].strip()
            if attr.lower().startswith("on"):
                return False, f"attribute {attr} is not allowed in a still"
            if attr in ("href", "xlink:href") and not v.startswith("#"):
                return False, f"{attr} must point inside the still (#id)"
    for m in re.finditer(r"url\(\s*['\"]?([^)'\"]*)", s, re.I):
        if not m.group(1).strip().startswith("#"):
            return False, "url() must point inside the still (#id)"
    try:
        ET.fromstring(s)                    # sans DOCTYPE (refusé plus haut) : aucune entité externe possible
    except ET.ParseError as e:
        return False, f"still is not well-formed XML ({e})"
    return True, ""


_STILLS = {"mtime": None, "stills": {}}
STILLS_FILE = os.path.join(C.ROOT, "library", "catalog", "anim-stills.json")


def default_stills():
    """Les images fixes du pack default (library/catalog/anim-stills.json, écrit par tools/make-anim-stills.py)."""
    try:
        mt = os.path.getmtime(STILLS_FILE)
    except OSError:
        return {}
    if _STILLS["mtime"] != mt:
        try:
            with open(STILLS_FILE, encoding="utf-8") as f:
                doc = json.load(f)
            st = doc.get("stills") if isinstance(doc, dict) else None
            _STILLS.update(mtime=mt, stills={k: v for k, v in (st or {}).items() if check_still(v)[0]})
        except (OSError, ValueError):
            _STILLS.update(mtime=mt, stills={})
    return _STILLS["stills"]


def _default_pack():
    """Le pack default, ses effets portant leur image fixe."""
    st = default_stills()
    d = dict(DEFAULT)
    d["effects"] = [({**e, "still": st[e["id"]]} if e["id"] in st else dict(e)) for e in DEFAULT["effects"]]
    return d


# ── lecture des packs installés ────────────────────────────────────────────────────────────
def _read(pid):
    d = os.path.join(PACKS_DIR, pid)
    try:
        with open(os.path.join(d, "pack.json")) as f:
            doc = json.load(f)
    except Exception:
        return None
    if not isinstance(doc, dict) or doc.get("id") != pid:
        return None
    doc["builtin"] = False
    doc["locked"] = False
    doc["css_bytes"] = os.path.getsize(os.path.join(d, "pack.css")) \
        if os.path.exists(os.path.join(d, "pack.css")) else 0
    return doc


def list_packs():
    """default TOUJOURS en tête (socle indésinstallable), puis les packs installés, triés."""
    out = [_default_pack()]
    try:
        for pid in sorted(os.listdir(PACKS_DIR)):
            if pid == "default" or not _ID_RE.match(pid):
                continue
            doc = _read(pid)
            if doc:
                out.append(doc)
    except FileNotFoundError:
        pass
    return out


def pack_css(pid):
    """Le CSS d'un pack, re-vérifié AU SERVICE (un fichier peut être remplacé après coup)."""
    if pid == "default" or not _ID_RE.match(pid or ""):
        return None
    p = os.path.join(PACKS_DIR, pid, "pack.css")
    try:
        with open(p) as f:
            css = f.read()
    except Exception:
        return None
    ok, errs, _warn = _check_css(css, pid)
    if not ok:
        log.warning(f"{pid}/pack.css REFUSÉ au service : {errs[0]}")
        return None
    return css


def install(doc, css):
    """Installe un pack (appelé par le job golem.fm). Valide TOUT avant d'écrire quoi que ce
    soit : un pack à moitié posé serait pire que pas de pack."""
    errs = []
    pid = (doc or {}).get("id") or ""
    if not _ID_RE.match(pid):
        errs.append("id invalide (a-z0-9-, 2 à 32 caractères)")
    if pid == "default":
        errs.append("« default » est le socle livré — il ne s'installe ni ne se remplace")
    if (doc or {}).get("schema") != SCHEMA:
        errs.append(f"schema {(doc or {}).get('schema')} — ce rack lit le schema {SCHEMA}")
    pal = (doc or {}).get("palette")
    if pal is not None:
        if not isinstance(pal, dict):
            errs.append("palette doit être un objet {primary, secondary, colors[]}")
        else:
            for k, v in pal.items():
                vals = v if isinstance(v, list) else [v]
                if any(not _COLOR_RE.match(str(x)) for x in vals):
                    errs.append(f"palette.{k} : couleurs #rrggbb attendues")
                    break
    effects = (doc or {}).get("effects")
    if not isinstance(effects, list) or len(effects) != PACK_SIZE:
        errs.append(f"{len(effects) if isinstance(effects, list) else 0} effets — il en faut exactement {PACK_SIZE}")
    else:
        for e in effects:
            if not isinstance(e, dict) or not _ID_RE.match(str(e.get("id") or "")) or not e.get("name"):
                errs.append(f"effet invalide : {str(e)[:40]} (id a-z0-9- + name requis)")
            elif e.get("color") is not None and not _COLOR_RE.match(str(e.get("color"))):
                # une couleur finit dans un attribut style de l'app : #rrggbb ou rien (2026-09-15)
                errs.append(f"effet « {e.get('id')} » : color doit être #rrggbb ({str(e.get('color'))[:20]!r})")
                break
            elif e.get("still") is not None:
                ok_s, why = check_still(e.get("still"))
                if not ok_s:
                    errs.append(f"effect « {e.get('id')} »: {why}")
                    break
    if not errs:
        ok, cerrs, warns = _check_css(css or "", pid)
        errs += cerrs
        # §8.2 : un effet sans image fixe ne montre que sa couleur quand les cases sont figées
        warns = list(warns) + [f"effect « {e.get('id')} » has no still image: a still tile shows only its colour"
                               for e in effects if not e.get("still")]
    if errs:
        return {"ok": False, "errors": errs}
    d = os.path.join(PACKS_DIR, pid)
    os.makedirs(d, exist_ok=True)
    from . import store
    store._write_json_atomic(os.path.join(d, "pack.json"), {**doc, "builtin": False}, indent=1)
    tmp = os.path.join(d, "pack.css.tmp")
    with open(tmp, "w") as f:
        f.write(css or "")
    os.replace(tmp, os.path.join(d, "pack.css"))
    return {"ok": True, "id": pid, "effects": len(effects), "warnings": warns}


def remove(pid):
    """Désinstalle — sauf `default`. Les presets qui s'y référaient perdent l'animation, pas
    la couleur (§ dégradé jamais silencieux)."""
    if pid == "default":
        return {"ok": False, "error": "the default pack cannot be removed"}
    d = os.path.join(PACKS_DIR, pid)
    if not (_ID_RE.match(pid or "") and os.path.isdir(d)):
        return {"ok": False, "error": "unknown pack"}
    import shutil
    shutil.rmtree(d)
    return {"ok": True}
