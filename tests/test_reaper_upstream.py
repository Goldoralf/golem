# SPDX-License-Identifier: GPL-3.0-or-later
"""La version PUBLIÉE en amont (docs : Settings ▸ Licenses ▸ Versioning, 2026-09-22).

Ce que ces tests gardent : LIRE N'EST PAS INSTALLER. Le rack affiche la dernière version publiée par
Cockos, mais sa CIBLE reste le pin de la release (`provision/install-reaper.sh`) — aucun bouton, aucun
chemin de code ne vise `upstream`. Et la lecture ne doit jamais bloquer une carte : elle part en fond,
une fois par jour, et une panne réseau n'efface pas ce qu'on savait.
"""
import time

import pytest

from bridge import reaper_update as R


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "_UP", {"version": None, "at": 0, "error": None, "checking": False})
    active = tmp_path / "reaper"
    active.touch()
    monkeypatch.setattr(R, "ACTIVE", str(active))
    monkeypatch.setattr(R, "WINDOWS", False)       # la mécanique du RACK, quel que soit l'OS du test
    return R._UP


def test_sous_windows_la_meme_regle_par_la_mecanique_de_windows(monkeypatch):
    """Windows (2026-10-03 : « que le golem puisse mettre à jour Reaper ») : même règle qu'au rack
    — le pin, l'ancienne gardée à côté, retour en un tap — mais par desktop_reaper (installeur + UAC)."""
    from bridge import desktop_reaper
    monkeypatch.setattr(R, "WINDOWS", True)
    # status() vérifie que le moteur EXISTE (559424d) : le dossier de REAPER de la machine de test n'existe pas
    monkeypatch.setattr(R, "_win_reaper_dir", lambda: R.ACTIVE)
    monkeypatch.setattr(R, "installed_version", lambda path=None: "7.27")
    monkeypatch.setattr(R, "pinned_version", lambda: "7.79")
    monkeypatch.setattr(desktop_reaper, "previous_version", lambda: "7.20")
    st = R.status(check=False)
    assert st["installed"] == "7.27" and st["status"] == "update-available" and st["needs_permission"]
    assert st["versions"] == [{"version": "7.27", "active": True}, {"version": "7.20", "active": False}]
    started = []
    monkeypatch.setattr(R.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append((target.__name__, args))})())
    assert R.start_update()[0] is True and started == [("_win_worker", ("7.27", "7.79", True))]
    R._PROG["busy"] = False
    started.clear()
    assert R.start_switch("7.20")[0] is True and started == [("_win_switch_worker", ("7.27", "7.20"))]
    R._PROG["busy"] = False


def _fake_engine(monkeypatch, verify, elevated_fails=False):
    from bridge import desktop_reaper as D
    calls = []
    monkeypatch.setattr(D, "download", lambda ver, url, sha, log: (calls.append(("download", url, sha)) or ("x.exe", "h")))
    monkeypatch.setattr(D, "stop_engine", lambda log: calls.append(("stop",)) or ["reaper.exe"])
    monkeypatch.setattr(D, "start_engine", lambda reopen: calls.append(("start",)))
    monkeypatch.setattr(D, "reaper_dir", lambda: "C:/PF/REAPER (x64)")

    def elevated(args, log):
        calls.append(("elevated", args[0]))
        if elevated_fails:
            raise RuntimeError("Windows permission was not granted — nothing was changed")
    monkeypatch.setattr(D, "elevated", elevated)
    monkeypatch.setattr(D, "verify_alive", lambda timeout=0: verify)
    monkeypatch.setattr(D, "reaper_title", lambda: None)              # jamais le REAPER de la machine
    monkeypatch.setattr(D, "wait_title", lambda version, timeout=30: None)
    return D, calls


def test_windows_update_verifiee_puis_rollback_si_le_moteur_ne_revient_pas(monkeypatch):
    D, calls = _fake_engine(monkeypatch, verify=True)
    noop = lambda *a: None
    last = D.run_update("7.27", "7.79", True, "https://pin/reaper779.exe", "ab" * 32, noop, noop)
    assert last["ok"] and calls[0] == ("download", "https://pin/reaper779.exe", "ab" * 32)
    assert [c[0] for c in calls] == ["download", "stop", "elevated", "start"]
    # non validée : l'URL officielle de Cockos, AUCUNE empreinte prétendue
    D, calls = _fake_engine(monkeypatch, verify=False)
    last = D.run_update("7.27", "7.81", False, "https://pin/reaper779.exe", "ab" * 32, noop, noop)
    assert calls[0] == ("download", "https://www.reaper.fm/files/7.x/reaper781_x64-install.exe", None)
    assert last["rolled_back"] and ("elevated", "-ReaperSwap") in calls


def test_la_licence_se_lit_dans_le_titre_de_reaper():
    from bridge import desktop_reaper as D
    assert D.license_state("golem-set - REAPER v7.27 - Registered to alex (Commercial license)") == "registered"
    assert D.license_state("golem-set - REAPER v7.79 - EVALUATION LICENSE") == "evaluation"
    assert D.license_state("") is None


def test_une_mise_a_jour_qui_perd_la_licence_revient_en_arriere(monkeypatch):
    """2026-10-03 : 7.79 debout, lien OSC vivant… et en ÉVALUATION — la clé que 7.27 acceptait était refusée."""
    D, calls = _fake_engine(monkeypatch, verify=True)
    titles = iter(["REAPER v7.27 - Registered to alex (Commercial license)"])
    monkeypatch.setattr(D, "reaper_title", lambda: next(titles, None))
    monkeypatch.setattr(D, "wait_title", lambda version, timeout=30: "golem-set - REAPER v7.79 - EVALUATION LICENSE")
    noop = lambda *a: None
    last = D.run_update("7.27", "7.79", True, "u", "s", noop, noop)
    assert not last["ok"] and last["rolled_back"] and last["license_lost"]
    assert "does not accept your license" in last["error"]
    assert ("elevated", "-ReaperSwap") in calls
    # licence gardée : pas de retour
    D, calls = _fake_engine(monkeypatch, verify=True)
    monkeypatch.setattr(D, "reaper_title", lambda: "REAPER v7.27 - Registered to alex (Commercial license)")
    monkeypatch.setattr(D, "wait_title", lambda version, timeout=30: "REAPER v7.79 - Registered to alex (Commercial license)")
    assert D.run_update("7.27", "7.79", True, "u", "s", noop, noop)["ok"]
    assert ("elevated", "-ReaperSwap") not in calls


def test_windows_permission_refusee_le_moteur_repart_tel_quel(monkeypatch):
    D, calls = _fake_engine(monkeypatch, verify=True, elevated_fails=True)
    noop = lambda *a: None
    with pytest.raises(RuntimeError, match="not granted"):
        D.run_update("7.27", "7.79", True, "u", "s", noop, noop)
    assert calls[-1] == ("start",)


def _wait(t):
    if t is not None:
        t.join(5)


def test_la_premiere_ligne_de_whatsnew_donne_la_version(monkeypatch):
    lines = []

    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def readline(self, n=0):
            return lines[0]

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    for raw, want in ((b"v7.80 - September 13 2026\n", "7.80"), (b"v7.79 - August 17 2026", "7.79")):
        lines[:] = [raw]
        assert R._fetch_upstream() == want
    lines[:] = [b"<html>maintenance</html>"]
    with pytest.raises(ValueError):
        R._fetch_upstream()


def test_la_lecture_part_en_fond_et_ne_se_refait_pas_avant_un_jour(monkeypatch):
    calls = []
    monkeypatch.setattr(R, "_fetch_upstream", lambda: (calls.append(1), "7.80")[1])
    _wait(R.upstream_check())
    assert calls == [1] and R._UP["version"] == "7.80" and R._UP["checking"] is False
    _wait(R.upstream_check())                       # frais : aucune seconde requête
    assert calls == [1]
    R._UP["at"] = time.time() - R.UPSTREAM_TTL - 1  # périmé
    _wait(R.upstream_check())
    assert len(calls) == 2
    _wait(R.upstream_check(force=True))             # ↻ de la carte
    assert len(calls) == 3


def test_une_panne_reseau_n_efface_pas_ce_qu_on_savait(monkeypatch):
    monkeypatch.setattr(R, "_fetch_upstream", lambda: "7.80")
    _wait(R.upstream_check())

    def boom():
        raise OSError("Network is unreachable")
    monkeypatch.setattr(R, "_fetch_upstream", boom)
    _wait(R.upstream_check(force=True))
    assert R._UP["version"] == "7.80" and "unreachable" in R._UP["error"] and R._UP["checking"] is False


def test_l_etat_dit_qu_une_version_plus_recente_EXISTE_sans_changer_la_cible(monkeypatch):
    monkeypatch.setattr(R, "installed_version", lambda path=None: "7.79")
    monkeypatch.setattr(R, "pinned_version", lambda: "7.79")
    monkeypatch.setattr(R, "_fetch_upstream", lambda: "7.80")
    _wait(R.upstream_check())
    st = R.status(check=False)
    assert st["upstream"] == "7.80" and st["upstream_newer"] is True
    # LA CIBLE NE BOUGE PAS : le statut reste « à jour » (c'est lui qui arme le bouton de l'UI)
    assert st["status"] == "up-to-date" and st["pinned"] == "7.79"


def test_un_rack_en_avance_ou_a_jour_avec_l_amont_ne_signale_rien(monkeypatch):
    monkeypatch.setattr(R, "installed_version", lambda path=None: "7.80")
    monkeypatch.setattr(R, "pinned_version", lambda: "7.80")
    monkeypatch.setattr(R, "_fetch_upstream", lambda: "7.80")
    _wait(R.upstream_check())
    st = R.status(check=False)
    assert st["upstream_newer"] is False and st["status"] == "up-to-date"


def test_on_n_installe_que_la_version_PUBLIEE_ou_le_pin(monkeypatch):
    """Une cible qui ne vient pas de reaper.fm ne s'installe pas : l'id arrive d'un écran, pas d'une
    autorité. Et une version malformée ne devient jamais un chemin de fichier."""
    monkeypatch.setattr(R, "installed_version", lambda path=None: "7.79")
    monkeypatch.setattr(R, "pinned_version", lambda: "7.79")
    monkeypatch.setattr(R, "_fetch_upstream", lambda: "7.80")
    _wait(R.upstream_check())
    started = []
    monkeypatch.setattr(R.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args)})())
    assert R.start_update("9.99")[0] is False
    assert R.start_update("../etc")[0] is False
    assert R.start_update("7.79")[0] is False          # déjà là
    assert started == []
    ok, err = R.start_update("7.80")
    assert ok and err is None and started == [("7.79", "7.80", False)]      # validated=False
    R._PROG["busy"] = False
    started.clear()
    monkeypatch.setattr(R, "pinned_version", lambda: "7.80")                 # le pin a bougé
    assert R.start_update()[0] is True and started == [("7.79", "7.80", True)]   # validated=True
    R._PROG["busy"] = False


def test_une_install_non_validee_ne_pretend_pas_verifier(monkeypatch, tmp_path):
    """Elle JOURNALISE le sha256 obtenu — Cockos n'en publie aucun à quoi le comparer."""
    monkeypatch.setattr(R, "PREFIX", str(tmp_path))
    monkeypatch.setattr(R, "VERSIONS", str(tmp_path / "reaper-versions"))
    monkeypatch.setattr(R, "pinned_sha256", lambda: "a" * 64)
    monkeypatch.setattr(R, "_run", lambda cmd, timeout, **kw: _fake_dl(cmd, tmp_path))
    R._PROG["log"] = []
    with pytest.raises(RuntimeError, match="no reaper binary"):              # l'install s'arrête après le hash
        R._download_and_install("7.80", validated=False)
    log = "\n".join(R._PROG["log"])
    assert "not validated" in log and "Downloaded sha256: " in log and "verified against the pinned" not in log
    R._PROG["log"] = []
    with pytest.raises(RuntimeError, match="sha256 mismatch"):                # le pin, lui, VÉRIFIE
        R._download_and_install("7.80", validated=True)


def _fake_dl(cmd, tmp_path):
    """curl -> écrit un faux tarball ; tar/install -> ne font rien (l'install échoue après le hash)."""
    if cmd[0] == "curl":
        open(cmd[-1], "wb").write(b"not a real tarball")
    return None


def test_le_retour_a_une_version_deja_installee_ne_depend_pas_du_reseau(monkeypatch):
    monkeypatch.setattr(R, "installed_version", lambda path=None: "7.80")
    monkeypatch.setattr(R, "installed_versions", lambda: [{"version": "7.80", "active": True},
                                                          {"version": "7.79", "active": False}])
    started = []
    monkeypatch.setattr(R.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append((target.__name__, args))})())
    assert R.start_switch("7.77")[0] is False          # pas sur le rack
    assert R.start_switch("7.80")[0] is False          # déjà celle qui tourne
    assert started == []
    assert R.start_switch("7.79")[0] is True and started == [("_switch_worker", ("7.80", "7.79"))]
    R._PROG["busy"] = False


def test_l_ecran_dit_ce_que_coute_une_install_non_validee():
    """Garde de CONCEPTION (2026-09-22 : l'utilisateur doit pouvoir installer seul, mais en
    sachant) : le bouton principal vise toujours le PIN ; celui de la version publiée est armé en
    deux taps et montre d'abord ce qu'on perd — pas jouée ici, rien à vérifier, retour en un tap."""
    import os
    js = open(os.path.join(os.path.dirname(__file__), "..", "app", "page-licenses.js"), encoding="utf8").read()
    card = js[js.index("function ReaperVersioningCard"):js.index("function ReaperLicenseCard")]
    assert "Update engine to ${r.pinned}" in card                      # le chemin validé reste le principal
    assert "confirm('u'" in card and "Install ${r.upstream}" in card
    warn = card[card.index("upd-warn"):card.index("upd-actions")]
    assert "Nobody has played it on this rig" in warn and "publishes no checksum" in warn
    assert "stays on this rack" in warn
    src = open(os.path.join(os.path.dirname(__file__), "..", "bridge", "reaper_update.py"), encoding="utf8").read()
    head = src[:src.index("import os")]
    assert "DEUX CHEMINS" in head and "HTTPS" in head                  # l'en-tête ne promet plus l'ancienne règle
