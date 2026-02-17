import tempfile
import unittest
from pathlib import Path

from good_bot.protocol import wait_for_handshake, write_handshake


class ProtocolTests(unittest.TestCase):
    def test_handshake_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime"
            token = "abc123"
            write_handshake(runtime_dir, token, instance_id="instance-1")
            payload = wait_for_handshake(runtime_dir, token, timeout_seconds=0.2, poll_seconds=0.05)
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["token"], token)
            self.assertEqual(payload["instance_id"], "instance-1")


if __name__ == "__main__":
    unittest.main()
