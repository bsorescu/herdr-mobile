import json
import subprocess
from pathlib import Path

import pytest

from herdr_remote import AgentInfo, HerdrClient, HerdrError

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
                          cwd="/Users/bogdan/Development/aqos-platform", name=None)
    assert a.project == "aqos-platform"
    assert agents[1].name == "firstmate"


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
