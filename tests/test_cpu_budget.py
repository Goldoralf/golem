# SPDX-License-Identifier: GPL-3.0-or-later
"""Le BUDGET CPU (docs/cpu-budget.md, lot 1) : l'estimation pure sur des plans faits à la main, les clés du profil
(architecture NAM, longueur d'IR, mono/stéréo), les routes du §9, et l'ordonnancement du banc (règle du repos,
reprise, re-mesure quand l'empreinte change) — REAPER jamais appelé : la mesure est remplacée par un faux.
`.venv/bin/python -m pytest tests/test_cpu_budget.py -q`"""
import json
import struct

import pytest

from bridge import cpu_bench as B
from bridge import cpu_budget as CB

MACHINE = {"cpu": "Test CPU", "cores": 8, "governor": "performance", "srate": 48000, "bsize": 192, "engine": "reaper"}
BUDGET = 4000.0                                    # 192 / 48000 s


def prof(**costs):
    """Un profil où chaque type coûte `avg` µs (pire = avg) à 192 échantillons. nam_standard -> clé « nam:standard »."""
    blocks = {}
    for k, us in costs.items():
        kind, _, var = k.partition("__")
        avg, worst = us if isinstance(us, tuple) else (us, us)
        blocks[CB.profile_key(kind.replace("_", "-"), var or None)] = {"avg_us": avg, "worst_us": worst, "bsize": 192}
    return {"machine": dict(MACHINE), "measured_at": "2026-11-16T10:00:00Z", "blocks": blocks}


def blk(bid, btype, on=True, variant=None, **kw):
    return {"id": bid, "type": btype, "bypass": not on, "_cpu": [[btype if btype not in CB.NAM_TYPES else "nam", variant]],
            "_label": kw.pop("label", bid), **kw}


def lane(lid, *tracks, stereo=False):
    return {"id": lid, "name": lid.title(), "stereo": stereo, "tracks": list(tracks)}


def main(*blocks):
    return {"role": "main", "blocks": list(blocks)}


# ── l'estimation pure ────────────────────────────────────────────────────────────────────────────────────────────
def test_une_lane_somme_ses_blocs_allumes_contre_un_coeur():
    plans = [("A", {"paths": [lane("guitar", main(blk("g", "gate"), blk("d", "delay"), blk("r", "reverb", on=False)))]})]
    est = CB.estimate(plans, prof(gate=400, delay=800, reverb=2000), MACHINE)
    assert est["budget_us"] == BUDGET
    assert est["lanes"][0]["pct"] == 30.0, "gate + delay = 1200 µs ; la reverb bypassée ne coûte rien"
    assert est["verdict"] == "ok" and est["worst"] == {"lane": "guitar", "scene": "A", "pct": 30.0}
    bl = {b["id"]: b for b in est["lanes"][0]["blocks"]}
    assert bl["r"]["pct"] == 50.0 and bl["r"]["on"] == {"A": False} and bl["r"]["measured"] is True
    assert est["fixes"] == [], "rien à proposer sous 60 %"
    assert est["machine"] == {"cpu": "Test CPU", "governor": "performance", "bsize": 192, "srate": 48000}


def test_la_scene_la_plus_lourde_fait_le_verdict_et_les_seuils():
    def plans(on_b):
        return [("A", {"paths": [lane("g", main(blk("x", "dist"), blk("y", "fuzz", on=False)))]}),
                ("B", {"paths": [lane("g", main(blk("x", "dist"), blk("y", "fuzz", on=on_b)))]})]
    p = prof(dist=2000, fuzz=1000)                 # A = 50 %, B = 75 %
    est = CB.estimate(plans(True), p, MACHINE)
    L = est["lanes"][0]
    assert L["by_scene"] == {"A": 50.0, "B": 75.0} and L["worst_scene"] == "B" and est["verdict"] == "tight"
    assert CB.estimate(plans(False), p, MACHINE)["verdict"] == "ok"
    est = CB.estimate(plans(True), prof(dist=2000, fuzz=1300), MACHINE)
    assert est["worst"]["pct"] == 82.5 and est["verdict"] == "red"
    assert CB.THRESHOLDS == {"ok": 60.0, "tight": 80.0}


def test_un_split_court_sur_la_branche_la_plus_lourde_et_le_merge_attend():
    """pré + max(branches) + merge : les branches tournent en parallèle, le travail total les somme."""
    tracks = [{"role": "pre", "blocks": [blk("g", "gate")]},
              {"role": "merge", "blocks": [blk("rv", "reverb")]},
              {"role": "branch", "blocks": [blk("a1", "dist"), blk("a2", "eq")]},
              {"role": "branch", "blocks": [blk("b1", "fuzz")]}]
    est = CB.estimate([("A", {"paths": [lane("g", *tracks)]})], prof(gate=200, reverb=600, dist=1000, eq=200, fuzz=1600), MACHINE)
    assert est["lanes"][0]["pct"] == pytest.approx((200 + 1600 + 600) / BUDGET * 100, abs=0.1)
    assert est["total_cores"] == pytest.approx((200 + 600 + 1000 + 200 + 1600) / BUDGET, abs=0.01)


def test_deux_lanes_le_verdict_vient_de_la_plus_chargee_et_le_total_en_coeurs():
    plans = [("A", {"paths": [lane("guitar", main(blk("a", "dist"))), lane("voice", main(blk("v", "comp")))]})]
    est = CB.estimate(plans, prof(dist=2800, comp=2000), MACHINE)
    assert est["worst"]["lane"] == "guitar" and est["verdict"] == "tight"
    assert est["total_cores"] == pytest.approx(1.2)
    assert est["cores"] == 8


def test_un_bloc_non_mesure_rend_inconnu_sauf_si_le_mesure_est_deja_rouge():
    plans = [("A", {"paths": [lane("g", main(blk("a", "dist"), blk("z", "mystery")))]})]
    est = CB.estimate(plans, prof(dist=1000), MACHINE)
    assert est["verdict"] == "unknown" and est["lanes"][0]["pct"] == 25.0
    z = next(b for b in est["lanes"][0]["blocks"] if b["id"] == "z")
    assert z["measured"] is False and z["pct"] is None
    est = CB.estimate(plans, prof(dist=3600), MACHINE)
    assert est["verdict"] == "red", "90 % déjà mesurés : rouge, quoi que coûte le reste"
    # un bloc non mesuré mais ÉTEINT dans toutes les scènes ne rend pas inconnu
    plans = [("A", {"paths": [lane("g", main(blk("a", "dist"), blk("z", "mystery", on=False)))]})]
    assert CB.estimate(plans, prof(dist=1000), MACHINE)["verdict"] == "ok"


def test_un_bloc_gratuit_compte_zero_et_reste_mesure():
    free = {"id": "w", "type": "whammy-dt", "bypass": False, "_cpu": [], "_label": "Whammy"}
    est = CB.estimate([("A", {"paths": [lane("g", main(free))]})], prof(), MACHINE)
    assert est["verdict"] == "ok" and est["lanes"][0]["blocks"][0] == {
        "id": "w", "type": "whammy-dt", "label": "Whammy", "pct": 0.0, "stereo": False, "measured": True, "on": {"A": True}}


def test_le_buffer_d_aujourd_hui_se_corrige_au_prorata_des_echantillons():
    p = prof(dist=(1000, 1200))                    # mesuré à 192 : 1000 µs, pire 1200
    assert CB.entry_us(p["blocks"]["dist|stereo"], 192) == 1200
    assert CB.entry_us(p["blocks"]["dist|stereo"], 384) == 2200, "le calcul double, l'écart au pire tour reste"
    est = CB.estimate([("A", {"paths": [lane("g", main(blk("a", "dist")))]})], p, dict(MACHINE, bsize=384))
    assert est["budget_us"] == 8000.0 and est["lanes"][0]["pct"] == 27.5


def test_mono_se_replie_sur_la_mesure_stereo():
    p = prof(dist=1000)
    assert CB.lookup(p, "dist", None, stereo=False) is p["blocks"]["dist|stereo"]
    assert CB.profile_key("nam", "feather", False) == "nam:feather|mono"
    assert CB.profile_key("gate") == "gate|stereo"


# ── les propositions ─────────────────────────────────────────────────────────────────────────────────────────────
def test_les_propositions_dans_l_ordre_avec_leur_gain():
    m = dict(MACHINE, governor="powersave")
    tracks = [main(blk("g", "gate"), blk("amp", "amp", variant="standard", ref="19", model=1, _variant="standard"),
                   blk("ch", "chorus", params={"mix": 0}, _silent=True), blk("d1", "delay", params={"t": 1}),
                   blk("d2", "delay", params={"t": 1}))]
    p = prof(gate=200, nam__standard=1800, nam__feather=600, chorus=400, delay=(500, 700))
    alts = {"amp": [{"ref": "19", "model": 2, "variant": "feather", "name": "Twin feather"},
                    {"ref": "19", "model": 3, "variant": "nano", "name": "Twin nano (not measured)"}]}
    est = CB.estimate([("A", {"paths": [lane("g", *tracks)]})], p, m, alts, (128, 192, 256, 384))
    assert est["verdict"] == "red"                 # 200 + 1800 + 400 + 700 + 700 = 3800 -> 95 %
    kinds = [f["id"].split(":")[0] for f in est["fixes"]]
    assert kinds == ["perf-mode", "turn-off", "turn-off", "lighter-capture", "buffer"], "pas de « too-heavy » : les gains suffisent"
    by = {f["id"]: f for f in est["fixes"]}
    assert by["perf-mode"]["action"] == {"kind": "perf-mode", "on": True} and by["perf-mode"]["gain_pct"] is None
    off = [f for f in est["fixes"] if f["id"].startswith("turn-off")]
    assert {f["action"]["block"] for f in off} == {"ch", "d2"}, "le chorus à mix 0, et le second delay identique"
    assert off[0]["gain_pct"] == 17.5 and off[0]["action"]["block"] == "d2", "le plus gros gain d'abord"
    lc = by["lighter-capture:g:amp"]
    assert lc["action"] == {"kind": "lighter-capture", "lane": "g", "block": "amp", "ref": "19", "model": 2, "variant": "feather"}
    assert lc["gain_pct"] == 30.0, "1800 -> 600 µs : une architecture non mesurée n'est jamais proposée"
    buf = by["buffer:256"]
    assert buf["action"] == {"kind": "buffer", "size": 256, "latency_ms": 2.7}
    assert buf["gain_pct"] == pytest.approx(400 / 4000 * 100 - 400 / (256 / 48000 * 1e6) * 100, abs=0.1)


def test_pas_de_mode_performance_quand_le_gouverneur_y_est_deja():
    plans = [("A", {"paths": [lane("g", main(blk("a", "dist")))]})]
    est = CB.estimate(plans, prof(dist=3000), MACHINE)
    assert est["verdict"] == "tight" and not any(f["id"] == "perf-mode" for f in est["fixes"])
    est = CB.estimate(plans, prof(dist=3000), dict(MACHINE, governor="powersave"))
    assert est["fixes"][0]["id"] == "perf-mode"


def test_trop_lourd_quand_rien_ne_suffit():
    plans = [("A", {"paths": [lane("g", main(blk("a", "dist"), blk("b", "fuzz")))]})]
    est = CB.estimate(plans, prof(dist=3000, fuzz=2000), dict(MACHINE, bsize=512, srate=48000))
    th = est["fixes"][-1]
    assert th["id"] == "too-heavy:g" and th["action"] is None and "Dist" not in th["sub"] and "a weighs most" in th["sub"]


# ── la mesure -> µs par buffer ─────────────────────────────────────────────────────────────────────────────────────
def test_per_buffer_soustrait_la_ligne_de_base_et_garde_le_pire():
    # 10 s à 48 kHz, buffers de 192 : 2500 buffers
    m = CB.per_buffer([1.5, 1.6, 1.55], [0.5, 0.52, 0.51], 10.0, 48000, 192)
    assert m["avg_us"] == pytest.approx((1.55 - 0.51) / 2500 * 1e6, abs=0.01)
    assert m["worst_us"] == pytest.approx((1.6 - 0.5) / 2500 * 1e6, abs=0.01)
    with pytest.raises(ValueError):
        CB.per_buffer([10.2], [9.8], 10.0, 48000, 192)      # rendu en temps réel : la mesure ne vaut rien


# ── les clés : architecture NAM, longueur d'IR ─────────────────────────────────────────────────────────────────────
def _nam(path, arch, layers=None, cfg=None):
    doc = {"version": "0.5.4", "architecture": arch, "config": cfg or {"layers": [
        {"channels": c, "head_size": h, "dilations": [1] * n} for c, h, n in (layers or [])]}, "weights": [0.0]}
    path.write_text(json.dumps(doc))
    return str(path)


def test_la_variante_nam_se_lit_dans_l_architecture(tmp_path):
    assert CB.nam_variant(_nam(tmp_path / "s.nam", "WaveNet", [(16, 8, 10), (8, 1, 10)])) == "standard"
    assert CB.nam_variant(_nam(tmp_path / "l.nam", "WaveNet", [(12, 6, 7), (6, 1, 13)])) == "lite"
    assert CB.nam_variant(_nam(tmp_path / "f.nam", "WaveNet", [(8, 4, 7), (4, 1, 13)])) == "feather"
    assert CB.nam_variant(_nam(tmp_path / "n.nam", "WaveNet", [(4, 2, 7), (2, 1, 13)])) == "nano"
    assert CB.nam_variant(_nam(tmp_path / "a2.nam", "SlimmableContainer", cfg={"submodels": []})) == "a2"
    assert CB.nam_variant(_nam(tmp_path / "x.nam", "LSTM", cfg={"num_layers": 1, "hidden_size": 24})) == "lstm-1x24"
    v = CB.nam_variant(_nam(tmp_path / "c.nam", "WaveNet", [(32, 8, 20), (8, 1, 20)]))
    assert v.startswith("wavenet-") and v == CB.nam_variant(_nam(tmp_path / "c2.nam", "WaveNet", [(32, 8, 20), (8, 1, 20)]))
    (tmp_path / "bad.nam").write_text("{not json")
    assert CB.nam_variant(str(tmp_path / "bad.nam")) is None


def _wav(path, frames, rate=48000, ch=1, bits=24):
    data = b"\0" * (frames * ch * bits // 8)
    fmt = struct.pack("<HHIIHH", 1, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"LIST" + struct.pack("<I", 4) + b"INFO" \
        + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def test_la_classe_d_une_ir_suit_sa_longueur(tmp_path):
    assert CB.wav_ms(_wav(tmp_path / "a.wav", 2048)) == pytest.approx(42.67, abs=0.01)
    assert CB.ir_bucket(CB.wav_ms(_wav(tmp_path / "b.wav", 2048))) == "50ms"
    assert CB.ir_bucket(CB.wav_ms(_wav(tmp_path / "c.wav", 9600, rate=48000, ch=2, bits=16))) == "200ms"
    assert CB.ir_bucket(CB.wav_ms(_wav(tmp_path / "d.wav", 44100 * 6, rate=44100))) == "long"
    assert CB.ir_bucket(None) is None
    (tmp_path / "x.wav").write_bytes(b"nope")
    assert CB.wav_ms(str(tmp_path / "x.wav")) is None


def test_les_composants_d_un_bloc(tmp_path):
    nam = _nam(tmp_path / "f.nam", "WaveNet", [(8, 4, 7), (4, 1, 13)])
    ir = _wav(tmp_path / "cab.wav", 4800)
    assert CB.components({"type": "amp", "ref": "x", "file": nam}, path_has_cab=False) == [["nam", "feather"]]
    # une TÊTE sans baffle en aval reçoit le baffle par défaut que la compile lui fond
    head = CB.components({"type": "amp-nam", "ref": "x", "file": nam}, False, lambda b: False, ir)
    assert head == [["nam", "feather"], ["cab", "100ms"]]
    assert CB.components({"type": "amp-nam", "ref": "x", "file": nam}, True, lambda b: False, ir) == [["nam", "feather"]]
    assert CB.components({"type": "cab", "ref": "x", "file": ir}, True) == [["cab", "100ms"]]
    assert CB.components({"type": "pedal-nam", "ref": "x"}, True) == [["nam", None]], "capture non résolue : non mesurable"
    assert CB.components({"type": "whammy-dt"}, True) == []
    assert CB.components({"type": "gate"}, True) == [["gate", None]]
    assert CB.components({"type": "vst-host", "plugin": "VST3: Fancy Verb (Acme)"}, True) == [["vst-host", "fancy-verb-acme"]]
    assert CB._silent({"params": {"mix": 0}}, {"params": [{"id": "mix", "min": 0, "max": 100, "unit": "%"}]}) is True
    assert CB._silent({"params": {"wet": -70}}, {"params": [{"id": "wet", "min": -120, "max": 6, "unit": "dB"}]}) is True
    assert CB._silent({"params": {"mix": 30}}, {"params": [{"id": "mix", "min": 0, "max": 100}]}) is False


# ── le banc : ordonnancement, sans REAPER ──────────────────────────────────────────────────────────────────────────
@pytest.fixture
def bench(tmp_path, monkeypatch):
    from bridge import config as C, preview as PV
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(B, "machine_now", lambda: dict(MACHINE))
    tg = [{"key": B.SYSTEM_KEY, "kind": "_system", "variant": None, "label": "empty lane", "block": None, "hash": "s1"},
          {"key": "gate|stereo", "kind": "gate", "variant": None, "label": "Gate", "block": {"type": "gate"}, "hash": "g1"},
          {"key": "nam:feather|stereo", "kind": "nam", "variant": "feather", "label": "NAM feather",
           "block": {"type": "amp"}, "hash": "n1"}]
    state = {"targets": tg}
    monkeypatch.setattr(B, "targets", lambda fresh=False: [dict(t) for t in state["targets"]])
    monkeypatch.setattr(PV, "rendering", lambda: False)
    monkeypatch.setattr(B, "_ST", dict(B._ST, state="idle", running=False))
    return state


def _measure(log, raw=None):
    raw = raw or {"_system|stereo": 50.0, "gate|stereo": 250.0, "nam:feather|stereo": 1050.0}

    def m(t, machine, seq):
        log.append(t["key"])
        return {"avg_us": raw[t["key"]], "worst_us": raw[t["key"]] + 20, "nfx": 1 if t["key"] == B.SYSTEM_KEY else 2,
                "srate": 48000, "bsize": 192}
    return m


def test_le_banc_mesure_la_lane_vide_d_abord_et_la_soustrait(bench):
    log, restored = [], []
    st = B.run(measure=_measure(log), busy_fn=lambda: None, restore=lambda: restored.append(1))
    assert st["state"] == "done" and st["done"] == 3 and st["total"] == 3
    assert log == [B.SYSTEM_KEY, "gate|stereo", "nam:feather|stereo"]
    p = B.load_profile()
    assert p["blocks"]["gate|stereo"]["avg_us"] == 200.0 and p["blocks"]["gate|stereo"]["worst_us"] == 220.0
    assert p["blocks"]["nam:feather|stereo"]["hash"] == "n1" and p["machine"]["bsize"] == 192
    assert restored == [1], "le moteur est rendu à la fin"
    # tout est à jour : rien ne se re-mesure
    log.clear()
    assert B.run(measure=_measure(log), busy_fn=lambda: None, restore=lambda: None)["state"] == "done" and log == []


def test_le_banc_attend_le_repos_et_reprend_ou_il_s_est_arrete(bench):
    log, calls = [], {"n": 0}

    def busy():
        calls["n"] += 1
        return "in use (screen, 3 s ago)" if calls["n"] == 3 else None
    st = B.run(measure=_measure(log), busy_fn=busy, restore=lambda: None)
    assert st["state"] == "waiting" and st["waiting_for"] == "in use (screen, 3 s ago)"
    assert log == [B.SYSTEM_KEY, "gate|stereo"], "deux mesures écrites avant le geste"
    log.clear()
    st = B.run(measure=_measure(log), busy_fn=lambda: None, restore=lambda: None)
    assert log == ["nam:feather|stereo"] and st["state"] == "done", "il reprend là où il s'était arrêté"


def test_un_plugin_change_d_empreinte_et_seul_lui_se_re_mesure(bench):
    B.run(measure=_measure([]), busy_fn=lambda: None, restore=lambda: None)
    bench["targets"][1]["hash"] = "g2"                     # golem-fx publie un nouveau binaire du gate
    log = []
    B.run(measure=_measure(log), busy_fn=lambda: None, restore=lambda: None)
    assert log == ["gate|stereo"] and B.load_profile()["blocks"]["gate|stereo"]["hash"] == "g2"


def test_une_autre_machine_re_mesure_tout_et_invalide_les_mesures(bench, monkeypatch):
    B.run(measure=_measure([]), busy_fn=lambda: None, restore=lambda: None)
    monkeypatch.setattr(B, "machine_now", lambda: dict(MACHINE, bsize=256))
    assert len(B.pending(B.load_profile(), B.targets(), B.machine_now())) == 3, "un autre buffer : tout se refait"
    assert B.usable_profile(None, dict(MACHINE, bsize=256))["blocks"], "…mais l'estimation garde les mesures au prorata"
    assert B.usable_profile(None, dict(MACHINE, cpu="Other CPU"))["blocks"] == {}, "un autre processeur : plus rien ne vaut"


def test_un_echec_n_est_pas_retente_avant_que_l_empreinte_change(bench):
    log = []

    def m(t, machine, seq):
        log.append(t["key"])
        if t["key"] == "gate|stereo":
            raise B.BenchError("the plugin did not load in the bench lane")
        return _measure([])(t, machine, seq)
    B.run(measure=m, busy_fn=lambda: None, restore=lambda: None)
    assert B.load_profile()["failed"]["gate|stereo"]["reason"].startswith("the plugin did not load")
    log.clear()
    B.run(measure=m, busy_fn=lambda: None, restore=lambda: None)
    assert log == []
    bench["targets"][1]["hash"] = "g2"
    B.run(measure=m, busy_fn=lambda: None, restore=lambda: None)
    assert log == ["gate|stereo"]


def test_un_rappel_pendant_la_mesure_arrete_le_banc_sans_rien_ecrire(bench):
    def m(t, machine, seq):
        if t["key"] == "gate|stereo":
            raise B.Interrupted("the rig was recalled during the measure")
        return _measure([])(t, machine, seq)
    st = B.run(measure=m, busy_fn=lambda: None, restore=lambda: None)
    assert st["state"] == "waiting" and "gate|stereo" not in (B.load_profile().get("failed") or {})


def test_le_veilleur_ne_lance_rien_quand_le_rack_est_pris(bench, monkeypatch):
    ran = []
    monkeypatch.setattr(B, "busy", lambda manual=False: "a take is recording")
    monkeypatch.setattr(B, "run", lambda **kw: ran.append(kw))
    assert B.idle_tick() == "a take is recording" and ran == []
    assert B._ST["state"] == "waiting" and B._ST["waiting_for"] == "a take is recording"
    monkeypatch.setattr(B, "busy", lambda manual=False: None)
    assert B.idle_tick() is None and ran == [{"manual": False}]


def test_la_regle_manuelle_ignore_les_dix_minutes(monkeypatch):
    from bridge import reamp, preview as PV
    from bridge.state import state
    seen = []
    monkeypatch.setattr(reamp, "busy_reason", lambda idle=True: seen.append(idle) or None)
    monkeypatch.setattr(PV, "rendering", lambda: False)
    monkeypatch.setattr(state, "reaper_running", True)
    B.busy(manual=True)
    B.busy(manual=False)
    assert seen == [False, True]


def test_le_patch_de_banc_est_une_lane_coupee_qui_ne_porte_que_le_bloc():
    doc = B.bench_doc({"id": "b1", "type": "gate", "params": {"thresh": -50}})
    assert doc["lanes"][0]["chain"] == {"chain": [{"id": "b1", "type": "gate", "params": {"thresh": -50}}]}
    assert doc["scenes"][0]["lanes"][B.LANE_ID]["mute"] is True, "rien ne sort aux baffles pendant le banc"
    assert B.bench_doc(None)["lanes"][0]["chain"] == {"chain": []}


# ── les routes (§9) ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client(bench, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bridge import routes_cpu as R
    p = prof(gate=400, delay=800, nam__feather=1200)
    B.save_profile(dict(p, blocks={**p["blocks"], B.SYSTEM_KEY: {"avg_us": 50, "worst_us": 60, "bsize": 192}}))
    plans = [("A", {"paths": [lane("guitar", main(blk("g", "gate"), blk("amp", "amp", variant="feather"), blk("d", "delay", on=False)))]}),
             ("B", {"paths": [lane("guitar", main(blk("g", "gate"), blk("amp", "amp", variant="feather"), blk("d", "delay")))]})]
    docs = {"p1": {"id": "p1", "scenes": [{"id": "A"}, {"id": "B"}]}, "p2": {"id": "p2"}}
    monkeypatch.setattr(R, "_load", lambda pid: docs.get(pid or "sandbox", docs["p1"] if pid == "sandbox" else None))
    monkeypatch.setattr(CB, "scene_plans", lambda preset: json.loads(json.dumps(plans if preset["id"] == "p1" else plans[:1])))
    monkeypatch.setattr(CB, "lighter_alternatives", lambda plans: {})
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app)


def test_route_profile(client):
    r = client.get("/api/cpu/profile")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"machine", "measured_at", "budget_us", "blocks", "calibration"}
    assert set(d["machine"]) == {"cpu", "cores", "governor", "srate", "bsize", "engine"} and d["budget_us"] == BUDGET
    assert d["blocks"]["gate|stereo"] == {"avg_us": 400, "worst_us": 400, "pct": 10.0, "at": None, "hash": None}
    assert B.SYSTEM_KEY not in d["blocks"]
    assert set(d["calibration"]) == {"state", "done", "total", "current", "waiting_for", "error"}


def test_route_estimate_et_estimate_many(client):
    d = client.get("/api/cpu/estimate?preset=p1").json()
    assert set(d) >= {"verdict", "budget_us", "cores", "total_cores", "worst", "lanes", "fixes", "machine", "measured_at"}
    assert d["worst"] == {"lane": "guitar", "scene": "B", "pct": 60.0} and d["verdict"] == "ok"
    L = d["lanes"][0]
    assert set(L) >= {"id", "name", "pct", "worst_scene", "by_scene", "blocks"}
    assert set(L["blocks"][0]) == {"id", "type", "label", "pct", "stereo", "measured", "on"}
    assert client.get("/api/cpu/estimate?preset=nope").status_code == 404
    many = client.get("/api/cpu/estimate-many?ids=p1,p2,nope").json()
    assert many["p1"] == {"verdict": "ok", "worst": {"lane": "guitar", "scene": "B", "pct": 60.0}}
    assert many["p2"]["worst"]["pct"] == 40.0 and many["nope"]["verdict"] == "unknown"


def test_route_block(client):
    assert client.get("/api/cpu/block?type=gate&stereo=false").json() == \
        {"pct": 10.0, "avg_us": 400, "worst_us": 400, "measured": True}
    assert client.get("/api/cpu/block?type=amp&variant=nam:feather").json()["pct"] == 30.0
    assert client.get("/api/cpu/block?type=nam&variant=feather").json()["measured"] is True
    assert client.get("/api/cpu/block?type=fuzz").json() == {"pct": None, "avg_us": None, "worst_us": None, "measured": False}
    assert client.get("/api/cpu/block").status_code == 400


def test_route_swap(client, monkeypatch):
    from bridge import routes_cpu as R
    calls = []

    def plans_of(preset):
        swapped = any(b.get("ref") == "light" for b in CB._walk_typed(preset, "amp"))
        calls.append(swapped)
        v = "nano" if swapped else "feather"
        return [("A", {"paths": [lane("guitar", main(blk("g", "gate"), blk("amp", "amp", variant=v)))]})]
    monkeypatch.setattr(CB, "scene_plans", plans_of)
    p = prof(gate=400, nam__feather=1200, nam__nano=400)
    B.save_profile(dict(p, blocks={**p["blocks"], B.SYSTEM_KEY: {"avg_us": 50, "worst_us": 60, "bsize": 192}}))
    doc = {"id": "p1", "lanes": [{"chain": {"chain": [{"id": "amp", "type": "amp", "ref": "heavy"}]}}]}
    monkeypatch.setattr(R, "_load", lambda pid: json.loads(json.dumps(doc)))
    d = client.get("/api/cpu/swap?preset=p1&block=amp&ref=light&model=7").json()
    assert d == {"lane": "guitar", "before_pct": 40.0, "after_pct": 20.0, "verdict_after": "ok", "lighter": None}
    assert calls == [False, True]
    assert client.get("/api/cpu/swap?preset=p1&block=zz&ref=light").status_code == 404


def test_route_calibrate_refusee_quand_le_rack_est_pris(client, monkeypatch):
    monkeypatch.setattr(B, "busy", lambda manual=False: "a take is recording")
    r = client.post("/api/cpu/calibrate", json={})
    assert r.status_code == 409 and "a take is recording" in r.json()["error"]
    assert client.post("/api/cpu/calibrate", json={"types": "gate"}).status_code == 400
    started = []
    monkeypatch.setattr(B, "busy", lambda manual=False: None)
    monkeypatch.setattr(B, "run", lambda **kw: started.append(kw))
    r = client.post("/api/cpu/calibrate", json={"force": True, "types": ["gate"]})
    assert r.status_code == 200 and r.json()["ok"] is True
    B._thread["run"].join(2)
    assert started == [{"manual": True, "force": True, "types": ["gate"]}]


def test_auth_lire_demande_un_appareil_appaire_et_calibrer_un_admin(monkeypatch):
    from bridge import auth
    from tests.test_audit_2026_10_15_security import DEVS, Req
    monkeypatch.setattr(auth, "_device_by_token", lambda t: DEVS.get(t))
    for path in ("/api/cpu/estimate", "/api/cpu/profile", "/api/cpu/estimate-many", "/api/cpu/block", "/api/cpu/swap"):
        assert auth.allowed_http(Req("GET", path)) is False, path
        assert auth.allowed_http(Req("GET", path, "musician")) is True, path
    assert auth.allowed_http(Req("POST", "/api/cpu/calibrate", "musician")) is False
    assert auth.allowed_http(Req("POST", "/api/cpu/calibrate", "admin")) is True
    assert auth.allowed_http(Req("POST", "/api/cpu/calibrate", client="127.0.0.1", host="localhost:8770")) is True


def test_le_fait_health_dit_l_age_du_profil(bench):
    level, text = B.fact()
    assert level == "wait" and text.startswith("not calibrated yet")
    B.run(measure=_measure([]), busy_fn=lambda: None, restore=lambda: None)
    level, text = B.fact()
    assert level == "ok" and text == "2 blocks measured " + B.load_profile()["measured_at"][:10] + " on this machine"


def test_une_frequence_que_la_machine_ne_dit_pas_ne_fait_pas_tout_re_mesurer(bench, monkeypatch):
    """Sous Linux, reaper.ini peut taire la fréquence : REAPER la rapporte au banc (48000). L'empreinte gardée est celle
    que le banc relira — sinon chaque passage du veilleur re-mesurerait tout, pour toujours."""
    monkeypatch.setattr(B, "machine_now", lambda: dict(MACHINE, srate=None))
    B.run(measure=_measure([]), busy_fn=lambda: None, restore=lambda: None)
    assert B.load_profile()["machine"]["srate"] == 48000, "la fréquence rapportée sert au budget"
    assert B.pending(B.load_profile(), B.targets(), B.machine_now()) == []


def test_reaper_muet_n_est_pas_un_echec(bench):
    def m(t, machine, seq):
        if t["key"] == "gate|stereo":
            raise B.Interrupted("REAPER did not answer the bench render")
        return _measure([])(t, machine, seq)
    st = B.run(measure=m, busy_fn=lambda: None, restore=lambda: None)
    assert st["state"] == "waiting" and not B.load_profile().get("failed")
    assert [t["key"] for t in B.pending(B.load_profile(), B.targets(), B.machine_now())] == ["gate|stereo", "nam:feather|stereo"]


# ── 2026-11-17 : sous le Golem Engine, un bloc éteint peut coûter, et le moteur a une part fixe ──────────────
def _profile_engine():
    blk = lambda avg, off=None: dict({"avg_us": avg, "worst_us": avg, "bsize": 192, "srate": 48000},
                                     **({"off_us": off} if off is not None else {}))
    return {"machine": {"bsize": 192, "srate": 48000},
            "blocks": {CB.profile_key("reverb"): blk(100.0, 120.0), CB.profile_key("chorus"): blk(80.0, 0.0),
                       CB.profile_key("delay"): blk(40.0)},
            "engine_idle": {"pct": 20.0, "us": 800.0}}


def _plan_engine(mute_branch=False):
    b = lambda t, off: {"id": t, "type": t, "bypass": off, "_cpu": [[t, None]]}
    return {"paths": [{"id": "g", "name": "G", "tracks": [
        {"role": "main", "blocks": [b("reverb", True), b("chorus", True), b("delay", False)]},
        {"role": "branch", "mute": mute_branch, "blocks": [dict(b("reverb", True), id="r2")]}]}]}


def test_un_bloc_eteint_qui_tourne_encore_compte_et_la_part_fixe_du_moteur_aussi():
    prof = _profile_engine()
    e = CB.estimate([("A", _plan_engine())], prof, {"bsize": 192, "srate": 48000})
    # delay allumé 40 + reverb éteinte 120 (chorus éteint : 0) + la branche (reverb éteinte 120) + part fixe 800, sur 4000
    assert e["lanes"][0]["by_scene"]["A"] == round((40 + 120 + 120 + 800) / 4000 * 100, 1) and e["engine_pct"] == 20.0
    # une branche MUETTE est endormie par le moteur : ses blocs éteints ne coûtent rien
    e = CB.estimate([("A", _plan_engine(mute_branch=True))], prof, {"bsize": 192, "srate": 48000})
    assert e["lanes"][0]["by_scene"]["A"] == round((40 + 120 + 800) / 4000 * 100, 1)


def test_sans_mesure_eteinte_ni_part_fixe_rien_ne_change():
    prof = _profile_engine()
    prof.pop("engine_idle")
    for v in prof["blocks"].values():
        v.pop("off_us", None)
    e = CB.estimate([("A", _plan_engine())], prof, {"bsize": 192, "srate": 48000})
    assert e["lanes"][0]["by_scene"]["A"] == 1.0 and e["engine_pct"] is None      # REAPER : le seul delay, 40/4000


def test_la_frequence_vient_du_moteur_actif_d_abord(monkeypatch):
    """Sous Windows avec le Golem Engine, la télémétrie de REAPER manque : la fréquence de l'empreinte venait à None
    (puis pouvait basculer et refaire toute la calibration). Le moteur actif la dit lui-même."""
    from bridge import engine

    class _Eng:
        def audio(self):
            return {"rate": 44100, "buffer": 256}
    monkeypatch.setattr(engine, "get", lambda: _Eng())
    assert B._srate() == 44100
