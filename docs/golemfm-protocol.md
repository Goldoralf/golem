# The rack ↔ golem.fm protocol (rack side)

> **Status: REFERENCE** — describes what the rack code does. It is the single description of the contract
> on the rack side. When this file and the code disagree, the code is right and this file is a bug.
> `tests/test_golemfm_protocol_doc.py` fails when an action of `bridge/tones_jobs._HANDLERS` or an `/api/ext/…`
> path used in `bridge/*.py` is missing from §3 / §4.

golem.fm (formerly "Maestrium") is a closed-source web service. This document only says what the **rack**
sends, expects and does. It never describes how golem.fm works inside. Hosts are written `https://golem.fm`
or `<server>`.

## 0. Principles

- **Outbound only.** The rack is always the client: HTTP(S) requests and one WebSocket it opens itself
  (§6). golem.fm never connects to the rack. Work golem.fm wants done on the rack is put in a **job queue**
  that the rack pulls (§3).
- **Cache-first.** Everything the rack plays lives on its disk (`assets/backing/`, `songs/`,
  `library/…`, `config/.band.json`…). golem.fm unreachable = nothing stops playing; only *new* content and
  re-syncs need the server. Every pull writes atomically (tmp + rename) and an invalid answer never
  overwrites a valid local copy.
- **Configuration** — `config/integrations.json`, key `"golemfm"`:

  | Key | Meaning |
  |---|---|
  | `base_url` | the ACTIVE server: always env `GOLEM_SERVER_URL` (`.env`), default `https://golem.fm` (`routes_content.server_url`). A saved value that differs is switched on read; the screen cannot change it (2026-10-31) |
  | `token` | the device token of the active server (from pairing, §1). Default: env `GOLEMFM_TOKEN` |
  | `servers` | `{url: {label, token}}` — one token PER server. Changing `GOLEM_SERVER_URL` (`routes_content.switch_server`) parks the old token under its server and brings back the new server's own token: a token is never presented to another server |
  | `auto_push` | push every backup to the vault (`POST /api/ext/backups`) — default `false` |
  | `connect_presence` | "Let golem.fm find this rack" (§4, presence) — absent = `true` |

  `POST /api/integrations` refuses any `base_url` other than the configured server (400). A server that is not
  `https://` is refused, except `http://` to `localhost`, `*.local`, loopback or private IPs
  (`routes_content.server_url_ok`): all modules read the pair `(base_url, token)` through `golemfm._cfg()`, which
  applies that rule to what it READS (env `GOLEM_SERVER_URL`, a hand-edited `integrations.json`): a refused server gives `("", "")` — "not configured",
  logged once, and `golemfm.status()` carries the reason in `error`.
- **Authentication.** Every `/api/ext/…` call except `pair/start` and `pair/poll` carries
  `Authorization: Bearer <device token>`. No base URL or no token = "not paired": every caller returns
  quietly (`(0, "not paired")`), no request leaves.
- **Status convention.** The HTTP helpers (`golemfm._req`, `tones_sync._req`, `golemfm.put_bytes`) never
  raise. They return `(status, data)`: `200..` + parsed JSON; an HTTP error + its message as a string, read by
  ONE helper (`golemfm.error_text`): `detail` as a string, as an object (`message`, else `error`, else `code`;
  the code is kept in parentheses beside a message), or as a 422 list (`msg` fields joined), then root
  `error` / `message`; **`0` + message = unreachable** (DNS, refused,
  timeout). Callers treat `0` as "offline, try later", `404` as "this golem.fm does not serve this yet"
  (logged once, never fatal), other `4xx` as a refusal to show.
- **What the rack never sends.** Tokens of other services (TONE3000, paid separation services); guest
  names (an input played by a guest goes out as `{"person": null, "guest": true}`); MAC addresses,
  DHCP leases, Wi-Fi passwords; the raw `/etc/machine-id` (only a salted hash, `rack_id`); a **lent**
  sound (packs and blobs lent by a band mate are filtered out of every upload, `loans.filter_packs`,
  `loans.lent_deps`); a **songs** backup (`backup.vault_refusal`); and in diagnostic reports anything
  outside the whitelist `diag.WHITELIST` (types and short hashes, never names — `docs/diagnostics.md`).
  Reports only leave when the "send usage and bug reports" box is ticked (`diag.auto()`).

## 1. Pairing (device-code flow)

| Step | Call | Rack behaviour |
|---|---|---|
| start | `POST /api/ext/pair/start` `{device_name, rack}` (no token) | `rack` = `rigstatus.rack_identity()`: `version, profile, installed_at, installer, catalog_version, classifier_version, rack_id, arch, cpu, cores, ram_mb, disk_gb, hostname, board`. Expects `{code, poll_token, approve_url?, expires_in?}`; the code and a QR to `approve_url` are shown |
| poll | `POST /api/ext/pair/poll` `{poll_token}` (no token), driven by the UI every ~2 s | `200 {status:"approved", token, serial?}` → token saved (active + under its server in `servers`), `serial` recorded (§2); **any 4xx closes the request** (`409` = "already claimed", other 4xx = "expired"); `5xx` or `0` → still pending (`unreachable: true` when 0) |

Only one pairing request runs at a time. Health probe used by Settings: `GET /api/health` (no token),
then `GET /api/ext/songs` with the token (`200` = authenticated).

## 2. Heartbeat

`PUT /api/ext/rig/status`, JSON body = `rigstatus.light()`. Sent by `rigstatus.start_pusher`: first 15 s
after boot (that first one carries the mode table), then every **300 s**; plus debounced out-of-cadence
pushes (`push_soon`, 2 s) after a retag, a take, a preset change, a mode or recorder save, a remote
patch of a card. Each periodic tick then flushes pending diagnostic reports and runs the roster sync (§5).

Every field (any probe that fails is simply absent — the push still leaves):

| Field | Meaning |
|---|---|
| `firmware` | golem version (`git describe`) |
| `reaper` | REAPER version |
| `disk` | free / used disk |
| `at` | UTC ISO-8601 time of the snapshot |
| `rack_id` | stable salted hash of the machine id (`connect.rack_id`) — the key of the life-long serial |
| `machine` | `{arch, cpu, cores, ram_mb, disk_gb, hostname, board}` (`serial.machine`) |
| `modes`, `modes_ctx` | **only with `with_modes`** (boot, mode/recorder save): the mode table and its context `{recorder, click, vocab, spaces, cards, foot_lists, modes_version}` |
| `pending_takes`, `pending_total`, `pending_bytes` | takes not yet uploaded (`takes.pending`), with their upload progress |
| `mode`, `locked`, `recording` | active mode id, is its UI locked, is a take recording |
| `preset_id`, `preset_name`, `scene` | what plays now (`patch:<id>` for a patch, `sandbox-try` for a trial) |
| `foot` | the foot list the mode wanted to set and why it is not there (absent if the mode declares none) |
| `inputs` | `{card, mode, entries[{slot, kind, role, name, device?, person, guest?}]}` — active card only |
| `cards`, `patch_version` | every card that matters (declared by a mode, active, plugged) with inputs, outputs, MIDI roles; `patch_version` = short hash of `cards` |
| `setlist` | `{active, pending[]}` — the setlist really under the feet, and pushes waiting for the mode to change |
| `catalog_version` | integer of `library/catalog/effects.json` (the catalogue itself never rides the heartbeat) |
| `classifier_version` | version of `tools/classify.py` |
| `captures` | installed captures `[{ref, type: nam|ir, family, name, gear, models, echo?}]`, max 500 (`rigstatus.captures`). One row per tone of the local catalogue with **at least one file on disk**; `ref` = the **catalog id** a block carries in `ref` (never the pack uid `t3k:<id>`); `type` = `ir` when `gear` is `cab`, else `nam`; `family` = `guitar`/`bass`; `models` = number of files actually present. `[]` means "this rack has no capture at all"; an absent field means "not reported" |
| `keys_instruments` | factory keys instruments `[{type, name, engine, factory, count, items[], sounds?}]` |
| `drum_kits` | `[{id, name, engine, playable}]`; `playable` = the kit's engine can be mounted on a lane (`avldrums`, `drumgizmo`) — only those are valid values of a `drumkit` block's `kit` (`rigstatus.drum_kits`) |
| `engine` | what the audio engine really opened (`rigstatus.engine_doc`), or `null`. Linux: `{mode: "ALSA", device, samplerate: null, bsize, latency_ms, latency_source}`. Windows/macOS (from REAPER): `{mode, device, samplerate, bsize, inputs, outputs, input_names[], output_names[], latency_ms, latency_source}` |
| `health` | `{cpu_pct, ram_used_pct, ram_total_mb, temp_c, xruns_total}` |
| `controllers` | MIDI controllers, pedalboard, MIDI pedals `[{id, name, kind, usb, calibrated, connected, active, where, role}]` (max 24) |
| `caps` | `{os, engine, engine_version, inventory, inventory_at, unavailable[], quarantine[], nam_unreadable, compo_bed, separation?}` (`blockstatus.caps`) |

**Response fields the rack reads** (`rigstatus.push`): `serial` → `serial.record` (written once to
`config/serial.json`, read-only; a different number is kept aside as a conflict; a non-production server
only gives a *provisional* number, `serial.is_prod`), and `genres_version` → if newer than the local
taxonomy, `GET /api/ext/genres` (§5). Nothing else in the answer is read. **`catalog_version` does not
trigger anything on the rack**: the full catalogue only leaves when golem.fm queues a `push-catalog` job (§3);
the rack never decides to send it.
The same goes for `modes_version` / `patch_version`: they let golem.fm skip unchanged data.

The on-demand job `rig-status` returns `rigstatus.full()` = `light()` + `cpu_pct`, `temp_c`, `ram`.

## 3. Job queue

**Pull.** `GET /api/ext/tones/jobs?wait=50` — a **long-poll**: the rack asks golem.fm to hold the request
up to 50 s (`_LONG_POLL`) until a job exists; client timeout = `wait + 15` s. `tones_jobs.start_poller`
loops forever: not paired → sleep 30 s; answer with jobs, or an answer that really blocked ≥ 30 s → poll
again at once; immediate empty answer (a server without `wait`) → back-off 3 s × 1.6 up to 300 s. A plain
`GET /api/ext/tones/jobs` (no `wait`) is also issued at the start of every tones sync and by the local
`POST /api/tones-jobs/run`. One pull at a time (`_lock`).

**Envelope.** Answer `{"jobs": [...]}`. Each job is **flat**: `{id, device, action, created_at, …payload,
_job?, space?}` — the payload keys sit beside the envelope keys (`JOB_ENVELOPE`). The job id used for
ack/progress is `_job` when present, else `id` (`job_id()`): a payload that carries its own `id`
overwrites the envelope's, so golem.fm must send `_job` for such actions.

**Two lanes, chosen by NAME PREFIX.**

> **An action whose name starts with `take-`, `setlist-` or `push-catalog` runs on the `sync` lane;
> EVERY other action — including unknown ones — runs on the `rig` lane** (`tones_jobs.lane_of`,
> `_SYNC_PREFIXES`). Naming a new action chooses its lane. `sync` = network only, never REAPER;
> `rig` = everything that installs, mounts or sounds, strictly one at a time, FIFO (a `patch-try` must wait
> for the `preset-install` before it).

Exception: `reamp` never enters a lane on arrival; it waits in `reamp`'s own queue until the rack is
idle, then is put on the `rig` lane.

**In flight.** golem.fm re-offers a job until it is acked; the rack remembers job ids in `_inflight` and
never starts the same job twice.

**Ack.** `POST /api/ext/tones/jobs/{job}/ack`, exactly once per job:
- success: `{"ok": true}` plus `"result": {…}` when the handler returns an object (its internal `_log`
  key removed); handlers that return a sentence ack `{"ok": true}` only;
- failure: `{"ok": false, "error": "<message, ≤ 500 chars, English>"}`. **A failed job is never retried**
  by the rack: the error ack closes it. An unknown action is acked `{"ok": false, "error": "unknown action '<x>'"}`.
- `song-separate` errors are **codes**, not sentences: `engine_changed | no_engine | engine_failed |
  source_unreadable | upload_failed | cancelled` (`separation.ERROR_CODES`).

**Deferred acks.** `song-separate` and `plugin-recipe` return `ASYNC_ACK`: the job stays in flight and is
acked later by its own worker (`separation._ack`, `plugin_recipes._start_verify`). `reamp`, when the rack
becomes busy again, is **not acked** (`reamp.Deferred`) and goes back to the head of its queue.

**Progress.** `POST /api/ext/tones/jobs/{job}/progress` `{scene, clip: {sha256, duration}}` — sent per
rendered scene by `generate-preview` and `patch-preview` (best effort; the endpoint is optional).

**Busy rack.** Refusals are error acks that say why, in English: a locked mode (`rack is in … mode — …
refused`), a take recording, the target preset playing, the Gig mode (previews), a song playing (`mode-set`
on the active mode). `setlist-push` received in a locked mode is *deferred*, not refused (applied at the
next mode change, visible in the heartbeat's `setlist.pending`). The uploader, separation, reamp and
recipe verification wait for an idle rack before taking CPU or the engine.

**Blobs.** Actions with a `sha` (or `blob.sha256`) download `GET /api/ext/tones/assets/{sha}` first. The sha
must be 64 hex chars and every file a pack places must stay under `assets/` — otherwise error, before
any network or disk write.

### All actions (`bridge/tones_jobs._HANDLERS`)

| Action | Lane | Payload (keys) | Effect on the rack | Ack `result` | Handler |
|---|---|---|---|---|---|
| `install` | rig | `uid` | reads `GET /api/ext/tones/manifest?trashed=1` (own packs, then `lent[]`), downloads every asset to its `extra.rel` (else `assets/<models\|irs>/golemfm/…`), upserts the tone catalogue; `groove` packs go to `library/grooves/`; `synth/kit/loop/sample` only place files | — | `_install` |
| `block-status` | rig | `sha`+`role` (patch document) or `preset` | computes each block's state (ready, to download, unavailable, empty); installs nothing | `preset_status` (an `unavailable` block carries `alternatives[]`, [block-status.md](block-status.md) §6) + `caps` + `suggested` | `_block_status` |
| `remove` | rig | `uid` | refuses if a preset/template uses the tone; else moves it to `assets/.trash/`; absent = ok | — | `_remove` |
| `recall` | rig | `preset`, `scene?` | recalls the preset (same path as the screen) | — | `_recall` |
| `fetch-backup` | rig | `backup_id` | downloads a vault zip into `backups/` (restoring stays a gesture on the rack) | — | `_fetch_backup` |
| `t3k-install` | rig | `tone_id` | installs a TONE3000 tone with the RACK's own TONE3000 account | — | `_t3k_install` |
| `push-library` | rig | — | starts a full tones sync; acked at START (already running = ok) | — | `_push_library` |
| `push-catalog` | sync | — | `PUT /api/ext/rig/catalog` with `rigstatus.catalog()` (gear, block types, params, quarantine); keys starting with `_` are dropped; `blocks[].quarantine` travels **as-is** — the reason string, or `false` — never coerced to a boolean | `catalog_version, gear, blocks, server` (`server` = golem.fm's own answer) | `_push_catalog` |
| `preset-install` | rig | `sha`, `name?`, `preset_id?` | blob = export envelope `{schema_version, preset}` or bare preset; migrated, checked (unique block and branch ids), written `origin: golem.fm`; replaces only a golem.fm-origin preset with the same id, else suffix `-2`; **never recalled** | `preset_id, unresolved[]` | `_preset_install` |
| `patch-install` | rig | `sha`, `role?`, `patch_id?`, `name?`, `saved_at?`, `rev?`, `draft?` | patch document → `library/patches/`; missing captures matched or installed; patch catalogue pushed back | `patch_id, matched, suggested, installed, install_failed` | `_patch_install` |
| `patch-push` | rig | as `patch-install` | alias of `patch-install` | as `patch-install` | `_patch_install` |
| `patch-try` | rig | `sha`, `role` | builds a one-lane trial preset and RECALLS it as `sandbox-try` (previous edit buffer kept in `.sandbox.prev.json`); acked after the audition | `ok, lane, input, unresolved, dropped, warnings, matched, suggested, installed, install_failed, scene_orphans, doc` | `_patch_try` |
| `patch-preview` | rig | `sha`, `role`, `patch_id`, `ref?` | renders the reference DI through each scene of a temporary preset, uploads one clip per scene (`POST /api/ext/tones/assets`), sends progress, deletes the temporary preset | `patch_id, di, di_name, instrument, fingerprint, scenes{id:{sha256,duration}}, missing, matched, installed, suggested` | `_patch_preview` |
| `patch-delete` | rig | `patch_id` | deletes the patch file (lanes keep their inline copy), pushes the patch catalogue; absent = ok | `patch_id, deleted` | `_patch_delete` |
| `preset-delete` | rig | `preset_id` | deletes the preset (bank slots freed); refused if it is playing | `preset_id, deleted, banks_freed, …` | `_preset_delete` |
| `generate-preview` | rig | `preset`, `in_key?`, `ref?` | renders the preset's demo per scene, uploads clips, sends progress | `preset, preview{ref, di_name, in_key, instrument, fingerprint, scenes}` | `_generate_preview` |
| `reamp` | rig (held until idle) | `reamp` (id), `preset`, `scene?`, `preset_lane?`, `role?`, `uid?`, `di?`, `result{declare, complete}?` | renders a take's DI through a lane offline, uploads it (`/api/ext/recordings/reamps/{id}/…`); already done/failed on golem.fm = no-op | `preset, scene, lane, filename, sha256, size_bytes, track, recording` (or `status`) | `_reamp` → `reamp.run` |
| `set-appearance` | rig | `preset` (or `patch:<id>`), `colors?`, `anims?` | replaces the Live grid colours/animations; no engine rebuild | — | `_set_appearance` |
| `kit-install` | rig | `sha`, `name?` | imports a `.golemkit`; a drum-kit *card* (JSON without samples) is not installed | `kit{id}` (+ `card, installed, why`) | `_kit_install` |
| `groove-install` | rig | `sha`, `name` | saves one GM `.mid` groove | `groove{id}` | `_groove_install` |
| `groove-pack` | rig | `sha`, `name?` | imports a `.groovepack` zip (`pack.json` + `grooves/*.mid`), partial tolerated | `name, grooves[], skipped[], song?` | `_groove_pack` |
| `sample-pack` | rig | `sha`, `name?` | imports a samples zip and its ordered sample set | `name, samples[], skipped[], slug?` | `_sample_pack` |
| `rig-status` | rig | — | — | `rigstatus.full()` | `_rig_status` |
| `inputmap-set` | rig | `card`, `entries[{slot, role?, nth?, person?}]`, `outputs[{slot, role?, person?, type?}]`, `pairs[]` | writes a card's patch, all-or-nothing; refused on the active card during a take, a song or a locked mode | `card, applied, cards, patch_version` | `_inputmap_set` |
| `mode-set` | rig | `mode`, `space?`, mode fields (`name, icon, desc, services, inputs_off, card, band, click_mode, live_view`…) | edits a mode, all-or-nothing, same validation as the rack sheet; some fields never remote (`modes.NEVER_REMOTE`) | `mode, modes, modes_version` | `_mode_set` |
| `recorder-set` | rig | `in<N>?`, `usb?`, `mode?`, `mix?`, `transcribe?`, `count_in?` | global recorder config; any other key refused; refused during a take | `recorder, modes_version` | `_recorder_set` |
| `diagnostic-report` | rig | `detail?` | builds and sends an `event` report, then acks; refused if reports are disabled | `report_id, sha256, size` | `_diagnostic_report` |
| `setlist-push` | sync | `setlist{id, name, rev, fcb, complete, lines[]}` — or `setlist{id, name?, fcb?, presets[]}` without `lines` | merges by id/rev; `complete` removes; deferred in a locked mode; lines kept by the rack are pushed back. Without `lines`, on an EXISTING list, `presets[]` is applied as the rack's own reorder (`set_presets`: each line follows its preset, the list rev is bumped) | `added, updated, removed, resend, deferred?, …` | `_setlist_push` |
| `song-push` | rig | `songs[{id, rev, title, artist, kind, song_slug?, sheet}]`, `band?`, `complete?` | merges repertoire entries of one space | `added, updated, removed, resend` | `_song_push` |
| `song-install` | rig | `id`, `slug`, `url` (the `…/golem` base: the rack derives `…/golem/plan` from it), `etag`, `category?` (`song`\|`vocals`\|`standard`) | downloads a `.golem` (plan first, §5), verifies it carries the announced `id`, merges it; `standard` goes to the standards shelf | `song{id}, missing[]` or `standard{slug}, missing[]` | `_song_install` → `golem_pull.song_install` |
| `golem-upload` | rig | `id`, `mode?` (`full`\|`light`), `url?` | sends the outbound copy of a `.golem` to `url` (default `POST /api/ext/golem?mode=…`) | `ok, kind, slug, golem_etag` | `_golem_upload` → `inventory.golem_upload_job` |
| `song-separate` | rig (ack deferred) | `source_url`, `upload_url`, `stems_wanted?` | separates the song with the active engine when idle; one multipart POST per stem to `upload_url` (both must be paths on the paired server) | `stems[], silent[]` | `separation.on_job` |
| `plugin-recipe` | rig (ack deferred) | `request_id`, `plugin`, `sha` | downloads an AI draft recipe and verifies it by measure when idle | the verification object | `plugin_recipes.on_job` |
| `card-setup-offer` | rig | `offer_id, from_rack, from_name, offered_at, usb, serial, card, os, fingerprint, setup` | stores another rack's card setup as an offer; **never applied by itself** | `status: "shown"` | `card_setups.on_job` |
| `take-tag` | sync | `takes[{uid, band\|null}]` | retags takes (partial tolerated), then a heartbeat | `tagged[], skipped[]` | `_take_tag` |
| `upload-di` | rig | `uid`, `band?` | uploads the DI tracks of ONE take, even one already uploaded: reopens it with no track to read what it has, then declares only the DI files under free `idx` (a DI already declared keeps its idx and resumes), sends them, seals. State in the take manifest `upload_di {state, pct, code?}`; never while playing | `queued[uid]` (error if the take is unknown) | `_upload_di` → `uploader.queue_di` / `upload_di` |
| `take-upload` | sync | `takes?[uid]` (absent = all tagged), `kinds?` | queues uploads (§4 recordings); progress in `pending_takes[].upload` | `queued[], skipped[]` | `_take_upload` |
| `take-cut` | sync | `takes?[uid]` | queues cut + upload of long takes | `queued[], …` | `_take_cut` |
| `take-recut` | sync | `parent`, `bounds[{offset_sec, duration_sec}]` | re-cuts a take from its kept source | `ok, uids[], removed[], skipped[]` | `_take_recut` |
| `take-source-release` | sync | `takes[uid]` | deletes the full source of already-cut takes | `released[], skipped[], freed_bytes` | `_take_source_release` |
| `anim-pack-install` | rig | `pack_id`, `version` | `GET /api/ext/anim-packs/{id}` → `{pack, css}` → validated install | `pack{id, effects}, warnings[]` | `_anim_pack_install` |
| `anim-pack-remove` | rig | `pack_id` | removes a pack (`default` refused) | `pack{id}` | `_anim_pack_remove` |

### Patch documents received (`patch-install`, `patch-push`, `patch-try`, `patch-preview`)

Read by `tones_jobs._patch_doc`; every refusal is an error ack with the reason, nothing written.

- **Shape.** `role` (job or document) is required and must be one of `tones_jobs.ROLES`. The chain is
  `{pre, split, post}` or a flat `{chain: […]}`; a document with no block is refused. A v2 patch
  (`lanes_v: 2` + `lanes[]`, `patches.is_v2`) must hold **one** lane of the patch's role; `lanes[0].chain`
  is the truth, and a top-level `chain` mirror that differs from it is refused. Duplicate block ids are
  refused (`duplicate block ids: …`).
- **Deduced on reception, never rewriting a given value** (`patches.normalize_patch`): a split without
  `mode` becomes `merge` if there is a `post`, else `fanout`; scenes without `id` get `A`, `B`… by position;
  blocks without `id` get `<type>-<n>` (first free `n`, `patches.assign_block_ids`).
- **Scene keys that name nothing** (neither a block id nor a block type present in the chain) are
  reported in `scene_orphans[{scene, key, where}]` and **never repaired**: no rule may guess which block
  a key meant (`patches.orphan_scene_keys`).
- **Captures** (`tones_jobs._settle_captures`): a `ref` absent on this rack is installed **before** the
  audition — from golem.fm (own packs, then lent ones), else with the rack's TONE3000 account
  (`installed[]`, `install_failed[{block, uid, why}]`). Inline installs are bounded: a pack over 48 MB or
  a total over 90 s fails with "push an `install {uid}` job first". A capture block **without** `ref` gets
  nothing: the name match is only a proposal in `suggested[]` (`blockstatus.suggestion`), never written
  into the document. `matched[]` is always empty.
- **`patch-install`** never refuses or edits a block for a missing capture: the stored patch is a
  recipe; replaces only a golem.fm-origin patch with the same id, else suffix `-2`.
- **`patch-try`** refuses, in this order: a locked mode (`rack is in <mode> mode — try later`), a take
  recording (`a take is recording — try after it`), a document error (above), no input of the role on
  the card (`no <role> input on « <card> » — …`, `patches.bind_input`), then a dry-run compile (`recall.check_preset`, e.g. a quarantined block). These refusals leave
  the edit buffer and the previous draft untouched (a capture installed before the compile refusal
  stays installed). Otherwise the previous buffer is copied to
  `presets/.sandbox.prev.json`, the trial is written and recalled as `sandbox-try`, and the ack comes
  **after** the recall (`ok: true` = it is playing); a failing recall at that point acks an error with
  the buffer already replaced.
  Ack fields: `lane` (`<role>-try`), `input` (the physical input chosen); `unresolved[{block, type, ref,
  label, why}]` with `why` ∈ `"not installed on this rack"`, `"no capture referenced"`, or the wrong-kind
  reason of `rig._wrong_kind`; `dropped[]` = capture blocks without `ref`, kept in the document but not
  mounted (`rig._drop_empty_capture`); `warnings[]` (a cab block after an amp-cab capture, silent
  scenes); and `doc`, exactly one of `"saved <saved_at> rev <rev>"`, `"draft (never saved)"`,
  `"undated (job emitted before 2026-09-11)"`, built from the job's `saved_at` / `rev` / `draft`
  (`tones_jobs._origin_of`). `ok` with empty `unresolved` and `dropped` means everything the patch names
  was found and placed — not that sound comes out.

## 4. Rack → cloud HTTP calls

Every `/api/ext/…` path the bridge uses (placeholders in braces; query strings shown in the Method column).
All carry the Bearer token except the two pairing calls.

| Path | Method | Module:function | Purpose |
|---|---|---|---|
| `/api/ext/pair/start` | POST | golemfm:pair_start | start pairing (§1) |
| `/api/ext/pair/poll` | POST | golemfm:pair_status | poll pairing (§1) |
| `/api/ext/rig/status` | PUT | rigstatus:push | heartbeat (§2) |
| `/api/ext/rig/catalog` | PUT | tones_jobs:_push_catalog | full gear/block catalogue, on `push-catalog` |
| `/api/ext/serial` | GET | serial:fetch | re-read the life-long serial (404 = none yet) |
| `/api/ext/t3k/relay` | POST `{challenge}` | routes_t3k:t3k_auth_start | TONE3000 sign-in through golem.fm's TONE3000 app (2026-10-22): the rack sends its PKCE challenge (S256), gets `{state, authorize_url, client_id, redirect_uri, expires_in}`; the phone signs in on `authorize_url`, TONE3000 returns to golem.fm. No key or return address to declare on the rack |
| `/api/ext/t3k/relay/{state}` | GET | routes_t3k:_relay_poll | every 2 s, 10 min at most: `202 pending`, then once `200 {status: ready, code, client_id, redirect_uri}` or `{status: denied}`; `410` expired. The RACK exchanges the code with its verifier and the returned `client_id`/`redirect_uri`, and keeps that `client_id` (`T3K_TOKEN_CLIENT`) for the lineage's refreshes — golem.fm never sees a token. A golem without golem.fm uses its own key (Settings ▸ Connect ▸ TONE3000 ▸ Advanced). **Measured 2026-10-22** (golem.fm dev, the maintainer's account): golem.fm's lineage and the rack's, same account and same `client_id`, live side by side — each refreshes without revoking the other, in both orders. Only sharing ONE lineage between two machines is forbidden |
| `/api/ext/assistant/ask` | POST | assistant:_post | « Ask golem » — one question, the Health facts (scrubbed), verdicts, the machine's action registry; answer `{answer, cites, propose?}` revalidated on the rack; needs the scope `assistant:ask` (a token paired before it gets `403` → re-pair); refusals `402 plan_required` · `429 ai_quota` / `rate_limited` · `502 ai_failed` · `503 ai_off`, body `{detail: {error, message, …}}` ([assistant.md](assistant.md) §5–§8) |
| `/api/ext/tones/jobs` | GET `?wait=` | tones_jobs:process | job queue long-poll (§3) |
| `/api/ext/tones/jobs/{job}/ack` | POST | tones_jobs:_run_one, separation:_ack, plugin_recipes:_start_verify | job ack (§3) |
| `/api/ext/tones/jobs/{job}/progress` | POST | tones_jobs:_generate_preview, _patch_preview | per-scene progress |
| `/api/ext/tones/manifest` | GET (`?trashed=1` for install) | tones_sync:_worker, publish_preset; tones_jobs:_install, _manifest_tones | packs golem.fm holds, `missing_blobs[]`, `lent[]`, `rev`, `bytes` |
| `/api/ext/tones/packs/{uid}` | PUT | tones_sync:_worker | one pack document (only those whose hash changed) |
| `/api/ext/tones/assets` | POST `?sha256=&filename=` (raw body) | tones_sync:_worker, publish_preset; preview:push_clip | upload a blob (507 = skipped, retried at next sync) |
| `/api/ext/tones/assets/{sha}` | GET | tones_jobs:_download_raw | download a blob by sha256 |
| `/api/ext/tones/rig-manifest` | PUT | tones_sync:_worker | `{device, at, packs[], blobs_bytes}` — what is installed |
| `/api/ext/golem/state` | PUT | tones_sync:_worker | read-only snapshot `{device, presets[], setlists[]}` |
| `/api/ext/golem/presets` | POST | tones_sync:publish_preset | `{presets: [export envelope]}` (§7) |
| `/api/ext/golem/patches` | POST | golemfm:push_patches | `{patches[], complete: true}` — whole patch catalogue, debounced 5 s |
| `/api/ext/golem/setlists` | POST | golemfm:push_setlist | `{setlist: {…, complete: true, scopes: {}}}`, debounced; songs it cites go first |
| `/api/ext/golem/songs` | POST | golemfm:push_songs_now | `{songs[]}` pending repertoire entries; answer `{applied, rejected}` |
| `/api/ext/song-links` | POST | golemfm:push_song_links | `{links[{slug, preset_id, preset_name}]}` — full replacement |
| `/api/ext/practice` | POST | golemfm:post_practice | `{slug, played_ms}` after a play session |
| `/api/ext/songs` | GET (`?tagged=1` for the screen catalogue) | golemfm:catalog, status; golem_pull:refresh_all | song cards (`slug, title, artist, album, bars_rev?, golem_etag?…`) |
| `/api/ext/songs/{slug}` | GET | golemfm:_dl_worker, asset | one song's stems and artwork paths |
| `/api/ext/files/{path}` | GET | golemfm:_dl_worker, asset | download a stem / cover / photo |
| `/api/ext/compo/beds/{path}` | GET | compo_bed:_download | the bed of an armed take, `<band public_id>/<sha256>.flac` (`docs/compo.md` §12) |
| `/api/ext/artists/photo` | GET `?name=&title=` | artist_photos:fetch | the artist photo for a library `.golem` without one, filed as `art/band.<ext>` (role `band`); `404 no_photo` = none, not asked again for 24 h |
| `/api/ext/albums/cover` | GET `?artist=&title=[&album=]` | artist_photos:fetch | the album cover for a library `.golem` without one, filed as `art/cover.<ext>` (role `cover`); `404 no_cover` = none, not asked again for 24 h |
| `/api/ext/songs/{slug}/bars` | GET | bars:fetch | bar map (404 = none; local copy removed) |
| `/api/ext/songs/{slug}/golem` | GET `?id=` | golem_pull:refresh_async, fetch_install | the `.golem` archive (streamed) |
| `/api/ext/songs/{slug}/golem/plan` | GET `?id=` | golem_pull:fetch_plan | member plan `{format:1, manifest, members[], etag}` — **the path golem.fm serves**; the rack's fallback to the archive row above on 404/405 is kept for older servers only |
| `/api/ext/songs/{slug}/recording` | GET | recording:of_song | `{isrc, mbid, lookup, links[]}` legal purchase links |
| `/api/ext/standards` | GET | golemfm:standards_catalog | standards golem.fm can serve, with `golem_etag` |
| `/api/ext/standards/{slug}/golem` | GET | golemfm:standards_import_golem | one standard as `.golem` |
| `/api/ext/standards/{slug}` | GET | golemfm:standards_import | legacy JSON form (fallback) |
| `/api/ext/karaoke/{id}` | GET | karaoke:fetch, _load | song info + stem URLs for a karaoke load |
| `/api/ext/band` | GET | golemfm:band_fetch (roster:sync) | all spaces and rosters of the token's owner |
| `/api/ext/genres` | GET | genres:sync | genre taxonomy |
| `/api/ext/keys` | GET | signatures:refresh_keys | public Ed25519 keys to verify signed originals |
| `/api/ext/anim-packs/{id}` | GET | tones_jobs:_anim_pack_install | `{pack, css}` |
| `/api/ext/backups` | POST `?filename=&kind=&sha256=` (zip body) / GET | golemfm:_push_worker / list_remote, pull_backup | vault upload / listing |
| `/api/ext/backups/{id}` | DELETE | golemfm:delete_remote | remove a vault backup |
| `/api/ext/backups/{id}/download` | GET | golemfm:pull_backup | download, sha256 checked |
| `/api/ext/diagnostics` | POST `?filename=&kind=&sha256=` (zip body) | diag:send | diagnostic report (§0) |
| `/api/ext/golem/connect/presence` | PUT / DELETE | connect:push_presence / withdraw | where to find the rack: `{session, rack_id, name, host, port, urls[≤6], ipv6_prefixes, wifi{ssid, ap, ap_ssid}, band, at}`; at +15 s, every 300 s, within 30 s of an address change; DELETE when the box is unticked |
| `/api/ext/golem/connect/redeem` | POST | connect:redeem | `{ticket}` → `{person?, screen?, kind?, client?}`; 404/410 = expired ticket |
| `/api/ext/golem/card-setups` | GET `?usb=&serial=` | card_setups:fetch | setups other racks published for this card (cached 60 s) |
| `/api/ext/golem/card-setups/offers` | POST | card_setups:offer | offer this card's setup to another rack (202 expected) |
| `/api/ext/golem/card-setups/offers/{offer_id}/reply` | POST | card_setups:reply | `{status: applied\|declined}` (410 = offer gone) |
| `/api/ext/golem/plugin-recipes` | GET `?plugin=&os=&version=` / POST | plugin_recipes:analyze / validate | shared recipe lookup / share a validated recipe |
| `/api/ext/golem/plugin-recipes/analyze` | POST | plugin_recipes:analyze | ask for an AI draft (202 `{request_id}`) |
| `/api/ext/golem/plugin-recipes/analyze/{request_id}` | GET | plugin_recipes:poll | status of a draft request |
| `/api/ext/golem/plugin-recipes/report` | POST | plugin_recipes:report | a shared recipe rejected by this rack's measures |
| `/api/ext/inventory` | PUT / PATCH | inventory:publish, _patch | cards of the `.golem` files held: full snapshot, then diffs `{upsert[], remove[]}` by batches of 500. A card's `category` is `song`, `standard`, `vocals` or `track`; refused as a whole (422) because of `track` cards, the send is redone without them |
| `/api/ext/quotas` | GET | inventory:quotas | `{section: {used, limit}}` shown before a "Store on golem.fm" |
| `/api/ext/golem` | POST `?mode=full\|light[&declared=1]` (zip body) | inventory:upload | store a `.golem` (a gesture, or the `golem-upload` job). `declared=1`: the user ticked, for this deposit, the declaration of lawful origin (terms §3.3) — sent by a batch store (separation-batch.md §7) |
| `/api/ext/recordings` | POST | uploader | declare a take `{uid, take, band, tracks}` — idempotent, returns per-track `received` (resume offset); 413 = refused (quota) |
| `/api/ext/recordings/{id}/tracks/{idx}` | PUT `?offset=` (raw bytes) | uploader (golemfm:put_bytes) | one chunk; 409 "expected offset N" = resume at N |
| `/api/ext/recordings/{id}/complete` | POST | uploader | seal the take |
| `/api/ext/recordings/reamps/{id}` | GET | reamp:remote_status | is this reamp already done/failed |
| `/api/ext/recordings/reamps/{id}/result` | POST | reamp:upload | declare the rendered file `{filename, sha256, size_bytes}` |
| `/api/ext/recordings/reamps/{id}/complete` | POST | reamp:upload | seal it |
| `/api/ext/separation-engines` | GET | separation:remote_list | separation engines golem.fm lists (cached 120 s) |
| `/api/ext/golem/link` | WebSocket | follow_uplink:run | live link (§6) |

Server-given URLs are also followed, never invented: a job's `url` / `source_url` / `upload_url`, a
reamp's `result.declare` / `result.complete` / `upload`. Job URLs must be **paths on the paired server**
(start with `/`) — anything else is refused (`golem_pull._download`, `inventory.upload`,
`separation._run_job`). A karaoke stem may be an absolute URL: the token is sent only if that URL starts
with the paired `base_url` (`karaoke._get_bytes`). A roster `avatar` is a server path (fetched with the
token) or an absolute URL (fetched without it, `roster.fetch_avatars`).

**Tone library sync** (`tones_sync._worker`, one at a time; manual or debounced after any write of the
catalogue, `schedule`, 20 s). It first runs the job queue, then: builds one pack per catalogue tone (+ Vital presets) —
lent packs filtered out — and `PUT`s only the packs whose document hash changed since the last push **to
this server**; `GET /api/ext/tones/manifest` and uploads the `missing_blobs[]` it has on disk (`507` =
quota, blob skipped and retried next sync; a `400` on `kit`/`loop`/`sample`/`groove` = server without
that kind, skipped without being marked pushed); `PUT /api/ext/tones/rig-manifest`; then, best effort,
`PUT /api/ext/golem/state`, the patch catalogue, and the preset catch-up below. The sync is a mirror in
one direction: **a pack deleted on the rack is never deleted on golem.fm**, it only leaves the
rig-manifest. A pack's `kind` is read from its files (`tones_sync.kind_of`: IR files → `cab`; `.nam`
files keep the declared `amp`/`amp-cab`/`pedal`/`outboard`, a declared `cab` of `.nam` files → `amp-cab`;
`experimental` only when the files say nothing); `family` (`guitar`/`bass`) is sent for
`amp`/`amp-cab`/`cab`/`pedal` (`tones_sync.family_of`). A plugin capture carries `provenance` +
`private: true` (`tones_sync._provenance`).

**Preset publication** (`tones_sync.publish_soon`). Every preset save schedules a publish (debounced
5 s per preset) that only leaves when the preset's sound fingerprint (`preset_export.fingerprint`, which
ignores `preview`, `colors`, `anims`) differs from the last one published **to this server**
(`library/catalog/.published.json`, keyed by server). A preset with an unresolved asset is skipped and
logged, never an error; each tones sync re-publishes whatever is behind (`publish_dirty`). `sandbox-try`,
`patch:<id>`, `karaoke` and presets using a lent sound are never published (`publish_preset`).

## 5. Cloud → rack pulls

The rack decides when to pull. Every pull is a GET of §4.

| What | When | Endpoint(s) | Lands in |
|---|---|---|---|
| Backing catalogue | Songs screen opened | `/api/ext/songs?tagged=1` (the starred subset), merged with the cache — un-starred but cached songs stay playable | memory |
| Backing stems | "Download" on a song | `/api/ext/songs/{slug}` then `/api/ext/files/{path}` per stem | `assets/backing/<slug>/` + `meta.json` (guitar muted by default) |
| Bar maps | catalogue read, when `bars_rev` changed | `/api/ext/songs/{slug}/bars` | `assets/backing/<slug>/bars.json` |
| `.golem` updates | each catalogue read, on the FULL list `/api/ext/songs`; only songs the rack already holds whose `golem_etag` differs from the last installed | `/api/ext/songs/{slug}/golem/plan?id=` (members fetched, sha256-checked, already-held members reused), else the archive | `songs/`; etags in `songs/.etag.json`, refused files remembered per etag |
| New songs | `song-install` job | job `url` (+ `/plan`) | `songs/` or standards shelf |
| Standards | Standards screen / sync | `/api/ext/standards`; only standards already on the rack whose `golem_etag` changed are re-fetched | `library/standards/golem/` |
| Karaoke | WS `karaoke-prefetch` / `karaoke-load` (§6) | `/api/ext/karaoke/{id}` + its stems | `assets/backing/k-<id>/` (50 songs max, least recently played evicted) |
| Band / roster | every heartbeat tick, at boot, before redeeming a connect ticket | `/api/ext/band` — only `bands[]`, `default`, `synced` are read; the current space is never switched by a sync | `config/.band.json`, avatars in `config/avatars/` |
| Genres | heartbeat answer `genres_version` > local | `/api/ext/genres` | remote taxonomy file (`genres.REMOTE_FILE`) |
| Tone packs | `install` job, patch captures, `t3k-install` | `/api/ext/tones/manifest?trashed=1`, `/api/ext/tones/assets/{sha}` | `assets/…`, `library/catalog/tones-index.json` |
| Animation packs | `anim-pack-install` job | `/api/ext/anim-packs/{id}` | animation packs store |
| Backups | `fetch-backup` job or Settings | `/api/ext/backups`, `/api/ext/backups/{id}/download` | `backups/` (restore stays manual) |
| Signing keys | verifying a signed original | `/api/ext/keys` | keys cache under `songs/` |
| Serial | Settings check / lost file | `/api/ext/serial` | `config/serial.json` (0444) |
| Card setups, recipes, separation engines | their screens | §4 rows | `config/.card-setups.json`, `config/plugin-recipes/`, separation config |

**Roster details** (`bridge/roster.py`). Of each person in `bands[].people[]` only `roster.PERSON_KEYS`
are kept (`id, name, roles, gear, rights, prefs, pending, avatar`). `avatar` absent or empty = no photo
(the initial is shown). A photo is downloaded **once per URL** (`config/avatars/index.json` remembers
the URL of each file): golem.fm must change the URL when the photo changes. Accepted: JPEG, PNG, WebP,
GIF, at most 2 MB, HTTP 200; anything else is ignored with a log line, never an error on screen
(`roster.fetch_avatars`). The screen serves the cached file (`GET /api/band/avatar/<id>`), offline.

## 6. The live link (WebSocket)

`wss://<server>/api/ext/golem/link` (`ws://` if `base_url` is `http://`), header
`Authorization: Bearer <token>` (scope `follow:push`). Opened at bridge start by `follow_uplink.run`;
ping 20 s; reconnect with back-off 1 → 10 s; the config is re-read every 5 s and a server/token change
closes and reopens the link. Close code **4401** = invalid/revoked token, **4403** = token without
`follow:push` (re-pair) — both logged by name.

**Rack → golem.fm frames**
- `{"type": "pos", "slug", "playing", "posMs", "seq"}` — the backing position (extrapolated while
  playing), ~4.5 Hz while playing (10 Hz during a karaoke), immediately on a transition, silent when
  stopped. `slug` is always the golem.fm slug, never a local song id. Optional: `src: "karaoke"`, `id`,
  `mix` (only when it changed) during a karaoke; `compo: {person, state, why?}` during a riff take.
- `{"type": "karaoke", "state", "id", "req"?, …}` — `state` ∈ `fetching` (with `done_mb`, `stems_done`),
  `cached`, `ready` (`rev, voice, mix, from_golem?, voice_input?, voice_src?, voice_why?`), `refused`
  (`why`), `stopped`, `ended` (`posMs` = length really played), `left` (a preset was recalled on the rack).
  `req` echoes the command's `req`.
- `{"type": "lyrics", "karaoke_id", "song_id", "rev", "format": "lrc", "text"}` — lyrics relayed when the
  karaoke plays a `.golem` of the rack (in transit only).

**golem.fm → rack frames.** Only `{"type": "cmd", "cmd": …}` is read; anything else is ignored. The
accepted commands, and nothing else:

| `cmd` | Fields | Effect |
|---|---|---|
| `compo-start`, `compo-stop` | `person` | start/stop a remote riff take (`compo.remote`) |
| `compo-target` | `person`, `target`, `clear?` | arm the rack on a piece for a person |
| `lyrics-get` | `karaoke_id?`, `song_id?` | resend lyrics of the CURRENT karaoke only |
| `karaoke-prefetch` | `karaoke{id, rev}`, `req?` | download only (own thread) |
| `karaoke-queue` | `items[{karaoke{id,rev}?, golem{id}?}]` (≤ 500), `pos`, `mix`, voice fields, `req?` | the evening's queue, full state; the rack advances on its own only while golem.fm is unreachable ([`karaoke.md`](karaoke.md) §3.1, lot 5) |
| `karaoke-load` | `karaoke{id, rev}` and/or `golem{id}`, `mix`, voice patch fields, `req?` | load stems + voice lane as the volatile `karaoke` preset; with `golem.id`, play the rack's own copy, no `rev`, nothing downloaded ([`karaoke.md`](karaoke.md) §3.1) |
| `karaoke-mix` | `mix`, `req?` | change the stem mix |
| `karaoke-stop` | `req?` | stop, recall the previous preset |
| `seek` | `posMs` | seek the backing |
| `play`, `pause`, `toggle` | — | transport |
| `loop` | `on`, `aMs`, `bMs` | A/B loop (`on` false or missing bounds = loop off) |

`play`, `toggle` and `seek` are ignored when no backing is loaded. Any other `karaoke-*` is ignored; any
other `cmd` does nothing. No command on this socket can install, delete, recall a preset or change a
setting: those go through jobs (§3).

## 7. Formats

- **`.golem`** (songs, standards, vocals): `docs/golem-format.md` (FIGÉ). The rack sends the *outbound*
  copy (`golemfile.outbound`, no repertoire, people or private captures), full or light
  (`golemfile.light_copy`).
- **Preset export envelope** (`preset_export.build_export`, `POST /api/ext/golem/presets`, and the blob of
  `preset-install`): `{schema_version: 1, catalog_version, preset, deps[], foot_context?, unresolved?}`.
  `deps[]` = `{sha256, uid, kind, bytes, name, source}` with `source` ∈ `"t3k"` (fetched by the installing
  rack from its own TONE3000 account) | `"golemfm"` (served by sha256 from golem.fm's blob store).
- **Tone packs**: uid `t3k:<id>` (from TONE3000) or `local:<id|slug>`; kinds `tones_sync.KINDS`
  (+ `sample`, `groove`); identity of a file = its sha256. The *nature* of an installed file is read from
  its extension, never taken from the declared `kind` (`_entry_from_pack`).
- **Takes** (`bridge/takes.py`, `bridge/uploader.py`, `bridge/takecut.py`):
  - **`take.json`**, written when a take stops (`monitors._take_manifest`), is a record of the take,
    never rewritten afterwards except `upload` (and `cut` / `source_released`): `kind` (take kind frozen at
    REC from the mode's `take_kind`: `rehearsal`, `gig`, legacy `show`; `riff` for a Riff capture), `mode`
    (`mix`/`tracks`/`tracks_di`), `sources`, `started_at` (the room's wall clock, naive ISO, never
    converted), `ended_at`, `started_epoch_ms` and `started_at_utc` (the absolute instant),
    `bwf_time_reference` (sample timestamp shared by every lane, read back from the BWF chunk) and
    `sample_rate`, `preset`, `preset_name`, `scene`, `bpm`, `flags[]` (set by a human), `marks[]` (set by
    the machine), `session`, `band` (frozen at the START of the take: `{id, name, source}` — only `id` is a
    key), `roles {"<input>": label}`, `people {"<input>": person id}` (parallel to `roles`, absent when
    nobody was assigned), `machine_mode` (the mode **id**, e.g. `studio`, never its label), `backing`,
    `standard {id, title, played, bars}`, `looper {active, loops[]}` (union of loops seen active), `drums`,
    `files[]`.
  - **`marks[]`** = `{sec, at, kind, value}` with `kind` in a closed set (`monitors._mark_state`):
    `preset` (+ `name`, + `song {slug, title, line}` when played from a setlist line), `scene`, `section`
    (arrangement running), `click` (+ `bpm`). An empty value is never a mark.
  - **Index** (`pending_takes[]` of the heartbeat, `takes._row`): the 50 most recent takes not `done`:
    `uid` (folder name, or the Reaper file name, lower-cased to `[a-z0-9._-]`, stable — `takes.uid_of`),
    `started_at`, `duration_sec`, `size_bytes`, `tracks`, `mode`, `band` (id), `band_name` (display
    only), `session`, `preset_name`, `title`, `machine_mode`, `kind` (derived from `machine_mode` for takes
    older than the field), `cut_pending`, `songs_detected`, `parent`/`offset_sec` for a cut piece, and
    `upload {state, code?, at?, rec_id?, pct?, until?, since?}` with `state` ∈ `pending` · `queued` · `uploading`
    · `done` · `refused` · `cut` · `held`/`transcribing`/`dropped` (Riff).
  - **`take-tag`** skips per take with a stable reason: `unknown_take`, `band_unknown_on_rack` (+ `band`),
    `malformed`. The rack never creates a space: a band id must be in its cached roster
    (`takes.resolve_band`). `band: null` = untagged: the take stays on the rack. A tag never starts an upload.
  - **Upload** (`uploader.upload_take`): only tagged takes, never during a REC or in the Gig mode
    (`uploader.can_run`). By default the processed lanes (`kind` `mix`, `track`) go as **FLAC** plus a frozen
    copy of `take.json` (without `upload`) as `meta`; the job's `kinds` adds `di` / `midi`. A track's kind
    comes from its file name (`uploader.kind_of`); names are cleaned to `[A-Za-z0-9._ -]` (original kept as
    `orig`). A Riff uploads only its author's lanes and score. Steps: `POST /api/ext/recordings {uid, take,
    band, tracks[{idx, filename, kind, sha256, size_bytes}]}` (`take` = the same frozen copy), then
    8 MiB chunks from the server's `received` offset (`409 expected offset N` = resume at N), then
    `complete`. Resuming keeps no state on the rack. A refusal is written as `upload.state: refused` with a
    `code` (`quota` for 413, `relink`, `forbidden`, `space_gone`, `no_space`, `offline`, `open_<status>`,
    `uploader.refusal`) and is **never retried automatically** (`uploader.due` skips it); `band` is never touched.
  - **Cut** (`takecut`, in the uploader loop, so never during a REC or in Gig): boundaries come from
    `marks[]` preset recalls, never from audio; a segment shorter than 20 s is absorbed by its neighbour;
    a segment whose Mix lane is at or below −80 dBFS is not kept (`cut.skipped`). Each piece is a take of
    its own with `parent`, `offset_sec`, `duration_sec`, `cut {by, at, confidence}`, `preset`,
    `preset_name`, `song`, `take_no`, `title`, the parent's `band` and `session`, marks and flags made
    **relative** to the piece, and a BWF `time_reference` shifted by the offset (a zero anchor is not
    propagated). The parent becomes `upload.state: cut` and keeps its media until `take-source-release`,
    which only accepts a cut take, deletes its `.wav`/`.mid` and keeps `take.json` with `source_released`.
- Other documents: patches `docs/patches.md`, setlists `docs/setlists.md`, songs `docs/songs.md`, modes
  `docs/modes.md`, returns/cards `docs/returns.md`, block status `docs/block-status.md`, diagnostics
  `docs/diagnostics.md`, karaoke `docs/karaoke.md`, connect `docs/connect.md`, loans
  `docs/library-loans.md`, anim packs `docs/anim-packs.md`.

## 8. Guarantees and compatibility

What a change on either side must not break:

1. **The rack keeps playing offline.** No live path waits on golem.fm; every network call has a timeout
   and returns `0` instead of raising.
2. **One ack per job, never a retry.** A job id in flight is never started twice; an error ack is final.
3. **Lane by prefix.** `take-*`, `setlist-*`, `push-catalog*` → sync; everything else → rig, in order.
4. **Flat jobs.** Payload keys beside the envelope; `_job` wins over `id`. `mode-set` and `recorder-set`
   treat every key that is not in `JOB_ENVELOPE` as a field: a new envelope key must be added there first,
   or those two actions refuse with "unknown field".
5. **Refusals are said.** Busy, locked, recording, unknown preset: an English sentence in the error ack,
   nothing half-written (`inputmap-set`, `mode-set`, `recorder-set` are all-or-nothing).
6. **A token stays with its server**; nothing is sent unpaired; plain `http` only to this machine or the LAN.
7. **Long-poll degrades**: a server ignoring `wait` gets the old periodic behaviour (back-off to 300 s).
8. **`404` = not served yet**, never a crash, for every optional endpoint (heartbeat, presence, state,
   patches, setlists, songs, plan, bars).
9. **Whole-catalogue pushes say so**: patches and setlists carry `complete: true`; setlists always carry
   `scopes` (possibly empty) — its presence says the rack can declare a scope.
10. **What the rack holds is not removed by a sync**: un-starred backings stay; inventory snapshots are only
    sent after an error-free library read (otherwise additions only).

Legacy values still accepted:

- `source: "maestrium"` in export `deps[]` is read as `"golemfm"` (`preset_export.STORE_SOURCES`); the rack
  only writes `"golemfm"`.
- `patch-push` = `patch-install`.
- No longer accepted (2026-10-15): `id` standing for `pack_id` (`anim-pack-*`) or `mode` (`mode-set`). A flat job
  without that payload key would have read the JOB id as the target; it is now an error ack "missing id".
- `song-install` without `category` = `song`; a standard without a `.golem` route falls back to
  `/api/ext/standards/{slug}` JSON.
- A server without `?wait`, without `/plan`, without `progress`, or answering `400` to a new pack kind
  (`kit`, `loop`, `sample`, `groove` — skipped, retried next sync) keeps working.
- `serial` absent from an answer = nothing recorded; `null` = no number yet.
- Root `band` / `people` in `/api/ext/band` (pre-multi-space servers) are ignored on purpose.
