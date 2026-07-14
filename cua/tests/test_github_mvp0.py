import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import cua  # noqa: E402
import cua_github_mvp0 as github  # noqa: E402
from cua_state import SessionState  # noqa: E402
from cua_util import SkillError  # noqa: E402


class FakeAuthState:
    api_base_url = "http://gateway"


class GitHubMvp0PureTests(unittest.TestCase):
    def test_parse_issue_url(self):
        result = github.parse_issue_url("https://github.com/2B-AL/cua_skill/issues/12")
        self.assertEqual(result["repository"], "2B-AL/cua_skill")
        self.assertEqual(result["issue_number"], 12)
        self.assertEqual(result["issue_url"], "https://github.com/2B-AL/cua_skill/issues/12")

    def test_parse_issue_url_rejects_noncanonical_or_unsafe_values(self):
        invalid = [
            "http://github.com/acme/repo/issues/1",
            "https://github.example.com/acme/repo/issues/1",
            "https://token@github.com/acme/repo/issues/1",
            "https://github.com/acme/repo/pull/1",
            "https://github.com/acme/repo/issues/0",
            "https://github.com/acme/repo/issues/1?x=y",
            "https://github.com:bad/acme/repo/issues/1",
            "https://github.com/acme/%2e%2e/issues/1",
            "https://github.com/acme/repo/issues/1/extra",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(SkillError) as ctx:
                github.parse_issue_url(value)
            self.assertEqual(ctx.exception.code, "VALIDATION_ERROR")

    def test_make_run_layout_is_deterministic(self):
        issue = github.parse_issue_url("https://github.com/acme/demo/issues/7")
        layout = github.make_run_layout(issue, "012345abcdef")
        self.assertEqual(layout["branch"], "cua/mvp0/012345abcdef-issue-7")
        self.assertEqual(layout["workspace"], r"C:\CUA\github-mvp0\012345abcdef\repo")

    def test_prompts_keep_fixed_repository_and_agent_boundaries(self):
        issue = github.parse_issue_url("https://github.com/acme/demo/issues/7")
        layout = github.make_run_layout(issue, "012345abcdef")
        prompt = github.build_issue_task_prompt(issue, layout, "claude-code")
        self.assertIn("repository: acme/demo", prompt)
        self.assertIn("branch: cua/mvp0/012345abcdef-issue-7", prompt)
        self.assertIn("/claude (Claude Code)", prompt)
        self.assertIn("must not commit, push, or create a PR", prompt)
        self.assertIn(github.ISSUE_COMPLETED_MARKER, prompt)

    def test_parse_device_auth_request(self):
        result = github.parse_device_auth_request(
            "MVP0_GITHUB_DEVICE_AUTH\n"
            "verification_uri=https://github.com/login/device\n"
            "user_code=AB12-CD34"
        )
        self.assertEqual(result, {
            "verification_uri": "https://github.com/login/device",
            "user_code": "AB12-CD34",
        })

    def test_parse_device_auth_rejects_wrong_uri_or_ambiguous_code(self):
        with self.assertRaises(SkillError) as ctx:
            github.parse_device_auth_request(
                "MVP0_GITHUB_DEVICE_AUTH\n"
                "verification_uri=https://evil.example/device\n"
                "user_code=AB12-CD34"
            )
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_AUTH_OUTPUT_INVALID")

    def test_parse_connected_result(self):
        parsed = github.parse_connected_result(
            "MVP0_GITHUB_CONNECTED\nhost=github.com\nlogin=cua-test\ngit_protocol=https"
        )
        self.assertEqual(parsed["status"], "connected")
        self.assertEqual(parsed["login"], "cua-test")

    def test_parse_status_disconnected(self):
        parsed = github.parse_status_result(
            "MVP0_GITHUB_STATUS\nstatus=disconnected\nhost=github.com"
        )
        self.assertEqual(parsed, {"status": "disconnected", "host": "github.com"})

    def test_parse_issue_result_and_expected_binding(self):
        text = (
            "MVP0_GITHUB_ISSUE_COMPLETED\n"
            "repository=acme/demo\n"
            "issue_number=7\n"
            "branch=cua/mvp0/012345abcdef-issue-7\n"
            "commit_sha=abc1234\n"
            "pull_request_number=9\n"
            "pull_request_url=https://github.com/acme/demo/pull/9\n"
            "tests=go test ./... passed"
        )
        parsed = github.parse_issue_task_result(text, expected={
            "repository": "acme/demo",
            "issue_number": 7,
            "branch": "cua/mvp0/012345abcdef-issue-7",
        })
        self.assertEqual(parsed["pull_request_number"], 9)
        self.assertEqual(parsed["tests"], "go test ./... passed")

        with self.assertRaises(SkillError) as ctx:
            github.parse_issue_task_result(text, expected={
                "repository": "acme/other",
                "issue_number": 7,
                "branch": "cua/mvp0/012345abcdef-issue-7",
            })
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_RESULT_INVALID")

    def test_known_failure_marker_becomes_skill_error(self):
        with self.assertRaises(SkillError) as ctx:
            github.parse_completed_result("GITHUB_MVP0_TEST_FAILED\nunit tests failed", kind="run")
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_TEST_FAILED")

    def test_config_sync_verified_requires_explicit_success(self):
        self.assertTrue(github.config_sync_verified({
            "app": "claude-code",
            "auth": {"effective_status": "verified", "native_file": {"verified": True}},
        }))
        self.assertTrue(github.config_sync_verified({"auth": {"status": "success"}}))
        self.assertFalse(github.config_sync_verified({"auth": {"auth_source": "native_file"}}))
        self.assertFalse(github.config_sync_verified(None))


class GitHubMvp0CommandTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.session = SessionState(Path(self.tempdir.name) / "session.json", {})
        self.state = FakeAuthState()
        self.parser = cua.build_parser()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_connect_returns_structured_device_action_and_saves_desktop(self):
        args = self.parser.parse_args(["github-mvp0", "connect"])
        envelope = {
            "invocation_id": "task-login-1",
            "outcome": "needs_input",
            "input_request": {"question": (
                "MVP0_GITHUB_DEVICE_AUTH\n"
                "verification_uri=https://github.com/login/device\n"
                "user_code=AB12-CD34"
            )},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(cua.cua_auth, "authorized_call", return_value=envelope) as call:
            result = args.handler(args, self.state, self.session)

        self.assertEqual(result["data"]["status"], "needs_user_action")
        self.assertEqual(result["data"]["user_code"], "AB12-CD34")
        self.assertIn("--authorized", result["next"]["command"])
        self.assertEqual(self.session.github_mvp0_task("task-login-1")["desktop"], "desktop-1")
        body = call.call_args.kwargs["body"]
        self.assertNotIn("disable_ask_user", body)

    def test_connect_authorized_answers_same_task_and_saves_connection(self):
        self.session.set_github_mvp0_task("task-login-1", {
            "kind": "connect", "desktop": "desktop-1",
        })
        args = self.parser.parse_args([
            "github-mvp0", "connect", "--task-id", "task-login-1", "--authorized",
        ])
        envelope = {
            "invocation_id": "task-login-1",
            "outcome": "completed",
            "result": {"text": (
                "MVP0_GITHUB_CONNECTED\n"
                "host=github.com\nlogin=cua-test\ngit_protocol=https"
            )},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(cua.cua_auth, "authorized_call", return_value=envelope) as call:
            result = args.handler(args, self.state, self.session)

        self.assertEqual(result["data"]["status"], "connected")
        self.assertEqual(self.session.github_mvp0_connection["login"], "cua-test")
        self.assertEqual(call.call_args.args[3], "/v1/tasks/task-login-1/answer")

    def test_connect_authorized_fetches_authoritative_result_for_thin_completion(self):
        self.session.set_github_mvp0_task("task-login-1", {
            "kind": "connect", "desktop": "desktop-1",
        })
        args = self.parser.parse_args([
            "github-mvp0", "connect", "--task-id", "task-login-1", "--authorized",
        ])
        thin = {
            "invocation_id": "task-login-1",
            "outcome": "completed",
            "result": {"text": None},
            "platform": {"desktop": "desktop-1"},
        }
        authoritative = {
            "invocation_id": "task-login-1",
            "outcome": "completed",
            "result": {"text": (
                "MVP0_GITHUB_CONNECTED\n"
                "host=github.com\nlogin=cua-test\ngit_protocol=https"
            )},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(
                cua.cua_auth, "authorized_call", side_effect=[thin, authoritative]) as call:
            result = args.handler(args, self.state, self.session)

        self.assertEqual(result["data"]["status"], "connected")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[0].args[3], "/v1/tasks/task-login-1/answer")
        self.assertEqual(call.call_args_list[1].args[3], "/v1/tasks/task-login-1/result")

    def test_watch_fetches_authoritative_result_for_thin_completion(self):
        self.session.set_github_mvp0_task("task-status-1", {
            "kind": "status", "desktop": "desktop-1",
        })
        args = self.parser.parse_args([
            "github-mvp0", "watch", "--task-id", "task-status-1",
        ])
        thin = {
            "invocation_id": "task-status-1",
            "outcome": "completed",
            "platform": {"desktop": "desktop-1"},
        }
        authoritative = {
            "invocation_id": "task-status-1",
            "outcome": "completed",
            "result": {"text": (
                "MVP0_GITHUB_STATUS\nstatus=connected\nhost=github.com\n"
                "login=cua-test\ngit_protocol=https\ncredential_helper_configured=true"
            )},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(
                cua.cua_auth, "authorized_call", side_effect=[thin, authoritative]) as call:
            result = args.handler(args, self.state, self.session)

        self.assertEqual(result["data"]["status"], "connected")
        self.assertTrue(result["data"]["credential_helper_configured"])
        self.assertEqual(call.call_args_list[0].args[3], "/v1/tasks/task-status-1")
        self.assertEqual(call.call_args_list[1].args[3], "/v1/tasks/task-status-1/result")

    def test_fast_task_creation_fetches_authoritative_result_for_thin_completion(self):
        args = self.parser.parse_args(["github-mvp0", "status"])
        thin = {
            "invocation_id": "task-status-1",
            "outcome": "completed",
            "platform": {"desktop": "desktop-1"},
        }
        authoritative = {
            "invocation_id": "task-status-1",
            "outcome": "completed",
            "result": {"text": "MVP0_GITHUB_STATUS\nstatus=disconnected\nhost=github.com"},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(
                cua.cua_auth, "authorized_call", side_effect=[thin, authoritative]) as call:
            result = args.handler(args, self.state, self.session)

        self.assertEqual(result["data"]["status"], "disconnected")
        self.assertEqual(call.call_args_list[0].args[3], "/v1/tasks")
        self.assertEqual(call.call_args_list[1].args[3], "/v1/tasks/task-status-1/result")

    def test_run_verifies_agent_and_reuses_connected_desktop(self):
        self.session.set_github_mvp0_connection({
            "login": "cua-test", "desktop": "desktop-1", "git_protocol": "https",
        })
        args = self.parser.parse_args([
            "github-mvp0", "run",
            "--issue", "https://github.com/acme/demo/issues/7",
            "--agent", "opencode",
        ])
        envelope = {
            "invocation_id": "task-run-1",
            "outcome": "in_progress",
            "platform": {"desktop": "desktop-1"},
        }
        calls = []

        def fake_call(_state, _base_url, method, path, body=None, **kwargs):
            calls.append((method, path, body, kwargs))
            if path.endswith("/verify"):
                return {"verified": True}
            return envelope

        fake_uuid = mock.Mock(hex="012345abcdef9999")
        with mock.patch.object(cua.cua_auth, "authorized_call", side_effect=fake_call), \
                mock.patch.object(cua.uuid, "uuid4", return_value=fake_uuid):
            result = args.handler(args, self.state, self.session)

        self.assertEqual(calls[0][1], "/v1/config-sync/apps/opencode/verify")
        self.assertEqual(calls[0][2], {"source": "active"})
        self.assertEqual(calls[1][1], "/v1/tasks")
        task_body = calls[1][2]
        self.assertEqual(task_body["desktop"], "desktop-1")
        self.assertTrue(task_body["disable_ask_user"])
        self.assertIn("cua/mvp0/012345abcdef-issue-7", task_body["objective"])
        self.assertEqual(result["data"]["status"], "in_progress")
        metadata = self.session.github_mvp0_task("task-run-1")
        self.assertEqual(metadata["repository"], "acme/demo")
        self.assertEqual(metadata["coding_agent"], "opencode")

    def test_run_requires_cached_connection_and_rejects_another_desktop(self):
        args = self.parser.parse_args([
            "github-mvp0", "run",
            "--issue", "https://github.com/acme/demo/issues/7",
            "--agent", "claude-code",
        ])
        with self.assertRaises(SkillError) as ctx:
            args.handler(args, self.state, self.session)
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_AUTH_REQUIRED")

        self.session.set_github_mvp0_connection({
            "status": "connected", "login": "cua-test", "desktop": "desktop-1",
        })
        args = self.parser.parse_args([
            "github-mvp0", "run",
            "--issue", "https://github.com/acme/demo/issues/7",
            "--agent", "claude-code", "--desktop", "desktop-2",
        ])
        with self.assertRaises(SkillError) as ctx:
            args.handler(args, self.state, self.session)
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_DESKTOP_CHANGED")

    def test_run_stops_when_config_sync_is_not_verified(self):
        self.session.set_github_mvp0_connection({
            "status": "connected", "login": "cua-test", "desktop": "desktop-1",
        })
        args = self.parser.parse_args([
            "github-mvp0", "run",
            "--issue", "https://github.com/acme/demo/issues/7",
            "--agent", "claude-code",
        ])
        with mock.patch.object(cua.cua_auth, "authorized_call", return_value={
            "app": "claude-code", "auth": {"effective_status": "unverified"},
        }) as call, self.assertRaises(SkillError) as ctx:
            args.handler(args, self.state, self.session)
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_AGENT_CONFIG_INVALID")
        self.assertEqual(call.call_count, 1)

    def test_disconnected_status_clears_cached_connection(self):
        self.session.set_github_mvp0_connection({
            "status": "connected", "login": "cua-test", "desktop": "desktop-1",
        })
        args = self.parser.parse_args(["github-mvp0", "status"])
        envelope = {
            "invocation_id": "task-status-1",
            "outcome": "completed",
            "result": {"text": "MVP0_GITHUB_STATUS\nstatus=disconnected\nhost=github.com"},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(cua.cua_auth, "authorized_call", return_value=envelope):
            result = args.handler(args, self.state, self.session)
        self.assertEqual(result["data"]["status"], "disconnected")
        self.assertEqual(self.session.github_mvp0_connection, {})

    def test_result_parses_pr_against_saved_request(self):
        self.session.set_github_mvp0_task("task-run-1", {
            "kind": "run",
            "desktop": "desktop-1",
            "repository": "acme/demo",
            "issue_number": 7,
            "branch": "cua/mvp0/012345abcdef-issue-7",
        })
        args = self.parser.parse_args([
            "github-mvp0", "result", "--task-id", "task-run-1", "--timeout", "1",
        ])
        envelope = {
            "invocation_id": "task-run-1",
            "outcome": "completed",
            "result": {"text": (
                "MVP0_GITHUB_ISSUE_COMPLETED\n"
                "repository=acme/demo\nissue_number=7\n"
                "branch=cua/mvp0/012345abcdef-issue-7\n"
                "commit_sha=abcdef1\npull_request_number=9\n"
                "pull_request_url=https://github.com/acme/demo/pull/9\n"
                "tests=passed"
            )},
            "platform": {"desktop": "desktop-1"},
        }
        with mock.patch.object(cua.cua_auth, "authorized_call", return_value=envelope):
            result = args.handler(args, self.state, self.session)
        self.assertEqual(result["data"]["status"], "completed")
        self.assertEqual(result["data"]["pull_request_url"], "https://github.com/acme/demo/pull/9")

    def test_non_login_needs_input_is_rejected(self):
        self.session.set_github_mvp0_task("task-run-1", {"kind": "run"})
        args = self.parser.parse_args(["github-mvp0", "watch", "--task-id", "task-run-1"])
        envelope = {
            "invocation_id": "task-run-1",
            "outcome": "needs_input",
            "input_request": {"question": "What should I do?"},
        }
        with mock.patch.object(cua.cua_auth, "authorized_call", return_value=envelope), \
                self.assertRaises(SkillError) as ctx:
            args.handler(args, self.state, self.session)
        self.assertEqual(ctx.exception.code, "GITHUB_MVP0_UNEXPECTED_INPUT")


if __name__ == "__main__":
    unittest.main()
