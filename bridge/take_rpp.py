# SPDX-License-Identifier: GPL-3.0-or-later
"""Une PRISE en projet REAPER (.rpp) — « ouvrir cette prise dans REAPER ou mon DAW » (2026-10-11).

Le rack enregistre une prise comme un dossier `recordings/perf-<ts>/` (une .wav par lane + `take.json`) ou une .wav
à plat (mode mix, sidecar .wav.json). Il n'existait aucun .rpp par prise. Ici on en ÉCRIT un, minimal et honnête :
une piste par fichier, un item par piste posé à 0 et long de la durée du fichier, le tempo du manifeste, le
sample-rate lu dans l'en-tête WAV — et des chemins RELATIFS : le .rpp est écrit DANS le dossier de la prise, à côté
des .wav, pour que le dossier entier s'ouvre tel quel sur n'importe quelle machine. Aucun effet, aucun plugin :
c'est l'audio tel qu'il a été pris, pas le rig. Les captures MIDI (.mid) ne sont pas posées (REAPER les veut
inline dans le projet) ; elles restent à côté, et c'est dit dans le nom des pistes manquantes."""
import os
import time

from . import config as C
from .golog import get

log = get("take-rpp")
RECORDINGS = os.path.join(C.ROOT, "recordings")


def _q(s):
    """Une chaîne entre guillemets, au format RPP (pas de guillemet dedans)."""
    return '"' + str(s or "").replace('"', "'") + '"'


def _labels(files, man):
    lab = (man or {}).get("labels") if isinstance((man or {}).get("labels"), dict) else {}
    out = {}
    for f in files:
        base = f[:-4] if f.lower().endswith(".wav") else f
        out[f] = str(lab.get(f) or lab.get(base) or base)
    return out


def build_rpp(files, man=None, sample_rate=None, lengths=None, project_name="take"):
    """Le texte d'un projet REAPER : `files` = noms de fichiers RELATIFS au dossier du .rpp (une piste chacun),
    `lengths` = {fichier: secondes}, `man` = le manifeste de la prise (bpm, labels, started_at). Pur."""
    man = man or {}
    bpm = man.get("bpm")
    try:
        bpm = float(bpm) if bpm and 20 <= float(bpm) <= 400 else 120.0
    except (TypeError, ValueError):
        bpm = 120.0
    sr = int(sample_rate or 48000)
    labels = _labels(files, man)
    lengths = lengths or {}
    lines = [f'<REAPER_PROJECT 0.1 "7.0/golem" {int(time.time())}',
             f"  TEMPO {bpm:g} 4 4",
             f"  SAMPLERATE {sr} 0 0",
             f"  NOTES 0 2",
             f"    |golem take {_q(project_name)[1:-1]} — audio as recorded, no effects. "
             f"{('Started ' + str(man.get('started_at'))) if man.get('started_at') else ''}",
             "  >"]
    for f in files:
        L = float(lengths.get(f) or 0.0)
        lines += ["  <TRACK",
                  f"    NAME {_q(labels[f])}",
                  "    <ITEM",
                  "      POSITION 0",
                  f"      LENGTH {L:.6f}",
                  f"      NAME {_q(f)}",
                  "      <SOURCE WAVE",
                  f"        FILE {_q(f)}",
                  "      >",
                  "    >",
                  "  >"]
    lines.append(">")
    return "\n".join(lines) + "\n"


def export(name):
    """Écrit le .rpp d'une prise (`perf-<ts>` ou `<fichier>.wav`) à côté de son audio ; rend le chemin du .rpp.
    ValueError si la prise n'existe pas."""
    from . import takes
    base = os.path.basename(str(name or ""))
    if not base or base.startswith("."):
        raise ValueError("bad take name")
    p = os.path.join(RECORDINGS, base)
    if os.path.isdir(p) and base.startswith("perf-"):
        wavs = sorted(f for f in os.listdir(p) if f.lower().endswith(".wav"))
        if not wavs:
            raise ValueError("this take has no audio file")
        man = takes._read_json(os.path.join(p, "take.json")) or {}
        folder, files, out = p, wavs, os.path.join(p, base + ".rpp")
    elif os.path.isfile(p) and base.lower().endswith(".wav"):
        man = takes._read_json(p + ".json") or {}
        folder, files, out = RECORDINGS, [base], os.path.join(RECORDINGS, base[:-4] + ".rpp")
    else:
        raise ValueError("take not found")
    lengths, sr = {}, None
    for f in files:
        fp = os.path.join(folder, f)
        try:
            lengths[f] = float(takes.wav_seconds(fp) or 0.0)
        except Exception:
            lengths[f] = 0.0
        if sr is None:
            try:
                sr = (takes.wav_info(fp) or {}).get("sample_rate")
            except Exception:
                sr = None
    text = build_rpp(files, man, sr, lengths, project_name=base)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    log.info(f"projet REAPER écrit : {out} ({len(files)} piste(s))")
    return out
