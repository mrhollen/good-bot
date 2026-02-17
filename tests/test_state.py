import tempfile
import unittest
from pathlib import Path

from good_bot.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_default_then_persisted_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            state = store.load()
            self.assertIn("agent_id", state)
            self.assertEqual(state["events"], [])

            store.append_event(state, kind="test", content="event one")

            reloaded = store.load()
            self.assertEqual(len(reloaded["events"]), 1)
            self.assertEqual(reloaded["events"][0]["kind"], "test")
            self.assertEqual(reloaded["events"][0]["content"], "event one")


if __name__ == "__main__":
    unittest.main()
