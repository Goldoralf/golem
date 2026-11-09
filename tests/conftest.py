# SPDX-License-Identifier: GPL-3.0-or-later
"""Garde commune à TOUS les tests : aucun ne parle au serveur golem.fm appairé.

Sans elle, la suite lisait la vraie config d'appairage (config/integrations.json) : tout chemin qui pousse
hors cadence (battement débouncé, catalogue de patches, setlist) pouvait envoyer l'état d'un test au vrai
serveur. Trouvé le 2026-09-30 en faisant pousser le battement à chaque changement de preset. Un test qui a
besoin d'un serveur le simule lui-même (monkeypatch de `_cfg` / `_req`) : son réglage passe après celui-ci."""
import os

import pytest

# ── LE BANC DU PREMIER USAGE D'UN PLUGIN (bridge/plugin_trial.py, 2026-11-09) : JAMAIS pendant la suite. Sans ça, tout
# test qui compile un bloc VST Host sous Linux lancerait un vrai REAPER séparé. Les tests du banc le rallument eux-mêmes.
os.environ["GOLEM_VST_TRIAL"] = "0"

# ── LES FICHIERS DU RACK QU'UN TEST NE TOUCHE JAMAIS (2026-10-29) ─────────────────────────────────────────────────
# Un test réécrivait presets/.perfsrc.json (ce que golem_perfrec lit à chaque prise) : après chaque passage de la
# suite, les prises partaient sans DI et sans partition, en silence. Leur CONTENU est photographié au début de la
# session et comparé à la fin : un écart fait échouer la suite, en le nommant. (Le contenu, pas la date : le bridge
# qui tourne à côté republie .perfsrc.json à chaque rappel, à l'identique.)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUARDED = ("presets/.perfsrc.json", "config/recorder.json", "config/compo.json", "config/click.json",
            "config/io.json", "config/string-calib.json", "config/vst-knobs.json", "config/vst-trials.json")


def _snapshot():
    out = {}
    for rel in _GUARDED:
        try:
            with open(os.path.join(_ROOT, rel), "rb") as f:
                out[rel] = f.read()
        except OSError:
            out[rel] = None
    return out


@pytest.fixture(autouse=True, scope="session")
def _les_fichiers_du_rack_restent_intacts():
    before = _snapshot()
    yield
    after = _snapshot()
    changed = [rel for rel in _GUARDED if before[rel] != after[rel]]
    if changed:
        # remis comme avant, puis dit : le rack ne doit pas rester abîmé par la suite
        for rel in changed:
            path = os.path.join(_ROOT, rel)
            if before[rel] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[rel])
        pytest.fail("a test wrote the rack's own files (restored): " + ", ".join(changed), pytrace=False)


@pytest.fixture(autouse=True)
def _pas_de_serveur(monkeypatch):
    from bridge import golemfm, rigstatus
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("", ""))
    monkeypatch.setattr(rigstatus, "push_soon", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _pas_les_configs_des_blocs_singletons(monkeypatch, tmp_path_factory):
    """Les blocs Rec, Click et Compo sont des SINGLETONS : enregistrer un preset écrit leur config globale
    (store.RECORDER_CFG, CLICK_CFG, COMPO_CFG — chemins figés à l'import, qu'un CONFIG_DIR redirigé ne suit pas).
    Une centaine de tests de quatre fichiers créaient ainsi config/recorder.json, compo.json et click.json du dépôt,
    et la CI était rouge depuis le 2026-10-26 (2026-11-04). Un test qui lit ou écrit ces configs pose les siennes :
    son réglage passe après celui-ci."""
    from bridge import store
    d = tmp_path_factory.mktemp("singletons")
    for k, name in (("RECORDER_CFG", "recorder.json"), ("CLICK_CFG", "click.json"), ("COMPO_CFG", "compo.json")):
        monkeypatch.setattr(store, k, str(d / name))


@pytest.fixture(autouse=True)
def _pas_de_peripheriques_reels(monkeypatch):
    """Aucun test ne lit le gestionnaire de périphériques de la machine (Get-PnpDevice, ~1 s, et ce qui est
    branché sur le PC du développeur) — 2026-10-03. Le test de usb_ids le rejoue avec une sortie simulée."""
    from bridge import desktop_midi
    real = desktop_midi.usb_ids
    monkeypatch.setattr(desktop_midi, "usb_ids", lambda names=None: {})
    monkeypatch.setattr(desktop_midi, "_REAL_USB_IDS", real, raising=False)


@pytest.fixture(autouse=True)
def _pas_de_kits_mesures_locaux(monkeypatch, tmp_path_factory):
    """Les kits MESURÉS de la machine (config/drumkits.local/, 2026-10-03) ne fuient pas dans les tests : ils
    prennent le pas sur les graines, et un test qui lit le Nitro d'usine lisait la mesure du mainteneur."""
    from bridge import drumkits
    monkeypatch.setattr(drumkits, "LOCAL_DIR", str(tmp_path_factory.mktemp("drumkits-local")))


@pytest.fixture(autouse=True)
def _pas_les_vraies_chansons(monkeypatch, tmp_path_factory):
    """Aucun test ne touche le VRAI répertoire `songs/` (2026-10-08). Une trentaine le LISAIENT via les
    setlists (chaque ligne résout sa chanson) — sans dégât tant que lire ne faisait que lire. Depuis qu'une
    chanson est un `.golem`, le premier accès MIGRE les anciens JSON : la suite a migré la chanson du mainteneur
    (sans perte, mais un test n'écrit pas sur la machine). Un test qui veut son dossier le pose lui-même :
    son réglage passe après celui-ci."""
    from bridge import config as C
    monkeypatch.setattr(C, "SONGS_DIR", str(tmp_path_factory.mktemp("songs")))


@pytest.fixture(autouse=True)
def _pas_le_vrai_cache_de_backings(monkeypatch, tmp_path_factory):
    """Aucun test ne lit le VRAI cache de backings (2026-10-16) : depuis qu'il entre dans l'inventaire, un test de
    l'inventaire comptait les six pistes du rack du mainteneur. Un test qui veut son cache le pose lui-même."""
    from bridge import config as C
    monkeypatch.setattr(C, "BACKING_DIR", str(tmp_path_factory.mktemp("backing")))


@pytest.fixture(autouse=True)
def _pas_les_vrais_standards_golem(monkeypatch, tmp_path_factory):
    """Les standards en .golem (library/standards/golem/, lot 10) : un test qui les lit lit la machine. Vécu le
    2026-10-08 — le premier test d'inventaire comptait 7 cartes au lieu d'une (les six standards du mainteneur)."""
    from bridge import standards as S
    monkeypatch.setattr(S, "GOLEM_DIR", str(tmp_path_factory.mktemp("std-golem")))
    S._cache.update(sig=None)


@pytest.fixture(autouse=True)
def _pas_les_vraies_donnees_dans_les_sauvegardes(monkeypatch, tmp_path_factory):
    """Les catégories de sauvegarde neuves (refonte I/O, 2026-10-09) lisent des dossiers du rack : patches, synthés,
    grooves, prises, standards, kits. Sans cette garde, un test qui fait `build("all")` zippait les VRAIES données de
    le mainteneur (64 Mo de Vital, 76 Mo de prises — vécu : 9 s pour un test). Un test qui veut des fichiers les pose lui-même."""
    from bridge import backup
    base = tmp_path_factory.mktemp("bk-data")
    for k in ("PATCHES_DIR", "VITAL_DIR", "GROOVES_DIR", "RECORDINGS_DIR", "STANDARDS_DIR", "KITS_DIR", "SAMPLES_DIR"):
        monkeypatch.setattr(backup, k, str(base / k.lower()))
    # les captures de l'utilisateur (backup_cli.captures_dir, docs/uninstall.md §9.5) : jamais celles du rack
    monkeypatch.setenv("GOLEM_NAM_TRAIN", str(base / "nam-train"))


@pytest.fixture(autouse=True)
def _pas_les_vrais_dossiers_de_chansons(monkeypatch, tmp_path_factory):
    """Ni le vrai `config/song-folders.json` ni l'index en mémoire d'un autre test (song-folders.md) : un test qui
    lirait la liste du mainteneur indexerait ses disques."""
    from bridge import song_folders
    monkeypatch.setattr(song_folders, "CFG", str(tmp_path_factory.mktemp("song-folders-cfg") / "song-folders.json"))
    monkeypatch.setattr(song_folders, "request_scan", lambda path=None: None)   # pas de passeur en tâche de fond
    song_folders.reset()
    yield
    song_folders.reset()


@pytest.fixture(autouse=True)
def _pas_le_vrai_dossier_surveille(monkeypatch, tmp_path_factory):
    """Ni le vrai `~/golem-inbox` ni le vrai `config/inbox.json` (lot 1.4, 2026-10-08) : un test qui démarre
    l'app lancerait la surveillance, et installerait ce que le mainteneur a déposé."""
    from bridge import inbox
    monkeypatch.setattr(inbox, "CFG", str(tmp_path_factory.mktemp("inbox-cfg") / "inbox.json"))
    box = str(tmp_path_factory.mktemp("golem-inbox"))
    monkeypatch.setattr(inbox, "inbox_dir", lambda: box)


@pytest.fixture(autouse=True)
def _pas_le_vrai_recu(monkeypatch, tmp_path_factory):
    """Aucun test n'écrit le VRAI reçu d'installation (~/.local/share/golem/install-receipt.json, 2026-10-15) :
    provision/airwindows.py, reaper-ini-setup.py et le bridge y notent ce qu'ils posent. Un fichier à part par
    test, qui n'existe pas tant que le test ne le crée pas."""
    monkeypatch.setenv("GOLEM_RECEIPT", str(tmp_path_factory.mktemp("receipt") / "install-receipt.json"))
