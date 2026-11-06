#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""POC Whammy DT — prouve que GoleM peut piloter la Whammy DT en MIDI via le MIDI OUT du Volt.

Sans dépendance pip : utilise `amidi` (ALSA, paquet alsa-utils). Sur le rack Linux, rien à installer.

Usage :
  python3 tools/whammy_poc.py --list                    # liste les ports MIDI
  python3 tools/whammy_poc.py                            # auto-détecte "Volt", joue la démo
  python3 tools/whammy_poc.py --port hw:2,0,0           # port explicite (voir --list)
  python3 tools/whammy_poc.py --mode "Dive Bomb (↓2 Oct)"
  python3 tools/whammy_poc.py --dry-run                 # affiche les messages, n'envoie rien

Démo : active le mode (Program Change), balaye le treadle (CC11 0->127->0), puis bypass.
Si le pitch monte/plonge pendant le balayage => la Whammy est bien pilotée. ✅

NB : amidi ouvre le port à chaque message (POC). Le chemin temps-réel final utilisera une
connexion persistante (python-rtmidi) ou une piste MIDI Reaper -> hardware out.
"""
import argparse, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHAMMY_JSON = os.path.join(ROOT, "mappings", "whammy-dt.json")


def amidi_list():
    try:
        return subprocess.check_output(["amidi", "-l"], text=True)
    except FileNotFoundError:
        sys.exit("amidi introuvable → installe alsa-utils (sudo apt install alsa-utils).")


def find_volt_port():
    for line in amidi_list().splitlines():
        if "volt" in line.lower():
            for tok in line.split():
                if tok.startswith("hw:"):
                    return tok
    return None


def hexmsg(*bytes_):
    return " ".join("%02X" % b for b in bytes_)


def send(port, msg, dry):
    print(("  [dry] " if dry else "  -> ") + msg)
    if not dry:
        subprocess.run(["amidi", "-p", port, "-S", msg], check=True)


def main():
    ap = argparse.ArgumentParser(description="POC pilotage Whammy DT en MIDI")
    ap.add_argument("--list", action="store_true", help="liste les ports MIDI et quitte")
    ap.add_argument("--port", help="port ALSA (ex. hw:2,0,0)")
    ap.add_argument("--mode", help="nom du mode (défaut = default_mode du json)")
    ap.add_argument("--channel", type=int, help="canal MIDI (1-16)")
    ap.add_argument("--dry-run", action="store_true", help="affiche sans envoyer")
    args = ap.parse_args()

    if args.list:
        print(amidi_list())
        return

    with open(WHAMMY_JSON) as f:
        w = json.load(f)
    ch = args.channel or w.get("channel", 1)
    treadle_cc = w.get("treadle_cc", 11)
    mode_name = args.mode or w.get("default_mode")
    mode = next((m for m in w.get("modes", []) if m["name"] == mode_name), None)
    if not mode:
        sys.exit("mode '%s' absent de %s (modes: %s)" %
                 (mode_name, WHAMMY_JSON, ", ".join(m["name"] for m in w.get("modes", []))))
    active_pc = mode.get("active_pc", mode.get("pc"))
    bypass_pc = mode.get("bypass_pc")

    port = args.port or find_volt_port()
    if not port and not args.dry_run:
        sys.exit("Port Volt introuvable. Lance `--list` puis `--port hw:X,Y,Z`.")
    port = port or "hw:?,?,?"

    pc_status = 0xC0 + (ch - 1)
    cc_status = 0xB0 + (ch - 1)

    print("Port %s · canal %d · mode '%s' (actif PC%s, bypass PC%s) · treadle CC%d"
          % (port, ch, mode_name, active_pc, bypass_pc, treadle_cc))

    print("[1/3] active le mode")
    send(port, hexmsg(pc_status, active_pc), args.dry_run)
    time.sleep(0.3)

    print("[2/3] balayage treadle 0 -> 127 -> 0")
    sweep = list(range(0, 128, 8)) + [127] + list(range(120, -1, -8)) + [0]
    for v in sweep:
        send(port, hexmsg(cc_status, treadle_cc, v), args.dry_run)
        time.sleep(0.03)

    if bypass_pc is not None:
        print("[3/3] bypass")
        send(port, hexmsg(pc_status, bypass_pc), args.dry_run)
    print("\nOK. Si le pitch a bougé pendant le balayage, la Whammy DT est pilotée par GoleM. ✅")


if __name__ == "__main__":
    main()
