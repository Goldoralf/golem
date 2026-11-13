# SPDX-License-Identifier: GPL-3.0-or-later
"""
Compilateur du modèle rig « clean » (paths + splits) — étape 2.

Ne rend PLUS de .RfxChain : golem construira les FX par NOM (TrackFX_AddByName) et chargera les
fichiers NAM/IR (résolus ici et passés dans le plan). Sortie = `<id>.rig.json` = contrat golem
(topologie de pistes + routage + fallback mono). (L'ancien compile.py est supprimé — audit 2026-07-07 ;
la résolution des refs vit dans resolver.py.)

Usage : import compile_rig ; ou  python3 -m bridge.compile_rig <preset-id>
"""
import contextlib, os, re, json, sys, shutil, hashlib, tempfile

COMPILE_TARGET = sys.platform

from . import config as C
from . import rig
from .golog import get

log = get("compile")
from . import vital as _vital
from . import resolver as _core   # _components/_resolve/_write (ex-compile.py)
from .resolver import _components, _resolve

OUT_DIR = os.path.join(C.ROOT, "reaper", "FXChains")


def file_stem(pid):
    """Nom de fichier d'un preset dans OUT_DIR. Un patch ouvert dans le Designer a l'id `patch:<id>`,
    et Windows refuse `:` dans un nom (WinError 123, 2026-10-05 : le patch ne se recompilait plus et
    chaque essai laissait un .tmp). golem_rig.lua applique la MÊME substitution pour relire le plan."""
    return str(pid).replace(":", "~")


IO_PATH = os.path.join(C.ROOT, "config", "io.json")
TEMPLATE_NAM = os.path.join(os.path.dirname(__file__), "templates", "nam-cab.RfxChain")    # NAM + x42 fondus
TEMPLATE_HEAD = os.path.join(os.path.dirname(__file__), "templates", "nam-head.RfxChain")   # NAM tête seule
TEMPLATE_CAB = os.path.join(os.path.dirname(__file__), "templates", "cab-x42.RfxChain")     # cab x42 seul
ASSET_CACHE = os.path.join(C.ROOT, "assets", ".cache")

# SEULS les file-loaders (ampli NAM + cab x42) sont bakés dans le template — c'est le seul chargement
# fichier fiable (load_fxchain à l'instanciation). TOUS les autres blocs (gate, eq, boost, delay, reverb…)
# sont ajoutés par NOM côté golem, DANS L'ORDRE, avec leurs params -> plus de params gate/eq figés, et un
# overdrive se place bien AVANT l'ampli (cf. golem_rig build_track_fx).
CORE_TYPES = ["amp", "amp-nam", "cab"]

# cab par défaut si un ampli n'a pas de cab explicite (parité avec l'ancien compile).
DEFAULT_CAB = "mesa-4x12-recto-ksm313"

# ── normalisation de loudness des captures NAM (bug volume 2026-07-23) ──────
# Les .nam portent metadata.loudness (loudness de sortie mesuré à l'entraînement) : de -11 à -28 dB
# selon la capture dans la lib (~16 dB de variance !) -> certains presets hurlent et écrêtent le DAC.
# Au compile, la sortie de CHAQUE bloc ampli est corrigée de (CIBLE - loudness) — la convention NAM
# (le toggle « normalize » du plugin officiel vise -18). Le potard `output` de l'utilisateur reste
# un offset PAR-DESSUS la sortie normalisée (paradigme QC). Pédales pedal-nam PAS normalisées :
# un boost doit booster. Clamp à la plage du slider Output Lvl du plugin (±20).
# Les captures d'OUTBOARD (preamp-nam, comp-nam — 2026-09-14) SONT normalisées, comme un ampli :
# un préampli capturé n'est pas un boost, c'est un étage de gain complet (Neve 31102 « Pre 70 »
# à −11 LUFS contre « Pre 30 » à −24) — sans ça, tourner le Capture dial fait sauter le niveau.
NORMALIZED_TYPES = ("amp", "amp-nam", "preamp-nam", "comp-nam")
LOUD_TARGET = -18.0


# audit 2026-11-04 (P3) : un .nam fait jusqu'à 2,3 Mo de JSON (poids compris) et il était relu ENTIER à chaque
# compile, donc à chaque scène, pour un seul nombre. Mémorisé par (chemin, mtime, taille).
_LOUD = {}


def _nam_loudness(path):
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
        if key in _LOUD:
            return _LOUD[key]
        with open(path) as f:
            v = (json.load(f).get("metadata") or {}).get("loudness")
        v = float(v) if v is not None else None
        if len(_LOUD) > 4096:
            _LOUD.clear()
        _LOUD[key] = v
        return v
    except Exception:
        return None


def _normalize_amp_outputs(blocks, comps):
    for b in blocks:
        if b.get("type") in NORMALIZED_TYPES and b.get("ref"):
            path = _resolve(b.get("ref"), comps, b.get("model"))
            loud = _nam_loudness(path) if path else None
            if loud is None:
                continue
            trim = LOUD_TARGET - loud
            pm = b.setdefault("params", {})
            out = pm.get("output") or 0
            pm["output"] = round(max(-20.0, min(20.0, out + trim)), 1)
            pm["_loud"] = round(loud, 1)                  # traçabilité dans le rig.json


# ── pitch-correct (fat1) : Key + Scale VIRTUELS -> masque de notes m00-m11 (tiroirs voix
# 2026-07-23). Le plugin n'a que 12 interrupteurs C..B ; l'UI offre une tonalité + gamme,
# la compile les traduit et RETIRE key/scale (ids inconnus du plugin -> golem_rig loguerait).
_PC_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_PC_SCALES = {"Chromatic": list(range(12)),
              "Major": [0, 2, 4, 5, 7, 9, 11],
              "Minor": [0, 2, 3, 5, 7, 8, 10]}


# ── clamp des params aux plages des defs (bug piste-6 Prism 2026-07-23 : chorus.mix=30 dans
# un port 0..1 = wet à fond empilé sur le dry -> clip). Une valeur hors plage (vieux preset
# d'avant un changement de def, IA, main) est CLAMPÉE et LOGUÉE — jamais matérialisée telle
# quelle. Le validateur IA refuse en amont ; ceci est le filet à la compile. ──
_FX_DEFS = None


def _fx_defs():
    global _FX_DEFS
    if _FX_DEFS is None:
        try:
            data = json.load(open(os.path.join(C.ROOT, "library", "catalog", "effects.json")))
            _FX_DEFS = {b["type"]: {p["id"]: p for p in b.get("params", [])}
                        for b in data.get("effects", []) if b.get("type")}
            # types dont les DÉFAUTS du catalogue s'écrivent à la compile (`defaults: compile`, docs/spectral.md)
            _FX_DEFS["__compile_defaults__"] = {b["type"] for b in data.get("effects", [])
                                                if b.get("type") and b.get("defaults") == "compile"}
        except Exception:
            _FX_DEFS = {}
    return _FX_DEFS


def _fill_compile_defaults(blocks):
    """Un potard absent du preset n'est PAS écrit : le plugin garde SON défaut. Pour la plupart des blocs
    c'est le bon (ReaComp, Calf…). Pour ceux marqués `defaults: compile` dans effects.json, le défaut du
    plugin est un piège — Spectral Compressor sort à 1:1 (aucun effet), PaulXStretch COUPE le direct —
    et un preset écrit à la main ou par l'IA de golem.fm ne porte pas les défauts d'UI du Designer.
    Ici on pose les défauts du catalogue pour les potards que le preset ne nomme pas."""
    defs = _fx_defs()
    kinds = defs.get("__compile_defaults__") or set()
    for b in blocks or []:
        if b.get("type") not in kinds:
            continue
        pm = b.setdefault("params", {})
        for pid, d in (defs.get(b["type"]) or {}).items():
            if pid not in pm and d.get("default") is not None:
                pm[pid] = d["default"]


def _clamp_params(blocks):
    try:
        from . import rig, golem_fx
        safe = rig._engine_safe_types()
    except Exception:
        safe, golem_fx = set(), None
    for b in blocks or []:
        defs = _fx_defs().get(b.get("type")) or {}
        if golem_fx and b.get("type") in safe:          # la feuille golem FX : les bornes de ses réglages propres aussi
            defs = {d["id"]: d for d in golem_fx.merged(b.get("type"), list(defs.values()))[0]}
        for k, v in list((b.get("params") or {}).items()):
            pd = defs.get(k)
            if not pd or pd.get("type") in ("enum", "bool"):
                continue
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            lo, hi = pd.get("min"), pd.get("max")
            if lo is not None and hi is not None and not (lo <= v <= hi):
                nv = max(lo, min(hi, v))
                log.warning(f"⚠ {b.get('type')}.{k}={v} hors plage [{lo}..{hi}] -> clampé {nv}")
                b["params"][k] = nv


def _expand_stretch(blocks):
    """Bloc `stretch` (PaulXStretch, docs/spectral.md) : ses modules spectraux ont chacun un INTERRUPTEUR
    dans le plugin (« Enable spread », « Enable compressor »), éteint par défaut. Un potard Spread ou
    Compress tourné sans son interrupteur ne fait RIEN — et un preset écrit à la main ou par l'IA de
    golem.fm ne porte pas nos défauts d'UI. L'interrupteur SUIT donc le potard : > 0 = allumé."""
    for b in blocks or []:
        if b.get("type") != "stretch":
            continue
        pm = b.setdefault("params", {})
        for knob, sw in (("spread", "spread_on"), ("compress", "comp_on")):
            if sw not in pm:
                try:
                    pm[sw] = float(pm.get(knob) or 0) > 0
                except (TypeError, ValueError):
                    pm[sw] = False


def _expand_pitch_correct(blocks):
    for b in blocks or []:
        if b.get("type") != "pitch-correct":
            continue
        pm = b.setdefault("params", {})
        key = pm.pop("key", "C")
        scale = pm.pop("scale", "Chromatic")
        root = _PC_NOTES.index(key) if key in _PC_NOTES else 0
        degrees = _PC_SCALES.get(scale, _PC_SCALES["Chromatic"])
        allowed = {(root + d) % 12 for d in degrees}
        for i in range(12):
            pm[f"m{i:02d}"] = (i in allowed)


# ── pitch (gfx-pitch, Golem Engine) : l'harmonie SUIT LA TONALITÉ DU MORCEAU (2026-11-13) ──
# `song_key` est VIRTUEL (jamais écrit au plugin) : allumé (défaut) et le patch a une tonalité, Key et Scale la
# prennent — la tonique, et Major / Minor sauf si la gamme choisie à la main est déjà de la bonne famille (un
# Dorian reste Dorian dans un morceau mineur). Les noms de Key sont ceux de gfx-pitch : une énumération part par
# son RANG (ardour_plan.table_def).
_GFX_KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_MINOR_SCALES = {"Minor", "Harmonic Minor", "Melodic Minor", "Dorian", "Phrygian", "Minor Pentatonic"}
_MAJOR_SCALES = {"Major", "Lydian", "Mixolydian", "Major Pentatonic"}


def parse_song_key(s):
    """« Em », « Bb », « F#m », « C minor », « Eb maj », « G♭m » -> (classe de hauteur 0-11, mineur ?) ; None sinon."""
    import re
    m = re.match(r"^\s*([A-Ga-g])\s*([#b♯♭]?)\s*(.*)$", str(s or ""))
    if not m:
        return None
    pc = _NOTE_PC[m.group(1).upper()] + {"#": 1, "♯": 1, "b": -1, "♭": -1}.get(m.group(2), 0)
    rest = m.group(3).strip().lower()
    minor = rest in ("m", "min", "minor", "-", "mi", "moll") or rest.startswith(("m ", "min ", "minor"))
    if rest and not minor and rest not in ("maj", "major", "dur"):
        return None                                    # « Original », « Cmaj7 »… : pas une tonalité
    return pc % 12, minor


def song_key_of(preset):
    """La tonalité du morceau que ce patch joue : `key` du preset, sinon celle de son bloc Standard (sa grille si
    « Original »). (classe de hauteur, mineur ?) ou None."""
    k = parse_song_key(preset.get("key")) if preset.get("key") else None
    if k:
        return k
    try:
        from . import store
        blk = next((b for b, _l in store.all_blocks(preset) if isinstance(b, dict) and b.get("type") == "standard"),
                   None)
    except Exception:
        blk = None
    if not blk:
        return None
    pm = blk.get("params") or {}
    if pm.get("key") and pm["key"] != "Original":
        return parse_song_key(pm["key"])
    try:
        from . import standards
        return parse_song_key((standards.get_grid(pm.get("standard")) or {}).get("key"))
    except Exception:
        return None


def _expand_pitch_harmony(blocks, sk):
    for b in blocks or []:
        if b.get("type") != "pitch":
            continue
        pm = b.setdefault("params", {})
        follow = pm.pop("song_key", True)
        if not (follow and sk):
            continue
        pc, minor = sk
        pm["key"] = _GFX_KEYS[pc]
        fam = _MINOR_SCALES if minor else _MAJOR_SCALES
        if pm.get("scale") not in fam:
            pm["scale"] = "Minor" if minor else "Major"


def _drop_engine_only(blocks):
    """Un potard que seul le plugin golem-fx a (`engine_only: "golem"` au catalogue : la polarité du flanger) est
    retiré là où le bloc ne joue PAS par golem-fx (REAPER sans le plugin, Windows, macOS) — golem_rig loguerait
    « non résolu » à chaque rappel. Sous le Golem Engine, et sous REAPER avec golem-fx installé, il reste."""
    try:
        from . import rig
        safe = rig._engine_safe_types()
    except Exception:
        safe = set()
    defs = _fx_defs()
    from . import golem_fx
    for b in blocks or []:
        pm = b.get("params")
        if not isinstance(pm, dict) or b.get("type") in safe:
            continue
        # les réglages de la feuille golem FX qui n'existent que sur le plugin golem-fx (docs/golem-fx-sheet.md)
        for pid in golem_fx.gfx_only_keys(b.get("type"), list((defs.get(b.get("type")) or {}).values())):
            pm.pop(pid, None)
        for pid, d in (defs.get(b.get("type")) or {}).items():
            if d.get("engine_only") == "golem":
                pm.pop(pid, None)


def _safe(name):
    return "".join(c if c.isalnum() else "_" for c in name)


# ── GARDE D'IR (2026-09-14, Sunfunk : « un delay d'un feedback alors que tout est désactivé ») ────
# Mesuré sur la prise : après chaque note, la DI décroît, la sortie REMONTE de 8 dB à 480 ms, une
# fois. Le delay était bypassé. La cause : les 16 IR des packs Palmer 2x12 (5004/5006) durent 1,6 s
# et portent une SECONDE impulsion à ~480 ms, 22 dB sous la première — convoluées, elles répètent
# chaque note. Le convolveur x42 n'a pas de limite de durée. Famille « bonne forme, mauvaise
# nature » : le fichier est un .wav valide, résolu, chargé, et il contient un écho.
# La garde LIT le fichier (jamais une déclaration) : au-delà de IR_HEAD_MS, une fenêtre de 20 ms
# qui remonte au-dessus de IR_LATE_DB sous la crête = impulsion tardive -> copie COUPÉE juste avant
# (fondu de 5 ms) dans le cache, et le journal le dit. Un IR propre est copié tel quel.
IR_HEAD_MS = 100          # un baffle de guitare tient dans ~50 ms ; on ne juge rien avant 100 ms
IR_LATE_DB = -40.0        # sous ça, c'est de la queue de pièce, pas un écho
IR_WIN_MS = 20


def _read_wav_mono(path):
    """(échantillons float canal 0, sample rate) — PCM 16/24/32 et float 32/64, sans numpy (venv nu)."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            tag, ch, sr, _, _, bits = struct.unpack("<HHIIHH", body[:16])
            if tag == 0xFFFE and len(body) >= 26:            # WAVE_FORMAT_EXTENSIBLE : le sous-format dit vrai
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, ch, sr, bits)
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if not fmt or raw is None:
        raise ValueError("fmt/data chunk missing")
    tag, ch, sr, bits = fmt
    step = bits // 8 * ch
    n = len(raw) // step
    out = []
    if tag == 3 and bits == 32:
        for i in range(n): out.append(struct.unpack_from("<f", raw, i * step)[0])
    elif tag == 3 and bits == 64:
        for i in range(n): out.append(struct.unpack_from("<d", raw, i * step)[0])
    elif tag == 1 and bits == 16:
        for i in range(n): out.append(struct.unpack_from("<h", raw, i * step)[0] / 32768.0)
    elif tag == 1 and bits == 24:
        for i in range(n):
            b = raw[i * step:i * step + 3]
            v = b[0] | (b[1] << 8) | (b[2] << 16)
            out.append((v - (1 << 24) if v & 0x800000 else v) / 8388608.0)
    elif tag == 1 and bits == 32:
        for i in range(n): out.append(struct.unpack_from("<i", raw, i * step)[0] / 2147483648.0)
    else:
        raise ValueError(f"unsupported wav format tag={tag} bits={bits}")
    return out, sr


def ir_late_impulse(path):
    """(ms de la 1re impulsion tardive, dB sous la crête) ou None si l'IR est propre. Lit le fichier."""
    import math
    x, sr = _read_wav_mono(path)
    peak = max((abs(v) for v in x), default=0.0)
    if peak <= 0:
        return None
    win, start = int(sr * IR_WIN_MS / 1000), int(sr * IR_HEAD_MS / 1000)
    for i in range(start, len(x) - win, win):
        m = max(abs(v) for v in x[i:i + win])
        if m > 0 and 20 * math.log10(m / peak) > IR_LATE_DB:
            return (round(1000 * i / sr), round(20 * math.log10(m / peak), 1))
    return None


def _write_wav_mono24(path, x, sr):
    import struct
    body = bytearray()
    for v in x:
        i = max(-8388608, min(8388607, int(round(v * 8388608.0))))
        body += struct.pack("<i", i)[:3]
    hdr = b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 3, 3, 24) + b"data" + struct.pack("<I", len(body))
    with open(path, "wb") as f:
        f.write(hdr + bytes(body))


def _ir_guard(src, dst):
    """Copie `src` vers `dst` — coupée juste avant une impulsion tardive s'il y en a une. Rend le
    diagnostic (None = propre, copiée telle quelle). Toute erreur de lecture = copie telle quelle."""
    try:
        late = ir_late_impulse(src)
    except Exception as e:
        log.warning(f"IR non lisible pour la garde ({os.path.basename(src)}) : {e} — copiée telle quelle")
        late = None
    if late is None:
        shutil.copy2(src, dst)
        return None
    ms, db = late
    x, sr = _read_wav_mono(src)
    cut = max(int(sr * IR_HEAD_MS / 1000), int(sr * ms / 1000) - int(sr * 0.005))
    fade = int(sr * 0.005)
    y = x[:cut]
    for k in range(fade):                                 # fondu de 5 ms : pas de clic à la coupe
        y[cut - fade + k] *= (fade - k) / fade
    _write_wav_mono24(dst, y, sr)
    log.warning(f"⚠ IR « {os.path.basename(src)} » : seconde impulsion à {ms} ms ({db} dB sous la crête) "
                f"— copie COUPÉE à {round(1000 * cut / sr)} ms dans le cache (un écho par note, sinon)")
    return late


def _safe_asset(path):
    """Copie `path` sous assets/.cache/ avec un nom SANS espace ni '#' (le format LV2 `P … <chemin> 3`
    est non-quoté -> un chemin à espaces casse). Idempotent (recopie si source plus récente).
    Un .wav (IR) passe par la GARDE D'IR : une impulsion tardive est coupée dans la copie."""
    if not path or not os.path.exists(path):
        return path
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(path))
    dst = os.path.join(ASSET_CACHE, hashlib.md5(path.encode()).hexdigest()[:8] + "_" + base)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(path) or (
            path.lower().endswith(".wav") and os.path.getmtime(dst) < _IR_GUARD_SINCE):
        os.makedirs(ASSET_CACHE, exist_ok=True)
        if path.lower().endswith(".wav"):
            _ir_guard(path, dst)
        else:
            shutil.copy2(path, dst)
    return dst


# les copies faites AVANT la garde (2026-09-14) se refont une fois : la date du code fait foi
_IR_GUARD_SINCE = os.path.getmtime(__file__)


def _tpl(path, subs):
    """Lit un template .RfxChain et substitue les placeholders (%MODEL%/%IR%) par les chemins."""
    t = open(path, "rb").read().decode("latin-1")
    for k, v in subs.items():
        if v:
            t = t.replace(k, v)
    return t


def _carries_cab(amp):
    """Cet ampli porte-t-il DÉJÀ son baffle ? Deux signes, et le second est le plus sûr :
      · le bloc est un `amp` — « Head+Cab (NAM) », par définition le rig complet (MODEL_GEARS) ;
      · sa capture est déclarée `gear: amp-cab` — un `amp-nam` mal apparié tombe donc aussi.
    Le type de bloc est notre donnée, le `gear` est une déclaration qui vient de TONE3000 : on
    interroge les deux, pour que le mauvais appariement ne passe pas par le second côté."""
    if (amp or {}).get("type") == "amp":
        return True
    ref = (amp or {}).get("ref")
    if not ref:
        return False
    from .resolver import _tones_index
    key = str(ref).split(":", 1)[1] if str(ref).startswith("t3k:") else str(ref)
    return (_tones_index().get(key) or {}).get("gear") == "amp-cab"


def _render_core_for(blocks, comps, path_has_cab=True):
    """Rend le cœur file-loaders (NAM/x42) d'UNE piste. Chemins résolus puis ASSAINIS (sans espace/#) et
    bakés (chargés EN SESSION via load_fxchain). Trois cas pour permettre le SPLIT DES CABS :
      - ampli + cab même piste  -> NAM + x42 fondus (nam-cab)  [linéaire, ou merge amp entier/branche]
      - ampli SEUL (tête)        -> NAM seul (nam-head) si un cab existe en AVAL du path (split) ;
                                    sinon NAM + cab défaut fondu (ampli isolé sans cab)
      - cab SEUL (branche)       -> x42 seul (cab-x42)
    None si la piste n'a ni ampli ni cab."""
    # slot ampli/cab SANS ref = vide (« platform » de template) -> ignoré (pas de tête/cab fantôme).
    # ⚠ `bypass` compris (2026-09-12) : _prep_block bypasse un bloc dont le fichier ne convient
    # pas à son type (doctrine « repli jamais silencieux »), mais le CŒUR ré-résolvait la ref sans
    # le savoir. Le patch « Titan » portait une capture amp-cab NAM sur son `cab` : le bloc était
    # bien bypassé, et le convolver recevait quand même le .nam — donc ne chargeait rien, et la
    # lane se taisait. Un bloc bypassé ne fournit plus son fichier : l'ampli retombe alors sur le
    # cab par défaut, et on entend l'ampli au lieu d'un silence.
    # ⚠ 2026-09-14 (Sunfunk « Heavy » muet de saturation) : exclure ici tout bloc BYPASSÉ rendait la
    # topologie dépendante de la scène — une branche bâtie pendant une scène qui coupe son ampli
    # était construite SANS NAM, et aucune bascule gapless ne pouvait le faire revenir. Le bypass de
    # scène est un ÉTAT (posé par apply_core_enabled côté rig) ; seule la mauvaise NATURE de fichier
    # (`_wrong_kind`, marqué par rig._prep_block) retire un bloc du cœur.
    usable = [b for b in blocks if not b.get("_wrong_kind")]
    amp = next((b for b in usable if b.get("type") in ("amp", "amp-nam") and b.get("ref")), None)
    cab = next((b for b in usable if b.get("type") == "cab" and b.get("ref")), None)
    if not amp and not cab:
        return None
    if amp and not cab:                                    # TÊTE
        model = _safe_asset(_resolve(amp.get("ref"), comps, amp.get("model")))
        if path_has_cab:                                   # le cab est en aval (branche d'un split) -> tête seule
            return _tpl(TEMPLATE_HEAD, {"%MODEL%": model})
        # ⚠ 2026-09-12, patch « Hammer » : « ampli isolé -> cab défaut fondu » est juste pour une
        # TÊTE, faux pour un rig COMPLET. Le bloc `amp` (« Head+Cab ») et toute capture de
        # `gear: amp-cab` portent DÉJÀ leur baffle — leur en fondre un second donnait deux baffles
        # en série, que golem.fm et nous classons pire qu'un silence : ça s'entend comme une
        # couverture jetée sur l'ampli, donc comme un mauvais réglage, et on cherche dans les
        # potards. Mesuré ici : capture « Randall X2 Warhead Full Rigs » + Mesa 4x12 par défaut.
        if _carries_cab(amp):
            return _tpl(TEMPLATE_HEAD, {"%MODEL%": model})
        ir = _safe_asset(_resolve(amp.get("cab") or DEFAULT_CAB, comps))   # tête isolée -> cab défaut fondu
        return _tpl(TEMPLATE_NAM, {"%MODEL%": model, "%IR%": ir})
    if cab and not amp:                                    # CAB SEUL (branche)
        ir = _safe_asset(_resolve(cab.get("ref") or DEFAULT_CAB, comps, cab.get("model")))
        return _tpl(TEMPLATE_CAB, {"%IR%": ir})
    # AMPLI + CAB même piste -> fondus
    model = _safe_asset(_resolve(amp.get("ref"), comps, amp.get("model")))
    cabref = amp.get("cab") or cab.get("ref")
    ir = _safe_asset(_resolve(cabref, comps, cab.get("model")) if cabref else _resolve(DEFAULT_CAB, comps))
    return _tpl(TEMPLATE_NAM, {"%MODEL%": model, "%IR%": ir})


def _native_core_for(blocks, comps, path_has_cab=True):
    """Resolve the NAM and IR files for the desktop VST3 backend.

    The official NAM VST3 hosts both a model and an IR. Keep the Linux LV2
    template path separate: its serialized state and plugin IDs are different.
    """
    usable = [b for b in blocks if not b.get("_wrong_kind")]
    amp = next((b for b in usable if b.get("type") in ("amp", "amp-nam") and b.get("ref")), None)
    cab = next((b for b in usable if b.get("type") == "cab" and b.get("ref")), None)
    if not amp and not cab:
        return None
    for block in (amp, cab):
        if block and not block.get("id"):
            raise ValueError(f"NAM natif : identifiant de bloc absent pour {block.get('type')}")
    model = _safe_asset(_resolve(amp["ref"], comps, amp.get("model"))) if amp else None
    ir = None
    if cab:
        ref = (amp or {}).get("cab") or cab["ref"]
        ir = _safe_asset(_resolve(ref, comps, cab.get("model")))
    elif amp and not path_has_cab and not _carries_cab(amp):
        ir = _safe_asset(_resolve(amp.get("cab") or DEFAULT_CAB, comps))
    if amp and (not model or not os.path.isfile(model) or not model.lower().endswith((".nam", ".json"))):
        raise ValueError(f"NAM natif : modèle absent ou incompatible pour {amp.get('id') or amp.get('ref')}")
    if (cab or (amp and not path_has_cab and not _carries_cab(amp))) and (
            not ir or not os.path.isfile(ir) or not ir.lower().endswith(".wav")):
        raise ValueError(f"NAM natif : IR WAV absente ou incompatible pour {(cab or amp).get('id')}")
    return {"model": model or "", "ir": ir or "",
            "amp_id": amp.get("id") if amp else None,
            "cab_id": cab.get("id") if cab else None,
            "default_ir": bool(ir and amp and not cab)}


def _io():
    """(out_count, mono_fallback) depuis config/io.json — supporte l'ancien et le nouveau format."""
    io = json.load(open(IO_PATH)) if os.path.exists(IO_PATH) else {}
    if isinstance(io.get("outputs"), list):                       # format clean
        return len(io["outputs"]), io.get("mono_fallback") or {"on": False, "gain": -3}
    n = io.get("outputs_count", 2)                                # ancien format (profils)
    return n, {"on": False, "gain": (io.get("fold_down") or {}).get("gain", -3)}


def plan_preset(preset: dict, comps=None):
    """Le plan du rig SANS rien écrire : normalise, valide le routage, résout les fichiers. C'est ici
    que la compile REFUSE (quarantaine, routage impossible) — donc c'est l'essai à blanc qu'un appelant
    fait AVANT d'engager quoi que ce soit (patch-try écrit la sandbox et rappelle seulement si ça passe)."""
    comps = comps if comps is not None else _components()
    out_count, mono = _io()
    return rig.build_plan(preset, out_count, resolve=lambda ref, model=None: _safe_asset(_resolve(ref, comps, model)),
                          mono_fallback=mono, strict_out=False)   # sandbox : sorties sommées, pas d'unicité exigée


def compile_preset(preset: dict) -> str:
    """Normalise, valide le routage, résout les fichiers, écrit `<id>.rig.json`. Retourne le chemin."""
    _drum_slot = [0]                                   # docs/drums-kit.md lot 2 : un slot gmem par bloc drumkit
    comps = _components()
    plan = plan_preset(preset, comps)
    sk = song_key_of(preset)                           # la tonalité du morceau, une fois pour tout le preset
    os.makedirs(OUT_DIR, exist_ok=True)
    # cœur file-loaders (NAM/x42) par piste. `path_has_cab` : si le path a un cab EN AVAL (branche d'un split),
    # une piste ampli-seule rend une TÊTE NAM seule (le cab vit dans la branche) -> split des cabs possible.
    for p in plan["paths"]:
        # `bypass` compris ici AUSSI : un cab bypassé (fichier du mauvais type) faisait croire
        # qu'un baffle attendait en aval, donc le cœur rendait une TÊTE SEULE — l'ampli sortait
        # sans baffle, très fizzy. Un cab qui ne charge rien n'est pas un cab en aval.
        path_has_cab = any(b.get("type") == "cab" and not b.get("bypass")
                           for t in p["tracks"] for b in t["blocks"])
        for t in p["tracks"]:
            # blocs MARQUEURS (engine "mode", ex. looper) : consommés au niveau preset
            # (plan.looper via rig.looper_enabled), jamais matérialisés en FX
            t["blocks"] = [b for b in t["blocks"] if b.get("type") != "looper"]
            from . import capture_module
            for captured in t["blocks"]:
                capture_module.prepare(captured)
            _normalize_amp_outputs(t["blocks"], comps)     # normalisation loudness (voir LOUD_TARGET)
            _expand_pitch_correct(t["blocks"])             # Key/Scale -> masque de notes fat1
            _expand_pitch_harmony(t["blocks"], sk)         # harmonie gfx-pitch : Key/Scale du morceau
            _fill_compile_defaults(t["blocks"])            # défauts du catalogue pour les blocs `defaults: compile`
            _expand_stretch(t["blocks"])                   # Spread/Compress -> leurs interrupteurs de module
            _clamp_params(t["blocks"])                     # filet : jamais de param hors plage au rig
            _drop_engine_only(t["blocks"])                 # potards du seul Golem Engine : retirés sous REAPER
            if COMPILE_TARGET in ("win32", "darwin"):
                native_core = _native_core_for(t["blocks"], comps, path_has_cab)
                if native_core:
                    t["native_core"] = native_core
                    t["core_types"] = CORE_TYPES
            else:
                core = _render_core_for(t["blocks"], comps, path_has_cab)
                if core:
                    fn = f"{file_stem(preset['id'])}__{_safe(t['name'])}.RfxChain"
                    _core._write(os.path.join(OUT_DIR, fn), core)
                    t["rfxchain"] = fn
                    t["core_types"] = CORE_TYPES
            # lane Keys : entrée MIDI (nom Reaper du contrôleur lié) + état Vital PAR BLOC — le JSON
            # du .vital de la scène (bakée dans params.preset) est GREFFÉ dans le template vst_chunk
            # (spike 2026-07-08 : seul chargement headless fiable = VST3 + vst_chunk à chaud).
            if t.get("midi"):
                t["midi_in"] = _vital.midi_input_for(t.get("midi_role"), t.get("in_sel"))
                # un contrôleur dont les pads ont LEUR canal (profil de calibration : mesuré, ou posé par la
                # programmation des pads, bridge/controller_program.py) : golem_rig trie — canal des pads -> les pads,
                # canal du clavier -> l'instrument (sinon un pad jouait aussi une note dans Vital)
                from . import controllers as _ctl
                _ch = _ctl.channels_for(t["midi_in"])
                if _ch and t.get("midi_role") != "drums":
                    t["midi_ch"] = _ch
                if t.get("midi_role") == "drums":
                    t["midi_strict"] = True            # pas d'heuristique AKAI pour une batterie (golem_rig)
                else:
                    t["midi_avoid"] = _vital.drums_devices()   # et la lane Keys ne prend jamais un module de batterie
            if not t.get("midi") and any(b.get("type") == "drumkit" for b in t["blocks"]):
                log.warning(f"{t.get('name')} : bloc Drum Kit sur une lane AUDIO — retiré (un kit du rack ne joue qu'en MIDI ; le module fait le son ici)")
                t["blocks"] = [b for b in t["blocks"] if b.get("type") != "drumkit"]
            for b in t["blocks"]:
                # bloc drumkit (docs/drums-kit.md lot 2) : le kit de la scène (bakée dans params.kit) ->
                # moteur + banque, et la TRADUCTION module -> kit (descripteur du port, table du kit)
                if b.get("type") == "drumkit":
                    from . import drumkits as _dk, inputmap as _im, kits as _kits
                    ports = _im.usb_ports()
                    port = next((u for u in ports if u.get("ch") == t.get("in_sel")), None)
                    # « usb » générique (le brouillon d'un patch), ou un rang qui n'est plus celui du module :
                    # le module de batterie LIÉ, par rôle — sinon la table du module était GM en silence
                    # (mesuré 2026-09-23 : « module=general-midi » sur une Nitro mesurée)
                    if not (port and port.get("role") == "drums"):
                        port = next((u for u in ports if u.get("role") == "drums" and u.get("bound")), port)
                    desc = _dk.get(((port or {}).get("kit") or {}).get("id")) or _dk.get(_dk.FALLBACK)
                    active = (b.get("params") or {}).get("kit")
                    # L'UNION DES KITS (scene_bake.annotate_drumkit_union) : un moteur par kit que les scènes
                    # utilisent, chacun avec SA table de traduction et SON slot gmem ; `kit_id` = celui de
                    # cette scène (golem_rig allume sa paire, bypass les autres — zéro rebuild entre scènes).
                    engines = []
                    for kid in (b.get("kits") or ([active] if active else [])):
                        k = _kits.get_kit(kid or "") or {}
                        if not k:
                            log.warning(f"drumkit {b.get('id')} : kit « {kid} » introuvable — moteur ignoré")
                            continue
                        tr = _dk.translation(desc, _kits.kit_notes(k))
                        e = {"kit_id": k.get("id"), "kit_engine": k.get("engine"), "kit_bank": k.get("bank"),
                             "drum_map": tr["map"], "drum_hh": tr["hh"], "drum_lost": tr["lost"], "drum_chan": tr["channel"],
                             "drum_slot": _drum_slot[0]}
                        if k.get("engine") == "drumgizmo":              # kit multi-micros : fichiers + mix d'usine (golem_rig)
                            e["kit_drumkit"], e["kit_midimap"] = k.get("drumkit"), k.get("midimap")
                            e["kit_mix"], e["kit_bleed"] = list(k.get("mix") or []), k.get("bleed")
                        _drum_slot[0] += 1
                        if tr["lost"]:
                            log.info(f"drumkit {b.get('id')} : le kit {k.get('id')} ne joue pas {tr['lost']} (module {(desc or {}).get('id')})")
                        engines.append(e)
                    b["engines"] = engines
                    b["drum_desc"] = (desc or {}).get("id")
                    cur = next((e for e in engines if e["kit_id"] == active), engines[0] if engines else None)
                    if cur:                                             # les champs « à plat » = le kit ACTIF (compat, journal)
                        for kk, vv in cur.items():
                            b[kk] = vv
                    else:
                        b["kit_id"], b["kit_engine"], b["kit_bank"] = None, None, None
                        # ⚠ (2026-10-08) une ligne de journal égarée ici lisait `k` et `tr` — qui n'existent PAS quand
                        # aucun kit n'est choisi (la boucle ne tourne pas) : « cannot access local variable 'k' », et
                        # TOUT le brouillon refusé (patch de batterie neuf impossible à sauver). Le bloc sans kit compile.
                        log.warning(f"drumkit {b.get('id')} : kit « {active} » introuvable — bloc sans moteur")
                # bloc pads : résout le kit de la scène (bakée dans params.kit) en liste
                # matérialisable — golem_rig pose une instance RS5k note-filtrée par pad
                if b.get("type") == "pads":
                    from . import kits as _kits
                    k = _kits.get_kit((b.get("params") or {}).get("kit") or "")
                    b["kit_pads"] = [
                        {"note": p["note"], "file": os.path.join(C.ROOT, p["sample"]),
                         "mode": p.get("mode") or "gate", "level": p.get("level") or 0}
                        for p in (k or {}).get("pads", []) if p.get("sample")
                    ]
                # bloc piano : le .sfz de la scène (bakée dans params.sfz) -> chemin absolu
                if b.get("type") == "piano":
                    sf = (b.get("params") or {}).get("sfz") or ""
                    fp = os.path.join(C.ROOT, sf)
                    if sf and os.path.isfile(fp):
                        b["sfz_file"] = fp
                # bloc ep : la banque DX7 de la scène (params.bank) -> chemin absolu + n° de patch
                if b.get("type") == "ep":
                    bk = (b.get("params") or {}).get("bank") or ""
                    fp = os.path.join(C.ROOT, bk)
                    if bk and os.path.isfile(fp):
                        b["dx7_bank"] = fp
                        b["dx7_patch"] = int((b.get("params") or {}).get("patch") or 0)
                # knobs AKAI (feature claviers) : déclaration du TYPE (effects.json) + CC de la
                # banque (config/knobs.json) -> cibles baked ; golem_rig écrit la carte runtime
                if b.get("type") in ("vital", "ep"):
                    try:
                        kdef = next((e for e in (json.load(open(C.EFFECTS)) or {}).get("effects", [])
                                     if e.get("type") == b.get("type")), {}).get("knobs")
                        if kdef:
                            from .controllers import knobs_config      # locale, sinon la graine
                            ccs = knobs_config().get("bank" + kdef.get("bank", "A")) or []
                            b["knobs"] = [{"cc": ccs[i], "name": t}
                                          for i, t in enumerate(kdef.get("targets") or []) if i < len(ccs)]
                    except Exception as e2:
                        log.warning(f"knobs {b.get('id')}: {e2}")
                if b.get("type") == "vital":
                    vf = _vital.preset_path((b.get("params") or {}).get("preset"))
                    if vf:
                        try:
                            b64 = _vital.splice_chunk(open(_vital.TEMPLATE_CHUNK).read(), vf)
                            fn = f"{file_stem(preset['id'])}__{_safe(t['name'])}__{_safe(b.get('id') or 'vital')}.vital.b64"
                            _core._write(os.path.join(OUT_DIR, fn), b64)
                            b["vital_chunk"] = fn
                        except Exception as e:
                            log.warning(f"greffe vital '{b.get('id')}' impossible: {e}")
                        # Vitalium LV2 (Windows) : pas de vst_chunk — ports + état binaire posés
                        # dans le chunk de piste. golem_rig prend l'une ou l'autre selon le moteur posé.
                        try:
                            fl = f"{file_stem(preset['id'])}__{_safe(t['name'])}__{_safe(b.get('id') or 'vital')}.vitalium.txt"
                            _core._write(os.path.join(OUT_DIR, fl), _vital.lv2_state(vf))
                            b["vitalium_state"] = fl
                        except Exception as e:
                            log.warning(f"état Vitalium LV2 '{b.get('id')}' impossible: {e}")
    # écriture ATOMIQUE (tmp+rename) : golem_rig ne doit jamais lire un .rig.json tronqué
    # (crash bridge en plein write — audit 2026-07-07 P1).
    path = os.path.join(OUT_DIR, f"{file_stem(preset['id'])}.rig.json")
    fd, tmp = tempfile.mkstemp(dir=OUT_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):        # jamais de .tmp orphelin dans reaper/FXChains
            os.remove(tmp)
        raise
    return path


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "demo-rig"
    src = os.path.join(C.PRESETS_DIR, f"{pid}.json")
    if not os.path.exists(src):
        src = os.path.join(C.ROOT, "docs", "examples", f"{pid}.json")
    p = json.load(open(src))
    print("écrit:", compile_preset(p))
