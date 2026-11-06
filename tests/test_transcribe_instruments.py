# SPDX-License-Identifier: GPL-3.0-or-later
"""Chaque instrument sur SA portée (lot 0 des partitions, 2026-10-17) : la basse avait la tablature à six cordes de
la guitare (ses notes graves sortaient sans case), le clavier aussi, et l'instrument d'une source n'était jamais
reconnu — tout tombait sur « guitar »."""
import xml.etree.ElementTree as ET

from bridge.transcribe import Figure, to_musicxml
from bridge.transcribe_cli import _instrument_of


def _root(xml):
    return ET.fromstring(xml.split("\n", 2)[2])


def _placed(xml):
    return [(int(n.find("pitch/octave").text), n.findtext("notations/technical/string"),
             n.findtext("notations/technical/fret")) for n in _root(xml).iter("note") if n.find("pitch") is not None]


def test_la_basse_a_quatre_cordes_et_son_mi_grave_a_une_case():
    xml = to_musicxml([Figure(0.0, 1.0, (28,)), Figure(1.0, 1.0, (33,)), Figure(2.0, 1.0, (45,))],
                      bpm=100, instrument="bass")
    r = _root(xml)
    assert r.findtext(".//staff-details/staff-lines") == "4"
    assert r.findtext(".//clef/sign") == "TAB"
    placed = _placed(xml)
    assert placed[0] == (1, "4", "0")                                         # E1 : la corde de mi à vide
    open_of = {"1": 43, "2": 38, "3": 33, "4": 28}                            # chaque case donne la bonne note
    assert all(s in open_of and f is not None for _, s, f in placed)
    assert [open_of[s] + int(f) for _, s, f in placed] == [28, 33, 45]
    assert r.findtext(".//midi-program") == "34"


def test_la_guitare_garde_ses_six_cordes():
    xml = to_musicxml([Figure(0.0, 1.0, (40, 47, 52))], bpm=100)
    assert _root(xml).findtext(".//staff-details/staff-lines") == "6"
    assert all(s and f for _, s, f in _placed(xml))


def test_le_clavier_est_ecrit_sur_une_portee_sans_cases():
    hi = to_musicxml([Figure(0.0, 1.0, (60, 64, 67))], bpm=100, instrument="keys")
    assert _root(hi).findtext(".//clef/sign") == "G" and _root(hi).find(".//staff-details") is None
    assert all(s is None for _, s, _f in _placed(hi))
    lo = to_musicxml([Figure(0.0, 1.0, (36, 43))], bpm=100, instrument="keys")
    assert _root(lo).findtext(".//clef/sign") == "F"


def test_l_instrument_vient_des_roles_de_la_prise():
    man = {"roles": {"1": "Voice", "2": "Guitar", "3": "Keys + Pads", "4": "Bass", "5": "Drums"}}
    assert _instrument_of("Sandbox-Input-1", man) == "voice"
    assert _instrument_of("Sandbox-Input-2", man) == "guitar"
    assert _instrument_of("Input-3", man) == "keys"
    assert _instrument_of("Sandbox-Input-4", man) == "bass"
    assert _instrument_of("Input-5", man) == "drums"
    assert _instrument_of("Input-12", man) == "guitar"          # « 1 » ne capture plus « 12 »
    assert _instrument_of("Bass-lane", {}) == "bass"            # sans rôle : le nom, puis la guitare


# ── lot 1 : le clavier sur deux portées ─────────────────────────────────────────────────────────
def test_le_clavier_a_deux_portees_et_la_main_gauche_garde_ses_rondes():
    from bridge.transcribe import RawNote, piano_hands, to_musicxml_piano
    spq = 60 / 100
    notes = [RawNote(0, 4 * spq - 0.01, 48), RawNote(0, 4 * spq - 0.01, 55)]          # ronde main gauche
    notes += [RawNote(k * spq, (k + 1) * spq - 0.02, p) for k, p in enumerate((64, 67, 72, 67))]
    hi, lo, grid = piano_hands(notes, 100)
    assert [f.dur_ql for f in lo] == [4.0] and [f.dur_ql for f in hi] == [1.0] * 4
    r = _root(to_musicxml_piano(None, bpm=100, hands=(hi, lo), pedals=[(0.0, 3.9)]))
    assert r.findtext(".//staves") == "2"
    assert [c.findtext("sign") for c in r.iter("clef")] == ["G", "F"]
    assert {n.findtext("staff") for n in r.iter("note")} == {"1", "2"}
    assert {n.findtext("voice") for n in r.iter("note")} == {"1"}        # voix 5 = grisée par alphaTab
    assert [p.get("type") for p in r.iter("pedal")] == ["start", "stop"]
    bar = r.find(".//measure")
    lh = [n for n in bar.iter("note") if n.findtext("staff") == "2" and n.find("pitch") is not None]
    assert {n.findtext("type") for n in lh} == {"whole"}


# ── lot 2 : la batterie sur une portée de percussion ───────────────────────────────────────────
def test_la_batterie_se_lit_par_le_descripteur_et_s_ecrit_en_percussion():
    from bridge import drumkits as K
    from bridge.transcribe import RawNote, DRUM_GM, apply_rules, to_musicxml_drums
    from bridge.transcribe_cli import _drum_notes
    nitro = K.get("alesis-nitro")
    raw = [(RawNote(i * 0.3, i * 0.3 + 0.05, n), 9, 100) for i, n in enumerate((36, 42, 38, 46, 99))]
    notes, unknown = _drum_notes(raw, nitro)
    assert unknown == 1                                                   # la 99 n'existe pas sur ce module
    assert [n.pitch for n in notes] == [DRUM_GM[e] for e in ("kick", "hh-closed", "snare", "hh-open")]
    figs, _ = apply_rules(notes, 100, instrument="drums")
    r = _root(to_musicxml_drums(figs, bpm=100))
    assert r.findtext(".//clef/sign") == "percussion"
    played = [(n.findtext("unpitched/display-step"), n.findtext("unpitched/display-octave"), n.findtext("notehead"))
              for n in r.iter("note") if n.find("unpitched") is not None]
    assert played == [("F", "4", "normal"), ("G", "5", "x"), ("C", "5", "normal"), ("G", "5", "circle-x")]
    # chaque élément joué a son instrument, canal 10, pour que le lecteur le fasse sonner
    assert {m.findtext("midi-channel") for m in r.iter("midi-instrument")} == {"10"}
    assert all(n.find("notehead") is not None for n in r.iter("note") if n.find("unpitched") is not None)


# ── lot 3 : les parties du bloc Standard, exactes ─────────────────────────────────────────────────
def test_les_parties_d_un_standard_s_ecrivent_sans_rien_ecouter(tmp_path):
    from bridge import standards as S
    from bridge.transcribe import read_seq, standard_scores
    g = S._gsx_grid({"v": 1, "title": "T", "key": "C", "meter": "4/4", "tempo": 140, "feel": "swing",
                     "sections": {"A": {"bars": "C6 | A7 | Dm7 G7 | C6"}}, "form": ["A"]}, "t")
    r = S.render(g, parts={"keys": True, "bass": True, "drums": True, "guitar": True}, bpm=140, count_in=1)
    path, _ = S.write_seq(r, path=str(tmp_path / "standard.seq"))
    seq = read_seq(path)
    assert seq["cin"] == r["count_in_ppq"] and len(seq["events"]) == len(r["events"])
    out = {sc["name"]: sc for sc in standard_scores(seq, 140, title="T")}
    assert set(out) == {"Piano", "Bass", "Drums", "Rhythm guitar"}               # le clic n'est pas une partie
    for sc in out.values():                                                      # la forme, sans le décompte
        assert sc["xml"].count("<measure ") == 4, sc["name"]
    assert "<staves>2</staves>" in out["Piano"]["xml"]
    assert "<staff-lines>4</staff-lines>" in out["Bass"]["xml"]
    assert "percussion" in out["Drums"]["xml"]
    assert out["Rhythm guitar"]["figures"] == 16                                 # la pompe : 4 coups par mesure


def test_une_prise_avec_un_standard_est_transcriptible(tmp_path):
    from bridge.transcribe_jobs import eligible
    (tmp_path / "standard.seq").write_text("v 1\nlen 3840\nbar 3840\ncin 0\nnev 0\n")
    assert eligible(str(tmp_path)) == (True, "")
