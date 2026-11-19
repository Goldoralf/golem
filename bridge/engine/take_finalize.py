#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'ASSEMBLEUR d'une prise du Golem Engine (docs/ardour-plan.md §7d, lot 3). Lancé par le veilleur du moteur à
l'arrêt d'une prise, HORS de lui : assembler une répète d'une heure ne doit figer ni les scènes ni les stomps.

Ardour écrit un fichier MONO PAR CANAL dans sa session (« Mix-1%L.wav », « Mix-1%R.wav ») ; golem range une prise
comme REAPER le fait — `recordings/perf-<date>/<Piste>.wav` (multipiste) ou `recordings/perf-<date>.wav` (mix seul),
un fichier stéréo par piste stéréo. Le veilleur dit ce qu'il a écrit dans presets/.engine-take.json :
    {root, file, mode, started_at, sample_rate,
     tracks: [{name, segments: [{pos, len, files: [gauche, droite] | [mono]}]}]}
Ici : deux fichiers -> un WAV stéréo (ffmpeg, sans ré-encodage du son : mêmes échantillons, même format) ; un seul ->
déplacé. Une prise mise EN PAUSE par un rappel de preset (le moteur ne refait pas ses routes en enregistrant) porte
plusieurs SEGMENTS par piste : chacun est posé à sa position (en échantillons, comptée depuis le premier segment de
la prise, toutes pistes confondues) et le trou reste du silence — les pistes d'une prise restent alignées entre elles. Puis presets/.perf.json dit la prise FINIE — c'est ce que le bridge attend pour écrire take.json. Une erreur
est dite dans ce même fichier (`error`), jamais tue.

Autonome exprès (bibliothèque standard seulement) : le veilleur le lance par son chemin, sans importer le bridge.

    take_finalize.py <presets/.engine-take.json>
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import wave


def sample_format(path):
    """Le codec PCM du fichier source (16, 24 ou 32 bits flottants) : la prise garde le format du moteur."""
    try:
        with wave.open(path, "rb") as w:
            return {2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}.get(w.getsampwidth(), "pcm_s24le")
    except (wave.Error, OSError, EOFError):
        return "pcm_f32le"                       # `wave` ne lit pas le flottant : c'est le format par défaut d'Ardour


def command(segments, origin, target, ffmpeg="ffmpeg", codec=None):
    """La commande ffmpeg d'UNE piste : chaque segment joint en stéréo s'il a deux fichiers, retardé de sa position
    (en échantillons, depuis `origin`), puis la somme — des segments qui ne se recouvrent pas, donc sans mélange."""
    inputs, chains, outs = [], [], []
    for i, seg in enumerate(segments):
        first = len(inputs) // 2
        for f in seg["files"]:
            inputs += ["-i", f]
        n = len(seg["files"])
        src = f"[{first}:a]" if n == 1 else f"[{first}:a][{first + 1}:a]join=inputs=2:channel_layout=stereo[j{i}];[j{i}]"
        delay = max(0, int(seg.get("pos") or 0) - origin)
        # deux segments qui se RECOUVRENT (la reprise d'une prise en pause peut partir quelques millisecondes avant la
        # fin du segment d'avant) : le premier est coupé où commence le suivant — sommés, ils doubleraient le son
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        # CHAQUE segment est coupé à la longueur de SA RÉGION : le fichier du moteur en contient davantage (il écrit
        # encore un instant après la pause — mesuré 2026-11-17 : une seconde de DI doublée à la reprise)
        keep = int(seg.get("len") or 0)
        if nxt:
            room = int(nxt.get("pos") or 0) - int(seg.get("pos") or 0)
            keep = min(keep, room) if keep > 0 else room
        cut = f"atrim=end_sample={keep}," if keep > 0 and len(segments) > 1 else ""
        chains.append(f"{src}{cut}adelay=delays={delay}S:all=1[s{i}]" if delay else f"{src}{cut}anull[s{i}]")
        outs.append(f"[s{i}]")
    graph = ";".join(chains)
    graph += f";{''.join(outs)}amix=inputs={len(outs)}:normalize=0:dropout_transition=0[a]" if len(outs) > 1 else ""
    last = "[a]" if len(outs) > 1 else "[s0]"
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-map", last,
            "-c:a", codec or sample_format(segments[0]["files"][0]), target]


def assemble(segments, origin, target, ffmpeg="ffmpeg", codec=None):
    """Un fichier de la prise. Un seul segment mono qui part à l'origine : simplement déplacé. Lève en cas d'échec.
    `codec` impose le format (un rendu que le bridge relit : voir finalize) — alors jamais de simple déplacement."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    files = [f for seg in segments for f in seg["files"]]
    if not codec and len(segments) == 1 and len(files) == 1 and int(segments[0].get("pos") or 0) <= origin:
        try:
            os.replace(files[0], target)
        except OSError:
            # Windows : le moteur garde ses fichiers de prise OUVERTS — ni renommage ni suppression (WinError 32). On
            # copie, et la source reste au moteur ; shutil.move copiait puis LEVAIT sur la suppression, et la prise
            # entière était perdue à mi-chemin (2026-11-19, banc Windows : 3 fichiers sur 6, « could not be assembled »)
            tmp = target + ".part.wav"
            shutil.copyfile(files[0], tmp)
            os.replace(tmp, target)
            with contextlib.suppress(OSError):
                os.remove(files[0])
        return
    tmp = target + ".part.wav"
    r = subprocess.run(command(segments, origin, tmp, ffmpeg, codec), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-300:])
    os.replace(tmp, target)
    for f in files:
        try:
            os.remove(f)
        except OSError:
            pass


def read_smf(data):
    """Les messages de jeu d'un Standard MIDI File (octets) : (division, [(tick, octets du message)]), triés. Notes,
    contrôleurs, pitch bend, pression, programmes ; les méta et les SysEx sont sautés. Lève ValueError."""
    if len(data) < 14 or data[:4] != b"MThd":
        raise ValueError("not a Standard MIDI File")
    division = int.from_bytes(data[12:14], "big")
    if division >= 0x8000 or division == 0:
        raise ValueError("unsupported time division")
    out, i = [], 8 + int.from_bytes(data[4:8], "big")
    while i + 8 <= len(data):
        kind, size = data[i:i + 4], int.from_bytes(data[i + 4:i + 8], "big")
        j, end = i + 8, i + 8 + size
        i = end
        if kind != b"MTrk":
            continue
        tick, status = 0, 0

        def vlq(j):
            v = 0
            while True:
                b = data[j]
                j += 1
                v = (v << 7) | (b & 0x7F)
                if not b & 0x80:
                    return v, j
        while j < end:
            d, j = vlq(j)
            tick += d
            b = data[j]
            if b == 0xFF:                                  # méta : type, longueur, données
                n, k = vlq(j + 2)
                j = k + n
            elif b in (0xF0, 0xF7):                        # SysEx
                n, k = vlq(j + 1)
                j = k + n
            else:
                if b & 0x80:
                    status, j = b, j + 1
                n = 1 if (status & 0xF0) in (0xC0, 0xD0) else 2
                out.append((tick, bytes([status]) + data[j:j + n]))
                j += n
    out.sort(key=lambda e: e[0])
    return division, out


def write_midi(segments, origin, rate, bpm, target, ppq=960):
    """Le MIDI joué pendant la prise, en UN fichier (format 0) calé sur la prise : le tick 0 est son premier échantillon.
    Chaque segment est un fichier du moteur, en temps musical au tempo de la session (`bpm`, fixe) : on le remet en
    secondes, à sa place, puis en ticks au même tempo — écrit en tête, comme le fait golem_perfrec sous REAPER, pour
    que la partition retombe sur la grille. Rend le nombre de NOTES ; zéro : aucun fichier (un fichier sans une frappe
    est un mensonge bien formé — docs/pitfalls)."""
    bpm = float(bpm) if bpm and float(bpm) > 0 else 120.0
    events = []
    for seg in segments:
        with open(seg["files"][0], "rb") as f:
            division, evs = read_smf(f.read())
        base = max(0, int(seg.get("pos") or 0) - origin) / float(rate)
        length = int(seg.get("len") or 0) / float(rate)
        for tick, msg in evs:
            t = tick / division * 60.0 / bpm
            if length and t > length + 0.5:               # au-delà de la région : pas dans la prise
                continue
            events.append((round((base + t) * bpm / 60.0 * ppq), msg))
    events.sort(key=lambda e: e[0])
    notes = sum(1 for _t, m in events if (m[0] & 0xF0) == 0x90 and len(m) > 2 and m[2] > 0)
    if not notes:
        return 0

    def vlq(v):
        out = [v & 0x7F]
        while v > 0x7F:
            v >>= 7
            out.append((v & 0x7F) | 0x80)
        return bytes(reversed(out))
    body, last = b"\x00\xff\x51\x03" + round(60000000 / bpm).to_bytes(3, "big"), 0
    for tick, msg in events:
        body += vlq(tick - last) + msg
        last = tick
    body += b"\x00\xff\x2f\x00"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".part"
    with open(tmp, "wb") as f:
        f.write(b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + ppq.to_bytes(2, "big")
                + b"MTrk" + len(body).to_bytes(4, "big") + body)
    os.replace(tmp, target)
    return notes


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def finalize(manifest_path, ffmpeg="ffmpeg"):
    with open(manifest_path, encoding="utf-8") as f:
        man = json.load(f)
    root, rel, error, done = man["root"], man["file"], "", []
    # LE RENDU D'UNE DÉMO (l'écoute sans jouer) : un seul fichier, là où le bridge l'attend, dit dans .preview.json
    preview = man.get("preview") if isinstance(man.get("preview"), dict) else None
    flat = man.get("mode") == "mix" or bool(preview)   # un fichier à plat, pas un dossier
    try:
        tracks = [dict(t, segments=sorted((s for s in t.get("segments") or [] if s.get("files")),
                                          key=lambda s: int(s.get("pos") or 0))) for t in man.get("tracks") or []]
        # l'ORIGINE de la prise : le premier échantillon enregistré, toutes pistes confondues
        origin = min((int(s.get("pos") or 0) for t in tracks for s in t["segments"]), default=0)
        for t in tracks:
            target = os.path.join(root, rel) if flat else os.path.join(root, rel, t["name"] + ".wav")
            if preview:
                target = preview["out"]
            if (flat and not preview and t["name"] != "Mix") or not t["segments"]:
                continue
            if t.get("midi"):                            # le clavier d'une lane : un fichier MIDI, s'il a joué une note
                with contextlib.suppress(OSError, ValueError, IndexError):
                    if not flat and write_midi(t["segments"], origin, man.get("sample_rate") or 48000, t.get("bpm"),
                                               os.path.join(root, rel, t["name"] + ".mid")):
                        done.append(t["name"])
                continue
            # UN RENDU est relu par le bridge avec le module `wave` de Python (reamp, banc CPU, démos) : il lit le PCM, pas
            # le flottant qu'écrit le moteur (« unknown extended format », trouvé au rack le 2026-11-17 sur un reamp) —
            # un rendu sort donc en PCM 24 bits ; une prise garde le format du moteur
            assemble(t["segments"], origin, target, ffmpeg, codec="pcm_s24le" if preview else None)
            done.append(t["name"])
        if not done:
            error = "nothing was recorded"
    except Exception as e:                       # jamais muet : l'écran le dira
        error = f"the take could not be assembled: {e}"[:300]
    if preview:
        st = {"seq": preview.get("seq") or 0, "scene": preview.get("scene") or "", "done": True, "wav": preview["out"] if done else ""}
        if error:
            st["error"] = error
        if isinstance(preview.get("extra"), dict):        # ce que le veilleur a mesuré pendant le rendu (le banc CPU)
            st.update(preview["extra"])
        write_atomic(os.path.join(root, "presets", ".preview.json"), st)
        return done, error
    write_atomic(os.path.join(root, "presets", ".perf.json"),
                 {"recording": False, "file": rel if done else "", "started_at": man.get("started_at") or "", "error": error})
    return done, error


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    names, err = finalize(sys.argv[1])
    print(f"take: {len(names)} file(s) {names}" + (f" — {err}" if err else ""))
    sys.exit(1 if err else 0)
