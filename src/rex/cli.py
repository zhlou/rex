from __future__ import annotations

import argparse
import curses
import locale

from rex.app import RexApp
from rex.remote import check_ssh_available


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="rex: remote explorer")
    parser.add_argument("host", help="SSH host, e.g. user@example.com")
    parser.add_argument("path", nargs="?", default=".", help="Remote start path")
    return parser.parse_args()


def main() -> None:
    locale.setlocale(locale.LC_ALL, "")
    args = parse_args()
    check_ssh_available()

    def wrapped(stdscr: curses.window) -> None:
        app = RexApp(stdscr=stdscr, host=args.host, start_path=args.path)
        app.run()

    curses.wrapper(wrapped)
