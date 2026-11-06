#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Sert UN fichier (l'ISO d'installation) en HTTP sur 127.0.0.1, avec les requêtes Range — ce que le
# pilote « curl » de QEMU exige pour lire un DVD réseau. Utilisé par win.sh (GOLEM_VM_ISO_HTTP=1) :
# l'ISO de 8 Go reste où elle est (un disque externe que libvirt ne peut pas lire) au lieu d'être
# copiée dans le pool, sur un / trop juste.
#
#   iso-http.py <fichier> <fichier-port>   # écrit le port choisi dans <fichier-port>, puis sert
import http.server
import os
import re
import shutil
import sys

PATH = os.path.abspath(sys.argv[1])
NAME = "/" + os.path.basename(PATH)
SIZE = os.path.getsize(PATH)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # QEMU lit par petits blocs : un journal par requête noierait tout
        pass

    def _head(self, send_body):
        if self.path.split("?")[0] != NAME:
            self.send_error(404)
            return
        start, end = 0, SIZE - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), SIZE - 1)
            else:  # « bytes=-N » : les N derniers octets
                start = max(0, SIZE - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{SIZE}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{SIZE}")
        else:
            self.send_response(200)
        length = end - start + 1
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if send_body:
            with open(PATH, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

    def do_HEAD(self):
        self._head(False)

    def do_GET(self):
        try:
            self._head(True)
        except (BrokenPipeError, ConnectionResetError):
            pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(sys.argv[2] + ".tmp", "w") as f:
    f.write(str(srv.server_address[1]))
shutil.move(sys.argv[2] + ".tmp", sys.argv[2])
srv.serve_forever()
