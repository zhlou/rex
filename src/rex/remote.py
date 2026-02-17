from __future__ import annotations

import os
import shlex
import subprocess

from rex.models import RemoteEntry


def build_remote_sh_command(command: str) -> str:
    return f"sh -lc {shlex.quote(command)}"


class RemoteShell:
    def __init__(self, host: str) -> None:
        self.host = host

    def run(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["ssh", self.host, build_remote_sh_command(command)],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def run_fullscreen(self, remote_command: str) -> None:
        subprocess.run(["ssh", "-t", self.host, build_remote_sh_command(remote_command)], check=False)

    def list_directory(self, target_path: str) -> tuple[str | None, list[RemoteEntry] | None, str | None]:
        cmd = f"cd -- {shlex.quote(target_path)} && pwd -P && LC_ALL=C ls -1Ap"
        try:
            result = self.run(cmd)
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
        parsed: list[RemoteEntry] = [RemoteEntry("..", True)]
        for item in raw:
            is_dir = item.endswith("/")
            name = item[:-1] if is_dir else item
            parsed.append(RemoteEntry(name=name, is_dir=is_dir))
        return resolved_cwd, parsed, None


def check_ssh_available() -> None:
    if not which_executable("ssh"):
        raise SystemExit("ssh binary not found in PATH")


def which_executable(name: str) -> str | None:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(p, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None
