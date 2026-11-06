# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture A2 sur un poste (2026-10-03) : la jumelle classique du même nom joue à sa place, et le rack sait
la tirer de TONE3000 sans retirer l'A2 du catalogue — un patch fait sous Linux reste portable."""
import json

from bridge import resolver, rig, routes_t3k as T

A2 = {"id": 418200, "name": "Tim R Fender TwinVerb Vibrato Bright", "file": "assets/m/vib-a2.nam", "arch": "2"}
A2B = {"id": 418201, "name": "Tim R Fender TwinVerb Norm Bright", "file": "assets/m/norm-a2.nam", "arch": "2"}
A1 = {"id": 82929, "name": "Tim R Fender TwinVerb Vibrato Bright", "file": "assets/m/vib.nam", "arch": 1}
FEATHER = {"id": 9, "name": "Tim R Fender TwinVerb Vibrato Bright Feather", "file": "assets/m/vib-f.nam", "arch": 1}


def test_hors_linux_la_jumelle_du_meme_nom_joue(monkeypatch):
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    assert resolver.playable_twin(A2, [A2, A2B, FEATHER, A1]) is A1           # standard avant feather
    assert resolver.playable_twin(A2, [A2, FEATHER]) is FEATHER
    assert resolver.playable_twin(A2B, [A2, A2B, A1]) is A2B                  # jamais un AUTRE réglage
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    assert resolver.playable_twin(A2, [A2, A1]) is A2                         # Linux lit l'A2 : rien ne change


def test_les_jumelles_s_ajoutent_au_pack_sans_retirer_l_a2(monkeypatch, tmp_path):
    index = tmp_path / "tones-index.json"
    index.write_text(json.dumps({"tones": [{"id": 246, "title": "Fender Twin Pack", "format": "nam",
                                            "models": [A2, A2B]}]}), encoding="utf-8")
    monkeypatch.setattr(T, "INDEX", str(index))
    api = [{"id": 82929, "name": "Tim R Fender TwinVerb Vibrato Bright", "architecture_version": 1, "model_url": "https://x/a.nam"},
           {"id": 418200, "name": "Tim R Fender TwinVerb Vibrato Bright", "architecture_version": 2, "model_url": "https://x/b.nam"},
           {"id": 82930, "name": "Tim R Fender TwinVerb Norm Bright", "architecture_version": 1, "model_url": "https://x/c.nam"}]
    monkeypatch.setattr(T, "_page_all", lambda path, required=True: api)
    got = []
    monkeypatch.setattr(T, "_download_model", lambda m, reldir, title, fmt: got.append((m["id"], reldir)) or
                        {"id": m["id"], "name": m["name"], "file": reldir + "/x.nam", "arch": 1})
    assert T.install_twins(246, [A2["name"]]) == [A2["name"]]
    assert got == [(82929, "assets/m")]                                       # la jumelle seule, dans le dossier du pack
    ids = [m["id"] for m in json.loads(index.read_text(encoding="utf-8"))["tones"][0]["models"]]
    assert ids == [418200, 418201, 82929]                                     # les A2 restent
    got.clear()
    assert T.install_twins(246, [A2["name"]]) == [] and got == []             # déjà là : rien à retélécharger
