# UI architecture — hubs, top bar, the desktop window

> **Status: CODED** — the app's five hubs and their routes (`app/main.js`), the top bar rules, the desktop
> window (size and zoom memory, close vs stop, Windows launcher) and REAPER kept off screen.

Related: [`architecture.md`](architecture.md) §4 (front-end files) · [`modes.md`](modes.md) (`ui.pages`,
`ui.locked`) · [`devices-people.md`](devices-people.md) (the phone screen, `app/m.html`) ·
[`installer.md`](installer.md) (desktop vs server) · [`pitfalls/ui.md`](pitfalls/ui.md).

**First rule: the app is a device, not a web page.** The rack screen and a tablet are 1024×600 and the
app **never scrolls**: it **navigates** (tabs, drill-in, paged grids, drawers). The UI grows in width, never
in height. Every page must fit the screen; check it rendered in that format, not in a full browser window.
Visible text is in English; the brand is written `/golem_` or `golem`.

## 1. The five hubs

`app/main.js` `NAV` (order: from "now" to "stock"):

| Hub | Route | Section colour | What it holds |
|---|---|---|---|
| **Live** | `#/live` | `--sect-live` (red) | `page-live.js`: what is playing. Three views (Pedalboard · Rehearsal · Concert, [`live-pages.md`](live-pages.md)); toolbar `[view] · Mixer · Tuner · ✎ Assign · Click · Lock · Rec`. **✎ Assign** opens the pedalboard editor on the grid you play (`app/live-assign.js` → `designer-pedalboard.js`); it is absent when the UI is locked. |
| **Designer** | `#/designer[/<lane>]` | `--sect-designer` (blue) | `page-designer.js`: the current preset's rig. One tab per lane (`#/designer/in2`, `#/designer/keys`, a new lane's own id) and ⚙ (`#/designer/config`: Global (Click, Rec, Riff), Players, Arrangement). Scene tabs in the top bar slot; the `⋯` menu holds Name & save, ⚙ Preset settings, ▦ Scenes & sounds (the lanes × scenes dictionary, `designer-scenes.js`). |
| **Songs** | `#/songs/<tab>` | `--sect-songs` | `page-songs.js`, **what you play**: Songs (landing, `page-repertoire.js`) · Patches · Presets · Banks & Setlists. |
| **Library** | `#/library/<tab>` | `--sect-library` (green) | `page-library.js`, **what you own**: Tones (Amps · Pedals · Cabs · Outboard, with a Guitar/Bass/Voice role segment) · Keys (Synths · Instruments) · Drums (Drums · Kits · Grooves) · Samples (Short · Songs) · Tracks (Backings · Standards · Recordings). |
| **Settings** | `#/system/<tab>/<sub>` | `--sect-settings` (violet) | `page-systeme.js` (mockups/settings-nav.html, 2026-10-20): **Mode** (the modes as a list on the left, the selected mode's sheet on the right in three groups — Who and where · On stage · Time and takes; `#/system/mode/compare` shows every mode side by side — mockups/mode-page.html, C + E) · **System** (Dashboard · Health) · **Gear** (Soundcard · Controllers · Pedals · Pedalboard · Drums) · **Engines** (Audio · Separation) · **Content** (Storage · Factory) · **Connect** (Wi-Fi · Devices · golem.fm · TONE3000) · **About** (golem — version and updates · REAPER · Libraries; a blue dot when a newer release is known). Every former address redirects (`legacyRoute`: `#/system/sys/mode`, `#/system/sound`, `#/system/pedal/<x>`, `#/system/net/…`, `#/system/api/…`, `#/system/lic/…`). |

The criterion between Songs and Library: what you **play** (produced) vs what you **own** (imported). A
recording is a material that is played again, so it lives in Library ▸ Tracks.

**Routing.** `useRoute` reads the hash; the first segment picks the page (`PAGES`), the rest is passed as
`sub` (a hub tab, and a sub-tab: `#/system/sys/mode`). Old routes stay as aliases (`#/systeme`,
`amps`, `setlists`…, mapped by `NAV_ACTIVE`). Hubs are built with `HubPage` (`lib.js`).

**The mode shapes the surface** ([`modes.md`](modes.md)): `mode.ui.pages` hides hubs (hidden, not greyed);
a route to a hidden hub shows Live. `mode.ui.locked` locks the screen; the way out is a **2 s hold** on
the logo (locked modes) or on the mode badge (any mode but Studio), with window-level pointer listeners,
14 px of tolerance and the context menu suppressed, so a real finger does not cancel it. If the bridge
does not answer, the exit says so and can be retried. A kiosk without an exit is a bug.

**Global banners** above the top bar: bridge link lost (after 4 s), "⟳ New version installed — tap to
reload" (the app never reloads itself: `GET /api/app-build` is polled every 20 s), foot slot entry,
missing sound card / REAPER stopped listening.

**Two screens, one code base.** The rack window and a tablet run `app/index.html`; the musician's phone
runs the Companion, `app/m.html` + `mobile.js` ([`devices-people.md`](devices-people.md)).

## 2. Conventions

| Convention | Implementation |
|---|---|
| **tap = open** | a block tile opens its drawer; a song or preset row loads it |
| **long press = assign** | long press on a tile opens MIDI assign (`longPress`, `lpFired` in `lib.js`); no visible context menu |
| **section colour** | each hub sets `--sect` on `.shell[data-sect]`; primary buttons use it |
| **foot labels are relative** | /live shows switches as "scene N / stomp N of the **current** preset", re-rendered at load |
| **one stack per switch** | a /live tile that holds several blocks shows one line per block (glyph · name · lane tag GTR/BASS/VOX/KEYS/SVC); a real scene shows its letter and, per lane, the state that scene picks |

## 3. The top bar: five zones that never overlap

The top bar is **1024 × 56**, left to right: the **brand** (tap = Live, hold = exit a locked mode; on /live
the `_` blinks on the beat), the **mode badge**, the **section nav** (five icons), the **hub slot** (its
tabs), then on the right the **chips** (⇅ I/O, ☁ sync — its detail on hover) and the **page action** (+ Add, Save; on Amps, + Add opens TONE3000 or a golem capture `.gcap`). When room runs out, the tabs shrink and shorten rather than slide under the chips.

1. **Nothing overlaps.** `.tb-slot` is bounded in width only (`overflow-x: clip; overflow-y: visible`):
   its tab row scrolls rather than sliding under a neighbour, and a menu anchored in the top bar can
   still open downwards (`hidden` would clip it vertically too). A hidden tab is a bug; a tab reached by
   swiping is acceptable.
2. **The sacrifice order is declared.** The mode badge gives its width first (`flex-shrink: 1000`): it
   informs, it does not act. The section nav and the actions never shrink. Tabs tighten before they
   scroll.
3. **The page action is always in the top bar, on the right**, Library included. Pages publish it with
   `setTopAction`; the host renders it (`setActionHost`, `lib.js`). Action labels stay short ("+ Add").
   A hub that publishes into the action slot hides its page's action: the parent's effects run **after**
   the child's.

## 4. The desktop window — size and zoom memory

Only for the desktop shells (`golem desktop`, `golem phone`, `golem ui`, and the Windows launcher). On a
rack screen the window is the screen.

Each shell (`ui`, `device`, `phone`) has its own memory in **`config/.desktop.json`**: local state, out of
the repository (it describes this machine's screen, not the rig). Written by the bridge from the page's
reports (`app/shell-geom.js`, `/api/ui/geometry`); read by the launcher.

```json
{ "ui": { "w": 1440, "h": 900, "dpr": 1.25, "base": 1, "forced": 1.25 } }
```

Why the code is shaped this way:

- `--window-size` gives exact `outerWidth/outerHeight` in an `--app` window; `--force-device-scale-factor`
  changes `devicePixelRatio` without touching the size. Size and scale are **orthogonal**: two numbers,
  replayed separately.
- A zoom stored in Chrome's preferences is **not** applied to an `--app` window: the launcher replays the
  scale.
- Under Wayland no program can move another's window (no `xdotool`/`wmctrl`): the geometry can only come
  **from the page**.
- Chrome is a singleton per `--user-data-dir`: a second window opened by the running process ignores
  `--window-size` and the scale flag. The page resizes itself (`window.resizeTo`, retried at 0 / 500 /
  1600 ms because a recycled window settles its size after load); a scale cannot be fixed afterwards, and
  the launcher says so.
- **`base`**: on a HiDPI screen `devicePixelRatio` is 2 without anyone zooming. `base` = the dpr **at
  load**, before any Ctrl+/- (the `first` flag of the report). While `dpr == base`, **no flag** is passed
  and the browser stays in charge. If a launch forced to X sees a page at ≠ X, the browser adds its own
  scale: the launcher stops forcing rather than squaring the zoom.

**The way out**: `golem desktop|phone|ui --reset` gives that shell its original size back. A remembered
window larger than today's screen would be unreachable.

## 5. Closing the window ≠ stopping the rig

| | Effect |
|---|---|
| the system **close** button, or **Esc** | closes the **window**. REAPER and the bridge keep running: the sound does not stop |
| **⏻ Stop golem** (System ▸ Dashboard) | closes the window **and** stops the rig (REAPER, MIDI reader, bridge): the same as `golem stop`. It needs **two taps** ("sure?") |
| **Continue on a tablet** (System ▸ Dashboard) | shows the working address and its QR code, a pairing code if no main device exists, then closes the window the Esc way: golem keeps running ([`installer.md`](installer.md)) |

The tablet shell has **no bottom bar** (2026-10-17): its only controls are **− +** in the bottom-right corner of
the bezel (the zoom; the percentage shows on hover and just after a change; **auto** appears only when the zoom is
manual) and Ctrl+wheel. They sit over the stage at a constant size, not inside the scaled bezel. Reload is the
"New version installed" banner or F5. The **phone** shell (`golem phone`, a dev tool) keeps its bar: ↻, ⏻, the
zoom, the Who selector and the conductor switch.

Closing a window and cutting the audio engine are two intentions: a close button that stopped everything
would cut the sound mid-song. In browser full screen (F11), Esc cannot be undone from JS: the page shows
what to press (`F11` / `Ctrl+W`).

`window.close()` is refused for a window no script opened, so both go through the bridge:
`POST /api/ui/quit` (`{"stop": true}` for ⏻). Only processes carrying the launcher's **dedicated**
`--user-data-dir` are killed, never the personal browser. The bridge stops **last and deferred**, so the
answer leaves before it dies. Without a window, stop from the main device: Settings ▸ System ▸ Dashboard,
"⏻ Stop golem".

## 6. Windows: the same window

`python -m provision.desktop start` opens the `device` shell like `golem desktop`: Chromium `--app`
(Chrome first, Edge otherwise), dedicated profile `%LOCALAPPDATA%\GoleM\browser`, the same
`config/.desktop.json` and the same `base`/`forced` logic. `--shell device|phone|ui`, `--reset`,
`--fullscreen`, `--dev`: same meanings.

| Linux (`provision/golem`, `golem.desktop`) | Windows (`provision/desktop.py`) |
|---|---|
| `golem` / the menu entry | **golem** icon (Desktop + Start menu), run by `pythonw.exe`: no console; an error shows in a Windows dialog |
| `golem server` | **golem server** icon (no window: a tablet or phone is the screen) |
| `golem stop` | **Stop golem** shortcut (Start menu) = `provision.desktop stop` = ⏻ |
| `golem phone` (development) | `python -m provision.desktop start --shell phone` (no icon) |
| `start.sh` does not restart a running rig | clicking the icon again **brings back** the open window, or opens it |
| `ps` + `kill` of the dedicated profile | `Win32_Process` (command line) + `taskkill`, same scope |
| `pkill reaper` | `WM_CLOSE`; REAPER is terminated only if it answers no message for 15 s (`desktop_window.reaper_hung`) — a "save?" dialog keeps its message loop alive and is left alone |

Shortcuts are created by `provision.desktop setup` and by the graphical installer through one function,
`install_shortcuts`, which also removes legacy shortcut names. Icons: `app/icons/golem.ico`,
`golem-phone.ico`.

**The logo** is the red slash of `/golem_` (`#ff5a3c`, `--accent` / `--sect-live`) on a `#0c0e12` tile (the
manifest's `theme_color`). One script draws every icon file (`favicon.ico`, `favicon-32/180.png`,
`icon-512.png`, the two Windows `.ico`); icons are never edited by hand.

## 7. REAPER is machinery, not a window

A golem user never reads REAPER. The launcher therefore opens **one** window.

| Command | For | REAPER |
|---|---|---|
| `golem desktop` (default; `device` is the old name) | golem on a computer | **hidden** |
| `golem server` | no window, a tablet is the screen | **hidden** |
| `golem phone` | the musician's view, for development | **hidden** |
| `golem ui` | the app in a plain window | **hidden** |
| `golem start` | debugging | **visible** |
| `… --dev` | show REAPER from any of the hidden ones | **visible** |

The **shell** is still called `device` internally: it is the name of the hardware frame rendered by
`app/device.html` and the key of the window memory; renaming it would orphan the remembered size.

How REAPER is hidden:

1. **No ReaScript console.** The rig scripts do not call `reaper.ShowConsoleMsg` (it opens a console window);
   each logs to its own file in `presets/` (`.watch.log`, `.apply.log`, `.click.log`, `.golem-rig.log`…), where the bridge reads them.
2. **The main window goes to a virtual X display** (`Xvfb :99`, `GOLEM_XVFB_DISPLAY`, `provision/start.sh`).
   The window exists on a screen nobody looks at; audio and OSC do not depend on it. `wnd_state` in
   `reaper.ini` has no effect under Linux (SWELL ignores it), and Wayland forbids moving another program's
   window, so a virtual display is the only working route. REAPER also starts with `-nosplash`.

**The way out and the fallback**: `--dev` puts REAPER back on the real screen. If `Xvfb` is not installed,
REAPER starts on the real screen **and the launcher says so** (`⚠ Xvfb absent — sudo apt install xvfb`):
never a silent failure. `golem stop` also kills the virtual display, so no orphan `Xvfb` survives a cycle.
