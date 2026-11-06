# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto-identification à l'insertion (audit 2026-08-12 §3, chantier ⑤) — la logique PURE.

Deux fonctions sous test, toutes deux sans fichier ni horloge :
  · hotplug.identify : (appareil scanné, contexte) -> verdict known-controller /
    pedalboard-usb / soundcard / unknown, avec le drapeau `propose` ;
  · hotplug.step : le débounce d'insertion (l'USB s'énumère en plusieurs temps) et la
    garantie anti-bruit — un appareil stable ne redéclenche RIEN.
"""

from bridge import hotplug


# ── appareils et contexte de fixture ─────────────────────────────────────────────────────

AKAI = {"index": 2, "id": "MPKmini", "usb": "09e8:0045", "name": "MPK Mini Mk II", "pcm": False}
STOMP = {"index": 3, "id": "HXStomp", "usb": "0e41:4246", "name": "Line 6 HX Stomp", "pcm": True}
VOLT = {"index": 1, "id": "V276", "usb": "1235:8210", "name": "Volt 276", "pcm": True}
MYSTERY = {"index": 4, "id": "nanoK", "usb": "0944:0117", "name": "nanoKONTROL2", "pcm": False}

CTX = {
    "profiles": [{"usb": "09e8:0045", "name": "AKAI MPK Mini Mk II",
                  "calibrated": "2026-07-26 15:56"},
                 {"name": "Launchkey Mini"}],                    # profil appris SANS VID:PID
    "bound": {"mpk mini mk ii"},
    "pb_usb": [{"id": "hx-stomp", "name": "HX Stomp",
                "transport": {"kind": "usb", "port_match": "hx stomp"}}],
    "active_pb": None,
}


# ── identify ─────────────────────────────────────────────────────────────────────────────

def test_controller_connu_par_vid_pid():
    v = hotplug.identify(AKAI, CTX)
    assert v["kind"] == "controller"
    assert v["match"] == "09e8:0045"
    assert "AKAI MPK Mini Mk II" in v["label"]


def test_controller_binde_ne_propose_rien():
    """L'AKAI est le binding actif (soundcard.json) : détecté, mais silence — un appareil
    déjà à sa place n'est pas une nouvelle."""
    v = hotplug.identify(AKAI, CTX)
    assert v["bound"] is True and v["propose"] is False


def test_controller_binde_sous_son_nom_court_ne_propose_rien():
    """Vécu 2026-09-09 : le scan dit « AKAI MPK Mini Mk II », le binding dit « MPK Mini Mk II »
    (nom court d'ALSA) — c'est le même appareil, à sa place, en containment."""
    v = hotplug.identify({**AKAI, "name": "AKAI MPK Mini Mk II"}, CTX)
    assert v["bound"] is True and v["propose"] is False


def test_controller_connu_non_binde_est_propose():
    ctx = {**CTX, "bound": set()}
    v = hotplug.identify(AKAI, ctx)
    assert v["kind"] == "controller" and v["propose"] is True


def test_controller_connu_par_nom_sans_vid_pid():
    """Un profil appris à la main n'a pas toujours de VID:PID : le nom (2e ligne de
    /proc/asound/cards) suffit, en containment — les deux côtés abrègent différemment."""
    dev = {"id": "LKMini", "usb": "1235:0102", "name": "Launchkey Mini MK3", "pcm": False}
    v = hotplug.identify(dev, CTX)
    assert v["kind"] == "controller" and "Launchkey Mini" in v["label"]


def test_pedalier_usb_matche_son_descripteur():
    v = hotplug.identify(STOMP, CTX)
    assert v["kind"] == "pedalboard" and v["match"] == "hx-stomp"
    assert v["propose"] is True                       # pas encore l'actif confirmé -> à sonder


def test_pedalier_usb_prime_sur_le_pcm():
    """Un HX Stomp est AUSSI une carte son (PCM) : le descripteur de pédalier gagne — sinon
    il serait avalé par l'étage carte son et jamais sondé."""
    assert hotplug.identify(STOMP, CTX)["kind"] == "pedalboard"


def test_pedalier_deja_actif_ne_propose_rien():
    ctx = {**CTX, "active_pb": "hx-stomp"}
    v = hotplug.identify(STOMP, ctx)
    assert v["kind"] == "pedalboard" and v["propose"] is False


def test_carte_son_pure_reste_a_son_etage():
    """La Volt (PCM + DIN MIDI) n'est PAS l'affaire du hotplug : sa bannière d'adoption
    existe déjà (state.cards)."""
    v = hotplug.identify(VOLT, CTX)
    assert v["kind"] == "soundcard" and v["propose"] is False


def test_inconnu_avec_son_nom_brut():
    v = hotplug.identify(MYSTERY, CTX)
    assert v["kind"] == "unknown" and v["propose"] is True
    assert v["label"] == "unknown MIDI device"


def test_contexte_vide_ne_crashe_pas():
    v = hotplug.identify({"name": None, "usb": "", "pcm": False}, {})
    assert v["kind"] == "unknown"


# ── step (débounce) ──────────────────────────────────────────────────────────────────────

def test_insertion_attend_deux_scans():
    """Premier scan : l'appareil est en attente, rien n'est signalé (l'USB s'énumère en
    plusieurs temps). Second scan après SETTLE : il arrive, UNE fois."""
    st = hotplug.new_watch()
    st, arr, dep = hotplug.step(st, [AKAI], now=100.0)
    assert arr == [] and dep == [] and st["present"] == {}
    st, arr, dep = hotplug.step(st, [AKAI], now=103.0)
    assert arr == [AKAI] and dep == []
    assert hotplug.key_of(AKAI) in st["present"]


def test_appareil_stable_ne_redeclenche_rien():
    st = hotplug.new_watch()
    st, _, _ = hotplug.step(st, [AKAI], now=0.0)
    st, arr, _ = hotplug.step(st, [AKAI], now=3.0)
    assert arr == [AKAI]
    for t in (6.0, 9.0, 12.0):
        st, arr, dep = hotplug.step(st, [AKAI], now=t)
        assert arr == [] and dep == []


def test_scintillement_reste_silencieux():
    """Vu une fois puis disparu avant SETTLE : l'appareil n'a jamais existé — ni arrivée,
    ni départ, ni trace en attente."""
    st = hotplug.new_watch()
    st, _, _ = hotplug.step(st, [AKAI], now=0.0)
    st, arr, dep = hotplug.step(st, [], now=3.0)
    assert arr == [] and dep == []
    assert st == hotplug.new_watch()


def test_depart_puis_retour_redeclenche():
    """Le seul chemin vers une re-détection (donc une re-sonde) est un VRAI départ suivi
    d'un retour débouncé."""
    st = hotplug.new_watch()
    st, _, _ = hotplug.step(st, [STOMP], now=0.0)
    st, arr, _ = hotplug.step(st, [STOMP], now=3.0)
    assert arr == [STOMP]
    st, arr, dep = hotplug.step(st, [], now=6.0)          # débranché
    assert dep == [STOMP] and st["present"] == {}
    st, arr, _ = hotplug.step(st, [STOMP], now=9.0)       # rebranché : re-débounce…
    assert arr == []
    st, arr, _ = hotplug.step(st, [STOMP], now=12.0)      # …puis re-signalé
    assert arr == [STOMP]


def test_cle_stable_par_vid_pid_pas_par_index():
    """L'index ALSA change à chaque ré-énumération (la Volt est passée 3 -> 1 dans la
    nuit) : la clé d'identité est le VID:PID, un index qui bouge n'est pas un événement."""
    st = hotplug.new_watch()
    st, _, _ = hotplug.step(st, [AKAI], now=0.0)
    st, arr, _ = hotplug.step(st, [AKAI], now=3.0)
    assert arr == [AKAI]
    moved = {**AKAI, "index": 5}
    st, arr, dep = hotplug.step(st, [moved], now=6.0)
    assert arr == [] and dep == []
    assert st["present"][hotplug.key_of(AKAI)]["index"] == 5   # rafraîchi, pas re-signalé


def test_snapshot_identifie_et_tait_les_cartes_son():
    present = {hotplug.key_of(d): d for d in (AKAI, VOLT, MYSTERY)}
    snap = hotplug.snapshot(present, [{"ev": "plug", "name": "x"}], CTX)
    kinds = {d["name"]: d["kind"] for d in snap["devices"]}
    assert kinds == {"MPK Mini Mk II": "controller", "nanoKONTROL2": "unknown"}
    assert snap["events"] == [{"ev": "plug", "name": "x"}]


def test_un_module_de_batterie_lie_en_drums_est_a_sa_place(monkeypatch):
    """docs/calibration.md addendum 2026-09-23 — mesuré : la Nitro liée en USB 1 déclenchait la
    bannière « unknown MIDI device — calibrate it ». Un module connu du registre et lié ne propose rien ;
    connu et NON lié, il dit quoi faire (bind as drums) ; lié sans registre, silence aussi."""
    from bridge import hotplug as H
    ctx = {"profiles": [], "bound": {"alesis nitro"}, "pb_usb": [], "active_pb": None,
           "drum_names": [("nitro", "Alesis Nitro")]}
    dev = {"name": "Alesis‭ Alesis Nitro", "usb": "13b2:009c", "pcm": False}
    v = H.identify(dev, ctx)
    assert v["kind"] == "drums" and v["bound"] is True and v["propose"] is False
    ctx["bound"] = set()
    v = H.identify(dev, ctx)
    assert v["kind"] == "drums" and v["propose"] is True and "Alesis Nitro" in v["label"]
    ctx["drum_names"] = []
    ctx["bound"] = {"alesis nitro"}
    assert H.identify(dev, ctx) == {"kind": "bound", "label": "bound MIDI device", "bound": True, "propose": False}
    ctx["bound"] = set()
    assert H.identify(dev, ctx)["kind"] == "unknown"
