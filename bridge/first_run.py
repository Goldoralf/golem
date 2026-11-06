# SPDX-License-Identifier: GPL-3.0-or-later
"""L'INSTRUMENT choisi à l'installation (docs/installer.md, écran « What do you play? », 2026-10-27).

L'installateur écrit `config/first-run.json` = {"instrument": "bass"} dans le dossier installé ; le bridge le lit
UNE fois au démarrage (après l'usine, avant le rappel de démarrage), applique, puis le retire :
  · `config/instrument.json` garde l'instrument : l'entrée 1 d'une carte vue pour la première fois naît sur ce rôle
    (inputmap._seed) — seulement guitare, basse, voix ; claviers et batterie arrivent en USB-MIDI, l'entrée 1 reste
    guitare ;
  · la banque d'usine de l'instrument va sur le pied, si aucune setlist n'a été choisie ;
  · guitare : la banque d'usine s'ouvre au démarrage sur sa première entrée (Jazz Clean), si aucun accueil n'est
    réglé. Pas un preset hors de la banque (Chill Jazz jusqu'au 2026-11-03) : /live disait « not in Factory Guitar »
    et cachait les flèches de banque, on croyait la banque pas chargée.
Une réinstallation par-dessus une installation n'écrase rien de ce que l'utilisateur a déjà réglé."""
import json
import os

from . import config as C
from .golog import get

log = get("first_run")

INSTRUMENTS = ("guitar", "bass", "keys", "drums", "voice")
INPUT_ROLE = {"guitar": "guitar", "bass": "bass", "voice": "voice"}    # le rôle de l'entrée 1 ; absent = guitare
BANK = {i: "factory-" + i for i in INSTRUMENTS}
HOME = {"guitar": {"kind": "setlist", "id": BANK["guitar"], "name": "Factory Guitar"}}


def _first_run_path():
    return os.path.join(C.CONFIG_DIR, "first-run.json")


def _instrument_path():
    return os.path.join(C.CONFIG_DIR, "instrument.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def instrument():
    """L'instrument noté à l'installation, ou None (une installation d'avant le 2026-10-27)."""
    i = _read(_instrument_path()).get("instrument")
    return i if i in INSTRUMENTS else None


def input_role():
    """Le rôle de l'entrée 1 d'une carte neuve : celui de l'instrument choisi, guitare sinon."""
    return INPUT_ROLE.get(instrument(), "guitar")


def apply():
    """Applique `config/first-run.json` s'il est là, puis le retire. Rend ce qui a été fait (liste), ou None."""
    path = _first_run_path()
    if not os.path.isfile(path):
        return None
    inst = _read(path).get("instrument")
    done = []
    if inst in INSTRUMENTS:
        from .store import _write_json_atomic
        _write_json_atomic(_instrument_path(), {"instrument": inst}, indent=1)
        done.append(f"instrument {inst}")
        from . import setlists, startup_home
        # la banque : seulement si personne n'a encore choisi la liste au pied
        if not os.path.isfile(setlists._active_cfg()):
            r = setlists.set_active(BANK[inst])
            done.append(f"bank {BANK[inst]}" if r.get("ok") else f"bank {BANK[inst]} refused: {r.get('error')}")
        if inst in HOME and not os.path.isfile(startup_home.PATH):
            try:
                startup_home.set_home(HOME[inst])
                done.append(f"startup {HOME[inst]['id']}")
            except ValueError as e:
                done.append(f"startup refused: {e}")
    else:
        done.append(f"unknown instrument {inst!r} ignored")
    try:
        os.remove(path)
    except OSError as e:
        log.warning(f"premier démarrage : {path} non retiré ({e})")
    log.info("premier démarrage : " + ", ".join(done))
    return done
