"""
screenbot.py

A small single-file GUI automation helper library built on PyAutoGUI + OpenCV.

Use this for screen-coordinate automation, image matching, color scanning,
randomized clicks, named coordinates, boxes/regions, keyboard shortcuts, and
clipboard-based text input.

Safety:
- PyAutoGUI FAILSAFE is enabled by default: slam the mouse to a screen corner
  to abort automation.
- This controls your real mouse/keyboard. Test slowly first.
"""

from __future__ import annotations

import json
import math
import platform
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
import pyautogui
from PIL import Image

try:
    import pyperclip
except Exception:  # pragma: no cover - optional dependency behavior
    pyperclip = None  # type: ignore[assignment]


# -----------------------------------------------------------------------------
# Global defaults
# -----------------------------------------------------------------------------

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

RGB = Tuple[int, int, int]
MouseButton = Literal["left", "right", "middle"]
ColorMode = Literal["channel", "euclidean"]


# -----------------------------------------------------------------------------
# Core geometry types
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Point:
    """A screen coordinate."""

    x: int
    y: int

    def tuple(self) -> tuple[int, int]:
        return (self.x, self.y)

    def offset(self, dx: int = 0, dy: int = 0) -> "Point":
        return Point(self.x + dx, self.y + dy)

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def jitter(
        self,
        radius: int = 0,
        *,
        x_radius: Optional[int] = None,
        y_radius: Optional[int] = None,
        clamp_to_screen: bool = True,
    ) -> "Point":
        """
        Return a nearby random point.

        radius=5 means x and y each vary by up to 5 pixels.
        Use x_radius/y_radius to vary axes independently.
        """

        xr = radius if x_radius is None else x_radius
        yr = radius if y_radius is None else y_radius
        p = Point(
            self.x + random.randint(-xr, xr),
            self.y + random.randint(-yr, yr),
        )
        return clamp_point_to_screen(p) if clamp_to_screen else p


@dataclass(frozen=True)
class Box:
    """
    A rectangular screen region.

    left/top/right/bottom use normal Python-style geometry:
    - left/top are included
    - right/bottom are the far edge
    - width = right - left
    - height = bottom - top
    """

    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def from_xywh(cls, x: int, y: int, width: int, height: int) -> "Box":
        return cls(x, y, x + width, y + height)

    @classmethod
    def around(cls, center: Point, radius: int) -> "Box":
        return cls(center.x - radius, center.y - radius, center.x + radius + 1, center.y + radius + 1)

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def center(self) -> Point:
        return Point(self.left + self.width // 2, self.top + self.height // 2)

    def tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    def xywh(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    def contains(self, p: Point) -> bool:
        return self.left <= p.x < self.right and self.top <= p.y < self.bottom

    def expand(self, amount: int) -> "Box":
        return Box(self.left - amount, self.top - amount, self.right + amount, self.bottom + amount)

    def clamp_to_screen(self) -> "Box":
        screen = screen_box()
        return Box(
            max(screen.left, self.left),
            max(screen.top, self.top),
            min(screen.right, self.right),
            min(screen.bottom, self.bottom),
        )

    def random_point(self, margin: int = 0) -> Point:
        if self.width <= margin * 2 or self.height <= margin * 2:
            raise ValueError(f"Box too small for margin={margin}: {self}")
        return Point(
            random.randint(self.left + margin, self.right - margin - 1),
            random.randint(self.top + margin, self.bottom - margin - 1),
        )


@dataclass(frozen=True)
class TemplateMatch:
    """Result from an OpenCV template/image match."""

    box: Box
    confidence: float
    template_path: str

    @property
    def center(self) -> Point:
        return self.box.center


@dataclass(frozen=True)
class ColorStats:
    """Color scan summary for a box."""

    color: RGB
    tolerance: int
    count: int
    total: int

    @property
    def ratio(self) -> float:
        return self.count / self.total if self.total else 0.0

    @property
    def percent(self) -> float:
        return self.ratio * 100


# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

def configure(*, pause: Optional[float] = None, fail_safe: Optional[bool] = None) -> None:
    """Configure PyAutoGUI global behavior."""

    if pause is not None:
        pyautogui.PAUSE = pause
    if fail_safe is not None:
        pyautogui.FAILSAFE = fail_safe


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def screen_size() -> tuple[int, int]:
    """Return screen size as (width, height)."""

    size = pyautogui.size()
    return (int(size.width), int(size.height))


def screen_box() -> Box:
    width, height = screen_size()
    return Box(0, 0, width, height)


def mouse_position() -> Point:
    p = pyautogui.position()
    return Point(int(p.x), int(p.y))


def print_mouse_position(interval: float = 0.5) -> None:
    """
    Print the mouse position repeatedly.

    Press Ctrl+C to stop. Useful for discovering important coordinates.
    """

    try:
        while True:
            p = mouse_position()
            print(f"Point(x={p.x}, y={p.y})")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped.")


def clamp_point_to_screen(p: Point) -> Point:
    width, height = screen_size()
    return Point(
        min(max(p.x, 0), width - 1),
        min(max(p.y, 0), height - 1),
    )


def as_point(x: Union[Point, tuple[int, int], list[int], int], y: Optional[int] = None) -> Point:
    """Coerce Point, (x, y), or x/y into a Point."""

    if isinstance(x, Point):
        return x
    if isinstance(x, (tuple, list)) and len(x) == 2:
        return Point(int(x[0]), int(x[1]))
    if isinstance(x, int) and y is not None:
        return Point(int(x), int(y))
    raise TypeError("Expected Point, (x, y), or x and y")


# -----------------------------------------------------------------------------
# Mouse movement and clicking
# -----------------------------------------------------------------------------

def move_to(
    point_or_x: Union[Point, tuple[int, int], list[int], int],
    y: Optional[int] = None,
    *,
    duration: float = 0.0,
    jitter_radius: int = 0,
) -> Point:
    """Move the mouse to a point, optionally jittered."""

    p = as_point(point_or_x, y).jitter(jitter_radius)
    pyautogui.moveTo(p.x, p.y, duration=duration)
    return p


def click(
    point_or_x: Union[Point, tuple[int, int], list[int], int],
    y: Optional[int] = None,
    *,
    button: MouseButton = "left",
    clicks: int = 1,
    interval: float = 0.0,
    duration: float = 0.0,
    jitter_radius: int = 0,
) -> Point:
    """Click a point or x/y coordinate, optionally with random jitter."""

    p = move_to(point_or_x, y, duration=duration, jitter_radius=jitter_radius)
    pyautogui.click(x=p.x, y=p.y, button=button, clicks=clicks, interval=interval)
    return p


def double_click(point_or_x: Union[Point, tuple[int, int], list[int], int], y: Optional[int] = None, **kwargs: Any) -> Point:
    kwargs["clicks"] = 2
    kwargs.setdefault("interval", 0.08)
    return click(point_or_x, y, **kwargs)


def right_click(point_or_x: Union[Point, tuple[int, int], list[int], int], y: Optional[int] = None, **kwargs: Any) -> Point:
    kwargs["button"] = "right"
    return click(point_or_x, y, **kwargs)


def click_box_center(box: Box, *, jitter_radius: int = 0, **kwargs: Any) -> Point:
    """Click the center of a box/region."""

    return click(box.center, jitter_radius=jitter_radius, **kwargs)


def click_box_random(box: Box, *, margin: int = 0, **kwargs: Any) -> Point:
    """Click a random point inside a box/region."""

    return click(box.random_point(margin=margin), **kwargs)


def drag_to(
    start: Point,
    end: Point,
    *,
    duration: float = 0.25,
    button: MouseButton = "left",
    start_jitter: int = 0,
    end_jitter: int = 0,
) -> tuple[Point, Point]:
    """Drag from one point to another."""

    s = start.jitter(start_jitter)
    e = end.jitter(end_jitter)
    pyautogui.moveTo(s.x, s.y)
    pyautogui.dragTo(e.x, e.y, duration=duration, button=button)
    return s, e


def scroll(amount: int, *, x: Optional[int] = None, y: Optional[int] = None) -> None:
    """Scroll the mouse wheel. Positive scrolls up; negative scrolls down."""

    pyautogui.scroll(amount, x=x, y=y)


# -----------------------------------------------------------------------------
# Saved coordinates
# -----------------------------------------------------------------------------

class CoordinateBook:
    """
    Store named screen coordinates in a small JSON file.

    Example:
        coords = CoordinateBook("coords.json")
        coords.set("pdf_download", Point(1400, 88)).save()
        coords.click("pdf_download", jitter_radius=5)
    """

    def __init__(self, path: Union[str, Path] = "coords.json"):
        self.path = Path(path)
        self.points: dict[str, Point] = {}
        if self.path.exists():
            self.load()

    def set(self, name: str, point: Point) -> "CoordinateBook":
        self.points[name] = point
        return self

    def set_current(self, name: str) -> "CoordinateBook":
        self.points[name] = mouse_position()
        return self

    def get(self, name: str) -> Point:
        if name not in self.points:
            raise KeyError(f"No coordinate named {name!r}")
        return self.points[name]

    def click(self, name: str, *, jitter_radius: int = 0, **kwargs: Any) -> Point:
        return click(self.get(name), jitter_radius=jitter_radius, **kwargs)

    def move_to(self, name: str, *, jitter_radius: int = 0, **kwargs: Any) -> Point:
        return move_to(self.get(name), jitter_radius=jitter_radius, **kwargs)

    def delete(self, name: str) -> "CoordinateBook":
        self.points.pop(name, None)
        return self

    def names(self) -> list[str]:
        return sorted(self.points)

    def load(self) -> "CoordinateBook":
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.points = {name: Point(**coords) for name, coords in data.items()}
        return self

    def save(self) -> "CoordinateBook":
        self.path.write_text(
            json.dumps({name: asdict(point) for name, point in self.points.items()}, indent=2),
            encoding="utf-8",
        )
        return self


# -----------------------------------------------------------------------------
# Screenshots and OpenCV conversion
# -----------------------------------------------------------------------------

def screenshot(box: Optional[Box] = None, *, path: Optional[Union[str, Path]] = None) -> Image.Image:
    """Take a screenshot of the full screen or a box."""

    region = box.clamp_to_screen().xywh() if box else None
    img = pyautogui.screenshot(region=region)
    if path is not None:
        img.save(path)
    return img


def screenshot_box(box: Box, *, path: Optional[Union[str, Path]] = None) -> Image.Image:
    return screenshot(box, path=path)


def _pil_to_rgb_array(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))


def _read_template_rgb(template_path: Union[str, Path]) -> np.ndarray:
    path = str(template_path)
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not read template image: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _maybe_gray(img: np.ndarray, grayscale: bool) -> np.ndarray:
    if grayscale:
        return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return img


# -----------------------------------------------------------------------------
# Image locating / template matching
# -----------------------------------------------------------------------------

def locate_image(
    template_path: Union[str, Path],
    *,
    confidence: float = 0.85,
    search_box: Optional[Box] = None,
    grayscale: bool = True,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Optional[TemplateMatch]:
    """
    Find the best matching instance of template_path on screen.

    Returns TemplateMatch or None.
    confidence usually works in the 0.80-0.95 range for TM_CCOEFF_NORMED.
    """

    screen_img = _pil_to_rgb_array(screenshot(search_box))
    template = _read_template_rgb(template_path)

    haystack = _maybe_gray(screen_img, grayscale)
    needle = _maybe_gray(template, grayscale)

    if haystack.shape[0] < needle.shape[0] or haystack.shape[1] < needle.shape[1]:
        raise ValueError("Template image is larger than the screenshot/search region")

    result = cv2.matchTemplate(haystack, needle, method)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
        score = 1.0 - float(min_val)
        loc = min_loc
    else:
        score = float(max_val)
        loc = max_loc

    if score < confidence:
        return None

    offset_x = search_box.left if search_box else 0
    offset_y = search_box.top if search_box else 0
    h, w = needle.shape[:2]
    box = Box.from_xywh(offset_x + loc[0], offset_y + loc[1], w, h)
    return TemplateMatch(box=box, confidence=score, template_path=str(template_path))


def locate_all_images(
    template_path: Union[str, Path],
    *,
    confidence: float = 0.85,
    search_box: Optional[Box] = None,
    grayscale: bool = True,
    method: int = cv2.TM_CCOEFF_NORMED,
    dedupe_distance: int = 10,
    limit: Optional[int] = None,
) -> list[TemplateMatch]:
    """
    Find multiple matches for a template on screen.

    For repeated icons/buttons, this returns a deduped list of TemplateMatch objects.
    """

    screen_img = _pil_to_rgb_array(screenshot(search_box))
    template = _read_template_rgb(template_path)

    haystack = _maybe_gray(screen_img, grayscale)
    needle = _maybe_gray(template, grayscale)

    if haystack.shape[0] < needle.shape[0] or haystack.shape[1] < needle.shape[1]:
        raise ValueError("Template image is larger than the screenshot/search region")

    result = cv2.matchTemplate(haystack, needle, method)

    if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
        ys, xs = np.where(result <= (1.0 - confidence))
        scored = [(float(1.0 - result[y, x]), int(x), int(y)) for y, x in zip(ys, xs)]
    else:
        ys, xs = np.where(result >= confidence)
        scored = [(float(result[y, x]), int(x), int(y)) for y, x in zip(ys, xs)]

    scored.sort(reverse=True, key=lambda item: item[0])

    offset_x = search_box.left if search_box else 0
    offset_y = search_box.top if search_box else 0
    h, w = needle.shape[:2]

    matches: list[TemplateMatch] = []
    centers: list[Point] = []

    for score, x, y in scored:
        box = Box.from_xywh(offset_x + x, offset_y + y, w, h)
        center = box.center
        if any(center.distance_to(existing) <= dedupe_distance for existing in centers):
            continue
        matches.append(TemplateMatch(box=box, confidence=score, template_path=str(template_path)))
        centers.append(center)
        if limit is not None and len(matches) >= limit:
            break

    return matches


def wait_for_image(
    template_path: Union[str, Path],
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.25,
    confidence: float = 0.85,
    search_box: Optional[Box] = None,
    grayscale: bool = True,
) -> TemplateMatch:
    """Wait until a template appears on screen or raise TimeoutError."""

    deadline = time.time() + timeout
    last: Optional[TemplateMatch] = None
    while time.time() < deadline:
        last = locate_image(
            template_path,
            confidence=confidence,
            search_box=search_box,
            grayscale=grayscale,
        )
        if last is not None:
            return last
        time.sleep(poll_interval)
    raise TimeoutError(f"Image not found within {timeout}s: {template_path}")


def move_to_image(
    template_path: Union[str, Path],
    *,
    confidence: float = 0.85,
    search_box: Optional[Box] = None,
    grayscale: bool = True,
    jitter_radius: int = 0,
    duration: float = 0.0,
) -> Point:
    """Locate an image and move to its center."""

    match = locate_image(template_path, confidence=confidence, search_box=search_box, grayscale=grayscale)
    if match is None:
        raise ImageNotFoundError(f"Image not found: {template_path}")
    return move_to(match.center, jitter_radius=jitter_radius, duration=duration)


def click_image(
    template_path: Union[str, Path],
    *,
    confidence: float = 0.85,
    search_box: Optional[Box] = None,
    grayscale: bool = True,
    jitter_radius: int = 0,
    button: MouseButton = "left",
    clicks: int = 1,
    interval: float = 0.0,
) -> Point:
    """Locate an image and click its center."""

    match = locate_image(template_path, confidence=confidence, search_box=search_box, grayscale=grayscale)
    if match is None:
        raise ImageNotFoundError(f"Image not found: {template_path}")
    return click(match.center, jitter_radius=jitter_radius, button=button, clicks=clicks, interval=interval)


def click_image_when_visible(
    template_path: Union[str, Path],
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.25,
    confidence: float = 0.85,
    search_box: Optional[Box] = None,
    grayscale: bool = True,
    jitter_radius: int = 0,
) -> Point:
    """Wait for an image, then click it."""

    match = wait_for_image(
        template_path,
        timeout=timeout,
        poll_interval=poll_interval,
        confidence=confidence,
        search_box=search_box,
        grayscale=grayscale,
    )
    return click(match.center, jitter_radius=jitter_radius)


class ImageNotFoundError(RuntimeError):
    pass


# -----------------------------------------------------------------------------
# Color scanning
# -----------------------------------------------------------------------------

def _color_mask(img_rgb: np.ndarray, color: RGB, tolerance: int = 10, mode: ColorMode = "channel") -> np.ndarray:
    target = np.array(color, dtype=np.int16)
    img = img_rgb.astype(np.int16)

    if mode == "channel":
        return np.all(np.abs(img - target) <= tolerance, axis=2)
    if mode == "euclidean":
        return np.sqrt(np.sum((img - target) ** 2, axis=2)) <= tolerance
    raise ValueError(f"Unknown color mode: {mode}")


def pixel_color(point: Point) -> RGB:
    """Get the RGB color at a screen point."""

    img = screenshot(Box.from_xywh(point.x, point.y, 1, 1))
    rgb = img.convert("RGB").getpixel((0, 0))
    return (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def color_stats(
    box: Box,
    color: RGB,
    *,
    tolerance: int = 10,
    mode: ColorMode = "channel",
) -> ColorStats:
    """Count matching pixels and matching percentage for a color in a box."""

    box = box.clamp_to_screen()
    img = _pil_to_rgb_array(screenshot(box))
    mask = _color_mask(img, color, tolerance=tolerance, mode=mode)
    return ColorStats(
        color=color,
        tolerance=tolerance,
        count=int(mask.sum()),
        total=int(mask.size),
    )


def count_color_pixels(box: Box, color: RGB, *, tolerance: int = 10, mode: ColorMode = "channel") -> int:
    return color_stats(box, color, tolerance=tolerance, mode=mode).count


def color_percent(box: Box, color: RGB, *, tolerance: int = 10, mode: ColorMode = "channel") -> float:
    return color_stats(box, color, tolerance=tolerance, mode=mode).percent


def box_has_color_count(
    box: Box,
    color: RGB,
    *,
    min_count: int,
    tolerance: int = 10,
    mode: ColorMode = "channel",
) -> bool:
    return count_color_pixels(box, color, tolerance=tolerance, mode=mode) >= min_count


def box_has_color_percent(
    box: Box,
    color: RGB,
    *,
    min_percent: float,
    tolerance: int = 10,
    mode: ColorMode = "channel",
) -> bool:
    return color_percent(box, color, tolerance=tolerance, mode=mode) >= min_percent


def find_nearest_color(
    anchor: Point,
    color: RGB,
    *,
    radius: int = 100,
    tolerance: int = 10,
    mode: ColorMode = "channel",
    search_box: Optional[Box] = None,
) -> Optional[Point]:
    """
    Find the closest pixel matching a color near an anchor point.

    The search is limited to a square around the anchor, then filtered by circle radius.
    """

    area = Box.around(anchor, radius).clamp_to_screen()
    if search_box is not None:
        area = Box(
            max(area.left, search_box.left),
            max(area.top, search_box.top),
            min(area.right, search_box.right),
            min(area.bottom, search_box.bottom),
        ).clamp_to_screen()

    if area.width <= 0 or area.height <= 0:
        return None

    img = _pil_to_rgb_array(screenshot(area))
    mask = _color_mask(img, color, tolerance=tolerance, mode=mode)

    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None

    screen_xs = xs + area.left
    screen_ys = ys + area.top
    dx = screen_xs - anchor.x
    dy = screen_ys - anchor.y
    dist2 = dx * dx + dy * dy

    within = dist2 <= radius * radius
    if not np.any(within):
        return None

    valid_indices = np.where(within)[0]
    best_local_index = valid_indices[int(np.argmin(dist2[within]))]
    return Point(int(screen_xs[best_local_index]), int(screen_ys[best_local_index]))


def click_nearest_color(
    anchor: Point,
    color: RGB,
    *,
    radius: int = 100,
    tolerance: int = 10,
    mode: ColorMode = "channel",
    jitter_radius: int = 0,
    **kwargs: Any,
) -> Point:
    """Find the nearest color around an anchor and click it."""

    p = find_nearest_color(anchor, color, radius=radius, tolerance=tolerance, mode=mode)
    if p is None:
        raise ColorNotFoundError(f"Color {color} not found near {anchor} within radius={radius}")
    return click(p, jitter_radius=jitter_radius, **kwargs)


class ColorNotFoundError(RuntimeError):
    pass


# -----------------------------------------------------------------------------
# Keyboard, typing, clipboard, OS-independent shortcuts
# -----------------------------------------------------------------------------

def primary_modifier() -> str:
    """Return 'command' on macOS, otherwise 'ctrl'."""

    return "command" if sys.platform == "darwin" else "ctrl"


def press(key: str, presses: int = 1, interval: float = 0.0) -> None:
    pyautogui.press(key, presses=presses, interval=interval)


def key_down(key: str) -> None:
    pyautogui.keyDown(key)


def key_up(key: str) -> None:
    pyautogui.keyUp(key)


def hotkey(*keys: str, interval: float = 0.0) -> None:
    pyautogui.hotkey(*keys, interval=interval)


def shortcut(key: str, *extra_keys: str, interval: float = 0.0) -> None:
    """Press OS-specific primary modifier + key, e.g. Ctrl+F or Cmd+F."""

    hotkey(primary_modifier(), key, *extra_keys, interval=interval)


def type_text(text: str, interval: float = 0.0) -> None:
    """Type text using keyboard events. For weird chars, paste_text is more reliable."""

    pyautogui.write(text, interval=interval)


def paste_text(text: str, *, restore_clipboard: bool = False) -> None:
    """
    Put text on the clipboard and paste it with Ctrl/Cmd+V.

    This is usually more reliable than type_text for long strings or special chars.
    Requires pyperclip.
    """

    if pyperclip is None:
        raise RuntimeError("paste_text requires pyperclip. Install it with: uv add pyperclip")

    old_text: Optional[str] = None
    if restore_clipboard:
        try:
            old_text = pyperclip.paste()
        except Exception:
            old_text = None

    pyperclip.copy(text)
    paste()

    if restore_clipboard and old_text is not None:
        pyperclip.copy(old_text)


def select_all() -> None:
    shortcut("a")


def copy() -> None:
    shortcut("c")


def cut() -> None:
    shortcut("x")


def paste() -> None:
    shortcut("v")


def undo() -> None:
    shortcut("z")


def redo() -> None:
    if sys.platform == "darwin":
        hotkey("command", "shift", "z")
    else:
        hotkey("ctrl", "y")


def find() -> None:
    shortcut("f")


def find_text(text: str, *, use_clipboard: bool = True) -> None:
    find()
    if use_clipboard:
        paste_text(text)
    else:
        type_text(text)


def save() -> None:
    shortcut("s")


def new_tab() -> None:
    shortcut("t")


def close_tab() -> None:
    shortcut("w")


def reopen_closed_tab() -> None:
    hotkey(primary_modifier(), "shift", "t")


def refresh() -> None:
    shortcut("r")


def hard_refresh() -> None:
    if sys.platform == "darwin":
        hotkey("command", "shift", "r")
    else:
        hotkey("ctrl", "shift", "r")


def enter(presses: int = 1, interval: float = 0.0) -> None:
    press("enter", presses=presses, interval=interval)


def escape(presses: int = 1, interval: float = 0.0) -> None:
    press("esc", presses=presses, interval=interval)


def tab(presses: int = 1, interval: float = 0.0) -> None:
    press("tab", presses=presses, interval=interval)


def backspace(presses: int = 1, interval: float = 0.0) -> None:
    press("backspace", presses=presses, interval=interval)


def delete(presses: int = 1, interval: float = 0.0) -> None:
    press("delete", presses=presses, interval=interval)


def arrow(direction: Literal["up", "down", "left", "right"], presses: int = 1, interval: float = 0.0) -> None:
    press(direction, presses=presses, interval=interval)


# -----------------------------------------------------------------------------
# Small diagnostics
# -----------------------------------------------------------------------------

def system_report() -> dict[str, Any]:
    """Return useful debugging information."""

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "screen_size": screen_size(),
        "mouse_position": asdict(mouse_position()),
        "pyautogui_pause": pyautogui.PAUSE,
        "pyautogui_failsafe": pyautogui.FAILSAFE,
        "primary_modifier": primary_modifier(),
    }


def print_system_report() -> None:
    print(json.dumps(system_report(), indent=2))


# -----------------------------------------------------------------------------
# Tiny manual demo
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print_system_report()
    print("Move your mouse around. Press Ctrl+C to stop coordinate printing.")
    print_mouse_position()
