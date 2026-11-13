# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrat du catalogue FX Windows, sans dépendance à REAPER."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.linux = {
            effect["type"]: effect
            for effect in json.loads(
                (ROOT / "library/catalog/effects.json").read_text(encoding="utf-8")
            )["effects"]
        }
        cls.windows = json.loads(
            (ROOT / "library/catalog/effects-windows.json").read_text(encoding="utf-8")
        )["effects"]

    def test_overrides_reference_real_blocks_and_parameters(self):
        for block_type, override in self.windows.items():
            with self.subTest(block_type=block_type):
                self.assertIn(block_type, self.linux)
                self.assertEqual("plugin" in override, "unsupported" not in override)
                params = {param["id"] for param in self.linux[block_type].get("params", [])}
                self.assertFalse((set(override.get("params", {})) |
                                  set(override.get("param_modes", {})) |
                                  set(override.get("param_ranges", {}))) - params)
                self.assertIn(override.get("param_mode", "norm"), ("norm", "pow"))

    def test_official_nam_output_uses_native_forty_db_range(self):
        # La sortie du VST3 NAM couvre ±40 dB : ±20 doublait réellement le trim.
        for block_type in ("pedal-nam", "preamp-nam", "comp-nam"):
            with self.subTest(block_type=block_type):
                bounds = self.windows[block_type]["param_ranges"]["output"]
                self.assertEqual(bounds, {"min": -40, "max": 40})

    def test_linux_only_plugins_are_explicitly_handled(self):
        for block_type in (
            "chorus", "phaser", "tremolo", "wah", "wah-color",
            "autowah", "delay-tape", "delay-echo", "reverb-shimmer", "rotary",
            "eq-para", "eq-graphic", "limiter", "octaver", "vibrato",
            "pitch-correct", "detune",
        ):
            with self.subTest(block_type=block_type):
                self.assertIn(block_type, self.windows)


if __name__ == "__main__":
    unittest.main()
