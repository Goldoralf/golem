# SPDX-License-Identifier: GPL-3.0-or-later
"""Les pistes de SERVICE ne s'installent que dans le projet du golem (reaper/Scripts/golem_project.lua, 2026-11-08).

golem_clock et golem_click tournent dans tout REAPER (__startup.lua) : ils créaient « MIDI Clock » et « Click » dans
n'importe quel projet ouvert — un projet vierge où l'on voulait rendre une basse recevait une piste sans envoi au
master, et l'instrument posé dessus restait muet. Les scripts sont joués tels quels sous lupa sur le REAPER factice
(tests/fakereaper.lua)."""
import json
from pathlib import Path
import shutil
import sys

import pytest

lupa = pytest.importorskip("lupa")

ROOT = Path(__file__).resolve().parents[1]
FAKE = (ROOT / "tests" / "fakereaper.lua").read_text(encoding="utf-8")
SCRIPTS = ("golem_paths.lua", "golem_project.lua", "golem_clock.lua", "golem_click.lua")


# l'OS de la machine qui fait tourner le banc : les scripts remplacent leurs fichiers d'état par os.rename, que Windows
# refuse sur une cible existante (golem_paths.replace ne contourne que si GetOS dit Windows)
HOST_OS = "Win64" if sys.platform == "win32" else "Other"


class Bench:
    def __init__(self, tmp, os_name=HOST_OS):
        self.root, self.res = tmp / "root", tmp / "res"
        for d in (self.root / "reaper/Scripts", self.root / "presets", self.root / "sets", self.res):
            d.mkdir(parents=True, exist_ok=True)
        for f in SCRIPTS:
            shutil.copy2(ROOT / "reaper/Scripts" / f, self.root / "reaper/Scripts" / f)
        (self.res / "golem-root.txt").write_text(str(self.root), encoding="utf-8")
        (self.res / "golem-runtime.txt").write_text(str(tmp / "rt"), encoding="utf-8")
        self.L = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.L.globals()
        g.FAKE_OS, g.FAKE_RESOURCE = os_name, str(self.res).replace("\\", "/")
        g.FAKE_INSTALLED = self.L.table_from(["JS:golem/midi-clock", "JS:golem/golem_click"])
        self.L.execute(FAKE)
        self.F = g.FAKE

    def open_project(self, path, proj):
        self.F.project_path, self.F.proj = path, proj

    def start(self, script):
        self.L.execute((self.root / "reaper/Scripts" / script).read_text(encoding="utf-8"))

    def ticks(self, n=3, step=1.0):
        for _ in range(n):
            self.F.now = self.F.now + step
            self.F.run_defers()

    def replace_project(self, path=""):
        """File ▸ New dans le même onglet : REAPER peut garder le même ReaProject* — pistes et ExtState neufs."""
        self.L.execute("FAKE.tracks = {}; for k in pairs(FAKE.ext) do if k:find('^proj:') then FAKE.ext[k] = nil end end")
        self.F.project_path = path

    def click_state(self):
        return json.loads((self.root / "presets" / ".click.json").read_text(encoding="utf-8"))

    def names(self):
        return [self.F.tracks[i + 1].name for i in range(len(self.F.tracks))]

    def mark(self):
        """Ce que golem_rig fait au rappel."""
        self.L.execute(f'dofile({str(self.root / "reaper/Scripts/golem_project.lua").replace(chr(92), "/")!r}).mark()')


@pytest.fixture
def bench(tmp_path):
    return Bench(tmp_path)


@pytest.mark.parametrize("script, track", [("golem_clock.lua", "MIDI Clock"), ("golem_click.lua", "Click")])
def test_un_projet_vierge_ne_recoit_aucune_piste(bench, script, track):
    bench.open_project("", "user#1")
    bench.start(script)
    bench.ticks()
    assert track not in bench.names()


@pytest.mark.parametrize("script, track", [("golem_clock.lua", "MIDI Clock"), ("golem_click.lua", "Click")])
def test_un_projet_range_ailleurs_ne_recoit_aucune_piste(bench, tmp_path, script, track):
    bench.open_project(str(tmp_path / "Music" / "bass-di.rpp"), "user#1")
    bench.start(script)
    bench.ticks()
    assert track not in bench.names()


@pytest.mark.parametrize("script, track", [("golem_clock.lua", "MIDI Clock"), ("golem_click.lua", "Click")])
def test_le_set_du_golem_recoit_sa_piste_des_le_demarrage(bench, script, track):
    bench.open_project(str(bench.root / "sets" / "golem-set.rpp"), "golem#1")
    bench.start(script)
    assert track in bench.names()


@pytest.mark.parametrize("script, track", [("golem_clock.lua", "MIDI Clock"), ("golem_click.lua", "Click")])
def test_premier_demarrage_la_piste_vient_au_rappel(bench, script, track):
    """REAPER lancé avec -new : projet sans chemin ; il devient le nôtre quand le bridge y rappelle la bank 00."""
    bench.open_project("", "golem#1")
    bench.start(script)
    bench.ticks()
    assert track not in bench.names()
    bench.mark()
    bench.ticks()
    assert bench.names().count(track) == 1


def test_le_chemin_windows_se_compare_sans_casse_ni_barres(tmp_path):
    b = Bench(tmp_path, os_name="Win64")
    win = str(b.root / "sets" / "golem-session-20261108.rpp").replace("/", "\\").upper()
    b.open_project(win, "golem#1")
    b.start("golem_clock.lua")
    assert "MIDI Clock" in b.names()


def test_le_temoin_audio_se_suspend_hors_du_projet(bench):
    """Le témoin `.clock.json` dit si le THREAD AUDIO avance (bridge/monitors.py) : hors du projet du golem il ne doit
    PAS publier de compteur figé — le bridge y lirait une carte perdue et relancerait l'audio."""
    bench.open_project("", "user#1")
    bench.start("golem_clock.lua")
    bench.ticks()
    assert not (bench.root / "presets" / ".clock.json").exists()
    bench.open_project(str(bench.root / "sets" / "golem-set.rpp"), "golem#1")
    bench.ticks()
    assert (bench.root / "presets" / ".clock.json").exists()


@pytest.mark.parametrize("path, coupe", [("", False), ("sets/golem-set.rpp", True)])
def test_le_metronome_natif_n_est_coupe_que_dans_le_projet_du_golem(bench, path, coupe):
    """Le click de golem coupe le métronome NATIF (double click pendant un backing) — pas celui d'un autre projet."""
    bench.L.execute("FAKE.toggles = {[40364] = 1}")
    bench.open_project(str(bench.root / path) if path else "", "p#1")
    bench.start("golem_click.lua")
    bench.ticks()
    assert (bench.F.toggles[40364] == 0) is coupe


def test_un_projet_vierge_qui_remplace_le_premier_set_ne_recoit_rien(bench):
    """Revue du 2026-11-08 : un verdict mis en cache sur (pointeur, chemin) disait encore « golem » au projet vierge
    qui remplaçait le premier set (même pointeur, chemin vide) — la piste revenait. Ticks à 30 Hz."""
    bench.open_project("", "tab#1")
    bench.start("golem_clock.lua")
    bench.mark()
    bench.ticks()
    assert "MIDI Clock" in bench.names()
    bench.replace_project("")
    bench.ticks(n=10, step=0.033)
    assert "MIDI Clock" not in bench.names()


def test_ouvrir_le_set_ne_rejoue_pas_son_click_sauve(bench):
    """Démarré sur un projet étranger, puis le set ouvert : son click_cmd sauvé (seq neuf, on=true) ne rallume pas
    le click — l'ouverture d'un set est toujours silencieuse."""
    bench.open_project("", "user#1")
    bench.start("golem_click.lua")
    bench.ticks()
    bench.open_project(str(bench.root / "sets" / "golem-set.rpp"), "golem#1")
    bench.L.execute('reaper.SetProjExtState(0, "golem", "click_cmd", \'{"seq":42,"op":"set","on":true}\')')
    bench.ticks()
    assert bench.click_state()["on"] is False
    assert bench.click_state()["present"] is True


def test_une_commande_neuve_allume_le_click_apres_l_adoption(bench):
    bench.open_project(str(bench.root / "sets" / "golem-set.rpp"), "golem#1")
    bench.start("golem_click.lua")
    bench.ticks()
    bench.L.execute('reaper.SetProjExtState(0, "golem", "click_cmd", \'{"seq":43,"op":"set","on":true}\')')
    bench.ticks()
    assert bench.click_state()["on"] is True


def test_le_temoin_attend_au_retour_dans_le_projet(bench):
    """Revue du 2026-11-08 : au retour d'un onglet étranger, le JSFX de l'onglet d'arrière-plan a pu s'arrêter ;
    publier tout de suite un `t` neuf avec les `ticks` d'avant ferait croire à un thread audio mort."""
    witness = bench.root / "presets" / ".clock.json"
    bench.open_project(str(bench.root / "sets" / "golem-set.rpp"), "golem#1")
    bench.start("golem_clock.lua")
    bench.ticks()
    bench.open_project("", "user#1")
    bench.ticks()
    witness.unlink()
    bench.open_project(str(bench.root / "sets" / "golem-set.rpp"), "golem#1")
    bench.ticks(n=4, step=0.25)
    assert not witness.exists()
    bench.ticks(n=2, step=1.0)
    assert witness.exists()
