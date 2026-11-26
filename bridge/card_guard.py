# SPDX-License-Identifier: GPL-3.0-or-later
"""LA CARTE DE GOLEM N'EST PAS CELLE DU BUREAU (2026-11-26, docs/pitfalls/reaper.md « The desktop sound can hold golem's card »).

golem ouvre sa carte en ALSA BRUT (REAPER `linux_audio_mode=1`, le Golem Engine par son backend ALSA) : un seul
programme à la fois. Sous Ubuntu, PipeWire (le son du bureau) prend la même carte dès qu'une application joue — la
carte USB branchée devient la sortie par défaut. Rack Linux, 2026-11-26 : Firefox jouait (page golem.fm de
l'appairage), PipeWire tenait `pcmC1D0p`, REAPER a démarré sans carte, et l'écran restait sur « Still starting. » —
deux redémarrages de golem et un rebranchement de la carte n'y changeaient rien.

Deux gestes, Linux seulement, coupables par GOLEM_CARD_GUARD=0 :
  guard()     — la carte active de golem est RETIRÉE à PipeWire : son profil passe à « off » tout de suite (wpctl), et
                une règle WirePlumber (`device.disabled`) la tient hors du bureau aux sessions suivantes. Le son du
                bureau part sur une autre sortie (les haut-parleurs du PC).
  held()      — qui tient la carte, quand le moteur ne l'a pas : les processus (lus dans /proc), et derrière PipeWire
                les applications qui jouent dessus (pw-dump). Ce que Health dit, au lieu de « Still starting. ».
"""
import contextlib
import json
import os
import re
import subprocess
import sys

from . import config as C
from .golog import get

log = get("card_guard")

RULE = os.path.expanduser("~/.config/wireplumber/wireplumber.conf.d/90-golem-card.conf")
ENGINE_NAMES = ("reaper", "luasession")             # les moteurs de golem : eux PEUVENT tenir la carte
DESKTOP_SERVERS = ("pipewire", "wireplumber", "pulseaudio")
_PCM = re.compile(r"^pcmC(\d+)D\d+[pc]$")
_ID = re.compile(r"^[A-Za-z0-9_\-]+$")             # un id ALSA (« iTwo », « V276 ») : rien d'autre n'entre dans la règle
_done = {"cid": None}


def enabled():
    return sys.platform.startswith("linux") and os.environ.get("GOLEM_CARD_GUARD", "1") != "0"


def card_number(cid, asound="/proc/asound"):
    """Le numéro ALSA de la carte `cid` (/proc/asound/<id> est un lien vers cardN), None si absente."""
    if not cid or not _ID.match(str(cid)):
        return None
    m = re.search(r"card(\d+)$", os.path.realpath(os.path.join(asound, str(cid))))
    return int(m.group(1)) if m and os.path.isdir(os.path.join(asound, f"card{m.group(1)}")) else None


def holders(n, proc="/proc"):
    """Les processus qui ont un PCM de la carte n ouvert : [{pid, name}]. Les processus illisibles sont sautés."""
    out = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        fd_dir = os.path.join(proc, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        hit = False
        for fd in fds:
            with contextlib.suppress(OSError):
                m = _PCM.match(os.path.basename(os.readlink(os.path.join(fd_dir, fd))))
                if m and int(m.group(1)) == n:
                    hit = True
                    break
        if hit:
            name = ""
            with contextlib.suppress(OSError):
                with open(os.path.join(proc, pid, "comm"), encoding="utf-8", errors="replace") as f:
                    name = f.read().strip()
            out.append({"pid": int(pid), "name": name})
    return out


def _pw_dump():
    try:
        r = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def _props(o):
    return ((o or {}).get("info") or {}).get("props") or {}


def desktop_apps(n, dump):
    """Les applications du bureau qui jouent sur (ou écoutent) la carte n à travers PipeWire, par leur nom."""
    nodes = {o["id"]: _props(o) for o in dump if str(o.get("type", "")).endswith(":Node")}
    card_nodes = {i for i, p in nodes.items() if str(p.get("alsa.card", p.get("api.alsa.pcm.card"))) == str(n)}
    apps = []
    for o in dump:
        if not str(o.get("type", "")).endswith(":Link"):
            continue
        info = o.get("info") or {}
        a, b = info.get("output-node-id"), info.get("input-node-id")
        other = a if b in card_nodes else b if a in card_nodes else None
        if other is None or other in card_nodes:
            continue
        p = nodes.get(other) or {}
        name = p.get("application.name") or p.get("node.description") or p.get("node.name")
        if name and name not in apps:
            apps.append(str(name))
    return apps


def held(cid=None):
    """Qui tient la carte active quand ce n'est pas un moteur de golem : {card, number, holders, apps, desktop} ou None.
    `desktop` : c'est le serveur son du bureau (PipeWire) — guard() peut la lui reprendre."""
    if not enabled():
        return None
    cid = cid or C.alsa_card()
    n = card_number(cid)
    if n is None:
        return None
    hs = [h for h in holders(n) if h["name"] not in ENGINE_NAMES]
    if not hs:
        return None
    desktop = any(h["name"] in DESKTOP_SERVERS for h in hs)
    apps = desktop_apps(n, _pw_dump()) if desktop else []
    return {"card": cid, "number": n, "holders": hs, "apps": apps, "desktop": desktop}


def rule_text(cid):
    return ("# golem (bridge/card_guard.py) : la carte de golem ne sert pas au son du bureau — golem l'ouvre en ALSA\n"
            "# brut, un seul programme à la fois. Le bureau joue sur une autre sortie. Retirer ce fichier la rend au\n"
            "# bureau (après un redémarrage de session, ou systemctl --user restart wireplumber).\n"
            "monitor.alsa.rules = [\n"
            "  {\n"
            f"    matches = [ {{ alsa.id = \"{cid}\" }} ]\n"
            "    actions = { update-props = { device.disabled = true } }\n"
            "  }\n"
            "]\n")


def write_rule(cid, path=RULE):
    """Pose (ou met à jour) la règle WirePlumber pour la carte `cid`. Vrai si le fichier a changé."""
    if not cid or not _ID.match(str(cid)):
        return False
    text = rule_text(cid)
    with contextlib.suppress(OSError):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def release(cid, dump=None):
    """Passe la carte `cid` au profil « off » dans PipeWire, tout de suite : le bureau la lâche. Vrai si fait."""
    dump = _pw_dump() if dump is None else dump
    dev = next((o["id"] for o in dump if str(o.get("type", "")).endswith(":Device")
                and str(_props(o).get("alsa.id")) == str(cid)), None)
    if dev is None:
        return False                                  # PipeWire ne la voit pas (déjà retirée, ou pas de PipeWire)
    try:
        r = subprocess.run(["wpctl", "set-profile", str(int(dev)), "0"], capture_output=True, text=True, timeout=5,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def guard(cid=None, force=False):
    """La carte active hors du bureau : règle posée, profil « off ». Une fois par carte, sauf `force`. Rend ce qui a
    été fait : {card, rule, released} (ou None si coupé, pas de carte)."""
    if not enabled():
        return None
    cid = cid or C.alsa_card()
    if not cid or not _ID.match(str(cid)):
        return None
    if _done["cid"] == cid and not force:
        return None
    out = {"card": cid, "rule": False, "released": False}
    with contextlib.suppress(OSError):
        out["rule"] = write_rule(cid)
    out["released"] = release(cid)
    _done["cid"] = cid
    if out["rule"] or out["released"]:
        log.info(f"carte {cid} retirée au son du bureau (règle {'posée' if out['rule'] else 'déjà là'}, "
                 f"profil PipeWire {'off' if out['released'] else 'inchangé'})")
    return out


if __name__ == "__main__":                            # provision/start.sh, avant le moteur
    print(guard() or "card guard: nothing to do")
