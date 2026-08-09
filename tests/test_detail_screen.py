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
        assert "⏺ main" in rendered
        assert "general-purpose" in rendered
        assert "Reviewing herdr_mobile.py diff" in rendered


async def test_output_spaces_out_glued_bullet_lines(fake_client):
    # Regression: rows felt glued together when a bullet glyph (⏺ ◯ etc.)
    # was directly followed by text with no space, e.g. from the agents
    # footer or a tool-result marker.
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
        assert "⏺ main" in rendered
        assert "◯ general-purpose  Reviewing herdr_mobile.py diff" in rendered
        assert "⎿ Read 5 lines" in rendered
        assert "⏺main" not in rendered
        assert "◯general-purpose  Reviewing herdr_mobile.py diff" not in rendered
        assert "⎿Read 5 lines" not in rendered


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


def _capture_notifications(app, monkeypatch):
    notifications = []
    monkeypatch.setattr(app, "notify", lambda message, **kwargs: notifications.append((message, kwargs)))
    return notifications


async def test_stall_warns_when_agent_stays_idle(fake_client, monkeypatch):
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
    # realistic worst case that must still fit a 44-col phone screen.
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
        for key_name in ["up", "down", "enter", "esc", "y", "n", "1", "2", "3", "4", "5", "6"]:
            widget = screen.query_one(f"#rk-{key_name}")
            assert widget.display is True
            region = widget.region
            assert region.width > 0
            assert region.right <= 44, f"rk-{key_name} clipped: {region}"
            assert region.bottom <= 30, f"rk-{key_name} clipped: {region}"
        for key_name in ["7", "8", "9"]:
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


async def test_remote_hint_shown_with_bar_hidden_with_bar(fake_client):
    from textual.widgets import Static
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked -> bar auto-shows
        assert screen.query_one("#remote-bar").display is True
        hint = screen.query_one("#remote-hint", Static)
        assert "n/p" in str(hint.render())
        await pilot.press("k")  # toggle the bar off
        assert screen.query_one("#remote-bar").display is False


async def test_detail_footer_fits_44_cols_and_hides_palette(fake_client):
    # Regression: at 44 columns the Footer used to truncate ("p Pr|^p
    # palette"), and the command-palette entry crowded out real bindings.
    # Every label the user relies on tapping must actually fit on screen,
    # and the palette entry must be gone (while ctrl+p itself still works —
    # that's an App-level binding, untouched by Footer(show_command_palette)).
    from textual.widgets import Footer
    from textual.widgets._footer import FooterKey

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        screen = await open_detail(app, pilot)
        footer = screen.query_one(Footer)
        keys = list(footer.query(FooterKey))
        descriptions = {k.description for k in keys}
        assert {"Back", "Prompt", "Keys", "Agent", "Scroll"} <= descriptions
        assert not any("palette" in k.description.lower() for k in keys)
        # Nothing renders past the 44-column screen edge — proves nothing
        # got silently clipped out.
        for k in keys:
            assert k.region.right <= 44, f"{k.key!r} {k.description!r} clipped: {k.region}"


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
        await pilot.click("#rk-6")
        assert ("wA:p1", "6") in fake_client.keys


async def test_digit_buttons_fall_back_to_three_without_a_dialog(fake_client):
    from textual.widgets import Button

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked, no dialog in reads
        for i in range(1, 4):
            assert screen.query_one(f"#rk-{i}", Button).display is True
        for i in range(4, 10):
            assert screen.query_one(f"#rk-{i}", Button).display is False


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
