# SPDX-License-Identifier: GPL-3.0-or-later
"""Le pédalier sourd qui se croit branché (2026-10-01).

La carte son a été ré-énumérée (prêtée à une VM, puis rendue) : l'audio s'est réparé tout seul,
l'écran disait `midi ok`, et plus un switch n'arrivait. aseqdump avait écrit « Port unsubscribed »
et restait vivant, abonné à rien ; la sortie MIDI, sur la même carte, parlait à un client mort
sans lever d'erreur. La ligne tombait dans `_handle`, qui l'ignorait."""
from bridge import foot, midi_out


class _Proc:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.terminated = False

    def terminate(self):
        self.terminated = True


def _run(monkeypatch, transport):
    spawned, resets = [], []
    reader = foot.FootReader(lambda *_: None, lambda *_: None)
    reader._retry = 0
    handled = []
    reader._handle = handled.append
    monkeypatch.setattr(reader, "_find_port", lambda: "20:0")
    monkeypatch.setattr(foot.shutil, "which", lambda _name: None)          # pas de stdbuf
    monkeypatch.setitem(foot._DEVICE, "transport", transport)
    monkeypatch.setattr(midi_out, "reset_ports", lambda: resets.append(1))

    def popen(cmd, **_kw):
        if spawned:                                    # 2e lancement = la reconnexion : on s'arrête là
            reader._stop = True
            proc = _Proc([])
        else:
            proc = _Proc(["Waiting for data. Press Ctrl+C to end.\n",
                          "  0:0   Control change          0, controller 20, value 127\n",
                          "  0:1   Port unsubscribed          20:0 -> 131:0\n",
                          "  0:0   Control change          0, controller 21, value 127\n"])
        spawned.append(proc)
        return proc

    monkeypatch.setattr(foot.subprocess, "Popen", popen)
    reader._supervise()
    return spawned, resets, handled


def test_un_port_disparu_relance_aseqdump_au_lieu_de_le_laisser_tourner_a_vide(monkeypatch):
    spawned, resets, handled = _run(monkeypatch, {"kind": "din-soundcard"})
    assert len(spawned) == 2                           # il a été RELANCÉ
    assert spawned[0].terminated                       # et l'ancien ne traîne pas
    assert len(handled) == 1 and "controller 20" in handled[0]   # rien n'est lu après la perte
    assert resets == [1]                               # DIN : la sortie MIDI de la même carte est oubliée


def test_un_pedalier_usb_ne_touche_pas_a_la_sortie_de_la_carte(monkeypatch):
    spawned, resets, _ = _run(monkeypatch, {"kind": "usb", "port_match": "MC6"})
    assert len(spawned) == 2 and spawned[0].terminated
    assert resets == []
