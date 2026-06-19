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

Print the current mouse coordinate:

```bash
screenbot mouse
# 842 517

screenbot mouse --json
# {"x":842,"y":517}
```

Save it as a reusable position file while also printing it:

```bash
screenbot mouse --save login-button.mouse.json
```

The file contains `{"x": ..., "y": ...}` and can be passed directly to library
methods that accept a point.

### Boxes

Capture a rectangle by moving the pointer to each corner and pressing `0`. The
smallest axis-aligned rectangle containing the four marked positions is returned:

```bash
screenbot box
screenbot box --json
screenbot box --save toolbar.box.json
```

The four positions can be marked in any order. A saved file contains `left`, `top`,
`right`, and `bottom`.

### Pixel colors

Inspect the pixel under the mouse or a specific coordinate:

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
screenbot colors --box-file toolbar.box.json --limit 20
screenbot colors --box 0 0 500 300 --limit 20
```

To emit every pixel instead of aggregated counts, use `--pixels`. Rows are in
top-to-bottom, left-to-right order and include screen coordinates:

```bash
screenbot colors --box-file toolbar.box.json --pixels
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
bot.save_position_file("button.mouse.json", point)

box = bot.load_box_file("toolbar.box.json")
print(box.left, box.top, box.right, box.bottom)

print(bot.pixel_color())
for item in bot.colors_in_box(box)[:10]:
    print(item.hex, item.color, item.count, item.percentage)
```

Position and box files can be used anywhere the respective value is accepted:

```python
bot.click("button.mouse.json")
bot.save_screenshot("toolbar.png", "toolbar.box.json")
```

Image colors are also available without using the screen:

```python
for item in bot.colors_in_image("screenshot.png"):
    print(item.as_dict())
```

### Automation

```python
bot.click((500, 300))
bot.double_click((500, 300))
bot.right_click((500, 300))
bot.click_box(box, padding=5)
bot.move_to((800, 400))
bot.drag_to((900, 400))
bot.scroll(-5)

bot.write("hello")
bot.press("enter")
bot.hotkey("command", "a")  # use "ctrl" on Linux/Windows
```

`human-like` state adds varied timing, curved movement, target variation, click
dwell, and paced scrolling. The default state performs direct input:

```python
bot = ScreenBot(state="human-like", seed=42)
bot.click((500, 300))

with bot.using_state("default"):
    bot.click((100, 100))
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
bot.save_screenshot("screen.png")
bot.save_screenshot("region.png", box)
bot.capture_template("save-button.png", box)

match = bot.locate("save-button.png", confidence=0.85)
if match:
    print(match.center, match.confidence)
    bot.click(match.center)

bot.click_image("save-button.png", confidence=0.85, timeout=5)
```

`locate_all()` returns multiple matches, `wait_for()` polls until a match appears,
and `click_all_images()` clicks all visible matches. Constructor defaults include
`confidence`, `timeout`, `poll_interval`, `grayscale`, `scales`, and
`coordinate_file`.

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
