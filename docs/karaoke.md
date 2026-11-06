# Vocals (karaoke) on the rack

> **Status: CODED** — the rack plays a song's stems and processes the singer's microphone on the same
> output, on command from golem.fm, and returns its clock (`bridge/karaoke.py`). Checked on a real rack
> with the stems muted; not yet heard through a real microphone.

**Names.** golem.fm calls the feature "Vocals" (the singer's tool, not a karaoke box); that is the
displayed name of the volatile preset on /live. Identifiers keep `karaoke` on both sides:
`karaoke-load|mix|prefetch|stop`, `{type:"karaoke"}`, `src:"karaoke"`, `GET /api/ext/karaoke/{id}`, the
reserved preset id `karaoke`, the cache `k-<id>`. Refusal reasons (`why`), which golem.fm may display, say
"song".

**Not a block.** There is nothing to place in a patch or a preset and no drawer entry. The karaoke is a
**volatile preset** loaded only by command from golem.fm. The rack **displays nothing** of it: no lyrics,
no title — all display is on golem.fm.

## 1. Principle

golem.fm decides, the rack executes. The rack knows nothing of the lyrics screen or of band sharing. It
receives **a song (stable id + revision), its mix and the voice patch**, plays the stems **and** processes
the microphone on the **same output**, in the **same engine**, and returns its clock. golem.fm's lyrics
screen follows that clock ("Follow golem") instead of playing the audio itself.

Why on the rack: backing and voice come out of the same converter, with the same latency and one level to
the PA, and the lyrics follow what is **heard**, not a browser clock.

golem.fm never depends on the rack to start: without a rack, or if the rack refuses, the browser plays.

## 2. What is reused

- **The Backing Track plays the stems** (`bridge/backing.py`, `golem_backing.lua`): a karaoke is a backing
  of slug `k-<id>` in the same cache `assets/backing/`, mixed per stem (`op:"mix" {stem, mute, vol}`, `vol` =
  linear `D_VOL`). The backing bus goes to OUT 1/2 like the lanes; levels are set in the mixer
  ([`mixer.md`](mixer.md)).
- **The voice lane** is built by the `patch-try` path (`tones_jobs._trial_preset`) but recalled as a
  **playing** preset, not as the sandbox.
- **The recall** is `recall.do_recall`: the mode, its vetoes, the foot controller and /live see it as a
  preset.
- **The clock and commands** use the follow WebSocket (`bridge/follow_uplink.py`, `/api/ext/golem/link`),
  already open and authenticated by the device token. Jobs are not used: they are polled too slowly for
  "load this song now".

## 3. Messages

The frame formats are listed in [`golemfm-protocol.md`](golemfm-protocol.md) §6. Their meaning:

### 3.1 golem.fm → rack

```jsonc
// load (or reload) a song — idempotent, the full state every time
{"type": "cmd", "cmd": "karaoke-load",
 "karaoke": {"id": "k_8f2c…", "rev": 3},
 "mix": {"vocals": "guide", "guide_db": -14, "muted": ["guitar"]},
 "voice": {"patch_id": "<patch>", "sha": "a91e…"} | null,    // null = no processed microphone
 "req": "r-1729…"}

// play THE RACK'S OWN COPY (2026-10-17): golem.fm no longer has this line's stems (purge M8), the rack does.
// `golem.id` = a song key (bs:/rs:/us:/ct:) or a bk:<hash> backing card; no `rev`, nothing is downloaded.
{"type": "cmd", "cmd": "karaoke-load", "karaoke": {"id": 1}, "golem": {"id": "rs:cf64…"}, "mix": {…}, "voice": {…}}

// change the mix while playing — the FULL mix state, never a delta
{"type": "cmd", "cmd": "karaoke-mix", "mix": {"vocals": "off", "muted": []}, "req": "…"}

// transport: the usual commands; play/toggle/seek are ignored when no backing is loaded
{"type": "cmd", "cmd": "play" | "pause" | "toggle" | "seek", "posMs": 63500}

// quit: the backing is unloaded and the previous preset recalled
{"type": "cmd", "cmd": "karaoke-stop", "req": "…"}

// download the NEXT song while the current one plays: download only, nothing in REAPER
{"type": "cmd", "cmd": "karaoke-prefetch", "karaoke": {"id": "k_91aa…", "rev": 1}, "req": "…"}
```

**Lot 5 (2026-10-17, maestrium `plan-vocals-library.md` §6 ter):**
- `golem.id` **alone** (no `karaoke`) plays a song that exists only on the golem (a karaoke song folder): replies,
  `pos` frames (`src: "karaoke"`) and `lyrics` (`song_id`) carry that id; nothing is fetched, the k- cache is never used.
- **No separated voice, no karaoke**: a song whose stems have no vocal stem is `refused`, why `no vocal stem` —
  never a full mix played instead.
- A `karaoke-load` of the song **already playing** is a no-op: the mix is applied, `ready` is replied, the transport
  is untouched (golem.fm may re-send it on `ended` after the rack advanced on its own).
- `{"cmd":"karaoke-queue","items":[{"karaoke":{id,rev}?,"golem":{id}?}…],"pos","mix","voice"}` — the evening's
  queue, FULL state each time (≤ 500, `items: []` clears), replied `{"state":"queue","pos","n"}`. golem.fm owns it and
  advances while connected; on `ended` with no link (`follow_uplink.LINKED`) the rack loads `items[pos+1]` itself, and
  on reconnection reports `{"type":"karaoke","state":"queue","pos","n"}`. The next song is made ready while the current
  one plays (fetched, or extracted from its `.golem`) — disk only, never during a take.

`golem.id` (`karaoke._golem_target`): a song key plays its `.golem` if it carries stems; a `.golem` without stems
(tab + lyrics only) plays the `k-<id>` cache entry of that line if it has them, with the `.golem`'s lyrics; a `bk:`
id plays the backing-cache entry with that id. Otherwise `refused`, why `not on this golem` or `this song has no stems
on this golem`. `ready` carries `from_golem` (what played), and the `lyrics` frame follows when the `.golem` has
`lyrics/song.lrc`. golem.fm only sends an id its inventory says this golem holds.

### 3.2 rack → golem.fm

- `{"type": "karaoke", "req", "state": "ready", "id", "rev", "voice", "mix", …}` — sent once, when it is
  TRUE: stems loaded in REAPER (read back from `.backing.json`), voice mounted. Optional `voice_input`
  (`"IN 2"`), `voice_src` (`rack` | `golem.fm`), `voice_why`, `from_golem` (§6).
- `state: "fetching"` with `done_mb`, `stems_done`, `stems_total` — at most one per second
  (`PROGRESS_EVERY_S`), stem by stem (the total size is only known at the end).
- `state: "refused"` with `why`; `state: "stopped"` (answer to `karaoke-stop`); `state: "cached"` (answer
  to `karaoke-prefetch`, no effect on what plays).
- `state: "ended"` with `posMs` — once, when playback reaches the end (§5).
- `state: "left"` — the user recalled a preset on the rack (screen, foot, setlist): the karaoke is left.
- `{"type": "pos", "src": "karaoke", "id", "playing", "posMs", "seq", "mix"?}` — the backing position
  frame tagged with what plays; `mix` only when it changed (`karaoke.pos_fields`). **10 Hz during a
  karaoke** (`follow_uplink.PUSH_KARAOKE_S`; about 4.5 Hz for an ordinary backing), plus an immediate frame
  on every play, pause or seek. `posMs` is REAPER's transport position, so what is heard minus the output
  latency. The browser extrapolates between frames.

The lyrics offset (±10 s) never reaches the rack: it is a display setting applied by golem.fm to the
clock it receives.

## 4. Loading (`karaoke._load`)

All of `karaoke-load`, `karaoke-mix` and `karaoke-stop` go through **one worker** (a queue): the WebSocket
never blocks and two close loads run in order. `karaoke-prefetch` has its own thread (it never touches
REAPER).

1. **Refusals of the whole karaoke** (`_refusal`): a locked mode, a take recording, a mode that keeps
   `backing` off, or the backing player not ready. The mix is validated before any download (`vocals` ∈
   `off | guide | full`).
2. **Stems.** If the song is not cached at that revision, the rack reads `GET /api/ext/karaoke/{id}`. If
   the answer links a song the rack holds as a `.golem` at the announced version (§6), that file plays.
   Otherwise the rack downloads every stem (`karaoke.fetch`) into `assets/backing/k-<id>/` under its own
   name and extension (`.mp3`, `.flac`, `.wav`), with a `meta.json` (`karaoke_id`, `rev`, `stems`,
   `voice_stems`, `title`, `duration_ms`, `mix`, `fetched_at`, `played_at`). A changed `rev` triggers a new
   download. A lent song whose stems golem.fm denies (`stems_denied`) is refused with "lent song: drop your
   own .golem on this golem".
3. **Mix** (`backing_mix`): every stem of the song is set (nothing inherited from a previous mix).
   `vocals` targets the **voice stems** (`voice_stems`: `["vocals"]` for a separated song, `voice-1`… for
   a recorded original): `off` mutes them, `guide` sets them to `guide_db` (default −14 dB, i.e. `D_VOL`
   0.1995, clamped to −60…0), `full` leaves them at unity. `muted` stems are muted.
4. **Voice** (`_voice_lane_preset`):
   - The mode must allow `voice`; otherwise `voice: "none"` with the reason.
   - **The rack is authoritative on the patch version.** If the patch is installed
     (`library/patches/<patch_id>.json`), that version plays — the one tuned in the Designer — and the
     `sha` is ignored (`voice_src: "rack"`). If it is absent and a `sha` is given, the document is
     resolved by its blob, as `patch-try` does (`voice_src: "golem.fm"`). Absent without `sha`:
     `voice: "refused"`, `patch <id> is not on this rack`.
   - **The physical input does not come from the patch** (a patch carries no input): the lane listens to
     the card's input of role `voice` (Soundcard input roles, `patches.bind_input`). `ready` names it in
     `voice_input`.
   - If the voice lane does not compile (`recall.check_preset`), `voice: "refused"` and the stems still
     play.
5. **No voice mounted → the karaoke sits ON TOP of the preset that was playing** (`_base_preset`): a rig
   without any lane cannot be built, and the musician's guitar keeps sounding. If no preset is loaded at
   all, the load is refused.
6. **Recall.** The volatile preset — id `karaoke` (`store.KARAOKE_ID`), name "Vocals",
   `origin: "golem.fm"`, `backing.songs = [song]`, `karaoke: {id}` — is written to
   `presets/.karaoke.json` (`store.KARAOKE_FILE`, local state) and recalled with `do_recall`. The preset
   that played before the FIRST load is remembered for `karaoke-stop`. The volatile preset never appears
   in the catalogue and is never published (`tones_sync.publish_preset` refuses it). It carries no
   backing-track block, so /live shows no playback pad.
7. `ready` is sent once REAPER reports the stems loaded; after 4 s without them the rack asks for an
   explicit load, and gives up after `READY_TIMEOUT_S` (25 s) with "the stems did not load in Reaper".

### Chaining songs (a playlist)

The **queue lives on golem.fm**; the rack only knows the current song and at most one prefetched.

1. `karaoke-load` (n) → `ready` → `play`. While (n) plays: `karaoke-prefetch` (n+1) → `cached`.
2. End of (n): the rack stops by itself and sends `ended` once.
3. `karaoke-load` (n+1): if a karaoke is mounted and the voice patch (`patch_id` + `sha`) is the same, the
   rack **chains**: it changes the stems and the mix without recalling a preset or rebuilding the voice —
   the microphone never cuts (`voice: "kept"`). If the voice patch changes, the lane is rebuilt; the
   microphone cuts for a second or two (`voice: "rebuilt"`).
4. End of the playlist: `karaoke-stop` recalls the preset from before the first load.

## 5. End, stop, leave

- **End** (`on_backing`): `golem_backing.lua` publishes a counter `ends` in `.backing.json` that only
  moves when a song reaches its end. Seen from the bridge, an end (stop + return to 0) otherwise looks
  exactly like a requested stop. `ended.posMs` is the length REAPER really played, not the duration
  golem.fm announced.
- **Stop** (`_stop`): stop and unload the backing, recall the previous preset, deactivate.
- **Leave** (`on_recall`): any preset recalled on the rack ends the karaoke and sends `left`.

## 6. Playing a `.golem` the rack already holds

`GET /api/ext/karaoke/{id}` may carry `song_id` (a golem id) and `golem_etag`. If the rack holds that song
with stems at **exactly** that version (the etag recorded when it was pulled, `golem_pull.etags`), it plays
its own `.golem` and downloads nothing (`_local_golem`); `ready` carries `from_golem`. It never plays a
different version from the one golem.fm announces.

In that case golem.fm may not be allowed to serve the lyrics, so the rack relays them itself on the
WebSocket, in transit only: `{"type": "lyrics", "karaoke_id", "song_id", "rev", "format": "lrc", "text"}`
(`send_lyrics`, raw `.lrc` text from the file). The browser can ask again with `lyrics-get`; the rack only
answers for the song currently playing.

## 7. Cache

`assets/backing/k-<id>/`, at most `CACHE_MAX = 50` songs (about 2 GB at ~40 MB a song). Eviction runs after
each download (`evict`) and removes the **least recently played** (a never-played song counts from its
download). The current song and the one just prefetched are never evicted. The `k-` prefix never collides
with a song slug.

## 8. Checking without golem.fm

- `GET /api/karaoke` — state and the last 50 frames.
- `POST /api/karaoke/cmd` (admin) — injects a `karaoke-*` command. Its answers stay on the rack (`local`)
  and are never sent to golem.fm.

## 9. Limits and what is not built

- The karaoke state (previous preset, mounted voice) lives in the bridge's memory. A bridge restart during
  a karaoke forgets it: `karaoke-stop` then no longer recalls the previous preset (the rack stays on
  `karaoke` until the next recall).
- Not built: any display on the rack, a placeable block, the play queue on the rack, key or tempo change,
  singer scoring, recording the karaoke take, a `karaoke` setlist line, foot control, several voices
  (duet). Modes have no `karaoke` service: the `backing` and `voice` vetoes apply.
