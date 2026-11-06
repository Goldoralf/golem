#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Valide les descripteurs d'appareils — pédales et pédaliers.

    ./tools/check-descriptors.py            # tout
    ./tools/check-descriptors.py -v         # + le détail de chaque fichier

POURQUOI CE SCRIPT EXISTE (registre §8.4)
Un descripteur dit au rack quoi envoyer à un appareil et quoi régler dessus. Il est écrit à la
main, parfois importé d'un tiers, et **il a l'air autorisé même quand il est faux** — c'est tout
son danger. Une table de PC décalée ne se découvre qu'au pied, en répète, un mardi soir.

Ce qu'on attrape ici est bête et suffisant : un `id` qui ne correspond plus à son fichier, un PC
hors bornes, deux modes sur le même PC, un `schema` qu'on ne sait pas lire, un geste d'install que
le rack n'offre pas, une provenance qui ment sur son vocabulaire. L'essentiel des mauvaises
contributions tombe là-dedans.

⚠ CE QU'IL NE PEUT PAS FAIRE, et qu'il ne faut pas lui demander : dire si la TABLE est juste.
« Le PC 12 donne-t-il vraiment le Small Plate ? » ne se répond qu'en branchant la pédale. C'est
la raison d'être de `provenance.confidence` — et la raison pour laquelle ce script REFUSE de
laisser passer une confiance non déclarée.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Où vivent les descripteurs. `mappings/` est de l'état local (hors dépôt) : on le valide s'il est
# là, sans exiger sa présence — le rack de quelqu'un d'autre ne l'aura pas.
FAMILIES = [
    ("pédales (bibliothèque)", os.path.join(ROOT, "library", "pedals"), True),
    ("pédaliers", os.path.join(ROOT, "config", "pedalboard", "devices"), True),
    ("mappings locaux", os.path.join(ROOT, "mappings"), False),
    ("kits de batterie", os.path.join(ROOT, "config", "drumkits"), True),   # docs/drums-kit.md §3
]

SCHEMA_MAX = 2                                   # au-delà : écrit par un futur qu'on ne sait pas lire
KINDS = {"pedal", "controller", "pedalboard"}
CONNECTIONS = {"din", "usb", "usb+din"}
SOURCES = {"measured", "manual", "manual+hardware", "imported", "hardware"}
CONFIDENCES = {"verified", "reported", "unconfirmed"}
# gestes que le rack sait offrir DANS une étape — Linux : le rack envoie lui-même ;
# Windows/macOS : Control Center (docs/fcb/uno2/README.md, addendum 2026-10-02)
ACTIONS = {"fcb-flash", "pedalboard-load",
           "pedalboard-editor", "pedalboard-hold", "pedalboard-copy", "pedalboard-flashed"}
RECIPES = {"uno104", "uno2"}                     # recettes de charge résolues par le bridge (routes_system._LOAD_RECIPES)
NOTE_EDGES = {"paired", "clean"}
TRANSPORTS = {"din-soundcard", "usb"}            # par où le pédalier ARRIVE (foot.resolve_port)
SEND_VERBS = {"pc", "cc", "val", "sweep_cc"}     # vocabulaire de POST /api/calibrate/midi
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

PROBLEMS = []      # ce qui rend un descripteur INUTILISABLE -> code de sortie 1
NOTES = []         # ce qui mérite d'être su, sans être faux -> affiché, n'échoue pas


def bad(path, msg):
    PROBLEMS.append((os.path.relpath(path, ROOT), msg))


def note(path, msg):
    NOTES.append((os.path.relpath(path, ROOT), msg))


def _int_in(value, lo, hi):
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def check_common(path, d):
    """Ce que TOUT descripteur doit tenir."""
    name = os.path.splitext(os.path.basename(path))[0]
    if not isinstance(d.get("id"), str) or not SLUG.match(d.get("id") or ""):
        bad(path, "`id` manquant ou pas un slug (minuscules, chiffres, tirets)")
    elif d["id"] != name:
        # L'id est la clé stable : les setlists, les presets et les états y renvoient. Le fichier
        # qui ne porte pas son id se renomme un jour, et les renvois pointent dans le vide.
        bad(path, "`id` = %r mais le fichier s'appelle %r — ils doivent coïncider" % (d["id"], name))
    if not d.get("name"):
        bad(path, "`name` manquant (c'est ce que l'écran affiche)")
    if d.get("kind") not in KINDS:
        bad(path, "`kind` = %r, attendu %s" % (d.get("kind"), " | ".join(sorted(KINDS))))
    if not _int_in(d.get("schema"), 1, SCHEMA_MAX):
        bad(path, "`schema` = %r : absent, ou plus récent que ce que ce rack sait lire (max %d)"
            % (d.get("schema"), SCHEMA_MAX))

    ident = d.get("identity")
    if not isinstance(ident, dict):
        bad(path, "`identity` manquante")
    else:
        for k in ("brand", "model"):
            if not ident.get(k):
                bad(path, "`identity.%s` manquant" % k)
        if ident.get("connection") not in CONNECTIONS:
            bad(path, "`identity.connection` = %r, attendu %s"
                % (ident.get("connection"), " | ".join(sorted(CONNECTIONS))))

    if _int_in(d.get("channel"), 1, 16) is False and "channel" in d:
        bad(path, "`channel` = %r hors 1-16" % d.get("channel"))

    prov = d.get("provenance")
    if not isinstance(prov, dict):
        # Sans provenance, rien ne distingue une table mesurée d'une table recopiée d'un PDF.
        bad(path, "`provenance` manquante — on ne saurait pas à quel point y croire")
    else:
        if prov.get("source") not in SOURCES:
            bad(path, "`provenance.source` = %r, attendu %s"
                % (prov.get("source"), " | ".join(sorted(SOURCES))))
        if prov.get("confidence") not in CONFIDENCES:
            bad(path, "`provenance.confidence` = %r, attendu %s"
                % (prov.get("confidence"), " | ".join(sorted(CONFIDENCES))))
        if not prov.get("note"):
            bad(path, "`provenance.note` vide — d'où vient cette information ?")

    check_install(path, d.get("install"))
    if d.get("install_desktop") is not None:
        check_install(path, d.get("install_desktop"))
    check_verify(path, d.get("verify"))


def check_install(path, install):
    if install is None:
        return                                   # rien à régler sur l'appareil : légitime
    if not isinstance(install, dict):
        bad(path, "`install` n'est pas un objet")
        return
    # `needs` est AFFICHÉ en tête du stepper : il tombe donc sous la règle de l'interface en
    # anglais, au même titre que les étapes. Repris tel quel d'une archive française, il est
    # passé en revue sans être vu (descripteur UnO 1.0.4, corrigé le 2026-08-06).
    for n in (install.get("needs") or []):
        if _looks_french(n):
            bad(path, "`install.needs` a l'air d'être en FRANÇAIS : %r — l'interface est en anglais"
                % (n[:60] + ("…" if len(n) > 60 else "")))
    phases = install.get("phases")
    if not isinstance(phases, list) or not phases:
        bad(path, "`install.phases` vide")
        return
    for pi, phase in enumerate(phases):
        steps = (phase or {}).get("steps")
        if not isinstance(steps, list) or not steps:
            bad(path, "phase %d (%r) sans étapes" % (pi, (phase or {}).get("name")))
            continue
        for si, step in enumerate(steps):
            where = "phase %d étape %d" % (pi, si)
            if not (step.get("title") and step.get("do")):
                bad(path, "%s : `title` et `do` sont obligatoires (c'est ce qu'on lit au pied)" % where)
            act = step.get("action")
            if act is not None and act not in ACTIONS:
                bad(path, "%s : geste %r inconnu du rack (connus : %s) — le bouton ne s'afficherait pas"
                    % (where, act, ", ".join(sorted(ACTIONS))))
            for key in ("title", "do", "hint", "badge"):
                if _looks_french(step.get(key)):
                    bad(path, "%s : `%s` a l'air d'être en FRANÇAIS — l'interface est en anglais" % (where, key))


# Mots outils qui n'existent qu'en français : suffisant pour attraper une étape recopiée telle
# quelle depuis des notes, et assez étroit pour ne pas crier sur « Plug the cable ».
_FR = re.compile(r"\b(le|la|les|du|des|une|un|puis|avec|sur|dans|pour|est|sont|qui|que|ce|cette|"
                 r"tu|vous|il faut|ensuite|jusqu|câbl|brancher|appuie|maintenu|allumé)\b", re.I)


def _looks_french(text):
    return isinstance(text, str) and len(_FR.findall(text)) >= 2


def check_verify(path, verify):
    if verify is None:
        return
    checks = (verify or {}).get("checks")
    if not isinstance(checks, list) or not checks:
        bad(path, "`verify.checks` vide")
        return
    for ci, chk in enumerate(checks):
        if not (chk.get("label") and chk.get("expect")):
            bad(path, "vérification %d : `label` et `expect` sont obligatoires" % ci)
        send = chk.get("send")
        if send is None:
            continue
        if not isinstance(send, dict) or not send:
            bad(path, "vérification %d : `send` n'est pas un objet" % ci)
            continue
        for verb, value in send.items():
            if verb not in SEND_VERBS:
                bad(path, "vérification %d : verbe %r inconnu (connus : %s)"
                    % (ci, verb, ", ".join(sorted(SEND_VERBS))))
            elif not _int_in(value, 0, 127):
                bad(path, "vérification %d : %s = %r hors 0-127" % (ci, verb, value))


def check_pedal(path, d):
    """Une pédale porte des `modes` : c'est sa table, et c'est là que ça se décale."""
    modes = d.get("modes")
    if d.get("kind") == "pedal" and not modes:
        bad(path, "`kind` = pedal mais aucun `modes` — une pédale sans table ne pilote rien")
    if not isinstance(modes, list):
        return
    seen, dupes = {}, []
    for mi, mode in enumerate(modes):
        if not (mode or {}).get("name"):
            bad(path, "mode %d sans `name`" % mi)
        for key in ("active_pc", "bypass_pc", "pc"):
            if key not in (mode or {}):
                continue
            pc = mode[key]
            if not _int_in(pc, 0, 127):
                bad(path, "mode %r : %s = %r hors 0-127" % (mode.get("name"), key, pc))
            elif key == "active_pc":
                if pc in seen:
                    dupes.append((pc, seen[pc], mode.get("name")))
                else:
                    seen[pc] = mode.get("name")

    # ⚠ UN PC EN DOUBLE N'EST PAS FORCÉMENT UNE ERREUR — mais c'est toujours une AMBIGUÏTÉ.
    # Les tables importées de MIDNAM sont organisées en banques que le format ne capture pas :
    # la banque ne vit que dans le préfixe du nom (« 100 … » / « 200 … »), pas dans un champ.
    # Envoyer ce PC sélectionne donc ce que la pédale a sous la main, et personne ne sait quoi.
    # On refuse une seule chose, et c'est la bonne : qu'une table ambiguë se dise VÉRIFIÉE.
    if dupes:
        conf = (d.get("provenance") or {}).get("confidence")
        pc, first, second = dupes[0]
        if conf == "verified":
            bad(path, "%d PC en double (ex. %d : « %s » et « %s ») dans une table déclarée "
                      "`verified` — une table ambiguë ne peut pas avoir été vérifiée : soit la "
                      "banque manque, soit la confiance est usurpée"
                % (len(dupes), pc, first, second))
        else:
            note(path, "%d PC en double (ex. %d : « %s » et « %s ») — banques non capturées par "
                       "l'import ; cohérent avec `%s`, à lever en mesurant au pied"
                 % (len(dupes), pc, first, second, conf))


def check_pedalboard(path, d):
    """Un pédalier ne porte pas de table de modes : il porte un canal, des travers, une recette."""
    if d.get("modes"):
        bad(path, "un pédalier ne devrait pas porter de `modes` (c'est le marqueur d'une pédale)")
    if not _int_in(d.get("channel"), 1, 16):
        bad(path, "`channel` = %r : un pédalier DOIT déclarer son canal, sinon le rack est sourd"
            % d.get("channel"))
    edges = (d.get("quirks") or {}).get("note_edges")
    if edges not in NOTE_EDGES:
        bad(path, "`quirks.note_edges` = %r, attendu %s — appliquer le mauvais rattrapage INVERSE "
                  "les appuis et les relâchements" % (edges, " | ".join(sorted(NOTE_EDGES))))
    for key in ("note_base", "display_base"):
        val = (d.get("quirks") or {}).get(key)
        if val is not None and not _int_in(val, 0, 1):
            bad(path, "`quirks.%s` = %r, attendu 0 ou 1" % (key, val))

    caps = d.get("capabilities") or {}
    goto = caps.get("goto_bank") or {}
    if goto.get("supported"):
        if not _int_in(goto.get("channel"), 1, 16):
            bad(path, "`capabilities.goto_bank.channel` = %r hors 1-16" % goto.get("channel"))
        for key in ("controller", "index_base"):
            if key in goto and not _int_in(goto[key], 0, 127):
                bad(path, "`capabilities.goto_bank.%s` = %r hors 0-127" % (key, goto[key]))

    # `transport` : optionnel (défaut = din-soundcard), mais s'il est là il doit être utilisable
    # — un pédalier USB sans motif de port est INTROUVABLE, et le lecteur réessaierait en boucle
    # sans jamais rien entendre.
    tr = d.get("transport")
    if tr is not None:
        kind = tr.get("kind") if isinstance(tr, dict) else tr
        if not isinstance(tr, dict) or kind not in TRANSPORTS:
            bad(path, "`transport.kind` = %r, attendu %s — le lecteur ne saurait pas OÙ écouter"
                % (kind, " | ".join(sorted(TRANSPORTS))))
        elif kind == "usb" and not (isinstance(tr.get("port_match"), str) and tr["port_match"].strip()):
            bad(path, "`transport.port_match` manquant — un pédalier USB sans motif de nom ALSA "
                      "est introuvable")

    recipe = (d.get("load") or {}).get("recipe")
    if recipe is not None and recipe not in RECIPES:
        bad(path, "recette de charge %r inconnue du bridge (connues : %s) — le bouton refuserait"
            % (recipe, ", ".join(sorted(RECIPES))))
    if recipe and not (d.get("load") or {}).get("label"):
        bad(path, "`load.label` manquant — le bouton n'aurait pas d'intitulé")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    total = 0
    for label, folder, required in FAMILIES:
        if not os.path.isdir(folder):
            if required:
                print("  ÉCHEC %s : dossier absent (%s)" % (label, os.path.relpath(folder, ROOT)))
                PROBLEMS.append((os.path.relpath(folder, ROOT), "dossier absent"))
            continue
        files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
        print("%s — %d fichier(s)" % (label, len(files)))
        for f in files:
            path = os.path.join(folder, f)
            total += 1
            try:
                with open(path, encoding="utf8") as fh:
                    d = json.load(fh)
            except Exception as e:
                bad(path, "JSON illisible : %s" % e)
                continue
            before = len(PROBLEMS)
            if d.get("kind") == "drumkit":
                # même validation que le bridge (drumkits.validate) : un fichier que le rack refuserait
                # de charger doit échouer ICI, avant d'être poussé sur un rack
                sys.path.insert(0, ROOT)
                from bridge import drumkits as _dk
                for msg in _dk.validate(d, os.path.splitext(f)[0]):
                    bad(path, msg)
                if not (d.get("identity") or {}).get("usb_names") and d.get("id") != _dk.FALLBACK:
                    note(path, "aucun `identity.usb_names` : ce kit ne sera jamais identifié tout seul, il faudra le choisir")
                if (d.get("provenance") or {}).get("confidence") == "unconfirmed":
                    note(path, "table SUPPOSÉE (unconfirmed) — mesurer ce module avant de s'y fier (check-drums.py, lot 4)")
            else:
                check_common(path, d)
                if d.get("kind") == "pedalboard":
                    check_pedalboard(path, d)
                else:
                    check_pedal(path, d)
            conf = (d.get("provenance") or {}).get("confidence", "?")
            if args.verbose or len(PROBLEMS) > before:
                print("  %s %-28s %s" % ("✗" if len(PROBLEMS) > before else "·", f, conf))

    print()
    if NOTES:
        print("À savoir — rien de faux, mais rien de garanti non plus :")
        for path, msg in NOTES:
            print("  %s\n      %s" % (path, msg))
        print()
    if PROBLEMS:
        print("%d problème(s) sur %d descripteur(s) :" % (len(PROBLEMS), total))
        for path, msg in PROBLEMS:
            print("  %s\n      %s" % (path, msg))
        return 1
    print("%d descripteurs valides." % total)
    print("⚠ Valide n'est pas JUSTE : ce script ne peut pas savoir si une table de PC dit vrai.")
    print("  C'est `provenance.confidence` qui porte cette question, et seul le pied y répond.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
