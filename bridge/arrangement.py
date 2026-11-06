# SPDX-License-Identifier: GPL-3.0-or-later
"""Moteur de CUES — le bloc `arrangement` joué (contrat docs/arrangement.md §8).

── UNE CUE RÉFÉRENCE UN BLOC, PAS UN SWITCH (décision 2026-07-30) ─────────────────────
« Stomp 7 » était du vocabulaire de PÉDALIER échappé dans le morceau. Le morceau ne connaît pas
le switch 7 ; il connaît « le boost est enclenché ». Le jour où l'on réassigne le boost au switch
9 — ce qui arrive à chaque réorganisation du pédalier — tous les arrangements changeraient de
sens EN SILENCE. Même famille d'erreur que le preset référencé par id du contrat Show.
Une cue porte donc `blocks: {"<id>": true|false}`, ce qui donne au passage la capacité
d'automatiser un bloc QUI N'EST PAS AU PIED — une automation n'a aucune raison d'exiger une
pédale.

Ce module est le chef d'orchestre. Il ne produit aucun audio et n'ajoute AUCUNE ligne côté
Reaper : il actionne des chemins déjà livrés — rappel de scène sans rebuild (gapless) et
bascule de stomps, dont `_do_stomp(sw, want)` acceptait déjà un état ABSOLU « pour les cues ».

── PLANIFIÉ, PAS POLLÉ ────────────────────────────────────────────────────────────────────
Tempo et métriques connus, on calcule l'instant de chaque frontière de section et on POSE un
réveil asyncio dessus. Un poll donnerait la latence de sa période sur un changement de scène,
et il faudrait le faire tourner en permanence pour rien.

── LA MESURE, ET UNE SEULE HORLOGE (§5) ───────────────────────────────────────────────────
    durée_pulsation = (4/den) × 60/bpm        durée_mesure = num × durée_pulsation
LE BPM DÉSIGNE LA NOIRE (convention Reaper). 7/8 à 120 -> 1,75 s la mesure ; 9/4 -> 4,5 s.
C'est la MÊME formule que le JSFX du click et que l'UI de la feuille : trois implémentations
qui doivent rester d'accord, sinon le batteur entend la mesure 33 pendant que le rig tire la 34.

── LES QUATRE RÈGLES (§12), toutes appliquées ici ─────────────────────────────────────────
1. Un arrangement ne traverse JAMAIS un changement de preset : `stop()` au recall.
2. Il SE RÉPARE : la scène est réappliquée à CHAQUE frontière. Le pied gagne maintenant,
   l'arrangement reprend la main à la section suivante.
3. La dernière section TIENT : on cesse d'avancer, on ne boucle pas, on ne coupe rien.
4. Une section qui pointe vers une scène absente NE FAIT RIEN (et le dit dans l'état) plutôt
   que de faire n'importe quoi.
"""
import asyncio
import threading

from . import config as C
from .golog import get

log = get("arrangement")
import os
import time

# ── GESTES AU PIED, sur UN SEUL switch (révisé le 2026-10-08, « juste start et stop, one tap à chaque fois »)
#   au repos          tap  -> LANCE le morceau (décompte compris)
#   en cours          tap  -> ARRÊTE tout (backing, click, prise) — et le morceau s'arrête aussi tout seul à sa fin
#   en cours, `foot`  tap  -> PARTIE SUIVANTE (c'est ce mode-là), puis ARRÊT après la dernière
# Avant : tap = « réappliquer la partie », appui long = arrêt — deux gestes que personne ne retenait.
# PRÉ-ARMEMENT (§15, gigue mesurée à ~30 ms = le tick defer de Reaper) : on émet la commande
# en avance avec l'instant visé, le JSFX décompte dans le thread audio. 0,35 s couvre dix fois
# la gigue mesurée sans qu'un STOP arrive trop tard pour annuler un tir déjà armé.
PREARM_S = 0.35
# horloge du transport (§5) : on relit la position de la backing au plus toutes les CLOCK_TICK_S ; un
# recul de plus de REWIND_S sous le début de la partie courante = on est revenu en arrière ; le HUD
# n'est republié que si l'origine estimée bouge de plus de HUD_SHIFT_S (une pause la fait glisser).
CLOCK_TICK_S = 0.05
REWIND_S = 0.5
HUD_SHIFT_S = 0.5
# LES GESTES DE RÉPÈTE (docs/live-pages.md §6, 2026-10-15). À une frontière de saut, le moteur applique lui-même la
# section cible et IGNORE le transport pendant JUMP_QUIET_S : la position de la backing n'est publiée qu'au quart de
# seconde (golem_backing.lua) — la suivre ferait entendre la section suivante 0,3 à 0,5 s avant le saut (relecture de
# l'ingénieur du son). Passé ce délai, si le transport contredit le moteur (saut raté), on se recale sur lui :
# FORWARD_S au-delà de la fin de la section courante = le transport est ailleurs.
JUMP_QUIET_S = 0.35
FORWARD_S = 0.6


def _sig(sec, base):
    s = sec.get("sig") or {}
    b = base or {}
    return (int(s.get("num") or b.get("num") or 4),
            int(s.get("den") or b.get("den") or 4))


def click_meter(sec, base):
    """La mesure que le CLICK doit jouer dans cette section : {beats, den, groups}, ou None quand ni la section ni le
    morceau n'en déclarent une — le click garde alors la sienne (surcharge de la ligne, puis config/click.json).
    `groups` n'est gardé que s'il fait bien `num` (le Lua retomberait de toute façon sur « le 1 seul »)."""
    s = (sec or {}).get("sig") or {}
    b = base or {}
    own = bool(s.get("num") or s.get("den"))
    if not (own or b.get("num") or b.get("den")):
        return None
    num, den = _sig(sec or {}, base)
    g = s.get("groups") if own else b.get("groups")
    ok = isinstance(g, list) and g and all(isinstance(x, int) and x > 0 for x in g) and sum(g) == num
    return {"beats": num, "den": den, "groups": list(g) if ok else []}


def click_anchor(plan_, k):
    """L'ANCRE DE PHASE du click pour la section `k` du plan (docs/arrangement.md §4) : l'instant (s, temps du morceau =
    position du transport de la backing, posée à 0) où commence la mesure 1 de la SUITE de sections de même mesure qui
    contient `k`. Le JSFX y recale sa phase au départ, au saut et au seek : pas = (pos − ancre) × bpm × den / 240.
    Pourquoi le début de la suite et pas celui de la section : des mesures ENTIÈRES de la même mesure donnent la même
    phase, et une ancre qui ne bouge pas ne coûte aucune commande — on n'en envoie une qu'à un changement de mesure."""
    if not (0 <= k < len(plan_)):
        return None
    key = (plan_[k]["num"], plan_[k]["den"])
    j = k
    while j > 0 and (plan_[j - 1]["num"], plan_[j - 1]["den"]) == key:
        j -= 1
    return round(float(plan_[j]["at"]), 4)


def section_seconds(sec, base, bpm):
    num, den = _sig(sec, base)
    return int(sec.get("bars") or 0) * num * (4.0 / den) * (60.0 / (bpm or 120))


def sample_marks(preset, bars=None):
    """La LANE DE SAMPLES (docs/arrangement.md §14) : [{at, block, idx, ring}] en secondes
    depuis le départ du morceau.

    Un marqueur vit à une MESURE ABSOLUE du morceau, pas dans une section — un riser traverse
    une frontière, un sub-drop tombe au milieu d'un solo. On convertit donc bar/beat en
    secondes en parcourant les sections (leurs mesures peuvent différer : 7/8 puis 4/4).

    `anchor: "land"` = le sample doit ARRIVER à cette mesure : on recule de sa durée. C'est ce
    qui sépare un outil d'un gadget — sans lui, on pose les risers à l'oreille en tâtonnant.
    Un marqueur dont le bloc n'existe plus est IGNORÉ (même loi que les scènes, règle 4).
    """
    b = block_of(preset)
    if not b:
        return []
    pm = b.get("params") or {}
    if pm.get("samples_off"):
        return []                                   # interrupteur global de la lane
    base = pm.get("sig") or {"num": 4, "den": 4}
    bpm = (preset or {}).get("bpm") or 120
    blocks = {x.get("id"): x for x in _sample_blocks(preset)}
    # table mesure -> instant : on cumule section par section (mètres composés compris)
    edges, t, bar = [], 0.0, 1
    for sec in pm.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        num, den = _sig(sec, base)
        one = num * (4.0 / den) * (60.0 / bpm)      # durée d'UNE mesure de cette section
        n = int(sec.get("bars") or 0)
        edges.append((bar, bar + n, t, one, num))
        t += n * one
        bar += n
    tail = (base.get("num", 4) * (4.0 / base.get("den", 4)) * (60.0 / bpm))

    def at_of(bar_no, beat):
        if bars:                                     # la carte des mesures : l'instant RÉEL (bars.py)
            from . import bars as _bars
            return _bars.time_of(bars, bar_no, beat)
        for b0, b1, t0, one, num in edges:
            if b0 <= bar_no < b1:
                return t0 + (bar_no - b0) * one + max(0, (beat or 1) - 1) * (one / max(1, num))
        return t + (bar_no - bar) * tail            # au-delà de l'écrit : mesure de base

    out = []
    for m in pm.get("samples") or []:
        if not isinstance(m, dict):
            continue
        blk = blocks.get(m.get("block"))
        if not blk:
            continue                                # bloc disparu -> rien (et ça se voit à l'écran)
        from . import sample as _smp
        samples = _smp.files_of(blk)               # liste COMPLÈTE : la lane ignore le drapeau
                                                   # « au pied » — un son de morceau n'a pas à
                                                   # défiler sous la pédale (décision)
        idx = int(m.get("idx") or 0)
        if not (0 <= idx < len(samples)):
            continue
        at = at_of(int(m.get("bar") or 1), m.get("beat"))
        dur = sample_seconds(samples[idx])
        if m.get("anchor") == "land":
            at -= dur                               # « atterrit à » : on recule de la durée RÉELLE
        out.append({"at": max(0.0, at), "block": blk["id"], "idx": idx, "dur": dur,
                    "ring": m.get("stop") != "section", "samples": samples,
                    "name": m.get("name") or ""})
    out.sort(key=lambda x: x["at"])
    return out


# durée d'un sample, en secondes — LE RACK possède cette vérité, pas l'app : c'est lui qui a
# les fichiers. Cache sur (chemin, mtime) : `sample_marks` est appelé à chaque load/start.
_dur_cache = {}


def sample_seconds(rel):
    """Durée d'un WAV, 0 si illisible (l'ancre « atterrit à » retombe alors sur « démarre à »
    — dégrade, jamais silencieusement : la maquette montre la durée, on verra qu'elle est nulle)."""
    p = rel if os.path.isabs(rel) else os.path.join(C.ROOT, rel)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return 0.0
    hit = _dur_cache.get(p)
    if hit and hit[0] == mt:
        return hit[1]
    d = 0.0
    try:
        import wave
        with wave.open(p, "rb") as w:
            fr = w.getframerate() or 0
            d = (w.getnframes() / fr) if fr else 0.0
    except Exception:
        d = 0.0
    _dur_cache[p] = (mt, d)
    return d


def _sample_blocks(preset):
    """Les blocs `sample` du preset (lane config `gen`)."""
    cfg = (preset or {}).get("config") or {}
    return [b for b in ((cfg.get("gen") or {}).get("blocks") or [])
            if isinstance(b, dict) and b.get("type") == "sample" and b.get("id")]


def foot_switch(preset):
    """Le switch qui porte l'arrangement, ou None. Un seul bloc, donc un seul switch."""
    b = block_of(preset)
    sw = (b or {}).get("foot")
    return sw if isinstance(sw, int) else None


def block_of(preset):
    """Le bloc `arrangement` du preset, ou None. Unique par contrat."""
    arr = ((preset or {}).get("config") or {}).get("arr") or {}
    for b in arr.get("blocks") or []:
        if isinstance(b, dict) and b.get("type") == "arrangement" and not b.get("bypass"):
            return b
    return None


def rig_block(preset):
    """Le bloc du RIG (config.arr), même sans parties — `block_of` ignore un bloc bypassé, pas nous."""
    arr = ((preset or {}).get("config") or {}).get("arr") or {}
    for b in arr.get("blocks") or []:
        if isinstance(b, dict) and b.get("type") == "arrangement":
            return b
    return None


# Les blocs qui « montaient » avec l'arrangement quand on les EMPILAIT sur son switch (lot 3 du 2026-10-07),
# et la case de la chanson qui dit désormais la même chose (docs/arrangement.md §7). Backing : pas de
# case à poser — elle part déjà avec le morceau par défaut.
STACK_TO_START = {"rec": "rec", "click": "click", "backing-track": None}
MIGRATION_FILE = ".arr-stacks-migrated.json"     # dans presets/ : ce qui a été déplacé, pour le DIRE une fois


def migrate_stacks_to_starts():
    """UNE FOIS, au démarrage (docs/arrangement.md §7, lot 3) : les blocs EMPILÉS sur le switch de
    l'arrangement deviennent des CASES de la chanson, et quittent le switch.

    Avant le contrat, « lancer la prise avec le morceau » se disait en posant Rec sur le switch de
    l'arrangement ; Click et Backing s'y empilaient aussi, sans y rien faire (le switch du morceau leur volait
    le geste). Désormais la chanson coche « When the song starts » : on pose la case équivalente sur CHAQUE
    chanson qui joue ce preset (si elle n'a pas déjà été réglée — une case touchée à la main gagne), sur chaque
    ligne de setlist LIBRE (sans chanson) qui porte son propre arrangement, puis on retire le switch des blocs
    empilés. Le brouillon du Designer (`.sandbox.json`) reçoit la même retouche s'il porte ce preset — sinon
    sa prochaine audition remettrait l'empilement (CLAUDE.md : le Designer édite la sandbox).

    Idempotent : un preset sans empilement n'est pas touché. Rend [{preset, name, switch, moved, songs, lines}],
    et l'écrit dans presets/.arr-stacks-migrated.json (le Designer le dit une fois, preset par preset)."""
    import glob
    import json

    from . import config as C
    from . import songs as _songs
    from . import store

    def stacked(p):
        blk = rig_block(p) or {}
        sw = blk.get("foot")
        if not isinstance(sw, int):
            return None, []
        out = []
        for lane in ("gen", "rec"):
            for b in (((p.get("config") or {}).get(lane) or {}).get("blocks") or []):
                if isinstance(b, dict) and b.get("type") in STACK_TO_START and b.get("foot") == sw:
                    out.append(b)
        return sw, out

    def tick(arr, types):
        """Pose les cases sur un bloc arrangement (dict muté) ; rend True s'il a changé."""
        if not isinstance(arr, dict):
            return False
        prm = arr.setdefault("params", {})
        st = dict(prm.get("starts") or {})
        changed = False
        for t in types:
            k = STACK_TO_START.get(t)
            if k and st.get(k) is None:
                st[k] = True
                changed = True
        if changed:
            prm["starts"] = st
        return changed

    done = []
    for path in sorted(glob.glob(os.path.join(C.PRESETS_DIR, "*.json"))):
        if os.path.basename(path).startswith("."):
            continue
        try:
            p = json.load(open(path))
        except Exception:
            continue
        if not isinstance(p, dict) or not p.get("id"):
            continue
        sw, blocks = stacked(p)
        if not blocks:
            continue
        pid = p["id"]
        types = sorted({b["type"] for b in blocks})
        n_songs = 0
        for doc in _songs.list_all():
            sheet = doc.get("sheet") or {}
            if sheet.get("preset") != pid or not isinstance(sheet.get("arrangement"), dict):
                continue
            if tick(sheet["arrangement"], types):
                _songs.save(doc)
                n_songs += 1
        n_lines = 0
        for spath in sorted(glob.glob(os.path.join(C.SETLISTS_DIR, "*.json"))):
            try:
                d = json.load(open(spath))
            except Exception:
                continue
            changed = False
            for ln in (d.get("lines") or []) if isinstance(d, dict) else []:
                if isinstance(ln, dict) and ln.get("preset") == pid and not ln.get("band_song") \
                        and tick(ln.get("arrangement"), types):
                    ln["rev"] = int(ln.get("rev") or 1) + 1
                    changed = True
                    n_lines += 1
            if changed:
                store._write_json_atomic(spath, d)
        for b in blocks:
            b.pop("foot", None)
        store._write_json_atomic(path, p)
        sb_path = os.path.join(C.PRESETS_DIR, ".sandbox.json")
        try:
            sb = json.load(open(sb_path))
        except Exception:
            sb = None
        if isinstance(sb, dict) and isinstance(sb.get("preset"), dict) and sb["preset"].get("id") == pid:
            _sw, sb_blocks = stacked(sb["preset"])
            for b in sb_blocks:
                b.pop("foot", None)
            if sb_blocks:
                store._write_json_atomic(sb_path, sb)
        done.append({"preset": pid, "name": p.get("name") or pid, "switch": sw, "moved": types,
                     "songs": n_songs, "lines": n_lines})
    if done:
        mpath = os.path.join(C.PRESETS_DIR, MIGRATION_FILE)
        try:
            prev = json.load(open(mpath))
        except Exception:
            prev = {}
        items = {x["preset"]: x for x in (prev.get("items") or []) if isinstance(x, dict)}
        for x in done:
            items[x["preset"]] = {**x, "at": time.time()}
        store._write_json_atomic(mpath, {"items": list(items.values())})
    return done


def migrate_foot_to_rig():
    """UNE FOIS : la PÉDALE de l'arrangement passe de la chanson au rig (docs/arrangement.md §4 bis,
    décision du 2026-09-16, maquette « Designer allégé »).

    Pourquoi : une pédale appartient au pédalier. Rangée dans la ligne de setlist, elle rendait possible
    deux morceaux du même rig démarrant sur deux pédales différentes, et l'éditeur de pédalier ne voyait
    pas l'arrangement du tout. On lit la pédale (et la règle d'avance) des arrangements existants et on
    la pose sur le bloc du preset. La ligne garde son champ : il n'est plus lu (`recall.merge_arrangement`).

    Idempotent : un preset dont le bloc a déjà une pédale n'est pas retouché. Rend [(preset, foot, n)]
    où `n` est le nombre de pédales DIFFÉRENTES trouvées sur les lignes — plus d'une se journalise, on
    prend la plus fréquente, parce qu'il faut bien en choisir une et qu'un silence serait pire."""
    import glob
    import json
    from collections import Counter

    from . import config as C
    from . import store

    seen = {}
    for path in sorted(glob.glob(os.path.join(C.SETLISTS_DIR, "*.json"))):
        try:
            d = json.load(open(path))
        except Exception:
            continue
        for ln in (d.get("lines") or []) if isinstance(d, dict) else []:
            a = (ln or {}).get("arrangement") or {}
            pid = (ln or {}).get("preset")
            if pid and a.get("foot"):
                seen.setdefault(pid, []).append((a["foot"], (a.get("params") or {}).get("advance")))
    done = []
    for pid, rows in seen.items():
        p = store.load_preset(pid)
        if p is None:
            continue
        blk = rig_block(p)
        if blk and blk.get("foot"):
            continue                                  # déjà migré, ou posé à la main
        foot = Counter([r[0] for r in rows]).most_common(1)[0][0]      # la pédale, pas le couple
        adv = Counter([r[1] for r in rows if r[1]]).most_common(1)
        cfg = p.setdefault("config", {})
        lane = cfg.setdefault("arr", {})
        blocks = lane.setdefault("blocks", [])
        if blk is None:
            blk = {"type": "arrangement", "id": "arr-1", "params": {}}
            blocks.append(blk)
        blk["foot"] = foot
        if adv:
            blk.setdefault("params", {})["advance"] = adv[0][0]
        store._write_json_atomic(os.path.join(C.PRESETS_DIR, f"{store._safe_id(pid)}.json"), p)
        n = len({r[0] for r in rows})
        done.append((pid, foot, n))
        if n > 1:
            log.warning(f"arrangement de {pid} : {n} pédales différentes sur les lignes, on garde SW{foot}")
    return done


def plan(preset, bars=None):
    """[{i, name, at, dur, scene, stomps, samples, num, den}] — `at` en secondes depuis le départ.

    Rend [] si le preset n'a pas d'arrangement jouable. Les scènes inconnues du preset sont
    NEUTRALISÉES ici (règle 4) : la section reste dans le plan, elle ne commande simplement rien.

    `bars` = la CARTE DES MESURES de la backing (bridge/bars.py, docs/bars-format.md) : une partie part
    alors à l'instant RÉEL de sa première mesure sur la timeline des stems, et non plus à « n mesures ×
    tempo de la fiche » — un groupe joué sans click n'a pas un tempo (Paper Kite : 85 → 89 BPM).
    Sans carte : le tempo de la fiche, comme avant.
    """
    b = block_of(preset)
    if not b:
        return []
    pm = b.get("params") or {}
    declared = pm.get("sig") or None                    # la mesure du MORCEAU telle qu'écrite (None = rien de dit)
    base = declared or {"num": 4, "den": 4}
    bpm = (preset or {}).get("bpm") or 120
    known = {(s.get("id") or chr(65 + i)) for i, s in enumerate((preset or {}).get("scenes") or [])}
    known_blocks = _block_ids(preset)
    out, t, bar = [], 0.0, 1
    if bars:
        from . import bars as _bars
    for i, sec in enumerate(pm.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        d = section_seconds(sec, base, bpm)
        num, den = _sig(sec, base)
        n_bars = int(sec.get("bars") or 0)
        if bars:
            t = _bars.time_of(bars, bar)
            d = _bars.time_of(bars, bar + n_bars) - t
        bar += n_bars
        sc = sec.get("scene")
        out.append({"i": len(out), "name": str(sec.get("name") or "part")[:24],
                    "at": t, "dur": d, "bars": int(sec.get("bars") or 0),
                    "scene": sc if sc in known else None,
                    "broken": bool(sc) and sc not in known,
                    # bascules explicites, par ID de bloc. Un id inconnu du preset est ignoré
                    # (même loi que la scène absente : on ne fait RIEN plutôt que n'importe quoi).
                    "blocks": {k: bool(v) for k, v in (sec.get("blocks") or {}).items()
                               if k in known_blocks},
                    "samples": sec.get("samples") if isinstance(sec.get("samples"), list) else [],
                    # LA BATTERIE DE LA SECTION (2026-10-20) : un numéro de groove (index des motifs du bloc drums), « stop »,
                    # ou rien = la section garde le groove d'avant
                    "drums": _drums_of(sec),
                    "num": num, "den": den,
                    # ce que le click joue dans la section (docs/arrangement.md §3) — None = la mesure du click
                    "click": click_meter(sec, declared)})
        t += d
    return out


def _drums_of(sec):
    v = (sec or {}).get("drums")
    if v == "stop" or v is False:
        return "stop"
    if isinstance(v, bool) or v is None:
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def drums_at(plan_, k):
    """Le groove qui doit jouer dans la section `k` : la dernière consigne posée à `k` ou avant ; sans aucune, le
    premier motif (le morceau démarre la batterie, la section 1 n'a pas à le redire)."""
    for j in range(min(k, len(plan_) - 1), -1, -1):
        v = plan_[j].get("drums")
        if v is not None:
            return v
    return 0


def _block_ids(preset):
    """Tous les ids de blocs du preset, toutes lanes confondues — pour valider les cues."""
    out, p = set(), preset or {}
    def walk(arr):
        for b in arr or []:
            if isinstance(b, dict) and b.get("id"):
                out.add(b["id"])
    from .store import all_blocks                                   # lot 4 : toutes les lanes, v2 ou legacy
    walk([b for b, _l in all_blocks(p)])
    return out


def starts_of(preset):
    """CE QUI PART AVEC LE MORCEAU (docs/arrangement.md §5-6) : les cases de la chanson,
    `params.starts` = {backing, click, rec, sample, drums}. Une case ABSENTE vaut None — l'appelant garde alors le
    comportement d'avant le contrat (backing, samples et batterie oui, click si son bloc est actif, pas de prise). Une
    case False coupe, une case True force."""
    b = block_of(preset) or {}
    st = (b.get("params") or {}).get("starts") or {}
    return {k: (bool(st[k]) if k in st and st[k] is not None else None)
            for k in ("backing", "click", "rec", "sample", "drums")}


def count_in_seconds(preset):
    """Durée du décompte, DANS LA MÉTRIQUE DE LA PREMIÈRE SECTION (§13) — décompter en 4/4 puis
    partir en 7 est le plus sûr moyen de rater le départ."""
    b = block_of(preset)
    if not b:
        return 0.0
    pm = b.get("params") or {}
    bars = int(pm.get("count_in") or 0)
    if bars <= 0:
        return 0.0
    secs = pm.get("sections") or []
    first = secs[0] if secs else {}
    base = pm.get("sig") or {"num": 4, "den": 4}
    num, den = _sig(first if isinstance(first, dict) else {}, base)
    return bars * num * (4.0 / den) * (60.0 / ((preset or {}).get("bpm") or 120))


class ArrangementCtl:
    """Un seul arrangement tourne à la fois — comme le rig n'a qu'un preset chargé.

    `apply_cue(sec)` et `on_change()` sont injectés : ce module ne connaît ni Reaper, ni le
    bridge, ni les routes — il ne sait que compter le temps et dire quoi appliquer, quand.
    """

    # ── pied ──
    def on_edge(self, sw, on, preset=None):
        """Front Note du FCB. Thread lecteur MIDI : on ne fait ici que de la décision et des
        appels courts — la planification, elle, vit dans la boucle asyncio."""
        # UN TAP DÉMARRE, UN TAP ARRÊTE (2026-10-08 : « il faut juste start et stop, et c'est one tap à chaque
        # fois »). Plus d'appui long, plus de « recaler » au tap : le morceau s'arrête aussi tout seul à sa fin. En
        # mode d'avance `foot` seulement, le tap fait passer à la partie suivante — c'est ce mode-là — et la
        # dernière partie franchie, il arrête.
        if on:
            self._press[sw] = {"t": time.monotonic(), "preset": preset}
            return
        p = self._press.pop(sw, None)
        if not p:
            return
        if not (self._live or self._counting):
            self._start_threadsafe(p.get("preset"))
        elif self._mode == "foot" and not self._counting and self._idx + 1 < len(self._plan):
            self.next()
        else:
            self._stop_threadsafe()

    def _stop_threadsafe(self):
        """`stop` annule une tâche asyncio : comme `start`, il passe par la boucle (thread MIDI ici)."""
        loop = self._loop
        if loop:
            loop.call_soon_threadsafe(self.stop)
        else:
            self.stop()

    def _start_threadsafe(self, preset):
        """`start` crée une tâche asyncio : elle DOIT naître dans la boucle, pas dans le thread
        MIDI (ensure_future y lèverait, ou pire, attacherait la tâche à une boucle morte)."""
        if not preset:
            return
        loop = self._loop
        if loop:
            loop.call_soon_threadsafe(lambda: self.start(preset, by="the pedalboard"))
        else:
            self.start(preset, by="the pedalboard")

    def __init__(self, apply_cue, on_change=None, click_hold=None, loop=None, allowed=None,
                 apply_sample=None, on_song=None, backing=None, transport=None, click_song=None, backing_ctl=None,
                 click_meter=None, drums=None):
        self._apply = apply_cue
        self._apply_sample = apply_sample or (lambda cue: None)
        self._marks = []
        self._on_change = on_change or (lambda: None)
        # LE MORCEAU COMMENCE / FINIT (docs/devices-people.md, lot F) : on_song("start", info) et
        # on_song("end", info) — le REC qui suit le morceau en répète, et qui part avec la 1re chanson en show
        self._on_song = on_song or (lambda ev, info: None)
        self._by = None           # qui a lancé : « le mainteneur », « the pedalboard », « the rack screen »
        self._click_hold = click_hold or (lambda on: None)
        # LA BACKING PART AVEC LE MORCEAU (§8 « Départ = lancer le morceau », §13.3) : backing(True) au
        # premier temps de la section 1 — APRÈS le décompte, qui décale donc les stems — et backing(False)
        # au ■ Stop. Rend True si une backing est partie. Injecté : ce module ne connaît pas Reaper.
        self._backing = backing or (lambda on: False)
        # LE CLICK DU MORCEAU (§8 « Départ = … le click si le mode l'autorise ») : click_song(ev), ev ∈
        # start (avant le décompte : on note s'il jouait) · go (premier temps) · cancel (arrêt pendant le
        # décompte) · stop (■ Stop, appui long, ou fin du morceau). Sans lui : l'ancien comportement — le
        # click ne sonne que le temps du décompte.
        self._click_song = click_song
        # LA MESURE DU CLICK SUIT LA SECTION (docs/arrangement.md §3) : click_meter(meter, push) avec meter =
        # {beats, den, groups} ou None (= la mesure du click d'avant). push=False : seulement la retenir — les
        # commandes du départ (décompte, premier temps) la portent déjà.
        self._click_meter = click_meter or (lambda meter, push=True: None)
        self._meter_sent = None   # la mesure confiée au click (None = la sienne)
        # LA BATTERIE PART AVEC LE MORCEAU (2026-10-20) : drums(op, idx=None), op ∈ play (premier temps, groove de la
        # section) · pattern (le groove suivant, envoyé dans la dernière pulsation : le JSFX le cale sur la mesure) ·
        # stop. Rend False quand le preset n'a pas de boîte à rythmes (ou que le mode la coupe) : on n'insiste plus.
        self._drums = drums or (lambda op, idx=None: False)
        self._drm = {"on": False, "idx": None, "off": True}
        self._bpm = 120
        self._with_backing = False
        # L'HORLOGE (§5) : avec une backing qui joue, le maître est le TRANSPORT, pas l'horloge du serveur.
        # transport() -> {playing, paused, pos, at} : `pos` lu dans Reaper à l'instant `at` (epoch).
        self._transport = transport or (lambda: None)
        self._bk_t = 0.0          # instant où l'on a lancé la backing : un état publié AVANT est périmé
        self._clock = "server"
        self._follow = False      # True = le transport de la backing donne le temps
        self._starts = {}         # les cases « When the song starts » du morceau lancé (starts_of)
        # veto de MODE (docs/modes.md) : l'automation ne tourne que là où on l'a demandée.
        # Injecté — ce module ne connaît pas les modes, il sait juste demander.
        self._allowed = allowed or (lambda: True)
        self._plan = []
        self._task = None
        self._idx = -1
        self._t0 = 0.0            # instant de la section 0 (APRÈS le décompte)
        self._mode = "bars"
        # vue demandée par le bloc pour /live (docs : la vue découle du preset). Défaut
        # live_view : ce que le MORCEAU demande à /live (Timeline | Pedalboard), None = rien de dit.
        # Depuis le 2026-09-24 (« l'arrangement suit le lecteur ») c'est /live qui décide du défaut :
        # pendant qu'un arrangement tourne, le pupitre — sauf si la chanson dit Pedalboard.
        self._live_view = None
        self._c0 = None                              # début du décompte (horloge serveur), pour le HUD
        self._counting = False
        self._done = False
        # ⚠ « VIVANT » ≠ « une tâche tourne ». En mode `foot` la tâche meurt dès la 1re section
        # (la suite vient des appuis, pas du temps) : se fier à `_task` faisait croire le morceau
        # à l'arrêt, donc chaque tap le REDÉMARRAIT sur l'intro au lieu d'avancer.
        self._live = False
        self._press = {}
        self._loop = loop
        # LES GESTES DE RÉPÈTE (docs/live-pages.md §6) — la commande de la backing : backing_ctl(op, **kw) avec
        # op ∈ seek(pos) · jump(at, to) · jump_off() · loop(a, b) · loop_off(). Le saut AUDIO est fait par Reaper
        # (golem_backing.lua) ; ce module ne connaît que le temps du morceau.
        self._bctl = backing_ctl or (lambda op, **kw: None)
        self._reset_practice()

    def attach_loop(self, loop):
        self._loop = loop

    # ── les gestes de répète (docs/live-pages.md §6) ──
    def _reset_practice(self):
        self._cue = None          # section mise en attente pour la prochaine frontière
        self._sloop = False       # la section courante boucle
        self._loops = 0           # tours accomplis de la boucle
        self._from = 0            # section de départ
        self._jumped = False      # un saut a eu lieu : les samples repartent sans `ring` (§6.3)
        self._quiet_until = 0.0   # transport ignoré jusque-là (JUMP_QUIET_S)
        self._prev_st = None      # temps du morceau au tour de boucle précédent (discontinuités)
        self._prearmed = set()    # marques de la section cible déjà pré-armées pour le saut

    def _armed(self):
        return self._with_backing and self._follow

    def _cur_bounds(self):
        cur = self._plan[self._idx] if 0 <= self._idx < len(self._plan) else None
        return (cur["at"], cur["at"] + cur["dur"]) if cur else (None, None)

    def _arm_backing(self):
        """Pose dans Reaper ce qui fera le saut audio à la frontière (§6.2) : boucle native vers l'arrière ou sur
        place, seek déclenché par le Lua vers l'avant, rien vers la section suivante."""
        if not self._armed():
            return
        a, b = self._cur_bounds()
        if a is None:
            return
        k = self._cue
        try:
            if k is None:
                self._bctl("loop", a=a, b=b) if self._sloop else self._bctl("loop_off")
            elif k == self._idx + 1:
                self._bctl("loop_off")
            else:
                self._bctl("jump", at=b, to=self._plan[k]["at"])
        except Exception as e:
            log.warning(f"backing (saut) : {e}")

    def _beat_s(self):
        cur = self._plan[self._idx] if 0 <= self._idx < len(self._plan) else None
        if not cur or not cur["bars"]:
            return 0.5
        return cur["dur"] / (cur["bars"] * max(1, cur["num"]))

    def _cue_locked(self):
        """Un temps avant la frontière, le saut est armé : ni mise en attente ni annulation (§6.2)."""
        _a, b = self._cur_bounds()
        if b is None or not self._live or self._counting:
            return False
        return (b - self._song_time()) < self._beat_s()

    def cue(self, index):
        """Met la section `index` en attente pour la fin de la section en cours (None = annuler)."""
        if not (self._live and not self._counting and self._plan and 0 <= self._idx < len(self._plan)):
            return {"ok": False, "error": "the song is not playing"}
        if index is not None and not (isinstance(index, int) and 0 <= index < len(self._plan)):
            return {"ok": False, "error": "no such section"}
        if self._mode == "foot" and self._with_backing:
            return {"ok": False, "error": "this song advances at the foot — its backing track cannot jump"}
        if self._mode != "foot" and self._cue_locked():
            return {"ok": False, "error": "too late — the jump is already armed", "locked": True}
        self._cue = index
        if self._mode != "foot":
            self._arm_backing()
        self._on_change()
        return {"ok": True, "cue": self._cue}

    def set_loop(self, on):
        """Boucle la section en cours (§6.3)."""
        if not (self._live and not self._counting and 0 <= self._idx < len(self._plan)) or self._mode == "foot":
            return {"ok": False, "error": "the song is not playing"}
        if self._cue_locked():
            return {"ok": False, "error": "too late — the end of the section is already armed", "locked": True}
        self._sloop = bool(on)
        self._loops = 0
        if on:
            self._cue = None                       # le dernier geste gagne : boucler annule une mise en attente
        self._arm_backing()
        self._on_change()
        return {"ok": True, "loop": self._sloop}

    def clear_practice(self):
        """Changement de mode ou de preset : une boucle ou un cue oubliés ne survivent pas (§6.3 bis)."""
        had = self._cue is not None or self._sloop
        self._cue, self._sloop, self._loops = None, False, 0
        if had and self._armed():
            try:
                self._bctl("loop_off")
            except Exception as e:
                log.warning(f"backing (boucle) : {e}")
        if had:
            self._on_change()

    # ── état publié (WS) ──
    def snapshot(self):
        cur = self._plan[self._idx] if 0 <= self._idx < len(self._plan) else None
        nxt = self._plan[self._idx + 1] if 0 <= self._idx + 1 < len(self._plan) else None
        return {
            "present": bool(self._plan),
            "allowed": bool(self._allowed()),
            "running": self._live or self._counting,
            "counting": self._counting,
            "done": self._done,
            "mode": self._mode,
            "live_view": self._live_view,
            "index": self._idx,
            "count": len(self._plan), "marks": len(self._marks),
            "name": cur["name"] if cur else None,
            "next": nxt["name"] if nxt else None,
            "scene": cur["scene"] if cur else None,
            "broken": bool(cur and cur["broken"]),
            "sig": f"{cur['num']}/{cur['den']}" if cur else None,
            # bornes de la section COURANTE, en horloge serveur. On publie les DEUX : une barre
            # de progression qui ne connaît que sa fin devrait deviner sa durée — et mentirait.
            "started_at": self._t0 or None,
            # bornes du DÉCOMPTE (horloge serveur) : le HUD de la page chanson compte les temps dessus
            "count_from": self._c0 if self._counting else None,
            "count_to": (self._c0 + getattr(self, "_count_s", 0)) if self._counting else None,
            "sec_from": (self._t0 + cur["at"]) if cur and self._t0 else None,
            "sec_to": (self._t0 + cur["at"] + cur["dur"]) if cur and self._t0 else None,
            "bars": cur["bars"] if cur else None,
            # le RAIL du téléphone (docs/devices-people.md, lot F) : les parties, leur scène et leur longueur
            "parts": [{"name": x["name"], "bars": x["bars"], "scene": x["scene"], "dur": round(x["dur"], 3),
                       "at": round(x["at"], 3), "num": x["num"], "den": x["den"]} for x in self._plan],
            "by": self._by,
            "backing": self._with_backing,          # la backing est partie avec le morceau
            "clock": self._clock,
            "starts": dict(getattr(self, "_starts", None) or {}),   # les cases du morceau en cours
            "bar_map": bool(getattr(self, "_bars", None)),            # parties calées sur la carte des mesures                    # « transport » (backing) | « server » — qui donne le temps
            # les gestes de répète (docs/live-pages.md §6.4)
            "cue": self._cue, "loop": self._sloop, "loops": self._loops, "from": self._from,
            "song_len": round(sum(x["dur"] for x in self._plan), 3) if self._plan else 0.0,
            "song_t0": self._t0 or None,          # origine du temps du morceau (horloge serveur) : pos = now − song_t0
        }

    # ── transport ──
    def load(self, preset):
        """Prépare (sans jouer) : le pupitre montre la structure avant qu'on lance quoi que ce soit."""
        self.stop(silent=True)
        self._plan = plan(preset)
        self._marks = sample_marks(preset)
        _pm = (block_of(preset) or {}).get("params") or {}
        self._mode = _pm.get("advance") or "bars"
        self._live_view = _pm.get("live_view") or None
        self._idx = -1
        self._done = False
        self._reset_practice()
        self._on_change()

    def start(self, preset, by=None, from_idx=None):
        self.stop(silent=True)
        self._starts = starts_of(preset)
        # LA CARTE DES MESURES (docs/bars-format.md) ne vaut que si la backing PART avec le morceau : c'est sa
        # timeline qu'elle décrit. Sans backing, le tempo de la fiche (rien d'autre à suivre).
        from . import bars as _bars
        self._bars = _bars.for_preset(preset) if self._starts.get("backing") is not False else None
        self._plan = plan(preset, self._bars)
        # case Sample décochée pour ce morceau : ses marqueurs ne partent pas
        self._marks = [] if self._starts.get("sample") is False else sample_marks(preset, self._bars)
        pm = (block_of(preset) or {}).get("params") or {}
        self._mode = pm.get("advance") or "bars"
        self._live_view = pm.get("live_view") or None
        self._bpm = (preset or {}).get("bpm") or 120
        self._idx = -1
        self._done = False
        if not self._plan:
            self._on_change()
            return {"ok": False, "error": "no arrangement in this preset"}
        if not self._allowed():
            self._on_change()
            return {"ok": False, "error": "the arrangement is off in this mode"}
        ci = count_in_seconds(preset)
        # ── PARTIR D'UNE SECTION (docs/live-pages.md §6.1) : `from_idx` = la page Répète. Décompte = max(celui du
        # morceau, 1 mesure, 2 mesures si une mesure dure moins de 2 s), dans la métrique — et la durée RÉELLE — de
        # la section de départ ; la backing est positionnée AVANT le décompte, pour sortir le seek du chemin critique.
        self._reset_practice()
        if from_idx is not None:
            if not (isinstance(from_idx, int) and 0 <= from_idx < len(self._plan)):
                self._on_change()
                return {"ok": False, "error": "no such section"}
            k = self._plan[from_idx]
            bar_s = (k["dur"] / k["bars"]) if k["bars"] else (k["num"] * (4.0 / k["den"]) * 60.0 / ((preset or {}).get("bpm") or 120))
            song_bars = int((((block_of(preset) or {}).get("params") or {}).get("count_in")) or 0)
            ci = max(song_bars, 1, 2 if bar_s < 2.0 else 1) * bar_s
            self._from = from_idx
            if k["at"] > 0 and self._starts.get("backing") is not False:
                try:
                    self._bctl("pause")                # une backing qui joue déjà : sinon elle jouerait pendant le décompte
                    self._bctl("seek", pos=k["at"])
                except Exception as e:
                    log.warning(f"backing (position de départ) : {e}")
        self._drm = {"on": False, "idx": None, "off": self._starts.get("drums") is False}
        self._count_s = ci
        # le décompte se joue DANS la mesure de la section de départ (§9) : posée avant tout ordre au click
        self._send_meter(self._plan[self._from], push=False)
        self._click_ev("start", self._starts.get("click"))
        self._live = True
        self._by = by
        self._task = asyncio.ensure_future(self._run(ci))
        try:
            self._on_song("start", {"by": by, "preset": (preset or {}).get("id"),
                                    "record": self._starts.get("rec"), "backing": self._starts.get("backing"),
                                    "count_in": ci})
        except Exception as e:
            log.warning(f"début de morceau : {e}")
        return {"ok": True, "sections": len(self._plan), "count_in": ci, "mode": self._mode}

    def stop(self, silent=False):
        was = self._live or self._counting
        if self._task:
            self._task.cancel()
            self._task = None
        if self._counting:
            self._counting = False
            if self._click_song:
                self._click_ev("cancel")
            else:
                self._click_hold(False)
        elif was:
            self._click_ev("stop")
        self._send_meter(None)                     # le click retrouve SA mesure (config, ligne)
        self._drums_stop()
        self._live = False
        self._idx = -1
        self._done = False
        if self._with_backing:
            try:
                self._bctl("loop_off")                 # une boucle native oubliée (même après un saut consommé) ferait tourner la backing en rond
            except Exception as e:
                log.warning(f"backing (boucle) : {e}")
        self._reset_practice()
        if self._with_backing:                     # on n'arrête que la backing qu'on a lancée
            self._with_backing = False
            try:
                self._backing(False)
            except Exception as e:
                log.warning(f"arrêt de la backing : {e}")
        if was:
            try:
                self._on_song("end", {"done": False})
            except Exception as e:
                log.warning(f"fin de morceau : {e}")
        if not silent:
            self._on_change()

    def next(self):
        """Mode `foot` : un appui = une section. Refusé en mode `bars` — deux maîtres, non."""
        if self._mode != "foot" or not self._plan:
            return {"ok": False, "error": "not in foot mode"}
        if self._cue is not None:                  # une section mise en attente : c'est elle, au prochain appui
            self._idx, self._cue = self._cue, None
            self._fire(self._plan[self._idx])
            self._on_change()
            return {"ok": True, "index": self._idx}
        if self._idx + 1 >= len(self._plan):
            self._done = True                      # règle 3 : la dernière section TIENT
            self._on_change()
            return {"ok": True, "done": True}
        self._idx += 1
        self._fire(self._plan[self._idx])
        self._on_change()
        return {"ok": True, "index": self._idx}

    # ── interne ──
    def _click_ev(self, ev, *args):
        if not self._click_song:
            return
        try:
            self._click_song(ev, *args)
        except Exception as e:
            log.warning(f"click du morceau ({ev}) : {e}")

    def _song_time(self):
        """Secondes écoulées depuis le premier temps de la section 1, selon le MAÎTRE de l'horloge (§5).

        Backing qui joue et état publié APRÈS son départ : pos + (maintenant − at). En pause : pos, figé —
        l'arrangement attend avec elle. Sinon (pas de backing, état pas encore frais, backing finie ou
        arrêtée ailleurs) : l'horloge du serveur, PROLONGÉE depuis la dernière estimation — on ne saute pas.
        `_t0` suit l'estimation : le HUD (sec_from/sec_to) reste juste, pause comprise."""
        now = time.time()
        tr = None
        if self._follow:
            try:
                tr = self._transport()
            except Exception:
                tr = None
        if tr and now < self._quiet_until:
            tr = None                              # juste après un saut : l'état publié peut être d'avant (§6.2)
        if tr and tr.get("present") and (tr.get("at") or 0) > max(self._bk_t, self._quiet_until - JUMP_QUIET_S) \
                and (tr.get("playing") or tr.get("paused")):
            pos = float(tr.get("pos") or 0.0)
            st = pos if tr.get("paused") else pos + max(0.0, now - float(tr["at"]))
            self._clock = "transport"
            t0 = now - st
            moved = abs(t0 - self._t0) > HUD_SHIFT_S
            self._t0 = t0
            if moved:
                self._on_change()
            return st
        return now - self._t0

    def _fire_sample(self, m):
        """Un marqueur de la lane. Pré-armé : on passe `at_ms` (le délai restant) pour que
        Reaper déclenche à l'échantillon près, et `ring` pour ne PAS couper ce qui sonne
        (§18 : la monophonie est la loi du PIED, pas celle de la lane)."""
        try:
            left = max(0.0, (self._t0 + m["at"]) - time.time())
            self._apply_sample({"block": m["block"], "idx": m["idx"], "samples": m["samples"],
                                "in_ms": round(left * 1000.0), "ring": bool(m.get("ring")) and not self._jumped})
        except Exception as e:
            log.warning(f"sample « {m.get('name') or m['block']} » a échoué : {e}")

    def _meter_of(self, sec):
        """Ce que le click reçoit pour `sec` : sa mesure ({beats, den, groups}, absente = celle du click) ET l'ancre
        de phase (`anchor`, click_anchor) — None = rien (le click retrouve sa mesure, sans ancre)."""
        if not sec:
            return None
        m = sec.get("click")
        a = click_anchor(self._plan, sec["i"]) if isinstance(sec.get("i"), int) else None
        if a is None:
            return m
        return dict(m or {}, anchor=a)

    def _send_meter(self, sec, push=True):
        """Confie au click la mesure de `sec` (None = la sienne) — rien si c'est déjà elle."""
        m = self._meter_of(sec)
        if m == self._meter_sent:
            return
        self._meter_sent = m
        try:
            self._click_meter(m, push)
        except Exception as e:
            log.warning(f"mesure du click : {e}")

    def _pulse_s(self, sec):
        """Durée d'une pulsation de `sec` (sa durée réelle quand la carte des mesures la donne)."""
        if sec.get("bars") and sec.get("dur"):
            return sec["dur"] / (sec["bars"] * max(1, sec["num"]))
        return (4.0 / sec["den"]) * 60.0 / (self._bpm or 120)

    def _premeter(self, nxt, cur, left):
        """La mesure de la section suivante part PENDANT LA DERNIÈRE PULSATION de la section en cours, à sa moitié.
        Le JSFX ne recale pas sa phase à un changement de mesure (seul un front 0->1 le fait, et il ferait un « 1 »
        en trop) : reçue après le dernier temps et avant la frontière, la mesure trouve son compteur sur le « 1 »
        à venir, et la frontière tombe juste — à une demi-pulsation de tolérance sur la latence de la commande
        (~30 ms de gigue). Envoyée APRÈS la frontière, la 2e pulsation garderait l'ancienne durée : tout le reste
        de la section décalée — sauf transport en lecture, où l'ANCRE (click_anchor) arrivée moins d'une
        demi-pulsation après la frontière recale le JSFX (docs/arrangement.md §4). Vers la cible d'un saut, l'ancre
        part ici aussi : le JSFX ne s'en sert qu'au saut lui-même. Rend le délai avant l'envoi, ou None."""
        if nxt is None or cur is None or self._meter_of(nxt) == self._meter_sent:
            return None
        half = self._pulse_s(cur) / 2.0
        if left <= half:
            self._send_meter(nxt)
            return None
        return left - half

    # ── la batterie du morceau ──
    def _drums_call(self, op, idx=None):
        try:
            return self._drums(op, idx=idx)
        except Exception as e:
            log.warning(f"batterie du morceau ({op}) : {e}")
            return False

    def _drums_go(self, k):
        """Premier temps : la batterie part sur le groove de la section de départ (sauf « stop » ou case décochée)."""
        if self._drm["off"]:
            return
        v = drums_at(self._plan, k)
        if v == "stop":
            return
        if self._drums_call("play", v) is False:
            self._drm["off"] = True                # pas de boîte à rythmes dans ce preset : on n'insiste plus
            return
        self._drm.update(on=True, idx=v)

    def _drums_at(self, sec):
        """À la frontière : ce que la section demande, si ce n'est pas déjà fait (groove pré-envoyé par _predrums)."""
        if self._drm["off"] or not isinstance(sec.get("i"), int):
            return
        v = drums_at(self._plan, sec["i"])
        if v == "stop":
            if self._drm["on"]:
                self._drums_call("stop")
                self._drm.update(on=False, idx=None)
        elif not self._drm["on"]:
            if self._drums_call("play", v) is not False:
                self._drm.update(on=True, idx=v)
        elif self._drm["idx"] != v:                # pas pré-envoyé (saut, pied) : il tombera à la mesure suivante
            self._drums_call("pattern", v)
            self._drm["idx"] = v

    def _predrums(self, nxt, cur, left):
        """Le groove de la section suivante part PENDANT LA DERNIÈRE PULSATION, à sa moitié (même règle que la mesure
        du click, _premeter) : le JSFX bascule à la mesure suivante, donc pile sur la frontière. Rend le délai avant
        l'envoi, ou None."""
        if self._drm["off"] or not self._drm["on"] or nxt is None or cur is None:
            return None
        v = drums_at(self._plan, nxt["i"])
        if v == "stop" or v == self._drm["idx"]:
            return None
        half = self._pulse_s(cur) / 2.0
        if left <= half:
            self._drums_call("pattern", v)
            self._drm["idx"] = v
            return None
        return left - half

    def _drums_stop(self):
        if self._drm.get("on"):
            self._drums_call("stop")
        self._drm.update(on=False, idx=None)

    def _fire(self, sec):
        self._send_meter(sec)                      # déjà partie si la frontière était prévue (_premeter)
        self._drums_at(sec)
        # règle 2 : la scène est RÉAPPLIQUÉE à chaque frontière -> l'arrangement se répare tout
        # seul quand un musicien l'a contredit au pied entre-temps.
        try:
            self._apply(sec)
        except Exception as e:                     # une cue qui rate ne doit pas tuer le morceau
            log.warning(f"cue « {sec.get('name')} » a échoué : {e}")

    def _prearm_target(self, k, until_s):
        """Pré-arme les samples du DÉBUT de la section cible (§15) : la boucle native saute à l'échantillon, un sample
        lancé après le saut (retard + tick + commande, 50 à 100 ms) ferait un flam."""
        a = self._plan[k]["at"]
        for m in self._marks:
            if a <= m["at"] < a + PREARM_S and id(m) not in self._prearmed:
                self._prearmed.add(id(m))
                try:
                    self._apply_sample({"block": m["block"], "idx": m["idx"], "samples": m["samples"],
                                        "in_ms": round((max(0.0, until_s) + (m["at"] - a)) * 1000.0), "ring": False})
                except Exception as e:
                    log.warning(f"sample pré-armé « {m.get('name') or m['block']} » : {e}")

    @staticmethod
    def _next_ev(evs, j, st):
        """Le premier événement à venir quand le morceau est à `st` dans la section `j` : les sections après `j`, les
        samples dont la marque est à `st` ou après, la fin."""
        return next((k for k, e in enumerate(evs)
                     if (e["kind"] == "sec" and e["sec"]["i"] > j)
                     or (e["kind"] == "smp" and e["mark"]["at"] >= st - 1e-6) or e["kind"] == "end"), len(evs))

    def _jump(self, k, late):
        """À la frontière : le moteur applique LUI-MÊME la section `k` et recale son origine (§6.2) — le saut audio,
        lui, est fait par Reaper (armé à la mise en attente). Le retard sur la frontière est conservé."""
        now = time.time()
        late = max(0.0, late)
        lap = self._cue is None                   # pas de cue : c'est un tour de boucle
        self._t0 = now - (self._plan[k]["at"] + late)
        if self._follow:
            self._quiet_until = now + JUMP_QUIET_S
        if lap:
            self._loops += 1
        else:
            self._cue, self._sloop, self._loops = None, False, 0
        self._jumped = True
        self._prev_st = None                       # une discontinuité VOULUE : pas de recalage sur elle
        log.info(f"{'tour de boucle' if lap else 'saut'} : « {self._plan[k]['name']} »")
        self._idx = k
        self._fire(dict(self._plan[k], _lap=True))
        self._on_change()

    async def _run(self, count_in):
        try:
            if count_in > 0:
                # §13 : le décompte est TOUJOURS audible, même quand le click est silencieux —
                # c'est sa seule raison d'être. On le force, puis on rend la main.
                self._counting = True
                self._c0 = time.time()
                self._click_hold(True)
                self._on_change()
                await asyncio.sleep(count_in)
                self._counting = False
                if not self._click_song:
                    self._click_hold(False)
            # partir d'une section (docs/live-pages.md §6.1) : le temps du morceau commence à `at[from]`
            k0 = self._from if 0 <= self._from < len(self._plan) else 0
            offset = self._plan[k0]["at"] if k0 else 0.0
            self._t0 = time.time() - offset
            self._click_ev("go", self._starts.get("click"))
            self._drums_go(k0)
            self._bk_t = time.time()
            self._clock = "server"
            self._follow = False
            try:
                if self._starts.get("backing") is not False:
                    _r = self._backing(True, offset) if offset else self._backing(True)
                else:
                    _r = False
                self._with_backing = bool(_r)
                self._follow = _r is True          # « free » : lancée mais pas suivie (prise perf-rec)
            except Exception as e:
                log.warning(f"départ de la backing : {e}")
            if self._mode == "foot":
                self._idx = k0                     # la 1re section (ou celle de départ) part avec le morceau
                self._fire(self._plan[k0])
                self._on_change()
                self._task = None
                return                             # la suite vient des appuis, pas du temps
            # ── FUSION sections + samples en UNE file d'événements datés (§14) ──
            # La boucle dormait jusqu'à UNE date (la frontière suivante) ; elle dort maintenant
            # jusqu'à la PROCHAINE ÉCHÉANCE, quelle qu'en soit la nature. Les samples sont
            # PRÉ-ARMÉS (§15) : on les émet PREARM_S en avance, avec l'instant exact — la gigue
            # de ~30 ms du chemin de commande devient une MARGE, plus une erreur.
            evs = [{"t": s2["at"], "kind": "sec", "sec": s2} for s2 in self._plan]
            evs += [{"t": max(0.0, m["at"] - PREARM_S), "kind": "smp", "mark": m}
                    for m in self._marks]
            evs.sort(key=lambda e: (e["t"], 0 if e["kind"] == "smp" else 1))
            # ── LA FIN DU MORCEAU = la fin de la DERNIÈRE partie, pas son début (2026-10-07). « Done » tombait
            # quand la dernière partie COMMENÇAIT : une prise « Record with the song » s'arrêtait donc au début de
            # l'outro. La dernière scène TIENT toujours (règle 3) ; c'est le morceau qui est fini.
            _last = self._plan[-1]
            evs.append({"t": _last["at"] + _last["dur"], "kind": "end"})
            # ── LA BOUCLE SUIT LE TEMPS DU MORCEAU, pas l'horloge murale (§5, lot 2 du 2026-10-07) ──
            # Sans backing, le temps du morceau EST l'horloge du serveur : une seule attente par
            # échéance, comme avant. Avec une backing, il vient du transport — on dort donc par petites
            # tranches et on relit : une PAUSE de la backing retient l'arrangement, un RETOUR en arrière
            # (double-tap restart, seek) le recale sur la partie où l'on est revenu.
            # départ depuis une section : ce qui est avant est sauté — un sample dont la MARQUE tombe avant le point de
            # départ ne part pas (lancé au milieu : attaque coupée, clic — §6.1)
            i = self._next_ev(evs, k0 - 1, offset)
            while i < len(evs):
                st = self._song_time()
                cur = self._plan[self._idx] if 0 <= self._idx < len(self._plan) else None
                prev, self._prev_st = self._prev_st, st
                tgt = self._cue if self._cue is not None else (self._idx if self._sloop else None)
                jumping = cur is not None and tgt is not None and tgt != self._idx + 1 and self._mode != "foot"
                b_cur = (cur["at"] + cur["dur"]) if cur else None
                # ── LE SAUT ARMÉ EST DÉJÀ FAIT DANS REAPER (relecture de l'ingénieur du son) : le Lua publie le rebouclage
                # tout de suite, le bridge le lit à 10 Hz — on peut le voir AVANT d'avoir atteint la frontière nous-mêmes.
                # Une discontinuité qui tombe sur la cible, juste après la fin de la section : c'est NOTRE saut.
                if (jumping and self._clock == "transport" and prev is not None and abs(st - prev) > 0.2
                        and b_cur - 1.0 < prev < b_cur + FORWARD_S and abs(st - self._plan[tgt]["at"]) < 0.6):
                    self._jump(tgt, st - self._plan[tgt]["at"])
                    i = self._next_ev(evs, self._idx, self._plan[self._idx]["at"])
                    continue
                # ── RECALAGE : le transport est revenu en arrière (double-tap restart, seek, boucle native) ou parti en
                # avant (saut raté, seek de quelqu'un) — on reprend là où il EST. Une section déjà en cours ne se rejoue pas.
                if self._clock == "transport" and cur and (st < cur["at"] - REWIND_S
                                                          or st > cur["at"] + cur["dur"] + FORWARD_S):
                    j = max([k for k, x in enumerate(self._plan) if x["at"] <= st] or [0])
                    log.info(f"transport à {st:.1f} s : on reprend à « {self._plan[j]['name']} »")
                    if self._cue is not None or self._sloop:
                        self.clear_practice()      # quelqu'un a déplacé la backing : la boucle et le cue n'ont plus de sens
                    if j != self._idx or st < cur["at"] - REWIND_S:
                        self._idx = j
                        self._fire(dict(self._plan[j], _lap=True))
                        self._on_change()
                    i = self._next_ev(evs, j, st)
                    continue
                # ── UN SEEK DANS LA SECTION pendant qu'un saut est armé : golem_backing lève le saut à tout seek (il
                # n'appartient qu'à la lecture où on l'a armé) — sans réarmement, la scène sauterait à la frontière et
                # l'audio continuerait sur la section suivante (relecture du 2026-10-15). On le repose tel quel.
                if (jumping and self._clock == "transport" and prev is not None and abs(st - prev) > 0.2
                        and self._cue is not None):
                    log.info(f"seek à {st:.1f} s dans la section : saut vers « {self._plan[tgt]['name']} » réarmé")
                    self._arm_backing()
                # ── LA MESURE DE LA SECTION SUIVANTE (ou de la cible du saut) part avant la frontière (_premeter)
                nxt = (self._plan[tgt] if jumping else
                       (self._plan[self._idx + 1] if cur is not None and self._idx + 1 < len(self._plan) else None))
                early = self._premeter(nxt, cur, b_cur - st) if b_cur is not None else None
                early_d = self._predrums(nxt, cur, b_cur - st) if b_cur is not None else None
                if early_d is not None:
                    early = early_d if early is None else min(early, early_d)
                ev = evs[i]
                # ── UN SAUT EST PRÉVU à la fin de la section en cours (cue, ou boucle — §6.2, §6.3) ──
                if jumping and b_cur - st <= PREARM_S:
                    self._prearm_target(tgt, b_cur - st)
                if jumping and ev["kind"] == "smp" and ev["mark"]["at"] >= b_cur - 1e-6:
                    i += 1                         # la suite ne jouera pas : ses samples pré-armés non plus
                    continue
                if jumping and ((ev["kind"] == "sec" and ev["sec"]["i"] == self._idx + 1) or ev["kind"] == "end"):
                    wait = b_cur - st
                    if wait > 0:
                        await asyncio.sleep(min(wait, early or wait, CLOCK_TICK_S if self._follow else 0.1))
                        continue
                    self._jump(tgt, st - b_cur)
                    i = self._next_ev(evs, self._idx, self._plan[self._idx]["at"])
                    continue
                wait = ev["t"] - st
                if wait > 0:
                    # au plus 0,1 s de sommeil, même sans backing : un cue posé pendant l'attente doit être vu
                    await asyncio.sleep(min(wait, early or wait, CLOCK_TICK_S if self._follow else 0.1))
                    continue
                i += 1
                if ev["kind"] == "end":
                    break
                if ev["kind"] == "smp":
                    if id(ev["mark"]) in self._prearmed:
                        self._prearmed.discard(id(ev["mark"]))   # déjà pré-armé pour le saut
                        continue
                    self._fire_sample(ev["mark"])
                    continue
                sec = ev["sec"]
                self._idx = sec["i"]
                self._jumped = False                   # une frontière normale : les samples retrouvent leur `ring`
                self._prearmed.clear()
                if self._cue == sec["i"]:          # la section mise en attente était la suivante : rien à sauter
                    self._cue, self._sloop, self._loops = None, False, 0
                self._fire(sec)
                self._on_change()
            # règle 3 : on ne boucle pas, on ne coupe rien — la dernière section TIENT.
            self._done = True
            self._task = None
            # le morceau est FINI : il repasse à l'arrêt (le tap suivant le relance). La dernière scène tient (règle 3) ;
            # la backing finit d'elle-même — on ne coupe pas sa queue.
            self._live = False
            self._click_ev("stop")                 # le morceau est fini : le click qu'il a lancé se tait
            self._drums_stop()                     # …et la batterie qu'il a lancée
            self._send_meter(None)
            try:
                self._on_song("end", {"done": True})
            except Exception as e:
                log.warning(f"fin de morceau : {e}")
            self._on_change()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error(f"moteur arrêté : {e}")
            self._task = None
            self._on_change()
