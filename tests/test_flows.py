from herdr_mobile import AgentDetailScreen, AgentListScreen, HerdrError, HerdrMobileApp


async def test_n_p_no_longer_cycle_agents(fake_client):
    # Agent cycling was removed 2026-08-16: navigation is q back to the
    # list, then pick a session there. n/p must be inert on the detail
    # screen (w3:p1 is "working", so the remote bar stays hidden and
    # nothing else claims the keys).
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("w3:p1")
        await pilot.pause()
        await pilot.press("n")
        await pilot.press("p")
        assert isinstance(app.screen, AgentDetailScreen)
        assert app.screen.pane_id == "w3:p1"
        assert fake_client.keys == []


async def test_physical_n_answers_no_while_bar_visible(fake_client):
    # With cycling gone, "n" is no longer reserved: while the remote bar
    # is open it forwards to the agent like y/1-9 already did, so a
    # physical keyboard can answer No directly.
    fake_client.reads["wA:p1"] = "Allow this action? (y/n)"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")  # blocked -> bar auto-shows
        await pilot.pause()
        assert app.screen.query_one("#remote-bar").display is True
        await pilot.press("n")
        assert ("wA:p1", "n") in fake_client.keys


async def test_opening_done_agent_marks_seen(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wC:p1")
        await pilot.pause()
        assert "wC:p1" in app.seen


async def test_vanished_agent_pops_to_list(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        fake_client.agents = [a for a in fake_client.agents if a.pane_id != "wA:p1"]
        app.refresh_agents()
        app.screen.refresh_output()  # read now raises agent_not_found
        await pilot.pause()
        assert isinstance(app.screen, AgentListScreen)


async def test_vanished_agent_pops_to_list_while_follow_paused(fake_client):
    from textual.widgets import RichLog
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        screen = app.screen
        fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
        screen.refresh_output()
        await pilot.pause()
        log = screen.query_one(RichLog)
        log.scroll_up(animate=False)
        screen.on_scroll_moved()
        assert screen.follow is False  # follow paused: refresh_output() alone
        # would silently no-op and never notice the agent is gone.

        fake_client.agents = [a for a in fake_client.agents if a.pane_id != "wA:p1"]
        app.refresh_agents()
        screen._tick()
        await pilot.pause()
        assert isinstance(app.screen, AgentListScreen)


async def test_server_down_at_start_shows_error_state_and_retry_recovers(fake_client):
    from textual.widgets import Static
    fake_client.errors["list_agents"] = HerdrError("connection_failed", "socket gone")
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        error_box = app.screen.query_one("#list-error", Static)
        assert error_box.display is True
        assert "socket gone" in str(error_box.render())
        del fake_client.errors["list_agents"]
        await pilot.press("r")
        await pilot.pause()
        assert app.screen.query_one("#list-error", Static).display is False
        from textual.widgets import DataTable
        assert app.screen.query_one(DataTable).row_count == 4
