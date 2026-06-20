# screenbot

`screenbot` is a consistent Python API and script-friendly CLI for screen inspection,
mouse and keyboard automation, screenshots, reusable coordinates, and image
matching. It supports direct automation and an optional seeded `human-like` mode.

## Requirements and installation

- Python 3.10 or newer
- macOS, Windows, or Linux with a graphical desktop
- [`uv`](https://docs.astral.sh/uv/) for the commands below

Install the CLI in an isolated environment:

```bash
make install
screenbot --version
screenbot --help
```

For development or library use from this checkout:

```bash
uv sync
uv run python your_script.py
```

On macOS, grant the terminal or Python executable **Accessibility** permission
for input and **Screen Recording** permission for screenshots, pixels, and image
matching. Restart it after changing permissions. Linux may require a desktop
session supported by PyAutoGUI; native Wayland sessions can restrict automation.

## Quick start

```python
from screenbot import Box, Point, ScreenBot

with ScreenBot(timeout=3, confidence=0.85) as bot:
    bot.click(Point(500, 300))
    bot.write("hello")
    bot.press("enter")

    area = Box.from_xywh(100, 100, 640, 480)
    bot.save_screenshot("artifacts/area.png", area)

    if match := bot.locate("submit.png"):
        bot.click(match.center)
```

The context manager stops any configured global kill listener. Calling
`bot.close()` directly is equivalent and is safe more than once.

## Values and accepted coordinates

Public imports are:

```python
from screenbot import (
    Box, ColorCount, ImageNotFound, Match, Pixel, Point,
    ScreenBot, ScreenBotError, VirtualDir, __version__,
)
```

`ScreenBot.Point`, `ScreenBot.Box`, and the other nested names remain available
for compatibility. New code should prefer module-level imports.

```python
point = Point(10, 20)
point.as_tuple()                 # (10, 20)
point.as_dict()                  # {"x": 10, "y": 20}
point.offset(dx=5, dy=-2)        # Point(15, 18)

box = Box.from_ltrb(10, 20, 110, 70)
box = Box.from_xywh(10, 20, 100, 50)
box.center                       # Point(60, 45)
box.as_region_tuple()            # (10, 20, 100, 50)
box.as_dict()
box.contains((20, 30))
```

Methods accepting a point support a `Point`, an `(x, y)` pair, an object with
`x` and `y`, or a saved position JSON path. Methods accepting a box support a
`Box`, four corner points, or a saved box JSON path. Boxes use half-open edges:
`left <= x < right` and `top <= y < bottom`.

`Match` exposes `x`, `y`, `width`, `height`, `confidence`, `image_path`, `scale`,
`center`, `box`, and `as_dict()`. `ColorCount` exposes `color`, `hex`, `count`,
`percentage`, and `as_dict()`. `Pixel` exposes `x`, `y`, `color`, `hex`, and
`as_dict()`.

## CLI

Normal results go to stdout and interactive instructions go to stderr. JSON
output is compact, so commands work cleanly in pipes and scripts.

### Capture coordinates

Move the pointer and press `0`; press Ctrl+C to stop the repeating mouse command:

```bash
screenbot mouse
screenbot mouse --json
screenbot mouse --save login-button.json

screenbot box
screenbot box --json
screenbot box --save toolbar.json
```

A box is the smallest axis-aligned rectangle containing four captured points;
the points may be marked in any order.

### Inspect pixels and colors

```bash
screenbot pixel
screenbot pixel --at 100 250 --json

screenbot colors screenshot.png --limit 10
screenbot colors screenshot.png --json
screenbot colors --box 0 0 500 300 --limit 20
screenbot colors --box-file toolbar.json --pixels --json
```

Color counts are ordered most-common first. `--pixels` emits screen pixels in
row-major order and is available for boxes, not image files.

### Screenshots and matching

```bash
screenbot screenshot full.png
screenbot screenshot toolbar.png --box-file toolbar.json
screenbot screenshot region.png --box 0 0 500 300

screenbot locate save-button.png
screenbot locate save-button.png --confidence 0.9 --json
screenbot locate icon.png --all --limit 20 --json
```

`locate` exits with status `1` when no match exists. Other operational failures
also return `1`; interruption returns `130`.

### Portable coordinate files

Saved position and box files store values by system ID. Capturing the same file
on another machine updates that machine only:

```json
{
  "type": "position",
  "systems": {
    "c7af2f64-250f-4982-a2cb-12d0aa19c02a": {"x": 842, "y": 517}
  }
}
```

Run `screenbot system` to print the current ID. ScreenBot creates it at
`~/.config/screenbot/system-id`, respecting `XDG_CONFIG_HOME`. Set
`SCREENBOT_SYSTEM_ID` for managed environments. Legacy flat coordinate files
remain readable.

## Configuration

```python
bot = ScreenBot(
    state=ScreenBot.DEFAULT,       # or ScreenBot.HUMAN_LIKE
    confidence=0.80,
    timeout=1.0,
    poll_interval=0.25,
    key_press_duration=0.05,
    key_release_duration=0.05,
    grayscale=True,
    scales=(1.0,),
    coordinate_file="screenbot_coords.json",
    seed=42,
    wait_time=(1, 2),             # random delay after each input action
    failsafe=True,
    kill_sequence=None,
    log=False,
)
```

`backend`, `sleeper`, `system_id`, and `log_stream` are dependency-injection
options useful for tests and embedded applications. PyAutoGUI's corner failsafe
is enabled by default. A `kill_sequence` starts a global keyboard listener and
sends SIGINT when that exact character sequence is typed.

Configuration methods return the bot for fluent setup:

```python
bot.set_state(ScreenBot.HUMAN_LIKE)
bot.set_human_like()
bot.set_fast()
bot.set_logging(True)
bot.reseed(42)
bot.configure_kill_sequence("911")
bot.stop_kill_listener()

with bot.using_state(ScreenBot.HUMAN_LIKE):
    bot.click((500, 300))
```

Read `bot.state` for the active state and `bot.is_human_like` for a boolean check.

Set a delay after every top-level input action. Explicit waits do not add it:

```python
bot = ScreenBot(wait_time=(1, 2))
bot.set_wait_time(1)       # exactly one second
bot.set_wait_time(1, 3)    # random inclusive range
bot.set_wait_time(0)       # disabled
```

## Screen inspection

```python
width, height = bot.screen_size()
center = bot.screen_center()
pointer = bot.mouse_position()

image = bot.screenshot()
region_image = bot.screenshot(box)
path = bot.save_screenshot("screen.png", box)
path = bot.capture_template("button.png", box)

rgb = bot.pixel_color()                  # current pointer
rgb = bot.pixel_color((100, 200))
matches = bot.pixel_matches((100, 200), (40, 120, 215), tolerance=5)

for color in bot.colors_in_box(box)[:10]:
    print(color.hex, color.count, color.percentage)
for color in bot.colors_in_image("screen.png"):
    print(color.as_dict())
for pixel in bot.pixels_in_box(box):
    print(pixel.as_dict())
```

RGB tolerance is per channel. Colors must contain exactly three integer channels
from `0` through `255`.

## Mouse automation

```python
bot.move_to((500, 300), duration=0.2)
bot.move_to((500, 300), duration=10)       # arrive at x, y in 10 seconds
bot.move_to_center()
bot.move_to_random(duration=10)            # random point, human path when enabled
bot.move_to_random(duration=(5, 10), padding=20)
bot.move_mouse_up(100, variation=5)
bot.move_mouse_down(100)
bot.move_mouse_left(100)
bot.move_mouse_right(100)

bot.click()                              # current pointer
bot.click((500, 300), button="left")
bot.click_xy(500, 300)
bot.click_center()
bot.double_click((500, 300))
bot.right_click((500, 300))
bot.click_box(box, padding=5)
bot.click_grid(box, columns=4, rows=7, variation=3)
bot.drag_to((900, 400), button="left", duration=0.5)
```

`click()` also accepts `clicks`, `interval`, `offset`, `jitter`, `move_only`, and
`dry_run`. It returns the resolved target point. `dry_run=True` resolves the
target without moving, clicking, logging an action delay, or sleeping.

PyAutoGUI scroll units are platform-dependent:

```python
bot.scroll(-5)
bot.scroll_random(800, direction="down", variation=100, duration=(1, 2))
bot.scroll_down(800)
bot.scroll_up(800)
```

The approximate-pixel helpers return the actual estimated pixel distance.

## Keyboard automation

```python
bot.write("hello", interval=0.05)
bot.press("enter")
bot.press("down", presses=3, interval=0.1)
bot.press_and_release("escape")

bot.hold("shift")
bot.press("a")
bot.release("shift")

bot.hotkey("control", "a")
bot.keycombo(("control", "p"), ("command", "p"))
#             Windows/Linux       macOS
```

`hotkey()` normalizes `control` to PyAutoGUI's portable `ctrl`. `keycombo()`
selects the first sequence on Windows/Linux and the second on macOS, then uses
the same hotkey implementation.

Convenience methods `press_arrow_up`, `press_arrow_down`, `press_arrow_left`,
`press_arrow_right`, `press_enter`, `press_escape`, `press_tab`, `press_space`,
`press_backspace`, `press_delete`, `press_insert`, `press_home`, `press_end`,
`press_page_up`, and `press_page_down` accept the same `presses` and `interval`
options as `press`. Use `press_function_key(1)` through `press_function_key(24)`
for function keys.

`press()` sends key-down and key-up events with a configurable dwell. It then
waits `key_release_duration` and reaffirms key-up to avoid a following shortcut
observing a stuck modifier. `hold()` intentionally keeps a key down.

## Image matching

```python
match = bot.locate("save.png", confidence=0.85, required=False)
matches = bot.locate_all("item.png", limit=10)
count = bot.count_images(["one.png", "two.png"])

match = bot.wait_for("save.png", timeout=5)
match = bot.click_image("save.png", timeout=5)
match = bot.click_first_available_image(["primary.png", "fallback.png"])
match = bot.wait_for_and_click("save.png", variation=8, button="right")
match = bot.click_random_in_image("save.png")
matches = bot.click_all_images("item.png", variation=4)
```

Matching methods accept `confidence`, `region`, `grayscale`, and `scales` where
applicable. Wait/click methods also accept `timeout` and polling `interval`.
Click helpers forward extra keyword arguments to `click`. `required=True` raises
`ImageNotFound`; optional searches return `None`. `locate_all` returns a list and
uses `limit=10` by default; pass `None` for no limit.

## Waiting and conditional actions

```python
bot.wait(1.5)
bot.wait_random(1, 3)
bot.countdown(3, message="Starting in")

dialog = bot.wait_until(
    lambda: bot.locate("dialog.png"),
    timeout=10,
    interval=0.2,
    message="dialog",
)

if bot.chance(5):
    bot.click((500, 300))
result = bot.run_with_chance(25, bot.write, "sometimes")
```

`wait_until` returns the predicate's first truthy value and raises built-in
`TimeoutError` on expiry. Chance percentages range from `0` through `100`; a
seed makes decisions repeatable. `run_with_chance` returns the action result or
`None` when skipped.

## Human-like mode

Human-like mode adds curved movement, timing variation, click dwell, target
variation, paced scrolling, and optional corrected typing mistakes. It never
changes the requested final text, key sequence, button, or final destination.
Image-click helpers choose a random point across each matched image (inside the
configured `image_padding`) instead of aiming near its center. Default mode
retains center-based image clicking and explicit `variation` behavior.

```python
bot = ScreenBot(state=ScreenBot.HUMAN_LIKE, seed=42)
bot.move_to_random(duration=10)
bot.configure_human_like(
    pause=(0.04, 0.16),
    move_duration=(0.22, 0.72),
    click_dwell=(0.035, 0.12),
    key_dwell=(0.035, 0.09),
    key_interval=(0.035, 0.14),
    typo_pause=(0.08, 0.32),
    typo_chance=0.04,
    scroll_pause=(0.04, 0.13),
    target_jitter=2,
    image_padding=3,
    path_deviation=(0.14, 0.42),
    speed_variation=(0.35, 2.40),
    overshoot_chance=0.35,
)
```

Probabilities passed to `configure_human_like` range from `0.0` to `1.0`, unlike
the percentage-based `chance()` method.

## Saved points and interactive capture

Store several named points in the configured `coordinate_file`:

```python
bot.save_point("login", (500, 300))
point = bot.get_point("login")
points = bot.list_points()
bot.click_saved("login")
deleted = bot.delete_point("login")
```

Standalone portable files use:

```python
bot.save_position_file("login.json", (500, 300))
point = bot.load_position_file("login.json")
bot.save_box_file("toolbar.json", box)
box = bot.load_box_file("toolbar.json")
```

Interactive library helpers are `capture_position_on_key`,
`capture_box_on_key`, `capture_box_on_click`, `print_pos_on_key`,
`print_pos_on_click`, `print_box_on_key`, and `print_box_on_click`. The key
capture methods use the `0` key.

`VirtualDir(base).path(*parts)` is a small compatibility helper for building
paths beneath an asset directory.

## Errors and logging

ScreenBot-specific failures derive from `ScreenBotError`. A required template
that cannot be found raises `ImageNotFound`. Invalid arguments raise `ValueError`
or `TypeError`, unreadable files raise a descriptive `ValueError`, and
`wait_until` raises `TimeoutError`.

Pass `log=True` or call `set_logging()` to write action arguments and results to
stderr. Supply `log_stream` to redirect those records.

## Development

```bash
uv sync
make test
```

`make test` runs both retained test suites. Uninstall the global CLI with
`make uninstall`.
