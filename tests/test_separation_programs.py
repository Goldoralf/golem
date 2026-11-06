# SPDX-License-Identifier: GPL-3.0-or-later
"""§4 quinquies (avocat, 2026-10-14) : une recette de programme documente le CONTENANT, jamais le CONTENU.
Elle ne nomme aucun modèle : le modèle est un CHAMP obligatoire que l'utilisateur remplit lui-même."""
import json
import os
import stat

from bridge import separation as S

# un fichier de modèle ou de configuration de modèle : la recette n'en nomme JAMAIS
MODEL_EXT = (".yaml", ".yml", ".ckpt", ".th", ".pth", ".pt", ".onnx", ".bin", ".safetensors", ".h5")


def _recipes():
    rs = S.program_recipes()
    assert rs, "aucune recette lue"
    return rs


def test_recipes_name_no_model():
    for r in _recipes():
        text = json.dumps(r).lower()
        for ext in MODEL_EXT:
            assert ext not in text, (r["id"], ext)


def test_recipes_ask_the_model():
    for r in _recipes():
        args = r["args"]
        assert args.count("{input}") == 1 and args.count("{outdir}") == 1, r["id"]
        fields = {f["token"]: f for f in r.get("fields") or []}
        assert "{model}" in args and fields["{model}"]["required"] is True, r["id"]
        # chaque champ présent dans les arguments est déclaré, et l'inverse
        toks = {a for a in args if a.startswith("{") and a.endswith("}")} - {"{input}", "{outdir}"}
        assert toks == set(fields), r["id"]


def test_detect_finds_a_program_by_its_recipe(tmp_path, monkeypatch):
    d = tmp_path / "recipes"; d.mkdir()
    (d / "t.json").write_text(json.dumps({"id": "t", "name": "tool", "licence": "MIT",
        "find": {"names": [], "paths": [str(tmp_path / "*" / "bin" / "sep-tool")]},
        "args": ["{input}", "--model", "{model}", "{outdir}"],
        "fields": [{"token": "{model}", "label": "Model", "required": True}]}))
    monkeypatch.setattr(S, "PROGRAMS_DIR", str(d))
    assert S.detect_programs() == []
    exe = tmp_path / "venv" / "bin" / "sep-tool"; exe.parent.mkdir(parents=True)
    exe.write_bytes(b"\x7fELF"); exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    found = S.detect_programs()
    assert [(p["id"], p["path"]) for p in found] == [("t", str(exe))]
    assert "find" not in found[0]
