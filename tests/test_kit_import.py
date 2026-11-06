# SPDX-License-Identifier: GPL-3.0-or-later
"""« + Add » d'une batterie par le rack (docs/drums-kit.md §8, 2026-10-11) : les parseurs lisent la table
pièce → note dans le midimap DrumGizmo ou les clés du .sfz (jamais déclarée), la lecture d'un dossier dit ce
qu'il contient AVANT d'écrire, l'installation copie et pose une fiche `imported` qui se supprime avec son dossier."""
import json
import os
import struct

import pytest

from bridge import kit_import as KI
from bridge import kits as K

DRUMKIT = """<?xml version="1.0" encoding="UTF-8"?>
<drumkit name="Salamander Drumkit" description="rock · multi-mic" version="1.0">
  <channels><channel name="KickL"/><channel name="SnareTop"/><channel name="OHL"/><channel name="OHR"/><channel name="Room"/><channel name="Trig"/></channels>
  <instruments>
    <instrument name="Kick" file="kick/kick.xml"><channelmap in="KickL" out="KickL"/></instrument>
    <instrument name="Snare" file="snare/snare.xml"/>
    <instrument name="HiHat-Closed" file="hh/c.xml"/>
    <instrument name="HiHat-Open" file="hh/o.xml"/>
    <instrument name="Tom1" file="t1.xml"/><instrument name="FloorTom" file="t3.xml"/>
    <instrument name="Ride" file="r.xml"/><instrument name="Crash" file="c1.xml"/><instrument name="Crash2" file="c2.xml"/>
    <instrument name="Weird" file="w.xml"/>
  </instruments>
</drumkit>"""
MIDIMAP = """<?xml version="1.0"?>
<midimap>
  <map note="36" instr="Kick"/><map note="38" instr="Snare"/><map note="42" instr="HiHat-Closed"/><map note="46" instr="HiHat-Open"/>
  <map note="44" instr="HiHat-Closed"/><map note="48" instr="Tom1"/><map note="43" instr="FloorTom"/><map note="51" instr="Ride"/>
  <map note="49" instr="Crash"/><map note="57" instr="Crash2"/><map note="60" instr="Weird"/><map note="200" instr="Kick"/>
</midimap>"""
SFZ = """// a drum kit
<control> default_path=samples/
<global> ampeg_release=0.3
<group> loop_mode=one_shot
<region> key=36 sample=Kick_v1.wav
<region> key=38 sample=Snare Top_v1.wav
<region> lokey=42 hikey=42 pitch_keycenter=42 sample=HH_Closed.wav
<region> key=c#3 sample=HH_Open.wav
#include "toms.sfz"
<region> key=51 sample=Ride_Bow.wav region_label=Ride
"""
SFZ_TOMS = "<group> loop_mode=one_shot\n<region> key=48 sample=Tom1.wav\n<region> key=43 sample=Tom_Floor.wav\n"


def _wav(path, sr=44100, bits=24, n=100):
    with open(path, "wb") as f:
        data = b"\x00" * (n * bits // 8)
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * bits // 8, bits // 8, bits)
                + b"data" + struct.pack("<I", len(data)) + data)


def test_le_midimap_drumgizmo_donne_les_pieces_une_note_par_piece_et_dit_ce_qu_il_ne_reconnait_pas():
    dk = KI.parse_drumkit_xml(DRUMKIT)
    assert dk["name"] == "Salamander Drumkit" and dk["channels"] == ["KickL", "SnareTop", "OHL", "OHR", "Room", "Trig"]
    assert len(dk["instruments"]) == 10
    table = KI.parse_midimap_xml(MIDIMAP)
    assert 200 not in table and table[36] == "Kick"
    pieces, unknown, extra = KI.pieces_from_names(table)
    assert pieces == {"kick": 36, "snare": 38, "hh-closed": 42, "hh-open": 46, "tom1": 48, "tom3": 43,
                      "ride": 51, "crash1": 49, "crash2": 57}
    assert extra == {"hh-closed": [44]}                      # la 2e note du charleston fermé reste visible, pas perdue
    assert unknown == ["Weird (60)"]
    assert all(e in __import__("bridge.drumkits", fromlist=["ELEMENTS"]).ELEMENTS for e in pieces)


def test_le_mix_d_usine_vient_des_canaux_groupe_et_pan_lus_dans_le_nom_triggers_coupes():
    mix = KI._mix_from_channels(["KickL", "SnareTop", "OHL", "OHR", "Room", "Trig"])
    assert [m["group"] for m in mix] == ["kick", "snare", "oh", "oh", "room", "trig"]
    assert mix[2]["pan"] < 0 < mix[3]["pan"] and mix[5]["gain"] == -60.0 and mix[0]["ch"] == 1
    # une paire stéréo déjà mixée (« left » / « right ») : tout à gauche, tout à droite — vécu le 2026-10-14, les deux
    # canaux tombaient au centre et un kit stéréo jouait en mono
    assert [m["pan"] for m in KI._mix_from_channels(["left", "right"])] == [-1.0, 1.0]


def test_le_sfz_se_lit_avec_include_heritage_default_path_et_noms_de_notes(tmp_path):
    (tmp_path / "toms.sfz").write_text(SFZ_TOMS)
    regions, dp = KI.parse_sfz(SFZ, str(tmp_path), 0, lambda inc: (tmp_path / inc).read_text())
    assert dp == "samples/" and len(regions) == 7                                             # 5 ici + 2 dans l'include
    by = {r["sample"]: r for r in regions}
    assert by["Kick_v1.wav"]["loop_mode"] == "one_shot" and by["Kick_v1.wav"]["ampeg_release"] == "0.3"   # <group> et <global> hérités
    assert by["Tom1.wav"]["loop_mode"] == "one_shot" and "ampeg_release" not in by["Tom1.wav"]           # l'include a son propre contexte
    assert "Snare Top_v1.wav" in by                                                            # un espace dans un chemin
    names = KI.sfz_note_names(regions)
    assert names[49] == "HH_Open" and names[42] == "HH_Closed" and names[51] == "Ride"       # c#3 = 49 ; pitch_keycenter ; label
    pieces, unknown, _ = KI.pieces_from_names(names)
    assert pieces == {"kick": 36, "snare": 38, "hh-closed": 42, "hh-open": 49, "tom1": 48, "tom3": 43, "ride": 51} and unknown == []


def test_guess_element_couvre_les_graphies_courantes():
    g = KI.guess_element
    assert g("36-Kick") == "kick" and g("BD") == "kick" and g("Snare Rimshot") == "snare-rim" and g("SideStick") == "snare-xstick"
    assert g("HH Pedal") == "hh-pedal" and g("hihat_half") == "hh-half" and g("Hat Open Edge") == "hh-open-edge"
    assert g("Tom 2 rim") == "tom2-rim" and g("High Tom") == "tom1" and g("Floor Tom") == "tom3" and g("Tom7") == "tom4"
    assert g("Ride Bell") == "ride-bell" and g("China") == "china" and g("Splash") == "splash" and g("Cowbell") == "aux1"
    assert g("crash", 1) == "crash2" and g("Crash 1 edge") == "crash1-edge" and g("") is None and g("Weird") is None


@pytest.fixture
def kit_on_disk(tmp_path):
    src = tmp_path / "usb" / "Salamander"; (src / "kick").mkdir(parents=True)
    (src / "salamander.xml").write_text(DRUMKIT); (src / "midimap.xml").write_text(MIDIMAP)
    _wav(src / "kick" / "kick1.wav", 48000, 24); _wav(src / "kick" / "kick2.wav")
    sfzdir = tmp_path / "usb" / "MySFZ"; sfzdir.mkdir()
    (sfzdir / "kit.sfz").write_text(SFZ); (sfzdir / "toms.sfz").write_text(SFZ_TOMS)
    _wav(sfzdir / "Kick_v1.wav")
    return tmp_path / "usb"


def test_scan_trouve_un_dossier_drumgizmo_et_chaque_sfz(kit_on_disk):
    hits = KI.scan(str(kit_on_disk))
    assert [(h["engine"], h["name"]) for h in hits] == [("sfz", "kit"), ("sfz", "toms"), ("drumgizmo", "Salamander Drumkit")]


def test_read_dit_ce_que_le_rack_a_lu_avant_d_ecrire(kit_on_disk, monkeypatch, tmp_path):
    monkeypatch.setattr(KI.C, "ROOT", str(tmp_path / "rack"))
    monkeypatch.setattr(KI, "availability", lambda eng: (eng == "sfz", None if eng == "sfz" else "DrumGizmo is not installed on this machine"))
    monkeypatch.setattr(KI, "_kit_exists", lambda kid: False)
    r = KI.read(str(kit_on_disk / "Salamander"))
    assert r["ok"] and r["engine"] == "drumgizmo" and r["name"] == "Salamander Drumkit" and r["mics"] == 6
    assert r["pieces"]["kick"] == 36 and r["pieces_src"] == "midimap.xml" and r["unknown"] == ["Weird (60)"]
    assert r["files"] == 4 and r["sample_rate"] == 48000 and r["bits"] == 24 and r["bytes"] > 0
    assert r["available"] is False and "DrumGizmo" in r["why"] and "Linux only" in r["os_note"]
    assert r["id"] == "drums-salamander-drumkit" and r["dest"] == "library/drumkits/salamander-drumkit" and r["exists"] is False
    r2 = KI.read(str(kit_on_disk / "MySFZ" / "kit.sfz"))
    assert r2["ok"] and r2["engine"] == "sfz" and r2["regions"] == 7 and r2["pieces"]["hh-open"] == 49 and r2["available"] is True
    assert r2["dest"] == "library/sfz/kit"
    assert KI.read(str(kit_on_disk))["ok"] is False                      # un dossier sans kit : dit, pas deviné
    with pytest.raises(ValueError):
        KI.install(str(kit_on_disk / "Salamander"))                      # moteur absent → on n'installe pas


def test_install_copie_pose_une_fiche_importee_qui_se_supprime_avec_son_dossier(kit_on_disk, monkeypatch, tmp_path):
    rack = tmp_path / "rack"; (rack / "library" / "kits").mkdir(parents=True)
    monkeypatch.setattr(KI.C, "ROOT", str(rack)); monkeypatch.setattr(K.C, "ROOT", str(rack))
    monkeypatch.setattr(K, "KITS_DIR", str(rack / "library" / "kits"))
    monkeypatch.setattr(KI, "availability", lambda eng: (True, None))
    jid = KI.install(str(kit_on_disk / "MySFZ" / "kit.sfz"), name="My SFZ kit")
    import time
    for _ in range(100):
        j = KI.job(jid)
        if j["state"] != "running":
            break
        time.sleep(0.05)
    assert j["state"] == "done", j
    kit = j["result"]["kit"]
    assert kit["id"] == "drums-my-sfz-kit" and kit["engine"] == "sfz" and kit["sfz"] == "library/sfz/my-sfz-kit/kit.sfz"
    assert kit["notes"]["kick"] == 36 and kit["imported"]["dir"] == "library/sfz/my-sfz-kit" and kit["imported"]["files"] == 3
    assert (rack / "library" / "sfz" / "my-sfz-kit" / "toms.sfz").is_file()
    assert j["done_bytes"] == j["total_bytes"] > 0
    listed = [k for k in K.list_kits() if k["id"] == kit["id"]][0]
    assert listed["factory"] is False and K.is_imported(listed) and not K.is_factory(listed)
    assert K.is_factory({"engine": "sfz", "sfz": "x"})                  # sans `imported`, une batterie reste d'usine
    with pytest.raises(ValueError):
        KI.install(str(kit_on_disk / "MySFZ" / "kit.sfz"), name="My SFZ kit")   # déjà là : on le dit, on n'écrase pas
    synced = []
    monkeypatch.setattr(K, "_sync_soon", lambda: synced.append(1))
    r = K.delete_kit(kit["id"])
    assert r["ok"] and r["freed_bytes"] > 0 and synced == [1]           # la carte doit quitter le rig-manifest
    assert not (rack / "library" / "sfz" / "my-sfz-kit").exists() and K.get_kit(kit["id"]) is None


def test_un_kit_d_usine_ne_se_supprime_toujours_pas(monkeypatch, tmp_path):
    kd = tmp_path / "kits"; kd.mkdir(); monkeypatch.setattr(K, "KITS_DIR", str(kd))
    (kd / "drums-black-pearl.json").write_text(json.dumps({"id": "drums-black-pearl", "engine": "avldrums", "bank": "black-pearl", "factory": True}))
    assert K.delete_kit("drums-black-pearl")["factory"] is True and (kd / "drums-black-pearl.json").is_file()


def test_l_extraction_refuse_un_membre_qui_sort_du_dossier(tmp_path):
    import zipfile
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        KI._safe_extract(str(z), str(tmp_path / "out"))
    ok = tmp_path / "ok.zip"
    with zipfile.ZipFile(ok, "w") as zf:
        zf.writestr("Kit/kit.sfz", SFZ)
    assert KI._safe_extract(str(ok), str(tmp_path / "out2")) and (tmp_path / "out2" / "Kit" / "kit.sfz").is_file()


def test_un_job_kit_install_qui_porte_une_carte_n_installe_rien(monkeypatch):
    """golem.fm ne doit pas pousser kit-install pour la carte d'une batterie importée ailleurs ; s'il le fait, le rack
    accuse réception sans poser une fiche qui pointerait des fichiers absents (docs/drums-kit.md §8.2)."""
    from bridge import tones_jobs as TJ
    card = json.dumps({"id": "drums-salamander", "engine": "drumgizmo", "imported": {"dir": "library/drumkits/salamander"}}).encode()
    monkeypatch.setattr(TJ, "_blob_bytes", lambda job, tmp: card)
    ack = TJ._kit_install({"action": "kit-install", "sha": "x"})
    assert ack["card"] is True and ack["installed"] is False and ack["kit"]["id"] == "drums-salamander"
    monkeypatch.setattr(TJ, "_blob_bytes", lambda job, tmp: b"not a zip")
    with pytest.raises(RuntimeError):
        TJ._kit_install({"action": "kit-install", "sha": "x"})
