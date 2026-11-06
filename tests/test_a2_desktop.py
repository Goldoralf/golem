# SPDX-License-Identifier: GPL-3.0-or-later
"""Une capture A2 ne joue pas hors Linux — mesuré le 2026-10-01 (docs/audit-2026-10-01-parite-coeurs-os.md).

Le NAM VST3 officiel publié (Windows, macOS) ne lit pas `architecture: SlimmableContainer` et laisse
passer la guitare à sec SANS erreur. La garde partagée (`rig._wrong_kind`) le dit sur ces OS, par le
CONTENU du fichier et pas son nom ; l'état de bloc en fait la raison `format` (pas `capture` : la
télécharger ailleurs n'y changerait rien). Sous Linux, rien ne change."""
import json

from bridge import blockstatus, rig


def _nam(tmp_path, name, arch):
    p = tmp_path / name
    p.write_text(json.dumps({"version": "0.7.0", "architecture": arch, "config": {}, "weights": []}))
    return str(p)


def test_a2_is_fine_on_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    assert rig._wrong_kind({"type": "amp"}, _nam(tmp_path, "x-a2.nam", "SlimmableContainer")) is None


def test_a2_refused_on_windows_and_macos(tmp_path, monkeypatch):
    path = _nam(tmp_path, "x.nam", "SlimmableContainer")       # le nom ne dit rien : c'est le contenu
    for plat in ("win32", "darwin"):
        monkeypatch.setattr(rig, "_platform", lambda plat=plat: plat)
        assert rig._wrong_kind({"type": "pedal-nam"}, path) == rig.A2_DESKTOP_WHY


def test_wavenet_plays_everywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    assert rig._wrong_kind({"type": "amp"}, _nam(tmp_path, "y-a2.nam", "WaveNet")) is None


def test_block_state_reason_is_format(tmp_path, monkeypatch):
    path = _nam(tmp_path, "z.nam", "SlimmableContainer")
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    monkeypatch.setattr("bridge.resolver._resolve", lambda ref, comps, model=None: path)
    monkeypatch.setattr(blockstatus, "plugin_state", lambda *a, **k: True)
    st = blockstatus.block_state({"type": "amp", "ref": "t3k:1"}, comps={}, manifest_fn=lambda: [])
    assert st["state"] == "unavailable" and st["reason"] == "format"


def test_caps_publishes_unreadable_formats(monkeypatch):
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    assert rig.nam_unreadable() == ["SlimmableContainer"]
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    assert rig.nam_unreadable() == []                           # liste vide : elle fait foi aussi


def test_t3k_import_keeps_a1_first_where_a2_is_unreadable(monkeypatch):
    from bridge import routes_t3k
    a2 = [{"id": 11, "name": "Clean"}, {"id": 12, "name": "Crunch"}]
    a1 = [{"id": 1, "name": "Clean"}, {"id": 2, "name": "Crunch"}, {"id": 3, "name": "Lead"}]
    monkeypatch.setattr(routes_t3k, "_page_all",
                        lambda url, required=True: a2 if "architecture=2" in url else a1)
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    assert [m["id"] for m in routes_t3k._fetch_models(9)] == [11, 12, 3]       # Linux : A2 d'abord, jumeaux A1 écartés
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    got = routes_t3k._fetch_models(9)
    assert [m["id"] for m in got] == [1, 2, 3, 11, 12]                          # A1 en tête, A2 gardés derrière
    assert [m["id"] for m in routes_t3k._cap_models(got, 2)] == [1, 2, 11, 12]  # 2 réglages = 4 fichiers
