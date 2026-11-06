# SPDX-License-Identifier: GPL-3.0-or-later


def test_la_premiere_boucle_recoit_tempo_et_mode_juste_avant_sa_commande():
    """docs/looper.md, addendum 2026-10-14 : le bridge pose GoleM Tempo / GoleM Mode (cmd+1, cmd+2) avant le départ
    et la fermeture de la 1re boucle — jamais pour une boucle suivante ni pour un stop."""
    calls = []

    class Osc:
        def set_fx_param(self, track, fx, param, v):
            calls.append((param, round(v, 6)))
            return True
    from bridge import looper as L
    c = L.LooperControl(Osc())
    c.set_addr({"track": 3, "fx": 0, "cmd_param": 2})
    calls.clear()                                         # la pose des volumes de boucle (adresse neuve)
    c.timing = lambda: {"bpm": 120, "beats": 4, "snap": False, "count_in": True}
    c.slot_tap(0)                                         # looper vide : départ de la 1re boucle
    assert calls[:2] == [(3, round(120 / 400, 6)), (4, round(42 / 999, 6))]   # 4 temps, décompte
    assert calls[2][0] == 2                               # puis la commande
    calls.clear()
    c.set_feedback([{"st": 2, "has": 1}, {"st": 0}, {"st": 0}, {"st": 0}], firstrec=1)
    c._opt.clear()
    c.timing = lambda: {"bpm": 120, "beats": 4, "snap": True, "count_in": False}
    c.slot_tap(0)                                         # fermeture de la 1re boucle : le calage
    assert calls[:2] == [(3, round(120 / 400, 6)), (4, round(41 / 999, 6))] and calls[2][0] == 2
    calls.clear()
    c.set_feedback([{"st": 1, "has": 1}, {"st": 0}, {"st": 0}, {"st": 0}], firstrec=0)
    c._opt.clear()
    c.slot_tap(1)                                         # une boucle SUIVANTE : rien d'autre que la commande
    assert [p for p, _ in calls] == [2]


def test_apres_un_rappel_l_adresse_perimee_est_ignoree_et_le_fichier_porte_le_calage(tmp_path, monkeypatch):
    """Vécu le 2026-10-14 : la piste du Looper passe de 21 à 20 au rappel ; le 1er appui partait vers l'ancien index.
    Au rappel, l'adresse est oubliée ; une publication d'AVANT est ignorée ; d'ici là, la commande passe par le
    fichier, avec le tempo et le mode."""
    import json, time
    from bridge import looper as L, config as C
    monkeypatch.setattr(C, "LOOPER_CMD_FILE", str(tmp_path / "cmd.json"))
    sent = []

    class Osc:
        def set_fx_param(self, *a):
            sent.append(a)
            return True
    c = L.LooperControl(Osc())
    c.set_addr({"track": 21, "fx": 0, "cmd_param": 2})
    c.forget_addr()
    sent.clear()
    c.set_addr({"track": 21, "fx": 0, "cmd_param": 2}, published_at=time.time() - 5)   # publiée AVANT le rappel
    c.timing = lambda: {"bpm": 100, "beats": 4, "snap": False, "count_in": True}
    c.slot_tap(0)
    assert sent == []                                           # rien vers l'ancien index
    doc = json.load(open(C.LOOPER_CMD_FILE))
    assert doc["notes"] == [36] and doc["cfg"] == {"tempo": 100.0, "mode": 42}
    c.set_addr({"track": 20, "fx": 0, "cmd_param": 2}, published_at=time.time() + 1)   # publiée APRÈS
    assert c._addr["track"] == 20
