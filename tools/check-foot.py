#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Retest du PIED — l'étage rack, sans avoir besoin du pédalier.

    ./tools/check-foot.py                 # tout le contrat MIDI, injecté
    ./tools/check-foot.py --preset polaris
    ./tools/check-foot.py --live          # ÉCOUTE le vrai pédalier et te guide (60 s)

POURQUOI CE SCRIPT EXISTE
Le contrat du pied (docs/archive/fcb1010-mapping.md) n'a pas bougé, mais tout ce qu'il pilote a bougé :
setlists, modes, assignation libre des stomps, revendications de switch (sample, batterie,
arrangement, Rec, backing), gestes du looper. Un pédalier « périmé » ne se manifeste pas par une
panne franche — il fait échouer le test SUIVANT, au mauvais étage, et on cherche une soirée.

CE QU'IL VÉRIFIE, ET CE QU'IL NE PEUT PAS
Il rejoue les messages EXACTS de la puce via /api/foot/inject et vérifie ce que le rack en
comprend. C'est la moitié qui casse quand le code bouge. Restent au pied du mainteneur, et seulement à
lui : que la puce ÉMETTE bien ces messages, l'état des LED, les deux pédales d'expression, et le
MIDI MERGE (piège n°1 du contrat). Le script les liste à la fin, sous forme de courte checklist.

Il repose l'état d'origine en sortant — preset, scène et stomps.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

BRIDGE = "http://localhost:8770"
SCENE_CC = {20: "A", 21: "B", 22: "C", 23: "D", 24: "E"}
STOMP_CC = {30: 6, 31: 7, 32: 8, 33: 9, 34: 10}
FAILED = []


def call(path, body=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BRIDGE + path, data=data,
                               headers={"Content-Type": "application/json"}, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def state():
    return call("/api/state", method="GET")[1]


def wire_channel():
    """Le canal du pédalier ACTIF, sur le fil (0-15) — demandé au rack, jamais supposé."""
    return (call("/api/pedalboard", method="GET")[1].get("wire") or {}).get("wire_channel", 1)


def inject(**kw):
    call("/api/foot/inject", kw)
    time.sleep(0.35)                       # le recall passe par la boucle asyncio + Reaper
    return state()


def ok(label, good, detail=""):
    print(f"  {'✓' if good else '✗'} {label}" + (f" — {detail}" if detail else ""))
    if not good:
        FAILED.append(label)
    return good


def skip(label, why):
    """Rien à tester ici — et ce n'est PAS un échec. Un rack neuf (ou remis à zéro) n'a ni
    preset ni setlist : le chemin du pied peut être parfait, il n'a simplement rien à
    rappeler. Crier « ✗ » dans ce cas, c'est fabriquer un faux négatif — et un outil qui
    en fabrique est un outil qu'on cesse de lire."""
    print(f"  ⊘ {label} — {why}")
    return False


def looper_switches(st0):
    """Les switches que le looper POSSÈDE avec CE preset. Ils ne sont plus figés : la table de
    boucles du preset décide (docs/looper.md §1) — une 4e boucle prend SW9, deux boucles peuvent
    partager une source. On lit donc l'état du rack, on ne recopie pas une liste ici : c'est la
    divergence qui a fait crier cette sonde au loup deux fois déjà.
    SW5 (« tout jouer ») et SW10 (« tout effacer ») sont toujours au looper quand il est actif —
    y compris SW5, qui est sur la RANGÉE DES SCÈNES et remplace donc la scène E."""
    lp = st0.get("looper") or {}
    if not lp.get("enabled"):
        return frozenset()
    rows = lp.get("loops") or lp.get("slots") or []
    sws = {int(r["sw"]) for r in rows if isinstance(r, dict) and r.get("sw")}
    return frozenset(sws | {5, 10})


def _svc_state(st):
    """Ce qu'un switch réservé peut avoir changé — pour le REMETTRE après la sonde."""
    return (bool((st.get("click") or {}).get("on")), bool((st.get("tuner") or {}).get("on")),
            bool(st.get("whammy_on")), json.dumps(st.get("stomps") or {}, sort_keys=True))


def scenes(st0):
    """CC 20-24 = les cinq scènes. Un slot REVENDIQUÉ par un bloc spécial n'est plus une scène :
    c'est la doctrine foot_scene_claim, et c'est le premier endroit où le contrat a pu dériver."""
    print("Scènes (CC 20-24)")
    claims = st0.get("scene_claims") or {}
    for cc, want in SCENE_CC.items():
        sw = cc - 19
        claimed = claims.get(str(sw)) or claims.get(sw)
        # ⚠ UNE SONDE NE LANCE PAS UNE PRISE (2026-09-21). Ce test envoyait 127 sur un switch
        # réservé au Rec : il DÉMARRAIT un enregistrement (et le backing avec) et repartait en le
        # laissant tourner — trouvé le jour où SW4/SW5 sont passés en `effect`, où 127 veut dire
        # « on » et plus « bascule ». Un switch qui enregistre ou joue n'est pas injecté ; les
        # autres réservations (click, tuner…) le sont, puis REMISES dans l'état d'avant.
        ctypes = {c.get("type") for c in (claimed or [])}
        if ctypes & {"rec", "backing-track"}:
            skip(f"SW{sw} revendiqué par « {' + '.join(sorted(ctypes))} »",
                 "non injecté : l'appui lancerait une prise / un backing — à vérifier au pied")
            continue
        before = _svc_state(state()) if claimed else None
        st = inject(type="cc", cc=cc, val=127)
        if claimed:
            inject(type="cc", cc=cc, val=0)                  # switch `effect` : l'état « off »
            time.sleep(0.8)
            if _svc_state(state()) != before:                # switch `preset` (bascule) : on rebascule
                inject(type="cc", cc=cc, val=127)
                time.sleep(0.8)
        # ⚠ SW5 = « tout jouer / tout arrêter » du looper, À LA PLACE DE LA SCÈNE E (carte validée
        # 2026-08-08, docs/looper.md). Le CC est donc ignoré PAR CONTRAT sur ce slot, exactement
        # comme sur la rangée haute — mais ce test-ci ne le savait pas et sortait un ROUGE sur un
        # rack parfaitement conforme. Une sonde qui crie au loup se fait ignorer le jour où elle
        # a raison ; c'est la deuxième fois pour celle-là.
        if sw in looper_switches(st0):
            ok(f"SW{sw} revendiqué par le looper — pas une scène",
               st.get("scene_id") != want, f"scène restée {st.get('scene_id')}")
        elif claimed:
            ok(f"SW{sw} revendiqué par « {claimed[0]['type']} » — pas une scène",
               st.get("scene_id") != want, f"scène restée {st.get('scene_id')}")
        else:
            ok(f"CC{cc} → scène {want}", st.get("scene_id") == want, f"lu : {st.get('scene_id')}")


def stomps(st0):
    """CC 30-34 = POSITIONS de switch 6-10. Ce que ces positions déclenchent dépend du preset
    (assignation libre, docs stomp-free-assignment) : on vérifie la BASCULE, pas un effet nommé."""
    print("Stomps (CC 30-34, positions 6-10)")
    # ⚠ CC30-34 n'est PAS « bascule », c'est « pose l'état » : c'est LA PUCE qui alterne 127/0.
    # Envoyer 127 sur un stomp déjà allumé est donc un no-op légitime — mon premier jet le
    # comptait comme un échec, alors qu'une scène venait simplement de l'allumer avant le test.
    # On envoie donc la valeur CONTRAIRE de l'état lu, et on repose.
    get = lambda st, sw: (st.get("stomps") or {}).get(str(sw), (st.get("stomps") or {}).get(sw))
    # Un switch REVENDIQUÉ par un service (sample, batterie, standard, arrangement) est piloté par
    # les FRONTS de Note : le rack IGNORE délibérément son CC (anti double-déclenchement, app.py
    # `_do_stomp`). Et `state.stomps` n'y veut rien dire — il répond « le bloc est activé dans la
    # scène », toujours vrai pour un service scene-invariant. Exiger que le CC fasse bouger cette
    # valeur, c'était tester un contrat qui n'existe pas : SW10 portant un Standard sortait ROUGE
    # alors que le rack se comportait exactement comme prévu (constaté 2026-08-04).
    # ⚠ LE LOOPER PREND TOUTE LA RANGÉE, et son CC est ignoré PAR CONTRAT (les fronts pilotent
    # le transport). Ce test l'ignorait : sur un preset looper il sortait deux ROUGES pour un
    # rack qui se comportait exactement comme prévu (constaté 2026-08-08 sur « ZZ Conflict »).
    # Une sonde qui crie au loup se fait ignorer le jour où elle a raison.
    def claimed(sw):
        if sw in looper_switches(st0):
            return "looper"
        for k in ("sample_switches", "drum_switches", "standard_switches"):
            if str(sw) in (st0.get(k) or {}) or sw in (st0.get(k) or {}):
                return k.split("_")[0]
        return "arrangement" if st0.get("arr_switch") == sw else None
    for cc, sw in STOMP_CC.items():
        why = claimed(sw)
        if why:
            ok(f"CC{cc} → position {sw} revendiquée par « {why} » — pilotée par les Notes",
               True, "le CC est ignoré par contrat")
            continue
        before = get(state(), sw)
        if before is None:
            ok(f"CC{cc} → position {sw}", True, "aucun bloc sur ce switch dans ce preset (normal)")
            continue
        st = inject(type="cc", cc=cc, val=0 if before else 127)
        after = get(st, sw)
        ok(f"CC{cc} → position {sw} suit la valeur", after != before, f"{before} → {after}")
        inject(type="cc", cc=cc, val=127 if before else 0)  # on repose


def scene_row_claims(st0):
    """Un bloc PILOTÉ PAR LES FRONTS qui revendique un switch de la RANGÉE DES SCÈNES (1-5).

    Le trou du 2026-08-07 : les deux chemins se renvoyaient la balle. Le CC cédait la main aux
    fronts (« _do_stomp : les fronts s'en occupent ») et les fronts s'arrêtaient au switch 6 —
    l'appui ne faisait RIEN, sans une ligne de log. Seuls le tuner et le Rec marchaient, parce
    qu'ils passent par le CC. Ce contrôle ferme les deux moitiés à la fois.
    """
    print("Rangée des scènes revendiquée (fronts)")
    claims = st0.get("scene_claims") or {}
    front_driven = {"standard": "standard_switches", "sample": "sample_switches",
                    "drums": "drum_switches"}
    tested = 0
    for sw, cs in claims.items():
        for c in (cs or []):
            reg = front_driven.get(c.get("type"))
            if not reg or not (1 <= int(sw) <= 5):
                continue
            tested += 1
            armed = str(sw) in (st0.get(reg) or {})
            ok(f"switch {sw} revendiqué par « {c.get('type')} » : le registre du pied est armé",
               armed, "" if armed else
               f"{reg} vide -> la tuile s'affiche et l'appui ne fait rien "
               f"(bug d'adoption au boot, 2026-08-07)")
            n = int(sw) - 1
            before = json.dumps(state().get(c.get("type")) or {}, sort_keys=True)
            call("/api/foot/inject", {"type": "note", "n": n, "on": True})
            call("/api/foot/inject", {"type": "cc", "cc": 20 + n, "val": 127})
            call("/api/foot/inject", {"type": "note", "n": n, "on": False})
            time.sleep(2.0)
            after = json.dumps(state().get(c.get("type")) or {}, sort_keys=True)
            fired = before != after
            ok(f"switch {sw} : l'appui DÉCLENCHE le service (et ne fait pas scène)",
               fired, "" if fired else
               "aucun des deux chemins n'a agi — c'est le trou du 2026-08-07 "
               "(le CC cède aux fronts, les fronts s'arrêtaient à 6)")
            call("/api/foot/inject", {"type": "note", "n": n, "on": True})   # on repose
            call("/api/foot/inject", {"type": "note", "n": n, "on": False})
            time.sleep(1.5)
            # LA PARITÉ PIED <-> ÉCRAN : la tuile de /live tape /api/stomp, un chemin où il n'y a
            # AUCUN front derrière le clic. Il a été mort exactement aussi longtemps que le pied
            # (2026-08-07) — et un contrôle qui ne teste que l'injection ne l'aurait jamais vu.
            was = json.dumps(state().get(c.get("type")) or {}, sort_keys=True)
            call("/api/stomp", {"switch": int(sw)})
            time.sleep(2.0)
            now = json.dumps(state().get(c.get("type")) or {}, sort_keys=True)
            moved = was != now
            ok(f"switch {sw} : la TUILE de /live déclenche aussi (parité pied/écran)",
               moved, "" if moved else
               "le clic écran ne fait rien — /api/stomp cède aux fronts, qui n'existent pas ici")
            call("/api/stomp", {"switch": int(sw)})                     # on repose
            time.sleep(1.5)
    if not tested:
        print("  ·    aucun bloc piloté par les fronts sur la rangée 1-5 dans ce preset")


def notes(st0):
    """Notes 0-9 = l'IDENTITÉ du switch (et la DURÉE : les gestes du looper, des samples et de
    l'arrangement vivent sur les fronts press/release, que les CC ne portent pas)."""
    print("Notes (identité + fronts)")
    # ⚠ Le canal vient du pédalier ACTIF, jamais d'une constante : le lecteur ne retient que le
    # canal du contrat, donc une ligne brute câblée en dur serait ignorée EN SILENCE dès qu'on
    # change de puce — le test paraîtrait muet et on accuserait le pédalier (piège du rollback,
    # docs/pedalboards.md). La 1.0.4 parle sur le fil 0, la UnO2 sur le fil 1.
    ok("format MIXTE accepté (release SANS velocity)",
       call("/api/foot/inject", {"type": "raw",
                                 "line": "Note off %d, note 5" % wire_channel()})[0] == 200,
       "piège n°3 du contrat")
    routed = []
    for n in range(5, 10):                                  # SW6-10 : les seuls à porter des gestes
        sw = n + 1
        for k, lbl in (("sample_switches", "sample"), ("drum_switches", "batterie"),
                       ("standard_switches", "standard")):
            if str(sw) in (st0.get(k) or {}) or sw in (st0.get(k) or {}):
                routed.append((sw, lbl))
        if st0.get("arr_switch") == sw:
            routed.append((sw, "arrangement"))
    ok("fronts press/release acceptés",
       call("/api/foot/inject", {"type": "note", "n": 5, "on": True})[0] == 200)
    call("/api/foot/inject", {"type": "note", "n": 5, "on": False})
    print(f"    switches routés vers un bloc spécial dans ce preset : "
          f"{', '.join(f'SW{s} → {l}' for s, l in routed) or 'aucun'}")


def slots(st0):
    """PC = slot de setlist (00-18). C'est le chemin le plus utilisé en concert, et celui que
    les évolutions de setlist pouvaient casser sans bruit."""
    print("Slots de setlist (PC)")
    start = st0.get("preset_id")
    # ⚠ Sans le moindre preset sur le rack, ce chemin n'a RIEN à rappeler : le tester
    # reviendrait à échouer sur une absence de contenu. Constaté au reset du 2026-09-07,
    # où « PC 0 → un preset est rappelé » criait ✗ sur un rack neuf — alors que la ligne
    # suivante, elle, prévoyait déjà le cas (`or moved is None`).
    try:
        with urllib.request.urlopen(BRIDGE + "/api/presets", timeout=5) as r:
            n_presets = len(json.loads(r.read() or b"[]") or [])
    except Exception as e:
        print(f"  (liste des presets illisible : {e} — on teste quand même)")
        n_presets = -1
    if n_presets == 0:
        skip("slots de setlist", "aucun preset sur ce rack — rien à rappeler (rack neuf)")
        return start
    st = inject(type="pc", n=0)
    moved = st.get("preset_id")
    ok("PC 0 → un preset est rappelé", bool(moved), f"« {moved} »")
    st = inject(type="pc", n=1)
    ok("PC 1 → un AUTRE slot", st.get("preset_id") != moved or moved is None,
       f"« {st.get('preset_id')} »")
    return start


def expr(st0):
    """EXP A = CC7 (volume), EXP B = CC11 (cible contextuelle). Le RÉGLAGE se vérifie ici ;
    la course réelle de la pédale, non — c'est un pied."""
    print("Pédales d'expression")
    st = inject(type="cc", cc=7, val=64)
    ok("CC7 → EXP 1 (volume)", st.get("exp1") == 64, f"lu : {st.get('exp1')}")
    st = inject(type="cc", cc=11, val=100)
    ok("CC11 → EXP 2", st.get("exp2") == 100,
       f"lu : {st.get('exp2')} · cible « {st.get('exp2_target')} »")
    inject(type="cc", cc=7, val=st0.get("exp1") or 0)
    inject(type="cc", cc=11, val=st0.get("exp2") or 0)


# ── MODE LIVE : le seul qui prouve que LA PUCE émet ────────────────────────────────────────
# Le reste du script vérifie ce que le RACK comprend. Ici on vérifie ce que le PÉDALIER DIT —
# c'est-à-dire la programmation de la puce UnO, que rien d'autre ne peut attester.
# ⚠ Le FCB n'apparaît PAS comme un client USB : c'est un pédalier DIN, il entre par la prise
# MIDI de la carte son. Chercher un client « FCB » dans `aconnect -l` ne trouve donc rien et
# ne prouve rien — c'est le port de la CARTE qu'il faut écouter (même choix que foot.py).
_SEEN = {"pc": set(), "scene": set(), "stomp": set(), "note": set(), "exp1": [], "exp2": [],
         "chan": set()}
# ⚠ LES FRONTS PAR SWITCH — l'instrument qui manquait. Le contrat exige `gestures` sur certains
# switches (« ce switch doit porter appui ET relâchement »), mais rien ne confrontait cette
# exigence au réel. Or un switch qui n'émet pas de relâchement ne rend pas les gestes
# inopérants : il les rend IMPRÉVISIBLES — une minuterie d'appui long armée au press n'est
# jamais annulée, donc elle FINIT PAR PARTIR. C'est ce qu'on vient chercher ici.
# {note du fil: {"on": n, "off": n}}
_EDGES = {}
# ⚠ LE CANAL PAR FAMILLE, pas seulement l'ensemble des canaux entendus. Mesuré le 2026-08-07 :
# la UnO2 émet sur DEUX canaux à la fois. Savoir « on entend 1 et 2 » ne dit pas quoi corriger ;
# savoir « les scènes sont sur 2 et les pédales EXP sur 1 » le dit. {famille: {canal}}
_CHAN = {}
# ⚠ LE CANAL EST CAPTURÉ, PAS IGNORÉ (2026-08-07). Il ne l'était pas : une puce qui émet sur le
# MAUVAIS canal cochait TOUTES les cases de ce mode — « la puce ÉMET », « CC 20-24 = scènes » —
# pendant que foot.py jetait chaque message au filtrage de canal. Vert partout, pédale morte.
# C'est le travers que la roadmap nomme : une vérification qui ne regarde qu'un côté conclut
# trop vite. On compare donc ce qu'on ENTEND au canal DÉCLARÉ par le descripteur actif.
_RE = {
    "pc": re.compile(r"Program change\s+(\d+), program (\d+)"),
    "cc": re.compile(r"Control change\s+(\d+), controller (\d+), value (\d+)"),
    # ⚠ LA VÉLOCITÉ FAIT PARTIE DU FRONT. Le rack tranche ainsi (bridge/foot.py:315) :
    #     appui = « Note on » AVEC une vélocité > 0 ; tout le reste est un relâchement.
    # Un « Note on velocity 0 » est un relâchement dans l'idiome MIDI courant, et la 1.0.4 émet
    # même ses Notes SANS champ velocity. Ne lire que le mot on|off, c'était compter des
    # relâchements comme des appuis — et conclure « ce switch ne relâche jamais » sur une puce
    # parfaitement saine. La sonde doit trancher EXACTEMENT comme le moteur qu'elle vérifie.
    "note": re.compile(r"Note (on|off)\s+(\d+), note (\d+)(?:, velocity (\d+))?"),
}


def _note_base():
    """La note de la 1re pédale, selon le descripteur ACTIF (0 chez la UnO2)."""
    d = call("/api/pedalboard", method="GET")[1]
    return ((d.get("wire") or {}).get("note_base")
            or (d.get("device") or {}).get("quirks", {}).get("note_base") or 0)


def _gesture_switches():
    """Les switches dont l'INTENTION exige les deux fronts (contract.json, pas la puce)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "config", "pedalboard", "contract.json"), encoding="utf-8") as fh:
            c = json.load(fh)
        return {st["switch"] for st in (c.get("stomps") or []) if st.get("gestures")}
    except (OSError, ValueError, KeyError):
        return set()


def _known_channels():
    """{canal(1-16): à qui il est} — les appareils que GoleM PILOTE, lus de leurs descripteurs.

    Sert à NOMMER le trafic étranger entendu sur le port d'entrée plutôt qu'à s'en alarmer :
    ce qu'on émet vers une pédale MIDI revient par le THRU. Données, jamais une constante ici.
    """
    import glob, os
    out = {}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in glob.glob(os.path.join(root, "library", "pedals", "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        ch = d.get("channel")
        if isinstance(ch, int):
            # ⚠ PLUSIEURS appareils partagent un canal (Whammy DT et MPX100 sont tous deux sur
            # le 1). N'en garder qu'un nommerait le mauvais coupable avec aplomb.
            out.setdefault(ch, []).append(d.get("name") or os.path.basename(f)[:-5])
    return {c: ", ".join(sorted(v)) for c, v in out.items()}


def _mark(family, wire_chan):
    """Retient le canal (sur le fil, 0-15) sur lequel cette famille de messages a été entendue."""
    _SEEN["chan"].add(wire_chan)
    _CHAN.setdefault(family, set()).add(wire_chan)


def _declared_channel():
    """Le canal que le DESCRIPTEUR actif annonce (1-16), ou None si on n'a pas pu le lire.

    Lu à la source — l'API du rack —, jamais recopié ici : une constante en dur dans un outil de
    vérification est exactement ce que le chantier « pédalier = descripteur » a supprimé."""
    try:
        import json as _j, urllib.request as _u
        d = _j.load(_u.urlopen(BRIDGE + "/api/pedalboard", timeout=3))
        return (d.get("device") or {}).get("channel")
    except Exception as e:
        # ⚠ VISIBLE, PAS AVALÉ. Un outil de vérification qui échoue en silence est le pire des
        # cas : il rend un verdict rassurant sur rien. Vécu ici même au premier jet — un
        # NameError (BASE au lieu de BRIDGE) était capté par un `except` nu, et le canal
        # déclaré ressortait « inconnu » sans que rien ne l'explique.
        print(f"    (canal déclaré illisible : {e})")
        return None


def _fcb_port():
    """Le port ALSA du PÉDALIER — celui que le rack écoute, pas le premier venu.

    ⚠ Le premier jet prenait le premier client non-système. Les numéros ALSA ne sont PAS
    stables : entre deux mesures du 2026-08-07, l'AKAI et la Volt ont permuté (20:0/32:0 ->
    16:0/32:0), et la sonde a écouté le CLAVIER. Elle a alors rendu « la puce n'émet rien »
    avec aplomb, sur un pédalier parfaitement sain — le pire mensonge possible pour un outil
    de diagnostic, et exactement celui qu'on passe la journée à traquer.
    On résout donc comme le rack : par le nom rawmidi de la CARTE ACTIVE (bridge.midi_out),
    source unique. Repli sur l'ancien comportement seulement si le bridge est injoignable, et
    on le DIT.
    """
    if os.environ.get("GOLEM_FCB_PORT"):
        return os.environ["GOLEM_FCB_PORT"]
    out = subprocess.run(["aseqdump", "-l"], capture_output=True, text=True).stdout
    want = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from bridge import midi_out as _mo
        want = (_mo._active_card_midi()[1] or "").lower() or None
    except Exception as e:
        print(f"    (carte active illisible : {e} — repli sur le 1er port MIDI, peu fiable)")
    for line in out.splitlines():
        m = re.match(r"\s*(\d+):(\d+)\s+(.+?)\s\s+", line)
        if not m:
            continue
        cl, prt, nm = m.group(1), m.group(2), m.group(3).strip()
        if nm in ("System", "Midi Through") or nm.startswith(("golem", "aseqdump", "PipeWire")):
            continue
        if want:
            if want in nm.lower():
                return f"{cl}:{prt}"
        else:
            return f"{cl}:{prt}"
    return None


def live(seconds):
    port = _fcb_port()
    if not port:
        print("  ✗ aucun port MIDI d'entrée trouvé."); return 1
    print(f"Écoute de {port} pendant {seconds} s. FAIS ÇA, dans l'ordre — sans te presser :\n"
          "   1. SW1, puis SW2, puis SW5      (scènes)\n"
          "   2. SW6, SW7                      (stomps : appuie DEUX fois sur chacun)\n"
          "   3. UP, puis DOWN                 (navigation de banks)\n"
          "   4. balaie EXP A de 0 au max, puis EXP B\n"
          "   5. appui LONG sur SW1, puis 0 puis 3   (slot 03)\n")
    proc = subprocess.Popen(["stdbuf", "-oL", "aseqdump", "-p", port],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    # ⚠ LECTURE NON BLOQUANTE. Premier jet : `readline()` en boucle — un pédalier SILENCIEUX
    # (débranché, puce non programmée) bloquait le script POUR TOUJOURS, sans un mot. C'est
    # précisément le cas qu'on cherche à diagnostiquer : il devait donc être celui qui répond
    # le plus clairement, pas celui qui fige.
    import select
    t0, lines = time.time(), 0
    try:
        while True:
            left = seconds - (time.time() - t0)
            if left <= 0:
                break
            if not select.select([proc.stdout], [], [], min(left, 0.5))[0]:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            if "Waiting for data" in line or "Cannot connect" in line or "Source" in line:
                continue          # bannière d'aseqdump — la compter, c'était dire « la puce
                                  # émet » à un pédalier muet : le pire des faux positifs ici
            lines += 1
            m = _RE["pc"].search(line)
            if m:
                _mark("PC (slot)", int(m.group(1)))
                _SEEN["pc"].add(int(m.group(2))); continue
            m = _RE["cc"].search(line)
            if m:
                _ch = int(m.group(1))
                cc, val = int(m.group(2)), int(m.group(3))
                if cc in SCENE_CC:
                    _mark("CC scène", _ch); _SEEN["scene"].add(cc)
                elif cc in STOMP_CC:
                    _mark("CC stomp", _ch); _SEEN["stomp"].add((cc, val))
                elif cc == 7:
                    _mark("EXP A (CC7)", _ch); _SEEN["exp1"].append(val)
                elif cc == 11:
                    _mark("EXP B (CC11)", _ch); _SEEN["exp2"].append(val)
                else:
                    _mark(f"CC{cc} (hors contrat)", _ch)
                continue
            m = _RE["note"].search(line)
            if m:
                _mark("Note (identité)", int(m.group(2)))
                _vel = m.group(4)
                _is_on = m.group(1) == "on" and _vel is not None and int(_vel) > 0
                _EDGES.setdefault(int(m.group(3)), {"on": 0, "off": 0})[
                    "on" if _is_on else "off"] += 1
                _SEEN["note"].add((int(m.group(3)), "on" if _is_on else "off",
                                   _vel is not None))
    finally:
        proc.terminate()

    print(f"\n  {lines} messages reçus\n")
    ok("la puce ÉMET quelque chose", lines > 0, "sinon : câble DIN, MIDI OUT du FCB, ou puce non programmée")
    # LE CANAL — le discriminant que ce mode ignorait. Sur le fil il compte depuis 0, le contrat
    # depuis 1 : on compare dans le repère du CONTRAT pour que le message soit lisible.
    heard = sorted(c + 1 for c in _SEEN["chan"])
    want = _declared_channel()
    if lines > 0 and want is not None:
        # ⚠ « TOUT DOIT ÊTRE SUR LE CANAL DÉCLARÉ » EST FAUX, et ce contrôle a crié au loup au
        # premier jet (2026-08-07). Le port d'entrée porte AUSSI notre propre sortie qui nous
        # revient — l'écho THRU que foot.py filtre par conception. Or l'écho est INDISCERNABLE
        # par type de message : on émet des PC et des CC vers la Whammy, exactement comme le
        # pédalier. Seul le CANAL les sépare.
        # La bonne question n'est donc pas « entend-on autre chose ? » mais « CHAQUE famille du
        # contrat est-elle bien présente SUR le canal déclaré ? ». Le reste est du trafic
        # étranger : on le NOMME quand on sait à qui il est, on n'en fait pas une panne.
        on_want = {f for f, cs in _CHAN.items() if (want - 1) in cs}
        off_only = {f: sorted(c + 1 for c in cs) for f, cs in _CHAN.items()
                    if (want - 1) not in cs}
        ok("les messages du pédalier arrivent sur le canal déclaré",
           bool(on_want) and not off_only,
           f"canal {want} · familles entendues : {', '.join(sorted(on_want)) or 'aucune'}"
           + ("" if not off_only else
              " — MAIS " + ", ".join(f"{f} seulement sur {c}" for f, c in sorted(off_only.items()))
              + " : le rack les JETTE en silence"))
        foreign = sorted(c for c in heard if c != want)
        if foreign:
            named = _known_channels()
            # On ne cherche PAS à nommer l'appareil : huit descripteurs déclarent le canal 1, et
            # rien dans le message ne dit lequel a répondu. Le fait actionnable est ailleurs —
            # « c'est un canal sur lequel GoleM ÉMET », donc un écho attendu.
            who = ", ".join(
                f"canal {c} — " + ("un appareil que GoleM pilote (écho attendu)"
                                   if c in named else "ORIGINE INCONNUE, à regarder")
                for c in foreign)
            print(f"    · trafic étranger sur le port d'entrée : {who}")
            print("      (attendu : le MIDI qu'on ÉMET revient par le THRU. foot.py le filtre "
                  "au canal — c'est le piège n°1 du contrat, et il est tenu.)")
    ok("PC = slot de setlist", bool(_SEEN["pc"]), "slots vus : " + str(sorted(_SEEN["pc"])))
    ok("CC 20-24 = scènes", bool(_SEEN["scene"]),
       "vus : " + ", ".join(f"CC{c}→{SCENE_CC[c]}" for c in sorted(_SEEN["scene"])))
    vals = {v for _, v in _SEEN["stomp"]}
    ok("CC 30-34 = stomps, en BASCULE 127/0", {0, 127} <= vals,
       "valeurs vues : " + str(sorted(vals)) + (" — la puce n'alterne pas !" if vals and {0,127} > vals else ""))
    ok("Notes 0-9 = identité du switch", bool(_SEEN["note"]),
       "notes vues : " + str(sorted({n for n, _, _ in _SEEN["note"]})))
    # LE TABLEAU DES FRONTS : ce qu'un switch peut PORTER, mesuré, et non ce qu'on espère.
    if _EDGES:
        base, want = _note_base(), _gesture_switches()
        print("\n  fronts par switch (ce qui décide des gestes possibles) :")
        for n in sorted(_EDGES):
            sw, e = n - base + 1, _EDGES[n]
            both = e["off"] > 0
            need = sw in want
            verdict = ("les deux fronts" if both else "APPUIS SEULS — aucune durée mesurable")
            flag = ""
            if need and not both:
                flag = "   ⚠ le contrat exige `gestures` sur ce switch"
            elif both and not need:
                flag = "   (bonus : le contrat ne demande pas de gestes ici)"
            print(f"      SW{sw:<3} {e['on']:>2} appui(s), {e['off']:>2} relâchement(s) — {verdict}{flag}")
        muets = [n - base + 1 for n in _EDGES if _EDGES[n]["off"] == 0]
        if muets:
            print(f"      -> sur SW{muets}, tout geste À DURÉE est à proscrire : la minuterie "
                  "armée à l'appui n'est jamais annulée, donc elle part TOUJOURS.")
    rel_no_vel = [n for n, d, hasvel in _SEEN["note"] if d == "off" and not hasvel]
    if rel_no_vel:
        print(f"    · relâchements SANS velocity (piège n°3, géré) : notes {sorted(set(rel_no_vel))}")
    for k, lbl, cc in (("exp1", "EXP A", 7), ("exp2", "EXP B", 11)):
        v = _SEEN[k]
        ok(f"{lbl} (CC{cc}) balaie sans trou", len(v) > 8 and min(v) < 16 and max(v) > 111,
           f"{len(v)} valeurs, de {min(v) if v else '—'} à {max(v) if v else '—'}")
    print("\n  ⚠ Ce que même ce mode ne voit pas : les LED. Regarde-les pendant que tu appuies.\n"
          "    (MIDI MERGE, lui, se tranche sans le pied : on ÉMET vers le Whammy en écoutant\n"
          "     l'entrée — si ça revient, le merge est ON. Fait le 2026-08-02 : OFF.)")
    return 1 if FAILED else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", help="rappeler ce preset avant de tester")
    ap.add_argument("--live", action="store_true", help="écoute le VRAI pédalier et te guide")
    ap.add_argument("--seconds", type=int, default=60, help="durée de la fenêtre d'écoute")
    a = ap.parse_args()
    if a.live:
        return live(a.seconds)
    try:
        st0 = state()
    except Exception:
        sys.exit("Le bridge ne répond pas — démarre GoleM d'abord.")
    if not st0.get("reaper_connected"):
        print("⚠ Reaper n'est pas connecté : les scènes et les slots ne seront pas concluants.\n")
    if a.preset:
        call("/api/recall", {"preset": a.preset}); time.sleep(2.5); st0 = state()

    print(f"preset « {st0.get('preset_id')} » · scène {st0.get('scene_id')}\n")
    # ⚠ ORDRE : `slots` CHANGE le preset. Tout ce qui dépend du preset courant passe avant,
    # sinon on mesure l'EXP 2 d'un autre morceau (vécu au premier jet : cible « — »).
    scenes(st0); print()
    stomps(st0); print()
    scene_row_claims(st0); print()
    notes(st0); print()
    expr(st0); print()
    start = slots(st0); print()

    # on repose l'état d'origine : ce script tire sur le VRAI rig
    if start:
        call("/api/recall", {"preset": start}); time.sleep(2.0)
    if st0.get("scene_id"):
        cc = next((c for c, s in SCENE_CC.items() if s == st0["scene_id"]), None)
        if cc:
            call("/api/foot/inject", {"type": "cc", "cc": cc, "val": 127})
    print(f"état reposé : preset « {state().get('preset_id')} » · scène {state().get('scene_id')}\n")

    if FAILED:
        print("  ✗ À REGARDER : " + " · ".join(FAILED))
    else:
        print("  ✓ L'étage RACK comprend le pied comme le contrat le dit.")
    print("""
  Ce que ce script NE PEUT PAS voir — au pied, pédalier branché :
    1. la PUCE émet-elle bien PC=slot, CC20-24, CC30-34, Note 0-9 ?  (aseqdump -p <FCB>)
    2. les LED suivent-elles l'état (SW1-5 = preset courant, SW6-10 = on/off du stomp) ?
    3. les deux pédales d'expression balaient-elles 0→127 sans saut ?
    4. MIDI MERGE est-il bien OFF ? (piège n°1 : sinon le Whammy renvoie des PC fantômes)
    5. appui long SW1 + deux chiffres → slots 10-18, ET le pédalier SUIT (son afficheur change).
    6. le pédalier SUIT le rack : demander un slot doit l'y amener, sans décalage.
         curl -sX POST localhost:8770/api/pedalboard/goto -d '{"slot":3}'
       attendu : afficheur 04, et un appui de scène renvoie PC 3.
       (MESURÉ le 2026-08-06 : la puce numérote ses banks DEPUIS 1, comme son afficheur,
        alors que le rack compte ses slots depuis 0 — d'où `index_base: 1` dans le
        descripteur. Envoyer 3 l'amenait sur l'afficheur 03, c'est-à-dire le SLOT 2.
        Un décalage d'une bank ne se voit qu'en jouant : c'est le contrôle qui l'attrape.)""")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
