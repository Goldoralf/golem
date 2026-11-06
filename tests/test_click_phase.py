# SPDX-License-Identifier: GPL-3.0-or-later
"""La PHASE du click après un départ / saut / seek du transport, et les GROUPES d'accents du click du morceau
(docs/arrangement.md §4, docs/bars-format.md §5 — 2026-10-15).

L'EEL2 ne se teste pas hors de REAPER : on en garde ici un MIROIR ligne à ligne (`eel_realign`, `eel_accent`,
`eel_song_accents`), et des tests de source vérifient que les lignes miroitées sont toujours celles du JSFX. Les deux
fonctions Lua pures (`songclick_parse` de golem_backing, `groups_mask` de golem_click) sont EXÉCUTÉES telles quelles
sous lupa. Ce que ces tests ne prouvent pas : que REAPER rend `play_position` comme on le croit — ça, c'est l'écoute
au rig (compte rendu de la passe)."""
import math
import re
from pathlib import Path

import pytest

from bridge import arrangement as A

ROOT = Path(__file__).resolve().parent.parent
JSFX = (ROOT / "reaper/Effects/golem_click.jsfx").read_text(encoding="utf8")
CLICK_LUA = (ROOT / "reaper/Scripts/golem_click.lua").read_text(encoding="utf8")
BACKING_LUA = (ROOT / "reaper/Scripts/golem_backing.lua").read_text(encoding="utf8")
SR = 48000.0


# ── miroirs EEL2 (golem_click.jsfx, @block « ANCRE DE SECTION » et @sample) ─────────────────────────────────────
def anchor_slider(anchor_s):
    """golem_click.lua : st.anchor >= 0 and st.anchor + 1 or 0."""
    return anchor_s + 1 if anchor_s is not None and anchor_s >= 0 else 0


def eel_realign(play_pos, slider, tempo, beats, den, div=1, since=1e9):
    """-> (index du PROCHAIN pas, secondes avant lui). Projet à tempo constant : beat_position = pos × tempo / 60."""
    t = max(tempo, 1)
    dv = min(4, max(1, math.floor(div + 0.5)))
    bt = min(32, max(1, math.floor(beats + 0.5)))
    dn = min(16, max(1, math.floor(den + 0.5)))
    nsteps = bt * dv
    spb = SR * 60 * 4 / (t * dn * dv)
    an_has = slider >= 0.5
    an_el = play_pos - (slider - 1)
    an_step = 240 / (t * dn * dv)
    if an_has and an_el > -0.01:
        bp = an_el / an_step
    else:
        bp = (play_pos * t / 60.0) * dv
    st = math.floor(bp)
    fr = bp - st
    if fr < 0.000001:
        nxt, idx = 0.0, st
    else:
        nxt, idx = (1 - fr) * spb, st + 1
    idx -= math.floor(idx / nsteps) * nsteps
    if since + nxt < spb * 0.5:
        nxt += spb
        idx = (idx + 1) % nsteps
    return int(idx), nxt / SR


def eel_should_realign(start_or_jump, an_chg, slider, play_pos, an_age, tempo, den, div=1):
    """Le déclencheur `re_go` (sync, lecture, pas asservi : supposés)."""
    if start_or_jump:
        return True
    an_has = slider >= 0.5
    an_el = play_pos - (slider - 1)
    an_step = 240 / (max(tempo, 1) * den * div)
    return bool(an_chg and an_has and an_el >= 0 and (an_age < 1.0 or an_el < an_step * div * 0.5))


def eel_accent(beat_idx, gmask, div=1):
    """@sample, compteur interne : « one » (1000 Hz) · « group » (800 Hz plein) · « beat » (−3 dB) · « sub »."""
    pi = beat_idx // div
    sub = (beat_idx - pi * div) > 0
    grp = (not sub) and (math.floor(gmask / (2 ** pi)) % 2) >= 0.5
    if pi == 0 and not sub:
        return "one"
    return "sub" if sub else ("group" if grp else "beat")


def eel_song_accents(notes, gmask):
    """midirecv, canal 16 : [(note, vel)] -> accents MQ_ACC (1 = le « 1 », 3 = début de groupe, 0 = temps)."""
    sb, out = 0, []
    for note, vel in notes:
        acc = 1 if note == 76 else (2 if note == 78 else 0)
        if note == 76:
            sb = 0
        elif vel < 100:
            sb = vel - 1
        else:
            sb += 1
        if note == 77 and sb < 32 and (math.floor(gmask / (2 ** sb)) % 2) >= 0.5:
            acc = 3
        out.append(acc)
    return out


# ── Lua réel, sous lupa ─────────────────────────────────────────────────────────────────────────────────────────
def _lua_fn(src, name):
    lupa = pytest.importorskip("lupa")
    m = re.search(r"^local function %s\(.*?^end\n" % name, src, re.S | re.M)
    assert m, f"{name} introuvable"
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(m.group(0).replace("local function", "function", 1))
    return L, L.globals()[name]


def groups_mask(groups, num):
    L, f = _lua_fn(CLICK_LUA, "groups_mask")
    return f(L.table_from(groups) if groups is not None else None, num)


def songclick_parse(text):
    _L, f = _lua_fn(BACKING_LUA, "songclick_parse")
    out, skipped = f(text)
    return [(t["t"], t["note"], t["vel"]) for t in out.values()], skipped


# ── un plan d'arrangement réel, et la VÉRITÉ (compter les pas depuis le début de SA section) ─────────────────────
def _preset(secs, bpm=120, base=None):
    pm = {"sections": secs}
    if base:
        pm["sig"] = base
    return {"id": "p", "bpm": bpm, "scenes": [],
            "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a", "params": pm}]}}}


def _section_at(plan, pos):
    return max([k for k, s in enumerate(plan) if s["at"] <= pos + 1e-9] or [0])


def truth(plan, pos, bpm):
    """(index du prochain pas, s avant lui) en comptant depuis le début de la section qui contient `pos`."""
    sec = plan[_section_at(plan, pos)]
    step = 240.0 / (bpm * sec["den"])
    n = (pos - sec["at"]) / step
    k = math.ceil(n - 1e-6)
    return k % sec["num"], (k * step + sec["at"]) - pos


def rig(plan, pos, bpm, anchored=True):
    """Ce que le JSFX calcule au recalage, avec la mesure et l'ancre que le bridge a envoyées pour cette section."""
    k = _section_at(plan, pos)
    sec = plan[k]
    sl = anchor_slider(A.click_anchor(plan, k)) if anchored else 0
    return eel_realign(pos, sl, bpm, sec["num"], sec["den"])


M78 = {"num": 7, "den": 8, "groups": [3, 2, 2]}
MIXED = _preset([{"name": "intro", "bars": 2},                    # 4/4 : 0 → 4 s
                 {"name": "verse", "bars": 2, "sig": M78},        # 7/8 : 4 → 7,5 s
                 {"name": "bridge", "bars": 1, "sig": M78},       # même mesure : même ancre (4 s)
                 {"name": "outro", "bars": 2}],                   # 4/4 : 9,25 → 13,25 s
                base={"num": 4, "den": 4})


# ── LIMITE A : la phase ─────────────────────────────────────────────────────────────────────────────────────────
def test_44_depart_a_zero_identique_a_l_ancien_calcul():
    for pos in (0.0, 0.3, 1.0, 1.75, 5.2):
        assert eel_realign(pos, anchor_slider(0.0), 120, 4, 4) == eel_realign(pos, 0, 120, 4, 4)
    assert eel_realign(0.0, anchor_slider(0.0), 120, 4, 4) == (0, 0.0)
    assert eel_realign(1.6, anchor_slider(0.0), 120, 4, 4)[0] == 0          # 1,6 s -> le pas 4 = le 1 de la mesure 2


def test_78_groupes_322():
    gm = groups_mask([3, 2, 2], 7)
    assert gm == 41                                                          # pulsations 0, 3, 5
    pulse = 0.25                                                             # croche à 120
    seen = [eel_realign(i * pulse, anchor_slider(0.0), 120, 7, 8)[0] for i in range(14)]
    assert seen == [0, 1, 2, 3, 4, 5, 6] * 2
    assert [eel_accent(i, gm) for i in range(7)] == ["one", "beat", "beat", "group", "beat", "group", "beat"]


def test_68_a_90():
    pulse = (4 / 8) * 60 / 90                                                # 1/3 s
    assert eel_realign(1.0, anchor_slider(0.0), 90, 6, 8)[0] == 3            # 3 croches
    assert eel_realign(2.0, anchor_slider(0.0), 90, 6, 8)[0] == 0            # mesure 2
    idx, dt = eel_realign(1.1, anchor_slider(0.0), 90, 6, 8)
    assert idx == 4 and abs(dt - (4 * pulse - 1.1)) < 1e-9
    # l'ANCIEN calcul (noires) était faux dès le 1er temps : 1 s à 90 = 1,5 noire -> pas 2, pas 3
    assert eel_realign(1.0, 0, 90, 6, 8)[0] != 3


def test_plan_et_ancres():
    pl = A.plan(MIXED)
    assert [s["at"] for s in pl] == [0.0, 4.0, 7.5, 9.25]
    assert [A.click_anchor(pl, k) for k in range(4)] == [0.0, 4.0, 4.0, 9.25]   # bridge : suite de même mesure
    assert A.click_anchor(pl, 9) is None


def test_saut_dans_une_section_en_78_depuis_le_44():
    pl = A.plan(MIXED)
    pos = 5.0                                                                # saut de répète (ou seek) dans « verse »
    idx, dt = rig(pl, pos, 120)
    assert (idx, round(dt, 9)) == (4, 0.0)                                   # 1 s = 4 croches : le pas 4, maintenant
    assert eel_accent(idx, groups_mask([3, 2, 2], 7)) == "beat"
    assert rig(pl, 5.75, 120)[0] == 0                                        # 1,75 s : le 1 de la mesure 2 du couplet
    assert rig(pl, 4.75, 120)[0] == 3 and eel_accent(3, 41) == "group"
    # l'ancien calcul : 5 s à 120 = 10 noires -> 10 % 7 = 3 — faux
    assert rig(pl, pos, 120, anchored=False)[0] == 3


def test_partir_d_une_section_44_apres_du_78():
    pl = A.plan(MIXED)
    assert rig(pl, 9.25, 120) == (0, 0.0)                                    # « outro » : le 1, tout de suite
    # l'ancien : 9,25 s = 18,5 noires -> pas 19 % 4 = 3 — un « 1 » joué sur le 4e temps pendant toute la section
    assert rig(pl, 9.25, 120, anchored=False)[0] == 3


@pytest.mark.parametrize("pos", [i * 0.0625 for i in range(int(13.25 / 0.0625))])
def test_partout_dans_le_morceau_l_ancre_donne_la_verite(pos):
    pl = A.plan(MIXED)
    got_idx, got_dt = rig(pl, pos, 120)
    want_idx, want_dt = truth(pl, pos, 120)
    assert got_idx == want_idx and abs(got_dt - want_dt) < 1e-6, (pos, got_idx, want_idx)


def test_atterrir_un_cheveu_avant_l_ancre():
    # rebouclage natif : play_position arrondi juste sous la cible -> le pas 0, sans attendre une mesure
    idx, dt = eel_realign(4.0 - 1e-7, anchor_slider(4.0), 120, 7, 8)
    assert idx == 0 and dt < 1e-6


def test_transport_avant_l_ancre_retombe_sur_l_ancien_calcul():
    # prise perf-rec partie de 0 alors que le morceau part de « outro » (9,25 s) : le transport n'est pas le temps du
    # morceau — on garde le comportement d'avant plutôt qu'une phase inventée
    assert eel_realign(0.0, anchor_slider(9.25), 120, 4, 4) == eel_realign(0.0, 0, 120, 4, 4)


def test_quand_une_ancre_qui_change_recale():
    step78 = 0.25
    # mesure pré-envoyée ½ pulsation AVANT la frontière (transport avant l'ancre) : on ne touche à rien
    assert not eel_should_realign(False, True, anchor_slider(4.0), 4.0 - 0.25, 30.0, 120, 8)
    # pré-envoyée avant un saut de répète vers l'ARRIÈRE (le transport est encore loin après l'ancre) : rien non plus,
    # c'est le saut qui recalera
    assert not eel_should_realign(False, True, anchor_slider(0.0), 8.9, 30.0, 120, 4)
    # arrivée EN RETARD sur sa frontière (< ½ pulsation) : recale
    assert eel_should_realign(False, True, anchor_slider(4.0), 4.0 + 0.4 * step78, 30.0, 120, 8)
    # seek vu après coup par le bridge : l'ancre juste arrive 0,3 s après le saut -> recale
    assert eel_should_realign(False, True, anchor_slider(4.0), 6.3, 0.3, 120, 8)
    # ancre inchangée, ou retirée (fin du morceau) : rien
    assert not eel_should_realign(False, False, anchor_slider(4.0), 6.3, 0.3, 120, 8)
    assert not eel_should_realign(False, True, 0, 6.3, 0.3, 120, 8)


def test_une_mesure_en_retard_recalee_par_l_ancre():
    # le compteur a sonné le 1 du 7/8 à 4,0 s avec l'ANCIENNE durée (0,5 s) ; la mesure arrive à 4,02 s
    since = 0.02 * SR
    idx, dt = eel_realign(4.02, anchor_slider(4.0), 120, 7, 8, since=since)
    assert idx == 1 and abs(dt - 0.23) < 1e-9                               # le 2e pas à 4,25 s, pas à 4,5 s


# ── LIMITE B : les groupes dans le click du morceau ────────────────────────────────────────────────────────────
def _ticks_78(bars=2, ms0=0, pulse_ms=250):
    lines = []
    for b in range(bars):
        for k in range(7):
            lines.append(f"{ms0 + (b * 7 + k) * pulse_ms} {1 if k == 0 else 0}")
    return "\n".join(lines) + "\n"


def test_la_velocite_porte_l_index_du_temps():
    ticks, skipped = songclick_parse(_ticks_78())
    assert skipped == 0 and len(ticks) == 14
    assert [n for _t, n, _v in ticks[:7]] == [76, 77, 77, 77, 77, 77, 77]
    assert [v for _t, _n, v in ticks] == [1, 2, 3, 4, 5, 6, 7] * 2
    assert ticks[7][0] == 1.75


def test_les_groupes_s_entendent_dans_le_click_du_morceau():
    ticks, _ = songclick_parse(_ticks_78())
    acc = eel_song_accents([(n, v) for _t, n, v in ticks], groups_mask([3, 2, 2], 7))
    assert acc == [1, 0, 0, 3, 0, 3, 0] * 2
    # 2+2+3 dans la section suivante : le même item, un autre masque
    assert eel_song_accents([(n, v) for _t, n, v in ticks[:7]], groups_mask([2, 2, 3], 7)) == [1, 0, 3, 0, 3, 0, 0]
    # sans groupement (ou groupement faux) : le 1 seul, comme avant
    assert eel_song_accents([(n, v) for _t, n, v in ticks[:7]], groups_mask([3, 3], 7)) == [1, 0, 0, 0, 0, 0, 0]


def test_un_seek_au_milieu_d_une_mesure_garde_ses_accents():
    ticks, _ = songclick_parse(_ticks_78())
    after_seek = [(n, v) for _t, n, v in ticks[4:]]                         # on reprend au 5e temps
    assert eel_song_accents(after_seek, 41)[:3] == [0, 3, 0]                # le pas 5 reste un début de groupe


def test_les_items_d_avant_velocite_100_comptent_depuis_le_1():
    legacy = [(76 if k == 0 else 77, 100) for k in range(7)] * 2
    assert eel_song_accents(legacy, 41) == [1, 0, 0, 3, 0, 3, 0] * 2


def test_un_fichier_qui_commence_au_milieu_d_une_mesure():
    # levée coupée à 0 s : les temps avant le premier « 1 » n'ont pas d'index sûr -> vélocité 100 (inconnu)
    text = "-120 0\n100 0\n350 0\n600 1\n850 0\n"
    ticks, skipped = songclick_parse(text)
    assert skipped == 1
    assert [v for _t, _n, v in ticks] == [100, 100, 1, 2]
    assert songclick_parse("")[0] == []


# ── les miroirs disent-ils encore ce que dit le code ? ──────────────────────────────────────────────────────────
def test_le_jsfx_porte_les_lignes_miroitees():
    assert "slider14:anchor=0<0," in JSFX                                    # min 0 : pas de taper bipolaire
    for line in ("an_el = play_position - (anchor - 1);",
                 "an_step = 240 / (t * dn * dv);",
                 "bp = an_el / an_step;",
                 "bp = beat_position * dv;",
                 "(an_has && an_el > -0.01) ?",
                 "idx -= floor(idx / nsteps) * nsteps;",
                 "(an_chg && an_has && an_el >= 0 && (an_age < AN_WIN || an_el < an_step * dv * 0.5)) ? re_go = 1;",
                 "AN_WIN = 1.0;",
                 "m_s3 < 100 ? ( sb_idx = m_s3 - 1; ) : ( sb_idx += 1; )",
                 "(m_s2 == 77 && sb_idx < 32 && (floor(gmask / (2 ^ sb_idx)) % 2) >= 0.5) ? MQ_ACC[mq_n] = 3;",
                 "vgain = a == 2 ? 0.398 : ((a == 1 || a == 3) ? 1 : 0.708);"):
        assert line in JSFX, line
    # le pas du recalage et celui du compteur sont la même formule (tools/meter-cases.json)
    assert "spb = srate * 60 * 4 / (t * dn * dv);" in JSFX
    # code avant la 1re section : rien (piège JSFX), et AN_WIN est bien dans @init
    head, init = JSFX.split("\n@init", 1)
    assert "AN_WIN" not in head and "AN_WIN = 1.0;" in init.split("\n@slider", 1)[0]


def test_le_lua_ecrit_l_ancre_au_bon_slider():
    assert "anchor = 13 }" in CLICK_LUA                                      # slider14 = index 13
    assert 'local LAST_SLIDER_NAME = "Section anchor"' in CLICK_LUA
    assert "st.anchor >= 0 and st.anchor + 1 or 0" in CLICK_LUA
    assert "tk.note, tk.vel, true" in BACKING_LUA


def test_le_bridge_porte_l_ancre_a_chaque_commande():
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    cmd = src[src.index("def _click_cmd"):src.index("def _arr_click_song")]
    assert 'cmd["anchor"]' in cmd
    meter = src[src.index("def _arr_click_meter"):src.index("def _click_cmd")]
    assert '_ARR_CLICK.get("song")' not in meter                           # poussée aussi en click du morceau (groupes)
