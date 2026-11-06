# SPDX-License-Identifier: GPL-3.0-or-later
"""Le PLAN de désinstallation (docs/uninstall.md §3) sur un faux système de fichiers : ce qu'il propose, avec ou sans
reçu, et ce qu'il ne propose jamais. `plan` ne touche à rien."""
import json
import os
import subprocess
import sys

import pytest

from provision import uninstall as U
from tests.uninstall_fixtures import HOME, INSTALL, machine, receipt_data

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def fs(tmp_path, monkeypatch):
    f = machine(tmp_path / "fs")
    # le reçu du faux arbre (conftest pointe GOLEM_RECEIPT vers un fichier temporaire vide)
    monkeypatch.setenv("GOLEM_RECEIPT", f.p(HOME + "/.local/share/golem/install-receipt.json"))
    return f


def _ids(plan):
    return {i["id"]: i for i in plan["items"]}


def test_sans_recu_ce_qui_est_a_golem_par_son_nom(fs):
    plan = U.build_plan(fs.ctx())
    assert plan["mode"] == "no-receipt" and plan["root"] == INSTALL     # trouvé par le lien ~/.local/bin/golem
    ids = _ids(plan)
    for i in ("golem:install-folder", "golem:command", "golem:desktop:golem.desktop", "golem:icon:golem.png",
              "golem:share-dir", "golem:cache:golem-build", "golem:user-unit:golem-server.service",
              "reaper-links:Scripts/golem", "reaper-links:Effects/golem", "reaper-links:FXChains",
              "reaper-links:Scripts/__startup.lua", "reaper-links:OSC/golem.ReaperOSC", "reaper-ini:revert",
              "system:/etc/sudoers.d/golem-net", "system:/usr/local/sbin/golem-net",
              "system:/etc/systemd/system/golem-net.service", "system:/etc/security/limits.d/95-golem-audio.conf",
              "dedicated:/etc/sysctl.d/90-golem-port80.conf"):
        assert ids[i]["default"] is True and ids[i]["origin"] == "golem-named", i
    # ce qui n'est PAS à golem n'apparaît pas
    assert "reaper-links:OSC/mine.ReaperOSC" not in ids
    assert not any("someone-else" in i for i in ids)
    # partagé : listé, décoché, origine inconnue
    assert ids["system:audio-group"]["origin"] == "unknown" and ids["system:audio-group"]["default"] is False
    assert ids["plugins:nam"]["origin"] == "unknown" and ids["plugins:nam"]["default"] is False
    assert ids["reaper:config"]["default"] is False
    # le plugin qui porte le nom de golem est à golem
    assert ids["plugins:freeze"]["origin"] == "golem-named" and ids["plugins:freeze"]["default"] is True
    # sans reçu : pas d'apt, pas de REAPER lui-même, pas de Rust
    assert not any(i.startswith("apt:") for i in ids)
    assert "reaper:app" not in ids and "toolchain:rust" not in ids
    assert ids["reaper-ini:revert"]["reason"].startswith("golem OSC surface removed")
    assert ids["system:/etc/systemd/system/golem-net.service"]["action"] == "disable"
    assert ids["system:/etc/sudoers.d/golem-net"]["privilege"] == "root"


def test_avec_recu_les_choix_par_defaut(fs):
    fs.receipt(receipt_data())
    fs.file(HOME + "/.config/REAPER/Scripts/__startup.lua.golem-orig", "mine")
    plan = U.build_plan(fs.ctx())
    assert plan["mode"] == "receipt"
    ids = _ids(plan)
    assert ids["system:/etc/sudoers.d/golem-net"]["origin"] == "receipt"
    assert ids["plugins:nam"]["origin"] == "receipt" and ids["plugins:nam"]["default"] is True
    assert ids["system:audio-group"]["origin"] == "receipt" and ids["system:audio-group"]["default"] is True
    assert ids["reaper:app"]["default"] is False and ids["reaper:app"]["origin"] == "receipt"
    assert ids["toolchain:rust"]["default"] is True        # posée PAR golem (le reçu le dit) : cochée, 2026-10-24
    assert ids["reaper-links:Scripts/__startup.lua"]["action"] == "restore"
    assert ids["reaper-links:Scripts/__startup.lua"]["origin"] == "receipt"
    # apt : plugins audio cochés, outils décochés, la base JAMAIS proposée
    assert ids["apt:guitarix-lv2"]["default"] is True
    assert ids["apt:x42-plugins"]["default"] is True
    assert ids["apt:surge-xt"]["default"] is True                    # un .deb posé par golem
    assert ids["apt:ffmpeg"]["default"] is False
    assert "apt:pipewire" not in ids and "apt:git" not in ids
    assert "apt:not-installed-anymore" in plan["absent"]
    assert "file:/etc/gone.conf" in plan["absent"]
    # ce que golem n'a pas changé ne bouge pas : linger n'est pas allumé ici
    assert "golem:linger" not in ids


def test_la_base_du_systeme_n_est_jamais_proposee(fs):
    base = ["pipewire", "pipewire-jack", "wireplumber", "alsa-utils", "pulseaudio-utils", "git", "curl", "wget",
            "unzip", "python3-venv", "python3-pip", "network-manager", "avahi-daemon", "ufw", "build-essential"]
    fs.file("/var/lib/dpkg/status", "".join("Package: %s\nStatus: install ok installed\n\n" % p for p in base))
    fs.receipt(receipt_data(apt={"added": base, "debs": []}))
    plan = U.build_plan(fs.ctx())
    assert not any(i["group"] == "apt" for i in plan["items"])


def test_groupe_audio_deja_membre_avant(fs):
    d = receipt_data()
    d["prior"]["audio_group"] = True
    fs.receipt(d)
    assert "system:audio-group" not in _ids(U.build_plan(fs.ctx()))


def test_linger_remis_a_sa_valeur(fs):
    fs.file("/var/lib/systemd/linger/u", "")
    assert _ids(U.build_plan(fs.ctx()))["golem:linger"]["default"] is False          # sans reçu : inconnu
    fs.receipt(receipt_data())
    it = _ids(U.build_plan(fs.ctx()))["golem:linger"]
    assert it["default"] is True and it["privilege"] == "root" and it["origin"] == "receipt"


def test_recu_csurf_non_ajoute_ne_touche_que_les_cles(fs):
    d = receipt_data()
    d["prior"]["reaper_ini"] = {"csurf_added": False, "keys": {"automute": "1"}}
    fs.receipt(d)
    it = _ids(U.build_plan(fs.ctx()))["reaper-ini:revert"]
    assert "automute" in it["reason"] and "OSC" not in it["reason"]


def test_le_plan_ne_touche_a_rien(fs):
    fs.receipt(receipt_data())
    before = fs.snapshot()
    U.build_plan(fs.ctx())
    assert fs.snapshot() == before


def test_plan_json_en_ligne_de_commande(fs):
    env = {**os.environ, "HOME": HOME, "USER": "u"}
    out = subprocess.run([sys.executable, os.path.join(REPO, "provision", "uninstall.py"), "--root-fs", fs.base,
                          "plan", "--json"], capture_output=True, text=True, env=env, check=True).stdout
    plan = json.loads(out)
    assert plan["mode"] == "no-receipt"
    for it in plan["items"]:
        assert set(it) == {"id", "group", "label", "paths", "privilege", "origin", "default", "reason", "action",
                           "presence"}
        assert it["presence"] in ("present", "unknown")
        assert it["group"] in U.GROUPS and it["privilege"] in ("user", "root")
        assert it["origin"] in ("receipt", "golem-named", "unknown")
        assert "GoleM" not in it["label"] and "GoleM" not in it["reason"]
    txt = subprocess.run([sys.executable, os.path.join(REPO, "provision", "uninstall.py"), "--root-fs", fs.base,
                          "plan"], capture_output=True, text=True, env=env, check=True).stdout
    assert "[reaper-links]" in txt and "Never offered" in txt


def test_racine_par_option_ou_par_defaut(fs):
    os.unlink(fs.p(HOME + "/.local/bin/golem"))
    assert U.build_plan(fs.ctx())["root"] == INSTALL                     # ~/golem
    fs.file("/opt/g2/provision/golem")
    fs.file("/opt/g2/bridge/app.py")
    assert U.build_plan(fs.ctx(root="/opt/g2"))["root"] == "/opt/g2"


def test_un_recu_qui_pointe_vers_un_chemin_dangereux_n_est_pas_offert(fs):
    d = receipt_data()
    d["items"] += [{"id": "x1", "kind": "dir", "path": "/etc", "group": "system"},
                   {"id": "x2", "kind": "file", "path": "~/.bashrc", "group": "golem"}]
    fs.file(HOME + "/.bashrc")
    fs.receipt(d)
    ctx = fs.ctx()
    plan = U.build_plan(ctx)
    ids = _ids(plan)
    assert not any(i.endswith(":/etc") or i.endswith("/.bashrc") for i in ids)
    assert sum("receipt entry refused" in w for w in plan["warnings"]) == 2
    assert not U._expected(ctx, "/etc", INSTALL, {"/etc"})
    assert not U._expected(ctx, HOME + "/.bashrc", INSTALL, {HOME + "/.bashrc"})
    assert isinstance(plan["items"], list)


def test_ini_revert_pure():
    from tests.uninstall_fixtures import INI
    new, ch = U.ini_revert(INI, {"automute": "1", "midiins": None, "newkey": "7"}, True)
    sec = new.split("[reaper]\n")[1].split("[other]")[0]
    assert "automute=1" in sec and "midiins" not in sec and "newkey=7" in sec
    assert 'csurf_0=HUI "Mackie" 0 0' in sec
    assert 'csurf_1=OSC "Other"' in sec and "GoleM" not in sec
    assert "csurf_cnt=2" in sec and "csurf_2" not in sec
    assert "[other]\nautomute=5" in new and "[audioconfig]\nx=1" in new      # les autres sections intactes
    assert len(ch) == 4
    # csurf seul : csurf_cnt disparaît (golem l'avait ajouté avec)
    only = '[reaper]\ncsurf_0=OSC "golem" 3 8000 "127.0.0.1" 9000 1024 10 "golem"\ncsurf_cnt=1\n'
    new2, _ = U.ini_revert(only, {}, True)
    assert new2 == "[reaper]\n"
    # rien à faire = texte identique
    assert U.ini_revert(INI, {"automute": "0"}, False) == (INI, [])


def test_recu_partiel_et_ajouts_du_contrat(fs):
    d = receipt_data()
    d["items"].append({"id": "dir:~/.vst3/GoleM Freeze.vst3", "kind": "dir", "path": "~/.vst3/GoleM Freeze.vst3",
                       "owner": "user", "by": "provision/install-spectral.sh", "group": "plugins",
                       "prior": {"existed": True}})
    d["prior"].update(reaper_ini={"existed": False, "csurf_added": True, "keys": {"automute": "1"}},
                      apt_timers={"apt-daily.timer": "enabled", "apt-daily-upgrade.timer": "disabled"},
                      avahi_enabled="disabled",
                      ufw={"active": True, "rules": ["OpenSSH                    ALLOW       Anywhere",
                                                     "OpenSSH (v6)               ALLOW       Anywhere (v6)"]})
    fs.receipt(d)
    fs.file("/etc/NetworkManager/dnsmasq-shared.d/golem-name.conf")
    plan = U.build_plan(fs.ctx())
    ids = _ids(plan)
    # (1) déjà là avant golem : décoché
    assert ids["plugins:freeze"]["default"] is False and ids["plugins:freeze"]["reason"] == "already here before golem"
    # (2) reaper.ini créé par golem : ses clés retirées, pas remises à « 1 »
    assert "automute removed" in ids["reaper-ini:revert"]["reason"]
    assert ids["dedicated:apt-timers"]["default"] and "apt-daily.timer" in ids["dedicated:apt-timers"]["reason"]
    assert ids["dedicated:avahi"]["action"] == "disable"
    # ufw : OpenSSH était là (lignes de `ufw status`), il reste ; ufw était actif, il le reste
    assert "turned off" not in ids["dedicated:ufw"]["reason"]
    # (4) un reçu partiel : les restes à golem par leur nom sont quand même trouvés
    assert ids["golem:command"]["origin"] == "golem-named" and ids["golem:user-unit:golem-server.service"]
    assert ids["system:/etc/NetworkManager/dnsmasq-shared.d/golem-name.conf"]["default"] is True
    assert "toolchain:rust" in ids


def test_reaper_ini_cree_par_golem_garde_le_fichier(fs, monkeypatch):
    d = receipt_data()
    d["prior"]["reaper_ini"] = {"existed": False, "csurf_added": True, "keys": {"automute": "1", "midiins": None}}
    fs.receipt(d)
    ctx = fs.ctx()
    U.revert_ini(ctx, *U._ini_plan(ctx, U.load_receipt(ctx)[0])[:2])
    ini = fs.read(HOME + "/.config/REAPER/reaper.ini")
    sec = ini.split("[reaper]\n")[1].split("[other]")[0]
    assert "automute" not in sec and "midiins" not in sec and "GoleM" not in sec


# ── apt : les éléments = les paquets que golem a DEMANDÉS ; les dépendances partent avec eux, au run ─────────
def _apt_machine(fs, pkgs, auto):
    fs.file("/var/lib/dpkg/status", "".join("Package: %s\nStatus: install ok installed\n\n" % p for p in pkgs))
    fs.file("/var/lib/apt/extended_states",
            "".join("Package: %s\nArchitecture: amd64\nAuto-Installed: 1\n\n" % p for p in auto)
            + "Package: ffmpeg\nArchitecture: amd64\nAuto-Installed: 0\n\n")


def test_apt_avec_requested_seuls_les_demandes_sont_des_elements(fs):
    # 609 paquets dans apt.added en VM (2026-10-15) : les dépendances ne sont PAS des cases à cocher
    _apt_machine(fs, ["pipewire", "x42-plugins", "libx42-dep", "ffmpeg", "libavcodec60", "surge-xt", "libsurge-dep",
                      "jq", "user-later"], auto=["libx42-dep", "libavcodec60", "libsurge-dep"])
    fs.receipt(receipt_data(apt={"added": ["x42-plugins", "libx42-dep", "ffmpeg", "libavcodec60", "libsurge-dep",
                                           "jq", "pipewire", "gone-pkg"],
                                 "debs": ["surge-xt"], "requested": ["x42-plugins", "ffmpeg", "pipewire", "curl",
                                                                     "gone-pkg"]}))
    plan = U.build_plan(fs.ctx())
    ids = _ids(plan)
    apt = sorted(i for i in ids if i.startswith("apt:"))
    assert apt == ["apt:ffmpeg", "apt:jq", "apt:surge-xt", "apt:x42-plugins"]
    assert plan["apt_model"] == "requested"
    assert sorted(plan["apt_deps"]) == ["libavcodec60", "libsurge-dep", "libx42-dep"]
    assert ids["apt:x42-plugins"]["default"] is True and ids["apt:surge-xt"]["default"] is True
    assert ids["apt:ffmpeg"]["default"] is False
    # « manuel » mais demandé par aucun script : proposé, jamais coché, et on dit pourquoi
    assert ids["apt:jq"]["default"] is False and "no golem script asked" in ids["apt:jq"]["reason"]
    assert "apt:gone-pkg" in plan["absent"]
    pub = U.public(plan)
    assert "_apt_ours" not in pub and pub["apt_deps"] == plan["apt_deps"]


def test_apt_sans_requested_repli_sur_les_manuels(fs):
    _apt_machine(fs, ["x42-plugins", "libx42-dep", "ffmpeg", "libavcodec60"], auto=["libx42-dep", "libavcodec60"])
    fs.receipt(receipt_data(apt={"added": ["x42-plugins", "libx42-dep", "ffmpeg", "libavcodec60"], "debs": []}))
    plan = U.build_plan(fs.ctx())
    apt = sorted(i for i in _ids(plan) if i.startswith("apt:"))
    assert apt == ["apt:ffmpeg", "apt:x42-plugins"] and plan["apt_model"] == "manual"
    assert sorted(plan["apt_deps"]) == ["libavcodec60", "libx42-dep"]
    assert "Dependencies golem's packages pulled in (2)" in U.plan_text(plan)


# ── 3e cycle en VM (2026-10-16) : ce que le plan ne voyait pas ──────────────────────────────────────────────
def _closed(fs, logical):
    """Ferme un dossier comme /etc/sudoers.d (0750 root) l'est pour l'utilisateur."""
    if os.geteuid() == 0:
        pytest.skip("root lit tout : le dossier fermé ne se simule pas")
    os.chmod(fs.p(logical), 0)


def _reopen(fs, logical):
    os.chmod(fs.p(logical), 0o755)


def test_sudoers_illisible_presence_inconnue_jamais_absent(fs):
    fs.receipt(receipt_data())
    fs.file("/etc/sudoers.d/golem-perf")
    _closed(fs, "/etc/sudoers.d")
    try:
        plan = U.build_plan(fs.ctx())
    finally:
        _reopen(fs, "/etc/sudoers.d")
    ids = _ids(plan)
    for name in ("golem-net", "golem-perf"):            # celle du reçu, et celle au nom fixe
        it = ids["system:/etc/sudoers.d/%s" % name]
        assert it["presence"] == "unknown" and it["default"] is True and it["privilege"] == "root", it
        assert "without root" in it["reason"]
    assert ids["system:/etc/sudoers.d/golem-net"]["origin"] == "receipt"
    assert ids["system:/etc/sudoers.d/golem-perf"]["origin"] == "golem-named"
    assert not any("sudoers" in a for a in plan["absent"])
    assert not any("someone-else" in i for i in ids)                 # on ne devine que les noms de golem
    # lisible : rien d'inconnu, présence vue
    plan = U.build_plan(fs.ctx())
    assert _ids(plan)["system:/etc/sudoers.d/golem-net"]["presence"] == "present"


def test_sudoers_illisible_sans_recu(fs):
    _closed(fs, "/etc/sudoers.d")
    try:
        ids = _ids(U.build_plan(fs.ctx()))
    finally:
        _reopen(fs, "/etc/sudoers.d")
    assert ids["system:/etc/sudoers.d/golem-net"]["presence"] == "unknown"
    assert ids["system:/etc/sudoers.d/golem-perf"]["presence"] == "unknown"


def test_recu_dans_un_dossier_ferme_n_est_pas_absent(fs):
    d = receipt_data()
    d["items"].append({"id": "file:/etc/golem-x/secret.conf", "kind": "file", "path": "/etc/golem-x/secret.conf",
                       "owner": "root", "by": "x", "group": "system", "prior": None})
    fs.file("/etc/golem-x/secret.conf")
    fs.receipt(d)
    _closed(fs, "/etc/golem-x")
    try:
        plan = U.build_plan(fs.ctx())
    finally:
        _reopen(fs, "/etc/golem-x")
    it = _ids(plan)["system:/etc/golem-x/secret.conf"]
    assert it["presence"] == "unknown" and it["privilege"] == "root"
    assert "file:/etc/golem-x/secret.conf" not in plan["absent"]


def test_dossier_surveille_coche_s_il_est_vide(fs):
    os.makedirs(fs.p(HOME + "/golem-inbox/.imported"))
    it = _ids(U.build_plan(fs.ctx()))["golem:inbox"]
    assert it["default"] is True and it["group"] == "golem" and it["paths"] == ["~/golem-inbox"]
    assert "empty" in it["reason"]
    fs.file(HOME + "/golem-inbox/.imported/song.golem")
    fs.file(HOME + "/golem-inbox/mine.mp3")
    it = _ids(U.build_plan(fs.ctx()))["golem:inbox"]
    assert it["default"] is False and "2 files" in it["reason"]


def test_dossier_surveille_deplace_par_config(fs):
    fs.file(INSTALL + "/config/inbox.json", json.dumps({"dir": "~/Shared songs"}))
    os.makedirs(fs.p(HOME + "/Shared songs"))
    os.makedirs(fs.p(HOME + "/golem-inbox"))                          # l'ancien défaut n'est plus le dossier surveillé
    it = _ids(U.build_plan(fs.ctx()))["golem:inbox"]
    assert it["paths"] == ["~/Shared songs"] and it["default"] is True
    # un dossier interdit (le dossier personnel, ~/Music…) n'est jamais proposé
    fs.file(INSTALL + "/config/inbox.json", json.dumps({"dir": "~/Music"}))
    os.makedirs(fs.p(HOME + "/Music"))
    assert "golem:inbox" not in _ids(U.build_plan(fs.ctx()))
    # dans le dossier d'install : il part avec lui
    fs.file(INSTALL + "/config/inbox.json", json.dumps({"dir": INSTALL + "/inbox"}))
    os.makedirs(fs.p(INSTALL + "/inbox"))
    assert "golem:inbox" not in _ids(U.build_plan(fs.ctx()))


def _reaper_desktop(fs):
    """Ce que `install-reaper.sh --integrate-user-desktop` laisse (relevé en VM, 2026-10-16)."""
    sh = HOME + "/.local/share"
    fs.file(HOME + "/opt/REAPER/uninstall-reaper.sh", "#!/bin/sh\n")
    fs.file(sh + "/applications/cockos-reaper.desktop")
    fs.file(sh + "/applications/mimeinfo.cache")
    fs.file(sh + "/applications/defaults.list", "[Default Applications]\napplication/x-reaper-project=cockos-reaper.desktop\n")
    fs.file(HOME + "/.gnome/apps/cockos-reaper.desktop")
    fs.file(HOME + "/.config/menus/applications-merged/xdg-desktop-menu-dummy.menu")
    for n in ("cockos-reaper", "cockos-reaper-backup", "cockos-reaper-document"):
        fs.file(sh + "/icons/hicolor/256x256/apps/%s.png" % n)
    fs.file(sh + "/icons/hicolor/icon-theme.cache")
    fs.file(sh + "/mime/packages/application-x-reaper.xml")
    for n in ("mime.cache", "globs2", "application/x-reaper-project.xml"):
        fs.file(sh + "/mime/" + n)


def test_reaper_app_porte_son_integration_bureau(fs):
    d = receipt_data()
    d["items"].append({"id": "dir:~/opt/REAPER", "kind": "dir", "path": "~/opt/REAPER", "owner": "user",
                       "by": "provision/install-reaper.sh", "group": "reaper", "prior": None})
    fs.receipt(d)
    _reaper_desktop(fs)
    ids = _ids(U.build_plan(fs.ctx()))
    paths = ids["reaper:app"]["paths"]
    for p in ("~/.local/share/applications/cockos-reaper.desktop", "~/.gnome/apps/cockos-reaper.desktop",
              "~/.local/share/icons/hicolor/256x256/apps/cockos-reaper-backup.png",
              "~/.local/share/mime/packages/application-x-reaper.xml", "~/opt/REAPER"):
        assert p in paths, p
    assert paths[-1] == "~/opt/REAPER"                                 # le programme APRÈS son intégration
    assert "reaper:~/opt/REAPER" not in ids                           # le ~/opt/REAPER du reçu n'est plus en double
    assert ids["reaper:app"]["default"] is False



def test_les_paquets_de_compilation_de_golem_sont_coches(fs):
    # 2026-10-24 : la désinstallation de la VM Linux gardait cmake, une vingtaine de -dev et leurs ~500 dépendances —
    # demandés seulement pour compiler les plugins de golem, absents avant lui
    _apt_machine(fs, ["cmake", "libx11-dev", "ffmpeg", "libmine-dev"], auto=[])
    fs.receipt(receipt_data(apt={"added": ["cmake", "libx11-dev", "ffmpeg", "libmine-dev"],
                                 "requested": ["cmake", "libx11-dev", "ffmpeg"]}))
    ids = _ids(U.build_plan(fs.ctx()))
    assert ids["apt:cmake"]["default"] is True and ids["apt:libx11-dev"]["default"] is True
    assert "compile" in ids["apt:cmake"]["reason"]
    assert ids["apt:ffmpeg"]["default"] is False                    # un outil général : peut servir à autre chose
    assert ids["apt:libmine-dev"]["default"] is False               # demandé par aucun script de golem : jamais coché
