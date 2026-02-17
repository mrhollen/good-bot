import os
import tempfile
import unittest
from pathlib import Path

from good_bot.bootstrap import _create_snapshot


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


if __name__ == "__main__":
    unittest.main()
