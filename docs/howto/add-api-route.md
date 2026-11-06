# How to add a bridge API route

**When:** the app, the Companion, a `tools/check-*.py` script or golem.fm needs a new HTTP
endpoint on the rack (`bridge/`, FastAPI, port 8770).

## Files, in order

1. **Pick the module.** `bridge/app.py` (~2600 lines) holds the historical core: `/api/state`,
   `/api/recall`, `/api/stomp`… New routes go in a topical `bridge/routes_<topic>.py` with its own
   `APIRouter`. Smallest model: `bridge/routes_blocks.py`.
   ```python
   from fastapi import APIRouter
   from fastapi.responses import JSONResponse
   router = APIRouter()

   @router.get("/api/blocks/status")
   def blocks_status(preset: str = ""):
       p = _preset_of(preset or None)
       if p is None:
           return JSONResponse({"error": f"unknown preset '{preset}'"}, 404)
       return BS.preset_status(p)
   ```
   - Success: return a `dict` (200). Error: `JSONResponse({"error": "<English sentence>"}, status)`.
     No `HTTPException` anywhere in `bridge/`. `app/lib.js: api()` throws on non-2xx and puts the
     parsed body in `e.body` — so a 409 can carry a question (`needs_confirm`) the UI answers.
   - The `error` text may be shown as is: write it in English, for a musician.
   - Blocking work (subprocess, big file, REAPER round trip) in an `async def` → use
     `run_in_executor`, as `routes_system.perf_mode` does.
2. **Register a new router** in `bridge/app.py`: add the module to the `from . import routes_…`
   line and an `app.include_router(routes_<topic>.router)` next to the others.
3. **Decide who may call it — `bridge/auth.py`.** One middleware (`_auth_guard` in `app.py`) calls
   `auth.allowed_http(request)`. Rules, in order:
   - localhost (`127.0.0.1`, `::1`) is the rack's own screen: **always allowed**, admin included.
   - `POST/PUT/DELETE/PATCH` need a paired device token (header `X-Golem-Token` or cookie).
   - **A `GET` is open to anyone on the LAN** unless its path is in `SENSITIVE_GET` or starts with
     a `SENSITIVE_GET_PREFIX` (`/api/state`, `/api/preset`, `/api/song`, `/api/sample`, …).
   - `ADMIN_PATHS` / `ADMIN_PREFIX`: promoted device only (any method, GETs included once guarded).
     `ADMIN_WRITES` / `ADMIN_WRITE_PREFIX`: admin for non-GET only.
   - Guests (expiring device) cannot `DELETE`. Phones that are not "conductor" cannot hit
     `CONDUCTOR_PATHS` or `/api/backing/…` (except `/api/backing/meta`).

   Decide: does the GET reveal names from the roster, takes, presets/songs content, file paths,
   keys or tokens? → add its prefix to `SENSITIVE_GET_PREFIX`. Does a write change the system
   (network, engine, pedalboard flash, integrations, dev probes)? → `ADMIN_PATHS`. A config a
   musician may read but not write? → `ADMIN_WRITES`. Starts the band playing? → `CONDUCTOR_PATHS`.
   Keep the "why" comment next to the entry, like the existing ones.
4. **Reload:** `./provision/reload.sh` (uvicorn runs without `--reload`). If the REAPER link drops,
   `POST /api/system/osc-refresh`.

## Test

Call the handler directly — `httpx` is not a rack dependency (`tests/test_drumlearn_routes.py`
reads a `dict` or a `JSONResponse` the same way with `_body`). For auth, copy the `Req` stub and
the `devs` fixture of `tests/test_audit_2026_10_15_security.py`:
```python
def test_my_route_is_not_readable_from_the_lan(devs):
    assert auth.allowed_http(Req("GET", "/api/my-thing")) is False            # unpaired LAN
    assert auth.allowed_http(Req("GET", "/api/my-thing", "musician")) is True
    assert auth.allowed_http(Req("GET", "/api/my-thing", client="127.0.0.1",
                                 host="localhost:8770")) is True               # the rack's screen
```
`tests/test_auth_get.py` lists what must stay open (`/api/app-build`, `/api/health`,
`/api/effects`): a phone loads the page before it is paired. Run `python3 -m pytest tests/ -q`.

## Traps

- Prefixes are plain `str.startswith`, not path segments: `"/api/sample"` also guards
  `/api/sample-sets`, `"/api/song"` guards `/api/song-folders`, `"/api/loop"` guards `/api/loops`.
  A route named to dodge a prefix (`/api/pre-sets`) is silently public.
- Testing from the rack itself proves nothing about auth: localhost bypasses everything. Test from
  another LAN client, or with the `Req` stub and a non-local `client`.
- The token is never accepted in `?token=` over HTTP (only on the WebSocket).
- `Host` must be an IP, `localhost`, the machine name or `*.local` (`auth.host_ok`, anti DNS
  rebinding): a custom hostname needs `GOLEM_ALLOWED_HOSTS`.
- Route order matters for overlapping paths: routers are included before `app.py`'s own routes.
