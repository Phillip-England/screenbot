# ScreenBot: PyAutoGUI + OpenCV Automation Helpers

`screenbot.py` is a single-file Python library for GUI automation when browser-level tools like Playwright are not enough. It helps you click coordinates, save named points, click random points in boxes, locate images on the screen with OpenCV, find pixels by color, scan screen regions for color percentages, and use OS-independent keyboard shortcuts.

This is best for automating visible desktop/browser UI, including things Playwright cannot see, such as browser PDF viewer buttons, native dialogs, desktop apps, menus, and other screen-only controls.

## What It Can Do

- Get screen size and current mouse position.
- Click exact `x, y` screen coordinates.
- Save named coordinates in JSON.
- Click with small random variation so every click is not exactly identical.
- Define `Point` and `Box` objects.
- Click the center of a box or a random point inside a box.
- Take screenshots of the full screen or a box.
- Locate an image on screen using OpenCV template matching.
- Move to or click the center of the matched image.
- Wait until an image appears, then click it.
- Find the closest pixel of a given color near an anchor point.
- Count how many pixels in a box match a color.
- Calculate what percentage of a box matches a color.
- Type text, paste text, press keys, repeat keys, and trigger OS-independent shortcuts like copy/paste/select-all/find.

## Install With uv

Create a new project:

```bash
uv init screenbot-demo
cd screenbot-demo
```

Install ScreenBot:

```bash
uv add screenbot
```

Test it:

```bash
uv run python -c "from screenbot import screen_size, mouse_position; print(screen_size()); print(mouse_position())"
```

Install the global `screenbot` command from a source checkout:

```bash
make install
```

Then inspect the mouse and screen from any directory:

```bash
screenbot pos
screenbot color
screenbot color -50
screenbot size
screenbot screenshot desktop.png
screenbot --help
```

`screenbot color` prints the RGB and hex color under the mouse. Passing a
square size, such as `-50` (or `50`), lists the unique colors in a centered
50-by-50 pixel square, most frequent first, with a pixel count. Add `--json`
to `pos`, `color`, or `size` for machine-readable output.

## Platform Notes

### macOS

You will usually need to give your terminal or IDE these permissions:

- **System Settings → Privacy & Security → Accessibility**
- **System Settings → Privacy & Security → Screen Recording**

Without those permissions, screenshots, clicking, typing, or image matching may fail.

### Linux

PyAutoGUI screenshot support may require screenshot tools depending on your desktop environment. On many Debian/Ubuntu setups:

```bash
sudo apt-get install scrot
```

Wayland can make GUI automation harder. X11 sessions are usually easier for PyAutoGUI-style automation.

### Windows

Usually works directly. Some admin-level windows may require running your terminal/IDE as administrator.

## Safety

PyAutoGUI's fail-safe is enabled by default.

Move the mouse hard into a screen corner to abort a runaway script.

You can configure this:

```python
from screenbot import configure

configure(pause=0.1, fail_safe=True)
```

Start slow. Test on harmless windows first.

## Quick Start

```python
from screenbot import Point, click, screen_size, mouse_position

print("Screen:", screen_size())
print("Mouse:", mouse_position())

click(Point(500, 300))
```

Click with random variation:

```python
from screenbot import Point, click

click(Point(500, 300), jitter_radius=5)
```

That clicks somewhere within about 5 pixels of the target point.

## Discover Coordinates

Run:

```bash
screenbot pos --watch --interval 0.25
```

Or use:

```python
from screenbot import print_mouse_position

print_mouse_position(interval=0.25)
```

Move your mouse over important UI spots and copy the printed `Point(x=..., y=...)` values.

## Save Named Coordinates

```python
from screenbot import CoordinateBook, Point

coords = CoordinateBook("coords.json")

coords.set("pdf_download_button", Point(1410, 87))
coords.set("search_box", Point(520, 160))
coords.save()
```

Use them later:

```python
from screenbot import CoordinateBook

coords = CoordinateBook("coords.json")
coords.click("pdf_download_button", jitter_radius=4)
```

Save your current mouse position:

```python
from screenbot import CoordinateBook

coords = CoordinateBook("coords.json")
coords.set_current("important_button").save()
```

## Boxes / Screen Regions

A `Box` is defined as:

```python
Box(left, top, right, bottom)
```

Example:

```python
from screenbot import Box, click_box_center, click_box_random

box = Box(100, 200, 500, 400)

click_box_center(box)
click_box_random(box)
click_box_random(box, margin=10)
```

Create from `x, y, width, height`:

```python
from screenbot import Box

box = Box.from_xywh(100, 200, 400, 200)
```

## Screenshots

Full screen:

```python
from screenbot import screenshot

screenshot(path="full-screen.png")
```

Region screenshot:

```python
from screenbot import Box, screenshot

box = Box.from_xywh(100, 100, 500, 300)
screenshot(box, path="region.png")
```

## Locate an Image on Screen

First, create a small screenshot image of the thing you want to find, for example:

```text
assets/download_button.png
```

Then:

```python
from screenbot import locate_image

match = locate_image("assets/download_button.png", confidence=0.85)

if match:
    print(match.center, match.confidence)
```

Click the image center:

```python
from screenbot import click_image

click_image("assets/download_button.png", confidence=0.85, jitter_radius=3)
```

Wait for an image, then click it:

```python
from screenbot import click_image_when_visible

click_image_when_visible(
    "assets/download_button.png",
    timeout=10,
    confidence=0.85,
    jitter_radius=3,
)
```

Search only inside part of the screen:

```python
from screenbot import Box, click_image

top_right = Box.from_xywh(1000, 0, 500, 200)
click_image("assets/download_button.png", search_box=top_right, confidence=0.85)
```

Find multiple matches:

```python
from screenbot import locate_all_images

matches = locate_all_images("assets/icon.png", confidence=0.88)
for match in matches:
    print(match.center, match.confidence)
```

## Find the Closest Pixel of a Color Near an Anchor

Colors are RGB tuples: `(red, green, blue)`.

Example: find the closest red-ish pixel near an anchor point:

```python
from screenbot import Point, find_nearest_color, click_nearest_color

anchor = Point(800, 450)
red = (255, 0, 0)

p = find_nearest_color(anchor, red, radius=150, tolerance=25)
print(p)

if p:
    click_nearest_color(anchor, red, radius=150, tolerance=25)
```

By default, `tolerance` is per-channel. So with `tolerance=10`, `(255, 0, 0)` matches pixels where:

```text
R is 245..255
G is 0..10
B is 0..10
```

You can use Euclidean color distance too:

```python
from screenbot import find_nearest_color, Point

p = find_nearest_color(
    Point(800, 450),
    (255, 0, 0),
    radius=150,
    tolerance=40,
    mode="euclidean",
)
```

## Scan a Box for Color Count or Percentage

```python
from screenbot import Box, color_stats, count_color_pixels, color_percent

box = Box.from_xywh(100, 100, 500, 300)
green = (0, 255, 0)

stats = color_stats(box, green, tolerance=20)
print(stats.count)
print(stats.percent)
```

Shortcut functions:

```python
from screenbot import Box, box_has_color_count, box_has_color_percent

box = Box.from_xywh(100, 100, 500, 300)
blue = (0, 0, 255)

if box_has_color_count(box, blue, min_count=100, tolerance=20):
    print("Box has at least 100 blue-ish pixels")

if box_has_color_percent(box, blue, min_percent=5.0, tolerance=20):
    print("At least 5% of this box is blue-ish")
```

## Keyboard and Typing

Type text:

```python
from screenbot import type_text

type_text("hello world")
```

Paste text through the clipboard:

```python
from screenbot import paste_text

paste_text("This is more reliable for long text or weird symbols.")
```

Press a key multiple times:

```python
from screenbot import press

press("tab", presses=3, interval=0.1)
press("enter")
```

Useful helpers:

```python
from screenbot import enter, escape, tab, backspace, arrow

enter()
escape()
tab(presses=3)
backspace(presses=5)
arrow("down", presses=4)
```

## OS-Independent Shortcuts

These use `Cmd` on macOS and `Ctrl` on Windows/Linux:

```python
from screenbot import select_all, copy, paste, cut, find, find_text, save

select_all()
copy()
paste()
cut()
find()
find_text("invoice")
save()
```

Browser-ish helpers:

```python
from screenbot import new_tab, close_tab, reopen_closed_tab, refresh, hard_refresh

new_tab()
close_tab()
reopen_closed_tab()
refresh()
hard_refresh()
```

Manual combo:

```python
from screenbot import hotkey, shortcut

hotkey("ctrl", "shift", "esc")
shortcut("f")  # Cmd+F on macOS, Ctrl+F elsewhere
```

## Example: Click a Browser PDF Download Button

This is the kind of thing Playwright often cannot directly click because the button belongs to the browser/PDF viewer UI, not the webpage DOM.

```python
from screenbot import click_image_when_visible

click_image_when_visible(
    "assets/chrome_pdf_download_button.png",
    timeout=8,
    confidence=0.85,
    jitter_radius=2,
)
```

A coordinate-based fallback:

```python
from screenbot import CoordinateBook, Point

coords = CoordinateBook("coords.json")
coords.set("chrome_pdf_download", Point(1412, 88)).save()

coords.click("chrome_pdf_download", jitter_radius=3)
```

## Example: Simple Visual Automation Flow

```python
from screenbot import (
    Box,
    Point,
    click,
    click_image_when_visible,
    find_text,
    paste_text,
    press,
)

# Click browser address bar-ish spot.
click(Point(450, 60), jitter_radius=3)
paste_text("https://example.com")
press("enter")

# Wait for button image and click it.
click_image_when_visible("assets/export_button.png", timeout=15, confidence=0.87)

# Use keyboard search.
find_text("Download")
press("enter")

# Click somewhere random inside a known region.
content_box = Box.from_xywh(300, 200, 600, 400)
click(content_box.random_point(margin=20))
```

## Troubleshooting

### Image matching does not find the image

Try these:

- Lower `confidence` from `0.90` to `0.85` or `0.80`.
- Use a smaller, cleaner template image.
- Make sure display scaling has not changed.
- Make sure the browser zoom level is the same as when the template was captured.
- Try `grayscale=False` if color matters.
- Restrict the search with `search_box` to make matching faster and less noisy.

### Clicks land in the wrong place

Check:

- Display scaling.
- Multiple monitor setup.
- Whether the target window moved.
- Whether your screenshot template was captured at a different zoom level.

### Nothing happens on macOS

Give your terminal or IDE Accessibility and Screen Recording permissions.

### Script is running away

Move the mouse into a screen corner. PyAutoGUI fail-safe should stop the script.

## Recommended Workflow

1. Use Playwright where the webpage DOM is available.
2. Use ScreenBot for browser UI, PDF viewer controls, desktop dialogs, and visual-only automation.
3. Prefer image matching over raw coordinates when the UI moves.
4. Prefer coordinates when the UI is stable and image matching is overkill.
5. Add `jitter_radius=2..5` when you want small click variation.
6. Keep automation slow and visible while developing.
7. Only switch to faster/headless-style flows after everything is reliable.

## Files

```text
screenbot-demo/
├── screenbot.py
├── README.md
├── coords.json
└── assets/
    ├── download_button.png
    └── export_button.png
```

## API Overview

### Geometry

```python
Point(x, y)
Box(left, top, right, bottom)
Box.from_xywh(x, y, width, height)
Box.around(center, radius)
```

### Mouse

```python
screen_size()
mouse_position()
print_mouse_position()
move_to(point, jitter_radius=0)
click(point, jitter_radius=0)
double_click(point)
right_click(point)
click_box_center(box)
click_box_random(box)
drag_to(start, end)
scroll(amount)
```

### Saved Coordinates

```python
CoordinateBook("coords.json")
coords.set(name, point)
coords.set_current(name)
coords.get(name)
coords.click(name)
coords.save()
coords.load()
```

### Screenshots and Images

```python
screenshot(path="full.png")
screenshot(box, path="region.png")
locate_image(path, confidence=0.85)
locate_all_images(path, confidence=0.85)
wait_for_image(path, timeout=10)
move_to_image(path)
click_image(path)
click_image_when_visible(path)
```

### Colors

```python
pixel_color(point)
find_nearest_color(anchor, color, radius=100, tolerance=10)
click_nearest_color(anchor, color, radius=100, tolerance=10)
color_stats(box, color, tolerance=10)
count_color_pixels(box, color, tolerance=10)
color_percent(box, color, tolerance=10)
box_has_color_count(box, color, min_count=100)
box_has_color_percent(box, color, min_percent=5.0)
```

### Keyboard

```python
press(key, presses=1)
hotkey("ctrl", "f")
shortcut("f")
type_text(text)
paste_text(text)
select_all()
copy()
cut()
paste()
undo()
redo()
find()
find_text(text)
save()
new_tab()
close_tab()
refresh()
enter()
escape()
tab()
backspace()
delete()
arrow("down")
```
