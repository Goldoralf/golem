# SPDX-License-Identifier: GPL-3.0-or-later
"""LE REC ET LE MORCEAU (docs/devices-people.md, lot F — décision 2026-09-15).

« Pour l'option je dirai que c'est ok pour la répète, mais en show le rec se lance avec la première
chanson auto, ou quelqu'un sur la tablette ou un téléphone l'a lancé 2 minutes avant d'entrer sur scène
et c'est prêt ! »

- `rec_scope: "song"` (tout mode qui ne dit rien) : le conductor coche « Record with the song » -> la prise
  part avec le morceau et s'arrête avec lui.
- `rec_scope: "set"` (Gig) : la prise part avec la PREMIÈRE chanson de la setlist si elle ne tourne pas
  déjà, et elle couvre tout le concert (elle ne s'arrête pas en fin de morceau). Un REC arrêté exprès au
  milieu du set ne repart pas tout seul.

⚠ 2026-09-18 : cette règle s'appelait « show » et se lisait sur l'ID DU MODE (`if mode == "show"`) — le
seul endroit du rack qui violait « pas de `if mode ==` disséminé » (docs/modes.md §2). Depuis la fusion
Show → Gig (§7 bis), elle se lit sur un CHAMP de la carte, `rec_scope`.

Pur : l'appelant (app._on_song) lit l'état et exécute la décision.
"""


def decide(ev, *, asked, set_scope, first_line, recording, with_song):
    """-> (action, with_song) : action ∈ {"start", "stop", None} ; with_song = la prise en cours suit le morceau."""
    if ev == "start":
        if recording:
            return None, with_song
        if set_scope and first_line:
            return "start", False
        if asked and not set_scope:
            return "start", True
        return None, False
    if ev == "end":
        return ("stop" if (with_song and recording) else None), False
    return None, with_song
