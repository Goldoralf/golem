#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesure le TROU entre deux scènes, sans musicien, à l'échantillon près.

    ./tools/check-scene-gap.py                     # A,B ×10 par l'écran puis par le pied ⚠ SON CONTINU
    ./tools/check-scene-gap.py --seq A,B,C -n 5    # une autre ronde, répétée 5 fois
    ./tools/check-scene-gap.py --path foot         # seulement le chemin du pédalier (PC, CC, Note)
    ./tools/check-scene-gap.py --off               # retire les sondes (si un run a été interrompu)
    ./tools/check-scene-gap.py --listen 180        # ÉCOUTE : TU joues et changes de scène au pied

LE MODE ÉCOUTE (--listen)
Aucun ton, aucune commande pendant la mesure : les détecteurs seuls, armés une fois. On enregistre
en parallèle ce que la VRAIE puce envoie (un second aseqdump sur le port du pédalier — un port ALSA
seq accepte plusieurs lecteurs), chaque commande écrite dans presets/.command.json, et l'enveloppe
de chaque piste à chaque tick. À la fin, pour chaque changement de scène : les messages du pied
qui l'ont causé, le délai jusqu'à la commande, et le son de la fusion et des branches autour.
Un silence de jeu (cordes étouffées) se voit aussi : c'est la coïncidence avec le geste qui compte.

POURQUOI CE SCRIPT EXISTE
Le 2026-09-20, un blanc de ~600 ms en passant de A à B sur « Paper Kite » a coûté une journée :
chaque mesure dépendait du mainteneur en train de jouer, et le crête-mètre sondé à 30 Hz REMPLIT un trou
par sa propre décroissance. Ici le signal est un ton continu posé par le rack, et le trou est
mesuré DANS le thread audio (reaper/Effects/golem_gapmeter.jsfx) : sa durée et sa date viennent de
l'horloge des échantillons, pas du tick `defer`.

CE QU'IL POSE, ET CE QU'IL RETIRE
Un Tone Generator en QUEUE de la piste d'entrée de la lane (après ses blocs : les index de blocs
ne bougent pas), et un détecteur en queue de la piste de fusion et de chaque branche. Le détecteur
d'une BRANCHE est avant son fader : il dit si ses PLUGINS produisent du son. Celui de la FUSION
voit la somme des branches après leurs faders : c'est ce qu'on entend. Tout est retiré à la fin,
ou par --off. ⚠ Le ton passe dans toute la chaîne jusqu'aux sorties : baisser le MONITOR.

LE CHEMIN DU PIED
L'écran envoie un seul geste (/api/recall {scene}). La vraie puce UnO2 envoie, pour UN appui de
scène : PC (le slot), puis CC 20+n (la scène), puis la Note du switch (note_base 0), puis son
relâché. On rejoue exactement cette suite par /api/foot/inject. Ce qu'on ne rejoue PAS : l'écart
réel entre ces messages sur le fil.
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge import config as C  # noqa: E402
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
GAPS = C.runtime_file("golem-gaps.json")
FXDUMP = os.path.join(ROOT, "presets", ".fxdump.json")


def _post(path, body):
    r = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=20))


def _get(path):
    return json.load(urllib.request.urlopen(BRIDGE + path, timeout=10))


# ── LE GOLEM ENGINE (docs/ardour-plan.md A2) : les sondes sont GoleM FX Gapmeter (golem-fx), qui envoient leurs mesures
# en OSC/UDP à CE script — /gfx/gap ,iidd (slot, k, fin en s, durée ms) à la fin d'un trou, /gfx/gapmeter ,idddid
# (slot, horloge s, enveloppe dB, silence en cours ms, nombre, plus long ms) toutes les ~50 ms. On en refait l'instantané
# que golem_apply.lua écrit sous REAPER (golem-gaps.json) : le reste du script ne change pas.
LISTENER = None


class GapListener:
    def __init__(self, names):
        import socket
        import threading
        self.names = names                       # slot -> nom de piste (les détecteurs, dans l'ordre)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.slots = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def _osc(data):
        import struct

        def s(i):
            j = data.index(b"\0", i)
            return data[i:j].decode(), (j + 4) & ~3
        addr, i = s(0)
        tags, i = s(i)
        out = []
        for t in tags[1:]:
            if t == "i":
                out.append(struct.unpack(">i", data[i:i + 4])[0]); i += 4
            elif t == "d":
                out.append(struct.unpack(">d", data[i:i + 8])[0]); i += 8
            elif t == "f":
                out.append(struct.unpack(">f", data[i:i + 4])[0]); i += 4
        return addr, out

    def _run(self):
        while True:
            try:
                addr, a = self._osc(self.sock.recv(4096))
            except Exception:
                continue
            now = time.monotonic()
            with self.lock:
                if addr == "/gfx/gapmeter" and len(a) >= 6:
                    sl = self.slots.setdefault(a[0], {"gaps": []})
                    sl.update(clk=a[1], env=a[2], run=a[3], n=a[4], max=a[5], recv=now)
                elif addr == "/gfx/gap" and len(a) >= 4:
                    sl = self.slots.setdefault(a[0], {"gaps": []})
                    sl["gaps"] = (sl["gaps"] + [[a[1], a[3], a[2]]])[-24:]

    def snapshot(self):
        """{t, slots:[{track, clk, env, n, max, run, gaps:[[k, ms, fin_s]]}]} comme golem-gaps.json : `t` = la réception
        du dernier battement du slot 0 ; l'horloge des autres slots est ramenée à ce même instant."""
        with self.lock:
            if 0 not in self.slots or "clk" not in self.slots[0]:
                return None
            t0 = self.slots[0]["recv"]
            rows = []
            for k, name in enumerate(self.names):
                sl = self.slots.get(k)
                if not sl or "clk" not in sl:
                    continue
                rows.append({"track": name, "clk": sl["clk"] + (t0 - sl["recv"]), "env": sl["env"], "n": sl["n"],
                             "max": sl["max"], "run": sl["run"], "gaps": list(sl["gaps"])})
            return {"t": t0, "slots": rows}


def _port(dets):
    """Sous le Golem Engine : l'écouteur OSC démarre (port libre) et son port part avec la commande ; sous REAPER : rien."""
    global LISTENER
    if _engine() != "ardour":
        return {}
    if LISTENER is None:
        LISTENER = GapListener(dets)
    return {"port": LISTENER.port}


def _engine():
    """Le moteur actif (/api/engines) : « ardour » = le Golem Engine."""
    try:
        return _get("/api/engines").get("current") or "reaper"
    except Exception:
        return "reaper"


def _read_gaps():
    if LISTENER is not None:
        return LISTENER.snapshot()
    try:
        with open(GAPS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _engine_tracks(lane):
    """Golem Engine : la piste de la lane `lane` est celle que la carte nourrit sur system:capture_<lane> (dump du
    veilleur) ; son merge est « <piste>#merge », ses branches « <piste>/… »."""
    dump = os.path.join(ROOT, "presets", ".engine-dump.json")
    m0 = os.path.getmtime(dump) if os.path.exists(dump) else 0
    import subprocess
    subprocess.run([sys.executable, os.path.join(ROOT, "reaper", "golem-cmd.py"), json.dumps({"action": "dump"})],
                   capture_output=True, timeout=20)
    for _ in range(60):
        time.sleep(0.1)
        if os.path.exists(dump) and os.path.getmtime(dump) > m0:
            break
    tracks = (json.load(open(dump)) or {}).get("tracks") or []
    names = [t["name"] for t in tracks]
    head = next((t["name"] for t in tracks if any(c.endswith(f"capture_{lane}") for c in t.get("input") or [])), None)
    if not head:
        sys.exit(f"✗ aucune lane du Golem Engine n'écoute l'entrée {lane}")
    branches = [n for n in names if n.startswith(head + "/")]
    if not branches:
        sys.exit(f"✗ « {head} » n'a pas de split : ce script mesure une bascule de BRANCHES.")
    merge = head + "#merge"
    return head, [merge] + branches if merge in names else branches


def _tracks(lane):
    """Les pistes Reaper de la lane `lane` (n° d'entrée), lues au dump FX — le nom est la seule
    chose que Reaper et nous partageons. Sous le Golem Engine : _engine_tracks."""
    if _engine() == "ardour":
        return _engine_tracks(lane)
    m0 = os.path.getmtime(FXDUMP) if os.path.exists(FXDUMP) else 0
    _post("/api/fxdump", {})
    for _ in range(60):
        time.sleep(0.1)
        if os.path.exists(FXDUMP) and os.path.getmtime(FXDUMP) > m0:
            break
    time.sleep(0.2)
    names = [t["track"] for t in json.load(open(FXDUMP))]
    head = f"Sandbox #Input {lane}"
    merge = head + "#merge"
    branches = [n for n in names if n.startswith(head + "/")]
    if head not in names:
        sys.exit(f"✗ piste « {head} » absente : la lane {lane} n'est pas montée")
    if not branches:
        sys.exit(f"✗ « {head} » n'a pas de split : le ton en queue de piste contournerait la chaîne. "
                 "Ce script mesure une bascule de BRANCHES.")
    return head, [merge] + branches if merge in names else branches


def _clock_offset():
    """Écart entre time.monotonic() et time_precise de Reaper : on attend une écriture neuve du
    fichier et on garde le plus petit écart vu (le fichier est lu APRÈS avoir été écrit)."""
    best, last = None, None
    t_end = time.monotonic() + 2.0
    while time.monotonic() < t_end:
        g = _read_gaps()
        now = time.monotonic()
        if g and g.get("t") != last:
            last = g["t"]
            d = now - g["t"]
            best = d if best is None else min(best, d)
        time.sleep(0.003)
    return best


def _scene_ids():
    st = _get("/api/state")
    pid = st.get("preset_id")
    p = _get(f"/api/preset/{pid}") if pid else {}
    return st, pid, [s.get("id") for s in (p.get("scenes") or [])]


def _pc_slot(pid):
    """Le slot (= numéro de PC) du preset dans la LISTE AU PIED, lue au bridge : setlists/fcb-banks.json n'existe plus
    depuis que la setlist au pied est une setlist comme les autres (2026-09-30)."""
    try:
        banks = _get("/api/foot-list").get("banks") or []
    except Exception:
        return None
    return next((b["slot"] for b in banks if b.get("preset") == pid), None)


def fire(path, sc, ids, pc):
    if path == "api":
        _post("/api/recall", {"scene": sc})
        return
    n = ids.index(sc)                                  # A=0 … E=4 : CC 20+n, Note n (note_base 0)
    if pc is not None:
        _post("/api/foot/inject", {"type": "pc", "n": pc})
    _post("/api/foot/inject", {"type": "cc", "cc": 20 + n, "val": 127})
    _post("/api/foot/inject", {"type": "note", "n": n, "on": True})
    time.sleep(0.12)                                   # un appui de pied dure ~100 ms
    _post("/api/foot/inject", {"type": "note", "n": n, "on": False})


def transition(path, frm, to, ids, pc, off, settle):
    g0 = _read_gaps() or {}
    n0 = {s["track"]: s["n"] for s in g0.get("slots", [])}
    clk0 = (g0["t"], g0["slots"][0]["clk"]) if g0.get("slots") else None
    env0 = g0["slots"][0]["env"] if g0.get("slots") else None
    t0 = time.monotonic()
    fire(path, to, ids, pc)
    t_fire = time.monotonic() - t0
    trace = []                                         # enveloppe de la fusion, ~30 Hz
    while time.monotonic() - t0 < settle:
        g = _read_gaps()
        if g and g.get("slots"):
            trace.append((g["t"] + off - t0, g["slots"][0]["env"]))
        time.sleep(0.008)
    g = _read_gaps() or {}
    out = {"from": frm, "to": to, "path": path, "fire_ms": t_fire * 1000, "tracks": {}}
    # ⚠ LE MOTEUR FIGÉ (2026-09-21). Le détecteur compte les échantillons QU'IL TRAITE : si Reaper
    # cesse de traiter l'audio, son horloge s'arrête avec lui et il ne voit AUCUN silence. C'est
    # ainsi que cet outil a rendu « 0 trou sur 36 bascules » le matin même où le mainteneur entendait un
    # blanc de 500 ms à chaque entrée en scène B (un plugin guitarix figeait tout le moteur à son
    # activation). On compare donc l'horloge du JSFX à celle de Reaper : l'écart EST le blanc.
    out["stall_ms"] = (((g["t"] - clk0[0]) - (g["slots"][0]["clk"] - clk0[1])) * 1000
                       if clk0 and g.get("slots") else None)
    for s in g.get("slots", []):
        new = [x for x in s["gaps"] if x[0] >= n0.get(s["track"], 0)]
        rows = []
        for _, ms, end in new:
            # fin du trou (horloge JSFX) -> time_precise -> monotonic, relative au geste
            end_tp = g["t"] - (s["clk"] - end)
            rows.append({"ms": ms, "start_ms": (end_tp + off - t0) * 1000 - ms})
        if s["run"] > 50:                              # silence toujours EN COURS à la lecture
            rows.append({"ms": s["run"], "start_ms": None, "ongoing": True})
        out["tracks"][s["track"]] = rows
    during = [e for t, e in trace if 0.03 <= t <= settle]
    out["env_before"] = env0
    out["env_after"] = trace[-1][1] if trace else None
    out["env_min"] = min(during) if during else None
    return out


BARS = ((-20, "█"), (-30, "▆"), (-40, "▄"), (-50, "▂"))


def _bar(e):
    for lim, ch in BARS:
        if e >= lim:
            return ch
    return "·"


def _fcb_port():
    """Le port que le bridge écoute : on le lit sur SON aseqdump, jamais en dur."""
    import subprocess
    out = subprocess.run(["ps", "-o", "args=", "-C", "aseqdump"], capture_output=True, text=True).stdout
    for ln in out.splitlines():
        parts = ln.split()
        if "-p" in parts:
            return parts[parts.index("-p") + 1]
    return None


def listen(a, dets):
    import subprocess
    import threading
    port = _fcb_port()
    midi = []
    proc = None
    if port:
        proc = subprocess.Popen(["aseqdump", "-p", port], stdout=subprocess.PIPE, text=True, bufsize=1)

        def rd():
            for ln in proc.stdout:
                ln = ln.strip()
                if ln and not ln.startswith(("Waiting", "Source")):
                    midi.append((time.monotonic(), ln))
        threading.Thread(target=rd, daemon=True).start()
    print(f"pédalier : " + (f"port {port}, second lecteur branché" if port else "⚠ port introuvable — les messages du pied ne seront pas vus"))
    _post("/api/gapmeter", {"on": True, "tracks": dets, "hold": min(900, a.listen + 30), **_port(dets)})
    time.sleep(1.0)
    off = _clock_offset()
    if off is None:
        _post("/api/gapmeter", {"on": False})
        sys.exit(f"✗ aucune lecture de {GAPS}")
    cmdf = os.path.join(ROOT, "presets", ".command.json")
    cmds, env, last_seq, last_t = [], [], None, None
    print(f"\n▶ À TOI : joue en continu (accords tenus, grattés) et change de scène AU PIED —")
    print(f"  A→B plusieurs fois, et B→A entre deux. {a.listen} s. Ctrl-C arrête plus tôt.\n")
    t_end = time.monotonic() + a.listen
    try:
        while time.monotonic() < t_end:
            try:
                c = json.load(open(cmdf))
                if c.get("seq") != last_seq:
                    last_seq = c.get("seq")
                    cmds.append((time.monotonic(), c))
                    if c.get("action") in ("scene_apply", "rig_recall"):
                        print(f"  {c.get('action')} {c.get('scene') or ''}", flush=True)
            except (OSError, ValueError):
                pass
            g = _read_gaps()
            if g and g.get("t") != last_t:
                last_t = g["t"]
                env.append((g["t"] + off, {s["track"]: s["env"] for s in g["slots"]}, g))
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        _post("/api/gapmeter", {"on": False})
        if proc:
            proc.terminate()
    raw = {"midi": midi, "cmds": [(t, c) for t, c in cmds],
           "env": [(t, e) for t, e, _ in env], "gaps": env[-1][2] if env else None}
    listen_path = C.runtime_file("golem-scene-listen.json")
    with open(listen_path, "w") as f:
        json.dump(raw, f)
    print("\n── ce qui s'est passé à chaque changement de scène ──")
    gl = env[-1][2] if env else {"slots": []}
    for t, c in cmds:
        if c.get("action") not in ("scene_apply", "rig_recall"):
            continue
        near = [(tm - t) * 1000 for tm, ln in midi if -0.6 <= tm - t <= 0.1]
        msgs = [ln.split("  ")[-1][:40] for tm, ln in midi if -0.6 <= tm - t <= 0.1]
        print(f"\n{c.get('action')} {c.get('scene')}  (seq {c.get('seq')})")
        if msgs:
            print(f"  pied : {len(msgs)} msg, de {min(near):+.0f} à {max(near):+.0f} ms avant la commande : " + " | ".join(msgs))
        else:
            print("  pied : AUCUN message dans les 600 ms avant (geste écran, ou lecteur absent)")
        for tr in dets:
            strip = "".join(_bar(e.get(tr, -150)) for tm, e, _ in env if -0.3 <= tm - t <= 1.2)
            print(f"  {tr.split('/')[-1].replace('Sandbox #Input 1', 'in1'):>8} -0,3s {strip} +1,2s")
        for s in gl["slots"]:
            for _, ms, end in s["gaps"]:
                end_m = gl["t"] - (s["clk"] - end) + off
                st = end_m - ms / 1000
                if -0.2 <= st - t <= 1.5 or (st - t < -0.2 and end_m - t > 0):
                    print(f"  TROU {s['track'].split('/')[-1]} : {ms:.0f} ms, commence à {(st - t) * 1000:+.0f} ms")
    other = [c.get("action") for t, c in cmds if c.get("action") not in ("scene_apply", "rig_recall")]
    if other:
        print(f"\nautres commandes pendant l'écoute : {sorted(set(other))}")
    print(f"\nsondes retirées ; brut dans {listen_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seq", default="A,B", help="ronde de scènes, rebouclée (défaut A,B)")
    ap.add_argument("-n", type=int, default=10, help="nombre de rondes par chemin")
    ap.add_argument("--path", choices=("api", "foot", "both"), default="both")
    ap.add_argument("--lane", type=int, default=1, help="n° d'entrée de la lane (défaut 1)")
    ap.add_argument("--db", type=float, default=-20, help="niveau du ton (dBFS, défaut -20)")
    ap.add_argument("--settle", type=float, default=1.5, help="attente après chaque geste (s)")
    ap.add_argument("--keep", action="store_true", help="laisser les sondes en place à la fin")
    ap.add_argument("--play", action="store_true",
                    help="backing EN LECTURE pendant la série (transport qui roule, comme en répète)")
    ap.add_argument("--off", action="store_true", help="retirer les sondes et sortir")
    ap.add_argument("--listen", type=int, default=0, metavar="S",
                    help="écoute passive pendant S secondes : le musicien joue et change de scène")
    a = ap.parse_args()

    if a.off:
        _post("/api/gapmeter", {"on": False})
        print("sondes retirées")
        return

    st, pid, ids = _scene_ids()
    seq = [s.strip() for s in a.seq.split(",") if s.strip()]
    missing = [s for s in seq if s not in ids]
    if missing:
        sys.exit(f"✗ scène(s) {missing} absente(s) de « {pid} » ({ids})")
    head, dets = _tracks(a.lane)
    if a.listen:
        print(f"preset « {pid} », scènes {ids} ; détecteurs : " + " · ".join(dets))
        return listen(a, dets)
    pc = _pc_slot(pid)
    print(f"preset « {pid} », scènes {ids}, ronde {seq} ×{a.n}")
    print(f"ton {a.db:g} dBFS en queue de « {head} » ; détecteurs : " + " · ".join(dets))
    if a.path in ("foot", "both"):
        print("pied : " + (f"PC {pc}, " if pc is not None else "⚠ preset absent de la liste au pied : PAS de PC, ")
              + "CC 20+n, Note n on/off")

    _post("/api/gapmeter", {"on": True, "tone": head, "db": a.db, "tracks": dets,
                            "hold": min(900, 60 + a.n * len(seq) * 2 * (a.settle + 1)), **_port(dets)})
    _post("/api/recall", {"scene": seq[-1]})           # point de départ connu : la dernière de la ronde
    time.sleep(2.5)
    off = _clock_offset()
    g = _read_gaps()
    if off is None or not g or not g.get("slots"):
        _post("/api/gapmeter", {"on": False})
        sys.exit(f"✗ aucune lecture de {GAPS} — golem_gapmeter chargé ? "
                 "(un JSFX neuf demande parfois un redémarrage de Reaper) ; .apply.log le dit")
    print(f"horloge : monotonic - time_precise = {off*1000:.0f} ms ; niveau de la fusion {g['slots'][0]['env']:.1f} dB")
    if g["slots"][0]["env"] < -40:
        print("⚠ la fusion est presque muette AVANT tout geste (pédale de volume au talon ?) : "
              "les trous ne voudront rien dire")

    results = []
    if a.play:
        r = _post("/api/backing", {"op": "play"})
        print("backing : " + ("en lecture" if r.get("ok") else f"⚠ refus {r}"))
        time.sleep(1.0)
    try:
        for path in (("api", "foot") if a.path == "both" else (a.path,)):
            print(f"\n── chemin {path.upper()} ──")
            cur = seq[-1]
            for r in range(a.n):
                for to in seq:
                    res = transition(path, cur, to, ids, pc, off, a.settle)
                    results.append(res)
                    merge = res["tracks"].get(dets[0], [])
                    worst = max(merge, key=lambda x: x["ms"]) if merge else None
                    br = " · ".join(f"{k.split('/')[-1]}:{max(x['ms'] for x in v):.0f}ms"
                                    for k, v in res["tracks"].items() if k != dets[0] and v)
                    # CREUX = sous le niveau le plus bas des DEUX scènes : B→A n'est pas un creux
                    # parce que A est plus douce que B (première version de ce script : elle l'affichait)
                    ref = [e for e in (res["env_before"], res["env_after"]) if e is not None]
                    dip = (res["env_min"] - min(ref)) if res["env_min"] is not None and ref else None
                    dip = dip if dip is not None and dip < -6 else None
                    stall = res.get("stall_ms")
                    print(f"  {r+1:2d} {cur}→{to}  "
                          + (f"MOTEUR FIGÉ {stall:.0f} ms  " if stall is not None and stall > 20 else "")
                          + (f"TROU {worst['ms']:.0f} ms" + (f" à +{worst['start_ms']:.0f} ms" if worst.get("start_ms") is not None else " (en cours)")
                             if worst else "sans trou")
                          + (f"  creux {dip:+.0f} dB" if dip is not None else "")
                          + (f"  [branches pré-fader : {br}]" if br else ""))
                    cur = to
    finally:
        if a.play:
            _post("/api/backing", {"op": "stop"})
        if not a.keep:
            _post("/api/gapmeter", {"on": False})

    print("\n── bilan ──")
    for path in sorted({r["path"] for r in results}):
        for frm, to in sorted({(r["from"], r["to"]) for r in results if r["path"] == path}):
            rs = [r for r in results if r["path"] == path and r["from"] == frm and r["to"] == to]
            gaps = [max((x["ms"] for x in r["tracks"].get(dets[0], [])), default=0) for r in rs]
            hit = [x for x in gaps if x > 0]
            stalls = [r["stall_ms"] for r in rs if (r.get("stall_ms") or 0) > 20]
            if stalls:
                print(f"  {path:4} {frm}→{to} : ⚠ MOTEUR FIGÉ {len(stalls)}/{len(rs)} fois "
                      f"(médiane {statistics.median(stalls):.0f} ms, max {max(stalls):.0f} ms)")
            print(f"  {path:4} {frm}→{to} : {len(hit)}/{len(rs)} avec trou"
                  + (f" (médiane {statistics.median(hit):.0f} ms, max {max(hit):.0f} ms)" if hit else ""))
    print("sondes " + ("LAISSÉES en place (--off pour retirer)" if a.keep else "retirées"))


if __name__ == "__main__":
    main()
