# golem Capture, as an LV2

**Status: CODED** — proven on the Golem Engine with a real capture (2026-11-17). Linux only.

The reader of [controllable capture modules](../../docs/capture-module.md) is a CLAP plugin
([`native/capture`](../capture/README.md)). The Golem Engine (Ardour) hosts LV2 and VST3, not CLAP. This folder builds
the **same reader** — `../capture/engine.cpp` and the same pinned NAM parametric core — behind an LV2 interface:

- `https://golem.fm/lv2/capture`: mono in, mono out, 32 controls `Control 01…32`, normalized 0..1 (the same slots as the
  CLAP parameters).
- The capture is given as a **file**: a `patch:Set` of `https://golem.fm/lv2/capture#bundle` with the path of a JSON
  `{"bundle": …}` (what golem's compiler stores in `assets/.cache/capture-modules`, decoded from base64 by
  `bridge/engine/ardour.py` `write_captures`). The file is read and the model built in the worker thread; the plugin
  then announces the path on its notify port. Without a capture it outputs silence, as the CLAP reader does.
- It exports `lv2_descriptor` only: its NAM core must not share a registry with the NAM plugin loaded in the same
  engine ([pitfall](../../docs/pitfalls/plugins.md#linux-two-plugins-embedding-the-nam-core-share-one-registry)).

Build and install into `~/.lv2/golem-capture.lv2` (cmake, a C++20 compiler, the LV2 headers; network for the first
build, which clones the pinned NAM core):

```sh
./tools/build-capture-lv2.sh
```

Restart the engine afterwards.

**Bundled.** `bin/linux-x86_64.zip` holds the compiled bundle with the notices; `bin/manifest.json` pins the archive,
the binary and the sources (this folder's and the shared `../capture/engine.*`). `tools/package-capture-lv2.py` writes
both. golem's setup installs it with the CLAP reader (`provision/capture_player.py`, `install_lv2_bundled`) — verified
copy into `~/.lv2/golem-capture.lv2`, noted in the install receipt — **only where the Golem Engine is installed**:
REAPER plays the CLAP and needs no second reader in its LV2 list. Another architecture is not bundled and never builds
at launch: use the script above. The CLAP reader, its archives and their hashes are untouched.
