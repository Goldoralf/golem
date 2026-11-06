# SPDX-License-Identifier: GPL-3.0-or-later
"""Le PACK DE TEST (library/test-content/, docs/quality-automation.md §8) : posé et retiré sans toucher au contenu de
l'utilisateur — même patron que le contenu d'usine (factory.py), avec SON registre.

    python -m bridge.test_content install   # pose patches, presets, setlists, la chanson et le standard de test
    python -m bridge.test_content remove    # retire EXACTEMENT ce que le registre liste, puis le registre
    python -m bridge.test_content status

Le registre (presets/.test-content.json) tient le chemin de chaque fichier posé : `remove` n'efface que ceux-là, et
seulement s'ils existent encore. Un fichier qui existait déjà au même chemin n'est jamais écrasé ni retiré (dit dans
`kept`). La chanson et le standard sont des `.golem` FABRIQUÉS ici depuis leurs sources (manifeste, paroles, grille) :
l'audio de la chanson — un original et deux stems — est synthétisé, déterministe, 4 s à 48 kHz : rien de binaire dans
le dépôt. L'id de la chanson est son content id (golemfile.content_id), que les setlists reçoivent à la pose."""
import json
import math
import os
import shutil
import struct
import sys
import wave

from . import config as C

SRC = os.path.join(C.ROOT, "library", "test-content")
SONG_ARTIST, SONG_TITLE = "golem test", "Test Song"
SR = 48000


def _kinds():
    """sorte -> (sous-dossier source, dossier de vie, extension) — les mêmes dossiers que factory.KINDS."""
    return {"patches": ("patches", os.path.join(C.ROOT, "library", "patches"), ".json"),
            "presets": ("presets", C.PRESETS_DIR, ".json"),
            "setlists": ("setlists", C.SETLISTS_DIR, ".json")}


def song_id():
    from . import golemfile as G
    return G.content_id(SONG_ARTIST, SONG_TITLE, "original")


def ledger_path():
    return os.path.join(C.PRESETS_DIR, ".test-content.json")      # lu à l'appel : les tests déplacent C.*


def _ledger():
    try:
        with open(ledger_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_ledger(d):
    from .store import _write_json_atomic
    _write_json_atomic(ledger_path(), d, indent=1)


def _tone(seconds, f0, amp, decay=1.5):
    n = int(SR * seconds)
    return [amp * math.sin(2 * math.pi * f0 * i / SR) * math.exp(-decay * i / SR) for i in range(n)]


def _wav_bytes(samples):
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams((1, 2, SR, len(samples), "NONE", "not compressed"))
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in samples))
    return buf.getvalue()


def _song_audio():
    """Un original (deux notes), un stem « drums » (clics courts sur les temps) et un stem « bass » (note grave) — 4 s
    à 120 BPM : de quoi jouer, muter un stem, et voir le compteur de mesures avancer."""
    n = int(SR * 4.0)
    bass = [0.0] * n
    drums = [0.0] * n
    for beat in range(8):                                        # 120 BPM : un temps toutes les 0,5 s
        s0 = int(beat * 0.5 * SR)
        for i, v in enumerate(_tone(0.08, 180.0 if beat % 4 == 0 else 900.0, 0.5, 40.0)):
            if s0 + i < n:
                drums[s0 + i] += v
        for i, v in enumerate(_tone(0.45, 55.0 if beat < 4 else 73.4, 0.4, 3.0)):
            if s0 + i < n:
                bass[s0 + i] += v
    original = [0.6 * b + 0.6 * d for b, d in zip(bass, drums)]
    return {"audio/original.wav": _wav_bytes(original), "stems/drums.wav": _wav_bytes(drums), "stems/bass.wav": _wav_bytes(bass)}


def _build_song(dest):
    from . import golemfile as G
    src = os.path.join(SRC, "song", "test-song")
    with open(os.path.join(src, "golem.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["id"] = song_id()
    members = {G.LYRICS: open(os.path.join(src, "song.lrc"), "rb").read(),
               G.CHART: open(os.path.join(src, "song.gsx"), "rb").read()}
    members.update(_song_audio())
    manifest["files"] = {"stems/drums.wav": {"part": "drums"}, "stems/bass.wav": {"part": "bass"}}
    G.write(dest, manifest, members)
    return dest


def _build_standard(dest):
    from . import golemfile as G
    src = os.path.join(SRC, "standards", "test-standard")
    with open(os.path.join(src, "golem.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["id"] = G.content_id(manifest.get("artist") or SONG_ARTIST, manifest.get("title") or "Test Standard", "original")
    G.write(dest, manifest, {G.CHART: open(os.path.join(src, "song.gsx"), "rb").read()})
    return dest


def targets():
    """Chaque fichier que `install` poserait : (sorte, source ou None, chemin de destination)."""
    out = []
    for kind, (sub, dst, ext) in _kinds().items():
        d = os.path.join(SRC, sub)
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if fn.endswith(ext):
                out.append((kind, os.path.join(d, fn), os.path.join(dst, fn)))
    from . import songs
    out.append(("songs", None, songs._path(song_id())))
    out.append(("standards", None, os.path.join(C.ROOT, "library", "standards", "golem", "test-standard.golem")))
    return out


def install():
    """Pose le pack. Rend {placed, kept (déjà là, laissés tels quels), song_id}."""
    led = _ledger()
    placed, kept = [], []
    sid = song_id()
    for kind, src, dst in targets():
        if os.path.exists(dst) and dst not in (led.get("placed") or []):
            kept.append(dst)                                     # à l'utilisateur, ou posé hors registre : on n'y touche pas
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if kind == "songs":
            _build_song(dst)
        elif kind == "standards":
            _build_standard(dst)
        else:
            with open(src, encoding="utf-8") as f:
                text = f.read().replace("@TEST_SONG_ID@", sid)
            tmp = dst + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, dst)
        placed.append(dst)
    led["placed"] = sorted(set(led.get("placed") or []) | set(placed))
    led["song_id"] = sid
    _write_ledger(led)
    for mod, fn in (("standards", "invalidate"),):
        try:
            getattr(__import__("bridge." + mod, fromlist=[fn]), fn)()
        except Exception:
            pass
    return {"placed": placed, "kept": kept, "song_id": sid}


def remove():
    """Retire ce que le registre liste — rien d'autre — puis le registre. Rend {removed, missing}."""
    led = _ledger()
    removed, missing = [], []
    for p in led.get("placed") or []:
        if os.path.isfile(p):
            os.remove(p)
            removed.append(p)
        else:
            missing.append(p)
    if os.path.isfile(ledger_path()):
        os.remove(ledger_path())
    try:
        from . import standards
        standards.invalidate()
    except Exception:
        pass
    return {"removed": removed, "missing": missing}


def status():
    led = _ledger()
    placed = led.get("placed") or []
    return {"installed": bool(placed), "placed": placed, "present": [p for p in placed if os.path.isfile(p)],
            "song_id": led.get("song_id") or song_id(), "would_place": [d for _, _, d in targets()]}


def main(argv=None):
    cmd = (argv or sys.argv[1:] or ["status"])[0]
    fn = {"install": install, "remove": remove, "status": status}.get(cmd)
    if not fn:
        print(__doc__)
        return 2
    print(json.dumps(fn(), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
