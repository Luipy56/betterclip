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
