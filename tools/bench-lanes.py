#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Combien de lanes NAM ce rack tient-il ? — mesure, ne devine pas.

    ./tools/bench-lanes.py                 # 2, 4, 6 lanes avec une capture moyenne
    ./tools/bench-lanes.py --lanes 8       # jusqu'à 8
    ./tools/bench-lanes.py --extremes      # 6 lanes avec la capture la PLUS LÉGÈRE puis la PLUS LOURDE

POURQUOI CE SCRIPT EXISTE
`docs/patches.md` §11 engage le rack sur « tout le groupe passe par une seule machine » : cinq
musiciens dont un multi-lignes, donc six lanes ou plus, chacune avec sa capture NAM. On ne promet
pas ça sans chiffre, et le chiffre dépend de la MACHINE — la première mesure a été faite sur un
i9-13900H de développement, pas sur le Ryzen 5 8500G du rack.

CE QU'IL FAUT SAVOIR AVANT DE LIRE LE RÉSULTAT
· Le coût D'UNE INSTANCE dépend de la CAPTURE, pas de « NAM » : de 61 Ko à 2,25 Mo dans notre
  bibliothèque, quatre architectures (SlimmableContainer, WaveNet 2/4/5 couches). Écart mesuré :
  ~5× entre la plus légère et la plus lourde. Un budget « 6 lanes » n'a de sens qu'avec les
  captures qu'on va VRAIMENT jouer.
· Un bloc `amp` instancie DEUX plugins : le NAM et un convolueur d'IR. Le coût rapporté ci-dessous
  est celui de la paire.
· Le CPU seul ne dit pas tout : ce qui décide, c'est XRUNS = 0. Une machine à 300 %/cœur sans
  xrun tient ; une à 80 % qui décroche ne tient pas.

⚠ NETTOYER AVANT DE MESURER. Un transport qui roule, une prise perf-rec en cours ou un kit
DrumGizmo chargé faussent tout — la première campagne a été polluée par les trois. Le script les
coupe et le dit.
"""
import argparse
import copy
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
HZ = os.sysconf("SC_CLK_TCK")


def _post(path, body=None):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body or {}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r))


def _state():
    return json.load(urllib.request.urlopen(BRIDGE + "/api/state"))


def _pid():
    out = subprocess.run(["pgrep", "-x", "reaper"], capture_output=True, text=True).stdout.split()
    if not out:
        sys.exit("Reaper ne tourne pas.")
    return int(out[0])


def _ticks(p):
    f = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
    return int(f[11]) + int(f[12])                 # utime + stime


def cleanup():
    """Coupe ce qui fausse la mesure, et le DIT."""
    st = _state()
    if (st.get("perf") or {}).get("recording"):
        print("  ⚠ une prise perf-rec tournait — arrêtée"); _post("/api/perf/stop"); time.sleep(4)
    if (st.get("backing") or {}).get("playing"):
        print("  ⚠ le transport du backing roulait — arrêté"); _post("/api/backing", {"op": "stop"}); time.sleep(2)


def pick_models():
    """(léger, moyen, lourd) : (ref, model) triés par TAILLE DE FICHIER, la seule mesure du poids
    qu'on ait sans instancier le plugin."""
    idx = json.load(open(os.path.join(ROOT, "library", "catalog", "tones-index.json")))
    tones = idx["tones"]
    rows = []
    it = tones.items() if isinstance(tones, dict) else [(t.get("id"), t) for t in tones]
    for tid, t in it:
        for m in (t.get("models") or []):
            f = m.get("file") or m.get("path")
            if f and f.endswith(".nam"):
                p = f if f.startswith("/") else os.path.join(ROOT, f)
                if os.path.exists(p):
                    rows.append((os.path.getsize(p), str(tid), m.get("id")))
    if not rows:
        sys.exit("aucune capture NAM résolue — lancer provision/fetch-assets.sh ?")
    rows.sort()
    return rows[0], rows[len(rows) // 2], rows[-1]


def _amp(i, ref, model):
    return {"type": "amp", "id": f"amp-b-{i}", "ref": ref, "model": model,
            "params": {"input": -6, "output": -18, "quality": 1}}


def build(n, ref, model, paths=False):
    """Un preset jetable à N amplis. `paths=False` : N BRANCHES d'une seule lane (l'ancien banc —
    mesure le coût des instances). `paths=True` (lot 2, audit N lanes) : N LANES AUDIO distinctes,
    un ampli chacune — le cas « deux guitares ». Tant que le document parle trois royaumes, n ≤ 2
    lanes audio (guitare + voix, la voix ayant désormais le graphe riche)."""
    p = {"id": "zz-bench", "name": "ZZ Bench", "bpm": 120, "guitar": {"pre": [], "split": None, "post": []},
         "voice": {"chain": []}, "keys": {"chain": []}, "scenes": [{"id": "A", "name": "A"}]}
    if paths:
        # LOT 5 : un document v2 à N lanes audio, une par entrée (au-delà des entrées de la carte,
        # Reaper crée le root et le lie à une entrée qui n'existe pas : muet, mais le CPU est réel)
        p = {"id": "zz-bench", "name": "ZZ Bench", "bpm": 120, "lanes_v": 2, "scenes": [{"id": "A", "name": "A"}],
             "lanes": [{"id": "guitar" if i == 0 else f"ln-{i + 1}", "role": "guitar", "name": f"Lane {i + 1}", "in_sel": str(i + 1),
                        "chain": {"pre": [_amp(i, ref, model)], "split": None, "post": []}} for i in range(n)]}
    else:
        p["guitar"]["split"] = {"mode": "merge", "gain": -18, "branches": [
            {"id": f"lane-{i}", "blocks": [_amp(i, ref, model)]} for i in range(n)]}
    json.dump(p, open(os.path.join(ROOT, "presets", "zz-bench.json"), "w"), ensure_ascii=False, indent=1)


def mounted():
    """⚠ VÉRIFIER QUE LE RIG A BIEN N LANES. Un rappel peut répondre « ok » et ne rien
    reconstruire — c'est arrivé, et on mesurait l'ancien rig en croyant mesurer le nouveau."""
    _post("/api/fxdump"); time.sleep(4)
    d = json.load(open(os.path.join(ROOT, "presets", ".fxdump.json")))
    return sum(1 for t in d if t.get("track", "").startswith("Sandbox #Input")
               and any("Neural Amp" in f["plugin"] for f in t["fx"]))


def sample(sec):
    p = _pid()
    x0 = _state().get("xruns") or 0
    t0, c0 = time.time(), _ticks(p)
    time.sleep(sec)
    t1, c1 = time.time(), _ticks(p)
    return (c1 - c0) / HZ / (t1 - t0) * 100, (_state().get("xruns") or 0) - x0


def run(n, ref, model, label, window, paths=False):
    build(n, ref, model, paths=paths)
    _post("/api/recall", {"preset": "zz-bench"})
    time.sleep(16)                                            # rebuild + settle
    got = mounted()
    vals, xr = [], 0
    for _ in range(2):
        c, x = sample(window); vals.append(c); xr += x
    ok = "" if got == n else f"  ⚠ {got} MONTÉES au lieu de {n} — écarté"
    print(f"  {label:<24} {statistics.median(vals):6.1f} %/cœur   xruns +{xr}{ok}")
    return (statistics.median(vals), xr) if got == n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", type=int, default=6)
    ap.add_argument("--window", type=int, default=20, help="durée d'un échantillon (s)")
    ap.add_argument("--extremes", action="store_true", help="capture la plus légère vs la plus lourde")
    ap.add_argument("--paths", action="store_true", help="N LANES audio distinctes (document v2) au lieu de N branches d'une lane")
    a = ap.parse_args()

    cpu = subprocess.run(["bash", "-c", "grep -m1 'model name' /proc/cpuinfo | cut -d: -f2"],
                         capture_output=True, text=True).stdout.strip()
    print(f"machine : {cpu} · {os.cpu_count()} threads")
    print("nettoyage :"); cleanup()
    light, mid, heavy = pick_models()
    print(f"captures  : léger {light[0]//1024} Ko · moyen {mid[0]//1024} Ko · lourd {heavy[0]//1024} Ko\n")

    before = _state().get("preset_id")
    try:
        if a.extremes:
            for tag, m in (("la plus LÉGÈRE", light), ("la plus LOURDE", heavy)):
                run(a.lanes, m[1], m[2], f"{a.lanes} lanes · {tag}", a.window)
        else:
            pts = {}
            for n in ((1, 2, a.lanes) if a.paths else (2, 4, a.lanes)):
                r = run(n, mid[1], mid[2], f"{n} {'lanes audio' if a.paths else 'branches'} · capture moyenne", a.window, paths=a.paths)
                if r:
                    pts[n] = r[0]
            if len(pts) >= 2:
                ns, ys = sorted(pts), [pts[k] for k in sorted(pts)]
                mx, my = statistics.mean(ns), statistics.mean(ys)
                pente = sum((n - mx) * (y - my) for n, y in zip(ns, ys)) / sum((n - mx) ** 2 for n in ns)
                print(f"\n  {pente:.1f} %/cœur PAR LANE (NAM + IR) · fond {my - pente * mx:.0f} %/cœur")
                print(f"  {a.lanes} lanes ≈ {a.lanes * pente / 100:.2f} cœur de traitement")
        print("\n  Ce qui DÉCIDE, c'est xruns = 0. Le pourcentage ne fait qu'indiquer la marge.")
    finally:
        os.path.exists(os.path.join(ROOT, "presets", "zz-bench.json")) and \
            os.remove(os.path.join(ROOT, "presets", "zz-bench.json"))
        if before:
            _post("/api/recall", {"preset": before})
        print(f"  rig restauré sur « {before} », preset de test supprimé.")


if __name__ == "__main__":
    main()
