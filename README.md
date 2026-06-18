# screenbot

`screenbot` is a small Python screen automation helper built on top of [PyAutoGUI](https://pyautogui.readthedocs.io/) and OpenCV template matching.

It is designed for scripts where you want to:

- click exact screen coordinates
- save important points by name
- define rectangular screen regions
- screenshot the screen or a region
- locate an image on screen
- wait for an image to appear
- click the center of a matched image
- add small click variation with `jitter`

The API is intentionally Pythonic: use keyword arguments instead of Go-style options structs.

```python
from screenbot import ScreenBot

bot = ScreenBot()
bot.click_image("chrome-logo.png", confidence=0.70, timeout=10, jitter=4)
```

---

## Install

### Using `pip`

```bash
pip install pyautogui pillow opencv-python numpy
```

Then copy `screenbot.py` into your project.

### Using `uv`

```bash
uv add pyautogui pillow opencv-python numpy
```

Then copy `screenbot.py` into your project.

---

## macOS permissions

On macOS, screen automation usually requires permissions before it works correctly.

Open:

```text
System Settings → Privacy & Security
```

Then allow your terminal, IDE, or Python executable in:

- **Accessibility** — required for moving/clicking the mouse
- **Screen Recording** — required for screenshots and image matching

After changing permissions, restart your terminal or IDE.

---

## Quick start

```python
from screenbot import ScreenBot

bot = ScreenBot()

print("Screen size:", bot.size)

# Click an exact point.
bot.click((500, 300))

# Click with a small random variation around the target.
bot.click((500, 300), jitter=5)

# Find and click an image on screen.
bot.click_image("assets/chrome-logo.png", confidence=0.75)
```

---

## Functional style

You do not have to create a `ScreenBot` instance. You can import functions directly.

```python
import screenbot

screenbot.click((100, 200))

match = screenbot.locate("assets/save-button.png", confidence=0.85)
if match:
    print(match.center)
    screenbot.click(match.center)
```

---

## Object style

Use `ScreenBot` when you want shared defaults.

```python
from screenbot import ScreenBot

bot = ScreenBot(
    confidence=0.85,
    timeout=8,
    interval=0.25,
    jitter=3,
    coordinate_file="coords.json",
)

bot.click_image("assets/login-button.png")
bot.click_image("assets/submit-button.png", confidence=0.90)
```

Defaults can still be overridden per call.

```python
bot.click_image("assets/icon.png", confidence=0.70, timeout=15, jitter=8)
```

---

## Points

A point is just an `x, y` screen coordinate.

```python
from screenbot import Point

p = Point(400, 250)

bot.click(p)
bot.click((400, 250))
bot.click(p.offset(dx=10, dy=-5))
```

---

## Boxes / regions

A `Box` is defined as:

```python
Box(x, y, width, height)
```

Example:

```python
from screenbot import Box

search_area = Box(0, 0, 800, 600)

match = bot.locate("assets/search-icon.png", region=search_area)
```

You can also click inside a box.

```python
button_area = Box(100, 200, 250, 80)

# Clicks a random point inside the box.
bot.click_box(button_area)

# Avoid the edges by 10 pixels.
bot.click_box(button_area, padding=10)
```

Create a box from left/top/right/bottom coordinates:

```python
box = Box.from_xyxy(left=100, top=200, right=350, bottom=280)
```

---

## Screenshots

Take a full screenshot:

```python
img = bot.screenshot()
img.save("screen.png")
```

Save a screenshot directly:

```python
bot.save_screenshot("screenshots/full.png")
```

Screenshot a region:

```python
from screenbot import Box

bot.save_screenshot("screenshots/top-left.png", region=Box(0, 0, 500, 400))
```

---

## Capture an image template

A common workflow is:

1. Screenshot a UI element.
2. Save it as a template image.
3. Later, locate that image on screen.

```python
from screenbot import Box

bot.capture_template("assets/save-button.png", Box(440, 720, 120, 40))
bot.click_image("assets/save-button.png", confidence=0.85)
```

---

## Locate an image

```python
match = bot.locate("assets/chrome-logo.png", confidence=0.80)

if match:
    print("Found at:", match.box)
    print("Center:", match.center)
    print("Score:", match.confidence)
```

`locate()` returns `None` if the image is not found.

Raise an error instead:

```python
match = bot.locate("assets/chrome-logo.png", confidence=0.80, required=True)
```

---

## Wait for an image

Use `wait_for()` when the UI needs time to load.

```python
match = bot.wait_for("assets/dashboard.png", timeout=15, confidence=0.80)
print(match.center)
```

By default, `wait_for()` raises `ImageNotFound` if the timeout expires.

Return `None` instead:

```python
match = bot.wait_for("assets/dashboard.png", timeout=15, required=False)

if match is None:
    print("Dashboard never appeared")
```

---

## Click an image

```python
bot.click_image("assets/login-button.png", confidence=0.85)
```

Wait up to 10 seconds, then click:

```python
bot.click_image("assets/login-button.png", confidence=0.85, timeout=10)
```

Move slowly before clicking:

```python
bot.click_image("assets/login-button.png", duration=0.25)
```

Right-click an image:

```python
bot.click_image("assets/file.png", button="right")
```

Double-click an image:

```python
bot.click_image("assets/app-icon.png", clicks=2, interval=0.1)
```

Move to the image without clicking:

```python
bot.click_image("assets/menu.png", move_only=True)
```

Preview an image click without touching the mouse:

```python
match = bot.click_image("assets/menu.png", dry_run=True)
print("Would click near:", match.center if match else None)
```

---

## Click variation with `jitter`

`jitter` randomly adjusts the final click inside a circular radius.

```python
bot.click((500, 300), jitter=5)
```

For image clicks:

```python
bot.click_image("assets/button.png", jitter=4)
```

This is useful when the exact center pixel is not ideal, or when you want a small amount of natural variation in a UI test.

---

## Save and reuse coordinates

```python
bot.save_point("login_button", (640, 420))
bot.click_saved("login_button")
```

Use a custom coordinate file:

```python
bot = ScreenBot(coordinate_file="my-coords.json")

bot.save_point("search_box", (300, 180))
bot.click_saved("search_box")
```

The coordinate file is plain JSON.

```json
{
  "login_button": [640, 420],
  "search_box": [300, 180]
}
```

---

## Locate multiple copies of the same image

```python
matches = bot.locate_all("assets/star-icon.png", confidence=0.82, limit=5)

for match in matches:
    print(match.center, match.confidence)
```

---

## Retina / DPI scaling

Some macOS Retina displays screenshot at a different pixel scale than the logical mouse coordinate system. `screenbot` tries to map screenshot pixels back to PyAutoGUI coordinates automatically.

If image matching seems offset:

1. Make sure your screenshot template was captured on the same display.
2. Try limiting the search with `region=Box(...)`.
3. Try template scales.

```python
bot.click_image(
    "assets/button.png",
    confidence=0.80,
    scales=(1.0, 0.75, 1.25, 0.5, 2.0),
)
```

---

## Compatibility with the older Go-style API

The newer Pythonic style is preferred:

```python
bot.click_image("chrome-logo.png", confidence=0.70, jitter=5)
```

But the old style still works:

```python
import screenbot

screenbot.ClickImage(
    "chrome-logo.png",
    screenbot.MatchOptions(confidence=0.70),
    screenbot.ClickOptions(offset_radius=5),
)
```

---

## Error handling

```python
from screenbot import ImageNotFound, ScreenBot

bot = ScreenBot()

try:
    bot.click_image("assets/submit.png", confidence=0.90, timeout=5)
except ImageNotFound as exc:
    print("Could not click submit:", exc)
```

---

## API reference

### Main class

```python
ScreenBot(
    confidence=0.80,
    timeout=0.0,
    interval=0.25,
    grayscale=True,
    scales=(1.0,),
    jitter=0,
    move_duration=0.0,
    coordinate_file="screenbot_coords.json",
    failsafe=True,
    pause=0.0,
)
```

### Common methods

```python
bot.size
bot.screen_size()
bot.screenshot(region=None)
bot.save_screenshot(path, region=None)
bot.capture_template(path, box)

bot.move_to(point, duration=None)
bot.click(point, jitter=None, duration=None, button="left", clicks=1)
bot.click_box(box, padding=0)

bot.save_point(name, point)
bot.get_point(name)
bot.click_saved(name)

bot.locate(image_path, confidence=None, region=None, required=False)
bot.locate_all(image_path, confidence=None, region=None, limit=10)
bot.wait_for(image_path, timeout=None, required=True)
bot.click_image(image_path, timeout=None, jitter=None, required=True)
```

### Functional API

```python
screenbot.screen_size()
screenbot.screenshot(region=None)
screenbot.save_screenshot(path, region=None)
screenbot.capture_template(path, box)

screenbot.move_to(point, duration=0.0)
screenbot.click(point, jitter=0, duration=0.0)
screenbot.click_box(box, padding=0)

screenbot.locate(image_path, confidence=0.80, required=False)
screenbot.locate_all(image_path, confidence=0.80, limit=10)
screenbot.wait_for(image_path, timeout=10, required=True)
screenbot.click_image(image_path, confidence=0.80, timeout=0, jitter=0)
```

---

## Troubleshooting

### `ModuleNotFoundError`

Install the dependencies into the same Python environment that runs your script.

```bash
python -m pip install pyautogui pillow opencv-python numpy
```

With `uv`:

```bash
uv add pyautogui pillow opencv-python numpy
uv run python your_script.py
```

### Screenshot is black or empty on macOS

Grant Screen Recording permission to your terminal or IDE, then restart it.

### Mouse does not move or click on macOS

Grant Accessibility permission to your terminal or IDE, then restart it.

### Image is not found

Try these in order:

1. Lower confidence slightly, such as `confidence=0.70`.
2. Capture a cleaner template image.
3. Search only the relevant area with `region=Box(...)`.
4. Try `grayscale=False` if color matters.
5. Try multiple `scales` if DPI or zoom is different.

```python
bot.click_image(
    "assets/button.png",
    confidence=0.70,
    region=Box(0, 0, 1200, 800),
    scales=(1.0, 0.75, 1.25),
)
```

### PyAutoGUI failsafe

By default, PyAutoGUI can abort if you move the mouse to a screen corner. This is a safety feature.

You can disable it, but it is usually better to keep it enabled:

```python
bot = ScreenBot(failsafe=False)
```

---

## Suggested project layout

```text
my-project/
├── assets/
│   ├── chrome-logo.png
│   └── login-button.png
├── screenbot.py
├── main.py
└── README.md
```

Example `main.py`:

```python
from screenbot import ScreenBot

bot = ScreenBot(confidence=0.80, timeout=10, jitter=3)

bot.click_image("assets/chrome-logo.png")
bot.click_image("assets/login-button.png")
```
