"""Stateful screen automation with one public entry point: :class:`ScreenBot`."""

from __future__ import annotations

import json
import math
import os
import random
import signal
import sys
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence, TextIO

import pyautogui
import pyscreeze
from PIL import Image
from pynput import keyboard, mouse

__all__ = ["ScreenBot", "VirtualDir"]


def _action(method: Callable[..., Any]) -> Callable[..., Any]:
    """Apply the configured delay once after a top-level input action."""
    @wraps(method)
    def wrapped(self: "ScreenBot", *args: Any, **kwargs: Any) -> Any:
        outermost = self._action_depth == 0
        self._action_depth += 1
        try:
            result = method(self, *args, **kwargs)
        except Exception as error:
            if outermost:
                self._log_operation(method.__name__, args, kwargs, error=error)
            raise
        finally:
            self._action_depth -= 1
        if outermost:
            self._log_operation(method.__name__, args, kwargs, result=result)
        if outermost and not kwargs.get("dry_run", False):
            self._wait_after_action()
        return result

    return wrapped


class VirtualDir:
    """Provide convenient access to paths beneath a base directory."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = os.fspath(directory)

    def path(self, *parts: str | os.PathLike[str]) -> str:
        """Return a platform-native path relative to this directory."""
        return os.path.join(self.directory, *(os.fspath(part) for part in parts))


class ScreenBot:
    """Screen automation whose input behavior is controlled by a state.

    ``default`` performs input immediately. ``human-like`` uses seeded random
    pauses, curved mouse paths, small target variation, click dwell, typing
    cadence, and chunked scrolling. Randomness never changes the requested text,
    key sequence, button, or final destination.
    """

    DEFAULT = "default"
    HUMAN_LIKE = "human-like"
    STATES = (DEFAULT, HUMAN_LIKE)
    SYSTEM_ID_ENV = "SCREENBOT_SYSTEM_ID"
    KEY_NEIGHBORS = {
        "q": "wa", "w": "qase", "e": "wsdr", "r": "edft", "t": "rfgy",
        "y": "tghu", "u": "yhji", "i": "ujko", "o": "iklp", "p": "ol",
        "a": "qwsz", "s": "awedxz", "d": "serfcx", "f": "drtgvc",
        "g": "ftyhbv", "h": "gyujnb", "j": "huikmn", "k": "jiolm",
        "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb",
        "b": "vghn", "n": "bhjm", "m": "njk",
    }

    class Error(Exception):
        """Base exception for ScreenBot operations."""

    class ImageNotFound(Error):
        """Raised when a required image cannot be found."""

    @dataclass(frozen=True)
    class Point:
        x: int
        y: int

        def as_tuple(self) -> tuple[int, int]:
            return self.x, self.y

        def offset(self, dx: float = 0, dy: float = 0) -> "ScreenBot.Point":
            return ScreenBot.Point(round(self.x + dx), round(self.y + dy))

    @dataclass(frozen=True)
    class Box:
        top_left: "ScreenBot.Point"
        top_right: "ScreenBot.Point"
        bottom_right: "ScreenBot.Point"
        bottom_left: "ScreenBot.Point"

        def __post_init__(self) -> None:
            points = tuple(ScreenBot._point(point) for point in self.as_tuple())
            object.__setattr__(self, "top_left", points[0])
            object.__setattr__(self, "top_right", points[1])
            object.__setattr__(self, "bottom_right", points[2])
            object.__setattr__(self, "bottom_left", points[3])

            if not (
                points[0].y == points[1].y
                and points[1].x == points[2].x
                and points[2].y == points[3].y
                and points[3].x == points[0].x
                and points[0].x <= points[1].x
                and points[0].y <= points[3].y
            ):
                raise ValueError(
                    "box points must form an axis-aligned rectangle in "
                    "top-left, top-right, bottom-right, bottom-left order"
                )

        @property
        def x(self) -> int:
            return self.top_left.x

        @property
        def y(self) -> int:
            return self.top_left.y

        @property
        def width(self) -> int:
            return self.top_right.x - self.top_left.x

        @property
        def height(self) -> int:
            return self.bottom_left.y - self.top_left.y

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
        def center(self) -> "ScreenBot.Point":
            return ScreenBot.Point(self.x + self.width // 2, self.y + self.height // 2)

        def as_tuple(self) -> tuple["ScreenBot.Point", "ScreenBot.Point", "ScreenBot.Point", "ScreenBot.Point"]:
            return self.top_left, self.top_right, self.bottom_right, self.bottom_left

        def as_region_tuple(self) -> tuple[int, int, int, int]:
            return self.x, self.y, self.width, self.height

    @dataclass(frozen=True)
    class Match:
        x: int
        y: int
        width: int
        height: int
        confidence: float
        image_path: str
        scale: float = 1.0

        @property
        def center(self) -> "ScreenBot.Point":
            return ScreenBot.Point(self.x + self.width // 2, self.y + self.height // 2)

        @property
        def box(self) -> "ScreenBot.Box":
            return ScreenBot.Box(
                (self.x, self.y),
                (self.x + self.width, self.y),
                (self.x + self.width, self.y + self.height),
                (self.x, self.y + self.height),
            )

        def as_dict(self) -> dict[str, object]:
            value = asdict(self)
            value["center"] = self.center.as_tuple()
            return value

    @dataclass(frozen=True)
    class ColorCount:
        """An RGB color and its frequency in an image or screen region."""

        color: tuple[int, int, int]
        count: int
        percentage: float

        @property
        def hex(self) -> str:
            return "#" + "".join(f"{channel:02X}" for channel in self.color)

        def as_dict(self) -> dict[str, object]:
            return {
                "rgb": list(self.color),
                "hex": self.hex,
                "count": self.count,
                "percentage": self.percentage,
            }

    @dataclass(frozen=True)
    class Pixel:
        """One pixel at a screen or image coordinate."""

        x: int
        y: int
        color: tuple[int, int, int]

        @property
        def hex(self) -> str:
            return "#" + "".join(f"{channel:02X}" for channel in self.color)

        def as_dict(self) -> dict[str, object]:
            return {"x": self.x, "y": self.y, "rgb": list(self.color), "hex": self.hex}

    def __init__(
        self,
        state: str = DEFAULT,
        *,
        confidence: float = 0.80,
        timeout: float = 1.0,
        poll_interval: float = 0.25,
        key_press_duration: float = 0.05,
        key_release_duration: float = 0.05,
        grayscale: bool = True,
        scales: Sequence[float] = (1.0,),
        coordinate_file: str | Path = "screenbot_coords.json",
        seed: Optional[int] = None,
        failsafe: bool = True,
        kill_sequence: Optional[str] = None,
        backend: Any = None,
        sleeper: Any = time.sleep,
        system_id: Optional[str] = None,
        log: bool = False,
        log_stream: Optional[TextIO] = None,
    ) -> None:
        self.log = bool(log)
        self.log_stream = sys.stderr if log_stream is None else log_stream
        self.confidence = self._confidence(confidence)
        self.timeout = self._non_negative(timeout, "timeout")
        self.poll_interval = self._non_negative(poll_interval, "poll_interval")
        self.key_press_duration = self._non_negative(
            key_press_duration, "key_press_duration"
        )
        self.key_release_duration = self._non_negative(
            key_release_duration, "key_release_duration"
        )
        self.grayscale = bool(grayscale)
        self.scales = self._validate_scales(scales)
        self.coordinate_file = Path(coordinate_file)
        self.system_id = self._resolve_system_id(system_id)
        self._backend = backend or pyautogui
        self._display_scale: Optional[tuple[float, float]] = None
        self._sleep = sleeper
        self._random = random.Random(seed)
        self._state = self._normalize_state(state)
        self.wait_time = (0.0, 0.0)
        self._action_depth = 0
        self.kill_sequence: Optional[str] = None
        self._kill_buffer = ""
        self._kill_listener: Any = None

        # Human-like ranges are public so scripts can tune behavior directly.
        self.human_pause = (0.04, 0.16)
        self.human_move_duration = (0.22, 0.72)
        self.human_click_dwell = (0.035, 0.12)
        self.human_key_dwell = (0.035, 0.09)
        self.human_key_interval = (0.035, 0.14)
        self.human_typo_pause = (0.08, 0.32)
        self.human_typo_chance = 0.04
        self.human_scroll_pause = (0.04, 0.13)
        self.human_target_jitter = 2
        self.human_image_padding = 3
        self.human_path_deviation = (0.14, 0.42)
        self.human_speed_variation = (0.35, 2.40)
        self.human_overshoot_chance = 0.35

        self._backend.FAILSAFE = failsafe
        self._backend.PAUSE = 0
        self.configure_kill_sequence(kill_sequence)

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_human_like(self) -> bool:
        return self._state == self.HUMAN_LIKE

    def set_state(self, state: str) -> "ScreenBot":
        """Change behavior and return this bot for fluent setup."""
        self._state = self._normalize_state(state)
        return self

    def set_human_like(self) -> "ScreenBot":
        """Enable human-like timing and movement behavior."""
        return self.set_state(self.HUMAN_LIKE)

    def set_fast(self) -> "ScreenBot":
        """Enable immediate input behavior without human-like semantics."""
        return self.set_state(self.DEFAULT)

    def set_logging(self, enabled: bool = True) -> "ScreenBot":
        """Enable or disable terminal logging and return this bot."""
        self.log = bool(enabled)
        return self

    @contextmanager
    def using_state(self, state: str) -> Iterator["ScreenBot"]:
        """Temporarily use a state, restoring the previous state afterward."""
        previous = self._state
        self.set_state(state)
        try:
            yield self
        finally:
            self._state = previous

    def reseed(self, seed: Optional[int]) -> "ScreenBot":
        """Reset the random stream used by chance and human-like behavior."""
        self._random.seed(seed)
        return self

    def set_wait_time(
        self, minimum: float, maximum: Optional[float] = None
    ) -> "ScreenBot":
        """Set the exact or random delay applied after each input action."""
        upper = minimum if maximum is None else maximum
        self.wait_time = self._range((minimum, upper), "wait time")
        return self

    def chance(self, percentage: float) -> bool:
        """Return whether an event with the given percentage should occur."""
        probability = self._percentage(percentage, "percentage")
        if probability == 0:
            return False
        if probability == 100:
            return True
        return self._random.random() < probability / 100

    def run_with_chance(
        self,
        percentage: float,
        action: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a callable at the given percentage chance, or return None."""
        if not callable(action):
            raise TypeError("action must be callable")
        if self.chance(percentage):
            return action(*args, **kwargs)
        return None

    def configure_kill_sequence(self, sequence: Optional[str]) -> "ScreenBot":
        """Stop execution when a character sequence is typed anywhere."""
        if sequence is not None and (not isinstance(sequence, str) or not sequence):
            raise ValueError("kill_sequence must be a non-empty string or None")
        self.stop_kill_listener()
        if sequence is None:
            self.kill_sequence = None
            return self

        self.kill_sequence = sequence
        self._kill_buffer = ""

        def on_press(key: Any) -> Optional[bool]:
            char = getattr(key, "char", None)
            if char is None:
                self._kill_buffer = ""
                return None
            self._kill_buffer = (self._kill_buffer + char)[-len(sequence):]
            if self._kill_buffer == sequence:
                self.stop_kill_listener()
                os.kill(os.getpid(), signal.SIGINT)
                return False
            return None

        self._kill_listener = keyboard.Listener(on_press=on_press)
        self._kill_listener.start()
        return self

    def stop_kill_listener(self) -> "ScreenBot":
        """Disable and release the global kill-sequence listener."""
        listener = self._kill_listener
        self._kill_listener = None
        self._kill_buffer = ""
        if listener is not None:
            listener.stop()
        return self

    def configure_human_like(
        self,
        *,
        pause: Optional[tuple[float, float]] = None,
        move_duration: Optional[tuple[float, float]] = None,
        click_dwell: Optional[tuple[float, float]] = None,
        key_dwell: Optional[tuple[float, float]] = None,
        key_interval: Optional[tuple[float, float]] = None,
        typo_pause: Optional[tuple[float, float]] = None,
        typo_chance: Optional[float] = None,
        scroll_pause: Optional[tuple[float, float]] = None,
        target_jitter: Optional[int] = None,
        image_padding: Optional[int] = None,
        path_deviation: Optional[tuple[float, float]] = None,
        speed_variation: Optional[tuple[float, float]] = None,
        overshoot_chance: Optional[float] = None,
    ) -> "ScreenBot":
        """Tune human-like timing and spatial variation ranges."""
        for name, value in (
            ("human_pause", pause),
            ("human_move_duration", move_duration),
            ("human_click_dwell", click_dwell),
            ("human_key_dwell", key_dwell),
            ("human_key_interval", key_interval),
            ("human_typo_pause", typo_pause),
            ("human_scroll_pause", scroll_pause),
        ):
            if value is not None:
                setattr(self, name, self._range(value, name))
        if target_jitter is not None:
            self.human_target_jitter = self._integer_non_negative(target_jitter, "target_jitter")
        if image_padding is not None:
            self.human_image_padding = self._integer_non_negative(image_padding, "image_padding")
        if path_deviation is not None:
            self.human_path_deviation = self._range(path_deviation, "path_deviation")
        if speed_variation is not None:
            self.human_speed_variation = self._positive_range(speed_variation, "speed_variation")
        if overshoot_chance is not None:
            self.human_overshoot_chance = self._probability(overshoot_chance, "overshoot_chance")
        if typo_chance is not None:
            self.human_typo_chance = self._probability(typo_chance, "typo_chance")
        return self

    # Screen and pointer -------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        size = self._backend.size()
        return int(size.width), int(size.height)

    def screen_center(self) -> "ScreenBot.Point":
        """Return the center point of the primary screen."""
        width, height = self.screen_size()
        return self.Point(width // 2, height // 2)

    def mouse_position(self) -> "ScreenBot.Point":
        point = self._backend.position()
        return self.Point(int(point.x), int(point.y))

    def screenshot(self, region: Any = None) -> Image.Image:
        box = None if region is None else self._resolve_box(region)
        return self._backend.screenshot(region=None if box is None else box.as_region_tuple())

    def save_screenshot(self, path: str | Path, region: Any = None) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot(region).save(output)
        return output

    def pixel_color(self, point: Any = None) -> tuple[int, int, int]:
        """Return the RGB color at a screen point, or at the mouse position."""
        target = self.mouse_position() if point is None else self._resolve_point(point)
        color = self._backend.pixel(target.x, target.y)
        return tuple(int(channel) for channel in color[:3])

    def colors_in_box(self, box: Any) -> list["ScreenBot.ColorCount"]:
        """Count RGB colors in a screen box, ordered from most common."""
        return self._color_counts(self.screenshot(self._resolve_box(box)))

    def colors_in_image(self, path: str | Path) -> list["ScreenBot.ColorCount"]:
        """Count RGB colors in an image file, ordered from most common."""
        source = Path(path)
        try:
            with Image.open(source) as image:
                image.load()
                return self._color_counts(image)
        except (OSError, ValueError) as error:
            raise ValueError(f"Could not read image: {source}") from error

    def pixels_in_box(self, box: Any) -> Iterator["ScreenBot.Pixel"]:
        """Yield every pixel in a screen box in row-major order."""
        area = self._resolve_box(box)
        image = self.screenshot(area).convert("RGB")
        try:
            for y in range(image.height):
                for x in range(image.width):
                    color = tuple(int(channel) for channel in image.getpixel((x, y)))
                    yield self.Pixel(area.left + x, area.top + y, color)
        finally:
            image.close()

    def capture_template(self, path: str | Path, box: Any) -> Path:
        return self.save_screenshot(path, self._resolve_box(box))

    @_action
    def move_to(self, point: Any, *, duration: Optional[float] = None) -> "ScreenBot.Point":
        target = self._resolve_point(point)
        if not self.is_human_like:
            self._backend.moveTo(target.x, target.y, duration=0 if duration is None else duration)
            return target

        self._pause(self.human_pause)
        self._human_move(target, duration)
        self._pause(self.human_pause, factor=0.35)
        return target

    def move_to_center(self, *, duration: Optional[float] = None) -> "ScreenBot.Point":
        """Move the pointer to the center of the primary screen."""
        return self.move_to(self.screen_center(), duration=duration)

    @_action
    def move_mouse_up(
        self,
        distance: int,
        *,
        variation: int = 0,
        duration: Optional[float | tuple[float, float]] = None,
    ) -> "ScreenBot.Point":
        """Move up by ``distance +/- variation`` pixels with human-like motion."""
        return self._move_mouse_direction(0, -1, distance, variation, duration)

    @_action
    def move_mouse_down(
        self,
        distance: int,
        *,
        variation: int = 0,
        duration: Optional[float | tuple[float, float]] = None,
    ) -> "ScreenBot.Point":
        """Move down by ``distance +/- variation`` pixels with human-like motion."""
        return self._move_mouse_direction(0, 1, distance, variation, duration)

    @_action
    def move_mouse_left(
        self,
        distance: int,
        *,
        variation: int = 0,
        duration: Optional[float | tuple[float, float]] = None,
    ) -> "ScreenBot.Point":
        """Move left by ``distance +/- variation`` pixels with human-like motion."""
        return self._move_mouse_direction(-1, 0, distance, variation, duration)

    @_action
    def move_mouse_right(
        self,
        distance: int,
        *,
        variation: int = 0,
        duration: Optional[float | tuple[float, float]] = None,
    ) -> "ScreenBot.Point":
        """Move right by ``distance +/- variation`` pixels with human-like motion."""
        return self._move_mouse_direction(1, 0, distance, variation, duration)

    @_action
    def click(
        self,
        point: Any = None,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.0,
        duration: Optional[float] = None,
        offset: tuple[int, int] = (0, 0),
        jitter: Optional[int] = None,
        move_only: bool = False,
        dry_run: bool = False,
    ) -> "ScreenBot.Point":
        """Move and click. Human-like mode adds pathing, pauses, and click dwell."""
        base = self.mouse_position() if point is None else self._resolve_point(point)
        radius = self.human_target_jitter if jitter is None and self.is_human_like else (jitter or 0)
        target = base.offset(offset[0], offset[1])
        if radius:
            dx, dy = self._point_in_circle(radius)
            target = target.offset(dx, dy)
        if dry_run:
            return target

        self.move_to(target, duration=duration)
        if move_only:
            return target
        if self.is_human_like:
            for index in range(self._positive_integer(clicks, "clicks")):
                self._backend.mouseDown(button=button)
                self._pause(self.human_click_dwell)
                self._backend.mouseUp(button=button)
                if index + 1 < clicks:
                    self._sleep(self._human_interval(interval, self.human_click_dwell))
            self._pause(self.human_pause, factor=0.5)
        else:
            self._backend.click(
                x=target.x, y=target.y, clicks=clicks,
                interval=self._non_negative(interval, "interval"), button=button,
            )
        return target

    def click_xy(self, x: int, y: int, **kwargs: Any) -> "ScreenBot.Point":
        return self.click((x, y), **kwargs)

    def click_center(self, **kwargs: Any) -> "ScreenBot.Point":
        """Click the center of the primary screen."""
        return self.click(self.screen_center(), **kwargs)

    def click_box(self, box: Any, *, padding: int = 0, **kwargs: Any) -> "ScreenBot.Point":
        return self.click(self._random_point_in_box(self._resolve_box(box), padding), **kwargs)

    def click_grid(
        self,
        box: Any,
        *,
        columns: int = 4,
        rows: int = 7,
        variation: int = 0,
        **click_kwargs: Any,
    ) -> list["ScreenBot.Point"]:
        """Click each grid cell once, in random order, near its center."""
        area = self._resolve_box(box)
        column_count = self._positive_integer(columns, "columns")
        row_count = self._positive_integer(rows, "rows")
        radius = self._integer_non_negative(variation, "variation")
        if area.width < column_count or area.height < row_count:
            raise ValueError("box must be at least one pixel per grid cell")

        cells: list[tuple[ScreenBot.Point, ScreenBot.Box]] = []
        for row in range(row_count):
            top = area.top + round(row * area.height / row_count)
            bottom = area.top + round((row + 1) * area.height / row_count)
            for column in range(column_count):
                left = area.left + round(column * area.width / column_count)
                right = area.left + round((column + 1) * area.width / column_count)
                cell = self.Box(
                    (left, top), (right, top), (right, bottom), (left, bottom)
                )
                cells.append((cell.center, cell))

        self._random.shuffle(cells)
        click_kwargs.setdefault("jitter", 0)
        clicked = []
        for center, cell in cells:
            dx, dy = self._point_in_circle(radius) if radius else (0, 0)
            target = self.Point(
                min(max(center.x + dx, cell.left), cell.right - 1),
                min(max(center.y + dy, cell.top), cell.bottom - 1),
            )
            clicked.append(self.click(target, **click_kwargs))
        return clicked

    def double_click(self, point: Any = None, **kwargs: Any) -> "ScreenBot.Point":
        return self.click(point, clicks=2, **kwargs)

    def right_click(self, point: Any = None, **kwargs: Any) -> "ScreenBot.Point":
        return self.click(point, button="right", **kwargs)

    @_action
    def drag_to(
        self,
        point: Any,
        *,
        button: str = "left",
        duration: Optional[float] = None,
    ) -> "ScreenBot.Point":
        target = self._resolve_point(point)
        if self.is_human_like:
            self._pause(self.human_pause)
            self._backend.mouseDown(button=button)
            self._pause(self.human_click_dwell)
            self._human_move(target, duration)
            self._pause(self.human_click_dwell)
            self._backend.mouseUp(button=button)
            self._pause(self.human_pause, factor=0.5)
        else:
            self._backend.dragTo(target.x, target.y, duration=duration or 0, button=button)
        return target

    @_action
    def scroll(self, clicks: int, *, x: Optional[int] = None, y: Optional[int] = None) -> int:
        amount = int(clicks)
        if not self.is_human_like:
            self._backend.scroll(amount, x=x, y=y)
            return amount
        self._pause(self.human_pause)
        remaining = abs(amount)
        direction = 1 if amount >= 0 else -1
        while remaining:
            chunk = min(remaining, self._random.randint(1, 3))
            self._backend.scroll(direction * chunk, x=x, y=y)
            remaining -= chunk
            if remaining:
                self._pause(self.human_scroll_pause)
        self._pause(self.human_pause, factor=0.4)
        return amount

    @_action
    def scroll_random(
        self,
        pixels: int,
        *,
        direction: str = "down",
        variation: int = 200,
        duration: tuple[float, float] = (2.0, 3.0),
        pixels_per_click: int = 40,
        x: Optional[int] = None,
        y: Optional[int] = None,
    ) -> int:
        """Scroll an approximate, varied pixel distance over a varied duration."""
        requested = self._positive_integer(pixels, "pixels")
        spread = self._integer_non_negative(variation, "variation")
        pixels_per_step = self._positive_integer(pixels_per_click, "pixels_per_click")
        direction_name = str(direction).strip().lower()
        if direction_name not in ("up", "down"):
            raise ValueError("direction must be 'up' or 'down'")

        target_pixels = self._random.randint(max(1, requested - spread), requested + spread)
        total_clicks = max(1, round(target_pixels / pixels_per_step))
        actual_pixels = total_clicks * pixels_per_step
        total_duration = self._random.uniform(*self._range(duration, "scroll duration"))
        sign = 1 if direction_name == "up" else -1

        chunks: list[int] = []
        remaining = total_clicks
        while remaining:
            chunk = min(remaining, self._random.randint(1, 3))
            chunks.append(chunk)
            remaining -= chunk

        # Longer pauses at the beginning and end create acceleration and easing.
        weights = []
        for index in range(len(chunks)):
            progress = (index + 1) / (len(chunks) + 1)
            speed = 0.25 + math.sin(math.pi * progress)
            weights.append(self._random.uniform(0.80, 1.20) / speed)
        weight_total = sum(weights)

        for chunk, weight in zip(chunks, weights):
            self._sleep(total_duration * weight / weight_total)
            self._backend.scroll(sign * chunk, x=x, y=y)

        return actual_pixels

    def scroll_down(self, pixels: int, **kwargs: Any) -> int:
        """Scroll down by an approximate pixel distance with human-like pacing."""
        return self.scroll_random(pixels, direction="down", **kwargs)

    def scroll_up(self, pixels: int, **kwargs: Any) -> int:
        """Scroll up by an approximate pixel distance with human-like pacing."""
        return self.scroll_random(pixels, direction="up", **kwargs)

    # Keyboard -----------------------------------------------------------

    @_action
    def write(self, text: str, *, interval: Optional[float] = None) -> str:
        """Type text accurately, with corrected mistakes in human-like mode."""
        if not self.is_human_like:
            self._backend.write(text, interval=0 if interval is None else interval)
            return text
        self._pause(self.human_pause)
        for char in text:
            mistake = self._typing_mistake(char)
            if mistake is not None:
                self._backend.write(mistake)
                self._pause(self.human_typo_pause)
                self._backend.press("backspace")
                self._sleep(self._human_interval(interval, self.human_key_interval))
            self._backend.write(char)
            self._sleep(self._human_interval(interval, self.human_key_interval))
        self._pause(self.human_pause, factor=0.4)
        return text

    @_action
    def press(self, key: str, *, presses: int = 1, interval: Optional[float] = None) -> str:
        """Press and release a key, with a short dwell between both events."""
        count = self._positive_integer(presses, "presses")
        repeat_delay = self._non_negative(
            0 if interval is None else interval, "interval"
        )
        if self.is_human_like:
            self._pause(self.human_pause)
        for index in range(count):
            self._backend.keyDown(key)
            try:
                dwell = (
                    self._random.uniform(*self.human_key_dwell)
                    if self.is_human_like
                    else self.key_press_duration
                )
                self._sleep(dwell)
            finally:
                self._backend.keyUp(key)
            # Quartz posts keyboard events asynchronously. Give the release
            # time to reach the OS before a following shortcut is pressed.
            self._sleep(self.key_release_duration)
            if index + 1 < count:
                self._sleep(
                    self._human_interval(interval, self.human_key_interval)
                    if self.is_human_like else repeat_delay
                )
        if self.is_human_like:
            self._pause(self.human_pause, factor=0.4)
        return key

    def press_and_release(
        self, key: str, *, presses: int = 1, interval: Optional[float] = None
    ) -> str:
        """Explicit alias for :meth:`press`."""
        return self.press(key, presses=presses, interval=interval)

    def press_arrow_up(self, **kwargs: Any) -> str:
        """Press the Up Arrow key."""
        return self.press("up", **kwargs)

    def press_arrow_down(self, **kwargs: Any) -> str:
        """Press the Down Arrow key."""
        return self.press("down", **kwargs)

    def press_arrow_left(self, **kwargs: Any) -> str:
        """Press the Left Arrow key."""
        return self.press("left", **kwargs)

    def press_arrow_right(self, **kwargs: Any) -> str:
        """Press the Right Arrow key."""
        return self.press("right", **kwargs)

    def press_enter(self, **kwargs: Any) -> str:
        """Press the Enter or Return key."""
        return self.press("enter", **kwargs)

    def press_escape(self, **kwargs: Any) -> str:
        """Press the Escape key."""
        return self.press("esc", **kwargs)

    def press_tab(self, **kwargs: Any) -> str:
        """Press the Tab key."""
        return self.press("tab", **kwargs)

    def press_space(self, **kwargs: Any) -> str:
        """Press the Space key."""
        return self.press("space", **kwargs)

    def press_backspace(self, **kwargs: Any) -> str:
        """Press the Backspace key."""
        return self.press("backspace", **kwargs)

    def press_delete(self, **kwargs: Any) -> str:
        """Press the forward Delete key."""
        return self.press("delete", **kwargs)

    def press_insert(self, **kwargs: Any) -> str:
        """Press the Insert key."""
        return self.press("insert", **kwargs)

    def press_home(self, **kwargs: Any) -> str:
        """Press the Home key."""
        return self.press("home", **kwargs)

    def press_end(self, **kwargs: Any) -> str:
        """Press the End key."""
        return self.press("end", **kwargs)

    def press_page_up(self, **kwargs: Any) -> str:
        """Press the Page Up key."""
        return self.press("pageup", **kwargs)

    def press_page_down(self, **kwargs: Any) -> str:
        """Press the Page Down key."""
        return self.press("pagedown", **kwargs)

    def press_function_key(self, number: int, **kwargs: Any) -> str:
        """Press an F1 through F24 function key."""
        key_number = self._positive_integer(number, "function key number")
        if key_number > 24:
            raise ValueError("function key number must be between 1 and 24")
        return self.press(f"f{key_number}", **kwargs)

    @_action
    def hold(self, key: str) -> str:
        """Hold a key down until :meth:`release` is called for that key."""
        self._backend.keyDown(key)
        return key

    @_action
    def release(self, key: str) -> str:
        """Release a key previously pressed with :meth:`hold`."""
        self._backend.keyUp(key)
        return key

    @_action
    def hotkey(self, *keys: str) -> tuple[str, ...]:
        if not keys:
            raise ValueError("hotkey requires at least one key")
        if not self.is_human_like:
            self._backend.hotkey(*keys)
            return tuple(keys)
        self._pause(self.human_pause)
        for key in keys:
            self._backend.keyDown(key)
            self._pause(self.human_key_interval, factor=0.35)
        for key in reversed(keys):
            self._backend.keyUp(key)
            self._pause(self.human_key_interval, factor=0.25)
        self._pause(self.human_pause, factor=0.4)
        return tuple(keys)

    def close_window(self) -> tuple[str, str]:
        keys = ("command" if sys.platform == "darwin" else "ctrl", "w")
        self.hotkey(*keys)
        return keys

    def websearch(self) -> tuple[str, str]:
        """Focus the address/search bar in the active browser window."""
        keys = ("command" if sys.platform == "darwin" else "ctrl", "l")
        return self.hotkey(*keys)

    def maximize(self) -> tuple[str, ...]:
        """Maximize the active window using the current platform's shortcut."""
        if sys.platform == "darwin":
            keys = ("ctrl", "command", "f")
        elif sys.platform == "win32":
            keys = ("win", "up")
        else:
            keys = ("alt", "f10")
        return self.hotkey(*keys)

    def minimize(self) -> tuple[str, ...]:
        """Minimize the active window using the current platform's shortcut."""
        if sys.platform == "darwin":
            keys = ("command", "m")
        elif sys.platform == "win32":
            keys = ("win", "down")
        else:
            keys = ("alt", "f9")
        return self.hotkey(*keys)

    def zoom_in(
        self,
        steps: int = 1,
        *,
        interval: float | tuple[float, float] = 0.0,
    ) -> int:
        """Zoom in by a number of application/browser zoom steps."""
        return self._zoom("+", steps, interval)

    def zoom_out(
        self,
        steps: int = 1,
        *,
        interval: float | tuple[float, float] = 0.0,
    ) -> int:
        """Zoom out by a number of application/browser zoom steps."""
        return self._zoom("-", steps, interval)

    # Image matching -----------------------------------------------------

    def locate(
        self,
        image_path: str | Path,
        *,
        confidence: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = False,
    ) -> Optional["ScreenBot.Match"]:
        threshold = self.confidence if confidence is None else self._confidence(confidence)
        match = self._locate_once(
            image_path, threshold, region,
            self.grayscale if grayscale is None else grayscale,
            self.scales if scales is None else self._validate_scales(scales),
        )
        self._log_message(
            f"locate({str(image_path)!r}) -> {match!r}" if match is not None
            else f"locate({str(image_path)!r}) -> no match"
        )
        if match is None and required:
            raise self.ImageNotFound(
                f"Could not find {str(image_path)!r} at confidence >= {threshold:.2f}"
            )
        return match

    def locate_all(
        self,
        image_path: str | Path,
        *,
        confidence: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        limit: Optional[int] = 10,
    ) -> list["ScreenBot.Match"]:
        threshold = self.confidence if confidence is None else self._confidence(confidence)
        matches = self._locate_all_once(
            image_path, threshold, region,
            self.grayscale if grayscale is None else grayscale,
            self.scales if scales is None else self._validate_scales(scales),
            None if limit is None else self._positive_integer(limit, "limit"),
        )
        self._log_message(f"locate_all({str(image_path)!r}) -> {len(matches)} matches")
        return matches

    def count_images(
        self,
        image_paths: Sequence[str | Path],
        *,
        confidence: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
    ) -> int:
        """Return the total number of visible matches for all image templates."""
        return sum(
            len(self.locate_all(
                image_path,
                confidence=confidence,
                region=region,
                grayscale=grayscale,
                scales=scales,
                limit=None,
            ))
            for image_path in image_paths
        )

    def wait_for(
        self,
        image_path: str | Path,
        *,
        confidence: Optional[float] = None,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = True,
    ) -> Optional["ScreenBot.Match"]:
        wait = self.timeout if timeout is None else self._non_negative(timeout, "timeout")
        poll = self.poll_interval if interval is None else self._non_negative(interval, "interval")
        deadline = time.monotonic() + wait
        while True:
            match = self.locate(
                image_path, confidence=confidence, region=region,
                grayscale=grayscale, scales=scales, required=False,
            )
            if match is not None:
                return match
            if wait <= 0 or time.monotonic() >= deadline:
                if required:
                    raise self.ImageNotFound(f"Timed out after {wait:.2f}s waiting for {str(image_path)!r}")
                return None
            self._sleep(poll)

    def click_image(
        self,
        image_path: str | Path,
        *,
        confidence: Optional[float] = None,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = True,
        random_point: Optional[bool] = None,
        padding: Optional[int] = None,
        **click_kwargs: Any,
    ) -> Optional["ScreenBot.Match"]:
        """Find and click an image; human-like mode defaults to an interior point."""
        match = self.wait_for(
            image_path, confidence=confidence, timeout=timeout, interval=interval,
            region=region, grayscale=grayscale, scales=scales, required=required,
        )
        if match is None:
            return None
        use_random = self.is_human_like if random_point is None else random_point
        if use_random:
            pad = self.human_image_padding if padding is None else padding
            target = self._random_point_in_box(match.box, pad)
        else:
            target = match.center
        self.click(target, **click_kwargs)
        return match

    def click_first_available_image(
        self,
        image_paths: Sequence[str | Path],
        *,
        confidence: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = True,
        random_point: Optional[bool] = None,
        padding: Optional[int] = None,
        **click_kwargs: Any,
    ) -> Optional["ScreenBot.Match"]:
        """Click the first currently visible image, in the provided order."""
        for image_path in image_paths:
            match = self.click_image(
                image_path,
                confidence=confidence,
                timeout=0,
                region=region,
                grayscale=grayscale,
                scales=scales,
                required=False,
                random_point=random_point,
                padding=padding,
                **click_kwargs,
            )
            if match is not None:
                return match

        if required:
            raise self.ImageNotFound("Could not find any of the provided images")
        return None

    def wait_for_and_click(
        self,
        image_path: str | Path,
        *,
        confidence: Optional[float] = None,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        required: bool = True,
        variation: int = 0,
        button: str = "left",
        **click_kwargs: Any,
    ) -> Optional["ScreenBot.Match"]:
        """Wait for an image, then click near its center without leaving it."""
        radius = self._integer_non_negative(variation, "variation")
        match = self.wait_for(
            image_path,
            confidence=confidence,
            timeout=timeout,
            interval=interval,
            region=region,
            grayscale=grayscale,
            scales=scales,
            required=required,
        )
        if match is None:
            return None

        target = self._point_near_center(match.box, radius)
        click_kwargs.setdefault("jitter", 0)
        self.click(target, button=button, **click_kwargs)
        return match

    def click_random_in_image(self, image_path: str | Path, **kwargs: Any) -> Optional["ScreenBot.Match"]:
        kwargs["random_point"] = True
        return self.click_image(image_path, **kwargs)

    def click_all_images(
        self,
        image_path: str | Path,
        *,
        confidence: Optional[float] = None,
        region: Any = None,
        grayscale: Optional[bool] = None,
        scales: Optional[Sequence[float]] = None,
        limit: Optional[int] = None,
        variation: int = 5,
        **click_kwargs: Any,
    ) -> list["ScreenBot.Point"]:
        """Click every visible match in random order near each match's center."""
        radius = self._integer_non_negative(variation, "variation")
        matches = self.locate_all(
            image_path,
            confidence=confidence,
            region=region,
            grayscale=grayscale,
            scales=scales,
            limit=limit,
        )
        self._random.shuffle(matches)

        # The requested radius is the complete spatial variation for this API.
        click_kwargs.setdefault("jitter", 0)
        clicked = []
        for match in matches:
            target = self._point_near_center(match.box, radius)
            clicked.append(self.click(target, **click_kwargs))
        return clicked

    # Named coordinates and utility -------------------------------------

    def save_point(self, name: str, point: Any) -> "ScreenBot.Point":
        points = self._load_points()
        value = self._resolve_point(point)
        points[name] = value
        self.coordinate_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: item.as_tuple() for key, item in sorted(points.items())}
        self.coordinate_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return value

    def get_point(self, name: str) -> "ScreenBot.Point":
        points = self._load_points()
        if name not in points:
            raise KeyError(f"No saved point named {name!r}")
        return points[name]

    def delete_point(self, name: str) -> bool:
        points = self._load_points()
        existed = points.pop(name, None) is not None
        payload = {key: item.as_tuple() for key, item in sorted(points.items())}
        self.coordinate_file.parent.mkdir(parents=True, exist_ok=True)
        self.coordinate_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return existed

    def list_points(self) -> dict[str, "ScreenBot.Point"]:
        return self._load_points()

    def click_saved(self, name: str, **kwargs: Any) -> "ScreenBot.Point":
        return self.click(self.get_point(name), **kwargs)

    def save_position_file(self, path: str | Path, point: Any) -> "ScreenBot.Point":
        """Save this system's position in a portable JSON file."""
        value = self._resolve_point(point)
        self._save_system_coordinate(
            path, "position", {"x": value.x, "y": value.y}
        )
        return value

    def load_position_file(self, path: str | Path) -> "ScreenBot.Point":
        """Load a position previously saved with :meth:`save_position_file`."""
        return self._point_from_file(path, self.system_id)

    def save_box_file(self, path: str | Path, box: Any) -> "ScreenBot.Box":
        """Save this system's box in a portable JSON file."""
        value = self._resolve_box(box)
        self._save_system_coordinate(path, "box", {
            "left": value.left,
            "top": value.top,
            "right": value.right,
            "bottom": value.bottom,
        })
        return value

    def load_box_file(self, path: str | Path) -> "ScreenBot.Box":
        """Load a box previously saved with :meth:`save_box_file`."""
        return self._box_from_file(path, self.system_id)

    def countdown(self, seconds: int = 3, *, message: str = "Starting in") -> None:
        for remaining in range(max(0, int(seconds)), 0, -1):
            print(f"{message} {remaining}...")
            self._sleep(1)
        print("Go!")

    def wait(self, seconds: float) -> float:
        """Wait for an exact number of seconds and return that duration."""
        duration = self._non_negative(seconds, "seconds")
        self._log_message(f"wait(seconds={duration!r})")
        self._sleep(duration)
        return duration

    def wait_random(self, minimum: float, maximum: float) -> float:
        """Wait for a random duration in the inclusive range and return it."""
        duration = self._random.uniform(*self._range((minimum, maximum), "wait range"))
        self._log_message(f"wait_random({minimum!r}, {maximum!r}) -> {duration!r} seconds")
        self._sleep(duration)
        return duration

    def capture_position_on_key(self, *, announce: bool = True) -> "ScreenBot.Point":
        """Return the pointer position when 0 is pressed."""
        points: list[ScreenBot.Point] = []
        if announce:
            print(
                "Move the pointer and press 0 to capture its position.",
                file=sys.stderr,
                flush=True,
            )

        def on_press(key: Any) -> Optional[bool]:
            if getattr(key, "char", None) != "0":
                return None
            points.append(self.mouse_position())
            return False

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()
        return points[0]

    def print_pos_on_key(self) -> None:
        """Print positions marked with 0 until interrupted with Ctrl+C."""
        print("Move the pointer and press 0 to print its position. Press Ctrl+C to stop.")
        while True:
            point = self.capture_position_on_key(announce=False)
            print(f"({point.x}, {point.y})", flush=True)

    def print_pos_on_click(self) -> None:
        """Compatibility alias for :meth:`print_pos_on_key`."""
        self.print_pos_on_key()

    def capture_box_on_key(self, *, announce: bool = True) -> "ScreenBot.Box":
        """Return the bounding box of four pointer positions marked with 0."""
        points: list[ScreenBot.Point] = []
        if announce:
            print(
                "Move the pointer to each corner and press 0 four times.",
                file=sys.stderr,
                flush=True,
            )

        def on_press(key: Any) -> Optional[bool]:
            if getattr(key, "char", None) != "0":
                return None
            point = self.mouse_position()
            points.append(point)
            if announce:
                print(
                    f"Point {len(points)}: {point.as_tuple()}",
                    file=sys.stderr,
                    flush=True,
                )
            return False if len(points) == 4 else None

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()

        left = min(point.x for point in points)
        right = max(point.x for point in points)
        top = min(point.y for point in points)
        bottom = max(point.y for point in points)
        return self.Box(
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        )

    def capture_box_on_click(self, *, announce: bool = True) -> "ScreenBot.Box":
        """Compatibility alias for :meth:`capture_box_on_key`."""
        return self.capture_box_on_key(announce=announce)

    def print_box_on_key(self) -> "ScreenBot.Box":
        """Capture four pointer positions marked with 0 and print their box."""
        box = self.capture_box_on_key()
        print(
            "ScreenBot.Box(\n"
            f"    ({box.left}, {box.top}),\n"
            f"    ({box.right}, {box.top}),\n"
            f"    ({box.right}, {box.bottom}),\n"
            f"    ({box.left}, {box.bottom}),\n"
            ")",
            flush=True,
        )
        return box

    def print_box_on_click(self) -> "ScreenBot.Box":
        """Compatibility alias for :meth:`print_box_on_key`."""
        return self.print_box_on_key()

    # Internals ----------------------------------------------------------

    def _log_message(self, message: str) -> None:
        if self.log:
            print(f"[ScreenBot] {message}", file=self.log_stream, flush=True)

    def _log_operation(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        result: Any = None,
        error: Optional[Exception] = None,
    ) -> None:
        arguments = [repr(value) for value in args]
        arguments.extend(f"{key}={value!r}" for key, value in kwargs.items())
        call = f"{name}({', '.join(arguments)})"
        if error is not None:
            self._log_message(f"{call} -> {type(error).__name__}: {error}")
        else:
            self._log_message(f"{call} -> {result!r}")

    def _move_mouse_direction(
        self,
        x_direction: int,
        y_direction: int,
        distance: int,
        variation: int,
        duration: Optional[float | tuple[float, float]],
    ) -> "ScreenBot.Point":
        requested = self._integer_non_negative(distance, "distance")
        spread = self._integer_non_negative(variation, "variation")
        actual_distance = self._random.randint(max(0, requested - spread), requested + spread)
        start = self.mouse_position()
        width, height = self.screen_size()
        target = self.Point(
            min(max(0, start.x + x_direction * actual_distance), max(0, width - 1)),
            min(max(0, start.y + y_direction * actual_distance), max(0, height - 1)),
        )

        if isinstance(duration, tuple):
            move_duration = self._random.uniform(*self._range(duration, "duration"))
        elif duration is None:
            move_duration = None
        else:
            move_duration = self._non_negative(duration, "duration")

        self._pause(self.human_pause)
        self._human_move(target, move_duration)
        self._pause(self.human_pause, factor=0.35)
        return target

    def _zoom(
        self,
        key: str,
        steps: int,
        interval: float | tuple[float, float],
    ) -> int:
        count = self._positive_integer(steps, "steps")
        if isinstance(interval, tuple):
            delay_range = self._range(interval, "interval")
        else:
            delay = self._non_negative(interval, "interval")
            delay_range = (delay, delay)

        modifier = "command" if sys.platform == "darwin" else "ctrl"
        for index in range(count):
            self.hotkey(modifier, key)
            if index + 1 < count:
                self._sleep(self._random.uniform(*delay_range))
        return count

    def _human_move(self, target: "ScreenBot.Point", duration: Optional[float]) -> None:
        start = self.mouse_position()
        total = self._random.uniform(*self.human_move_duration) if duration is None else self._non_negative(duration, "duration")
        distance = math.hypot(target.x - start.x, target.y - start.y)
        if distance == 0:
            return
        steps = max(2, min(120, round(max(total * 60, distance / 12))))
        dx, dy = target.x - start.x, target.y - start.y
        normal_x, normal_y = -dy / distance, dx / distance
        waypoint_count = self._random.randint(2, 4)
        waypoints: list[tuple[float, float]] = [(start.x, start.y)]
        side = self._random.choice((-1, 1))
        for index in range(1, waypoint_count + 1):
            progress = index / (waypoint_count + 1)
            progress += self._random.uniform(-0.10, 0.10) / waypoint_count
            deviation = distance * self._random.uniform(*self.human_path_deviation)
            deviation *= side * self._random.uniform(0.55, 1.0)
            waypoints.append((
                start.x + dx * progress + normal_x * deviation,
                start.y + dy * progress + normal_y * deviation,
            ))
            if self._random.random() < 0.55:
                side *= -1

        if self._random.random() < self.human_overshoot_chance and distance >= 20:
            overshoot = self._random.uniform(0.04, 0.16)
            correction = distance * self._random.uniform(0.03, 0.12) * self._random.choice((-1, 1))
            waypoints.append((
                target.x + dx * overshoot + normal_x * correction,
                target.y + dy * overshoot + normal_y * correction,
            ))
        waypoints.append((target.x, target.y))

        path: list[tuple[float, float]] = []
        segment_count = len(waypoints) - 1
        for segment in range(segment_count):
            p0 = waypoints[max(0, segment - 1)]
            p1 = waypoints[segment]
            p2 = waypoints[segment + 1]
            p3 = waypoints[min(len(waypoints) - 1, segment + 2)]
            segment_steps = max(1, round(steps / segment_count))
            for index in range(1, segment_steps + 1):
                t = index / segment_steps
                t2, t3 = t * t, t * t * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t +
                           (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                           (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t +
                           (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                           (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                path.append((x, y))
        path[-1] = (target.x, target.y)

        # Pace changes persist for several samples instead of becoming jittery noise.
        speeds: list[float] = []
        current_speed = self._random.uniform(*self.human_speed_variation)
        desired_speed = current_speed
        change_after = self._random.randint(3, 9)
        for index in range(len(path)):
            if index >= change_after:
                desired_speed = self._random.uniform(*self.human_speed_variation)
                change_after = index + self._random.randint(3, 9)
            current_speed += (desired_speed - current_speed) * 0.35
            progress = (index + 1) / len(path)
            acceleration = 0.28 + math.sin(math.pi * progress) ** 0.65
            speeds.append(max(0.01, current_speed * acceleration))
        weights = [1 / speed for speed in speeds]
        weight_total = sum(weights)

        for index, ((x, y), weight) in enumerate(zip(path, weights)):
            if index + 1 < len(path):
                x += self._random.uniform(-1.2, 1.2)
                y += self._random.uniform(-1.2, 1.2)
            self._backend.moveTo(round(x), round(y), duration=0)
            if total:
                self._sleep(total * weight / weight_total)

    def _locate_once(self, path: str | Path, confidence: float, region: Any, grayscale: bool, scales: Sequence[float]) -> Optional["ScreenBot.Match"]:
        search_region = None if region is None else self._resolve_box(region)
        display_scale = self._get_display_scale()
        template = self._load_template(path)
        try:
            for scale in scales:
                candidate = self._scale_template(template, scale)
                try:
                    box = self._backend.locateOnScreen(
                        candidate,
                        confidence=confidence,
                        grayscale=grayscale,
                        region=self._capture_region(search_region, display_scale),
                    )
                except (pyautogui.ImageNotFoundException, pyscreeze.ImageNotFoundException):
                    box = None
                finally:
                    if candidate is not template:
                        candidate.close()
                if box is not None:
                    return self._match(path, box, confidence, scale, display_scale)
            return None
        finally:
            template.close()

    def _locate_all_once(self, path: str | Path, confidence: float, region: Any, grayscale: bool, scales: Sequence[float], limit: Optional[int]) -> list["ScreenBot.Match"]:
        search_region = None if region is None else self._resolve_box(region)
        display_scale = self._get_display_scale()
        template = self._load_template(path)
        results = []
        try:
            for scale in scales:
                candidate = self._scale_template(template, scale)
                try:
                    boxes = self._backend.locateAllOnScreen(
                        candidate,
                        confidence=confidence,
                        grayscale=grayscale,
                        region=self._capture_region(search_region, display_scale),
                    )
                    results.extend(
                        self._match(path, box, confidence, scale, display_scale)
                        for box in boxes
                    )
                except (pyautogui.ImageNotFoundException, pyscreeze.ImageNotFoundException):
                    continue
                finally:
                    if candidate is not template:
                        candidate.close()
        finally:
            template.close()

        kept = []
        for result in results:
            if all(self._iou(result.box, other.box) < 0.35 for other in kept):
                kept.append(result)
                if limit is not None and len(kept) == limit:
                    break
        return kept

    @staticmethod
    def _match(
        path: str | Path,
        box: Any,
        confidence: float,
        scale: float,
        display_scale: tuple[float, float] = (1.0, 1.0),
    ) -> "ScreenBot.Match":
        scale_x, scale_y = display_scale
        return ScreenBot.Match(
            round(box.left / scale_x), round(box.top / scale_y),
            round(box.width / scale_x), round(box.height / scale_y),
            float(confidence), str(path), float(scale),
        )

    def _get_display_scale(self) -> tuple[float, float]:
        """Return capture pixels per mouse-coordinate unit.

        macOS Retina screenshots can be twice the dimensions reported by the
        mouse API. PyAutoGUI's image matcher returns screenshot coordinates,
        while its input methods require the smaller logical coordinates.
        """
        if self._display_scale is not None:
            return self._display_scale
        if self._backend is not pyautogui:
            self._display_scale = (1.0, 1.0)
            return self._display_scale

        logical_width, logical_height = self.screen_size()
        capture_width, capture_height = self._backend.screenshot().size
        self._display_scale = (
            capture_width / logical_width if logical_width else 1.0,
            capture_height / logical_height if logical_height else 1.0,
        )
        return self._display_scale

    @staticmethod
    def _capture_region(
        region: Optional["ScreenBot.Box"],
        display_scale: tuple[float, float],
    ) -> Optional[tuple[int, int, int, int]]:
        if region is None:
            return None
        scale_x, scale_y = display_scale
        return (
            round(region.x * scale_x),
            round(region.y * scale_y),
            round(region.width * scale_x),
            round(region.height * scale_y),
        )

    @staticmethod
    def _load_template(path: str | Path) -> Image.Image:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"Template image not found: {source}")
        try:
            with Image.open(source) as image:
                image.load()
                return image.copy()
        except (OSError, ValueError) as error:
            raise ValueError(f"Could not read template image: {source}") from error

    @staticmethod
    def _scale_template(template: Image.Image, scale: float) -> Image.Image:
        if scale == 1:
            return template
        width, height = template.size
        resampling = Image.Resampling.LANCZOS if scale < 1 else Image.Resampling.BICUBIC
        return template.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            resampling,
        )

    def _load_points(self) -> dict[str, "ScreenBot.Point"]:
        if not self.coordinate_file.exists():
            return {}
        raw = json.loads(self.coordinate_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Coordinate file must contain a JSON object: {self.coordinate_file}")
        return {str(name): self._point(value) for name, value in raw.items()}

    def _resolve_point(self, value: Any) -> "ScreenBot.Point":
        if isinstance(value, (str, Path)):
            return self._point_from_file(value, self.system_id)
        return self._point(value)

    def _resolve_box(self, value: Any) -> "ScreenBot.Box":
        if isinstance(value, (str, Path)):
            return self._box_from_file(value, self.system_id)
        return self._box(value)

    def _save_system_coordinate(
        self, path: str | Path, coordinate_type: str, value: dict[str, int]
    ) -> None:
        output = Path(path)
        systems: dict[str, Any] = {}
        if output.exists():
            raw = self._read_coordinate_file(output)
            if self._is_portable_coordinate(raw):
                if raw["type"] != coordinate_type:
                    raise ValueError(
                        f"Cannot save a {coordinate_type} in {raw['type']} file: {output}"
                    )
                systems.update(raw["systems"])
            elif self._is_legacy_coordinate(raw, coordinate_type):
                systems[self.system_id] = raw
            else:
                raise ValueError(f"Invalid {coordinate_type} file: {output}")
        systems[self.system_id] = value
        payload = {"type": coordinate_type, "systems": systems}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def _resolve_system_id(cls, explicit: Optional[str] = None) -> str:
        configured = explicit or os.environ.get(cls.SYSTEM_ID_ENV)
        if configured:
            return cls._validate_system_id(configured)

        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = config_home / "screenbot" / "system-id"
        if path.exists():
            return cls._validate_system_id(path.read_text(encoding="utf-8").strip())

        generated = str(uuid.uuid4())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated + "\n", encoding="utf-8")
        return generated

    @staticmethod
    def _validate_system_id(value: str) -> str:
        normalized = str(value).strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("ScreenBot system ID must be a non-empty value without spaces")
        return normalized

    @staticmethod
    def _is_portable_coordinate(raw: Any) -> bool:
        return (
            isinstance(raw, dict)
            and raw.get("type") in {"position", "box"}
            and isinstance(raw.get("systems"), dict)
        )

    @staticmethod
    def _is_legacy_coordinate(raw: Any, coordinate_type: str) -> bool:
        fields = {"x", "y"} if coordinate_type == "position" else {
            "left", "top", "right", "bottom"
        }
        return isinstance(raw, dict) and set(raw) == fields

    @classmethod
    def _coordinate_for_system(
        cls, raw: Any, path: Path, coordinate_type: str, system_id: Optional[str]
    ) -> Any:
        if cls._is_legacy_coordinate(raw, coordinate_type):
            return raw
        if not cls._is_portable_coordinate(raw) or raw["type"] != coordinate_type:
            raise ValueError(f"Invalid {coordinate_type} file: {path}")
        current_id = system_id or cls._resolve_system_id()
        try:
            return raw["systems"][current_id]
        except KeyError as error:
            raise ValueError(
                f"No {coordinate_type} saved for this system ({current_id}) in {path}; "
                "run the corresponding screenbot command with --save on this system"
            ) from error

    @staticmethod
    def _color_counts(image: Image.Image) -> list["ScreenBot.ColorCount"]:
        rgb = image.convert("RGB")
        try:
            counts = Counter(rgb.get_flattened_data())
        finally:
            rgb.close()
        total = sum(counts.values())
        return [
            ScreenBot.ColorCount(
                tuple(int(channel) for channel in color),
                count,
                (count / total * 100) if total else 0.0,
            )
            for color, count in counts.most_common()
        ]

    @staticmethod
    def _read_coordinate_file(path: str | Path) -> Any:
        source = Path(path)
        try:
            return json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid coordinate file: {source}") from error

    def _random_point_in_box(self, box: "ScreenBot.Box", padding: int) -> "ScreenBot.Point":
        pad = self._integer_non_negative(padding, "padding")
        left, top = box.left + pad, box.top + pad
        right, bottom = box.right - pad - 1, box.bottom - pad - 1
        if right < left or bottom < top:
            return box.center
        return self.Point(self._random.randint(left, right), self._random.randint(top, bottom))

    def _point_in_circle(self, radius: int) -> tuple[int, int]:
        while True:
            dx = self._random.randint(-radius, radius)
            dy = self._random.randint(-radius, radius)
            if dx * dx + dy * dy <= radius * radius:
                return dx, dy

    def _point_near_center(self, box: "ScreenBot.Box", radius: int) -> "ScreenBot.Point":
        center = box.center
        if radius == 0 or (box.width <= 1 and box.height <= 1):
            return center

        while True:
            dx, dy = self._point_in_circle(radius)
            target = self.Point(
                min(max(center.x + dx, box.left), box.right - 1),
                min(max(center.y + dy, box.top), box.bottom - 1),
            )
            if target != center:
                return target

    def _pause(self, value_range: tuple[float, float], *, factor: float = 1.0) -> None:
        self._sleep(self._random.uniform(*value_range) * factor)

    def _wait_after_action(self) -> None:
        minimum, maximum = self.wait_time
        if maximum <= 0:
            return
        duration = minimum if minimum == maximum else self._random.uniform(minimum, maximum)
        self._sleep(duration)

    def _human_interval(self, explicit: Optional[float], default: tuple[float, float]) -> float:
        return self._random.uniform(*default) if explicit is None else self._non_negative(explicit, "interval") * self._random.uniform(0.75, 1.25)

    def _typing_mistake(self, char: str) -> Optional[str]:
        neighbors = self.KEY_NEIGHBORS.get(char.lower())
        if not neighbors or self._random.random() >= self.human_typo_chance:
            return None
        mistake = self._random.choice(neighbors)
        return mistake.upper() if char.isupper() else mistake

    @classmethod
    def _point(cls, value: Any) -> "ScreenBot.Point":
        if isinstance(value, cls.Point):
            return value
        if isinstance(value, (str, Path)):
            return cls._point_from_file(value)
        try:
            x, y = value
            return cls.Point(round(x), round(y))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "point must be ScreenBot.Point, a 2-item sequence, or a position file path"
            ) from exc

    @classmethod
    def _point_from_file(
        cls, path: str | Path, system_id: Optional[str] = None
    ) -> "ScreenBot.Point":
        source = Path(path)
        raw = cls._coordinate_for_system(
            cls._read_coordinate_file(source), source, "position", system_id
        )
        if not isinstance(raw, dict) or set(raw) != {"x", "y"}:
            raise ValueError(f"Position file must contain numeric 'x' and 'y' fields: {source}")
        try:
            return cls.Point(round(raw["x"]), round(raw["y"]))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Position file must contain numeric 'x' and 'y' fields: {source}") from error

    @classmethod
    def _box(cls, value: Any) -> "ScreenBot.Box":
        if isinstance(value, cls.Box):
            return value
        if isinstance(value, (str, Path)):
            return cls._box_from_file(value)
        try:
            top_left, top_right, bottom_right, bottom_left = value
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "box must be ScreenBot.Box or four corner points"
            ) from exc
        return cls.Box(top_left, top_right, bottom_right, bottom_left)

    @classmethod
    def _box_from_file(
        cls, path: str | Path, system_id: Optional[str] = None
    ) -> "ScreenBot.Box":
        source = Path(path)
        raw = cls._coordinate_for_system(
            cls._read_coordinate_file(source), source, "box", system_id
        )
        fields = {"left", "top", "right", "bottom"}
        if not isinstance(raw, dict) or set(raw) != fields:
            raise ValueError(
                "Box file must contain numeric 'left', 'top', 'right', and "
                f"'bottom' fields: {source}"
            )
        try:
            left, top = round(raw["left"]), round(raw["top"])
            right, bottom = round(raw["right"]), round(raw["bottom"])
            return cls.Box(
                (left, top), (right, top), (right, bottom), (left, bottom)
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Box file contains invalid coordinates: {source}") from error

    @staticmethod
    def _normalize_state(state: str) -> str:
        normalized = str(state).strip().lower().replace("_", "-")
        if normalized not in ScreenBot.STATES:
            raise ValueError(f"state must be one of {ScreenBot.STATES}, got {state!r}")
        return normalized

    @staticmethod
    def _confidence(value: float) -> float:
        number = float(value)
        if not 0 <= number <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return number

    @staticmethod
    def _non_negative(value: float, name: str) -> float:
        number = float(value)
        if number < 0:
            raise ValueError(f"{name} cannot be negative")
        return number

    @staticmethod
    def _integer_non_negative(value: int, name: str) -> int:
        number = int(value)
        if number < 0:
            raise ValueError(f"{name} cannot be negative")
        return number

    @staticmethod
    def _positive_integer(value: int, name: str) -> int:
        number = int(value)
        if number < 1:
            raise ValueError(f"{name} must be at least 1")
        return number

    @staticmethod
    def _range(value: tuple[float, float], name: str) -> tuple[float, float]:
        if len(value) != 2:
            raise ValueError(f"{name} must contain (minimum, maximum)")
        low, high = float(value[0]), float(value[1])
        if low < 0 or high < low:
            raise ValueError(f"{name} must satisfy 0 <= minimum <= maximum")
        return low, high

    @classmethod
    def _positive_range(cls, value: tuple[float, float], name: str) -> tuple[float, float]:
        low, high = cls._range(value, name)
        if low <= 0:
            raise ValueError(f"{name} minimum must be greater than zero")
        return low, high

    @staticmethod
    def _probability(value: float, name: str) -> float:
        number = float(value)
        if not 0 <= number <= 1:
            raise ValueError(f"{name} must be between 0 and 1")
        return number

    @staticmethod
    def _percentage(value: float, name: str) -> float:
        number = float(value)
        if not 0 <= number <= 100:
            raise ValueError(f"{name} must be between 0 and 100")
        return number

    @staticmethod
    def _validate_scales(scales: Sequence[float]) -> tuple[float, ...]:
        values = tuple(float(scale) for scale in scales)
        if not values or any(scale <= 0 for scale in values):
            raise ValueError("scales must contain at least one positive number")
        return values

    @staticmethod
    def _iou(a: "ScreenBot.Box", b: "ScreenBot.Box") -> float:
        width = max(0, min(a.right, b.right) - max(a.left, b.left))
        height = max(0, min(a.bottom, b.bottom) - max(a.top, b.top))
        intersection = width * height
        union = a.width * a.height + b.width * b.height - intersection
        return intersection / union if union else 0.0
