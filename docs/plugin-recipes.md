# Capture recipes: golem.fm proposes, the rack measures, the musician validates

> **Status: CODED (rack side)** — how a capture recipe for an unknown plugin is drafted by golem.fm's AI, verified
> by measurement on the rack and validated by the musician (`bridge/plugin_recipes.py`); the cloud side is described
> only through the calls the rack makes.

Capturing a VST **whole** works for any plugin. Capturing it **effect by effect** and **naming what blocks**
("Chorus is on") requires knowing which parameter switches what: a plugin only exposes names and values. A recipe
(format: [`plugin-capture.md`](plugin-capture.md) §2) carries that knowledge. One recipe ships in the repository;
others are drafted by an AI on golem.fm, because only something that knows the plugin can read its parameter names.

## 1. Roles

| | does | never does |
|---|---|---|
| **rack** | describes the plugin (its parameters), **measures** every claim of the draft, shows the result, keeps the recipe | interpret parameter names |
| **golem.fm AI** | proposes a draft, each claim with a reason and a confidence | decide: its draft is never applied as is |
| **musician** | validates with the plugin open, or corrects | — |

A declared nature is worth nothing until it is read. The AI **declares** ("`Time Active` is a chorus"); the rack
**reads** (does the sound move when that switch is on, and only then?). A claim the measure contradicts is
rejected and shown; a claim the measure cannot settle stays marked "declared".

## 2. Flow

```
 rack                                              golem.fm
  │ ① GET  /api/ext/golem/plugin-recipes?plugin=&os=&version=   a validated recipe exists?
  │ ◄── 200 {recipe, validated:{count,…}, version_match}     → measured again here (§5), then ④
  │ ◄── 404
  │ ② POST /api/ext/golem/plugin-recipes/analyze  (the sheet, §3, no audio)
  │ ◄── 202 {request_id}                                      the AI works (async)
  │ ◄── job `plugin-recipe` {request_id, plugin, sha}, blob = draft
  │ ③ the rack measures every claim (separate REAPER, when idle) → ack {status, verified, rejected, declared}
  │ ④ the musician validates in the drawer
  │ ⑤ POST /api/ext/golem/plugin-recipes  (the validated recipe, shared)
```

If golem.fm is unreachable nothing changes: the whole-plugin capture (no recipe) stays available. The exact
calls, scopes (`tones:read` for the GET, `tones:write` for the others) and the `plugin-recipe` job are listed in
[`golemfm-protocol.md`](golemfm-protocol.md) §3–4.

Rack routes (drawer, Windows/macOS only for `analyze`):

| Route | Function |
|---|---|
| `GET /api/vst-host/recipe?plugin=` | `poll` — local state (the whole draft, rejected claims included); polls `GET …/analyze/{request_id}` while `analyzing` |
| `POST /api/vst-host/recipe/analyze` `{block, plugin, restart?}` | `analyze` in a thread (the sheet takes ~11 s) |
| `POST /api/vst-host/recipe/validate` `{plugin, edits[]}` | `validate` |
| `POST /api/vst-host/recipe/forget` `{plugin}` | `forget` — delete the local recipe |

## 3. The plugin sheet (`plugin_recipes.sheet`)

Read in a **separate REAPER** (`plugin_capture.bench_run`) on the musician's block state; their instance is not
touched.

```json
{
  "plugin": "VST3: Example Lead Suite (Example Vendor)",
  "vendor": "Example Vendor", "format": "VST3", "os": "windows", "plugin_version": "1.1.0.0",
  "params": [{"i": 3, "name": "Pedals Active", "display": "Active", "norm": 1.0, "min": 0, "max": 1,
              "display_min": "Inactive", "display_max": "Active"}],
  "steps": {"3": ["Inactive", "Active"], "16": ["Clean", "Rhythm", "Lead"]},
  "known_recipe_schema": 2,
  "instrument": false
}
```

- `plugin` — the **exact REAPER name**, whose prefix carries the format (`VST3:`, `VST:`, `CLAP:`): VST2 and VST3
  of one plugin are different keys. `format` is sent as well (`_format`).
- `os` — `platform.system().lower()` (`rack_os`, same value as the heartbeat `caps.os`): `windows`, `darwin`,
  `linux`.
- `plugin_version` — read from the plugin **file** (`plugin_version`): the Windows version resource of the
  `.vst3`/`.dll`, or `CFBundleShortVersionString` of the macOS bundle; `null` if absent. The path is the `ident`
  of the REAPER plugin list (`plugin_file`).
- `params` — every parameter REAPER reads (index, name, displayed value, normalized, bounds, display at norm 0
  and 1). MIDI CC matrix parameters are dropped.
- `steps` — for stepped parameters (switches, selectors), the **displayed** value of each step, read by sweeping
  the normalized value (up to `MAX_STEPS`). The AI must write `"Inactive"`, not guess `"Off"`.
- `instrument` — true for a `VST3i:`-style prefix; the rack answers `unsupported` itself.

No audio and no user setting leave the rack.

## 4. The draft (job `plugin-recipe`)

The blob is a recipe in the format of `library/catalog/plugin-captures.json` (`schema` 2) plus, on every claim,
an `id`, a `why` (English, displayed) and a `confidence` ∈ `high | medium | low`. Claims are the entries of
`full.refuse[]`, `full.captured[]`, `split.parts[]` and `translate[]` (`_claims`).

Rules, checked by `check_draft` (a violation → ack `status: "invalid"` with `errors[]`):

1. Every parameter name cited exists in the sheet.
2. Every value is a step of a stepped parameter; for a continuous one it is the current display,
   `display_min`, `display_max`, `"min"` or `"max"`.
3. Every claim has a unique `id`, a `why` and a valid `confidence`.
4. `when` carries the **section and** the effect switch (an effect "on" in a disabled section does not play).
   The switch the rack toggles to measure is `switch`, or else the **last** key of `when`. For `refuse` and
   `captured`, the switch must be a stepped parameter.
5. `full.off` only switches off effects **after the amp** that will be translated; anything before the amp that
   moves belongs in `refuse` — golem never switches off for the musician.

## 5. Verification (`plugin_recipes.verify`)

All renders of one verification run in **one REAPER session** (`render_many`; launching REAPER is most of the
cost of a short render). The bench forces settings in that instance only: a claim is tested whatever the
musician's current setting. It waits while `reamp.busy_reason(idle=False)` reports a reason (recording, Gig mode,
a song playing or loading) and shows it as `waiting`.

**Probe** (`_probe`): the validation passage of the NAM v3 signal (9 s), 0.5 s of silence, the same passage,
then 3 s of silence (the tail).

**Measures:**

| Measure | Meaning |
|---|---|
| `self_esr` (`m_self_esr`) | difference between the two identical passages: does the sound move **in time**? ≈ 0 = static |
| `tail_db` (`m_tail_db`) | energy of the final 3 s (after a 50 ms margin) below the signal's: a delay or reverb tail |
| `on_vs_off_db` (`m_null_db`) | energy of the difference between "on" and "off" renders, relative to the signal. High = the switch changes the sound; ≤ −40 dB = it does nothing. Not a level change |
| `peak` (`m_peak`) | silence / clipping of a split part |
| `linear_db` | a cab part rendered at half level, doubled, against the full render: a cab is linear, an amp is not |

Thresholds: `STABLE_MAX` 1e-3 (a plugin without time effects renders 0 or close), `MOVES_MIN` 0.01 (the NAM
trainer's), `AUDIBLE_DB` −40, `TAIL_ON_DB` −60, `TAIL_OFF_DB` −80, `LINEAR_DB` −40.

**Plan** (`plan`): every configuration sets **all** keys the recipe cites; untouched keys keep the musician's
normalized value. `quiet` = `full.off` applied plus every `refuse` and `translate` switched off. A `refuse` or
`translate` claim is rendered "on alone" against `quiet`; a `captured` claim on vs off; a split part with its
`off` (plus a half-level render for an IR part). A claim whose switch has no two-step on/off is `declared`.

**Verdicts** (`judge`):

| Claim | Verified when | Otherwise |
|---|---|---|
| `full` (`quiet`) | `self_esr` ≤ 1e-3 and tail ≤ −80 dB | rejected: an effect the recipe does not know is on |
| `refuse` | audible (`on_vs_off_db` ≥ −40) and it moves (`self_esr` > 0.01) or rings (tail > −60 dB); `kind: pitch` only needs to be audible (pitch nature declared) | "has no audible effect" / "doesn't move the sound: it could be captured" |
| `captured` | audible, static, no tail (nature stays declared) | moves or rings → rejected; inaudible with these settings → declared, not rejected |
| `translate` delay/reverb | tail > −60 dB | "leaves no tail: not a delay or reverb"; other blocks → declared |
| split part | not silent, not clipping (except IR), static; an IR part also linear | rejected with its measure |

**Bench fault** (`bench_fault`): if the `quiet` render shows no signal (< −100 dB) or noise (`self_esr` > 0.5 or
tail > −20 dB), the bench did not play the plugin. The verification is retried once after 30 s, then fails with
`ok: false` — a silent bench never produces a "rejected".

**Status**: `rejected` if `full` is rejected or nothing is verified, `partial` if some claims are rejected,
`verified` otherwise. A split with a rejected part is dropped entirely (`split:dropped`): an incomplete per-effect
capture would be wrong.

**Ack** (sent by the verification thread, the job returned `ASYNC_ACK`): `{ok: true, result: {request_id, status,
verified[], rejected[{id, measure, why}], declared[], errors[], probe_s, renders, measures, rack: {os}}}`.
`ok: true` as soon as the measure ran — a rejection is a successful measure. `ok: false` + `error` only when the
measure could not run.

**A recipe received already validated (①)** goes through the same verification on this plugin (a different
plugin version may differ). If it rejects claims, the rack reports them (`report` →
`POST …/plugin-recipes/report`); no ack is sent since there is no job.

## 6. Local state (`config/plugin-recipes/<slug>.json`)

Local, never committed. `{plugin, os, plugin_version, block, request_id, state, step, draft, verification, edits,
shared, waiting, error, validated_at, updated}`. `state`: `analyzing` → `verifying` → `to-validate` →
`validated`, or `unsupported` | `failed` | `rejected`. A new analysis forgets the previous request.

Only a `validated` recipe is used: `validated_recipe` returns `applied(draft, verification, edits)` — the draft
minus measured rejections and lines the musician removed, with their renames; a split missing a part is dropped.
`plugin_capture.recipe_for` reads it before the repository seed.

## 7. Validation (drawer)

`app/designer-vst-host.js` shows the recipe as a list of lines tagged **MEASURED**, **DECLARED** or
**REJECTED**. The musician, plugin open, renames (✎) or removes (✕) lines, then taps **"This matches my plugin"**
(or "Discard"). `validate` stores `state: "validated"` and posts `{plugin, format, os, plugin_version, recipe,
verification, edits, validated_at}` to golem.fm (`shared_status` keeps the answer). Without that tap the recipe
is used by nobody.

Error codes read from golem.fm answers (`_http` flattens FastAPI's `detail`): `unsupported` (instrument, or a
pedalboard with reorderable pedals: whole-plugin capture only), `ai_quota`, `ai_off`, `schema`.

## 8. Why the capture itself has no tail warning

The v3 training signal has only 0.5 s of silence before its second passage: over that window a long reverb and
a dry pedal's noise floor cannot be told apart reliably. The capture warning therefore stays `self_esr` alone
(modulation, modulated reverb); the recipe probe ends on 3 s of silence and separates tails cleanly.
