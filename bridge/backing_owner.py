# SPDX-License-Identifier: GPL-3.0-or-later
"""La backing appartient à la CHANSON (docs/song-backing.md, 2026-10-18).

Un preset est un rig : il sert plusieurs chansons et ne sait pas lesquelles. La backing qui joue est celle de la
chanson qu'on joue ; le preset, lui, a le LECTEUR (le bloc Backing Track : son pied) et la RÈGLE des stems — il sait
ce qu'on joue en live, puisqu'il connaît ses lanes. Ce module porte :
  · `rule(preset)`    — les familles de stems que ce preset coupe, et pourquoi ;
  · `apply(mix, ...)` — le mix JOUÉ : celui de la chanson, puis la règle du preset par-dessus ;
  · `used_by(pid)`    — les chansons et les lignes qui jouent ce preset, CALCULÉ (jamais stocké dans le preset) ;
  · `migrate()`       — l'ancien `backing.songs` des presets recopié sur leurs chansons et leurs lignes.
"""
from .golog import get

log = get("backing")

FAMILIES = ("guitar", "bass", "piano", "drums", "vocals", "other")
# le rôle d'une lane -> la famille de stems qu'elle joue
ROLE_FAMILY = {"guitar": "guitar", "bass": "bass", "voice": "vocals", "vocals": "vocals", "keys": "piano",
               "piano": "piano", "drums": "drums"}
_NO_INPUT = ("", "—", "NONE", None)


def block_of(preset):
    """Le bloc Backing Track du preset (le LECTEUR), ou None — sans lui, aucune backing ne joue."""
    for lane in ((preset or {}).get("config") or {}).values():
        for b in (lane or {}).get("blocks") or []:
            if isinstance(b, dict) and b.get("type") == "backing-track":
                return b
    return None


def own_parts(preset, imap=None):
    """{famille: libellé de la lane} — ce que CE preset joue sur ce golem : chaque lane qui a une entrée. Une lane
    « IN KO » (aucune entrée branchée) ne joue rien : sa famille n'est pas coupée."""
    from . import preset_view as PV
    if imap is None:
        try:
            from .store import _imap
            imap = _imap()
        except Exception:
            imap = None
    out = {}
    try:
        inputs = PV._inputs_summary(preset or {}, imap)
    except Exception:
        inputs = []
    for inp in inputs or []:
        fam = ROLE_FAMILY.get(str(inp.get("role") or "").lower())
        if fam and inp.get("in") not in _NO_INPUT and fam not in out:
            out[fam] = inp.get("name") or inp.get("role")
    return out


def rule(preset, imap=None):
    """{famille: raison} des stems que ce preset coupe dans TOUTES ses chansons. Les exceptions `stems` du bloc
    l'emportent : « play » lève la règle, « mute » coupe en plus."""
    b = block_of(preset)
    if not b:
        return {}
    params = b.get("params") or {}
    out = {}
    if params.get("mute_own", True) is not False:
        for fam, lane in own_parts(preset, imap).items():
            out[fam] = f"you play it — {str(lane).lower()} lane"
    for fam, how in (params.get("stems") or {}).items():
        if fam not in FAMILIES:
            continue
        if how == "play":
            out.pop(fam, None)
        elif how == "mute":
            out[fam] = "muted by this preset"
    return out


def apply(mix, muted_families, stems):
    """Le mix JOUÉ : celui de la chanson (`mix`, par stem ou par famille), puis la règle du preset. Un stem coupé
    par l'un OU l'autre est coupé ; la règle n'écrit jamais dans la chanson. `stems` = les stems de la chanson."""
    from .golemfm import expand_mix
    out = {k: dict(v) for k, v in (mix or {}).items()}
    for fam in muted_families or ():
        out[fam] = {**(out.get(fam) or {}), "mute": 1}
    return expand_mix(out, list(stems or []))


def used_by(pid):
    """Les chansons qui jouent ce preset et les lignes de setlist qui les jouent — CALCULÉ : le preset ne le sait
    pas. [{song, title, artist, lines: [{setlist, name, bank, line}]}] ; une ligne sans chanson compte à part."""
    from . import setlists as SL
    from . import songs as SG
    songs = {}
    for d in SG.list_all():
        if ((d.get("sheet") or {}).get("preset")) == pid:
            songs[d["id"]] = {"song": d["id"], "title": d.get("title"), "artist": d.get("artist"), "lines": []}
    loose = []
    try:
        lists = SL.list_all() if hasattr(SL, "list_all") else []
    except Exception:
        lists = []
    for sl in lists:
        sl = SL.load(sl.get("id")) if isinstance(sl, dict) and "lines" not in sl else sl
        for i, ln in enumerate((sl or {}).get("lines") or []):
            if SL.pid_of(ln) != pid:
                continue
            where = {"setlist": sl.get("id"), "name": sl.get("name"), "bank": i, "line": ln.get("id")}
            bs = ln.get("band_song")
            if bs and bs in songs:
                songs[bs]["lines"].append(where)
            elif bs:
                d = SG.load(bs) or {}
                songs[bs] = {"song": bs, "title": d.get("title") or ln.get("title"), "artist": d.get("artist"),
                             "lines": [where]}
            else:
                loose.append({**where, "title": ln.get("title")})
    return {"songs": list(songs.values()), "lines": loose}


def migrate():
    """L'ancien `backing.songs` d'un preset, recopié là où la backing vit désormais (docs/song-backing.md §5) :
    sur chaque CHANSON de ce preset qui n'a ni stems ni backing, et sur chaque LIGNE qui le joue sans chanson et
    sans backing. Idempotent ; rien n'est effacé (le champ du preset reste, ignoré). Rend le nombre de copies."""
    from . import golemfm, setlists as SL, songs as SG
    from .store import load_presets
    n = 0
    for p in load_presets():
        bk = p.get("backing")
        # deux formes anciennes : {songs: [{slug…}]} et une simple liste de slugs
        raw = (bk.get("songs") or []) if isinstance(bk, dict) else (bk if isinstance(bk, list) else [])
        legacy = [x if isinstance(x, str) else x.get("slug") for x in raw if isinstance(x, (str, dict))]
        legacy = [x for x in legacy if x]
        if not legacy:
            continue
        slug, pid = legacy[0], p.get("id")
        for d in SG.list_all():
            sh = d.get("sheet") or {}
            if sh.get("preset") != pid or sh.get("backing") or golemfm._golem_stems(d["id"]):
                continue
            try:
                SG.update(d["id"], backing=slug)
                n += 1
                log.info(f"backing : « {slug} » recopiée du preset {pid} sur la chanson {d.get('title')}")
            except Exception as e:
                log.warning(f"backing : chanson {d.get('title')} non migrée : {e}")
        try:
            lists = SL.list_all() if hasattr(SL, "list_all") else []
        except Exception:
            lists = []
        for meta in lists:
            sl = SL.load(meta.get("id")) or {}
            changed = False
            for ln in sl.get("lines") or []:
                if SL.pid_of(ln) == pid and not ln.get("band_song") and not ln.get("backing"):
                    ln["backing"] = slug
                    changed = True
                    n += 1
            if changed:
                try:
                    SL.save(sl)
                    log.info(f"backing : « {slug} » recopiée du preset {pid} sur les lignes de « {sl.get('name')} »")
                except Exception as e:
                    log.warning(f"backing : setlist {sl.get('name')} non migrée : {e}")
    return n
