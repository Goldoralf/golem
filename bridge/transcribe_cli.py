# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker de transcription — tourne dans `.venv-transcribe`, JAMAIS dans le bridge.

    .venv-transcribe/bin/python -m bridge.transcribe_cli <dossier de prise>

Pourquoi un processus séparé, et pas un thread : le modèle et ses dépendances (onnxruntime,
librosa, numpy) pèsent des centaines de mégaoctets et ne doivent pas vivre dans le processus qui
tient le lien OSC. Séparé, il est aussi tuable, `nice`-able, et son plantage ne prend rien avec
lui. Le bridge le lance avec `nice -19` : le contrat interdit de peser sur le thread audio.

Ce qu'il écrit dans la prise (contrat de sortie, lu par /api/loops) :

    scores/index.json        { engine, at, ok, sources:[…] }
    scores/<source>.musicxml une partition par SOURCE

Deux qualités, et elles ne se confondent pas (docs/archive/tablature-study.md §12) :
  · `exact`   — une capture MIDI. Ce sont déjà des notes : conversion, pas transcription.
  · `draft`   — une DI audio passée par le modèle puis les cinq règles. ~80 %, doigté à revoir.

La DI d'une guitare ou d'une basse dans une prise À GRILLE (un riff armé : `bpm`, `downbeat_s`) passe par la stratégie
TX (`transcribe_di`) : attaques du DI, grille du click, doigté qui écoute la corde quand la guitare est étalonnée.
"""
import json
import os
import sys
import time
from .golog import swallowed as _swallowed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.transcribe import (RawNote, apply_rules, piano_hands, to_musicxml,   # noqa: E402
                               to_musicxml_drums, to_musicxml_piano)

ENGINE = "golem-transcribe/2 (basic-pitch + 5 règles ; tx1 sur grille)"
#: les instruments que la stratégie TX sait lire (une corde pincée, des attaques nettes)
TX_INSTRUMENTS = ("guitar", "bass")


def _say(_ev, **kw):
    """Une ligne JSON sur stdout par événement : le bridge la lit pour suivre l'avancement.
    Un flush explicite — sans lui la sortie d'un sous-processus est bufferisée par blocs et
    l'écran resterait à 0 % jusqu'à la fin.
    Le paramètre est `_ev` et non `ev`/`kind` : un événement porte un champ `kind` (audio ou
    MIDI), et le nom collidait avec le positionnel."""
    print(json.dumps({"ev": _ev, **kw}), flush=True)


# le libellé d'un rôle (« Guitar », « Keys + Pads », « Bass 2 »…) -> l'instrument que les règles connaissent
_ROLE_WORDS = (("drum", "drums"), ("bass", "bass"), ("voice", "voice"), ("vocal", "voice"), ("voc", "voice"),
               ("key", "keys"), ("pad", "keys"), ("piano", "keys"), ("synth", "keys"), ("organ", "keys"),
               ("guitar", "guitar"), ("gtr", "guitar"))


def _word_instrument(text):
    low = (text or "").lower()
    for word, inst in _ROLE_WORDS:
        if word in low:
            return inst
    return None


def _instrument_of(name, manifest):
    """L'instrument d'une source, pour la RÈGLE 1 (tessiture) et pour la portée. Le patch du rack le sait :
    `take.json.roles` = numéro d'entrée -> libellé (« Guitar », « Keys + Pads »), gelé à la prise, et le nom de
    la source porte l'entrée (« Sandbox-Input-2 » -> 2 ; même lecture que reamp.take_role).
    ⚠ Avant le 2026-10-17 on lisait `inputs` (absent de take.json) puis on comparait des libellés en majuscules
    à des rôles en minuscules : tout tombait sur « guitar » — la basse comme le clavier."""
    import re
    m = re.search(r"input-(\d+)", (name or "").lower())
    roles = (manifest or {}).get("roles") or {}
    if m and isinstance(roles, dict):
        inst = _word_instrument(str(roles.get(m.group(1)) or ""))
        if inst:
            return inst
    return _word_instrument(name) or "guitar"


def _midi_read(path):
    """Une capture MIDI -> (notes, pédales). Les notes sont des RawNote de confiance 1.0 (ce ne sont pas des
    hypothèses), `.channel` en plus ; les pédales sont les appuis de sustain (CC64 ≥ 64), en secondes.
    Lu avec mido, au TEMPO DU FICHIER, changements compris : la durée était comptée à 120 bpm quel que soit
    le tempo (corrigé 2026-10-17)."""
    import mido
    mf = mido.MidiFile(path)
    notes, pedals, held, ped_on = [], [], {}, None
    t = 0.0
    for msg in mf:                                   # l'itération rend `time` en SECONDES, tempos appliqués
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            held.setdefault((msg.channel, msg.note), []).append((t, msg.velocity))
        elif msg.type in ("note_off", "note_on"):
            q = held.get((msg.channel, msg.note))
            if q:
                t0, vel = q.pop(0)
                n = RawNote(onset=t0, offset=max(t, t0 + 0.01), pitch=int(msg.note), conf=1.0)
                notes.append((n, msg.channel, vel))
        elif msg.type == "control_change" and msg.control == 64:
            if msg.value >= 64 and ped_on is None:
                ped_on = t
            elif msg.value < 64 and ped_on is not None:
                pedals.append((ped_on, t))
                ped_on = None
    for (ch, note), q in held.items():               # une note jamais relâchée finit avec le fichier
        for t0, vel in q:
            notes.append((RawNote(onset=t0, offset=max(t, t0 + 0.01), pitch=int(note), conf=1.0), ch, vel))
    if ped_on is not None:
        pedals.append((ped_on, t))
    notes.sort(key=lambda x: (x[0].onset, x[0].pitch))
    return notes, pedals


def _midi_notes(path):
    """Les notes seules d'une capture MIDI (RawNote)."""
    return [n for n, _, _ in _midi_read(path)[0]]


def _drum_descriptor(man):
    """Le descripteur du module de batterie gravé dans la prise (take.json `drums`), sinon General MIDI.
    Plusieurs modules liés : le premier — une prise n'en porte qu'un en pratique."""
    from bridge import drumkits as K
    for d in (man or {}).get("drums") or []:
        desc = K.get((d or {}).get("descriptor"))
        if desc:
            return desc
    return K.get(K.FALLBACK) or {}


def _drum_notes(raw, desc):
    """Notes du module -> la note General MIDI de leur ÉLÉMENT (DRUM_GM). Une note que le descripteur ne
    connaît pas ne s'écrit pas : elle est comptée dans le rapport."""
    from bridge import drumkits as K
    from bridge.transcribe import DRUM_GM
    out, unknown = [], 0
    for n, _ch, _vel in raw:
        gm = DRUM_GM.get(K.element_of(desc, n.pitch) or "")
        if gm is None:
            unknown += 1
            continue
        out.append(RawNote(onset=n.onset, offset=n.offset, pitch=gm, conf=1.0))
    return out, unknown


def _score_name(label):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in label) + ".musicxml"


def _heard_b(path, events):
    """Le B d'inharmonicité de chaque note SEULE (None pour un accord ou une mesure impossible), lu sur le DI à sa
    fréquence d'origine — la précision d'un partiel aigu en dépend."""
    import librosa
    from bridge import inharm
    y, sr = librosa.load(path, sr=None, mono=True)
    return [inharm.estimate_b(y, sr, t0, t1, float(librosa.midi_to_hz(ps[0]))) if len(ps) == 1 else None
            for t0, t1, ps in events]


def _neck(path, events, g):
    """Ce que la carte du manche de la guitare dit de chaque note (`neckmap.costs`), ou None sans carte."""
    from bridge import neckmap
    nmap = neckmap.load((g or {}).get("neckmap"))
    if not nmap or nmap.get("tuning") != g["tuning"]:
        return None                                   # une carte d'un autre accordage ne dit rien de celui-ci
    import soundfile as sf
    y, sr = sf.read(path, always_2d=True)
    return neckmap.costs(y[:, 0], sr, events, nmap, g["tuning"])


def _guitar_of(man, inst):
    """La guitare de la prise (take.json `guitar`, gravée au REC) : son profil et sa tessiture — de la corde la plus
    grave à vide jusqu'à la dernière case de la plus aiguë. None hors guitare. Une prise SANS le champ date d'avant les
    profils (2026-10-29) : c'est la 6 cordes « default », pas la guitare active d'aujourd'hui (retranscrire une prise
    d'hier pendant qu'on joue la 8 cordes la lisait en 8 cordes)."""
    if inst != "guitar":
        return None, None
    from bridge import inharm
    man = man or {}
    tun = man.get("tuning")
    if "guitar" in man and man["guitar"] is None and isinstance(tun, list) and tun:
        # un accordage qu'aucune guitare du rack n'a : on l'écrit tel quel, sans étalonnage (rien n'est jugé)
        g = {"id": None, "name": "unknown", "tuning": sorted(tun), "b_open": {}, "hand": {}, "neckmap": None,
             "frets": 24 if len(tun) > 6 else inharm.DEFAULT_FRETS}
    else:
        g = inharm.guitar(inharm.CALIB, man.get("guitar") if "guitar" in man else "default")
    return g, (g["tuning"][0], g["tuning"][-1] + g["frets"])


def _tx(path, man, inst, label, title, out_dir, done):
    """La stratégie TX sur une DI de prise à grille : écrit la partition et sa ligne d'index. False si la prise n'a
    pas de grille (les cinq règles reprennent la main)."""
    from bridge import transcribe_di
    g, rng = _guitar_of(man, inst)
    got = transcribe_di.transcribe_take(path, man, inst, rng)
    if got is None:
        return False
    figs, rep, events, grid = got
    b_open = g["b_open"] if g else {}
    heard = _heard_b(path, events) if b_open else None
    neck = _neck(path, events, g) if g else None
    if g:
        rep["guitare"] = g["id"]
    if neck is not None:
        rep["carte_du_manche"] = sum(1 for x in neck if x)
    if heard is not None:
        rep["cordes_etalonnees"] = sorted(b_open)
        rep["b_mesures"] = sum(1 for b in heard if b)
    xml = to_musicxml(figs, bpm=grid["bpm"], beats=grid["beats"], beat_type=grid["beat_type"], part_name=label,
                      instrument=inst, title=title, heard=heard, b_open=b_open, neck=neck,
                      tuning=g["tuning"] if g else None, frets=g["frets"] if g else None,
                      hand=g["hand"] if g else None)
    name = _score_name(label)
    open(os.path.join(out_dir, name), "w").write(xml)
    done.append({"src": label, "kind": "audio", "file": "scores/" + name, "quality": "draft", "instrument": inst,
                 "bars": xml.count("<measure "), "figures": len(figs), "report": rep})
    _say("ok", name=label, bars=xml.count("<measure "), figures=len(figs))
    return True


def main(take_dir):
    man = {}
    try:
        man = json.load(open(os.path.join(take_dir, "take.json")))
    except Exception as _e:
        _swallowed(_e)
    bpm = float(man.get("bpm") or 120)

    # Sources ÉLIGIBLES, et l'ordre compte : le MIDI d'abord, parce qu'il est exact et instantané
    # — l'écran a quelque chose à montrer avant que le modèle ait fini de mouliner la première DI.
    files = sorted(os.listdir(take_dir))
    srcs = ([(f, "midi") for f in files if f.lower().endswith(".mid")]
            + [(f, "audio") for f in files if f.startswith("DI-") and f.lower().endswith(".wav")])
    std = os.path.join(take_dir, "standard.seq")
    if not srcs and not os.path.isfile(std):
        _say("done", ok=False, error="aucune source transcriptible (ni MIDI, ni DI, ni Standard)")
        return 2

    out_dir = os.path.join(take_dir, "scores")
    os.makedirs(out_dir, exist_ok=True)

    def title_of(label):
        return "%s — %s" % (man.get("preset") or os.path.basename(take_dir), label)
    done, t0 = [], time.time()
    _say("start", total=len(srcs) + (1 if os.path.isfile(std) else 0))

    # LES PARTIES DU STANDARD joué pendant la prise (lot 3) : des notes que golem a écrites — exactes, instantanées,
    # donc AVANT le modèle, comme le MIDI
    if os.path.isfile(std):
        from bridge.transcribe import read_seq, standard_scores
        stitle = ((man.get("standard") or {}).get("title")) or ((man.get("standard") or {}).get("id")) or "Standard"
        try:
            for sc in standard_scores(read_seq(std), bpm, title=stitle):
                name = "Standard-" + "".join(c if c.isalnum() else "-" for c in sc["name"]) + ".musicxml"
                with open(os.path.join(out_dir, name), "w") as fh:
                    fh.write(sc["xml"])
                label = "Standard " + sc["name"]
                done.append({"src": label, "kind": "standard", "file": "scores/" + name, "quality": "exact",
                             "instrument": sc["instrument"], "bars": sc["xml"].count("<measure "),
                             "figures": sc["figures"]})
                _say("ok", name=label, bars=sc["xml"].count("<measure "), figures=sc["figures"])
        except Exception as e:                          # une source qui casse n'emporte pas la prise
            done.append({"src": "Standard", "kind": "standard", "error": "%s: %s" % (type(e).__name__, e)})
            _say("fail", name="Standard", error=str(e)[:200])

    for i, (fn, kind) in enumerate(srcs):
        base = os.path.splitext(fn)[0]
        # ⚠ L'ORDRE COMPTE : retirer « DI- » avant « MIDI- » mange le DI de MIDI et rend
        # « MIInput-3 » (constaté). On enlève les préfixes du plus long au plus court.
        for pref in ("DI-Sandbox-", "MIDI-", "DI-"):
            if base.startswith(pref):
                base = base[len(pref):]
                break
        label = base
        _say("source", i=i, total=len(srcs), name=label, kind=kind)
        try:
            path = os.path.join(take_dir, fn)
            inst = _instrument_of(label, man)
            pedals, extra = [], {}
            if kind == "audio" and inst == "drums":
                # une batterie acoustique ne se transcrit pas avec un modèle de hauteurs : il faudrait un modèle
                # de batterie. Seule la capture MIDI d'une batterie électronique s'écrit.
                done.append({"src": label, "kind": kind, "instrument": inst,
                             "skipped": "drums are written from a MIDI capture only"})
                _say("skip", name=label, why="drums audio")
                continue
            if kind == "midi":
                raw, pedals = _midi_read(path)
                total_s = None
                if inst == "drums":
                    desc = _drum_descriptor(man)
                    notes, unknown = _drum_notes(raw, desc)
                    extra = {"descriptor": desc.get("id"), "unknown_notes": unknown}
                else:
                    notes = [n for n, _, _ in raw]
            elif inst in TX_INSTRUMENTS and _tx(path, man, inst, label, title_of(label), out_dir, done):
                continue
            else:
                from bridge.transcribe import notes_from_audio
                import soundfile as sf
                notes = notes_from_audio(path)
                total_s = sf.info(path).duration
            if kind == "midi" and inst == "keys":
                # un clavier capté en MIDI : les vraies durées, main par main (pas la règle 5, faite pour la corde)
                hi, lo, grid = piano_hands(notes, bpm)
                figs, rep = hi + lo, {"entrees": len(notes), "grille_ql": grid, "main_droite": len(hi),
                                      "main_gauche": len(lo), "pedales": len(pedals)}
            else:
                g, rng = _guitar_of(man, inst)
                figs, rep = apply_rules(notes, bpm, instrument=inst, total_s=total_s, rng=rng)
            title = title_of(label)
            if inst == "drums":
                xml = to_musicxml_drums(figs, bpm=bpm, part_name=label, title=title)
            elif inst == "keys":
                # les pédales, en noires depuis le début de la prise (la même échelle que les figures)
                q = bpm / 60.0
                xml = to_musicxml_piano(None, bpm=bpm, part_name=label, title=title, hands=(hi, lo),
                                        pedals=[(a * q, z * q) for a, z in pedals])
            else:
                g, _rng = _guitar_of(man, inst)
                xml = to_musicxml(figs, bpm=bpm, part_name=label, instrument=inst, title=title,
                                  tuning=g["tuning"] if g else None, frets=g["frets"] if g else None,
                                  hand=g["hand"] if g else None)
            name = _score_name(label)
            open(os.path.join(out_dir, name), "w").write(xml)
            done.append({"src": label, "kind": kind, "file": "scores/" + name,
                         "quality": "exact" if kind == "midi" else "draft",
                         "instrument": inst, "bars": xml.count("<measure "),
                         "figures": len(figs), "report": {**rep, **extra}})
            _say("ok", name=label, bars=xml.count("<measure "), figures=len(figs))
        except Exception as e:                          # une source qui casse n'emporte pas la prise
            done.append({"src": label, "kind": kind, "error": "%s: %s" % (type(e).__name__, e)})
            _say("fail", name=label, error=str(e)[:200])

    index = {"engine": ENGINE, "at": time.time(), "seconds": round(time.time() - t0, 2),
             "bpm": bpm, "ok": any("file" in d for d in done), "sources": done}
    tmp = os.path.join(out_dir, "index.json.tmp")
    json.dump(index, open(tmp, "w"), indent=1)
    os.replace(tmp, os.path.join(out_dir, "index.json"))
    _say("done", ok=index["ok"], sources=len(done), seconds=index["seconds"])
    return 0 if index["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m bridge.transcribe_cli <dossier de prise>", file=sys.stderr)
        sys.exit(64)
    sys.exit(main(sys.argv[1]))
