# Library loans to a band (rack side)

> **Status: CODED** — how the rack receives sounds a band mate lends to one of its bands, pulls them on
> demand, records their provenance, and never pushes them back as its own (`bridge/loans.py`).

The cloud side of the exchange (the manifest, the blob route) is described in
[`golemfm-protocol.md`](golemfm-protocol.md). This page covers what the rack does with it.

## 1. What arrives

A member lends a patch, a preset, a tone (NAM capture, IR…), a keys bank, a sample, a kit or a groove
to a band. A loan is not a copy: the object stays with the lender.

The tones manifest (`GET /api/ext/tones/manifest`) carries a `lent[]` section per (band, lender):

| Field | Content |
|---|---|
| `packs[]` | same shape as the member's own `packs`, plus `loan` |
| `items[]` | content created on golem.fm; the file is the blob `sha` |
| `patches[]`, `presets[]` | informational |
| `gone[]` | loans withdrawn upstream (nothing to pull) |
| `incomplete[]` | a dependency is missing on the lender's side — never installed, shown as a missing capture |
| `missing_blobs[]` | blobs not yet available |
| `lent_rev` | fingerprint of the section |

A lent blob downloads through the usual `GET /api/ext/tones/assets/{sha}`.

## 2. Pull on demand, never by default

A member's personal rack sees everything lent to all of their bands. Pulling it all automatically would
fill the disk with sounds they will not play. A lent sound is only downloaded when something that will
**play** it asks for it:

- **An incoming patch or preset** (`patch-*` and `preset-install` jobs → `tones_jobs._settle_captures`):
  a referenced capture the rack lacks is looked up in the member's own packs first, then in the lent
  packs (`tones_jobs._manifest_tones`, `_install` via `loans.find_pack`).
- **Recalling a preset** whose capture does not resolve (`recall.py` → `loans.pull_for_preset`, in the
  background; the recall never waits). If the capture is lent, it is installed and the sandbox is
  re-applied (`recall.reapply_sandbox`) — only if the same preset is still the one playing.
- **The ⬇ Lent (N) chip** in the Library top bar (`app/page-library.js` `LentChip`,
  `POST /api/library/lent/pull-all` → `loans.pull_all`): the human gesture that pulls every pending
  pack and item. The chip is hidden when nothing is pending.

## 3. Provenance: `library/catalog/.lent.json` (local state, not in the repository)

A lent pack is stored **like the member's own** (same folders, same `tones-index.json`), so a patch
that references `t3k:246` resolves it with no special path. Provenance lives beside it, in a registry
(`loans.REG`):

```json
{"lent_rev": "9f2c…",
 "available": {"t3k:246": {"title": "Fender Twin", "kind": "amp", "catalog_id": "246", "bytes": 1234,
                           "lent_by": [{"band": "<band>", "owner": "<member>"}]}},
 "installed": {"t3k:246": {"lent_by": [...], "shas": ["…"], "at": "…", "state": "lent"}},
 "installed_items": {"<sha>": {"kind": "sample", "name": "…", "lent_by": [...], "state": "lent"}},
 "incomplete": [...], "gone": [...]}
```

Rules applied by `loans.refresh(manifest)`, called on every library sync and when a job reads the
manifest:

- `lent_by` is a **list**: the same uid can arrive from two sections (two bands, two lenders).
- **Own copy wins.** A uid present in the member's own `packs` leaves the registry: it is theirs again,
  so it syncs normally.
- **Withdrawal.** An installed uid that left `lent[]` becomes `state: "no_longer_lent"`. **Nothing is
  deleted** (an orphan still plays tonight, see [`patches.md`](patches.md)); cleaning up is a human
  gesture. A withdrawal is seen at the next sync, not live.

## 4. Never send a loan back as one's own

The library sync uploads to golem.fm everything the rack owns. Without a guard, a loan would silently
become a copy. Two guards:

- **Sync** (`tones_sync._worker` → `loans.filter_packs`): a pack whose uid is an installed loan is not
  pushed. In **aggregated** packs (`local:samples`, `local:synth-vital-*`, one asset per file), a file
  whose sha256 is a loan's is removed from the pack and from the blobs to upload. Consequence: a file the
  member also owns byte for byte is not pushed while it is also a loan — its bytes are already on
  golem.fm.
- **Store** (`tones_sync.publish_preset` → `loans.lent_deps`): a preset with a lent dependency is refused
  with `uses <title>, lent by <owner> — keep a copy first`. golem.fm applies the same guard
  (`not_lent`, 422).

## 5. Screen

- Library ▸ Tones: a lent sound's card reads `lent by <owner> · <band>` or `no longer lent (was …)`
  (`app/page-amps.js` `lentLabel`).
- `GET /api/library/lent` (`loans.status`) serves the registry state, including `pending`, `by_catalog`
  and the `pull_all` progress the chip displays (`⏳ done/total`).
- The block status also names a missing lent pack: `not on this rack — on golem.fm (lent by …)`
  (`bridge/blockstatus.py`).
