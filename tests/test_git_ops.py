import os
import unittest
from pathlib import Path
from unittest.mock import call, patch

from good_bot.git_ops import (
    GitSyncError,
    commit_and_push_update,
    configure_process_git_env,
    verify_github_token_access,
)


class GitOpsTests(unittest.TestCase):
    def test_configure_process_git_env_with_token_and_rewrite(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            configure_process_git_env(
                github_token="token",
                rewrite_ssh_to_https=True,
            )
            self.assertNotIn("GIT_HTTP_EXTRAHEADER", dict(os.environ))
            self.assertEqual(os.environ["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(os.environ["GIT_CONFIG_COUNT"], "3")
            self.assertEqual(
                os.environ["GIT_CONFIG_KEY_0"],
                "http.https://github.com/.extraheader",
            )
            self.assertTrue(
                os.environ["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic "),
            )
            self.assertEqual(
                os.environ["GIT_CONFIG_KEY_1"],
                "url.https://github.com/.insteadOf",
            )
            self.assertEqual(
                os.environ["GIT_CONFIG_KEY_2"],
                "url.https://github.com/.insteadOf",
            )
            self.assertEqual(
                os.environ["GIT_CONFIG_VALUE_2"],
                "ssh://git@github.com/",
            )
            self.assertEqual(os.environ["GIT_CONFIG_VALUE_1"], "git@github.com:")

    def test_configure_process_git_env_without_token_no_rewrite(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            configure_process_git_env(
                github_token=None,
                rewrite_ssh_to_https=True,
            )
            self.assertNotIn("GIT_HTTP_EXTRAHEADER", dict(os.environ))
            self.assertNotIn("GIT_CONFIG_COUNT", dict(os.environ))

    def test_configure_process_git_env_is_idempotent(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            configure_process_git_env(
                github_token="token",
                rewrite_ssh_to_https=True,
            )
            configure_process_git_env(
                github_token="token",
                rewrite_ssh_to_https=True,
            )
            self.assertEqual(os.environ["GIT_CONFIG_COUNT"], "3")

    def test_commit_with_token_requires_repo(self) -> None:
        with patch("good_bot.git_ops._run_git") as run_git:
            run_git.side_effect = [
                "true",  # rev-parse --is-inside-work-tree
                "",  # status --porcelain
            ]
            with self.assertRaises(GitSyncError):
                commit_and_push_update(
                    workspace=Path("/tmp/workspace"),
                    remote="origin",
                    branch="main",
                    commit_message="good-bot: update",
                    author_name=None,
                    author_email=None,
                    github_token="token",
                    github_repo=None,
                )

    def test_commit_and_push_with_changes(self) -> None:
        workspace = Path("/tmp/workspace")
        with patch("good_bot.git_ops._run_git") as run_git:
            run_git.side_effect = [
                "true",  # rev-parse --is-inside-work-tree
                " M src/file.py",  # status --porcelain
                "",  # add -A
                "",  # commit
                "abc1234",  # rev-parse --short HEAD
                "",  # push
            ]
            result = commit_and_push_update(
                workspace=workspace,
                remote="origin",
                branch="main",
                commit_message="good-bot: update",
                author_name="good-bot",
                author_email="bot@example.local",
                github_token=None,
                github_repo=None,
            )

            self.assertTrue(result.committed)
            self.assertTrue(result.pushed)
            self.assertEqual(result.commit_sha, "abc1234")
            commit_call = run_git.call_args_list[3]
            self.assertEqual(commit_call.args[0], ["commit", "-m", "good-bot: update"])
            commit_env = commit_call.kwargs["env"]
            self.assertEqual(commit_env["GIT_AUTHOR_NAME"], "good-bot")
            self.assertEqual(commit_env["GIT_AUTHOR_EMAIL"], "bot@example.local")
            self.assertEqual(
                run_git.call_args_list[-1],
                call(["push", "origin", "HEAD:main"], workspace=workspace),
            )

    def test_commit_and_push_without_changes(self) -> None:
        workspace = Path("/tmp/workspace")
        with patch("good_bot.git_ops._run_git") as run_git:
            run_git.side_effect = [
                "true",  # rev-parse --is-inside-work-tree
                "",  # status --porcelain
                "",  # push
            ]
            result = commit_and_push_update(
                workspace=workspace,
                remote="origin",
                branch="main",
                commit_message="good-bot: update",
                author_name=None,
                author_email=None,
                github_token=None,
                github_repo=None,
            )
            self.assertFalse(result.committed)
            self.assertTrue(result.pushed)
            self.assertIsNone(result.commit_sha)
            self.assertEqual(run_git.call_count, 3)

    def test_commit_and_push_with_token_uses_auth_env(self) -> None:
        workspace = Path("/tmp/workspace")
        with patch("good_bot.git_ops._run_git") as run_git:
            run_git.side_effect = [
                "true",  # rev-parse --is-inside-work-tree
                "",  # status --porcelain
                "",  # push with token
            ]
            result = commit_and_push_update(
                workspace=workspace,
                remote="origin",
                branch="main",
                commit_message="good-bot: update",
                author_name=None,
                author_email=None,
                github_token="token",
                github_repo="owner/repo",
            )
            self.assertFalse(result.committed)
            self.assertTrue(result.pushed)
            push_call = run_git.call_args_list[-1]
            self.assertEqual(
                push_call.args[0],
                ["push", "https://github.com/owner/repo.git", "HEAD:main"],
            )
            self.assertNotIn("GIT_HTTP_EXTRAHEADER", push_call.kwargs["env"])
            self.assertIn("GIT_CONFIG_KEY_0", push_call.kwargs["env"])

    def test_verify_github_token_access(self) -> None:
        workspace = Path("/tmp/workspace")
        with patch("good_bot.git_ops._run_git") as run_git:
            run_git.return_value = "ok"
            verify_github_token_access(
                workspace=workspace,
                github_token="token",
                github_repo="owner/repo",
            )
            args = run_git.call_args.args[0]
            self.assertEqual(
                args,
                ["ls-remote", "--exit-code", "https://github.com/owner/repo.git", "HEAD"],
            )
            self.assertNotIn("GIT_HTTP_EXTRAHEADER", run_git.call_args.kwargs["env"])
            self.assertIn("GIT_CONFIG_KEY_0", run_git.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
