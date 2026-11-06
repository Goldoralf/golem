# Music genres — the taxonomy

> **Status: CODED** (rack side) — the two-level genre taxonomy (17 families, 1022 subgenres), what a preset
> and a song carry, and how the rack loads and migrates it (`bridge/genres.py`, `config/genres.json`).

golem.fm owns the list. The rack ships a copy in `config/genres.json` and replaces it with the version
golem.fm serves (§6). The full list of subgenres, with aliases and references, lives **only** in that file —
read it there rather than in a document.

## 1. Model

- **Two levels**: a **family** (17), then a **subgenre** of that family. A family alone is a valid choice.
- **A preset carries families only** — 0 to 2, ordered, optional (`styles`, with `style` = the first;
  `genres.MAX_PRESET_STYLES`). To match a sound to a song the family is enough (a "Metal" sound serves
  djent as well as thrash). Hardware modelers do not ask for a genre on the device either; genre lives on
  sharing sites.
- **A song carries up to two (family, subgenre) pairs, ordered.** The first is the main one: it shelves
  the work and weighs most in searches. A hyperpop metalcore track is **Metal / Metalcore** then
  **Pop / Hyperpop** (the noun first, the adjective second); it shows under all four. golem.fm edits song
  genres, not the rack.
- **A hybrid with an established name stays ONE subgenre**, in one family (the dominant one): nu metal,
  rap metal, pop punk, trip hop, jazz fusion… Only unnamed combinations use two pairs.
- **Two subgenres of the same family** are allowed (Metal / Djent + Metal / Progressive metal).
- **No free tags**: the list aims at completeness.
- Only the subgenre is stored; its family is always derived, never stored separately.
- **Ids** (`id`, kebab-case ASCII) are exchange keys; only the English **label** is displayed. Family ids
  and subgenre ids are disjoint (`genres.label_of` relies on it).

## 2. File format (`config/genres.json`)

```json
{"version": 1, "status": "draft", "verified": {"date": "…", "musicbrainz": …, "discogs": …},
 "families": [
   {"id": "metal", "label": "Metal",
    "subgenres": [{"id": "djent", "label": "Djent", "tier": "core", "aliases": [], "refs": ["musicbrainz"]}, …]},
   …],
 "legacy": {"<old style>": ["<family>", "<subgenre>|null"]}}
```

- `tier`: `core` (the most common, shown first; 307 of them) or `niche`.
- `aliases`: other names, so that searches and external lists meet ours.
- `refs`: which open reference confirms the subgenre (`musicbrainz`, `discogs`, or none).
- `legacy` (optional, served by golem.fm): the mapping of old flat styles.

`genres._valid` accepts a document whose families all have `id`, `label` and a `subgenres` list.

Families and ids: Metal (`metal`), Rock (`rock`), Punk & Hardcore (`punk`), Pop (`pop`), Electronic
(`electronic`), Hip-hop (`hip-hop`), R&B, Soul & Funk (`rnb`), Blues (`blues`), Jazz (`jazz`),
Folk & Country (`folk`), Latin (`latin`), Reggae & Caribbean (`caribbean`), World (`world`),
Classical (`classical`), Stage & Screen (`screen`), Experimental (`experimental`), Other (`other`).

## 3. How the list was built

Built from Wikipedia's genre lists, then each subgenre was checked by label and aliases against
**MusicBrainz**'s official genre list and **Discogs**' 400 most used styles (as published by the Essentia
project). Subgenres confirmed by neither were reviewed one by one and kept when they have an established
name. Labels that are not genres one buys (critics' pejoratives, art-performance movements), labels of
hate movements, radio formats, micro-trends without a catalogue, and umbrellas that are already a family
(extreme metal) are left out on purpose.

## 4. Placement rules

- A genre defined by a **region or nation** goes to **World** (by region), European traditions included
  (flamenco, fado, celtic, klezmer, musette). **Folk & Country** keeps Anglo-American folk and country and
  place-less folk movements (indie folk, freak folk…).
- **Latin** = Spanish- and Portuguese-speaking Latin America, Spanish-speaking Caribbean and Brazil included.
  **Reggae & Caribbean** = English-, French-, Creole- and Dutch-speaking Caribbean.
- A **national industrial pop scene** (K-pop, J-pop, Schlager, variété, enka, trot, filmi) goes to **Pop**.
- A **regional rock form** (Anatolian rock, Zamrock, J-rock) stays in **Rock**: instrumentation decides.
- **Other** holds what record shops file outside genres: children's music, Christmas, brass and military
  bands, a cappella, spoken word, comedy, audiobooks, meditation, sound effects, karaoke…

Settled cases where two families were plausible:

| Subgenre | Family | Why |
|---|---|---|
| Coldwave | Rock | post-punk lineage, played by bands |
| Ethio-jazz | Jazz | a jazz practice |
| Free improvisation | Experimental | non-idiomatic; free jazz stays in Jazz |
| Nu jazz | Electronic | producers' music |
| Trap metal | Hip-hop | trap production with screams |
| Crossover thrash | Metal | filed under thrash by record shops |
| Proto-metal | Rock | retrospective label for heavy rock |

An alias that designated two genres was removed from one of them (for example "rapcore" stays on rap metal).

## 5. Old flat styles (`genres.LEGACY`)

Presets used to carry one of 20 flat styles. On load, `store` calls `preset_view.migrate` with
`genres.migrate_styles`, which maps every value through `genres.family_of`: a family id stays; an old
style uses the `legacy` table served by golem.fm, then `genres.LEGACY`; a subgenre id gives its family.
A value that matches nothing is **dropped, never guessed**. The result is deduplicated, capped at 2, and
`style` is set to the first. The migration is idempotent and happens on load, never as a mass rewrite.

| Old style | Family |
|---|---|
| djent, metal | `metal` |
| punk | `punk` |
| math rock, rock | `rock` |
| pop | `pop` |
| funk, soul | `rnb` |
| blues | `blues` |
| jazz, manouche | `jazz` |
| rap | `hip-hop` |
| electronic, ambient | `electronic` |
| reggae | `caribbean` |
| latin, brazilian | `latin` |
| folk, country | `folk` |
| world, traditionnal | `world` |
| classical | `classical` |

## 6. On the rack

- **Serving.** `GET /api/genres` returns `genres.load()`: the list served by golem.fm
  (`config/genres.remote.json`, local state, not in the repository) when it exists and its `version` is at
  least the shipped copy's, otherwise `config/genres.json`. Reloaded when either file changes.
- **Update.** The heartbeat answer announces `genres_version`; when it is newer, `genres.sync` pulls
  `GET /api/ext/genres` (see [`golemfm-protocol.md`](golemfm-protocol.md)). An invalid answer replaces
  nothing; `sync` never raises.
- **App.** `app/lib.js` `GENRE_FAMILIES` keeps a copy of the 17 families (checked by
  `tests/test_genres.py`); `app/genres.js` reads the full list. Designer ▸ Preset settings shows the 17
  families as chips with their rank (1, 2); the preset list filters by family; setlists show the label.
- **Preview DI** (`bridge/preview.py` `_bucket`): `metal` → high-gain DI; `punk`, `rock`, `blues` →
  crunch; otherwise clean (guitar) or finger (bass). The djent DI is only chosen by hand (`ref` parameter
  of the preview block).
- **Grooves** carry a single genre id (family or subgenre) from golem.fm packs; `genres.label_of` displays
  it.

## 7. Not decided

The genre of a groove is a single id today. A (family, subgenre) pair has been proposed, since a rhythm is
specific (bossa nova, shuffle, d-beat); nothing is built for it.
