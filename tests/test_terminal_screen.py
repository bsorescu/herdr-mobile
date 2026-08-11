from textual.widgets import Button, Input, RichLog

from herdr_mobile import AgentInfo, HerdrMobileApp, TerminalScreen


async def open_terminal(app, pilot):
    app.open_terminal()
    await pilot.pause()
    return app.screen


async def test_o_key_creates_workspace_and_opens_terminal_screen(fake_client):
    fake_client.new_terminal_pane_id = "wT:p9"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await pilot.press("o")
        await pilot.pause()
        assert fake_client.workspaces_created == 1
        assert isinstance(app.screen, TerminalScreen)
        assert app.screen.pane_id == "wT:p9"


async def test_terminal_reads_via_read_pane_not_read_agent(fake_client):
    fake_client.pane_texts["wT:p1"] = "$ echo hi\nhi"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        assert "wT:p1" in fake_client.pane_reads
        log = screen.query_one(RichLog)
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "echo hi" in rendered
        assert "hi" in rendered


async def test_terminal_mounts_with_prompt_input_focused(fake_client):
    # Unlike the agent detail screen (navigation-first, unfocused), a
    # terminal is for typing one command after another — the user
    # shouldn't have to press "i" every time.
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        assert isinstance(app.focused, Input)
        assert app.focused is screen.query_one("#prompt", Input)


async def test_terminal_typing_immediately_lands_in_input(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        # q/u/d/i are screen-binding keys elsewhere, but with the input
        # already focused they must type into it like any other letter.
        await pilot.press(*"qud i")
        assert screen.query_one("#prompt", Input).value == "qud i"


async def test_terminal_enter_sends_keeps_focus_and_clears(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        await pilot.press(*"ls -la")
        await pilot.press("enter")
        assert fake_client.prompts == [("wT:p1", "ls -la")]
        prompt = screen.query_one("#prompt", Input)
        assert prompt.value == ""
        assert prompt.has_focus  # stays focused: unlike the agent prompt, no blur-on-send
        # Immediately usable for the next command.
        await pilot.press(*"pwd")
        await pilot.press("enter")
        assert fake_client.prompts == [("wT:p1", "ls -la"), ("wT:p1", "pwd")]


async def test_terminal_prompt_sends_via_pane_run(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        assert isinstance(app.focused, Input)
        await pilot.press(*"ls -la")
        await pilot.press("enter")
        assert fake_client.prompts == [("wT:p1", "ls -la")]
        assert screen.query_one("#prompt", Input).value == ""


async def test_terminal_stall_watch_is_disabled(fake_client):
    # A plain shell pane has no idle/blocked agent lifecycle to watch for.
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_terminal(app, pilot)
        await pilot.press(*"echo hi")
        await pilot.press("enter")
        assert app.pending_prompts == {}


async def test_terminal_esc_blurs_then_q_goes_back(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        prompt = screen.query_one("#prompt", Input)
        assert prompt.has_focus
        await pilot.press("escape")  # blurs, does not leave the screen
        assert not prompt.has_focus
        assert app.screen is screen
        await pilot.press("q")  # now reaches the screen binding
        assert app.screen is not screen
        from herdr_mobile import AgentListScreen
        assert isinstance(app.screen, AgentListScreen)


async def test_terminal_ctrl_d_exits_while_input_focused(fake_client):
    # One-key exit for the shell idiom (ctrl+d = EOF/exit a real shell) —
    # must work even though the prompt Input is focused by default (Input
    # itself binds ctrl+d to delete_right; our priority binding must win).
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        prompt = screen.query_one("#prompt", Input)
        assert prompt.has_focus
        await pilot.press("ctrl+d")
        assert app.screen is not screen
        from herdr_mobile import AgentListScreen
        assert isinstance(app.screen, AgentListScreen)


async def test_terminal_footer_back_tap_works_while_input_focused(fake_client):
    # FooterEntry calls its action directly (not App.simulate_key), so
    # tapping "Back" must work unconditionally, even with the input
    # focused by default.
    from herdr_mobile import FooterEntry

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        assert app.focused is screen.query_one("#prompt", Input)
        back_entry = next(e for e in screen.query(FooterEntry) if e.description == "Back")
        await pilot.click(back_entry)
        assert app.screen is not screen
        from herdr_mobile import AgentListScreen
        assert isinstance(app.screen, AgentListScreen)


async def test_terminal_remote_bar_is_navigation_core_only(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        bar = screen.query_one("#remote-bar")
        assert bar.display is False
        await pilot.press("escape")  # blur the input first: "k" types into it otherwise
        await pilot.press("k")
        assert bar.display is True
        for key_name in ["up", "down", "enter", "esc"]:
            widget = screen.query_one(f"#rk-{key_name}", Button)
            assert widget.display is True
        # No y/n or digit buttons exist at all (structurally absent, not
        # just hidden) — no dialog detection for a plain shell pane.
        for missing_id in ["#rk-y", "#rk-n"] + [f"#rk-{i}" for i in range(1, 10)]:
            assert len(screen.query(missing_id)) == 0


async def test_terminal_arrow_key_forwards_while_bar_visible(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        await pilot.press("escape")
        await pilot.press("k")
        assert screen.query_one("#remote-bar").display is True
        await pilot.press("down")
        await pilot.press("enter")
        assert fake_client.keys == [("wT:p1", "down"), ("wT:p1", "enter")]


async def test_terminal_q_closes_bar_then_returns_to_list(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_terminal(app, pilot)
        await pilot.press("escape")
        await pilot.press("k")
        assert screen.query_one("#remote-bar").display is True
        await pilot.press("q")  # first q closes the bar
        assert screen.query_one("#remote-bar").display is False
        assert app.screen is screen
        await pilot.press("q")  # second q goes back
        assert app.screen is not screen
        from herdr_mobile import AgentListScreen
        assert isinstance(app.screen, AgentListScreen)


async def test_terminal_agent_detected_toast_does_not_auto_navigate(fake_client, monkeypatch):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        notifications = []
        monkeypatch.setattr(app, "notify", lambda message, **kwargs: notifications.append((message, kwargs)))
        screen = await open_terminal(app, pilot)

        # The user launched claude inside the terminal pane; herdr now
        # reports it as a registered agent.
        fake_client.agents = [
            *fake_client.agents,
            AgentInfo(pane_id="wT:p1", kind="claude", status="working", cwd="/dev/scratch"),
        ]
        app.refresh_agents()
        await pilot.pause()
        screen._tick()
        await pilot.pause()

        assert app.screen is screen  # did NOT auto-navigate away
        infos = [(msg, kw) for msg, kw in notifications if kw.get("severity") == "information"]
        assert any("Agent detected" in msg for msg, _ in infos)

        # Only toasts once even if _tick runs again.
        screen._tick()
        await pilot.pause()
        infos_after = [(msg, kw) for msg, kw in notifications if kw.get("severity") == "information"]
        assert len(infos_after) == len(infos)


async def test_terminal_footer_fits_44_cols(fake_client):
    from herdr_mobile import FooterEntry, FooterSeparator, TerminalFooter

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        screen = await open_terminal(app, pilot)
        footer = screen.query_one(TerminalFooter)
        entries = list(footer.query(FooterEntry))
        separators = list(footer.query(FooterSeparator))
        descriptions = {e.description for e in entries}
        assert descriptions == {"Back", "Exit", "Ask", "Keys", "Scr"}
        assert len(separators) == 2
        for widget in [*entries, *separators]:
            region = widget.region
            assert region.width > 0
            assert region.right <= 44, f"{widget!r} clipped: {region}"
            assert region.bottom <= 30


async def test_list_footer_term_entry_fits_44_cols(fake_client):
    from textual.widgets import Footer
    from textual.widgets._footer import FooterKey

    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(44, 30)) as pilot:
        await pilot.pause()
        footer = app.screen.query_one(Footer)
        keys = list(footer.query(FooterKey))
        descriptions = {k.description for k in keys}
        assert "Term" in descriptions
        for k in keys:
            assert k.region.right <= 44, f"{k.key!r} {k.description!r} clipped: {k.region}"
