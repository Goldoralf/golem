# The backing belongs to the song

> **Status: CODED** (2026-10-18) — a backing is the **song's** audio; a preset only **plays** it and says which
> stems it mutes. Replaces the preset's own song list (`backing.songs`), now ignored and migrated (§5).

Related: [songs.md](songs.md) (the song, its sheet), [setlists.md](setlists.md) (lines),
[arrangement.md](arrangement.md), [samples-backings.md](samples-backings.md), [golem-format.md](golem-format.md).

## 1. The model

- A **song** has one preset (its sheet), one arrangement, and its **audio**: the stems of its `.golem`.
- A **preset** serves any number of songs and does **not** know which ones. It is a rig.
- So the backing that plays is the backing **of the song being played** — never one chosen by the preset.

A preset played **on its own** (from a bank of sounds, no song) plays **no** backing.

## 2. Which backing plays

`recall.effective_preset`, in this order, only when a song is being played (a setlist line, or ▶ Play from Songs):

1. the song's `.golem`, when it carries stems (`golemfm.backing_key` with the line's `band_song`);
2. otherwise the song's sheet `backing` (a golem.fm backing cached on this rack), the line's exception included
   (`songs.line_sheet`);
3. otherwise nothing.

The **Backing Track** block is not required for the song's backing to play (a setlist line already played it
without one): it adds the foot (`SW5 · ▶ / ■`) and the stem rule (§3). Without it, the song plays its backing with
its own mix only.

## 3. The stem rule — in the preset

The Backing Track block carries **which stems this preset mutes, in every song** — it knows what is played live,
because it knows its lanes:

| Param | Meaning |
|---|---|
| `mute_own` (default `true`) | mute the parts **this preset plays**: each lane of the preset that has an input on this golem (a lane "IN KO" plays nothing) — guitar → `guitar`, bass → `bass`, voice → `vocals`, keys → `piano`, drums → `drums` |
| `stems` | exceptions per family, `{family: "mute" \| "play"}` — the tap on a tile |

Families: `vocals`, `drums`, `bass`, `guitar`, `piano`, `other` (the same as golem.fm's separation;
`golemfm.expand_mix` applies a family to `guitar-1`, `guitar-electric`…).

## 4. The song's own mutes

A song can mute more, for itself only ("on this one, no piano"): its **mix**, stored on this rack next to the song
(`songs/.mix/<id>.json`, or the cache's `meta.json`) — unchanged.

**What plays** = the song's mix, then the preset's rule on top: a stem muted by either is muted; an exception
`play` in the preset lifts the preset's own rule only, never the song's mute. Computed at load
(`backing.BackingControl.load`), never written into the song.

## 5. Migration

At startup (`backing_owner.migrate`, idempotent, nothing deleted): for every preset whose legacy
`backing.songs` names a backing,

- each **song** whose sheet uses this preset and has neither stems nor a sheet `backing` receives it;
- each **setlist line** playing this preset without a song (`band_song`) and without its own backing receives it.

The preset's `backing.songs` stays on disk, ignored.

## 6. The drawer (Designer ▸ Config ▸ Backing Track)

Mockup validated 2026-10-18. Top row: Active, the foot (`SW5 · ▶ / ■`), **▶ Listen** (the loaded song's original;
greyed without a song), move, delete.

- **The song loaded now**: cover, title, artist, "stems on this golem", where it comes from (the setlist line),
  **Open the song ›**. Without a song: "No song loaded — the backing belongs to the song", with **▶ Load « title »**
  for each song that uses this preset — it loads the song **without starting it** (`POST /api/arrangement
  {op: "select", song}`: the state names the song, its backing is armed, its arrangement stays stopped). With a song
  loaded, the other songs of "Used by" offer **▶ Load** too, and **✕ Unload** (`{op: "unselect"}`) leaves the preset
  on its own. Both are **remembered** (`.live.json`, `recall.remember_live`): a restart of the bridge comes back
  with the song loaded, as after a setlist line.
- **Nothing binds the song to the preset**: the loaded song lasts until another preset or another setlist line is
  recalled, or Unload. A setlist line that has a song loads it with its preset, automatically.
- **The stems this preset mutes — in every song**: the toggle `Mute what this preset plays`, six tiles (Guitar,
  Bass, Piano, Drums, Vocals, Other) — muted by the preset (with the reason: "you play it — guitar lane"), muted by
  the song (pink), or playing. A song loaded adds a switch **This preset · This song**: the tiles then edit the
  preset's rule, or the song's own mutes.
- **Used by**: the songs that use this preset and the lines that play them — computed by golem
  (`GET /api/backing/drawer`), never stored in the preset.

## 7. Endpoint

`GET /api/backing/drawer?preset=<id>` → `{song, used_by, parts, own}` — the loaded song (if it plays this preset),
the songs and lines using the preset, each family's state and reason, and the parts this preset plays.
