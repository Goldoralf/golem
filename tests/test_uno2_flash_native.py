# SPDX-License-Identifier: GPL-3.0-or-later
"""Flash UnO2 sous Windows (2026-10-03) : le dialogue de tools/fcb/flash_uno2.py, mais DANS le bridge — sous
WinMM une prise MIDI n'a qu'un propriétaire, et c'est le bridge. Une fausse puce répond par le lecteur du pied."""
import queue

from bridge import foot, midi_out, routes_system as R

IDENT_UNO2 = [0xF0, 0x7E, 0x7E, 0x38, 8, 0x13, 0, 42, 0xF7]
ACK = lambda code: [0xF0, 0x7E, 0x7E, code, 0xF7]


class FakeChip:
    """Répond aux SysEx envoyés comme la puce : écho THRU d'abord (on doit l'ignorer), puis la réponse."""
    def __init__(self, ident=IDENT_UNO2, confirm=True):
        self.q, self.sent, self.closed = queue.SimpleQueue(), [], False
        self.ident, self.confirm = ident, confirm

    def send(self, data):
        b = list(data)
        self.sent.append(b)
        self.q.put_nowait((b, 0.0))                        # l'écho THRU de nos propres octets
        if b == [0xF0, 0x7E, 0x7E, 0x30, 0xF7]:
            if self.ident:
                self.q.put_nowait((self.ident, 0.0))
        elif b[:4] == [0xF0, 0x7E, 0x7E, 0x51] and self.confirm:
            self.q.put_nowait((ACK(0x7C), 0.0))
            self.q.put_nowait((ACK(0x7C), 0.0))
            self.q.put_nowait((ACK(0x7F), 0.0))
        return True

    def get_message(self):
        try:
            return self.q.get_nowait()
        except queue.Empty:
            return None

    def close_port(self):
        self.closed = True


def _wire(monkeypatch, fake, remembered):
    import sys, os
    sys.path.insert(0, os.path.join(R.C.ROOT, "tools", "fcb"))
    import flash_uno2 as F
    monkeypatch.setattr(foot, "native_sysex_stream", lambda timeout=4: fake)
    monkeypatch.setattr(midi_out, "send_sysex", fake.send)
    monkeypatch.setattr(midi_out, "held", lambda: False)
    monkeypatch.setattr(midi_out, "find_port", lambda: "Volt 276")
    monkeypatch.setattr(F, "_remember_flash", lambda syx, loops, claims: remembered.append(len(syx)))
    monkeypatch.setattr(F, "TIMEOUT_IDENTIFY", 0.3)
    monkeypatch.setattr(F, "TIMEOUT_FLASH", 0.5)
    return F


def test_le_flash_windows_identifie_ecrit_et_retient(monkeypatch):
    fake, remembered = FakeChip(), []
    _wire(monkeypatch, fake, remembered)
    ok, log, status = R._flash_uno2_native("fcb1010-uno2")
    assert ok and status == 200, log
    assert fake.sent[0] == [0xF0, 0x7E, 0x7E, 0x30, 0xF7]             # l'identification d'abord, toujours
    assert fake.sent[1][:4] == [0xF0, 0x7E, 0x7E, 0x51]                # puis le dump
    assert remembered == [len(fake.sent[1])] and fake.closed           # mémoire du flash, abonnement rendu


def test_on_n_ecrit_pas_dans_une_puce_qui_n_est_pas_une_uno2(monkeypatch):
    fake, remembered = FakeChip(ident=[0xF0, 0x7E, 0x7E, 0x38, 0, 0x10, 0, 1, 0xF7]), []   # une TinyBox
    _wire(monkeypatch, fake, remembered)
    ok, log, status = R._flash_uno2_native("fcb1010-uno2")
    assert not ok and status == 409 and len(fake.sent) == 1 and not remembered


def test_un_pedalier_muet_ou_debranche_le_dit(monkeypatch):
    fake, remembered = FakeChip(ident=None), []
    _wire(monkeypatch, fake, remembered)
    ok, log, status = R._flash_uno2_native("fcb1010-uno2")
    assert not ok and status == 502 and not remembered
    assert "REVENUE" in log.upper()                                   # l'écho THRU sans réponse est NOMMÉ
    monkeypatch.setattr(foot, "native_sysex_stream", lambda timeout=4: None)
    ok, log, status = R._flash_uno2_native("fcb1010-uno2")
    assert not ok and status == 409 and "Soundcard" in log


def test_une_puce_qui_ne_confirme_pas_n_est_pas_retenue(monkeypatch):
    fake, remembered = FakeChip(confirm=False), []
    _wire(monkeypatch, fake, remembered)
    ok, log, status = R._flash_uno2_native("fcb1010-uno2")
    assert not ok and status == 502 and not remembered
