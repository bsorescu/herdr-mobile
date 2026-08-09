from herdr_remote import AgentDetailScreen, AgentListScreen, HerdrError, HerdrRemoteApp


async def test_n_p_cycle_in_list_order(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")  # first in triage order
        await pilot.pause()
        await pilot.press("n")
        assert app.screen.pane_id == "wC:p1"
        await pilot.press("n")
        assert app.screen.pane_id == "w3:p1"
        await pilot.press("p")
        assert app.screen.pane_id == "wC:p1"
        await pilot.press("p")
        await pilot.press("p")
        assert app.screen.pane_id == "w7:p2"  # wrap backwards


async def test_opening_done_agent_marks_seen(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wC:p1")
        await pilot.pause()
        assert "wC:p1" in app.seen


async def test_vanished_agent_pops_to_list(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        fake_client.agents = [a for a in fake_client.agents if a.pane_id != "wA:p1"]
        app.refresh_agents()
        app.screen.refresh_output()  # read now raises agent_not_found
        await pilot.pause()
        assert isinstance(app.screen, AgentListScreen)


async def test_server_down_at_start_shows_error_state_and_retry_recovers(fake_client):
    from textual.widgets import Static
    fake_client.errors["list_agents"] = HerdrError("connection_failed", "socket gone")
    app = HerdrRemoteApp(client=fake_client)
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
