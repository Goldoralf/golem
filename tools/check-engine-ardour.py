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
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class EngineDied(Exception):
    """Le moteur est sorti sur un plantage pendant le banc (la ligne de run.py)."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine-dir", default=os.path.expanduser("~/golem-engine"))
    ap.add_argument("--keep", action="store_true", help="garder la racine jetable")
    ap.add_argument("--only", help="ne jouer que ces sections, séparées par des virgules (rig, rec, click, clock, drums, "
                                   "standard, tuner, backing, preview, sample, looper, host, riff, trial, miditake, "
                                   "capture, keys) — le démarrage (relance, ping, inventaire, transport) tourne toujours")
    a = ap.parse_args()
    os.environ["GOLEM_ENGINE_DIR"] = a.engine_dir
    # SON port OSC, jamais le 3819 : un rack qui tourne sur le Golem Engine l'occupe — le moteur du banc prenait 3820 en
    # silence et l'adaptateur du banc parlait au moteur du RACK (2026-11-17 : il a lancé son transport)
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as _s:
        _s.bind(("127.0.0.1", 0))
        os.environ["GOLEM_ENGINE_OSC"] = str(_s.getsockname()[1])
    # la carte factice JOUE du MIDI sur ses entrées (des phrases fixes) : la prise d'une lane clavier a quelque chose à
    # capter. Aucune autre lane du banc n'ouvre ces ports.
    os.environ["GOLEM_ENGINE_MIDI"] = "Midi Event Generators"

    work = tempfile.mkdtemp(prefix="golem-engine-check-")
    from bridge import commands
    from bridge import config as C
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from fakeardour import free_udp_port
    C.ROOT, C.PRESETS_DIR = work, os.path.join(work, "presets")
    # les chemins calculés à l'import suivent : sans ça le banc lisait — et écrivait — le looper du RACK d'à côté
    C.LOOPER_FILE, C.LOOPER_CMD_FILE = os.path.join(C.PRESETS_DIR, ".looper.json"), os.path.join(C.PRESETS_DIR, ".looper-cmd.json")
    C.COMMAND_FILE = os.path.join(C.PRESETS_DIR, ".command.json")
    commands.ACK_FILE = os.path.join(C.PRESETS_DIR, ".command-ack.json")
    C.BRIDGE_OSC_RECV_PORT = free_udp_port()
    os.makedirs(C.PRESETS_DIR)
    os.makedirs(os.path.join(work, "library"))
    # la branche muette ENDORMIE (2026-11-13) : allumée ici pour l'éprouver ; éteinte par défaut sur un rack
    os.makedirs(os.path.join(work, "config"))
    with open(os.path.join(work, "config", "golem-engine.json"), "w", encoding="utf-8") as f:
        json.dump({"sleep_muted_branches": True}, f)
    src, dst = os.path.join(ROOT, "library", "catalog"), os.path.join(work, "library", "catalog")   # lu, jamais écrit
    if sys.platform == "win32":
        # un lien symbolique demande un privilège sous Windows (WinError 1314) : une JONCTION de dossier, non
        import _winapi
        _winapi.CreateJunction(src, dst)
    else:
        os.symlink(src, dst)
    from bridge import monitors
    monitors._WATCH_LOG = os.path.join(C.PRESETS_DIR, ".watch.log")
    from bridge.engine import ardour as A
    A.SESSION_DIR, A.RUN_LOG, A.BACKEND, A.DEVICE = os.path.join(work, "session"), os.path.join(work, "engine.log"), \
        "None (Dummy)", "Sine Wave 1K, 1/3 Oct"   # la carte factice qui JOUE un sinus FIXE sur ses entrées (1 kHz et ses
    # tiers d'octave, un par canal). Le nom EXACT : « Sine Wave 1K » ouvrait « Sine Wave », dont la fréquence est tirée
    # au hasard à chaque démarrage du backend — les niveaux du banc changeaient d'un lancement à l'autre (2026-11-17)
    eng = A.ArdourEngine()
    from bridge import engine
    engine.use(eng)

    fails = []

    def check(label, ok, detail=""):
        print(f"  {'ok ' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
        if not ok:
            fails.append(label)
        return ok

    # un moteur MORT (plantage) arrête le banc : sans ça chaque attente allait à son plafond et chaque section échouait
    # à son tour — 5 min de faux échecs après une violation d'accès (2026-11-20). La ligne vient de run.py ; un arrêt
    # demandé sort en 0 ou 15, un plantage en négatif (signal, Linux) ou en 0xC…… (exception, Windows)
    log_seen = {"pos": 0}

    def engine_crash():
        try:
            with open(A.RUN_LOG, "rb") as f:
                f.seek(log_seen["pos"])
                new = f.read()
        except OSError:
            return None
        log_seen["pos"] += len(new)
        for m in re.finditer(rb"luasession exited with code (-?\d+)[^\r\n]*", new):
            code = int(m.group(1))
            if code < 0 or code >= 0xC0000000:
                return m.group(0).decode("utf-8", "replace")
        return None

    def wait(cond, timeout):
        end = time.time() + timeout
        while time.time() < end:
            v = cond()
            if v:
                return v
            dead = engine_crash()
            if dead:
                raise EngineDied(dead)
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
        # attendre qu'il ROULE, pas le premier état lu (2026-11-19, Windows) : avec les 35 pistes du banc le transport met
        # plus de 0,5 s à partir, et l'état « arrêté » d'avant le départ suffisait à juger — l'état est republié toutes les 2 s
        st = wait(lambda: acked(s) and (status() or {}).get("rolling") is True and status(), 3) or status() or {}
        check("transport lancé par OSC", st.get("rolling") is True, json.dumps(st))
        xr0 = st.get("xruns") or 0          # le montage en compte (A0 : xruns au montage seulement) ; on juge le JEU
        eng.transport("stop")
        time.sleep(0.5)
        os.remove(os.path.join(C.PRESETS_DIR, ".engine-status.json"))
        s = eng.send({"action": "status"})
        st = wait(lambda: acked(s) and status(), 3) or {}
        check("transport arrêté par OSC", st.get("rolling") is False)
        check("0 xrun en jouant", (st.get("xruns") or 0) == xr0, f"dsp {st.get('dsp_load', 0):.1f} %, {xr0} au montage")
        # --only : les sections nommées seulement (2026-11-19, portage Windows : rejouer celle qui plante en 2 min, pas 10)
        sections = [("rig", rig_bench), ("rec", rec_bench), ("click", click_bench), ("clock", clock_bench),
                    ("drums", drums_bench), ("standard", standard_bench), ("tuner", tuner_bench),
                    ("backing", backing_bench), ("preview", preview_bench), ("sample", sample_bench),
                    ("looper", looper_bench), ("host", host_bench), ("riff", riff_bench), ("trial", None),
                    ("miditake", miditake_bench), ("capture", capture_bench), ("keys", keys_bench)]
        only = {s.strip() for s in (a.only or "").split(",") if s.strip()}
        unknown = only - {n for n, _ in sections}
        if unknown:
            raise SystemExit(f"--only: unknown section(s) {sorted(unknown)} — known: {[n for n, _ in sections]}")
        for name, fn in sections:
            if only and name not in only:
                continue
            print(f"── {name}", flush=True)
            if fn is None:
                trial_bench(check)
            else:
                fn(eng, check, wait, acked)
        commands.flush(2)
    except EngineDied as e:
        check("le moteur est resté vivant", False, f"{e} — banc arrêté, journal {A.RUN_LOG}")
    finally:
        eng.stop_feedback()
        check("arrêt", eng.stop(timeout=10))
        if not a.keep:
            catalog = os.path.join(work, "library", "catalog")
            if sys.platform == "win32" and os.path.isdir(catalog):
                os.rmdir(catalog)                        # la JONCTION seule, jamais le catalogue qu'elle désigne
            shutil.rmtree(work, ignore_errors=True)
    print("OK" if not fails else f"{len(fails)} échec(s) : {', '.join(fails)}")
    return 0 if not fails else 1


# ── A2.0 : le patch de banc (une entrée, deux branches, un merge), rappel -> scène -> stomp -> potard OSC ────────────
# des fichiers du cache local de golem (assets/.cache, rempli par le contenu d'usine) : absents, le banc le dit (échec)
CACHE = os.path.join(ROOT, "assets", ".cache")


def _cached(name, prefix):
    """Le fichier du cache PAR SON NOM (2026-11-19) : le préfixe est une empreinte du fichier, qui change quand la capture
    est republiée — figé, il faisait échouer le banc sur une machine qui a la même capture sous un autre préfixe. Le
    préfixe connu d'abord, sinon le premier `<préfixe>_<nom>` du cache."""
    exact = os.path.join(CACHE, f"{prefix}_{name}")
    if os.path.isfile(exact):
        return exact
    import glob
    found = sorted(glob.glob(os.path.join(glob.escape(CACHE), "*_" + glob.escape(name))))
    return found[0] if found else exact


NAM = _cached("tim-r-fender-twinverb-vibrato-bright-a2.nam", "2cea181b")
NAM2 = _cached("amp-jcm800-2203-modified-hi-bad-boys-2---blend-1-a2.nam", "c4efbab1")
IR = _cached("16---palmer-g12m65-sm57-mid-15cm-45.wav", "93a0207e")
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
                        {"id": "dly", "type": "delay", "foot": 8, "bypass": a, "params": {"feedback": 40, "mix": 30}},
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
    from bridge import mixer
    mixer.MIXER_FILE = os.path.join(C.ROOT, "config", "mixer.json")     # les trims du banc, jamais ceux du rack
    os.makedirs(os.path.dirname(mixer.MIXER_FILE), exist_ok=True)

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
    check("scène A : la branche B muette est ENDORMIE (son gate, actif dans la scène, n'est pas calculé)",
          lb.get("asleep") is True and (blk.get("gate-b") or {}).get("active") is False and la.get("asleep") is False
          and (blk.get("amp-a") or {}).get("active") is True,
          f"B asleep={lb.get('asleep')} gate-b active={(blk.get('gate-b') or {}).get('active')}")
    check("scène A : delay coupé, NAM A actif", (blk.get("dly") or {}).get("enabled") is False
          and (blk.get("amp-a") or {}).get("enabled") is True)
    check("paramètre posé (NAM A Output 3,7 dB)",
          abs(((blk.get("amp-a") or {}).get("params") or {}).get("Output Lvl", 0) - 3.7) < 0.01)
    key = (blk.get("met") or {}).get("key") or []
    check("la clé de Met (après les branches) entend l'entrée 1 de la carte, le DI",
          bool(key) and all(c.endswith("capture_1") for c in key), str(key))
    gkey = (blk.get("gate-b") or {}).get("key") or []
    check("la clé du gate golem-fx aussi", bool(gkey) and all(c.endswith("capture_1") for c in gkey), str(gkey))
    fb = ((blk.get("dly") or {}).get("params") or {}).get("Feedback")
    # le delay est celui de golem-fx : un réglage renommé par la table part dans l'unité du CATALOGUE (40 %, plus le
    # 0,4 du delay Calf d'avant — docs/ardour-plan.md, ardour_plan.table_def)
    check("unité du catalogue (Feedback 40 % arrive à 40 sur le delay golem-fx)", fb is not None and abs(fb - 40) < 0.01,
          f"Feedback = {fb} ; ports : {sorted((blk.get('dly') or {}).get('params') or {})[:12]}")

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
    check("scène B : la branche B RÉVEILLÉE (NAM et gate calculés), la A endormie",
          (tr.get("GoleM:bench/lane-b") or {}).get("asleep") is False and (blk.get("amp-b") or {}).get("active") is True
          and (blk.get("gate-b") or {}).get("active") is True and (tr.get("GoleM:bench/lane-a") or {}).get("asleep") is True,
          f"amp-b active={(blk.get('amp-b') or {}).get('active')} gate-b active={(blk.get('gate-b') or {}).get('active')}")
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

    # LES CRÊTES de la chasse au silence (bridge/silence.py) : la carte factice joue un sinus sur ses entrées
    from bridge import silence

    def peaks():
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        rows = json.loads(txt) if txt else []
        return {r["track"].split(" ", 1)[1]: r for r in rows}

    time.sleep(1.0)
    pk = peaks()
    root, out = pk.get("golem:in1") or {}, pk.get("GoleM:bench#merge") or {}
    check("crêtes : l'entrée de la lane est dite `root` et porte le signal de la carte",
          root.get("root") is True and root.get("instL", -150) > -60, json.dumps(root))
    check("crêtes : la route qui sort est dite reliée à la carte (2 sorties) et porte le signal",
          out.get("rig") is True and out.get("hw_sends") == 2 and out.get("instL", -150) > -60, json.dumps(out))
    best = {n: {"inst": r["instL"], **{k: r[k] for k in ("mute", "hw_sends", "sends", "root", "rig")}} for n, r in pk.items()}
    v = silence.verdict({"audio": {"ok": True}, "engine_name": "Golem Engine"}, best, None, None)
    check("crêtes : la chasse conclut « le signal sort du moteur »", v.get("code") == "downstream", json.dumps(v)[:160])

    # LE MIXER DE SORTIES (docs/mixer.md) : le trim du rig par-dessus le niveau de scène, sur la route qui sort
    def merge_now():
        return {x["name"]: x for x in dump().get("tracks") or []}.get("GoleM:bench#merge") or {}

    def mix(levels):
        s = eng.send({"action": "mixer_apply", "levels": levels})
        wait(lambda: acked(s), 3)
        time.sleep(0.1)
        return merge_now()

    m = mix({"in1": {"db": -6.0, "mute": False}})
    check("mixer : trim -6 dB sur la route qui sort (source in1), niveau de scène gardé",
          m.get("mixer") == "in1" and abs((m.get("gain_db") or 0) + 6) < 0.05 and m.get("mute") is False
          and abs((m.get("trim_db") or 0) + 3) < 0.05, f"fader {m.get('gain_db')} trim {m.get('trim_db')} mute {m.get('mute')}")
    check("mixer : le trim ne touche que la sortie (les branches restent à 0 dB)",
          all(abs(x.get("gain_db") or 0) < 0.05 for x in dump().get("tracks") or [] if x["name"] != "GoleM:bench#merge"))
    m = mix({"in1": {"db": -6.0, "mute": True}})
    check("mixer : mute de la tranche", m.get("mute") is True)
    m = mix({"in1": {"db": -60.0, "mute": False}})
    check("mixer : -60 dB vaut silence", m.get("mute") is True, f"fader {m.get('gain_db')}")
    m = mix({"in1": {"db": 6.0, "mute": False}})
    check("mixer : jamais de gain (un +6 dB demandé reste à 0)", abs(m.get("gain_db") or 0) < 0.05 and m.get("mute") is False,
          f"fader {m.get('gain_db')}")
    with open(mixer.MIXER_FILE, "w", encoding="utf-8") as f:
        json.dump({"levels": {"in1": {"db": -9.0, "mute": False}}}, f)
    put("A")
    s = eng.send({"action": "scene_apply", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s), 3)
    time.sleep(0.2)
    m = merge_now()
    check("mixer : une scène repose le trim du rig (config/mixer.json, -9 dB)", abs((m.get("gain_db") or 0) + 9) < 0.05,
          f"fader {m.get('gain_db')}")
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == BENCH_ID, 30)
    time.sleep(0.3)
    m = merge_now()
    check("mixer : un rappel aussi", abs((m.get("gain_db") or 0) + 9) < 0.05, f"fader {m.get('gain_db')}")

    # LA CARTE ROUVERTE et les claviers rouverts (Health ▸ Fix) : le moteur repart, le rig et ses liens restent
    s = eng.send({"action": "audio_reset"})
    wait(lambda: acked(s), 10)
    time.sleep(0.5)
    st = read(".engine-status.json") or {}
    m = merge_now()
    check("carte rouverte : le moteur tourne, le rig et ses sorties sont restés",
          st.get("running") is True and sorted(c.rsplit("_", 1)[-1] for c in m.get("output") or []) == ["1", "2"]
          and len(dump().get("blocks") or {}) == 7, f"running={st.get('running')} sorties={m.get('output')}")
    pk = peaks()
    check("carte rouverte : le signal passe encore", (pk.get("GoleM:bench#merge") or {}).get("instL", -150) > -60,
          json.dumps(pk.get("GoleM:bench#merge")))
    s = eng.send({"action": "midi_reinit"})
    check("claviers rouverts : commande accusée (aucune lane MIDI dans ce rig)", bool(wait(lambda: acked(s), 5)))


# ── lot 3 : la PRISE (docs/ardour-plan.md §7d) — la carte factice joue un sinus sur ses entrées : on l'enregistre ─────
def wav_info(path):
    """(canaux, secondes, crête en dBFS) d'un fichier de la prise, par ffmpeg (le moteur écrit du flottant)."""
    import re
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    ch = 2 if re.search(r"Audio:.*stereo", r) else 1 if re.search(r"Audio:.*mono", r) else 0
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r)
    pk = re.search(r"max_volume: ([-\d.]+) dB", r)
    return ch, (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else 0.0, float(pk.group(1)) if pk else -150.0


def wav_typical_peak(path, win=2400):
    """Crête TYPIQUE en dBFS : la médiane des crêtes par tranche de `win` échantillons (50 ms à 48 kHz), tranches muettes
    exclues. Un recouvrement bref (un son relancé sur lui-même) ne touche qu'une ou deux tranches : la médiane l'ignore."""
    import re
    import statistics
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                        f"asetnsamples=n={win}:p=0,astats=metadata=1:reset=1,"
                        "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-", "-f", "null", "-"],
                       capture_output=True, text=True).stdout
    pk = []
    for v in re.findall(r"Peak_level=(\S+)", r):          # « -inf » pour une tranche muette
        try:
            pk.append(float(v))
        except ValueError:
            pass
    pk = [v for v in pk if v > -60]
    return statistics.median(pk) if pk else -150.0


def rec_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge.engine import ardour_plan

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return None

    def perf():
        return read(".perf.json") or {}

    def take(src, seconds, during=None):
        with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
            json.dump(src, f)
        s = eng.send({"action": "perf_rec", "on": True})
        ok = wait(lambda: acked(s) and perf().get("recording") is True, 8)
        time.sleep(seconds)
        if during:
            during()
        s = eng.send({"action": "perf_rec", "on": False})
        done = wait(lambda: acked(s) and perf().get("recording") is False, 20)
        return bool(ok), bool(done), perf()

    # le rig du banc, scène A, remonté propre (le mixer du banc tient la sortie à -9 dB)
    with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
        json.dump(bench_rig("A"), f)
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == BENCH_ID, 30)
    time.sleep(1.0)

    def recall_again():
        s2 = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
        wait(lambda: acked(s2), 30)
        time.sleep(1.5)

    ok, done, st = take({"in1": True, "in2": True, "usb": False, "mode": "tracks_di", "mix": True}, 2.0, during=recall_again)
    check("prise : partie, puis dite finie une fois ses fichiers rangés", ok and done and not st.get("error"), json.dumps(st))
    d = os.path.join(C.ROOT, st.get("file") or "missing")
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    check("prise multipiste : un dossier, le mix, la lane, sa DI et la boîte à rythmes — les noms de REAPER",
          files == ["DI-Sandbox-Input-1.wav", "Drums.wav", "Input-1.wav", "Mix.wav"], f"{st.get('file')} : {files}")
    if files == ["DI-Sandbox-Input-1.wav", "Drums.wav", "Input-1.wav", "Mix.wav"]:
        di, drums, lane, mix = (wav_info(os.path.join(d, n)) for n in files)
        check("prise : le mix et la lane sont stéréo, la DI mono", (mix[0], lane[0], di[0]) == (2, 2, 1), f"{mix[0]}/{lane[0]}/{di[0]}")
        check("prise : un rappel PENDANT la prise ne la coupe pas (elle dure toute la séance, plus de 3 s)",
              mix[1] > 3.0 and abs(mix[1] - di[1]) < 0.3, f"mix {mix[1]:.2f} s, DI {di[1]:.2f} s")
        check("prise : la DI est le signal BRUT de l'entrée (le sinus de la carte, -18 dBFS), rien n'est doublé à la reprise",
              abs(di[2] + 18) < 0.5, f"DI {di[2]:.1f} dBFS")
    # le mix se juge contre un autre FICHIER de la même prise, pas contre le vumètre du moteur (sa crête garde un
    # transitoire d'avant la remise à zéro)
    first_mix = first_typ = None
    if files == ["DI-Sandbox-Input-1.wav", "Drums.wav", "Input-1.wav", "Mix.wav"]:
        first_mix, first_typ = mix[2], wav_typical_peak(os.path.join(d, "Mix.wav"))
        check("prise : avec une seule lane, le mix et la piste de la lane sont le même son (à 0,5 dB près)",
              abs(mix[2] - lane[2]) < 0.5 and mix[2] > -100, f"mix {mix[2]:.1f} dBFS, lane {lane[2]:.1f} dBFS")
    lm = read(".livemap.json") or {}
    b = (lm.get("blocks") or {}).get("amp-b") or {}
    pm = (b.get("params") or {}).get("input") or {}
    eng._ranges = {}                                       # les bornes relues au livemap d'après la prise
    eng.set_fx_param(b.get("track"), b.get("fx"), pm.get("p"), 0.5)
    time.sleep(0.4)
    p = os.path.join(C.PRESETS_DIR, ".engine-dump.json")
    if os.path.exists(p):
        os.remove(p)
    s = eng.send({"action": "dump"})
    dmp = wait(lambda: acked(s) and read(".engine-dump.json"), 5) or {}
    v = ((dmp.get("blocks") or {}).get("amp-b", {}).get("params") or {}).get("Input Lvl")
    check("prise : après elle, les potards par OSC visent toujours le bon plugin (les strips sont renumérotés)",
          v is not None and abs(v) < 0.05, f"strip {b.get('track')} -> Input Lvl {v}")
    # le potard REMIS à la valeur de la scène (+4 dB) : la prise suivante est comparée à celle d'avant, sur le même rig.
    # (2026-11-19, Windows : ce n'était PAS la cause de l'écart d'environ 1 dB entre les deux prises — la seconde mesure
    # -37,6 dBFS avec ou sans ce geste ; l'écart était une pointe passagère dans la prise qui couvre le rappel, voir
    # plus bas : le niveau se juge maintenant en crête typique)
    lo, hi = float(pm.get("pmin", -20)), float(pm.get("pmax", 20))
    eng.set_fx_param(b.get("track"), b.get("fx"), pm.get("p"), (4.0 - lo) / ((hi - lo) or 1.0))
    time.sleep(0.4)

    ok, done, st = take({"in1": True, "mode": "mix", "mix": True}, 1.5)
    f = os.path.join(C.ROOT, st.get("file") or "missing")
    info = wav_info(f) if os.path.isfile(f) else (0, 0, -150)
    check("prise en mode mix : UN fichier stéréo à plat, qui sonne", ok and done and f.endswith(".wav") and info[0] == 2
          and info[1] > 1.0 and info[2] > -100, f"{st.get('file')} {info}")
    # LE MÊME RIG SORT AU MÊME NIVEAU D'UN RAPPEL À L'AUTRE : la prise d'avant couvre un rappel, celle-ci le suit. Deux
    # causes d'écart trouvées le 2026-11-17 et retirées : la carte factice ouverte par un nom ambigu (fréquence tirée au
    # hasard à chaque démarrage), et l'entrée reliée avant que la scène soit posée (un écho fantôme dans le delay).
    # Le niveau STABLE (crête typique) : la prise d'avant porte parfois une pointe passagère au moment du rappel (2026-11-20 :
    # -36,3 au lieu de -37,6 dBFS en crête globale, la piste de la lane aussi — c'est le son du rig pendant sa
    # reconstruction, pas un autre niveau). Elle est affichée (« pointe ») sans juger : ce n'est pas la question posée ici.
    typ = wav_typical_peak(f) if os.path.isfile(f) else -150.0
    check("le rig sort au même niveau d'un rappel à l'autre (deux prises de suite, à 1 dB près)",
          first_typ is not None and abs(typ - first_typ) < 1.0,
          f"prise d'avant {first_typ if first_typ is None else round(first_typ, 1)} dBFS typique "
          f"(pointe au rappel +{(first_mix or 0) - (first_typ or 0):.1f} dB), celle-ci {typ:.1f} dBFS")
    ok, done, st = take({"in1": False, "in2": True, "mode": "tracks_di", "mix": True}, 1.2)
    d = os.path.join(C.ROOT, st.get("file") or "missing")
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    silent = wav_info(os.path.join(d, "Mix.wav"))[2] if "Mix.wav" in files else 0
    check("prise : une entrée décochée n'est ni dans le mix ni en piste", files == ["Drums.wav", "Mix.wav"] and silent < -85, f"{files} {silent}")
    # le mix est ce que le musicien ENTEND : la tranche coupée au mixer, il se tait — la DI, elle, reste brute
    s = eng.send({"action": "mixer_apply", "levels": {"in1": {"db": 0.0, "mute": True}}})
    wait(lambda: acked(s), 3)
    ok, done, st = take({"in1": True, "mode": "tracks_di", "mix": True}, 1.2)
    d = os.path.join(C.ROOT, st.get("file") or "missing")
    lv = {n: wav_info(os.path.join(d, n))[2] for n in (os.listdir(d) if os.path.isdir(d) else [])}
    check("prise : le mix suit le mixer (tranche coupée = mix muet), la DI reste brute",
          lv.get("Mix.wav", 0) < -85 and abs(lv.get("DI-Sandbox-Input-1.wav", 0) + 18) < 0.5, str(lv))
    s = eng.send({"action": "mixer_apply", "levels": {"in1": {"db": -9.0, "mute": False}}})
    wait(lambda: acked(s), 3)
    s = eng.send({"action": "perf_rec", "on": False})
    wait(lambda: acked(s), 3)
    check("prise : un arrêt sans prise ne casse rien", perf().get("recording") is False)

    # LE NIVEAU DE SCÈNE EST UN NIVEAU, pas une saturation : les plugins sont posés AVANT le fader (golem_chain.lua).
    # Sur un ampli poussé (entrée +12 dB), +6 dB de scène doivent sortir +6 dB — posés après le fader, ils donnaient
    # -1 dB (mesuré 2026-11-17).
    def amp_level(level):
        rig = {"id": BENCH_ID, "mono_fallback": {"on": False, "gain": -3}, "looper": None, "paths": [{
            "id": "bench", "name": "Bench", "input": 1, "tracks": [
                {"role": "main", "name": "GoleM:bench", "input": 1, "out": 1, "level": level, "out_sel": "1-2",
                 "blocks": [{"id": "amp-a", "type": "amp-nam", "file": NAM2, "params": {"input": 12, "output": 0}}]}]}]}
        with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
            json.dump(rig, f)
        s2 = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
        wait(lambda: acked(s2), 30)
        time.sleep(1.2)
        _, _, st2 = take({"in1": True, "mode": "mix", "mix": True}, 1.0)
        f2 = os.path.join(C.ROOT, st2.get("file") or "missing")
        return wav_info(f2)[2] if os.path.isfile(f2) else None

    s = eng.send({"action": "mixer_apply", "levels": {"in1": {"db": 0.0, "mute": False}}})
    wait(lambda: acked(s), 3)
    l0, l6 = amp_level(0), amp_level(6)
    check("niveau de scène : +6 dB sur un ampli saturé sortent +6 dB (le fader est APRÈS les plugins)",
          l0 is not None and l6 is not None and abs((l6 - l0) - 6.0) < 0.3, f"{l0} -> {l6} dBFS")
    s = eng.send({"action": "mixer_apply", "levels": {"in1": {"db": -9.0, "mute": False}}})
    wait(lambda: acked(s), 3)


# ── lot 3 : le MÉTRONOME (docs/ardour-plan.md §7d) — il compte et sonne transport arrêté, sur sa propre route ─────────
def clock_bench(eng, check, wait, acked):
    """L'horloge MIDI (golem_clock.lua du moteur) : sa piste existe dès le démarrage et ses tics sortent à 24 par noire
    au tempo du moteur, TRANSPORT ARRÊTÉ. Le lien vers la sortie d'un clavier ne se prouve que sur une vraie carte."""
    def st():
        return (eng._status() or {}).get("midi_clock") or {}

    # LE TÉMOIN DU FIL AUDIO (presets/.clock.json, lu par monitors._audio_alive) : la table de l'horloge MIDI portait le
    # nom de son chemin et l'écrasait — plus de témoin, plus de détection d'un son coupé (rack muet une nuit, 2026-11-18)
    from bridge import config as C

    def witness():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".clock.json")))
        except (OSError, ValueError):
            return {}
    w1 = wait(lambda: witness().get("ticks") and witness(), 6) or {}
    time.sleep(1.6)
    w2 = witness()
    check("témoin du fil audio : écrit chaque seconde, ses tics avancent", bool(w1) and (w2.get("ticks") or 0) > (w1.get("ticks") or 0)
          and w2.get("t") != w1.get("t"), f"{w1} -> {w2}")
    a = wait(lambda: st().get("ticks") and eng._status(), 8) or {}
    check("horloge MIDI : sa piste existe et elle tourne dès le démarrage", bool((a.get("midi_clock") or {}).get("ticks")),
          json.dumps(a.get("midi_clock")))
    b = wait(lambda: (eng._status() or {}).get("at", 0) >= a.get("at", 0) + 6 and eng._status(), 12) or {}
    ca, cb = a.get("midi_clock") or {}, b.get("midi_clock") or {}
    dt, bpm = (b.get("at") or 0) - (a.get("at") or 0), cb.get("bpm") or 0
    got, want = (cb.get("ticks") or 0) - (ca.get("ticks") or 0), dt * bpm * 24 / 60
    # `at` est à la seconde près des deux côtés : ±1 s sur l'intervalle
    check("horloge MIDI : 24 tics par noire au tempo du moteur, transport arrêté",
          bpm > 0 and dt >= 6 and not b.get("rolling") and abs(got - want) <= bpm * 24 / 60 * 1.2,
          f"{got} tics en {dt} s à {bpm} BPM (attendu {want:.0f})")


def click_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge import silence

    def state():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".click.json")))
        except (OSError, ValueError):
            return {}

    def send(**kw):
        s = eng.send({"action": "click", "op": "set", **kw})
        wait(lambda: acked(s), 3)
        time.sleep(0.7)                                   # l'état est publié deux fois par seconde
        return state()

    def loud():
        silence._probe({"action": "peaks", "clear": True}, silence.PEAKS(), timeout=4)
        time.sleep(1.2)
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        rows = {r["track"].split(" ", 1)[1]: r for r in (json.loads(txt) if txt else [])}
        return (rows.get("golem:click") or {}).get("max", -150)

    st = wait(lambda: state().get("present") and state(), 5) or {}
    check("click : sa route existe dès le démarrage, éteint", st.get("present") is True and st.get("on") is False, json.dumps(st))
    time.sleep(1.0)
    quiet = loud()
    st = send(on=True, level=-6, beats=7, den=8, groups=[3, 2, 2], div=1, out="1-2")
    check("click : la commande est prise (7/8 en 3+2+2, -6 dB, sortie 1-2)",
          st.get("on") is True and st.get("beats") == 7 and st.get("den") == 8 and st.get("level") == -6 and st.get("out") == "1-2",
          json.dumps(st))
    t0, n0 = time.time(), state().get("ticks", 0)
    lv = loud()
    time.sleep(2.0)
    t1, n1, tempo = time.time(), state().get("ticks", 0), state().get("tempo") or 0
    # une pulsation = une croche (den 8) : tempo × 2 pas par minute ; l'état n'est lu qu'à 0,5 s près
    want = (t1 - t0) * tempo * 2 / 60
    check("click : il compte au tempo du moteur, transport arrêté (croches)", tempo > 0 and abs((n1 - n0) - want) <= tempo / 60 + 1.5,
          f"{n1 - n0} pas en {t1 - t0:.1f} s à {tempo} BPM (attendu {want:.1f})")
    check("click : il SONNE sur sa route, et se taisait avant", lv > -20 and quiet < -80, f"{lv:.1f} dBFS, avant {quiet:.1f}")
    st = send(on=False, clock=True)
    n0 = st.get("ticks", 0)
    silent = loud()
    n1 = state().get("ticks", 0)
    check("click : horloge muette — il compte toujours, sans un son", n1 > n0 and silent < -80, f"{n1 - n0} pas, {silent:.1f} dBFS")
    st = send(clock=False, level=-12)
    n0 = state().get("ticks", 0)
    time.sleep(1.2)
    check("click : éteint, il ne compte plus ; un champ absent garde sa valeur (7/8)",
          state().get("ticks", 0) == n0 and st.get("beats") == 7 and st.get("on") is False, json.dumps(st))


# ── lot 3 : la BOÎTE À RYTHMES (docs/ardour-plan.md §7d) — les grooves d'usine joués par un kit, transport arrêté ────
def drums_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge import silence
    from bridge.engine import ardour as A
    grooves = [os.path.join(ROOT, "library", "factory", "grooves", n) for n in ("golem-funk-16.mid", "golem-half-time.mid")]
    if not all(os.path.isfile(g) for g in grooves):
        check("boîte à rythmes : grooves d'usine présents", False)
        return

    def state():
        try:
            return (json.load(open(os.path.join(C.PRESETS_DIR, ".drums.json"))).get("blocks") or {}).get("bench") or {}
        except (OSError, ValueError):
            return {}

    def send(**kw):
        cmd = {"action": "drums", "block": "bench", **kw}
        if kw.get("op") == "play":                       # le chemin réel : l'adaptateur joint la banque et le kit
            cmd = A.drums_play(cmd, root=ROOT, out_dir=os.path.join(C.ROOT, "reaper", "FXChains"))
            s = __import__("bridge.commands", fromlist=["x"]).enqueue(cmd)
        else:
            s = eng.send(cmd)
        wait(lambda: acked(s), 8)
        time.sleep(0.8)
        return state()

    def loud(seconds=1.5):
        silence._probe({"action": "peaks", "clear": True}, silence.PEAKS(), timeout=4)
        time.sleep(seconds)
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        rows = {r["track"].split(" ", 1)[1]: r for r in (json.loads(txt) if txt else [])}
        return (rows.get("golem:drums") or {}).get("max", -150)

    os.makedirs(os.path.join(C.ROOT, "reaper", "FXChains"), exist_ok=True)
    quiet = loud(0.6)
    st = send(op="play", kit="drums-black-pearl", patterns=grooves, fills=[grooves[1]], idx=0)
    time.sleep(1.0)                                       # le kit charge ses samples
    lv = loud()
    check("boîte à rythmes : un groove d'usine joue dans un kit AVL, transport arrêté",
          st.get("playing") is True and st.get("idx") == 0 and lv > -40 and quiet < -80, f"{json.dumps(st)} {lv:.1f} dBFS, avant {quiet:.1f}")
    send(op="variation", idx=1)
    st = wait(lambda: state().get("idx") == 1 and state(), 8) or state()
    check("boîte à rythmes : la variation prend à la barre", st.get("idx") == 1 and st.get("playing") is True, json.dumps(st))
    send(op="fill", fill_idx=0)
    seen = wait(lambda: state().get("mode") == "fill", 8)
    back = wait(lambda: state().get("mode") == "groove" and state().get("idx") == 1, 12)
    check("boîte à rythmes : le fill joue une fois puis rend la main au groove", bool(seen) and bool(back), json.dumps(state()))
    st = send(op="stop")
    time.sleep(2.5)
    off = loud(1.0)
    check("boîte à rythmes : stop — plus rien ne joue", st.get("playing") is False and off < -60, f"{json.dumps(st)} {off:.1f} dBFS")
    st = send(op="play", kit="pads-house", patterns=grooves[:1], fills=[], idx=0,
              sequence=[{"i": 0, "times": 1}], seq_mode="once")
    lv = loud(1.0)
    ended = wait(lambda: state().get("playing") is False, 20)
    check("boîte à rythmes : un kit de samples (SFZ écrit par golem) joue un morceau d'une étape, une fois, puis se tait",
          lv > -40 and bool(ended), f"{lv:.1f} dBFS, fini : {bool(ended)} {json.dumps(state())}")
    # sa tranche au MIXER, et sa place dans une PRISE (le métronome, lui, n'y entre jamais)
    send(op="play", kit="drums-black-pearl", patterns=grooves, fills=[], idx=0)
    time.sleep(1.0)
    s = eng.send({"action": "click", "op": "set", "on": True, "level": 0})
    wait(lambda: acked(s), 3)
    with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
        json.dump({"in1": False, "mode": "tracks", "mix": True}, f)

    def take():
        def perf():
            try:
                return json.load(open(os.path.join(C.PRESETS_DIR, ".perf.json")))
            except (OSError, ValueError):
                return {}
        s1 = eng.send({"action": "perf_rec", "on": True})
        wait(lambda: acked(s1) and perf().get("recording") is True, 8)
        time.sleep(2.0)
        s1 = eng.send({"action": "perf_rec", "on": False})
        wait(lambda: acked(s1) and perf().get("recording") is False, 20)
        d = os.path.join(C.ROOT, perf().get("file") or "missing")
        return {n: wav_info(os.path.join(d, n))[2] for n in (sorted(os.listdir(d)) if os.path.isdir(d) else [])}

    t1 = take()
    check("prise : la boîte à rythmes a sa piste et entre dans le mix ; le métronome, qui sonne, n'y est pas",
          set(t1) == {"Drums.wav", "Mix.wav"} and t1.get("Drums.wav", -150) > -40 and abs(t1["Mix.wav"] - t1["Drums.wav"]) < 0.5, str(t1))
    s = eng.send({"action": "mixer_apply", "levels": {"drums": {"db": -12.0, "mute": False}, "in1": {"db": -9.0, "mute": False}}})
    wait(lambda: acked(s), 3)
    t2 = take()
    check("mixer : la tranche « drums » baisse la boîte à rythmes de 12 dB (dans la prise aussi)",
          "Drums.wav" in t2 and abs((t1.get("Drums.wav", 0) - t2["Drums.wav"]) - 12) < 1.5, f"{t1.get('Drums.wav')} -> {t2.get('Drums.wav')}")
    s = eng.send({"action": "mixer_apply", "levels": {"drums": {"db": 0.0, "mute": False}, "in1": {"db": -9.0, "mute": False}}})
    wait(lambda: acked(s), 3)
    s = eng.send({"action": "click", "op": "set", "on": False})
    wait(lambda: acked(s), 3)
    send(op="stop")
    st = send(op="play", kit="drums-aasimonster", patterns=grooves[:1], fills=[], idx=0)
    check("boîte à rythmes : un kit DrumGizmo n'est pas joué ici, et c'est dit (le séquenceur tourne quand même)",
          st.get("playing") is True, json.dumps(st))
    send(op="stop")


# ── lot 3 : les STANDARDS (docs/ardour-plan.md §7d) — une grille rendue, jouée par une piste par partie ───────────────
def standard_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge import silence
    PPQ, BAR = 960, 3840
    ev = []
    for bar in range(2):                                  # deux mesures : un accord, une basse en noires, charleston, pompe, click
        t0 = bar * BAR
        ev += [(t0, n, 80, 0) for n in (52, 55, 59)] + [(t0 + BAR - 60, n, 0, 0) for n in (52, 55, 59)]
        for beat in range(4):
            t = t0 + beat * PPQ
            ev += [(t, 40, 100, 1), (t + 900, 40, 0, 1), (t, 42, 90, 2), (t, 52, 90, 4), (t + 400, 52, 0, 4),
                   (t, 76 if beat == 0 else 77, 100, 3)]
    ev.sort()
    seq = os.path.join(C.PRESETS_DIR, ".standard.seq")
    with open(seq, "w", encoding="utf-8") as f:
        f.write("v 1\nlen %d\nbar %d\ncin 0\nnev %d\n" % (2 * BAR, BAR, len(ev)) + "".join("%d %d %d %d\n" % e for e in ev))

    def state():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".standard.json")))
        except (OSError, ValueError):
            return {}

    def send(**kw):
        cmd = {"action": "standard", **kw}
        if kw.get("op") == "play":                       # le chemin réel : l'adaptateur nomme le piano et la pompe du dépôt
            from bridge.engine import ardour as A
            cmd["instruments"] = A.standard_instruments(ROOT)
            s = __import__("bridge.commands", fromlist=["x"]).enqueue(cmd)
        else:
            s = eng.send(cmd)
        wait(lambda: acked(s), 30)
        time.sleep(0.8)
        return state()

    def levels(seconds=2.5):
        silence._probe({"action": "peaks", "clear": True}, silence.PEAKS(), timeout=4)
        time.sleep(seconds)
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        return {r["track"].split(" ", 1)[1].replace("golem:", ""): round(r.get("max", -150), 1) for r in (json.loads(txt) if txt else [])}

    st = wait(lambda: state().get("present") and state(), 5) or {}
    check("standards : le lecteur est là dès le démarrage, à l'arrêt", st.get("present") is True and st.get("playing") is False, json.dumps(st))
    s = eng.send({"action": "click", "op": "set", "on": True, "level": -6, "beats": 4, "den": 4, "div": 1})
    wait(lambda: acked(s), 3)
    st = send(op="play", standard="bench-chart", file=seq, loop=True, keys=True, bass=True, drums=True, guitar=True, kit="black-pearl")
    time.sleep(6.0)                                       # le piano et la pompe chargent leurs samples
    lv = levels()
    st = state()
    parts = {k: lv.get("std:" + k, -150) for k in ("keys", "bass", "drums", "guitar")}
    check("standards : la grille joue, mesures comptées", st.get("playing") is True and st.get("standard") == "bench-chart"
          and st.get("bars") == 2 and st.get("events") == len(ev) and st.get("bar") in (0, 1), json.dumps(st))
    # la pompe joue Shinyguitar, un téléchargement FACULTATIF de l'installateur (installer/desktop_steps.py) : absent, sa
    # piste se tait sous REAPER comme ici — ce n'est pas le moteur qu'on juge, le détail le dit (2026-11-19, poste Windows)
    shiny = os.path.isdir(os.path.join(ROOT, "library", "sfz", "Shinyguitar"))
    judged = {k: v for k, v in parts.items() if shiny or k != "guitar"}
    check("standards : les QUATRE parties sonnent, chacune sur sa piste (piano, basse, batterie, pompe)",
          all(v > -60 for v in judged.values()),
          str(parts) + ("" if shiny else " — pompe non jugée : Shinyguitar n'est pas installé (téléchargement de l'installateur)"))
    check("standards : le click est JOUÉ par la grille (ses temps arrivent en MIDI)", lv.get("click", -150) > -30, str(lv.get("click")))
    st = send(op="play", standard="bench-chart", file=seq, loop=True, keys=False, bass=True, drums=False, guitar=False)
    time.sleep(1.5)
    lv = levels(2.0)
    check("standards : une partie non demandée se TAIT (basse seule)",
          lv.get("std:bass", -150) > -60 and all(lv.get("std:" + k, 0) < -80 for k in ("keys", "drums", "guitar")), str(lv))
    st = send(op="stop")
    time.sleep(1.5)
    lv = levels(1.5)
    check("standards : stop — plus rien ne joue, aucune note tenue", st.get("playing") is False
          and all(lv.get("std:" + k, 0) < -60 for k in ("keys", "bass", "drums", "guitar")), f"{json.dumps(st)} {lv}")
    tk0 = (json.load(open(os.path.join(C.PRESETS_DIR, ".click.json"))) or {}).get("ticks", 0)
    time.sleep(2.0)
    tk1 = (json.load(open(os.path.join(C.PRESETS_DIR, ".click.json"))) or {}).get("ticks", 0)
    check("standards : la grille arrêtée, le click reprend son propre compteur", tk1 > tk0, f"{tk1 - tk0} pas en 2 s")
    send(op="play", standard="bench-chart", file=seq, loop=False, keys=False, bass=True, drums=False, guitar=False)
    ended = wait(lambda: state().get("playing") is False, 15)
    check("standards : sans boucle, la grille s'arrête seule à la fin", bool(ended), json.dumps(state()))
    s = eng.send({"action": "click", "op": "set", "on": False})
    wait(lambda: acked(s), 3)


# ── lot 3 : l'ACCORDEUR (docs/ardour-plan.md §7d) — il lit le sinus de la carte factice sur l'entrée qu'on lui nomme ──
def tuner_bench(eng, check, wait, acked):
    from bridge import config as C

    def state():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".tuner.json")))
        except (OSError, ValueError):
            return {}

    def send(**kw):
        s = eng.send(kw)
        wait(lambda: acked(s), 3)

    send(action="tuner", on=True)
    st = wait(lambda: state().get("active") and state(), 6) or state()
    # l'entrée 1 de la carte factice : 1000 Hz × 2^(-4/3) = 396,85 Hz, un sol 4 trop haut de 21 cents
    check("accordeur : il lit la note de l'entrée 1 (396,85 Hz : sol 4, +21 cents)",
          st.get("on") is True and st.get("note") == "G" and st.get("octave") == 4 and abs((st.get("freq") or 0) - 396.85) < 0.5
          and abs((st.get("cents") or 0) - 21) < 2, json.dumps(st))
    send(action="extstate", key="tuner_in", value="2")
    time.sleep(1.5)
    st = state()
    # l'entrée 2 : 1000 Hz × 2^(-1) = 500 Hz, un si 4 trop haut de 21 cents
    check("accordeur : on lui nomme une autre entrée, il la lit (500 Hz : si 4)",
          st.get("active") is True and st.get("note") == "B" and abs((st.get("freq") or 0) - 500.0) < 0.6, json.dumps(st))
    seq0 = st.get("seq")
    time.sleep(1.0)
    check("accordeur : la lecture est vivante (de nouvelles analyses arrivent)", (state().get("seq") or 0) > (seq0 or 0))
    send(action="tuner", on=False)
    time.sleep(0.5)
    check("accordeur : coupé, il le dit", state() == {"on": False, "active": False, "seq": 0}, json.dumps(state()))
    send(action="extstate", key="tuner_in", value="1")


# ── lot 3 : la BACKING (docs/ardour-plan.md §7d) — les stems d'une chanson joués par le transport ────────────────────
def backing_bench(eng, check, wait, acked):
    import glob
    from bridge import config as C
    from bridge import silence
    dirs = [d for d in sorted(glob.glob(os.path.join(ROOT, "assets", "backing", "*"))) if os.path.isfile(os.path.join(d, "drums.mp3"))]
    if not dirs:
        check("backing : une chanson à six stems présente (assets/backing)", False)
        return
    song = dirs[0]

    def state():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".backing.json")))
        except (OSError, ValueError):
            return {}

    def send(**kw):
        cmd = {"action": "backing", **kw}
        if kw.get("op") == "load":                       # le chemin réel : l'adaptateur décode les stems dans son cache
            from bridge.engine import ardour as A
            cmd = A.backing_load(cmd, cache_dir=os.path.join(C.ROOT, "assets", ".cache", "backing-wav"))
            s = __import__("bridge.commands", fromlist=["x"]).enqueue(cmd)
        else:
            s = eng.send(cmd)
        wait(lambda: acked(s), 15)
        time.sleep(0.5)
        return state()

    def level(row="golem:backing", seconds=1.0):
        silence._probe({"action": "peaks", "clear": True}, silence.PEAKS(), timeout=4)
        time.sleep(seconds)
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        return {r["track"].split(" ", 1)[1]: r for r in (json.loads(txt) if txt else [])}.get(row, {}).get("max", -150)

    t0 = time.time()
    st = send(op="load", slug="bench-song", dir=song, mix={"vocals": {"mute": 1, "vol": 1}})
    check("backing : une chanson de six stems mp3 se charge (posés, pas importés)",
          st.get("present") is True and st.get("slug") == "bench-song" and (st.get("len") or 0) > 30
          and st["stems"]["vocals"]["mute"] == 1 and st["stems"]["drums"]["mute"] == 0 and st.get("playing") is False,
          f"{time.time() - t0:.1f} s — len {st.get('len')} {json.dumps(st.get('stems'))[:90]}")
    eng.transport("play")
    time.sleep(1.0)
    p1 = state().get("pos") or 0
    lv = level()
    p2 = state().get("pos") or 0
    check("backing : le transport la joue (la position avance, le bus sonne)", state().get("playing") is True and p2 > p1 + 0.5 and lv > -60,
          f"{p1:.2f} -> {p2:.2f} s, {lv:.1f} dBFS")
    send(op="seek", pos=60.0)
    time.sleep(0.6)
    p = state().get("pos") or 0
    check("backing : seek en lecture", 60.0 <= p < 63.0 and state().get("playing") is True, f"{p:.2f} s")
    send(op="loop", a=20.0, b=21.5)
    seen = []
    for _ in range(14):
        time.sleep(0.3)
        seen.append(state().get("pos") or 0)
    check("backing : boucle A/B — la lecture reste entre 20 et 21,5 s", all(19.9 <= x <= 21.6 for x in seen) and state()["loop"]["on"] is True
          and max(seen) - min(seen) > 0.5, str([round(x, 1) for x in seen]))
    send(op="loop", off=1)
    time.sleep(2.5)
    p = state().get("pos") or 0
    check("backing : boucle levée, la lecture continue au-delà", p > 21.6 and state()["loop"]["on"] is False, f"{p:.2f} s")
    send(op="seek", pos=40.0)
    time.sleep(0.5)
    send(op="jump", at=42.0, to=30.0)                     # saut ARRIÈRE : à 42 s, on reprend à 30 s
    wait(lambda: 30.0 <= (state().get("pos") or 0) < 34.0, 6)
    time.sleep(3.5)
    p = state().get("pos") or 0
    check("backing : saut de section vers l'arrière, fait une fois (la lecture ne reboucle pas)", 33.0 < p < 40.0, f"{p:.2f} s")
    send(op="jump", at=p + 1.5, to=100.0)                 # saut AVANT
    ok = wait(lambda: 100.0 <= (state().get("pos") or 0) < 104.0, 6)
    check("backing : saut de section vers l'avant", bool(ok), f"{state().get('pos')}")
    send(op="mix", stem="drums", mute=1)
    send(op="mix", stem="bass", vol=0.5)
    st = state()
    check("backing : le mix d'un stem (mute, volume)", st["stems"]["drums"]["mute"] == 1 and abs(st["stems"]["bass"]["vol"] - 0.5) < 0.01,
          json.dumps(st["stems"])[:120])
    # une PRISE pendant que la backing joue : elle se greffe sur le transport sans le ramener au début
    with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
        json.dump({"in1": False, "mode": "tracks", "mix": True}, f)
    before = state().get("pos") or 0
    s = eng.send({"action": "perf_rec", "on": True})

    def perf():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".perf.json")))
        except (OSError, ValueError):
            return {}
    wait(lambda: acked(s) and perf().get("recording") is True, 8)
    time.sleep(2.0)
    during = state().get("pos") or 0
    s = eng.send({"action": "perf_rec", "on": False})
    wait(lambda: acked(s) and perf().get("recording") is False, 20)
    d = os.path.join(C.ROOT, perf().get("file") or "missing")
    files = {n: wav_info(os.path.join(d, n)) for n in (sorted(os.listdir(d)) if os.path.isdir(d) else [])}
    bt = files.get("Backing-Track.wav", (0, 0, -150))
    check("prise + backing : la prise ne ramène pas la chanson au début, et la backing a sa piste dans la prise",
          during > before + 1.0 and bt[0] == 2 and bt[2] > -60 and 1.5 < bt[1] < 4.0, f"{before:.1f} -> {during:.1f} s ; {files.get('Backing-Track.wav')}")
    eng.transport("stop")
    eng.transport("start")
    time.sleep(1.0)
    st = state()
    check("backing : arrêt et retour au début", st.get("playing") is False and (st.get("pos") or 0) < 0.1 and st.get("paused") is False, json.dumps(st)[:100])
    send(op="seek", pos=(st.get("len") or 0) - 1.5)
    ends0 = state().get("ends", 0)
    eng.transport("play")
    done = wait(lambda: state().get("ends", 0) == ends0 + 1 and state().get("playing") is False, 8)
    check("backing : fin de chanson — arrêt, retour au début, fin comptée", bool(done) and (state().get("pos") or 0) < 0.1, json.dumps(state())[:120])
    st = send(op="unload")
    check("backing : déchargée", st.get("present") is False, json.dumps(st))


# ── lot 3 : l'ÉCOUTE SANS JOUER (docs/ardour-plan.md §7d) — une phrase jouée dans la lane, sa sortie enregistrée ─────
def preview_bench(eng, check, wait, acked):
    import subprocess
    from bridge import config as C
    from bridge.engine import ardour_plan
    out_dir = os.path.join(C.ROOT, "previews")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.dirname(ardour_plan.rig_path(BENCH_ID)), exist_ok=True)
    from bridge import mixer
    mixer.MIXER_FILE = os.path.join(C.ROOT, "config", "mixer.json")     # les trims du banc, jamais ceux du rack
    os.makedirs(os.path.dirname(mixer.MIXER_FILE), exist_ok=True)
    with open(mixer.MIXER_FILE, "w", encoding="utf-8") as f:
        json.dump({"levels": {"in1": {"db": -9.0, "mute": False}}}, f)

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return None

    def render(**kw):
        p = os.path.join(C.PRESETS_DIR, ".preview.json")
        if os.path.exists(p):
            os.remove(p)
        s = eng.send({"action": "preview", "op": "render", "tail": 0.6, **kw})
        wait(lambda: acked(s), 8)
        return wait(lambda: (read(".preview.json") or {}).get("done") and read(".preview.json"), 30) or {}

    def tone(path):
        """La fréquence dominante d'un fichier (Hz) : dit QUELLE source a été rendue."""
        import numpy as np
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                             capture_output=True).stdout
        x = np.frombuffer(raw, dtype="<f4")[4800:4800 + 32768]
        if len(x) < 32768:
            return 0.0
        sp = abs(np.fft.rfft(x * np.hanning(len(x))))
        return float(np.fft.rfftfreq(len(x), 1 / 48000)[int(sp.argmax())])

    def dump():
        p = os.path.join(C.PRESETS_DIR, ".engine-dump.json")
        if os.path.exists(p):
            os.remove(p)
        s = eng.send({"action": "dump"})
        return wait(lambda: acked(s) and read(".engine-dump.json"), 5) or {}

    # une DI de banc : 2 s d'un la à 220 Hz — rien à voir avec le 397 Hz que la carte factice joue sur l'entrée 1
    di = os.path.join(out_dir, "di.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=2:sample_rate=48000",
                    "-af", "volume=-12dB", "-ac", "1", di], check=True)
    with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
        json.dump(bench_rig("A"), f)
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == BENCH_ID, 30)
    time.sleep(1.5)
    wav = os.path.join(out_dir, "A.wav")
    st = render(scene="A", di=di, out=wav, chain="Sandbox #Input 1")
    info = wav_info(wav) if os.path.isfile(wav) else (0, 0, -150)
    f0 = tone(wav) if os.path.isfile(wav) else 0
    check("écoute : la DI est rendue à travers la lane (un fichier stéréo de la durée de la phrase et de sa queue)",
          st.get("done") is True and not st.get("error") and st.get("wav") == wav and info[0] == 2 and 2.3 < info[1] < 3.6 and info[2] > -70,
          f"{json.dumps(st)[:120]} {info}")
    check("écoute : c'est la DI qu'on entend (220 Hz), pas l'entrée de la carte (397 Hz)", abs(f0 - 220) < 5 or abs(f0 - 660) < 8, f"{f0:.0f} Hz")
    time.sleep(1.0)
    d = dump()
    tr = {x["name"]: x for x in d.get("tracks") or []}
    merge, pre = tr.get("GoleM:bench#merge") or {}, tr.get("GoleM:bench") or {}
    check("écoute : ensuite la lane a retrouvé la carte (entrée, sorties, clé du gate) et son trim de mixer",
          any(c.endswith("capture_1") for c in pre.get("input") or []) and sorted(c.rsplit("_", 1)[-1] for c in merge.get("output") or []) == ["1", "2"]
          and all(c.endswith("capture_1") for c in ((d.get("blocks") or {}).get("met") or {}).get("key") or ["x"])
          and abs((merge.get("gain_db") or 0) + 9) < 0.1 and len(tr) == 4,
          f"entrée {pre.get('input')} sorties {merge.get('output')} fader {merge.get('gain_db')} routes {sorted(tr)}")
    st = render(scene="A", out=os.path.join(out_dir, "x.wav"), chain="Sandbox #Input 1", tracks={"x": 1}, di=di)
    check("écoute : un rendu qui n'est pas encore sur ce moteur le DIT tout de suite (le bridge n'attend pas pour rien)",
          st.get("done") is True and "not on the Golem Engine yet" in (st.get("error") or ""), json.dumps(st))

    # une PHRASE MIDI dans une lane de clavier (l'orgue) : deux notes, jouées sans personne au clavier
    with open(ardour_plan.rig_path(KEYS_ID), "w", encoding="utf-8") as f:
        json.dump(keys_rig({"id": "bench-organ", "type": "organ", "params": {"db16": 8, "db8": 8}}), f)
    s = eng.send({"action": "rig_recall", "preset": KEYS_ID, "scene": "A"})
    wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == KEYS_ID, 40)
    time.sleep(2.5)
    mid = os.path.join(out_dir, "A.midi.txt")
    with open(mid, "w", encoding="utf-8") as f:
        f.write("len 1.800000\nn 0.200000 0.900000 0 57 100\nn 1.000000 1.700000 0 60 100\n")
    wav = os.path.join(out_dir, "K.wav")
    st = render(scene="A", midi=mid, di=mid, out=wav, chain="Sandbox #Input 3")
    info = wav_info(wav) if os.path.isfile(wav) else (0, 0, -150)
    check("écoute : une phrase MIDI est jouée par l'instrument de la lane et rendue", st.get("done") is True and not st.get("error")
          and info[0] == 2 and 2.0 < info[1] < 3.4 and info[2] > -40, f"{json.dumps(st)[:120]} {info}")
    time.sleep(1.0)
    d = dump()
    check("écoute : ensuite le lecteur de phrase a quitté la lane (zone, arpégiateur et orgue seulement)",
          set(d.get("blocks") or {}) == {"bench-organ", "bench-organ~zone", "bench-organ~arp"} and len(d.get("tracks") or []) == 1,
          f"{sorted(d.get('blocks') or {})} {[x['name'] for x in d.get('tracks') or []]}")
    # LE RENDU D'UN BLOC DE SERVICE : une phrase de batterie jouée dans la piste vivante de la boîte à rythmes
    from bridge.engine import ardour as A
    # le chemin réel : l'adaptateur joint le plugin du kit (ici lu dans le dépôt, la racine du banc n'a pas de kits)
    s = __import__("bridge.commands", fromlist=["x"]).enqueue(A.drums_play(
        {"action": "drums", "op": "load", "block": "library", "kit": "drums-black-pearl"}, root=ROOT,
        out_dir=os.path.join(C.ROOT, "reaper", "FXChains")))
    wait(lambda: acked(s), 10)
    time.sleep(1.5)
    dm = os.path.join(out_dir, "drums.midi.txt")
    with open(dm, "w", encoding="utf-8") as f:
        f.write("len 1.500000\n" + "".join(f"n {t:.6f} {t + 0.1:.6f} 9 {n} 110\n" for t, n in ((0.1, 36), (0.5, 38), (0.9, 36), (1.3, 38))))
    wav = os.path.join(out_dir, "D.wav")
    st = render(scene="block-1-drums", out=wav, chains="Drums", midis=dm, strip="drumseq")
    info = wav_info(wav) if os.path.isfile(wav) else (0, 0, -150)
    check("écoute : un bloc de service (la boîte à rythmes) est rendu — sa phrase jouée par son kit, dans sa piste",
          st.get("done") is True and not st.get("error") and info[0] == 2 and 1.6 < info[1] < 3.2 and info[2] > -40,
          f"{json.dumps(st)[:120]} {info}")
    # LE BANC CPU : la DI jouée dans la lane, et ce que ses plugins ont coûté par buffer (les compteurs du moteur)
    with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
        json.dump(bench_rig("A"), f)
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == BENCH_ID, 30)
    time.sleep(1.5)
    st = render(scene="cpu-1", di=di, out=os.path.join(out_dir, "cpu.wav"), chain="Sandbox #Input 1", bench=3, tail=0.25)
    check("écoute : le banc CPU rend ce que la lane a coûté par buffer (moyenne, pire, nombre de plugins, buffer du moteur)",
          st.get("done") is True and (st.get("avg_us") or 0) > 0 and (st.get("worst_us") or 0) >= st.get("avg_us", 9e9)
          and (st.get("nfx") or 0) >= 3 and st.get("bsize") and st.get("srate") == 48000, json.dumps(st)[:260])


# ── lot 3 : les SAMPLES (docs/ardour-plan.md §7d) — des sons lancés par commande, coupés, enchaînés ─────────────────────
def sample_bench(eng, check, wait, acked):
    import subprocess
    from bridge import config as C
    from bridge import silence
    from bridge.engine import ardour as A
    d = os.path.join(C.ROOT, "samples")
    os.makedirs(d, exist_ok=True)
    files = []
    for name, freq, dur in (("long", 330, 4.0), ("short", 550, 0.6)):
        f = os.path.join(d, name + ".wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}:duration={dur}:sample_rate=48000", "-af", "volume=-6dB", "-ac", "2", f], check=True)
        files.append(f)

    def state():
        try:
            return (json.load(open(os.path.join(C.PRESETS_DIR, ".sample.json"))).get("blocks") or {}).get("bench") or {}
        except (OSError, ValueError):
            return {}

    def send(cmd):
        if cmd.get("op") == "play":                      # le chemin réel : l'adaptateur donne chemins absolus et durées
            cmd = A.sample_play(cmd, root=C.ROOT)
        if cmd.get("action") == "sample_preview" and cmd.get("file"):
            cmd = {**cmd, "dur": A.audio_seconds(cmd["file"])}
        s = __import__("bridge.commands", fromlist=["x"]).enqueue(cmd)
        wait(lambda: acked(s), 5)

    def level(seconds=0.8):
        silence._probe({"action": "peaks", "clear": True}, silence.PEAKS(), timeout=4)
        time.sleep(seconds)
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        return {r["track"].split(" ", 1)[1]: r for r in (json.loads(txt) if txt else [])}.get("golem:sample", {}).get("max", -150)

    quiet = level(0.4)
    send({"action": "sample", "op": "play", "block": "bench", "idx": 0, "samples": files})
    time.sleep(0.8)
    lv, st = level(), state()
    check("samples : un son lancé joue (le premier de la liste)", st.get("playing") is True and st.get("idx") == 0 and lv > -60 and quiet < -80,
          f"{json.dumps(st)} {lv:.1f} dBFS, avant {quiet:.1f}")
    # son NIVEAU, lu dans une prise (le vumètre du moteur n'est pas une mesure) : le fichier est à -6 dBFS
    with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
        json.dump({"in1": False, "mode": "tracks", "mix": True}, f)

    def perf():
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, ".perf.json")))
        except (OSError, ValueError):
            return {}
    s1 = eng.send({"action": "perf_rec", "on": True})
    wait(lambda: acked(s1) and perf().get("recording") is True, 8)
    time.sleep(0.4)
    held = level(0.5)                                     # le son lancé AVANT la prise sonne-t-il encore ?
    send({"action": "sample", "op": "play", "block": "bench", "idx": 0, "samples": files})
    time.sleep(1.2)
    s1 = eng.send({"action": "perf_rec", "on": False})
    wait(lambda: acked(s1) and perf().get("recording") is False, 20)
    tk = os.path.join(C.ROOT, perf().get("file") or "missing", "Sample.wav")
    got = wav_info(tk) if os.path.isfile(tk) else (0, 0, -150)
    typ = wav_typical_peak(tk) if os.path.isfile(tk) else -150.0
    ref = wav_info(files[0])[2]
    # crête TYPIQUE, pas la crête globale : le son est RELANCÉ pendant la prise, l'ancien retombe en 30 ms sous le nouveau
    # et la crête de ce recouvrement dépend de leur phase (mesuré : de 0,0 à +2,7 dB) — ce n'est pas le niveau du son
    check("samples : le son sort au niveau de SON fichier (à 1 dB près), a sa piste dans une prise, et le départ de la prise ne coupe "
          "pas un son qui sonnait", got[0] == 2 and abs(typ - ref) < 1.0 and held > -60,
          f"{got} typique {typ:.1f}, fichier {ref} dBFS, tenu {held:.1f}")
    send({"action": "sample", "op": "stop", "block": "bench"})
    time.sleep(0.6)
    off = level(0.6)
    check("samples : stop le coupe avant sa fin", state().get("playing") is False and off < -60, f"{json.dumps(state())} {off:.1f} dBFS")
    send({"action": "sample", "op": "play", "block": "bench", "idx": 1, "samples": files})
    time.sleep(0.25)
    playing = state().get("playing")
    ended = wait(lambda: state().get("playing") is False, 4)
    check("samples : un son court va au bout et le dit (sa durée vient du bridge)", playing is True and bool(ended) and state().get("idx") == 1,
          json.dumps(state()))
    send({"action": "sample", "op": "play", "block": "bench", "idx": 0, "samples": files, "in_ms": 700})
    time.sleep(0.3)
    early = state().get("playing")
    time.sleep(0.9)
    check("samples : un départ différé (in_ms) attend son heure", early is False and state().get("playing") is True, f"{early} puis {state()}")
    send({"action": "sample", "op": "stop", "block": "bench"})
    time.sleep(0.5)
    send({"action": "sample_preview", "file": files[1], "db": -6})
    time.sleep(0.2)
    pv = level(0.5)
    check("samples : l'écoute d'un son depuis la Library joue, sans toucher à l'état des blocs", pv > -40 and state().get("playing") is False,
          f"{pv:.1f} dBFS {json.dumps(state())}")
    send({"action": "sample_preview", "file": ""})


# ── lot 3 : le LOOPER (docs/looper.md) — quatre boucles nourries par les lanes, pilotées comme sous REAPER ────────────
def looper_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge import silence
    from bridge.engine import ardour_plan
    os.makedirs(os.path.dirname(ardour_plan.rig_path(BENCH_ID)), exist_ok=True)

    def state():
        try:
            return json.load(open(C.LOOPER_FILE))
        except (OSError, ValueError):
            return {}

    def recall():
        rig = bench_rig("A")
        rig["looper"] = {"enabled": True, "loops": [{"sw": 1, "src": "bench"}, {"sw": 2, "src": "1"}, {"sw": 3, "src": "nope"}]}
        with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
            json.dump(rig, f)
        t0 = time.time()
        s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
        wait(lambda: acked(s), 30)
        return wait(lambda: state().get("present") and os.path.getmtime(C.LOOPER_FILE) >= t0 - 1 and state(), 10) or {}

    seq = [0]

    def cmd(note):                                        # le chemin RÉEL : l'OSC de l'adaptateur, à l'adresse publiée
        st = state()
        seq[0] = seq[0] % 127 + 1
        return eng.set_fx_param(st.get("track"), st.get("fx"), st.get("cmd_param"), (seq[0] * 128 + note) / 16383.0)

    def slot(i):
        return (state().get("slots") or [{}] * 4)[i]

    def level(seconds=0.6):
        silence._probe({"action": "peaks", "clear": True}, silence.PEAKS(), timeout=4)
        time.sleep(seconds)
        txt = silence._probe({"action": "peaks", "clear": False}, silence.PEAKS(), timeout=4)
        return {r["track"].split(" ", 1)[1]: r for r in (json.loads(txt) if txt else [])}.get("golem:looper", {}).get("max", -150)

    st = recall()
    time.sleep(1.0)
    check("looper : le preset a un looper — son adresse de commande est publiée après le rappel", st.get("present") is True
          and isinstance(st.get("track"), int) and st.get("fx") == 0 and st.get("cmd_param") == 0, json.dumps(st)[:160])
    ok = cmd(36)
    wait(lambda: slot(0).get("st") == 2, 3)
    rec = dict(state())
    time.sleep(1.2)
    cmd(37)
    wait(lambda: slot(0).get("st") == 1, 3)
    st = state()
    check("looper : rec puis play au pied (OSC) — la première boucle enregistre, se ferme et pose la longueur",
          ok and rec.get("firstrec") == 1 and slot(0).get("has") is True and 1.0 < (st.get("len") or 0) < 1.8 and st.get("firstrec") == 0,
          f"rec {json.dumps(rec)[:110]} puis len {st.get('len')}")
    lv = level()
    check("looper : la boucle JOUE ce que la lane a sorti", lv > -50, f"{lv:.1f} dBFS")
    cmd(41)                                               # la boucle 2 écoute la même lane (src « 1 ») : une couche calée
    wait(lambda: slot(1).get("st") == 2, 3)
    dub = dict(state())
    time.sleep(0.5)
    cmd(42)
    wait(lambda: slot(1).get("st") == 1, 3)
    check("looper : une deuxième boucle de la même lane suit la longueur de la première", dub.get("firstrec") == 0
          and slot(1).get("has") is True and abs((state().get("len") or 0) - (st.get("len") or -1)) < 0.001, json.dumps(state())[:200])
    a = state()
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 3, 0.0)     # « GoleM Loop 1 dB » à -60 : muette
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 4, 0.0)
    time.sleep(0.4)
    muted = level()
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 3, 1.0)
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 4, 1.0)
    time.sleep(0.3)
    back = level()
    check("looper : le niveau de chaque boucle se règle (-60 = muette), sans toucher à ce qui est enregistré",
          muted < -80 and back > -50, f"muettes {muted:.1f}, revenues {back:.1f} dBFS")
    length = state().get("len")
    st = recall()                                          # un rappel reconstruit le rig : les boucles survivent
    time.sleep(1.0)
    lv = level()
    check("looper : les boucles survivent à un rappel et jouent toujours", abs((st.get("len") or 0) - length) < 0.001
          and slot(0).get("has") is True and slot(0).get("st") == 1 and lv > -50, f"{json.dumps(st)[:140]} {lv:.1f} dBFS")
    with open(C.LOOPER_CMD_FILE, "w", encoding="utf-8") as f:   # le secours par fichier (avant que l'adresse soit connue)
        json.dump({"seq": 99, "notes": [37]}, f)
    stopped = wait(lambda: slot(0).get("st") == 0, 3)
    cmd(21)
    allplay = wait(lambda: slot(0).get("st") == 1 and slot(1).get("st") == 1, 3)
    check("looper : la commande par fichier arrête une boucle, « tout jouer » les relance", bool(stopped) and bool(allplay), json.dumps(state())[:160])
    cmd(20)
    wait(lambda: (state().get("len") or 0) == 0, 3)
    st = state()
    check("looper : tout effacer vide les boucles", st.get("len") == 0 and not any(x.get("has") or x.get("st") for x in st.get("slots") or [{"has": 1}]),
          json.dumps(st)[:160])
    # le DÉCOMPTE et le CALAGE : 120 BPM, 4 temps (mesure = 2 s), calage + décompte
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 1, 120 / 400.0)
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 2, 43 / 999.0)
    time.sleep(0.2)
    cmd(36)
    counting = wait(lambda: (state().get("countin") or 0) > 0 and state(), 2) or {}
    started = wait(lambda: slot(0).get("st") == 2, 4)
    time.sleep(1.6)                                       # fermée à 1,6 s : un peu tôt — la boucle attend la barre
    cmd(37)
    time.sleep(0.15)
    early = slot(0).get("st")
    wait(lambda: slot(0).get("st") == 1, 3)
    st = state()
    check("looper : décompte d'une mesure, puis une première boucle calée sur la barre (2,000 s à 120 BPM)",
          counting.get("countin_slot") == 1 and bool(started) and early == 2 and abs((st.get("len") or 0) - 2.0) < 0.001,
          f"décompte {json.dumps(counting)[:90]} · tôt {early} · len {st.get('len')}")
    cmd(20)
    eng.set_fx_param(a.get("track"), a.get("fx"), a.get("cmd_param") + 2, 0.0)
    time.sleep(0.3)


# ── lot 3 : le VST HOST (docs/platforms.md §6.1) — un plugin VST3 installé, hébergé par son nom ──────────────────────
def host_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge.engine import ardour_plan
    os.makedirs(os.path.dirname(ardour_plan.rig_path(BENCH_ID)), exist_ok=True)

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return None

    def ask(cmd, name):
        s = eng.send(cmd)
        return wait(lambda: acked(s) and str((read(name) or {}).get("seq")) == str(s) and read(name), 8) or {}

    lst = ask({"action": "vst_list"}, ".vst-host-list.json")
    rows = lst.get("plugins") or []
    mine = [r for r in rows if "golem" in r["name"].lower() and r["name"].startswith("VST3:")]
    check("vst host : l'inventaire des plugins VST3 du moteur, nommés comme sous REAPER", len(rows) > 0 and bool(mine)
          and all(r["name"].startswith(("VST3: ", "VST3i: ")) and r.get("ident") for r in rows), f"{len(rows)} plugin(s), ex. {rows[:2]}")
    if not mine:
        return
    name = mine[0]["name"]

    K = [0]                                               # le rang du potard choisi (un réglage continu)

    def recall(value):
        rig = bench_rig("A")
        merge = next(t for t in rig["paths"][0]["tracks"] if t["role"] == "merge")
        merge["blocks"].append({"id": "hosted", "type": "vst-host", "plugin": name, "knobs": [{"i": K[0], "name": ""}],
                                "params": {f"p{K[0]}": value}})
        with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
            json.dump(rig, f)
        s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
        wait(lambda: acked(s) and "hosted" in ((read(".livemap.json") or {}).get("blocks") or {}), 30)
        time.sleep(0.6)
        return (read(".livemap.json") or {}).get("blocks", {}).get("hosted") or {}

    recall(0.5)
    pr = ask({"action": "vst_params", "block": "hosted"}, ".vst-host-params.json")
    K[0] = next((p["i"] for p in pr.get("params") or [] if not p.get("toggle") and not p.get("step")), 0)
    lm = recall(0.25)
    pr = ask({"action": "vst_params", "block": "hosted"}, ".vst-host-params.json")
    p0 = next((p for p in pr.get("params") or [] if p.get("i") == K[0]), {})
    check(f"vst host : « {name} » est posé dans le rig par son nom, son potard choisi est dans le livemap",
          lm.get("type") == "vst-host" and f"p{K[0]}" in (lm.get("params") or {}), json.dumps(lm)[:160])
    check("vst host : les vrais paramètres de l'instance se lisent, le potard a la valeur du patch (normalisée)",
          pr.get("found") is True and len(pr.get("params") or []) > 0 and abs((p0.get("value") or 0) - 0.25) < 0.01 and p0.get("name"),
          f"{len(pr.get('params') or [])} paramètre(s), p0 = {p0}")
    b = lm
    ok = eng.set_fx_param(b.get("track"), b.get("fx"), (b.get("params") or {}).get(f"p{K[0]}", {}).get("p"), 0.8)   # la pédale EXP, l'écran
    time.sleep(0.4)
    pr = ask({"action": "vst_params", "block": "hosted"}, ".vst-host-params.json")
    p0 = next((p for p in pr.get("params") or [] if p.get("i") == K[0]), {})
    check("vst host : son potard se pilote en direct (OSC), comme un potard du catalogue", ok and abs((p0.get("value") or 0) - 0.8) < 0.01, f"{p0}")
    miss = ask({"action": "vst_params", "block": "nope"}, ".vst-host-params.json")
    check("vst host : un bloc absent le dit", miss.get("found") is False, f"{miss}")
    # L'ÉTAT NATIF, aller et retour : Vital hébergé avec l'état d'un son d'usine (au format du patch, celui de REAPER),
    # puis relu dans le moteur — ce qui revient est le son posé, pas l'état par défaut du plugin
    import base64
    import glob
    from bridge import vital
    from bridge.engine import ardour as A
    vf = sorted(glob.glob(os.path.join(ROOT, "library", "synth", "vital", "factory", "*.vital")))
    vname = next((r["name"] for r in rows if r["name"].startswith("VST3i: Vital")), None)
    if not vf or not vname:
        print("  --    vst host : Vital ou ses sons d'usine absents, état natif non éprouvé")
        return

    def host(chunk):
        rig = bench_rig("A")
        merge = next(t for t in rig["paths"][0]["tracks"] if t["role"] == "merge")
        merge["blocks"].append({"id": "hosted", "type": "vst-host", "plugin": vname, "knobs": [],
                                "params": {"_vst_chunk": chunk} if chunk else {}})
        with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
            json.dump(rig, f)
        s = eng.send({"action": "rig_recall", "preset": "", "scene": "A"})          # un rig vide entre les deux : l'instance repart de zéro
        s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
        wait(lambda: acked(s) and "hosted" in ((read(".livemap.json") or {}).get("blocks") or {}), 40)
        time.sleep(1.5)
        got = ask({"action": "vst_state", "block": "hosted"}, ".vst-host-state.json")
        try:
            return A.reaper_vst3_parts(base64.b64decode(A.host_state_chunk(got)))[0] if got.get("preset_label") else b""
        except ValueError as e:
            return str(e).encode()
    default = host(None)
    src = vital.splice_chunk(open(vital.TEMPLATE_CHUNK).read(), vf[0])
    want = A.reaper_vst3_parts(base64.b64decode(src))[0]
    back = host(src)
    import re as _re

    def sound(blob):                                      # le nom du son que porte un état de Vital (son JSON)
        m = _re.search(rb'"preset_name"\s*:\s*"([^"]*)"', blob)
        return m.group(1).decode("utf-8", "replace") if m else None
    check("vst host : l'état natif d'un plugin se CAPTURE (au format du patch) et se RECHARGE — le son posé revient, pas le défaut",
          len(default) > 1000 and len(back) > 1000 and sound(want) is not None and sound(back) == sound(want) != sound(default),
          f"défaut « {sound(default)} » ({len(default)} o) · posé « {sound(want)} » ({len(want)} o) · relu « {sound(back)} » ({len(back)} o)")


# ── lot 3 : la PRISE ARMÉE d'un riff (docs/compo.md §12) — le click de la prise dans la backing, la prise part à 0 ─────
def riff_bench(eng, check, wait, acked):
    import subprocess
    import numpy as np
    from bridge import config as C
    from bridge.engine import ardour as A
    from bridge.engine import ardour_plan
    os.makedirs(os.path.dirname(ardour_plan.rig_path(BENCH_ID)), exist_ok=True)

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return {}

    with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
        json.dump(bench_rig("A"), f)
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s) and read(".livemap.json").get("preset") == BENCH_ID, 30)
    time.sleep(1.0)
    # le « click de la prise » : un fichier dont le premier temps tombe à 1,000 s (un tic de 20 ms à 2 kHz)
    click = os.path.join(C.ROOT, "riff-click.wav")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=2000:duration=3:sample_rate=48000", "-af", "volume='if(between(t,1,1.02),1,0)':eval=frame",
                    "-ac", "1", click], check=True)
    cmd = A.backing_load({"action": "backing", "op": "load", "slug": "__riff__", "dir": os.path.dirname(click),
                          "files": {"drums": click}, "mix": {"drums": {"mute": 0, "vol": 1.0}}},
                         cache_dir=os.path.join(C.ROOT, "assets", ".cache", "backing-wav"))
    s = __import__("bridge.commands", fromlist=["x"]).enqueue(cmd)
    wait(lambda: acked(s) and read(".backing.json").get("slug") == "__riff__", 10)
    with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
        json.dump({"in1": True, "mode": "tracks_di", "mix": True}, f)    # les entrées de la personne (compo.riff_inputs)
    s = eng.send({"action": "perf_rec", "on": True, "backing": True})
    wait(lambda: acked(s) and read(".perf.json").get("recording") is True, 8)
    time.sleep(2.6)
    s = eng.send({"action": "perf_rec", "on": False})
    wait(lambda: acked(s) and read(".perf.json").get("recording") is False, 20)
    d = os.path.join(C.ROOT, read(".perf.json").get("file") or "missing")
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    onset = -1.0
    bt = os.path.join(d, "Backing-Track.wav")
    if os.path.isfile(bt):
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", bt, "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                             capture_output=True).stdout
        x = np.abs(np.frombuffer(raw, dtype="<f4"))
        hit = np.nonzero(x > 0.05)[0]
        onset = float(hit[0]) / 48000 if len(hit) else -1.0
    check("riff : la prise armée a les fichiers que le Riff monte (le son de la lane, sa DI, le click de la prise)",
          {"Input-1.wav", "DI-Sandbox-Input-1.wav", "Backing-Track.wav"} <= set(files), f"{files}")
    check("riff : le « 1 » du click tombe dans la prise là où il est dans son fichier (1,000 s, à 5 ms près)", abs(onset - 1.0) < 0.005,
          f"premier temps à {onset:.4f} s")
    s = eng.send({"action": "backing", "op": "unload"})
    wait(lambda: acked(s), 5)


# ── le BANC DU PREMIER USAGE d'un plugin hébergé (bridge/plugin_trial.py) : un SECOND moteur, à côté de celui du banc ──
def trial_bench(check):
    from bridge import plugin_trial as T
    try:
        bad = T.trial_engine("stall", lua="golem Stall")          # le plugin fautif du fork : il fige le fil audio exprès
    except RuntimeError as e:
        bad = (None, str(e), {})
    check("banc du premier usage : un plugin qui fige le moteur à l'allumage est REFUSÉ, avec sa mesure",
          bad[0] is False and "stopped the audio engine" in (bad[1] or "") and bad[2].get("stall_ms", 0) > 100, f"{bad}")
    try:
        good = T.trial_engine("VST3: GoleM FX Delay (golem)")
    except RuntimeError as e:
        good = (None, str(e), {})
    check("banc du premier usage : un plugin sain passe (trou sous 50 ms)", good[0] is True and good[2].get("stall_ms", 99) <= 50, f"{good}")
    try:
        T.trial_engine("VST3: No Such Plugin (Nobody)")
        gone = "jugé"
    except RuntimeError as e:
        gone = str(e)
    check("banc du premier usage : un plugin introuvable n'est PAS jugé (pas de verdict gardé)", gone == "plugin not found", gone)


# ── le MIDI dans une prise (docs/ardour-plan.md §7d) : ce que le clavier d'une lane a joué, en « MIDI-Input-N.mid » ────
def miditake_bench(eng, check, wait, acked):
    from bridge import config as C
    from bridge.engine import ardour_plan, take_finalize
    os.makedirs(os.path.dirname(ardour_plan.rig_path(KEYS_ID)), exist_ok=True)

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return {}

    rig = keys_rig({"id": "bench-organ", "type": "organ", "params": {"db16": 8, "db8": 8}})
    rig["paths"][0]["tracks"][0]["midi_in"] = "port:system:midi_capture_dummy_1"   # une entrée MIDI de la carte factice
    with open(ardour_plan.rig_path(KEYS_ID), "w", encoding="utf-8") as f:
        json.dump(rig, f)
    s = eng.send({"action": "rig_recall", "preset": KEYS_ID, "scene": "A"})
    wait(lambda: acked(s) and read(".livemap.json").get("preset") == KEYS_ID, 40)
    time.sleep(2.0)
    with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
        json.dump({"usb": True, "mode": "tracks", "mix": False}, f)
    s = eng.send({"action": "perf_rec", "on": True})
    wait(lambda: acked(s) and read(".perf.json").get("recording") is True, 8)
    time.sleep(3.0)
    s = eng.send({"action": "perf_rec", "on": False})
    wait(lambda: acked(s) and read(".perf.json").get("recording") is False, 20)
    d = os.path.join(C.ROOT, read(".perf.json").get("file") or "missing")
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    mid, notes, last, tempo = os.path.join(d, "MIDI-Input-3.mid"), [], 0.0, b""
    if os.path.isfile(mid):
        data = open(mid, "rb").read()
        div, evs = take_finalize.read_smf(data)
        tempo = data[22:29]
        bpm = 60000000 / int.from_bytes(data[26:29], "big") if data[23:26] == b"\xff\x51\x03" else 120
        notes = [t / div * 60 / bpm for t, m in evs if (m[0] & 0xF0) == 0x90 and m[2] > 0]
        last = max((t / div * 60 / bpm for t, _m in evs), default=0)
    wav = wav_info(os.path.join(d, "Input-3.wav")) if "Input-3.wav" in files else (0, 0, -150)
    check("prise : le clavier d'une lane MIDI est capté — « MIDI-Input-3.mid » à côté du son de la lane",
          {"MIDI-Input-3.mid", "Input-3.wav"} <= set(files) and len(notes) >= 3 and wav[2] > -50, f"{files} {len(notes)} note(s) son {wav}")
    check("prise : le fichier MIDI est calé sur la prise (tempo en tête, des notes du début à la fin, rien au-delà)",
          tempo[1:4] == b"\xff\x51\x03" and notes and notes[0] < 1.0 and 2.0 < last < wav[1] + 0.3,
          f"première note {notes[0] if notes else None} s, dernier événement {last:.2f} s, prise {wav[1]} s")
    # le MIDI et le SON de la même prise racontent la même chose : chaque montée du son suit une note de peu
    import subprocess
    import numpy as np
    rises = []
    if "Input-3.wav" in files:
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", os.path.join(d, "Input-3.wav"), "-f", "f32le",
                              "-ac", "1", "-ar", "48000", "-"], capture_output=True).stdout
        x = np.abs(np.frombuffer(raw, dtype="<f4"))
        env = np.array([x[i:i + 240].max() for i in range(0, len(x) - 240, 240)])        # par 5 ms
        top = float(env.max()) if len(env) else 0.0
        for i in range(3, len(env)):
            t = i * 240 / 48000
            if env[i] > 0.5 * top and env[i - 3] < 0.2 * top and (not rises or t - rises[-1] > 0.08):
                rises.append(t)
    lags = [min((r - n for n in notes if 0 <= r - n), default=9) for r in rises]
    check("prise : le MIDI et le son de la lane sont sur la même ligne de temps (le son suit sa note de moins de 80 ms)",
          len(rises) >= 1 and all(lag < 0.08 for lag in lags),   # le nombre de montées dépend d'où la phrase en est
          f"montées {[round(r, 3) for r in rises]} · retards {[round(v * 1000) for v in lags]} ms")


# ── une CAPTURE PILOTABLE (docs/capture-module.md) jouée par le lecteur LV2 golem Capture (native/capture-lv2) ───────
def capture_bench(eng, check, wait, acked):
    import glob
    from bridge import capture_module
    from bridge import config as C
    from bridge.engine import ardour_plan
    # une capture de CE rack (état local, jamais dans le dépôt) : sans elle, rien à jouer — dit, pas compté en échec
    found = sorted(glob.glob(os.path.join(ROOT, "assets", "models", "captures", "*", "module.gcap")))
    if not found:
        print("  --    capture pilotable : aucune capture .gcap sur cette machine, lecteur non éprouvé")
        return
    os.makedirs(os.path.dirname(ardour_plan.rig_path(BENCH_ID)), exist_ok=True)

    def read(name):
        try:
            return json.load(open(os.path.join(C.PRESETS_DIR, name)))
        except (OSError, ValueError):
            return {}

    def ask(cmd, name):
        s = eng.send(cmd)
        return wait(lambda: acked(s) and str(read(name).get("seq")) == str(s) and read(name), 8) or {}

    block = {"id": "cap", "type": "amp", "file": found[0], "params": {}}
    capture_module.prepare(block)                         # le compileur : le bloc devient un capture-module
    n = len(block["capture_values"])
    rig = bench_rig("A")
    merge = next(t for t in rig["paths"][0]["tracks"] if t["role"] == "merge")
    merge["blocks"].append(block)
    with open(ardour_plan.rig_path(BENCH_ID), "w", encoding="utf-8") as f:
        json.dump(rig, f)
    s = eng.send({"action": "rig_recall", "preset": BENCH_ID, "scene": "A"})
    wait(lambda: acked(s) and "cap" in (read(".livemap.json").get("blocks") or {}), 40)
    time.sleep(1.5)
    pr = ask({"action": "vst_params", "block": "cap"}, ".vst-host-params.json")
    vals = {p["name"]: p["value"] for p in pr.get("params") or []}
    check(f"capture pilotable : le lecteur LV2 est posé, ses {n} contrôle(s) ont les valeurs de la capture",
          pr.get("found") is True and len(vals) == 32
          and all(abs(vals.get(f"Control {i + 1:02d}", -1) - v) < 0.001 for i, v in enumerate(block["capture_values"])),
          f"{len(vals)} contrôles, attendus {[round(v, 3) for v in block['capture_values'][:6]]}")
    with open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), "w", encoding="utf-8") as f:
        json.dump({"in1": True, "mode": "tracks", "mix": False}, f)

    def take():
        s1 = eng.send({"action": "perf_rec", "on": True})
        wait(lambda: acked(s1) and read(".perf.json").get("recording") is True, 8)
        time.sleep(1.5)
        s1 = eng.send({"action": "perf_rec", "on": False})
        wait(lambda: acked(s1) and read(".perf.json").get("recording") is False, 20)
        f = os.path.join(C.ROOT, read(".perf.json").get("file") or "missing", "Input-1.wav")
        return wav_info(f) if os.path.isfile(f) else (0, 0, -150)
    lv = take()
    check("capture pilotable : le modèle est chargé et SONNE (sans capture, le lecteur rend du silence)", lv[2] > -60, f"{lv}")
    s = eng.send({"action": "capture_params", "block": "cap", "values": {"0": 0.9}})
    wait(lambda: acked(s), 5)
    time.sleep(0.3)
    pr = ask({"action": "vst_params", "block": "cap"}, ".vst-host-params.json")
    c1 = next((p["value"] for p in pr.get("params") or [] if p["name"] == "Control 01"), -1)
    check("capture pilotable : un potard bouge en jouant (capture_params), sans rien recharger", abs(c1 - 0.9) < 0.001, f"Control 01 = {c1}")


# ── lot 2 : les instruments de clavier (docs/ardour-plan.md §7d) — chacun posé sur une lane MIDI, et ENTENDU : une note
# écrite dans la piste, le niveau lu sur sa route ─────────────────────────────────────────────────────────────────────
KEYS_ID = "patch:engine-keys"


def keys_rig(*blocks, midi_ch=None, role="keys"):
    name = "GoleM:keys"
    return {"id": KEYS_ID, "mono_fallback": {"on": False, "gain": -3}, "looper": None, "paths": [{
        "id": "keys", "name": "Keys", "input": 3, "tracks": [
            {"role": "main", "name": name, "input": 3, "midi": True, "midi_in": None, "midi_role": role,
             "midi_ch": midi_ch or {"keys": 1}, "out": 1, "level": 0, "out_sel": "1-2", "blocks": list(blocks)}]}]}


def keys_bench(eng, check, wait, acked):
    import base64
    import glob
    from bridge import config as C
    from bridge import silence, vital
    from bridge.engine import ardour as A
    from bridge.engine import ardour_plan
    rig_file = ardour_plan.rig_path(KEYS_ID)
    out_dir = os.path.dirname(rig_file)
    os.makedirs(out_dir, exist_ok=True)                  # `--only keys` : aucune section d'avant ne l'a créé

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

    def peak(clear, row="GoleM:keys"):
        txt = silence._probe({"action": "peaks", "clear": clear}, silence.PEAKS(), timeout=4)
        rows = {r["track"].split(" ", 1)[1]: r for r in (json.loads(txt) if txt else [])}
        return (rows.get(row) or {}).get("max", -150)

    def play(note, hold=0.7, settle=2.5, route="GoleM:keys", row="GoleM:keys", ch=0):
        """Une note à l'ENTRÉE de la piste (le chemin d'un clavier) ; rend la crête la plus haute pendant qu'elle sonne.
        La queue de la note d'avant s'éteint d'abord (`settle`), puis la crête est remise à zéro."""
        time.sleep(settle)
        peak(True, row)
        s = eng.send({"action": "midi_send", "route": route, "msgs": [[0x90 | ch, note, 110]]})
        wait(lambda: acked(s), 3)
        time.sleep(hold)
        best = peak(False, row)
        s = eng.send({"action": "midi_send", "route": route, "msgs": [[0x80 | ch, note, 0]]})
        wait(lambda: acked(s), 3)
        return best

    def mount(*blocks, scene="A", recall=True, **kw):
        with open(rig_file, "w", encoding="utf-8") as f:
            json.dump(keys_rig(*blocks, **kw), f)
        s = eng.send({"action": "rig_recall" if recall else "scene_apply", "preset": KEYS_ID, "scene": scene})
        if recall:
            wait(lambda: acked(s) and (read(".livemap.json") or {}).get("preset") == KEYS_ID, 40)
            time.sleep(2.5)                              # le renvoi du MIDI d'un synthé tout juste posé (1 s), sa voix
        else:
            wait(lambda: acked(s), 5)
            time.sleep(0.6)
        return dump().get("blocks") or {}

    made = []
    try:
        # VITAL : son état est un preset VST3 écrit par l'adaptateur, chargé par le veilleur ; un autre son = un autre état
        vitals = sorted(glob.glob(os.path.join(ROOT, "library", "synth", "vital", "factory", "*.vital")))
        if len(vitals) < 2:
            check("Vital : deux presets .vital d'usine présents", False)
        else:
            sigs = []
            for i, vf in enumerate(vitals[:2]):
                fn = f"bench-{i}.vital.b64"
                with open(os.path.join(out_dir, fn), "w", encoding="ascii") as f:
                    f.write(vital.splice_chunk(open(vital.TEMPLATE_CHUNK).read(), vf))
                blk = mount({"id": "bench-synth", "type": "vital", "vital_chunk": fn,
                             "params": {"vol": 0.7, "zone_lo": 48, "zone_hi": 72, "transpose": 0}}, recall=(i == 0))
                sigs.append((blk.get("bench-synth") or {}).get("preset"))
            made.append(os.path.join(A.preset_dir("Vital Audio", "Vital"), "golem-bench-synth.vstpreset"))
            check("Vital : posé avec son filtre de zone devant lui", {"bench-synth", "bench-synth~zone"} <= set(blk),
                  ", ".join(sorted(blk)))
            check("Vital : l'état du .vital est chargé, et un autre son à la scène le remplace sans rebuild",
                  all(sigs) and sigs[0] != sigs[1], str(sigs))
            check("Vital : le potard Volume est posé (0,7)",
                  abs(((blk.get("bench-synth") or {}).get("params") or {}).get("Volume", 0) - 0.7) < 0.01)
            inside, outside = play(60), play(30)
            check("Vital SONNE sur une note de sa zone", inside > -60, f"{inside:.1f} dBFS")
            check("zone : une note hors de [48..72] est éliminée", outside < -60, f"{outside:.1f} dBFS")

        # ORGUE : setBfree n'a aucun port ; sa registration part en Control Change
        blk = mount({"id": "bench-organ", "type": "organ", "params": {"db16": 8, "db8": 8, "leslie": "fast", "zone_lo": 0,
                                                                         "zone_hi": 127, "transpose": 0}})
        check("orgue : posé, registration envoyée en MIDI (16 Control Change, vibrato coupé)",
              (blk.get("bench-organ") or {}).get("midi") == 16, str((blk.get("bench-organ") or {}).get("midi")))
        loud = play(60)
        check("orgue SONNE", loud > -60, f"{loud:.1f} dBFS")
        blk = mount({"id": "bench-organ", "type": "organ", "params": {"db16": 0, "db513": 0, "db8": 0, "zone_lo": 0,
                                                                         "zone_hi": 127}}, scene="B", recall=False)
        mute = play(60)
        check("orgue : toutes tirettes rentrées à la scène, il se tait (les CC arrivent au plugin)", mute < loud - 20,
              f"{mute:.1f} dBFS contre {loud:.1f}")

        # PIANO ÉLECTRIQUE : Dexed reçoit la voix choisie de la cartouche, en SysEx « une voix »
        # une cartouche de banc : celle d'usine, dont la voix 2 a tous ses opérateurs à niveau 0 — elle doit se TAIRE
        # n'importe quelle cartouche de 32 voix fait l'affaire (accpiano.syx n'existe que sur le poste Linux ; absente, le
        # banc entier mourait ici sur un FileNotFoundError — 2026-11-19, poste Windows) : la première de library/dx7
        dx7 = os.path.join(ROOT, "library", "dx7")
        carts = sorted(f for f in os.listdir(dx7) if f.lower().endswith(".syx")) if os.path.isdir(dx7) else []
        cart = "accpiano.syx" if "accpiano.syx" in carts else (carts[0] if carts else None)
        raw = bytearray(open(os.path.join(dx7, cart), "rb").read()) if cart else b""
        if len(raw) < 6 + 32 * 128:
            check("piano électrique : une cartouche DX7 de 32 voix dans library/dx7", False, cart or "aucune")
        else:
            for op in range(6):
                raw[6 + 128 + op * 17 + 14] = 0
            bank = os.path.join(out_dir, "bench-cart.syx")
            with open(bank, "wb") as f:
                f.write(bytes(raw))
            blk = mount({"id": "bench-ep", "type": "ep", "dx7_bank": bank, "dx7_patch": 0, "params": {"bank": "x", "patch": 0}})
            check("piano électrique : posé, voix envoyée (1 SysEx)", (blk.get("bench-ep") or {}).get("midi") == 1,
                  str((blk.get("bench-ep") or {}).get("midi")))
            v = play(60)
            check("piano électrique SONNE", v > -60, f"{v:.1f} dBFS ({cart})")
            mount({"id": "bench-ep", "type": "ep", "dx7_bank": bank, "dx7_patch": 1, "params": {"bank": "x", "patch": 1}},
                  scene="B", recall=False)
            v2 = play(60)
            # le silence ne prouve rien si la première voix n'a pas sonné non plus (Dexed absent : -150 contre -150)
            check("piano électrique : la voix de la scène est LUE par Dexed (une voix aux opérateurs à 0 se tait)",
                  v > -60 and v2 < -60, f"{v2:.1f} dBFS contre {v:.1f}")
        # ARPÉGIATEUR : toujours posé entre la zone et l'instrument ; « Off » transparent, une scène l'allume
        blk = mount({"id": "bench-organ", "type": "organ", "params": {"db16": 8, "db8": 8, "arp": "Off"}})
        arp = (blk.get("bench-organ~arp") or {}).get("params") or {}
        check("arpégiateur : posé devant l'orgue, coupé (transparent)", arp.get("On") == 0 and play(60) > -60, json.dumps(arp))
        blk = mount({"id": "bench-organ", "type": "organ", "params": {"db16": 8, "db8": 8, "arp": "Up 1/16"}},
                    scene="B", recall=False)
        arp = (blk.get("bench-organ~arp") or {}).get("params") or {}
        on = play(60, hold=1.0)
        check("arpégiateur : la scène l'allume sans rebuild (double-croches, il monte) et la note sonne",
              arp.get("On") == 1 and arp.get("Rate") == 4 and arp.get("Mode") == 1 and on > -60, f"{json.dumps(arp)} {on:.1f} dBFS")
        time.sleep(1.5)
        peak(True)
        time.sleep(1.0)
        tail = peak(False)
        check("arpégiateur : la note relâchée, il s'arrête", tail < -40, f"{tail:.1f} dBFS une seconde après")

        # PADS : le kit devient un SFZ que sfizz charge ; un pad garni sonne, une note sans pad se tait
        kit = sorted(glob.glob(os.path.join(ROOT, "assets", "samples", "kits", "pads-*", "*.wav")))[:2]
        if len(kit) < 2:
            check("pads : deux samples de kit présents", False)
        else:
            pads = {"id": "bench-pads", "type": "pads", "params": {"kit": "x"},
                    "kit_pads": [{"note": 36, "file": kit[0], "mode": "oneshot", "level": 0},
                                 {"note": 38, "file": kit[1], "mode": "gate", "level": -3}]}
            blk = mount(pads, midi_ch={"keys": 1, "pads": 10}, role="keys-pads")
            rc = wait(lambda: (read(".rig-check.json") or {}).get("checked") and read(".rig-check.json"), 10) or {}
            check("pads : posés (sfizz), leur kit SFZ est lu par le plugin", "bench-pads" in blk and rc.get("ok") is True
                  and rc.get("checked") == 1, json.dumps(rc)[:160])
            hit, miss = play(36, ch=9), play(50, ch=9)
            check("pads : un pad garni SONNE, une note sans pad se tait", hit > -60 and miss < -60,
                  f"{hit:.1f} / {miss:.1f} dBFS")
            # (une note écrite dans la piste passe APRÈS son filtre de canal : le filtre se lit, il ne s'entend pas ici)
            mask = next((x.get("midi_mask") for x in dump().get("tracks") or [] if x["name"] == "GoleM:keys"), None)
            check("pads : la lane n'écoute que le canal des pads (10)", mask == 1 << 9, str(mask))

            # UNE LANE, UN SYNTHÉ ET DES PADS : chacun sa piste et son canal, les effets sur leur somme
            organ = {"id": "bench-organ", "type": "organ", "params": {"db16": 8, "db8": 8}}
            comp = {"id": "bench-comp", "type": "comp", "params": {}}
            mount(organ, pads, comp, midi_ch={"keys": 1, "pads": 10}, role="keys-pads")
            d = dump()
            tr = {x["name"]: x for x in d.get("tracks") or []}
            m = tr.get("GoleM:keys#merge") or {}
            check("lane à deux instruments : une piste par instrument, un bus qui les somme et sort vers la carte",
                  set(tr) == {"GoleM:keys#merge", "GoleM:keys/bench-organ", "GoleM:keys/bench-pads"}
                  and sorted(c.rsplit("_", 1)[-1] for c in m.get("output") or []) == ["1", "2"] and len(m.get("input") or []) >= 2,
                  f"{sorted(tr)} entrée du bus {m.get('input')}")
            lm = read(".livemap.json") or {}
            check("lane à deux instruments : chaque piste n'écoute que son canal (touches 1, pads 10)",
                  (tr.get("GoleM:keys/bench-organ") or {}).get("midi_mask") == 1
                  and (tr.get("GoleM:keys/bench-pads") or {}).get("midi_mask") == 1 << 9,
                  f"{(tr.get('GoleM:keys/bench-organ') or {}).get('midi_mask')} / {(tr.get('GoleM:keys/bench-pads') or {}).get('midi_mask')}")
            check("lane à deux instruments : l'effet audio est sur le bus",
                  (lm.get("blocks") or {}).get("bench-comp", {}).get("track") == m.get("ssid"), str(m.get("ssid")))
            k1 = play(60, route="GoleM:keys/bench-organ", row="GoleM:keys#merge", ch=0)
            k2 = play(60, route="GoleM:keys/bench-pads", row="GoleM:keys#merge", ch=0)
            p1 = play(36, route="GoleM:keys/bench-pads", row="GoleM:keys#merge", ch=9)
            check("lane à deux instruments : les touches jouent l'orgue, pas les pads ; un pad joue son sample",
                  k1 > -60 and k2 < -60 and p1 > -60, f"orgue {k1:.1f}, touche sur les pads {k2:.1f}, pad {p1:.1f} dBFS")
    finally:
        for f in made:
            if os.path.isfile(f):
                os.remove(f)                             # le preset du banc ne reste pas chez l'utilisateur


if __name__ == "__main__":
    sys.exit(main())
