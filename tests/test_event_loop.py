"""The polling CLI calls must not run on the event loop.

`herdr` is a subprocess with a 10s timeout. Textual services every keypress,
scroll and repaint on the event loop, so a CLI call made there freezes the
whole UI for its full duration — worst on the phone-over-SSH setup this app
exists for.

These tests measure it rather than assert a code shape: a heartbeat coroutine
ticks every 10ms while a deliberately slow client is polled, and the gap
between ticks is the stall the user would feel. Moving a poll back onto the
event loop makes them fail.
"""
import asyncio
import time

from herdr_mobile import HerdrMobileApp, TerminalScreen

CLI_LATENCY = 0.3           # a slow, but entirely plausible, herdr call
STALL_BUDGET = 0.15         # half the latency: comfortably separates the two cases
HEARTBEAT = 0.01


def slow_down(client, *names, seconds=CLI_LATENCY):
    """Make the named client methods block, the way subprocess.run does."""
    for name in names:
        real = getattr(client, name)

        def blocking(*args, _real=real, **kwargs):
            time.sleep(seconds)
            return _real(*args, **kwargs)

        setattr(client, name, blocking)
    return client


class Heartbeat:
    """Records the gap between ticks of a 10ms coroutine."""

    def __init__(self):
        self.gaps = []
        self._task = None

    async def __aenter__(self):
        async def beat():
            last = time.perf_counter()
            while True:
                await asyncio.sleep(HEARTBEAT)
                now = time.perf_counter()
                self.gaps.append(now - last)
                last = now

        self._task = asyncio.create_task(beat())
        await asyncio.sleep(0)
        self.gaps.clear()
        return self

    async def __aexit__(self, *exc):
        self._task.cancel()

    @property
    def worst(self):
        return max(self.gaps) if self.gaps else 0.0


async def test_agent_list_poll_does_not_block_the_event_loop(fake_client):
    slow_down(fake_client, "list_agents")
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await pilot.pause()
        async with Heartbeat() as hb:
            app.poll_agents()
            await app.workers.wait_for_complete()
            await pilot.pause()

    assert hb.worst < STALL_BUDGET, (
        f"event loop stalled {hb.worst*1000:.0f}ms during the agent-list poll "
        f"(CLI latency {CLI_LATENCY*1000:.0f}ms) — the call is on the event loop")


async def test_agent_output_poll_does_not_block_the_event_loop(fake_client):
    fake_client.reads["wA:p1"] = "agent output\n" * 40
    slow_down(fake_client, "read_agent")
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        screen = app.screen
        async with Heartbeat() as hb:
            screen.poll_output()
            await app.workers.wait_for_complete()
            await pilot.pause()

    assert hb.worst < STALL_BUDGET, (
        f"event loop stalled {hb.worst*1000:.0f}ms during the agent-output poll")


async def test_terminal_poll_does_not_block_the_event_loop(fake_client):
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.push_screen(TerminalScreen("wT:p1"))
        await pilot.pause()
        screen = app.screen
        fake_client.pane_texts["wT:p1"] = "shell output\n" * 40
        slow_down(fake_client, "read_pane")
        async with Heartbeat() as hb:
            screen.poll_output()
            await app.workers.wait_for_complete()
            await pilot.pause()

    assert hb.worst < STALL_BUDGET, (
        f"event loop stalled {hb.worst*1000:.0f}ms during the terminal poll")


async def test_worker_poll_still_renders_the_output(fake_client):
    """Off-thread must not mean off-screen: the worker path has to actually
    paint, or the stall tests above could pass by doing nothing at all."""
    fake_client.reads["wA:p1"] = "distinctive-agent-line"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#output").clear()
        screen._render_key = None

        screen.poll_output()
        await app.workers.wait_for_complete()
        await pilot.pause()

        rendered = "\n".join(str(s) for s in screen.query_one("#output").lines)
        assert "distinctive-agent-line" in rendered
