#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recette de charge « uno2 » — compile l'intention GoleM pour une puce UnO2.

    ./tools/fcb/gen_uno2_syx.py              # compile, affiche l'occupation mémoire
    ./tools/fcb/gen_uno2_syx.py -o out.syx   # et écrit le dump SysEx

Deux entrées, et le découpage est le contrat (docs/pedalboards.md) :

    config/pedalboard/contract.json          l'INTENTION — sans appareil, sans canal, sans octet
    config/pedalboard/devices/<id>.json      le DESCRIPTEUR — canal, travers, capacités

Le format binaire et ses pièges sont dans tools/fcb/uno2.py. Ici on ne fait que déplier :
N banks identiques, les scènes, les stomps, les pédales.

⚠ L'ORDRE DE DÉCLARATION EST SIGNIFIANT. Les pointeurs de l'image mémoire suivent l'ordre dans
lequel les blocs sont ajoutés ; à contrat identique, changer l'ordre change le binaire. On
déclare donc : scènes dans l'ordre du contrat, puis les stomps SANS geste, puis ceux AVEC.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uno2

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PEDALBOARD_DIR = os.path.join(ROOT, "config", "pedalboard")
CONTRACT = os.path.join(PEDALBOARD_DIR, "contract.json")
DEVICES_DIR = os.path.join(PEDALBOARD_DIR, "devices")
DEFAULT_DEVICE = "fcb1010-uno2"


def _read(path):
    with open(path, encoding="utf8") as fh:
        return json.load(fh)


def load(contract_path=CONTRACT, device_id=DEFAULT_DEVICE):
    """Charge l'intention et le descripteur, et refuse ce qui ne va pas ensemble."""
    contract = _read(contract_path)
    device = _read(os.path.join(DEVICES_DIR, device_id + ".json"))
    if device.get("load", {}).get("recipe") != "uno2":
        raise SystemExit("%s attend la recette « uno2 », pas « %s » — mauvais compilateur."
                         % (device_id, device.get("load", {}).get("recipe")))
    if len(contract["scenes"]) + len(contract["stomps"]) > 10:
        raise SystemExit("le FCB1010 n'a que 10 switches")
    if not 1 <= device["channel"] <= 16:
        raise SystemExit("canal du contrat hors bornes : %r" % device["channel"])
    return contract, device


def unmet_gestures(contract, device):
    """Les switches qui RÉCLAMENT des fronts sur un appareil qui ne sait pas les donner.

    Une exigence qu'on ne peut pas satisfaire doit être DITE, pas rabotée en silence :
    l'appui long disparaîtrait, et on chercherait la panne dans le rack.
    """
    if device.get("capabilities", {}).get("gestures"):
        return []
    return [s["switch"] for s in contract["stomps"] if s.get("gestures")]


def looper_slots_from_setlist():
    """Les slots de la setlist dont le preset porte un bloc looper.

    ⚠ ON IMPORTE LA RÈGLE DU RACK (`bridge.rig.looper_enabled`), on ne la réécrit pas. Deux
    définitions du même mot, c'est précisément le bug du 2026-08-08 : l'écran d'édition ne
    balayait pas la lane de config, le rack si, et la rangée haute n'appartenait pas au même
    propriétaire selon qui répondait. Un compilateur qui aurait sa troisième définition ferait
    flasher une puce en désaccord avec le rack qui la pilote.

    Rend () si la setlist ou les presets sont illisibles : une bank looper en trop est une
    perte de LED, une bank looper qui manque est un geste mort — dans le doute, on ne promet rien.
    """
    try:
        sys.path.insert(0, ROOT)
        from bridge import rig, store
        ids = _foot_ids()
        out = []
        for i, pid in enumerate(ids):
            if not pid:
                continue
            p = store.load_preset(pid)            # un preset OU un patch (`patch:<id>`, bank de sons)
            if p and rig.looper_enabled(p):
                out.append(i)
        return tuple(out)
    except Exception as e:
        print("  (slots looper indéterminés : %s — toutes les banks seront identiques)" % e)
        return ()


def _foot_ids():
    """Les ids de la liste AU PIED — celle que `config/setlist.json` désigne (bridge.setlists.active_id), pas
    `setlists/fcb-banks.json` : ce fichier est la setlist historique « Repertoire », pas un miroir. Lu en dur,
    il compilait la puce d'après la mauvaise liste dès qu'une autre était au pied (trouvé le 2026-09-30).
    Une ligne de bank de sons rend `patch:<id>` (setlists.pid_of)."""
    sys.path.insert(0, ROOT)
    from bridge import setlists
    return (setlists.load(setlists.active_id()) or {}).get("presets") or []


def claim_slots_from_setlist(contract=None):
    """{slot: [switches]} — les switches de la RANGÉE DES SCÈNES qu'un preset réserve à un bloc
    ON/OFF (Rec, Click, Tuner, Rec + Backing…), slot par slot.

    Même discipline que `looper_slots_from_setlist` : ON IMPORTE LA RÈGLE DU RACK
    (`bridge.store.toggle_claim_switches`), on ne la réécrit pas. Le switch de sélection n'en est
    jamais (son appui long a besoin du relâchement). Rend {} si quoi que ce soit est illisible :
    dans le doute, toutes les banks restent des scènes, comme avant."""
    try:
        sys.path.insert(0, ROOT)
        from bridge import store
        sel = int(((contract or _read(CONTRACT)).get("select") or {}).get("switch", 1))
        ids = _foot_ids()
        out = {}
        for i, pid in enumerate(ids):
            if not pid:
                continue
            p = store.load_preset(pid)
            sws = store.toggle_claim_switches(p, sel) if p else []
            if sws:
                out[i] = sws
        return out
    except Exception as e:
        print("  (switches réservés indéterminés : %s — toutes les banks gardent leurs scènes)" % e)
        return {}


def build(contract, device, looper_slots=(), claim_slots=None):
    """Déplie l'intention en un Setup UnO2 prêt à compiler.

    `claim_slots` : {slot: [switches 1-5]} — dans CES banks, ces switches passent de `preset`
    (diode en radio avec les scènes) à `effect` (diode on/off, comme un stomp). Vide -> binaire
    inchangé au bit près.

    `looper_slots` : les slots de setlist dont le preset porte un bloc looper. Leur bank
    compile ses switches de loop en `trigger` (cf. contract.looper_bank). Vide -> toutes les
    banks sont identiques, exactement comme avant."""
    ch = device["channel"]
    base = device.get("quirks", {}).get("note_base", 0)
    goto = device.get("capabilities", {}).get("goto_bank", {})
    setup = uno2.Setup(switch_count=10,
                       remote_control_channel=goto.get("channel", 0) if goto.get("supported") else 0)

    # La variable qui porte le slot courant : posée par le bloc d'init de chaque bank,
    # relue par chaque scène pour émettre son Program Change.
    slot = setup.add_variable("slot", 0)

    def note_of(switch):
        """La Note qu'émet ce switch sur le fil — l'intention numérote depuis 1, la puce
        depuis `note_base`."""
        return switch - 1 + base

    # — les pédales d'expression : un sweep chacune, rattaché dans l'init général —
    for exp in contract.get("expression", []):
        i = setup.add_sweep(uno2.Sweep("Exp%d" % exp["pedal"], uno2.sweep_ctrl_change(
            ch, exp["cc"], exp.get("min", 0), exp.get("max", 127))))
        setup.init += uno2.assign_pedal(exp["pedal"], i)

    # — rangée basse : les scènes. Le Program Change porte le slot, pas la scène —
    scene_idx = []
    for scene in contract["scenes"]:
        n = note_of(scene["switch"])
        scene_idx.append(setup.add_preset(uno2.Block(
            "Scene" + scene["name"],
            on=uno2.prog_change(ch, uno2.var_ref(slot))
               + uno2.ctrl_change(ch, scene["cc"], 127)
               + uno2.note_on(ch, n, 100),
            off=uno2.note_off(ch, n, 0))))

    # — rangée haute : les stomps. L'exigence de gestes décide de l'espèce, et donc de la
    #   face « off » : un `effect` tient sa LED mais n'émet AUCUN relâchement (deux NoteOn),
    #   un `trigger` donne les deux fronts mais sa LED ne reste pas allumée. Exclusif.
    can_gesture = bool(device.get("capabilities", {}).get("gestures"))

    def stomp_block(stomp, gesture):
        n = note_of(stomp["switch"])
        return uno2.Block(
            "Stomp%d%s" % (stomp["switch"], "T" if gesture else ""),
            on=uno2.ctrl_change(ch, stomp["cc"], 127) + uno2.note_on(ch, n, 100),
            off=uno2.ctrl_change(ch, stomp["cc"], 0)
                + (uno2.note_off(ch, n, 0) if gesture else uno2.note_on(ch, n, 100)))

    stomp_idx = {}
    for wants in (False, True):
        for stomp in contract["stomps"]:
            gesture = bool(stomp.get("gestures")) and can_gesture
            if gesture != wants:
                continue
            block = stomp_block(stomp, gesture)
            stomp_idx[stomp["switch"]] = (setup.add_trigger(block) if gesture
                                          else setup.add_effect(block))

    # — LA BANK LOOPER : les mêmes switches, en `trigger` —
    # L'espèce est par BANK sur la UnO2 (manuel §Bank layout). Un slot dont le preset porte un
    # bloc looper a besoin des DEUX FRONTS sur ses trois loops : sans relâchement, tap/overdub
    # sont morts et l'appui long — armé au press, jamais annulé — finit par EFFACER la boucle.
    # On paie la LED d'état de ces trois switches ; /live affiche déjà l'état ET la position,
    # ce qu'une LED ne saura jamais faire.
    # ⚠ Les blocs supplémentaires sont ajoutés APRÈS les autres : les index déjà distribués ne
    # bougent pas, donc une bank normale compile exactement comme avant (témoin check-uno2).
    # ⚠ N'EXISTENT QUE SI UNE BANK LES UTILISE. Les ajouter inconditionnellement gonflait le
    # binaire de 54 octets sur une setlist SANS aucun preset looper — et faisait diverger le
    # témoin pour rien. Une puce ne doit pas porter le coût d'une capacité que personne n'a
    # demandée : pas de slot looper -> binaire identique au bit près, garanti par check-uno2.
    loop_sw = ([s for s in (contract.get("looper_bank") or {}).get("gestures", [])]
               if (can_gesture and looper_slots) else [])
    loop_idx = dict(stomp_idx)
    for stomp in contract["stomps"]:
        if stomp["switch"] in loop_sw and not stomp.get("gestures"):
            loop_idx[stomp["switch"]] = setup.add_trigger(stomp_block(stomp, True))

    # — LES SWITCHES RÉSERVÉS : la même case de la rangée des scènes, en `effect` —
    # 2026-09-21 : « je clique REC, la diode s'allume, REC se lance ; je reclique, la diode
    # s'éteint, REC se coupe — le même comportement que sur les stomps ». En `preset`, la diode du
    # switch entre en RADIO avec celles des scènes : elle s'allume, éteint la scène, et ne s'éteint
    # plus. L'espèce est par BANK : seules les banks dont le preset réserve ce switch changent.
    #   · les deux faces portent le Program Change : après un UP/DOWN, le PREMIER appui peut être
    #     celui-ci, et sans PC le rack basculerait le Rec du preset PRÉCÉDENT ;
    #   · le CC de la scène porte l'ÉTAT (127 = on, 0 = off), comme un stomp : le rack le lit en
    #     ordre ABSOLU pour les switches qu'il sait flashés ainsi (presets/.uno2-flashed.json) ;
    #   · AUCUNE Note : un `effect` n'a pas de relâchement, et ces blocs n'ont pas de geste.
    # ⚠ Ajoutés APRÈS tout le reste, et seulement si une bank s'en sert : sans réservation, le
    # binaire est identique au bit près (témoin check-uno2).
    claim_slots = {int(k): sorted(set(v)) for k, v in (claim_slots or {}).items() if v}
    scene_of_sw = {sc["switch"]: sc for sc in contract["scenes"]}
    claim_idx = {}
    for sw in sorted({s for v in claim_slots.values() for s in v}):
        sc = scene_of_sw.get(sw)
        if not sc:
            continue
        claim_idx[sw] = setup.add_effect(uno2.Block(
            "Claim%d" % sw,
            on=uno2.prog_change(ch, uno2.var_ref(slot)) + uno2.ctrl_change(ch, sc["cc"], 127),
            off=uno2.prog_change(ch, uno2.var_ref(slot)) + uno2.ctrl_change(ch, sc["cc"], 0)))

    # — les banks : une par slot de setlist, identiques sauf leur numéro, leur looper, leurs réservations —
    order_st = [stomp_idx[s["switch"]] for s in contract["stomps"]]
    order_st_loop = [loop_idx[s["switch"]] for s in contract["stomps"]]
    for n in range(contract["slots"]):
        loop = n in (looper_slots or ())
        mine = claim_slots.get(n) or []
        row = [claim_idx.get(sc["switch"], scene_idx[i]) if sc["switch"] in mine else scene_idx[i]
               for i, sc in enumerate(contract["scenes"])]
        setup.add_bank(uno2.Bank("Slot%02d%s%s" % (n, "L" if loop else "", "C" if mine else ""),
                                 switches=row + (order_st_loop if loop else order_st),
                                 init=uno2.set_var(slot, n)))
    return setup


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--contract", default=CONTRACT)
    ap.add_argument("-d", "--device", default=DEFAULT_DEVICE)
    ap.add_argument("-o", "--out", help="écrire le dump SysEx dans ce fichier")
    ap.add_argument("--bin", help="écrire aussi l'image mémoire brute (mise au point)")
    ap.add_argument("--no-looper-banks", action="store_true",
                    help="ignorer la setlist : toutes les banks identiques (comparaison de témoin)")
    args = ap.parse_args()

    contract, device = load(args.contract, args.device)
    slots = () if args.no_looper_banks else looper_slots_from_setlist()
    claims = {} if args.no_looper_banks else claim_slots_from_setlist(contract)
    setup = build(contract, device, looper_slots=slots, claim_slots=claims)
    used = uno2.setup_length(setup)
    binary = uno2.build_binary(setup)
    syx = uno2.to_sysex(binary)

    print("%-22s %s" % ("appareil :", device["name"]))
    print("%-22s %s" % ("banks looper :",
                        ", ".join("#%02d" % n for n in slots) if slots else "aucune"))
    print("%-22s %s" % ("switches en effect :",
                        " · ".join("#%02d: SW%s" % (n, "+".join(map(str, v))) for n, v in sorted(claims.items()))
                        if claims else "aucun"))
    print("%-22s %d slots · %d scènes · %d stomps · %d pédales"
          % ("intention :", contract["slots"], len(contract["scenes"]),
             len(contract["stomps"]), len(contract.get("expression", []))))
    goto = device.get("capabilities", {}).get("goto_bank", {})
    print("%-22s canal %d · télécommande %s"
          % ("canaux :", device["channel"],
             ("canal %d" % goto["channel"]) if goto.get("supported") else "non gérée"))
    unmet = unmet_gestures(contract, device)
    if unmet:
        print("%-22s switch(es) %s réclament des fronts que cet appareil NE SAIT PAS donner —"
              % ("⚠ non satisfait :", ", ".join(map(str, unmet))))
        print("%-22s l'appui long n'existera pas dessus." % "")
    print("%-22s %d / %d octets (%.1f %%)%s"
          % ("occupation :", used, uno2.BUDGET, used / uno2.BUDGET * 100,
             "   *** DÉPASSEMENT ***" if used > uno2.BUDGET else ""))
    print("%-22s %d octets · sysex %d octets" % ("image mémoire :", len(binary), len(syx)))
    if used > uno2.BUDGET:
        return 1

    if args.bin:
        with open(args.bin, "wb") as fh:
            fh.write(binary)
        print("%-22s %s" % ("image écrite :", args.bin))
    if args.out:
        with open(args.out, "wb") as fh:
            fh.write(syx)
        print("%-22s %s" % ("dump écrit :", args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
