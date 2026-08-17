import pytest

import herdr_mobile
from herdr_mobile import AgentInfo, HerdrError


@pytest.fixture(autouse=True)
def isolate_prompt_history(tmp_path, monkeypatch):
    """Prevent tests from touching the real
    ~/.local/state/herdr-mobile/prompt_history.json: HerdrMobileApp(client=...)
    with no explicit `history=` kwarg constructs a PromptHistoryStore() with
    no path, which resolves DEFAULT_PROMPT_HISTORY_PATH at call time —
    patched here to a per-test tmp_path so the real file is never read or
    written by the test suite.
    """
    monkeypatch.setattr(herdr_mobile, "DEFAULT_PROMPT_HISTORY_PATH", tmp_path / "prompt_history.json")


@pytest.fixture(autouse=True)
def isolate_access_history(tmp_path, monkeypatch):
    """Same isolation as isolate_prompt_history, for
    ~/.local/state/herdr-mobile/access_history.json (AccessHistoryStore)."""
    monkeypatch.setattr(herdr_mobile, "DEFAULT_ACCESS_HISTORY_PATH", tmp_path / "access_history.json")


class FakeHerdrClient:
    def __init__(self, agents=None):
        self.agents = agents or []
        self.reads = {}
        self.prompts = []
        self.keys = []
        self.errors = {}
        # Terminal-space (Feature B): configurable pane/workspace id
        # returned by create_workspace(), and a separate text store for
        # read_pane() (distinct from `reads`, which backs read_agent()).
        self.new_terminal_pane_id = "wT:p1"
        self.new_terminal_workspace_id = "wT"
        self.workspaces_created = 0
        self.pane_texts = {}
        self.pane_reads = []

    def _maybe_raise(self, method):
        if method in self.errors:
            raise self.errors[method]

    def list_agents(self):
        self._maybe_raise("list_agents")
        return list(self.agents)

    def read_agent(self, pane_id, lines=200):
        self._maybe_raise("read_agent")
        if pane_id not in {a.pane_id for a in self.agents}:
            raise HerdrError("agent_not_found", f"agent target {pane_id} not found")
        return self.reads.get(pane_id, "")

    def prompt_agent(self, pane_id, text):
        self._maybe_raise("prompt_agent")
        self.prompts.append((pane_id, text))

    def run_pane(self, pane_id, text):
        # Terminal-screen path: same recording, so flow tests can assert on
        # .prompts regardless of which send path a screen uses.
        self._maybe_raise("prompt_agent")
        self.prompts.append((pane_id, text))

    def send_key(self, pane_id, key):
        self._maybe_raise("send_key")
        self.keys.append((pane_id, key))

    def create_workspace(self):
        self._maybe_raise("create_workspace")
        self.workspaces_created += 1
        return self.new_terminal_pane_id, self.new_terminal_workspace_id

    def read_pane(self, pane_id, lines=200):
        self._maybe_raise("read_pane")
        self.pane_reads.append(pane_id)
        return self.pane_texts.get(pane_id, "")


@pytest.fixture
def agents():
    return [
        AgentInfo(pane_id="w3:p1", kind="claude", status="working", cwd="/dev/web-app"),
        AgentInfo(pane_id="wA:p1", kind="claude", status="blocked", cwd="/dev/api-server"),
        AgentInfo(pane_id="wC:p1", kind="claude", status="done", cwd="/dev/infra"),
        AgentInfo(pane_id="w7:p2", kind="pi", status="idle", cwd="/dev/docs-site", name="docs-site"),
    ]


@pytest.fixture
def fake_client(agents):
    return FakeHerdrClient(agents=agents)
