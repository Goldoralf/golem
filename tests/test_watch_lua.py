# SPDX-License-Identifier: GPL-3.0-or-later
"""Le VEILLEUR (reaper/Scripts/golem_watch.lua), joué tel quel sous lupa sur le REAPER factice (tests/fakereaper.lua).
Chaque commande du bridge vers REAPER passe par lui : s'il casse, plus rien n'arrive au moteur. Audit des tests du
2026-11-09 : seul son aiguillage était vérifié, par recherche de texte. Ici on l'EXÉCUTE : commande résiduelle jetée
au démarrage, accusé de réception, gel après un rebuild, commandes légères qui passent pendant le gel, aiguillage
exact (le piège « golem_tuner »), remplacement par une instance plus récente, erreur qui ne tue pas la boucle.
golem_rig.lua et golem_apply.lua sont remplacés par des enregistreurs : leur propre comportement a ses tests."""
import json
import os
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ROOT = Path(__file__).resolve().parents[1]
FAKE = (ROOT / "tests" / "fakereaper.lua").read_text(encoding="utf-8")
WATCH = (ROOT / "reaper" / "Scripts" / "golem_watch.lua").read_text(encoding="utf-8")

# un script remplacé : il note la commande qu'il a reçue ; « rebuild » dans la commande = il dit avoir rebâti
RECORDER = """local root = io.open(reaper.GetResourcePath() .. "/golem-root.txt"):read("*l")
local cmd = io.open(root .. "/presets/.command.json"):read("*a")
local f = io.open(root .. "/presets/.calls.log", "a"); f:write("%s " .. cmd .. "\\n"); f:close()
if cmd:find("boom", 1, true) then error("plantage simulé") end
if cmd:find("rebuild", 1, true) then reaper.SetExtState("golem", "rig_rebuilt", "1", false) end
"""


class Watch:
    def __init__(self, tmp, residual=None):
        self.root, self.res = tmp / "root", tmp / "res"
        (self.root / "presets").mkdir(parents=True)
        (self.root / "reaper" / "Scripts").mkdir(parents=True)
        self.res.mkdir()
        for name, tag in (("golem_rig.lua", "rig"), ("golem_apply.lua", "apply")):
            (self.root / "reaper" / "Scripts" / name).write_text(RECORDER % tag, encoding="utf-8")
        (self.root / "reaper" / "Scripts" / "golem_fxinventory.lua").write_text("-- inventaire : rien ici\n")
        (self.res / "golem-root.txt").write_text(str(self.root), encoding="utf-8")
        if residual:
            self.cmd_file.write_text(json.dumps(residual), encoding="utf-8")
        self.L = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.L.globals()
        g.FAKE_OS, g.FAKE_RESOURCE = "Other", str(self.res).replace("\\", "/")
        g.FAKE_INSTALLED = self.L.table_from([])
        g.py_mkdir = lambda p: os.makedirs(p, exist_ok=True)
        self.L.execute(FAKE)
        self.F = g.FAKE
        self.L.execute(WATCH)

    cmd_file = property(lambda self: self.root / "presets" / ".command.json")

    def send(self, **cmd):
        self.cmd_file.write_text(json.dumps(cmd), encoding="utf-8")
        return self

    def tick(self, n=1):
        for _ in range(n):
            self.L.execute("local d = FAKE.defers; FAKE.defers = {}; for _, f in ipairs(d) do f() end")
        return self

    def wait(self, seconds):
        self.F.now = self.F.now + seconds
        return self

    def calls(self):
        p = self.root / "presets" / ".calls.log"
        return [ln.split(" ", 1) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def acked(self):
        p = self.root / "presets" / ".command-ack.json"
        return json.loads(p.read_text(encoding="utf-8"))["seq"] if p.exists() else None

    def proj(self, key):
        return self.L.eval(f'select(2, reaper.GetProjExtState(0, "golem", "{key}"))')

    def log(self):
        p = self.root / "presets" / ".watch.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""


def test_la_commande_residuelle_est_consommee_sans_etre_jouee(tmp_path):
    """La rejouer pendant le chargement du projet = chirurgie FX pendant que l'audio démarre (segfault, 2026-07-10)."""
    w = Watch(tmp_path, residual={"action": "rig_recall", "preset": "p", "seq": 7}).tick(3)
    assert w.acked() == 7 and w.calls() == []
    assert "démarré. surveille" in w.log()                         # la ligne qu'attend le bridge après une relance


def test_une_commande_est_jouee_une_fois_et_accusee(tmp_path):
    w = Watch(tmp_path).send(action="rig_recall", preset="p", seq=1).tick(3)
    assert w.acked() == 1
    assert [c[0] for c in w.calls()] == ["rig"]                     # une seule fois, malgré trois tours


def test_apres_un_rebuild_une_scene_attend_la_fin_du_gel(tmp_path):
    w = Watch(tmp_path).send(action="rig_recall", preset="p", seq=1).tick()
    w.send(action="scene_apply", preset="p", scene="B", seq=2).tick()
    assert w.acked() == 1 and len(w.calls()) == 1                   # gelée : ni jouée, ni accusée (le slot reste plein)
    w.wait(0.6).tick()
    assert w.acked() == 2 and [c[0] for c in w.calls()] == ["rig", "apply"]


def test_les_commandes_legeres_passent_pendant_le_gel(tmp_path):
    w = Watch(tmp_path).send(action="rig_recall", preset="p", seq=1).tick()
    w.send(action="tuner", on=True, seq=2).tick()
    assert w.acked() == 2 and w.proj("tuner_on") == "1"
    w.send(action="backing", op="play", seq=3).tick()
    assert w.acked() == 3 and json.loads(w.proj("backing_cmd"))["op"] == "play"
    assert len(w.calls()) == 1                                      # ni rig ni apply n'ont vu ces deux-là


def test_l_aiguillage_suit_l_action_jamais_une_sous_chaine(tmp_path):
    """Le piège du 2026-07-26 : {"action":"reload","script":"golem_tuner"} contient « tuner » et désarmait
    l'accordeur au lieu d'atteindre golem_apply."""
    w = Watch(tmp_path).send(action="reload", script="golem_tuner", seq=1).tick()
    assert [c[0] for c in w.calls()] == ["apply"] and w.proj("tuner_on") == ""
    w.send(action="stomp", block="dly", on=True, seq=2).tick()
    w.send(action="vst_list", seq=3).tick()
    assert [c[0] for c in w.calls()] == ["apply", "rig", "rig"]


def test_une_scene_qui_retombe_sur_un_rebuild_gele_comme_un_rappel(tmp_path):
    w = Watch(tmp_path).send(action="scene_apply", preset="p", scene="B", note="rebuild", seq=1).tick()
    w.send(action="stomp", block="dly", on=True, seq=2).tick()
    assert w.acked() == 1                                           # golem_rig a dit « rebâti » : même gel
    w.wait(0.6).tick()
    assert w.acked() == 2


def test_une_erreur_du_script_ne_tue_pas_le_veilleur(tmp_path):
    w = Watch(tmp_path).send(action="stomp", block="boom", seq=1).tick()
    assert "plantage simulé" in w.log()
    w.send(action="stomp", block="dly", on=True, seq=2).tick()
    assert w.acked() == 2 and len(w.calls()) == 2


def test_une_instance_plus_recente_remplace_la_premiere(tmp_path):
    w = Watch(tmp_path).tick()
    w.L.execute('reaper.SetExtState("golem", "watch_gen", "une-autre", false)')
    w.tick()
    assert "remplacé par une instance plus récente" in w.log()
    assert len(w.F.defers) == 0                                     # plus de defer : la boucle est morte
