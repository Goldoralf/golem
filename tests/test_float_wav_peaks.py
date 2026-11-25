# SPDX-License-Identifier: GPL-3.0-or-later
"""Les prises du Golem Engine sont en 32 bits flottant : Recordings doit quand même en dessiner l'onde (2026-11-25)."""
import struct
from array import array

from bridge import routes_content as R


def _float_wav(path, frames, nch=2, fr=48000, extensible=False):
    data = array("f", frames).tobytes()
    if extensible:
        fmt = struct.pack("<HHIIHHHHI", 0xFFFE, nch, fr, fr * nch * 4, nch * 4, 32, 22, 32, 3) + \
            struct.pack("<H", 3) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    else:
        fmt = struct.pack("<HHIIHHH", 3, nch, fr, fr * nch * 4, nch * 4, 32, 0)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"fact" + struct.pack("<II", 4, len(frames) // nch) \
        + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def test_une_prise_flottante_donne_son_enveloppe(tmp_path):
    p = tmp_path / "Mix.wav"
    _float_wav(p, [0.0, 0.0] * 500 + [0.5, -0.8] * 500)
    d = R._wav_peaks(str(p), buckets=10)
    assert d["ch"] == 2 and d["rate"] == 48000 and abs(d["dur"] - 1000 / 48000) < 1e-3
    assert d["peaks"][0] == 0.0 and d["peaks"][-1] == 0.8


def test_le_format_extensible_flottant_aussi(tmp_path):
    p = tmp_path / "DI.wav"
    _float_wav(p, [1.5, -0.25] * 100, extensible=True)
    assert R._wav_peaks(str(p), buckets=4)["peaks"] == [1.0] * 4       # borné à 1 : un dépassement reste dessinable
