# SPDX-License-Identifier: GPL-3.0-or-later
"""CE QUE GOLEM SAIT JOUER (docs/library-tones.md §7) : une capture se décrit par sa NATURE (TONE3000 `gear` : amp,
amp-cab, cab, pedal, outboard) et son FORMAT (`nam` : un modèle neuronal ; `ir` : une réponse impulsionnelle). Le
couple dit quel bloc la joue — ou qu'aucun ne la joue encore.

Vécu le 2026-11-14 : « + Add outboard » a installé le Roland RE-301, 13 IR d'écho et de réverbe que TONE3000 range
sous « outboard » comme les préamplis NAM. Le modal ne montrait pas le format, l'install ne vérifiait rien : le pack
est entré sans bloc pour le jouer (le bloc Cab l'aurait coupé avant son premier écho). UNE règle, ici, sert la
recherche (filtre et verdict par résultat), l'installation (refus), le catalogue (`playable` par pack) et l'écran."""

# (nature, format) -> type du bloc qui la joue
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
}
WHY = {
    ("outboard", "ir"): "This is a set of impulse responses of a studio unit (an echo, a reverb): "
                        "no golem block plays a full-length impulse response yet.",
}
FORMATS = ("nam", "ir")


def _gears(gear):
    return [g.strip() for g in str(gear or "").split(",") if g.strip()]


def block_for(gear, fmt):
    """Le type du bloc qui joue cette capture ici, ou None."""
    fmt = str(fmt or "nam").lower()
    for g in _gears(gear) or [""]:
        b = BLOCK.get((g, fmt))
        if b:
            return b
    return None


def verdict(gear, fmt):
    """(jouable, phrase pour le musicien — vide si jouable)."""
    if block_for(gear, fmt):
        return True, ""
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
