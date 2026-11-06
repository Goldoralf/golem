# SPDX-License-Identifier: GPL-3.0-or-later
"""« GET THIS RECORDING » — le chemin légal vers l'audio (docs/private/song-sharing.md §2.6, plan-song-sharing.md lot 7).

golem.fm identifie l'enregistrement exact d'une chanson (empreinte → AcoustID → MusicBrainz → ISRC) et rend des
liens vers des marchands qui vendent sans DRM : `GET /api/ext/songs/{slug}/recording` (scope songs:read) →
`{isrc, mbid, lookup: {status, via, score}, links: [{store, label, url}]}`. Niveau 1 : un simple lien, aucun
contrat. Le but : que le chemin le plus simple dans golem soit le chemin légal.

Trois règles :
  · LE RACK NE DÉCLENCHE PAS L'IDENTIFICATION. Elle part chez golem.fm au premier affichage dans son lecteur (ou par
    une route de COMPTE, `/api/my/…`, que le jeton d'appareil n'ouvre pas). Tant qu'elle n'a pas eu lieu, l'écran le
    dit ; il n'invente pas de lien.
  · DES LIENS DE MARCHANDS, RIEN D'AUTRE. Seuls les `https://` passent : une URL d'un autre schéma (magnet:, file:…)
    ferait du bouton une incitation que §2.4 interdit (« personne ne renvoie vers une source »).
  · HORS LIGNE, LA DERNIÈRE RÉPONSE. Elle est gardée dans `songs/.recording.json` ({slug: {at, data}}). Et un
    manifeste qui porte `recording.mbid` / `recording.isrc` (golem.fm les y écrit après identification) donne au
    moins le lien MusicBrainz, sans réseau.
"""
import json
import os
import time
import urllib.parse

from . import config as C
from . import golemfile as G
from .golog import get

log = get("recording")

MB = "https://musicbrainz.org"


def _cache_path():
    return os.path.join(C.SONGS_DIR, ".recording.json")


def _cache():
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(slug, data):
    from .store import _write_json_atomic
    d = _cache()
    d[slug] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "data": data}
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    _write_json_atomic(_cache_path(), d)


def _links(raw):
    """Les liens de golem.fm, nettoyés : https seulement, un libellé, sans doublon d'URL."""
    out, seen = [], set()
    for x in raw or []:
        if not isinstance(x, dict):
            continue
        url = str(x.get("url") or "").strip()
        if not url.lower().startswith("https://") or url in seen or len(url) > 1000:
            continue
        seen.add(url)
        store = str(x.get("store") or "").strip()[:40]
        out.append({"store": store, "label": str(x.get("label") or store or "Store").strip()[:60], "url": url})
    return out


def _from_manifest(sid):
    """(isrc, mbid) que porte le `.golem` de la chanson (le golem, sinon un dossier de chansons)."""
    from . import songs
    try:
        m = G.read_manifest(songs.source_path(sid))
    except (G.GolemError, OSError):
        return None, None
    rec = m.get("recording") if isinstance(m.get("recording"), dict) else {}
    isrc, mbid = rec.get("isrc"), rec.get("mbid")
    return (isrc if isinstance(isrc, str) and isrc else None), (mbid if isinstance(mbid, str) and mbid else None)


def of_song(sid):
    """Ce qu'on sait de l'enregistrement d'une chanson : `{isrc, mbid, identified, links, source, at?}` ou None si la
    chanson est inconnue. `source` = golem.fm (réponse fraîche) | cache (golem.fm injoignable) | file (le manifeste
    seul) | none."""
    from . import songs, golemfm
    d = songs.load(sid)
    if not d:
        return None
    isrc, mbid = _from_manifest(sid)
    out = {"isrc": isrc, "mbid": mbid, "identified": bool(isrc or mbid), "links": [], "source": "file" if (isrc or mbid) else "none"}
    slug = d.get("song_slug")
    if slug:
        _base, token = golemfm._cfg()
        st, data = (golemfm._req("/api/ext/songs/%s/recording" % urllib.parse.quote(slug, safe=""), token=token,
                                   timeout=10) if token else (0, "not paired"))
        if st == 200 and isinstance(data, dict):
            _remember(slug, data)
            src, at = "golem.fm", None
        else:
            hit = _cache().get(slug) or {}
            data, src, at = hit.get("data"), "cache", hit.get("at")
            if st and st != 200:
                log.info("recording %s : golem.fm répond %s (%s)" % (slug, st, data if not isinstance(data, dict) else ""))
        if isinstance(data, dict):
            out["isrc"] = data.get("isrc") or out["isrc"]
            out["mbid"] = data.get("mbid") or out["mbid"]
            lk = data.get("lookup") if isinstance(data.get("lookup"), dict) else None
            out["identified"] = bool(out["isrc"] or out["mbid"])
            if lk:
                out["lookup"] = {k: lk.get(k) for k in ("status", "via", "score") if k in lk}
            out["links"] = _links(data.get("links"))
            out["source"] = src
            if at:
                out["at"] = at
    # le repli SANS RÉSEAU : MusicBrainz, d'après le manifeste (ou la dernière réponse)
    if not out["links"] and out["mbid"]:
        out["links"] = [{"store": "musicbrainz", "label": "MusicBrainz", "url": "%s/recording/%s" % (MB, urllib.parse.quote(out["mbid"]))}]
    elif not out["links"] and out["isrc"]:
        out["links"] = [{"store": "musicbrainz", "label": "MusicBrainz", "url": "%s/isrc/%s" % (MB, urllib.parse.quote(out["isrc"]))}]
    return out
