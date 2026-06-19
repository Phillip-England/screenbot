import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from screenbot import ScreenBot, VirtualDir
from screenbot_cli import main


class VirtualDirTests(unittest.TestCase):
    def test_path_joins_components_under_directory(self):
        directory = VirtualDir("./static")

        self.assertEqual(
            directory.path("img", "some-img.png"),
            os.path.join("./static", "img", "some-img.png"),
        )

    def test_path_accepts_pathlike_components(self):
        directory = VirtualDir(Path("assets"))

        self.assertEqual(
            directory.path(Path("icons"), Path("save.png")),
            os.path.join("assets", "icons", "save.png"),
        )


class FakePoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class FakeBackend:
    FAILSAFE = True
    PAUSE = 0

    def position(self):
        return FakePoint(12, 34)

    def pixel(self, x, y):
        return (x, y, 99)

    def screenshot(self, region=None):
        image = Image.new("RGB", (2, 2), "red")
        image.putpixel((1, 1), (0, 0, 255))
        return image


class ScreenBotTests(unittest.TestCase):
    def setUp(self):
        self.bot = ScreenBot(backend=FakeBackend())

    def test_pixel_color_defaults_to_mouse(self):
        self.assertEqual(self.bot.pixel_color(), (12, 34, 99))

    def test_screen_center_uses_primary_screen_dimensions(self):
        backend = Mock()
        backend.size.return_value = SimpleNamespace(width=1919, height=1079)
        bot = ScreenBot(backend=backend)

        self.assertEqual(bot.screen_center(), ScreenBot.Point(959, 539))

    def test_move_to_center_moves_to_screen_center(self):
        backend = Mock()
        backend.size.return_value = SimpleNamespace(width=1920, height=1080)
        bot = ScreenBot(backend=backend)

        self.assertEqual(bot.move_to_center(duration=0.25), ScreenBot.Point(960, 540))
        backend.moveTo.assert_called_once_with(960, 540, duration=0.25)

    def test_click_center_forwards_click_options(self):
        backend = Mock()
        backend.size.return_value = SimpleNamespace(width=1920, height=1080)
        bot = ScreenBot(backend=backend)

        self.assertEqual(bot.click_center(button="right"), ScreenBot.Point(960, 540))
        backend.click.assert_called_once_with(
            x=960, y=540, clicks=1, interval=0.0, button="right"
        )

    def test_color_counts_are_most_common_first(self):
        colors = self.bot.colors_in_box(((0, 0), (2, 0), (2, 2), (0, 2)))
        self.assertEqual(colors[0].color, (255, 0, 0))
        self.assertEqual(colors[0].count, 3)
        self.assertEqual(colors[1].hex, "#0000FF")

    def test_position_and_box_files_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            point_path = Path(directory) / "point.json"
            box_path = Path(directory) / "box.json"
            self.bot.save_position_file(point_path, (5, 8))
            self.bot.save_box_file(box_path, ((1, 2), (5, 2), (5, 7), (1, 7)))
            self.assertEqual(self.bot.load_position_file(point_path).as_tuple(), (5, 8))
            self.assertEqual(self.bot.load_box_file(box_path).as_region_tuple(), (1, 2, 4, 5))

    def test_chance_uses_percentage_threshold(self):
        self.bot._random.random = lambda: 0.049
        self.assertTrue(self.bot.chance(5))
        self.bot._random.random = lambda: 0.05
        self.assertFalse(self.bot.chance(5))

    def test_chance_validates_percentage_and_guarantees_boundaries(self):
        self.bot._random.random = lambda: self.fail("boundary chance consumed randomness")
        self.assertFalse(self.bot.chance(0))
        self.assertTrue(self.bot.chance(100))
        for percentage in (-1, 101, float("nan")):
            with self.subTest(percentage=percentage):
                with self.assertRaises(ValueError):
                    self.bot.chance(percentage)

    def test_run_with_chance_only_calls_action_when_selected(self):
        calls = []

        self.assertIsNone(self.bot.run_with_chance(0, calls.append, "skipped"))
        result = self.bot.run_with_chance(100, lambda value: value * 2, 4)

        self.assertEqual(result, 8)
        self.assertEqual(calls, [])
        with self.assertRaises(TypeError):
            self.bot.run_with_chance(50, "not callable")

    def test_human_like_and_fast_modes_are_easy_to_toggle(self):
        self.assertIs(self.bot.set_human_like(), self.bot)
        self.assertEqual(self.bot.state, ScreenBot.HUMAN_LIKE)
        self.assertTrue(self.bot.is_human_like)

        self.assertIs(self.bot.set_fast(), self.bot)
        self.assertEqual(self.bot.state, ScreenBot.DEFAULT)
        self.assertFalse(self.bot.is_human_like)

    def test_using_state_temporarily_switches_modes(self):
        self.bot.set_fast()

        with self.bot.using_state(ScreenBot.HUMAN_LIKE):
            self.assertTrue(self.bot.is_human_like)

        self.assertFalse(self.bot.is_human_like)

    def test_human_like_typing_corrects_mistakes_and_remains_accurate(self):
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(
            state=ScreenBot.HUMAN_LIKE,
            backend=backend,
            sleeper=sleeper,
            seed=7,
        )
        bot.configure_human_like(
            pause=(0, 0),
            key_interval=(0.01, 0.02),
            typo_pause=(0.03, 0.04),
            typo_chance=1,
        )

        self.assertEqual(bot.write("Ab "), "Ab ")

        typed = ""
        for item in backend.method_calls:
            if item[0] == "write":
                typed += item.args[0]
            elif item == unittest.mock.call.press("backspace"):
                typed = typed[:-1]
        self.assertEqual(typed, "Ab ")
        self.assertEqual(
            [item for item in backend.method_calls if item == unittest.mock.call.press("backspace")],
            [unittest.mock.call.press("backspace")] * 2,
        )
        self.assertGreaterEqual(sleeper.call_count, 7)

    def test_fast_typing_is_direct_and_does_not_make_mistakes(self):
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(backend=backend, sleeper=sleeper).set_fast()
        bot.configure_human_like(typo_chance=1)

        self.assertEqual(bot.write("accurate"), "accurate")

        backend.write.assert_called_once_with("accurate", interval=0)
        sleeper.assert_not_called()

    def test_human_typing_configuration_is_validated(self):
        bot = ScreenBot(backend=Mock())

        for chance in (-0.1, 1.1):
            with self.subTest(chance=chance), self.assertRaises(ValueError):
                bot.configure_human_like(typo_chance=chance)

    def test_exact_default_wait_runs_once_after_each_action(self):
        backend = Mock()
        sleeper = Mock()
        bot = ScreenBot(backend=backend, sleeper=sleeper)

        self.assertIs(bot.set_wait_time(3), bot)
        bot.click((10, 20))
        bot.write("hello")

        self.assertEqual(sleeper.call_args_list, [unittest.mock.call(3.0)] * 2)

    def test_random_default_wait_uses_configured_range(self):
        sleeper = Mock()
        bot = ScreenBot(backend=Mock(), sleeper=sleeper)
        bot._random.uniform = Mock(return_value=4.25)

        bot.set_wait_time(3, 5).press("enter")

        bot._random.uniform.assert_called_once_with(3.0, 5.0)
        self.assertEqual(
            sleeper.call_args_list,
            [
                unittest.mock.call(0.05),
                unittest.mock.call(0.05),
                unittest.mock.call(4.25),
            ],
        )

    def test_wait_actions_do_not_include_the_default_wait(self):
        sleeper = Mock()
        bot = ScreenBot(backend=Mock(), sleeper=sleeper).set_wait_time(3, 5)
        bot._random.uniform = Mock(return_value=4.0)

        self.assertEqual(bot.wait(2), 2.0)
        self.assertEqual(bot.wait_random(6, 8), 4.0)

        self.assertEqual(
            sleeper.call_args_list,
            [unittest.mock.call(2.0), unittest.mock.call(4.0)],
        )
        bot._random.uniform.assert_called_once_with(6.0, 8.0)

    def test_composite_action_only_adds_one_default_wait(self):
        backend = Mock()
        backend.size.return_value = SimpleNamespace(width=1920, height=1080)
        sleeper = Mock()
        bot = ScreenBot(backend=backend, sleeper=sleeper).set_wait_time(1)

        bot.click_center()

        sleeper.assert_called_once_with(1.0)

    def test_zero_default_wait_disables_action_delay(self):
        sleeper = Mock()
        bot = ScreenBot(backend=Mock(), sleeper=sleeper).set_wait_time(0)

        bot.press("enter")

        self.assertEqual(
            sleeper.call_args_list,
            [unittest.mock.call(0.05), unittest.mock.call(0.05)],
        )

    def test_dry_run_does_not_include_the_default_wait(self):
        sleeper = Mock()
        bot = ScreenBot(backend=Mock(), sleeper=sleeper).set_wait_time(3)

        bot.click((10, 20), dry_run=True)

        sleeper.assert_not_called()

    def test_default_wait_range_is_validated(self):
        bot = ScreenBot(backend=Mock())

        for values in ((-1,), (5, 3)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                bot.set_wait_time(*values)

    def test_capture_box_samples_pointer_on_zero_key_presses(self):
        positions = iter([(8, 9), (2, 7), (3, 1), (10, 4)])
        self.bot._backend.position = lambda: FakePoint(*next(positions))

        class FakeListener:
            def __init__(self, *, on_press):
                self.on_press = on_press

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def join(self):
                self.on_press(SimpleNamespace(char="x"))
                for _ in range(4):
                    self.on_press(SimpleNamespace(char="0"))

        with patch("screenbot.keyboard.Listener", FakeListener):
            box = self.bot.capture_box_on_key(announce=False)

        self.assertEqual(box.as_region_tuple(), (2, 1, 8, 8))

    def test_capture_position_samples_pointer_on_zero_key_press(self):
        class FakeListener:
            def __init__(self, *, on_press):
                self.on_press = on_press

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def join(self):
                self.on_press(SimpleNamespace(char="x"))
                self.on_press(SimpleNamespace(char="0"))

        with patch("screenbot.keyboard.Listener", FakeListener):
            point = self.bot.capture_position_on_key(announce=False)

        self.assertEqual(point.as_tuple(), (12, 34))

    @patch("screenbot_cli.ScreenBot")
    def test_mouse_cli_prints_each_zero_captured_position(self, bot_type):
        bot = bot_type.return_value
        bot.capture_position_on_key.side_effect = [
            ScreenBot.Point(12, 34),
            ScreenBot.Point(56, 78),
            KeyboardInterrupt,
        ]
        output = io.StringIO()

        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["mouse"]), 0)

        self.assertEqual(output.getvalue(), "12 34\n56 78\n")
        self.assertEqual(bot.capture_position_on_key.call_count, 3)

    @patch("screenbot_cli.ScreenBot")
    def test_system_cli_prints_system_id(self, bot_type):
        bot_type.return_value.system_id = "workstation-a"
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertEqual(main(["system"]), 0)

        self.assertEqual(output.getvalue(), "workstation-a\n")

    @patch("screenbot_cli.ScreenBot")
    def test_pixel_cli_waits_for_zero_capture_without_explicit_coordinates(self, bot_type):
        bot = bot_type.return_value
        point = ScreenBot.Point(12, 34)
        bot.capture_position_on_key.return_value = point
        bot.pixel_color.return_value = (10, 20, 30)
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertEqual(main(["pixel"]), 0)

        bot.capture_position_on_key.assert_called_once_with()
        bot.pixel_color.assert_called_once_with(point)
        self.assertEqual(output.getvalue(), "#0A141E 10 20 30\n")

    def test_image_color_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "colors.png"
            Image.new("RGB", (2, 1), (10, 20, 30)).save(path)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["colors", str(path), "--limit", "1"]), 0)
            self.assertEqual(output.getvalue(), "#0A141E 10 20 30 2 100.0000%\n")


if __name__ == "__main__":
    unittest.main()
