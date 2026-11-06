# SPDX-License-Identifier: GPL-3.0-or-later
"""La GARDE D'IR du compile (2026-09-14, Sunfunk « un delay d'un feedback alors que tout est désactivé ») :
un .wav d'IR qui porte une seconde impulsion après 100 ms est copié COUPÉ juste avant dans le cache,
et le journal le dit ; un IR propre est copié tel quel ; un float32 se lit aussi.
`.venv/bin/python -m pytest tests/test_ir_guard.py -q`"""
import math
import os
import struct

from bridge import compile_rig as cr


def _wav(path, samples, sr=48000, fmt="pcm24"):
    body = bytearray()
    if fmt == "pcm24":
        for v in samples:
            body += struct.pack("<i", max(-8388608, min(8388607, int(round(v * 8388608)))))[:3]
        fmtc = struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 3, 3, 24)
    else:
        for v in samples:
            body += struct.pack("<f", v)
        fmtc = struct.pack("<IHHIIHH", 16, 3, 1, sr, sr * 4, 4, 32)
    open(path, "wb").write(b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVE" + b"fmt " + fmtc + b"data" + struct.pack("<I", len(body)) + bytes(body))


def _ir(sr=48000, ms=1600, echo_ms=None, echo_db=-22.0):
    n = int(sr * ms / 1000)
    x = [0.0] * n
    for i in range(0, int(sr * 0.04)):                      # un baffle : décroissance exponentielle sur 40 ms
        x[i] = 0.9 * math.exp(-i / (sr * 0.006)) * (1 if i % 2 == 0 else -1)
    if echo_ms is not None:
        j = int(sr * echo_ms / 1000)
        for i in range(0, int(sr * 0.02)):
            x[j + i] = 0.9 * (10 ** (echo_db / 20)) * math.exp(-i / (sr * 0.004))
    return x


def test_une_impulsion_tardive_est_vue_et_coupee(tmp_path, monkeypatch):
    src, dst = str(tmp_path / "palmer.wav"), str(tmp_path / "palmer_cache.wav")
    _wav(src, _ir(echo_ms=480))
    late = cr.ir_late_impulse(src)
    assert late and 470 <= late[0] <= 490 and -25 <= late[1] <= -19
    assert cr._ir_guard(src, dst) == late
    x, sr = cr._read_wav_mono(dst)
    assert 100 <= 1000 * len(x) / sr <= 480                  # coupée AVANT l'écho, jamais sous 100 ms
    assert cr.ir_late_impulse(dst) is None                   # la copie est propre
    assert abs(x[0] - 0.9) < 0.01                            # et la tête est intacte


def test_un_ir_propre_est_copie_tel_quel(tmp_path):
    src, dst = str(tmp_path / "clean.wav"), str(tmp_path / "clean_cache.wav")
    _wav(src, _ir(ms=500))
    assert cr.ir_late_impulse(src) is None
    assert cr._ir_guard(src, dst) is None
    assert open(src, "rb").read() == open(dst, "rb").read()


def test_le_lecteur_lit_aussi_le_float32(tmp_path):
    src = str(tmp_path / "f32.wav")
    _wav(src, _ir(echo_ms=300, echo_db=-30), fmt="f32")
    late = cr.ir_late_impulse(src)
    assert late and 290 <= late[0] <= 310


def test_safe_asset_passe_par_la_garde(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "ASSET_CACHE", str(tmp_path / "cache"))
    src = str(tmp_path / "ir with space.wav"); _wav(src, _ir(echo_ms=480))
    dst = cr._safe_asset(src)
    assert dst.startswith(str(tmp_path / "cache")) and " " not in os.path.basename(dst)
    assert cr.ir_late_impulse(dst) is None
    nam = str(tmp_path / "amp.nam"); open(nam, "w").write("{}")
    assert open(cr._safe_asset(nam)).read() == "{}"           # un .nam n'est pas jugé
