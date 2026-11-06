# SPDX-License-Identifier: GPL-3.0-or-later
"""La `source` d'un asset du store golem.fm (accord golem.fm du 2026-10-15) : le rack écrit "golemfm", et lit encore
"maestrium" — l'ancien nom, porté par des presets déjà publiés. Le renommage du 2026-10-15 avait cassé la lecture :
publier un preset n'envoyait plus ses kits et captures perso (la comparaison ne voyait plus rien)."""
from bridge import preset_export, tones_sync


def _publish(monkeypatch, deps, blobs, missing):
    sent = []

    def req(method, path, **k):
        if path.endswith("/manifest"):
            return 200, {"missing_blobs": missing}
        if "/assets" in path:
            sent.append(path.split("sha256=")[1].split("&")[0])
            return 200, {}
        return 200, {}
    monkeypatch.setattr(preset_export, "build_export", lambda pid: ({"deps": deps, "unresolved": []}, blobs))
    monkeypatch.setattr(tones_sync, "_req", req)
    monkeypatch.setattr("bridge.loans.lent_deps", lambda deps: [])
    return tones_sync.publish_preset("paper-kite"), sent


def test_les_deux_noms_du_store_envoient_leurs_fichiers(monkeypatch, tmp_path):
    a, b = tmp_path / "kit.zip", tmp_path / "old.nam"
    a.write_text("a"); b.write_text("b")
    deps = [{"sha256": "a1", "source": "golemfm"}, {"sha256": "b2", "source": "maestrium"}, {"sha256": "c3", "source": "t3k"}]
    r, sent = _publish(monkeypatch, deps, {"a1": str(a), "b2": str(b), "c3": str(a)}, ["a1", "b2", "c3"])
    assert r["ok"] and sorted(sent) == ["a1", "b2"]              # la capture TONE3000 se tire du compte, pas d'ici


def test_le_rack_ecrit_golemfm():
    assert preset_export.STORE_SOURCE == "golemfm" and "maestrium" in preset_export.STORE_SOURCES
