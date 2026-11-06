#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'ÉTALON : SWS LiveConfigs contre le moteur de scènes du GoleM, mesurés par le même instrument.

    ./tools/bench-liveconfigs.py            # 15 bascules par moteur ⚠ SON CONTINU, ~2 min, REAPER REDÉMARRE À LA FIN
    ./tools/bench-liveconfigs.py -n 30

POURQUOI (docs/audit-2026-09-21-latence-scenes.md §6) : le dépôt annonçait LiveConfigs comme « the
scene engine » sans jamais s'en servir, et le mainteneur l'a utilisé avant le GoleM — « ça marchait plutôt
bien ». Avant de refaire le moteur, on mesure sur CETTE machine ce que fait l'outil qu'il connaît :
c'est le chiffre à égaler.

CE QU'ON MESURE, pour les deux : le temps entre l'ORDRE et le moment où le SON de l'autre branche
arrive en sortie de la piste de fusion. Un ton continu entre dans la lane ; deux détecteurs
golem_gapmeter écoutent la fusion, à l'échantillon près :
  · l'un a son seuil ENTRE le niveau de la branche claire et celui de la branche saturée : il date
    l'arrivée de la branche forte (fin de « silence ») et son départ (début du suivant) ;
  · l'autre a un seuil à -45 dB : il mesure le vrai TROU, s'il y en a un.
  · GoleM      : l'ordre = la suite exacte de la puce (PC + CC), par /api/foot/inject ;
  · LiveConfigs: l'ordre = un message OSC « ligne suivante » envoyé DIRECTEMENT à Reaper.

COMMENT ON MONTE UNE LIVE CONFIG SANS L'INTERFACE : LiveConfigs n'a pas d'API. On sauve le projet
courant dans un fichier jetable, on y écrit le bloc <S&M_LIVE_CONFIG> (format lu dans
SnM_LiveConfigs.cpp : deux lignes, lane-a et lane-b, « mute all but active », CC delay 0, fondu
réglable), et on rouvre ce fichier. LA SORTIE : Reaper est redémarré par le rack à la fin — le Set
d'origine n'est jamais écrit — puis le preset est rappelé.
"""
import argparse
import json
import os
import re
import socket
import statistics
import struct
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge import config as C  # noqa: E402
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
GAPS, LCB = C.runtime_file("golem-gaps.json"), C.runtime_file("golem-lcbench.json")
FXDUMP = os.path.join(ROOT, "presets", ".fxdump.json")
NULL_GUID = "{00000000-0000-0000-0000-000000000000}"


def post(path, body=None):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body or {}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=30))


def get(path):
    return json.load(urllib.request.urlopen(BRIDGE + path, timeout=10))


def gaps():
    try:
        return json.load(open(GAPS))
    except (OSError, ValueError):
        return None


def osc(addr, arg):
    def pad(b):
        return b + b"\0" * (4 - len(b) % 4)
    msg = pad(addr.encode()) + pad(b",s") + pad(arg.encode())
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(msg, ("127.0.0.1", OSC_PORT))
    s.close()


def osc_port():
    ini = open(os.path.expanduser("~/.config/REAPER/reaper.ini"), errors="replace").read()
    m = re.search(r'^csurf_\d+=OSC "[^"]*" \d+ (\d+) ', ini, re.M)
    return int(m.group(1)) if m else 8000


class Clock:
    """horloge du JSFX (échantillons) -> time.monotonic. On garde le plus petit (t - clk) vu : le
    fichier est écrit APRÈS le bloc audio, jamais avant."""
    def __init__(self):
        self.off_tc, self.off_m = None, None

    def feed(self):
        g, now = gaps(), time.monotonic()
        if not g or not g.get("slots"):
            return None
        d = g["t"] - g["slots"][0]["clk"]
        self.off_tc = d if self.off_tc is None else min(self.off_tc, d)
        m = now - g["t"]
        self.off_m = m if self.off_m is None else min(self.off_m, m)
        return g

    def mono(self, clk):
        return clk + self.off_tc + self.off_m


def wait(clock, secs):
    end, g = time.monotonic() + secs, None
    while time.monotonic() < end:
        g = clock.feed() or g
        time.sleep(0.004)
    return g


def arm(tone_track, merge):
    """Le ton entre EN TÊTE de la branche forte seulement : la fusion n'a du son QUE si cette
    branche est audible. (Distinguer deux scènes par leur niveau était trop fragile : le phaser de
    la scène A fait onduler la sortie, -17,7 contre -15,6 dB au 2e essai.) Deux détecteurs sur la
    fusion, seuils -40 dB (la branche est là / n'y est pas) et -45 dB."""
    post("/api/gapmeter", {"on": False}); time.sleep(0.5)
    post("/api/gapmeter", {"on": True, "tone": tone_track, "tone_head": True, "db": -24,
                           "tracks": [merge, merge], "thrs": [-40, -45], "min_ms": 3, "hold": 600})
    time.sleep(1.5)


def crossings(clock, g):
    """Tous les changements de niveau vus par le détecteur 0, datés en monotonic : la FIN d'un
    « silence » = la branche forte arrive (+1) ; son DÉBUT = elle s'en va (-1)."""
    s0, out = g["slots"][0], []
    for _, ms, end in s0["gaps"]:
        out.append((clock.mono(end), +1))
        out.append((clock.mono(end) - ms / 1000.0, -1))
    if s0["run"] > 3:
        out.append((clock.mono(s0["clk"]) - s0["run"] / 1000.0, -1))
    return sorted(out)


def measure(clock, n, orders, label, settle=1.0):
    """2n ordres alternés. Pour CHAQUE ordre : le premier changement de niveau qui le suit — sans
    rien supposer du sens (la 1re version supposait, et attribuait l'arrivée du son au mauvais
    ordre : 950 ms = mon attente de 900 ms + la vraie latence)."""
    up, down, holes, miss = [], [], [], 0
    orders[1](); wait(clock, settle + 0.3)
    for i in range(2 * n):
        g0 = clock.feed() or {}
        h0 = g0["slots"][1]["n"] if g0.get("slots") else 0
        t = time.monotonic(); orders[i % 2]()
        g = wait(clock, settle)
        c = next(((tc, d) for tc, d in crossings(clock, g) if t - 0.003 <= tc <= t + settle), None)
        holes += [x[1] for x in g["slots"][1]["gaps"] if x[0] >= h0]
        if c is None:
            miss += 1
            print("  %s %2d  AUCUN changement de niveau en %.1f s (niveau %.1f dB)" % (label, i + 1, settle, g["slots"][0]["env"]), flush=True)
            continue
        (up if c[1] > 0 else down).append((c[0] - t) * 1000)
        print("  %s %2d  %s +%4.0f ms   (niveau %.1f dB)" % (label, i + 1, "forte ARRIVE" if c[1] > 0 else "forte S'EN VA", (c[0] - t) * 1000, g["slots"][0]["env"]), flush=True)
    return up, down, holes, miss


def summary(name, up, down, holes, miss):
    def f(v):
        return ("médiane %3.0f · min %3.0f · max %3.0f ms (%d)" % (statistics.median(v), min(v), max(v), len(v))) if v else "aucune mesure"
    print("%-12s la branche forte arrive  : %s" % (name, f(up)))
    print("%-12s la branche forte s'en va : %s" % ("", f(down)))
    print("%-12s ordres sans effet        : %d" % ("", miss))
    print("%-12s trous < -45 dB           : %s" % ("", ("%d, médiane %.0f ms, max %.0f ms" % (len(holes), statistics.median(holes), max(holes))) if holes else "aucun"))


def main():
    global OSC_PORT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-n", type=int, default=15)
    ap.add_argument("--fade", type=int, default=10, help="fondu LiveConfigs en ms (0-100, défaut 10)")
    ap.add_argument("--lane", type=int, default=1)
    a = ap.parse_args()
    OSC_PORT = osc_port()

    st = get("/api/state")
    if (st.get("perf") or {}).get("recording") or (st.get("backing") or {}).get("playing"):
        sys.exit("✗ une prise ou un backing tourne : pas de banc d'essai maintenant")
    pid = st.get("preset_id")
    m0 = os.path.getmtime(FXDUMP) if os.path.exists(FXDUMP) else 0
    post("/api/fxdump")
    for _ in range(60):
        time.sleep(0.1)
        if os.path.exists(FXDUMP) and os.path.getmtime(FXDUMP) > m0:
            break
    time.sleep(0.2)
    names = [t["track"] for t in json.load(open(FXDUMP))]
    head = "Sandbox #Input %d" % a.lane
    merge, branches = head + "#merge", sorted(n for n in names if n.startswith(head + "/"))
    if merge not in names or len(branches) < 2:
        sys.exit("✗ il faut une lane à deux branches (pistes : %s)" % names)
    print("preset « %s » · branches : %s · OSC Reaper : %d" % (pid, " / ".join(b.split("/")[-1] for b in branches), OSC_PORT))

    def inject_scene(letter):
        n = "ABCDE".index(letter)
        post("/api/foot/inject", {"type": "pc", "n": 0})
        post("/api/foot/inject", {"type": "cc", "cc": 20 + n, "val": 127})

    results = {}
    try:
        # ── 1. LE MOTEUR DU GOLEM ────────────────────────────────────────────────────────────
        print("\n── moteur GoleM (scène A <-> B, suite de la puce) ──")
        clock = Clock()
        arm(branches[1], merge)
        clock = Clock()
        inject_scene("A"); la = wait(clock, 1.5)["slots"][0]["env"]
        inject_scene("B"); lb = wait(clock, 1.5)["slots"][0]["env"]
        print("niveau de la fusion : scène A %.1f dB · scène B %.1f dB (ton dans %s seulement)" % (la, lb, branches[1].split("/")[-1]))
        if lb - la < 15:
            sys.exit("✗ la branche forte ne se distingue pas du silence de l'autre : mesure impossible")
        loud, soft = "B", "A"
        clock = Clock(); wait(clock, 1.0)
        results["GoleM"] = measure(clock, a.n, [lambda: inject_scene(loud), lambda: inject_scene(soft)], "GoleM")
        post("/api/gapmeter", {"on": False}); time.sleep(0.8)

        # ── 2. SWS LIVECONFIGS ───────────────────────────────────────────────────────────────
        print("\n── SWS LiveConfigs (ligne 0 = %s, ligne 1 = %s, fondu %d ms, CC delay 0) ──" % (
            branches[0].split("/")[-1], branches[1].split("/")[-1], a.fade))
        tmp = os.path.join(tempfile.mkdtemp(prefix="golem-lcbench-"), "lcbench.rpp")
        if os.path.exists(LCB):
            os.remove(LCB)
        post("/api/lcbench", {"op": "save", "path": tmp, "tracks": branches, "prep": True})
        for _ in range(80):
            time.sleep(0.1)
            if os.path.exists(LCB):
                break
        info = json.load(open(LCB))
        guids = [t["guid"] for t in info["tracks"]]
        if not all(guids) or not os.path.exists(tmp):
            sys.exit("✗ sauvegarde du projet jetable ratée : %s" % info)
        if not info["actions"].get("_S&M_NEXT_LIVE_CFG1"):
            sys.exit("✗ SWS n'expose pas _S&M_NEXT_LIVE_CFG1 sur ce Reaper")
        rpp = open(tmp, encoding="utf8", errors="surrogateescape").read()
        rpp = re.sub(r"\n\s*<S&M_LIVE_CONFIG 1 .*?\n\s*>", "", rpp, flags=re.S)       # une config 1 déjà là ? on la remplace
        chunk = ("    <S&M_LIVE_CONFIG 1 1 3 17 %s 0 %d \"\" -1 -1 -1 -1\n" % (NULL_GUID, a.fade)
                 + "".join("      %d \"%s\" %s \"\" \"\" \"\" \"\" \"\"\n" % (i, b.split("/")[-1], g) for i, (b, g) in enumerate(zip(branches, guids)))
                 + "    >\n")
        if "<EXTENSIONS" in rpp:
            rpp = rpp.replace("<EXTENSIONS\n", "<EXTENSIONS\n" + chunk, 1)
        else:
            i = rpp.rstrip().rfind(">")
            rpp = rpp[:i] + "  <EXTENSIONS\n" + chunk + "  >\n" + rpp[i:]
        open(tmp, "w", encoding="utf8", errors="surrogateescape").write(rpp)
        post("/api/lcbench", {"op": "open", "path": tmp})
        print("projet jetable rouvert avec la Live Config — j'attends que les captures se rechargent (8 s)…")
        time.sleep(8.0)
        arm(branches[1], merge)
        clock = Clock(); wait(clock, 1.0)
        nxt = lambda: osc("/action/str", "_S&M_NEXT_LIVE_CFG1")
        nxt(); g1 = wait(clock, 1.2); nxt(); g2 = wait(clock, 1.2)             # mise en route : première activation
        e1, e2 = g1["slots"][0]["env"], g2["slots"][0]["env"]
        print("niveau de la fusion : après 1er ordre %.1f dB · après 2e %.1f dB" % (e1, e2))
        if abs(e1 - e2) < 15:
            print("⚠ la Live Config ne bascule pas (niveaux identiques) — mesure sans valeur ; voir .apply.log")
        else:
            results["LiveConfigs"] = measure(clock, a.n, [nxt, nxt], "LiveCfg")
        post("/api/gapmeter", {"on": False}); time.sleep(0.5)
    finally:
        # ── LA SORTIE : Reaper redémarre sur le Set d'origine, puis le preset revient ──────────
        print("\nsortie : redémarrage de Reaper par le rack, puis rappel de « %s »…" % pid)
        try:
            post("/api/gapmeter", {"on": False})
        except Exception:
            pass
        post("/api/system/reaper-restart")
        for _ in range(90):
            time.sleep(1.0)
            s = get("/api/state")
            if s.get("reaper_running") and s.get("reaper_connected"):
                break
        time.sleep(4.0)
        try:
            post("/api/system/osc-refresh")
            post("/api/recall", {"preset": pid, "scene": "A"})
            # ⚠ mesuré le 2026-09-21 : après un rebuild, les captures d'une branche qui n'a JAMAIS été
            # active restent « en attente » dans le plugin (vérif : « la ligne est là, le plugin ne
            # charge pas ») ; un passage par la scène qui l'ouvre les charge. On le fait, puis on revient.
            time.sleep(4.0); post("/api/recall", {"scene": "B"}); time.sleep(3.0); post("/api/recall", {"scene": "A"})
        except Exception as e:
            print("⚠ rappel du preset : %s" % e)

    print("\n══ RÉSULTAT (ordre -> le son de l'autre branche sort de la fusion) ══")
    for k, r in results.items():
        summary(k, *r)
    print("\nGoleM : l'ordre passe par deux requêtes HTTP d'injection (~5 ms de plus que la vraie puce).")
    print("LiveConfigs : l'ordre est un paquet OSC envoyé droit à Reaper ; un pédalier y ajouterait son trajet MIDI.")


if __name__ == "__main__":
    main()
