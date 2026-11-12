# SPDX-License-Identifier: GPL-3.0-or-later
"""Un faux Golem Engine pour tester bridge/engine/ardour.py sans Ardour (docs/ardour-plan.md §2) — ce que
tests/fakereaper.lua est pour REAPER :
  - FakeSurface : la surface OSC d'Ardour (UDP local) — enregistre ce qu'elle reçoit, renvoie du retour au bridge ;
  - FakeWatcher : le veilleur Lua (golem/engine/golem_watch.lua) — lit le slot de commandes, accuse {seq, t},
    garde ce qu'il a exécuté. Même règle que le vrai : une commande déjà présente au démarrage est accusée, pas jouée.
"""
import json
import os
import socket
import threading
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeSurface:
    def __init__(self):
        self.got = []
        self._cv = threading.Condition()
        disp = Dispatcher()
        disp.set_default_handler(self._recv)
        self.server = ThreadingOSCUDPServer(("127.0.0.1", 0), disp)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _recv(self, address, *args):
        with self._cv:
            self.got.append((address, *args))
            self._cv.notify_all()

    def wait(self, n, timeout=2.0):
        """Attend au moins n messages ; rend la liste reçue."""
        end = time.time() + timeout
        with self._cv:
            while len(self.got) < n and time.time() < end:
                self._cv.wait(0.05)
            return list(self.got)

    def feedback(self, port, address, *args):
        """La surface renvoie son retour au port d'écoute du bridge."""
        SimpleUDPClient("127.0.0.1", port).send_message(address, list(args))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeWatcher:
    def __init__(self, cmd_file, ack_file, tick=0.02):
        self.cmd_file, self.ack_file, self.tick = cmd_file, ack_file, tick
        self.ran = []
        self._stop = threading.Event()
        self.last = self._read_seq()
        if self.last:
            self._ack(self.last)                 # posée avant le démarrage : accusée, jamais exécutée
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _read(self):
        try:
            with open(self.cmd_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _read_seq(self):
        c = self._read()
        return (c or {}).get("seq") or 0

    def _ack(self, seq):
        tmp = self.ack_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"seq": seq, "t": time.monotonic()}, f)
        os.replace(tmp, self.ack_file)

    def _loop(self):
        while not self._stop.is_set():
            c = self._read()
            if c and c.get("seq") and c["seq"] != self.last:
                self.last = c["seq"]
                self._ack(self.last)
                self.ran.append(c)
            time.sleep(self.tick)

    def wait_ran(self, n, timeout=2.0):
        end = time.time() + timeout
        while len(self.ran) < n and time.time() < end:
            time.sleep(0.01)
        return list(self.ran)

    def stop(self):
        self._stop.set()
        self._t.join(1)
