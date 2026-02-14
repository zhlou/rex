from __future__ import annotations

import argparse
import curses
import errno
import fcntl
import locale
import os
import pty
import re
import select
import shlex
import signal
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
    def __init__(self, stdscr: curses.window, host: str, start_path: str = ".") -> None:
        self.stdscr = stdscr
        self.host = host
        self.cwd = self._normalize_remote_path(start_path)
        self.entries: List[RemoteEntry] = []
        self.selected = 0
        self.top_index = 0
        self.message = ""
        self.focus = "browser"  # browser | shell

        self.shell_pid: int | None = None
        self.shell_fd: int | None = None
        self.shell_lines: List[str] = []
        self.max_shell_lines = 2000
        self._shell_partial = ""
        self._pair_cache: dict[tuple[int, int], int] = {}
        self._next_pair = 1
        self._supports_color = False

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(50)
        self.stdscr.keypad(True)
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            self._supports_color = True

        self._start_shell()
        self._reload_entries()

        try:
            while True:
                self._drain_shell_output()
                self._draw()
                key = self.stdscr.getch()
                if key == -1:
                    continue
                if not self._handle_key(key):
                    break
        finally:
            self._stop_shell()

    def _run_ssh(self, command: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["ssh", self.host, build_remote_sh_command(command)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _list_remote_dir(self, target_path: str) -> tuple[str | None, List[RemoteEntry] | None, str | None]:
        # Print physical cwd first so we can keep browser state synced to what remote shell resolved.
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
        editor = os.environ.get("EDITOR", "vi")
        cmd = f"cd -- {shlex.quote(self.cwd)} && {editor} -- {shlex.quote(filename)}"
        self._run_fullscreen_ssh(cmd)

    def _run_fullscreen_ssh(self, remote_command: str) -> None:
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

    def _prompt(self, label: str) -> str | None:
        h, w = self.stdscr.getmaxyx()
        win = curses.newwin(1, w, h - 1, 0)
        win.erase()
        win.addstr(0, 0, label[: max(0, w - 1)])
        curses.echo()
        curses.curs_set(1)
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            text = win.getstr(0, min(len(label), max(0, w - 1)), max(0, w - len(label) - 1))
            return text.decode("utf-8", errors="ignore").strip()
        except curses.error:
            return None
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.stdscr.nodelay(True)
            self.stdscr.timeout(50)

    def _run_oneoff_command(self) -> None:
        user_cmd = self._prompt("Run in cwd> ")
        if not user_cmd:
            self.message = "Cancelled"
            return

        cmd = f"cd -- {shlex.quote(self.cwd)} && {user_cmd}"
        self._run_fullscreen_ssh(cmd)
        self.message = "Command finished"

    def _start_shell(self) -> None:
        if self.shell_fd is not None:
            return

        pid, fd = pty.fork()
        if pid == 0:
            shell = os.environ.get("SHELL", "/bin/sh")
            cmd = f"cd -- {shlex.quote(self.cwd)} && exec $SHELL -l"
            os.execvp("ssh", ["ssh", "-tt", self.host, build_remote_sh_command(cmd)])

        self.shell_pid = pid
        self.shell_fd = fd
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def _restart_shell(self) -> None:
        self._stop_shell()
        self.shell_lines.clear()
        self._shell_partial = ""
        self._start_shell()

    def _stop_shell(self) -> None:
        if self.shell_fd is not None:
            try:
                os.close(self.shell_fd)
            except OSError:
                pass
            self.shell_fd = None

        if self.shell_pid is not None:
            try:
                os.kill(self.shell_pid, signal.SIGTERM)
            except OSError as e:
                if e.errno != errno.ESRCH:
                    raise
            self.shell_pid = None

    def _drain_shell_output(self) -> None:
        if self.shell_fd is None:
            return

        while True:
            rlist, _, _ = select.select([self.shell_fd], [], [], 0)
            if not rlist:
                break
            try:
                data = os.read(self.shell_fd, 4096)
            except BlockingIOError:
                break
            except OSError:
                self.message = "Shell disconnected"
                self._restart_shell()
                return
            if not data:
                self.message = "Shell exited, restarting"
                self._restart_shell()
                return
            self._append_shell_data(data.decode("utf-8", errors="replace"))

    def _append_shell_data(self, text: str) -> None:
        data = self._sanitize_shell_text(self._shell_partial + text)
        parts = data.split("\n")
        self._shell_partial = parts.pop() if parts else ""
        self.shell_lines.extend(parts)

        if len(self.shell_lines) > self.max_shell_lines:
            self.shell_lines = self.shell_lines[-self.max_shell_lines :]

    def _sanitize_shell_text(self, text: str) -> str:
        # Keep CSI for SGR rendering, but remove OSC sequences.
        text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
        # Normalize CRLF and treat bare CR as line overwrite boundary.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text

    def _pair_for(self, fg: int, bg: int) -> int:
        if not self._supports_color:
            return 0
        key = (fg, bg)
        if key in self._pair_cache:
            return self._pair_cache[key]
        if self._next_pair >= curses.COLOR_PAIRS:
            return 0
        pair_id = self._next_pair
        self._next_pair += 1
        try:
            curses.init_pair(pair_id, fg, bg)
        except curses.error:
            return 0
        self._pair_cache[key] = pair_id
        return pair_id

    def _ansi_attr(self, sgr_codes: str, current: int) -> int:
        if not sgr_codes:
            sgr_codes = "0"
        parts = [int(p) if p else 0 for p in sgr_codes.split(";")]
        # State: (bold, fg, bg) packed into local vars for this line render call.
        bold = bool(current & curses.A_BOLD)
        fg = -1
        bg = -1
        for code in parts:
            if code == 0:
                bold = False
                fg = -1
                bg = -1
            elif code == 1:
                bold = True
            elif code in (22,):
                bold = False
            elif 30 <= code <= 37:
                fg = code - 30
            elif code == 39:
                fg = -1
            elif 40 <= code <= 47:
                bg = code - 40
            elif code == 49:
                bg = -1
            elif 90 <= code <= 97:
                fg = (code - 90) + 8
            elif 100 <= code <= 107:
                bg = (code - 100) + 8
        attr = curses.A_NORMAL
        if bold:
            attr |= curses.A_BOLD
        pair = self._pair_for(fg, bg)
        if pair:
            attr |= curses.color_pair(pair)
        return attr

    def _draw_ansi_line(self, y: int, x: int, width: int, line: str) -> int:
        if width <= 1:
            return 0
        csi = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")
        col = 0
        attr = curses.A_NORMAL
        pos = 0
        for m in csi.finditer(line):
            chunk = line[pos : m.start()]
            if chunk and col < width - 1:
                drawn = chunk[: max(0, width - 1 - col)]
                self.stdscr.addnstr(y, x + col, drawn, width - 1 - col, attr)
                col += len(drawn)
            final = m.group(3)
            if final == "m":
                attr = self._ansi_attr(m.group(1), attr)
            pos = m.end()
            if col >= width - 1:
                break
        if col < width - 1 and pos < len(line):
            chunk = line[pos:]
            drawn = chunk[: max(0, width - 1 - col)]
            self.stdscr.addnstr(y, x + col, drawn, width - 1 - col, attr)
            col += len(drawn)
        return col

    def _measure_ansi_line(self, width: int, line: str) -> int:
        if width <= 1:
            return 0
        csi = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")
        col = 0
        pos = 0
        for m in csi.finditer(line):
            chunk = line[pos : m.start()]
            col += len(chunk)
            pos = m.end()
            if col >= width - 1:
                return width - 1
        col += len(line[pos:])
        return min(col, width - 1)

    def _send_to_shell(self, key: int) -> bool:
        if self.shell_fd is None:
            return False

        mapping = {
            curses.KEY_UP: b"\x1b[A",
            curses.KEY_DOWN: b"\x1b[B",
            curses.KEY_RIGHT: b"\x1b[C",
            curses.KEY_LEFT: b"\x1b[D",
            curses.KEY_BACKSPACE: b"\x7f",
            10: b"\n",
            13: b"\n",
            9: b"\t",
            27: b"\x1b",
        }

        if key in mapping:
            os.write(self.shell_fd, mapping[key])
            return True

        if 0 <= key <= 255:
            os.write(self.shell_fd, bytes([key]))
            return True

        return False

    def _handle_key(self, key: int) -> bool:
        if key in (ord("q"), ord("Q")):
            return False

        if key in (ord("\t"),):
            self.focus = "shell" if self.focus == "browser" else "browser"
            return True

        if key in (curses.KEY_RESIZE,):
            return True

        if self.focus == "shell":
            if key in (curses.KEY_ENTER, 10, 13):
                self.message = "Enter sent to shell (shell focus). Press TAB/b for browser focus."
                self._send_to_shell(key)
                return True
            if key in (ord("r"), ord("R")):
                self._restart_shell()
                self.message = "Shell restarted"
                return True
            if key in (ord("b"), ord("B")):
                self.focus = "browser"
                return True
            self._send_to_shell(key)
            return True

        if key in (curses.KEY_UP, ord("k")):
            self._move_selection(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_selection(1)
        elif key in (curses.KEY_NPAGE,):
            self._move_selection(10)
        elif key in (curses.KEY_PPAGE,):
            self._move_selection(-10)
        elif key in (curses.KEY_ENTER, 10, 13, ord("l")):
            self._enter_selected()
        elif key in (ord("h"),):
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
        elif key in (ord(":"),):
            self._run_oneoff_command()
        elif key in (ord("s"),):
            self.focus = "shell"

        self._ensure_visible()
        return True

    def _ensure_visible(self) -> None:
        h, _ = self.stdscr.getmaxyx()
        list_height = max(3, h // 2 - 3)

        if self.selected < self.top_index:
            self.top_index = self.selected
        if self.selected >= self.top_index + list_height:
            self.top_index = self.selected - list_height + 1

    def _draw(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        left_w = max(30, w // 2)

        browser_focus = "*" if self.focus == "browser" else " "
        shell_focus = "*" if self.focus == "shell" else " "

        header = f"{browser_focus} rex  host={self.host}  cwd={self.cwd}"
        self.stdscr.addnstr(0, 0, header, w - 1, curses.A_BOLD)

        split = h // 2
        self.stdscr.hline(split, 0, ord("-"), w)

        self.stdscr.addnstr(1, 0, "Files", left_w - 1, curses.A_UNDERLINE)
        self._draw_entries(2, 0, split - 2, left_w)

        self.stdscr.addnstr(split + 1, 0, f"{shell_focus} Shell (TAB to switch focus)", w - 1, curses.A_UNDERLINE)
        cursor_pos = self._draw_shell(split + 2, 0, h - split - 4, w)

        footer = "q quit | enter open/dir | e edit | o view | : cmd | s shell focus | tab toggle"
        self.stdscr.addnstr(h - 2, 0, footer, w - 1, curses.A_DIM)
        self.stdscr.addnstr(h - 1, 0, self.message, w - 1, curses.A_BOLD)
        if self.focus == "shell" and cursor_pos is not None:
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
        if height <= 0 or width <= 1:
            return

        visible = self.entries[self.top_index : self.top_index + height]
        for i, entry in enumerate(visible):
            idx = self.top_index + i
            marker = "/" if entry.is_dir else ""
            line = f"{entry.name}{marker}"
            attr = curses.A_REVERSE if idx == self.selected and self.focus == "browser" else curses.A_NORMAL
            self.stdscr.addnstr(y + i, x, line, width - 1, attr)

    def _draw_shell(self, y: int, x: int, height: int, width: int) -> tuple[int, int] | None:
        if height <= 0 or width <= 1:
            return None

        lines = self.shell_lines[-height:]
        start = y
        cursor_y = start + max(0, min(height - 1, len(lines)))
        cursor_x = x
        for i, line in enumerate(lines):
            self._draw_ansi_line(start + i, x, width, line)
        if self._shell_partial and len(lines) < height:
            cursor_y = start + len(lines)
            col = self._draw_ansi_line(cursor_y, x, width, self._shell_partial)
            cursor_x = x + min(col, width - 2)
        elif lines:
            last_y = start + len(lines) - 1
            col = self._measure_ansi_line(width, lines[-1])
            cursor_y = last_y
            cursor_x = x + min(col, width - 2)
        return (cursor_y, cursor_x)


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
