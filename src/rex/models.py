from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RemoteEntry:
    name: str
    is_dir: bool


@dataclass
class CommandPanelState:
    visible: bool = False
    input: str = ""
    cursor: int = 0
    lines: list[str] = field(default_factory=list)
    max_lines: int = 2000
    history: list[str] = field(default_factory=list)
    history_index: int | None = None
    history_stash: str = ""
    scroll: int = 0
    search_mode: bool = False
    search_query: str = ""
    search_matches: list[int] = field(default_factory=list)
    search_pos: int = -1

    def reset_for_open(self) -> None:
        self.visible = True
        self.input = ""
        self.cursor = 0
        self.lines.clear()
        self.scroll = 0
        self.history_index = None
        self.history_stash = ""
        self.search_mode = False
        self.search_query = ""
        self.search_matches = []
        self.search_pos = -1

    def close(self) -> None:
        self.visible = False
        self.history_index = None
        self.history_stash = ""
        self.search_mode = False

    def append_line(self, line: str) -> None:
        was_bottom = self.scroll == 0
        self.lines.append(line)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines :]
        if was_bottom:
            self.scroll = 0

    def clear_input(self) -> None:
        self.input = ""
        self.cursor = 0


@dataclass
class AppState:
    host: str
    cwd: str
    entries: list[RemoteEntry] = field(default_factory=list)
    selected: int = 0
    top_index: int = 0
    message: str = ""
    focus: str = "browser"
    command: CommandPanelState = field(default_factory=CommandPanelState)
