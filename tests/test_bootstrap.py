import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from good_bot.bootstrap import _create_snapshot, _maybe_pull_latest_on_startup


class BootstrapTests(unittest.TestCase):
    def test_create_snapshot_copies_package_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "src"
            package_dir = source_root / "good_bot"
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("__version__='x'\n", encoding="utf-8")
            (package_dir / "module.py").write_text("VALUE=1\n", encoding="utf-8")

            previous_runtime = os.environ.get("GOOD_BOT_RUNTIME_DIR")
            os.environ["GOOD_BOT_RUNTIME_DIR"] = str(Path(tmp) / "runtime")
            try:
                snapshot_root = _create_snapshot(source_root)
            finally:
                if previous_runtime is None:
                    os.environ.pop("GOOD_BOT_RUNTIME_DIR", None)
                else:
                    os.environ["GOOD_BOT_RUNTIME_DIR"] = previous_runtime

            self.assertTrue((snapshot_root / "good_bot" / "__init__.py").exists())
            self.assertTrue((snapshot_root / "good_bot" / "module.py").exists())

    def test_pull_on_startup_disabled_does_not_run_git(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GOOD_BOT_GIT_PULL_ON_STARTUP": "false",
                "GOOD_BOT_STARTUP_PULL_DONE": "",
            },
            clear=False,
        ):
            with patch("good_bot.bootstrap._run_git") as run_git:
                _maybe_pull_latest_on_startup()
                run_git.assert_not_called()

    def test_pull_on_startup_runs_fetch_and_ff_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "GOOD_BOT_GIT_PULL_ON_STARTUP": "true",
                    "GOOD_BOT_STARTUP_PULL_DONE": "",
                    "GOOD_BOT_WORKSPACE": tmp,
                    "GOOD_BOT_GIT_REMOTE": "origin",
                    "GOOD_BOT_GIT_BRANCH": "",
                },
                clear=False,
            ):
                with patch("good_bot.bootstrap._run_git") as run_git:
                    run_git.side_effect = [
                        "true",  # rev-parse --is-inside-work-tree
                        "",  # status --porcelain
                        "production",  # rev-parse --abbrev-ref HEAD
                        "",  # fetch
                        "",  # pull
                    ]
                    _maybe_pull_latest_on_startup()
                    self.assertEqual(
                        run_git.call_args_list,
                        [
                            call(["rev-parse", "--is-inside-work-tree"], Path(tmp).resolve()),
                            call(["status", "--porcelain"], Path(tmp).resolve()),
                            call(["rev-parse", "--abbrev-ref", "HEAD"], Path(tmp).resolve()),
                            call(["fetch", "origin", "production"], Path(tmp).resolve()),
                            call(["pull", "--ff-only", "origin", "production"], Path(tmp).resolve()),
                        ],
                    )

    def test_pull_on_startup_skips_when_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "GOOD_BOT_GIT_PULL_ON_STARTUP": "true",
                    "GOOD_BOT_STARTUP_PULL_DONE": "",
                    "GOOD_BOT_WORKSPACE": tmp,
                    "GOOD_BOT_GIT_REMOTE": "origin",
                    "GOOD_BOT_GIT_BRANCH": "production",
                },
                clear=False,
            ):
                with patch("good_bot.bootstrap._run_git") as run_git:
                    run_git.side_effect = [
                        "true",  # rev-parse --is-inside-work-tree
                        " M src/file.py",  # status --porcelain
                    ]
                    _maybe_pull_latest_on_startup()
                    self.assertEqual(run_git.call_count, 2)


if __name__ == "__main__":
    unittest.main()
