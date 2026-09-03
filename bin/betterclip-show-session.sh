#!/bin/bash
# GNOME custom shortcuts often run with almost no environment; rofi needs the
# same DISPLAY / WAYLAND_DISPLAY / XDG_RUNTIME_DIR as your graphical session.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  export "$line"
done < <(systemctl --user show-environment 2>/dev/null || true)
if [[ -x "$REPO_ROOT/.venv/bin/betterclip" ]]; then
  exec "$REPO_ROOT/.venv/bin/betterclip" show
fi
exec betterclip show
