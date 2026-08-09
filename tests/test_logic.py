from herdr_remote import AgentInfo, effective_status, sort_agents, trim_trailing_chrome


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


def test_trim_trailing_chrome_removes_claude_footer_but_keeps_spinner():
    lines = [
        "Some real output line one",
        "Some real output line two",
        "",
        "✻ Working…",  # spinner: has letters, must survive
        "────────",
        "❯",
        "────────",
        "⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt",
    ]
    text = "\n".join(lines)
    result = trim_trailing_chrome(text)
    assert result.splitlines()[-1] == "✻ Working…"
    assert "auto mode on" not in result
    assert "❯" not in result.splitlines()[-1:][0].replace("✻ Working…", "")
    # Nothing above the spinner line was touched.
    assert result.splitlines()[:3] == lines[:3]


def test_trim_trailing_chrome_keeps_blocked_dialog_contents():
    lines = [
        "some earlier context",
        "╭───────────────────────────╮",
        "│ Allow Bash command?                          │",
        "│                                               │",
        "│ ❯ 1. Yes                                    │",
        "│   2. No                                      │",
        "╰───────────────────────────╯",
    ]
    text = "\n".join(lines)
    result = trim_trailing_chrome(text)
    assert "Allow Bash command?" in result
    assert "1. Yes" in result
    assert "2. No" in result
    # Only the trailing frame border (no alnum) was trimmed.
    assert "2. No" in result.splitlines()[-1]


def test_trim_trailing_chrome_caps_at_fifteen_lines():
    real_lines = [f"real content line {i}" for i in range(5)]
    decorative_lines = ["────"] * 20  # 20 no-alnum lines
    text = "\n".join(real_lines + decorative_lines)
    result = trim_trailing_chrome(text)
    result_lines = result.splitlines()
    # Cap of 15: exactly 15 trailing lines removed, 5 decorative lines remain.
    assert len(result_lines) == len(real_lines) + len(decorative_lines) - 15
    assert result_lines[:5] == real_lines


def test_trim_trailing_chrome_leaves_middle_of_text_untouched():
    text = "\n".join([
        "line one",
        "───",  # decorative, but NOT trailing (middle of text)
        "line three",
    ])
    result = trim_trailing_chrome(text)
    assert result == text
