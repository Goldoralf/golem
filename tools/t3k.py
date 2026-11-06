#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
t3k — client TONE3000 pour GoleM (fetcher OAuth, zéro dépendance).

  ./tools/t3k.py auth                         # OAuth une fois (ouvre le navigateur)
  ./tools/t3k.py search "5150" --gears amp    # cherche des tones
  ./tools/t3k.py fetch <tone_id> [--type ir]  # télécharge les modèles d'un tone -> assets/

Auth : OAuth 2.0 + PKCE (S256). La clé t3k_pub_ et les tokens vivent dans .env (gitignored).
Doc API : docs/private/exchanges/tone3000-api.md
"""
import sys, os, re, json, base64, hashlib, secrets, urllib.parse, urllib.request, urllib.error
import http.server, webbrowser, argparse

API = "https://www.tone3000.com"
USER_AGENT = "golem (+https://golem.fm)"      # voir http_json : sans lui, Cloudflare refuse les téléchargements
REDIRECT = "http://localhost:8765/callback"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, ".env")

# ── .env helpers ────────────────────────────────────────────────────────────
def env_read():
    d = {}
    if os.path.exists(ENV):
        with open(ENV, encoding="utf-8", errors="surrogateescape") as source:
            for line in source:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip()
    return d

# Audit 2026-10-15 (S1) : une valeur qui porte un saut de ligne AJOUTE une variable au .env — un téléphone
# appairé écrivait `x\nLD_PRELOAD=…` par la clé TONE3000, et le bridge la rechargeait au redémarrage.
# Une clé ou un jeton n'a besoin que de ces caractères ; tout le reste est refusé, pas nettoyé.
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ENV_VAL = re.compile(r"^[A-Za-z0-9_.:/+=-]{0,4096}$")


def env_set(updates):
    """Écrit .env en 0600 (il porte les jetons — audit 2026-09-13, M1) et de façon atomique."""
    for k, v in updates.items():
        if not _ENV_KEY.match(str(k)) or not _ENV_VAL.match(str(v)):
            raise ValueError(f"refused .env value for {k}")
    if os.path.exists(ENV):
        with open(ENV, encoding="utf-8", errors="surrogateescape") as source:
            lines = source.read().splitlines()
    else:
        lines = []
    keys = set(updates)
    out, seen = [], set()
    for line in lines:
        m = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if m in updates:
            out.append(f"{m}={updates[m]}"); seen.add(m)
        else:
            out.append(line)
    for k in keys - seen:
        out.append(f"{k}={updates[k]}")
    tmp = ENV + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, ENV)
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


# ── UN SEUL PROPRIÉTAIRE DU JETON (audit 2026-09-13, M2). Un refresh TONE3000 CONSOMME le refresh
# token et en rend un neuf : deux processus qui rafraîchissent chacun de leur côté (le bridge ET un
# outil CLI comme build-library) finissent par faire révoquer toute la lignée — vécu le 12/09
# (« refresh_token_already_used »), ré-autorisation humaine obligatoire. Donc :
#   · le bridge est le propriétaire (IN_BRIDGE posé par routes_t3k à l'import) ;
#   · un CLI qui trouve le bridge vivant REFUSE de rafraîchir et renvoie vers /api/t3k/… ;
#   · dans tous les cas le refresh se fait sous verrou de fichier, en RELISANT .env sous le verrou —
#     si un autre a rafraîchi entre-temps, on prend son jeton neuf au lieu de brûler le sien.
IN_BRIDGE = False
LOCK = ENV + ".lock"


def _bridge_alive():
    import urllib.request as _u
    port = os.environ.get("GOLEM_PORT", "8770")
    try:
        with _u.urlopen(f"http://127.0.0.1:{port}/api/app-build", timeout=0.5) as r:
            return r.status == 200
    except Exception:
        return False


class _env_lock:
    def __enter__(self):
        self.fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if sys.platform == "win32":
                import msvcrt
                # Lock byte zero (also valid beyond EOF). LK_LOCK retries for
                # about 10 s, then raises if another refresh still holds it.
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX)
        except BaseException:
            os.close(self.fd)
            raise
        return self

    def __exit__(self, *a):
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)

# ── HTTP helpers ────────────────────────────────────────────────────────────
def http_json(method, url, data=None, headers=None, raw=False):
    h = headers or {}
    # UN USER-AGENT QUI DIT GOLEM (PC Windows neuf, 2026-11-03) : sans lui, urllib s'annonce « Python-urllib » et le
    # Cloudflare de TONE3000 refuse /api/v1/models/<id>/download — 403 « error code: 1010 » (le même appel depuis Linux
    # passait). Un UA honnête, jamais celui d'un navigateur : c'est une API partenaire. golem.fm pose le même.
    h.setdefault("User-Agent", USER_AGENT)
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        # timeout (2026-10-24, un testeur Windows) : sans lui, un TONE3000 qui ne répond plus figeait l'install en
        # « meta » pour toujours, et chaque téléchargement suivant répondait « already running » jusqu'à la relance
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")

# ── PKCE ────────────────────────────────────────────────────────────────────
def b64url(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def pkce():
    verifier = b64url(secrets.token_bytes(64))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge

# ── Tokens ──────────────────────────────────────────────────────────────────
# l'exemple de .env.example (« t3k_pub_colle_ta_cle_ici ») copié tel quel par install.sh sur chaque golem neuf : ce
# n'est PAS une clé — l'écran Connect disait « key saved » et la connexion partait avec (VM 2026-10-23)
_PLACEHOLDER = re.compile(r"colle_ta_cle|_ici$|your[_-]?key", re.I)


def own_key():
    """La clé TONE3000 posée par l'utilisateur, ou "" (absente, ou l'exemple de .env.example)."""
    key = env_read().get("T3K_PUBLISHABLE_KEY", "").strip()
    return "" if _PLACEHOLDER.search(key) else key


def publishable_key():
    """La clé À SOI (repli « Advanced » d'un golem sans golem.fm) : sert seulement à OUVRIR une lignée."""
    key = own_key()
    if not key.startswith("t3k_pub_"):
        sys.exit("✗ T3K_PUBLISHABLE_KEY absente/invalide dans .env (Settings → API Keys).")
    return key

def client_id():
    """Le client de la LIGNÉE en cours : une lignée se rafraîchit avec le client_id qui l'a ouverte — celui que le relais
    de golem.fm a rendu (T3K_TOKEN_CLIENT, 2026-10-22), sinon la clé à soi (lignées ouvertes avant le relais)."""
    return env_read().get("T3K_TOKEN_CLIENT") or publishable_key()

def token_request(data):
    st, res = http_json("POST", f"{API}/api/v1/oauth/token", data=data)
    if st != 200:
        sys.exit(f"✗ token endpoint {st}: {res}")
    upd = {"T3K_ACCESS_TOKEN": res["access_token"], "T3K_REFRESH_TOKEN": res["refresh_token"]}
    if data.get("grant_type") == "authorization_code":
        upd["T3K_TOKEN_CLIENT"] = data["client_id"]             # le client qui ouvre la lignée la rafraîchira
    env_set(upd)
    return res["access_token"]

def access_token():
    """Renvoie un access token valide (refresh si 401)."""
    e = env_read()
    tok = e.get("T3K_ACCESS_TOKEN")
    if not tok:
        sys.exit("✗ Pas de token. Lance d'abord : ./tools/t3k.py auth")
    return tok

def refresh(stale_access=None):
    """Rafraîchit sous verrou. `stale_access` = le jeton qui vient d'être refusé : si .env en porte
    déjà un autre (quelqu'un a rafraîchi entre-temps), on le prend sans consommer le refresh token."""
    if not IN_BRIDGE and _bridge_alive():
        sys.exit("✗ Le bridge tourne et possède le jeton TONE3000 : passe par http://127.0.0.1:8770/api/t3k/… "
                 "(un refresh concurrent révoque toute la lignée).")
    with _env_lock():
        e = env_read()
        cur = e.get("T3K_ACCESS_TOKEN")
        if stale_access and cur and cur != stale_access:
            return cur                                             # déjà rafraîchi par un autre : on le réutilise
        rt = e.get("T3K_REFRESH_TOKEN")
        if not rt:
            sys.exit("✗ Pas de refresh token. Relance : ./tools/t3k.py auth")
        return token_request({"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id()})

def api_get(path):
    """GET JSON authentifié, avec refresh auto sur 401."""
    url = path if path.startswith("http") else f"{API}{path}"
    st = None; res = None; tok = None
    for attempt in (1, 2):
        tok = access_token() if attempt == 1 else refresh(stale_access=tok)
        st, res = http_json("GET", url, headers={"Authorization": f"Bearer {tok}"})
        if st == 401 and attempt == 1:
            continue
        return st, res
    return st, res

# ── Commandes ───────────────────────────────────────────────────────────────
def cmd_auth(args):
    cid = publishable_key()
    verifier, challenge = pkce()
    state = b64url(secrets.token_bytes(16))
    params = {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
              "code_challenge": challenge, "code_challenge_method": "S256", "state": state}
    url = f"{API}/api/v1/oauth/authorize?" + urllib.parse.urlencode(params)

    holder = {}
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            holder.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(b"<h2>GoleM : TONE3000 connecte. Tu peux fermer cet onglet.</h2>")
    srv = http.server.HTTPServer(("localhost", 8765), H)
    srv.timeout = 300
    print("→ Ouverture du navigateur pour autoriser TONE3000…")
    print(f"  (si rien ne s'ouvre, colle cette URL dans ton navigateur :)\n  {url}\n")
    webbrowser.open(url)
    # bloque jusqu'à recevoir le callback (?code=...) — ignore les requêtes parasites (favicon…)
    tries = 0
    while "code" not in holder and "error" not in holder and tries < 20:
        srv.handle_request()
        tries += 1
    if "error" in holder:
        sys.exit(f"✗ Autorisation refusée : {holder.get('error')}")
    if holder.get("state") != state:
        sys.exit("✗ state mismatch (sécurité) — réessaie.")
    if "code" not in holder:
        sys.exit("✗ Pas de code reçu (timeout ?). Réessaie.")
    token_request({"grant_type": "authorization_code", "code": holder["code"],
                   "code_verifier": verifier, "redirect_uri": REDIRECT, "client_id": cid})
    print("✅ Authentifié. Tokens stockés dans .env (gitignored).")

def cmd_search(args):
    qs = {"query": args.query, "page_size": str(args.limit)}
    if args.gears: qs["gears"] = "_".join(args.gears)
    if args.sort: qs["sort"] = args.sort
    st, res = api_get(f"/api/v1/tones/search?{urllib.parse.urlencode(qs)}")
    if st != 200: sys.exit(f"✗ search {st}: {res}")
    items = res.get("data", res if isinstance(res, list) else [])
    print(f"{len(items)} résultats pour « {args.query} » :\n")
    for t in items:
        gears = ",".join(t.get("gears", []) or ([t["gear"]] if t.get("gear") else []))
        title = (t.get("title") or t.get("name") or "?")[:50]
        print(f"  id={str(t.get('id')):<8} {title:<50} [{gears}]  ♥{t.get('favorites_count', t.get('favorites','?'))}")
    print("\n→ ./tools/t3k.py fetch <id>  pour télécharger.")

def cmd_fetch(args):
    st, tone = api_get(f"/api/v1/tones/{args.id}")
    if st != 200: sys.exit(f"✗ tone {st}: {tone}")
    title = tone.get("title", f"tone-{args.id}")
    st, res = api_get(f"/api/v1/models?tone_id={args.id}")
    if st != 200: sys.exit(f"✗ models {st}: {res}")
    models = res.get("data", res if isinstance(res, list) else [])
    if not models: sys.exit("✗ Aucun modèle pour ce tone.")
    subdir = "irs" if args.type == "ir" else "models"
    outdir = os.path.join(ROOT, "assets", subdir)
    os.makedirs(outdir, exist_ok=True)
    saved = []
    for m in models:
        murl = m.get("model_url")
        if not murl: continue
        ext = os.path.splitext(urllib.parse.urlparse(murl).path)[1] or (".wav" if args.type == "ir" else ".nam")
        name = (m.get("name") or title).strip()
        fname = name if name.lower().endswith(ext) else name + ext
        dest = os.path.join(outdir, fname)
        tok = access_token()
        st2, blob = http_json("GET", murl, headers={"Authorization": f"Bearer {tok}"}, raw=True)
        if st2 == 401:
            tok = refresh()
            st2, blob = http_json("GET", murl, headers={"Authorization": f"Bearer {tok}"}, raw=True)
        if st2 != 200:
            print(f"  ✗ {fname} : {st2}"); continue
        open(dest, "wb").write(blob)
        saved.append((dest, name))
        print(f"  ✓ {os.path.relpath(dest, ROOT)}")
    if saved:
        print(f"\n→ Tone « {title} » (source: {API}/tones/{args.id})")
        print("  Entrée components.json suggérée :")
        ex = saved[0]
        print(json.dumps({"id": title.lower().replace(" ", "-"), "name": title,
                          "type": "ir" if args.type == "ir" else "nam",
                          "file": os.path.relpath(ex[0], ROOT),
                          "source": f"{API}/tones/{args.id}"}, ensure_ascii=False, indent=2))

# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="t3k", description="Client TONE3000 pour GoleM")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth").set_defaults(func=cmd_auth)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--gears", nargs="+")
    s.add_argument("--sort", default="trending"); s.add_argument("--limit", type=int, default=15)
    s.set_defaults(func=cmd_search)
    f = sub.add_parser("fetch"); f.add_argument("id")
    f.add_argument("--type", choices=["nam", "ir"], default="nam"); f.set_defaults(func=cmd_fetch)
    args = p.parse_args()
    args.func(args)
