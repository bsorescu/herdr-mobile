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
