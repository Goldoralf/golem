# SPDX-License-Identifier: GPL-3.0-or-later
"""LES PARCOURS (docs/quality-automation.md §9) : ce qu'un musicien fait avec golem, hub par hub, sur le contenu
d'USINE — Factory Golem (la setlist et ses chansons, Chill Jazz / Rooftop Prowl), les banques Factory Guitar, Bass,
Keys, Drums, Voice, les patches et presets d'usine.

Chaque geste passe par `t.step(nom, geste)` : les oracles jugent (runner.py). Un élément introuvable est noté « skip »
— un parcours dit ce qu'il n'a pas pu faire, il ne s'arrête pas. `t.listen(nom)` est un point de contrôle SON."""


def boot(t):
    """Le démarrage : l'écran de chargement, puis la première vérification — comme une installation neuve."""
    t.step("open golem", t.goto("#/live"), settle=2500)
    if t.page.get_by_text("Open the app anyway").count():
        t.step("loading: Open the app anyway", t.tap("Open the app anyway"))
    if t.page.get_by_text("/first check").count() or t.page.get_by_text("first check").count():
        t.step("first check: Nothing to plug in — skip", t.tap("Nothing to plug in"))
        t.step("first check: listen — No, nothing", t.tap("No, nothing"))
        t.step("first check: Skip for now", t.tap("Skip for now"))
    t.step("the Live page", t.goto("#/live"), settle=1500)


def live(t):
    """/live : les scènes, les stomps, preset suivant / précédent, les outils de la barre du haut."""
    t.step("go Live", t.goto("#/live"))
    t.listen("Live: first preset")
    for s in ("B", "C", "D", "E", "A"):
        t.step(f"scene {s}", t.tap(title=None, text=s, exact=True))
    t.listen("Live: back on scene A")
    for n in (6, 7, 8):
        t.step(f"stomp #{n} on", lambda p, n=n: p.locator(f"text=#{n}").first.click(timeout=3000))
        t.step(f"stomp #{n} off", lambda p, n=n: p.locator(f"text=#{n}").first.click(timeout=3000))
    for k in range(4):
        t.step(f"next preset ({k + 1})", t.tap(title="next preset"), settle=1500)
        t.listen(f"Live: next preset {k + 1}")
    t.step("previous preset", t.tap(title="previous preset"), settle=1500)
    for tool in ("mixer", "tuner", "assign the pedalboard", "metronome"):
        t.step(f"open the {tool}", t.tap(title=tool))
        t.step(f"close the {tool}", t.close())
    t.step("tap the metronome twice (start/stop)", lambda p: (t.find(title="metronome").click(), p.wait_for_timeout(800),
                                                              t.find(title="metronome").click()))
    t.step("record the set: start", t.tap(title="record the set"), settle=3000)
    t.step("record the set: stop", t.tap(title="stop recording"), settle=2000)
    t.step("setlist menu", t.tap(title="setlist « "))
    t.step("close the setlist menu", t.close())
    t.step("pedalboard page switch", t.tap(title="Pedalboard page"))
    t.step("lock the Designer (live lock) on", t.tap(title="lock the Designer"))
    t.step("Designer while locked", t.goto("#/designer"))
    t.step("back to Live", t.goto("#/live"))
    t.step("unlock the Designer", t.tap(title="live lock ON"))
    t.step("the Designer is editable again", t.goto("#/designer"))


def songs(t):
    """Songs : chercher, filtrer, jouer une chanson d'usine ; patches et presets (jouer, éditer, dupliquer,
    effacer la copie) ; les banques et setlists (ouvrir, mettre au pied, dupliquer, accueil au démarrage)."""
    t.step("go Songs", t.goto("#/songs"))
    t.step("search « rooftop »", t.fill("input[type=search]", "rooftop"))
    t.step("search « zzz-nothing »", t.fill("input[type=search]", "zzz-nothing"))
    t.step("clear the search", t.fill("input[type=search]", ""))
    for f in ("Covers", "Originals", "Stage-ready", "To finish", "All"):
        t.step(f"filter {f}", t.tap(f, exact=True))
    t.step("open the song Golem Rising", t.tap("Golem Rising"))
    t.step("song: Stage board", t.tap("Stage board", exact=True))
    t.step("song: Stomps", t.tap("Stomps", exact=True))
    t.step("song: Fit", t.tap("Fit", exact=True))
    t.step("song: Bars", t.tap("Bars", exact=True))
    t.step("song: tap the Chorus part", t.tap(title="Chorus — 8 bars"))
    t.step("song: tempo 132", t.fill("input[type=number]", "132"))
    t.step("song: tempo absurd -5", t.fill("input[type=number]", "-5"))
    t.step("song: tempo back to empty", t.fill("input[type=number]", ""))
    t.step("song: add a chorus", t.tap(title="add a chorus"))
    t.step("song: Add to a setlist menu", t.tap("Add to a setlist", exact=False))
    t.step("song: close the menu", t.close())
    t.step("song: back to All songs", t.tap("All songs", exact=False))
    t.step("new song: open", t.tap(title="create a song"))
    t.step("new song: close", t.close())
    # les patches
    t.step("Patches", t.goto("#/songs/patches"))
    for name in ("Jazz Warm", "British Crunch", "Modern Metal", "Electric Piano"):
        t.step(f"play patch « {name} »", t.tap(title=f"Play « {name} »"), settle=2500)
        t.listen(f"Patch {name}")
    t.step("sort", t.tap(title="sort"))
    t.step("tap sort again (a finger hits the scrim: it closes)", t.tap(title="sort"))
    t.step("filters", t.tap(title="filters"))
    t.step("tap filters again (it closes)", t.tap(title="filters"))
    t.step("the filters panel is closed", t.expect("a second tap on Filters closes its panel",
                                                   lambda p: p.locator(".ltb-pop").count() == 0 or "the panel is still open"))
    t.step("⋯ menu of the first patch", t.tap("⋯", exact=True))
    t.step("⋯ menu: Duplicate", t.tap("Duplicate"))
    t.step("Escape", t.close())
    t.step("edit « Jazz Warm » in the Designer", t.tap(title="Edit « Jazz Warm »"), settle=2000)
    t.step("the Designer opened", t.goto("#/designer"))
    # les presets
    t.step("Presets", t.goto("#/songs/presets"))
    t.step("preset scene button", t.tap("Scene A", exact=False), settle=2000)
    t.listen("Presets: a preset's scene A")
    # banques et setlists
    t.step("Banks & Setlists", t.goto("#/songs/setlists"))
    for tab in ("Setlists", "Banks", "Factory", "Mine"):
        t.step(f"tab {tab}", t.tap(tab, exact=False))
    t.step("tab All (kind)", t.tap("All", exact=False, nth=0))
    t.step("tab All (owner)", t.tap("All", exact=False, nth=1))
    t.step("duplicate a setlist", t.tap(title="duplicate"), settle=1200)
    t.step("Mine (the copy is there)", t.tap("Mine", exact=False))
    t.step("delete the copy", t.tap(title="delete the setlist"), settle=1200)
    t.step("All again (owner)", t.tap("All", exact=False, nth=1))
    t.step("put a bank on the foot", t.tap(title="use this setlist on the footswitch", nth=1), settle=1500)
    t.step("open this bank at startup", t.tap(title="open this bank at startup"))
    t.step("open a bank", t.tap("Open", exact=True, nth=1))
    t.step("back to Banks & Setlists", t.goto("#/songs/setlists"))
    t.step("Live with the bank on the foot", t.goto("#/live"), settle=1500)
    t.listen("Live: first slot of the bank on the foot")


def designer(t):
    """Le Designer sur un patch d'usine (Jazz Warm, ouvert depuis Songs ▸ Patches) : la feuille d'un bloc, ajouter un
    bloc par le tiroir, muter une branche, le tempo, les scènes, patch suivant ; puis le bac à sable vide."""
    t.step("Songs ▸ Patches", t.goto("#/songs/patches"), settle=1500)
    t.step("edit « Jazz Warm » in the Designer", t.tap(title="Edit « Jazz Warm »"), settle=2000)
    t.listen("Designer: Jazz Warm as opened")
    t.step("open the Comp block", t.tap(title="Comp · comp"))
    t.step("close the block sheet", t.close())
    t.step("open the amp block", t.tap(title="Head · amp-nam"))
    t.step("close the amp sheet", t.close())
    t.step("add block (after EQ)", t.tap(title="add block"))
    t.step("drawer: search junk", t.fill("input[type=search]", "zz<>«»"))
    t.step("drawer: clear the search", t.fill("input[type=search]", ""))
    for cat in ("Drive", "Delay", "Reverb", "Modulation", "Utility"):
        t.step(f"drawer: {cat}", t.tap(cat))
    t.step("drawer: Drive", t.tap("Drive"))
    # les cartes du tiroir n'ont pas de rôle de bouton : le doigt touche la première, en haut à gauche de la grille
    t.step("drawer: the first Drive block", lambda p: p.mouse.click(200, 118), settle=1500)
    t.step("drawer: close", t.close())
    t.listen("Designer: after adding a block")
    t.step("mute a branch in this scene", t.tap(title="lane plays in this scene"))
    t.step("unmute it", t.tap(title="lane muted in this scene"))
    t.step("delete branch: ONE tap only arms it", t.tap(title="delete branch"))
    t.step("the branch is still there", t.expect("one tap on « delete branch » deletes nothing",
                                                 lambda p: p.locator('[title*="amp-nam"], [aria-label*="amp-nam"]').count() > 0
                                                 or "the amp of the branch is gone"))
    t.step("wait for « sure? » to disarm", None, settle=3000)
    t.step("fan-out", t.tap(title="fan-out — each branch"))
    t.step("back to merge (as the factory patch)", t.tap(title="merge — branches summed"))
    t.step("tempo 140", t.fill("input[type=number]", "140"))
    t.step("tempo +1", t.tap(title="+1"))
    t.step("tempo −1", t.tap(title="−1"))
    t.step("tempo absurd 9999", t.fill("input[type=number]", "9999"))
    t.step("tempo back to 120", t.fill("input[type=number]", "120"))
    t.step("scene B (Warm)", t.tap("B", exact=True))
    t.listen("Designer: scene B")
    t.step("scene: rename or level", t.tap(title="tap to rename or set its level"))
    t.step("close", t.close())
    t.step("add scene E", t.tap(title="add scene E"))
    t.step("add scene: Duplicate « Warm »", t.tap("Duplicate « Warm »", exact=False), settle=1500)
    t.listen("Designer: the duplicated scene E")
    t.step("Config", t.tap(title="Config — services"))
    t.step("back to the lane", t.tap("bass patch", exact=False))
    t.step("actions menu", t.tap(title="actions"))
    t.step("close the actions", t.close())
    t.step("browse patches", t.tap(title="browse patches"))
    t.step("close the browser", t.close())
    t.step("next patch", t.tap(title="next patch"), settle=2000)
    t.listen("Designer: next patch")
    t.step("previous patch", t.tap(title="previous patch"), settle=2000)
    t.step("an empty bench (Songs ▸ Patches)", t.goto("#/songs/patches"))
    t.step("+ Add (an empty bench)", t.tap(title="empty bench in the Designer"))
    t.step("+ Add: Guitar", t.tap("amps, pedals, cabs"), settle=2000)
    t.step("bench: load a patch into this lane", t.tap(title="load a patch into this lane"))
    t.step("close", t.close())
    t.step("bench: add block", t.tap(title="add block"))
    t.step("close the drawer", t.close())


def library(t):
    """La Library : chaque onglet, la recherche, les filtres, écouter un sample, une groove, un standard."""
    for route in ("#/library/tones/amps", "#/library/tones/pedals", "#/library/tones/cabs", "#/library/tones/outboard",
                  "#/library/keys/synth", "#/library/keys/instruments", "#/library/drums/drums", "#/library/drums/kits",
                  "#/library/drums/grooves", "#/library/samples/short", "#/library/samples/songs",
                  "#/library/tracks/backing", "#/library/tracks/vocals", "#/library/tracks/standards",
                  "#/library/tracks/recordings"):
        t.step(f"open {route}", t.goto(route))
        if t.page.locator("input[type=search]:visible").count():
            t.step(f"search « a » on {route}", t.fill("input[type=search]", "a"))
            t.step(f"search absurd on {route}", t.fill("input[type=search]", "«»<>%%' ♪"))
            t.step(f"clear the search on {route}", t.fill("input[type=search]", ""))
    t.step("Samples: play the first", t.goto("#/library/samples/short"))
    t.step("listen to a sample", t.tap(title="listen"), settle=1500)
    t.step("listen to another sample", t.tap(title="listen", nth=3), settle=1500)
    t.step("Grooves", t.goto("#/library/drums/grooves"))
    t.step("Grooves: Genre filter", lambda p: p.locator("select").first.select_option(index=1, timeout=3000))
    t.step("Standards", t.goto("#/library/tracks/standards"))
    t.step("▶ a standard", t.tap("▶", exact=True), settle=3000)
    t.step("■ stop the standard", t.tap("▶", exact=True), settle=1000)
    t.step("Amps: + Add menu", t.goto("#/library/tones/amps"))
    t.step("+ Add", t.tap("+ Add", exact=False))
    t.step("Escape", t.close())


def settings(t):
    """Settings : chaque onglet ; changer de mode et revenir (Gig : verrouillé, et en SORTIR) ; Health ▸ Run ;
    Content ; Connect sans réseau ; About."""
    t.step("Settings ▸ Mode", t.goto("#/system/mode"))
    t.step("mode Rehearsal", t.tap(title="Rehearsal studio"), settle=2000)
    t.step("confirm if asked", lambda p: t.find("Switch", exact=False).click(timeout=2000))
    t.step("mode Jam", t.tap(title="Play along"), settle=2000)
    t.step("confirm if asked", lambda p: t.find("Switch", exact=False).click(timeout=2000))
    t.step("mode Gig (locked)", t.tap(title="On stage"), settle=2000)
    t.step("confirm if asked", lambda p: t.find("Switch", exact=False).click(timeout=2000))
    t.step("Live in Gig", t.goto("#/live"), settle=1500)
    t.step("Designer in Gig (hidden: lands on Live)", t.goto("#/designer"), settle=1000)
    t.step("leave Gig: hold the logo 2 s", t.hold(".tb-brand"), settle=1500)
    t.step("Settings after Gig", t.goto("#/system/mode"), settle=1500)
    t.step("back to Home", t.tap(title="Everything on"), settle=2000)
    t.step("confirm if asked", lambda p: t.find("Switch", exact=False).click(timeout=2000))
    t.step("every mode side by side", t.tap(title="every mode side by side"))
    t.step("Settings ▸ System", t.goto("#/system/sys"))
    t.step("Health", t.tap("Health", exact=True))
    t.step("Health: Run", t.tap("Run", exact=True), settle=4000)
    for route in ("#/system/gear/sound", "#/system/gear/controllers", "#/system/gear/pedals", "#/system/gear/board",
                  "#/system/gear/drums", "#/system/engines/audio", "#/system/engines/separation",
                  "#/system/content/storage", "#/system/content/factory", "#/system/connect/wifi",
                  "#/system/connect/devices", "#/system/connect/golemfm", "#/system/connect/tone3000",
                  "#/system/about/golem", "#/system/about/libs"):
        t.step(f"open {route}", t.goto(route))
    t.step("Content ▸ Factory", t.goto("#/system/content/factory"))
    t.step("Factory: hide a group", t.tap("Shown", exact=True))
    t.step("Factory: show it back", t.tap("Hidden", exact=False))
    t.step("Devices: Guests & screens", t.goto("#/system/connect/devices"))
    t.step("Guest for a day: open", t.tap("Guest for a day", exact=False))
    t.step("Escape", t.close())
    t.step("About ▸ Libraries", t.goto("#/system/about/libs"))
    for f in ("Commercial", "GPL / LGPL", "Permissive", "Missing Only", "All"):
        t.step(f"Libraries: {f}", t.tap(f, exact=False))


def unplugged(t):
    """La carte son débranchée (le bandeau « No sound card ») : la config du banc nomme une carte absente — le bandeau ne
    doit cacher ni les flèches preset de Live, ni le ✕ d'une fenêtre ; il se replie d'un toucher. Puis la carte revient."""
    import json
    io = t.bench.root / "config" / "io.json"
    before = io.read_text(encoding="utf-8")
    try:
        io.write_text(json.dumps({**json.loads(before), "device": "a-card-not-plugged"}) + "\n", encoding="utf-8")
        t.step("the card goes away (the banner shows)", t.goto("#/live"), settle=4500)
        t.step("setlist picker with the banner up", t.tap(title="on the pedalboard and Live"))
        t.step("close the picker (its ✕ above the banner)", t.close())
        t.step("fold the banner", t.tap(title="fold this message"))
        t.step("nothing stays under the folded banner", t.expect("no control under the folded banner", lambda p: p.evaluate(
            """() => { const out = []; for (const e of document.querySelectorAll('button,a[href],input,select')) {
                 const r = e.getBoundingClientRect(); if (!r.width || !r.height || e.closest('.cm-banner')) continue;
                 const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                 if (top && top.closest('.cm-banner')) out.push((e.title || e.innerText || '').trim().slice(0, 30)); }
               return out.length ? 'under it: ' + out.join(', ') : true; }""")))
        t.step("Songs: the filters under the folded banner", t.goto("#/songs"))
        t.step("filter Covers", t.tap("Covers", exact=True))
        t.step("unfold the banner", t.tap(title="no sound card — tap"))
    finally:
        io.write_text(before, encoding="utf-8")
    t.step("the card is back", t.goto("#/live"), settle=4500)


def companion(t):
    """Le Companion du musicien (390×844) : ses onglets, la marque, le Who."""
    t.open((390, 844), "/app/m.html?tab=now")
    t.step("Companion: Now", None, settle=1500)
    for tab in ("song", "rec", "now"):
        t.step(f"Companion: {tab}", lambda p, tab=tab: p.goto(t.bench.base + f"/app/m.html?tab={tab}"), settle=1500)
    t.step("Companion: tap the first button", lambda p: p.locator("button:visible").first.click(timeout=3000))
    t.open((1024, 600))


ALL = [("boot", boot), ("live", live), ("songs", songs), ("designer", designer), ("library", library),
       ("settings", settings), ("unplugged", unplugged), ("companion", companion)]
