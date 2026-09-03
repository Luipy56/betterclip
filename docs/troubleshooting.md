# Troubleshooting

Typical issues are environment-related (systemd user services and desktop shortcuts do not automatically see your graphical session).

## Clipboard history stops updating (daemon not recording copies)

**Symptoms:** `betterclip show` still opens and shows old items, but new copies never appear. The daemon may restart in a loop or stay dead.

**Cause:** The systemd **user** unit runs with a minimal environment. Without `DISPLAY`, `WAYLAND_DISPLAY`, and related variables, the daemon cannot attach to the session clipboard stack. It may treat the session as plain X11 with an empty display and exit with an error such as:

```text
Xlib.error.DisplayNameError: Bad display name ""
```

**Fix:**

1. Ensure your unit passes the session variables from the user manager into the service. The sample unit in the repo includes:

   ```ini
   Environment=XDG_RUNTIME_DIR=%t
   PassEnvironment=WAYLAND_DISPLAY XDG_SESSION_TYPE DISPLAY
   ```

2. If you copied an older unit or wrote one by hand, merge in those lines (and reload):

   ```bash
   systemctl --user daemon-reload
   systemctl --user restart betterclip
   ```

3. On some setups (e.g. GNOME on Wayland with XWayland auth), also pass:

   ```ini
   PassEnvironment=WAYLAND_DISPLAY XDG_SESSION_TYPE DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS
   ```

4. Confirm the manager actually has the variables (after graphical login):

   ```bash
   systemctl --user show-environment | grep -E 'DISPLAY|WAYLAND|XDG_SESSION_TYPE'
   ```

5. Check logs:

   ```bash
   journalctl --user -u betterclip.service -b --no-pager
   ```

You should see a stable **active (running)** state; on GNOME Wayland you may see a message about using XFixes on XWayland when `wl-paste --watch` is not available.

---

## Super+V does nothing (custom shortcut never runs)

**Symptoms:** The notification tray no longer opens on Super+V (or never did), but betterclip’s picker also never appears. Settings shows your custom shortcut, yet pressing the key has no effect.

**Causes (common on GNOME/Ubuntu):**

1. **Super+V is still owned by the shell** (`toggle-message-tray`). `gsd-media-keys` then logs `Failed to grab accelerator for keybinding custom:...` and never runs your command.
2. **Command is wrong for a custom shortcut.** Bare `betterclip show` / `#!/usr/bin/env bash` can fail when GNOME launches with a minimal/`PATH`-less environment.
3. **`gsd-media-keys` is not running** (e.g. after it was killed). Custom shortcuts stop working until the MediaKeys target is started again.

**Fix:**

1. Free Super+V, then bind the session launcher with an absolute path:

   ```bash
   gsettings set org.gnome.shell.keybindings toggle-message-tray "['<Super>m']"
   # Command in Settings (or gsettings): /path/to/betterclip/bin/betterclip-show-session.sh
   # Binding: <Super>v   (fallback: <Control><Alt>v)
   ```

2. Confirm grab + daemon:

   ```bash
   journalctl --user -u org.gnome.SettingsDaemon.MediaKeys.service -b --no-pager | grep -i grab
   pgrep -a gsd-media-keys
   # If media-keys is dead:
   systemctl --user start org.gnome.SettingsDaemon.MediaKeys.target
   ```

3. Prefer `bin/betterclip-show-session.sh` over `betterclip show` so rofi inherits `DISPLAY` / `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR`.

---

## Super+V opens rofi but Escape does not close it

**Symptoms:** The picker appears, but keyboard shortcuts (e.g. Escape) do nothing until you click the rofi window.

**Cause:** GNOME **custom shortcuts** often run the command with almost no environment. `rofi` may open on XWayland without keyboard focus until the window is clicked.

**Fix:**

- Prefer launching the picker via `bin/betterclip-show-session.sh` (from your clone), which imports `systemctl --user show-environment` so `DISPLAY`, `WAYLAND_DISPLAY`, and `XDG_RUNTIME_DIR` match your session.
- In **Settings → Keyboard → Custom shortcuts**, set the command to the full path of that script, or to an equivalent wrapper that exports the same variables.

---

## Related files

| File | Purpose |
|------|---------|
| `systemd/betterclip.service` | Reference unit with `PassEnvironment` |
| `bin/betterclip-show-session.sh` | Session-aware launcher for `betterclip show` |

After changing `~/.config/systemd/user/betterclip.service`, always run `systemctl --user daemon-reload`.
