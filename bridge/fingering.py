# SPDX-License-Identifier: GPL-3.0-or-later
"""LA MAIN — choisir la corde et la case comme un guitariste (docs/tablature-fingering.md §5).

Un guitariste ne choisit pas note par note : il prend une FORME, et sa main RESTE où elle est. Le doigté
naïf (`transcribe.naive_fingering`, la case la plus basse) est mathématiquement minimal et musicalement faux :
l'octave jouée `0 7 x 9` (mi grave à vide, la case 7, sol case 9) devenait `0 x 2 x x 0`.

Ici :
  1. CANDIDATS — pour chaque groupe d'attaques simultanées, toutes les façons de le jouer : une note par
     corde, case 0 à `max_fret`, écart des notes fretées ≤ `max_span`.
  2. COÛT d'un candidat seul (l'écart des doigts, la hauteur, les cordes à vide quand la main est haute) moins
     les FORMES connues (octave à corde sautée, power chord) ; et coût d'une TRANSITION (la main qui bouge, la
     corde qui change dans une ligne mélodique).
  3. LE MORCEAU ENTIER d'un coup — programmation dynamique (Viterbi) : la meilleure SUITE de positions, pas le
     meilleur accord isolé.

Module AUTONOME (§4) : bibliothèque standard seulement, rien du bridge, aucun effet à l'import — golem.fm en
recevra une copie (« une source, deux exécutions »). Les POIDS sont des données (`WEIGHTS`), calibrées par
`tools/check-fingering.py` sur les partitions Guitar Pro (corpus A) ; `FINGERING_VERSION` monte dès qu'un
RÉSULTAT change.

4. CE QUE LE SON DIT DE LA CORDE (v2, 2026-10-29, banc TX de golem.fm) : quand la guitare est étalonnée, le B
   d'inharmonicité MESURÉ d'une note seule (`inharm.estimate_b`) est comparé à celui que prévoit chaque forme,
   B = B_vide(corde)·2^(case/6) — un coût de preuve de plus, plafonné (`evidence_cost`). Sans mesure, rien ne change.
"""
import math

FINGERING_VERSION = 3

# Accordages standard, du GRAVE à l'AIGU (notes MIDI). La corde 1 (MusicXML) est la plus aiguë.
STANDARD = {"guitar": (40, 45, 50, 55, 59, 64), "bass": (28, 33, 38, 43)}

# Les poids — ce que la calibration règle. Tous en « coût » : plus c'est haut, moins le choix plaît.
#   span       écart des doigts (case max − case min des notes fretées), par case
#   height     la hauteur de la main, par octave de case (une légère préférence pour le bas du manche)
#   open       une corde à vide, toujours un peu (la vérité en a 14 %, le naïf 23 %)
#   open_high  une corde à vide AU-DESSUS d'une note fretée quand la main est HAUTE (≥ `open_from` case) : le mi
#              grave de `0 7 x 9` (sous les doigts, une pédale) est juste, une corde aiguë à vide dans un solo case 12 non
#   open_from  la case à partir de laquelle une corde à vide « tire » la main
#   shape_*    bonus (retranché) d'une forme connue : power chord ; octave à corde sautée sur les cordes graves
#              (mi→ré, la→sol) ; octave qui enjambe la corde de si (ré→si, sol→mi aigu)
#   reach      ce que la main couvre SANS bouger (cases) : quatre doigts, une position
#   move       la main qui se déplace, par case au-delà de sa portée (centre des notes fretées)
#   shift      un déplacement, quel qu'il soit (rester dans la position vaut quelque chose en soi)
#   string     changer de corde dans une ligne de notes seules, par corde
#   max_span   l'écart maximal d'une forme (cases)
#   max_fret   la case la plus haute
WEIGHTS = {
    "guitar": {"span": 0.5, "height": 0.3, "open": 0.5, "open_high": 3.0, "open_from": 5.0, "shape_power": 1.5, "shape_oct_low": 1.5, "shape_oct_high": 1.5,
               "move": 1.0, "shift": 1.0, "reach": 3.0, "string": 0.2, "max_span": 4.0, "max_fret": 22.0},
    "bass": {"span": 0.5, "height": 0.3, "open": 0.5, "open_high": 3.0, "open_from": 5.0, "shape_power": 1.5, "shape_oct_low": 1.5, "shape_oct_high": 1.5,
             "move": 1.0, "shift": 1.0, "reach": 3.0, "string": 0.2, "max_span": 4.0, "max_fret": 24.0},
}
MAX_CANDIDATES = 48              # par groupe, les moins chers : un accord de 6 notes n'en a de toute façon que peu
#: LA PREUVE DE L'OREILLE : l'écart toléré en octaves de B, et le plafond d'une note — au-delà c'est la mesure qui
#: est fausse (une sur cinq environ), pas la corde. 0,35 (la dispersion de TX01) laissait le sol à vide perdre contre
#: le ré case 5 (B prévus à 0,18 octave l'un de l'autre) ; 0,2 le départage, mesuré au banc TX le 2026-10-29 (deux
#: prises à vide concordent à 6 % près ; 10 prises, rien d'autre ne bouge)
EVIDENCE_SIGMA_OCT = 0.2
EVIDENCE_CAP = 4.0
EVIDENCE_TAIL = 0.15                     # par unité de dispersion au-delà du plafond
W_EVIDENCE = 1.0
#: QUAND L'OREILLE NE PEUT PAS TRANCHER, LA CORDE À VIDE (2026-10-30, 8 cordes du mainteneur : le sol à vide et le ré case 5
#: prévoient le même B à 2 % près, et la tab écrivait la ronde de sol à vide en case 5). Une note jugée dont la forme à
#: vide et une forme fretée prévoient des B à moins de DEAF_OCT l'une de l'autre : la mesure ne dit rien, la forme à
#: vide reçoit OPEN_WHEN_DEAF. Au-delà (le sol de la 6 cordes : 0,15 octave), c'est l'oreille qui décide, seule.
DEAF_OCT = 0.08
OPEN_WHEN_DEAF = 1.0
#: LES POINTS D'APPUI : une note dont une forme colle au B lu (coût ≤ ANCHOR_FIT) et la suivante loin derrière
#: (≥ ANCHOR_GAP de plus) ; ses voisines non lues, jusqu'à ANCHOR_SPAN notes de part et d'autre, paient ANCHOR_W par
#: douzaine de cases d'écart à elle.
ANCHOR_FIT = 1.0
ANCHOR_GAP = 2.0
ANCHOR_SPAN = 16
ANCHOR_W = 1.0
#: LA CARTE DU MANCHE (2026-11-01, `bridge/neckmap.py`) : l'écart de l'empreinte d'une note à celle de chaque position
#: possible, mesurée sur la guitare case par case, pèse W_NECK, plafonné à NECK_CAP. Choisis sur la 8 cordes du mainteneur,
#: riffs ET rondes ensemble : 0,5 sans plafond gagnait 10 notes de riff mais envoyait deux mi graves à vide en corde 7
#: case 7 ; plafonné à 2, il en gagne 6 et ne perd aucune ronde.
W_NECK = 0.5
NECK_CAP = 2.0


def _strings(tuning):
    """[(numéro MusicXML, note à vide)] de l'aiguë à la grave."""
    n = len(tuning)
    return [(n - i, p) for i, p in enumerate(tuning)][::-1]


def candidates(pitches, tuning, w):
    """Toutes les façons jouables d'un groupe : [((pitch, corde, case), …)], une corde par note."""
    pitches = sorted(set(pitches), reverse=True)
    strings = _strings(tuning)
    max_fret, max_span = int(w["max_fret"]), w["max_span"]
    opts = [[(p, s, p - o) for s, o in strings if 0 <= p - o <= max_fret] for p in pitches]
    out = []

    def walk(i, used, acc, lo, hi):
        if len(out) >= 4000:                         # garde-fou : un groupe absurde ne fige pas la transcription
            return
        if i == len(opts):
            out.append(tuple(acc))
            return
        for p, s, f in opts[i]:
            if s in used:
                continue
            nlo, nhi = (min(lo, f), max(hi, f)) if f > 0 else (lo, hi)
            if f > 0 and nhi - nlo > max_span:
                continue
            walk(i + 1, used | {s}, acc + [(p, s, f)], nlo, nhi)
    walk(0, frozenset(), [], 99, -1)
    return out


def _center(c):
    fr = [f for _, _, f in c if f > 0]
    return sum(fr) / len(fr) if fr else None


def static_cost(c, w):
    """Le coût d'une forme, seule."""
    fr = [f for _, _, f in c if f > 0]
    opens = sum(1 for _, _, f in c if f == 0)
    low = min(fr) if fr else 0
    cost = w["span"] * ((max(fr) - min(fr)) if fr else 0) + w["height"] * low / 12.0 + w["open"] * opens
    # une corde à vide SOUS les doigts (le mi grave de `0 7 x 9`) est une pédale : un geste normal. Celle qui tire la
    # main, c'est la corde à vide AU-DESSUS d'une note fretée quand la main est haute.
    if opens and fr and low >= w["open_from"]:
        deepest = max(s for _, s, f in c if f > 0)
        cost += w["open_high"] * sum(1 for _, s, f in c if f == 0 and s < deepest)
    # LES FORMES CONNUES — ce qu'aucune bibliothèque ne sait : on les reconnaît sur les CORDES et les CASES, pas
    # sur les hauteurs (les mêmes notes ailleurs ne sont pas la même forme)
    by_string = {s: (p, f) for p, s, f in c}
    for s, (p, f) in by_string.items():
        up1, up2 = by_string.get(s - 1), by_string.get(s - 2)
        # power chord : la quinte sur la corde voisine aiguë, 2 cases plus haut (corde de si exceptée : 3)
        if up1 and up1[0] - p == 7 and up1[1] - f == (3 if s == 3 else 2):
            cost -= w["shape_power"]
        # octave à corde sautée : 2 cases plus haut sur les cordes graves (mi→ré, la→sol), 3 quand on enjambe la
        # corde de si (ré→si, sol→mi aigu) — deux formes que le corpus départage
        if up2 and up2[0] - p == 12 and up2[1] - f == (3 if s in (3, 4) else 2):
            cost -= w["shape_oct_low"] if s >= 5 else w["shape_oct_high"]
    return cost


def evidence_cost(c, b_meas, b_open):
    """Ce que le son dit d'une forme d'UNE note : (log2 B mesuré − log2 B prévu)² en unités de dispersion, plafonné.
    0 quand on ne peut pas juger (accord, pas de mesure, corde non étalonnée)."""
    if b_meas is None or b_meas <= 0 or len(c) != 1:
        return 0.0
    _p, s, f = c[0]
    if s not in b_open:
        return 0.0
    z = (math.log2(b_meas) - (math.log2(b_open[s]) + f / 6.0)) / EVIDENCE_SIGMA_OCT
    # au-delà du plafond, la mesure est fausse — mais entre deux formes qu'elle contredit toutes deux, la plus proche
    # reste la plus probable (prise 290 : le la grave lu 1,3e-4, à 1 octave de la corde 7 à vide, à 2,4 de la corde 8
    # case 5 : plafonnées ensemble, la case 5 gagnait au doigté)
    tail = EVIDENCE_TAIL * max(abs(z) - math.sqrt(EVIDENCE_CAP), 0.0)
    return W_EVIDENCE * (min(z * z, EVIDENCE_CAP) + tail)


def deaf_bonus(cs, b_open):
    """{forme à vide : bonus} quand une forme fretée de la même note prévoit le même B qu'elle (à DEAF_OCT près)."""
    pred = {c: math.log2(b_open[c[0][1]]) + c[0][2] / 6.0 for c in cs if len(c) == 1 and c[0][1] in b_open}
    opens = [c for c in pred if c[0][2] == 0]
    return {o: OPEN_WHEN_DEAF for o in opens
            if any(c[0][2] > 0 and abs(pred[c] - pred[o]) < DEAF_OCT for c in pred)}


def _anchor(ev):
    """La case d'une note que le son place SANS DOUTE (une forme qui colle, la suivante loin derrière), ou None."""
    if len(ev) < 2:
        return None
    (c0, e0), (_c1, e1) = sorted(ev.items(), key=lambda x: x[1])[:2]
    return c0[0][2] if e0 <= ANCHOR_FIT and e1 - e0 >= ANCHOR_GAP else None


def _center1(c):
    """La case d'une forme pour la comparer à un point d'appui : la moyenne de ses cases (une corde à vide : 0)."""
    fr = [f for _, _, f in c]
    return sum(fr) / len(fr) if fr else 0.0


def move_cost(a, b, w):
    """Le coût de passer de la forme `a` à la forme `b`."""
    ca, cb = _center(a), _center(b)
    cost = 0.0
    if ca is not None and cb is not None:
        # la MAIN couvre `reach` cases sans bouger (quatre doigts) : dans une position, une gamme change de case
        # à chaque note sans que la main se déplace. Seul ce qui sort de cette portée est un déplacement.
        d = abs(cb - ca) - w["reach"]
        if d > 0:
            cost += w["shift"] + w["move"] * d
    if len(a) == 1 and len(b) == 1:                  # une ligne mélodique : la corde suit
        cost += w["string"] * abs(a[0][1] - b[0][1])
    return cost


def fingering(groups, tuning=None, weights=None, instrument="guitar", heard=None, b_open=None, neck=None):
    """Groupes de hauteurs (une liste par attaque) -> pour chacun [(pitch, corde, case)] de l'aigu au grave.
    Une note qu'aucune forme ne peut jouer sort avec (pitch, None, None) — dite, pas inventée.
    `heard[i]` = le B mesuré du groupe i (ou None), `b_open` = {corde: B à vide} de la guitare (§4). Une note n'est
    jugée que si TOUTES les cordes qui peuvent la jouer sont étalonnées : comparer une corde connue à une corde
    inconnue, c'est déclarer, pas lire. `neck[i]` = ce que la carte du manche dit du groupe i ({(corde, case): écart},
    `neckmap.costs`) ou None : une preuve de plus, même pour une note trop brève pour son B."""
    tuning = tuple(tuning or STANDARD[instrument])
    w = dict(WEIGHTS[instrument], **(weights or {}))
    b_open = b_open or {}
    cands, costs, anchors = [], [], []
    for i, g in enumerate(groups):
        cs = candidates(g, tuning, w) if g else [()]
        if not cs:                                    # injouable en une forme : on retire la note la plus aiguë
            ps = sorted(set(g), reverse=True)
            while ps and not cs:
                ps = ps[1:]
                cs = candidates(ps, tuning, w) if ps else []
            cs = cs or [()]
        bm = heard[i] if heard and i < len(heard) else None
        calibrated = bool(b_open) and all(len(c) == 1 and c[0][1] in b_open for c in cs)
        judge = calibrated and bm is not None and bm > 0
        # une note seule, guitare étalonnée, mais une mesure qui ne dit rien (B nul : 8 cordes, prises 288 et 292, le
        # mi de la corde 6 sous le mi grave qui sonne encore) : l'oreille est sourde à TOUTES les formes — la corde à
        # vide, comme quand deux formes prévoient le même B
        # (B nul seulement : une note trop brève pour être mesurée — `None` — n'a rien dit du tout, et la tirer vers une
        # corde à vide casse la position d'un trait rapide : riff de 2026-10-30, prise 305)
        if calibrated and bm is not None and bm <= 0:
            deaf = {c: OPEN_WHEN_DEAF for c in cs if c[0][2] == 0}
        else:
            deaf = deaf_bonus(cs, b_open) if judge else {}
        ev = {c: evidence_cost(c, bm, b_open) for c in cs} if judge else {}
        nk = neck[i] if neck and i < len(neck) else None
        if nk:
            for c in cs:
                if len(c) == 1 and (c[0][1], c[0][2]) in nk:
                    ev[c] = ev.get(c, 0.0) + W_NECK * min(nk[(c[0][1], c[0][2])], NECK_CAP)
        scored = sorted(((static_cost(c, w) + ev.get(c, 0.0) - deaf.get(c, 0.0), c)
                         for c in cs), key=lambda x: x[0])[:MAX_CANDIDATES]
        cands.append([c for _, c in scored])
        costs.append([v for v, _ in scored])
        anchors.append(_anchor(ev))

    # LA MAIN RESTE OÙ L'OREILLE L'A VUE (2026-10-30, riffs du mainteneur en position haute) : entre deux notes que le son
    # a placées sans doute possible, les notes trop brèves pour être lues ont souvent plusieurs doigtés aussi
    # jouables l'un que l'autre (le même motif case 3 ou case 10) ; la main choisit celui qui reste près des cases
    # entendues. Sans oreille (corpus, guitare non étalonnée), aucun point d'appui : rien ne change.
    marks = [(i, a) for i, a in enumerate(anchors) if a is not None]
    if marks:
        for i in range(len(cands)):
            near = [fa for j, fa in marks if j != i and abs(j - i) <= ANCHOR_SPAN]
            if anchors[i] is not None or not near:
                continue
            costs[i] = [v + ANCHOR_W * min(abs(_center1(c) - fa) for fa in near) / 12.0 for v, c in zip(costs[i], cands[i])]

    # Viterbi : best[i][k] = coût minimal d'une suite qui finit sur le candidat k du groupe i
    n = len(cands)
    if not n:
        return []
    best, back = [costs[0][:]], [[-1] * len(cands[0])]
    for i in range(1, n):
        row, brow = [], []
        for k, c in enumerate(cands[i]):
            v, arg = min(((best[i - 1][j] + move_cost(cp, c, w), j) for j, cp in enumerate(cands[i - 1])),
                         key=lambda x: x[0])
            row.append(v + costs[i][k])
            brow.append(arg)
        best.append(row)
        back.append(brow)
    k = min(range(len(best[-1])), key=lambda j: best[-1][j])
    path = [0] * n
    for i in range(n - 1, -1, -1):
        path[i] = k
        k = back[i][k]
    out = []
    for i, g in enumerate(groups):
        c = cands[i][path[i]]
        placed = {p: (p, s, f) for p, s, f in c}
        out.append(sorted([placed.get(p, (p, None, None)) for p in set(g)], key=lambda x: -x[0]))
    return out

