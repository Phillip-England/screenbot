import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from PIL import Image
from pyscreeze import ImageNotFoundException as PyScreezeImageNotFound

from screenbot import ScreenBot, VirtualDir


class VirtualDirTests(unittest.TestCase):
    def test_path_joins_components_under_directory(self) -> None:
        directory = VirtualDir("./static")

        self.assertEqual(
            directory.path("img", "some-img.png"),
            os.path.join("./static", "img", "some-img.png"),
        )

    def test_path_accepts_pathlike_components(self) -> None:
        directory = VirtualDir(Path("assets"))

        self.assertEqual(
            directory.path(Path("icons"), Path("save.png")),
            os.path.join("assets", "icons", "save.png"),
        )


class KeyboardTests(unittest.TestCase):
    def test_named_special_keys_use_portable_backend_names(self) -> None:
        backend = Mock()
        bot = ScreenBot(backend=backend, sleeper=Mock())
        methods = {
            "press_arrow_up": "up",
            "press_arrow_down": "down",
            "press_arrow_left": "left",
            "press_arrow_right": "right",
            "press_enter": "enter",
            "press_escape": "esc",
            "press_tab": "tab",
            "press_space": "space",
            "press_backspace": "backspace",
            "press_delete": "delete",
            "press_insert": "insert",
            "press_home": "home",
            "press_end": "end",
            "press_page_up": "pageup",
            "press_page_down": "pagedown",
        }

        for method_name, key in methods.items():
            with self.subTest(method=method_name):
                self.assertEqual(getattr(bot, method_name)(), key)

        self.assertEqual(
            backend.method_calls,
            [
                event
                for key in methods.values()
                for event in (call.keyDown(key), call.keyUp(key), call.keyUp(key))
            ],
        )

    def test_named_special_key_forwards_repeat_options(self) -> None:
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(backend=backend, sleeper=sleeper)

        bot.press_arrow_down(presses=3, interval=0.2)

        self.assertEqual(
            backend.method_calls,
            [
                call.keyDown("down"), call.keyUp("down"), call.keyUp("down"),
                call.keyDown("down"), call.keyUp("down"), call.keyUp("down"),
                call.keyDown("down"), call.keyUp("down"), call.keyUp("down"),
            ],
        )
        self.assertEqual(
            sleeper.call_args_list,
            [
                call(0.05), call(0.05), call(0.2),
                call(0.05), call(0.05), call(0.2),
                call(0.05), call(0.05),
            ],
        )

    def test_function_keys_are_validated_and_pressed(self) -> None:
        backend = Mock()
        bot = ScreenBot(backend=backend, sleeper=Mock())

        self.assertEqual(bot.press_function_key(12), "f12")
        self.assertEqual(
            backend.method_calls,
            [call.keyDown("f12"), call.keyUp("f12"), call.keyUp("f12")],
        )
        for number in (0, 25):
            with self.subTest(number=number):
                with self.assertRaisesRegex(ValueError, "function key number"):
                    bot.press_function_key(number)

    def test_press_and_release_is_an_explicit_alias_for_press(self) -> None:
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(backend=backend, sleeper=sleeper)

        self.assertEqual(bot.press_and_release("shift"), "shift")

        self.assertEqual(
            backend.method_calls,
            [call.keyDown("shift"), call.keyUp("shift"), call.keyUp("shift")],
        )
        self.assertEqual(sleeper.call_args_list, [call(0.05), call(0.05)])

    def test_release_settles_before_following_shortcut(self) -> None:
        events = Mock()
        backend = Mock()
        sleeper = Mock()
        events.attach_mock(backend, "backend")
        events.attach_mock(sleeper, "sleep")
        bot = ScreenBot(backend=backend, sleeper=sleeper)

        with patch("screenbot.sys.platform", "linux"):
            bot.press_and_release("up")
            bot.keycombo(("ctrl", "l"), ("command", "l"))

        self.assertEqual(
            events.method_calls,
            [
                call.backend.keyDown("up"),
                call.sleep(0.05),
                call.backend.keyUp("up"),
                call.sleep(0.05),
                call.backend.keyUp("up"),
                call.backend.hotkey("ctrl", "l"),
            ],
        )

    def test_press_releases_key_when_dwell_is_interrupted(self) -> None:
        backend = Mock()
        sleeper = Mock(side_effect=RuntimeError("interrupted"))
        bot = ScreenBot(backend=backend, sleeper=sleeper)

        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            bot.press("ctrl")

        self.assertEqual(
            backend.method_calls,
            [call.keyDown("ctrl"), call.keyUp("ctrl")],
        )

    def test_human_like_press_randomizes_key_dwell(self) -> None:
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(
            state=ScreenBot.HUMAN_LIKE,
            backend=backend,
            sleeper=sleeper,
            seed=7,
        )

        bot.press("enter")

        self.assertEqual(
            backend.method_calls,
            [call.keyDown("enter"), call.keyUp("enter"), call.keyUp("enter")],
        )
        dwell = sleeper.call_args_list[1].args[0]
        self.assertGreaterEqual(dwell, bot.human_key_dwell[0])
        self.assertLessEqual(dwell, bot.human_key_dwell[1])

    def test_hold_and_release_send_explicit_key_events(self) -> None:
        backend = Mock()
        bot = ScreenBot(backend=backend)

        self.assertEqual(bot.hold("shift"), "shift")
        self.assertEqual(bot.release("shift"), "shift")

        self.assertEqual(
            backend.method_calls,
            [call.keyDown("shift"), call.keyUp("shift")],
        )

    def test_hold_and_release_are_explicit_in_human_like_mode(self) -> None:
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(state=ScreenBot.HUMAN_LIKE, backend=backend, sleeper=sleeper)

        bot.hold("ctrl")
        bot.release("ctrl")

        self.assertEqual(
            backend.method_calls,
            [call.keyDown("ctrl"), call.keyUp("ctrl")],
        )
        sleeper.assert_not_called()


class LoggingTests(unittest.TestCase):
    def test_log_true_outputs_actions_with_results(self) -> None:
        output = io.StringIO()
        backend = Mock()
        backend.position.return_value = SimpleNamespace(x=12, y=34)
        bot = ScreenBot(backend=backend, sleeper=Mock(), log=True, log_stream=output)

        bot.press_arrow_up()
        bot.click()

        log = output.getvalue()
        self.assertIn("[ScreenBot] press('up') -> 'up'", log)
        self.assertIn("[ScreenBot] click() -> ScreenBot.Point(x=12, y=34)", log)

    def test_logging_is_off_by_default_and_can_be_toggled(self) -> None:
        output = io.StringIO()
        bot = ScreenBot(backend=Mock(), sleeper=Mock(), log_stream=output)

        bot.press_enter()
        self.assertEqual(output.getvalue(), "")

        self.assertIs(bot.set_logging(), bot)
        bot.press_escape()
        self.assertIn("[ScreenBot] press('esc') -> 'esc'", output.getvalue())

        bot.set_logging(False)
        previous_output = output.getvalue()
        bot.press_tab()
        self.assertEqual(output.getvalue(), previous_output)

    def test_image_searches_and_waits_are_logged(self) -> None:
        output = io.StringIO()
        backend = Mock()
        backend.locateOnScreen.return_value = None
        bot = ScreenBot(backend=backend, log=True, log_stream=output)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.png"
            Image.new("RGB", (4, 4)).save(path)
            self.assertIsNone(bot.locate(path))
        bot.wait(0.25)

        log = output.getvalue()
        self.assertIn(f"[ScreenBot] locate({str(path)!r}) -> no match", log)
        self.assertIn("[ScreenBot] wait(seconds=0.25)", log)


class WindowAndClickTests(unittest.TestCase):
    def test_right_click_uses_right_mouse_button(self) -> None:
        backend = Mock()
        backend.position.return_value = SimpleNamespace(x=12, y=34)
        bot = ScreenBot(backend=backend)

        self.assertEqual(bot.right_click((50, 60)), ScreenBot.Point(50, 60))

        backend.click.assert_called_once_with(
            x=50, y=60, clicks=1, interval=0.0, button="right"
        )

    def test_keycombo_uses_macos_combo(self) -> None:
        bot = ScreenBot(backend=Mock())

        with patch("screenbot.sys.platform", "darwin"):
            result = bot.keycombo(("control", "p"), ("command", "p"))

        self.assertEqual(result, ("command", "p"))
        bot._backend.hotkey.assert_called_once_with("command", "p")

    def test_keycombo_uses_windows_linux_combo(self) -> None:
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform):
                bot = ScreenBot(backend=Mock())
                with patch("screenbot.sys.platform", platform):
                    result = bot.keycombo(("control", "p"), ("command", "p"))

                self.assertEqual(result, ("ctrl", "p"))
                bot._backend.hotkey.assert_called_once_with("ctrl", "p")

    def test_keycombo_requires_both_platform_combos(self) -> None:
        bot = ScreenBot(backend=Mock())

        for windows_linux, macos in (((), ("command", "p")), (("ctrl", "p"), ())):
            with self.subTest(windows_linux=windows_linux, macos=macos):
                with self.assertRaisesRegex(ValueError, "non-empty combo"):
                    bot.keycombo(windows_linux, macos)


class KillSequenceTests(unittest.TestCase):
    @patch("screenbot.os.kill")
    @patch("screenbot.keyboard.Listener")
    def test_kill_sequence_interrupts_process_when_typed(self, listener_type, kill) -> None:
        listener = listener_type.return_value
        bot = ScreenBot(backend=Mock(), kill_sequence="911")
        on_press = listener_type.call_args.kwargs["on_press"]

        for char in "x911":
            on_press(Mock(char=char))

        listener.start.assert_called_once_with()
        listener.stop.assert_called_once_with()
        kill.assert_called_once()
        self.assertEqual(kill.call_args.args[1], __import__("signal").SIGINT)
        self.assertIsNone(bot._kill_listener)

    @patch("screenbot.keyboard.Listener")
    def test_kill_sequence_can_be_reconfigured_or_disabled(self, listener_type) -> None:
        first_listener = Mock()
        second_listener = Mock()
        listener_type.side_effect = [first_listener, second_listener]
        bot = ScreenBot(backend=Mock(), kill_sequence="911")

        self.assertIs(bot.configure_kill_sequence("123"), bot)
        first_listener.stop.assert_called_once_with()
        second_listener.start.assert_called_once_with()

        self.assertIs(bot.configure_kill_sequence(None), bot)
        second_listener.stop.assert_called_once_with()
        self.assertIsNone(bot.kill_sequence)

    @patch("screenbot.keyboard.Listener")
    def test_kill_sequence_must_not_be_empty(self, listener_type) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty string"):
            ScreenBot(backend=Mock(), kill_sequence="")

        listener_type.assert_not_called()


class ImageCountTests(unittest.TestCase):
    def test_count_images_returns_zero_when_no_templates_match(self) -> None:
        backend = Mock()

        def no_matches(*args, **kwargs):
            def matches():
                raise PyScreezeImageNotFound("not found")
                yield

            return matches()

        backend.locateAllOnScreen.side_effect = no_matches
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            paths = [Path(directory) / "one.png", Path(directory) / "two.png"]
            for path in paths:
                Image.new("RGB", (4, 4)).save(path)

            self.assertEqual(bot.count_images(paths), 0)

    def test_count_images_uses_backend_image_detection_for_every_template(self) -> None:
        backend = Mock()
        backend.locateAllOnScreen.side_effect = [
            [
                SimpleNamespace(left=10, top=20, width=5, height=6),
                SimpleNamespace(left=20, top=20, width=5, height=6),
            ],
            [SimpleNamespace(left=30, top=40, width=7, height=8)],
        ]
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            paths = [Path(directory) / "one.png", Path(directory) / "two.png"]
            for path in paths:
                Image.new("RGB", (4, 4)).save(path)

            count = bot.count_images(paths, confidence=0.9, grayscale=False)

        self.assertEqual(count, 3)
        self.assertEqual(backend.locateAllOnScreen.call_count, 2)
        for image_call in backend.locateAllOnScreen.call_args_list:
            self.assertIsInstance(image_call.args[0], Image.Image)
            self.assertEqual(image_call.kwargs["confidence"], 0.9)
            self.assertFalse(image_call.kwargs["grayscale"])
            self.assertIsNone(image_call.kwargs["region"])

    def test_image_matches_are_converted_from_capture_to_mouse_coordinates(self) -> None:
        backend = Mock()
        backend.locateOnScreen.return_value = SimpleNamespace(
            left=400, top=200, width=100, height=40
        )
        bot = ScreenBot(backend=backend)
        bot._display_scale = (2.0, 2.0)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "button.png"
            Image.new("RGB", (10, 10)).save(path)
            match = bot.locate(path, region=ScreenBot.Box(
                (10, 20), (110, 20), (110, 70), (10, 70)
            ))

        self.assertEqual((match.x, match.y, match.width, match.height), (200, 100, 50, 20))
        self.assertEqual(backend.locateOnScreen.call_args.kwargs["region"], (20, 40, 200, 100))


class GridClickTests(unittest.TestCase):
    BOX = ScreenBot.Box((10, 20), (90, 20), (90, 90), (10, 90))

    def test_click_grid_clicks_all_28_centers_once_in_random_order(self) -> None:
        backend = Mock()
        bot = ScreenBot(backend=backend, seed=7)

        points = bot.click_grid(self.BOX)

        row_major = [
            ScreenBot.Point(x, y)
            for y in (25, 35, 45, 55, 65, 75, 85)
            for x in (20, 40, 60, 80)
        ]
        self.assertEqual(len(points), 28)
        self.assertEqual(set(points), set(row_major))
        self.assertNotEqual(points, row_major)
        self.assertEqual(backend.click.call_count, 28)

    def test_click_grid_varies_targets_within_radius_and_cell(self) -> None:
        bot = ScreenBot(backend=Mock(), seed=11)

        points = bot.click_grid(self.BOX, variation=5, dry_run=True)

        centers = [
            ScreenBot.Point(x, y)
            for y in (25, 35, 45, 55, 65, 75, 85)
            for x in (20, 40, 60, 80)
        ]
        self.assertEqual(len(points), 28)
        for point in points:
            self.assertTrue(any(
                (point.x - center.x) ** 2 + (point.y - center.y) ** 2 <= 5 ** 2
                for center in centers
            ))


class ImageClickAllTests(unittest.TestCase):
    def test_click_all_images_shuffles_matches_and_clicks_near_centers(self) -> None:
        backend = Mock()
        boxes = [
            SimpleNamespace(left=x, top=20, width=12, height=10)
            for x in (10, 30, 50, 70, 90, 110)
        ]
        backend.locateAllOnScreen.return_value = boxes
        bot = ScreenBot(backend=backend, seed=7)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "item.png"
            Image.new("RGB", (4, 4)).save(path)
            points = bot.click_all_images(path, variation=4)

        centers = [ScreenBot.Point(box.left + 6, box.top + 5) for box in boxes]
        self.assertEqual(len(points), len(centers))
        self.assertEqual(backend.click.call_count, len(centers))
        self.assertNotEqual(
            [min(centers, key=lambda center: (point.x - center.x) ** 2 + (point.y - center.y) ** 2)
             for point in points],
            centers,
        )
        for point in points:
            center = min(
                centers,
                key=lambda candidate: (point.x - candidate.x) ** 2 + (point.y - candidate.y) ** 2,
            )
            distance_squared = (point.x - center.x) ** 2 + (point.y - center.y) ** 2
            self.assertGreater(distance_squared, 0)
            self.assertLessEqual(distance_squared, 4 ** 2)
            match_box = boxes[centers.index(center)]
            self.assertTrue(match_box.left <= point.x < match_box.left + match_box.width)
            self.assertTrue(match_box.top <= point.y < match_box.top + match_box.height)

    def test_click_all_images_returns_empty_list_when_none_match(self) -> None:
        backend = Mock()
        backend.locateAllOnScreen.return_value = []
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "item.png"
            Image.new("RGB", (4, 4)).save(path)
            self.assertEqual(bot.click_all_images(path), [])

        backend.click.assert_not_called()

    def test_click_all_images_rejects_negative_variation(self) -> None:
        bot = ScreenBot(backend=Mock())

        with self.assertRaisesRegex(ValueError, "variation"):
            bot.click_all_images("unused.png", variation=-1)


class ClickFirstAvailableImageTests(unittest.TestCase):
    def test_clicks_first_visible_image_in_path_order(self) -> None:
        backend = Mock()
        box = SimpleNamespace(left=40, top=60, width=20, height=10)
        backend.locateOnScreen.side_effect = [None, box]
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            paths = [
                Path(directory) / name
                for name in ("first.png", "second.png", "third.png")
            ]
            for path in paths:
                Image.new("RGB", (4, 4)).save(path)
            match = bot.click_first_available_image(paths, random_point=False)

        self.assertIsNotNone(match)
        self.assertEqual(match.center, ScreenBot.Point(50, 65))
        self.assertEqual(backend.locateOnScreen.call_count, 2)
        backend.click.assert_called_once_with(
            x=50, y=65, clicks=1, interval=0.0, button="left"
        )

    def test_returns_none_when_no_image_is_visible_and_not_required(self) -> None:
        backend = Mock()
        backend.locateOnScreen.return_value = None
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("first.png", "second.png")]
            for path in paths:
                Image.new("RGB", (4, 4)).save(path)
            match = bot.click_first_available_image(paths, required=False)

        self.assertIsNone(match)
        self.assertEqual(backend.locateOnScreen.call_count, 2)
        backend.click.assert_not_called()

    def test_raises_when_no_image_is_visible_by_default(self) -> None:
        bot = ScreenBot(backend=Mock())

        with self.assertRaises(ScreenBot.ImageNotFound):
            bot.click_first_available_image([])


class WaitForAndClickTests(unittest.TestCase):
    def test_default_timeout_is_one_second(self) -> None:
        bot = ScreenBot(backend=Mock())

        self.assertEqual(bot.timeout, 1.0)

    def test_default_timeout_can_be_configured(self) -> None:
        bot = ScreenBot(backend=Mock(), timeout=4.5)

        self.assertEqual(bot.timeout, 4.5)

    def test_waits_then_right_clicks_with_variation_inside_image(self) -> None:
        backend = Mock()
        backend.locateOnScreen.side_effect = [
            None,
            SimpleNamespace(left=100, top=200, width=12, height=8),
        ]
        bot = ScreenBot(backend=backend, seed=7)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "button.png"
            Image.new("RGB", (4, 4)).save(path)
            match = bot.wait_for_and_click(
                path, timeout=1, interval=0, variation=20, button="right"
            )

        self.assertIsNotNone(match)
        self.assertEqual(backend.locateOnScreen.call_count, 2)
        click = backend.click.call_args.kwargs
        self.assertTrue(100 <= click["x"] < 112)
        self.assertTrue(200 <= click["y"] < 208)
        self.assertEqual(click["button"], "right")

    def test_optional_missing_image_does_not_click(self) -> None:
        backend = Mock()
        backend.locateOnScreen.return_value = None
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "button.png"
            Image.new("RGB", (4, 4)).save(path)
            match = bot.wait_for_and_click(path, timeout=0, required=False)

        self.assertIsNone(match)
        backend.click.assert_not_called()

    def test_rejects_negative_variation(self) -> None:
        bot = ScreenBot(backend=Mock())

        with self.assertRaisesRegex(ValueError, "variation"):
            bot.wait_for_and_click("unused.png", variation=-1)


class CoordinateFileTests(unittest.TestCase):
    def test_position_file_round_trip_and_direct_click(self) -> None:
        backend = Mock()
        bot = ScreenBot(backend=backend, system_id="workstation-a")

        with TemporaryDirectory() as directory:
            path = Path(directory) / "buttons" / "login.pos"
            saved = bot.save_position_file(path, (120, 75))

            self.assertEqual(saved, ScreenBot.Point(120, 75))
            self.assertEqual(bot.load_position_file(path), saved)
            self.assertEqual(bot.click(path), saved)
            self.assertEqual(json.loads(path.read_text()), {
                "type": "position",
                "systems": {"workstation-a": {"x": 120, "y": 75}},
            })

        backend.click.assert_called_once_with(
            x=120, y=75, clicks=1, interval=0.0, button="left"
        )

    def test_box_file_round_trip_and_direct_grid_use(self) -> None:
        bot = ScreenBot(backend=Mock(), seed=3)
        box = ScreenBot.Box((10, 20), (30, 20), (30, 40), (10, 40))

        with TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.box"
            saved = bot.save_box_file(path, box)

            self.assertEqual(saved, box)
            self.assertEqual(bot.load_box_file(path), box)
            points = bot.click_grid(path, columns=2, rows=2, dry_run=True)

        self.assertEqual(
            set(points),
            {ScreenBot.Point(15, 25), ScreenBot.Point(25, 25),
             ScreenBot.Point(15, 35), ScreenBot.Point(25, 35)},
        )

    def test_box_file_can_be_used_as_image_search_region(self) -> None:
        backend = Mock()
        backend.locateOnScreen.return_value = None
        bot = ScreenBot(backend=backend)

        with TemporaryDirectory() as directory:
            box_path = Path(directory) / "search.box"
            image_path = Path(directory) / "item.png"
            bot.save_box_file(
                box_path,
                ScreenBot.Box((10, 20), (50, 20), (50, 60), (10, 60)),
            )
            Image.new("RGB", (4, 4)).save(image_path)
            bot.locate(image_path, region=box_path)

        self.assertEqual(backend.locateOnScreen.call_args.kwargs["region"], (10, 20, 40, 40))

    def test_coordinate_file_types_are_validated(self) -> None:
        bot = ScreenBot(backend=Mock())

        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.pos"
            path.write_text('{"left": 1, "top": 2}')

            with self.assertRaisesRegex(ValueError, "position file"):
                bot.load_position_file(path)

    def test_coordinate_file_merges_and_selects_system_entries(self) -> None:
        first = ScreenBot(backend=Mock(), system_id="workstation-a")
        second = ScreenBot(backend=Mock(), system_id="workstation-b")

        with TemporaryDirectory() as directory:
            path = Path(directory) / "login.json"
            first.save_position_file(path, (10, 20))
            second.save_position_file(path, (30, 40))

            self.assertEqual(first.load_position_file(path), ScreenBot.Point(10, 20))
            self.assertEqual(second.load_position_file(path), ScreenBot.Point(30, 40))
            self.assertEqual(json.loads(path.read_text())["systems"], {
                "workstation-a": {"x": 10, "y": 20},
                "workstation-b": {"x": 30, "y": 40},
            })

    def test_coordinate_file_rejects_unsaved_system(self) -> None:
        first = ScreenBot(backend=Mock(), system_id="workstation-a")
        second = ScreenBot(backend=Mock(), system_id="workstation-b")

        with TemporaryDirectory() as directory:
            path = Path(directory) / "toolbar.json"
            first.save_box_file(path, ((1, 2), (5, 2), (5, 7), (1, 7)))

            with self.assertRaisesRegex(ValueError, "No box saved.*workstation-b"):
                second.load_box_file(path)

    def test_legacy_coordinate_files_remain_readable(self) -> None:
        bot = ScreenBot(backend=Mock(), system_id="workstation-a")

        with TemporaryDirectory() as directory:
            position = Path(directory) / "position.json"
            box = Path(directory) / "box.json"
            position.write_text('{"x": 4, "y": 9}')
            box.write_text('{"left": 1, "top": 2, "right": 5, "bottom": 7}')

            self.assertEqual(bot.load_position_file(position), ScreenBot.Point(4, 9))
            self.assertEqual(bot.load_box_file(box).as_region_tuple(), (1, 2, 4, 5))


if __name__ == "__main__":
    unittest.main()
