# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérification Ed25519 en Python PUR (RFC 8032 §5.1.7) — lot 8, la signature des originaux.

Pourquoi pas une bibliothèque : le bridge n'en a aucune (ni `cryptography`, ni PyNaCl), et en ajouter une compilée
pèse sur les trois installateurs (Linux, Windows, macOS) pour vérifier UN manifeste à l'import. Ce module ne fait que
VÉRIFIER (le rack ne signe rien) ; il suit la référence de la RFC, en coordonnées étendues. Quelques millisecondes par
signature : assez pour un geste, jamais sur le thread audio.

Contrôlé par les vecteurs de la RFC 8032 §7.1 (tests/test_signatures.py)."""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
_G_Y = 4 * pow(5, P - 2, P) % P


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_G_X = _recover_x(_G_Y, 0)
_G = (_G_X, _G_Y, 1, _G_X * _G_Y % P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % P
    B = (y1 + x1) * (y2 + x2) % P
    C = 2 * t1 * t2 * D % P
    Dd = 2 * z1 * z2 % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a, b):
    x1, y1, z1, _ = a
    x2, y2, z2, _ = b
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def verify(public, msg, sig):
    """True si `sig` (64 octets) est la signature Ed25519 de `msg` par la clé `public` (32 octets)."""
    if len(public) != 32 or len(sig) != 64:
        return False
    A = _decompress(public)
    R = _decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + public + msg).digest(), "little") % L
    return _equal(_mul(s, _G), _add(R, _mul(h, A)))
