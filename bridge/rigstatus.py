# SPDX-License-Identifier: GPL-3.0-or-later
"""Status rig -> golem.fm (contrat Addendum 13, demande « status rig » du dashboard web).

Deux canaux, comme le fingerprint :
  - PUSH périodique LÉGER (~5 min, thread daemon) : {firmware, reaper, disk, at}
    en PUT /api/ext/rig/status (Bearer token du pairing). Les sondes coûteuses
    (cpu/temp/ram) n'y sont PAS — décision Addendum 13.
  - Job on-demand `rig-status` (tones_jobs) : l'objet COMPLET en ack
    {firmware, reaper, cpu_pct, temp_c, ram, disk, at}.

Zéro dépendance (pas de psutil) : /proc/stat (cpu, 2 échantillons), /proc/meminfo (ram),
/sys/class/thermal (temp), shutil.disk_usage (disque), git describe (firmware = tag release,
fallback « dev »), reaper_update.installed_version (Reaper). Tout est TOLÉRANT : une sonde
qui échoue rend null, jamais d'exception. Le PUT sur un serveur qui n'expose pas encore
l'endpoint (404) est silencieux — golem.fm le câble de son côté.
"""
import glob
import os
import shutil
import subprocess
import sys
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("rig-status")

_PUSH_EVERY = 300          # push léger toutes les 5 min
_FIRST_PUSH = 15           # premier push peu après le boot (le temps que tout monte)


# ── sondes (toutes tolérantes : None si indisponible) ────────────────────────
def golem_version():
    """Tag release du repo (v0.18…) = « firmware » GoleM. Fallback dev/inconnu."""
    try:
        r = subprocess.run(["git", "-C", C.ROOT, "describe", "--tags", "--always", "--dirty"],
                           capture_output=True, text=True, timeout=3)
        v = r.stdout.strip()
        return v or "dev"
    except Exception:
        return "dev"


def reaper_version():
    try:
        from .reaper_update import installed_version
        return installed_version()
    except Exception:
        return None


def disk():
    """Le SSD local (volume de C.ROOT : presets/samples/Reaper) — LA jauge demandée."""
    try:
        u = shutil.disk_usage(C.ROOT)
        return {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
                "used_pct": round(100 * (u.total - u.free) / u.total)}
    except Exception:
        return None


def ram():
    if sys.platform == "win32":
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"total_mb": round(status.ullTotalPhys / 1048576),
                    "used_pct": int(status.dwMemoryLoad)}
        return None
    if sys.platform == "darwin":                      # sysctl + vm_stat (bridge/desktop_macos.py)
        from . import desktop_macos
        return desktop_macos.ram()
    try:
        info = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0])              # kB
        total, avail = info["MemTotal"], info["MemAvailable"]
        return {"total_mb": round(total / 1024), "used_pct": round(100 * (total - avail) / total)}
    except Exception:
        return None


def _cpu_sample():
    parts = open("/proc/stat").readline().split()[1:]
    vals = [int(x) for x in parts]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)       # idle + iowait
    return idle, sum(vals)


def cpu_pct(interval=0.25):
    """% CPU global (2 échantillons /proc/stat) — sonde on-demand seulement."""
    if sys.platform == "win32":
        import ctypes
        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]
        def sample():
            idle, kernel, user = FileTime(), FileTime(), FileTime()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel),
                                                         ctypes.byref(user)):
                return None
            value = lambda t: (t.high << 32) | t.low
            return value(idle), value(kernel) + value(user)
        first = sample()
        if first is None:
            return None
        time.sleep(interval)
        second = sample()
        if second is None:
            return None
        idle, total = second[0] - first[0], second[1] - first[1]
        return round(100 * (total - idle) / total, 1) if total > 0 else None
    if sys.platform == "darwin":                      # host_statistics de Mach (bridge/desktop_macos.py)
        from . import desktop_macos
        return desktop_macos.cpu_pct(interval)
    try:
        i0, t0 = _cpu_sample()
        time.sleep(interval)
        i1, t1 = _cpu_sample()
        dt = t1 - t0
        return round(100 * (dt - (i1 - i0)) / dt, 1) if dt > 0 else None
    except Exception:
        return None


def temp_c():
    """Température max des zones thermiques (CPU en pratique sur le rack AM5). Windows et macOS : None
    (aucune sonde sans droits ; la tuile le dit au lieu d'inventer)."""
    best = None
    try:
        base = "/sys/class/thermal"
        for z in os.listdir(base):
            if not z.startswith("thermal_zone"):
                continue
            try:
                t = int(open(os.path.join(base, z, "temp")).read().strip()) / 1000.0
                if 1 < t < 150 and (best is None or t > best):
                    best = t
            except Exception as _e:
                _swallowed(_e)
    except Exception as _e:
        _swallowed(_e)
    return round(best, 1) if best is not None else None


def _at():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── objets du contrat ─────────────────────────────────────────────────────────
def modes_table():
    """LA TABLE DES MODES (demande golem.fm 2026-09-08) : quel mode tague pour quel espace, s'il
    enregistre, et ce que ses prises disent d'elles-mêmes. Lecture seule — un réglage invisible
    est un réglage qu'on croit faux (« which space the rack tags its takes for is decided on
    the rack itself »). ⚠ PAS dans le heartbeat périodique : golem.fm a mesuré +189 % pour une
    donnée qui ne change qu'à la main. Elle part UNE fois au démarrage et à chaque sauvegarde
    d'un mode (push_soon(with_modes=True)) — zéro octet en régime permanent."""
    from . import modes as _modes
    # ENRICHIE le 2026-09-26 (docs/modes.md, addendum golem.fm) : la feuille Settings ▸ Mode entière —
    # les clés d'avant (id, label, band, perfrec, take_kind) restent, le reste s'ajoute (`modes.doc`)
    return [_modes.doc(m) for m in sorted(_modes.list_modes(), key=lambda m: m.get("order") or 99)]


def modes_ctx():
    """Ce qui accompagne la table des modes, hors cadence : les configs GLOBALES que la feuille édite
    (REC ✎ = config/recorder.json, Click ✎ = config/click.json — décision 2026-09-08, pas de config par
    mode), les VOCABULAIRES (pour que le widget n'en code aucun en dur), les espaces et cartes connus, et
    une empreinte `modes_version`."""
    import hashlib
    import json as _j
    from . import modes as _modes, store as _store, inputmap as _im, cards as _cards, roster as _roster
    tbl = modes_table()
    r = _roster.read()
    ctx = {"recorder": _store.load_recorder_cfg(), "click": _store.load_click_cfg(),
           "vocab": {**_modes.vocab(), "out_roles": [o["id"] for o in _im.OUT_ROLES], "instruments": [i["id"] for i in _im.INSTRUMENTS]},
           "spaces": [{"id": b.get("id"), "name": b.get("name")} for b in (r.get("bands") or []) if b.get("id")],
           "cards": [{"id": c.get("id"), "name": c.get("name")} for c in _cards.registry() if c.get("id")]}
    # les listes qu'un mode peut mettre au pied (docs/patches.md §9 bis-9) : golem.fm valide `foot_list`
    # contre elles ; dans l'empreinte, pour qu'une bank créée ou renommée se voie à la feuille des modes
    with __import__("contextlib").suppress(Exception):
        from . import setlists as _sl
        ctx["foot_lists"] = [{"id": x["id"], "name": x.get("name") or x["id"], "kind": x.get("kind") or "songs"}
                             for x in _sl.list_all()]
    ctx["modes_version"] = hashlib.sha1(_j.dumps([tbl, ctx["recorder"], ctx["click"], ctx.get("foot_lists")],
                                                 sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return ctx


# ── ce que le rack SAIT et ce qu'il A (réponse golem.fm du 2026-09-09, docs/private/exchanges/message-maestrium-installer-2.md) ──
def drum_kits():
    """Les KITS DE BATTERIE du rack (docs/drums-kit.md lot 2, demande golem.fm 2026-09-17) : ce que le
    paramètre `kit` d'un bloc drumkit peut valoir — [{id, name, engine, playable}] ; `playable` = le
    moteur est porté sur une lane (avldrums au lot 2, drumgizmo depuis le 2026-09-23 ; sfz suit)."""
    from . import kits
    out = []
    for k in kits.list_kits():
        if k.get("role") == "drum":
            out.append({"id": k["id"], "name": k.get("name") or k["id"], "engine": k.get("engine"),
                        "playable": k.get("engine") in ("avldrums", "drumgizmo")})   # drumgizmo porté le 2026-09-23
    return out


def catalog_version():
    """L'entier `catalog_version` de library/catalog/effects.json — dans le heartbeat, jamais le catalogue."""
    try:
        from .store import _read_json
        return int((_read_json(os.path.join(C.ROOT, "library", "catalog", "effects.json"), {}) or {}).get("catalog_version") or 0)
    except Exception:
        return 0


def classifier_version():
    """`CLASSIFIER_VERSION` de tools/classify.py — golem.fm classe le marché TONE3000 avec une copie de
    ce module (décision 2026-09-14) et compare : un écart = « golem.fm en retard », pas une panne."""
    try:
        from .routes_t3k import _clf
        return int(getattr(_clf, "CLASSIFIER_VERSION", 0) or 0)
    except Exception:
        return 0


def catalog():
    """Le catalogue ENTIER, à la demande (job `push-catalog`) : la liste exhaustive du matériel que ce rack
    connaît par son nom (amplis, pédales, baffles, marques) et les types de blocs avec leurs potards,
    leurs plages et leur quarantaine — ce qui contraint l'assistant IA de golem.fm (patches.md §14)."""
    from .store import _read_json
    fx = _read_json(os.path.join(C.ROOT, "library", "catalog", "effects.json"), {}) or {}
    brands = _read_json(os.path.join(C.ROOT, "library", "catalog", "brands.json"), {}) or {}
    slim = lambda e: {k: v for k, v in e.items() if not str(k).startswith("_")}
    return {"catalog_version": fx.get("catalog_version"), "classifier_version": classifier_version(),
            "amps": [slim(a) for a in fx.get("amps") or []],
            "pedals": [slim(p) for p in fx.get("pedals") or []],
            "cabs": [slim(c) for c in fx.get("cabs") or []],
            "brands": brands.get("brands") or [],
            "categories": fx.get("categories") or [],
            # catégories par RÔLE de lane (v11) : le tiroir de golem.fm et le vocabulaire de son IA filtrent
            # comme le Designer — une table, deux maisons ; `_comment` exclu
            "role_categories": {k: v for k, v in (fx.get("role_categories") or {}).items() if not str(k).startswith("_")},
            # le TAMIS FIN par rôle (v15) : la liste exacte des blocs d'un rôle — même table, deux maisons
            "role_blocks": {k: v for k, v in (fx.get("role_blocks") or {}).items() if not str(k).startswith("_")},
            # ⚠ `quarantine` porte la RAISON en clair (« GxDetune corrompt le tas de Reaper… ») — la
            # coercer en booléen jetait la seule phrase qui dit à l'utilisateur pourquoi le bloc a disparu.
            # golem.fm accepte les deux (leur réponse 2, §2) : on passe la valeur telle quelle.
            # TOUT ce qu'un tiroir a besoin de savoir d'un bloc (demande golem.fm 2026-09-17, option 2 : la ligne
            # du rack fait AUTORITÉ sur le vocabulaire, elle ne peut donc pas être une projection amputée) :
            # identité, catégorie, potards, quarantaine + icône/glyphe/couleur/nom court, unicité, moteur,
            # invariance de scène, paramètre de contenu. `note` (documentation) reste ici : le rack l'écrit,
            # golem.fm le lit. Absents = le bloc ne les a pas.
            "blocks": [{"type": b.get("type") or b.get("id"), "name": b.get("name"), "category": b.get("category"),
                        "params": b.get("params") or [], "quarantine": b.get("quarantine") or False,
                        **({k: b[k] for k in ("roles", "foot_mode", "input_claim", "icon", "glyph", "short", "color",
                                              "unique", "engine", "scene_invariant", "content_param", "foot_scene_claim",
                                              "note") if k in b})}
                       for b in fx.get("effects") or []]}


CAPTURES_MAX = 500


def keys_instruments():
    """Les instruments CLAVIER livrés avec le rack (Library ▸ Keys ▸ Instruments, lecture seule) — dans
    le HEARTBEAT (`PUT /api/ext/rig/status`, via push(), à côté de `captures`), PAS dans l'état
    `PUT /api/ext/golem/state` et PAS en packs : le piano pèse 714 Mo et vient d'un téléchargement
    public, les banques DX7 et l'orgue n'ont rien à mettre au coffre. golem.fm les garde champ par champ
    depuis le dernier heartbeat (`GET /api/golem/keys-instruments`). ⚠ Ma réponse du 2026-09-15 disait
    « dans l'état » : faux, golem.fm a lu au mauvais endroit et vu Keys vide. [{type, name, engine,
    factory, items[], count, sounds?}]."""
    import glob
    out = []
    try:
        # les variantes du PIANO seulement (2026-11-14) : library/sfz/ range aussi la guitare pompe des Standards et
        # Shinyguitar, qui partaient ici comme des pianos — et `piano:<item>` est l'adresse d'un son chez golem.fm
        from .sound_preview import piano_variants
        sfz = list(piano_variants())
        out.append({"type": "piano", "name": "Piano", "engine": "sfizz", "factory": True, "count": len(sfz),
                    "items": sfz})
        from .store import _read_json
        banks = []
        for f in sorted(glob.glob(os.path.join(C.ROOT, "library", "dx7", "*.syx"))):
            banks.append(os.path.splitext(os.path.basename(f))[0])
        out.append({"type": "ep", "name": "E-Piano", "engine": "dexed", "factory": True, "count": len(banks),
                    "sounds": 32 * len(banks), "items": banks})
        out.append({"type": "organ", "name": "Organ", "engine": "b3", "factory": True, "count": 1, "items": ["setBfree tonewheel"]})
    except Exception as e:
        log.warning(f"keys_instruments : {e}")
    return out


def captures(limit=CAPTURES_MAX):
    """Les captures INSTALLÉES sur cette machine — une entrée par tone du catalogue local dont au moins un
    fichier est là : `{ref, type, family}` (le minimum demandé) + name, gear, models. Absent ≠ vide :
    une liste vide veut dire « ce rack n'a aucun son » (starter set), le champ absent « le rack n'a rien dit »."""
    from .store import _read_json
    from . import ir_quality
    irq = ir_quality.load()
    idx = _read_json(os.path.join(C.ROOT, "library", "catalog", "tones-index.json"), {}) or {}
    out = []
    for t in idx.get("tones") or []:
        models = [m for m in (t.get("models") or []) if m.get("file") and os.path.isfile(os.path.join(C.ROOT, m["file"]))]
        if not models:
            continue
        gear = str(t.get("gear") or "amp")
        tags = [str(x).lower() for x in (t.get("tags") or [])]
        fam = "bass" if (str(t.get("style") or "").lower() == "bass" or "bass" in tags or "bass" in gear) else "guitar"
        row = {"ref": str(t.get("id")), "type": "ir" if gear == "cab" else "nam", "family": fam,
               "name": t.get("title"), "gear": gear, "models": len(models)}
        if gear == "cab" and ir_quality.echo_of(t.get("id"), irq):
            row["echo"] = True                               # pack d'IR à impulsion tardive (docs/blocks-doctrine.md)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _profile():
    """desktop | server MAINTENANT : il suit la fenêtre (bridge/machine.py), GOLEM_LAUNCH avant la première."""
    try:
        from . import machine
        return machine.profile()
    except Exception:
        return os.environ.get("GOLEM_LAUNCH") or "desktop"


def rack_identity():
    """Ce que le rack dit de lui à l'appairage (`rack{}` de pair/start) : version, profil, date et mode
    d'installation, version du catalogue. Liste blanche : rien qui identifie quelqu'un."""
    from .store import _read_json
    # `profile` = ce que ce golem est MAINTENANT, desktop (une fenêtre est ouverte) ou server (docs/installer.md §4,
    # 2026-10-16 : il suit la fenêtre) — plus un profil d'installation. La trace d'installation vient de config/engine.json (écrit par
    # l'installateur et install.sh), à défaut d'un ancien config/profile.json.
    inst = _read_json(os.path.join(C.CONFIG_DIR, "engine.json"), {}) or {}
    if not inst.get("at"):
        inst = _read_json(os.path.join(C.CONFIG_DIR, "profile.json"), {}) or {}
    d = {"version": golem_version(), "profile": _profile(),
         "installed_at": inst.get("at"), "installer": "gui" if inst.get("set_by") == "installer" else "manual",
         "catalog_version": catalog_version(), "classifier_version": classifier_version()}
    # LE NUMÉRO À VIE (docs/connect.md §4.5, 2026-09-24) : golem.fm l'attribue à la MACHINE (`rack_id`,
    # dérivé salé de /etc/machine-id — jamais le jeton, qui change à chaque appairage) et affiche la fiche.
    try:
        from . import connect, serial
        d["rack_id"] = connect.rack_id()
        d.update(serial.machine())
    except Exception as e:
        log.warning(f"rack_id/fiche machine absents de l'identité : {e}")
    return d


def inputs_doc():
    """QUI JOUE QUELLE ENTRÉE (docs/devices-people.md §8.1, décision 2026-09-16). C'est une propriété
    de l'ENTRÉE, pas de la personne : elle suit la carte son et le mode, et la même personne change d'entrée
    d'un morceau à l'autre. Seule la carte ACTIVE part, avec le battement.

    ⚠ UN INVITÉ SORT SANS SON PRÉNOM (`{"person": null, "guest": true}`) : son nom est frappé sur le rack,
    il n'a pas de compte sur golem.fm, et docs/identity.md §6 bis n'autorise à sortir que ce qu'un geste
    de l'utilisateur désigne. Un membre sort avec son handle global, que golem.fm re-vérifie chez lui."""
    from . import inputmap as _im
    m = _im.current() or {}
    entries = []
    for e in (m.get("inputs") or []):
        if not e.get("role") or e["role"] in ("none", "other"):
            continue
        entries.append({"slot": f"IN {e.get('ch')}", "kind": "audio", "role": str(e.get("role"))[:32],
                        "name": str(e.get("name") or e.get("label") or "")[:64] or None,
                        **_who(e)})
    for u in (m.get("usb") or []):
        if not u.get("bound"):
            continue
        entries.append({"slot": f"USB {u.get('port')}", "kind": "midi" if u.get("kind") == "midi" else "audio",
                        "role": str(u.get("role") or "")[:32], "name": str(u.get("name") or u.get("label") or "")[:64] or None,
                        "device": str(u.get("device") or "")[:64] or None, **_who(u)})
    try:
        from .state import state as _st
        mode = (_st.mode or {}).get("id")
    except Exception:
        mode = None
    return {"card": str(m.get("card") or "")[:120] or None, "mode": mode, "entries": entries[:64]}


def _slot(e, prefix):
    ch = str(e.get("ch") or "")
    if ch.startswith("usb"):
        return "USB " + ch[3:]
    return f"{prefix} {ch}"


def cards_doc():
    """TOUTES LES CARTES QUI COMPTENT, branchées ou non (docs/returns.md §2, R1 2026-09-26) : celles qu'un
    mode déclare (`config/modes*/…card`), la carte active, celles branchées — avec le patch complet de
    chacune : entrées (rôle, numéro, nom dérivé, personne, paire), SORTIES (rôle, personne, type) et les
    ports MIDI. C'est ce que le widget Soundcard de golem.fm et le rider lisent RACK ÉTEINT ; d'où le
    battement, pas un job. Même liste blanche que `inputs_doc` : un invité sort sans son prénom."""
    from . import inputmap as _im, modes as _modes, cards as _cards
    declared = {}
    for m in _modes.list_modes():
        c = _modes.card_of(m)
        if c:
            declared.setdefault(c, []).append(str(m.get("id")))
    try:
        active = _im._card_device()
    except Exception:
        active = None
    # CE QUI EST BRANCHÉ, dans la clé de CHAQUE système (2026-10-05) : `hw:` sous Linux, mais le pilote
    # ouvert par REAPER est `asio:<pilote>` sous Windows et `coreaudio:<entrée>` sous macOS — préfixé `hw:`,
    # il ne correspondait jamais : toutes les cartes partaient « non branchées » d'une machine qui jouait.
    # Une carte du registre (`hw:<id>`) est aussi branchée si son périphérique USB est présent.
    prefix = "asio:" if sys.platform == "win32" else "coreaudio:" if sys.platform == "darwin" else "hw:"
    connected = {f"{prefix}{c['id']}" for c in _cards.connected()}
    usb_here = _cards.present_usb_ids()
    connected |= {f"hw:{c['id']}" for c in _cards.registry()
                  if c.get("id") and str(c.get("usb") or "").lower() in usb_here}
    # macOS réglé sur « périphériques système par défaut » : la carte active s'appelle `coreaudio:<default system
    # devices>`, la carte OUVERTE `coreaudio:Volt 276` — elles ne correspondaient jamais, et un Mac qui jouait
    # partait « not plugged in » (passe macOS du 2026-10-10). Le défaut ouvert par REAPER EST la carte active.
    if sys.platform == "darwin" and active and active.startswith("coreaudio:") and _cards.connected():
        from . import desktop_audio as _da
        if active == "coreaudio:" + _da.DEFAULT_DEVICE:
            connected.add(active)
    names = {f"hw:{c.get('id')}": c.get("name") for c in _cards.registry() if c.get("id")}
    # une carte branchée que ni un mode ni l'écran n'ont jamais patchée n'est PAS semée par un battement
    # (une lecture qui écrit : trouvé au premier essai, 2026-09-26 — l'audio USB du Nitro s'était vu
    # créer un patch) ; une carte DÉCLARÉE l'est, comme par GET /api/inputmap?card= (c'est son contrat)
    extras = {d for d in connected if d not in declared and d != active and os.path.exists(_im._path(d))}
    devs = sorted({*declared, *extras, *([active] if active else [])})
    # OPÉRATIONNELLE ? (2026-10-05 : « on veut savoir si c'est opérationnel ») — pour la carte du
    # moteur seulement : branchée, ouverte par le moteur, le thread audio AVANCE (state.audio, le compteur
    # de golem_clock — CLAUDE.md : REAPER ne sait pas dire que sa carte a disparu) et ses scripts répondent.
    # Une carte que le moteur n'utilise pas : null (on ne sait pas, on ne devine pas).
    from .state import state as _st
    audio_ok = (_st.audio or {}).get("ok")
    stalled = bool((_st.cards or {}).get("scripts_stalled"))
    reaper_up = bool(getattr(_st, "reaper_running", True))
    # l'APPAREIL derrière les prises DIN (le pédalier entre par la Volt 276…) : le port de l'OS choisi
    din = {"in": None, "out": None}
    if sys.platform in ("win32", "darwin"):
        try:
            from . import desktop_midi
            din = {k: desktop_midi.din_port(k) for k in ("in", "out")}
        except Exception as e:
            log.warning(f"cards_doc : ports MIDI DIN illisibles : {e}")

    def operational(dev, plugged):
        if dev != active:
            return None, None
        if not plugged:
            return False, "not plugged in"
        if not reaper_up:
            return False, "audio engine not running"
        if stalled:
            return False, "REAPER stopped listening"
        if audio_ok is False:
            return False, "no audio (the engine stopped processing)"
        return (True, None) if audio_ok else (None, None)
    out = []
    for dev in devs[:8]:
        try:
            m = _im.current(dev)
        except Exception as e:
            log.warning(f"cards_doc : patch de {dev} illisible : {e}")
            continue
        op, why = operational(dev, dev in connected)
        # l'IDENTITÉ et la DATE de la configuration (docs/card-setups-exchange.md §3) : golem.fm garde une
        # configuration par rack et par clé USB ; `os` et `rack` ne sont PAS ici — il les lit sur le battement et le jeton
        try:
            from . import card_setups as _cs
            usb, serial = _cs.identity(dev)
            upd = _cs.updated_at(dev)
        except Exception as e:
            _swallowed(e)
            usb, serial, upd = None, None, None
        out.append({"card": dev[:120], "name": (names.get(dev) or dev)[:120],
                    "connected": dev in connected, "active": dev == active,
                    "operational": op, "operational_why": why,
                    "usb": usb, "serial": serial, "updated_at": upd,
                    "usb_ports": len(m.get("usb") or []),
                    "midi_in_device": (str(din["in"])[:120] if din["in"] else None) if dev == active else None,
                    "midi_out_device": (str(din["out"])[:120] if din["out"] else None) if dev == active else None,
                    "modes": declared.get(dev, []), **setup_of(m)})
    # UNE IDENTITÉ, UNE CONFIGURATION PAR RACK (docs/card-setups-exchange.md §3-4) : la même Volt apparaît ici sous
    # deux noms (la carte active `asio:…` ET la carte `hw:V276` que les modes déclarent) ; golem.fm range la dernière
    # reçue par (rack, usb) — celle du mode, jamais branchée, écrasait celle qui joue. Seule la carte ACTIVE (sinon
    # branchée, sinon la première) porte la clé ; les autres homonymes la perdent (`usb: null` = ignorée là-bas).
    by_usb = {}
    for c in out:
        if c.get("usb"):
            by_usb.setdefault(c["usb"], []).append(c)
    for usb, group in by_usb.items():
        if len(group) < 2:
            continue
        keep = next((c for c in group if c.get("active")), None) or next((c for c in group if c.get("connected")), None) or group[0]
        for c in group:
            if c is not keep:
                c["usb"] = None
    return out


def setup_of(m):
    """La CONFIGURATION d'une carte sous la forme du contrat — {inputs, outputs, midi_in, midi_out} — depuis son
    input map `m` (inputmap.current(dev)). Une seule fabrique : le battement l'envoie, card_setups la compare
    et la propose (docs/card-setups-exchange.md §3)."""
    ins = []
    for e in (m.get("inputs") or []):
        ch = str(e.get("ch") or "")
        ins.append({"slot": _slot(e, "IN"), "kind": "audio", "role": str(e.get("role") or "none")[:32],
                    "nth": e.get("nth"), "name": str(e.get("name") or "")[:64] or None,
                    "pair": ch if "-" in ch else None, **_who(e)})
    for u in (m.get("usb") or []):
        if not u.get("bound"):
            continue
        ins.append({"slot": _slot(u, "USB"), "kind": "midi" if u.get("kind") == "midi" else "audio",
                    "role": str(u.get("role") or "")[:32], "nth": u.get("nth"),
                    "name": str(u.get("name") or "")[:64] or None,
                    "device": str(u.get("device") or "")[:64] or None, "pair": None, **_who(u)})
    outs = []
    for o in (m.get("outputs") or []):
        ch = str(o.get("ch") or "")
        outs.append({"slot": f"OUT {ch}", "role": str(o.get("role") or "other")[:32],
                    "type": o.get("type") if o.get("type") in ("iem", "wedge") else None,
                    "pair": ch if "-" in ch else None, **_who(o)})
    return {"inputs": ins[:64], "outputs": outs[:32],
            "midi_in": ((m.get("midi_in") or {}).get("role")), "midi_out": ((m.get("midi_out") or {}).get("role"))}


def patch_version(cards=None):
    """Empreinte des patches (pour que golem.fm ne re-diffe pas un battement identique)."""
    import hashlib
    import json as _j
    blob = _j.dumps(cards if cards is not None else cards_doc(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def _who(e):
    p = e.get("person")
    if not p:
        return {"person": None}
    return {"person": None, "guest": True} if str(p).startswith("guest:") else {"person": str(p)[:64]}


def light(with_modes=False):
    """Payload du push périodique : versions + disque (sondes gratuites) + l'INDEX DES PRISES
    non montées (`pending_takes` / `pending_total` / `pending_bytes`, docs/message-golemfm-
    ranger-prises.md §1) — c'est ce qui permet à l'écran « À ranger » d'exister côté web.
    Un index qui échoue ne fait pas tomber le heartbeat : le reste part sans lui.
    `with_modes` : joint la table des modes (boot, sauvegarde d'un mode) — jamais en cadence."""
    st = {"firmware": golem_version(), "reaper": reaper_version(), "disk": disk(), "at": _at()}
    # `rack_id` + fiche machine (docs/connect.md §4.5) : c'est par le battement qu'un rack appairé AVANT le
    # contrat reçoit son numéro à vie, et la fiche rafraîchit ce que golem.fm affiche du rack.
    try:
        from . import connect, serial
        st["rack_id"] = connect.rack_id()
        st["machine"] = serial.machine()
    except Exception as e:
        log.warning(f"rack_id/fiche machine absents du push : {e}")
    if with_modes:
        try:
            st["modes"] = modes_table()
            st["modes_ctx"] = modes_ctx()        # configs globales, vocabulaires, modes_version (2026-09-26)
        except Exception as e:                   # jamais fatal : le push part sans la table
            log.warning(f"table des modes absente du push : {e}")
    try:
        from . import takes
        st.update(takes.pending())
    except Exception as e:
        log.warning(f"index des prises indisponible : {e}")
    # ce que le rack A (captures installées) et la VERSION de ce qu'il sait (le catalogue entier part
    # à la demande, ~100 Ko — jamais toutes les cinq minutes). Jamais fatal : le push part sans.
    try:
        from .state import state as _st
        m = _st.mode or {}
        st["mode"] = m.get("id")
        st["locked"] = bool((m.get("ui") or {}).get("locked"))
        st["recording"] = bool((_st.perf or {}).get("recording"))
        # CE QUI JOUE (demande golem.fm, 2026-09-30) : le preset courant — `patch:<id>` pour un patch joué
        # (docs/patches.md), `sandbox-try` pour un brouillon sans nom — son nom et la scène. Absent =
        # golem.fm n'affiche rien. Poussé hors cadence à chaque changement de PRESET (recall.do_recall).
        st["preset_id"] = _st.preset_id or None
        # sans le « ⛓ » que le Designer préfixe à un patch ouvert : l'id `patch:` le dit déjà
        st["preset_name"] = (str(_st.preset_name).replace("⛓", "", 1).strip() or None) if _st.preset_name else None
        st["scene"] = _st.scene_id or None
        # la liste au pied que le mode a voulu poser, et pourquoi elle n'y est pas (patch-as-preset §7) — absent si
        # le mode n'en déclare pas
        from . import modes as _modes
        _f = _modes.last_foot()
        if _f:
            st["foot"] = _f
    except Exception as e:
        log.warning(f"mode/recording absents du push : {e}")
    try:
        st["inputs"] = inputs_doc()
    except Exception as e:
        log.warning(f"carte d'entrées absente du push : {e}")
    # TOUTES les cartes qui comptent, avec sorties et retours (docs/returns.md R1) — ~1 Ko, rack éteint compris
    try:
        st["cards"] = cards_doc()
        st["patch_version"] = patch_version(st["cards"])
    except Exception as e:
        log.warning(f"cartes absentes du push : {e}")
    # LA SETLIST SOUS LES PIEDS, LUE (question golem.fm 2026-09-17, docs/private/exchanges/message-maestrium-setlists-2.md
    # §4) : `fcb: true` dans un push n'est qu'un souhait (setlists.md §9.6) — seul ce champ dit ce que
    # le pied joue vraiment. `pending` = les pushs reçus en mode verrouillé, appliqués au prochain
    # changement de mode (ids de setlist) : le web peut afficher « waiting for the mode to change ».
    try:
        from . import setlists as _sl
        pend = sorted(os.path.splitext(os.path.basename(f))[0]
                      for f in glob.glob(os.path.join(_sl.PENDING_DIR, "*.json")))
        st["setlist"] = {"active": _sl.active_id(), "pending": pend}
    except Exception as e:
        log.warning(f"setlist active absente du push : {e}")
    try:
        st["catalog_version"] = catalog_version()
        st["classifier_version"] = classifier_version()
        st["captures"] = captures()
        st["keys_instruments"] = keys_instruments()
        # les démos des sons de clavier rendues ici (docs/preset-preview.md §9) : un clip envoyé -> la fiche de son son
        from .sound_preview import rendered as _keys_previews
        st["keys_previews"] = _keys_previews()
        st["drum_kits"] = drum_kits()             # docs/drums-kit.md : ce que `params.kit` d'un drumkit peut valoir
    except Exception as e:
        log.warning(f"captures/catalogue absents du push : {e}")
    # le moteur ouvert + les jauges, en cadence (demande golem.fm, 2026-10-05) — jamais fatal
    try:
        st["engine"] = engine_doc()
        st["health"] = health_doc()
        st["controllers"] = controllers_doc()
    except Exception as e:
        log.warning(f"moteur/santé absents du push : {e}")
    # ce que CETTE machine sait jouer (docs/block-status.md §7) : OS, moteur, types de blocs dont le
    # plugin manque — golem.fm en tire « 3 elements to download on the rack » et filtre son IA
    try:
        from . import blockstatus
        st["caps"] = blockstatus.caps()
    except Exception as e:
        log.warning(f"caps absentes du push : {e}")
    # le job song-separate tenu, et pourquoi il attend (docs/separation.md §10, demande golem.fm 2026-10-24) —
    # absent quand aucun job n'est tenu
    try:
        from . import separation
        sj = separation.heartbeat_job()
        if sj:
            st["separation_job"] = sj
    except Exception as e:
        log.warning(f"separation_job absent du push : {e}")
    return st


def controllers_doc():
    """LES CONTRÔLEURS DU GOLEM (2026-10-05 : « ce qui est ACTIF, et les contrôleurs DISPOS déjà
    calibrés ») — widget Controllers de golem.fm. Chaque champ est LU, jamais déduit d'un nom :
      - appareils USB MIDI que le rack connaît (devices) : `calibrated` = un profil de contrôleur calibré,
        ou, pour une batterie, un descripteur de kit MESURÉ (confidence verified) ;
      - le pédalier (pedalboard.active : puce identifiée par sondage), la ou les pédales MIDI pilotées
        (mappings/*.json : leur provenance dit si la table est vérifiée).
    `connected` : vu par l'OS maintenant (USB) ou sondé (pédalier) ; null quand rien ne peut le dire (une
    prise DIN de sortie ne sait pas ce qui est au bout). `active` : lié/écouté par le golem. Les
    descripteurs d'usine non mesurés (alesis-strike…) ne sont PAS des contrôleurs de ce rack : absents."""
    out = []
    kinds = {frozenset(["keys", "pads"]): "keys-pads", frozenset(["keys"]): "keys", frozenset(["pads"]): "pads",
             frozenset(["drums"]): "drums"}
    try:
        from . import devices, controllers, drumkits
        profiles = {c.get("key"): c for c in controllers.listing()}
        for d in devices.listing():
            roles = [r for r in (d.get("roles") or []) if r]
            kind = kinds.get(frozenset(roles), "controller")
            calibrated = bool((profiles.get(d.get("key")) or {}).get("calibrated"))
            if kind == "drums":
                try:
                    kid, _auto, fallback = drumkits.identify(d.get("name"))
                    kit = drumkits.get(kid) if kid and not fallback else None
                    calibrated = bool(kit and (kit.get("provenance") or {}).get("confidence") == "verified")
                except Exception as e:
                    log.warning(f"controllers : kit de {d.get('name')} illisible : {e}")
            out.append({"id": str(d.get("key"))[:64], "name": str(d.get("name") or d.get("key"))[:80], "kind": kind,
                        "usb": d.get("usb"), "calibrated": calibrated, "connected": bool(d.get("connected")),
                        "active": bool(d.get("connected") and d.get("port") and roles),
                        "where": f"USB {d['port']}" if d.get("port") else None, "role": ",".join(roles) or None})
    except Exception as e:
        log.warning(f"controllers : appareils USB illisibles : {e}")
    try:
        from . import pedalboard
        a = pedalboard.active()
        dev = a.get("device") or {}
        if a.get("source") != "fallback":            # aucun pédalier déclaré ni mesuré : rien à lister
            out.append({"id": str(a.get("id"))[:64], "name": str(a.get("name"))[:80], "kind": "pedalboard",
                        "usb": None, "calibrated": (dev.get("provenance") or {}).get("confidence") == "verified",
                        "connected": True if a.get("source") == "measured" and not a.get("stale") else None,
                        "active": a.get("source") == "measured" and not a.get("stale"), "where": "MIDI IN",
                        "role": "pedalboard"})
    except Exception as e:
        log.warning(f"controllers : pédalier illisible : {e}")
    try:
        from . import inputmap as _im
        out_role = ((_im.current() or {}).get("midi_out") or {}).get("role")
        for path in sorted(glob.glob(os.path.join(C.ROOT, "mappings", "*.json"))):
            try:
                import json as _j
                m = _j.load(open(path, encoding="utf-8"))
            except Exception:
                continue
            prov = m.get("provenance") or {}
            out.append({"id": str(m.get("id"))[:64], "name": str(m.get("name") or m.get("id"))[:80], "kind": "pedal",
                        "usb": None, "calibrated": prov.get("confidence") == "verified", "connected": None,
                        "active": out_role == m.get("id"), "where": "MIDI OUT" if out_role == m.get("id") else None,
                        "role": m.get("kind") or "pedal"})
    except Exception as e:
        log.warning(f"controllers : pédales MIDI illisibles : {e}")
    return out[:24]


def engine_doc():
    """CE QUE LE MOTEUR A RÉELLEMENT OUVERT (demande golem.fm, 2026-10-05), distinct de `cards[].active`
    (la carte DÉCLARÉE). Windows/macOS : ce que REAPER rapporte (golem_desktop_audio.lua) — pilote,
    fréquence, buffer, canaux et leurs noms, latence entrée+sortie. Linux : buffer et latence du moteur.
    None quand le moteur ne dit rien (arrêté, ou télémétrie muette : voir cards.scripts_stalled)."""
    from .state import state as _st
    if sys.platform in ("win32", "darwin"):
        from . import desktop_audio
        a = desktop_audio._public_actual()
        if not a:
            return None
        num = lambda v: int(float(v)) if str(v).replace(".", "", 1).isdigit() else None
        lat, src = desktop_audio.latency_ms(a)
        return {"mode": a.get("MODE"), "device": str(a.get("IDENT_IN") or "").removeprefix("ASIO ")[:120] or None,
                "samplerate": num(a.get("SRATE")), "bsize": num(a.get("BSIZE")),
                "inputs": a.get("INPUT_COUNT"), "outputs": a.get("OUTPUT_COUNT"),
                "input_names": [str(x)[:40] for x in (a.get("INPUT_NAMES") or [])][:16],
                "output_names": [str(x)[:40] for x in (a.get("OUTPUT_NAMES") or [])][:16],
                "latency_ms": lat, "latency_source": src}
    from .routes_system import _read_bsize
    return {"mode": "ALSA", "device": C.alsa_card() or None, "samplerate": None,
            "bsize": _read_bsize(), "latency_ms": _st.latency_ms, "latency_source": "engine"}


def health_doc():
    """Les jauges de la page d'un golem (demande golem.fm, 2026-10-05) — EN CADENCE : elles ne partaient
    qu'au job `rig-status`, et golem.fm se repliait sur le dernier rapport, daté. Un échantillon CPU de
    0,25 s toutes les 5 min. temp_c : None sous Windows/macOS (aucune sonde sans droits — dit, pas inventé)."""
    from .state import state as _st
    r = ram() or {}
    return {"cpu_pct": cpu_pct(), "ram_used_pct": r.get("used_pct"), "ram_total_mb": r.get("total_mb"),
            "temp_c": temp_c(), "xruns_total": getattr(_st, "xruns", None)}


def full():
    """Payload du job on-demand `rig-status` : tout, y compris les sondes actives."""
    st = light()
    st.update({"cpu_pct": cpu_pct(), "temp_c": temp_c(), "ram": ram()})
    return st


# ── push périodique ───────────────────────────────────────────────────────────
def push(payload=None, with_modes=False):
    """PUT /api/ext/rig/status. Rend (status_http, data). Silencieux si non appairé/endpoint absent."""
    import json as _json
    import urllib.request
    from .golemfm import _cfg
    base, token = _cfg()
    if not base or not token:
        return 0, "not paired"
    req = urllib.request.Request(base + "/api/ext/rig/status", method="PUT")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.data = _json.dumps(payload or light(with_modes=with_modes)).encode()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status, blob = r.status, r.read()
    except Exception as e:
        return getattr(e, "code", 0), str(e)
    # la réponse porte le numéro à vie (`{"ok": true, "serial": {...}|null}`) : gardé une fois, jamais réécrit
    try:
        ans = _json.loads(blob or b"null")
        if isinstance(ans, dict) and "serial" in ans:
            from . import serial
            serial.record(ans.get("serial"))
        # la TAXONOMIE DES GENRES (docs/genres.md) : golem.fm en annonce la version, on la relit quand elle change
        if isinstance(ans, dict) and ans.get("genres_version"):
            from . import genres
            if genres.sync(ans.get("genres_version")):
                log.info(f"genres : liste de golem.fm reçue (version {genres.version()})")
    except Exception as e:
        log.warning(f"serial du battement illisible : {e}")
    return status, None


_pusher = None
_soon = None
_soon_lock = threading.Lock()


_soon_modes = False


def push_soon(delay=2.0, with_modes=False):
    """Push léger DÉBOUNCÉ, hors cadence : après un retag (web ou écran), à la fin d'une prise,
    et — avec la table des modes — à la sauvegarde d'un mode, pour que l'écran « À ranger » et
    le panneau « On the rack » n'attendent pas le prochain tick de 5 min. Silencieux si non
    appairé ; une rafale ne coûte qu'un PUT, et si l'un des appels de la rafale voulait la
    table, elle part avec."""
    global _soon, _soon_modes
    with _soon_lock:
        if _soon is not None:
            _soon.cancel()
        _soon_modes = _soon_modes or bool(with_modes)
        def fire():
            global _soon_modes
            wm, _soon_modes = _soon_modes, False
            push(with_modes=wm)
        _soon = threading.Timer(delay, fire)
        _soon.daemon = True
        _soon.start()


def start_pusher():
    """Thread daemon : push léger périodique tant qu'on est appairé. Idempotent."""
    global _pusher
    if _pusher is not None:
        return

    def loop():
        time.sleep(_FIRST_PUSH)
        warned = False
        first = True                                     # le premier push du boot porte la table des modes
        while True:
            try:
                st, err = push(with_modes=first)
                first = False
                try:                                     # lot 8 : ce qui attend part avec le battement
                    from . import diag
                    diag.flush_pending()
                except Exception as _e:
                    _swallowed(_e, "diag flush")
                # LE ROSTER SUIT LE MÊME BATTEMENT (docs/devices-people.md §8, 2026-09-16) : il ne se
                # tirait qu'au démarrage et à la demande, donc un musicien qui rejoignait le groupe
                # pendant la répète n'apparaissait qu'au redémarrage du rack. `sync` ne lève jamais et
                # ne rebascule jamais l'espace courant — hors ligne, le cache fait foi.
                try:
                    from . import roster
                    roster.sync()
                except Exception as _e:
                    _swallowed(_e, "roster sync")
                if st == 404 and not warned:                 # endpoint pas encore livré côté web
                    log.warning("PUT 404 — golem.fm n'expose pas encore /api/ext/rig/status")
                    warned = True
                elif st == 200:
                    warned = False
            except Exception as e:
                log.warning(f"push: {e}")
            time.sleep(_PUSH_EVERY)

    _pusher = threading.Thread(target=loop, daemon=True)
    _pusher.start()
