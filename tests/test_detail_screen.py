from textual.widgets import Input, RichLog

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


async def test_prompt_sends_and_clears(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        assert isinstance(app.focused, Input)
        await pilot.press(*"do it")
        await pilot.press("enter")
        assert fake_client.prompts == [("w3:p1", "do it")]
        assert screen.query_one("#prompt", Input).value == ""


async def test_prompt_error_keeps_text(fake_client):
    from herdr_remote import HerdrError
    fake_client.errors["prompt_agent"] = HerdrError("pane_busy", "pane not at prompt")
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "w3:p1")
        await pilot.press("i")
        await pilot.press(*"do it")
        await pilot.press("enter")
        assert fake_client.prompts == []
        assert screen.query_one("#prompt", Input).value == "do it"


async def test_escape_blurs_input_without_sending(fake_client):
    app = HerdrRemoteApp(client=fake_client)
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
    import herdr_remote as hr
    app = HerdrRemoteApp(client=fake_client)
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
    import herdr_remote as hr
    from herdr_remote import AgentInfo
    app = HerdrRemoteApp(client=fake_client)
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
    app = HerdrRemoteApp(client=fake_client)
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
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")  # blocked
        assert screen.query_one("#remote-bar").display is True


async def test_visible_bar_forwards_whitelisted_keys(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        await open_detail(app, pilot, "wA:p1")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.press("y")
        assert fake_client.keys == [("wA:p1", "down"), ("wA:p1", "enter"), ("wA:p1", "y")]


async def test_buttons_send_keys(fake_client):
    app = HerdrRemoteApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot, "wA:p1")
        await pilot.click("#rk-esc")
        assert ("wA:p1", "esc") in fake_client.keys
