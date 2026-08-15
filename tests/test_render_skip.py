"""refresh_output() must not rewrite the log when the result would be identical.

The skip is keyed on (content, width), not content alone. There is no
on_resize handler in this app: a rotate is picked up because the next poll
re-renders at the new width. A content-only key would therefore leave a
rotated phone showing rules collapsed for the old width until the agent
happened to print something — so the width half of the key has its own test,
and it fails if the key is weakened to content alone.
"""
from textual.widgets import RichLog

from herdr_mobile import HerdrMobileApp

PANE = "\n".join(["\x1b[33m" + "─" * 170 + "\x1b[0m"] + [f"line {i}" for i in range(40)])


async def open_detail(app, pilot, pane_id="wA:p1"):
    app.open_agent(pane_id)
    await pilot.pause()
    return app.screen


def count_writes(log):
    """Record calls to log.write() without suppressing them."""
    writes = []
    original = log.write

    def counting(*args, **kwargs):
        writes.append(1)
        return original(*args, **kwargs)

    log.write = counting
    return writes


async def test_identical_content_is_not_rewritten(fake_client):
    fake_client.reads["wA:p1"] = PANE
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        screen.refresh_output()
        await pilot.pause()

        writes = count_writes(screen.query_one(RichLog))
        for _ in range(5):
            screen.refresh_output()
            await pilot.pause()

        assert writes == [], f"identical content was re-rendered {len(writes)} times"


async def test_changed_content_is_still_rendered(fake_client):
    fake_client.reads["wA:p1"] = PANE
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test() as pilot:
        screen = await open_detail(app, pilot)
        screen.refresh_output()
        await pilot.pause()

        writes = count_writes(screen.query_one(RichLog))
        fake_client.reads["wA:p1"] = PANE + "\nsomething new"
        screen.refresh_output()
        await pilot.pause()

        assert writes, "new agent output was skipped"


async def test_width_change_forces_a_rerender_of_identical_content(fake_client):
    """The regression the (content, width) key exists to prevent.

    Rotate the phone: the bytes from the agent are unchanged, but
    collapse_wide_rules must refit them to the new width. Weakening the key
    to `content` alone makes this test fail.
    """
    fake_client.reads["wA:p1"] = PANE
    app = HerdrMobileApp(client=fake_client)
    async with app.run_test(size=(40, 24)) as pilot:
        screen = await open_detail(app, pilot)
        screen.refresh_output()
        await pilot.pause()

        writes = count_writes(screen.query_one(RichLog))

        screen.refresh_output()
        await pilot.pause()
        assert writes == [], "identical content at an unchanged width was re-rendered"

        await pilot.resize_terminal(100, 24)
        await pilot.pause()
        screen.refresh_output()
        await pilot.pause()

        assert writes, "content unchanged but width changed — the render was skipped"
