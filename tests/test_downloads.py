# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistrer dans les Téléchargements de la machine (bridge/downloads.py) : jamais d'écrasement, jamais hors du dossier."""
import os

from bridge import downloads as D


def test_un_nom_deja_pris_devient_nom_2_et_un_chemin_ne_sort_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "downloads_dir", lambda: str(tmp_path))
    a = D.save_bytes("engine.golem-engine.json", b"{}")
    b = D.save_bytes("engine.golem-engine.json", b"{}")
    assert a["name"] == "engine.golem-engine.json" and b["name"] == "engine.golem-engine (2).json"
    c = D.save_bytes("../../etc/evil.json", b"x")                       # le chemin est retiré : le nom seul reste
    assert os.path.dirname(c["path"]) == str(tmp_path) and c["name"] == "evil.json"
    src = tmp_path / "backup.zip"
    src.write_bytes(b"zip")
    d = D.save_copy(str(src), "backup.zip")
    assert d["name"] == "backup (2).zip" and open(d["path"], "rb").read() == b"zip"


def test_un_flux_est_ecrit_tel_quel_et_le_nom_vient_de_la_route(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(D, "downloads_dir", lambda: str(tmp_path))
    r = D.save_stream("take.wav", io.BytesIO(b"RIFF" + b"\0" * 5000), chunk=1024)
    assert open(r["path"], "rb").read()[:4] == b"RIFF" and os.path.getsize(r["path"]) == 5004
    assert D.filename_of('attachment; filename="groove.mid"', "/api/groove/x") == "groove.mid"
    assert D.filename_of(None, "/api/kit/pads-lofi/export") == "export"
    assert D.filename_of("", "/api/take/rpp/2026-10-14%20jam") == "2026-10-14 jam"


def test_la_copie_par_adresse_est_reservee_a_l_ecran_local_et_aux_adresses_du_rack():
    import types
    from bridge import routes_system as R
    req = lambda host: types.SimpleNamespace(client=types.SimpleNamespace(host=host), base_url="http://127.0.0.1:8770/")
    assert R.system_save_local_url(req("192.168.0.22"), {"url": "/api/groove/x"}).status_code == 403
    for bad in ("https://evil.example/x", "//evil.example/api/x", "/etc/passwd", "/api/../etc/passwd", ""):
        assert R.system_save_local_url(req("127.0.0.1"), {"url": bad}).status_code == 400, bad
