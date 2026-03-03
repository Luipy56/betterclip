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

### 3. Super+V shortcut

On **GNOME/Ubuntu**:

1. Open *Settings* → *Keyboard* → *Custom shortcuts*
2. Click *+* to add
3. Name: `betterclip`
4. Command: `betterclip show` (or full path `~/.local/bin/betterclip show` if needed)
5. Shortcut: Super+V (or Ctrl+Alt+V if Super+V is taken)

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
  "hotkey": "Super+V"
}
```

- `max_items`: Maximum number of items in history (default: 50).
- `hotkey`: Documentation only; the shortcut is configured in the system.

## Data structure

- **History**: `~/.local/share/betterclip/history.json`
- **Config**: `~/.config/betterclip/config.json`

## Tests

```bash
cd /path/to/betterclip
PYTHONPATH=. python3 -m unittest discover -v
```

Runs 16 tests covering config, storage, clipboard, picker, utils and daemon.

## License

MIT. You can use and modify this code freely as long as you give credit.  
Author: [ldeluipy.es](https://ldeluipy.es)
