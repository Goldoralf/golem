# How-to recipes

Short, checklist-style recipes for the changes contributors make most often. Each one says when
to use it, which files to touch in order (with a snippet copied from an existing example), what
to run, and the traps specific to that change. They are derived from the code: when a recipe and
the code disagree, the code wins — fix the recipe in the same change.

| Recipe | Use it when you… |
|---|---|
| [add-block-type.md](add-block-type.md) | add an effect block to the Designer drawer (catalog, OS tables, aliases, presets, stall bench, quarantine) |
| [add-api-route.md](add-api-route.md) | add an HTTP endpoint to the bridge, and decide who may call it (`bridge/auth.py`) |
| [add-app-page.md](add-app-page.md) | add a page or a hub tab to the app (Preact + htm, no build, 1024×600, no scroll) |
| [add-golemfm-job.md](add-golemfm-job.md) | let golem.fm ask the rack to do something (`bridge/tones_jobs.py`) |
| [add-reaper-loop.md](add-reaper-loop.md) | run something permanently inside REAPER (Lua `defer` loop, command relay, telemetry) |
| [add-jsfx.md](add-jsfx.md) | write an in-house JSFX (effect block, service engine or probe) |

## Rules that apply to every recipe

- `bridge/*.py` changed → `./provision/reload.sh` (uvicorn runs without `--reload`).
  JS/CSS/Lua: a refresh is enough — but the rack window only reloads when its banner is tapped.
- UI text in **English**, code comments in **French**. The brand is displayed as `golem` or
  `/golem_`; identifiers (`GoleM` folders, firewall rule, mDNS service) stay as they are.
- Never commit local state: `sets/*.rpp`, `presets/*.json`, `mappings/*.json`, `config/`.
- Verify at render (Chrome headless at 1024×600) and on the rig (measure), not at build.
- `./tools/check-cold.sh` must stay green (pytest, then the descriptor, pedalboard chip,
  transcription, standards and meter checks — no bridge, no REAPER needed).
- A decision that matters goes in a contract `docs/*.md` with its status, not in a commit message.
- Scripts that write real files (presets, setlists, mappings) are restored after a test.

The longer story behind each trap is in [`CLAUDE.md`](../../CLAUDE.md); the contribution rules
(DCO sign-off, licences per zone) are in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
