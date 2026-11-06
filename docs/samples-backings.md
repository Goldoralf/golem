# Samples and backings

> **Status: CODED** — two sample types chosen at import (`short`, `song`) and one backing object played by the
> Backing Track block; composing a local backing from samples is no longer offered (existing local backings
> still play).

Related: [arrangement.md](arrangement.md) (one clock), [songs.md](songs.md) (song stems come from golem.fm or a
`.golem`), [separation.md](separation.md) (stem vocabulary), [golem-format.md](golem-format.md).

## 1. Two kinds of samples

| `kind` | What it is | Played by | Library tab |
|---|---|---|---|
| `short` | a one-shot | pad kits (RS5k) and the Sample block, on the foot | Samples ▸ Short |
| `song` | a long file: a whole song, a version without vocals, a click, a pad | a local backing, through the Backing Track block | Samples ▸ Songs |

- **The kind is chosen at import, never guessed from the duration**: you drop into the Short or the Songs tab
  (`POST /api/sample/upload?name=&kind=short|song`, raw body, ≤ 200 MB).
- "→ Songs" / "→ Short" corrects a mistake: `POST /api/sample/kind {file, kind}` (`kits.set_sample_kind`);
  turning a sample back to `short` is refused (409) while a local backing uses it as a stem.
- The kind lives in the sidecar `assets/samples/.kinds.json` `{rel: {kind, loudness_db}}`; a file absent from it
  is `short` (`kits.sample_kind`).
- A `song` sample measures its **loudness** (RMS dBFS, `kits.sample_loudness_db`, WAV only) at import.
- The kind travels in the sample pack pushed to golem.fm (`extra.kind`, `extra.loudness_db`) and comes back in
  `sample-pack` jobs (`samples[].kind`).

## 2. A backing

A backing is a song directory `assets/backing/<slug>/` with a `meta.json`, played by `golem_backing.lua`
(command `backing`, op `load`) on the Backing bus. Sources:

- **golem.fm**: stems separated by golem.fm, downloaded into the cache (`/api/backing/catalog`, download routes);
  `meta.files` names the stems;
- **a `.golem` song**: its stems are explicit files in the song's working copy (`golemfm.local_files` for a song
  key);
- **legacy local backings** (`slug` `local-…`, `meta.local: true`, `meta.stems: {slot: rel}`, `bpm`, `mix`):
  composed from `song` samples. Creating one (the former "+ New backing" and `POST /api/backing/local`) is
  removed: backings are added from golem.fm or by importing a `.golem`. Existing ones still play and can be
  deleted (`DELETE /api/backing/cache/{slug}`); their samples stay protected while they serve as stems
  (`kits.backing_usage`).

Stem names follow the open vocabulary of `golemfm.STEM_NAME_RX` (`^[a-z][a-z0-9-]{0,31}$`), **at most
`MAX_STEMS = 16`**; extra or malformed names are ignored and logged, never renamed (`golemfm.keep_stems`). The mix
applies per family (`guitar` covers `guitar-1`, `guitar-electric`; aliases `voice` = `vocals`, `keys` = `piano`)
— `golemfm.expand_mix`.

The Backing Track block, the setlist line and the Designer sheet are **pickers**: they list backings of every
origin (`/api/backing/catalog`, `/api/backing/cache`, entries `local: true`). A backing is reused across setlists.

## 3. Rules

1. **All stems start together, at zero.** No per-stem offset: a file that starts later carries its own silence.
   The longest stem sets the end.
2. **A backing carries its tempo.** The Arrangement has one clock; a golem.fm backing arrives with the song's BPM.
   Without a tempo the backing plays but the Arrangement cannot follow it — the screen says so.
3. **Same loudness for every stem**: a local `song` sample is brought to the capture target
   (`kits.LOUD_TARGET_DB = -18` dBFS RMS) by `kits.stem_gain` (linear gain bounded ×0.1..×4, written into
   `mix[slot].vol`). A stem whose format cannot be measured here (mp3, ogg) plays at 0 dB.
4. **The mix belongs to the backing** (`meta.json`), not to the block sheet. A local backing loads with its own
   mix, not golem.fm's default mix.
5. When a song has a bar map, the backing load also places the song's real beats as a MIDI item on the Click
   track (`bars.write_ticks`, [bars-format.md](bars-format.md)).

## 4. Out of scope

- No MIDI player assigned to a patch: a whole song = a backing; a fragment = a `short` sample; an accompaniment
  that follows sections = the Standard block's chart ([standards.md](standards.md)).
