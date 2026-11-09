# A plugin's own window (Vital)

> **Status: CODED** — opening Vital's original editor window from its drawer and saving the sound when it closes;
> validated on a Linux rack (filmed view), the native-window path on Windows/macOS has not been tried on hardware.

## 1. What the musician sees

Vital drawer, **Preset** row: a small **Edit** button right of ◀ ▶. The button is always shown; when it cannot
work it is greyed and a tap says why (a missing button explains nothing).

| Where | What opens (`mode`) |
|---|---|
| Windows / macOS, the machine's own screen | the **real Vital window**, in front of golem (`native`) |
| Windows / macOS, tablet | nothing: greyed, "Vital's window opens on the golem's own screen, not on a tablet" |
| **Linux**, machine screen **or tablet** | the window **filmed**, full screen inside golem (`view`), driven by finger or mouse; **Done** closes it |

The **VST Host block** on Linux uses the same filmed view (2026-11-09, [`platforms.md`](platforms.md) §6.1): on close, its
native state goes into the patch instead of a Vital preset.

When the window closes, if Vital's state changed, the sound is stored as a Vital preset named
"*original name* (edited)" in the `edited` pack (`bridge/vital.py` `save_edited`, `library/synth/vital/edited/`,
local, not versioned) and **replaces the old one on the block** — in the base and in every scene that played the
original sound; a scene playing another sound keeps it (`app/designer-model.js` `swapVitalPreset`). The original
preset is never touched: picking it again gives the previous sound. Editing again rewrites the same file.

## 2. The chain

- **`golem_rig.lua`, action `plugin_window`** (sent with `_route: "rig_recall"`, so `golem_watch` needs no new
  route). `op`:
  - `open` reads the state, opens the floating window and starts a `defer` loop watching `TrackFX_GetOpen`. On
    close it re-reads the state and writes `presets/.plugin-window-<id>.json` (`{seq, state, changed, …}`,
    `changed` = state differs from the one at opening) and the state itself in `.plugin-window-<id>.b64`.
  - `close` closes the window (the view's **Done**).
  - `peek` reads without opening (diagnostic).
  - If the instance changes while the window is open (a rebuild), the state is `lost` and nothing is read: a fresh
    instance holds the preset, not the edit.
  - A keys block carries **two FX under the same `golem:<id>` label** (the JSFX note zone first, then the engine);
    `plugin_window` targets the first non-JS FX. The VST Host's `vst_state` has the same blind spot if it ever
    targets a keys block.
- **Bridge** (`bridge/routes_content.py`):

| Route | Role |
|---|---|
| `GET /api/plugin-window` | `{available, mode}` or `{available: false, why}` (`_plugin_window_mode`: native only for a local client on Windows/macOS; `view` on Linux when REAPER's display is found) |
| `POST /api/plugin-window/open` `{block}` | sends `open`, waits up to 3 s for the matching `seq`; 404 `missing` if the instance is not loaded; in `view` mode places the window and returns its `w`, `h`; in `native` mode brings it to front (`provision/desktop_window.focus_reaper_fx`) |
| `GET /api/plugin-window/{block}` | `{seq, state: open\|closed\|lost\|missing, changed?}` — the state stays on the rack |
| `POST /api/plugin-window/{block}/close` | sends `close` |
| `POST /api/plugin-window/{block}/save-vital` `{seq}` | stores the closed, changed state as an `edited` preset → `{id, name}`; 409 "nothing to save" otherwise |
| `GET /api/plugin-view/{block}/stream` | Linux: MJPEG stream (`multipart/x-mixed-replace`) |
| `POST /api/plugin-view/{block}/input` | Linux: `{ev: move\|down\|up\|wheel, x, y ∈ [0,1], dy}` |

- **App**: the watch on the window lives in the **page** (`app/page-designer.js`), so closing the drawer before the
  window loses nothing; `app/plugin-view.js` `PluginView` renders the filmed view.

Vital's state is ~240 KB: it travels in its own `.b64` file, never escaped inside JSON.

## 3. The filmed view (Linux)

On Linux REAPER draws on a virtual X display (Xvfb, `:99` by default, `GOLEM_XVFB_DISPLAY`, started by
`provision/start.sh`), and an X window cannot change screens. `bridge/plugin_view.py`:

- finds the window by title (`golem:<id> - Track …`, the FX label) and moves it to **0,0** (`place`): REAPER
  reopens it where it last was, which can overflow the virtual screen, and x11grab refuses to film outside it;
- films it with **ffmpeg x11grab** (`frames`: 15 fps, scaled to 1024 px wide, MJPEG, so an `<img>` reads it with
  no JS); ffmpeg stops when the client leaves or the window disappears;
- replays gestures through **XTEST** (`gesture`: move, left click, wheel) in window coordinates [0,1]²; the app
  sends them in order, a pending move being replaced by the next one.

No new dependency: ffmpeg is already required, libX11/libXtst come with Xvfb (loaded by `ctypes`). No keyboard:
Vital is set with the mouse.

## 4. OpenGL cost without a GPU

On Xvfb a plugin GUI's OpenGL is rendered in software by Mesa's llvmpipe, which spawns one thread per core: an
open Vital window took REAPER from ~150 % to ~1100 % CPU. `start.sh` therefore exports `LP_NUM_THREADS=2`
(`GOLEM_LP_THREADS` overrides) before launching REAPER. With that cap an open, filmed Vital window costs about
1.4 cores (ffmpeg ~0.2 core) with no xrun, and the cost disappears when the window closes.
