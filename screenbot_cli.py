"""Command-line interface for screenbot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from screenbot import ScreenBot


def _point_dict(point: ScreenBot.Point) -> dict[str, int]:
    return {"x": point.x, "y": point.y}


def _box_dict(box: ScreenBot.Box) -> dict[str, int]:
    return {
        "left": box.left,
        "top": box.top,
        "right": box.right,
        "bottom": box.bottom,
        "width": box.width,
        "height": box.height,
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, separators=(",", ":")))


def _add_box_source(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--box-file", type=Path, help="read the box from a screenbot JSON file")
    source.add_argument(
        "--box",
        nargs=4,
        type=int,
        metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
        help="use explicit box coordinates instead of pressing 0 at each corner",
    )


def _resolve_box(bot: ScreenBot, args: argparse.Namespace) -> ScreenBot.Box:
    if args.box_file:
        return bot.load_box_file(args.box_file)
    if args.box:
        left, top, right, bottom = args.box
        return bot.Box((left, top), (right, top), (right, bottom), (left, bottom))
    return bot.capture_box_on_key()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenbot",
        description="Inspect screen coordinates and colors from scripts.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")
    commands = parser.add_subparsers(dest="command", required=True)

    mouse = commands.add_parser("mouse", help="print or save the current mouse position")
    mouse.add_argument("--save", type=Path, metavar="FILE", help="save as a position JSON file")
    mouse.add_argument("--json", action="store_true", help="print compact JSON")

    box = commands.add_parser("box", help="capture a box by pressing 0 at four corners")
    box.add_argument("--save", type=Path, metavar="FILE", help="save as a box JSON file")
    box.add_argument("--json", action="store_true", help="print compact JSON")

    pixel = commands.add_parser("pixel", help="print the RGB color under the mouse")
    pixel.add_argument("--at", nargs=2, type=int, metavar=("X", "Y"), help="inspect a coordinate")
    pixel.add_argument("--json", action="store_true", help="print compact JSON")

    colors = commands.add_parser("colors", help="list colors from an image or screen box")
    colors.add_argument("image", nargs="?", type=Path, help="image file; omit to capture a box")
    _add_box_source(colors)
    colors.add_argument("--limit", type=int, help="only print the N most common colors")
    colors.add_argument(
        "--pixels",
        action="store_true",
        help="print every pixel in a screen box instead of aggregate counts",
    )
    colors.add_argument("--json", action="store_true", help="print one JSON object per line")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    bot = ScreenBot()

    if args.command == "mouse":
        point = bot.mouse_position()
        if args.save:
            bot.save_position_file(args.save, point)
        _print_json(_point_dict(point)) if args.json else print(f"{point.x} {point.y}")
        return 0

    if args.command == "box":
        value = bot.capture_box_on_key()
        if args.save:
            bot.save_box_file(args.save, value)
        data = _box_dict(value)
        _print_json(data) if args.json else print(
            f"{value.left} {value.top} {value.right} {value.bottom}"
        )
        return 0

    if args.command == "pixel":
        point = bot.mouse_position() if args.at is None else bot.Point(*args.at)
        color = bot.pixel_color(point)
        data = {**_point_dict(point), "rgb": list(color), "hex": "#" + "".join(f"{c:02X}" for c in color)}
        _print_json(data) if args.json else print(
            f"{data['hex']} {color[0]} {color[1]} {color[2]}"
        )
        return 0

    if args.command == "colors":
        if args.image and (args.box or args.box_file):
            parser.error("an image cannot be combined with --box or --box-file")
        if args.image and args.pixels:
            parser.error("--pixels is only available for screen boxes")
        if args.limit is not None and args.limit < 1:
            parser.error("--limit must be at least 1")

        if args.image:
            counts = bot.colors_in_image(args.image)
        else:
            value = _resolve_box(bot, args)
            if args.pixels:
                for pixel_value in bot.pixels_in_box(value):
                    _print_json(pixel_value.as_dict()) if args.json else print(
                        f"{pixel_value.x} {pixel_value.y} {pixel_value.hex} "
                        f"{pixel_value.color[0]} {pixel_value.color[1]} {pixel_value.color[2]}"
                    )
                return 0
            counts = bot.colors_in_box(value)

        if args.limit is not None:
            counts = counts[: args.limit]
        for item in counts:
            _print_json(item.as_dict()) if args.json else print(
                f"{item.hex} {item.color[0]} {item.color[1]} {item.color[2]} "
                f"{item.count} {item.percentage:.4f}%"
            )
        return 0

    return 1


def cli() -> int:
    """Run the console entry point with concise operational errors."""
    try:
        return main()
    except KeyboardInterrupt:
        print("screenbot: interrupted", file=sys.stderr)
        return 130
    except (ScreenBot.Error, ValueError, OSError) as error:
        print(f"screenbot: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
