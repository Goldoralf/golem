# SPDX-License-Identifier: GPL-3.0-or-later
"""Choix du backend RtMidi natif, commun aux entrées et sorties MIDI."""
import sys


def native_api(rtmidi):
    """Garde ALSA sur le rack ; utilise WinMM ou CoreMIDI sur desktop."""
    if sys.platform == "win32":
        return rtmidi.API_WINDOWS_MM
    if sys.platform == "darwin":
        return rtmidi.API_MACOSX_CORE
    return rtmidi.API_LINUX_ALSA
