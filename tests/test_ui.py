import io
import unittest

from good_bot.ui import ConsoleEventStream


class ConsoleEventStreamTests(unittest.TestCase):
    def test_file_output_renders_each_line(self) -> None:
        stream_buffer = io.StringIO()
        stream = ConsoleEventStream(stream=stream_buffer, use_color=False)
        stream.emit("file_output", operation="read_file", text="line-a\nline-b\n")
        lines = [line for line in stream_buffer.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)
        self.assertIn("[file] line-a", lines[0])
        self.assertIn("[file] line-b", lines[1])


if __name__ == "__main__":
    unittest.main()
