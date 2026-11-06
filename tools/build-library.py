#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
build-library — peuple la bibliothèque d'amplis GoleM depuis TONE3000.

Sources :
  • tools/classify-data/legendary-amps.json  (wishlist)  -> top captures par ampli
  • users "nommés" (pris en entier)                  -> --named
  • users "suivis" par klm314 (top N par downloads)  -> --followed

Sorties :
  • assets/models/<creator>/<tone_id>_<slug>/<model>.nam   (gitignored — captures tierces)
  • library/catalog/tones-index.json   (métadonnées taguées — COMMITÉ, aucune capture)

Reprenable : skip les fichiers déjà présents ; fusionne avec l'index existant.
Rate-limit : pause entre appels API (l'API T3K est limitée).

  ./tools/build-library.py --scope klm314          # test : un seul user
  ./tools/build-library.py --named --followed --wishlist   # tout
  ./tools/build-library.py --all --top 5
  ./tools/build-library.py --dry-run --all         # ne télécharge rien, liste le plan
"""
import sys, os, re, json, time, argparse, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t3k

ROOT = t3k.ROOT
RATE = 1.3   # s entre appels API (l'anti-bot T3K throttle bien en dessous de 100/min)
WISHLIST = os.path.join(ROOT, "tools", "classify-data", "legendary-amps.json")   # versionné, livré avec classify.py
INDEX = os.path.join(ROOT, "library", "catalog", "tones-index.json")
PICKS_CACHE = os.path.join(ROOT, "library", "catalog", ".picks-cache.json")

NAMED_USERS = ["klm314", "ampspedalspickups"]
# users suivis par klm314 (scrapés le 2026-06-29 ; brianbuckles a 0 tone -> omis)
FOLLOWED_USERS = ["resington", "sinmix", "primalnerd", "arlingtonaudio", "elgringoloco",
                  "drewhast", "strangeangles", "dogusaltin", "deathblossomaudio",
                  "2dor", "mattvdh", "blackstaramps"]

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.5", "Connection": "keep-alive"}

# ── helpers ───────────────────────────────────────────────────────────────────
def safe_refresh():
    """Refresh OAuth résilient : l'endpoint token est aussi anti-botté (403 transitoire).
    t3k.refresh() fait sys.exit sur non-200 -> on l'attrape et on retente, jamais fatal."""
    for i in range(5):
        try:
            return t3k.refresh()
        except SystemExit:
            wait = 20 * (i + 1)
            print(f"  …token endpoint throttlé, backoff {wait}s")
            time.sleep(wait)
    return t3k.access_token()  # on garde l'ancien token, tant pis

def api(path):
    """GET API avec rate-limit + backoff exponentiel sur 429/403/5xx, jamais fatal."""
    st = res = None
    for attempt in range(6):
        time.sleep(RATE)
        try:
            st, res = t3k.api_get(path)
        except SystemExit:          # un refresh interne a échoué -> on retente
            safe_refresh(); continue
        if st in (429, 500, 502, 503, 403):
            wait = 20 * (attempt + 1)   # 20,40,60,80,100 — vide la fenêtre de throttle
            print(f"  …API {st}, backoff {wait}s ({path[:50]})")
            time.sleep(wait); continue
        return st, res
    return st, res

def slugify(s):
    s = re.sub(r"[^\w\- ]", "", s).strip().lower()
    return re.sub(r"[\s_]+", "-", s)[:60] or "tone"

def style_of(tags):
    t = {x.lower() for x in tags}
    for s in ("metal", "blues", "jazz", "funk", "bass"):
        if s in t:
            return s
    return "rock"

def scrape_user_tone_ids(username):
    """IDs des tones publics affichés sur la page profil (ordre d'affichage préservé).
    Backoff sur 403/429/503 (anti-bot du site se déclenche sur les rafales)."""
    url = f"https://www.tone3000.com/{username}"
    html = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            html = urllib.request.urlopen(req, timeout=30).read().decode(errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 503) and attempt < 4:
                wait = 8 * (attempt + 1)
                print(f"  …scrape {username} {e.code}, backoff {wait}s")
                time.sleep(wait); continue
            print(f"  ✗ scrape {username}: {e}"); return []
        except Exception as e:
            print(f"  ✗ scrape {username}: {e}"); return []
    if not html:
        return []
    seen, out = set(), []
    for m in re.finditer(r'/tones/[a-z0-9][a-z0-9\-]*-(\d+)(?=["/\\?\s])', html):
        i = int(m.group(1))
        if i not in seen:
            seen.add(i); out.append(i)
    return out

def tone_meta(tid):
    st, t = api(f"/api/v1/tones/{tid}")
    return t if st == 200 and isinstance(t, dict) else None

def tone_models(tid):
    # défaut = A1+Custom ; si vide, retenter en A2 (les tones récents sont architecture 2)
    for extra in ("", "&architecture=2"):
        st, r = api(f"/api/v1/models?tone_id={tid}&page_size=100{extra}")
        data = r.get("data", r if isinstance(r, list) else []) if st == 200 else []
        if data:
            return data
    return []

def download(murl, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "skip"
    st = None
    for attempt in range(5):
        time.sleep(RATE)          # pause AUSSI sur chaque download (sinon rafale -> anti-bot)
        tok = t3k.access_token()
        st, blob = t3k.http_json("GET", murl, headers={"Authorization": f"Bearer {tok}"}, raw=True)
        if st == 200:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "wb").write(blob)
            return "ok"
        if st == 401:             # vrai problème d'auth -> refresh (résilient)
            safe_refresh(); continue
        if st == 403 and "error code: 1010" in str(blob):
            # Cloudflare a BANNI ce client (signature refusée — l'UA « Python-urllib », PC Windows 2026-11-03) : ce
            # n'est pas une rafale, réessayer ne change rien et coûtait ~4 min de pauses par capture. On dit pourquoi.
            return "err403 (TONE3000 refused this client: Cloudflare 1010)"
        if st in (429, 500, 502, 503, 403):   # anti-bot : backoff, PAS de refresh
            time.sleep(20 * (attempt + 1)); continue
        break
    return f"err{st}"

# ── sélection des tones ────────────────────────────────────────────────────────
def from_wishlist(top):
    """Pour chaque ampli de la wishlist : top captures amp/amp-cab par downloads."""
    cat = json.load(open(WISHLIST))
    picks = {}  # tone_id -> reason
    for cname, cdata in cat["categories"].items():
        for amp in cdata["amps"]:
            q = urllib.parse.urlencode({"query": amp["search"], "gears": "amp_amp-cab",
                                        "sort": "downloads-all-time", "page_size": 25})
            st, res = api(f"/api/v1/tones/search?{q}")
            items = res.get("data", []) if isinstance(res, dict) else []
            took = 0
            for it in items:
                if took >= top: break
                picks.setdefault(it["id"], f"wishlist:{amp['make']}")
                took += 1
            print(f"  wishlist {amp['make']:<32} -> {took} captures")
    return picks

def from_users(users, full, top):
    """full=True : tous les tones du user. Sinon : les `top` premiers dans l'ordre
    d'affichage du profil (T3K trie par popularité) — 0 appel API de classement,
    on évite l'anti-bot. La méta réelle est récupérée plus tard dans pull()."""
    picks = {}
    for u in users:
        ids = scrape_user_tone_ids(u)
        chosen = ids if full else ids[:top]
        for tid in chosen:
            picks.setdefault(tid, ("named:" if full else "follow:") + u)
        print(f"  user {u:<20} {len(ids):>3} tones -> {len(chosen)} retenus")
    return picks

# ── pull ────────────────────────────────────────────────────────────────────
def load_index():
    if os.path.exists(INDEX):
        return {str(e["id"]): e for e in json.load(open(INDEX)).get("tones", [])}
    return {}

def save_index(idx):
    tones = sorted(idx.values(), key=lambda e: (-e.get("downloads", 0), e["id"]))
    by_style, by_creator = {}, {}
    for e in tones:
        by_style[e["style"]] = by_style.get(e["style"], 0) + 1
        by_creator[e["creator"]] = by_creator.get(e["creator"], 0) + 1
    out = {"_comment": "Catalogue des tones tirés de TONE3000. Métadonnées seulement — "
                       "les .nam vivent dans assets/ (gitignored). Régénérable via tools/build-library.py.",
           "stats": {"tones": len(tones), "models": sum(len(e["models"]) for e in tones),
                     "by_style": by_style, "by_creator": by_creator},
           "tones": tones}
    json.dump(out, open(INDEX, "w"), ensure_ascii=False, indent=2)

def pull(picks, dry, max_models):
    idx = load_index()
    # tronque les packs déjà en index au plafond (anti-bloat rétroactif)
    for e in idx.values():
        e["models"] = e.get("models", [])[:max_models]
    print(f"\n→ {len(picks)} tones à traiter (index actuel : {len(idx)} tones, cap {max_models} mdl)\n")
    n_dl = n_skip = n_err = n_done = 0
    for i, (tid, reason) in enumerate(sorted(picks.items()), 1):
        if str(tid) in idx and idx[str(tid)].get("models"):
            n_done += 1
            continue  # déjà tiré -> reprise instantanée, zéro appel API
        meta = tone_meta(tid)
        if not meta:
            print(f"[{i}/{len(picks)}] tone {tid} introuvable"); continue
        title = meta.get("title", f"tone-{tid}")
        creator = (meta.get("user") or {}).get("username", "unknown")
        tags = [t["name"] for t in meta.get("tags", [])]
        makes = [m["name"] for m in meta.get("makes", [])]
        gear = meta.get("gear", "")
        fmt = meta.get("format", "nam")
        sub = "irs" if fmt == "ir" else "models"
        slug = slugify(title)
        reldir = os.path.join("assets", sub, creator, f"{tid}_{slug}")
        models = tone_models(tid)[:max_models]   # plafond anti-bloat
        entry = {"id": tid, "title": title, "slug": slug, "creator": creator,
                 "url": meta.get("url", f"{t3k.API}/tones/{tid}"),
                 "gear": gear, "format": fmt, "makes": makes, "tags": tags,
                 "style": style_of(tags + makes), "downloads": meta.get("downloads_count", 0),
                 "favorites": meta.get("favorites_count", 0), "source_group": reason,
                 "models": []}
        for m in models:
            murl = m.get("model_url")
            if not murl: continue
            ext = os.path.splitext(urllib.parse.urlparse(murl).path)[1] or (".wav" if fmt == "ir" else ".nam")
            mname = slugify(m.get("name") or title) + ext
            rel = os.path.join(reldir, mname)
            dest = os.path.join(ROOT, rel)
            if dry:
                res = "DRY"
            else:
                res = download(murl, dest)
            if res == "ok": n_dl += 1
            elif res == "skip": n_skip += 1
            elif res.startswith("err"): n_err += 1; print(f"      ✗ {mname}: {res}")
            entry["models"].append({"id": m.get("id"), "name": m.get("name"),
                                    "file": rel, "size": m.get("size"),
                                    "arch": m.get("architecture_version")})
        idx[str(tid)] = entry
        print(f"[{i}/{len(picks)}] {title[:42]:<42} {creator:<16} {gear:<8} "
              f"{len(entry['models'])}mdl [{reason}]")
        if not dry and i % 10 == 0:
            save_index(idx)  # checkpoint
    if not dry:
        save_index(idx)
    print(f"\n✓ terminé. déjà-en-index={n_done} téléchargés={n_dl} skip={n_skip} err={n_err}  index={len(idx)} tones")

# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--wishlist", action="store_true")
    p.add_argument("--named", action="store_true")
    p.add_argument("--followed", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--scope", help="un seul username (test)")
    p.add_argument("--top", type=int, default=5, help="captures/ampli (wishlist) et tones/user suivi")
    p.add_argument("--max-models", type=int, default=8, help="plafond modèles/tone (anti-bloat)")
    p.add_argument("--resume", action="store_true", help="charge les picks du cache (saute la sélection)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    picks = {}
    if a.resume and os.path.exists(PICKS_CACHE):
        picks = {int(k): v for k, v in json.load(open(PICKS_CACHE)).items()}
        print(f"→ picks chargés du cache : {len(picks)} tones (sélection sautée)")
    elif a.scope:
        picks.update(from_users([a.scope], full=True, top=a.top))
    else:
        if a.wishlist or a.all:
            picks.update(from_wishlist(min(a.top, 3)))  # 3 meilleures captures/ampli suffisent
        if a.named or a.all:
            picks.update(from_users(NAMED_USERS, full=True, top=a.top))
        if a.followed or a.all:
            picks.update(from_users(FOLLOWED_USERS, full=False, top=a.top))
    if not picks:
        sys.exit("Rien à faire. Donne --wishlist/--named/--followed/--all ou --scope <user> (ou --resume).")
    if not a.resume:
        json.dump({str(k): v for k, v in picks.items()}, open(PICKS_CACHE, "w"))  # cache pour reprise
    pull(picks, a.dry_run, a.max_models)
