#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vérifie que les ÉCRITURES de paramètres ATTERRISSENT — écrire, relire, comparer.

    ./tools/check-params.py                 # tous les blocs de la livemap, ~3 s/param
    ./tools/check-params.py --block wah-1   # un seul bloc
    ./tools/check-params.py --dry-run       # hors rig : autotest des parseurs sur les fichiers locaux

POURQUOI CE SCRIPT EXISTE
Le bloc sample a été INTÉGRALEMENT MUET parce qu'un slider JSFX à minimum négatif est BIPOLAIRE
pour Reaper : sur <-1,127,1>, la normalisée 0,5 vaut zéro — la formule linéaire (v-min)/(max-min)
écrivait n'importe quoi (0,031 envoyé, −1 relu, chaque note traitée comme un « stop »). La panne
jumelle : un index de send/FX faux fait de l'écriture un NO-OP SILENCIEUX (24 prises perdues au
perf-rec). Dans les deux cas la valeur finale SEMBLE posée quand on ne relit pas. La seule sonde
honnête est celle qui a démasqué le sampler : écrire en VALEUR BRUTE (TrackFX_SetParam, insensible
au taper), relire, comparer — c'est exactement ce que fait la commande `fxset`.

CE QU'IL FAIT
Pour chaque bloc de presets/.livemap.json (bloc → piste/fx/params, écrit par golem_rig au
build) : `fxparams` liste les paramètres RÉELS du FX (index, valeur, min/max vus PAR REAPER),
puis pour chaque potard mappé on écrit min, milieu, max en BRUT via `fxset` et on relit —
écart > tolérance = échec. Au passage : livemap ≠ réel (pmin/pmax qui ont bougé) = livemap
périmée, et un FX ambigu (deux FX au même nom sur la piste) est SAUTÉ plutôt que risqué.

GARDE-FOUS
· REFUSE de tourner pendant une prise (presets/.perf.json recording) — on ne balaye pas les
  potards d'un enregistrement.
· RESTAURE chaque paramètre à sa valeur d'origine, même sur échec ou Ctrl-C (try/finally).
⚠ ÇA S'ENTEND : les potards balayent réellement min/milieu/max pendant ~1 s chacun. À lancer
entre deux morceaux, jamais pendant qu'on joue.

CE QU'IL NE PEUT PAS VOIR
Que la valeur posée fait le bon SON (mix à 100 % peut être câblé à l'envers dans le plugin), ni
les blocs hors livemap (whammy-dt = MIDI externe, moteurs synthé non estampillés golem:).
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS = os.path.join(ROOT, "presets")
BRIDGE = os.environ.get("GOLEM_URL", "http://localhost:8770")
FXPARAMS_LOG = os.path.join(PRESETS, ".fxparams.log")
PEAKS_JSON = os.path.join(PRESETS, ".peaks.json")
OK, KO, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m⚠\033[0m"
fails = []

# à restaurer QUOI QU'IL ARRIVE : [(track, needle, fx_index, param_index, valeur_d_origine)]
RESTORES = []

# formats EXACTS de golem_apply.lua (fxparams/fxset écrivent presets/.fxparams.log)
RE_FX = re.compile(r"^FX (\d+) : (.+)$")
RE_PARAM = re.compile(r"^\s*\[(\d+)\]\s+(.*?)\s+val=(\S+)\s+norm=(\S+)\s+min=(\S+)\s+max=(\S+)")
RE_FXSET = re.compile(r"^FX (\d+) \[(\d+)\] : (\S+) -> (?:val|norm) (\S+) -> (\S+) "
                      r"\(retour=(\S+), min=(\S+) max=(\S+)\)")


def check(cond, label, detail=""):
    print(f"  {OK if cond else KO} {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(label)
    return cond


def _acked(seq):
    from bridge.commands import _ack_path
    try:
        return int(json.load(open(_ack_path(seq))).get("seq") or 0) >= seq
    except (OSError, ValueError):
        return None


def send_cmd(cmd, outfile, timeout=8.0):
    """write_command (rend le `seq`, n'écrase jamais un slot pas encore lu) → attend l'ACK de
    consommation de golem_watch (.command-ack.json) → attend que le fichier de sortie CHANGE.
    L'ack prouve « lu », le fichier prouve « fait » — on veut les deux."""
    sys.path.insert(0, ROOT)
    from bridge.commands import write_command
    try:
        before = os.stat(outfile).st_mtime_ns
    except OSError:
        before = None
    seq = write_command(cmd)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if os.stat(outfile).st_mtime_ns != before:
                time.sleep(0.08)              # l'écriture Lua n'est pas atomique : petite grâce
                return open(outfile, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
        time.sleep(0.1)
    if _acked(seq) is False:
        print(f"    (commande « {cmd.get('action')} » jamais consommée — golem_watch/Reaper "
              "éteint ? gel SETTLE post-rebuild ?)")
    return None


def parse_fxparams(text):
    """{fx_index: {"name": str, "params": {p: (val, min, max)}}} depuis .fxparams.log."""
    out, cur = {}, None
    for line in (text or "").splitlines():
        m = RE_FX.match(line)
        if m:
            cur = int(m.group(1))
            out[cur] = {"name": m.group(2).strip(), "params": {}}
            continue
        m = RE_PARAM.match(line)
        if m and cur is not None:
            try:
                out[cur]["params"][int(m.group(1))] = (
                    float(m.group(3)), float(m.group(5)), float(m.group(6)))
            except ValueError:
                pass                          # val « -inf » etc. : paramètre injouable, ignoré
    return out


def parse_fxset(text):
    """(fx, param, before, after, min, max) de la 1re ligne fxset — None si illisible."""
    for line in (text or "").splitlines():
        m = RE_FXSET.match(line)
        if m:
            try:
                return (int(m.group(1)), int(m.group(2)), float(m.group(3)),
                        float(m.group(5)), float(m.group(7)), float(m.group(8)))
            except ValueError:
                return None
    return None


def fxparams(track, needle=""):
    txt = send_cmd({"action": "fxparams", "track": track, "fx": needle}, FXPARAMS_LOG)
    return parse_fxparams(txt) if txt is not None else None


def fxset_raw(track, needle, param, value):
    """Écrit UNE valeur BRUTE (TrackFX_SetParam — insensible au taper) puis relit."""
    txt = send_cmd({"action": "fxset", "track": track, "fx": needle,
                    "param": param, "value": value}, FXPARAMS_LOG)
    return parse_fxset(txt) if txt is not None else None


def peaks_track_map():
    """{numéro de piste 1-based: nom} via la sonde `peaks` (read-only) — la livemap ne porte
    que le NUMÉRO de piste, fxparams/fxset veulent son NOM ; peaks nomme dans l'ordre."""
    txt = send_cmd({"action": "peaks", "clear": False}, PEAKS_JSON)
    if txt is None:
        return None
    out = {}
    try:
        for row in json.loads(txt):
            m = re.match(r"^(\d+) (.*)$", row.get("track") or "")
            if m:
                out[int(m.group(1))] = m.group(2)
    except ValueError:
        return None
    return out


def test_block(bid, ent, tmap, tol_pct):
    tnum, fxi = ent.get("track"), ent.get("fx")
    tname = tmap.get(tnum)
    if not check(bool(tname), f"{bid} : piste n°{tnum} résolue en nom",
                 tname or "absente de peaks — livemap périmée ? (re-recall du preset)"):
        return
    listing = fxparams(tname)
    if not check(listing is not None, f"{bid} : fxparams répond sur « {tname} »"):
        return
    info = listing.get(fxi)
    if not check(info is not None, f"{bid} : le FX #{fxi} de la livemap existe encore",
                 (info or {}).get("name") or
                 f"la piste ne porte que les FX {sorted(listing)} — livemap périmée"):
        return
    needle = info["name"].lower()
    # fxset prend le PREMIER FX dont le nom CONTIENT le motif : si un FX plus haut dans la
    # chaîne matcherait aussi, on écrirait chez lui. On saute — jamais d'écriture à l'aveugle.
    for i in sorted(listing):
        if i < fxi and needle in listing[i]["name"].lower():
            check(False, f"{bid} : cible fxset non ambiguë",
                  f"le FX #{i} « {listing[i]['name']} » matche aussi — bloc sauté")
            return
    for pid, spec in sorted((ent.get("params") or {}).items()):
        p = spec.get("p")
        got = info["params"].get(p)
        if got is None:
            check(False, f"{bid}.{pid} [p{p}] : le paramètre existe",
                  f"index absent du FX ({len(info['params'])} params)")
            continue
        orig, mn, mx = got
        # livemap ≠ réel : pmin/pmax figés au build qui ont bougé = livemap périmée (le même
        # symptôme que l'EXP qui pousse un potard fantôme).
        if abs((spec.get("pmin") or 0) - mn) > 1e-4 or abs((spec.get("pmax") or 0) - mx) > 1e-4:
            print(f"  {WARN} {bid}.{pid} : plage livemap [{spec.get('pmin')};{spec.get('pmax')}]"
                  f" ≠ réelle [{mn};{mx}] — livemap périmée ?")
        if mx <= mn:
            print(f"  ·   {bid}.{pid} [p{p}] : plage nulle [{mn};{mx}] — rien à balayer")
            continue
        tol = max(tol_pct * (mx - mn), 1e-4)
        RESTORES.append((tname, needle, fxi, p, orig))      # AVANT la première écriture
        results, worst = [], 0.0
        for want in (mn, (mn + mx) / 2.0, mx):
            res = fxset_raw(tname, needle, p, want)
            if res is None:
                results.append((want, None))
                continue
            rfx, rp, _, after, _, _ = res
            if rfx != fxi or rp != p:
                check(False, f"{bid}.{pid} : fxset a visé le bon FX",
                      f"écrit sur FX {rfx} p{rp} au lieu de FX {fxi} p{p} — STOP sur ce bloc")
                return
            results.append((want, after))
            worst = max(worst, abs(after - want))
        missing = [w for w, a in results if a is None]
        if missing:
            check(False, f"{bid}.{pid} [p{p}] : fxset répond", f"pas de retour pour {missing}")
            continue
        detail = " · ".join(f"{w:g}→{a:g}" for w, a in results)
        check(worst <= tol, f"{bid}.{pid} [p{p}] balaye min/milieu/max en brut",
              detail + ("" if worst <= tol else
                        f"  (écart max {worst:g} > tolérance {tol:g} — l'écriture n'atterrit "
                        "pas : taper ? index ? API qui refuse ?)"))


def restore_all():
    """Repose CHAQUE paramètre touché — même sur échec, même sur Ctrl-C. Et le vérifie."""
    if not RESTORES:
        return
    print("\n── Restauration ──")
    bad = 0
    for tname, needle, fxi, p, orig in RESTORES:
        res = fxset_raw(tname, needle, p, orig)
        if res is None or abs(res[3] - orig) > max(1e-4, abs(orig) * 0.001):
            bad += 1
            print(f"  {KO} « {tname} » FX {fxi} p{p} : PAS reposé à {orig:g}"
                  + (f" (relu {res[3]:g})" if res else " (fxset muet)"))
    if bad:
        fails.append("restauration incomplète")
        print(f"  {KO} {bad} paramètre(s) NON restauré(s) — re-recall du preset pour repartir propre")
    else:
        print(f"  {OK} {len(RESTORES)} paramètre(s) reposé(s) à l'identique")


# ── autotest hors rig ───────────────────────────────────────────────────────────────────────
FXSET_SAMPLE = "FX 1 [5] : 162.0 -> val 200 -> 200.0 (retour=true, min=0.0 max=1000000000.0)"


def dry_run():
    print("── dry-run : autotest des parseurs (ne prouve RIEN sur le rack) ──")
    r = parse_fxset(FXSET_SAMPLE)
    check(r == (1, 5, 162.0, 200.0, 0.0, 1000000000.0), "parse fxset (échantillon figé)", str(r))
    if os.path.exists(FXPARAMS_LOG):
        d = parse_fxparams(open(FXPARAMS_LOG, encoding="utf-8", errors="replace").read())
        nfx = len(d)
        nprm = sum(len(v["params"]) for v in d.values())
        check(nfx > 0 and nprm > 0, "parse fxparams sur presets/.fxparams.log (vrai fichier)",
              f"{nfx} FX, {nprm} params")
    else:
        print("  ·   presets/.fxparams.log absent ici (normal hors rack)")
    try:
        lm = json.load(open(os.path.join(PRESETS, ".livemap.json")))
        blocks = lm.get("blocks") or {}
        check(all("track" in b and "fx" in b for b in blocks.values()),
              "livemap lisible (track/fx par bloc)",
              f"preset « {lm.get('preset')} », {len(blocks)} bloc(s) : "
              + ", ".join(list(blocks)[:6]))
    except (OSError, ValueError):
        print("  ·   presets/.livemap.json absent/illisible ici (normal hors rack)")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description="Écrire-relire chaque potard mappé (sonde fxset).")
    ap.add_argument("--block", help="ne tester que ce bloc (id livemap, ex. wah-1)")
    ap.add_argument("--tol", type=float, default=0.02,
                    help="tolérance en fraction de la plage (défaut 0.02 = 2 %%)")
    ap.add_argument("--dry-run", action="store_true",
                    help="autotest local des parseurs, sans toucher au rig")
    a = ap.parse_args()
    if a.dry_run:
        return dry_run()

    # GARDE-FOU : jamais pendant une prise. La source de vérité est le fichier du Lua, pas
    # l'état optimiste du bridge.
    try:
        perf = json.load(open(os.path.join(PRESETS, ".perf.json")))
    except (OSError, ValueError):
        perf = {}
    if perf.get("recording"):
        sys.exit(f"{KO} une prise TOURNE ({perf.get('file')}) — on ne balaye pas les potards "
                 "d'un enregistrement. Réessayer après le stop.")

    try:
        lm = json.load(open(os.path.join(PRESETS, ".livemap.json")))
    except (OSError, ValueError):
        sys.exit(f"{KO} presets/.livemap.json absent/illisible — recall d'abord un preset.")
    blocks = lm.get("blocks") or {}
    if a.block:
        if a.block not in blocks:
            sys.exit(f"{KO} bloc « {a.block} » absent de la livemap. Disponibles : "
                     + ", ".join(sorted(blocks)))
        blocks = {a.block: blocks[a.block]}
    if not blocks:
        sys.exit(f"{KO} livemap vide (preset sans blocs mappés ?) — rien à tester.")
    print(f"preset « {lm.get('preset')} » · {len(blocks)} bloc(s) · "
          f"{sum(len(b.get('params') or {}) for b in blocks.values())} potard(s) mappé(s)")
    print(f"{WARN} ça va s'ENTENDRE : chaque potard balaye min/milieu/max ~1 s.\n")

    tmap = peaks_track_map()
    if tmap is None:
        sys.exit(f"{KO} la sonde peaks ne répond pas — Reaper/golem_watch tourne ?")

    try:
        for bid, ent in sorted(blocks.items()):
            test_block(bid, ent, tmap, a.tol)
    finally:
        restore_all()

    print("\n" + "=" * 64)
    if fails:
        print(f"{KO} {len(fails)} échec(s) : " + " · ".join(fails[:6]))
    else:
        print(f"{OK} chaque écriture atterrit là où on la vise, sur toute la plage.")
    print(f"\n{WARN} Non vérifié ici : que la valeur posée fait le bon SON, et les blocs hors "
          "livemap\n(whammy-dt = MIDI externe ; moteurs synthé non estampillés golem:).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
