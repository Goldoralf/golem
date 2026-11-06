#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Écrit le PACK DE TEST — library/test-content/ (docs/quality-automation.md §8) : des patches, presets, setlists,
une chanson et un standard faits EXPRÈS pour les tests, préfixés `test-`, en anglais, modifiables à volonté. Ils se
posent et se retirent par bridge/test_content.py (registre), jamais mêlés au contenu de l'utilisateur.

Ce qu'ils couvrent, et pourquoi (l'inventaire du contenu d'usine du 2026-10-20) :
  - chaque bloc qui se pose PARTOUT (intégrés REAPER, JSFX du stock et de golem) : gate, comp, eq, delay, clean-boost,
    chorus-js, phaser-js, flanger-js, killswitch, guitar-drive, pitch-shift-js, deesser, volume — un patch sur un
    runner sans modèle ni plugin tiers se matérialise quand même ;
  - un split merge ET un split fan-out, des mutes de branche par scène, des coupures par scène, des potards par scène ;
  - les quatre rôles audio (guitar, bass, voice) et les lanes MIDI (keys-pads avec le kit de pads d'usine « pads-house »
    = les 16 samples d'usine ; drums avec le kit « drums-black-pearl » et les grooves d'usine) ;
  - les blocs de service : rec, click, compo, arrangement (sections), looper, tuner, backing-track, standard, drums ;
    sample (bloc à pads) — avec leurs conflits respectés (standard ≠ backing-track/drums : deux presets) ;
  - des assignations au pied (6-10) et une cible d'expression ; des couleurs et animations de scène ;
  - une setlist de sons (6 lignes, un patch partagé par deux lignes) et une setlist de chansons (2 lignes, l'une
    portant la chanson de test avec son audio, ses paroles et sa grille) ; un standard de test (grille 12 mesures).
Relancer ce script régénère tout à l'identique (déterministe)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "library" / "test-content"


def st(lane, sid, name, blocks=None, params=None, branches=None):
    return {"id": f"st-{lane}-{sid}", "name": name, "blocks": blocks or {}, "params": params or {}, "branches": branches or {}}


def scenes_of(lanes_states, names, extra=None):
    """Les scènes d'un patch à partir des états par lane : scene[sid] = {blocks ∪, branches ∪, lanes {lane: state}}."""
    out = []
    for i, (sid, name) in enumerate(names):
        blocks, branches, lanes = {}, {}, {}
        for lane, states in lanes_states.items():
            s = states[i]
            blocks.update(s["blocks"]); branches.update(s["branches"]); lanes[lane] = {"state": s["id"]}
        sc = {"id": sid, "name": name, "blocks": blocks, "branches": branches, "lanes": lanes}
        if extra and sid in extra:
            sc.update(extra[sid])
        out.append(sc)
    return out


def patch(pid, name, role, lanes, scenes, config=None, tags=(), bpm=120, colors=None, anims=None):
    d = {"id": pid, "name": name, "role": role, "tags": list(tags), "kind": "patch", "patch_v": 2, "lanes_v": 2, "bpm": bpm,
         "origin": "test", "lanes": lanes, "scenes": scenes, "config": config or {"gen": {"out": "1-2", "blocks": []}}}
    if colors:
        d["colors"] = colors
    if anims:
        d["anims"] = anims
    return d


def write(rel, data):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n" if not isinstance(data, str) else data
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def main():
    files = []
    # ── 1. guitar : merge split, 3 scènes, pied 6-9, expression sur le volume, couleurs et animations ─────────────
    L = "guitar-1"
    chain = {"pre": [{"id": "gate", "type": "gate", "params": {"thresh": -55}}],
             "split": {"mode": "merge", "gain": -3, "branches": [
                 {"id": "lane-a", "blocks": [{"id": "boost", "type": "clean-boost", "params": {"gain": 3}}, {"id": "eq", "type": "eq"}]},
                 {"id": "lane-b", "blocks": [{"id": "phaser", "type": "phaser-js", "foot": 6}, {"id": "comp", "type": "comp"}]}]},
             "post": [{"id": "chorus", "type": "chorus-js", "foot": 7}, {"id": "dly", "type": "delay", "foot": 8, "params": {"mix": 20}},
                      {"id": "kill", "type": "killswitch", "foot": 9}]}
    states = [st(L, "A", "Both branches", {"chorus": False}),
              st(L, "B", "Branch A, chorus and delay", {"chorus": True, "dly": True}, {"dly": {"mix": 35}}, {"lane-b": {"mute": True}}),
              st(L, "C", "Branch B only", {"phaser": True}, {}, {"lane-a": {"mute": True}})]
    lanes = [{"id": L, "role": "guitar", "name": "Test guitar", "midi": False, "stereo": False, "chain": chain, "states": states}]
    names = [("A", "Both branches"), ("B", "Branch A"), ("C", "Branch B")]
    files.append(write("patches/test-guitar-bench.json", patch(
        "test-guitar-bench", "Test — Guitar bench", "guitar", lanes, scenes_of({L: states}, names, {"B": {"level": 2}}),
        tags=["test", "bench"], colors={"A": "#4f8cff", "B": "#ff7a1a", "C": "#2fbf71"}, anims={"A": "aurora", "B": "vortex", "C": "sheen"})))

    # ── 2. bass : FAN-OUT (deux sorties, pas de post), drive JS, 2 scènes avec mute de branche ───────────────────
    L = "bass-1"
    chain = {"pre": [{"id": "gate", "type": "gate"}],
             "split": {"mode": "fanout", "gain": 0, "branches": [
                 {"id": "clean", "blocks": [{"id": "comp", "type": "comp"}, {"id": "eq", "type": "eq"}]},
                 {"id": "dirty", "blocks": [{"id": "drive", "type": "guitar-drive", "foot": 6}, {"id": "flanger", "type": "flanger-js", "foot": 7}]}]},
             "post": []}
    states = [st(L, "A", "Clean", {"flanger": False}, {}, {"dirty": {"mute": True}}),
              st(L, "B", "Dirty", {"drive": True, "flanger": True}, {}, {"clean": {"mute": True}})]
    lanes = [{"id": L, "role": "bass", "name": "Test bass", "midi": False, "stereo": False, "chain": chain, "states": states}]
    files.append(write("patches/test-bass-fanout.json", patch(
        "test-bass-fanout", "Test — Bass fan-out", "bass", lanes, scenes_of({L: states}, [("A", "Clean"), ("B", "Dirty")]), tags=["test"])))

    # ── 3. voice : de-esser (JSFX golem), pitch (JS superpitch), chaîne plate, 2 scènes ─────────────────────────
    L = "voice-1"
    chain = {"pre": [{"id": "gate", "type": "gate"}, {"id": "deess", "type": "deesser"}, {"id": "comp", "type": "comp"}],
             "post": [{"id": "eq", "type": "eq"}, {"id": "pitch", "type": "pitch-shift-js", "foot": 6}, {"id": "dly", "type": "delay", "foot": 7}]}
    states = [st(L, "A", "Dry", {"pitch": False, "dly": False}), st(L, "B", "Wet", {"pitch": False, "dly": True}, {"dly": {"mix": 25}})]
    lanes = [{"id": L, "role": "voice", "name": "Test voice", "midi": False, "stereo": False, "chain": chain, "states": states}]
    files.append(write("patches/test-voice-plain.json", patch(
        "test-voice-plain", "Test — Voice plain", "voice", lanes, scenes_of({L: states}, [("A", "Dry"), ("B", "Wet")]), tags=["test"])))

    # ── 4. keys-pads : le bloc pads sur le kit d'usine « pads-house » (16 samples d'usine), lane MIDI ──────────────
    L = "keys-pads-1"
    lanes = [{"id": L, "role": "keys-pads", "name": "Test pads", "midi": True,
              "chain": {"chain": [{"id": "pads", "type": "pads", "params": {"kit": "pads-house"}}, {"id": "comp", "type": "comp"}]},
              "states": [st(L, "A", "Pads")]}]
    files.append(write("patches/test-keys-pads.json", patch(
        "test-keys-pads", "Test — Keys pads", "keys-pads", lanes, scenes_of({L: lanes[0]["states"]}, [("A", "Pads")]),
        config={"gen": {"out": "1-2", "blocks": []}, "rec": {"blocks": [{"id": "rec-global", "type": "rec", "foot": 9}]}}, tags=["test"])))

    # ── 5. drums : kit d'usine avldrums + grooves d'usine, et le bloc standard de service sur le standard de test ─
    L = "drums-1"
    states = [st(L, "A", "Groove"), st(L, "B", "Tight", {}, {"comp": {"attack": 10}})]
    lanes = [{"id": L, "role": "drums", "name": "Test drums", "midi": True, "chain": {"chain": [{"id": "comp", "type": "comp"}]}, "states": states}]
    config = {"gen": {"out": "1-2", "blocks": [
        {"type": "drums", "id": "drums", "foot": 10, "params": {"patterns": ["library/grooves/golem-rock-8.mid", "library/grooves/golem-four-on-the-floor.mid"],
                                                              "fills": [], "kit": "drums-black-pearl"}}]},
        "rec": {"blocks": [{"id": "rec-global", "type": "rec", "foot": 9}]}}
    files.append(write("patches/test-drums-kit.json", patch(
        "test-drums-kit", "Test — Drums kit", "drums", lanes, scenes_of({L: states}, [("A", "Groove"), ("B", "Tight")]), config=config, tags=["test"])))

    # ── 6. preset « band session » : guitar + voice, backing-track, drums, click, rec, compo, arrangement, looper, tuner
    G, V = "guitar-1", "voice-1"
    gchain = {"pre": [{"id": "g-gate", "type": "gate"}], "post": [{"id": "g-chorus", "type": "chorus-js", "foot": 6}, {"id": "g-dly", "type": "delay", "foot": 7}]}
    vchain = {"pre": [{"id": "v-comp", "type": "comp"}], "post": [{"id": "v-eq", "type": "eq"}, {"id": "v-dly", "type": "delay", "foot": 8}]}
    gst = [st(G, "A", "Verse", {"g-chorus": False, "g-dly": False}), st(G, "B", "Chorus", {"g-chorus": True, "g-dly": True}), st(G, "C", "Bridge", {"g-chorus": True, "g-dly": False})]
    vst_ = [st(V, "A", "Verse", {"v-dly": False}), st(V, "B", "Chorus", {"v-dly": True}), st(V, "C", "Bridge", {"v-dly": True})]
    lanes = [{"id": G, "key": G, "role": "guitar", "name": "Guitar", "in_sel": "", "out_sel": "1-2", "midi": False, "in_role": "guitar", "in_nth": 1, "chain": gchain, "states": gst},
             {"id": V, "key": V, "role": "voice", "name": "Voice", "in_sel": "", "out_sel": "1-2", "midi": False, "in_role": "voice", "in_nth": 1, "chain": vchain, "states": vst_}]
    scenes = scenes_of({G: gst, V: vst_}, [("A", "Verse"), ("B", "Chorus"), ("C", "Bridge")])
    config = {"gen": {"out": "1-2", "blocks": [
                  {"id": "backing", "type": "backing-track", "foot": 5, "params": {}},
                  {"id": "drums", "type": "drums", "foot": 10, "params": {"patterns": ["library/grooves/golem-rock-8.mid"], "fills": [], "kit": "drums-black-pearl"}},
                  {"id": "looper", "type": "looper", "params": {}},
                  {"id": "tuner", "type": "tuner", "params": {}}]},
              "rec": {"blocks": [{"id": "rec-global", "type": "rec", "params": {"in1": True, "in2": True, "usb": False, "rec_mode": "tracks_di", "mix": True, "count_in": 0, "transcribe": "manual"}},
                                 {"id": "click-global", "type": "click", "params": {"level": -12, "beats": 4}},
                                 {"id": "compo-global", "type": "compo", "params": {"keep_s": 30, "transcribe": False}}], "click_out": "1-2"},
              "arr": {"blocks": [{"id": "arrangement", "type": "arrangement", "params": {"advance": "bars", "sections": [
                  {"name": "Verse", "bars": 4, "scene": "A"}, {"name": "Chorus", "bars": 4, "scene": "B"}, {"name": "Bridge", "bars": 2, "scene": "C"}, {"name": "Chorus", "bars": 4, "scene": "B"}]}}]}}
    files.append(write("presets/test-band-session.json", {
        "id": "test-band-session", "name": "Test — Band session", "lanes_v": 2, "lanes": lanes, "scenes": scenes, "bpm": 120, "origin": "test",
        "styles": ["rock"], "config": config,
        "colors": {"A": "#4f8cff", "B": "#ff7a1a", "C": "#2fbf71"}, "anims": {"A": "aurora", "B": "vortex", "C": "sheen"}}))

    # ── 7. preset « standard trio » : le bloc standard (conflit avec backing-track et drums : preset à part) ──────
    G = "guitar-1"
    gst = [st(G, "A", "Head", {"g-dly": False}), st(G, "B", "Solo", {"g-dly": True})]
    lanes = [{"id": G, "key": G, "role": "guitar", "name": "Guitar", "in_sel": "", "out_sel": "1-2", "midi": False, "in_role": "guitar", "in_nth": 1,
              "chain": {"pre": [{"id": "g-comp", "type": "comp"}], "post": [{"id": "g-dly", "type": "delay", "foot": 6}]}, "states": gst}]
    config = {"gen": {"out": "1-2", "blocks": [{"type": "standard", "id": "standard", "foot": 10, "params": {
                  "standard": "test-standard", "key": "Original", "feel": "auto", "motion": "comp", "voicing": "rootless", "arp": "Off",
                  "keys": True, "bass": True, "drums": True, "groove": "auto", "kit": "black-pearl", "choruses": 2}}]},
              "rec": {"blocks": [{"id": "rec-global", "type": "rec", "foot": 9}, {"id": "click-global", "type": "click", "params": {"level": -12, "beats": 4}}]}}
    files.append(write("presets/test-standard-trio.json", {
        "id": "test-standard-trio", "name": "Test — Standard trio", "lanes_v": 2, "lanes": lanes,
        "scenes": scenes_of({G: gst}, [("A", "Head"), ("B", "Solo")]), "bpm": 160, "origin": "test", "styles": ["jazz"], "config": config}))

    # ── 8. setlists : une de sons (un patch partagé par deux lignes), une de chansons (la chanson de test, le standard)
    lines = [("Guitar bench", "test-guitar-bench"), ("Bass fan-out", "test-bass-fanout"), ("Guitar bench again", "test-guitar-bench"),
             ("Voice plain", "test-voice-plain"), ("Keys pads", "test-keys-pads"), ("Drums kit", "test-drums-kit")]
    files.append(write("setlists/test-sounds.json", {
        "id": "test-sounds", "name": "Test — Sounds", "fcb": True, "rev": 1, "kind": "sounds", "origin": "test",
        "presets": ["patch:" + p for _, p in lines],
        "lines": [{"id": f"r:test-sounds:{i:02d}", "rev": 1, "title": t, "patch": p} for i, (t, p) in enumerate(lines)]}))
    files.append(write("setlists/test-songs.json", {
        "id": "test-songs", "name": "Test — Songs", "fcb": True, "rev": 1, "kind": "songs", "origin": "test",
        "presets": ["test-band-session", "test-standard-trio"],
        "lines": [{"id": "r:test-songs:00", "rev": 1, "preset": "test-band-session", "title": "Test Song", "bpm": 120, "band_song": "@TEST_SONG_ID@"},
                  {"id": "r:test-songs:01", "rev": 1, "preset": "test-standard-trio", "title": "Test Standard", "bpm": 160}]}))

    # ── 9. la chanson de test (sources ; le .golem et son audio synthétique sont fabriqués à l'installation) ──────
    files.append(write("song/test-song/golem.json", {
        "type": "song", "title": "Test Song", "artist": "golem test", "kind": "original", "rights": {"work": "public-domain"},
        "genres": [{"family": "rock", "subgenre": None}], "bpm": 120, "key": "A", "meter": "4/4"}))
    files.append(write("song/test-song/song.lrc", "[ti:Test Song]\n[ar:golem test]\n[00:00.50]One two three four\n[00:02.50]A test song for the rack\n[00:04.50]Nothing else to say\n"))
    files.append(write("song/test-song/song.gsx", json.dumps({
        "v": 1, "slug": "test-song", "title": "Test Song", "composer": "golem test", "year": 2026, "style": "rock", "key": "A", "meter": "4/4",
        "tempo": 120, "feel": "straight", "form": ["A", "B"], "sections": {"A": {"bars": "A | D | A | E"}, "B": {"bars": "D | A | E | A"}}}, indent=1) + "\n"))
    # ── 10. le standard de test : une grille de 12 mesures ────────────────────────────────────────────────────────
    files.append(write("standards/test-standard/golem.json", {
        "type": "song", "title": "Test Standard", "artist": "golem test", "kind": "original", "rights": {"work": "public-domain"},
        "genres": [{"family": "jazz", "subgenre": None}]}))
    files.append(write("standards/test-standard/song.gsx", json.dumps({
        "v": 1, "slug": "test-standard", "title": "Test Standard", "composer": "golem test", "year": 2026, "style": "blues", "key": "F", "meter": "4/4",
        "tempo": 160, "feel": "swing", "groove": "jazz/bop/brushes", "play": {"motion": "comp", "voicing": "rootless", "parts": {"keys": True, "bass": True, "drums": True}},
        "form": ["A"], "sections": {"A": {"bars": "F7 | Bb7 | F7 | F7 | Bb7 | Bb7 | F7 | D7 | Gm7 | C7 | F7 D7 | Gm7 C7"}}}, indent=1) + "\n"))
    files.append(write("README.md", "# Test content\n\nContent made **for the tests** (docs/quality-automation.md §8): patches, presets, setlists, a song and a standard,\nall prefixed `test-`, generated by `tools/make-test-content.py` — edit the generator, not these files. Installed and removed\nby `bridge/test_content.py` (`python -m bridge.test_content install|remove|status`), which keeps a ledger and never touches\nthe user's content. Every block type here is a REAPER built-in or a JSFX, so it materializes on any machine; the pads kit\nand the drum kit are the factory ones, the grooves the factory grooves.\n"))
    for f in files:
        print(f.relative_to(ROOT))


if __name__ == "__main__":
    main()
