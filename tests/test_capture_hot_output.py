# SPDX-License-Identifier: GPL-3.0-or-later
"""Une partie de capture au-dessus de 1,0 (une suite de pédales, Booster + Hex : crête 1,457, mesuré 2026-10-10).
Le rendu est en flottant : ce n'est pas une saturation. Il est ramené à −1 dBFS pour l'entraînement, et le gain est
RENDU par le réglage « output » du bloc pédale (non normalisé) — pas d'un bloc ampli, que la compile normalise."""
import json
from pathlib import Path

from bridge import plugin_capture as P

RECIPE = {"vendor": "Example Vendor", "full": {"label": "Full", "gear": "amp-cab", "off": {}},
          "split": {"parts": [{"id": "pedal", "label": "Pedal", "gear": "pedal", "block": "pedal-nam", "off": {}},
                              {"id": "head", "label": "Amp", "gear": "amp", "block": "amp-nam", "off": {}}]}}


def test_une_pedale_trop_chaude_est_ramenee_et_son_gain_rendu(monkeypatch, tmp_path):
    peaks = {"pedal": 1.457, "head": 1.2}
    chains = []
    monkeypatch.setattr(P, "recipe_for", lambda plugin: RECIPE)
    monkeypatch.setattr(P, "_live_state", lambda b: {"chunk": "C"})
    monkeypatch.setattr(P, "_live_params", lambda b: [])
    monkeypatch.setattr(P, "train_home", lambda: tmp_path)
    P.write_wav(tmp_path / "v3_0_0.wav", [0.5, -0.5] * 10)

    def render(plugin, chunk, off, src, pw, name, **k):
        part = Path(pw).name
        P.write_wav(Path(pw) / "target.wav", [peaks[part], -0.3] * 10)
        return {"peak": peaks[part], "set": []}
    monkeypatch.setattr(P, "render", render)

    def train(pw, epochs, progress=None):
        for f in ("capture.nam", "capture-v07.nam"):
            (Path(pw) / f).write_text("{}")
        return {"validation_esr": 0.001}
    monkeypatch.setattr(P, "train", train)
    monkeypatch.setattr(P, "playback_check", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(P, "test", lambda work, plugin, chunk, off, chain: chains.append(chain) or {"synth": {"null_db": -30}})
    monkeypatch.setattr(P, "install", lambda f, meta: {"id": meta["part"], "models": [{"id": meta["part"] + "-1"}]})
    P._job.clear()
    P._set(state="render", block="b", patch="p")
    P._worker("b", "VST3: Example Pedal Suite (Example Vendor)", "Cap", tmp_path / "work", "split", 1)
    job = P.status()
    assert job["state"] == "done", job.get("error")
    core = {c["type"]: c for c in job["result"]["core"]}
    assert core["pedal-nam"]["params"]["output"] == round(20 * __import__("math").log10(1.457 / 0.891), 1)   # +4,3 dB
    assert "params" not in core["amp-nam"]                                  # normalisé par la compile : rien à rendre
    y, _ = P.read_wav(tmp_path / "work" / "pedal" / "target.wav")
    assert max(abs(v) for v in y) < 0.999                                   # ce que NAM apprend est sous 1,0
    kinds = [k for k, _ in chains[0]]
    assert kinds == ["nam", "gain", "nam", "gain"]                          # la mesure joue la chaîne au bon niveau
