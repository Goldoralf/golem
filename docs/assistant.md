# The assistant — golem.fm in front of Health

> **Status: PARTLY CODED (2026-10-20).** **CODED:** step 1 — §3 the action registry, Health ▸ Fix, `golem doctor`,
> and §3.1 incidents with how they ended, sent in the diagnostic reports (`bridge/fixes.py`, `bridge/incidents.py`,
> `tools/doctor.py`; the page in [health.md](health.md) §1.4); step 3 on the rack — §5–§6 « Ask golem »
> (`bridge/assistant.py`, the drawer in `app/page-health.js`), against golem.fm's `POST /api/ext/assistant/ask`
> (coded on golem.fm's side, not deployed yet). **PROPOSED:** §4 the help pages (golem.fm's ids exist, no page is
> written: a cited page is named, not linked).
>
> Revised from a first draft
> ("golem — Assistant IA embarqué, spec v0"), then re-decided: the conversation runs on **golem.fm**, not on a
> local model. This **applies** the 2026-09-09 decision (commit `23f813f1`: the AI lives on golem.fm, the rack
> stays the validator) instead of working around it. A local model was studied and set aside (§9).
>
> §3.1: the diagnostic reports say **how each failure ended**, not only that it happened.
>
> Depends on [health.md](health.md) (facts, "Why no sound?", the first-start check),
> [golemfm-protocol.md](golemfm-protocol.md) (pairing, token, `/api/ext/…`), [telemetry.md](telemetry.md) (what
> leaves a machine), [diagnostics.md](diagnostics.md) (the whitelist discipline), [modes.md](modes.md).

## 0. What it is, in one paragraph

A chat panel in Settings ▸ Health. The musician asks in their own words ("it crackles when I change scene",
"how do I add a second guitar?"). golem sends the question, its Health facts and **its own list of actions** to
golem.fm; golem.fm answers in plain words, cites a help page, and may **propose one action**. golem validates
that proposal against its registry, shows it (before → after), runs it on one tap and verifies it by re-running
the probe. golem.fm proposes, the machine decides. Without golem.fm — not paired, offline — Health ▸ Fix, the
help pages and `golem doctor` still do the job.

## 1. Where it lives

| Use | Assistant | Without it |
|---|---|---|
| **Desktop / laptop** (`golem desktop`), paired, online | **Yes** | — |
| **Rack** (`golem server`, the box in the rehearsal room), paired, online | **Yes** — nothing runs on the machine but an HTTP call | — |
| Not paired, offline, or golem.fm unreachable | Absent from the UI (not greyed) | Health ▸ Fix (§3), the help (§4), `golem doctor` |

No GPU, no model, no download on any machine. golem.fm stays **optional** (golemfm-protocol §0): every step that
does not need it must stand on its own.

## 2. Principles

| # | Principle |
|---|---|
| P1 | **golem.fm proposes, the machine decides.** A proposed action is validated by the bridge (exists in the registry, parameters within the schema, the objects exist) before anything is shown. An invalid proposal is dropped and said. |
| P2 | **No shell, no free command.** golem.fm can only name an action the machine sent it, with parameters. Nothing arrives from outside on its own: the machine asks, golem.fm answers. |
| P3 | **Recipes, not improvisation.** A system fix is a script written and tested by us; the model picks the recipe and its parameters. |
| P4 | **Read-only while playing**, enforced locally (`reamp.busy_reason(idle=False)`: gig mode, locked mode, a take, a song, a load, a preview render). golem.fm cannot lift it. |
| P5 | **Reversible.** An action that changes a persistent setting carries its own undo (the buffer: the size before), offered on the incident it closed. No global snapshot: no other action of the registry changes anything that could be undone (a resync, a restart, reopening a device, re-posing the preset). |
| P6 | **Clean give-up.** No matching action → the answer says so and offers the diagnostic report; no other attempt. |
| P7 | **Absent when unavailable.** Not paired or unreachable → no entry in the UI. |
| P8 | **Consent and a whitelist.** The first question asks once what will be sent; what is sent is a fixed whitelist, never a secret or a name (§6). |

## 3. Step 1 — Health ▸ Fix and `golem doctor` (no AI; required either way)

This is the foundation, it serves every machine, and it is what remains when golem.fm is not there. It extends
[health.md](health.md) §4.

**The action registry** lives in the bridge. Each action declares:

| Field | Meaning |
|---|---|
| `name`, `description` | the description is written with care: it is what the model reads |
| `risk` | `read` (runs freely) · `modify` (before → after shown, one-tap confirm) · `system` (dry-run shown, privileged helper) |
| `params` | a JSON schema with bounds (`enum` for a buffer size, an existing input `ch`, an existing plugin id) |
| `live_allowed` | false for everything that is not `read` (P4) |
| `verify` | the probe re-run after the action; the fix is done only when it is green |
| `help` | the help page(s) it belongs to (§4) |

Kept **short** — a few dozen actions. Built (2026-10-20), all existing code paths: `set_buffer`, `osc_refresh`,
`reaper_restart`, `audio_reset`, `midi_reinit`, `repose_preset` (modify), `silence_hunt`, `health_facts` (read).
Next candidates: the scene gap probe, assign an input's instrument (`POST /api/inputmap`), quarantine a plugin
**as data** (`effects.json`, never a file deletion). Hardware advice ("turn down the gain of IN 2") is a verdict, not an
action.

**Never exposed:** deleting a preset, song, take or setlist; a global config reset; anything that records or
makes sound (a probe never starts a take).

**System recipes** (`system`): only where a tested script exists, through the privilege model golem already uses
— a root-owned script plus a narrow sudoers entry, as `net.sh` does on Linux; the Windows and macOS equivalents
follow the installer's. Scope: RT limits, audio group, release a device lock, rescan plugin paths, repair
golem's own components (`components.json` and the install receipt). **Out of scope:** kernel, bootloader,
drivers, distribution upgrades, and **installing distribution packages**: plugins golem ships are installed by our
scripts; a third-party plugin missing a library is quarantined, the scene plays without it, and the musician is
told why.

**`golem doctor`** is the same registry from the command line — the path when the screen is dead or the network
is down. `tools/check-silence.py` already drives the "Why no sound?" route; doctor generalizes it.

**Journal:** every action — who asked (a button, the assistant, doctor), parameters, result of `verify` — goes to
the diag timeline and the session packet. Beyond a journal, the goal is to know **how each failure ended**: §3.1.

### 3.1 Incidents and how they were resolved — sent to golem.fm

The diagnostic reports ([diagnostics.md](diagnostics.md), CODED) already send each machine's failures to
golem.fm: `event` packages on a trigger (REAPER down, audio lost, rig-check failed, xrun burst, an ERROR), the
timeline in the `session` package, the first-start check in the `boot` package. What they do not say is **how a
failure ended**. This adds the link, on the same channel, under the same rules (the reports box, the inverted
whitelist, the closed vocabulary, the scrubber, 90 days on golem.fm).

**An incident** is opened by a trigger of diagnostics §4.2 or by a red Health verdict (a probe result, the
first-start check, "Why no sound?"), and gets a short id. It is closed by the first of:

| `resolved_by` | How the machine knows |
|---|---|
| `action` | a registry action (§3) ran and its `verify` went green — with `action`, `by` (`button` / `assistant` / `doctor`) |
| `outside` | the same probe went green with no action in between: the musician did something golem cannot see (a cable, a knob, a power switch) |
| `restart` | REAPER, the bridge or the machine restarted and the probe is green after |
| `open` | still red when the session closes — sent as such; a recurring `open` is the most useful signal of all |

For `outside`, one optional tap on the green verdict — "What fixed it? cable · gain · power · other" — turns a
guess into a fact. Never asked during a take or in a stage mode.

**New timeline events** (diagnostics §2.3, closed vocabulary, types and codes only — never free text):

| `type` | Fields |
|---|---|
| `incident` | `id`, `state` (`open` / `closed`), `kind` (the trigger type or the probe), `code` (the verdict code, e.g. `no_input`, `downstream`), `stage` |
| `fix` | `id` (the incident, if any), `action`, `params` (**types and bounded values only**: a buffer size, an input number — never a name or a path), `by`, `verify` (`ok` / `ko`), `ms` |
| `resolution` | `id`, `resolved_by`, `after_s` (time from open to close), `hint` (the tap above, if given) |

A closed incident with an `action` builds no `event` package of its own: it leaves with the `session` package.
An incident still `open` at session end goes in the session summary.

**The assistant's part:** the conversation itself is **not** stored by golem in a report — free text cannot be
scrubbed reliably, and golem does not know people. The report carries the structured outcome only: the
assistant was asked (`by: assistant` on the `fix`), the help pages it cited (ids), the action proposed, accepted
or refused, and `verify`. Whether golem.fm keeps the text of questions it received at ask time (§5) is golem.fm's
decision under its own privacy terms, and must be said in the consent of §6.

**What golem.fm gets out of it, per machine and across machines:** which failures happen, how often, how long
they last, which ones end by an action (automate them further), by `outside` (write the help page, or detect it
better), or stay `open` (the bugs to fix first). golem.fm owns any longer retention of **aggregated** counts.

## 4. Step 2 — a help written for musicians

Our `docs/` are for contributors (architecture, pitfalls, formats). The assistant and the verdicts need pages a
player understands:

- **One short page per task or symptom**, in plain English: "plug in a second guitar", "no sound", "the pedalboard
  does nothing", "crackles", "change the output". `docs/troubleshooting.md` is the seed, rewritten for a player.
- Each page links the registry actions that solve it (`help` field, both ways); each Health verdict links its page.
  **Retrieval done deterministically** — it works with no AI and no network.
- **Hosted on golem.fm** (updated without a release) **with a copy shipped in golem** (offline, unpaired). The
  copy is the floor; golem.fm can be newer, never required.

## 5. Step 3 — the assistant through golem.fm

**The exchange** (one request per question; a conversation is a sequence of them):

1. **golem → golem.fm**, `POST /api/ext/assistant/ask` with the pairing token (golemfm-protocol §0), body:
   `{question, history?, facts, verdicts, actions, context, lang}`.
   - `actions`: **the machine's own registry** (name, description, risk, params schema, `live_allowed`) as this
     version of golem defines it. The machine is the source of truth of what it can do: no version skew, and
     golem.fm never needs to know golem's code.
   - `facts` / `verdicts`: the Health facts and the last probe results; `context`: the whitelist of §6.
   - `busy`: the local `busy_reason`, so the answer can say "stop playing first" instead of proposing.
   - `lang: "auto"`: golem.fm answers **in the language of the question** — English when it is ambiguous (owner,
     2026-10-20). The answer and the proposal's `why` follow the musician; the screen's labels (buttons, the "Fix"
     sheet) stay English — they are the interface, not the conversation. No language detection on the rack.
2. **golem.fm → golem**: `{answer, cites: [help page ids], propose?: {action, params, why}}` — at most one
   proposal per answer.
3. **golem validates** the proposal (P1). Valid → shown with its before → after and a confirm button; invalid →
   dropped, and the panel says the assistant proposed something golem cannot do.
4. **On tap**: snapshot (P5, once per session), run, `verify`, journal. The result is sent back as the next
   message's `history`, so the conversation knows whether it worked.

Nothing reaches the machine without the machine asking. The job queue (golemfm-protocol §3) is **not** used: it
exists for golem.fm to send work to a machine; here the machine asks and the musician confirms on its own screen.

**When it is available:**
- Paired, golem.fm reachable, and the account allowed (§8). Otherwise absent (P7).
- It is a **mode service** (`modes.md` §3.1, `services.assistant`): on in Home, off in the stage modes. Adding it
  to a mode is data.
- Asking while golem is busy is allowed; proposing a `modify` or `system` action is not (P4).

**What the model does, and does not:** it **translates** words into a probe and verdicts into a sentence,
**chooses** among the machine's actions, answers "how do I…" from §4's pages **citing the page**. It does not
diagnose on its own: the facts come from the probes. No page and no matching action → it says so and offers the
report (P6).

## 6. What leaves the machine

Only when the musician asks a question, after a one-time consent ("Your question and a summary of this golem's
state are sent to golem.fm and forwarded to the AI provider it uses, to answer it. golem.fm keeps no text of it."),
withdrawn by "Stop sending" at the bottom of the drawer (`config/.assistant.json`, local).

| Sent | Never sent |
|---|---|
| the question and the conversation's previous turns | tokens, keys, passwords, the pairing secret beyond the auth header |
| Health facts and verdicts (engine, card, buffer, xruns, probe results) | person names, band names, song titles, file paths under the user's home |
| the input map **roles** (guitar on IN 2), the active preset's **summary** (block types, scene count) | audio, takes, recordings |
| the action registry, the busy reason, OS / golem version | anything from another machine on the network |

Built like the diagnostic packet: a whitelist in the bridge, checked by a test, with `violations()` refusing a
name. When coded, the call goes into [telemetry.md](telemetry.md) (a user-initiated send, listed with the others)
and `POST /api/ext/assistant/ask` into [golemfm-protocol.md](golemfm-protocol.md) §4 — its test fails until it is.

## 7. Order

1. Registry + Health ▸ Fix + `golem doctor` + journal (§3), and incidents with their resolution in the
   diagnostic reports (§3.1) — the same journal, sent on the channel that already exists.
2. The help pages, shipped copy first, linked from verdicts (§4).
3. With golem.fm: the help hosted there; `POST /api/ext/assistant/ask` specified together (rack side here, golem.fm side
   in their repo).
4. The panel, consent, whitelist, validation of proposals (§5, §6).
5. System recipes (§3), Linux first, then Windows and macOS.

Steps 1 and 2 are required: they are what a machine without golem.fm gets.

## 8. What golem.fm owns, and what it answered (2026-10-20)

The model, its instructions, the hosted help, rate limits per account, cost, and whether the assistant is free
or part of a plan. Asked which golem.fm functions give access to the AI, golem.fm's session answered (nothing coded
on either side yet):

- **No assistant route exists; the building blocks do.** A one-shot JSON call to the AI provider (server key, a
  provider golem.fm configures), a monthly quota per plan with a token meter (`AiUsage` rows), and the device
  pairing token with scopes. Step 3 is a thin route on their side.
- **Endpoint:** `POST /api/ext/assistant/ask`, the pairing token, a new device scope `assistant:ask`. The request and
  answer formats of §5 are accepted as written. golem.fm validates too: `propose.action` must be one of the
  `actions` sent and its `params` must pass that action's schema, otherwise the proposal is dropped and the answer
  kept; `cites` is filtered against the known help ids. Caps on question length, history turns, ~30 actions, body
  size → `413` / `422`.
- **Refusals**, in golem.fm's existing shape `{"detail": {"error", "message", …}}` — `message` is a sentence the
  panel shows: `503 ai_off` (no key on the server), `429 ai_quota` (+ `used`, `limit`), `429 rate_limited`
  (+ `retry_after`), and `402 plan_required` only if the assistant is gated by plan.
- **Retention:** golem.fm keeps **no text** — neither question nor answer; one usage row (account, kind, model,
  token counts, ok, date). The consent must say that the question and the facts are **forwarded to the AI provider
  golem.fm uses**, which applies its own policy — without naming a provider that can change.
- **Help ids:** golem.fm's docs tree (`/docs/<section>/<page>`) gives citable ids such as `help/no-sound`,
  `golem/soundcard`, `golem/modes`; golem.fm proposes `golem/health` for Health ▸ Fix. **None is written yet**
  (titles and outlines only, writing planned for the v1.0 release candidates). The rack ships a copy of ids and pages.
- **The reports:** the new events and the `incidents` section already arrive in the zips golem.fm keeps per machine
  (90 days); its summary page and its analysis prompt do not read them yet — a small change on their side.

**Decided (owner, 2026-10-20):**
1. **Re-pair.** A rack paired before the scope `assistant:ask` existed is re-paired; no migration of old tokens. On
   a `403` for that scope, the panel says so and offers the pairing (Settings ▸ Connect) — nothing else.
2. **The quota is golem.fm's, per plan.** golem.fm decides how many questions each plan includes (its own counter
   or not) and whether a plan has none. The rack never counts: it shows the `message` of a `402` / `429` as it comes.

Step 3 can start on the rack once golem.fm's route exists.

## 9. Studied and set aside: a local model

A local model on desktop installs (llama.cpp, a 7–8B instruct model, measured speed test, mode service paused
while playing) was studied the same day. Set aside because it costs much more for a worse result: a 4–5 GB
optional engine on three OSes and GPU runtimes, model licensing, GPU load on a laptop that also runs the audio
(shared power and cooling → CPU throttling → xruns), and a small model more prone to confident wrong answers —
for nothing the golem.fm path does not do better. It would only come back if musicians ask for an assistant that
works **offline and private**; the registry of §3 would serve it unchanged.

## 10. What it adds over Health alone — the honest account

- **For a known failure, nothing.** A probe plus a registry action is faster and more reliable; the assistant
  can only call the same action.
- **Where it adds:** the musician who does not know which check to run (it maps their words to the right probe);
  "how do I…" questions, which will outnumber failures; explaining several facts together in one sentence. All
  about **the front door**, not about capability.
- **Its main risk** is a confident wrong answer about the UI. Citing a page or refusing is the guard.
- **The decision rule:** after step 1, read the journal. If most sessions end on a known verdict found by a
  button, the assistant is a nice-to-have; if many start with a question nobody mapped, build step 3.
