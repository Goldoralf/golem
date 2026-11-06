# Autostart — a dedicated box starts golem on its own

> **Status: CODED** — `golem autostart on|off|status` starts `golem server` at boot, with no login session
> (see [docs/installer.md](../../docs/installer.md)).

A golem has two uses: `golem desktop` (a window on the computer) and `golem server` (no window; a tablet or phone is the
screen). A dedicated box — the rack in the rehearsal room — is only an option on top: start `golem server` at boot.

```
BIOS auto-power-on
 └─ systemd
     ├─ golem-perf.service (system, harden.sh)    # CPU governor "performance"
     └─ user@<uid> (linger: no session needed)
         └─ golem-server.service (user, oneshot)  # provision/golem server
             ├─ bridge (uvicorn :8770)
             └─ REAPER on Xvfb :99                # no display needed
```

```bash
golem autostart on      # = ./provision/autostart/install-autostart.sh — also System ▸ Dashboard ▸ "Start golem with this computer"
golem autostart off     # removes the service; linger goes back to its value before golem (install receipt)
golem autostart status
```

Files: `units/golem-server.service` (user unit, `@ROOT@` replaced by the checkout path at install),
`system/golem-perf.service` (system unit, sets `performance` on every CPU at boot; no-op without cpufreq, e.g. in a VM).

**Autostart never hardens** (2026-10-16, [docs/installer.md](../../docs/installer.md) §4): `golem-perf.service` is installed
by `provision/harden.sh`, the separate "Lock down this machine" gesture (System ▸ Dashboard, Linux only), with the
firewall, frozen updates and USB autosuspend. Run from the app there is no terminal: linger is set with
`loginctl enable-linger` first (polkit allows it in an active session), then `sudo -n`; if both are refused the script
installs nothing and exits 3 with the reason.

Design points:

- **No session**: `loginctl enable-linger` makes the user's services start at boot. No autologin, no graphical session:
  REAPER runs on Xvfb (`provision/start.sh`, display `GOLEM_XVFB_DISPLAY`, default `:99`), as with `golem desktop`.
- **Sound card without a session**: with no logind seat, access to `/dev/snd` comes from the `audio` group (added by
  `provision/install.sh`). The install script warns when the user is not in it.
- **Leftovers of the old kiosk setup are cleaned** on activation (units `golem-kiosk/-reaper/-midi/-bridge`,
  `golem.target`, our Openbox autostart, the LightDM autologin drop-in). They are disabled without `--now`, so a golem
  that is playing is not cut.
- Logs: `journalctl --user -u golem-server`, then `/tmp/golem-bridge.log` and `/tmp/golem-reaper.log` (written by
  `provision/start.sh`).
