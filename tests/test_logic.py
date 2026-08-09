from herdr_remote import AgentInfo, effective_status, sort_agents


def make(pane_id, status):
    return AgentInfo(pane_id=pane_id, kind="claude", status=status, cwd="/tmp/proj")


def test_effective_status_done_seen_becomes_idle():
    a = make("w1:p1", "done")
    assert effective_status(a, seen=set()) == "done"
    assert effective_status(a, seen={"w1:p1"}) == "idle"
    assert effective_status(make("w1:p1", "working"), seen={"w1:p1"}) == "working"


def test_sort_agents_triage_order_and_stability():
    agents = [make("w1:p1", "idle"), make("w2:p1", "blocked"), make("w3:p1", "done"),
              make("w4:p1", "working"), make("w5:p1", "unknown"), make("w0:p1", "blocked")]
    ordered = sort_agents(agents, seen=set())
    assert [a.pane_id for a in ordered] == ["w0:p1", "w2:p1", "w3:p1", "w4:p1", "w1:p1", "w5:p1"]


def test_sort_agents_respects_seen():
    agents = [make("w1:p1", "done"), make("w2:p1", "working")]
    ordered = sort_agents(agents, seen={"w1:p1"})
    assert [a.pane_id for a in ordered] == ["w2:p1", "w1:p1"]
