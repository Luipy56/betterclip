# betterclip

Clipboard manager for Linux (Wayland/X11), Windows+V style.

## Features

- **Automatic capture**: Records text when you copy (Ctrl+C, Ctrl+Shift+C, right-click → Copy). Mouse selection is not recorded to avoid duplicate or partial entries.
- **Configurable history**: Stores up to N items (default 50).
- **Picker with shortcut**: Super+V opens the history in rofi to choose what to paste.
- **Compatibility**: Wayland (Ubuntu 24.04 default) and X11.

## Dependencies

Install on Ubuntu:

```bash
sudo apt install wl-clipboard xsel python3-xlib rofi
```

| Package        | Use                                |
| -------------- | ---------------------------------- |
| `wl-clipboard` | Wayland: wl-paste, wl-copy         |
| `xsel`         | X11: read/write clipboard          |
| `python3-xlib` | X11: change monitoring             |
| `rofi`         | History picker                     |

## Installation

```bash
# Option 1: With pip (in a venv)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Option 2: Without installing, from the project directory
PYTHONPATH=. python3 -m betterclip daemon
PYTHONPATH=. python3 -m betterclip show
```

## Usage

### 1. Start the daemon

Run in the background so it monitors the clipboard:

```bash
betterclip daemon
```

### 2. Configure autostart (systemd user)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/betterclip.service ~/.config/systemd/user/

# Edit ExecStart if you use venv or PYTHONPATH:
# ExecStart=/path/to/project/.venv/bin/python -m betterclip daemon
# Or with PYTHONPATH:
# ExecStart=/usr/bin/env bash -c 'cd /path/to/project && PYTHONPATH=. python3 -m betterclip daemon'

systemctl --user daemon-reload
systemctl --user enable betterclip
systemctl --user start betterclip
```

Keep the `PassEnvironment` / `Environment` lines from the sample unit so the daemon inherits `DISPLAY` and `WAYLAND_DISPLAY` (see [docs/troubleshooting.md](docs/troubleshooting.md)).

### 3. Super+V shortcut (GNOME/Ubuntu)

`hotkey` in `config.json` is documentation only — GNOME must own the real binding.

**Free Super+V first.** On Ubuntu, GNOME already uses Super+V for the notification tray. If you bind betterclip without freeing it, `gsd-media-keys` logs `Failed to grab accelerator` for your custom shortcut and Super+V does nothing useful:

```bash
# Keep the tray on Super+M only
gsettings set org.gnome.shell.keybindings toggle-message-tray "['<Super>m']"
```

**Use the session launcher as the command** (not bare `betterclip show`). GNOME custom shortcuts often run with an empty/`PATH`-less environment; `bin/betterclip-show-session.sh` imports your graphical session env and then runs the picker:

```bash
# Absolute path to the script in your clone (shebang is #!/bin/bash)
/path/to/betterclip/bin/betterclip-show-session.sh
```

Then in *Settings* → *Keyboard* → *Custom shortcuts* → *+*:

1. Name: `betterclip`
2. Command: the absolute path above
3. Shortcut: Super+V (or Ctrl+Alt+V if Super+V still fails to grab)

Optional CLI equivalent:

```bash
SCHEMA=org.gnome.settings-daemon.plugins.media-keys
BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
KEY="$BASE/custom0/"
SCRIPT="/path/to/betterclip/bin/betterclip-show-session.sh"

gsettings set org.gnome.shell.keybindings toggle-message-tray "['<Super>m']"
gsettings set $SCHEMA custom-keybindings "['$KEY']"
gsettings set $SCHEMA.custom-keybinding:$KEY name 'betterclip'
gsettings set $SCHEMA.custom-keybinding:$KEY command "$SCRIPT"
gsettings set $SCHEMA.custom-keybinding:$KEY binding '<Super>v'
```

If Super+V still does nothing, check `journalctl --user -u org.gnome.SettingsDaemon.MediaKeys.service` for grab failures, confirm `gsd-media-keys` is running, and see [docs/troubleshooting.md](docs/troubleshooting.md).

### 4. Workflow

1. Copy text as usual (Ctrl+C or mouse selection).
2. Press Super+V to open the history.
3. Use rofi to search and pick an item.
4. Press Enter: the text is copied to the clipboard.
5. Paste wherever you want with Ctrl+V.

## Configuration

File `~/.config/betterclip/config.json`:

```json
{
  "max_items": 50,
  "hotkey": "Super+V",
  "cli_mode": false,
  "theme": "modern_mac"
}
```

- `max_items`: Maximum number of items in history (default: 50).
- `hotkey`: Documentation only; the shortcut is configured in the system (see Super+V section above).
- `cli_mode`: If `true`, `betterclip show` uses a terminal picker (numbered list + stdin) instead of rofi, and prints the selected text to stdout. Use on servers or over SSH where there is no display; you can pipe the output (e.g. `betterclip show | xclip -i -b` on a machine with X11).
- `theme`: Rofi picker look. Default is `modern_mac` — light “Modern Mac” style (bundled theme file): pager scroll mode, no in-theme scrollbar. `classic` — stock rofi appearance. On Wayland, the picker always uses `-normal-window` and `-steal-focus` so Super+V can type without an extra click. Unknown values fall back to `modern_mac`.

## Data structure

- **History**: `~/.local/share/betterclip/history.json`
- **Config**: `~/.config/betterclip/config.json`

## Tests

```bash
cd /path/to/betterclip
PYTHONPATH=. python3 -m unittest discover -v
```

Runs 24 tests covering config, storage, clipboard, picker, utils, daemon, and rofi theme assets.

## Troubleshooting

See **[docs/troubleshooting.md](docs/troubleshooting.md)** for common fixes (systemd clipboard environment, rofi/Escape focus on GNOME, etc.).

## License

MIT. You can use and modify this code freely as long as you give credit.  
Author: [ldeluipy.es](https://ldeluipy.es)
