# SPDX-License-Identifier: GPL-3.0-or-later
"""CE QUE GOLEM SAIT JOUER (docs/library-tones.md §7) : une capture se décrit par sa NATURE (TONE3000 `gear` : amp,
amp-cab, cab, pedal, outboard) et son FORMAT (`nam` : un modèle neuronal ; `ir` : une réponse impulsionnelle). Le
couple dit quel bloc la joue — ou qu'aucun ne la joue encore.

Vécu le 2026-11-14 : « + Add outboard » a installé le Roland RE-301, 13 IR d'écho et de réverbe que TONE3000 range
sous « outboard » comme les préamplis NAM. Le modal ne montrait pas le format, l'install ne vérifiait rien : le pack
est entré sans bloc pour le jouer (le bloc Cab l'aurait coupé avant son premier écho). UNE règle, ici, sert la
recherche (filtre et verdict par résultat), l'installation (refus), le catalogue (`playable` par pack) et l'écran."""

# (nature, format) -> type du bloc qui la joue (le premier de PLAYS)
BLOCK = {
    ("amp", "nam"): "amp-nam",
    ("amp-cab", "nam"): "amp",
    ("pedal", "nam"): "pedal-nam",
    ("outboard", "nam"): "preamp-nam",          # ou comp-nam : bridge/audition.outboard_type le dit par le nom
    # une IR de baffle — ou d'une pédale de simulation, d'un ampli avec son baffle : le bloc Cab la joue
    ("cab", "ir"): "cab",
    ("pedal", "ir"): "cab",
    ("amp", "ir"): "cab",
    ("amp-cab", "ir"): "cab",
    ("outboard", "ir"): "ir-fx",                # lot B (docs/library-tones.md §8) : l'IR d'un appareil, jouée ENTIÈRE
}
# tous les blocs qui savent la jouer (le sélecteur de capture du Designer filtre dessus)
PLAYS = {("outboard", "nam"): ("preamp-nam", "comp-nam")}
WHY = {}
# une IR « pedal » LONGUE est une réverbe ou un écho (Boss RV-6 en IR), pas un simulateur de baffle : sa longueur
# MESURÉE à l'install (ir_kind) la donne à ir-fx ; courte, le bloc Cab la joue
EFFECT_IR_MS = 250
FORMATS = ("nam", "ir")


def _gears(gear):
    return [g.strip() for g in str(gear or "").split(",") if g.strip()]


def block_for(gear, fmt, ir_kind=None):
    """Le type du bloc qui joue cette capture ici, ou None. `ir_kind` = « effect » pour une IR mesurée longue."""
    fmt = str(fmt or "nam").lower()
    if fmt == "ir" and ir_kind == "effect":
        return "ir-fx"
    for g in _gears(gear) or [""]:
        b = BLOCK.get((g, fmt))
        if b:
            return b
    return None


def plays(tone):
    """Les types de blocs qui jouent cette entrée du catalogue (vide = aucun)."""
    fmt = str(tone.get("format") or "nam").lower()
    b = block_for(tone.get("gear"), fmt, tone.get("ir_kind"))
    if not b:
        return []
    for g in _gears(tone.get("gear")):
        if (g, fmt) in PLAYS and b == BLOCK.get((g, fmt)):
            return list(PLAYS[(g, fmt)])
    return [b]


def ir_kind_of(files):
    """« effect » si une des IR dure (énergie au-dessus de -60 dB sous la crête) plus de EFFECT_IR_MS, sinon « cab ».
    Lit les fichiers ; un fichier illisible ne compte pas."""
    from .compile_rig import _read_wav_mono
    for f in files:
        try:
            x, sr = _read_wav_mono(f)
        except (OSError, ValueError):
            continue
        peak = max((abs(v) for v in x), default=0.0)
        if peak <= 0:
            continue
        floor = peak * 0.001                                    # -60 dB
        last = next((i for i in range(len(x) - 1, -1, -1) if abs(x[i]) >= floor), 0)
        if 1000.0 * last / sr > EFFECT_IR_MS:
            return "effect"
    return "cab"


def verdict(gear, fmt, ir_kind=None):
    """(jouable, phrase pour le musicien — vide si jouable). Un bloc en quarantaine SUR CETTE MACHINE (ir-fx sous
    Windows et macOS : pas de convolveur stéréo mappé) ne joue rien ici."""
    b = block_for(gear, fmt, ir_kind)
    if b:
        q = _quarantined().get(b)
        return (False, f"golem cannot play this here yet: {q}") if q else (True, "")
    fmt = str(fmt or "nam").lower()
    for g in _gears(gear):
        if (g, fmt) in WHY:
            return False, WHY[(g, fmt)]
    kind = {"nam": "NAM capture", "ir": "impulse response"}.get(fmt, f"'{fmt}' file")
    return False, f"golem has no block that plays this kind of {kind} ({gear or 'unknown gear'}) yet."


def formats_for(gears):
    """Les formats qu'une recherche filtrée sur ces natures peut installer : le filtre `format` de TONE3000 quand il
    n'y en a qu'un (« outboard » -> nam), sinon None (les deux, chaque résultat porte son verdict)."""
    gl = [g for g in str(gears or "").replace(",", "_").split("_") if g]
    if not gl:
        return None
    ok = {f for g in gl for f in FORMATS if (g, f) in BLOCK}
    return next(iter(ok)) if len(ok) == 1 else None


def _quarantined():
    try:
        from . import rig
        return rig.quarantined_types() or {}
    except Exception:
        return {}
