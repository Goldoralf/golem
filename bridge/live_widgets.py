# SPDX-License-Identifier: GPL-3.0-or-later
"""Les données des widgets des pages de /live (docs/live-pages.md §5) — ce qui n'est pas déjà dans l'état publié.

Paroles : `lyrics/song.lrc` du `.golem` de la chanson qui joue. Le `.golem` est retrouvé par la clé de sa backing
(`rs-…`) : une ligne de setlist qui joue une chanson enregistrée porte cette clé. Les temps du `.lrc` sont ceux de
l'enregistrement — la timeline des stems, celle que l'arrangement suit quand la backing joue (`song_pos`).
"""
import re

from . import golemfm

_LRC = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_cache = {}                                              # (chemin, mtime) -> lignes


def parse_lrc(text):
    """[(secondes, texte)] triées ; une ligne à plusieurs horodatages (refrain) apparaît à chacun. Les balises
    d'en-tête ([ar:], [ti:]…) et les lignes vides sont ignorées ; un texte vide après un horodatage est GARDÉ (un
    silence voulu entre deux phrases)."""
    out = []
    for raw in (text or "").splitlines():
        stamps = _LRC.findall(raw)
        if not stamps:
            continue
        words = _LRC.sub("", raw).strip()
        for m, s in stamps:
            out.append((int(m) * 60 + float(s), words))
    out.sort(key=lambda x: x[0])
    return out


def song_key(state):
    """La clé `rs-…` de la chanson enregistrée qui joue, ou None (un morceau d'usine n'en a pas)."""
    for k in (((getattr(state, "backing", None) or {}).get("slug")), ((getattr(state, "song", None) or {}).get("backing")),
              ((getattr(state, "song", None) or {}).get("slug"))):
        if k and golemfm.is_song_key(k):
            return k
    return None


def lyrics(state):
    """{key, lines: [[t, text]]} des paroles de la chanson qui joue, ou {key, lines: []} — le widget s'efface alors."""
    import os
    key = song_key(state)
    if not key:
        return {"key": None, "lines": []}
    from . import golemfile as G, songs as _songs
    path = _songs.source_path(key)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {"key": key, "lines": []}
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return {"key": key, "lines": hit[1]}
    try:
        m = G.read_manifest(path)
        arc = next((a for a in sorted(m.get("files") or {}) if a.startswith("lyrics/") and a.endswith(".lrc")), None)
        lines = [[round(t, 2), w] for t, w in parse_lrc(G.read_member(path, arc).decode("utf-8", errors="replace"))] if arc else []
    except (G.GolemError, OSError, KeyError):
        lines = []
    _cache[path] = (mt, lines)
    return {"key": key, "lines": lines}
