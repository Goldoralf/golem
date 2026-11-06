# SPDX-License-Identifier: GPL-3.0-or-later
"""Comparer deux empreintes Chromaprint — le golem COMPARE, il ne calcule rien (golem-format.md §12 point 5,
règle de rattachement validée le 2026-10-08).

Une empreinte voyage sous sa forme compressée (sortie par défaut de `fpcalc`, base64 URL sans remplissage).
Deux encodages du même master ne donnent PAS la même chaîne : on la DÉCODE (le format de compression de
Chromaprint, réimplémenté ici en Python pur — pas de bibliothèque native, le golem tourne sur trois
plateformes), puis on mesure la ressemblance des deux suites d'entiers de 32 bits : le TAUX D'ERREUR BINAIRE
au meilleur décalage (un autre silence en tête décale tout d'un bloc). Même enregistrement : 0,006 à ~0,07 ;
deux morceaux différents : ~0,45-0,5 (le hasard). Mesures et seuil : SAME_MAX_BER.

Vérifié contre libchromaprint (chromaprint_get_raw_fingerprint) sur de vraies empreintes : tests/test_fingerprint.py."""
import base64

FRAME_S = 0.1238          # durée d'un entier d'empreinte (TEST2 : un pas de 4096/3 échantillons à 11025 Hz)
MAX_SHIFT_S = 10.0        # décalage cherché, dans les deux sens (silence de tête différent)
MIN_OVERLAP = 60          # entiers comparés au minimum (~7 s)
# au-delà : pas le même enregistrement. MESURÉ le 2026-10-08 sur de vraies empreintes, algorithme TEST2 (celui de
# fpcalc par défaut — l'enum libchromaprint vaut 1 ; une première mesure faite par erreur en TEST3 est jetée) :
#   même enregistrement — réencodé 96 kb/s 0,006 · retardé 70/300 ms 0,058 · coupé 20 ms à 1 s 0,006-0,065 ;
#   pas le même — un STEM isolé du même morceau : basse 0,259, batterie 0,412 · autres morceaux 0,457-0,492.
# 0,15 : plus du double du pire « même », bien sous le plus proche « pas le même ». Empreintes : tests/data/.
# L'empreinte de golem.fm (muxer chromaprint de ffmpeg) est IDENTIQUE octet pour octet à celle de libchromaprint.
SAME_MAX_BER = 0.15
DURATION_TOL_MS = 2000    # golem-format.md §13 : « même master » = durée à ±2 s, d'abord


class FingerprintError(ValueError):
    pass


def _b64(s):
    s = str(s or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _unpack(data, width, count):
    """`count` valeurs de `width` bits, lues dans `data` comme un flux de bits petit-boutiste."""
    out, acc, nbits, i = [], 0, 0, 0
    mask = (1 << width) - 1
    while len(out) < count:
        while nbits < width:
            if i >= len(data):
                raise FingerprintError("truncated fingerprint")
            acc |= data[i] << nbits
            nbits += 8
            i += 1
        out.append(acc & mask)
        acc >>= width
        nbits -= width
    return out


def decode(value):
    """L'empreinte compressée -> (algorithme, [entiers de 32 bits]). Lève FingerprintError."""
    try:
        data = _b64(value)
    except (ValueError, TypeError) as e:
        raise FingerprintError("not a chromaprint fingerprint") from e
    if len(data) < 4:
        raise FingerprintError("not a chromaprint fingerprint")
    algo = data[0]
    n = (data[1] << 16) | (data[2] << 8) | data[3]
    body = data[4:]
    # 1. les valeurs NORMALES (3 bits) : un zéro clôt chaque entier ; on lit jusqu'au n-ième zéro
    normal, zeros, acc, nbits, i = [], 0, 0, 0, 0
    while zeros < n:
        while nbits < 3:
            if i >= len(body):
                raise FingerprintError("truncated fingerprint")
            acc |= body[i] << nbits
            nbits += 8
            i += 1
        v = acc & 7
        acc >>= 3
        nbits -= 3
        normal.append(v)
        if v == 0:
            zeros += 1
    # 2. les valeurs EXCEPTIONNELLES (5 bits), une par valeur normale saturée (7), après l'octet entamé
    start = (len(normal) * 3 + 7) // 8
    n_exc = sum(1 for v in normal if v == 7)
    exc = _unpack(body[start:], 5, n_exc) if n_exc else []
    k = 0
    for j, v in enumerate(normal):
        if v == 7:
            normal[j] = v + exc[k]
            k += 1
    # 3. les écarts de position des bits mis -> les entiers, puis le XOR avec le précédent
    out, value_, last = [], 0, 0
    for b in normal:
        if b == 0:
            out.append(value_ ^ out[-1] if out else value_)
            value_, last = 0, 0
            continue
        last += b
        value_ |= 1 << (last - 1)
    return algo, [x & 0xFFFFFFFF for x in out]


def ber(a, b):
    """Le plus petit taux d'erreur binaire entre deux suites, au meilleur décalage (±MAX_SHIFT_S). 1.0 si elles
    ne se recouvrent pas assez pour juger."""
    max_shift = int(MAX_SHIFT_S / FRAME_S)
    best = 1.0
    for off in range(-max_shift, max_shift + 1):
        lo, hi = max(0, -off), min(len(a), len(b) - off)
        n = hi - lo
        if n < MIN_OVERLAP:
            continue
        diff = sum(bin(a[i] ^ b[i + off]).count("1") for i in range(lo, hi))
        r = diff / (32.0 * n)
        if r < best:
            best = r
    return best


def same_recording(fa, fb, dur_a_ms=None, dur_b_ms=None):
    """Même enregistrement ? D'abord la durée (±2 s, si les deux sont connues), puis les empreintes.
    `fa`/`fb` = empreintes compressées. Rend (bool, taux d'erreur ou None)."""
    if dur_a_ms and dur_b_ms and abs(int(dur_a_ms) - int(dur_b_ms)) > DURATION_TOL_MS:
        return False, None
    try:
        aa, ra = decode(fa)
        ab, rb = decode(fb)
    except FingerprintError:
        return False, None
    if aa != ab:                       # deux algorithmes de Chromaprint ne se comparent pas
        return False, None
    r = ber(ra, rb)
    return r <= SAME_MAX_BER, r
