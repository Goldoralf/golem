# Sound-card setups travel through golem.fm

> **Status: CODED** (rack side) — how a rack sees the setup of the same sound card on the user's other
> racks, offers its own, and applies one only on a local gesture (`bridge/card_setups.py`,
> `bridge/routes_card_setups.py`, Soundcard page).

The same card can carry different input setups on two racks (or two OSes of one machine), with nothing
linking them. The end user has no git and no second clone: they have one or more racks and golem.fm. So
golem.fm keeps each rack's setup and offers it to the others.

## 1. Principle

1. **Each rack loads its own setup**, specific to its OS and to the name under which it sees the card
   ([`input-map.md`](input-map.md)).
2. **Each rack publishes** its card setups in the heartbeat's `cards[]`.
3. **golem.fm returns**, on request, the setups of the same card on the user's other racks ("siblings")
   and any pending offers.
4. **A rack is never modified remotely.** "Offer this setup to …" leaves an offer; the target rack shows a
   chip and the user decides in front of the card.

Presets and patches are not affected: they bind to inputs by name ("Guitar 1") and follow whatever setup
the rack loads.

## 2. Card identity

`usb` = `vvvv:pppp` (vendor:product, lowercase hex, `cards.usb_of`), the key that already links
`hw:V276` ↔ `asio:Universal Audio Volt` ↔ `coreaudio:Volt 276` (`cards.same_card`). It identifies the
**model**: two identical cards of one user are not told apart. `serial` is part of the protocol for that
case but the rack always sends `null` today (`card_setups.identity`). A card without `usb` (unknown to the
registry) is not synchronized, and that is not an error.

## 3. What the rack sends (heartbeat)

Each `cards[]` entry built by `rigstatus.cards_doc` carries, besides the existing fields, `usb`, `serial`
and `updated_at` (mtime of the card's input-map file, `card_setups.updated_at`). The setup itself
(`inputs`, `outputs`, `midi_in`, `midi_out`) comes from `rigstatus.setup_of` — the same function that
`card_setups.local_setup` uses, so golem.fm compares exactly what the rack sends.

```json
{ "card": "asio:Universal Audio Volt", "connected": true, "active": true,
  "usb": "2b5a:0023", "serial": null, "updated_at": "…Z",
  "inputs":  [{"slot": "IN 1", "kind": "audio", "role": "voice",  "nth": 1, "name": "Voice 1", "pair": null, "person": null}],
  "outputs": [{"slot": "OUT 1-2", "role": "monitors", "type": null, "pair": "1-2", "person": null}],
  "midi_in": "fcb", "midi_out": "whammy-dt" }
```

- The rack sends no `os`, `rack` or `fingerprint` per card: golem.fm reads the OS from `caps.os`, the rack
  from the token, and computes the fingerprint itself.
- One identity, one setup per rack: when the same card appears under two names (the active `asio:…` and a
  `hw:…` declared by a mode), only the active one (else the connected one, else the first) keeps `usb`; the
  others are sent with `usb: null`.
- A known but disconnected card is sent too: its setup still counts.

golem.fm keeps the last setup received per (user, rack, usb); a card missing from a heartbeat is kept.

## 4. Calls to golem.fm

All with the rack token, under `card_setups.EXT = /api/ext/golem/card-setups` (see
[`golemfm-protocol.md`](golemfm-protocol.md)):

| Call | Body / answer |
|---|---|
| `GET …?usb=<id>[&serial=…]` | `{usb, fingerprint, siblings:[{rack, rack_name, os, card, updated_at, received_at, fingerprint, same, inputs, outputs, midi_in, midi_out}], offers:[{offer_id, from_rack, from_name, offered_at, fingerprint, setup}]}`. Cached 60 s (`fetch`, `CACHE_S`). |
| `POST …/offers` | `{usb, serial?, to_rack, card, setup}` → 202 `{offer_id, fingerprint}` |
| `POST …/offers/{offer_id}/reply` | `{status: "applied" \| "declined"}` → 200; 410 if the offer was already deleted or replaced (the rack drops its chip and applies nothing more) |

`same` means the sibling's fingerprint equals the one the asking rack last published. "applied" proves
nothing by itself: the next heartbeat of the rack is what makes `same: true`.

golem.fm unreachable or not paired → no siblings, no chip, no question. Nothing breaks, nothing is guessed.

**Job `card-setup-offer`** (pushed to the target rack, flattened payload `{offer_id, from_rack, from_name,
offered_at, usb, serial, card, os, fingerprint, setup}`): `card_setups.on_job` stores it locally, **applies
nothing**, and acks `{status: "shown"}`. A newer offer from the same rack replaces the older one.

## 5. On the rack

**Local state** `config/.card-setups.json` (`STATE_PATH`):
`{"<usb>": {"ask": bool, "separate": {"<rack>": "<fingerprint>"}, "offers": [...]}}`.

**First encounter.** When `inputmap._load` seeds a card under a new name, it calls
`card_setups.first_seen`, which sets `ask`. The Soundcard page then asks the question only if golem.fm
knows at least one sibling: "Use this setup" or "Keep it" (`POST /api/card-setups/later`). Seeding stays
seeding; nothing is guessed.

**Soundcard page chip** (`app/card-setups-model.mjs` `chipLabel`): an offer comes first
(`⇄ setup offered by <rack>`), otherwise `⇄ <rack> setup differs` while a sibling has `same: false` and is
not marked separate. Tapping it shows a row-by-row comparison (`setupRows`; USB ports are the rack's, not
the card's, so they are left out).

| Rack route | Gesture |
|---|---|
| `GET /api/card-setups?card=&fresh=` | `card_setups.status`: `{usb, serial, local, siblings[+separate], offers, ask, differs, reachable}` |
| `POST /api/card-setups/apply {rack}` | "Use the …'s setup here" (`use_sibling`) |
| `POST /api/card-setups/offer {to_rack}` | "Offer this setup to …" (`offer`) |
| `POST /api/card-setups/separate {rack}` | "Keep them separate" (`separate`) |
| `POST /api/card-setups/later` | "Keep it" at first encounter (`ask_later`) |
| `POST /api/card-setups/offers/{id}/reply {status}` | "Use it here" / "Decline" on an offer (`reply`) |

**Keep them separate** is local: the rack remembers (sibling rack, sibling fingerprint) and shows the chip
again only if that fingerprint changes. golem.fm stores nothing for it.

## 6. Applying a setup (`card_setups.apply_setup`)

A setup is applied entry by entry **through the input-map setters** (`set_pair`, `set_role`, `set_nth`,
`set_person`, `set_out_person`), never by writing the file, so their invariants (unique number per role,
known roles, pairs) stay the judges. Whatever does not pass is listed in `skipped`, never invented:

- only audio `IN n` entries are applied (USB ports belong to the rack);
- a slot beyond this card's inputs is skipped (`not on this card`); slot numbers (`IN 1`, `OUT 1-2`) are
  REAPER's, the same on every OS;
- an unknown instrument role is skipped; an unknown output role becomes `other`;
- a `person` not in this rack's roster is **cleared**, not invented;
- output `type` is kept only if `iem` or `wedge`.

Then the input map is refreshed and the rig re-emitted (`routes_inputmap._refresh(reemit=True)`).

**Never automatic**: neither on receiving an offer nor at first encounter. A setup copied silently is
exactly what can bind a guitar lane to a microphone.

## 7. Development

`config/.card-setups.json` with `"demo": true` makes `fetch` return a fabricated sibling (`_demo`), to see
the screen without golem.fm.
