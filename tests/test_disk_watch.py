# SPDX-License-Identifier: GPL-3.0-or-later
"""La garde de place pendant une prise (bridge/disk.py Watch) : une écriture d'AILLEURS ne coupe pas la prise
(2026-10-27, tools/check-use.py : « 0 min » avec 18 Go libres), un disque vraiment plein l'arrête toujours."""
from bridge import disk


def _run(monkeypatch, frees, lanes=2):
    clock = {"t": 0.0}
    seq = iter(frees)
    cur = {"free": None}

    def free():
        return cur["free"]
    monkeypatch.setattr(disk, "_free_bytes", free)
    monkeypatch.setattr(disk.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(disk, "_lanes_planned", lambda: lanes)
    monkeypatch.setattr(disk, "conf", lambda: dict(disk.DEFAULTS))
    w, why = disk.Watch(), None
    for f in seq:
        cur["free"] = f
        why = w.tick() or why
        clock["t"] += 3
    return w, why


def test_une_rafale_d_ecriture_ailleurs_ne_coupe_pas_la_prise(monkeypatch):
    gb = 1e9
    # 18,4 Go libres, puis 1,6 Go écrits par un autre programme en quelques secondes
    w, why = _run(monkeypatch, [18.4 * gb, 18.0 * gb, 17.2 * gb, 16.8 * gb, 16.8 * gb, 16.8 * gb])
    assert why is None
    assert w.rate <= 3 * disk.rate_bps()
    assert disk.status(w.rate)["seconds"] > 60 * 60          # des heures, pas « 0 min »


def test_un_disque_vraiment_presque_plein_arrete_toujours(monkeypatch):
    gb = 1e9
    w, why = _run(monkeypatch, [6.3 * gb, 6.25 * gb, 6.2 * gb, 6.15 * gb, 6.1 * gb])
    assert why and why.startswith("recording stopped: only ")
    assert "Go" not in why                                    # en anglais : il s'affiche à l'écran


def test_les_refus_au_depart_sont_en_anglais(monkeypatch):
    monkeypatch.setattr(disk, "_free_bytes", lambda: 2e9)
    ok, why = disk.check_start()
    assert not ok and why.startswith("disk full")
