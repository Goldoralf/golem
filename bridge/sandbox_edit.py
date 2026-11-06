# SPDX-License-Identifier: GPL-3.0-or-later
"""DEUX ÉCRANS N'ÉDITENT PAS LE MÊME BROUILLON EN SILENCE (docs/devices-people.md, lot D — 2026-09-15).

Le Designer n'édite pas le preset, il édite la SANDBOX (`presets/.sandbox.json`, CLAUDE.md). Chaque
écran ouvert — le kiosk, la fenêtre de bureau, une tablette — écrivait ce même brouillon, et le dernier
gagnait sans un mot. Vécu le 2026-09-15 : une fenêtre ouverte depuis la veille, restée sur un vieux
brouillon, a très probablement réécrit Paper Kite avec une scène D « scene » que personne n'avait vue.

Chaque Designer ouvert porte un identifiant d'ÉDITEUR et la RÉVISION du brouillon sur laquelle il a
commencé. Le brouillon garde sa révision et son dernier éditeur (dans le fichier : un rechargement du
bridge ne remet pas le compteur à zéro). Une écriture d'un AUTRE éditeur, partie d'une révision
dépassée (ou inconnue), est refusée — sauf `force`, que le Designer n'envoie qu'après un geste
explicite : ouvrir un preset, déposer un patch, « Keep mine ».

Pur : pas d'I/O ici, la route lit et écrit le fichier.
"""


def conflict(meta, editor, base, force=False):
    """None si l'écriture passe ; sinon {rev, by} — la révision courante et qui l'a écrite."""
    meta = meta or {}
    cur, last = int(meta.get("edit_rev") or 0), meta.get("editor")
    if force or not editor or not last or editor == last or cur == 0:
        return None
    try:
        b = int(base)
    except (TypeError, ValueError):
        b = None
    if b is not None and b >= cur:
        return None
    return {"rev": cur, "by": meta.get("editor_name") or "another screen"}


def after_write(meta, editor, editor_name):
    """La méta du brouillon après une écriture acceptée."""
    meta = meta or {}
    out = {"edit_rev": int(meta.get("edit_rev") or 0) + 1}
    if editor:
        out["editor"] = str(editor)
        out["editor_name"] = editor_name or "another screen"
    else:
        for k in ("editor", "editor_name"):
            if meta.get(k):
                out[k] = meta[k]
    return out
