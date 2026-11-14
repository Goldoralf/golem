# SPDX-License-Identifier: GPL-3.0-or-later
"""Patches — le SON D'UN MUSICIEN, réutilisé entre morceaux (docs/patches.md §15).

**MODÈLE : LA COPIE.** Un patch est une entité AUTONOME. L'assigner à un morceau copie sa
chaîne dans la lane du rôle, et c'est fini : rien ne se propage, jamais. Les deux objets
s'enregistrent chacun de leur côté et ne se parlent plus qu'au moment où quelqu'un le demande.

POURQUOI (2026-08-02) — deux raisons, la seconde suffirait :
  · personne ne fait autrement. Le Quad Cortex référence les captures (lourdes et FIGÉES) mais
    copie les chaînes ; le Kemper met un Rig de Performance dans une zone mémoire dédiée,
    « independently from their parent Rigs », et la propagation y est un BOUTON.
  · la propagation fait la chose la plus déstabilisante qu'un logiciel puisse faire à un
    musicien : modifier un morceau qu'il ne regarde pas.

CE QUI A DISPARU AVEC : `rev`, `snap`, `rev:null`, l'épingle, `backfill_scenes()` (il allait chercher les scènes dans le premier morceau LIÉ),
`refresh()`, `link_lane()`,
`set_pin()`, `pin_preset_file()`, `accept_latest()`, `pull_from_lane()` — et le
rafraîchissement dans l'entonnoir `store.load_preset`, qui était le SEUL endroit du code
capable de modifier un son que personne ne regardait.

PAS DE LIEN DE PROVENANCE non plus, délibérément : la lane est retouchée dans le morceau (c'est
l'usage prévu), donc l'étiquette vieillirait mal. Une vérité qui se périme sur un appareil de
scène est pire que pas de vérité : elle se croit encore juste. Conséquence assumée — le rack ne
PEUT PAS dire « ce patch est utilisé ailleurs ».

La table des scènes vit dans le PRESET ; un patch porte SA tranche (scenes_of), fusionnée par
identifiant au dépôt. Un patch à 4 scènes déposé dans un morceau qui en a 3 perd la quatrième —
et on le DIT.
"""
import glob
import json
import os
import re

from . import config as C

PATCHES_DIR = os.path.join(C.ROOT, "library", "patches")

# clés de chaîne par realm : le payload d'un patch est EXACTEMENT ces clés-là, rien d'autre
# (le realm garde ses clés hors-chaîne : patch, et demain d'autres réglages de lane).
REALM_CHAIN_KEYS = {"guitar": ("pre", "split", "post"), "voice": ("chain",), "keys": ("chain",)}


def _safe_id(s):
    return re.sub(r"[^a-z0-9\-_]", "", str(s or "").lower().replace(" ", "-")) or "patch"


def _path(pid):
    return os.path.join(PATCHES_DIR, f"{_safe_id(pid)}.json")


# ── lecture cachée par mtime (chemin chaud : refresh à chaque load_preset) ──────────────
_cache = {}     # pid -> (mtime, doc)


def get_patch(pid):
    p = _path(pid)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        _cache.pop(pid, None)
        return None
    hit = _cache.get(pid)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        doc = json.load(open(p))
    except Exception:
        return None
    from . import option_renames
    option_renames.apply(doc)                    # étiquettes de choix renommées au catalogue (lu, jamais réécrit ici)
    _cache[pid] = (mt, doc)
    return doc


_DEAD_KEYS = ("rev", "snap")     # vestiges du modèle à révisions (§15.6)


def _write(doc):
    from . import store
    # les champs du modèle abandonné tombent à la première réécriture — pas de migration, pas
    # de fichier réécrit d'autorité : ils s'effacent au fil de l'usage.
    doc = {k: v for k, v in doc.items() if k not in _DEAD_KEYS}
    store._write_json_atomic(_path(doc["id"]), doc, indent=1)
    _cache.pop(doc["id"], None)
    return doc


# ── chaînes : extraire / injecter / comparer ────────────────────────────────────────────
def _lane_v2(preset, realm):
    """La lane v2 visée par `realm` (un id de lane ; les trois noms d'origine SONT des ids), ou None."""
    from . import store
    if not store.is_v2(preset):
        return None
    return next((L for L in preset["lanes"] if isinstance(L, dict) and str(L.get("id")) == str(realm)), None)


def lane_ids(preset):
    from . import store
    if store.is_v2(preset):
        return [str(L.get("id")) for L in preset["lanes"] if isinstance(L, dict) and L.get("id")]
    return list(REALM_CHAIN_KEYS)


SCENE_IDS = "ABCDEFGH"


def normalize_patch(shape, scenes):
    """Le rack est le VALIDATEUR d'un patch reçu (patches.md §17) : ce qu'il accepte doit être
    JOUABLE **et** AFFICHABLE. Deux manques mesurés le 2026-09-11 sur un patch de golem.fm :

      · `split` SANS `mode` — le compilateur en déduisait un merge (il y a un `post`), mais
        l'écran lit `mode === 'merge'` : il dessinait un FAN-OUT et cachait les cinq blocs du
        post. Un patch qui se VOIT autrement qu'il ne SONNE : le pire des deux mondes.
      · `scenes[].id` absent — les cinq onglets s'affichaient VIDES, aucune scène sélectionnable.

    On COMPLÈTE, on ne réécrit pas : un `mode` ou un `id` fourni est respecté. Mutation en place,
    retourne (shape, scenes) pour l'appelant. Fonction PURE côté I/O (testable à froid)."""
    if isinstance(shape, dict):
        sp = shape.get("split")
        if isinstance(sp, dict) and not sp.get("mode"):
            # un post ne peut exister qu'APRÈS une sommation : sa présence dit le merge
            sp["mode"] = "merge" if (shape.get("post") or []) else "fanout"
    for i, sc in enumerate(scenes or []):
        if isinstance(sc, dict) and not sc.get("id"):
            sc["id"] = SCENE_IDS[i] if i < len(SCENE_IDS) else str(i + 1)
    assign_block_ids(shape)          # sans id, un bloc est hors de portée des scènes et du pied
    return shape, scenes


def shape_blocks(shape):
    """Tous les blocs d'une forme de patch — `{pre,split,post}` ou `{chain}` plate. Générateur."""
    if not isinstance(shape, dict):
        return
    for b in shape.get("chain") or []:
        yield b
    for b in shape.get("pre") or []:
        yield b
    for br in ((shape.get("split") or {}).get("branches") or []):
        for b in br.get("blocks") or []:
            yield b
    for b in shape.get("post") or []:
        yield b


def assign_block_ids(shape):
    """Donne un id aux blocs qui n'en ont pas (« <type>-<n> », premier n libre). Rend les ids posés.

    ⚠ Un bloc SANS id est INGÉRABLE, et pas seulement à l'affichage : les scènes le ciblent par id
    (`scene.blocks` / `scene.params`), le pied s'y assigne par id, le Designer l'édite par id — et
    un on/off écrit dessus produirait la clé « undefined ». Vu le 2026-09-11 sur des patches de
    golem.fm dont les scènes AVAIENT l'air d'agir : elles portaient bien `blocks: {…}`, mais les
    blocs de la chaîne n'avaient pas d'id, donc ces clés ne désignaient rien."""
    blocks = list(shape_blocks(shape))
    taken = {b.get("id") for b in blocks if b.get("id")}
    posed = []
    for b in blocks:
        if b.get("id"):
            continue
        base, n = (b.get("type") or "block"), 1
        while f"{base}-{n}" in taken:
            n += 1
        b["id"] = f"{base}-{n}"
        taken.add(b["id"])
        posed.append(b["id"])
    return posed


def orphan_scene_keys(shape, scenes):
    """Clés de `scene.blocks` / `scene.params` qui ne désignent RIEN dans la chaîne — ni un id de
    bloc, ni un type présent (la clé par type reste lue, cf. store._block_on_in_scene).
    Une scène qui semble exécutable et ne l'est pas est pire qu'une scène vide : elle se lit
    comme une promesse. Rend [{scene, key, where}], jamais réparé — l'intention ne se devine pas."""
    ids = {b.get("id") for b in shape_blocks(shape) if b.get("id")}
    types = {b.get("type") for b in shape_blocks(shape) if b.get("type")}
    out = []
    for sc in scenes or []:
        if not isinstance(sc, dict):
            continue
        for where in ("blocks", "params"):
            for k in (sc.get(where) or {}):
                if k not in ids and k not in types:
                    out.append({"scene": sc.get("id"), "key": k, "where": where})
    return out


# Ce que chaque bloc à capture sait porter (miroir de MODEL_GEARS côté app — UNE table, deux
# maisons : cf. docs/archive/preset-schema.md « quatre blocs portent une capture »).
BLOCK_GEARS = {"amp": ("amp-cab",), "amp-nam": ("amp",), "cab": ("cab",), "pedal-nam": ("pedal",),
               "preamp-nam": ("outboard",), "comp-nam": ("outboard",), "ir-fx": ("outboard", "pedal")}
_TOK = re.compile(r"[a-z0-9]+")
# « MK III » / « MKIII » / « Mk-3 » nomment le même ampli — et « Mark IV » aussi (Mesa). Sans
# ça, « Revv Generator 120 MKIII » (le patch) contre « Revv Generator 120 MK III » (le rack)
# scorait 3/4 et le rack possédait la capture sans l'associer (Prism, 2026-09-12).
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8"}
_MK = re.compile(r"\b(mk|mark)[\s-]*(viii|vii|vi|iv|v|iii|ii|i|\d+)\b")


def _tokens(s):
    txt = str(s or "").lower()
    txt = _MK.sub(lambda m: m.group(1) + _ROMAN.get(m.group(2), m.group(2)), txt)
    return {_ROMAN.get(t, t) if t in _ROMAN and len(t) > 1 else t
            for t in _TOK.findall(txt) if len(t) > 1}


def match_capture(label, btype, tones):
    """Une capture POSSÉDÉE qui corresponde au matériel nommé, ou None.

    2026-09-12 : « si les captures existent et qu'on les possède, elles doivent être
    associées automatiquement ». Le cas : le patch « Hammer » nommait un « Roland Jazz
    Chorus-120 » sans `ref` — alors que ce rack possède TROIS captures de JC-120, toutes poussées
    à golem.fm, dont leur appariement par nom n'a retenu aucune. Une branche vide, un son perdu,
    et une capture qui dormait à côté.

    ⚠ Apparier par NOM est exactement ce qui a produit le bug du « Blackstar 412 Pro » (un pack
    amp-cab pris pour un baffle parce que son titre contenait « 412 »). Trois garde-fous, donc :
      · le TYPE d'abord — un bloc ne reçoit que ce qu'il sait charger (BLOCK_GEARS) ;
      · un score FRANC — tous les mots du matériel nommé doivent se retrouver dans le titre, à un
        près, et au moins deux mots en commun (« Roland » seul ne décide de rien) ;
      · l'AMBIGUÏTÉ ne tranche pas — deux candidats à égalité, on ne choisit pas.
    Et jamais en silence : l'appelant le dit dans l'ack. Rend (tone, score) ou (None, raison)."""
    want = BLOCK_GEARS.get(btype)
    if not want:
        return None, "block carries no capture"
    lab = _tokens(label)
    if len(lab) < 2:
        return None, "no usable label"
    best, second = None, 0.0
    for t in tones:
        if t.get("gear") not in want:
            continue
        # deux noms par capture : le TITRE du pack (« Fender Twin Pack ») et le MATÉRIEL classé
        # (`amp` : « Fender Twin Reverb ») — le patch nomme l'un ou l'autre. Le meilleur des deux.
        common = max((lab & _tokens(t.get(k)) for k in ("title", "amp")), key=len)
        score = len(common) / len(lab)
        if len(common) < 2:
            continue
        if best is None or score > best[1]:
            best, second = (t, score), (best[1] if best else 0.0)
        elif score > second:
            second = score
    if best is None:
        return None, f"nothing in the library matches « {label} » for a {btype} block"
    tone, score = best
    if score < 0.8:
        return None, f"closest match « {tone.get('title')} » scores {score:.2f} — too weak to decide"
    if second >= score:
        return None, "two captures match equally well — refusing to choose"
    return tone, score


# Un ampli capturé est une TÊTE (`amp`, → bloc amp-nam) ou un RIG COMPLET (`amp-cab`, → bloc amp) :
# le bloc suit la capture, c'est la doctrine du Designer (« head → amp-nam + cab vide »). Quand
# le patch nomme un « Fender Twin Reverb » sur un bloc `amp` et que la capture possédée est une
# tête, la refuser pour le type laisse une branche muette — golem.fm l'a fait ce soir, en silence.
AMP_FAMILY = {"amp": "amp-nam", "amp-nam": "amp"}


def match_capture_family(label, btype, tones):
    """match_capture, puis — pour un bloc ampli — l'autre forme d'ampli, le bloc étant RETYPÉ
    pour suivre la capture. Rend (tone, score, type_du_bloc) ; (None, raison, btype) sinon."""
    tone, info = match_capture(label, btype, tones)
    if tone is not None or btype not in AMP_FAMILY:
        return tone, info, btype
    other = AMP_FAMILY[btype]
    tone2, info2 = match_capture(label, other, tones)
    if tone2 is not None:
        return tone2, info2, other
    return None, info, btype


def drop_blocks(preset, ids):
    """Retire des blocs (par id) de toutes les lanes d'un preset v2 — pre, branches, post.
    Mutation en place, retourne le preset. Sert à l'audition d'un patch : un bloc à capture VIDE
    fait taire toute sa branche, on le retire pour entendre le reste (cf. tones_jobs._patch_try)."""
    ids = {i for i in (ids or []) if i}
    if not ids:
        return preset
    keep = lambda lst: [b for b in (lst or []) if b.get("id") not in ids]
    for L in preset.get("lanes") or []:
        ch = L.get("chain") or {}
        ch["pre"], ch["post"] = keep(ch.get("pre")), keep(ch.get("post"))
        for br in ((ch.get("split") or {}).get("branches") or []):
            br["blocks"] = keep(br.get("blocks"))
    return preset


def _patch_shape(c):
    """La forme d'un patch depuis une chaîne riche : {pre,split,post} s'il y a un split, sinon
    {chain} plate — un patch de voix ou de clavier reste ce qu'il a toujours été."""
    from . import store
    c = store.rich_chain(c)
    if c["split"]:
        return {"pre": c["pre"], "split": c["split"], "post": c["post"]}
    return {"chain": c["pre"] + c["post"]}


def chain_of(preset, realm):
    """Le payload de chaîne d'une lane (copie par référence — ne pas muter). v2 : la lane par id."""
    L = _lane_v2(preset, realm)
    if L is not None:
        return _patch_shape(L.get("chain"))
    r = preset.get(realm)
    if not isinstance(r, dict):
        return None
    return {k: r.get(k) for k in REALM_CHAIN_KEYS.get(realm, ())}


def _dedupe(chain, patch_scenes, taken, taken_branches=()):
    """Renomme, dans la chaîne ET les scènes d'un patch, les ids de blocs déjà pris ailleurs dans
    le preset (P0 de l'audit 2026-09-08 : le patch voix de Velvetine apportait comp-1/chorus-1/
    delay-1/reverb-1, déjà dans la guitare — la compile refusait, en silence pour l'utilisateur).
    `base-N` avec le premier N libre. Rend (chain, scenes, {ancien: nouveau})."""
    ids, _t, brs = _chain_sets(chain)
    taken = set(taken or ())
    ren = {}
    for old in sorted(ids):
        if old not in taken:
            continue
        base = re.sub(r"-[0-9a-z]+$", "", old) or old
        n = 2
        while f"{base}-{n}" in taken or f"{base}-{n}" in ids or f"{base}-{n}" in ren.values():
            n += 1
        ren[old] = f"{base}-{n}"
    # les ids de BRANCHES aussi : `lane-a`/`lane-b` arrivent tels quels de golem.fm dans chaque patch à
    # split, et le mute par branche d'une scène est cherché à plat (2026-09-14) — `taken_branches` =
    # les ids de branches des AUTRES lanes du preset (store.lane_branch_ids)
    bren = {}
    for old in sorted(brs):
        if old not in taken_branches:
            continue
        base = old                                # `lane-a` reste lisible : `lane-a-2`, pas `lane-2`
        n = 2
        while f"{base}-{n}" in taken_branches or f"{base}-{n}" in brs or f"{base}-{n}" in bren.values():
            n += 1
        bren[old] = f"{base}-{n}"
    if bren:
        for v in (chain or {}).values():
            if isinstance(v, dict):
                for br in v.get("branches") or []:
                    if isinstance(br, dict) and br.get("id") in bren:
                        br["id"] = bren[br["id"]]
    if not ren and not bren:
        return chain, patch_scenes, ren

    def walk(blocks):
        for b in blocks or []:
            if isinstance(b, dict) and b.get("id") in ren:
                b["id"] = ren[b["id"]]
    for v in (chain or {}).values():
        if isinstance(v, list):
            walk(v)
        elif isinstance(v, dict):
            for br in v.get("branches") or []:
                walk(br.get("blocks"))
    scenes = json.loads(json.dumps(patch_scenes)) if patch_scenes is not None else None
    for sc in scenes or []:
        for key in ("blocks", "params"):
            if isinstance(sc.get(key), dict):
                sc[key] = {ren.get(k, k): v for k, v in sc[key].items()}
        if bren:
            if isinstance(sc.get("branches"), dict):
                sc["branches"] = {bren.get(k, k): v for k, v in sc["branches"].items()}
            if isinstance(sc.get("lanes"), dict):          # legacy : le mute vivait sous `lanes`
                from .store import is_legacy_branch_mute
                sc["lanes"] = {(bren.get(k, k) if is_legacy_branch_mute(v) else k): v for k, v in sc["lanes"].items()}
    return chain, scenes, {**ren, **{f"branch:{k}": v for k, v in bren.items()}}


def _taken_outside(preset, realm):
    """Les ids de blocs du preset HORS de la lane visée (elle est remplacée, ses ids sont libres)."""
    from . import store
    return {b.get("id") for b, lane in store.all_blocks(preset)
            if isinstance(b, dict) and b.get("id") and lane != realm}


def _taken_branches_outside(preset, realm):
    """Les ids de branches des AUTRES lanes (le mute par branche d'une scène est cherché à plat)."""
    from . import store
    return {bid for bid, lane in store.lane_branch_ids(preset) if lane != realm}


def _inject(preset, realm, chain, origin=None):
    L = _lane_v2(preset, realm)
    if L is not None:
        from . import store
        L["chain"] = store.rich_chain(chain)
        if origin:
            L["patch_from"] = {"id": origin.get("id"), "name": origin.get("name")}
        else:
            L.pop("patch_from", None)
        return
    r = preset.setdefault(realm, {})
    # la chaîne d'un patch arrive en forme COMPACTE ({chain} sans split) ou étendue : la lane legacy
    # reçoit la SIENNE — {pre, split, post} pour la guitare, {chain} pour la voix et les claviers
    from . import store
    rc = store.rich_chain(chain)
    if REALM_CHAIN_KEYS.get(realm) == ("pre", "split", "post"):
        r.update(pre=rc["pre"], split=rc["split"], post=rc["post"])
    else:
        r["chain"] = rc["pre"] + rc["post"]
    # le lien de provenance a disparu du modèle (§15.3). On ne réécrit pas les presets d'autorité
    # pour l'effacer, mais partout où l'on RÉÉCRIT une lane, on ne laisse pas traîner une
    # étiquette morte : elle ne dit plus rien et le prochain lecteur la croirait vivante.
    r.pop("patch", None)
    # MÉMOIRE d'origine (2026-09-08), pas un lien : {id, name} du patch déposé. Le Designer
    # l'affiche tant que la lane EST encore ce patch (comparaison de chaînes), et dit « edited »
    # sinon — une étiquette vérifiée à chaque rendu ne peut pas mentir.
    if origin:
        r["patch_from"] = {"id": origin.get("id"), "name": origin.get("name")}
    else:
        r.pop("patch_from", None)


def scene_branches_of(e):
    from .store import scene_branches
    return scene_branches(e)


def _chain_sets(chain):
    """Les identités d'une chaîne : ids de blocs, TYPES (clés de scène « sémantique stomp »,
    cf. scene_bake._bake_block), ids de branches du split. C'est ce qui délimite la part de la
    table de scènes qui APPARTIENT au patch (§13)."""
    ids, types, brs = set(), set(), set()

    def walk(blocks):
        for b in blocks or []:
            if b.get("id"):
                ids.add(str(b["id"]))
            if b.get("type"):
                types.add(str(b["type"]))
    for v in (chain or {}).values():
        if isinstance(v, list):
            walk(v)
        elif isinstance(v, dict):
            for br in v.get("branches") or []:
                if br.get("id"):
                    brs.add(str(br["id"]))
                walk(br.get("blocks"))
    return ids, types, brs


# clé de niveau par realm dans scene.levels (observé : levels.guitar / levels.voice)
_LEVEL_KEY = {"guitar": "guitar", "voice": "voice", "keys": "keys"}


def scenes_of(preset, realm):
    """La TRANCHE de la table de scènes qui appartient à la lane (§13) : pour chaque scène du
    morceau, les entrées blocks/params/lanes qui visent les blocs de CETTE chaîne, plus le
    niveau du realm et le drapeau voice — ET le nom de la scène, s'il en a un.

    ⚠ Le nom voyageait PAS (« le nom des scènes reste au morceau ») : vrai pour un patch DÉPOSÉ
    dans un morceau, faux pour un patch qui vit seul — celui que l'IA vient de générer, ou
    qu'on vient de sauver depuis une lane. Ses « Creepy Intro / Main Riff / Bridge Swoosh »
    tombaient à l'enregistrement, et le brouillon rouvrait A/B/C sans nom (six patches sur
    disque le prouvaient, 2026-09-08). Le patch garde donc le nom avec lequel il est né ;
    le MORCEAU, lui, garde les siens : _inject_scenes n'écrit jamais un nom (§13 bis)."""
    chain = chain_of(preset, realm)
    ids, types, brs = _chain_sets(chain)
    out = []
    for sc in preset.get("scenes") or []:
        if not isinstance(sc, dict) or not sc.get("id"):
            continue
        e = {"id": sc["id"]}
        if isinstance(sc.get("name"), str) and sc["name"].strip():
            e["name"] = sc["name"].strip()
        blocks = {k: v for k, v in (sc.get("blocks") or {}).items() if k in ids or k in types}
        params = {k: v for k, v in (sc.get("params") or {}).items() if k in ids}
        if blocks:
            e["blocks"] = blocks
        if params:
            e["params"] = params
        if brs:
            from .store import scene_branches
            branches = {k: v for k, v in scene_branches(sc).items() if k in brs}
            if branches:
                e["branches"] = branches
        if realm == "voice" and "voice" in sc:
            e["voice"] = sc["voice"]
        lk = _LEVEL_KEY.get(realm)
        if lk and isinstance(sc.get("levels"), dict) and lk in sc["levels"]:
            e["levels"] = {lk: sc["levels"][lk]}
        # le niveau PAR LANE (v2, `lanes[<lane>].level` — lu en priorité par scene_bake) voyage
        # comme un scalaire `level`, indépendant de l'id de lane : un patch né sur `guitar-try`
        # se dépose sur `guitar`. Il ne voyageait pas du tout (retour golem.fm, 2026-09-14 : sur
        # Sunfunk, « Fuzzy Lead » avait `lanes.guitar.level: 3` sur le web, plus rien sur le rack).
        from .store import scene_lane_level
        lv = scene_lane_level(sc, realm)
        if lv is None and lk and lk != realm:
            lv = scene_lane_level(sc, lk)
        if lv is not None:
            e["level"] = lv
        if len(e) > 1:
            out.append(e)
    return out or None


MAX_SCENES = 8


def _inject_scenes(preset, realm, patch_scenes, chain):
    """Matérialise les scènes du patch dans la table du MORCEAU (copie inline, §13) : pour
    chaque scène du morceau, on PURGE les entrées visant les blocs du patch puis on applique
    les siennes. Les clés d'anciens blocs disparus restent inertes (le bake ignore les ids inconnus).

    **CORRIGÉ 2026-09-08 (« j'assigne la scène d'un patch, pas le patch »)** : une scène du
    patch que le morceau N'A PAS est désormais CRÉÉE (id, nom, entrées du patch, niveau), dans la
    limite de MAX_SCENES — déposer un patch, c'est déposer le patch ENTIER. Le morceau garde ses
    noms pour les scènes qu'il possède déjà. Rend la liste des ids de scènes créées."""
    # Un patch SANS scènes (extrait avant le §13, ou banc sans réglage de scène) n'a PAS
    # d'opinion : on ne touche à rien. Purger ici effacerait le comportement de scènes que le
    # MORCEAU possède — constaté au banc : un Update depuis un draft d'un vieux patch aurait
    # vidé les scènes guitare du morceau lié. Un patch qui veut « tout en base » exprime des
    # entrées vides explicites, pas une absence.
    if patch_scenes is None:
        return []
    ids, types, brs = _chain_sets(chain)
    by_id = {e.get("id"): e for e in (patch_scenes or [])}
    scenes = preset.setdefault("scenes", [])
    have = {sc.get("id") for sc in scenes if isinstance(sc, dict)}
    created = []
    for e in (patch_scenes or []):
        sid = e.get("id")
        if not sid or sid in have or len(scenes) >= MAX_SCENES:
            continue
        sc = {"id": sid, "blocks": {}, "params": {}, "voice": True}
        if isinstance(e.get("name"), str) and e["name"].strip():
            sc["name"] = e["name"].strip()
        scenes.append(sc); have.add(sid); created.append(sid)
    for sc in preset.get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        pe = by_id.get(sc.get("id")) or {}
        for key, keep in (("blocks", lambda k: k not in ids and k not in types),
                          ("params", lambda k: k not in ids)):
            cur = {k: v for k, v in (sc.get(key) or {}).items() if keep(k)}
            cur.update(pe.get(key) or {})
            if cur:
                sc[key] = cur
            elif key in sc:
                sc[key] = {}
        if brs or scene_branches_of(pe):
            from .store import scene_branches
            cur = {k: v for k, v in scene_branches(sc).items() if k not in brs}
            cur.update(scene_branches(pe))
            # `lanes` a deux vies : les mutes legacy (déplacés dans `branches` ici) et les NIVEAUX
            # par lane d'instrument, qui restent — un `pop("lanes")` effaçait les niveaux de la
            # scène au premier dépôt d'un patch à split (retour golem.fm, 2026-09-14)
            from .store import is_legacy_branch_mute
            # ⚠ n'écarter que les ANCIENS mutes de branche : une lane coupée dans la scène (`mute` + `state`)
            # est une entrée de lane — l'écarter effaçait la coupure et le pointeur d'état d'une AUTRE lane
            keep = {k: v for k, v in (sc.get("lanes") or {}).items() if not is_legacy_branch_mute(v)}
            if keep:
                sc["lanes"] = keep
            else:
                sc.pop("lanes", None)
            sc["branches"] = cur
        if realm == "voice" and "voice" in pe:
            sc["voice"] = pe["voice"]
        if "levels" in pe:
            sc.setdefault("levels", {}).update(pe["levels"])
        if "level" in pe and pe["level"] is not None:
            # le niveau du patch se range sous la lane VISÉE (v2, priorité au bake) et, pour les
            # trois lanes historiques, sous le legacy `levels` aussi — les deux lecteurs sont servis
            sc.setdefault("lanes", {}).setdefault(realm, {})["level"] = pe["level"]
            lk = _LEVEL_KEY.get(realm)
            if lk:
                sc.setdefault("levels", {})[lk] = pe["level"]
    _inject_states(preset, realm, patch_scenes)
    return created


def _inject_states(preset, realm, patch_scenes):
    """LES NOMS VOYAGENT (docs/band-scenes.md §3, lot 1) : les scènes du patch deviennent les ÉTATS
    de la lane visée, avec leur nom (« Pick », « Fuzz »), et chaque scène du morceau qui porte le
    même id POINTE l'état. Explicites (pas `implicit`) : ils survivent à la suppression d'une scène.
    Le contenu est recopié depuis la table plate au prochain `ensure_lane_states` (lot 1 : la table
    plate reste la vérité) — ici on ne pose que l'identité. Lane legacy (hors v2) : rien."""
    from . import store
    L = _lane_v2(preset, realm)
    if L is None:
        return
    states = []
    for pe in (patch_scenes or []):
        if not isinstance(pe, dict) or not pe.get("id"):
            continue
        nm = pe.get("name") if isinstance(pe.get("name"), str) and pe["name"].strip() else str(pe["id"])
        states.append({"id": store.state_id_for(realm, pe["id"]), "name": nm.strip(),
                       "blocks": dict(pe.get("blocks") or {}), "params": dict(pe.get("params") or {}),
                       "branches": dict(scene_branches_of(pe))})
    L["states"] = states                       # la lane est REMPLACÉE par le dépôt : ses états aussi
    have = {st["id"] for st in states}
    for sc in preset.get("scenes") or []:
        if not isinstance(sc, dict) or not sc.get("id"):
            continue
        sid = store.state_id_for(realm, sc["id"])
        sc.setdefault("branches", {})
        ent = sc.setdefault("lanes", {}).setdefault(realm, {})
        if sid in have:
            ent["state"] = sid
        else:
            ent.pop("state", None)             # une scène du morceau que le patch n'a pas : état implicite au prochain passage


def _sig(chain, scenes=None):
    """Signature canonique chaîne + scènes — le pull détecte aussi un changement de scène seule."""
    return json.dumps({"c": chain, "s": scenes or None}, sort_keys=True, ensure_ascii=False)


def _has_blocks(chain):
    if not chain:
        return False
    for v in chain.values():
        if isinstance(v, list) and v:
            return True
        if isinstance(v, dict) and any(br.get("blocks") for br in (v.get("branches") or [])):
            return True
    return False


def needs_of(chain):
    """Les dépendances d'une chaîne (captures NAM/IR référencées) — ce que golem.fm doit
    vérifier avant d'installer le patch ailleurs (contrat §5)."""
    out, seen = [], set()

    def walk(blocks):
        for b in blocks or []:
            ref = b.get("ref")
            if ref is not None:
                key = (b.get("type"), str(ref), str(b.get("model")))
                if key not in seen:
                    seen.add(key)
                    out.append({"type": b.get("type"), "ref": ref, "model": b.get("model")})
    for v in (chain or {}).values():
        if isinstance(v, list):
            walk(v)
        elif isinstance(v, dict):
            for br in v.get("branches") or []:
                walk(br.get("blocks"))
    return out


# ── le rôle d'une lane : realm guitar → rôle de l'IN 1 de l'input map (guitar|bass) ─────
REALM_OF_ROLE = {"voice": "voice", "keys": "keys", "keys-pads": "keys", "pads": "keys"}
# tout le reste (guitar, bass, line) vit dans le royaume guitare — un preset n'a qu'UNE lane
# par royaume, les splits vivent DEDANS : le rôle désigne donc la lane sans ambiguïté (§15.4).


def role_of_lane(preset, realm):
    """Le rôle d'une lane : v2 = la lane le porte ; legacy = le rôle de l'entrée patchée (role_of_realm)."""
    L = _lane_v2(preset, realm)
    if L is not None:
        return str(L.get("role") or "guitar")
    return role_of_realm(realm)


def role_of_realm(realm):
    if realm in ("voice", "keys"):
        return realm
    try:
        from . import inputmap
        e = next((i for i in (inputmap.current().get("inputs") or [])
                  if str(i.get("ch")) in ("1", "1-2")), None)
        r = (e or {}).get("role")
        return r if r in ("guitar", "bass") else "guitar"
    except Exception:
        return "guitar"


# ── CRUD ────────────────────────────────────────────────────────────────────────────────
def list_patches():
    """Tous les patches du catalogue.

    ⚠ PLUS DE COMPTE D'USAGE (§15.3). Il se calculait en scannant les liens `realm.patch` des
    presets — liens qui n'existent plus. Et il aurait menti de toute façon : la lane est
    retouchée dans le morceau, donc « utilisé dans 5 morceaux » devenait faux dès la première
    retouche. La question a changé de forme : on ne demande plus quels morceaux utilisent ce
    patch, on choisit dans quels morceaux le déposer.
    """
    from .preset_view import features
    out = []
    for path in sorted(glob.glob(os.path.join(PATCHES_DIR, "*.json"))):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        if isinstance(d, dict):
            d["features"] = features(d, capture=True)    # le filtre « With » du sélecteur (calculé, jamais écrit)
        out.append(d)
    return out


def create_from_lane(preset, realm, name=None, person=None, tags=None, pid=None, origin=None):
    """La naissance d'un patch : DEPUIS une lane (jamais une page blanche).

    ⚠ NE LIE PLUS RIEN (§15) : le patch part vivre sa vie, le morceau garde la sienne. C'est
    aussi le geste « ce son que je viens de trouver en jouant, mets-le au catalogue » —
    l'*Export Rig to Pool* du Kemper — et il crée TOUJOURS une entrée neuve…

    …SAUF quand le patch a déjà une identité (`pid`, 2026-09-12). Un patch essayé depuis
    golem.fm arrive avec son `patch_id` : le sauver sous un id dérivé du NOM fabriquait
    `paper-kite`, `paper-kite-ii`, `paper-kite-iii` — trois objets pour un patch et deux
    reprises, et plus aucun moyen de savoir qu'ils sont parents (docs/archive/patch-sync-avis.md §1).
    Même règle que `patch-install` : on remplace si le patch local porte la même origine et le
    même id ; sinon suffixe, parce qu'un patch de l'utilisateur ne s'écrase pas.
    """
    chain = chain_of(preset, realm)
    if not _has_blocks(chain):
        raise ValueError(f"lane '{realm}' has no blocks")
    role = role_of_lane(preset, realm)
    name = (name or "").strip() or f"{preset.get('name') or preset.get('id')} · {realm}"
    base = _safe_id(pid) if pid else _safe_id(f"{person + '-' if person else ''}{name}")
    pid, n = base, 2
    cur = get_patch(pid) if origin else None
    if not (cur is not None and cur.get("origin") == origin):     # pas le même patch revenu : on n'écrase pas
        while os.path.exists(_path(pid)):
            pid, n = f"{base}-{n}", n + 1
    # premier tag SEMÉ par le style du preset d'origine (le brief de l'IA le connaît) — on complète après
    seed = [preset.get("style")] if isinstance(preset.get("style"), str) and preset.get("style").strip() else []
    doc = {"id": pid, "name": name, "person": person or None, "role": role,
           "tags": norm_tags(seed + (tags if isinstance(tags, list) else []))}
    # v2 (docs/patches.md) : depuis un BANC de patch, tout le banc et son ⚙ ; depuis la lane d'un
    # MORCEAU (« Save lane as patch »), la lane seule et PAS de config — on ne devine pas le looper de quelqu'un (§5)
    doc.update(v2_fields(preset, patch_lanes_of(preset, realm), old=get_patch(pid) if origin else None,
                         with_config=bool(preset.get("__patch"))))
    doc["role"] = role
    if origin:
        doc["origin"] = origin
    return _write(doc)


def save_patch(pid, preset, realm):
    """Cible de la SAUVEGARDE AUTOMATIQUE du mode patch : la lane du banc devient le patch.

    Aucun morceau n'en est affecté — c'est tout l'intérêt du modèle copie. On écrit donc aussi
    tranquillement qu'on enregistre un preset, sans compteur ni confirmation.
    """
    doc = get_patch(pid)
    if doc is None:
        raise ValueError(f"unknown patch: {pid}")
    chain = chain_of(preset, realm)
    if not _has_blocks(chain):
        raise ValueError(f"lane '{realm}' has no blocks")
    # ÉCRIT EN v2 (docs/patches.md §3) : le banc entier du patch — ses lanes, ses scènes, son ⚙ —
    # avec les clés miroir que lisent golem.fm et les racks d'avant. Un patch v1 passe en v2 ICI, à sa
    # première sauvegarde sur le rack, jamais par une migration.
    fields = v2_fields(preset, patch_lanes_of(preset, realm), old=doc, with_config=bool(preset.get("__patch")))
    new = dict(doc, **fields)
    if not fields.get("chain"):
        new.pop("chain", None)
    if doc.get("lanes_v") == 2 and _v2_sig(new) == _v2_sig(doc):
        return doc                       # rien n'a bougé : pas de réécriture inutile
    return _write(new)


def save_kit_patch(pid, preset, drumset, name=None, person=None):
    """Le GROUPE de batterie d'un preset -> un patch de kit (docs/drums-kit.md §6.7).

    Le pendant de « Save this lane as patch », pour un instrument qui occupe N entrées. C'est une
    CRÉATION comme les autres : rien n'est lié après, le patch est une copie (patches.md §15).
    `needs` est l'union de ce que réclament les chaînes — un kit peut porter des captures.
    """
    els = kit_elements(preset, drumset)
    if not els:
        raise ValueError("this preset has no drum kit group to save")
    needs, seen = [], set()
    for e in els:
        for n in needs_of(e["chain"]):
            k = json.dumps(n, sort_keys=True)
            if k not in seen:
                seen.add(k)
                needs.append(n)
    doc = get_patch(pid) or {"id": _safe_id(pid), "tags": []}
    # rien n'a bougé : pas de réécriture inutile (l'auto-save frappe à chaque touche, comme pour
    # un patch ordinaire — `save_patch` a la même garde depuis toujours)
    if doc.get("elements") == els and doc.get("lanes_v") == 2 and not name and person is None:
        return doc
    doc = dict(doc, id=_safe_id(pid), role="drums", elements=els, needs=needs)
    # v2 : les lanes du groupe (le MIROIR `elements` reste pour les lecteurs d'avant — pas de `chain`)
    from . import store
    kit_ids = [L["id"] for L in store.lanes_of(preset) if L.get("drumset") == drumset and L.get("element")]
    v2 = v2_fields(preset, kit_ids, old=doc, with_config=bool(preset.get("__patch")))
    v2.pop("chain", None)
    v2["needs"] = needs
    doc.update(v2)
    # un patch de kit n'a PAS de `chain` : la porter à vide ferait croire à un patch mono-lane
    # aux lecteurs qui ne connaissent pas `elements` — mieux vaut l'absence, qui se remarque.
    doc.pop("chain", None)
    doc.pop("scenes", None)
    if name:
        doc["name"] = name
    if person is not None:
        doc["person"] = person
    doc.setdefault("name", doc["id"])
    return _write(doc)


def deposit(pid, preset_ids):
    """LE DÉPÔT : copie la chaîne du patch dans la lane de chaque morceau visé.

    ⚠ DESTRUCTIF, et c'est le seul geste du modèle qui le soit : la lane visée est REMPLACÉE.
    L'appelant doit l'avoir dit à l'utilisateur AVANT (docs/patches.md §15.4) — ici on exécute.

    Renvoie, par morceau, ce qui a été remplacé et les scènes PERDUES : un patch à 4 scènes
    déposé dans un morceau qui n'en a que 3 perd la quatrième, et ça ne doit jamais être muet.
    """
    from . import store
    from .config import PRESETS_DIR
    from .store import _write_json_atomic, _safe_id
    doc = get_patch(pid)
    if doc is None:
        raise ValueError(f"unknown patch: {pid}")
    realm = None                      # par morceau : la lane de SON rôle (_target_lane), plus un id `guitar` supposé
    out = []
    for sid in (preset_ids or []):
        p = store.load_preset(sid)
        if not p:
            out.append({"preset": sid, "error": "introuvable"})
            continue
        realm = _target_lane(p, doc, None)
        had = len(_chain_sets(chain_of(p, realm) or {})[0])
        pc, ps = deposit_payload(doc)
        chain, scenes, ren = _dedupe(pc, ps, _taken_outside(p, realm), _taken_branches_outside(p, realm))
        _inject(p, realm, chain, origin=doc)
        added = _inject_scenes(p, realm, scenes, chain)
        have = {sc.get("id") for sc in (p.get("scenes") or [])}
        lost = [sc.get("id") for sc in (doc.get("scenes") or []) if sc.get("id") not in have]   # plafond atteint seulement
        _write_json_atomic(os.path.join(PRESETS_DIR, f"{_safe_id(sid)}.json"), p)
        out.append({"preset": sid, "lane": realm, "replaced_blocks": had,
                    **({"renamed": ren} if ren else {}),
                    **({"added_scenes": added} if added else {}),
                    **({"lost_scenes": lost} if lost else {})})
    return {"patch": pid, "lane": realm, "presets": out}


# ── LE PATCH BATTERIE PORTE LE KIT ENTIER (docs/drums-kit.md §6.7) ──────────────────────
# 2026-09-20 : « sans créer N patchs de batterie ». Un patch porte `role` et UNE chaîne ;
# un kit multi-micro demandait donc sept patchs posés un par un — alors que le kit d'un batteur
# est UN son, pas sept sons voisins. Un patch de rôle `drums` peut donc porter `elements`.
#
# ⚠ LES AUTRES RÔLES NE BOUGENT PAS D'UN OCTET : `elements` absent, `chain` fait foi, et tout le
# code d'avant passe par le même chemin. C'est la condition pour que ce lot ne casse rien.
def is_kit_patch(doc):
    """Un patch qui porte plusieurs éléments — pas un patch de batterie mono-lane."""
    els = (doc or {}).get("elements")
    return isinstance(els, list) and len(els) > 0


def kit_elements(preset, drumset):
    """Les lanes d'un GROUPE de batterie -> `elements[]`, prêtes à écrire dans un patch.

    L'ordre est celui des lanes du preset (donc celui de l'écran) : un patch se relit, et une
    liste dans le désordre se relit mal. Une lane sans chaîne n'est PAS sautée — un élément
    branché sans traitement fait partie du kit, et son absence du patch le ferait disparaître
    au chargement suivant."""
    from . import store
    out = []
    for L in store.lanes_of(preset):
        if not drumset or L.get("drumset") != drumset:
            continue
        el = L.get("element")
        if not el:
            continue
        out.append({"element": el, "chain": chain_of(preset, L["id"]), "scenes": scenes_of(preset, L["id"])})
    return out


def apply_elements(preset, doc, lanes_by_element):
    """Pose chaque élément du patch sur la lane du groupe qui porte le MÊME élément.

    Rend (preset mutée, lanes touchées, éléments SAUTÉS). Un élément sans lane correspondante est
    sauté et NOMMÉ : le batteur a câblé six sorties sur sept, il doit le lire, pas le deviner.
    C'est la même règle que les scènes perdues au dépôt — rien ne disparaît en silence."""
    p = json.loads(json.dumps(preset))
    touched, skipped = [], []
    for el in (doc.get("elements") or []):
        name = el.get("element")
        realm = lanes_by_element.get(name)
        if not realm:
            skipped.append(name)
            continue
        chain, scenes, _ren = _dedupe(json.loads(json.dumps(el.get("chain") or {})), el.get("scenes"),
                                      _taken_outside(p, realm), _taken_branches_outside(p, realm))
        _inject(p, realm, chain, origin=doc)
        _inject_scenes(p, realm, scenes, chain)
        touched.append(realm)
    return p, touched, skipped


def apply_to(preset, pid, lane=None):
    """LE DÉPÔT DEPUIS LE DESIGNER (2026-09-08) : même geste que `deposit`, mais PUR — le
    brouillon est celui du Designer, c'est lui qui enregistre. La lane visée est REMPLACÉE, comme
    au dépôt. `lane` (lot 3) : l'id de la lane visée — avec N lanes, le rôle ne désigne plus une
    lane ; sans lui, la première lane de ce rôle.

    Rend `(preset mutée, realm, scènes perdues, scènes ajoutées, éléments sautés)`.
    ⚠ Les ÉLÉMENTS SAUTÉS ont leur propre place et ne voyagent JAMAIS dans « scènes perdues » :
    un ride non câblé n'est pas une scène, et l'écran aurait écrit « 1 scene lost » pour ça."""
    doc = get_patch(pid)
    if doc is None:
        raise ValueError(f"unknown patch: {pid}")
    from . import store
    # KIT ENTIER (§6.7) : un patch à `elements` vise un GROUPE, pas une lane. On cherche le
    # groupe de la lane visée, sinon le premier groupe du preset. Aucun groupe = refus DIT :
    # poser sept chaînes sur une lane unique ne veut rien dire, et le silence serait pire.
    if is_kit_patch(doc):
        lanes = store.lanes_of(preset)
        ds = next((L.get("drumset") for L in lanes if L["id"] == lane and L.get("drumset")), None) \
            or next((L.get("drumset") for L in lanes if L.get("drumset")), None)
        if not ds:
            # PAS DE GROUPE : le kit arrive EN ENTIER (docs/patches.md §9 bis, garantie 10) — une lane
            # par élément, chacune sur l'entrée LIBRE suivante de la carte, dans l'ordre du kit ; les lanes en
            # trop attendent leur carte (⏳), jamais deux éléments sur la même entrée
            preset, ds = add_kit_lanes(preset, doc)
            lanes = store.lanes_of(preset)
        by_el = {L.get("element"): L["id"] for L in lanes if L.get("drumset") == ds and L.get("element")}
        p, touched, skipped = apply_elements(preset, doc, by_el)
        return p, (touched[0] if touched else ds), [], [], skipped
    realm = _target_lane(preset, doc, lane)
    p = json.loads(json.dumps(preset))
    pc, ps = deposit_payload(doc)
    chain, scenes, _ren = _dedupe(pc, ps, _taken_outside(p, realm), _taken_branches_outside(p, realm))
    _inject(p, realm, chain, origin=doc)
    added = _inject_scenes(p, realm, scenes, chain)
    have = {sc.get("id") for sc in (p.get("scenes") or [])}
    lost = [sc.get("id") for sc in (doc.get("scenes") or []) if sc.get("id") not in have]
    return p, realm, lost, added, []


def norm_tags(v):
    """Tags d'un patch — même grammaire que les presets (chaînes libres, dédoublonnées, ordre
    conservé, 40 tags max). Une valeur non-liste = pas de tags."""
    out = []
    for t in (v if isinstance(v, list) else []):
        t = str(t or "").strip()[:40]
        if t and t not in out:
            out.append(t)
    return out[:40]


def update_meta(pid, name=None, person=None, tags=None):
    doc = get_patch(pid)
    if doc is None:
        raise ValueError(f"unknown patch: {pid}")
    if name is not None:
        doc["name"] = str(name).strip() or doc["name"]
    if person is not None:
        doc["person"] = person or None
    if tags is not None:                              # 2026-09-08 : un patch se tague comme un preset
        doc["tags"] = norm_tags(tags)
    return _write(dict(doc))


def delete_patch(pid):
    """Supprime le FICHIER. Les lanes liées deviennent orphelines et JOUENT toujours
    (leur copie inline) — §9.3 : on n'emporte pas les sons de la salle."""
    p = _path(pid)
    if os.path.exists(p):
        os.remove(p)
        _cache.pop(pid, None)
        # une bank de sons qui le jouait libère sa ligne (le titre reste : on lit ce qu'il y avait)
        try:
            from . import setlists
            setlists.forget_patch(pid)
        except Exception:
            pass
        return True
    return False


# ── UN PATCH EST UN PRESET — À UN MUSICIEN (docs/patches.md) ──────────────────────────────
# Le rack joue un patch comme un preset : `store.load_preset("patch:<id>")` sert le document ci-dessous.
# Trois formes se lisent — LUES, jamais déduites de `kind`/`patch_v` (guarantie 2 du §9 bis) :
#   v2  : `lanes_v == 2` et `lanes[]`  -> les lanes telles quelles ;
#   kit : `elements[]` (v1 batterie)  -> une lane par élément, groupe de batterie compris ;
#   v1  : `chain` + `scenes`          -> une lane du rôle.
# Pour v1 et kit, on ne réécrit pas un lecteur : on DÉPOSE le patch dans un preset vide, par le chemin
# du dépôt (dédoublonnage, injection, scènes, états) — celui que les tests couvrent déjà.
PATCH_PREFIX = "patch:"


def is_v2(doc):
    return isinstance(doc, dict) and doc.get("lanes_v") == 2 and isinstance(doc.get("lanes"), list) and bool(doc["lanes"])


def _has_drumkit(lane):
    c = (lane or {}).get("chain") or {}
    blocks = list(c.get("chain") or []) + list(c.get("pre") or []) + list(c.get("post") or [])
    for br in ((c.get("split") or {}).get("branches") or []):
        blocks += list(br.get("blocks") or [])
    return any(isinstance(b, dict) and b.get("type") == "drumkit" for b in blocks)


def bind_input(lane, role, imap, nth=1):
    """Lie une lane de patch à la PREMIÈRE entrée de son rôle sur la carte du moment (input-map.md §2) —
    un patch est portable, il ne connaît que son rôle. Batterie : un module lié en USB d'abord (MIDI),
    sinon l'entrée audio Drums. Lève ValueError, avec quoi faire, si la carte n'a pas d'entrée de ce rôle.
    Même règle que l'essai d'un patch venu de golem.fm (tones_jobs._trial_preset)."""
    from .tones_jobs import MIDI_ROLES
    midi = role in MIDI_ROLES
    if role == "drums":
        port = next((u for u in (imap.get("usb") or []) if u.get("bound") and u.get("role") == "drums"), None)
        if port:
            midi = True
            lane.update(midi=True, in_sel=str(port["ch"]))
    if midi:
        lane["midi"] = True
        lane.setdefault("in_sel", "usb1")
        return lane
    ins = [e for e in (imap.get("inputs") or []) if e.get("role") == role]
    # la k-ième lane de ce rôle prend l'entrée « Rôle k » ; sans numéro sur la carte, la première sert la première
    e = next((x for x in ins if int(x.get("nth") or 0) == int(nth)), ins[0] if (ins and int(nth) == 1) else None)
    if e is None and role == "drums" and (lane.get("midi") or _has_drumkit(lane)):
        # NI MODULE USB NI ENTRÉE AUDIO « DRUMS » (2026-10-13) : un bloc Drum Kit ne joue qu'en MIDI (sur une lane
        # audio, la compile le retire). Plutôt qu'un refus, la lane ATTEND sur « usb » — le port qui portera le rôle
        # drums, et l'écran le dit (« USB · auto (by role) »). Une entrée audio Drums, elle, garde la priorité : sur
        # une XR18 le module fait le son et la lane prend son entrée (test_drums_patch).
        lane.update(midi=True, in_sel="usb")
        return lane
    if e is None:
        card = str(imap.get("card") or "this card").replace("hw:", "")
        if int(nth) > 1:
            raise ValueError(f"no {role} input #{nth} on « {card} » — number a second {role} input in Modes ▸ Inputs of « {card} »")
        if role == "drums":
            raise ValueError(f"no drums input on « {card} » — bind a drum module on a USB port, or assign a Drums input in Modes ▸ Inputs of « {card} »")
        raise ValueError(f"no {role} input on « {card} » — assign one in Modes ▸ Inputs of « {card} »")
    lane.update(in_sel=str(e["ch"]), in_role=role, in_nth=int(e.get("nth") or 1), in_name=e.get("name"))
    return lane


def as_preset(doc, imap=None):
    """Le patch `doc` sous la forme d'un preset jouable, id `patch:<id>`. None si le document est vide.
    Le marqueur `__patch` fait que le Designer l'ouvre en mode patch."""
    from . import store
    if not isinstance(doc, dict) or not doc.get("id"):
        return None
    pid, role = str(doc["id"]), str(doc.get("role") or "guitar")
    name = str(doc.get("name") or pid)
    if imap is None:
        from . import inputmap
        from .state import state
        imap = state.inputmap or inputmap.current() or {}
    marker = {"id": pid, "name": name, "role": role}
    if is_v2(doc):
        lanes = json.loads(json.dumps(doc["lanes"]))
        for L in lanes:
            L["chain"] = store.rich_chain(L.get("chain"))
        p = {"lanes": lanes, "scenes": json.loads(json.dumps(doc.get("scenes") or []))}
        if lanes[0].get("drumset"):
            marker["drumset"] = lanes[0]["drumset"]
    elif is_kit_patch(doc):
        lanes = [{"id": f"drums-{i + 1}", "key": f"drums-{i + 1}", "role": "drums", "name": el.get("element") or f"Drums {i + 1}",
                  "in_sel": str(i + 1), "out_sel": "1-2", "chain": store.rich_chain(None),
                  "drumset": pid, "drumset_module": doc.get("drumset_module") or pid, "element": el.get("element")}
                 for i, el in enumerate(doc.get("elements") or [])]
        p, _t, _s = apply_elements({"lanes_v": 2, "lanes": lanes, "scenes": []}, doc,
                                   {L["element"]: L["id"] for L in lanes if L.get("element")})
        marker["drumset"] = pid
    else:
        lid = f"{role}-1"
        lane = {"id": lid, "key": lid, "role": role, "name": name, "out_sel": "1-2", "chain": store.rich_chain(None)}
        p = {"lanes_v": 2, "lanes": [lane], "scenes": []}
        chain, scenes, _ren = _dedupe(json.loads(json.dumps(doc.get("chain") or {})), doc.get("scenes"), set(), set())
        _inject(p, lid, chain, origin=doc)
        _inject_scenes(p, lid, scenes, chain)
    # les lanes non batterie-groupe se lient à l'entrée de leur rôle ; un kit garde ses entrées nominales
    seen = {}                                        # k-ième lane d'un rôle -> « Rôle k » (audit 2026-10-10)
    for L in p["lanes"]:
        if not L.get("drumset"):
            r = L.get("role") or role
            seen[r] = seen.get(r, 0) + 1
            try:
                bind_input(L, r, imap, nth=seen[r])
            except ValueError as e:
                L.update(in_sel="NONE", bind_error=str(e))      # la lane attend une entrée — dit, pas deviné
    if not p.get("scenes"):
        p["scenes"] = [{"id": "A", "name": "A", "blocks": {}, "params": {}}]
    marker["realm"] = p["lanes"][0]["id"]
    out = {"id": PATCH_PREFIX + pid, "kind": "patch", "name": name, "lanes_v": 2, "lanes": p["lanes"],
           "scenes": p["scenes"], "bpm": doc.get("bpm") or 120, "config": json.loads(json.dumps(doc.get("config") or {})),
           "__patch": marker}
    for k in ("exp", "colors", "anims", "origin", "backing"):
        if doc.get(k) is not None:
            out[k] = json.loads(json.dumps(doc[k]))
    for k in doc:                                    # exp2, exp3… (les pédales d'expression numérotées)
        if _EXP_KEY.match(k) and k not in out:
            out[k] = json.loads(json.dumps(doc[k]))
    return out


# ── L'ÉCRITURE v2 (docs/patches.md §3 et §9 bis) ──────────────────────────────────────────
# Ce que le ⚙ d'un patch peut porter (§4) : de quoi jouer SEUL — l'ACCOMPAGNEMENT (looper, grooves, grille
# Standard, samples, et la backing depuis le 2026-09-30 : « en tant que guitariste j'ai envie de jouer sur mes
# chansons préférées », le mainteneur). Jamais l'arrangement — la FORME du morceau, qui change de scène tout seul —, jamais
# le Rec/Click/Compo (globaux, re-hydratés au chargement).
PATCH_GEN_TYPES = ("looper", "sample", "drums", "standard", "backing-track")
# la backing se choisit dans le bloc mais vit dans `backing` au niveau du document (backing.py la lit là)
_PATCH_DOC_KEYS = ("colors", "anims", "backing")
_LANE_KEEP = ("id", "role", "name", "states", "midi", "stereo", "drumset", "drumset_module", "element")
_EXP_KEY = re.compile(r"^exp\d*$")


def _lane_doc(L):
    """Une lane de preset -> une lane de patch : ce qui décrit le SON, jamais le branchement du moment
    (entrée, sortie, montage) — un patch est portable. La chaîne est dans la forme du miroir `chain`,
    pour que `chain == lanes[0].chain` soit vrai À L'OCTET (garantie 1, golem.fm compare)."""
    d = {k: json.loads(json.dumps(L[k])) for k in _LANE_KEEP if L.get(k) is not None}
    d["chain"] = _patch_shape(L.get("chain"))
    if L.get("drumset"):
        d["in_sel"] = L.get("in_sel")                # un kit garde ses entrées NOMINALES (drums-kit.md §6.7)
    return d


def _block_sets(lanes):
    ids, types, brs = set(), set(), set()
    for L in lanes:
        i, t, b = _chain_sets(L["chain"])
        ids |= i; types |= t; brs |= b
    return ids, types, brs


def v2_fields(preset, lane_ids, old=None, with_config=True):
    """Les champs v2 d'un patch fait des lanes `lane_ids` du brouillon `preset`. `old` = le patch d'avant
    (les champs descriptifs de ses scènes — what, gain, out — viennent de golem.fm et se gardent)."""
    from . import store
    lanes = [_lane_doc(L) for L in store.lanes_of(preset) if L["id"] in lane_ids]
    if not lanes:
        raise ValueError("no lane to save as a patch")
    roles = {L.get("role") for L in lanes}
    if len(roles) != 1:                              # garantie 3 : un musicien, un instrument
        raise ValueError("a patch holds one instrument — these lanes have " + ", ".join(sorted(r or "?" for r in roles)))
    ids, types, brs = _block_sets(lanes)
    lids = {L["id"] for L in lanes}
    lkeys = {L["id"]: L.get("level_key") or L["id"] for L in store.lanes_of(preset) if L["id"] in lane_ids}
    olds = {s.get("id"): s for s in ((old or {}).get("scenes") or []) if isinstance(s, dict)}
    scenes = []
    for sc in preset.get("scenes") or []:
        s = {"id": sc.get("id")}
        if str(sc.get("name") or "").strip():               # un nom fait d'espaces n'est pas un nom (scenes_of)
            s["name"] = str(sc["name"]).strip()
        bl = {k: v for k, v in (sc.get("blocks") or {}).items() if k in ids or k in types}
        pa = {k: v for k, v in (sc.get("params") or {}).items() if k in ids}
        br = {k: v for k, v in (sc.get("branches") or {}).items() if k in brs}
        ln = {k: v for k, v in (sc.get("lanes") or {}).items() if k in lids}
        # LE NIVEAU LEGACY N'EST PAS UN NIVEAU PERDU (2026-10-11, Paper Kite basse : +2 dB sur Chorus effacé à
        # l'ouverture). Un patch v1 rouvert dans le Designer porte son niveau sous `levels[<level_key>]` — le moteur
        # le joue, mais seul `lanes[<id>].level` était relu ici : l'auto-save l'effaçait. Il passe dans la lane.
        for lid, lk in lkeys.items():
            lv = (sc.get("levels") or {}).get(lk) if isinstance(sc.get("levels"), dict) else None
            if lv is not None and (ln.get(lid) or {}).get("level") is None:
                ln[lid] = {**(ln.get(lid) or {}), "level": lv}
        for k, v in (("blocks", bl), ("params", pa), ("branches", br), ("lanes", ln)):
            if v:
                s[k] = json.loads(json.dumps(v))
        if len(lanes) == 1 and (ln.get(lanes[0]["id"]) or {}).get("level") is not None:
            s["level"] = ln[lanes[0]["id"]]["level"]   # lecteurs v1 : le niveau de LA lane
        for k in ("what", "gain", "out"):
            if (olds.get(s["id"]) or {}).get(k) is not None:
                s[k] = olds[s["id"]][k]
        scenes.append(s)
    out = {"kind": "patch", "patch_v": 2, "lanes_v": 2, "role": lanes[0]["role"], "lanes": lanes, "scenes": scenes}
    if with_config:
        gen = ((preset.get("config") or {}).get("gen") or {})
        blocks = [json.loads(json.dumps(b)) for b in (gen.get("blocks") or []) if (b or {}).get("type") in PATCH_GEN_TYPES]
        out["config"] = {"gen": {"blocks": blocks, "out": gen.get("out") or "1-2"}} if blocks else {}
        # REC et RIFF AU PIED (2026-10-14 : tutos dans les banks de patches) : ces blocs sont des singletons globaux
        # (config.rec, réglages dans config/recorder.json et compo.json) — un patch ne garde que LEUR SWITCH. Sans ça,
        # enregistrer le patch depuis le Designer effaçait le switch REC/RIFF qu'on venait de lui donner.
        rec = [{"id": b["id"], "type": b["type"], "foot": b["foot"]}
               for b in (((preset.get("config") or {}).get("rec") or {}).get("blocks") or [])
               if (b or {}).get("type") in ("rec", "compo") and isinstance(b.get("foot"), int) and b.get("id")]
        if rec:
            out["config"]["rec"] = {"blocks": rec}
        for k, v in preset.items():
            if _EXP_KEY.match(k) or k in _PATCH_DOC_KEYS:
                out[k] = json.loads(json.dumps(v))
        if not any(b.get("type") == "backing-track" for b in blocks):
            out.pop("backing", None)                 # une backing sans son bloc ne joue pas : elle ne voyage pas
        if preset.get("bpm"):
            out["bpm"] = preset["bpm"]
    if len(lanes) == 1 and not lanes[0].get("drumset"):
        out["chain"] = json.loads(json.dumps(lanes[0]["chain"]))   # le MIROIR (lecteurs d'avant)
    needs, seen = [], set()
    for src in [L["chain"] for L in lanes] + [{"cfg": (out.get("config") or {}).get("gen", {}).get("blocks") or []}]:
        for n in needs_of(src):
            k = json.dumps(n, sort_keys=True)
            if k not in seen:
                seen.add(k)
                needs.append(n)
    out["needs"] = needs
    return out


_V2_SIG_KEYS = ("lanes", "scenes", "config", "colors", "anims", "backing", "bpm", "chain", "role")


def _v2_sig(doc):
    return json.dumps({k: doc.get(k) for k in _V2_SIG_KEYS + tuple(k for k in doc if _EXP_KEY.match(k))},
                      sort_keys=True, ensure_ascii=False)


def patch_lanes_of(preset, realm):
    """Les lanes du brouillon qui FONT le patch : en mode patch (`__patch`), toutes celles du banc —
    le banc EST le patch ; sinon la lane `realm` du morceau (« Save lane as patch »)."""
    from . import store
    pm = (preset or {}).get("__patch") or {}
    if pm:
        lanes = store.lanes_of(preset)
        if pm.get("drumset"):
            ids = [L["id"] for L in lanes if L.get("drumset") == pm["drumset"]]
        else:
            # le banc part de blank() : trois lanes (guitare, voix, claviers) dont une seule est le patch —
            # celles du RÔLE du patch, la lane affichée (`realm`) en tête
            ids = [L["id"] for L in lanes if L.get("role") == pm.get("role")]
            if realm in {L["id"] for L in lanes}:
                ids = [realm] + [i for i in ids if i != realm]
        return ids or [realm]
    return [realm]


def deposit_payload(doc):
    """(chaîne, scènes) qu'un patch DÉPOSE dans une lane de morceau — v1 ou v2 (docs/patches.md §5).
    Jamais sa config. Les scènes v2 portent `lanes` indexé par l'id de lane DU PATCH : déposé tel quel, ça
    ferait une entrée orpheline dans le morceau — on le retire, le niveau voyage par `level`."""
    if is_v2(doc):
        chain = json.loads(json.dumps(doc["lanes"][0].get("chain") or {}))
    else:
        chain = json.loads(json.dumps(doc.get("chain") or {}))
    scenes = None
    if isinstance(doc.get("scenes"), list):
        scenes = []
        for sc in doc["scenes"]:
            sc = {k: json.loads(json.dumps(v)) for k, v in sc.items() if k != "lanes"}
            scenes.append(sc)
    return chain, scenes


def _target_lane(preset, doc, lane=None):
    """La lane d'un morceau qui reçoit un patch : celle qu'on a désignée, sinon (v2) la première lane de SON
    RÔLE — jamais un id `guitar` supposé, qui n'existe plus dans un morceau v2."""
    from . import store
    if lane and lane in lane_ids(preset):
        return lane
    if store.is_v2(preset):
        role = doc.get("role") or "guitar"
        realm = next((L["id"] for L in store.lanes_of(preset) if L["role"] == role), None) \
            or next((L["id"] for L in store.lanes_of(preset) if L["role"] in ("guitar", "bass", "line") and role in ("guitar", "bass", "line")), None)
        if realm is None and role == "drums":
            # docs/drums-kit.md : un patch batterie n'atterrit JAMAIS sur la lane guitare « faute de mieux »
            raise ValueError("this preset has no Drums lane — add a Drums input (Soundcard) or a drum module on a USB port first")
        return realm or (store.lanes_of(preset) or [{"id": "guitar"}])[0]["id"]
    return REALM_OF_ROLE.get(doc.get("role") or "guitar", "guitar")


def add_kit_lanes(preset, doc):
    """Un kit multi-lane déposé dans un morceau qui n'a pas de groupe : ses lanes naissent sur les entrées
    LIBRES de la carte, dans l'ordre du kit (le calcul du tiroir « Add a drum kit », drums-kit.md §6.5).
    Rend (preset copiée, id du groupe)."""
    from . import store, inputmap
    from .state import state
    p = json.loads(json.dumps(preset))
    if not store.is_v2(p):
        raise ValueError("this song is not in the lanes format yet — open it in the Designer once, then deposit the kit")
    imap = state.inputmap or inputmap.current() or {}
    used = set()
    for L in store.lanes_of(p):
        if not L.get("midi"):
            used.update(c for c in str(L.get("in_sel") or "").split("-") if c)
    free = [c for e in (imap.get("inputs") or []) for c in str(e.get("ch")).split("-") if c not in used]
    ds = _safe_id(doc.get("id") or "drums")
    els = [e.get("element") for e in (doc.get("elements") or []) if e.get("element")]
    taken = {L["id"] for L in p.get("lanes") or []}
    for i, el in enumerate(els):
        lid = _safe_id(f"{ds}-{el}")
        while lid in taken:
            lid += "-2"
        taken.add(lid)
        p["lanes"].append({"id": lid, "key": lid, "role": "drums", "name": el, "out_sel": "1-2",
                           "in_sel": free[i] if i < len(free) else "NONE",
                           "chain": store.rich_chain(None), "drumset": ds,
                           "drumset_module": doc.get("drumset_module") or ds, "element": el})
    return p, ds


def refresh_deps():
    """Les `deps[]` de chaque patch v2 (garantie 4, docs/patches.md §9 bis) : à la forme de l'export
    de preset — toutes ses lanes ET son ⚙ (captures, kits, samples, Vital, grooves) —, calculées par
    `preset_export` sur `patch:<id>` et écrites dans le fichier. Seulement quand le patch a changé
    (`deps_sig`) : l'export hache la bibliothèque. Rend le nombre de patches mis à jour."""
    from . import preset_export
    n = 0
    for doc in list_patches():
        if not is_v2(doc):
            continue
        sig = _v2_sig(doc)
        if doc.get("deps_sig") == sig:
            continue
        out, _blobs = preset_export.build_export(PATCH_PREFIX + doc["id"])
        if out is None:
            continue
        cur = get_patch(doc["id"]) or doc
        new = dict(cur, deps=out.get("deps") or [], deps_sig=sig)
        if out.get("unresolved"):
            new["unresolved"] = out["unresolved"]
        else:
            new.pop("unresolved", None)                 # plus rien d'irrésolu : la liste ne traîne pas
        _write(new)
        n += 1
    return n
