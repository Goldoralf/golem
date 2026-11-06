# SPDX-License-Identifier: GPL-3.0-or-later
"""Le reçu d'installation (docs/uninstall.md §2) : provision/receipt.py, et les scripts qui l'appellent.

Tout se passe dans des dossiers temporaires : HOME et GOLEM_RECEIPT sont redirigés, rien ne touche la machine."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROV = ROOT / "provision"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def R(tmp_path, monkeypatch):
    """receipt.py avec un HOME temporaire et le chemin par défaut du reçu (~/.local/share/golem/…)."""
    if sys.platform == "win32":
        # Le reçu Linux vit sous HOME ; sous Windows le module résout %LOCALAPPDATA%\GoleM et, GOLEM_RECEIPT
        # retiré ci-dessous, ces tests écrivaient le VRAI reçu de la machine (constaté le 2026-10-19 : 40 entrées
        # pytest dedans). Windows a son fichier : tests/test_receipt_windows.py.
        pytest.skip("the Linux receipt (HOME, apt, POSIX paths); Windows is covered by test_receipt_windows.py")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GOLEM_RECEIPT", raising=False)
    monkeypatch.delenv("SUDO_USER", raising=False)
    m = _load("golem_receipt_t", PROV / "receipt.py")
    m._home = home
    return m


def _data(R):
    return json.loads(Path(R.receipt_path()).read_text(encoding="utf-8"))


def test_chemin_du_recu_et_squelette(R):
    assert R.receipt_path() == str(R._home / ".local/share/golem/install-receipt.json")
    R.set_root(str(R._home / "golem"), release="v9.9.9")
    d = _data(R)
    assert d["format"] == 1 and d["root"] == str(R._home / "golem") and d["release"] == "v9.9.9"
    assert d["items"] == [] and d["apt"] == {"added": [], "debs": []} and d["prior"] == {}
    assert d["created"] and d["updated"]


def test_prior_le_premier_gagne_et_cles_pointees(R):
    assert R.prior("reaper_ini.keys.automute", "1") is True
    assert R.prior("reaper_ini.keys.automute", "0") is False           # jamais remplacé
    assert R.prior("reaper_ini.keys.midiins", None) is True            # null = la clé était absente : c'est une valeur
    assert R.prior("reaper_ini.keys.midiins", "4") is False
    assert R.prior("linger", False) is True
    assert R.prior("linger", True) is False
    d = _data(R)
    assert d["prior"] == {"reaper_ini": {"keys": {"automute": "1", "midiins": None}}, "linger": False}
    assert R.get_prior("reaper_ini.keys.automute") == "1"
    assert R.get_prior("nope", "dflt") == "dflt"


def test_prior_cli_json_texte_et_fichier(R, tmp_path, capsys):
    assert R.main(["prior", "audio_group", "false"]) == 0
    assert R.main(["prior", "governor", "powersave"]) == 0               # pas du JSON : du texte
    assert R.main(["prior", "reaper.version", "7.79", "--string"]) == 0  # sans --string ce serait un nombre
    assert R.main(["prior", "ufw", '{"active": false, "rules": []}']) == 0
    assert R.main(["prior", "auto_upgrades", "--file", str(tmp_path / "absent")]) == 0
    f = tmp_path / "20auto-upgrades"
    f.write_text('APT::Periodic::Update-Package-Lists "1";\n')
    assert R.main(["prior", "auto_upgrades", "--file", str(f)]) == 0     # déjà là (null) : non remplacé
    p = _data(R)["prior"]
    assert p["audio_group"] is False and p["governor"] == "powersave" and p["reaper"]["version"] == "7.79"
    assert p["ufw"] == {"active": False, "rules": []} and p["auto_upgrades"] is None
    capsys.readouterr()
    assert R.main(["get", "audio_group"]) == 0 and capsys.readouterr().out.strip() == "false"
    assert R.main(["get", "linger"]) == 1


def test_prior_fichier_lu_avant_ecrasement(R, tmp_path):
    f = tmp_path / "20auto-upgrades"
    f.write_text('APT::Periodic::Unattended-Upgrade "1";\n')
    R.main(["prior", "auto_upgrades", "--file", str(f)])
    f.write_text('APT::Periodic::Unattended-Upgrade "0";\n')            # harden.sh l'écrase ensuite
    R.main(["prior", "auto_upgrades", "--file", str(f)])                # 2e passage : rien ne bouge
    assert _data(R)["prior"]["auto_upgrades"] == 'APT::Periodic::Unattended-Upgrade "1";\n'


def test_ufw_status_parse():
    R = _load("golem_receipt_u", PROV / "receipt.py")
    txt = ("Status: active\n\nTo                         Action      From\n--                         ------      ----\n"
           "22/tcp                     ALLOW       Anywhere\n8080/tcp                   DENY        10.0.0.0/8\n")
    assert R.parse_ufw(txt) == {"active": True, "rules": ["22/tcp                     ALLOW       Anywhere",
                                                          "8080/tcp                   DENY        10.0.0.0/8"]}
    assert R.parse_ufw("Status: inactive\n") == {"active": False, "rules": []}
    assert R.parse_ufw("") == {"active": False, "rules": []}


def test_add_tilde_dedoublonne_et_fusion_garde_le_prior(R):
    h = R._home
    R.add(str(h / ".config/REAPER/Scripts/__startup.lua"), "link", "provision/link-reaper.sh", "reaper-links",
          moved_to=str(h / ".config/REAPER/Scripts/__startup.lua.golem-orig"))
    R.add(str(h / ".config/REAPER/Scripts/__startup.lua"), "link", "provision/link-reaper.sh", "reaper-links")
    R.add("/etc/sudoers.d/golem-net", "file", "provision/setup-net-sudo.sh", "system", owner="root")
    R.add("/etc/sudoers.d/golem-net", "file", "provision/setup-net-sudo.sh", "system", owner="root")
    items = _data(R)["items"]
    assert len(items) == 2
    link = items[0]
    assert link["id"] == "link:~/.config/REAPER/Scripts/__startup.lua"
    assert link["path"] == "~/.config/REAPER/Scripts/__startup.lua" and link["owner"] == "user"
    assert link["prior"] == {"moved_to": "~/.config/REAPER/Scripts/__startup.lua.golem-orig"}   # gardé
    assert items[1] == {"id": "file:/etc/sudoers.d/golem-net", "kind": "file", "path": "/etc/sudoers.d/golem-net",
                        "owner": "root", "by": "provision/setup-net-sudo.sh", "group": "system", "prior": None}


def test_add_existed_ne_remplace_pas_un_prior_nul(R):
    p = str(R._home / ".lv2/Aether.lv2")
    R.add(p, "dir", "provision/plugins.sh", "plugins")                  # 1er passage : posé par nous
    R.add(p, "dir", "provision/plugins.sh", "plugins", existed=True)    # 2e passage : il est là… c'est le nôtre
    assert _data(R)["items"][0]["prior"] is None
    q = str(R._home / ".lv2/Ratatouille.lv2")
    R.add(q, "dir", "provision/plugins.sh", "plugins", existed=True)    # là avant golem
    R.add(q, "dir", "provision/plugins.sh", "plugins")
    assert _data(R)["items"][1]["prior"] == {"existed": True}


def test_add_un_original_mis_de_cote_plus_tard_est_garde(R):
    p = str(R._home / ".config/REAPER/FXChains")
    R.add(p, "link", "provision/link-reaper.sh", "reaper-links")
    R.add(p, "link", "provision/link-reaper.sh", "reaper-links", moved_to=p + ".golem-orig")
    assert _data(R)["items"][0]["prior"] == {"moved_to": "~/.config/REAPER/FXChains.golem-orig"}


def test_add_refuse_un_kind_inconnu(R):
    with pytest.raises(ValueError):
        R.add("/x", "socket", "t", "g")


def test_apt_difference_dedoublonnee(R):
    R.apt_snapshot("before", packages=["bash", "pipewire", "ffmpeg"])
    assert R.apt_snapshot("after", packages=["bash", "pipewire", "ffmpeg", "x42-plugins", "jq"]) == ["jq", "x42-plugins"]
    R.apt_snapshot("before", packages=["bash", "pipewire", "ffmpeg", "x42-plugins", "jq"])
    R.deb("byod")
    R.apt_snapshot("after", packages=["bash", "pipewire", "ffmpeg", "x42-plugins", "jq", "byod", "calf-plugins"])
    apt = _data(R)["apt"]
    assert apt["added"] == ["jq", "x42-plugins", "calf-plugins"]         # fusion, dans l'ordre, sans doublon
    assert apt["debs"] == ["byod"]                                        # un .deb n'est pas aussi dans added
    assert "pipewire" not in apt["added"] and "ffmpeg" not in apt["added"]   # là avant : jamais à nous


def test_apt_after_sans_before_ne_devine_rien(R):
    assert R.apt_snapshot("after", packages=["pipewire"]) == []
    assert not Path(R.receipt_path()).exists() or _data(R)["apt"]["added"] == []


def test_apt_before_photo_fraiche(R):
    """Une photo d'un passage précédent attribuerait à golem ce que l'utilisateur a posé depuis : `before` la
    refait à chaque fois."""
    R.apt_snapshot("before", packages=["a"])
    R.apt_snapshot("after", packages=["a", "golem-dep"])
    R.apt_snapshot("before", packages=["a", "golem-dep", "user-own"])    # posé par l'utilisateur entre-temps
    R.apt_snapshot("after", packages=["a", "golem-dep", "user-own", "golem-dep2"])
    assert _data(R)["apt"]["added"] == ["golem-dep", "golem-dep2"]


def test_installed_packages_ne_garde_que_les_installes(R, monkeypatch):
    out = "installed\tbash\nconfig-files\told-thing\ninstalled\tjq\nnot-installed\tfoo\n"
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out))
    assert R.installed_packages() == ["bash", "jq"]


def test_deb_dedoublonne(R):
    R.deb("surge-xt")
    R.deb("surge-xt")
    assert _data(R)["apt"]["debs"] == ["surge-xt"]


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="sudo is POSIX")
def test_sous_sudo_le_recu_va_chez_l_utilisateur_et_lui_est_rendu(R, tmp_path, monkeypatch):
    user_home = tmp_path / "alice"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "root-home"))             # sous sudo : le HOME de root
    monkeypatch.setenv("SUDO_USER", "alice")
    monkeypatch.setattr(R.os, "geteuid", lambda: 0)
    monkeypatch.setattr(R.pwd, "getpwnam",
                        lambda n: SimpleNamespace(pw_dir=str(user_home), pw_uid=4242, pw_gid=4343))
    chowned = []
    monkeypatch.setattr(R.os, "chown", lambda p, u, g: chowned.append((str(p), u, g)))
    R.add(str(user_home / ".config/REAPER/UserPlugins/reaper_sws-x86_64.so"), "file", "provision/install-plugins.sh",
          "plugins", owner="root")
    rp = user_home / ".local/share/golem/install-receipt.json"
    assert R.receipt_path() == str(rp) and rp.is_file()
    assert json.loads(rp.read_text())["items"][0]["path"] == "~/.config/REAPER/UserPlugins/reaper_sws-x86_64.so"
    owned = {p for p, u, g in chowned if (u, g) == (4242, 4343)}
    # les dossiers CRÉÉS, le verrou et le fichier final (écrit par tmp puis replace) sont rendus à alice
    for d in (".local", ".local/share", ".local/share/golem"):
        assert str(user_home / d) in owned
    assert str(rp) + ".lock" in owned
    assert any(os.path.basename(p).startswith(".install-receipt-") for p in owned)
    assert str(user_home) not in owned                                    # ce qui existait n'est pas touché


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="sudo is POSIX")
def test_sudo_vers_root_ou_sans_sudo_user(R, monkeypatch):
    monkeypatch.setattr(R.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "root")
    assert R.receipt_path() == str(R._home / ".local/share/golem/install-receipt.json")


def test_ecriture_atomique(R, monkeypatch):
    R.prior("linger", False)
    before = Path(R.receipt_path()).read_text()

    def boom(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(R.json, "dump", boom)
    with pytest.raises(OSError):
        R.prior("governor", "powersave")
    assert Path(R.receipt_path()).read_text() == before                  # l'ancien reçu est intact
    leftovers = [p for p in Path(R.receipt_path()).parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_sans_changement_pas_de_reecriture(R):
    R.prior("linger", False)
    st = os.stat(R.receipt_path())
    R.prior("linger", True)
    assert os.stat(R.receipt_path()).st_mtime_ns == st.st_mtime_ns


def test_recu_illisible_mis_de_cote_jamais_ecrase(R):
    rp = Path(R.receipt_path())
    rp.parent.mkdir(parents=True)
    rp.write_text("{pas du json")
    R.prior("linger", False)
    aside = [p for p in rp.parent.iterdir() if ".corrupt-" in p.name]
    assert len(aside) == 1 and aside[0].read_text() == "{pas du json"
    assert _data(R)["prior"] == {"linger": False}


@pytest.mark.skipif(os.name != "posix", reason="POSIX paths (/etc/golem-…)")
def test_ecrivains_concurrents(tmp_path):
    """Plusieurs scripts écrivent : le verrou ne perd aucune écriture."""
    env = dict(os.environ, GOLEM_RECEIPT=str(tmp_path / "r.json"))
    procs = [subprocess.Popen([sys.executable, str(PROV / "receipt.py"), "prior", f"k{i}", str(i)], env=env)
             for i in range(12)]
    procs += [subprocess.Popen([sys.executable, str(PROV / "receipt.py"), "add", f"/etc/golem-{i}", "--kind", "file",
                                "--by", "t", "--group", "system"], env=env) for i in range(12)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    d = json.loads((tmp_path / "r.json").read_text())
    assert d["prior"] == {f"k{i}": i for i in range(12)}
    assert sorted(it["path"] for it in d["items"]) == sorted(f"/etc/golem-{i}" for i in range(12))


@pytest.mark.skipif(os.name != "posix", reason="runs the shell library under bash")
def test_lib_receipt_ne_casse_jamais_le_script(tmp_path):
    """L'enveloppe bash : un helper en échec (ici : un argument refusé) ne fait pas tomber un `set -e`."""
    script = tmp_path / "s.sh"
    script.write_text(f'set -euo pipefail\n. "{PROV}/lib-receipt.sh"\nreceipt add /x --kind socket --by t --group g\n'
                      f'receipt_add /etc/golem-x file system --owner root\necho "by=$GOLEM_RECEIPT_BY"\n')
    env = dict(os.environ, GOLEM_RECEIPT=str(tmp_path / "r.json"))
    r = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "install receipt not updated" in r.stderr
    d = json.loads((tmp_path / "r.json").read_text())
    assert [it["id"] for it in d["items"]] == ["file:/etc/golem-x"]


@pytest.mark.skipif(os.name != "posix", reason="runs the shell library under bash")
def test_lib_receipt_by_est_le_script_appelant(tmp_path):
    env = dict(os.environ, GOLEM_RECEIPT=str(tmp_path / "r.json"))
    r = subprocess.run(["bash", "-c", f'. "{PROV}/lib-receipt.sh"; echo "$GOLEM_RECEIPT_BY"'],
                       env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    script = tmp_path / "probe.sh"
    script.write_text(f'. "{PROV}/lib-receipt.sh"\necho "$GOLEM_RECEIPT_BY"\n')
    out = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30).stdout.strip()
    assert out.endswith("probe.sh")


@pytest.mark.skipif(os.name != "posix", reason="runs provision/link-reaper.sh under bash")
def test_link_reaper_met_de_cote_en_golem_orig(tmp_path):
    """link-reaper.sh dans un HOME temporaire : l'original de l'utilisateur part en *.golem-orig (jamais .bak) et
    le reçu dit où ; un ancien .bak posé par golem n'est pas touché ; rejouer ne déplace rien de plus."""
    home = tmp_path / "home"
    rdir = home / ".config/REAPER"
    (rdir / "Scripts").mkdir(parents=True)
    (rdir / "Scripts/__startup.lua").write_text("-- à moi\n")
    (rdir / "Scripts/__startup.lua.bak").write_text("-- ancien .bak golem\n")
    (rdir / "FXChains").mkdir()
    env = dict(os.environ, HOME=str(home))
    env.pop("GOLEM_RECEIPT", None)
    for _ in range(2):
        r = subprocess.run(["bash", str(PROV / "link-reaper.sh")], env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    assert (rdir / "Scripts/__startup.lua.golem-orig").read_text() == "-- à moi\n"
    assert (rdir / "Scripts/__startup.lua.bak").read_text() == "-- ancien .bak golem\n"
    assert (rdir / "FXChains.golem-orig").is_dir() and (rdir / "FXChains").is_symlink()
    assert not list(rdir.glob("*.golem-orig.*")) and not list((rdir / "Scripts").glob("*.golem-orig.*"))
    d = json.loads((home / ".local/share/golem/install-receipt.json").read_text())
    by_id = {it["id"]: it for it in d["items"]}
    assert by_id["link:~/.config/REAPER/Scripts/__startup.lua"]["prior"] == {
        "moved_to": "~/.config/REAPER/Scripts/__startup.lua.golem-orig"}
    assert by_id["link:~/.config/REAPER/FXChains"]["prior"] == {"moved_to": "~/.config/REAPER/FXChains.golem-orig"}
    assert by_id["link:~/.config/REAPER/Scripts/golem"]["group"] == "reaper-links"
    assert all(it["by"] == "provision/link-reaper.sh" for it in d["items"])


def test_reaper_ini_setup_note_les_valeurs_d_avant(tmp_path, monkeypatch):
    rp = tmp_path / "r.json"
    monkeypatch.setenv("GOLEM_RECEIPT", str(rp))
    M = _load("reaper_ini_setup_t", PROV / "reaper-ini-setup.py")
    section = ["automute=1", "midiins=4", "csurf_cnt=1"]
    M.record_prior(section, ["automute", "midiins", "alsa_indev"], csurf_added=False)
    assert not rp.exists()                       # pas de reçu : start.sh le relance à chaque démarrage, on n'en crée pas
    R = _load("golem_receipt_t2", PROV / "receipt.py")
    R.set_root(str(tmp_path))
    M.record_prior(section, ["automute", "midiins", "alsa_indev"], csurf_added=False)
    M.record_prior(["automute=0", "midiins=0"], ["automute", "midiins"], csurf_added=True)   # 2e passage : rien
    ini = json.loads(rp.read_text())["prior"]["reaper_ini"]
    assert ini == {"keys": {"automute": "1", "midiins": "4", "alsa_indev": None}, "csurf_added": False}


def test_reaper_ini_setup_main_complet(tmp_path, monkeypatch):
    """main() sur un reaper.ini temporaire : toutes les clés écrites ont leur valeur d'avant au reçu."""
    rp = tmp_path / "r.json"
    monkeypatch.setenv("GOLEM_RECEIPT", str(rp))
    R = _load("golem_receipt_t3", PROV / "receipt.py")
    R.set_root(str(tmp_path))
    M = _load("reaper_ini_setup_t2", PROV / "reaper-ini-setup.py")
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\nautomute=1\nnorunmute=1\nmidiins=4\n[other]\nx=1\n", encoding="latin-1")
    monkeypatch.setattr(M, "INI", str(ini))
    monkeypatch.setattr(M, "reaper_running", lambda: False)
    monkeypatch.setattr(M, "write_keys_sidecar", lambda *a, **k: None)
    monkeypatch.setattr(M, "reaper_midi_index", lambda direction: (None, None, "test"))
    M.main()
    prior = json.loads(rp.read_text())["prior"]["reaper_ini"]
    assert prior["csurf_added"] is True
    k = prior["keys"]
    assert k["automute"] == "1" and k["norunmute"] == "1" and k["midiins"] == "4"
    assert k["alsa_indev"] is None and k["alsa_outdev"] is None and k["midiouts"] is None
    assert "csurf_cnt" not in k and "csurf_0" not in k
    assert "automute=0" in ini.read_text(encoding="latin-1")


def test_bridge_n_ecrit_que_dans_un_recu_existant(tmp_path, monkeypatch):
    rp = tmp_path / "r.json"
    monkeypatch.setenv("GOLEM_RECEIPT", str(rp))
    from bridge import install_receipt as B
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux seulement")
    assert B.prior("reaper.license_present", False) is False
    assert not rp.exists()
    R = _load("golem_receipt_t4", PROV / "receipt.py")
    R.set_root(str(tmp_path))
    assert B.prior("reaper.license_present", False) is True
    assert B.prior("reaper.license_present", True) is False
    ini = tmp_path / "reaper.ini"
    ini.write_text("[audio]\nlinux_audio_bsize=1\n[reaper]\nlinux_audio_bsize=128\n", encoding="latin-1")
    assert B.ini_value(str(ini), "linux_audio_bsize") == "128"
    assert B.ini_value(str(ini), "alsa_indev") is None
    B.add(str(tmp_path / "opt/reaper-versions"), "dir", "reaper", by="bridge/reaper_update.py")
    d = json.loads(rp.read_text())
    assert d["prior"]["reaper"] == {"license_present": False}
    assert d["items"][0]["group"] == "reaper"


def test_autostart_off_rend_le_linger_d_avant():
    src = (PROV / "autostart/install-autostart.sh").read_text(encoding="utf-8")
    off = src.split('if [ "${1:-}" = "--off" ]; then', 1)[1].split("\nfi\n", 1)[0]
    assert 'receipt.py" get linger' in off
    assert re.search(r'\[ "\$prior_linger" = false \] && linger_on', off)
    assert "disable-linger" in off
    on = src.split("\nfi\n", 1)[1]
    assert on.index("receipt prior linger") < on.index("enable-linger")      # noté AVANT d'être posé


def test_installateur_retire_son_askpass(monkeypatch):
    sys.path.insert(0, str(ROOT / "installer"))
    try:
        P = _load("platform_linux_t", ROOT / "installer/platform_linux.py")
    finally:
        sys.path.remove(str(ROOT / "installer"))
    p = P._askpass()
    d = os.path.dirname(p)
    assert os.path.isdir(d) and os.path.basename(d).startswith("golem-installer-")
    P.cleanup()
    assert not os.path.exists(d)
    P.cleanup()                                   # idempotent
    srv = (ROOT / "installer/server.py").read_text(encoding="utf-8")
    assert "os._exit(0)" not in srv.replace("os._exit(code)", "")   # toute sortie passe par cleanup()
    assert "atexit.register(cleanup)" in srv


# ── garde statique : tout script de provision qui écrit dans un endroit partagé tient le reçu ──────────────
SHARED = re.compile(r"/etc/|/usr/local|\.lv2|\.vst3|\.clap|\.vst\b|\.local/|\.config/REAPER|HOME\}?/opt|\.cache/golem")
# exceptions, chacune avec sa raison
ALLOW = {
    "net.sh": "copie ROOT-OWNED exécutée en sudo NOPASSWD (/usr/local/sbin/golem-net) : elle ne doit JAMAIS exécuter "
              "un script du dépôt (modifiable par l'utilisateur). Le profil golem-ap et dnsmasq-shared.d/golem-name.conf "
              "sont retrouvés par leur nom à la désinstallation.",
    "start.sh": "lit le binaire REAPER (~/opt/REAPER), n'écrit rien d'installé",
    "golem": "lanceur à l'exécution ; son profil de navigateur (~/.local/share/golem/browser) est noté par "
             "install-desktop.sh",
    "desktop.py": "Windows / macOS — le reçu commence par Linux (docs/uninstall.md, statut)",
    "receipt.py": "le helper lui-même",
    "lib-receipt.sh": "l'enveloppe du helper",
    "uninstall.py": "la désinstallation LIT le reçu et retire : elle n'installe rien",
}


def _provision_scripts():
    files = sorted(PROV.glob("*.sh")) + sorted(PROV.glob("*.py")) + sorted((PROV / "autostart").glob("*.sh"))
    files.append(PROV / "golem")
    return files


def test_chaque_script_qui_ecrit_un_endroit_partage_tient_le_recu():
    missing = []
    for f in _provision_scripts():
        txt = f.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
        if not SHARED.search(code) or f.name in ALLOW:
            continue
        if "receipt.py" not in txt and "lib-receipt.sh" not in txt:
            missing.append(str(f.relative_to(ROOT)))
    assert missing == [], f"scripts qui écrivent un endroit partagé sans tenir le reçu : {missing}"


def test_les_exceptions_existent_encore():
    names = {f.name for f in _provision_scripts()}
    assert set(ALLOW) <= names, set(ALLOW) - names


def test_plus_de_bak_pour_les_originaux_deplaces():
    src = (PROV / "link-reaper.sh").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert ".golem-orig" in code and '.bak"' not in code


def test_apt_requested_note_les_explicites(R):
    R.apt_requested(["x42-plugins", "ffmpeg", "x42-plugins", "libfoo:amd64", "", "-y", "/tmp/x/surge.deb"])
    R.apt_requested(["ffmpeg", "jq"])
    apt = _data(R)["apt"]
    assert apt["requested"] == ["x42-plugins", "ffmpeg", "libfoo", "jq"]          # fusion, sans doublon ni arch
    assert apt["added"] == [] and apt["debs"] == []                               # la demande n'est pas l'effet


def test_chaque_apt_get_install_note_sa_demande():
    """Chaque script qui appelle apt-get install / dpkg -i nomme aussi ses paquets au reçu (apt.requested) : sinon le
    désinstallateur prend ses paquets explicites pour des dépendances (docs/uninstall.md §2)."""
    miss = []
    for p in sorted(PROV.glob("*.sh")):
        src = p.read_text(encoding="utf-8")
        code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
        if re.search(r"apt-get\b[^\n]*\binstall -y|\bdpkg -i\b|\$\{APT\[@\]\}\" install", code) \
                and "receipt apt-requested" not in code:
            miss.append(p.name)
    assert not miss, miss
