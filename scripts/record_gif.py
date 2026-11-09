# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.45"]
# ///
"""Record the definition builder as a GIF for the article.

Needs the app running (`make dev`) and ffmpeg. The first time, install the browser:

    uv run --with playwright playwright install chromium

Then, from anywhere:

    uv run scripts/record_gif.py

Every count is checked in a browser before recording starts. If one is wrong, nothing is recorded
and any existing GIF is left alone.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "article_assets" / "builder.gif"
URL = "http://localhost:5173"
COUNT = 'section[aria-label="Cohort"] p[aria-live="polite"]'
VIEWPORT = {"width": 1280, "height": 800}

STEP_PAUSE_MS = 1500
FINAL_HOLD_MS = 2000
COUNT_TIMEOUT_MS = 5000

GIF_FPS = 12
GIF_WIDTH = 960
MAX_GIF_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Step:
    description: str
    expected: str
    preset: str | None = None
    toggle: str | None = None


STEPS = [
    Step("Click the exact SNOMED preset", "74", preset="Exact SNOMED code"),
    Step("Turn on Type 2 complications", "152", toggle="Type 2 complications"),
    Step("Turn on Other diabetic complications", "169", toggle="Other diabetic complications"),
    Step("Turn on Prediabetes", "474", toggle="Prediabetes"),
]


class CountMismatch(Exception):
    pass


def open_builder(page: Page) -> None:
    page.goto(URL)
    page.get_by_role("button", name="Exact SNOMED code").wait_for()
    # The app selects the first preset on load. Wait for its count, so no frame shows a blank panel.
    expect(page.locator(COUNT)).to_have_text(re.compile(r"\d"), timeout=COUNT_TIMEOUT_MS)


def run_step(page: Page, step: Step) -> None:
    if step.preset:
        page.get_by_role("button", name=step.preset).click()
    else:
        page.locator("label", has_text=step.toggle).click()

    count = page.locator(COUNT)
    try:
        expect(count).to_have_text(step.expected, timeout=COUNT_TIMEOUT_MS)
    except AssertionError:
        raise CountMismatch(
            f"{step.description}: expected {step.expected}, the app shows {count.inner_text()}"
        ) from None
    print(f"  ok  {step.description}: {step.expected}")


def verify(browser) -> None:
    page = browser.new_page(viewport=VIEWPORT)
    open_builder(page)
    for step in STEPS:
        run_step(page, step)
    page.close()


def record(browser, directory: Path) -> tuple[Path, float, float]:
    """Returns the video, plus where the sequence starts and ends in it, in seconds."""
    context = browser.new_context(
        viewport=VIEWPORT, record_video_dir=directory, record_video_size=VIEWPORT
    )
    page = context.new_page()
    video_started = time.monotonic()

    open_builder(page)
    start = time.monotonic() - video_started
    for step in STEPS:
        run_step(page, step)
        page.wait_for_timeout(STEP_PAUSE_MS)
    page.wait_for_timeout(FINAL_HOLD_MS)
    end = time.monotonic() - video_started

    video = page.video
    context.close()
    return Path(video.path()), start, end


def convert(video: Path, start: float, end: float, gif: Path) -> None:
    filters = (
        f"fps={GIF_FPS},scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=stats_mode=diff[palette];"
        "[b][palette]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
            "-i", str(video),
            "-filter_complex", filters,
            str(gif),
        ],
        check=True,
    )  # fmt: skip


def main() -> int:
    if shutil.which("ffmpeg") is None:
        print("ffmpeg is not installed.", file=sys.stderr)
        return 1

    with sync_playwright() as playwright, tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        browser = playwright.chromium.launch()
        try:
            print("Checking counts, not recording yet:")
            verify(browser)
            print("Recording:")
            video, start, end = record(browser, directory)
        except CountMismatch as mismatch:
            print(f"\nStopped, nothing was recorded. {mismatch}", file=sys.stderr)
            return 1
        except PlaywrightError as error:
            print(f"\nCouldn't drive the app. Is `make dev` running?\n{error}", file=sys.stderr)
            return 1
        finally:
            browser.close()

        gif = directory / OUTPUT.name
        convert(video, start, end, gif)
        size = gif.stat().st_size
        if size > MAX_GIF_BYTES:
            print(f"The GIF is {size / 1024 / 1024:.1f} MB, over the limit.", file=sys.stderr)
            return 1
        shutil.move(gif, OUTPUT)

    print(f"Saved {OUTPUT.relative_to(ROOT)} ({size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
