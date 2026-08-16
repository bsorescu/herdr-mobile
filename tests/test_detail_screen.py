from textual.widgets import Input, RichLog

from herdr_mobile import HerdrMobileApp


async def open_detail(app, pilot, pane_id="wA:p1"):
    app.open_agent(pane_id)
    await pilot.pause()
    return app.screen


async def settle_at_bottom(screen, pilot):
    """Force the RichLog to a real, settled bottom position.

    on_mount's initial scroll_end race ahead of the first layout pass in the
    test harness (max_scroll_y isn't known yet), so scroll_y can still read 0
    right after open_detail() even though the widget is logically "following".
    Tests that need a genuine non-zero starting scroll position settle here,
    the same way test_returning_to_bottom_refreshes_immediately does inline.
    """
    await pilot.pause()
    log = screen.query_one(RichLog)
    log.scroll_end(animate=False, immediate=True)
    screen.on_scroll_moved()
    return log


async def test_output_renders_and_updates(fake_client):
    fake_client.reads["wA:p1"] = "\x1b[32mAllow Bash?\x1b[0m\n> Yes / No"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        assert log.lines  # something rendered
        fake_client.reads["wA:p1"] = "NEW CONTENT"
        screen.refresh_output()
        await pilot.pause()
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "NEW CONTENT" in rendered


async def test_output_survives_crlf_line_endings(fake_client):
    # Regression: herdr's `agent read` returns \r\n-terminated lines. Rich's
    # Text.from_ansi treats a trailing \r as carriage-return-overwrite, which
    # wipes every line but the last at render time, leaving the output pane
    # blank except for one line. The fake client returns raw text unmodified
    # (bypassing HerdrClient's own normalization), so this exercises the
    # screen's own defensive stripping in refresh_output before from_ansi.
    fake_client.reads["wA:p1"] = "\x1b[32mearly line\x1b[0m\r\nmiddle line\r\nlast line"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "early line" in rendered
        assert "middle line" in rendered
        assert "last line" in rendered


async def test_output_trims_trailing_claude_chrome(fake_client):
    fake_client.reads["wA:p1"] = "\n".join([
        "some real agent output",
        "the last real line of content",
        "",
        "────────",
        "❯",
        "────────",
        "⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "auto mode on" not in rendered
        assert "the last real line of content" in rendered


async def test_output_keeps_agents_footer_below_status_line(fake_client):
    # Regression: the agents footer ("⏺ main" / "◯ general-purpose ...") can
    # render BELOW the "-- INSERT -- ... auto mode on" status line. Those
    # lines have letters and are useful, so they must survive even though
    # the chrome above them (separators, ❯, the status line) is removed.
    # (⏺/◯ get normalized to ●/○ — see test_output_normalizes_ambiguous_
    # width_glyphs — so the assertions below check for the narrow forms.)
    fake_client.reads["wA:p1"] = "\n".join([
        "some real content",
        "────────",
        "❯",
        "-- INSERT -- ⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt",
        "",
        "⏺ main",
        "◯ general-purpose  Reviewing herdr_mobile.py diff",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "auto mode on" not in rendered
        assert "-- INSERT --" not in rendered
        assert "some real content" in rendered
        assert "● main" in rendered
        assert "general-purpose" in rendered
        assert "Reviewing herdr_mobile.py diff" in rendered


async def test_output_spaces_out_glued_bullet_lines(fake_client):
    # Regression: rows felt glued together when a bullet glyph (⏺ ◯ etc.)
    # was directly followed by text with no space, e.g. from the agents
    # footer or a tool-result marker. (⏺/◯ get normalized to ●/○ first — see
    # test_output_normalizes_ambiguous_width_glyphs — so the spaced-out
    # assertions below check for the narrow forms.)
    fake_client.reads["wA:p1"] = "\n".join([
        "⏺main",
        "◯general-purpose  Reviewing herdr_mobile.py diff",
        "⎿Read 5 lines",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        rendered = [strip.text for strip in log.lines]
        assert "● main" in rendered
        assert "○ general-purpose  Reviewing herdr_mobile.py diff" in rendered
        assert "⎿ Read 5 lines" in rendered
        assert "●main" not in rendered
        assert "○general-purpose  Reviewing herdr_mobile.py diff" not in rendered
        assert "⎿Read 5 lines" not in rendered


async def test_output_normalizes_ambiguous_width_glyphs(fake_client):
    # Regression: some terminal fonts (e.g. Termius) render ⏺/◯ as
    # double-width even though Rich counts them as width 1, shifting the
    # rest of the row right and clipping its last character off-screen
    # (e.g. "⏺ main" rendered as "⏺ mai"). Substituted for safe width-1
    # equivalents (●/○) before anything else touches the text.
    fake_client.reads["wA:p1"] = "\n".join(["⏺ main", "◯ idle"])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        rendered = "\n".join(strip.text for strip in log.lines)
        assert "● main" in rendered
        assert "○ idle" in rendered
        assert "⏺" not in rendered
        assert "◯" not in rendered


async def test_output_collapses_wide_space_gaps(fake_client):
    # Regression: agent TUIs right-align stats with huge space gaps (e.g. a
    # tool-status row followed by ~100 spaces and then "6s · ... tokens"),
    # which wraps into a near-empty row plus the stats alone on their own
    # row at phone width.
    fake_client.reads["wA:p1"] = (
        "  ◯ general-purpose  Sleep briefly (footer probe)" + " " * 100 + "6s · ↓ 20.8k tokens"
    )
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "Sleep briefly (footer probe) · 6s" in rendered
        assert " " * 20 not in rendered


async def test_output_collapses_wide_input_box_border(fake_client):
    # Regression: Claude Code's input-box border is one ~170-char rule line
    # with the session name right-aligned on it. At phone width RichLog
    # wraps that into several useless all-rule "stripe" rows. It must be
    # rebuilt right-aligned to the RichLog's actual usable width, with the
    # name chip-styled (black on cyan).
    border = "─" * 150 + " herdr-remote-s0 ──"
    fake_client.reads["wA:p1"] = "\n".join(["some real content", border])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:  # portrait phone width
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        # The 170-char border collapses to exactly one row instead of
        # wrapping into several useless all-rule "stripe" rows.
        assert len(log.lines) == 2
        assert log.lines[0].text == "some real content"
        border_strip = log.lines[1]
        assert border_strip.text.endswith("herdr-remote-s0 ──")
        assert border_strip.cell_length <= log.size.width  # fits, doesn't wrap
        # The name segment carries the black-on-cyan chip style.
        name_segment = next(seg for seg in border_strip if seg.text == "herdr-remote-s0")
        assert name_segment.style is not None
        assert name_segment.style.bgcolor is not None
        assert name_segment.style.color is not None
        # The width used to build the chip line (scrollable_content_region.width)
        # must actually match the RichLog's real wrap width — confirmed by the
        # chip row fitting in exactly one row with nothing clipped off.
        assert border_strip.cell_length <= log.scrollable_content_region.width


async def test_output_inlines_detected_mode_on_session_border_row(fake_client):
    # The agent's detected permission mode is inlined directly onto the
    # session border row itself (not a separate widget) — e.g.
    # "── auto ──────────── herdr-remote-s0 ──". detect_agent_mode runs on
    # the PRE-TRIM text, since the status line it reads is exactly what
    # trim_trailing_chrome removes from the displayed output below.
    border = "─" * 150 + " herdr-remote-s0 ──"
    fake_client.reads["wA:p1"] = "\n".join([
        "some real content",
        border,
        "⏵⏵ auto mode on (ctrl+p to cycle) · esc to interrupt",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        border_strip = next(strip for strip in log.lines if "herdr-remote-s0" in strip.text)
        assert "auto" in border_strip.text  # left: the mode word
        assert border_strip.text.endswith("herdr-remote-s0 ──")  # right: the session chip
        assert border_strip.text.startswith("──")
        # No separate mode-line widget exists.
        assert len(screen.query("#mode-line")) == 0
        # The status line itself is trimmed from the displayed output.
        assert not any("auto mode on" in strip.text for strip in log.lines)


async def test_output_does_not_clip_long_lines_at_phone_width(fake_client):
    # Regression: RichLog defaults to min_width=78. At phone width (44
    # columns) that made content wrap at 78 and then get horizontally
    # CLIPPED to the actual (narrower) viewport — silently losing chunks of
    # every long line. min_width=1 forces wrapping at the real viewport
    # width instead.
    long_line = "word" + "".join(f" w{i}" for i in range(60))  # ~230 chars
    fake_client.reads["wA:p1"] = long_line
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:  # portrait phone width
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        usable_width = log.scrollable_content_region.width
        assert max(strip.cell_length for strip in log.lines) <= usable_width
        full_text = "".join(strip.text for strip in log.lines)
        assert long_line[-20:] in full_text  # nothing lost off the end


async def test_header_shows_identity_and_status(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        header = screen.query_one("#detail-header")
        text = str(header.render())
        assert "wA:p1" in text and "blocked" in text and "api-server" in text


async def test_scroll_up_pauses_follow(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        assert screen.follow is True
        log = screen.query_one(RichLog)
        log.scroll_up(animate=False)
        screen.on_scroll_moved()
        assert screen.follow is False
        # scroll_end() defers via call_after_refresh unless immediate=True (textual 8.2.8);
        # force it synchronous so on_scroll_moved() observes the new position immediately.
        log.scroll_end(animate=False, immediate=True)
        screen.on_scroll_moved()
        assert screen.follow is True


async def test_paused_follow_ignores_tick_refresh(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        log.scroll_up(animate=False)
        screen.on_scroll_moved()
        assert screen.follow is False
        rendered_before = "\n".join(str(strip) for strip in log.lines)

        # A sliding "last 200 lines" window would silently swap the text under the
        # user's eyes if refresh_output() fetched while paused. It must not.
        fake_client.reads["wA:p1"] = "SHOULD NOT APPEAR"
        screen._tick()
        await pilot.pause()

        rendered_after = "\n".join(str(strip) for strip in log.lines)
        assert rendered_after == rendered_before
        assert "SHOULD NOT APPEAR" not in rendered_after


async def test_returning_to_bottom_refreshes_immediately(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        log.scroll_up(animate=False)
        screen.on_scroll_moved()
        assert screen.follow is False

        fake_client.reads["wA:p1"] = "FRESH CONTENT"
        log.scroll_end(animate=False, immediate=True)
        screen.on_scroll_moved()
        assert screen.follow is True

        # No pilot.pause()/tick wait: the scroll-back-to-bottom path itself
        # must trigger the refresh synchronously.
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "FRESH CONTENT" in rendered


async def test_prompt_sends_and_clears(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        assert isinstance(app.focused, Input)
        await pilot.press(*"do it")
        await pilot.press("enter")
        assert fake_client.prompts == [("w3:p1", "do it")]
        assert screen.query_one("#prompt", Input).value == ""


async def test_prompt_history_suggests_and_accepts_on_right_arrow(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        await pilot.press(*"run the tests")
        await pilot.press("enter")
        assert fake_client.prompts == [("w3:p1", "run the tests")]

        # Focus again and type a prefix of the just-sent prompt.
        await pilot.press("i")
        await pilot.press(*"run the")
        await pilot.pause()  # let the suggester's async worker complete
        prompt_input = app.screen.query_one("#prompt", Input)
        assert prompt_input._suggestion == "run the tests"

        await pilot.press("right")  # accept — Input's own built-in behavior
        assert prompt_input.value == "run the tests"

        await pilot.press("enter")
        assert fake_client.prompts[-1] == ("w3:p1", "run the tests")


async def test_prompt_history_shared_across_agents(fake_client):
    # All agents share one history — a prompt sent to one agent suggests on
    # a different agent's detail screen too.
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        await pilot.press(*"run the tests")
        await pilot.press("enter")

        screen2 = await open_detail(app, pilot, "wA:p1")  # a different agent
        await pilot.press("i")
        await pilot.press(*"run the")
        await pilot.pause()
        assert screen2.query_one("#prompt", Input)._suggestion == "run the tests"


async def test_prompt_history_empty_prefix_has_no_suggestion(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        await pilot.press(*"run the tests")
        await pilot.press("enter")

        await pilot.press("i")
        await pilot.pause()
        assert app.screen.query_one("#prompt", Input)._suggestion == ""


async def test_right_arrow_does_not_conflict_with_remote_bar_while_input_focused(fake_client):
    # Regression guard: right-arrow-accepts-suggestion must work even while
    # the remote-control bar is visible — the existing "Input focused" early
    # return in AgentDetailScreen.on_key must not be shadowed by anything
    # REMOTE_KEYS-related for the prompt Input specifically.
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        await pilot.press("i")
        await pilot.press(*"do it")
        await pilot.press("left")
        await pilot.press("left")
        cursor_before = screen.query_one("#prompt", Input).cursor_position
        await pilot.press("right")
        # Plain cursor movement (no suggestion pending): moved right by one,
        # nothing forwarded to the agent as a remote key.
        assert screen.query_one("#prompt", Input).cursor_position == cursor_before + 1
        assert fake_client.keys == []


async def test_prompt_error_keeps_text(fake_client):
    from herdr_mobile import HerdrError
    fake_client.errors["prompt_agent"] = HerdrError("pane_busy", "pane not at prompt")
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        await pilot.press(*"do it")
        await pilot.press("enter")
        assert fake_client.prompts == []
        assert screen.query_one("#prompt", Input).value == "do it"


async def test_escape_blurs_input_without_sending(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        assert isinstance(app.focused, Input)
        await pilot.press(*"do it")
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen  # escape must not pop the detail screen
        assert not screen.query_one("#prompt", Input).has_focus  # blurred
        assert fake_client.prompts == []  # not sent
        assert screen.query_one("#prompt", Input).value == "do it"  # text kept


async def test_ctrl_d_is_unbound_on_agent_detail_screen(fake_client):
    # ctrl+d's priority binding is only ever added to TerminalScreen — the
    # agent detail screen has no such binding, so ctrl+d stays exactly as
    # it always was (Input's own built-in delete-right while focused;
    # navigation-wise, nothing happens).
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        await pilot.press(*"do it")
        await pilot.press("ctrl+d")
        assert app.screen is screen  # did not navigate away


def _capture_notifications(app, monkeypatch):
    notifications = []
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notifications.append((message, kwargs)))
    return notifications


async def test_stall_first_strike_is_silent(fake_client, monkeypatch):
    # A single stale-and-still-idle observation isn't enough to warn: list-poll
    # data can lag up to LIST_POLL_SECONDS behind a read that already saw
    # progress, so the first strike just marks the entry and waits.
    import herdr_mobile as hr
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        notifications = _capture_notifications(app, monkeypatch)
        await open_detail(app, pilot, "w7:p2")  # idle agent
        await pilot.press("i")
        await pilot.press(*"hi")
        await pilot.press("enter")
        assert "w7:p2" in app.pending_prompts
        app.pending_prompts["w7:p2"] -= hr.STALL_SECONDS + 1  # age the entry

        app.refresh_agents()
        await pilot.pause()
        assert "w7:p2" in app.pending_prompts  # still tracked, not yet warned
        assert not any(kw.get("severity") == "warning" for _, kw in notifications)


async def test_stall_warns_on_second_consecutive_strike(fake_client, monkeypatch):
    import herdr_mobile as hr
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        notifications = _capture_notifications(app, monkeypatch)
        await open_detail(app, pilot, "w7:p2")  # idle agent
        await pilot.press("i")
        await pilot.press(*"hi")
        await pilot.press("enter")
        assert "w7:p2" in app.pending_prompts
        app.pending_prompts["w7:p2"] -= hr.STALL_SECONDS + 1  # age the entry

        app.refresh_agents()  # first strike: silent
        await pilot.pause()
        app.refresh_agents()  # second consecutive strike: warn
        await pilot.pause()
        assert "w7:p2" not in app.pending_prompts  # consumed + warned
        warnings = [(msg, kw) for msg, kw in notifications if kw.get("severity") == "warning"]
        assert len(warnings) == 1
        message, kwargs = warnings[0]
        assert "Prompt may not have arrived" in message
        assert "idle" in message
        assert kwargs.get("title") == "prompt stall"


async def test_stall_silent_when_agent_progressed(fake_client, monkeypatch):
    import herdr_mobile as hr
    from herdr_mobile import AgentInfo
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        notifications = _capture_notifications(app, monkeypatch)
        await open_detail(app, pilot, "w7:p2")  # idle agent
        await pilot.press("i")
        await pilot.press(*"hi")
        await pilot.press("enter")
        assert "w7:p2" in app.pending_prompts

        # Agent progressed past idle/blocked before the stall window elapsed.
        fake_client.agents = [
            AgentInfo(pane_id=a.pane_id, kind=a.kind, status="working", cwd=a.cwd, name=a.name)
            if a.pane_id == "w7:p2" else a
            for a in fake_client.agents
        ]
        app.pending_prompts["w7:p2"] -= hr.STALL_SECONDS + 1  # age the entry
        app.refresh_agents()
        await pilot.pause()
        assert "w7:p2" not in app.pending_prompts  # consumed silently
        assert not any(kw.get("severity") == "warning" for _, kw in notifications)


async def test_stall_silent_if_agent_progresses_after_first_strike(fake_client, monkeypatch):
    # First refresh sees the agent still idle/blocked (a strike); before the
    # second refresh the agent progresses to "working" — no warning must
    # ever fire, and the earlier strike must not carry over.
    import herdr_mobile as hr
    from herdr_mobile import AgentInfo
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        notifications = _capture_notifications(app, monkeypatch)
        await open_detail(app, pilot, "w7:p2")  # idle agent
        await pilot.press("i")
        await pilot.press(*"hi")
        await pilot.press("enter")
        assert "w7:p2" in app.pending_prompts
        app.pending_prompts["w7:p2"] -= hr.STALL_SECONDS + 1  # age the entry

        app.refresh_agents()  # first strike
        await pilot.pause()
        assert "w7:p2" in app.pending_prompts

        fake_client.agents = [
            AgentInfo(pane_id=a.pane_id, kind=a.kind, status="working", cwd=a.cwd, name=a.name)
            if a.pane_id == "w7:p2" else a
            for a in fake_client.agents
        ]
        app.refresh_agents()  # sees progress before a second strike
        await pilot.pause()
        assert "w7:p2" not in app.pending_prompts  # consumed silently
        assert not any(kw.get("severity") == "warning" for _, kw in notifications)


async def test_remote_bar_hidden_then_toggles(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")  # working, no auto-show
        bar = screen.query_one("#remote-bar")
        assert bar.display is False
        await pilot.press("k")
        assert bar.display is True
        await pilot.press("q")
        assert bar.display is False
        assert app.screen is screen  # q closed the bar, did NOT leave the detail screen


async def test_remote_bar_autoshows_for_blocked(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked
        assert screen.query_one("#remote-bar").display is True


async def test_visible_bar_forwards_whitelisted_keys(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_detail(app, pilot, "wA:p1")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.press("y")
        assert fake_client.keys == [("wA:p1", "down"), ("wA:p1", "enter"), ("wA:p1", "y")]


async def test_visible_bar_forwards_digits_four_through_nine(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_detail(app, pilot, "wA:p1")
        await pilot.press("6")
        assert ("wA:p1", "6") in fake_client.keys


async def test_buttons_send_keys(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")
        await pilot.click("#rk-esc")
        assert ("wA:p1", "esc") in fake_client.keys


async def test_remote_bar_fits_portrait_phone(fake_client):
    # Blocked-with-6-options: the digit row grows to 1-6 (see
    # test_digit_buttons_scale_to_dialog_option_count), which is the
    # realistic worst case that must still fit a 44-col phone screen. This
    # dialog text has no y/n marker, so y/n stay hidden — only the
    # navigation core (always shown) plus the 6 digits are visible.
    from textual.widgets import Static
    fake_client.reads["wA:p1"] = "\n".join([
        "Allow this action?",
        "❯ 1. Yes",
        "  2. Yes, and don't ask again",
        "  3. No, and tell Claude what to do differently",
        "  4. Always allow for this project",
        "  5. Always allow for this session",
        "  6. Never ask again",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        bar = screen.query_one("#remote-bar")
        assert bar.display is True
        for key_name in ["up", "down", "enter", "esc", "1", "2", "3", "4", "5", "6"]:
            widget = screen.query_one(f"#rk-{key_name}")
            assert widget.display is True
            region = widget.region
            assert region.width > 0
            assert region.right <= 44, f"rk-{key_name} clipped: {region}"
            assert region.bottom <= 30, f"rk-{key_name} clipped: {region}"
        for key_name in ["y", "n", "7", "8", "9"]:
            assert screen.query_one(f"#rk-{key_name}").display is False
        hint = screen.query_one("#remote-hint", Static)
        hint_region = hint.region
        assert hint_region.width > 0
        assert hint_region.right <= 44
        assert hint_region.bottom <= 30
        # visible on screen, not just laid out off-canvas
        assert hint_region.x >= 0 and hint_region.y >= 0


async def test_button_click_works_at_portrait_size(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        await open_detail(app, pilot, "wA:p1")
        await pilot.click("#rk-esc")
        assert ("wA:p1", "esc") in fake_client.keys


async def test_u_key_scrolls_up_and_pauses_follow(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = await settle_at_bottom(screen, pilot)
        assert screen.follow is True
        scroll_before = log.scroll_y
        await pilot.press("u")
        assert log.scroll_y < scroll_before
        assert screen.follow is False


async def test_d_key_scrolls_down_and_resumes_follow(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = await settle_at_bottom(screen, pilot)
        await pilot.press("u")
        assert screen.follow is False
        for _ in range(10):
            await pilot.press("d")
            if screen.follow:
                break
        assert screen.follow is True
        assert log.is_vertical_scroll_end


async def test_u_d_typed_into_prompt_input_insert_not_scroll(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = await settle_at_bottom(screen, pilot)
        assert screen.follow is True
        await pilot.press("i")
        assert isinstance(app.focused, Input)
        scroll_before = log.scroll_y
        await pilot.press("u")
        await pilot.press("d")
        assert screen.query_one("#prompt", Input).value == "ud"
        assert log.scroll_y == scroll_before
        assert screen.follow is True  # unaffected: keys were consumed by the Input


async def test_m_key_sends_ctrl_p_to_cycle_mode(fake_client, monkeypatch):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        notifications = _capture_notifications(app, monkeypatch)
        await open_detail(app, pilot, "w3:p1")
        await pilot.press("m")
        assert ("w3:p1", "ctrl+p") in fake_client.keys
        infos = [(msg, kw) for msg, kw in notifications if kw.get("severity") == "information"]
        assert any("Mode cycle sent" in msg for msg, _ in infos)


async def test_m_typed_into_prompt_input_inserts_not_cycle(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        assert isinstance(app.focused, Input)
        await pilot.press("m")
        assert screen.query_one("#prompt", Input).value == "m"
        assert fake_client.keys == []  # nothing sent — the Input consumed it


async def test_u_scrolls_even_while_remote_bar_visible(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        log = await settle_at_bottom(screen, pilot)
        scroll_before = log.scroll_y
        await pilot.press("u")
        assert log.scroll_y < scroll_before
        assert screen.follow is False
        # u/d are not remote keys: nothing forwarded to the agent
        assert fake_client.keys == []


async def test_g_key_jumps_to_top(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        await settle_at_bottom(screen, pilot)
        assert screen.follow is True
        log = screen.query_one(RichLog)
        await pilot.press("g")
        assert log.scroll_y == 0
        assert screen.follow is False


async def test_G_key_jumps_to_bottom_and_resumes_follow(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = await settle_at_bottom(screen, pilot)
        await pilot.press("g")  # jump to top first
        assert screen.follow is False

        # Reuses the exact return-to-bottom path: content refreshes
        # synchronously, no pilot.pause()/tick wait needed.
        fake_client.reads["wA:p1"] = "FRESH CONTENT"
        await pilot.press("G")
        assert screen.follow is True
        assert log.is_vertical_scroll_end
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "FRESH CONTENT" in rendered


async def test_g_G_typed_into_prompt_input_insert_not_scroll(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = await settle_at_bottom(screen, pilot)
        assert screen.follow is True
        await pilot.press("i")
        assert isinstance(app.focused, Input)
        scroll_before = log.scroll_y
        await pilot.press("g")
        await pilot.press("G")
        assert screen.query_one("#prompt", Input).value == "gG"
        assert log.scroll_y == scroll_before
        assert screen.follow is True  # unaffected: keys were consumed by the Input


async def test_g_G_scroll_even_while_remote_bar_visible(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        log = await settle_at_bottom(screen, pilot)
        await pilot.press("g")
        assert log.scroll_y == 0
        assert screen.follow is False
        await pilot.press("G")
        assert screen.follow is True
        # g/G are not remote keys: nothing forwarded to the agent
        assert fake_client.keys == []


async def test_remote_hint_shown_with_bar_hidden_with_bar(fake_client):
    from textual.widgets import Static
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        await pilot.press("k")  # toggle the bar off
        assert screen.query_one("#remote-bar").display is False


async def test_detail_footer_fits_44_cols_with_separators(fake_client):
    # Regression: at 44 columns the old stock Footer used to truncate. The
    # detail screen now uses a custom DetailFooter that groups keys with
    # "│" separators (exit · agent actions · scroll) — every entry AND
    # both separators must actually fit on a 44-column phone screen.
    from herdr_mobile import DetailFooter, FooterEntry, FooterSeparator

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        screen = await open_detail(app, pilot)
        footer = screen.query_one(DetailFooter)
        entries = list(footer.query(FooterEntry))
        separators = list(footer.query(FooterSeparator))
        descriptions = {e.description for e in entries}
        assert descriptions == {"Back", "Ask", "Keys", "Mod", "Scr"}
        assert len(separators) == 2
        # Nothing renders past the 44-column screen edge — proves nothing
        # got silently clipped out.
        for widget in [*entries, *separators]:
            region = widget.region
            assert region.width > 0
            assert region.right <= 44, f"{widget!r} clipped: {region}"
            assert region.bottom <= 30


async def test_detail_footer_ctrl_p_still_opens_command_palette(fake_client):
    # ctrl+p is an App-level binding, independent of any Footer/custom
    # footer — must keep working even though the detail screen no longer
    # uses a stock Footer at all (so there's no "^p palette" entry to hide).
    from textual.command import CommandPalette

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        await open_detail(app, pilot)
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert any(isinstance(s, CommandPalette) for s in app.screen_stack)


async def test_detail_footer_keys_entry_tap_toggles_remote_bar(fake_client):
    # Proves the custom footer's tap wiring actually works end to end.
    from herdr_mobile import FooterEntry

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        screen = await open_detail(app, pilot, "w3:p1")  # working, no auto-show
        bar = screen.query_one("#remote-bar")
        assert bar.display is False
        keys_entry = next(e for e in screen.query(FooterEntry) if e.description == "Keys")
        await pilot.click(keys_entry)
        assert bar.display is True


async def test_digit_buttons_scale_to_dialog_option_count(fake_client):
    from textual.widgets import Button

    fake_client.reads["wA:p1"] = "\n".join([
        "Allow this action?",
        "❯ 1. Yes",
        "  2. Yes, and don't ask again",
        "  3. No, and tell Claude what to do differently",
        "  4. Always allow for this project",
        "  5. Always allow for this session",
        "  6. Never ask again",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        for i in range(1, 7):
            assert screen.query_one(f"#rk-{i}", Button).display is True
        for i in range(7, 10):
            assert screen.query_one(f"#rk-{i}", Button).display is False
        # No y/n marker in this dialog: y/n stay hidden alongside the digits.
        assert screen.query_one("#rk-y", Button).display is False
        assert screen.query_one("#rk-n", Button).display is False
        await pilot.click("#rk-6")
        assert ("wA:p1", "6") in fake_client.keys


async def test_bar_open_with_no_dialog_shows_only_navigation_core(fake_client):
    # "when I press k and there's no dialog, I don't want 1,2,3,y,n — only
    # if we actually have such a thing. Arrows can stay." The min-3 digit
    # fallback is gone entirely: no numbered options detected means no
    # digit buttons at all.
    from textual.widgets import Button

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")  # working, no auto-show
        await pilot.press("k")  # open manually — no dialog in reads
        assert screen.query_one("#remote-bar").display is True
        for key_name in ["up", "down", "enter", "esc"]:
            assert screen.query_one(f"#rk-{key_name}", Button).display is True
        assert screen.query_one("#rk-y", Button).display is False
        assert screen.query_one("#rk-n", Button).display is False
        for i in range(1, 10):
            assert screen.query_one(f"#rk-{i}", Button).display is False


async def test_non_blocked_agent_ignores_text_that_looks_like_a_dialog(fake_client):
    # Regression (screenshot-verified false positive): the user's own
    # conversation text contained "(y/n)" and numbered-list prose — they
    # were DISCUSSING the feature, there was no actual dialog. Detection
    # must be gated on the agent's effective status being "blocked", not
    # just on what the text happens to contain.
    from textual.widgets import Button

    fake_client.reads["w3:p1"] = "\n".join([
        "Let's talk about the y/n detector: it matches (y/n), [Y/n], etc.",
        "The numbered options work like this:",
        "1. count_dialog_options scans the trailing window",
        "2. detect_yn_prompt does the same for y/n markers",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")  # working, no auto-show
        await pilot.press("k")  # open manually
        assert screen.query_one("#remote-bar").display is True
        for key_name in ["up", "down", "enter", "esc"]:
            assert screen.query_one(f"#rk-{key_name}", Button).display is True
        assert screen.query_one("#rk-y", Button).display is False
        assert screen.query_one("#rk-n", Button).display is False
        for i in range(1, 10):
            assert screen.query_one(f"#rk-{i}", Button).display is False


async def test_blocked_agent_with_real_dialog_still_shows_buttons(fake_client):
    # Sanity check: gating on "blocked" must not break the real case.
    from textual.widgets import Button

    fake_client.reads["wA:p1"] = "\n".join([
        "Allow this action?",
        "❯ 1. Yes",
        "  2. Yes, and don't ask again",
        "  3. No, and tell Claude what to do differently",
    ])
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        for i in range(1, 4):
            assert screen.query_one(f"#rk-{i}", Button).display is True
        for i in range(4, 10):
            assert screen.query_one(f"#rk-{i}", Button).display is False


async def test_yn_prompt_shows_only_yn_buttons(fake_client):
    from textual.widgets import Button

    fake_client.reads["wA:p1"] = "Allow this action? (y/n)"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#rk-y", Button).display is True
        assert screen.query_one("#rk-n", Button).display is True
        for i in range(1, 10):
            assert screen.query_one(f"#rk-{i}", Button).display is False
        await pilot.click("#rk-y")
        assert ("wA:p1", "y") in fake_client.keys


async def test_remote_hint_hides_without_answer_buttons_shows_with(fake_client):
    from textual.widgets import Static

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked, no dialog in reads
        hint = screen.query_one("#remote-hint", Static)
        assert hint.display is False

        fake_client.reads["wA:p1"] = "Allow this action? (y/n)"
        screen.refresh_output()
        await pilot.pause()
        assert hint.display is True
        assert "tap buttons to answer" in str(hint.render())


async def test_auto_shown_bar_hides_when_status_leaves_blocked(fake_client):
    from herdr_mobile import AgentInfo

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        fake_client.agents = [
            AgentInfo(pane_id=a.pane_id, kind=a.kind, status="working", cwd=a.cwd, name=a.name)
            if a.pane_id == "wA:p1" else a
            for a in fake_client.agents
        ]
        app.refresh_agents()
        screen.refresh_header()
        await pilot.pause()
        assert screen.query_one("#remote-bar").display is False


async def test_manually_opened_bar_stays_open_across_blocked_to_working(fake_client):
    from herdr_mobile import AgentInfo

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        await pilot.press("k")  # close the auto-shown bar
        assert screen.query_one("#remote-bar").display is False
        await pilot.press("k")  # reopen it manually -> now user-driven
        assert screen.query_one("#remote-bar").display is True

        fake_client.agents = [
            AgentInfo(pane_id=a.pane_id, kind=a.kind, status="working", cwd=a.cwd, name=a.name)
            if a.pane_id == "wA:p1" else a
            for a in fake_client.agents
        ]
        app.refresh_agents()
        screen.refresh_header()
        await pilot.pause()
        assert screen.query_one("#remote-bar").display is True  # stays open: manual
