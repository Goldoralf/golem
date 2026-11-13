#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le Golem Engine piloté par SON adaptateur (bridge/engine/ardour.py), sans rack (docs/ardour-plan.md §2, lot A1.4).

Lance le vrai moteur (luasession + golem_watch.lua, backend factice : aucun son, aucune carte) sur une racine golem
JETABLE (presets/ temporaire) et un port d'écoute libre : le rack d'à côté ne voit rien — ni ses presets, ni son port
OSC 9000. Puis, uniquement par l'adaptateur : relance, attente du veilleur, ping et status par le slot de commandes,
lecture du transport par OSC, arrêt. Rend 0 si tout passe.

  tools/check-engine-ardour.py [--engine-dir ~/golem-engine] [--keep]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine-dir", default=os.path.expanduser("~/golem-engine"))
    ap.add_argument("--keep", action="store_true", help="garder la racine jetable")
    a = ap.parse_args()
    os.environ["GOLEM_ENGINE_DIR"] = a.engine_dir

    work = tempfile.mkdtemp(prefix="golem-engine-check-")
    from bridge import commands
    from bridge import config as C
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from fakeardour import free_udp_port
    C.ROOT, C.PRESETS_DIR = work, os.path.join(work, "presets")
    C.COMMAND_FILE = os.path.join(C.PRESETS_DIR, ".command.json")
    commands.ACK_FILE = os.path.join(C.PRESETS_DIR, ".command-ack.json")
    C.BRIDGE_OSC_RECV_PORT = free_udp_port()
    os.makedirs(C.PRESETS_DIR)
    os.makedirs(os.path.join(work, "library"))
    os.symlink(os.path.join(ROOT, "library", "catalog"), os.path.join(work, "library", "catalog"))   # lu, jamais écrit
    from bridge import monitors
    monitors._WATCH_LOG = os.path.join(C.PRESETS_DIR, ".watch.log")
    from bridge.engine import ardour as A
    A.SESSION_DIR, A.RUN_LOG, A.BACKEND, A.DEVICE = os.path.join(work, "session"), os.path.join(work, "engine.log"), \
        "None (Dummy)", ""
    eng = A.ArdourEngine()
    from bridge import engine
    engine.use(eng)

    fails = []

    def check(label, ok, detail=""):
        print(f"  {'ok ' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            fails.append(label)
        return ok

    def wait(cond, timeout):
        end = time.time() + timeout
        while time.time() < end:
            v = cond()
            if v:
                return v
            time.sleep(0.1)
        return None

    def status():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".engine-status.json")))
        except (OSError, ValueError):
            return None

    def acked(seq):
        try:
            return json.load(open(commands.ACK_FILE)).get("seq") == seq
        except (OSError, ValueError):
            return False

    print(f"Golem Engine : {a.engine_dir}  (racine jetable {work}, retour OSC sur {C.BRIDGE_OSC_RECV_PORT})")
    t0 = time.time() - 1
    try:
        check("relance", eng.restart("check")["ok"])
        check("le moteur tourne (PID)", bool(wait(eng.pid, 20)), f"pid {eng.pid()}")
        check("le veilleur lit ses commandes", bool(wait(lambda: eng.ready_since(t0), 30)))
        check("version", bool(eng.version()), str(eng.version()))
        s = eng.send({"action": "ping"})
        check("ping accusé", bool(wait(lambda: acked(s), 3)), f"seq {s}")
        check("action hors vocabulaire refusée", eng.send({"action": "looper"}) is None)
        eng.request_inventory()
        inv = wait(lambda: eng.inventory(), 5) or {}
        check("inventaire : les plugins de la table sont installés", inv.get("total") and inv.get("n") == inv.get("total"),
              f"{inv.get('n')}/{inv.get('total')} {sorted(t for t, ok in (inv.get('found') or {}).items() if not ok)}")
        seen = []
        eng.start_feedback(lambda addr, args: seen.append(addr))
        time.sleep(0.5)
        eng.transport("play")
        time.sleep(0.5)
        s = eng.send({"action": "status"})
        st = wait(lambda: acked(s) and (status() or {}).get("rolling") is not None and status(), 3) or {}
        check("transport lancé par OSC", st.get("rolling") is True, json.dumps(st))
        xr0 = st.get("xruns") or 0          # le montage en compte (A0 : xruns au montage seulement) ; on juge le JEU
        eng.transport("stop")
        time.sleep(0.5)
        os.remove(os.path.join(C.PRESETS_DIR, ".engine-status.json"))
        s = eng.send({"action": "status"})
        st = wait(lambda: acked(s) and status(), 3) or {}
        check("transport arrêté par OSC", st.get("rolling") is False)
        check("0 xrun en jouant", (st.get("xruns") or 0) == xr0, f"dsp {st.get('dsp_load', 0):.1f} %, {xr0} au montage")
        rig_bench(eng, check, wait, acked)
        commands.flush(2)
    finally:
        eng.stop_feedback()
        check("arrêt", eng.stop(timeout=10))
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    print("OK" if not fails else f"{len(fails)} échec(s) : {', '.join(fails)}")
    return 0 if not fails else 1


# ── A2.0 : le patch de banc (une entrée, deux branches, un merge), rappel -> scène -> stomp -> potard OSC ────────────
# des fichiers du cache local de golem (assets/.cache, rempli par le contenu d'usine) : absents, le banc le dit (échec)
CACHE = os.path.join(ROOT, "assets", ".cache")
NAM = os.path.join(CACHE, "2cea181b_tim-r-fender-twinverb-vibrato-bright-a2.nam")
NAM2 = os.path.join(CACHE, "c4efbab1_amp-jcm800-2203-modified-hi-bad-boys-2---blend-1-a2.nam")
IR = os.path.join(CACHE, "93a0207e_16---palmer-g12m65-sm57-mid-15cm-45.wav")
BENCH_ID = "patch:engine-bench"


def bench_rig(scene):
    """Le plan COMPILÉ (forme de compile_rig) du patch de banc dans l'état de la scène : A = branche A seule, delay
    coupé ; B = branche B seule, delay au pied allumé, entrée du NAM B poussée."""
    a = scene == "A"
    pre = "GoleM:bench"
    merge, la, lb = pre + "#merge", pre + "/lane-a", pre + "/lane-b"
    return {"id": BENCH_ID, "mono_fallback": {"on": False, "gain": -3}, "looper": None, "paths": [{
        "id": "bench", "name": "Bench", "input": 1, "tracks": [
            {"role": "pre", "name": pre, "input": 1, "blocks": [], "sends_to": [la, lb], "out": None},
            {"role": "merge", "name": merge, "input": None, "merge_gain": -3, "folder": "parent", "out": 1,
             "level": None, "out_sel": "1-2",
             "blocks": [{"id": "met", "type": "met", "params": {"thresh": -60}},       # gate à clé : le DI de l'entrée 1
                        {"id": "dly", "type": "delay-tape", "foot": 8, "bypass": a, "params": {"feedback": 40, "mix": 30}},
                        {"type": "volume", "id": "volume-sys", "params": {"gain": 0.0}}]},
            {"role": "branch", "name": la, "input": None, "folder": "child", "folder_of": merge, "out": None, "mute": not a,
             "blocks": [{"id": "amp-a", "type": "amp-nam", "file": NAM, "bypass": not a, "params": {"output": 3.7}},
                        {"id": "cab-a", "type": "cab", "file": IR, "bypass": not a}]},
            {"role": "branch", "name": lb, "input": None, "folder": "child", "folder_of": merge, "out": None, "mute": a,
             "blocks": [{"id": "amp-b", "type": "amp", "file": NAM2, "bypass": a,
                         "params": {"input": 0.0 if a else 4.0, "output": 0.7}},
                        {"id": "gate-b", "type": "gate"}]}]}]}


def rig_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge.engine import ardour_plan
    rig_file = ardour_plan.rig_path(BENCH_ID)
    os.makedirs(os.path.dirname(rig_file), exist_ok=True)

    def put(scene):
        with open(rig_file, "w", encoding="utf-8") as f:
            json.dump(bench_rig(scene), f)

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return None

    def dump():
        p = os.path.join(C.PRESETS_DIR, ".engine-dump.json")
        if os.path.exists(p):
            os.remove(p)
        s = eng.send({"action": "dump"})
        return wait(lambda: acked(s) and read(".engine-dump.json"), 5) or {}

    if not all(os.path.isfile(f) for f in (NAM, NAM2, IR)):
        check("fichiers NAM/IR du banc présents", False, "assets/.cache sans les captures du banc")
        return
    put("A")
    t = time.time()
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    lm = wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == BENCH_ID and read(".livemap.json"), 30) or {}
    check("rappel : livemap écrit", bool(lm), f"{(time.time() - t) * 1000:.0f} ms, {len(lm.get('blocks') or {})} blocs")
    # le gate est joué par golem-fx depuis le 2026-11-12 : il est posé comme les autres (avant : écarté, REAPER seul)
    check("tous les blocs posés (gate et Met par golem-fx)",
          {"amp-a", "cab-a", "amp-b", "gate-b", "met", "dly", "volume-sys"} <= set(lm.get("blocks") or {}),
          ", ".join(sorted(lm.get("blocks") or {})))
    rc = wait(lambda: (read(".rig-check.json") or {}).get("checked") and read(".rig-check.json"), 10) or {}
    check("fichiers NAM et IR lus par les plugins", rc.get("ok") is True and rc.get("checked") == 3, json.dumps(rc)[:160])
    d = dump()
    tr = {x["name"]: x for x in d.get("tracks") or []}
    pre, merge = tr.get("GoleM:bench") or {}, tr.get("GoleM:bench#merge") or {}
    la, lb = tr.get("GoleM:bench/lane-a") or {}, tr.get("GoleM:bench/lane-b") or {}
    check("4 routes", len(tr) == 4, ", ".join(tr))
    check("entrée 1 de la carte sur la piste d'entrée", any(c.endswith("capture_1") for c in pre.get("input") or []),
          str(pre.get("input")))
    outs = pre.get("output") or []                      # Ardour écrit « : » en « - » dans les noms de PORTS
    check("la piste d'entrée nourrit les deux branches",
          len(outs) == 2 and any("/lane-a/" in c for c in outs) and any("/lane-b/" in c for c in outs), str(outs))
    mins = merge.get("input") or []
    check("les deux branches nourrissent le merge",
          len(mins) == 2 and any("/lane-a/" in c for c in mins) and any("/lane-b/" in c for c in mins), str(mins))
    check("le merge sort sur 1 et 2", sorted(c.rsplit("_", 1)[-1] for c in merge.get("output") or []) == ["1", "2"],
          str(merge.get("output")))
    # le gain du merge est son TRIM depuis le 2026-11-12 (le fader porte le niveau de la scène)
    check("merge à -3 dB (trim)", abs((merge.get("trim_db") or 0) + 3) < 0.05,
          f"trim {merge.get('trim_db')}, fader {merge.get('gain_db')}")
    check("limiteur de sécurité COMPILÉ (gfx-limiter) sur la route qui sort, et seulement elle",
          merge.get("safety") == "gfx-limiter" and not any(x.get("safety") for x in (pre, la, lb)), str(merge.get("safety")))
    blk = d.get("blocks") or {}
    check("scène A : branche B muette, A ouverte", lb.get("mute") is True and la.get("mute") is False)
    check("scène A : delay coupé, NAM A actif", (blk.get("dly") or {}).get("enabled") is False
          and (blk.get("amp-a") or {}).get("enabled") is True)
    check("paramètre posé (NAM A Output 3,7 dB)",
          abs(((blk.get("amp-a") or {}).get("params") or {}).get("Output Lvl", 0) - 3.7) < 0.01)
    key = (blk.get("met") or {}).get("key") or []
    check("la clé de Met (après les branches) entend l'entrée 1 de la carte, le DI",
          bool(key) and all(c.endswith("capture_1") for c in key), str(key))
    gkey = (blk.get("gate-b") or {}).get("key") or []
    check("la clé du gate golem-fx aussi", bool(gkey) and all(c.endswith("capture_1") for c in gkey), str(gkey))
    check("échelle du catalogue (Feedback 40 % -> 0,4)",
          abs(((blk.get("dly") or {}).get("params") or {}).get("Feedback", 0) - 0.4) < 0.001)

    # le COÛT du limiteur de sécurité (2026-11-13 : le Lua prenait 323 µs par cycle de 4 ms sur le rack)
    time.sleep(2)
    p = os.path.join(C.PRESETS_DIR, ".engine-dspstats.json")
    if os.path.exists(p):
        os.remove(p)
    s = eng.send({"action": "dspstats"})
    st = wait(lambda: acked(s) and read(".engine-dspstats.json"), 5) or {}
    lim = [x for r in st.get("routes") or [] if r.get("name") == "GoleM:bench#merge"
           for x in r.get("procs") or [] if "Limiter" in (x.get("name") or "") or x.get("name") == "golem Safety"]
    # par ÉCHANTILLON : le banc tourne à 1024, le rack à 192 (le Lua : 323 µs / 192 = 1,7 µs par échantillon)
    buf = st.get("buffer") or 1024
    per = (lim[-1].get("avg", 1e9) / buf) if lim else 1e9
    check("limiteur de sécurité peu coûteux (< 1 µs par échantillon ; le Lua : 1,7)", per < 1.0,
          f"{lim[-1].get('name')} : {per:.2f} µs/échantillon (moyenne {lim[-1].get('avg'):.0f} µs sur {buf})"
          if lim else json.dumps(st)[:200])

    put("B")
    s = eng.send({"action": "scene_apply", "preset": BENCH_ID, "scene": "B"})
    wait(lambda: acked(s), 3)
    time.sleep(0.2)
    d = dump()
    tr = {x["name"]: x for x in d.get("tracks") or []}
    blk = d.get("blocks") or {}
    check("scène B sans rebuild : branche A muette, B ouverte",
          (tr.get("GoleM:bench/lane-a") or {}).get("mute") is True and (tr.get("GoleM:bench/lane-b") or {}).get("mute") is False)
    check("scène B : delay allumé, entrée du NAM B à +4 dB", (blk.get("dly") or {}).get("enabled") is True
          and abs(((blk.get("amp-b") or {}).get("params") or {}).get("Input Lvl", 0) - 4.0) < 0.01)

    s = eng.send({"action": "stomp", "preset": BENCH_ID, "ids": ["dly"], "on": False})
    wait(lambda: acked(s), 3)
    time.sleep(0.1)
    check("stomp : delay coupé au pied", (dump().get("blocks") or {}).get("dly", {}).get("enabled") is False)

    lm = read(".livemap.json") or {}
    b = (lm.get("blocks") or {}).get("amp-b") or {}
    pm = (b.get("params") or {}).get("input") or {}
    ok = bool(pm) and eng.set_fx_param(b.get("track"), b.get("fx"), pm.get("p"), 0.75)
    time.sleep(0.3)
    v = ((dump().get("blocks") or {}).get("amp-b", {}).get("params") or {}).get("Input Lvl")
    check("potard par OSC via le livemap (norm 0,75 -> +10 dB)", bool(ok) and v is not None and abs(v - 10.0) < 0.05,
          f"strip {b.get('track')} fx {b.get('fx')} p {pm.get('p')} -> {v}")


if __name__ == "__main__":
    sys.exit(main())
