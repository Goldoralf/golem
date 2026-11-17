# SPDX-License-Identifier: GPL-3.0-or-later
"""LE BUDGET CPU D'UN PRESET (docs/cpu-budget.md, lot 1) : ce preset jouera-t-il sur CE golem ?

Deux étages :
  · le CŒUR, pur (aucune lecture de fichier) : un plan compilé par scène (les pistes que golem_rig pose, avec l'état
    on/off de chaque bloc) + le profil mesuré par le banc (bridge/cpu_bench.py, config/cpu-profile.json) -> la
    réponse `estimate` du contrat (§9). Testable avec des plans faits à la main.
  · les BORDS (en bas du fichier) : bâtir ces plans depuis un preset (le chemin du rappel : scene_bake union + rig),
    lire la variante d'une capture NAM (son architecture) ou la longueur d'une IR, lister les captures plus légères.

Le modèle (§1, décidé ici) : une lane = ses pistes REAPER. Les blocs d'une piste s'enchaînent sur UN cœur ; les
branches d'un split sont des pistes qui tournent en parallèle ; le merge attend toutes ses branches. Dans un buffer,
une lane doit donc finir son CHEMIN CRITIQUE : pré + la plus lourde des branches + post (merge). C'est ce chemin
qui se compare au budget d'un cœur pour un buffer (buffer / srate). Un bloc bypassé ne coûte rien ; une branche
coupée par la scène (D_MUTE) COMPTE, par prudence : on ne suppose pas que REAPER saute les FX d'une piste muette
(c'est une préférence, pas vérifiée au rack).
Conséquence assumée : « déplacer la fin de la chaîne dans une branche » ne raccourcit pas ce chemin (la branche
attend toujours la pré) — la proposition `split` du §4 n'est donc pas émise, faute de gain à annoncer.
"""
import hashlib
import json
import logging
import os
import statistics
import struct
import threading

# ok ≤ 60 %, tight ≤ 80 %, red au-delà (§9 : UNE constante)
THRESHOLDS = {"ok": 60.0, "tight": 80.0}

NAM_TYPES = ("amp", "amp-nam", "pedal-nam", "preamp-nam", "comp-nam")    # tous joués par le moteur NAM
IR_TYPES = ("cab", "ir-fx")                                             # convolveurs x42 : le coût suit la longueur
IR_BUCKETS_MS = (50, 100, 200, 500, 1000, 2000, 5000)                   # bornes hautes ; au-delà « long »
# les instruments jouent des NOTES : leur coût dépend de ce qu'on joue (voix de Vital, kit, piano) — pas de mesure
# par type honnête au lot 1, ils restent « non mesurés »
INSTRUMENT_TYPES = ("vital", "pads", "drumkit", "organ", "piano", "ep")
FREE_ENGINES = ("midi", "virtual", "mode")                              # aucun FX posé : coût nul
# la taille du réseau WaveNet (couches : canaux, tête, nombre de dilatations) -> le nom que lui donne l'entraîneur NAM
WAVENET_SIZES = {((16, 8, 10), (8, 1, 10)): "standard", ((12, 6, 7), (6, 1, 13)): "lite",
                 ((8, 4, 7), (4, 1, 13)): "feather", ((4, 2, 7), (2, 1, 13)): "nano"}
FIX_ORDER = ("perf-mode", "turn-off", "lighter-capture", "buffer", "too-heavy")


# ── le profil ─────────────────────────────────────────────────────────────────────────────────────────────────────
def profile_key(kind, variant=None, stereo=True):
    """« <type>[:<variant>]|mono|stereo » — la clé d'une mesure (§9)."""
    return f"{kind}{':' + str(variant) if variant else ''}|{'stereo' if stereo else 'mono'}"


def lookup(profile, kind, variant=None, stereo=True):
    """La mesure d'un composant, ou None. Le banc mesure l'instance STÉRÉO : une piste REAPER a deux canaux et un
    plugin y traite les deux, que la lane soit mono (entrée mono posée sur 1+2) ou stéréo. La clé « mono » se replie
    donc sur la stéréo (et inversement), sans être inventée."""
    blocks = (profile or {}).get("blocks") or {}
    return blocks.get(profile_key(kind, variant, stereo)) or blocks.get(profile_key(kind, variant, not stereo))


def entry_us(entry, bsize):
    """Le coût d'une mesure pour UN buffer de `bsize` échantillons, en µs. Deux parts : le calcul, proportionnel au
    nombre d'échantillons (mesuré à entry.bsize), et l'écart du pire tour au tour moyen, fixe par buffer — c'est lui
    qu'un plus grand buffer absorbe (fix « buffer »)."""
    avg = float(entry.get("avg_us") or 0.0)
    worst = max(avg, float(entry.get("worst_us") or avg))
    eb = entry.get("bsize")
    scale = (float(bsize) / float(eb)) if eb and bsize else 1.0
    return avg * scale + (worst - avg)


def budget_us(bsize, srate):
    return (float(bsize) / float(srate)) * 1e6 if bsize and srate else None


def block_us(components, stereo, profile, bsize):
    """Coût d'un bloc (somme de ses composants), ou None si l'un n'est pas mesuré. [] = gratuit (mesuré, 0)."""
    total = 0.0
    for kind, variant in components or []:
        e = lookup(profile, kind, variant, stereo)
        if e is None:
            return None
        total += entry_us(e, bsize)
    return total


def block_off_us(components, stereo, profile, bsize):
    """Ce qu'un bloc ÉTEINT coûte encore (0 si rien n'a été mesuré éteint : REAPER, ou un profil d'avant). Sous le Golem
    Engine un plugin qui porte son propre bypass continue de tourner : le banc le mesure (`off_us`, cpu_bench)."""
    total = 0.0
    for kind, variant in components or []:
        e = lookup(profile, kind, variant, stereo)
        off = float((e or {}).get("off_us") or 0.0)
        eb = (e or {}).get("bsize")
        total += off * ((float(bsize) / float(eb)) if eb and bsize else 1.0)
    return total


def _verdict_of(pct):
    if pct is None:
        return "unknown"
    if pct > THRESHOLDS["tight"]:
        return "red"
    if pct > THRESHOLDS["ok"]:
        return "tight"
    return "ok"


def _r(x, n=1):
    return None if x is None else round(float(x), n)


# ── une lane, une scène ──────────────────────────────────────────────────────────────────────────────────────────
def _track_cost(track, cost_of, skip=None, off_of=None):
    """(µs des blocs ON mesurés, un bloc ON non mesuré ?, travail total) d'une piste dans une scène. `off_of` : ce qu'un
    bloc éteint coûte encore — jamais sur une branche muette, que le moteur endort (ses plugins désactivés : 0 µs)."""
    us, unknown = 0.0, False
    for b in track.get("blocks") or []:
        if skip and b.get("id") in skip:
            continue
        if b.get("bypass"):
            if off_of and not (track.get("role") == "branch" and track.get("mute") is True):
                us += off_of(b)
            continue
        c = cost_of(b)
        if c is None:
            unknown = True
        else:
            us += c
    return us, unknown


def lane_path_us(tracks, cost_of, skip=None, off_of=None):
    """(chemin critique en µs, inconnu ?, travail total en µs) — pré + max(branches) + merge/post."""
    serial, branches, unknown, work = 0.0, [], False, 0.0
    for t in tracks or []:
        us, unk = _track_cost(t, cost_of, skip, off_of)
        unknown = unknown or unk
        work += us
        if t.get("role") == "branch":
            branches.append(us)
        else:                                            # main, pre, merge : en série
            serial += us
    return serial + (max(branches) if branches else 0.0), unknown, work


# ── l'estimation (§9) ────────────────────────────────────────────────────────────────────────────────────────────
def estimate(scene_plans, profile, machine=None, alternatives=None, bsizes=None):
    """Le cœur pur. `scene_plans` : [(scene_id, plan)] dans l'ordre des scènes ; un plan = {paths: [{id, name, stereo?,
    tracks: [{role, blocks: [{id, type, bypass, _cpu: [[kind, variant]…], _label, _silent?}]}]}]} (rig.build_plan
    annoté par `annotate`). `profile` : config/cpu-profile.json. `machine` : l'état COURANT {cpu, cores, governor,
    srate, bsize} (le buffer et la fréquence d'aujourd'hui, pas forcément ceux de la mesure). `alternatives` :
    {block id: [{ref, model, variant, name}]} — les captures plus légères du même ampli. Rend le JSON du contrat."""
    profile = profile or {}
    pm = profile.get("machine") or {}
    machine = dict(machine or {})
    bsize = machine.get("bsize") or pm.get("bsize")
    srate = machine.get("srate") or pm.get("srate")
    budget = budget_us(bsize, srate)
    lanes, order = {}, []

    def cost_for(stereo, at_bsize=None):
        def f(b):
            return block_us(b.get("_cpu"), stereo, profile, at_bsize or bsize)
        return f

    def pct(us):
        return (us / budget * 100.0) if (budget and us is not None) else None

    # LA PART FIXE DU MOTEUR (profil du Golem Engine : `engine_idle`, mesurée lane vide) : ce que le moteur charge sans
    # un seul bloc. Ajoutée à chaque lane — le pourcentage affiché est alors celui que le moteur annonce en jouant.
    fixed_us = float(((profile or {}).get("engine_idle") or {}).get("us") or 0.0)

    def off_for(stereo):
        return lambda b: block_off_us(b.get("_cpu"), stereo, profile, bsize)

    scenes = [sid for sid, _p in scene_plans]
    total_by_scene = {}
    for sid, plan in scene_plans:
        total = 0.0
        for p in (plan or {}).get("paths") or []:
            lid = p.get("id")
            stereo = bool(p.get("stereo") or any(t.get("stereo") for t in p.get("tracks") or []))
            L = lanes.get(lid)
            if L is None:
                L = lanes[lid] = {"id": lid, "name": p.get("name") or lid, "stereo": stereo, "tracks": {},
                                  "blocks": {}, "border": [], "by_scene": {}, "unknown": {}}
                order.append(lid)
            L["tracks"][sid] = p.get("tracks") or []
            us, unk, work = lane_path_us(L["tracks"][sid], cost_for(stereo), off_of=off_for(stereo))
            L["by_scene"][sid], L["unknown"][sid] = us + fixed_us, unk
            total += work
            for t in p.get("tracks") or []:
                for b in t.get("blocks") or []:
                    bid = b.get("id")
                    if bid not in L["blocks"]:
                        L["blocks"][bid] = {"b": b, "on": {}}
                        L["border"].append(bid)
                    L["blocks"][bid]["on"][sid] = not b.get("bypass")
        total_by_scene[sid] = total

    out_lanes, worst = [], {"lane": None, "scene": None, "pct": None}
    verdicts = []
    for lid in order:
        L = lanes[lid]
        cost = cost_for(L["stereo"])
        by_scene = {sid: _r(pct(us)) for sid, us in L["by_scene"].items()}
        wsid = max(L["by_scene"], key=lambda s: L["by_scene"][s]) if L["by_scene"] else None
        lpct = pct(L["by_scene"][wsid]) if wsid is not None else 0.0
        v = _verdict_of(lpct)
        if v != "red" and any(L["unknown"].values()):
            v = "unknown"                                # un bloc non mesuré : on ne certifie pas (§9)
        verdicts.append(v)
        blocks = []
        for bid in L["border"]:
            e = L["blocks"][bid]
            c = cost(e["b"])
            blocks.append({"id": bid, "type": e["b"].get("type"), "label": e["b"].get("_label") or e["b"].get("type"),
                           "pct": _r(pct(c)), "stereo": L["stereo"], "measured": c is not None,
                           "on": {sid: e["on"].get(sid, False) for sid in scenes if sid in e["on"]}})
        out_lanes.append({"id": lid, "name": L["name"], "pct": _r(lpct), "worst_scene": wsid, "by_scene": by_scene,
                          "blocks": blocks, "verdict": v})
        if lpct is not None and (worst["pct"] is None or lpct > worst["pct"]):
            worst = {"lane": lid, "scene": wsid, "pct": lpct}
    if worst["pct"] is not None:
        worst["pct"] = _r(worst["pct"])
    if "red" in verdicts:
        verdict = "red"
    elif "unknown" in verdicts or budget is None:
        verdict = "unknown"
    elif "tight" in verdicts:
        verdict = "tight"
    else:
        verdict = "ok"
    tot = max(total_by_scene.values()) if total_by_scene else 0.0
    fixes = _fixes(lanes, order, out_lanes, profile, machine, alternatives or {}, bsize, srate, budget,
                   bsizes or (64, 96, 128, 192, 256, 384, 512)) if budget else []
    return {"verdict": verdict, "budget_us": _r(budget), "cores": machine.get("cores") or pm.get("cores"),
            "total_cores": round(tot / budget, 2) if budget else None, "worst": worst, "lanes": out_lanes,
            "fixes": fixes, "engine_pct": _r(pct(fixed_us)) if fixed_us else None,
            "machine": {"cpu": pm.get("cpu") or machine.get("cpu"), "governor": machine.get("governor") or pm.get("governor"),
                        "bsize": bsize, "srate": srate},
            "measured_at": profile.get("measured_at")}


# ── ce que golem propose (§4) ────────────────────────────────────────────────────────────────────────────────────
def _same_sound(a, b):
    keys = ("type", "ref", "model", "params", "plugin")
    return all(a.get(k) == b.get(k) for k in keys)


def _fixes(lanes, order, out_lanes, profile, machine, alternatives, bsize, srate, budget, bsizes):
    """Les propositions, la moins chère d'abord, chacune avec son gain estimé (points de % de la lane visée)."""
    fixes = []
    heavy = [ol for ol in out_lanes if ol["pct"] is not None and ol["pct"] > THRESHOLDS["ok"]]
    if not heavy:
        return []
    pm = profile.get("machine") or {}

    def pct_of(us):
        return us / budget * 100.0

    # 1. le gouverneur : le gain ne se mesure pas d'ici (le banc ne tourne que sous un gouverneur), donc null
    gov = machine.get("governor")
    if gov and gov != "performance":
        fixes.append({"id": "perf-mode", "title": "Turn on performance mode",
                      "sub": f"The CPU governor is “{gov}”: the processor slows down between bursts of work."
                             + (f" This golem was measured under “{pm.get('governor')}”." if pm.get("governor") else ""),
                      "gain_pct": None, "action": {"kind": "perf-mode", "on": True}})
    for ol in heavy:
        L = lanes[ol["id"]]
        sid = ol["worst_scene"]
        tracks = L["tracks"][sid]
        base_cost = (lambda st: (lambda b: block_us(b.get("_cpu"), st, profile, bsize)))(L["stereo"])
        base, _u, _w = lane_path_us(tracks, base_cost)
        # 2. un bloc que personne n'entend dans cette scène : allumé à mix 0, ou le même son posé deux fois
        for t in tracks:
            seen = []
            for b in t.get("blocks") or []:
                if b.get("bypass"):
                    continue
                dup = next((s for s in seen if _same_sound(s, b)), None)
                seen.append(b)
                if not (b.get("_silent") or dup):
                    continue
                after, _u, _w = lane_path_us(tracks, base_cost, skip={b.get("id")})
                gain = pct_of(base - after)
                if gain <= 0.05:
                    continue
                why = "it is on at mix 0" if b.get("_silent") else f"it doubles {dup.get('_label') or dup.get('id')}"
                fixes.append({"id": f"turn-off:{ol['id']}:{sid}:{b.get('id')}",
                              "title": f"Turn off {b.get('_label') or b.get('type')} in scene {sid}",
                              "sub": f"Nobody hears it: {why}.", "gain_pct": _r(gain),
                              "action": {"kind": "turn-off", "lane": ol["id"], "scene": sid, "block": b.get("id")}})
        # 3. une capture plus légère du même ampli (architecture NAM moins coûteuse, mesurée)
        for t in tracks:
            for b in t.get("blocks") or []:
                if b.get("bypass") or b.get("type") not in NAM_TYPES or not alternatives.get(b.get("id")):
                    continue
                cur = block_us(b.get("_cpu"), L["stereo"], profile, bsize)
                if cur is None:
                    continue
                best = None
                for alt in alternatives[b["id"]]:
                    comps = [c for c in (b.get("_cpu") or []) if c[0] != "nam"] + [["nam", alt.get("variant")]]
                    us = block_us(comps, L["stereo"], profile, bsize)
                    if us is not None and us < cur and (best is None or us < best[0]):
                        best = (us, alt, comps)
                if not best:
                    continue
                swapped = dict(b, _cpu=best[2])
                trk = [dict(tt, blocks=[swapped if x is b else x for x in tt.get("blocks") or []]) for tt in tracks]
                after, _u, _w = lane_path_us(trk, base_cost)
                gain = pct_of(base - after)
                if gain <= 0.05:
                    continue
                alt = best[1]
                fixes.append({"id": f"lighter-capture:{ol['id']}:{b.get('id')}",
                              "title": f"A lighter capture for {b.get('_label') or b.get('type')}",
                              "sub": f"“{alt.get('name') or alt.get('model')}” is the same amp as a {alt.get('variant')} "
                                     f"model ({b.get('_variant') or '?'} now).",
                              "gain_pct": _r(gain),
                              "action": {"kind": "lighter-capture", "lane": ol["id"], "block": b.get("id"),
                                         "ref": alt.get("ref"), "model": alt.get("model"), "variant": alt.get("variant")}})
    # 5. un buffer plus grand : la part fixe (l'écart au pire tour) s'étale sur plus d'échantillons
    worst_lane = max(heavy, key=lambda ol: ol["pct"])
    nxt = next((b for b in sorted(bsizes) if bsize and b > bsize), None)
    if nxt and srate:
        L = lanes[worst_lane["id"]]
        sid = worst_lane["worst_scene"]
        cost_now = (lambda b: block_us(b.get("_cpu"), L["stereo"], profile, bsize))
        cost_next = (lambda b: block_us(b.get("_cpu"), L["stereo"], profile, nxt))
        now_us, _u, _w = lane_path_us(L["tracks"][sid], cost_now)
        next_us, _u, _w = lane_path_us(L["tracks"][sid], cost_next)
        gain = pct_of(now_us) - next_us / budget_us(nxt, srate) * 100.0
        lat = 2 * (nxt - bsize) / float(srate) * 1000.0
        fixes.append({"id": f"buffer:{nxt}", "title": f"Raise the buffer to {nxt}",
                      "sub": f"More room per buffer; about {lat:.1f} ms more latency (in and out).",
                      "gain_pct": _r(max(0.0, gain)), "action": {"kind": "buffer", "size": nxt, "latency_ms": _r(lat)}})
    # 6. sinon : trop lourd pour ce golem — la lane et le bloc qui pèse le plus
    for ol in heavy:
        if ol["pct"] <= THRESHOLDS["tight"]:
            continue
        gains = sum((f.get("gain_pct") or 0) for f in fixes
                    if (f.get("action") or {}).get("lane") in (None, ol["id"]))
        if ol["pct"] - gains <= THRESHOLDS["tight"]:
            continue
        on = [b for b in ol["blocks"] if b["on"].get(ol["worst_scene"]) and b["pct"] is not None]
        top = max(on, key=lambda b: b["pct"]) if on else None
        fixes.append({"id": f"too-heavy:{ol['id']}", "title": "This preset is too heavy for this golem",
                      "sub": f"Lane “{ol['name']}”, scene {ol['worst_scene']}"
                             + (f": {top['label']} weighs most ({top['pct']:.0f} % of a core)." if top else "."),
                      "gain_pct": 0.0, "action": None})
    rank = {k: i for i, k in enumerate(FIX_ORDER)}
    fixes.sort(key=lambda f: (rank.get(f["id"].split(":")[0], 99), -(f.get("gain_pct") or 0)))
    return fixes


def summary(est):
    """La ligne d'un preset pour estimate-many : {verdict, worst}."""
    return {"verdict": est.get("verdict"), "worst": est.get("worst")}


# ── la mesure brute -> µs par buffer (le calcul du banc, pur) ──────────────────────────────────────────────────────
def per_buffer(times, base, length_s, srate, bsize):
    """Les temps de rendu hors ligne (s) avec le bloc (`times`) et sans aucun FX (`base`), sur `length_s` secondes
    rendues -> {avg_us, worst_us} par buffer de `bsize`. avg : médianes ; worst : le plus lent avec bloc contre le plus
    rapide sans. Lève ValueError si le rendu n'était pas hors ligne pleine vitesse (le temps sans FX ≈ la durée)."""
    if not times or not base or not length_s or not srate or not bsize:
        raise ValueError("incomplete measure")
    if statistics.median(base) >= 0.9 * float(length_s):
        raise ValueError("the render ran in real time, not full-speed offline")
    n = float(length_s) * float(srate) / float(bsize)
    avg = (statistics.median(times) - statistics.median(base)) / n * 1e6
    worst = (max(times) - min(base)) / n * 1e6
    avg = max(0.0, avg)
    return {"avg_us": round(avg, 2), "worst_us": round(max(avg, worst), 2)}


# ═══ LES BORDS : fichiers, catalogue, plans ════════════════════════════════════════════════════════════════════════
_MEMO = {}


def _memo_file(kind, path, fn):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (kind, path, st.st_mtime_ns, st.st_size)
    if key not in _MEMO:
        if len(_MEMO) > 8192:
            _MEMO.clear()
        try:
            _MEMO[key] = fn(path)
        except Exception:
            _MEMO[key] = None
    return _MEMO[key]


def nam_variant_of_doc(doc):
    """La variante de coût d'un .nam déjà lu : standard / lite / feather / nano (WaveNet de l'entraîneur), a2
    (SlimmableContainer), lstm-<couches>x<taille>, sinon wavenet-<empreinte> pour une taille sur mesure."""
    arch = (doc or {}).get("architecture")
    cfg = (doc or {}).get("config") or {}
    if arch == "SlimmableContainer":
        return "a2"
    if arch == "WaveNet":
        sig = tuple((L.get("channels"), L.get("head_size"), len(L.get("dilations") or [])) for L in cfg.get("layers") or [])
        return WAVENET_SIZES.get(sig) or "wavenet-" + hashlib.sha1(repr(sig).encode()).hexdigest()[:6]
    if arch == "LSTM":
        return f"lstm-{cfg.get('num_layers')}x{cfg.get('hidden_size')}"
    return str(arch or "unknown").lower()


def nam_variant(path):
    """La variante d'un fichier .nam (lu une fois par version du fichier), None s'il est illisible."""
    def read(p):
        with open(p, encoding="utf-8") as f:
            return nam_variant_of_doc(json.load(f))
    return _memo_file("nam", path, read)


def wav_ms(path):
    """La durée d'un WAV en ms, lue dans son en-tête (chunks fmt et data) ; None s'il est illisible."""
    def read(p):
        with open(p, "rb") as f:
            head = f.read(12)
            if head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
                return None
            ch = rate = bits = None
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return None
                cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
                if cid == b"fmt ":
                    fmt = f.read(size)
                    ch, rate, bits = struct.unpack("<H", fmt[2:4])[0], struct.unpack("<I", fmt[4:8])[0], struct.unpack("<H", fmt[14:16])[0]
                    if size % 2:
                        f.read(1)
                elif cid == b"data":
                    if not (ch and rate and bits):
                        return None
                    return size / (ch * bits / 8) / rate * 1000.0
                else:
                    f.seek(size + (size % 2), 1)
    return _memo_file("wav", path, read)


def ir_bucket(ms):
    """La classe de longueur d'une IR : « 200ms » = jusqu'à 200 ms ; « long » au-delà de 5 s ; None si inconnue."""
    if ms is None:
        return None
    for b in IR_BUCKETS_MS:
        if ms <= b:
            return f"{b}ms"
    return "long"


def _catalog():
    from . import config as C
    def read(p):
        with open(p, encoding="utf-8") as f:
            return {e["type"]: e for e in (json.load(f) or {}).get("effects") or [] if e.get("type")}
    return _memo_file("catalog", C.EFFECTS, read) or {}


def _silent(b, entry):
    """Le bloc est-il allumé à mix 0 ? (`mix`/`wet` au minimum, ou ≤ −60 dB pour un `wet` en dB)."""
    params = b.get("params") or {}
    for p in (entry or {}).get("params") or []:
        if p.get("id") not in ("mix", "wet") or params.get(p["id"]) is None:
            continue
        try:
            v = float(params[p["id"]])
        except (TypeError, ValueError):
            continue
        if p.get("unit") == "dB":
            return v <= -60
        return v <= float(p.get("min") or 0)
    return False


def components(b, path_has_cab, carries_cab=None, default_cab_file=None):
    """[[kind, variant]] — ce qui coûte dans un bloc annoté par rig (fichiers résolus) : la capture NAM par son
    architecture, l'IR par sa longueur, la tête NAM sans baffle en aval + le baffle par défaut que la compile lui fond
    (compile_rig._render_core_for), un plugin par son type. [] = gratuit ; None dans la variante = non mesurable."""
    t = b.get("type")
    entry = _catalog().get(t) or {}
    if t in NAM_TYPES:
        if not b.get("file"):
            return [] if not b.get("ref") else [["nam", None]]
        out = [["nam", nam_variant(b["file"])]]
        if t in ("amp", "amp-nam") and not path_has_cab and not (carries_cab(b) if carries_cab else t == "amp"):
            out.append(["cab", ir_bucket(wav_ms(default_cab_file)) if default_cab_file else None])
        return out
    if t in IR_TYPES:
        if not b.get("file"):
            return [] if not b.get("ref") else [[t, None]]
        return [[t, ir_bucket(wav_ms(b["file"]))]]
    if t == "vst-host":
        name = str(b.get("plugin") or "")
        return [["vst-host", plugin_slug(name)]] if name else []
    if entry.get("engine") in FREE_ENGINES or t in ("looper",):
        return []
    return [[t, None]]                                   # un plugin (ou un instrument : jamais mesuré au lot 1)


def plugin_slug(name):
    """Une variante stable pour un plugin choisi dans VST Host : son nom, sans le préfixe de format."""
    import re
    n = re.sub(r"^(VST3?i?|LV2i?|CLAPi?|AUi?|JS):\s*", "", str(name)).strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")[:48] or "plugin"


def annotate(plan, path_has_cab_of=None):
    """Annote chaque bloc d'un plan rig (fichiers résolus) : `_cpu` (ses composants), `_label`, `_silent`, `_variant`.
    Lit les .nam/.wav (mémoïsé) : c'est un bord."""
    from . import compile_rig, resolver
    cat = _catalog()
    default_cab = None
    try:
        default_cab = resolver._resolve(compile_rig.DEFAULT_CAB, resolver._components())
    except Exception:
        default_cab = None
    for p in (plan or {}).get("paths") or []:
        has_cab = any(b.get("type") == "cab" and not b.get("bypass") for t in p.get("tracks") or [] for b in t.get("blocks") or [])
        p["stereo"] = bool(any(t.get("stereo") for t in p.get("tracks") or []))
        for t in p.get("tracks") or []:
            for b in t.get("blocks") or []:
                entry = cat.get(b.get("type")) or {}
                b["_cpu"] = components(b, has_cab, compile_rig._carries_cab, default_cab)
                b["_label"] = b.get("label") or b.get("name") or entry.get("name") or b.get("type")
                b["_silent"] = _silent(b, entry)
                nam = next((c[1] for c in b["_cpu"] if c[0] == "nam"), None)
                if nam:
                    b["_variant"] = nam
    return plan


_QUIET = threading.local()


class _Quiet(logging.Filter):
    """Une estimation rebâtit le plan de chaque scène : les avertissements du rig (capture absente…) sont déjà dits par
    le vrai rappel — ici, dans CE fil seulement, ils se taisent (estimate-many en écrivait des dizaines par appel)."""
    def filter(self, record):
        return not getattr(_QUIET, "on", False)


_QUIET_FILTER = _Quiet()


def scene_plans(preset):
    """[(scene id, plan annoté)] d'un preset, par le chemin du rappel (recall.emit_sandbox_preset) : volume système,
    bake union de chaque scène, plan rig — SANS compiler ni écrire (aucune copie d'asset : les fichiers sont lus là où
    ils sont)."""
    import copy
    from . import recall, resolver, rig, scene_bake, store
    work = copy.deepcopy(preset)
    store.ensure_volume(work)
    veto = recall.input_veto(work)
    comps = resolver._components()

    def resolve(ref, model=None, whole=False):
        return resolver._resolve(ref, comps, model)
    ids = [s.get("id") for s in work.get("scenes") or [] if isinstance(s, dict) and s.get("id") is not None] or [None]
    rlog = logging.getLogger("golem.rig")
    if _QUIET_FILTER not in rlog.filters:
        rlog.addFilter(_QUIET_FILTER)
    _QUIET.on = True
    try:
        return _plans(work, ids, veto, resolve)
    finally:
        _QUIET.on = False


def _plans(work, ids, veto, resolve):
    from . import rig, scene_bake
    out = []
    for sid in ids:
        baked = scene_bake.to_paths_preset(work, sid, union=True, veto=veto)
        if not baked.get("paths"):
            out.append((sid if sid is not None else "A", {"paths": []}))
            continue
        plan = rig.build_plan(baked, 99, resolve=resolve, strict_out=False)
        out.append((sid if sid is not None else "A", annotate(plan)))
    return out


def lighter_alternatives(plans):
    """{block id: [{ref, model, variant, name}]} — pour chaque bloc NAM : les autres modèles INSTALLÉS du même son
    (même entrée du catalogue des tones, même nom une fois retiré le suffixe de taille — resolver.twin_name) et
    d'une autre architecture. Le cœur choisit le moins cher parmi ceux que le profil a mesurés."""
    from . import config as C
    from .resolver import _tones_index, twin_name
    idx = _tones_index()
    out = {}
    for _sid, plan in plans:
        for p in (plan or {}).get("paths") or []:
            for t in p.get("tracks") or []:
                for b in t.get("blocks") or []:
                    if b.get("type") not in NAM_TYPES or not b.get("ref") or b.get("id") in out:
                        continue
                    key = str(b["ref"]).split(":", 1)[1] if str(b["ref"]).startswith("t3k:") else str(b["ref"])
                    tone = idx.get(key.split("/")[-1])
                    if not tone:
                        continue
                    models = tone.get("models") or []
                    cur = next((m for m in models if str(m.get("id")) == str(b.get("model"))), models[0] if models else None)
                    if not cur:
                        continue
                    alts = []
                    for m in models:
                        if m is cur or twin_name(m.get("name")) != twin_name(cur.get("name")):
                            continue
                        f = os.path.join(C.ROOT, str(m.get("file") or ""))
                        v = "a2" if str(m.get("arch")) == "2" else (nam_variant(f) if os.path.isfile(f) else None)
                        if v and v != b.get("_variant") and os.path.isfile(f):
                            alts.append({"ref": str(tone.get("id")), "model": m.get("id"), "variant": v, "name": m.get("name")})
                    if alts:
                        out[b["id"]] = alts
    return out


def _walk_typed(node, btype, out=None):
    """Tous les dicts `{type: btype}` d'un document (preset, patch), à toute profondeur."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("type") == btype:
            out.append(node)
        for v in node.values():
            _walk_typed(v, btype, out)
    elif isinstance(node, list):
        for v in node:
            _walk_typed(v, btype, out)
    return out


def _walk_ids(node, bid, out=None):
    """Tous les blocs d'id `bid` d'un document (le même bloc peut vivre dans la lane et dans un miroir legacy)."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if node.get("id") == bid and node.get("type"):
            out.append(node)
        for v in node.values():
            _walk_ids(v, bid, out)
    elif isinstance(node, list):
        for v in node:
            _walk_ids(v, bid, out)
    return out
