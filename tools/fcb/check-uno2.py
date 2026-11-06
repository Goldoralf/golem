#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie le compilateur UnO2 — sans la puce, et sans aucun outil tiers.

    ./tools/fcb/check-uno2.py            # tout
    ./tools/fcb/check-uno2.py --update   # ré-étalonne le témoin après un changement VOULU

POURQUOI CE SCRIPT EXISTE
Le format binaire de la UnO2 n'est pas publié : il a été établi par mesure, en comparant nos
octets à ceux du compilateur d'origine, sur treize variantes de configuration. Cette
comparaison-là ne peut pas vivre dans le dépôt — elle demandait un logiciel tiers. Ce qui
reste, et qui suffit à retenir une régression, c'est un TÉMOIN : le condensat des octets
qu'on produisait le jour où l'égalité a été prouvée. S'il bouge sans qu'on l'ait voulu,
quelque chose a changé dans la compilation, et il faut savoir quoi avant de flasher.

Le témoin a été établi le 2026-08-06, égalité vérifiée octet pour octet avec le compilateur
d'origine sur : production, banc v1.2, tous les stomps en effect, tous en trigger, canal 1
sans télécommande, canal 16, un seul slot, sans pédale, une pédale, l'autre pédale, bornes de
sweep inversées, trois scènes, aucun stomp.
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uno2
import gen_uno2_syx as gen

WITNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uno2-witness.json")
FAILED = []


def ok(label, condition, detail=""):
    print("  %s %s%s" % ("OK  " if condition else "ÉCHEC", label,
                         "" if condition or not detail else "\n        " + detail))
    if not condition:
        FAILED.append(label)
    return condition


def check_roundtrip(syx, binary):
    """Le dump se laisse-t-il redécoder ? Parité et somme de contrôle comprises."""
    if not (syx[:6] == bytes(uno2.SYSEX_HEADER) and syx[-1] == 0xF7):
        return False, "en-tête ou terminateur SysEx faux"
    body = syx[6:-1]
    if any(b > 127 for b in body):
        return False, "un octet du corps dépasse 7 bits"
    if len(body) % 9:
        return False, "le corps n'est pas un multiple de 9 octets"
    out = bytearray()
    for i in range(0, len(body), 9):
        data, msb, chk = body[i:i + 7], body[i + 7], body[i + 8]
        run = msb
        for b in data:
            run ^= b
        if run != chk:
            return False, "somme de contrôle fausse au groupe %d" % (i // 9)
        for s, b in enumerate(data):
            out.append(b | (((msb >> s) & 1) << 7))
    # les trois premiers octets portent la longueur ré-empaquetée sur 7 bits
    announced = (out[0] << 14) | (out[1] << 7) | out[2]
    if announced != len(binary):
        return False, "longueur annoncée %d, image de %d octets" % (announced, len(binary))
    if out[3] != 0x20:
        return False, "octet marqueur %#x au lieu de 0x20" % out[3]
    return True, ""


def foot_hardcodes_channel():
    """`bridge/foot.py` porte-t-il encore un canal en dur ?

    C'est LA régression à empêcher : tant que le canal vivait dans le code, ressouder l'autre
    puce rendait le rack sourd sans un mot de log. Il doit venir du descripteur.
    """
    path = os.path.join(gen.ROOT, "bridge", "foot.py")
    src = open(path, encoding="utf8").read()
    return re.search(r"^CONTRACT_WIRE_CHANNEL\s*=\s*\d+", src, re.M) is not None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--update", action="store_true", help="ré-étalonne le témoin")
    args = ap.parse_args()

    contract, dev = gen.load()
    setup = gen.build(contract, dev)
    used = uno2.setup_length(setup)
    binary = uno2.build_binary(setup)
    syx = uno2.to_sysex(binary)
    digest = {"binary": hashlib.sha256(binary).hexdigest(),
              "sysex": hashlib.sha256(syx).hexdigest(),
              "binary_len": len(binary), "sysex_len": len(syx), "used": used}

    if args.update:
        with open(WITNESS, "w", encoding="utf8") as fh:
            json.dump(digest, fh, indent=1)
            fh.write("\n")
        print("Témoin ré-étalonné : %s octets, occupation %d." % (len(binary), used))
        return 0

    print("Compilation")
    ok("la configuration se compile", True)
    ok("l'occupation tient dans le budget (%d / %d)" % (used, uno2.BUDGET), used <= uno2.BUDGET)
    ok("compiler deux fois donne le même binaire", uno2.build_binary(setup) == binary)

    print("Empaquetage SysEx")
    good, why = check_roundtrip(syx, binary)
    ok("le dump se redécode (parité, somme de contrôle, longueur)", good, why)

    # ── LA BANK LOOPER (contract.looper_bank) ────────────────────────────────────────────
    # Une capacité qu'aucune sonde n'exerce est une capacité qu'on découvre cassée le soir où
    # on en a besoin. Ici on vérifie les deux promesses : sans slot looper le binaire est
    # IDENTIQUE au bit près (la puce ne paie pas une capacité que personne n'a demandée), et
    # avec, il compile, tient dans le budget et se redécode.
    print("Bank looper")
    neutre = uno2.build_binary(gen.build(contract, dev, looper_slots=()))
    ok("sans slot looper, le binaire est inchangé", neutre == binary,
       "%d vs %d octets" % (len(neutre), len(binary)))
    lset = gen.build(contract, dev, looper_slots=(3,))
    lbin = uno2.build_binary(lset)
    lused = uno2.setup_length(lset)
    if (contract.get("looper_bank") or {}).get("gestures"):
        ok("une bank looper compile et grossit", len(lbin) > len(binary),
           "%d -> %d octets" % (len(binary), len(lbin)))
    else:
        # amendement looper du 2026-10-14 : les boucles sont sur SW 1-4 (la rangée des scènes donne déjà les deux
        # fronts) — la bank looper n'a plus rien à changer, elle est IDENTIQUE aux autres
        ok("une bank looper est identique aux autres (boucles sur la rangée des scènes)", lbin == binary,
           "%d -> %d octets" % (len(binary), len(lbin)))
    ok("elle tient dans le budget", lused <= 2032, "%d / 2032" % lused)
    lgood, lwhy = check_roundtrip(uno2.to_sysex(lbin), lbin)
    ok("son dump se redécode", lgood, lwhy)
    # les blocs `trigger` sont PARTAGÉS : 19 banks looper ne coûtent pas plus que 1.
    l19 = uno2.build_binary(gen.build(contract, dev, looper_slots=tuple(range(19))))
    ok("19 banks looper ne coûtent pas plus qu'une", len(l19) == len(lbin),
       "%d vs %d octets" % (len(l19), len(lbin)))

    # ── LES SWITCHES RÉSERVÉS EN `effect` (2026-09-21) ───────────────────────────────────
    # Même exigence que la bank looper : sans réservation le binaire ne bouge pas d'un bit ;
    # avec, il compile, tient, se redécode — et SEULS les switches demandés changent d'espèce.
    print("Switches réservés (diode on/off sur la rangée des scènes)")
    cneutre = uno2.build_binary(gen.build(contract, dev, claim_slots={}))
    ok("sans réservation, le binaire est inchangé", cneutre == binary)
    cset = gen.build(contract, dev, claim_slots={0: [4, 5]})
    cbin = uno2.build_binary(cset)
    ok("une bank à switches réservés compile et grossit", len(cbin) > len(binary),
       "%d -> %d octets" % (len(binary), len(cbin)))
    ok("elle tient dans le budget", uno2.setup_length(cset) <= uno2.BUDGET)
    cgood, cwhy = check_roundtrip(uno2.to_sysex(cbin), cbin)
    ok("son dump se redécode", cgood, cwhy)
    b0, b1 = cset.banks[0].switches, cset.banks[1].switches
    ok("dans CETTE bank, seuls SW4 et SW5 changent d'espèce",
       [i for i in range(10) if b0[i] != b1[i]] == [3, 4], str([i + 1 for i in range(10) if b0[i] != b1[i]]))
    ok("les autres banks gardent leurs cinq scènes",
       list(b1) == list(gen.build(contract, dev).banks[1].switches))
    c19 = uno2.build_binary(gen.build(contract, dev, claim_slots={n: [4, 5] for n in range(19)}))
    ok("19 banks réservées ne coûtent pas plus qu'une (blocs partagés)", len(c19) == len(cbin),
       "%d vs %d octets" % (len(c19), len(cbin)))
    both = gen.build(contract, dev, looper_slots=(0,), claim_slots={0: [4]})
    ok("looper ET réservation dans la même bank : SW4 en effect, SW5 reste la scène (play all du looper)",
       both.banks[0].switches[3] != both.banks[1].switches[3]
       and both.banks[0].switches[4] == both.banks[1].switches[4])
    sel = int((contract.get("select") or {}).get("switch", 1))
    try:
        import sys as _sys
        _sys.path.insert(0, gen.ROOT)
        from bridge import store as _store
        fake = {"lanes": [], "config": {"rec": {"blocks": [{"id": "r", "type": "rec", "foot": sel}]}}}
        ok("le switch de sélection n'est jamais réservé en effect (son appui long a besoin du relâchement)",
           sel not in _store.toggle_claim_switches(fake, sel))
        ok("un backing SEUL garde ses fronts (tap / double-tap / appui long)",
           _store.claim_species([{"type": "backing-track"}]) == "gesture"
           and _store.claim_species([{"type": "backing-track"}, {"type": "rec"}]) == "toggle")
    except Exception as e:
        ok("la règle du rack se charge", False, str(e))

    # LA PUCE EST-ELLE À JOUR ? On compare ce que la setlist demande AUJOURD'HUI à ce qui a été
    # écrit au dernier flash (presets/.uno2-flashed.json). Un écart n'est pas une panne — le rack
    # bascule au lieu de lire un état, la diode reste en radio — mais il doit se DIRE.
    flashed_path = os.path.join(gen.ROOT, "presets", ".uno2-flashed.json")
    wanted = {str(k): v for k, v in sorted(gen.claim_slots_from_setlist(contract).items())}
    try:
        flashed = json.load(open(flashed_path, encoding="utf8")).get("effect_switches") or {}
        ok("la puce porte les switches réservés que la setlist demande aujourd'hui", flashed == wanted,
           "flashé %s, demandé %s — ./tools/fcb/flash_uno2.py --write" % (flashed, wanted))
    except (OSError, ValueError):
        print("  ·    aucun flash mémorisé sur cette machine (demandé : %s)" % (wanted or "rien"))

    print("Architecture")
    ok("bridge/foot.py ne porte plus le canal en dur", not foot_hardcodes_channel(),
       "le canal doit venir du descripteur — sinon ressouder l'autre puce rend le rack SOURD")
    all_devices, bad = {}, []
    for name in sorted(os.listdir(gen.DEVICES_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            d = json.load(open(os.path.join(gen.DEVICES_DIR, name), encoding="utf8"))
            all_devices[d["id"]] = d
            if (d.get("load") or {}).get("recipe") not in ("uno2", "uno104"):
                bad.append(name)
        except Exception as e:
            bad.append("%s (%s)" % (name, e))
    ok("les %d descripteurs se chargent et nomment une recette connue" % len(all_devices),
       all_devices and not bad, " · ".join(bad))
    ok("chaque descripteur déclare un canal valide",
       all(1 <= d.get("channel", 0) <= 16 for d in all_devices.values()))

    print("Cohérence de l'intention")
    ok("au moins un switch réclame des fronts (sinon aucun appui long)",
       any(s.get("gestures") for s in contract["stomps"]))
    unmet = gen.unmet_gestures(contract, dev)
    ok("l'appareil par défaut satisfait ce que l'intention réclame", not unmet,
       "switch(es) %s réclament des fronts que %s ne sait pas donner"
       % (", ".join(map(str, unmet)), dev["id"]))
    switches = [s["switch"] for s in contract["scenes"]] + [s["switch"] for s in contract["stomps"]]
    ok("aucun switch n'est réclamé deux fois", len(switches) == len(set(switches)),
       "doublons : %s" % sorted({s for s in switches if switches.count(s) > 1}))

    print("Témoin")
    try:
        with open(WITNESS, encoding="utf8") as fh:
            witness = json.load(fh)
    except Exception as e:
        ok("le témoin est lisible", False, str(e))
        witness = None
    if witness:
        same = witness["binary"] == digest["binary"] and witness["sysex"] == digest["sysex"]
        ok("les octets produits sont ceux du témoin", same,
           "témoin : %d octets / occupation %d\n        produit : %d octets / occupation %d\n"
           "        Si le changement est VOULU : ./tools/fcb/check-uno2.py --update"
           % (witness["binary_len"], witness["used"], digest["binary_len"], digest["used"]))

    print()
    if FAILED:
        print("%d vérification(s) en échec : %s" % (len(FAILED), " · ".join(FAILED)))
        return 1
    print("Tout est vert — %d octets, occupation %d / %d (%.1f %%)."
          % (len(binary), used, uno2.BUDGET, used / uno2.BUDGET * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
