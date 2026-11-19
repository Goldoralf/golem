# SPDX-License-Identifier: GPL-3.0-or-later
"""Un dossier à la place du fichier à rendre gèle REAPER (2026-11-19) : la boîte « Can't create file » est modale.
Le bridge l'efface avant d'envoyer le rendu ; un vrai fichier, ou une autre commande, n'est jamais touché."""
from bridge import commands


def test_un_dossier_wav_est_efface_avant_le_rendu(tmp_path):
    d = tmp_path / "D.wav"
    (d / "preview.wav").parent.mkdir()
    (d / "preview.wav").write_bytes(b"RIFF")
    commands._clear_render_target({"action": "preview", "op": "render", "out": str(d)})
    assert not d.exists()


def test_un_fichier_ou_une_autre_commande_reste(tmp_path):
    f = tmp_path / "A.wav"
    f.write_bytes(b"RIFF")
    commands._clear_render_target({"action": "preview", "out": str(f)})
    assert f.read_bytes() == b"RIFF"
    d = tmp_path / "B.wav"
    d.mkdir()
    commands._clear_render_target({"action": "reamp", "out": str(d)})
    commands._clear_render_target({"action": "preview", "out": str(tmp_path)})   # pas un .wav : jamais
    assert d.is_dir() and tmp_path.is_dir()
