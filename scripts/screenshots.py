"""Regenerate the README and docs screenshots from fictional demo data.

    uv run --with playwright python scripts/screenshots.py

Uses the locally installed Google Chrome (no browser download). Writes docs/images/*.png.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
import demo_data  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
PREFS = {
    "hourPx": 64,
    "colorBy": "project",
    "gap": 15,
    "span": "week",
    "logStats": True,
    "view": "calendar",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "claude"
        sys.argv = ["demo_data", str(root)]
        demo_data.main()
        port = free_port()
        server = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from cc_calendar.cli import main; main()",
                "--claude-dir",
                str(root),
                "--port",
                str(port),
                "--no-browser",
                "--notes",
                str(root / "notes.json"),
                "--search-index",
                str(Path(tmp) / "search.db"),
            ],
        )
        try:
            # The server process stands in for the live Claude Code process of one session.
            (root / "sessions" / "1.json").write_text(
                json.dumps(
                    {"pid": server.pid, "sessionId": demo_data.RUNNING_SESSION, "status": "busy"}
                )
            )
            url = f"http://127.0.0.1:{port}/"
            for _ in range(50):
                try:
                    urllib.request.urlopen(url)
                    break
                except OSError:
                    time.sleep(0.2)
            shoot(url)
        finally:
            server.terminate()
            server.wait(timeout=10)


def shoot(url: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 860},
            device_scale_factor=2,
            timezone_id="UTC",
            locale="en-US",
            color_scheme="light",
        )
        prefs = {f"cc-calendar:{k}": json.dumps(v) for k, v in PREFS.items()}
        ctx.add_init_script(
            f"for (const [k, v] of Object.entries({json.dumps(prefs)})) localStorage.setItem(k, v);"
        )
        page = ctx.new_page()
        page.clock.set_fixed_time(demo_data.NOW)
        page.goto(url)
        page.wait_for_selector(".bar")
        page.evaluate("document.getElementById('calendar').scrollTop = 8 * 64")
        page.screenshot(path=OUT / "calendar.png")

        page.click(f'.bar[data-sid="{demo_data.session_id(6)}"]')
        page.wait_for_selector("#detail .card")
        page.screenshot(path=OUT / "detail.png")

        page.get_by_role("button", name="Open log").click()
        page.wait_for_selector("#log-stats .tile")
        page.wait_for_selector("#log-body .entry")
        page.screenshot(path=OUT / "transcript.png")

        page.keyboard.press("Escape")
        page.click('#view-toggle button[data-view="list"]')
        page.wait_for_selector(".list table")
        page.screenshot(path=OUT / "list.png")

        page.keyboard.press("Escape")  # close the detail pane
        page.check("#full-text")
        page.fill("#search", "1 failed")
        page.wait_for_selector("#full-text-status:has-text('in transcripts')")
        page.wait_for_selector("#list .snippet")
        page.screenshot(path=OUT / "search.png")
        page.fill("#search", "")
        page.uncheck("#full-text")

        page.keyboard.press("Escape")
        page.click('#view-toggle button[data-view="calendar"]')
        page.click('#span-toggle button[data-span="month"]')
        page.wait_for_selector(".month-day")
        page.screenshot(path=OUT / "month.png")

        page.click('#view-toggle button[data-view="list"]')
        page.locator("#list .project-link", has_text="acme-web").first.click()
        page.wait_for_selector("#project-view .project-body")
        page.screenshot(path=OUT / "project.png")

        # Panes above the week calendar, one at a time.
        page.goto(url + "#view=calendar&span=week&date=2026-09-28")
        page.wait_for_selector(".bar")
        for name, pane in [
            ("summary", "summary"),
            ("costs", "costs-pane"),
            ("requests", "requests-pane"),
            ("hours", "hours-pane"),
            ("tools", "tools-pane"),
            ("prs", "prs-pane"),
        ]:
            toggle = "summary-toggle" if name == "summary" else f"{name}-toggle"
            page.click(f"#{toggle}")
            page.wait_for_selector(f"#{pane}:not([hidden]) table, #{pane}:not([hidden]) .hours")
            page.wait_for_timeout(300)
            # The whole pane, without its scroll limit.
            el = page.locator(f"#{pane}")
            el.evaluate("e => { e.style.maxHeight = 'none'; }")
            el.screenshot(path=OUT / f"{name}.png")
            el.evaluate("e => { e.style.maxHeight = ''; }")
            page.click(f"#{toggle}")

        # The day view with its Parallel column, on a day with overlapping sessions.
        page.goto(url + "#view=calendar&span=day&date=2026-09-30")
        page.wait_for_selector(".conc-head")
        page.evaluate("document.getElementById('calendar').scrollTop = 8 * 64")
        page.screenshot(path=OUT / "day.png")

        # Friction and context size further down the detail pane.
        page.goto(url + "#view=calendar&span=week&date=2026-09-28")
        page.click(f'.bar[data-sid="{demo_data.session_id(6)}"]')
        page.wait_for_selector("#detail .ctx-chart")
        page.wait_for_timeout(500)
        page.locator("#detail .ctx-chart").evaluate("e => e.scrollIntoView({block: 'center'})")
        page.screenshot(path=OUT / "detail-context.png")

        # The month view with a budget set.
        page.evaluate(
            "localStorage.setItem('cc-calendar:budget', '300');"
            "localStorage.setItem('cc-calendar:planPrice', '200')"
        )
        page.goto(url + "#view=calendar&span=month&date=2026-10-01")
        page.wait_for_selector(".month-day")
        page.mouse.move(0, 0)  # no hover outline on a day
        page.screenshot(path=OUT / "budget.png")
        browser.close()
    for f in sorted(OUT.glob("*.png")):
        print(f"{f}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
