from __future__ import annotations

import argparse
import curses
import locale
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List


def build_remote_sh_command(command: str) -> str:
    return f"sh -lc {shlex.quote(command)}"


@dataclass
class RemoteEntry:
    name: str
    is_dir: bool


class RexApp:
    def __init__(self, stdscr: curses.window | None, host: str, start_path: str = ".") -> None:
        self.stdscr = stdscr
        self.host = host
        self.cwd = self._normalize_remote_path(start_path)
        self.entries: List[RemoteEntry] = []
        self.selected = 0
        self.top_index = 0
        self.message = ""
        self.focus = "browser"  # browser | command

        self.command_visible = False
        self.command_input = ""
        self.command_cursor = 0
        self.command_lines: List[str] = []
        self.max_command_lines = 2000
        self.command_history: List[str] = []
        self.command_history_index: int | None = None
        self._history_stash = ""
        self.command_scroll = 0
        self.command_search_mode = False
        self.command_search_query = ""
        self.command_search_matches: List[int] = []
        self.command_search_pos = -1

    def run(self) -> None:
        if self.stdscr is None:
            raise RuntimeError("stdscr is required to run RexApp")

        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(50)
        self.stdscr.keypad(True)
        self._reload_entries()

        while True:
            self._draw()
            key = self.stdscr.getch()
            if key == -1:
                continue
            if not self._handle_key(key):
                break

    def _run_ssh(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["ssh", self.host, build_remote_sh_command(command)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _list_remote_dir(self, target_path: str) -> tuple[str | None, List[RemoteEntry] | None, str | None]:
        cmd = f"cd -- {shlex.quote(target_path)} && pwd -P && LC_ALL=C ls -1Ap"
        try:
            result = self._run_ssh(cmd)
        except subprocess.TimeoutExpired:
            return None, None, "Listing timed out"

        if result.returncode != 0:
            err = result.stderr.strip() or "failed to list directory"
            return None, None, f"Error: {err}"

        lines = result.stdout.splitlines()
        if not lines:
            return None, None, "Error: empty response while listing directory"

        resolved_cwd = lines[0].strip() or target_path
        raw = [line for line in lines[1:] if line]
        parsed: List[RemoteEntry] = [RemoteEntry("..", True)]
        for item in raw:
            is_dir = item.endswith("/")
            name = item[:-1] if is_dir else item
            parsed.append(RemoteEntry(name=name, is_dir=is_dir))

        return resolved_cwd, parsed, None

    def _reload_entries(self) -> None:
        resolved_cwd, parsed, err = self._list_remote_dir(self.cwd)
        if err is not None or parsed is None or resolved_cwd is None:
            self.message = err or "Error: failed to list directory"
            return

        self.cwd = resolved_cwd
        self.entries = parsed
        self.selected = 0
        self.top_index = 0
        self.message = f"Loaded {len(parsed)-1} entries"

    def _normalize_remote_path(self, path: str) -> str:
        p = PurePosixPath(path)
        if not p.is_absolute():
            p = PurePosixPath(".") / p
        text = str(p)
        return text if text else "."

    def _current_entry(self) -> RemoteEntry | None:
        if not self.entries:
            return None
        return self.entries[self.selected]

    def _move_selection(self, delta: int) -> None:
        if not self.entries:
            return
        self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def _move_selection_grid(self, d_row: int, d_col: int) -> None:
        if not self.entries:
            return

        browser_h, browser_w = self._browser_pane_dimensions()
        rows, _, _, _ = self._browser_layout(browser_h, browser_w)
        if rows <= 0:
            return

        delta = d_row + (d_col * rows)
        if delta == 0:
            return
        target = self.selected + delta
        if target < 0 or target >= len(self.entries):
            return
        self.selected = target

    def _command_block_height(self, total_height: int) -> int:
        return max(3, total_height // 4)

    def _browser_pane_dimensions(self) -> tuple[int, int]:
        if self.stdscr is None:
            return 1, 1
        h, w = self.stdscr.getmaxyx()
        content_h = max(1, h - 3)
        browser_h = content_h
        if self.command_visible:
            command_h = min(content_h - 1, self._command_block_height(content_h))
            browser_h = max(1, content_h - command_h)
        return max(1, browser_h - 1), max(1, w)

    def _enter_selected(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return

        if entry.name == "..":
            self._change_directory(str(PurePosixPath(self.cwd).parent) or "/")
            return

        target = str(PurePosixPath(self.cwd) / entry.name)
        if self._change_directory(target):
            return

        self.message = f"Not a directory: {entry.name}. Opening file."
        self._open_file(entry.name)

    def _change_directory(self, target_path: str) -> bool:
        old_cwd = self.cwd
        resolved_cwd, parsed, err = self._list_remote_dir(target_path)
        if err is not None or parsed is None or resolved_cwd is None:
            self.message = err or "Failed to change directory"
            return False

        self.cwd = resolved_cwd
        self.entries = parsed
        self.selected = 0
        self.top_index = 0
        if old_cwd != self.cwd:
            self.message = f"Entered {self.cwd} ({len(parsed)-1} entries)"
        else:
            self.message = f"Staying in {self.cwd} ({len(parsed)-1} entries)"
        return True

    def _open_file(self, filename: str) -> None:
        cmd = (
            f"cd -- {shlex.quote(self.cwd)} && "
            f"if command -v less >/dev/null 2>&1; then less -- {shlex.quote(filename)}; "
            f"else cat -- {shlex.quote(filename)}; fi"
        )
        self._run_fullscreen_ssh(cmd)

    def _edit_file(self, filename: str) -> None:
        editor_value = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        try:
            editor_argv = shlex.split(editor_value)
        except ValueError:
            editor_argv = ["vi"]
        if not editor_argv:
            editor_argv = ["vi"]
        editor_cmd = " ".join(shlex.quote(arg) for arg in editor_argv)
        cmd = f"cd -- {shlex.quote(self.cwd)} && {editor_cmd} -- {shlex.quote(filename)}"
        self._run_fullscreen_ssh(cmd)

    def _run_fullscreen_ssh(self, remote_command: str) -> None:
        if self.stdscr is None:
            subprocess.run(["ssh", "-t", self.host, build_remote_sh_command(remote_command)], check=False)
            return

        curses.def_prog_mode()
        curses.endwin()
        try:
            subprocess.run(["ssh", "-t", self.host, build_remote_sh_command(remote_command)], check=False)
        finally:
            curses.reset_prog_mode()
            curses.curs_set(0)
            self.stdscr.nodelay(True)
            self.stdscr.timeout(50)
            self.stdscr.keypad(True)
            self._reload_entries()

    def _show_command_panel(self) -> None:
        self.command_visible = True
        self.focus = "command"
        self.command_history_index = None
        self._history_stash = ""
        self.command_input = ""
        self.command_cursor = 0
        self.command_lines.clear()
        self.command_scroll = 0
        self.command_search_mode = False
        self.command_search_query = ""
        self.command_search_matches = []
        self.command_search_pos = -1
        self.message = f"Run command in {self.cwd}"

    def _hide_command_panel(self) -> None:
        self.focus = "browser"
        self.command_visible = False
        self.command_history_index = None
        self._history_stash = ""
        self.command_search_mode = False

    def _append_command_line(self, line: str) -> None:
        was_bottom = self.command_scroll == 0
        self.command_lines.append(line)
        if len(self.command_lines) > self.max_command_lines:
            self.command_lines = self.command_lines[-self.max_command_lines :]
        if was_bottom:
            self.command_scroll = 0
        self._refresh_search_matches()

    def _execute_command_input(self) -> None:
        user_cmd = self.command_input.strip()
        if not user_cmd:
            self.message = "Empty command"
            return

        if not self.command_history or self.command_history[-1] != user_cmd:
            self.command_history.append(user_cmd)
        self.command_history_index = None
        self._history_stash = ""

        self._append_command_line(f"$ {user_cmd}")
        remote = f"cd -- {shlex.quote(self.cwd)} && {user_cmd}"
        self.command_scroll = 0
        try:
            result = self._run_ssh(remote, timeout=60)
        except subprocess.TimeoutExpired:
            self._append_command_line("[timed out]")
            self.message = "Command timed out"
            self.command_input = ""
            self.command_cursor = 0
            return

        out_lines = result.stdout.splitlines()
        err_lines = result.stderr.splitlines()
        if not out_lines and not err_lines:
            self._append_command_line("[no output]")
        else:
            for line in out_lines:
                self._append_command_line(line)
            for line in err_lines:
                self._append_command_line(f"stderr: {line}")

        if result.returncode != 0:
            self._append_command_line(f"[exit {result.returncode}]")
            self.message = f"Command failed ({result.returncode})"
        else:
            self.message = "Command finished"

        self.command_input = ""
        self.command_cursor = 0

    def _command_output_rows(self) -> int:
        if self.stdscr is None or not self.command_visible:
            return 0
        h, _ = self.stdscr.getmaxyx()
        content_h = max(1, h - 3)
        command_block_h = min(content_h - 1, self._command_block_height(content_h))
        panel_h = max(1, command_block_h - 1)
        return max(0, panel_h - 1)

    def _command_max_scroll(self) -> int:
        output_rows = self._command_output_rows()
        if output_rows <= 0:
            return 0
        return max(0, len(self.command_lines) - output_rows)

    def _clamp_command_scroll(self) -> None:
        self.command_scroll = max(0, min(self.command_scroll, self._command_max_scroll()))

    def _refresh_search_matches(self) -> None:
        query = self.command_search_query.strip().lower()
        if not query:
            self.command_search_matches = []
            self.command_search_pos = -1
            return
        self.command_search_matches = [i for i, line in enumerate(self.command_lines) if query in line.lower()]
        if not self.command_search_matches:
            self.command_search_pos = -1
        elif self.command_search_pos < 0 or self.command_search_pos >= len(self.command_search_matches):
            self.command_search_pos = 0

    def _scroll_to_line(self, line_idx: int) -> None:
        output_rows = self._command_output_rows()
        if output_rows <= 0:
            self.command_scroll = 0
            return
        total = len(self.command_lines)
        line_idx = max(0, min(total - 1, line_idx))
        desired_start = max(0, line_idx - (output_rows // 2))
        desired_end = min(total, desired_start + output_rows)
        desired_start = max(0, desired_end - output_rows)
        self.command_scroll = max(0, total - desired_end)
        self._clamp_command_scroll()

    def _jump_search(self, direction: int) -> None:
        if not self.command_search_matches:
            self.message = "No search matches"
            return
        if self.command_search_pos < 0:
            self.command_search_pos = 0 if direction >= 0 else len(self.command_search_matches) - 1
        else:
            self.command_search_pos = (self.command_search_pos + direction) % len(self.command_search_matches)
        line_idx = self.command_search_matches[self.command_search_pos]
        self._scroll_to_line(line_idx)
        self.message = (
            f"Match {self.command_search_pos + 1}/{len(self.command_search_matches)}"
            f" for '{self.command_search_query}'"
        )

    def _handle_search_key(self, key: int) -> bool:
        if key in (27,):  # ESC
            self.command_search_mode = False
            self.message = "Search cancelled"
            return True
        if key in (curses.KEY_ENTER, 10, 13):
            self.command_search_mode = False
            self._refresh_search_matches()
            if not self.command_search_matches:
                self.message = f"No matches for '{self.command_search_query}'"
                return True
            self.command_search_pos = -1
            self._jump_search(1)
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.command_search_query:
                self.command_search_query = self.command_search_query[:-1]
            return True
        if key == 21:  # Ctrl-u
            self.command_search_query = ""
            return True
        if 32 <= key <= 126:
            self.command_search_query += chr(key)
            return True
        return True

    def _set_command_from_history(self, direction: int) -> None:
        if not self.command_history:
            return

        if self.command_history_index is None:
            self._history_stash = self.command_input
            self.command_history_index = len(self.command_history)

        next_idx = self.command_history_index + direction
        next_idx = max(0, min(len(self.command_history), next_idx))
        self.command_history_index = next_idx

        if self.command_history_index == len(self.command_history):
            self.command_input = self._history_stash
        else:
            self.command_input = self.command_history[self.command_history_index]
        self.command_cursor = len(self.command_input)

    def _handle_command_key(self, key: int) -> bool:
        if self.command_search_mode:
            return self._handle_search_key(key)

        if key in (27, 29):  # ESC, Ctrl-]
            self._hide_command_panel()
            return True
        if key in (ord("/"),):
            self.command_search_mode = True
            self.message = "Search output (/ then Enter, ESC cancel, n/N navigate)"
            return True
        if key in (ord("n"),):
            self._refresh_search_matches()
            self._jump_search(1)
            return True
        if key in (ord("N"),):
            self._refresh_search_matches()
            self._jump_search(-1)
            return True
        if key in (curses.KEY_PPAGE,):
            step = max(1, self._command_output_rows())
            self.command_scroll += step
            self._clamp_command_scroll()
            return True
        if key in (curses.KEY_NPAGE,):
            step = max(1, self._command_output_rows())
            self.command_scroll -= step
            self._clamp_command_scroll()
            return True
        if key in (curses.KEY_ENTER, 10, 13):
            self._execute_command_input()
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.command_cursor > 0:
                self.command_input = (
                    self.command_input[: self.command_cursor - 1] + self.command_input[self.command_cursor :]
                )
                self.command_cursor -= 1
            return True
        if key in (curses.KEY_DC,):
            if self.command_cursor < len(self.command_input):
                self.command_input = (
                    self.command_input[: self.command_cursor] + self.command_input[self.command_cursor + 1 :]
                )
            return True
        if key in (curses.KEY_LEFT,):
            self.command_cursor = max(0, self.command_cursor - 1)
            return True
        if key in (curses.KEY_RIGHT,):
            self.command_cursor = min(len(self.command_input), self.command_cursor + 1)
            return True
        if key in (curses.KEY_HOME,):
            self.command_cursor = 0
            return True
        if key in (curses.KEY_END,):
            self.command_cursor = len(self.command_input)
            return True
        if key in (curses.KEY_UP,):
            self._set_command_from_history(-1)
            return True
        if key in (curses.KEY_DOWN,):
            self._set_command_from_history(1)
            return True
        if key == 21:  # Ctrl-u
            self.command_input = self.command_input[self.command_cursor :]
            self.command_cursor = 0
            return True
        if 32 <= key <= 126:
            ch = chr(key)
            self.command_input = self.command_input[: self.command_cursor] + ch + self.command_input[self.command_cursor :]
            self.command_cursor += 1
            return True
        return True

    def _handle_key(self, key: int) -> bool:
        if key in (ord("q"), ord("Q")):
            return False

        if key in (curses.KEY_RESIZE,):
            return True

        if self.focus == "command":
            return self._handle_command_key(key)

        if key in (curses.KEY_UP, ord("k")):
            self._move_selection_grid(-1, 0)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_selection_grid(1, 0)
        elif key in (curses.KEY_LEFT, ord("h")):
            self._move_selection_grid(0, -1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            self._move_selection_grid(0, 1)
        elif key in (curses.KEY_NPAGE,):
            self._move_selection(10)
        elif key in (curses.KEY_PPAGE,):
            self._move_selection(-10)
        elif key in (curses.KEY_ENTER, 10, 13):
            self._enter_selected()
        elif key in (ord("p"),):
            if not self._change_directory(str(PurePosixPath(self.cwd).parent) or "/"):
                self.message = "Error: failed to change to parent directory"
        elif key in (ord("r"),):
            self._reload_entries()
        elif key in (ord("e"),):
            entry = self._current_entry()
            if entry and not entry.is_dir and entry.name != "..":
                self._edit_file(entry.name)
        elif key in (ord("o"),):
            entry = self._current_entry()
            if entry and not entry.is_dir and entry.name != "..":
                self._open_file(entry.name)
        elif key in (ord(":"), ord("s"), ord("S")):
            self._show_command_panel()

        self._ensure_visible()
        return True

    def _ensure_visible(self) -> None:
        browser_h, browser_w = self._browser_pane_dimensions()
        _, _, _, page_size = self._browser_layout(browser_h, browser_w)
        if page_size <= 0:
            return

        if self.selected < self.top_index or self.selected >= self.top_index + page_size:
            self.top_index = (self.selected // page_size) * page_size
        max_start = 0
        if self.entries:
            max_start = ((len(self.entries) - 1) // page_size) * page_size
        self.top_index = min(self.top_index, max_start)

    def _browser_layout(self, height: int, width: int) -> tuple[int, int, int, int]:
        rows = max(1, height)
        usable_width = max(1, width - 1)

        max_label = 2
        for entry in self.entries:
            marker = 1 if entry.is_dir else 0
            max_label = max(max_label, len(entry.name) + marker)

        column_width = max(4, min(usable_width, max_label + 2))
        cols = max(1, usable_width // column_width)
        if cols > 1:
            column_width = max(4, usable_width // cols)
        page_size = rows * cols
        return rows, column_width, cols, page_size

    def _draw(self) -> None:
        if self.stdscr is None:
            return

        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        browser_focus = "*" if self.focus == "browser" else " "
        command_focus = "*" if self.focus == "command" else " "

        header = f"{browser_focus} rex  host={self.host}  cwd={self.cwd}"
        self.stdscr.addnstr(0, 0, header, w - 1, curses.A_BOLD)

        content_h = max(1, h - 3)
        browser_block_h = content_h
        command_block_h = 0
        if self.command_visible:
            command_block_h = min(content_h - 1, self._command_block_height(content_h))
            browser_block_h = max(1, content_h - command_block_h)

        self.stdscr.addnstr(1, 0, "Files", w - 1, curses.A_UNDERLINE)
        self._draw_entries(2, 0, max(1, browser_block_h - 1), w)

        cursor_pos = None
        if self.command_visible:
            panel_title_y = 1 + browser_block_h
            self.stdscr.hline(panel_title_y - 1, 0, ord("-"), w)
            self.stdscr.addnstr(
                panel_title_y,
                0,
                f"{command_focus} Run Command (Enter run | PgUp/PgDn scroll | / search | Esc dismiss)",
                w - 1,
                curses.A_UNDERLINE,
            )
            cursor_pos = self._draw_command_panel(panel_title_y + 1, 0, max(1, command_block_h - 1), w)

        footer = (
            "q quit | arrows/hjkl move | enter open/dir | p parent | e edit | o view | "
            "s/: run command | pgup/pgdn scroll | / search"
        )
        self.stdscr.addnstr(h - 2, 0, footer, w - 1, curses.A_DIM)
        self.stdscr.addnstr(h - 1, 0, self.message, w - 1, curses.A_BOLD)

        if self.focus == "command" and cursor_pos is not None:
            cy, cx = cursor_pos
            try:
                curses.curs_set(1)
            except curses.error:
                pass
            self.stdscr.move(cy, cx)
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

        self.stdscr.refresh()

    def _draw_entries(self, y: int, x: int, height: int, width: int) -> None:
        if self.stdscr is None or height <= 0 or width <= 1:
            return

        rows, column_width, _, page_size = self._browser_layout(height, width)
        visible = self.entries[self.top_index : self.top_index + page_size]
        for i, entry in enumerate(visible):
            idx = self.top_index + i
            row = i % rows
            col = i // rows
            draw_x = x + col * column_width
            if draw_x >= x + width - 1:
                continue
            marker = "/" if entry.is_dir else ""
            line = f"{entry.name}{marker}"
            attr = curses.A_REVERSE if idx == self.selected and self.focus == "browser" else curses.A_NORMAL
            self.stdscr.addnstr(y + row, draw_x, line, max(1, column_width - 1), attr)

    def _draw_command_panel(self, y: int, x: int, height: int, width: int) -> tuple[int, int] | None:
        if self.stdscr is None or height <= 0 or width <= 1:
            return None

        output_rows = max(0, height - 1)
        self._clamp_command_scroll()
        if output_rows > 0:
            end = max(0, len(self.command_lines) - self.command_scroll)
            start = max(0, end - output_rows)
            lines = self.command_lines[start:end]
        else:
            lines = []
        for i, line in enumerate(lines):
            self.stdscr.addnstr(y + i, x, line, width - 1)

        input_y = y + max(0, height - 1)
        prompt = "/ " if self.command_search_mode else "> "
        prompt_w = len(prompt)
        avail = max(0, width - 1 - prompt_w)
        text = self.command_search_query if self.command_search_mode else self.command_input
        cursor = len(text) if self.command_search_mode else self.command_cursor

        scroll = 0
        if cursor > avail:
            scroll = cursor - avail
        visible_input = text[scroll : scroll + avail]

        self.stdscr.addnstr(input_y, x, prompt, width - 1, curses.A_BOLD)
        self.stdscr.addnstr(input_y, x + prompt_w, visible_input, max(0, width - 1 - prompt_w))
        cursor_x = x + prompt_w + min(max(0, cursor - scroll), max(0, avail))
        cursor_x = min(cursor_x, x + width - 2)
        return (input_y, cursor_x)


def _check_ssh_available() -> None:
    if not shutil_which("ssh"):
        raise SystemExit("ssh binary not found in PATH")


def shutil_which(name: str) -> str | None:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="rex: remote explorer")
    parser.add_argument("host", help="SSH host, e.g. user@example.com")
    parser.add_argument("path", nargs="?", default=".", help="Remote start path")
    return parser.parse_args()


def main() -> None:
    locale.setlocale(locale.LC_ALL, "")
    args = parse_args()
    _check_ssh_available()

    def wrapped(stdscr: curses.window) -> None:
        app = RexApp(stdscr=stdscr, host=args.host, start_path=args.path)
        app.run()

    curses.wrapper(wrapped)


if __name__ == "__main__":
    main()
