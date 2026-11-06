# SPDX-License-Identifier: GPL-3.0-or-later
"""L'INHARMONICITÉ d'une note : ce qui dit sur quelle CORDE elle est jouée (banc TX de golem.fm, 2026-10-29).

Une corde réelle a une raideur : son partiel k ne sonne pas à k·f0 mais à k·f0·√(1 + B·k²). B dépend de la corde
(diamètre, âme, filage) et de la longueur qui vibre : B ∝ 1/L², donc une case de plus multiplie B par 2^(1/6). Un la
corde 6 case 5 (corde grosse, raccourcie) et un la corde 5 à vide n'ont pas le même B — ce que la hauteur seule ne
peut pas dire. Mesuré sur la corde 6 du mainteneur : 2,0e-4 à vide, 7,8e-4 case 12, comme la physique le prévoit.

Le B à vide de chaque corde est celui de LA guitare (`config/string-calib.json`, mesuré corde par corde) ; le
doigté s'en sert comme d'une preuve de plus (`fingering.evidence_cost`). numpy seulement, importé à l'appel : ce
module tourne dans `.venv-transcribe`.
"""
from __future__ import annotations

import json
import os

#: Le spectre est pris sur le CORPS de la note (après le transitoire, avant l'extinction).
SKIP_S = 0.06
MAX_HZ = 7000.0
MAX_PARTIALS = 30
#: Fenêtre de recherche d'un partiel, en fraction de f0 autour de sa position prédite.
SEARCH_FRAC = 0.12
MIN_PARTIALS = 6
PEAK_SNR = 4.0
#: B de DÉPART des recherches : de la corde aiguë à vide à la corde grave case 12. Un seul départ (2e-4) ratait
#: les cases hautes : leurs partiels aigus tombent hors de la fenêtre de recherche et l'ajustement retombe à B = 0.
B_PRIORS = (1e-4, 2e-4, 4e-4, 8e-4, 16e-4)
#: Fenêtres de lecture : courte (la note avant qu'elle ne glisse), longues (un partiel plus précis), 0,9 s au plus.
WINDOWS_S = (0.30, 0.45, 0.9)
RICH_PARTIALS = 10


def _peak(spec, freqs, f_pred, half):
    import numpy as np
    lo, hi = np.searchsorted(freqs, [f_pred - half, f_pred + half])
    if hi - lo < 3:
        return None
    i = lo + int(np.argmax(spec[lo:hi]))
    if i <= lo or i >= hi - 1:
        return None
    a, b, c = np.log(spec[i - 1] + 1e-12), np.log(spec[i] + 1e-12), np.log(spec[i + 1] + 1e-12)
    p = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    # un partiel dépasse le plancher local, sinon c'est du bruit
    snr = spec[i] / (np.median(spec[lo:hi]) + 1e-12)
    if snr < PEAK_SNR:
        return None
    return freqs[i] + p * (freqs[1] - freqs[0]), float(np.log10(snr))


def _fit(ks, fs, ws, residuals=False):
    """La droite (f_k/k)² = f0² + f0²·B·k², pondérée par la netteté des pics."""
    import numpy as np
    kk = np.array(ks, float)
    yy = (np.array(fs) / kk) ** 2
    slope, icpt = np.polyfit(kk ** 2, yy, 1, w=np.array(ws, float))
    if icpt <= 0:
        return None if not residuals else (float(np.sqrt(abs(icpt))), 0.0, yy * 0)
    f0, B = float(np.sqrt(icpt)), float(slope / icpt)
    if not residuals:
        return f0, B
    pred = kk * f0 * np.sqrt(1 + max(B, 0) * kk * kk)
    return f0, B, (np.array(fs) - pred) / (kk * f0)


def _estimate(y, sr, t0, t1, f0_hint, win_s, b_prior):
    """(B, f0, partiels gardés, dispersion, rang du plus haut partiel gardé) — ou None si la note est trop courte
    ou trop pauvre. Les partiels sont cherchés depuis un B de départ réaliste, puis la droite est ajustée en
    écartant, tour après tour, le partiel le plus loin d'elle (un pic voisin, une autre corde qui sonne) tant que
    l'écart dépasse 3 fois la dispersion médiane."""
    import numpy as np
    a = int((t0 + SKIP_S) * sr)
    b = int(min(t1, t0 + SKIP_S + win_s) * sr)
    if b - a < int(0.15 * sr):
        return None
    seg = y[a:b] * np.hanning(b - a)
    n = 1 << int(np.ceil(np.log2(len(seg) * 8)))
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    f0, B = f0_hint, b_prior
    ks, fs, ws = [], [], []
    for k in range(1, MAX_PARTIALS + 1):
        pred = k * f0 * np.sqrt(1 + B * k * k)
        if pred > MAX_HZ:
            break
        got = _peak(spec, freqs, pred, SEARCH_FRAC * f0)
        if got is None:
            continue
        ks.append(k)
        fs.append(got[0])
        ws.append(got[1])
        if len(ks) >= 4:
            fit = _fit(ks, fs, ws)
            if fit:
                f0, B = fit
    if len(ks) < MIN_PARTIALS:
        return None
    while len(ks) > MIN_PARTIALS:
        f0, B, res = _fit(ks, fs, ws, residuals=True)
        med = float(np.median(np.abs(res))) + 1e-12
        worst = int(np.argmax(np.abs(res)))
        if abs(res[worst]) <= 3 * med:
            break
        for lst in (ks, fs, ws):
            lst.pop(worst)
    f0, B, res = _fit(ks, fs, ws, residuals=True)
    return max(B, 0.0), f0, len(ks), float(np.median(np.abs(res))), max(ks)


def estimate_b(y, sr, t0, t1, f0_hint):
    """Le B d'une note seule jouée de `t0` à `t1` (s) — ou None. Lu sur plusieurs fenêtres et plusieurs B de
    départ : on garde la lecture la plus COHÉRENTE, la dispersion rapportée au rang du plus haut partiel gardé
    (seuls les partiels aigus portent B : une droite tenue par k ≤ 6 est cohérente à bon compte, et fausse)."""
    outs = [r for prior in B_PRIORS for w in WINDOWS_S if (r := _estimate(y, sr, t0, t1, f0_hint, w, prior))]
    # une lecture tenue par MIN_PARTIALS partiels triés sur trente est cohérente à bon compte : une corde grave en a
    # deux, l'une sur ses partiels, l'autre sur ceux d'une corde qui sonne encore (8 cordes, 2026-10-30 : le la grave
    # lu 0,75 sur 8 partiels, 2,65 sur 15). Les lectures à RICH_PARTIALS partiels passent d'abord. (Une droite à B nul
    # reste une lecture : elle dit « rien de sûr », et le doigté ne juge pas — l'écarter faisait juger sur la suivante,
    # fausse : TX00 corde 6 case 12 lue 1,8e-4.)
    outs = [r for r in outs if r[2] >= RICH_PARTIALS] or outs
    return min(outs, key=lambda r: r[3] / r[4])[0] if outs else None


# ── LES GUITARES DU RACK (2026-10-29 : « une 8 cordes plutôt ? ») ──────────────────────────────────────────────────
# Un profil par guitare dans le même fichier : son accordage (notes MIDI, de la plus GRAVE à la plus aiguë), son
# nombre de cases, et le B à vide de chaque corde — l'inharmonicité dépend du calibre, du filage et du diapason : celle
# d'une guitare ne vaut pas pour une autre. `active` dit laquelle on joue ; elle est gravée dans chaque prise
# (take.json `guitar`), et la transcription lit celle de la prise. Les cordes sont numérotées comme en MusicXML :
# 1 = la plus aiguë.
STANDARD = {6: (40, 45, 50, 55, 59, 64), 7: (35, 40, 45, 50, 55, 59, 64), 8: (30, 35, 40, 45, 50, 55, 59, 64)}
DEFAULT_FRETS = 22
#: Les poids du doigté qu'un profil peut régler (`hand`), en coûts positifs ; les autres sont ignorés.
HAND_KEYS = frozenset({"span", "height", "open", "open_high", "open_from", "move", "shift", "reach", "string",
                       "max_span"})


def _doc(path):
    try:
        with open(path) as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def active_guitar(path=None):
    """L'id de la guitare jouée en ce moment (`active`, sinon « default »)."""
    a = _doc(path or CALIB).get("active")
    return a if isinstance(a, str) and a else "default"


def guitar(path=None, gid=None):
    """Le profil d'une guitare : {id, name, tuning (grave -> aigu), frets, b_open {corde: B}, hand, neckmap}. Une guitare inconnue
    ou sans accordage déclaré est une 6 cordes standard ; sans étalonnage, `b_open` est vide (rien n'est jugé)."""
    doc = _doc(path or CALIB)
    gid = gid if isinstance(gid, str) and gid else active_guitar(path)
    g = doc.get(gid) if isinstance(doc.get(gid), dict) else {}
    tuning = g.get("tuning")
    if not (isinstance(tuning, list) and 4 <= len(tuning) <= 9 and all(isinstance(p, int) for p in tuning)):
        tuning = list(STANDARD.get(int(g.get("strings") or 6), STANDARD[6]))
    try:
        frets = max(12, min(30, int(g.get("frets") or DEFAULT_FRETS)))
    except (TypeError, ValueError):
        frets = DEFAULT_FRETS
    b_open = {}
    for k, v in (g.get("b_open") or {}).items():
        try:
            if 1 <= int(k) <= len(tuning) and float(v) > 0:
                b_open[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    # LA MAIN DE CETTE GUITARE (2026-10-30) : des poids du doigté (`fingering.WEIGHTS`) propres à la guitare — une
    # 8 cordes jouée en position haute en motifs de 3-4 notes par corde n'a pas la main du corpus 6 cordes
    hand = {}
    for k, v in (g.get("hand") or {}).items():
        if k in HAND_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 30:
            hand[k] = float(v)
    # SA CARTE DU MANCHE (2026-11-01, bridge/neckmap.py) : le nom du fichier de config/neckmap/, ou None
    nm = g.get("neckmap")
    return {"id": gid, "name": g.get("name") or gid, "tuning": sorted(tuning), "frets": frets, "b_open": b_open,
            "hand": hand, "neckmap": nm if isinstance(nm, str) and nm else None}


def guitar_for(tuning, path=None):
    """L'id du profil dont l'accordage EST `tuning` (mêmes notes, même nombre de cordes) — l'actif d'abord si
    plusieurs l'ont (deux 6 cordes standard) ; None si aucun."""
    want = sorted(tuning or [])
    doc = _doc(path or CALIB)
    ids = [k for k, v in doc.items() if isinstance(v, dict) and not k.startswith("_")]
    hits = [k for k in ids if guitar(path, k)["tuning"] == want]
    act = active_guitar(path)
    return act if act in hits else (hits[0] if hits else None)


def load_calib(path, guitar_id="default"):
    """{corde: B à vide} d'une guitare (1 = la plus aiguë) ; {} sans étalonnage. Une corde absente n'est pas jugée."""
    return guitar(path, guitar_id)["b_open"]


CALIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "string-calib.json")
