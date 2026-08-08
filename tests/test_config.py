from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ddvc.config import dotenv_path, dotenv_value


class ConfigTests(unittest.TestCase):
    def test_runner_supplied_environment_file_is_parsed_without_sourcing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# comment\nGRAPH_API_KEYS=first, second\nDUNE_API_KEY='dune'\n",
                encoding="utf-8",
            )
            with (
                patch("ddvc.config.REPO_ROOT", Path(directory) / "missing"),
                patch.dict(os.environ, {"DDVC_ENV_FILE": str(path)}, clear=False),
            ):
                self.assertEqual(dotenv_path(), path)
                self.assertEqual(
                    dotenv_value("GRAPH_API_KEYS", "GRAPH_API_KEY"),
                    "first, second",
                )
                self.assertEqual(dotenv_value("DUNE_API_KEYS", "DUNE_API_KEY"), "dune")

    def test_local_environment_file_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / ".env"
            supplied = root / "primary.env"
            local.write_text("GRAPH_API_KEY=local\n", encoding="utf-8")
            supplied.write_text("GRAPH_API_KEY=primary\n", encoding="utf-8")
            with (
                patch("ddvc.config.REPO_ROOT", root),
                patch.dict(os.environ, {"DDVC_ENV_FILE": str(supplied)}, clear=False),
            ):
                self.assertEqual(dotenv_path(), local)
                self.assertEqual(dotenv_value("GRAPH_API_KEY"), "local")


if __name__ == "__main__":
    unittest.main()
