import dataclasses

from textual.widgets import DataTable

from herdr_remote import AgentDetailScreen, AgentListScreen, HerdrRemoteApp


async def test_list_renders_agents_in_triage_order(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        assert isinstance(app.screen, AgentListScreen)
        table = app.screen.query_one(DataTable)
        assert table.row_count == 4
        first_row = table.get_row_at(0)
        assert "wA:p1" in str(first_row)   # blocked first
        second_row = table.get_row_at(1)
        assert "wC:p1" in str(second_row)  # done second


async def test_enter_opens_detail_for_selected_agent(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert isinstance(app.screen, AgentDetailScreen)
        assert app.screen.pane_id == "wA:p1"


async def test_q_from_detail_returns_to_list_and_q_quits(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        # Default row is wA:p1 (blocked), so the remote bar auto-shows; the
        # first "q" closes it (per spec) rather than leaving the screen.
        await pilot.press("q")
        assert isinstance(app.screen, AgentDetailScreen)
        assert app.screen.query_one("#remote-bar").display is False
        await pilot.press("q")
        assert isinstance(app.screen, AgentListScreen)


async def test_list_error_shows_notification_keeps_last_list(fake_client):
    from herdr_remote import HerdrError
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        fake_client.errors["list_agents"] = HerdrError("connection_failed", "socket gone")
        app.refresh_agents()
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 4  # last good list kept


async def test_refresh_preserves_selection_by_identity_across_reorder(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        # initial triage order: wA:p1 (blocked), wC:p1 (done), w3:p1 (working), w7:p2 (idle)
        await pilot.press("j")  # move cursor from wA:p1 (row 0) to wC:p1 (row 1)
        assert app.screen._selected_pane_id() == "wC:p1"

        # promote w3:p1 to blocked -> it now sorts ahead of wC:p1, pushing wC:p1 down
        fake_client.agents = [
            dataclasses.replace(a, status="blocked") if a.pane_id == "w3:p1" else a
            for a in fake_client.agents
        ]
        app.refresh_agents()
        await pilot.pause()

        table = app.screen.query_one(DataTable)
        assert str(table.get_row_at(2)) and "wC:p1" in str(table.get_row_at(2))
        assert app.screen._selected_pane_id() == "wC:p1"  # cursor followed the agent, not the index
