# Bridge security pitfalls

The bridge (`bridge/`, FastAPI on port 8770) serves the app, the Companion on phones and the tools.
Its access model lives in `bridge/auth.py`; the contract is `SECURITY.md`. The LAN is plain
HTTP and is treated as a trusted network; everything below is about what a device on that LAN, a
web page in the rack's browser, or a remote server must NOT be able to do.

---

## Protection is by URL prefix: a new route outside the lists is public

**Symptom.** A new endpoint exposes data (recordings, roster names, keys) or a dangerous action to
any unpaired device on the LAN.

**Cause.** `allowed_http` guards mutations (POST/PUT/DELETE/PATCH) and the GETs listed in
`SENSITIVE_GET` / `SENSITIVE_GET_PREFIX`; admin-only routes are those in `ADMIN_PATHS`,
`ADMIN_PREFIX`, `ADMIN_WRITES`, `ADMIN_WRITE_PREFIX`. Any GET not listed is open; any mutation not
listed is allowed to every paired device, including 24-hour guests.

**Rule.** When adding a route, decide its tier explicitly and add it to the right tuple:
- reads group data or files → `SENSITIVE_GET_PREFIX`;
- changes system config, network, devices, modes, input map, integrations, restarts a process,
  or drives REAPER for diagnostics → admin;
- deletes → not for guests (enforced generically).
Prefixes, not equality, for routes carrying a path parameter.

**Detect.** `tests/test_audit_2026_10_15_security.py`; request the route from another LAN machine
without a token (expect 403).

**Code.** `bridge/auth.py` (`SENSITIVE_GET`, `SENSITIVE_GET_PREFIX`, `ADMIN_*`, `allowed_http`,
`allowed_ws`).

---

## Local means admin — so anything that makes the bridge call itself is admin

**Cause.** Requests from `127.0.0.1`/`::1` are auto-authenticated (the rack window and the tools).
Two ways to borrow that: server-side request forgery (the bridge fetches a user-supplied URL that
points to itself) and DNS rebinding (a page in the rack's browser whose domain re-resolves to
127.0.0.1; its Origin and Host carry the same foreign name).

**Rule.**
- Validate the `Host` header on HTTP and WebSocket: an IP, `localhost`, the machine's name or a
  `.local` name (extra names via `GOLEM_ALLOWED_HOSTS`).
- Even locally, refuse a foreign `Origin`.
- Any server-side fetch of a user URL resolves the host and refuses loopback, private and
  link-local addresses, re-checks on every redirect, and caps the size. Do not serve the download
  area statically.

**Code.** `bridge/auth.py` (`host_ok`, `_origin_ok`, `_is_local`), `bridge/kit_import.py`
(`_public_host`, `MAX_DOWNLOAD`), `bridge/app.py` (hidden `/library/.…` folders answer 404).

---

## A config value that reaches the environment is code execution

**Cause.** A key written verbatim into `.env` (newline injection: `x\nLD_PRELOAD=…`), a loader that
imports every key, and a restart endpoint reachable by a paired phone.

**Rule.** Values written to `.env` are filtered to a safe character set; the loader imports only
whitelisted prefixes; writing integrations and restarting the bridge are admin-only.

**Code.** `tools/t3k.py` `env_set` (`_ENV_KEY`, `_ENV_VAL`), `bridge/config.py` `_load_dotenv`
(`_DOTENV_PREFIXES`), `bridge/auth.py` (`/api/integrations`, `/api/system/bridge-restart` in
`ADMIN_PATHS`).

---

## The remote server URL is a trust anchor

**Cause.** The rack sends its token to the configured golem.fm server and executes jobs it returns.
A paired phone that could change that URL could pair a fake server as admin.

**Rule.** The server URL and token are admin-only; `https://` is mandatory except towards this
machine, a private IP or a `.local` name (development).

**Code.** `bridge/routes_content.py` `server_url_ok`.

---

## Paths from requests

**Rule.** Resolve with `realpath` and check containment in the allowed base. On Windows also reject
drive-relative forms (`C:x`) and sibling-prefix tricks (`assets/samplesX` vs `assets/samples`).

**Code.** `bridge/routes_content.py` `_within`.

---

## Do not build URLs from the client's `Host`

**Rule.** A URL the rack hands out (e.g. "save local URL") is built from the socket's own address,
not from the request's `Host` header (combinable with DNS rebinding).

**Code.** `bridge/routes_system.py` (`save-local-url`).

---

## Filtering user-supplied CSS

**Rule.** Decode CSS escapes before checking (`\75rl(` is `url(`); refuse every image-loading function
(`image-set()`, `image()`, `src()`, `cross-fade()`, `element()`), not only `url()` with remote targets;
refuse combinators that escape the component scope (`~`, `+`).

**Code.** `bridge/anim_packs.py` (`_unescape`, `_check_css`).

---

## Smaller rules

- Escape every roster-provided string rendered as HTML (`esc()`), dev shells included.
- Diagnostic reports are as sensitive as the route that serves them: the MCP `diag_report` tool is
  admin-only like `/api/diag` (`bridge/mcp.py` `ADMIN_TOOLS`).
- Tokens and device files are written with mode 0600; secrets never go into the repository.
- A secret passed as a command-line argument is visible in `ps` to local users (known for the Wi-Fi
  key passed to the network helper); prefer stdin or a 0600 file.
- Development probes (`/api/rig_recall`, `/api/loadtest`, `/api/chunkdump`, `/api/fxdump`…) are
  admin-only; the `tools/check-*` scripts run locally and are admin by construction.
