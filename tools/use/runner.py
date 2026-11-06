# SPDX-License-Identifier: GPL-3.0-or-later
"""Le moteur du testeur (docs/quality-automation.md §9) : un navigateur sur le banc, des GESTES, et après chaque geste les
oracles qui disent si golem a mal pris la chose. Les parcours (journeys.py) et le singe (monkey.py) ne font que des
gestes ; tout ce qui juge est ici."""
import html as H
import json
from pathlib import Path
import re
import time

from playwright.sync_api import sync_playwright

RACK = (1024, 600)
PHONE = (390, 844)
# ce qui n'est pas une erreur de l'app : un WebSocket qui se rouvre, une ressource absente du banc (pas de golem.fm)
CONSOLE_NOISE = ("WebSocket", "favicon", "net::ERR_", "Failed to load resource")
SLOW_S = 6.0                  # un geste qui ne rend pas la main en 6 s est noté
SMALL_TARGET = 32             # rack tactile : une cible de moins de 32 px de côté est notée (UX)
JS_UX = """() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity !== 0; };
  const name = e => ((e.getAttribute('aria-label') || e.title || e.innerText || e.placeholder || '') + '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const ctl = [...document.querySelectorAll('button,a[href],input,select,[role=switch],[role=button]')].filter(vis);
  const W = innerWidth, Hh = innerHeight;
  const inScroller = e => { for (let p = e.parentElement; p; p = p.parentElement) { const s = getComputedStyle(p);
    if (/(auto|scroll)/.test(s.overflowY + s.overflowX) && (p.scrollHeight > p.clientHeight + 1 || p.scrollWidth > p.clientWidth + 1)) return true; } return false; };
  const small = [], off = [], trunc = [], overlap = [];
  // la part VISIBLE d'une commande : coupée par chaque parent qui ne laisse pas déborder (une liste qui défile) —
  // sans ça, une ligne à moitié sortie de sa liste « chevauchait » la barre du dessous (faux positif du 2026-10-27)
  const clip = e => { let r = e.getBoundingClientRect(); let x0 = r.left, y0 = r.top, x1 = r.right, y1 = r.bottom;
    for (let p = e.parentElement; p; p = p.parentElement) { const s = getComputedStyle(p);
      if (s.overflowX !== 'visible' || s.overflowY !== 'visible') { const q = p.getBoundingClientRect();
        x0 = Math.max(x0, q.left); y0 = Math.max(y0, q.top); x1 = Math.min(x1, q.right); y1 = Math.min(y1, q.bottom); } }
    return { left: x0, top: y0, right: x1, bottom: y1, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) }; };
  const boxes = ctl.map(e => [e, clip(e)]).filter(([e, r]) => r.width > 2 && r.height > 2);
  for (const [e, r] of boxes) {
    const full0 = e.getBoundingClientRect();          // la taille d'une cible : entière, pas la part visible
    // + la zone invisible d'un ::after en position absolue à bords négatifs (app/style.css, « cibles agrandies »)
    const a = getComputedStyle(e, '::after'), px = v => Math.max(0, -parseFloat(v) || 0);
    const grow = a.content !== 'none' && a.position === 'absolute' ? [px(a.top), px(a.right), px(a.bottom), px(a.left)] : [0, 0, 0, 0];
    const full = { width: full0.width + grow[1] + grow[3], height: full0.height + grow[0] + grow[2] };
    if (!e.disabled && Math.min(full.width, full.height) < %d) small.push(name(e) + ' ' + Math.round(full.width) + 'x' + Math.round(full.height));
    if ((r.right > W + 1 || r.bottom > Hh + 1 || r.left < -1 || r.top < -1) && !inScroller(e)) off.push(name(e));
  }
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const [a, ra] = boxes[i], [b, rb] = boxes[j];
    if (a.contains(b) || b.contains(a)) continue;
    // un bouton DANS son champ (▼▲ du tempo, l'œil d'un mot de passe) : voulu, pas un chevauchement
    if (a.parentElement === b.parentElement && (a.tagName === 'INPUT' || b.tagName === 'INPUT')) continue;
    const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    // le centre de la plus petite DANS la plus grande : un « + » à cheval sur le bord d'une tuile est le dessin voulu
    const [sm, bg] = ra.width * ra.height <= rb.width * rb.height ? [ra, rb] : [rb, ra];
    const cx = (sm.left + sm.right) / 2, cy = (sm.top + sm.bottom) / 2;
    const inside = cx > bg.left && cx < bg.right && cy > bg.top && cy < bg.bottom;
    if (inside && w > 4 && h > 4 && w * h > 0.3 * Math.min(ra.width * ra.height, rb.width * rb.height)) overlap.push(name(a) + ' ⟷ ' + name(b));
  }
  for (const e of document.querySelectorAll('body *')) {
    if (!vis(e) || e.children.length || !(e.innerText || '').trim()) continue;
    const s = getComputedStyle(e);
    if ((s.textOverflow === 'ellipsis' || s.overflow === 'hidden') && e.scrollWidth > e.clientWidth + 2) trunc.push((e.innerText || '').trim().slice(0, 40));
  }
  const se = document.scrollingElement;
  return { small: small.slice(0, 30), nsmall: small.length, off: off.slice(0, 20), trunc: trunc.slice(0, 20), ntrunc: trunc.length,
           overlap: overlap.slice(0, 20), scroll: [se.scrollWidth - innerWidth, se.scrollHeight - innerHeight],
           text: document.body.innerText.slice(0, 20000) };
}""" % SMALL_TARGET


# un voile de feuille ou de fenêtre : ce qui est dessous est inaccessible PAR CONSTRUCTION tant qu'elle est ouverte
# + les popovers et menus sans voile (un doigt aurait touché le popover, qui se ferme) et un <select> déroulé
SCRIM = re.compile(r"scrim|modal|overlay|backdrop|dialog|class=\"detail|sheet|drawer|pick|pop|menu|brw|<select", re.I)


def covered_by(exc):
    """L'élément qui a intercepté le clic (le message de Playwright), ou None."""
    m = re.search(r"- (<[^\n]{1,240}?) intercepts pointer events", str(exc))
    return re.sub(r"…</\w+>", "", m.group(1)).replace(" subtree", "") if m else None


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:60] or "step"


class Tester:
    """Un navigateur sur le banc. `step(nom, geste)` joue le geste puis passe les oracles ; les parcours et le singe
    n'appellent que ça et les petites aides (tap, fill, goto…)."""

    def __init__(self, bench, out, log, ui, rig, headed=False, audio=True):
        self.bench, self.out, self.log, self.audio = bench, Path(out), log, audio
        self.ui, self.rig = ui, rig             # tools/check-ui.py (français, marque) et check-rig-materialize.py (rendu)
        self.shots = self.out / "shots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.steps, self.failures, self.ux, self.sounds = [], [], {}, []
        self.n = 0
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=not headed)
        self._log_pos = bench.bridge_log.stat().st_size if bench.bridge_log.exists() else 0
        self._lua = bench.root / "presets" / ".lua-errors.log"
        self._lua_pos = self._lua.stat().st_size if self._lua.exists() else 0
        self.journey = None
        self.page = None
        self.open(RACK)

    # ── le navigateur ──────────────────────────────────────────────────────────────────────────────────────────────
    def open(self, size, path="/app/#/live"):
        if self.page:
            self.page.context.close()
        ctx = self.browser.new_context(viewport={"width": size[0], "height": size[1]})
        self.page = ctx.new_page()
        self.size = size
        self._errors, self._api = [], []
        self.page.on("pageerror", lambda e: self._errors.append(f"JS error: {e}"))
        self.page.on("console", lambda m: m.type == "error" and not any(n in m.text for n in CONSOLE_NOISE)
                     and self._errors.append(f"console: {m.text[:300]}"))
        self.page.on("response", lambda r: "/api/" in r.url and r.status >= 500
                     and self._api.append(f"{r.request.method} {r.url.split('/api/', 1)[1][:80]} → {r.status}"))
        self.page.on("dialog", lambda d: d.accept())          # un confirm() du singe : accepté (on veut voir la suite)
        self.page.goto(self.bench.base + path)
        self.page.wait_for_timeout(1500)
        return self.page

    def close(self):
        try:
            self.browser.close()
        finally:
            self._pw.stop()

    # ── un geste et ses oracles ────────────────────────────────────────────────────────────────────────────────────
    def step(self, name, fn=None, expect_fail=False, settle=600):
        """Joue `fn(page)` puis les oracles. Rend True si le geste a pu se faire (un sélecteur absent n'est pas un bug
        de golem : c'est noté « skipped »)."""
        self.n += 1
        page, t0, did, why = self.page, time.monotonic(), True, None
        url0 = page.url
        try:
            if fn:
                fn(page)
            page.wait_for_timeout(settle)
        except LookupError as e:                       # l'élément attendu n'est pas là : le parcours le dit
            did, why = False, str(e)
        except Exception as e:                         # un timeout Playwright, un clic refusé : noté, pas fatal
            did, why = False, f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
        took = time.monotonic() - t0
        issues = self._oracles(took)
        shot = self.shots / f"{self.n:04d}-{_slug((self.journey or '') + '-' + name)}.png"
        try:
            page.screenshot(path=str(shot))
        except Exception:
            shot = None
        rec = {"n": self.n, "journey": self.journey, "name": name, "ok": did, "why": why, "issues": issues,
               "took_s": round(took, 2), "url": page.url, "from": url0, "shot": shot.name if shot else None, "t": time.time()}
        self.steps.append(rec)
        with (self.out / "steps.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for i in issues:
            self.failures.append({"n": self.n, "journey": self.journey, "step": name, "issue": i, "shot": rec["shot"]})
        mark = "  FAIL " if issues else ("  ok   " if did else "  skip ")
        self.log(f"{mark}{self.n:4} {self.journey or '':10} {name}" + (f" — {why}" if why and not did else "")
                 + "".join("\n           " + i for i in issues))
        return did

    def _oracles(self, took):
        issues = []
        issues += self._errors
        issues += [f"API {x}" for x in self._api]
        self._errors, self._api = [], []
        dead = self.bench.alive()
        if dead:
            issues.append(dead)
        # le journal du bridge : les ERROR et les traces depuis le dernier geste
        try:
            with self.bench.bridge_log.open("rb") as f:
                f.seek(self._log_pos)
                new = f.read().decode("utf-8", "replace")
                self._log_pos = f.tell()
            for ln in new.splitlines():
                if re.search(r"^golem\.\S+ E |Traceback|^ERROR|\bERROR\b:", ln):
                    issues.append("bridge: " + ln[:300])
        except OSError:
            pass
        if self._lua.exists() and self._lua.stat().st_size > self._lua_pos:
            with self._lua.open("rb") as f:
                f.seek(self._lua_pos)
                issues += ["lua: " + x[:300] for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()][:5]
            self._lua_pos = self._lua.stat().st_size
        if took > SLOW_S:
            issues.append(f"slow: the gesture took {took:.1f} s")
        try:
            ux = self.page.evaluate(JS_UX)
        except Exception as e:
            issues.append(f"page not answering: {type(e).__name__}")
            return issues
        sx, sy = ux["scroll"]
        if self.size == RACK and (sx > 1 or sy > 1):
            issues.append(f"the page scrolls ({sx}px wide, {sy}px tall) — the rack never scrolls")
        if self.size == PHONE and sx > 1:
            issues.append(f"the phone page scrolls sideways ({sx}px)")
        fr = [ln for ln in ux["text"].splitlines() if self.ui.looks_french(ln)]
        if fr:
            issues.append("French on screen: " + " | ".join(x[:60] for x in fr[:3]))
        if self.ui.brand_misspelt(ux["text"]):
            issues.append("the brand is written « GoleM » on screen")
        # l'UX : par écran (la route), une seule fois — ce sont des notes, pas des échecs
        key = (self.size, self.page.url.split("#", 1)[-1].split("?")[0])
        if key not in self.ux:
            self.ux[key] = {k: ux[k] for k in ("small", "nsmall", "off", "trunc", "ntrunc", "overlap")}
        return issues

    # ── les aides des parcours ─────────────────────────────────────────────────────────────────────────────────────
    def find(self, text=None, title=None, role=None, nth=0, exact=False):
        """Le n-ième élément VISIBLE dont le texte, le title ou l'aria-label contient `text`/`title`. LookupError sinon."""
        pg = self.page
        if title:
            q = json.dumps(title, ensure_ascii=False)           # « » tels quels : un \u00ab n'est pas un échappement CSS
            loc = pg.locator(f"[title*={q}], [aria-label*={q}]")
        elif role:
            loc = pg.get_by_role(role, name=text, exact=exact)
        else:
            loc = pg.get_by_text(text, exact=exact)
        vis = [loc.nth(i) for i in range(min(loc.count(), 40)) if loc.nth(i).is_visible()]
        if len(vis) <= nth:
            raise LookupError(f"not on screen: {title or text!r}")
        return vis[nth]

    def tap(self, text=None, title=None, role=None, nth=0, exact=False):
        """Toucher comme un doigt. Si un AUTRE élément est par-dessus (le clic est intercepté), c'est un manquement
        d'UX noté sur ce geste — puis le clic est remis à l'élément lui-même, pour que le parcours continue."""
        def go(pg):
            el = self.find(text, title, role, nth, exact)
            for attempt in (1, 2):
                try:
                    el.click(timeout=2500)
                    return
                except Exception as e:
                    who = covered_by(e)
                    if not who:
                        raise
                    if SCRIM.search(who) and attempt == 1:
                        # une feuille ou un popover ouvert et son voile : pas un bug. Un DOIGT qui touche là touche le
                        # voile, qui ferme le panneau — c'est ce qu'on fait (toucher le point, pas l'élément) ; si la
                        # cible est encore là et libre ensuite, le geste continue avec elle
                        box = el.bounding_box()
                        if box:
                            pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            pg.wait_for_timeout(300)
                        return
                    self._errors.append(f"covered: « {title or text} » is under {who[:160]} — a finger cannot reach it")
                    el.dispatch_event("click")
                    return
        return go

    def expect(self, what, ok):
        """Un geste qui VÉRIFIE : `ok(page)` rend True, ou False / une phrase — c'est alors un manquement de ce geste."""
        def go(pg):
            r = ok(pg)
            if r is not True:
                self._errors.append(f"expected: {what}" + (f" — {r}" if isinstance(r, str) else ""))
        return go

    def hold(self, selector, ms=2300):
        """Appui long (le logo en mode Gig : « Hold 2 s to exit »)."""
        def go(pg):
            box = pg.locator(selector).first.bounding_box()
            if not box:
                raise LookupError(f"not on screen: {selector}")
            pg.mouse.move(box["x"] + box["width"] / 3, box["y"] + box["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(ms)
            pg.mouse.up()
        return go

    def goto(self, route):
        def go(pg):
            pg.evaluate("h => { location.hash = h }", route)
            pg.wait_for_timeout(700)
            self.past_boot(pg)
        return go

    def past_boot(self, pg):
        """L'écran de chargement et la première vérification reviennent à chaque nouvelle session de navigateur : le
        parcours « boot » les teste ; les autres passent (comme un musicien qui les a déjà vus)."""
        for label in ("Open the app anyway", "Skip for now"):
            loc = pg.get_by_text(label)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                pg.wait_for_timeout(800)

    def fill(self, selector, value):
        def go(pg):
            loc = pg.locator(selector)
            vis = [loc.nth(i) for i in range(min(loc.count(), 20)) if loc.nth(i).is_visible()]
            if not vis:
                raise LookupError(f"no field {selector}")
            vis[0].fill(value, timeout=3000)
        return go

    def close(self):
        """Fermer ce qui est ouvert, comme un doigt : Échap, puis le ✕ / « close » / « Done » s'il reste une fenêtre."""
        def go(pg):
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(300)
            scrim = pg.locator("[class*=scrim]:visible")
            if scrim.count():                          # une feuille et son voile : toucher le voile, comme un doigt
                try:
                    scrim.last.click(position={"x": 5, "y": 5}, timeout=1500)
                    pg.wait_for_timeout(300)
                except Exception:
                    pass
            # SEULEMENT dans une fenêtre ou une feuille : dans le Designer, « × » est aussi « delete branch » (un premier
            # jet du testeur y a effacé une branche entière en croyant fermer — 2026-10-27)
            box = ":is([role=dialog], [class*=sheet], [class*=modal], [class*=drawer], [class*=picker], [class*=popover], [class*=brw], .detail) "
            for q in ('[title*="close" i]', '[aria-label*="close" i]', 'button:text-is("✕")', 'button:text-is("×")',
                      'button:text-is("Done")', 'button:text-is("Close")'):
                q = box + q
                loc = pg.locator(q)
                vis = [loc.nth(i) for i in range(min(loc.count(), 10)) if loc.nth(i).is_visible()]
                if vis:
                    try:
                        vis[-1].click(timeout=2000)
                    except Exception as e:
                        who = covered_by(e)
                        if not who:
                            raise
                        self._errors.append(f"covered: the close button is under {who[:160]} — a finger cannot reach it")
                        vis[-1].dispatch_event("click")
                    return
        return go

    def press(self, key):
        return lambda pg: pg.keyboard.press(key)

    def api(self, path, body=None):
        from urllib.request import Request, urlopen
        req = Request(self.bench.base + path, method="POST" if body is not None else "GET",
                      data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")

    # ── le son ─────────────────────────────────────────────────────────────────────────────────────────────────────
    def listen(self, name):
        """Point de contrôle SON : la DI du banc à travers la lane posée (golem_preview.lua, hors ligne), analysée."""
        if not self.audio:
            return
        RIG = self.rig
        # l'état STABLE d'abord : juste après un toucher sur « Play », le rappel n'est peut-être pas encore parti — on
        # lisait le preset d'AVANT et on rendait pendant la reconstruction (un faux « silence » du 2026-10-27)
        pid, deadline = None, time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(1.0)
            st = self.api("/api/state")
            if st.get("rig_loading") or st.get("preset_id") != pid:
                pid = st.get("preset_id")
                try:
                    RIG.wait_rig(self.bench.base, self.bench.root / "presets", 20, pid=pid)
                except Exception:
                    pass
                continue
            break
        scene = st.get("scene_id") or "A"
        ctx = self._audio_ctx()
        wav = err = None
        # la piste de la lane du preset d'abord (la carte du banc : guitare IN 1, basse IN 2, voix IN 3) : juste après un
        # rappel, la piste guitare du preset d'avant existe encore, MUETTE — y rendre la DI donnait un faux silence
        first = {"bass": 1, "voice": 2}.get(self._role(pid), 0)
        for chain in RIG.CHAINS[first:] + RIG.CHAINS[:first]:
            wav, err = RIG.render_scene(ctx, pid or "none", scene, chain)
            if wav or not ("absente" in str(err) or "pas de sortie" in str(err)):
                break
        rec = {"n": self.n, "journey": self.journey, "name": name, "preset": pid, "scene": scene}
        if not wav:
            rec["status"] = "no audio lane" if ("absente" in str(err) or "pas de sortie" in str(err)) else "render failed"
            rec["why"] = err
            if rec["status"] == "render failed":
                self.failures.append({"n": self.n, "journey": self.journey, "step": f"sound: {name}", "issue": f"render failed: {err}", "shot": None})
        else:
            x, sr = RIG.read_wav(wav)
            fp = RIG.fingerprint(x, sr)
            import numpy as np
            bad = []
            if not np.all(np.isfinite(x)):
                bad.append("non-finite samples (NaN/Inf)")
            if fp["rms_db"] < -60 and not self._midi_only(pid):
                bad.append(f"silence (rms {fp['rms_db']} dBFS)")
            elif fp["rms_db"] < -60:
                rec["note"] = "MIDI lane: the DI does not play it"
            if fp["peak_db"] >= -0.01:
                bad.append(f"digital clipping (peak {fp['peak_db']} dBFS)")
            ref = ((ctx["golden"].get(pid) or {}).get(scene) or {}).get("fp")
            if ref:
                bad += ["vs reference: " + w for w in RIG.compare_fp(fp, ref, 2.0, 3.0)]
            rec.update(status="ok" if not bad else "BAD", issues=bad, rms_db=fp["rms_db"], peak_db=fp["peak_db"],
                       bands_db=fp["bands_db"], wav=str(Path(wav).name))
            for b in bad:
                self.failures.append({"n": self.n, "journey": self.journey, "step": f"sound: {name} ({pid} {scene})", "issue": b, "shot": None})
        self.sounds.append(rec)
        self.log(f"  sound {pid} {scene}: {rec['status']}" + (f" — rms {rec.get('rms_db')} dB, peak {rec.get('peak_db')} dB" if wav else f" ({rec.get('why')})")
                 + "".join("\n           " + i for i in rec.get("issues") or []))

    def _role(self, pid):
        """Le rôle de la première lane du preset (guitar, bass, voice, keys…), lu dans son fichier ; None sinon."""
        name = (pid or "").split(":", 1)[-1] + ".json"
        for d in ("presets", "library/patches", "library/factory/patches", "library/factory/presets"):
            f = self.bench.root / d / name
            if f.is_file():
                doc = json.loads(f.read_text(encoding="utf-8"))
                lanes = [L for L in doc.get("lanes") or [] if isinstance(L, dict)]
                return doc.get("role") or (lanes[0].get("role") or lanes[0].get("in_role") if lanes else None)
        return None

    def _midi_only(self, pid):
        """Un preset dont toutes les lanes jouent du MIDI (claviers, pads, batterie) : la DI guitare n'y entre pas."""
        midi = {"keys", "keys-pads", "pads", "drums"}
        name = (pid or "").split(":", 1)[-1] + ".json"
        for d in ("presets", "library/patches", "library/factory/patches", "library/factory/presets"):
            f = self.bench.root / d / name
            if f.is_file():
                doc = json.loads(f.read_text(encoding="utf-8"))
                roles = {L.get("role") or L.get("in_role") for L in doc.get("lanes") or [] if isinstance(L, dict)} or {doc.get("role")}
                return bool(roles) and roles <= midi
        return False

    def _audio_ctx(self):
        if not hasattr(self, "_actx"):
            RIG = self.rig
            work = self.out / "audio"
            work.mkdir(exist_ok=True)
            self._actx = {"base": self.bench.base, "root": self.bench.root, "env": self.bench.env, "work": work,
                          "di": RIG.make_di(work / "di.wav"), "render_timeout": 45,
                          "golden": json.loads(RIG.GOLDEN.read_text(encoding="utf-8")) if RIG.GOLDEN.exists() else {}}
        return self._actx

    # ── le rapport ─────────────────────────────────────────────────────────────────────────────────────────────────
    def report(self, meta):
        ux = [{"size": "rack" if k[0] == RACK else "phone", "screen": k[1], **v} for k, v in self.ux.items()]
        data = {**meta, "steps": len(self.steps), "skipped": sum(1 for s in self.steps if not s["ok"]),
                "failures": self.failures, "sounds": self.sounds, "ux": ux}
        (self.out / "report.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        (self.out / "report.html").write_text(render_html(data, self.steps), encoding="utf-8")
        return data


def render_html(data, steps):
    """Un rapport à ouvrir dans un navigateur : les manquements d'abord, le son, l'UX par écran, puis chaque geste."""
    e = H.escape
    fails = "".join(f"<tr><td>#{f['n']}</td><td>{e(f['journey'] or '')}</td><td>{e(f['step'])}</td><td>{e(f['issue'])}</td>"
                    f"<td>{'<a href=shots/' + e(f['shot']) + '><img src=shots/' + e(f['shot']) + '></a>' if f.get('shot') else ''}</td></tr>"
                    for f in data["failures"]) or "<tr><td colspan=5>none</td></tr>"
    snd = "".join(f"<tr><td>#{s['n']}</td><td>{e(s['name'])}</td><td>{e(str(s.get('preset')))} {e(str(s.get('scene')))}</td>"
                  f"<td class={'bad' if s['status'] in ('BAD', 'render failed') else ''}>{e(s['status'])}</td>"
                  f"<td>{s.get('rms_db', '')}</td><td>{s.get('peak_db', '')}</td><td>{e('; '.join(s.get('issues') or []) or str(s.get('why') or ''))}</td></tr>"
                  for s in data["sounds"]) or "<tr><td colspan=7>no sound checked</td></tr>"
    uxr = "".join(f"<tr><td>{e(u['size'])}</td><td>{e(u['screen'])}</td><td>{u['nsmall']}<small>{e(', '.join(u['small'][:6]))}</small></td>"
                  f"<td>{u['ntrunc']}<small>{e(' · '.join(u['trunc'][:5]))}</small></td><td>{len(u['overlap'])}<small>{e(' · '.join(u['overlap'][:4]))}</small></td>"
                  f"<td>{len(u['off'])}<small>{e(', '.join(u['off'][:5]))}</small></td></tr>" for u in data["ux"])
    rows = "".join(f"<div class='st {'bad' if s['issues'] else ('skip' if not s['ok'] else '')}'><a href=shots/{e(s['shot'] or '')}>"
                   f"<img loading=lazy src=shots/{e(s['shot'] or '')}></a><b>#{s['n']} {e(s['journey'] or '')}</b> {e(s['name'])}"
                   f"<small>{s['took_s']} s{(' · ' + e(s['why'] or '')) if not s['ok'] else ''}</small>"
                   + "".join(f"<i>{e(i)}</i>" for i in s["issues"]) + "</div>" for s in steps)
    return f"""<!doctype html><meta charset=utf-8><title>golem in use</title><style>
body{{font:14px system-ui;background:#111;color:#ddd;margin:16px}} h1,h2{{color:#fff}} table{{border-collapse:collapse;width:100%}}
td{{border-bottom:1px solid #333;padding:4px 6px;vertical-align:top}} td img{{width:160px}} .bad{{color:#f66}} small{{display:block;color:#888}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}} .st{{background:#1b1b1b;padding:6px;border-radius:6px}}
.st img{{width:100%}} .st.bad{{outline:2px solid #f44}} .st.skip{{opacity:.6}} .st i{{display:block;color:#f88;font-style:normal;font-size:12px}}
</style><h1>golem in use — {e(str(data.get('commit', '')))} · seed {data.get('seed')}</h1>
<p>{data['steps']} gestures, {data['skipped']} skipped, <b class=bad>{len(data['failures'])} failures</b>, {len(data['sounds'])} sound checks, {data.get('seconds')} s</p>
<h2>Failures</h2><table>{fails}</table><h2>Sound</h2><table><tr><td>#</td><td>checkpoint</td><td>preset scene</td><td>status</td><td>rms dB</td><td>peak dB</td><td>why</td></tr>{snd}</table>
<h2>UX by screen</h2><p>small targets (&lt;{SMALL_TARGET}px) · truncated text · overlapping controls · controls off screen</p>
<table><tr><td>size</td><td>screen</td><td>small</td><td>truncated</td><td>overlap</td><td>off screen</td></tr>{uxr}</table>
<h2>Every gesture</h2><div class=grid>{rows}</div>"""


def run(bench, a, log, ui, rig):
    """Les parcours puis le singe ; écrit le rapport ; rend le code de sortie."""
    import shutil
    from . import journeys, monkey
    if a.out.exists():
        shutil.rmtree(a.out)
    a.out.mkdir(parents=True)
    t0 = time.monotonic()
    t = Tester(bench, a.out, log, ui, rig, headed=a.headed, audio=not a.no_audio)
    try:
        only = set((a.only or "").split(",")) - {""}
        for name, fn in journeys.ALL:
            if only and name not in only:
                continue
            t.journey = name
            log(f"── journey: {name}")
            try:
                fn(t)
            except Exception as e:                      # un parcours qui casse s'arrête ; les autres continuent
                t.failures.append({"n": t.n, "journey": name, "step": "(journey)", "issue": f"journey stopped: {type(e).__name__}: {e}", "shot": None})
                log(f"  FAIL journey {name} stopped: {type(e).__name__}: {e}")
            if bench.alive():
                break
        if a.monkey and not bench.alive():
            t.journey = "monkey"
            log(f"── monkey: {a.monkey} gestures, seed {a.seed}")
            monkey.run(t, a.monkey, a.seed)
    finally:
        try:
            meta = {"seed": a.seed, "monkey": a.monkey, "seconds": round(time.monotonic() - t0), "commit": str(bench.rev)[:10],
                    "base": bench.base}
            data = t.report(meta)
        finally:
            t.close()
    log(f"{data['steps']} gestures, {len(data['failures'])} failures, {len(data['sounds'])} sound checks — "
        f"report: {a.out / 'report.html'}")
    return 1 if data["failures"] else 0
