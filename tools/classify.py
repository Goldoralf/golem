#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
classify — normalise la bibliothèque : détecte la MARQUE d'ampli/pédale de chaque tone
et un nom propre, puis regroupe. Enrichit library/catalog/tones-index.json (champs
`brand` + `amp`) et écrit library/catalog/brands.json (vue groupée pour l'app).

Heuristique : on scrute makes[] (prioritaire) puis le titre, contre un dico de marques
ordonné (spécifique avant générique). On ignore le bruit (micros, HP/cabs seuls, pédales
quand on cherche un ampli, loadboxes).

  ./tools/classify.py            # applique et écrit
  ./tools/classify.py --report   # affiche le rapport sans rien écrire
"""
import sys, os, json, re, collections

# ── CONTRAT AVEC golem.fm (2026-09-14, décision : UNE source pour le classement du matériel) ──
# golem.fm balaie TONE3000 avec SON jeton et classe avec CE module, copié par script à chaque
# release du rack (comme effects.json). Il doit donc rester IMPORTABLE SEUL (stdlib uniquement,
# rien du bridge) et ne RIEN écrire à l'import ; le main() ci-dessous ne concerne que le rack.
# Signatures figées : detect_brand(makes, title, gear) · clean_amp_name(makes, title, gear, brand)
# · is_pack(makes, title, tid) · legendary(). Incrémenter CLASSIFIER_VERSION à chaque changement
# de résultat (table, motif, règle) : le rack l'envoie dans le heartbeat, golem.fm compare.
CLASSIFIER_VERSION = 2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "library", "catalog", "tones-index.json")
BRANDS_OUT = os.path.join(ROOT, "library", "catalog", "brands.json")
# les amplis « légendaires » (wishlist + curation : style, ère, note) voyagent AVEC le module
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "classify-data")
LEGENDARY = os.path.join(DATA_DIR, "legendary-amps.json")


def legendary():
    """La liste des amplis de référence (tools/classify-data/legendary-amps.json), à plat :
    [{make, search, style, tags, era, note, category}] — la catégorie du fichier reportée sur
    chaque entrée. golem.fm en tire `curated` / `style` / `era` / `note` du catalogue marché."""
    d = json.load(open(LEGENDARY))
    out = []
    for cat, grp in (d.get("categories") or {}).items():
        for it in (grp or {}).get("amps") or []:
            out.append({**it, "category": cat, "category_label": (grp or {}).get("label") or cat})
    return out

# Marques d'amplis (guitare + basse). Ordre = spécifique avant générique ; 1er match gagne.
# (canonique, [motifs regex testés en minuscule contre makes+titre])
AMP_BRANDS = [
    ("EVH",            [r"\bevh\b", r"5150 ?iii", r"5153", r"stealth"]),
    ("Peavey",         [r"\bpeavey\b", r"\b6505\b", r"\b5150\b"]),
    ("Mesa/Boogie",    [r"\bmesa\b", r"boogie", r"rectifier", r"\brecto\b", r"badlander",
                        r"\bmark ?(i{1,3}v?|v?i{1,3}|iv|v|vii?)\b", r"\bmk ?(iic\+?|iv|v)\b", r"subway", r"triaxis"]),
    ("Marshall",       [r"\bmarshall\b", r"\bjcm\s?\d", r"\bjmp\b", r"plexi", r"\b1959\b",
                        r"\bjvm\b", r"\b220[34]\b", r"\bslp\b", r"\btsl\b", r"bluesbreaker", r"jtm"]),
    ("Fender",         [r"\bfender\b", r"twin reverb", r"deluxe reverb", r"super reverb",
                        r"princeton", r"bassman", r"tweed", r"\b5e3\b", r"vibrolux", r"\bdeville\b"]),
    ("Vox",            [r"\bvox\b", r"\bac ?30\b", r"\bac ?15\b"]),
    ("Diezel",         [r"\bdiezel\b", r"\bvh4\b", r"\bherbert\b"]),
    ("Bogner",         [r"\bbogner\b", r"ecstasy", r"ecstacy", r"uberschall"]),
    ("Soldano",        [r"\bsoldano\b", r"\bslo ?-?100\b", r"\bslo\b", r"super lead overdrive"]),
    ("Friedman",       [r"\bfriedman\b", r"\bbe ?-?100\b", r"brown eye", r"\bplex\b"]),
    ("Revv",           [r"\brevv\b", r"generator 120", r"\brv\d\d\b"]),
    ("Fortin",         [r"\bfortin\b", r"\bnatas\b", r"evil pumpkin", r"hexdrive", r"grinder"]),
    ("Randall",        [r"\brandall\b", r"warhead", r"dimebag", r"dimezone", r"satan"]),
    ("ENGL",           [r"\bengl\b", r"powerball", r"fireball", r"ironball", r"savage", r"steve morse"]),
    ("Roland",         [r"\broland\b", r"jazz chorus", r"\bjc ?-?120\b"]),
    ("Ampeg",          [r"\bampeg\b", r"\bsvt\b", r"\bb-?15\b", r"portaflex"]),
    ("Orange",         [r"\borange\b", r"rockerverb", r"rockverb", r"\bor\d\d\b", r"thunderverb"]),
    ("Blackstar",      [r"\bblackstar\b", r"\bht-?\d", r"series one", r"\bht ?dual\b"]),
    ("Hiwatt",         [r"\bhiwatt\b", r"\bdr ?103\b"]),
    ("Dumble",         [r"\bdumble\b", r"overdrive special", r"\bods\b"]),
    ("Darkglass",      [r"\bdarkglass\b", r"\bb7k\b", r"\bb3k\b", r"alpha omega", r"alpha omicron",
                        r"microtubes", r"\bx ultra\b", r"hyper luminal", r"harmonic booster"]),
    ("Aguilar",        [r"\baguilar\b", r"\bdb ?7?51\b", r"tone hammer"]),
    ("Gallien-Krueger",[r"gallien", r"\bg-?k\b", r"\brb ?\d{3}\b"]),
    ("Polytone",       [r"\bpolytone\b", r"mini-?brute"]),
    ("Henriksen",      [r"\bhenriksen\b"]),
    ("PRS",            [r"\bprs\b", r"archon"]),
    ("Suhr",           [r"\bsuhr\b", r"\bpt-?\d", r"\bsl67\b", r"badger"]),
    ("Synergy",        [r"\bsynergy\b", r"\bsyn-?\d"]),
    ("Victory",        [r"\bvictory\b", r"\bvx?\d+\b kraken", r"kraken", r"\bsheriff\b"]),
    ("BadCat",         [r"\bbadcat\b", r"\blynx\b"]),
    ("Omega Ampworks", [r"\bomega ampworks\b", r"granophyre"]),
    ("Framus",         [r"\bframus\b", r"\bcobra\b", r"dragon"]),
    ("EBS",            [r"\bebs\b"]),
    ("Glockenklang",   [r"glockenklang"]),
    ("Behringer",      [r"\bbehringer\b", r"v-?amp"]),
    ("SinMix",         [r"\bsinmix\b", r"sinamp"]),
]

# Marques de pédales (pour gear=pedal). Réutilise certaines marques d'ampli (Fortin, Darkglass…).
PEDAL_BRANDS = [
    ("Ibanez",     [r"\bibanez\b", r"\bts ?-?808\b", r"\bts ?-?9\b", r"tube screamer"]),
    ("Maxon",      [r"\bmaxon\b", r"\bod ?808\b"]),
    ("Boss",       [r"\bboss\b", r"\bbd-?2\b", r"\bsd-?1\b", r"blues driver"]),
    ("MXR",        [r"\bmxr\b", r"wylde", r"\bzakk\b"]),
    ("JHS",        [r"\bjhs\b", r"bonsai"]),
    ("Xotic",      [r"\bxotic\b", r"\bbb\b"]),
    ("Suhr",       [r"\bsuhr\b", r"shiba", r"riot"]),
    ("Fortin",     [r"\bfortin\b", r"hexdrive", r"33\b", r"grind"]),
    ("Darkglass",  [r"\bdarkglass\b", r"duality"]),
    ("Origin Effects", [r"origin effects", r"halcyon"]),
    ("Friedman",   [r"\bfriedman\b", r"\bbe-?od\b", r"dirty shirley"]),
    ("Wampler",    [r"\bwampler\b", r"tumnus"]),
    ("Klon",       [r"\bklon\b", r"centaur"]),
    ("Voodoo Lab", [r"voodoo lab", r"proctavia"]),
]

# Marques d'OUTBOARD (gear=outboard, 2026-09-14) : préamplis, tranches, compresseurs, magnétophones.
# Pour tout AUTRE gear, ces mêmes noms sont du BRUIT (le Neve 1073 d'une chaîne de capture d'ampli
# n'est pas l'appareil capturé) — voir PRE_NOISE.
OUTBOARD_BRANDS = [
    # les CLONES avant l'original : « BAE 1073 », « WA273 », « Stam 1073 » portent le numéro Neve
    ("BAE",               [r"\bbae\b"]),
    ("Warm Audio",        [r"warm audio", r"\bwa-?\d{2,4}\b"]),
    ("Stam Audio",        [r"\bstam\b"]),
    ("Petroglyph",        [r"\bpetroglyph\b"]),
    ("Heritage Audio",    [r"heritage audio", r"\bha-?73\b"]),
    ("Vintech",           [r"\bvintech\b", r"\bx73\b"]),
    ("Golden Age",        [r"golden age", r"\bgap\b", r"\bpre-?73\b"]),
    ("Chameleon Labs",    [r"chameleon"]),
    ("Aurora Audio",      [r"\baurora\b", r"\bgtq"]),
    ("Great River",       [r"great river", r"\bme-?1nv\b"]),
    ("Audioscape",        [r"\baudioscape\b"]),
    ("Sound Skulptor",    [r"sound skulptor", r"\bmp-?573\b"]),
    ("Lindell",           [r"\blindell\b"]),
    ("Hairball",          [r"\bhairball\b", r"\blola\b"]),
    ("CAPI",              [r"\bcapi\b", r"\bvp-?28\b", r"\bvp-?26\b"]),
    ("Rupert Neve Designs", [r"rupert neve", r"\brnd\b", r"\b5059\b", r"\b511\b", r"\bshelford\b"]),
    ("Neve",              [r"\bneve\b", r"\b1073", r"\b1057\b", r"\b31102\b", r"\b1084\b", r"\b33609\b"]),   # 1073MP, 1073N…
    ("Universal Audio",   [r"universal audio", r"\bua\b", r"\b610-?b?\b", r"\b1176", r"\bla-?2a\b", r"\bla-?3a\b"]),
    ("API",               [r"\bapi\b", r"\b512c?\b", r"\b2500\b"]),
    ("Avalon",            [r"\bavalon\b", r"\bvt-?737\b", r"\bad-?2022\b"]),
    ("Thermionic Culture", [r"thermionic", r"culture vulture"]),
    ("Tascam",            [r"\btascam\b", r"\bporta ?0?\d\b", r"\b424\b"]),
    ("SSL",               [r"\bssl\b", r"solid state logic", r"\bgssl\b", r"\b4000\b"]),   # pas « bus comp » : Audioscape en fait un
    ("Manley",            [r"\bmanley\b", r"\bvoxbox\b", r"\bvari-?mu\b"]),
    ("Tube-Tech",         [r"tube-?tech", r"\bcl ?1b\b"]),
    ("Empirical Labs",    [r"empirical", r"\bdistressor\b", r"\bel-?8\b"]),
    ("Chandler",          [r"\bchandler\b", r"\btg-?2\b"]),
    ("dbx",               [r"\bdbx\b", r"\b160\b"]),
    ("Teletronix",        [r"\bteletronix\b"]),
    ("Pultec",            [r"\bpultec\b", r"\beqp-?1a?\b"]),
    ("Focusrite",         [r"\bfocusrite\b", r"\bisa\b"]),
]
# Outboard dans la chaîne de capture d'un AUTRE appareil : bruit pour le nom (« Neve 1073 » d'un
# ampli capturé au micro). Appliqué seulement quand le gear N'EST PAS outboard.
# ⚠ pas le MOT « preamp » : un « Mesa Subway Bass DI-Preamp » EST l'ampli d'une capture basse
# (tone 70614 — mesuré en le retirant : le nom tombait sur la pédale Darkglass de la chaîne).
PRE_NOISE = re.compile(r"\b(neve|1073|1084|1176|la-?2a|api ?512|avalon|bae|1057|rnd|shelford|cl ?1b|"
                       r"distressor|pultec|focusrite|isa ?\d*)\b", re.I)

# Un make qui EST un baffle/HP/loadbox de la chaîne (pas l'appareil capturé) : ignoré pour la
# MARQUE d'un ampli ou d'une pédale. Les micros n'y sont pas : « Kingsley Page Henriksen Bud
# TL806 SM57 » est une chaîne entière qui porte l'ampli (tone 6484).
CAB_MAKE = re.compile(r"\b(4x12|2x12|1x12|6x10|8x10|cab|speakers?|celestion|vintage 30|v30|greenback|creamback|"
                      r"eminence|scumback|zilla|swamp thang|loadbox|reactive load|\bir\b)\b", re.I)

# Un make qui EST une pédale de la chaîne : ne vote pas pour la marque d'un AMPLI (tone 70614 :
# trois pédales Darkglass contre un Mesa Subway → Darkglass). Même liste que la moitié pédale de NOISE.
PEDAL_MAKE = re.compile(r"\b(ts ?-?9|ts ?-?808|od ?808|tube screamer|maxon|boss|bd-?2|sd-?1|xotic|wylde|mxr|"
                        r"king of drive|demonfx|duality|halcyon|origin effects|pepers|bb pre|microtubes|b3k|"
                        r"alpha omicron|deadweald|lichtlaerm|blues driver|fuzz|pedal|klon|centaur|"
                        r"tumnus|bonsai|shiba|riot|hexdrive|grind|dirty shirley|be-?od)\b", re.I)

# Bruit à ignorer pour CHOISIR un nom d'ampli (micros, HP/cabs nus, loadboxes, marques de pédale)
MIC_MAKE = re.compile(
    r"\b(sm ?-?57|sm ?-?58|sm ?-?7b?|shure|sennheiser|md ?-?421|e ?906|beyerdynamic|m160|akg|c414|"
    r"royer|r-?101|r-?121|neumann|u ?47|u ?87|telefunken|apollo|loadbox|reactive load|suhr reactive|"
    r"\bv-?type\b|ppc\d|fatboy|\bh75\b|dv-?77)\b", re.I)
# NOISE = l'union, pour un baffle (gear cab) et les appelants sans gear : rien n'y est l'appareil
NOISE = re.compile("|".join(r.pattern for r in (MIC_MAKE, CAB_MAKE, PEDAL_MAKE)), re.I)


def _noisy_for(gear):
    """Ce qui n'est PAS l'appareil selon la nature cherchée (golem.fm, 2026-09-14, v2) :
    ampli → micros, baffles, pédales, préamplis de chaîne ; pédale → micros, baffles, préamplis
    (les motifs de pédale sont l'appareil : « Ibanez TS808 Tube Screamer » est le nom, pas le
    titre qui varie par tone) ; outboard → micros, baffles, pédales (CAPI/VP28 est l'appareil)."""
    if gear in ("amp", "amp-cab"):
        parts = (MIC_MAKE, CAB_MAKE, PEDAL_MAKE, PRE_NOISE)
    elif gear == "pedal":
        parts = (MIC_MAKE, CAB_MAKE, PRE_NOISE)
    elif gear == "outboard":
        parts = (MIC_MAKE, CAB_MAKE, PEDAL_MAKE)
    else:
        return lambda m: NOISE.search(m)
    return lambda m: any(r.search(m) for r in parts)


def _hit(brands, text):
    for canon, pats in brands:
        for p in pats:
            if re.search(p, text):
                return canon
    return None

def _brand_of(brands, text):
    """LA marque d'un texte : la première de la table qui matche — spécifique avant générique DANS
    un make. « Rupert Neve Designs Shelford Channel » matche RND et Neve : RND (v2, golem.fm :
    « Shelford » sortait Neve parce qu'un make voisin disait Neve)."""
    t = str(text or "").lower()
    for rank, (canon, pats) in enumerate(brands):
        if any(re.search(p, t) for p in pats):
            return canon, rank
    return None, None


def _vote(brands, makes, title):
    """La marque que le plus de makes (+ le titre) désignent ; égalité = ordre de la table.
    « Revv Generator 120 MK III » vote Mesa (MK) ET Revv ; « Revv RV30 » vote Revv : Revv gagne.
    Le premier motif de la table sur tout le blob donnait Mesa (« spécifique avant générique »
    ne vaut que DANS un make, pas entre makes)."""
    score = {}
    for text in list(makes) + [title]:
        canon, rank = _brand_of(brands, text)
        if canon:
            score[canon] = (score.get(canon, (0, rank))[0] + 1, rank)
    if not score:
        return None
    return max(score, key=lambda c: (score[c][0], -score[c][1]))


def detect_brand(makes, title, gear):
    makes = makes or []
    # le baffle de la CHAÎNE ne fait pas la marque : « Mesa Rectifier 4x12 » dans les makes d'un
    # Revv Generator donnait Mesa/Boogie (tone 68986, 2026-09-14). Pour un cab, tout compte.
    if gear != "cab":
        makes = [m for m in makes if not CAB_MAKE.search(m)]
    if gear in ("amp", "amp-cab"):
        makes = [m for m in makes if not PEDAL_MAKE.search(m)]
    blob = " ".join(makes + [title]).lower()
    if gear == "outboard":                     # l'appareil capturé EST le préampli/compresseur
        return _vote(OUTBOARD_BRANDS, makes, title) or "Custom / Other"
    table = PEDAL_BRANDS if gear == "pedal" else AMP_BRANDS
    b = _vote(table, makes, title)
    if not b:                                  # fallback croisé (pédale↔ampli : Fender, Fortin…)
        b = _hit(AMP_BRANDS if gear == "pedal" else PEDAL_BRANDS, blob)
    if b:
        return b
    if gear in ("cab", "experimental"):        # IR/cab sans marque d'ampli identifiable
        return "Cabs / IR"
    return "Custom / Other"

# Packs MULTI-AMPLIS confirmés à la main (l'heuristique ne suffit pas pour les surnoms).
MULTI_PACK_IDS = {1868, 28241, 67139}


def is_pack(makes, title, tid=None):
    """Pack MULTI-amplis uniquement (les packs de captures d'UN ampli gardent leur nom propre) :
    le make le plus long concatène ≥2 autres makes PAIRWISE DISTINCTS (pas une famille
    « Ampeg / Ampeg SVT / Ampeg SVT Classic »), ou id confirmé à la main."""
    if tid is not None and int(tid) in MULTI_PACK_IDS:
        return True
    cands = [m for m in (makes or []) if len(m) > 3]
    if len(cands) >= 3:
        longest = max(cands, key=len)
        inside = [m for m in cands if m != longest and m.lower() in longest.lower()]
        distinct = [m for i, m in enumerate(inside)
                    if not any(m.lower() in o.lower() or o.lower() in m.lower()
                               for o in inside[:i] + inside[i + 1:])]
        # ≥2 mots chacun : écarte les fragments marque/modèle d'UN MÊME ampli (« Badlander » + « Mesa Boogie »)
        distinct = [m for m in distinct if len(m.split()) >= 2]
        if len(distinct) >= 2:
            return True
    return False


def clean_amp_name(makes, title, gear=None, brand=None):
    """Meilleur nom d'ampli : le make non-bruité le plus 'riche', sinon titre nettoyé.
    Un PACK multi-amplis garde son TITRE (le make le plus long serait la concaténation).
    ⚠ `makes` liste toute la CHAÎNE d'enregistrement (micro, HP, loadbox, préampli), pas
    l'appareil capturé : le nom se choisit dans ce qui reste APRÈS le bruit. Pour un gear
    outboard, le préampli est l'appareil, donc PRE_NOISE ne s'applique pas."""
    noisy = _noisy_for(gear)
    cands = [m for m in (makes or []) if not noisy(m) and len(m) > 3
             and not re.fullmatch(r"[\d\s\-]+", m)]
    # écarte les fragments trop courts/génériques quand il y a mieux. D'ABORD le make qui porte
    # la MARQUE détectée (tone 70614 : « Mesa Subway Bass DI-Preamp » perdait contre la pédale
    # « Darkglass Vintage Microtubes », deux caractères plus longue — 2026-09-14), PUIS le plus riche.
    if cands:
        table = OUTBOARD_BRANDS if gear == "outboard" else PEDAL_BRANDS if gear == "pedal" else AMP_BRANDS
        own = (lambda m: _brand_of(table, m)[0] == brand) if brand else (lambda m: False)
        cands.sort(key=lambda m: (own(m), len(m), m.count(" ")), reverse=True)
        return cands[0]
    return clean_title(title)

def clean_title(title):
    n = (title or "").strip()
    n = re.sub(r"\s*[\[(](full ?rig|amp ?head|amp only|fullrig|raw|ir|tutorial|multiload|"
               r"community pack?|free|el34|6l6|hyper accuracy\+?)\b[^\])]*[\])]", "", n, flags=re.I)
    n = re.sub(r"\b(community pack|full pack|gain range pack|sample|pack|multiload)\b", "", n, flags=re.I)
    n = re.sub(r'["“”]', "", n)
    n = re.sub(r"[-–—|]\s*$", "", n).strip()
    return re.sub(r"\s{2,}", " ", n) or title


def main():
    report = "--report" in sys.argv
    d = json.load(open(INDEX))
    tones = d["tones"]
    for t in tones:
        if t.get("parent"):
            continue                                   # entrée dérivée d'un split de pack : figée
        t["brand"] = detect_brand(t.get("makes"), t.get("title", ""), t.get("gear", ""))
        t["pack"] = is_pack(t.get("makes"), t.get("title", ""), t.get("id"))   # multi-amplis -> badge
        t["amp"] = (t.get("title") or "").strip() if t["pack"] else clean_amp_name(t.get("makes"), t.get("title", ""), t.get("gear"), t["brand"])

    by_brand = collections.Counter(t["brand"] for t in tones)
    print("=== marques détectées ===")
    for b, c in by_brand.most_common():
        print(f"  {c:3}  {b}")
    autres = [t for t in tones if t["brand"] == "Autres"]
    print(f"\n  'Autres' (non classés) : {len(autres)}")
    for t in autres:
        print(f"      [{t['gear']}] {t['title'][:45]:<45} makes={t.get('makes')}")

    if report:
        print("\n(--report : rien écrit)")
        return

    # regroupé pour l'app
    groups = {}
    for t in tones:
        groups.setdefault(t["brand"], []).append(
            {"id": t["id"], "amp": t["amp"], "style": t["style"], "gear": t["gear"]})
    brands = {"_comment": "Vue groupée par marque (dérivée de tones-index.json par tools/classify.py).",
              "brands": [{"name": b, "count": len(v), "tones": v}
                         for b, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]}
    json.dump(brands, open(BRANDS_OUT, "w"), ensure_ascii=False, indent=2)
    d["stats"]["by_brand"] = dict(by_brand.most_common())
    json.dump(d, open(INDEX, "w"), ensure_ascii=False, indent=2)
    print(f"\n✓ écrit : brand+amp dans tones-index.json, et {os.path.relpath(BRANDS_OUT, ROOT)} "
          f"({len(groups)} marques)")

if __name__ == "__main__":
    main()
