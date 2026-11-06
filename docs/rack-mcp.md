# The rack's MCP server — read-only

> **Status: CODED** — a read-only MCP server on `POST /mcp` that answers questions about the rack's
> current state; every write goes through the golem.fm job queue (`bridge/mcp.py`, tests in
> `tests/test_mcp.py`).

## 1. Why it exists

A client (golem.fm, a developer, an agent debugging next to the rack) that wants to know the rack's
**state** should ask the rack, not deduce it by reading the source code: code gives the rule, never the
state. For example, `presets/.rig-check.json` says which file each plugin really loaded; `rig_check`
returns it.

## 2. The boundary

| | |
|---|---|
| **Read** | this server |
| **Write** | the **job queue** — `patch-try`, `patch-install`, `install`, `t3k-install`… (see [`golemfm-protocol.md`](golemfm-protocol.md)) |

The queue is ordered, acknowledged and auditable: a job leaves a trace, a refusal reason, an
`unresolved[]`. An MCP call that mounted a preset would open a second path to change the machine, with no
guaranteed order and no history. `test_aucun_outil_ne_peut_ecrire` refuses any tool whose name announces
a mutation (`set`, `install`, `apply`, `recall`, `delete`…).

## 3. Tools (`mcp.TOOLS`)

| Tool | Arguments | Answer |
|---|---|---|
| `rig_check` | `history?` | the rack's file verdict: what each block had to load and what the plugin really reports. `issues: []` means everything is in place. `history` returns the last abnormal passes (see §6) |
| `resolve` | `ref`, `model?`, `type?` | dry run of a capture ref: `{found, file, exists, why}`. Accepts a catalog id (`44209`) **and** a pack uid (`t3k:44209`). With `type` (the block that will carry it), also checks the file's **nature** (`rig._wrong_kind`) and returns `usable_as` |
| `captures` | `limit?` | what is installed **right now** (`rigstatus.captures`), not the heartbeat snapshot |
| `jobs_log` | — | the rack's side of the queue (`tones_jobs.status`): its counters, the last 10 log lines and the jobs in flight |
| `patch` | `id?` | the patch document the rack holds; without `id`, the list |
| `preset_export` | `id` | the export envelope of a preset, `deps[]` and `unresolved[]` included ([`preset-format.md`](preset-format.md) §8) |
| `rig_status` | — | mode, lock, take in progress, preset, engine, audio, MIDI, card |
| `diag_report` | `tail?` | the last diagnostic package ([`diagnostics.md`](diagnostics.md)): `report.json` and the tail of `timeline.ndjson`, already scrubbed. **Admin only** (`ADMIN_TOOLS`): the rack's main device |

`rig_status` is **filtered**: no roster, no first names, no space identifier. The mode says what it
allows, never for whom ([`identity.md`](identity.md)). `test_rig_status_ne_dit_jamais_QUI_joue` keeps it
true.

A `model` that does not exist in the pack falls back to `models[0]`. To test that `model` is honoured, pin a
model that is **not** `models[0]`: comparing "first model" with "no model" proves nothing, both return the
same file.

## 4. Reachability and authentication

- **Development and diagnosis only.** Locally: `http://127.0.0.1:8770/mcp`. On a shared LAN: the rack's
  address, same port.
- **Never a production channel.** A rack lives behind its owner's router; the rack pushes, the cloud never
  comes in ([`identity.md`](identity.md)). If golem.fm needs more state from a remote rack, it goes into
  the heartbeat or a job that answers.
- **Auth** is the bridge's (`bridge/auth.py`): localhost is trusted; a remote caller presents a device
  token in `X-Golem-Token`. Every tool reads, so a lost token cannot break anything; `diag_report` also
  requires the admin device (`auth.request_is_admin`).

## 5. Transport

JSON-RPC 2.0 on `POST /mcp` (MCP "streamable HTTP", protocol `2025-06-18`, `mcp.PROTOCOL`), written by
hand: the `mcp` SDK would add a dependency tree to a rack that must start offline, for three methods
(`initialize`, `tools/list`, `tools/call`).

- One request object per call: batches were removed in this protocol revision; an array gets
  `INVALID_REQUEST`.
- A notification (no `id`) gets `202` and an empty body.
- `GET /mcp` does not stream: it describes the server (tools, transport, "writes: never — use the job
  queue") instead of a bare 405.
- Results are returned twice, as `content` (JSON text) and `structuredContent`. A tool that raises returns an error; the session survives.

```bash
curl -s -X POST localhost:8770/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"resolve","arguments":{"ref":"t3k:44209"}}}'
```

```json
{"found": true, "ref": "t3k:44209", "file": "assets/models/…/amp-…-a2.nam", "exists": true, "why": null}
```

## 6. Abnormal pass history

`.rig-check.json` only keeps the **last** pass, and its value lies in the passes that are not clean —
which the next compile erases. The bridge therefore archives the **last 20 abnormal passes**
(`presets/.rig-check.history.json`, `monitors.RIG_CHECK_HIST`, timestamped, with the preset). Clean
passes are not stacked: they say nothing the current state does not, and would push the useful entries
out of the log.

## 7. `warnings[]` in the `patch-try` ack

The `patch-try` ack carries `warnings[]` (`tones_jobs`):

- **Stacked cabinet** (`rig.stacked_cab`): an `amp` or `amp-nam` block whose capture is declared
  `gear: amp-cab` (it already carries its cabinet), followed by a `cab` block, stacks two cabinets.
  Reported, never removed — it may be intended. A bypassed block is ignored: it loads nothing.
  This check reads the catalog `gear`, which comes from the capture author's declaration: two `.nam`
  files cannot be told apart by content, so if the declaration is wrong, the check is silent.
- **Silent scenes** (`rig.silent_scenes`): a scene in which a lane produces no sound.

Five block types carry a capture file — `amp` (full rig), `amp-nam` (head only), `pedal-nam`,
`preamp-nam`, `comp-nam` — plus `cab` (IR): `rig.CAPTURE_EXT` on the engine side, `MODEL_GEARS` in
`app/designer-model.js`. Forgetting `amp` in such a table is the classic mistake: it is the block that goes
most silent when its capture is wrong.
