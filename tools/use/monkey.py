# SPDX-License-Identifier: GPL-3.0-or-later
"""LE SINGE (docs/quality-automation.md §9) : des gestes au hasard sur ce qui est cliquable à l'écran, y compris ce qui
n'a pas de sens — taper deux fois, remplir un champ de texte absurde, changer de page au milieu d'un geste. La graine
fixe la suite : `--seed 7` rejoue exactement les mêmes gestes, et steps.jsonl dit lesquels.

Écartés : les gestes qui tueraient le BANC (arrêter golem, redémarrer, verrouiller la machine, mettre à jour) et ceux
qui toucheraient le MATÉRIEL de la machine où il tourne (basculer sur une vraie carte son, flasher ou sonder le pédalier,
le Wi-Fi) — le banc tourne à côté du rack, il n'y touche pas."""
import random
import re

from .runner import SCRIM, covered_by

# le libellé, le title ou l'aria-label d'une commande : si l'un d'eux correspond, le singe ne la touche jamais
DENY = re.compile("|".join([
    r"stop golem", r"⏻", r"restart", r"reboot", r"shut ?down", r"lock down", r"harden", r"autostart",
    r"start golem with", r"update", r"check for releases", r"uninstall", r"quit",
    r"switch the engine to this card", r"use universal audio", r"use generic usb", r"\bvolt\b",
    r"flash", r"detect", r"learn", r"wi-?fi", r"hotspot", r"access point", r"network",
    r"revoke", r"pair", r"🔗", r"sign in", r"connect$", r"📱 connect",
    r"download", r"pull from golem\.fm", r"☁", r"separate a folder", r"add engine", r"back up", r"⇅",
    r"show on this computer", r"buffer", r"\bms\b$", r"reaper-?update", r"select$",
]), re.I)
# les pages où un geste au hasard peut faire ouvrir le VRAI matériel au REAPER du banc (carte son, moteur, buffer) : le
# singe n'y fait que repartir — les parcours y passent à la main, geste par geste
HANDS_OFF = re.compile(r"#/system/(gear/sound|engines|sys)(/|$)")
# le texte absurde des champs
JUNK = ["", " ", "x" * 300, "Léa ♪ 🎸 «»", "<script>alert(1)</script>", "../../etc/passwd", "-1", "99999999", "0",
        "NaN", "  spaces  ", "ＡＢＣ", "‮evil", "a\nb", "%s%s%n", "'; DROP TABLE x; --"]
HUBS = ["#/live", "#/designer", "#/songs", "#/songs/patches", "#/songs/presets", "#/songs/setlists", "#/library/tones/amps",
        "#/library/drums/grooves", "#/library/samples/short", "#/library/tracks/standards", "#/system/mode",
        "#/system/content/storage", "#/system/connect/devices", "#/system/about/libs"]

JS_TARGETS = """() => { for (const e of document.querySelectorAll('[data-monkey]')) e.removeAttribute('data-monkey');
  return [...document.querySelectorAll('button,a[href],input,select,[role=switch],[role=button],[role=tab]')]
  .filter(e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.disabled
      && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth; })
  .map((e, i) => { e.setAttribute('data-monkey', i);
    const label = ((e.getAttribute('aria-label') || '') + ' | ' + (e.title || '') + ' | ' + (e.innerText || e.placeholder || e.value || '')).replace(/\\s+/g, ' ').trim();
    return { i, tag: e.tagName.toLowerCase(), type: e.type || '', label: label.slice(0, 120) }; }); }"""


def run(t, n, seed):
    rng = random.Random(seed)
    for k in range(n):
        if t.bench.alive():
            t.log("  the bench died — the monkey stops")
            return
        pg = t.page
        roll = rng.random()
        if roll < 0.06:                                            # changer de page au hasard
            hub = rng.choice(HUBS)
            t.step(f"go {hub}", t.goto(hub))
            continue
        if roll < 0.09:                                            # Échap, retour arrière
            key = rng.choice(["Escape", "Escape", "Backspace"])
            if key == "Backspace":
                t.step("browser back", lambda p: p.go_back(timeout=4000))
            else:
                t.step("Escape", t.press("Escape"))
            continue
        if HANDS_OFF.search(pg.url):
            t.step("leave a hands-off page", t.goto(rng.choice(HUBS[:6])))
            continue
        try:
            targets = pg.evaluate(JS_TARGETS)
        except Exception:
            t.step("page reload (page not answering)", lambda p: p.reload())
            continue
        targets = [x for x in targets if not DENY.search(x["label"])]
        if not targets:
            t.step("go live (nothing to touch)", t.goto("#/live"))
            continue
        x = rng.choice(targets)
        sel = f"[data-monkey='{x['i']}']"
        label = x["label"].strip(" |") or x["tag"]
        if x["tag"] == "select":
            def act(p, sel=sel):
                opts = p.locator(sel + " option")
                if opts.count():
                    p.locator(sel).first.select_option(index=rng.randrange(opts.count()), timeout=3000)
            t.step(f"choose in « {label[:50]} »", act)
        elif x["tag"] == "input" and x["type"] not in ("checkbox", "radio", "file", "range", "submit", "button", "color"):
            junk = rng.choice(JUNK)

            def act(p, sel=sel, junk=junk):
                p.locator(sel).first.fill(junk, timeout=3000)
                if rng.random() < 0.5:
                    p.keyboard.press("Enter")
            t.step(f"type {junk[:20]!r} in « {label[:40]} »", act)
        elif x["type"] == "file":
            continue                                               # pas de fichier choisi au hasard
        else:
            times = 2 if rng.random() < 0.12 else 1                # le double-tap impatient

            def act(p, sel=sel, times=times, label=label):
                for _ in range(times):
                    try:
                        p.locator(sel).first.click(timeout=2500, no_wait_after=True)
                    except Exception as e:
                        who = covered_by(e)
                        if not who:
                            raise
                        if SCRIM.search(who):
                            t.close()(p)               # une feuille ouverte : le singe la ferme, comme un doigt
                            return
                        t._errors.append(f"covered: « {label[:60]} » is under {who[:160]} — a finger cannot reach it")
                        return
            t.step(("double-" if times == 2 else "") + f"tap « {label[:60]} »", act, settle=400)
