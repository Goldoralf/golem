# UI pitfalls

The app (`app/`) is Preact + htm with no build step: nothing compiles, so nothing warns. It targets a
1024×600 touch screen with no scrolling, plus phones for the Companion (`app/m.html`). UI text is in
English; the brand is written `/golem_` or `golem` wherever it is displayed (identifiers such as
folder names, firewall rules and mDNS service names keep their historical spelling).

---

## Verify at render, not at build

**Symptom.** A change "works" in code review and breaks on screen: overflow, hidden controls,
unclickable tabs.

**Cause.** No compiler, no type checker; CSS from several sheets combines at runtime.

**Rule.** Look at pixels and read the console. Use headless Chrome
(`google-chrome --headless --screenshot`, or Playwright with `executable_path="/usr/bin/google-chrome"`)
at the real formats: 1024×600 for the rack (`golem desktop`, `--dev` to see REAPER), 390×844 for the
Companion (`golem phone`, dev only). A full-browser window shows neither panel overflow nor what a
phone shows. When driving the real app in a browser, intercept every `POST/PUT/DELETE /api/` —
autosave writes real files.

**Detect.** `./tools/check-syntax.py` (JS module syntax, Lua); `node --test` for `app/*.test.mjs`.

---

## Generic CSS class names collide

**Symptom.** A tile marked `live` fills the whole screen.

**Cause.** It inherited `.live { min-height: 100vh }`, the class of the Live page.

**Rule.** Prefix state classes with their component (`pd-live`, `pd-live-bypass`); never use a bare
generic word as a state class.

**Code.** `app/style.css` (`.pd-tile.pd-live`), `app/page-pedals.js`.

---

## The `hidden` attribute is beaten by any author rule

**Symptom.** Controls declared hidden are visible and clickable, writing into state nothing saves.

**Cause.** `hidden` is a browser default style; any author rule such as `.x { display: flex }` in any
stylesheet overrides it. The component's code does not lie — another layer silently undoes it.

**Rule.** Do not render the node (`cond && html\`…\``) instead of hiding it. If `hidden` is ever used,
add `[hidden] { display: none !important }` and check it on a screenshot.

**Detect.** `grep -rn 'hidden=' app/` (no non-`aria-hidden` use at the time of writing); screenshot.

---

## `setTopAction` is overwritten by the parent

**Symptom.** A page's top-bar button disappears.

**Cause.** Parent effects run AFTER child effects: a hub that publishes into the action slot
overwrites its page's action.

**Rule.** Only the page publishes its action; the hub decides WHERE it renders (`setActionHost`), not
what it contains. Check after any hub change that each page's button is still there.

**Code.** `app/lib.js` (`setTopAction`, `setActionHost`, `useTopAction`, `useActionHost`).

---

## A screen dropped on a send error must have its socket closed

**Symptom.** The rack window shows the loading screen frozen a few seconds into the boot (or any page
frozen), `GET /api/health` says `"screens": 0`, and the bridge log still shows that window's
`WebSocket /ws?shell=device [accepted]` with no `connection closed`. The user is stuck: the page never
reconnects (2026-10-20).

**Cause.** `_broadcast` was scheduled from several threads (OSC meters at 20 Hz during the bank 00
recall, monitors, the recall itself): two `send` calls overlapped on the same socket, one raised, and
the client was discarded **silently without closing the socket**. The page kept a live but mute
WebSocket, so its `onclose` reconnection never fired, and its last frame stayed on screen.

**Rule.** One broadcast at a time (a lock; concurrent requests coalesce into one more pass with the
freshest state), one serialization for every screen, the error logged, and a client that fails to
receive is **closed** (`ws.close(1011)`) so the page reconnects. A screen must never be dropped in
silence.

**Code.** `bridge/app.py` `_broadcast`, `_drop`, `_bcast_lock`; `tests/test_broadcast.py`.

---

## The rack window never reloads by itself

**Symptom.** A fix is delivered and the user still sees the old behaviour.

**Cause.** The rack window (`golem desktop`) keeps the loaded code; it only shows a "New version
installed — tap to reload" banner when `GET /api/app-build` changes (polled every 20 s and on
WebSocket reconnect).

**Rule.** After a JS/CSS change, the banner must be tapped before testing. Python changes need
`./provision/reload.sh` (uvicorn runs without `--reload`); Lua/JSFX/JS/CSS need only a refresh.

**Code.** `app/main.js` `useAppBuild`, `bridge/routes_system.py` (`/api/app-build`).

---

## Chrome ignores `--window-size` when an instance already runs

**Symptom.** The app window opens at the wrong size.

**Cause.** Chrome is a singleton per profile: with the same profile it hands the URL to the running
instance and exits.

**Rule.** Use a dedicated `--user-data-dir` for the rack window.

**Code.** `provision/golem` (`--user-data-dir="$APPDIR"`).

---

## An endless animation steals the audio thread

FIXED 2026-11-25 (Windows dev box: i9-13900H laptop, 240 Hz screen; Linux rack: i5-3337U, 2 cores).

**Symptom.** Crackles that come and go with the golem window: none when it is minimised, closed or covered by
another window, crackles as soon as it is in front. This happens whatever the patch, the engine, the buffer or the
power plan. On Linux (REAPER, Funk Clean), 116–119 ALSA restarts a minute with the window open and 0 with it
minimised. On Windows (Golem Engine, buffer 128), the engine's peak load is 80–86 % with the window in front against
58–66 % with it minimised.

**Cause.** As long as ONE infinite CSS animation runs, or one `requestAnimationFrame` loop requests the next frame,
Chrome recomposes the page at every screen refresh: 240 times a second on a 240 Hz panel. That holds even for a
26-pixel blinking caret (the `/golem_` wordmark), a pulsing dot or a progress bar of a stopped looper. Measured in a
windowed Chrome on that panel, the GPU process used 16–49 % of a core and the renderer 6–18 %, while script and
layout cost only 4–6 ms a second (CDP `Performance.getMetrics`). The work competes with the audio thread on the same
machine. A remote screen (a tablet or phone) costs the rack nothing: it draws with its own CPU, and the state stream
is about 10 messages and 60 KB a second.

**Rule.** At rest, nothing on screen redraws continuously.
- Infinite CSS animations are put on a step by `app/anim-stepper.mjs`, started by `main.js` and `mobile.js`. Each one
  is paused and set in turn to its "on" and "off" state at its own half-period. A blink looks the same and a pulse
  becomes two steps. The cost is two frames a second instead of 240: the GPU process drops to 0.4–0.6 % of a core.
- Exempt by design: spinners (a stepped rotation does not turn) and the Live tile animations the user picks
  (`anim-*`). The Designer's effect picker says these tiles cost CPU on the computer that plays the sound.
- Values that move by themselves (looper progress and ring, record timer, bar clock, backing progress, all in
  `page-live.js`) update about 15 times a second through `useLiveTick`, and write only when the value changed.
  They never use a `requestAnimationFrame` loop.
- A gesture animation (a transition, a one-shot keyframe) is fine: it ends.

**Detect.** `tools/check-ui.py` fails a page that, at rest, keeps an infinite CSS animation running (outside the
exemptions) or makes more than 20 `requestAnimationFrame` calls in a second. Live check: with the window in front,
compare the CPU of the golem Chrome processes (Task Manager, or `top` on Linux) with the window minimised.

**Code.** `app/anim-stepper.mjs`, `app/anim-stepper.test.mjs`, `app/page-live.js` (`useLiveTick`, `setIfChanged`),
`tools/check-ui.py` (`_ENDLESS_JS`, `_RAF_COUNTER`).

---

## Never ship a mode without a tested exit

A full-screen kiosk with no way out locks the user in. Every mode, overlay or full-screen view ships
with its exit path tested (gesture, button, keyboard).

---

## A missing instrument is said on its lane

An absent controller is reported on the lane it belongs to, never as a scene-level alert on `/live`.
