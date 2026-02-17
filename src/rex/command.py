from __future__ import annotations

import shlex
import subprocess

from rex.models import AppState
from rex.remote import RemoteShell
from rex.ui.layout import LayoutEngine


class CommandController:
    def __init__(self, state: AppState, remote: RemoteShell, layout: LayoutEngine) -> None:
        self.state = state
        self.remote = remote
        self.layout = layout

    def show_panel(self) -> None:
        self.state.command.reset_for_open()
        self.state.focus = "command"
        self.state.message = f"Run command in {self.state.cwd}"

    def hide_panel(self) -> None:
        self.state.focus = "browser"
        self.state.command.close()

    def append_line(self, line: str) -> None:
        self.state.command.append_line(line)
        self.refresh_search_matches()

    def execute_input(self) -> None:
        user_cmd = self.state.command.input.strip()
        if not user_cmd:
            self.state.message = "Empty command"
            return

        if not self.state.command.history or self.state.command.history[-1] != user_cmd:
            self.state.command.history.append(user_cmd)
        self.state.command.history_index = None
        self.state.command.history_stash = ""

        self.append_line(f"$ {user_cmd}")
        remote = f"cd -- {shlex.quote(self.state.cwd)} && {user_cmd}"
        self.state.command.scroll = 0
        try:
            result = self.remote.run(remote, timeout=60)
        except subprocess.TimeoutExpired:
            self.append_line("[timed out]")
            self.state.message = "Command timed out"
            self.state.command.clear_input()
            return

        out_lines = result.stdout.splitlines()
        err_lines = result.stderr.splitlines()
        if not out_lines and not err_lines:
            self.append_line("[no output]")
        else:
            for line in out_lines:
                self.append_line(line)
            for line in err_lines:
                self.append_line(f"stderr: {line}")

        if result.returncode != 0:
            self.append_line(f"[exit {result.returncode}]")
            self.state.message = f"Command failed ({result.returncode})"
        else:
            self.state.message = "Command finished"

        self.state.command.clear_input()

    def refresh_search_matches(self) -> None:
        query = self.state.command.search_query.strip().lower()
        if not query:
            self.state.command.search_matches = []
            self.state.command.search_pos = -1
            return

        self.state.command.search_matches = [
            i for i, line in enumerate(self.state.command.lines) if query in line.lower()
        ]
        if not self.state.command.search_matches:
            self.state.command.search_pos = -1
        elif self.state.command.search_pos < 0 or self.state.command.search_pos >= len(self.state.command.search_matches):
            self.state.command.search_pos = 0

    def jump_search(self, direction: int) -> None:
        if not self.state.command.search_matches:
            self.state.message = "No search matches"
            return

        if self.state.command.search_pos < 0:
            self.state.command.search_pos = 0 if direction >= 0 else len(self.state.command.search_matches) - 1
        else:
            self.state.command.search_pos = (
                self.state.command.search_pos + direction
            ) % len(self.state.command.search_matches)
        line_idx = self.state.command.search_matches[self.state.command.search_pos]
        self.layout.scroll_to_line(line_idx)
        self.state.message = (
            f"Match {self.state.command.search_pos + 1}/{len(self.state.command.search_matches)}"
            f" for '{self.state.command.search_query}'"
        )
