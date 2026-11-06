# SPDX-License-Identifier: GPL-3.0-or-later
"""Le JUGE de la désinstallation en VM (docs/uninstall.md §7, tools/uninstall-judge.py) sur des relevés fabriqués :
montées de version (a), gardé exprès ou par choix (b), vraies traces (c) -> code 1."""
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def J():
    spec = importlib.util.spec_from_file_location("golem_uninstall_judge", os.path.join(ROOT, "tools", "uninstall-judge.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fp(path, packages, versions, files, extra=""):
    path.write_text("\n## packages\n%s\n\n## versions\n%s\n\n## files\n%s\n%s" % (
        "\n".join(packages), "\n".join(versions), "\n".join(files), extra))
    return str(path)


H = "/home/golem"
BEFORE_FILES = ["d /etc", "f /etc/hosts", "d %s" % H, "f %s/.bashrc" % H]


@pytest.fixture
def case(tmp_path):
    before = _fp(tmp_path / "before.txt", ["libc6", "pipewire", "bash"],
                 ["libc6 2.39-0ubuntu8", "pipewire 1.0.5", "bash 5.2"], BEFORE_FILES)
    after = _fp(tmp_path / "after.txt",
                ["libc6", "pipewire", "bash", "pipewire-jack", "ffmpeg", "libav", "gcc-13", "stray-dep", "mystery"],
                ["libc6 2.39-0ubuntu8.4", "pipewire 1.0.5", "bash 5.2", "pipewire-jack 1.0.5", "ffmpeg 6",
                 "libav 6", "gcc-13 13", "stray-dep 1", "mystery 1"],
                BEFORE_FILES + ["f /etc/pipewire/jack.conf", "f /etc/ffmpeg.conf", "d %s/opt/REAPER" % H,
                                "f %s/opt/REAPER/reaper" % H, "f %s/.local/bin/golem" % H, "f /etc/golem-orphan.conf",
                                "d %s/golem-backup-2026-10-15" % H])
    plan = {"items": [{"id": "apt:ffmpeg", "group": "apt", "label": "ffmpeg", "default": False, "paths": []},
                      {"id": "reaper:app", "group": "reaper", "default": False, "paths": ["~/opt/REAPER"]},
                      {"id": "golem:command", "group": "golem", "default": True, "paths": ["~/.local/bin/golem"]}],
            "apt_deps": ["libav", "gcc-13", "stray-dep"]}
    owners = "pipewire-jack:amd64: /etc/pipewire/jack.conf\nffmpeg: /etc/ffmpeg.conf\n"
    auto = "NOTE: This is only a simulation!\nPurg stray-dep [1]\n"
    return before, after, plan, owners, auto


def test_trois_classes(J, case):
    before, after, plan, owners, auto = case
    res = J.judge(before, after, plan, J.parse_owners(owners), J.parse_sim(auto), H)
    up = [r[0] for r in res["upgraded"]]
    kept = {r[0]: r[1] for r in res["kept"]}
    left = {r[0]: r[1] for r in res["leftovers"]}
    assert up == ["~ libc6 2.39-0ubuntu8 -> 2.39-0ubuntu8.4"]                     # (a) montée de version
    assert "base" in kept["> [packages] pipewire-jack"]                           # NEVER_APT
    assert "offered" in kept["> [packages] ffmpeg"]                               # proposé, gardé
    assert "still needed" in kept["> [packages] libav"] and "> [packages] gcc-13" in kept
    assert "pipewire-jack" in kept["> [files] f /etc/pipewire/jack.conf"]         # fichier d'un paquet de base
    assert "ffmpeg" in kept["> [files] f /etc/ffmpeg.conf"]
    assert "reaper:app" in kept["> [files] f %s/opt/REAPER/reaper" % H]           # REAPER décoché par défaut
    assert "> [files] d %s/golem-backup-2026-10-15" % H in kept
    # (c) : une dépendance qu'apt retirerait encore, un paquet inconnu, un fichier orphelin, un élément golem coché
    assert "autoremove" in left["> [packages] stray-dep"]
    assert "> [packages] mystery" in left and "> [files] f /etc/golem-orphan.conf" in left
    assert "golem:command" in left["> [files] f %s/.local/bin/golem" % H]
    assert not [r for r in res["leftovers"] if "libc6" in r[0]]                    # une montée n'est jamais une trace


def test_ce_qui_disparait_est_une_trace(J, tmp_path):
    b = _fp(tmp_path / "b.txt", ["bash", "old-tool"], ["bash 5", "old-tool 1"], BEFORE_FILES)
    a = _fp(tmp_path / "a.txt", ["bash"], ["bash 5"], BEFORE_FILES[:-1])
    res = J.judge(b, a)
    assert {r[0] for r in res["leftovers"]} == {"< [packages] old-tool", "< [files] f %s/.bashrc" % H}


def test_ligne_de_commande_ecrit_chaque_classe_et_rend_son_code(J, case, tmp_path, capsys):
    before, after, plan, owners, auto = case
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "owners.txt").write_text(owners)
    (tmp_path / "auto.txt").write_text(auto)
    out = tmp_path / "out"
    rc = J.main(["judge", before, after, "--out", str(out), "--plan", str(tmp_path / "plan.json"),
                 "--owners", str(tmp_path / "owners.txt"), "--autoremove", str(tmp_path / "auto.txt"), "--home", H])
    assert rc == 1
    for cls in ("upgraded", "kept", "leftovers"):
        assert (out / (cls + ".txt")).is_file()
    assert "stray-dep" in (out / "leftovers.txt").read_text()
    txt = capsys.readouterr().out
    assert "(a) upgraded" in txt and "(c) REAL leftovers: 4" in txt
    # propre : code 0
    rc = J.main(["judge", before, before, "--out", str(out)])
    assert rc == 0
    # chemins apparus, pour dpkg -S
    assert "/etc/golem-orphan.conf" in J.new_paths(before, after)
    # un relevé à l'ancien format (sans « versions ») : incomparable, code 2
    old = tmp_path / "old.txt"
    old.write_text("\n## packages\nbash 5\n")
    assert J.main(["judge", str(old), after, "--out", str(out)]) == 2


# ── 3e cycle en VM (2026-10-16) : les faux positifs, et ce qui reste une vraie trace ─────────────────────────
def test_regles_du_troisieme_cycle(J, tmp_path):
    base = ["libc6", "sudo", "pipewire"]
    before = _fp(tmp_path / "b.txt", base, ["%s 1" % p for p in base],
                 BEFORE_FILES + ["d /etc/sudoers.d", "d /etc/security/limits.d", "d /etc/systemd/user"],
                 "\n## units\nsystem ssh.service enabled\n")
    pk = base + ["ppp", "gcr4", "javascript-common", "lighttpd-gone (config-files)"]
    files = BEFORE_FILES + [
        "d /etc/sudoers.d", "d /etc/security/limits.d", "d /etc/systemd/user",
        # REAPER gardé (reaper:app, reaper:config décochés) ; reaper.ini « revert » : le fichier reste
        "d %s/opt" % H, "d %s/opt/REAPER" % H, "f %s/opt/REAPER/reaper" % H,
        "d %s/.config" % H, "d %s/.config/REAPER" % H, "f %s/.config/REAPER/reaper.ini" % H,
        "l %s/.config/REAPER/Scripts" % H,                                        # sous un gardé, mais DOIT partir
        # dossiers XDG vides, caches du bureau d'une entrée gardée, dossier vide quelconque
        "d %s/.local" % H, "d %s/.local/bin" % H, "d %s/.local/share" % H, "d %s/.local/share/applications" % H,
        "f %s/.local/share/applications/cockos-reaper.desktop" % H,
        "f %s/.local/share/applications/mimeinfo.cache" % H,
        "d %s/.local/share/mime" % H, "f %s/.local/share/mime/mime.cache" % H, "d %s/.stray" % H,
        # /etc : un fichier écrit dans un dossier de ppp, un lien vers un fichier d'un paquet gardé, le postinst
        # de jackd2 (purgé ici), une règle sudo de golem (le dossier est à sudo : ça ne la garde pas)
        "d /etc/ppp", "d /etc/ppp/peers", "f /etc/ppp/peers/provider",
        "d /etc/lighttpd", "d /etc/lighttpd/conf-enabled", "l /etc/lighttpd/conf-enabled/90-javascript-alias.conf",
        "f /etc/security/limits.d/audio.conf.disabled", "f /etc/sudoers.d/golem-net",
        "d /etc/systemd/user/sockets.target.wants", "l /etc/systemd/user/sockets.target.wants/gcr-ssh-agent.socket",
        "f /etc/old-lighttpd.conf", "d /etc/lighttpd-gone", "f /etc/lighttpd-gone/x.conf"]
    after = _fp(tmp_path / "a.txt", pk, ["%s 1" % p.split()[0] for p in pk], files,
                "\n## units\nsystem ssh.service enabled\nuser gcr-ssh-agent.socket enabled\nuser golem-x.service enabled\n"
                "system mystery.service enabled\n")
    plan = {"items": [
        {"id": "reaper:app", "group": "reaper", "default": False, "action": "remove", "paths": ["~/opt/REAPER",
         "~/.local/share/applications/cockos-reaper.desktop"]},
        {"id": "reaper:config", "group": "reaper", "default": False, "action": "remove", "paths": ["~/.config/REAPER"]},
        {"id": "reaper-ini:revert", "group": "reaper-ini", "default": True, "action": "revert",
         "paths": ["~/.config/REAPER/reaper.ini"]},
        {"id": "reaper-links:Scripts", "group": "reaper-links", "default": True, "action": "remove",
         "paths": ["~/.config/REAPER/Scripts"]}],
        "apt_deps": ["ppp", "gcr4", "javascript-common", "jackd2", "lighttpd-gone"]}
    owners = J.parse_owners("ppp: /etc/ppp\nppp: /etc/ppp/peers\njavascript-common: /etc/lighttpd\n"
                            "javascript-common: /etc/lighttpd/conf-available/90-javascript-alias.conf\n"
                            "sudo: /etc/sudoers.d\ngcr4: /usr/lib/systemd/user/gcr-ssh-agent.socket\n"
                            "lighttpd-gone: /etc/lighttpd-gone\n")
    links = J.parse_links("/etc/lighttpd/conf-enabled/90-javascript-alias.conf\t/etc/lighttpd/conf-available/"
                          "90-javascript-alias.conf\n/etc/systemd/user/sockets.target.wants/gcr-ssh-agent.socket\t"
                          "/usr/lib/systemd/user/gcr-ssh-agent.socket\n")
    res = J.judge(before, after, plan, owners, set(), H, links)
    kept = {r[0]: r[1] for r in res["kept"]}
    left = {r[0]: r[1] for r in res["leftovers"]}
    f = "> [files] "
    for p in ("d %s/opt" % H, "d %s/.config" % H):                                   # parents de ce qui est gardé
        assert "holds only what stays" in kept[f + p], p
    assert "set back in place by reaper-ini:revert" in kept[f + "f %s/.config/REAPER/reaper.ini" % H]
    assert "reaper-links:Scripts" in left[f + "l %s/.config/REAPER/Scripts" % H]       # le plus précis gagne
    assert "XDG" in kept[f + "d %s/.local/bin" % H]
    assert "desktop cache" in kept[f + "f %s/.local/share/applications/mimeinfo.cache" % H]
    assert f + "d %s/.local/share/applications" % H in kept
    assert f + "d %s/.local" % H in left                     # il porte la base MIME orpheline : pas « que du gardé »
    assert "nothing it describes" in left[f + "f %s/.local/share/mime/mime.cache" % H]  # aucune source : trace
    assert f + "d %s/.stray" % H in left
    assert "folder of ppp" in kept[f + "f /etc/ppp/peers/provider"]
    assert "javascript-common" in kept[f + "l /etc/lighttpd/conf-enabled/90-javascript-alias.conf"]
    assert f + "d /etc/lighttpd/conf-enabled" in kept
    assert "jackd2 is no longer installed" in left[f + "f /etc/security/limits.d/audio.conf.disabled"]
    assert "golem" in left[f + "f /etc/sudoers.d/golem-net"]                           # /etc/sudoers.d à sudo : rien
    assert "gcr4" in kept[f + "l /etc/systemd/user/sockets.target.wants/gcr-ssh-agent.socket"]
    assert "lighttpd-gone is no longer installed" in left[f + "f /etc/lighttpd-gone/x.conf"]
    assert f + "f /etc/old-lighttpd.conf" in left
    assert "gcr4" in kept["> [units] user gcr-ssh-agent.socket enabled"]
    assert "> [units] user golem-x.service enabled" in left
    assert "no package ships" in left["> [units] system mystery.service enabled"]
    # /home/golem : le NOM de l'utilisateur ne fait pas d'un dossier une trace de golem
    assert not any("carries golem's name" in w for k, w in left.items() if "/etc/" not in k and "units" not in k)


def test_requetes_pour_la_vm(J, tmp_path):
    b = _fp(tmp_path / "b.txt", ["bash"], ["bash 5"], BEFORE_FILES, "\n## units\n")
    a = _fp(tmp_path / "a.txt", ["bash"], ["bash 5"], BEFORE_FILES + [
        "d /etc/ppp", "d /etc/ppp/peers", "f /etc/ppp/peers/provider", "f /etc/security/limits.d/audio.conf",
        "l /etc/rc0.d/K01alsa-utils", "l %s/.x" % H], "\n## units\nsystem alsa-utils.service masked\nuser p.socket enabled\n")
    q = J.new_paths(b, a)
    assert "/etc/security/limits.d" in q and "/etc/security" in q and "/etc" not in q   # parents sous /etc
    assert "*/systemd/system/alsa-utils.service" in q and "/etc/init.d/alsa-utils" in q
    assert "*/systemd/user/p.socket" in q
    assert J.new_links(b, a) == ["/etc/rc0.d/K01alsa-utils"]                          # sous /etc seulement


# ── WINDOWS (docs/uninstall.md §9.6) : relevés de tools/footprint.ps1, en CRLF ───────────────────────────────────────
WH = "C:\\Users\\golem"
LAD = WH + "\\AppData\\Local"
PF = "C:\\Program Files"


def _wfp(path, keys=(), locations=(), progfiles=(), files=(), firewall=(), shortcuts=(), power="active aaa"):
    secs = [("uninstall-keys", keys), ("versions", [k + " | 1.0" for k in keys]), ("install-locations", locations),
            ("program-files", progfiles), ("files", files), ("firewall", firewall), ("shortcuts", shortcuts),
            ("power", [power])]
    path.write_bytes("".join("\r\n## %s\r\n%s\r\n" % (n, "\r\n".join(v)) for n, v in secs).encode())
    return str(path)


WBASE = dict(keys=["HKLM Microsoft Edge"], files=["d " + LAD, "d " + WH + "\\Documents"],
             firewall=["Core Networking - DNS | True | Outbound | Allow"],
             shortcuts=[WH + "\\Desktop\\Microsoft Edge.lnk"])

WPLAN = {"platform": "windows", "items": [
    {"id": "golem:install-folder", "group": "golem", "default": True, "action": "remove", "paths": [WH + "\\golem"]},
    {"id": "golem:local-data", "group": "golem", "default": True, "action": "remove", "paths": [LAD + "\\GoleM"]},
    {"id": "programs:reaper", "group": "programs", "default": False, "action": "uninstall",
     "paths": [PF + "\\REAPER (x64)"]},
    {"id": "programs:pawpaw", "group": "programs", "default": True, "action": "uninstall",
     "paths": [PF + "\\Common Files\\LV2\\vitalium.lv2"]},
    {"id": "reaper:config", "group": "reaper", "default": False, "action": "remove",
     "paths": [WH + "\\AppData\\Roaming\\REAPER"]},
]}


def test_win_tout_coche_rien_ne_reste(J, tmp_path):
    b = _wfp(tmp_path / "b.txt", **WBASE)
    a = _wfp(tmp_path / "a.txt", keys=WBASE["keys"] + ["HKLM Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.40"],
             files=WBASE["files"] + ["f " + LAD + "\\Microsoft\\Windows\\Explorer\\iconcache_32.db",
                                     "d C:\\ProgramData\\Package Cache", "f C:\\ProgramData\\Package Cache\\vc.exe",
                                     "d " + WH + "\\golem-backup-2026-10-16", "f " + WH + "\\golem-backup-2026-10-16\\README.txt"],
             firewall=WBASE["firewall"], shortcuts=WBASE["shortcuts"])
    res = J.judge_win(b, a, WPLAN, WH)
    assert res["leftovers"] == [] and res["upgraded"] == []
    why = dict(res["kept"])
    assert any("system base" in w for w in why.values())


def test_win_reaper_decoche_garde_ses_fichiers_le_reste_est_une_trace(J, tmp_path):
    b = _wfp(tmp_path / "b.txt", **WBASE)
    a = _wfp(tmp_path / "a.txt", keys=WBASE["keys"] + ["HKLM REAPER (x64)", "HKCU golem"],
             locations=["REAPER (x64) | %s\\REAPER (x64) | %s\\REAPER (x64)" % (PF, PF)],
             progfiles=["d %s\\REAPER (x64)" % PF, "f %s\\REAPER (x64)\\reaper.exe" % PF,
                        "d %s\\Common Files\\LV2\\vitalium.lv2" % PF, "d %s\\NeuralAmpModeler" % PF],
             files=WBASE["files"] + ["d " + LAD + "\\GoleM", "f " + LAD + "\\GoleM\\x", "f " + LAD + "\\stray.txt",
                                     "d " + WH + "\\AppData\\Roaming\\REAPER", "f " + WH + "\\AppData\\Roaming\\REAPER\\reaper.ini"],
             firewall=WBASE["firewall"] + ["reaper.exe | True | Inbound | Block", "GoleM - bridge | True | Inbound | Allow"],
             shortcuts=WBASE["shortcuts"] + [WH + "\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\REAPER (x64)\\REAPER.lnk",
                                             WH + "\\Desktop\\golem.lnk"],
             power="active bbb")
    res = J.judge_win(b, a, WPLAN, WH)
    left = {ln: why for ln, why in res["leftovers"]}
    kept = {ln: why for ln, why in res["kept"]}
    assert "> [uninstall-keys] HKLM REAPER (x64)" in kept                         # proposé, décoché : gardé
    assert "> [program-files] f %s\\REAPER (x64)\\reaper.exe" % PF in kept
    assert "> [files] f %s\\AppData\\Roaming\\REAPER\\reaper.ini" % WH in kept    # reaper:config gardé
    assert "> [firewall] reaper.exe | True | Inbound | Block" in kept
    assert any("REAPER.lnk" in k for k in kept)
    # les traces
    assert "> [uninstall-keys] HKCU golem" in left
    assert "should have gone with golem:local-data" in left["> [files] f %s\\GoleM\\x" % LAD]
    assert "> [files] f %s\\stray.txt" % LAD in left
    assert "> [program-files] d %s\\Common Files\\LV2\\vitalium.lv2" % PF in left                  # PawPaw coché
    assert "> [program-files] d %s\\NeuralAmpModeler" % PF in left
    assert "> [firewall] GoleM - bridge | True | Inbound | Allow" in left
    assert "> [shortcuts] %s\\Desktop\\golem.lnk" % WH in left
    assert "> [power] active bbb" in left and "< [power] active aaa" in left


def test_win_une_regle_d_avant_golem_disparue_est_une_trace(J, tmp_path):
    b = _wfp(tmp_path / "b.txt", **{**WBASE, "firewall": WBASE["firewall"] + ["python.exe | True | Inbound | Block"]})
    a = _wfp(tmp_path / "a.txt", **WBASE)
    res = J.judge_win(b, a, WPLAN, WH)
    assert [ln for ln, _w in res["leftovers"]] == ["< [firewall] python.exe | True | Inbound | Block"]


def test_win_une_regle_du_store_disparue_est_du_bruit_mais_pas_une_regle_au_nom_de_golem(J, tmp_path):
    """2e cycle VM, 2026-10-16 : Windows a mis à jour des applis du Store pendant le test, leurs règles ont changé.
    Le désinstalleur ne touche qu'aux règles de golem ; une règle À NOM de golem qui disparaît (« GoleM sshd », 1er
    cycle) reste un vrai reste."""
    extra = ["Game Bar | True | Inbound | Allow", "GoleM sshd | True | Inbound | Allow"]
    b = _wfp(tmp_path / "b.txt", **{**WBASE, "firewall": WBASE["firewall"] + extra})
    a = _wfp(tmp_path / "a.txt", **WBASE)
    res = J.judge_win(b, a, WPLAN, WH)
    assert [ln for ln, _w in res["leftovers"]] == ["< [firewall] GoleM sshd | True | Inbound | Allow"]
    assert any("Game Bar" in ln for ln, _w in res["kept"])


def test_win_le_bruit_est_explicite(J):
    assert J._wnoise(LAD + "\\Microsoft\\Edge\\User Data\\x", WH)          # l'utilisateur s'appelle golem
    assert J._wnoise("C:\\ProgramData\\Microsoft\\Windows Defender\\Scans\\x")
    assert J._wnoise(LAD + "\\Temp\\golem-install-1.log", WH) is None                  # le nom de golem n'est jamais du bruit


def test_win_ligne_de_commande(J, tmp_path, capsys):
    b = _wfp(tmp_path / "b.txt", **WBASE)
    a = _wfp(tmp_path / "a.txt", **{**WBASE, "shortcuts": WBASE["shortcuts"] + [WH + "\\Desktop\\golem.lnk"]})
    (tmp_path / "plan.json").write_text(json.dumps(WPLAN))
    rc = J.main(["judge", "--win", b, a, "--out", str(tmp_path / "out"), "--plan", str(tmp_path / "plan.json"),
                 "--home", WH])
    assert rc == 1 and "golem.lnk" in (tmp_path / "out" / "leftovers.txt").read_text()


# ── premier cycle en VM Windows (2026-10-16) ─────────────────────────────────────────────────────────
WPLAN2 = {"platform": "windows", "items": WPLAN["items"] + [
    {"id": "system:firewall:GoleM - bridge", "group": "system", "default": True, "action": "remove-rule", "paths": []},
    {"id": "system:firewall:GoleM sshd", "group": "system", "default": False, "action": "remove-rule", "paths": []},
    {"id": "programs:nam_vst3", "group": "programs", "default": True, "action": "uninstall",
     "paths": [PF + "\\Common Files\\VST3\\NeuralAmpModeler.vst3"]},
    {"id": "toolchain:python", "group": "toolchain", "default": False, "action": "uninstall-later",
     "paths": [LAD + "\\Programs\\Python\\Python312"]},
    {"id": "system:common-dirs", "group": "system", "default": True, "action": "remove-empty-dirs",
     "paths": [PF + "\\Common Files\\VST3", PF + "\\Common Files\\LV2"]},
]}


def test_win_le_va_et_vient_de_windows_n_est_pas_une_trace(J, tmp_path):
    od = LAD + "\\Microsoft\\OneDrive\\25.087.0506.0001"
    b = _wfp(tmp_path / "b.txt", **{**WBASE, "files": WBASE["files"] + ["d " + od, "f " + od + "\\x.dll",
                                                                      "f " + LAD + "\\Temp\\tmp4FF4.tmp"]})
    a = _wfp(tmp_path / "a.txt", keys=WBASE["keys"] + ["HKCU Microsoft OneDrive"],
             files=WBASE["files"] + ["d " + LAD + "\\PeerDistRepub"],
             firewall=WBASE["firewall"] + ["Microsoft Teams | True | Inbound | Allow",
                                           "Sécurité Windows | True | Outbound | Allow",
                                           "GoleM sshd | True | Inbound | Allow"],
             shortcuts=WBASE["shortcuts"] + [WH + "\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\OneDrive.lnk"])
    res = J.judge_win(b, a, WPLAN2, WH)
    assert res["leftovers"] == [], res["leftovers"]
    kept = dict(res["kept"])
    assert "Windows churn" in kept["> [firewall] Microsoft Teams | True | Inbound | Allow"]
    assert "gone by itself" in kept["< [files] d " + od]
    # une règle « golem* » qui n'est pas à golem, proposée décochée : gardée
    assert "offered by the uninstaller" in kept["> [firewall] GoleM sshd | True | Inbound | Allow"]


def test_win_une_regle_de_golem_reste_une_trace_meme_parmi_le_va_et_vient(J, tmp_path):
    b = _wfp(tmp_path / "b.txt", **{**WBASE, "firewall": WBASE["firewall"] + ["GoleM sshd | True | Inbound | Allow"]})
    a = _wfp(tmp_path / "a.txt", **{**WBASE, "firewall": WBASE["firewall"] + [
        "GoleM - bridge | True | Inbound | Allow", "GoleM - golem.local (mDNS) | True | Inbound | Allow",
        "Xbox TCUI | True | Outbound | Allow"]})
    res = J.judge_win(b, a, WPLAN2, WH)
    left = dict(res["leftovers"])
    assert "golem's firewall rule" in left["> [firewall] GoleM - bridge | True | Inbound | Allow"]      # du plan, coché
    assert "golem's firewall rule" in left["> [firewall] GoleM - golem.local (mDNS) | True | Inbound | Allow"]  # nom fixe
    assert "was here before golem" in left["< [firewall] GoleM sshd | True | Inbound | Allow"]      # le bug du 16/10
    assert "> [firewall] Xbox TCUI | True | Outbound | Allow" in dict(res["kept"])


def test_win_les_dossiers_communs_vont_a_leur_programme_jamais_a_python(J, tmp_path):
    cf = PF + "\\Common Files"
    b = _wfp(tmp_path / "b.txt", **WBASE)
    a = _wfp(tmp_path / "a.txt", keys=WBASE["keys"] + ["HKCU Python 3.12.10 (64-bit)"],
             progfiles=["d %s\\LV2" % cf, "d %s\\VST3" % cf, "d %s\\VST3\\NeuralAmpModeler.vst3" % cf,
                        "f %s\\VST3\\NeuralAmpModeler.vst3\\x" % cf, "d %s\\LV2\\other.lv2" % cf],
             files=WBASE["files"], firewall=WBASE["firewall"], shortcuts=WBASE["shortcuts"])
    res = J.judge_win(b, a, WPLAN2, WH)                    # défauts : NAM coché, Python décoché (gardé)
    left, kept = dict(res["leftovers"]), dict(res["kept"])
    assert "python" not in " ".join(left.values()).lower() + " ".join(kept.values()).lower().replace(
        "toolchain:python) and kept", "")
    assert "left behind" in left["> [program-files] d %s\\VST3\\NeuralAmpModeler.vst3" % cf]
    assert "> [program-files] d %s\\LV2\\other.lv2" % cf in left                    # NAM retiré : à personne
    assert "> [program-files] d %s\\LV2" % cf in left and "> [program-files] d %s\\VST3" % cf in left
    # NAM GARDÉ (choix réel) : son bundle et le dossier qui le porte restent, gardés
    a2 = _wfp(tmp_path / "a2.txt", keys=WBASE["keys"] + ["HKLM Neural Amp Modeler"],
              progfiles=["d %s\\VST3" % cf, "d %s\\VST3\\NeuralAmpModeler.vst3" % cf], files=WBASE["files"],
              firewall=WBASE["firewall"], shortcuts=WBASE["shortcuts"])
    res = J.judge_win(b, a2, WPLAN2, WH, chosen={"golem:install-folder"})
    kept = dict(res["kept"])
    assert res["leftovers"] == [] and "holds only what stays" in kept["> [program-files] d %s\\VST3" % cf]


def test_win_le_choix_reel_compte(J, tmp_path):
    b = _wfp(tmp_path / "b.txt", **WBASE)
    a = _wfp(tmp_path / "a.txt", keys=WBASE["keys"] + ["HKCU Python 3.12.10 (64-bit)"],
             progfiles=["d " + LAD + "\\Programs\\Python\\Python312", "f " + LAD + "\\Programs\\Python\\Python312\\python.exe"],
             files=WBASE["files"] + ["f " + LAD + "\\Temp\\golem-after-uninstall-20261016-1.log"],
             firewall=WBASE["firewall"] + ["python.exe | True | Inbound | Allow"], shortcuts=WBASE["shortcuts"])
    # les défauts : Python décoché -> gardé
    assert J.judge_win(b, a, WPLAN2, WH)["leftovers"] == []
    # coché pour de vrai : tout ce qui en reste est une trace ; le journal du veilleur, lui, est gardé exprès
    res = J.judge_win(b, a, WPLAN2, WH, chosen={"toolchain:python", "golem:install-folder"})
    left, kept = dict(res["leftovers"]), dict(res["kept"])
    assert "still installed" in left["> [uninstall-keys] HKCU Python 3.12.10 (64-bit)"]
    assert "should have gone with toolchain:python" in left["> [program-files] f %s\\Programs\\Python\\Python312\\python.exe" % LAD]
    assert "which was removed" in left["> [firewall] python.exe | True | Inbound | Allow"]
    assert "after-exit log" in kept["> [files] f %s\\Temp\\golem-after-uninstall-20261016-1.log" % LAD]


def test_win_lire_les_choix(J):
    assert J.parse_chosen('["a", "b"]') == {"a", "b"}
    assert J.parse_chosen('{"items": [{"id": "x", "selected": true}, {"id": "y", "selected": false}]}') == {"x"}
    log = ("LOG 2026-10-16T10:00:00 [stop] - OK golem stopped\n"
           "LOG 2026-10-16T10:00:01 [root] system:firewall:GoleM - bridge OK removed (1)\n"
           "LOG 2026-10-16T10:00:02 [user] golem:shortcut:Desktop/golem server.lnk FAILED boom OK\n")
    assert J.parse_chosen(log) == {"system:firewall:GoleM - bridge", "golem:shortcut:Desktop/golem server.lnk"}
    assert J.parse_chosen('SELECT ["a"]\nSELECT ["b"]\n') == {"a", "b"}
    assert J.parse_chosen("") is None and J.parse_chosen("garbage") is None


def test_win_ligne_de_commande_avec_les_choix(J, tmp_path, capsys):
    b = _wfp(tmp_path / "b.txt", **WBASE)
    a = _wfp(tmp_path / "a.txt", **{**WBASE, "keys": WBASE["keys"] + ["HKCU Python 3.12.10 (64-bit)"]})
    (tmp_path / "plan.json").write_text(json.dumps(WPLAN2))
    (tmp_path / "chosen.txt").write_text('SELECT ["toolchain:python"]\n')
    argv = ["judge", "--win", b, a, "--out", str(tmp_path / "out"), "--plan", str(tmp_path / "plan.json"), "--home", WH]
    assert J.main(argv) == 0 and "defaults are assumed" in capsys.readouterr().out
    assert J.main(argv + ["--chosen", str(tmp_path / "chosen.txt")]) == 1
    assert "1 item(s)" in capsys.readouterr().out
