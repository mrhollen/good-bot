import os
import tempfile
import unittest
from pathlib import Path

from good_bot.config import Config


class ConfigTests(unittest.TestCase):
    def test_loads_values_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                (
                    "OPENROUTER_API_KEY=test-key\n"
                    "OPENROUTER_MODEL=my/model\n"
                    "GOOD_BOT_GIT_AUTO_PUSH=false\n"
                    "GOOD_BOT_GIT_BRANCH=main\n"
                    "GOOD_BOT_HISTORY_EVENTS=12\n"
                    "GOOD_BOT_AUTONOMOUS=true\n"
                ),
                encoding="utf-8",
            )
            config = Config.from_env(env_path=env_path)
            self.assertEqual(config.api_key, "test-key")
            self.assertEqual(config.model, "my/model")
            self.assertFalse(config.git_auto_push)
            self.assertEqual(config.git_branch, "main")
            self.assertEqual(config.history_events, 12)
            self.assertTrue(config.autonomous)

    def test_missing_api_key_raises(self) -> None:
        previous = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_path = Path(tmp) / ".env"
                env_path.write_text("OPENROUTER_MODEL=x/y\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    Config.from_env(env_path=env_path)
        finally:
            if previous is not None:
                os.environ["OPENROUTER_API_KEY"] = previous

    def test_git_auto_push_defaults_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")
            config = Config.from_env(env_path=env_path)
            self.assertTrue(config.git_auto_push)
            self.assertEqual(config.max_steps, 0)
            self.assertEqual(config.history_events, 50)
            self.assertTrue(config.freeze_code)
            self.assertTrue(config.stream_events)
            self.assertFalse(config.autonomous)


if __name__ == "__main__":
    unittest.main()
