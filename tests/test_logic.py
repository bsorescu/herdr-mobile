from herdr_remote import AgentInfo, effective_status, sort_agents, strip_ansi, trim_trailing_chrome


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
        "✻ Working…",  # spinner: has letters, must survive
        "────────",
        "❯",
        "────────",
        "⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt",
    ]
    text = "\n".join(lines)
    result = trim_trailing_chrome(text)
    # Blank/separator/prompt/footer lines are gone; real content (including
    # the spinner, which has letters) survives, in original order.
    assert result == "\n".join([
        "Some real output line one",
        "Some real output line two",
        "✻ Working…",
    ])


def test_trim_trailing_chrome_keeps_agents_footer_below_status_line():
    # Regression: when Claude Code shows its agents footer BELOW the status
    # line, those lines have letters and must be kept even though they sit
    # below chrome that gets removed — the whole trailing window is scanned,
    # not just a bottom-up scan that stops at the first real content.
    lines = [
        "some real content",
        "────────",
        "❯",
        "-- INSERT -- ⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt",
        "",
        "⏺ main",
        "◯ general-purpose  Reviewing herdr_remote.py diff",
    ]
    text = "\n".join(lines)
    result = trim_trailing_chrome(text)
    assert result == "\n".join([
        "some real content",
        "⏺ main",
        "◯ general-purpose  Reviewing herdr_remote.py diff",
    ])


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
    # Dialog text lines survive; frame-only lines inside the window may go
    # (this whole block is within the trailing window) — that's fine.
    assert "Allow Bash command?" in result
    assert "1. Yes" in result
    assert "2. No" in result
    assert "2. No" in result.splitlines()[-1]


def test_trim_trailing_chrome_window_limited_to_last_thirty_lines():
    real_lines = [f"real content line {i}" for i in range(5)]
    decorative_lines = ["────"] * 35  # >30 no-alnum lines
    text = "\n".join(real_lines + decorative_lines)
    result = trim_trailing_chrome(text)
    result_lines = result.splitlines()
    # Only the trailing 30 lines are ever considered. The first 5 decorative
    # lines fall outside that window and are left untouched; the 30 inside
    # the window (the rest of the decorative lines) are all removed (no
    # alnum) — only the last 30 of the >30 no-alnum tail get removed.
    assert result_lines == real_lines + decorative_lines[:5]


def test_trim_trailing_chrome_leaves_lines_outside_window_untouched():
    # A decorative line far enough from the end (outside the trailing-30
    # window) survives even though it would be dropped inside the window.
    lines = ["line one", "───"] + [f"filler {i}" for i in range(35)]
    text = "\n".join(lines)
    result = trim_trailing_chrome(text)
    assert result == text


def test_trim_trailing_chrome_removes_ansi_wrapped_separators_and_prompt():
    # Regression: on real panes the separators/❯ are wrapped in truecolor SGR
    # sequences (e.g. "\x1b[38;2;248;248;242m"), which are full of digits and
    # letters. A naive alnum check on the raw line would treat that as "has
    # real content" and never remove it. Classification must happen on an
    # ANSI-stripped copy of the line.
    separator = "\x1b[0m\x1b[38;2;248;248;242m────────────────\x1b[0m"
    prompt = "\x1b[0m\x1b[38;2;248;248;242m❯\x1b[0m"
    status = "\x1b[0m\x1b[38;2;248;248;242m⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt\x1b[0m"
    content = "\x1b[38;2;100;200;100msome real content\x1b[0m"
    text = "\n".join([content, separator, prompt, separator, status])
    result = trim_trailing_chrome(text)
    assert result == content
    assert "auto mode on" not in result
    assert "some real content" in result


def test_strip_ansi_removes_csi_sequences():
    assert strip_ansi("\x1b[0m\x1b[38;2;248;248;242m────\x1b[0m") == "────"
    assert strip_ansi("\x1b[32mhello\x1b[0m") == "hello"
    assert strip_ansi("plain text") == "plain text"
