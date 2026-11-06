# SPDX-License-Identifier: GPL-3.0-or-later
"""Validation du CSS d'un pack d'animations (bridge/anim_packs._check_css) : l'espace de nom se
vérifie sur les SÉLECTEURS, pas sur les commentaires — le premier pack envoyé depuis le studio
golem.fm (« /* le groupe — 20 effets … */ ») était refusé sur sa signature (2026-09-15)."""

from bridge import anim_packs as A


def test_un_commentaire_en_tete_n_est_pas_un_selecteur():
    css = "/* Night Shift — 20 effets · ambiance « Monster » */\n.anim-u1-fire { animation: u1fire 2s infinite }\n@keyframes u1fire { 50% { opacity: .5 } }"
    ok, errs, _w = A._check_css(css, "u1")
    assert ok, errs


def test_un_selecteur_hors_espace_de_nom_reste_refuse():
    ok, errs, _w = A._check_css("/* signé */ .live { min-height: 100vh }", "u1")
    assert not ok and "hors de l'espace de nom" in errs[0]


def test_un_commentaire_ne_cache_pas_du_code():
    # ce qui est dans un commentaire n'existe pas ; ce qui est dehors est toujours vu
    ok, errs, _w = A._check_css("/* javascript: */ .anim-u1-a { background: url(javascript:alert(1)) }", "u1")
    assert not ok


def test_une_longue_declaration_n_est_pas_une_tete_de_bloc():
    """Job #58 : dégradés et data: URI SVG de 400+ caractères DANS les déclarations — ce n'est pas un
    sélecteur, le garde-fou des têtes ne doit pas les compter."""
    body = "background:" + ",".join("radial-gradient(2.6px 11px at 42% 54%, color-mix(in srgb, #0a0207 30%, #141414) 9%, transparent 78%)" for _ in range(6))
    css = ".anim-u1-lurk::before{" + body + ";content:'';mask:url(\"data:image/svg+xml," + "%3Csvg%3E" * 60 + "\")}"
    ok, errs, _w = A._check_css(css, "u1")
    assert ok, errs
    # une vraie tête démesurée reste refusée
    ok2, errs2, _w2 = A._check_css(".anim-u1-a" + ", .anim-u1-b" * 200 + "{color:red}", "u1")
    assert not ok2 and "démesurée" in errs2[0]
    # vingt effets × ::before, ::after sous un @media = ~650 c. de tête : légitime
    lst = ", ".join(f".anim-u1-e{i}::before, .anim-u1-e{i}::after" for i in range(20))
    ok3, errs3, _w3 = A._check_css("@media (prefers-reduced-motion: reduce){" + lst + "{animation:none}}", "u1")
    assert ok3, errs3


def test_la_couleur_d_un_pack_est_rrggbb_ou_refusee(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "PACKS_DIR", str(tmp_path))
    fx = [{"id": f"e{i}", "name": f"E{i}", "color": "#ff1414"} for i in range(20)]
    css = "\n".join(f".anim-u9-e{i}{{opacity:.9}}" for i in range(20))
    ok = A.install({"schema": 1, "id": "u9", "name": "P", "effects": fx, "palette": {"primary": "#ff1414", "colors": ["#000000", "#ffffff"]}}, css)
    assert ok["ok"], ok
    bad = A.install({"schema": 1, "id": "u9", "name": "P", "effects": [{**fx[0], "color": "red"}] + fx[1:]}, css)
    assert not bad["ok"] and "rrggbb" in " ".join(bad["errors"])
    bad2 = A.install({"schema": 1, "id": "u9", "name": "P", "effects": fx, "palette": {"primary": "url(x)"}}, css)
    assert not bad2["ok"] and "palette.primary" in " ".join(bad2["errors"])
