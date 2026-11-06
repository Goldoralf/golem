# Pitfalls — index

Hard-won rules for working on golem. Each entry: **symptom → rule → where the details are**. The
linked pages give the cause, how to detect it, and the code that implements the guard. Read the page
of a subsystem before changing it.

| Page | Covers |
|---|---|
| [reaper.md](reaper.md) | REAPER API, Lua `defer` loops, track chunks, sends, live path |
| [jsfx.md](jsfx.md) | EEL2 / JSFX DSP written for the rack |
| [plugins.md](plugins.md) | Third-party plugins: crashes, state, parameters, quarantine |
| [midi.md](midi.md) | Controllers, drum modules, foot controller |
| [windows.md](windows.md) | ASIO, hung REAPER, file replacement, encodings |
| [data.md](data.md) | References, natures, guards, single source of truth |
| [ui.md](ui.md) | Preact app, CSS, top bar, render checks |
| [tooling.md](tooling.md) | Probes, measurement, tests, process matching |
| [install.md](install.md) | Provisioning scripts, fresh installs, pinned downloads |
| [security.md](security.md) | Bridge auth tiers, local = admin, SSRF, injection |

## REAPER

- Service track (click, clock, drums, sampler, looper) stops or never starts → arm it with `I_RECMODE = 2` → [reaper.md](reaper.md#an-unarmed-service-track-leaves-the-live-graph)
- Silence while REAPER reports audio running → trust only an audio-thread counter vs wall clock; `audio_reset` → [reaper.md](reaper.md#reaper-cannot-tell-that-its-sound-card-disappeared)
- All Lua loops freeze after a restart, one thread at 100 % → never persist `time_precise()`; reject future timestamps, cap waits → [reaper.md](reaper.md#a-relative-clock-persisted-in-the-project-freezes-reaper)
- One script error stops unrelated loops → every `defer` callback under `pcall`/`xpcall`, errors to `.lua-errors.log` → [reaper.md](reaper.md#all-lua-loops-share-one-context-one-failing-callback-kills-the-others)
- A loop reads another script's shared memory → `gmem_attach` at the top of every tick → [reaper.md](reaper.md#gmem-must-be-re-attached-on-every-tick)
- REAPER reads no command for minutes → modal dialog; delete render output first, "exists" ≠ "produced" → [reaper.md](reaper.md#a-modal-dialog-stops-the-whole-rack)
- Track memory vanishes after a chunk write → write `P_EXT` after `SetTrackStateChunk`, single-line values → [reaper.md](reaper.md#settrackstatechunk-also-erases-p_ext)
- Amp/cab silent after a rebuild → the chunk lies while loading: heal, verify the plugin's own parameter, repair only after a rebuild, settle → [reaper.md](reaper.md#the-track-chunk-lies-while-a-plugin-is-loading)
- Send settings land on the wrong send → use the index returned by `CreateTrackSend` → [reaper.md](reaper.md#a-sends-index-is-the-value-returned-by-createtracksend)
- Looper toggles by itself when a keyboard plays → `I_MIDIFLAGS = 31` on audio-only sends → [reaper.md](reaper.md#a-send-carries-midi-by-default)
- Half-second blank on every track at scene change → a plugin stalls the engine; `check-block-stall.py`, toggle the convolver's Enable, quarantine → [reaper.md](reaper.md#a-plugin-can-freeze-the-whole-audio-engine-when-it-turns-on)
- Scene changes feel late → budget ≤ 40 ms, no undo points on the live path → [reaper.md](reaper.md#the-live-path-has-a-latency-budget-and-undo-points-break-it)
- A preset named like an action triggers that action → route on decoded/quoted tokens, never substrings → [reaper.md](reaper.md#route-commands-on-exact-tokens-never-on-substrings)
- Commands lost while REAPER is busy → bridge-side command queue → [reaper.md](reaper.md#a-single-command-slot-loses-commands)
- A lane mutes itself mid-song → `automute=0`, limit on the master → [reaper.md](reaper.md#auto-mute-cuts-a-track-mid-song)
- A "no plugin" render does not null → zero auto-fades on items you create → [reaper.md](reaper.md#reaper-adds-auto-fades-to-a-new-item)
- A level judged "too hot" at −18 dBFS, a threshold that never fires → the OSC meter `n/track/@/vu` is linear in dB (0 = −72, 1 = +6), not an amplitude → [reaper.md](reaper.md#the-osc-meter-is-linear-in-db-not-an-amplitude)

## JSFX

- Index constants change at runtime, sequences loop every bar → EEL2 is case-insensitive; prefix local copies → [jsfx.md](jsfx.md#eel2-is-case-insensitive)
- Top-of-file constants are all zero → everything goes in `@init` → [jsfx.md](jsfx.md#code-before-the-first--section-never-runs)
- Writing a slider with negative minimum lands on the wrong value → bipolar taper; write raw values → [jsfx.md](jsfx.md#a-slider-with-a-negative-minimum-is-bipolar-for-reaper)
- Choppy sound from a JSFX → decimate and spread heavy work across blocks → [jsfx.md](jsfx.md#the-audio-thread-has-a-budget)
- A sequencer forgets its state or cuts its first note when the transport starts → `@init` reruns; set `ext_noinit = 1` → [jsfx.md](jsfx.md#init-runs-again-at-every-transport-start)

## Plugins

- REAPER dies, kernel log is empty → read REAPER's stderr (`/tmp/golem-reaper.log`) first, then apport → [plugins.md](plugins.md#read-reapers-stderr-first-when-it-dies)
- Crash ~1 in 10 on quick preset changes (cab) → patched x42 zeroconvo via `install-zconvo.sh` → [plugins.md](plugins.md#x42-zeroconvo-double-state-restore-on-a-fresh-instance-crashes-reaper)
- Crash on quick patch changes (amp) → patched NAM LV2 via `install-nam.sh` → [plugins.md](plugins.md#nam-lv2-two-producers-on-the-lv2-work-queue-crash-reaper)
- Linux: REAPER dies "Config parser already registered for: SlimmableContainer" when a capture module joins a NAM block → a plugin that embeds a library exports only its entry point → [plugins.md](plugins.md#linux-two-plugins-embedding-the-nam-core-share-one-registry)
- Plugin state never seems to reload → LV2 ports override state; write state AND computed ports → [plugins.md](plugins.md#lv2-ports-belong-to-the-host-they-override-restored-state)
- VST3 parameter written as 12 reads 60 → `TrackFX_SetParam` is normalized; target displayed value → [plugins.md](plugins.md#trackfx_setparam-is-normalized-01-on-the-nam-vst3)
- Same preset sounds different per OS, A2 capture plays dry → configure VST3 like LV2; read capture architecture → [plugins.md](plugins.md#same-plugin-family-different-sound-per-os)
- "Installed" plugin crashes or stalls → test alone + stall test before offering; quarantine as data → [plugins.md](plugins.md#installed-is-not-validated-quarantine-is-data)
- Echo with every delay off → IR file contains a late impulse; `check-irs.py` → [plugins.md](plugins.md#ir-files-can-contain-an-echo)

## MIDI

- Keyboard dead after "start rig, then plug" → keep an absent controller's mask bit from memory → [midi.md](midi.md#an-unplugged-controller-is-no-longer-nameable--keep-its-mask-bit-from-memory)
- Hot-plugged device stays dead → `midi_reinit` only, never restart the engine → [midi.md](midi.md#reaper-opens-midi-devices-only-at-startup)
- Drum module stops sending on Windows → open outputs only for devices that need clock → [midi.md](midi.md#windows-a-drum-module-opened-as-an-output-stops-sending)
- "Port opens in Python" used as proof → Windows MIDI is multi-client; observe messages → [midi.md](midi.md#windows-python-can-open-the-port-proves-nothing)
- Windows: the sound card's DIN ports offered for calibration in Controllers / Drums / plug banners → exclude the active card's ports (signer of its ASIO DLL = driver provider of their PnP parent) → [midi.md](midi.md#windows-the-sound-cards-midi-ports-are-not-instruments)
- Foot controller deaf (USB, or after card re-enumeration) → transport is descriptor data; restart reader on "Port unsubscribed" → [midi.md](midi.md#foot-controller-din-versus-usb-and-a-reader-subscribed-to-nothing)
- Switch LED/behaviour wrong → reflash when switch ownership changes; `check-uno2.py` → [midi.md](midi.md#the-foot-controller-chip-must-be-reflashed-when-switch-ownership-changes)

## Windows

- One input missing → generic ASIO wrapper; prefer the native driver by USB identity → [windows.md](windows.md#a-generic-asio-driver-can-lose-an-input)
- Input activity reads −150 everywhere → hidden window; use an armed track's meter → [windows.md](windows.md#getinputactivitylevel-is-useless-while-reaper-is-hidden)
- REAPER won't close → kill only after 15 s without answering `WM_NULL` → [windows.md](windows.md#a-hung-reaper-does-not-close-politely--and-a-dialog-is-not-a-hang)
- Lost writes / commands → retrying replace helper; Lua remove-then-rename → [windows.md](windows.md#replacing-a-file-fails-while-another-process-has-it-open)
- Garbled process list or JSON from PowerShell → detect UTF-16/BOM → [windows.md](windows.md#console-encodings-and-boms)
- Bridge alive at 100 % CPU, `/api/health` times out, installer says "did not start" → a snapshot does no I/O; one queued broadcast, none without a screen; `py-spy dump` first → [windows.md](windows.md#a-snapshot-that-does-work-starves-the-event-loop)
- TONE3000 downloads fail `err403` after minutes → honest golem User-Agent; Cloudflare 1010 fails at once → [windows.md](windows.md#tone3000-downloads-refused-with-403-error-code-1010)
- One golem per installer click, hidden "golem server" boxes → `bridge_start` asks `/api/health`; `GOLEM_NO_DIALOG` → [windows.md](windows.md#the-installer-started-golem-once-per-click)

## Data

- Silent lane with every check green → check what a reference CONTAINS, not only that it exists → [data.md](data.md#right-shape-wrong-nature)
- Nature guard fooled by a wrong field → read the nature from the file; declarations never contradict readings → [data.md](data.md#read-the-nature-do-not-trust-a-declared-one)
- Guarded item still plays → every consumer must read the verdict → [data.md](data.md#a-guard-nobody-consults-is-not-a-guard)
- Hole survives reviews → distrust commented exclusions; re-verify them → [data.md](data.md#be-suspicious-of-an-exception-that-explains-why-it-is-not-checked)
- Double cabinet nobody wrote → check the basis of rules that add to the signal → [data.md](data.md#a-rule-can-add-something-to-the-signal-that-no-document-contains)
- Screen and engine disagree → one source; show the engine's verdict where the user acts → [data.md](data.md#one-source-and-the-verdict-shown-where-the-user-acts)
- Breaks at the second guitar → hidden couplings (flat ids, role-indexed data, decorative fields) → [data.md](data.md#hidden-couplings-that-a-grep-does-not-show)
- Hand-edited preset reverts → edit through the sandbox path → [data.md](data.md#the-designer-edits-the-sandbox-not-the-preset-file)
- Feature dies after a rename → compared values are a protocol: write new, read both, test → [data.md](data.md#a-mass-rename-of-a-compared-value-breaks-silently)
- Noisy diffs, fresh install inherits a machine → never commit machine state → [data.md](data.md#never-commit-machine-state)
- "no model selected" for a pinned capture → a requested id passes before the A1/A2 ordering; re-pinning is a sound decision → [data.md](data.md#a-browsing-preference-must-not-rewrite-a-pinned-reference)

## UI

- Looks right in code, wrong on screen → render at 1024×600 / 390×844 and read the console → [ui.md](ui.md#verify-at-render-not-at-build)
- A tile fills the screen → prefix state classes (`pd-live`) → [ui.md](ui.md#generic-css-class-names-collide)
- "Hidden" controls visible → don't render the node → [ui.md](ui.md#the-hidden-attribute-is-beaten-by-any-author-rule)
- Page button disappears → pages publish, hubs only host → [ui.md](ui.md#settopaction-is-overwritten-by-the-parent)
- Fix delivered, old behaviour persists → tap the reload banner; `reload.sh` for Python → [ui.md](ui.md#the-rack-window-never-reloads-by-itself)
- Window frozen, `/api/health` says 0 screens, its WebSocket still "open" in the log → a dropped screen must be closed so it reconnects → [ui.md](ui.md#a-screen-dropped-on-a-send-error-must-have-its-socket-closed)
- Window at wrong size → dedicated `--user-data-dir` → [ui.md](ui.md#chrome-ignores---window-size-when-an-instance-already-runs)
- User trapped in a mode → ship every mode with a tested exit → [ui.md](ui.md#never-ship-a-mode-without-a-tested-exit)

## Tooling

- Tool says "no gap", user hears one → measure against an independent clock → [tooling.md](tooling.md#measure-with-a-clock-that-does-not-depend-on-what-you-measure)
- "0 ms" on an untouched effect → confirm the gesture landed → [tooling.md](tooling.md#check-that-the-gesture-reached-its-target-before-trusting-the-measurement)
- A check started a recording → probes restore state and never trigger Rec/backing → [tooling.md](tooling.md#a-probe-must-not-start-a-take)
- Real presets changed by tests → restore and say so → [tooling.md](tooling.md#clean-up-test-writes)
- Measurement shows "before" → wait for the person's "done" → [tooling.md](tooling.md#a-measurement-started-together-with-an-instruction-measures-nothing)
- Evidence gone after restart → `check-silence.py` first → [tooling.md](tooling.md#run-the-diagnostic-before-restarting)
- `pkill -f` kills the caller → exact names or PIDs → [tooling.md](tooling.md#killing-by-pattern-matches-yourself)
- "Running" while dead (`oom_reaper`) → equality on names → [tooling.md](tooling.md#on-a-process-or-action-name-compare--never-search-inside)
- `.gitignore` line ignores nothing → no trailing comments → [tooling.md](tooling.md#gitignore-does-not-accept-trailing-comments)
- Platform "tested" via monkeypatch → run on the real OS → [tooling.md](tooling.md#a-monkeypatched-platform-proves-nothing)
- Feature silently off → narrow `suppress`, lint undefined names → [tooling.md](tooling.md#swallowed-exceptions-hide-real-bugs)

## Install

- Clean VM inherits dev state and secrets → push with `.gitignore` filter → [install.md](install.md#a-test-install-must-not-inherit-the-developers-state)
- Non-interactive install fails at sudo → `sudo -n true` first → [install.md](install.md#sudo--v-needs-a-terminal-even-with-nopasswd)
- Install dies in phase 1 on a newer Ubuntu ("no installation candidate") → optional packages `name?`, resolved against the index → [install.md](install.md#a-package-that-a-new-ubuntu-release-removed)
- Installer stalls on System packages, password asked in the terminal (Ubuntu 25.10+) → sudo-rs needs `-A`: `sudo` shim in the job's PATH → [install.md](install.md#sudo-rs-ignores-sudo_askpass-without--a)
- Audio still crackles after the first install and a log-out → golem's processes survive the session: restart the computer → [install.md](install.md#golems-processes-survive-a-log-out--log-out-and-back-in-is-not-enough)
- First install fails, second works → `DPkg::Lock::Timeout=300` → [install.md](install.md#the-dpkg-lock-fails-the-first-install-on-a-fresh-machine)
- Install exits 141 → bounded producer under `pipefail` → [install.md](install.md#sigpipe-under-pipefail)
- Second run fails → idempotent, non-interactive steps → [install.md](install.md#the-install-must-be-replayable)
- Crash fix not active after `git pull` → run the patched-plugin scripts → [install.md](install.md#patched-plugin-builds-are-not-installed-by-git-pull)
- Unverified binary → pinned hashes only → [install.md](install.md#every-download-is-pinned)
- Fresh install: loading screen stuck on the sound card, REAPER frozen on "Error opening devices" / "error opening the project" → ALSA + the plugged card in `reaper.ini`, never the author's card; no set → `-new` → [install.md](install.md#a-fresh-install-must-not-assume-the-authors-sound-card-or-set)
- REAPER dies on the first recall, kernel says "invalid opcode in neural_amp_modeler.so" → CPU without x86-64-v3: NAM compiled here with `-march=native` → [install.md](install.md#prebuilt-plugins-need-x86-64-v3)

## Security

- New route readable by any LAN device → add it to the right tier in `auth.py` → [security.md](security.md#protection-is-by-url-prefix-a-new-route-outside-the-lists-is-public)
- Bridge fetches itself / rebinding page → Host allow-list, Origin check, public-address-only fetches → [security.md](security.md#local-means-admin--so-anything-that-makes-the-bridge-call-itself-is-admin)
- Config value reaches the environment → filter values, whitelist keys, admin-only restart → [security.md](security.md#a-config-value-that-reaches-the-environment-is-code-execution)
- Remote server swappable by a phone → admin-only, https except local → [security.md](security.md#the-remote-server-url-is-a-trust-anchor)

## Guards not found in code

Rules above that are documented but not enforced by any script at the time of writing:

- **Undo block in `golem_apply.lua` `main()`** (`reaper/Scripts/golem_apply.lua:1070`): still wraps
  every command routed to that script. Live actions (stomp, scene, mixer) are routed to `golem_rig.lua`
  and carry no undo; keep it that way.
