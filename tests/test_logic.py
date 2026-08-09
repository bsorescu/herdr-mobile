from herdr_remote import (
    AgentInfo,
    PROJECT_CHIP_STYLE,
    build_header_text,
    collapse_wide_rules,
    effective_status,
    normalize_bullet_spacing,
    sort_agents,
    strip_ansi,
    trim_trailing_chrome,
)


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


def test_build_header_text_plain_text_contains_all_parts():
    a = AgentInfo(pane_id="wA:p1", kind="claude", status="blocked", cwd="/dev/AiMate")
    text = build_header_text(a, "blocked")
    plain = text.plain
    assert "wA:p1" in plain
    assert "claude" in plain
    assert "AiMate" in plain
    assert "blocked" in plain


def test_build_header_text_project_segment_has_green_chip_style():
    a = AgentInfo(pane_id="wA:p1", kind="claude", status="blocked", cwd="/dev/AiMate")
    text = build_header_text(a, "blocked")
    green_spans = [s for s in text.spans if s.style == PROJECT_CHIP_STYLE]
    assert len(green_spans) == 1
    span = green_spans[0]
    # The chip covers exactly " {project} " — padded, nothing else styled.
    assert text.plain[span.start:span.end] == " AiMate "


def test_collapse_wide_rules_right_aligns_name_to_exact_width():
    # Claude Code's input-box border: one ~170-char rule with the session
    # name right-aligned on it. Rebuilt to exactly `width` visible chars,
    # name chip-styled, everything before it collapsed rule fill.
    line = "─" * 150 + " herdr-remote-s0 ──"
    width = 44
    result = collapse_wide_rules(line, width=width)
    visible = strip_ansi(result)
    assert len(visible) == width
    assert visible == "─" * 25 + " herdr-remote-s0 ──"
    assert "\x1b[30;46mherdr-remote-s0\x1b[0m" in result


def test_collapse_wide_rules_pure_divider_fills_exact_width():
    line = "─" * 160  # no other text: a plain mid-content divider
    width = 44
    result = collapse_wide_rules(line, width=width)
    assert result == "─" * width


def test_collapse_wide_rules_leaves_short_rules_untouched():
    line = "── ok ──"
    result = collapse_wide_rules(line, width=44)
    assert result == line


def test_collapse_wide_rules_handles_ansi_wrapped_rule_run():
    line = "\x1b[38;2;100;100;100m" + "─" * 150 + "\x1b[0m"
    result = collapse_wide_rules(line, width=20)
    assert result == "─" * 20
    assert "\x1b" not in result


def test_collapse_wide_rules_emits_bare_chip_when_text_exceeds_width():
    line = "─" * 150 + " a-very-long-session-name-that-does-not-fit ──"
    result = collapse_wide_rules(line, width=10)
    assert result == "\x1b[30;46ma-very-long-session-name-that-does-not-fit\x1b[0m"


def test_collapse_wide_rules_falls_back_to_default_width_when_invalid():
    line = "─" * 160
    result = collapse_wide_rules(line, width=0)
    assert result == "─" * 40  # _COLLAPSE_FALLBACK_WIDTH


def test_normalize_bullet_spacing_inserts_space_when_glued():
    assert normalize_bullet_spacing("⏺main") == "⏺ main"
    assert normalize_bullet_spacing("◯general-purpose  Reviewing diff") == \
        "◯ general-purpose  Reviewing diff"
    assert normalize_bullet_spacing("⎿Read 5 lines") == "⎿ Read 5 lines"


def test_normalize_bullet_spacing_leaves_already_spaced_lines_untouched():
    line = "⏺ main"
    assert normalize_bullet_spacing(line) == line
    line2 = "◯ general-purpose  Reviewing diff"
    assert normalize_bullet_spacing(line2) == line2
    # A bullet alone on a line (nothing to glue to) is untouched too.
    assert normalize_bullet_spacing("⏺") == "⏺"


def test_normalize_bullet_spacing_handles_ansi_wrapped_glyph():
    # Bullet and reset code share a style span, text starts right after.
    line = "\x1b[32m⏺\x1b[0mmain"
    result = normalize_bullet_spacing(line)
    assert result == "\x1b[32m⏺\x1b[0m main"
    # Bullet and text share the same style span (no reset in between).
    line2 = "\x1b[32m⏺main\x1b[0m"
    result2 = normalize_bullet_spacing(line2)
    assert result2 == "\x1b[32m⏺ main\x1b[0m"


def test_normalize_bullet_spacing_only_touches_line_start():
    # A bullet glyph appearing mid-line (not a leading status marker) is
    # left alone — only the start of the line is normalized.
    line = "some text ⏺mid not touched"
    assert normalize_bullet_spacing(line) == line


def test_normalize_bullet_spacing_tolerates_leading_whitespace():
    assert normalize_bullet_spacing("  ⏺main") == "  ⏺ main"
