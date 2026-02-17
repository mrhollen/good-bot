import tempfile
import unittest
from pathlib import Path

from good_bot.agent import Agent
from good_bot.config import Config
from good_bot.openrouter import ChatCompletionResult, ToolCall
from good_bot.state import StateStore


class _FakeClient:
    def __init__(self, completion: ChatCompletionResult) -> None:
        self.completion = completion
        self.calls: list[dict] = []

    def create_chat_completion(self, messages, *, tools=None, tool_choice=None, temperature=0.1):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "temperature": temperature,
            }
        )
        return self.completion


def _config_for_test(tmp: str) -> Config:
    root = Path(tmp)
    return Config(
        api_key="test-key",
        model="test-model",
        base_url="https://example.com",
        state_path=root / "state.json",
        runtime_dir=root / "runtime",
        workspace=root,
        max_steps=0,
        history_events=10,
        command_timeout_seconds=5,
        max_output_chars=2000,
        max_restarts=1,
        autonomous=False,
        autonomous_pause_seconds=0.0,
        freeze_code=True,
        stream_events=False,
        git_auto_push=False,
        git_auth_check=False,
        git_pull_on_startup=False,
        git_remote="origin",
        git_branch="main",
        git_commit_prefix="good-bot",
        git_author_name=None,
        git_author_email=None,
        github_token=None,
        github_repo=None,
    )


class AgentToolPlanningTests(unittest.TestCase):
    def test_plan_run_command_from_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_command",
                        arguments={"command": "git status --short", "summary": "checking"},
                    )
                ],
            )
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            decision = agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            self.assertEqual(decision["action"], "run_command")
            self.assertEqual(decision["command"], "git status --short")
            self.assertEqual(decision["summary"], "checking")

    def test_plan_list_files_from_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="list_files",
                        arguments={"path": "src", "recursive": False, "max_entries": 50},
                    )
                ],
            )
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            decision = agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            self.assertEqual(decision["action"], "list_files")
            self.assertEqual(decision["path"], "src")
            self.assertEqual(decision["recursive"], "false")
            self.assertEqual(decision["max_entries"], "50")

    def test_plan_respond_from_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="respond",
                        arguments={"message": "Done."},
                    )
                ],
            )
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            decision = agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            self.assertEqual(decision["action"], "respond")
            self.assertEqual(decision["message"], "Done.")

    def test_plan_read_file_from_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "README.md", "start_line": 2, "end_line": 3},
                    )
                ],
            )
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            decision = agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            self.assertEqual(decision["action"], "read_file")
            self.assertEqual(decision["path"], "README.md")
            self.assertEqual(decision["start_line"], "2")
            self.assertEqual(decision["end_line"], "3")

    def test_plan_write_file_from_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={"path": "notes.txt", "content": "hello", "append": True},
                    )
                ],
            )
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            decision = agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            self.assertEqual(decision["action"], "write_file")
            self.assertEqual(decision["path"], "notes.txt")
            self.assertEqual(decision["content"], "hello")
            self.assertEqual(decision["append"], "true")

    def test_plan_unknown_tool_falls_back_to_respond(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="unknown_tool",
                        arguments={},
                    )
                ],
            )
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            decision = agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            self.assertEqual(decision["action"], "respond")
            self.assertIn("unknown tool", decision["message"].lower())

    def test_read_write_and_list_file_ops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(content="", tool_calls=[])
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            write_result = agent._write_file(path="sub/notes.txt", content="a\nb\nc\n", append=False)
            self.assertIn("write_file ok", write_result)

            read_result = agent._read_file(path="sub/notes.txt", start_line=2, end_line=3)
            self.assertIn("2", read_result)
            self.assertIn("b", read_result)

            list_result = agent._list_files(path="sub", recursive=True, max_entries=10)
            self.assertIn("sub/notes.txt", list_result)

    def test_file_ops_reject_workspace_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(content="", tool_calls=[])
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            result = agent._read_file(path="../outside.txt", start_line=None, end_line=None)
            self.assertIn("escapes workspace", result)


if __name__ == "__main__":
    unittest.main()
