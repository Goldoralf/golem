# SPDX-License-Identifier: GPL-3.0-or-later
"""Le MIDI qu'un instrument de clavier attend du Golem Engine (docs/ardour-plan.md §7d, lot 2). Pur : testé en CI.

Deux instruments ne se règlent pas par des ports de plugin mais par du MIDI, comme les vraies machines :
  - l'ORGUE (setBfree, LV2 b_synth) n'a aucun port de contrôle : tirettes, Leslie, vibrato, percussion et saturation
    sont des Control Change. Sous REAPER, le JSFX golem/b3-ctl les émet depuis ses sliders ; ici le plan moteur porte la
    liste des CC, calculée par la MÊME table (reaper/Effects/b3-ctl.jsfx), et le veilleur les écrit dans le plugin ;
  - le PIANO ÉLECTRIQUE (Dexed) reçoit sa voix en SysEx. Sous REAPER, golem/dx7-ctl envoie la cartouche de 32 voix
    (4104 octets) puis un Program Change ; le veilleur ne peut écrire qu'un message de 1024 octets dans un plugin :
    on envoie donc LA voix choisie, seule (163 octets), dépliée de la cartouche — le format « une voix » du DX7.
"""

LESLIE = {"stop": 64, "slow": 21, "fast": 110}             # CC1 : 0-42 lent, 43-85 arrêt, 86-127 rapide
VIBRATO = ("off", "V1", "C1", "V2", "C2", "V3", "C3")
DRAWBARS = (("db16", 70), ("db513", 71), ("db8", 72), ("db4", 73), ("db223", 74), ("db2", 75), ("db135", 76),
            ("db113", 77), ("db1", 78))
ORGAN_DEFAULTS = {"db16": 8, "db513": 8, "db8": 8, "db4": 0, "db223": 0, "db2": 0, "db135": 0, "db113": 0, "db1": 0,
                  "leslie": "slow", "vibrato": "off", "perc": False, "perc_harm": "3rd", "perc_decay": "fast",
                  "drive": False, "character": 30}
ORGAN_PARAMS = frozenset(ORGAN_DEFAULTS)


def _cc(n, v):
    return [0xB0, n, max(0, min(127, int(v)))]


def organ_cc(params):
    """Les Control Change de la registration, canal 1 (le clavier supérieur de setBfree), dans l'ordre de b3-ctl."""
    p = {**ORGAN_DEFAULTS, **{k: v for k, v in (params or {}).items() if k in ORGAN_DEFAULTS and v is not None}}
    out = []
    for pid, cc in DRAWBARS:                                # tirettes INVERSÉES : 8 (tirée) = 0, 0 (rentrée) = 127
        pos = max(0.0, min(8.0, float(p[pid])))
        out.append(_cc(cc, 127 - int(pos * 127 / 8 + 0.5)))
    out.append(_cc(1, LESLIE.get(str(p["leslie"]).lower(), LESLIE["slow"])))
    vib = VIBRATO.index(p["vibrato"]) if p["vibrato"] in VIBRATO else 0
    if vib == 0:
        out.append(_cc(95, 0))                              # routage du vibrato coupé
    else:
        out += [_cc(95, 80), _cc(92, (vib - 1) * 23 + 11)]
    out.append(_cc(80, 127 if p["perc"] else 0))
    out.append(_cc(83, 127 if str(p["perc_harm"]).lower() == "3rd" else 0))
    out.append(_cc(82, 127 if str(p["perc_decay"]).lower() == "fast" else 0))
    out.append(_cc(65, 127 if p["drive"] else 0))
    out.append(_cc(93, int(max(0.0, min(100.0, float(p["character"]))) * 127 / 100 + 0.5)))
    return out


BANK_SIZE, VOICE_PACKED, VOICE_SIZE = 4104, 128, 155


def dx7_unpack(v):
    """Une voix de cartouche (128 octets, champs empaquetés) -> la voix dépliée (155 octets), ordre du DX7."""
    if len(v) != VOICE_PACKED:
        raise ValueError("a packed DX7 voice is 128 bytes")
    out = []
    for op in range(6):
        o = v[op * 17:op * 17 + 17]
        out += list(o[0:11])                                # R1-4, L1-4, BP, LD, RD
        out += [o[11] & 3, (o[11] >> 2) & 3]                # LC, RC
        out += [o[12] & 7, o[13] & 3, (o[13] >> 2) & 7]     # RS, AMS, KVS
        out += [o[14], o[15] & 1, (o[15] >> 1) & 31, o[16]]  # OL, mode, coarse, fine
        out += [(o[12] >> 3) & 15]                          # detune
    g = v[102:128]
    out += list(g[0:8])                                     # PEG rates, levels
    out += [g[8] & 31, g[9] & 7, (g[9] >> 3) & 1]           # algorithm, feedback, osc key sync
    out += list(g[10:14])                                   # LFO speed, delay, PMD, AMD
    out += [g[14] & 1, (g[14] >> 1) & 7, (g[14] >> 4) & 7]  # LFO sync, wave, pitch mod sens
    out += [g[15]] + list(g[16:26])                         # transpose, name
    return [b & 0x7F for b in out]


def dx7_voice_sysex(bank, patch):
    """Le SysEx « une voix » (163 octets) de la voix `patch` (0-31) d'une cartouche .syx de 32 voix (octets)."""
    bank = bytes(bank)
    if len(bank) < BANK_SIZE or bank[0] != 0xF0 or bank[1] != 0x43 or bank[3] != 0x09:
        raise ValueError("not a 32-voice DX7 cartridge")
    n = max(0, min(31, int(patch or 0)))
    data = dx7_unpack(bank[6 + n * VOICE_PACKED:6 + (n + 1) * VOICE_PACKED])
    return [0xF0, 0x43, 0x00, 0x00, 0x01, 0x1B] + data + [(-sum(data)) & 0x7F, 0xF7]
