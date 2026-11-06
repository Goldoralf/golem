# SPDX-License-Identifier: GPL-3.0-or-later
"""LIRE UN CORPS BRUT SANS LIMITE, C'ÉTAIT METTRE LE BRIDGE À GENOUX (audit 2026-11-04, M9).

`await request.body()` charge tout en mémoire avant le moindre contrôle : un appareil appairé envoyait 2 Go à
/api/import/inspect, ou n'importe quelle taille à /api/groove/import, et le bridge — qui porte le pied et la scène —
gonflait d'autant. Ici, le corps est lu par morceaux et la lecture s'ARRÊTE au plafond ; un `Content-Length` déjà
trop grand est refusé avant d'avoir lu un octet."""
import os

MB = 1024 * 1024


class TooLarge(Exception):
    """Le corps dépasse le plafond de la route."""

    def __init__(self, limit):
        super().__init__(f"file too large (> {limit // MB} MB)")
        self.limit = limit


def _declared_too_big(request, limit):
    try:
        return int(request.headers.get("content-length") or 0) > limit
    except ValueError:
        return False


async def read_body(request, limit):
    """Les octets du corps, au plus `limit` ; TooLarge au-delà."""
    if _declared_too_big(request, limit):
        raise TooLarge(limit)
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > limit:
            raise TooLarge(limit)
    return bytes(buf)


async def body_to_file(request, path, limit):
    """Écrit le corps dans `path` sans le garder en mémoire ; rend la taille. TooLarge au-delà (fichier retiré)."""
    if _declared_too_big(request, limit):
        raise TooLarge(limit)
    n = 0
    try:
        with open(path, "wb") as f:
            async for chunk in request.stream():
                n += len(chunk)
                if n > limit:
                    raise TooLarge(limit)
                f.write(chunk)
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    return n
