from textual.widgets import RichLog

from herdr_remote import HerdrRemoteApp


async def open_detail(app, pilot, pane_id="wA:p1"):
    app.open_agent(pane_id)
    await pilot.pause()
    return app.screen


async def test_output_renders_and_updates(fake_client):
    fake_client.reads["wA:p1"] = "\x1b[32mAllow Bash?\x1b[0m\n> Yes / No"
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        log = screen.query_one(RichLog)
        assert log.lines  # something rendered
        fake_client.reads["wA:p1"] = "NEW CONTENT"
        screen.refresh_output()
        await pilot.pause()
        rendered = "\n".join(str(strip) for strip in log.lines)
        assert "NEW CONTENT" in rendered


async def test_header_shows_identity_and_status(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        header = screen.query_one("#detail-header")
        text = str(header.render())
        assert "wA:p1" in text and "blocked" in text and "AiMate" in text


async def test_scroll_up_pauses_follow(fake_client):
    fake_client.reads["wA:p1"] = "\n".join(f"line {i}" for i in range(200))
    app = HerdrRemoteApp(client=fake_client)
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
    app = HerdrRemoteApp(client=fake_client)
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
    app = HerdrRemoteApp(client=fake_client)
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
