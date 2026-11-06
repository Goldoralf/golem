#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Format binaire de la puce UnO2 (FCB1010) — émetteur autonome, sans éditeur tiers.

GoleM décrit son contrat de pédalier en DONNÉES (config/fcb/uno2-golem.json) ; ce module
traduit ces données en image mémoire UnO2, puis en dump SysEx prêt à envoyer à la puce.
Aucun langage texte intermédiaire, aucun outil externe : le rack se flashe tout seul.

    charger la config -> Setup -> build_binary() -> to_sysex() -> flash_uno2.py

── D'OÙ VIENT CE FORMAT ─────────────────────────────────────────────────────────────────
Il n'est pas publié. Il a été établi ici par mesure : compilations différentielles (on fait
varier UNE construction, on lit les octets qui bougent), puis vérification octet pour octet
sur la configuration réelle. `tools/fcb/check-uno2.py` rejoue cette vérification.
Tout ce qui est affirmé plus bas a été mesuré, pas déduit d'un manuel.

── L'IMAGE MÉMOIRE ──────────────────────────────────────────────────────────────────────
    [0..3]   en-tête : longueur totale sur 3 octets (32768/256/1) puis le marqueur 0x20
    [4..7]   pointeur de fin de zone de données (2 octets) + 2 octets à zéro
    [8..]    ZONE DE DONNÉES — les blocs de bytecode, chacun clos par 0xFD. Ordre imposé :
             variables, INIT global, banks, sweeps, presets, effects, triggers.
             Un bloc VIDE n'est pas écrit : son pointeur vaut 0.
    [..]     TABLE D'INDEX — drapeaux, canal de télécommande, puis pour chaque famille son
             compte et les pointeurs de ses blocs ; enfin l'affectation des switches.

Les pointeurs (« memloc ») sont des offsets ABSOLUS dans l'image, et démarrent donc à 8.

── LE BYTECODE ──────────────────────────────────────────────────────────────────────────
Un bloc est une suite de messages MIDI BRUTS — l'octet de statut est le vrai octet MIDI :

    ProgChange v        -> C0|n, v                 (n = canal - 1)
    CtrlChange cc v     -> B0|n, cc, v
    NoteOn k v          -> 90|n, k, v
    NoteOff k v         -> 80|n, k, v

⚠ UN OCTET DE DONNÉE À BIT DE POIDS FORT ARMÉ EST UNE RÉFÉRENCE DE VARIABLE, pas une
valeur : 0x80|i désigne la variable d'index i. C'est ce qui permet `ProgChange $slot`.
Une valeur littérale est donc bornée à 0-127, et c'est structurel, pas un choix.

Les ordres non-MIDI sont préfixés 0xF5 :

    affecter une variable   F5 81 (80|i) valeur
    affecter une pédale     F5 D8 (24+pédale) 0F (index de sweep)
    définir un sweep        F5 E8 <statut> <cc> <de> <à> <style>   style 0=défaut
                                                                   1=FastRising 2=SlowRising

⚠ LA VARIABLE D'INDEX 0 EXISTE TOUJOURS : `MidiChannel`, intégrée à la puce. Les variables
déclarées commencent donc à l'index 1. L'oublier décale toutes les références.

── L'AFFECTATION DES SWITCHES ───────────────────────────────────────────────────────────
Chaque bank porte un index par switch, sur 2 octets, dans un espace segmenté :

    0            aucune affectation
    1024 + i     preset i     (rangée des scènes : bascule de preset, LED en radio)
    2048 + i     effect i     (bascule avec LED d'état — mais AUCUN front de relâchement)
    3072 + i     trigger i    (fronts press ET release francs — mais la LED ne tient pas)

⚠ EFFECT ET TRIGGER SONT EXCLUSIFS, et ce choix se paie : un `effect` ne peut pas porter
de geste (appui long), un `trigger` ne peut pas porter de LED d'état. Voir docs/fcb/uno2/.

── LA BANK DIRECTE ──────────────────────────────────────────────────────────────────────
Sans `use_direct_bank`, une bank vide est insérée EN TÊTE de la liste : les banks réelles
commencent donc à l'indice 1. Avec, la première bank déclarée EST la bank directe.
"""

# ── ordres non-MIDI ──────────────────────────────────────────────────────────────────────
_ESC        = 0xF5      # préfixe des ordres qui ne sont pas du MIDI
_OP_SETVAR  = 0x81      # affectation de variable entière
_OP_SETBOOL = 0xC2      # affectation de booléen   (non utilisé par GoleM, porté pour être complet)
_OP_SETSTR  = 0xC1      # affectation de chaîne    (idem)
_OP_PEDAL   = 0xD8      # affectation d'une pédale d'expression à un sweep
_OP_SWEEP   = 0xE8      # définition d'un sweep
_END        = 0xFD      # fin de bloc

# ── espaces d'index des switches ─────────────────────────────────────────────────────────
IDX_NONE, IDX_PRESET, IDX_EFFECT, IDX_TRIGGER = 0, 1024, 2048, 3072

# ── styles de sweep ──────────────────────────────────────────────────────────────────────
SWEEP_LINEAR, SWEEP_FAST_RISING, SWEEP_SLOW_RISING = 0, 1, 2

BUDGET = 2032           # octets utilisables ; au-delà la puce n'a plus la place


# ══ le bytecode ══════════════════════════════════════════════════════════════════════════

def var_ref(index):
    """Référence à la variable `index`, à poser à la place d'une valeur littérale."""
    if not 0 <= index <= 127:
        raise ValueError("index de variable hors bornes : %r" % index)
    return 0x80 | index


def _data(v, what):
    """Un octet de donnée : littéral 0-127, ou déjà une référence de variable (bit 7 armé)."""
    if isinstance(v, int) and 0x80 <= v <= 0xFF:
        return v                                    # référence de variable, déjà encodée
    if not isinstance(v, int) or not 0 <= v <= 127:
        raise ValueError("%s doit être 0-127 ou une référence de variable, reçu %r" % (what, v))
    return v


def _status(high, channel):
    if not 1 <= channel <= 16:
        raise ValueError("canal MIDI hors bornes (1-16) : %r" % channel)
    return high | (channel - 1)


def prog_change(channel, program):
    return [_status(0xC0, channel), _data(program, "program")]


def ctrl_change(channel, controller, value):
    return [_status(0xB0, channel), _data(controller, "controller"), _data(value, "valeur")]


def note_on(channel, note, velocity=100):
    return [_status(0x90, channel), _data(note, "note"), _data(velocity, "vélocité")]


def note_off(channel, note, velocity=0):
    return [_status(0x80, channel), _data(note, "note"), _data(velocity, "vélocité")]


def set_var(index, value):
    """Affecte une valeur à une variable entière (0-255 : la puce stocke un octet plein)."""
    if not 0 <= value <= 255:
        raise ValueError("valeur de variable hors bornes (0-255) : %r" % value)
    return [_ESC, _OP_SETVAR, var_ref(index), value]


def assign_pedal(pedal, sweep_index):
    """Rattache la pédale d'expression 1 ou 2 au sweep d'index donné (dans INIT_FCB)."""
    if pedal not in (1, 2):
        raise ValueError("pédale d'expression inconnue : %r" % pedal)
    return [_ESC, _OP_PEDAL, 24 + pedal, 0x0F, sweep_index]


def sweep_ctrl_change(channel, controller, lo=0, hi=127, style=SWEEP_LINEAR):
    """Corps d'un sweep : une pédale qui balaie un CC de `lo` à `hi`."""
    return [_ESC, _OP_SWEEP, _status(0xB0, channel),
            _data(controller, "controller"), _data(lo, "borne basse"), _data(hi, "borne haute"),
            style]


# ══ la structure d'un setup ══════════════════════════════════════════════════════════════

class Block:
    """Un élément à deux faces : preset (appui/relâchement), effect (on/off), trigger
    (click/release). Une face vide ne consomme pas de mémoire."""

    def __init__(self, name, on=None, off=None):
        self.name = name
        self.on = list(on or [])
        self.off = list(off or [])
        self.loc_on = 0
        self.loc_off = 0


class Sweep:
    def __init__(self, name, content=None):
        self.name = name
        self.content = list(content or [])
        self.loc = 0


class Bank:
    """Une bank : jusqu'à `switch_count` affectations, plus un bloc d'init joué à l'entrée."""

    def __init__(self, name, switches=None, init=None, switch_count=10):
        self.name = name
        self.switches = list(switches or [])
        self.switches += [IDX_NONE] * (switch_count - len(self.switches))
        if len(self.switches) > switch_count:
            raise ValueError("bank %s : plus de %d switches" % (name, switch_count))
        self.init = list(init or [])
        self.loc = 0


class Setup:
    """Un setup complet, prêt à être transformé en image mémoire.

    `variables` ne contient QUE les variables déclarées : la variable intégrée `MidiChannel`
    est ajoutée d'office en tête, et c'est elle qui occupe l'index 0.
    """

    BUILTIN_VAR = ("MidiChannel", 0)

    def __init__(self, switch_count=10, remote_control_channel=0,
                 use_direct_bank=False, no_updown_switches=False):
        self.switch_count = switch_count
        self.remote_control_channel = remote_control_channel
        self.use_direct_bank = use_direct_bank
        self.no_updown_switches = no_updown_switches
        self.variables = [self.BUILTIN_VAR]
        self.init = []                              # INIT_FCB : joué au démarrage
        self.presets, self.effects, self.triggers = [], [], []
        self.sweeps, self.banks = [], []

    # — déclaration —
    def add_variable(self, name, value=0):
        """Déclare une variable et rend son index (à passer à var_ref / set_var)."""
        self.variables.append((name, value))
        return len(self.variables) - 1

    def add_sweep(self, sweep):
        self.sweeps.append(sweep)
        return len(self.sweeps) - 1

    def add_preset(self, block):
        self.presets.append(block)
        return IDX_PRESET + len(self.presets) - 1

    def add_effect(self, block):
        self.effects.append(block)
        return IDX_EFFECT + len(self.effects) - 1

    def add_trigger(self, block):
        self.triggers.append(block)
        return IDX_TRIGGER + len(self.triggers) - 1

    def add_bank(self, bank):
        self.banks.append(bank)
        return len(self.banks) - 1

    # — mise en page mémoire —
    def _layout(self):
        """Pose chaque bloc en mémoire et rend (préambule, pointeur de fin).

        L'ordre de pose est CELUI DE LA PUCE et n'est pas négociable : variables et init
        d'abord, puis banks, sweeps, presets, effects, triggers.
        """
        head = []
        for i, (_, value) in enumerate(self.variables):
            head += [_ESC, _OP_SETVAR, var_ref(i), value & 0xFF]
        head += self.init
        head.append(_END)
        loc = 8 + len(head)

        placed = {}

        def place(key, content):
            """Range un bloc s'il n'est pas vide, et rend son pointeur.

            Le bloc terminé est mis de côté plutôt qu'écrit dans l'objet : compiler deux
            fois le même Setup doit donner deux fois le même binaire.
            """
            nonlocal loc
            if not content:
                placed[key] = []
                return 0
            here = loc
            placed[key] = content + [_END]
            loc += len(content) + 1
            return here

        for bank in self.banks:
            bank.loc = place(("bank", id(bank)), bank.init)
        for sweep in self.sweeps:
            sweep.loc = place(("sweep", id(sweep)), sweep.content)
        for block in self.presets + self.effects + self.triggers:
            block.loc_on = place(("on", id(block)), block.on)
            block.loc_off = place(("off", id(block)), block.off)
        return head, loc, placed

    def banks_in_memory(self):
        """Les banks telles que la puce les voit : sans `use_direct_bank`, une bank vide
        est insérée en tête, et les banks réelles commencent à l'indice 1."""
        if self.use_direct_bank:
            return list(self.banks)
        return [Bank("Direct Bank", switch_count=self.switch_count)] + list(self.banks)


# ══ l'image mémoire ══════════════════════════════════════════════════════════════════════

def build_binary(setup):
    """Rend l'image mémoire complète de la puce (bytes). Ne modifie pas le setup."""
    banks = setup.banks_in_memory()
    saved_banks, setup.banks = setup.banks, banks
    try:
        head, end, placed = setup._layout()
    finally:
        setup.banks = saved_banks

    # — zone de données : même ordre que la mise en page —
    data = [end >> 8, end & 0xFF, 0, 0] + head
    for bank in banks:
        data += placed[("bank", id(bank))]
    for sweep in setup.sweeps:
        data += placed[("sweep", id(sweep))]
    for block in setup.presets + setup.effects + setup.triggers:
        data += placed[("on", id(block))] + placed[("off", id(block))]

    # — table d'index —
    idx = [2 if setup.no_updown_switches else 0, setup.remote_control_channel]
    for family in (setup.presets, setup.effects, setup.triggers):
        idx += [len(family) >> 8, len(family) & 0xFF]
        for block in family:
            idx += [block.loc_on >> 8, block.loc_on & 0xFF,
                    block.loc_off >> 8, block.loc_off & 0xFF]
    idx.append(len(setup.sweeps))
    for sweep in setup.sweeps:
        idx += [sweep.loc >> 8, sweep.loc & 0xFF]

    idx.append(len(banks))
    if setup.use_direct_bank:
        # une bank directe sans bloc d'init se signale par 0xFFFF, pas par 0
        idx += ([banks[0].loc >> 8, banks[0].loc & 0xFF] if banks[0].loc else [255, 255])
    else:
        idx += [0, 0]
    for bank in banks[1:]:
        idx += [bank.loc >> 8, bank.loc & 0xFF]

    idx.append(setup.switch_count)
    for bank in banks:
        for s in range(setup.switch_count):
            target = bank.switches[s]
            if target == 255:                       # « aucune » se note 0 dans l'image
                target = 0
            idx += [target >> 8, target & 0xFF]
    idx.append(0)

    total = 4 + len(data) + len(idx)
    return bytes([total // 32768, (total % 32768) // 256, total % 256, 0x20] + data + idx)


def setup_length(setup):
    """Occupation mémoire annoncée par la puce, à comparer à BUDGET.

    Ce n'est PAS len(build_binary()) : le calcul de la puce compte les terminateurs des
    blocs vides et arrondit à sa façon. On reproduit son calcul, pas le nôtre.
    """
    banks = setup.banks_in_memory()
    n = 8 + len(setup.init) + 1
    n += 4 * len(setup.variables)
    for block in setup.presets + setup.effects + setup.triggers:
        n += (len(block.on) + 1) if block.on else 0
        n += (len(block.off) + 1) if block.off else 0
    for sweep in setup.sweeps:
        n += (len(sweep.content) + 1) if sweep.content else 0
    for bank in banks:
        n += (len(bank.init) + 1) if bank.init else 0
    blocks = 1 + len(setup.presets) + len(setup.effects) + len(setup.triggers)
    return n + (14 + 4 * blocks + 2 * len(setup.sweeps) + 2 * len(banks)
                + len(banks) * setup.switch_count * 2)


# ══ l'empaquetage SysEx ══════════════════════════════════════════════════════════════════

SYSEX_HEADER = (0xF0, 0x7E, 0x7E, 0x51, 0x00, 0x00)


def _pack_7bit(data):
    """8 bits -> 7 bits, par groupes de 7 octets.

    Chaque groupe rend 9 octets : les 7 charges utiles amputées de leur bit de poids fort,
    puis un octet qui rassemble ces bits (le bit s porte le poids fort de l'octet s), puis
    un XOR de contrôle des 8 précédents. Le dernier groupe est complété de zéros.
    """
    out = []
    for start in range(0, len(data), 7):
        msb = check = 0
        for s in range(7):
            b = data[start + s] if start + s < len(data) else 0
            out.append(b & 0x7F)
            check ^= b & 0x7F
            msb |= (b & 0x80) >> (7 - s)
        out.append(msb)
        check ^= msb
        out.append(check)
    return out


def to_sysex(binary):
    """Enrobe l'image mémoire dans le dump SysEx que la puce attend.

    ⚠ Les trois premiers octets sont RÉ-EMPAQUETÉS avant l'encodage 7 bits : la longueur
    passe de 3 octets de 8 bits à 3 champs alignés sur 7 bits. Sans ça la puce lit une
    taille fausse et rejette le dump.
    """
    b = list(binary)
    if len(b) < 4:
        raise ValueError("image mémoire trop courte")
    b[0] = ((b[0] << 1) + (1 if b[1] & 0x40 else 0)) & 0xFF
    b[1] = (((b[1] & 0x3F) << 1) + (1 if b[2] & 0x80 else 0)) & 0xFF
    b[2] = b[2] & 0x7F
    return bytes(list(SYSEX_HEADER) + _pack_7bit(b) + [0xF7])
