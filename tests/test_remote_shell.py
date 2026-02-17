import subprocess
import unittest
from unittest.mock import patch

from rex.main import RemoteShell


class TestRemoteShell(unittest.TestCase):
    def test_list_directory_parses_entries(self) -> None:
        shell = RemoteShell("example.com")
        result = subprocess.CompletedProcess(
            args=["ssh"],
            returncode=0,
            stdout="/tmp\nfile.txt\ndir/\n",
            stderr="",
        )

        with patch.object(shell, "run", return_value=result):
            cwd, entries, err = shell.list_directory("/tmp")

        self.assertIsNone(err)
        self.assertEqual(cwd, "/tmp")
        self.assertIsNotNone(entries)
        assert entries is not None
        self.assertEqual(entries[0].name, "..")
        self.assertTrue(entries[0].is_dir)
        self.assertEqual(entries[1].name, "file.txt")
        self.assertFalse(entries[1].is_dir)
        self.assertEqual(entries[2].name, "dir")
        self.assertTrue(entries[2].is_dir)

    def test_list_directory_propagates_remote_error(self) -> None:
        shell = RemoteShell("example.com")
        result = subprocess.CompletedProcess(args=["ssh"], returncode=2, stdout="", stderr="denied")

        with patch.object(shell, "run", return_value=result):
            cwd, entries, err = shell.list_directory("/tmp")

        self.assertIsNone(cwd)
        self.assertIsNone(entries)
        self.assertEqual(err, "Error: denied")

    def test_list_directory_handles_timeout(self) -> None:
        shell = RemoteShell("example.com")

        with patch.object(shell, "run", side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=30)):
            cwd, entries, err = shell.list_directory("/tmp")

        self.assertIsNone(cwd)
        self.assertIsNone(entries)
        self.assertEqual(err, "Listing timed out")


if __name__ == "__main__":
    unittest.main()
