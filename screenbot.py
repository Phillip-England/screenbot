"""
screenbot
=========

A small Pythonic screen automation helper built on top of PyAutoGUI and OpenCV.

The main API is intentionally simple:

    from screenbot import ScreenBot

    bot = ScreenBot()
    bot.click_image("chrome-logo.png", confidence=0.70, timeout=10, jitter=4)

You can also use the module-level functions directly:

    import screenbot

    screenbot.click((100, 200), jitter=5)
    match = screenbot.locate("button.png", confidence=0.85)

Dependencies:
    pip install pyautogui pillow opencv-python numpy

macOS note:
    Your terminal, IDE, or Python executable may need Accessibility and
    Screen Recording permissions before screenshots/clicks work.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

try:
    import cv2
    import numpy as np
    import pyautogui
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "screenbot requires pyautogui, pillow, opencv-python, and numpy.\n"
        "Install them with:\n\n"
        "    pip install pyautogui pillow opencv-python numpy\n\n"
        f"Original import error: {exc}"
    ) from exc


__all__ = [
    "Box",
    "ClickOptions",
    "ImageNotFound",
    "ImageNotFoundError",
    "Match",
    "MatchResult",
    "MatchOptions",
    "Point",
    "ScreenBot",
    "ScreenBotError",
    "capture_template",
    "click",
    "click_box",
    "click_image",
    "click_saved",
    "locate",
    "locate_all",
    "move_to",
    "save_point",
    "save_screenshot",
    "screenshot",
    "screen_size",
    "wait_for",
    # Backward-compatible Go-style aliases.
    "ClickImage",
    "LocateImage",
    "WaitForImage",
]


Number = Union[int, float]
PointInput = Union["Point", Tuple[int, int], List[int]]
BoxInput = Union["Box", Tuple[int, int, int, int], List[int]]
PathInput = Union[str, Path]
Button = str


class ScreenBotError(Exception):
    """Base exception for screenbot."""


class ImageNotFound(ScreenBotError):
    """Raised when an image cannot be found and the operation requires it."""


# Name used by the earlier version.
ImageNotFoundError = ImageNotFound


@dataclass(frozen=True)
class Point:
    """A screen coordinate."""

    x: int
    y: int

    @classmethod
    def from_value(cls, value: PointInput) -> "Point":
        if isinstance(value, Point):
            return value
        if len(value) != 2:  # type: ignore[arg-type]
            raise ValueError("Point must be Point(x, y) or a 2-item tuple/list")
        return cls(int(value[0]), int(value[1]))  # type: ignore[index]

    def offset(self, dx: Number = 0, dy: Number = 0) -> "Point":
        """Return a new point shifted by dx/dy."""

        return Point(int(round(self.x + dx)), int(round(self.y + dy)))

    def as_tuple(self) -> Tuple[int, int]:
        return self.x, self.y

    # Compatibility with the previous API.
    from_any = from_value
    shifted = offset
    to_tuple = as_tuple


@dataclass(frozen=True)
class Box:
    """A screen rectangle using x, y, width, height."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_value(cls, value: BoxInput) -> "Box":
        if isinstance(value, Box):
            return value
        if len(value) != 4:  # type: ignore[arg-type]
            raise ValueError("Box must be Box(x, y, width, height) or a 4-item tuple/list")
        return cls(int(value[0]), int(value[1]), int(value[2]), int(value[3]))  # type: ignore[index]

    @classmethod
    def from_xyxy(cls, left: int, top: int, right: int, bottom: int) -> "Box":
        """Create a box from left/top/right/bottom coordinates."""

        return cls(left, top, right - left, bottom - top)

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width // 2, self.y + self.height // 2)

    def contains(self, point: PointInput) -> bool:
        p = Point.from_value(point)
        return self.left <= p.x <= self.right and self.top <= p.y <= self.bottom

    def inset(self, pixels: int) -> "Box":
        """Return a smaller box inset on every side."""

        return Box(
            self.x + pixels,
            self.y + pixels,
            max(0, self.width - pixels * 2),
            max(0, self.height - pixels * 2),
        )

    def random_point(self, padding: int = 0) -> Point:
        """Pick a random point inside the box."""

        box = self.inset(padding) if padding else self
        if box.width <= 0 or box.height <= 0:
            return self.center
        return Point(
            random.randint(box.left, max(box.left, box.right - 1)),
            random.randint(box.top, max(box.top, box.bottom - 1)),
        )

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    # Compatibility with the previous API.
    from_any = from_value
    to_tuple = as_tuple


@dataclass(frozen=True)
class Match:
    """The location and score of an image match."""

    x: int
    y: int
    width: int
    height: int
    confidence: float
    image_path: str
    scale: float = 1.0

    @property
    def found(self) -> bool:
        return True

    @property
    def center(self) -> Point:
        return Point(self.x + self.width // 2, self.y + self.height // 2)

    @property
    def box(self) -> Box:
        return Box(self.x, self.y, self.width, self.height)

    def as_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["found"] = True
        data["center"] = self.center.as_tuple()
        return data

    # Compatibility with the previous API.
    to_dict = as_dict


# Name used by the earlier version.
MatchResult = Match


# Backward-compatible option objects. The preferred API is keyword arguments.
@dataclass
class MatchOptions:
    confidence: float = 0.80
    region: Optional[BoxInput] = None
    grayscale: bool = True
    timeout: float = 0.0
    interval: float = 0.25
    scales: Sequence[float] = (1.0,)
    raise_on_missing: bool = True


@dataclass
class ClickOptions:
    button: Button = "left"
    clicks: int = 1
    interval: float = 0.0
    duration: float = 0.0
    offset: Optional[Tuple[int, int]] = None
    offset_radius: int = 0
    move_only: bool = False
    dry_run: bool = False
    pause_after: float = 0.0


class CoordinateStore:
    """JSON-backed storage for named screen coordinates."""

    def __init__(self, path: PathInput = "screenbot_coords.json"):
        self.path = Path(path)
        self.points: Dict[str, Point] = {}
        self.load()

    def load(self) -> "CoordinateStore":
        if not self.path.exists():
            self.points = {}
            return self

        raw = json.loads(self.path.read_text())
        self.points = {name: Point.from_value(value) for name, value in raw.items()}
        return self

    def save(self) -> "CoordinateStore":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: point.as_tuple() for name, point in self.points.items()}
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True))
        return self

    def set(self, name: str, point: PointInput) -> Point:
        self.points[name] = Point.from_value(point)
        self.save()
        return self.points[name]

    def get(self, name: str) -> Point:
        try:
            return self.points[name]
        except KeyError as exc:
            raise KeyError(f"No saved point named {name!r}") from exc

    def delete(self, name: str) -> None:
        self.points.pop(name, None)
        self.save()

    def all(self) -> Dict[str, Point]:
        return dict(self.points)


class ScreenBot:
    """
    Convenience wrapper that holds defaults and saved coordinates.

    Prefer this when writing automation scripts because it keeps your defaults in
    one place:

        bot = ScreenBot(confidence=0.85, timeout=5, jitter=3)
        bot.click_image("submit-button.png")
    """

    def __init__(
        self,
        *,
        confidence: float = 0.80,
        timeout: float = 0.0,
        interval: float = 0.25,
        grayscale: bool = True,
        scales: Sequence[float] = (1.0,),
        jitter: int = 0,
        move_duration: float = 0.0,
        coordinate_file: PathInput = "screenbot_coords.json",
        failsafe: bool = True,
        pause: float = 0.0,
        default_match: Optional[MatchOptions] = None,
        default_click: Optional[ClickOptions] = None,
        coord_path: Optional[PathInput] = None,
    ):
        if default_match is not None:
            confidence = default_match.confidence
            timeout = default_match.timeout
            interval = default_match.interval
            grayscale = default_match.grayscale
            scales = default_match.scales
        if default_click is not None:
            jitter = default_click.offset_radius
            move_duration = default_click.duration
        if coord_path is not None:
            coordinate_file = coord_path

        self.confidence = confidence
        self.timeout = timeout
        self.interval = interval
        self.grayscale = grayscale
        self.scales = tuple(scales)
        self.jitter = jitter
        self.move_duration = move_duration
        self.coords = CoordinateStore(coordinate_file)

        pyautogui.FAILSAFE = failsafe
        pyautogui.PAUSE = pause

    @property
    def size(self) -> Tuple[int, int]:
        return screen_size()

    def screen_size(self) -> Tuple[int, int]:
        return screen_size()

    def screenshot(self, region: Optional[BoxInput] = None) -> Image.Image:
        return screenshot(region)

    def save_screenshot(self, path: PathInput, region: Optional[BoxInput] = None) -> Path:
        return save_screenshot(path, region)

    def capture_template(self, path: PathInput, box: BoxInput) -> Path:
        return capture_template(path, box)

    def move_to(self, point: PointInput, *, duration: Optional[float] = None) -> Point:
        return move_to(point, duration=self.move_duration if duration is None else duration)

    def click(
        self,
        point: PointInput,
        *,
        button: Button = "left",
        clicks: int = 1,
        interval: float = 0.0,
        duration: Optional[float] = None,
        jitter: Optional[int] = None,
        offset: Optional[Tuple[int, int]] = None,
        move_only: bool = False,
        dry_run: bool = False,
        pause_after: float = 0.0,
    ) -> Point:
        return click(
            point,
            button=button,
            clicks=clicks,
            interval=interval,
            duration=self.move_duration if duration is None else duration,
            jitter=self.jitter if jitter is None else jitter,
            offset=offset,
            move_only=move_only,
            dry_run=dry_run,
            pause_after=pause_after,
        )

    def click_xy(self, x: int, y: int, **kwargs) -> Point:
        return self.click(Point(x, y), **kwargs)

    def click_box(self, box: BoxInput, *, padding: int = 0, **kwargs) -> Point:
        return click_box(box, padding=padding, **self._click_kwargs(kwargs))

    def save_point(self, name: str, point: PointInput) -> Point:
        return self.coords.set(name, point)

    def get_point(self, name: str) -> Point:
        return self.coords.get(name)

    def click_saved(self, name: str, **kwargs) -> Point:
        return self.click(self.coords.get(name), **kwargs)

    def locate(
        self,
        image_path: PathInput,
        *,
        confidence: Optional[float] = None,
        region: Optional[BoxInput] = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = False,
    ) -> Optional[Match]:
        return locate(
            image_path,
            confidence=self.confidence if confidence is None else confidence,
            region=region,
            grayscale=self.grayscale if grayscale is None else grayscale,
            scales=self.scales if scales is None else scales,
            required=required,
        )

    def locate_all(
        self,
        image_path: PathInput,
        *,
        confidence: Optional[float] = None,
        region: Optional[BoxInput] = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        limit: int = 10,
    ) -> List[Match]:
        return locate_all(
            image_path,
            confidence=self.confidence if confidence is None else confidence,
            region=region,
            grayscale=self.grayscale if grayscale is None else grayscale,
            scales=self.scales if scales is None else scales,
            limit=limit,
        )

    def wait_for(
        self,
        image_path: PathInput,
        *,
        confidence: Optional[float] = None,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        region: Optional[BoxInput] = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = True,
    ) -> Optional[Match]:
        return wait_for(
            image_path,
            confidence=self.confidence if confidence is None else confidence,
            timeout=self.timeout if timeout is None else timeout,
            interval=self.interval if interval is None else interval,
            region=region,
            grayscale=self.grayscale if grayscale is None else grayscale,
            scales=self.scales if scales is None else scales,
            required=required,
        )

    def click_image(
        self,
        image_path: PathInput,
        *,
        confidence: Optional[float] = None,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        region: Optional[BoxInput] = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        jitter: Optional[int] = None,
        required: bool = True,
        **click_kwargs,
    ) -> Optional[Match]:
        match = wait_for(
            image_path,
            confidence=self.confidence if confidence is None else confidence,
            timeout=self.timeout if timeout is None else timeout,
            interval=self.interval if interval is None else interval,
            region=region,
            grayscale=self.grayscale if grayscale is None else grayscale,
            scales=self.scales if scales is None else scales,
            required=required,
        )
        if match is None:
            return None
        self.click(match.center, jitter=self.jitter if jitter is None else jitter, **click_kwargs)
        return match

    # Compatibility with the previous method names.
    def locate_image(self, image_path: PathInput, options: Optional[MatchOptions] = None, **kwargs) -> Optional[Match]:
        if options is None:
            return self.locate(image_path, **kwargs)
        match_kwargs, _ = _options_to_kwargs(options, None)
        if "timeout" in match_kwargs:
            return wait_for(image_path, **match_kwargs)
        return locate(image_path, **match_kwargs)

    def locate_all_images(
        self,
        image_path: PathInput,
        options: Optional[MatchOptions] = None,
        *,
        max_results: int = 10,
        **kwargs,
    ) -> List[Match]:
        if options is None:
            return self.locate_all(image_path, limit=max_results, **kwargs)
        match_kwargs, _ = _options_to_kwargs(options, None)
        match_kwargs.pop("timeout", None)
        match_kwargs.pop("interval", None)
        return locate_all(image_path, limit=max_results, **match_kwargs)

    def wait_for_image(self, image_path: PathInput, options: Optional[MatchOptions] = None, **kwargs) -> Optional[Match]:
        if options is None:
            return self.wait_for(image_path, **kwargs)
        match_kwargs, _ = _options_to_kwargs(options, None)
        match_kwargs.setdefault("timeout", 10.0)
        return wait_for(image_path, **match_kwargs)

    click_point = click

    def _click_kwargs(self, kwargs: Dict[str, object]) -> Dict[str, object]:
        kwargs = dict(kwargs)
        kwargs.setdefault("duration", self.move_duration)
        kwargs.setdefault("jitter", self.jitter)
        return kwargs


# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------


def screen_size() -> Tuple[int, int]:
    size = pyautogui.size()
    return int(size.width), int(size.height)


def screenshot(region: Optional[BoxInput] = None) -> Image.Image:
    if region is None:
        return pyautogui.screenshot()
    box = Box.from_value(region)
    return pyautogui.screenshot(region=box.as_tuple())


def save_screenshot(path: PathInput, region: Optional[BoxInput] = None) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    screenshot(region).save(out)
    return out


def capture_template(path: PathInput, box: BoxInput) -> Path:
    """Save a screenshot region as an image template for later matching."""

    return save_screenshot(path, Box.from_value(box))


def move_to(point: PointInput, *, duration: float = 0.0) -> Point:
    p = Point.from_value(point)
    pyautogui.moveTo(p.x, p.y, duration=duration)
    return p


def click(
    point: PointInput,
    *,
    button: Button = "left",
    clicks: int = 1,
    interval: float = 0.0,
    duration: float = 0.0,
    jitter: int = 0,
    offset: Optional[Tuple[int, int]] = None,
    move_only: bool = False,
    dry_run: bool = False,
    pause_after: float = 0.0,
) -> Point:
    """Move to a point and click it.

    Set ``jitter`` to vary the final point randomly inside a small radius.
    Set ``dry_run=True`` to calculate the final point without moving the mouse.
    """

    target = _final_click_point(Point.from_value(point), offset=offset, jitter=jitter)

    if dry_run:
        return target

    pyautogui.moveTo(target.x, target.y, duration=duration)
    if not move_only:
        pyautogui.click(
            x=target.x,
            y=target.y,
            clicks=clicks,
            interval=interval,
            button=button,
        )
    if pause_after > 0:
        time.sleep(pause_after)
    return target


def click_box(box: BoxInput, *, padding: int = 0, **click_kwargs) -> Point:
    """Click a random point inside a box."""

    target = Box.from_value(box).random_point(padding=padding)
    return click(target, **click_kwargs)


def locate(
    image_path: PathInput,
    *,
    confidence: float = 0.80,
    region: Optional[BoxInput] = None,
    grayscale: bool = True,
    scales: Sequence[float] = (1.0,),
    required: bool = False,
) -> Optional[Match]:
    """Find an image on screen once.

    Returns ``Match`` when found. Returns ``None`` when missing unless
    ``required=True`` is passed.
    """

    match = _locate_once(
        image_path,
        confidence=confidence,
        region=region,
        grayscale=grayscale,
        scales=scales,
    )
    if match is None and required:
        raise ImageNotFound(
            f"Could not find image {str(image_path)!r} at confidence >= {confidence:.2f}"
        )
    return match


def locate_all(
    image_path: PathInput,
    *,
    confidence: float = 0.80,
    region: Optional[BoxInput] = None,
    grayscale: bool = True,
    scales: Sequence[float] = (1.0,),
    limit: int = 10,
) -> List[Match]:
    """Find up to ``limit`` matching instances of an image on screen."""

    return _locate_all_once(
        image_path,
        confidence=confidence,
        region=region,
        grayscale=grayscale,
        scales=scales,
        limit=limit,
    )


def wait_for(
    image_path: PathInput,
    *,
    confidence: float = 0.80,
    timeout: float = 10.0,
    interval: float = 0.25,
    region: Optional[BoxInput] = None,
    grayscale: bool = True,
    scales: Sequence[float] = (1.0,),
    required: bool = True,
) -> Optional[Match]:
    """Keep looking for an image until it appears or timeout expires."""

    deadline = time.time() + max(0.0, timeout)

    while True:
        match = locate(
            image_path,
            confidence=confidence,
            region=region,
            grayscale=grayscale,
            scales=scales,
            required=False,
        )
        if match is not None:
            return match

        if timeout <= 0 or time.time() >= deadline:
            if required:
                raise ImageNotFound(
                    f"Timed out after {timeout:.2f}s waiting for {str(image_path)!r} "
                    f"at confidence >= {confidence:.2f}"
                )
            return None

        time.sleep(max(0.0, interval))


def click_image(
    image_path: PathInput,
    *,
    confidence: float = 0.80,
    timeout: float = 0.0,
    interval: float = 0.25,
    region: Optional[BoxInput] = None,
    grayscale: bool = True,
    scales: Sequence[float] = (1.0,),
    jitter: int = 0,
    required: bool = True,
    **click_kwargs,
) -> Optional[Match]:
    """Find an image on screen and click its center."""

    if timeout > 0:
        match = wait_for(
            image_path,
            confidence=confidence,
            timeout=timeout,
            interval=interval,
            region=region,
            grayscale=grayscale,
            scales=scales,
            required=required,
        )
    else:
        match = locate(
            image_path,
            confidence=confidence,
            region=region,
            grayscale=grayscale,
            scales=scales,
            required=required,
        )

    if match is None:
        return None

    click(match.center, jitter=jitter, **click_kwargs)
    return match


_DEFAULT_STORE = CoordinateStore()


def save_point(name: str, point: PointInput, *, file: PathInput = "screenbot_coords.json") -> Point:
    """Save a named coordinate."""

    store = _DEFAULT_STORE if file == "screenbot_coords.json" else CoordinateStore(file)
    return store.set(name, point)


def click_saved(name: str, *, file: PathInput = "screenbot_coords.json", **click_kwargs) -> Point:
    """Click a previously saved coordinate."""

    store = _DEFAULT_STORE if file == "screenbot_coords.json" else CoordinateStore(file)
    return click(store.get(name), **click_kwargs)


# ---------------------------------------------------------------------------
# Backward-compatible Go-style API
# ---------------------------------------------------------------------------


def _options_to_kwargs(
    match_options: Optional[MatchOptions], click_options: Optional[ClickOptions]
) -> Tuple[Dict[str, object], Dict[str, object]]:
    match_kwargs: Dict[str, object] = {}
    click_kwargs: Dict[str, object] = {}

    if match_options is not None:
        match_kwargs = {
            "confidence": match_options.confidence,
            "region": match_options.region,
            "grayscale": match_options.grayscale,
            "scales": match_options.scales,
            "required": match_options.raise_on_missing,
        }
        if match_options.timeout:
            match_kwargs["timeout"] = match_options.timeout
            match_kwargs["interval"] = match_options.interval

    if click_options is not None:
        click_kwargs = {
            "button": click_options.button,
            "clicks": click_options.clicks,
            "interval": click_options.interval,
            "duration": click_options.duration,
            "offset": click_options.offset,
            "jitter": click_options.offset_radius,
            "move_only": click_options.move_only,
            "dry_run": click_options.dry_run,
            "pause_after": click_options.pause_after,
        }

    return match_kwargs, click_kwargs


def ClickImage(
    image_path: PathInput,
    match_options: Optional[MatchOptions] = None,
    click_options: Optional[ClickOptions] = None,
) -> Optional[Match]:
    match_kwargs, click_kwargs = _options_to_kwargs(match_options, click_options)
    return click_image(image_path, **match_kwargs, **click_kwargs)


def LocateImage(
    image_path: PathInput,
    match_options: Optional[MatchOptions] = None,
) -> Optional[Match]:
    match_kwargs, _ = _options_to_kwargs(match_options, None)
    if "timeout" in match_kwargs:
        return wait_for(image_path, **match_kwargs)
    return locate(image_path, **match_kwargs)


def WaitForImage(
    image_path: PathInput,
    match_options: Optional[MatchOptions] = None,
) -> Optional[Match]:
    match_kwargs, _ = _options_to_kwargs(match_options, None)
    if "timeout" not in match_kwargs:
        match_kwargs["timeout"] = 10.0
    return wait_for(image_path, **match_kwargs)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _final_click_point(
    point: Point,
    *,
    offset: Optional[Tuple[int, int]],
    jitter: int,
) -> Point:
    x, y = point.x, point.y

    if offset is not None:
        x += int(offset[0])
        y += int(offset[1])

    if jitter > 0:
        dx, dy = _random_point_in_circle(jitter)
        x += dx
        y += dy

    return Point(int(round(x)), int(round(y)))


def _random_point_in_circle(radius: int) -> Tuple[int, int]:
    angle = random.uniform(0, math.tau)
    distance = radius * math.sqrt(random.random())
    return int(round(math.cos(angle) * distance)), int(round(math.sin(angle) * distance))


def _load_template(path: PathInput, grayscale: bool):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Template image not found: {p}")

    flags = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
    data = np.fromfile(str(p), dtype=np.uint8)
    template = cv2.imdecode(data, flags)
    if template is None:
        raise ValueError(f"Could not read template image: {p}")
    return template


def _screenshot_cv(region: Optional[Box], grayscale: bool):
    img = screenshot(region)
    arr = np.array(img)

    if grayscale:
        if arr.ndim == 2:
            return arr, img.size
        if arr.shape[2] == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY), img.size
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY), img.size

    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    elif arr.shape[2] == 4:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    else:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr, img.size


def _coord_scale(region: Optional[Box], screenshot_size: Tuple[int, int]) -> Tuple[float, float]:
    """Map screenshot pixels back to PyAutoGUI logical screen coordinates."""

    if region is not None:
        expected_width, expected_height = region.width, region.height
    else:
        expected_width, expected_height = screen_size()

    sx = screenshot_size[0] / max(1, expected_width)
    sy = screenshot_size[1] / max(1, expected_height)
    return sx or 1.0, sy or 1.0


def _scale_template(template, scale: float):
    if scale == 1.0:
        return template

    height, width = template.shape[:2]
    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(template, (scaled_width, scaled_height), interpolation=interpolation)


def _locate_once(
    image_path: PathInput,
    *,
    confidence: float,
    region: Optional[BoxInput],
    grayscale: bool,
    scales: Sequence[float],
) -> Optional[Match]:
    search_region = None if region is None else Box.from_value(region)
    screen_img, shot_size = _screenshot_cv(search_region, grayscale)
    template_original = _load_template(image_path, grayscale)
    sx, sy = _coord_scale(search_region, shot_size)

    best: Optional[Match] = None

    for scale in scales:
        if scale <= 0:
            continue

        template = _scale_template(template_original, scale)
        template_height, template_width = template.shape[:2]
        screen_height, screen_width = screen_img.shape[:2]

        if template_width > screen_width or template_height > screen_height:
            continue

        scores = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        _, max_score, _, max_loc = cv2.minMaxLoc(scores)

        if max_score < confidence:
            continue

        local_x, local_y = max_loc
        abs_x = int(round((search_region.x if search_region else 0) + local_x / sx))
        abs_y = int(round((search_region.y if search_region else 0) + local_y / sy))
        result_width = int(round(template_width / sx))
        result_height = int(round(template_height / sy))

        candidate = Match(
            x=abs_x,
            y=abs_y,
            width=result_width,
            height=result_height,
            confidence=float(max_score),
            image_path=str(image_path),
            scale=float(scale),
        )

        if best is None or candidate.confidence > best.confidence:
            best = candidate

    return best


def _locate_all_once(
    image_path: PathInput,
    *,
    confidence: float,
    region: Optional[BoxInput],
    grayscale: bool,
    scales: Sequence[float],
    limit: int,
) -> List[Match]:
    search_region = None if region is None else Box.from_value(region)
    screen_img, shot_size = _screenshot_cv(search_region, grayscale)
    template_original = _load_template(image_path, grayscale)
    sx, sy = _coord_scale(search_region, shot_size)

    results: List[Match] = []

    for scale in scales:
        if scale <= 0:
            continue

        template = _scale_template(template_original, scale)
        template_height, template_width = template.shape[:2]
        screen_height, screen_width = screen_img.shape[:2]

        if template_width > screen_width or template_height > screen_height:
            continue

        scores = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(scores >= confidence)

        for local_x, local_y in zip(xs.tolist(), ys.tolist()):
            abs_x = int(round((search_region.x if search_region else 0) + local_x / sx))
            abs_y = int(round((search_region.y if search_region else 0) + local_y / sy))
            result_width = int(round(template_width / sx))
            result_height = int(round(template_height / sy))

            results.append(
                Match(
                    x=abs_x,
                    y=abs_y,
                    width=result_width,
                    height=result_height,
                    confidence=float(scores[local_y, local_x]),
                    image_path=str(image_path),
                    scale=float(scale),
                )
            )

    results.sort(key=lambda result: result.confidence, reverse=True)
    return _non_max_suppress(results, limit=limit)


def _non_max_suppress(results: List[Match], *, limit: int) -> List[Match]:
    kept: List[Match] = []
    for result in results:
        if all(_iou(result.box, other.box) < 0.35 for other in kept):
            kept.append(result)
            if len(kept) >= limit:
                break
    return kept


def _iou(a: Box, b: Box) -> float:
    x1 = max(a.left, b.left)
    y1 = max(a.top, b.top)
    x2 = min(a.right, b.right)
    y2 = min(a.bottom, b.bottom)

    intersection_width = max(0, x2 - x1)
    intersection_height = max(0, y2 - y1)
    intersection = intersection_width * intersection_height
    union = a.width * a.height + b.width * b.height - intersection
    return intersection / union if union else 0.0
