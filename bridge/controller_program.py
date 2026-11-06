# SPDX-License-Identifier: GPL-3.0-or-later
"""DONNER AUX PADS LEUR PROPRE CANAL — programmer un contrôleur clavier+pads depuis le rack (2026-10-13).

Pourquoi : quand les pads et le clavier d'un contrôleur envoient sur le MÊME canal, aucun logiciel ne peut distinguer
un pad d'une touche — chaque pad joue aussi une note dans l'instrument de la lane Keys (mesuré sur l'AKAI MPK Mini Mk II
du mainteneur : tout sur le canal 1, et une rangée de pads sur les mêmes notes que les touches graves). La seule vraie
séparation est DANS le contrôleur : pads sur le canal 10, chaque pad sur la note GM de son son (kits.DEFAULT_NOTES).

Générique : ce module ne connaît AUCUN modèle. Ce qu'il faut savoir d'un modèle (comment lire un programme, où sont le
canal des pads, celui du clavier, les notes des pads ; quel programme est la mémoire de travail) est en DONNÉES, dans
`config/controller-models/<id>.json` (`program.kind: "sysex-dump"`). Un nouveau contrôleur = un descripteur, pas de code.
Un modèle sans descripteur se règle dans l'éditeur de son fabricant ; la calibration MESURE ensuite les canaux (profil,
bridge/controllers.py) et le moteur trie pareil.

Le transport : Reaper tient le contrôleur en EXCLUSIF ; on passe par sa piste « SysexIO » (golem_drumlearn.lua, prise
"sysex", sysex-io.jsfx). Rien n'est écrit sans avoir été LU ; chaque écriture est RELUE ; l'original de chaque programme
touché est gardé (presets/.controller-backup.json, jamais écrasé)."""
import glob
import json
import os
import time

from . import config as C
from .commands import write_command

MODELS_DIR = os.path.join(C.CONFIG_DIR, "controller-models")
BACKUP = os.path.join(C.PRESETS_DIR, ".controller-backup.json")
LIVE = C.runtime_file("golem-drumlearn.json")

# LA CIBLE (la même pour tous les modèles) : pads sur le canal 10, notes GM au placement MPC (kits.DEFAULT_NOTES)
PADS_CHANNEL = 10


# ── les descripteurs ────────────────────────────────────────────────────────────────────────────

def models():
    out = []
    for p in sorted(glob.glob(os.path.join(MODELS_DIR, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("kind") == "controller-model" and d.get("id"):
            out.append(d)
    return out


def model_for(usb="", name=""):
    """Le descripteur de CE contrôleur : VID:PID d'abord, sinon un nom contenu dans l'autre (règle devices._match)."""
    usb, nm = (usb or "").lower(), (name or "").strip().lower()
    for m in models():
        if usb and usb in [u.lower() for u in m.get("usb") or []]:
            return m
    if nm:
        for m in models():
            for n in [m.get("name") or ""] + list(m.get("names") or []):
                n = n.strip().lower()
                if n and (n in nm or nm in n):
                    return m
    return None


def can_program(model):
    return bool(model and (model.get("program") or {}).get("kind") == "sysex-dump")


# ── le format, lu dans le descripteur ───────────────────────────────────────────────────────────

def _spec(model):
    sp = (model or {}).get("program") or {}
    if sp.get("kind") != "sysex-dump":
        raise ValueError(f"{(model or {}).get('id')} : no SysEx program recipe")
    return sp


def read_request(model, prog):
    return bytes.fromhex(_spec(model)["read"].replace("{prog}", "%02x" % (prog & 0x7F)))


def decode(model, data):
    """Le programme lu, en clair — ou ValueError si ce n'est pas un dump de CE modèle."""
    sp, d = _spec(model), bytes(data)
    head = bytes.fromhex(sp["header"])
    ca = sp["command_at"]
    if (len(d) != sp["length"] or d[0] != 0xF0 or d[-1] != 0xF7 or not d.startswith(head)
            or d[ca] not in (sp["command_dump"], sp["command_load"])):
        raise ValueError(f"not a {model.get('name')} program ({len(d)} bytes, head {d[:5].hex()})")
    base, pn = int(sp.get("channel_base", 0)), sp["pad_notes"]
    notes = [d[pn["at"] + i * pn["stride"]] for i in range(pn["count"])]
    return {"prog": d[sp["prog_at"]], "pad_ch": d[sp["pad_channel_at"]] - base + 1,
            "key_ch": d[sp["key_channel_at"]] - base + 1, "notes": notes}


def target_notes(model):
    """Les notes GM au placement MPC (kits.DEFAULT_NOTES), autant que le modèle a de pads."""
    from .kits import DEFAULT_NOTES
    return list(DEFAULT_NOTES[:_spec(model)["pad_notes"]["count"]])


def patched(model, data, prog=None):
    """Le même programme, pads sur le canal 10 et notes GM au placement MPC — RIEN d'autre ne change. Prêt à ENVOYER (commande load)."""
    sp = _spec(model)
    decode(model, data)
    d = bytearray(data)
    d[sp["command_at"]] = sp["command_load"]
    if prog is not None:
        d[sp["prog_at"]] = prog & 0x7F
    d[sp["pad_channel_at"]] = PADS_CHANNEL - 1 + int(sp.get("channel_base", 0))
    pn = sp["pad_notes"]
    for i, n in enumerate(target_notes(model)):
        d[pn["at"] + i * pn["stride"]] = n
    return bytes(d)


def is_target(model, data):
    p = decode(model, data)
    return p["pad_ch"] == PADS_CHANNEL and p["notes"] == target_notes(model) and p["key_ch"] != PADS_CHANNEL


# ── le transport par Reaper ──────────────────────────────────────────────────────────────────────

def _live():
    try:
        with open(LIVE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def open_io(dev_in, dev_out, timeout=4.0):
    write_command({"action": "drumlearn", "on": True, "tap": "sysex", "dev": dev_in, "out": dev_out})
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = _live()
        if st.get("on") and st.get("tap") == "sysex":
            if st.get("err"):
                raise RuntimeError(st["err"])
            return st
        time.sleep(0.1)
    raise RuntimeError("REAPER did not open the SysEx track (is the audio engine running ?)")


def close_io():
    write_command({"action": "drumlearn", "on": False})


def _send(data):
    write_command({"action": "drumlearn", "tx": bytes(data).hex()})


def exchange(data, timeout=3.0):
    """Envoie un SysEx et attend le SUIVANT reçu (le compteur avance) — rend ses octets, ou None."""
    before = ((_live().get("sysex") or {}).get("n")) or 0
    _send(data)
    t0 = time.time()
    while time.time() - t0 < timeout:
        sx = _live().get("sysex") or {}
        if (sx.get("n") or 0) > before and sx.get("hex"):
            return bytes.fromhex(sx["hex"])
        time.sleep(0.05)
    return None


def read_program(model, prog):
    raw = exchange(read_request(model, prog))
    if raw is None:
        raise RuntimeError(f"the controller did not answer for program {prog}")
    decode(model, raw)
    return raw


def setup(model, dev_in, dev_out=None):
    """Programme `stored` (lu, gardé, écrit, RELU) puis la mémoire de travail `working` — écrire un programme
    l'enregistre, mais le contrôleur continue de jouer ce qu'il a chargé (mesuré sur l'AKAI, 2026-10-13).
    Rend {"ok", "stored": {before, after}, "working": {...}|None, "pad_ch", "key_ch"}. Ferme la piste quoi qu'il arrive."""
    sp = _spec(model)
    stored, working = int(sp.get("stored", 1)), sp.get("working")
    try:
        open_io(dev_in, dev_out or dev_in)
        try:
            with open(BACKUP, encoding="utf-8") as f:
                backup = json.load(f)
        except (OSError, ValueError):
            backup = {}
        raw = read_program(model, stored)
        backup.setdefault(model["id"], {}).setdefault(str(stored), raw.hex())      # l'ORIGINAL, jamais écrasé
        os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
        with open(BACKUP, "w", encoding="utf-8") as f:
            json.dump(backup, f, indent=1)
        before = decode(model, raw)
        if not is_target(model, raw):
            _send(patched(model, raw, stored))
            time.sleep(0.4)
            raw = read_program(model, stored)
        out = {"stored": {"prog": stored, "before": before, "after": decode(model, raw)}, "working": None}
        ok = is_target(model, raw)
        if ok and working is not None:
            ram = read_program(model, int(working))
            if not is_target(model, ram):
                _send(patched(model, raw, int(working)))
                time.sleep(0.4)
                ram = read_program(model, int(working))
            out["working"] = {"prog": int(working), "after": decode(model, ram)}
            ok = is_target(model, ram)
        after = decode(model, raw)
        return {"ok": ok, **out, "pad_ch": after["pad_ch"], "key_ch": after["key_ch"], "notes": after["notes"]}
    finally:
        close_io()
