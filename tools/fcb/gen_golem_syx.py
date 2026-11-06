#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Génère le .syx FCB1010 au layout GoleM v3 — UnO 1.0.4 MODE STOMPBOX (docs/archive/fcb1010-mapping.md).

Layout 19 banks × 5 presets + 5 stompboxes (rangée haute), rétro-ingénié depuis Ripwerx 2.1
(FcbPreset/FcbGlobal/FcbMessage) + bench matériel 2026-07-24 :
  - patchs presets : bank 0 -> 0-4 ; bank b>=1 -> 5b+5..5b+9  (l'écran FCB affiche 00-18 = slot !)
  - patchs 5-9 = STOMPBOXES SB1-5 (switches 6-10) : CC 30-34 à BASCULE 127/0 (LED = état),
    pas de PC, pédales EXP intouchées
  - preset : PC = slot + CC 20-24 = scène (switch 1-5) + Note = identité ; liens stomp = UNCHANGED
  - globals : data[2330] |= 0x40 (stompbox) | 0x80 (rangée haute) — le flash ACTIVE le mode
Octets UnO par patch (zone après les 16 valeurs, flux 7+1) :
  b16 = transpose(0-4)+tNc(0x20)+s5(0x40) / porteur = s5nc ; b17 = c1AltVal+porteur c1te ;
  b18 = c2AltVal+porteur c2te ; b19 = flags sysex-par-message (0) / porteur = e1te.
  b3 (=PC4) réutilisé en mode stomp : bits0-3 = s1-4, bits4-6 = s1-3nc, porteur = s4nc
  (= bit "PC4 désactivé" riban : désactivé == unchanged, même bit, tout va bien).
Sortie : mappings/fcb1010-golem.syx (+ .csv lisible).
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from fcb1010 import fcb1010

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "mappings", "fcb1010-golem.syx")

SCENE_CC = [20, 21, 22, 23, 24]
STOMP_CC = [30, 31, 32, 33, 34]

fcb = fcb1010()
# MERGE = OFF impératif : le bridge parle au Whammy DT sur le même DIN — merge ON = nos propres
# messages bouclent FCB IN -> FCB OUT (PC22 fantômes, aftertouch corrompu par le running status).
fcb.merge = False
fcb.running_status = False
fcb.direct_select = False
for attr in ("pc1_midi_channel", "cc1_midi_channel", "cc2_midi_channel",
             "expA_midi_channel", "expB_midi_channel", "note_midi_channel",
             "pc2_midi_channel", "pc3_midi_channel", "pc4_midi_channel", "pc5_midi_channel"):
    setattr(fcb, attr, 0)

def bank_patches(b):
    """patchs mémoire des switches 1-5 de la bank b (mapping UnO 1.0.4, bench 2026-07-24)."""
    return list(range(0, 5)) if b == 0 else list(range(5 * b + 5, 5 * b + 10))

def base(p):
    p.pc1_enabled = p.pc2_enabled = p.pc3_enabled = p.pc4_enabled = p.pc5_enabled = False
    p.cc1_enabled = p.cc2_enabled = False
    p.note_enabled = False
    p.switch1_enabled = p.switch2_enabled = False
    p.expA_enabled = p.expB_enabled = False
    p.expA_controller = 7;  p.expA_min = 0; p.expA_max = 127
    p.expB_controller = 11; p.expB_min = 0; p.expB_max = 127
    p.pc1_program = p.pc2_program = p.pc3_program = p.pc5_program = 0
    p.pc4_program = 0x70            # mode stomp : bits4-6 = s1-3nc (liens "unchanged")
    p.cc1_controller = p.cc1_value = 0
    p.cc2_controller = p.cc2_value = 0
    p.note_value = 0

# — 95 presets (19 banks × 5) : PC=slot, CC=scène, Note=identité, EXP actives —
for b in range(19):
    for k, patch in enumerate(bank_patches(b)):
        p = fcb.preset[patch]
        base(p)
        p.pc1_enabled = True;  p.pc1_program = b
        p.cc1_enabled = True;  p.cc1_controller = SCENE_CC[k]; p.cc1_value = 127
        p.note_enabled = True; p.note_value = k
        p.expA_enabled = True; p.expB_enabled = True

# — 5 stompboxes (patchs 5-9) : CC30-34 bascule, Note 5-9, pas de PC, EXP intouchées —
for i in range(5):
    p = fcb.preset[5 + i]
    base(p)
    p.cc1_enabled = True;  p.cc1_controller = STOMP_CC[i]; p.cc1_value = 127
    p.note_enabled = True; p.note_value = 5 + i

data = fcb.get_raw_sysex()

# ── post-traitement UnO : zone des octets 16-19 par patch (flux 7 données + 1 porteur) ──
# On PROLONGE le flux riban : les valeurs occupent les positions logiques 0-1599, les octets
# 16-19 des 100 patchs = logiques 1600-1999. porteur(groupe g) = position 14+8g, bit = L-7g.
# flux : dans chaque groupe de 8 positions (à partir de 7), 7 octets de données puis 1 porteur.
def dpos(L):
    return 7 + (L // 7) * 8 + (L % 7)

def carrier(L):
    return 7 + (L // 7) * 8 + 7, L % 7          # (position du porteur, bit)

# efface le remplissage 127 de riban sur la zone UnO (1839-2310) : c'était du bruit
for i in range(1839, 2311):
    data[i] = 0

for patch in range(100):
    is_stomp = 5 <= patch <= 9
    vals = {
        16: 0x20,                                # t=0, tNc=1, s5=0
        17: 0x00,                                # c1AltVal = 0
        18: 0x00,                                # c2AltVal = 0
        19: 0x00,                                # pas de sysex par message
    }
    msbs = {
        16: 1,                                   # s5nc = 1 (unchanged)
        17: 1 if is_stomp else 0,                # c1te : BASCULE sur les stomps seulement
        18: 0,
        19: 0,
    }
    for j in (16, 17, 18, 19):
        L = 1600 + patch * 4 + (j - 16)
        data[dpos(L)] = vals[j]
        cpos, cbit = carrier(L)
        if msbs[j]:
            data[cpos] |= (1 << cbit)
        else:
            data[cpos] &= ~(1 << cbit)

# ── globals : ACTIVE le mode stompbox rangée haute (le flash suffit, pas de config au pied) ──
data[2330] |= 0x40 | 0x80                        # stomp mode + upper row (Direct Select reste 0)

with open(OUT, "wb") as f:
    f.write(bytes(data))
print(f"OK {OUT} ({len(data)} octets) — stompbox 19x5, SB=patchs 5-9, globals 2330=0x{data[2330]:02x}")

# CSV lisible pour vérif humaine
import csv
with open(OUT.replace(".syx", ".csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["patch", "role", "bank", "sw", "PC", "CC", "CCval", "note"])
    for b in range(19):
        for k, patch in enumerate(bank_patches(b)):
            w.writerow([patch, "preset", b, k + 1, b, SCENE_CC[k], 127, k])
    for i in range(5):
        w.writerow([5 + i, "stompbox", "-", 6 + i, "-", STOMP_CC[i], "127/0 toggle", 5 + i])
