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

import herdr_mobile
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


# The three tests above drive poll_output()/poll_agents() by hand, so they pass
# even if the timer is wired straight back to the blocking call. These drive the
# real timer instead: they shrink the poll interval and let Textual fire it, so
# reverting _tick() to refresh_output(), or set_interval to refresh_agents,
# fails here.

TIMER_INTERVAL = 0.05
TIMER_WINDOW = 0.4          # long enough for several ticks at 50ms


async def test_list_timer_does_not_block_the_event_loop(fake_client, monkeypatch):
    monkeypatch.setattr(herdr_mobile, "LIST_POLL_SECONDS", TIMER_INTERVAL)
    slow_down(fake_client, "list_agents")
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        await pilot.pause()
        async with Heartbeat() as hb:
            await asyncio.sleep(TIMER_WINDOW)
        # No wait_for_complete(): exclusive=True deliberately cancels the
        # superseded workers here, and waiting on a cancelled one raises.

    assert hb.worst < STALL_BUDGET, (
        f"event loop stalled {hb.worst*1000:.0f}ms while the list timer ran — "
        f"the timer is calling the blocking path")


async def test_detail_timer_does_not_block_the_event_loop(fake_client, monkeypatch):
    monkeypatch.setattr(herdr_mobile, "READ_POLL_SECONDS", TIMER_INTERVAL)
    fake_client.reads["wA:p1"] = "agent output\n" * 40
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        # Slow the client only after mount, so the initial synchronous
        # refresh_output() is not what we end up measuring.
        slow_down(fake_client, "read_agent")
        async with Heartbeat() as hb:
            await asyncio.sleep(TIMER_WINDOW)
        # No wait_for_complete(): exclusive=True deliberately cancels the
        # superseded workers here, and waiting on a cancelled one raises.

    assert hb.worst < STALL_BUDGET, (
        f"event loop stalled {hb.worst*1000:.0f}ms while the detail timer ran — "
        f"_tick() is calling the blocking path")


async def test_terminal_timer_does_not_block_the_event_loop(fake_client, monkeypatch):
    monkeypatch.setattr(herdr_mobile, "READ_POLL_SECONDS", TIMER_INTERVAL)
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.push_screen(TerminalScreen("wT:p1"))
        await pilot.pause()
        fake_client.pane_texts["wT:p1"] = "shell output\n" * 40
        slow_down(fake_client, "read_pane")
        async with Heartbeat() as hb:
            await asyncio.sleep(TIMER_WINDOW)
        # No wait_for_complete(): exclusive=True deliberately cancels the
        # superseded workers here, and waiting on a cancelled one raises.

    assert hb.worst < STALL_BUDGET, (
        f"event loop stalled {hb.worst*1000:.0f}ms while the terminal timer ran")


# _render_output() re-checks on the event-loop side what poll_output() checked on
# the worker side. That double check is the stated justification for the split,
# so it gets its own tests rather than being taken on trust.

def rendered_text(screen):
    return "\n".join(str(s) for s in screen.query_one("#output").lines)


async def test_render_is_dropped_when_the_screen_was_popped(fake_client):
    """A read in flight when the user goes back must not paint over the list."""
    fake_client.reads["wA:p1"] = "first"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        screen = app.screen
        # Hold the widget: once the screen is popped it is no longer queryable.
        log = screen.query_one("#output")
        writes = []
        log.write = lambda *a, **k: writes.append(1)

        app.pop_screen()
        await pilot.pause()

        screen._render_output("late content from a read that was already running")
        await pilot.pause()

        assert writes == [], "a read that finished after the screen was popped still painted"


async def test_render_is_dropped_when_the_user_scrolled_up(fake_client):
    """Content fetched before the user stopped to read must not jump them away."""
    fake_client.reads["wA:p1"] = "first"
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        app.open_agent("wA:p1")
        await pilot.pause()
        screen = app.screen
        screen.follow = False

        screen._render_output("late content from a read that was already running")
        await pilot.pause()

        assert "late content" not in rendered_text(screen)
