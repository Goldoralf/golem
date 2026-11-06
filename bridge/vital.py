# SPDX-License-Identifier: GPL-3.0-or-later
"""Presets Vital(ium) — bibliothèque .vital + greffe d'état dans le vst_chunk Reaper (lane Keys).

Un .vital est du JSON pur (wavetables incluses, ~200 KB). SPIKE VALIDÉ (2026-07-08) : en VST3, la
voie de chargement headless est le `vst_chunk` À CHAUD (SetNamedConfigParm sur l'instance vivante).
Le spike concluait aussi « l'état LV2 du chunk n'est jamais rechargé » : FAUX, corrigé le 2026-10-03 —
il l'est à l'instanciation, mais les PORTS (que l'hôte possède) l'écrasent ; le spike les retirait, d'où
un état « ignoré ». Avec les ports calculés depuis le .vital, le LV2 passe entier (lv2_state, plus bas,
et chunk_set_vitalium dans golem_rig). Le vst_chunk est une
structure JUCE (VstW/CcnK/FBCh) : on GREFFE le JSON du preset dans un TEMPLATE (le vst_chunk
courant, dumpé par golem_rig après la création de la piste Keys) et on corrige les 3 champs de
taille impactés. Offsets relevés au spike (Vitalium distrho-ports ; le Vital officiel est JUCE
aussi — les offsets sont validés par sanity-check avant la greffe)."""
import os, re, io, json, base64, struct, zipfile, shutil, sys

from . import config as C
from .golog import swallowed as _swallowed

VITAL_DIR = os.path.join(C.ROOT, "library", "synth", "vital")
USER_PACK = "user"          # pack par défaut d'un .vital isolé uploadé (les .zip/.vitalbank -> pack nommé)
# Template vst_chunk du Vital OFFICIEL (1.5.x) — défaut de la lane Keys (charge les presets du store
# vital.audio). Mêmes offsets JUCE que Vitalium -> vitalium-vst3.chunk.b64 reste un secours valide.
TEMPLATE_CHUNK = os.path.join(os.path.dirname(__file__), "templates", "vital-vst3.chunk.b64")

# (offset, format struct) des champs de taille à corriger quand la longueur du JSON change :
#   0   : uint32 LE = len(total) - 16      (wrapper Reaper/VstW)
#   28  : uint32 BE = len(total) - 40      (taille du bank CcnK)
#   180 : uint32 BE = taille du chunk plugin (= JSON + 32 octets de trailer JUCEPrivateData)
_SIZE_FIELDS = ((0, "<I", 16), (28, ">I", 40))
_PLUGIN_SIZE_OFF = 180


def _meta(path, fallback):
    """(name, author, style, macros, macro_vals) lus dans le JSON .vital, repli = nom de fichier.
    macros = les 4 noms donnés par le sound-designer (top-level macro1..4) ; macro_vals = les
    valeurs du patch (settings.macro_control_N) — la feuille du bloc les affiche comme base."""
    name, author, style = fallback, "", ""
    macros, macro_vals = ["Macro 1", "Macro 2", "Macro 3", "Macro 4"], [0.0] * 4
    try:
        d = json.load(open(path))
        name = d.get("preset_name") or name
        author = d.get("author") or ""
        style = d.get("preset_style") or ""
        st = d.get("settings") or {}
        for i in range(4):
            m = str(d.get(f"macro{i + 1}") or "").strip()
            if m:
                macros[i] = m.title() if m == m.upper() else m   # "MACRO 1"/"GRIT" -> "Macro 1"/"Grit"
            try:
                macro_vals[i] = round(float(st.get(f"macro_control_{i + 1}", 0.0)), 3)
            except (TypeError, ValueError):
                pass
    except Exception as _e:
        _swallowed(_e)
    return name, author, style, macros, macro_vals


def _walk_vitals():
    """Itère (id, pack, path) sur tous les .vital : à la racine ET dans les sous-dossiers (= packs).
    L'id est le basename sans extension ; le pack = nom du sous-dossier ("" à la racine)."""
    for root, _dirs, files in os.walk(VITAL_DIR):
        rel = os.path.relpath(root, VITAL_DIR)
        pack = "" if rel == "." else rel.replace(os.sep, "/")
        for fn in sorted(files):
            if fn.endswith(".vital"):
                yield fn[:-6], pack, os.path.join(root, fn)


def list_presets():
    """Bibliothèque des .vital (récursive, packs = sous-dossiers) :
    [{id, name, author, style, pack, file}] triée par (pack, nom)."""
    out = []
    for pid, pack, path in _walk_vitals():
        name, author, style, macros, macro_vals = _meta(path, pid.replace("_", " "))
        out.append({"id": pid, "name": name, "author": author, "style": style, "pack": pack,
                    "file": path, "macros": macros, "macro_vals": macro_vals})
    out.sort(key=lambda p: (p["pack"], p["name"].lower()))
    return out


def preset_path(pid):
    """Chemin du .vital pour un id (basename sans extension), cherché récursivement dans les packs.
    None si absent/invalide. (Les ids restent des basenames : collision improbable entre packs ;
    on renvoie la 1re occurrence — à qualifier par pack si le besoin apparaît.)"""
    if not pid or "/" in pid or "\\" in pid or ".." in pid:
        return None
    for cand_id, _pack, path in _walk_vitals():
        if cand_id == pid:
            return path
    return None


def _safe_pack(name):
    """Nom de dossier de pack assaini (pas de séparateur, pas de '..')."""
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(name or "")).strip() or USER_PACK
    return base


def _is_vital_json(data: bytes):
    """True si `data` ressemble à un preset .vital (JSON avec au moins un champ Vital connu)."""
    try:
        d = json.loads(data)
        return isinstance(d, dict) and any(k in d for k in ("synth_version", "settings", "preset_name", "author"))
    except Exception:
        return False


def _save_one(data: bytes, filename: str, pack: str):
    """Écrit un .vital (validé) dans le pack donné. Renvoie l'id (basename) ou None si invalide."""
    if not _is_vital_json(data):
        return None
    stem = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(filename or "")).strip()
    if stem.endswith(".vital"):
        stem = stem[:-6]
    stem = stem or "preset"
    dst_dir = os.path.join(VITAL_DIR, pack)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, stem + ".vital")
    n = 2
    while os.path.exists(dst):                       # ne jamais écraser un preset existant
        dst = os.path.join(dst_dir, f"{stem}-{n}.vital"); n += 1
    with open(dst, "wb") as f:
        f.write(data)
    return os.path.basename(dst)[:-6]


def save_upload(filename: str, data: bytes):
    """Ajoute un upload à la bibliothèque. Accepte :
      - .vital           -> pack 'user'
      - .vitalbank/.zip  -> extrait chaque .vital dans un pack nommé d'après l'archive
    Renvoie {ok, added:[ids], pack, error?}. Ne casse jamais sur un fichier douteux (ignoré)."""
    fn = (filename or "").strip()
    low = fn.lower()
    if low.endswith(".vital"):
        pid = _save_one(data, fn, USER_PACK)
        if not pid:
            return {"ok": False, "error": "invalid .vital file (not a Vital preset)"}
        return {"ok": True, "added": [pid], "pack": USER_PACK}
    if low.endswith(".zip") or low.endswith(".vitalbank"):
        pack = _safe_pack(re.sub(r"\.(zip|vitalbank)$", "", fn, flags=re.I))
        added = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.is_dir() or not info.filename.lower().endswith(".vital"):
                        continue
                    pid = _save_one(z.read(info), os.path.basename(info.filename), pack)
                    if pid:
                        added.append(pid)
        except zipfile.BadZipFile:
            return {"ok": False, "error": "unreadable archive (corrupt zip/vitalbank)"}
        if not added:
            return {"ok": False, "error": "no .vital preset in the archive"}
        return {"ok": True, "added": added, "pack": pack}
    return {"ok": False, "error": "unsupported format (expected .vital, .vitalbank or .zip)"}


def delete_preset(pid: str):
    """Supprime un preset (déplacé en corbeille assets/.trash/vital/). Renvoie {ok, error?}.
    Refuse le pack factory/ (seed versionné) pour ne pas perdre les défauts par mégarde."""
    path = preset_path(pid)
    if not path:
        return {"ok": False, "error": "preset not found"}
    if os.path.relpath(path, VITAL_DIR).split(os.sep)[0] == "factory":
        return {"ok": False, "error": "factory preset (seed) protected — cannot delete"}
    trash = os.path.join(C.ROOT, "assets", ".trash", "vital")
    os.makedirs(trash, exist_ok=True)
    dst = os.path.join(trash, os.path.basename(path))
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(trash, f"{pid}-{n}.vital"); n += 1
    shutil.move(path, dst)
    return {"ok": True}


def _bound_devices(role=None):
    """Bindings USB actifs (config/soundcard.json), filtrés par rôle (P0 claviers,
    docs/archive/keys-rig-plan.md). Rétro-compat : une entrée sans `roles` vaut
    ["keys","pads"] (l'AKAI historique)."""
    # TOUS les appareils connus (bridge/devices.py, 2026-09-23) — la présence se lit ensuite avec
    # _hw_of : un appareil débranché n'est plus perdu, il est juste absent ce soir
    from . import devices
    out = []
    for e in devices.known().values():
        if not e.get("name"):
            continue
        roles = e.get("roles") or ["keys", "pads"]
        if role is None or role in roles:
            out.append({"device": e["name"], "roles": roles})
    return out


def _hw_of(device_name):
    """Nom ALSA "hw:<id>" d'un device PRÉSENT (par nom, /proc/asound/cards) — None si débranché.
    Windows/macOS : le nom du port MIDI présent (celui que REAPER donne à son entrée)."""
    if sys.platform in ("win32", "darwin"):
        from . import devices
        hit = next((d for d in devices.detected() if devices._match({"name": device_name}, d)), None)
        return hit and hit.get("hw")
    try:
        for ln in open("/proc/asound/cards"):
            m = re.match(r"\s*\d+\s+\[(\S+)\s*\]:\s*\S+ - (.*)", ln)
            if m and m.group(2).strip() == device_name:
                return "hw:" + m.group(1)
    except Exception as _e:
        _swallowed(_e)
    # REPLI par l'identité (2026-10-13) : le registre garde le nom USB LONG (« AKAI MPK Mini Mk II »), /proc le
    # COURT (« MPK Mini Mk II ») — l'égalité ratait, la lane Keys n'avait pas de contrôleur nommé (golem_rig
    # devinait par heuristique) et rien ne pouvait s'attacher à CE contrôleur (ses canaux, bridge/akai_mpk.py).
    # Même règle que Windows/macOS ci-dessus : devices._match (VID:PID, sinon le nom en containment).
    try:
        from . import devices
        known = [e for e in devices.known().values() if (e.get("name") or "") == device_name] or [{"name": device_name}]
        for d in devices.detected():
            if d.get("hw") and any(devices._match(e, d) for e in known):
                return d["hw"]
    except Exception as _e:
        _swallowed(_e)
    return None


def _best_input(role):
    """Meilleur device BRANCHÉ pour un rôle : un contrôleur dédié (moins de rôles)
    gagne sur un hybride — le 88 touches (["keys"]) prime sur l'AKAI (keys+pads),
    et le fallback est automatique quand on le débranche."""
    candidates = []
    for b in _bound_devices(role):
        hw = _hw_of(b["device"])
        if hw:
            candidates.append((len(b["roles"]), hw))
    candidates.sort()
    return candidates[0][1] if candidates else None


def port_midi_input(in_sel):
    """Device MIDI d'un PORT USB du rack (in_sel "usbN") : le binding de config/soundcard.json, s'il
    est branché. None si pas de port nommé, pas lié, ou débranché."""
    m = re.fullmatch(r"usb(\d)", str(in_sel or ""))
    if not m:
        return None
    from . import devices
    b = devices.bindings().get(f"usb{m.group(1)}")
    if isinstance(b, dict) and b.get("enabled") and b.get("device"):
        return _hw_of(b["device"])
    return None


def drums_devices():
    """Les devices MIDI BRANCHÉS liés au rôle drums (hw:<id>) — ce qu'une lane Keys ne doit JAMAIS
    prendre par son heuristique de repli (revue 2026-09-17, P7 : un module de batterie est un
    `hw:` de plus, l'AKAI débranché la lane Keys l'aurait pris)."""
    out = []
    for b in _bound_devices("drums"):
        hw = _hw_of(b["device"])
        if hw:
            out.append(hw)
    return out


def midi_input_for(role=None, in_sel=None):
    """Le contrôleur d'une lane MIDI (docs/drums-kit.md lot 2) : le PORT qu'elle nomme d'abord,
    sinon le meilleur device de son RÔLE (drums -> un module de batterie, jamais l'AKAI), sinon le
    chemin historique des claviers. ⚠ golem_rig retombe sur une heuristique mpk/akai/hw: quand le
    hint est nul : une lane Drums sans module branché doit donc rendre None ET le dire."""
    hw = port_midi_input(in_sel)
    if hw:
        return hw
    if role == "drums":
        return _best_input("drums")
    return _best_input("keys")


def lane_port(role=None, in_sel=None):
    """Le PORT USB (n°) que joue VRAIMENT une lane MIDI — la règle de midi_input_for, en un seul endroit. Un `in_sel`
    nu (« usb », les lanes Keys des presets d'usine) n'est pas le port 1 : c'est le meilleur device de son rôle, là
    où il est branché (le MPK en USB 2 chez le mainteneur). Le Designer (sa couleur verte/orange, son « USB n ») et le Riff
    (compo._entry_of_lane) lisent ce numéro au lieu de deviner 1 (2026-11-02). None = rien de branché pour elle."""
    m = re.fullmatch(r"usb(\d)", str(in_sel or ""))
    if m:
        return int(m.group(1))
    hw = midi_input_for(role, in_sel)
    if not hw:
        return None
    from . import devices
    for k, b in devices.bindings().items():
        if b.get("device") and _hw_of(b["device"]) == hw:
            return int(k[3:])
    return None


def keys_midi_input():
    """Device MIDI (ALSA raw "hw:<id>") de la lane Keys — rôle "keys", 88 dédié
    prioritaire, fallback AKAI. None si rien de lié/branché — golem_rig retombe
    alors sur son heuristique (mpk/akai/hw: hors carte son)."""
    return _best_input("keys")


def pads_midi_input():
    """Device des PADS (bloc pads) — rôle "pads". Tant que la lane Keys est
    mono-piste (pré-P2), utilisé seulement si ≠ du device keys (la sous-piste
    pads arrive en P2) ; aujourd'hui l'AKAI porte les deux."""
    return _best_input("pads")


def splice_chunk(template_b64: str, vital_file: str) -> str:
    """Greffe le JSON d'un .vital dans un vst_chunk template (b64) -> nouveau b64 prêt pour
    SetNamedConfigParm('vst_chunk'). Lève ValueError si le template n'a pas la tête attendue."""
    raw = bytearray(base64.b64decode(template_b64.strip()))
    if raw[8:12] != b"VstW" or raw[24:28] != b"CcnK":
        raise ValueError("template vst_chunk inattendu (pas de VstW/CcnK) — plugin non-JUCE ?")
    i = bytes(raw).find(b'{"')
    j = bytes(raw).rfind(b"}")
    if i < 0 or j <= i:
        raise ValueError("pas de JSON dans le template vst_chunk")
    new_json = open(vital_file, "rb").read().rstrip(b"\x00\n\r ")
    delta = len(new_json) - (j + 1 - i)
    out = bytearray(raw[:i] + new_json + raw[j + 1:])
    for off, fmt, _sub in _SIZE_FIELDS:
        struct.pack_into(fmt, out, off, struct.unpack_from(fmt, out, off)[0] + delta)
    struct.pack_into(">I", out, _PLUGIN_SIZE_OFF,
                     struct.unpack_from(">I", out, _PLUGIN_SIZE_OFF)[0] + delta)
    # sanity : les invariants de taille doivent tomber juste après correction
    if struct.unpack_from("<I", out, 0)[0] != len(out) - 16:
        raise ValueError("greffe vst_chunk incohérente (champ de taille LE@0)")
    return base64.b64encode(bytes(out)).decode()


EDITED_PACK = "edited"


def chunk_json(b64: str) -> bytes:
    """Le JSON .vital contenu dans un vst_chunk (l'inverse de splice_chunk). Mesuré le 2026-10-14 sur l'instance
    vivante : 238 Ko, clés d'un .vital (settings, macro1-4, synth_version…), et deux lectures sans retouche rendent
    le même état à l'octet. ValueError si ce n'est pas un état Vital."""
    raw = base64.b64decode(b64.strip())
    if raw[8:12] != b"VstW" or raw[24:28] != b"CcnK":
        raise ValueError("not a VST state")
    i, j = raw.find(b'{"'), raw.rfind(b"}")
    if i < 0 or j <= i or not _is_vital_json(raw[i:j + 1]):
        raise ValueError("no Vital preset in this state")
    return raw[i:j + 1]


def save_edited(data: bytes, from_id: str, block_id: str):
    """Range le son retouché dans la fenêtre de Vital (2026-10-14) : pack « edited », UN fichier par
    (son d'origine, bloc) — rouvrir et retoucher le même bloc réécrit le même fichier au lieu d'empiler des
    copies. Le preset d'origine n'est jamais touché : le rechoisir dans la liste rend le son d'avant.
    Nom affiché : celui d'origine + « (edited) ». Rend l'id du preset."""
    src = preset_path(from_id) if from_id else None
    if src and os.path.basename(os.path.dirname(src)) == EDITED_PACK:
        stem, name = from_id, _meta(src, from_id)[0]               # déjà une retouche : on la réécrit
    else:
        base = _meta(src, from_id or "Vital")[0] if src else (from_id or "Vital")
        stem = re.sub(r"[^A-Za-z0-9._-]", "_", f"{from_id or 'vital'}~{block_id}")[:120]
        name = base + " (edited)"
    d = json.loads(data)
    d["preset_name"] = name
    dst_dir = os.path.join(VITAL_DIR, EDITED_PACK)
    os.makedirs(dst_dir, exist_ok=True)
    tmp = os.path.join(dst_dir, stem + ".vital.tmp")
    with open(tmp, "w") as f:
        json.dump(d, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(dst_dir, stem + ".vital"))
    return stem, name


# ── Vitalium LV2 (Windows : PawPaw) ────────────────────────────────────────────────────────────────
# Le LV2 n'a pas de vst_chunk : l'état passe par le CHUNK de piste (bloc <LV2 : lignes P des ports +
# <X urn:juce:stateBinary>), relu à l'instanciation (FXID retiré). Les ports appartiennent à l'hôte et
# écrasent l'état binaire : un .vital ne passe ENTIER que si on écrit aussi chaque port — sinon les
# paramètres retombent à leur défaut et seuls wavetables/modulations suivent (mesuré 2026-10-03).
LV2_PORTS = os.path.join(os.path.dirname(__file__), "templates", "vitalium-lv2-ports.json")
_lv2_ports = None


def lv2_ports():
    """{symbole de port: (id Vital, min, max)} — bornes lues sur le plugin (voir le fichier)."""
    global _lv2_ports
    if _lv2_ports is None:
        _lv2_ports = {k: tuple(v) for k, v in json.load(open(LV2_PORTS, encoding="utf-8"))["ports"].items()}
    return _lv2_ports


def lv2_state(vital_file: str) -> str:
    """Texte lu par golem_rig (chunk_set_vitalium) : une ligne « P <port> <normalisée> » par port que
    le .vital renseigne, puis « B <base64> » (JSON .vital + NUL final, comme le sérialise Vitalium).
    Un paramètre absent du .vital (preset d'une version antérieure) n'a pas de ligne : l'instance
    neuve garde son défaut, comme Vital à l'ouverture du fichier."""
    raw = open(vital_file, "rb").read().rstrip(b"\x00\n\r ")
    settings = json.loads(raw).get("settings") or {}
    out = []
    for sym, (pid, lo, hi) in sorted(lv2_ports().items()):
        v = settings.get(pid)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or hi == lo:
            continue
        out.append("P %s %.9g" % (sym, min(1.0, max(0.0, (float(v) - lo) / (hi - lo)))))
    b64 = base64.b64encode(raw + b"\x00").decode()
    out.extend("B " + b64[i:i + 256] for i in range(0, len(b64), 256))
    return "\n".join(out) + "\n"
