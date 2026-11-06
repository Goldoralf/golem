# SPDX-License-Identifier: GPL-3.0-or-later
"""Setlists — groupes de presets nommés, ordonnés, échangeables (contrat docs/setlists.md).

Une setlist est une LISTE ORDONNÉE DE RÉFÉRENCES : la position vaut numéro de bank au pied
(00-18 en accès direct sur le UnO, 19+ en saisie numérique). C'est l'objet VIVANT — on l'édite,
on la partage, et un preset retouché reste à jour partout, puisqu'elle ne contient que des ids.

⚠ La setlist ACTIVE n'est PAS un champ des setlists (deux fichiers pourraient se contredire) :
c'est une config globale, `config/setlist.json`. Même doctrine que le bloc Rec — la vérité vit à
UN endroit, tout le reste la lit. Et corollaire appris à nos dépens le 2026-07-27 : un simple
rappel ne doit JAMAIS réécrire une config globale.

L'INSTANTANÉ est un objet DIFFÉRENT et un geste explicite : il fige le CONTENU des presets dans
une archive datée, en lecture seule. La setlist ne prétend donc jamais protéger les sons — c'est
l'instantané qui le fait, et on sait qu'on l'a demandé. (Le vrai coût des copies n'est pas
l'octet, c'est la divergence : deux vérités pour un même son. D'où deux objets séparés.)
"""
import contextlib
import glob
import json
import os
import re
import time

from . import config as C
from .store import _read_json, _write_json_atomic, _safe_id, load_preset

ACTIVE_CFG = None        # None = config/setlist.json du dossier de config COURANT (_active_cfg) ; un test peut le poser
SNAP_DIR = os.path.join(C.SETLISTS_DIR, "snapshots")
DEFAULT_ID = "fcb-banks"          # la setlist historique : l'id ne bouge JAMAIS (importer,
                                  # preset_export et les backups le connaissent). Seul son NOM
                                  # affiché change — « Repertoire », celle de tous les jours.
DEFAULT_NAME = "Repertoire"       # un seul concept (setlist) ; la setlist par défaut n'est pas un
                                  # concert, c'est le répertoire courant — d'où un nom honnête.

# Décision 2026-07-28 : **une setlist = un concert, ça tient sur le pédalier**. 19 banks en
# accès direct au pied (UnO stompbox) = 19 slots, point. Ce n'est pas une limite de confort, c'est
# la taille du matériel : un 20e slot serait injouable. Le plafond est vérifié ICI (les routes s'y
# réfèrent) et c'est app.FCB_PHYS_BANKS qui pointe vers cette constante, pas l'inverse.
MAX_SLOTS = 19

# ── LA LIGNE (docs/setlists.md §9, FIGÉ 2026-09-08) ─────────────────────────────────────────
# Pas d'objet chanson sur le rack : la ligne de setlist EST le morceau — {id, rev, preset, title,
# song_slug, bpm} — plusieurs lignes peuvent porter le même preset, le preset reste le rig.
# `lines` est la vérité ; `presets: [ids]` est DÉRIVÉ et réécrit à chaque save pour les lecteurs
# d'avant (pied, pages, instantanés, backups). Une entrée nue d'une vieille liste vaut une ligne.
LINE_FIELDS = ("id", "rev", "preset", "title", "song_slug", "bpm", "backing", "arrangement", "blocks",
               # CE QU'IL FAUT PRÉPARER (docs/devices-people.md, lot F — page « Between songs ») : l'accordage
               # demandé, le capodastre, une note libre (« Ju prend l'acoustique »). Opaques pour le moteur.
               "tuning", "capo", "note",
               # ── LA CHANSON POSSÈDE SA FICHE DE SCÈNE (§9.12, FIGÉ 2026-09-18) ──────────────────────
               # Trois champs POSÉS PAR golem.fm et transportés tels quels — le rack les recopie, ne les
               # invente jamais, et n'en fabrique aucun pour une ligne née ici.
               #   band_song      « bs:<id> » — l'identité de la CHANSON du groupe. OPAQUE : même espace de
               #                  noms que le `target.id` des cibles COMPO (docs/compo.md §10), à ne pas casser.
               #                  ⚠ `song_slug` n'est PAS une identité : c'est un slug de CATALOGUE (§9.2).
               #   line_overrides les clés que CETTE ligne surcharge ; le reste est hérité de la chanson.
               #                  Ignoré par le rack en v1 — il débloque la propagation locale en v2.
               #   song_setlists  dans combien de setlists la chanson est jouée. L'autorité est chez eux : le
               #                  rack ne détient que ce qu'on lui a poussé (un compte local mentirait).
               "band_song", "line_overrides", "song_setlists",
               # ── UNE BANK DE SONS (docs/patches.md §7) : une ligne joue un PATCH — `{id, rev, patch,
               #    title}`, `title` toujours présent (golem.fm, §9 bis-8). Jamais dans une setlist de morceaux.
               "patch")
KINDS = ("songs", "sounds")          # fixé à la création : une setlist ne mélange pas morceaux et sons (§11)
PENDING_DIR = os.path.join(C.SETLISTS_DIR, ".pending")


def pid_of(line):
    """LA fonction qui rend l'id de preset d'une ligne — appelée par tous les consommateurs,
    jamais deux lectures de la forme. Accepte une ligne (dict), un id nu (str), None. "" = libre.

    Une ligne qui porte `band_song` joue le preset de SA CHANSON (docs/songs.md §9.7, 2026-09-22) —
    sauf si elle le surcharge (`line_overrides`). Avant, on lisait `line.preset` seul : une ligne
    ajoutée depuis le répertoire ({band_song} et rien d'autre) donnait une bank VIDE au pied."""
    if isinstance(line, dict):
        if line.get("patch"):                # une ligne de bank de sons joue un patch comme un preset
            return "patch:" + str(line["patch"])
        if line.get("band_song"):
            from . import songs as _songs
            return _songs.line_sheet(line).get("preset") or ""
        return line.get("preset") or ""
    return line or ""


def view_line(ln):
    """Ce que les ÉCRANS lisent d'une ligne : ce qu'elle JOUE (§9.7), pas ce qu'elle stocke.

    Une ligne ajoutée depuis le répertoire ne porte que `band_song` : sans cette vue, Live, le pupitre
    et le téléphone affichaient « New song · no preset yet » pour un morceau parfaitement prêt. La
    fiche jouée remplace les champs de fiche, le titre de la chanson comble un titre absent, et
    `song` dit d'où ça vient. ⚠ JAMAIS écrite : c'est une vue — les écritures de ligne passent par
    des champs explicites (`update_line`), et une ligne à chanson ne s'édite pas dans la setlist."""
    if not isinstance(ln, dict) or not ln.get("band_song"):
        return ln
    from . import songs as _songs
    song = _songs.load(ln["band_song"])
    if not song:
        return ln
    out = {k: v for k, v in ln.items() if k not in SCOPED_FIELDS}
    out.update(_songs.line_sheet(ln))
    out["title"] = ln.get("title") or song.get("title")
    out["song"] = {k: song[k] for k in ("id", "title", "artist", "kind", "born", "band") if k in song}
    return out


def view(sl):
    """La setlist telle que les écrans la lisent : ses lignes passées par `view_line`."""
    if not isinstance(sl, dict):
        return sl
    return {**sl, "lines": [view_line(ln) for ln in sl.get("lines") or []]}


def _new_line_id(sid):
    import uuid
    return f"r:{_safe_id(sid)}:{uuid.uuid4().hex[:8]}"


def _clean_line(ln, sid):
    """Une ligne propre : champs connus seulement, rev ≥ 1, bpm entier ou absent, id posé."""
    out = {}
    for k in LINE_FIELDS:
        if k in ln and ln[k] not in (None, ""):
            out[k] = ln[k]
    if "preset" in ln and ln["preset"] in (None, ""):
        out["preset"] = None                         # ligne SANS rig, gardée (§9.4)
    if out.get("patch"):
        out["patch"] = _safe_id(out["patch"])
        if not out.get("title"):                     # `title` toujours présent sur une ligne de patch (§9 bis-8)
            with contextlib.suppress(Exception):
                from . import patches as _P
                out["title"] = ((_P.get_patch(out["patch"]) or {}).get("name") or out["patch"])
            out.setdefault("title", out["patch"])
        out.pop("preset", None)
    out["id"] = str(out.get("id") or _new_line_id(sid))
    try:
        out["rev"] = max(1, int(out.get("rev") or 1))
    except (TypeError, ValueError):
        out["rev"] = 1
    if "bpm" in out:
        try:
            b = int(round(float(out["bpm"])))
            if 20 <= b <= 400:
                out["bpm"] = b
            else:
                out.pop("bpm")
        except (TypeError, ValueError):
            out.pop("bpm")
    if "title" in out:
        out["title"] = str(out["title"]).strip()[:120] or None
        if out["title"] is None:
            out.pop("title")
    # LOT 2 (docs/setlists.md §9, arrangement.md §4 corrigé) : l'ARRANGEMENT vit sur la ligne — le même
    # bloc que portait `preset.config.arr` ; le BACKING de la ligne = un slug de chanson (opaque).
    if "arrangement" in out:
        a = out["arrangement"]
        if isinstance(a, dict) and isinstance(a.get("params"), dict):
            out["arrangement"] = {**a, "type": "arrangement", "id": str(a.get("id") or "arr-line")}
        else:
            out.pop("arrangement")
    if "backing" in out:
        b = out["backing"]
        out["backing"] = str(b.get("slug") if isinstance(b, dict) else b).strip()[:120]
        if not out["backing"]:
            out.pop("backing")
    # LOT 3 (§9.9) : les BLOCS PAR MORCEAU — {id de bloc du preset: {bypass?, params?}}. On garde la
    # forme, pas le sens : c'est effective_preset qui sait quel bloc existe encore dans le rig.
    if "blocks" in out:
        out["blocks"] = clean_blocks(out["blocks"])
        if not out["blocks"]:
            out.pop("blocks")
    for k, n in (("tuning", 24), ("note", 140)):
        if k in out:
            out[k] = str(out[k]).strip()[:n]
            if not out[k]:
                out.pop(k)
    if "capo" in out:
        try:
            c = int(out["capo"])
            if 1 <= c <= 12:
                out["capo"] = c
            else:
                out.pop("capo")
        except (TypeError, ValueError):
            out.pop("capo")
    # §9.12 : trois champs de golem.fm, transportés — validés en FORME, jamais interprétés
    if "band_song" in out:
        out["band_song"] = str(out["band_song"]).strip()[:120]
        if not out["band_song"]:
            out.pop("band_song")
    if "line_overrides" in out:
        ov = out["line_overrides"]
        out["line_overrides"] = [str(x)[:40] for x in ov if x] if isinstance(ov, list) else []
        if not out["line_overrides"]:
            out.pop("line_overrides")
    if "song_setlists" in out:
        try:
            n = int(out["song_setlists"])
            out["song_setlists"] = n if n >= 0 else 0
        except (TypeError, ValueError):
            out.pop("song_setlists")
    return out


def clean_blocks(raw):
    """{bid: {bypass?: bool, params?: dict}} — tout le reste est jeté ; une entrée vide disparaît."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for bid, ov in raw.items():
        if not bid or not isinstance(ov, dict):
            continue
        e = {}
        if "bypass" in ov and ov["bypass"] is not None:
            e["bypass"] = bool(ov["bypass"])
        if isinstance(ov.get("params"), dict) and ov["params"]:
            e["params"] = dict(ov["params"])
        if e:
            out[str(bid)[:80]] = e
    return out


def add_line(sid, **fields):
    """Ajoute une ligne à la FIN (« + Add a song ») : id neuf, rev 1, champs validés. Rend la setlist
    (avec `line_id` posé dessus pour l'appelant), None si la setlist n'existe pas ou est pleine."""
    sl = load(sid)
    if not sl:
        return None
    if sl.get("kind") == "sounds" and not fields.get("patch"):
        return None                                  # une bank de sons ne prend que des patches (§11)
    if len(sl["lines"]) >= MAX_SLOTS:
        return {"error": f"the pedalboard has {MAX_SLOTS} banks — clear one first"}
    ln = _clean_line({k: v for k, v in fields.items() if k in LINE_FIELDS and k not in ("id", "rev")}, sid)
    ln["id"] = _new_line_id(sid)
    ln["rev"] = 1
    sl["lines"].append(ln)
    out = save(sl)
    out["line_id"] = ln["id"]
    return out


def add_songs(sid, song_ids):
    """« ＋ Add a song » (docs/songs.md §9.6) : des chansons du RÉPERTOIRE, en fin de setlist. Chaque
    ligne ne porte que `{id, rev, band_song}` — tout le reste se lit dans la chanson (§9.7). Une
    chanson inconnue du rack ou déjà dans la setlist est écartée et DITE (`skipped`), jamais ajoutée
    en silence. Rend la setlist + `added` (ids de lignes) + `skipped`, None si la setlist n'existe pas."""
    from . import songs as _songs
    sl = load(sid)
    if sl and sl.get("kind") == "sounds":
        raise ValueError("this is a sound list — songs go into a setlist of songs")
    if not sl:
        return None
    have = {ln.get("band_song") for ln in sl["lines"] if ln.get("band_song")}
    added, skipped, adopted = [], [], []
    for bs in song_ids or []:
        bs = str(bs or "")
        if not _songs.load(bs):
            skipped.append({"id": bs, "why": "unknown song"})
        elif bs in have:
            skipped.append({"id": bs, "why": "already in this setlist"})
        elif len(sl["lines"]) >= MAX_SLOTS:
            skipped.append({"id": bs, "why": f"the pedalboard has {MAX_SLOTS} banks"})
        elif not _adopt_for_stage(bs, skipped, adopted):
            pass
        else:
            ln = {"id": _new_line_id(sid), "rev": 1, "band_song": bs}
            sl["lines"].append(ln)
            have.add(bs)
            added.append(ln["id"])
    if added:
        sl["rev"] = int(sl.get("rev") or 1) + 1          # l'ordre a changé : c'est le rev de liste
        sl = save(sl)
    return {**sl, "added": added, "skipped": skipped, **({"adopted": adopted} if adopted else {})}


def _adopt_for_stage(bs, skipped, adopted):
    """CE QUI PART EN CONCERT EST SUR LE GOLEM (docs/song-folders.md §2.3) : une chanson lue dans un dossier de
    chansons est copiée dans le golem en entrant dans une setlist — un disque débranché le soir du concert, et elle
    serait muette. Rend False (et le dit dans `skipped`) si la copie échoue."""
    from . import songs as _songs
    try:
        if _songs.ensure_local(bs):
            adopted.append(bs)
        return True
    except _songs.InstallError as e:
        skipped.append({"id": bs, "why": str(e)})
        return False


def line_to_song(sid, line_id, kind, band=None):
    """« ◆ Make it a song » (§9.6) : la ligne LIBRE devient une chanson du répertoire, et la ligne ne
    garde que sa place et sa référence. Rev de ligne +1 (son contenu a changé). Rend
    `(setlist, chanson)`, None si inconnue ; lève ValueError (nature absente, ligne déjà liée)."""
    from . import songs as _songs
    from .store import load_preset
    sl = load(sid)
    if not sl:
        return None
    for ln in sl["lines"]:
        if ln.get("id") == line_id:
            pname = ((load_preset(ln.get("preset")) or {}).get("name")) if ln.get("preset") else None
            song = _songs.from_line(ln, kind, band=band, preset_name=pname)
            keep = {"id": ln["id"], "rev": int(ln.get("rev") or 1) + 1, "band_song": song["id"]}
            ln.clear(); ln.update(keep)
            return save(sl), song
    return None


def remove_line(sid, line_id, keep_slot=False):
    """Retire UNE ligne (« Remove from setlist », 2026-09-14) — jamais le preset qu'elle porte.
    Rev de LISTE +1 : l'ordre change, et c'est le rev de liste qui l'arbitre chez golem.fm ; le push
    miroir part avec `complete: true`, donc la ligne absente y est supprimée aussi (§9.5), pas
    ressuscitée à la synchro suivante. Rend la setlist, None si setlist ou ligne inconnue."""
    sl = load(sid)
    if not sl:
        return None
    if keep_slot:
        # VIDER UNE BANK (2026-10-08 : « on ne peut pas supprimer un preset assigné ») : la ligne part, mais
        # son RANG reste, vide — les banks suivantes ne bougent pas (un pédalier se joue de mémoire).
        idx = next((i for i, ln in enumerate(sl["lines"]) if ln.get("id") == line_id), None)
        if idx is None:
            return None
        sl["lines"][idx] = _clean_line({"preset": None}, sid)
        sl["rev"] = int(sl.get("rev") or 1) + 1
        return save(sl)
    keep = [ln for ln in sl["lines"] if ln.get("id") != line_id]
    if len(keep) == len(sl["lines"]):
        return None
    sl["lines"] = keep
    sl["rev"] = int(sl.get("rev") or 1) + 1
    return save(sl)


def place_song(sid, song_id, slot, cap=MAX_SLOTS):
    """RANGER UNE CHANSON dans une bank (sélecteur de bank, 2026-10-08) — en UNE écriture.

    Pourquoi : la bank est une LIGNE, et une ligne porte un preset seul OU une chanson (qui apporte son preset, son
    arrangement, ses stems). Le sélecteur ne savait ranger qu'un preset : vider puis remettre Paper Kite avait laissé une
    ligne « preset seul » — l'arrangement n'était plus joué par la bank. Ici :
      - la ligne de la chanson, si elle est déjà dans la setlist, quitte son ancien rang (qui devient VIDE) ;
      - les lignes « preset seul » du même preset deviennent vides : le preset arrive désormais avec la chanson ;
      - ce qui occupait la bank visée est REMPLACÉ (le geste « replace ? » du sélecteur) ; aucune autre bank ne bouge.
    Rend la setlist, None si inconnue ; ValueError (chanson inconnue, bank hors du pédalier, bank de sons)."""
    from . import songs as _songs
    sl = load(sid)
    if not sl:
        return None
    if sl.get("kind") == "sounds":
        raise ValueError("this is a sound list — songs go into a setlist of songs")
    song = _songs.load(song_id)
    if not song:
        raise ValueError(f"unknown song: {song_id}")
    try:
        _songs.ensure_local(song_id)                   # lue dans un dossier : copiée dans le golem (song-folders.md §2.3)
    except _songs.InstallError as e:
        raise ValueError(str(e)) from e
    if slot < 0 or (cap and slot >= cap):
        raise ValueError("bank out of the pedalboard")
    pid = ((song.get("sheet") or {}).get("preset")) or None
    lines = sl["lines"]
    while len(lines) <= slot:
        lines.append(_clean_line({"preset": None}, sid))
    line = None
    for k, ln in enumerate(lines):
        if ln.get("band_song") == song_id:
            line = ln
            lines[k] = _clean_line({"preset": None}, sid)
        elif pid and not ln.get("band_song") and not ln.get("title") and ln.get("preset") == pid:
            lines[k] = _clean_line({"preset": None}, sid)
    if line is None:
        line = {"id": _new_line_id(sid), "rev": 1, "band_song": song_id}
    lines[slot] = line
    sl["rev"] = int(sl.get("rev") or 1) + 1
    return save(sl)


def swap_lines(sid, i, j, cap=None):
    """ÉCHANGE deux banks (glisser-déposer du sélecteur de bank, 2026-10-08) : les lignes i et j changent de
    rang, tout ce qu'elles portent les suit ; une bank libre au-delà de la fin est créée vide. Rien d'autre ne bouge —
    un pédalier se joue de mémoire. Rend la setlist, None si inconnue ; ValueError hors du pédalier."""
    sl = load(sid)
    if not sl:
        return None
    if i < 0 or j < 0 or (cap and max(i, j) >= cap):
        raise ValueError("bank out of the pedalboard")
    if i == j:
        return sl
    while len(sl["lines"]) <= max(i, j):
        sl["lines"].append(_clean_line({"preset": None}, sid))
    sl["lines"][i], sl["lines"][j] = sl["lines"][j], sl["lines"][i]
    sl["rev"] = int(sl.get("rev") or 1) + 1
    return save(sl)


def line_by_id(sid, line_id):
    sl = load(sid)
    for ln in (sl or {}).get("lines") or []:
        if ln.get("id") == line_id:
            return ln
    return None


def _legacy_arrangement(pid):
    """Le bloc `arrangement` AVEC SES PARTIES que le preset portait avant le lot 2 (config.arr), ou None.

    ⚠ La garde « avec ses parties » date du 2026-09-16 : depuis que le bloc est revenu dans l'onglet ⚙
    pour porter la PÉDALE (docs/arrangement.md §4 bis), un preset en a un sans en avoir jamais eu de
    parties. Sans cette garde, la migration d'un vieux rack aurait posé un arrangement VIDE sur chaque
    ligne qui n'en avait pas — un objet qui a l'air d'exister et ne joue rien."""
    if not pid:
        return None
    try:
        from .arrangement import block_of
        blk = block_of(load_preset(pid))
        return blk if ((blk or {}).get("params") or {}).get("sections") else None
    except Exception:
        return None


def migrate_legacy_arrangements():
    """UNE FOIS, au démarrage : chaque ligne SANS arrangement dont le preset en portait un
    (config.arr, l'ancien lieu) le reçoit en copie (rev +1). Le preset n'est pas réécrit — son
    bloc devient une donnée morte que le Designer ne montre plus. Rend [(setlist, ligne)]."""
    done = []
    for path in sorted(glob.glob(os.path.join(C.SETLISTS_DIR, "*.json"))):
        d = _read_json(path, None)
        if not isinstance(d, dict) or not d.get("id"):
            continue
        normalize(d)
        changed = False
        for ln in d["lines"]:
            if ln.get("arrangement") or not pid_of(ln):
                continue
            blk = _legacy_arrangement(pid_of(ln))
            if blk:
                ln["arrangement"] = json.loads(json.dumps(blk)); ln["rev"] = int(ln.get("rev") or 1) + 1
                changed = True; done.append((d["id"], ln["id"]))
        if changed:
            save(d)
    return done


def normalize(sl):
    """Rend la setlist avec `lines` (vérité) ET `presets` (dérivé, ids ou ""). Idempotent ; une
    vieille liste nue devient des lignes `r:<sid>:<n>` rev 1."""
    if not isinstance(sl, dict):
        return sl
    sid = sl.get("id") or DEFAULT_ID
    if isinstance(sl.get("lines"), list):
        lines = [_clean_line(ln if isinstance(ln, dict) else {"preset": ln}, sid) for ln in sl["lines"]]
    else:
        lines = [_clean_line({"id": f"r:{_safe_id(sid)}:{i}", "preset": (pid or None)}, sid)
                 for i, pid in enumerate(sl.get("presets") or [])]
    sl["lines"] = lines
    sl["presets"] = [pid_of(ln) for ln in lines]
    if sl.get("kind") not in KINDS:
        sl["kind"] = "songs"                         # tout ce qui existe avant les banks de sons
    try:
        sl["rev"] = max(1, int(sl.get("rev") or 1))
    except (TypeError, ValueError):
        sl["rev"] = 1
    sl.setdefault("origin", "local")
    return sl


def line_at(sl, slot):
    lines = (sl or {}).get("lines") or []
    return lines[slot] if 0 <= slot < len(lines) else None


def set_presets(sl, pids):
    """Réconcilie l'ORDRE avec une liste d'ids (le geste des pages et du sélecteur de bank) sans
    perdre ce que les lignes portent : une ligne suit son preset (1re occurrence), "" garde une
    ligne sans rig déjà là, un id nouveau crée une ligne. Bump du rev de liste (l'ordre)."""
    normalize(sl)
    old = list(sl["lines"])
    used = set()
    out = []
    for i, pid in enumerate(pids or []):
        pid = str(pid or "")
        ln = None
        if pid:
            for j, o in enumerate(old):
                if j not in used and pid_of(o) == pid:
                    ln = o; used.add(j); break
            if ln is None and pid.startswith("patch:"):
                if sl.get("kind") != "sounds":
                    raise ValueError("this is a setlist of songs — patches go into a sound list")
                ln = _clean_line({"patch": pid[len("patch:"):]}, sl["id"])
            elif ln is None and sl.get("kind") == "sounds":
                raise ValueError("this is a sound list — songs go into a setlist of songs")
            if ln is None:
                ln = _clean_line({"preset": pid}, sl["id"])
                blk = _legacy_arrangement(pid)   # arrangement que le preset portait avant le lot 2
                if blk:
                    ln["arrangement"] = json.loads(json.dumps(blk))
        else:
            for j, o in enumerate(old):              # 1re ligne SANS rig pas encore reprise (titre seul) : conservée
                if j not in used and not pid_of(o):
                    ln = o; used.add(j); break
            if ln is None:
                ln = _clean_line({"preset": None}, sl["id"])
        out.append(ln)
    sl["lines"] = out
    sl["presets"] = [pid_of(ln) for ln in out]
    sl["rev"] = int(sl.get("rev") or 1) + 1
    return sl


def over_cap(presets):
    """Message d'erreur si la liste dépasse le pédalier, None sinon. On REFUSE au lieu de tronquer :
    tronquer perdrait un preset en silence, et l'utilisateur ne saurait pas lequel."""
    n = len(presets or [])
    if n <= MAX_SLOTS:
        return None
    return (f"{n} presets — the footswitch only reaches {MAX_SLOTS} banks (00-{MAX_SLOTS - 1}). "
            "A setlist is one gig : it has to fit on the pedalboard.")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _path(sid):
    return os.path.join(C.SETLISTS_DIR, f"{_safe_id(sid)}.json")


def _slug(name, taken=()):
    """Slug de fichier à partir d'un nom libre, unique parmi `taken`."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "setlist"
    out, n = s, 2
    while out in taken:
        out, n = f"{s}-{n}", n + 1
    return out


# ── setlist active (config globale) ──────────────────────────────────────────
def active_id():
    """Id de la setlist active. Repli sur la setlist historique, puis sur la 1re trouvée :
    le pied doit TOUJOURS avoir une source, même si la config a été supprimée à la main."""
    a = (_read_json(_active_cfg(), {}) or {}).get("active")
    if a and os.path.isfile(_path(a)):
        return a
    if os.path.isfile(_path(DEFAULT_ID)):
        return DEFAULT_ID
    # les FICHIERS, pas list_all() — qui appelle active_id() : sans liste désignée ni fcb-banks.json (un rack
    # neuf), les deux s'appelaient l'un l'autre sans fin (trouvé le 2026-09-30)
    ids = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(C.SETLISTS_DIR, "*.json")))
    return ids[0] if ids else DEFAULT_ID


def _active_cfg():
    """Le fichier de la liste au pied, calculé À L'APPEL : une constante figée au chargement du module
    ignorait le dossier de config du moment — un test a ainsi réécrit le vrai config/setlist.json (2026-09-30)."""
    return ACTIVE_CFG or os.path.join(C.CONFIG_DIR, "setlist.json")


def set_active(sid):
    if not os.path.isfile(_path(sid)):
        return {"ok": False, "error": f"unknown setlist: {sid}"}
    _write_json_atomic(_active_cfg(), {"active": _safe_id(sid)})
    return {"ok": True, "active": _safe_id(sid)}


# ── lecture / écriture ───────────────────────────────────────────────────────
def load(sid):
    d = _read_json(_path(sid), None)
    if not isinstance(d, dict):
        return None
    normalize(d)
    # Migration idempotente du NOM d'usage de la setlist par défaut (« FCB Banks » -> « Repertoire »,
    # 2026-07-28) : elle ne désigne pas un concert mais le répertoire courant. L'id ne bouge pas.
    # Un seul cas est réécrit — un nom que l'utilisateur aurait choisi lui-même n'est jamais touché.
    if d.get("id") == DEFAULT_ID and d.get("name") in ("FCB Banks", "fcb-banks"):
        d["name"] = DEFAULT_NAME
        _write_json_atomic(_path(DEFAULT_ID), d)
    return d


def save(sl):
    sl = {**sl, "id": _safe_id(sl.get("id")), "updated_at": _now()}
    sl.setdefault("presets", [])
    sl.setdefault("name", sl["id"])
    normalize(sl)                                    # `presets` dérivé des lignes, toujours
    _write_json_atomic(_path(sl["id"]), sl)
    return sl


# ── `scope` — OÙ VA UNE RETOUCHE FAITE ICI (§9.12, sens retour) ───────────────────────────────
# « song » : la modification va à la CHANSON, toutes ses setlists suivent. « line » : elle ne vaut que
# pour CE SOIR. C'est une CONSIGNE D'ÉCRITURE : elle dit où ça va, pas ce que la ligne EST — stockée
# sur la ligne, on ne saurait plus distinguer une ligne héritée d'une ligne surchargée à l'identique.
# Elle voyage donc à part, dans `sl["scopes"] = {line_id: {champ: scope}}`, et elle est EFFACÉE dès que
# le miroir est accepté (golemfm.push_setlist) : c'est une instruction en attente, pas un état.
# ⚠ UNE CONSIGNE PAR CHAMP, pas par ligne (golem.fm, 2026-09-18) : la consigne est par ÉCRITURE, mais
# le miroir FUSIONNE les écritures. Hors ligne, en répète : on corrige l'arrangement (scope `song`),
# puis on règle un tempo « tonight only » (scope `line`) sur la même ligne. Avec une consigne par
# ligne, la dernière gagnait et l'arrangement corrigé partait en exception du soir, sans que personne
# le sache. Une retouche ULTÉRIEURE du même champ remplace sa consigne — ça, c'est voulu.
# ⚠ Elle ne couvre QUE les champs de la FICHE — `title` (l'exception du soir « Toxicity (acoustic) »)
# et `song_slug` (l'attachement au catalogue, qui se change dans Band ▸ Songs) en sont EXCLUS.
SCOPES = ("song", "line")
SCOPED_FIELDS = ("preset", "bpm", "tuning", "capo", "note", "backing", "arrangement", "blocks")


def default_scope(mode=None):
    """Le défaut se LIT dans la carte du mode : « line » quand ce mode joue UN CONCERT (`take_kind`
    vaut `gig` — sur scène, ce qu'on retouche est ce soir), « song » partout ailleurs (en répète on
    corrige le morceau). Aucune énumération d'ids : une règle qui énumère rate le mode suivant.

    ⚠ CORRIGÉ le 2026-09-18 (golem.fm) : la première version lisait `ui.locked`. Il coïncide
    aujourd'hui — seul Gig est verrouillé — mais c'est une NATURE lue sur un champ déclaré pour AUTRE
    CHOSE : `ui.locked` ne commande que la sortie par appui long sur le logo (mesuré le matin même,
    docs/modes.md §7 bis). Un mode maison verrouillé pour qu'un enfant ne sorte pas du kiosque aurait
    rangé ses corrections de répète en « tonight only ». `take_kind` DIT la situation de jeu, et c'est
    le vocabulaire partagé avec golem.fm (Agenda, Recordings)."""
    from . import modes as _modes
    return "line" if _modes.take_kind(mode if mode is not None else _modes.current()) == "gig" else "song"


def update_line(sid, line_id, scope=None, **fields):
    """Édite UNE ligne : rev de ligne +1. Rend la setlist, None si inconnue. `bpm: None` retire le
    tempo (jamais 0, jamais celui du preset recopié). `scope` (§9.12) : la consigne d'écriture posée
    à part pour le prochain miroir — seulement si ce geste touche un champ de la FICHE."""
    sl = load(sid)
    if not sl:
        return None
    for ln in sl["lines"]:
        if ln.get("id") == line_id:
            # ── UNE LIGNE QUI JOUE UNE CHANSON DU RACK (docs/songs.md §9.7) ─────────────────────────
            # Ses champs de fiche ne jouent que s'ils sont déclarés dans `line_overrides`. Donc : portée
            # « song » -> la retouche va à la CHANSON (toutes ses setlists suivent), la ligne n'y touche
            # pas ; portée « line » -> la ligne la porte ET la déclare en exception. Sans ça, une retouche
            # de l'arrangement depuis le Designer s'écrivait sur la ligne et ne jouait jamais.
            from . import songs as _songs
            song = _songs.load(ln["band_song"]) if ln.get("band_song") else None
            if song:
                sheet_f = {k: v for k, v in fields.items() if k in SCOPED_FIELDS}
                if sheet_f and scope != "line":
                    _songs.update(song["id"], **sheet_f)
                    ov = [k for k in (ln.get("line_overrides") or []) if k not in sheet_f]
                    for k in sheet_f:
                        ln.pop(k, None)
                    ln["line_overrides"] = ov
                    fields = {k: v for k, v in fields.items() if k not in SCOPED_FIELDS}
                    if not fields:
                        cleaned = _clean_line(ln, sid)
                        cleaned["rev"] = int(ln.get("rev") or 1) + 1
                        ln.clear(); ln.update(cleaned)
                        return save(sl)
                elif sheet_f:
                    ov = list(ln.get("line_overrides") or [])
                    for k, v in sheet_f.items():
                        if v in (None, "") and k in ov:
                            ov.remove(k)              # vider l'exception = rendre le champ à la chanson
                        elif v not in (None, "") and k not in ov:
                            ov.append(k)
                    ln["line_overrides"] = ov
            for k, v in fields.items():
                if k not in LINE_FIELDS or k in ("id", "rev"):
                    continue
                if v in (None, "") or (k == "blocks" and v == {}):
                    if k == "preset":
                        ln["preset"] = None
                    else:
                        ln.pop(k, None)
                else:
                    ln[k] = v
            cleaned = _clean_line(ln, sid)
            cleaned["rev"] = int(ln.get("rev") or 1) + 1
            ln.clear(); ln.update(cleaned)
            touched = {k: scope for k in fields if k in SCOPED_FIELDS}
            if scope in SCOPES and touched:
                allsc = {**(sl.get("scopes") or {})}
                allsc[str(line_id)] = {**(allsc.get(str(line_id)) or {}), **touched}
                sl["scopes"] = allsc
            return save(sl)
    return None


# ── FUSION d'un push golem.fm (docs/setlists.md §9.5-9.6) ─────────────────────────────────────
# ⚠ `song_setlists` est une INFORMATION, pas du contenu de ligne (golem.fm, 2026-09-18) : le nombre
# change sans que la ligne change — ajouter un morceau à une 5e setlist fait passer de 4 à 5 le compte
# porté par les QUATRE autres lignes. Le comparer ici produisait une boucle de `resend` SANS FIN : rev
# égal + corps différent = le rack garde sa ligne et la renvoie, golem.fm repousse 5, et ainsi de
# suite. Il est donc hors du corps, et la valeur reçue remplace la locale quel que soit le rev
# (l'autorité est chez eux). `line_overrides`, lui, ne bouge qu'avec le contenu de la ligne — donc
# son rev monte avec, et il reste dans le corps.
BODY_EXCLUDED = ("id", "rev", "song_setlists")


def _line_body(ln):
    """Le corps COMPARÉ à rev égal. Pour une ligne qui joue une chanson (`band_song`), c'est ce qu'elle
    DÉCLARE — sa référence, ses exceptions (`line_overrides` et leurs valeurs) — et jamais les copies de
    la fiche que golem.fm y résout (titre, preset, tempo, slug…). Depuis le §9.7 (2026-09-22) le rack
    stocke une ligne ajoutée depuis le répertoire SANS ces copies : les comparer faisait diverger chaque
    push venu du web à rev égal, donc un `resend` à chaque fois, pour une différence qui ne joue pas."""
    body = {k: v for k, v in ln.items() if k not in BODY_EXCLUDED}
    if not ln.get("band_song"):
        return body
    ov = list(ln.get("line_overrides") or [])
    out = {k: v for k, v in body.items() if k not in SCOPED_FIELDS and k not in ("title", "song_slug")}
    out.update({k: body[k] for k in ov if k in body})
    return out


def _tomb_of_ours(inc, loc):
    """La ligne revient de golem.fm en « pierre tombale » (docs/songs.md §9.8.5) : notre chanson née ici
    leur est encore inconnue, ils ont gardé la ligne SANS `band_song` (preset nul, au mieux le titre que
    le rack leur a envoyé). À rev égal ce n'est pas une divergence — renvoyer n'y changerait rien tant que
    leur route des chansons n'existe pas. Lu dans `born`, jamais dans le préfixe."""
    bs = (loc or {}).get("band_song")
    if not bs or inc.get("band_song"):
        return False
    from . import songs as _songs
    if (_songs.load(bs) or {}).get("born") != "rack":
        return False
    rest = {k: v for k, v in _line_body(inc).items()
            if not (k == "preset" and v in (None, "")) and k not in ("title", "song_slug")}
    return rest == {k: v for k, v in _line_body(loc).items() if k != "band_song"}


def merge_push(doc):
    """Fusionne une setlist reçue dans la locale, par id de ligne et rev : supérieur gagne ; à
    égalité et contenu différent, le RACK gagne (son état a joué) et la ligne repart (resend) ;
    `complete: true` supprime les lignes absentes ; le rev de LISTE arbitre le nom et l'ordre.
    Rend (setlist sauvée, rapport). Ne pousse rien : l'appelant décide."""
    sid0 = _safe_id((doc or {}).get("id") or "")
    # UNE LISTE D'IDS SANS LIGNES sur une setlist qui EXISTE (le sélecteur de bank de golem.fm, qui ne connaît pas les
    # id ni les rev des lignes) : c'est le geste de notre propre page — set_presets, où une ligne suit son preset et
    # l'ordre bumpe le rev de liste. Sinon normalize en faisait des lignes `r:<sid>:<n>` en rev 1, battues par les
    # lignes locales : le changement fait sur le web était perdu sans un mot (comparaison du contrat, 2026-10-15).
    if sid0 and "lines" not in (doc or {}) and isinstance((doc or {}).get("presets"), list):
        cur0 = load(sid0)
        if cur0 is not None:
            set_presets(cur0, [str(p or "") for p in doc["presets"]])
            if doc.get("name"):
                cur0["name"] = str(doc["name"])
            if doc.get("fcb"):
                cur0["fcb_wanted"] = True            # un SOUHAIT, jamais une bascule (§9.6)
            return save(cur0), {"added": [], "updated": ["order"], "kept": [], "removed": [], "resend": []}
    inc = normalize(dict(doc))
    inc.pop("scopes", None)          # §9.12 : une consigne d'écriture ne voyage QUE du rack vers le web
    sid = _safe_id(inc.get("id") or "")
    if not sid:
        raise ValueError("setlist without an id")
    cur = load(sid)
    report = {"added": [], "updated": [], "kept": [], "removed": [], "resend": []}
    if cur is None:
        sl = {"id": sid, "name": inc.get("name") or sid, "origin": inc.get("origin") or "golem.fm",
              "rev": inc["rev"], "lines": inc["lines"], "created_at": _now(),
              "kind": inc.get("kind") if inc.get("kind") in KINDS else "songs"}   # la nature naît avec la liste
        if inc.get("fcb"):
            sl["fcb_wanted"] = True                  # un SOUHAIT, jamais une bascule (§9.6)
        report["added"] = [ln["id"] for ln in inc["lines"]]
        return save(sl), report
    by_id = {ln["id"]: ln for ln in cur["lines"]}
    merged = {}

    def _info(win, incoming):
        """`song_setlists` : l'autorité est chez golem.fm — la valeur reçue remplace la locale quel
        que soit le rev, y compris sur une ligne que le rack vient de gagner."""
        if "song_setlists" in incoming:
            win["song_setlists"] = incoming["song_setlists"]
        elif "song_setlists" in win:
            win.pop("song_setlists")
        return win

    def _keep_ref(win, loc):
        """§9.7 : golem.fm ne sait pas encore résoudre une chanson NÉE ICI tant qu'elle n'est pas montée
        (lot 4) — chez eux la ligne devient une « pierre tombale » qui perd son `band_song`, et elle
        revient sans. On ne perd JAMAIS une référence que l'autre côté ne sait pas encore résoudre :
        la ligne gagnante reprend le `band_song` local. Lu dans le champ `born`, pas dans le préfixe."""
        bs = (loc or {}).get("band_song")
        if bs and not win.get("band_song"):
            from . import songs as _songs
            if (_songs.load(bs) or {}).get("born") == "rack":
                win = {**win, "band_song": bs}
                report.setdefault("kept_ref", []).append(win["id"])
        return win

    for ln in inc["lines"]:
        loc = by_id.get(ln["id"])
        if loc is None:
            merged[ln["id"]] = ln; report["added"].append(ln["id"])
        elif ln["rev"] > loc["rev"]:
            merged[ln["id"]] = _keep_ref(ln, loc); report["updated"].append(ln["id"])
        elif ln["rev"] == loc["rev"] and (_line_body(ln) == _line_body(loc) or _tomb_of_ours(ln, loc)):
            merged[ln["id"]] = _info(loc, ln); report["kept"].append(ln["id"])
        else:                                        # égalité et différence, ou rev inférieur : le rack gagne
            merged[ln["id"]] = _info(loc, ln); report["kept"].append(ln["id"]); report["resend"].append(ln["id"])
    complete = bool(inc.get("complete"))
    inc_ids = [ln["id"] for ln in inc["lines"]]
    local_only = [ln for ln in cur["lines"] if ln["id"] not in merged]
    if complete:
        report["removed"] = [ln["id"] for ln in local_only]
        local_only = []
    # nom et ORDRE : le rev de liste arbitre
    inc_rev, cur_rev = int(inc.get("rev") or 1), int(cur.get("rev") or 1)
    if inc_rev > cur_rev:
        order = inc_ids + [ln["id"] for ln in local_only]
        cur["name"] = inc.get("name") or cur.get("name"); cur["rev"] = inc_rev
    else:                                            # le rack garde SON ordre ; les nouvelles lignes du web viennent après
        local_ids = [ln["id"] for ln in cur["lines"]]
        order = [i for i in local_ids if i in merged or i in {ln["id"] for ln in local_only}]
        order += [i for i in inc_ids if i not in set(local_ids)]
        if inc.get("name") != cur.get("name") or inc_ids != local_ids:
            report["resend"].append("*order*")
    all_lines = {**{ln["id"]: ln for ln in local_only}, **merged}
    cur["lines"] = [all_lines[i] for i in order if i in all_lines]
    if inc.get("fcb"):
        cur["fcb_wanted"] = True
    cur["origin"] = cur.get("origin") or inc.get("origin") or "golem.fm"
    return save(cur), report


def _locked_now():
    try:
        from . import modes as _modes
        return bool(((_modes.current() or {}).get("ui") or {}).get("locked"))
    except Exception:
        return False


def receive_push(doc):
    """Le job `setlist-push`. JAMAIS sous les pieds : en mode verrouillé (Gig/Show), un push qui
    touche la setlist ACTIVE ou demande le pied attend le changement de mode (fichier .pending/).
    Rend le rapport ({deferred: true} si mis en attente)."""
    sid = _safe_id((doc or {}).get("id") or "")
    if not sid:
        raise ValueError("setlist without an id")
    if _locked_now() and (sid == active_id() or doc.get("fcb")):
        os.makedirs(PENDING_DIR, exist_ok=True)
        _write_json_atomic(os.path.join(PENDING_DIR, f"{sid}.json"), doc)
        return {"setlist": sid, "deferred": True, "reason": "locked mode — applied at the next mode change"}
    sl, report = merge_push(doc)
    return {"setlist": sid, "deferred": False, **{k: v for k, v in report.items()}}


def apply_pending():
    """Applique les pushs mis en attente (appelé à la bascule de mode). Rend la liste des ids."""
    done = []
    if _locked_now() or not os.path.isdir(PENDING_DIR):
        return done
    for path in sorted(glob.glob(os.path.join(PENDING_DIR, "*.json"))):
        doc = _read_json(path, None)
        try:
            if isinstance(doc, dict):
                merge_push(doc); done.append(_safe_id(doc.get("id") or ""))
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)
    return done


def forget_preset(pid):
    """Un preset SUPPRIMÉ (geste explicite) quitte toutes les setlists — son emplacement devient
    LIBRE (None), jamais retiré : retirer décalerait les banks suivantes sous les pieds. Rend le
    nombre d'emplacements libérés. ⚠ Ne vaut que pour une suppression volontaire : un preset
    absent du disque reste sinon un état normal (setlist reçue avant ses presets)."""
    pid = _safe_id(pid)
    freed = 0
    for path in sorted(glob.glob(os.path.join(C.SETLISTS_DIR, "*.json"))):
        d = _read_json(path, None)
        if not isinstance(d, dict):
            continue
        normalize(d)
        hit = [ln for ln in d["lines"] if pid_of(ln) == pid]
        if not hit:
            continue
        for ln in hit:
            ln["preset"] = None
        freed += len(hit)
        d["updated_at"] = _now()
        normalize(d)
        _write_json_atomic(path, d)
    return freed


def list_all():
    """Toutes les setlists, enrichies pour l'UI : nombre de presets, presets MANQUANTS, active.
    Un preset absent du disque est un état NORMAL (setlist reçue, preset pas encore synchronisé) :
    on le signale, on ne casse rien."""
    act = active_id()
    out = []
    for p in sorted(glob.glob(os.path.join(C.SETLISTS_DIR, "*.json"))):
        d = _read_json(p, None)
        if not isinstance(d, dict) or not d.get("id"):
            continue
        if d["id"] == DEFAULT_ID:
            d = load(DEFAULT_ID) or d      # passe par load() : c'est lui qui porte la migration du nom
        normalize(d)
        pids = [pid_of(ln) for ln in d["lines"] if pid_of(ln)]
        missing = [pid for pid in pids if load_preset(pid) is None]
        out.append({**d, "count": len(d["lines"]), "missing": missing,
                    "active": d["id"] == act,
                    "default": d["id"] == DEFAULT_ID})
    out.sort(key=lambda s: (not s["active"], (s.get("name") or "").lower()))
    return out


# ── gestes ───────────────────────────────────────────────────────────────────
def create(name, presets=None, kind="songs"):
    """`kind` : « songs » (setlist de morceaux, défaut) ou « sounds » (bank de patches) — FIXÉ à la création
    (docs/patches.md §11) : une setlist ne change jamais de nature."""
    taken = {s["id"] for s in list_all()}
    sid = _slug(name, taken)
    kind = kind if kind in KINDS else "songs"
    return save({"id": sid, "name": (name or sid).strip(), "fcb": True, "rev": 1, "kind": kind,
                 "presets": list(presets or []) if kind == "songs" else [], "origin": "local", "created_at": _now()})


def add_patches(sid, patch_ids):
    """Ajoute des PATCHES à une bank de sons (Songs ▸ Patches ▸ Add to a bank). Refus dits : une setlist
    de morceaux, un patch inconnu, la bank pleine (19 slots). Rend la bank."""
    from . import patches as _P
    sl = load(sid)
    if not sl:
        raise ValueError(f"unknown setlist {sid}")
    if sl.get("kind") != "sounds":
        raise ValueError("this is a setlist of songs — patches go into a sound list")
    for pid in patch_ids or []:
        doc = _P.get_patch(_safe_id(pid))
        if not doc:
            raise ValueError(f"unknown patch {pid}")
        if len(sl["lines"]) >= MAX_SLOTS:
            raise ValueError(f"the list is full ({MAX_SLOTS} banks on the pedalboard)")
        sl["lines"].append(_clean_line({"patch": doc["id"], "title": doc.get("name") or doc["id"]}, sl["id"]))
    sl["rev"] = int(sl.get("rev") or 1) + 1
    return save(sl)


def forget_patch(pid):
    """Un patch SUPPRIMÉ libère ses lignes dans les banks de sons — même geste que `forget_preset` : la ligne
    reste (son titre dit ce qu'il y avait), elle ne joue plus rien. Rend les ids de banks touchées."""
    pid = _safe_id(pid)
    touched = []
    for path in glob.glob(os.path.join(C.SETLISTS_DIR, "*.json")):
        d = _read_json(path, None)
        if not isinstance(d, dict) or d.get("kind") != "sounds":
            continue
        normalize(d)
        hit = False
        for ln in d["lines"]:
            if ln.get("patch") == pid:
                ln.pop("patch", None)
                ln["rev"] = int(ln.get("rev") or 1) + 1
                hit = True
        if hit:
            save(d)
            touched.append(d["id"])
    return touched


def duplicate(sid, name=None):
    src = load(sid)
    if not src:
        return None
    return create(name or f"{src.get('name', sid)} (copy)", src.get("presets") or [])


def rename(sid, name):
    sl = load(sid)
    if not sl or not (name or "").strip():
        return None
    sl["name"] = name.strip()
    return save(sl)


def remove(sid):
    """Supprime une setlist. JAMAIS les presets qu'elle référence (ils vivent leur vie, et un
    preset peut appartenir à plusieurs setlists). La setlist ACTIVE ne se supprime pas : on
    obligerait l'utilisateur à réparer sa config pour que le pied refonctionne."""
    if _safe_id(sid) == active_id():
        return {"ok": False, "error": "this setlist is on the pedalboard — put another one on it first"}
    p = _path(sid)
    if not os.path.isfile(p):
        return {"ok": False, "error": "setlist not found"}
    os.remove(p)
    return {"ok": True}


# ── instantanés (le geste qui fige VRAIMENT les sons) ────────────────────────
# Audit 2026-10-15 : l'instantané ne voyait que des ids de presets. Une ligne de bank de sons (`patch:<id>`)
# était figée comme un preset COMPOSÉ, puis restaurée en `presets/patch<id>.json` (via _safe_id) — un preset
# fantôme, et le patch jamais rendu. Les données de ligne (titre, bpm, arrangement…) étaient perdues aussi.
# Désormais : un patch est figé comme PATCH (son document, sous son id de patch) et les lignes sont gardées.
def _frozen_item(pid):
    """Ce que l'instantané garde pour un id de ligne : `{id, patch}` pour `patch:<id>`, `{id, preset}` sinon."""
    if str(pid).startswith("patch:"):
        from . import patches as _P
        doc = _P.get_patch(str(pid)[len("patch:"):])
        return {"id": pid, "patch": doc} if isinstance(doc, dict) else None
    p = load_preset(pid)
    return {"id": pid, "preset": p} if p is not None else None


def snapshot(sid, name=None):
    """Archive datée, EN LECTURE SEULE : les lignes de la setlist + le CONTENU de chaque preset ou patch.
    C'est le filet avant de tout remplacer — la seule chose qui permette de revenir en arrière
    sur les SONS, ce qu'une setlist en références ne fera jamais."""
    sl = load(sid)
    if not sl:
        return {"ok": False, "error": "setlist not found"}
    order = [pid_of(ln) for ln in sl.get("lines") or []]
    items, missing, seen = [], [], set()
    for pid in order:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        it = _frozen_item(pid)
        if it is None:
            # ce qui n'a PAS pu être figé : le dire plutôt que de laisser croire à une archive complète
            missing.append(pid)
        else:
            items.append(it)
    os.makedirs(SNAP_DIR, exist_ok=True)
    snid = time.strftime("%Y%m%d-%H%M%S") + "-" + _safe_id(sid)
    _write_json_atomic(os.path.join(SNAP_DIR, f"{snid}.json"), {
        "id": snid, "kind": "snapshot", "of": sl["id"], "list_kind": sl.get("kind") or "songs",
        "name": (name or sl.get("name") or sl["id"]).strip(),
        "created_at": _now(), "order": order,
        # les LIGNES telles quelles (titre, bpm, arrangement, backing…) : l'ordre seul n'est pas le concert
        "lines": json.loads(json.dumps(sl.get("lines") or [])),
        "presets": items,
        "missing": missing,
    })
    return {"ok": True, "id": snid, "frozen": len(items)}


def list_snapshots():
    out = []
    for p in sorted(glob.glob(os.path.join(SNAP_DIR, "*.json")), reverse=True):
        d = _read_json(p, None)
        if isinstance(d, dict) and d.get("kind") == "snapshot":
            out.append({k: d.get(k) for k in ("id", "name", "of", "created_at", "missing")}
                       | {"count": len(d.get("presets") or [])})
    return out


def _restore_plan(d):
    """Ce qu'une restauration écrirait : [(type, id, doc)] avec type « preset » ou « patch », + ce qui ne se
    restaure pas (un ancien instantané a figé un `patch:` comme preset composé : il n'a pas le document du patch)."""
    from . import patches as _P
    plan, skipped = [], []
    for it in d.get("presets") or []:
        if not isinstance(it, dict):
            continue
        rid = str(it.get("id") or "")
        if isinstance(it.get("patch"), dict):
            plan.append(("patch", _P._safe_id(rid[len("patch:"):] if rid.startswith("patch:") else
                                              it["patch"].get("id")), it["patch"]))
        elif rid.startswith("patch:"):
            skipped.append(rid)                  # JAMAIS en preset « patchx » : un preset fantôme, pas le patch
        elif isinstance(it.get("preset"), dict):
            plan.append(("preset", _safe_id(rid or it["preset"].get("id")), it["preset"]))
    return plan, skipped


def _current(kind, xid):
    if kind == "patch":
        from . import patches as _P
        return _P.get_patch(xid)
    return load_preset(xid)


def restore(snid, as_name=None, overwrite=False):
    """Réécrit les presets et patches figés sur le disque, puis crée une setlist qui remet les lignes.
    Un preset ou patch de MÊME id qui a changé depuis est un CONFLIT : sans `overwrite`, RIEN n'est écrit et
    la liste des conflits revient — on prévient AVANT d'écraser, pas après (audit 2026-10-15)."""
    d = _read_json(os.path.join(SNAP_DIR, f"{_safe_id(snid)}.json"), None)
    if not isinstance(d, dict) or d.get("kind") != "snapshot":
        return {"ok": False, "error": "snapshot not found"}
    from .store import migrate_config, ensure_volume
    from . import patches as _P
    plan, skipped = _restore_plan(d)
    conflicts = []
    for kind, xid, doc in plan:
        cur = _current(kind, xid)
        if cur is not None and cur != {**doc, "id": xid}:
            conflicts.append(("patch:" + xid) if kind == "patch" else xid)
    if conflicts and not overwrite:
        return {"ok": False, "conflicts": conflicts,
                "error": f"{len(conflicts)} sound{'s' if len(conflicts) > 1 else ''} changed since this snapshot "
                         f"and would be overwritten: {', '.join(conflicts)}"}
    written, patches_written = [], []
    for kind, xid, doc in plan:
        doc = {**doc, "id": xid}
        if kind == "patch":
            _P._write(doc)
            patches_written.append(xid)
        else:
            migrate_config(doc)
            ensure_volume(doc)
            _write_json_atomic(os.path.join(C.PRESETS_DIR, f"{xid}.json"), doc)
            written.append(xid)
    name = as_name or f"{d.get('name') or d['of']} (restored)"
    kind = d.get("list_kind") if d.get("list_kind") in KINDS else "songs"
    if isinstance(d.get("lines"), list):
        # les lignes revivent dans une liste NEUVE : ids neufs (la synchro golem.fm compare par id de ligne)
        sl = create(name, [], kind)
        sl["lines"] = [_clean_line({**ln, "id": None, "rev": 1}, sl["id"]) for ln in d["lines"] if isinstance(ln, dict)]
        sl = save(sl)
    else:                                         # instantané d'avant 2026-10-15 : l'ordre seul
        order = list(d.get("order") or written)
        if "list_kind" not in d and any(str(p).startswith("patch:") for p in order):
            kind = "sounds"                       # un ancien instantané de bank de sons : ses lignes jouaient des patches
        keep = [str(p or "") for p in order if str(p or "").startswith("patch:") == (kind == "sounds")]
        sl = save(set_presets(create(name, [], kind), keep))
    return {"ok": True, "setlist": sl["id"], "presets": written, "patches": patches_written,
            "overwritten": conflicts, "skipped": skipped}
