import subprocess
import unittest

from rex.main import build_remote_sh_command


class TestRemoteCommandQuoting(unittest.TestCase):
    def run_remote(self, command: str) -> subprocess.CompletedProcess[str]:
        remote = build_remote_sh_command(command)
        return subprocess.run(
            ["sh", "-lc", remote],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_shell_operators_are_inside_inner_shell(self) -> None:
        result = self.run_remote("cd / && pwd")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "/")

    def test_paths_with_spaces_work(self) -> None:
        result = self.run_remote("cd -- '/tmp' && printf '%s\n' 'a b'")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "a b")


if __name__ == "__main__":
    unittest.main()
