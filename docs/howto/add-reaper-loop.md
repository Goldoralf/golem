# How to add a persistent REAPER loop (Lua `defer`)

**When:** something must run continuously inside REAPER — poll a JSFX through `gmem`, own a
service track, execute commands from the bridge, publish telemetry. Model: `golem_click.lua`
(command relay + state file + armed service track); `golem_looper.lua` / `golem_knobs.lua` for gmem.

## Files, in order

1. **`reaper/Scripts/golem_<name>.lua`** — the loop. Skeleton, as in `golem_click.lua`:
   ```lua
   local ROOT = repo_root()                                       -- golem-root.txt, see golem_click.lua
   local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
   local GEN = tostring(reaper.time_precise())
   reaper.SetExtState("golem", "<name>_gen", GEN, false)          -- the last instance started wins

   local last_seq                                                 -- ADOPT the saved command, never replay it
   do local _, b = reaper.GetProjExtState(0, "golem", "<name>_cmd")
      last_seq = b and b:match('"seq"%s*:%s*(%-?%d+)') or nil end

   local function loop()
     if reaper.GetExtState("golem", "<name>_gen") ~= GEN then return end   -- replaced: die
     reaper.gmem_attach("golem_<name>")                           -- EVERY tick (shared Lua context)
     local ok, err = pcall(tick)                                  -- an error never kills the chain
     if not ok then log("tick: " .. tostring(err)) end
     reaper.defer(loop)
   end
   loop()
   ```
   - `tick()` reads `<name>_cmd`, dedups on `"seq"`, applies, then publishes state.
   - **Publish atomically:** write `path .. ".tmp"`, then `runtime.replace(tmp, path)`
     (`golem_paths.lua`: on Windows `os.rename` cannot overwrite, so it removes then renames —
     readers must tolerate a brief absence). Volatile state goes to `runtime.runtime_file(name)`
     (`/dev/shm` on the rack, a cache folder on desktops); `golem_click` uses `presets/.click.json`.
   - A **service track** that has no input and no item must be armed with `I_RECMODE = 2` ("none")
     + `I_RECARM = 1` (`ensure_live` in `golem_click.lua`), or REAPER drops it from the live graph
     after ~2 s of silence and its JSFX `@block` stops forever. Monitoring alone is not enough.
2. **`reaper/Scripts/__startup.lua`** — add a `dofile` block like the others. Every script runs in
   **one** Lua context: one `gmem` attachment (hence the per-tick re-attach), and `reaper.defer`
   is wrapped there with `xpcall` — an uncaught error is written to `presets/.lua-errors.log`
   and only that loop stops.
3. **`reaper/Scripts/golem_watch.lua` → `tick()`** — the only reader of `presets/.command.json`.
   Add `local is_<name> = (action == "<name>")` (exact action, parsed once — never a substring:
   `"reload","script":"golem_tuner"` once disarmed the tuner), then a relay branch:
   `reaper.SetProjExtState(0, "golem", "<name>_cmd", cur)`. If the loop never touches the preset
   FX graph, add `is_<name>` to the exemption list of the post-rebuild freeze (`SETTLE`, 0.5 s).
4. **`reaper/Scripts/golem_apply.lua` → `ALLOWED`** in the `reload` action — the whitelist of
   scripts that may be hot-swapped. Without it your loop can only be updated by restarting REAPER.
5. **Bridge side** — send with `bridge.commands.write_command({"action": "<name>", ...})` (adds
   `seq`, waits for the previous command's ack, queues; `_superseded` drops commands made useless).
   Read the state file with `bridge.config.runtime_file(...)` / `presets/`.

## Checks

- No Lua interpreter here and nothing compiles: read the loop's own log, `presets/.watch.log`,
  `presets/.lua-errors.log`.
- Hot swap without restarting REAPER:
  `.venv/bin/python -c 'from bridge.commands import write_command; write_command({"action": "reload", "script": "golem_<name>"})'`
  `presets/.apply.log` must show "golem_<name> rechargé" and the old instance must stop.
- Restart REAPER once: the loop must come up silent (no replay of the saved command).
- A JSFX witness slider (a counter) read with the `fxparams` command proves the audio thread runs.
- Ask the `golem-reascript-engineer` agent to review: this code cannot be unit-tested here.

## Traps

- `SetProjExtState` is **saved in the project**: at the next REAPER start the last command is still
  there. Adopt its `seq`, never execute it (`golem_watch` does the same with `.command.json`).
- `reaper.time_precise()` restarts at each launch: never persist it (`P_EXT`, project state) and
  compare it later — a "future" value from yesterday kept a loop busy-waiting for hours.
- Editing `golem_watch.lua` itself has no effect until it is reloaded (`reload` + `golem_watch`)
  or REAPER restarts — it is loaded once.
- A modal dialog (render overwrite, "Save?") freezes REAPER's main thread: every loop stops.
- Commands that are not relayed fall to the last branch, which picks `golem_rig` over
  `golem_apply` when the JSON contains the quoted token `"rig_recall"` or `"stomp"` **anywhere**,
  not only as the action. Relay your action explicitly (step 3) instead of relying on that branch.
