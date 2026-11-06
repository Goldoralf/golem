#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le module de batterie envoie-t-il ce que son descripteur PRÉTEND ? — mesuré, élément par élément.

    ./tools/check-drums.py                  # écoute libre : dit ce qui arrive, sans rien demander
    ./tools/check-drums.py --learn          # te nomme chaque élément, tu frappes, il note
    ./tools/check-drums.py --learn --only hh-closed,hh-open   # reprend ces étapes, garde le reste
    ./tools/check-drums.py --compare        # la dernière mesure contre le descripteur
    ./tools/check-drums.py --write          # grave la mesure DANS le descripteur (source measured, verified)

C'est le jumeau en ligne de commande de Settings ▸ Calibration ▸ Drums (docs/calibration.md, addendum
2026-09-23) : pour un rack sans écran, ou une session SSH. L'ANALYSE est la même — `bridge/drumlearn.py`
(la règle de la frappe, la comparaison, l'écriture) — ce fichier ne fait que poser les questions et
choisir comment écouter.

DEUX TRANSPORTS, choisis à l'exécution
  · `aseqdump` sur le port ALSA, quand il est LIBRE ;
  · sinon le flux de Reaper : tant que Reaper détient le port rawmidi d'un module, PERSONNE d'autre ne
    peut l'écouter (« Resource temporarily unavailable », mesuré le 2026-09-23). On demande alors au
    bridge la piste d'écoute (`POST /api/calibrate/drums/start`) et on lit `GET /api/calibrate/drums/live`.
    ⚠ Par ce chemin, Reaper ne laisse pas passer l'horloge MIDI : `clock` reste à 0.

COMMENT ON ÉVITE LA COURSE
Pas de chronomètre : tu frappes QUAND TU VEUX, puis tu appuies sur Entrée. Ce qui est arrivé entre les
deux est ce qui compte — et la SÉQUENCE est gardée (un geste en produit plusieurs : chick de pédale
puis frappe ; peau faible + diaphonie). Une frappe ratée se refait (« r »).

GARDE-FOUS
  · LECTURE SEULE : rien n'est envoyé au module, aucun son n'est déclenché.
  · `--write` sauvegarde le descripteur (`.bak`), n'écrit que le mesuré, et REFUSE une mesure qui se
    contredit (deux éléments de base sur la même note — le 23/09, « pédale seule » a rendu la note de
    l'ouverte et aurait effacé `hh-open`).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge import drumlearn as D          # noqa: E402  (l'analyse partagée)
from bridge import drumkits                # noqa: E402

OUT = os.path.join(ROOT, "presets", ".drums-learn.json")
BRIDGE = os.environ.get("GOLEM_BRIDGE", "http://localhost:8770")
OK, KO, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m⚠\033[0m"
DIM, B, R = "\033[2m", "\033[1m", "\033[0m"

NOTE_ON = re.compile(r"Note on\s+(\d+), note (\d+), velocity (\d+)")
CTRL = re.compile(r"Control change\s+(\d+), controller (\d+), value (\d+)")
POLY = re.compile(r"Polyphonic aftertouch\s+(\d+), note (\d+), value (\d+)")

# La phrase de chaque étape (bridge/drumlearn.STEPS donne l'ordre et la nature)
ASK = {
    "kick": "la GROSSE CAISSE (pédale)", "snare": "la CAISSE CLAIRE, au centre de la peau",
    "snare-rim": "la CAISSE CLAIRE, sur le CERCLE", "tom1": "le TOM 1 (le plus aigu)", "tom1-rim": "le TOM 1, sur le cercle",
    "tom2": "le TOM 2", "tom2-rim": "le TOM 2, sur le cercle", "tom3": "le TOM 3 (le plus grave, au sol)",
    "tom3-rim": "le TOM 3, sur le cercle", "tom4": "le TOM 4, s'il existe", "tom4-rim": "le TOM 4, sur le cercle",
    "hh-closed": "le CHARLESTON, pédale ENFONCÉE et tenue", "hh-open": "le CHARLESTON, pédale RELÂCHÉE",
    "hh-half": "le CHARLESTON, pédale À MI-COURSE, tenue", "hh-pedal": "la PÉDALE de charleston SEULE (le « chick », sans baguette)",
    "hh-splash": "le charleston en SPLASH (frappe ouverte, puis ferme la pédale)", "crash1": "le CRASH 1",
    "crash1-choke": "le CRASH 1 : frappe PUIS attrape-le pour l'étouffer", "crash2": "le CRASH 2, s'il existe",
    "ride": "la RIDE", "ride-bell": "la CLOCHE de la ride, si le pad en a une",
}
KIND = {1: "note", 2: "CC  ", 3: "AT  "}


# ── transport A : aseqdump (port libre) ────────────────────────────────────────────────────
class AlsaTap:
    """Une écoute continue d'`aseqdump`, dont on vide le sac quand on veut. Événements au format du
    bridge : {k, n, v, c, t}."""

    def __init__(self, addr, name):
        self.name, self.evts, self.lock, self.clock = name, [], threading.Lock(), False
        self.p = subprocess.Popen(["stdbuf", "-oL", "aseqdump", "-p", addr],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        threading.Thread(target=self._pump, daemon=True).start()
        time.sleep(0.6)
        if self.p.poll() is not None:
            raise RuntimeError((self.p.stderr.read() or "").strip() or f"aseqdump n'a pas pu écouter {addr}")

    def _pump(self):
        for line in self.p.stdout:
            m, k = NOTE_ON.search(line), D.NOTE
            if not m:
                m, k = CTRL.search(line), D.CC
            if not m:
                m, k = POLY.search(line), D.POLY
            if not m:
                if "Clock" in line or "sensing" in line:
                    self.clock = True
                continue
            with self.lock:
                self.evts.append({"k": k, "c": int(m.group(1)), "n": int(m.group(2)), "v": int(m.group(3)),
                                  "t": time.monotonic()})

    def take(self):
        with self.lock:
            e, self.evts = self.evts, []
            return e

    def close(self):
        self.p.terminate()


# ── transport B : la piste d'écoute de Reaper, via le bridge ───────────────────────────────
def _http(path, body=None):
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


class BridgeTap:
    """Lit le tampon des 32 derniers événements publié par golem_drumlearn.lua (par seq)."""

    def __init__(self, device):
        r = _http("/api/calibrate/drums/start", {"device": device})
        if r.get("error"):
            raise RuntimeError(r["error"])
        self.name, self.dev, self.clock = device, r.get("dev"), False
        self.seq, self.evts, self.lock, self.alive = None, [], threading.Lock(), True
        deadline = time.time() + 4
        while time.time() < deadline:                    # la piste se monte au tick suivant de Reaper
            d = _http("/api/calibrate/drums/live")
            if d.get("on"):
                self.seq = d.get("seq", 0)
                break
            if d.get("err"):
                raise RuntimeError(d["err"])
            time.sleep(0.2)
        if self.seq is None:
            raise RuntimeError("la piste d'écoute ne s'est pas montée (Reaper tourne-t-il ? le module est-il ouvert par Reaper ?)")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while self.alive:
            try:
                d = _http("/api/calibrate/drums/live")
            except Exception:
                time.sleep(0.5); continue
            cur = d.get("seq", 0)
            if cur > self.seq:
                fresh = (d.get("events") or [])[-min(cur - self.seq, len(d.get("events") or [])):]
                self.seq = cur
                with self.lock:
                    self.evts.extend(fresh)
            if d.get("clock"):
                self.clock = True
            time.sleep(0.12)

    def take(self):
        with self.lock:
            e, self.evts = self.evts, []
            return e

    def close(self):
        self.alive = False
        try:
            _http("/api/calibrate/drums/stop", {})
        except Exception:
            pass


def ports():
    """Les entrées MIDI vues par ALSA : (adresse, client, port) — l'ADRESSE sert à écouter (un nom peut
    porter un caractère invisible : l'Alesis Nitro a un bidi mark dans le sien)."""
    out = subprocess.run(["aseqdump", "-l"], capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines()[1:]:
        m = re.match(r"\s*(\d+:\d+)\s+(.+?)\s\s+(.+?)\s*$", line)
        if m:
            found.append((m.group(1), m.group(2), m.group(3)))
    return found


def open_tap(hint):
    """ALSA si le port est libre, Reaper sinon — et on dit lequel."""
    got = ports()
    if not got:
        sys.exit("aucune entrée MIDI — le module est-il branché et allumé ?")
    hit = next(((a, c) for a, c, p in got if hint.lower() in (c + " " + p).lower() and "Through" not in c), None)
    if not hit:
        sys.exit(f"aucune entrée ne contient « {hint} ».\n  vues : " + "\n          ".join(f"{a}  {c}" for a, c, _ in got))
    addr, name = hit
    try:
        tap = AlsaTap(addr, name)
        print(f"{DIM}transport : aseqdump sur {addr} (port libre){R}")
        return tap
    except RuntimeError as e:
        print(f"{DIM}aseqdump : {e} → le port est tenu par Reaper, on écoute par sa piste{R}")
    try:
        tap = BridgeTap(name)
        print(f"{DIM}transport : piste d'écoute Reaper ({tap.dev}) via {BRIDGE}{R}")
        return tap
    except Exception as e:
        sys.exit(f"impossible d'écouter « {name} » : {e}")


# ── rendu ──────────────────────────────────────────────────────────────────────────────────
def _seq_lines(evts, t0, limit=10):
    out = [f"{DIM}      {(e['t'] - t0) * 1000:5.0f} ms  {KIND[e['k']]} {e['n']:3d}  {e['v']:3d}{R}" for e in evts[:limit]]
    if len(evts) > limit:
        out.append(f"{DIM}      … {len(evts) - limit} de plus{R}")
    return out


def render(report, cmp_, kit):
    """Le rapport de bridge.drumlearn, en texte."""
    print(f"\n── {B}{(kit or {}).get('name', 'module inconnu')}{R} ──")
    rows = cmp_["rows"] if cmp_ else [{"el": el, "note": m["note"], "status": "new", "vel": m["vel"]}
                                      for el, m in sorted(report["elements"].items(), key=lambda x: x[1]["note"])]
    for r in rows:
        if r["status"] == "twin":
            print(f"  {WARN} {r['el']:<13} note {r['note']:3d}  — la MÊME que {r['of']} (vélocité {r['vel']} contre {r['vel_of']}) : une seule zone sur ce pad")
        elif r["status"] == "ok":
            print(f"  {OK} {r['el']:<13} note {r['note']:3d}")
        elif r["status"] == "differs":
            print(f"  {KO} {r['el']:<13} note {r['note']:3d}  — le descripteur dit {r['declared']}")
        elif r["status"] == "absent":
            print(f"  {WARN} {r['el']:<13} note {r['note']:3d}  — absent du descripteur")
        else:
            print(f"  {OK} {r['el']:<13} note {r['note']:3d}  (nouveau)")
    if cmp_ and cmp_["ghosts"]:
        print(f"  {WARN} déclarés, jamais reçus : " + ", ".join(f"{g['el']} ({g['note']})" for g in cmp_["ghosts"]))
    hh = report["hihat"]
    print(f"  {'·'} charleston : " + (f"CC {hh['cc']} (valeurs {hh['cc_range'][0]}–{hh['cc_range'][1]})" if hh["cc"] is not None
                                     else "pédale interrupteur, aucun CC") + f", {hh['positions']} positions"
          + (f"  {KO} le descripteur dit CC {cmp_['verdict']['hihat_cc']['declared']}, {cmp_['verdict']['hihat_positions']['declared']} positions"
             if cmp_ and not (cmp_["verdict"]["hihat_cc"]["ok"] and cmp_["verdict"]["hihat_positions"]["ok"]) else ""))
    print(f"  · étouffement : {report['choke']}"
          + (f"  {KO} le descripteur dit {cmp_['verdict']['choke']['declared']}" if cmp_ and not cmp_["verdict"]["choke"]["ok"] else "")
          + (f"\n    {DIM}aftertouch reçu HORS étouffement pendant : {', '.join(report['aftertouch_elsewhere'])} — la pédale, pas un choke{R}"
             if report["aftertouch_elsewhere"] else ""))
    ch = report["channel"]
    print(f"  {OK if not cmp_ or cmp_['verdict']['channel']['ok'] else KO} canal {ch[0] if ch else '?'}"
          + (f" (déclaré {cmp_['verdict']['channel']['declared']})" if cmp_ and not cmp_["verdict"]["channel"]["ok"] else ""))
    if report["clock"]:
        print(f"  {DIM}· ce module émet une horloge MIDI en continu (sans effet sur nos horloges){R}")
    if report["clash"]:
        print(f"  {KO} la mesure se contredit — une note ne sert qu'UN élément de base : "
              + " ; ".join(f"note {n} : {', '.join(els)}" for n, els in report["clash"].items()))
        print(f"  {DIM}      reprends ces étapes (--learn --only …), rien ne sera écrit avant{R}")
    if cmp_:
        print(f"\n  {B}{'tout concorde' if not cmp_['bad'] else str(cmp_['bad']) + ' écart(s)'}{R} · provenance actuelle : {cmp_['provenance']}")


# ── les modes ──────────────────────────────────────────────────────────────────────────────
def listen(tap, seconds):
    print(f"— écoute de « {tap.name} » pendant {seconds} s : frappe ce que tu veux —")
    tap.take(); time.sleep(seconds)
    evts = tap.take()
    if not evts:
        print(f"  {WARN} rien reçu" + (" (à part l'horloge MIDI)" if tap.clock else "")); return
    t0 = evts[0]["t"]
    print("\n".join(_seq_lines(evts, t0, limit=40)))
    print(f"\n  notes : {sorted({e['n'] for e in evts if e['k'] == D.NOTE})}")
    ccs = sorted({e['n'] for e in evts if e['k'] == D.CC})
    print(f"  CC    : {ccs if ccs else 'aucun'}")


def learn(tap, kit, only=None, previous=None):
    steps_all = [s for s in D.STEPS if not only or s["id"] in only]
    if only and not steps_all:
        sys.exit(f"étapes inconnues : {', '.join(only)}\n  connues : {', '.join(s['id'] for s in D.STEPS)}")
    print(f"\n{B}« {tap.name} » — je nomme, tu frappes, tu appuies sur Entrée.{R}")
    print(f"{DIM}  Frappe QUAND tu veux avant d'appuyer : il n'y a pas de chrono.")
    print("  Entrée sans avoir frappé = cet élément n'existe pas sur ce kit → passé.")
    print(f"  « r » puis Entrée = refaire le précédent. Ctrl-C = arrêter (le mesuré est gardé).{R}")
    if only:
        print(f"{DIM}  (reprise de {len(steps_all)} étape(s), le reste de la mesure est conservé){R}")
    print()
    steps = dict((previous or {}).get("steps") or {})
    i = 0
    try:
        while i < len(steps_all):
            st = steps_all[i]
            tap.take()
            t0 = time.monotonic()
            ans = input(f"  ▸ frappe {ASK.get(st['id'], st['id'])} … ").strip().lower()
            if ans == "r" and i > 0:
                steps.pop(steps_all[i - 1]["id"], None); i -= 1
                print(f"    {DIM}(on refait le précédent){R}"); continue
            evts = tap.take()
            for e in evts:                                    # l'heure du bridge est celle de Reaper : on relativise
                e["t"] = e["t"] if e["t"] < 1e6 else t0 + (e["t"] - evts[0]["t"])
            steps[st["id"]] = {"events": evts}
            s, others = D.strike(evts, st.get("pick", "loudest"))
            if s is None:
                print(f"    {WARN} rien entendu — passé" + (f" {DIM}(de l'aftertouch, mais aucune note){R}" if any(e["k"] == D.POLY for e in evts) else ""))
            else:
                note, vel = s
                print(f"    {OK} note {B}{note}{R} · vélocité {vel}" + (f" · aussi {', '.join(f'{n}@{v}' for n, v in others)}" if others else ""))
                if others and others[0][1] >= vel * D.TWIN_RATIO:
                    print(f"    {WARN} deux notes fortes dans le même geste — la séquence est gardée")
                elif vel <= D.WEAK_VEL:
                    print(f"    {WARN} frappe très faible (vélocité {vel}) : zone réelle, ou diaphonie d'un pad voisin ?")
                if len(evts) > 1:
                    print("\n".join(_seq_lines(evts, min(e["t"] for e in evts))))
            i += 1
    except (KeyboardInterrupt, EOFError):
        print("\n  (interrompu)")
    measure = {"port": tap.name, "kit": (kit or {}).get("id"), "measured_at": time.strftime("%Y-%m-%d"),
               "clock": bool(tap.clock or (previous or {}).get("clock")), "steps": steps}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(measure, open(OUT, "w", encoding="utf8"), indent=1, ensure_ascii=False)
    print(f"\n  mesure écrite : {os.path.relpath(OUT, ROOT)}")
    return measure


def load_measure():
    if not os.path.isfile(OUT):
        sys.exit("aucune mesure — lance d'abord --learn")
    m = json.load(open(OUT, encoding="utf8"))
    if "steps" not in m:
        sys.exit("mesure d'un ancien format (avant le 2026-09-23) — refais --learn")
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", default="Nitro", help="fragment du nom de l'entrée MIDI (défaut : Nitro)")
    ap.add_argument("--kit", default=None, help="id du descripteur à comparer/corriger (défaut : identifié par le nom)")
    ap.add_argument("--learn", action="store_true"); ap.add_argument("--only", default="")
    ap.add_argument("--compare", action="store_true"); ap.add_argument("--write", action="store_true")
    ap.add_argument("--seconds", type=int, default=20); ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for addr, client, port in ports():
            print(f"  {addr:<7} {client:<28} {port}")
        return
    if a.compare or a.write:
        m = load_measure()
        kid = a.kit or m.get("kit") or drumkits.identify(m.get("port"))[0]
        kit = drumkits.get(kid)
        rep = D.analyse(m)
        cmp_ = D.compare(rep, kit) if kit else None
        render(rep, cmp_, kit)
        if a.write:
            try:
                desc = D.descriptor(rep, m, kit)
                path = D.write(desc)
            except ValueError as e:
                sys.exit(f"  {KO} rien n'est écrit : {e}")
            print(f"  {OK} {os.path.relpath(path, ROOT)} écrit ({len(desc['map'])} éléments, source measured / confidence verified)")
        sys.exit(1 if cmp_ and cmp_["bad"] else 0)
    tap = open_tap(a.port)
    try:
        kid, auto, fb = (a.kit, False, False) if a.kit else drumkits.identify(tap.name)
        kit = None if fb and not a.kit else drumkits.get(kid)
        if a.learn:
            only = [s.strip() for s in a.only.split(",") if s.strip()]
            prev = json.load(open(OUT, encoding="utf8")) if only and os.path.isfile(OUT) else None
            if prev is not None and "steps" not in prev:
                prev = None
            m = learn(tap, kit, only=only, previous=prev)
            if m["steps"]:
                rep = D.analyse(m)
                render(rep, D.compare(rep, kit) if kit else None, kit)
                print(f"\n  pour graver : ./tools/check-drums.py --write" + (f" --kit {kit['id']}" if kit else "  (crée un descripteur)"))
        else:
            listen(tap, a.seconds)
    finally:
        tap.close()


if __name__ == "__main__":
    main()
