# SPDX-License-Identifier: GPL-3.0-or-later
"""Standards jouables — la grille d'accords devient une section rythmique.

Contrat : `docs/standards.md`. Le rack tient piano + basse (+ batterie via le bloc drums),
le musicien joue le thème par-dessus. Un standard **se transpose** : c'est tout l'intérêt,
et aucune piste audio ne le fera jamais.

── LE FORMAT VIENT DE golem.fm, ON NE L'INVENTE PAS ──
golem.fm expose 1382 standards au format **iReal Pro** (dataset mikeoliphant/JazzStandards) :

    { "Title", "Composer", "Key", "Rhythm", "TimeSignature",
      "Sections": [ { "Label": "A", "MainSegment": { "Chords": "Dm7,G7|Cmaj7|..." },
                      "Endings": [ { "Chords": "..." } ] } ] }

    `|` sépare les MESURES · `,` sépare les SUBDIVISIONS dans une mesure
    subdivision vide = l'accord précédent tient · `(X)` = substitution (affichée, pas jouée)

On CONSOMME ce format tel quel (doctrine : « on COPIE ce qu'on fabrique, on RÉFÉRENCE ce
qu'on reçoit »). Le corpus a été dépouillé avant d'écrire la grammaire ci-dessous :
55 272 symboles, **77 suffixes distincts**, aucun autre — la grammaire est donc FERMÉE et
vérifiable (voir `tools/check-standards.py`).

⚠ Deux pièges du corpus, mesurés :
  · `Cm/maj7` (mineur-majeur) s'écrit AVEC UNE BARRE — un split naïf sur `/` en fait une
    basse `/maj7` et l'accord ne sonne pas. 212 occurrences. On le traite AVANT le slash.
  · `Rhythm` est une ÉTIQUETTE (« Medium Swing »), pas un tempo. Le BPM sort d'une table
    (TEMPO_BY_RHYTHM) : c'est une convention de style, jamais une déduction.

── CE QUE CE MODULE PRODUIT ──
Une liste d'événements `(ppq, note, vel, lane)` pour la grille entière, prête à être écrite
en gmem par `golem_chordseq.lua` et jouée à l'échantillon près par `golem_chordseq.jsfx`.
Tout le musical est ICI, en Python, testable sans Reaper — le Lua ne fait que transporter.
"""
import json
import os
import re
import unicodedata

from . import config
from . import grooves as _G     # lecteur SMF, pour les grooves joués (§6 ter)

PPQ = 960                      # ticks/noire — même résolution que golem_drums
LANE_KEYS = 0                  # canal MIDI 1 : accords (piano/EP/orgue)
LANE_BASS = 1                  # canal MIDI 2 : basse
LANE_DRUMS = 2                 # canal MIDI 3 : batterie (notes General MIDI)
# canal MIDI 4 : LE CLIC. Il vit dans la MÊME liste d'événements que les accords — donc sur la
# même tête de lecture, à l'échantillon près, par construction. C'est la réponse au
# problème de phase (2026-08-09) et elle est meilleure que la précédente : deux horloges mises
# d'accord laissaient un résidu d'un bloc audio ; une seule horloge n'en laisse aucun.
LANE_CLICK = 3
CLICK_ACCENT = 76             # le « 1 » de la mesure
CLICK_BEAT = 77               # les autres temps
CLICK_SUB = 78                # les subdivisions

# ── registres (MIDI) ─────────────────────────────────────────────────────────────────────
KEYS_LO, KEYS_HI = 55, 79      # G3..G5 — là où vivent les voicings sans fondamentale
BASS_LO, BASS_HI = 28, 52      # E1..E3

PC_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


# ═════════════════════════════════════════════════════════════════════════════════════════
# 1. LA GRAMMAIRE DES SYMBOLES
# ═════════════════════════════════════════════════════════════════════════════════════════
# Noyaux, du PLUS LONG au plus court : l'ordre EST l'algorithme (« maj7 » doit gagner
# contre « m », « m7b5 » contre « m7 »). Chaque entrée : demi-tons depuis la fondamentale.
_CORES = [
    ("m/maj7", [0, 3, 7, 11]),   # le piège à barre — traité en premier
    # mineur-majeur 9 et diminué-majeur 7 (2026-11-09) : `EmMaj9`, `Ebdimmaj7` rendaient None dans 21 grilles du
    # corpus synchronisé — l'accord ne sonnait pas. AVANT `mmaj7` et `dim7`/`dim` (premier préfixe qui colle).
    ("mmaj9",  [0, 3, 7, 11, 14]),
    ("mmaj7",  [0, 3, 7, 11]),
    ("maj13",  [0, 4, 7, 11, 14, 21]),
    ("maj9",   [0, 4, 7, 11, 14]),
    ("maj7",   [0, 4, 7, 11]),
    ("m7b5",   [0, 3, 6, 10]),
    ("m11",    [0, 3, 7, 10, 14, 17]),
    ("m69",    [0, 3, 7, 9, 14]),
    ("m9",     [0, 3, 7, 10, 14]),
    ("m7",     [0, 3, 7, 10]),
    ("m6",     [0, 3, 7, 9]),
    ("mb6",    [0, 3, 7, 8]),
    ("maug",   [0, 3, 8]),
    ("m",      [0, 3, 7]),
    # ⚠ On lit les DEUX écritures. `07`/`0` viennent d'iReal ; `dim7`/`dim` sont ce qu'on
    # ÉCRIT dans notre propre format (docs/standards-format.md) — et ils manquaient, alors
    # que la spec les promettait. Trouvé en comparant nos grilles aux références : `C#dim7`
    # rendait None, donc l'accord n'aurait pas sonné.
    ("dimmaj7", [0, 3, 6, 11]),
    ("dim7",   [0, 3, 6, 9]),
    ("dim",    [0, 3, 6]),
    ("07",     [0, 3, 6, 9]),    # iReal : dim7
    ("0",      [0, 3, 6]),       # iReal : dim triade
    ("aug",    [0, 4, 8]),
    ("add9",   [0, 4, 7, 14]),
    ("alt",    [0, 4, 10, 13, 20]),   # 7alt = 7 b9 #9 b13 — squelette, altéré ensuite
    ("69",     [0, 4, 7, 9, 14]),
    ("13",     [0, 4, 7, 10, 14, 21]),
    ("11",     [0, 4, 7, 10, 14, 17]),
    ("9",      [0, 4, 7, 10, 14]),
    ("7",      [0, 4, 7, 10]),
    ("6",      [0, 4, 7, 9]),
    ("5",      [0, 7]),
    ("",       [0, 4, 7]),       # majeur nu
]
# Altérations : (motif, degré visé en demi-tons naturels, décalage). Appliquées APRÈS le
# noyau ; une altération qui vise un degré absent l'AJOUTE (7b9 = 7 + un 9 bémol).
_ALTS = [("b5", 7, -1), ("#5", 7, +1), ("b9", 14, -1), ("#9", 14, +1),
         ("#11", 17, +1), ("b13", 21, -1), ("#13", 21, +1)]

# Notes AJOUTÉES à n'importe quel noyau (2026-11-09) : `madd9`, `7add11`, `m7add13`. Le noyau `add9` reste pour le
# majeur nu (`Cadd9`) ; ici l'ajout se lit APRÈS un autre noyau. `add3` vit avec `sus` (plus bas) : la tierce GARDÉE.
_ADDS = [("add9", 14), ("add11", 17), ("add13", 21)]

_SYM_RE = re.compile(r"^([A-G][#b]?)(.*)$")


def _pc(name):
    """`Bb` -> 10. Rend None sur autre chose (jamais lever ici : le corpus décide)."""
    if not name:
        return None
    n = name[0].upper()
    if n not in _STEP:
        return None
    v = _STEP[n]
    for c in name[1:]:
        if c == "#":
            v += 1
        elif c == "b":
            v -= 1
        else:
            return None
    return v % 12


def parse_symbol(sym):
    """`Am7b5` -> {root, ints, bass, quality, sym}. Rend None si illisible.

    Un symbole que le rack ne sait pas lire est un accord qui NE SONNE PAS en plein
    morceau : on préfère un None franc (loggué par l'appelant) à un accord approximatif.
    """
    if not sym:
        return None
    s = sym.strip()
    if s in ("N.C.", "NC", "n.c."):
        return {"root": None, "ints": [], "bass": None, "quality": "N.C.", "sym": "N.C."}

    # `m/maj7` n'est PAS une basse (212 occurrences) — et il peut en PORTER une
    # (`Am/maj7/G#`). On le normalise AVANT toute logique de slash.
    s = re.sub(r"m/maj7", "mmaj7", s, flags=re.I)
    s = re.sub(r"6/9", "69", s)            # absent du corpus, fréquent sous une main humaine

    bass = None
    if "/" in s:
        s, _, b = s.partition("/")
        bass = _pc(b.strip())
        if bass is None:
            return None

    m = _SYM_RE.match(s.strip())
    if not m:
        return None
    root = _pc(m.group(1))
    if root is None:
        return None
    suf = m.group(2).strip()

    # `sus` se retire d'où qu'il vienne (`7sus`, `9sus`, `7b9sus`, `13sus`)
    sus = False
    if "sus" in suf:
        sus = True
        suf = suf.replace("sus4", "").replace("sus2", "").replace("sus", "")
    # `7sus4add3` : la quarte suspendue ET la tierce (une couleur de jazz) — sans ceci, `add3` restait un reliquat
    add3 = "add3" in suf
    suf = suf.replace("add3", "")

    rest = suf.lower()
    ints = None
    for core, iv in _CORES:
        if rest.startswith(core):
            ints = list(iv)
            rest = rest[len(core):]
            break
    if ints is None:
        return None

    # `7alt` : l'altéré total (b9 #9 b13, PAS de quinte juste). S'écrit après le noyau
    # `7`, donc il ne peut pas être un noyau lui-même — il se traite ici.
    if "alt" in rest:
        rest = rest.replace("alt", "")
        ints = [i for i in ints if i != 7] + [13, 15, 20]

    for pat, deg in _ADDS:
        if pat in rest:
            rest = rest.replace(pat, "")
            ints = ints + [deg]
    for pat, deg, off in _ALTS:
        if pat in rest:
            rest = rest.replace(pat, "")
            ints = [i for i in ints if i != deg] + [deg + off]
    if rest.strip():                       # reliquat = symbole hors grammaire
        return None

    if sus:                                # la tierce cède la place à la quarte
        ints = [i for i in ints if i not in (3, 4)] + [5]
    if add3:                               # … sauf si on l'a demandée en plus
        ints = ints + [4]

    ints = sorted(set(ints))
    return {"root": root, "ints": ints, "bass": bass,
            "quality": suf or "maj", "sym": sym.strip()}


def chord_pcs(ch):
    """Classes de hauteur de l'accord (fondamentale incluse)."""
    if not ch or ch["root"] is None:
        return []
    return [(ch["root"] + i) % 12 for i in ch["ints"]]


def transpose_symbol(sym, semis):
    """Transpose un symbole EN TEXTE, en gardant sa qualité telle quelle."""
    ch = parse_symbol(sym)
    if not ch or ch["root"] is None:
        return sym
    out = PC_NAMES[(ch["root"] + semis) % 12]
    m = _SYM_RE.match(sym.strip().split("/")[0] if "/maj7" not in sym.lower() else sym.strip())
    tail = sym.strip()[len(m.group(1)):] if m else ""
    if ch["bass"] is not None and "/" in tail:
        head, _, _b = tail.partition("/")
        return out + head + "/" + PC_NAMES[(ch["bass"] + semis) % 12]
    return out + tail


# ═════════════════════════════════════════════════════════════════════════════════════════
# 2. LE CATALOGUE (cache local du dataset golem.fm)
# ═════════════════════════════════════════════════════════════════════════════════════════
STD_DIR = os.path.join(config.ROOT, "library", "standards")
# ⚠ N'EST PLUS une source du produit : le rack ne consulte aucun corpus (cf. _load_raw).
# Ce chemin ne sert qu'à `tools/seed-standards.py`, qui simule une synchro golem.fm.
STD_FILE = os.path.join(STD_DIR, "jazz-standards.json")

# `Rhythm` est une étiquette de style : le tempo conventionnel sort d'ICI, il ne se devine
# pas. L'utilisateur corrige ensuite dans le preset (preset.bpm reste LA vérité).
TEMPO_BY_RHYTHM = {
    "medium swing": 132, "up tempo swing": 220, "medium up swing": 168, "slow swing": 92,
    "ballad": 62, "waltz": 132, "bossa nova": 150, "samba": 190, "latin": 160,
    "latin-swing": 150, "afro": 140, "calypso": 150, "funk": 104, "rock pop": 120,
    "slow rock": 76, "medium slow": 100, "even 8ths": 130, "even 16ths": 120,
}
# étiquette iReal -> `feel` du bloc (ce qui change le comping ET le swing des croches)
FEEL_BY_RHYTHM = {
    "medium swing": "swing", "up tempo swing": "swing", "medium up swing": "swing",
    "slow swing": "swing", "latin-swing": "swing", "ballad": "ballad",
    "waltz": "waltz", "bossa nova": "bossa", "samba": "samba", "latin": "latin",
    "afro": "latin", "calypso": "latin", "funk": "funk", "rock pop": "even",
    "slow rock": "ballad", "medium slow": "ballad", "even 8ths": "even", "even 16ths": "even",
}
# groove conseillé pour le bloc drums (simple indice — l'utilisateur remplace)
GROOVE_BY_FEEL = {"swing": "swing-medium", "ballad": "ballad", "bossa": "bossa",
                  "samba": "samba", "latin": "latin", "funk": "funk", "even": "rock",
                  "waltz": "jazz-waltz"}

_cache = {"sig": None, "by_slug": {}, "list": []}


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "untitled"


SYNCED_DIR = os.path.join(STD_DIR, "synced")
GOLEM_DIR = os.path.join(STD_DIR, "golem")             # lot 10 : les standards en .golem (golemfm.standards_sync)


def invalidate():
    """Force la relecture (appelé après une synchro golem.fm)."""
    _cache["sig"] = None


def _sig():
    """Signature du cache : le dossier synchronisé, et les .golem de la bibliothèque (leurs grilles, lot 10)."""
    parts = []
    try:
        for fn in sorted(os.listdir(SYNCED_DIR)):
            if fn.endswith(".json"):
                parts.append((fn, os.path.getmtime(os.path.join(SYNCED_DIR, fn))))
    except OSError:
        pass
    try:
        for fn in sorted(os.listdir(GOLEM_DIR)):
            if fn.endswith(".golem"):
                parts.append(("g:" + fn, os.path.getmtime(os.path.join(GOLEM_DIR, fn))))
    except OSError:
        pass
    try:
        for fn in sorted(os.listdir(config.SONGS_DIR)):
            if fn.endswith(".golem"):
                parts.append((fn, os.path.getmtime(os.path.join(config.SONGS_DIR, fn))))
    except OSError:
        pass
    from . import song_folders
    parts.append(("folders", song_folders.sig()))         # les standards des dossiers de chansons (song-folders.md)
    return tuple(parts)


SONG_PREFIX = "song-"


def _golem_standards():
    """Les standards rangés en .golem (lot 10 : `library/standards/golem/<slug>.golem`, tirés de golem.fm). La grille
    est `chart/song.gsx` ; le slug, le nom du fichier (`golemfm.standard` du manifeste est ignoré : song-sharing.md §2.8)."""
    from . import golemfile as G
    out = []
    try:
        files = sorted(os.listdir(GOLEM_DIR))
    except OSError:
        return out
    for fn in files:
        if not fn.endswith(".golem") or fn.startswith("."):
            continue
        p = os.path.join(GOLEM_DIR, fn)
        try:
            m = G.read_manifest(p)
            raw = json.loads(G.read_member(p, "chart/song.gsx").decode("utf-8"))
        except (G.GolemError, OSError, ValueError):
            continue
        if not (is_gsx(raw) or raw.get("Sections")):
            continue
        slug = fn[:-6]                                  # <slug>.golem ; `golemfm.standard` ignoré (song-sharing.md §2.8)
        out.append(dict(raw, _slug=slug, _synced=True, _golem_id=m.get("id")))
    return out


def _folder_standards(have):
    """Les standards des DOSSIERS DE CHANSONS (docs/song-folders.md §2.3) : joués sur place, en lecture seule
    (`_folder` = le fichier). Un slug que le golem a déjà n'y est pas : la copie du golem fait foi."""
    from . import golemfile as G, song_folders
    out = []
    for slug, p, gid in song_folders.standards_entries():
        if slug in have:
            continue
        try:
            raw = json.loads(G.read_member(p, "chart/song.gsx").decode("utf-8"))
        except (G.GolemError, OSError, ValueError):
            continue
        if not (is_gsx(raw) or raw.get("Sections")):
            continue
        out.append(dict(raw, _slug=slug, _synced=False, _golem_id=gid, _folder=p))
    return out


def song_slug(sid):
    """Le slug de standard de la grille d'une chanson : `song-<id portable>` (pas de deux-points : il nomme aussi la
    surcouche locale, un fichier)."""
    from . import songs as _songs
    return SONG_PREFIX + _songs._safe(sid)


def _song_charts():
    """Les grilles portées par les chansons de la bibliothèque — `chart/song.gsx` de leur .golem (golem-format.md
    §6 bis, plan lot 10). Le bloc Standard les joue comme les autres : même format, lu tel quel."""
    from . import golemfile as G, songs as _songs
    out = []
    for d in _songs.list_all():
        path = _songs._path(d["id"])
        try:
            raw = json.loads(G.read_member(path, "chart/song.gsx").decode("utf-8"))
        except (G.GolemError, OSError, ValueError):
            continue                                       # pas de grille dans ce fichier : rien à proposer
        if not is_gsx(raw):
            continue
        raw = dict(raw, _slug=song_slug(d["id"]), _song=d["id"], _synced=False)
        raw.setdefault("title", d.get("title") or d["id"])
        out.append(raw)
    return out


def _load_raw():
    """Les grilles présentes sur le rack — **rien d'autre**.

    ── LE RACK NE CONNAÎT PAS DE CATALOGUE ──────────────────────────────────────────────
    Décision le mainteneur (2026-08-03) : le rack n'affiche pas une liste de standards, il **reçoit**
    ce que golem.fm lui envoie (« Send to <golem> », job song-install). Ce n'est plus un miroir
    des étoiles (2026-10-08) : `golemfm.standards_sync` met à jour ce que le rack a, sans rien
    ajouter ni retirer ; retirer est un geste au golem.

    Conséquence directe : une seule source, `library/standards/synced/`. Il n'y a plus de
    corpus de repli à consulter — pour travailler avant que l'endpoint golem.fm existe,
    `tools/seed-standards.py` installe des grilles À LA PLACE d'une synchro, et le dit.
    """
    sig = _sig()
    if _cache.get("sig") == sig:
        return _cache["list"]

    by_slug, out = {}, []
    try:
        files = sorted(os.listdir(SYNCED_DIR))
    except OSError:
        files = []
    for fn in files:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(SYNCED_DIR, fn), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        env = r.get("_golem") or {}
        r = dict(r, _slug=env.get("slug") or fn[:-5], _synced=True,
                 _synced_at=env.get("synced_at"), _seeded=bool(env.get("seeded")))
        by_slug[r["_slug"]] = r
        out.append(r)
    for r in _golem_standards():                           # les standards en .golem : ils FONT FOI sur l'ancien JSON
        if r["_slug"] in by_slug:
            out = [x for x in out if x.get("_slug") != r["_slug"]]
        by_slug[r["_slug"]] = r
        out.append(r)
    for r in _folder_standards(set(by_slug)):              # lus SUR PLACE dans un dossier : le golem gagne toujours
        by_slug[r["_slug"]] = r
        out.append(r)
    for r in _song_charts():                               # les grilles des chansons (.golem), lot 10
        by_slug[r["_slug"]] = r
        out.append(r)

    _cache.update(sig=sig, by_slug=by_slug, list=out)
    return out


def _infer_key(r):
    """17 % des grilles n'ont pas de tonalité — or c'est ce qui rend la transposition
    possible, donc on ne peut pas s'en passer.

    Heuristique assumée : le DERNIER accord de la forme est la tonique (vrai pour la
    quasi-totalité des standards, qui résolvent). Le mode suit sa qualité. On marque
    `key_inferred` pour que l'UI le dise et que l'utilisateur puisse corriger.
    """
    last = None
    for sec in r.get("Sections", []):
        seg = sec.get("MainSegment")
        if not seg:
            continue
        for bar in seg["Chords"].split("|"):
            for c in _parse_bar(bar, 4):
                ch = parse_symbol(c["sym"])
                if ch and ch["root"] is not None:
                    last = ch
    if not last:
        return None
    minor = last["quality"].lower().startswith("m") and not \
        last["quality"].lower().startswith("maj")
    return PC_NAMES[last["root"]] + ("min" if minor else "")


SHAPE_BARS = 32                                     # l'aperçu d'une carte : les 32 premières mesures (golem.fm)


def _shape(g):
    """(forme, [accords par mesure]) d'une grille, pour la CARTE (golem.fm StandardCard, 2026-10-17) : la forme = les
    lettres des sections dans l'ordre joué (« AABA ») ; l'aperçu = le nombre d'accords de chacune des 32 premières
    mesures — une barre par mesure, plus haute quand l'harmonie bouge."""
    secs = {s.get("id"): s for s in g.get("sections") or []}
    order = g.get("order") or [s.get("id") for s in g.get("sections") or []]
    form, shape = [], []
    for sid in order:
        sec = secs.get(sid if isinstance(sid, str) else (sid or {}).get("id"))
        if not sec:
            continue
        form.append(re.sub(r"[^A-Za-z]", "", str(sec.get("label") or ""))[:1])
        for bar in sec.get("bars") or []:
            if len(shape) < SHAPE_BARS:
                shape.append(sum(1 for c in bar or [] if (c or {}).get("sym")))
    return "".join(form), shape


def _meta(r):
    if is_gsx(r):                                   # .gsx : tout est déjà explicite
        g = _gsx_grid(r, r.get("_slug") or r.get("slug"))
        form, shape = _shape(g)
        return {"slug": g["slug"], "title": g["title"], "composer": g["composer"],
                "key": g["key"], "key_inferred": False, "rhythm": g["rhythm"],
                "meter": g["meter"], "beats": g["beats"], "feel": g["feel"],
                "groove": g["groove"], "tempo": g["tempo"], "bars": g["bars"],
                "sections": len(g["sections"]), "form": form, "shape": shape, "synced": bool(r.get("_synced", True)),
                "synced_at": r.get("_synced_at"), "seeded": bool(r.get("_seeded")),
                "v": g["v"], "source": g["source"], **({"song": r["_song"]} if r.get("_song") else {}),
                **({"folder": r["_folder"]} if r.get("_folder") else {})}
    rhythm = (r.get("Rhythm") or "Medium Swing")
    key = r.get("Key")
    inferred = False
    if not key:
        key, inferred = _infer_key(r), True
    feel = FEEL_BY_RHYTHM.get(rhythm.lower(), "swing")
    sig = r.get("TimeSignature") or "4/4"
    try:
        beats = int(sig.split("/")[0])
    except ValueError:
        beats = 4
    bars = sum(len((seg or {}).get("Chords", "").split("|"))
               for sec in r.get("Sections", [])
               for seg in [sec.get("MainSegment")] if seg)
    return {"slug": r["_slug"], "title": r.get("Title") or "", "composer": r.get("Composer") or "",
            "key": key, "key_inferred": inferred, "rhythm": rhythm, "meter": sig, "beats": beats,
            "feel": feel, "groove": GROOVE_BY_FEEL.get(feel, "swing-medium"),
            "tempo": TEMPO_BY_RHYTHM.get(rhythm.lower(), 132), "bars": bars,
            "sections": len(r.get("Sections", [])),
            "synced": bool(r.get("_synced", True)), "synced_at": r.get("_synced_at"),
            "seeded": bool(r.get("_seeded")), **({"folder": r["_folder"]} if r.get("_folder") else {})}


def list_standards(q=None, limit=None):
    out = [_meta(r) for r in _load_raw()]
    if q:
        ql = q.lower()
        out = [m for m in out if ql in m["title"].lower() or ql in m["composer"].lower()]
    out.sort(key=lambda m: m["title"])
    return out[:limit] if limit else out


def catalog_ready():
    """Y a-t-il quelque chose à jouer ? Un seul standard synchronisé suffit — en JSON (l'ancien format) OU en .golem
    (lot 10). ⚠ Le 2026-10-08, la synchro .golem a vidé `synced/` et cette fonction ne regardait que lui : la route
    /api/standards répondait « aucune grille » avec six standards sur le disque (tiroir du bloc vide)."""
    for d, ext in ((SYNCED_DIR, ".json"), (GOLEM_DIR, ".golem")):
        try:
            if any(f.endswith(ext) and not f.startswith(".") for f in os.listdir(d)):
                return True
        except OSError:
            pass
    from . import song_folders
    return song_folders.has_standards()                   # un dossier de chansons qui porte des standards


# ═════════════════════════════════════════════════════════════════════════════════════════
# 3. LA GRILLE
# ═════════════════════════════════════════════════════════════════════════════════════════
_PAREN = re.compile(r"\(([^)]*)\)")


def _parse_bar(txt, beats):
    """Une mesure iReal -> [{beat, len, sym}] en NOIRES 1-based.

    `Am7,,D7,Db7` en 4/4 = 4 subdivisions -> Am7 tient 2 temps (la 2ᵉ est vide), D7 un
    temps, Db7 un temps. C'est la règle iReal : une subdivision vide PROLONGE la
    précédente — compter des accords au lieu de subdivisions décale tout le chorus.
    """
    subs = txt.split(",")
    n = len(subs)
    span = beats / n
    out = []
    for i, s in enumerate(subs):
        s = s.strip()
        alt = None
        mm = _PAREN.search(s)
        if mm:                              # substitution : affichée, pas jouée
            alt = mm.group(1).strip()
            s = _PAREN.sub("", s).strip()
        if not s:
            if out:                          # subdivision vide -> l'accord précédent tient
                out[-1]["len"] += span
            continue
        out.append({"beat": 1.0 + i * span, "len": span, "sym": s, "alt": alt})
    return out


# Surcouche de correction : `library/standards/local/<slug>.json`, fusionné PAR-DESSUS la
# grille compilée. Le motif existe déjà deux fois (config/modes + config/modes.local,
# scene.params par-dessus la base) : le défaut n'est JAMAIS écrasé, on stocke l'écart.
# C'est ce qui permet de garder la source iReal intacte tout en corrigeant une grille.
LOCAL_DIR = os.path.join(STD_DIR, "local")

GRID_V = 1
SOURCE = "ireal:mikeoliphant/JazzStandards"


def _overlay(slug):
    p = os.path.join(LOCAL_DIR, slug + ".json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_overlay(slug, patch):
    """Écrit la surcouche (clés partielles). `patch` vide -> on supprime la correction."""
    os.makedirs(LOCAL_DIR, exist_ok=True)
    p = os.path.join(LOCAL_DIR, slug + ".json")
    if not patch:
        try:
            os.remove(p)
        except OSError:
            pass
        return None
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(patch, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return patch


def get_grid(slug):
    """Grille COMPILÉE : le format iReal est une source d'échange, pas un format de
    travail. On le normalise ici, une fois, vers notre forme explicite —
    `{beat, len, sym}` en noires 1-based — puis on applique la surcouche locale.

    Ce qu'on gagne à compiler plutôt qu'à parser au jeu : la subdivision implicite
    (`Am7,,D7`) devient une DURÉE explicite, et une grille fausse se corrige sans
    forker le corpus amont.
    """
    _load_raw()
    r = _cache["by_slug"].get(slug)
    if not r:
        return None
    if is_gsx(r):
        grid = _gsx_grid(r, slug)
        ov = _overlay(slug)
        if ov:
            grid.update({k: v for k, v in ov.items() if k not in ("slug", "v", "source")})
            grid["patched"] = sorted(k for k in ov if k not in ("slug", "v", "source"))
        return grid
    meta = _meta(r)
    beats = meta["beats"]
    sections = []
    for i, sec in enumerate(r.get("Sections", [])):
        seg = sec.get("MainSegment")
        if not seg:
            continue
        label = sec.get("Label") or chr(65 + i)
        bars = [_parse_bar(b, beats) for b in seg["Chords"].split("|")]
        endings = [[_parse_bar(b, beats) for b in (e.get("Chords") or "").split("|")]
                   for e in (sec.get("Endings") or [])]
        sections.append({"id": f"{label}{i + 1}", "label": label,
                         "bars": bars, "endings": endings})
    grid = dict(meta, v=GRID_V, source=SOURCE, sections=sections,
                order=[s["id"] for s in sections])

    ov = _overlay(slug)
    if ov:
        # fusion PLATE : une clé posée dans la surcouche remplace la clé compilée. Pas de
        # fusion profonde sur `sections` — corriger une grille, c'est la redonner entière
        # (sinon on ne sait plus, six mois après, ce qui vient d'où).
        grid.update({k: v for k, v in ov.items() if k not in ("slug", "v", "source")})
        grid["patched"] = sorted(k for k in ov if k not in ("slug", "v", "source"))
    return grid


def flatten(grid, key=None, choruses=1):
    """Grille -> suite PLATE de mesures, transposée, prête à rendre.

    Les fins (1ʳᵉ/2ᵈᵉ) sont déroulées : la fin `k` remplace la queue de la section au
    passage `k`. Une section sans fin se joue telle quelle.
    """
    semis = 0
    if key and grid.get("key"):
        a, b = _pc(_key_tonic(grid["key"])), _pc(_key_tonic(key))
        if a is not None and b is not None:
            semis = (b - a) % 12
            if semis > 6:
                semis -= 12
    bars = []
    for _ in range(max(1, choruses)):
        for sec in grid["sections"]:
            n_end = len(sec["endings"])
            if not n_end:
                bars += [(sec["id"], b) for b in sec["bars"]]
                continue
            for k in range(n_end):          # une passe par fin
                bars += [(sec["id"], b) for b in sec["bars"]]
                bars += [(sec["id"], b) for b in sec["endings"][k]]
    out = []
    for sid, bar in bars:
        out.append({"section": sid,
                    "chords": [dict(c, sym=transpose_symbol(c["sym"], semis)) for c in bar]})
    return {"semis": semis, "bars": out, "beats": grid["beats"]}


def _key_tonic(k):
    """`Gm` / `Bb-` -> la tonique seule."""
    m = re.match(r"^([A-G][#b]?)", (k or "").strip())
    return m.group(1) if m else None


# ═════════════════════════════════════════════════════════════════════════════════════════
# 3 bis. LE FORMAT .gsx — nos propres grilles
# ═════════════════════════════════════════════════════════════════════════════════════════
# Contrat : `docs/standards-format.md`. On lit les DEUX formats et on choisit sur la FORME,
# pas sur l'URL — c'est ce qui permet aux deux côtés de basculer sans se coordonner :
#
#     "v": 1  +  "sections" en OBJET   ->  .gsx
#     "Sections" en TABLEAU            ->  iReal (import de playlist utilisateur)
#
# Les deux produisent la MÊME structure interne, donc `render()` ignore d'où vient la grille.

def is_gsx(raw):
    return isinstance(raw, dict) and raw.get("v") and isinstance(raw.get("sections"), dict)


_GSX_ALT = re.compile(r"^\((.*)\)$")


def _gsx_bar(txt, beats, prev):
    """« Am7 . . D7 » -> [{beat, len, sym, alt}]. UNE PART DE MESURE PAR JETON.

    `%` rend la mesure précédente. `.` prolonge l'accord d'avant d'une part. Un jeton
    ENTIÈREMENT entre parenthèses est une SUBSTITUTION : elle s'attache à l'accord qui la
    précède et ne consomme AUCUNE part — sinon `Cmaj7 (Am7)` volerait la moitié de la mesure.
    """
    txt = txt.strip()
    if txt == "%":
        return [dict(c) for c in prev] if prev else []

    toks = txt.split()
    slots, alts = [], {}
    for t in toks:
        m = _GSX_ALT.match(t)
        if m:                                   # substitution : pas de part
            if slots:
                alts[len(slots) - 1] = m.group(1)
            continue
        slots.append(t)
    if not slots:
        return []
    span = beats / len(slots)

    out = []
    for i, t in enumerate(slots):
        if t == ".":                            # prolonge : pas de nouvel accord
            if out:
                out[-1]["len"] += span
            continue
        out.append({"sym": t, "len": span, "alt": alts.get(i)})
    b = 1.0
    for c in out:
        c["beat"] = b
        b += c["len"]
    return out


def _gsx_grid(raw, slug):
    """Document .gsx -> la structure interne (identique à celle du lecteur iReal)."""
    meter = raw.get("meter") or "4/4"
    try:
        beats = int(meter.split("/")[0])
    except ValueError:
        beats = 4

    def bars(txt):
        out, prev = [], None
        for chunk in (txt or "").split("|"):
            cur = _gsx_bar(chunk, beats, prev)
            out.append(cur)
            if chunk.strip() != "%":
                prev = cur
        return out

    secs = []
    for i, sid in enumerate(raw.get("form") or list(raw.get("sections") or {})):
        node = (raw.get("sections") or {}).get(sid)
        if node is None:
            continue                            # forme qui pointe vers une section absente
        body = node if isinstance(node, str) else node.get("bars", "")
        ends = [] if isinstance(node, str) else [bars(e) for e in (node.get("endings") or [])]
        secs.append({"id": f"{sid}{i + 1}", "label": sid, "bars": bars(body), "endings": ends})

    play = raw.get("play") or {}
    return {
        "v": raw.get("v"), "slug": slug, "title": raw.get("title") or slug,
        "composer": raw.get("composer") or "", "key": raw.get("key"), "key_inferred": False,
        "rhythm": raw.get("style") or "", "meter": meter, "beats": beats,
        "feel": raw.get("feel") or "swing", "groove": raw.get("groove") or "auto",
        "tempo": int(raw.get("tempo") or 120),
        # ⚠ UNE FIN COMPTE. Sans elle le catalogue annonçait « 14 mesures » pour Summertime,
        # qui en fait 16 : on compte le corps + la PREMIÈRE fin, soit la longueur d'un passage.
        "bars": sum(len(s["bars"]) + (len(s["endings"][0]) if s["endings"] else 0)
                    for s in secs), "sections": secs,
        "order": [s["id"] for s in secs], "source": raw.get("source"),
        # défauts de JEU portés par la grille — le bloc les écrase s'il le veut
        "play": {"motion": play.get("motion") or "comp",
                 "voicing": play.get("voicing") or "rootless",
                 "parts": play.get("parts") or {"keys": True, "bass": True, "drums": True},
                 "bass_mode": ((play.get("bass") or {}).get("mode")) or "auto"},
    }


# ═════════════════════════════════════════════════════════════════════════════════════════
# 4. LES VOICINGS — tabulaires, jamais génératifs
# ═════════════════════════════════════════════════════════════════════════════════════════
# Empiler des tierces depuis le symbole donne un son d'orgue liturgique. Ce qu'il faut, ce
# sont des voicings SANS FONDAMENTALE (la basse la joue) enchaînés par CONDUITE DES VOIX.
# Déterministe, corrigeable — même argument que pour l'automix : débogable bat génératif.
# ── ce qu'on ajoute (ou retire) au-dessus de l'accord écrit ─────────────────────────────
# La grille dit « Am7 ». Un pianiste qui reprend Summertime ne joue pas Am7 quatre fois : il
# enrichit. `size` décide de combien — et « as-written » reste le défaut, parce que la grille
# a raison par défaut et qu'une valeur par défaut qui invente des notes est un piège.
#
# ⚠ On n'ajoute une tension QUE si elle ne heurte pas l'accord. La règle est celle des
# « avoid notes » : une tension posée un demi-ton AU-DESSUS d'une note de l'accord sonne
# faux (le fa sur un Cmaj7, la 9 juste sur un 7alt qui porte déjà sa b9). Le sens compte —
# un demi-ton EN DESSOUS ne gêne pas : Am9 empile si b avec sa tierce mineure.
CHORD_SIZES = ("as-written", "triad", "7th", "9", "9-13", "alt")
_TENSIONS = {"9": (14,), "9-13": (14, 21), "alt": (13, 15, 20)}   # 9 · 9+13 · b9 #9 b13


def size_ints(ints, size):
    """Les intervalles de l'accord, retaillés. Rend `ints` tel quel si `size` ne dit rien."""
    ints = sorted(set(ints))
    if not size or size == "as-written":
        return ints
    pcs = [i % 12 for i in ints]
    # 4 AVANT 3 : une dominante altérée porte les deux (le #9 vaut une tierce mineure) et
    # c'est la tierce MAJEURE qui la définit. Sans cet ordre, « triad » sur E7alt rendait un
    # accord mineur.
    third = next((i for i in (4, 3, 2, 5) if i in pcs), None)      # inclut sus2 / sus4
    fifth = next((i for i in (7, 6, 8) if i in pcs), None)
    if size == "triad":
        # Construit, pas filtré : filtrer les intervalles d'un 7alt rendait un « triad »
        # sans quinte (E Ab G C). Une triade, c'est fondamentale + tierce + quinte.
        return sorted({0} | {x for x in (third, fifth) if x is not None}) or ints[:3]
    if size == "7th":
        return [i for i in ints if i < 12] or ints
    dominant = (4 in pcs and 10 in pcs and 3 not in pcs)
    if size == "alt" and not dominant:
        # Les tensions altérées n'appartiennent QU'aux dominantes : un Am7 « altéré » n'existe
        # pas. On ne refuse pas le réglage, on rend l'enrichissement qui a du sens ici.
        size = "9-13"
    # ⚠ On part des intervalles ÉCRITS, pas d'un noyau à quatre notes : réduire d'abord
    # jetait les altérations du symbole (E7alt perdait sa b9, son #9 et sa b13 — on rendait
    # un E7 ordinaire sous l'étiquette « altered »).
    out = list(ints)
    for t in _TENSIONS.get(size, ()):
        pc = t % 12
        if any((pc - (i % 12)) % 12 == 1 for i in out):
            continue              # un ½ ton AU-DESSUS d'une note de l'accord = avoid note
        if pc == 9 and not (dominant or fifth == 7):
            continue              # la 13 juste demande une quinte juste (ou une dominante) :
                                  # sur un m7b5 elle sonne contre la quinte bémol
        out.append(t)
    # dédoublonnage par CLASSE de hauteur : sur un C6 la 6 et la 13 sont le même la.
    seen, keep = set(), []
    for i in sorted(set(out)):
        if i % 12 in seen:
            continue
        seen.add(i % 12); keep.append(i)
    return keep


# Styles de voicing. `rootless` reste le défaut : il laisse le bas à la basse.
VOICINGS = ("rootless", "shell", "drop2", "full")
# Registres : le trio de base vit entre G3 et G5 ; les deux autres décalent d'une octave.
REGISTERS = {"low": (43, 67), "mid": (KEYS_LO, KEYS_HI), "high": (67, 91)}


def voicing_pcs(ch, rootless=True, size=None, style=None):
    """Les classes de hauteur à jouer au clavier pour cet accord.

    `rootless` est conservé pour les appelants existants ; `style` le remplace quand il est
    donné (« rootless » y est le même comportement, au bit près).
    """
    if not ch or ch["root"] is None:
        return []
    style = style or ("rootless" if rootless else "full")
    ints = size_ints(ch["ints"], size)
    if style == "shell":
        # 3 et 7 seulement : le squelette. Deux notes suffisent à dire l'accord — c'est ce
        # que joue une main gauche qui laisse la place au soliste.
        keep = [i for i in ints if i % 12 in (3, 4, 10, 11)]
        return [(ch["root"] + i) % 12 for i in (keep or ints[:2])]
    if style in ("rootless", "drop2") and len(ints) >= 4:
        # on retire la fondamentale ET la quinte juste (les deux notes que la basse et
        # l'oreille fournissent gratuitement) ; on garde 3, 7 et les tensions
        keep = [i for i in ints if i not in (0, 7)]
        if len(keep) >= 3:
            ints = keep
        else:
            ints = [i for i in ints if i != 0] or ints
    ints = sorted(set(ints))[:5]
    return [(ch["root"] + i) % 12 for i in ints]


def drop2(notes):
    """Descend la 2e note la plus haute d'une octave — le voicing « drop 2 » du big band.

    Il ouvre l'accord : la même harmonie, mais étalée, donc moins compacte au milieu du
    spectre où vivent la voix et la guitare.
    """
    if len(notes) < 3:
        return notes
    v = sorted(notes)
    return sorted(v[:-2] + [v[-2] - 12, v[-1]])


def place_voicing(pcs, prev, lo=KEYS_LO, hi=KEYS_HI):
    """Pose les classes de hauteur dans le registre, au plus près du voicing précédent.

    Conduite des voix : chaque note prend l'octave qui minimise le saut depuis l'accord
    d'avant ; la note commune ne bouge donc pas. Sans `prev`, on empile depuis le bas.
    """
    if not pcs:
        return []
    out = []
    if not prev:
        cur = lo
        for pc in pcs:
            n = cur + ((pc - cur) % 12)
            if n > hi:
                n -= 12
            out.append(n)
            cur = n + 1
        return sorted(out)
    center = sum(prev) / len(prev)
    for pc in pcs:
        best, bd = None, 1e9
        n = lo + ((pc - lo) % 12)
        while n <= hi:
            d = min(abs(n - p) for p in prev) + abs(n - center) * 0.25
            if d < bd:
                best, bd = n, d
            n += 12
        if best is not None:
            out.append(best)
    return sorted(set(out))


# ═════════════════════════════════════════════════════════════════════════════════════════
# 5. LA WALKING BASS — une table de règles, rien de plus
# ═════════════════════════════════════════════════════════════════════════════════════════
def _oct(n, shift):
    """Décale d'une octave, sans jamais sortir de la tessiture de la basse."""
    if not shift:
        return n
    m = n + 12 * int(shift)
    return m if BASS_LO <= m <= BASS_HI else n


def _near(pc, ref, lo=BASS_LO, hi=BASS_HI):
    n = lo + ((pc - lo) % 12)
    best, bd = n, abs(n - ref)
    while n <= hi:
        if abs(n - ref) < bd:
            best, bd = n, abs(n - ref)
        n += 12
    return best


# Modes de basse. Par défaut il se DÉDUIT du feel — mais certains morceaux le contredisent :
# le vamp de Take Five joue les fondamentales (Mib 3 temps, Sib 2), pas une walking, et son
# feel `even` en donnerait une. D'où `bass.mode` dans le fichier de grille : le morceau peut
# corriger la déduction sans qu'on invente un feel pour lui.
BASS_MODES = ("auto", "walk", "roots", "two", "root5", "pedal", "bossa")
# Notes d'approche : ce qui relie une fondamentale à la suivante. `chromatic` est le défaut
# (c'est ce que faisait le moteur), `diatonic` reste dans la tonalité, `none` pose une note
# de l'accord — trois façons d'arriver, pas trois réglages décoratifs.
APPROACHES = ("chromatic", "diatonic", "none")
GHOST_VEL = 44                 # la note fantôme : on l'entend comme une pulsation, pas comme
                               # une note. 44 contre 92 pour une note jouée.


def walking(ch, nxt, prev_note, beats, feel, mode=None, approach="chromatic",
            ghost=False, tonic=None):
    """Notes de basse d'UNE mesure : [(beat, note)] ou [(beat, note, vélocité)].

    Règle : fondamentale sur le 1, note d'approche (chromatique ou diatonique) vers la
    fondamentale suivante sur le dernier temps, notes de l'accord entre les deux.
    """
    if not ch or ch["root"] is None:
        return []
    root_pc = ch["bass"] if ch["bass"] is not None else ch["root"]
    r = _near(root_pc, prev_note if prev_note else 40)

    if mode == "roots":          # la fondamentale, et rien d'autre : vamps et ostinatos
        return [(1.0, r)]
    if mode == "pedal":
        # UNE note tenue sous toute la grille — la pédale. C'est la TONIQUE du morceau, pas
        # la fondamentale de l'accord : une pédale qui suit les accords n'est pas une pédale.
        return [(1.0, _near(tonic if tonic is not None else root_pc,
                            prev_note if prev_note else 40))]
    if mode == "two":            # 2-feel explicite : deux blanches
        fifth = _near((ch["root"] + 7) % 12, r)
        return [(1.0, r), (3.0, fifth)] if beats >= 4 else [(1.0, r)]
    if mode == "root5":          # fondamentale-quinte en noires : la basse de bal, et de bop
        # ⚠ la quinte MONTE. `_near` prend la plus proche, donc la quinte inférieure (une
        # quarte descendante) : la ligne entière tombait une octave sous la walking et
        # s'empâtait en bas du spectre. Une basse root-5 monte à la quinte.
        fifth = r + 7 if r + 7 <= BASS_HI else _near((ch["root"] + 7) % 12, r)
        if beats >= 4:
            return [(1.0, r), (2.0, fifth), (3.0, r), (4.0, fifth)]
        return [(1.0, r), (2.0, fifth)][:beats]
    if mode == "bossa":          # la figure : le 1 et le « et » du 3
        fifth = _near((ch["root"] + 7) % 12, r)
        return [(1.0, r), (3.5, fifth)] if beats >= 4 else [(1.0, r)]
    if mode == "walk":           # walking forcée, quel que soit le feel
        feel = "swing"

    if feel in ("ballad", "bossa", "latin", "samba"):     # 2-feel : fondamentale + quinte
        fifth = _near((ch["root"] + 7) % 12, r)
        if beats >= 4:
            return [(1.0, r), (3.0, fifth)]
        return [(1.0, r)]
    if feel == "waltz" or beats == 3:
        third = _near((ch["root"] + ch["ints"][1 if len(ch["ints"]) > 1 else 0]) % 12, r)
        fifth = _near((ch["root"] + 7) % 12, third)
        return [(1.0, r), (2.0, third), (3.0, fifth)]
    if feel == "funk" and beats >= 4:
        oct_ = r + 12 if r + 12 <= BASS_HI else r
        return [(1.0, r), (2.5, r), (3.5, oct_), (4.0, r)]

    # swing / even : quatre noires, la 4ᵉ approche la fondamentale suivante
    tones = [(ch["root"] + i) % 12 for i in ch["ints"] if i not in (0,)] or [root_pc]
    # un N.C. suivant n'a pas de fondamentale : la ligne vise alors la sienne (« A Banda » plantait)
    nxt_pc = (nxt["bass"] if nxt and nxt["bass"] is not None
              else (nxt["root"] if nxt and nxt["root"] is not None else root_pc))
    b2 = _near(tones[0], r)
    b3 = _near(tones[min(1, len(tones) - 1)], b2)
    tgt = _near(nxt_pc, b3)
    if approach == "none":
        # pas d'approche : on reste dans l'accord. La ligne perd son tirage vers l'avant —
        # c'est exactement ce qu'on veut quand la basse doit juste tenir le fond.
        b4 = _near(tones[min(2, len(tones) - 1)], b3)
    elif approach == "diatonic":
        # un degré de la gamme au-dessus ou au-dessous : ça reste dans la tonalité, donc
        # ça sonne moins « jazz » et plus chanson.
        step = 2 if (tgt - b3) < 0 else -2
        b4 = max(BASS_LO, min(BASS_HI, tgt + step))
        if b4 == b3:                  # rejouer la même note deux temps de suite n'approche
            b4 = max(BASS_LO, min(BASS_HI, tgt - step))   # rien : on approche de l'autre côté
    else:
        b4 = tgt - 1 if abs((tgt - 1) - b3) <= abs((tgt + 1) - b3) else tgt + 1
        b4 = max(BASS_LO, min(BASS_HI, b4))
    out = [(1.0, r), (2.0, b2), (3.0, b3), (4.0, b4)]
    if ghost:
        # La note fantôme : un demi-ton sous la cible, une croche avant, à peine audible.
        # C'est ce qui donne l'impression que la contrebasse « pousse » — un contrebassiste
        # frôle la corde entre deux notes, il ne joue pas quatre attaques propres.
        g = max(BASS_LO, min(BASS_HI, b3 - 1))
        out.append((2.5 if beats >= 4 else 1.5, g, GHOST_VEL))
    return sorted(out)


# ═════════════════════════════════════════════════════════════════════════════════════════
# 6. LE COMPING — c'est le rythme qui rend un accompagnement musical
# ═════════════════════════════════════════════════════════════════════════════════════════
# L'arpégiateur donne du MOUVEMENT, pas du GROOVE. Ce qui fait la différence, ce sont les
# anticipations, les syncopes et les SILENCES. Cycles de 2 mesures en (beat, durée), en
# noires 1-based ; le swing décale les croches à 2/3 de temps (voir _swing).
COMP = {
    "swing":  [[(1.0, 1.66), (2.66, 1.33)], [(2.66, 1.33), (4.66, 1.33)]],
    "bossa":  [[(1.0, 1.5), (2.5, 1.0), (4.0, 1.0)], [(1.5, 1.5), (3.0, 1.0), (4.5, 0.5)]],
    "latin":  [[(1.0, 1.0), (2.5, 0.5), (3.5, 1.0)], [(1.0, 1.0), (2.5, 0.5), (4.0, 1.0)]],
    "samba":  [[(1.0, 0.5), (1.5, 1.0), (3.0, 0.5), (3.5, 1.0)], None],
    "funk":   [[(1.0, 0.5), (2.5, 0.5), (3.0, 0.5), (4.5, 0.5)], None],
    "ballad": [[(1.0, 4.0)], None],
    "even":   [[(1.0, 2.0), (3.0, 2.0)], None],
    "waltz":  [[(1.0, 1.0), (2.0, 2.0)], [(1.0, 3.0)]],
}

# ── combien de fois dans la mesure ──────────────────────────────────────────────────────
# `auto` = le motif du feel ci-dessus, et c'est le défaut. Les autres forcent une densité
# quel que soit le feel — parce que « comment on comp » est un choix de jeu, pas une
# conséquence du style : le même Summertime se joue dense en trio et rare derrière un
# chanteur. Le swing décale les croches (voir _swing), donc « charleston » swingue tout seul.
DENSITIES = ("auto", "1", "2", "4", "charleston", "sparse")
COMP_DENSITY = {
    "1":          [[(1.0, 4.0)], None],
    "2":          [[(1.0, 2.0), (3.0, 2.0)], None],
    "4":          [[(1.0, 1.0), (2.0, 1.0), (3.0, 1.0), (4.0, 1.0)], None],
    # le charleston : le « et » du 2, rien d'autre — la figure qui a fait le comping moderne
    "charleston": [[(1.0, 1.5), (2.5, 1.5)], [(2.5, 2.0)]],
    # rare : un accord toutes les deux mesures, et un silence complet dans la seconde
    "sparse":     [[(1.0, 3.0)], []],          # [] = mesure MUETTE (≠ None = « pas d'entrée »)
}


def comp_cycle(feel, beats, density=None):
    """Le cycle de comping à jouer : (motif) par mesure. `None` dans un cycle = mesure muette."""
    if density and density != "auto" and density in COMP_DENSITY:
        cyc = COMP_DENSITY[density]
        if beats < 4:                     # une figure à 4 temps déborde une mesure à 3
            cyc = [[(b, ln) for b, ln in (pat or []) if b < 1 + beats] or None
                   for pat in cyc]
        return cyc
    cyc = COMP.get(feel) or COMP["swing"]
    if beats == 3 and feel not in ("waltz",):
        cyc = COMP["waltz"]               # un motif à 4 temps dans une mesure à 3 déborde
    return cyc


# ═════════════════════════════════════════════════════════════════════════════════════════
# 6 bis. LES GROOVES DE BATTERIE — même nature que le comping, même endroit
# ═════════════════════════════════════════════════════════════════════════════════════════
# ⚠ POURQUOI ICI ET PAS DANS LE BLOC DRUMS. Deux séquenceurs = deux horloges libres : chacun
# remet SA tête à zéro quand SA commande arrive, et les commandes passent par un canal à
# créneau unique relu tous les ~30 ms. À 132 BPM une noire fait 455 ms — 30 ms d'écart, c'est
# 6,6 % du temps, et une batterie décalée du piano de ça s'entend immédiatement.
# En émettant la batterie DANS la même liste triée, le problème de phase n'est pas géré :
# il n'existe pas. C'est le même raisonnement que pour le décompte (§7) et que celui qui a
# fait naître tout ce moteur (Lua remplit gmem, le JSFX émet à l'échantillon près).
#
# Notes General MIDI — les mêmes que les grooves .mid du bloc drums (app/page-grooves.js).
KICK, SNARE, RIM, HAT, HAT_OPEN, HAT_PED, RIDE, RIDE_BELL, CRASH = 36, 38, 37, 42, 46, 44, 51, 53, 49
VEL_CEIL = 92                  # la vélocité la plus forte des motifs écrits ci-dessous — elle
                               # sert de plafond aux grooves joués (§6 ter, mise à niveau)

# (beat 1-based, note, vélocité). Cycles de 2 mesures quand le style le demande, comme le
# comping. Les temps « swingués » (x.5) sont décalés à 2/3 par _swing, exactement comme les
# accords — sinon la ride sonnerait binaire sous un piano ternaire.
GROOVES = {
    # ride ternaire + charleston au pied sur 2 et 4 : le geste de base du jazz
    "swing": [[(1, RIDE, 74), (2, RIDE, 62), (2.5, RIDE, 54), (2, HAT_PED, 70),
               (3, RIDE, 70), (4, RIDE, 62), (4.5, RIDE, 54), (4, HAT_PED, 70)], None],
    "bossa": [[(1, RIM, 66), (1.5, KICK, 78), (2.5, RIM, 60), (3, KICK, 72), (4, RIM, 64),
               (1, HAT, 50), (2, HAT, 44), (3, HAT, 50), (4, HAT, 44)],
              [(1, KICK, 78), (2, RIM, 62), (3.5, RIM, 66), (4, KICK, 72),
               (1, HAT, 50), (2, HAT, 44), (3, HAT, 50), (4, HAT, 44)]],
    "latin": [[(1, KICK, 80), (2.5, KICK, 70), (3, RIM, 66), (4, RIM, 60),
               (1, HAT, 52), (2, HAT, 46), (3, HAT, 52), (4, HAT, 46)], None],
    "samba": [[(1, KICK, 82), (1.5, KICK, 62), (2, SNARE, 58), (3, KICK, 80),
               (3.5, KICK, 62), (4, SNARE, 62), (1, HAT, 50), (2, HAT, 46),
               (3, HAT, 50), (4, HAT, 46)], None],
    "funk":  [[(1, KICK, 92), (2, SNARE, 88), (2.75, KICK, 70), (3.5, KICK, 78),
               (4, SNARE, 86), (1, HAT, 58), (1.5, HAT, 44), (2, HAT, 56), (2.5, HAT, 44),
               (3, HAT, 58), (3.5, HAT, 44), (4, HAT, 56), (4.5, HAT, 44)], None],
    # ballade : balais, presque rien — le silence fait partie du groove
    "ballad": [[(1, RIDE, 58), (3, RIDE, 52), (2, SNARE, 40), (4, SNARE, 40)], None],
    "even":  [[(1, KICK, 88), (2, SNARE, 84), (3, KICK, 84), (4, SNARE, 84),
               (1, HAT, 54), (2, HAT, 48), (3, HAT, 54), (4, HAT, 48)], None],
    "waltz": [[(1, KICK, 78), (1, RIDE, 70), (2, RIDE, 58), (3, RIDE, 58)], None],
}


# ── les grooves JOUÉS (packs .mid) ────────────────────────────────────────────────────────
# Les motifs ci-dessus sont ÉCRITS : ils tiennent le rôle, mais chaque mesure est identique
# à la précédente au centième de temps près. Un pack de batteur donne l'inverse — des
# frappes qui respirent, des ghost notes, un charleston qui n'a jamais deux fois la même
# vélocité. `tools/import-drum-packs.py` en importe une sélection par (famille, tempo).
#
# `groove` nomme alors une FAMILLE, pas un fichier — « jazz/walk/sticks » — et on choisit
# le fichier dont le tempo est le plus PROCHE de celui du preset. Le groove suit le tempo
# au lieu d'être étiré : c'est ce que fait un batteur, et c'est pour ça qu'on importe 8
# tempos par famille plutôt qu'un seul.
#
# ⚠ Ces motifs NE repassent PAS par _swing : ils sont déjà joués ternaire par un humain.
# Les re-swinguer décalerait une croche déjà décalée.
_PACKS = {"mtime": None, "doc": None}


def _packs():
    """L'index des packs, relu quand le fichier change. {} si aucun pack importé."""
    path = os.path.join(config.ROOT, "library", "grooves", "packs.json")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    if _PACKS["mtime"] != mt:
        try:
            with open(path, encoding="utf-8") as f:
                _PACKS["doc"] = json.load(f)
            _PACKS["mtime"] = mt
        except (OSError, ValueError):
            return {}
    return _PACKS["doc"] or {}


def pack_families(meter=None):
    """[{family, tempos, meter, bars}] — ce que l'UI propose. Filtré sur la métrique."""
    doc = _packs()
    out = []
    for fam, lst in sorted((doc.get("families") or {}).items()):
        keep = [e for e in lst if not meter or e.get("meter") == meter]
        if keep:
            out.append({"family": fam, "meter": keep[0].get("meter"),
                        "bars": keep[0].get("bars"),
                        "tempos": [e["bpm"] for e in keep]})
    return out


def pack_pattern(family, bpm, meter=None, take=None):
    """Le motif du pack, au format de GROOVES : [[(temps, note, vél), …] par mesure].

    None si la famille est inconnue, si aucun fichier ne colle à la métrique, ou si le
    .mid est illisible — l'appelant retombe alors sur les motifs écrits.
    """
    doc = _packs()
    lst = (doc.get("families") or {}).get(family)
    if not lst:
        return None
    if meter:                                   # un groove en 4/4 sous une valse est FAUX
        lst = [e for e in lst if e.get("meter") == meter] or None
        if not lst:
            return None
    # ── QUELLE PRISE ? ───────────────────────────────────────────────────────────────
    # Par défaut la plus proche du tempo : c'est le bon réflexe tant que personne n'a écouté.
    # Mais un batteur ne joue pas « le shuffle », il joue CETTE prise-là — deux prises d'une
    # même famille ne se ressemblent pas (densité, ghost notes, ride). `take` (le tempo de la
    # prise, qui l'identifie : un fichier par tempo, unicité vérifiée sur les 138 prises)
    # permet donc d'en DÉSIGNER une.
    # Si elle a disparu — pack réimporté, prise retirée — on retombe sur le choix au tempo
    # plutôt que de ne rien jouer : un groove qui change vaut mieux qu'une batterie muette.
    e = None
    if take:
        e = next((x for x in lst if int(x.get("bpm") or 0) == int(take)), None)
    if e is None:
        e = min(lst, key=lambda x: abs(x["bpm"] - (bpm or 120)))
    d = _G.read_smf(os.path.join(config.ROOT, e["file"]))
    if not d or not d.get("events"):
        return None
    remap = {int(k): v for k, v in
             (doc.get("remap") or {}).get(family.split("/")[0], {}).items()}
    # ── mise à niveau ────────────────────────────────────────────────────────────────
    # MESURÉ : à réglages identiques, le pack sort à −1,1 dB crête là où le motif écrit sort
    # à −4,0 — presque 3 dB de plus, à un cheveu du clip. La cause est simple : les motifs
    # écrits plafonnent à 92 de vélocité, un batteur enregistré tape à 127.
    # On ramène donc la crête de CHAQUE motif sur celle des motifs écrits. Un facteur unique
    # préserve la dynamique — l'écart entre une ghost note et un accent est la raison d'être
    # du pack. Et on ne remonte JAMAIS un pack discret : décider qu'il manque du volume
    # n'est pas notre rôle.
    vmax = max((v for _, _, v in d["events"]), default=0)
    gain = min(1.0, VEL_CEIL / vmax) if vmax else 1.0
    ppq, nb = d["ppq"] or 480, max(1, int(e.get("bars") or d["bars"] or 1))
    beats = d["num"] * 4 // d["den"] if d.get("den") else 4
    cyc = [[] for _ in range(nb)]
    for tick, note, vel in d["events"]:
        beat = tick / ppq                       # en temps depuis le début du fichier
        bi = int(beat // beats)
        if bi >= nb:                            # queue au-delà du cycle : elle rebouclerait
            continue
        cyc[bi].append((round(beat - bi * beats, 4) + 1,
                        remap.get(note, note), max(1, min(127, round(vel * gain)))))
    if not any(cyc):
        return None
    for bar in cyc:
        bar.sort()
    return cyc


FILLS = ("off", "8", "section", "chorus")


def pack_fill(family, bpm, meter=None):
    """La mesure de fill de cette famille, au format d'un motif. None s'il n'y en a pas.

    On prend la DERNIÈRE mesure du fichier : un fill de deux mesures pose son groove
    d'abord et sa relance ensuite — c'est la relance qu'on veut, pas l'élan.
    """
    doc = _packs()
    lst = (doc.get("fills") or {}).get(family)
    if not lst:
        return None
    if meter:
        lst = [e for e in lst if e.get("meter") == meter] or None
        if not lst:
            return None
    e = min(lst, key=lambda x: abs(x["bpm"] - (bpm or 120)))
    d = _G.read_smf(os.path.join(config.ROOT, e["file"]))
    if not d or not d.get("events"):
        return None
    remap = {int(k): v for k, v in
             (doc.get("remap") or {}).get(family.split("/")[0], {}).items()}
    vmax = max((v for _, _, v in d["events"]), default=0)
    gain = min(1.0, VEL_CEIL / vmax) if vmax else 1.0
    ppq = d["ppq"] or 480
    beats = d["num"] * 4 // d["den"] if d.get("den") else 4
    nb = max(1, int(d["bars"] or 1))
    last = nb - 1
    bar = []
    for tick, note, vel in d["events"]:
        bi = int((tick / ppq) // beats)
        if bi != last:
            continue
        bar.append((round(tick / ppq - last * beats, 4) + 1,
                    remap.get(note, note), max(1, min(127, round(vel * gain)))))
    bar.sort()
    return bar or None


def fill_bars(nbars, per_chorus, sections, mode):
    """Les indices de mesure où poser un fill. Ensemble vide si `mode` ne dit rien.

    Un fill se pose AVANT un point de couture : la dernière mesure d'une phrase, pas la
    première de la suivante — sinon il annonce ce qui vient de commencer.
    """
    if not mode or mode == "off":
        return set()
    if mode == "8":
        return {i for i in range(nbars) if (i + 1) % 8 == 0 and i + 1 < nbars}
    if mode == "chorus":
        n = max(1, per_chorus)
        return {i for i in range(nbars) if (i + 1) % n == 0 and i + 1 < nbars}
    if mode == "section":
        return {i for i in range(nbars - 1)
                if sections[i] and sections[i + 1] and sections[i] != sections[i + 1]}
    return set()


def _swing(beat, feel):
    """Décale la croche faible à 2/3 du temps — sinon le swing sonne binaire."""
    if feel != "swing":
        return beat
    frac = beat - int(beat)
    if abs(frac - 0.5) < 0.08:
        return int(beat) + 0.6667
    return beat


# ═════════════════════════════════════════════════════════════════════════════════════════
# 6 bis. LA POMPE — la guitare rythmique manouche (docs/standards.md §10)
# ═════════════════════════════════════════════════════════════════════════════════════════
# En jazz manouche il n'y a ni piano ni batterie : la guitare rythmique EST la section. Règle :
# guitare rythmique oui, guitare solo jamais (le soliste, c'est le musicien).
#
# Ce qui fait sonner une pompe, et que trois notes posées sur le même tick n'ont pas :
#  - l'ÉTALEMENT : le médiator descend les cordes, de la grave à l'aiguë (~12 ms entre deux) ;
#    un contre-temps remonte, de l'aiguë à la grave ;
#  - la LONGUEUR comme groove : coups très courts sur 1 et 3, plus longs sur 2 et 4 ;
#  - l'ACCENT sur 2 et 4. Il exige un instrument qui traduit la vélocité en niveau : mesuré sur
#    Shinyguitar, +2,7 dB entre temps forts et faibles (un patch qui l'ignore efface la pompe).
# Les durées sont en MILLISECONDES, pas en fraction de temps : un coup étouffé dure le temps de
# la main gauche, quel que soit le tempo. Réglages validés à l'oreille sur la version « sèche ».
LANE_GUITAR = 4                # canal MIDI 5 : la pompe (piste « Standard Guitar »)
POMPE_SPREAD_MS = 12           # entre deux cordes
POMPE_SHORT_MS = 45            # le coup étouffé (1 et 3)
POMPE_LONG_MS = 120            # le coup accentué (2 et 4)
POMPE_SOFT, POMPE_ACC = 58, 122
POMPE_STYLES = ("pompe", "pompe-fast", "ballad", "valse", "bolero", "rumba", "bossa")

# Les FORMES, en intervalles depuis la fondamentale, de la corde grave à l'aiguë. Un tableau,
# jamais un calcul : ce sont les doigtés que joue un guitariste manouche (Dm6 = x5x465).
#  - 6 (ou 6/9) à la place de maj7 : la septième majeure n'est pas de ce langage ;
#  - pas de quinte sur les dominantes (x5x56x pour A7) ;
#  - la fondamentale JOUÉE, sur la corde grave : pompe et contrebasse se verrouillent.
SHAPE_6 = (0, 9, 16, 19)       # G6   3x243x
SHAPE_69 = (0, 16, 21, 26)     # G6/9 : 3 · 6 · 9 au-dessus de la fondamentale
SHAPE_M6 = (0, 9, 15, 19)      # Dm6  x5x465 — LA forme manouche
SHAPE_M7 = (0, 10, 15, 19)     # Gm7  3x333x
SHAPE_7 = (0, 10, 16)          # A7   5x56xx
SHAPE_13 = (0, 10, 16, 21)
SHAPE_7S5 = (0, 10, 16, 20)
SHAPE_M7B5 = (0, 10, 15, 18)
SHAPE_DIM7 = (0, 9, 15, 18)
SHAPE_7SUS = (0, 10, 17, 19)
SHAPE_SUS = (0, 7, 12, 17)
POMPE_ROOT_LO = 40             # E2 : la fondamentale tombe entre E2 et Eb3 (6e et 5e cordes)


def pompe_shape(ch):
    """Accord analysé -> notes MIDI de la forme de guitare, de la grave à l'aiguë."""
    ints = list(ch.get("ints") or [])
    s = {i % 12 for i in ints}
    root = ch["root"]
    shape = SHAPE_SUS
    if ch.get("quality") in ("dim7", "dim"):
        shape = SHAPE_DIM7
    elif 3 in s and 6 in s:
        shape = SHAPE_M7B5
    elif 3 in s and 4 not in s:
        shape = SHAPE_M7 if 10 in s else SHAPE_M6
    elif 4 in s and 10 in s:
        if 1 in s:
            # 7b9 -> le dim7 posé sur la b9 (A7b9 = Bbdim7) : le geste manouche. Il contient
            # 3, 5, b7 et b9 ; la contrebasse garde la fondamentale.
            root, shape = (root + 1) % 12, SHAPE_DIM7
        elif 8 in s:
            shape = SHAPE_7S5
        elif 9 in s:
            shape = SHAPE_13
        else:
            shape = SHAPE_7
    elif 4 in s:
        shape = SHAPE_69 if 2 in s else SHAPE_6
    elif 10 in s:
        shape = SHAPE_7SUS
    base = POMPE_ROOT_LO + (root - POMPE_ROOT_LO) % 12
    return [base + i for i in shape]


def pompe_style(feel, beats, bpm):
    """Le style quand le bloc dit « auto » : d'après la métrique, le feel et le tempo DU PRESET."""
    if beats == 3:
        return "valse"
    if feel == "bossa":
        return "bossa"
    if feel == "latin":
        return "rumba"
    if feel == "ballad":
        return "ballad"
    return "pompe-fast" if (bpm or 0) >= 230 else "pompe"


def pompe_strokes(style, beats, bar_index):
    """Les coups d'UNE mesure : (temps depuis 0, accent, longueur, montant).

    Longueur : "s" court, "l" accentué (ms fixes), "m" la moitié d'un temps (la ballade respire).
    """
    if style in ("pompe", "pompe-fast", "ballad"):
        out = []
        for b in range(beats):
            acc = b % 2 == 1
            if style == "pompe-fast" and not acc:
                continue          # au-delà de ~230 bpm : 2 et 4 seuls, la contrebasse tient 1 et 3
            out.append((b, acc, "m" if style == "ballad" else ("l" if acc else "s"), False))
        return out
    if style == "valse":          # la valse manouche : le 1 étouffé, 2 et 3 qui sonnent
        return [(0, False, "s", False)] + [(b, True, "l", False) for b in range(1, beats)]
    if style == "bolero":         # 1 · 2-et · 3 · 4 : le « et » remonte
        return [(0, True, "l", False), (1, False, "s", False), (1.5, False, "s", True),
                (2, True, "l", False), (3, False, "s", False)]
    if style == "rumba":          # 3-3-2 en croches
        return [(0, True, "l", False), (1, False, "s", True), (1.5, True, "l", False),
                (2.5, False, "s", True), (3, True, "l", False)]
    if style == "bossa":          # le motif sur deux mesures : x.x..x.x | .x..x.x.
        if bar_index % 2 == 0:
            return [(0, True, "m", False), (1, False, "m", False), (2.5, True, "m", True),
                    (3.5, False, "m", True)]
        return [(0.5, False, "m", True), (2, True, "m", False), (3, False, "m", False)]
    return pompe_strokes("pompe", beats, bar_index)


def pompe_events(flat, t0, bar_ppq, beats, bpm, style=None, feel=None):
    """La pompe sur toute la grille : événements `(ppq, note, vel, LANE_GUITAR, len_ppq)`."""
    tempo = bpm or 120
    ms = lambda v: max(1, int(round(v * tempo * PPQ / 60000)))     # noqa: E731
    st = style if style in POMPE_STYLES else pompe_style(feel, beats, tempo)
    spread = ms(20 if st == "ballad" else POMPE_SPREAD_MS)
    ev = []
    for bi, bar in enumerate(flat["bars"]):
        base = t0 + bi * bar_ppq
        chords = bar["chords"] or []
        for pos, acc, kind, up in pompe_strokes(st, beats, bi):
            if pos >= beats:
                continue
            c = next((c for c in chords if c["beat"] <= pos + 1 < c["beat"] + c["len"]), None)
            ch = parse_symbol(c["sym"]) if c else None
            if ch is None or ch["root"] is None:      # N.C. : la pompe se tait aussi
                continue
            notes = pompe_shape(ch)
            if up:
                notes = notes[::-1]
            ln = (ms(POMPE_LONG_MS) if kind == "l" else ms(POMPE_SHORT_MS) if kind == "s"
                  else PPQ // 2)
            vel = POMPE_ACC if acc else POMPE_SOFT
            if st == "ballad":
                vel = 92 if acc else 76
            at = base + int(pos * PPQ)
            for i, n in enumerate(notes):
                # la corde frappée en premier sonne plus fort : le médiator perd de l'élan
                ev.append((at + i * spread, n, max(1, vel - 4 * i), LANE_GUITAR, ln))
    return ev


# ═════════════════════════════════════════════════════════════════════════════════════════
# 7. LE RENDU — grille + réglages -> événements MIDI
# ═════════════════════════════════════════════════════════════════════════════════════════
def render(grid, key=None, feel=None, motion="comp", parts=None, choruses=1, click_div=0,
           count_in=0, rootless=True, groove=None, groove_take=None, bass_mode=None, bpm=None,
           size=None, style=None, register=None, density=None,
           anticip=True, move=True, passing=False,
           approach=None, bass_oct=0, ghost=False, land=False, fill=None, pompe=None):
    """Rend la grille en événements `(ppq, note, vel, lane, len_ppq)`.

    `motion` :
      block    — accords plaqués (travailler une grille, pas jouer)
      comp     — patterns rythmiques par feel (§6)
      arp      — l'accord TENU ; c'est `midi_arp` qui l'anime (le geste de l'AKAI)
      arp+bass — idem + walking

    Réglages du CLAVIER : `size` (taille d'accord), `style` (voicing), `register`,
    `density` (combien de fois par mesure), `anticip` / `move` / `passing`.
    Réglages de la BASSE : `bass_mode`, `approach`, `bass_oct`, `ghost`, `land`.
    Réglage de la BATTERIE : `fill` (off | 8 | section | chorus).
    Réglage de la GUITARE : `pompe` (auto | un de POMPE_STYLES), si `parts["guitar"]` (§6 bis).

    Tous ont pour défaut le comportement d'avant : un rendu sans réglages est inchangé,
    ce que `tools/check-standards.py` vérifie octet pour octet.

    Rend aussi `bars` (les symboles par mesure) pour le pupitre et le téléphone.
    """
    parts = parts or {"keys": True, "bass": True}
    feel = feel or grid.get("feel") or "swing"
    lo, hi = REGISTERS.get(register or "mid", (KEYS_LO, KEYS_HI))
    style = style or ("rootless" if rootless else "full")
    # ⚠ classe de HAUTEUR, pas nom de note : _key_tonic rend « G », la pédale a besoin de 7.
    tonic_pc = _pc(_key_tonic(key or grid.get("key")) or "")
    cur_section = None
    if bass_mode in (None, "auto"):                  # non précisé -> déduit du feel
        bass_mode = None
    # la formation manouche (pompe sans piano) : la contrebasse joue 1 et 3, elle ne marche pas
    if bass_mode is None and parts.get("guitar") and not parts.get("keys", True):
        bass_mode = "two"
    flat = flatten(grid, key=key, choruses=choruses)
    beats = flat["beats"] or 4
    bar_ppq = int(beats * PPQ)
    hold = motion in ("arp", "arp+bass")
    want_bass = parts.get("bass", True) and motion != "arp"

    ev, view, fset = [], [], set()
    prev_voice, prev_bass = [], None
    last_pcs, rep, base_voice = None, 0, []   # voicing mobile : accord répété -> on le remue
    pending_skip = False                      # anticipation posée -> le temps 1 suivant se tait
    hold_anticip = None                # accord anticipé sur la mesure d'avant (cf. plus bas)
    t0 = count_in * bar_ppq
    unknown = []

    # ── LE DÉCOMPTE ────────────────────────────────────────────────────────────────────
    # Il décalait la grille sans rien faire entendre : un décompte muet ne décompte rien.
    #
    # Pourquoi pas le bloc Click ? À l'origine parce que les deux horloges étaient
    # FREE-RUNNING et que rien ne les mettait en phase. ⚠ CE N'EST PLUS VRAI depuis le
    # 2026-08-09 : le click SE CALE sur la grille (il lit la tête de lecture publiée par
    # golem_chordseq et adopte même sa métrique — cf. l'en-tête de golem_click.jsfx).
    # Le décompte reste joué ICI quand même, et c'est délibéré : il tombe à l'échantillon
    # près parce qu'il fait partie de la même liste d'événements, là où le click garde un
    # résidu d'un bloc audio. Pour quatre notes qui donnent le départ, on prend l'exact.
    #
    # Donc on l'émet NOUS-MÊMES, sur la lane qui joue déjà : deux notes hautes et courtes,
    # le « 1 » accentué. C'est un ping de piano, pas un woodblock — mais il tombe à
    # l'échantillon près, ce qui est la seule chose qui compte pour un décompte.
    # Sans piano, c'est la POMPE qui décompte ; ses notes restent dans la tessiture de la
    # guitare (au-delà, Shinyguitar se tait) : 83/78 au lieu de 96/91.
    cin_lane = (LANE_KEYS if parts.get("keys", True)
                else LANE_GUITAR if parts.get("guitar") else LANE_BASS)
    cin_hi, cin_lo = (83, 78) if cin_lane == LANE_GUITAR else (96, 91)
    for bar_i in range(count_in):
        for beat in range(beats):
            at = bar_i * bar_ppq + beat * PPQ
            first = (beat == 0)
            ev.append((at, cin_hi if first else cin_lo, 110 if first else 78, cin_lane, PPQ // 3))

    skip_down = False
    for bi, bar in enumerate(flat["bars"]):
        base = t0 + bi * bar_ppq
        skip_down, pending_skip = pending_skip, False
        chords = bar["chords"] or []
        parsed = []
        for c in chords:
            ch = parse_symbol(c["sym"])
            if ch is None:
                unknown.append(c["sym"])
            parsed.append((c, ch))
        view.append({"section": bar["section"],
                     "chords": [{"beat": c["beat"], "sym": c["sym"]} for c in chords]})

        for ci, (c, ch) in enumerate(parsed):
            if ch is None or ch["root"] is None:      # N.C. : le rack se tait, c'est musical
                continue
            c_start = base + int((c["beat"] - 1) * PPQ)
            c_len = int(c["len"] * PPQ)

            # ── clavier ──
            if parts.get("keys", True):
                pcs = voicing_pcs(ch, size=size, style=style)
                notes = place_voicing(pcs, prev_voice, lo=lo, hi=hi)
                if style == "drop2":
                    notes = drop2(notes)
                # ⚠ LE VOICING DOIT BOUGER SUR UN ACCORD TENU. `place_voicing` cherche le plus
                # proche du précédent : sur 16 mesures de Dm7 il rend 16 fois les MÊMES notes,
                # et ça sonne comme une machine — c'est ce qu'on entend sur « So What ».
                # Un pianiste, lui, re-voice : il monte la note du bas d'une octave, puis
                # redescend. On compte les répétitions et on alterne. Déterministe, donc une
                # mesure qui sonne mal reste reproductible (exigence de check-standards).
                if move and pcs and pcs == last_pcs:
                    rep += 1
                    # On dérive de la position de BASE (celle de la 1re occurrence), jamais de
                    # la précédente : en chaînant, place_voicing ramène toujours au plus proche
                    # et la variation converge au bout d'une mesure — mesuré.
                    # Un changement toutes les 2 mesures, sur 3 positions : ça respire sans
                    # s'agiter. Déterministe (pas de hasard) : une mesure ratée reste
                    # reproductible, exigence de check-standards.
                    step = (rep // 2) % 3
                    v0 = list(base_voice or notes)
                    if step == 1 and v0 and v0[0] + 12 <= hi:
                        v0 = sorted(v0[1:] + [v0[0] + 12])          # la basse monte
                    elif step == 2 and v0 and v0[-1] - 12 >= lo:
                        v0 = sorted([v0[-1] - 12] + v0[:-1])        # l'aiguë descend
                    notes = v0
                else:
                    rep, base_voice = 0, list(notes)
                last_pcs = pcs
                prev_voice = notes or prev_voice
                if hold or motion == "block":
                    # ⚠ L'ARPÈGE SE JOUE PLUS LÉGER. Le comping respire (des trous entre les
                    # coups) ; un arpège est CONTINU — à vélocité égale il écrase tout.
                    # Mesuré : crête clavier -4,0 dB en arp contre -7,1 en comp, et l'écart
                    # PERÇU est bien pire. On corrige à la source (la vélocité, donc aussi le
                    # timbre du piano) plutôt qu'au fader, où ça sonnerait « baissé ».
                    # 88 calé à la mesure : crête -13,4 dB contre -7,1 pour le comping. Une
                    # source CONTINUE doit crêter plus bas qu'une source intermittente pour
                    # être perçue au même niveau — 6 dB sous le comping est le bon écart.
                    v = 88 if hold else 78
                    for n in notes:
                        ev.append((c_start, n, v, LANE_KEYS, c_len))
                else:
                    cyc = comp_cycle(feel, beats, density)
                    pat = cyc[bi % len(cyc)]
                    if pat is None:           # « pas d'entrée » -> on rejoue la 1re mesure
                        pat = cyc[0] or []    # (une LISTE VIDE, elle, veut dire : silence)
                    for b, ln in pat:
                        b = _swing(b, feel)
                        # ⚠ BORNE À LA MÉTRIQUE : le corpus contient du 2/4, du 3/4, du 5/4 et
                        # du 6/4. Un motif écrit pour 4 temps posait des notes APRÈS la fin de
                        # la mesure — et, sur la dernière, après la fin de la grille (trouvé
                        # par tools/check-standards.py sur « Walk Tall », en 2/4).
                        if b >= 1 + beats:
                            continue
                        if not (c["beat"] <= b < c["beat"] + c["len"]):
                            continue          # ce coup appartient à l'accord d'à côté
                        at = base + int((b - 1) * PPQ)
                        dur = min(int(ln * PPQ), c_start + c_len - at)
                        if dur <= 0:
                            continue
                        if skip_down and abs(b - 1.0) < 0.01:
                            continue          # déjà joué en anticipation sur la mesure d'avant
                        v = 84 if abs(b - 1.0) < 0.01 else 72

                        # ── ANTICIPATION ────────────────────────────────────────────────
                        # LE geste du comping jazz : l'accord suivant tombe sur le « et » du
                        # 4, AVANT sa mesure. Notre contrat le décrivait (§5.2) sans qu'on
                        # l'implémente — on posait tout sur les temps, d'où le côté « plaqué ».
                        # ⚠ On ne rajoute AUCUN coup : le motif en pose déjà un après le
                        # dernier temps ; on lui change son ACCORD. Ajouter une frappe créait
                        # un flam à 4,66/4,67 et vidait la mesure suivante (mesuré).
                        hit, hn = notes, None
                        if anticip and b > beats and ci == len(parsed) - 1 and feel in ("swing", "even"):
                            nb = flat["bars"][bi + 1] if bi + 1 < len(flat["bars"]) else None
                            hn = parse_symbol(nb["chords"][0]["sym"]) if (nb and nb["chords"]) else None
                            if hn and hn["root"] is not None and chord_pcs(hn) != chord_pcs(ch):
                                hit = place_voicing(voicing_pcs(hn, size=size, style=style),
                                                    notes, lo=lo, hi=hi)
                                if style == "drop2":
                                    hit = drop2(hit)
                                # elle SONNE PAR-DESSUS LA BARRE : c'est ce qui fait qu'une
                                # anticipation n'est pas un coup en avance mais un accord posé
                                # tôt. Trop court, la mesure suivante paraît vide alors que le
                                # son devrait la porter.
                                dur = max(dur, int(1.8 * PPQ))
                                pending_skip = True                # ...donc le 1 se tait
                        for n in hit:
                            ev.append((at, n, v, LANE_KEYS, dur))

                    # ── ACCORD DE PASSAGE ───────────────────────────────────────────
                    # Le geste qui manque le plus à un accompagnement écrit : sur le dernier
                    # temps d'une mesure tenue, un pianiste pose une dominante qui vise
                    # l'accord suivant d'un demi-ton au-dessus. Ça crée le mouvement que la
                    # grille ne note pas — et c'est exactement ce qui distingue « joué » de
                    # « saisi ». Court, plus doux que le temps fort : c'est un passage, pas
                    # un accord de la grille.
                    if (passing and ci == len(parsed) - 1 and beats >= 4
                            and c["len"] >= beats - 0.01 and feel in ("swing", "even")):
                        nb = flat["bars"][bi + 1] if bi + 1 < len(flat["bars"]) else None
                        hn = parse_symbol(nb["chords"][0]["sym"]) if (nb and nb["chords"]) else None
                        if hn and hn["root"] is not None and chord_pcs(hn) != chord_pcs(ch):
                            sub = {"root": (hn["root"] + 1) % 12, "bass": None,
                                   "ints": [0, 4, 10]}            # dominante ½ ton au-dessus
                            pn = place_voicing(voicing_pcs(sub, size=size, style=style),
                                               notes, lo=lo, hi=hi)
                            if style == "drop2":
                                pn = drop2(pn)
                            at = base + int((beats - 1) * PPQ)
                            for n in pn:
                                ev.append((at, n, 66, LANE_KEYS, int(0.8 * PPQ)))

            # ── basse ──
            if want_bass and bass_mode == "pedal":
                # La pédale ne se rejoue pas à chaque accord : UNE note, tenue. On ne l'émet
                # donc que sur le 1er accord de la mesure, et longue.
                if ci == 0:
                    n = _near(tonic_pc if tonic_pc is not None else ch["root"],
                              prev_bass if prev_bass else 40)
                    n = _oct(n, bass_oct)
                    ev.append((base, n, 84, LANE_BASS, bar_ppq))
                    prev_bass = n
            elif want_bass and bass_mode == "roots":
                # UNE fondamentale PAR ACCORD, à sa place dans la mesure — c'est ce que joue
                # un vamp. La walking, elle, ne regarde que le 1er accord et pose ses quatre
                # noires : sur « Ebm . . Bbm7 . » elle raterait le Sib du temps 4.
                n = _near(ch["bass"] if ch["bass"] is not None else ch["root"],
                          prev_bass if prev_bass else 40)
                ev.append((c_start, n, 92, LANE_BASS, max(PPQ // 2, int(c_len * 0.9))))
                prev_bass = n
            elif want_bass and ci == 0:
                nxt = None
                for nb in flat["bars"][bi + 1:]:
                    if nb["chords"]:
                        nxt = parse_symbol(nb["chords"][0]["sym"])
                        break
                if len(parsed) > 1 and parsed[1][1]:
                    nxt = parsed[1][1]
                # « Land on the root at each section » : au premier accord d'une section, on
                # repart de la fondamentale au lieu de continuer la ligne. C'est le repère
                # que donne un contrebassiste quand le thème recommence — sans lui, une
                # walking bien conduite gomme la structure.
                # On ne se contente pas d'oublier la note d'avant (la ligne était souvent
                # déjà au bon endroit : mesuré, 0 événement changé sur 3 grilles sur 4). On
                # RÉANCRE dans le grave — c'est ça, « poser » : le registre repart d'en bas
                # au lieu de rester là où la conduite l'avait emmené.
                start_from = prev_bass
                if land and bar["section"] and bar["section"] != cur_section:
                    start_from = BASS_LO + 7
                cur_section = bar["section"] or cur_section
                for w in walking(ch, nxt, start_from, beats, feel, bass_mode,
                                 approach=approach or "chromatic", ghost=ghost,
                                 tonic=tonic_pc):
                    b, n = w[0], w[1]
                    vel = w[2] if len(w) > 2 else 92
                    if b >= 1 + beats:        # même borne que le comping (cf. ci-dessus)
                        continue
                    if len(parsed) > 1 and b - 1 >= parsed[1][0]["beat"] - 1:
                        ch2 = parsed[1][1]
                        if ch2 and ch2["root"] is not None:
                            n = _near(ch2["bass"] if ch2["bass"] is not None else ch2["root"], n)
                    n = _oct(n, bass_oct)
                    ev.append((base + int((b - 1) * PPQ), n, vel, LANE_BASS, int(0.9 * PPQ)))
                    if vel != GHOST_VEL:      # une fantôme ne pilote pas la note suivante
                        prev_bass = n

    # ── la batterie ────────────────────────────────────────────────────────────────────
    # Elle ne dépend pas des accords : c'est un motif qui tourne sous la grille. On l'émet
    # DANS la même liste, donc elle partage la tête de lecture — pas de phase à recaler.
    if parts.get("drums"):
        gr = groove if groove and groove != "auto" else feel
        # Un groove JOUÉ (« jazz/walk/sticks ») prime : il vient d'un batteur. S'il manque
        # — pack pas importé, métrique incompatible — on retombe sur le motif écrit.
        # ⚠ Le tempo qui compte est celui du PRESET, pas celui de la grille : c'est lui que
        # le rack pose dans Reaper au rappel, et le pied de tiroir propose justement de
        # l'aligner (« Usually played at 80 — the preset is at 120 »). Choisir la prise
        # d'après la grille ferait jouer un groove à 80 sous un morceau qui tourne à 120.
        eff_bpm = bpm or grid.get("bpm") or grid.get("tempo")
        played = (pack_pattern(gr, eff_bpm, f"{beats}/4", take=groove_take)
                  if gr and "/" in str(gr) else None)
        cyc = played or GROOVES.get(gr) or GROOVES.get(feel) or GROOVES["swing"]
        # ── les fills ───────────────────────────────────────────────────────────────────
        # Ils ne viennent QUE d'un pack : un fill écrit à la main serait le même à chaque
        # fois, donc pire que pas de fill du tout. Sans pack -> aucun fill, en silence non :
        # `build` le remonte à l'UI, qui grise l'option (le pack jazz n'en livre aucun).
        fpat = pack_fill(gr, eff_bpm, f"{beats}/4") if (fill and fill != "off"
                                                       and gr and "/" in str(gr)) else None
        fset |= fill_bars(len(flat["bars"]),
                         len(flat["bars"]) // max(1, choruses),
                         [b["section"] for b in flat["bars"]], fill) if fpat else set()
        for bi in range(len(flat["bars"])):
            base = t0 + bi * bar_ppq
            pat = fpat if bi in fset else (cyc[bi % len(cyc)] or cyc[0])
            for b, note, vel in pat:
                b = b if (played or bi in fset) else _swing(b, feel)
                if b >= 1 + beats:          # même borne que le comping (métriques 2/4, 3/4…)
                    continue
                ev.append((base + int((b - 1) * PPQ), note, vel, LANE_DRUMS, PPQ // 4))

    # ── la pompe ───────────────────────────────────────────────────────────────────────
    if parts.get("guitar"):
        ev += pompe_events(flat, t0, bar_ppq, beats, bpm or grid.get("bpm") or grid.get("tempo"),
                           style=pompe, feel=feel)

    total = t0 + len(flat["bars"]) * bar_ppq

    # ── LE CLIC, DANS LA MÊME LISTE ────────────────────────────────────────────────────
    # C'est LA réponse au problème de phase, et elle vient du mainteneur : au lieu de mettre deux
    # horloges d'accord (ce qui laissait un résidu d'un bloc audio), on n'en garde qu'une. Le
    # clic devient des ÉVÉNEMENTS de la grille, joués par la même tête de lecture que les
    # accords — donc à l'échantillon près, comme le décompte l'était déjà.
    # Il couvre AUSSI le décompte : c'est le moment où l'on a le plus besoin de lui.
    # La hauteur porte l'accent (le JSFX du clic n'a que ça à lire) ; la vélocité est libre,
    # sauf 0 qui veut dire note-off dans ce format.
    if click_div:
        step = max(1, PPQ // int(click_div))
        n_steps = int(round(total / step))
        for k in range(n_steps):
            at = k * step
            in_bar = (at - t0) % bar_ppq if at >= t0 else (at % bar_ppq)
            on_beat = (at % PPQ) == 0
            note = (CLICK_ACCENT if (in_bar == 0 and on_beat)
                    else CLICK_BEAT if on_beat else CLICK_SUB)
            ev.append((at, note, 100, LANE_CLICK, step // 2))

    # ── note-off : produits ICI, dans la MÊME liste triée ──────────────────────────────
    # Le JSFX reste bête (il joue une liste), et surtout : un accord qui reste collé sur
    # scène est une catastrophe. Les fins sont ramenées AVANT le point de bouclage, sinon
    # une note tenue par-dessus la boucle ne se relâche jamais.
    out = []
    for at, note, vel, lane, ln in ev:
        out.append((at, note, vel, lane))
        off = min(at + max(1, ln), total - 1)
        out.append((off, note, 0, lane))
    out.sort(key=lambda e: (e[0], e[2], e[3], e[1]))   # note-off (vel 0) avant note-on

    # `fills` : COMBIEN ont réellement été posés. Un réglage « à chaque section » sur une
    # grille d'une seule section n'en pose aucun — le dire vaut mieux que se taire, sinon
    # l'utilisateur croit le réglage cassé (Summertime : 32 mesures, une seule section A1).
    return {"events": out, "bars": view, "bar_ppq": bar_ppq, "len_ppq": total,
            "semis": flat["semis"], "feel": feel, "motion": motion,
            # La métrique sur laquelle les prises de pack sont FILTRÉES. L'UI en a besoin :
            # sans elle, elle proposait des prises 6/8 sous un morceau en 4/4, que le moteur
            # écarte à raison — le clic « marchait » et le groove ne changeait pas.
            "groove_meter": f"{beats}/4",
            "count_in_ppq": t0, "unknown": sorted(set(unknown)), "fills": len(fset)}


# ═════════════════════════════════════════════════════════════════════════════════════════
# 8. LE TRANSPORT VERS REAPER
# ═════════════════════════════════════════════════════════════════════════════════════════
# Un chorus fait déjà ~1500 événements : les passer en JSON dans la commande coûterait cher
# à chaque play (le lecteur Lua n'a pas de parseur JSON). On écrit donc un fichier texte,
# une ligne par événement, et la commande ne porte que le CHEMIN — exactement ce que fait
# le bloc drums avec ses .mid.
SEQ_FILE = os.path.join(config.ROOT, "presets", ".standard.seq")


def pack_tree():
    """L'arbre du navigateur de grooves : pack -> style -> kit -> prises.

    C'est la MÊME donnée que `pack_families`, rangée pour être parcourue plutôt que
    déroulée. Le tiroir a besoin des deux : la liste pour le résumé, l'arbre pour choisir.
    """
    doc = _packs()
    fills = doc.get("fills") or {}
    packs = {}
    for fam, takes in sorted((doc.get("families") or {}).items()):
        bits = fam.split("/")
        pack, style = bits[0], bits[1]
        kit = bits[2] if len(bits) > 2 else None
        p = packs.setdefault(pack, {"pack": pack, "styles": {}})
        st = p["styles"].setdefault(style, {"style": style, "kits": []})
        st["kits"].append({"kit": kit, "family": fam,
                           "meter": takes[0].get("meter"), "bars": takes[0].get("bars"),
                           "takes": takes, "fills": len(fills.get(fam) or [])})
    out = []
    for p in packs.values():
        p["styles"] = sorted(p["styles"].values(), key=lambda x: x["style"])
        p["takes"] = sum(len(k["takes"]) for st in p["styles"] for k in st["kits"])
        out.append(p)
    return sorted(out, key=lambda x: x["pack"])


def render_groove(family, bpm=None, bars=2, meter="4/4", fill=False):
    """Rend UNE famille de grooves seule, pour l'écoute au ▶ du navigateur.

    Aucun accord, aucune basse : on écoute le rythme, pas le morceau. C'est ce qui permet
    de comparer deux prises sans changer le réglage du bloc.
    """
    pat = (pack_fill(family, bpm, meter) if fill
           else None) or pack_pattern(family, bpm, meter)
    if not pat:
        return None
    cyc = [pat] if fill else pat
    beats = int((meter or "4/4").split("/")[0]) or 4
    bar_ppq = beats * PPQ
    ev = []
    for bi in range(max(1, bars)):
        for b, note, vel in cyc[bi % len(cyc)] or cyc[0]:
            if b >= 1 + beats:
                continue
            at = bi * bar_ppq + int((b - 1) * PPQ)
            ev.append((at, note, vel, LANE_DRUMS, PPQ // 4))
    out = []
    total = max(1, bars) * bar_ppq
    for at, note, vel, lane, ln in sorted(ev):
        out.append((at, note, vel, lane))
        out.append((min(at + ln, total - 1), note, 0, lane))
    return {"events": sorted(out), "len_ppq": total, "bars": max(1, bars),
            "bar_ppq": bar_ppq, "semis": 0, "feel": "", "motion": "groove",
            "count_in_ppq": 0, "unknown": []}


def write_seq(rendered, path=SEQ_FILE):
    """Écrit la séquence rendue. Retourne (chemin, nombre d'événements)."""
    ev = rendered["events"]
    lines = ["v 1",
             "len %d" % int(rendered["len_ppq"]),
             "bar %d" % int(rendered["bar_ppq"]),
             "cin %d" % int(rendered.get("count_in_ppq") or 0),
             "nev %d" % len(ev)]
    lines += ["%d %d %d %d" % (int(a), int(n), int(v), int(l)) for a, n, v, l in ev]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return path, len(ev)


# Les réglages de jeu, en UN endroit : le tiroir les envoie, le pied les relit du bloc, et
# `build` les passe à `render`. Une liste unique évite qu'un réglage marche à l'écran et pas
# au pied — c'est arrivé avec `parts` (batterie rendue mais piste muette).
PLAY_KEYS = ("size", "style", "register", "density", "anticip", "move", "passing",
             "approach", "bass_oct", "ghost", "land", "fill", "pompe")


def _click_div():
    """Le clic doit-il être RENDU dans la grille, et à quelle subdivision ?

    Il est rendu SEULEMENT si le métronome est allumé au moment où l'on compile — sinon on
    graverait un clic muet dans la séquence, et l'allumer en cours de morceau ne ferait rien.
    C'est le prix de la précision : le clic fait partie de la partition, donc il se décide au
    départ. En échange il tombe à l'échantillon près, ce qu'aucune synchro d'horloges ne
    donnait (docs/standards.md)."""
    try:
        from .store import load_click_cfg
        st = json.load(open(os.path.join(config.PRESETS_DIR, ".click.json")))
        if not st.get("on"):
            return 0
        return max(1, int((load_click_cfg() or {}).get("div") or 1))
    except Exception:
        return 0


def block_kwargs(pm, bpm=None):
    """Les params d'un bloc `standard` → les arguments de `build` (sans le slug). UN endroit pour le pied, l'écran et
    le rendu d'un bloc (preview.render_block) : un réglage lu ici vaut partout."""
    pm = pm or {}
    return {"key": pm.get("key") if pm.get("key") not in (None, "Original") else None,
            "feel": pm.get("feel") if pm.get("feel") not in (None, "auto") else None,
            "motion": pm.get("motion") or "comp", "groove": pm.get("groove"), "groove_take": pm.get("groove_take"),
            "parts": {"keys": pm.get("keys", True) is not False, "bass": pm.get("bass", True) is not False,
                      "drums": bool(pm.get("drums")), "guitar": bool(pm.get("guitar"))},
            "choruses": int(pm.get("choruses") or 1), "count_in": int(pm.get("count_in") or 0),
            "rootless": (pm.get("voicing") or "rootless") == "rootless", "bpm": bpm,
            "play": {k: pm.get(k) for k in PLAY_KEYS}}


def build(slug, key=None, feel=None, motion="comp", parts=None, choruses=1,
          count_in=0, rootless=True, groove=None, groove_take=None, bass_mode=None,
          bpm=None, play=None, click_div=None, write=True):
    """Compile + rend + écrit la séquence. Rend le dossier complet pour l'UI et le pied.

    `write=False` : rend sans écrire presets/.standard.seq — le rendu d'un bloc (preview.render_block) ne touche pas
    la séquence que le lecteur relira au prochain play.

    `play` : les réglages de jeu (§PLAY_KEYS). Absent -> comportement d'avant, au bit près.
    """
    grid = get_grid(slug)
    if not grid:
        return None
    # Défaut + surcouche : la GRILLE dit comment elle se joue d'habitude, le BLOC décide.
    pl = grid.get("play") or {}
    motion = motion or pl.get("motion") or "comp"
    if parts is None:
        parts = pl.get("parts")
    if bass_mode in (None, "auto"):
        bass_mode = pl.get("bass_mode")
    pk = {k: v for k, v in (play or {}).items() if k in PLAY_KEYS and v is not None}
    cdiv = _click_div() if click_div is None else int(click_div)
    r = render(grid, key=key or grid.get("key"), feel=feel, motion=motion, parts=parts,
               choruses=choruses, count_in=count_in, rootless=rootless, groove=groove,
               groove_take=groove_take, bass_mode=bass_mode, bpm=bpm, click_div=cdiv, **pk)
    path, n = write_seq(r) if write else (None, len(r["events"]))
    # ⚠ On rend les réglages EFFECTIFS (défauts de la grille + surcouche du bloc). L'appelant
    # doit muter les pistes d'après EUX, pas d'après sa requête : une requête sans `parts`
    # laissait la batterie rendue dans la séquence mais MUETTE sur sa piste.
    eff = dict({"keys": True, "bass": True, "drums": False, "guitar": False}, **(parts or {}))
    return {"grid": grid, "render": r, "file": path, "events": n,
            "bars": len(r["bars"]), "tempo": grid["tempo"], "parts": eff,
            "motion": motion, "bass_mode": bass_mode, "fills": r.get("fills", 0),
            "click_div": cdiv, "play": pk}


# ═════════════════════════════════════════════════════════════════════════════════════════
# 9. LE PIED — un switch, trois gestes
# ═════════════════════════════════════════════════════════════════════════════════════════
# Doctrine `foot_scene_claim` : le bloc emprunte un switch de la rangée scènes. Le geste est
# le plus simple qu'on puisse tenir sur scène avec une chaussure :
#
#   ARRÊTÉ   + tap          -> PLAY
#   EN COURS + tap          -> STOP
#   EN COURS + maintenu     -> RELANCE au début (on a raté le thème, on repart)
#
# Pas de « variation » ni de « fill » comme sur la boîte à rythmes : la FORME appartient à
# l'arrangement (contrat §3), et un standard qui changerait de grille au pied serait un
# second séquenceur.
RESTART_S = 1.20        # maintenu au-delà -> relance (mesuré confortable sur le FCB)


def block_of(preset):
    """Les params du bloc `standard` du preset — QU'IL AIT UN SWITCH OU NON.

    ⚠ `switches` ne rend que les blocs assignés au pied : s'en servir pour savoir si le preset
    porte une grille masquait la vue Chart de /live sur tout preset lancé depuis l'écran.
    Deux questions différentes, deux fonctions.
    """
    for lane in ((preset or {}).get("config") or {}).values():
        for b in (lane or {}).get("blocks") or []:
            if b.get("type") == "standard" and (b.get("params") or {}).get("standard"):
                return dict(b["params"])
    return None


def meta_of(preset):
    """{slug: {title, composer}} des standards RÉFÉRENCÉS par ce preset — rien de plus.

    L'état publié ne portait que le slug, et /live ne peut pas afficher « Take Five · Paul
    Desmond » à partir de « take-five ». On ne publie pas le catalogue entier pour autant :
    seulement ce que le preset cite, parce qu'une tuile ne peut nommer que ce qu'elle lance.
    """
    want = set()
    b = block_of(preset)
    if b and b.get("standard"):
        want.add(b["standard"])
    for e in (switches(preset) or {}).values():
        sl = (e.get("params") or {}).get("standard")
        if sl:
            want.add(sl)
    if not want:
        return {}
    return {m["slug"]: {"title": m["title"], "composer": m["composer"]}
            for m in list_standards() if m["slug"] in want}


def switches(preset):
    """{sw(int): {block, params}} des blocs `standard` assignés au pied."""
    from . import store
    out = {}
    for b, _k in store._foot_blocks(preset or {}):
        if b.get("type") == "standard" and isinstance(b.get("foot"), int):
            pm = b.get("params") or {}
            if pm.get("standard"):
                out[b["foot"]] = {"block": b.get("id"), "params": dict(pm)}
    return out


class StandardControl:
    """Moteur de gestes du bloc Standard (fronts press/release du FCB)."""

    def __init__(self, emit, on_change=None):
        self._emit = emit                              # (op, params) -> commande vers Reaper
        self._on_change = on_change or (lambda: None)
        self._press = {}                               # sw -> {t, params, timer, fired}
        self._playing = False
        self._lock = __import__("threading").Lock()

    def snapshot(self):
        return {"playing": self._playing}

    def apply_feedback(self, playing):
        """Réconcilie avec le témoin écrit par golem_chordseq.lua (le JSFX fait foi)."""
        if bool(playing) != self._playing:
            self._playing = bool(playing)
            self._on_change()

    def on_edge(self, sw, on, params=None):
        import threading
        with self._lock:
            if on:
                p = {"t": _now(), "params": params or {}, "timer": None, "fired": False}
                if self._playing:                      # armer la RELANCE seulement si ça tourne
                    t = threading.Timer(RESTART_S, self._restart, args=(sw,))
                    t.daemon = True
                    p["timer"] = t
                    t.start()
                self._press[sw] = p
            else:
                p = self._press.pop(sw, None)
                if not p:
                    return
                if p["timer"]:
                    p["timer"].cancel()
                if p["fired"]:                         # la relance est déjà partie au maintien
                    return
                if self._playing:
                    self._go("stop", p["params"])
                else:
                    self._go("play", p["params"])

    def _restart(self, sw):
        with self._lock:
            p = self._press.get(sw)
            if not p or p["fired"]:
                return
            p["fired"] = True
            self._go("play", p["params"])              # play recale la tête au tick 0

    def _go(self, op, params):
        self._playing = (op == "play")
        self._emit(op, params)
        self._on_change()


def _now():
    import time as _t
    return _t.monotonic()
