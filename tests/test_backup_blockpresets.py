# SPDX-License-Identifier: GPL-3.0-or-later
"""Les presets de bloc entrent dans les Backups (2026-10-11) : seulement les TIENS — les 158 d'usine sont
versionnés et reviennent avec le code, les sauver serait du bruit. `all` les emporte."""
import io
import json
import os
import zipfile

from bridge import backup as B


def test_les_presets_de_bloc_perso_sont_comptes_et_sauves_sans_l_usine(monkeypatch, tmp_path):
    bp = tmp_path / "library" / "block-presets" / "gate"; bp.mkdir(parents=True)
    (bp / "soft.json").write_text(json.dumps({"name": "Soft", "params": {"thresh": -55}, "factory": True}))
    (bp / "palm-mute-tight.json").write_text(json.dumps({"name": "Palm-mute tight", "params": {"thresh": -38}, "inst": "guitar"}))
    monkeypatch.setattr(B, "BLOCK_PRESETS_DIR", str(bp.parent))
    monkeypatch.setattr(B.C, "ROOT", str(tmp_path))
    assert "blockpresets" in B.KINDS and "blockpresets" in B.ALL_PARTS
    c = B._block_presets_stat()
    assert c["n"] == 1 and c["factory"] == 1 and c["bytes"] > 0
    buf = io.BytesIO(); entries = []
    with zipfile.ZipFile(buf, "w") as zf:
        B._add_kind(zf, "blockpresets", set(), entries)
        names = zf.namelist()
    assert names == ["library/block-presets/gate/palm-mute-tight.json"]      # le tien, pas l'usine
