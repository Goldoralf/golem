# SPDX-License-Identifier: GPL-3.0-or-later
"""La signature des originaux, vérifiée hors ligne (lot 8, golem-format.md §10). Ed25519 en Python pur contre les
vecteurs de la RFC 8032 ; puis le cycle réel : golem.fm signe les octets de golem.json, le rack installe le fichier
(et réécrit son manifeste), la signature reste vérifiable."""
import base64
import hashlib
import json
import os
import zipfile

import pytest

from bridge import config as C, ed25519, golemfile as G, golemfm as M, signatures as SIG, songs as S

# ── Ed25519 : RFC 8032 §7.1, tests 1 et 2 ──

RFC = [("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
       ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")]


@pytest.mark.parametrize("pk,msg,sig", RFC)
def test_ed25519_vecteurs_rfc(pk, msg, sig):
    pk, msg, sig = bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig)
    assert ed25519.verify(pk, msg, sig)
    assert not ed25519.verify(pk, msg + b"x", sig)
    assert not ed25519.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1]))
    assert not ed25519.verify(pk, msg, sig[:63])


# ── un signataire de test : Ed25519 PUR, la signature de la RFC (le rack ne signe jamais ; seul le test signe) ──

SECRET = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")


def _sign(msg, secret=SECRET):
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    def enc(pt):
        x, y, z, _ = pt
        zi = pow(z, ed25519.P - 2, ed25519.P)
        x, y = x * zi % ed25519.P, y * zi % ed25519.P
        return int.to_bytes(y | ((x & 1) << 255), 32, "little")
    A = enc(ed25519._mul(a, ed25519._G))
    r = int.from_bytes(hashlib.sha512(h[32:] + msg).digest(), "little") % ed25519.L
    R = enc(ed25519._mul(r, ed25519._G))
    k = int.from_bytes(hashlib.sha512(R + A + msg).digest(), "little") % ed25519.L
    return A, R + int.to_bytes((r + k * a) % ed25519.L, 32, "little")


PUB, _ = _sign(b"")
KEY = {"key_id": "k:0123456789abcdef", "alg": "ed25519", "owner": {"type": "band", "id": 7},
       "public_key": base64.b64encode(PUB).decode(), "created_at": "2026-10-08", "revoked_at": None}
SID = "rs:" + "5" * 32


@pytest.fixture
def keys(monkeypatch):
    st = {"keys": [dict(KEY)], "calls": 0}

    def req(path, token=None, **kw):
        st["calls"] += 1
        assert path == "/api/ext/keys"
        return 200, {"version": 1, "keys": [dict(k) for k in st["keys"]]}
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(M, "_req", req)
    SIG._verdicts.clear()
    return st


def _original(path, signer=None, tamper=None):
    """Un original tel que golem.fm l'assemble et le signe : golem.json écrit, puis signé à l'octet."""
    G.write(path, {"type": "song", "id": SID, "title": "Our Song", "kind": "original"},
            {"audio/original.flac": b"fLaC" + b"\1" * 300, "lyrics/song.lrc": b"[00:01.00]la"})
    with zipfile.ZipFile(path) as zf:
        raw = zf.read(G.MANIFEST)
    _, sig = _sign(raw)
    doc = {"v": 1, "alg": "ed25519", "key_id": KEY["key_id"], "signer": signer or {"type": "band", "id": 7, "name": "The Band"},
           "signed_at": "2026-10-08T22:00:00", "sig": base64.b64encode(sig).decode()}
    G.replace(path, None, {SIG.SIG_MEMBER: json.dumps(doc).encode()})
    if tamper:
        tamper(path)
    return path


def test_un_original_signe_est_verifie(tmp_path, keys):
    v = SIG.check(_original(str(tmp_path / "o.golem")))
    assert v["signed"] and v["valid"] is True and v["signer"]["name"] == "The Band"


def test_un_fichier_non_signe_n_a_pas_de_verdict(tmp_path, keys):
    p = str(tmp_path / "c.golem")
    G.write(p, {"type": "song", "id": SID, "title": "A cover"}, {"lyrics/song.lrc": b"x"})
    assert SIG.check(p) is None


def test_un_octet_du_manifeste_change_casse_la_signature(tmp_path, keys):
    p = _original(str(tmp_path / "o.golem"), tamper=lambda p: G.rewrite_manifest(p, lambda m: m.update(title="Their Song")))
    v = SIG.check(p)
    assert v["valid"] is False and "does not match" in v["reason"]


def test_un_fichier_du_groupe_remplace_casse_la_signature(tmp_path, keys):
    def swap(p):                                     # le manifeste signé garde l'ancienne empreinte : l'audio a changé
        with zipfile.ZipFile(p) as zf:
            items = {n: zf.read(n) for n in zf.namelist()}
        items["audio/original.flac"] = b"fLaC" + b"\2" * 300
        with zipfile.ZipFile(p, "w") as zf:
            for n, b in items.items():
                zf.writestr(n, b)
    v = SIG.check(_original(str(tmp_path / "o.golem"), tamper=swap))
    assert v["valid"] is False and v["altered"] == ["audio/original.flac"]


def test_une_cle_revoquee_ou_un_signataire_usurpe(tmp_path, keys):
    keys["keys"][0]["revoked_at"] = "2026-10-09T10:00:00"
    v = SIG.check(_original(str(tmp_path / "r.golem")))
    assert v["valid"] is False and v.get("revoked")
    keys["keys"][0]["revoked_at"] = None
    SIG.refresh_keys()
    v = SIG.check(_original(str(tmp_path / "u.golem"), signer={"type": "band", "id": 8, "name": "Someone else"}))
    assert v["valid"] is False and "owner" in v["reason"]


def test_une_cle_inconnue_relit_la_liste_une_fois(tmp_path, keys):
    SIG.refresh_keys()
    keys["keys"] = []                                # la liste gardée connaît la clé ; on simule une rotation
    os.unlink(SIG._keys_path())
    keys["calls"] = 0
    v = SIG.check(_original(str(tmp_path / "o.golem")))
    assert keys["calls"] == 1 and v["valid"] is False and v["reason"] == "unknown key"


def test_jamais_connecte_on_ne_conclut_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "_cfg", lambda: (None, None))
    SIG._verdicts.clear()
    v = SIG.check(_original(str(tmp_path / "o.golem")))
    assert v["signed"] and v["valid"] is None


def test_installe_sur_le_golem_la_signature_reste_verifiable(tmp_path, keys):
    """Le PIÈGE : le rack réécrit golem.json (repertoire, puis la fiche). Il garde les octets signés à part."""
    S.install_golem(_original(str(tmp_path / "o.golem")))
    path = S._path(SID)
    assert G.read_member(path, G.MANIFEST) != G.read_member(path, SIG.SIGNED_MANIFEST)   # réécrit, bien sûr
    assert SIG.check(path)["valid"] is True
    S.update(SID, bpm=120)                           # la fiche est la couche du propriétaire
    assert SIG.check(S._path(SID))["valid"] is True
    items = {i["key"]: i for i in S.files_summary(SID)["items"]}
    assert items["signature"]["state"] == "ok" and "The Band" in items["signature"]["info"]
    assert S.files_summary(SID)["state"] == "complete"


def test_une_signature_recopiee_sur_un_autre_fichier_ne_vaut_rien(tmp_path, keys):
    """La copie des octets signés (signatures/golem.json) ne doit pas se prêter à un autre contenu."""
    good = _original(str(tmp_path / "o.golem"))
    with zipfile.ZipFile(good) as zf:
        raw, sigdoc = zf.read(G.MANIFEST), zf.read(SIG.SIG_MEMBER)
    fake = str(tmp_path / "fake.golem")
    G.write(fake, {"type": "song", "id": SID, "title": "Not their song", "kind": "original"},
            {"audio/other.flac": b"fLaC" + b"\3" * 300})
    G.replace(fake, None, {SIG.SIG_MEMBER: sigdoc, SIG.SIGNED_MANIFEST: raw})
    v = SIG.check(fake)
    assert v["valid"] is False and "golem.json:title" in v["altered"] and "audio/other.flac" in v["altered"]
