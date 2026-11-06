# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bed d'une prise armée (docs/compo.md §12 ter) : validation de `target.bed`, téléchargement vérifié (octets, sha256,
STREAMINFO ± 20 ms), cache par sha, état avant le tap, refus après le tap, second stem de la Backing, take.json."""
import hashlib
import http.server
import threading
import time

import pytest

from bridge import compo, compo_bed, golemfm
from bridge.state import state

from .test_compo import IMAP, PRESET, cfgdir  # noqa: F401  (la fixture)

TAKE = {"bpm": 96, "sig": {"num": 4, "den": 4}, "count_in": 1, "bars": 4, "passes": 1, "click": "count-in"}


def fake_flac(seconds, rate=48000, pad=4000):
    """Un FLAC dont seul l'en-tête compte ici : « fLaC » + STREAMINFO (le rack ne décode rien), puis des octets."""
    total = int(round(seconds * rate))
    packed = (rate << 44) | (1 << 41) | (15 << 36) | total            # stéréo, 16 bits
    info = b"\x00" * 10 + packed.to_bytes(8, "big") + b"\x00" * 16
    return b"fLaC" + b"\x80\x00\x00\x22" + info + bytes(range(256)) * (pad // 256)


BLOB = fake_flac(12.5)
SHA = hashlib.sha256(BLOB).hexdigest()


def bed(**kw):
    return {"sha256": SHA, "bytes": len(BLOB), "length_s": 12.5, "gain_db": -6.0, "format": "flac", "offset_s": 0.0,
            "url": f"/api/ext/compo/beds/bd_x/{SHA}.flac", **kw}


class Golemfm:
    """Un golem.fm local : la route des beds, ses requêtes comptées."""
    def __init__(self, files):
        self.files, self.hits = files, []
        owner = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.hits.append((self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != "Bearer tok":
                    self.send_response(401)
                    self.end_headers()
                    return
                body = owner.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/flac")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"


@pytest.fixture
def fm(tmp_path, monkeypatch, cfgdir):  # noqa: F811
    monkeypatch.setattr(compo_bed, "CACHE_DIR", str(tmp_path / "beds"))
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    compo_bed._failed.clear()
    g = Golemfm({f"/api/ext/compo/beds/bd_x/{SHA}.flac": BLOB})
    monkeypatch.setattr(golemfm, "_cfg", lambda: (g.base, "tok"))
    yield g
    g.srv.shutdown()


def _settle(person="alex", want=("ready",), timeout=5.0):
    t_end = time.time() + timeout
    while time.time() < t_end:
        st = ((compo.target_of(person) or {}).get("bed") or {}).get("state")
        if st in want or (st or "").startswith("failed") and "failed" in want:
            return st
        time.sleep(0.02)
    return ((compo.target_of(person) or {}).get("bed") or {}).get("state")


def test_la_validation_borne_le_gain_et_refuse_ce_qu_on_ne_sait_pas_jouer():
    b, why = compo_bed.clean(bed(gain_db=6))
    assert why is None and b["gain_db"] == 0.0                        # convenu : 0 dB au plus
    assert compo_bed.clean(bed(gain_db=-90))[0]["gain_db"] == -60.0
    assert compo_bed.clean(bed(gain_db=None))[0]["gain_db"] == -6.0
    assert compo_bed.clean(bed(offset_s=0.5))[1] == "offset not supported"
    assert compo_bed.clean(bed(format="wav"))[1] == "format wav not supported"
    assert compo_bed.clean(bed(sha256="xyz"))[1] == "bad sha256"
    assert compo_bed.clean(bed(url="/api/ext/files/x"))[1] == "bad url"
    assert compo_bed.clean(bed(url="/api/ext/compo/beds/../x"))[1] == "bad url"


def test_streaminfo_dit_la_duree_exacte(tmp_path):
    p = tmp_path / "b.flac"
    p.write_bytes(BLOB)
    assert compo_bed.streaminfo(str(p)) == (48000, 2, 16, 600000)
    assert compo_bed.check_file(str(p), compo_bed.clean(bed())[0]) is None
    assert compo_bed.check_file(str(p), compo_bed.clean(bed(length_s=12.53))[0]).startswith("length 12.500 s")
    p.write_bytes(b"RIFF" + BLOB[4:])
    assert compo_bed.check_file(str(p), compo_bed.clean(bed(sha256=hashlib.sha256(p.read_bytes()).hexdigest()))[0]) \
        == "unreadable flac"


def test_armer_telecharge_le_bed_une_fois_puis_le_cache_le_sert(fm):
    assert compo.set_target("alex", {"id": "rf:318|ly:4|b:5-8", **TAKE, "bed": bed()}) == (True, "armed")
    assert _settle() == "ready"
    assert fm.hits == [(f"/api/ext/compo/beds/bd_x/{SHA}.flac", "Bearer tok")]
    assert compo.armed_frames() == [{"person": "alex", "target_id": "rf:318|ly:4|b:5-8", "bed": "ready"}]
    # le renvoi de l'armement à la reconnexion : même sha, aucune requête
    compo.set_target("alex", {"id": "rf:318|ly:4|b:5-8", **TAKE, "bed": bed()})
    assert compo.target_of("alex")["bed"]["state"] == "ready" and len(fm.hits) == 1


def test_un_bed_introuvable_se_dit_avant_le_tap(fm):
    fm.files = {}
    compo.set_target("alex", {"id": "rf:1", **TAKE, "bed": bed()})
    assert _settle(want=("failed",)) == "failed: not found on golem.fm"
    assert compo.armed_frames() == [{"person": "alex", "target_id": "rf:1", "bed": "failed: not found on golem.fm"}]


def test_un_jeton_refuse_dit_de_reappairer(fm, monkeypatch):
    monkeypatch.setattr(golemfm, "_cfg", lambda: (fm.base, "revoked"))
    compo.set_target("alex", {"id": "rf:1", **TAKE, "bed": bed()})
    assert _settle(want=("failed",)) == "failed: golem.fm refused the token: pair again"


def test_des_octets_qui_ne_valent_pas_le_sha_ne_sont_jamais_gardes(fm):
    fm.files[f"/api/ext/compo/beds/bd_x/{SHA}.flac"] = BLOB[:-1] + b"\x00"
    compo.set_target("alex", {"id": "rf:1", **TAKE, "bed": bed()})
    assert _settle(want=("failed",)) == "failed: sha256 mismatch"
    assert compo_bed.cached(compo_bed.clean(bed())[0]) is None


def test_les_refus_de_l_armement(fm):
    assert compo.set_target("alex", {"id": "rf:1", **dict(TAKE, passes=0), "bed": bed()}) == \
        (False, "bad take: no bed in loop mode")
    assert compo.set_target("alex", {"id": "rf:1", "bed": bed()}) == (False, "bad take: a bed needs bpm and bars")
    # un offset n'est pas un refus d'armement : la cible est armée, et l'écran le dit avant le tap
    assert compo.set_target("alex", {"id": "rf:1", **TAKE, "bed": bed(offset_s=1.0)}) == (True, "armed")
    assert compo.target_of("alex")["bed"]["state"] == "failed: offset not supported" and fm.hits == []


def _tap_and_wait():
    compo.tap(preset=PRESET)
    for _ in range(200):
        a = compo.RIFF["active"]
        if a is None or a.get("armed"):
            return a
        time.sleep(0.02)


def test_au_tap_le_bed_devient_le_second_stem_et_take_json_en_garde_le_sha(fm):
    got = []
    compo.bind(armed_start=lambda path, alive, bed=None: (got.append(bed), (True, None))[1])
    compo.set_target("alex", {"id": "rf:318|ly:4|b:5-8", **TAKE, "bed": bed(gain_db=-12)})
    a = _tap_and_wait()
    assert a and a["armed"] and got == [(compo_bed.path_of(SHA), -12.0)]
    assert compo.riff_frame()["bed"] == "ready"
    man = {"files": []}
    compo.stamp_manifest(man, a)
    assert man["bed"] == {"sha256": SHA} and man["target"]["id"] == "rf:318|ly:4|b:5-8"


def test_au_tap_un_bed_absent_refuse_la_prise_avec_sa_raison(fm):
    got = []
    compo.bind(armed_start=lambda path, alive, bed=None: (got.append(bed), (True, None))[1])
    fm.files = {}
    compo.set_target("alex", {"id": "rf:9", **TAKE, "bed": bed()})
    _settle(want=("failed",))
    assert _tap_and_wait() is None and got == []                       # jamais le click seul
    assert compo.riff_frame() == {"person": "alex", "state": "refused", "target_id": "rf:9",
                                  "why": "bed not available: not found on golem.fm"}


def test_sans_bed_rien_ne_change(fm):
    got = []
    compo.bind(armed_start=lambda path, alive: (got.append(path), (True, None))[1])   # l'ancienne signature
    compo.set_target("alex", {"id": "rf:2", **TAKE})
    a = _tap_and_wait()
    assert a["armed"] and len(got) == 1 and "bed" not in compo.target_of("alex")
    assert compo.armed_frames() == [] and "bed" not in (compo.riff_frame() or {})
    man = {"files": []}
    compo.stamp_manifest(man, a)
    assert "bed" not in man and fm.hits == []


def test_le_cache_garde_sa_taille_le_plus_ancien_part(tmp_path, monkeypatch):
    monkeypatch.setattr(compo_bed, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(compo_bed, "CACHE_MAX", 2500)
    for i, n in enumerate("abc"):
        p = tmp_path / f"{n}.flac"
        p.write_bytes(b"x" * 1000)
        import os
        os.utime(p, (1000 + i, 1000 + i))
    compo_bed._prune(str(tmp_path / "a.flac"))
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a.flac", "c.flac"]     # b, le plus ancien hors `keep`


def test_le_second_stem_de_la_backing(monkeypatch):
    from bridge import app
    sent = []
    monkeypatch.setattr(app._backing_ctl, "load_files", lambda slug, files, mix: sent.append((files, mix)))
    monkeypatch.setattr(state, "backing", {"present": False}, raising=False)
    app._riff_armed_start("/c.wav", lambda: False, bed=("/b.flac", -6.0))
    files, mix = sent[0]
    assert files == {"drums": "/c.wav", "other": "/b.flac"}
    assert mix["other"] == {"mute": 0, "vol": round(10 ** (-6 / 20), 6)} and mix["drums"]["vol"] == 1.0


def test_un_fichier_du_cache_qui_ne_vaut_pas_son_sha_n_est_jamais_joue(fm):
    b = compo_bed.clean(bed())[0]
    import os
    os.makedirs(compo_bed.CACHE_DIR, exist_ok=True)
    with open(compo_bed.path_of(SHA), "wb") as f:
        f.write(BLOB[:-1] + b"\x01")                                     # la bonne taille, pas les bons octets
    assert compo_bed.cached(b) is None and not os.path.exists(compo_bed.path_of(SHA))
    assert compo_bed.fetch(b) == (compo_bed.path_of(SHA), None) and len(fm.hits) == 1   # retéléchargé
