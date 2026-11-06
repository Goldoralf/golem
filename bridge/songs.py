# SPDX-License-Identifier: GPL-3.0-or-later
"""Le RÉPERTOIRE du groupe — `songs/<id>.golem` (docs/songs.md, lot 1 ; docs/golem-format.md §2).

⚠ LA CHANSON EST UN FICHIER `.golem` (plan-song-sharing.md lot 1, 2026-10-08) : le format natif,
comme le `.rpp` pour Reaper — pas d'étape d'export. Elle s'y range ainsi :
  - `golem.json` : l'identité, là où le format la met (`id`, `title`, `artist`, `kind`) ; et sous la clé
    `repertoire` ce qui n'appartient qu'à la synchro du répertoire (`rev`, `band`, `song_slug`, `born`,
    `pulled_at`). PAS au premier niveau : le format y réserve `rev` à la RÉVISION SIGNÉE d'un album
    (golem-format.md §11) — même nom, autre nature, le piège de CLAUDE.md. Un autre lecteur l'ignore (§13).
  - `sheet.json` : la fiche (golem-format.md §9, « même forme que la fiche »).
Les anciens `songs/<id>.json` sont MIGRÉS au premier accès (`_migrate`), puis rangés dans
`songs/.json-migrated/` — jamais effacés. L'API de ce module ne change pas.

Une chanson n'existait que DANS une setlist, et mourait avec elle : deux setlists qui jouaient le
même morceau étaient deux lignes qui s'ignoraient, et une chanson qu'on répète sans l'avoir
programmée n'existait nulle part. Ce module lui donne un fichier.

Trois règles qui tiennent tout :

1. **UN ID NAÎT AVEC LA CHANSON ET NE CHANGE JAMAIS** (docs/songs.md §9.3). `bs:<n>` si elle naît
   chez golem.fm, `rs:<uuid4 hex>` si elle naît sur un rack — golem.fm garde ce dernier
   (`BandSong.rack_id`) et le renvoie tel quel. Opaques tous les deux, recopiés, jamais interprétés :
   même espace de noms que le `target.id` des cibles Riff (docs/compo.md §10). « Née ici » se lit
   dans un CHAMP (`born`), jamais dans le préfixe. ⚠ `song_slug` n'est PAS une identité : c'est un slug de CATALOGUE,
   attaché à 0..1 chanson ; une compo n'en a pas, deux groupes qui reprennent le même titre
   partagent le même. Bien formé, mauvaise nature — le piège de CLAUDE.md.

2. **LA FICHE EST LA MÊME FORME QUE LA LIGNE.** `sheet` porte les huit champs de
   `setlists.SCOPED_FIELDS` plus rien : une ligne résolue et une fiche de chanson doivent être
   comparables octet pour octet, sinon la synchro boucle en `resend` (docs/setlists.md §9.12).
   On réutilise donc LE nettoyeur de `setlists`, jamais une copie — une seconde implémentation de
   la même validation diverge le jour où l'une des deux est corrigée.

3. **`rev` ARBITRE, COMME POUR UNE LIGNE.** Compteur d'écriture, jamais une horloge : un rack de
   scène peut vivre sans NTP. Rev entrant supérieur → golem.fm gagne ; à rev égal et corps
   différent → le rack gagne (son état a réellement joué) et repart au prochain push.
"""
import json
import os
import re
import time
import uuid

from . import config as C
from . import golemfile as G
from . import setlists as SL
from .golog import get
from .store import _write_json_atomic

log = get("songs")

# ── L'ID ────────────────────────────────────────────────────────────────────────────────────
# TROIS formes, et trois seulement (docs/songs.md §9.3) : `bs:<n>` née chez golem.fm dans un groupe,
# `rs:<uuid4 hex>` née sur un rack (2026-09-22), `us:<32 hex>` chanson perso née chez golem.fm (le mainteneur
# 2026-10-08, plan-song-sharing R5). JAMAIS de renommage de l'une vers l'autre : un id
# renommé entre deux systèmes qui se synchronisent, c'est l'envoi parti sous l'ancien nom qui
# arrive après — et chez golem.fm tout le prix serait chez nous (lignes, cibles Riff, prises).
# Une chanson perso n'avait qu'un slug, qui n'est pas une identité : d'où `us:`. Une quatrième forme serait
# une décision que personne n'a prise.
# `ct:` (song-sharing.md §2.8, 2026-10-11) : l'id d'un fichier qui CIRCULE, dérivé de ce qu'est la chanson (ISRC, id
# MusicBrainz, ou artiste+titre normalisés) — jamais du compte. Le rack garde en interne son bs:/rs: ; un ct: entrant
# qui est le même enregistrement s'y rattache (_same_recording), sinon la chanson naît sous ct:.
BS = re.compile(r"^(?:bs|rs|us|ct):[A-Za-z0-9_-]{1,96}$")
# les champs de la FICHE : exactement ceux qu'une ligne peut porter et qu'une portée peut viser.
# Importés, pas recopiés — deux listes qui disent la même chose divergent (mesuré ailleurs).
SHEET_FIELDS = SL.SCOPED_FIELDS
KINDS = ("cover", "original")
# `born: "rack"` = frappée sur un rack. Un CHAMP DÉCLARÉ, pas une lecture du préfixe `rs:` : une
# nature se lit dans un champ, pas dans une convention de nommage (CLAUDE.md, « bonne forme, mauvaise
# nature »). golem.fm le range en `origin` (`web` | `rack`), comme `BandSetlist.origin`.
TOP_FIELDS = ("id", "rev", "band", "title", "artist", "kind", "song_slug", "born", "sheet", "pulled_at")


def _safe(sid):
    """L'id -> un nom de fichier. `bs:42` devient `bs-42` : les deux-points sont légaux sur ext4
    mais pas partout (FAT d'une clé USB de sauvegarde), et un id ne doit jamais décider de la
    portabilité d'un dossier."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(sid or "")) or "song"


def _path(sid):
    """Le fichier de la chanson SUR LE GOLEM — celui qu'on écrit."""
    return os.path.join(C.SONGS_DIR, f"{_safe(sid)}.golem")


def source_path(sid):
    """Le fichier à LIRE : celui du golem, sinon celui d'un dossier de chansons en ligne (docs/song-folders.md §2.3 :
    écouter, répéter, chanter se font sur place). Ne sert jamais à écrire : un dossier de chansons ne s'écrit pas."""
    p = _path(sid)
    if os.path.exists(p):
        return p
    from . import song_folders
    return song_folders.path_of(sid) or p


def in_folder(sid):
    """La chanson n'est PAS sur le golem mais un dossier de chansons la porte : le chemin, sinon None."""
    if os.path.exists(_path(sid)):
        return None
    from . import song_folders
    return song_folders.path_of(sid)


def ensure_local(sid):
    """ADOPTER si besoin (song-folders.md §2.3) : une écriture (fiche, setlist) vise une chanson lue dans un dossier
    -> elle est d'abord copiée dans le golem par le chemin unique. Rend True si une adoption a eu lieu. Lève
    InstallError si elle échoue (l'écriture n'a alors pas lieu : on n'écrit jamais là-bas)."""
    src = in_folder(sid)
    if not src:
        return False
    from . import song_folders
    try:
        song_folders.adopt(src)
    except song_folders.AdoptError as e:
        raise InstallError(str(e)) from e
    if not os.path.exists(_path(sid)):
        # rattachée par empreinte à une AUTRE chanson du golem (ou rangée parmi les standards) : écrire sous cet id
        # fabriquerait un fichier sans médias — on le dit, on n'écrit pas
        raise InstallError("this file joined another song on this golem (same recording) — edit that one")
    log.info(f"{sid} adoptée depuis son dossier avant écriture")
    return True


# ── la chanson ↔ le fichier `.golem` ─────────────────────────────────────────────────────────
REPERTOIRE_FIELDS = ("rev", "band", "song_slug", "born", "pulled_at")   # la synchro, sous `repertoire`
IDENTITY_FIELDS = ("title", "artist", "kind")                         # le premier niveau du manifeste


def _read_golem(path):
    """La chanson PROPRE lue dans un `.golem` (manifeste + `sheet.json`), ou None. Ne vérifie pas les
    empreintes des médias : c'est l'affaire de l'import et du cache de travail, pas d'une lecture de fiche
    faite à chaque ligne de setlist."""
    try:
        m = G.read_manifest(path)
        try:
            sheet = json.loads(G.read_member(path, "sheet.json").decode("utf-8"))
        except G.GolemError:
            sheet = {}
    except (G.GolemError, OSError, ValueError) as e:
        log.warning(f"chanson illisible {os.path.basename(path)} : {e}")
        return None
    if m.get("type") != "song":
        return None
    r = m.get("repertoire") if isinstance(m.get("repertoire"), dict) else {}
    doc = {"id": m.get("id"), "sheet": sheet, **{k: m[k] for k in IDENTITY_FIELDS if k in m},
           **{k: r[k] for k in REPERTOIRE_FIELDS if k in r}}
    doc = clean(doc)
    # une DÉMO de golem.fm (écoute et téléchargement libres, jamais vendue) : lue pour la montrer, jamais écrite —
    # absent = vendu ou inconnu (golem-format.md §3, 2026-10-28)
    rel = m.get("release")
    if isinstance(rel, dict) and rel.get("kind") == "demo":
        doc["demo"] = True
    return doc


PRESET_KEY = "preset_doc"      # la copie du preset dans sheet.json (golem-format.md §9, 2026-10-08)


def _current_preset_doc(path):
    """La copie du preset déjà rangée dans le sheet.json du fichier, ou None."""
    try:
        raw = json.loads(G.read_member(path, "sheet.json").decode("utf-8"))
        doc = raw.get(PRESET_KEY) if isinstance(raw, dict) else None
        return doc if isinstance(doc, dict) else None
    except (G.GolemError, OSError, ValueError):
        return None


def _write_golem(d, preset_doc="keep"):
    """Écrit la chanson propre `d` dans son `.golem` : créé s'il n'existe pas, sinon RÉÉCRIT sans toucher
    aux autres membres (stems, tab, paroles… recopiés octet pour octet, golemfile.replace).
    `preset_doc` : "keep" = garder la copie du preset déjà rangée SI elle est toujours celui de la fiche (une
    retouche de fiche ne la perd pas, et ne la recalcule pas — c'est le travail de `snapshot_preset`) ; un dict =
    la nouvelle copie ; None = la retirer."""
    path = _path(d["id"])
    body = dict(d.get("sheet") or {})
    if preset_doc == "keep":
        cur = _current_preset_doc(path) if os.path.exists(path) else None
        preset_doc = cur if cur and cur.get("id") == body.get("preset") else None
    if isinstance(preset_doc, dict):
        body[PRESET_KEY] = preset_doc
    sheet = json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8")

    def fill(m):
        m["format"] = m.get("format") or G.FORMAT
        m["type"] = "song"
        m["id"] = d["id"]
        for k in IDENTITY_FIELDS:
            if d.get(k):
                m[k] = d[k]
            else:
                m.pop(k, None)
        m["repertoire"] = {k: d[k] for k in REPERTOIRE_FIELDS if d.get(k) is not None}
    if os.path.exists(path):
        G.replace(path, fill, {"sheet.json": sheet})
    else:
        m = {}
        fill(m)
        G.write(path, m, {"sheet.json": sheet})
    return path


# ── la MIGRATION des anciens `songs/<id>.json` ──────────────────────────────────────────────
_MIGRATED = set()          # dossiers déjà migrés par ce processus (le premier accès suffit)


def _migrate():
    """Chaque `songs/<id>.json` devient `songs/<id>.golem`, RELU et comparé avant que le JSON soit rangé
    dans `songs/.json-migrated/` (jamais effacé). Un JSON illisible reste où il est, journalisé : on ne
    perd pas une chanson parce qu'elle est cassée. Idempotent ; une fois par dossier et par processus."""
    d0 = C.SONGS_DIR
    if d0 in _MIGRATED:
        return
    _MIGRATED.add(d0)
    if not os.path.isdir(d0):
        return
    for f in sorted(os.listdir(d0)):
        if not f.endswith(".json") or f.startswith("."):          # `.sync.json` n'est pas une chanson
            continue
        src = os.path.join(d0, f)
        try:
            with open(src, encoding="utf8") as fh:
                d = clean(json.load(fh))
        except (OSError, ValueError) as e:
            log.warning(f"migration .golem : {f} illisible, laissé en place ({e})")
            continue
        if not d:
            log.warning(f"migration .golem : {f} n'est pas une chanson, laissé en place")
            continue
        try:
            if os.path.exists(_path(d["id"])):
                back = _read_golem(_path(d["id"]))
                if back and int(back.get("rev") or 0) >= int(d.get("rev") or 0):
                    log.info(f"migration .golem : {f} déjà migré (rev {back.get('rev')}), JSON rangé")
                else:
                    _write_golem(d)
            else:
                _write_golem(d)
            back = _read_golem(_path(d["id"]))
            # relu IDENTIQUE au JSON (même rev, même corps) — ou plus récent : sinon on ne range pas le JSON
            ok = bool(back) and (int(back.get("rev") or 0) > int(d.get("rev") or 0)
                                 or (int(back.get("rev") or 0) == int(d.get("rev") or 0) and _body(back) == _body(d)))
            if not ok:
                log.warning(f"migration .golem : {f} relu différent — JSON laissé en place")
                continue
            os.makedirs(os.path.join(d0, ".json-migrated"), exist_ok=True)
            os.replace(src, os.path.join(d0, ".json-migrated", f))
            log.info(f"migration .golem : {f} → {os.path.basename(_path(d['id']))}")
        except (G.GolemError, OSError) as e:
            log.warning(f"migration .golem : {f} échouée, laissé en place ({e})")


# ── INSTALLER un `.golem` venu d'ailleurs (dossier surveillé, job song-install de golem.fm) ──
class InstallError(Exception):
    """Un `.golem` refusé à l'installation. Message montrable (anglais)."""


def install_golem(src, replace_into=None, slug=None):
    """Installe le `.golem` `src` dans la bibliothèque. UN SEUL CHEMIN pour tout ce qui arrive : le dossier
    surveillé (plan lot 1.4) et le job `song-install` de golem.fm (lot 2).

    Vérifié EN ENTIER d'abord (chemins, zip piégé, version, type, formats audio, empreintes). Puis la RÈGLE
    DE FUSION (réglée avec golem.fm le 2026-10-08) :
      - chanson INCONNUE : créée telle qu'elle arrive. Sa clé `repertoire` est ÉCARTÉE — c'est l'état de
        synchro d'un AUTRE rack (rev, band). Son slug golem.fm vient du TRANSPORT (`slug` : le job `song-install`,
        le tirage par `golem_etag`), jamais du fichier — un .golem ne mène à personne (song-sharing.md §2.8) ; un
        fichier posé à la main se relie par le catalogue golem.fm de ce compte (`slug_from_cards`), sinon reste seul.
      - chanson CONNUE : le fichier apporte les médias et l'identité (audio/, stems/, scores/, chart/,
        lyrics/, sync/, art/… et title/artist/kind/rights/genres/credits…), le rack GARDE sa fiche
        (`sheet.json`), sa synchro (`repertoire`) et `mine/` : la fiche voyage déjà par le canal des
        chansons, arbitrée par rev — deux canaux pour la même fiche finiraient par se contredire.
    L'ancien fichier est remplacé d'un coup. Rend {id, title, created, missing}.

    `replace_into` = l'id d'une de nos chansons : « Replace with a file… » (lot 5, 2026-10-08). Un fichier du
    MÊME ENREGISTREMENT que cette chanson remplace ses médias, même si elle est déjà complète ; la fiche reste la
    sienne. Un fichier d'un AUTRE enregistrement est refusé — remplacer ne change pas de chanson."""
    import shutil
    import zipfile
    try:
        rep = G.verify(src)
    except G.GolemError as e:
        raise InstallError(str(e)) from e
    m = rep["manifest"]
    if m.get("type") != "song":
        raise InstallError("albums are not installed yet — only songs")
    sid = str(m.get("id") or "")
    if not BS.match(sid):
        raise InstallError("not a song id: %s (expected bs:, rs:, us: or ct:)" % sid)
    _migrate()
    # ── RATTACHER PAR L'EMPREINTE (golem-format.md §12.5, 2026-10-08) : un id INCONNU qui est le même
    # ENREGISTREMENT qu'une de nos chansons — refusé si elle a déjà ses médias, la complète si elle n'en a pas
    if replace_into and replace_into != sid:
        hit = _same_recording(m)
        if not hit or hit[1]["id"] != replace_into:
            target = load(replace_into) or {}
            raise InstallError("this file is not the same recording as « %s » — nothing replaced"
                               % (target.get("title") or replace_into))
        sid = replace_into
    elif not os.path.exists(_path(sid)):
        hit = _same_recording(m)
        if hit and hit[0] == "complete":
            raise InstallError("same recording as your song « %s » — already complete" % (hit[1].get("title") or hit[1]["id"]))
        if hit and hit[0] == "card":
            log.info(f"{sid} : même enregistrement que la carte de {hit[1]['id']} — ses médias la complètent")
            sid = hit[1]["id"]
    dest = _path(sid)
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    tmp = os.path.join(C.SONGS_DIR, ".install-%s.golem" % uuid.uuid4().hex[:8])
    shutil.copyfile(src, tmp)
    try:
        members, keep_rep = {}, None
        created = not os.path.exists(dest)
        if not created:
            with zipfile.ZipFile(dest) as zl, zipfile.ZipFile(tmp) as zi:
                lm = json.loads(zl.read(G.MANIFEST).decode("utf-8"))
                keep_rep = lm.get("repertoire") if isinstance(lm.get("repertoire"), dict) else {}
                lnames = [n for n in zl.namelist() if not n.endswith("/")]
                if "sheet.json" in lnames:
                    members["sheet.json"] = zl.read("sheet.json")
                elif "sheet.json" in zi.namelist():
                    members["sheet.json"] = None
                for n in lnames:
                    if n.startswith("mine/"):
                        members[n] = zl.read(n)
                for n in zi.namelist():
                    if n.startswith("mine/") and n not in members:
                        members[n] = None
        if not slug:                                    # `golemfm.slug` du fichier : IGNORÉ (song-sharing.md §2.8)
            slug = slug_from_cards(sid, m)
        # un ORIGINAL SIGNÉ (lot 8) : la signature couvre les octets de golem.json, que `fuse` va réécrire — on les
        # garde sous signatures/golem.json (hors manifeste), c'est sur eux que `signatures.check` vérifie
        from . import signatures as SIG
        signed = SIG.signed_manifest_member(tmp)
        if signed is not None:
            members[SIG.SIGNED_MANIFEST] = signed

        def fuse(mm):
            mm["id"] = sid                                   # un rattachement par empreinte garde NOTRE id
            if created:
                r = {}
                if isinstance(slug, str) and slug.strip():
                    r["song_slug"] = slug.strip()[:160]
                mm["repertoire"] = r
            else:
                # une MISE À JOUR garde la synchro du rack telle quelle, slug compris — jamais celui du fichier :
                # R2 (golem.fm, 2026-10-08) envoie au golem d'un groupe la COPIE d'un membre, dont le slug
                # n'est pas lisible par le compte du propriétaire (suivi de tab, pratique : refusés là-bas)
                mm["repertoire"] = dict(keep_rep or {})
        G.replace(tmp, fuse, members)
        G.verify(tmp)
        got = _read_golem(tmp)
        if not got:
            raise InstallError("the song could not be read back after installing")
        os.replace(tmp, dest)
    except G.GolemError as e:
        raise InstallError(str(e)) from e
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _CACHE.pop(dest, None)
    preset = _adopt_preset(_current_preset_doc(dest))
    log.info(f"chanson installée {sid} ({'nouvelle' if created else 'mise à jour'}) — {len(rep['missing'])} fichier(s) "
             f"attendu(s) absent(s){' — preset ' + preset['action'] if preset else ''}")
    return {"id": sid, "title": got.get("title"), "created": created, "missing": rep["missing"],
            **({"preset": preset} if preset else {})}


def _fp_of(m):
    """(empreinte compressée, durée ms) du `recording` d'un manifeste, ou (None, None)."""
    rec = m.get("recording") if isinstance(m.get("recording"), dict) else {}
    fp = rec.get("fingerprint")
    val = fp.get("value") if isinstance(fp, dict) and fp.get("algo", "chromaprint") == "chromaprint" else None
    return (val if isinstance(val, str) and val else None), rec.get("duration_ms")


def _has_media(path):
    """Le fichier porte-t-il des médias (l'original ou un stem) ? Lu dans l'archive, jamais déclaré."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as zf:
            return any(n.startswith(("audio/", "stems/")) and not n.endswith("/") for n in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


# ── UN STEM ENREGISTRÉ SUR UN STANDARD EST FIGÉ DANS UNE VERSION (golem-format.md §6 ter, plan lot 10) ──
def version_now(sid):
    """La version que la chanson joue AUJOURD'HUI : {key, tempo, form, chorus} — tonalité du bloc Standard (sa
    grille si « Original »), tempo de la fiche (sinon du preset, sinon de la grille), forme = l'ordre des sections
    de la grille, chorus du bloc. Une clé inconnue est absente (on ne la compare pas)."""
    from . import standards as STD, store
    d = load(sid) or {}
    sh = d.get("sheet") or {}
    grid = STD.get_grid(STD.song_slug(sid)) or {}
    pm = {}
    preset = store.load_preset(sh["preset"]) if sh.get("preset") else None
    if preset:
        blk = next((b for b, _l in store.all_blocks(preset) if isinstance(b, dict) and b.get("type") == "standard"), None)
        if blk:
            pm = dict(blk.get("params") or {})
            pm.update(((sh.get("blocks") or {}).get(blk.get("id")) or {}).get("params") or {})
    out = {}
    key = pm.get("key") if pm.get("key") not in (None, "", "Original") else grid.get("key")
    if key:
        out["key"] = str(key)
    tempo = sh.get("bpm") or (preset or {}).get("bpm") or grid.get("tempo")
    if tempo:
        out["tempo"] = float(tempo)
    form = [sec.get("label") for sec in (grid.get("sections") or []) if sec.get("label")]
    if form:
        out["form"] = form
    if pm.get("choruses"):
        out["chorus"] = int(pm["choruses"])
    return out


def stem_takes(sid, manifest=None):
    """Les stems ENREGISTRÉS sur une version (`take_of`) et leur verdict : [{stem, take_of, ok, why}]. Un stem dont
    la version ne correspond plus à celle d'aujourd'hui (tonalité, tempo, forme, chorus) est COUPÉ — le bloc
    Standard suit la fiche, le stem non : « le golem le dit et coupe ce stem plutôt que de jouer faux »."""
    if manifest is None:
        try:
            manifest = G.read_manifest(source_path(sid))
        except (G.GolemError, OSError):
            return []
    takes = [(arc, e.get("take_of")) for arc, e in sorted((manifest.get("files") or {}).items())
             if arc.startswith("stems/") and isinstance(e, dict) and isinstance(e.get("take_of"), dict)]
    if not takes:
        return []
    now = version_now(sid)
    out = []
    for arc, t in takes:
        why = []
        if "key" in t and "key" in now and str(t["key"]).lower() != now["key"].lower():
            why.append("recorded in %s, the song is now in %s" % (t["key"], now["key"]))
        if "tempo" in t and "tempo" in now and abs(float(t["tempo"]) - now["tempo"]) > 0.5:
            why.append("recorded at %g, the song is now at %g" % (float(t["tempo"]), now["tempo"]))
        if "form" in t and "form" in now and list(t["form"]) != now["form"]:
            why.append("recorded on the form %s, it is now %s" % ("".join(t["form"]), "".join(now["form"])))
        if "chorus" in t and "chorus" in now and int(t["chorus"]) != now["chorus"]:
            why.append("recorded over %d chorus, the song now plays %d" % (int(t["chorus"]), now["chorus"]))
        out.append({"stem": arc, "take_of": t, "ok": not why, "why": "; ".join(why)})
    return out


# ── CE QUE PORTE UNE CHANSON (lot 5, écran « What this song carries », maquette mockups/golem-files.html) ──
def files_summary(sid, detail=True):
    """Ce que le `.golem` de la chanson porte, LU dans l'archive (jamais déclaré) : une entrée par élément du
    format, `state` = ok | missing (attendu, absent) | none (sans objet ici). + l'état d'ensemble :
    `complete` (médias et rien d'attendu qui manque) · `partial` · `card` (pas de médias). Ne vérifie pas les
    empreintes (c'est l'affaire de l'import) : c'est un écran, il doit répondre vite."""
    import zipfile
    path = source_path(sid)
    try:
        m = G.read_manifest(path)
        with zipfile.ZipFile(path) as zf:
            names = {n for n in zf.namelist() if not n.endswith("/")}
            sheet_raw = json.loads(zf.read("sheet.json").decode("utf-8")) if "sheet.json" in names else {}
            bars_n = None
            if detail and "sync/bars.json" in names:
                try:
                    bars_n = len(json.loads(zf.read("sync/bars.json").decode("utf-8")).get("bars") or [])
                except ValueError:
                    bars_n = None
    except (G.GolemError, OSError, zipfile.BadZipFile, ValueError) as e:
        return {"state": "broken", "why": str(e)}
    files = m.get("files") or {}
    declared = set(files)
    got = lambda pre: sorted(n for n in names if n.startswith(pre))
    want = lambda pre: sorted(n for n in declared if n.startswith(pre))
    rec = m.get("recording") if isinstance(m.get("recording"), dict) else {}
    items = []

    def add(key, label, present, expected, info, how=None):
        st = "ok" if present else ("missing" if expected else "none")
        items.append({"key": key, "label": label, "state": st, "info": info, **({"how": how} if how and st == "missing" else {})})
    au = got("audio/")
    a0 = (files.get(au[0]) or {}) if au else {}
    dur = rec.get("duration_ms")
    add("audio", "Original recording", bool(au), bool(want("audio/")),
        " · ".join(x for x in [(a0.get("codec") or (os.path.splitext(au[0])[1][1:] if au else "")).upper(),
                               ("%d:%02d" % (dur // 60000, dur // 1000 % 60)) if dur else "",
                               ("%.1f MB" % (a0["bytes"] / 1e6)) if a0.get("bytes") else ""] if x) or "—")
    st_ = got("stems/")
    parts = [str((files.get(n) or {}).get("part") or os.path.splitext(os.path.basename(n))[0]) for n in st_]
    origins = sorted({(files.get(n) or {}).get("origin") for n in st_} - {None})
    add("stems", "Stems · %d" % len(st_) if st_ else "Stems", bool(st_), bool(want("stems/")),
        (" · ".join(parts) + (" — " + "/".join(origins) if origins else "")) if st_ else "no stems in this file")
    for tk in (stem_takes(sid, m) if detail else []):                    # lot 10 : un stem figé dans une version
        if not tk["ok"]:
            nm = os.path.splitext(os.path.basename(tk["stem"]))[0]
            items.append({"key": "take:" + nm, "label": "%s · muted" % nm, "state": "missing", "info": tk["why"],
                          "how": "record it again in this version, or go back to the version it was recorded in"})
    add("bars", "Bar map", "sync/bars.json" in names, "sync/bars.json" in declared,
        ("%d bars · the click and the parts follow it" % bars_n) if bars_n else "the click and the parts follow it")
    tab = "scores/song.gp" in names
    tracks = (files.get("scores/song.gp") or {}).get("tracks") or []
    add("tab", "Tab", tab, "scores/song.gp" in declared,
        ((" · ".join(str(t.get("part")) for t in tracks if t.get("part")) + " (%d tracks)" % len(tracks)) if tracks else "the song's .gp")
        + (" · synced" if "sync/score.json" in names else ""))
    lrc = got("lyrics/")
    add("lyrics", "Lyrics", bool(lrc), bool(want("lyrics/")), "synced" if lrc else "—")
    pdoc = sheet_raw.get(PRESET_KEY) if isinstance(sheet_raw, dict) else None
    pid = (sheet_raw or {}).get("preset")
    if isinstance(pdoc, dict):
        un = len(pdoc.get("unresolved") or [])
        add("preset", "Preset copy", True, True, "%d capture%s, %s" % (len(pdoc.get("deps") or []), "" if len(pdoc.get("deps") or []) == 1 else "s",
                                                                       "none missing on this rack" if not un else "%d missing" % un))
    else:
        add("preset", "Preset copy", False, bool(pid), "kept up to date in the background" if pid else "no preset on this song")
    art = got("art/")
    add("art", "Cover art", bool(art), bool(want("art/")), " · ".join(os.path.basename(n) for n in art) or "—")
    vid = got("video/")
    add("video", "Video", bool(vid), bool(want("video/")), "present" if vid else "only for songs recorded on a golem")
    d = load(sid) or {}
    fp = _fp_of(m)[0] or ((_cards().get(d.get("song_slug") or "") or {}).get("fingerprint"))
    add("identity", "Recording identity", bool(fp) and bool(au or st_), False,
        "fingerprint — a copy from elsewhere is recognised by it" if fp else "no fingerprint yet")
    if detail and "signatures/manifest.json" in names:                # un original SIGNÉ (lot 8) : le verdict se montre
        from . import signatures as SIG
        v = SIG.check(path) or {}
        who = ((v.get("signer") or {}).get("name")) or "its band"
        if v.get("valid"):
            items.append({"key": "signature", "label": "Signed", "state": "ok",
                          "info": "by %s · verified%s" % (who, " with the last known keys" if v.get("offline") else "")})
        elif v.get("valid") is None:
            items.append({"key": "signature", "label": "Signed", "state": "none", "info": "by %s · %s" % (who, v.get("reason"))})
        else:
            items.append({"key": "signature", "label": "Signature not valid", "state": "missing",
                          "info": "claims %s · %s" % (who, v.get("reason") or "not valid")})
    media = bool(au or st_)
    missing = [i["label"] for i in items if i["state"] == "missing" and i["key"] != "signature"]   # une signature n'est pas un fichier attendu
    state = "card" if not media else ("complete" if not missing else "partial")
    present = len([n for n in declared if n in names])
    cat = G.category(names, declared)                                   # LUE, la règle partagée avec golem.fm (§2.7)
    out = {"state": state, "present": present, "expected": len(declared), "missing": missing,
           "bytes": os.path.getsize(path), "category": cat,
           "section": {"song": "songs", "vocals": "songs", "standard": "standards", "track": "songs"}.get(cat)}
    if path != _path(sid):                                              # lue sur place (song-folders.md §2.3)
        out["folder"] = {"path": path, "folder": os.path.dirname(path)}
    if detail:
        from . import golem_pull
        slug = d.get("song_slug")
        out.update({"items": items, "path": path if out.get("folder") else C.rel(path), "mtime": int(os.path.getmtime(path)),
                    "etag": golem_pull.etags().get(slug) if slug else None,
                    "from_golemfm": bool(slug and golem_pull.etags().get(slug))})
    return out


def _same_recording(m):
    """La chanson du golem qui est le MÊME ENREGISTREMENT que le manifeste `m` : ("complete", chanson) si elle a
    déjà ses médias, ("card", chanson) si elle n'en a pas. Son empreinte : celle de son manifeste, SINON celle de
    sa carte golem.fm (mémorisée au tirage du catalogue) — vécu le 2026-10-08 : une chanson tirée AVANT que golem.fm
    ne calcule les empreintes n'en a pas dans son manifeste, et une copie d'ami serait devenue un doublon.
    « A ses médias » se LIT dans l'archive. Compare, ne calcule rien. None si rien ne ressemble."""
    from . import fingerprint as FP
    fp, dur = _fp_of(m)
    if not fp:
        return None
    cards = _cards()
    for d in list_all():
        path = _path(d["id"])
        try:
            mine, mdur = _fp_of(G.read_manifest(path))
        except (G.GolemError, OSError):
            continue
        if not mine:
            c = cards.get(d.get("song_slug") or "") or {}
            mine, mdur = c.get("fingerprint"), c.get("duration_ms")
        if mine and FP.same_recording(fp, mine, dur, mdur)[0]:
            return ("complete" if _has_media(path) else "card", d)
    return None


def _cards_path():
    return os.path.join(C.SONGS_DIR, ".cards.json")


def _cards():
    """{slug: {fingerprint, duration_ms}} — les empreintes des CARTES golem.fm, mémorisées au tirage du catalogue
    (golem_pull.refresh_all). Une trace locale, jamais poussée."""
    try:
        with open(_cards_path(), encoding="utf8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def slug_from_cards(sid, m=None):
    """Le slug golem.fm d'un .golem arrivé SANS transport (dossier, inbox, glisser-déposer) : la carte du catalogue de
    CE compte qui porte cet id (`golem_id`, ou `ct_id` pour un fichier qui a circulé), sinon celle du même
    enregistrement (empreinte). None : la chanson reste sans lien —
    jamais deviné, jamais lu dans le fichier (song-sharing.md §2.8)."""
    cards = _cards()
    hit = [slug for slug, c in cards.items() if isinstance(c, dict) and sid in (c.get("golem_id"), c.get("ct_id"))]
    if len(hit) == 1:
        return hit[0]
    if m is None:
        return None
    from . import fingerprint as FP
    fp, dur = _fp_of(m)
    if not fp:
        return None
    same = [slug for slug, c in cards.items()
            if isinstance(c, dict) and c.get("fingerprint") and FP.same_recording(fp, c["fingerprint"], dur, c.get("duration_ms"))[0]]
    return same[0] if len(same) == 1 else None


def remember_cards(cards):
    """Mémorise l'empreinte des cartes du catalogue qui en portent une : `fingerprint` (chaîne, ou {algo, value})
    et `duration_ms` (ou `duration_sec`). Rend le nombre mémorisé."""
    d = _cards()
    n = 0
    for c in cards or []:
        if not isinstance(c, dict) or not c.get("slug"):
            continue
        gid = c.get("golem_id")                          # l'id .golem de la carte, quand golem.fm le donne
        ctid = c.get("ct_id")                            # l'id `ct:` d'un fichier qui circule (song-sharing.md §2.8)
        fp = c.get("fingerprint")
        val = fp.get("value") if isinstance(fp, dict) else fp
        if not (isinstance(val, str) and val) and not (isinstance(gid, str) and gid) and not (isinstance(ctid, str) and ctid):
            continue
        e = {}
        if isinstance(val, str) and val:
            dur = c.get("duration_ms") or (int(c["duration_sec"] * 1000) if isinstance(c.get("duration_sec"), (int, float)) else None)
            e.update(fingerprint=val, duration_ms=dur)
        if isinstance(gid, str) and gid:
            e["golem_id"] = gid
        if isinstance(ctid, str) and ctid:
            e["ct_id"] = ctid
        if d.get(c["slug"]) != e:
            d[c["slug"]] = e
            n += 1
    if n:
        os.makedirs(C.SONGS_DIR, exist_ok=True)
        _write_json_atomic(_cards_path(), d)
    return n


def _adopt_preset(doc):
    """Le preset qu'un `.golem` porte (golem-format.md §9) : ABSENT du golem → créé ; présent et identique (même
    empreinte) → rien ; présent et DIFFÉRENT → le golem garde le sien (ce qui a joué ici gagne), et c'est dit.
    Mêmes contrôles que le job preset-install : migration, volume système, ids de blocs et de branches uniques.
    Rend {preset, action: created|same|kept_local|refused, unresolved?, why?} ou None (pas de preset)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("preset"), dict):
        return None
    from . import preset_export, store
    pid = store._safe_id(str(doc.get("id") or doc["preset"].get("id") or ""))
    if not pid:
        return {"preset": None, "action": "refused", "why": "the preset has no id"}
    path = os.path.join(C.PRESETS_DIR, f"{pid}.json")
    if os.path.exists(path):
        mine = store._read_json(path, {}) or {}
        if preset_export.fingerprint(mine) == preset_export.fingerprint(doc["preset"]):
            return {"preset": pid, "action": "same"}
        return {"preset": pid, "action": "kept_local",
                "why": "this rack has its own « %s », different from the file's — kept" % pid}
    p = dict(doc["preset"], id=pid)
    store.migrate_config(p)
    store.ensure_volume(p)
    bad = store.duplicate_block_ids(p) or store.duplicate_branch_ids(p)
    if bad:
        return {"preset": pid, "action": "refused", "why": "duplicate ids: " + ", ".join(bad)}
    _write_json_atomic(path, p)
    out = {"preset": pid, "action": "created"}
    if doc.get("unresolved"):
        out["unresolved"] = doc["unresolved"]
    return out


# ── la copie du preset dans le .golem, tenue à jour en tâche de fond (golem-format.md §9) ──
SNAPSHOT_SETTLE_S = 60


def _seen_path():
    return os.path.join(C.SONGS_DIR, ".preset-seen.json")


def _seen():
    """{id de chanson: mtime du preset déjà examiné} — une trace LOCALE : un preset réenregistré sans changer de
    son (couleur, sauvegarde identique) est noté ici, sans réécrire 55 Mo de .golem pour une date."""
    try:
        with open(_seen_path(), encoding="utf8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _note_seen(sid, mt):
    d = _seen()
    d[sid] = mt
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    _write_json_atomic(_seen_path(), d)


def preset_snapshot_stale(sid, now=None):
    """True si le preset de la fiche a changé depuis la copie rangée ET est stable depuis SNAPSHOT_SETTLE_S."""
    # une chanson d'USINE ne reçoit jamais la copie : livrée sans elle, la réécrire changeait l'empreinte du .golem, et
    # factory.edited() la disait « retouchée » une minute après le premier démarrage — les mises à jour d'usine la
    # sautaient pour toujours. Elle ne monte pas vers golem.fm, et son preset est d'usine sur chaque golem.
    if is_factory(sid):
        return False
    d = load(sid)
    pid = ((d or {}).get("sheet") or {}).get("preset")
    if not pid:
        return bool(d) and _current_preset_doc(_path(sid)) is not None          # fiche sans preset : retirer la copie
    try:
        mt = os.stat(os.path.join(C.PRESETS_DIR, f"{pid}.json")).st_mtime_ns
    except OSError:
        return False                                                             # preset absent : rien à copier
    if ((now or time.time()) - mt / 1e9) < SNAPSHOT_SETTLE_S:
        return False
    cur = _current_preset_doc(_path(sid))
    if not cur or cur.get("id") != pid:
        return True
    return mt not in (cur.get("source_mtime_ns"), _seen().get(sid))


def snapshot_preset(sid):
    """Range (ou retire) la copie du preset de la fiche dans le `.golem`. Coûteux (le zip est réécrit, et la
    première résolution des dépendances hache la bibliothèque) : appelé en tâche de fond, jamais pendant le jeu.
    Rend "written" | "removed" | "unchanged" | None."""
    d = load(sid)
    if not d:
        return None
    pid = (d.get("sheet") or {}).get("preset")
    if not pid:
        if _current_preset_doc(_path(sid)) is None:
            return "unchanged"
        _write_golem(d, preset_doc=None)
        _CACHE.pop(_path(sid), None)
        return "removed"
    from . import preset_export
    path = os.path.join(C.PRESETS_DIR, f"{pid}.json")
    try:
        mt = os.stat(path).st_mtime_ns
    except OSError:
        return None
    exp, _blobs = preset_export.build_export(pid)
    if not exp:
        return None
    doc = {"schema_version": exp.get("schema_version"), "id": pid, "fingerprint": preset_export.fingerprint(exp["preset"]),
           "source_mtime_ns": mt, "preset": exp["preset"], "deps": exp.get("deps") or [],
           "unresolved": exp.get("unresolved") or [], "catalog_version": exp.get("catalog_version")}
    cur = _current_preset_doc(_path(sid))
    if cur and cur.get("id") == pid and cur.get("fingerprint") == doc["fingerprint"] \
            and cur.get("deps") == doc["deps"] and cur.get("unresolved") == doc["unresolved"]:
        _note_seen(sid, mt)                                  # même son, mêmes dépendances : la date seule, notée à part
        return "unchanged"
    _write_golem(d, preset_doc=doc)
    _note_seen(sid, mt)
    _CACHE.pop(_path(sid), None)
    log.info(f"copie du preset {pid} rangée dans {os.path.basename(_path(sid))}")
    return "written"


# ── le CACHE DE TRAVAIL (golem-format.md §2) ────────────────────────────────────────────────
def workdir(sid):
    """Le dossier décompressé d'une chanson, pour JOUER (stems, tab…) : `songs/.work/<id>/`, reconstruit
    à la demande depuis le `.golem`, qui fait foi (empreintes vérifiées à la reconstruction). Rend le
    chemin, ou None si la chanson n'existe pas ou ne se vérifie pas."""
    path = source_path(sid)
    try:
        stamp = str(os.stat(path).st_mtime_ns)
    except OSError:
        return None
    local = path == _path(sid)
    if not local:                                  # lue sur place : le cache dit d'où il vient, et il est plafonné
        stamp = "folder:%s:%s" % (path, stamp)
    dest = os.path.join(C.SONGS_DIR, ".work", _safe(sid))
    mark = os.path.join(dest, ".from")
    try:
        if open(mark, encoding="utf8").read() == stamp:
            return dest
    except OSError:
        pass
    try:
        G.extract(path, dest)
    except (G.GolemError, OSError) as e:
        log.warning(f"cache de travail {sid} : {e}")
        if isinstance(e, PermissionError) and os.path.isfile(mark):
            return dest                            # Windows : un stem changé est tenu ouvert — l'ancien cache joue, on retentera
        return None
    with open(mark, "w", encoding="utf8") as fh:
        fh.write(stamp)
    if not local:
        from . import song_folders
        song_folders.prune_work(keep=dest)
    return dest


def clean_sheet(raw):
    """La fiche, nettoyée par LE nettoyeur de lignes — jamais une seconde implémentation.

    On emprunte `setlists._clean_line` en lui donnant une ligne jetable : il connaît déjà les
    bornes de `bpm`, l'aplatissement de `backing`, la forme de `arrangement` et le ménage de
    `blocks`. Le prix est un id de ligne factice qu'on jette ; le gain est qu'une fiche et une
    ligne resteront comparables le jour où l'une des règles change."""
    if not isinstance(raw, dict):
        return {}
    ln = SL._clean_line({k: raw.get(k) for k in SHEET_FIELDS if k in raw}, "song")
    return {k: v for k, v in ln.items() if k in SHEET_FIELDS}


def clean(doc):
    """Une chanson propre. Rend None si l'id n'est pas une identité de chanson.

    ⚠ Un id refusé n'est PAS une erreur silencieuse : trois formes existent (`bs:`, `rs:`, `us:`, §9.3),
    et en accepter une quatrième fabriquerait un format que personne n'a décidé."""
    if not isinstance(doc, dict):
        return None
    sid = str(doc.get("id") or "").strip()
    if not BS.match(sid):
        return None
    out = {"id": sid}
    try:
        out["rev"] = max(1, int(doc.get("rev") or 1))
    except (TypeError, ValueError):
        out["rev"] = 1
    for k in ("band", "title", "artist", "song_slug"):
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:160]
    # `kind` DÉCLARÉ, jamais déduit : chez golem.fm il porte une muraille juridique (une reprise
    # n'est pas publiable). Absent = « nature à dire », un état affiché, pas un défaut inventé.
    if doc.get("kind") in KINDS:
        out["kind"] = doc["kind"]
    if doc.get("born") == "rack":
        out["born"] = "rack"
    out["sheet"] = clean_sheet(doc.get("sheet"))
    if isinstance(doc.get("pulled_at"), str):
        out["pulled_at"] = doc["pulled_at"][:32]
    return out


# ── lecture / écriture ──────────────────────────────────────────────────────────────────────
_CACHE = {}          # chemin -> (mtime_ns, chanson propre)


def load(sid):
    """Une chanson, ou None. Mise en cache par date du fichier : `setlists.pid_of` résout la chanson
    de CHAQUE ligne à chaque lecture de setlist (§9.7), le pied compris — relire le JSON à chaque
    fois serait un coût sans raison. Une copie est rendue : l'appelant peut la modifier."""
    _migrate()
    path = source_path(sid)
    try:
        mt = os.stat(path).st_mtime_ns
    except OSError:
        _CACHE.pop(path, None)
        return None
    hit = _CACHE.get(path)
    if hit and hit[0] == mt:
        return json.loads(json.dumps(hit[1])) if hit[1] else None
    d = _read_golem(path)
    _CACHE[path] = (mt, d)
    return json.loads(json.dumps(d)) if d else None


def list_all():
    """Le répertoire, trié par titre. Un fichier illisible est journalisé et IGNORÉ : une chanson
    cassée ne doit pas emporter l'écran qui liste les dix-neuf autres."""
    _migrate()
    out = []
    if not os.path.isdir(C.SONGS_DIR):
        return out
    for f in sorted(os.listdir(C.SONGS_DIR)):
        if not f.endswith(".golem") or f.startswith("."):
            continue
        d = load_path(os.path.join(C.SONGS_DIR, f))
        if d:
            out.append(d)
    out.sort(key=lambda d: (d.get("title") or d["id"]).lower())
    return out


def load_path(path):
    """La chanson d'un fichier `.golem` donné (même cache que `load`)."""
    try:
        mt = os.stat(path).st_mtime_ns
    except OSError:
        return None
    hit = _CACHE.get(path)
    if hit and hit[0] == mt:
        return json.loads(json.dumps(hit[1])) if hit[1] else None
    d = _read_golem(path)
    _CACHE[path] = (mt, d)
    return json.loads(json.dumps(d)) if d else None


def save(doc, bump=True):
    """Écrit une chanson. `bump` incrémente `rev` — c'est une ÉCRITURE LOCALE qui repartira au
    prochain push. `bump=False` sert à la réception : le rev vient d'en face, l'incrémenter ici
    ferait croire à une modification locale et renverrait la chanson en boucle."""
    d = clean(doc)
    if not d:
        raise ValueError("not a song id (expected « bs:<id> », « rs:<id> » or « us:<id> »)")
    if bump:
        d["rev"] = int(d.get("rev") or 1) + 1
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    _migrate()
    # une chanson lue dans un DOSSIER est adoptée avant d'être écrite : sa copie reçoit l'écriture, le dossier jamais
    # (song-folders.md §2.2-2.3) — sans quoi la fiche écrite ici serait un fichier SANS ses médias
    ensure_local(d["id"])
    path = _write_golem(d)
    _CACHE.pop(path, None)  # mtime peut rester identique sur deux écritures rapides
    return d


def update(sid, **fields):
    """Édite la fiche d'une chanson : `rev` +1. Rend la chanson, None si inconnue.

    Les champs de FICHE vont dans `sheet` (c'est le geste courant — la page chanson n'édite que
    ça) ; les champs d'identité restent au premier niveau. Une valeur vide RETIRE le champ,
    jamais un zéro ni une chaîne vide : « pas de capo » n'est pas « capo 0 »."""
    d = load(sid)
    if not d:
        return None
    sheet = dict(d.get("sheet") or {})
    top = {}
    for k, v in fields.items():
        if k in SHEET_FIELDS:
            if v in (None, "") or (k == "blocks" and v == {}):
                sheet.pop(k, None)
            else:
                sheet[k] = v
        elif k == "kind":
            # la nature DÉCLARÉE ne s'efface pas et ne se devine pas : seules les deux valeurs passent
            # (chez golem.fm, une chanson sans nature tomberait dans leur défaut `original` — une
            # reprise publiable, §9.2). Une valeur vide ou inconnue est ignorée, pas appliquée.
            if v in KINDS:
                top[k] = v
        elif k in ("title", "artist", "song_slug", "band"):
            top[k] = v
    return save({**d, **top, "sheet": clean_sheet(sheet)})


def new_id():
    """`rs:<uuid4 hex>` — frappé UNE fois, à la création, et jamais réécrit (§9.3)."""
    return "rs:" + uuid.uuid4().hex


def create(title, kind, band=None, preset=None, bpm=None, artist=None, song_slug=None, sheet=None):
    """Une chanson NÉE SUR LE RACK (docs/songs.md §9.2). Rend la chanson, lève ValueError sinon.

    Quatre réponses sans lesquelles elle ne peut ni jouer ni monter : le titre, la NATURE (cover |
    original — obligatoire, sans défaut : chez golem.fm une chanson sans nature deviendrait une
    reprise publiable), le preset et le tempo (optionnels : vide = celui du preset). `band` = l'espace
    déclaré (perso ou groupe) ; le rack ne peut pas vérifier l'appartenance, golem.fm le fera."""
    title = str(title or "").strip()
    if not title:
        raise ValueError("a song needs a title")
    if kind not in KINDS:
        raise ValueError("say what it is: « cover » or « original »")
    sh = dict(sheet or {})
    if preset:
        sh["preset"] = preset
    if bpm not in (None, ""):
        sh["bpm"] = bpm
    doc = {"id": new_id(), "rev": 1, "title": title, "kind": kind, "born": "rack",
           "sheet": clean_sheet(sh)}
    for k, v in (("band", band), ("artist", artist), ("song_slug", song_slug)):
        if isinstance(v, str) and v.strip():
            doc[k] = v.strip()
    return save(doc, bump=False)


def transfer(sid, band):
    """Donne la chanson à un autre espace (« Give to <groupe> », §9.6) : MÊME id, `band` change,
    rev +1. Pas de copie (recommandé par golem.fm, le mainteneur penche pour). Rend la chanson, None si
    inconnue ou déjà là."""
    d = load(sid)
    band = str(band or "").strip()
    if not d or not band or d.get("band") == band:
        return None
    return save({**d, "band": band})


def from_line(line, kind, band=None, preset_name=None):
    """« ◆ Make it a song » (§9.6) : une ligne LIBRE devient une chanson. Ses champs de fiche
    passent dans la chanson, son titre aussi (repli : le nom du preset). Rend la chanson."""
    if not isinstance(line, dict) or line.get("band_song"):
        raise ValueError("this line already plays a song")
    sheet = {k: line[k] for k in SHEET_FIELDS if k in line and line[k] not in (None, "")}
    title = line.get("title") or preset_name or line.get("preset")
    return create(title, kind, band=band, song_slug=line.get("song_slug"), sheet=sheet)


def delete(sid):
    """Retire une chanson DU RACK. Elle reste au répertoire du groupe chez golem.fm — d'où le nom :
    on ne supprime pas une chanson, on cesse de la porter ici."""
    import shutil
    shutil.rmtree(os.path.join(C.SONGS_DIR, ".work", _safe(sid)), ignore_errors=True)
    try:
        os.remove(_path(sid))
        return True
    except OSError:
        return False


# ── la fiche d'une LIGNE de setlist ─────────────────────────────────────────────────────────
def line_sheet(line):
    """La fiche que CETTE ligne joue (docs/songs.md §9.7) : celle de sa chanson, surchargée par les
    SEULES clés que la ligne déclare dans `line_overrides` (« ce soir à 108 »).

    ⚠ POURQUOI PAS « la ligne gagne champ par champ » (la règle d'avant le 2026-09-22) : golem.fm
    pousse des lignes RÉSOLUES, qui portent une copie de la fiche. Avec cette règle, une retouche de la
    chanson au rack ne jouait jamais — la vieille copie de la ligne gagnait. `line_overrides` est le
    seul endroit qui distingue une exception d'une copie (§9.12 : « il débloque la propagation locale
    en v2 » — c'est la v2).

    Une ligne SANS `band_song` (ligne libre d'avant) est maîtresse de son contenu ; une chanson ABSENTE
    du rack (setlist reçue avant son répertoire) laisse la ligne jouer ce qu'elle porte."""
    if not isinstance(line, dict):
        return {}
    own = {k: line[k] for k in SHEET_FIELDS if k in line and line[k] not in (None, "")}
    bs = line.get("band_song")
    song = load(bs) if bs else None
    if not song:
        return own
    ov = [k for k in (line.get("line_overrides") or []) if k in own]
    return {**(song.get("sheet") or {}), **{k: own[k] for k in ov}}


def line_title(line):
    """Le titre affiché d'une ligne : le sien (l'exception « Toxicity (acoustic) »), sinon celui de
    sa chanson. Une ligne ajoutée depuis le répertoire n'en porte pas (§9.6)."""
    if not isinstance(line, dict):
        return None
    if line.get("title"):
        return line["title"]
    song = of_line(line)
    return (song or {}).get("title")


def of_line(line):
    """La chanson d'une ligne, ou None — pour l'écran, qui veut son titre et son id."""
    bs = (line or {}).get("band_song") if isinstance(line, dict) else None
    return load(bs) if bs else None


def wire_titles(lines):
    """Les lignes telles qu'elles PARTENT vers golem.fm : une ligne à chanson sans titre reçoit celui de
    sa chanson — sur le fil seulement (golemfm.push_setlist), jamais stocké : stocké, il deviendrait
    une exception du soir qui masquerait un renommage. Sans lui, une ligne née du répertoire s'affichait
    « — » chez golem.fm tant que leur route des chansons n'existe pas (§9.8.5)."""
    out = []
    for ln in lines or []:
        t = line_title(ln) if isinstance(ln, dict) and ln.get("band_song") and not ln.get("title") else None
        out.append({**ln, "title": t} if t else ln)
    return out


def setlists_of(sid, setlists=None):
    """Dans quelles setlists LOCALES cette chanson est jouée : [{id, name, slot}].
    `setlists` : la liste de `SL.list_all()` déjà chargée — la route /api/songs la passe pour ne pas relire
    toutes les setlists (et leurs presets) une fois PAR chanson (2026-10-19 : 15 chansons = 720 chargements).

    ⚠ C'est un compte LOCAL, et il ne remplace pas `song_setlists` que golem.fm pousse : eux
    savent toutes les setlists du groupe, nous seulement celles qu'on détient. Les deux cohabitent
    et l'écran doit dire lequel il montre (docs/setlists.md §9.12)."""
    out = []
    try:
        act = SL.active_id()
    except Exception:
        act = None
    for sl in (SL.list_all() if setlists is None else setlists):
        for i, ln in enumerate(sl.get("lines") or []):
            if ln.get("band_song") == sid:
                # `line` + `active` : l'accueil au démarrage d'une chanson se pose sur SA ligne de la setlist au pied
                # (2026-10-13 — une chanson s'ouvre avec le tempo, l'arrangement et le backing de sa ligne)
                out.append({"id": sl.get("id"), "name": sl.get("name"), "slot": i + 1, "line": ln.get("id"),
                            "active": sl.get("id") == act})
    return out


# ── réception d'un lot venu de golem.fm ─────────────────────────────────────────────────────
def merge_push(songs, band=None, complete=False):
    """Fusionne un lot de chansons poussé par golem.fm. Même arbitrage qu'une ligne (§9.6).

    Rend `{added, updated, kept, removed, resend}` — `resend` = les chansons que le RACK détient
    à un état plus récent, à renvoyer au prochain push. Elles ne sont jamais écrasées en silence :
    c'est la règle qui protège ce qui a réellement joué.

    `complete=True` : ce lot EST le répertoire de cet espace, les chansons locales absentes sont
    retirées. Sans ce drapeau, jamais de suppression — un lot partiel ne doit pas vider un rack.
    """
    have = {d["id"]: d for d in list_all()}
    seen, added, updated, kept, resend = set(), [], [], [], []
    for raw in (songs or []):
        d = clean(raw)
        if not d:
            continue
        if band and not d.get("band"):
            d["band"] = band
        seen.add(d["id"])
        cur = have.get(d["id"])
        if not cur:
            d.setdefault("pulled_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
            save(d, bump=False)
            added.append(d["id"])
            continue
        if int(d["rev"]) > int(cur["rev"]):
            save({**d, "pulled_at": cur.get("pulled_at")}, bump=False)
            updated.append(d["id"])
        elif int(d["rev"]) == int(cur["rev"]) and _body(d) == _body(cur):
            kept.append(d["id"])
        else:
            # rev égal + corps différent, ou rev inférieur : LE RACK GAGNE. Son état a joué.
            resend.append(cur["id"])
    # le rev REÇU est un rev que golem.fm a : noté, pour qu'une retouche locale ultérieure reparte
    # (et qu'une chanson reçue ne reparte pas telle quelle)
    got = {i: (load(i) or {}).get("rev") for i in added + updated + kept}
    if got:
        st = sync_state()
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        for i, r in got.items():
            if r:
                st[i] = {"rev": int(r), "at": now, "status": "pulled"}
        os.makedirs(C.SONGS_DIR, exist_ok=True)
        _write_json_atomic(_sync_path(), st)
    removed = []
    if complete:
        for sid, cur in have.items():
            if sid not in seen and (not band or cur.get("band") == band):
                if delete(sid):
                    removed.append(sid)
    return {"added": added, "updated": updated, "kept": kept, "removed": removed, "resend": resend}


def _body(d):
    """Le corps COMPARÉ : tout sauf le rev et ce qui n'est qu'une trace locale.

    ⚠ `pulled_at` est hors du corps pour la même raison que `song_setlists` l'est pour une ligne
    (docs/setlists.md §9.12) : il change sans que la chanson change, et le comparer produirait une
    boucle de `resend` sans fin. Ce piège a déjà été trouvé une fois par golem.fm avant le premier
    push ; on ne le rejoue pas."""
    return {k: v for k, v in (d or {}).items() if k not in ("rev", "pulled_at")}


def push_body(band=None):
    """Le lot à pousser vers golem.fm : toutes les chansons (d'un espace si `band` est donné).

    `complete: True` a le même sens que pour les setlists — ce lot EST ce que le rack détient."""
    rows = [d for d in list_all() if not band or d.get("band") == band]
    return {"band": band, "complete": True,
            "songs": [{k: v for k, v in d.items() if k in TOP_FIELDS and k != "pulled_at"} for d in rows]}


# ── LA MONTÉE VERS golem.fm (docs/songs.md §9.8, lot 4) ─────────────────────────────────────
# Contrat de leur `POST /api/ext/golem/songs` (leur agent, 2026-09-22) : une chanson par entrée,
# `band` DÉCLARÉ (jamais de repli sur le groupe du jeton), `kind` obligatoire pour une chanson née
# ici, `bpm` au premier niveau, la fiche SANS lui ; réponse toujours 200 avec un résultat PAR chanson
# (`applied[]` / `rejected[{id, why}]`). Quand le rack gagne, leur `rev` adopte le nôtre.
#
# `songs/.sync.json` = {id: {rev, at, status, band_song?, why?, rejected_rev?}} : le dernier rev
# ACCEPTÉ par golem.fm, ou la raison d'un refus. C'est une trace locale, jamais poussée ni comparée.
# Une chanson refusée ne repart que si elle a changé depuis (sinon « not a member of X » partirait
# à chaque geste, pour la même réponse).
def _sync_path():
    return os.path.join(C.SONGS_DIR, ".sync.json")


def sync_state():
    try:
        with open(_sync_path(), encoding="utf8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def sync_of(d, paired=True):
    """L'état de montée d'une chanson, tel que l'écran le dit : `synced` (golem.fm a ce rev),
    `pending` (partira au prochain aller-retour), `rejected` (+ `why`), `rack_only` (rack non apparié).
    Une chanson REÇUE de golem.fm y est notée au rev reçu (merge_push) : retouchée ici, elle repart."""
    if is_factory(d["id"]):
        return {"state": "factory"}
    e = sync_state().get(d["id"]) or {}
    rev = int(d.get("rev") or 1)
    if e.get("status") == "rejected" and int(e.get("rejected_rev") or 0) == rev:
        return {"state": "rejected", "why": e.get("why")}
    if int(e.get("rev") or 0) >= rev:
        return {"state": "synced", "rev": int(e["rev"])}
    return {"state": "pending" if paired else "rack_only"}


def is_factory(sid):
    """Une chanson d'USINE (library/factory/songs, docs/factory.md) : elle est à golem, pas à un groupe — elle ne monte
    jamais vers golem.fm, qui la refuserait faute d'espace (« band required »)."""
    from . import factory as _factory
    return _safe(sid) in _factory.ids("songs")


def wire_song(d):
    """Une chanson telle qu'elle PART (leur contrat) : `bpm` au premier niveau, la fiche sans lui."""
    sh = dict(d.get("sheet") or {})
    bpm = sh.pop("bpm", None)
    out = {"id": d["id"], "rev": int(d.get("rev") or 1), "band": d.get("band"), "title": d.get("title"),
           "kind": d.get("kind"), "born": d.get("born") or "web", "sheet": sh}
    if bpm is not None:
        out["bpm"] = bpm
    if d.get("song_slug"):
        out["song_slug"] = d["song_slug"]
    return out


def pending(ids=None):
    """Les chansons à faire monter : rev local au-delà du dernier rev accepté, pas refusées à CE rev.
    `ids` restreint (les chansons qu'une setlist cite). Une chanson sans nature, sans espace ou sans
    titre n'est pas envoyée — golem.fm la refuserait — et c'est dit dans `blocked`."""
    todo, blocked = [], []
    for d in list_all():
        if ids is not None and d["id"] not in ids:
            continue
        s = sync_of(d)
        if s["state"] in ("synced", "rejected", "factory"):
            continue
        why = None if d.get("kind") in KINDS else "kind is required: original or cover"
        why = why or (None if d.get("band") else "band required")
        if why:
            blocked.append({"id": d["id"], "why": why})
        else:
            todo.append(d)
    return todo, blocked


def apply_ack(resp, sent):
    """Range la réponse de golem.fm. `sent` = {id: rev envoyé}. Rend {applied, rejected} (des ids)."""
    st = sync_state()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    done, bad = [], []
    for a in (resp or {}).get("applied") or []:
        sid = a.get("id")
        if sid not in sent:
            continue
        st[sid] = {"rev": int(sent[sid]), "at": now, "status": a.get("status") or "applied",
                   **({"band_song": a["band_song"]} if a.get("band_song") else {})}
        done.append(sid)
    for r in (resp or {}).get("rejected") or []:
        sid = r.get("id")
        if sid not in sent:
            continue
        prev = st.get(sid) or {}
        st[sid] = {**{k: v for k, v in prev.items() if k in ("rev", "band_song")}, "at": now,
                   "status": "rejected", "why": str(r.get("why") or "rejected")[:200],
                   "rejected_rev": int(sent[sid])}
        bad.append(sid)
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    _write_json_atomic(_sync_path(), st)
    return {"applied": done, "rejected": bad}
