#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pré-configure reaper.ini pour GoleM, SANS rien casser : ajoute/garantit seulement
les clés nécessaires (device OSC + carte audio + activation MIDI de la lane Keys).
Sauvegarde d'abord. Idempotent.

⚠ Reaper réécrit reaper.ini à la fermeture → lancer ce script **Reaper FERMÉ**.

  python3 provision/reaper-ini-setup.py

--- Activation MIDI (lane Keys) -----------------------------------------------
Reaper stocke l'état "device MIDI d'entrée activé" dans un BITMASK indexé par
index de device Reaper (celui de reaper.GetMIDIInputName / I_RECINPUT) :

  midiins          bits  0..31   (device index 0..31)
  midiins_h        bits  0..31   -> device index 32..63
  midiins_x        bits  0..31   -> device index 64..95
  midiins_x_h      bits  0..31   -> device index 96..127

  midiins_cs*      idem, mais "Enable input for control messages" (déclenche des
                   actions Reaper) — on le laisse à 0 pour la lane Keys : un
                   clavier ne doit PAS piloter des actions.
  midiins_nowarn*  idem, "ne pas avertir si le device est absent" — on l'active
                   pour le device Keys : un boot kiosk headless ne doit PAS
                   ouvrir de pop-up modale si l'AKAI est débranché.

Réf. valeurs réelles : une config publique a midiins=1581057 (bits 0,13,19,20)
et midiins_cs=1581057 identiques => bit = index de device, deux masques séparés
(input / control).

On N'active QUE le device AKAI (le clavier de la lane Keys), JAMAIS "tous les
inputs" : le MIDI du Volt 276 (hw:V276) est détenu en exclusif par le bridge
Python (aseqdump/amidi pour la Whammy DT). Si Reaper ouvrait aussi le rawmidi du
Volt, il entrerait en conflit avec le bridge. On écrase donc le masque à
"AKAI seul" (pas de OR : un bit rémanent d'un ancien ordre USB pourrait tomber
sur le Volt).

Index de device : ⚠ CE N'EST PAS l'ordre `amidi -l` (piège chassé le 2026-07-26).
Reaper PERSISTE sa liste de devices dans ~/.config/REAPER/reaper-midihw-alsa.ini
[mididevcache] :

    it0=1 / in0=virtual          <- slot 0 réservé
    it1=1 / in1=hw:V276
    it2=1 / in2=hw:II            <- l'AKAI
    it3=1 / in3=hw:iTwo          <- débranchée, MAIS l'index reste réservé

L'ordre est celui de la PREMIÈRE RENCONTRE, et un device débranché n'est JAMAIS
retiré. Après la valse USB (Presonus iTwo adoptée puis retour Volt, AKAI
rebranché ailleurs), l'ordre `amidi -l` (par n° de carte : AKAI card1 en tête)
donnait index 1 pour l'AKAI... alors que l'index 1 de Reaper est hw:V276.
Résultat vécu : Reaper ouvrait la SORTIE MIDI de la carte son (rawmidi ALSA =
EXCLUSIF) -> Whammy muette, et n'ouvrait jamais l'AKAI -> lane Keys + horloge
MIDI mortes, sans le moindre message d'erreur.

Donc : la source de vérité est le [mididevcache] de Reaper. On y cherche le
contrôleur Keys par NOM — sachant que Reaper nomme ses devices
« hw:<id de carte ALSA> » (« hw:II »), qui ne contient rien du nom commercial :
on résout l'id via /proc/asound/cards (les DEUX lignes — la 2e porte le nom
constructeur, celui que la calibration enregistre). `amidi -l` ne sert plus que
de REPLI, quand le cache n'existe pas encore (machine vierge : Reaper construira
sa liste dans l'ordre des cartes, ce que `amidi -l` reflète).

QUEL contrôleur ouvrir n'est PAS codé en dur (audit 2026-08-12 §3, chantier ②) :
les noms viennent de la CONFIG — binding actif (config/soundcard.json) + profils
calibrés (config/controllers/*.json). Repli : l'ancien motif mpk|akai, pour un
rack jamais calibré (l'AKAI d'origine ne doit JAMAIS régresser). Les motifs
retenus sont publiés dans presets/.keys-midi.json pour la sentinelle Lua.

⚠ PIÈGE DU 2026-09-11 — « à chaque reboot le MIDI est en erreur ». Un contrôleur DÉBRANCHÉ
garde son slot dans le cache de Reaper, mais n'est plus NOMMABLE : Reaper l'appelle « hw:II » et
/proc/asound/cards ne l'enrichit plus en « AKAI MPK Mini Mk II ». La résolution par nom échouait
donc, et ce script écrasait midiins/midiouts à 0 — mesuré : reaper.ini.bak=4, reaper.ini=0. Or le
geste quotidien est « je démarre le rig, PUIS je branche le clavier » : le masque partait à 0
avant même que l'AKAI soit sur le bus, et le rebrancher ne rendait plus rien (masque 0, silence,
aucune erreur) jusqu'à une relance complète. Remède : keys_memory() — on MÉMORISE le device
résolu par nom (presets/.keys-midi.json « devices »), et un contrôleur absent garde son bit.
`nowarn` porte déjà la même valeur : aucune modale au boot kiosk.

Le miroir runtime de cette résolution vit dans reaper/Scripts/golem_midi.lua
(sentinelle : publie presets/.midi.json, répare à chaud si SWS est présent).
"""
import glob, json, os, re, sys, shutil, subprocess

INI = os.path.expanduser("~/.config/REAPER/reaper.ini")

# Racine du dépôt (ce script vit dans provision/) : la config data-driven est là.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
# Motifs publiés pour golem_midi.lua (le Lua ne sait pas lire du JSON imbriqué :
# un fichier PLAT, sur le patron de presets/.command.json). Absent => repli Lua.
KEYS_SIDECAR = os.path.join(ROOT, "presets", ".keys-midi.json")

# REPLI historique : reconnaissait le clavier maître (AKAI MPK) quand aucune
# config n'existe. Équivalent de l'ancien re.compile(r"mpk|akai", re.IGNORECASE).
KEYS_FALLBACK = ("mpk", "akai")


def keys_name_patterns(soundcard=None, profiles=None):
    """Motifs (minuscules, match par SOUS-CHAÎNE insensible à la casse) reconnaissant le
    contrôleur clavier/pads. La source est la CONFIG, pas le code (audit 2026-08-12 §3 ②) :
      · binding actif de config/soundcard.json — champ `device`, même sémantique que
        vital._bound_devices (enabled + device ; un binding sans `roles` = keys+pads) ;
      · profils calibrés config/controllers/*.json — champ `name`, écrit par le wizard.
    Sans ça, un Arturia/Novation calibré au wizard restait INVISIBLE de Reaper : jamais
    ouvert, silence total sans erreur — la panne « hors du graphe vivant », version MIDI.
    REPLI si aucune donnée (rack jamais calibré, AKAI d'origine) : mpk|akai.
    Fonction PURE (testable à froid). Retourne (patterns, source_texte)."""
    pats = []
    for b in (soundcard or {}).values():
        if isinstance(b, dict) and b.get("enabled") and b.get("device"):
            pats.append(str(b["device"]).strip().lower())
    for p in profiles or []:
        if isinstance(p, dict) and p.get("name"):
            pats.append(str(p["name"]).strip().lower())
    pats = [p for i, p in enumerate(pats) if p and p not in pats[:i]]   # dédoublonné, ordre stable
    if pats:
        return pats, "config (soundcard.json + controllers/)"
    return list(KEYS_FALLBACK), "repli mpk|akai (aucun binding ni profil calibré)"


def keys_match(rich_name, patterns):
    """Le nom enrichi d'un device désigne-t-il le contrôleur Keys ? (sous-chaîne, casse ignorée)"""
    low = str(rich_name or "").lower()
    return any(p in low for p in patterns)


def _read_keys_sources():
    """Lit les fichiers de config — TOLÉRANT : un JSON absent/corrompu ne casse pas le
    provisioning (on retombera sur le repli mpk|akai, jamais sur une exception au boot)."""
    sc, profs = {}, []
    # depuis le 2026-09-23 : config/devices.json (appareils CONNUS, branchés ou non — un connu garde son
    # bit, c'est la panne du 09-11 réglée à la racine) ; soundcard.json en repli (rack pas encore migré)
    try:
        with open(os.path.join(CONFIG_DIR, "devices.json"), encoding="utf-8") as f:
            devs = (json.load(f) or {}).get("devices") or {}
        sc = {k: {"enabled": True, "device": e.get("name")} for k, e in devs.items() if isinstance(e, dict) and e.get("name")}
    except Exception:
        try:
            with open(os.path.join(CONFIG_DIR, "soundcard.json"), encoding="utf-8") as f:
                sc = json.load(f)
        except Exception:
            sc = {}
    for p in sorted(glob.glob(os.path.join(CONFIG_DIR, "controllers", "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                profs.append(json.load(f))
        except Exception:
            pass
    return (sc if isinstance(sc, dict) else {}), profs


def _soundcard_hw():
    """« hw:<id> » de la CARTE SON (config/io.json) : son MIDI appartient au BRIDGE (FCB en
    entrée, Whammy en sortie) — jamais candidate Keys, même si un binding mal saisi la nommait."""
    try:
        with open(os.path.join(CONFIG_DIR, "io.json"), encoding="utf-8") as f:
            dev = json.load(f).get("device") or ""
        return dev if str(dev).startswith("hw:") else None
    except Exception:
        return None


def read_keys_sidecar():
    """Contenu du sidecar — TOLÉRANT (absent/corrompu -> {})."""
    try:
        with open(KEYS_SIDECAR, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def keys_memory():
    """Dernier device REAPER (« hw:II ») reconnu comme contrôleur Keys, par direction.

    ⚠ LA PANNE DU 2026-09-11 (« à chaque reboot le MIDI est en erreur ») : un contrôleur
    DÉBRANCHÉ n'est plus NOMMABLE — Reaper l'appelle « hw:II » et /proc/asound/cards ne
    l'enrichit plus en « AKAI MPK Mini Mk II ». La résolution par nom échouait donc, et ce
    script ÉCRASAIT midiins/midiouts à 0 (mesuré : reaper.ini.bak = 4, reaper.ini = 0). Le
    clavier rebranché n'était plus jamais ouvert : masque à 0, silence, aucune erreur.
    L'index dans le cache de Reaper, lui, est IMMUABLE (un device débranché garde son slot) :
    on le mémorise pour garder le bit. `nowarn` porte déjà la même valeur — aucune modale."""
    devs = read_keys_sidecar().get("devices")
    if not isinstance(devs, dict):
        return {}
    return {k: v for k, v in devs.items() if isinstance(v, str) and v}


def write_keys_sidecar(patterns, source, devices=None):
    """Publie les motifs + la mémoire des devices pour golem_midi.lua (atomique).
    devices=None PRÉSERVE la mémoire existante. Absent => le Lua retombe sur mpk|akai."""
    if devices is None:
        devices = keys_memory()
    try:
        os.makedirs(os.path.dirname(KEYS_SIDECAR), exist_ok=True)
        tmp = KEYS_SIDECAR + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"patterns": patterns, "source": source, "devices": devices},
                      f, ensure_ascii=False)
        os.replace(tmp, KEYS_SIDECAR)
    except OSError as e:
        print(f"⚠ {KEYS_SIDECAR} non écrit ({e}) — golem_midi restera sur le repli mpk|akai")


def remember_keys_device(direction, name):
    """Mémorise le device résolu PAR NOM — la seule résolution qui fasse foi. Idempotent."""
    mem = keys_memory()
    if mem.get(direction) == name:
        return
    mem[direction] = name
    sc = read_keys_sidecar()
    write_keys_sidecar(sc.get("patterns") or [], sc.get("source") or "", mem)

# LA CARTE SON DE REAPER (2026-11-03). Avant : `alsa_indev/outdev=hw:V276` en dur — la Volt de l'auteur — et AUCUN
# `linux_audio_mode`. Sur un golem neuf (portable Ubuntu 26.04, PreSonus iTwo branchée), REAPER partait en JACK (son
# défaut quand la clé manque), échouait, ouvrait « Error opening devices » : une modale qui fige tout le moteur, le
# rappel n'était jamais lu, l'écran de chargement attendait la carte pour toujours.
# Désormais : ALSA brut (le choix de golem, cf. bridge/monitors.py), sur la carte ACTIVE résolue comme le bridge
# (bridge/config.alsa_card : io.json > registre > carte USB branchée). Aucune carte : le PCM `null` d'ALSA, un vrai
# périphérique muet — le moteur tourne sans modale, et la carte sera prise au prochain démarrage où elle est là.
LINUX_AUDIO_ALSA = "1"          # reaper.ini linux_audio_mode : 1 = ALSA (même valeur que tools/shell_snapshot.py)


def active_card():
    """Id ALSA de la carte active (« iTwo »), ou « » — par le bridge lui-même, pour ne jamais diverger."""
    env = os.environ.get("GOLEM_ALSA_CARD")
    if env:
        return env
    try:
        sys.path.insert(0, ROOT)
        from bridge import config as _bc
        return _bc.alsa_card() or ""
    except Exception as e:
        print(f"⚠ carte active non résolue ({e}) — périphérique ALSA « null »")
        return ""
    finally:
        if sys.path and sys.path[0] == ROOT:
            sys.path.pop(0)


def card_present(device):
    """`hw:<id>` désigne-t-il une carte BRANCHÉE ? (/proc/asound/<id> existe tant que la carte est là)"""
    d = str(device or "")
    if not d.startswith("hw:"):
        return False
    return os.path.isdir(f"/proc/asound/{d[3:].split(',')[0]}")


def audio_keys(section_values):
    """(à insérer si absentes, à corriger) pour la carte de REAPER. On ne touche à une valeur existante QUE si elle
    désigne une carte ABSENTE (ou `null`) alors que la carte active, elle, est branchée : REAPER ne peut rien ouvrir
    d'autre, et sa modale d'erreur figerait le moteur. Un choix de l'utilisateur qui marche n'est jamais changé."""
    card = active_card()
    dev = f"hw:{card}" if card else "null"
    insert = {"linux_audio_mode": LINUX_AUDIO_ALSA, "alsa_indev": dev, "alsa_outdev": dev}
    fix = {}
    if card and card_present(dev):
        for k in ("alsa_indev", "alsa_outdev"):
            cur = section_values.get(k)
            if cur is not None and cur != dev and (cur == "null" or not card_present(cur)):
                fix[k] = dev
    return insert, fix

# Valeurs FORCÉES pour le moteur de scènes (écrasent une valeur existante, comme les masques MIDI).
# norunmute=0 : Reaper TRAITE les pistes muettes. Les branches d'un split se taisent par un mute de
# piste (docs/live-engine.md) ; si l'option « ne pas traiter les pistes muettes » était cochée — un
# réflexe pour gagner du CPU —, une branche muette s'arrêterait et chaque retour en scène réveillerait
# ses plugins : le convolveur d'IR fige alors TOUT le moteur ~540 ms (mesuré le 2026-09-21).
# automute=0 : sans lui, REAPER coupe EN PLEIN MORCEAU une piste qui dépasse +6 dB (Preferences ▸ Audio),
# sans rien dans nos journaux. Sur scène, un mute surprise est le pire ; notre garde est le limiteur
# golem_safety en fin de chaîne (provision/system-tuning.md).
ENGINE_FORCED = {"norunmute": "0", "automute": "0"}

# device OSC : seulement si AUCUN control surface n'est configuré.
OSC_LINES = [
    'csurf_0=OSC "golem" 3 8000 "127.0.0.1" 9000 1024 10 "golem"',
    "csurf_cnt=1",
]


def _receipt():
    """provision/receipt.py chargé par son chemin (ce script tourne aussi importé par les tests) — None s'il
    manque : le reçu ne casse jamais la configuration de REAPER."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "golem_receipt", os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def record_prior(section, keys, csurf_added, existed=True):
    """Reçu d'install (docs/uninstall.md §2) : la valeur d'AVANT de chaque clé que ce script écrit (None =
    absente), et si le control surface OSC est le nôtre. Le premier passage gagne (receipt.prior) — c'est
    lui, et non reaper.ini.bak (réécrit à chaque passage), qui dit ce qu'il faut remettre. Jamais d'exception."""
    R = _receipt()
    # SEULEMENT si le reçu existe : start.sh relance ce script avant CHAQUE démarrage du moteur. Sur une machine
    # installée avant le reçu, en créer un ici n'y mettrait que nos propres valeurs, prises pour celles d'avant.
    # (install.sh crée le reçu avant setup-reaper.sh.)
    if R is None or not R.exists():
        return
    try:
        cur = {}
        for line in section:
            if "=" in line:
                k, v = line.split("=", 1)
                cur.setdefault(k.strip(), v)
        if not existed:
            R.prior("reaper_ini.existed", False)
        for k in keys:
            R.prior(f"reaper_ini.keys.{k}", cur.get(k))
        R.prior("reaper_ini.csurf_added", bool(csurf_added))
    except Exception as e:
        print(f"⚠ reçu d'install non mis à jour ({e})")


def reaper_running():
    try:
        return subprocess.run(["pgrep", "-x", "reaper"], capture_output=True).returncode == 0
    except Exception:
        return False


MIDIHW = os.path.expanduser("~/.config/REAPER/reaper-midihw-alsa.ini")


def alsa_card_names():
    """id ALSA court -> nom long, les DEUX lignes de /proc/asound/cards :
       " 1 [II             ]: USB-Audio - MPK Mini Mk II"          (driver - nom)
       "                      AKAI MPK Mini Mk II at usb-…"        (nom CONSTRUCTEUR)
    -> {"II": "USB-Audio - MPK Mini Mk II AKAI MPK Mini Mk II"}.
    ⚠ La 2e ligne est CELLE que la calibration enregistre comme `name` du profil
    (controllers.detected) : sans elle, un profil calibré ne matcherait JAMAIS."""
    out, last = {}, None
    try:
        txt = open("/proc/asound/cards", encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for line in txt.splitlines():
        m = re.match(r"\s*(\d+)\s*\[([^\]]+?)\s*\]\s*:\s*(.*)", line)
        if m:
            out[m.group(2)] = m.group(3).strip()
            last = m.group(2)
        elif last is not None:
            desc = line.split(" at ")[0].strip()      # « … at usb-0000:… » : le chemin USB est du bruit
            if desc:
                out[last] = (out[last] + " " + desc).strip()
            last = None
    return out


def _amidi_ports(direction):
    """Ports rawmidi branchés, dans l'ordre des cartes, NOMMÉS COMME REAPER (« hw:<id carte> »).
    direction: "I" (entrées) | "O" (sorties). Sert de repli quand Reaper n'a pas encore de cache."""
    try:
        out = subprocess.run(["amidi", "-l"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    cards = {}
    try:
        for line in open("/proc/asound/cards", encoding="utf-8", errors="replace"):
            m = re.match(r"\s*(\d+)\s*\[([^\]]+?)\s*\]", line)
            if m:
                cards[m.group(1)] = m.group(2)
    except OSError:
        pass
    res = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or parts[0] == "Dir":
            continue
        if direction not in parts[0]:
            continue
        m = re.match(r"hw:(\d+),", parts[1])           # "hw:1,0,0" -> carte 1 -> id ALSA -> "hw:II"
        name = f"hw:{cards.get(m.group(1), m.group(1))}" if m else parts[1]
        if name not in res:
            res.append(name)
    return res


def _devcache(prefix):
    """[mididevcache] de Reaper -> {index: nom}. prefix "in" (entrées) ou "on" (sorties)."""
    try:
        txt = open(MIDIHW, encoding="latin-1").read()
    except OSError:
        return {}
    res = {}
    for m in re.finditer(rf"^{prefix}(\d+)\s*=\s*(.*)$", txt, re.M):
        res[int(m.group(1))] = m.group(2).strip()
    return res


def resolve_keys_index(order, rich, patterns, sc_hw=None, remembered=None):
    """PURE : index du contrôleur Keys dans `order` (noms de device Reaper, index = position).
      1) PAR NOM — le device est BRANCHÉ : /proc/asound/cards enrichit « hw:II » en
         « … AKAI MPK Mini Mk II ». Seule résolution qui fasse foi (et qu'on mémorise).
      2) PAR MÉMOIRE — le device est DÉBRANCHÉ : plus rien à matcher, mais son index de cache
         Reaper ne bouge jamais. Sans ce repli le masque partait à 0, et le clavier rebranché
         n'était plus jamais ouvert (cf. keys_memory).
    La carte son n'est JAMAIS candidate — mémoire comprise : son MIDI appartient au bridge.
    Retourne (index, nom de device, "name"|"memory") ou (None, None, None)."""
    for idx, name in enumerate(order):
        if name and name != sc_hw and keys_match(rich(name), patterns):
            return idx, name, "name"
    if remembered and remembered != sc_hw:
        for idx, name in enumerate(order):
            if name and name == remembered:
                return idx, name, "memory"
    return None, None, None


def reaper_midi_index(direction):
    """Index de device MIDI Reaper du contrôleur Keys. direction: "in" (entrées) | "out" (sorties).
    Renvoie (index, nom_lisible, source) — (None, None, source) si introuvable.

    1) Source de vérité = le cache de devices de Reaper (ordre de PREMIÈRE RENCONTRE ; un device
       débranché GARDE son index). Le nom y est « hw:<id carte ALSA> » -> enrichi via
       /proc/asound/cards pour pouvoir matcher le nom déclaré en config.
    2) Un device branché mais PAS encore dans le cache sera ajouté par Reaper À LA SUITE, dans
       l'ordre des cartes : on l'anticipe en concaténant les ports `amidi -l` inconnus du cache.
    3) Cache absent (machine vierge) : slot 0 = "virtual", puis l'ordre des cartes.
    QUI est « le contrôleur Keys » vient de la config (keys_name_patterns), plus jamais du code."""
    cards = alsa_card_names()
    patterns, psrc = keys_name_patterns(*_read_keys_sources())
    sc_hw = _soundcard_hw()

    def rich(name):
        m = re.match(r"hw:(.+)$", name or "")
        return f"{name} {cards.get(m.group(1), '')}".strip() if m else (name or "")

    cache = _devcache("in" if direction == "in" else "on")
    if cache:
        order = [cache.get(i, "") for i in range(max(cache) + 1)]
        source = "reaper-midihw-alsa.ini [mididevcache]"
    else:
        order = ["virtual"]
        source = "repli ordre des cartes (cache Reaper absent)"
    source += f" · motifs: {psrc}"
    for p in _amidi_ports("I" if direction == "in" else "O"):
        if p not in order:                       # branché, jamais vu par Reaper -> ajouté à la suite
            order.append(p)
    idx, name, how = resolve_keys_index(order, rich, patterns, sc_hw, keys_memory().get(direction))
    if idx is None:
        return None, None, source
    if how == "memory":                          # débranché : le bit tient, le nom ne dit plus rien
        return idx, name, source + " · MÉMOIRE (contrôleur débranché)"
    remember_keys_device(direction, name)
    return idx, rich(name), source


def akai_reaper_index():
    """Compat (nom historique) : index d'ENTRÉE du contrôleur Keys (voir reaper_midi_index)."""
    idx, name, _src = reaper_midi_index("in")
    return idx, name


def midi_enable_out():
    """Masques {cle: valeur} a FORCER pour n'activer QUE la sortie du contrôleur Keys (horloge -> arp).
    On ecrase midiouts* a "Keys seul" : la sortie du Volt 276 (Whammy) est detenue en EXCLUSIF par le
    bridge Python (amidi) -> Reaper ne doit JAMAIS ouvrir sa sortie. Retourne (overrides, note)."""
    idx, name, src = reaper_midi_index("out")
    regs = ["midiouts", "midiouts_h", "midiouts_x", "midiouts_x_h"]
    warn = ["midiouts_nowarn", "midiouts_nowarn_h", "midiouts_nowarn_x", "midiouts_nowarn_x_h"]
    ov = {k: "0" for k in regs + warn}  # Keys seul (sortie de la carte son JAMAIS activee)
    if idx is None:
        return ov, f"Keys OUT jamais résolu ({src}) — midiouts=0 (horloge sans sortie)"
    reg, bit = regs[idx // 32], idx % 32
    val = 1 << bit
    ov[reg] = str(val)
    ov[warn[idx // 32]] = str(val)      # nowarn : boot kiosk sans pop-up si debranche
    return ov, f"Keys OUT '{name}' = device out index {idx} -> {reg}={val} (bit {bit}) + nowarn [{src}]"


def midi_enable_keys_names():
    """Les clés de masques MIDI que ce script FORCE toujours (entrée + sortie), quelle que soit la résolution."""
    return ["midiins", "midiins_h", "midiins_x", "midiins_x_h", "midiins_nowarn", "midiins_nowarn_h",
            "midiins_nowarn_x", "midiins_nowarn_x_h", "midiins_cs",
            "midiouts", "midiouts_h", "midiouts_x", "midiouts_x_h", "midiouts_nowarn", "midiouts_nowarn_h",
            "midiouts_nowarn_x", "midiouts_nowarn_x_h"]


def midi_enable_keys():
    """Masques {clé: valeur} à FORCER pour n'activer QUE le contrôleur Keys en entrée MIDI.
    Retourne (overrides_dict, note)."""
    idx, name, src = reaper_midi_index("in")
    # Registre + bit selon l'index (0..31 / 32..63 / 64..95 / 96..127).
    regs = ["midiins", "midiins_h", "midiins_x", "midiins_x_h"]
    warn = ["midiins_nowarn", "midiins_nowarn_h", "midiins_nowarn_x", "midiins_nowarn_x_h"]
    ov = {k: "0" for k in regs + warn}  # on écrase à "Keys seul" (carte son jamais activée)
    ov["midiins_cs"] = "0"              # un clavier ne pilote JAMAIS d'actions Reaper
    if idx is None:
        return ov, f"contrôleur Keys jamais résolu ({src}) — MIDI-in à 0 (carte son protégée)"
    reg, bit = regs[idx // 32], idx % 32
    val = 1 << bit
    ov[reg] = str(val)
    ov[warn[idx // 32]] = str(val)      # nowarn : boot kiosk sans pop-up si débranché
    return ov, f"Keys '{name}' = device index {idx} -> {reg}={val} (bit {bit}) + nowarn [{src}]"


def main():
    if reaper_running():
        sys.exit("✗ Reaper est ouvert — ferme-le d'abord (il réécrirait reaper.ini).")
    # Publie les motifs Keys pour la sentinelle golem_midi.lua — AVANT tout : même si l'ini
    # est déjà conforme (retour anticipé plus bas), le Lua doit voir la config du jour.
    _pats, _psrc = keys_name_patterns(*_read_keys_sources())
    write_keys_sidecar(_pats, _psrc)
    existed = os.path.exists(INI)
    if not existed:
        # From-scratch (machine vierge, Reaper jamais lancé) : on crée un
        # reaper.ini minimal. Reaper complétera ses défauts au 1er lancement
        # et CONSERVE les clés existantes (audio/OSC/MIDI posées ci-dessous).
        os.makedirs(os.path.dirname(INI), exist_ok=True)
        with open(INI, "w", encoding="latin-1") as f:
            f.write("[reaper]\n")
        print(f"→ {INI} absent (machine vierge) — créé minimal, Reaper complétera.")

    lines = open(INI, encoding="latin-1").read().splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "[reaper]"), None)
    if start is None:
        sys.exit("✗ section [reaper] absente de reaper.ini.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    section = lines[start + 1:end]
    have = {l.split("=", 1)[0].strip() for l in section if "=" in l}
    values = {l.split("=", 1)[0].strip(): l.split("=", 1)[1].strip() for l in section if "=" in l}
    audio_insert, audio_fix = audio_keys(values)

    # 1) valeurs à FORCER (activation MIDI) : update in-place, insert si absente.
    overrides, midi_note = midi_enable_keys()
    out_ov, out_note = midi_enable_out()          # active la SORTIE AKAI (horloge MIDI -> arp)
    overrides.update(out_ov)
    overrides.update(ENGINE_FORCED)               # moteur de scènes + pas d'auto-mute (voir ENGINE_FORCED)
    overrides.update(audio_fix)                   # carte absente remplacée par la carte branchée (voir audio_keys)
    midi_note = midi_note + " | " + out_note
    changed = []
    for i in range(start + 1, end):
        if "=" not in lines[i]:
            continue
        k = lines[i].split("=", 1)[0].strip()
        if k in overrides:
            want = f"{k}={overrides[k]}"
            if lines[i] != want:
                lines[i] = want
                changed.append(k)
            overrides.pop(k)
    # 2) clés à INSÉRER si absentes (audio + OSC + tout override non trouvé).
    add = [f"{k}={v}" for k, v in overrides.items()]          # midiins* pas encore présents
    add += [f"{k}={v}" for k, v in audio_insert.items() if k not in have and k not in audio_fix]
    csurf_added = not any(k.startswith("csurf") for k in have)
    if csurf_added:
        add += OSC_LINES
    # reçu : TOUTES les clés que ce script possède (forcées, ou ajoutées si absentes), avec leur valeur
    # d'avant — même celles déjà conformes, c'était la valeur de la machine
    written = set(k for k in list(changed) + [a.split("=", 1)[0] for a in add] if not k.startswith("csurf"))
    written |= set(midi_enable_keys_names()) | set(ENGINE_FORCED)
    written |= {k for k in audio_insert if k not in have}
    record_prior(section, sorted(written), csurf_added, existed)

    if not add and not changed:
        print("✓ rien à faire — reaper.ini déjà conforme (OSC + audio + MIDI Keys).")
        print(f"  MIDI : {midi_note}")
        return

    shutil.copy2(INI, INI + ".bak")         # filet de confort ; la VÉRITÉ des valeurs d'avant est le reçu
    if add:
        # recalcule end (peut avoir bougé si des lignes ont changé de longueur — non ici)
        new = lines[:start + 1] + add + lines[start + 1:]
    else:
        new = lines
    open(INI, "w", encoding="latin-1").write("\n".join(new) + "\n")
    if changed:
        print(f"✓ mis à jour : {', '.join(changed)}")
    if add:
        print(f"✓ ajouté à [reaper] : {', '.join(a.split('=')[0] for a in add)}")
    print(f"  MIDI : {midi_note}")
    print(f"  (sauvegarde : {INI}.bak)")


if __name__ == "__main__":
    main()
