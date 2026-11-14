# SPDX-License-Identifier: GPL-3.0-or-later
"""« Play it » depuis la Library (bridge/try_sound.py, docs/library-play.md) : le son brut sous les doigts, avec
l'instrument branché ; sans lui, on le dit."""
import pytest

from bridge import try_sound as T


@pytest.fixture
def rack(monkeypatch):
    from bridge import inputmap, devices
    from bridge.state import state
    imap = {"inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar"}]}
    monkeypatch.setattr(state, "inputmap", imap, raising=False)
    monkeypatch.setattr(inputmap, "current", lambda: imap)
    devs = [{"name": "MPK", "roles": ["keys", "pads"], "connected": True}, {"name": "Nitro", "roles": ["drums"], "connected": False}]
    monkeypatch.setattr(devices, "listing", lambda: devs)
    return imap, devs


def test_each_role_finds_its_instrument_or_says_why(rack):
    imap, devs = rack
    assert T.device("guitar") == {"ok": True, "name": "your guitar on input 2", "why": None}
    assert T.device("bass")["name"] == "your guitar on input 2"           # pas d'entrée basse : la guitare
    assert T.device("keys")["name"] == "MPK"
    assert T.device("drums")["name"] == "MPK"                              # la Nitro débranchée : les pads du MPK
    devs[0]["connected"] = False
    d = T.device("drums")
    assert not d["ok"] and "Plug one" in d["why"]
    imap["inputs"] = [{"ch": "1", "role": "voice"}]
    assert not T.device("guitar")["ok"]


def test_a_sound_resolves_to_its_block_and_role(rack, monkeypatch):
    from bridge import kits
    monkeypatch.setattr(kits, "get_kit", lambda k: {"id": k, "role": "drum" if k.startswith("drums") else "pad", "name": "K"})
    role, blk, _ = T.resolve({"kit": "drums-x"})
    assert (role, blk["type"], blk["params"]) == ("drums", "drumkit", {"kit": "drums-x"})
    assert T.resolve({"kit": "pads-x"})[1]["type"] == "pads"
    role, blk, name = T.resolve({"sound": "organ:b3"})
    assert (role, blk["type"], blk["id"]) == ("keys", "organ", T.BLOCK_ID)
    with pytest.raises(T.TryError):
        T.resolve({})


def test_the_try_patch_holds_only_the_sound_on_one_lane():
    doc = T.patch_doc("keys", {"id": "sound", "type": "ep", "params": {"patch": 3}}, "E.PIANO 1")
    L = doc["lanes"][0]
    assert L["midi"] and L["chain"]["chain"] == [{"id": "sound", "type": "ep", "params": {"patch": 3}}]
    assert [s["id"] for s in doc["scenes"]] == ["A"]
    g = T.patch_doc("guitar", {"id": "sound", "type": "amp"}, "X")["lanes"][0]
    assert "midi" not in g


def test_the_try_is_refused_without_its_instrument(rack, monkeypatch):
    imap, devs = rack
    monkeypatch.setattr(T, "resolve", lambda item: ("guitar", {"id": "sound", "type": "amp", "params": {}}, "Amp"))
    imap["inputs"] = []
    with pytest.raises(T.TryError, match="no guitar input"):
        T.build({"capture": "x"})
