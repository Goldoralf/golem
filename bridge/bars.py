# SPDX-License-Identifier: GPL-3.0-or-later
"""LA CARTE DES MESURES D'UNE BACKING — docs/bars-format.md (FIGÉ, 2026-10-07).

Pourquoi : un morceau joué sans click n'a pas UN tempo (Paper Kite : 85 → 89 BPM, mesuré sur le stem de
batterie). À tempo fixe, le click décroche dès l'intro et les parties tombent à côté. golem.fm livre, pour
chaque chanson, l'instant RÉEL de chaque mesure (et de chaque temps) sur la timeline des stems ; le rack le
tire, le VALIDE, le range à côté des stems et s'en sert pour :
  - placer les changements de partie sur la mesure réelle (arrangement.plan / sample_marks) ;
  - jouer le click sur les temps réels (`ticks` -> item MIDI sur la piste Click, golem_backing.lua).

Doctrine (cues-format.md) : golem.fm produit, le rack valide, stocke et exécute. Une carte invalide est
rejetée EN ENTIER (jamais une moitié de carte) — le rack retombe alors sur le tempo de la fiche.
"""
import json
import os
import threading

from .golog import get

log = get("bars")

FILE = "bars.json"
TICKS_FILE = ".ticks.txt"          # les temps du click, un par ligne « ms accent » (golem_backing.lua)
_CACHE = {}                        # chemin -> (mtime, doc) ; une carte se relit à chaque plan()
# appelés avec le slug quand une carte arrive, change ou disparaît : la backing CHARGÉE doit reposer les temps
# de son click (app.py s'abonne) — sinon une carte reçue après le chargement n'aurait d'effet qu'au rappel suivant
listeners = []


def _changed(slug):
    for fn in list(listeners):
        try:
            fn(slug)
        except Exception as e:
            log.warning(f"bars : abonné en échec ({e})")


def _dir(slug):
    from . import golemfm
    return golemfm.song_dir(slug)


def path(slug):
    """La carte d'une backing. Clé = id de chanson (lot 1.5) : celle que porte son `.golem`, `sync/bars.json`
    (golem-format.md §8) ; clé = slug : celle de l'ancien cache."""
    from . import golemfm
    if golemfm.is_song_key(slug):
        return os.path.join(_dir(slug), "sync", FILE)
    return os.path.join(_dir(slug), FILE)


def validate(d, slug):
    """-> (doc, None) si la carte est conforme au §3, sinon (None, "pourquoi"). Rien n'est réparé."""
    if not isinstance(d, dict):
        return None, "not an object"
    if d.get("version") != 1:
        return None, f"unknown version {d.get('version')!r}"
    from . import golemfm
    in_golem = golemfm.is_song_key(slug)
    want = golemfm.golemfm_slug(slug) if in_golem else slug
    # une carte rangée dans un .golem PEUT ne pas porter de slug : un .golem ne mène à personne (song-sharing.md
    # §2.8, 2026-10-11) et le filtre de sortie le retire. S'il est là, il doit être le bon.
    if want and d.get("slug") != want and not (in_golem and d.get("slug") is None):
        return None, f"slug {d.get('slug')!r} is not {want!r}"
    bars = d.get("bars")
    if not isinstance(bars, list) or not bars:
        return None, "no bars"
    prev = -1
    for i, b in enumerate(bars):
        if not isinstance(b, dict):
            return None, f"bar #{i + 1} is not an object"
        if b.get("bar") != i + 1:
            return None, f"bar #{i + 1} is numbered {b.get('bar')!r} (1-based, contiguous)"
        ms, num, den = b.get("ms"), b.get("num"), b.get("den")
        if not isinstance(ms, (int, float)) or ms <= prev:
            return None, f"bar {i + 1}: ms {ms!r} is not after {prev}"
        if not (isinstance(num, int) and num > 0 and isinstance(den, int) and den > 0):
            return None, f"bar {i + 1}: bad meter {num!r}/{den!r}"
        prev = ms
    end = d.get("end_ms")
    if end is not None and (not isinstance(end, (int, float)) or end <= prev):
        return None, f"end_ms {end!r} is not after the last bar"
    for i, b in enumerate(bars):
        bt = b.get("beats")
        if bt is None:
            continue
        nxt = bars[i + 1]["ms"] if i + 1 < len(bars) else end
        if (not isinstance(bt, list) or len(bt) != b["num"] or bt[0] != b["ms"]
                or any(not isinstance(x, (int, float)) for x in bt)
                or any(bt[k] >= bt[k + 1] for k in range(len(bt) - 1))
                or (nxt is not None and bt[-1] >= nxt)):
            return None, f"bar {i + 1}: beats do not fit the bar"
    return d, None


def load(slug):
    """La carte VALIDÉE de cette backing, ou None (absente ou invalide — l'invalide est journalisé une fois
    par version du fichier)."""
    if not slug:
        return None
    p = path(slug)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None
    hit = _CACHE.get(p)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        doc, why = validate(json.load(open(p, encoding="utf8")), slug)
    except (OSError, ValueError) as e:
        doc, why = None, str(e)
    if why:
        log.warning(f"bars.json de {slug} rejeté : {why}")
    _CACHE[p] = (mt, doc)
    return doc


def slug_of(preset):
    """La backing que ce preset (tel que la chanson le joue) déclare — celle dont la carte s'applique."""
    songs = (((preset or {}).get("backing") or {}).get("songs")) or []
    return (songs[0] or {}).get("slug") if songs else None


def for_preset(preset):
    return load(slug_of(preset))


def _bar_len_s(doc, i):
    """Durée (s) de la mesure d'index i (0-based) ; la dernière : jusqu'à end_ms, sinon comme la précédente."""
    bars = doc["bars"]
    if i + 1 < len(bars):
        return (bars[i + 1]["ms"] - bars[i]["ms"]) / 1000.0
    if doc.get("end_ms") is not None:
        return (doc["end_ms"] - bars[i]["ms"]) / 1000.0
    return (bars[i]["ms"] - bars[i - 1]["ms"]) / 1000.0 if i > 0 else 2.0


def time_of(doc, bar, beat=1):
    """Instant (s, timeline des stems) du temps `beat` (1-based) de la mesure `bar` (1-based).

    Au-delà de la carte : on prolonge avec la durée de la dernière mesure (§4). Un temps sans `beats` est
    placé régulièrement dans la mesure."""
    bars = doc["bars"]
    bar = max(1, int(bar))
    beat = max(1, float(beat or 1))
    if bar > len(bars):
        last = len(bars) - 1
        one = _bar_len_s(doc, last)
        t0 = bars[last]["ms"] / 1000.0 + one * (bar - len(bars))
        return t0 + (beat - 1) * one / max(1, bars[last]["num"])
    b = bars[bar - 1]
    bt = b.get("beats")
    k = int(beat) - 1
    if bt and k < len(bt) and beat == int(beat):
        return bt[k] / 1000.0
    return b["ms"] / 1000.0 + (beat - 1) * _bar_len_s(doc, bar - 1) / max(1, b["num"])


def ticks(doc):
    """[(ms, accent)] — chaque temps du morceau, accent 1 sur le premier temps de la mesure. Un temps sans
    `beats` est interpolé régulièrement (et compté par stats())."""
    out = []
    for i, b in enumerate(doc["bars"]):
        bt = b.get("beats")
        if not bt:
            one = _bar_len_s(doc, i) * 1000.0
            bt = [b["ms"] + k * one / b["num"] for k in range(b["num"])]
        out += [(int(round(x)), 1 if k == 0 else 0) for k, x in enumerate(bt)]
    return out


def stats(doc):
    """Ce que l'écran dit de la carte : source, mesures, ancres, temps approximés."""
    if not doc:
        return {"present": False}
    bars = doc["bars"]
    approx = sum(1 for b in bars if not b.get("beats") or b.get("beats_source") == "interpolated")
    return {"present": True, "rev": doc.get("rev"), "source": doc.get("source"),
            "bars": len(bars), "confirmed": sum(1 for b in bars if b.get("confirmed")),
            "approx_beats": approx, "beats": not any(not b.get("beats") for b in bars)}


def write_ticks(slug):
    """Écrit les temps du click à côté des stems pour golem_backing.lua ; rend le chemin, ou None sans carte."""
    doc = load(slug)
    if not doc:
        return None
    p = os.path.join(_dir(slug), TICKS_FILE)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        for ms, acc in ticks(doc):
            f.write(f"{ms} {acc}\n")
    os.replace(tmp, p)
    return p


# ── téléchargement (§2) : le rack TIRE, auth appareil ─────────────────────────────────────────
def fetch(slug):
    """GET /api/ext/songs/{slug}/bars -> assets/backing/<slug>/bars.json. 404 = pas de carte (on retire une
    carte locale devenue sans objet). Une réponse invalide n'écrase JAMAIS une carte valide."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not token:
        return {"ok": False, "error": "not paired"}
    st, data = golemfm._req(f"/api/ext/songs/{slug}/bars", token=token, timeout=20)
    p = path(slug)
    if st == 404:
        if os.path.exists(p):
            os.remove(p)
            log.info(f"bars.json de {slug} retiré (plus de carte chez golem.fm)")
            _changed(slug)
        return {"ok": True, "present": False}
    if st != 200:
        return {"ok": False, "error": f"bars failed ({st})"}
    doc, why = validate(data, slug)
    if why:
        log.warning(f"bars.json de {slug} reçu invalide, ignoré : {why}")
        return {"ok": False, "error": why}
    os.makedirs(_dir(slug), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, p)
    log.info(f"bars.json de {slug} : rev {doc.get('rev')} · {len(doc['bars'])} mesures")
    _changed(slug)
    return {"ok": True, "present": True, "rev": doc.get("rev")}


def local_rev(slug):
    d = load(slug)
    return (d or {}).get("rev")


def refresh_async(songs):
    """Catalogue reçu : pour chaque chanson EN CACHE dont `bars_rev` diffère de la carte locale, on la retire
    en tâche de fond. `bars_rev` absent du catalogue (golem.fm d'avant le contrat) = on ne touche à rien."""
    todo = [s["slug"] for s in songs or []
            if s.get("cached") and "bars_rev" in s and s.get("bars_rev") != local_rev(s["slug"])]
    if not todo:
        return

    def run():
        for slug in todo:
            try:
                fetch(slug)
            except Exception as e:
                log.warning(f"bars.json de {slug} : {e}")
    threading.Thread(target=run, daemon=True).start()
