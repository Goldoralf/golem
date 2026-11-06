# SPDX-License-Identifier: GPL-3.0-or-later
"""Le vocabulaire OUVERT des stems (docs/separation.md §7) : la famille décide du mix par défaut et de la voix du
karaoké ; un nom hors forme, ou au-delà de 16, est ignoré et signalé — jamais renommé."""
from bridge import golemfm as M


def test_la_famille_est_ce_qui_precede_le_premier_tiret_avec_deux_alias():
    assert [M.stem_family(s) for s in ("guitar", "guitar-2", "guitar-electric", "voice-1", "vocals-lead", "keys",
                                       "piano-2", "strings")] == \
        ["guitar", "guitar", "guitar", "vocals", "vocals", "piano", "piano", "strings"]


def test_guitare_coupee_coupe_toutes_les_guitares_mais_un_reglage_propre_gagne():
    mix = {"guitar": {"mute": 1, "vol": 1.0}, "guitar-acoustic": {"mute": 0, "vol": 0.8}}
    out = M.expand_mix(mix, ["guitar-electric", "guitar-acoustic", "guitar-1", "bass", "vocals"])
    assert out["guitar-electric"] == {"mute": 1, "vol": 1.0} and out["guitar-1"] == {"mute": 1, "vol": 1.0}
    assert out["guitar-acoustic"] == {"mute": 0, "vol": 0.8}            # son réglage à lui
    assert "bass" not in out and "vocals" not in out
    assert mix == {"guitar": {"mute": 1, "vol": 1.0}, "guitar-acoustic": {"mute": 0, "vol": 0.8}}   # pas modifié


def test_hors_vocabulaire_ou_au_dela_de_16_est_ignore(caplog):
    files = {"vocals": "a", "Guitar": "b", "bass_2": "c", **{"x%d" % i: str(i) for i in range(20)}}
    kept, ignored = M.keep_stems(files)
    assert "vocals" in kept and len(kept) == 16
    assert "Guitar" in ignored and "bass_2" in ignored and len(ignored) == len(files) - 16
    assert "ignored" in caplog.text


def test_la_voix_du_karaoke_est_la_famille_vocals(monkeypatch):
    from bridge import karaoke as K
    monkeypatch.setattr(M, "is_song_key", lambda k: True)
    monkeypatch.setattr(M, "local_files", lambda k: {"vocals-lead": "a", "voice-2": "b", "guitar-1": "c", "vocals": "d"})
    monkeypatch.setattr(M, "read_meta", lambda k: {})
    from bridge import songs
    monkeypatch.setattr(songs, "load", lambda k: {"title": "T"})
    assert sorted(K._kmeta("rs:x")["voice_stems"]) == ["vocals", "vocals-lead", "voice-2"]
