#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce plugin FIGE-T-IL LE MOTEUR AUDIO quand on l'allume ? — mesuré, plugin par plugin.

    ./tools/check-block-stall.py                         # les delays + la famille guitarix du catalogue
    ./tools/check-block-stall.py GxEchoCat ReaDelay      # ceux-là seulement
    ./tools/check-block-stall.py --track "Sandbox #Input 2" GxEchoCat    # sur une autre piste
    ./tools/check-block-stall.py --waits 0.5,2,5,10 GxEchoCat            # selon le temps passé éteint
    ./tools/check-block-stall.py --catalog               # TOUS les plugins du catalogue (hors quarantaine)
    ./tools/check-block-stall.py --rig                   # les blocs du preset CHARGÉ, avec leurs vrais fichiers

POURQUOI : le « blanc de A vers B » de Paper Kite (2026-09-20/21) était GxEchoCat, le delay-echo de
la lane voix : son activation arrête le traitement de TOUTES les pistes ~520 ms. Un plugin « installé »
n'est pas un plugin validé (CLAUDE.md, GxDetune) : avant d'offrir un bloc, on le mesure.

COMMENT : un détecteur golem_gapmeter compte les échantillons qu'il traite ; on compare son horloge à
celle de Reaper autour de chaque geste : l'écart EST le temps pendant lequel le moteur n'a rien traité.
Le plugin est posé en queue d'une piste VIVANTE du rig (commande `fxadd`), bypassé, puis allumé/éteint
par la commande `stomp` — le chemin exact d'un bloc. Tout est retiré à la fin. ⚠ Un ton de test sonne.

--rig : un plugin posé à VIDE ne dit rien d'une capture NAM ou d'un convolveur d'IR, dont le coût
éventuel est dans leur FICHIER. Ce mode bascule les blocs du preset chargé, fichiers compris, et
remet chacun dans l'état où il l'a trouvé (on mesure toujours l'ALLUMAGE).
"""
import argparse, json, os, statistics, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge.commands import write_command            # noqa: E402  (même slot que le bridge, avec son attente d'accusé)
from bridge import config as C                         # noqa: E402

BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
DEFAULT = ["GxEchoCat", "ReaDelay", "Calf Vintage Delay", "Gxshimmizita", "GxTubeVibrato", "Gxoc_2",
           "Gxgcb_95", "GxWahwah", "GxAutoWah", "GxGraphicEQ"]


def post(path, body=None):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body or {}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=30))


def snap():
    # Windows : le JSFX/Lua remplace le fichier (supprimer puis écrire) — une lecture qui tombe dans ce
    # creux voit « fichier absent » ou un JSON coupé (vécu 2026-10-03, le banc mourait au 2e plugin).
    # Le couple (t, clk) vient toujours d'UNE même lecture : relire un peu plus tard ne fausse rien.
    for attempt in range(30):
        try:
            d = json.load(open(C.runtime_file("golem-gaps.json")))
            return d["t"], d["slots"][0]["clk"]
        except (OSError, ValueError, KeyError, IndexError):
            if attempt == 29:
                raise
            time.sleep(0.01)


def catalog_plugins():
    """Les plugins du catalogue, hors quarantaine, dédoublonnés par nom — avec les noms de repli
    que golem_rig essaie (ADD_ALIAS), lus dans son source pour ne pas en tenir une 2e liste."""
    import re
    fx = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json")))["effects"]
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf8").read()
    alias = {}
    for m in re.finditer(r'^\s*\[?"?([\w-]+)"?\]?\s*=\s*\{([^}]*)\}', lua[lua.index("local ADD_ALIAS"):lua.index("\n}", lua.index("local ADD_ALIAS"))], re.M):
        alias[m.group(1)] = re.findall(r'"([^"]+)"', m.group(2))
    out, seen = [], set()
    for b in fx:
        if b.get("engine") != "plugin" or not b.get("plugin") or b.get("quarantine"):
            continue
        if b["plugin"] in seen:
            continue
        seen.add(b["plugin"])
        out.append((b["plugin"], b["type"], [a for a in alias.get(b["type"], []) if a != b["plugin"]]))
    return out


def added(seq_before):
    for _ in range(40):
        time.sleep(0.1)
        try:
            r = json.load(open(C.runtime_file("golem-fxadd.json")))
            if r.get("seq") != seq_before:
                return r
        except (OSError, ValueError):
            pass
    return {"ok": False, "name": ""}


def stall(act, settle):
    time.sleep(0.3); t0, c0 = snap(); act(); time.sleep(settle); t1, c1 = snap()
    return ((t1 - t0) - (c1 - c0)) * 1000


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plugins", nargs="*", default=DEFAULT)
    ap.add_argument("--track", default="Sandbox #Input 1#merge", help="piste vivante où poser le plugin")
    ap.add_argument("--waits", default="1.5,4", help="durées passées ÉTEINT avant de rallumer (s)")
    ap.add_argument("-n", type=int, default=4, help="allumages par durée")
    ap.add_argument("--catalog", action="store_true", help="tous les plugins du catalogue (hors quarantaine)")
    ap.add_argument("--rig", action="store_true", help="les blocs du preset chargé, avec leurs fichiers")
    ap.add_argument("--engine", action="store_true",
                    help="avec --rig : basculer par le chemin du MOTEUR (fx_set_on de golem_rig) au lieu du bypass "
                         "brut de Reaper — vérifie qu'un convolveur passe par son interrupteur interne")
    a = ap.parse_args()
    waits = [float(x) for x in a.waits.split(",")]
    st = json.load(urllib.request.urlopen(BRIDGE + "/api/state"))
    if (st.get("perf") or {}).get("recording"):
        sys.exit("✗ une prise tourne")
    pid = st.get("preset_id")
    post("/api/gapmeter", {"on": True, "tone": "Sandbox #Input 1", "db": -30,
                           "tracks": ["Sandbox #Input 1"], "thrs": [-70], "hold": 900})
    time.sleep(2.0)
    print("piste : « %s » · %d allumages par durée · éteint %s s avant de rallumer\n" % (a.track, a.n, " / ".join("%g" % w for w in waits)))
    base = [abs(stall(lambda: None, 1.0)) for _ in range(3)]
    print("témoin (rien ne bouge) : %.0f ms\n" % max(base))
    verdicts = []
    stomp = lambda ids, on: write_command({"action": "stomp", "preset": pid, "ids": ids, "on": on, "_route": "rig_recall"})
    if a.rig:
        return rig_mode(a, pid, waits, verdicts, stomp)
    plist = catalog_plugins() if a.catalog else [(p, None, []) for p in a.plugins]
    try:
        for plug, btype, alts in plist:
            try:
                prev = json.load(open(C.runtime_file("golem-fxadd.json"))).get("seq")
            except (OSError, ValueError):
                prev = None
            seq = "%s-%d" % (plug, time.time() * 1000)
            write_command({"action": "fxadd", "track": a.track, "plugin": plug, "alts": alts, "tag": "zz-stall", "seq": seq})
            r = added(prev)
            if not r.get("ok"):
                # le même échec dit « piste absente » : le journal de golem_apply le distingue (2026-10-22 : quatre
                # JSFX déclarés « ne se charge pas » alors que le preset chargé n'avait pas de piste #merge)
                try:
                    tail = open(os.path.join(C.PRESETS_DIR, ".apply.log"), encoding="utf-8", errors="replace").read()[-600:]
                except OSError:
                    tail = ""
                if "piste introuvable" in tail:
                    print("✗ la piste « %s » n'existe pas dans le preset chargé — choisir une piste vivante avec --track"
                          % a.track, flush=True)
                    break
                verdicts.append((plug, None, 0, 0))
                print("%-22s ✗ NE SE CHARGE PAS (ni sous ce nom ni sous ses replis) — non mesuré" % plug, flush=True)
                continue
            time.sleep(1.5)
            row = []
            for w in waits:
                hits = []
                for _ in range(a.n):
                    time.sleep(max(0.0, w - 0.3))
                    hits.append(stall(lambda: write_command({"action": "stomp", "preset": pid, "ids": ["zz-stall"], "on": True, "_route": "rig_recall"}), 1.2))
                    off = stall(lambda: write_command({"action": "stomp", "preset": pid, "ids": ["zz-stall"], "on": False, "_route": "rig_recall"}), 0.6)
                    if off > 20:
                        hits.append(off)
                row.append((w, hits))
            write_command({"action": "fxdel", "tag": "zz-stall"})
            time.sleep(0.8)
            worst = max(h for _, hs in row for h in hs)
            bad = sum(1 for _, hs in row for h in hs if h > 20)
            tot = sum(len(hs) for _, hs in row)
            verdicts.append((plug, worst, bad, tot))
            print("%-22s %s   %s" % (plug, "⚠ FIGE LE MOTEUR" if worst > 20 else "ok              ",
                                     " · ".join("éteint %gs : %s" % (w, " ".join("%3.0f" % h for h in hs)) for w, hs in row)), flush=True)
    finally:
        write_command({"action": "fxdel", "tag": "zz-stall"})
        time.sleep(0.5)
        post("/api/gapmeter", {"on": False})
    report(verdicts)


def report(verdicts):
    print("\n── bilan ──")
    for plug, worst, bad, tot in verdicts:
        if worst is None:
            print("  %-26s NON MESURÉ (ne se charge pas)" % plug)
            continue
        print("  %-26s %s" % (plug, ("⚠ FIGE le moteur %d fois sur %d, jusqu'à %.0f ms" % (bad, tot, worst)) if bad else "aucun gel (max %.0f ms)" % worst))
    import tempfile                                    # /tmp n'existe pas sous Windows
    out = os.path.join(tempfile.gettempdir(), "golem-block-stall-%d.json" % int(time.time()))
    json.dump([{"plugin": p, "worst_ms": w, "stalls": b, "of": t} for p, w, b, t in verdicts], open(out, "w"), indent=1)
    print("sondes retirées · brut : %s" % out)


def rig_mode(a, pid, waits, verdicts, stomp):
    """Les blocs du preset chargé : on lit leur état réel (dump FX), on mesure l'ALLUMAGE, on remet."""
    fxd = os.path.join(ROOT, "presets", ".fxdump.json")
    m0 = os.path.getmtime(fxd) if os.path.exists(fxd) else 0
    post("/api/fxdump")
    for _ in range(60):
        time.sleep(0.1)
        if os.path.exists(fxd) and os.path.getmtime(fxd) > m0:
            break
    time.sleep(0.3)
    # chaque FX de chaque piste du rig, ESTAMPILLÉ OU NON : les cœurs (ampli NAM, baffle) ne portent pas
    # toujours golem:<id>, et la commande `stomp` (par id) ne les trouvait pas — la 1re version de ce
    # mode les mesurait « à 0 ms » sans les toucher. On bascule donc PAR POSITION (commande fxenable).
    blocks = []
    for t in json.load(open(fxd)):
        if not t["track"].startswith("Sandbox"):
            continue
        for f in t["fx"]:
            tag = f.get("tag") or ""
            if tag.startswith("golem:__") or tag == "golem:volume-sys" or tag.startswith("diag:"):
                continue
            label = tag[6:] if tag.startswith("golem:") else f["plugin"].split(":", 1)[-1].strip()[:26]
            blocks.append(((t["track"], f["fx"]), t["track"], label, bool(f.get("enabled"))))
    print("%d blocs vivants dans « %s »\n" % (len(blocks), pid))
    try:
        for (trk, fxi), track, plugin, was_on in blocks:
            en = ((lambda on, trk=trk, fxi=fxi: write_command({"action": "fx_onoff", "track": trk, "fx": fxi, "on": on, "_route": "rig_recall"}))
                  if a.engine else
                  (lambda on, trk=trk, fxi=fxi: write_command({"action": "fxenable", "track": trk, "fx": fxi, "on": on})))
            hits = []
            for w in waits:
                for _ in range(a.n):
                    if was_on:                                   # allumé : on l'éteint, on attend, on RALLUME
                        stall(lambda: en(False), 0.6)
                        time.sleep(max(0.0, w - 0.3))
                        hits.append(stall(lambda: en(True), 1.2))
                    else:                                        # éteint : on l'allume, puis on le remet éteint
                        time.sleep(max(0.0, w - 0.3))
                        hits.append(stall(lambda: en(True), 1.2))
                        stall(lambda: en(False), 0.6)
            worst, bad = max(hits), sum(1 for h in hits if h > 20)
            name = "%s #%d %s" % (track.replace("Sandbox #Input ", "in"), fxi, plugin)
            verdicts.append((name, worst, bad, len(hits)))
            print("%-44s %s   %s" % (name, "⚠ FIGE LE MOTEUR" if bad else "ok              ", " ".join("%3.0f" % h for h in hits)), flush=True)
    finally:
        post("/api/gapmeter", {"on": False})
        post("/api/recall", {"scene": json.load(urllib.request.urlopen(BRIDGE + "/api/state"))["scene_id"]})
    report(verdicts)


if __name__ == "__main__":
    main()
