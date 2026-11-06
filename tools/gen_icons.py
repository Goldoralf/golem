#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Génère le set d'icônes GoleM via Nano Banana, style verrouillé, fond sombre uni.
Sortie : app/icons/<type>.png   (puis key_bg.py pour la version transparente -a.png)
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import nanobanana as nb

STYLE = (" Minimalist, bold clean silhouette, light warm-gray (#dfe3ea) flat shapes with a single "
         "subtle orange (#ff5a3c) accent. Centered, even medium line weight, generous margin. "
         "Solid completely uniform very dark charcoal background (#14181d), NO checkerboard, "
         "NO transparency pattern, NO grid. Modern premium music-gear app icon, no text, no drop "
         "shadow, crisp flat vector style, square 1:1.")

ICONS = {
  "gate":    "a noise gate for guitar (a square-wave gate cutting off a sound signal)",
  "comp":    "an audio compressor (a downward chevron compressing a waveform between two lines)",
  "boost":   "an overdrive guitar stompbox pedal seen from top, one round knob and a footswitch",
  "amp":     "a guitar amplifier head, rectangular amp top with a horizontal row of four control knobs",
  "cab":     "a 4x12 guitar speaker cabinet, a tall box with four round speaker cones in a 2x2 grid",
  "eq":      "a graphic equalizer, a row of five vertical slider faders set at different heights",
  "chorus":  "a chorus modulation effect, two overlapping smooth wavy sine waves",
  "phaser":  "a phaser effect, sweeping nested concentric phase curves",
  "delay":   "a delay echo effect, a tall sound bar followed by three fading repeated bars to the right",
  "reverb":  "a reverb effect, concentric soft arcs radiating and diffusing outward in a space",
  "pitch":   "a pitch shifter, an upward arrow next to a musical eighth note",
  "volume":  "a volume level control, a horizontal fader knob on a track",
  "mic":     "a vocal studio condenser microphone seen from the front, on a short stand",
  "tuner":   "a chromatic guitar tuner, a half-circle meter with a centered vertical needle",
  "tempo":   "a classic mechanical metronome with a swinging pendulum, front view",
  "stack":   "a guitar amp full stack, an amplifier head sitting on top of a tall 4x12 speaker cabinet",
}

def main():
    only = set(sys.argv[1:])
    out_dir = os.path.join(os.path.dirname(__file__), "..", "app", "icons")
    key = nb._load_key()
    items = [(k, v) for k, v in ICONS.items() if not only or k in only]
    for i, (name, subj) in enumerate(items, 1):
        out = os.path.join(out_dir, f"{name}.png")
        nb.generate(f"Premium flat UI icon of {subj}.{STYLE}", out, key=key)
        print(f"[{i}/{len(items)}] {name} -> {out}")

if __name__ == "__main__":
    main()
