#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["textual==8.2.8"]
# ///
"""Generate the docs/demo-*.svg screenshots used in the README.

Drives HerdrMobileApp headlessly (Textual's run_test harness) against a
fake HerdrClient with a handful of generic agents, then exports two SVG
screenshots via App.export_screenshot():

  docs/demo-list.svg   - the agent list screen (triage order, status icons)
  docs/demo-detail.svg - a blocked agent's detail screen, remote-control bar
                         auto-opened, showing the tappable key row

No real herdr instance or network access is used -- everything is
synthetic. Run with: uv run scripts/make_demo.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from herdr_mobile import AccessHistoryStore, AgentInfo, HerdrMobileApp, PromptHistoryStore  # noqa: E402

DOCS_DIR = REPO_ROOT / "docs"

DEMO_SIZE = (50, 32)


class FakeHerdrClient:
    """Minimal stand-in for HerdrClient -- same shape as tests/conftest.py's,
    kept inline here so this script has no test-suite dependency."""

    def __init__(self, agents, reads=None):
        self.agents = agents
        self.reads = reads or {}

    def list_agents(self):
        return list(self.agents)

    def read_agent(self, pane_id, lines=200):
        return self.reads.get(pane_id, "")

    def prompt_agent(self, pane_id, text):
        pass

    def send_key(self, pane_id, key):
        pass


DEMO_AGENTS = [
    AgentInfo(pane_id="w3:p1", kind="claude", status="working", cwd="/home/dev/projects/web-app"),
    AgentInfo(pane_id="wA:p1", kind="claude", status="blocked", cwd="/home/dev/projects/api-server"),
    AgentInfo(pane_id="wC:p1", kind="claude", status="done", cwd="/home/dev/projects/infra"),
    AgentInfo(pane_id="w7:p2", kind="pi", status="idle", cwd="/home/dev/projects/docs-site", name="docs-site"),
]

BLOCKED_OUTPUT = "\n".join([
    "⏺ I'll update the deploy config for the new environment.",
    "⏺ Bash: kubectl apply -f deploy/staging.yaml",
    "",
    "Allow this action?",
    "  1. Yes",
    "  2. Yes, and don't ask again",
    "  3. No, and tell Claude what to do differently",
])


async def make_demo() -> None:
    DOCS_DIR.mkdir(exist_ok=True)

    # Scratch history paths: HerdrMobileApp(client=...) with no explicit
    # history=/access_history= would otherwise read/write the REAL
    # ~/.local/state/herdr-mobile/{prompt,access}_history.json (the detail
    # screenshot below calls open_agent(), which records access history) --
    # same isolation the test suite's conftest.py fixtures apply, needed
    # here too since this script runs outside pytest.
    with tempfile.TemporaryDirectory() as scratch_dir:
        scratch = Path(scratch_dir)

        def fresh_histories():
            return (PromptHistoryStore(scratch / "prompt_history.json"),
                    AccessHistoryStore(scratch / "access_history.json"))

        # --- list screen ---------------------------------------------
        client = FakeHerdrClient(agents=DEMO_AGENTS)
        history, access_history = fresh_histories()
        app = HerdrMobileApp(client=client, history=history, access_history=access_history)
        async with app.run_test(size=DEMO_SIZE) as pilot:
            await pilot.pause()
            svg = app.export_screenshot(title="herdr-mobile")
            (DOCS_DIR / "demo-list.svg").write_text(svg)

        # --- detail screen (blocked agent, remote bar auto-shown) -----
        client = FakeHerdrClient(agents=DEMO_AGENTS, reads={"wA:p1": BLOCKED_OUTPUT})
        history, access_history = fresh_histories()
        app = HerdrMobileApp(client=client, history=history, access_history=access_history)
        async with app.run_test(size=DEMO_SIZE) as pilot:
            await pilot.pause()
            app.open_agent("wA:p1")
            await pilot.pause()
            svg = app.export_screenshot(title="herdr-mobile")
            (DOCS_DIR / "demo-detail.svg").write_text(svg)

    print(f"Wrote {DOCS_DIR / 'demo-list.svg'}")
    print(f"Wrote {DOCS_DIR / 'demo-detail.svg'}")


if __name__ == "__main__":
    asyncio.run(make_demo())
