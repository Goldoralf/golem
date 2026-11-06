# SPDX-License-Identifier: GPL-3.0-or-later
"""Un FAUX système de fichiers pour provision/uninstall.py (docs/uninstall.md) : une machine où golem est installé,
dans un dossier temporaire. Le moteur y travaille en mode --root-fs : rien de système ne s'exécute."""
import json
import os

from provision import uninstall as U

HOME = "/home/u"
INSTALL = HOME + "/golem"

INI = """[audioconfig]
x=1
[reaper]
automute=0
midiins=4
csurf_0=HUI "Mackie" 0 0
csurf_1=OSC "OSC GoleM" 7 8000 "127.0.0.1" 9000 1024 10 "golem"
csurf_2=OSC "Other" 3 9100 "" 9101 1024 10 "other"
csurf_cnt=3
[other]
automute=5
"""

DPKG = "".join("Package: %s\nStatus: install ok installed\n\n" % p for p in
               ("pipewire", "git", "guitarix-lv2", "ffmpeg", "surge-xt", "x42-plugins", "jq"))


class FakeFS:
    def __init__(self, base):
        self.base = str(base)
        os.makedirs(self.base, exist_ok=True)

    def p(self, logical):
        return self.base + logical

    def file(self, logical, content="x"):
        path = self.p(logical)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def __new__(cls, *a, **kw):
        if os.name != "posix":
            # Le moteur de désinstallation LINUX (chemins POSIX, liens, sudo, apt) : joué sur un Windows où les
            # liens sont permis (runner admin), il échouait sur la forme des chemins. Windows a son propre
            # moteur et ses tests : tests/test_uninstall_win.py (constaté sur windows-2025, 2026-10-19).
            import pytest
            pytest.skip("the Linux uninstall engine; Windows is covered by test_uninstall_win.py")
        return super().__new__(cls)

    def link(self, logical, target_logical):
        path = self.p(logical)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            os.symlink(self.p(target_logical), path)
        except OSError as e:
            if getattr(e, "winerror", None) == 1314:          # Windows sans mode développeur ni droits admin
                import pytest
                pytest.skip("symlinks need Developer Mode or an elevated shell on Windows")
            raise
        return path

    def exists(self, logical):
        return os.path.lexists(self.p(logical))

    def read(self, logical):
        with open(self.p(logical)) as f:
            return f.read()

    def ctx(self, **kw):
        return U.Ctx(fsroot=self.base, home=HOME, user="u", **kw)

    def receipt(self, data):
        self.file(HOME + "/.local/share/golem/install-receipt.json", json.dumps(data))

    def snapshot(self):
        out = {}
        for r, ds, fs in os.walk(self.base):
            for n in ds + fs:
                full = os.path.join(r, n)
                st = os.lstat(full)
                out[full] = (st.st_mode, st.st_size, os.readlink(full) if os.path.islink(full) else None)
        return out


def machine(base):
    """Une machine où golem est installé (sans reçu)."""
    fs = FakeFS(base)
    fs.file(INSTALL + "/provision/golem", "#!/bin/sh\n")
    fs.file(INSTALL + "/provision/stop.sh", "#!/bin/sh\n")
    fs.file(INSTALL + "/bridge/app.py")
    for d in ("Scripts", "Effects", "FXChains", "OSC"):
        fs.file(INSTALL + "/reaper/%s/keep" % d)
    fs.link(HOME + "/.local/bin/golem", INSTALL + "/provision/golem")
    fs.file(HOME + "/.local/share/applications/golem.desktop")
    fs.file(HOME + "/.local/share/icons/hicolor/180x180/apps/golem.png")
    fs.file(HOME + "/.local/share/golem/browser/Default/prefs")
    fs.file(HOME + "/.cache/golem-build/x/y")
    fs.file(HOME + "/.config/systemd/user/golem-server.service")
    r = HOME + "/.config/REAPER"
    fs.link(r + "/Scripts/golem", INSTALL + "/reaper/Scripts")
    fs.link(r + "/Effects/golem", INSTALL + "/reaper/Effects")
    fs.link(r + "/FXChains", INSTALL + "/reaper/FXChains")
    fs.link(r + "/Scripts/__startup.lua", INSTALL + "/reaper/Scripts/__startup.lua")
    fs.link(r + "/OSC/golem.ReaperOSC", INSTALL + "/reaper/OSC/golem.ReaperOSC")
    fs.file("/elsewhere/mine.ReaperOSC")
    fs.link(r + "/OSC/mine.ReaperOSC", "/elsewhere/mine.ReaperOSC")
    fs.file(r + "/reaper.ini", INI)
    fs.file(r + "/reaper-license.rk", "LICENCE")
    fs.file("/etc/sudoers.d/golem-net")
    fs.file("/etc/sudoers.d/someone-else")
    fs.file("/usr/local/sbin/golem-net")
    fs.file("/etc/systemd/system/golem-net.service")
    fs.file("/etc/security/limits.d/95-golem-audio.conf")
    fs.file("/etc/sysctl.d/90-golem-port80.conf")
    fs.file("/etc/group", "root:x:0:\naudio:x:29:u,pulse\n")
    fs.file("/var/lib/dpkg/status", DPKG)
    fs.file(HOME + "/.lv2/neural_amp_modeler.lv2/manifest.ttl")
    fs.file(HOME + "/.vst3/GoleM Freeze.vst3/Contents/x")
    fs.file(HOME + "/.cargo/bin/cargo")
    fs.file(HOME + "/opt/REAPER/reaper")
    return fs


def receipt_data(**over):
    d = {
        "format": 1, "root": "~/golem", "release": "v2.9.0",
        "items": [
            {"id": "file:/etc/sudoers.d/golem-net", "kind": "file", "path": "/etc/sudoers.d/golem-net",
             "owner": "root", "by": "provision/setup-net-sudo.sh", "group": "system", "prior": None},
            {"id": "link:~/.config/REAPER/Scripts/__startup.lua", "kind": "link",
             "path": "~/.config/REAPER/Scripts/__startup.lua", "owner": "user", "by": "provision/link-reaper.sh",
             "group": "reaper", "prior": {"moved_to": "~/.config/REAPER/Scripts/__startup.lua.golem-orig"}},
            {"id": "dir:~/.lv2/neural_amp_modeler.lv2", "kind": "dir", "path": "~/.lv2/neural_amp_modeler.lv2",
             "owner": "user", "by": "provision/install-nam.sh", "group": "plugins", "prior": None},
            {"id": "file:/etc/gone.conf", "kind": "file", "path": "/etc/golem-gone/gone.conf", "owner": "root",
             "by": "x", "group": "system", "prior": None},
        ],
        "apt": {"added": ["pipewire", "git", "guitarix-lv2", "ffmpeg", "x42-plugins", "not-installed-anymore"],
                "debs": ["surge-xt"]},
        "prior": {
            "audio_group": False,
            "reaper": {"installed_by_golem": True, "path": "~/opt/REAPER", "version": "7.79"},
            "reaper_ini": {"csurf_added": True, "keys": {"automute": "1", "midiins": None}},
            "linger": False,
            "toolchain": {"rust_installed_by_golem": True},
        },
    }
    d.update(over)
    return d
