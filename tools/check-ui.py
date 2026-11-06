#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'app RENDUE, page par page, comme un musicien la verrait (docs/quality-automation.md, lot 2).

Rien ne compile dans l'app (Preact + htm) : seul le rendu dit si une page tient. Cette sonde démarre un bridge
JETABLE (runtime et dossier REAPER temporaires, port libre — comme tools/check-desktop-bridge.py), ouvre chaque
page du rack à 1024×600 et le Companion à 390×844 dans le Chrome du système (Playwright, aucun navigateur
téléchargé), et vérifie sur chacune :

  - aucune erreur JavaScript, aucune erreur console ;
  - AUCUN défilement (le rack est une tablette 1024×600 qui ne scrolle pas ; le téléphone ne scrolle pas en largeur) ;
  - aucun libellé FRANÇAIS à l'écran (règle 4 du CLAUDE.md) — le même détecteur que tools/check-descriptors.py ;
  - la marque s'écrit « golem », jamais « GoleM » ;
  - la page a rendu quelque chose (le hub et ses onglets).

Toute écriture (POST/PUT/DELETE/PATCH vers /api/) est INTERCEPTÉE et répond {ok: true} : explorer ne modifie
rien, même contre un vrai bridge (`--base http://localhost:8770`). Captures d'écran dans `--out` (CI : artefact).
Sortie : un rapport JSON (`--json`) et le code 1 au premier manquement. ~1 à 2 minutes."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]

RACK = (1024, 600)
PHONE = (390, 844)

# Les pages du rack : un hub, ses onglets, ses sous-onglets (docs/ui-architecture.md §1). Une page qui n'existe
# plus retombe sur l'atterrissage de son hub : la sonde le dit (« landed elsewhere ») sans échouer.
RACK_PAGES = [
    "#/live", "#/designer", "#/designer/config",
    "#/songs", "#/songs/patches", "#/songs/presets", "#/songs/setlists",
    "#/library/tones/amps", "#/library/tones/pedals", "#/library/tones/cabs", "#/library/tones/outboard",
    "#/library/keys/synth", "#/library/keys/instruments",
    "#/library/drums/drums", "#/library/drums/kits", "#/library/drums/grooves",
    "#/library/samples/short", "#/library/samples/songs",
    "#/library/tracks/backing", "#/library/tracks/vocals", "#/library/tracks/standards", "#/library/tracks/recordings",
    # Settings, la barre de mockups/settings-nav.html (2026-10-20) : Mode · System · Gear · Engines · Content · Connect · About
    "#/system/mode", "#/system/mode/compare", "#/system/sys", "#/system/sys/health",
    "#/system/gear/sound", "#/system/gear/controllers", "#/system/gear/pedals", "#/system/gear/board", "#/system/gear/drums",
    "#/system/engines/audio", "#/system/engines/separation",
    "#/system/content/storage", "#/system/content/factory",
    "#/system/connect/wifi", "#/system/connect/devices", "#/system/connect/golemfm", "#/system/connect/tone3000",
    "#/system/about/golem", "#/system/about/libs",
    # la vérification de première installation (docs/health.md §2), en démo : pendant le geste 2, puis le bilan
    "/app/?boot=firstcheck#/live", "/app/?boot=firstcheck&at=input#/live", "/app/?boot=firstcheck&at=done#/live",
]
# Le Companion du musicien (app/m.html) : ses onglets dépendent de l'appareil appairé ; depuis l'écran local,
# Now et Song existent toujours.
PHONE_PAGES = ["/app/m.html?tab=now", "/app/m.html?tab=song", "/app/m.html?tab=rec"]

# Le détecteur de français, dans l'esprit de tools/check-descriptors.py : des mots outils qui n'existent qu'en
# français — TROIS dans une même ligne (un titre de chanson comme « Pour que tu m'aimes encore » en a deux et
# n'est pas un libellé) — ou UN seul mot du vocabulaire d'interface (réglage, appuyer, enregistrer…), qu'un
# titre ne porte jamais.
_FR = re.compile(r"\b(le|la|les|du|des|une|un|puis|avec|sur|dans|pour|est|sont|qui|que|ce|cette|vers|chaque|"
                 r"aucun|aucune|tous|toutes|mais|donc|alors|votre|vos|notre|nos)\b", re.I)
_FR_UI = re.compile(r"\b(réglages?|appuyer|appuyez|choisir|choisissez|enregistrer|enregistrement|sauvegarder|"
                    r"charger|chargement|supprimer|modifier|fermer|ouvrir|nouveau|nouvelle|annuler|valider|"
                    r"paramètres?|connecté|connectée|déconnecté|lecture|arrêter|démarrer|télécharger)\b", re.I)
# Ce qui n'est pas une erreur de l'app : le WebSocket d'un bridge sans REAPER se ferme et se rouvre.
_CONSOLE_NOISE = ("WebSocket", "favicon", "net::ERR_", "503", "Failed to load resource")
# « GoleM » : la marque s'écrit « golem » dans tout ce qui s'affiche (CLAUDE.md, règle 4) — SAUF les identifiants
# existants, qu'on ne renomme pas : un dossier (…/GoleM/…), un nom de plugin tel que REAPER le donne
# (« CLAP: GoleM Freeze (GoleM) »).
_BRAND_OK = re.compile(r"[\\/]GoleM|GoleM[\\/]|(?:CLAP|VST3?|LV2|JS): GoleM|GoleM Freeze|\(GoleM\)")
# des commandes qui nomment la MACHINE, pas la surface : le réseau WiFi, les périphériques USB branchés, le pilote,
# le témoin « LIVE » d'un REAPER présent — hors inventaire, sinon le poste de dev et le runner ne s'accordent jamais.
# 2026-10-20 (Settings en sept onglets, la CI rouge depuis) : « ▶ start » (REAPER arrêté, le runner) contre « restart »
# (REAPER lancé, le poste), une ligne Health « Storage » selon le disque, « Calibrate » d'un contrôleur BRANCHÉ, et
# « This Is A Drum Module » — un appareil connu du poste (config/devices.json).
_VOLATILE = re.compile(r"\bUSB #|🔒 connected|● LIVE|\b(?:asio|hw|coreaudio):|\bMPK\b|\bVolt\b"
                       r"|▶ start$|\| Storage →|\| (?:Re-)?[Cc]alibrate$|Is A Drum Module"
                       # le mode performance du processeur (offert sur le poste) ; le balayage WiFi (le runner n'a pas de radio)
                       r"|⚡ boost$|↓ turn off$|… [Ss]canning$|⟳ Scan$")
# … et celles qui ne le sont que sur UNE page : « × » y oublie un réseau connu du poste ; « Fix… » n'existe que
# pour un incident OUVERT (le runner en a un selon les passes, le poste presque toujours)
_VOLATILE_ON = {"#/system/connect/wifi": re.compile(r"\| ×$"),
                "#/system/sys/health": re.compile(r"\| Fix…$")}


def stable_controls(controls, page=None):
    # normaliser d'abord (« USB 1 » -> « USB # »), filtrer ensuite : le motif volatil parle de la forme normalisée
    normalized = {re.sub(r"\d+(?:[.,]\d+)?", "#", c) for c in controls}
    here = _VOLATILE_ON.get(page)
    return sorted(c for c in normalized if not _VOLATILE.search(c) and not (here and here.search(c)))


def looks_french(line):
    return len(_FR.findall(line)) >= 3 or bool(_FR_UI.search(line))


def brand_misspelt(text):
    return [ln.strip()[:100] for ln in text.splitlines() if "GoleM" in _BRAND_OK.sub("", ln)]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def working_tree_commit():
    """Un commit FANTÔME de l'arbre de travail (fichiers modifiés et nouveaux compris), sans toucher ni la branche ni
    l'index : un index temporaire, `write-tree`, `commit-tree`. C'est ce qui permet de vérifier au rendu AVANT de
    committer (CLAUDE.md règle 3) — le worktree jetable se fait sur ce commit au lieu de HEAD."""
    with tempfile.NamedTemporaryFile(prefix="golem-ui-index-", delete=False) as f:
        idx = f.name
    os.unlink(idx)
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    g = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], env=env, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    try:
        g("read-tree", "HEAD")
        g("add", "-A", ".")
        tree = g("write-tree")
        return g("commit-tree", tree, "-p", "HEAD", "-m", "golem ui check: working tree")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(idx)


class Bridge:
    """Un bridge jetable sur un DÉPÔT jetable : un `git worktree` de HEAD (ce que la CI a : contenu d'usine, pack de
    test, rien de l'utilisateur — l'inventaire des boutons est alors le même ici et sur le runner), runtime et dossier
    REAPER temporaires, ports libres, pas d'annonce mDNS ; arrêté et nettoyé à la sortie."""

    def __init__(self, test_content=False, rev="HEAD"):
        self.tmp = tempfile.TemporaryDirectory(prefix="golem-ui-check-")
        self.rev = rev                                   # HEAD, ou le commit fantôme de l'arbre de travail (--working-tree)
        self.port = free_port()
        self.proc = None
        self.root = Path(self.tmp.name) / "root"
        self.log = Path(self.tmp.name) / "bridge.log"
        self.test_content = test_content

    def __enter__(self):
        runtime, resource = Path(self.tmp.name) / "runtime", Path(self.tmp.name) / "REAPER"
        runtime.mkdir(); resource.mkdir()
        subprocess.run(["git", "-C", str(ROOT), "worktree", "prune"], check=False, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "-f", "-q", str(self.root), self.rev], check=True)
        # ses ports OSC aussi : sur un poste où le vrai golem tourne, 8000/9000 sont pris (WinError 10048)
        env = {**os.environ, "GOLEM_RUNTIME_DIR": str(runtime), "GOLEM_REAPER_RESOURCE_DIR": str(resource),
               "GOLEM_PORT": str(self.port), "GOLEM_OSC_RECV": str(free_port()), "GOLEM_OSC_SEND": str(free_port()),
               "GOLEM_NO_REACH": "1", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
               # 2026-10-31 : sans lui, le banc ouvrait le pédalier du rack voisin (bank 0 + LEDs SW6-8 → stomps du live)
               "GOLEM_NO_HW_MIDI": "1"}
        self.env = env
        subprocess.run([sys.executable, "-c", "from bridge import factory; factory.seed()"], cwd=self.root, env=env,
                       check=True, capture_output=True, timeout=600)
        if self.test_content:
            subprocess.run([sys.executable, "-m", "bridge.test_content", "install"], cwd=self.root, env=env,
                           check=True, capture_output=True, timeout=120)
        self._logf = self.log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "bridge.app:app", "--host", "127.0.0.1",
                                      "--port", str(self.port)], cwd=self.root, env=env,
                                     stdout=self._logf, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 40
        try:
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"bridge exited with {self.proc.returncode}:\n{self.tail()}")
                try:
                    with urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=0.5) as r:
                        if r.status == 200 and json.load(r).get("ok") is True:
                            return f"http://127.0.0.1:{self.port}"
                except (URLError, TimeoutError, OSError):
                    time.sleep(0.2)
            raise RuntimeError(f"bridge not ready after 40 s:\n{self.tail()}")
        except Exception:
            self.__exit__(None, None, None)                                # tue, ferme le journal, nettoie
            raise

    def tail(self):
        try:
            self._logf.flush()
            return self.log.read_text(encoding="utf-8", errors="replace")[-3000:]
        except OSError:
            return ""

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, check=False, timeout=10)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait()
        self._logf.close()
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(self.root)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(ROOT), "worktree", "prune"], check=False, stdout=subprocess.DEVNULL)
        self.tmp.cleanup()


def visit(page, url, size, settle_ms):
    """Ouvre une page, attend qu'elle se pose, et rend ce que l'on a vu : erreurs, défilement, texte, hash final."""
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
    page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error"
            and not any(n in m.text for n in _CONSOLE_NOISE) else None)
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(url, wait_until="load")
    page.wait_for_timeout(settle_ms)
    metrics = page.evaluate("""() => {
        // l'INVENTAIRE de ce qui s'actionne sur la page : tag, rôle, nom accessible (aria-label, texte, title,
        // placeholder) — ce que le fichier tests/ui/inventory.json tient comme contrat de la surface
        const seen = new Set(), controls = [];
        for (const el of document.querySelectorAll('button, a[href], input, select, textarea, [role=button], [role=tab], [role=menuitem], [role=switch]')) {
          if (!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)) continue;   // invisible : pas un bouton pour l'humain
          // une liste déroulante se nomme par son étiquette, jamais par le texte de ses options (du contenu, instable)
          const name = (el.tagName === 'SELECT'
            ? (el.getAttribute('aria-label') || el.getAttribute('title') || el.name || el.id || '')
            : (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || el.getAttribute('placeholder') || el.value || ''))
            .replace(/\\s+/g, ' ').trim().slice(0, 48);
          const role = el.getAttribute('role') || (el.tagName === 'INPUT' ? 'input:' + (el.type || 'text') : el.tagName.toLowerCase());
          const key = role + ' | ' + (name || '(unnamed)');
          if (seen.has(key)) continue;
          seen.add(key); controls.push(key);
        }
        return { sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight,
                 iw: innerWidth, ih: innerHeight, hash: location.hash, search: location.search,
                 text: document.body.innerText, nodes: controls.length, controls };
    }""")
    return errors, metrics


def check(base, out, settle_ms, pages_rack, pages_phone, log):
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    writes, report = [], []

    def guard(route):
        if route.request.method in ("POST", "PUT", "DELETE", "PATCH"):
            writes.append(route.request.method + " " + route.request.url.split("/api/", 1)[-1])
            return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        return route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        for kind, size, pages in (("rack", RACK, pages_rack), ("phone", PHONE, pages_phone)):
            for target in pages:
                url = base + ("/app/" + target if target.startswith("#") else target)
                page = browser.new_page(viewport={"width": size[0], "height": size[1]})
                page.route("**/api/**", guard)
                try:
                    errors, m = visit(page, url, size, settle_ms)
                except Exception as e:                                 # la page n'a pas chargé : c'est un manquement
                    errors, m = [f"load: {e}"], {"sw": 0, "sh": 0, "iw": size[0], "ih": size[1], "hash": "", "search": "",
                                                "text": "", "nodes": 0}
                name = re.sub(r"[^A-Za-z0-9]+", "-", target).strip("-") or "root"
                shot = out / f"{kind}-{name}.png"
                try:
                    page.screenshot(path=str(shot))
                except Exception:
                    pass
                page.close()
                issues = list(errors)
                if kind == "rack" and (m["sh"] > m["ih"] or m["sw"] > m["iw"]):
                    issues.append(f"scrolls: {m['sw']}×{m['sh']} in {m['iw']}×{m['ih']}")
                if kind == "phone" and m["sw"] > m["iw"]:
                    issues.append(f"scrolls horizontally: {m['sw']} in {m['iw']}")
                french = [ln.strip() for ln in m["text"].splitlines() if looks_french(ln)]
                if french:
                    issues.append("french on screen: " + " | ".join(french[:3]))
                brand = brand_misspelt(m["text"])
                if brand:
                    issues.append("brand written « GoleM »: " + " | ".join(brand[:3]))
                # l'écran /loading (bridge sans moteur) n'a rien à toucher : c'est voulu
                if m["nodes"] == 0 and not re.search(r"/\s*loading", m["text"]):
                    issues.append("nothing interactive rendered")
                landed = m["hash"] if target.startswith("#") else m["search"]
                note = "" if (not target.startswith("#") or landed == target or landed.startswith(target)) else f"landed on {landed}"
                # les chiffres d'un nom (« Banks 6 », « 0.3 s ») sont du contenu, pas de la surface : normalisés
                controls = stable_controls(m.get("controls") or [], target)
                report.append({"kind": kind, "page": target, "ok": not issues, "issues": issues, "landed": note,
                               "screenshot": shot.name, "controls": controls})
                log(("  ok   " if not issues else "  FAIL ") + f"{kind:5} {target:36} {note}" + ("" if not issues else "\n" + "\n".join("         " + i for i in issues)))
        browser.close()
    return report, writes


# ── les attentes par commande (docs/quality-automation.md §8) ────────────────────────────────────────────────────
# Appuyer sur chaque commande d'une page et NOTER son effet, en quatre familles : une navigation (le hash change),
# une ouverture (un dialogue, tiroir ou fiche apparaît), des appels à l'API (méthode + chemin, interceptés, jamais
# exécutés), rien de visible. Deux fichiers : tests/ui/effects-<platform>.json, l'effet OBSERVÉ de chaque commande,
# généré (--press all --update-effects) et comparé (un effet qui change fait tomber la sonde) ; tests/ui/expectations.json,
# écrit à la main pour les commandes qui comptent : ce qu'on EXIGE (navigates_to, opens, api, writes_nothing), et qui
# se vérifie vite (--press declared) à chaque push. Toujours : aucune erreur de page, aucune écriture non déclarée.
PRESSABLE = "button, a[href]:not([target=_blank]):not([href^='http']):not([download]), [role=button], [role=tab], [role=menuitem], [role=switch]"
_FIND_JS = """(args) => {
    const [sel, key] = args;
    const norm = s => s.replace(/\\d+(?:[.,]\\d+)?/g, '#');
    // la marque d'un appui précédent sur la même page (pas rechargée) ferait cliquer le MAUVAIS bouton (.first)
    for (const el of document.querySelectorAll('[data-golem-press]')) el.removeAttribute('data-golem-press');
    for (const el of document.querySelectorAll(sel)) {
      if (!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)) continue;
      const name = (el.tagName === 'SELECT'
        ? (el.getAttribute('aria-label') || el.getAttribute('title') || el.name || el.id || '')
        : (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || el.getAttribute('placeholder') || el.value || ''))
        .replace(/\\s+/g, ' ').trim().slice(0, 48);
      const role = el.getAttribute('role') || (el.tagName === 'INPUT' ? 'input:' + (el.type || 'text') : el.tagName.toLowerCase());
      if (norm(role + ' | ' + (name || '(unnamed)')) === key) { el.scrollIntoView({block: 'center'}); el.setAttribute('data-golem-press', '1'); return true; }
    }
    return false;
}"""
_LIST_JS = """(sel) => [...document.querySelectorAll(sel)]
    .filter(el => el.offsetWidth || el.offsetHeight || el.getClientRects().length)
    .map(el => ((el.getAttribute('role') || (el.tagName === 'INPUT' ? 'input:' + (el.type || 'text') : el.tagName.toLowerCase())) + ' | ' +
      (((el.tagName === 'SELECT'
          ? (el.getAttribute('aria-label') || el.getAttribute('title') || el.name || el.id || '')
          : (el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || el.getAttribute('placeholder') || el.value || ''))
        .replace(/\\s+/g, ' ').trim().slice(0, 48)) || '(unnamed)')))"""
_OPEN_JS = """() => [...document.querySelectorAll('[role=dialog], dialog[open], .modal, .drawer, .sheet, .overlay, .popover, .menu')]
    .filter(el => el.offsetWidth || el.offsetHeight).length"""


def press_page(page, base, target, size, settle_ms, writes, keys, log, dialogs=None):
    """Appuie sur chaque commande de la page (celles de `keys`, ou toutes), repart d'une page fraîche dès qu'un appui
    a eu un effet, et rend {clé: effet} avec effet = {hash, at, opens, api[], errors[], confirms?, becomes?}."""
    dialogs = dialogs if dialogs is not None else []
    url = base + ("/app/" + target if target.startswith("#") else target)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def fresh():
        # un goto vers la même page avec un autre hash ne RECHARGE pas le document (navigation dans le même document :
        # l'app garderait son état, et le hub réécrirait le hash) : on passe par about:blank pour repartir de zéro
        page.goto("about:blank")
        page.goto(url, wait_until="load")
        page.wait_for_timeout(settle_ms)
        return page.evaluate("() => location.hash"), page.evaluate(_OPEN_JS)
    hash0, open0 = fresh()
    present = stable_controls(page.evaluate(_LIST_JS, PRESSABLE))
    todo = [k for k in present if keys is None or k in keys]
    out, dirty = {}, False
    for key in todo:
        if dirty:
            hash0, open0 = fresh(); dirty = False
        del writes[:]; del errors[:]; del dialogs[:]
        hash0, open0 = page.evaluate("() => location.hash"), page.evaluate(_OPEN_JS)   # juste avant l'appui
        found = page.evaluate(_FIND_JS, [PRESSABLE, key])
        for _ in range(3):                                   # une liste qui se remplit après le chargement : on lui laisse une seconde
            if found:
                break
            page.wait_for_timeout(700)
            found = page.evaluate(_FIND_JS, [PRESSABLE, key])
        if not found:
            out[key] = {"missing": True}; continue
        names_before = set(page.evaluate(_LIST_JS, PRESSABLE))
        covered = False
        try:
            page.locator("[data-golem-press='1']").first.click(timeout=2000, no_wait_after=True)
        except Exception:
            # recouvert (un voile d'attente du moteur, un tiroir) : on appuie quand même, et on le DIT — le vrai bridge
            # de la nuit n'a pas ce voile ; une commande injoignable pour de bon reste une erreur
            try:
                # dispatch_event, pas un clic forcé : un clic forcé frappe aux coordonnées, donc ce qui RECOUVRE ;
                # l'événement envoyé à l'élément lui-même déclenche son gestionnaire malgré le voile
                page.locator("[data-golem-press='1']").first.dispatch_event("click", timeout=2000)
                covered = True
            except Exception as e:
                out[key] = {"error": f"click: {str(e).splitlines()[0][:120]}"}; dirty = True; continue
        page.wait_for_timeout(450)
        try:
            hash1, open1 = page.evaluate("() => location.hash"), page.evaluate(_OPEN_JS)
            # une commande en DEUX temps (« ⏻ Stop golem » -> « Stop golem — sure? », « 🗑 » -> « sure? ») : une QUESTION
            # apparaît quelque part sur la page. On ne suit pas l'élément appuyé (Preact réutilise les nœuds au rendu
            # suivant : il porterait un autre bouton) — on cherche les noms qui finissent par « ? » et qui n'y étaient pas
            asks = [n for n in page.evaluate(_LIST_JS, PRESSABLE) if n.rstrip().endswith("?") and n not in names_before]
        except Exception:
            hash1, open1, asks = "?", 0, []                  # la page a navigué hors de l'app (rare) : on repart
        api = sorted({w.split(" ", 1)[0] + " " + re.sub(r"\?.*$", "", w.split(" ", 1)[1]) for w in writes})
        eff = {"hash": hash1 if hash1 != hash0 else None, "at": hash1, "opens": bool(open1 > open0), "api": api, "errors": list(errors)}
        if dialogs:
            eff["confirms"] = list(dialogs)                    # un confirm()/alert() natif, refusé par la sonde
        if asks:
            eff["asks"] = [a.split(" | ", 1)[1] for a in asks]  # « Stop golem — sure? », « change the foot? »
        if covered:
            eff["covered"] = True
        out[key] = eff
        dirty = bool(eff["hash"] or eff["opens"] or api or errors or dialogs or asks or hash1 == "?")
        if not dirty:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
    return out


def press(base, out_dir, pages, settle_ms, log, effects_path, update, expectations_path, declared_only):
    """La tournée des appuis sur les pages du rack ; rend (effets observés, problèmes)."""
    from playwright.sync_api import sync_playwright
    expectations = json.loads(expectations_path.read_text(encoding="utf-8")) if expectations_path.exists() else {}
    known = json.loads(effects_path.read_text(encoding="utf-8")) if effects_path.exists() else {}
    observed, problems, writes = {}, [], []

    def guard(route):
        if route.request.method in ("POST", "PUT", "DELETE", "PATCH"):
            writes.append(route.request.method + " " + route.request.url.split("/api/", 1)[-1])
            return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        return route.continue_()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": RACK[0], "height": RACK[1]})
        page.route("**/api/**", guard)
        dialogs = []
        # un confirm()/alert()/prompt() natif : noté, puis REFUSÉ — la sonde ne confirme jamais rien
        page.on("dialog", lambda d: (dialogs.append(f"{d.type}: {d.message[:80]}"), d.dismiss()))
        for target in pages:
            # « * » : les attentes valables sur TOUTES les pages (la barre du haut) ; la page peut en préciser d'autres
            wanted = {**(expectations.get("*") or {}), **(expectations.get(target) or {})}
            keys = None
            if declared_only:
                keys = set(wanted)
                if not keys:
                    continue
            t0 = time.monotonic()
            effects = press_page(page, base, target, RACK, settle_ms, writes, keys, log, dialogs=dialogs)
            observed[target] = effects
            # 1. les attentes écrites à la main : ce qu'on EXIGE
            for key, want in wanted.items():
                got = effects.get(key)
                if got is None:
                    if key not in (expectations.get(target) or {}):
                        continue                         # une attente « * » sur une page qui n'a pas ce bouton (/live sans moteur : pas de barre)
                    problems.append(f"{target} · {key}: control not found"); continue
                if got.get("missing") or got.get("error"):
                    problems.append(f"{target} · {key}: {got.get('error') or 'not clickable'}"); continue
                # navigates_to : la page où l'on EST après l'appui (déjà là compris : un hub depuis son propre hub)
                if want.get("navigates_to") and not str(got.get("at") or "").startswith(want["navigates_to"]):
                    problems.append(f"{target} · {key}: expected to land on {want['navigates_to']}, landed on {got.get('at')!r}")
                if want.get("navigates") is True and not got.get("hash"):
                    problems.append(f"{target} · {key}: expected to navigate somewhere, hash unchanged")
                if want.get("opens") is True and not got.get("opens"):
                    problems.append(f"{target} · {key}: expected to open a dialog or drawer")
                if want.get("api") is not None and sorted(want["api"]) != got.get("api"):
                    problems.append(f"{target} · {key}: expected API {want['api']}, got {got.get('api')}")
                if want.get("writes_nothing") and got.get("api"):
                    problems.append(f"{target} · {key}: wrote {got['api']} but must write nothing")
                # une commande DANGEREUSE doit d'abord demander : un confirm() natif (refusé par la sonde), ou un bouton
                # en deux temps dont le nom change (« Stop golem — sure? ») — et n'avoir rien écrit entre-temps
                if want.get("confirms") is True and not got.get("confirms"):
                    problems.append(f"{target} · {key}: expected a native confirmation, got none")
                if want.get("asks") is True and not got.get("asks"):
                    problems.append(f"{target} · {key}: expected a two-step question (« … ? ») to appear, got none")
            # 2. toujours : aucune erreur de page ; et un effet OBSERVÉ qui change par rapport au fichier
            for key, got in effects.items():
                if got.get("errors"):
                    problems.append(f"{target} · {key}: page error — {got['errors'][0][:140]}")
                before = (known.get(target) or {}).get(key)
                if before and not update and not declared_only:
                    cmp_b = {k: before.get(k) for k in ("hash", "opens", "api", "confirms", "asks")}
                    cmp_g = {k: got.get(k) for k in ("hash", "opens", "api", "confirms", "asks")}
                    if cmp_b != cmp_g and not got.get("error") and not before.get("error"):
                        problems.append(f"{target} · {key}: effect changed — was {cmp_b}, now {cmp_g}")
            n_bad = sum(1 for e in effects.values() if e.get("errors") or e.get("error"))
            log(f"  press {target:36} {len(effects):4} controls, {n_bad} with errors, {round(time.monotonic() - t0, 1)} s")
        browser.close()
    if update or (not effects_path.exists() and not declared_only):
        effects_path.parent.mkdir(parents=True, exist_ok=True)
        merged = {**known, **observed}
        effects_path.write_text(json.dumps(merged, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        log(f"effects written: {effects_path} ({sum(len(v) for v in merged.values())} controls)")
    return observed, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="un bridge déjà lancé (ex. http://localhost:8770) ; sinon un bridge jetable")
    ap.add_argument("--working-tree", action="store_true",
                    help="le bridge jetable part de l'ARBRE DE TRAVAIL (modifs non committées comprises), pas de HEAD")
    ap.add_argument("--out", default=str(ROOT / "assets" / ".cache" / "ui-check"), help="dossier des captures")
    ap.add_argument("--json", help="écrire le rapport ici")
    ap.add_argument("--settle", type=int, default=1200, help="ms d'attente après le chargement (défaut 1200)")
    ap.add_argument("--only", help="ne visiter que les pages contenant ce texte")
    ap.add_argument("--test-content", action="store_true",
                    help="poser le pack de test (bridge/test_content.py) avant, le retirer après — les pages ont alors un terrain connu")
    # un inventaire PAR SYSTÈME : les pages Settings n'offrent pas les mêmes commandes sous Linux, Windows et macOS
    ap.add_argument("--inventory", type=Path, default=ROOT / "tests" / "ui" / f"inventory-{sys.platform}.json",
                    help="le contrat de la surface : les boutons de chaque page (défaut tests/ui/inventory-<platform>.json)")
    ap.add_argument("--update-inventory", action="store_true", help="réécrire l'inventaire avec ce qui a été vu")
    ap.add_argument("--no-inventory", action="store_true", help="ne pas comparer à l'inventaire")
    g = ap.add_argument_group("attentes par commande")
    g.add_argument("--press", choices=["declared", "all"], help="appuyer sur les commandes : celles de expectations.json (vite), ou toutes")
    g.add_argument("--expectations", type=Path, default=ROOT / "tests" / "ui" / "expectations.json", help="ce qu'on exige, écrit à la main")
    g.add_argument("--effects", type=Path, default=ROOT / "tests" / "ui" / f"effects-{sys.platform}.json", help="l'effet observé de chaque commande")
    g.add_argument("--update-effects", action="store_true", help="réécrire les effets observés (après un changement voulu)")
    a = ap.parse_args()
    rack = [p for p in RACK_PAGES if not a.only or a.only in p]
    phone = [p for p in PHONE_PAGES if not a.only or a.only in p]
    out = Path(a.out)
    t0 = time.monotonic()
    installed = None
    if a.test_content and a.base:
        # contre un bridge VIVANT : le pack se pose dans son dépôt, par le registre, et se retire quoi qu'il arrive
        sys.path.insert(0, str(ROOT))
        from bridge import test_content
        installed = test_content.install()
        print(f"test content: {len(installed['placed'])} placed, {len(installed['kept'])} kept (song {installed['song_id']})")
    pressed, press_problems = {}, []

    def run(base):
        rep, wr = check(base, out, a.settle, rack, phone, print)
        if a.press:
            obs, probs = press(base, out, rack, a.settle, print, a.effects, a.update_effects, a.expectations, a.press == "declared")
            pressed.update(obs); press_problems.extend(probs)
        return rep, wr
    try:
        if a.base:
            print(f"golem ui check against {a.base} (writes intercepted)")
            report, writes = run(a.base.rstrip("/"))
        else:
            with Bridge(test_content=a.test_content, rev=working_tree_commit() if a.working_tree else "HEAD") as base:
                print(f"golem ui check: disposable bridge on {base} (fresh worktree, factory content"
                      + (", test content)" if a.test_content else ")"))
                report, writes = run(base)
    finally:
        if installed is not None:
            gone = test_content.remove()
            print(f"test content: {len(gone['removed'])} removed" + (f", {len(gone['missing'])} already gone" if gone["missing"] else ""))
    bad = [r for r in report if not r["ok"]]
    if press_problems:
        bad.append({"page": "press", "issues": press_problems})
        print("  FAIL press:\n" + "\n".join("         " + p for p in press_problems[:40]) + ("" if len(press_problems) <= 40 else f"\n         … {len(press_problems) - 40} more"))
    elif pressed:
        print(f"  ok   press — {sum(len(v) for v in pressed.values())} controls pressed on {len(pressed)} pages, no page error, effects as expected")
    # l'inventaire : un bouton qui disparaît ou perd son nom fait tomber la sonde ; un nouveau est dit, et entre dans le
    # contrat par --update-inventory (relu par un humain : c'est un changement de surface)
    seen = {r["page"]: sorted(r["controls"]) for r in report if r["kind"] == "rack"}
    inventory_note = ""
    # l'inventaire est relevé AVEC le pack de test (comme la CI) : sans lui, ses boutons « manquent » toujours
    if not a.no_inventory and not a.only and not a.test_content and not a.update_inventory:
        inventory_note = "inventory not compared (it is taken with --test-content, as CI runs it)"
        print(f"  note {inventory_note}")
    elif not a.no_inventory and not a.only:
        if a.update_inventory or not a.inventory.exists():
            a.inventory.parent.mkdir(parents=True, exist_ok=True)
            a.inventory.write_text(json.dumps(seen, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            inventory_note = f"inventory written: {a.inventory} ({sum(len(v) for v in seen.values())} controls)"
        else:
            want = {p: stable_controls(c, p) for p, c in json.loads(a.inventory.read_text(encoding="utf-8")).items()}
            missing = {p: sorted(set(c) - set(seen.get(p, []))) for p, c in want.items() if set(c) - set(seen.get(p, []))}
            new = {p: sorted(set(c) - set(want.get(p, []))) for p, c in seen.items() if set(c) - set(want.get(p, []))}
            if missing:
                bad.append({"page": "inventory", "issues": [f"{p}: gone — {', '.join(c)}" for p, c in missing.items()]})
                print("  FAIL inventory — controls gone:\n" + "\n".join(f"         {p}: {', '.join(c)}" for p, c in missing.items()))
            if new:
                print("  note inventory — new controls (add them with --update-inventory):\n"
                      + "\n".join(f"         {p}: {', '.join(c)}" for p, c in new.items()))
            inventory_note = f"inventory: {sum(len(v) for v in want.values())} known, {sum(len(v) for v in missing.values())} gone, {sum(len(v) for v in new.values())} new"
    if a.inventory.exists():
        shutil.copy2(a.inventory, out / a.inventory.name)        # dans l'artefact de la CI : le premier inventaire d'un OS se commit depuis là
    summary = {"pages": len(report), "failed": len(bad), "seconds": round(time.monotonic() - t0, 1),
               "writes_blocked": writes, "screenshots": str(out), "inventory": inventory_note,
               "press_problems": press_problems, "pressed": {p: len(v) for p, v in pressed.items()}, "report": report}
    if a.json:
        Path(a.json).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(report)} pages, {len(bad)} failed, {len(writes)} writes blocked, {summary['seconds']} s — screenshots in {out}"
          + (f"; {inventory_note}" if inventory_note else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
