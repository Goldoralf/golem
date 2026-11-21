# SPDX-License-Identifier: GPL-3.0-or-later
"""LES ÉTIQUETTES D'UN CHOIX QUI CHANGENT DE NOM (catalogue `renamed` sur un paramètre enum, 2026-10-22).

Un réglage à choix se range sous son ÉTIQUETTE (« 1/4 »), pas sous sa valeur. Quand une étiquette mentait — le Tape
Delay disait « 1/4 » pour un tick de Calf, une double croche —, la corriger sans migration ferait jouer l'option 0 à
tous les presets existants (golem_rig.index_of ne trouve plus l'étiquette). Le catalogue déclare donc, sur le
paramètre, `renamed: {ancienne: nouvelle}`, et ce module réécrit au CHARGEMENT tout document qui porte encore
l'ancienne — preset, patch, preset de bloc, .golem importé, document venu de golem.fm.

Règles, pour qu'une réécriture ne puisse jamais se tromper de sens :
  - une ancienne étiquette n'est JAMAIS une nouvelle option (le test du catalogue l'exige) : réécrire est pur et
    idempotent, un document déjà migré ne bouge plus ;
  - seuls les blocs du TYPE déclaré sont touchés (« 1/4 » est aussi une option du Delay, qui garde la sienne) : leurs
    params, puis les params rangés sous leur id dans les états de lane et les scènes.

Rend le nombre de valeurs réécrites (0 : rien n'a changé)."""
import json
import math
import os

from . import config as C

_cache = {"mtime": None, "val": {}}


def table():
    """{type de bloc: {id de paramètre: {ancienne: nouvelle}}}, lu dans effects.json (relu s'il change)."""
    try:
        mt = os.path.getmtime(C.EFFECTS)
    except OSError:
        return {}
    if _cache["mtime"] != mt:
        out = {}
        try:
            with open(C.EFFECTS, encoding="utf-8") as f:
                effects = json.load(f).get("effects", [])
        except (OSError, ValueError):
            effects = []
        for e in effects:
            for p in e.get("params") or []:
                if isinstance(p.get("renamed"), dict) and p.get("id"):
                    out.setdefault(e.get("type"), {})[p["id"]] = dict(p["renamed"])
        _cache.update(mtime=mt, val=out)
    return _cache["val"]


def _rename(params, renames):
    n = 0
    if not isinstance(params, dict):
        return 0
    for pid, ren in renames.items():
        v = params.get(pid)
        if isinstance(v, str) and v in ren:
            params[pid] = ren[v]
            n += 1
    return n


# ── LES TYPES DE BLOCS RETIRÉS (2026-11-13) : un type qui fait double emploi disparaît du catalogue, et un document
# qui le porte encore est réécrit au chargement vers le type qui reste, valeurs CONVERTIES. Pur et idempotent : le
# type retiré n'existe plus au catalogue, donc un document réécrit ne le porte plus.
def _flanger_from_calf(pm):
    """Calf Flanger (`flanger` : rate Hz, depth = largeur du balayage en ms, feedback linéaire -0.9…0.9) -> le flanger
    qui reste (`flanger-js` : length ms, feedback dB, wet/dry dB, rate Hz). La traduction est celle de golem-fx
    (gfx-flanger-calf `translate`, qui jouait ce bloc sous le Golem Engine) : balayage de min_delay 0,5 ms à
    0,5 + depth, |feedback| en dB et son signe en `fb_polarity` (plafond -1 dB, celui du moteur ; le catalogue s'arrêtait à -6 et
    l'a suivi en v40 pour qu'un « Jet » à 0,85 garde son caractère), Amount 0,5 de Calf = wet -6 dB. Sous REAPER, le JSFX n'a pas de polarité : le
    compilateur retire `fb_polarity` (engine_only) et le signe s'y perd."""
    import math
    pm = pm if isinstance(pm, dict) else {}
    out = {}
    if "rate" in pm:
        out["rate"] = round(min(2.0, max(0.05, float(pm["rate"]))), 3)
    if "depth" in pm:
        out["length"] = round(min(30.0, 0.5 + max(0.0, float(pm["depth"]))), 2)
    if "feedback" in pm:
        fb = abs(float(pm["feedback"]))
        out["feedback"] = -60.0 if fb < 0.001 else round(min(-1.0, max(-60.0, 20 * math.log10(fb))), 1)
        if float(pm["feedback"]) < 0 and fb >= 0.001:
            out["fb_polarity"] = "Inverted"                # le signe passe par la polarité (Golem Engine seulement)
    if pm.get("depth") is not None or pm.get("rate") is not None or pm.get("feedback") is not None:
        out.setdefault("wet", -6.0)
        out.setdefault("dry", 0.0)
    return out


# ── LES BLOCS HÉRITÉS (2026-11-15, décision du mainteneur : « le golem ne tournera qu'avec nos blocs » ; liste de
# golem-fx docs/legacy-blocks.md). Chaque ancien type va vers la pédale golem-fx qui le remplace ; la traduction garde
# l'INTENTION du réglage (un temps, une quantité, un caractère), pas une identité de son — golem-fx l'a accepté : ses
# pédales sont des sons neufs. Les réglages que seule la pédale golem-fx connaît (model, algo, taps…) sont écrits par
# leur id golem-fx.
def _f(pm, k, d=None):
    try:
        return float(pm.get(k, d))
    except (TypeError, ValueError):
        return d


def _clamp(v, lo, hi, nd=2):
    return round(min(hi, max(lo, v)), nd)


def _db(lin, floor=-60.0, top=0.0):
    import math
    return floor if lin is None or lin < 0.001 else _clamp(20 * math.log10(lin), floor, top, 1)


def _chorus_from_js(pm):
    """JS chorus_stereo (length ms, voices, rate Hz, wet / dry dB) -> gfx-chorus (`chorus` : rate Hz, depth ms, mix
    0–1 au-dessus du sec). Le wet en dB devient le mix linéaire ; la longueur, le retard de base et la profondeur."""
    out = {}
    if "rate" in pm:
        out["rate"] = _clamp(_f(pm, "rate", 0.5), 0.1, 3.0, 3)
    if "length" in pm:
        ln = _f(pm, "length", 15)
        out["delay_base"] = _clamp(ln, 1, 30, 1)
        out["depth"] = _clamp(ln / 4, 1, 8, 1)
    if "wet" in pm:
        out["mix"] = _clamp(10 ** (_f(pm, "wet", -12) / 20), 0, 1, 2)
    if "voices" in pm:
        out["voices"] = str(int(_clamp(_f(pm, "voices", 2), 1, 6, 0)))
    return out


def _phaser_from_calf(pm):
    """Calf Phaser (rate Hz, depth en cents 1000–8000, stages 4–12, feedback linéaire 0–0.8) -> gfx-phaser
    (`phaser-js` : rate, balayage low–high Hz, feedback dB). Le balayage part de 440 Hz et couvre `depth` cents."""
    out = {}
    if "rate" in pm:
        out["rate"] = _clamp(_f(pm, "rate", 0.4), 0.05, 5, 3)
    if "depth" in pm:
        out["low"] = 440
        out["high"] = int(_clamp(440 * 2 ** (_f(pm, "depth", 4000) / 1200), 200, 8000, 0))
    if "feedback" in pm:
        out["feedback"] = min(-1.0, _db(_f(pm, "feedback", 0.3)))
    if "stages" in pm:
        st = int(_f(pm, "stages", 6) or 6)
        out["stages"] = str(min((2, 4, 6, 8, 10, 12, 16), key=lambda x: abs(x - st)))
    return out


_DELAY_16THS = {1: "1/16", 2: "1/8", 3: "1/8•", 4: "1/4", 6: "1/4•", 8: "1/2"}
_TAPE_16THS = {"16th": 1, "8th": 2, "dotted 8th": 3, "quarter": 4, "5 16ths": 5, "dotted quarter": 6, "half": 8,
               "dotted half": 12, "whole": 16,
               # les étiquettes d'avant le catalogue 31 (un « 1/4 » y valait UN tick de Calf : une double croche)
               "1/4": 1, "1/2": 2, "3/4": 3, "1 bar": 4}


def _delay_from_calf(pm):
    """Calf Vintage Delay (time en seizièmes au tempo du bloc, feedback %, mix %, medium) -> gfx-delay modèle Tape.
    Une division que le Delay a reste synchronisée ; les autres (5 seizièmes, blanche pointée, ronde) passent en
    temps libre au tempo du bloc."""
    out = {"model": "Tape"}
    if "time" in pm:                                      # une surcharge de scène partielle ne touche que ce qu'elle dit
        n = _TAPE_16THS.get(pm.get("time"), 3)
        if n in _DELAY_16THS:
            out["time"] = _DELAY_16THS[n]
        else:
            out["time"] = "Free"
            out["time_ms"] = _clamp(n * 15000 / max(60.0, _f(pm, "tempo", 120)), 1, 4000, 0)
    if "feedback" in pm:
        out["feedback"] = _clamp(_f(pm, "feedback", 40), 0, 75, 0)
    if "mix" in pm:
        out["mix"] = _clamp(_f(pm, "mix", 30), 0, 50, 0)
    if pm.get("time_r") and pm.get("time_r") != pm.get("time"):
        out["stereo"] = "Ping-Pong"
    if pm.get("medium") == "Old Tape":
        out["age"] = 60
    return out


def _delay_from_airwindows(pm):
    """Airwindows TapeDelay2 (time en ms, regen, tone, reso, flutter, mix %) -> gfx-delay modèle Tape, temps libre."""
    out = {"model": "Tape"}
    if "time" in pm:
        t = str(pm.get("time") or "350 ms").strip()
        try:
            ms = float(t[:-2]) if t.endswith("ms") else float(t[:-1]) * 1000
        except ValueError:
            ms = 350.0
        out.update(time="Free", time_ms=_clamp(ms, 1, 4000, 0))
    if "regen" in pm:
        out["feedback"] = _clamp(_f(pm, "regen", 35), 0, 75, 0)
    if "mix" in pm:
        out["mix"] = _clamp(_f(pm, "mix", 30), 0, 50, 0)
    if "flutter" in pm:
        out["mod"] = _clamp(_f(pm, "flutter", 15), 0, 100, 0)
    if "tone" in pm:
        out["high_cut"] = int(_clamp(2000 * 2 ** (_f(pm, "tone", 50) / 100 * 3.3), 1000, 20000, 0))
    return out


def _delay_from_echocat(pm):
    """GxEchoCat (time en bpm = une noire, repeats %, mix %, input = saturation, têtes 1–3) -> gfx-delay modèle Tape :
    le temps libre de la noire, les têtes allumées en motif de têtes."""
    out = {"model": "Tape"}
    if "time" in pm:
        out.update(time="Free", time_ms=_clamp(60000 / max(30.0, _f(pm, "time", 120)), 1, 4000, 0))
    if "repeats" in pm:
        out["feedback"] = _clamp(_f(pm, "repeats", 30) * 0.75, 0, 75, 0)
    if "mix" in pm:
        out["mix"] = _clamp(_f(pm, "mix", 35), 0, 50, 0)
    if "input" in pm:
        out["drive"] = _clamp(_f(pm, "input", 25), 0, 100, 0)
    heads = tuple(i for i in (1, 2, 3) if pm.get(f"head{i}") in (True, 1, "1", "true"))
    if any(f"head{i}" in pm for i in (1, 2, 3)):
        out["taps"] = {(1, 2): "Heads 1+2", (1, 2, 3): "Heads 1+2+3", (1, 3): "Heads 1+3"}.get(heads, "Single")
    return out


def _eq_from_x42(pm):
    """x42 parametric (coupe-bas on/off + Hz, grave dB, trois cloches f/g, aigu dB) -> gfx-eq (`eq`). La cloche du
    milieu devient le médium du bloc, la plus marquée des deux autres son second médium (gfx-eq), grave et aigu leurs
    étagères."""
    out = {}
    if "lowcut" in pm or "lowcut_on" in pm:
        on = pm.get("lowcut_on", True) not in (False, 0, "0", "false")
        out["lowcut"] = _clamp(_f(pm, "lowcut", 80), 20, 200, 0) if on else 20
    if "bass" in pm:
        out["lows"] = _clamp(_f(pm, "bass", 0), -18, 18, 1)
    if "g2" in pm or "f2" in pm:
        out["midgain"] = _clamp(_f(pm, "g2", 0), -12, 12, 1)
        out["midfreq"] = _clamp(_f(pm, "f2", 500), 300, 2500, 0)
    side = max((("1", _f(pm, "g1", 0)), ("3", _f(pm, "g3", 0))), key=lambda x: abs(x[1] or 0))
    if side[1]:
        out["mid2gain"] = _clamp(side[1], -18, 18, 1)
        out["mid2freq"] = _clamp(_f(pm, "f" + side[0], 1000), 100, 8000, 0)
    if "treble" in pm:
        out["highs"] = _clamp(_f(pm, "treble", 0), -12, 12, 1)
    return out


def _reverb_from_surge_spring(pm):
    """Surge XT spring (tout en 0–1) -> gfx-reverb voix Spring (`reverb` : mix %, decay s, size m, hicut Hz)."""
    out = {"algo": "Spring"}
    if "mix" in pm:
        out["mix"] = _clamp(_f(pm, "mix", 0.35) * 100, 0, 60, 0)
    if "decay" in pm:
        out["decay"] = _clamp(0.4 + _f(pm, "decay", 0.55) * 3.6, 0.4, 4, 2)
    if "size" in pm:
        out["size"] = _clamp(10 + _f(pm, "size", 0.5) * 40, 10, 50, 0)
    if "damp" in pm:
        out["hicut"] = _clamp(3000 + (1 - _f(pm, "damp", 0.45)) * 9000, 3000, 12000, 0)
    return out


def _drive_from_proteus(pm):
    """Proteus (« Overdrive / Boost » : drive %, level %, bass/mid/treble ±8) -> Emet Overdrive (gain %, tone_stack %,
    level dB). Le choix entre Emet et Shem (un boost propre) se fait sur le drive : voir _retire_type."""
    out = {}
    if "drive" in pm:
        out["gain"] = _clamp(_f(pm, "drive", 30), 0, 100, 0)
    if "treble" in pm or "bass" in pm:
        tone = (_f(pm, "treble", 0) or 0) - (_f(pm, "bass", 0) or 0) / 2
        out["tone_stack"] = _clamp(50 + tone * 6, 0, 100, 0)
    if "level" in pm:
        out["level"] = _clamp((_f(pm, "level", 50) - 50) * 0.24, -24, 12, 1)
    return out


def _boost_from_proteus(pm):
    """Proteus à faible drive -> Shem Boost (grind dB) : le niveau donne la poussée."""
    return {"grind": _clamp((_f(pm, "level", 50) - 50) * 0.2 + 6, -8, 20, 1)} if "level" in pm else {}


def _pitch_from_spectral(pm):
    """Spectral Shift (« Digital Detuner » : shift st, formant_comp) -> gfx-pitch moteur Poly, tout mouillé."""
    out = {"engine": "Poly", "mix": 100}
    if "shift" in pm:
        out["shift"] = _clamp(_f(pm, "shift", 0), -12, 12, 2)
    return out


def _autowah_from_rez(pm):
    """MDA RezFilter (tout en 0–1 : freq, res, env, attack, release, lfodepth, lforate) -> gfx-autowah passe-bas
    résonant : la sensibilité est l'enveloppe, la source suit ce qui bouge (enveloppe, LFO ou les deux)."""
    out = {"type": "Low-pass"}
    if "env" in pm:
        out["wah"] = _clamp(_f(pm, "env", 0.4), 0, 1, 2)
    if "freq" in pm:
        low = _clamp(50 * 2 ** (_f(pm, "freq", 0.5) * 7), 50, 2000, 0)
        out.update(low=low, high=_clamp(low * 6, 200, 8000, 0))
    for k, (lo, span, hi, nd, ok) in {"res": (0.5, 19.5, 20, 1, "peak"), "attack": (0.5, 99.5, 100, 1, "attack"),
                                       "release": (10, 1990, 2000, 0, "release")}.items():
        if k in pm:
            out[ok] = _clamp(lo + _f(pm, k, 0.5) * span, lo, hi, nd)
    if "lforate" in pm:
        out["rate"] = _clamp(0.05 * 2 ** (_f(pm, "lforate", 0.3) * 7.6), 0.05, 10, 2)
    if "env" in pm or "lfodepth" in pm:
        env, lfo = _f(pm, "env", 0.4), _f(pm, "lfodepth", 0)
        out["source"] = "Envelope + LFO" if lfo > 0.05 and env > 0.05 else ("LFO" if lfo > 0.05 else "Envelope")
    return out


def _grains_from_freeze(pm):
    """GoleM Freeze (retiré sans remplaçant, le mainteneur le trouvait pauvre) -> le maintien de gfx-grains, au plus
    près : Freeze et Mix passent, le reste est propre à l'ancien bloc."""
    out = {}
    if "freeze" in pm:
        out["freeze"] = pm.get("freeze") in (True, 1, "1", "true")
    if "mix" in pm:
        out["mix"] = _clamp(_f(pm, "mix", 80), 0, 100, 0)
    return out


RETIRED = {"flanger": ("flanger-js", _flanger_from_calf),
           "chorus-js": ("chorus", _chorus_from_js),
           "phaser": ("phaser-js", _phaser_from_calf),
           "delay-tape": ("delay", _delay_from_calf),
           "delay-tape-aw": ("delay", _delay_from_airwindows),
           "delay-echo": ("delay", _delay_from_echocat),
           "eq-para": ("eq", _eq_from_x42),
           "surge-spring": ("reverb", _reverb_from_surge_spring),
           "boost": ("emet", _drive_from_proteus),
           "pitch-spectral": ("pitch", _pitch_from_spectral),
           "rezfilter": ("autowah", _autowah_from_rez),
           "freeze": ("granular", _grains_from_freeze)}


_IDENTITY = ("model", "algo", "type", "engine")


def _retire_type(t, pm):
    """Le type et la traduction d'un bloc retiré. Le Proteus se partage : un drive faible était un boost (Shem)."""
    if t == "boost" and isinstance(pm, dict) and (_f(pm, "drive", 30) or 0) <= 15:
        return "shem", _boost_from_proteus
    return RETIRED[t]


def _retire(doc):
    """Réécrit les blocs d'un type retiré (et leurs réglages rangés sous leur id : scènes, états de lane)."""
    n = 0
    ids = {}

    def blocks(o):
        nonlocal n
        if isinstance(o, dict):
            t = o.get("type")
            if isinstance(t, str) and t in RETIRED:
                to, conv = _retire_type(t, o.get("params"))
                o["type"] = to
                if isinstance(o.get("params"), dict):
                    o["params"] = conv(o["params"])
                if o.get("id") is not None:
                    ids[str(o["id"])] = conv
                n += 1
            for v in o.values():
                blocks(v)
        elif isinstance(o, list):
            for v in o:
                blocks(v)

    def keyed(o):
        if isinstance(o, dict):
            ps = o.get("params")
            if isinstance(ps, dict):
                for bid, conv in ids.items():
                    if isinstance(ps.get(bid), dict):
                        # une surcharge de scène ne dit que ce qu'elle change : l'identité posée par la traduction (le
                        # modèle Tape, la voix Spring…) appartient au bloc, jamais à une scène — un réglage structurel
                        # réécrit à chaque bascule rechargerait le moteur de la pédale
                        before = set(ps[bid])
                        ps[bid] = {k: v for k, v in conv(ps[bid]).items() if k not in _IDENTITY or k in before}
            for v in o.values():
                keyed(v)
        elif isinstance(o, list):
            for v in o:
                keyed(v)

    blocks(doc)
    if ids:
        keyed(doc)
    return n


# ── UN RÉGLAGE QUI CHANGE D'UNITÉ (catalogue v51, 2026-11-21 : grit joué par gfx-grit). Les quantités des modules et les
# gains de bande suivaient les lois de Prisma ; gfx-grit en a de nouvelles, linéaires dans une vraie unité (dB, bits).
# Le catalogue déclare `was` sur chaque réglage concerné : il a changé d'id en changeant d'unité (`lo_v1` -> `lo_amt1`,
# `lo_gain` en % -> `lo_lvl` en dB). Un document qui porte encore l'ancien id est converti au chargement, l'ancien id
# retiré : pur et idempotent comme `renamed`, un ancien id n'étant jamais un nouveau. Les formules sont celles de
# golem-fx (gfx-grit/README « converting golem's grit values », gfx-grit/src/convert.rs) ; la quantité d'un module se
# convertit selon le TYPE de son emplacement (`lo_m1` pour `lo_v1`).
_GRIT_BANDS = ("lo", "lm", "hm", "hi")
_GRIT_ZC = ((0.05, -67.0), (0.10, -46.0), (0.20, -34.0), (0.30, -30.0), (0.40, -27.0), (0.50, -25.0), (0.60, -22.5),
            (0.70, -20.0), (0.80, -16.0), (0.90, -11.0), (0.95, -8.5), (1.00, -6.0))


def _grit_zc(v):
    if v <= _GRIT_ZC[0][0]:
        return _GRIT_ZC[0][1]
    for (v0, t0), (v1, t1) in zip(_GRIT_ZC, _GRIT_ZC[1:]):
        if v <= v1:
            return t0 + (t1 - t0) * (v - v0) / (v1 - v0)
    return _GRIT_ZC[-1][1]


def grit_amount(kind, old_pct):
    """La quantité d'un module : l'ancien % (loi de Prisma) -> le % de gfx-grit, pour un emplacement de type `kind`."""
    v = min(1.0, max(0.0, float(old_pct) / 100.0))
    if kind in ("Soft clip", "Hard clip"):
        val = 1.0 - (1.0 - ((1.0 - v) ** 10 + 1.0 - v ** 0.2) / 2.0) * 0.99
        new = -20.0 * math.log10(val) / 48.0
    elif kind == "Fold":
        new = 20.0 * math.log10(70.0 * v * v + 1.0) / 48.0
    elif kind == "Sine fold":
        new = min(5.0 * v * v, 1.0) * 20.0 * math.log10(70.0 * v * v + 2.0) / 48.0
    elif kind == "Zero cross":
        new = (_grit_zc(v) + 66.0) / 60.0
    elif kind == "Bit crush":
        new = (16.0 - math.log2(2.0 / (0.99 * v ** 5 + 0.01))) / 15.0
    elif kind == "Gain":
        new = (40.0 * math.log10(v / 0.35) + 24.0) / 48.0 if v > 0 else 0.0
    elif kind == "DC":
        new = 0.5 + 0.5 * (2.0 * v - 1.0) ** 5
    elif kind == "Stereo DC":
        new = v ** 5
    else:                                        # Off, Heavy, Asym, Rectify, Sample divide, les filtres… : même loi
        new = v
    return round(100.0 * min(1.0, max(0.0, new)), 2)


def grit_level(old_pct):
    """Le gain d'une bande : l'ancien % ((2 g)², 50 % = 0 dB) -> des dB, −60 = muet."""
    g = float(old_pct) / 100.0
    return -60.0 if g <= 0 else round(min(12.0, max(-60.0, 40.0 * math.log10(2.0 * g))), 2)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _grit_units(pm, base=None):
    """Convertit EN PLACE les anciens ids de `pm` (les params d'un bloc grit, ou une surcharge de scène / d'état rangée
    sous son id). `base` = les params du bloc AVANT conversion, pour une surcharge : elle ne dit que ce qu'elle change,
    le type de l'emplacement vient alors du bloc. Une surcharge qui change le TYPE sans redire la quantité jouait la
    quantité du bloc dans la loi du nouveau type : on l'écrit, convertie pour ce type. Rend le nombre de valeurs."""
    if not isinstance(pm, dict):
        return 0
    base = base if isinstance(base, dict) else {}
    n = 0
    for b in _GRIT_BANDS:
        for i in (1, 2):
            old, new, mod = f"{b}_v{i}", f"{b}_amt{i}", f"{b}_m{i}"
            kind = pm.get(mod, base.get(mod, "Off"))
            if old in pm:
                v = pm.pop(old)
                if new not in pm and _num(v):
                    pm[new] = grit_amount(kind, v)
                n += 1
            elif mod in pm and new not in pm and _num(base.get(old)):
                pm[new] = grit_amount(kind, base[old])
                n += 1
        old, new = f"{b}_gain", f"{b}_lvl"
        if old in pm:
            v = pm.pop(old)
            if new not in pm and _num(v):
                pm[new] = grit_level(v)
            n += 1
    return n


def _units(doc):
    """Convertit les blocs grit d'un document (et leurs réglages rangés sous leur id : scènes, états de lane)."""
    n = 0
    ids = {}

    def blocks(o):
        nonlocal n
        if isinstance(o, dict):
            if o.get("type") == "grit":
                before = dict(o["params"]) if isinstance(o.get("params"), dict) else {}
                n += _grit_units(o.get("params"))
                if o.get("id") is not None:
                    ids[str(o["id"])] = before
            for v in o.values():
                blocks(v)
        elif isinstance(o, list):
            for v in o:
                blocks(v)

    def keyed(o):
        nonlocal n
        if isinstance(o, dict):
            ps = o.get("params")
            if isinstance(ps, dict):
                for bid, before in ids.items():
                    n += _grit_units(ps.get(bid), before)
            for v in o.values():
                keyed(v)
        elif isinstance(o, list):
            for v in o:
                keyed(v)

    blocks(doc)
    if ids:
        keyed(doc)
    return n


def apply(doc, tbl=None):
    """Réécrit EN PLACE les anciennes étiquettes de `doc` (n'importe quel document : preset, patch, preset de bloc).
    Rend le nombre de valeurs réécrites."""
    if not isinstance(doc, (dict, list)):
        return 0
    retired = _retire(doc) if tbl is None else 0           # un type retiré d'abord : ses renommages sont ceux du type qui reste
    if tbl is None:
        retired += _units(doc)                    # un réglage qui a changé d'unité (grit, catalogue v51)
    tbl = table() if tbl is None else tbl
    if not tbl:
        return retired
    by_id = {}                                   # id de bloc -> renommages de son type
    n = 0

    def blocks(o):
        nonlocal n
        if isinstance(o, dict):
            t = o.get("type")
            if isinstance(t, str) and t in tbl:
                n += _rename(o.get("params"), tbl[t])
                if o.get("id") is not None:
                    by_id[str(o["id"])] = tbl[t]
            for v in o.values():
                blocks(v)
        elif isinstance(o, list):
            for v in o:
                blocks(v)

    def keyed(o):
        nonlocal n
        if isinstance(o, dict):
            ps = o.get("params")
            if isinstance(ps, dict):
                for bid, ren in by_id.items():
                    n += _rename(ps.get(bid), ren)
            for v in o.values():
                keyed(v)
        elif isinstance(o, list):
            for v in o:
                keyed(v)

    blocks(doc)
    if by_id:
        keyed(doc)
    return n + retired
