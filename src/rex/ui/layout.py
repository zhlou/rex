from __future__ import annotations

from collections.abc import Callable

from rex.models import AppState


class LayoutEngine:
    def __init__(self, state: AppState, stdscr_getter: Callable[[], object | None]) -> None:
        self.state = state
        self._stdscr_getter = stdscr_getter

    def command_block_height(self, total_height: int) -> int:
        return max(3, total_height // 4)

    def browser_pane_dimensions(self) -> tuple[int, int]:
        stdscr = self._stdscr_getter()
        if stdscr is None:
            return 1, 1
        h, w = stdscr.getmaxyx()
        content_h = max(1, h - 3)
        browser_h = content_h
        if self.state.command.visible:
            command_h = min(content_h - 1, self.command_block_height(content_h))
            browser_h = max(1, content_h - command_h)
        return max(1, browser_h - 1), max(1, w)

    def command_output_rows(self) -> int:
        stdscr = self._stdscr_getter()
        if stdscr is None or not self.state.command.visible:
            return 0
        h, _ = stdscr.getmaxyx()
        content_h = max(1, h - 3)
        command_block_h = min(content_h - 1, self.command_block_height(content_h))
        panel_h = max(1, command_block_h - 1)
        return max(0, panel_h - 1)

    def command_max_scroll(self) -> int:
        output_rows = self.command_output_rows()
        if output_rows <= 0:
            return 0
        return max(0, len(self.state.command.lines) - output_rows)

    def clamp_command_scroll(self) -> None:
        self.state.command.scroll = max(0, min(self.state.command.scroll, self.command_max_scroll()))

    def scroll_to_line(self, line_idx: int) -> None:
        output_rows = self.command_output_rows()
        if output_rows <= 0:
            self.state.command.scroll = 0
            return
        total = len(self.state.command.lines)
        line_idx = max(0, min(total - 1, line_idx))
        desired_start = max(0, line_idx - (output_rows // 2))
        desired_end = min(total, desired_start + output_rows)
        desired_start = max(0, desired_end - output_rows)
        self.state.command.scroll = max(0, total - desired_end)
        self.clamp_command_scroll()

    def browser_layout(self, height: int, width: int) -> tuple[int, int, int, int]:
        rows = max(1, height)
        usable_width = max(1, width - 1)

        max_label = 2
        for entry in self.state.entries:
            marker = 1 if entry.is_dir else 0
            max_label = max(max_label, len(entry.name) + marker)

        column_width = max(4, min(usable_width, max_label + 2))
        cols = max(1, usable_width // column_width)
        if cols > 1:
            column_width = max(4, usable_width // cols)
        page_size = rows * cols
        return rows, column_width, cols, page_size

    def ensure_visible(self) -> None:
        browser_h, browser_w = self.browser_pane_dimensions()
        _, _, _, page_size = self.browser_layout(browser_h, browser_w)
        if page_size <= 0:
            return

        if self.state.selected < self.state.top_index or self.state.selected >= self.state.top_index + page_size:
            self.state.top_index = (self.state.selected // page_size) * page_size

        max_start = 0
        if self.state.entries:
            max_start = ((len(self.state.entries) - 1) // page_size) * page_size
        self.state.top_index = min(self.state.top_index, max_start)
