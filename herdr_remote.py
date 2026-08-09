# /// script
# requires-python = ">=3.12"
# dependencies = ["textual==8.2.8"]
# ///
"""herdr-remote: phone-friendly TUI for controlling Herdr agents over SSH."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass


class HerdrError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentInfo:
    pane_id: str
    kind: str
    status: str
    cwd: str
    name: str | None = None

    @property
    def project(self) -> str:
        return os.path.basename(self.cwd.rstrip("/"))


def _default_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


class HerdrClient:
    def __init__(self, run_cli=None) -> None:
        self._run = run_cli or _default_run

    def _call(self, *args: str) -> dict:
        try:
            proc = self._run(["herdr", *args])
        except FileNotFoundError:
            raise HerdrError("herdr_missing", "herdr CLI not found on PATH") from None
        except subprocess.TimeoutExpired:
            raise HerdrError("timeout", f"herdr {' '.join(args)} timed out") from None
        for stream in (proc.stdout, proc.stderr):
            stripped = (stream or "").strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except ValueError:
                continue
            if "error" in payload:
                err = payload["error"]
                raise HerdrError(err.get("code", "cli_error"), err.get("message", stripped))
            return payload
        if proc.returncode != 0:
            raise HerdrError("cli_error", (proc.stderr or proc.stdout or "herdr failed").strip())
        return {}

    def list_agents(self) -> list[AgentInfo]:
        payload = self._call("agent", "list")
        return [
            AgentInfo(pane_id=a["pane_id"], kind=a["agent"], status=a["agent_status"],
                      cwd=a["cwd"], name=a.get("name"))
            for a in payload["result"]["agents"]
        ]

    def read_agent(self, pane_id: str, lines: int = 200) -> str:
        payload = self._call("agent", "read", pane_id, "--source", "recent-unwrapped",
                             "--format", "ansi", "--lines", str(lines))
        return payload["result"]["read"]["text"]

    def prompt_agent(self, pane_id: str, text: str) -> None:
        self._call("pane", "run", pane_id, text)

    def send_key(self, pane_id: str, key: str) -> None:
        if len(key) == 1:
            self._call("pane", "send-text", pane_id, key)
        else:
            self._call("pane", "send-keys", pane_id, key)
