#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flashe la configuration GoleM dans la puce UnO2 du FCB1010.

    ./tools/fcb/flash_uno2.py --identify     # LECTURE SEULE : qui répond, et en quelle version
    ./tools/fcb/flash_uno2.py --dry-run      # compile et montre ce qui serait envoyé
    ./tools/fcb/flash_uno2.py --write        # écrit vraiment dans la puce
    ./tools/fcb/flash_uno2.py --write --no-claims   # la sortie : SW1-5 redeviennent cinq scènes partout

L'écriture demande `--write` : elle remplace TOUT le contenu de la puce, et un pédalier à moitié
flashé ne se découvre qu'au moment de jouer. Le tour d'identification passe d'abord, toujours :
on refuse d'écrire dans une puce qui ne s'annonce pas comme une UnO2.

── LE DIALOGUE AVEC LA PUCE ─────────────────────────────────────────────────────────────
Tout tient en SysEx universel non-temps-réel, appareil 7E :

    identification      -> F0 7E 7E 30 F7
    réponse             <- F0 7E 7E 38 <type> <version> <série…> F7      type 8 = FCB1010 UnO2
    dump                -> F0 7E 7E 51 00 00 <données 7 bits> F7
    en cours            <- F0 7E 7E 7C F7        (la puce écrit sa mémoire)
    succès              <- F0 7E 7E 7F F7
    échec               <- tout autre code

La version tient dans un octet : quartet haut = majeure, quartet bas = mineure.

⚠ ON IGNORE CE QU'ON NE COMPREND PAS. La UnO2 renvoie son MIDI IN vers son OUT sans qu'on
puisse l'en empêcher, donc nos propres octets peuvent nous revenir ; et le pédalier reste
libre d'émettre un appui pendant qu'on attend. On ne retient que les réponses à la forme
exacte attendue, jusqu'au délai de garde — plutôt que de traiter le premier message venu
comme un échec.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uno2
import gen_uno2_syx

try:
    import rtmidi
except Exception:
    # python-rtmidi vit dans l'environnement du bridge, pas dans le Python système. On s'y
    # relance plutôt que d'exiger la bonne incantation : le rack doit pouvoir se flasher seul.
    # ⚠ Le témoin est une variable d'environnement, PAS une comparaison de chemins : le
    # `python` d'un venv est un lien vers le binaire système, donc les chemins réels sont
    # égaux et la garde ne se déclencherait jamais.
    _venv = os.path.join(gen_uno2_syx.ROOT, ".venv", "bin", "python")
    if os.path.exists(_venv) and not os.environ.get("GOLEM_FLASH_RELAUNCHED"):
        os.environ["GOLEM_FLASH_RELAUNCHED"] = "1"
        os.execv(_venv, [_venv, os.path.abspath(__file__)] + sys.argv[1:])
    rtmidi = None

REQ_IDENTIFY = [0xF0, 0x7E, 0x7E, 0x30, 0xF7]
REPLY_IDENTIFY = 0x38
ACK_SAVING, ACK_DONE = 0x7C, 0x7F
DEVICE_UNO2 = 8
DEVICES = {0: "TinyBox", 1: "TinyBox4Kemper", DEVICE_UNO2: "FCB1010 (puce UnO2)"}

TIMEOUT_IDENTIFY = 3.0
TIMEOUT_FLASH = 15.0


class Midi:
    """Un port MIDI d'entrée et un de sortie sur la même carte, le temps du dialogue.

    On passe par la couche séquenceur d'ALSA, pas par la rawmidi : le bridge tourne pendant
    ce temps-là et tient déjà la carte. Le séquenceur accepte plusieurs clients, `amidi` non
    (il répondrait « busy »).
    """

    def __init__(self, want):
        if rtmidi is None:
            raise SystemExit("python-rtmidi est absent — impossible de parler à la puce.")
        self.want = want.lower()
        self.out = rtmidi.MidiOut(rtmidi.API_LINUX_ALSA, name="golem-flash")
        self.inp = rtmidi.MidiIn(rtmidi.API_LINUX_ALSA, name="golem-flash")
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.out_name = self._open(self.out, "sortie")
        self.in_name = self._open(self.inp, "entrée")

    def _open(self, port, label):
        names = port.get_ports()
        for i, name in enumerate(names):
            if self.want in name.lower():
                port.open_port(i, name="uno2")
                return name
        raise SystemExit("aucun port MIDI de %s ne contient « %s ».\nPorts vus : %s"
                         % (label, self.want, ", ".join(names) or "(aucun)"))

    def send(self, data):
        self.out.send_message(list(data))

    def await_reply(self, timeout, match):
        """Attend un SysEx que `match` accepte. Rend le message, ou None au délai de garde.

        Les messages non retenus sont rendus au passage pour pouvoir les dire à l'écran :
        un dialogue muet et un dialogue bruyant ne se soignent pas pareil.
        """
        seen, deadline = [], time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.inp.get_message()
            if msg is None:
                time.sleep(0.002)
                continue
            data = msg[0]
            if match(data):
                return data, seen
            if data and data[0] == 0xF0:
                seen.append(data)
        return None, seen

    def close(self):
        for port in (self.inp, self.out):
            try:
                port.close_port()
            except Exception:
                pass


def _is_ack(data):
    return len(data) == 5 and data[:3] == [0xF0, 0x7E, 0x7E] and data[4] == 0xF7


def identify(midi, verbose=True):
    """Interroge la puce. Rend le dictionnaire de sa réponse, ou None."""
    midi.send(REQ_IDENTIFY)
    data, seen = midi.await_reply(
        TIMEOUT_IDENTIFY,
        lambda d: len(d) == 9 and d[:4] == [0xF0, 0x7E, 0x7E, REPLY_IDENTIFY] and d[8] == 0xF7)
    if data is None:
        if any(_is_ack(d) and d[3] == 0x30 for d in seen):
            print("  la demande d'identification NOUS EST REVENUE : c'est l'écho THRU, et rien")
            print("  n'a répondu. Un FCB1010 est peut-être là, mais sans la puce UnO2.")
        else:
            print("  aucune réponse en %.0f s." % TIMEOUT_IDENTIFY)
            print("  À vérifier : le pédalier est allumé, MIDI OUT du FCB -> MIDI IN de la carte,")
            print("  MIDI OUT de la carte -> MIDI IN du FCB.")
            if seen:
                print("  (%d message(s) SysEx reçus, aucun à la forme attendue)" % len(seen))
        return None
    info = {"device": data[4],
            "version": "%d.%d" % (data[5] >> 4, data[5] & 0x0F),
            "serial": (data[6] >> 1, data[7] + 128 * (data[6] & 1))}
    if verbose:
        print("  appareil  : %s" % DEVICES.get(info["device"], "inconnu (type %d)" % info["device"]))
        print("  firmware  : %s" % info["version"])
        print("  série     : %d-%d" % info["serial"])
    return info


def flash(midi, syx):
    """Envoie le dump et suit les accusés. Rend True si la puce a confirmé."""
    midi.send(syx)
    saw_saving = False
    deadline = time.monotonic() + TIMEOUT_FLASH
    while time.monotonic() < deadline:
        data, _ = midi.await_reply(max(0.1, deadline - time.monotonic()),
                                   lambda d: _is_ack(d) and d[3] in (ACK_SAVING, ACK_DONE))
        if data is None:
            break
        if data[3] == ACK_SAVING:
            if not saw_saving:
                print("  la puce écrit sa mémoire…")
            saw_saving = True
            continue
        print("  la puce a confirmé le dump.")
        return True
    if saw_saving:
        print("  ÉCHEC : la puce a commencé à écrire puis n'a jamais confirmé.")
        print("  Elle est peut-être à moitié flashée — refaire l'opération AVANT de jouer.")
    else:
        print("  ÉCHEC : aucun accusé en %.0f s." % TIMEOUT_FLASH)
    return False


def _remember_flash(syx, loop_slots, claim_slots):
    """Ce qui est RÉELLEMENT dans la puce, écrit APRÈS un flash réussi : presets/.uno2-flashed.json.

    Le rack le lit pour savoir quels switches de la rangée des scènes envoient un ÉTAT (CC 127 /
    0, espèce `effect`) et lesquels envoient toujours 127 (espèce `preset`). Il ne peut pas le
    DÉDUIRE du preset : une réservation changée dans le Designer sans reflash, et le rack croirait
    la puce à jour — il lirait « 127 = on » pour toujours et la prise ne s'arrêterait plus. On lit
    ce qui a été écrit, on ne déclare pas ce qui devrait l'être (CLAUDE.md, « forme et nature »).
    État LOCAL de la machine : jamais commité."""
    import hashlib
    import json
    path = os.path.join(gen_uno2_syx.ROOT, "presets", ".uno2-flashed.json")
    doc = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sysex_sha256": hashlib.sha256(bytes(syx)).hexdigest(),
           "looper_slots": list(loop_slots or ()),
           "effect_switches": {str(k): list(v) for k, v in sorted((claim_slots or {}).items())}}
    # LE DUMP LUI-MÊME, octet pour octet (2026-10-14 : « que le fichier de flash soit stocké ») : ce qui
    # est dans la puce se relit et se rejoue (un autre outil SysEx, un pédalier de rechange) ; le précédent est
    # gardé à côté, pour revenir en arrière d'un flash. Toujours de l'état local (il suit la setlist de CE rack).
    syx_path = os.path.join(os.path.dirname(path), ".uno2-flashed.syx")
    if os.path.exists(syx_path):
        os.replace(syx_path, os.path.join(os.path.dirname(path), ".uno2-flashed.prev.syx"))
    with open(syx_path + ".tmp", "wb") as fh:
        fh.write(bytes(syx))
    os.replace(syx_path + ".tmp", syx_path)
    doc["sysex_file"] = os.path.relpath(syx_path, gen_uno2_syx.ROOT)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)
    print("  mémoire du flash : %s + %s (%d octets)" % (os.path.relpath(path, gen_uno2_syx.ROOT),
                                                       doc["sysex_file"], len(syx)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--contract", default=gen_uno2_syx.CONTRACT)
    ap.add_argument("-d", "--device", default=gen_uno2_syx.DEFAULT_DEVICE)
    ap.add_argument("-p", "--port", default=os.environ.get("GOLEM_MIDI_PORT", "Volt"),
                    help="sous-chaîne du nom de port MIDI (défaut : Volt)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--identify", action="store_true", help="lecture seule : qui répond")
    mode.add_argument("--dry-run", action="store_true", help="compile sans rien envoyer")
    mode.add_argument("--write", action="store_true", help="écrit vraiment dans la puce")
    ap.add_argument("--no-claims", action="store_true",
                    help="LA SORTIE : ignorer les switches réservés — la rangée des scènes redevient "
                         "cinq scènes dans toutes les banks, comme avant le 2026-09-21")
    args = ap.parse_args()

    if not (args.identify or args.dry_run or args.write):
        ap.error("choisir --identify, --dry-run ou --write")

    # — compilation, sauf pour une simple identification —
    syx = None
    if not args.identify:
        contract, dev = gen_uno2_syx.load(args.contract, args.device)
        # ⚠ LES BANKS LOOPER VIENNENT DE LA SETLIST, comme dans gen_uno2_syx.main(). Sans cet
        # argument, l'outil de FLASH compilait la variante « aucune bank looper » — il aurait
        # écrit dans la puce un binaire différent de celui que le générateur annonce, et les
        # gestes du looper seraient restés morts sans que rien ne l'explique. Attrapé par le
        # --dry-run le 2026-08-08 : 775 octets là où le générateur en annonçait 829.
        loop_slots = gen_uno2_syx.looper_slots_from_setlist()
        claim_slots = {} if args.no_claims else gen_uno2_syx.claim_slots_from_setlist(contract)
        setup = gen_uno2_syx.build(contract, dev, looper_slots=loop_slots, claim_slots=claim_slots)
        used = uno2.setup_length(setup)
        syx = uno2.to_sysex(uno2.build_binary(setup))
        # les banks au NUMÉRO DE L'ÉCRAN DU FCB (quirks.display_base, 1 sur la UnO2) : « #01 » pour le slot 1
        # annonçait une bank que l'afficheur montre en 02 (2026-09-30)
        base = int(((dev.get("quirks") or {}).get("display_base")) or 0)
        print("Configuration")
        print("  %s  ←  %s" % (dev["name"], os.path.relpath(args.contract, gen_uno2_syx.ROOT)))
        print("  banks looper : %s"
              % (", ".join("#%02d" % (n + base) for n in loop_slots) if loop_slots else "aucune"))
        print("  switches en effect (diode on/off) : %s"
              % (" · ".join("#%02d SW%s" % (n + base, "+".join(map(str, v))) for n, v in sorted(claim_slots.items()))
                 if claim_slots else "aucun"))
        print("  %d slots, %d scènes, %d stomps, %d pédales — canal %d"
              % (contract["slots"], len(contract["scenes"]), len(contract["stomps"]),
                 len(contract.get("expression", [])), dev["channel"]))
        unmet = gen_uno2_syx.unmet_gestures(contract, dev)
        if unmet:
            print("  ⚠ switch(es) %s réclament des fronts que cet appareil ne sait pas donner."
                  % ", ".join(map(str, unmet)))
        print("  occupation %d / %d octets (%.1f %%) — dump de %d octets"
              % (used, uno2.BUDGET, used / uno2.BUDGET * 100, len(syx)))
        if used > uno2.BUDGET:
            print("  DÉPASSEMENT — rien ne sera envoyé.")
            return 1
        if args.dry_run:
            print("\n--dry-run : rien n'a été envoyé.")
            return 0

    midi = Midi(args.port)
    try:
        print("\nPorts MIDI")
        print("  sortie : %s" % midi.out_name)
        print("  entrée : %s" % midi.in_name)
        print("\nIdentification")
        info = identify(midi)
        if info is None:
            return 1
        if info["device"] != DEVICE_UNO2:
            print("\n  Ce n'est pas une puce UnO2 — on n'écrit pas.")
            return 1
        if args.identify:
            return 0

        print("\nÉcriture")
        print("  ne débranche rien et n'appuie sur rien pendant l'opération.")
        if not flash(midi, syx):
            return 1
        _remember_flash(syx, loop_slots, claim_slots)
    finally:
        midi.close()

    print("\nFlash terminé. À vérifier ensuite, au pied : ./tools/check-foot.py --live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
