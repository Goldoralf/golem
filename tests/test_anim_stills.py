# SPDX-License-Identifier: GPL-3.0-or-later
"""L'image fixe de chaque effet (docs/anim-packs.md §8, 2026-11-26) : le validateur que golem.fm applique aussi, les 19
images du pack default, et l'installation d'un pack qui en porte (ou pas)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bridge import anim_packs as A

ROOT = Path(__file__).resolve().parents[1]
OK = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'><defs><linearGradient id='g'><stop offset='0' stop-color='#fff'/>" \
     "</linearGradient></defs><rect width='200' height='200' fill='url(#g)'/><circle cx='9' cy='9' r='3' fill='currentColor'/>" \
     "<use href='#g'/><text x='4' y='4'>R&amp;B</text></svg>"


def test_une_image_fixe_bien_faite_passe():
    assert A.check_still(OK) == (True, "")


@pytest.mark.parametrize("svg, why", [
    (OK.replace("<rect", "<animate attributeName='x'/><rect"), "element <animate>"),
    (OK.replace("<rect", "<set to='1'/><rect"), "element <set>"),
    ("<?xml version='1.0'?>" + OK, "start with <svg"),
    ("<svg><!DOCTYPE x [<!ENTITY a 'b'>]><g/></svg>", "<!…>"),
    ("<svg><!-- un commentaire --></svg>", "<!…>"),
    ("<svg><g>&ent;</g></svg>", "entities"),
    ("<svg><image href='data:image/png;base64,AAAA'/></svg>", "data:"),
    ("<svg><image href='#x'/></svg>", "element <image>"),
    ("<svg><filter id='f'/></svg>", "element <filter>"),
    ("<svg><style>rect{fill:red}</style></svg>", "element <style>"),
    ("<svg><foreignObject/></svg>", "foreignobject"),
    ("<svg><script>alert(1)</script></svg>", "<script"),
    ("<svg onload='x()'><g/></svg>", "attribute onload"),
    ("<svg><use href='https://x/y.svg#a'/></svg>", "href must point"),
    ("<svg><use xlink:href='https://x/y.svg#a'/></svg>", "href must point"),
    ("<svg><rect fill='url(https://x/p.svg)'/></svg>", "url() must point"),
    ("<svg><g style='animation: x 1s infinite'/></svg>", "animation"),
    ("<svg><g style='fill:red'>@keyframes</g></svg>", "@keyframes"),
    ("<svg><g></svg>", "well-formed"),
    ("<svg>" + "<g/>" * 5000 + "</svg>", "bytes"),
    (None, "string"),
])
def test_une_image_fixe_qui_bouge_charge_ou_execute_est_refusee(svg, why):
    ok, reason = A.check_still(svg)
    assert not ok and why in reason, reason


def test_les_19_images_du_pack_default():
    d = next(p for p in A.list_packs() if p["id"] == "default")
    stills = {e["id"]: e.get("still") for e in d["effects"]}
    assert stills[""] is None, "None n'a pas d'image"
    missing = [k for k, v in stills.items() if k and not v]
    assert not missing, missing
    for k, v in stills.items():
        if v:
            assert A.check_still(v)[0], k
            assert len(v.encode()) < 2048, f"{k} : une image du pack default reste petite"
    assert "still" not in A.DEFAULT["effects"][1], "le descripteur figé n'est pas modifié en place"


def test_le_fichier_des_images_suit_son_outil():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "make-anim-stills.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _pack(stills):
    fx = [{"id": f"e{i}", "name": f"E{i}", **({"still": stills[i]} if i in stills else {})} for i in range(A.PACK_SIZE)]
    return {"schema": 1, "id": "u9", "name": "P", "effects": fx}, ".anim-u9-e0{opacity:.5}"


def test_un_pack_sans_images_s_installe_avec_un_avertissement_par_effet(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PACKS_DIR", str(tmp_path))
    doc, css = _pack({0: OK})
    r = A.install(doc, css)
    assert r["ok"], r
    no_still = [w for w in r["warnings"] if "no still image" in w]
    assert len(no_still) == A.PACK_SIZE - 1 and "« e1 »" in no_still[0]
    saved = json.loads((tmp_path / "u9" / "pack.json").read_text())
    assert saved["effects"][0]["still"] == OK, "l'image voyage dans pack.json"
    assert next(p for p in A.list_packs() if p["id"] == "u9")["effects"][0]["still"] == OK


def test_une_seule_image_refusee_refuse_tout_le_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PACKS_DIR", str(tmp_path))
    doc, css = _pack({0: OK, 3: OK.replace("<rect", "<animate/><rect")})
    r = A.install(doc, css)
    assert not r["ok"] and "« e3 »" in r["errors"][0] and "<animate>" in r["errors"][0]
    assert not (tmp_path / "u9").exists(), "rien d'écrit"
