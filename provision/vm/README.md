# Install-test VMs

> **Status: CODED** — `vm.sh` (Ubuntu 24.04) and `win.sh` (Windows 11) make `provision/` testable on a disposable
> machine: snapshot a bare OS, run the install, note what breaks, restore, repeat.

## Linux VM — `vm.sh`

```bash
./provision/vm/vm.sh fetch          # Ubuntu 24.04 cloud image (~600 MB, once)
./provision/vm/vm.sh create         # VM 6 vCPU / 8 GB / 40 GB, test account from the cloud-init.yaml template
./provision/vm/vm.sh snap bare-os   # clean starting point
./provision/vm/vm.sh push           # rsync the repository → ~/golem in the VM
./provision/vm/vm.sh ssh './golem/provision/install.sh'
# ... something breaks? fix it IN THE REPOSITORY (never by hand in the VM), then:
./provision/vm/vm.sh restore bare-os && ./provision/vm/vm.sh push   # and replay
```

Other commands: `ip`, `status`, `snaps`, `stop`, `start`, `destroy`, `shot [png]`.

**Other distributions** (2026-11-03): `GOLEM_VM_DISTRO=debian12 | debian13 | mint22` in front of every command (default
`ubuntu`). Each distribution has its own VM (`golem-vm-<distro>`), its own image and its own credentials file, so they
can live side by side. Debian uses the official `genericcloud` images. Linux Mint publishes no cloud image and its
installer has no unattended mode: `mint22` is an Ubuntu 24.04 that `mintify.sh` turns into Mint where golem can see
it — snapd removed and blocked (`nosnap.pref`), the Mint repository with its priority (its real `chromium` package),
Mint's `os-release` and `lsb-release`. No Cinnamon, no desktop: an install test, not a full Mint.

```bash
GOLEM_VM_DISTRO=debian13 ./provision/vm/vm.sh fetch
GOLEM_VM_DISTRO=debian13 ./provision/vm/vm.sh create
GOLEM_VM_DISTRO=debian13 ./provision/vm/vm.sh push
GOLEM_VM_DISTRO=debian13 ./provision/vm/vm.sh ssh './golem/provision/install.sh --light'
```

### Archiving a VM off the machine — `vm-archive.sh`

```bash
./provision/vm/vm-archive.sh export golem-vm "/media/$USER/<disk>/VM"   # shuts the VM down cleanly, then copies it
./provision/vm/vm-archive.sh import "/media/$USER/<disk>/VM/golem-vm"   # recreates it as it was
```

Works for `golem-vm` and `golem-win` alike. What leaves: every volume of the `default` pool named after the VM (work
disk, qcow2 base or snapshot overlays, seed or answer ISO), the definition, the snapshots (their XML; their content —
disk, and RAM for live snapshots — lives inside the qcow2 files), the credentials file, a `MANIFEST` with size and
sha256 per volume, checked on import, and a `NOTE` saying what the archive holds.

A UEFI VM (`golem-win`) also has state **outside the pool, owned by root**: its firmware variables
(`/var/lib/libvirt/qemu/nvram/<vm>_VARS.fd` — Secure Boot, boot entries) and its emulated TPM
(`/var/lib/libvirt/swtpm/<uuid>/tpm2/`). The script still needs no sudo: it lays a **transient** libvirt pool over
each of those directories so that the daemon itself reads them (export, into `firmware/` + `MANIFEST.firmware`) and
writes them back (import, before `virsh define`; libvirt restores their owners when the VM starts). If they are
missing, libvirt starts from a blank variable store (the Microsoft Secure Boot keys come from its template; Windows
boots through the ESP fallback loader) and a new TPM — which Windows accepts because BitLocker is off
(`win/autounattend.xml` sets `PreventDeviceEncryption`; check with `win.sh ssh 'manage-bde -status C:'`). The VM
is **archived**, never run from the external disk: the libvirt system daemon cannot read `/media/<user>`, and a VM
disk on USB/NTFS would be slow and fragile.

- Everything goes through the **libvirt system daemon** (`qemu:///system`, `vol-create`/`vol-upload`): no sudo.
  Prerequisites: `qemu-kvm libvirt-daemon-system libvirt-clients virtinst cloud-image-utils` and membership of the
  `libvirt` group (otherwise prefix with `sg libvirt -c '…'`).
- **Test account.** `cloud-init.yaml` and `win/autounattend.xml` are templates: nothing personal is versioned. At
  `create`, the scripts substitute their `@GOLEM_VM_…@` tokens from the environment:

  | Variable | Default |
  |---|---|
  | `GOLEM_VM_USER` | `golem` |
  | `GOLEM_VM_PASSWORD` | generated (16 alphanumerics) and printed once |
  | `GOLEM_VM_SSH_KEY` | `~/.ssh/id_ed25519.pub` — a path to a `.pub` file, or the key text itself |

  The account is remembered in `~/.cache/golem-vm/<vm>.credentials` (mode 600, removed by `destroy`) so that `ssh`,
  `push` & co. log in as the right user; `GOLEM_VM_USER` overrides it (e.g. for a VM created before the templates).
  The password exists only for the rescue console (`virsh console golem-vm`) when the network dies — test VM only.
- Snapshots are **live** (disk + RAM). After a `restore`, SSH takes ~5–10 s to come back (ARP cache).
- `shot` captures the VM console as a PNG — the visual check of a boot without a screen.
- `push` honours `.gitignore` (what leaves is what a `git clone` would give, so no local state or secrets reach the VM)
  and also excludes `assets/`, `library/sfz/`, `.env`, `.venv`: in the VM, `fetch-assets.sh` downloads them, as on a
  new rack.
- Known limit: no WiFi radio and no USB audio in the VM — the access-point network and real-time audio are validated on
  real hardware.

## Windows 11 VM — `win.sh`

The counterpart of `vm.sh` for a **real** Windows machine (KVM, UEFI, Secure Boot, emulated TPM), installed without a
click and driven from the host. It validates the desktop port ([docs/platforms.md](../../docs/platforms.md)).

```bash
./provision/vm/win.sh fetch            # Windows 11 Enterprise evaluation ISO (8 GB) + OpenSSH
./provision/vm/win.sh create           # unattended install (~20–30 min), then:
./provision/vm/win.sh wait
./provision/vm/win.sh snap bare-windows
./provision/vm/win.sh tools            # Python 3.12, REAPER, NAM VST3, ffmpeg, Node (versions pinned in win/tools.ps1)
./provision/vm/win.sh snap tooled      # ← the starting point of every test
./provision/vm/win.sh push [ref]       # repository → C:\golem (or one commit: the head of a PR)
./provision/vm/win.sh ssh 'cd /d C:\golem & python -m provision.desktop setup'
./provision/vm/win.sh gui 'python -m provision.desktop start'   # INSIDE the graphical session
./provision/vm/win.sh shot             # what the screen shows
./provision/vm/win.sh dialog           # REAPER's dialog boxes; `dialog reaper '&No'` clicks a button
./provision/vm/win.sh restore tooled   # and replay
```

Other commands: `ps '<powershell>'`, `view` (virt-viewer, for a human), `usb`, `status`, `snaps`, `ip`, `stop`, `start`,
`destroy`. Prerequisites: those of `vm.sh` plus `swtpm` and `genisoimage`.

**On a tight host** (a rack that plays, another VM, little room on `/`):

| Variable | Default | Effect |
|---|---|---|
| `GOLEM_VM_RAM_MB` | `8192` | memory given to the VM at `create` (6144 is enough for the tests) |
| `GOLEM_VM_VCPUS` | `6` | vCPUs at `create` |
| `GOLEM_VM_ISO_DIR` | `~/.cache/golem-vm` | where `fetch` puts the 8 GB ISO and the OpenSSH msi, and where `create` reads them (an external disk) — pass it to both |
| `GOLEM_VM_ISO_HTTP` | `0` | `1`: `create` does **not** copy the ISO into the libvirt pool (8 GB on `/`); `iso-http.py` serves it on `127.0.0.1` with Range requests and QEMU reads it as a network DVD. `wait` ejects the DVDs and stops the server |

```bash
export GOLEM_VM_ISO_DIR="/media/$USER/<disk>/VM/iso" GOLEM_VM_RAM_MB=6144 GOLEM_VM_VCPUS=4
./provision/vm/win.sh fetch && GOLEM_VM_ISO_HTTP=1 ./provision/vm/win.sh create && ./provision/vm/win.sh wait
```

Disk: the installed system takes ~15.3 GiB in the pool; the `bare-windows` → `tooled` overlay adds ~2.9 GiB.

- **Test account**: same variables and credentials file as `vm.sh` (the password is written in plain text on the
  answer ISO: test VM only); the session opens automatically, NAT network only. `create` installs the public key as
  the administrators' authorized key.
  The Microsoft evaluation lasts **90 days** from install: after that, `destroy` then `create`.
- **An SSH session has no desktop.** REAPER started over `ssh` has neither a window nor audio; anything graphical goes
  through `gui` (an interactive scheduled task). `gui` returns immediately: `shot`, or a file written by the command,
  tells what happened.
- **Snapshots are taken powered off, disk only**: libvirt cannot snapshot a running UEFI VM. `snap` shuts down,
  `restore` discards the current state and restarts (~1 min).
- **`push` without rsync** (Windows has none): a tar archive over SSH. Without an argument, the working tree as git sees
  it; with a ref, that exact commit. `GOLEM_PUSH_REPO=<clone>` pushes from another clone, so a PR can be tested without
  touching this checkout.
- **Lending a USB device** (sound card, keyboard): `win.sh usb <vid:pid>`, then `win.sh usb <vid:pid> off`. ⚠ The host
  loses the device while it is lent, and a REAPER that held the card goes silent without saying so (the bridge runs
  `audio_reset` on its own when the card comes back). Some interfaces expose no MIDI port to Windows without their
  vendor driver.
- **What the VM does not tell**: latency, dropouts, an engine stall when a block is switched on, the sound by ear.
  Without a lent card, REAPER shows "audio device closed". Real-time behaviour is measured on Windows without a
  hypervisor.
- **Importing an archive** (`vm-archive.sh import`) redefines the snapshots parent first (read from their XML): in
  file-name order a child came before its parent, libvirt refused it, only one snapshot came back — and the next
  `restore` crashed the libvirt daemon (2026-10-24).
- Construction traps are documented in the files themselves: REAPER's silent installer returns 1223 after installing
  everything (`win/tools.ps1`); Windows Setup's Cancel button has focus when you "press a key" to boot from the DVD
  (`win.sh create`); a snapshot without `--diskspec` embeds the DVDs.
