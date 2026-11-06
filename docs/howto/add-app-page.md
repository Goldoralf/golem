# How to add a page (or a hub tab) to the app

**When:** a new screen in the rack app (`app/`, Preact + htm, **no build step**). For the
musician's phone, the entry is `app/m.html` + `app/mobile.js` instead — same rules.

## Files, in order

1. **Choose where it hangs.** The topbar has five sections (`NAV` in `app/main.js`: Live,
   Designer, Songs, Library, Settings). A new top-level section is a product decision; almost
   every new screen is a **tab of a hub**: Settings = `TABS` in `app/page-systeme.js`, Library =
   `TABS` built from `GROUPS` in `app/page-library.js`. A tab is one line:
   ```js
   { id: 'lic', label: 'Licenses', Page: LicensesPage },     // app/page-systeme.js
   ```
   `HubPage` (`app/lib.js`) publishes the tabs in the topbar and writes the URL: the tab is then
   reachable at `#/system/lic`, sub-tabs at `#/system/sys/<sub>` (passed as `props.sub`).
   Only a true top-level page goes in `PAGES` + `NAV` + `NAV_ACTIVE` of `main.js`.
2. **Create `app/page-<name>.js`** with the SPDX header, a French comment saying why the page
   exists, and an exported component. Model: `app/page-engine.js` (`EnginePanel`).
   ```js
   // SPDX-License-Identifier: GPL-3.0-or-later
   import { html, api, useAsync, LoadGuard } from './lib.js';
   export function ThingPage({ rig }) {
     const { data, err, reload } = useAsync(() => api('/api/thing'), []);
     if (!data) return html`<${LoadGuard} err=${err} reload=${reload} />`;
     return html`<div class="thg-page">…</div>`;
   }
   ```
   `lib.js` helpers: `api` / `post` / `del` (throw on non-2xx, body in `e.body`), `useAsync`
   (retries every 4 s while mounted), `useRigState` (the `/ws` state; pages receive it as `rig`),
   `useRev('library_rev' | 'content_rev')` in deps to reload when a golem.fm job lands something,
   `go('system/lic')` to navigate, `longPress`, `cls`.
3. **Topbar action** (a "+ Add" button): publish it from an effect and clear it on unmount, as
   `app/page-outboard.js` does:
   ```js
   useEffect(() => {
     setTopAction(html`<div class="tb-action"><button class="primary tb-new" onClick=${open}>+ Add</button></div>`);
     return () => setTopAction(null);
   }, []);
   ```
   Never call it during render (infinite loop). A **hub** must not use `setTopAction` for its own
   chrome: parent effects run **after** the child's, so the hub overwrites the page's button (two
   buttons vanished that way). Hub chrome goes in `setTopIO` / `setSubToolbar`.
4. **CSS in `app/style.css`** (one stylesheet, loaded by `index.html`). Prefix every class with a
   short page prefix (`eng-card`, `eng-chip`) and every state too (`pd-live`, not `live`): `.live`
   is the Live page's root rule with `min-height:100vh`, and a tile marked `live` inherited it.
   If edit controls must disappear in golem.fm's read-only shell (`?shell=ro`), add your class
   to the `[data-shell=ro]` list or use `.edit-only`.
5. **Text on screen is English**; comments are French. The brand is written `golem` or `/golem_`.

## Layout rule

1024×600, **no page scroll**: the page navigates (tabs, drill-in, paged grid), it never grows
downward. Size with `flex:1; min-height:0` chains (`.hub-body` / `.hub-scroll`); measure that no
element overflows. Touch targets for a finger.

## Checks

- Render it, don't trust it: nothing compiles, so nothing warns you.
  `google-chrome --headless=new --window-size=1024,600 --virtual-time-budget=5000
  --screenshot=/tmp/p.png 'http://localhost:8770/app/#/system/lic'` — then look at the pixels;
  use Playwright (`executable_path="/usr/bin/google-chrome"`) to read the console. The real
  window is `golem desktop` (`--dev` shows REAPER too). A page may `POST` on mount: when driving
  it in a browser, intercept every `POST/PUT/DELETE /api/…` unless you mean to write.
- Pure logic goes in a `*-model.mjs` with a `*.test.mjs` next to it (`node --test app/*.test.mjs`).
- After shipping JS/CSS, the rack window **does not reload by itself**: it shows
  "⟳ New version installed — tap to reload" when `GET /api/app-build` changes (polled every 20 s).
  Until someone taps it, the old code runs.

## Traps

- `/api/app-build` takes the newest mtime of `.js`, `.css`, `.html` files at the **top level** of
  `app/` only: changing only an `.mjs` model, an icon or `vendor/` does not raise the banner.
- `hidden={cond}` is a browser rule any author rule beats (`display:flex` elsewhere re-shows it):
  don't render the node instead.
- A guarded GET (see [add-api-route.md](add-api-route.md)) answers 403 to an unpaired phone: the
  page must survive it (`LoadGuard`), not render a blank.
