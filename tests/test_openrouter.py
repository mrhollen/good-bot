import unittest

from good_bot.openrouter import _extract_tool_calls, _parse_tool_call_args


class OpenRouterParsingTests(unittest.TestCase):
    def test_parse_tool_call_args_from_json_string(self) -> None:
        parsed = _parse_tool_call_args('{"command":"git status --short"}')
        self.assertEqual(parsed["command"], "git status --short")

    def test_parse_tool_call_args_invalid_json_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            _parse_tool_call_args("{bad json")

    def test_extract_tool_calls_from_tool_calls_field(self) -> None:
        message = {
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "run_command",
                        "arguments": '{"command":"echo hi","summary":"running"}',
                    },
                }
            ]
        }
        calls = _extract_tool_calls(message)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "run_command")
        self.assertEqual(calls[0].arguments["command"], "echo hi")

    def test_extract_tool_calls_from_legacy_function_call(self) -> None:
        message = {
            "function_call": {
                "name": "respond",
                "arguments": '{"message":"done"}',
            }
        }
        calls = _extract_tool_calls(message)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "respond")
        self.assertEqual(calls[0].arguments["message"], "done")


if __name__ == "__main__":
    unittest.main()
