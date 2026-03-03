"""Entry point for betterclip daemon and show commands."""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("daemon", "show"):
        print("Usage: betterclip daemon | show", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "daemon":
        from .daemon import run_daemon
        run_daemon()

    elif cmd == "show":
        from .picker import run_picker
        ok = run_picker()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
