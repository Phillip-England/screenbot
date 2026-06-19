# screenbot

`screenbot` is a Python screen automation library and a script-friendly CLI. It
can inspect coordinates and colors, save reusable point and box files, automate
mouse and keyboard input, take screenshots, and locate image templates.

## Install

The project uses [`uv`](https://docs.astral.sh/uv/). Install the `screenbot`
command and its isolated Python environment with:

```bash
make install
screenbot --help
```

By default, `uv` places tool executables in `~/.local/bin`. Run `uv tool update-shell`
once if that directory is not already on your `PATH`.

For library development inside this repository:

```bash
uv sync
uv run python your_script.py
```

On macOS, grant the terminal or Python executable **Accessibility** permission
for global clicks and input, and **Screen Recording** permission for screenshots
and pixel/image inspection. These settings are under **System Settings > Privacy
& Security**. Restart the application after changing permissions.

## CLI

Every normal result is written to stdout. Interactive capture instructions are
written to stderr, which makes the commands suitable for redirects, pipes, and
command substitution.

### Mouse positions

Move the pointer and press `0` to print its coordinate. Keep pressing `0` to
print more positions; press Ctrl+C to stop:

```bash
screenbot mouse
# 842 517

screenbot mouse --json
# {"x":842,"y":517}
```

Save each captured position as a reusable position file while also printing it.
Each new `0` press updates this system's entry with the latest position:

```bash
screenbot mouse --save login-button.json
```

The file can be passed directly to library methods that accept a point.

### Boxes

Capture a rectangle by moving the pointer to each corner and pressing `0`. The
smallest axis-aligned rectangle containing the four marked positions is returned:

```bash
screenbot box
screenbot box --json
screenbot box --save toolbar.json
```

The four positions can be marked in any order.

### Portable coordinate files

Position and box files store coordinates by ScreenBot system ID. Saving an existing
file updates only the current system, so the same JSON file can be committed and
used across machines after it has been captured once on each machine:

```json
{
  "type": "position",
  "systems": {
    "c7af2f64-250f-4982-a2cb-12d0aa19c02a": {"x": 842, "y": 517}
  }
}
```

ScreenBot creates a random, non-sensitive ID on first use and stores it at
`~/.config/screenbot/system-id` (or under `XDG_CONFIG_HOME`). View it with
`screenbot system`. Set `SCREENBOT_SYSTEM_ID` to override it in containers or
managed environments. Existing flat coordinate files remain readable.

### Pixel colors

Inspect the pixel under the mouse by moving the pointer and pressing `0`, or use
a specific coordinate:

```bash
screenbot pixel
# #2878D7 40 120 215

screenbot pixel --at 100 250 --json
# {"x":100,"y":250,"rgb":[40,120,215],"hex":"#2878D7"}
```

### Image and box colors

List every unique image color from most to least common. Each row contains hex,
RGB channels, pixel count, and percentage:

```bash
screenbot colors screenshot.png
screenbot colors screenshot.png --limit 10
screenbot colors screenshot.png --limit 10 --json
```

Inspect a screen region by pressing `0` at four pointer positions, loading a saved
box, or passing coordinates explicitly:

```bash
screenbot colors --limit 20
screenbot colors --box-file toolbar.json --limit 20
screenbot colors --box 0 0 500 300 --limit 20
```

To emit every pixel instead of aggregated counts, use `--pixels`. Rows are in
top-to-bottom, left-to-right order and include screen coordinates:

```bash
screenbot colors --box-file toolbar.json --pixels
screenbot colors --box 0 0 10 10 --pixels --json
```

Use `screenbot COMMAND --help` for all options.

## Library

The CLI is built on the same `ScreenBot` class available to Python scripts:

```python
from screenbot import ScreenBot

bot = ScreenBot()

point = bot.mouse_position()
print(point.x, point.y)
bot.save_position_file("button.json", point)

box = bot.load_box_file("toolbar.json")
print(box.left, box.top, box.right, box.bottom)

print(bot.pixel_color())
for item in bot.colors_in_box(box)[:10]:
    print(item.hex, item.color, item.count, item.percentage)
```

Position and box files can be used anywhere the respective value is accepted:

```python
bot.click("button.json")
bot.save_screenshot("toolbar.png", "toolbar.json")
```

Image colors are also available without using the screen:

```python
for item in bot.colors_in_image("screenshot.png"):
    print(item.as_dict())
```

### Automation

```python
bot = ScreenBot(log=True)  # print each action to the terminal

bot.click((500, 300))
bot.double_click((500, 300))
bot.right_click((500, 300))
bot.click_box(box, padding=5)
bot.move_to((800, 400))
center = bot.screen_center()
bot.move_to_center()
bot.click_center()
bot.drag_to((900, 400))
bot.scroll(-5)

bot.maximize()  # active window
bot.minimize()  # active window
bot.websearch()  # focus the active browser's address/search bar

bot.write("hello")
bot.press("enter")  # key down, short dwell, then key up
bot.press_and_release("enter")  # explicit name for the same behavior
bot.press_arrow_up()
bot.press_arrow_down(presses=3, interval=0.1)
bot.press_arrow_left()
bot.press_arrow_right()
bot.press_enter()
bot.press_escape()
bot.press_tab()
bot.press_space()
bot.press_backspace()
bot.press_delete()
bot.press_insert()
bot.press_home()
bot.press_end()
bot.press_page_up()
bot.press_page_down()
bot.press_function_key(5)  # F1 through F24
bot.hold("shift")
bot.press("a")
bot.release("shift")
bot.hotkey("command", "a")  # use "ctrl" on Linux/Windows
```

`press()` and `press_and_release()` always send separate key-down and key-up
events. Fast mode uses `key_press_duration` (0.05 seconds by default) between
them; human-like mode randomizes the dwell using `human_key_dwell`. Use `hold()`
when a key must remain down, then pair it with `release()`.

Logging is disabled by default. Pass `log=True` to the constructor, or toggle it
while a bot is running with `bot.set_logging()` and `bot.set_logging(False)`.
Actions include their arguments and resolved result; image searches report their
matches, and waits report their duration. Logs are written to stderr by default.

The named special-key methods use PyAutoGUI's portable key names and work on
macOS, Windows, and Linux. They accept the same `presses` and `interval` options
as `press()`; operating systems may reserve some function-key combinations.

Set an automatic delay after every mouse or keyboard action. Pass one value for
an exact delay, or two values for a random delay in that inclusive range:

```python
bot.set_wait_time(3)     # exactly 3 seconds after each action
bot.set_wait_time(3, 5)  # randomly 3 to 5 seconds after each action
bot.set_wait_time(0)     # disable the automatic delay
```

Explicit waiting methods such as `wait()`, `wait_random()`, and `countdown()` do
not add the automatic action delay.

Window controls use the operating system's standard shortcut. On macOS,
`maximize()` enters full screen; on Windows it uses Win+Up; on Linux it uses
Alt+F10. `minimize()` uses Command+M, Win+Down, or Alt+F9 respectively.

`human-like` state adds varied timing, curved movement, target variation, click
dwell, and paced scrolling. The default state performs direct input:

```python
bot = ScreenBot(seed=42)

bot.set_human_like()
bot.click((500, 300))
bot.write("Human-like typing varies the cadence and corrects occasional typos.")

bot.set_fast()
bot.click((100, 100))

# Temporarily switch without changing the surrounding mode.
with bot.using_state(ScreenBot.HUMAN_LIKE):
    bot.click((100, 100))
```

Fast mode executes actions directly, aside from the short key dwell used by
`press()`. The default action delay configured with `set_wait_time()` still
applies in either mode.

Human-like typing always produces the requested final text. It uses random
intervals between keystrokes and may type an adjacent key, pause, backspace it,
and continue with the correct character. Tune or disable mistakes as needed:

```python
bot.configure_human_like(
    key_dwell=(0.03, 0.09),
    key_interval=(0.04, 0.16),
    typo_chance=0.03,       # probability per eligible letter
    typo_pause=(0.08, 0.3),
)
```

Run an action with a percentage chance. A seed makes the sequence repeatable:

```python
bot = ScreenBot(seed=42)

if bot.chance(5):
    bot.click((500, 300))

bot.run_with_chance(25, bot.write, "This runs about one time in four")
```

Percentages are from `0` through `100`. Each call makes an independent choice;
`0` never runs and `100` always runs. The action's return value is returned when
it runs, otherwise `run_with_chance()` returns `None`.

### Screenshots and image matching

```python
bot = ScreenBot(timeout=3)  # Default for wait_for and image-click helpers.

bot.save_screenshot("screen.png")
bot.save_screenshot("region.png", box)
bot.capture_template("save-button.png", box)

match = bot.locate("save-button.png", confidence=0.85)
if match:
    print(match.center, match.confidence)
    bot.click(match.center)

bot.click_image("save-button.png", confidence=0.85, timeout=5)
bot.click_first_available_image(
    ["primary-button.png", "fallback-button.png"],
    confidence=0.85,
)
bot.wait_for_and_click(
    "save-button.png",
    confidence=0.85,
    timeout=5,
    variation=8,       # vary around the center, staying inside the image
    button="right",    # "left" by default
)
```

`locate_all()` returns multiple matches, `wait_for()` polls until a match appears,
`click_first_available_image()` checks paths in order and clicks the first visible
match, `wait_for_and_click()` waits and clicks once, and `click_all_images()` clicks
all visible matches. Constructor defaults include
`confidence`, `timeout`, `poll_interval`, `grayscale`, `scales`, and
`coordinate_file`. The timeout defaults to one second and can be overridden on
individual calls; use `timeout=0` for an immediate check.

### Named points

For several coordinates in one JSON file, use the named-point API:

```python
bot = ScreenBot(coordinate_file="screenbot_coords.json")
bot.save_point("login", (500, 300))
bot.click_saved("login")
print(bot.list_points())
bot.delete_point("login")
```

## Development

```bash
uv sync
make test
```

Uninstall the global CLI with `make uninstall`.
