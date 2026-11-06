#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesure la LATENCE d'un changement de scène AU VRAI PIED — en observateur passif.

    ./tools/check-scene-latency.py            # 3 min : tu joues et tu changes de scène au pied
    ./tools/check-scene-latency.py 600        # 10 min

POURQUOI CE SCRIPT EXISTE
Le 2026-09-21, « le passage SW1 vers SW2 a de la latence, c'est vraiment relou ». Tout ce
qu'on mesurait jusque-là partait d'une INJECTION (le rack se parle à lui-même) ou d'un ton de test.
Ici on regarde le vrai geste : un SECOND aseqdump sur le port du pédalier (le séquenceur ALSA
accepte plusieurs lecteurs) date chaque message de la puce, et on date à la milliseconde l'écriture
de presets/.command.json (le bridge a décidé), de .command-ack.json (Reaper l'a prise) et de
.golem-rig.log (golem_rig a fini d'appliquer). RIEN n'est envoyé au rack ni à Reaper : on peut le
lancer pendant une prise.

Ce qu'il NE mesure PAS : le moment où le son change vraiment (c'est tools/check-scene-gap.py), ni
les ~8 ms de la carte. Budget visé (docs/audit-2026-09-21-latence-scenes.md) : appui -> scène
appliquée <= 40 ms au 95e centile.
"""
import json, os, statistics, subprocess, sys, tempfile, threading, time

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "presets") + os.sep
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
OUT = os.path.join(tempfile.gettempdir(), "golem-scene-latency-%d.ndjson" % int(time.time()))
print("observateur passif, %.0f s — joue, et change de scène AU PIED. Brut : %s" % (DUR, OUT))


out=open(OUT,'a',buffering=1)
def emit(kind, **kw): out.write(json.dumps({'t': time.time(), 'k': kind, **kw})+'\n')
port=None
for ln in subprocess.run(['ps','-o','args=','-C','aseqdump'],capture_output=True,text=True).stdout.splitlines():
    p=ln.split()
    if '-p' in p: port=p[p.index('-p')+1]
proc=subprocess.Popen(['aseqdump','-p',port],stdout=subprocess.PIPE,text=True,bufsize=1) if port else None
def rd():
    for ln in proc.stdout:
        ln=ln.strip()
        if ln and not ln.startswith(('Waiting','Source')) and 'Clock' not in ln and 'Active Sensing' not in ln:
            emit('midi', line=' '.join(ln.split()[1:]))
if proc: threading.Thread(target=rd,daemon=True).start()
emit('start', port=port)
files={'cmd':'.command.json','ack':'.command-ack.json','rig':'.golem-rig.log','live':'.live.json'}
last={k:None for k in files}
end=time.time()+DUR
while time.time()<end:
    for k,f in files.items():
        try: m=os.stat(ROOT+f).st_mtime_ns
        except OSError: continue
        if m!=last[k]:
            first=last[k] is None; last[k]=m
            if first: continue
            try: body=open(ROOT+f).read()
            except OSError: body=''
            if k=='cmd':
                try: c=json.loads(body); emit('cmd', action=c.get('action'), scene=c.get('scene'), seq=c.get('seq'), on=c.get('on'))
                except ValueError: emit('cmd', raw=body[:80])
            elif k=='ack':
                try: emit('ack', seq=json.loads(body).get('seq'))
                except ValueError: pass
            elif k=='rig': emit('rig', last=body.strip().split('\n')[-2:][0][:90] if body.strip() else '')
            else: emit('live', body=body.replace('\n','')[:80])
    time.sleep(0.003)
if proc: proc.terminate()
emit('end')

rows = [json.loads(l) for l in open(OUT)]
res, slow = {}, []
for i, r in enumerate(rows):
    if r["k"] == "midi" and "Control change" in r["line"] and any(", controller %d," % c in r["line"] for c in range(20, 25)):
        t = r["t"]; grp = [x for x in rows[i:i + 80] if 0 <= x["t"] - t < 2.5]
        cmd = next((x for x in grp if x["k"] == "cmd" and x.get("action") in ("scene_apply", "rig_recall")), None)
        if not cmd:
            continue
        ack = next((x for x in grp if x["k"] == "ack" and x.get("seq") == cmd["seq"]), None)
        rigs = [x for x in grp if x["k"] == "rig" and x["t"] > cmd["t"] and x["t"] - cmd["t"] < 0.5]
        row = ((cmd["t"] - t) * 1000, (ack["t"] - t) * 1000 if ack else None,
               (max(x["t"] for x in rigs) - t) * 1000 if rigs else None, cmd.get("action"))
        res.setdefault(cmd.get("scene"), []).append(row)
        if row[0] > 150 or (row[2] or 0) > 250:
            slow.append((cmd.get("scene"), row))
print()
for sc, v in sorted(res.items(), key=lambda kv: str(kv[0])):
    c = [a for a, _, _, _ in v]; k = [b for _, b, _, _ in v if b]; g = [d for _, _, d, _ in v if d]
    print("vers %s : %2d appuis | commande +%3.0f ms (max %4.0f) | prise par Reaper +%3.0f ms | appliquée +%3.0f ms (max %4.0f)%s"
          % (sc, len(v), statistics.median(c), max(c), statistics.median(k) if k else -1,
             statistics.median(g) if g else -1, max(g) if g else -1,
             "  ⚠ REBUILD" if any(a == "rig_recall" for *_, a in v) else ""))
if not res:
    print("aucun changement de scène au pied vu pendant l'écoute.")
for sc, row in slow:
    print("  LENT vers %s : commande +%.0f ms, appliquée %s" % (sc, row[0], ("+%.0f ms" % row[2]) if row[2] else "?"))
