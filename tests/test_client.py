import json
import subprocess
from pathlib import Path

import pytest

from herdr_mobile import AgentInfo, HerdrClient, HerdrError

FIXTURES = Path(__file__).parent / "fixtures"


def fake_run(stdout="", stderr="", returncode=0):
    calls = []

    def run(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)

    run.calls = calls
    return run


def test_list_agents_parses_fixture():
    run = fake_run(stdout=(FIXTURES / "agent_list.json").read_text())
    agents = HerdrClient(run_cli=run).list_agents()
    assert run.calls[0] == ["herdr", "agent", "list"]
    assert len(agents) == 4
    a = agents[0]
    assert a == AgentInfo(pane_id="w3:p1", kind="claude", status="working",
                          cwd="/home/dev/projects/web-app", name=None)
    assert a.project == "web-app"
    assert agents[1].name == "docs-site"


def test_read_agent_returns_text_and_uses_ansi_source():
    payload = {"id": "cli:agent:read", "result": {"read": {
        "format": "ansi", "pane_id": "w3:p1", "source": "recent_unwrapped",
        "text": "\x1b[32mhello\x1b[0m\nworld"}}}
    run = fake_run(stdout=json.dumps(payload))
    text = HerdrClient(run_cli=run).read_agent("w3:p1", lines=120)
    assert text == "\x1b[32mhello\x1b[0m\nworld"
    assert run.calls[0] == ["herdr", "agent", "read", "w3:p1",
                            "--source", "recent-unwrapped", "--format", "ansi",
                            "--lines", "120"]


def test_read_agent_normalizes_crlf_line_endings():
    # herdr's `agent read` returns lines terminated with \r\n. Rich's
    # Text.from_ansi treats a trailing \r as carriage-return-overwrite, which
    # wipes every line but the last at render time. The client must strip it.
    payload = {"id": "cli:agent:read", "result": {"read": {
        "format": "ansi", "pane_id": "w3:p1", "source": "recent_unwrapped",
        "text": "\x1b[32mline one\x1b[0m\r\nline two\r\nline three"}}}
    run = fake_run(stdout=json.dumps(payload))
    text = HerdrClient(run_cli=run).read_agent("w3:p1")
    assert "\r" not in text
    assert text == "\x1b[32mline one\x1b[0m\nline two\nline three"


def test_prompt_agent_uses_pane_run():
    run = fake_run(stdout='{"id":"x","result":{}}')
    HerdrClient(run_cli=run).prompt_agent("w3:p1", "fix the bug")
    assert run.calls[0] == ["herdr", "pane", "run", "w3:p1", "fix the bug"]


def test_send_key_special_vs_text():
    run = fake_run(stdout='{"id":"x","result":{}}')
    c = HerdrClient(run_cli=run)
    c.send_key("w3:p1", "up")
    c.send_key("w3:p1", "y")
    assert run.calls[0] == ["herdr", "pane", "send-keys", "w3:p1", "up"]
    assert run.calls[1] == ["herdr", "pane", "send-text", "w3:p1", "y"]


def test_create_workspace_parses_root_pane_and_workspace_id():
    # Real JSON shape, captured from a live `herdr workspace create --no-focus`.
    payload = {
        "id": "cli:workspace:create",
        "result": {
            "root_pane": {"pane_id": "wM:p1", "workspace_id": "wM", "tab_id": "wM:t1",
                          "cwd": "/Users/bogdan/Development/herdr-remote"},
            "tab": {"tab_id": "wM:t1", "workspace_id": "wM"},
            "workspace": {"workspace_id": "wM", "label": "5"},
            "type": "workspace_created",
        },
    }
    run = fake_run(stdout=json.dumps(payload))
    pane_id, workspace_id = HerdrClient(run_cli=run).create_workspace()
    assert pane_id == "wM:p1"
    assert workspace_id == "wM"
    assert run.calls[0] == ["herdr", "workspace", "create", "--no-focus"]


def test_read_pane_uses_visible_source_and_agent_read_command():
    # Verified live: `herdr agent read <pane> --source recent-unwrapped`
    # returns EMPTY text for a pane with no registered agent; only
    # `--source visible` returns real content. `herdr pane read` (the other
    # candidate) prints plain unwrapped text, not JSON, so it's unusable.
    payload = {"id": "cli:agent:read", "result": {"read": {
        "format": "ansi", "pane_id": "wM:p1", "source": "visible",
        "text": "\x1b[32m$ \x1b[0mecho hello\r\nhello"}}}
    run = fake_run(stdout=json.dumps(payload))
    text = HerdrClient(run_cli=run).read_pane("wM:p1", lines=50)
    assert text == "\x1b[32m$ \x1b[0mecho hello\nhello"  # \r\n normalized too
    assert run.calls[0] == ["herdr", "agent", "read", "wM:p1",
                            "--source", "visible", "--format", "ansi",
                            "--lines", "50"]


def test_error_json_raises_herdr_error():
    run = fake_run(stderr=(FIXTURES / "error_not_found.json").read_text(), returncode=1)
    with pytest.raises(HerdrError) as ei:
        HerdrClient(run_cli=run).read_agent("w99:p99")
    assert ei.value.code == "agent_not_found"
    assert "w99:p99" in ei.value.message


def test_error_json_on_stdout_also_raises():
    run = fake_run(stdout='{"error":{"code":"invalid_key","message":"unsupported key bogus"},"id":"cli:request"}',
                   returncode=1)
    with pytest.raises(HerdrError) as ei:
        HerdrClient(run_cli=run).send_key("w3:p1", "up")
    assert ei.value.code == "invalid_key"


def test_non_json_failure_raises_herdr_error_unknown():
    run = fake_run(stderr="usage: ...", returncode=2)
    with pytest.raises(HerdrError) as ei:
        HerdrClient(run_cli=run).list_agents()
    assert ei.value.code == "cli_error"


def test_missing_herdr_binary_raises_herdr_missing():
    def run(args):
        raise FileNotFoundError("herdr")
    with pytest.raises(HerdrError) as ei:
        HerdrClient(run_cli=run).list_agents()
    assert ei.value.code == "herdr_missing"


def test_error_json_on_stderr_takes_precedence_over_success_on_stdout():
    """When error JSON is on stderr but success JSON is on stdout, error takes precedence."""
    success_payload = {"id": "cli:agent:read", "result": {"read": {"text": "hello"}}}
    error_json = '{"error":{"code":"agent_busy","message":"agent is busy"},"id":"cli:request"}'
    run = fake_run(stdout=json.dumps(success_payload), stderr=error_json, returncode=1)
    with pytest.raises(HerdrError) as ei:
        HerdrClient(run_cli=run).read_agent("w3:p1")
    assert ei.value.code == "agent_busy"


def test_returncode_1_without_error_json_raises_cli_error():
    """When returncode is non-zero but no error JSON anywhere, raise cli_error."""
    success_payload = {"id": "cli:agent:read", "result": {"read": {"text": "hello"}}}
    run = fake_run(stdout=json.dumps(success_payload), returncode=1)
    with pytest.raises(HerdrError) as ei:
        HerdrClient(run_cli=run).read_agent("w3:p1")
    assert ei.value.code == "cli_error"
