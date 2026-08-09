import pytest

from herdr_remote import AgentInfo, HerdrError


class FakeHerdrClient:
    def __init__(self, agents=None):
        self.agents = agents or []
        self.reads = {}
        self.prompts = []
        self.keys = []
        self.errors = {}

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

    def send_key(self, pane_id, key):
        self._maybe_raise("send_key")
        self.keys.append((pane_id, key))


@pytest.fixture
def agents():
    return [
        AgentInfo(pane_id="w3:p1", kind="claude", status="working", cwd="/dev/aqos-platform"),
        AgentInfo(pane_id="wA:p1", kind="claude", status="blocked", cwd="/dev/AiMate"),
        AgentInfo(pane_id="wC:p1", kind="claude", status="done", cwd="/dev/homelab-configs"),
        AgentInfo(pane_id="w7:p2", kind="pi", status="idle", cwd="/dev/firstmate", name="firstmate"),
    ]


@pytest.fixture
def fake_client(agents):
    return FakeHerdrClient(agents=agents)
