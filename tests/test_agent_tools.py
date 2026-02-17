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


class _SequenceClient:
    def __init__(self, completions: list[ChatCompletionResult]) -> None:
        self._completions = list(completions)
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
        if not self._completions:
            raise AssertionError("No more mocked completions available.")
        return self._completions.pop(0)


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event: str, **payload) -> None:
        self.events.append((event, payload))


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
        git_rewrite_ssh_to_https=True,
        git_remote="origin",
        git_branch="main",
        git_commit_prefix="good-bot",
        git_author_name=None,
        git_author_email=None,
        github_token=None,
        github_repo=None,
    )


class AgentToolPlanningTests(unittest.TestCase):
    def test_system_prompt_includes_agents_md_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            (Path(tmp) / "AGENTS.md").write_text("Rule: always run tests.\n", encoding="utf-8")
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="respond",
                        arguments={"message": "ok"},
                    )
                ],
            )
            client = _FakeClient(completion)
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=client,  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            system_prompt = str(client.calls[0]["messages"][0]["content"])
            self.assertIn("Contents of AGENTS.md file:", system_prompt)
            self.assertIn("Rule: always run tests.", system_prompt)
            self.assertIn("call `list_files` first", system_prompt)

    def test_system_prompt_omits_agents_md_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="respond",
                        arguments={"message": "ok"},
                    )
                ],
            )
            client = _FakeClient(completion)
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=client,  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            agent._plan_next_action("goal", {"events": []}, step=1, max_steps=0)
            system_prompt = str(client.calls[0]["messages"][0]["content"])
            self.assertNotIn("Contents of AGENTS.md file:", system_prompt)

    def test_plan_prompt_includes_file_event_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="respond",
                        arguments={"message": "ok"},
                    )
                ],
            )
            client = _FakeClient(completion)
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=client,  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            state = {
                "events": [
                    {
                        "timestamp": "2026-01-01T00:00:00Z",
                        "kind": "file_result",
                        "content": "read_file result: path=README.md",
                        "metadata": {"operation": "read_file", "path": "README.md"},
                    }
                ]
            }
            agent._plan_next_action("goal", state, step=1, max_steps=0)
            user_prompt = str(client.calls[0]["messages"][1]["content"])
            self.assertIn("operation=read_file", user_prompt)
            self.assertIn("path=README.md", user_prompt)

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
            self.assertEqual(decision["continue_cycle"], "false")

    def test_plan_respond_continue_cycle_from_tool_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="respond",
                        arguments={"message": "Still working...", "continue_cycle": True},
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
            self.assertEqual(decision["message"], "Still working...")
            self.assertEqual(decision["continue_cycle"], "true")

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
                        arguments={"path": "notes.txt", "content": "hello", "mode": "append"},
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
            self.assertEqual(decision["mode"], "append")
            self.assertEqual(decision["overwrite_confirmed"], "false")

    def test_plan_write_file_legacy_append_maps_to_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={"path": "notes.txt", "content": "hello", "append": False},
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
            self.assertEqual(decision["mode"], "overwrite")

    def test_plan_write_file_defaults_to_append_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="write_file",
                        arguments={"path": "notes.txt", "content": "hello"},
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
            self.assertEqual(decision["mode"], "append")

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
            write_result = agent._write_file(
                path="sub/notes.txt",
                content="a\nb\nc\n",
                mode="overwrite",
                overwrite_confirmed=True,
            )
            self.assertIn("write_file ok", write_result)

            read_result = agent._read_file(path="sub/notes.txt", start_line=2, end_line=3)
            self.assertIn("path=sub/notes.txt", read_result)
            self.assertIn("2", read_result)
            self.assertIn("b", read_result)

            append_result = agent._write_file(
                path="sub/notes.txt",
                content="tail\n",
                mode="append",
                overwrite_confirmed=False,
            )
            self.assertIn("appended to", append_result)
            final_text = (Path(tmp) / "sub" / "notes.txt").read_text(encoding="utf-8")
            self.assertTrue(final_text.endswith("tail\n"))

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

    def test_write_file_overwrite_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completion = ChatCompletionResult(content="", tool_calls=[])
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            blocked = agent._write_file(
                path="notes.txt",
                content="replace",
                mode="overwrite",
                overwrite_confirmed=False,
            )
            self.assertIn("requires overwrite_confirmed=true", blocked)

            allowed = agent._write_file(
                path="notes.txt",
                content="replace",
                mode="overwrite",
                overwrite_confirmed=True,
            )
            self.assertIn("write_file ok", allowed)

    def test_run_respond_continue_cycle_then_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            completions = [
                ChatCompletionResult(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_1",
                            name="respond",
                            arguments={"message": "Working...", "continue_cycle": True},
                        )
                    ],
                ),
                ChatCompletionResult(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_2",
                            name="respond",
                            arguments={"message": "Done."},
                        )
                    ],
                ),
            ]
            client = _SequenceClient(completions)
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=client,  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            result = agent.run("goal", max_steps=5)
            self.assertEqual(result.message, "Done.")
            self.assertTrue(result.pause_for_user)

            events = StateStore(config.state_path).load()["events"]
            kinds = [event["kind"] for event in events]
            self.assertIn("interim_response", kinds)
            self.assertIn("final_response", kinds)

    def test_run_repeated_read_file_emits_feedback_and_aborts_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            (Path(tmp) / "README.md").write_text("line-1\nline-2\n", encoding="utf-8")
            completions = [
                ChatCompletionResult(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id=f"call_{idx}",
                            name="read_file",
                            arguments={"path": "README.md"},
                        )
                    ],
                )
                for idx in range(1, 8)
            ]
            client = _SequenceClient(completions)
            store = StateStore(config.state_path)
            agent = Agent(
                config=config,
                store=store,
                client=client,  # type: ignore[arg-type]
                instance_id="instance-1",
            )
            result = agent.run("goal", max_steps=20)
            self.assertTrue(result.pause_for_user)
            self.assertIn("repeating the same read_file action", result.message)

            events = store.load()["events"]
            file_results = [event for event in events if event["kind"] == "file_result"]
            feedback_events = [event for event in events if event["kind"] == "strategy_feedback"]
            self.assertEqual(len(file_results), 2)
            self.assertGreaterEqual(len(feedback_events), 1)
            self.assertEqual(feedback_events[0]["metadata"]["repeat_count"], 3)

    def test_run_read_file_emits_file_output_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _config_for_test(tmp)
            (Path(tmp) / "README.md").write_text("line-1\nline-2\n", encoding="utf-8")
            completion = ChatCompletionResult(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "README.md"},
                    )
                ],
            )
            collector = _EventCollector()
            agent = Agent(
                config=config,
                store=StateStore(config.state_path),
                client=_FakeClient(completion),  # type: ignore[arg-type]
                instance_id="instance-1",
                events=collector,  # type: ignore[arg-type]
            )
            agent.run("goal", max_steps=1)
            file_events = [payload for event, payload in collector.events if event == "file_output"]
            self.assertEqual(len(file_events), 1)
            self.assertEqual(file_events[0]["operation"], "read_file")
            self.assertIn("line-1", file_events[0]["text"])


if __name__ == "__main__":
    unittest.main()
